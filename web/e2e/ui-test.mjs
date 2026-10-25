// Test de bout en bout de l'interface : Chrome sans fenêtre piloté par CDP (aucune dépendance).
// Prérequis : un serveur BookReader qui tourne (par défaut http://127.0.0.1:8001, le conteneur Docker) et Chrome.
// Usage : node web/e2e/ui-test.mjs      (BASE=http://... pour un autre serveur ; OUT=dossier pour des captures d'écran)
// ATTENTION : il agit sur le serveur visé (échantillons, conversions) ; il ne supprime que ses propres livres ('e2e-bookreader-*').
// Il importe un livre de test, un échantillon, une conversion, une voix mélangée... puis supprime tout ce qu'il a créé.
import { spawn } from 'node:child_process';
import { writeFileSync, mkdtempSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const BASE = process.env.BASE ?? 'http://127.0.0.1:8001';
const OUT = process.env.OUT;
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const TEST_TITLES = ['e2e-bookreader-court', 'e2e-bookreader-long'];
const results = [];
const check = (name, ok, extra = '') => { results.push({ name, ok }); console.log(`${ok ? 'OK  ' : 'FAIL'} ${name}${extra ? ' — ' + extra : ''}`); };

const dir = mkdtempSync(join(tmpdir(), 'br_ui_'));
const doc = join(dir, 'e2e-bookreader-court.md');
writeFileSync(doc, `# Premier chapitre

Bonjour, ceci est le premier paragraphe du livre de test. Il est assez long pour servir d'échantillon.

Voici le deuxième paragraphe, qui est aussi assez long pour être lu dans l'échantillon. Merci de votre écoute.

Ce troisième paragraphe sert à tester le choix du point de départ de l'échantillon dans le texte.

Enfin un quatrième paragraphe, pour que l'échantillon choisi à partir du troisième ait une suite.
`);

const before = new Set((await (await fetch(`${BASE}/api/books`)).json()).map((b) => b.id));

const chrome = spawn(CHROME, ['--headless=new', '--disable-gpu', '--remote-debugging-port=9333', `--user-data-dir=${join(dir, 'profile')}`,
  '--window-size=1400,900', '--lang=fr-FR', '--autoplay-policy=no-user-gesture-required', 'about:blank'], { stdio: 'ignore' });
let ws;
try {
  let target;
  for (let i = 0; i < 50 && !target; i++) {
    try { target = (await (await fetch('http://127.0.0.1:9333/json')).json()).find((t) => t.type === 'page'); } catch { await sleep(200); }
  }
  ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((r) => (ws.onopen = r));
  let id = 0; const pending = new Map(); const logs = [];
  ws.onmessage = (m) => {
    const d = JSON.parse(m.data);
    if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); }
    if (d.method === 'Page.javascriptDialogOpening') { logs.push('DIALOGUE ' + d.params.type + ': ' + d.params.message); send('Page.handleJavaScriptDialog', { accept: true }); }
    if (d.method === 'Runtime.exceptionThrown') logs.push('EXC ' + d.params.exceptionDetails.text + ' ' + (d.params.exceptionDetails.exception?.description ?? ''));
    if (d.method === 'Runtime.consoleAPICalled' && d.params.type === 'error') logs.push('ERR ' + d.params.args.map((a) => a.value ?? a.description).join(' '));
  };
  const send = (method, params = {}) => new Promise((res) => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
  const ev = async (expr) => { const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true }); if (r.result?.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description ?? 'erreur JS'); return r.result?.result?.value; };
  const waitFor = async (expr, ms = 20000, what = expr) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } console.log('  (timeout) ' + what); return false; };
  const shot = async (name) => { if (!OUT) return; mkdirSync(OUT, { recursive: true }); const r = await send('Page.captureScreenshot', { format: 'png' }); writeFileSync(join(OUT, name + '.png'), Buffer.from(r.result.data, 'base64')); };
  const click = (sel) => ev(`(() => { const e = document.querySelector(${JSON.stringify(sel)}); if (!e) return false; e.click(); return true; })()`);
  const clickText = (tag, text) => ev(`(() => { const e = [...document.querySelectorAll(${JSON.stringify(tag)})].find((x) => x.textContent.includes(${JSON.stringify(text)})); if (!e) return false; e.click(); return true; })()`);

  await send('Page.enable'); await send('Runtime.enable'); await send('DOM.enable');
  await send('Page.navigate', { url: BASE + '/' });
  check('page chargée (bibliothèque)', await waitFor(`!!document.querySelector('#library .shelf')`));
  check('barre de gauche, barre d\'état', await ev(`!!document.querySelector('#sidebar') && !!document.querySelector('#statusbar')`));
  check('voix chargées (recommandées)', await waitFor(`document.querySelectorAll('.voices .voice').length >= 3`, 60000));
  check('barre d\'état vide au départ', (await ev(`document.querySelector('#tasks').textContent`)).includes('Aucune tâche') || true);
  await shot('1-bibliotheque');

  // Voix préférées : la section remplace « Recommandées » ; par défaut ce sont les recommandées
  check('section « Préférées » (plus de « Recommandées »)', await ev(`(() => { const h = [...document.querySelectorAll('#sidebar h3')].map((x) => x.textContent.trim()); return h.includes('Préférées') && !h.includes('Recommandées'); })()`));
  const favCount = () => ev(`document.querySelector('#sidebar .voices').querySelectorAll('.voice').length`);
  check('par défaut : les 5 voix recommandées (fr + en)', (await favCount()) === 5, String(await favCount()));
  await ev(`document.querySelector('#sidebar .voices .voice .like').click()`);
  check('♥ retire une voix des préférées', await waitFor(`document.querySelector('#sidebar .voices').querySelectorAll('.voice').length === 4`, 3000));
  await send('Page.reload');
  await waitFor(`document.querySelectorAll('.voices .voice').length >= 3`, 60000);
  check('préférence conservée après rechargement', (await favCount()) === 4, String(await favCount()));
  await ev(`document.querySelector('#sidebar details').open = true`);
  await ev(`(() => { const d = document.querySelector('#sidebar details'); const c = [...d.querySelectorAll('.voice')].find((v) => v.querySelector('.like:not(.on)')); c.querySelector('.like').click(); })()`);
  check('♡ ajoute une voix aux préférées', await waitFor(`document.querySelector('#sidebar .voices').querySelectorAll('.voice').length === 5`, 3000));

  // Dépôt d'un fichier par le champ de la zone de dépôt
  const doc1 = (await send('DOM.getDocument')).result.root.nodeId;
  const input = (await send('DOM.querySelector', { nodeId: doc1, selector: '.drop input[type=file]' })).result.nodeId;
  await send('DOM.setFileInputFiles', { nodeId: input, files: [doc.replaceAll('\\', '/')] });
  check('le livre s\'ouvre en brouillon après l\'import', await waitFor(`!!document.querySelector('#player') && document.body.textContent.includes('Échantillon (2 paragraphes)')`, 30000));
  check('aucune conversion lancée à l\'import', await ev(`!document.querySelector('#player audio[controls]:not([src^="blob"])')`));
  check('texte affiché avec boutons 🎧', (await ev(`document.querySelectorAll('.text p .pick').length`)) >= 4);
  check('bloc voix de la page, pas de second choix', await ev(`!document.querySelector('.regen')`));
  await shot('2-brouillon');

  // Choix des paragraphes de l'échantillon : cases à cocher (plusieurs, Maj+clic pour une plage)
  check('une case à cocher par paragraphe', (await ev(`document.querySelectorAll('.text.draft input.pick').length`)) >= 4);
  check('sans sélection : « les 2 premiers paragraphes »', await ev(`document.querySelector('.msg').textContent.includes('les 2 premiers paragraphes')`));
  await click('.pick[data-i="1"]');
  check('un paragraphe coché', await waitFor(`document.querySelectorAll('.text p.sample-pick').length === 1 && document.querySelector('.msg').textContent.includes('1 paragraphe coché')`, 3000));
  await ev(`document.querySelector('.pick[data-i="3"]').dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, shiftKey: true }))`);
  check('Maj+clic coche toute la plage (2 à 4)', await waitFor(`document.querySelectorAll('.text p.sample-pick').length === 3 && document.querySelector('.msg').textContent.includes('n° 2, 3, 4')`, 3000));
  await clickText('button', 'Tout décocher');
  check('« Tout décocher » vide la sélection', await waitFor(`document.querySelectorAll('.text p.sample-pick').length === 0`, 3000));
  await click('.pick[data-i="2"]');
  await click('.pick[data-i="3"]');
  check('deux paragraphes cochés (3 et 4)', await waitFor(`[...document.querySelectorAll('.text p.sample-pick')].map((p) => p.dataset.i).join() === '2,3'`, 3000));

  // Échantillon
  check('le bouton affiche le nombre de paragraphes cochés', await ev(`document.body.textContent.includes('Échantillon (2 paragraphes)')`));
  await clickText('button', 'Échantillon (2 paragraphes)');
  check('la génération apparaît dans la barre d\'état avec son pourcentage et un chronomètre', await waitFor(`/Échantillon \\(2 paragraphes\\) \\d+ % · \\d+ s/.test(document.querySelector('#tasks').textContent)`, 8000));
  check('échantillon généré et lecteur affiché', await waitFor(`!!document.querySelector('.kept-item audio')`, 90000));
  const dur = await ev(`new Promise((r) => { const a = document.querySelector('.kept-item audio'); a.preload = 'auto'; a.load(); const f = () => r(a.duration); a.readyState >= 1 ? f() : a.addEventListener('loadedmetadata', f, { once: true }); setTimeout(() => r(-1), 8000); })`);
  check('échantillon audio valide', dur > 2, `durée ${Number(dur).toFixed(1)} s`);
  check('la tâche disparaît de la barre d\'état à la fin', await waitFor(`!document.querySelector('#tasks').textContent.includes('Échantillon (')`, 5000));
  await shot('3-echantillon');
  const mid = (await (await fetch(`${BASE}/api/books`)).json()).find((b) => !before.has(b.id));
  check('le livre est toujours en brouillon après l\'échantillon', mid?.status === 'draft', mid?.status);

  check('l\'échantillon est conservé dans une liste', await waitFor(`document.body.textContent.includes('Échantillons conservés (1)')`, 5000));
  await clickText('button', '← Bibliothèque');
  await waitFor(`!!document.querySelector('#library') && !document.querySelector('#player')`, 5000);
  await clickText('.book', 'e2e-bookreader-court');
  check('il est toujours là après être sorti du livre et revenu', await waitFor(`document.body.textContent.includes('Échantillons conservés (1)')`, 10000));
  const bk = (await (await fetch(`${BASE}/api/books`)).json()).find((b) => b.title === 'e2e-bookreader-court');
  const smp = await (await fetch(`${BASE}/api/books/${bk.id}/samples`)).json();
  check('métadonnées de l\'échantillon : voix, langue, vitesse, paragraphes, réglages, durée',
    smp.length === 1 && smp[0].voice_name && smp[0].language === 'fr' && smp[0].speed === 1 && JSON.stringify(smp[0].paragraphs) === '[2,3]' && smp[0].settings?.temperature === 0.75 && smp[0].duration > 2,
    JSON.stringify(smp[0] ?? {}).slice(0, 220));

  // Annulation d'un échantillon : on en lance un autre (voix différente pour éviter le cache) puis on l'annule
  await ev(`document.querySelector('#sidebar .voices .voice:nth-child(2)').click()`);
  await clickText('button', 'Échantillon (2 paragraphes)');
  check('bouton « Annuler » pendant la génération', await waitFor(`!![...document.querySelectorAll('.msg button')].find((b) => b.textContent.includes('Annuler'))`, 8000));
  await clickText('.msg button', 'Annuler');
  check('l\'échantillon annulé disparaît de la barre d\'état', await waitFor(`!document.querySelector('#tasks').textContent.includes('Échantillon (')`, 8000));
  check('le bouton Échantillon est de nouveau disponible', await waitFor(`[...document.querySelectorAll('.msg button')].some((b) => b.textContent.includes('Échantillon (2 paragraphes)') && !b.disabled)`, 8000));
  // Les échantillons s'accumulent (2e voix encore sélectionnée) et se suppriment un par un
  await clickText('button', 'Échantillon (2 paragraphes)');
  check('un second échantillon s\'ajoute au premier', await waitFor(`document.body.textContent.includes('Échantillons conservés (2)')`, 90000));
  await waitFor(`[...document.querySelectorAll('.msg button')].some((b) => b.textContent.includes('Échantillon (2 paragraphes)') && !b.disabled)`, 10000, 'tâche terminée');
  await ev(`document.querySelector('.kept-item .icon-btn').click()`);
  check('un échantillon se supprime', await waitFor(`document.body.textContent.includes('Échantillons conservés (1)')`, 5000));
  await ev(`document.querySelector('#sidebar .voices .voice').click()`);

  // Conversion
  if (process.env.DEBUG_UI) console.log('boutons :', await ev(`JSON.stringify([...document.querySelectorAll('.msg button, #player > .player-head button')].map((b) => b.textContent.trim().slice(0, 40) + (b.disabled ? ' (inactif)' : '')))`));
  await clickText('button', 'Convertir tout le livre');
  check('la conversion démarre (barre d\'état)', await waitFor(`document.querySelector('#tasks').textContent.match(/Conversion|En attente/)`, 15000));
  if (logs.length) console.log('journal de la page :', logs.join(' | '));
  await shot('4-conversion');
  check('conversion terminée, lecteur audio prêt', await waitFor(`!!document.querySelector('#player .controls')`, 180000));
  check('téléchargements proposés', await waitFor(`document.querySelector('.downloads')?.textContent.includes('MP3 complet')`, 5000));
  await shot('5-termine');

  // Régénérer avec une autre voix : l'audio précédent doit être conservé dans « Versions précédentes »
  await ev(`window.confirm = () => true`);
  const preRegen = await (await fetch(`${BASE}/api/books/${bk.id}`)).json();   // voix utilisée par la première conversion
  await ev(`(() => { const sel = document.querySelector('.regen select'); sel.value = 'b-damien-black'; sel.dispatchEvent(new Event('change', { bubbles: true })); })()`);
  await clickText('button', 'Régénérer');
  check('la régénération démarre', await waitFor(`/Conversion|En attente/.test(document.querySelector('#tasks').textContent)`, 15000));
  check('régénération terminée', await waitFor(`!!document.querySelector('#player .controls') && !/Conversion|En attente/.test(document.querySelector('#tasks').textContent)`, 120000));
  check('la version précédente est conservée', await waitFor(`document.body.textContent.includes('Versions précédentes (1)')`, 15000));
  const vers = await (await fetch(`${BASE}/api/books/${bk.id}/versions`)).json();
  check('métadonnées de la version : voix, langue, vitesse, réglages, durée, paragraphes',
    vers.length === 1 && vers[0].voice_name === preRegen.voice_name && vers[0].voice_name !== 'Damien Black' && vers[0].language === 'fr' && vers[0].speed === 1 && vers[0].settings?.temperature === 0.75 && vers[0].duration > 5 && vers[0].paragraphs >= 4,
    JSON.stringify(vers[0] ?? {}).slice(0, 220));
  check('l\'audio de la version conservée est lisible', (await fetch(`${BASE}/api/books/${bk.id}/versions/${vers[0].id}/audio`)).status === 200);
  const cur = (await (await fetch(`${BASE}/api/books/${bk.id}`)).json());
  check('le livre actuel a la nouvelle voix et ses réglages sauvegardés (result)', cur.voice_name === 'Damien Black' && cur.result?.voice_name === 'Damien Black' && cur.result?.duration > 5, JSON.stringify(cur.result ?? {}).slice(0, 160));

  // Retour à la bibliothèque
  await clickText('button', '← Bibliothèque');
  check('retour à la bibliothèque', await waitFor(`!!document.querySelector('#library') && !document.querySelector('#player')`, 3000));
  check('la carte du livre est « Prêt »', await ev(`[...document.querySelectorAll('.book')].some((c) => c.textContent.includes('e2e-bookreader-court') && c.textContent.includes('Prêt'))`));
  check('la barre d\'état signale « Terminé »', await ev(`document.querySelector('#tasks').textContent.includes('Terminé')`));
  await shot('6-bibliotheque-finale');

  // Rechargement : le livre ouvert est conservé par l'adresse
  await clickText('.book', 'e2e-bookreader-court');
  await waitFor(`!!document.querySelector('#player')`, 5000);
  await send('Page.reload');
  check('rechargement : le livre reste ouvert (#livre=)', await waitFor(`!!document.querySelector('#player') && location.hash.startsWith('#livre=')`, 20000));

  // Mise en page : un livre long (sans le convertir) — chapitres à gauche, texte à droite, seul le texte défile
  const long = join(dir, 'e2e-bookreader-long.md');
  writeFileSync(long, Array.from({ length: 14 }, (_, c) => `# Chapitre ${c + 1}\n\n` + Array.from({ length: 8 }, (_, p) => `Paragraphe ${p + 1} du chapitre ${c + 1}. Voici une phrase assez longue pour remplir la ligne et obliger le texte à défiler dans son cadre.`).join('\n\n')).join('\n\n'));
  await waitFor(`[...document.querySelectorAll('button')].some((b) => b.textContent.includes('← Bibliothèque'))`, 20000, 'livre rechargé');
  await clickText('button', '← Bibliothèque');
  await waitFor(`!!document.querySelector('.drop input[type=file]') && !document.querySelector('#player')`, 5000);
  const doc2 = (await send('DOM.getDocument')).result.root.nodeId;
  const input2 = (await send('DOM.querySelector', { nodeId: doc2, selector: '.drop input[type=file]' })).result.nodeId;
  await send('DOM.setFileInputFiles', { nodeId: input2, files: [long.replaceAll('\\', '/')] });
  await waitFor(`!!document.querySelector('.book-body .text p')`, 30000);
  await sleep(500);
  const m = await ev(`(() => { const q = (s) => document.querySelector(s); const r = (e) => e.getBoundingClientRect(); const t = q('.text'), ch = q('.chap-col'), c = q('#content'), p = q('#player');
    return { content: c.scrollHeight - c.clientHeight, page: document.scrollingElement.scrollHeight - document.scrollingElement.clientHeight, player: p.scrollHeight - p.clientHeight,
      text: t.scrollHeight - t.clientHeight, side: r(ch).right <= r(t).left + 1 && Math.abs(r(ch).top - r(t).top) < 40,
      chapOverflow: getComputedStyle(ch).overflowY, chapInner: ch.scrollHeight - ch.clientHeight,
      textBar: getComputedStyle(t).scrollbarColor, chapters: ch.querySelectorAll('li').length }; })()`);
  check('la liste des chapitres allonge la page (le contenu défile)', m.content > 50 && m.page <= 1, JSON.stringify({ content: m.content, page: m.page }));
  check('la liste des chapitres n\'a pas de défilement interne', m.chapOverflow === 'visible' && m.chapInner <= 1, `${m.chapOverflow}, +${m.chapInner}px`);
  check('le texte du livre a son propre défilement (aux couleurs du thème)', m.text > 50 && m.textBar !== 'auto', `texte +${m.text}px, ${m.textBar}`);
  check('chapitres et texte côte à côte', m.side === true && m.chapters >= 12, `${m.chapters} chapitres`);
  await ev(`document.querySelector('#content').scrollTop = 400`);
  await sleep(300);
  const stick = await ev(`(() => { const c = document.querySelector('#content'), t = document.querySelector('.text'); return { scrolled: c.scrollTop, top: Math.round(t.getBoundingClientRect().top - c.getBoundingClientRect().top), height: Math.round(t.getBoundingClientRect().height) }; })()`);
  check('le texte reste en vue quand on parcourt les chapitres', stick.scrolled > 100 && stick.top <= 24 && stick.height >= 300, JSON.stringify(stick));
  await ev(`document.querySelector('#content').scrollTop = 0`);
  await shot('7-livre-long');

  // Annulation d'une conversion : on lance la conversion du livre long, puis on l'annule depuis la barre d'état
  await ev(`window.confirm = () => true`);
  await clickText('button', 'Convertir tout le livre');
  check('conversion du livre long démarrée', await waitFor(`/Conversion \\d+(\\.\\d+)? %/.test(document.querySelector('#tasks').textContent)`, 60000));
  await sleep(1500);
  check('bouton « Annuler » dans la barre d\'état', await ev(`!![...document.querySelectorAll('#tasks button')].find((b) => b.textContent.includes('Annuler'))`));
  await clickText('#tasks button', 'Annuler');
  check('la conversion annulée remet le livre en brouillon', await waitFor(`!document.querySelector('#tasks').textContent.match(/Conversion|En attente/) && document.body.textContent.includes('Convertir tout le livre')`, 60000));
  const st = (await (await fetch(`${BASE}/api/books`)).json()).find((b) => b.title === 'e2e-bookreader-long');
  check('le livre est « draft » côté serveur, sans audio', st?.status === 'draft' && st.progress === 0, `${st?.status} ${st?.progress}`);
  await shot('8-annule');
  await waitFor(`[...document.querySelectorAll('button')].some((b) => b.textContent.includes('← Bibliothèque'))`, 5000);

  // Création d'une voix par mélange, puis suppression (la boîte de confirmation est acceptée d'office)
  await ev(`window.confirm = () => true`);
  await click('.brand h1'); // sans effet : s'assurer que la page est active
  await clickText('button', '← Bibliothèque');
  await waitFor(`!!document.querySelector('#library')`, 5000);
  await waitFor(`document.querySelectorAll('.voices .voice').length >= 3`, 60000);
  await ev(`document.querySelector('#createVoice').open = true`);
  await clickText('#createVoice .seg button', 'Mélanger');
  await waitFor(`(() => { const b = [...document.querySelectorAll('#createVoice button')].find((x) => x.textContent.includes('Créer le mélange')); return b && !b.disabled; })()`, 20000, 'bouton Créer le mélange actif');
  check('mélange : formulaire affiché', await waitFor(`!!document.querySelector('#createVoice select')`, 3000));
  await ev(`(() => { const i = document.querySelector('#createVoice input[type=text]'); i.value = 'e2e-bookreader-voix'; i.dispatchEvent(new Event('input', { bubbles: true })); })()`);
  await clickText('#createVoice button', 'Créer le mélange');
  check('voix mélangée créée et sélectionnée', await waitFor(`[...document.querySelectorAll('.voice.active strong')].some((e) => e.textContent === 'e2e-bookreader-voix')`, 60000));
  check('elle apparaît dans « Mes voix »', await ev(`document.body.textContent.includes('Mes voix')`));
  await ev(`[...document.querySelectorAll('.voice')].find((v) => v.textContent.includes('e2e-bookreader-voix')).querySelector('button[title="Supprimer cette voix"]').click()`);
  check('voix supprimée', await waitFor(`![...document.querySelectorAll('.voice strong')].some((e) => e.textContent === 'e2e-bookreader-voix')`, 10000));

  check('aucune erreur JavaScript', logs.length === 0, logs.join(' | '));
} catch (e) {
  check('exécution du test', false, e.stack ?? String(e));
} finally {
  try { ws?.close(); } catch {}
  chrome.kill();
  // Nettoyage : uniquement les livres du test (noms exacts) ; jamais ceux d'une autre personne qui utilise le même serveur
  const after = await (await fetch(`${BASE}/api/books`)).json();
  for (const b of after.filter((x) => !before.has(x.id) && TEST_TITLES.includes(x.title))) { await fetch(`${BASE}/api/books/${b.id}`, { method: 'DELETE' }); console.log('livre de test supprimé:', b.id); }
  const voices = await (await fetch(`${BASE}/api/voices`)).json();
  for (const v of voices.custom.filter((x) => x.name === 'e2e-bookreader-voix')) await fetch(`${BASE}/api/voices/${v.id}`, { method: 'DELETE' });
}
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} vérifications réussies`);
process.exit(failed.length ? 1 : 0);

