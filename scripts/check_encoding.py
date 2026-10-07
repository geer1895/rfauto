#!/usr/bin/env python3
"""UTF-8 无 BOM 编码检查（扩展方案 风险 12：编码漂移）。

扫描仓库跟踪的文本源文件，拒绝两类漂移：
- UTF-8 BOM（多编辑器环境下 Windows 工具链最爱悄悄加的东西）
- 非 UTF-8 可解码（mojibake / GBK 误存的硬信号）

跟随 git ls-files，与 CI/本地口径一致；跳过二进制后缀与 vendor 目录。

E-09（W1-F 2026-10-05）：逐文件判定抽成纯函数 :func:`check_bytes`
（name+raw 字节进、violation 串出或 None）——main 的扫描循环与输出
格式逐字节不变，纯函数面由此可单测（tests/unit/test_w1_f_check_encoding.py）。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# 二进制/外部 vendor 资产不进编码检查
SKIP_SUFFIXES = {
    ".png", ".jpg", ".gif", ".ico", ".pdf", ".zip", ".whl", ".exe",
    ".dll", ".so", ".pyd", ".step", ".stp", ".stl", ".s2p", ".s1p",
    ".s3p", ".s4p", ".touchstone", ".snP", ".db", ".sqlite", ".woff", ".ttf",
}
SKIP_DIRS = {"pyaedt-main", "pyaedt_reference", ".venv", "__pycache__"}

_BOM = b"\xef\xbb\xbf"


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, check=True
    )
    return [f for f in out.stdout.splitlines() if f.strip()]


def has_bom(path: Path) -> bool:
    with open(path, "rb") as f:
        return f.read(3) == _BOM


def check_bytes(name: str, raw: bytes) -> str | None:
    """单文件编码判定（纯函数）：violation 描述串或 None（干净）。

    两类违例与 main 历史输出逐字节同形：
    - ``"<name>: UTF-8 BOM detected"``
    - ``"<name>: not valid UTF-8 (<UnicodeDecodeError 原文>)"``
    """
    if raw.startswith(_BOM):
        return f"{name}: UTF-8 BOM detected"
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError as e:
        return f"{name}: not valid UTF-8 ({e})"
    return None


def is_skipped(name: str) -> bool:
    """路径是否在扫描跳过集（二进制后缀/vendor 目录；纯函数）。"""
    p = Path(name)
    return p.suffix.lower() in SKIP_SUFFIXES or any(
        d in p.parts for d in SKIP_DIRS)


def main() -> int:
    bad: list[str] = []
    checked = 0
    for name in tracked_files():
        if is_skipped(name):
            continue
        p = Path(name)
        if not p.exists():
            continue
        checked += 1
        violation = check_bytes(name, p.read_bytes())
        if violation is not None:
            bad.append(violation)
    if bad:
        print(f"ENCODING CHECK: {len(bad)} violations")
        for b in bad:
            print(f"  {b}")
        return 1
    print(f"Encoding check: clean ({checked} files).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
