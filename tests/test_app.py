import base64
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from datetime import timedelta, datetime

spec = importlib.util.spec_from_file_location('app', Path(__file__).parents[1] / 'server.py')
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)

class ApplicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        app.DB = Path(cls.temp.name) / 'test.sqlite3'
        app.initialize()
        app.set_password('mot-de-passe-test-123')
        cls.server = app.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.temp.cleanup()

    def call(self, path, data=None, cookie='', custom=True, origin=None):
        headers = {'Content-Type':'application/json'}
        if cookie:
            headers['Cookie'] = cookie
        if custom:
            headers['X-Suivi-Request'] = '1'
        if origin:
            headers['Origin'] = origin
        request = urllib.request.Request(self.base+'/api/'+path, data=None if data is None else json.dumps(data).encode(), headers=headers)
        try:
            response = urllib.request.urlopen(request)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.loads(response.read()), response.headers

    def login(self):
        status, _, headers = self.call('login', {'password':'mot-de-passe-test-123'})
        self.assertEqual(status, 200)
        self.assertIn('HttpOnly', headers['Set-Cookie'])
        self.assertIn('SameSite=Strict', headers['Set-Cookie'])
        return headers['Set-Cookie'].split(';')[0]

    def test_full_lifecycle_and_conflict(self):
        cookie = self.login()
        self.assertEqual(self.call('state')[0], 401)
        self.assertEqual(self.call('apprentices', {'name':'Test'})[0], 401)
        first = self.call('apprentices', {'name':'Apprenti A', 'company':'Entreprise A'}, cookie)[1]
        second = self.call('apprentices', {'name':'Apprenti B'}, cookie)[1]
        day = (datetime.now(app.TZ).date() + timedelta(days=10)).isoformat()
        self.assertEqual(self.call('availability', {'kind':'date','day':day,'period':'matin'},cookie)[0], 200)
        request = {'day':day,'period':'matin','mode':'site','note':'Accès atelier'}
        self.assertEqual(self.call('request',dict(request,token=first['token']))[0], 201)
        self.assertEqual(self.call('request',dict(request,token=first['token']))[0], 400)
        self.assertEqual(self.call('request',dict(request,token=second['token']))[0], 201)
        state = self.call('state',cookie=cookie)[1]
        requests = [x for x in state['appointments'] if x['day']==day]
        self.assertEqual(len(requests), 2)
        self.assertEqual(self.call('decision',{'id':requests[0]['id'],'status':'approved'},cookie)[0],200)
        self.assertEqual(self.call('decision',{'id':requests[1]['id'],'status':'approved'},cookie)[0],400)
        portal = self.call('portal',{'token':first['token']})[1]
        self.assertEqual(portal['name'],'Apprenti A')
        self.assertNotIn('Apprenti B', json.dumps(portal))
        self.assertFalse(any(x['day']==day and x['period']=='matin' for x in portal['slots']))
        self.assertEqual(self.call('decision',{'id':requests[0]['id'],'status':'cancelled'},cookie)[0],200)
        self.assertEqual(self.call('decision',{'id':requests[1]['id'],'status':'approved'},cookie)[0],200)
        rotated = self.call('rotate',{'id':first['id']},cookie)[1]['token']
        self.assertEqual(self.call('portal',{'token':first['token']})[0],401)
        self.assertEqual(self.call('portal',{'token':rotated})[0],200)
        self.assertEqual(self.call('apprentices/update',{'id':first['id'],'name':'Nom corrigé'},cookie)[0],200)
        self.assertEqual(self.call('portal',{'token':rotated})[1]['name'],'Nom corrigé')
        serialized = json.dumps(self.call('state',cookie=cookie)[1])
        self.assertNotIn(rotated,serialized)
        self.assertNotIn('token_hash',serialized)
        with app.connect() as db:
            self.assertNotEqual(db.execute('SELECT value FROM settings WHERE key="password"').fetchone()[0], 'mot-de-passe-test-123')
            self.assertEqual(db.execute('SELECT token_hash FROM apprentices WHERE id=?',(first['id'],)).fetchone()[0],app.digest(rotated))
        self.assertEqual(self.call('logout',{},cookie)[0],200)
        self.assertEqual(self.call('state',cookie=cookie)[0],401)

    def test_csrf_and_invalid_login(self):
        self.assertEqual(self.call('login',{'password':'x'},custom=False)[0],403)
        self.assertEqual(self.call('login',{'password':'x'},origin='https://other.example')[0],403)
        self.assertEqual(self.call('login',{'password':'x'})[0],401)
        self.assertEqual(self.call('portal',{'token':'invalid'})[0],401)

    def test_csv_import_transaction(self):
        cookie=self.login()
        csv='nom;classe;entreprise;tuteur;email;adresse\nÉlève CSV;TIIN;Atelier;Mme Test;t@example.fr;Cherbourg\n'
        status,result,_=self.call('import',{'filename':'liste.csv','content':base64.b64encode(csv.encode()).decode()},cookie)
        self.assertEqual(status,200)
        self.assertEqual(result['created'][0]['name'],'Élève CSV')
        before=len(self.call('state',cookie=cookie)[1]['apprentices'])
        csv='nom;classe\nValide;BTS\n;TIIN\n'
        self.assertEqual(self.call('import',{'filename':'liste.csv','content':base64.b64encode(csv.encode()).decode()},cookie)[0],400)
        self.assertEqual(len(self.call('state',cookie=cookie)[1]['apprentices']),before)

    def test_xlsx_and_recurring(self):
        content=io.BytesIO()
        with zipfile.ZipFile(content,'w') as archive:
            archive.writestr('xl/worksheets/sheet1.xml','''<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>nom</t></is></c><c r="C1" t="inlineStr"><is><t>entreprise</t></is></c></row><row r="2"><c r="A2" t="inlineStr"><is><t>Élève Excel</t></is></c><c r="C2" t="inlineStr"><is><t>Entreprise</t></is></c></row></sheetData></worksheet>''')
        # Empty header columns are rejected to avoid silently misaligned imports.
        with self.assertRaises(app.Invalid):
            app.import_rows('liste.xlsx',content.getvalue())
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w') as archive:
            archive.writestr('xl/sharedStrings.xml', '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>nom</t></si><si><t>Élève Excel</t></si></sst>')
            archive.writestr('xl/worksheets/sheet1.xml', '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c></row><row r="2"><c r="A2" t="s"><v>1</v></c></row></sheetData></worksheet>')
        self.assertEqual(app.import_rows('liste.xlsx',output.getvalue())[0]['name'],'Élève Excel')
        cookie=self.login()
        self.assertEqual(self.call('availability',{'kind':'weekly','day':'1','period':'apres-midi'},cookie)[0],200)
        with app.connect() as db:
            candidates=[x for x in app.slots(db) if app.date.fromisoformat(x['day']).weekday()==1 and x['period']=='apres-midi']
        self.assertGreater(len(candidates),8)

if __name__=='__main__':
    unittest.main()
