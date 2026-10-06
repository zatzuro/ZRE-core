# Thin Windows entrypoint for the existing ZRE updater. No persistent channel change.
param([string]$Root, [switch]$RestoreStable)
$ErrorActionPreference = 'Stop'
if (-not $Root) {
    Add-Type -AssemblyName System.Windows.Forms
    $picker = New-Object System.Windows.Forms.OpenFileDialog
    $picker.Title = 'Selecciona start_dashboard.bat de tu ZRE actual (cierra ZRE primero)'
    $picker.Filter = 'ZRE launcher (start_dashboard.bat)|start_dashboard.bat'
    if ($picker.ShowDialog() -ne 'OK') { exit 1 }
    $Root = Split-Path -Parent $picker.FileName
}
$Root = (Resolve-Path -LiteralPath $Root).Path
$python = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'No encuentro el Python de tu ZRE actual. Selecciona su carpeta instalada.' }
if (-not (Test-Path -LiteralPath (Join-Path $Root 'start_dashboard.bat'))) { throw 'Carpeta ZRE incorrecta.' }
# Refuse to modify assets while the local bridge is running.
$running = $false
try { $null = Invoke-RestMethod 'http://localhost:8765/version' -TimeoutSec 2; $running = $true } catch {}
if ($running) { throw 'Cierra la ventana del puente ZRE antes de instalar y vuelve a ejecutar.' }
$tempUpdater = Join-Path ([IO.Path]::GetTempPath()) ('zre-updater-' + [guid]::NewGuid() + '.py')
try {
    $ref = 'develop/2.6.5.1'
    $commit = Invoke-RestMethod 'https://api.github.com/repos/zatzuro/ZRE-core/commits/develop%2F2.6.5.1' -TimeoutSec 30
    if ($commit.sha -notmatch '^[0-9a-f]{40}$') { throw 'Commit GitHub inválido.' }
    Invoke-WebRequest ('https://raw.githubusercontent.com/zatzuro/ZRE-core/' + $commit.sha + '/updater.py') -OutFile $tempUpdater -UseBasicParsing -TimeoutSec 30
    if ($RestoreStable) { & $python $tempUpdater --root $Root --restore-stable }
    else { & $python $tempUpdater --root $Root --test-ref $ref }
    if ($LASTEXITCODE -ne 0) { throw 'No se instaló la build. Revisa el error del updater; no inicies una versión incorrecta.' }
    $meta = Get-Content -LiteralPath (Join-Path $Root 'version.json') -Raw | ConvertFrom-Json
    if (-not $RestoreStable -and $meta.version -ne '2.6.5.1') { throw 'La instalación no reporta 2.6.5.1.' }
    Write-Host ('ZRE Core v' + $meta.version + ' instalada en ' + $Root)
    Start-Process -FilePath (Join-Path $Root 'start_dashboard.bat') -WorkingDirectory $Root
} finally { Remove-Item -LiteralPath $tempUpdater -ErrorAction SilentlyContinue }
