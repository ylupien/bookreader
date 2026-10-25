# Prépare tout ce qu'il faut embarquer dans l'installateur hors ligne :
#   build\runtime\python  Python 3.11 autonome avec toutes les dépendances (torch cu128 inclus)
#   build\runtime\models  modèle XTTS-v2
#   build\runtime\bin     ffmpeg.exe / ffprobe.exe
# À lancer UNE fois par version, sur une machine avec internet. N'utilise pas le GPU.
param([string]$FfmpegDir = 'C:\Program Files\ffmpeg-8.0-full_build\bin')

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$rt = Join-Path $PSScriptRoot 'runtime'
Set-Location $root

if (Test-Path $rt) { Remove-Item $rt -Recurse -Force }
New-Item -ItemType Directory $rt, "$rt\bin", "$rt\models" | Out-Null

# 1. Python autonome (python-build-standalone, déplaçable) copié depuis le cache de uv
uv python install 3.11
$pyHome = (Get-ChildItem (uv python dir).Trim() -Directory |
    Where-Object { $_.Name -like 'cpython-3.11.*' -and -not $_.LinkType } |
    Sort-Object Name | Select-Object -Last 1).FullName
if (-not $pyHome) { throw 'Python 3.11 de uv introuvable' }
# (robocopy : le dossier de uv est une jonction, Copy-Item n'en copierait pas le contenu)
robocopy $pyHome "$rt\python" /E /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw 'Copie de Python echouee' }
$rtPy = "$rt\python\python.exe"

# 2. Dépendances exactement figées par uv.lock
$req = Join-Path $rt 'requirements.txt'
uv export --frozen --no-emit-project --no-hashes -o $req | Out-Null
# Cette copie est faite pour être modifiée : on retire le marqueur « externally managed » de uv
Get-ChildItem "$rt\python" -Recurse -Filter EXTERNALLY-MANAGED | Remove-Item
uv pip install --python $rtPy --no-cache --extra-index-url https://download.pytorch.org/whl/cu128 `
    --index-strategy unsafe-best-match -r $req
if ($LASTEXITCODE) { throw 'Installation des dependances echouee' }
Remove-Item $req

# 3. Modèle XTTS-v2 (téléchargement seul, sans charger le GPU)
# (coqui-tts 0.28 télécharge via Hugging Face : HF_HOME décide où va le modèle)
$env:TTS_HOME = "$rt\models"
$env:HF_HOME = "$rt\models\hf"
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = '1'
$env:COQUI_TOS_AGREED = '1'
& $rtPy -I -c "from TTS.utils.manage import ModelManager; print(ModelManager().download_model('tts_models/multilingual/multi-dataset/xtts_v2'))"
if ($LASTEXITCODE) { throw 'Téléchargement du modèle échoué' }

# 4. ffmpeg
Copy-Item "$FfmpegDir\ffmpeg.exe", "$FfmpegDir\ffprobe.exe" "$rt\bin"

"{0:N1} Go dans $rt" -f ((Get-ChildItem $rt -Recurse -File | Measure-Object Length -Sum).Sum / 1GB)
