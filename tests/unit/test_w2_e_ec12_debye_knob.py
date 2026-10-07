"""W2-E EC-12——openEMS loss_model 旋钮（kappa_f0 缺省逐字节不变 + debye 档）。

钉住契约（sa_specs2 §二 EC-12 预声明门值）：

1. **缺省路径逐字节不变**（#329）：不带 ``loss_model``（=kappa_f0）的渲染
   输出与 kappa 档完全一致——无 CSPropDebyeMaterial 痕迹、kappa AddMaterial
   卡在位（71 模板全表对 HEAD 的逐字节比对见
   runs/w2_phase2/w2e/default_diff_check.json，本文件钉抽样+机制）；
2. **debye 档显式生效**：substrate 材料卡换装 CSPropDebyeMaterial（官方
   MSL_Debye_Substrate 例 API：order/epsilon/eps_delta/eps_relax，0 基
   order 索引），AddBox 几何保持，脚本可 compile；
3. **拟合质量**（#118 自证）：等 Δε 极点在激励带内还原平坦 tanD（带内
   ripple ≤10%）、eps_inf < er（极点贡献 Δε>0 的物理方向）；
4. **fail-loud**：非法 loss_model 值 / 无基板模板（自由空间族）显式拒绝。
"""

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

_KAPPA_CARD = 'sub = CSX.AddMaterial("substrate", epsilon=ER,'
_DEBYE_MARKER = "CSPropDebyeMaterial"


def _mline_kwargs():
    return dict(
        template="mline",
        params=dict(TEMPLATE_NOMINAL["mline"]),
        freq_range_ghz=(4.0, 6.0),
        mesh_resolution_mm=0.4,
    )


# ─── 判据①：缺省路径逐字节不变 ───────────────────────────────────────────


def test_default_and_kappa_f0_render_identical():
    """不带 loss_model 与显式 kappa_f0（同基板值）渲染输出逐字节相同。"""
    a = render_script(**_mline_kwargs())
    kw = _mline_kwargs()
    kw["substrate"] = {"er": 3.66, "h_mm": 0.508, "tan_d": 0.0037,
                       "loss_model": "kappa_f0"}
    b = render_script(**kw)
    assert a == b


def test_default_path_has_kappa_card_no_debye():
    text = render_script(**_mline_kwargs())
    assert _KAPPA_CARD in text
    assert _DEBYE_MARKER not in text
    assert "TAND * 2 * np.pi * F0" in text


# ─── 判据②：debye 档显式生效 ─────────────────────────────────────────────


def test_debye_knob_swaps_material_card():
    kw = _mline_kwargs()
    kw["substrate"] = {"er": 4.4, "h_mm": 1.0, "tan_d": 0.02,
                       "loss_model": "debye"}
    text = render_script(**kw)
    # 官方例 API 面：CSPropDebyeMaterial + order + 逐极点 eps_delta/eps_relax
    assert f"from CSXCAD.CSProperties import {_DEBYE_MARKER}" in text
    assert "sub = CSPropDebyeMaterial(CSX.GetParameterSet(), order=2," in text
    assert "sub.SetDispersiveMaterialProperty(" in text
    assert "eps_delta=_sub_eps_delta" in text
    assert "eps_relax=float(_t)" in text
    assert 'sub.SetName("substrate")' in text
    assert "CSX.AddProperty(sub)" in text
    # kappa 材料卡不再出现（substrate 头部唯一化）
    assert _KAPPA_CARD not in text
    # AddBox 几何保持（基板盒与 kappa 档同源）
    assert "sub.AddBox((-BOARD, -BOARD, 0), (BOARD, BOARD, H_SUB)" in text
    # 生成脚本可编译（CSXCAD 旧绑定无 Debye 类，exec 不做——构建面判据）
    compile(text, "debye_render", "exec")


def test_debye_pole_count_knob():
    kw = _mline_kwargs()
    kw["substrate"] = {"er": 4.4, "h_mm": 1.0, "tan_d": 0.02,
                       "loss_model": "debye"}
    kw["params"]["_debye_poles"] = 5
    text = render_script(**kw)
    assert "order=5," in text
    # 弛豫表 5 个字面量（列表长 5）
    import re

    m = re.search(r"_sub_tau = \[(.*?)\]", text, re.S)
    assert m is not None
    assert m.group(1).count(",") == 4


def test_debye_addbox_survives_on_branchline():
    """branchline（三方对拍推荐模板）：debye 档 AddBox 与 kappa 档同几何。"""
    base = dict(TEMPLATE_NOMINAL["branchline"])
    kw = dict(template="branchline", params=base,
              freq_range_ghz=(2.4, 2.5), mesh_resolution_mm=0.4)
    kw_kappa = dict(kw)
    kw_kappa["substrate"] = {"er": 4.4, "h_mm": 1.0, "tan_d": 0.02,
                             "loss_model": "kappa_f0"}
    kw_debye = dict(kw)
    kw_debye["substrate"] = {"er": 4.4, "h_mm": 1.0, "tan_d": 0.02,
                             "loss_model": "debye"}
    t_kappa = render_script(**kw_kappa)
    t_debye = render_script(**kw_debye)
    assert _KAPPA_CARD in t_kappa
    assert _DEBYE_MARKER in t_debye
    # 基板 AddBox 行两档逐字节相同（旋钮只换材料卡头部）
    box_line = "sub.AddBox((-BOARD, -BOARD, 0), (BOARD, BOARD, H_SUB)"
    assert box_line in t_kappa and box_line in t_debye


# ─── 判据③：拟合质量自证（#118：先证拟合器本身） ─────────────────────────


def test_debye_fit_deterministic():
    a = _debye_pole_fit(4.4, 0.02, (4.0, 6.0), n_poles=2)
    b = _debye_pole_fit(4.4, 0.02, (4.0, 6.0), n_poles=2)
    assert a == b


def test_debye_fit_restores_flat_tand_in_band():
    """等 Δε 极点在激励带内还原平坦 tanD（官方例 medium 档量级 ripple）。"""
    er, tan_d = 4.4, 0.02
    eps_inf, d_eps, tau = _debye_pole_fit(er, tan_d, (4.0, 6.0), n_poles=2)
    # 物理方向：极点贡献 Δε>0 → eps_inf < 静态 er
    assert eps_inf < er
    assert d_eps > 0
    f = np.linspace(4.0, 6.0, 61) * 1e9
    eps = eps_inf + sum(d_eps / (1 + 1j * 2 * np.pi * f * t) for t in tau)
    tand = -eps.imag / eps.real
    assert np.all(np.abs(tand / tan_d - 1) < 0.10), (
        f"带内 tanD ripple 超 10%：{tand.min():.5f}..{tand.max():.5f}")


# ─── 判据④：fail-loud ────────────────────────────────────────────────────


def test_invalid_loss_model_raises():
    kw = _mline_kwargs()
    kw["substrate"] = {"er": 4.4, "h_mm": 1.0, "tan_d": 0.02,
                       "loss_model": "lorentz"}
    with pytest.raises(ValueError, match="loss_model"):
        render_script(**kw)


def test_debye_on_free_space_template_raises():
    kw = dict(template="dipole",
              params=dict(TEMPLATE_NOMINAL["dipole"]),
              freq_range_ghz=(2.0, 3.0), mesh_resolution_mm=0.4)
    kw["substrate"] = {"er": 4.4, "h_mm": 1.0, "tan_d": 0.02,
                       "loss_model": "debye"}
    with pytest.raises(ValueError, match="debye 不适用于无介质基板"):
        render_script(**kw)


def test_debye_invalid_pole_count_raises():
    kw = _mline_kwargs()
    kw["substrate"] = {"er": 4.4, "h_mm": 1.0, "tan_d": 0.02,
                       "loss_model": "debye"}
    kw["params"]["_debye_poles"] = 0
    with pytest.raises(ValueError, match="_debye_poles"):
        render_script(**kw)
