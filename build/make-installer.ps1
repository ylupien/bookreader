# Étape finale : assemble l'installateur hors ligne dans dist\installer, puis crée
#   - BookReader-Setup.zip : tous les fichiers de l'installation (exe + .bin) en un seul fichier ;
#   - SHA256SUMS.txt       : sommes de contrôle de chaque fichier (compatible `sha256sum -c`).
# Prérequis : build\prepare-runtime.ps1 (runtime), « npm run pack » (dist\win-unpacked), Inno Setup 6.
# -ZipOnly : ne refait que le ZIP et les sommes (installateur déjà compilé).
# Pour publier le dossier sur le réseau local : docker compose --profile distribution up -d installer-server
param([switch]$ZipOnly)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$out = "$root\dist\installer"

if (-not $ZipOnly) {
    $iscc = "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    if (-not (Test-Path $iscc)) { $iscc = 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe' }
    foreach ($p in "$PSScriptRoot\runtime\python\python.exe", "$root\dist\win-unpacked\BookReader.exe", $iscc) {
        if (-not (Test-Path $p)) { throw "Introuvable : $p" }
    }
    & $iscc "$PSScriptRoot\installer.iss"
    if ($LASTEXITCODE) { throw 'Compilation Inno Setup echouee' }
}

# --- ZIP de tous les fichiers de l'installation ---
$parts = @(Get-ChildItem $out -File | Where-Object { $_.Name -like 'BookReader-Setup*' -and $_.Extension -in '.exe', '.bin' })
if (-not ($parts | Where-Object Extension -eq '.exe')) { throw "BookReader-Setup.exe introuvable dans $out (compiler d'abord l'installateur)" }
$zip = Join-Path $out 'BookReader-Setup.zip'
Remove-Item $zip -ErrorAction SilentlyContinue
$names = $parts | Sort-Object Name | ForEach-Object Name
Push-Location $out
try {
    $sevenZip = "$root\node_modules\7zip-bin\win\x64\7za.exe"   # fourni par electron-builder (npm install)
    if (Test-Path $sevenZip) {
        & $sevenZip a -tzip -mx=5 -mmt=on -bso0 -bsp0 $zip @names
        if ($LASTEXITCODE) { throw '7za a echoue' }
    } else {
        tar -a -c -f $zip @names   # tar de Windows (bsdtar) : ZIP64 pour les gros fichiers
        if ($LASTEXITCODE) { throw 'tar a echoue' }
    }
} finally { Pop-Location }

# --- Sommes de contrôle ---
$sums = Get-ChildItem $out -File | Where-Object { $_.Name -like 'BookReader-Setup*' } | Sort-Object Name | ForEach-Object {
    "{0} *{1}" -f (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower(), $_.Name
}
[IO.File]::WriteAllText("$out\SHA256SUMS.txt", ($sums -join "`n") + "`n", (New-Object Text.UTF8Encoding $false))

Get-ChildItem $out | Select-Object Name, @{n = 'Go'; e = { [math]::Round($_.Length / 1GB, 2) } }
