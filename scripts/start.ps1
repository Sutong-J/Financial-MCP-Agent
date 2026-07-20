# Financial MCP Agent - local startup script (Windows)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "==> Financial MCP Agent Web UI" -ForegroundColor Cyan
Write-Host "Project root: $Root"

New-Item -ItemType Directory -Force -Path (Join-Path $Root "data\reports") | Out-Null

$Python = $null
if ($env:CONDA_PREFIX) {
    $condaPython = Join-Path $env:CONDA_PREFIX "python.exe"
    if (Test-Path $condaPython) {
        $Python = $condaPython
    }
}

if (-not $Python) {
    $Candidates = @(
        "D:\Anacodna3\envs\agent\python.exe",
        "python"
    )
    foreach ($c in $Candidates) {
        if ($c -eq "python") {
            if (Get-Command python -ErrorAction SilentlyContinue) {
                $Python = "python"
                break
            }
        }
        elseif (Test-Path $c) {
            $Python = $c
            break
        }
    }
}

if (-not $Python) {
    Write-Host "Python not found. Activate conda env 'agent' and retry." -ForegroundColor Red
    exit 1
}

Write-Host "Python: $Python"

function Stop-PortListeners {
    param([int[]]$Ports)
    foreach ($port in $Ports) {
        $conns = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
        foreach ($conn in $conns) {
            $procId = $conn.OwningProcess
            if ($procId -and $procId -ne 0) {
                Write-Host "==> Stopping process $procId on port $port" -ForegroundColor Yellow
                Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
            }
        }
    }
    Start-Sleep -Seconds 2
}

Stop-PortListeners -Ports @(8000, 3000)

& $Python -m pip install -q fastapi "uvicorn[standard]" sqlalchemy sse-starlette "python-jose[cryptography]" bcrypt email-validator chromadb openai 2>$null

Write-Host "==> Starting FastAPI on http://127.0.0.1:8000" -ForegroundColor Green
$backend = Start-Process -FilePath $Python -ArgumentList @(
    "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", "8000"
) -WorkingDirectory $Root -PassThru -WindowStyle Normal

Start-Sleep -Seconds 4

try {
    $health = Invoke-WebRequest -Uri "http://127.0.0.1:8000/openapi.json" -UseBasicParsing -TimeoutSec 10
    if ($health.Content -notmatch '"/api/auth/register"') {
        Write-Host "WARNING: Backend started but auth routes missing. Close old backend window and rerun start.ps1." -ForegroundColor Red
    }
}
catch {
    Write-Host "WARNING: Backend health check failed. Check the uvicorn window for errors." -ForegroundColor Red
}

$WebDir = Join-Path $Root "web"
if (-not (Test-Path (Join-Path $WebDir "node_modules"))) {
    Write-Host "==> Installing npm dependencies..." -ForegroundColor Yellow
    Push-Location $WebDir
    npm install
    Pop-Location
}

# Fix broken Next.js cache (app-paths-manifest.json missing)
$NextCache = Join-Path $WebDir ".next"
$Manifest = Join-Path $NextCache "server\app-paths-manifest.json"
if ((Test-Path $NextCache) -and -not (Test-Path $Manifest)) {
    Write-Host "==> Cleaning incomplete Next.js cache (.next)..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force $NextCache
}

Write-Host "==> Starting Next.js on http://localhost:3000" -ForegroundColor Green
Push-Location $WebDir
$frontend = Start-Process -FilePath "npm.cmd" -ArgumentList @("run", "dev") -PassThru -WindowStyle Normal
Pop-Location

Write-Host "==> Waiting for Next.js to be ready..." -ForegroundColor Yellow
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    try {
        $resp = Invoke-WebRequest -Uri "http://localhost:3000/login" -UseBasicParsing -TimeoutSec 3
        if ($resp.StatusCode -eq 200) {
            $ready = $true
            break
        }
    }
    catch {
        Start-Sleep -Seconds 2
    }
}

if ($ready) {
    Start-Process "http://localhost:3000/login"
}
else {
    Write-Host "Next.js not ready yet. Open manually: http://localhost:3000/login" -ForegroundColor Yellow
}

Write-Host ""
Write-Host ("Backend PID:  {0}" -f $backend.Id) -ForegroundColor DarkGray
Write-Host ("Frontend PID: {0}" -f $frontend.Id) -ForegroundColor DarkGray
Write-Host "Stop services with Ctrl+C in the backend/frontend windows." -ForegroundColor Yellow
