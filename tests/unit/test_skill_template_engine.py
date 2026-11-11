"""T-Q27 席 Q-X32（aurora_q CAD 大扩展）——SKILL 模板引擎+模板集单测。

覆盖面（任务书 ≥20 条之引擎/守卫/模板集半边）：
- 字面量渲染（str 转义/数值/bool t,nil/None nil/list 函数形态/dict 拒渲染）；
- 过滤器（raw 须 str/default 兜底/未知过滤器 fail-loud/非法字面量参数）；
- 控制流（for+loop.index/嵌套遮蔽/if-elif-else/比较/in-and-or-not/括号）；
- fail-loud（变量缺失带行号/未闭合标签/条件首段拼写缺失红、实例级可选键
  falsy——#117 反像语义）；
- 确定性（同模板+变量两跑逐字节同）；
- 语法守卫（括号配对/引号闭合/let 绑定/函数名白名单 warning 分级/赋值
  目标/残留标签）；
- 结构化生成器（skill_call/skill_let/skill_if/skill_foreach）；
- 模板注册表（5 模板/consumer 单源自查 functions⊆白名单/全模板
  example_vars 渲染零 issue/两跑逐字节同/逐模板输出形态钉）。

零网络零真机零 runs/ 湖写入（纯内存字符串面）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rfauto.cli.main import app
from rfauto.core.skill_template_engine import (
    CALC_SKILL_FUNCTIONS,
    CORE_SKILL_FUNCTIONS,
    EDA_SKILL_FUNCTIONS,
    KNOWN_SKILL_FUNCTIONS,
    SkillTemplateError,
    list_template_var_info,
    list_template_vars,
    render_template,
    skill_call,
    skill_foreach,
    skill_if,
    skill_let,
    skill_lint_issues,
    skill_literal,
)
from rfauto.core.skill_templates import (
    SKILL_TEMPLATE_CATEGORIES,
    SKILL_TEMPLATES,
    get_skill_template,
    list_skill_template_names,
)

# ── 字面量渲染 ────────────────────────────────────────────────────────────────


def test_literal_str_escapes_quote_and_backslash():
    out = render_template("{{s}}", {"s": 'a"b\\c'})
    assert out == '"a\\"b\\\\c"'


def test_literal_numbers_bool_none():
    out = render_template("{{i}} {{f}} {{t}} {{x}} {{y}}",
                          {"i": 3, "f": 0.25, "t": True, "x": False,
                           "y": None})
    assert out == "3 0.25 t nil nil"


def test_literal_list_renders_list_call_and_dict_rejected():
    out = render_template("{{xs}}", {"xs": ["M1", "drawing", 2, True]})
    assert out == 'list("M1" "drawing" 2 t)'
    with pytest.raises(SkillTemplateError, match="无 SKILL 字面量形态"):
        render_template("{{d}}", {"d": {"a": 1}})


def test_non_finite_float_rejected():
    with pytest.raises(SkillTemplateError, match="非有限数值"):
        render_template("{{f}}", {"f": float("inf")})


# ── 过滤器 ────────────────────────────────────────────────────────────────────


def test_raw_filter_passthrough_and_non_str_rejected():
    assert render_template("{{p|raw}}", {"p": "list(0:0 1:1)"}) == \
        "list(0:0 1:1)"
    with pytest.raises(SkillTemplateError, match="raw 过滤器要求 str"):
        render_template("{{p|raw}}", {"p": 3})


def test_default_filter_missing_and_present():
    src = "{{v|default(\"layout\")}}"
    assert render_template(src, {}) == '"layout"'
    assert render_template(src, {"v": "schematic"}) == '"schematic"'
    # default 参数须为合法字面量
    with pytest.raises(SkillTemplateError, match="非法字面量参数"):
        render_template("{{v|default(未引用)}}", {})
    with pytest.raises(SkillTemplateError, match="default 过滤器必须带"):
        render_template("{{v|default}}", {})
    with pytest.raises(SkillTemplateError, match="raw 过滤器不收参数"):
        render_template("{{v|raw(1)}}", {"v": "x"})


def test_unknown_filter_fails_loud():
    with pytest.raises(SkillTemplateError, match="未知过滤器"):
        render_template("{{v|upper}}", {"v": "x"})


# ── 控制流 ────────────────────────────────────────────────────────────────────


def test_for_loop_with_loop_index_and_nested_shadowing():
    src = "{%for s in shapes%}[{{loop.index}}:{{s.layer}}]{%endfor%}"
    out = render_template(src, {"shapes": [{"layer": "M1"}, {"layer": "M2"}]})
    assert out == '[1:"M1"][2:"M2"]'
    nested = ("{%for a in outer%}{%for b in inner%}"
              "{{loop.index0}}{%endfor%}|{{loop.index}}{%endfor%}")
    out2 = render_template(nested, {"outer": [1], "inner": [1, 2, 3]})
    assert out2 == "012|1"
    # 非序列迭代目标 fail-loud
    with pytest.raises(SkillTemplateError, match="须为 list/tuple"):
        render_template("{%for x in items%}{{x}}{%endfor%}", {"items": 5})
    # 缺失且无 default 的迭代目标 fail-loud
    with pytest.raises(SkillTemplateError, match="变量缺失: items"):
        render_template("{%for x in items%}{{x}}{%endfor%}", {})


def test_for_iter_default_allows_missing_list():
    src = "{%for w in wires|default([])%}W{%endfor%}END"
    assert render_template(src, {}) == "END"
    assert render_template(src, {"wires": [1, 2]}) == "WWEND"


def test_if_elif_else_with_comparisons_and_logic():
    src = "{%if n > 2%}big{%elif n == 2%}two{%else%}small{%endif%}"
    assert render_template(src, {"n": 2}) == "two"
    assert render_template(src, {"n": 9}) == "big"
    assert render_template(src, {"n": 1}) == "small"
    logic = ("{%if (a == \"R0\" or b) and not c%}Y{%endif%}"
             "{%if \"m\" in layers%}in{%endif%}"
             "{%if \"z\" not in layers%}notin{%endif%}")
    out = render_template(logic, {"a": "R90", "b": True, "c": False,
                                  "layers": ["m"]})
    assert out == "Yinnotin"
    # 字符串字面量带转义引号
    assert render_template("{%if s == \"a\\\"b\"%}Q{%endif%}",
                           {"s": 'a"b'}) == "Q"
    # 非法 token fail-loud
    with pytest.raises(SkillTemplateError, match="非法 token"):
        render_template("{%if a $ b%}Y{%endif%}", {"a": 1, "b": 2})


def test_cond_item_attr_missing_falsy_but_root_typo_fails_loud():
    # 实例级可选键（d.rot）缺失 → falsy（#117 反像：条件容错只到首段存在）
    out = render_template("{%for d in ds%}{%if d.rot%}R{%endif%}{%endfor%}",
                          {"ds": [{"rot": "R90"}, {}]})
    assert out == "R"
    # 首段拼写不存在 → fail loud（防静默 falsy）
    with pytest.raises(SkillTemplateError, match="变量缺失: rt"):
        render_template("{%if rt%}Y{%endif%}", {})


def test_missing_output_var_fails_loud_with_line_number():
    with pytest.raises(SkillTemplateError, match="变量缺失: nope") as ei:
        render_template("line1\nline2 {{nope}}", {})
    assert ei.value.line == 2


def test_unclosed_tag_and_malformed_path_fail_loud():
    with pytest.raises(SkillTemplateError, match="未闭合的模板标签"):
        render_template("abc {{x y", {"x": 1})
    with pytest.raises(SkillTemplateError, match="非法变量路径段"):
        render_template("{{x.}}", {"x": 1})
    with pytest.raises(SkillTemplateError, match="未知语句标签"):
        render_template("{%while x%}{%endwhile%}", {"x": 1})
    with pytest.raises(SkillTemplateError, match="缺 endfor"):
        render_template("{%for x in xs%}{{x}}", {"xs": [1]})
    with pytest.raises(SkillTemplateError, match="缺 elif/else/endif"):
        render_template("{%if x%}Y", {"x": 1})


def test_template_comments_dropped_and_determinism_byte_identical():
    src = "{# secret #}A{{x}}{# gone #}"
    assert render_template(src, {"x": 1}) == "A1"
    spec = get_skill_template("cell_layout")
    a = render_template(spec.source,
                        {**spec.default_vars, **spec.example_vars})
    b = render_template(spec.source,
                        {**spec.default_vars, **spec.example_vars})
    assert a == b


# ── 变量盘点 ──────────────────────────────────────────────────────────────────


def test_list_template_var_info_required_optional():
    src = ("{{a}} {{b|default(\"x\")}} {%for s in ss|default([])%}{{s.k}}"
           "{%endfor%} {%if flag%}F{%endif%}")
    info = list_template_var_info(src)
    assert info["required"] == ["a", "flag"]
    assert info["optional"] == ["b", "ss"]
    assert list_template_vars(src) == ["a", "flag"]


# ── 结构化生成器 ──────────────────────────────────────────────────────────────


def test_structured_builders_shapes():
    assert skill_call("dbCreateRect", "cv", 'list("M1" "drawing")',
                      "list(0:0 10:20)") == \
        'dbCreateRect(cv list("M1" "drawing") list(0:0 10:20))'
    assert skill_literal("a\"b") == '"a\\"b"'
    let = skill_let([("cv", None), ("n", "3")], ["setq(n 4)"], indent=1)
    assert let == "  let( (cv n 3)\n    setq(n 4)\n  )"
    blk = skill_if("a > b", ["x = 1"], ["x = 2"])
    assert blk == "if( a > b\n  then\n    x = 1\n  else\n    x = 2\n)"
    fe = skill_foreach("s", "shapes", ["foo(s)"])
    assert fe == "foreach( s shapes\n  foo(s)\n)"


# ── SKILL 语法守卫（lint） ────────────────────────────────────────────────────

GOOD_SKILL = (
    "let( (cv master inst)\n"
    "  cv = dbOpenCellViewByType(\"l\" \"c\" \"layout\" \"a\" \"maskLayout\")\n"
    "  dbCreateRect(cv list(\"M1\" \"drawing\") list(0:0 10:20))\n"
    "  inst~>orient = \"R90\"\n"
    ")\n"
)


def test_lint_clean_code_zero_issues():
    assert skill_lint_issues(GOOD_SKILL) == []


def test_lint_paren_balance_strings_and_comments_ignored():
    # 字符串/注释里的括号引号不计
    ok = 'dbCreateLabel(cv "t(x) \\"q") ; comment ( unbalanced\n'
    assert skill_lint_issues(ok) == []
    codes = {(i["code"], i["line"]) for i in
             skill_lint_issues("a = list(1\nb = list(2)\n")}
    assert ("paren_balance", 2) in codes
    codes2 = {(i["code"], i["line"]) for i in
              skill_lint_issues("a = list(1)\n)\n")}
    assert ("paren_balance", 2) in codes2


def test_lint_quote_closure_odd_per_line():
    issues = skill_lint_issues('a = list("open\nb = list(1)\n')
    assert any(i["code"] == "quote_closure" and i["line"] == 1
               for i in issues)
    assert skill_lint_issues('a = list("say \\"hi\\" ok")\n') == []


def test_lint_let_binding_needs_paren_and_not_flag_letseq():
    issues = skill_lint_issues("let cv\nlist(1)\n")
    assert any(i["code"] == "let_binding" and i["line"] == 1 for i in issues)
    assert skill_lint_issues("letseq( (x 1)\n  list(x)\n)\n") == []


def test_lint_unknown_function_warning_and_known_clean():
    issues = skill_lint_issues("dbCreateRec(cv x)\n")
    assert [(i["severity"], i["code"]) for i in issues] == \
        [("warning", "unknown_function")]
    # 计算器函数面在白名单
    assert skill_lint_issues('ocnPrint(?output "o.csv" v("out") IDC("/V0"))\n') \
        == []


def test_lint_assignment_target_forms():
    assert skill_lint_issues("cv = list(1)\nx~>orient = \"R0\"\n") == []
    issues = skill_lint_issues("1bad = list(1)\n")
    assert any(i["code"] == "assignment_target" for i in issues)


def test_lint_residual_template_tags_error():
    issues = skill_lint_issues("dbSave(cv) ; {{x}} leak\n")
    assert [i["code"] for i in issues] == ["template_tag"]


# ── 模板注册表（#3 注册表消费者单源自查） ─────────────────────────────────────


def test_registry_has_five_templates_sorted_with_valid_category():
    names = list_skill_template_names()
    assert names == ["aedt_run_simulation", "cell_layout", "layer_setup",
                     "schematic_instance", "waveform_export"]
    assert len(SKILL_TEMPLATES) == 5
    for name in names:
        spec = get_skill_template(name)
        assert spec.category in SKILL_TEMPLATE_CATEGORIES
        assert spec.source.strip()
    with pytest.raises(SkillTemplateError, match="未知 SKILL 模板"):
        get_skill_template("nope")
    with pytest.raises(SkillTemplateError, match="重名注册"):
        from rfauto.core.skill_templates import SkillTemplateSpec, register_skill_template
        register_skill_template(SkillTemplateSpec(
            name="cell_layout", title="t", description="d",
            category="layout", source="x"))


def test_registry_functions_subset_of_known_whitelist_single_source():
    """模板注册表消费者自查（#304 家法）：生成面函数 ⊆ lint 白名单单源。"""
    for name in list_skill_template_names():
        spec = get_skill_template(name)
        unknown = [f for f in spec.functions if f not in KNOWN_SKILL_FUNCTIONS]
        assert not unknown, f"{name}: 白名单外函数 {unknown}"


def test_whitelist_families_exported():
    assert "let" in CORE_SKILL_FUNCTIONS and "foreach" in CORE_SKILL_FUNCTIONS
    assert "dbCreateRect" in EDA_SKILL_FUNCTIONS
    assert "v" in CALC_SKILL_FUNCTIONS
    assert KNOWN_SKILL_FUNCTIONS == (
        CORE_SKILL_FUNCTIONS | EDA_SKILL_FUNCTIONS | CALC_SKILL_FUNCTIONS)


@pytest.mark.parametrize("name", list_skill_template_names())
def test_every_template_renders_clean_and_deterministic(name):
    """全模板冒烟（5 模板全可用验收）：example_vars 渲染零 lint issue +
    两跑逐字节同 + 输出零残留标签。"""
    spec = get_skill_template(name)
    vars_v = {**spec.default_vars, **spec.example_vars}
    code1 = render_template(spec.source, vars_v)
    code2 = render_template(spec.source, vars_v)
    assert code1 == code2
    assert "{{" not in code1 and "{%" not in code1
    assert skill_lint_issues(code1) == []


def test_cell_layout_emits_rect_path_label_with_var_values():
    spec = get_skill_template("cell_layout")
    code = render_template(spec.source,
                           {**spec.default_vars, **spec.example_vars})
    assert 'dbOpenCellViewByType("myLib" "myCell" "layout" "a" "maskLayout")' \
        in code
    assert 'dbCreateRect(cv list("Metal1" "drawing") list(0:0 10.0:20.0))' \
        in code
    assert "dbCreatePath(cv list(\"Metal1\" \"drawing\") 0.5 " \
           "list(0:0 10:0 10:5))" in code
    assert '"GND" "centerCenter" "R0" 0.25 "labelObject"' in code
    assert "dbSave(cv)" in code and "dbClose(cv)" in code


def test_schematic_instance_orient_only_when_present_and_wires():
    spec = get_skill_template("schematic_instance")
    base = {**spec.default_vars, **spec.example_vars}
    code = render_template(spec.source, base)
    assert 'dbCreateInst(cv master list(0.0:1.0) "R0")' in code
    assert 'inst~>orient = "R0"' in code  # 首实例带 rot
    assert code.count("inst~>orient") == 1  # 次实例无 rot 不写
    assert ('schCreateWire(cv "draw" "full" '
            'list(list(0.375:1.0 1.625:1.0)) 0.0625 0.0625 0)') in code
    # 全实例无 rot + 无 wires → orient/wire 面零出现
    slim = render_template(spec.source, {
        "lib_name": "L", "cell_name": "C",
        "instances": [{"lib": "a", "cell": "b", "name": "I0", "x": 0, "y": 0}],
    })
    assert "inst~>orient" not in slim
    assert "schCreateWire" not in slim


def test_aedt_run_simulation_exit_after_flag():
    spec = get_skill_template("aedt_run_simulation")
    off = render_template(spec.source, {**spec.default_vars,
                                        **spec.example_vars,
                                        "exit_after": False})
    assert "ocnxlExit" not in off
    assert 'load("./mySim_setup.ocnxl")' in off
    assert 'ocnxlOutputSummaryCSV("./results_summary.csv")' in off
    on = render_template(spec.source, {**spec.default_vars,
                                       **spec.example_vars,
                                       "exit_after": True})
    assert "ocnxlExit()" in on


def test_waveform_export_v_and_raw_expr_signals():
    spec = get_skill_template("waveform_export")
    code = render_template(spec.source,
                           {**spec.default_vars, **spec.example_vars})
    assert 'v("out") IDC("/V0")' in code
    assert '?numberNotation "engineering" ?precision 10 ?width 80' in code
    assert 'ocnPrint(?output "./wave_out.csv"' in code


def test_layer_setup_save_flag_and_display_rows():
    spec = get_skill_template("layer_setup")
    code = render_template(spec.source,
                           {**spec.default_vars, **spec.example_vars})
    assert 'ddGetObj("myTechLib")' in code
    assert 'techAddLayer(tf "Metal1" "drawing" 11)' in code
    assert "techUpdateTechFile(tf)" in code  # example save=True
    assert 'displayProps = \'(' in code
    nosave = render_template(spec.source, {**spec.default_vars,
                                           **spec.example_vars,
                                           "save": False,
                                           "display_rows": []})
    assert "techUpdateTechFile" not in nosave
    assert "displayProps = '(" not in nosave


# ── 计数链（CLI 新叶照 #304 家法字面钉） ─────────────────────────────────────


def test_cli_count_pin_skill_three_leaves():
    import importlib.util as _ilu

    cn_spec = _ilu.spec_from_file_location(
        "check_numbers_gate",
        Path(__file__).resolve().parents[2] / "scripts" / "check_numbers.py")
    cn = _ilu.module_from_spec(cn_spec)
    cn_spec.loader.exec_module(cn)
    # 总量钉=共享面（并行席 liberty/spice/citi 同窗落树持续推进，精确总量
    # 由四共享钉文件承担+合流终扫收口）；本席所有权断言=skill 域恰 3 叶
    # +总量不低于本席贡献后下限（作用域收窄非放松：+3 的精确记账在
    # test_cli/test_check_numbers 链条目）。
    assert cn.cli_leaf_counts()["skill"] == 3
    assert cn.count_cli() >= 311
    from typer.main import get_command

    cmd = get_command(app)
    skill = cmd.commands["skill"]
    assert set(skill.commands) == {"list", "render", "lint"}
