"""F-C P2 aging_service 单测（service simulate/verdict/report + CLI/MCP 薄壳冒烟）。

裁判口径（#118：不自证）：漂移终值与 core.profile_integrate 直算逐位一致
（同一确定性内核同参调用）；方向性物理钉 er↑→f0↓（f0∝1/√εeff，纯函数
detune_pct_of_er_drift 单调性）+ X7R 端到端 er↓→detune>0；实测 detune 与
预测 detune 的一致性按频率栅格步长给容差（argmax 类谷位在离散栅格上量化，
#281 峰位量化同族）。

材料诚实边界按 knowledge/aging_laws.yaml 实态钉：er_aging typical 的只有
ceramic_class2_x7r（Knowles −1%/decade-hour 单源）；ro4350b/fr4/alumina/
generic 的 er_aging 均 awaiting_data → ok=False 不产数字（任务书草稿
"alumina/FR4 typical"与 yaml 实态不符，以 knowledge 只读实态为准）。
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import aging
from rfauto.service.aging_service import (
    aging_eol_verdict,
    aging_report,
    aging_simulate,
    detune_pct_of_er_drift,
)

TEN_YEARS_S = 10.0 * 365.25 * 86400.0
X7R = "ceramic_class2_x7r"
# 与 aging_laws.yaml typical 条目逐位一致（接线钉：yaml 数值喂内核得同值）
X7R_LAWS = {
    "t_use_c": 55.0,
    "ea_ev": 0.0,  # 恒温于使用温度 → AF≡1，占位值（isothermal_at_use 语义）
    "er0": 9.8,
    "aging_frac_per_decade": -0.01,
}
PATCH_PARAMS = {"patch_len_mm": 40.0, "feed_offset_mm": 10.0, "patch_w_mm": 30.0}


def _payload(**over):
    base = {
        "template": "patch_antenna",
        "params": dict(PATCH_PARAMS),
        "mission_profile": [{"t_s": TEN_YEARS_S, "t_c": 55.0}],
        "lifetime_years": 10.0,
        "laws_material": X7R,
        "er0": 9.8,
        "t_use_c": 55.0,
        "freq_ghz": [0.5, 6.0, 4001],
    }
    base.update(over)
    return base


# ─── 1. simulate：漂移轨迹与内核直算一致 + 单调 ──────────────────────────────


def test_simulate_er_drift_matches_kernel_and_monotonic():
    r = aging_simulate(_payload())
    assert r["ok"] is True
    # 终值与 core.profile_integrate 直算逐位一致（同内核同参，薄壳不改语义）
    integ = aging.profile_integrate(
        [{"t_s": TEN_YEARS_S, "t_c": 55.0}], X7R_LAWS, t_total_s=TEN_YEARS_S
    )
    assert r["drift"]["er_eol"] == integ["drift"]["er_eol"]
    assert r["drift"]["drift_frac"] == integ["drift"]["drift_frac"]
    assert r["t_equivalent_s"] == integ["t_equivalent_s"]
    # 曲线单调下降（X7R frac<0）且末点=内核轨迹末点
    curve = r["er_drift_curve"]
    assert len(curve) == 1
    assert curve[-1]["er"] == integ["trajectory"][-1]["er_t"]
    assert curve[-1]["er"] < X7R_LAWS["er0"]
    # Knowles −1%/decade × log10(87600h) ≈ −4.94%：与解析手算一致（rel 1e-9）
    expect_frac = -0.01 * __import__("math").log10(TEN_YEARS_S / 3600.0)
    assert r["drift"]["drift_frac"] == pytest.approx(expect_frac, rel=1e-9)


def test_simulate_detune_direction_end_to_end_and_grid_consistency():
    r = aging_simulate(_payload())
    assert r["ok"] is True
    # 物理方向端到端：er 下降（X7R）→ f0 上移 → detune > 0
    assert r["drift"]["er_eol"] < r["drift"]["er0"]
    assert r["f_dip_ghz"]["eol"] > r["f_dip_ghz"]["nominal"]
    assert r["detune_pct"] > 0.0
    assert r["detune_pct_predicted"] > 0.0
    # 实测 vs 预测：差异 ≤ 2 个频率栅格步（谷位 argmin 在离散栅格上量化）
    df = (6.0 - 0.5) / (4001 - 1)
    tol_pct = 2.0 * df / r["f_dip_ghz"]["nominal"] * 100.0
    assert abs(r["detune_pct"] - r["detune_pct_predicted"]) <= tol_pct


def test_detune_mapping_direction_pure_function():
    # 物理方向纯函数钉：εr↑ → f0↓（负失谐）；εr↓ → 正；不变 → 逐位 0
    assert detune_pct_of_er_drift(9.8, 10.3) < 0.0
    assert detune_pct_of_er_drift(9.8, 9.3) > 0.0
    assert detune_pct_of_er_drift(9.8, 9.8) == 0.0
    # 单调：漂移越大失谐越远
    assert detune_pct_of_er_drift(9.8, 9.0) > detune_pct_of_er_drift(9.8, 9.5)
    # 恒等式：f0 比值 = √(εeff_nom/εeff_eol)
    import math

    q = 0.7
    d = detune_pct_of_er_drift(4.0, 4.4, fill_fraction=q)
    expect = (math.sqrt((1 + q * 3.0) / (1 + q * 3.4)) - 1.0) * 100.0
    assert d == pytest.approx(expect, rel=1e-12)
    with pytest.raises(ValueError):
        detune_pct_of_er_drift(9.8, 9.3, fill_fraction=0.0)
    with pytest.raises(ValueError):
        detune_pct_of_er_drift(9.8, 9.3, fill_fraction=1.1)


# ─── 2. simulate：诚实边界（awaiting/引擎/参数） ─────────────────────────────


@pytest.mark.parametrize(
    "material",
    [
        "laminate_ro4350b",
        "laminate_fr4",
        "ceramic_alumina_99p6",
        "generic_jesd85",
    ],
)
def test_simulate_awaiting_material_produces_no_numbers(material):
    r = aging_simulate(_payload(laws_material=material))
    assert r["ok"] is False
    assert any("awaiting_data" in e for e in r["errors"])
    # 不产数字：漂移/S 参数/失谐键全部缺席
    for key in ("detune_pct", "er_drift_curve", "s_params_nominal", "s_params_eol"):
        assert key not in r
    assert r["laws_provenance"]["material_id"] == material
    assert r["laws_provenance"]["er_aging"]["status"] == "awaiting_data"


def test_simulate_off_use_temperature_with_arrhenius_awaiting_rejected():
    # X7R arrhenius awaiting + 剖面含 125°C 段 → 无法折算等效时间，不产数字
    r = aging_simulate(_payload(
        mission_profile=[
            {"t_s": 1e7, "t_c": 55.0},
            {"t_s": 1e6, "t_c": 125.0},
        ],
        t_total_s=1.1e7,
        lifetime_years=None,
    ))
    assert r["ok"] is False
    assert any("arrhenius" in e for e in r["errors"])
    assert "detune_pct" not in r


def test_simulate_engine_unsupported():
    r = aging_simulate(_payload(engine="hfss"))
    assert r["ok"] is False
    assert any("unsupported" in e for e in r["errors"])
    r2 = aging_simulate(_payload(engine="openems"))
    assert r2["ok"] is False


def test_simulate_template_guards():
    # 未注册模板
    r = aging_simulate(_payload(template="no_such_template"))
    assert r["ok"] is False
    assert any("未注册" in e for e in r["errors"])
    # TL 族（mline）fake 模型 v1 不支持（无长度驱动谷位）
    r2 = aging_simulate(_payload(template="mline"))
    assert r2["ok"] is False
    assert any("v1 不支持" in e for e in r2["errors"])


def test_simulate_param_guards():
    # 缺谐振长度变量（等效伸缩编码必须有真柄）
    r = aging_simulate(_payload(params={"patch_w_mm": 30.0}))
    assert r["ok"] is False
    assert any("谐振长度" in e for e in r["errors"])
    # lifetime 二选一
    r2 = aging_simulate(_payload(t_total_s=TEN_YEARS_S))
    assert r2["ok"] is False
    r3 = aging_simulate(_payload(lifetime_years=None))
    assert r3["ok"] is False
    # fill_fraction 域外
    r4 = aging_simulate(_payload(fill_fraction=1.5))
    assert r4["ok"] is False
    # 非对象 payload → service 面自身收敛 ok=False 信封（F-11/S3：原裸
    # ValueError 靠 MCP 薄壳层兜——与全模块「不抛穿」口径统一）
    assert aging_simulate([1, 2, 3])["ok"] is False
    assert aging_simulate(None)["ok"] is False


def test_simulate_fill_fraction_scales_detune():
    # q<1 → εeff 漂移被稀释 → 失谐量单调缩小（一阶填充口径自洽）
    r_full = aging_simulate(_payload(freq_ghz=[0.5, 6.0, 801]))
    r_dil = aging_simulate(_payload(fill_fraction=0.5, freq_ghz=[0.5, 6.0, 801]))
    assert r_full["ok"] and r_dil["ok"]
    assert r_dil["detune_pct_predicted"] < r_full["detune_pct_predicted"]


# ─── 3. verdict：恰等容差 + 双口径 ───────────────────────────────────────────


def test_verdict_exact_equality_is_pass_ge1_boundary():
    # ge1③ 恰等容差口径：|detune| == spec → PASS（margin 恰 0）
    v = aging_eol_verdict({"detune_pct": 2.0, "spec_pct": 2.0})
    assert v["ok"] is True
    assert v["verdict"] == "PASS"
    assert v["margin_pct"] == 0.0
    v_neg = aging_eol_verdict({"detune_pct": -2.0, "spec_pct": 2.0})
    assert v_neg["verdict"] == "PASS"
    # 略超 → FAIL
    assert aging_eol_verdict({"detune_pct": 2.0000001, "spec_pct": 2.0})["verdict"] == "FAIL"
    assert aging_eol_verdict({"detune_pct": 0.0, "spec_pct": 0.0})["verdict"] == "PASS"


def test_verdict_ppm_and_simulate_passthrough():
    # ppm 口径：20000 ppm = 2%
    v = aging_eol_verdict({"detune_pct": 2.0, "spec_ppm": 20000})
    assert v["verdict"] == "PASS"
    assert v["spec_pct"] == pytest.approx(2.0)
    v2 = aging_eol_verdict({"detune_pct": 2.5, "spec_ppm": 20000})
    assert v2["verdict"] == "FAIL"
    # simulate 结果包装透传
    r = aging_simulate(_payload())
    v3 = aging_eol_verdict({"simulate": r, "spec_pct": abs(r["detune_pct"])})
    assert v3["verdict"] == "PASS"
    v4 = aging_eol_verdict({"simulate_result": r, "spec_pct": abs(r["detune_pct"]) / 2})
    assert v4["verdict"] == "FAIL"
    # 错误面
    assert aging_eol_verdict({"detune_pct": 1.0, "spec_pct": 1.0, "spec_ppm": 1e4})["ok"] is False
    assert aging_eol_verdict({"detune_pct": 1.0})["ok"] is False
    assert aging_eol_verdict({"spec_pct": 1.0})["ok"] is False
    assert aging_eol_verdict({"detune_pct": 1.0, "spec_pct": -0.1})["ok"] is False


# ─── 4. report：sections 齐全 + provenance ───────────────────────────────────


def test_report_sections_complete_with_provenance():
    r = aging_simulate(_payload())
    rep = aging_report({"simulate_result": r})
    assert rep["ok"] is True
    sections = rep["sections"]
    assert set(sections) == {"mission_profile", "drift_trajectory", "eol_verdict", "provenance"}
    # 剖面表回显
    assert sections["mission_profile"]["rows"][0]["t_c"] == 55.0
    assert sections["mission_profile"]["t_total_s"] == TEN_YEARS_S
    # 漂移轨迹节含 er0/er_eol/失谐
    assert sections["drift_trajectory"]["er0"] == 9.8
    assert sections["drift_trajectory"]["detune_pct"] == r["detune_pct"]
    # 措辞钉：非认证寿命结论（F-C §4 风险④）
    assert "非认证寿命结论" in rep["disclaimer"]
    # provenance：laws 出处 + awaiting 状态面
    prov = sections["provenance"]
    assert prov["laws_source"].endswith("aging_laws.yaml")
    assert prov["laws_schema"] == "aging_laws/v1"
    assert prov["material_id"] == X7R
    assert prov["er_aging"]["status"] == "typical"
    assert "Knowles" in prov["er_aging"]["provenance"]
    assert prov["arrhenius"]["status"] == "awaiting_data"
    assert prov["isothermal_at_use"] is True
    assert prov["kernel"] == "rfauto.core.aging（F-C.1；三律+Miner+profile_integrate）"


def test_report_verdict_unknown_without_spec_and_fail_with_spec():
    r = aging_simulate(_payload())
    rep = aging_report({"simulate_result": r})
    assert rep["sections"]["eol_verdict"]["verdict"] == "UNKNOWN"
    rep2 = aging_report({"simulate_result": r, "spec_pct": 0.001})
    assert rep2["sections"]["eol_verdict"]["verdict"] == "FAIL"
    rep3 = aging_report({"simulate_result": r, "spec_pct": 100.0})
    assert rep3["sections"]["eol_verdict"]["verdict"] == "PASS"
    # simulate_payload 现场跑 + simulate 失败如实透传
    rep4 = aging_report({"simulate_payload": _payload()})
    assert rep4["ok"] is True
    rep5 = aging_report({"simulate_payload": _payload(laws_material="laminate_fr4")})
    assert rep5["ok"] is False
    assert rep5["sections"] is None
    # F-11/S3：非 dict payload 收敛为失败信封（原裸 raise，统一后不抛穿）
    assert aging_report("not-a-dict")["ok"] is False
    assert aging_report({})["ok"] is False


# ─── 5. CLI 三命令冒烟（typer CliRunner 真入口） ─────────────────────────────


def _write_json(tmp_path: Path, name: str, data) -> str:
    p = tmp_path / name
    p.write_text(json.dumps(data), encoding="utf-8")
    return str(p)


def test_cli_aging_three_commands_smoke(tmp_path):
    from typer.main import get_command
    from typer.testing import CliRunner

    from rfauto.cli.main import app

    runner = CliRunner()
    # 注册面：aging 子应用三命令在位
    cmd = get_command(app)
    assert {"simulate", "verdict", "report"} <= set(cmd.commands["aging"].commands)

    sim_path = _write_json(tmp_path, "sim.json", _payload(freq_ghz=[0.5, 6.0, 401]))
    res = runner.invoke(app, ["aging", "simulate", sim_path])
    assert res.exit_code == 0, res.output
    assert '"detune_pct"' in res.output
    assert '"laws_provenance"' in res.output
    detune = json.loads(res.output[res.output.index("{"):])["detune_pct"]

    v_path = _write_json(tmp_path, "v.json",
                         {"detune_pct": detune, "spec_pct": abs(detune)})
    res2 = runner.invoke(app, ["aging", "verdict", v_path])
    assert res2.exit_code == 0
    assert '"verdict": "PASS"' in res2.output

    r_path = _write_json(tmp_path, "rep.json",
                         {"simulate_payload": _payload(), "spec_pct": 100.0})
    res3 = runner.invoke(app, ["aging", "report", r_path])
    assert res3.exit_code == 0
    assert '"provenance"' in res3.output and '"disclaimer"' in res3.output

    # awaiting 材料 → ok=False 退出码 1（_emit 契约）
    a_path = _write_json(tmp_path, "await.json",
                         _payload(laws_material="laminate_fr4"))
    res4 = runner.invoke(app, ["aging", "simulate", a_path])
    assert res4.exit_code == 1
    assert "awaiting_data" in res4.output


# ─── 6. MCP 注册冒烟 ─────────────────────────────────────────────────────────


def test_mcp_aging_tools_registered():
    from rfauto.mcp_server import mcp

    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    assert {"aging_simulate", "aging_verdict", "aging_report"} <= names


def test_mcp_aging_tools_callable_envelope():
    # 直接调用工具函数体（薄壳转发 + 异常信封）
    from rfauto.mcp_server import aging_report, aging_simulate, aging_verdict

    sim = aging_simulate(_payload(freq_ghz=[0.5, 6.0, 201]))
    assert sim["ok"] is True and "detune_pct" in sim
    assert aging_verdict({"detune_pct": 1.0, "spec_pct": 1.0})["verdict"] == "PASS"
    rep = aging_report({"simulate_result": sim})
    assert rep["ok"] is True and "provenance" in rep["sections"]
    # 非法 payload → ok=False 信封不抛出（不炸会话）
    assert aging_simulate(None)["ok"] is False
    assert aging_verdict(None)["ok"] is False
    assert aging_report(None)["ok"] is False


# ─── S3 F-11：非 dict payload 收敛为失败信封（glass_weave 同款 try 收敛）────

@pytest.mark.parametrize("bad", [None, 123, "str", [1, 2]])
def test_non_dict_payload_returns_envelope_not_raise(bad):
    """F-11/S3：三入口非 dict payload → ok=False 信封，不再裸 ValueError
    穿透（与全模块「ok/errors 不抛穿」口径统一；MCP 薄壳原靠自身 try 兜
    ——service 面自身也不再依赖上层兜底）。"""
    from rfauto.service.aging_service import (
        aging_eol_verdict,
        aging_report,
        aging_simulate,
    )

    r1 = aging_simulate(bad)
    assert r1["ok"] is False and r1["errors"]
    r2 = aging_eol_verdict(bad)
    assert r2["ok"] is False and r2["errors"]
    r3 = aging_report(bad)
    assert r3["ok"] is False and r3["errors"]
