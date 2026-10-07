# 换机迁移指南（单工作区方案，2026-09-06 v2）

> 场景：E: 是移动硬盘，旧机开发完成后插到新工作机（先装好 Zcode），
> **在本机它是 F: 盘**；拷贝到新机本地 E: 盘后继续开发。
> **单工作区原则（用户拍板）**：开发所需的一切（代码+数据+免 license
> 求解器+缓存）都收进 **一个文件夹 `D:/rf_workspace`**——备份/迁移只
> 拷一个夹。openEMS 运行时放进工作区 `vendor\` 子目录（已 gitignore，
> GPL 二进制永不入库），路径经 `RFAUTO_OPENEMS_BIN` 环境变量注入
> （configs/solvers.yaml 已改为 `${RFAUTO_OPENEMS_BIN}` 可移植形式，
> 2026-09-06 提交）。
> 仍在工作区**外**的只有商用 EDA（HFSS/ADS/KiCad，用户重装+授权）与
> ZCode 本体——这是"单文件夹"的物理上限。

## 1. 要拷贝什么（源盘 F:\ → 新机 D:/rf_workspace）

| # | 源（移动盘上 F:\） | 拷到新机 | 说明 |
|---|---|---|---|
| 1 | `F:\rf_workspace` **整个目录** | `D:/rf_workspace` | git 仓库/源码/测试/配方/skills/docs 全在；**排除** `.venv`、`__pycache__`、`.pytest_cache`（重建）。**runs/ 全拷**——仅 0.2GB，含三份不可再生战役数据集（wilkinson ρ=0.845 / branchline ρ=0.909 / 0.3mm 种子）与 runs\audit_freq_scale\ 证据链 |
| 2 | `F:\openEMS\install` | `D:/rf_workspace\vendor\openEMS\install` | **放进工作区**（方案 B 核心）。自包含 exe/DLL，零 license 中保真求解器；重编译要 vcpkg+VS，几小时级——拷它换几小时 |
| 3 | `F:\rf_workspace\.venv\Lib\site-packages\` 下的 `CSXCAD`、`openEMS` 两包及同名 .pth/.egg-link | 暂存 `%TEMP%\openems_bindings\` → 新 venv 建好后回填 | **openEMS Python 绑定源码编译进 venv，PyPI 装不回来**——唯一不能"重建"的包 |
| 4 | `F:\cache`（pip/uv 缓存） | `D:/rf_workspace\.cache`（可选） | 新机装依赖提速；已 gitignore，不拷也行 |

**不拷（新机自行解决，拷目录无效）**：
- `F:\HFSS`（AEDT 2023.1+2026）、`F:\ADS`（2027）、`F:\KiCad`（10）——
  商用软件官方包重装+换机授权（license 常绑机器，提前找供应商确认）。
  未装好前 fake/openEMS 通道开发不受影响，仅真机档不可用。
  KiCad 重装到 `E:\KiCad` 同路径（src 里 kicad_drc/pcell 有三处该路径）。
- ZCode 本体及其 MCP 工具 key（web_reader/zai 等）——新机自行安装配置。
  项目内 `configs/chat_settings.yaml`（LLM key）与
  `configs/settings.local.yaml`（EDA 路径）都在 .gitignore，整目录拷贝
  自然带上（git clone 路线则必须单独补拷）。
- uv / Python 3.12：新机 `uv python install 3.12` 重新生成（C 盘基解释
  器含用户名路径，不拷旧机的）。

## 2. 新机操作顺序

1. 装 Zcode（自带/安装 uv）→ `uv python install 3.12`。
2. 插移动硬盘（本机 F:），按 §1 清单 robocopy（§4 提示词可让 Agent 全自动）。
3. 重建虚拟环境（在 `D:/rf_workspace` 下）：
   ```cmd
   uv venv .venv --python 3.12
   .venv\Scripts\python.exe -m pip install -e .[dev]
   .venv\Scripts\python.exe -m pip install "smt>=2.9"
   .venv\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cpu
   ```
   **torch 必须 CPU 源**（不带 index 会拉 2GB+ CUDA 版，与旧基线不一致）。
4. **回填 openEMS 绑定**：暂存的 `CSXCAD`、`openEMS` 包目录（及
   .pth/.egg-link）拷进新 `.venv\Lib\site-packages\`（同为 Python 3.12
   x64 二进制兼容；运行时 DLL 走 RFAUTO_OPENEMS_BIN 指向的 vendor 目录）。
5. 设系统环境变量（setx，**单工作区方案 B 的三行**）：
   ```cmd
   setx RFAUTO_OPENEMS_BIN "D:/rf_workspace\vendor\openEMS\install\bin"
   setx PIP_CACHE_DIR "D:/rf_workspace\.cache\pip"
   setx UV_CACHE_DIR "D:/rf_workspace\.cache\uv"
   ```
   （`RFAUTO_AEDT_PATH=E:\HFSS\v231` 等 HFSS 装好后再设。）
6. 重装 HFSS 2023.1 / ADS 2027 / KiCad 10（官方包+授权），核对
   `configs/settings.local.yaml`。

## 3. 迁移后验收清单（按序全过才算迁完）

```cmd
.venv\Scripts\python.exe -m pytest tests\unit -q          :: 1059+ 全绿
.venv\Scripts\ruff.exe check src tests scripts             :: 0 warnings
.venv\Scripts\lint-imports.exe --config .importlinter      :: 1 kept
.venv\Scripts\python.exe -c "import CSXCAD, openEMS; print('openEMS 绑定 OK')"
.venv\Scripts\python.exe -c "import smt, torch; print('smt/torch OK')"
.venv\Scripts\rfauto.exe doctor                            :: openems verified（指向 vendor 路径；HFSS/ADS 未装时不可用属正常）
.venv\Scripts\rfauto.exe ui --port 8643                    :: UI 起得来（含 S参数/成本/报告三页）
```

**验收后按 `交接任务书` 继续开发——patch 校准战役
是当前关键路径**（新机内存 ≥5.5GB 可 workers=2，≥4GB 串行）。

## 4. 给 Agent 的自动迁移提示词（新机 Zcode 里直接粘贴）

> 你是 rfauto 项目的迁移 Agent。移动硬盘已插好，**在本机上盘符是 F:**
> （若实际不是 F: 请先告诉我并全部替换再动手）；新机目标 = **单工作区
> `D:/rf_workspace`**——openEMS 运行时也放进工作区 vendor 子目录（路径
> 经 RFAUTO_OPENEMS_BIN 注入，configs/solvers.yaml 已是 ${VAR} 可移植
> 形式）。拷贝方向与目的地：
> - `F:\rf_workspace` → `D:/rf_workspace`（排除 .venv/__pycache__/
>   .pytest_cache）
> - `F:\openEMS\install` → `D:/rf_workspace\vendor\openEMS\install`
> - `F:\cache` → `D:/rf_workspace\.cache`（可选）
>
> 步骤（任何一步异常就停下报告，不要自行变通）：
> 1. `dir F:\` 与 `dir E:\` 确认源/目标：源上应有 rf_workspace、
>    openEMS\install、cache；目标 E: 上若已有 rf_workspace，停下来报告
>    我，不要覆盖。迁移指南全文在
>    `F:\rf_workspace\docs\migration_guide.md`（拷完即在新机 docs\），
>    先读它再动手。
> 2. robocopy 三项（E /XD .venv __pycache__ .pytest_cache /XF *.pyc；
>    第三项可选），拷完核对源/目标文件数与字节数一致。
> 3. 暂存 `F:\rf_workspace\.venv\Lib\site-packages\` 下的 `CSXCAD`、
>    `openEMS` 两包及同名 .pth/.egg-link 到 `%TEMP%\openems_bindings\`。
> 4. `uv python install 3.12` → 在 `D:/rf_workspace` 下
>    `uv venv .venv --python 3.12` → `pip install -e .[dev]` → 再装
>    `smt>=2.9` 与 `torch --index-url
>    https://download.pytorch.org/whl/cpu`（torch 必须 CPU 源）。
> 5. 回填步骤 3 的绑定包到新 `.venv\Lib\site-packages\`。
> 6. 设用户级环境变量（setx）：RFAUTO_OPENEMS_BIN=
>    `D:/rf_workspace\vendor\openEMS\install\bin`、
>    PIP_CACHE_DIR=`D:/rf_workspace\.cache\pip`、
>    UV_CACHE_DIR=`D:/rf_workspace\.cache\uv`。
>    （RFAUTO_AEDT_PATH 等 HFSS 装好后再设。）
> 7. 按 docs/migration_guide.md §3 验收清单逐条执行并汇报：pytest
>    1059+ 全绿、ruff 0、import-linter 1 kept、openEMS 绑定 import、
>    smt/torch import、doctor（openems 应指向 vendor 路径）、UI 启动。
>    任何一条不过就停下报告，不要跳过。
> 8. HFSS/ADS/KiCad 重装与 ZCode 的 MCP 工具配置我没有授权你操作，
>    跳过并在最后提醒我补做。
> 9. 验收全过后：读 交接任务书 并按它继续开发
>    （patch 校准战役是关键路径；新机内存 ≥5.5GB 可 workers=2）。
>    最后写迁移报告（拷贝量/耗时/验收结果/遗留项）到 runs\ 下。

## 5. 已知坑

- **盘符/路径硬要求**：项目必须落 `D:/rf_workspace`（单根）。openEMS 已
  可移植化（走 RFAUTO_OPENEMS_BIN），但 KiCad 源码引用仍是
  `E:\KiCad`（重装同路径即闭合）。若新机 E: 被占用，给别的盘换盘符，
  不要改项目内路径。
- **vendor/ 与 .cache/ 永不入库**：openEMS 二进制是 GPL 且体积大，已
  gitignore（2026-09-06 提交）——开源发布前 grep 确认无泄漏。
- **torch 别裸装**：不带 `--index-url .../whl/cpu` 会拉 CUDA 版。
- **openEMS 绑定靠回填**：PyPI 装不回；import 报 DLL 错先查
  RFAUTO_OPENEMS_BIN 是否指向 `...\vendor\openEMS\install\bin`。
- **历史实验脚本**（runs/audit_freq_scale/ 下 gitignored 探针）个别
  硬编码旧 exe 路径（如 smoke_patch.py 的 exe_path）——新机重跑前改
  成 vendor 路径或 env 优先即可；主链路（模板渲染/战役/doctor）已全部
  可移植化。
- **uv 基解释器在 C 盘**：新机重新生成，不要拷旧机的。
- **HFSS/ADS license 常与机器绑定**：提前向供应商确认换机授权流程。

## 6. 2026-09-07 新机实测补充（迁移 Agent 记录，五处偏差已修正）

> 本节是 F:→E: 实际迁移的实测记录：指南 §2 的命令清单按下面修正后才
> 闭环。根因多为"旧 venv 手动装过的包没进 pyproject/指南"。

1. **绑定 import 的 DLL 目录变量是 `OPENEMS_INSTALL_PATH`**（或
   `CSXCAD_INSTALL_PATH`），不是 `RFAUTO_OPENEMS_BIN`——后者只喂
   solvers.yaml 的 exe_path。setx 清单实际需要**四行**：
   ```cmd
   setx RFAUTO_OPENEMS_BIN "D:/rf_workspace\vendor\openEMS\install\bin"
   setx OPENEMS_INSTALL_PATH "D:/rf_workspace\vendor\openEMS\install\bin"
   setx PIP_CACHE_DIR "D:/rf_workspace\.cache\pip"
   setx UV_CACHE_DIR "D:/rf_workspace\.cache\uv"
   ```
2. **依赖安装清单缺包**（旧 venv 手动装、pyproject 未声明或 extra 未提）：
   `pip install -e ".[dev,openems]"`（openems extra 才有 h5py，绑定
   import 必需）之外还要装 **starlette uvicorn**（UI server）、
   **fastmcp**（mcp_server）、**pymoo**（multiobj_backend）、
   **pyvisa**（vna_capture）、**cmaes**（optuna CmaEsSampler，首跑
   25 failed/28 errors 的元凶之一）。根治项：pyproject extras 收编
   （见 TODO 〇）。
3. **验收清单的 doctor 行不存在**：service/api.py 的 doctor 只输出
   Python/AEDT/ADS/缓存四行，本就没有 openems 项。等价验收改用真实
   解析链：`load_solvers_config()` 展开 `${RFAUTO_OPENEMS_BIN}` 后
   openEMS.exe 存在且指向 vendor 路径（实测过）。
4. **本机 EDA 实况（2026-09-07）**：AEDT **2025.1** 在
   `E:\ANSYSINC\ANSYS Inc\v251`（ANSYSEM_ROOT251 自动发现，
   RFAUTO_AEDT_PATH 已 setx 钉住）；ADS **2027** 在
   `E:\ADS\ADS27`（settings.local.yaml hpeesof_dir；2026-09-18 治理：旧口径 E:\ads2026\ADS_2026 / E:\Ads2027 均失效，env RFAUTO_HPEESOF_DIR 优先；license=EEsof FlexNet License Server 服务 27009@localhost，C:\Program Files\Keysight\EEsof_License_Tools）。
   与已测组合（HFSS 2023.1/2026 + ADS 2027）有版本漂移，均 best_effort
   档，真机档跑前先冒烟。KiCad 仍未装（kicad_drc/pcell 通道不可用，
   装到 `E:\KiCad` 同路径即闭合）。
5. **实测体量/耗时**：工作区净荷 2.391G/21553 文件（du 4.9G 是移动盘
   大簇分配虚高）、openEMS install 116.5M/565 文件、cache 13.56G/27212
   文件；USB 读约 85-135MB/s，三项合计约 11 分钟；新 venv（3.12.14，
   基解释器在 `tools\uv\pythons`，不占 C 盘）重建+依赖全家桶约 6 分钟。
   回填绑定后首跑 pytest 会因 h5py/cmaes 等缺包红一批——按 §2 修正
   清单装齐即可，代码零改动。
