"""T-Q27 席 Q-X32（aurora_q）——SKILL 模板服务面+CLI 三叶单测。

覆盖面（任务书 ≥20 条之服务/CLI 半边）：
- 服务四函数信封正负例（list 目录/render 渲染+确定性/lint 守卫/save 落盘
  防覆盖+sha256 互证）；
- 失败信封分类（未知模板带可用清单/必填缺失带指引/渲染异常 fail-loud 不吞
  产物——monkeypatch 注入坏模板钉 lint error → ok=False 路径，#139 钉通道
  家法）；
- CLI ``rfauto skill list/render/lint`` --json 双路径（成功+失败信封同构、
  退出码 0/1/2 口径、--var 解析、--out 落盘、两跑逐字节同）；
- help 卫生（--help 构建成功+零裸 %，#305 家族）；
- 零 runs/ 湖写入（--out 与 lint 文件全落 tmp_path）。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from typer.testing import CliRunner

from rfauto.cli.main import app
from rfauto.core.skill_templates import SKILL_TEMPLATES, get_skill_template
from rfauto.service.skill_template_service import (
    lint_skill_code,
    list_skill_templates,
    render_skill_template,
    save_skill_file,
)

# ── 服务面：list ─────────────────────────────────────────────────────────────


def test_list_skill_templates_envelope_sorted_five():
    result = list_skill_templates()
    assert result["ok"] is True
    assert result["count"] == 5
    names = [t["name"] for t in result["templates"]]
    assert names == sorted(names) == sorted(SKILL_TEMPLATES)
    row = result["templates"][0]
    for key in ("name", "title", "description", "category", "required_vars",
                "optional_vars", "default_vars", "functions"):
        assert key in row


def test_list_required_vars_match_registry():
    for t in list_skill_templates()["templates"]:
        spec = get_skill_template(t["name"])
        assert t["required_vars"] == list(spec.required_vars)
        assert t["optional_vars"] == list(spec.optional_vars)


# ── 服务面：render ───────────────────────────────────────────────────────────


CELL_VARS = {
    "lib_name": "myLib",
    "cell_name": "myCell",
    "shapes": [{"type": "rect", "layer": "M1", "x1": 0, "y1": 0,
                "x2": 1, "y2": 2}],
}


def test_render_envelope_fields_and_determinism():
    a = render_skill_template("cell_layout", CELL_VARS)
    b = render_skill_template("cell_layout", CELL_VARS)
    assert a["ok"] is True
    assert a["skill_code"] == b["skill_code"]
    assert a["sha256"] == b["sha256"]
    assert a["sha256"] == hashlib.sha256(a["skill_code"].encode("utf-8")) \
        .hexdigest()
    assert a["template"] == "cell_layout"
    assert a["category"] == "layout"
    assert a["lint"]["n_errors"] == 0 and a["lint"]["n_warnings"] == 0
    assert a["vars_echo"]["lib_name"] == "myLib"
    # default_vars 合并（cell_layout 无；schematic 有 wires 等）
    r2 = render_skill_template("schematic_instance", {
        "lib_name": "L", "cell_name": "C",
        "instances": [{"lib": "a", "cell": "b", "name": "I0", "x": 0, "y": 0}],
    })
    assert r2["vars_echo"]["wires"] == []  # 服务缺省合并单源
    assert r2["vars_echo"]["seg_width"] == 0.0625


def test_render_with_default_vars_example_roundtrip_all_templates():
    """全模板 default_vars+example_vars 两跑逐字节同（铁律 7 变量直出口径）。"""
    for name in sorted(SKILL_TEMPLATES):
        spec = get_skill_template(name)
        code = render_skill_template(name, dict(spec.example_vars))
        assert code["ok"] is True, (name, code.get("errors"))
        code2 = render_skill_template(name, dict(spec.example_vars))
        assert code["skill_code"] == code2["skill_code"]


def test_render_unknown_template_error_with_available_list():
    result = render_skill_template("nope", {})
    assert result["ok"] is False
    assert "未知 SKILL 模板" in result["errors"][0]
    assert "cell_layout" in result["errors"][0]


def test_render_missing_required_var_error_with_guidance():
    result = render_skill_template("cell_layout", {"lib_name": "x"})
    assert result["ok"] is False
    assert "变量缺失" in result["errors"][0]
    assert any("必填变量" in e for e in result["errors"])


def test_render_unknown_vars_warning_field_not_flipping_ok():
    result = render_skill_template("cell_layout", {**CELL_VARS,
                                                   "lib_nam": "x"})
    assert result["ok"] is True
    assert result["unknown_vars"] == ["lib_nam"]
    assert any("lib_nam" in w for w in result["warnings"])


def test_render_lint_error_fail_loud_keeps_code(monkeypatch):
    """坏模板注入（#139 通道钉法）：lint error → ok=False 且 skill_code 附带。"""
    broken_spec = get_skill_template("cell_layout")
    broken = type(broken_spec)(
        name="broken_probe", title="t", description="d", category="layout",
        source='dbOpenCellViewByType({{lib_name}} "a")\nlet cv\n')
    import rfauto.core.skill_templates as reg

    monkeypatch.setitem(reg.SKILL_TEMPLATES, "broken_probe", broken)
    result = render_skill_template("broken_probe", {"lib_name": "L"})
    assert result["ok"] is False
    assert result["lint"]["n_errors"] >= 1
    assert "skill_code" in result  # 产物可见不吞
    assert any("语法守卫" in e for e in result["errors"])


# ── 服务面：lint / save ──────────────────────────────────────────────────────


def test_lint_skill_code_envelope_counts():
    good = lint_skill_code("dbSave(cv)\n")
    assert good["ok"] is True
    assert good["n_errors"] == 0
    bad = lint_skill_code("let cv\ndbSave(cv\n")
    assert bad["ok"] is True  # ok=调用成立；健康度读 n_errors
    assert bad["n_errors"] >= 2  # let_binding + paren_balance
    codes = {i["code"] for i in bad["issues"]}
    assert "let_binding" in codes and "paren_balance" in codes


def test_save_skill_file_roundtrip_sha_and_overwrite_guard(tmp_path):
    code = "dbSave(cv)\n"
    target = tmp_path / "sub" / "out.il"
    saved = save_skill_file(code, target)
    assert saved["ok"] is True
    disk = target.read_bytes()
    assert saved["sha256"] == hashlib.sha256(disk).hexdigest()
    assert saved["bytes"] == len(disk)
    assert disk == code.encode("utf-8")  # 零平台换行翻译
    again = save_skill_file(code, target)
    assert again["ok"] is False and "防覆盖" in again["errors"][0]
    forced = save_skill_file(code, target, overwrite=True)
    assert forced["ok"] is True


# ── CLI 三叶 ─────────────────────────────────────────────────────────────────


def _invoke(args: list[str]):
    return CliRunner().invoke(app, args)


def _invoke_json(args: list[str]) -> tuple[int, dict]:
    result = _invoke(args)
    payload = json.loads(result.output)
    return result.exit_code, payload


def test_cli_skill_list_json_envelope():
    rc, payload = _invoke_json(["skill", "list", "--json"])
    assert rc == 0
    assert payload["ok"] is True and payload["count"] == 5
    assert "cell_layout" in [t["name"] for t in payload["templates"]]


def test_cli_skill_list_human_smoke():
    result = _invoke(["skill", "list"])
    assert result.exit_code == 0
    assert "cell_layout" in result.output


def test_cli_skill_render_json_out_and_byte_identical_two_runs(tmp_path):
    out1 = tmp_path / "a.il"
    out2 = tmp_path / "b.il"
    args = ["skill", "render", "cell_layout",
            "--var", "lib_name=myLib", "--var", "cell_name=myCell",
            "--var", "shapes=[{\"type\": \"rect\", \"layer\": \"M1\","
            " \"x1\": 0, \"y1\": 0, \"x2\": 1, \"y2\": 2}]"]
    rc1, p1 = _invoke_json([*args, "--out", str(out1), "--json"])
    rc2, p2 = _invoke_json([*args, "--out", str(out2), "--json"])
    assert rc1 == 0 and rc2 == 0
    assert p1["ok"] and p2["ok"]
    assert p1["skill_code"] == p2["skill_code"]  # 两跑逐字节同（验收口径）
    assert out1.read_bytes() == out2.read_bytes()  # 盘上亦同
    assert Path(p1["file_path"]) == out1
    assert p1["sha256"] == hashlib.sha256(out1.read_bytes()).hexdigest()
    # --var 数值/bool/list 解析进 vars_echo
    assert p1["vars_echo"]["lib_name"] == "myLib"
    shapes = p1["vars_echo"]["shapes"]
    assert isinstance(shapes, list) and shapes[0]["x2"] == 1


def test_cli_skill_render_refuses_overwrite_without_force(tmp_path):
    out = tmp_path / "x.il"
    out.write_text("old\n", encoding="utf-8")
    rc, payload = _invoke_json([
        "skill", "render", "aedt_run_simulation",
        "--var", "setup_file=s.ocnxl", "--var", "summary_csv=r.csv",
        "--out", str(out), "--json"])
    assert rc == 1
    assert payload["ok"] is False
    assert any("防覆盖" in e for e in payload["errors"])
    assert out.read_text(encoding="utf-8") == "old\n"  # 原文件零改动
    rc2, p2 = _invoke_json([
        "skill", "render", "aedt_run_simulation",
        "--var", "setup_file=s.ocnxl", "--var", "summary_csv=r.csv",
        "--out", str(out), "--force", "--json"])
    assert rc2 == 0 and p2["ok"] is True


def test_cli_skill_render_missing_var_fail_envelope_exit_1():
    rc, payload = _invoke_json(["skill", "render", "cell_layout",
                                "--var", "lib_name=x", "--json"])
    assert rc == 1
    assert payload["ok"] is False
    assert any("变量缺失" in e for e in payload["errors"])


def test_cli_skill_render_usage_error_exit_2_json_envelope():
    rc, payload = _invoke_json(["skill", "render", "cell_layout",
                                "--var", "novalue", "--json"])
    assert rc == 2  # usage 错误退出码 2（#ge1㉙：--json 失败路径 JSON 信封）
    assert payload["ok"] is False
    assert any("形态非法" in e for e in payload["errors"])


def test_cli_skill_render_human_prints_code(tmp_path):
    out = tmp_path / "h.il"
    result = _invoke(["skill", "render", "aedt_run_simulation",
                      "--var", "setup_file=s.ocnxl",
                      "--var", "summary_csv=r.csv",
                      "--out", str(out)])
    assert result.exit_code == 0
    assert "SKILL 渲染完成" in result.output
    assert out.is_file()


def test_cli_skill_lint_ok_and_error_exit_codes(tmp_path):
    good = tmp_path / "good.il"
    good.write_text("let( (cv)\n  dbSave(cv)\n)\n", encoding="utf-8")
    rc, payload = _invoke_json(["skill", "lint", str(good), "--json"])
    assert rc == 0 and payload["ok"] is True and payload["n_errors"] == 0

    bad = tmp_path / "bad.il"
    bad.write_text("let cv\ndbSave(cv\n", encoding="utf-8")
    rc_bad, payload_bad = _invoke_json(["skill", "lint", str(bad), "--json"])
    assert rc_bad == 1  # error 级 → 退出码 1（CI 面裁定）
    assert payload_bad["ok"] is True and payload_bad["n_errors"] >= 2

    human = _invoke(["skill", "lint", str(bad)])
    assert human.exit_code == 1
    assert "let_binding" in human.output

    missing = _invoke_json(["skill", "lint", str(tmp_path / "nope.il"),
                            "--json"])
    assert missing[0] == 2 and missing[1]["ok"] is False


def test_cli_skill_help_hygiene_no_bare_percent():
    """--help 三叶构建成功+零裸 %（#305 家族）。"""
    runner = CliRunner()
    for args in (["skill", "--help"], ["skill", "render", "--help"],
                 ["skill", "lint", "--help"], ["skill", "list", "--help"]):
        result = runner.invoke(app, args)
        assert result.exit_code == 0, (args, result.output)
        assert "%" not in result.output.replace("%%", "")


def test_cli_skill_registration_face_zero_shadow():
    """顶层 skill 组+三叶在位（zero-shadow 家法：注册面=解析面）。"""
    from typer.main import get_command

    cmd = get_command(app)
    assert "skill" in cmd.commands
    assert set(cmd.commands["skill"].commands) == {"list", "render", "lint"}
