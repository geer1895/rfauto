"""hfss_run_report 四联图 service 测试（晶圆键合反馈 P2，Q-X5）。

三面锚（铁律 7：数字全出数据源 + 独立复算裁判 #118 家法）：
- **合成解析对照**：理想无耗线 fixture（已知 εeff=4.0 / 参考面跨度 5 mm /
  Γ=0.05），四联图逐面与闭式独立复算对照（εeff 复算=构造值 rel 1e-9——
  fixture 以 17 位有效数字写盘，读回逐位恢复 float64）；
- **负例信封契约**：坏文件/缺源/空 run 目录/乱序频率 → ok=False + errors
  list[str]（AU-2 契约，失败信封与成功同构）；
- **确定性**：同输入两跑 PNG 逐字节一致 + 信封数字逐字节一致
  （OO API + 显式 metadata + 零时间戳，design_replay_report 先例）。

单源消费钉（Q-W8-4 家法）：plot_style 冻结面只消费——dpi/figsize 绑定
与 PNG 实际像素双向核对。

零网络零真机：全部 tmp_path + 合成数据（Agg OO API，零 pyplot 后端依赖）。
"""

from __future__ import annotations

import json
import math
import struct
from pathlib import Path

import numpy as np
import pytest

from rfauto.service.hfss_run_report_service import (
    _C_LIGHT_M_S,
    _DB_FLOOR,
    _FIG_DPI,
    _FIGSIZE_FOURPANEL,
    render_hfss_run_report,
)

_TESTS_DIR = Path(__file__).resolve().parent
_FIXTURE_PATH = _TESTS_DIR / "fixtures" / "hfss_run_report" / "ideal_line_eps4.s2p"

# ── fixture 闭式形态常量（解析真值，独立于 service 计算路径） ────────────────
EPS_EFF_TARGET = 4.0
REF_SPAN_M = 5.0e-3
GAMMA = 0.05
T_COEF = math.sqrt(1.0 - GAMMA**2)
N_FREQS = 101
F_MIN_HZ = 1.0e9
F_MAX_HZ = 10.0e9

#: 理想线群时延（解析）：τ = √εeff·L/c = 33.36 ps（f 无关）
_TAU_PS_IDEAL = math.sqrt(EPS_EFF_TARGET) * REF_SPAN_M / _C_LIGHT_M_S * 1e12


def _phi_rad(f_hz: float) -> float:
    """带内传播相位解析式：φ(f) = 2π f √εeff L / c。"""
    return (2.0 * math.pi * f_hz * math.sqrt(EPS_EFF_TARGET) * REF_SPAN_M
            / _C_LIGHT_M_S)


def _ideal_line_s_matrix(freq_hz: np.ndarray) -> np.ndarray:
    """理想线 S 矩阵闭式（fixture 与解析对照共用的唯一构造源）。"""
    phi = (2.0 * np.pi * freq_hz * math.sqrt(EPS_EFF_TARGET) * REF_SPAN_M
           / _C_LIGHT_M_S)
    s11 = GAMMA * np.exp(-1j * 2.0 * phi)
    s21 = T_COEF * np.exp(-1j * phi)
    n = freq_hz.shape[0]
    s = np.zeros((n, 2, 2), dtype=complex)
    s[:, 0, 0] = s11
    s[:, 1, 0] = s21
    s[:, 0, 1] = s21  # 互易
    s[:, 1, 1] = s11
    return s


def _ideal_line_s2p_text() -> str:
    """fixture 文件唯一生成源（17 位有效数字 repr——float64 逐位 round-trip）。"""
    freq_hz = np.linspace(F_MIN_HZ, F_MAX_HZ, N_FREQS)
    s = _ideal_line_s_matrix(freq_hz)
    lines = [
        "! Ideal lossless line fixture (deterministic analytic form)",
        "! eps_eff=4.0, ref_span=0.005 m, Gamma=0.05, f=1..10 GHz (101 pts)",
        "! S11=Gamma*exp(-j*2*phi), S21=T*exp(-j*phi), phi=2*pi*f*sqrt(eps_eff)*L/c",
        "! Consumers: tests/unit/test_hfss_run_report.py",
        "# HZ S RI R 50",
    ]
    for i in range(N_FREQS):
        vals = [freq_hz[i], s[i, 0, 0].real, s[i, 0, 0].imag,
                s[i, 1, 0].real, s[i, 1, 0].imag,
                s[i, 0, 1].real, s[i, 0, 1].imag,
                s[i, 1, 1].real, s[i, 1, 1].imag]
        lines.append(" ".join(repr(float(v)) for v in vals))
    return "\n".join(lines) + "\n"


# ── fixture 完整性锚 ─────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def ideal_s2p_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """fixture 路径：在库文件在位即用之（完整性锚逐字节钉生成源）；缺位
    （.gitignore ``*.s2p`` 家法——仓库既有 sNp fixture 同口径，fresh clone
    不随库）→ 生成源逐字节写 tmp 兜底，数值锚全环境可达（环境差异=如实
    降级不放松断言）。"""
    if _FIXTURE_PATH.exists():
        return _FIXTURE_PATH
    p = tmp_path_factory.mktemp("fixture_fallback") / _FIXTURE_PATH.name
    p.write_text(_ideal_line_s2p_text(), encoding="utf-8")
    return p


def test_fixture_file_matches_canonical_generator(ideal_s2p_path: Path) -> None:
    """在库 fixture == 唯一生成源逐字节（完整性+确定性双钉）。

    fresh clone 且在库文件缺位时，路径即兜底生成产物——本锚在缺位环境
    退化为生成源自等（如实登记：真锚依赖在库文件在位，本机在位）。
    """
    committed = ideal_s2p_path.read_text(encoding="utf-8")
    assert committed == _ideal_line_s2p_text()


def test_fixture_readback_skrf_matches_analytic(ideal_s2p_path: Path) -> None:
    """fixture 经 skrf 读回 → 逐位恢复构造 S 矩阵（文件链路无损）。"""
    import skrf

    net = skrf.Network(str(ideal_s2p_path))
    assert net.nports == 2
    freq_hz = np.asarray(net.f, dtype=float)
    assert freq_hz.shape[0] == N_FREQS
    expect = _ideal_line_s_matrix(freq_hz)
    np.testing.assert_allclose(net.s, expect, rtol=0.0, atol=0.0)


# ── 主链路：四联图数值锚（独立复算，rel 1e-9 级） ────────────────────────────


@pytest.fixture(scope="module")
def ideal_report(ideal_s2p_path: Path,
                 tmp_path_factory: pytest.TempPathFactory) -> dict:
    out_dir = tmp_path_factory.mktemp("rf_figures")
    return render_hfss_run_report(
        ideal_s2p_path, out_dir=out_dir, ref_span_m=REF_SPAN_M)


def test_report_ok_envelope_shape(ideal_report: dict) -> None:
    """成功信封形状：ok/png_paths/summary 三键 + PNG 落盘存在。"""
    assert ideal_report["ok"] is True
    paths = ideal_report["png_paths"]
    assert isinstance(paths, list) and len(paths) == 1
    assert Path(paths[0]).is_file() and Path(paths[0]).suffix == ".png"
    s = ideal_report["summary"]
    assert s["source_kind"] == "touchstone"
    assert s["n_ports"] == 2
    assert s["n_freqs"] == N_FREQS
    assert s["f_min_ghz"] == pytest.approx(F_MIN_HZ * 1e-9, rel=1e-12)
    assert s["f_max_ghz"] == pytest.approx(F_MAX_HZ * 1e-9, rel=1e-12)


def test_panel1_sparam_mag_db_anchor(ideal_report: dict) -> None:
    """联 1 锚：|S21| dB 恒 = 20log10(T)；|S11| dB 恒 = 20log10(Γ)。"""
    s = ideal_report["summary"]
    s21_db_expect = 20.0 * math.log10(T_COEF)
    assert s["s21"]["mag_db_min"] == pytest.approx(s21_db_expect, rel=1e-12)
    assert s["s21"]["mag_db_max"] == pytest.approx(s21_db_expect, rel=1e-12)
    s11_db_expect = 20.0 * math.log10(GAMMA)
    assert s["s11_db"]["min"] == pytest.approx(s11_db_expect, rel=1e-12)
    assert s["s11_db"]["max"] == pytest.approx(s11_db_expect, rel=1e-12)
    assert s11_db_expect > _DB_FLOOR  # 地板不参与（fixture 无 |S|=0 点）


def test_panel2_phase_unwrap_anchor(ideal_report: dict) -> None:
    """联 2 锚：展开相位端点 = −φ(f) 解析值（1e-9 rel）。"""
    s = ideal_report["summary"]
    start_deg = s["s21"]["phase_unwrap_start_deg"]
    end_deg = s["s21"]["phase_unwrap_end_deg"]
    expect_start = -math.degrees(_phi_rad(F_MIN_HZ))
    expect_end = -math.degrees(_phi_rad(F_MAX_HZ))
    assert start_deg == pytest.approx(expect_start, rel=1e-9)
    assert end_deg == pytest.approx(expect_end, rel=1e-9)
    # 单调下降（无耗线传播相位）
    assert end_deg < start_deg


def test_panel3_group_delay_anchor(ideal_report: dict) -> None:
    """联 3 锚：线性相位 → 群时延恒 = √εeff·L/c（三点 min/med/max 同值）。"""
    s = ideal_report["summary"]
    gd = s["group_delay"]
    assert gd["smooth_window"] == 1  # 缺省关闭声明
    for k in ("median_ps", "min_ps", "max_ps"):
        assert gd[k] == pytest.approx(_TAU_PS_IDEAL, rel=1e-9), k


def test_panel4_eps_eff_scalar_anchor(ideal_report: dict) -> None:
    """联 4 锚：εeff 复算 = 构造值 4.0（rel 1e-9，标量模式）。"""
    eps = ideal_report["summary"]["eps_eff"]
    assert eps is not None
    assert eps["mode"] == "scalar"
    assert eps["value"] == pytest.approx(EPS_EFF_TARGET, rel=1e-9)
    assert eps["rel_spread"] < 1e-9
    assert eps["ref_span_m"] == REF_SPAN_M
    assert "(beta/omega)^2*c^2" in eps["method"]


def test_eps_eff_note_declares_reference_plane_semantics(ideal_report: dict) -> None:
    """#364-② 口径声明落档：notes 含参考面跨度语义 + 零手拍声明要素。"""
    notes = "\n".join(ideal_report["summary"]["notes"])
    assert "#364-②" in notes
    assert "参考面跨度" in notes
    assert f"L={REF_SPAN_M:g}" in notes


# ── 色散形态：曲线模式 + 群时延解析对照 ──────────────────────────────────────


def _dispersive_s2p(tmp_path: Path) -> Path:
    """色散合成：εeff(f) = 2.0 + 0.5·(f−f0)/(fmax−f0)（线性色散）。"""
    freq_hz = np.linspace(F_MIN_HZ, F_MAX_HZ, N_FREQS)
    eps = 2.0 + 0.5 * (freq_hz - F_MIN_HZ) / (F_MAX_HZ - F_MIN_HZ)
    phi = 2.0 * np.pi * freq_hz * np.sqrt(eps) * REF_SPAN_M / _C_LIGHT_M_S
    s21 = T_COEF * np.exp(-1j * phi)
    lines = ["# HZ S RI R 50"]
    for i in range(N_FREQS):
        s11 = GAMMA * np.exp(-1j * 2.0 * phi[i])
        vals = [freq_hz[i], s11.real, s11.imag, s21[i].real, s21[i].imag,
                s21[i].real, s21[i].imag, s11.real, s11.imag]
        lines.append(" ".join(repr(float(v)) for v in vals))
    p = tmp_path / "dispersive.s2p"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def test_eps_eff_curve_mode_dispersive(tmp_path: Path) -> None:
    """色散数据 → curve 模式；median/min/max 与解析逐点复算对照（1e-9）。"""
    src = _dispersive_s2p(tmp_path)
    result = render_hfss_run_report(src, out_dir=tmp_path / "fig",
                                    ref_span_m=REF_SPAN_M)
    assert result["ok"] is True
    eps = result["summary"]["eps_eff"]
    assert eps["mode"] == "curve"
    freq_hz = np.linspace(F_MIN_HZ, F_MAX_HZ, N_FREQS)
    eps_analytic = 2.0 + 0.5 * (freq_hz - F_MIN_HZ) / (F_MAX_HZ - F_MIN_HZ)
    assert eps["median"] == pytest.approx(float(np.median(eps_analytic)),
                                          rel=1e-9)
    assert eps["min"] == pytest.approx(float(np.min(eps_analytic)), rel=1e-9)
    assert eps["max"] == pytest.approx(float(np.max(eps_analytic)), rel=1e-9)
    assert eps["rel_spread"] > 0.05  # 色散超出标量阈值 → 曲线如实


def test_group_delay_dispersive_analytic(tmp_path: Path) -> None:
    """色散群时延 vs 独立解析式 τ = L/c·(√εeff + ω·εeff'/(2√εeff))。"""
    src = _dispersive_s2p(tmp_path)
    result = render_hfss_run_report(src, out_dir=tmp_path / "fig",
                                    ref_span_m=REF_SPAN_M,
                                    gd_smooth_window=1)
    assert result["ok"] is True
    freq_hz = np.linspace(F_MIN_HZ, F_MAX_HZ, N_FREQS)
    eps = 2.0 + 0.5 * (freq_hz - F_MIN_HZ) / (F_MAX_HZ - F_MIN_HZ)
    d_eps_d_omega = 0.5 / (F_MAX_HZ - F_MIN_HZ) / (2.0 * math.pi)
    omega = 2.0 * math.pi * freq_hz
    tau_analytic = (REF_SPAN_M / _C_LIGHT_M_S
                    * (np.sqrt(eps)
                       + omega * d_eps_d_omega / (2.0 * np.sqrt(eps)))) * 1e12
    gd = result["summary"]["group_delay"]
    # 数值差分 O(h²) 误差带（101 点平滑解析函数，实测远小于该带）
    assert gd["median_ps"] == pytest.approx(float(np.median(tau_analytic)),
                                            rel=1e-4)
    assert gd["min_ps"] == pytest.approx(float(np.min(tau_analytic)), rel=1e-4)
    assert gd["max_ps"] == pytest.approx(float(np.max(tau_analytic)), rel=1e-4)


def test_group_delay_smooth_window_declared_and_exact_on_linear(
        ideal_s2p_path: Path, tmp_path: Path) -> None:
    """平滑窗声明式：窗 5 对线性相位精确（2 阶基含线性）；窗值随信封落档。"""
    result = render_hfss_run_report(
        ideal_s2p_path, out_dir=tmp_path / "fig",
        ref_span_m=REF_SPAN_M, gd_smooth_window=5)
    assert result["ok"] is True
    gd = result["summary"]["group_delay"]
    assert gd["smooth_window"] == 5
    assert gd["median_ps"] == pytest.approx(_TAU_PS_IDEAL, rel=1e-9)


def test_smooth_window_even_input_bumped_to_odd(ideal_s2p_path: Path,
                                                 tmp_path: Path) -> None:
    """偶数窗自动上调奇数并落注记（声明式参数面）。"""
    result = render_hfss_run_report(
        ideal_s2p_path, out_dir=tmp_path / "fig",
        ref_span_m=REF_SPAN_M, gd_smooth_window=4)
    assert result["ok"] is True
    assert result["summary"]["group_delay"]["smooth_window"] == 5
    assert any("奇数 5" in n for n in result["summary"]["notes"])


# ── 零手拍与降级面 ───────────────────────────────────────────────────────────


def test_eps_eff_skipped_without_ref_span(ideal_s2p_path: Path,
                                          tmp_path: Path) -> None:
    """ref_span_m=None → εeff 面跳过（ok 仍 True）+ #364-② 零手拍注记。"""
    result = render_hfss_run_report(ideal_s2p_path, out_dir=tmp_path / "fig")
    assert result["ok"] is True
    assert result["summary"]["eps_eff"] is None
    notes = "\n".join(result["summary"]["notes"])
    assert "ref_span_m 未由调用方声明" in notes
    assert "零手拍" in notes


def test_one_port_run_dir_honest_degradation(tmp_path: Path) -> None:
    """1 端口 run（results/params.s1p）：S21/群时延/εeff 如实 None+注记。

    单文件 1 端口源被装载单源拒收（si_channel 后缀契约限 s2p+）→ 另见
    ``test_negative_one_port_file_rejected``；run 目录 params.s1p 走
    health 单源候选序仍可达（params.s*p glob 含 s1p）。
    """
    run_dir = tmp_path / "hfss_run_1port"
    (run_dir / "results").mkdir(parents=True)
    lines = ["# HZ S RI R 50"]
    for f in (1e9, 2e9, 3e9):
        lines.append(f"{f!r} {GAMMA!r} 0.0")
    (run_dir / "results" / "params.s1p").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")
    result = render_hfss_run_report(run_dir, out_dir=tmp_path / "fig",
                                    ref_span_m=REF_SPAN_M)
    assert result["ok"] is True
    s = result["summary"]
    assert s["n_ports"] == 1
    assert s["s21"] is None
    assert s["group_delay"] is None
    assert s["eps_eff"] is None
    assert any("1 端口" in n for n in s["notes"])
    assert s["s11_db"]["max"] == pytest.approx(20.0 * math.log10(GAMMA),
                                               rel=1e-12)


def test_negative_one_port_file_rejected(tmp_path: Path) -> None:
    """裸 .s1p 文件源 → 装载单源如实拒收（ok=False 信封，不硬算不猜）。"""
    p = tmp_path / "one_port.s1p"
    p.write_text("# HZ S RI R 50\n1e9 0.05 0.0\n", encoding="utf-8")
    result = render_hfss_run_report(p, out_dir=tmp_path / "fig")
    assert result["ok"] is False
    assert any(".s1p" in e for e in result["errors"])


# ── 负例信封契约（AU-2：失败信封与成功同构） ─────────────────────────────────


def test_negative_bad_file_envelope(tmp_path: Path) -> None:
    """坏文件 → ok=False + errors list[str] 非空（信封同构）。"""
    p = tmp_path / "garbage.s2p"
    p.write_bytes(b"this is not a touchstone file \x00\x01")
    result = render_hfss_run_report(p, out_dir=tmp_path / "fig")
    assert result["ok"] is False
    errs = result["errors"]
    assert isinstance(errs, list) and len(errs) >= 1
    assert all(isinstance(e, str) for e in errs)


def test_negative_missing_source(tmp_path: Path) -> None:
    """源不存在 → ok=False。"""
    result = render_hfss_run_report(tmp_path / "nope.s2p",
                                    out_dir=tmp_path / "fig")
    assert result["ok"] is False
    assert result["errors"]


def test_negative_empty_run_dir(tmp_path: Path) -> None:
    """空 run 目录（无 sparams.csv / 无 Touchstone）→ ok=False。"""
    d = tmp_path / "empty_run"
    d.mkdir()
    result = render_hfss_run_report(d, out_dir=tmp_path / "fig")
    assert result["ok"] is False
    assert result["errors"]


def test_negative_non_monotonic_freq(tmp_path: Path) -> None:
    """频率轴乱序 → ok=False（差分/展开前提守卫，不硬算）。"""
    lines = ["# HZ S RI R 50",
             f"{3e9!r} {GAMMA!r} 0.0 {T_COEF!r} 0.0 {T_COEF!r} 0.0 {GAMMA!r} 0.0",
             f"{1e9!r} {GAMMA!r} 0.0 {T_COEF!r} 0.0 {T_COEF!r} 0.0 {GAMMA!r} 0.0",
             f"{2e9!r} {GAMMA!r} 0.0 {T_COEF!r} 0.0 {T_COEF!r} 0.0 {GAMMA!r} 0.0"]
    p = tmp_path / "shuffled.s2p"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    result = render_hfss_run_report(p, out_dir=tmp_path / "fig")
    assert result["ok"] is False
    assert any("单调" in e for e in result["errors"])


def test_negative_invalid_s21_ports(ideal_s2p_path: Path,
                                    tmp_path: Path) -> None:
    """端口对越界 → ok=False（1 起物理口号校验）。"""
    result = render_hfss_run_report(ideal_s2p_path, out_dir=tmp_path / "fig",
                                    s21_ports=(1, 9))
    assert result["ok"] is False
    assert any("越界" in e for e in result["errors"])


# ── run 目录源形态 ───────────────────────────────────────────────────────────


def test_run_dir_results_params_s2p_source(tmp_path: Path) -> None:
    """run 目录形态：results/params.s2p → 装载+四联图全链（主用例）。"""
    run_dir = tmp_path / "hfss_run_001"
    (run_dir / "results").mkdir(parents=True)
    (run_dir / "results" / "params.s2p").write_text(
        _ideal_line_s2p_text(), encoding="utf-8")
    out_dir = tmp_path / "figs"
    result = render_hfss_run_report(run_dir, out_dir=out_dir,
                                    ref_span_m=REF_SPAN_M)
    assert result["ok"] is True
    s = result["summary"]
    assert s["source_kind"] == "run_dir_touchstone"
    assert s["source_path"].endswith(str(Path("results") / "params.s2p"))
    assert s["eps_eff"]["value"] == pytest.approx(EPS_EFF_TARGET, rel=1e-9)
    assert Path(result["png_paths"][0]).parent == out_dir


# ── 确定性（同输入两跑逐字节） ───────────────────────────────────────────────


def test_determinism_png_bytes_identical(ideal_s2p_path: Path,
                                         tmp_path: Path) -> None:
    """同输入两跑 → PNG 逐字节一致（OO API+显式 metadata+零时间戳）。"""
    out1 = tmp_path / "a"
    out2 = tmp_path / "b"
    r1 = render_hfss_run_report(ideal_s2p_path, out_dir=out1,
                                ref_span_m=REF_SPAN_M)
    r2 = render_hfss_run_report(ideal_s2p_path, out_dir=out2,
                                ref_span_m=REF_SPAN_M)
    assert r1["ok"] and r2["ok"]
    b1 = Path(r1["png_paths"][0]).read_bytes()
    b2 = Path(r2["png_paths"][0]).read_bytes()
    assert b1 == b2


def test_determinism_envelope_numbers(ideal_s2p_path: Path,
                                      tmp_path: Path) -> None:
    """同输入两跑 → summary 数字面逐字节一致（JSON 规范序列化）。

    ``png_path`` 键随调用方 out_dir 走（合法差异），比对前置空。
    """
    r1 = render_hfss_run_report(ideal_s2p_path, out_dir=tmp_path / "a",
                                ref_span_m=REF_SPAN_M)
    r2 = render_hfss_run_report(ideal_s2p_path, out_dir=tmp_path / "b",
                                ref_span_m=REF_SPAN_M)
    s1 = dict(r1["summary"])
    s2 = dict(r2["summary"])
    assert s1.pop("png_path").endswith("hfss_run_figures.png")
    assert s2.pop("png_path").endswith("hfss_run_figures.png")
    j1 = json.dumps(s1, sort_keys=True)
    j2 = json.dumps(s2, sort_keys=True)
    assert j1 == j2


# ── plot_style 单源消费钉（Q-W8-4 家法：冻结面只消费） ───────────────────────


def test_plot_style_single_source_binding() -> None:
    """dpi/figsize 绑定 == plot_style 单源（消费面不私造数值）。"""
    from rfauto.core import plot_style

    assert int(plot_style.STYLE["savefig.dpi"]) == _FIG_DPI
    assert _FIGSIZE_FOURPANEL == plot_style.PAPER_FIGSIZE_DOUBLE


def test_png_pixel_dims_follow_style_single_source(ideal_s2p_path: Path,
                                                    tmp_path: Path) -> None:
    """PNG 实际像素 == figsize×dpi（IHDR 直读，双向核对消费面）。"""
    result = render_hfss_run_report(ideal_s2p_path, out_dir=tmp_path / "fig",
                                    ref_span_m=REF_SPAN_M)
    png = Path(result["png_paths"][0]).read_bytes()
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    w, h = struct.unpack(">II", png[16:24])
    assert w == round(_FIGSIZE_FOURPANEL[0] * _FIG_DPI)
    assert h == round(_FIGSIZE_FOURPANEL[1] * _FIG_DPI)


# ── 信封契约键集钉 ───────────────────────────────────────────────────────────


def test_envelope_summary_key_contract(ideal_report: dict) -> None:
    """summary 键集冻结钉（形状变更=显式契约动作）。"""
    s = ideal_report["summary"]
    assert set(s) == {
        "source_kind", "source_path", "n_ports", "n_freqs",
        "f_min_ghz", "f_max_ghz", "s11_db", "s21", "group_delay",
        "eps_eff", "png_path", "notes",
    }
    assert set(s["s11_db"]) == {"port", "min", "max"}
    assert set(s["s21"]) == {"ports", "mag_db_min", "mag_db_max",
                             "phase_unwrap_start_deg", "phase_unwrap_end_deg"}
    assert set(s["group_delay"]) == {"median_ps", "min_ps", "max_ps",
                                     "smooth_window"}
    assert set(s["eps_eff"]) == {"mode", "value", "rel_spread",
                                 "ref_span_m", "method"}


# ── CLI 叶（rfauto reports run-figures） ────────────────────────────────────


def _invoke(args: list[str]):
    from typer.testing import CliRunner

    from rfauto.cli.main import app

    return CliRunner().invoke(app, args)


def test_cli_run_figures_json_ok(ideal_s2p_path: Path,
                                 tmp_path: Path) -> None:
    """CLI --json 正例：exit 0 + 信封 ok + png_paths 指向在盘 PNG。"""
    out_dir = tmp_path / "cli_fig"
    r = _invoke(["reports", "run-figures", str(ideal_s2p_path),
                 "--ref-span-m", str(REF_SPAN_M),
                 "--out-dir", str(out_dir), "--json"])
    assert r.exit_code == 0, r.output
    payload = json.loads(r.output)
    assert payload["ok"] is True
    assert Path(payload["png_paths"][0]).is_file()
    assert payload["summary"]["eps_eff"]["mode"] == "scalar"


def test_cli_run_figures_json_error_envelope(tmp_path: Path) -> None:
    """CLI 失败路径：exit 1 + JSON 信封（errors list，--json 下禁裸文本）。"""
    r = _invoke(["reports", "run-figures", str(tmp_path / "missing.s2p"),
                 "--json"])
    assert r.exit_code == 1
    payload = json.loads(r.output)
    assert payload["ok"] is False
    assert isinstance(payload["errors"], list) and payload["errors"]


def test_cli_run_figures_usage_error_exit2(ideal_s2p_path: Path,
                                            tmp_path: Path) -> None:
    """--s21 参数错（非 from,to 两整数）→ exit 2 usage 通道。"""
    r = _invoke(["reports", "run-figures", str(ideal_s2p_path),
                 "--s21", "1", "--json"])
    assert r.exit_code == 2
    payload = json.loads(r.output)
    assert payload["ok"] is False


def test_cli_run_figures_help_hygiene() -> None:
    """--help 构建成功（#305 家族：help 特殊字符零崩溃 + 关键字在位）。"""
    r = _invoke(["reports", "run-figures", "--help"])
    assert r.exit_code == 0
    assert "run-figures" in r.output
    assert "ref-span-m" in r.output


def test_cli_run_figures_human_output(ideal_s2p_path: Path,
                                       tmp_path: Path) -> None:
    """人读分支：✓ + PNG 路径 + εeff 标量行。"""
    out_dir = tmp_path / "human_fig"
    r = _invoke(["reports", "run-figures", str(ideal_s2p_path),
                 "--ref-span-m", str(REF_SPAN_M),
                 "--out-dir", str(out_dir)])
    assert r.exit_code == 0
    assert "hfss_run_figures.png" in r.output
    assert "εeff" in r.output
