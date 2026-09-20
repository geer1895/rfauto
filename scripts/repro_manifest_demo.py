"""可复现性清单演示。

用法：

    .venv/Scripts/python.exe scripts/repro_manifest_demo.py runs/<run_id>
    .venv/Scripts/python.exe scripts/repro_manifest_demo.py runs/<run_id> --out repro_manifest.json
    .venv/Scripts/python.exe scripts/repro_manifest_demo.py runs/<run_id> --verify repro_manifest.json

零新依赖：只调用 rfauto.service.reproducibility_service，不依赖 Docker。
未做：Docker 镜像构建/镜像内干净 venv 重放（如实记未做）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="rfauto G7 复现清单演示")
    parser.add_argument("target", nargs="?", default=".",
                        help="run 目录或产物文件（默认当前目录）")
    parser.add_argument("--out", help="清单落盘路径（JSON）")
    parser.add_argument("--verify", help="已有清单路径：改为校验模式，报 missing/changed/extra")
    parser.add_argument("--ignore", action="append", default=[],
                        help="忽略的相对路径 glob（可重复）")
    args = parser.parse_args(argv)

    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    from rfauto.service.reproducibility_service import (
        build_reproducibility_manifest,
        read_manifest,
        verify_reproducibility_manifest,
        write_manifest,
    )

    target = Path(args.target)

    if args.verify:
        loaded = read_manifest(args.verify)
        if not loaded["ok"]:
            print(json.dumps(loaded, ensure_ascii=False), file=sys.stderr)
            return 1
        report = verify_reproducibility_manifest(loaded["manifest"], target)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if report["ok"] else 2

    manifest = build_reproducibility_manifest(target, ignore=args.ignore)
    if args.out:
        written = write_manifest(manifest, args.out)
        print(f"清单已写入 {written['path']}（{written['digest']}）")
    artifacts = manifest.get("artifacts", {})
    print(json.dumps({
        "ok": manifest["ok"],
        "lock_digest": manifest["environment"]["lock_digest"],
        "artifact_digest": artifacts.get("digest"),
        "artifact_files": artifacts.get("file_count"),
    }, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if manifest["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
