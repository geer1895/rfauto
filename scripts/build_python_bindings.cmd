@echo off
REM openEMS Python bindings build (CSXCAD + openEMS packages into project venv)
REM Prereqs: venv has pip/setuptools/cython/setuptools_scm/numpy/matplotlib/h5py (uv pip install)
REM Usage: scripts\build_python_bindings.cmd
setlocal
call "C:\Program Files (x86)\Microsoft Visual Studio\2019\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b 1

REM Cython 3.3 output needs C++17; setup.py adds no /std flag on MSVC -> inject via CL
set "CL=/std:c++17"
set "CSXCAD_INSTALL_PATH=E:\openEMS\install"
set "OPENEMS_INSTALL_PATH=E:\openEMS\install"
set "PATH=E:\openEMS\install\bin;%PATH%"
set "PY=D:/rf_workspace\.venv\Scripts\python.exe"

echo === building CSXCAD binding ===
pushd E:\openEMS\openEMS-Project-git\CSXCAD\python
%PY% -m pip install --no-build-isolation --no-deps .
if errorlevel 1 popd & exit /b 1
popd

echo === building openEMS binding ===
pushd E:\openEMS\openEMS-Project-git\openEMS\python
%PY% -m pip install --no-build-isolation --no-deps .
if errorlevel 1 popd & exit /b 1
popd

echo === smoke import ===
%PY% -c "import CSXCAD, openEMS; print('CSXCAD', CSXCAD.__version__ if hasattr(CSXCAD,'__version__') else 'ok'); print('openEMS ok')"
endlocal
