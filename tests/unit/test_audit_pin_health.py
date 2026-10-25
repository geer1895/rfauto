"""R8 pyproject 钉版健康度审计单测：纯声明面分类/矛盾/余量 + rc 语义。

解析口径用 packaging.Requirement（`pydantic>=2.5` 无空格形态首版手写
split 出过坑，此处钉住回归）；实树测试钉现值基线（0 矛盾/extras 理由
全覆盖棘轮——新增无理由 extras 即红，house style 守卫）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import audit_pin_health as ph


def _project(deps: list, extras: dict | None = None) -> dict:
    """project 表（parse_declared 入参口径，非整个 TOML 文档）。"""
    project: dict = {"dependencies": deps}
    if extras is not None:
        project["optional-dependencies"] = extras
    return project


def test_parse_declared_no_space_spec_and_extras_merge():
    declared = ph.parse_declared(_project(
        ["pydantic>=2.5", "scikit_rf>=2.0,<3", "rich"],
        {"ui": ["starlette>=0.35"], "report": ["rich>=13.7"]}))
    assert set(declared) == {"pydantic", "scikit-rf", "rich", "starlette"}
    assert declared["pydantic"]["specs"] == ["<2.6,>=2.5"] or \
        declared["pydantic"]["specs"] == [">=2.5"]
    assert declared["scikit-rf"]["specs"] == ["<3,>=2.0"]  # packaging 规范序
    assert declared["rich"]["sources"] == ["core", "extras:report"]
    assert declared["rich"]["specs"] == [">=13.7"]


def test_parse_declared_extra_bracket_and_marker_forms():
    declared = ph.parse_declared(_project(
        ["pymoo[pysr]>=0.6", "numpy>=1.24; platform_system != 'Windows'"]))
    assert "pymoo" in declared and "numpy" in declared
    assert declared["pymoo"]["specs"] == [">=0.6"]


def test_classify_shape_six_forms():
    assert ph.classify_shape("") == "none"
    assert ph.classify_shape(">=1.2") == "floor"
    assert ph.classify_shape("<2") == "cap"
    assert ph.classify_shape("==3.8.0") == "pin"
    assert ph.classify_shape(">=2.0,<3") == "range"
    assert ph.classify_shape("==2.1.*") == "wildcard"


def test_find_contradictions_floor_cap_and_pins():
    declared = ph.parse_declared(_project(
        ["a<3"], {"x": ["a>=3"], "y": ["b==1.0", "b==2.0"]}))
    issues = ph.find_contradictions(declared)
    assert any("a" in s and "floor" in s for s in issues)
    assert any("b" in s and "精钉" in s for s in issues)


def test_find_contradictions_compatible_range_not_flagged():
    declared = ph.parse_declared(_project(
        ["a>=2.0,<3"], {"x": ["a>=1.5"]}))
    assert ph.find_contradictions(declared) == []
    same_pin = ph.parse_declared(_project(
        [], {"x": ["c==1.0"], "y": ["c==1.0"]}))
    assert ph.find_contradictions(same_pin) == []


def test_check_installed_violation_and_missing():
    declared = ph.parse_declared(_project(["a>=2.0", "b<1.0", "c>=1.0"]))
    issues = ph.check_installed(declared, {"a": "1.9", "b": "0.9", "c": "2.0"})
    assert len(issues) == 1
    assert "a" in issues[0] and "1.9" in issues[0]
    assert ph.check_installed(declared, {"a": "2.5"}) == []  # 缺名跳过


def test_cap_headroom_semantics():
    near = ph.cap_headroom("1.4.0", ">=1.0,<1.5")
    assert near["near_cap"] is True  # 同 major 且距 cap 1 个 minor
    far = ph.cap_headroom("2.1.0", ">=2.0,<3")
    assert far["gap_major"] == 1 and far["near_cap"] is False
    assert ph.cap_headroom("2.1.0", ">=2.0") is None  # 无 cap
    assert ph.cap_headroom("garbage", ">=2.0,<3")["near_cap"] is False


def test_weak_floors_two_major_lead():
    declared = ph.parse_declared(_project(["a>=1.0", "b>=2.9"]))
    out = ph.weak_floors(declared, {"a": "3.0", "b": "3.0"})
    assert len(out) == 1 and "a" in out[0]


def test_extras_missing_rationale_styles():
    lines = [
        "# 组注释",
        "good = [\"a>=1\"]",
        "inline = [\"b>=1\"]  # 行内理由",
        "blank_gap = [\"c>=1\"]",  # 注释与键之间隔空行 → 缺
        "",
        "# 上面隔了空行",
    ]
    assert ph.extras_missing_rationale(
        lines, ["good", "inline", "blank_gap", "nokey"]) == [
            "blank_gap", "nokey"]


def test_verdict_rc_semantics():
    assert ph.verdict({"error": "x"}) == 2
    base = {"contradictions": [], "installed_violations": [],
            "extras_missing_rationale": []}
    assert ph.verdict(base) == 0
    for key in ("contradictions", "installed_violations",
                "extras_missing_rationale"):
        trip = dict(base)
        trip[key] = ["x"]
        assert ph.verdict(trip) == 1


def test_main_rc1_on_contradiction(tmp_path):
    p = tmp_path / "pyproject.toml"
    p.write_text(
        '[project]\nname = "x"\nversion = "0"\n'
        'dependencies = ["a<3"]\n'
        "[project.optional-dependencies]\n"
        'e = ["a>=3"]\n',
        encoding="utf-8")
    rc = ph.main(["--pyproject", str(p), "--no-env"])
    assert rc == 1


def test_main_rc2_on_unreadable(tmp_path):
    rc = ph.main(["--pyproject", str(tmp_path / "nope.toml")])
    assert rc == 2


def test_main_real_tree_baseline():
    out = Path("runs/aurora72/_a7d_pin_health_test.json")
    out.parent.mkdir(parents=True, exist_ok=True)  # 干净 checkout 容错
    try:
        rc = ph.main(["--json", str(out)])
        assert rc == 0
        rep = json.loads(out.read_text(encoding="utf-8"))
        assert rep["declared_names"] >= 40
        assert rep["contradictions"] == []
        assert rep["extras_missing_rationale"] == []  # 棘轮 0：理由全覆盖
        assert rep["installed_violations"] == []
    finally:
        out.unlink(missing_ok=True)
