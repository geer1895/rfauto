"""kicad/layout 面 s-expr 大文件手术纪律守卫（aurora_q T-Q25 席，2026-11-05）.

来源 = cad-lab CAD-Agent 交接文档 §6 第 14 坑（2026-11-04 实证）：对含铺铜
多边形的大 .kicad_pcb 用嵌套量词正则做块级替换 → 灾难性回溯挂死（脚本
hang 无结果无报错）。处方 = 大 s-expr 一律按行定位块起止后切片插入/删除，
禁跨千行正则；rfauto 现行安全范式 = ``kicad_extract._extract_stackup_block``
的括号配平线性扫描（find 起点 + 深度计数到闭合，零回溯）+ 块内切 chunk 后
小正则。

本守卫三件（AGENTS 踩坑速查同日转正条目的落地面）：

1. 静态棘轮：扫 ``adapters/kicad*.py`` + ``adapters/layout*.py`` 全部
   ``re.compile(r"...")`` 模式，禁"量化组体内再含量化原子"（灾难性回溯
   签名，如 ``(a+)+``/``([^)]*)*``）；已知良性模式进 ``_ALLOWLIST``
   （逐条带互斥分支理由），新增命中必须显式入清单（带理由）或重写——
   棘轮只收不放。近似口径：按模式源文本静态扫描，不追踪非 r 前缀/
   三引号形态（本域 12 文件现无此类；新增大正则请保持 r 前缀单行）。
2. 探测器自证：已知坏形态全捕获 + 已知安全形态零误报（防探测器本身
   失真——#331 家法：观察工具先自证）。
3. 性质钉：``_extract_stackup_block`` 在大文本（数万行铺铜多边形噪声）
   下结果与无噪声逐位一致、嵌套括号块完整截取、无 stackup/未闭合如实
   None——块提取对跨千行内容免疫。**不设计时断言**（环境类抖动见
   AGENTS「全量门失败定性三分法①」，性质钉已覆盖免疫性本体）。
"""

from __future__ import annotations

import re
from pathlib import Path

from rfauto.adapters.kicad_extract import _extract_stackup_block

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ADAPTERS_DIR = _REPO_ROOT / "src" / "rfauto" / "adapters"

#: 静态扫描面：kicad/layout 面 s-expr 大文件手术风险域（第 14 坑影响对象）。
_SCAN_GLOB_PREFIXES = ("kicad", "layout")

#: 从模块源文本抽取 ``re.compile(r"...")`` 模式字面量（近似：r 前缀单行）。
_PATTERN_RE = re.compile(r"re\.compile\(\s*r?([\"'])(.*?)\1", re.S)

#: 现扫描面模式总数下限（2026-11-05 实测 15）——棘轮只收不放：模式被删到
#: 低于此值说明扫描面结构性缩水，须人工复核后调门。
_MIN_PATTERN_FLOOR = 12

#: 已知良性白名单：命中"量化组体内含量化原子"签名但逐位分析安全，逐条带
#: 理由。新增命中必须显式入本清单（带理由）或重写模式。
_ALLOWLIST: dict[str, str] = {
    # kicad_sch_gen s-expr 分词器的引号串分支：``(?:\\.|[^"\\])*`` 二分支
    # 互斥（转义对以反斜杠起、字符类排除反斜杠），每位置唯一可行分支 =
    # 线性，无回溯放大（RE2 同款安全形态）。
    r'"(?:\\.|[^"\\])*"|[()]|[^\s()]+': (
        "引号串分支二选一互斥（转义对 vs 排除反斜杠单字符），每位置唯一"
        "可行分支=线性无回溯放大"),
}


def _strip_noise(pattern: str) -> str:
    """剥离转义与字符类，留结构性括号/量词（防字符类内 ``*`` 误报）。"""
    s = re.sub(r"\\.", " ", pattern)
    s = re.sub(r"\[[^\]]*\]", "C", s)
    return s


def _quantified_at(s: str, j: int) -> bool:
    """位置 j 是否为量词（``*``/``+``/``?``/``{m,n}``；字面 ``{`` 不算）。"""
    if j < len(s) and s[j] in "*+?":
        return True
    return j < len(s) and s[j] == "{" and re.match(
        r"\{\d+(,\d*)?\}", s[j:]) is not None


def _nested_quantifier_flags(pattern: str) -> list[str]:
    """检测"量化组体内再含量化原子"（灾难性回溯签名）。

    栈式扫描：``(`` 入栈记录组体是否已含量化原子；``)`` 出栈时若组体含
    量化原子且组本身带量词（``*``/``+``/``?``/``{m,n}``）则记命中，并
    向父组体传播（量化组对父层而言也是量化原子）。近似口径：不判分支
    交叠（``(a|aa)*`` 类）——命中者走白名单逐位定性。
    """
    s = _strip_noise(pattern)
    flags: list[str] = []
    stack: list[list] = []  # 每项 [组体是否含量化原子, 组起点]
    for i, c in enumerate(s):
        if c == "(":
            stack.append([False, i])
        elif c == ")":
            if not stack:
                continue
            body_has_quant, group_start = stack.pop()
            quantified = _quantified_at(s, i + 1)
            if quantified and body_has_quant:
                flags.append(pattern[group_start:i + 2])
            if quantified and stack:
                stack[-1][0] = True
        elif _quantified_at(s, i) and stack:
            stack[-1][0] = True
    return flags


def _iter_scan_files() -> list[Path]:
    return sorted(p for p in _ADAPTERS_DIR.iterdir()
                  if p.suffix == ".py"
                  and p.name.startswith(_SCAN_GLOB_PREFIXES))


def _scan_patterns() -> list[tuple[Path, str]]:
    found: list[tuple[Path, str]] = []
    for f in _iter_scan_files():
        text = f.read_text(encoding="utf-8")
        for m in _PATTERN_RE.finditer(text):
            found.append((f, m.group(2)))
    return found


class TestDetectorSelfCheck:
    """探测器自证（#331 家法：观察工具先自证再上岗）。"""

    def test_bad_shapes_all_flagged(self):
        bad = [
            r"([^)]*)*",      # 嵌套量词经典态（第 14 坑元凶形态）
            r"(a+)+",         # 指数回溯教科书形态
            r"(?:\w+:)*\w+",  # 常见"逐段匹配"灾难态
            r"(a|b+)+c",      # 量化交替体
            r"(x{2,})+y",     # 区间量词嵌套
        ]
        for p in bad:
            flags = _nested_quantifier_flags(p)
            assert flags, f"坏形态漏检: {p!r}"

    def test_safe_shapes_zero_false_positive(self):
        safe = [
            r'\(type\s+"([^"]+)"\)',          # layout_substrate 层类型
            r"\(thickness\s+([0-9.eE+-]+)\s*\)",  # kicad_extract 字段
            r"rect([\d.]+)x([\d.]+)",         # layout_interchange 焊盘形
            r"(ab)+c",                        # 量化组但体无量化原子
            r"a*b+c*",                        # 顶层量化无组嵌套
            r"[abc]+(def)?g",                 # 字符类量化+可选组体纯净
        ]
        for p in safe:
            flags = _nested_quantifier_flags(p)
            assert not flags, f"安全形态误报: {p!r} -> {flags}"


class TestStaticRatchet:
    """静态棘轮：kicad/layout 面禁嵌套量词正则（白名单显式豁免）。"""

    def test_scan_face_non_empty_above_floor(self):
        patterns = _scan_patterns()
        assert len(patterns) >= _MIN_PATTERN_FLOOR, (
            f"扫描面模式数 {len(patterns)} 低于棘轮下限 {_MIN_PATTERN_FLOOR}"
            f"——扫描面或模式面结构性缩水，人工复核后调门")

    def test_no_unreviewed_nested_quantifier(self):
        offenders = []
        for f, pattern in _scan_patterns():
            for flag in _nested_quantifier_flags(pattern):
                if flag not in _ALLOWLIST and pattern not in _ALLOWLIST:
                    offenders.append((f.name, pattern, flag))
        assert not offenders, (
            "kicad/layout 面新增嵌套量词正则（灾难性回溯签名，第 14 坑）——"
            "重写为按行/括号配平或逐位定性后带理由入 _ALLOWLIST："
            f"{offenders}")

    def test_allowlist_entries_still_alive(self):
        # 白名单防陈旧：条目对应模式已从代码消失则条目失效，须摘除。
        alive = {p for _, p in _scan_patterns()}
        for entry in _ALLOWLIST:
            assert entry in alive, f"白名单条目已不在扫描面（摘除）: {entry!r}"


# ---------------------------------------------------------------------------
# 性质钉：括号配平块提取对大文本免疫
# ---------------------------------------------------------------------------

def _synth_stackup_block() -> str:
    layers = [
        '    (layer "F.Cu" (type "copper") (thickness 0.035))',
        '    (layer "dielectric 1" (type "dielectric") (thickness 0.1)'
        ' (epsilon_r 4.5) (loss_tangent 0.02))',
        '    (layer "In1.Cu" (type "copper") (thickness 0.035))',
        '    (layer "dielectric 2" (type "dielectric") (thickness 0.6)'
        ' (epsilon_r 4.5) (loss_tangent 0.02))',
        '    (layer "B.Cu" (type "copper") (thickness 0.035))',
    ]
    return "(stackup\n" + "\n".join(layers) + "\n  )"


def _synth_board(stackup: str, n_zone_lines: int) -> str:
    header = '(kicad_pcb (version 20241209) (generator "rf_probe")\n'
    zones = "\n".join(
        f'    (polygon (pts (xy {i % 97} {i % 89}) (xy {i % 53} {i % 31})))'
        for i in range(n_zone_lines))
    return header + stackup + "\n  (zone\n" + zones + "\n  )\n)"


class TestBlockExtractionImmunity:
    """_extract_stackup_block 括号配平范式对跨千行内容免疫（第 14 坑性质钉）。"""

    def test_result_identical_with_large_trailing_noise(self):
        stackup = _synth_stackup_block()
        small = _extract_stackup_block(_synth_board(stackup, 0))
        big = _extract_stackup_block(_synth_board(stackup, 50_000))
        assert small is not None
        assert small == big == stackup

    def test_noise_before_stackup_does_not_disturb(self):
        stackup = _synth_stackup_block()
        noisy = "(junk (nested (deep)))\n" + _synth_board(stackup, 10_000)
        assert _extract_stackup_block(noisy) == stackup

    def test_missing_or_unclosed_stackup_returns_none(self):
        assert _extract_stackup_block(_synth_board("", 100)) is None
        unclosed = '(kicad_pcb\n  (stackup\n    (layer "F.Cu")'
        assert _extract_stackup_block(unclosed) is None

    def test_nested_parens_block_fully_captured(self):
        stackup = _synth_stackup_block()
        extracted = _extract_stackup_block(_synth_board(stackup, 5_000))
        assert extracted is not None
        assert extracted.count("(") == extracted.count(")")
        assert '(epsilon_r 4.5)' in extracted
        assert extracted.startswith("(stackup")
