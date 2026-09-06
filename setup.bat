@echo off
cd /d "%~dp0"
call build.bat
if errorlevel 1 exit /b %errorlevel%
if not exist .env copy .env.example .env >nul
echo Edit .env to select the intended SAP session, then run run.bat.
echo Existing Windows/SAP SSO sessions do not require a password.
