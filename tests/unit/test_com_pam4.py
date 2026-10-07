"""DR-1（round16）COM 参数化与 PAM4 锚树（判据预声明，合成通道全确定性）。

判据与出处（round16 DR-1 / core/com_pam4 模块 docstring 实测口径，逐条对号）：
1. PAM4 电平语义闭式：理想电平 RLM=1.0、三段眼高各 =swing/3；失配电平 RLM
   手算回收（6/7）；符号方差 93A-29（L=2→1、L=4→5/9）；Gray 映射相邻电平
   恰差 1 bit；
2. 分项噪声→COM 换算（93A-36）：手算回收 20·log10(15)；恒等式
   20log10(As)−10log10(Σvar) 一致；
3. 负例（非法电平/方差/码映射/空扫描/钉向量不可行/带宽不足/端口数/缺文件）；
4. 参数面（pychopmarg 面用 importorskip）：dj=L=4 PAM4、by=NRZ L=2 多
   preset；C_d/L_s 平铺→Tx/Rx 嵌套（sDie 消费面，TypeError 防回归钉）、
   R_d 两元、粗档旋钮、钉抽头+c0_min=0；未注册 preset（802.3ck 未随包）
   ValueError；
5. 端到端（合成 4 端口解耦对，~2s/点）：L=4 PAM4 status=ok、com_db 有限、
   分项复算 fom_db_recalc==fom_db（同源恒等复算）、均衡终态在域内、同参
   复跑确定性；pychopmarg 缺装 unavailable / 计算失败 degraded 不抛；
6. fb/抽头 sweep schema：行数/回显/单点降级不阻塞。

合成通道 = 纯 numpy 解析式（无 RNG）；COM 数值以 pychopmarg 内核为权威，
不自证精确值（802-COM 公开测试向量对照面 UNVERIFIED，见模块 docstring）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

from rfauto.core.com_pam4 import (
    AVAILABLE_PRESETS,
    PAM4_GRAY_MAP,
    UNVERIFIED_VS_802COM,
    com_db_from_terms,
    gray_adjacency_ok,
    pam4_com_params,
    pam4_eye_heights,
    pam4_levels,
    pam4_rlm,
    pam4_symbol_variance,
    run_com,
    sweep_fb,
    sweep_tx_tap,
)

F_HZ = np.arange(1e7, 20.001e9, 2e7)  # 0.01–20 GHz，20 MHz 步进（探针同款）

#: dj 粗档 PAM4 钉抽头（主抽头 1、其余 0；|v|.sum()=1 在 c0_min=0 可行域上）
DJ_PINS = (0.0, 1.0, 0.0, 0.0, 0.0, 0.0)


def _dj_coarse_params(fb_gbaud: float = 10.0, pins: tuple[float, ...] | None = DJ_PINS):
    params, note = pam4_com_params(
        "8023dj", fb_gbaud=fb_gbaud, g_dc_stride=8, g_dc2_stride=11,
        tx_taps_step=0.2, pinned_taps=pins)
    return params, note


# ---------------------------------------------------------------------------
# 合成 4 端口解耦差分对（因果 RLC 线；与 test_si_channel_service 同款解析式）
# ---------------------------------------------------------------------------

def _write_s4p_decoupled_pair(path: Path, f: np.ndarray = F_HZ) -> Path:
    w = 2.0 * np.pi * f
    r_ohm, l_h, c_f, g_s, length = 8.0, 260e-9, 130e-12, 1e-6, 0.25
    gamma = np.sqrt((r_ohm + 1j * w * l_h) * (g_s + 1j * w * c_f))
    zc = np.sqrt((r_ohm + 1j * w * l_h) / (g_s + 1j * w * c_f))
    thru = np.exp(-gamma * length) * (2.0 * zc / (zc + 50.0))
    ref = (zc - 50.0) / (zc + 50.0)
    n = f.size
    s = np.zeros((n, 4, 4), dtype=complex)
    for i, j in ((0, 1), (1, 0), (2, 3), (3, 2)):
        s[:, i, j] = thru
    for i in range(4):
        s[:, i, i] = ref
    lines = ["# HZ S RI R 50.0"]
    for k in range(n):
        parts: list[str] = [f"{f[k]:.10e}"]
        for i in range(4):
            for j in range(4):
                parts.append(f"{s[k, i, j].real:.10e}")
                parts.append(f"{s[k, i, j].imag:.10e}")
        lines.append(" ".join(parts))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_s2p(path: Path, f: np.ndarray = F_HZ) -> Path:
    """2 端口匹配线（负例：非 .s4p 后缀显式拒绝）。"""
    lines = ["# HZ S RI R 50.0"]
    for k in range(f.size):
        lines.append(f"{f[k]:.10e} 0 0 1 0 0")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# 判据 1：PAM4 电平语义（纯闭式手算回收）
# ---------------------------------------------------------------------------

class TestPam4LevelSemantics:
    def test_ideal_levels_eye_heights_and_rlm(self) -> None:
        # swing = 最外电平峰峰摆幅：swing=1 → ±0.5/±1/6，三段眼高各 1/3
        lv = pam4_levels(1.0)
        assert lv.tolist() == pytest.approx(
            [-0.5, -0.5 / 3.0, 0.5 / 3.0, 0.5])
        eh = pam4_eye_heights(lv)
        assert eh.tolist() == pytest.approx([1.0 / 3.0] * 3)
        assert pam4_rlm(lv) == pytest.approx(1.0, abs=1e-12)
        # swing 缩放：三段眼高各 = swing/3
        lv2 = pam4_levels(6.0)
        assert lv2.tolist() == pytest.approx([-3.0, -1.0, 1.0, 3.0])
        assert pam4_eye_heights(lv2).tolist() == pytest.approx([2.0] * 3)
        assert pam4_rlm(lv2) == pytest.approx(1.0, abs=1e-12)

    def test_rlm_mismatched_levels_handcalc(self) -> None:
        # 失配电平 {-3,-1,1,2.6}：眼高 (2,2,1.6)、平均 (5.6)/3 → RLM = 1.6/1.8666… = 6/7
        lv = np.array([-3.0, -1.0, 1.0, 2.6])
        assert pam4_rlm(lv) == pytest.approx(6.0 / 7.0, rel=1e-12)

    def test_symbol_variance_93a29(self) -> None:
        # (L²−1)/(3(L−1)²)：NRZ→1、PAM4→5/9、L=6→7/15
        assert pam4_symbol_variance(2) == pytest.approx(1.0)
        assert pam4_symbol_variance(4) == pytest.approx(5.0 / 9.0, rel=1e-12)
        assert pam4_symbol_variance(6) == pytest.approx(7.0 / 15.0, rel=1e-12)

    def test_gray_mapping_adjacency(self) -> None:
        assert PAM4_GRAY_MAP == ((0, 0), (0, 1), (1, 1), (1, 0))
        assert gray_adjacency_ok(PAM4_GRAY_MAP) is True
        # 二进制序映射 01→10 差 2 bit → 非 Gray
        assert gray_adjacency_ok(((0, 0), (0, 1), (1, 0), (1, 1))) is False
        assert gray_adjacency_ok(((0, 0),)) is False


# ---------------------------------------------------------------------------
# 判据 2：分项噪声→COM 换算（93A-36）手算回收
# ---------------------------------------------------------------------------

class TestComFromTerms:
    def test_handcalc_recovery(self) -> None:
        # As=0.3、σ=√(1e-4+3e-4)=0.02 → COM = 20·log10(15)
        com = com_db_from_terms(0.3, 0.0, 1e-4, 0.0, 0.0, 3e-4)
        assert com == pytest.approx(20.0 * np.log10(15.0), rel=1e-12)

    def test_identity_vs_log_domain(self) -> None:
        vars_ = (4e-4, 2.5e-4, 1e-5, 3e-3, 2e-6)
        com = com_db_from_terms(0.42, *vars_)
        expect = 20.0 * np.log10(0.42) - 10.0 * np.log10(sum(vars_))
        assert com == pytest.approx(expect, rel=1e-12)

    def test_docstring_semantics_pin_c2_1(self) -> None:
        """审查 C2-1 口径收口钉：函数与模块 docstring 必须明示『非标准
        final-COM』口径差异（优化 FOM ≠ final-COM，缺 DER/Ani/BER 因子），
        防止后续把 fom 复算误当 final-COM 权威消费。"""
        fn_doc = com_db_from_terms.__doc__ or ""
        assert "非标准" in fn_doc, "com_db_from_terms docstring 须含『非标准』字样（C2-1）"
        assert "final-COM" in fn_doc
        assert "DER" in fn_doc and "Ani" in fn_doc
        assert "C2-1" in fn_doc
        mod_doc = sys.modules["rfauto.core.com_pam4"].__doc__ or ""
        assert "非标准 final-COM" in mod_doc, (
            "模块级注记须含『非标准 final-COM』字样（C2-1）")


# ---------------------------------------------------------------------------
# 判据 3：负例（非法电平/方差/码映射/空扫描/钉向量不可行）
# ---------------------------------------------------------------------------

class TestNegativeCases:
    def test_illegal_levels(self) -> None:
        with pytest.raises(ValueError, match="swing"):
            pam4_levels(0.0)
        with pytest.raises(ValueError, match="4 个"):
            pam4_eye_heights(np.array([0.0, 1.0, 2.0]))
        with pytest.raises(ValueError, match="升序"):
            pam4_rlm(np.array([3.0, 1.0, 2.0, 0.0]))

    def test_illegal_terms(self) -> None:
        with pytest.raises(ValueError, match="As"):
            com_db_from_terms(0.0, 1e-4, 0, 0, 0, 0)
        with pytest.raises(ValueError, match="非负"):
            com_db_from_terms(1.0, -1e-4, 0, 0, 0, 0)
        with pytest.raises(ValueError, match="总和为零"):
            com_db_from_terms(1.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    def test_symbol_variance_needs_l_ge2(self) -> None:
        with pytest.raises(ValueError, match="≥2"):
            pam4_symbol_variance(1)

    def test_preset_knobs_negative(self) -> None:
        pytest.importorskip("pychopmarg", reason="pychopmarg 缺装")
        with pytest.raises(ValueError, match="未知 preset"):
            pam4_com_params("8023ck")  # 802.3ck 未随包，如实不含（不凭记忆造数值）
        with pytest.raises(ValueError, match="≥1"):
            pam4_com_params("8023dj", g_dc_stride=0)
        with pytest.raises(ValueError, match="长度"):
            pam4_com_params("8023dj", pinned_taps=(0.0, 1.0, 0.0))
        with pytest.raises(ValueError, match="可行域"):
            pam4_com_params("8023dj", pinned_taps=(0.0, 1.2, 0.0, 0.0, 0.0, 0.0))
        with pytest.raises(ValueError, match="fb_gbaud"):
            pam4_com_params("8023dj", fb_gbaud=-1.0)

    def test_sweep_empty_fb_list(self, tmp_path: Path) -> None:
        s4p = _write_s4p_decoupled_pair(tmp_path / "thru.s4p")
        with pytest.raises(ValueError, match="空扫描"):
            sweep_fb(s4p, fb_list_gbaud=(), params_factory=lambda fb: None)


# ---------------------------------------------------------------------------
# 判据 4：参数面（多 preset / 嵌套映射 / 粗档旋钮 / 钉抽头）
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not AVAILABLE_PRESETS, reason="preset 注册表为空")
class TestPam4ComParams:
    def test_dj_is_pam4(self) -> None:
        pytest.importorskip("pychopmarg", reason="pychopmarg 缺装")
        params, note = pam4_com_params("8023dj")
        assert params.L == 4
        assert params.fb == pytest.approx(106.25)
        assert params.RLM == 0.95
        # 平铺→Tx/Rx 嵌套（sDie 消费面：C_d[ix] 须可 len()，TypeError 防回归钉）
        cd = np.asarray(params.C_d, dtype=object)
        assert len(cd) == 2 and len(cd[0]) == 3 and len(cd[1]) == 3
        ls = np.asarray(params.L_s, dtype=object)
        assert len(ls) == 2 and len(ls[0]) == 3
        assert len(params.R_d) == 2
        assert len(params.C_b) == 2 and len(params.C_p) == 2
        assert "8023dj" in note and UNVERIFIED_VS_802COM in note

    def test_by_is_nrz(self) -> None:
        pytest.importorskip("pychopmarg", reason="pychopmarg 缺装")
        params, _ = pam4_com_params("8023by")
        assert params.L == 2
        assert params.fb == pytest.approx(25.78125)
        assert len(params.R_d) == 2

    def test_coarse_knobs(self) -> None:
        pytest.importorskip("pychopmarg", reason="pychopmarg 缺装")
        params, _ = _dj_coarse_params()
        assert params.fb == pytest.approx(10.0)
        assert list(params.g_DC) == [0, -8]  # 16 档 stride 8
        assert list(params.g_DC2) == [0.0]  # 11 档 stride 11
        assert params.tx_taps_min == params.tx_taps_max == list(DJ_PINS)
        assert params.c0_min == 0.0  # 钉组合须过 (1-|v|.sum())≥c0_min 滤波
        assert all(s > 0 for s in params.tx_taps_step)  # step=0 → 恒 [0.0] 陷阱


# ---------------------------------------------------------------------------
# 判据 5：端到端（pychopmarg 权威；~2s/点，单独类便于定向挑选）
# ---------------------------------------------------------------------------

class TestRunComEndToEnd:
    def test_pam4_l4_schema_and_decomposition(self, tmp_path: Path) -> None:
        pytest.importorskip("pychopmarg", reason="pychopmarg 缺装")
        s4p = _write_s4p_decoupled_pair(tmp_path / "thru.s4p")
        params, note = _dj_coarse_params()
        rslt = run_com(s4p, params=params, params_note=note)
        assert rslt["ok"] is True and rslt["status"] == "ok"
        com_db = rslt["com_db"]
        assert com_db is not None and np.isfinite(com_db)
        assert 0.0 < com_db < 60.0  # 数值带（精确值不自证——内核权威）
        assert rslt["params"]["L"] == 4
        assert rslt["params"]["opt_mode"] == "PRZF"  # 93A 规格路线（FOM=93A-36）
        assert rslt["as_v"] > 0.0
        # 分项闭式复算与内核 FOM 恒等（同源数字复算，非独立裁判）
        sig = rslt["sigma_v"]
        recalc = com_db_from_terms(
            rslt["as_v"], sig["tx"] ** 2, sig["isi"] ** 2, sig["jitter"] ** 2,
            sig["xt"] ** 2, sig["thermal"] ** 2)
        assert recalc == pytest.approx(rslt["fom_db"], rel=1e-9)
        # 均衡终态在域内：零向量 + 钉组合 = 2 组合；CTLE 档命中粗档表
        eq = rslt["eq"]
        assert eq["n_tx_combs"] == 2
        assert eq["g_dc"] in (0.0, -8.0)
        assert rslt["cursor_ix"] > 0
        assert len(eq["rx_taps"]) == 16 and len(eq["dfe_taps"]) == 1  # dj 缺省面
        # 对照面诚实标记 + 带宽外推如实注记（20 GHz < 内核 Nyquist 160 GHz）
        assert rslt["verification"] == UNVERIFIED_VS_802COM
        assert rslt["coverage_note"] is not None and "外推" in rslt["coverage_note"]
        assert rslt["wall_time_s"] > 0.0
        assert rslt["pychopmarg_version"] is not None

    def test_deterministic_rerun(self, tmp_path: Path) -> None:
        pytest.importorskip("pychopmarg", reason="pychopmarg 缺装")
        s4p = _write_s4p_decoupled_pair(tmp_path / "thru.s4p")
        params, _ = _dj_coarse_params()
        a = run_com(s4p, params=params)
        b = run_com(s4p, params=params)
        assert a["com_db"] == pytest.approx(b["com_db"], abs=1e-9)

    def test_input_contract_errors_raise(self, tmp_path: Path) -> None:
        pytest.importorskip("pychopmarg", reason="pychopmarg 缺装")
        params, _ = _dj_coarse_params()
        with pytest.raises(FileNotFoundError):
            run_com(tmp_path / "nope.s4p", params=params)
        s2p = _write_s2p(tmp_path / "thru.s2p")
        with pytest.raises(ValueError, match=r"\.s4p"):
            run_com(s2p, params=params)
        # 带宽不足（源 0.01–5 GHz < fb=10 GHz）→ 采样率不足显式拒绝
        narrow = _write_s4p_decoupled_pair(tmp_path / "narrow.s4p",
                                           f=F_HZ[F_HZ <= 5e9])
        with pytest.raises(ValueError, match="采样率不足"):
            run_com(narrow, params=params)
        good = _write_s4p_decoupled_pair(tmp_path / "good.s4p")
        with pytest.raises(ValueError, match="opt_mode"):
            run_com(good, params=params, opt_mode="bogus")

    def test_nports_guard_via_stub(self, tmp_path: Path, monkeypatch) -> None:
        s4p = _write_s4p_decoupled_pair(tmp_path / "thru.s4p")

        class _FakeNet:  # 模拟非 4 端口网络（skrf 按扩展名推断 rank，#248 口径）
            nports = 2
            f = np.array([1e9])

        class _FakeSkrf:
            Network = staticmethod(lambda _p: _FakeNet())

        monkeypatch.setitem(sys.modules, "skrf", _FakeSkrf)
        with pytest.raises(ValueError, match="2 端口"):
            run_com(s4p, params=object())

    def test_pychopmarg_missing_unavailable(self, tmp_path: Path,
                                            monkeypatch) -> None:
        pytest.importorskip("pychopmarg", reason="pychopmarg 缺装")
        s4p = _write_s4p_decoupled_pair(tmp_path / "thru.s4p")
        params, note = _dj_coarse_params()
        monkeypatch.setitem(sys.modules, "pychopmarg.com", None)
        rslt = run_com(s4p, params=params, params_note=note)
        assert rslt["ok"] is True and rslt["status"] == "unavailable"
        assert rslt["com_db"] is None and "pychopmarg" in rslt["note"]

    def test_compute_failure_degrades_not_raises(self, tmp_path: Path,
                                                 monkeypatch) -> None:
        pytest.importorskip("pychopmarg", reason="pychopmarg 缺装")
        s4p = _write_s4p_decoupled_pair(tmp_path / "thru.s4p")
        params, _ = _dj_coarse_params()

        def _boom(*_a: object, **_k: object) -> None:
            raise RuntimeError("boom")

        monkeypatch.setattr("pychopmarg.com.COM", _boom)
        rslt = run_com(s4p, params=params)
        assert rslt["ok"] is True and rslt["status"] == "degraded"
        assert "RuntimeError" in rslt["note"]


# ---------------------------------------------------------------------------
# 判据 6：fb / 抽头 sweep schema
# ---------------------------------------------------------------------------

class TestSweeps:
    def test_fb_sweep_schema(self, tmp_path: Path) -> None:
        pytest.importorskip("pychopmarg", reason="pychopmarg 缺装")
        s4p = _write_s4p_decoupled_pair(tmp_path / "thru.s4p")
        rows = sweep_fb(
            s4p, fb_list_gbaud=(12.0, 16.0),  # COMParams fb ∈ [10, 300]（实测）
            params_factory=lambda fb: _dj_coarse_params(fb)[0])
        assert [r["fb_gbaud"] for r in rows] == [12.0, 16.0]
        for row in rows:
            assert row["status"] == "ok"
            assert row["com_db"] is not None and np.isfinite(row["com_db"])

    def test_tx_tap_sweep_schema_and_infeasible_pin(self, tmp_path: Path) -> None:
        pytest.importorskip("pychopmarg", reason="pychopmarg 缺装")
        s4p = _write_s4p_decoupled_pair(tmp_path / "thru.s4p")
        base, _ = _dj_coarse_params()  # 钉基 [0,1,0,0,0,0]：每点 1 钉组合，秒级
        # 主抽头钉 0.9 给扫描留可行域（|v|.sum() ≤ 1，预检显式拒绝越界值）
        base_taps = (0.0, 0.9, 0.0, 0.0, 0.0, 0.0)
        rows = sweep_tx_tap(s4p, tap_ix=0, values=(0.0, -0.05),
                            base_params=base, base_taps=base_taps)
        assert [r["tap_value"] for r in rows] == [0.0, -0.05]
        for row in rows:
            assert row["tx_taps"][0] == pytest.approx(row["tap_value"])
            assert row["tx_taps"][1] == pytest.approx(0.9)
            assert row["status"] == "ok"
            assert row["com_db"] is not None and np.isfinite(row["com_db"])
        # 扫描值使钉向量不可行（|-0.2|+0.9 > 1）→ 整列契约错误显式抛
        with pytest.raises(ValueError, match=r"可行域|sum"):
            sweep_tx_tap(s4p, tap_ix=0, values=(0.0, -0.2), base_params=base,
                         base_taps=base_taps)

    def test_sweep_single_point_failure_degrades(self, tmp_path: Path,
                                                 monkeypatch) -> None:
        pytest.importorskip("pychopmarg", reason="pychopmarg 缺装")
        s4p = _write_s4p_decoupled_pair(tmp_path / "thru.s4p")
        # 非法 fb（≤0）让 params_factory 抛 → 该行 degraded，不阻塞整列
        rows = sweep_fb(s4p, fb_list_gbaud=(10.0, -1.0),
                        params_factory=lambda fb: pam4_com_params(
                            "8023dj", fb_gbaud=fb, g_dc_stride=16,
                            g_dc2_stride=11, pinned_taps=DJ_PINS)[0])
        assert rows[0]["status"] == "ok"
        assert rows[1]["status"] == "degraded" and "fb_gbaud" in rows[1]["note"]
