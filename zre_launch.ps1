param([switch]$Demo, [switch]$NoBrowser)
$ErrorActionPreference='Stop'
$Root=$PSScriptRoot
$listeners=@(Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue)
if ($listeners.Count) {
    foreach ($ownerId in ($listeners.OwningProcess | Select-Object -Unique)) {
        $p=Get-CimInstance Win32_Process -Filter "ProcessId=$ownerId"
        Write-Error "Puerto 8765 ocupado. PID: $ownerId; ejecutable: $($p.ExecutablePath); comando: $($p.CommandLine). No inicio ni reutilizo otra instancia." -ErrorAction Continue
    }
    exit 2
}
$python=Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    if (Get-Command py -ErrorAction SilentlyContinue) { & py -3 -m venv (Join-Path $Root '.venv') }
    elseif (Get-Command python -ErrorAction SilentlyContinue) { & python -m venv (Join-Path $Root '.venv') }
    else { throw 'Python no encontrado.' }
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear el entorno Python.' }
}
& $python (Join-Path $Root 'updater.py')
& $python -m pip install --disable-pip-version-check -q -r (Join-Path $Root 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'No se pudieron instalar las dependencias.' }
$arguments=@('-u', ('"'+(Join-Path $Root 'zre_runtime.py')+'"'))
if ($Demo) { $arguments+='--demo' }
$bridge=Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $Root -NoNewWindow -PassThru
try {
    $runtime=$null
    for ($attempt=0; $attempt -lt 60; $attempt++) {
        $bridge.Refresh(); if ($bridge.HasExited) { throw 'El puente termino antes de validar su identidad.' }
        try { $runtime=Invoke-RestMethod 'http://127.0.0.1:8765/version' -TimeoutSec 1; break } catch { Start-Sleep -Milliseconds 500 }
    }
    if (-not $runtime) { throw 'El puente no respondio.' }
    $meta=Get-Content (Join-Path $Root 'version.json') -Raw | ConvertFrom-Json
    if ($runtime.pid -ne $bridge.Id -or $runtime.root -ne $Root -or $runtime.runtimeVersion -ne $meta.version -or $runtime.installedVersion -ne $meta.version) {
        throw "Runtime incorrecto: PID $($runtime.pid), root $($runtime.root), version $($runtime.runtimeVersion). Esperado: PID $($bridge.Id), root $Root, version $($meta.version)."
    }
    Write-Host "$($runtime.mode) BUILD ACTIVE`nZRE Core $($runtime.runtimeVersion)`ncommit: $($runtime.sourceCommit)`nroot: $($runtime.root)`nruntime verified: $($runtime.runtimeVersion)"
    if (-not $NoBrowser) { Start-Process ('http://localhost:8765/?instance='+$runtime.instanceId) }
    Wait-Process -Id $bridge.Id
} finally {
    $bridge.Refresh();if (-not $bridge.HasExited) { Stop-Process -Id $bridge.Id -ErrorAction SilentlyContinue }
}
