@echo off
setlocal
pushd "%~dp0"
set "NOVEL_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%NOVEL_PYTHON%" goto bundled
python -m unittest discover -s tests -p test_*.py -v
goto finished
:bundled
"%NOVEL_PYTHON%" -m unittest discover -s tests -p test_*.py -v
:finished
set "NOVEL_TEST_EXIT=%errorlevel%"
popd
exit /b %NOVEL_TEST_EXIT%
