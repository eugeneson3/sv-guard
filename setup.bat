@echo off
rem One-click setup for SV-Guard: installs Python if needed, then the IDE and its desktop icon,
rem and starts it. The work happens in scripts\install.ps1; this file only starts it.
chcp 65001 >nul
if not exist "%~dp0scripts\install.ps1" (
    echo 압축을 먼저 풀어 주세요: ZIP 파일을 마우스 오른쪽 버튼으로 누르고 "압축 풀기"를 고른 뒤,
    echo 풀린 폴더 안의 setup.bat을 실행하세요.
    pause
    exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install.ps1"
