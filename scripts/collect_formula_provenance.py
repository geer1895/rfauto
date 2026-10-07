"""KD-1 公式 provenance 收集器薄壳（specs 研究扩充 round16 KD-1）。

扫描/渲染/schema 单源在 src/rfauto/core/formula_provenance.py——本脚本只做
CLI 编排：读 manual_entries（人工补录区逐字保留）→ 仓级扫描 → 渲染 → 写
knowledge/formula_provenance.yaml（或 --check 只验漂移不写）。

用法（仓根执行）：
    .venv/Scripts/python.exe scripts/collect_formula_provenance.py            # 再生
    .venv/Scripts/python.exe scripts/collect_formula_provenance.py --check    # 漂移门（CI/定向门用）

退出码：--check 漂移=1（stdout 给出再生指引与漂移摘要）；其余失败=2。
幂等契约：同树二跑逐字节 diff=0（无时间戳类字段）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.core.formula_provenance import (  # noqa: E402
    load_formula_provenance,
    render_formula_provenance_yaml,
    scan_repo_formula_provenance,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="KD-1 公式 provenance 注册表收集器（knowledge/formula_provenance.yaml）",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="只校验注册表与 docstring 扫描一致（漂移=exit 1），不写文件",
    )
    args = parser.parse_args(argv)

    yaml_path = ROOT / "knowledge" / "formula_provenance.yaml"
    fresh = scan_repo_formula_provenance(ROOT)

    # manual_entries 人工补录区逐字保留（首次落盘无注册表时为空）
    manual: list[dict] = []
    if yaml_path.is_file():
        manual = load_formula_provenance(yaml_path)["manual_entries"]
    rendered = render_formula_provenance_yaml(fresh, manual)

    if args.check:
        if not yaml_path.is_file():
            print(f"[kd1] FAIL: 注册表不存在 {yaml_path}——先跑再生（无 --check）")
            return 1
        on_disk = yaml_path.read_text(encoding="utf-8").replace("\r\n", "\n")
        if on_disk == rendered.replace("\r\n", "\n"):
            n = len(fresh)
            print(f"[kd1] OK: 注册表与 docstring 扫描逐字节一致（entries={n}，manual={len(manual)}）")
            return 0
        _print_drift(on_disk, rendered)
        return 1

    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    yaml_path.write_text(rendered, encoding="utf-8", newline="\n")
    files = sorted({e["kernel_file"] for e in fresh})
    print(f"[kd1] 写入 {yaml_path}（entries={len(fresh)}，files={len(files)}，manual={len(manual)}）")
    return 0


def _print_drift(on_disk: str, rendered: str) -> None:
    disk_lines = on_disk.replace("\r\n", "\n").splitlines()
    new_lines = rendered.replace("\r\n", "\n").splitlines()
    import difflib

    diff = list(difflib.unified_diff(disk_lines, new_lines, "registry(on disk)", "scan(fresh)", lineterm=""))
    changed = [ln for ln in diff if ln.startswith(("+", "-")) and not ln.startswith(("+++", "---"))]
    print(f"[kd1] FAIL: 注册表与 docstring 扫描漂移（diff 行数={len(changed)}）——"
          f"docstring 出处改动后须再生：python scripts/collect_formula_provenance.py")
    for ln in changed[:20]:
        print(ln)
    if len(changed) > 20:
        print(f"  ...（其余 {len(changed) - 20} 行省略）")


if __name__ == "__main__":
    raise SystemExit(main())
