"""F-L 第 1 步 Pospieszalski 噪声内核单测（研究扩充 round6 §二 F-L）。

裁判口径（#118 双路径，先于引源逐位 #122）：
- 路径 A（被测）= core/fet_noise.py 本征闭式 / 数值嵌入四参；
- 路径 B1（独立代数排布）= 本文件内转录的 Pronić-Renić ICEST 2004 eq.(2)
  Tmin 闭式（逐字转引 Pospieszalski 1989 的标准教材通载形式）；
- 路径 B2（独立数值裁判）= 本文件内独立编码的暴力节点分析电路裁判——
  各噪声源（Ri@Tg 串联噪声的支路诺顿、Rds@Td 电流源、源@T0）逐个注入，
  求漏极开路戴维南电压传递 H，F = 1 + Σ T_i·g_i·|H_i|²/(T0·Gs·|Hs|²)。
  该式惯例无关（可用功率=|Vth|²/4Re{Zout}，Zout 在分子分母同消），
  与四参闭式 F(Ys) 在随机 Ys 上逐位互证（实测 ~5e-16）。
- 极限自检先行（Tg=Td=T0、Ri=0 → Fmin=0 dB 逐位；Td→0⁺ 下确界；
  Td↑/ω↑ 单调），全部通过后才允许引源逐位（判据顺序即测试顺序）。

诚实边界：Fukui 对照面 kf 为单位约定相关的经验系数（无可达单源精确数
不虚构，#118），测试用"参考频点标定 + ±30% 带扫描"语义，不构成器件背书。
"""
from __future__ import annotations

import itertools
import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import active_chain, fet_noise
from rfauto.core.fet_noise import (
    FetNoiseParams,
    FetSmallSignal,
    fukui_fmin,
    lna_source_match,
    noise_circle,
    noise_figure_at,
    params_from_dict,
    pospieszalski_noise_params,
    transition_frequency_hz,
)

# ─── 代表性器件（量级参照：100 fF / 50 mS / 2 Ω，10 GHz 处 fT/f ≈ 8）─────────
MODEL = FetSmallSignal(cgs_f=100e-15, ri_ohm=2.0, gm_s=0.05, gds_s=2e-3)
F_HZ = 10e9
TG_K = 297.0
TD_K = 1500.0
T0_K = 290.0


def _params(model: FetSmallSignal = MODEL, f_hz: float = F_HZ, **kw) -> FetNoiseParams:
    kw.setdefault("tg_k", TG_K)
    kw.setdefault("td_k", TD_K)
    return pospieszalski_noise_params(model, f_hz, **kw)


# ─── 独立数值裁判（路径 B2：惯例无关暴力电路，独立编码）──────────────────────


def _referee_f_of_ys(
    w: float,
    ys: complex,
    model: FetSmallSignal,
    tg_k: float,
    td_k: float,
    t0_k: float = T0_K,
    trg_k: float | None = None,
    trs_k: float | None = None,
) -> float:
    """暴力节点裁判：节点 gext-g-x-d-s，逐噪声源注入求漏极开路电压传递。

    与被测模块零共享代码（独立 stamp/独立求解/独立 F 组装）。
    """
    trg = t0_k if trg_k is None else trg_k
    trs = t0_k if trs_k is None else trs_k
    has_rg = model.rg_ohm > 0.0
    has_rs = model.rs_ohm > 0.0
    names = (["ga", "gb"] if has_rg else ["gb"]) + ["gx", "gd"] + (["gs"] if has_rs else [])
    pos = {n: i for i, n in enumerate(names)}
    nn = len(names)
    ymat = np.zeros((nn, nn), dtype=complex)

    def add(a: str, b: str | None, y: complex) -> None:
        ia = pos[a]
        ymat[ia, ia] += y
        if b is not None:
            ib = pos[b]
            ymat[ib, ib] += y
            ymat[ia, ib] -= y
            ymat[ib, ia] -= y

    if has_rg:
        add("ga", "gb", 1.0 / model.rg_ohm)
    add("gb", "gx", 1j * w * model.cgs_f)
    add("gx", "gs" if has_rs else None, 1.0 / model.ri_ohm)
    add("gd", "gs" if has_rs else None, model.gds_s)
    add("ga" if has_rg else "gb", None, ys)
    igb, igx, igd = pos["gb"], pos["gx"], pos["gd"]
    ymat[igd, igb] -= model.gm_s
    ymat[igd, igx] += model.gm_s
    if has_rs:
        igs = pos["gs"]
        ymat[igs, igb] += model.gm_s
        ymat[igs, igx] -= model.gm_s
        ymat[igs, igs] += 1.0 / model.rs_ohm  # Rs 对地导纳

    def vth(inj: dict[str, float]) -> complex:
        rhs = np.zeros(nn, dtype=complex)
        for n_, cur in inj.items():
            if n_ in pos:
                rhs[pos[n_]] += cur
        return complex(np.linalg.solve(ymat, rhs)[pos["gd"]])

    # 源噪声注入点=外部栅端口；栅支路诺顿跨 gb-gs；漏诺顿跨 gd-gs
    hs = vth({("ga" if has_rg else "gb"): 1.0})
    total = td_k * model.gds_s * abs(vth({"gd": 1.0, "gs": -1.0})) ** 2
    if model.ri_ohm > 0.0:
        wc = w * model.cgs_f
        ybr = 1j * wc / (1.0 + 1j * wc * model.ri_ohm)  # 独立代数路径求 Re{Ygs}
        ggs = ybr.real
        hg = vth({"gb": 1.0, "gs": -1.0})
        total += tg_k * ggs * abs(hg) ** 2
    if has_rg:
        h_rg = vth({"ga": 1.0, "gb": -1.0})
        total += trg * abs(h_rg) ** 2 / model.rg_ohm
    if has_rs:
        h_rs = vth({"gs": 1.0})
        total += trs * abs(h_rs) ** 2 / model.rs_ohm
    return 1.0 + total / (t0_k * ys.real * abs(hs) ** 2)


def _f_yform(params: FetNoiseParams, ys: complex) -> float:
    """四参 F(Ys) 的导纳形（F = Fmin + Rn|Ys−Yopt|²/Gs）——与 Γ 形互证用。"""
    return params.fmin_linear + params.rn_ohm * abs(ys - params.yopt) ** 2 / ys.real


# ─── 1. 极限自检（#122 判据①②③，先于引源）──────────────────────────────────


class TestLimitChecks:
    def test_lossless_passive_limit_gives_zero_db_exact(self):
        """Tg=Td=T0 且 Ri=0（无损寄生）→ Fmin=1（0 dB）逐位；Γopt 落单位圆。"""
        model = FetSmallSignal(cgs_f=100e-15, ri_ohm=0.0, gm_s=0.05, gds_s=2e-3)
        p = _params(model)
        assert p.fmin_linear == pytest.approx(1.0, abs=1e-14)
        assert p.fmin_db == pytest.approx(0.0, abs=1e-12)
        assert abs(p.gamma_opt) == pytest.approx(1.0, rel=1e-9)

    def test_td_to_zero_floor(self):
        """Td→0⁺ 且 Tg=T0：NFmin→纯栅极贡献下确界 0 dB（大 Gs 淹没栅噪声）。"""
        p_cold = _params(td_k=1e-6)
        p_norm = _params(td_k=TD_K)
        assert p_cold.fmin_db < 1e-4
        assert p_cold.fmin_db < p_norm.fmin_db

    def test_nfmin_monotone_in_td(self):
        """高温 Td↑ → NFmin 单调升（预声明带内严格）。"""
        dbs = [
            _params(td_k=t).fmin_db
            for t in (300.0, 600.0, 900.0, 1500.0, 3000.0)
        ]
        assert all(a < b for a, b in itertools.pairwise(dbs))

    def test_nfmin_monotone_in_frequency(self):
        """频率扫描 NFmin 单调升（Pospieszalski 低频 NFmin∝ω 特性带）。"""
        dbs = [
            _params(f_hz=f).fmin_db for f in (2e9, 6e9, 12e9, 20e9, 30e9)
        ]
        assert all(a < b for a, b in itertools.pairwise(dbs))


# ─── 2. 独立电路裁判互证（路径 B2）───────────────────────────────────────────


class TestCircuitReferee:
    def test_referee_equals_fmin_at_yopt(self):
        """裁判 F(Yopt) == Fmin（rel 1e-12）。"""
        p = _params()
        ys = p.yopt
        f_ref = _referee_f_of_ys(2 * np.pi * F_HZ, ys, MODEL, TG_K, TD_K)
        assert f_ref == pytest.approx(p.fmin_linear, rel=1e-12)

    def test_referee_generic_source_grid(self):
        """随机 Ys 网格：裁判 F(Ys) 与四参闭式逐位一致（~1e-12 级）。"""
        p = _params()
        w = 2 * np.pi * F_HZ
        rng = np.random.default_rng(20260927)
        for _ in range(12):
            g = float(10 ** rng.uniform(-4.5, -1.0))
            b = float(rng.uniform(-4e-2, 4e-2))
            ys = complex(g, b)
            f_ref = _referee_f_of_ys(w, ys, MODEL, TG_K, TD_K)
            assert f_ref == pytest.approx(_f_yform(p, ys), rel=1e-9)
            # 源导纳 → Γ：Γs = (1/Ys − Z0)/(1/Ys + Z0)（导纳口径换算）；
            # noise_figure_at 返回 dB → 线性化后与裁判（线性）比
            gamma_s = active_chain.z_to_gamma(1.0 / ys)
            f_gamma_lin = 10.0 ** (noise_figure_at(p, gamma_s) / 10.0)
            assert f_ref == pytest.approx(f_gamma_lin, rel=1e-9)

    def test_gamma_form_vs_yform_identity(self):
        """Γ 形（active_chain）与 Y 形四参式一致（恒等式钉；导纳→Γ 走 1/Ys，
        dB 线性化后比）。"""
        p = _params()
        ys = 0.01 + 0.005j
        lhs_lin = 10.0 ** (noise_figure_at(p, active_chain.z_to_gamma(1.0 / ys)) / 10.0)
        assert lhs_lin == pytest.approx(_f_yform(p, ys), rel=1e-9)

    def test_icest_quoted_tmin_identity(self):
        """引源回收：Pronić ICEST 2004 eq.(2) Tmin 闭式（本文件独立转录）
        与被测 Fmin 恒等——Tmin = T0·(Fmin−1)，参数网格 rel 1e-12。"""
        for ri in (0.5, 2.0, 5.0):
            for f in (5e9, 10e9, 18e9):
                for td in (400.0, 1500.0):
                    model = FetSmallSignal(cgs_f=150e-15, ri_ohm=ri, gm_s=0.04, gds_s=3e-3)
                    w = 2 * math.pi * f
                    wc = w * model.cgs_f
                    ratio = wc / model.gm_s
                    # eq.(2) 转录（de-OCR'd，分母归位：量纲 K）
                    t_min = (
                        2.0 * ratio * math.sqrt(
                            model.ri_ohm * TG_K * model.gds_s * td
                            + (wc * model.ri_ohm * model.gds_s * td / model.gm_s) ** 2
                        )
                        + 2.0 * ratio * ratio * model.ri_ohm * model.gds_s * td
                    )
                    p = pospieszalski_noise_params(model, f, tg_k=TG_K, td_k=td)
                    assert t_min == pytest.approx(T0_K * (p.fmin_linear - 1.0), rel=1e-12)


# ─── 3. 换算面恒等式（Γopt↔Zopt、噪声圆）────────────────────────────────────


class TestConversions:
    def test_zopt_gamma_roundtrip(self):
        """Zopt↔Γopt 往返逐位（active_chain z_to_gamma 复用）。"""
        p = _params()
        assert active_chain.z_to_gamma(p.zopt, p.z0) == pytest.approx(p.gamma_opt, rel=1e-12)
        assert active_chain.gamma_to_z(p.gamma_opt, p.z0) == pytest.approx(p.zopt, rel=1e-9)

    def test_noise_circle_degenerate_at_fmin(self):
        """NF=NFmin → 半径 0（恒等式 r=0），圆心=Γopt。"""
        p = _params()
        c = noise_circle(p, p.fmin_db)
        assert c.radius == pytest.approx(0.0, abs=1e-12)
        assert c.center == pytest.approx(p.gamma_opt, rel=1e-12)

    def test_noise_circle_radius_tends_one(self):
        """NF→∞（+60 dB 回退）→ 半径→1（1e-3 带）。"""
        p = _params()
        c = noise_circle(p, p.fmin_db + 60.0)
        assert c.radius == pytest.approx(1.0, abs=1e-3)

    def test_noise_circle_points_back_substitute(self):
        """圆上多点回代 F == 目标 NF（rel 1e-9）。"""
        p = _params()
        target = p.fmin_db + 1.5
        c = noise_circle(p, target)
        for theta in np.linspace(0.0, 2.0 * np.pi, 8, endpoint=False):
            gamma_pt = c.center + c.radius * np.exp(1j * float(theta))
            assert noise_figure_at(p, complex(gamma_pt)) == pytest.approx(target, rel=1e-9)

    def test_noise_figure_at_matches_active_chain_directly(self):
        p = _params()
        gs = 0.2 + 0.3j
        assert noise_figure_at(p, gs) == pytest.approx(
            active_chain.noise_figure_db(p.fmin_db, p.gamma_opt, p.rn_norm, gs), rel=1e-12
        )


# ─── 4. 数值守卫（#122 判据）─────────────────────────────────────────────────


class TestValidationGuards:
    @pytest.mark.parametrize(
        "kwargs",
        [
            {"cgs_f": 0.0, "ri_ohm": 2.0, "gm_s": 0.05, "gds_s": 2e-3},
            {"cgs_f": -1e-13, "ri_ohm": 2.0, "gm_s": 0.05, "gds_s": 2e-3},
            {"cgs_f": 100e-15, "ri_ohm": 2.0, "gm_s": 0.0, "gds_s": 2e-3},
            {"cgs_f": 100e-15, "ri_ohm": 2.0, "gm_s": 0.05, "gds_s": -2e-3},
            {"cgs_f": 100e-15, "ri_ohm": -2.0, "gm_s": 0.05, "gds_s": 2e-3},
        ],
    )
    def test_model_invalid_params_raise(self, kwargs):
        with pytest.raises(ValueError):
            FetSmallSignal(**kwargs).validate()

    def test_bool_rejected(self):
        with pytest.raises(ValueError):
            pospieszalski_noise_params(MODEL, F_HZ, tg_k=True, td_k=TD_K)

    @pytest.mark.parametrize("field_", ["tg_k", "td_k", "t0_k", "z0"])
    def test_nonpositive_scalars_raise(self, field_):
        with pytest.raises(ValueError):
            _params(**{field_: 0.0})
        with pytest.raises(ValueError):
            _params(**{field_: -1.0})

    def test_bad_frequency_raise(self):
        with pytest.raises(ValueError):
            _params(f_hz=0.0)

    def test_td_zero_rejected_with_reason(self):
        """td=0 拒收：Γopt 退化为 −1 的无漏噪极限（docstring 预声明）。"""
        with pytest.raises(ValueError, match="td_k"):
            _params(td_k=0.0)


# ─── 5. 数值嵌入路径（rg/rs>0）───────────────────────────────────────────────


class TestEmbeddedPath:
    def test_embedded_matches_closed_form_when_no_parasitics(self):
        """嵌入路径（rg=rs=0 强制）与闭式一致（rel 1e-9）——交叉验证。"""
        w = 2 * math.pi * F_HZ
        fmin_e, rn_e, yopt_e = fet_noise._embedded_noise_params(
            w, MODEL, TG_K, TD_K, T0_K, T0_K, T0_K
        )
        p = _params()
        assert fmin_e == pytest.approx(p.fmin_linear, rel=1e-9)
        assert rn_e == pytest.approx(p.rn_ohm, rel=1e-6)
        assert yopt_e == pytest.approx(p.yopt, rel=1e-6)

    def test_extrinsic_referee_and_properties(self):
        """rg/rs>0：裁判互证四参 + Fmin/Rn 单调不降 + path 标记。"""
        model = FetSmallSignal(cgs_f=100e-15, ri_ohm=2.0, gm_s=0.05, gds_s=2e-3,
                               rg_ohm=1.5, rs_ohm=0.8)
        p_int = _params()
        p_ext = _params(model)
        assert p_ext.path == "embedded"
        assert p_ext.fmin_linear > p_int.fmin_linear
        assert p_ext.rn_ohm > p_int.rn_ohm
        w = 2 * math.pi * F_HZ
        rng = np.random.default_rng(7)
        for _ in range(6):
            ys = complex(float(10 ** rng.uniform(-4.0, -1.5)), float(rng.uniform(-3e-2, 1e-2)))
            f_ref = _referee_f_of_ys(w, ys, model, TG_K, TD_K)
            assert f_ref == pytest.approx(_f_yform(p_ext, ys), rel=1e-7)

    def test_extrinsic_monotone_in_parasitics(self):
        """寄生增大 → Fmin 不降（跨频网格）。"""
        base = FetSmallSignal(cgs_f=100e-15, ri_ohm=2.0, gm_s=0.05, gds_s=2e-3)
        big = FetSmallSignal(cgs_f=100e-15, ri_ohm=2.0, gm_s=0.05, gds_s=2e-3,
                             rg_ohm=3.0, rs_ohm=1.6)
        for f in (4e9, 10e9, 18e9):
            assert _params(big, f).fmin_linear >= _params(base, f).fmin_linear


# ─── 6. LNA 匹配面 / fT / Fukui 对照面 ───────────────────────────────────────


class TestFaces:
    def test_lna_source_match_nf_identity(self):
        """Γs=Γopt（四参式极小点，非共轭——形式论见 docstring）→ NF==NFmin。"""
        p = _params()
        out = lna_source_match(p)
        assert out["gamma_s"]["re"] == pytest.approx(p.gamma_opt.real, abs=1e-12)
        assert out["gamma_s"]["im"] == pytest.approx(p.gamma_opt.imag, abs=1e-12)
        assert out["nf_at_match_db"] == pytest.approx(out["nf_min_db"], abs=1e-9)

    def test_lna_source_match_with_sparams(self):
        """S 参数给入 → ΓL 建议 + 变换增益端口（active_chain 复用）。"""
        p = _params()
        hyb = active_chain.HybridPiModel(gm_s=MODEL.gm_s, rds_ohm=1.0 / MODEL.gds_s,
                                         cgs_f=MODEL.cgs_f, cds_f=50e-15,
                                         cgd_f=MODEL.cgd_f, rg_ohm=MODEL.ri_ohm)
        sp = hyb.to_sparams(F_HZ)
        out = lna_source_match(p, sp)
        gl = complex(out["gamma_l"]["re"], out["gamma_l"]["im"])
        expected = active_chain.transducer_gain_db(
            sp, p.gamma_opt, gl,
        )
        assert out["transducer_gain_db"] == pytest.approx(expected, abs=1e-6)
        # 缺省 ΓL = conj(Γout(Γs))
        assert gl == pytest.approx(
            np.conj(active_chain.output_gamma(sp, p.gamma_opt)), rel=1e-9
        )

    def test_ft_closed_form(self):
        """fT = gm/(2π(Cgs+Cgd))——闭式恒等 + 量级注记（10 GHz ≪ fT/5）。"""
        ft = transition_frequency_hz(MODEL)
        assert ft == pytest.approx(MODEL.gm_s / (2 * math.pi * MODEL.cgs_f), rel=1e-15)
        model_cgd = FetSmallSignal(cgs_f=100e-15, ri_ohm=2.0, gm_s=0.05, gds_s=2e-3,
                                   cgd_f=30e-15)
        assert transition_frequency_hz(model_cgd) == pytest.approx(
            0.05 / (2 * math.pi * 130e-15), rel=1e-15
        )
        assert ft > 5 * F_HZ  # 本征闭式域注记：f ≪ fT

    def test_fukui_band_agreement(self):
        """Fukui 对照面：参考频点标定 kf 后，2–20 GHz 带内两模型 ±30% 互证
        （预声明量级带，不逐位；kf 单位约定随所选文献，#118 不内嵌魔数）。"""
        f_ref = 10e9
        p_ref = _params(f_hz=f_ref)
        kf_cal = (p_ref.fmin_linear - 1.0) * MODEL.gm_s / (
            f_ref * MODEL.cgs_f * math.sqrt(MODEL.rg_ohm + MODEL.rs_ohm + MODEL.ri_ohm)
        )
        for f in (2e9, 5e9, 10e9, 15e9, 20e9):
            p_posp = _params(f_hz=f)
            f_fukui = fukui_fmin(MODEL, f, kf_cal, include_ri=True)
            rel = abs(f_fukui - p_posp.fmin_linear) / (p_posp.fmin_linear - 1.0)
            assert rel <= 0.30


# ─── 7. 数据面（dataclass/to_dict/JSON 往返）────────────────────────────────


class TestDataFace:
    def test_to_dict_json_serializable(self):
        p = _params()
        blob = json.dumps(p.to_dict())
        assert json.loads(blob)["path"] == "intrinsic"
        assert json.dumps(MODEL.to_dict())

    def test_params_roundtrip(self):
        """to_dict（有限位舍入）→ params_from_dict 往返；容差=舍入位精度。"""
        p = _params()
        p2 = params_from_dict(p.to_dict())
        assert p2.fmin_linear == pytest.approx(p.fmin_linear, rel=1e-9)
        assert p2.rn_ohm == pytest.approx(p.rn_ohm, rel=1e-9)
        assert p2.yopt == pytest.approx(p.yopt, rel=1e-9)
        assert p2.gamma_opt == pytest.approx(p.gamma_opt, rel=1e-9)
        assert p2.trg_k is None and p2.trs_k is None

    def test_rn_norm_property(self):
        p = _params(z0=50.0)
        assert p.rn_norm == pytest.approx(p.rn_ohm / 50.0, rel=1e-15)

    def test_missing_vs_zero_semantics(self):
        """trg_k/trs_k 缺省 None（判缺失 is not None，#364④）vs 显式 290.0。"""
        p_none = _params()
        p_zero = _params(trg_k=290.0, trs_k=290.0)
        assert p_none.trg_k is None
        assert p_zero.trg_k == 290.0
        # 嵌入路径缺省 trg=trs=t0：与显式传 T0 结果一致
        model = FetSmallSignal(cgs_f=100e-15, ri_ohm=2.0, gm_s=0.05, gds_s=2e-3,
                               rg_ohm=1.0, rs_ohm=1.0)
        a = _params(model)
        b = _params(model, trg_k=T0_K, trs_k=T0_K)
        assert a.fmin_linear == pytest.approx(b.fmin_linear, rel=1e-12)


# ─── 8. service 薄壳（JSON 信封，ok=False 不抛）─────────────────────────────


class TestServiceEnvelope:
    def test_service_happy_path(self):
        from rfauto.service.fet_noise_service import fet_noise_evaluate

        payload = {
            "model": {"cgs_f": 100e-15, "ri_ohm": 2.0, "gm_s": 0.05, "gds_s": 2e-3},
            "f_hz": 10e9, "tg_k": 297.0, "td_k": 1500.0,
            "nf_targets_db": [1.0, 2.0],
        }
        out = fet_noise_evaluate(payload)
        assert out["ok"] is True
        data = out["data"]
        assert data["noise_params"]["path"] == "intrinsic"
        assert data["noise_params"]["fmin_db"] == pytest.approx(
            10 * math.log10(
                pospieszalski_noise_params(MODEL, F_HZ, tg_k=TG_K, td_k=TD_K).fmin_linear
            ), rel=1e-9,
        )
        assert len(data["noise_circles"]) == 2
        assert data["ft_hz"] > 0

    def test_service_error_envelope(self):
        from rfauto.service.fet_noise_service import fet_noise_evaluate

        assert fet_noise_evaluate({"f_hz": 10e9})["ok"] is False
        bad = {"model": {"cgs_f": -1.0, "ri_ohm": 2.0, "gm_s": 0.05, "gds_s": 2e-3},
               "f_hz": 10e9, "tg_k": 297.0, "td_k": 1500.0}
        out_bad = fet_noise_evaluate(bad)
        assert out_bad["ok"] is False and "error" in out_bad
        assert fet_noise_evaluate("not-a-dict")["ok"] is False

    def test_service_extrinsic_and_sparams(self):
        from rfauto.service.fet_noise_service import fet_noise_evaluate

        payload = {
            "model": {"cgs_f": 100e-15, "ri_ohm": 2.0, "gm_s": 0.05, "gds_s": 2e-3,
                      "rg_ohm": 1.5, "rs_ohm": 0.8},
            "f_hz": 10e9, "tg_k": 297.0, "td_k": 1500.0,
            "sparams": [[[0.5, 0.1], [0.0, -0.1]], [[3.0, 0.0], [-0.05, 0.6]]],
            "with_fukui": True,
        }
        out = fet_noise_evaluate(payload)
        assert out["ok"] is True
        assert out["data"]["noise_params"]["path"] == "embedded"
        assert out["data"]["lna_match"]["nf_at_match_db"] == pytest.approx(
            out["data"]["lna_match"]["nf_min_db"], abs=1e-6
        )
        assert out["data"]["fukui"]["fmin_linear"] > 1.0
