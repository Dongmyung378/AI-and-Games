@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m hexai %*
) else (
  where py >nul 2>nul
  if not errorlevel 1 (
    py -3 -m hexai %*
  ) else (
    python -m hexai %*
  )
)
exit /b %errorlevel%
