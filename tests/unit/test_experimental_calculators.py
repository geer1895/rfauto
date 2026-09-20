"""实验计算器开关机制 + E13 候选公式实验态入库（2026-09-16 定案）。

口径：所有符号回归归纳公式一律 experimental=True 入库——注册表默认不列
（names/describe）、service 运行默认拒绝；显式 allow_experimental=True 或
配置 calculators.allow_experimental: true（env RFAUTO_CALCULATORS_ALLOW_
EXPERIMENTAL）放行；清单（list_calculators）始终列出但打 experimental 标签。

数值断言口径（#175）：断言函数返回值，不匹配渲染文本。E13 三点核对锚 =
归纳公式记录的系数（0.0261448 + 75.1834/L + 0.0162789·L/W），
独立裁判 = symbolic_fit.patch_resonance_hj_ghz（Hammerstad/HJ，#118 不自证），
阈值 = 归纳记录的验收门 2%。

通道钉子（#139 同源纪律）：开关相关单测清掉 env、CWD 隔离到 tmp_path（repo
configs/settings.yaml 与本机 settings.local.yaml 不参与），默认分支可复现。
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest
import yaml

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.calculators import (
    CALCULATOR_REGISTRY,
    CalculatorRegistry,
    register_symbolic_formula,
)
from rfauto.core.symbolic_fit import CandidateFormula, patch_resonance_hj_ghz
from rfauto.infra.config import load_settings
from rfauto.service.calculator_service import list_calculators, run_calculator

EXP_KEY = "patch_f0_symbolic_e13"
ENV_KEY = "RFAUTO_CALCULATORS_ALLOW_EXPERIMENTAL"

# 归纳公式记录系数（渲染文本 6 位有效数字）——三点核对的独立锚
_RECORDED_A, _RECORDED_B, _RECORDED_C = 0.0261448, 75.1834, 0.0162789
# 三个已知点（拟合数据域内：L∈[35,45]、W∈[40,60]）
_THREE_POINTS = ((35.0, 40.0), (40.0, 50.0), (45.0, 60.0))
# 数据集基底（er/h 在数据集上恒定，公式不含 er/h）
_ER, _H_MM = 3.66, 0.508


@pytest.fixture(autouse=True)
def _pin_switch_channel(tmp_path, monkeypatch):
    """钉住开关通道：无 env、CWD 无 configs/ → load_settings 走代码默认。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(ENV_KEY, raising=False)
    yield


def _recorded_f0(l_mm: float, w_mm: float) -> float:
    return _RECORDED_A + _RECORDED_B / l_mm + _RECORDED_C * l_mm / w_mm


# ─── 注册表：默认不列 / 显式含 / 标签 ─────────────────────────────────────────

def test_default_names_exclude_experimental():
    assert EXP_KEY not in CALCULATOR_REGISTRY.names()
    assert EXP_KEY in CALCULATOR_REGISTRY.names(include_experimental=True)
    assert CALCULATOR_REGISTRY.is_experimental(EXP_KEY) is True
    assert CALCULATOR_REGISTRY.is_experimental("patch_length") is False


def test_experimental_key_count_is_exactly_one():
    """本波仅 E13 一个实验键；全量计数单源取 test_calculators.EXPECTED
    （#247：全量计数禁轨内自钉——2026-09-18 slotline 两键入库时 35→37 实证）。"""
    from tests.unit.test_calculators import EXPECTED, EXPERIMENTAL_EXPECTED

    full = set(CALCULATOR_REGISTRY.names(include_experimental=True))
    default = set(CALCULATOR_REGISTRY.names())
    assert full - default == {EXP_KEY}
    assert len(EXPERIMENTAL_EXPECTED) == 1
    assert len(default) == len(EXPECTED)
    assert len(full) == len(EXPECTED) + 1


def test_describe_default_excludes_and_full_flags():
    default_names = {c["name"] for c in CALCULATOR_REGISTRY.describe()}
    assert EXP_KEY not in default_names
    full = {c["name"]: c for c in CALCULATOR_REGISTRY.describe(include_experimental=True)}
    assert full[EXP_KEY]["experimental"] is True
    assert full["patch_length"]["experimental"] is False
    # 参数自描述完整（供 UI/CLI 表单）
    required = {p["name"] for p in full[EXP_KEY]["params"] if p["required"]}
    assert required == {"l_mm", "w_mm"}


def test_get_still_reaches_experimental_spec():
    """get() 是直达取用（不受默认过滤影响）；spec 带 experimental 元数据。"""
    spec = CALCULATOR_REGISTRY.get(EXP_KEY)
    assert spec.experimental is True
    assert spec.required == ("l_mm", "w_mm")
    assert "符号回归标定产物 patch_f0" in spec.description


# ─── service 清单：默认列出但打标签 ───────────────────────────────────────────

def test_service_list_includes_experimental_with_label():
    out = list_calculators()
    assert out["ok"] is True
    by_name = {c["name"]: c for c in out["calculators"]}
    assert by_name[EXP_KEY]["experimental"] is True
    assert by_name["microstrip_analysis"]["experimental"] is False
    # 清单条数 = 全键（含实验）
    assert len(by_name) == len(CALCULATOR_REGISTRY.names(include_experimental=True))
    json.dumps(out, ensure_ascii=False)


def test_service_list_ledger_and_exclude_switch():
    """壳层透传口径：清单附实验键台账；include_experimental=
    False 剔除实验键但台账（n_experimental/experimental 名单）仍如实报告。"""
    full = list_calculators()
    assert full["include_experimental"] is True
    assert full["n_experimental"] == 1
    assert full["experimental"] == [EXP_KEY]

    slim = list_calculators(include_experimental=False)
    assert slim["ok"] is True
    assert slim["include_experimental"] is False
    names = [c["name"] for c in slim["calculators"]]
    assert EXP_KEY not in names
    assert names == CALCULATOR_REGISTRY.names()  # 默认 names() 口径（35）
    assert slim["n_experimental"] == 1
    assert slim["experimental"] == [EXP_KEY]


def test_service_run_success_envelope_carries_experimental_tag():
    exp = run_calculator(EXP_KEY, {"l_mm": 40.0, "w_mm": 50.0}, allow_experimental=True)
    assert exp["ok"] is True and exp["experimental"] is True
    regular = run_calculator("patch_length",
                             {"f0_ghz": 2.4, "epsilon_r": 3.66, "h_mm": 0.508})
    assert regular["ok"] is True and regular["experimental"] is False


# ─── service 运行：默认拒绝 / 显式开关 / 配置开关 ────────────────────────────

def test_service_run_default_rejects_experimental():
    out = run_calculator(EXP_KEY, {"l_mm": 40.0, "w_mm": 50.0})
    assert out["ok"] is False
    assert out["experimental"] is True
    assert "experimental" in out["error"]
    assert "allow_experimental" in out["error"]
    assert "calculators.allow_experimental" in out["error"]
    assert "result" not in out


def test_service_run_explicit_allow_runs():
    out = run_calculator(EXP_KEY, {"l_mm": 40.0, "w_mm": 50.0},
                         allow_experimental=True)
    assert out["ok"] is True
    assert out["result"]["f0_ghz"] == pytest.approx(_recorded_f0(40.0, 50.0), abs=1e-4)
    assert "provenance" in out["result"]
    assert "formula" in out["result"]


def test_service_run_explicit_false_rejects_even_if_config_allows(monkeypatch):
    monkeypatch.setenv(ENV_KEY, "1")
    out = run_calculator(EXP_KEY, {"l_mm": 40.0, "w_mm": 50.0},
                         allow_experimental=False)
    assert out["ok"] is False and out["experimental"] is True


@pytest.mark.parametrize("raw", ["1", "true", "TRUE", "yes", "on"])
def test_service_run_env_switch_allows(monkeypatch, raw):
    monkeypatch.setenv(ENV_KEY, raw)
    out = run_calculator(EXP_KEY, {"l_mm": 40.0, "w_mm": 50.0})
    assert out["ok"] is True, out
    assert out["result"]["f0_ghz"] == pytest.approx(_recorded_f0(40.0, 50.0), abs=1e-4)


@pytest.mark.parametrize("raw", ["0", "false", "off", "garbage"])
def test_service_run_env_falsy_or_bad_stays_closed(monkeypatch, raw):
    monkeypatch.setenv(ENV_KEY, raw)
    out = run_calculator(EXP_KEY, {"l_mm": 40.0, "w_mm": 50.0})
    assert out["ok"] is False and out["experimental"] is True


def test_service_run_yaml_switch_allows(tmp_path, monkeypatch):
    """configs/settings.yaml 的 calculators.allow_experimental: true 放行。"""
    cfg_dir = tmp_path / "configs"
    cfg_dir.mkdir()
    (cfg_dir / "settings.yaml").write_text(
        yaml.safe_dump({"calculators": {"allow_experimental": True}}),
        encoding="utf-8")
    out = run_calculator(EXP_KEY, {"l_mm": 40.0, "w_mm": 50.0})
    assert out["ok"] is True, out


def test_service_run_config_failure_falls_back_closed(monkeypatch):
    """配置读取异常一律按关闭处理（安全侧默认，best-effort 不阻塞主路径）。"""
    import rfauto.infra.config as cfg_mod

    def _boom(*_args, **_kwargs):
        raise RuntimeError("config broken")

    monkeypatch.setattr(cfg_mod, "load_settings", _boom)
    # 走配置路径 → 兜底关闭（不抛出）
    out = run_calculator(EXP_KEY, {"l_mm": 40.0, "w_mm": 50.0})
    assert out["ok"] is False and out["experimental"] is True
    # 显式开关不经配置 → 仍能跑
    ok = run_calculator(EXP_KEY, {"l_mm": 40.0, "w_mm": 50.0}, allow_experimental=True)
    assert ok["ok"] is True


def test_regular_calculators_unaffected_by_switch():
    """非实验键不受开关影响：默认/显式 False/显式 True 三态都正常跑。"""
    params = {"f0_ghz": 2.4, "epsilon_r": _ER, "h_mm": _H_MM}
    base = run_calculator("patch_length", params)
    assert base["ok"] is True
    for flag in (False, True):
        out = run_calculator("patch_length", params, allow_experimental=flag)
        assert out == base


# ─── 配置层：calculators.allow_experimental 三层优先级 ────────────────────────

def test_config_default_false(tmp_path):
    s = load_settings(tmp_path / "nope.yaml")
    assert s.calculators.allow_experimental is False


def test_config_yaml_nested_key(tmp_path):
    p = tmp_path / "settings.yaml"
    p.write_text(yaml.safe_dump({"calculators": {"allow_experimental": True}}),
                 encoding="utf-8")
    assert load_settings(p).calculators.allow_experimental is True
    # 本机 local 覆盖优先
    (tmp_path / "settings.local.yaml").write_text(
        yaml.safe_dump({"calculators": {"allow_experimental": False}}),
        encoding="utf-8")
    assert load_settings(p).calculators.allow_experimental is False


def test_config_env_beats_yaml(tmp_path, monkeypatch):
    p = tmp_path / "settings.yaml"
    p.write_text(yaml.safe_dump({"calculators": {"allow_experimental": False}}),
                 encoding="utf-8")
    monkeypatch.setenv(ENV_KEY, "true")
    assert load_settings(p).calculators.allow_experimental is True
    monkeypatch.setenv(ENV_KEY, "not-a-bool")  # 坏值保持 YAML/默认
    assert load_settings(p).calculators.allow_experimental is False


def test_config_flat_keys_untouched(tmp_path, monkeypatch):
    """加嵌套节不影响既有平铺键（回归护栏）。"""
    monkeypatch.delenv("RFAUTO_HPEESOF_DIR", raising=False)
    p = tmp_path / "settings.yaml"
    p.write_text(yaml.safe_dump({"hpeesof_dir": "C:/ads",
                                 "calculators": {"allow_experimental": True}}),
                 encoding="utf-8")
    s = load_settings(p)
    assert s.hpeesof_dir == "C:/ads"
    assert s.calculators.allow_experimental is True
    assert s.grpc_port == 50051


def test_repo_settings_yaml_declares_key_default_false():
    """仓库 configs/settings.yaml 必须声明该键且默认 false（配置与代码同 commit）。"""
    repo_yaml = Path(__file__).resolve().parents[2] / "configs" / "settings.yaml"
    data = yaml.safe_load(repo_yaml.read_text(encoding="utf-8"))
    assert data["calculators"]["allow_experimental"] is False
    assert load_settings(repo_yaml).calculators.allow_experimental is False


# ─── E13 公式：三点核对 / 适用域 / 独立裁判 / 确定性 ─────────────────────────

@pytest.mark.parametrize("l_mm,w_mm", _THREE_POINTS)
def test_e13_three_points_match_recorded_coefficients(l_mm, w_mm):
    """注册函数值 vs 归纳公式记录系数：6 位有效数字截断 → |Δ|≲1e-5GHz。"""
    spec = CALCULATOR_REGISTRY.get(EXP_KEY)
    value = spec.func(l_mm=l_mm, w_mm=w_mm)["f0_ghz"]
    assert value == pytest.approx(_recorded_f0(l_mm, w_mm), abs=1e-4)
    # 物理量级护栏：数据集基模 [1.3, 2.7] GHz
    assert 1.3 < value < 2.7


@pytest.mark.parametrize("l_mm,w_mm", _THREE_POINTS)
def test_e13_within_2pct_of_hj_referee(l_mm, w_mm):
    """独立裁判（Hammerstad/HJ 闭式，#118 不自证）：归纳记录验收门 2%。"""
    value = CALCULATOR_REGISTRY.get(EXP_KEY).func(l_mm=l_mm, w_mm=w_mm)["f0_ghz"]
    hj = patch_resonance_hj_ghz(l_mm, w_mm, _ER, _H_MM)
    assert abs(value - hj) / hj < 0.02
    # 归纳式系统性略低于 HJ（mean −0.699%）：符号方向一致
    assert value < hj


def test_e13_formula_text_matches_recorded_form():
    """公式渲染串含三项（1 / 1/L / L/W）——结构与归纳记录一致。"""
    out = CALCULATOR_REGISTRY.get(EXP_KEY).func(l_mm=40.0, w_mm=50.0)
    assert out["formula"].startswith("f0_ghz = ")
    assert "1/L_mm" in out["formula"] and "L_mm/W_mm" in out["formula"]
    assert "51" in out["provenance"] and "0.765%" in out["provenance"]


@pytest.mark.parametrize("params", [
    {"l_mm": 34.9, "w_mm": 50.0},
    {"l_mm": 45.1, "w_mm": 50.0},
    {"l_mm": 40.0, "w_mm": 39.9},
    {"l_mm": 40.0, "w_mm": 60.1},
])
def test_e13_out_of_domain_explicit_error(params):
    spec = CALCULATOR_REGISTRY.get(EXP_KEY)
    with pytest.raises(ValueError, match="适用域"):
        spec.func(**params)
    out = run_calculator(EXP_KEY, params, allow_experimental=True)
    assert out["ok"] is False and "适用域" in out["error"]


def test_e13_domain_edges_inclusive():
    spec = CALCULATOR_REGISTRY.get(EXP_KEY)
    for l_mm, w_mm in ((35.0, 40.0), (45.0, 60.0), (35.0, 60.0), (45.0, 40.0)):
        assert spec.func(l_mm=l_mm, w_mm=w_mm)["f0_ghz"] > 0


def test_e13_nonfinite_and_unknown_params_rejected():
    spec = CALCULATOR_REGISTRY.get(EXP_KEY)
    with pytest.raises(ValueError):
        spec.func(l_mm=float("nan"), w_mm=50.0)
    with pytest.raises(TypeError):
        spec.func(l_mm=40.0, w_mm=50.0, bogus=1)


def test_e13_deterministic_and_json_ready():
    a = run_calculator(EXP_KEY, {"l_mm": 42.0, "w_mm": 55.0}, allow_experimental=True)
    b = run_calculator(EXP_KEY, {"l_mm": 42.0, "w_mm": 55.0}, allow_experimental=True)
    assert json.dumps(a, sort_keys=True, allow_nan=False) == json.dumps(
        b, sort_keys=True, allow_nan=False)


# ─── 通用登记入口 register_symbolic_formula ──────────────────────────────────

def _toy_candidate(terms, coefficients):
    return CandidateFormula(
        terms=tuple(terms), coefficients=tuple(coefficients), complexity=1,
        mse_train=0.0, rmse_train=0.0, r2_train=1.0)


def test_register_symbolic_formula_registers_experimental_by_default():
    reg = CalculatorRegistry()
    key = register_symbolic_formula(
        _toy_candidate(("1", "x", "x^2"), (1.0, 2.0, 0.5)), "toy_quadratic",
        variables=("x",), output_key="y", provenance="toy", registry=reg)
    assert key == "toy_quadratic"
    assert reg.names() == []                       # 默认不列
    assert reg.names(include_experimental=True) == ["toy_quadratic"]
    assert reg.is_experimental("toy_quadratic") is True
    # y = 1 + 2x + 0.5x²，x=3 → 11.5（^→** 翻译 + 系数加权）
    assert reg.get("toy_quadratic").func(x=3.0)["y"] == pytest.approx(11.5)


def test_register_symbolic_formula_param_mapping_and_library_vocab():
    """build_library 全词表（sqrt/log/倒数/比值/乘积）可求值；变量名→入参名映射。"""
    reg = CalculatorRegistry()
    register_symbolic_formula(
        _toy_candidate(("sqrt(A)", "log(B)", "1/A", "A/B", "A*B"),
                       (1.0, 1.0, 1.0, 1.0, 1.0)),
        "toy_vocab", variables=("A", "B"), param_names=("a", "b"),
        output_key="z", registry=reg)
    expected = math.sqrt(4.0) + math.log(2.0) + 1.0 / 4.0 + 4.0 / 2.0 + 4.0 * 2.0
    assert reg.get("toy_vocab").func(a=4.0, b=2.0)["z"] == pytest.approx(expected)
    assert reg.get("toy_vocab").required == ("a", "b")


def test_register_symbolic_formula_domain_enforced():
    reg = CalculatorRegistry()
    register_symbolic_formula(
        _toy_candidate(("x",), (1.0,)), "toy_dom", variables=("x",),
        domain={"x": (0.0, 1.0)}, registry=reg)
    assert reg.get("toy_dom").func(x=0.5)["y"] == pytest.approx(0.5)
    with pytest.raises(ValueError, match="适用域"):
        reg.get("toy_dom").func(x=2.0)


@pytest.mark.parametrize("bad_term", [
    "x.__class__",              # 属性访问
    "__import__('os')",         # 调用非白名单函数
    "x if x else 0",            # 条件表达式
    "y",                        # 未声明变量
    "exp(x)",                   # 非白名单函数
    "[x]",                      # 容器
])
def test_register_symbolic_formula_rejects_non_whitelist_syntax(bad_term):
    """项字符串只允许 build_library 词表语法；其余显式拒绝（不进 eval）。"""
    reg = CalculatorRegistry()
    with pytest.raises(ValueError, match="不允许"):
        register_symbolic_formula(
            _toy_candidate((bad_term,), (1.0,)), "toy_bad", variables=("x",),
            registry=reg)
    assert reg.names(include_experimental=True) == []


def test_register_symbolic_formula_validates_shapes():
    reg = CalculatorRegistry()
    with pytest.raises(ValueError, match="长度不一致"):
        register_symbolic_formula(
            _toy_candidate(("x",), (1.0,)), "t1", variables=("x",),
            param_names=("a", "b"), registry=reg)
    with pytest.raises(ValueError, match="domain"):
        register_symbolic_formula(
            _toy_candidate(("x",), (1.0,)), "t2", variables=("x",),
            domain={"nope": (0.0, 1.0)}, registry=reg)
    with pytest.raises(ValueError, match="重复"):
        register_symbolic_formula(
            _toy_candidate(("x",), (1.0,)), "t3", variables=("x", "x"),
            registry=reg)
    # 重名照常拒绝
    register_symbolic_formula(_toy_candidate(("x",), (1.0,)), "dup",
                              variables=("x",), registry=reg)
    with pytest.raises(ValueError, match="重名"):
        register_symbolic_formula(_toy_candidate(("x",), (1.0,)), "dup",
                                  variables=("x",), registry=reg)


def test_global_registry_untouched_by_toy_registrations():
    """上面所有 toy 登记都走独立 registry，全局表仍是 EXPECTED+1（单源计数）。"""
    from tests.unit.test_calculators import EXPECTED

    assert len(CALCULATOR_REGISTRY.names()) == len(EXPECTED)
    assert len(CALCULATOR_REGISTRY.names(include_experimental=True)) == len(EXPECTED) + 1
