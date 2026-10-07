"""许可合规门（r4 P-3，2026-09-27）——pip-licenses 包装，release §5 三层审查的证据面自动化。

用法：.venv/Scripts/python.exe scripts/license_gate.py [--json <out>]
- 枚举当前环境全部已装发行版许可，凡许可族不在 ALLOWED 内→exit 1 并列出；
- 弱 copyleft（MPL/LGPL）与 UNKNOWN 一律不自动放行（待逐案裁决后进 ALLOWED）；
- 与  铁律 8 人工三层审查叠加不替代（自动扫描 clean 不豁免人工三问）。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

# 允许许可族（大小写不敏感子串匹配）。
ALLOWED: tuple[str, ...] = (
    "MIT",
    "Apache",
    "BSD",
    "Python-2.0",
    "PSF",
    "Python Software Foundation",  # matplotlib/defusedxml/distlib/pywin32 全称写法
    "Unlicense",
    "Unlicensed",
    "ISC",
    "ML",  # Historical Permission Notice（matplotlib 族）
    "Mozilla",  # MPL-2.0 文件级弱 copyleft（certifi/pathspec）——2026-09-27 裁决入
    "MPL",  # MPL-2.0 缩写形态（hypothesis）——同上裁决
    "Boost",  # BSL-1.0 宽松（gdstk）
)

#: 逐案豁免裁决表（{包名: 注记}）——许可不在 ALLOWED 但经人工裁决放行；
#: 每条必须带裁决理由，无条目的非 ALLOWED 包=gate 红（#122 不静默放行）。
EXEMPT: dict[str, str] = {
    "openEMS": "GPL-3.0 引擎——adapter 独立进程调用，不链接不分发（豁免 2026-09-27）",
    "CSXCAD": "LGPL-3.0——openEMS 引擎组件，同上独立进程口径",
    "gmsh": "GPL-2+ 网格引擎——独立进程调用（Elmer 链）",
    "netgen-mesher": "LGPL——ngsolve 求解器族引擎面，独立进程",
    "netgen_occt": "LGPL——同上",
    "ngsolve": "LGPL——可选求解器后端，独立进程",
    "moocore": "LGPL-2.1+——pymoo（multiobj extra）传递依赖；库 import 语义保留声明",
    "tidy3d": "LGPL-2.1+——fdtdx（diff-fdtd extra）传递依赖",
    "paramiko": "LGPL-2.1+——remote extra（remote-v0 SSH 通道，懒加载可选依赖，"
                "moocore 同款库 import 语义保留声明）；随 [remote] extra 分发前"
                "须过 release §5 人工审查（2026-09-28 批 B1 P-3 接线时逐案补裁）",
    "fdtdx": "元数据 UNKNOWN 但上游 MIT（round5 许可表[20] arXiv:2603.24027+GitHub 实证）——豁免+建议上游补元数据",
    "pymupdf": "AGPL-3.0——仅内部 scripts（lit_mine_pipeline PDF 提取）无分发面不触发网络服务条款；分发前必须替换或合规（2026-09-27 裁决）",
}

#: 已知弱 copyleft/特殊族：出现即点名（裁决记录用，不自动放行）。
NOTABLE: tuple[str, ...] = ("MPL", "LGPL", "CDDL", "EPL", "AGPL", "GPL")


def normalize_name(name: str) -> str:
    """PEP503 归一（大小写折叠+-_. 折叠）——豁免表键匹配用。"""
    import re as _re

    return _re.sub(r"[-_.]+", "-", name).lower()


#: 全文 License 字段（无自标识）的签名匹配——MIT 正文不含 "MIT" 字样，
#: 旧子串匹配靠 "limitation" 撞中纯属偶然（审查轨 C P2-9 修复实证）。
_TEXT_SIGNATURES: tuple[tuple[str, str], ...] = (
    ("MIT", "permission is hereby granted, free of charge"),
    ("BSD", "redistribution and use in source and binary forms"),
)


def _family_match(token: str, lic: str) -> bool:
    """许可族 token 匹配：纯字母数字 token 用词边界，其余子串（大小写不敏感）。

    2026-09-28 修复（批 B1 P-3 单测钉出）：原实现 alnum token 词边界
    未命中后落入子串兜底（``token.lower() in lic.lower()``），词边界
    形同虚设（"ML" 撞 "html5lib" 实测 True）——P2-9 修复残留。修复后
    alnum token 只走词边界+全文签名两路，非 alnum（含空格/点的族名）
    保持子串。
    """
    import re as _re

    lic_lower = lic.lower()
    if token.isalnum():
        if _re.search(
                rf"(?<![A-Za-z0-9]){token}(?![A-Za-z0-9])", lic,
                _re.IGNORECASE) is not None:
            return True
        # 全文 License 字段签名兜底（MIT 正文不含 "MIT" 字样等）
        return any(sig in lic_lower
                   for t, sig in _TEXT_SIGNATURES if t == token)
    return token.lower() in lic_lower


def collect_rows() -> list[dict[str, str]]:
    """pip-licenses 5.x API：parser→table→行字典（Name/Version/License）。"""
    import piplicenses

    parser = piplicenses.create_parser()
    args = parser.parse_args(["--format=json", "--from=mixed"])
    table = piplicenses.create_licenses_table(
        args, output_fields=["Name", "Version", "License"])
    return [dict(zip(["Name", "Version", "License"], row, strict=True)) for row in table.rows]


def main() -> int:
    parser = argparse.ArgumentParser(description="许可合规门（pip-licenses 包装）")
    parser.add_argument("--json", default=None, help="逐包许可清单 JSON 落盘路径")
    args = parser.parse_args()

    rows = collect_rows()
    if args.json:
        Path(args.json).write_text(
            json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")

    violations: list[str] = []
    for row in rows:
        lic = str(row.get("License", ""))
        name = str(row.get("Name", "?"))
        # 审查轨 C P2-9：豁免匹配按 PEP503 归一名（大小写/-_. 折叠）；
        # 家族 token 用词边界匹配防 "ML" 撞 "html" 类子串
        name_key = normalize_name(name)
        if lic in ("", "UNKNOWN"):
            if name_key in {normalize_name(k) for k in EXEMPT}:
                continue  # 豁免条目已含裁决注记
            violations.append(f"{name}: UNKNOWN/缺失——逐案核对后入 ALLOWED 或 EXEMPT")
            continue
        if not any(_family_match(a, lic) for a in ALLOWED):
            if name_key in {normalize_name(k) for k in EXEMPT}:
                continue  # 逐案豁免（注记见 EXEMPT 表）
            tag = " [弱copyleft待裁决]" if any(n.lower() in lic.lower() for n in NOTABLE) else ""
            violations.append(f"{name}: {lic}{tag}")

    print(f"[license-gate] 已扫描 {len(rows)} 个发行版；violation={len(violations)}")
    for v in violations:
        print(f"  - {v}")
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
