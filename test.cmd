@echo off
setlocal
set "NOVEL_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%NOVEL_PYTHON%" goto bundled
python -m unittest discover -s "%~dp0." -p test_*.py -v
exit /b
:bundled
"%NOVEL_PYTHON%" -m unittest discover -s "%~dp0." -p test_*.py -v
exit /b
