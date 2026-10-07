"""F-L.1b SG13G2 Day-1 链单测（不上 ngspice；真跑走 RFAUTO_FL1_ITEST=1 opt-in）。

覆盖面（任务书交付骨架 3）：
- 结果 JSON schema 校验（validate_results 契约）；
- 闭式互证链的合成数据单测：功率波→S 换算（解析参照电路）、fT 过 1 外推、
  NF 公式（3dB 衰减器 F=2）、L-match 综合回收、VBIC→Pospieszalski 映射的
  串/并导纳恒等与闭式可运行性；
- 网表生成器含 PDK 契约（.lib cornerHBT hbt_typ、npn13G2 引脚序 c b e bn）；
- 真跑链 opt-in（env RFAUTO_FL1_ITEST=1， 真跑纪律：缺省 unit 门零
  真跑依赖），落在仓根 runs/fl1_sg13g2/。
"""
from __future__ import annotations

import importlib.util
import math
import os
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "fl1_sg13g2" / "run_day1.py"
_spec = importlib.util.spec_from_file_location("fl1_run_day1", _SCRIPT)
assert _spec is not None and _spec.loader is not None
fl1 = importlib.util.module_from_spec(_spec)
sys.modules["fl1_run_day1"] = fl1
_spec.loader.exec_module(fl1)

from rfauto.core.fet_noise import (
    K_B_J_PER_K,
    pospieszalski_noise_params,
)

# ─── 代表性 .op 输出（量级取自 2026-09-27 实测 Nx=2/Vbe=0.86/Vce=1.0 探针）────
OP_NX2 = {
    "vbe": 0.839357,
    "vbc": -0.0643201,
    "ic": 1.45679e-3,
    "ib": 2.16938e-6,
    "beta": 671.524,
    "gm": 4.3931e-2,
    "go": -4.17546e-6,
    "gpi": 7.63812e-5,
    "gmu": 3.74408e-9,
    "gx": 3.52335e-2,
    "cbe": 1.47243e-14,
    "cbex": 0.0,
    "cbc": 7.57857e-16,
    "cbcx": 3.17348e-32,
    "cbep": 1.75065e-15,
    "cbcp": 2.02752e-15,
}

F0 = 5e9
T_SIM = 300.15


# ─── wrdata / .op 解析 ────────────────────────────────────────────────────────


def test_parse_wrdata_two_complex_vectors():
    text = (
        " 1.00000000e+09  7.50000000e-01 -1.00000000e-01"
        "  1.00000000e+09  5.00000000e-03  2.00000000e-04\n"
        " 2.00000000e+09  7.40000000e-01 -2.00000000e-01"
        "  2.00000000e+09  5.10000000e-03  3.00000000e-04\n"
    )
    rows = fl1.parse_wrdata(text, 2)
    assert len(rows) == 2
    assert rows[0][0][0] == complex(1e9, 0)
    assert rows[0][0][1] == complex(0.75, -0.1)
    assert rows[0][1][1] == complex(5e-3, 2e-4)
    assert rows[1][1][1] == complex(5.1e-3, 3e-4)


def test_parse_wrdata_real_vector_two_column_format():
    """实数矢量 = (f, val) 2 列（noise 谱实测格式；三列分组会吞频率当虚部）。"""
    text = (
        " 1.00000000e+09  1.61951757e-09  1.00000000e+09  2.44193747e-09\n"
        " 2.00000000e+09  1.61944373e-09  2.00000000e+09  2.44188901e-09\n"
    )
    rows = fl1.parse_wrdata(text, 2)
    assert len(rows) == 2
    assert rows[0][0] == [complex(1e9), complex(1.61951757e-09)]
    assert rows[0][1] == [complex(1e9), complex(2.44193747e-09)]
    assert rows[1][1][1].real == pytest.approx(2.44188901e-09)


def test_parse_wrdata_real_format_freq_mismatch_raises():
    text = " 1.0e9  1.0e-9  2.0e9  2.0e-9\n"
    with pytest.raises(ValueError, match="频率列不一致"):
        fl1.parse_wrdata(text, 2)


def test_parse_op_vbic_block():
    stdout = "\n".join(
        [
            "Circuit: day1",
            " VBIC: Vertical Bipolar Inter-Company Model",
            "     device         q.xq.qnpn13g2",
            "      model    xq:npn13g2_nx_vbic",
            "        vbe              0.839357",
            "         gm              4.3931e-02",
            "        gpi           7.63812e-05",
            "         ic            0.00145679",
            "",
            " Vsource: Independent voltage source",
            "     device                   vbe                   vce",
            "         dc                  0.86                     1",
        ]
    )
    op = fl1.parse_op_vbic(stdout)
    assert op["gm"] == pytest.approx(4.3931e-2)
    assert op["ic"] == pytest.approx(1.45679e-3)
    assert "dc" not in op  # Vsource 块不得混入


def test_parse_op_vbic_missing_block_raises():
    with pytest.raises(ValueError, match="VBIC"):
        fl1.parse_op_vbic("no device table here\n")


# ─── 功率波 → S 换算（解析参照电路）───────────────────────────────────────────


def _series_z_waves(z: complex, z0: float = 50.0) -> tuple[fl1.PortWaves, fl1.PortWaves]:
    """串 Z 双 50Ω port 网络两轮驱动的解析 port 波（run A/B）。"""
    # run A（port1 驱动 AC 1V）：环路阻抗 2z0+z
    i1 = 1.0 / (2 * z0 + z)
    v1 = i1 * (z0 + z)  # port1 平面电压（Z 与负载 50 串）
    v2 = i1 * z0
    i2 = -i1
    a = fl1.PortWaves(v1=v1, i1=i1, v2=v2, i2=i2)
    # run B：对称（port2 驱动）
    i2b = 1.0 / (2 * z0 + z)
    v2b = i2b * (z0 + z)
    v1b = i2b * z0
    i1b = -i2b
    b = fl1.PortWaves(v1=v1b, i1=i1b, v2=v2b, i2=i2b)
    return a, b


def test_waves_to_s_series_100r_analytic():
    a, b = _series_z_waves(complex(100, 0))
    s = fl1.waves_to_s(a, b, 50.0)
    for k in ("s11", "s21", "s22", "s12"):
        assert s[k] == pytest.approx(0.5, abs=1e-12)


def test_waves_to_s_complex_series_z():
    z = complex(30.0, 80.0)
    a, b = _series_z_waves(z)
    s = fl1.waves_to_s(a, b, 50.0)
    s11_t = z / (100.0 + z)
    s21_t = 100.0 / (100.0 + z)
    assert s["s11"] == pytest.approx(s11_t, rel=1e-12)
    assert s["s21"] == pytest.approx(s21_t, rel=1e-12)
    assert s["s22"] == pytest.approx(s11_t, rel=1e-12)
    assert s["s12"] == pytest.approx(s21_t, rel=1e-12)


def test_waves_to_s_zero_excitation_raises():
    zero = fl1.PortWaves(0j, 0j, 0j, 0j)
    with pytest.raises(ValueError, match="激励波"):
        fl1.waves_to_s(zero, zero, 50.0)


# ─── fT 过 1 外推 ─────────────────────────────────────────────────────────────


def test_ft_crossing_recovers_single_pole():
    beta0, ft_true = 300.0, 250e9
    freqs = [ft_true * 10 ** (k / 20.0) for k in range(-40, 41)]
    # 单极点电流增益：h21(f)=β0/sqrt(1+(β0·f/fT)²)（f_3dB=fT/β0）
    h21 = [beta0 / math.sqrt(1.0 + (beta0 * f / ft_true) ** 2) for f in freqs]
    ft = fl1.ft_crossing_hz(freqs, h21)
    assert ft == pytest.approx(ft_true, rel=0.02)


def test_ft_crossing_no_crossing_returns_none():
    freqs = [1e9, 2e9, 3e9]
    h21 = [10.0, 5.0, 4.0]
    assert fl1.ft_crossing_hz(freqs, h21) is None


# ─── NF 公式（3dB 衰减器解析参照）────────────────────────────────────────────


def test_nf_linear_3db_attenuator_recovers_two():
    inoise = math.sqrt(2.0 * 4.0 * K_B_J_PER_K * 300.15 * 50.0)
    f = fl1.nf_linear_from_inoise(inoise, 50.0, 300.15)
    assert f == pytest.approx(2.0, rel=1e-12)


def test_nf_linear_rejects_nonpositive():
    with pytest.raises(ValueError, match=">0"):
        fl1.nf_linear_from_inoise(0.0, 50.0, 300.15)


# ─── L-match 综合（port 侧阻抗回收 50Ω）──────────────────────────────────────


def test_lmatch_roundtrip_recovers_50ohm():
    zin = complex(28.0, -600.0)
    m = fl1.synthesize_lmatch(zin, 50.0, F0)
    assert m is not None
    w = 2 * math.pi * F0
    zser = 1j * w * m.series_l_h + zin
    zsh = 1.0 / (1j * w * m.shunt_c_f)
    zseen = zsh * zser / (zsh + zser)
    assert zseen == pytest.approx(50.0 + 0j, rel=1e-9, abs=1e-9)
    assert m.series_l_h > 0 and m.shunt_c_f > 0


@pytest.mark.parametrize("zin", [complex(75, 0), complex(-20, -100), complex(0, -50)])
def test_lmatch_degenerate_returns_none(zin):
    assert fl1.synthesize_lmatch(zin, 50.0, F0) is None


def test_zs_device_plane_unmatched_is_50_plus_cin():
    w = 2 * math.pi * F0
    expect = 50.0 + 1.0 / (1j * w * 10e-12)
    assert fl1.zs_device_plane(F0, None) == pytest.approx(expect, rel=1e-12)


# ─── VBIC → Pospieszalski 映射 ───────────────────────────────────────────────


def test_fet_mapping_series_parallel_admittance_identity():
    """串等价 (Ri+Cs) 必须逐位重建结支路导纳 gpi+jwCπ（映射正确性的根）。"""
    nm, _, extra = fl1.fet_models_from_op(OP_NX2, F0, 2, T_SIM)
    w = 2 * math.pi * F0
    y_series = 1.0 / (extra["ri_ohm"] + 1.0 / (1j * w * extra["cgs_series_f"]))
    y_parallel = OP_NX2["gpi"] + 1j * w * (OP_NX2["cbe"] + OP_NX2["cbep"])
    assert y_series == pytest.approx(y_parallel, rel=1e-12)
    assert nm.gm_s == OP_NX2["gm"]
    assert nm.gds_s == abs(OP_NX2["go"])  # go 打印为负（自热），映射取 |go|


def test_fet_mapping_feeds_closed_form_runnable():
    nm, ft_model, extra = fl1.fet_models_from_op(OP_NX2, F0, 2, T_SIM)
    params = pospieszalski_noise_params(nm, F0, extra["tg_k"], extra["td_k"], t0_k=300.15, z0=50.0)
    assert params.fmin_linear > 1.0
    assert params.rn_ohm > 0.0
    assert abs(params.gamma_opt) < 1.0
    assert math.isfinite(params.fmin_db)
    # fT 闭式量级：gm/(2π(Cπ+Cμ)) 应落在 1e11-1e12 Hz（Nx=2 偏置点实测 ~3e11 量级）
    ft = fl1.transition_frequency_hz(ft_model)
    assert 1e11 < ft < 1e12


# ─── 网表生成器 PDK 契约 ─────────────────────────────────────────────────────


def test_netlists_carry_pdk_contract():
    for nl in (
        fl1.netlist_op(0.86, 1.2, 2),
        fl1.netlist_h21(0.86, 1.2, 2, "/mnt/e/out.txt"),
        fl1.netlist_lna(1, None, 2, with_noise=False, ac_wrdata_wsl="/mnt/e/a.txt"),
        fl1.netlist_nf_point(5e9, 2, "/mnt/e/n.txt"),
    ):
        assert "cornerHBT.lib hbt_typ" in nl
        assert "npn13G2 Nx=2" in nl
        # 引脚序 c b e bn（模型卡 L41），四端版共射：e/bn 接地
        assert "Xq c b 0 0 npn13G2" in nl


def test_netlist_lna_drive_swap_and_noise():
    a = fl1.netlist_lna(1, None, 2, with_noise=True, ac_wrdata_wsl="/x", nf_wrdata_wsl="/y")
    b = fl1.netlist_lna(2, None, 2, with_noise=False, ac_wrdata_wsl="/x")
    assert "V1 p1s 0 DC 0 AC 1" in a and "V2 p2s 0 DC 0 AC 0" in a
    assert "V1 p1s 0 DC 0 AC 0" in b and "V2 p2s 0 DC 0 AC 1" in b
    assert "noise v(p2) v1 dec" in a
    assert "noise" not in b
    assert "noise1.inoise_spectrum" in a  # plot 限定名（实证：noise 分析后当前 plot 是积分）


def test_netlist_lna_match_elements_inserted():
    m = fl1.MatchNetwork(series_l_h=2e-8, shunt_c_f=5.6e-13)
    nl = fl1.netlist_lna(1, m, 2, with_noise=False, ac_wrdata_wsl="/x")
    assert "Cm p1 0 5.600000e-13" in nl
    assert "Lm p1 p1x 2.000000e-08" in nl
    assert "Cin p1x p1y" in nl


def test_netlist_h21_voltage_drive_topology():
    """h21 拓扑防回归：电压驱动+测双节点（电流直注会被理想 Vbe 源短路）。"""
    nl = fl1.netlist_h21(0.86, 1.2, 2, "/mnt/e/o.txt")
    assert "Vsig bs 0 DC 0.86 AC 1" in nl
    assert "Rb bs b 50" in nl
    assert "wrdata /mnt/e/o.txt v(bs) v(b) i(vam)" in nl


# ─── verdict 与 schema 契约 ──────────────────────────────────────────────────


def test_band_verdict_predeclared_bands():
    assert fl1.band_verdict(0.10) == "PASS"
    assert fl1.band_verdict(0.15) == "PASS"
    assert fl1.band_verdict(0.16) == "PARTIAL"
    assert fl1.band_verdict(0.30) == "PARTIAL"
    assert fl1.band_verdict(0.31) == "FAIL"


def test_ft_band_verdict():
    assert fl1.ft_band_verdict(250e9) == "PASS"
    assert fl1.ft_band_verdict(90e9) == "FAIL"
    assert fl1.ft_band_verdict(None) == "FAIL"


def _synthetic_results() -> dict:
    st = {
        "pass": True,
        "tolerance": 1e-6,
        "theory": {},
        "measured": {},
        "max_abs_dev": 1e-9,
        "note": "",
    }
    grid = [
        {"vbe_v": v, "vce_v": c, "ic_a": 1e-3, "gm_s": 0.04, "ft_h21_hz": 300e9, "ft_closed_hz": 310e9}
        for v in (0.8, 0.85, 0.9)
        for c in (0.6, 1.2, 1.5)
    ]
    xcheck = [
        {
            "f_hz": f,
            "f_spice_linear": 2.0,
            "f_closed_linear": 2.1,
            "rel_dev": 0.05,
            "verdict": "PASS",
        }
        for f in (2e9, 5e9, 8e9)
    ]
    return {
        "schema": fl1.SCHEMA_ID,
        "meta": {},
        "criteria": {},
        "instrument_selftest": st,
        "grid": grid,
        "lna": {"bias": {}, "nf_points": xcheck},
        "xcheck": xcheck,
        "attribution": [],
        "verdicts": {"overall": "PASS"},
        "provenance": {"netlists": [], "logs": []},
    }


def test_validate_results_accepts_synthetic_complete(tmp_path: Path):
    res = _synthetic_results()
    assert fl1.validate_results(res) == []


def test_validate_results_flags_missing_sections_and_bad_verdicts():
    res = _synthetic_results()
    del res["lna"]
    res["xcheck"][0]["verdict"] = "GREEN"
    res["grid"] = res["grid"][:3]
    res["instrument_selftest"]["pass"] = False
    problems = fl1.validate_results(res)
    assert any("lna" in p for p in problems)
    assert any("verdict 非法" in p for p in problems)
    assert any("3x3" in p for p in problems)
    assert any("instrument_selftest" in p for p in problems)


def test_validate_results_provenance_paths_checked(tmp_path: Path):
    res = _synthetic_results()
    res["provenance"] = {"netlists": [str(tmp_path / "missing.cir")], "logs": []}
    problems = fl1.validate_results(res)
    assert any("netlist 不存在" in p for p in problems)


# ─── 真跑 opt-in（RFAUTO_FL1_ITEST=1；落仓根 runs/fl1_sg13g2）───────────────


@pytest.mark.skipif(
    os.environ.get("RFAUTO_FL1_ITEST") != "1",
    reason="真跑 opt-in",
)
def test_day1_real_run_chain():
    res = fl1.run_day1(fl1.DEFAULT_OUTDIR, nx=2)
    assert res["instrument_selftest"]["pass"] is True
    assert len(res["grid"]) == 9
    assert res["lna"]["unmatched"]["s21_db_at_f0"] > 0.0
    assert len(res["xcheck"]) == 3
    for x in res["xcheck"]:
        assert x["f_spice_linear"] > 1.0  # 有源链 NF>0dB
        assert x["verdict"] in {"PASS", "PARTIAL", "FAIL"}
    assert res["verdicts"]["overall"] in {"PASS", "PARTIAL", "FAIL"}
    assert Path(res["provenance"]["results_json"]).exists()
