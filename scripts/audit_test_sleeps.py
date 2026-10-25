#!/usr/bin/env python3
"""tests 面 time.sleep(N>10) AST 常驻守卫（门口径 v2 ④ followUp 清偿，2026-10-11 W2-D）。

开发注记（八百八十三）门口径 v2 采纳批遗留 followUp："--durations top-20 分层
+ sleep(N>10) AST 扫描常驻"——本脚本补齐后半（前半=wf_gate_full_v2.py
durations 分层报告，同批清偿）。

扫描形态（AST 结构判定，非正则——字符串模板里的 sleep 不误报）：

- ``time.sleep(N)`` / ``from time import sleep`` 直名 ``sleep(N)`` /
  ``asyncio.sleep(N)`` 等任意 ``*.sleep(N)`` 属性形态，首个实参为**数值
  字面量**且 ``N > 阈值（缺省 10，秒）`` → 违例；
- 非字面量实参（变量/表达式）静态不可判 → 不报（零误报红线；现树唯一
  长睡 tests/unit/test_w2_a_dag.py 的 sleep(600) 在子进程 helper 字符串
  模板内，AST Call 扫描天然不命中——实测零违例出生绿）。

常驻接线：scripts/merge_preflight.py 第 11 面（席位返回前必跑）；全量门
不直跑本脚本（守卫在预检面拦截，门只兜底——门口径 v2 分工）。

用法（仓根执行）::

    .venv/Scripts/python.exe scripts/audit_test_sleeps.py [--threshold 10]
        [--tests-dir tests] [--allow tests/unit/test_x.py ...] [--json]

退出码：0=清洁；1=有违例（逐条列出）；2=扫描目录不存在。
豁免：``--allow <路径或文件名>``（可多次，按路径尾段/文件名匹配）——
合法长睡（如 opt-in 真机档）须带理由登记在豁免使用处注释里，不留裸豁免。
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: 违例条目形态（--json / 报告行同源）
Violations = list[dict[str, object]]


def _sleep_seconds(call: ast.Call) -> float | None:
    """Call 节点 → sleep 秒数（首个实参为数值字面量时）；否则 None。"""
    if not call.args:
        return None
    arg = call.args[0]
    if isinstance(arg, ast.Constant) and isinstance(arg.value, (int, float)):
        return float(arg.value)
    return None


def _is_sleep_call(node: ast.AST) -> bool:
    """``*.sleep(...)`` 属性形态或 ``sleep(...)`` 直名形态（from-import）。"""
    if not isinstance(node, ast.Call):
        return False
    fn = node.func
    if isinstance(fn, ast.Attribute) and fn.attr == "sleep":
        return True
    return isinstance(fn, ast.Name) and fn.id == "sleep"


def scan_tree(tests_dir: str | Path, threshold: float,
              allow: tuple[str, ...] = ()) -> Violations:
    """递归 AST 扫描目录内全部 ``*.py`` → 违例条目列表（路径排序确定性）。

    条目：{file(仓根相对 posix), line, seconds, source(调用行首 80 字符)}。
    解析失败文件按违例条目登记（fail-closed，不静默跳过——坏文件比漏报
    安全，#316 方向）。
    """
    tests_dir = Path(tests_dir).resolve()  # #140：入参先收敛，rglob 产出方为绝对
    out: Violations = []
    for path in sorted(tests_dir.rglob("*.py")):
        try:
            rel = path.relative_to(REPO_ROOT).as_posix()
        except ValueError:  # 扫描根在仓外（单测 tmp 树）→ 相对扫描根标号
            rel = path.relative_to(tests_dir).as_posix()
        if _allowed(rel, allow):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError) as exc:
            out.append({"file": rel, "line": 0, "seconds": None,
                        "source": f"AST 解析失败（fail-closed 计违例）: {exc}"})
            continue
        for node in ast.walk(tree):
            if not _is_sleep_call(node):
                continue
            seconds = _sleep_seconds(node)
            if seconds is None or seconds <= threshold:
                continue
            src_line = ""
            with contextlib.suppress(OSError):
                src_line = path.read_text(encoding="utf-8").splitlines()[
                    node.lineno - 1].strip()[:80]
            out.append({"file": rel, "line": node.lineno,
                        "seconds": seconds, "source": src_line})
    return out


def _allowed(rel: str, allow: tuple[str, ...]) -> bool:
    """豁免匹配：路径尾段或文件名精确匹配（``tests/x.py`` 或 ``x.py``）。"""
    for a in allow:
        a_norm = a.replace("\\", "/").strip("/")
        if rel == a_norm or rel.endswith("/" + a_norm) or \
                Path(rel).name == Path(a_norm).name:
            return True
    return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--threshold", type=float, default=10.0,
                    help="sleep 秒数阈值（严格大于判违例；缺省 10=登记口径）")
    ap.add_argument("--tests-dir", default="tests",
                    help="扫描根（仓根相对；缺省 tests 全树）")
    ap.add_argument("--allow", action="append", default=[],
                    help="豁免文件（路径尾段或文件名，可多次；须带理由注记）")
    ap.add_argument("--json", action="store_true", help="JSON 输出")
    args = ap.parse_args(argv)

    tests_dir = Path(args.tests_dir)
    if not tests_dir.is_dir():
        print(f"FAIL 扫描目录不存在: {tests_dir}")
        return 2
    violations = scan_tree(tests_dir, args.threshold,
                           tuple(args.allow))
    if args.json:
        print(json.dumps({
            "ok": not violations,
            "threshold_s": args.threshold,
            "tests_dir": str(tests_dir),
            "allow": list(args.allow),
            "n_violations": len(violations),
            "violations": violations,
        }, ensure_ascii=False, indent=2))
    elif violations:
        print(f"sleep-AST 守卫：{len(violations)} 处 sleep(N>{args.threshold:g}) 违例"
              "（常驻慢测试；门口径 v2 ④）")
        for v in violations:
            print(f"  {v['file']}:{v['line']} sleep({v['seconds']:g}s)"
                  f"  {v['source']}")
        print("处置：改事件驱动/短睡轮询（#157 副作用落盘口径）；确需长睡走"
              " --allow 豁免并注记理由")
    else:
        if not args.json:
            print(f"sleep-AST 守卫：清洁（tests 树零 sleep(N>{args.threshold:g})）")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
