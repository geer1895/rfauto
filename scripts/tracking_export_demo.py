"""实验追踪互操作演示。

用法：

    .venv/Scripts/python.exe scripts/tracking_export_demo.py [run_id] --out runs/tracking

零新依赖：只写 MLflow 兼容目录 + W&B JSONL + JSON manifest，不 import
mlflow/wandb。数值全部来自既有 trials 文件。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rfauto.service.tracking_export import export_run_tracking


def _pick_run(runs_root: Path) -> str | None:
    if not runs_root.is_dir():
        return None
    for candidate in sorted(runs_root.iterdir()):
        if (candidate.is_dir() and (candidate / "meta.json").is_file()
                and (candidate / "trials").is_dir()):
            return candidate.name
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="rfauto G10 MLflow/W&B 单向外导演示")
    parser.add_argument("run_id", nargs="?", help="runs/<run_id>；缺省取第一个含 trials 的 run")
    parser.add_argument("--runs-root", default="runs")
    parser.add_argument("--out", default="runs/tracking")
    args = parser.parse_args(argv)

    runs_root = Path(args.runs_root)
    run_id = args.run_id or _pick_run(runs_root)
    if not run_id:
        print("no run with meta.json + trials/ found", file=sys.stderr)
        return 1
    result = export_run_tracking(run_id, runs_root=runs_root, out_dir=args.out)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
