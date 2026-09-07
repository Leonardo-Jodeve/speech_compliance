@echo off
setlocal
pushd "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Python environment missing. Run: powershell -File scripts\setup.ps1
    popd
    pause
    exit /b 1
)
echo Open http://127.0.0.1:8000 in your browser.
echo Close this window or press Ctrl+C to stop the server.
".venv\Scripts\python.exe" -X utf8 -m app.runners.web %*
popd
pause
