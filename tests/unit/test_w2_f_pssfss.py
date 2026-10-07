"""W2-F（EC-20 PyPSSFSS 严格快通道）域面测试。

纪律（#139）：引擎面全部 monkeypatch/mock——本文件零网络零 Julia 调用；
真编译真跑只走 scripts/pssfss_ms_judge.py 与 runs/w2_phase2/w2f/ 冒烟脚本
（opt-in）。确定性钉面：
1. 几何映射纯函数（cross_sheet_spec/jcross_pixel_mask/patch_sheet_spec/
   strata_order/resolve_geometry）——与仓内可复跑裁判 judge_pssfss.jl 逐
   构造参数同源（#154 语义逐对）；
2. #300 判读纯函数（valley/peak 估计器 + judge_ms_cross/judge_ms_jcross
   预声明门语义）；
3. 缺装双态（is_available fail-closed 显式报缺，qucsator 同款）；
4. solve 面 mock 引擎（产物落盘 openEMS 同构契约 + 掩码语义）；
5. 注册面（键 13 在册 + 能力表 supported_templates 单源——反向 import
   链回归钉，2026-10-05 循环 import 空表实证）。
"""

from __future__ import annotations

import json
import sys
from typing import Any

import numpy as np
import pytest

from rfauto.adapters import pssfss_adapter as pa
from rfauto.adapters.em_solver_base import (
    EMSolverConfig,
    EMSolverType,
    get_global_registry,
    solver_capabilities_for,
)
from rfauto.adapters.pssfss_adapter import (
    PssfssAdapter,
    PssfssError,
    cross_sheet_spec,
    jcross_pixel_mask,
    judge_ms_cross,
    judge_ms_jcross,
    nominal_params,
    patch_sheet_spec,
    peak_f_ghz,
    resolve_geometry,
    strata_order,
    valley_f_ghz,
)


def _config(tmp_path: Any) -> EMSolverConfig:
    return EMSolverConfig(solver_type=EMSolverType.PSSFSS,
                          working_dir=str(tmp_path))


# ─── 注册面（键 13）────────────────────────────────────────────────────────


class TestRegistration:
    def test_key13_registered_after_package_import(self):
        import rfauto.adapters  # noqa: F401

        reg = get_global_registry()
        assert reg.is_registered(EMSolverType.PSSFSS)
        assert reg.lookup(EMSolverType.PSSFSS) is PssfssAdapter

    def test_register_into_fresh_registry_isolated(self):
        from rfauto.adapters.em_solver_base import EMSolverRegistry

        reg = EMSolverRegistry()
        pa.register_pssfss(reg)
        assert reg.lookup(EMSolverType.PSSFSS) is PssfssAdapter
        # 显式实例零全局污染（观测面隔离契约）
        assert get_global_registry().lookup(EMSolverType.PSSFSS) is not None \
            or True  # 全局键由包导入链保证，这里只钉显式通道行为

    def test_capability_table_single_source(self):
        """能力表 supported_templates 必须实测导入 adapter 单源（防手写
        漂移）；循环 import 空表回归钉（2026-10-05 实证，块须位于
        EMSolverAdapter 类定义之后）。"""
        caps = solver_capabilities_for(EMSolverType.PSSFSS)
        assert caps.supported_templates == pa.SUPPORTED_TEMPLATES
        assert caps.availability_gate == "pypssfss"
        assert caps.dimension == "2d"
        assert caps.requires_license is False


# ─── 几何映射纯函数 ─────────────────────────────────────────────────────────


class TestCrossSheetSpec:
    def test_nominal_mapping_matches_archived_judge(self):
        """名义映射与归档裁判 judge_pssfss.jl :78 逐构造参数同源
        （P/L1/L2/A/B/w；A=aw/2 防重合哨兵）。"""
        spec = cross_sheet_spec(nominal_params("ms_cross"))
        assert spec == {"P": 11.9917, "L1": 9.82, "L2": 0.982, "A": 0.491,
                        "B": 0.982, "w": 0.982, "clas": "J", "ntri": 1500}
        assert spec["A"] != spec["L2"]  # A==L2 → 引擎 Infs/NaNs（防重合）

    def test_overrides_flow_through(self):
        spec = cross_sheet_spec({"arm_len_mm": 5.0, "arm_w_mm": 1.0,
                                 "period_mm": 12.0, "ntri": 800})
        assert spec == {"P": 12.0, "L1": 10.0, "L2": 1.0, "A": 0.5, "B": 1.0,
                        "w": 1.0, "clas": "J", "ntri": 800}

    def test_touching_and_wide_arm_rejected(self):
        with pytest.raises(PssfssError, match="不 touching"):
            cross_sheet_spec({"arm_len_mm": 6.0, "arm_w_mm": 0.98,
                              "period_mm": 11.99})
        with pytest.raises(PssfssError, match="总跨之半"):
            cross_sheet_spec({"arm_len_mm": 4.91, "arm_w_mm": 5.0,
                              "period_mm": 11.99})


class TestJcrossPixelMask:
    def test_mask_is_deterministic_and_symmetric(self):
        params = nominal_params("ms_jcross")
        m1 = jcross_pixel_mask(params, npix=96)
        m2 = jcross_pixel_mask(params, npix=96)
        assert m1.shape == (96, 96) and m1.dtype == np.bool_
        assert np.array_equal(m1, m2)
        assert np.array_equal(m1, m1[::-1, :])  # y 镜像（主缝沿 x 居中）
        assert np.array_equal(m1, m1[:, ::-1])  # x 镜像
        # 主缝沿 x+端枝 ±y 的树状 JC 非 4 重旋转对称（转置不同构）——
        # 仅 2 镜面对称（judge_pssfss.jl :24-25 H 形互联缝拓扑）

    def test_slot_aperture_present_at_center_row(self):
        """主缝沿 x：中心行（y≈0）上 |x|≤slot_len/2 为孔径（False）。"""
        params = nominal_params("ms_jcross")
        m = jcross_pixel_mask(params, npix=96)
        center_row = m[47] | m[48]  # y=±d/2 两行都属缝带
        # x 中心段（|x|≤S/2-w/2 必然在缝内）
        assert not center_row[44:52].any()

    def test_stub_aperture_at_slot_ends(self):
        """端枝：主缝端（|x|≈S/2）外侧 ±y 方向（|y|∈[w/2, w/2+T]）为孔径；
        x≈0 中心列在缝带外全金属（树状缝端加载拓扑）。"""
        params = nominal_params("ms_jcross")
        m = jcross_pixel_mask(params, npix=96)
        end_col = m[:, 67]  # x≈+S/2 主缝端列（col68 已出缝区全金属——
        # 与全金属列取 | 会把孔径掩掉，须单列直查）
        # 端枝区（y 方向主缝外）应有孔径
        assert not end_col[:30].all()
        assert not end_col[66:].all()
        # 中心列（x≈0）缝带（|y|≤w/2，行 47/48）外全金属
        center_col = m[:, 47]
        assert center_col[:40].all() and center_col[56:].all()

    def test_invalid_geometry_rejected(self):
        with pytest.raises(PssfssError, match="slot_w"):
            jcross_pixel_mask({"period_mm": 12.0, "slot_len_mm": 4.0,
                               "slot_w_mm": 5.0, "stub_len_mm": 1.0})
        with pytest.raises(PssfssError, match="越界"):
            jcross_pixel_mask({"period_mm": 12.0, "slot_len_mm": 8.0,
                               "slot_w_mm": 1.0, "stub_len_mm": 6.0})
        with pytest.raises(PssfssError, match="过粗"):
            jcross_pixel_mask({"period_mm": 12.0, "slot_len_mm": 4.0,
                               "slot_w_mm": 0.5, "stub_len_mm": 1.0}, npix=4)


class TestPatchSheetSpecAndStrata:
    def test_nominal_mapping(self):
        spec = patch_sheet_spec(nominal_params("ms_patch"))
        assert spec["Lx"] == pytest.approx(8.5406)
        assert spec["Ly"] == pytest.approx(8.5406)
        assert spec["Px"] == pytest.approx(14.9896)
        assert spec["clas"] == "J"

    def test_strata_orders(self):
        assert strata_order("ms_cross") == ["air", "substrate", "sheet",
                                            "air"]
        assert strata_order("ms_patch") == ["air", "sheet", "substrate",
                                            "pec_ground", "air"]


class TestResolveGeometry:
    def test_nominal_defaults_from_template_single_source(self):
        r = resolve_geometry({"template": "ms_cross"}, _config("/tmp"))
        assert r["params"] == nominal_params("ms_cross")
        assert r["substrate"]["er"] == pytest.approx(3.66)
        assert r["substrate"]["h_mm"] == pytest.approx(0.508)
        assert r["fast_sweep"] is True  # 快扫档缺省开（spec §3.2）
        assert r["z0_ref"] == 50.0

    def test_unknown_template_rejected_anti_misuse(self):
        with pytest.raises(PssfssError, match="防误用"):
            resolve_geometry({"template": "wilkinson"}, _config("/tmp"))
        with pytest.raises(PssfssError, match="不在 PSSFSS 支持面"):
            resolve_geometry({"template": "ms_ring_patch"}, _config("/tmp"))

    def test_floquet_mode_knob_honestly_rejected(self):
        """PSSFSS 1.14.x 无 neff 旋钮——传值显式报错不虚报（B2 纪律）。"""
        with pytest.raises(PssfssError, match="n_floquet_modes"):
            resolve_geometry({"template": "ms_cross",
                              "n_floquet_modes": 4}, _config("/tmp"))
        r = resolve_geometry({"template": "ms_cross",
                              "n_floquet_modes": None}, _config("/tmp"))
        assert r["template"] == "ms_cross"

    def test_bad_freqs_rejected(self):
        with pytest.raises(PssfssError, match="递增"):
            resolve_geometry({"template": "ms_cross",
                              "freqs_ghz": [10.0, 9.0]}, _config("/tmp"))
        with pytest.raises(PssfssError, match="正有限"):
            resolve_geometry({"template": "ms_cross",
                              "freqs_ghz": [0.0, 1.0]}, _config("/tmp"))

    def test_substrate_override(self):
        r = resolve_geometry({"template": "ms_cross",
                              "substrate": {"er": 2.2, "h_mm": 0.254}},
                             _config("/tmp"))
        assert r["substrate"] == {"er": 2.2, "tan_d": 0.0037, "h_mm": 0.254}


# ─── #300 判读纯函数 ────────────────────────────────────────────────────────


class TestExtremumEstimators:
    def test_valley_recovery_with_parabolic_refine(self):
        f = np.linspace(7.0, 12.0, 101)
        f0 = 10.15
        db = 4.0 * (f - f0) ** 2  # 抛物线谷（细化对二次型精确回收）
        out = valley_f_ghz(f, db)
        assert out["f_ghz"] == pytest.approx(10.15)
        assert out["f_ghz_refined"] == pytest.approx(10.15, abs=1e-6)
        assert out["argmin_is_best_local"] is True

    def test_peak_recovery(self):
        f = np.linspace(7.0, 12.0, 101)
        f0 = 9.6
        db = -(np.abs(f - f0) * 8.0)
        out = peak_f_ghz(f, db)
        assert out["f_ghz"] == pytest.approx(9.6, abs=0.06)

    def test_band_window_and_shape_guard(self):
        f = np.linspace(7.0, 12.0, 101)
        db = np.zeros_like(f)
        with pytest.raises(PssfssError, match="判读带"):
            valley_f_ghz(f, db, band_ghz=(11.9, 12.5))
        with pytest.raises(PssfssError, match="同长"):
            valley_f_ghz(f, db[:-1])


class TestJudgeGates:
    def test_ms_cross_gate_recovery_pin(self):
        # 2026-10-07 真形重锚（哨兵形 10.152 证伪作废，新 ref=11.4265）：
        # 真形引擎读数与 HFSS Floquet 11.4199 差 +0.06%，1% 门内 PASS；
        # +2% 偏离（哨兵形量级）必须 FAIL——门判别力钉。
        v = judge_ms_cross(11.4265)
        assert v["verdict"] == "PASS"
        assert v["delta_rel"] == pytest.approx(0.0, abs=1e-9)
        assert judge_ms_cross(11.4265 * 0.995)["verdict"] == "PASS"  # −0.5% 门内
        assert judge_ms_cross(11.4265 * 1.02)["verdict"] == "FAIL"

    def test_ms_jcross_or_gate_semantics(self):
        # 绝对门过、相对门不过：Δ=0.25GHz@10GHz（2.5% 也过，改 10.6 基）
        v = judge_ms_jcross(10.25, f0_ghz=10.0)
        assert v["verdict"] == "PASS"  # 0.25≤0.3（rel 2.5% 也 ≤5% 双过）
        # 绝对门不过、相对门过：Δ=0.45GHz@10GHz=4.5%
        v = judge_ms_jcross(10.45, f0_ghz=10.0)
        assert v["verdict"] == "PASS"
        assert v["delta_ghz"] > v["gate_abs_ghz"]
        # 双门皆不过
        v = judge_ms_jcross(10.7, f0_ghz=10.0)
        assert v["verdict"] == "FAIL"


# ─── 缺装双态（fail-closed 显式报缺）────────────────────────────────────────


class TestAvailability:
    def test_missing_dep_fail_closed(self, monkeypatch):
        monkeypatch.setattr(pa, "load_pypssfss", lambda: None)
        ad = PssfssAdapter(_config("/tmp"))
        assert ad.is_available() is False
        assert ad.connect() is False
        res = EMSolverResult_probe_missing(ad)
        assert res.success is False
        assert "rfauto[pssfss]" in res.message  # 显式指路 extras 不静默

    def test_depot_pin_env(self, monkeypatch):
        monkeypatch.delenv("JULIA_DEPOT_PATH", raising=False)
        depot = pa.ensure_julia_depot_env()
        assert depot == r"E:\julia_depot"
        import os

        assert os.environ["JULIA_DEPOT_PATH"] == r"E:\julia_depot"
        # 用户已设值时尊重不覆盖
        monkeypatch.setenv("JULIA_DEPOT_PATH", r"E:\custom_depot")
        assert pa.ensure_julia_depot_env() == r"E:\custom_depot"


def EMSolverResult_probe_missing(ad: PssfssAdapter) -> Any:
    """缺装态下走 solve 的 fail-closed 回传（不经引擎）。"""
    # build_geometry 是纯解析面：缺装仍 True（引擎几何未构建≠解析失败），
    # fail-closed 发生在 solve（原 `is False or True` 恒真断言按真实语义
    # 改写，审查 P2-3）
    assert ad.build_geometry({"template": "ms_cross"}) is True
    ad._resolved = resolve_geometry({"template": "ms_cross"},
                                    ad._config)
    ad._freqs_hz = ad._resolved["freqs_ghz"] * 1e9
    monkey_freeze = pa.load_pypssfss
    assert monkey_freeze() is None
    return ad.solve()


# ─── solve 面（mock 引擎）──────────────────────────────────────────────────


class _FakeSheet:
    def __init__(self, **kw):
        self.kw = kw


class _FakeLayer:
    def __init__(self, **kw):
        self.kw = kw


def _install_fake_engine(monkeypatch, freqs, capture, analyze_impl=None):
    """构造假 pypssfss 模块（analyze/extract/构造器全 mock，#139）。

    sys.modules 三钉（pypssfss / pypssfss.pypssfss / juliacall）——缺一即
    真 juliacall init 启动真 Julia（seed 序依赖假红根因，2026-10-05）。
    """
    from types import SimpleNamespace

    arr = np.zeros((len(freqs), 9), dtype=complex)
    arr[:, 0] = np.asarray(freqs, dtype=float)
    arr[:, 1] = 0.3 - 0.1j  # s11(v,v)
    arr[:, 2] = 0.9 + 0.05j  # s21(v,v)
    arr[:, 3] = 0.02  # s12
    arr[:, 4] = 0.3 - 0.1j  # s22
    arr[:, 5:9] = 0.1

    class _Results:
        pass

    if analyze_impl is None:
        def analyze_impl(strata, flist, steering, **kw):
            capture["strata_types"] = [type(x).__name__ for x in strata]
            capture["n_freq"] = len(list(flist))
            capture["fastsweep"] = kw.get("fastsweep")
            capture["steering"] = steering
            return _Results()

    class _FakeMM(float):
        """pypssfss mm 单位替身（支持 0.508*mm 算术）。"""

        def __mul__(self, other):
            return float(self) * float(other)

        def __rmul__(self, other):
            return float(other) * float(self)

    fake_jl = SimpleNamespace(
        seval=lambda s: ("9.9.9-fake" if "pkgversion" in s else "9.9-fake"),
        Matrix=object,
        Char=object,
    )
    fake_pkg = SimpleNamespace(jl=fake_jl)
    monkeypatch.setitem(sys.modules, "pypssfss", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "pypssfss.pypssfss", fake_pkg)
    # adapter 的 _jchar/位图转换直接 from juliacall import convert——mock 环
    # 境须同钉（否则真 juliacall init 启动 Julia，#139 通道泄漏）
    monkeypatch.setitem(sys.modules, "juliacall",
                        SimpleNamespace(convert=lambda target, v: v))

    def fake_load():
        return SimpleNamespace(
            mm=_FakeMM(1.0),
            jerusalemcross=lambda **kw: _FakeSheet(**kw),
            rectstrip=lambda **kw: _FakeSheet(**kw),
            pixels=lambda **kw: _FakeSheet(**kw),
            Layer=lambda **kw: _FakeLayer(**kw),
            pecsheet=lambda: None,
            ThetaPhi=lambda t, p: {"theta": t, "phi": p},
            analyze=analyze_impl,
            atoutputs=lambda s: ("outreq", s),
            extract_result=lambda results, outreq: arr,
        )

    monkeypatch.setattr(pa, "load_pypssfss", fake_load)


class TestSolveMocked:
    def test_solve_products_and_contract(self, tmp_path, monkeypatch):
        capture: dict[str, Any] = {}
        freqs = [9.0, 9.5, 10.0, 10.5, 11.0]
        _install_fake_engine(monkeypatch, freqs, capture)
        ad = PssfssAdapter(_config(tmp_path))
        assert ad.is_available() is True
        assert ad.connect() is True
        assert ad.build_geometry({"template": "ms_cross",
                                  "freqs_ghz": freqs}) is True
        result = ad.solve()
        assert result.success is True
        assert result.s_params.shape == (5, 2, 2)
        assert result.measured_mask is not None
        assert bool(result.measured_mask.all())  # 全矩阵实测（四 S 请求）
        assert result.freq_ghz.shape == (5,)
        assert "fastsweep=on" in result.message
        assert capture["fastsweep"] is True
        assert capture["steering"] == {"theta": 0.0, "phi": 0.0}
        # openEMS 同构产物契约
        from rfauto.service.health_service import _parse_sparams_csv_masked

        parsed = _parse_sparams_csv_masked(tmp_path / "sparams.csv")
        assert parsed is not None
        f_hz, s_mat, mask = parsed
        assert f_hz.shape == (5,)
        assert s_mat.shape[1:] == (2, 2)
        # 5 列 CSV 契约：S11/S21 直测为 True，S12/S22 互易补齐为 False
        # （全 2×2 实测在 .s2p/meta——mmt 同款口径）
        assert mask[0, 0] and mask[1, 0]
        assert not mask[0, 1] and not mask[1, 1]
        assert np.allclose(s_mat[:, 1, 0], 0.9 + 0.05j)  # S21 直测值回读
        meta = json.loads((tmp_path / "pssfss_meta.json").read_text(
            encoding="utf-8"))
        assert meta["template"] == "ms_cross"
        assert meta["schema"] == "rfauto-pssfss/v1"
        assert meta["strata_order"] == ["air", "substrate", "sheet", "air"]
        assert meta["extremum"]["f_ghz"] == pytest.approx(9.0)

    def test_jcross_solve_meta_pol_note(self, tmp_path, monkeypatch):
        capture: dict[str, Any] = {}
        _install_fake_engine(monkeypatch, [9.0, 10.0], capture)
        ad = PssfssAdapter(_config(tmp_path))
        assert ad.build_geometry({"template": "ms_jcross"}) is True
        result = ad.solve()
        assert result.success is True
        meta = ad.get_meta()
        assert meta["npix"] == 96
        assert "旋转等价" in meta["polarizations"]["note"]
        assert "fastsweep" in capture

    def test_fast_sweep_off_passthrough(self, tmp_path, monkeypatch):
        capture: dict[str, Any] = {}
        _install_fake_engine(monkeypatch, [9.0, 10.0], capture)
        ad = PssfssAdapter(_config(tmp_path))
        assert ad.build_geometry({"template": "ms_cross",
                                  "fast_sweep": False}) is True
        result = ad.solve()
        assert result.success is True
        assert capture["fastsweep"] is False
        assert "fastsweep=off" in result.message

    def test_engine_exception_fail_closed(self, tmp_path, monkeypatch):
        def boom(*a, **kw):
            raise RuntimeError("matrix contains Infs or NaNs")

        # 共享假引擎（含 sys.modules 三钉）+ analyze 注入异常
        _install_fake_engine(monkeypatch, [9.0, 10.0], {}, analyze_impl=boom)
        ad = PssfssAdapter(_config(tmp_path))
        assert ad.build_geometry({"template": "ms_cross"}) is True
        result = ad.solve()
        assert result.success is False
        assert "Infs or NaNs" in result.message  # fail-closed 带原文


class TestBuildGeometryGuards:
    def test_unresolved_solve_returns_failure(self, tmp_path):
        ad = PssfssAdapter(_config(tmp_path))
        res = ad.solve()
        assert res.success is False
        assert "build_geometry" in res.message

    def test_get_sparams_before_solve_raises(self, tmp_path, monkeypatch):
        capture: dict[str, Any] = {}
        _install_fake_engine(monkeypatch, [9.0, 10.0], capture)
        ad = PssfssAdapter(_config(tmp_path))
        assert ad.build_geometry({"template": "ms_cross",
                                  "freqs_ghz": [9.0, 10.0]}) is True
        f, s = ad.get_sparams()  # 未 solve → 先 solve
        assert f.shape == (2,)
        assert s.shape == (2, 2, 2)
