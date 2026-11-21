@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv || exit /b 1
)
if not exist "dist\index.html" (
  call npm.cmd ci || exit /b 1
  call npm.cmd run build || exit /b 1
)
".venv\Scripts\python.exe" -c "import fastapi,uvicorn,openai,pint" 2>nul
if errorlevel 1 ".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m uvicorn backend.main:app --host 127.0.0.1 --port 8765

