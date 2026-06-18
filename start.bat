@echo off
title LPR System
chcp 65001 >nul

echo [1/4] MinIO...
start "MinIO" /min D:\MinIo\minio.windows-amd64.RELEASE.2025-09-07T16-13-09Z.exe server D:\minio-data --console-address :9001
timeout /t 2 /nobreak >nul

echo [2/4] Flask...
start "Flask" cmd /c "cd /d %~dp0inference && python app.py"
timeout /t 5 /nobreak >nul

echo [3/4] Java...
start "Java" cmd /c "cd /d %~dp0backend && mvn spring-boot:run"
timeout /t 10 /nobreak >nul

echo [4/4] Vue...
start "Vue" cmd /c "cd /d %~dp0frontend && npm run dev"

echo Done! http://localhost:3000
pause
