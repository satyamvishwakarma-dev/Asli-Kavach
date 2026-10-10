@echo off
title Asli Kavach - first-time setup
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python 3.11, 3.12 or 3.13 from python.org
  echo and tick "Add python.exe to PATH" in the installer. Then run this file again.
  pause
  exit /b 1
)

if not exist "venv\Scripts\activate.bat" (
  echo Creating the virtual environment...
  python -m venv venv
)

call venv\Scripts\activate.bat
python -m pip install --upgrade pip

if exist requirements_frozen.txt (
  echo Installing the exact versions from requirements_frozen.txt ...
  pip install -r requirements_frozen.txt
) else (
  echo Installing from requirements.txt ...
  pip install -r requirements.txt
)

echo.
python -c "import cv2; print('OpenCV', cv2.__version__, 'face finder OK' if hasattr(cv2,'CascadeClassifier') else 'PROBLEM: no face finder - run: pip install opencv-python==4.12.0.88')"
echo.
echo Setup finished. Now double-click start_demo.bat
pause
