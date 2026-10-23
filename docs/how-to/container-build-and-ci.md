# 容器构建与 CI 通道

**场景**：想用容器跑 rfauto，或核对"镜像真的能构建吗"。本文给出构建/
冒烟命令、CI 构建通道的现状与镜像内容边界。一处更正：早期 Dockerfile
头注写过"未真构建"（当时开发机没有 docker，只做过静态检查）——从
2026-10-23 起，公开仓的 CI 每次提交都会自动构建镜像，那个说法已过时。

## 1. 本机构建与冒烟（需本机有 docker）

```bash
docker build -t rfauto:local .     # 仓根执行；.dockerignore 已把
                                   # 构建上下文收到最小安装集
docker run --rm rfauto:local       # 入口冒烟：CMD=rfauto --help，退出码 0
docker run --rm rfauto:local rfauto doctor   # 任意子命令同理
```

**本机现状**：开发机无 docker CLI/守护，本地只做过静态校验
（runs/dockerfile_static_check.py：指令合法性、COPY 源存在性、CMD JSON
数组解析、基镜像与 requires-python 相容性）。真构建由下节 CI 通道持续
保证，本机拿到 docker 环境后按上面两条复验即可。

## 2. CI 真构建通道（公开仓）

`release/rfauto_public/.github/workflows/ci.yml` 的 `docker-build` job
（ubuntu-latest，runner 自带 docker）每次 push/PR：

1. `docker build -t rfauto:ci .`——只验证可构建，不 push 镜像；
2. 容器内 `python -c "import rfauto; print('ok')"`——import 冒烟；
3. 容器内 `python -c "import rfauto; print(rfauto.__version__)"`——
   版本元数据冒烟；
4. `docker run --rm rfauto:ci`（无参=默认 CMD）——CLI 帮助冒烟：验证
   命令入口（console script）装好了，CLI 各命令模块也能全部导入。

这个 job 同时长期验证一件事：只装核心依赖时，rfauto 在 linux 容器里
能自洽运行。2026-10-23 核对过：`rfauto` 与 `rfauto.cli.*` 的模块级导入
只用到核心依赖和标准库（逐模块比对核心依赖清单，没有顶层 import 任何
extras），核心依赖里也没有 pywin32 这类 Windows 专属包——`pip install .`
在 linux 容器里不会缺件报错。

## 3. 镜像内容边界

- 基镜像 `python:3.12-slim`，与 `requires-python = ">=3.10,<3.13"` 相容；
- 只装核心依赖（`pip install .`）：pydantic / omegaconf / loguru / rich /
  typer / numpy / scipy / scikit-rf / matplotlib / pandas / optuna——全部
  有 linux wheel；
- EDA SDK（HFSS/ADS/openEMS/COMSOL…）全在 extras，不进镜像：容器内
  真机求解不可用，fake 通道（内置的免仿真假求解适配器，测试与演示用）
  与纯确定性计算面可用；
- `tests/` 不在镜像内（wheel 打包只含 `src/rfauto`）——想在容器里跑
  测试子集需 COPY tests 或另设 dev 镜像，暂不做这层复杂度；linux 上的
  测试由同一 CI 的 pytest job（ubuntu-latest）负责。

## 4. 保鲜核对清单（改 pyproject / Dockerfile 时过一遍）

1. 基镜像 python 版本 ∈ `requires-python` 区间；
2. 新增**核心依赖**必须 linux 可装（有 manylinux wheel；不能是
   Windows-only 件）——违者 CI docker job 直接红，兜底做法是环境标记
   `; sys_platform == 'win32'` 或移入 extras（改前 grep 消费面）；
3. CLI 入口链（`rfauto.cli.*`）模块级导入不得引 extras（惰性 import
   纪律）——违者第 2 节第 4 步冒烟必红；
4. `.dockerignore` 与新增顶层目录同步（运行数据/本地环境/内部文档不入
   构建上下文）。
