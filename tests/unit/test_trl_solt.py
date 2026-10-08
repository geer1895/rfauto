"""TRL/SOLT 校准提取内核定向门（TH-2 尾程项 12 前半席，2026-10-08）。

内核 core/trl_solt.py；只读消费 TH-2（core/thz_vna.py）八项误差模型
闭式——extender_forward_twoport 为合成裁判（独立数值来源）、
extender_correct_twoport 为修正单一事实源；TH-2 既有文件零改动。

四类钉（预声明）：
① 合成回收（#118：注入已知误差箱 → TH-2 前向合成标准件测量 → 提取 →
   真值回收，容差 1e-9）：SOLT（端口一端口三项 + thru 归一常数 k + 规范
   关系）与 TRL（line 特征根 λ / reflect γ / 七项规范不变量 d/s/r）各有
   非理想箱、有耗/无耗 line、short/open reflect、多频点逐点变参配置；
② 病态显式拒绝：开路≡短路（ρ=1）、短路≡负载（N_s=0）、开路≡负载
   （tracking 零）、thru 反向传输零、line=thru（λ=1）、line=半波长
   （λ=−1）、line 电长度跨半波长（θ∈(π,2π) 有耗无源性签名；无耗两根
   同模信息不可辨由 docstring 声明排除）、|Γref|<0.2 病态、
   0.2≤|Γref|<0.3 低于文献判据、reflect 相位 ±90° 判别边界、
   reflect_kind 非法、标准件形状不配；
③ SOLT↔TRL 交叉对拍：同误差箱两法提取，规范不变量（d/s/r）一致 + 同一
   原始 DUT 测量 apply 修正一致（1e-9）；apply_calibration 与
   extender_correct_twoport 逐点一致（TH-2 消费端对齐钉）；
④ 极限=理想箱（误差=0）提取回理想值且 apply=恒等；结果 JSON 安全。

数学口径（提取公式来源与假设）见 core/trl_solt.py 模块 docstring：
级联测量阵 R 恒等式 M12=1/R21（绝对定标锚）、SOLT 一端口三项闭式
（Pozar VNA 校准章同款）、TRL 相似变换 Q=R_line·R_thru^{-1}（Engen–Hoer
1979）与 reflect ±γ 相位歧义选根（±90° 相位先验 + Keysight |Γ|≥0.3）。
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from rfauto.core.thz_vna import (
    extender_correct_twoport,
    extender_forward_twoport,
)
from rfauto.core.trl_solt import apply_calibration, solt_extract, trl_extract

TOL = 1e-9

# 非理想真值误差箱（e12/e21 分裂任意——七项模型固有规范自由度）
BOX1 = {"ed": 0.08 + 0.03j, "es": 0.12 - 0.05j,
        "e12": 1.7 + 0.4j, "e21": 0.61 - 0.12j}
BOX2 = {"ed": -0.05 + 0.06j, "es": 0.09 + 0.04j,
        "e12": 0.83 + 0.21j, "e21": 1.24 - 0.33j}
IDEAL = {"ed": 0.0 + 0.0j, "es": 0.0 + 0.0j,
         "e12": 1.0 + 0.0j, "e21": 1.0 + 0.0j}
# 非互易 DUT（S12≠S21，端到端修正回收判 DUT 无互易假设）
DUT = np.array([[0.2 + 0.1j, 0.9 - 0.3j], [0.05 + 0.8j, 0.1 - 0.05j]])
SWAP = np.array([[0, 1], [1, 0]], dtype=complex)


def _cbox(d: complex, s: complex, e12: complex, e21: complex) -> dict:
    return {"ed": d, "es": s, "e12": e12, "e21": e21}


def _oneport_std(gamma: complex, port2: bool = False) -> np.ndarray:
    """一端口标准件（TH-2 一端口退化形态 S=[[Γ,0],[0,0]] / [[0,0],[0,Γ]]）。"""
    s = np.zeros((2, 2), dtype=complex)
    s[1 if port2 else 0, 1 if port2 else 0] = gamma
    return s


def _meas(s_dut: np.ndarray, b1: dict, b2: dict) -> np.ndarray:
    """TH-2 八项前向合成（独立数值裁判）→ 单频点仪器口径原始测量。"""
    return extender_forward_twoport(s_dut, b1, b2)[0]


def _meas_n(s_dut: np.ndarray, b1: dict, b2: dict) -> np.ndarray:
    """同上，保留 (n,2,2) 系列维（多频点标准件测量）。"""
    return extender_forward_twoport(s_dut, b1, b2)


def _solt_meas(b1: dict, b2: dict) -> dict[str, np.ndarray]:
    return {
        "short_p1": _meas(_oneport_std(-1.0), b1, b2),
        "open_p1": _meas(_oneport_std(1.0), b1, b2),
        "load_p1": _meas(_oneport_std(0.0), b1, b2),
        "short_p2": _meas(_oneport_std(-1.0, True), b1, b2),
        "open_p2": _meas(_oneport_std(1.0, True), b1, b2),
        "load_p2": _meas(_oneport_std(0.0, True), b1, b2),
        "thru": _meas(SWAP, b1, b2),
    }


def _trl_meas(b1: dict, b2: dict, lam: complex, gamma: complex,
              thru: np.ndarray | None = None) -> dict[str, np.ndarray]:
    line = np.array([[0, lam], [lam, 0]], dtype=complex)
    return {
        "thru": _meas(SWAP if thru is None else thru, b1, b2),
        "reflect_p1": _meas(_oneport_std(gamma), b1, b2),
        "reflect_p2": _meas(_oneport_std(gamma, True), b1, b2),
        "line": _meas(line, b1, b2),
    }


def _toc(pairs: list) -> np.ndarray:
    a = np.asarray(pairs, dtype=float)
    return a[:, 0] + 1j * a[:, 1]


def _box_series(model_box: dict) -> dict[str, np.ndarray]:
    return {k: _toc(v) for k, v in model_box.items()}


def _prods(box: dict[str, np.ndarray]) -> tuple[np.ndarray, ...]:
    """规范不变量 (d, s, r=e12·e21)。"""
    return box["ed"], box["es"], box["e12"] * box["e21"]


def _assert_close(a: np.ndarray | complex, b: np.ndarray | complex,
                  tol: float = TOL) -> None:
    assert np.max(np.abs(np.asarray(a) - np.asarray(b))) < tol


def _assert_json_safe(out: dict) -> None:
    json.dumps(out, ensure_ascii=False, allow_nan=False)


# ══════════════════ 一、SOLT 合成回收（#118） ══════════════════
class TestSoltRecovery:
    """①SOLT：注入已知八项 → 合成标准件 → 提取 → 真值回收（1e-9）。"""

    def test_recovery_products_and_terms(self):
        m = _solt_meas(BOX1, BOX2)
        out = solt_extract(**m)
        assert out["method"] == "solt" and out["n_points"] == 1
        b1 = _box_series(out["box1"])
        b2 = _box_series(out["box2"])
        # 规范不变量：d/s/r 逐项回收
        for ext, tru in ((b1, BOX1), (b2, BOX2)):
            _assert_close(ext["ed"], tru["ed"])
            _assert_close(ext["es"], tru["es"])
            _assert_close(ext["e12"] * ext["e21"],
                          tru["e12"] * tru["e21"])
        # 归一常数 k = e21_1/(e21_2·r1) 回收
        r1t = BOX1["e12"] * BOX1["e21"]
        k_true = BOX1["e21"] / (BOX2["e21"] * r1t)
        _assert_close(_toc(out["k"])[0], k_true)

    def test_split_gauge_relation(self):
        """规范钉：e21_2=1、e21_1=k·r1、e12_1=1/k、e12_2=r2（模块口径）。"""
        m = _solt_meas(BOX1, BOX2)
        out = solt_extract(**m)
        b1 = _box_series(out["box1"])
        b2 = _box_series(out["box2"])
        r1 = b1["e12"] * b1["e21"]
        assert b2["e21"][0] == pytest.approx(1.0, abs=1e-15)
        assert b1["e21"][0] == pytest.approx(_toc(out["k"])[0] * r1[0],
                                             rel=1e-12)
        assert b1["e12"][0] == pytest.approx(1.0 / _toc(out["k"])[0],
                                             rel=1e-12)
        assert b2["e12"][0] == pytest.approx(b2["e12"][0] * b2["e21"][0],
                                             rel=1e-15)

    def test_end_to_end_correction_nonreciprocal(self):
        """端到端：真箱合成 DUT 原始测量 → 提取模型 apply → DUT 回收。"""
        m = _solt_meas(BOX1, BOX2)
        model = solt_extract(**m)
        raw = extender_forward_twoport(DUT, BOX1, BOX2)
        corr = apply_calibration(raw, model)
        _assert_close(corr, DUT)
        # 前向-修正闭环锚：真箱修正亦回收（合成裁判自洽）
        _assert_close(extender_correct_twoport(raw, BOX1, BOX2), DUT)

    def test_series_multipoint(self):
        """多频点逐点提取：n=7 逐点变参误差箱 + 逐点变 DUT。"""
        n = 7
        def _series(c: complex, f: complex) -> np.ndarray:
            return c + f * np.arange(n)
        b1 = {"ed": _series(0.08 + 0.03j, 0.004j),
              "es": _series(0.12 - 0.05j, -0.002),
              "e12": _series(1.7 + 0.4j, 0.01j),
              "e21": _series(0.61 - 0.12j, 0.008)}
        b2 = {"ed": _series(-0.05 + 0.06j, -0.003),
              "es": _series(0.09 + 0.04j, 0.002j),
              "e12": _series(0.83 + 0.21j, -0.005j),
              "e21": _series(1.24 - 0.33j, 0.006)}
        dut = np.stack([DUT * (1.0 + 0.05 * i) for i in range(n)])
        # 每件标准件在全部 n 点各测一次（(n,2,2)，与逐点误差箱同流）
        m = {
            "short_p1": _meas_n(np.stack([_oneport_std(-1.0)] * n), b1, b2),
            "open_p1": _meas_n(np.stack([_oneport_std(1.0)] * n), b1, b2),
            "load_p1": _meas_n(np.stack([_oneport_std(0.0)] * n), b1, b2),
            "short_p2": _meas_n(np.stack([_oneport_std(-1.0, True)] * n), b1, b2),
            "open_p2": _meas_n(np.stack([_oneport_std(1.0, True)] * n), b1, b2),
            "load_p2": _meas_n(np.stack([_oneport_std(0.0, True)] * n), b1, b2),
            "thru": _meas_n(np.stack([SWAP] * n), b1, b2),
        }
        model = solt_extract(**m)
        assert model["n_points"] == n
        raw = extender_forward_twoport(dut, b1, b2)
        corr = apply_calibration(raw, model)
        _assert_close(corr, dut)
        # 规范不变量逐点回收
        sb1 = _box_series(model["box1"])
        r1t = b1["e12"] * b1["e21"]
        _assert_close(sb1["ed"], b1["ed"])
        _assert_close(sb1["es"], b1["es"])
        _assert_close(sb1["e12"] * sb1["e21"], r1t)

    def test_ideal_boxes_identity(self):
        """④极限：理想箱（误差=0）提取回理想值且 apply=恒等。"""
        m = _solt_meas(IDEAL, IDEAL)
        out = solt_extract(**m)
        b1 = _box_series(out["box1"])
        b2 = _box_series(out["box2"])
        assert np.max(np.abs(b1["ed"])) == 0.0
        assert np.max(np.abs(b1["es"])) == 0.0
        assert b1["e12"][0] * b1["e21"][0] == pytest.approx(1.0, abs=1e-15)
        assert b2["e12"][0] * b2["e21"][0] == pytest.approx(1.0, abs=1e-15)
        assert _toc(out["k"])[0] == pytest.approx(1.0, abs=1e-15)
        raw = extender_forward_twoport(DUT, IDEAL, IDEAL)
        _assert_close(apply_calibration(raw, out), DUT, tol=1e-12)

    def test_result_json_safe(self):
        _assert_json_safe(solt_extract(**_solt_meas(BOX1, BOX2)))


class TestSoltGuards:
    """②SOLT 病态显式拒绝（不静默）。"""

    def test_open_equals_short_rejected(self):
        m = _solt_meas(BOX1, BOX2)
        m["open_p1"] = m["short_p1"]  # ρ=1 → Es 不可辨
        with pytest.raises(ValueError, match="开路与短路响应重合"):
            solt_extract(**m)

    def test_short_equals_load_rejected(self):
        m = _solt_meas(BOX1, BOX2)
        m["short_p1"] = m["load_p1"]  # N_s=0
        with pytest.raises(ValueError, match="短路响应与负载响应重合"):
            solt_extract(**m)

    def test_open_equals_load_tracking_zero_rejected(self):
        m = _solt_meas(BOX1, BOX2)
        m["open_p1"] = m["load_p1"]  # N_o=0 → tracking 零
        with pytest.raises(ValueError, match="tracking 为零"):
            solt_extract(**m)

    def test_thru_transmission_zero_rejected(self):
        m = _solt_meas(BOX1, BOX2)
        # S12=0 的 DUT（隔离双端口）冒充 thru：M12=0
        m["thru"] = _meas(np.array([[0.3, 0.0], [0.0, 0.4]],
                                   dtype=complex), BOX1, BOX2)
        with pytest.raises(ValueError, match="thru 反向传输 M12=0"):
            solt_extract(**m)

    def test_shape_mismatch_rejected(self):
        m = _solt_meas(BOX1, BOX2)
        m["open_p1"] = np.stack([m["open_p1"], m["open_p1"]])  # 点数不配
        with pytest.raises(ValueError, match="点数"):
            solt_extract(**m)

    def test_bad_shape_rejected(self):
        with pytest.raises(ValueError, match="须为"):
            solt_extract(1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0)


# ══════════════════ 二、TRL 合成回收（#118） ══════════════════
class TestTrlRecovery:
    """①TRL：λ/γ/七项规范不变量回收 + 端到端修正（1e-9）。"""

    def test_recovery_lossless_line_short_reflect(self):
        lam = np.exp(-1j * 1.1)          # 无耗线，θ∈(0,π)
        gam = -0.92 + 0.15j              # short-like
        m = _trl_meas(BOX1, BOX2, lam, gam)
        out = trl_extract(**m)
        assert out["method"] == "trl"
        _assert_close(_toc(out["line_lambda"])[0], lam)
        _assert_close(_toc(out["reflect_gamma"])[0], gam)
        for key, tru in (("box1", BOX1), ("box2", BOX2)):
            ext = _box_series(out[key])
            _assert_close(ext["ed"], tru["ed"])
            _assert_close(ext["es"], tru["es"])
            _assert_close(ext["e12"] * ext["e21"],
                          tru["e12"] * tru["e21"])

    def test_recovery_lossy_line_open_reflect(self):
        lam = np.exp(-0.25 - 1j * 0.9)   # 有耗线 |λ|<1
        gam = 0.88 - 0.2j                # open-like
        m = _trl_meas(BOX1, BOX2, lam, gam)
        out = trl_extract(**m, reflect_kind="open")
        _assert_close(_toc(out["line_lambda"])[0], lam)
        _assert_close(_toc(out["reflect_gamma"])[0], gam)
        assert out["reflect_kind"] == "open"

    def test_end_to_end_correction(self):
        lam = np.exp(-0.15 - 1j * 1.3)
        gam = -0.95 + 0.05j
        model = trl_extract(**_trl_meas(BOX1, BOX2, lam, gam))
        raw = extender_forward_twoport(DUT, BOX1, BOX2)
        _assert_close(apply_calibration(raw, model), DUT)

    def test_series_multipoint(self):
        """多频点：逐点变 λ/γ/误差箱，逐点回收 + 端到端。"""
        n = 5
        lams = np.exp(-0.1 - 1j * (0.7 + 0.2 * np.arange(n)))
        gams = -0.9 - 0.02j * np.arange(n)
        b1 = {"ed": 0.08 + 0.03j, "es": 0.12 - 0.05j,
              "e12": (1.7 + 0.4j) * np.ones(n), "e21": (0.61 - 0.12j)
              + 0.01j * np.arange(n)}
        thru = np.stack([SWAP] * n)
        refl1 = np.stack([_oneport_std(g) for g in gams])
        refl2 = np.stack([_oneport_std(g, True) for g in gams])
        lines = np.stack([np.array([[0, lm], [lm, 0]], dtype=complex)
                          for lm in lams])
        raw_thru = extender_forward_twoport(thru, b1, BOX2)
        raw_r1 = extender_forward_twoport(refl1, b1, BOX2)
        raw_r2 = extender_forward_twoport(refl2, b1, BOX2)
        raw_l = extender_forward_twoport(lines, b1, BOX2)
        model = trl_extract(raw_thru, raw_r1, raw_r2, raw_l)
        assert model["n_points"] == n
        _assert_close(_toc(model["line_lambda"]), lams)
        _assert_close(_toc(model["reflect_gamma"]), gams)
        sb1 = _box_series(model["box1"])
        _assert_close(sb1["ed"], np.full(n, b1["ed"]))
        _assert_close(sb1["e12"] * sb1["e21"],
                      b1["e12"] * b1["e21"])
        dut = np.stack([DUT * (1.0 + 0.03 * i) for i in range(n)])
        raw_dut = extender_forward_twoport(dut, b1, BOX2)
        _assert_close(apply_calibration(raw_dut, model), dut)

    def test_ideal_boxes_identity(self):
        """④极限：理想箱 → d/s=0、r=1、γ/λ 回收、apply=恒等。"""
        lam = np.exp(-1j * 0.9)
        gam = -0.9 + 0.1j
        model = trl_extract(**_trl_meas(IDEAL, IDEAL, lam, gam))
        raw = extender_forward_twoport(DUT, IDEAL, IDEAL)
        _assert_close(apply_calibration(raw, model), DUT, tol=1e-12)
        sb1 = _box_series(model["box1"])
        assert np.max(np.abs(sb1["ed"])) == 0.0
        assert np.max(np.abs(sb1["es"])) == 0.0
        assert sb1["e12"][0] * sb1["e21"][0] == pytest.approx(1.0, abs=1e-12)

    def test_result_json_safe(self):
        model = trl_extract(**_trl_meas(BOX1, BOX2,
                                        np.exp(-1j * 1.1), -0.92 + 0.15j))
        _assert_json_safe(model)


class TestTrlGuards:
    """②TRL 病态显式拒绝。"""

    def test_line_zero_length_rejected(self):
        # λ=1：line 与 thru 测量重合 → 特征根简并
        m = _trl_meas(BOX1, BOX2, 1.0 + 0.0j, -0.9 + 0.1j)
        with pytest.raises(ValueError, match="电长度"):
            trl_extract(**m)

    def test_line_halfwave_rejected(self):
        # λ=−1：半波长线，同样与 thru 信息重合
        m = _trl_meas(BOX1, BOX2, -1.0 + 0.0j, -0.9 + 0.1j)
        with pytest.raises(ValueError, match="电长度"):
            trl_extract(**m)

    def test_line_inside_halfwave_upper_edge_ok(self):
        # θ→π⁻（3.0 rad）仍在合法窗：λ/γ 回收 + 端到端（审查批边界钉）
        lam = np.exp(-1j * 3.0)
        m = _trl_meas(BOX1, BOX2, lam, -0.92 + 0.15j)
        out = trl_extract(**m)
        _assert_close(_toc(out["line_lambda"])[0], lam)
        _assert_close(_toc(out["reflect_gamma"])[0], -0.92 + 0.15j)

    def test_line_beyond_halfwave_lossy_rejected_by_passivity(self):
        # θ∈(π,2π) 有耗线：arg λ 卷绕进上半平面，延迟半平面判别把 1/λ
        # 当成 λ（|λ_选中|=e^{+α}>1）——无源性签名显式拒绝，不静默错根
        lam = np.exp(-0.25 - 1j * 4.0)
        m = _trl_meas(BOX1, BOX2, lam, -0.92 + 0.15j)
        with pytest.raises(ValueError, match=r"\|λ\|.*>1"):
            trl_extract(**m)

    def test_line_small_phase_near_degeneracy_boundary_ok(self):
        # θ=1e-3 rad：远在 1e-9 相对容差的拒绝边界（≈3.2e-5 rad）之上
        lam = np.exp(-1j * 1e-3)
        m = _trl_meas(BOX1, BOX2, lam, -0.92 + 0.15j)
        out = trl_extract(**m)
        _assert_close(_toc(out["line_lambda"])[0], lam)

    def test_reflect_pathologic_magnitude_rejected(self):
        m = _trl_meas(BOX1, BOX2, np.exp(-1j * 1.1), 0.10 + 0.05j)
        with pytest.raises(ValueError, match=r"\|Γref\|"):
            trl_extract(**m)

    def test_reflect_below_literature_threshold_rejected(self):
        m = _trl_meas(BOX1, BOX2, np.exp(-1j * 1.1), 0.25 - 0.05j)
        with pytest.raises(ValueError, match="文献选根判据"):
            trl_extract(**m)

    def test_reflect_phase_boundary_rejected(self):
        # 纯虚 reflect：相位落在 ±90° 判别边界，short/open 不可辨
        m = _trl_meas(BOX1, BOX2, np.exp(-1j * 1.1), 0.95j)
        with pytest.raises(ValueError, match="判别边界"):
            trl_extract(**m)

    def test_reflect_kind_invalid_rejected(self):
        # reflect_kind 校验先于测量收敛（None 占位即可触达）
        with pytest.raises(ValueError, match="reflect_kind"):
            trl_extract(None, None, None, None,
                        reflect_kind="match")  # type: ignore[arg-type]

    def test_thru_singular_rejected(self):
        # thru 位放 S12=0 隔离件：M12=0 → R 不可定
        m = _trl_meas(BOX1, BOX2, np.exp(-1j * 1.1), -0.9 + 0.1j)
        m["thru"] = _meas(np.array([[0.2, 0.0], [0.0, 0.3]],
                                   dtype=complex), BOX1, BOX2)
        with pytest.raises(ValueError, match="M12=0"):
            trl_extract(**m)


# ══════════════ 三、SOLT↔TRL 交叉对拍与 TH-2 消费端对齐 ══════════════
class TestCrossCompareAndAlignment:
    """③④：同误差箱两法互证 + apply 与 TH-2 修正单一事实源对齐。"""

    LAM = np.exp(-0.2 - 1j * 1.2)
    GAM = -0.93 + 0.12j

    def test_gauge_invariant_products_agree(self):
        """规范不变量 d/s/r：SOLT 与 TRL 逐点一致（1e-9），且同真值。"""
        solt_model = solt_extract(**_solt_meas(BOX1, BOX2))
        trl_model = trl_extract(**_trl_meas(BOX1, BOX2, self.LAM, self.GAM))
        for key, tru in (("box1", BOX1), ("box2", BOX2)):
            a = _prods(_box_series(solt_model[key]))
            b = _prods(_box_series(trl_model[key]))
            t = (tru["ed"], tru["es"], tru["e12"] * tru["e21"])
            for x, y, tv in zip(a, b, t, strict=True):
                _assert_close(x, y)
                _assert_close(y, tv)

    def test_apply_agreement_between_methods(self):
        """同一原始 DUT 测量：两法提取模型 apply 修正一致（1e-9）。"""
        solt_model = solt_extract(**_solt_meas(BOX1, BOX2))
        trl_model = trl_extract(**_trl_meas(BOX1, BOX2, self.LAM, self.GAM))
        raw = extender_forward_twoport(DUT, BOX1, BOX2)
        _assert_close(apply_calibration(raw, solt_model),
                      apply_calibration(raw, trl_model))

    def test_apply_matches_thz_vna_correct(self):
        """消费端对齐钉：apply_calibration ≡ extender_correct_twoport。"""
        model = solt_extract(**_solt_meas(BOX1, BOX2))
        raw = extender_forward_twoport(DUT, BOX1, BOX2)
        box1 = _box_series(model["box1"])
        box2 = _box_series(model["box2"])
        _assert_close(apply_calibration(raw, model),
                      extender_correct_twoport(raw, box1, box2))

    def test_apply_rejects_bad_model(self):
        raw = extender_forward_twoport(DUT, BOX1, BOX2)
        with pytest.raises(ValueError, match="box1/box2"):
            apply_calibration(raw, {"method": "solt"})
        with pytest.raises(ValueError, match="须为 dict"):
            apply_calibration(raw, {"box1": [1, 2], "box2": {"ed": 0.0}})

    def test_ideal_apply_is_exact_identity(self):
        """④极限：误差=0 时 apply=恒等（两法，含提取自理想标准件）。"""
        raw = extender_forward_twoport(DUT, IDEAL, IDEAL)
        model_s = solt_extract(**_solt_meas(IDEAL, IDEAL))
        model_t = trl_extract(**_trl_meas(IDEAL, IDEAL, self.LAM, self.GAM))
        _assert_close(apply_calibration(raw, model_s), DUT, tol=1e-12)
        _assert_close(apply_calibration(raw, model_t), DUT, tol=1e-12)
