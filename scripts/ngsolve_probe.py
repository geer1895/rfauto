"""A9 NGSolve 开源 FEM 频域通道可行性探针（§10.1 A9 / §10.19 第 6 条：待确证项）。

A9 定位 = 零 license 开源 FEM 频域通道（Palace 已由用户跳过；COMSOL 席位稀缺）。
本探针只做能力确证：不求解用户资产、不写配方、不改工作区产物。每项 best-effort
（#105）——任何异常落成 available=false/unknown，脚本不崩。

待确证口径（本项目标假设，全部实测）：
- Windows wheel 可用性：ngsolve / netgen-mesher / netgen-occt 发行版能否直接 pip 安装；
- HCurl 时谐 Maxwell：PEC 单位立方腔特征模（curl curl E = k^2 E，齐次时谐形式），
  与闭式解 k = pi*sqrt(2)（TE101）对照，报告网格/自由度/相对误差；
- 端口激励 / S 参数后处理的现成 API：ngsolve 顶层名称扫描——缺就如实记缺，
  不臆造 API，也不把"需手工实现"包装成"有现成 API"。

用法::
    .venv/Scripts/python.exe scripts/ngsolve_probe.py
    .venv/Scripts/python.exe scripts/ngsolve_probe.py --skip-real   # 离线占位（全 unknown）
    .venv/Scripts/python.exe scripts/ngsolve_probe.py --out <path>

退出码：0=核心判据（import_and_version + hcurl_timeharmonic_maxwell）均为 available；
2=核心判据非 available（如实标 partial/blocked，不凑绿）。--skip-real 恒 0。

每条记录固定五字段：{backend, capability, available, evidence, detail}，
available 取 true / false / "unknown"。
"""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
import math
import platform
import sys
import time
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO / "runs" / "ngsolve_probe" / "capability_matrix.json"

UNKNOWN = "unknown"
_VALID_AVAILABLE = (True, False, UNKNOWN)

# 决定退出码的核心判据（端口/S 参数 API 缺失是"成熟度"发现，不是探针执行失败）
CORE_CAPABILITIES = ("import_and_version", "hcurl_timeharmonic_maxwell")

# PEC 单位立方腔（边长 1，单位无关）基模 TE101 闭式解 k = pi*sqrt(2)
CAVITY_TARGET_K = math.pi * math.sqrt(2)
CAVITY_ORDER = 2
CAVITY_MAXH = 0.35
# 容差取 2%（实测 order=2 / maxh=0.35 相对误差 ~0.3%，见脚本真机输出）
CAVITY_REL_TOL = 0.02

# Windows wheel 可用性证据：这些发行版缺失即说明 pip 安装不完整
INSTALLED_DISTRIBUTIONS = ("ngsolve", "netgen-mesher", "netgen-occt", "ngsolve-openblas")

# 现成通道 API 名称扫描 token（子串匹配；命中即转 unknown 交人工核实）
API_TOKEN_GROUPS: dict[str, tuple[str, ...]] = {
    "ready_made_port_api": ("port", "waveguide", "modal", "excitation"),
    "ready_made_sparameter_api": ("sparam", "smatrix", "scatter", "touchstone"),
}
API_CAPABILITIES = tuple(API_TOKEN_GROUPS)


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
    head = f"{'backend':<10} {'capability':<30} {'available':<12} evidence"
    lines = [head, "-" * len(head)]
    labels = {True: "available", False: "unavailable"}
    for row in rows:
        status = labels.get(row.get("available"), str(row.get("available")))
        lines.append(f"{row['backend']:<10} {row['capability']:<30} {status:<12} {row.get('evidence', '')}")
    lines.append("-" * len(head))
    lines.append(
        f"total={summary['total']} available={summary['available']} "
        f"unavailable={summary['unavailable']} unknown={summary['unknown']}"
    )
    return "\n".join(lines)


# ── 纯函数（离线可测） ────────────────────────────────────────────────────────


def _dist_version(name: str) -> str | None:
    """已安装发行版版本；缺失/异常返回 None（best-effort，不触发 import）。"""
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None
    except Exception:  # 元数据损坏等：不阻断探测
        return None


def scan_api_tokens(names: Iterable[str], tokens: Iterable[str]) -> list[str]:
    """名称集合里命中任一 token（子串、大小写不敏感）的 token 列表。"""
    lowered = [str(n).lower() for n in names]
    return sorted({str(tok) for tok in tokens if any(str(tok).lower() in n for n in lowered)})


def eigen_verdict(k0: object, target: float = CAVITY_TARGET_K, tol: float = CAVITY_REL_TOL) -> bool | str:
    """特征值闭式解对照判决：True=在容差内，False=超容差，unknown=数值无效。"""
    try:
        value = float(k0)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return UNKNOWN
    if not math.isfinite(value) or not math.isfinite(target) or target == 0.0:
        return UNKNOWN
    return abs(value - target) / abs(target) <= tol


# ── 探测函数（真机；依赖注入便于离线单测） ────────────────────────────────────


def probe_import(importer: Callable[[str], object] | None = None) -> list[dict]:
    """ngsolve / netgen 可导入性 + 版本 + Windows wheel 发行版证据。"""
    imp = importer or importlib.import_module
    try:
        ngsolve = imp("ngsolve")
        netgen = imp("netgen")
    except Exception as exc:  # 导入失败=能力判负，如实记录不崩
        return [
            entry(
                "ngsolve",
                "import_and_version",
                False,
                f"{type(exc).__name__}: {exc}",
                "ngsolve/netgen 不可导入：A9 Windows 通道判 blocked（原始错误见 evidence）",
            )
        ]
    versions = {name: _dist_version(name) for name in INSTALLED_DISTRIBUTIONS}
    ns_version = getattr(ngsolve, "__version__", None)
    ng_version = getattr(netgen, "__version__", None)
    evidence = (
        f"ngsolve.__version__={ns_version}; netgen.__version__={ng_version}; "
        f"pip 发行版={versions}"
    )
    detail = "Windows cp312 wheel 由 pip 直接安装；可选依赖条目见 pyproject [project.optional-dependencies] ngsolve"
    if ns_version is None or ng_version is None:
        return [unknown_entry("ngsolve", "import_and_version", evidence, detail + "（版本属性缺失，判 unknown）")]
    return [entry("ngsolve", "import_and_version", True, evidence, detail)]


def solve_cavity_eigen(order: int = CAVITY_ORDER, maxh: float = CAVITY_MAXH) -> dict:
    """真机最小求解：PEC 单位立方腔 HCurl 特征模（时谐 Maxwell 齐次形式）。

    弱形式 ∫ curl E · curl v dx = k² ∫ E · v dx；dirichlet=".*" ⇒ 全壁 PEC
    （切向 E = 0）。梯度核（k=0）用 >1e-8 过滤后取最小正特征值。
    """
    import numpy as np
    from netgen.occ import Box, Pnt
    from ngsolve import BilinearForm, HCurl, Mesh, curl, dx
    from scipy.linalg import eigh

    started = time.time()
    geometry = Box(Pnt(0, 0, 0), Pnt(1, 1, 1))
    generated = geometry.GenerateMesh(maxh=maxh)
    mesh = generated if isinstance(generated, Mesh) else Mesh(generated)
    fes = HCurl(mesh, order=order, dirichlet=".*")
    trial, test = fes.TrialFunction(), fes.TestFunction()
    stiff = BilinearForm(fes, symmetric=True)
    stiff += curl(trial) * curl(test) * dx
    mass = BilinearForm(fes, symmetric=True)
    mass += trial * test * dx
    stiff.Assemble()
    mass.Assemble()
    dense_stiff = np.array(stiff.mat.ToDense())
    dense_mass = np.array(mass.mat.ToDense())
    free = np.array([bool(fes.FreeDofs()[i]) for i in range(fes.ndof)])
    free_idx = np.where(free)[0]
    values = eigh(
        dense_stiff[np.ix_(free_idx, free_idx)],
        dense_mass[np.ix_(free_idx, free_idx)],
        eigvals_only=True,
    )
    positive = np.sort(values[values > 1e-8])
    k0 = float(np.sqrt(positive[0])) if positive.size else float("nan")
    return {
        "order": order,
        "maxh": maxh,
        "n_elements": int(mesh.ne),
        "n_dof": int(fes.ndof),
        "n_free_dof": int(free_idx.size),
        "k0": k0,
        "target_k": CAVITY_TARGET_K,
        "rel_error": abs(k0 - CAVITY_TARGET_K) / CAVITY_TARGET_K,
        "elapsed_s": round(time.time() - started, 2),
    }


def probe_hcurl_maxwell(solve_fn: Callable[[], dict] | None = None) -> list[dict]:
    """HCurl 时谐 Maxwell 建模+求解能力：真机求解并与闭式解 k=pi*sqrt(2) 对照。"""
    solve = solve_fn or solve_cavity_eigen
    try:
        info = solve()
    except Exception as exc:  # 建模/求解异常=能力判负，如实记录不崩
        return [
            entry(
                "ngsolve",
                "hcurl_timeharmonic_maxwell",
                False,
                f"{type(exc).__name__}: {exc}",
                "HCurl 时谐 Maxwell 建模/求解异常：A9 判 partial/blocked（原始错误见 evidence）",
            )
        ]
    info = info or {}
    k0 = info.get("k0")
    target = info.get("target_k", CAVITY_TARGET_K)
    verdict = eigen_verdict(k0, target, CAVITY_REL_TOL)
    evidence = (
        f"PEC 单位立方腔 HCurl order={info.get('order')} maxh={info.get('maxh')}: "
        f"ne={info.get('n_elements')} ndof={info.get('n_dof')} free={info.get('n_free_dof')} "
        f"k0={k0} vs 闭式 pi*sqrt(2)={float(target):.6f} "
        f"rel_err={info.get('rel_error')} ({info.get('elapsed_s')}s)"
    )
    detail = "curl-curl 特征模（齐次时谐 Maxwell）；端口激励/S 参数需另行手工后处理"
    if verdict is True:
        return [entry("ngsolve", "hcurl_timeharmonic_maxwell", True, evidence, detail)]
    if verdict is False:
        return [
            entry(
                "ngsolve",
                "hcurl_timeharmonic_maxwell",
                False,
                evidence,
                detail + "；与闭式解偏差超容差，判负不凑绿",
            )
        ]
    return [unknown_entry("ngsolve", "hcurl_timeharmonic_maxwell", evidence, detail + "；数值无效，判 unknown")]


def probe_api_surface(ngsolve_names: Iterable[str] | None) -> list[dict]:
    """端口激励 / S 参数后处理现成 API 存在性（名称扫描；缺就如实记缺）。"""
    names = [str(n) for n in (ngsolve_names or [])]
    if not names:
        return [
            unknown_entry("ngsolve", cap, "无法枚举 ngsolve 顶层名称", "API 面未确证，如实记 unknown")
            for cap in API_CAPABILITIES
        ]
    rows: list[dict] = []
    for capability, tokens in API_TOKEN_GROUPS.items():
        hits = scan_api_tokens(names, tokens)
        if hits:
            rows.append(
                unknown_entry(
                    "ngsolve",
                    capability,
                    f"ngsolve 顶层名称命中 {hits}（共 {len(names)} 名）",
                    "命中名需人工核实是否真为端口/S 参数通道 API，不臆断可用",
                )
            )
        else:
            rows.append(
                entry(
                    "ngsolve",
                    capability,
                    False,
                    f"ngsolve 顶层无 {list(tokens)} 名称命中（dir(ngsolve)={len(names)} 名）",
                    "无现成 API：端口激励/S 参数需手工 mode matching + 切向场积分，"
                    "A9 该面判缺（如实记缺，不包装成熟）",
                )
            )
    return rows


def probe_ngsolve(
    importer: Callable[[str], object] | None = None,
    solve_fn: Callable[[], dict] | None = None,
) -> list[dict]:
    """A9 全量探测：import → HCurl 时谐 Maxwell → 端口/S 参数 API 面。"""
    imp = importer or importlib.import_module
    rows = probe_import(imp)
    if rows[0]["available"] is not True:
        rows.append(
            unknown_entry("ngsolve", "hcurl_timeharmonic_maxwell", "ngsolve 不可导入", "无法建模求解，跳过")
        )
        rows.extend(probe_api_surface(None))
        return rows
    rows.extend(probe_hcurl_maxwell(solve_fn))
    try:
        names = sorted(dir(imp("ngsolve")))
    except Exception:  # 名称枚举失败只影响 API 面，落 unknown（#105）
        names = []
    rows.extend(probe_api_surface(names))
    return rows


# ── 聚合 / 报告 ───────────────────────────────────────────────────────────────


def real_probe_table() -> dict[str, Callable[[], list[dict]]]:
    """真机探测表（lambda 在调用时解析全局名，便于单测 monkeypatch）。"""
    return {"ngsolve": lambda: probe_ngsolve()}


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
    """报告级环境事实（不 import ngsolve，纯元数据）。"""
    return {
        "platform": sys.platform,
        "python": platform.python_version(),
        "python_executable": sys.executable,
        "distributions": {name: _dist_version(name) for name in INSTALLED_DISTRIBUTIONS},
        "cavity": {
            "target_k": CAVITY_TARGET_K,
            "target_k_formula": "pi*sqrt(2)  # PEC 单位立方腔 TE101",
            "order": CAVITY_ORDER,
            "maxh": CAVITY_MAXH,
            "rel_tol": CAVITY_REL_TOL,
        },
    }


def build_report(
    matrix: list[dict],
    failures: list[dict],
    *,
    elapsed_s: float = 0.0,
    skip_real: bool = False,
) -> dict:
    return {
        "probe": "a9-ngsolve-open-fem-capability",
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


def core_verdict(matrix: Iterable[dict]) -> bool:
    """核心判据是否全部 available（决定退出码；端口/S 参数缺失不算执行失败）。"""
    core = [r for r in matrix if r.get("capability") in CORE_CAPABILITIES]
    return bool(core) and all(r.get("available") is True for r in core)


def _skip_probe(name: str) -> Callable[[], list[dict]]:
    def _run() -> list[dict]:
        return [unknown_entry(name, "skipped", "--skip-real", "离线占位模式，未做真机探测")]

    return _run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="能力矩阵 JSON 输出路径")
    parser.add_argument("--skip-real", action="store_true", help="不触碰真机：所有探测直接记 unknown")
    args = parser.parse_args(argv)

    started = time.time()
    table = real_probe_table()
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
    if failures:
        print(f"\n探测异常 {len(failures)} 项: {failures}")
    print(f"\nA9 NGSolve 能力矩阵 -> {out}")
    if args.skip_real:
        return 0
    if core_verdict(matrix):
        print("核心判据 PASS（import + HCurl 时谐 Maxwell）")
        return 0
    print("核心判据 FAIL（import 或 HCurl 时谐 Maxwell 非 available）——如实标 partial/blocked")
    return 2


if __name__ == "__main__":
    sys.exit(main())
