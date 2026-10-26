# BookReader — version Windows native (Electron)

L'utilisateur écrit en français : réponds en français.

## Objectif

Créer une application de bureau **Windows uniquement, sans WSL ni Docker**, qui reprend
BookReader : importer un document (PDF, TXT, MD, HTML, DOCX, EPUB, RTF), en extraire le texte
et le convertir en livre audio avec XTTS-v2 sur le GPU NVIDIA local, puis l'écouter.
Tout tourne en local et hors ligne après la première installation.

## Origine

La version de référence (Docker, sous WSL2) se trouve dans un dossier `bookreader` de la distribution
WSL de l'utilisateur (accessible par `\\wsl$\<distribution>\...`) et tourne en production sur
http://localhost:8000.

- **Ne pas la modifier ni l'arrêter.** Une conversion peut être en cours, et l'utilisateur a
  demandé à plusieurs reprises de ne jamais interrompre une conversion.
- Les deux versions ne doivent pas utiliser le GPU en même temps (8 Go de VRAM seulement).

Ce dossier contient une **copie** du code Python et de l'interface (`server/`), prise le
2026-10-25. `README-docker.md` est le README de la version Docker.

## Matériel

- Le portable a un RTX 5070 Laptop (8 Go, architecture Blackwell).
- Il faut **torch 2.7.1 et torchaudio 2.7.1 depuis l'index cu128**
  (`https://download.pytorch.org/whl/cu128`). Les versions plus anciennes ne supportent pas
  les RTX 50xx.

## Ce que fait déjà le code (`server/`)

- **FastAPI et uvicorn** :
  - L'interface HTML/JS/CSS est dans `server/static`, servie par `StaticFiles`.
  - Le serveur est lancé par `uvicorn server.main:app`. Les imports sont relatifs
    (`from . import ...`).
- **`tts_engine.py`** : utilise XTTS-v2 (`tts_models/multilingual/multi-dataset/xtts_v2`,
  coqui-tts 0.28.0).
  - Une voix est un couple `gpt_cond_latent` / `speaker_embedding`.
  - 58 voix sont intégrées.
  - Le clonage passe par `get_conditioning_latents`, le mélange par une interpolation.
  - Réglages exposés : temperature, top_p, top_k, repetition_penalty, length_penalty, speed.
  - Le texte est découpé une phrase par morceau. Un verrou GPU protège le calcul.
- **`extract.py`** : extrait le texte et les chapitres de la structure du document (signets
  PDF, table des matières EPUB, titres DOCX/MD/HTML) avec des marqueurs `\x01titre\x02`.
- **`chapters.py`** : détecte les chapitres dans cet ordre : structure, table des matières,
  titres (regex), découpe par longueur. Il décoche les pages liminaires (TOC, Copyright…).
- **`export.py`** :
  - ZIP d'un MP3 par chapitre : `ffmpeg -c copy`, tags ID3 et playlist `.m3u`.
  - M4B avec chapitres : démuxeur concat, ffmetadata, AAC 64k.
- **`main.py`** :
  - API sous `/api/...` : voix (aperçu, clonage, mélange, suppression), livres, chapitres,
    exports.
  - Un thread worker pour le GPU et un thread pour les exports.
  - Les données sont dans `DATA_DIR` (`books/<id>/meta.json` écrit de façon atomique,
    `audio.mp3`, `voices/*.pt` et `*.json`, `previews/`).
  - Statuts d'un livre : draft, queued, processing, done, error.
  - Les conversions et exports en attente reprennent au démarrage.
  - Le MP3 est produit en envoyant le PCM dans `ffmpeg` (64k, 24 kHz). Un timing est noté
    par paragraphe, pour surligner le texte et calculer les chapitres.
- **Variables d'environnement utilisées par Docker** : `DATA_DIR`, `TTS_HOME` (cache du
  modèle), `COQUI_TOS_AGREED=1`, `HF_HOME`, `HF_HUB_OFFLINE=1`.
- **Licence** : XTTS-v2 est sous licence Coqui CPML, **usage non commercial uniquement**.
  L'utilisateur le sait.

## Architecture

```
Electron (main process, Node)
  ├─ lance server/ (Python embarqué dans runtime\) sur 127.0.0.1:<port libre>
  │    avec un jeton secret, attend /api/config, puis ouvre la fenêtre
  ├─ fenêtre = l'interface server/static existante
  ├─ powerSaveBlocker pendant une conversion, notification « livre terminé »
  ├─ icône dans la barre des tâches : fermer la fenêtre n'arrête pas la conversion
  ├─ confirmation avant de quitter si une conversion est en cours
  └─ « Enregistrer sous » natif pour MP3, ZIP et M4B ; autorisation micro (clonage)
Données : %APPDATA%\BookReader (DATA_DIR) ; modèle : <dossier d'installation>\runtime\models
```

Installation : **installateur Inno Setup 100 % hors ligne** (voir « État du projet »), qui contient
Python, les dépendances, le modèle XTTS et ffmpeg ; aucun téléchargement au lancement.

Ne pas utiliser PyInstaller pour empaqueter torch et CUDA (trop gros et fragile) ni NSIS
(limite de 2 Go).

## Corrections propres à Windows dans `server/` (toutes faites)

1. **`extract.py` `_epub`** : un `NamedTemporaryFile` reste ouvert pendant que EbookLib le
   relit. Sous Windows, le fichier est verrouillé et l'import échoue. Utiliser `delete=False`,
   fermer le fichier, lire, puis le supprimer.
2. **`Path.replace` vers un fichier ouvert** (`audio.mp3`, `meta.json`, exports) échoue sous
   Windows (PermissionError), par exemple si le lecteur lit le MP3 pendant une régénération.
   Ajouter quelques nouvelles tentatives. Pour `audio.mp3`, envisager un nom versionné.
3. **`ffmpeg` / `ffprobe`** sont appelés par leur nom :
   - lire leur chemin depuis une variable d'environnement (`FFMPEG`, `FFPROBE`) ;
   - passer `creationflags=subprocess.CREATE_NO_WINDOW`, sinon une console s'ouvre à chaque
     appel.
4. **`export.py` `build_m4b`** : échapper les apostrophes dans les chemins de la liste concat
   (`'` devient `'\''`).
5. **`export.py` `safe_name`** : éviter les noms réservés (CON, PRN, AUX, NUL, COM1-9, LPT1-9).
6. **Sécurité** : écouter seulement sur `127.0.0.1` et exiger un jeton (en-tête) fourni par
   Electron.
7. **Valeur par défaut de `DATA_DIR`** : `/data` n'a pas de sens sous Windows. Electron
   fournit toujours la variable.

## État du projet (2026-10-25)

Toutes les étapes du plan initial sont faites, **avec un changement de décision** : l'installateur
est **100 % hors ligne** (rien à télécharger chez l'utilisateur), au lieu d'un écran de premier
lancement avec `uv sync` et téléchargement du modèle. `uv.exe` n'est donc pas embarqué.

**Un seul installateur pour tous les GPU NVIDIA** (Maxwell à Blackwell) : torch **2.7.1+cu128** a
`sm_50…sm_120`. Aucune sélection de GPU ni patch : l'ancien patch « GPU ancien » (torch 2.7.1+cu126)
a été supprimé.
Historique de validation : la GTX 970 (Maxwell, 4 Go) a fonctionné chez l'utilisateur avec le patch
cu126 ; l'installateur unique actuel est vérifié sur la RTX 5070 (synthèse GPU, installation, démarrage)
mais **pas encore sur la GTX 970** : à confirmer lors du prochain essai sur cet ancien PC.

### Environnement de développement

- `uv` (winget, utilisateur) ; `pyproject.toml` + `uv.lock` (Python 3.11, torch/torchaudio
  2.7.1+cu128, index `https://download.pytorch.org/whl/cu128`). `uv run ...` ; ouvrir un nouveau terminal si `uv` n'est pas dans le PATH.
- `npm install` puis `npm start` : lance Electron, qui utilise `build/runtime` s'il existe, sinon
  `uv run python`. Il faut alors `FFMPEG` / `FFPROBE` (ou ffmpeg dans le PATH).
- Ne pas lancer deux versions en même temps (8 Go de VRAM) et ne jamais interrompre la version Docker.

### Corrections Windows (faites)

`server/winutil.py` (`FFMPEG`/`FFPROBE`, `CREATE_NO_WINDOW`, `replace` avec nouvelles tentatives) ;
EPUB via fichier temporaire fermé ; apostrophes dans la liste concat du M4B ; noms réservés ;
jeton `BOOKREADER_TOKEN` (middleware, en-tête `X-BookReader-Token`) ; `DATA_DIR` par défaut
`%APPDATA%\BookReader`. L'écoute sur `127.0.0.1` est réglée par Electron (`--host`).

### Electron (`desktop/`)

`main.js` : port libre + jeton aléatoire, lance `python -m uvicorn server.main:app`, attend
`/api/config`, injecte le jeton avec `webRequest.onBeforeSendHeaders` (couvre aussi `<audio>`),
autorise seulement le micro, icône dans la zone de notification (fermer la fenêtre ne coupe pas la
conversion), confirmation avant de quitter, `powerSaveBlocker`, notification « Livre terminé »
(sondage de `/api/books` toutes les 3 s), arrêt du serveur avec `taskkill /T`. Installé, le runtime
est dans `<dossier de l'exe>\runtime` ; variables : `HF_HOME`, `HF_HUB_OFFLINE=1`, `TTS_HOME`,
`FFMPEG`, `FFPROBE`, `PYTHONNOUSERSITE=1`. **L'interface web est dans `server/static/`**
(servie par FastAPI) ; la fenêtre charge `http://127.0.0.1:<port>/`.

### Construire les installateurs (dans cet ordre)

1. `build\prepare-runtime.ps1` (une fois par version, **avec internet**, sans GPU) → `build\runtime`
   (~8,2 Go) : Python 3.11 autonome avec les dépendances de `uv.lock`, modèle XTTS-v2 dans
   `models\hf` (coqui-tts 0.28 télécharge via Hugging Face, donc `HF_HOME`), ffmpeg/ffprobe
   (copiés depuis `C:\Program Files\ffmpeg-8.0-full_build\bin`).
2. `npm run pack` (construit d'abord l'interface `web/`, puis `electron-builder --dir`) → `dist\win-unpacked`. `signAndEditExecutable:false`,
   car l'extraction de `winCodeSign` échoue sans privilège symlink ; conséquence : l'icône n'est
   pas incrustée dans `BookReader.exe` (elle est utilisée par la fenêtre, la zone de notification
   et les raccourcis).
3. `build\make-installer.ps1` (Inno Setup 6, `build\installer.iss`) → `dist\installer\` :
   `BookReader-Setup.exe` + 5 `.bin` (~8,4 Go, à garder ensemble), ~8,4 Go installés. NSIS est exclu
   (limite de 2 Go). Le runtime est en `nocompression` (≈ pas de gain avec torch/CUDA).
   Installation par utilisateur (pas besoin d'administrateur), installation silencieuse ~100 s.
   Désinstaller conserve `%APPDATA%\BookReader` (livres et voix).

### GPU supportés

Tous les GPU NVIDIA à partir de Maxwell (GTX 9xx, `sm_50`) jusqu'à Blackwell (RTX 50xx, `sm_120`),
avec le même installateur : torch 2.7.1+cu128 embarque `sm_50, 60, 61, 70, 75, 80, 86, 90, 100, 120`
(vérifié avec `torch.cuda.get_arch_list()`). Aucun CUDA Toolkit à installer. Pilote NVIDIA récent
requis (≥ ~570 pour cu128). Sans GPU utilisable, `tts_engine.device()` retombe sur le processeur.

**Piège à retenir** : torch **2.8.0** (cu128 ET cu126) n'a plus `sm_5x` (liste `sm_61…`), d'où l'erreur
« CUDA error: no kernel image is available » sur une GTX 970 ; ne pas remonter à 2.8+ sans
vérifier la liste d'architectures. torch 2.7.1+cu126 n'a pas Blackwell : l'ancien patch cassait les RTX 50xx.
Une carte de 4 Go de VRAM suffit pour XTTS mais c'est juste.

### Interface web (`web/`, ajoutée le 2026-10-25) et service Docker

- **Svelte 5 (runes) + Vite 8 + TypeScript 5.9** (svelte-check n'accepte pas TypeScript 7). Le build écrit dans
  `server/static` (généré, ne pas modifier à la main) ; FastAPI le sert (`StaticFiles`), donc Electron, Docker et le
  mode web utilisent les mêmes fichiers. L'ancienne interface en JS pur a été supprimée (équivalence vérifiée).
- Structure : `src/lib/store.svelte.ts` (état global : voix, réglages, livres, envois, favoris), `src/lib/book.svelte.ts`
  (`BookSession` : texte, chapitres, échantillon, lecture, exports), `src/components/*` (Sidebar, VoiceCard, CreateVoice,
  AdvancedSettings, Library, BookView, DraftBar, ChapterPanel, BookText, Downloads, StatusBar), `src/app.css` (thème
  clair/sombre, variables CSS). `npm run dev` proxy `/api` vers le port 8001 (`API_URL`).
- **Mise en page** : barre de gauche (réglages) · contenu · barre d'état fixe en bas. Le contenu ne défile pas : seul le
  texte du livre défile (barres fines aux couleurs du thème) ; chapitres à gauche, texte à droite ; la liste des chapitres
  défile à la molette sans barre visible ; la bibliothèque (cartes) défile, la zone de dépôt reste en bas. Le livre ouvert
  est dans l'adresse (`#livre=<id>`).
- **Flux d'un document** : l'import ne convertit rien (statut `draft`). Voix, langue, vitesse (défaut **1×**) et réglages viennent
  **uniquement de la barre de gauche**. `POST /api/books/<id>/sample` (voix, lang, vitesse, réglages, `sel` = indices de paragraphes
  cochés ; vide = les 2 premiers de plus de 60 caractères) lance un échantillon en tâche de fond (`GET .../sample/jobs/<job>` :
  statut + progression, `DELETE` : annuler) ; `POST /api/books/<id>/start` lance la conversion ; `POST /api/books/<id>/cancel`
  l'annule (retour à `draft`, ou `done` si un audio existait). Voir « Conservation » ci-dessous.
- **Conservation et métadonnées** (rien n'est perdu) : chaque échantillon terminé reste dans `books/<id>/samples/<id>.wav` avec son
  `.json` (voix, langue, vitesse, réglages, numéros de paragraphes, durée, taille) ; liste `GET .../samples`, audio
  `GET .../samples/<id>/audio`, `DELETE`. Chaque conversion est archivée avant d'être remplacée par la suivante
  (`archive_current` dans `convert`) : `books/<id>/versions/<id>/` = `audio.mp3`, `timings.json`, `chapters.json`, exports ZIP/M4B et
  `version.json` (mêmes métadonnées + titre, nombre de paragraphes, tailles) ; `GET .../versions`, `.../versions/<id>/audio`,
  `.../export/<kind>`, `DELETE`. `meta.json` garde un instantané `result` des réglages réellement utilisés pour l'audio actuel.
  Régénérer ne détruit plus les exports de la version actuelle (ils sont archivés à la fin).- **Voix préférées** : ♥/♡ sur chaque voix ; liste « Préférées » en haut ; par défaut les voix recommandées (fr + en) tant que
  l'utilisateur n'a rien changé (`localStorage` « liked »).
- **Electron** : la croix quitte l'application sauf pendant une conversion (ou si l'état est inconnu) : fenêtre cachée dans la
  zone de notification. À reconstruire dans l'installateur pour être prise en compte.
- **Docker** (`Dockerfile`, `docker-compose.yml`, `.dockerignore`) : construction en deux étapes (Node construit `web/`, puis
  Python) ; service `bookreader-win` sur `127.0.0.1:8001`, données dans `./data`. Ne pas toucher à la version de référence
  (WSL, port 8000). Une seule version à la fois sur le GPU.
- **Test de bout en bout** : `node web/e2e/ui-test.mjs` (Chrome sans fenêtre piloté par CDP, aucun paquet) sur le serveur du
  port 8001 : import, cases à cocher, échantillon, conversion, favoris, mélange de voix, mise en page ; 60 vérifications réussies le 2026-10-25 ; il supprime ce qu'il crée. **Non testés** : clonage de voix au micro, import PDF/DOCX.
### Qualité de la narration (`server/speech_text.py`, `tts_engine.py`, 2026-10-25)

Diagnostic mesuré avec une retranscription **Whisper** de l'audio réellement produit (CPU, cas types puis conversions réelles) : XTTS
**invente des mots** dans ces cas :
1. un morceau de **ponctuation seule** (« . », « ” », « » ») : charabia (« Nine round », « Yua »…) ; il naissait de l'espace avant un
   guillemet fermant (`… . ”`, fréquent dans les livres typographiés) et de l'ancien ajout d'un « . » derrière `”` ;
2. un **morceau très court issu d'une abréviation coupée** (`p. 12` → « p. » + « 12). » → « CPA 12 ») ;
3. un **caractère inconnu** de son vocabulaire (©, `[`, `]`, `+`, `}`, **ligatures PDF ﬁ ﬂ**…) ou un **appel de note** (`[1]` → « one
   you », `animals.1` → « one door ») ; les PDF coupent aussi les mots autour d'une ligature (« ré ﬂexion » → « réaction ») ;
4. **au hasard (~4-7 % des morceaux)** : un mot parasite en fin de phrase (« point », « coin », « pont »…), même avec un texte propre.
   La ponctuation finale n'est PAS le levier (test de 81 synthèses : « . » 7 %, rien 4 %, « , » 0 % : écart non significatif, et une
   virgule change l'intonation) ; on garde « . ». Remède : `tts_engine.synthesize` mesure la durée de chaque morceau et la compare à la
   vitesse de parole médiane de la voix (`_rates`, par langue et vitesse) ; au-delà de 1,5× la durée attendue **et** +1,2 s
   (`is_overlong`), il **resynthétise** (2 tirages max, garde le plus court). Les nombres sont exclus (durée non comparable).
5. **Mauvaise langue** : une voix « en » sur un texte français déforme presque tous les mots. L'import détecte la langue ; le brouillon
   affiche une alerte rouge avec un bouton « Passer en <langue> » et demande confirmation avant de convertir.

Corrections : nettoyage (guillemets supprimés, apostrophes normalisées, notes et symboles retirés, caractères inconnus du tokenizer
retirés, espaces insécables/invisibles, ligatures développées et mots recollés (`ré ﬂexion` → réflexion, sans toucher à `la ﬁn`),
`p. 12` → « page 12 », `No. 5` → « number 5 »/« numéro »), découpage en phrases qui respecte les abréviations, **aucun morceau de
ponctuation seule ni morceau final orphelin** (< 25 car. rattaché au précédent), un paragraphe sans rien à dire ne produit ni son ni
silence. Même texte et même voix sur la conversion réelle : similarité avec le texte 86,5 % → 93,0 %, mots ajoutés 34 → 3.
Tests : `build\runtime\python\python.exe -m unittest server.tests.test_speech_text server.tests.test_overlong -v` (sans GPU).
Ne pas remettre un découpage « naïf » dans `tts_engine.py`. Les scripts de diagnostic (Whisper) ne sont pas dans le dépôt : ne jamais
mettre Whisper dans `build\runtime` (1 Go de plus dans l'installateur).
### Licence et limites

- XTTS-v2 : licence Coqui CPML, **usage non commercial uniquement** (l'utilisateur le sait).
- Installateur non signé : SmartScreen affichera un avertissement.
- Testé : import MD/EPUB, conversion en mode chapitres, MP3/ZIP/M4B, jeton, installation et
  désinstallation silencieuses, synthèse GPU sur la RTX 5070 avec l'installateur actuel. La GTX 970
  a fonctionné avec l'ancien patch cu126 (pas encore reconfirmée avec l'installateur unique).
- **Non testés** : import PDF et DOCX, clonage de voix au micro (jamais testé dans un vrai
  navigateur), « Enregistrer sous » pour les téléchargements (comportement par défaut d'Electron).

### Pistes (optionnelles)

Compresser l'installateur principal (`lzma2`, plus lent), incruster l'icône dans l'exe, signer le
code, retirer des paquets inutiles (tensorboard, tests) pour gagner quelques centaines de Mo.

## Données à reprendre (optionnel)

Les voix créées par l'utilisateur (`data\voices\*.pt` + `*.json`) et les livres
(`data\books\<id>\`) de la version Docker sont compatibles tels quels. On peut les copier
depuis le dossier `data` de la version Docker de référence (sous WSL) vers
`%APPDATA%\BookReader`.
