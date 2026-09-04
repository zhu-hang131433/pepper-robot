@echo off
setlocal EnableExtensions DisableDelayedExpansion
set "BRIDGE_ROOT=%~dp0"
if not defined NAOQI_SDK_ROOT for /f "tokens=2,*" %%A in ('reg query "HKCU\Environment" /v NAOQI_SDK_ROOT 2^>nul') do if /I "%%A"=="REG_SZ" set "NAOQI_SDK_ROOT=%%B"
if not defined PEPPER_ROBOT_IP set "PEPPER_ROBOT_IP=192.168.0.100"
if not defined PEPPER_SDK_ROOT if defined NAOQI_SDK_ROOT set "PEPPER_SDK_ROOT=%NAOQI_SDK_ROOT%"
if not defined PEPPER_SDK_ROOT set "PEPPER_SDK_ROOT=%BRIDGE_ROOT%..\pynaoqi-python2.7-2.5.7.1-win64"
if not exist "%PEPPER_SDK_ROOT%" (
    echo Pepper NAOqi SDK path is invalid: "%PEPPER_SDK_ROOT%" 1>&2
    exit /b 1
)
if defined PEPPER_PYTHON goto validate_python
if exist "%USERPROFILE%\.conda\envs\py27\python.exe" set "PEPPER_PYTHON=%USERPROFILE%\.conda\envs\py27\python.exe"
if not defined PEPPER_PYTHON if exist "%USERPROFILE%\.conda\envs\python27\python.exe" set "PEPPER_PYTHON=%USERPROFILE%\.conda\envs\python27\python.exe"
if not defined PEPPER_PYTHON if exist "%CONDA_PREFIX%\python.exe" set "PEPPER_PYTHON=%CONDA_PREFIX%\python.exe"
if not defined PEPPER_PYTHON if exist "%PEPPER_SDK_ROOT%\python.exe" set "PEPPER_PYTHON=%PEPPER_SDK_ROOT%\python.exe"
if not defined PEPPER_PYTHON if exist "%PEPPER_SDK_ROOT%\bin\python.exe" set "PEPPER_PYTHON=%PEPPER_SDK_ROOT%\bin\python.exe"
if not defined PEPPER_PYTHON (
    where python2.7.exe >nul 2>&1
    if not errorlevel 1 set "PEPPER_PYTHON=python2.7.exe"
)
if not defined PEPPER_PYTHON set "PEPPER_PYTHON=python.exe"

:validate_python
"%PEPPER_PYTHON%" -c "import sys; sys.exit(0 if sys.version_info[0] == 2 else 1)" >nul 2>&1
if errorlevel 1 (
    echo Python 2.7 was not found. Set PEPPER_PYTHON to the full path of python.exe. 1>&2
    exit /b 1
)
set "PATH=%PEPPER_SDK_ROOT%;%PEPPER_SDK_ROOT%\bin;%PEPPER_SDK_ROOT%\lib;%PATH%"
set "PYTHONPATH=%PEPPER_SDK_ROOT%;%PEPPER_SDK_ROOT%\lib;%PEPPER_SDK_ROOT%\lib\python2.7\site-packages;%PEPPER_SDK_ROOT%\lib\site-packages;%PYTHONPATH%"
"%PEPPER_PYTHON%" "%BRIDGE_ROOT%pepper_say.py" --robot-ip "%PEPPER_ROBOT_IP%" --language Chinese %*
exit /b %errorlevel%
