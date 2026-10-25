const { app, BrowserWindow, Menu, Notification, Tray, dialog, powerSaveBlocker, session } = require('electron');
const { spawn, spawnSync } = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const http = require('http');
const net = require('net');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const TOKEN = crypto.randomBytes(24).toString('hex');
const HOST = '127.0.0.1';

let port = 0;
let server = null;        // processus Python
let win = null;
let tray = null;
let quitting = false;
let blockerId = null;
let busy = false;          // une conversion est en cours ou en attente
let lastStatus = new Map(); // id -> statut, pour détecter « terminé »

if (!app.requestSingleInstanceLock()) app.quit();
app.on('second-instance', showWindow);

function freePort() {
  return new Promise((resolve, reject) => {
    const s = net.createServer();
    s.once('error', reject);
    s.listen(0, HOST, () => { const p = s.address().port; s.close(() => resolve(p)); });
  });
}

function api(p) {
  return new Promise((resolve, reject) => {
    const req = http.get({ host: HOST, port, path: p, headers: { 'X-BookReader-Token': TOKEN }, timeout: 5000 }, (res) => {
      let body = '';
      res.on('data', (c) => (body += c));
      res.on('end', () => (res.statusCode === 200 ? resolve(JSON.parse(body)) : reject(new Error('HTTP ' + res.statusCode))));
    });
    req.on('error', reject);
    req.on('timeout', () => req.destroy(new Error('timeout')));
  });
}

function startServer() {
  const dataDir = path.join(app.getPath('appData'), 'BookReader');
  // Runtime embarqué (build/prepare-runtime.ps1) : Python, modèle et ffmpeg, tout hors ligne.
  // Installé : à côté de l'exécutable ; en développement : build/runtime s'il existe.
  const rt = app.isPackaged ? path.join(path.dirname(process.execPath), 'runtime') : path.join(ROOT, 'build', 'runtime');
  const python = path.join(rt, 'python', 'python.exe');
  const embedded = fs.existsSync(python);
  const env = {
    ...process.env,
    DATA_DIR: dataDir,
    BOOKREADER_TOKEN: TOKEN,
    COQUI_TOS_AGREED: '1',
    PYTHONUTF8: '1',
  };
  const args = ['-m', 'uvicorn', 'server.main:app', '--host', HOST, '--port', String(port), '--log-level', 'warning'];
  let cmd, cwd;
  if (embedded) {
    Object.assign(env, {
      TTS_HOME: path.join(rt, 'models'),
      HF_HOME: path.join(rt, 'models', 'hf'),
      HF_HUB_OFFLINE: '1',
      FFMPEG: path.join(rt, 'bin', 'ffmpeg.exe'),
      FFPROBE: path.join(rt, 'bin', 'ffprobe.exe'),
    });
    cmd = python;
    cwd = app.isPackaged ? process.resourcesPath : ROOT; // dossier qui contient « server »
    env.PYTHONNOUSERSITE = '1'; // n'utilise jamais les paquets Python de l'utilisateur
  } else {
    // Développement sans runtime : uv gère l'environnement (FFMPEG / FFPROBE à définir à la main)
    cmd = 'uv';
    args.unshift('run', 'python');
    cwd = ROOT;
  }
  server = spawn(cmd, args, { cwd, env, windowsHide: true, stdio: ['ignore', 'inherit', 'inherit'] });
  server.on('exit', (code) => {
    server = null;
    if (!quitting) {
      dialog.showErrorBox('BookReader', `Le serveur s'est arrêté (code ${code}).`);
      quitting = true;
      app.quit();
    }
  });
}

function stopServer() {
  if (server && server.pid) spawnSync('taskkill', ['/pid', String(server.pid), '/T', '/F'], { windowsHide: true });
  server = null;
}

async function waitForServer(timeoutMs = 180000) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    if (!server) throw new Error('Serveur arrêté');
    try { await api('/api/config'); return; } catch { await new Promise((r) => setTimeout(r, 500)); }
  }
  throw new Error('Le serveur ne répond pas');
}

function createWindow() {
  win = new BrowserWindow({
    width: 1200, height: 860, show: false, title: 'BookReader', autoHideMenuBar: true,
    icon: app.isPackaged ? path.join(process.resourcesPath, 'icon.png') : path.join(ROOT, 'build', 'icon.png'),
    webPreferences: { preload: path.join(__dirname, 'preload.js'), contextIsolation: true, sandbox: true },
  });
  win.once('ready-to-show', () => win.show());
  // La croix quitte l'application, sauf si une conversion est en cours (ou si on ne peut pas le
  // savoir) : la fenêtre va alors dans la zone de notification et le travail continue.
  let closing = false;
  win.on('close', (e) => {
    if (quitting) return;
    e.preventDefault();
    if (closing) return;
    closing = true;
    // État à jour, pas celui du dernier sondage : une conversion lancée il y a 1 s compte
    pollBooks()
      .then((known) => { if (!known || busy) win.hide(); else app.quit(); })
      .finally(() => { closing = false; });
  });
  win.loadURL(`http://${HOST}:${port}/`);
}

function showWindow() {
  if (!win) return;
  if (win.isMinimized()) win.restore();
  win.show();
  win.focus();
}

function createTray() {
  const { nativeImage } = require('electron');
  const iconPath = app.isPackaged ? path.join(process.resourcesPath, 'icon.png') : path.join(ROOT, 'build', 'icon.png');
  tray = new Tray(nativeImage.createFromPath(iconPath).resize({ width: 32, height: 32 }));
  tray.setToolTip('BookReader');
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: 'Ouvrir BookReader', click: showWindow },
    { label: 'Quitter', click: () => app.quit() },
  ]));
  tray.on('click', showWindow);
}

// Surveille les conversions : veille bloquée pendant le travail, notification à la fin
async function pollBooks() {
  try {
    const books = await api('/api/books');
    busy = books.some((b) => b.status === 'processing' || b.status === 'queued');
    for (const b of books) {
      if (lastStatus.get(b.id) === 'processing' && b.status === 'done') {
        new Notification({ title: 'Livre terminé', body: b.title }).on('click', showWindow).show();
      }
      lastStatus.set(b.id, b.status);
    }
    if (busy && blockerId === null) blockerId = powerSaveBlocker.start('prevent-app-suspension');
    if (!busy && blockerId !== null) { powerSaveBlocker.stop(blockerId); blockerId = null; }
    return true;
  } catch { return false; /* serveur occupé : on réessaie au prochain tour */ }
}

app.on('before-quit', (e) => {
  if (quitting) return;
  if (busy) {
    const choice = dialog.showMessageBoxSync({
      type: 'warning', buttons: ['Continuer en arrière-plan', 'Quitter quand même'], defaultId: 0, cancelId: 0,
      title: 'Conversion en cours',
      message: 'Une conversion est en cours.',
      detail: 'Si vous quittez, elle sera reprise au prochain démarrage.',
    });
    if (choice === 0) { e.preventDefault(); if (win) win.hide(); return; }
  }
  quitting = true;
});
app.on('will-quit', stopServer);
app.on('window-all-closed', () => { /* reste actif dans la zone de notification */ });

app.whenReady().then(async () => {
  try {
    port = await freePort();
    startServer();

    // Le jeton est ajouté à toutes les requêtes vers le serveur local (pages, API, <audio>)
    session.defaultSession.webRequest.onBeforeSendHeaders({ urls: [`http://${HOST}:${port}/*`] }, (details, cb) => {
      cb({ requestHeaders: { ...details.requestHeaders, 'X-BookReader-Token': TOKEN } });
    });
    // Seul le micro (clonage de voix) est autorisé, et seulement pour notre page
    session.defaultSession.setPermissionRequestHandler((wc, permission, cb) => {
      cb(permission === 'media' && wc.getURL().startsWith(`http://${HOST}:${port}/`));
    });

    await waitForServer();
    createWindow();
    createTray();
    setInterval(pollBooks, 3000);
  } catch (err) {
    dialog.showErrorBox('BookReader', String(err.message || err));
    quitting = true;
    app.quit();
  }
});
