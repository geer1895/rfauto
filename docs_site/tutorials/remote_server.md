<!-- PR-10 文档站同步副本：源=docs/tutorials/remote_server.md（scripts/build_docs_pages.py 重建，勿直接改本文件——改动请改源文件后重跑生成器） -->

# 远程仿真服务器协同：多机通道的边界与第一次接入

> 课题组共用一台仿真服务器（HFSS/ADS 许可与算力都在那边）时，怎么让
> rfauto 把真机求解发上去、把产物拉回来、再把现场清理干净？本文讲多机
> 协同面（`rfauto remote` 命令域 + HFSS/openEMS/ADS 三个远跑通道）的
> 机器登记、探活、资源视图、冒烟与清理纪律。**本文全程零真连**：所有
> 远程动作只描述契约与 opt-in 门，命令的 `--help` 逐条实测，离线行为
> 实测照录；服务器硬规则（版本配对/中间文件根/备份窗/清理）以
> docs/服务器接入与仿真资源说明.md 为准，文中主机一律以 `<host>` 占位。

## 0. 前置与红线

- 已按 docs/tutorials/getting-started.md 装好环境；SSH 通道是可选依赖
  `pip install rfauto[remote]`（paramiko 懒加载，缺装时显式报错提示，
  不影响注册表/探活面）。
- 硬规则速记（逐条出处见服务器说明与 AGENTS 规则 0/0b，违反即返工）：

| 红线 | 内容 |
|---|---|
| 版本配对 | 服务器 AEDT 必须与本机**同版本**（2025 R1/v251；PyAEDT gRPC 客户端-服务端版本配对 + HFSS=对齐基准的数值可比性）；服务器只需 `ansysedt -grpcsrv` 监听，无需装 pyaedt |
| 中间文件根 | 服务器侧一切临时目录/中间文件/工作目录一律放**大容量数据盘**（注册表 `hfss.project_root` 键，登记为该盘下 `rfauto_remote` 目录）；**禁写生产云盘** |
| 备份窗 | 避开凌晨 02:50–05:35（夜间归档/备份/知识库同步）；overnight 队列属合法用例但发射侧会如实登记风险 |
| 内存上限 | 服务器同时承载云盘/备份/AI 知识库，单任务内存 ≤80GB，勿占满全部核与内存 |
| 任务毕清理 | 杀掉本次拉起的 ansysedt、删掉 schtasks 任务、清掉任务目录——清理失败翻 FAIL，不许留孤儿 |
| 共享机互斥 | 发射前互斥预检（#261）：命中在跑实例=候跑 SKIP，**禁止代杀**别人的进程 |

- 本文演示边界：本教程写作时不真连服务器（现状不明）。凡涉及真实
  网络的动作，只给契约与"接入日清单"，不做实跑演示。

## 1. 机器登记：configs/remote_machines.yaml 的键结构

登记分两个文件（键结构如下，值以 `<…>` 占位）：

```yaml
# configs/remote_machines.yaml —— 入库无凭据，可提交
machines:
  <machine名>:
    host: <host>                      # IP 或主机名（DHCP 漂移时更新此行）
    ssh_port: 22
    probe_ports:                      # 语义名→端口，probe 消费
      rdp: 3389
      ansys_license: 1055
      ads_license: 27009
      smb: 445
    hfss:
      version: "2025.1"               # 必须=本机 AEDT 版本
      grpc_port: 50051                # ansysedt -grpcsrv 监听端口
      project_root: '<数据盘>:\rfauto_remote'   # 服务器侧唯一中间文件根
      ansysedt_exe: '<服务器 AEDT 安装目录>\ansysedt.exe'
      # 可选：cores: N（HPC 核数，>0 才透传）；max_parallel: 2（v1 发射闸）
    ads:
      hpeesof_dir: '<服务器 ADS 安装根>'         # hpeesofsim 远跑 HPEESOF_DIR 前置
```

**凭据零入库**（铁律 8 同源）：登记文件永不持有用户名/密码/私钥。
凭据面只有两处——环境变量 `RFAUTO_REMOTE_SSH_USER` /
`RFAUTO_REMOTE_SSH_PASSWORD`，或同目录 `remote_machines.local.yaml`
（已 gitignore）里的 `ssh_user` + `ssh_password` / `ssh_key_path` 覆盖
（key 优先，与密码二选一）。mTLS 三键（`hfss_ca_cert`/`hfss_client_cert`/
`hfss_client_key`）同样只进 local 覆盖文件，且三键须同时配置或同时省略。

装载契约：读 `configs/remote_machines.yaml` 后用同目录 local 覆盖文件
深合并；**文件不存在=空表**，所有 remote 面"无配置零行为变化"（adapter
与 service 全走本地路径）。local 文件存在但不可读/非法 YAML 不静默跳过
——记入 `load_errors` 并告警后继续。

## 2. 探活与状态：`remote probe` / `remote status`

```bash
.venv/Scripts/rfauto.exe remote probe --help
.venv/Scripts/rfauto.exe remote status --help
```

两者参数相同：位置参数 `machine`（缺省=唯一登记机器）+ `--json/-j`。

- `probe`：TCP 探活（`probe_ports` 表逐端口 connect/close + 时延），
  **零副作用零凭据**——不登录、不写文件。输出逐端口 `OPEN/CLOSED +
  latency_ms`。
- `status`：探活 + SSH 认证可达性。判定不猜不试：凭据缺失 →
  `ssh_auth: missing_credentials`（连试都不试，附提示）；凭据在 →
  真连一次跑回显命令，`ok/failed` 按命令回执判。

诚实报错契约（本机实测，可用机器名列表已略）：

```bash
.venv/Scripts/rfauto.exe remote probe nosuch_demo
```

```text
RemoteConfigError: 远程机器 'nosuch_demo' 未登记（可用：<已登记机器名>）
```

而"登记文件不存在"的环境里，`probe`/`status` 打印
`无登记机器（configs/remote_machines.yaml）——本地模式`（CLI 契约；
本机有登记机器，此形态未在写作环境复现）。

接入日清单（真机首连时逐条打勾，本文不代跑）：

```text
□ 1. pip install rfauto[remote]（paramiko 就位）
□ 2. rfauto remote probe            —— license/RDP/SSH 端口全 OPEN
□ 3. 凭据就位（env 或 local 覆盖文件）
□ 4. rfauto remote status           —— ssh_auth=ok
□ 5. RFAUTO_REMOTE_SMOKE=1 冒烟（见 §5）—— attach health=True 后现场已清理
```

## 3. 资源与队列视图：`remote resources` / `remote queue`

```bash
.venv/Scripts/rfauto.exe remote resources --help
.venv/Scripts/rfauto.exe remote queue --help
```

- `resources`：并发求解面资源视图。本机半边 = openEMS/HFSS 进程互斥态
  （BUSY/IDLE）；服务器半边 = 可达性/在跑进程数/磁盘余量。子面降级
  一律 `unknown`（#105：探测失败不是故障，不阻塞聚合面）。
- `queue`：任务队列视图 = 进程内在册作业 + 单写锁 owner/排队 + 席位
  占用 + 服务器在跑态（进程 census 口径，**非 license 席位**）。历史
  run 不在进程内注册表里，走 `jobs status`/meta.json 磁盘面。

两条隐私契约值得记住：**主机名/IP 与凭据恒不落信封**（机器只以注册表
键名出现）；`n_tasks` 在任一通道 census 降级时为 None——半边 census
不凑数。

## 4. 通道拓扑：一条探活面 + 三个远跑通道

`remote` 命令域本身只有只读四件（probe/status/resources/queue）；真正
"发任务上去"走三个通道，全部挂在同一注册表与同一互斥预检上：

| 通道 | 服务模块 | 形态 | 现状 |
|---|---|---|---|
| HFSS gRPC | `service/remote_service.py` | 本机 pyaedt 客户端 attach 服务器 `ansysedt -grpcsrv`；文件走 SSH/sftp | v0 已交付，L1 attach 冒烟真机 PASS（v0 真机批记录：探活端口全 OPEN + ssh_auth=ok + attach version/health=True） |
| openEMS 远跑 | `service/remote_oe_service.py` | `fd_oe_campaign --remote` 执行通道：本地渲染 → sftp 传四件轻量文件 → 服务器跑 → 产物回拉镜像本地 runs/ 布局 | v1（判读/健康门全在本地消费，回拉零改动） |
| ADS 网表远跑 | `service/remote_ads_service.py` | 网表 sftp 上传（自包含化检查）→ 服务器 hpeesofsim → 数据集逐文件回拉 | v1（本机无需装 ADS） |

三个通道共享的发射纪律：

- **互斥预检先行（#261）**：服务器侧进程指纹直查=权威判据 + 探针
  census mutex 行=旁证；命中=候跑 SKIP；rc≠0=验不了不发射
  （fail-closed）；**禁止代杀**——非本批指纹的实例（含他人的 GUI/其他
  端口会话）绝不碰。
- **同步缺省，长座位才轮询**：openEMS/ADS 座位在同步等待期内通道必然
  存活、进程自然结束；分钟-小时级长座位可选轮询档（发射后按 rc 文件/
  进程指纹/时间轴三证据轮询 + 双 CPU 采样存活复核，防静默击杀钉到
  2 分钟窗）。超时不代杀：PID 落信封交人工处置。
- **判据先行**：openEMS 座位的 `criteria.md` 发射前必落盘，缺失
  fail-closed（#122 判读先行纪律）。
- **license 预检一级门**（`license_preflight`）：license 端口 TCP 探活
  全 OPEN → PASS；不通/未登记 → FAIL（fail-skip 不硬打）。席位级
  lmstat 查询未接线，信封里 `seat_level_query` 如实标 UNVERIFIED——
  端口 OPEN≠席位可用。

## 5. 真机冒烟：opt-in 门与 L1/L2

真机冒烟是**运维面，不进 CLI/MCP 缺省面**，由单一环境变量门把守：
`RFAUTO_REMOTE_SMOKE=1`。门未设时服务函数直接拒绝（零网络，本机实测）：

```bash
.venv/Scripts/python.exe -c "import sys; sys.path.insert(0,'src'); \
from rfauto.service.remote_service import remote_hfss_smoke; \
print(remote_hfss_smoke())"
```

```text
{'ok': False, 'skipped': True, 'reason': '真机冒烟需显式 opt-in：RFAUTO_REMOTE_SMOKE=1（unit 门零真机）'}
```

- **L1 attach 冒烟**（`remote_hfss_smoke`）：探活 → 互斥预检 → SSH 拉
  `ansysedt -grpcsrv`（服务器侧工作根 sftp 传 .bat + schtasks 注册 once
  任务触发——Win32-OpenSSH 会话 job object 会连坐通道内进程，持久进程
  必须走 Task Scheduler）→ 轮询 gRPC 端口 → 本机 pyaedt attach（版本
  配对断言）→ health_check。**finally 兜底清理**：launch 成功后的任何
  失败路径都收掉本次拉起的 ansysedt 与 schtasks 任务（#265 孤儿桌面
  铁律）；互斥候跑路径例外——本次零发射，清理让位（禁止代杀在跑实例）。
- **L2 求解冒烟**（`remote_hfss_l2_smoke`，驱动脚本
  `scripts/smoke_remote_l2.py`）：远程建模（mline 锚，几何/材料单一
  事实源）→ 求解 → Touchstone sftp 回拉（缺省 `runs/remote_l2/<日期>/`）
  → skrf 判读。判读四判据预声明（#122，全过=PASS，任一不过=FAIL 附
  数字）：① 回拉文件 skrf 可读且 2 端口 41 点；② 带内 min|S11| ≤
  -10 dB；③ 带内 min|S21| ≥ -1 dB；④ S21 相位斜率反演 εeff ∈
  [2.60, 3.10]（S11 谷位只参考不进门）。真机批记录：服务器侧 hfss_gui
  许可签名失效期间 L2 fail-closed（代码链本地对照四判据全 PASS，归因
  服务器环境非代码）；许可换发后一条命令重跑：

```bash
# 真机 opt-in（unit 门零真机，绝不缺省跑）
set RFAUTO_REMOTE_SMOKE=1
.venv\Scripts\python.exe scripts\smoke_remote_l2.py --machine <machine名>
```

- **清理语义**（`remote_hfss_cleanup`）：按 PID 精确杀——先查
  `Win32_Process` 取 ansysedt 的 ProcessId+CommandLine，只杀命令行含
  `-grpcsrv` 且含本次端口指纹的实例；**绝不做全名 taskkill**（共享机
  他人的 GUI/其他端口实例不受影响）；schtasks 任务按唯一名删（uuid
  后缀，并发冒烟不互踩）。任务毕清理失败翻 FAIL——不许留孤儿。

## 6. 离线演示与测试模式（无服务器时怎么开发）

- **无登记机器=本地模式**：配置文件不存在时空表，`probe/status` 打印
  本地模式提示，adapter/service 全走本地路径——离线开发零行为差。
- **未登记名=诚实报错**：`RemoteConfigError` 列出可用机器名（§2 实测）。
- **unit 门全 mock**：`tests/unit/test_remote_service.py` 全通道 mock
  （假 transport/打桩建模，#139 纪律——真机绝不混进测试，配置存在也不
  真连网）。通道行为的问题先跑这套测试再想真机。
- **本机半边独立可用**：`resources`/`queue` 的本机进程互斥态与进程内
  队列半边不依赖服务器（注意：机器已登记时这两条命令会对默认机器发起
  TCP 探活——纯只读，但确是网络动作）。
- **SSH 严格档**：`RFAUTO_SSH_STRICT=1` 时主机钥不匹配/无落档指纹即
  拒连；缺省是 TOFU 折中——首连指纹落档告警，指纹变更醒目报错仍放行
  （全量严格档等 mTLS 通道一起收口）。

## 7. 什么时候该上服务器（使用边界）

- **该上**：HFSS/ADS 真机求解与仲裁、参数扫描/优化战役、长跑判读、
  overnight 队列、分钟级以上纯计算批——可借服务器加速的环节一律优先
  服务器，本机只留编排与轻计算（AGENTS 规则 0b）。
- **不该上**：秒级冒烟/离线审计/渲染期几何校验——本地更快也更省
  服务器窗口；真机互斥按"每机互斥"意识管理，别把服务器当免费并发池
  （远程并行度上限在注册表 `hfss.max_parallel`，v1 发射侧闸）。
- **发射形态**：服务器侧发射优先 console 可见/bat 直指形态（隐藏窗口
  类形态易被服务器杀毒静默击杀），发射后必须存活复核。
- **远程扩展**：多机扩展时新服务器侧版本必须=本机（规则 0），接入
  步骤照 §1 登记 + §2 清单走一遍。

## 8. 下一步

- 服务器硬规则全文（硬件/许可/端口/账号）：docs/服务器接入与仿真资源说明.md
- openEMS 服务器侧安装与九步 SOP：docs/rfauto_openEMS_服务器安装与调用说明.md
- 真机仿真本地侧的判读与体检：docs/tutorials/real-simulation.md
- 战役批量发射与 `--remote` 路由进展：TODO「多机协同远程求解」条

## 附：本文核对清单与敏感面自查

| 命令/契约 | 核对方式 | 结果 |
|---|---|---|
| `rfauto remote --help` 四子命令（probe/status/resources/queue）+ 各自 `--help` | 实跑 | 过（machine 参数 + --json 旗标逐条对） |
| 未登记名报错（RemoteConfigError，可用列表已略） | 实跑 | 过（§2 照录） |
| env 门未设 → smoke 如实 SKIP（零网络） | `python -c` 实调 `remote_hfss_smoke()` | 过（§5 照录） |
| 登记键结构/凭据面/local 覆盖深合并/load_errors 留痕 | `configs/remote_machines.yaml` 实读 + `infra/remote_machines.py` 源码 | 过（值一律占位） |
| L1 编排/schtasks 形态/cleanup 精确杀口径/互斥候跑让位 | `service/remote_service.py` docstring 与函数体实读 | 过（§5 引语出自原文） |
| OE/ADS 通道形态与发射纪律 | `remote_oe_service.py`、`remote_ads_service.py` docstring 实读 | 过 |
| L2 现状（许可签名失效 fail-closed，代码链本地 PASS） | TODO「多机协同远程求解」条 | 过（如实转述） |
| mock 路径 | `tests/unit/test_remote_service.py` 实读（全 mock，#139） | 过 |
| 服务器硬规则（版本/E 盘/备份窗/内存/云盘/清理） | docs/服务器接入与仿真资源说明.md §10/§11 + AGENTS 规则 0/0b | 过（本文只转述，以原文为准） |
| **真连红线** | 写作全程未对任何登记机器发起 probe/status/resources/queue/冒烟 | 过 |
| **敏感面** | 全文 grep：真实 IP/真实主机名/盘符路径/用户名/密码零命中；主机用 `<host>` 占位，凭据零出现 | 过 |
