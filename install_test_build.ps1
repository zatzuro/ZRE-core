param([string]$Root,[switch]$RestoreStable,[switch]$NoLaunch)
$ErrorActionPreference='Stop'
$registry='HKCU:\Software\ZRE'
$listeners=@(Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue)
if ($listeners.Count) {
    foreach ($ownerId in ($listeners.OwningProcess | Select-Object -Unique)) {
        $p=Get-CimInstance Win32_Process -Filter "ProcessId=$ownerId"
        $inferred=$null
        if ($p.ExecutablePath -match '^(.*)\\\.venv\\Scripts\\python(?:w)?\.exe$') { $inferred=$Matches[1] }
        if ($inferred -and (Test-Path (Join-Path $inferred 'start_dashboard.bat'))) {
            New-Item $registry -Force | Out-Null
            Set-ItemProperty $registry -Name InstallationRoot -Value $inferred
        }
        Write-Error "INSTALLATION STOPPED: puerto 8765 ocupado. PID: $ownerId; ejecutable: $($p.ExecutablePath); comando: $($p.CommandLine); root detectado: $inferred. Cierra ese puente y vuelve a ejecutar; no se modifica ni se reutiliza esa instancia." -ErrorAction Continue
    }
    exit 2
}
if (-not $Root) {
    $remembered=(Get-ItemProperty $registry -ErrorAction SilentlyContinue).InstallationRoot
    if ($remembered -and (Test-Path (Join-Path $remembered 'start_dashboard.bat'))) { $Root=$remembered }
    elseif (Test-Path (Join-Path $PSScriptRoot 'start_dashboard.bat')) { $Root=$PSScriptRoot }
    elseif (Test-Path (Join-Path (Get-Location).Path 'start_dashboard.bat')) { $Root=(Get-Location).Path }
    else {
        $candidates=@(Get-ChildItem -LiteralPath $env:USERPROFILE -Filter start_dashboard.bat -File -Recurse -Depth 4 -ErrorAction SilentlyContinue | Where-Object {
            (Test-Path (Join-Path $_.DirectoryName 'version.json')) -and (Test-Path (Join-Path $_.DirectoryName '.venv\Scripts\python.exe'))
        } | Select-Object -ExpandProperty DirectoryName -Unique)
        if ($candidates.Count -eq 1) { $Root=$candidates[0] }
        else { throw ('No hay una instalacion unica identificable. No se modifica ninguna carpeta. Candidatas: ' + ($candidates -join '; ') + '. Ejecuta desde la carpeta de tu launcher habitual o con -Root explicito.') }
    }
}
$Root=(Resolve-Path -LiteralPath $Root).Path
$python=Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path $python) -or -not (Test-Path (Join-Path $Root 'start_dashboard.bat'))) { throw "No es una instalacion ZRE existente: $Root" }
$before=Get-Content (Join-Path $Root 'version.json') -Raw | ConvertFrom-Json
Write-Host "INSTALACION IDENTIFICADA: $Root | version actual: $($before.version)"
New-Item $registry -Force | Out-Null
Set-ItemProperty $registry -Name InstallationRoot -Value $Root
$tempUpdater=Join-Path ([IO.Path]::GetTempPath()) ('zre-updater-'+[guid]::NewGuid()+'.py')
try {
    $commit=Invoke-RestMethod 'https://api.github.com/repos/zatzuro/ZRE-core/commits/develop%2F2.6.5.1' -TimeoutSec 30
    if ($commit.sha -notmatch '^[0-9a-f]{40}$') { throw 'Commit invalido.' }
    Invoke-WebRequest ('https://raw.githubusercontent.com/zatzuro/ZRE-core/'+$commit.sha+'/updater.py') -OutFile $tempUpdater -UseBasicParsing -TimeoutSec 30
    if ($RestoreStable) { & $python $tempUpdater --root $Root --restore-stable }
    else { & $python $tempUpdater --root $Root --test-ref develop/2.6.5.1 }
    if ($LASTEXITCODE -ne 0) { throw 'Instalacion fallida; no se inicia ZRE.' }
    $state=Get-Content (Join-Path $Root '.zre-build.json') -Raw | ConvertFrom-Json
    if (-not $RestoreStable -and ($state.mode -ne 'TEST' -or $state.version -ne '2.6.5.1')) { throw 'No se activo TEST 2.6.5.1.' }
    Write-Host "$($state.mode) BUILD ACTIVE`nZRE Core $($state.version)`ncommit: $($state.sourceCommit)`nroot: $Root"
    if (-not $NoLaunch) {
        Start-Process -FilePath (Join-Path $Root 'start_dashboard.bat') -WorkingDirectory $Root
        $runtime=$null
        for ($attempt=0;$attempt -lt 90;$attempt++) {
            try { $runtime=Invoke-RestMethod 'http://127.0.0.1:8765/version' -TimeoutSec 1; break } catch { Start-Sleep -Seconds 1 }
        }
        if (-not $runtime -or $runtime.root -ne $Root -or $runtime.mode -ne $state.mode -or $runtime.sourceCommit -ne $state.sourceCommit -or $runtime.runtimeVersion -ne $state.version -or $runtime.installedVersion -ne $state.version -or -not $runtime.assetsVerified) {
            throw "Runtime no verificado para $Root. Revisa la ventana del launcher."
        }
        $owners=@(Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction Stop).OwningProcess
        if ($runtime.pid -notin $owners) { throw 'El PID del runtime no coincide con el dueno del puerto 8765.' }
        Write-Host "runtime verified: $($runtime.runtimeVersion) | PID: $($runtime.pid) | root: $($runtime.root)"
    }
} finally { Remove-Item -LiteralPath $tempUpdater -ErrorAction SilentlyContinue }
