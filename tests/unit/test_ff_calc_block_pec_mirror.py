"""patch ff_calc_block 渲染侧接 PEC 地镜像修正（#249）。

渲染脚本保持纯净（不 import rfauto 内核，openems_solver 可用其他 python_exe 跑
绑定），故 ff_calc_block 内联同一公式；本测试把渲染出的修正段（RFAUTO_PEC_MIRROR
标记之间）原样 exec，逐键钉住与 core.farfield.correct_pec_mirror 数值一致（含
raw 留痕、k=1 六面全包不动、P_acc≤0 边界），并钉住内核幂等（服务层对脚本已修正
的 meta 再调用不二次折半，nf2ff_service._read_metrics 端到端同值）。
"""
from __future__ import annotations

import textwrap

import numpy as np
import pytest

from rfauto.adapters.openems_templates import render_script
from rfauto.core.farfield import correct_pec_mirror
from rfauto.service.nf2ff_service import _read_metrics

_BEGIN = "# RFAUTO_PEC_MIRROR_BEGIN"
_END = "# RFAUTO_PEC_MIRROR_END"
_KEYS = ("prad_w", "dmax_linear", "dmax_dbi", "efficiency", "gain_max_dbi",
         "power_budget_closure")


def _mirror_block(template: str, params: dict, band: tuple[float, float]) -> str:
    text = render_script(template, params, band, far_field=True)
    compile(text, f"{template}_ff", "exec")
    assert text.count(_BEGIN) == 1 and text.count(_END) == 1
    # 从标记行行首切起（标记本身缩进 4 格），dedent 后可独立 exec
    b = text.rfind("\n", 0, text.index(_BEGIN)) + 1
    return textwrap.dedent(text[b:text.index(_END)])


def _script_meta(template: str = "patch", **over) -> dict:
    """渲染脚本 _ff_meta 字面结构（修正前原值，patch_field_smoke 真机量级）。"""
    prad, p_acc, dmax = 0.5148, 0.4142, 2.2545      # η_raw 1.243 / Dmax_raw 3.53 dBi
    meta = {
        "ok": True, "template": template, "f_res_ghz": 2.4525,
        "freq_band_ghz": [2.0, 3.0], "prad_w": prad, "p_acc_w": p_acc,
        "dmax_linear": dmax, "dmax_dbi": 10 * np.log10(max(dmax, 1e-300)),
        "efficiency": prad / p_acc,
        "gain_max_dbi": 10 * np.log10(max(dmax, 1e-300)) + 10 * np.log10(prad / p_acc),
        "power_budget_closure": abs(p_acc - prad) / p_acc,
        "nf2ff_box_start_m": [-0.0554, -0.0554, 0.0],
        "nf2ff_box_stop_m": [0.0554, 0.0554, 0.0407], "radius_m": 1.0,
    }
    meta.update(over)
    return meta


def _run_block(block: str, meta: dict) -> dict:
    ns = {"np": np, "_ff_meta": dict(meta)}
    exec(compile(block, "pec_mirror_block", "exec"), ns)
    return ns["_ff_meta"]


@pytest.fixture(scope="module")
def patch_block() -> str:
    return _mirror_block("patch", {"patch_len_mm": 34.9}, (2.0, 3.0))


class TestRenderedBlockMatchesCoreKernel:
    def test_patch_k2_bitwise_equal_to_core(self, patch_block):
        meta = _script_meta()
        got = _run_block(patch_block, meta)
        ref = correct_pec_mirror(meta)
        assert got["pec_mirror_factor"] == ref["pec_mirror_factor"] == 2.0
        for k in _KEYS:
            assert got[k] == ref[k], k                  # 同式同序 → 逐位相等
            assert got["raw"][k] == ref["raw"][k] == meta[k], k
        assert got["prad_w"] == meta["prad_w"] / 2.0
        assert got["dmax_dbi"] == pytest.approx(meta["dmax_dbi"] + 10 * np.log10(2.0))
        assert got["efficiency"] == pytest.approx(0.6215, abs=5e-4)   # 1.243 → 0.62
        assert got["gain_max_dbi"] == pytest.approx(meta["gain_max_dbi"])  # G 不变
        # 入参不被改写（与 core 同：返回副本语义由 exec 命名空间副本承担）
        assert meta["prad_w"] == 0.5148 and "raw" not in meta

    def test_six_face_box_k1_untouched(self, patch_block):
        meta = _script_meta("dipole", nf2ff_box_start_m=[-0.06, -0.06, -0.0339])
        got = _run_block(patch_block, meta)
        ref = correct_pec_mirror(meta)
        assert got["pec_mirror_factor"] == ref["pec_mirror_factor"] == 1.0
        assert "raw" not in got and "raw" not in ref
        for k in _KEYS:
            assert got[k] == ref[k] == meta[k], k

    def test_p_acc_nonpositive_edge(self, patch_block):
        meta = _script_meta(p_acc_w=0.0, efficiency=None, gain_max_dbi=None,
                            power_budget_closure=None)
        got = _run_block(patch_block, meta)
        ref = correct_pec_mirror(meta)
        for k in _KEYS:
            assert got[k] == ref[k], k
        assert got["efficiency"] is None and got["gain_max_dbi"] is None
        assert got["power_budget_closure"] is None
        assert got["prad_w"] == meta["prad_w"] / 2.0 and got["dmax_linear"] == meta["dmax_linear"] * 2.0

    def test_dipole_render_shares_block(self):
        block = _mirror_block("dipole", {"dipole_len_mm": 58.0}, (2.25, 2.75))
        assert block == _mirror_block("patch", {"patch_len_mm": 34.9}, (2.0, 3.0))
        text = render_script("dipole", {"dipole_len_mm": 58.0}, (2.25, 2.75),
                             far_field=True)
        assert "-AIR_TOP + _FF_MARGIN" in text          # 六面全包盒 → 运行时 k=1


class TestCoreIdempotence:
    def test_correct_twice_equals_once(self):
        meta = _script_meta()
        once = correct_pec_mirror(meta)
        twice = correct_pec_mirror(once)
        assert twice == once
        assert twice["prad_w"] == meta["prad_w"] / 2.0     # 未再折半

    def test_script_corrected_meta_passes_through_services(self, patch_block):
        """渲染脚本已修正（带 pec_mirror_factor/raw）的 meta 经 nf2ff_service._read_metrics
        与原值 meta 经同一路径得到逐键相同指标——无二次修正。"""
        meta = _script_meta()
        script_fixed = _run_block(patch_block, meta)
        m_raw = _read_metrics(meta, None)
        m_fixed = _read_metrics(script_fixed, None)
        for k in ("f_res_ghz", "dmax_dbi", "gain_max_dbi", "efficiency",
                  "power_budget_closure", "pec_mirror_factor"):
            assert m_raw[k] == m_fixed[k], k
        assert m_raw["raw"] == m_fixed["raw"]
        assert m_fixed["efficiency"] == pytest.approx(0.6215, abs=5e-4)

    def test_explicit_factor_one_is_kept(self):
        meta = _script_meta(pec_mirror_factor=1.0)
        out = correct_pec_mirror(meta)
        assert out["pec_mirror_factor"] == 1.0 and out["prad_w"] == meta["prad_w"]
        assert "raw" not in out
