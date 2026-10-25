# RFAUTO_* 环境变量参考页（QW-12）

> 全仓单一清单（2026-09-26 实测：`git grep -o "RFAUTO_[A-Z0-9_]+"` 共
> **48 个**变量，消费者映射见本表；2026-10-04 E3-4 补登 remote 凭据两键；
> 同日 W3 补登 `RFAUTO_SSH_STRICT`）。
> 惯例：`RFAUTO_` 前缀；缺省行为一律
> 回落到 configs/settings.yaml 或 configs/solvers.yaml 的对应键，环境变量
> 优先级更高。**doctor `--env` 校验面**（对清单逐项体检）为 QW-12 后半件，
> 随接线批落地。
> 维护纪律：新增环境变量必须同批在本表登记（#97 文档-代码同 commit 惯例
> 的环境变量版）；本表由 `git grep` 实测生成，禁止凭记忆补条目。

## 一、求解器/工具链路径

| 变量 | 消费者（节选） | 用途 |
|---|---|---|
| `RFAUTO_AEDT_PATH` | infra/config、version_probe、HFSS 仲裁脚本 | AEDT 安装根（HFSS/PyAEDT 链） |
| `RFAUTO_HPEESOF_DIR` | infra/config、ADS 探针脚本 | ADS 安装根（hpeesofsim 链，#272：必须指真实安装目录） |
| `RFAUTO_OPENEMS_BIN` | openems_solver、em_solver_base、configs/solvers.yaml | openEMS 可执行/绑定定位 |
| `RFAUTO_NGSPICE_BIN` | spice_netlist、r3_services、qucsator 链 | ngspice 可执行 |
| `RFAUTO_XYCE_BIN` | spice_netlist、r3_services | Xyce 可执行（WSL 场景） |
| `RFAUTO_QUCSATOR_BIN` | qucsator_adapter/qucsator_service | qucsatorRF 可执行 |
| `RFAUTO_PALACE_EXE` | palace_solver | Palace 可执行（WSL） |
| `RFAUTO_PALACE_ITEST` | tests/unit/test_palace_solver | Palace WSL 真跑集成 opt-in 门（#df4⑥：env 显式意图门） |
| `RFAUTO_MEEP_PYTHON` | meep_adapter | Meep 专用解释器（CI-only 冻结面） |
| `RFAUTO_ELMER_BIN` / `RFAUTO_ELMER_BIN_ENV` | elmer_adapter、elmer_plate_case | ElmerGrid/ElmerSolver 可执行与其环境变量注入 |
| `RFAUTO_COMSOL_ROOT` | comsol_adapter、configs/solvers.yaml | COMSOL 安装根（mph+6.3 显式版本，#215） |
| `RFAUTO_LICENSE_SERVER` | infra/license_probe | 商业 license 服务器探测目标 |
| `RFAUTO_OPENEMS_EXE` / `RFAUTO_OPENEMS_MESH` | scripts/p0_experiment、p0_gate_service | P0 历史实验面（遗留） |

## 二、infra/config（工作区/数据库/超时）

| 变量 | 消费者 | 用途 |
|---|---|---|
| `RFAUTO_WORKSPACE_DIR`（兼容 `RFAUTO_WORKSPACE`） | infra/config、configs/settings.yaml | 工作区根目录 |
| `RFAUTO_REGISTRY_DB` | infra/db、run_store、cli/mcp | run 注册库（duckdb 路径） |
| `RFAUTO_REGISTRY_PG_DSN` | infra/db | Postgres DSN（可选后端） |
| `RFAUTO_JOB_REGISTRY_DB` | service/job_registry | 任务注册库路径 |
| `RFAUTO_TIMEOUT_S` | infra/config | 通用超时秒数 |
| `RFAUTO_GRPC_PORT` | infra/config | AEDT gRPC 端口 |
| `RFAUTO_LOG_LEVEL` | cli/main | 日志级别 |
| `RFAUTO_MAX_CONCURRENT` | infra/config | 并发上限 |
| `RFAUTO_DEFAULT_UNIT` | infra/config | 缺省单位制 |
| `RFAUTO_CACHE` | openems_optimizer_adapter、各战役脚本 | ResultCache 开关/路径口径（configs/settings.yaml 有缺省） |
| `RFAUTO_SOLVERS_YAML` | em_solver_base | solvers 配置文件覆盖（缺省 configs/solvers.yaml） |
| `RFAUTO_FS_ROOT` | service/r3_services（fs_read_fence） | 文件浏览/配方读允许根（os.pathsep 多根；缺省 cwd） |

## 三、行为开关（测试/离线面）

| 变量 | 消费者 | 用途 |
|---|---|---|
| `RFAUTO_CALCULATORS_ALLOW_EXPERIMENTAL` | calculator_service、cli/mcp、config | 实验计算器键放行（缺省拒绝） |
| `RFAUTO_SKIP_RUN` | openems_templates、slotline/marchand 冒烟脚本 | 模板层跳过真跑（离线审计态） |
| `RFAUTO_NRTS` | openems_templates、marchand_via_ab | 覆盖渲染 NrTS（时窗旋钮，#283） |
| `RFAUTO_REGEN_GOLDEN` | test_golden_regression、wilkinson_fake_baseline | 金快照重生成开关（评审后重钉，#455 先例） |
| `RFAUTO_AGENTBENCH_PRIVATE_SET` | agent_bench、cli/bench_app、mcp | agent 基准私有集放行 |
| `RFAUTO_PEC_MIRROR` / `RFAUTO_PEC_MIRROR_BEGIN` / `RFAUTO_PEC_MIRROR_END` | openems_templates、ff_calc_block 测试 | PEC 镜像修正旋钮（#249/#296 幂等链） |

## 四、战役/仲裁旋钮（scripts 面，真机窗口用）

| 变量 | 消费者 | 用途 |
|---|---|---|
| `RFAUTO_HFSS_SOLVE_TIMEOUT_S` | 各 HFSS 仲裁脚本 | HFSS 单解超时（#145：超时走此变量不判废竞态完成） |
| `RFAUTO_C4_ARB_TAG` / `RFAUTO_C4_ARB_DELTA_S` / `RFAUTO_C4_ARB_MAX_PASSES` | hfss_c4_arbitration.py | C4 仲裁战役旋钮（#335：ΔS 阶梯） |
| `RFAUTO_MAPES_G0_TAG` / `RFAUTO_MAPES_G0_DELTA_S` / `RFAUTO_MAPES_G0_MAX_PASSES` | hfss_mapes_g0_arbitration.py | MAPES G0 仲裁战役旋钮 |
| `RFAUTO_MAPES_M_TAG` / `RFAUTO_MAPES_M_DELTA_S` / `RFAUTO_MAPES_M_MAX_PASSES` | hfss_mapes_m_arbitration.py | MAPES M 仲裁战役旋钮 |

## 四b、远程多机面（infra/remote_machines，E3-4 审查批补登）

| 变量 | 消费者 | 用途 |
|---|---|---|
| `RFAUTO_REMOTE_SSH_USER` | infra/remote_machines（SshTransport 凭据解析） | SSH 用户名（凭据面=local yaml 覆盖优先，env 为无 yaml 场景回退） |
| `RFAUTO_REMOTE_SSH_PASSWORD` | infra/remote_machines（SshTransport 凭据解析） | SSH 密码（凭据面=local yaml 覆盖优先，env 为无 yaml 场景回退；doctor `--env` 值不回显） |
| `RFAUTO_SSH_STRICT` | infra/remote_machines（SshTransport.connect 主机钥策略） | SSH 主机钥严格模式（E3-3 TOFU 折中：缺省 AutoAdd+首连指纹落档告警、变更 error 告警仍放行；设 1=无落档指纹/不匹配即拒连。指纹账本=`<仓根>/runs/ssh_host_fingerprints.json`） |

## 四c、UI 工作台面（架构批 W6-S2，R2 审计 §面5.4 写端点鉴权）

| 变量 | 消费者 | 用途 |
|---|---|---|
| `RFAUTO_UI_TOKEN` | ui/server（BearerAuthMiddleware + index meta 注入）、static/pages/api.js（装配期读 meta → setApiToken） | UI 写端点 Bearer 令牌：设置即启用（写端点 POST/PUT/DELETE 要求 `Authorization: Bearer`、读端点豁免）；未设=零鉴权零行为变化（本机回环缺省安全）；doctor `--env` 值不回显 |

**威胁模型边界（2026-10-20 架构批 补，W16 审计 P2-4 清偿）**：本令牌
只防"非本机来源的意外写"（LAN 内误触/扫描器/其他用户会话），**不构成
完整 Web 安全边界**——①无 CSRF 防（写端点认 Authorization 头不认
Origin，浏览器内已持页面的跨站请求若能读到 token 仍可伪造，token 经
GET / 的 meta 传递=同源可读是已声明取舍，W9 P2-1）；②明文 HTTP 传输
（无 TLS 终止时 token 可被链路观测）；③读端点全豁免=数据面（runs 湖/
配方/测量结果）对能到达端口的一侧只读开放；④单用户共享令牌无逐会话
撤销。非回环部署应前置反向代理（TLS+访问控制）或防火墙限源；缺省
回环（127.0.0.1）+未设令牌=零风险面。

## 五、PySR/Julia 面

| 变量 | 消费者 | 用途 |
|---|---|---|
| `RFAUTO_JULIA_DEPOT` / `RFAUTO_JULIA_UP` | scripts/pysr_anchor_fit.py | Julia depot 定位与升级开关（PySR 锚拟合） |

## 五b、工具链门面（ge1 批）

| 变量 | 消费者 | 用途 |
|---|---|---|
| `RFAUTO_GITLEAKS_BIN` | scripts/pre_commit_gitleaks.py | gitleaks 可执行定位 |
| `RFAUTO_GITLEAKS_STRICT` | scripts/pre_commit_gitleaks.py | 设 1=工具缺失即 fail（缺省警告放行） |
| `RFAUTO_GITLEAKS_PY` | scripts/install_git_hooks.py（生成钩子内消费） | 钩子 launcher 的 python 绝对路径 |
| `RFAUTO_KICAD_PYTHON` | scripts/mtrl_kit_kicad.py | KiCad 自带 Python 定位 |

## 六、非 RFAUTO_ 前缀但被本仓消费的第三方变量

| 变量 | 说明 |
|---|---|
| `HPEESOF_DIR` | ADS 官方变量（#272：裸调 exe 静默无输出的根因，须设对+前置 PATH）；仓内 77 处引用含第三方/日志，设置面以 `RFAUTO_HPEESOF_DIR`+adapter env 构造为准 |
| `COMSOL_ROOT` | COMSOL 官方查找变量（mph 桥） |
| `OPENEMS_INSTALL_PATH` | openEMS 官方安装探测变量（迁移指南 §6） |

## 七、测试隔离变量（conftest/单测专用）

单测内大量使用同名前缀清空+注入（#139 纪律：网络通道 monkeypatch 钉住；
确定性测试清空整个同名前缀集合）。此类变量（如 tests/conftest.py 的
CSXCAD 门控）不在上表逐项列出，以 conftest 注释为准。

## 八、doctor 资源卫生面（janitor + 内存闸）

来自真实用户实战反馈（异常退出后孤儿 ansysedt.exe 堆积把整机内存推到
提交量上限、HFSS 无法再启动）的诊断与清理入口，service 单源
`src/rfauto/service/resource_janitor_service.py`：

| 命令 | 作用 |
|---|---|
| `rfauto doctor --janitor` | 只扫描不动手：清点 ansysedt 族进程（PID/内存/启动时间/父进程链，疑似孤儿仅启发式标记=父进程已退出或父进程为系统会话进程，是否击杀由用户判断）+ 扫描 runs/ 工作根内 AEDT 工程锁（`*.aedt.lock` 命名或与同名 `.aedt` 工程伴生的 `*.lock`，文件/目录皆收；不扫全盘） |
| `rfauto doctor --janitor --janitor-clean` | 对同次扫描标疑的进程 + 扫到的 AEDT 锁执行清理（击杀走白名单+击杀前进程名复核防 PID 复用；不给 `--janitor-clean` 绝不动手） |
| `rfauto doctor --min-free-gb N` | 内存闸：系统可用内存（psutil 优先、Windows ctypes 兜底）低于 N GB 时判定不放行，信息性恒 exit 0 |
| `rfauto doctor --min-free-gb N --enforce` | 闸不放行时退出码非 0（供脚本在求解发射前做门） |

均支持 `--json`（信封形态：`{ok, scan, clean, memory_gate}` 分节）。psutil
为惰性可选依赖（未装时进程面/内存面如实注明通道不可用，不阻塞 doctor）。
