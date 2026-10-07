"""性能基准三热点（F-G 兼差件，研究扩充 round4 F-G 4）。

三个仓内已知热点函数的本机基线（固定输入合成数据，确定性、零网络）：

1. ``calculators_microstrip_synthesis``——core/calculators.py 高频键
   （微带综合 = brentq 求逆 + 自洽回代，配方渲染/优化内环反复调用）；
2. ``pce_fit_sobol``——core/pce.py 变换（Ishigami 合成函数、degree=4、
   n_samples=150、seed=42，代理预测面）；
3. ``metric_transform_loo_loglik``——core/metric_transform.py 逐域
   LOO-LML 选择器内核（n=48 曲线点，域选择/校准判读调用）。

口径（任务书铁律）：
- **pytest-benchmark 不在装（venv 实测 2026-09-27：pip list 无）**——
  按任务书降级为**手计时口径**（time.perf_counter，不装新依赖），
  JSON 里 ``basis: "manual_perf_counter"`` 如实登记；
- **不进 tests/unit 门**（性能基准不进全量门—— 纪律），本脚本
  只提供 ``--run`` 手动入口；不带 --run 时仅打印基准计划并退出；
- 输出 JSON schema 稳定（SCHEMA_VERSION="1.0"，键集固定），落
  runs/perf_hotspots_bench/<时间戳>.json；
- 热点函数全部惰性导入（本脚本 --help 不触发仓内重模块导入）。

用法：
    python scripts/perf_hotspots_bench.py --run [--repeat 10] [--warmup 2]
        [--json-dir runs/perf_hotspots_bench]

退出码：0=正常（含未带 --run 的计划打印）；2=基准执行异常。
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0"
GENERATOR = "perf_hotspots_bench"
BASIS = "manual_perf_counter"  # pytest-benchmark 不在装（venv 实测），手计时如实登记

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_JSON_DIR = REPO_ROOT / "runs" / "perf_hotspots_bench"


# ─── 三热点基准函数（固定输入合成数据，确定性） ──────────────────────────────


def _bench_calculators_microstrip_synthesis() -> None:
    """热点 1：微带综合（brentq 求逆 + 回代），高频键。"""
    from rfauto.core.calculators import microstrip_synthesis

    for freq_ghz in (2.0, 5.0, 10.0, 18.0):
        microstrip_synthesis(z0_ohm=50.0, freq_ghz=freq_ghz, epsilon_r=4.4, h_mm=1.0)


def _bench_pce_fit_sobol() -> None:
    """热点 2：PCE 拟合 + Sobol 直读（Ishigami 合成函数，seed 钉死）。"""
    import numpy as np

    from rfauto.core.pce import pce_sobol

    specs = {
        "x1": {"low": -3.141592653589793, "high": 3.141592653589793},
        "x2": {"low": -3.141592653589793, "high": 3.141592653589793},
        "x3": {"low": -3.141592653589793, "high": 3.141592653589793},
    }

    def ishigami(params: dict[str, float]) -> float:
        x1, x2, x3 = params["x1"], params["x2"], params["x3"]
        return (
            float(np.sin(x1))
            + 7.0 * float(np.sin(x2)) ** 2
            + 0.1 * x3**4 * float(np.sin(x1))
        )

    pce_sobol(specs, ishigami, degree=4, n_samples=150, seed=42)


def _bench_metric_transform_loo_loglik() -> None:
    """热点 3：逐折 LOO 高斯 logpdf（n=48 曲线点，域选择内核）。"""
    import numpy as np

    from rfauto.core.metric_transform import loo_loglik

    x1 = np.linspace(-1.0, 1.0, 48)
    x2 = np.linspace(0.2, 1.4, 48)
    x = np.column_stack([x1, x2])
    y = 2.0 * np.sin(3.0 * x1) + 0.5 * x2 + 0.1 * x1 * x2
    loo_loglik(x, y, random_state=0)


def build_benchmarks() -> list[dict[str, Any]]:
    """基准计划（名称/模块/函数标签 + 可调用；惰性导入在可调用内部）。"""
    return [
        {
            "name": "calculators_microstrip_synthesis",
            "module": "rfauto.core.calculators",
            "func": "microstrip_synthesis",
            "callable": _bench_calculators_microstrip_synthesis,
        },
        {
            "name": "pce_fit_sobol",
            "module": "rfauto.core.pce",
            "func": "pce_sobol",
            "callable": _bench_pce_fit_sobol,
        },
        {
            "name": "metric_transform_loo_loglik",
            "module": "rfauto.core.metric_transform",
            "func": "loo_loglik",
            "callable": _bench_metric_transform_loo_loglik,
        },
    ]


# ─── 手计时内核 ──────────────────────────────────────────────────────────────


def bench_one(spec: dict[str, Any], *, repeat: int, warmup: int) -> dict[str, float | str | int]:
    """单热点计时：warmup 次预热后 repeat 次独立计时，出 min/mean/max/std。"""
    fn: Callable[[], None] = spec["callable"]
    for _ in range(warmup):
        fn()
    samples = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - t0)
    return {
        "name": spec["name"],
        "module": spec["module"],
        "func": spec["func"],
        "repeat": repeat,
        "warmup": warmup,
        "total_s": sum(samples),
        "min_s": min(samples),
        "mean_s": statistics.fmean(samples),
        "max_s": max(samples),
        "std_s": statistics.stdev(samples) if repeat > 1 else 0.0,
        "units": "s_per_iteration",
        "basis": BASIS,
    }


def host_info() -> dict[str, str]:
    import platform

    try:
        import numpy as np

        np_version = np.__version__
    except Exception:  # pragma: no cover - numpy 缺失时如实登记
        np_version = "unavailable"
    return {
        "python": sys.version.split()[0],
        "numpy": np_version,
        "platform": platform.platform(),
    }


def run_benchmarks(*, repeat: int, warmup: int, json_dir: Path) -> Path:
    results = [bench_one(spec, repeat=repeat, warmup=warmup) for spec in build_benchmarks()]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generator": GENERATOR,
        "basis": BASIS,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "host": host_info(),
        "benchmarks": results,
        "notes": [
            "pytest-benchmark 不在装（venv 实测），手计时口径（time.perf_counter）",
            "固定输入合成数据；机器噪声/BLAS 线程数会影响绝对值，趋势看 min_s",
            "本脚本不进 tests/unit 门（性能基准不进全量门），仅 --run 手动入口",
        ],
    }
    json_dir.mkdir(parents=True, exist_ok=True)
    out_path = json_dir / f"perf_hotspots_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )

    print(f"perf hotspots baseline -> {out_path}")
    header = f"{'benchmark':<36}{'min_s':>12}{'mean_s':>12}{'max_s':>12}{'repeat':>8}"
    print(header)
    for row in results:
        print(
            f"{row['name']:<36}{row['min_s']:>12.6f}{row['mean_s']:>12.6f}"
            f"{row['max_s']:>12.6f}{row['repeat']:>8d}"
        )
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--run",
        action="store_true",
        help="实际执行基准（缺省只打印计划；性能基准不进任何自动门）",
    )
    parser.add_argument("--repeat", type=int, default=10, help="每热点计时次数（缺省 10）")
    parser.add_argument("--warmup", type=int, default=2, help="每热点预热次数（缺省 2）")
    parser.add_argument(
        "--json-dir",
        type=str,
        default=str(DEFAULT_JSON_DIR),
        help="JSON 输出目录（缺省 runs/perf_hotspots_bench）",
    )
    args = parser.parse_args(argv)

    plan = build_benchmarks()
    if not args.run:
        print("基准计划（加 --run 执行）：")
        for spec in plan:
            print(f"  - {spec['name']} ({spec['module']}.{spec['func']})")
        print(f"JSON 目标目录: {args.json_dir}；basis={BASIS}")
        return 0
    try:
        run_benchmarks(
            repeat=max(1, args.repeat),
            warmup=max(0, args.warmup),
            json_dir=Path(args.json_dir),
        )
    except Exception as exc:  # 基准失败显式退出码，不静默
        print(f"benchmark failed: {exc!r}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
