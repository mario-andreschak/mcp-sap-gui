@echo off
cd /d "%~dp0"
if /I "%~1"=="test" (
  python -m pytest tests
) else if /I "%~1"=="debug" (
  npx @modelcontextprotocol/inspector python -m sap_gui_server.server
) else (
  python -m sap_gui_server.server
)
