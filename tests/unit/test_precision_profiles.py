"""XC-P 精度档案锚树（specs 规格深案 §B-3，2026-10-02）。

五面锚（specs §B-3 载体裁决=三载体缺一即漂移）：
1. KD-1 同款收集器——YAML 键集 × KERNEL_MODULES 键集 × 各内核 docstring
   「精度档案」镜像行逐条对照（behavior/last_verified 逐字一致，防漂移）；
2. 查询函数 precision_profile 域内/域外行为三分支（REFUSE→ValueError /
   WARN→注记 / UNVERIFIED 如实不判）+ 不可判（in_domain=None 不抛）；
3. schema 负例（缺键/多键/坏枚举/铁律 7 双向钉 band=UNVERIFIED ⟺ unverified）；
4. 能力卡「精度域」节数据面（10 内核镜像全通 + 未知 kernel 如实降级）；
5. 路径发现（显式 > env 设置即信 > canonical）。

铁律 7 锚：本测试零物理数字断言——只核对"档案声明与 docstring 声明一致"
与"查询行为语义正确"；典型偏差数值本身由各内核自己的单测门（文献锚/FEM
裁判）看管，本档案是声明面不是数值裁判。
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
import yaml

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.core.precision_profiles import (
    KERNEL_MODULES,
    PRECISION_MARKER_RE,
    PRECISION_PROFILES_ENV,
    PrecisionProfileSchemaError,
    capability_card_precision_section,
    default_precision_profiles_yaml_path,
    docstring_marker_line,
    domain_ok,
    load_precision_profiles,
    precision_profile,
    resolve_precision_profiles_yaml_path,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_YAML_PATH = _REPO_ROOT / "knowledge" / "precision_profiles.yaml"


@pytest.fixture(scope="module")
def profiles() -> dict:
    return load_precision_profiles(_YAML_PATH)


# ─── 1. KD-1 同款收集器：YAML × KERNEL_MODULES × docstring 镜像逐条对照 ──────

def test_collector_yaml_keys_match_kernel_modules(profiles):
    """三源键集双向一致：YAML ↔ KERNEL_MODULES（缺/多任一侧即漂移）。"""
    assert set(profiles["kernels"]) == set(KERNEL_MODULES), (
        f"YAML-only: {sorted(set(profiles['kernels']) - set(KERNEL_MODULES))}; "
        f"module-map-only: {sorted(set(KERNEL_MODULES) - set(profiles['kernels']))}")
    assert len(profiles["kernels"]) == 10, "首批 10 内核口径（§B-3 清单）"


def test_collector_docstring_mirror_per_kernel(profiles):
    """每内核：docstring 恰一个镜像行且 kernel_id/behavior/date 与 YAML 逐字一致。"""
    for kernel_id, spec in profiles["kernels"].items():
        module = importlib.import_module(KERNEL_MODULES[kernel_id])
        marker = docstring_marker_line(module)
        assert marker is not None, (
            f"{kernel_id}: 模块 docstring 缺「精度档案」镜像行（或有多行）")
        assert marker["kernel_id"] == kernel_id
        assert marker["behavior"] == spec["out_of_domain_behavior"], kernel_id
        assert marker["last_verified"] == spec["last_verified"], kernel_id
        assert marker["line"].startswith("精度档案：knowledge/precision_profiles.yaml#")


def test_collector_no_orphan_or_duplicate_markers(profiles):
    """跨 10 模块扫全部镜像行：总数=键数、无孤儿（镜像指向不存在的键）。"""
    seen: dict[str, int] = {}
    for kernel_id, dotted in KERNEL_MODULES.items():
        module = importlib.import_module(dotted)
        doc = module.__doc__ or ""
        hits = [m.group("kernel_id") for m in PRECISION_MARKER_RE.finditer(doc)]
        assert len(hits) == 1, f"{kernel_id}: docstring 镜像行恰 1 个，得到 {hits}"
        seen[kernel_id] = seen.get(kernel_id, 0) + len(hits)
    assert set(seen) == set(profiles["kernels"])
    assert sum(seen.values()) == len(profiles["kernels"])


# ─── 2. 查询函数：域内 / 域外三分支 / 不可判 ─────────────────────────────────

def test_query_in_domain_returns_verified_band(profiles):
    r = precision_profile("ridged_waveguide", "cutoff_kc",
                          {"g_over_b": 0.9}, profiles=profiles)
    assert r["in_domain"] is True
    assert r["behavior"] == "in_domain"
    assert r["warning"] is None
    matched = [d for d in r["typical_dev"] if d["quantity"] == "cutoff_kc"]
    assert len(matched) == 1
    assert matched[0]["direction"] == "overestimate"
    assert matched[0]["unverified"] is False


def test_query_quantity_scoped_unverified_entry(profiles):
    """z_pv：档案如实登记 UNVERIFIED（对 Cohn 曲线无独立锚）。"""
    r = precision_profile("ridged_waveguide", "z_pv_ohm",
                          {"g_over_b": 0.9}, profiles=profiles)
    assert r["in_domain"] is True
    assert r["unverified"] is True
    assert [d["band"] for d in r["typical_dev"]] == ["UNVERIFIED"]


def test_query_kernel_level_entries_match_any_quantity(profiles):
    r = precision_profile("bounds", "cohn_il_lower_bound", None, profiles=profiles)
    bands = {d["quantity"] for d in r["typical_dev"]}
    assert bands == {None}


def test_query_out_of_domain_warn(profiles):
    """深脊 g/b<0.4 定量不可信 → WARN 注记（不抛，调用方自知）。"""
    r = precision_profile("ridged_waveguide", "cutoff_kc",
                          {"g_over_b": 0.3}, profiles=profiles)
    assert r["in_domain"] is False
    assert r["behavior"] == "WARN"
    assert r["warning"] is not None and "域外" in r["warning"]


def test_query_out_of_domain_refuse_raises(profiles):
    """coupled s/h<0.1 → REFUSE 抛 ValueError（CALC 入口守卫口径）。"""
    with pytest.raises(ValueError, match="确认域外"):
        precision_profile("coupled_microstrip", "coupling_k",
                          {"s_over_h": 0.05}, profiles=profiles)


def test_query_out_of_domain_unverified_honest(profiles):
    """etch θ≥90° 域外 → UNVERIFIED 如实不判（不编数、不冒充 FAIL）。"""
    r = precision_profile("etch_trapezoid", "delta_z_estimate",
                          {"etch_angle_deg": 95.0, "w_top_mm": 0.2,
                           "t_cu_mm": 0.035}, profiles=profiles)
    assert r["in_domain"] is False
    assert r["behavior"] == "UNVERIFIED"
    assert r["unverified"] is True


def test_query_indeterminable_point_never_raises(profiles):
    """缺域变量/无条件可判 → in_domain=None 不抛（不可判≠确认域外）。"""
    r1 = precision_profile("bounds", "chu_q_bound", None, profiles=profiles)
    assert r1["in_domain"] is None
    r2 = precision_profile("coupled_microstrip", "coupling_k", None,
                           profiles=profiles)
    assert r2["in_domain"] is None  # REFUSE 内核也不可判抛——缺变量不是域外证据
    r3 = precision_profile("ridged_waveguide", "cutoff_kc",
                           {"g_over_b": True}, profiles=profiles)
    assert r3["in_domain"] is None  # bool 域变量按缺失处理（df7+⑯）


def test_query_domain_boundary_conditions(profiles):
    """机器判域边界逐 op 钉（恰等不炸——#347 家族边界留显式语义）。"""
    assert domain_ok({"etch_angle_deg": 90.0, "w_top_mm": 0.2, "t_cu_mm": 0.035},
                     profiles["kernels"]["etch_trapezoid"]["valid_domain"]) is False
    assert domain_ok({"etch_angle_deg": 89.999, "w_top_mm": 0.2, "t_cu_mm": 0.035},
                     profiles["kernels"]["etch_trapezoid"]["valid_domain"]) is True
    assert domain_ok({"g_over_b": 0.4}, profiles["kernels"]["ridged_waveguide"]["valid_domain"]) is True
    assert domain_ok({"g_over_b": 1.0}, profiles["kernels"]["ridged_waveguide"]["valid_domain"]) is True


def test_query_extra_point_keys_ignored(profiles):
    r = precision_profile("ridged_waveguide", "cutoff_kc",
                          {"g_over_b": 0.75, "unrelated": 42},
                          profiles=profiles)
    assert r["in_domain"] is True


def test_query_unknown_kernel_and_quantity(profiles):
    with pytest.raises(ValueError, match="可用"):
        precision_profile("no_such_kernel", "x", None, profiles=profiles)
    with pytest.raises(ValueError, match="无 quantity"):
        precision_profile("ridged_waveguide", "no_such_quantity", None,
                          profiles=profiles)


# ─── 3. schema 负例（判定单点=_validate_kernel 经 load_precision_profiles）───

_VALID_MIN: dict = {
    "schema_version": 1,
    "kernels": {
        "demo_kernel": {
            "quantities": ["q_a", "q_b"],
            "valid_domain": {
                "point_params": ["x"],
                "conditions": [{"param": "x", "op": ">=", "value": 0.1}],
                "note": "演示域",
            },
            "typical_deviation": [
                {"quantity": "q_a", "band": "≤1%", "direction": "none",
                 "condition": "测试锚", "unverified": False},
                {"quantity": None, "band": "UNVERIFIED", "direction": "unknown",
                 "condition": "未定级", "unverified": True},
            ],
            "refs": ["Test Ref 2026"],
            "out_of_domain_behavior": "WARN",
            "last_verified": "2026-10-02",
        }
    },
}


def _write_and_load(tmp_path: Path, data: dict) -> None:
    p = tmp_path / "pp.yaml"
    p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    load_precision_profiles(p)


def test_schema_valid_minimum_loads(tmp_path):
    _write_and_load(tmp_path, _VALID_MIN)  # 不抛即过


def test_schema_negative_missing_and_extra_keys(tmp_path):
    import copy
    bad = copy.deepcopy(_VALID_MIN)
    del bad["kernels"]["demo_kernel"]["refs"]
    with pytest.raises(PrecisionProfileSchemaError, match="缺 schema 必需键"):
        _write_and_load(tmp_path, bad)
    bad2 = copy.deepcopy(_VALID_MIN)
    bad2["kernels"]["demo_kernel"]["vendor"] = "x"
    with pytest.raises(PrecisionProfileSchemaError, match="多余键"):
        _write_and_load(tmp_path, bad2)


def test_schema_negative_bad_behavior_and_op(tmp_path):
    import copy
    bad = copy.deepcopy(_VALID_MIN)
    bad["kernels"]["demo_kernel"]["out_of_domain_behavior"] = "SILENT"
    with pytest.raises(PrecisionProfileSchemaError, match="out_of_domain_behavior"):
        _write_and_load(tmp_path, bad)
    bad2 = copy.deepcopy(_VALID_MIN)
    bad2["kernels"]["demo_kernel"]["valid_domain"]["conditions"][0]["op"] = "!="
    with pytest.raises(PrecisionProfileSchemaError, match="op"):
        _write_and_load(tmp_path, bad2)


def test_schema_negative_quantities(tmp_path):
    import copy
    bad = copy.deepcopy(_VALID_MIN)
    bad["kernels"]["demo_kernel"]["quantities"] = []
    with pytest.raises(PrecisionProfileSchemaError, match="quantities"):
        _write_and_load(tmp_path, bad)
    bad2 = copy.deepcopy(_VALID_MIN)
    bad2["kernels"]["demo_kernel"]["quantities"] = ["q_a", "q_a"]
    with pytest.raises(PrecisionProfileSchemaError, match="唯一"):
        _write_and_load(tmp_path, bad2)


def test_schema_negative_unverified_bidirectional_pin(tmp_path):
    """铁律 7 双向钉：band=UNVERIFIED ⟺ unverified=true（两向各自打红）。"""
    import copy
    bad = copy.deepcopy(_VALID_MIN)
    bad["kernels"]["demo_kernel"]["typical_deviation"][1]["unverified"] = False
    with pytest.raises(PrecisionProfileSchemaError, match="双向一致"):
        _write_and_load(tmp_path, bad)
    bad2 = copy.deepcopy(_VALID_MIN)
    bad2["kernels"]["demo_kernel"]["typical_deviation"][0]["unverified"] = True
    with pytest.raises(PrecisionProfileSchemaError, match="双向一致"):
        _write_and_load(tmp_path, bad2)


def test_schema_negative_direction_vocabulary(tmp_path):
    import copy
    bad = copy.deepcopy(_VALID_MIN)
    bad["kernels"]["demo_kernel"]["typical_deviation"][0]["direction"] = "大概偏高"
    with pytest.raises(PrecisionProfileSchemaError, match="受控词表"):
        _write_and_load(tmp_path, bad)


def test_schema_negative_deviation_quantity_scope(tmp_path):
    import copy
    bad = copy.deepcopy(_VALID_MIN)
    bad["kernels"]["demo_kernel"]["typical_deviation"][0]["quantity"] = "q_x"
    with pytest.raises(PrecisionProfileSchemaError, match="不在 quantities"):
        _write_and_load(tmp_path, bad)


def test_schema_negative_empty_domain_and_bad_date(tmp_path):
    import copy
    bad = copy.deepcopy(_VALID_MIN)
    bad["kernels"]["demo_kernel"]["valid_domain"] = {"point_params": []}
    with pytest.raises(PrecisionProfileSchemaError, match="conditions 或 note"):
        _write_and_load(tmp_path, bad)
    bad2 = copy.deepcopy(_VALID_MIN)
    bad2["kernels"]["demo_kernel"]["last_verified"] = "2026-13-40"
    with pytest.raises(PrecisionProfileSchemaError):
        _write_and_load(tmp_path, bad2)


def test_schema_negative_condition_shape_and_bool_value(tmp_path):
    import copy
    bad = copy.deepcopy(_VALID_MIN)
    bad["kernels"]["demo_kernel"]["valid_domain"]["conditions"][0] = {"param": "x"}
    with pytest.raises(PrecisionProfileSchemaError, match="conditions"):
        _write_and_load(tmp_path, bad)
    bad2 = copy.deepcopy(_VALID_MIN)
    bad2["kernels"]["demo_kernel"]["valid_domain"]["conditions"][0]["value"] = True
    with pytest.raises(PrecisionProfileSchemaError, match="value"):
        _write_and_load(tmp_path, bad2)


def test_schema_negative_empty_deviation_list(tmp_path):
    import copy
    bad = copy.deepcopy(_VALID_MIN)
    bad["kernels"]["demo_kernel"]["typical_deviation"] = []
    with pytest.raises(PrecisionProfileSchemaError, match="typical_deviation"):
        _write_and_load(tmp_path, bad)


def test_real_yaml_unverified_entries_are_honest(profiles):
    """实档面统计锚：首批 10 内核每档要么有出处分档要么如实 UNVERIFIED；
    本锚钉"UNVERIFIED 计数>0 的内核集合"与档案一致（防后人悄悄改口凑数）。"""
    unv_by_kernel = {
        kid: sum(1 for d in spec["typical_deviation"] if d["unverified"])
        for kid, spec in profiles["kernels"].items()}
    assert unv_by_kernel == {
        "ridged_waveguide": 1, "etch_trapezoid": 2, "conductor_loss": 1,
        "dielectric_extract": 1, "synthesis.forward_z0": 2,
        "coupled_microstrip": 0, "high_power": 2, "bounds": 1,
        "thermal_iteration": 1, "shield_cavity_mode": 1}


# ─── 4. 能力卡「精度域」节数据面 ─────────────────────────────────────────────

def test_capability_card_section_all_ten(profiles):
    for kernel_id in profiles["kernels"]:
        card = capability_card_precision_section(kernel_id, profiles=profiles)
        assert card["ok"] is True
        assert card["section"] == "精度域"
        assert card["out_of_domain_behavior"] in ("REFUSE", "WARN", "UNVERIFIED")
        mirror = card["docstring_mirror"]
        assert mirror["ok"] is True, kernel_id
        assert mirror["kernel_id"] == kernel_id


def test_capability_card_unknown_kernel_degrades_honestly(profiles):
    card = capability_card_precision_section("no_such_kernel", profiles=profiles)
    assert card["ok"] is False
    assert card["available"] == sorted(profiles["kernels"])


# ─── 5. 路径发现：显式 > env 设置即信 > canonical ────────────────────────────

def test_resolve_explicit_path_wins(tmp_path):
    p = tmp_path / "elsewhere.yaml"
    p.write_text("kernels: {}", encoding="utf-8")
    assert resolve_precision_profiles_yaml_path(p) == p


def test_resolve_env_set_and_trusted(monkeypatch, tmp_path):
    """env 设置即信：不存在的路径也直返（ FileNotFoundError 在读档层，不静默回退）。"""
    missing = tmp_path / "nope.yaml"
    monkeypatch.setenv(PRECISION_PROFILES_ENV, str(missing))
    assert resolve_precision_profiles_yaml_path() == missing
    with pytest.raises(FileNotFoundError):
        load_precision_profiles()
    monkeypatch.setenv(PRECISION_PROFILES_ENV, "   ")
    assert resolve_precision_profiles_yaml_path() == default_precision_profiles_yaml_path()


def test_real_yaml_default_path_resolves():
    assert resolve_precision_profiles_yaml_path() == _YAML_PATH
