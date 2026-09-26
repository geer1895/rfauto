"""DP-6 守卫比对器：串行 vs 并行两份 junitxml 逐位比对。

规格：docs/plan_deepdive_specs_20260924.md §DP-6——测试 id 集合+失败/跳过
集合逐位比对，diff 为空才算守卫过；任一轮不一致 → 冻结并行、`-n0`
串行复现按 flake 流程取证。

用法：
    .venv/Scripts/python.exe scripts/gate_diff_results.py SERIAL.xml PARALLEL.xml

exit code：0=两份完全一致（守卫过）；1=存在差异；2=解析/用法错误。
比对维度：collected id 集合、failed 集合、skipped 集合、逐 id 状态变化。
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def load_cases(xml_path: Path) -> dict[str, str]:
    """解析 junitxml → {test_id: status}；status ∈ passed/failed/skipped。

    test_id = classname::name（pytest junitxml 口径，含参数化后缀，
    足以逐位区分收集项）。
    """
    try:
        tree = ET.parse(xml_path)
    except ET.ParseError as exc:
        raise SystemExit(f"2: 无法解析 {xml_path}: {exc}") from exc
    root = tree.getroot()
    suites = [root] if root.tag == "testsuite" else root.findall(".//testsuite")
    cases: dict[str, str] = {}
    for suite in suites:
        for tc in suite.iter("testcase"):
            cid = f"{tc.get('classname', '')}::{tc.get('name', '')}"
            if tc.find("failure") is not None or tc.find("error") is not None:
                status = "failed"
            elif tc.find("skipped") is not None:
                status = "skipped"
            else:
                status = "passed"
            cases[cid] = status
    return cases


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2:
        print(__doc__)
        return 2
    serial_xml, parallel_xml = (Path(a) for a in argv)
    for p in (serial_xml, parallel_xml):
        if not p.is_file():
            print(f"2: 文件不存在: {p}")
            return 2

    serial = load_cases(serial_xml)
    parallel = load_cases(parallel_xml)

    serial_ids = set(serial)
    parallel_ids = set(parallel)
    serial_failed = {k for k, v in serial.items() if v == "failed"}
    parallel_failed = {k for k, v in parallel.items() if v == "failed"}
    serial_skipped = {k for k, v in serial.items() if v == "skipped"}
    parallel_skipped = {k for k, v in parallel.items() if v == "skipped"}
    status_changed = sorted(
        k for k in serial_ids & parallel_ids if serial[k] != parallel[k])

    diffs: list[str] = []
    for title, items in (
        ("ids_only_in_serial", sorted(serial_ids - parallel_ids)),
        ("ids_only_in_parallel", sorted(parallel_ids - serial_ids)),
        ("failed_only_in_serial", sorted(serial_failed - parallel_failed)),
        ("failed_only_in_parallel", sorted(parallel_failed - serial_failed)),
        ("skipped_only_in_serial", sorted(serial_skipped - parallel_skipped)),
        ("skipped_only_in_parallel", sorted(parallel_skipped - serial_skipped)),
    ):
        if items:
            diffs.append(f"{title} ({len(items)}):")
            diffs.extend(f"  {i}" for i in items)
    if status_changed:
        diffs.append(f"status_changed ({len(status_changed)}):")
        diffs.extend(f"  {k}: {serial[k]} -> {parallel[k]}"
                     for k in status_changed)

    print(f"serial:   collected={len(serial_ids)} "
          f"failed={len(serial_failed)} skipped={len(serial_skipped)}")
    print(f"parallel: collected={len(parallel_ids)} "
          f"failed={len(parallel_failed)} skipped={len(parallel_skipped)}")
    if diffs:
        print("\n".join(diffs))
        print("DIFF: DIFFERENCES FOUND")
        return 1
    print("DIFF: EMPTY (identical id/failed/skipped sets)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
