r"""UI i18n hardcode 棘轮扫描器（aurora_g W2-S1 批 4 常驻化；R1 §面2 P9-6）。

口径（R1 可行性实证的三步法，双语言原型互证）：
  ①逐 .js 文件做字符级状态机（行注释//、块注释/**、三态字面量
    '...'/"..."/`...`，含反斜杠转义）——**只扫字符串/模板字面量**，中文
    行注释/块注释天然豁免（这是本扫描器与"grep CJK"土法的本质区别，
    R1 §面2 写死；仓内中文注释惯例不被误伤）；
  ②字面量内容计 Han 字符数（\u3400-\u9fff，与 view_tools _HAS_CJK 同块
    ——全角标点（）：·—等不计，避免把标点排版当文案记账）；
  ③与基线账本 scripts/ui_i18n_baseline.json（文件→字符数）对账：
    **只减不增**——任一文件超基线=新 hardcode 回潮即红；迁移批顺笔减账
    （count<baseline 合法，--update 重生账本落盘）。

白名单（不扫描）：pages/i18n.js（词表本体）、vendor/**（第三方）、
非 .js（index.html 的壳字面为 data-i18n 兜底文本，归 test_ui_i18n 键集
互证管辖，不在本账）。

与 test_ui_i18n 互补分工：后者管"已接线页键集完整性（悬空/死键双向）"，
本扫描管"未接线面不再恶化"（硬编码 CJK 只减不增的棘轮）。已接线页的
数据面协议标识符（如 view_tools 组名表/服务端组名对齐用）属刻意保留，
随首批基线入账，消化时顺笔减。

退出码：0=对账通过；1=有回潮/有未入账新面（逐条列出）；2=static 树
不可读（环境类 SKIP 诚实降级）。
用法：
  .venv/Scripts/python.exe scripts/check_ui_i18n_coverage.py           # 对账
  .venv/Scripts/python.exe scripts/check_ui_i18n_coverage.py --update  # 重生基线
merge_preflight 挂点：经 tests/unit/test_ui_i18n.py 第 6 层钉间接常驻
（面 24"UI i18n 守卫"已收 test_ui_i18n——零 preflight 改动即入预检）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_ROOT = REPO_ROOT / "src" / "rfauto" / "ui" / "static"
BASELINE = Path(__file__).resolve().parent / "ui_i18n_baseline.json"

# 白名单（相对 STATIC_ROOT 的 posix 路径前缀/全等）
WHITELIST_FILES = {"pages/i18n.js"}
WHITELIST_PREFIXES = ("vendor/",)

_CJK = None  # 惰性编译（见 _count_han）


def _count_han(text: str) -> int:
    global _CJK
    if _CJK is None:
        import re

        _CJK = re.compile("[\u3400-\u4dbf\u4e00-\u9fff]")
    return len(_CJK.findall(text))


_REGEX_KEYWORDS = {
    "return", "typeof", "instanceof", "in", "of", "new", "delete", "void",
    "throw", "case", "do", "else", "yield", "await",
}


def _regex_position(src: str, i: int) -> bool:
    """`/` 是否处于正则字面量起始位（前导 token 启发式，ECMA-262 词法惯例）：
    前一有效字符为运算符/开括号/逗号等 → regex；为词字符时回溯整词，
    关键字（return/typeof/…）后 → regex，标识符/数字后 → 除法；`)`/`]` 后
    → 除法（仓内无 `if (x) /re/` 形态）。误判方向自愈兜底=引号串跨裸换行
    重同步（见 _scan_source）。"""
    j = i - 1
    while j >= 0 and src[j] in " \t\r\n":
        j -= 1
    if j < 0:
        return True
    c = src[j]
    if c in "(,=:[!&|?{};+-*%~^<>":
        return True
    if c.isalnum() or c in "_$":
        k = j
        while k >= 0 and (src[k].isalnum() or src[k] in "_$"):
            k -= 1
        word = src[k + 1:j + 1]
        return word in _REGEX_KEYWORDS
    return False


def _scan_source(src: str) -> int:
    r"""字符级栈式状态机：收集三态字面量内容并计 Han 数。

    栈帧语境：code / line_comment / block_comment / regex / squote / dquote /
    template。模板串遇 ${ 入栈 code 帧做插值扫描（brace 配深），嵌套模板
    （`${cols.map((c) => `<td>${x}</td>`)}` 惯例，view_data/view_tune 实证）
    逐层入栈逐层闭合——平铺单变量状态机在嵌套模板处必错配（幻影模板吞
    代码注释，首版实证 plotcard 1865 vs 真值 12）。模板插值内代码照常走
    引号/正则判别；字面量闭合即计 Han 并弹栈。

    正则字面量按 _regex_position 判别进入并整段跳过（plotcard.js
    `return /[",\\n]/.test(t)` 实证：regex 体内引号不参与串配对）。伪串
    自愈（第二道兜底）：JS 单/双引号串不允许跨裸换行——遇裸换行未闭合
    =非串语境，弹栈弃 content 重同步（行尾反斜杠续行由转义分支先行消费，
    真串不受扰；模板串合法跨行不在此列）。"""
    total = 0
    stack = [{"state": "code", "brace": 0, "buf": []}]
    in_class = False  # regex 字符类 [...] 内（`/` 不闭合）
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        top = stack[-1]
        st = top["state"]
        if st == "code":
            if c == "/" and nxt == "/":
                stack.append({"state": "line_comment", "brace": 0, "buf": []})
                i += 2
                continue
            if c == "/" and nxt == "*":
                stack.append({"state": "block_comment", "brace": 0, "buf": []})
                i += 2
                continue
            if c == "/" and _regex_position(src, i):
                stack.append({"state": "regex", "brace": 0, "buf": []})
                in_class = False
                i += 1
                continue
            if c == "'" or c == '"':
                stack.append({"state": "squote" if c == "'" else "dquote",
                              "brace": 0, "buf": []})
                i += 1
                continue
            if c == "`":
                stack.append({"state": "template", "brace": 0, "buf": []})
                i += 1
                continue
            if c == "{":
                top["brace"] += 1
                i += 1
                continue
            if c == "}":
                if top["brace"] == 0 and len(stack) > 1 and \
                        stack[-2]["state"] == "template":
                    stack.pop()  # 插值结束，回到外层模板
                else:
                    top["brace"] = max(0, top["brace"] - 1)
                i += 1
                continue
            i += 1
            continue
        if st == "line_comment":
            if c == "\n":
                stack.pop()
            i += 1
            continue
        if st == "block_comment":
            if c == "*" and nxt == "/":
                stack.pop()
                i += 2
                continue
            i += 1
            continue
        if st == "regex":
            if c == "\\" and i + 1 < n:
                i += 2
                continue
            if in_class:
                if c == "]":
                    in_class = False
                i += 1
                continue
            if c == "[":
                in_class = True
                i += 1
                continue
            if c == "/":
                stack.pop()
                i += 1
                while i < n and src[i].isalpha():
                    i += 1  # flags（g/i/m/s/u/y/d）
                continue
            i += 1
            continue
        # 三态字面量帧内部
        if c == "\\" and i + 1 < n:
            top["buf"].append(src[i:i + 2])
            i += 2
            continue
        if c == "\n" and st in ("squote", "dquote"):
            # 伪串自愈：单/双引号串不跨裸换行（模板串合法跨行，不在此列）
            stack.pop()
            i += 1
            continue
        if (st == "squote" and c == "'") or (st == "dquote" and c == '"'):
            total += _count_han("".join(top["buf"]))
            stack.pop()
            i += 1
            continue
        if st == "template" and c == "`":
            total += _count_han("".join(top["buf"]))
            stack.pop()
            i += 1
            continue
        if st == "template" and c == "$" and nxt == "{":
            stack.append({"state": "code", "brace": 0, "buf": []})
            i += 2
            continue
        top["buf"].append(c)
        i += 1
    # 未闭合字面量（语法坏串）按已收集内容记账——node --check 门另有语法兜底
    for frame in stack:
        if frame["state"] in ("squote", "dquote", "template"):
            total += _count_han("".join(frame["buf"]))
    return total


def _iter_targets() -> list[Path]:
    out = []
    for p in sorted(STATIC_ROOT.rglob("*.js")):
        rel = p.relative_to(STATIC_ROOT).as_posix()
        if rel in WHITELIST_FILES:
            continue
        if any(rel.startswith(pre) for pre in WHITELIST_PREFIXES):
            continue
        out.append(p)
    return out


def _counts() -> dict[str, int]:
    return {
        p.relative_to(STATIC_ROOT).as_posix(): _scan_source(
            p.read_text(encoding="utf-8"))
        for p in _iter_targets()
    }


def main(argv: list[str] | None = None) -> int:
    update = "--update" in (argv if argv is not None else sys.argv[1:])
    if not STATIC_ROOT.is_dir():
        print(f"[SKIP] static 树不可读: {STATIC_ROOT}")
        return 2
    counts = _counts()
    if update:
        old = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else {}
        BASELINE.write_text(
            json.dumps(counts, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
            encoding="utf-8")
        grew = {k: (old.get(k, 0), v) for k, v in counts.items() if v > old.get(k, 0)}
        dropped = {k: v for k, v in old.items() if k not in counts}
        print(f"[UPDATE] 基线重生 {BASELINE.name}：{len(counts)} 文件 / "
              f"总 Han {sum(counts.values())} 字符（上账 {len(old)} 文件）")
        for k, v in sorted(counts.items()):
            if v or k in old:
                mark = "=" if v == old.get(k, 0) else ("<" if v < old.get(k, 0) else ">")
                print(f"  {mark} {k}: {old.get(k, 0)} -> {v}")
        if dropped:
            print(f"  - 移除失活条目: {sorted(dropped)}")
        if grew:
            print(f"[WARN] 本次 update 含增长条目 {len(grew)}——确认属刻意扩面"
                  "（新 hardcode 应直接进词表而非涨账）")
        return 0
    base = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else {}
    failures: list[str] = []
    for rel, cnt in sorted(counts.items()):
        if rel not in base:
            if cnt > 0:
                failures.append(f"{rel}: {cnt} Han 字面量未入基线账本"
                                "（新文件/新面——进词表或带理由 --update 入账）")
            continue
        if cnt > base[rel]:
            failures.append(f"{rel}: {cnt} > 基线 {base[rel]}（+{cnt - base[rel]}）"
                            "——新 hardcode 回潮，文案进 pages/i18n.js 词表")
    total_now = sum(counts.values())
    total_base = sum(v for k, v in base.items() if k in counts)
    if failures:
        print(f"[FAIL] UI i18n hardcode 棘轮（{len(failures)} 条；"
              f"在账总量 {total_now} vs 基线 {total_base}）")
        for f in failures:
            print("  " + f)
        print("处置：新文案一律进 pages/i18n.js（zh/en 双语+视图引用同笔）；"
              "迁移批减账/白名单变更走 --update 重生基线并在席位报告登记。")
        return 1
    print(f"[PASS] UI i18n hardcode 棘轮（{len(counts)} 文件对账零回潮；"
          f"在账 {sum(1 for v in counts.values() if v)} 文件 / "
          f"总 Han {total_now} 字符，只减不增）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
