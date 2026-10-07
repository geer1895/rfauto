"""coupled_line `_gap_midline` 缝场网格加密旋钮（ge8 K-3 机制分离批）。

旋钮语义（runs/ge8_k3mech/criteria.md 预声明）：True 时缝区
[-gap/2, +gap/2] 等分 10 格内部线精确入网（0.5mm 名义缝 → 0.05mm 格，
#311 缝中点精确入网法推广）；False/缺省=近点集与渲染逐字节不变
（#329 缺省恒等口径）。

判据全部在最终网格上实测（#368：效力断言必须在与求解同参渲染的最终
网格上做，非字符串存在性）：render → exec 几何段 → CSXCAD 实测
GetLines。CSXCAD 缺席环境按仓 conftest 同语义 importorskip 诚实跳过。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL, render_script

BAND = (1.5, 5.0)
MESH_MM = 0.4
KNOB = "_gap_midline"


def _render(params: dict) -> str:
    return render_script("coupled_line", params, BAND,
                         mesh_resolution_mm=MESH_MM, excite_port=1)


def _nominal() -> dict:
    return dict(TEMPLATE_NOMINAL["coupled_line"])


def test_default_path_byte_identity() -> None:
    """缺省恒等（#329）：无键与显式 False 的渲染与名义渲染逐字节一致。"""
    base = _render(_nominal())
    assert base == _render({**_nominal(), KNOB: False})
    assert base == _render({**_nominal(), KNOB: None})


def test_enabled_diff_is_single_near_x_line() -> None:
    """生效档差异面=恰好一行 _near_x（单变量字节实证，ge7 render_diff 同法）。"""
    base = _render(_nominal()).splitlines()
    knob = _render({**_nominal(), KNOB: True}).splitlines()
    assert len(base) == len(knob)
    diff = [i for i, (a, b) in enumerate(zip(base, knob, strict=False))
            if a != b]
    assert len(diff) == 1
    i = diff[0]
    assert base[i].startswith("_near_x = ")
    assert knob[i].startswith("_near_x = ")
    # 生效行必须恰含 10 格细分的 9 条线位（浮点值比较，不匹配 repr 文本）
    import ast

    vals = ast.literal_eval(knob[i].split("=", 1)[1].strip())
    base_vals = ast.literal_eval(base[i].split("=", 1)[1].strip())
    added = sorted(set(vals) - set(base_vals))
    assert np.allclose(
        added, np.array([-0.2, -0.15, -0.1, -0.05, 0.05,
                         0.1, 0.15, 0.2]) * 1e-3, atol=1e-12)


def test_enabled_final_mesh_gap_refined() -> None:
    """生效档最终网格实测（#368/#311 口径）：缝内 9 条内部线、10 格
    0.05mm、全轴最小线距 ≥10µm（#349 守卫）。"""
    pytest.importorskip("CSXCAD")
    from tests.unit import _geometry_audit_helpers as gh

    params = {**_nominal(), KNOB: True}
    scope, _prims = gh.load_geometry("coupled_line", params, MESH_MM)
    xl = gh.mesh_lines(scope, "x")
    gap_half = float(params["gap_mm"]) * 1e-3 / 2.0
    strict = xl[(xl > -gap_half) & (xl < gap_half)]
    assert len(strict) == 9
    expect = np.array([-0.2, -0.15, -0.1, -0.05, 0.0,
                       0.05, 0.1, 0.15, 0.2]) * 1e-3
    assert np.allclose(np.sort(strict), expect, atol=1e-12)
    # 覆盖缝区的网格胞=10（±gap/2 金属缘非网格线，缘胞跨界各 1）
    n_cells = int(np.sum((xl[:-1] < gap_half) & (xl[1:] > -gap_half)))
    assert n_cells == 10
    # 缝格=0.05mm（基线 0.0972mm 的一半；9 条内部线间 8 个全内部区间）
    d_in = np.diff(xl[(xl >= -gap_half) & (xl <= gap_half)])
    assert np.allclose(d_in, np.full(d_in.shape, 5e-5), atol=1e-9)
    # #349 最小线距守卫：三轴全部 ≥10µm
    for ax in ("x", "y", "z"):
        lines = gh.mesh_lines(scope, ax)
        assert float(np.min(np.diff(lines))) >= 10e-6


def test_baseline_mesh_gap_five_cells_pinned() -> None:
    """基线（缺省）最终网格实测钉：缝内 5 条内部线（0/±0.0972mm 系）——
    criteria.md §0 预声明「#311 ≥1 基线已满足、X1 生效断言取缝格减半」
    的事实依据；缺省漂移即红。"""
    pytest.importorskip("CSXCAD")
    from tests.unit import _geometry_audit_helpers as gh

    scope, _prims = gh.load_geometry("coupled_line", _nominal(), MESH_MM)
    xl = gh.mesh_lines(scope, "x")
    gap_half = float(_nominal()["gap_mm"]) * 1e-3 / 2.0
    strict = xl[(xl > -gap_half) & (xl < gap_half)]
    assert len(strict) == 5
    assert np.isclose(strict[2], 0.0, atol=1e-12)   # x=0 中线在网


def test_single_variable_other_axes_and_geometry_unchanged() -> None:
    """单变量背书：旋钮只动 x 近点集——y/z 网格线与导体原语逐项不变。"""
    pytest.importorskip("CSXCAD")
    from tests.unit import _geometry_audit_helpers as gh

    s0, p0 = gh.load_geometry("coupled_line", _nominal(), MESH_MM)
    s1, p1 = gh.load_geometry(
        "coupled_line", {**_nominal(), KNOB: True}, MESH_MM)
    assert gh.mesh_lines(s0, "y").tolist() == gh.mesh_lines(s1, "y").tolist()
    assert gh.mesh_lines(s0, "z").tolist() == gh.mesh_lines(s1, "z").tolist()
    assert len(p0) == len(p1)
    for a, b in zip(p0, p1, strict=False):
        assert np.array_equal(a.lo, b.lo) and np.array_equal(a.hi, b.hi)


def test_knob_scales_with_gap_param_subset() -> None:
    """旋钮随 gap_mm 参数标度（非 0.5mm 硬编码）：gap 1.0mm → 9 条细分线
    全部落网（子集断言）。注：任意 gap 与 NEAR 平滑线的近重合风险不在本
    旋钮声明域（#349 最小线距守卫只在名义 0.5mm 座位审计钉，见
    test_enabled_final_mesh_gap_refined）——非名义 gap 使用前须重跑审计。"""
    pytest.importorskip("CSXCAD")
    from tests.unit import _geometry_audit_helpers as gh

    params = {**_nominal(), "gap_mm": 1.0, KNOB: True}
    scope, _ = gh.load_geometry("coupled_line", params, MESH_MM)
    xl = gh.mesh_lines(scope, "x")
    strict = xl[(xl > -0.5e-3) & (xl < 0.5e-3)]
    for want in np.array([-4, -3, -2, -1, 0, 1, 2, 3, 4]) * 1e-4:
        assert np.any(np.abs(strict - want) < 1e-12)
