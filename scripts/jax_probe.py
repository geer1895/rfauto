"""A7 JAX 可微 FDTD（CPU）小规模可行性探针（§10.1 A7 / §10.18 第 2 条；GPU 为用户侧跳过项）。

A7 定位 = JAX 原生可微 FDTD（FDTDX/rfx 路线），价值 = 第三 FDTD 引擎交叉验证 +
E5 梯度路径脱离 Meep CPU adjoint。本探针只做 CPU 小规模能力确证：不求解用户资产、
不写配方、不改工作区产物。每项 best-effort（#105）——任何异常落成 available=false/
unknown，脚本不崩。

待确证口径（本项目标假设，全部实测）：
- jax / jaxlib 能否 pip 直装、能否导入、版本与 x64 开关；
- 可见设备（GPU 为用户侧跳过项，只确证 CPU 通道存在）；
- 最小 1D Yee FDTD 时间步进（归一化单位 c=eps0=mu0=1）是否确定性 + 数值稳定；
- jax.grad 能否穿过完整时间步进对材料参数 theta 求梯度，并与同一 objective 的
  中心有限差分对拍（相对误差目标 <= 1e-3，达不到如实报实际值）。

用法::
    .venv/Scripts/python.exe scripts/jax_probe.py
    .venv/Scripts/python.exe scripts/jax_probe.py --skip-real   # 离线占位（全 unknown）
    .venv/Scripts/python.exe scripts/jax_probe.py --out <path>

退出码：0=核心判据（import_and_version + differentiable_fdtd_grad）均 available；
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
DEFAULT_OUT = REPO / "runs" / "jax_probe" / "capability_matrix.json"

UNKNOWN = "unknown"
_VALID_AVAILABLE = (True, False, UNKNOWN)
_REL_EPS = 1e-300

# 决定退出码的核心判据（设备面/稳定性是成熟度发现，不是探针执行失败）
CORE_CAPABILITIES = ("import_and_version", "differentiable_fdtd_grad")

# Windows wheel 可用性证据：这些发行版缺失即说明 pip 安装不完整
INSTALLED_DISTRIBUTIONS = ("jax", "jaxlib", "ml_dtypes", "opt_einsum")

# ── 最小 1D Yee FDTD 口径（归一化：c = eps0 = mu0 = 1，S = c*dt/dx）────────────────
FDTD_N_CELLS = 240
FDTD_STEPS = 320
FDTD_COURANT = 0.5  # S = c*dt/dx < 1 ⇒ 稳定；波速 0.5 cell/step
FDTD_SRC_INDEX = 60
FDTD_PROBE_INDEX = 150  # 源-探针距 90 cell ⇒ 180 step 到达，320 step 内走完
FDTD_SLAB = (110, 150)  # theta 作用的介质板区间 [lo, hi)
FDTD_THETA0 = 0.35  # 参考介电增量：eps_r = 1 + theta * mask
FDTD_PULSE_T0 = 40.0
FDTD_PULSE_WIDTH = 12.0
FDTD_NOISE_AMP = 1e-3  # 固定种子初始微扰（证明 PRNG 确定性与梯度不受影响）
FDTD_SEED = 0

# 中心差分步长：x64 用小步长压截断误差，float32 放大避免舍入噪声
FD_STEP_X64 = 1e-4
FD_STEP_F32 = 1e-3
# 梯度对拍目标（jax.grad vs 中心有限差分），达不到如实报实际值
GRAD_REL_TOL = 1e-3
# 稳定性上限：源幅值 O(1)，max|Ez| 远超此值即判爆（CFL/更新式有误）
STABILITY_MAX_ABS = 1e3


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
    head = f"{'backend':<8} {'capability':<26} {'available':<12} evidence"
    lines = [head, "-" * len(head)]
    labels = {True: "available", False: "unavailable"}
    for row in rows:
        status = labels.get(row.get("available"), str(row.get("available")))
        lines.append(f"{row['backend']:<8} {row['capability']:<26} {status:<12} {row.get('evidence', '')}")
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


def _enable_x64(jax_module: object) -> bool:
    """尽力开启 x64（float64）；失败返回 False，不阻断探测（best-effort）。"""
    try:
        jax_module.config.update("jax_enable_x64", True)  # type: ignore[attr-defined]
        return bool(getattr(jax_module.config, "x64_enabled", False))  # type: ignore[attr-defined]
    except Exception:
        return False


def device_kinds(devices: Iterable[object] | None) -> list[str]:
    """设备类型标签集合（纯函数）：优先 device_kind，退化 platform / 类名。"""
    kinds: set[str] = set()
    for device in devices or []:
        kind = getattr(device, "device_kind", None) or getattr(device, "platform", None) or type(device).__name__
        kinds.add(str(kind))
    return sorted(kinds)


def relative_error(approx: object, reference: object) -> float | None:
    """|approx - reference| / |reference|；输入非法/非有限/参考近零返回 None。"""
    try:
        value = float(approx)  # type: ignore[arg-type]
        ref = float(reference)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(value) and math.isfinite(ref)):
        return None
    if abs(ref) < _REL_EPS:
        return None
    return abs(value - ref) / abs(ref)


def grad_verdict(rel_err: object, tol: float = GRAD_REL_TOL) -> bool | str:
    """梯度对拍判决：True=相对误差在容差内，False=超容差，unknown=数值无效。"""
    if rel_err is None:
        return UNKNOWN
    try:
        value = float(rel_err)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return UNKNOWN
    if not math.isfinite(value) or value < 0.0:
        return UNKNOWN
    return value <= tol


def stability_verdict(
    max_abs: object,
    finite: object,
    deterministic: object,
    limit: float = STABILITY_MAX_ABS,
) -> bool | str:
    """稳定性+确定性判决：三态。字段缺失/类型非法 ⇒ unknown。"""
    if max_abs is None or finite is None or deterministic is None:
        return UNKNOWN
    try:
        peak = float(max_abs)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return UNKNOWN
    if finite is not True or deterministic is not True:
        return False
    if not math.isfinite(peak):
        return False
    return peak <= limit


# ── 真机内核（依赖注入便于离线单测） ──────────────────────────────────────────


def _prng_key(jax_module: object, seed: int) -> object:
    """固定种子 PRNG key：优先 jax.random.key（typed key），退化 PRNGKey。"""
    random_mod = jax_module.random  # type: ignore[attr-defined]
    factory = getattr(random_mod, "key", None) or random_mod.PRNGKey  # type: ignore[attr-defined]
    return factory(int(seed))


def solve_fdtd_gradient(seed: int = FDTD_SEED) -> dict:
    """真机最小可微 FDTD：1D Yee 时间步进 + jax.grad 对 theta 求梯度 + 有限差分对拍。

    更新式（归一化单位，leapfrog）::

        Hy[i] += S * (Ez[i+1] - Ez[i])                     i = 0..n-2
        Ez[i] += S * (Hy[i] - Hy[i-1]) / eps_r[i]          i = 1..n-1
        Ez[src] += gaussian_pulse(t)                       # 软源
        eps_r = 1 + theta * mask                           # 介质板

    objective(theta) = sum_t Ez[probe](t)^2（穿过时间步的后处理"探头"读数）。
    """
    import jax
    import jax.numpy as jnp

    x64 = _enable_x64(jax)
    dtype = jnp.float64 if x64 else jnp.float32
    fd_step = FD_STEP_X64 if x64 else FD_STEP_F32

    n, steps = FDTD_N_CELLS, FDTD_STEPS
    src_index, probe_index = FDTD_SRC_INDEX, FDTD_PROBE_INDEX
    slab_lo, slab_hi = FDTD_SLAB

    mask = jnp.asarray([1.0 if slab_lo <= i < slab_hi else 0.0 for i in range(n)], dtype=dtype)
    pulse = jnp.exp(-(((jnp.arange(steps, dtype=dtype) - FDTD_PULSE_T0) / FDTD_PULSE_WIDTH) ** 2))
    key = _prng_key(jax, seed)
    ez_init = jnp.asarray(FDTD_NOISE_AMP, dtype=dtype) * jax.random.normal(key, (n,), dtype=dtype)

    def sim(theta: object) -> tuple[object, object]:
        eps = 1.0 + theta * mask
        ez = ez_init
        hy = jnp.zeros(n, dtype=dtype)
        acc = jnp.zeros((), dtype=dtype)
        peak = jnp.zeros((), dtype=dtype)
        for step in range(steps):
            hy = hy.at[:-1].add(FDTD_COURANT * (ez[1:] - ez[:-1]))
            ez = ez.at[1:].add(FDTD_COURANT * (hy[1:] - hy[:-1]) / eps[1:])
            ez = ez.at[src_index].add(pulse[step])
            acc = acc + ez[probe_index] ** 2
            peak = jnp.maximum(peak, jnp.max(jnp.abs(ez)))
        return acc, peak

    started = time.time()
    theta0 = jnp.asarray(FDTD_THETA0, dtype=dtype)
    objective, peak = sim(theta0)
    objective_again, _ = sim(theta0)
    grad_ad = jax.grad(lambda t: sim(t)[0])(theta0)
    fd_plus, _ = sim(theta0 + fd_step)
    fd_minus, _ = sim(theta0 - fd_step)
    grad_fd = (fd_plus - fd_minus) / (2 * fd_step)

    grad_ad_f = float(grad_ad)
    grad_fd_f = float(grad_fd)
    objective_f = float(objective)
    return {
        "n_cells": n,
        "steps": steps,
        "courant": FDTD_COURANT,
        "theta0": FDTD_THETA0,
        "seed": int(seed),
        "fd_step": fd_step,
        "x64": bool(x64),
        "dtype": str(dtype),
        "objective": objective_f,
        "max_abs_ez": float(peak),
        "finite": bool(jnp.isfinite(objective) and jnp.isfinite(peak) and jnp.isfinite(grad_ad)),
        "deterministic": bool(objective_f == float(objective_again)),
        "grad_ad": grad_ad_f,
        "grad_fd": grad_fd_f,
        "rel_error": relative_error(grad_ad_f, grad_fd_f),
        "elapsed_s": round(time.time() - started, 2),
    }


# ── 探测函数 ──────────────────────────────────────────────────────────────────


def probe_import(importer: Callable[[str], object] | None = None) -> list[dict]:
    """jax 可导入性 + 版本 + x64 开关 + Windows wheel 发行版证据。"""
    imp = importer or importlib.import_module
    try:
        jax = imp("jax")
    except Exception as exc:  # 导入失败=能力判负，如实记录不崩
        return [
            entry(
                "jax",
                "import_and_version",
                False,
                f"{type(exc).__name__}: {exc}",
                "jax 不可导入：A7 JAX CPU 通道判 blocked（原始错误见 evidence）",
            )
        ]
    version = getattr(jax, "__version__", None)
    jaxlib_version = _dist_version("jaxlib")
    x64 = _enable_x64(jax)
    dists = {name: _dist_version(name) for name in INSTALLED_DISTRIBUTIONS}
    evidence = (
        f"jax.__version__={version}; jaxlib dist={jaxlib_version}; "
        f"x64_enabled={x64}; pip 发行版={dists}"
    )
    detail = (
        "jax CPU wheel 由 pip 直接安装；可选依赖条目见 pyproject "
        "[project.optional-dependencies] jax"
    )
    if version is None or jaxlib_version is None:
        return [unknown_entry("jax", "import_and_version", evidence, detail + "（版本信息缺失，判 unknown）")]
    return [entry("jax", "import_and_version", True, evidence, detail)]


def probe_devices(jax_module: object | None) -> list[dict]:
    """可见设备枚举：CPU 存在即 A7 CPU 通道可用（GPU 为用户侧跳过项）。"""
    try:
        devices = list(jax_module.devices())  # type: ignore[attr-defined]
    except Exception as exc:  # 枚举失败=信息缺失，判 unknown 不判负
        return [
            unknown_entry(
                "jax",
                "device_topology",
                f"{type(exc).__name__}: {exc}",
                "设备枚举失败：设备面未确证，如实记 unknown",
            )
        ]
    kinds = device_kinds(devices)
    evidence = f"devices={len(devices)} kinds={kinds}"
    detail = "GPU 为用户侧跳过项；本项只确证 CPU 通道"
    if not devices:
        return [entry("jax", "device_topology", False, evidence, "无可见设备：A7 判 blocked")]
    has_cpu = any("cpu" in kind.lower() for kind in kinds)
    if not has_cpu:
        return [entry("jax", "device_topology", False, evidence, detail + "；未见 CPU 设备")]
    return [entry("jax", "device_topology", True, evidence, detail)]


def probe_fdtd(run_fn: Callable[[], dict] | None = None) -> list[dict]:
    """可微 FDTD 内核：稳定性/确定性 + jax.grad 对拍有限差分（两项记录）。"""
    run = run_fn or solve_fdtd_gradient
    try:
        info = run()
    except Exception as exc:  # 内核异常=能力判负，如实记录不崩
        raw = f"{type(exc).__name__}: {exc}"
        return [
            entry("jax", "fdtd_stability", False, raw, "内核异常：A7 判 blocked（不凑绿）"),
            entry("jax", "differentiable_fdtd_grad", False, raw, "内核异常：A7 判 blocked（不凑绿）"),
        ]
    info = info or {}

    stab = stability_verdict(info.get("max_abs_ez"), info.get("finite"), info.get("deterministic"))
    stab_evidence = (
        f"1D Yee FDTD n={info.get('n_cells')} steps={info.get('steps')} "
        f"courant={info.get('courant')} dtype={info.get('dtype')} seed={info.get('seed')}: "
        f"objective={info.get('objective')} max|Ez|={info.get('max_abs_ez')} "
        f"finite={info.get('finite')} deterministic={info.get('deterministic')} "
        f"({info.get('elapsed_s')}s)"
    )
    stab_detail = "固定种子 + 同输入两次逐位一致；max|Ez| 未爆（阈值见 meta.fdtd.stability_max_abs）"

    rel = relative_error(info.get("grad_ad"), info.get("grad_fd"))
    verdict = grad_verdict(rel)
    grad_evidence = (
        f"theta0={info.get('theta0')} eps_r=1+theta*mask: grad_ad={info.get('grad_ad')} "
        f"grad_fd(中心差分 h={info.get('fd_step')})={info.get('grad_fd')} "
        f"rel_err={rel} (tol={GRAD_REL_TOL}, x64={info.get('x64')})"
    )
    grad_detail = "jax.grad 反向模式穿过完整时间步；对拍=同一 objective 的中心有限差分"

    rows = [
        entry("jax", "fdtd_stability", stab, stab_evidence, stab_detail)
        if stab is not UNKNOWN
        else unknown_entry("jax", "fdtd_stability", stab_evidence, stab_detail + "；数值无效判 unknown"),
    ]
    if verdict is True:
        rows.append(entry("jax", "differentiable_fdtd_grad", True, grad_evidence, grad_detail))
    elif verdict is False:
        rows.append(
            entry(
                "jax",
                "differentiable_fdtd_grad",
                False,
                grad_evidence,
                grad_detail + f"；相对误差超容差 {GRAD_REL_TOL}，判负不凑绿",
            )
        )
    else:
        rows.append(
            unknown_entry("jax", "differentiable_fdtd_grad", grad_evidence, grad_detail + "；梯度数值无效判 unknown")
        )
    return rows


def _safe_import(importer: Callable[[str], object], name: str) -> object | None:
    try:
        return importer(name)
    except Exception:  # 二次导入失败只影响设备面（#105）
        return None


def probe_jax(
    importer: Callable[[str], object] | None = None,
    run_fn: Callable[[], dict] | None = None,
) -> list[dict]:
    """A7 全量探测：import/版本/x64 → 设备 → 可微 FDTD（稳定性 + 梯度对拍）。"""
    imp = importer or importlib.import_module
    rows = probe_import(imp)
    if rows[0]["available"] is not True:
        rows.append(unknown_entry("jax", "device_topology", "jax 不可导入", "跳过设备枚举"))
        rows.append(unknown_entry("jax", "fdtd_stability", "jax 不可导入", "跳过真机内核"))
        rows.append(unknown_entry("jax", "differentiable_fdtd_grad", "jax 不可导入", "跳过真机内核"))
        return rows
    rows.extend(probe_devices(_safe_import(imp, "jax")))
    rows.extend(probe_fdtd(run_fn))
    return rows


# ── 聚合 / 报告 ───────────────────────────────────────────────────────────────


def real_probe_table() -> dict[str, Callable[[], list[dict]]]:
    """真机探测表（lambda 在调用时解析全局名，便于单测 monkeypatch）。"""
    return {"jax": lambda: probe_jax()}


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
    """报告级环境事实（不 import jax，纯元数据）。"""
    return {
        "platform": sys.platform,
        "python": platform.python_version(),
        "python_executable": sys.executable,
        "distributions": {name: _dist_version(name) for name in INSTALLED_DISTRIBUTIONS},
        "fdtd": {
            "n_cells": FDTD_N_CELLS,
            "steps": FDTD_STEPS,
            "courant": FDTD_COURANT,
            "src_index": FDTD_SRC_INDEX,
            "probe_index": FDTD_PROBE_INDEX,
            "slab": list(FDTD_SLAB),
            "theta0": FDTD_THETA0,
            "seed": FDTD_SEED,
            "noise_amp": FDTD_NOISE_AMP,
            "fd_step_x64": FD_STEP_X64,
            "fd_step_f32": FD_STEP_F32,
            "grad_rel_tol": GRAD_REL_TOL,
            "stability_max_abs": STABILITY_MAX_ABS,
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
        "probe": "a7-jax-differentiable-fdtd-cpu",
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
    """核心判据是否全部 available（决定退出码；设备/稳定性缺失不算执行失败）。"""
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
    print(f"\nA7 JAX 可微 FDTD 能力矩阵 -> {out}")
    if args.skip_real:
        return 0
    if core_verdict(matrix):
        print("核心判据 PASS（import_and_version + differentiable_fdtd_grad）")
        return 0
    print("核心判据 FAIL（import 或可微梯度非 available）——如实标 partial/blocked")
    return 2


if __name__ == "__main__":
    sys.exit(main())
