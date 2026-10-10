@echo off
title Asli Kavach - demo launcher
cd /d "%~dp0"

if not exist "venv\Scripts\activate.bat" (
  echo Could not find the venv folder next to this file.
  pause
  exit /b 1
)

rem ---- Optional: for the "related web pages" panel, remove the word rem from the next line and paste your TinyFish key ----
rem set TINYFISH_API_KEY=PASTE_YOUR_KEY_HERE

set GRADIO_ANALYTICS_ENABLED=False
set HF_HUB_OFFLINE=1
set TRANSFORMERS_OFFLINE=1

echo Starting the backend. The models take a minute to load...
start "Asli Kavach backend" cmd /k "call venv\Scripts\activate.bat && python app.py"
start "Asli Kavach page server" cmd /k "call venv\Scripts\activate.bat && python serve.py"

set /a tries=0
:wait
set /a tries+=1
if %tries% gtr 80 goto failed
timeout /t 3 /nobreak >nul
powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing http://127.0.0.1:7860/ -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }"
if errorlevel 1 goto wait

start "" "http://127.0.0.1:8000/asli_kavach.html"
echo.
echo Ready. Leave the two black windows open during the demo.
timeout /t 5 >nul
exit /b 0

:failed
echo The backend did not start. Read the error in the "Asli Kavach backend" window.
pause
exit /b 1
