$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonBuild = Join-Path $PSScriptRoot 'venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonBuild)) {
    throw 'Crie o ambiente venv e instale requirements-build.txt antes de compilar.'
}
$env:QT_API = 'pyqt6'
# PyInstaller writes progress to stderr; Windows PowerShell must not treat
# redirected progress messages as terminating errors.
$ErrorActionPreference = 'Continue'
& $pythonBuild -m PyInstaller --noconfirm StudioDesenho.spec
$buildExitCode = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
if ($buildExitCode -ne 0) { throw 'Falha ao compilar o executavel.' }
Write-Host "Executavel standalone: $PSScriptRoot\dist\StudioDesenho.exe"
