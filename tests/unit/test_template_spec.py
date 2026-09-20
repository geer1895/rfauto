"""WP2.0 TemplateSpec（E2）单测：注册表语义 + 三模板接线 + 草稿生成。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SRC))

from rfauto.models.template_spec import (
    TEMPLATE_SPECS,
    TemplateComponentMissing,
    TemplateSpec,
    TemplateSpecRegistry,
)
from rfauto.models.template_specs import bootstrap_template_specs
from rfauto.service.template_spec_service import (
    draft_recipe_from_spec,
    list_template_specs,
)


def test_bootstrap_registers_expected_templates():
    bootstrap_template_specs()
    assert set(TEMPLATE_SPECS.names()) >= {"branchline", "patch",
                                           "wilkinson", "mline"}


def test_duplicate_registration_rejected():
    reg = TemplateSpecRegistry()
    spec = TemplateSpec(name="x", meta={}, synthesizer=lambda **k: None)
    reg.register(spec)
    with pytest.raises(ValueError, match="重名"):
        reg.register(spec)


def test_unknown_name_keyerror_lists_available():
    with pytest.raises(KeyError) as ei:
        TEMPLATE_SPECS.get("no_such_template")
    assert "wilkinson" in str(ei.value)


def test_component_missing_explicit_error():
    reg = TemplateSpecRegistry()
    reg.register(TemplateSpec(name="bare", meta={},
                              synthesizer=lambda **k: None))
    with pytest.raises(TemplateComponentMissing, match="未实现组件"):
        reg.component("bare", "render_script")


def test_describe_json_ready_with_component_flags():
    bootstrap_template_specs()
    items = {t["name"]: t for t in TEMPLATE_SPECS.describe()}
    for name in ("wilkinson", "branchline", "patch"):
        comp = items[name]["components"]
        assert comp["render_script"] and comp["synthesizer"]
        assert comp["fake_model"] and comp["hfss_plugin"]
        assert "param_semantics" in items[name]["meta_keys"]
    assert items["wilkinson"]["physics_roles"]["arm_len_mm"] == \
        "resonator_length_mm"
    json.dumps(TEMPLATE_SPECS.describe(), ensure_ascii=False)


def test_wired_components_resolve_and_call():
    bootstrap_template_specs()
    # render_script 组件经 partial 绑定模板名后可调用（不真渲染，
    # 只验证组件解析与调用约定）
    render = TEMPLATE_SPECS.component("wilkinson", "render_script")
    assert callable(render)
    # fake_model 组件可调用
    assert callable(TEMPLATE_SPECS.component("patch", "fake_model"))


def test_draft_recipe_via_spec_real_synthesis():
    """草稿走真 synthesis（skrf HJ + materials.yaml，零求解）。"""
    import os

    old = os.getcwd()
    os.chdir(REPO)  # synthesize_* 需 configs/materials.yaml
    try:
        bootstrap_template_specs()
        r = TEMPLATE_SPECS.draft_recipe("wilkinson")
        assert r["model"] == "wilkinson_power_divider"
        assert {"arm_len_mm", "series_w_mm", "shunt_w_mm"} <= set(r["params"])
    finally:
        os.chdir(old)


def test_service_list_and_draft():
    import os

    old = os.getcwd()
    os.chdir(REPO)
    try:
        r = list_template_specs()
        assert r["ok"] and len(r["templates"]) >= 3
        r = draft_recipe_from_spec("patch", {})
        assert r["ok"] and r["recipe_draft"]["model"] == "patch_antenna"
        r = draft_recipe_from_spec("no_such", {})
        assert not r["ok"]
    finally:
        os.chdir(old)
