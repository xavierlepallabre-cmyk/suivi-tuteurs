import argparse
import base64
import csv
import getpass
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parent
DB = Path(os.environ.get('SUIVI_DB', ROOT / 'data' / 'suivi.sqlite3'))
TZ = ZoneInfo('Europe/Paris')
SECURE = os.environ.get('COOKIE_SECURE', '0') == '1'
ATTEMPTS = {}

class Invalid(Exception):
    pass

def connect():
    db = sqlite3.connect(DB, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    return db

def initialize():
    DB.parent.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY,expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS apprentices(id TEXT PRIMARY KEY,name TEXT NOT NULL,class_name TEXT NOT NULL,company TEXT NOT NULL,tutor TEXT NOT NULL,email TEXT NOT NULL,address TEXT NOT NULL,token_hash TEXT UNIQUE NOT NULL);
        CREATE TABLE IF NOT EXISTS availability(id TEXT PRIMARY KEY,kind TEXT NOT NULL,day TEXT NOT NULL,period TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS appointments(id TEXT PRIMARY KEY,apprentice_id TEXT NOT NULL REFERENCES apprentices(id),day TEXT NOT NULL,period TEXT NOT NULL,mode TEXT NOT NULL,status TEXT NOT NULL,note TEXT NOT NULL,created TEXT NOT NULL);
        ''')
    try:
        os.chmod(DB.parent, 0o700)
        os.chmod(DB, 0o600)
    except OSError:
        pass

def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()

def set_password(password):
    if len(password) < 12:
        raise Invalid('Le mot de passe doit contenir au moins 12 caractères.')
    salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 600000).hex()
    with connect() as db:
        db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', ('password', salt + ':' + hashed))
        db.execute('DELETE FROM sessions')

def clean(value, maximum=300):
    return str(value or '').strip()[:maximum]

def valid_day(value):
    try:
        result = date.fromisoformat(value)
    except (ValueError, TypeError):
        raise Invalid('Date invalide.')
    today = datetime.now(TZ).date()
    if not today <= result <= today + timedelta(days=180):
        raise Invalid('Choisir une date dans les 180 prochains jours.')
    return result

def available(db, day, period):
    d = valid_day(day)
    if period not in ('matin', 'apres-midi'):
        raise Invalid('Demi-journée invalide.')
    start_hour = 8 if period == 'matin' else 13
    if datetime.combine(d, datetime.min.time(), TZ).replace(hour=start_hour) <= datetime.now(TZ):
        return False
    return bool(db.execute('SELECT 1 FROM availability WHERE period=? AND ((kind="date" AND day=?) OR (kind="weekly" AND day=?))', (period, day, str(d.weekday()))).fetchone())

def free(db, day, period, exclude=''):
    return not db.execute('SELECT 1 FROM appointments WHERE day=? AND period=? AND status="approved" AND id!=?', (day, period, exclude)).fetchone()

def slots(db):
    result = []
    today = datetime.now(TZ).date()
    for offset in range(90):
        day = (today + timedelta(days=offset)).isoformat()
        for period in ('matin', 'apres-midi'):
            if available(db, day, period) and free(db, day, period):
                result.append({'day': day, 'period': period})
    return result

def create_apprentice(db, row):
    token = secrets.token_urlsafe(32)
    name = clean(row.get('name'))
    if not name:
        raise Invalid('Le nom de l’apprenti est obligatoire.')
    ident = secrets.token_hex(12)
    values = [clean(row.get(key)) for key in ('class_name', 'company', 'tutor', 'email', 'address')]
    db.execute('INSERT INTO apprentices VALUES (?,?,?,?,?,?,?,?)', (ident, name, *values, digest(token)))
    return {'id': ident, 'name': name, 'token': token}

def import_rows(filename, raw):
    if filename.lower().endswith('.csv'):
        text = raw.decode('utf-8-sig')
        delimiter = ';' if text.partition('\n')[0].count(';') >= text.partition('\n')[0].count(',') else ','
        rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    elif filename.lower().endswith('.xlsx'):
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            if sum(x.file_size for x in archive.infolist()) > 20000000:
                raise Invalid('Classeur trop volumineux.')
            ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            strings = []
            if 'xl/sharedStrings.xml' in archive.namelist():
                strings = [''.join(x.itertext()) for x in ET.fromstring(archive.read('xl/sharedStrings.xml')).findall('s:si', ns)]
            sheet = ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
            rows = []
            for r in sheet.findall('s:sheetData/s:row', ns):
                values = {}
                for cell in r.findall('s:c', ns):
                    col = 0
                    for char in cell.attrib.get('r', ''):
                        if char.isalpha():
                            col = col * 26 + ord(char.upper()) - 64
                    if not 1 <= col <= 30:
                        continue
                    val = cell.find('s:v', ns)
                    value = val.text if val is not None else ''
                    if cell.attrib.get('t') == 's':
                        value = strings[int(value)]
                    elif cell.attrib.get('t') == 'inlineStr':
                        value = ''.join(cell.find('s:is', ns).itertext())
                    values[col - 1] = value
                rows.append([values.get(i, '') for i in range(max(values, default=-1) + 1)])
    else:
        raise Invalid('Utiliser un fichier CSV UTF-8 ou Excel .xlsx.')
    if not rows or len(rows) > 501:
        raise Invalid('Importer entre 1 et 500 apprentis.')
    headers = [clean(x).lower() for x in rows[0]]
    required = ['nom', 'classe', 'entreprise', 'tuteur', 'email', 'adresse']
    if 'nom' not in headers or any(x not in required for x in headers):
        raise Invalid('En-têtes attendus : nom;classe;entreprise;tuteur;email;adresse')
    mapping = dict(zip(required, ('name', 'class_name', 'company', 'tutor', 'email', 'address')))
    result = []
    for row in rows[1:]:
        if any(clean(x) for x in row):
            result.append({mapping[k]: row[i] if i < len(row) else '' for i, k in enumerate(headers)})
    if not result:
        raise Invalid('Aucun apprenti dans le fichier.')
    return result

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def send(self, status, data, cookie=None, mime='application/json; charset=utf-8'):
        body = json.dumps(data, ensure_ascii=False).encode() if mime.startswith('application/json') else data
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if cookie:
            self.send_header('Set-Cookie', cookie)
        self.end_headers()
        self.wfile.write(body)

    def cookie(self, token, age=28800):
        return f'suivi_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={age}' + ('; Secure' if SECURE else '')

    def teacher(self, db):
        cookies = dict(x.strip().split('=', 1) for x in self.headers.get('Cookie', '').split(';') if '=' in x)
        return bool(db.execute('SELECT 1 FROM sessions WHERE hash=? AND expires>?', (digest(cookies.get('suivi_session', '')), time.time())).fetchone())

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/api/state':
            with connect() as db:
                if not self.teacher(db):
                    return self.send(401, {'error': 'Connexion requise.'})
                result = {'apprentices': [dict(x) for x in db.execute('SELECT id,name,class_name,company,tutor,email,address FROM apprentices ORDER BY name')], 'availability': [dict(x) for x in db.execute('SELECT * FROM availability ORDER BY kind,day,period')], 'appointments': [dict(x) for x in db.execute('SELECT appointments.*,apprentices.name,apprentices.company,apprentices.address FROM appointments JOIN apprentices ON apprentices.id=apprentice_id ORDER BY day,period')], 'slots': slots(db)}
                return self.send(200, result)
        names = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/style.css': ('style.css', 'text/css; charset=utf-8')}
        if path not in names:
            return self.send(404, {'error': 'Page introuvable.'})
        filename, mime = names[path]
        self.send(200, (ROOT / 'static' / filename).read_bytes(), mime=mime)

    def do_POST(self):
        try:
            if self.headers.get('X-Suivi-Request') != '1':
                return self.send(403, {'error': 'Requête refusée.'})
            origin = self.headers.get('Origin')
            expected = os.environ.get('PUBLIC_ORIGIN')
            if origin and origin != (expected or ('http://' + self.headers.get('Host', ''))):
                return self.send(403, {'error': 'Origine refusée.'})
            length = int(self.headers.get('Content-Length', 0))
            if not 0 < length <= 3000000:
                raise Invalid('Requête vide ou trop volumineuse.')
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise Invalid('Requête invalide.')
            with connect() as db:
                db.execute('BEGIN IMMEDIATE')
                self.dispatch(db, urlsplit(self.path).path, data)
        except Invalid as exc:
            self.send(400, {'error': str(exc)})
        except (ValueError, KeyError, TypeError, UnicodeError, zipfile.BadZipFile, ET.ParseError, IndexError):
            self.send(400, {'error': 'Données invalides. Vérifier le formulaire ou le fichier.'})
        except Exception:
            self.send(500, {'error': 'Erreur interne. Réessayer.'})

    def dispatch(self, db, path, data):
        if path == '/api/login':
            ip = self.client_address[0]
            now = time.time()
            ATTEMPTS[ip] = [t for t in ATTEMPTS.get(ip, []) if t > now - 900]
            if len(ATTEMPTS[ip]) >= 8:
                return self.send(429, {'error': 'Trop de tentatives. Réessayer dans 15 minutes.'})
            row = db.execute('SELECT value FROM settings WHERE key="password"').fetchone()
            if not row:
                return self.send(503, {'error': 'Créer le mot de passe sur le serveur : python server.py --set-password'})
            salt, stored = row[0].split(':')
            given = hashlib.pbkdf2_hmac('sha256', clean(data.get('password'), 1000).encode(), salt.encode(), 600000).hex()
            if not hmac.compare_digest(stored, given):
                ATTEMPTS[ip].append(now)
                return self.send(401, {'error': 'Mot de passe incorrect.'})
            ATTEMPTS.pop(ip, None)
            token = secrets.token_urlsafe(32)
            db.execute('DELETE FROM sessions WHERE expires<=?', (now,))
            db.execute('INSERT INTO sessions VALUES (?,?)', (digest(token), now + 28800))
            db.commit()
            return self.send(200, {'ok': True}, self.cookie(token))
        if path in ('/api/portal', '/api/request'):
            apprentice = db.execute('SELECT * FROM apprentices WHERE token_hash=?', (digest(clean(data.get('token'), 100)),)).fetchone()
            if not apprentice:
                return self.send(401, {'error': 'Lien invalide ou révoqué. Contacter l’enseignant.'})
            if path == '/api/portal':
                return self.send(200, {'name': apprentice['name'], 'company': apprentice['company'], 'slots': slots(db), 'appointments': [dict(x) for x in db.execute('SELECT day,period,mode,status,note FROM appointments WHERE apprentice_id=? ORDER BY day', (apprentice['id'],))]})
            day, period = data.get('day'), data.get('period')
            if not available(db, day, period) or not free(db, day, period):
                raise Invalid('Cette demi-journée n’est plus disponible.')
            mode = data.get('mode')
            if mode not in ('site', 'visio', 'telephone'):
                raise Invalid('Mode de rendez-vous invalide.')
            if db.execute('SELECT 1 FROM appointments WHERE apprentice_id=? AND status="pending"', (apprentice['id'],)).fetchone():
                raise Invalid('Une demande est déjà en attente pour cet apprenti.')
            db.execute('INSERT INTO appointments VALUES (?,?,?,?,?,?,?,?)', (secrets.token_hex(12), apprentice['id'], day, period, mode, 'pending', clean(data.get('note'), 1000), datetime.now(TZ).isoformat()))
            db.commit()
            return self.send(201, {'ok': True})
        if not self.teacher(db):
            return self.send(401, {'error': 'Connexion requise.'})
        if path == '/api/logout':
            cookies = dict(x.strip().split('=', 1) for x in self.headers.get('Cookie', '').split(';') if '=' in x)
            db.execute('DELETE FROM sessions WHERE hash=?', (digest(cookies.get('suivi_session', '')),))
            db.commit()
            return self.send(200, {'ok': True}, self.cookie('', 0))
        if path == '/api/apprentices':
            result = create_apprentice(db, data)
        elif path == '/api/apprentices/update':
            name = clean(data.get('name'))
            if not name:
                raise Invalid('Le nom de l’apprenti est obligatoire.')
            values = [clean(data.get(key)) for key in ('name', 'class_name', 'company', 'tutor', 'email', 'address')]
            cur = db.execute('UPDATE apprentices SET name=?,class_name=?,company=?,tutor=?,email=?,address=? WHERE id=?', (*values, data.get('id')))
            if not cur.rowcount:
                raise Invalid('Apprenti introuvable.')
            result = {'ok': True}
        elif path == '/api/import':
            raw = base64.b64decode(data.get('content', ''), validate=True)
            rows = import_rows(clean(data.get('filename')), raw)
            result = {'created': [create_apprentice(db, row) for row in rows]}
        elif path == '/api/rotate':
            token = secrets.token_urlsafe(32)
            cur = db.execute('UPDATE apprentices SET token_hash=? WHERE id=?', (digest(token), data.get('id')))
            if not cur.rowcount:
                raise Invalid('Apprenti introuvable.')
            result = {'token': token}
        elif path == '/api/availability':
            kind, day, period = data.get('kind'), clean(data.get('day')), data.get('period')
            if kind == 'date':
                valid_day(day)
            elif kind != 'weekly' or day not in tuple(str(x) for x in range(7)):
                raise Invalid('Disponibilité invalide.')
            if period not in ('matin', 'apres-midi'):
                raise Invalid('Demi-journée invalide.')
            if not db.execute('SELECT 1 FROM availability WHERE kind=? AND day=? AND period=?', (kind, day, period)).fetchone():
                db.execute('INSERT INTO availability VALUES (?,?,?,?)', (secrets.token_hex(12), kind, day, period))
            result = {'ok': True}
        elif path == '/api/availability/delete':
            db.execute('DELETE FROM availability WHERE id=?', (data.get('id'),))
            result = {'ok': True}
        elif path == '/api/decision':
            row = db.execute('SELECT * FROM appointments WHERE id=?', (data.get('id'),)).fetchone()
            status = data.get('status')
            if not row or status not in ('approved', 'rejected', 'cancelled'):
                raise Invalid('Décision invalide.')
            if status in ('approved', 'rejected') and row['status'] != 'pending':
                raise Invalid('Cette demande a déjà été traitée.')
            if status == 'cancelled' and row['status'] not in ('pending', 'approved'):
                raise Invalid('Ce rendez-vous est déjà clos.')
            if status == 'approved' and (not available(db, row['day'], row['period']) or not free(db, row['day'], row['period'], row['id'])):
                raise Invalid('Conflit : la demi-journée est occupée ou n’est plus ouverte.')
            db.execute('UPDATE appointments SET status=? WHERE id=?', (status, row['id']))
            result = {'ok': True}
        else:
            return self.send(404, {'error': 'Route introuvable.'})
        db.commit()
        self.send(200, result)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--set-password', action='store_true')
    parser.add_argument('--strictPort', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    initialize()
    if args.set_password:
        password = getpass.getpass('Mot de passe enseignant (12 caractères minimum) : ')
        if password != getpass.getpass('Confirmer : '):
            raise SystemExit('Les mots de passe diffèrent.')
        set_password(password)
        print('Mot de passe enregistré. Sessions précédentes révoquées.')
    else:
        print(f'Suivi Tuteurs v0.1 — http://{args.host}:{args.port}')
        ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
