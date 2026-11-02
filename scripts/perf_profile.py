"""代理面性能画像一键驱动（aurora_p G3 席；回归检测器，不是门）。

薄壳（规则 4）：调 service/perf_profile_service.run_profile——
5 键缩小画像档（fit/predict 墙钟+RMSE 质量单源）→ 快照
``runs/perf_profile/profile_NNNN.json`` + diff 报告 ``*_diff.md`` 落盘，
与上一份画像 diff（RMSE 漂移 >25% / 墙钟比 >2× 红项如实列出）。

用法::

    .venv/Scripts/python.exe scripts/perf_profile.py              # 全套件
    .venv/Scripts/python.exe scripts/perf_profile.py --keys poly_ridge,nn
    .venv/Scripts/python.exe scripts/perf_profile.py --json       # 信封直出

零 CLI 数字链影响（计数面并发保护：G1/G2 在飞，CLI 接线留主代理合流笔——
scripts 直跑形态，bench_surrogates 同款纪律）。
"""

from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

#: 画像产物白名单（runs/ 湖内本席唯一写入点）。
DEFAULT_OUT = _REPO / "runs" / "perf_profile"


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="代理面性能画像（缩小档一键跑+快照+diff 回归检测；不是门）")
    parser.add_argument(
        "--out", default=str(DEFAULT_OUT),
        help=f"产物目录（缺省 {DEFAULT_OUT}；白名单唯一落点）")
    parser.add_argument(
        "--keys", default=None,
        help="只跑逗号分隔的画像键（缺省全 5 键套件）")
    parser.add_argument("--json", action="store_true", help="信封 JSON 直出")
    args = parser.parse_args(argv)

    from rfauto.service.perf_profile_service import run_profile

    # --keys 缺席 → None（全套件）；给了但解析为空集 → []（service 显式
    # 报错信封——空选不静默吞成全套件，#117 falsy 惯语反面教材）
    keys = (None if args.keys is None
            else [s.strip() for s in args.keys.split(",") if s.strip()])
    result = run_profile(args.out, keys=keys)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1
    if not result.get("ok"):
        for err in result.get("errors") or []:
            print(f"ERROR: {err}", file=sys.stderr)
        return 1
    print(f"PROFILE_DONE {result['profile_id']} keys={result['n_keys']} "
          f"ok={result['n_ok']} error={result['n_error']} "
          f"red={result['n_red']} wall_s={result['wall_s']:.1f} "
          f"budget_ok={result['budget_ok']} "
          f"first_run={result['first_run']}")
    for item in result.get("red_items") or []:
        for r in item["red"]:
            print(f"RED {item['key']}: {r}")
    print(f"OUT {result['profile_path']}")
    print(f"OUT {result['diff_path']}")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        with contextlib.suppress(Exception):
            sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
