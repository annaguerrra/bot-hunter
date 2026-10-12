$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskRoot
$taskPython = Join-Path $taskRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    if (Get-Command py -ErrorAction SilentlyContinue) { & py -3 -m venv .venv }
    elseif (Get-Command python -ErrorAction SilentlyContinue) { & python -m venv .venv }
    else { throw 'Instale Python 3.12 ou superior em https://www.python.org/downloads/ e execute INICIAR.cmd novamente.' }
    if ($LASTEXITCODE -ne 0) { throw 'Nao foi possivel preparar Python.' }
}
$taskRequirements = Get-FileHash -LiteralPath (Join-Path $taskRoot 'requirements.txt') -Algorithm SHA256
$taskStamp = Join-Path $taskRoot '.venv\hunter-requirements.sha256'
if (-not (Test-Path -LiteralPath $taskStamp) -or (Get-Content -LiteralPath $taskStamp) -ne $taskRequirements.Hash) {
    & $taskPython -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Nao foi possivel instalar as dependencias.' }
    Set-Content -LiteralPath $taskStamp -Value $taskRequirements.Hash
}
if (-not (Test-Path -LiteralPath '.env')) { New-Item -Path '.env' -ItemType File | Out-Null }
$taskUrl = 'http://127.0.0.1:5000'
try { $taskResponse = Invoke-WebRequest -Uri "$taskUrl/api/auth/session" -UseBasicParsing -TimeoutSec 3 } catch { $taskResponse = $null }
if (-not $taskResponse -or $taskResponse.StatusCode -ne 200) {
    New-Item -Path logs -ItemType Directory -Force | Out-Null
    $taskProcess = Start-Process -FilePath $taskPython -ArgumentList '-u','serve.py' -WorkingDirectory $taskRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $taskRoot 'logs\web.log') -RedirectStandardError (Join-Path $taskRoot 'logs\web-error.log') -PassThru
    Set-Content -LiteralPath 'logs\web.pid' -Value $taskProcess.Id
    $taskReady = $false
    for ($taskAttempt = 0; $taskAttempt -lt 30; $taskAttempt++) {
        try { Invoke-WebRequest -Uri "$taskUrl/health" -UseBasicParsing -TimeoutSec 2 | Out-Null; $taskReady = $true; break } catch { Start-Sleep -Milliseconds 500 }
    }
    if (-not $taskReady) { throw 'O servidor nao iniciou. Consulte logs\web-error.log.' }
}
Start-Process $taskUrl
Write-Output "Bot Hunter aberto em $taskUrl. A automacao funciona com o computador desligado; consulte docs\automation.md."
