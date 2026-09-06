@echo off
cd /d "%~dp0"
python -m pip install -r requirements-dev.txt
if errorlevel 1 exit /b %errorlevel%
python -m build
