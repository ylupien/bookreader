# BookReader (Windows)

Application de bureau Windows qui convertit un document (PDF, TXT, MD, HTML, DOCX, EPUB, RTF) en
livre audio avec **XTTS-v2** sur le GPU NVIDIA local, puis permet de l'écouter. Tout tourne en
local et **hors ligne** : sans WSL, sans Docker, sans Python ni CUDA Toolkit à installer.

> XTTS-v2 est sous licence Coqui CPML : **usage non commercial uniquement**.

## Fonctions

- Import de PDF, TXT, MD, HTML, DOCX, EPUB et RTF, avec détection des chapitres.
- 58 voix intégrées, clonage de voix (enregistrement ou fichier) et mélange de voix.
- Interface en trois zones : **barre de gauche** (langue, voix, vitesse, réglages avancés, format), **contenu**
  (bibliothèque en cartes avec la zone de dépôt en bas, ou le livre ouvert : chapitres à gauche, texte à droite)
  et **barre d'état** toujours visible (extractions, conversions, exports, erreurs).
- Voix **préférées** : ♥ sur une voix pour l'ajouter à la liste du haut (par défaut, les voix recommandées).
- Rien n'est converti à l'import : on règle la voix, la langue, la vitesse et les pauses, on **coche les
  paragraphes** à écouter (Maj+clic pour une plage ; sinon les deux premiers) pour un **échantillon**, puis on
  lance **Convertir tout le livre**.
- Lecture avec surlignage du texte ; réglages de la voix (température, vitesse, pauses…).
- Export : MP3, ZIP d'un MP3 par chapitre (tags ID3 et playlist) et M4B avec chapitres.
- **Rien n'est perdu** : les échantillons s'accumulent dans le livre (lecture, suppression, avec leur voix, vitesse, langue, paragraphes…)
  et chaque conversion est conservée dans « Versions précédentes » (audio, exports et réglages utilisés).
- Narration soignée : guillemets, ligatures de PDF, notes de bas de page ([1]), symboles et abréviations (p. 12) sont préparés avant la
  lecture, et les phrases où le moteur déraille (mot parasite en fin de phrase) sont resynthétisées. Une alerte signale une voix d'une
  autre langue que le texte. Vitesse de lecture par défaut : 1×.
- La croix de la fenêtre quitte l'application, sauf pendant une conversion : la fenêtre est alors
  cachée dans la zone de notification (clic sur l'icône pour la rouvrir, clic droit puis « Quitter »
  pour arrêter) ; notification quand un livre est terminé ; la mise en veille est bloquée pendant le calcul.

## Installer

Il faut un PC Windows 64 bits avec un **GPU NVIDIA** et un pilote récent (≈ 570 ou plus). Un seul
installateur convient à tous les GPU, de la GTX 9xx (Maxwell) à la RTX 50xx (Blackwell).
Prévoir environ **8,5 Go** sur le disque (une dizaine de Go libres pendant l'installation).

1. Copiez le dossier `dist\installer` (`BookReader-Setup.exe` **et** les `BookReader-Setup-N.bin`,
   à garder ensemble, ≈ 8,4 Go) sur le PC et lancez `BookReader-Setup.exe`.
   L'installation est par utilisateur (pas besoin d'administrateur).
2. L'installateur n'est pas signé : SmartScreen peut afficher un avertissement
   (« Informations complémentaires » puis « Exécuter quand même »).

Aucun CUDA Toolkit, Python ni ffmpeg à installer. Sans GPU utilisable, l'application passe sur le
processeur (beaucoup plus lent). Une carte de 4 Go de VRAM (GTX 970) suffit, mais c'est juste.

Erreur « CUDA error: no kernel image is available » : le GPU n'est pas reconnu par la version de
torch embarquée. Signalez le modèle du GPU (`nvidia-smi --query-gpu=name,compute_cap --format=csv`).

## Version web (Docker)

Le serveur peut aussi tourner seul dans Docker (Docker Desktop avec GPU NVIDIA), sans Electron :

```powershell
docker compose up -d --build     # 1re fois : long (image ≈ 16 Go, le modèle est inclus)
```

Puis ouvrir http://127.0.0.1:8001. Les livres sont dans `.\data` (conteneur `bookreader-win`, port 8001
pour ne pas gêner l'ancienne version de référence sur le port 8000). Une seule version à la fois doit
utiliser le GPU : arrêter les autres (`docker compose down`, fermer l'application Windows).

## Distribuer l'installateur sur le réseau local (Apache)

Un petit serveur Apache (Docker) publie le dossier `dist\installer` avec la **liste des fichiers** (`Options +Indexes`) :
`BookReader-Setup.exe` + `.bin`, **`BookReader-Setup.zip`** (tous les fichiers de l'installation en un seul) et `SHA256SUMS.txt`.
Le ZIP et les sommes de contrôle sont créés par `build\make-installer.ps1` (`-ZipOnly` pour les refaire sans recompiler).

```powershell
docker compose --profile distribution up -d installer-server    # démarrer
docker compose --profile distribution stop installer-server     # arrêter
```

Adresse : `http://<IP de ce PC>:8090/` (port modifiable avec la variable `INSTALLER_PORT`). Le service est dans le profil
`distribution` : **`docker compose up` ne le lance pas**, et il ne redémarre pas tout seul avec Docker ou Windows. Il est en lecture seule, limité aux adresses privées du réseau local,
et accepte la reprise des téléchargements interrompus. Si un autre PC n'y accède pas, autoriser le port 8090 en entrée dans le
pare-feu Windows.

## Données

Livres, voix et aperçus sont dans `%APPDATA%\BookReader` (conservés à la désinstallation). Les
données de la version Docker (`data\books`, `data\voices`) sont compatibles : copiez-les dans ce
dossier.

## Développement

Prérequis : [uv](https://docs.astral.sh/uv/), Node.js 22, ffmpeg.

```powershell
npm install                   # Electron
npm run setup:web             # dépendances de l'interface (web/)
uv sync                       # environnement Python (torch 2.7.1+cu128)
npm run build:web             # interface -> server/static
npm start                     # lance Electron ; utilise build\runtime s'il existe, sinon uv
```

Sans `build\runtime`, définir `FFMPEG` et `FFPROBE` (ou avoir ffmpeg dans le PATH) et le modèle
se télécharge au premier lancement. Pour tester le serveur seul :
`uv run uvicorn server.main:app --host 127.0.0.1` (variables `DATA_DIR`, `BOOKREADER_TOKEN`).

### Interface (`web/` : Svelte 5 + Vite + TypeScript)

```powershell
cd web
npm run dev        # http://localhost:5173 avec rechargement à chaud ; /api est envoyé au serveur sur le port 8001
                   # (conteneur Docker ; autre serveur : $env:API_URL = "http://127.0.0.1:8000")
npm run check      # vérification des types (svelte-check)
npm run build      # écrit dans ../server/static, servi tel quel par FastAPI
node e2e/ui-test.mjs   # test de bout en bout dans Chrome sans fenêtre (serveur sur le port 8001) ; il utilise ce serveur\n                       # (échantillons, conversions) mais ne supprime que ses livres « e2e-bookreader-* »
```

`server/static/` est **généré** : ne pas le modifier à la main, il est réécrit à chaque `npm run build:web`.

### Organisation

| Dossier | Contenu |
|---|---|
| `server/` | FastAPI : API, extraction, chapitres, export, moteur XTTS |
| `web/` | Interface (sources Svelte) : `src/components`, `src/lib` (état, API, types), `e2e/` |
| `server/static/` | Interface construite (générée par `web/`) |
| `desktop/` | Electron : `main.js` (serveur, fenêtre, zone de notification…), `preload.js` |
| `build/` | Scripts et configuration d'empaquetage |
### Construire les installateurs

Avec internet, dans cet ordre (Inno Setup 6 : `winget install JRSoftware.InnoSetup`) :

```powershell
powershell -File build\prepare-runtime.ps1       # Python + dépendances + modèle + ffmpeg -> build\runtime (~8,2 Go)
npm run pack                                     # interface (Vite) puis Electron -> dist\win-unpacked
powershell -File build\make-installer.ps1        # -> dist\installer\BookReader-Setup.exe + .bin
```

Pourquoi Inno Setup et pas NSIS : l'installateur dépasse largement la limite de 2 Go de NSIS ;
Inno Setup le découpe en fichiers `.bin` de 2 Go. Le détail des choix et des pièges est dans
`CLAUDE.md`.

## Limites connues

Import PDF/DOCX, clonage de voix au micro et « Enregistrer sous » pas encore vérifiés à fond.
L'icône n'est pas incrustée dans `BookReader.exe` (elle apparaît dans la fenêtre, la zone de
notification et les raccourcis).