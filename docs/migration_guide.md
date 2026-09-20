# 换机迁移指南（单工作区方案）

> 场景：项目（代码+数据+免 license 求解器+缓存）整体放在**一个工作区
> 文件夹**里（下文记作 `<工作区>`，例如 `D:\rfauto`），可整体搬到移动
> 硬盘再拷贝到新机继续开发。
> **单工作区原则**：开发所需的一切（代码+数据+免 license 求解器+缓存）
> 都收进**一个文件夹**——备份/迁移只拷一个夹。openEMS 运行时放进工作区
> `vendor\` 子目录（已 gitignore，GPL 二进制永不入库），路径经
> `RFAUTO_OPENEMS_BIN` 环境变量注入（configs/solvers.yaml 以
> `${RFAUTO_OPENEMS_BIN}` 可移植形式引用）。
> 仍在工作区**外**的只有商用 EDA（HFSS/ADS/KiCad，需自行重装+授权）——
> 这是"单文件夹"方案的物理上限。

## 1. 要拷贝什么

| # | 源（旧机工作区内） | 拷到新机 | 说明 |
|---|---|---|---|
| 1 | `<工作区>` **整个目录** | 新机任意盘下同名目录 | git 仓库/源码/测试/配方/skills/docs 全在；**排除** `.venv`、`__pycache__`、`.pytest_cache`（重建）。**runs/ 全拷**——体积小，含不可再生的校准数据集与证据链 |
| 2 | `<openEMS 安装根>\install`（自编译产物） | `<工作区>\vendor\openEMS\install` | **放进工作区**。自包含 exe/DLL，零 license 中保真求解器；重编译要 vcpkg+VS，几小时级——拷它换几小时 |
| 3 | `<工作区>\.venv\Lib\site-packages\` 下的 `CSXCAD`、`openEMS` 两包及同名 .pth/.egg-link | 暂存 `%TEMP%\openems_bindings\` → 新 venv 建好后回填 | **openEMS Python 绑定源码编译进 venv，PyPI 装不回来**——唯一不能"重建"的包 |
| 4 | pip/uv 缓存目录 | `<工作区>\.cache`（可选） | 新机装依赖提速；已 gitignore，不拷也行 |

**不拷（新机自行解决，拷目录无效）**：
- HFSS（AEDT）、ADS、KiCad——商用软件官方包重装+换机授权
  （license 常绑机器，提前找供应商确认）。
  未装好前 fake/openEMS 通道开发不受影响，仅真机档不可用。
  KiCad 建议装到源码默认引用的同一路径（见 §5 已知坑）。
- LLM/Agent 工具及其 API key 配置——新机自行安装配置。
  项目内 `configs/chat_settings.yaml`（LLM key）与
  `configs/settings.local.yaml`（EDA 路径）都在 .gitignore，整目录拷贝
  自然带上（git clone 路线则必须单独补拷）。
- uv / Python 3.12：新机 `uv python install 3.12` 重新生成（基础解释器
  含用户名路径，不拷旧机的）。

## 2. 新机操作顺序

1. 安装 AI 编码助手/uv → `uv python install 3.12`。
2. 插移动硬盘，按 §1 清单 robocopy（§4 提示词可让 Agent 全自动）。
3. 重建虚拟环境（在 `<工作区>` 下）：
   ```cmd
   uv venv .venv --python 3.12
   .venv\Scripts\python.exe -m pip install -e .[dev,openems]
   .venv\Scripts\python.exe -m pip install "smt>=2.9"
   .venv\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cpu
   ```
   **torch 必须 CPU 源**（不带 index 会拉 2GB+ CUDA 版，与既有基线不一致）。
4. **回填 openEMS 绑定**：暂存的 `CSXCAD`、`openEMS` 包目录（及
   .pth/.egg-link）拷进新 `.venv\Lib\site-packages\`（同为 Python 3.12
   x64 二进制兼容；运行时 DLL 目录见 §6 的 `OPENEMS_INSTALL_PATH`）。
5. 设系统环境变量（setx，把 `<工作区>` 换成实际路径）：
   ```cmd
   setx RFAUTO_OPENEMS_BIN "<工作区>\vendor\openEMS\install\bin"
   setx OPENEMS_INSTALL_PATH "<工作区>\vendor\openEMS\install\bin"
   setx PIP_CACHE_DIR "<工作区>\.cache\pip"
   setx UV_CACHE_DIR "<工作区>\.cache\uv"
   ```
   （`RFAUTO_AEDT_PATH=<HFSS 版本目录>` 等 HFSS 装好后再设。）
6. 重装 HFSS / ADS / KiCad（官方包+授权），核对
   `configs/settings.local.yaml`。

## 3. 迁移后验收清单（按序全过才算迁完）

```cmd
.venv\Scripts\python.exe -m pytest tests\unit -q          :: 全绿
.venv\Scripts\ruff.exe check src tests scripts             :: 0 warnings
.venv\Scripts\lint-imports.exe --config .importlinter      :: 1 kept
.venv\Scripts\python.exe -c "import CSXCAD, openEMS; print('openEMS 绑定 OK')"
.venv\Scripts\python.exe -c "import smt, torch; print('smt/torch OK')"
.venv\Scripts\rfauto.exe doctor                            :: openems verified（指向 vendor 路径；HFSS/ADS 未装时不可用属正常）
.venv\Scripts\rfauto.exe ui --port 8643                    :: UI 起得来（含 S参数/成本/报告三页）
```

## 4. 给 AI 编码助手的自动迁移提示词（新机直接粘贴）

> 你是 rfauto 项目的迁移 Agent。移动硬盘已插好（若盘符与下文不符请先
> 确认并全部替换再动手）；新机目标 = **单工作区 `<工作区>`**——openEMS
> 运行时也放进工作区 vendor 子目录（路径经 RFAUTO_OPENEMS_BIN 注入，
> configs/solvers.yaml 已是 ${VAR} 可移植形式）。拷贝方向与目的地：
> - `<工作区>` → 新机 `<工作区>`（排除 .venv/__pycache__/.pytest_cache）
> - `<openEMS 安装根>\install` → `<工作区>\vendor\openEMS\install`
> - pip/uv 缓存 → `<工作区>\.cache`（可选）
>
> 步骤（任何一步异常就停下报告，不要自行变通）：
> 1. `dir` 确认源/目标盘：源上应有工作区目录、openEMS\install、cache；
>    目标盘上若已有同名工作区，停下来报告，不要覆盖。迁移指南全文在
>    `docs\migration_guide.md`，先读它再动手。
> 2. robocopy 三项（/E /XD .venv __pycache__ .pytest_cache /XF *.pyc；
>    第三项可选），拷完核对源/目标文件数与字节数一致。
> 3. 暂存 `.venv\Lib\site-packages\` 下的 `CSXCAD`、`openEMS` 两包及
>    同名 .pth/.egg-link 到 `%TEMP%\openems_bindings\`。
> 4. `uv python install 3.12` → 在 `<工作区>` 下
>    `uv venv .venv --python 3.12` → `pip install -e .[dev,openems]` →
>    再装 `smt>=2.9` 与
>    `torch --index-url https://download.pytorch.org/whl/cpu`
>    （torch 必须 CPU 源）。
> 5. 回填步骤 3 的绑定包到新 `.venv\Lib\site-packages\`。
> 6. 设用户级环境变量（setx）：RFAUTO_OPENEMS_BIN 与
>    OPENEMS_INSTALL_PATH= `<工作区>\vendor\openEMS\install\bin`、
>    PIP_CACHE_DIR=`<工作区>\.cache\pip`、
>    UV_CACHE_DIR=`<工作区>\.cache\uv`。
>    （RFAUTO_AEDT_PATH 等 HFSS 装好后再设。）
> 7. 按 §3 验收清单逐条执行并汇报：pytest 全绿、ruff 0、
>    import-linter 1 kept、openEMS 绑定 import、smt/torch import、
>    doctor、UI 启动。任何一条不过就停下报告，不要跳过。
> 8. HFSS/ADS/KiCad 重装与 LLM 工具配置不在授权范围，
>    跳过并在最后提醒补做。
> 9. 验收全过后写迁移报告（拷贝量/耗时/验收结果/遗留项）到 runs\ 下。

## 5. 已知坑

- **盘符/路径**：项目以工作区单根组织，openEMS 已可移植化（走
  RFAUTO_OPENEMS_BIN），但 KiCad 相关源码引用了固定的本机安装路径——
  新机 KiCad 装到同一路径即闭合；否则需改源码常量或用环境变量覆盖。
  若原盘符被占用，给别的盘换盘符，不要改项目内路径。
- **vendor/ 与 .cache/ 永不入库**：openEMS 二进制是 GPL 且体积大，已
  gitignore——开源发布前 grep 确认无泄漏。
- **torch 别裸装**：不带 `--index-url .../whl/cpu` 会拉 CUDA 版。
- **openEMS 绑定靠回填**：PyPI 装不回；import 报 DLL 错先查
  OPENEMS_INSTALL_PATH / RFAUTO_OPENEMS_BIN 是否指向
  `...\vendor\openEMS\install\bin`（两个变量的分工见 §6）。
- **历史实验脚本**（runs/ 下 gitignored 探针）个别硬编码旧 exe 路径——
  新机重跑前改成 vendor 路径或 env 优先即可；主链路（模板渲染/优化/
  doctor）已全部可移植化。
- **uv 基解释器在系统盘**：新机重新生成，不要拷旧机的。
- **HFSS/ADS license 常与机器绑定**：提前向供应商确认换机授权流程。

## 6. 实测补充（首次迁移后修正，五处偏差）

> 本节是实际迁移的实测记录：§2 的命令清单按下面修正后才闭环。根因多为
> "旧 venv 手动装过的包没进 pyproject/指南"。

1. **绑定 import 的 DLL 目录变量是 `OPENEMS_INSTALL_PATH`**（或
   `CSXCAD_INSTALL_PATH`），不是 `RFAUTO_OPENEMS_BIN`——后者只喂
   solvers.yaml 的 exe_path。setx 清单实际需要**四行**（见 §2 步骤 5）。
2. **依赖安装清单缺包**（旧 venv 手动装、pyproject 未声明或 extra 未提）：
   `pip install -e ".[dev,openems]"`（openems extra 才有 h5py，绑定
   import 必需）之外还要装 **starlette uvicorn**（UI server）、
   **fastmcp**（mcp_server）、**pymoo**（multiobj_backend）、
   **pyvisa**（vna_capture）、**cmaes**（optuna CmaEsSampler，首跑
   大面积 failed/errors 的元凶之一）。根治项：pyproject extras 收编。
3. **验收清单的 doctor 行以实际实现为准**：service/api.py 的 doctor
   输出项随版本演进，openEMS 一项的等价验收可用真实解析链：
   `load_solvers_config()` 展开 `${RFAUTO_OPENEMS_BIN}` 后
   openEMS.exe 存在且指向 vendor 路径。
4. **EDA 实况记录**：HFSS/ADS 各版本在本机的安装根经环境变量
   （RFAUTO_AEDT_PATH / RFAUTO_HPEESOF_DIR）或
   configs/settings.local.yaml 钉住；license 服务（EEsof FlexNet，
   27009@localhost）随官方安装自带。与历史已测组合有版本漂移时均按
   best_effort 档处理，真机档跑前先冒烟。
5. **实测体量/耗时参考**：工作区净荷约 2.4GB、openEMS install 约
   116MB、cache 约 13.6GB；USB 读约 85-135MB/s，三项合计约 11 分钟；
   新 venv（3.12）重建+依赖全家桶约 6 分钟。回填绑定后首跑 pytest 会
   因 h5py/cmaes 等缺包红一批——按 §2 修正清单装齐即可，代码零改动。
