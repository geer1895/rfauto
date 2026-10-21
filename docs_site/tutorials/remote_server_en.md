<!-- PR-10 文档站同步副本：源=docs/tutorials/remote_server_en.md（scripts/build_docs_pages.py 重建，勿直接改本文件——改动请改源文件后重跑生成器） -->

# Remote Simulation Server Collaboration: Multi-Machine Channel Boundaries and First Contact

> When your research group shares one simulation server (the HFSS/ADS
> licenses and compute live over there), how do you get rfauto to send
> real solves up, pull the artifacts back, and clean up the site
> afterwards? This article covers the multi-machine surface (the
> `rfauto remote` command domain + the HFSS/openEMS/ADS remote-run
> channels): machine registration, liveness probing, resource views,
> smoke tests, and cleanup discipline. **This article performs zero real
> connections**: every remote action is described as contract + opt-in
> gate only; every `--help` was measured, and offline behaviors are
> recorded from measured runs. Server hard rules (version pairing /
> scratch-file root / backup window / cleanup) are governed by
> docs/服务器接入与仿真资源说明.md; hosts appear as `<host>` placeholders
> throughout.
> Chinese original: docs/tutorials/remote_server.md. CLI's own messages
> stay in their original language; only the narrative is translated.
> Re-verified 2026-10-19 (help surfaces, offline error paths, smoke
> opt-in gate, registry key structure, and source-docstring claims all
> re-checked against the current tree).

## 0. Prerequisites and red lines

- Environment installed per docs/tutorials/getting-started.md; the SSH
  channel is an optional extra `pip install rfauto[remote]` (paramiko is
  lazily imported; when missing you get an explicit error and the
  registry/probing surface is unaffected).
- Hard-rule quick reference (full sources: the server notes doc and
  project rules; violating any line means rework):

| Red line | Content |
|---|---|
| Version pairing | The server's AEDT must be the **same version** as local (2025 R1/v251; PyAEDT gRPC client-server version pairing + HFSS as the numeric alignment baseline); the server only needs `ansysedt -grpcsrv` listening — no pyaedt install |
| Scratch-file root | Everything temporary on the server — temp dirs, intermediate files, working dirs — goes on the **large-capacity data disk** (registry key `hfss.project_root`, registered as `rfauto_remote` under that disk); **never write to the production cloud-drive** |
| Backup window | Avoid 02:50–05:35 (nightly archive/backup/knowledge sync); overnight queues are a legitimate use case but the launch side records the risk honestly |
| Memory ceiling | The server also hosts cloud-drive/backup/AI-knowledge workloads; keep single-task memory ≤80GB; don't hog all cores and memory |
| Clean up when done | Kill the ansysedt instances this task spawned, delete its schtasks entries, remove its task directory — a failed cleanup flips the verdict to FAIL; no orphans allowed |
| Shared-machine mutex | Mutex precheck before launch: a hit on a running instance means wait-and-SKIP; **never kill other people's processes** |

- Demo boundary for this article: no real server connection is performed
  (the writing environment makes no promises about any specific server).
  Anything involving real networking is given as contract + a
  "first-contact checklist", never as a live demo.

## 1. Machine registration: the key structure of configs/remote_machines.yaml

Registration spans two files (key structure below; values are
placeholders):

```yaml
# configs/remote_machines.yaml —— credential-free, safe to commit
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

**Zero credentials in the registry** (same iron rule as the project's
upload-scrubbing policy): the registration file never holds usernames,
passwords, or private keys. Credentials live in exactly two places — the
environment variables `RFAUTO_REMOTE_SSH_USER` /
`RFAUTO_REMOTE_SSH_PASSWORD`, or the same-directory
`remote_machines.local.yaml` (gitignored) overrides `ssh_user` +
`ssh_password` / `ssh_key_path` (key takes precedence; pick key or
password). The three mTLS keys (`hfss_ca_cert`/`hfss_client_cert`/
`hfss_client_key`) likewise only go into the local override file, and
must be configured all together or omitted all together.

Loading contract: `configs/remote_machines.yaml` is read first, then the
same-directory local override file is deep-merged on top; **a missing
file means an empty table**, and the entire remote surface behaves
exactly as the local-only path ("no config, zero behavior change"). A
local file that exists but is unreadable / invalid YAML is never
silently skipped — it is recorded into `load_errors` with a warning, and
loading continues.

## 2. Probe and status: `remote probe` / `remote status`

```bash
.venv/Scripts/rfauto.exe remote probe --help
.venv/Scripts/rfauto.exe remote status --help
```

Both take the same arguments: positional `machine` (default = the sole
registered machine) + `--json/-j`.

- `probe`: TCP liveness (connect/close + latency for each port in
  `probe_ports`), **zero side effects, zero credentials** — no login, no
  files written. Output is per-port `OPEN/CLOSED + latency_ms`.
- `status`: probe + SSH authentication reachability. The verdict never
  guesses or retries: missing credentials → `ssh_auth:
  missing_credentials` (it won't even try, with a hint attached); with
  credentials present it makes one real connection, runs an echo
  command, and reports `ok/failed` from the command receipt.

Honest-error contract (measured locally; registered machine names
elided):

```bash
.venv/Scripts/rfauto.exe remote probe nosuch_demo
```

```text
RemoteConfigError: 远程机器 'nosuch_demo' 未登记（可用：<已登记机器名>）
```

(In an environment whose registry file does not exist, `probe`/`status`
print `无登记机器（configs/remote_machines.yaml）——本地模式` — CLI
contract; the writing environment has a registered machine, so that
form was not reproduced here.)

First-contact checklist (tick through on the first real connection;
this article does not run it for you):

```text
□ 1. pip install rfauto[remote]（paramiko 就位）
□ 2. rfauto remote probe            —— license/RDP/SSH 端口全 OPEN
□ 3. 凭据就位（env 或 local 覆盖文件）
□ 4. rfauto remote status           —— ssh_auth=ok
□ 5. RFAUTO_REMOTE_SMOKE=1 冒烟（见 §5）—— attach health=True 后现场已清理
```

## 3. Resource and queue views: `remote resources` / `remote queue`

```bash
.venv/Scripts/rfauto.exe remote resources --help
.venv/Scripts/rfauto.exe remote queue --help
```

- `resources`: the concurrent-solve resource view. Local half =
  openEMS/HFSS process mutex state (BUSY/IDLE); server half =
  reachability / running-process count / disk headroom. Any sub-view
  that cannot be probed degrades to `unknown` (probing failures are not
  faults and never block the aggregate view).
- `queue`: the task-queue view = in-process registered jobs + single
  writer-lock owner/queue + seat occupancy + server running state
  (process-census semantics, **not license seats**). Historical runs are
  not in the in-process registry — use `jobs status` / the meta.json
  on-disk surface.

Two privacy contracts worth remembering: **hostnames/IPs and
credentials never enter an envelope** (machines appear only as registry
key names); and `n_tasks` is None whenever any channel's census
degrades — a half-side census is never padded into a number.

## 4. Channel topology: one probing surface + three remote-run channels

The `remote` command domain itself is only the four read-only verbs
(probe/status/resources/queue); actually "sending work up" goes through
three channels, all hanging off the same registry and the same mutex
precheck:

| Channel | Service module | Shape | Status |
|---|---|---|---|
| HFSS gRPC | `service/remote_service.py` | Local pyaedt client attaches the server's `ansysedt -grpcsrv`; files via SSH/sftp | v0 delivered; L1 attach smoke passed on real hardware (probe ports all OPEN + ssh_auth=ok + attach version/health=True) |
| openEMS remote | `service/remote_oe_service.py` | The `fd_oe_campaign --remote` execution channel: render locally → sftp four lightweight files → run on server → artifacts pulled back mirroring the local runs/ layout | v1 (judgment/health gates all consumed locally; pull-back needs zero changes) |
| ADS netlist remote | `service/remote_ads_service.py` | Netlist sftp upload (self-containment check) → server-side hpeesofsim → per-file dataset pull-back | v1 (no local ADS install needed) |

Launch discipline shared by all three channels:

- **Mutex precheck first**: the authoritative criterion is a direct
  process-fingerprint query on the server side; the probe census mutex
  row is corroborating evidence. A hit = wait-and-SKIP; a failed
  precheck (rc≠0) = unverifiable, don't launch (fail-closed); **never
  kill on someone's behalf** — instances not matching this batch's
  fingerprint (including other people's GUIs or other-port sessions)
  are never touched.
- **Synchronous by default, polling only for long seats**: during an
  openEMS/ADS seat's synchronous wait the channel is necessarily alive
  and the process ends naturally; minute-to-hour seats may opt into the
  polling mode (three-evidence polling — rc file / process fingerprint /
  timeline — plus dual CPU-sample liveness re-checks, pinning silent
  kills to a 2-minute window). On timeout it never kills on your
  behalf: the PID goes into the envelope for a human to handle.
- **Criteria first**: the openEMS seat's `criteria.md` must be on disk
  before launch; missing = fail-closed (judgment-first discipline).
- **License precheck as the first gate** (`license_preflight`): all
  license ports TCP-OPEN → PASS; unreachable/unregistered → FAIL
  (fail-skip, no hard pounding). Seat-level lmstat queries are not
  wired; the envelope's `seat_level_query` honestly says UNVERIFIED —
  port OPEN ≠ seat available.

## 5. Real-hardware smoke: the opt-in gate and L1/L2

Real-hardware smoke is an **operations surface, not part of the
CLI/MCP default surface**, guarded by a single environment-variable
gate: `RFAUTO_REMOTE_SMOKE=1`. With the gate unset the service function
refuses outright (zero network; measured locally):

```bash
.venv/Scripts/python.exe -c "import sys; sys.path.insert(0,'src'); \
from rfauto.service.remote_service import remote_hfss_smoke; \
print(remote_hfss_smoke())"
```

```text
{'ok': False, 'skipped': True, 'reason': '真机冒烟需显式 opt-in：RFAUTO_REMOTE_SMOKE=1（unit 门零真机）'}
```

- **L1 attach smoke** (`remote_hfss_smoke`): probe → mutex precheck →
  SSH-launch `ansysedt -grpcsrv` (server-side working root via sftp'd
  .bat + a one-shot schtasks registration — Win32-OpenSSH session job
  objects would take down channel child processes, so persistent
  processes must go through Task Scheduler) → poll the gRPC port →
  local pyaedt attach (version-pairing assert) → health check.
  **finally-block cleanup**: any failure path after a successful launch
  reaps the spawned ansysedt and the schtasks entry (the orphan-desktop
  iron rule); the mutex wait-and-skip path is the exception — this
  launch was zero, so cleanup stands down (never kill running instances
  you don't own).
- **L2 solve smoke** (`remote_hfss_l2_smoke`, driver
  `scripts/smoke_remote_l2.py`): remote modeling (the mline anchor — a
  single source of truth for geometry/material) → solve → Touchstone
  sftp pull-back (default `runs/remote_l2/<date>/`) → skrf judgment.
  Four pre-declared judgment criteria (all pass = PASS, any miss = FAIL
  with numbers): ① the pulled-back file is skrf-readable, 2-port,
  41 points; ② in-band min|S11| ≤ -10 dB; ③ in-band min|S21| ≥ -1 dB;
  ④ S21 phase-slope εeff ∈ [2.60, 3.10] (the S11 dip position is
  reference-only, never a gate). Real-hardware campaign record: during
  a server-side hfss_gui license-signature lapse, L2 failed closed (the
  code chain's local four criteria all PASS — attributed to the server
  environment, not the code); after license renewal, one command reruns
  it:

```bash
# 真机 opt-in（unit 门零真机，绝不缺省跑）
set RFAUTO_REMOTE_SMOKE=1
.venv\Scripts\python.exe scripts\smoke_remote_l2.py --machine <machine名>
```

- **Cleanup semantics** (`remote_hfss_cleanup`): kill by PID precisely —
  first query `Win32_Process` for ansysedt ProcessId+CommandLine, and
  only kill instances whose command line contains `-grpcsrv` and this
  launch's port fingerprint; **never a bare full-name taskkill**
  (other people's GUI / other-port instances on the shared machine stay
  untouched); schtasks entries are deleted by unique name (uuid suffix,
  concurrent smokes don't stomp each other). A failed post-task cleanup
  flips the verdict to FAIL — no orphans allowed.

## 6. Offline demo and test mode (developing without a server)

- **No registered machines = local mode**: with the config file absent
  the table is empty, `probe/status` print the local-mode hint, and
  adapters/services all take the local path — offline development has
  zero behavior delta.
- **Unregistered name = honest error**: `RemoteConfigError` lists the
  available machine names (§2, measured).
- **The unit gate is fully mocked**: `tests/unit/test_remote_service.py`
  mocks every channel (fake transports / stubbed modeling — real
  hardware never enters tests even when a config exists). For channel
  behavior questions, run this suite before thinking about real
  hardware.
- **The local half works standalone**: the `resources`/`queue` local
  process-mutex half and in-process queue half don't need the server
  (note: with a machine registered, these two commands do initiate a
  TCP probe against the default machine — read-only, but a network
  action nonetheless).
- **SSH strict mode**: with `RFAUTO_SSH_STRICT=1`, a host-key mismatch
  or an absent recorded fingerprint refuses the connection; the default
  is a TOFU compromise — first connection records the fingerprint with
  a warning, and a fingerprint change errors loudly but still proceeds
  (full strict mode lands together with the mTLS channel).

## 7. When should work go to the server (usage boundaries)

- **Send it up**: HFSS/ADS real solves and arbitration, parameter
  sweeps/optimization campaigns, long-run judgment, overnight queues,
  compute batches of minutes or more — anything the server can
  accelerate goes to the server first; local keeps orchestration and
  light computation only.
- **Keep it local**: second-scale smokes / offline audits /
  render-time geometry checks — local is faster and saves server
  windows; manage real-hardware mutex with a per-machine mindset and
  don't treat the server as a free concurrency pool (the remote
  parallelism cap lives in registry key `hfss.max_parallel`, enforced
  on the v1 launch side).
- **Launch shape**: server-side launches prefer console-visible / .bat
  direct forms (hidden-window forms tend to be silently killed by
  server antivirus); after launch, liveness re-checks are mandatory.
- **Scaling out**: any new server must run the same AEDT version as
  local; onboard it via §1 registration + the §2 checklist.

## 8. Next steps

- Full server hard rules (hardware/license/ports/accounts):
  docs/服务器接入与仿真资源说明.md
- Server-side openEMS install and the nine-step SOP:
  docs/rfauto_openEMS_服务器安装与调用说明.md
- Local-side judgment and health checks for real simulation:
  docs/tutorials/real-simulation_en.md
- Campaign batch launch and `--remote` routing progress: the
  multi-machine remote-solve item in the project TODO.
- Chinese original of this article: docs/tutorials/remote_server.md.

## Appendix: verification checklist and sensitive-surface self-audit

| Command/contract | How it was checked | Result |
|---|---|---|
| `rfauto remote --help` four subcommands (probe/status/resources/queue) + each `--help` | Re-run 2026-10-19 | Pass (machine argument + --json flag on each) |
| Unregistered-name error (RemoteConfigError; machine list elided) | Re-run | Pass (§2 as recorded) |
| Gate unset → smoke honestly SKIPs (zero network) | `python -c` call to `remote_hfss_smoke()` | Pass (§5 as recorded) |
| Registry key structure / credential surface / local deep-merge / load_errors | `configs/remote_machines.yaml` read + `infra/remote_machines.py` source (values all placeholders here) | Pass |
| L1 orchestration / schtasks shape / cleanup precise-kill / mutex stand-down | `service/remote_service.py` docstrings and function bodies | Pass (§5 quotes from source) |
| OE/ADS channel shapes and launch discipline | `remote_oe_service.py`, `remote_ads_service.py` docstrings | Pass |
| L2 status (license lapse fail-closed, code chain locally PASS) | Original campaign records | Pass (reported as stated) |
| Mock path | `tests/unit/test_remote_service.py` (fully mocked) | Pass |
| Server hard rules (versions / scratch root / backup window / memory / cloud-drive / cleanup) | docs/服务器接入与仿真资源说明.md + project rules | Pass (this article only restates; the source documents govern) |
| **Real-connection red line** | Zero probe/status/resources/queue/smoke was issued against any registered machine while writing | Pass |
| **Sensitive surface** | Full-text scan: zero real IPs / real hostnames / drive-letter paths / usernames / passwords; hosts as `<host>`, credentials absent, registered machine names elided | Pass |
