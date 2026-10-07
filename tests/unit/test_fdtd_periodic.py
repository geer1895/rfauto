"""SV-4：FDTDX 周期边界扩面单元测试（规格层 + 支持性实录探针）。

fdtdx 本机未装（diff-fdtd extra 缺席，合法常态）——本文件全部为
fdtdx-free 的规格/判据/探针离线面：

1. PeriodicSlabSpec 校验（守卫家族同 fdtd_diff.CavitySpec 口径）：
   体素上限 64/steps≤320/pml 厚度/slab 自由区/预算守卫；合法缺省全过；
2. 通带判据纯函数：pass_band_mask 门限掩码；band_edges 带边/带宽、
   无通带点如实 None（不虚构带结构）、形状不符拒绝；
3. 支持性实录探针：fdtdx 缺席 → ("not_installed", evidence 含 extras
   指路)；注入假模块（无 boundaries 子模块/源码无证据词）→
   "unsupported"；require_fdtdx_periodic 对两状态显式 RuntimeError
   （fail-closed 待证，不猜 API——round14"先源码实录"原文）。
"""

from __future__ import annotations

import types

import numpy as np
import pytest

from rfauto.adapters.sv.fdtd_periodic import (
    PeriodicSlabSpec,
    band_edges,
    pass_band_mask,
    probe_fdtdx_periodic_support,
    require_fdtdx_periodic,
)


class TestSpecValidation:
    def test_default_spec_valid(self):
        spec = PeriodicSlabSpec()
        spec.validate()
        assert spec.total_voxels == (spec.nx, spec.ny, spec.nz_core)

    def test_time_total_cfl_scale(self):
        spec = PeriodicSlabSpec(resolution=20e-9, steps=320)
        t = spec.time_total()
        c0 = 299_792_458.0
        dt = 0.99 * 20e-9 / (c0 * np.sqrt(3.0))
        assert t == pytest.approx(320 * dt)

    @pytest.mark.parametrize("mutate, match", [
        ({"nx": 1}, "nx,ny≥2"),
        ({"nx": 100}, "≤ 64"),
        ({"steps": 0}, "steps"),
        ({"steps": 400}, "steps"),
        ({"resolution": -1.0}, "必须为正"),
        ({"slab_voxels_x": 0}, "slab"),
        ({"slab_voxels_x": 30}, "slab"),
        ({"eps_diel": 0.0}, "介电常数"),
        ({"y_boundary": "mur"}, "pec|pml"),
        ({"y_boundary": "pml", "pml_thickness": 0}, "≥1"),
        ({"y_boundary": "pml", "pml_thickness": 13}, "放不进"),
        ({"y_boundary": "pml", "pml_thickness": 10,
          "slab_voxels_y": 6}, "自由区"),
        ({"nx": 64, "ny": 64, "nz_core": 2}, "预算"),
    ])
    def test_guards(self, mutate, match):
        spec = PeriodicSlabSpec(**mutate)
        with pytest.raises(ValueError, match=match):
            spec.validate()

    def test_pml_free_zone_ok(self):
        # 不抛即过：PML 自由区足值=validate 直通（欠值由负例钉）
        PeriodicSlabSpec(y_boundary="pml", pml_thickness=2,
                         slab_voxels_y=10).validate()


class TestPassBandFunctions:
    def test_mask_and_edges(self):
        freqs = np.linspace(1.0, 9.0, 9)      # [1,2,...,9]
        s21 = np.array([-30, -25, -5, -1, -0.5, -1, -4, -20, -30])
        mask = pass_band_mask(s21, threshold_db=-3.0)
        assert mask.tolist() == [False, False, False, True, True, True,
                                 False, False, False]
        band = band_edges(freqs, mask)         # 通带 idx 3..5 → f∈[4,6]
        assert band == pytest.approx((4.0, 6.0, 2.0))

    def test_no_passband_returns_none(self):
        freqs = np.linspace(1.0, 5.0, 5)
        assert band_edges(freqs, pass_band_mask(np.full(5, -40.0), -3.0)) \
            is None

    def test_validation(self):
        with pytest.raises(ValueError, match="一维"):
            pass_band_mask(np.zeros((2, 2)), -3.0)
        with pytest.raises(ValueError, match="有限"):
            pass_band_mask(np.array([0.0]), float("nan"))
        with pytest.raises(ValueError, match="形状不符"):
            band_edges(np.linspace(0, 1, 4), np.array([True, False]))
        with pytest.raises(ValueError, match="形状不符"):
            band_edges(np.array([]), np.array([]))


class TestSupportProbe:
    def test_fdtdx_absent_honest(self):
        status, evidence = probe_fdtdx_periodic_support()
        # 本机 venv 无 fdtdx（合法常态）——缺席状态如实可判
        if status == "not_installed":
            assert "diff-fdtd" in evidence
        else:  # 换机装了 fdtdx 时不假红
            assert status in ("supported", "unsupported")

    def test_injected_module_without_boundary_submodule(self):
        fake = types.ModuleType("fdtdx_fake_no_bnd")
        status, _ = probe_fdtdx_periodic_support(fake)
        assert status == "unsupported"

    def test_require_raises_on_unsupported(self):
        fake = types.ModuleType("fdtdx_fake_unsupported")
        with pytest.raises(RuntimeError, match=r"待证|diff-fdtd"):
            require_fdtdx_periodic(fake)

    def test_require_passes_on_supported_evidence(self, tmp_path):
        # 构造"源码含周期证据词"的假模块（inspect.getsource 需真实文件）
        import importlib.machinery
        import importlib.util

        src = "class BoundaryConfig:\n    periodic = ('x', 'y')\n"
        mod_file = tmp_path / "fake_bnd_init.py"
        mod_file.write_text(src, encoding="utf-8")
        sfl = importlib.machinery.SourceFileLoader(
            "fake_bnd_init", str(mod_file))
        spec = importlib.util.spec_from_loader("fake_bnd_init", sfl)
        bnd = importlib.util.module_from_spec(spec)
        sfl.exec_module(bnd)
        fake = types.ModuleType("fdtdx_fake_supported")
        fake.boundaries = types.SimpleNamespace(initialization=bnd)
        status, evidence = probe_fdtdx_periodic_support(fake)
        assert status == "supported"
        assert "periodic" in evidence
        s2, e2 = require_fdtdx_periodic(fake)
        assert s2 == "supported" and "periodic" in e2
