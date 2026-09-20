#!/usr/bin/env python3
"""UTF-8 无 BOM 编码检查（防编码漂移）。

扫描仓库跟踪的文本源文件，拒绝两类漂移：
- UTF-8 BOM（多编辑器环境下 Windows 工具链最爱悄悄加的东西）
- 非 UTF-8 可解码（mojibake / GBK 误存的硬信号）

跟随 git ls-files，与 CI/本地口径一致；跳过二进制后缀与 vendor 目录。
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


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, check=True
    )
    return [f for f in out.stdout.splitlines() if f.strip()]


def has_bom(path: Path) -> bool:
    with open(path, "rb") as f:
        return f.read(3) == b"\xef\xbb\xbf"


def main() -> int:
    bad: list[str] = []
    checked = 0
    for name in tracked_files():
        p = Path(name)
        if p.suffix.lower() in SKIP_SUFFIXES:
            continue
        if any(d in p.parts for d in SKIP_DIRS):
            continue
        if not p.exists():
            continue
        checked += 1
        raw = p.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            bad.append(f"{name}: UTF-8 BOM detected")
            continue
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError as e:
            bad.append(f"{name}: not valid UTF-8 ({e})")
    if bad:
        print(f"ENCODING CHECK: {len(bad)} violations")
        for b in bad:
            print(f"  {b}")
        return 1
    print(f"Encoding check: clean ({checked} files).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
