# Khởi động toàn bộ môi trường dev: Docker (MySQL/Qdrant/MinIO) + Backend + Frontend.
# Chạy bằng cách bấm đúp start-dev.bat (file này không nên chạy trực tiếp bằng double-click
# vì Windows sẽ chặn theo Execution Policy mặc định).

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

Write-Host "== 1. Kiem tra Docker Desktop ==" -ForegroundColor Cyan
$dockerReady = $false
try {
    docker ps *> $null
    if ($LASTEXITCODE -eq 0) { $dockerReady = $true }
} catch {}

if (-not $dockerReady) {
    Write-Host "Dang khoi dong Docker Desktop, vui long doi..." -ForegroundColor Yellow
    $dockerExe = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    if (Test-Path $dockerExe) { Start-Process $dockerExe }
    $tries = 0
    while (-not $dockerReady -and $tries -lt 40) {
        Start-Sleep -Seconds 3
        docker ps *> $null
        if ($LASTEXITCODE -eq 0) { $dockerReady = $true }
        $tries++
    }
    if (-not $dockerReady) {
        Write-Host "Docker chua san sang sau 2 phut. Mo Docker Desktop thu cong roi chay lai script nay." -ForegroundColor Red
        exit 1
    }
}
Write-Host "Docker OK." -ForegroundColor Green

Write-Host "== 2. Khoi dong MySQL / Qdrant / MinIO ==" -ForegroundColor Cyan
docker compose up -d mysql qdrant minio

Write-Host "== 3. Cho MySQL healthy ==" -ForegroundColor Cyan
$healthy = $false
for ($i = 0; $i -lt 20; $i++) {
    $status = docker inspect --format='{{.State.Health.Status}}' ai20k_mysql 2>$null
    if ($status -eq "healthy") { $healthy = $true; break }
    Start-Sleep -Seconds 3
}
if ($healthy) { Write-Host "MySQL healthy." -ForegroundColor Green }
else { Write-Host "MySQL chua healthy, van tiep tuc thu..." -ForegroundColor Yellow }

Write-Host "== 3.1. Nap anh phan khu vao MinIO (project-images-source/) ==" -ForegroundColor Cyan
& "$root\.venv\Scripts\python.exe" "$root\scripts\upload_project_images.py"

Write-Host "== 4. Khoi dong Backend (cua so rieng) ==" -ForegroundColor Cyan
$backendCmd = "cd `"$root`"; `$env:DATABASE_URL='mysql+pymysql://salesmate:salesmate@localhost:3307/salesmate_db'; .\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 8000"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $backendCmd

Write-Host "== 5. Khoi dong Frontend (cua so rieng) ==" -ForegroundColor Cyan
$frontendCmd = "cd `"$root\frontend`"; npm run dev -- --host"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $frontendCmd

Write-Host "== 6. Cho frontend san sang roi mo trinh duyet ==" -ForegroundColor Cyan
Start-Sleep -Seconds 6
Start-Process "http://localhost:5173"

Write-Host "`nXong! Dung 2 cua so PowerShell moi mo de tat Backend/Frontend (dong cua so hoac Ctrl+C)." -ForegroundColor Green
