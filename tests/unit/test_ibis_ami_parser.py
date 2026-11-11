"""IBIS-AMI（.ami）解析内核+服务+CLI 薄壳单测（aurora_q Q-X86 席位）。

覆盖面（任务书 ≥55 条）：

- 词法：``|`` 注释（行中任何位置/至 EOF）、引号串内容原样（含竖线）、
  未闭合引号 fail-soft 警告至 EOF、atom 括号终结、行号跨行推进、CRLF、
  空串；词法扫描=定点 ``match(text, i)`` 形态（Q-X80 教训——恒前进恒
  终止，结构钉）；
- 森林：括号嵌套栈（节名=首个裸 atom 子项、字符串不充当节名）、空节
  警告丢弃、多余右括号警告、顶层裸 token/裸字符串警告、EOF 括号失衡
  自内向外重建嵌套（fail-soft 如实收编）；
- RESERVED：全标准键值断言、大小写不敏感键、多 token 值如实列表、缺
  值 None+警告、重复键后列覆盖+警告、未识别保留键照常登记（开放集）、
  重复 RESERVED 节合并、含嵌套子节警告；
- Model_Specific 五键逐参：describe 内容、type 归一闭集（非法→warning
  +raw 保留）、default raw+typed 分派（float/boolean/integer、非法
  字面/不可转→warning+None）、缺 default 构造 warning、Description/
  In_Bounds 别名同收、in-bounds (a:b) 开闭区间结构化（``[``/``(`` 定
  开闭/无括号=闭/形态不识/端点非数值→warning+None+raw 保留/下界>上界
  警告保留）、usage 多值取首、未识别子键/重复子键/重复参数/裸值/无五键
  子节/记录行号；
- 版本档位：已知 3.2 零版本警告、未知档位 warning+保留、顶层
  ami_version 兜底（RESERVED 优先+重复警告）；
- DLL/SoC 引用：DLL_file/SoC_file 登记、大小写不敏感键、重复覆盖、缺
  值、未识别顶层节警告（零静默丢弃）；
- 查询三函数：ami_param_lookup（model 优先/RESERVED 回落/大小写不敏感
  /miss None/source 标注/空 doc）、ami_required_check（complete/missing
  canonical/present）、ami_defaults_table（typed 平表/缺 default 记
  None 键）；
- 截断 fail-soft：括号失衡重建、未闭合引号收编、空文件/仅注释/纯空白
  → AmiParseError（ValueError 子类）；
- 服务三函数信封契约（ok/error 两态、errors 恒 list[str]、不可读/空
  →error、Latin-1 兜底、report 行视图、detail 未命中带可用清单）；
- CLI（**ibis_ami_app 直连+局部父 Typer 自测**——共享 app 接线由主代
  合流统一，本席禁改 cli/main.py）：parse/report --json 全结构+human
  紧凑面+失败信封同构（exit 1）+缺 --file usage 错（exit 2）+--help
  真构建（#305）+help 字符卫生（裸 [ /% 零违例）+域叶形状钉+源码字面
  钉（两叶各带 --json）+**cli.main 零导入钉**（合流契约）。

主夹具预声明账（逐项断言）：RESERVED 5 标准键（AMI_Version=3.2/
Ignore_IL=False/Init_Returns_Impulse=True/GetWave_Exists=True/
Use_Init_Output=False）；DLL_file+SoC_file 2 引用；参数 4（gain=in-bounds
[-10:0]+default -2.0+usage Info；pole=Description/In_Bounds 别名+
default 2.0e9；boost=boolean True；steps=Integer 缺 default→唯一 1 条
warning）；missing_reserved 空；stats 五计数=5/4/2/0/1。

单测零网络零真机；文件面一律 tmp_path（#144 run 湖零写入）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import typer
from typer.testing import CliRunner

from rfauto.cli.domains.ibis_ami import ibis_ami_app
from rfauto.core.ibis_ami_parser import (
    AMI_VERSIONS,
    DLL_SOC_KEYS,
    PARAM_TYPES,
    REQUIRED_RESERVED_KEYS,
    AmiParseError,
    _parse_forest,
    _Sect,
    _tokenize,
    ami_defaults_table,
    ami_param_lookup,
    ami_required_check,
    parse_ami,
)
from rfauto.service.ibis_ami_service import (
    ami_param_detail,
    ibis_ami_report,
    parse_ibis_ami_file,
)

# ── 主夹具（任务书口径：RESERVED 全标准键+版本 3.2+DLL/SoC 引用+
#    Model_Specific 4 参数含 in-bounds/别名/缺 default 构造 warning）───
SAMPLE_AMI = """\
| demo AMI: aurora_q Q-X86 fixture
( DLL_file "ctle_eq.dll" )
( SoC_file "soc_clock.dll" )
(Reserved
    (AMI_Version 3.2)
    (Ignore_IL False)
    (Init_Returns_Impulse True)
    (GetWave_Exists True)
    (Use_Init_Output False)
)
(Model_Specific
    (eq_ctle_gain
        (describe "CTLE low-frequency gain (dB)")
        (type Float)
        (default -2.0)
        (parse_inbounds [-10:0])
        (usage Info)
    )
    (eq_ctle_pole
        (Description "CTLE pole frequency (Hz)")
        (Type Float)
        (Default 2.0e9)
        (In_Bounds [0:20e9])
    )
    (eq_ctle_boost
        (describe "Boost enable")
        (type Boolean)
        (default True)
    )
    (eq_ctle_steps
        (describe "Number of CTLE steps")
        (type Integer)
        (parse_inbounds [0:16])
    )
)
"""

# 缺失必需键场景：仅 AMI_Version → 其余 4 键 missing 如实清单（不硬拒）
MINI_MISSING_AMI = """\
| missing required keys scenario
(Reserved
    (ami_version 3.2)
)
"""

PARSE_KEYS = {
    "ok", "path", "ami_version", "reserved", "missing_reserved",
    "model_specific", "dll_refs", "stats", "warnings",
}
REPORT_KEYS = {
    "ok", "path", "ami_version", "stats", "reserved_rows", "model_rows",
    "dll_refs", "missing_reserved", "warnings",
}

runner = CliRunner()

def _mini(body: str) -> dict[str, Any]:
    """全 RESERVED 壳+Model_Specific 正文 → 解析 doc（内联用例拼装器）。"""
    return parse_ami(
        "(Reserved (AMI_Version 3.2))\n(Model_Specific\n"
        f"{body}\n)\n")

def _forest(text: str) -> tuple[list[_Sect], list[str]]:
    """内联森林拼装器（词法+森林两步合成）。"""
    toks, warns = _tokenize(text)
    return _parse_forest(toks, warns), warns

@pytest.fixture(scope="module")
def doc() -> dict[str, Any]:
    return parse_ami(SAMPLE_AMI)

@pytest.fixture(scope="module")
def stats(doc: dict[str, Any]) -> dict[str, Any]:
    return doc["stats"]

@pytest.fixture()
def ami_file(tmp_path: Path) -> Path:
    f = tmp_path / "sample.ami"
    f.write_text(SAMPLE_AMI, encoding="utf-8")
    return f

@pytest.fixture()
def mini_file(tmp_path: Path) -> Path:
    f = tmp_path / "mini.ami"
    f.write_text(MINI_MISSING_AMI, encoding="utf-8")
    return f

@pytest.fixture(scope="module")
def local_app() -> typer.Typer:
    """局部父 Typer（共享 app 接线待主代合流；本席自测不经 cli/main）。"""
    parent = typer.Typer()
    parent.add_typer(ibis_ami_app, name="ibis-ami")
    return parent

# ── 词法（注释/引号串/守卫/行号）──────────────────────────────────────

class TestLexer:
    def test_comment_stripped_mid_atom(self) -> None:
        toks, warns = _tokenize("abc|comment")
        assert [v for _k, v, _l in toks] == ["abc"]
        assert warns == []

    def test_comment_mid_line(self) -> None:
        toks, warns = _tokenize("a | the rest\nb")
        assert [v for _k, v, _l in toks] == ["a", "b"]
        assert warns == []

    def test_comment_till_eof_no_newline(self) -> None:
        toks, warns = _tokenize("a | till end")
        assert [v for _k, v, _l in toks] == ["a"]
        assert warns == []

    def test_quoted_string_content(self) -> None:
        toks, warns = _tokenize('(a "b c" )')
        kinds = [k for k, _v, _l in toks]
        vals = [v for _k, v, _l in toks]
        assert kinds == ["open", "atom", "str", "close"]
        assert vals == ["(", "a", "b c", ")"]
        assert warns == []

    def test_pipe_inside_string_kept(self) -> None:
        toks, warns = _tokenize('"a|b"')
        assert [(k, v) for k, v, _l in toks] == [("str", "a|b")]
        assert warns == []

    def test_empty_string(self) -> None:
        toks, warns = _tokenize('""')
        assert [(k, v) for k, v, _l in toks] == [("str", "")]
        assert warns == []

    def test_unclosed_string_fail_soft(self) -> None:
        toks, warns = _tokenize('"abc (def')
        assert [(k, v) for k, v, _l in toks] == [("str", "abc (def")]
        assert len(warns) == 1
        assert "未闭合" in warns[0]

    def test_atom_split_at_paren(self) -> None:
        toks, _w = _tokenize("(ab)")
        assert [(k, v) for k, v, _l in toks] == [
            ("open", "("), ("atom", "ab"), ("close", ")")]

    def test_line_numbers_multiline(self) -> None:
        toks, _w = _tokenize("(a\n  b\n c)")
        lines = [ln for _k, _v, ln in toks]
        assert lines == [1, 1, 2, 3, 3]

    def test_crlf_tolerated(self) -> None:
        toks, warns = _tokenize("a\r\nb")
        assert [v for _k, v, _l in toks] == ["a", "b"]
        assert [ln for _k, _v, ln in toks] == [1, 2]
        assert warns == []

# ── 森林（嵌套栈/空节/失衡重建/裸 token）──────────────────────────────

class TestForest:
    def test_nested_sections(self) -> None:
        forest, warns = _forest("(A (B 1) 2)")
        assert warns == []
        assert len(forest) == 1
        top = forest[0]
        assert top.name == "A"
        child = top.items[0]
        assert isinstance(child, _Sect) and child.name == "B"
        assert child.items == ["1"]
        assert top.items[1] == "2"

    def test_name_is_first_atom_only(self) -> None:
        # 节名=首个裸 atom 子项；字符串叶不充当节名
        forest, warns = _forest('(A "s" x)')
        assert warns == []
        assert forest[0].name == "A"
        assert forest[0].items == ["s", "x"]

    def test_empty_section_dropped_with_warning(self) -> None:
        forest, warns = _forest("(A) () (B)")
        assert [s.name for s in forest] == ["A", "B"]
        assert len(warns) == 1
        assert "空节" in warns[0]

    def test_extra_close_warning(self) -> None:
        forest, warns = _forest("(A))")
        assert len(forest) == 1
        assert len(warns) == 1
        assert "多余的 ')'" in warns[0]

    def test_unbalanced_eof_rebuilds_nesting(self) -> None:
        # 自内向外弹栈重建：B 归回未闭合的 A（fail-soft 保真）
        forest, warns = _forest("(A (B 1)")
        assert len(warns) == 1
        assert "括号失衡" in warns[0]
        top = forest[0]
        assert top.name == "A"
        assert isinstance(top.items[0], _Sect)
        assert top.items[0].name == "B"

    def test_top_level_bare_token_warning(self) -> None:
        forest, warns = _forest("junk (A)")
        assert len(forest) == 1
        assert len(warns) == 1
        assert "顶层裸 token" in warns[0]

    def test_top_level_bare_string_warning(self) -> None:
        forest, warns = _forest('"junk" (A)')
        assert len(forest) == 1
        assert any("顶层裸字符串" in w for w in warns)

# ── RESERVED（键闭集/缺失清单/值形态/重复）────────────────────────────

class TestReserved:
    def test_five_standard_keys_exact(self, doc: dict[str, Any]) -> None:
        assert doc["reserved"] == {
            "AMI_Version": "3.2",
            "Ignore_IL": "False",
            "Init_Returns_Impulse": "True",
            "GetWave_Exists": "True",
            "Use_Init_Output": "False",
        }

    def test_required_keys_constant(self) -> None:
        assert REQUIRED_RESERVED_KEYS == (
            "AMI_Version", "Ignore_IL", "Init_Returns_Impulse",
            "GetWave_Exists", "Use_Init_Output")

    def test_case_insensitive_key(self) -> None:
        out = parse_ami("(Reserved (ami_version 3.2))")
        assert out["reserved"] == {"ami_version": "3.2"}
        assert out["ami_version"] == "3.2"
        # 缺失清单记 canonical 名（大小写不敏感比对）
        assert out["missing_reserved"] == [
            "Ignore_IL", "Init_Returns_Impulse",
            "GetWave_Exists", "Use_Init_Output"]

    def test_multi_token_value_list(self) -> None:
        out = parse_ami("(Reserved (AMI_Version 3.2) (Tx_Eq 1 2 3))")
        assert out["reserved"]["Tx_Eq"] == ["1", "2", "3"]

    def test_missing_value_warning(self) -> None:
        out = parse_ami("(Reserved (AMI_Version 3.2) (Ignore_IL))")
        assert out["reserved"]["Ignore_IL"] is None
        assert any("缺值" in w for w in out["warnings"])

    def test_duplicate_key_latter_wins(self) -> None:
        out = parse_ami(
            "(Reserved (AMI_Version 3.2) (Ignore_IL True) (Ignore_IL False))")
        assert out["reserved"]["Ignore_IL"] == "False"
        assert any("重复" in w and "覆盖" in w for w in out["warnings"])
        assert len(out["reserved"]) == 2

    def test_duplicate_key_case_insensitive(self) -> None:
        out = parse_ami(
            "(Reserved (AMI_Version 3.2) (GetWave_Exists True)"
            " (getwave_exists False))")
        assert out["reserved"] == {
            "AMI_Version": "3.2", "getwave_exists": "False"}
        assert any("重复" in w for w in out["warnings"])

    def test_unknown_reserved_key_kept_open_set(self) -> None:
        out = parse_ami(
            "(Reserved (AMI_Version 3.2) (Tx_Dq_PassThru_Exists True))")
        assert out["reserved"]["Tx_Dq_PassThru_Exists"] == "True"
        # 保留键开放集：未识别键零额外警告
        assert out["warnings"] == []

    def test_duplicate_reserved_sections_merged(self) -> None:
        out = parse_ami(
            "(Reserved (AMI_Version 3.2))\n(Reserved (Ignore_IL False))")
        assert out["reserved"]["AMI_Version"] == "3.2"
        assert out["reserved"]["Ignore_IL"] == "False"
        assert any("重复 RESERVED" in w for w in out["warnings"])

    def test_nested_child_in_reserved_entry_warned(self) -> None:
        # 嵌套子节非标量值：警告+记 None（诚实降级，不猜节名当值）
        out = parse_ami("(Reserved (AMI_Version 3.2) (Tx_Eq (1)))")
        assert out["reserved"]["Tx_Eq"] is None
        assert any("嵌套" in w for w in out["warnings"])

# ── Model_Specific 五键逐参 ────────────────────────────────────────────

class TestModelSpecific:
    def test_four_param_names_in_order(
            self, doc: dict[str, Any]) -> None:
        assert list(doc["model_specific"]) == [
            "eq_ctle_gain", "eq_ctle_pole", "eq_ctle_boost", "eq_ctle_steps"]

    def test_describe_content_unquoted(self, doc: dict[str, Any]) -> None:
        assert doc["model_specific"]["eq_ctle_gain"]["describe"] == \
            "CTLE low-frequency gain (dB)"

    def test_types_normalized_lower(self, doc: dict[str, Any]) -> None:
        types = {n: r["type"] for n, r in doc["model_specific"].items()}
        assert types == {
            "eq_ctle_gain": "float", "eq_ctle_pole": "float",
            "eq_ctle_boost": "boolean", "eq_ctle_steps": "integer"}

    def test_param_types_closed_set(self) -> None:
        assert PARAM_TYPES == ("float", "boolean", "integer")

    def test_description_alias(self, doc: dict[str, Any]) -> None:
        # (Description ...) 别名同收 → describe
        assert doc["model_specific"]["eq_ctle_pole"]["describe"] == \
            "CTLE pole frequency (Hz)"

    def test_in_bounds_alias(self, doc: dict[str, Any]) -> None:
        # (In_Bounds ...) 别名同收 → bounds_raw/bounds
        rec = doc["model_specific"]["eq_ctle_pole"]
        assert rec["bounds_raw"] == "[0:20e9]"
        assert rec["bounds"] == {
            "lo": 0.0, "hi": 20e9, "lo_closed": True, "hi_closed": True}

    def test_type_illegal_warning_raw_kept(self) -> None:
        out = _mini("(p1 (type Float32) (default 1.0))")
        rec = out["model_specific"]["p1"]
        assert rec["type"] == "Float32"  # raw 保留
        assert rec["default_typed"] is None  # type 非法→不派发
        assert rec["default_raw"] == "1.0"
        assert any("不在闭集" in w for w in out["warnings"])

    def test_missing_default_warning(self, doc: dict[str, Any]) -> None:
        rec = doc["model_specific"]["eq_ctle_steps"]
        assert rec["default_raw"] is None
        assert rec["default_typed"] is None
        assert doc["warnings"] == [
            "第 30 行：参数 eq_ctle_steps 缺 default 子节——如实登记"]

    def test_default_float_typed(self, doc: dict[str, Any]) -> None:
        assert doc["model_specific"]["eq_ctle_gain"]["default_typed"] == -2.0
        assert doc["model_specific"]["eq_ctle_pole"]["default_typed"] == 2.0e9

    def test_default_boolean_typed(self, doc: dict[str, Any]) -> None:
        assert doc["model_specific"]["eq_ctle_boost"]["default_typed"] is True

    def test_default_boolean_false(self) -> None:
        out = _mini("(pb (type Boolean) (default False))")
        assert out["model_specific"]["pb"]["default_typed"] is False

    def test_default_boolean_illegal_literal(self) -> None:
        out = _mini("(px (type Boolean) (default yes))")
        assert out["model_specific"]["px"]["default_typed"] is None
        assert any("非 boolean 字面" in w for w in out["warnings"])

    def test_default_integer_typed(self) -> None:
        out = _mini("(pn (type Integer) (default 16))")
        assert out["model_specific"]["pn"]["default_typed"] == 16

    def test_default_integer_float_like_fails(self) -> None:
        out = _mini("(pn (type Integer) (default 2.5))")
        assert out["model_specific"]["pn"]["default_typed"] is None
        assert any("不可转 integer" in w for w in out["warnings"])

    def test_default_float_unconvertible(self) -> None:
        out = _mini("(pf (type Float) (default abc))")
        rec = out["model_specific"]["pf"]
        assert rec["default_raw"] == "abc"
        assert rec["default_typed"] is None
        assert any("不可转 float" in w for w in out["warnings"])

    def test_default_multi_leaf_joined(self) -> None:
        out = _mini("(pj (type Float) (default 1.0 V))")
        rec = out["model_specific"]["pj"]
        assert rec["default_raw"] == "1.0 V"
        assert rec["default_typed"] is None  # join 后不可转

    def test_bounds_closed_bracketed(self, doc: dict[str, Any]) -> None:
        b = doc["model_specific"]["eq_ctle_gain"]["bounds"]
        assert b == {"lo": -10.0, "hi": 0.0,
                     "lo_closed": True, "hi_closed": True}

    def test_bounds_bare_both_closed(self) -> None:
        out = _mini("(pb (type Float) (default 1.0) (parse_inbounds 0:2))")
        b = out["model_specific"]["pb"]["bounds"]
        assert b == {"lo": 0.0, "hi": 2.0,
                     "lo_closed": True, "hi_closed": True}

    def test_bounds_open_interval_quoted(self) -> None:
        # 开区间经引号串表达（圆括号是节定界符——raw 字符串形态）
        out = _mini('(po (type Float) (default 0.5) '
                    '(parse_inbounds "(0:1)"))')
        b = out["model_specific"]["po"]["bounds"]
        assert b == {"lo": 0.0, "hi": 1.0,
                     "lo_closed": False, "hi_closed": False}

    def test_bounds_half_open_quoted(self) -> None:
        out = _mini('(ph (type Float) (default 0.5) '
                    '(parse_inbounds "[0:1)"))')
        b = out["model_specific"]["ph"]["bounds"]
        assert b == {"lo": 0.0, "hi": 1.0,
                     "lo_closed": True, "hi_closed": False}

    def test_bounds_unparseable_shape(self) -> None:
        out = _mini("(pu (type Float) (default 1.0) (parse_inbounds abc))")
        rec = out["model_specific"]["pu"]
        assert rec["bounds_raw"] == "abc"
        assert rec["bounds"] is None
        assert any("形态不识" in w for w in out["warnings"])

    def test_bounds_non_numeric_endpoint(self) -> None:
        out = _mini("(pv (type Float) (default 1.0) (parse_inbounds [a:1]))")
        rec = out["model_specific"]["pv"]
        assert rec["bounds_raw"] == "[a:1]"
        assert rec["bounds"] is None
        assert any("端点非数值" in w for w in out["warnings"])

    def test_bounds_lo_gt_hi_warned_kept(self) -> None:
        out = _mini("(pw (type Float) (default 1.0) (parse_inbounds [5:1]))")
        b = out["model_specific"]["pw"]["bounds"]
        assert b == {"lo": 5.0, "hi": 1.0,
                     "lo_closed": True, "hi_closed": True}
        assert any("下界" in w and "上界" in w for w in out["warnings"])

    def test_usage_captured(self, doc: dict[str, Any]) -> None:
        assert doc["model_specific"]["eq_ctle_gain"]["usage"] == "Info"

    def test_usage_missing_none(self, doc: dict[str, Any]) -> None:
        assert doc["model_specific"]["eq_ctle_pole"]["usage"] is None

    def test_usage_multi_leaf_takes_first(self) -> None:
        out = _mini("(p1 (type Float) (default 1.0) (usage Info In))")
        assert out["model_specific"]["p1"]["usage"] == "Info"
        assert any("多值" in w for w in out["warnings"])

    def test_unknown_subkey_warned(self) -> None:
        out = _mini("(p1 (type Float) (default 1.0) (Range 0 1))")
        assert any("未识别子键" in w for w in out["warnings"])
        assert out["model_specific"]["p1"]["type"] == "float"

    def test_duplicate_subkey_latter_wins(self) -> None:
        out = _mini("(p1 (type Float) (Type Boolean))")
        assert out["model_specific"]["p1"]["type"] == "boolean"
        assert any("重复" in w and "覆盖" in w for w in out["warnings"])

    def test_duplicate_param_latter_wins(self) -> None:
        out = _mini("(p1 (type Float) (default 1.0))\n"
                    "(p1 (type Integer) (default 2))")
        rec = out["model_specific"]["p1"]
        assert rec["type"] == "integer"
        assert rec["default_typed"] == 2
        assert len(out["model_specific"]) == 1
        assert any("参数 'p1' 重复" in w for w in out["warnings"])

    def test_param_no_children_all_none(self) -> None:
        out = _mini("(p1)")
        rec = out["model_specific"]["p1"]
        assert rec["describe"] is None and rec["type"] is None
        assert rec["default_raw"] is None and rec["bounds_raw"] is None
        assert any("无五键子节" in w for w in out["warnings"])
        assert any("缺 default" in w for w in out["warnings"])

    def test_bare_value_under_param_warned(self) -> None:
        out = _mini("(p1 stray (type Float) (default 1.0))")
        assert out["model_specific"]["p1"]["type"] == "float"
        assert any("裸值 'stray'" in w for w in out["warnings"])

    def test_record_line_number(self) -> None:
        out = parse_ami("(Model_Specific\n  (p (type Float))\n)")
        assert out["model_specific"]["p"]["line"] == 2

    def test_bounds_empty_value_warned(self) -> None:
        out = _mini("(p1 (type Float) (default 1.0) (parse_inbounds))")
        rec = out["model_specific"]["p1"]
        assert rec["bounds_raw"] is None and rec["bounds"] is None
        assert any("无内容" in w for w in out["warnings"])

# ── 版本档位（AMI_Version 表）─────────────────────────────────────────

class TestVersion:
    def test_known_version_no_warning(self, doc: dict[str, Any]) -> None:
        assert doc["ami_version"] == "3.2"
        assert doc["warnings"] == [
            "第 30 行：参数 eq_ctle_steps 缺 default 子节——如实登记"]

    def test_version_table_contains_fixture(self) -> None:
        assert "3.2" in AMI_VERSIONS

    def test_unknown_version_warned_kept(self) -> None:
        out = parse_ami("(Reserved (AMI_Version 9.9))")
        assert out["ami_version"] == "9.9"
        assert any("未知 AMI_Version 档位" in w for w in out["warnings"])

    def test_top_level_fallback(self) -> None:
        out = parse_ami("(ami_version 3.2)\n(Model_Specific (p (type Float)))")
        assert out["ami_version"] == "3.2"
        assert not any("重复" in w for w in out["warnings"])

    def test_top_level_reserved_duplicate_reserved_wins(self) -> None:
        out = parse_ami("(Reserved (AMI_Version 3.2))\n(ami_version 9.9)")
        assert out["ami_version"] == "3.2"
        assert any("RESERVED 优先" in w for w in out["warnings"])

    def test_version_missing_entirely(self) -> None:
        out = parse_ami("(Reserved (Ignore_IL False))")
        assert out["ami_version"] is None
        assert "AMI_Version" in out["missing_reserved"]

# ── DLL/SoC 引用与顶层节闭集 ──────────────────────────────────────────

class TestDllRefs:
    def test_dll_soc_refs_registered(self, doc: dict[str, Any]) -> None:
        assert doc["dll_refs"] == {
            "DLL_file": "ctle_eq.dll", "SoC_file": "soc_clock.dll"}

    def test_dll_soc_keys_closed_set(self) -> None:
        assert DLL_SOC_KEYS == ("dll_file", "soc_file")

    def test_ci_key_keeps_original_spelling(self) -> None:
        out = parse_ami('(dll_file "x.dll")')
        assert out["dll_refs"] == {"dll_file": "x.dll"}

    def test_duplicate_ref_latter_wins(self) -> None:
        out = parse_ami('(DLL_file "a.dll")\n(DLL_file "b.dll")')
        assert out["dll_refs"] == {"DLL_file": "b.dll"}
        assert any("重复" in w for w in out["warnings"])

    def test_missing_ref_value(self) -> None:
        out = parse_ami("(DLL_file)")
        assert out["dll_refs"] == {"DLL_file": None}
        assert any("缺值" in w for w in out["warnings"])

    def test_unknown_top_section_warned(self) -> None:
        out = parse_ami("(Reserved (AMI_Version 3.2))\n(Note hi)")
        assert any("未识别顶层节 'Note'" in w for w in out["warnings"])

# ── 查询三函数 ────────────────────────────────────────────────────────

class TestQueries:
    def test_lookup_model_hit(self, doc: dict[str, Any]) -> None:
        rec = ami_param_lookup(doc, "eq_ctle_gain")
        assert rec is not None
        assert rec["name"] == "eq_ctle_gain"
        assert rec["source"] == "model_specific"
        assert rec["type"] == "float"
        assert rec["default_typed"] == -2.0
        assert rec["bounds"]["hi"] == 0.0
        assert "line" in rec

    def test_lookup_case_insensitive(self, doc: dict[str, Any]) -> None:
        rec = ami_param_lookup(doc, "EQ_CTLE_GAIN")
        assert rec is not None and rec["name"] == "eq_ctle_gain"

    def test_lookup_reserved_fallback(self, doc: dict[str, Any]) -> None:
        rec = ami_param_lookup(doc, "ignore_il")
        assert rec == {
            "name": "Ignore_IL", "source": "reserved", "value": "False"}

    def test_lookup_model_priority_over_reserved(self) -> None:
        out = parse_ami("(Reserved (AMI_Version 3.2) (p1 True))\n"
                        "(Model_Specific (p1 (type Float) (default 1.0)))")
        rec = ami_param_lookup(out, "p1")
        assert rec is not None and rec["source"] == "model_specific"

    def test_lookup_miss_none(self, doc: dict[str, Any]) -> None:
        assert ami_param_lookup(doc, "no_such_param") is None

    def test_lookup_empty_doc(self) -> None:
        assert ami_param_lookup({}, "x") is None

    def test_required_check_complete(self, doc: dict[str, Any]) -> None:
        chk = ami_required_check(doc)
        assert chk["complete"] is True
        assert chk["missing"] == []
        assert chk["present"] == list(REQUIRED_RESERVED_KEYS)
        assert chk["n_missing"] == 0 and chk["n_present"] == 5

    def test_required_check_mini_missing_four(
            self, doc: dict[str, Any]) -> None:
        out = parse_ami(MINI_MISSING_AMI)
        chk = ami_required_check(out)
        assert chk["complete"] is False
        assert chk["missing"] == [
            "Ignore_IL", "Init_Returns_Impulse",
            "GetWave_Exists", "Use_Init_Output"]
        assert chk["present"] == ["AMI_Version"]

    def test_required_check_empty_doc(self) -> None:
        chk = ami_required_check({})
        assert chk["complete"] is False
        assert chk["missing"] == list(REQUIRED_RESERVED_KEYS)

    def test_defaults_table(self, doc: dict[str, Any]) -> None:
        table = ami_defaults_table(doc)
        assert table == {
            "eq_ctle_gain": -2.0, "eq_ctle_pole": 2.0e9,
            "eq_ctle_boost": True, "eq_ctle_steps": None}

    def test_defaults_table_empty_doc(self) -> None:
        assert ami_defaults_table({}) == {}

# ── 截断 fail-soft 与致命面 ───────────────────────────────────────────

class TestTruncation:
    def test_unbalanced_eof_fail_soft(self) -> None:
        out = parse_ami("(Reserved (AMI_Version 3.2)(GetWave_Exists True")
        assert any("括号失衡" in w for w in out["warnings"])
        # 自内向外重建：截断处参数归回 RESERVED（值如实收编）
        assert out["reserved"]["AMI_Version"] == "3.2"
        assert out["reserved"]["GetWave_Exists"] == "True"
        assert "GetWave_Exists" not in out["missing_reserved"]

    def test_unclosed_string_fail_soft(self) -> None:
        out = parse_ami('(Reserved (AMI_Version "3.2')
        assert any("未闭合" in w for w in out["warnings"])
        assert out["reserved"]["AMI_Version"] == "3.2"

    def test_truncated_param_partial_collection(self) -> None:
        out = parse_ami(
            "(Reserved (AMI_Version 3.2))\n(Model_Specific\n"
            "  (p1 (type Float) (default 1.0)")
        assert out["model_specific"]["p1"]["default_typed"] == 1.0
        assert any("括号失衡" in w for w in out["warnings"])

    def test_empty_file_fatal(self) -> None:
        with pytest.raises(AmiParseError):
            parse_ami("")

    def test_whitespace_only_fatal(self) -> None:
        with pytest.raises(AmiParseError):
            parse_ami("   \n\t  ")

    def test_comment_only_fatal(self) -> None:
        with pytest.raises(AmiParseError):
            parse_ami("| just a comment\n| another\n")

    def test_parse_error_is_valueerror(self) -> None:
        assert issubclass(AmiParseError, ValueError)

    def test_deterministic_same_input_same_output(self) -> None:
        assert parse_ami(SAMPLE_AMI) == parse_ami(SAMPLE_AMI)

    def test_output_json_native(self, doc: dict[str, Any]) -> None:
        # 全 JSON 原生类型：直 dump 零 default 兜底
        json.dumps(doc)

    def test_top_level_keys_exact(self, doc: dict[str, Any]) -> None:
        assert set(doc) == {
            "ami_version", "reserved", "missing_reserved",
            "model_specific", "dll_refs", "stats", "warnings"}

    def test_stats_exact(self, stats: dict[str, Any]) -> None:
        assert stats == {
            "n_reserved": 5, "n_model_specific": 4, "n_dll_refs": 2,
            "n_missing_reserved": 0, "n_warnings": 1}

# ── 服务三函数信封契约 ────────────────────────────────────────────────

class TestService:
    def test_parse_envelope_ok_exact_keys(self, ami_file: Path) -> None:
        result = parse_ibis_ami_file(str(ami_file))
        assert set(result) == PARSE_KEYS
        assert result["ok"] is True
        assert result["ami_version"] == "3.2"
        assert result["path"] == str(ami_file)

    def test_parse_envelope_values(self, ami_file: Path) -> None:
        result = parse_ibis_ami_file(str(ami_file))
        assert result["stats"]["n_model_specific"] == 4
        assert result["missing_reserved"] == []
        assert result["warnings"] == [
            "第 30 行：参数 eq_ctle_steps 缺 default 子节——如实登记"]

    def test_parse_missing_file_error(self, tmp_path: Path) -> None:
        result = parse_ibis_ami_file(str(tmp_path / "nope.ami"))
        assert result["ok"] is False
        assert isinstance(result["errors"], list)
        assert all(isinstance(e, str) for e in result["errors"])
        assert any("不可读" in e for e in result["errors"])

    def test_parse_empty_file_error(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.ami"
        f.write_text("", encoding="utf-8")
        result = parse_ibis_ami_file(str(f))
        assert result["ok"] is False
        assert any("AMI 解析失败" in e for e in result["errors"])

    def test_latin1_fallback(self, tmp_path: Path) -> None:
        # 高位字节（Latin-1 é）在注释内——utf-8 解码失败走兜底不炸
        f = tmp_path / "latin.ami"
        f.write_bytes(
            b"(Reserved (AMI_Version 3.2))\n| caf\xe9 comment\n")
        result = parse_ibis_ami_file(str(f))
        assert result["ok"] is True
        assert result["ami_version"] == "3.2"

    def test_report_envelope_ok(self, ami_file: Path) -> None:
        result = ibis_ami_report(str(ami_file))
        assert set(result) == REPORT_KEYS
        assert result["ok"] is True
        assert len(result["reserved_rows"]) == 5
        assert len(result["model_rows"]) == 4
        assert result["reserved_rows"][0] == {
            "name": "AMI_Version", "value": "3.2"}
        assert result["model_rows"][0]["name"] == "eq_ctle_gain"
        assert result["model_rows"][0]["default_typed"] == -2.0
        assert result["dll_refs"] == {
            "DLL_file": "ctle_eq.dll", "SoC_file": "soc_clock.dll"}

    def test_report_missing_file_error(self, tmp_path: Path) -> None:
        result = ibis_ami_report(str(tmp_path / "nope.ami"))
        assert result["ok"] is False
        assert isinstance(result["errors"], list)

    def test_report_empty_file_error(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.ami"
        f.write_text("|| nothing\n", encoding="utf-8")
        result = ibis_ami_report(str(f))
        assert result["ok"] is False

    def test_detail_hit_model(self, ami_file: Path) -> None:
        result = ami_param_detail(str(ami_file), "eq_ctle_gain")
        assert result["ok"] is True
        assert result["requested"] == "eq_ctle_gain"
        assert result["source"] == "model_specific"
        assert result["type"] == "float"
        assert result["default_typed"] == -2.0
        assert result["path"] == str(ami_file)

    def test_detail_case_insensitive(self, ami_file: Path) -> None:
        result = ami_param_detail(str(ami_file), "EQ_CTLE_STEPS")
        assert result["ok"] is True
        assert result["name"] == "eq_ctle_steps"
        assert result["default_typed"] is None

    def test_detail_reserved_hit(self, ami_file: Path) -> None:
        result = ami_param_detail(str(ami_file), "GetWave_Exists")
        assert result["ok"] is True
        assert result["source"] == "reserved"
        assert result["value"] == "True"

    def test_detail_miss_error_with_available(self, ami_file: Path) -> None:
        result = ami_param_detail(str(ami_file), "nope")
        assert result["ok"] is False
        assert isinstance(result["errors"], list)
        assert any("不存在" in e and "可用" in e for e in result["errors"])
        names = result["available"]
        assert "eq_ctle_gain" in names
        assert "Ignore_IL" in names

    def test_detail_missing_file_error(self, tmp_path: Path) -> None:
        result = ami_param_detail(str(tmp_path / "nope.ami"), "x")
        assert result["ok"] is False

# ── CLI（ibis_ami_app 直连/局部父 Typer 自测；接线待合流）──────────────

class TestCLI:
    def test_parse_json_envelope(self, local_app: typer.Typer,
                                 ami_file: Path) -> None:
        r = runner.invoke(local_app, ["ibis-ami", "parse", "--file",
                                      str(ami_file), "--json"])
        assert r.exit_code == 0, r.output
        payload = json.loads(r.output)
        assert payload["ok"] is True
        assert payload["ami_version"] == "3.2"
        assert payload["stats"]["n_model_specific"] == 4

    def test_parse_human_output(self, local_app: typer.Typer,
                                ami_file: Path) -> None:
        r = runner.invoke(local_app, ["ibis-ami", "parse", "--file",
                                      str(ami_file)])
        assert r.exit_code == 0, r.output
        assert "✓ AMI" in r.output
        assert "eq_ctle_gain" in r.output
        assert "缺 default 子节" in r.output

    def test_parse_failure_json_exit1(self, local_app: typer.Typer,
                                      tmp_path: Path) -> None:
        r = runner.invoke(local_app, ["ibis-ami", "parse", "--file",
                                      str(tmp_path / "nope.ami"), "--json"])
        assert r.exit_code == 1
        assert json.loads(r.output)["ok"] is False

    def test_parse_failure_human_exit1(self, local_app: typer.Typer,
                                       tmp_path: Path) -> None:
        r = runner.invoke(local_app, ["ibis-ami", "parse", "--file",
                                      str(tmp_path / "nope.ami")])
        assert r.exit_code == 1
        assert "AMI 解析失败" in r.output

    def test_report_json_envelope(self, local_app: typer.Typer,
                                  ami_file: Path) -> None:
        r = runner.invoke(local_app, ["ibis-ami", "report", "--file",
                                      str(ami_file), "--json"])
        assert r.exit_code == 0, r.output
        payload = json.loads(r.output)
        assert payload["ok"] is True
        assert len(payload["reserved_rows"]) == 5
        assert len(payload["model_rows"]) == 4

    def test_report_human_output(self, local_app: typer.Typer,
                                 ami_file: Path) -> None:
        r = runner.invoke(local_app, ["ibis-ami", "report", "--file",
                                      str(ami_file)])
        assert r.exit_code == 0, r.output
        assert "✓ AMI 报告" in r.output
        assert "AMI_Version" in r.output
        assert "DLL_file" in r.output

    def test_report_failure_json_exit1(self, local_app: typer.Typer,
                                       tmp_path: Path) -> None:
        r = runner.invoke(local_app, ["ibis-ami", "report", "--file",
                                      str(tmp_path / "nope.ami"), "--json"])
        assert r.exit_code == 1
        assert json.loads(r.output)["ok"] is False

    def test_missing_file_option_usage_exit2(
            self, local_app: typer.Typer) -> None:
        r = runner.invoke(local_app, ["ibis-ami", "parse"])
        assert r.exit_code == 2

    @pytest.mark.parametrize("leaf", ["parse", "report"])
    def test_help_real_build(self, local_app: typer.Typer, leaf: str) -> None:
        # #305：真构建 --help（帮助串含 % 或裸 [ 会在展开期炸/渲染歪）
        r = runner.invoke(local_app, ["ibis-ami", leaf, "--help"])
        assert r.exit_code == 0, r.output
        assert "--file" in r.output

    def test_direct_app_help(self) -> None:
        r = runner.invoke(ibis_ami_app, ["--help"])
        assert r.exit_code == 0, r.output
        assert "parse" in r.output and "report" in r.output

    def test_domain_leaf_shape(self, local_app: typer.Typer) -> None:
        from typer.main import get_command

        group = get_command(local_app).commands.get("ibis-ami")
        assert group is not None
        assert set(group.commands) == {"parse", "report"}

    def test_help_text_hygiene(self, local_app: typer.Typer) -> None:
        # D-06 门同判定面预检：命令 help/short_help 与参数 help 零裸 [、
        # 零未成对 %（合流后进全树门亦绿）
        from typer.main import get_command

        group = get_command(local_app).commands["ibis-ami"]
        texts = [group.help or ""]
        for cmd in group.commands.values():
            texts.extend([cmd.help or "", cmd.short_help or ""])
            texts.extend(getattr(p, "help", None) or "" for p in cmd.params)
        for text in texts:
            assert "[" not in text, text
            assert text.replace("%%", "").count("%") == 0, text

    def test_cli_leaves_literal_pin(self) -> None:
        # 计数链钉：ibis-ami 域恰 2 叶、每叶带 --json（新叶无 --json 即红）
        source = Path(
            __import__("rfauto.service.ibis_ami_service", fromlist=["x"])
            .__file__).parent.parent.joinpath(
            "cli", "domains", "ibis_ami.py").read_text(encoding="utf-8")
        assert source.count('@ibis_ami_app.command("parse")') == 1
        assert source.count('@ibis_ami_app.command("report")') == 1
        assert source.count("json_output: bool = typer.Option") == 2
        assert '--json", "-j"' in source
class TestEncodingHygiene:
    @pytest.mark.parametrize("relpath", [
        "src/rfauto/core/ibis_ami_parser.py",
        "src/rfauto/service/ibis_ami_service.py",
        "src/rfauto/cli/domains/ibis_ami.py",
        "tests/unit/test_ibis_ami_parser.py",
    ])
    def test_no_replacement_char(self, relpath: str) -> None:
        # 仓根=tests/unit/test_ibis_ami_parser.py 的 parents[2]
        repo = Path(__file__).resolve().parents[2]
        p = repo / relpath
        text = p.read_text(encoding="utf-8")
        assert "\ufffd" not in text, f"{p} 含 U+FFFD 替换字符"
