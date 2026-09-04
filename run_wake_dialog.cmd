@echo off
setlocal EnableExtensions DisableDelayedExpansion
set "BRIDGE_ROOT=%~dp0"
if not defined PEPPER_PYTHON3 if defined CONDA_ROOT if exist "%CONDA_ROOT%\python.exe" set "PEPPER_PYTHON3=%CONDA_ROOT%\python.exe"
if not defined PEPPER_PYTHON3 if defined CONDA_EXE if exist "%CONDA_EXE%\..\python.exe" set "PEPPER_PYTHON3=%CONDA_EXE%\..\python.exe"
if not defined PEPPER_PYTHON3 for /f "delims=" %%C in ('where conda 2^>nul') do if not defined PEPPER_PYTHON3 for %%D in ("%%~dpC..") do if exist "%%~fD\python.exe" set "PEPPER_PYTHON3=%%~fD\python.exe"
if not defined PEPPER_PYTHON3 set "PEPPER_PYTHON3=python.exe"
"%PEPPER_PYTHON3%" -c "import sys; sys.exit(0 if sys.version_info[0] >= 3 else 1)" >nul 2>&1
if errorlevel 1 (
    echo Python 3 was not found. Set PEPPER_PYTHON3 to the full path of python.exe. 1>&2
    exit /b 1
)
"%PEPPER_PYTHON3%" "%BRIDGE_ROOT%wake_dialog.py" %*
exit /b %errorlevel%
