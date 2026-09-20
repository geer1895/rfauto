"""多物理工具/license 能力探测（WP4.4-0）。

只探能力、不求解、不建/存任何用户资产，产出「多物理能力矩阵」JSON，供
上层路线决策。每项硬超时 + best-effort（#105）：任何异常
落成 available="unknown"，脚本不崩。

探测面：
- AEDT（本机 v251 / 2025.1）：Icepak / Q3D Extractor / Maxwell / SIwave —— 安装
  面二进制 + Ansys Licensing Client ansysli_util -checkexists <feature> 真实
  license 查询；配 hfss_solve 正控 + 不存在 feature 负控证明探针能判别。
  安装路径以实际探测为准（如 E:/ANSYSINC/ANSYS Inc/v251/AnsysEM，
  2025.1）——如实记录，不臆造。
- COMSOL 6.3：license.dat PACKAGE 特征核对（HEATTRANSFER/HT、
  STRUCTURALMECHANICS/SME）+ MPh 子进程建 HeatTransfer(ht) /
  SolidMechanics(solid) 接口试探（version="6.3" 显式钉版本，#215）。
- ADS 2027：EEsof FlexNet license server 可达性（注册表 ADS_LICENSE_FILE）+
  本机 agileesofd.lic 的 ETH/HeatWave 特征核对；不跑 hpeesofsim 仿真。
- Elmer：本机安装 / ElmerSolver 可执行性结论（只做结论，不装大件）。

复用 infra/license_probe.py 的 probe_license 做通用 license server 可达性探测。

用法::
    .venv/Scripts/python.exe scripts/multiphysics_probe.py
    .venv/Scripts/python.exe scripts/multiphysics_probe.py --skip-real   # 离线占位

每条矩阵记录固定五字段：{backend, capability, available, evidence, detail}，
available 取 true / false / "unknown"。
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path

from rfauto.infra.license_probe import probe_license

REPO = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO / "runs" / "multiphysics_probe" / "capability_matrix.json"

UNKNOWN = "unknown"
_VALID_AVAILABLE = (True, False, UNKNOWN)

LICENSE_TIMEOUT_S = 3.0
AEDT_TIMEOUT_S = 30.0
COMSOL_TIMEOUT_S = 180.0
ADS_TIMEOUT_S = 5.0
ELMER_TIMEOUT_S = 30.0

# ── AEDT（ANSYS Electronics Desktop）────────────────────────────────────────────
# 常见安装根候选（env 优先；候选逐一探测，缺失即如实记 unavailable）：
AEDT_TASK_STATED_ROOT = Path("E:/HFSS/ANSYS Inc/v261")
AEDT_ROOT_ENV_VARS = ("ANSYSEM_ROOT251", "ANSYSEM_ROOT261", "RFAUTO_AEDT_PATH")
AEDT_ROOT_CANDIDATES = (
    Path("E:/HFSS/ANSYS Inc/v261/AnsysEM"),
    Path("E:/ANSYSINC/ANSYS Inc/v261/AnsysEM"),
    Path("E:/ANSYSINC/ANSYS Inc/v251/AnsysEM"),
)
AEDT_LICENSING_UTIL = Path("licensingclient") / "winx64" / "ansysli_util.exe"
# 多物理产品 → license 特征（lmstat 实测本机 server 提供）+ 安装面二进制哨兵
AEDT_PRODUCTS: dict[str, dict[str, tuple[str, ...]]] = {
    "icepak": {"features": ("elec_solve_icepak",), "binaries": ("IcepakLib.dll", "ICEPAKCOMENGINE.exe")},
    "q3d_extractor": {"features": ("q3d_desktop",), "binaries": ("Q3D.dll", "Q3DCOMENGINE.exe")},
    "maxwell": {"features": ("maxwell_desktop",), "binaries": ("MaxwellLib.dll", "MAXWELLCOMENGINE.exe")},
    "siwave": {"features": ("siwave_gui", "siwave_solver"), "binaries": ("siwave.exe", "SIwaveSimEngine.dll")},
}
# 探针自校验：hfss_solve 已知可用（正控）；余者必不存在（负控）
AEDT_CONTROL_FEATURE = "hfss_solve"
AEDT_NEGATIVE_FEATURE = "rfauto_definitely_not_a_feature"

# ── COMSOL ────────────────────────────────────────────────────────────────────
COMSOL_VERSION_PIN = "6.3"  # #215：MPh 自动选最新=6.4（license 过期），必须显式钉
COMSOL_ROOT_CANDIDATES = (
    Path("E:/COMSOL/COMSOL_63/COMSOL63/Multiphysics"),
    Path("E:/COMSOL/COMSOL_64/COMSOL64/Multiphysics"),
)
# 能力 → （license.dat 特征候选，MPh/Java 物理场接口类型串）
COMSOL_INTERFACES: dict[str, tuple[tuple[str, ...], str]] = {
    "heat_transfer_in_solids": (("HEATTRANSFER", "HT"), "HeatTransfer"),
    "solid_mechanics": (("STRUCTURALMECHANICS", "SME"), "SolidMechanics"),
}

# ── ADS ───────────────────────────────────────────────────────────────────────
# ADS 安装根治理：安装根经环境变量 RFAUTO_HPEESOF_DIR 指定（缺省不假定任何
# 本机安装路径）；license 由 Windows 服务 "EEsof FlexNet License Server"
# （C:/Program Files/Keysight/EEsof_License_Tools/bin/lmgrd.exe，27009@localhost，
# 注册表 FLEXlm License Manager 登记 lic 文件）供给。
ADS_HOME = Path(os.environ.get("RFAUTO_HPEESOF_DIR", ""))
ADS_LICENSE_FILE_CANDIDATES = (
    Path("C:/Program Files/Keysight/EEsof_License_Tools/bin/agileesofd.lic"),
    ADS_HOME / "license" / "agileesofd.lic",
)
ADS_SIM_CANDIDATES = (
    ADS_HOME / "bin" / "hpeesofsim.exe",
)
ADS_ETH_TOKENS = ("e_sim_heatwave", "e_heatwave_sim_interface", "e_heatwave_capacity_1", "e_sim_eth_reuse")
ADS_DEFAULT_LICENSE_SERVER = "27009@localhost"
_BS = chr(92)  # 注册表路径分隔符（避免源码内反斜杠字面量）
ADS_REGISTRY_KEY = "Software" + _BS + "Keysight" + _BS + "EEsof License Configuration"
ADS_REGISTRY_VALUE = "ADS_LICENSE_FILE"

# ── Elmer ─────────────────────────────────────────────────────────────────────
ELMER_HOME_ENV = "ELMER_HOME"
ELMER_ROOT_CANDIDATES = (Path("E:/Elmer/Elmer 26.1-Release"), Path("E:/Elmer"))
ELMER_SOLVER_REL = Path("bin") / "ElmerSolver.exe"

DEFAULT_ANSYS_LICENSE_SERVER = "1055@localhost"


# ── 结构化记录 ────────────────────────────────────────────────────────────────


def entry(backend: str, capability: str, available: bool | str, evidence: str, detail: str = "") -> dict:
    """构造矩阵行；available 只允许 true/false/"unknown"。"""
    if available not in _VALID_AVAILABLE:
        raise ValueError(f"available 必须是 true/false/unknown，收到 {available!r}")
    return {
        "backend": str(backend),
        "capability": str(capability),
        "available": available,
        "evidence": str(evidence),
        "detail": str(detail),
    }


def unknown_entry(backend: str, capability: str, evidence: str, detail: str = "") -> dict:
    """探测不确定/不可执行：如实记 unknown，绝不臆断 true/false。"""
    return entry(backend, capability, UNKNOWN, evidence, detail)


def summarize(matrix: Iterable[dict]) -> dict:
    """按 available 三态计数。"""
    rows = list(matrix)
    return {
        "total": len(rows),
        "available": sum(1 for r in rows if r.get("available") is True),
        "unavailable": sum(1 for r in rows if r.get("available") is False),
        "unknown": sum(1 for r in rows if r.get("available") == UNKNOWN),
    }


def render_summary(matrix: Iterable[dict], summary: dict | None = None) -> str:
    """纯文本摘要表（真机执行时打印）。"""
    rows = list(matrix)
    summary = summary or summarize(rows)
    head = f"{'backend':<10} {'capability':<26} {'available':<12} evidence"
    lines = [head, "-" * len(head)]
    labels = {True: "available", False: "unavailable"}
    for row in rows:
        status = labels.get(row.get("available"), str(row.get("available")))
        lines.append(f"{row['backend']:<10} {row['capability']:<26} {status:<12} {row.get('evidence', '')}")
    lines.append("-" * len(head))
    lines.append(
        f"total={summary['total']} available={summary['available']} "
        f"unavailable={summary['unavailable']} unknown={summary['unknown']}"
    )
    return "\n".join(lines)


# ── 通用工具 ──────────────────────────────────────────────────────────────────


def _as_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def run_command(cmd: list[str], timeout_s: float) -> dict:
    """子进程硬超时执行；超时/OSError 都落成结构化结果，不抛异常。"""
    started = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=timeout_s)
        return {
            "rc": proc.returncode,
            "stdout": proc.stdout or "",
            "stderr": proc.stderr or "",
            "timed_out": False,
            "elapsed_s": round(time.time() - started, 1),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "rc": None,
            "stdout": _as_text(exc.stdout),
            "stderr": _as_text(exc.stderr),
            "timed_out": True,
            "elapsed_s": round(time.time() - started, 1),
        }
    except OSError as exc:  # 可执行缺失/权限：如实记录
        return {
            "rc": None,
            "stdout": "",
            "stderr": repr(exc),
            "timed_out": False,
            "elapsed_s": round(time.time() - started, 1),
        }


def resolve_first_existing(paths: Iterable[Path]) -> Path | None:
    """返回首个存在路径；全部缺失返回 None（PathLike 先收敛，见 #140）。"""
    for raw in paths:
        path = Path(raw)
        if path.exists():
            return path
    return None


def read_text_safe(path: Path | None) -> str:
    """读文本；任何 IO 错误返回空串（best-effort）。"""
    if path is None:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def mph_available() -> bool:
    """MPh 是否可导入（不触发 JVM 启动）。"""
    return importlib.util.find_spec("mph") is not None


# ── AEDT ──────────────────────────────────────────────────────────────────────


def aedt_root_candidates() -> list[Path]:
    """候选安装根：环境变量优先，且优先取 AnsysEM 子目录（v251 根 vs AnsysEM）。"""
    raw: list[Path] = []
    for var in AEDT_ROOT_ENV_VARS:
        value = os.environ.get(var, "").strip()
        if value:
            raw.append(Path(value))
    raw.extend(AEDT_ROOT_CANDIDATES)
    out: list[Path] = []
    for base in raw:
        for cand in (base / "AnsysEM", base):
            if cand not in out:
                out.append(cand)
    return out


def parse_license_check(output: str, feature: str) -> str:
    """解析 ansysli_util -checkexists 输出 → exists / missing / unknown。"""
    text = (output or "").lower()
    if f"{feature.lower()} exists" in text:
        return "exists"
    if "could not be found" in text or "not found" in text:
        return "missing"
    return UNKNOWN


def check_aedt_feature(util: Path, feature: str, timeout_s: float) -> dict:
    """真实 license 存在性查询（一次 checkout 试探，不启动桌面、不求解）。"""
    result = run_command([str(util), "-checkexists", feature], timeout_s)
    state = UNKNOWN if result["timed_out"] else parse_license_check(result["stdout"] + "\n" + result["stderr"], feature)
    return {
        "feature": feature,
        "state": state,
        "rc": result["rc"],
        "timed_out": result["timed_out"],
        "elapsed_s": result["elapsed_s"],
    }


def probe_aedt(timeout_s: float = AEDT_TIMEOUT_S) -> list[dict]:
    """Icepak / Q3D / Maxwell / SIwave license + 安装面能力探测。"""
    root = resolve_first_existing(aedt_root_candidates())
    note = "; ".join(str(p) for p in AEDT_ROOT_CANDIDATES)
    if root is None:
        return [
            unknown_entry("aedt", name, "未找到 AEDT 安装根", f"候选: {note}") for name in AEDT_PRODUCTS
        ]
    util = resolve_first_existing((root / AEDT_LICENSING_UTIL, root / "AnsysEM" / AEDT_LICENSING_UTIL))
    if util is None:
        return [
            unknown_entry("aedt", name, f"未找到 ansysli_util（root={root}）", "无法做 license checkout 试探")
            for name in AEDT_PRODUCTS
        ]
    control = check_aedt_feature(util, AEDT_CONTROL_FEATURE, timeout_s)
    negative = check_aedt_feature(util, AEDT_NEGATIVE_FEATURE, timeout_s)
    control_txt = (
        f"正控 {AEDT_CONTROL_FEATURE}={control['state']}; 负控 {AEDT_NEGATIVE_FEATURE}={negative['state']}"
    )
    entries: list[dict] = []
    for product, spec in AEDT_PRODUCTS.items():
        states = [check_aedt_feature(util, f, timeout_s) for f in spec["features"]]
        by_state = {s["feature"]: s["state"] for s in states}
        binaries = {b: (root / b).exists() for b in spec["binaries"]}
        missing_features = [f for f, s in by_state.items() if s == "missing"]
        unknown_features = [f for f, s in by_state.items() if s == UNKNOWN]
        missing_bins = [b for b, ok in binaries.items() if not ok]
        if missing_features or missing_bins:
            available: bool | str = False
        elif unknown_features:
            available = UNKNOWN
        else:
            available = True
        evidence = f"ansysli_util -checkexists -> {by_state}; binaries={binaries}; root={root}; {control_txt}"
        detail = (
            f"AEDT 安装 {root}；"
            f"license 查询工具 {util}；不启动桌面、不求解"
        )
        entries.append(entry("aedt", product, available, evidence, detail))
    return entries


# ── COMSOL ────────────────────────────────────────────────────────────────────


def extract_license_components(text: str) -> set[str]:
    """从 COMSOL license.dat 抽 PACKAGE COMPONENTS 特征名（跨行，反斜杠续行不碍事）。"""
    tokens: set[str] = set()
    for chunk in (text or "").split("COMPONENTS")[1:]:
        if "=" not in chunk:
            continue
        rest = chunk.split("=", 1)[1].lstrip()
        if not rest.startswith('"'):
            continue
        body = rest[1:].split('"', 1)[0]
        tokens.update(body.split())
    return {t.upper() for t in tokens}


def parse_child_json(stdout: str) -> dict:
    """从子进程 stdout 取最后一行 PROBE_JSON=<json>。"""
    marker = "PROBE_JSON="
    for line in reversed((stdout or "").splitlines()):
        if line.startswith(marker):
            try:
                payload = json.loads(line[len(marker):])
            except json.JSONDecodeError:
                return {}
            return payload if isinstance(payload, dict) else {}
    return {}


def comsol_child_probe(version: str = COMSOL_VERSION_PIN, cores: int = 2) -> dict:
    """子进程侧 COMSOL 试探：启 server → 建 ht/solid 接口（不求解）。"""
    payload: dict = {"version": version, "interfaces": {}, "ok": False, "error": None}
    started = time.time()
    client = None
    model = None
    try:
        import mph

        client = mph.start(version=version, cores=cores)
        model = client.create(f"rfauto_mp_probe_{int(time.time())}")
        j = model.java
        j.component().create("comp1", True)
        comp = j.component("comp1")
        geom = comp.geom().create("geom1", 3)
        geom.lengthUnit("mm")
        geom.create("blk1", "Block")
        geom.feature("blk1").set("size", ["10", "10", "1"])
        geom.run()
        for _cap, (_, physics_type) in COMSOL_INTERFACES.items():
            tag = "ht" if physics_type == "HeatTransfer" else "solid"
            try:
                comp.physics().create(tag, physics_type, "geom1")
                payload["interfaces"][physics_type] = {"tag": tag, "status": "created"}
            except Exception as exc:  # 单接口失败不中断另一接口
                payload["interfaces"][physics_type] = {
                    "tag": tag,
                    "status": "failed",
                    "error": repr(exc)[:300],
                }
        payload["ok"] = bool(payload["interfaces"]) and all(
            v["status"] == "created" for v in payload["interfaces"].values()
        )
    except Exception as exc:
        payload["error"] = repr(exc)[:500]
    finally:
        if client is not None and model is not None:
            with contextlib.suppress(Exception):
                client.remove(model)
    payload["elapsed_s"] = round(time.time() - started, 1)
    return payload


def probe_comsol(timeout_s: float = COMSOL_TIMEOUT_S) -> list[dict]:
    """COMSOL 6.3 基础 license 是否含 ht/solid 核心接口。"""
    root = resolve_first_existing(COMSOL_ROOT_CANDIDATES)
    lic_path = (root / "license" / "license.dat") if root else None
    components = extract_license_components(read_text_safe(lic_path))
    entitle = {cap: sorted(f for f in feats if f in components) for cap, (feats, _) in COMSOL_INTERFACES.items()}
    if not mph_available():
        return [
            unknown_entry(
                "comsol",
                cap,
                f"{lic_path} 特征命中 {entitle[cap] or '无'}",
                "MPh 未安装，无法做接口 checkout 试探（不臆断）",
            )
            for cap in COMSOL_INTERFACES
        ]
    child = run_command([sys.executable, str(Path(__file__).resolve()), "--comsol-child"], timeout_s)
    payload = {} if child["timed_out"] else parse_child_json(child["stdout"])
    interfaces = payload.get("interfaces", {}) if isinstance(payload, dict) else {}
    entries: list[dict] = []
    for cap, (_, physics_type) in COMSOL_INTERFACES.items():
        iface = interfaces.get(physics_type, {}) if isinstance(interfaces, dict) else {}
        status = iface.get("status")
        if child["timed_out"]:
            available: bool | str = UNKNOWN
        elif status == "created":
            available = True
        elif status == "failed":
            available = False
        else:
            available = UNKNOWN
        evidence = (
            f"license.dat {lic_path} PACKAGE 特征命中 {entitle[cap] or '无'}; "
            f"MPh {COMSOL_VERSION_PIN} 建 {physics_type} 接口 -> {status or 'N/A'}; 子进程 {child['elapsed_s']}s"
        )
        detail = (
            f"version 显式钉 {COMSOL_VERSION_PIN}（#215）；子进程隔离硬超时 {timeout_s:.0f}s；不求解、用完即关。"
            f"child_error={payload.get('error') or iface.get('error') or 'none'}"
        )
        entries.append(entry("comsol", cap, available, evidence, detail))
    return entries


# ── ADS ───────────────────────────────────────────────────────────────────────


def read_ads_license_server() -> str:
    """从 Keysight 注册表读 ADS license server；失败回退默认值。"""
    try:
        import winreg  # 仅 Windows 可用；函数内导入保证跨平台可导入

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, ADS_REGISTRY_KEY) as key:
            value, _ = winreg.QueryValueEx(key, ADS_REGISTRY_VALUE)
            text = str(value).strip()
            return text or ADS_DEFAULT_LICENSE_SERVER
    except (OSError, ImportError):
        return ADS_DEFAULT_LICENSE_SERVER


def probe_license_servers(timeout_s: float = LICENSE_TIMEOUT_S) -> list[dict]:
    """通用 license server 可达性（复用 infra/license_probe.probe_license）。"""
    servers = (
        ("aedt", os.environ.get("ANSYSLMD_LICENSE_FILE", "").strip() or DEFAULT_ANSYS_LICENSE_SERVER),
        ("ads", read_ads_license_server()),
    )
    entries: list[dict] = []
    for backend, server in servers:
        result = probe_license(server, timeout_s=timeout_s)
        if result.get("server") is None:
            entries.append(
                unknown_entry(backend, "license_server_reachable", "未配置 license server", str(result.get("detail", "")))
            )
        else:
            entries.append(
                entry(
                    backend,
                    "license_server_reachable",
                    bool(result.get("available")),
                    f"server={result.get('server')}",
                    str(result.get("detail", "")),
                )
            )
    return entries


def probe_ads(timeout_s: float = ADS_TIMEOUT_S) -> list[dict]:
    """ADS 2027 电热（ETH / Electrothermal）license 探测；不跑仿真。"""
    server = read_ads_license_server()
    reachable = probe_license(server, timeout_s=timeout_s)
    lic_path = resolve_first_existing(ADS_LICENSE_FILE_CANDIDATES)
    lic_text = read_text_safe(lic_path)
    tokens = sorted({t for t in ADS_ETH_TOKENS if t.lower() in lic_text.lower()})
    sim_bin = resolve_first_existing(ADS_SIM_CANDIDATES)
    if reachable.get("server") is None or not reachable.get("available"):
        available: bool | str = UNKNOWN
        reason = f"license server {server} 不可达（{reachable.get('detail')}），无法做 ETH checkout 试探"
    elif tokens:
        available = True
        reason = f"license server 可达且 license 文件含 ETH 特征 {tokens}"
    else:
        available = UNKNOWN
        reason = "license server 可达但未在 license 文件核对到 ETH 特征"
    evidence = (
        f"ADS license server={server} reachable={bool(reachable.get('available'))}; "
        f"agileesofd.lic={lic_path} ETH 特征命中 {tokens or '无'}; hpeesofsim={sim_bin}"
    )
    detail = (
        f"{reason}；本项只做 license 探测，不跑 hpeesofsim 仿真（任务允许口径）；"
        "EEsof FlexNet License Server 服务状态见证据"
    )
    return [entry("ads", "electrothermal_eth", available, evidence, detail)]


# ── Elmer ─────────────────────────────────────────────────────────────────────


def resolve_elmer_home() -> Path | None:
    """ELMER_HOME 优先，其次常见安装根。"""
    env = os.environ.get(ELMER_HOME_ENV, "").strip()
    candidates: list[Path] = [Path(env)] if env else []
    candidates.extend(ELMER_ROOT_CANDIDATES)
    return resolve_first_existing(candidates)


def parse_elmer_version(stdout: str) -> str | None:
    match = re.search("ELMER SOLVER[^0-9]*([0-9][0-9A-Za-z.-]*)", stdout or "", re.IGNORECASE)
    return match.group(1) if match else None


def probe_elmer(timeout_s: float = ELMER_TIMEOUT_S) -> list[dict]:
    """Elmer Windows 安装到 E:/ 的可行性结论（只探测，不安装）。"""
    home = resolve_elmer_home()
    if home is None:
        return [
            unknown_entry(
                "elmer",
                "open_source_install",
                f"ELMER_HOME 未设且候选 {[str(p) for p in ELMER_ROOT_CANDIDATES]} 均不存在",
                "本机未发现 Elmer；只做结论，不安装大件",
            )
        ]
    solver = home / ELMER_SOLVER_REL
    if not solver.exists():
        return [
            entry(
                "elmer",
                "open_source_install",
                False,
                f"ELMER_HOME={home} 下未找到 {ELMER_SOLVER_REL}",
                "安装不完整：仅目录存在但 ElmerSolver 缺失",
            )
        ]
    result = run_command([str(solver), "--version"], timeout_s)
    version = parse_elmer_version(result["stdout"] + "\n" + result["stderr"])
    if result["timed_out"]:
        available: bool | str = UNKNOWN
    elif version is not None:
        available = True
    else:
        available = UNKNOWN
    evidence = (
        f"ELMER_HOME={home}; {ELMER_SOLVER_REL} 存在; "
        f"ElmerSolver --version -> {version or 'N/A'}（rc={result['rc']}, {result['elapsed_s']}s）"
    )
    detail = "本机已安装到 E:/，无需再下官方安装器；只做结论，不安装大件（任务口径）"
    return [entry("elmer", "open_source_install", available, evidence, detail)]


# ── 聚合 / 报告 ───────────────────────────────────────────────────────────────


def real_probe_table(timeout_s: float | None = None) -> dict[str, Callable[[], list[dict]]]:
    """真机探测表（lambda 在调用时解析全局名，便于单测 monkeypatch）。"""
    t = timeout_s
    return {
        "license_servers": lambda: probe_license_servers(t or LICENSE_TIMEOUT_S),
        "aedt": lambda: probe_aedt(t or AEDT_TIMEOUT_S),
        "comsol": lambda: probe_comsol(t or COMSOL_TIMEOUT_S),
        "ads": lambda: probe_ads(t or ADS_TIMEOUT_S),
        "elmer": lambda: probe_elmer(t or ELMER_TIMEOUT_S),
    }


def collect_capabilities(
    probe_table: dict[str, Callable[[], list[dict]]] | None = None,
) -> tuple[list[dict], list[dict]]:
    """逐项 best-effort 聚合：单项异常落 unknown 并记入 failures，绝不中断。"""
    table = dict(probe_table) if probe_table is not None else real_probe_table()
    matrix: list[dict] = []
    failures: list[dict] = []
    for name, probe in table.items():
        try:
            rows = probe()
        except Exception as exc:  # #105：观测性代码不得成为主路径故障点
            matrix.append(
                unknown_entry(name, "probe", f"{type(exc).__name__}: {exc}", "探测异常，best-effort 落 unknown")
            )
            failures.append({"probe": name, "error": f"{type(exc).__name__}: {exc}"})
            continue
        for row in rows or []:
            matrix.append(row)
    return matrix, failures


def build_meta() -> dict:
    """报告级环境事实（安装根 / license server），供 §1 表回写引用。"""
    return {
        "aedt_root": str(resolve_first_existing(aedt_root_candidates()) or ""),
        "aedt_root_task_stated": str(AEDT_TASK_STATED_ROOT),
        "aedt_root_task_stated_exists": AEDT_TASK_STATED_ROOT.exists(),
        "aedt_products": list(AEDT_PRODUCTS),
        "comsol_root": str(resolve_first_existing(COMSOL_ROOT_CANDIDATES) or ""),
        "comsol_version_pin": COMSOL_VERSION_PIN,
        "ads_license_server": read_ads_license_server(),
        "hpeesofsim": str(resolve_first_existing(ADS_SIM_CANDIDATES) or ""),
        "elmer_home": str(resolve_elmer_home() or ""),
    }


def build_report(matrix: list[dict], failures: list[dict], *, elapsed_s: float = 0.0, skip_real: bool = False) -> dict:
    return {
        "probe": "wp440-multiphysics-capability-matrix",
        "schema": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "host": {"platform": sys.platform, "python": sys.version.split()[0]},
        "meta": build_meta(),
        "matrix": matrix,
        "summary": summarize(matrix),
        "probe_failures": failures,
        "elapsed_s": round(elapsed_s, 1),
        "skip_real": skip_real,
    }


def write_report(report: dict, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path


def _skip_probe(name: str) -> Callable[[], list[dict]]:
    def _run() -> list[dict]:
        return [unknown_entry(name, "skipped", "--skip-real", "离线占位模式，未做真机探测")]

    return _run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="能力矩阵 JSON 输出路径")
    parser.add_argument("--timeout", type=float, default=None, help="覆盖所有真机子探测的硬超时（秒）")
    parser.add_argument("--skip-real", action="store_true", help="不触碰真机：所有探测直接记 unknown")
    parser.add_argument("--comsol-child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.comsol_child:
        payload = comsol_child_probe()
        print("PROBE_JSON=" + json.dumps(payload, ensure_ascii=False, default=str))
        return 0

    started = time.time()
    table = real_probe_table(args.timeout)
    if args.skip_real:
        table = {name: _skip_probe(name) for name in table}
    matrix, failures = collect_capabilities(table)
    report = build_report(matrix, failures, elapsed_s=time.time() - started, skip_real=args.skip_real)
    out = Path(args.out)
    try:
        write_report(report, out)
    except OSError as exc:
        print(f"[ERROR] 写能力矩阵失败: {exc}", file=sys.stderr)
        return 1
    print(render_summary(matrix, report["summary"]))
    print(f"\n多物理能力矩阵 -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
