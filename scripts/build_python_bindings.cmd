@echo off
REM openEMS Python bindings build (CSXCAD + openEMS packages into project venv)
REM Prereqs: venv has pip/setuptools/cython/setuptools_scm/numpy/matplotlib/h5py (uv pip install)
REM Usage:  set OPENEMS_ROOT=D:\openEMS   (optional, defaults to D:\openEMS; must
REM         contain openEMS-Project-git\{CSXCAD,openEMS}\python and install\)
REM         scripts\build_python_bindings.cmd
setlocal
call "C:\Program Files (x86)\Microsoft Visual Studio\2019\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b 1

REM Cython 3.3 output needs C++17; setup.py adds no /std flag on MSVC -> inject via CL
set "CL=/std:c++17"
if "%OPENEMS_ROOT%"=="" set "OPENEMS_ROOT=D:\openEMS"
set "CSXCAD_INSTALL_PATH=%OPENEMS_ROOT%\install"
set "OPENEMS_INSTALL_PATH=%OPENEMS_ROOT%\install"
set "PATH=%OPENEMS_ROOT%\install\bin;%PATH%"
set "PY=%~dp0..\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

echo === building CSXCAD binding ===
pushd "%OPENEMS_ROOT%\openEMS-Project-git\CSXCAD\python"
%PY% -m pip install --no-build-isolation --no-deps .
if errorlevel 1 popd & exit /b 1
popd

echo === building openEMS binding ===
pushd "%OPENEMS_ROOT%\openEMS-Project-git\openEMS\python"
%PY% -m pip install --no-build-isolation --no-deps .
if errorlevel 1 popd & exit /b 1
popd

echo === smoke import ===
%PY% -c "import CSXCAD, openEMS; print('CSXCAD', CSXCAD.__version__ if hasattr(CSXCAD,'__version__') else 'ok'); print('openEMS ok')"
endlocal
