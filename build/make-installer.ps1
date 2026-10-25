# Étape finale : assemble l'installateur hors ligne dans dist\installer.
# Prérequis : build\prepare-runtime.ps1 (runtime), « npm run pack » (dist\win-unpacked), Inno Setup 6.
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$iscc = "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $iscc)) { $iscc = 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe' }
foreach ($p in "$PSScriptRoot\runtime\python\python.exe", "$root\dist\win-unpacked\BookReader.exe", $iscc) {
    if (-not (Test-Path $p)) { throw "Introuvable : $p" }
}
& $iscc "$PSScriptRoot\installer.iss"
if ($LASTEXITCODE) { throw 'Compilation Inno Setup echouee' }
Get-ChildItem "$root\dist\installer" | Select-Object Name, @{n = 'Go'; e = { [math]::Round($_.Length / 1GB, 2) } }
