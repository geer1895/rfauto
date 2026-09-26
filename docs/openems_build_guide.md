# openEMS Windows Build Guide

## Overview

openEMS requires compilation from source on Windows. The process involves:
1. Installing build tools (CMake, Visual Studio Build Tools)
2. Installing dependencies (TinyXML, HDF5, CGAL, Boost, VTK)
3. Compiling openEMS and its dependencies

**Estimated time**: 1-2 hours (mostly dependency compilation)

## 实测经验（2026-08-31 批次，先读再动手）

1. **依赖清单以 CSXCAD/openEMS 的 CMakeLists 为准**：TinyXML、HDF5 (C HL)、
   CGAL、Boost (system thread date_time serialization chrono program_options)、
   VTK (IOXML/IOGeometry/IOLegacy/IOPLY)。MPI 可选（不开 WITH_MPI 不需要）。
2. **vcpkg 首次运行会下载 powershell-core**：经代理下载 117MB 的
   PowerShell-7.6.4-win-x64.zip 极易反复断流（.part 文件堆积）。
   对策：用 `curl -C -` 断点续传手动下到 `C:\vcpkg\downloads\`，
   vcpkg 会校验哈希后直接使用缓存。
3. **不要装 `boost` 超级包**（1.92 共 221 个组件）：会拉进 boost-cobalt
   等需要 C++20 协程的组件，VS2019 (MSVC 14.29) 直接编挂。
   对策：只装 openEMS 实际需要的组件
   `boost-system boost-thread boost-date-time boost-serialization
   boost-chrono boost-program-options`。
4. **CLI 用途推荐 `-DBUILD_APPCSXCAD=NO`**：跳过 QCSXCAD/AppCSXCAD
   可避开整个 Qt 依赖链，编译时间大幅缩短。
5. **代理不稳时用重试循环**：vcpkg 遇断流即整体退出，但已构建的包
   有缓存，`for /L %i in (1,1,30) do (vcpkg install ... && exit)` 循环
   即可自愈；GitHub 下载逐包计入 downloads/ 缓存。
6. **ExternalProject 的依赖注入靠 toolchain**：顶层 CMake 把
   CMAKE_TOOLCHAIN_FILE 透传给每个子项目，所以 toolchain 必须在
   顶层 configure 时传入；事后改缓存无效（需删 build 目录重来）。
7. **构建中断恢复**：直接 `cmake --build build --config Release` 即可，
   ExternalProject 会从上次失败的子项目继续。

## Step 1: Install Build Tools

### CMake
```bash
winget install Kitware.CMake
```

### Visual Studio Build Tools 2019/2022
```bash
winget install Microsoft.VisualStudio.2022.BuildTools
```

## Step 2: Install Dependencies with vcpkg

### Install vcpkg
```bash
git clone https://github.com/microsoft/vcpkg.git C:\vcpkg
cd C:\vcpkg
bootstrap-vcpkg.bat
```

### Install dependencies
```bash
cd C:\vcpkg
vcpkg install tinyxml hdf5 cgal vtk --triplet x64-windows
```

**Note**: This step takes 30-60 minutes as it compiles all dependencies from source.

## Step 3: Clone openEMS-Project

下文 `%OPENEMS_ROOT%` 为自选安装根（例：`D:\openEMS`），按需替换。

```bash
git clone --recursive https://github.com/thliebig/openEMS-Project.git %OPENEMS_ROOT%\openEMS-Project
```

## Step 4: Build openEMS（推荐配置：跳过 GUI）

```bash
cd /d %OPENEMS_ROOT%\openEMS-Project
mkdir build && cd build
cmake .. -G "Visual Studio 16 2019" -A x64 ^
  -DCMAKE_TOOLCHAIN_FILE=C:\vcpkg\scripts\buildsystems\vcpkg.cmake ^
  -DCMAKE_INSTALL_PREFIX=%OPENEMS_ROOT%\install ^
  -DBUILD_APPCSXCAD=NO
cmake --build . --config Release
cmake --install .
```

> 已有的 build 目录若 configure 时没带 toolchain，必须删掉重新 configure
> （CMakeCache 里的 toolchain 是 configure 期固化的）。

## Step 5: Verify Installation

```bash
# Check executable
%OPENEMS_ROOT%\install\bin\openEMS.exe --version
```

Python 绑定（CSXCAD/openEMS 包）随编译安装；rfauto 模板生成的
simulation.py 需要绑定可用（`python -c "import CSXCAD, openEMS"`）。

## Integration with rfauto

After openEMS is built:
1. 确认 `configs/solvers.yaml` 的 exe_path 指向编译产物
2. Run `rfauto doctor` to verify
3. wilkinson 模板冒烟：
   `solver.build_geometry({"template": "wilkinson", "params": {...}})` →
   `solver.solve()` → 解析 sparams.csv

## Troubleshooting

### PowerShell download stalls (proxy)
见"实测经验"第 2 条。`C:\vcpkg\downloads\*.part` 堆积 = 下载卡死的标志。

### TinyXML/HDF5/CGAL not found
toolchain 必须在顶层 configure 传入（Step 4），ExternalProject 才能继承；
必要时显式 `-DHDF5_ROOT=C:\vcpkg\installed\x64-windows`。

### Build fails with MSVC errors
- Ensure Visual Studio Build Tools are installed
- Run `vcvarsall.bat x64` before building

## Python bindings（2026-09-01 本机验证通过）

C++ exe 之外还需要 Python 绑定（CSXCAD/openEMS 包）才能跑模板仿真：

```bash
# 前置：项目 venv 有 pip/setuptools/cython/setuptools_scm/numpy/matplotlib/h5py
uv pip install --python .venv\Scripts\python.exe pip setuptools wheel cython setuptools_scm matplotlib h5py
# 一条命令构建并安装进项目 venv（内部已处理 vcvars64 + /std:c++17 + INSTALL_PATH）：
scripts\build_python_bindings.cmd
```

实测要点：

- Cython 3.3 产物需 C++17，绑定 setup.py 在 MSVC 下不传 `/std` → 用 `CL`
  环境变量注入，不改上游 setup.py；
- 运行时 import 需
  `os.add_dll_directory(<OPENEMS_ROOT>\install\bin)`（目录经
  OPENEMS_INSTALL_PATH / RFAUTO_OPENEMS_BIN 环境变量注入）——单加
  PATH 不保证 .pyd 的 DLL 依赖解析；rfauto 的 OpenEMSSolver.solve 已用
  `_rfauto_runner.py` 引导脚本自动注入；
- 绑定走 openEMS.dll **进程内**求解，solvers.yaml 的 exe_path 只用于
  doctor/可用性探测；
- **线程数旋钮 numThreads**：绑定消费点是 `FDTD.Run(..., numThreads=N)`
  kwarg（openEMS.pyx `Run`，缺省 0=auto），非构造参数；本机构建是
  boost::thread 无 OpenMP，`OMP_NUM_THREADS` 无效。实测（runs/df7_e5）：
  钉 8 线程 146.8 MC/s 比 auto 快 20%+，且 FDTD 结果逐位=线程数敏感
  （并行求和序）——逐位可复现场景钉 8。当前 `configs/solvers.yaml` 的
  `num_threads` 为注释键（渲染层各模板 `FDTD.Run` 硬编码、extra_params
  尚无 →Run kwargs 透传点，接线需模板面逐处开洞，另行立项）；
- 模板已内置 `disable_dumps` / `SetEndCriteria(1e-4)` / `SetMaxTime(30ns)`。
  裸写脚本别用默认值：默认场时域 dump 是 GB 级文件、默认 -60dB 收敛判据
  在开路微带结构上是小时级时长；
- 网格线构造避开 `arange(..., -H_SUB+eps, MESH)` 形态——浮点毛刺会产生
  重复线，金属面被判 Unused primitive → 探针全 NaN。
