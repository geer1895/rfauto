#!/usr/bin/env python3
"""docs 再生面漂移日检驱动（aurora72 A4-D，2026-10-11）。

对两个再生面各跑一次脚本官方 --check 语义并聚合退出码——供每日 schedule
巡检/本地手动使用。merge_preflight 已含同一批面（走 pytest 测试文件
test_docs_site/test_kernel_cards），本脚本是同一批面的"无 pytest 依赖独立
形态"，二者判据同源、不重复挂接：

  1. docs_site    —— scripts/build_docs_pages.py --check
                     （重生成到临时目录 vs 已提交 docs_site/ 逐字节比对）
  2. kernel_cards —— scripts/build_kernel_cards.py --check（同语义）

退出码语义（全量门失败定性三分法：先定性再动手）：
  0 = 两面全绿（与已提交产物逐字节一致）；
  1 = 漂移红（某面 rc=1 且输出含漂移标记——修复=仓根重跑对应生成器并
      同笔提交产物，勿手改产物）；
  2 = 基础设施类（脚本缺席/超时/进程崩溃 rc<0/退出码无漂移标记——
      跑不起来 ≠ 漂移，如实分开：不冒充红也不放行绿）。
  漂移与基础设施并存时取 2（基础设施掩盖漂移判定，先修环境）。

用法（venv 内，任意 cwd）：
    python scripts/check_docs_drift.py
    python scripts/check_docs_drift.py --only docs_site
    python scripts/check_docs_drift.py --timeout 300
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable

# 漂移标记：两个生成器判红输出共有的字面（build_kernel_cards "漂移："、
# build_docs_pages "漂移："）——rc=1 但无标记=进程崩溃 traceback，归基础设施。
DRIFT_MARKER = "漂移"

RC_GREEN = 0
RC_DRIFT = 1
RC_INFRA = 2

# (面名, 脚本相对 REPO_ROOT 路径, 额外参数)
FACES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("docs_site", "scripts/build_docs_pages.py", ("--check",)),
    ("kernel_cards", "scripts/build_kernel_cards.py", ("--check",)),
)


def classify(returncode: int, output: str) -> tuple[str, int]:
    """(rc, 输出) → (定性标签, 贡献退出码)。纯函数，单测直钉。"""
    if returncode == 0:
        return "PASS", RC_GREEN
    if returncode == 1 and DRIFT_MARKER in output:
        return "DRIFT", RC_DRIFT
    return "INFRA", RC_INFRA


def aggregate(versions: list[tuple[str, int]]) -> int:
    """各面 (标签, 贡献码) 聚合：INFRA 优先于 DRIFT（掩盖判定先修环境）。

    空清单（--only 无命中）按基础设施类红处理——静默空跑=假绿，禁止。
    """
    if not versions:
        return RC_INFRA
    codes = {code for _, code in versions}
    if RC_INFRA in codes:
        return RC_INFRA
    if RC_DRIFT in codes:
        return RC_DRIFT
    return RC_GREEN


def run_face(script: str, extra: tuple[str, ...], timeout_s: int,
             ) -> tuple[int, str]:
    """跑单面脚本，返回 (rc, 合并输出尾段)。基础设施异常归一为 rc=-1。"""
    try:
        r = subprocess.run(
            [PY, script, *extra], cwd=str(REPO_ROOT),
            capture_output=True, text=True, timeout=timeout_s,
        )
    except FileNotFoundError:
        return -1, f"脚本缺席：{script}"
    except subprocess.TimeoutExpired:
        return -1, f"超时（>{timeout_s}s）"
    except OSError as exc:  # 权限/内存等发射失败——环境类如实上报
        return -1, f"进程发射失败：{exc}"
    output = (r.stdout + r.stderr).strip()
    lines = output.splitlines() if output else []
    return r.returncode, lines[-1] if lines else "(无输出)"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="docs 再生面（docs_site/kernel_cards）漂移日检驱动")
    parser.add_argument("--only", type=str, default=None,
                        help="逗号分隔只跑指定面（如 docs_site,kernel_cards；"
                             "缺省全部；未知面名=报错）")
    parser.add_argument("--timeout", type=int, default=600,
                        help="单面 subprocess 超时秒数（缺省 600）")
    args = parser.parse_args(argv)

    faces = list(FACES)
    if args.only is not None:
        wanted = {s.strip() for s in args.only.split(",") if s.strip()}
        known = {name for name, _, _ in FACES}
        unknown = sorted(wanted - known)
        if unknown:
            parser.error(f"未知面名 {unknown}（可选：{sorted(known)}）")
        faces = [f for f in FACES if f[0] in wanted]

    print("== check_docs_drift（docs 再生面漂移日检；"
          "红=仓根重跑生成器并同笔提交）==", flush=True)
    versions: list[tuple[str, int]] = []
    for name, script, extra in faces:
        t0 = time.monotonic()
        rc, detail = run_face(script, extra, args.timeout)
        label, code = classify(rc, detail)
        wall = time.monotonic() - t0
        print(f"[{label}] {name} ({wall:.1f}s) {detail}", flush=True)
        versions.append((label, code))

    final = aggregate(versions)
    labels = "/".join(label for label, _ in versions) or "空"
    print(f"== check_docs_drift {'GREEN' if final == RC_GREEN else 'RED'} "
          f"(rc={final})：{labels} ==")
    return final


if __name__ == "__main__":
    sys.exit(main())
