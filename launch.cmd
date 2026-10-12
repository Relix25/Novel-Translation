@echo off
setlocal
set "NOVEL_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%NOVEL_PYTHON%" goto bundled
python "%~dp0app.py" %*
exit /b
:bundled
"%NOVEL_PYTHON%" "%~dp0app.py" %*
exit /b
