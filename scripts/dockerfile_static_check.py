"""Dockerfile 静态校验。

如实口径：本机无 docker 守护（`docker` 命令不存在），**未真构建**；
本脚本只做静态校验，不冒充构建 PASS：

1. 指令白名单与顺序：FROM 必须是第一条逻辑指令；指令名须为 Dockerfile
   合法指令；逻辑指令（含 ``\\`` 续行拼接）非空；
2. JSON 数组形式指令（CMD/ENTRYPOINT）可被 json.loads 解析且元素全为字符串；
3. COPY 源路径在仓根真实存在（--chown 等 flag 剥离后判定）；
4. 基镜像口径：FROM 为 python:3.12-slim，且 3.12 落在 pyproject
   requires-python 区间内（tomllib 实测，不靠目测）。

退出码 0=静态校验全过；非 0=有 NG 项（不凑绿）。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import tomllib

REPO = Path(__file__).resolve().parents[1]
DOCKERFILE = REPO / "Dockerfile"

VALID_INSTRUCTIONS = {
    "FROM", "RUN", "CMD", "LABEL", "MAINTAINER", "EXPOSE", "ENV", "ADD",
    "COPY", "ENTRYPOINT", "VOLUME", "USER", "WORKDIR", "ARG", "ONBUILD",
    "STOPSIGNAL", "HEALTHCHECK", "SHELL",
}


def logical_lines(text: str) -> list[tuple[int, str]]:
    """物理行 → 逻辑指令行（跳过空行/整行注释，拼接 ``\\`` 续行）。

    限制：续行中间夹整行注释的冷僻写法不支持（本 Dockerfile 不用）。
    """
    out: list[tuple[int, str]] = []
    buf = ""
    start = 0
    for lineno, raw in enumerate(text.splitlines(), 1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not buf:
            start = lineno
        buf = f"{buf} {stripped}" if buf else stripped
        if buf.endswith("\\"):
            buf = buf[:-1].rstrip()
            continue
        out.append((start, buf))
        buf = ""
    if buf:
        out.append((start, buf + "  [警告：末尾续行未闭合]"))
    return out


def main() -> int:
    text = DOCKERFILE.read_text(encoding="utf-8")
    checks: list[tuple[str, bool, str]] = []
    lines = logical_lines(text)
    checks.append(("逻辑指令非空", bool(lines), f"{len(lines)} 条逻辑指令"))

    # 1. 指令白名单 + FROM 首位
    instructions: list[tuple[int, str, str]] = []
    for lineno, line in lines:
        m = re.match(r"^(\S+)\s*(.*)$", line)
        word = m.group(1).upper() if m else ""
        instructions.append((lineno, word, m.group(2) if m else ""))
    bad_words = [
        f"L{ln}:{w}" for ln, w, _ in instructions if w not in VALID_INSTRUCTIONS
    ]
    checks.append((
        "指令均为合法 Dockerfile 指令", not bad_words,
        "全部合法" if not bad_words else f"非法：{bad_words}"))
    first = instructions[0][1] if instructions else ""
    checks.append(("FROM 是第一条逻辑指令", first == "FROM", f"首条指令={first or '（空）'}"))

    # 2. CMD/ENTRYPOINT JSON 数组形式可解析
    for lineno, word, rest in instructions:
        if word in ("CMD", "ENTRYPOINT") and rest.lstrip().startswith("["):
            try:
                arr = json.loads(rest.strip())
                ok = isinstance(arr, list) and all(isinstance(x, str) for x in arr)
                detail = f"L{lineno} {word}={arr}"
            except json.JSONDecodeError as exc:
                ok, detail = False, f"L{lineno} {word} JSON 解析失败：{exc}"
            checks.append((f"JSON 数组指令可解析（{word} L{lineno}）", ok, detail))

    # 3. COPY 源存在性（flag 剥离；最后一个 token 是目标，不判存在性）
    for lineno, word, rest in instructions:
        if word not in ("COPY", "ADD"):
            continue
        tokens = [t for t in rest.split() if not t.startswith("--")]
        sources = tokens[:-1] if len(tokens) >= 2 else []
        missing = [s for s in sources if not (REPO / s).exists()]
        checks.append((
            f"COPY 源存在（L{lineno}: {' '.join(sources)}）", not missing,
            "全部存在" if not missing else f"仓根缺失：{missing}"))

    # 4. 基镜像 vs requires-python（pyproject 实测）
    from_line = next((rest for _, w, rest in instructions if w == "FROM"), "")
    base_tag = from_line.split()[-1] if from_line else ""
    py_match = re.search(r"python:(\d+)\.(\d+)", base_tag)
    requires = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"]["requires-python"]
    if py_match:
        minor = int(py_match.group(2))
        # requires-python = ">=3.10,<3.13"：抽上界/下界数字实测（不手抄口径）
        lo = re.search(r">=3\.(\d+)", requires)
        hi = re.search(r"<3\.(\d+)", requires)
        ok = (lo is not None and hi is not None
              and int(lo.group(1)) <= minor < int(hi.group(1)))
        checks.append((
            f"基镜像 {base_tag} 与 requires-python={requires} 相容", ok,
            f"镜像 Python 3.{minor} ∈ [3.{lo.group(1)}, 3.{hi.group(1)})" if ok
            else f"3.{minor} 越界"))
    else:
        checks.append(("基镜像为 python:x.y 口径", False, f"FROM={base_tag!r}"))

    all_ok = all(ok for _, ok, _ in checks)
    print("== G7 Dockerfile 静态校验（未真构建：本机无 docker 守护，如实口径） ==")
    for name, ok, detail in checks:
        print(f"  [{'ok' if ok else 'NG'}] {name}: {detail}")
    print("结论：" + ("静态校验全过（构建验证仍欠：需有 docker 守护的机器真跑 "
                    "docker build + docker run 冒烟）" if all_ok else "存在 NG——按明细修复"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
