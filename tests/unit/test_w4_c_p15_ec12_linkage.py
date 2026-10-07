"""W4-C P15：EC-12 Debye 渲染面 ↔ P13 core 拟合面联动复核。

任务口径（criteria.md W4-C）：P15 = debye 联动 EC-12 渲染面**复核**——
W2-E 已落渲染面（substrate.loss_model 旋钮 kappa_f0|debye，官方
MSL_Debye_Substrate 例口径）并在 test_w2_e_ec12_debye_knob.py 钉住渲染
契约（缺省逐字节不变/材料卡换装/pole 数旋钮/fail-loud）。本文件不重复
其钉，只补**两面临通**（P13 只做拟合面扩展，缺省路径零变化，#329 家法）：

1. core DebyeModel 求值器读渲染面拟合产物（_debye_pole_fit 的等 Δε 极点）
   → 带内 tanD 平坦度与 ε′≈er 独立复核（渲染面的物理设计目标经 core 面
   二次验证，两面临通=同一数学对象）；
2. P13 core 拟合面 → 渲染面参数映射（fit_debye_multipoles → to_openems
   的 epsilon/kappa/poles[].eps_delta/relax_time_s 与 CSPropDebyeMaterial
   的 order/epsilon/eps_delta/eps_relax 签名 1:1 对位——P13 拟合模型可经
   既有旋钮 API 注入，无需改渲染面）；
3. 缺省路径零变化的独立复核钉（抽样模板与 W2-E 错开：patch/suspended_
   stripline 两族 + 自由空间族 debye 拒绝）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from rfauto.adapters.oe_templates.registry import TEMPLATE_NOMINAL
from rfauto.adapters.oe_templates.render_core import (
    _debye_pole_fit,
    render_script,
)
from rfauto.core.dispersion import (
    DebyeModel,
    DebyePole,
    DjordjevicSarkar,
    fit_debye_multipoles,
)

# ─── 1. core 面复核渲染面拟合产物 ─────────────────────────────────────────────


def _render_fit_as_debye_model(er: float, tan_d: float, band_ghz: tuple[float, float],
                               n_poles: int = 2) -> DebyeModel:
    """渲染面等 Δε 拟合产物 → core DebyeModel（同一数学对象的两面表达）。

    _debye_pole_fit 返回 (eps_inf, eps_delta, tau_s...)——等 Δε 每极点；
    tau 秒 → DebyePole f_relax_hz = 1/(2πτ)（与 to_openems 的 relax_time_s
    同一换算，往返恒等）。
    """
    eps_inf, eps_delta, taus = _debye_pole_fit(er, tan_d, band_ghz, n_poles=n_poles)
    poles = tuple(
        DebyePole(delta_eps=eps_delta, f_relax_hz=1.0 / (2.0 * np.pi * t))
        for t in taus
    )
    return DebyeModel(eps_inf=eps_inf, poles=poles)


def test_core_evaluator_reads_render_fit_flat_tand():
    """core DebyeModel 求值渲染面等 Δε 拟合：带内 tanD 平坦（ripple ≤10%
    ——W2-E 判据③的 core 面独立复核）且 ε′ 带内 ≈ er（组合拟合目标）。"""
    er, tan_d, band = 4.4, 0.02, (4.0, 6.0)
    model = _render_fit_as_debye_model(er, tan_d, band, n_poles=2)
    f = np.linspace(band[0], band[1], 41) * 1e9
    td = np.asarray(model.loss_tangent(f))
    assert float(np.nanmean(td)) == pytest.approx(tan_d, rel=0.10)
    assert float((np.nanmax(td) - np.nanmin(td)) / tan_d) <= 0.10
    eps_r = np.asarray(model.epsilon_r(f))
    assert float(np.nanmean(eps_r)) == pytest.approx(er, rel=0.02)


def test_render_fit_physical_direction():
    """eps_inf < er（极点贡献 Δε>0 的物理方向，W2-E 判据③同款、core 面重证）。"""
    eps_inf, eps_delta, _ = _debye_pole_fit(4.4, 0.02, (4.0, 6.0), n_poles=2)
    assert eps_inf < 4.4
    assert eps_delta > 0.0


def test_render_fit_tau_to_core_roundtrip_identity():
    """渲染面 tau(秒) ↔ core f_relax_hz 换算往返恒等（1/(2π) 单源换算）。"""
    _, _, taus = _debye_pole_fit(4.4, 0.02, (4.0, 6.0), n_poles=3)
    model = _render_fit_as_debye_model(4.4, 0.02, (4.0, 6.0), n_poles=3)
    for pole, t in zip(model.poles, taus, strict=True):
        assert 1.0 / (2.0 * np.pi * pole.f_relax_hz) == pytest.approx(t, rel=1e-15)
    payload = model.to_openems()
    for pole_out, pole in zip(payload["poles"], model.poles, strict=True):
        assert pole_out["relax_time_s"] == pytest.approx(
            1.0 / (2.0 * np.pi * pole.f_relax_hz), rel=1e-15)


# ─── 2. P13 core 拟合面 → 渲染面参数映射 ─────────────────────────────────────


def test_core_fit_feeds_render_face_parameter_signature():
    """P13 拟合产物 to_openems 与渲染面 CSPropDebyeMaterial API 1:1 对位。

    渲染面注入签名（render_core.py debye 档装配）：epsilon=ε∞、逐极点
    ``eps_delta=``、``eps_relax=float(秒)``、order=极点数——to_openems
    载荷逐键对位（P13 拟合模型经既有旋钮 API 可注入，零渲染面改动）。
    """
    band = (4.0, 6.0)
    # 合成"平坦 tanD 基板"数据（渲染面同一设计目标）→ core 多极拟合
    er, tan_d = 4.4, 0.02
    f = np.linspace(band[0], band[1], 21) * 1e9
    data = er * (1.0 - 1j * tan_d) * np.ones_like(f)
    fitted = fit_debye_multipoles(f, data, n_poles=4, weights="relative")
    payload = fitted.to_openems()
    assert payload["model"] == "debye"
    assert set(payload) >= {"epsilon", "kappa", "poles"}
    assert len(payload["poles"]) >= 1
    # 键名映射注记：core 载荷极点键 delta_eps/f_relax_hz/relax_time_s →
    # 渲染面 CSPropDebyeMaterial 签名 eps_delta=/eps_relax=float(秒)（两层
    # 各自既有命名，映射面在本测试钉住，非同键直通）
    for pole in payload["poles"]:
        assert set(pole) >= {"delta_eps", "f_relax_hz", "relax_time_s"}
        assert pole["delta_eps"] >= 0.0
        assert pole["relax_time_s"] > 0.0
    order = len(payload["poles"])
    kwargs = {
        "epsilon": payload["epsilon"],
        "eps_delta": [p["delta_eps"] for p in payload["poles"]],
        "eps_relax": [p["relax_time_s"] for p in payload["poles"]],
    }
    assert order >= 1
    assert all(x > 0.0 for x in kwargs["eps_relax"])
    # 拟合模型带内回代（core 面：ε≈er、tanD≈tan_d）
    td = np.asarray(fitted.loss_tangent(f))
    assert float(np.nanmean(td)) == pytest.approx(tan_d, rel=0.05)
    assert float(np.nanmean(np.asarray(fitted.epsilon_r(f)))) == pytest.approx(er, rel=0.02)


def test_core_fit_from_ds_sampled_data_multipole():
    """core 拟合面消费 D-S 采样数据（datasheet 型输入）→ 多极 Debye 近似，
    带内曲线回收 ≤2%（跨模型族拟合边界如实：D-S 的 1/f 幂律尾由极点组
    近似，band 内精度门、band 外不锚）。"""
    ds = DjordjevicSarkar.from_single_point(
        eps_r=4.4, loss_tangent=0.02, f_meas_hz=10e9, f1_hz=1e8, f2_hz=40e9)
    f = np.geomspace(1e8, 40e9, 41)
    data = np.asarray(ds.epsilon(f), dtype=complex)
    fitted = fit_debye_multipoles(f, data, n_poles=8, weights="relative")
    dev = np.abs(fitted.epsilon(f) - data) / np.abs(data)
    assert float(np.max(dev)) < 0.02


# ─── 3. 缺省路径零变化（独立复核钉，抽样与 W2-E 错开）────────────────────────


from rfauto.adapters.oe_templates.registry import _DEFAULT_SUB


def _kwargs_for(template: str, band: tuple[float, float],
                substrate: dict | None = None) -> dict:
    kw = dict(
        template=template,
        params=dict(TEMPLATE_NOMINAL[template]),
        freq_range_ghz=band,
        mesh_resolution_mm=0.4,
    )
    if substrate is not None:
        kw["substrate"] = substrate
    return kw


@pytest.mark.parametrize("template,band", [
    ("patch", (2.0, 3.0)),
    ("suspended_stripline", (4.0, 6.0)),
])
def test_default_path_zero_change_other_families(template, band):
    """缺省（无 loss_model）与显式 kappa_f0 渲染逐字节相同（#329 独立复核；
    抽样模板与 W2-E 的 mline/branchline 错开）。"""
    a = render_script(**_kwargs_for(template, band))
    sub = {**_DEFAULT_SUB, "loss_model": "kappa_f0"}
    b = render_script(**_kwargs_for(template, band, substrate=sub))
    assert a == b
    assert "CSPropDebyeMaterial" not in a


def test_debye_rejected_on_free_space_family():
    """自由空间族（dipole，无介质基板）+ loss_model=debye → fail-loud 拒绝
    （无介质可建；静默 no-op 旋钮是陷阱，W2-E 同款独立复核）。"""
    kw = _kwargs_for("dipole", (2.0, 3.0))
    kw["substrate"] = {"er": 4.4, "h_mm": 1.0, "tan_d": 0.02,
                       "loss_model": "debye"}
    with pytest.raises(ValueError, match="debye"):
        render_script(**kw)


def test_invalid_loss_model_rejected():
    """非法 loss_model 值 → fail-loud（合法 kappa_f0|debye）。"""
    kw = _kwargs_for("mline", (4.0, 6.0))
    kw["substrate"] = {"er": 4.4, "h_mm": 1.0, "tan_d": 0.02,
                       "loss_model": "cole_cole"}
    with pytest.raises(ValueError, match="loss_model"):
        render_script(**kw)
