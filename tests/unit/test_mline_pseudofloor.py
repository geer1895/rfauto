"""mline MSLPort |S11| 伪底判据内核单测（H1/H2 合成钉子，零真机）。

背景：wp39 mline 工厂地貌 |S11|@2.5 反物理归因（#250 线阻抗反演）+ 引擎
自算线阻抗 ZL 新证据。本项离线重放归档 10 档实证
H1（伪底 ≡ |Γ(ZL_engine,50)|，残差 ≤0.94dB；换引擎 ZL 基后 −50dB 量级）
——真机数字归档不入库，关键量级以**合成等价**
形式钉进本文件（ZL/偏差取真机档位值构造）。
"""
from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
for p in (str(REPO / "scripts"), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from rfauto.adapters.openems_templates import (
    loaded_ratios_to_line_basis,
    render_script,
)
from rfauto.service.wp39_benchmark import (
    GAMMA_DB_FLOOR,
    H1_DOMINANCE_MIN_GAIN_DB,
    MLINE_LINE_BASIS_S11_MAX_DB,
    OPENEMS_MLINE_Z0_BIAS_BY_MESH,
    OPENEMS_MLINE_Z0_BIAS_PCT,
    engine_z0_from_hj,
    eps_eff_from_beta,
    interp_complex_at,
    judge_pseudofloor_hypothesis,
    mag_db,
    median_in_window,
    mline_landscape_health_gate,
    mline_port_match_health,
    reflection_db,
    s11_to_line_basis,
)


def _gamma(z: complex, zr: float = 50.0) -> complex:
    return (z - zr) / (z + zr)


# ── reflection_db ────────────────────────────────────────────────────────────

def test_reflection_db_synthetic_values():
    # |Γ(75,50)| = 0.2 → 20log10(0.2) = −13.9794
    assert reflection_db(75.0, 50.0) == pytest.approx(20 * math.log10(0.2), abs=1e-12)
    # 真机量级：ZL=47.64（wstep 50Ω 线引擎值，H1 预测口径）
    assert reflection_db(47.64, 50.0) == pytest.approx(
        20 * math.log10(2.36 / 97.64), abs=1e-12)


def test_reflection_db_matched_is_floor():
    assert reflection_db(50.0 + 0j, 50.0) == GAMMA_DB_FLOOR


def test_reflection_db_complex():
    g = abs(_gamma(40 + 3j))
    assert reflection_db(40 + 3j, 50.0) == pytest.approx(20 * math.log10(g), abs=1e-12)


def test_reflection_db_rejects_bad_input():
    with pytest.raises(ValueError):
        reflection_db(50.0, 0.0)
    with pytest.raises(ValueError):
        reflection_db(complex(float("nan"), 0), 50.0)


def test_mag_db_floor():
    assert mag_db(0j) == GAMMA_DB_FLOOR
    assert mag_db(0.01) == pytest.approx(-40.0)


# ── s11_to_line_basis（与 adapters helper 对拍）─────────────────────────────

def test_line_basis_identity_at_zref():
    r = 0.1 - 0.05j
    assert s11_to_line_basis(r, 50.0, 50.0) == pytest.approx(r, abs=1e-15)


def test_line_basis_pure_mismatch_vanishes_in_own_basis():
    # 语义钉子：均匀匹配线的 r11=Γ(Z,50)（带载比值=真实反射）→ 自身基下恒 0
    for z in (47.64, 44.11 + 0.01j, 58.75):
        assert abs(s11_to_line_basis(_gamma(z), z)) < 1e-15


def test_line_basis_matches_helper_diagonal():
    rng = np.random.default_rng(20260916)
    n = 8
    s = (rng.normal(size=(n, 1, 1)) + 1j * rng.normal(size=(n, 1, 1))) * 0.2
    zl = rng.uniform(35.0, 65.0, size=(n, 1))
    out = loaded_ratios_to_line_basis(s, zl, 50.0)
    for i in range(n):
        scalar = s11_to_line_basis(complex(s[i, 0, 0]), complex(zl[i, 0]), 50.0)
        assert complex(out[i, 0, 0]) == pytest.approx(scalar, abs=1e-14)


# ── 频窗中值 / 插值 ─────────────────────────────────────────────────────────

def test_median_in_window_complex_split_and_tolerance():
    f = np.linspace(2.4e9, 2.6e9, 201)
    zl = 47.0 + 0.02j
    vals = np.full(f.shape, zl, dtype=complex)
    assert median_in_window(f, vals, 2.5e9) == pytest.approx(zl, abs=1e-12)


def test_median_in_window_empty_raises():
    with pytest.raises(ValueError, match="无样本"):
        median_in_window(np.array([1e9, 1.1e9]), np.array([50.0, 50.0], dtype=complex),
                         2.5e9)


def test_interp_complex_at_linear_and_range_guard():
    f = np.array([2.4e9, 2.6e9])
    v = np.array([0.0 + 0j, 0.2 + 0.4j])
    got = interp_complex_at(f, v, 2.5e9)
    assert got.real == pytest.approx(0.1) and got.imag == pytest.approx(0.2)
    with pytest.raises(ValueError, match="越出"):
        interp_complex_at(f, v, 3.0e9)


# ── mline_port_match_health：H1/H2 合成裁决 ─────────────────────────────────

def test_health_h1_pure_mismatch():
    # 真机同构：ZL=44.11（w=1.113@1.2mm 引擎值），r11=纯失配 Γ(ZL,50)
    zl = 44.11 + 0.0j
    h = mline_port_match_health(w_mm=1.113, z0_hj_ohm=50.01,
                                zl_engine_ohm=zl, s11_raw_50=_gamma(zl))
    assert h["s11_meas_50_db"] == pytest.approx(h["s11_pred_50_db"], abs=1e-9)
    assert h["h1_residual_db"] == pytest.approx(0.0, abs=1e-9)
    assert h["s11_line_basis_db"] == GAMMA_DB_FLOOR        # 自身基下恒 0 → 夹底
    assert h["line_basis_ok"] is True and h["h1_dominant"] is True
    assert h["verdict"] == "PASS"
    assert h["z0_dev_pct"] == pytest.approx((44.11 / 50.01 - 1) * 100.0, abs=1e-12)


def test_health_h2_residual_only_h1_weak():
    # H2 合成例：ZL=50（无失配）但存在端口分解残差 r11=0.02（−34dB）
    h = mline_port_match_health(w_mm=1.113, z0_hj_ohm=50.01,
                                zl_engine_ohm=50.0 + 0j, s11_raw_50=0.02)
    assert h["s11_line_basis_db"] == pytest.approx(-33.979, abs=0.01)
    assert h["line_basis_ok"] is True
    assert h["basis_gain_db"] == pytest.approx(0.0, abs=1e-12)   # 换基不降 → H1 弱
    assert h["h1_dominant"] is False
    assert h["verdict"] == "PASS"                                 # 线基过门
    assert any("H1 弱" in r for r in h["reasons"])


def test_health_line_basis_gate_fail():
    # 残差 0.05（−26dB）> 门 −30dB：端口分解残差不可接受
    h = mline_port_match_health(w_mm=1.4, z0_hj_ohm=43.15,
                                zl_engine_ohm=39.5 + 0j, s11_raw_50=0.05)
    assert h["line_basis_ok"] is False and h["verdict"] == "FAIL"
    assert any("超门" in r for r in h["reasons"])


def test_health_gain_threshold_h1_min_gain_db():
    # r11 = k·Γ(ZL,50)：换基是 Möbius 变换（S(kΓ) ≠ (1−k)S(Γ)），增益无闭式
    # k/(1−k)——断言改为：50Ω 基 meas=k·|Γ| 精确；gain 随 k 单调增；
    # h1_dominant 的方向（k→1 全失配 → True；k 小残差主导 → False）。
    zl = 44.0 + 0j
    g_mag = abs(_gamma(zl))
    gains = {}
    for k, expect_h1 in ((0.95, True), (0.7, True), (0.5, False), (0.3, False)):
        h = mline_port_match_health(w_mm=1.113, z0_hj_ohm=50.01,
                                    zl_engine_ohm=zl, s11_raw_50=k * _gamma(zl))
        assert h["s11_meas_50_db"] == pytest.approx(20 * math.log10(k * g_mag),
                                                    abs=1e-9)
        gains[k] = h["basis_gain_db"]
        assert h["h1_dominant"] is expect_h1, (k, h["basis_gain_db"],
                                               h["line_basis_ok"])
    assert gains[0.95] > gains[0.7] > gains[0.5] > gains[0.3]
    assert gains[0.3] < H1_DOMINANCE_MIN_GAIN_DB <= gains[0.7]


def test_health_input_validation():
    with pytest.raises(ValueError):
        mline_port_match_health(w_mm=1.0, z0_hj_ohm=0.0,
                                zl_engine_ohm=50.0, s11_raw_50=0.0)
    with pytest.raises(ValueError):
        mline_port_match_health(w_mm=1.0, z0_hj_ohm=50.0,
                                zl_engine_ohm=-1.0, s11_raw_50=0.0)


# ── judge_pseudofloor_hypothesis 聚合裁决 ───────────────────────────────────

def _row(h1: bool, line_ok: bool = True, dev: float = -9.0) -> dict:
    return {"h1_dominant": h1, "line_basis_ok": line_ok, "z0_dev_pct": dev}


def test_judge_h1_all_dominant():
    out = judge_pseudofloor_hypothesis([_row(True, dev=-11.8), _row(True, dev=-8.4),
                                        _row(True, dev=-7.2)])
    assert out["verdict"] == "H1"
    assert out["n_h1_dominant"] == 3 and out["n_rows"] == 3
    assert out["z0_dev_pct_mean"] == pytest.approx((-11.8 - 8.4 - 7.2) / 3)


def test_judge_h2_when_no_h1_and_line_gate_breached():
    out = judge_pseudofloor_hypothesis([_row(False, line_ok=False),
                                        _row(False, line_ok=False)])
    assert out["verdict"] == "H2"


def test_judge_mixed():
    out = judge_pseudofloor_hypothesis([_row(True), _row(False, line_ok=False)])
    assert out["verdict"] == "MIXED"


def test_judge_empty_raises():
    with pytest.raises(ValueError):
        judge_pseudofloor_hypothesis([])


# ── mline_landscape_health_gate 的 port_match 可选融合（向后兼容）───────────

def _health_h1_like() -> dict:
    zl = 44.11 + 0.0j
    return mline_port_match_health(w_mm=1.113, z0_hj_ohm=50.01,
                                   zl_engine_ohm=zl, s11_raw_50=_gamma(zl))


def test_gate_without_port_match_backward_compatible():
    gate = mline_landscape_health_gate(
        [0.85, 1.113, 1.4], [2.847, 2.918, 2.959],
        nominal_w=1.113, eps_hj=2.85264)
    assert gate["verdict"] == "PASS"
    assert gate["port_match_ok"] is None and gate["port_match"] is None


def test_gate_with_port_match_three_way_verdict():
    kwargs = dict(w_list=[0.85, 1.113, 1.4], eps_list=[2.847, 2.918, 2.959],
                  nominal_w=1.113, eps_hj=2.85264)
    ok = mline_landscape_health_gate(port_match=_health_h1_like(), **kwargs)
    assert ok["verdict"] == "PASS" and ok["port_match_ok"] is True
    bad = mline_landscape_health_gate(
        port_match={"line_basis_ok": False, "s11_line_basis_db": -26.0,
                    "line_basis_max_db": MLINE_LINE_BASIS_S11_MAX_DB}, **kwargs)
    assert bad["verdict"] == "FAIL" and bad["port_match_ok"] is False
    assert any("ZL 基匹配超门" in r for r in bad["reasons"])
    # εeff 两门保持原语义：port_match 过但 εeff 非单调仍 FAIL
    nonmono = mline_landscape_health_gate(
        w_list=[0.85, 1.113, 1.4], eps_list=[2.9, 2.85, 2.96],
        nominal_w=1.113, eps_hj=2.85264,
        port_match=_health_h1_like())
    assert nonmono["verdict"] == "FAIL" and nonmono["monotonic_ok"] is False


# ── 档位经验偏差表（真机拟合、可复算、不进 HJ 内核）────────────────────────

def test_z0_bias_table_mesh_monotone_toward_zero():
    # H1 机理=阶梯化随网格收敛：细网格 |偏差| 更小，全为负号。
    # 注意可比性：1.2/0.8 档为三宽度均值、auto(1.1405)/0.6/0.4/0.25/0.2 为
    # w=1.113 单宽度——只对同口径（三宽度均值两档 + 最细单宽度档）断链。
    t = OPENEMS_MLINE_Z0_BIAS_BY_MESH
    assert all(v < 0.0 for v in t.values())
    # 细网格收敛链（w=1.113 单宽度；0.2mm 真机判定"随网格收敛非固定平台"）
    assert abs(t[0.2]) < abs(t[0.25]) < abs(t[0.4]) < abs(t[0.6]) < abs(t[1.1405])
    assert abs(t[0.25]) < abs(t[0.8]) < abs(t[1.2])   # 多宽度均值档同向


def test_z0_bias_table_factory_tier_value():
    # 工厂档 1.2mm：真机三宽度均值 −10.48%（h1_check_newtpl.json 实测均值）
    assert OPENEMS_MLINE_Z0_BIAS_BY_MESH[1.2] == pytest.approx(-10.48, abs=0.01)
    # 0.2mm 最细已标定档（w=1.113 单宽度，真机 8243.6s 判定档）
    assert OPENEMS_MLINE_Z0_BIAS_BY_MESH[0.2] == pytest.approx(-4.21, abs=0.01)


# ── 常量预声明（不随数据挪）与经验修正常数 ──────────────────────────────────

def test_constants_predeclared():
    assert MLINE_LINE_BASIS_S11_MAX_DB == -30.0
    assert H1_DOMINANCE_MIN_GAIN_DB == 6.0
    assert GAMMA_DB_FLOOR == -200.0
    # 经验修正常数须显式声明未标定态（None），禁静默恒等
    assert OPENEMS_MLINE_Z0_BIAS_PCT is None or isinstance(
        OPENEMS_MLINE_Z0_BIAS_PCT, float)


def test_engine_z0_from_hj_undetermined_raises():
    with pytest.raises(ValueError, match="尚未标定"):
        engine_z0_from_hj(50.0, bias_pct=None)


def test_engine_z0_from_hj_applies_bias():
    assert engine_z0_from_hj(50.0, bias_pct=-4.7) == pytest.approx(47.65)
    assert engine_z0_from_hj(50.01, bias_pct=0.0) == pytest.approx(50.01)


def test_engine_z0_rejects_nonpositive():
    with pytest.raises(ValueError):
        engine_z0_from_hj(0.0, bias_pct=-4.7)


# ── 模板 mline β 块契约（列位置 + ZL 列 + ReadUIData 位置）─────────────────

@pytest.fixture(scope="module")
def mline_script() -> str:
    return render_script("mline", {"w_mm": 1.113, "line_len_mm": 40.0},
                         (2.4, 2.6), mesh_resolution_mm=1.2)


def test_template_beta_header_column_position_contract(mline_script: str):
    # scripts/wp39_followup_run.read_port_beta_csv 与 engine_benchmark_mline._beta_eps
    # 按列位置 r[0]/r[1] 读 → 前两列名必须逐字节不变
    assert '"freq_hz", "beta_rad_per_m"' in mline_script
    for col in ("beta2_rad_per_m", "re_zl1_ohm", "im_zl1_ohm",
                "re_zl2_ohm", "im_zl2_ohm"):
        assert f'"{col}"' in mline_script


def test_template_readuidata_before_run_and_calcport_unchanged(mline_script: str):
    # ReadUIData（β 块）必须都在 FDTD.Run 行之前（#212 截断审计同构断言）；
    # CalcPort(ref_impedance=50) 仍在 → sparams.csv S 列口径不变
    run_at = mline_script.index("FDTD.Run(")
    assert mline_script.count("_port1.ReadUIData(SIM_PATH, f)") == 1
    assert mline_script.count("_port2.ReadUIData(SIM_PATH, f)") == 1
    assert mline_script.index("_port1.ReadUIData(SIM_PATH, f)") > run_at
    assert mline_script.index("_port2.ReadUIData(SIM_PATH, f)") > run_at
    assert "ref_impedance=50" in mline_script


def test_other_templates_rendering_untouched():
    # β 块分支改动不得波及其它模板：cpw/via/sma_launcher 无 ReadUIData；
    # wstep 保持既有 2 次（行为钉住）
    for tpl, params in (("cpw", {"w_mm": 0.849, "gap_mm": 0.2}),
                        ("via", {}),
                        ("sma_launcher", {})):
        script = render_script(tpl, params, (2.4, 2.6), mesh_resolution_mm=1.2)
        assert "ReadUIData" not in script, tpl
    wstep = render_script("wstep", {"w1_mm": 1.1134, "w2_mm": 1.897},
                          (2.4, 2.6), mesh_resolution_mm=1.2)
    assert wstep.count("ReadUIData(") == 2


# ── scripts/mline_pseudofloor_probe.py 的 CSV 读取（两种 ZL 来源形态）───────

def _load_probe_module():
    spec = importlib.util.spec_from_file_location(
        "mline_pseudofloor_probe",
        REPO / "scripts" / "mline_pseudofloor_probe.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("mline_pseudofloor_probe", mod)
    spec.loader.exec_module(mod)
    return mod


def test_probe_read_port_beta_csv_with_and_without_zl(tmp_path):
    mod = _load_probe_module()
    # 新模板形态（mline β 块 7 列）
    p = tmp_path / "port_beta.csv"
    p.write_text(
        "freq_hz,beta_rad_per_m,beta2_rad_per_m,re_zl1_ohm,im_zl1_ohm,"
        "re_zl2_ohm,im_zl2_ohm\n"
        "2.4e9,85.93,85.94,44.10,0.007,44.14,0.008\n"
        "2.6e9,93.09,93.10,44.11,0.006,44.15,0.007\n", encoding="utf-8")
    d = mod.read_port_beta_csv(p)
    assert d["zl1"][0] == pytest.approx(44.10 + 0.007j)
    assert d["zl2"][1] == pytest.approx(44.15 + 0.007j)
    # 旧归档形态（2 列）→ 无 zl 键
    q = tmp_path / "old.csv"
    q.write_text("freq_hz,beta_rad_per_m\n2.4e9,85.93\n", encoding="utf-8")
    d2 = mod.read_port_beta_csv(q)
    assert "zl1" not in d2 and d2["beta_rad_per_m"][0] == pytest.approx(85.93)


def test_probe_replay_guard_rejects_multi_run_lines(tmp_path):
    # #212 同构：FDTD.Run 行不唯一 → 拒绝重放
    mod = _load_probe_module()
    d = tmp_path / "case"
    d.mkdir()
    (d / "simulation.py").write_text(
        "import numpy as np\nFDTD.Run(a, b)\nFDTD.Run(a, b)\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="唯一"):
        mod.replay_engine_zl(d, np.array([2.4e9, 2.6e9]))


def test_eps_eff_from_beta_consistency_with_probe_row():
    # 真机归档 m1.2 w=1.113 量级：β(2.5GHz)=√εeff·2πf/c，εeff=2.91816
    eps = 2.91816
    beta = math.sqrt(eps) * 2 * math.pi * 2.5e9 / 299792458.0
    f = np.linspace(2.4e9, 2.6e9, 401)
    got, f_med = eps_eff_from_beta(f, np.full(f.shape, beta), 2.5e9)
    assert got == pytest.approx(eps, abs=1e-9)
    assert f_med == pytest.approx(2.5e9)
