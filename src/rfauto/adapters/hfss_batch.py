"""HFSS 一次性批处理求解（one-shot batch，无长驻桌面会话）。

每求解一个独立短命 ``ansysedt`` 进程：``ansysedt -ng -BatchSolve
<project.aedt>``（官方批处理命令行与普通工程同款；Ansys 团队确认路径
也可指向 *.aedb native database 文件夹——.aedt 文件优先，.aedb 目录
回退）。动机：会话污染类故障的结构性修复 + 与 openEMS 逐求解子进程
模式统一；无长驻桌面即无会话态可污染，超时即整树回收无孤儿桌面
（#265 铁律的结构性兑现）。

分层：adapters（可依赖 pipeline/infra，绝不 import service/cli）——
- 进程超时 watchdog 复用 pipeline.watchdog.Watchdog（只复用不改）；
- AEDT 安装发现复用 infra.version_probe（RFAUTO_AEDT_PATH env 约定 +
  ANSYSEM_ROOTxxx 自动探测），找不到明确报错不猜。

进程树击杀边界（#245 不盲杀）：本模块只对**自己 Popen 拉起的子进程**
做 watchdog 超时回收（pid 由 Popen 句柄持有，不存在误伤）；仓内既有
桌面清场（他人孤儿 ansysedt）仍归 infra.desktop_guard 单源，此处绝不
按进程名扫杀。psutil 树杀优先（terminate→kill 两段），taskkill /F /T
兜底（Python subprocess 直调不经 git-bash，无 //PID 斜杠转义坑）。

结果回收（best-effort #105）：求解结束后扫描工程产物——Touchstone
（.sNp）与 AEDT 结果文件（.prof/.csv/.mesh/BlockInformation），路径
清单随结构化结果返回；logfile 尾部随结果回读（失败判读第一现场）。

Touchstone 批后导出（2026-10-08 真机冒烟补路）：``-BatchSolve`` 只求解
不产网络参数（artifacts=0，EDB 快车道判读断链）——``export_touchstone=
True`` 时于求解成功后拉起第二个短命批处理进程 ``ansysedt -ng
-batchextract <script.py> <project>``（官方旗标：非图形跑脚本后自动退出，
不做求解 license 检查）跑内嵌 IronPython 导出脚本（``ExportNetworkData``
14 参直连口径，同 hfss_adapter._direct_export_touchstone / remote_service
L2 先例）。脚本为模块内字符串资产按字面量烘焙（IronPython 2 口径：纯
ASCII 无 f-string、不读 argv/env）；导出失败只向 errors 追加告警项，
绝不推翻求解 ok（#105）。

导出分派（2026-10-08 W5 真机实证，runs/edblane85/w5_batch_campaign/）：
HFSS 3D Layout 设计（EDB 快车道产物形态）**无任何 Analysis 模块**——
GetModule("AnalysisSetup"/"Setup"/"Output"/"Solutions") 四名全 FAIL，
``ExportNetworkData`` 直接挂在 design 对象上（pyaedt analysis.py 源码
先例：design_type=="HFSS 3D Layout Design" 时 module=self.odesign，
"HFSS" 时才走 osolution 模块）。导出脚本先探针 design.GetModule(
"Solutions")（HFSS 3D 建模器口径），失败自动回退 design 级直呼——
无旗标自动适配两形态；setup 枚举同样不可达时按 EDB 快车道惯例取
名义名（setup1:sweep1）兜底。脚本 QuitApplication 置于 finally：
-batchextract FATAL 早退也必须退出批处理会话，否则留孤儿桌面
（#265 家族，W5 实证）。
"""

from __future__ import annotations

import contextlib
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from rfauto.pipeline.watchdog import Watchdog

#: AEDT 批处理日志文件名形态（<stem> 拼工程名，落 logfile_dir/工程旁）。
BATCH_LOGFILE_FMT = "ansysedt_batch_{stem}.log"

#: -batchextract 第二段进程的日志文件名形态（与求解段分开，互不覆盖）。
BATCH_EXTRACT_LOGFILE_FMT = "ansysedt_batch_extract_{stem}.log"

#: -batchextract 导出脚本的落盘文件名（每次烘焙重写，随 logfile 目录留档
#  ——渲染字面量在档证据链，2026-09-24 #49 cf5 语义）。
BATCH_EXTRACT_SCRIPT_FMT = "batch_extract_touchstone_{stem}.py"

#: -batchextract 提取段 watchdog 缺省超时（工程加载数十秒 + 导出秒~分钟级，
#  给足一个数量级余量；到点整树击杀同求解段语义）。
BATCH_EXTRACT_TIMEOUT_S = 600.0

#: 批后导出缺省产物名（落工程旁，collect_solve_artifacts 浅层可扫到）。
#: 扩展名是占位（.s2p）——导出后按文件内容反推实际端口数再改名 .sNp
#: （skrf 只认扩展名推断 rank，hfss_adapter 同款纪律，#248/#309）。
BATCH_EXPORT_TOUCHSTONE_FMT = "{stem}_export.s2p"

#: 结构化结果回读的 logfile 尾部行数（失败判读第一现场，非全量回拖）。
LOGFILE_TAIL_LINES = 40

#: 产物扫描条目上限（防巨型结果目录拖死返回面；超出截断并注记）。
MAX_ARTIFACTS = 200

#: Touchstone 扩展名（.sNp，N=1..2 位；大小写不敏感）。
_TOUCHSTONE_RE = re.compile(r"\.s(\d{1,2})p$", re.IGNORECASE)

#: AEDT 结果文件扩展名（BatchSolve 常见落盘面；touchstone 之外的白名单）。
_RESULT_EXTS = (".prof", ".csv", ".mesh", ".sol")

#: ``-designs`` 设计限定在 AEDT 2025 R1 (v251) ``-BatchSolve`` **不受支持**
#: （2026-10-13 sim_host 真机核实 verdict=FAIL，runs/aurora_c/designs_verify/
#: ：`-designs DesignB` 与 `-designs DesignA:setup1` 两形态旗标被静默吞掉，
#: 值按 ``Unexpected command line argument 'DesignB' ignored.`` 丢弃并
#: **退化为全设计求解（rc=0）**；desktop.dll 命令行选项表无 -designs）。
#: 带"假限定"发射是静默 solve-all 隐患（多烧许可/墙钟+产物新鲜度误信），
#: 故本模块对 design/setup 限定请求 fail-closed（结构化失败，零发射）。
_DESIGNS_UNSUPPORTED_MSG = (
    "-designs 设计限定不受 AEDT 2025 R1 (v251) -BatchSolve 支持"
    "（2026-10-13 真机核实：旗标被忽略并退化为全设计求解，console log"
    " 'Unexpected command line argument ... ignored'，证据"
    " runs/aurora_c/designs_verify/）——为避免静默 solve-all 本模块拒绝"
    "发射；限定了设计的需求请按设计拆分工程（每工程单设计）后批解，或走"
    " hfss_session 会话通道指定设计分析")

_EXE_NAME = "ansysedt.exe"


# ─── AEDT 安装发现（复用 infra.version_probe 既有链，勿新造）─────────────────

def _exe_candidates_under(install_dir: Path) -> list[Path]:
    """安装版本目录 → ansysedt.exe 候选（按布局可信度排序）。"""
    return [
        install_dir / "AnsysEM" / _EXE_NAME,  # v251 实测布局（ANSYSEM_ROOT251 上层）
        install_dir / "Win64" / _EXE_NAME,    # 旧布局（<版本目录>\Win64）
        install_dir / _EXE_NAME,              # env 直指 bin 层的安装形态
    ]


def find_ansysedt_exe(explicit: str | Path | None = None) -> Path | None:
    """定位本机 ansysedt.exe（找不到返回 None，由调用方明确报错）。

    优先级：
    1. ``explicit``：入参直指 exe 文件（存在即用）或安装目录（在其下
       按候选布局找）；
    2. 环境变量 ``RFAUTO_AEDT_PATH``（仓内既有约定，service/api 同源）；
    3. 自动探测（``infra.version_probe.resolve_aedt_install``：ANSYSEM_
       ROOTxxx env + Windows 注册表，取最高版本安装）。

    另将 ANSYSEM_ROOTxxx 原值目录本身纳入候选（部分安装把该 env 指到
    AnsysEM bin 层而非版本目录，version_probe 已归一版本目录，原值目录
    直下再试一次零成本兜底）。
    """
    from rfauto.infra.version_probe import resolve_aedt_install

    if explicit:
        p = Path(explicit)
        if p.is_file():
            return p
        if p.is_dir():
            for cand in _exe_candidates_under(p):
                if cand.is_file():
                    return cand
        return None

    install = resolve_aedt_install(
        os.environ.get("RFAUTO_AEDT_PATH") or None)
    if install is not None:
        for cand in _exe_candidates_under(Path(install["path"])):
            if cand.is_file():
                return cand

    # ANSYSEM_ROOTxxx 原值目录兜底（env 直指 bin 层形态）
    for name, value in os.environ.items():
        if not name.startswith("ANSYSEM_ROOT"):
            continue
        cand = Path(value) / _EXE_NAME
        if cand.is_file():
            return cand
    return None


# ─── 命令行构造（纯函数，测试钉字面）────────────────────────────────────────

def build_batch_command(
    ansysedt_exe: str | Path,
    project_path: str | Path,
    design: str | None = None,
    setup: str | None = None,
    logfile: str | Path | None = None,
) -> list[str]:
    """拼 ansysedt 批处理命令行（官方形态，非交互 ``-ng`` 无 GUI）。

    模板：``ansysedt.exe -ng -BatchSolve [-Logfile <path>] <project>``；
    -Logfile 收 AEDT 自身输出（进程 console 输出另由 Popen 重定向追加进
    同一文件）。

    参数顺序纪律（真机实证 2026-10-08，runs/edblane85/w1_smoke/）：
    AEDT 2025 R1 拒收"-Logfile 置于工程之后"（requires a filename
    ... last parameter，rc=1）——**工程路径必须恒为末位**。

    design/setup（历史形态 ``-designs <design:setup>``）：**2026-10-13
    真机核实不受 v251 支持**（旗标被静默吞、值按 unexpected argument
    丢弃、退化全设计求解，见 :data:`_DESIGNS_UNSUPPORTED_MSG`）——传非
    None 即抛 ValueError（纯函数 fail-loud；solve_project_batch 在发射
    前先行结构化 fail-closed，生产链不会触达本抛错）。
    """
    if design or setup:
        raise ValueError(_DESIGNS_UNSUPPORTED_MSG)
    cmd = [str(ansysedt_exe), "-ng", "-BatchSolve"]
    if logfile:
        cmd += ["-Logfile", str(logfile)]
    cmd.append(str(project_path))
    return cmd


# ─── 进程树回收（只对自己拉起的子进程；#245 不盲杀）──────────────────────────

def _kill_process_tree(pid: int, timeout_s: float = 10.0) -> bool:
    """击杀进程树（psutil terminate→kill 两段优先，taskkill /F /T 兜底）。

    只用于本模块 watchdog 超时回收**自己 Popen 的子进程**（ansysedt 会
    fork 求解子进程，单杀根进程留孤儿，故整树）。返回是否全树清零。
    """
    try:
        import psutil
    except ImportError:
        psutil = None  # 兜底路径可用，缺 psutil 不致命

    if psutil is not None:
        try:
            parent = psutil.Process(pid)
            procs = [*parent.children(recursive=True), parent]
        except psutil.Error:
            procs = []
        for proc in procs:
            with contextlib.suppress(psutil.Error):
                proc.terminate()
        _, alive = psutil.wait_procs(procs, timeout=max(timeout_s / 2, 0.5))
        for proc in alive:
            with contextlib.suppress(psutil.Error):
                proc.kill()
        _, alive = psutil.wait_procs(alive, timeout=max(timeout_s / 2, 0.5))
        if not alive:
            return True
        # 仍有存活 → 落到 taskkill 兜底再补一刀

    try:
        # Python subprocess 直调 Windows 原生参数（不经 git-bash 转义层）
        r = subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True, timeout=max(timeout_s, 1.0), check=False)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


# ─── 工程路径归一（.aedt 文件优先，.aedb 目录回退）───────────────────────────

def normalize_project_path(project_path: str | Path
                           ) -> tuple[Path, str] | None:
    """工程路径 → (规范化路径, 形态 "aedt"|"aedb")；两态都不成立=None。

    - 存在的文件 → .aedt 形态（扩展名不强制，官方口径 .aedt 优先）；
    - 存在的目录 → 须 .aedb 后缀（native database 文件夹，Ansys 团队
      确认 -BatchSolve 直接受）；
    - 不存在 → None（调用方明确报错，含两种可接受形态的提示）。
    """
    p = Path(project_path)
    if p.is_file():
        return p, "aedt"
    if p.is_dir() and p.suffix.lower() == ".aedb":
        return p, "aedb"
    return None


# ─── 产物回收（best-effort #105：扫描失败不翻求解结果）───────────────────────

def _is_touchstone(name: str) -> bool:
    return bool(_TOUCHSTONE_RE.search(name))


def _is_result_file(name: str) -> bool:
    return name.lower().endswith(_RESULT_EXTS)


def collect_solve_artifacts(project_path: str | Path,
                            limit: int = MAX_ARTIFACTS) -> list[str]:
    """求解完成后扫描工程目录产物（touchstone/结果文件路径清单）。

    扫描根（工程旁目录**浅层**，2026-10-08 审查批 P1 修正两处：①rglob 递归
    会把同父目录下兄弟工程/他 run 的同名白名单产物混进本工程清单——父目录
    常为共享工作目录；②results 目录名原为 ``<p.name>.aedtresults``（对
    demo.aedt 拼出 demo.aedt.aedtresults，恒不存在——真机布局是
    ``<stem>.aedtresults``，runs/edblane85/w1_smoke/branchline 实证），其失
    效一直被①的父目录递归扫描掩盖；两处同修后工程旁浅层+工程专属目录递归）：
    - .aedt 工程 → ``<stem>.aedtresults/``（递归）+ 工程旁浅层（批后导出
      ``<stem>_export.sNp`` 落工程旁，浅层即覆盖）；
    - .aedb 工程 → .aedb 目录内（递归，工程自有目录无跨工程污染面）。
    命中=Touchstone（.sNp）+ 结果白名单（.prof/.csv/.mesh/.sol）；
    排序稳定、截断于 ``limit``。任何扫描异常降级为已收集部分（不抛）。
    """
    p = Path(project_path)
    # (扫描根, 是否递归)：父目录浅层防兄弟工程产物混入，工程自有目录递归
    roots: list[tuple[Path, bool]] = []
    if p.is_file():
        results_dir = p.parent / f"{p.stem}.aedtresults"
        if results_dir.is_dir():
            roots.append((results_dir, True))
        roots.append((p.parent, False))
    elif p.is_dir():
        roots.append((p, True))

    found: set[str] = set()
    for root, recursive in roots:
        try:
            entries = root.rglob("*") if recursive else root.iterdir()
            for entry in entries:
                if not entry.is_file():
                    continue
                name = entry.name
                if _is_touchstone(name) or _is_result_file(name):
                    found.add(str(entry))
                    if len(found) >= limit:
                        break
        except OSError:
            continue  # 单根扫描失败降级（#105），已收部分照常返回
        if len(found) >= limit:
            break
    return sorted(found)[:limit]


def read_logfile_tail(logfile: str | Path,
                      max_lines: int = LOGFILE_TAIL_LINES) -> str:
    """logfile 尾部回读（失败判读第一现场；读不到返回空串不抛）。"""
    try:
        with open(logfile, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            window = min(size, 256 * 1024)
            f.seek(size - window)
            blob = f.read(window)
    except OSError:
        return ""
    lines = blob.decode("utf-8", errors="replace").splitlines()
    return "\n".join(lines[-max_lines:])


# ─── Touchstone 批后导出（-batchextract 第二段进程，官方旗标）────────────────
#
# 铁律：本段全部 best-effort（#105）——导出失败不抛异常、不推翻求解 ok，
# 结构化 errors 由调用方追加告警项。

#: 模板占位符残留守卫（token 模式）：只认 ``<<大写TOKEN>>`` 形态——值内
#: 字面 ``<<``（``D<<1``/``a<<b>>`` 类合法名）不误报（裸 ``"<<" in text``
#: 会把这类名误判成模板漏洞并抛 ValueError 逃逸调用点）；token 形态的值
#: 与模板残留不可区分，保守方向仍拦（绝不带占位符上真机）。
_TEMPLATE_TOKEN_RE = re.compile(r"<<[A-Z_][A-Z_0-9]*>>")


def _bake_string_literal(value: str) -> str:
    """值 → IronPython 2 双引号字面量安全文本（烘焙注入面转义）。

    反斜杠加倍、双引号前缀反斜杠、控制字符（<0x20 与 DEL）转 ``\\xNN``
    形态——含 ``"``/``\\``/换行/控制字符的 design/setup/sweep 名不再产出
    语法坏脚本，且脚本内值逐位保真（测试 exec 回读钉）；普通值（含正斜杠
    路径）逐字节不变。非 ASCII 不在此转义，由烘焙后 isascii 守卫拦下
    （ValueError → 调用点结构化失败）。
    """
    escaped: list[str] = []
    for ch in str(value):
        if ch == "\\":
            escaped.append("\\\\")
        elif ch == '"':
            escaped.append('\\"')
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            escaped.append(f"\\x{ord(ch):02x}")
        else:
            escaped.append(ch)
    return "".join(escaped)


#: -batchextract 导出脚本模板。口径（2025 R1 内嵌 IronPython 2.7）：
#: 纯 ASCII、无 f-string、无 py3-only 语法；全部可变值以 ``<<TOKEN>>``
#: 占位由 :func:`build_batch_extract_script` 烘焙成字面量，脚本自身不读
#: argv/env/配置。ExportNetworkData 14 参签名与 hfss_adapter.
#: _direct_export_touchstone / remote_service L2 真机先例逐参一致；
#: API 名（GetActiveProject/GetTopDesignList/SetActiveDesign/
#: AnalysisSetup.GetSetups/GetSweeps）经 pyaedt COM 协议桩核对。
_BATCH_EXTRACT_SCRIPT_TEMPLATE = '''# -*- coding: utf-8 -*-
# AEDT batch-extract script: export Touchstone after BatchSolve.
# Generated by rfauto.adapters.hfss_batch (all values baked as literals;
# the script reads no argv/env). Run mode (official flag):
#   ansysedt -ng -batchextract <this script> <project>
# Interpreter: AEDT embedded IronPython 2.7 -- no f-strings, no py3-only
# syntax, ASCII only. Design/setup/sweep left empty means auto-pick
# (active design / first setup / first sweep, with nominal fallback).
# Export dispatch (2026-10-08 W5 evidence): the Solutions-module path is
# probed first (HFSS 3D modeler caliber); on failure the design-level
# ExportNetworkData is used -- HFSS 3D Layout designs carry no analysis
# modules at all (GetModule fails for every name) and expose the method
# on the design object itself (pyaedt analysis.py precedent: module =
# self.odesign for design_type "HFSS 3D Layout Design"). QuitApplication
# runs in finally: a FATAL early exit must still quit the batch session,
# else the -batchextract process lingers as an orphan desktop (#265).

_OUT_FILE = "<<OUT_FILE>>"
_DESIGN_NAME = "<<DESIGN_NAME>>"
_SETUP_NAME = "<<SETUP_NAME>>"
_SWEEP_NAME = "<<SWEEP_NAME>>"
_RENORM = <<RENORM>>
_EXPECT_PROJECT = "<<PROJECT_NAME>>"

# Nominal fallback when no analysis module is reachable (HFSS 3D Layout
# caliber, EDB-lane convention; W5 evidence: setup1:sweep1 exports fine).
_NOMINAL_SETUP = "setup1"
_NOMINAL_SWEEP = "sweep1"


def _log(msg):
    try:
        print("[rfauto-batch-extract] " + str(msg))
    except Exception:
        pass


def _fail(msg):
    raise RuntimeError("[rfauto-batch-extract] FATAL: " + str(msg))


def _pick_project():
    p = oDesktop.GetActiveProject()
    if p is not None:
        return p
    try:
        projects = oDesktop.GetProjects()
    except Exception:
        projects = None
    if projects is not None and len(projects) > 0:
        return projects[0]
    return None


def _pick_design(project):
    if _DESIGN_NAME:
        try:
            d = project.SetActiveDesign(_DESIGN_NAME)
        except Exception as exc:
            _fail("pinned design not accessible: " + _DESIGN_NAME
                  + " (" + str(exc) + ")")
        if d is None:
            _fail("pinned design not accessible: " + _DESIGN_NAME)
        return d
    d = project.GetActiveDesign()
    if d is not None:
        return d
    try:
        entries = list(project.GetTopDesignList())
    except Exception:
        entries = []
    for entry in entries:
        # pyaedt-grade parse: entries may look like "name;editor", design
        # name is the last ";-separated" token (same rule as pyaedt).
        name = str(entry).split(";")[-1]
        try:
            d = project.SetActiveDesign(name)
        except Exception:
            d = None
        if d is not None:
            return d
    return None


def _module_setups(design, module_name):
    try:
        mod = design.GetModule(module_name)
        return mod, list(mod.GetSetups())
    except Exception:
        return None, []


def _module_sweeps(design, module_name, setup):
    try:
        return list(design.GetModule(module_name).GetSweeps(setup))
    except Exception:
        return []


def _first_sweep(design, setup):
    for module_name in ("AnalysisSetup", "Setup"):
        sweeps = _module_sweeps(design, module_name, setup)
        if sweeps:
            return str(sweeps[0])
    return ""


def _resolve_solution(design):
    if _SETUP_NAME:
        return _SETUP_NAME, (_SWEEP_NAME or _first_sweep(design, _SETUP_NAME))
    setups = []
    mod = None
    for module_name in ("AnalysisSetup", "Setup"):
        mod, setups = _module_setups(design, module_name)
        if setups:
            break
    if mod is None or not setups:
        # No analysis module reachable (HFSS 3D Layout designs carry
        # none at all; W5 evidence). Nominal EDB-lane names keep the
        # export auto-adaptive without flags.
        _log("setup enumeration unavailable, nominal fallback: "
             + _NOMINAL_SETUP + ":" + _NOMINAL_SWEEP)
        return _NOMINAL_SETUP, (_SWEEP_NAME or _NOMINAL_SWEEP)
    setup = str(setups[0])
    return setup, (_SWEEP_NAME or _first_sweep(design, setup))


def _export_network(design, selection):
    # Dispatch probe: Solutions module first (HFSS 3D modeler caliber);
    # on any failure fall back to the design-level call (HFSS 3D Layout
    # caliber, pyaedt analysis.py precedent). All 14 args identical on
    # both paths (list form: the solution entry is re-baked when the
    # design-level sweep padding kicks in below).
    args = [
        "",                       # DesignVariations: empty = nominal
        [selection],              # solution selection (Setup or Setup:Sweep)
        3,                        # FileFormat 3 = Touchstone (.sNp)
        _OUT_FILE,                # absolute output path (forward slashes)
        ["all"],                  # FreqsArray: all frequency points
        _RENORM,                  # DoRenorm (renormalize to 50 ohm)
        50,                       # RenormImped
        "S",                      # DataType
        -1,                       # Pass: -1 = all passes
        0,                        # ComplexFormat 0 = Mag/Phase
        15,                       # DigitsPrecision
        False,
        False,                    # IncludeGammaImpedance
        False,                    # NonStandardExtensions
    ]
    try:
        solutions = design.GetModule("Solutions")
        solutions.ExportNetworkData(*args)
        _log("export path: Solutions module")
        return
    except Exception as exc:
        _log("Solutions module path unavailable (" + str(exc)
             + "), falling back to design-level export")
    if ":" not in selection:
        # Design-level caliber (pyaedt) always sends Setup:Sweep pairs;
        # pad the nominal sweep when enumeration had no sweep to offer.
        selection = selection + ":" + _NOMINAL_SWEEP
        args[1] = [selection]
        _log("design-level selection padded to " + selection)
    try:
        design.ExportNetworkData(*args)
    except Exception as exc:
        _fail("both export paths failed; design-level error: " + str(exc))
    _log("export path: design-level (HFSS 3D Layout caliber)")


def main():
    try:
        _log("start, expect project: " + _EXPECT_PROJECT)
        project = _pick_project()
        if project is None:
            _fail("no project open in batch-extract session")
        _log("project: " + str(project.GetName()))
        design = _pick_design(project)
        if design is None:
            _fail("no design accessible in project")
        _log("design: " + str(design.GetName()))
        setup, sweep = _resolve_solution(design)
        selection = setup + (":" + sweep if sweep else "")
        _log("solution selection: " + selection)
        _export_network(design, selection)
        _log("export issued: " + _OUT_FILE)
    finally:
        # FATAL early exits must still quit the batch session, else the
        # -batchextract process lingers as an orphan desktop (#265).
        try:
            oDesktop.QuitApplication()
        except Exception:
            pass


main()
'''


def build_batch_extract_script(
    project_name: str = "",
    design: str = "",
    setup: str = "",
    sweep: str = "",
    out_file: str | Path = "",
    renorm: bool = False,
) -> str:
    """烘焙 -batchextract 导出脚本（纯函数，测试可钉字面）。

    占位符 ``<<TOKEN>>`` 整体 replace（模板含 ``%``/花括号安全）；字符串
    值烘焙前经 :func:`_bake_string_literal` 转义（反斜杠/双引号/控制字符
    ——含特殊字符的 design/setup/sweep 名产出语法合法且值保真的脚本）；
    替换后仍残留 token 形态 ``<<X>>``（大写 token 模式正则）即模板漏洞，
    抛 ValueError（绝不带占位符上真机；值内非 token 形态 ``<<`` 不误报）。
    产物保证纯 ASCII（IronPython 2 编码面零风险），非 ASCII 名抛
    ValueError——调用点（``export_touchstone_after_solve``/
    ``solve_project_batch``）捕成结构化失败，绝不逃逸到 CLI/MCP 信封
    （edb_solve 只捕 RuntimeError/OSError）。design/setup/sweep 传空串=
    脚本内自动枚举（HFSS 3D Layout 设计无 Analysis 模块可枚举时按名义
    名 setup1:sweep1 兜底 + design 级 ``ExportNetworkData`` 回退，自动
    适配无需旗标）；``out_file`` 烘焙为正斜杠绝对路径。
    """
    text = _BATCH_EXTRACT_SCRIPT_TEMPLATE
    for token, value in (
        ("<<OUT_FILE>>",
         _bake_string_literal(
             Path(out_file).as_posix() if str(out_file) else "")),
        ("<<DESIGN_NAME>>", _bake_string_literal(design or "")),
        ("<<SETUP_NAME>>", _bake_string_literal(setup or "")),
        ("<<SWEEP_NAME>>", _bake_string_literal(sweep or "")),
        ("<<RENORM>>", "True" if renorm else "False"),
        ("<<PROJECT_NAME>>", _bake_string_literal(project_name or "")),
    ):
        text = text.replace(token, value)
    if _TEMPLATE_TOKEN_RE.search(text):
        raise ValueError("导出脚本模板存在未替换占位符（禁上真机）")
    if not text.isascii():
        raise ValueError("导出脚本非纯 ASCII（IronPython 2 编码面风险）")
    return text


def build_batch_extract_command(
    ansysedt_exe: str | Path,
    script_path: str | Path,
    project_path: str | Path,
) -> list[str]:
    """拼 -batchextract 命令行（官方旗标：非图形跑脚本后自动退出，不做
    求解 license 检查）。

    模板：``ansysedt.exe -ng -batchextract <script.py> <project>``——
    沿用 -BatchSolve 真机实证的参数顺序纪律（2026-10-08）：**工程路径
    恒为末位**。
    """
    return [str(ansysedt_exe), "-ng", "-batchextract",
            str(script_path), str(project_path)]


def _write_extract_script(path: Path, text: str) -> None:
    """导出脚本落盘（LF 行尾；测试注入失败 monkeypatch 此函数）。"""
    path.write_text(text, encoding="utf-8", newline="\n")


def _infer_touchstone_ports(path: Path) -> int | None:
    """按文件内容反推端口数（hfss_adapter 单源，best-effort 不抛）。"""
    try:
        from rfauto.adapters.hfss_adapter import infer_touchstone_port_count
        return infer_touchstone_port_count(path)
    except Exception:
        return None


def _touchstone_path_for_ports(path: Path, n_ports: int) -> Path:
    """按端口数纠正 .sNp 扩展名（hfss_adapter 单源，best-effort 原样回退）。"""
    try:
        from rfauto.adapters.hfss_adapter import touchstone_path_for_ports
        return touchstone_path_for_ports(path, n_ports)
    except Exception:
        return path


def _export_fail_result(
    errors: list[str], *, project: str, mode: str = "batchextract",
    project_kind: str = "", ansysedt_exe: str = "",
    command: list[str] | None = None, script: str = "", logfile: str = "",
    elapsed: float = 0.0,
) -> dict[str, Any]:
    """导出段前置失败（mode/路径/exe/脚本落盘/拉起）的统一结构化出口。"""
    return {
        "ok": False,
        "rc": None,
        "timed_out": False,
        "mode": mode,
        "command": list(command or []),
        "ansysedt_exe": ansysedt_exe,
        "project": project,
        "project_kind": project_kind,
        "script": script,
        "logfile": logfile,
        "logfile_tail": read_logfile_tail(logfile) if logfile else "",
        "out_file": None,
        "n_ports": None,
        "elapsed_s": round(elapsed, 3),
        "errors": errors,
    }


def export_touchstone_after_solve(
    project_path: str | Path,
    design: str | None = None,
    setup: str | None = None,
    sweep: str | None = None,
    out_path: str | Path | None = None,
    renorm: bool = False,
    timeout_s: float = BATCH_EXTRACT_TIMEOUT_S,
    ansysedt_exe: str | Path | None = None,
    logfile_dir: str | Path | None = None,
    mode: str = "batchextract",
) -> dict[str, Any]:
    """批后导出 Touchstone（第二段短命 ansysedt ``-batchextract`` 进程）。

    动机（真机冒烟 2026-10-08）：``-BatchSolve`` 只求解不产网络参数
    （artifacts=0，EDB 快车道判读断链）——求解完成后用官方旗标拉起第二
    个无 GUI 批处理进程跑 IronPython 导出脚本（``ExportNetworkData``
    14 参直连口径，与 hfss_adapter._direct_export_touchstone /
    remote_service L2 先例逐参一致）。

    参数：
    - ``design``/``setup``/``sweep``：None=脚本内自动枚举（活动设计/
      首个设计、首个 setup、首个 sweep；AnalysisSetup→Setup 模块名双试；
      HFSS 3D Layout 设计无任何 Analysis 模块可枚举（W5 实证四名全
      FAIL）时自动回退 design 级 ``ExportNetworkData`` + 名义名
      setup1:sweep1 兜底，无需旗标）；sweep 缺省=setup-only 选择即
      nominal 口径（design 级回退路径会补名义 sweep 成 Setup:Sweep 对）；
    - ``out_path``：缺省 ``<stem>_export.s2p`` 落工程旁（占位扩展名——
      导出后按文件内容反推实际端口数并改名 .sNp，hfss_adapter
      ``infer_touchstone_port_count`` 单源；Touchstone 内容不依赖扩展名，
      改名即可无需重导出）；
    - ``renorm``：False=原生参考基（hfss_adapter 主路径口径），
      True=50Ω 重归一（remote_service L2 口径）；
    - ``timeout_s``：watchdog 超时（秒），到点整树击杀；``<=0`` 不设超时；
    - ``mode``：``"batchextract"``=官方旗标段（已实现）；``"session"``
      为回退 B 的**预留接口位**（hfss_session 短会话导出，当前结构化
      报错未接线，绝不静默走错通道）。

    失败语义（#105 best-effort）：本函数不抛异常——一切失败落结构化
    ``ok=False`` + ``errors``，由调用方决定是否告警（solve_project_batch
    追加告警项、不推翻求解 ok）；脚本烘焙守卫 ValueError（占位符残留/
    非 ASCII 名）同样结构化落账不逃逸。提取段被击杀树可能残留
    ``<project>.lock``，复跑前按 #157 核对进程后清理。

    返回：``{ok, rc, timed_out, mode, command, ansysedt_exe, project,
    project_kind, script, logfile, logfile_tail, out_file, n_ports,
    elapsed_s, errors}``——``ok`` = 输出文件存在且未超时；``rc`` 为提取
    进程退出码（前置失败 None）。
    """
    started = time.monotonic()
    errors: list[str] = []

    if mode != "batchextract":
        return _export_fail_result(
            errors=[f"导出后端 mode={mode!r} 尚未接线（预留回退位："
                    "hfss_session 短会话导出，口径见 hfss_adapter."
                    "HfssAdapter.export_touchstone）"],
            project=str(project_path), mode=mode, elapsed=_elapsed(started))

    if not isinstance(project_path, (str, os.PathLike)):
        return _export_fail_result(
            errors=[f"project_path 形态非法: {project_path!r}"],
            project=str(project_path), mode=mode, elapsed=_elapsed(started))

    resolved = normalize_project_path(project_path)
    if resolved is None:
        return _export_fail_result(
            errors=[f"工程路径不存在或形态不可识别: {project_path}"
                    "（可接受：.aedt 工程文件，或 .aedb 目录）"],
            project=str(project_path), mode=mode, elapsed=_elapsed(started))
    project, kind = resolved

    exe_path = find_ansysedt_exe(ansysedt_exe)
    if exe_path is None:
        return _export_fail_result(
            errors=["未找到 ansysedt.exe（RFAUTO_AEDT_PATH/自动探测均未命中）"],
            project=str(project), project_kind=kind, mode=mode,
            elapsed=_elapsed(started))

    stem = project.stem if kind == "aedt" else project.name
    # 路径参数形态守卫（审查批 P2 补）：非路径形态（如 int）在 Path() 构造
    # 即 TypeError、嵌空字节在 mkdir/unlink 处 ValueError——两者都不是
    # OSError，裸抛即违"本函数不抛异常"承诺（edb_solve 只捕
    # RuntimeError/OSError），一律结构化落账。
    for _pname, _pval in (("out_path", out_path),
                          ("logfile_dir", logfile_dir)):
        if _pval is not None and not isinstance(_pval, (str, os.PathLike)):
            return _export_fail_result(
                errors=[f"{_pname} 形态非法: {_pval!r}（须为路径或 None）"],
                project=str(project), project_kind=kind, mode=mode,
                elapsed=_elapsed(started))
    out = (Path(out_path) if out_path
           else project.parent / BATCH_EXPORT_TOUCHSTONE_FMT.format(stem=stem))
    log_dir = Path(logfile_dir) if logfile_dir else project.parent
    if "\x00" in str(out) or "\x00" in str(log_dir):
        # 空字节路径早拦（is_file 对其吞错返回 False，探测不到）——防带病
        # out 路径白发射一段真机 ansysedt 会话（license 席位浪费）。
        return _export_fail_result(
            errors=["导出路径/日志目录形态非法（含空字节）: "
                    f"out={out!r} log_dir={log_dir!r}"],
            project=str(project), project_kind=kind,
            ansysedt_exe=str(exe_path), mode=mode, elapsed=_elapsed(started))
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except (OSError, ValueError) as exc:
        # ValueError=路径嵌空字节等形态非法（mkdir 对其抛 ValueError 非
        # OSError，审查批 P2 补），与磁盘/权限失败同落结构化出口。
        return _export_fail_result(
            errors=[f"日志目录不可创建: {log_dir}（{exc}）"],
            project=str(project), project_kind=kind,
            ansysedt_exe=str(exe_path), mode=mode, elapsed=_elapsed(started))
    logfile = log_dir / BATCH_EXTRACT_LOGFILE_FMT.format(stem=stem)
    script_path = log_dir / BATCH_EXTRACT_SCRIPT_FMT.format(stem=stem)
    try:
        script_text = build_batch_extract_script(
            project_name=project.name, design=design or "", setup=setup or "",
            sweep=sweep or "", out_file=out, renorm=renorm)
    except ValueError as exc:
        # 烘焙守卫（占位符残留/非 ASCII）结构化落账，绝不逃逸（本函数
        # 不抛异常承诺；edb_solve 只捕 RuntimeError/OSError，裸 ValueError
        # 直达即信封契约违例）
        return _export_fail_result(
            errors=[f"导出脚本烘焙失败: {exc}"],
            project=str(project), project_kind=kind,
            ansysedt_exe=str(exe_path), mode=mode, elapsed=_elapsed(started))
    try:
        _write_extract_script(script_path, script_text)
    except OSError as exc:
        return _export_fail_result(
            errors=[f"导出脚本写入失败: {script_path}（{exc}）"],
            project=str(project), project_kind=kind,
            ansysedt_exe=str(exe_path), mode=mode, elapsed=_elapsed(started))

    # 陈旧产物防御：同路径旧导出文件先行移除，防失败路径误读旧解
    # （ValueError=路径嵌空字节等形态非法，suppress(OSError) 接不住——
    # 审查批 P2 补；坏路径在下方 out.is_file() 处自然落"未生成"出口）
    with contextlib.suppress(OSError, ValueError):
        Path(out).unlink(missing_ok=True)

    cmd = build_batch_extract_command(exe_path, script_path, project)

    timed_out = False
    rc: int | None = None
    try:
        # console 输出追加进 logfile（脚本侧 [rfauto-batch-extract] 行 +
        # IronPython traceback 是失败判读第一现场）
        with open(logfile, "ab") as log_handle:
            proc = subprocess.Popen(
                cmd, stdout=log_handle, stderr=subprocess.STDOUT,
                cwd=str(log_dir))
            wd = Watchdog()
            if timeout_s and timeout_s > 0:
                wd.start(timeout_s, lambda: _on_watchdog_fire(proc.pid))
            try:
                rc = proc.wait()
            except BaseException:
                # 异常路径也整树回收，不留孤儿桌面（#265 语义同求解段）
                wd.cancel()
                _kill_process_tree(proc.pid)
                with contextlib.suppress(subprocess.SubprocessError):
                    proc.wait(timeout=10.0)
                raise
            finally:
                wd.cancel()
            timed_out = wd.fired
    except OSError as exc:
        return _export_fail_result(
            errors=[f"ansysedt 提取进程拉起失败: {exc}"],
            project=str(project), project_kind=kind,
            ansysedt_exe=str(exe_path), command=cmd, script=str(script_path),
            logfile=str(logfile), mode=mode, elapsed=_elapsed(started))

    if timed_out:
        errors.append(f"导出超时（>{timeout_s:.0f}s），进程树已整树击杀"
                      f"（击杀后退出码 rc={rc}）")
    elif rc != 0:
        errors.append(f"ansysedt 提取进程退出码非零: rc={rc}"
                      "（详见 logfile 尾部 [rfauto-batch-extract] 行）")

    final_out = out
    n_ports: int | None = None
    if out.is_file() and not timed_out:
        n_ports = _infer_touchstone_ports(out)
        if n_ports:
            corrected = _touchstone_path_for_ports(out, n_ports)
            if corrected != out:
                try:
                    out.replace(corrected)
                    final_out = corrected
                except OSError as exc:
                    errors.append(f"扩展名按端口数 {n_ports} 修正失败"
                                  f"（数据仍在 {out}）: {exc}")
        else:
            errors.append("端口数推断不可用（infer_touchstone_port_count"
                          f"=None），扩展名保持 {out.suffix or '<无>'}")
    elif not out.is_file():
        errors.append(f"导出文件未生成: {out}（脚本/选择器错误通常见 "
                      "logfile 尾部 [rfauto-batch-extract] 行或 "
                      "IronPython traceback）")

    return {
        "ok": bool(final_out.is_file() and not timed_out),
        "rc": rc,
        "timed_out": bool(timed_out),
        "mode": mode,
        "command": cmd,
        "ansysedt_exe": str(exe_path),
        "project": str(project),
        "project_kind": kind,
        "script": str(script_path),
        "logfile": str(logfile),
        "logfile_tail": read_logfile_tail(logfile),
        "out_file": str(final_out) if final_out.is_file() else None,
        "n_ports": n_ports,
        "elapsed_s": round(_elapsed(started), 3),
        "errors": errors,
    }


# ─── 主入口 ──────────────────────────────────────────────────────────────────

def solve_project_batch(
    project_path: str | Path,
    design: str | None = None,
    setup: str | None = None,
    sweep: str | None = None,
    timeout_s: float = 3600.0,
    logfile_dir: str | Path | None = None,
    ansysedt_exe: str | Path | None = None,
    export_touchstone: bool = False,
) -> dict[str, Any]:
    """一次性批处理求解工程（每求解一个独立短命 ansysedt 进程）。

    流程：工程路径归一（.aedt 文件/.aedb 目录）→ ansysedt.exe 发现
    （``find_ansysedt_exe``，找不到明确报错）→ 命令行拼装（``build_
    batch_command``）→ Popen 发射（console 输出重定向追加进 logfile）
    → ``Watchdog`` 超时语义整树击杀（pipeline.watchdog 复用）→ 产物
    扫描 + logfile 尾部回读 → 结构化结果。

    参数：
    - ``design``/``setup``：历史形态为 ``-designs <design:setup>`` 限定；
      **2026-10-13 真机核实 AEDT 2025 R1 (v251) ``-BatchSolve`` 不支持该
      旗标**（静默退化为全设计求解，证据 :data:`_DESIGNS_UNSUPPORTED_MSG`
      与 runs/aurora_c/designs_verify/）——传非 None 时**发射前结构化
      fail-closed**（``ok=False``/``rc=None``/零进程零许可消耗），绝不带
      假限定发射；``None``=工程内全部设计求解（AEDT 缺省语义，真机对照
      臂实证）。
    - ``sweep``：批后导出段的 sweep 选择（仅 ``export_touchstone=True``
      时生效，透传 ``export_touchstone_after_solve``；求解命令行不带
      sweep——``-BatchSolve`` 求解面无 sweep/设计限定旗标可传）；
      None=导出脚本内自动枚举/名义兜底。
    - ``timeout_s``：watchdog 超时（秒），到点整树击杀并如实记
      ``timed_out=True``、``ok=False``；``<=0`` 视为不设超时（无限等）。
    - ``logfile_dir``：日志目录（缺省=工程旁）；目录不存在自动创建。
    - ``ansysedt_exe``：显式 exe 路径（缺省走 ``find_ansysedt_exe``
      发现链）。
    - ``export_touchstone``：True=求解成功后追加第二段 ``-batchextract``
      进程导出 Touchstone（缺省 False=零行为变化，补 ``-BatchSolve``
      不产网络参数的断链，2026-10-08 真机冒烟）。仅 ``rc==0 且未超时``
      时尝试；导出失败只向 ``errors`` 追加告警项，**绝不推翻求解
      ok**（#105 best-effort；导出链 ValueError 亦结构化兜底不逃逸）；
      导出细节见 ``export_touchstone_after_
      solve`` 与结果 ``export`` 键。

    返回（ExecutorFn/服务面可直接消费的结构化 dict，零数值面）：
    ``{ok, rc, timed_out, command, ansysedt_exe, project, project_kind,
    logfile, logfile_tail, artifacts, export, elapsed_s, errors}``——
    ``ok`` 仅在 ``rc==0 且未超时`` 为真；``rc=None`` 表示前置失败未拉起
    进程（路径/exe/日志目录/发射，此时 ``errors`` 说明原因）；``export``
    为导出段结构化结果（未请求或求解未成功=None）。
    """
    started = time.monotonic()
    errors: list[str] = []
    cmd: list[str] = []
    exe_path: Path | None = None
    logfile: Path | None = None

    if not isinstance(project_path, (str, os.PathLike)):
        return _fail_result(
            errors=[f"project_path 形态非法: {project_path!r}"
                    "（须为 .aedt 工程文件或 .aedb 目录路径）"],
            project=str(project_path), elapsed=_elapsed(started))

    resolved = normalize_project_path(project_path)
    if resolved is None:
        return _fail_result(
            errors=[f"工程路径不存在或形态不可识别: {project_path}"
                    "（可接受：.aedt 工程文件，或 .aedb native database"
                    " 目录）"],
            project=str(project_path), elapsed=_elapsed(started))
    project, kind = resolved

    # -designs 设计限定不受 v251 支持（真机核实 FAIL，2026-10-13）——
    # 发射前结构化 fail-closed（零进程零许可），绝不带假限定静默 solve-all。
    if design or setup:
        return _fail_result(
            errors=[_DESIGNS_UNSUPPORTED_MSG],
            project=str(project), project_kind=kind, elapsed=_elapsed(started))

    exe_path = find_ansysedt_exe(ansysedt_exe)
    if exe_path is None:
        return _fail_result(
            errors=["未找到 ansysedt.exe：RFAUTO_AEDT_PATH 未设置且自动"
                    "探测未发现安装（可设 RFAUTO_AEDT_PATH=<AEDT 版本目录>，"
                    "如 E:\\ANSYSINC\\ANSYS Inc\\v251，或显式传 ansysedt_"
                    "exe=<...>/ansysedt.exe）"],
            project=str(project), project_kind=kind,
            elapsed=_elapsed(started))

    if logfile_dir is not None and not isinstance(logfile_dir,
                                                  (str, os.PathLike)):
        # 形态守卫（审查批 P2 补）：非路径形态 Path() 构造即 TypeError——
        # 结构化落账，不让裸异常逃到 executor/服务层。
        return _fail_result(
            errors=[f"logfile_dir 形态非法: {logfile_dir!r}"
                    "（须为路径或 None）"],
            project=str(project), project_kind=kind, elapsed=_elapsed(started))

    log_dir = Path(logfile_dir) if logfile_dir else project.parent
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except (OSError, ValueError) as exc:
        # ValueError=logfile_dir 嵌空字节等形态非法（mkdir 抛 ValueError 非
        # OSError，审查批 P2 补）——结构化失败同路，绝不让裸异常逃到
        # executor/服务层（_route_batch_stage 对本函数不设 try，节点失败
        # 面留给真正的求解异常）。
        return _fail_result(
            errors=[f"日志目录不可创建: {log_dir}（{exc}）"],
            project=str(project), project_kind=kind,
            ansysedt_exe=str(exe_path), elapsed=_elapsed(started))
    logfile = log_dir / BATCH_LOGFILE_FMT.format(
        stem=project.name if kind == "aedb" else project.stem)

    cmd = build_batch_command(exe_path, project, design=design, setup=setup,
                              logfile=logfile)

    # console 输出追加进 logfile（-Logfile 收 AEDT 自身日志，此处收
    # 启动器侧 stdout/stderr；文件句柄直写无管道死锁面）
    timed_out = False
    rc: int | None = None
    try:
        with open(logfile, "ab") as log_handle:
            proc = subprocess.Popen(
                cmd, stdout=log_handle, stderr=subprocess.STDOUT,
                cwd=str(log_dir))
            wd = Watchdog()
            if timeout_s and timeout_s > 0:
                wd.start(timeout_s, lambda: _on_watchdog_fire(proc.pid))
            try:
                rc = proc.wait()
            except BaseException:
                # 异常路径（含 KeyboardInterrupt）也整树回收，不留孤儿桌面
                wd.cancel()
                _kill_process_tree(proc.pid)
                with contextlib.suppress(subprocess.SubprocessError):
                    proc.wait(timeout=10.0)
                raise
            finally:
                wd.cancel()
            timed_out = wd.fired
    except OSError as exc:
        return _fail_result(
            errors=[f"ansysedt 进程拉起失败: {exc}"],
            project=str(project), project_kind=kind,
            ansysedt_exe=str(exe_path), command=cmd, logfile=str(logfile),
            elapsed=_elapsed(started))

    if timed_out:
        errors.append(f"求解超时（>{timeout_s:.0f}s），进程树已整树击杀"
                      f"（击杀后退出码 rc={rc}）")
    elif rc != 0:
        errors.append(f"ansysedt 退出码非零: rc={rc}（详见 logfile 尾部）")

    # Touchstone 批后导出（可选，仅求解成功时；失败只告警不推翻 ok，
    # #105 best-effort）。导出链异常（含未来回归引入的烘焙守卫类
    # ValueError）结构化兜底，绝不逃逸——edb_solve 只捕
    # (RuntimeError, OSError)，裸 ValueError 直达即信封契约违例。
    export_info: dict[str, Any] | None = None
    if export_touchstone and rc == 0 and not timed_out:
        try:
            export_info = export_touchstone_after_solve(
                project, design=design, setup=setup, sweep=sweep,
                logfile_dir=log_dir)
        except ValueError as exc:
            export_info = _export_fail_result(
                errors=[f"导出段异常（结构化兜底）: {exc}"],
                project=str(project), project_kind=kind,
                ansysedt_exe=str(exe_path), elapsed=_elapsed(started))
        if not export_info.get("ok"):
            errors.append(
                "Touchstone 批后导出失败（不推翻求解 ok，#105 best-effort"
                "）: " + "；".join(export_info.get("errors") or ["未知原因"]))

    return {
        "ok": bool(rc == 0 and not timed_out),
        "rc": rc,
        "timed_out": bool(timed_out),
        "command": cmd,
        "ansysedt_exe": str(exe_path),
        "project": str(project),
        "project_kind": kind,
        "logfile": str(logfile),
        "logfile_tail": read_logfile_tail(logfile),
        # 产物扫描置于导出尝试之后：批后导出的 .sNp 随 artifacts 一并回收
        "artifacts": collect_solve_artifacts(project),
        "export": export_info,
        "elapsed_s": round(_elapsed(started), 3),
        "errors": errors,
    }


def _on_watchdog_fire(pid: int) -> None:
    """watchdog 到点回调：整树击杀（坑账 #157/#265 语义：不留孤儿桌面）。"""
    import logging

    logging.getLogger(__name__).warning(
        "hfss_batch: ansysedt pid=%s 超时，整树击杀", pid)
    _kill_process_tree(pid)


def _elapsed(started: float) -> float:
    return time.monotonic() - started


def _fail_result(errors: list[str], *, project: str,
                 project_kind: str = "", ansysedt_exe: str = "",
                 command: list[str] | None = None, logfile: str = "",
                 elapsed: float = 0.0) -> dict[str, Any]:
    """前置失败（路径/exe/日志目录/拉起）的统一结构化失败出口。"""
    return {
        "ok": False,
        "rc": None,
        "timed_out": False,
        "command": list(command or []),
        "ansysedt_exe": ansysedt_exe,
        "project": project,
        "project_kind": project_kind,
        "logfile": logfile,
        "logfile_tail": read_logfile_tail(logfile) if logfile else "",
        "artifacts": [],
        "elapsed_s": round(elapsed, 3),
        "errors": errors,
    }
