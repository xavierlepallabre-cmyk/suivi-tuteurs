'use strict';
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const periods = {'matin':'Matin · 8 h–12 h','apres-midi':'Après-midi · 13 h–17 h'};
const statuses = {pending:'À valider',approved:'Confirmé',rejected:'Refusé',cancelled:'Annulé'};
const modes = {site:'Visite sur site',visio:'Visioconférence',telephone:'Téléphone'};
const weekdays = ['Lundi','Mardi','Mercredi','Jeudi','Vendredi','Samedi','Dimanche'];
let state, currentTab = 'appointments', portalToken = '';
let fragment = new URLSearchParams(location.hash.slice(1));
if (fragment.has('tuteur')) { portalToken = fragment.get('tuteur'); history.replaceState(null, '', location.pathname); }
fragment = null;
async function api(path, data) {
  const response = await fetch('/api/' + path, data === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json','X-Suivi-Request':'1'},body:JSON.stringify(data)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Connexion impossible.');
  return result;
}
function notify(message) { $('#notice').textContent = message; $('#notice').hidden = false; clearTimeout(notify.timer); notify.timer = setTimeout(() => $('#notice').hidden = true, 6500); }
function dateLabel(day) { return new Date(day + 'T12:00:00').toLocaleDateString('fr-FR',{weekday:'long',day:'numeric',month:'long',year:'numeric'}); }
function formData(form) { return Object.fromEntries(new FormData(form)); }
function field(label, name, type='text', required=false) { return `<label>${label}<input name="${name}" type="${type}" maxlength="300" ${required?'required':''}></label>`; }
function bindForm(id, fn) { $(id).addEventListener('submit', async e => { e.preventDefault(); const button = e.target.querySelector('button[type="submit"]'); if(button)button.disabled=true; try { await fn(formData(e.target), e.target); } catch(error) { notify(error.message); } finally { if(button)button.disabled=false; } }); }
function appointment(item, admin=false) {
  return `<article class="item"><div class="item-head"><div><h3>${admin?esc(item.name):esc(modes[item.mode])}</h3><div class="date">${esc(dateLabel(item.day))}</div></div><span class="tag ${esc(item.status)}">${esc(statuses[item.status])}</span></div><p>${esc(periods[item.period])} · ${esc(modes[item.mode])}${admin?'\n'+esc(item.company)+(item.address?'\n'+esc(item.address):''):''}</p>${item.note?`<p>${esc(item.note)}</p>`:''}${admin?`<div class="actions">${item.status==='pending'?`<button class="primary" data-decision="approved" data-id="${esc(item.id)}">Valider</button><button data-decision="rejected" data-id="${esc(item.id)}">Refuser</button>`:''}${item.status==='approved'?`<button class="danger" data-decision="cancelled" data-id="${esc(item.id)}">Annuler le rendez-vous</button>`:''}</div>`:''}</article>`;
}
async function load() { state = await api('state'); $('#logout').hidden = false; render(); }
function login() {
  $('#logout').hidden = true;
  $('#app').innerHTML = `<section class="login"><div class="intro"><span class="eyebrow">ESPACE ENSEIGNANT</span><h1>Organiser les rencontres.</h1><p>Apprentis, tuteurs et rendez-vous, réunis au même endroit.</p></div><div class="card"><h2>Connexion</h2><form id="login-form"><label>Mot de passe<input type="password" name="password" required autocomplete="current-password" maxlength="1000"></label><button type="submit" class="primary wide">Accéder à mon espace</button></form><p class="helper">Tuteur ? Utilisez le lien personnel transmis par l’enseignant.</p></div></section>`;
  bindForm('#login-form', async data => { await api('login',data); await load(); });
}
function render() {
  const pending = state.appointments.filter(x=>x.status==='pending');
  $('#app').innerHTML = `<div class="intro"><span class="eyebrow">MON ESPACE DE SUIVI</span><h1>Les rencontres se préparent ici.</h1><p>Gardez le lien avec les entreprises et validez chaque rendez-vous.</p></div><section class="metrics"><div class="metric"><strong>${state.apprentices.length}</strong><span>Apprentis suivis</span></div><div class="metric"><strong>${pending.length}</strong><span>Demandes à valider</span></div><div class="metric"><strong>${state.appointments.filter(x=>x.status==='approved').length}</strong><span>Rendez-vous confirmés</span></div></section><nav class="tabs" aria-label="Rubriques"><button data-tab="appointments">Rendez-vous ${pending.length?'('+pending.length+')':''}</button><button data-tab="apprentices">Apprentis & tuteurs</button><button data-tab="availability">Disponibilités</button></nav><div id="content"></div>`;
  document.querySelectorAll('[data-tab]').forEach(button => { button.classList.toggle('active',button.dataset.tab===currentTab); button.onclick=()=>{currentTab=button.dataset.tab;render();}; });
  if(currentTab==='appointments') renderAppointments();
  if(currentTab==='apprentices') renderApprentices();
  if(currentTab==='availability') renderAvailability();
}
function renderAppointments() {
  const pending = state.appointments.filter(x=>x.status==='pending');
  const others = state.appointments.filter(x=>x.status!=='pending');
  $('#content').innerHTML = `<div class="columns"><section class="card"><h2>Demandes en attente</h2><p class="helper">Une demande ne réserve pas la demi-journée. La validation bloque le créneau et vérifie les conflits.</p>${pending.map(x=>appointment(x,true)).join('')||'<p class="empty">Aucune demande en attente.</p>'}</section><section class="card"><h2>Planning & historique</h2>${others.map(x=>appointment(x,true)).join('')||'<p class="empty">Les rendez-vous traités apparaîtront ici.</p>'}</section></div>`;
  document.querySelectorAll('[data-decision]').forEach(button=>button.onclick=async()=>{if(button.dataset.decision==='cancelled'&&!confirm('Annuler ce rendez-vous ? Le tuteur verra le changement dans son portail.'))return;button.disabled=true;try{await api('decision',{id:button.dataset.id,status:button.dataset.decision});await load();notify('Décision enregistrée.');}catch(e){notify(e.message);button.disabled=false;}});
}
function showLinks(items) {
  $('#link-list').innerHTML = items.map(item=>`<div class="linkbox"><strong>${esc(item.name)}</strong><input readonly aria-label="Lien personnel de ${esc(item.name)}" value="${esc(location.origin+'/#tuteur='+item.token)}"><button class="copy">Copier le lien</button></div>`).join('');
  $('#links').showModal();
  document.querySelectorAll('.copy').forEach(button=>button.onclick=async()=>{const input=button.previousElementSibling;input.select();try{await navigator.clipboard.writeText(input.value);notify('Lien copié.');}catch{notify('Lien sélectionné : utilisez Copier.');}});
}
function renderApprentices() {
  $('#content').innerHTML = `<div class="columns"><section class="card"><div class="split"><h2>Apprentis & entreprises</h2><span class="tag">${state.apprentices.length}</span></div><label>Rechercher<input id="search" class="search" placeholder="Nom, entreprise, classe…"></label><div id="apprentice-list"></div></section><div class="stack"><section class="card"><h2 id="apprentice-form-title">Ajouter un apprenti</h2><form id="add-form"><input name="id" type="hidden"><div class="grid">${field('Nom et prénom','name','text',true)}${field('Classe','class_name')}${field('Entreprise','company')}${field('Tuteur','tutor')}${field('Email du tuteur','email','email')}${field('Adresse de visite','address')}</div><button type="submit" class="primary">Créer et obtenir le lien</button><button type="button" id="cancel-edit" hidden>Annuler la modification</button></form></section><section class="card"><h2>Importer une liste</h2><p class="helper">CSV UTF-8 (virgule ou point-virgule) ou Excel .xlsx, première feuille. 500 lignes maximum. L’import ajoute des apprentis ; il ne met pas à jour ceux qui existent.</p><p class="helper">Colonnes : <strong>nom, classe, entreprise, tuteur, email, adresse</strong>. Seule la colonne nom est obligatoire.</p><form id="import-form"><label>Fichier<input name="file" type="file" accept=".csv,.xlsx" required></label><button type="submit">Importer et obtenir les liens</button></form></section></div></div>`;
  const list=()=>{
    const query=$('#search').value.toLocaleLowerCase();
    $('#apprentice-list').innerHTML=state.apprentices.filter(x=>[x.name,x.company,x.class_name,x.tutor].join(' ').toLocaleLowerCase().includes(query)).map(x=>`<article class="item"><div class="item-head"><h3>${esc(x.name)}</h3><span class="tag">${esc(x.class_name||'Sans classe')}</span></div><p>${esc(x.company||'Entreprise à renseigner')}${x.tutor?'\nTuteur : '+esc(x.tutor):''}${x.email?'\n'+esc(x.email):''}${x.address?'\n'+esc(x.address):''}</p><div class="actions"><button data-edit="${esc(x.id)}">Modifier la fiche</button><button data-rotate="${esc(x.id)}">Renouveler le lien personnel</button></div></article>`).join('')||'<p class="empty">Aucun apprenti à afficher.</p>';
    document.querySelectorAll('[data-edit]').forEach(button=>button.onclick=()=>{const item=state.apprentices.find(x=>x.id===button.dataset.edit);const form=$('#add-form');Object.entries(item).forEach(([key,value])=>{if(form.elements.namedItem(key))form.elements.namedItem(key).value=value;});$('#apprentice-form-title').textContent='Modifier la fiche';form.querySelector('button[type="submit"]').textContent='Enregistrer les modifications';$('#cancel-edit').hidden=false;form.scrollIntoView({behavior:'smooth',block:'center'});});
    document.querySelectorAll('[data-rotate]').forEach(button=>button.onclick=async()=>{if(!confirm('Le lien précédent cessera de fonctionner. Créer un nouveau lien ?'))return;try{const result=await api('rotate',{id:button.dataset.rotate});showLinks([{name:state.apprentices.find(x=>x.id===button.dataset.rotate).name,token:result.token}]);}catch(e){notify(e.message);}});
  };
  $('#search').oninput=list;list();
  $('#cancel-edit').onclick=renderApprentices;
  bindForm('#add-form',async data=>{if(data.id){await api('apprentices/update',data);await load();notify('Fiche mise à jour.');}else{const result=await api('apprentices',data);await load();showLinks([result]);}});
  bindForm('#import-form',async(_,form)=>{const file=form.querySelector('input').files[0];if(file.size>2000000)throw new Error('Fichier limité à 2 Mo.');const bytes=new Uint8Array(await file.arrayBuffer());let binary='';for(const byte of bytes)binary+=String.fromCharCode(byte);const result=await api('import',{filename:file.name,content:btoa(binary)});await load();showLinks(result.created);notify(result.created.length+' apprentis importés.');});
}
function renderAvailability() {
  $('#content').innerHTML=`<div class="columns"><section class="card"><h2>Ouvrir une demi-journée</h2><div class="banner">Les visites sur site bloquent toute la demi-journée, déplacements compris. En v0.1, les appels et visios réservent également une demi-journée : l’heure précise est à convenir avec le tuteur.</div><form id="availability-form"><label>Type<select name="kind" id="availability-kind"><option value="weekly">Chaque semaine</option><option value="date">Une date précise</option></select></label><label id="day-label">Jour<select name="day">${weekdays.map((day,i)=>`<option value="${i}">${day}</option>`).join('')}</select></label><label>Demi-journée<select name="period">${Object.entries(periods).map(([key,value])=>`<option value="${key}">${value}</option>`).join('')}</select></label><button type="submit" class="primary">Ajouter la disponibilité</button></form><p class="helper">Les tuteurs voient les 90 prochains jours. Retirer une disponibilité ne supprime pas les rendez-vous déjà confirmés.</p></section><section class="card"><h2>Disponibilités ouvertes</h2>${state.availability.map(x=>`<article class="item"><h3>${esc(x.kind==='weekly'?'Chaque '+weekdays[Number(x.day)].toLowerCase():dateLabel(x.day))}</h3><p>${esc(periods[x.period])}</p><button data-remove="${esc(x.id)}">Retirer</button></article>`).join('')||'<p class="empty">Ajoutez vos disponibilités pour ouvrir la prise de rendez-vous.</p>'}</section></div>`;
  $('#availability-kind').onchange=e=>{$('#day-label').innerHTML=e.target.value==='date'?'Date<input type="date" name="day" required>':`Jour<select name="day">${weekdays.map((day,i)=>`<option value="${i}">${day}</option>`).join('')}</select>`;};
  bindForm('#availability-form',async data=>{await api('availability',data);await load();notify('Disponibilité ajoutée.');});
  document.querySelectorAll('[data-remove]').forEach(button=>button.onclick=async()=>{try{await api('availability/delete',{id:button.dataset.remove});await load();}catch(e){notify(e.message);}});
}
async function portal() {
  $('#logout').hidden=true;
  try {
    const result=await api('portal',{token:portalToken});
    $('#app').innerHTML=`<section class="portal"><span class="eyebrow">ESPACE TUTEUR</span><h1>Préparons notre prochain échange.</h1><p>Suivi de <strong>${esc(result.name)}</strong> · ${esc(result.company)}</p><div class="banner">Chaque rendez-vous est soumis à la validation de l’enseignant. Consultez ce portail pour connaître sa réponse. Aucun email automatique n’est envoyé.</div><section class="card"><h2>Proposer un rendez-vous</h2>${result.appointments.some(x=>x.status==='pending')?'<p>Votre demande est en attente de validation.</p>':result.slots.length?`<form id="request-form"><label>Demi-journée souhaitée<select name="slot">${result.slots.map((slot,i)=>`<option value="${i}">${esc(dateLabel(slot.day)+' — '+periods[slot.period])}</option>`).join('')}</select></label><label>Format<select name="mode">${Object.entries(modes).map(([k,v])=>`<option value="${k}">${v}</option>`).join('')}</select></label><label>Informations complémentaires<textarea name="note" maxlength="1000" placeholder="Lieu, accès, sujets à aborder…"></textarea></label><p class="helper">La visite sur site mobilise toute la demi-journée. Pour un appel ou une visio, l’heure précise sera convenue avec l’enseignant.</p><button type="submit" class="primary">Envoyer la demande</button></form>`:'<p class="empty">Aucune disponibilité pour le moment. Contactez l’enseignant.</p>'}</section><section class="card"><div class="split"><h2>Vos rendez-vous</h2><button id="refresh">Actualiser</button></div>${result.appointments.map(x=>appointment(x)).join('')||'<p class="empty">Vous n’avez pas encore proposé de rendez-vous.</p>'}</section><p class="helper">Conservez votre lien personnel pour revenir sur cette page. Pour modifier ou annuler une demande, contactez l’enseignant.</p></section>`;
    $('#refresh').onclick=portal;
    if($('#request-form'))bindForm('#request-form',async data=>{const slot=result.slots[Number(data.slot)];await api('request',{token:portalToken,...slot,mode:data.mode,note:data.note});await portal();notify('Demande transmise à l’enseignant.');});
  }catch(e){$('#app').innerHTML=`<section class="login card"><h1>Accès au portail</h1><p>${esc(e.message)}</p><p>Rouvrez le lien personnel transmis par l’enseignant.</p></section>`;}
}
$('#close-links').onclick=()=>{$('#links').close();$('#link-list').replaceChildren();};
$('#links').addEventListener('cancel',()=>$('#link-list').replaceChildren());
$('#logout').onclick=async()=>{try{await api('logout',{});state=null;login();}catch(e){notify(e.message);}};
if(portalToken)portal();else load().catch(()=>login());
