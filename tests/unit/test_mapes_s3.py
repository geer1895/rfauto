"""A8 MAPES stage-3 定向单元测试（确定性、离线、零真机依赖）。

覆盖文件面：
1. **E3 registry 注册**：``mapes_pixel_analytic`` 可用且既有 kind 全部保留
   （"不破既有语义"回归）；create → fit → predict 契约；与
   :class:`core.mapes.MapesModel` 二进制参数下逐值一致（包装不改数值）；
2. **连续参数兼容**：[0,1] 连续值 ≥0.5 判 1、缺键补 0、topology_key 不符
   显式报错、非数值参数显式报错；
3. **symmetrize 消费口径**：(Z+Zᵀ)/2 只改互易性不改变理想对称网格（数值锚）；
4. **对照脚本**（scripts/mapes_s3_compare.py，importlib 载入）：
   metrics_from_s 与独立重推公式一致（#118 独立来源）、预声明门
   evaluate_gate 合成数据 pass/fail 判定、图案槽计数（route 桥链含对角
   corridor 槽）、真跑渲染脚本接线（shorts 数/单激励/无虚拟口）。

阈值依据：fake_mesh RLC 网格 Z 由构造保证互易无源（stage-1 实测
reciprocity_rel ~1e-15 量级），包装一致性与公式重推均为纯代数，断言
1e-12 / 严格相等。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

from rfauto.core.errors import ConfigError
from rfauto.core.mapes import (
    MapesModel,
    PixelLayout,
    fake_mesh,
    s_to_z,
    z_to_s,
)
from rfauto.optimization.surrogate import MapesAnalyticSurrogate, surrogate_registry

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "mapes_s3_compare.py"
Z0 = 50.0
FREQ_HZ = np.array([1.0e9, 3.5e9, 6.0e9])


def _s3_module():
    spec = importlib.util.spec_from_file_location("mapes_s3_compare", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _small_layout() -> PixelLayout:
    """2×2 单层无双 via 布局：Q=12（io2+pixel4+h2+v2+diag4）。"""
    return PixelLayout(2, 2, 1, 2)


def _small_z_all() -> np.ndarray:
    mesh = fake_mesh(12, n_cols=4)
    return np.stack([mesh.z_all(float(f)) for f in FREQ_HZ])


def _write_npz(tmp_path: Path, z_all: np.ndarray) -> Path:
    npz = tmp_path / "z_all.npz"
    np.savez_compressed(npz, freq_hz=FREQ_HZ, z_all=z_all)
    return npz


def _make_surrogate(tmp_path: Path, **config: object) -> MapesAnalyticSurrogate:
    surrogate = MapesAnalyticSurrogate(config={
        "z_all_npz": str(_write_npz(tmp_path, _small_z_all())),
        "layout": {"n_rows": 2, "n_cols": 2, "n_layers": 1, "n_io_ports": 2,
                   "via_slots": []},
        "reference_impedance": Z0,
        **config,
    })
    surrogate.fit([])
    return surrogate


# ─── 1. E3 registry：注册与既有语义不破 ───────────────────────────────────

def test_registry_has_mapes_analytic_and_keeps_existing_kinds():
    kinds = surrogate_registry.available()
    assert "mapes_pixel_analytic" in kinds
    # 既有数据驱动/代理档全部保留（增量注册不破坏既有消费面）
    for legacy in ("poly_ridge", "nn", "smt_kriging", "fno_lite", "smt_mfk"):
        assert legacy in kinds
    # 既有 kind 仍可照常实例化
    legacy_model = surrogate_registry.create(
        "poly_ridge", config={"bounds": {"x": (0.0, 1.0)}})
    assert legacy_model.KIND == "poly_ridge"


def test_create_via_registry_and_binary_predict_matches_mapes_model(tmp_path):
    layout = _small_layout()
    z_all = _small_z_all()
    surrogate = _make_surrogate(tmp_path)
    reference = MapesModel(layout, z_all, FREQ_HZ, reference_impedance=Z0)
    pattern = np.array([[1, 0], [0, 1]], dtype=bool)
    params = layout.flatten(pattern, np.zeros(0, dtype=int))
    assert surrogate.predict(params) == reference.predict(params)


def test_predict_is_pure_function_of_params(tmp_path):
    surrogate = _make_surrogate(tmp_path)
    params = {"occ0_0": 1.0, "occ1_1": 1.0}
    assert surrogate.predict(dict(params)) == surrogate.predict(dict(params))


def test_fit_returns_contract_info_and_predict_requires_fit(tmp_path):
    surrogate = MapesAnalyticSurrogate(config={
        "z_all_npz": str(_write_npz(tmp_path, _small_z_all())),
        "layout": {"n_rows": 2, "n_cols": 2, "n_io_ports": 2, "via_slots": []},
    })
    assert surrogate.fitted is False
    info = surrogate.fit([{"params": {}, "metrics": {}}, "junk-entry", 7])
    assert info["n_samples"] == 1 and info["kind"] == "mapes_pixel_analytic"
    assert surrogate.fitted is True
    with pytest.raises(RuntimeError, match="未拟合"):
        MapesAnalyticSurrogate(config={
            "z_all_npz": str(tmp_path / "z_all.npz")}).predict({})


def test_uncertainty_is_none(tmp_path):
    surrogate = _make_surrogate(tmp_path)
    assert surrogate.uncertainty({}) is None


def test_missing_or_bad_npz_raises_config_error(tmp_path):
    with pytest.raises(ConfigError, match="z_all_npz"):
        MapesAnalyticSurrogate(config={}).fit([])
    with pytest.raises(ConfigError, match="不存在"):
        MapesAnalyticSurrogate(config={
            "z_all_npz": str(tmp_path / "absent.npz")}).fit([])
    bad = tmp_path / "bad.npz"
    np.savez_compressed(bad, freq_hz=FREQ_HZ)  # 缺 z_all
    with pytest.raises(ConfigError, match="缺少数组"):
        MapesAnalyticSurrogate(config={"z_all_npz": str(bad)}).fit([])


# ─── 2. 连续参数兼容（WP3.2 环 Optuna [0,1] 建议）─────────────────────────

def test_predict_snaps_continuous_and_fills_missing_keys(tmp_path):
    layout = _small_layout()
    z_all = _small_z_all()
    surrogate = _make_surrogate(tmp_path)
    reference = MapesModel(layout, z_all, FREQ_HZ, reference_impedance=Z0)
    on = np.array([[1, 0], [0, 0]], dtype=bool)
    expect = reference.predict(layout.flatten(on, np.zeros(0, dtype=int)))
    # ≥0.5 判 1；缺键（occ0_1/occ1_0/occ1_1）= 缺席像素 = 0
    got = surrogate.predict({"occ0_0": 0.9})
    assert got == expect
    # 0.49 判 0
    below = surrogate.predict({"occ0_0": 0.49})
    assert below == reference.predict(
        layout.flatten(np.zeros((2, 2), dtype=bool), np.zeros(0, dtype=int)))
    assert below != expect


def test_predict_rejects_topology_key_mismatch_and_bad_values(tmp_path):
    surrogate = _make_surrogate(tmp_path)
    with pytest.raises(ConfigError, match="topology_key"):
        surrogate.predict({"topology_key": "mapes:px9x9x1:io2:via[-]"})
    with pytest.raises(ConfigError, match="不可解析"):
        surrogate.predict({"occ0_0": "high"})


def test_configured_topology_key_exposed(tmp_path):
    surrogate = _make_surrogate(tmp_path)
    assert surrogate._build().topology_key == "mapes:px2x2x1:io2:via[-]"


# ─── 3. symmetrize 消费口径（stage-2 followUp ⑥ 的量化）──────────────────

def test_symmetrize_repairs_injected_asymmetry(tmp_path):
    z_all = _small_z_all()
    noise = np.zeros_like(z_all)
    noise[:, 0, 5] = 0.1 * np.max(np.abs(z_all), axis=(1, 2))
    asymmetric = z_all + noise
    sym = 0.5 * (asymmetric + np.swapaxes(asymmetric, -1, -2))
    rec = lambda z: float(np.max(np.abs(z - np.swapaxes(z, -1, -2))))  # noqa: E731
    assert rec(sym) < 1.0e-12
    assert rec(asymmetric) > 1.0e-3
    # 对称化只改非对称注入部分：对原本对称的网格，两次消费数值一致
    #（浮点结合序差异 ~1e-14，不逐值相等——断言取机器精度容差）
    surrogate_raw = _make_surrogate(tmp_path, symmetrize=False)
    surrogate_sym = _make_surrogate(tmp_path, symmetrize=True)
    params = {"occ0_0": 1.0}
    raw_metrics = surrogate_raw.predict(dict(params))
    sym_metrics = surrogate_sym.predict(dict(params))
    assert set(raw_metrics) == set(sym_metrics)
    for key, val in raw_metrics.items():
        assert abs(val - sym_metrics[key]) <= 1.0e-9 * (1.0 + abs(val))
    # 非对称数据下两种口径预测不同（口径开关真实生效）
    asym_npz = tmp_path / "asym.npz"
    np.savez_compressed(asym_npz, freq_hz=FREQ_HZ, z_all=asymmetric)
    surrogate_asym = MapesAnalyticSurrogate(config={
        "z_all_npz": str(asym_npz),
        "layout": {"n_rows": 2, "n_cols": 2, "n_io_ports": 2, "via_slots": []},
        "reference_impedance": Z0})
    surrogate_asym.fit([])
    surrogate_asym_sym = MapesAnalyticSurrogate(config={
        "z_all_npz": str(asym_npz), "symmetrize": True,
        "layout": {"n_rows": 2, "n_cols": 2, "n_io_ports": 2, "via_slots": []},
        "reference_impedance": Z0})
    surrogate_asym_sym.fit([])
    assert (surrogate_asym.predict({"occ0_0": 1.0})
            != surrogate_asym_sym.predict({"occ0_0": 1.0}))


def test_s_to_z_z_to_s_roundtrip_keeps_surrogate_input_wellformed():
    rng = np.random.default_rng(20260913)
    z = rng.normal(size=(4, 12, 12)) + 1j * rng.normal(size=(4, 12, 12))
    z = 0.5 * (z + np.swapaxes(z, -1, -2))
    assert np.max(np.abs(s_to_z(z_to_s(z, reference_impedance=Z0),
                                reference_impedance=Z0) - z)) <= 1.0e-10


# ─── 4. 对照脚本：公式独立重推 / 预声明门 / 图案与渲染接线 ─────────────────

def test_metrics_from_s_matches_independent_formula():
    mod = _s3_module()
    rng = np.random.default_rng(31)
    s = (rng.normal(size=(9, 2, 2)) + 1j * rng.normal(size=(9, 2, 2))) * 0.4
    got = mod.metrics_from_s(s)
    db = 20.0 * np.log10(np.maximum(np.abs(s), 1.0e-30))
    expect = {
        "s11_db_at_fc": float(db[4, 0, 0]),
        "s12_db_at_fc": float(db[4, 0, 1]),
        "s21_db_at_fc": float(db[4, 1, 0]),
        "s22_db_at_fc": float(db[4, 1, 1]),
        "s11_db_min": float(np.min(db[:, 0, 0])),
        "s21_db_min": float(np.min(db[:, 1, 0])),
        "passive_margin": float(1.0 - np.max(np.linalg.norm(s, ord=2, axis=(-2, -1)))),
        "reciprocity_err": float(np.max(np.abs(s - np.swapaxes(s, -1, -2)))),
    }
    assert got == expect


def test_evaluate_gate_pre_declared_thresholds():
    mod = _s3_module()
    cases = {f"c{i}": {"delta_s11_db_min_db": 0.1,
                       "delta_s21_lin_at_fc": 0.001} for i in range(7)}
    gate = mod.evaluate_gate(cases, rank_rho=1.0)
    assert gate["pass"] is True
    assert mod.evaluate_gate(cases, rank_rho=0.5)["g3_pass"] is False
    heavy = {**cases, "worst": {"delta_s11_db_min_db": 2.5,
                                "delta_s21_lin_at_fc": 0.001}}
    g1 = mod.evaluate_gate(heavy, rank_rho=1.0)
    assert g1["g1_pass"] is False and g1["pass"] is False
    lin = {**cases, "worst": {"delta_s11_db_min_db": 0.1,
                              "delta_s21_lin_at_fc": 0.06}}
    assert mod.evaluate_gate(lin, rank_rho=1.0)["g2_pass"] is False
    few = dict(list(cases.items())[:4])
    assert mod.evaluate_gate(few, rank_rho=1.0)["g3_pass"] is False


def test_pattern_slot_counts_routes_and_stage2():
    mod = _s3_module()
    layout = mod.build_layout()
    vias = np.zeros(len(layout.via_slots), dtype=int)
    counts = {name: int(layout.slot_occupancy(p, vias).sum())
              for name, p in {**mod.stage2_patterns(),
                              **mod.stage3_patterns()}.items()}
    # stage-2 四案（与 stage-2 report.json n_short_slots 一致）
    assert counts["all_empty"] == 0
    assert counts["single_2_3"] == 1
    assert counts["row2"] == 11
    assert counts["checker"] == 43
    # stage-3 桥链三案：路由走廊 11 像素 + 10 座 h/v 桥 + 9 个对角 corridor 槽
    assert counts["route_full"] == 30
    # 中断 (2,2) 缺席：像素 -1、桥 -2、对角 corridor -2
    assert counts["route_broken"] == 25
    assert counts["route_half"] == 12


def test_ab_space_snap_and_bounds_shape():
    mod = _s3_module()
    layout = mod.build_layout()
    bounds = mod._ab_bounds(layout)
    assert sorted(bounds) == [f"occ{r}_{c}" for r, c in mod.AB_PARAM_PATCHES]
    assert all(v == (0.0, 1.0) for v in bounds.values())
    pattern = mod._snap_pattern(
        {f"occ{r}_{c}": (0.9 if i % 2 == 0 else 0.1)
         for i, (r, c) in enumerate(mod.AB_PARAM_PATCHES)}, layout)
    expect = np.zeros((6, 6), dtype=bool)
    for i, (r, c) in enumerate(mod.AB_PARAM_PATCHES):
        expect[r, c] = i % 2 == 0
    assert np.array_equal(pattern, expect)


def test_render_route_full_pattern_mode_wiring():
    mod = _s3_module()
    layout = mod.build_layout()
    stage2 = mod._stage2_module()
    geom = stage2.build_geom(layout)
    pattern = mod.stage3_patterns()["route_full"]
    loads = mod.occupancy_to_load(pattern, layout, np.zeros(2, dtype=int))
    short_numbers = tuple(int(i) + 3 for i in np.flatnonzero(np.isfinite(loads)))
    text = stage2.render_round_script(
        geom, excite_port=1, virtual_ports=False,
        short_numbers=short_numbers)
    assert text.count("shorts.AddBox(") == len(short_numbers) == 30
    assert text.count("LumpedPort(CSX") == 2  # 仅 io 双探针
    assert text.count("excite=1") == 1
    assert "PML_8" in text


def test_stage2_module_exposes_import_surface():
    mod = _s3_module()
    stage2 = mod._stage2_module()
    for attr in ("render_round_script", "_run_round", "build_geom"):
        assert callable(getattr(stage2, attr))


# ─── 6. stage-4：α 透传 / 质量版路径接线 / 直接全波案装配 ─────────────────────

def test_surrogate_alpha_config_passthrough(tmp_path):
    base = _make_surrogate(tmp_path)
    scaled = _make_surrogate(tmp_path, alpha=1.5)
    assert base._build().alpha == 1.0 and scaled._build().alpha == 1.5
    params = {"occ0_0": 1.0, "occ1_1": 1.0}
    # α=1.5 → 提取网格 [1,3.5,6]GHz 重采样，中心频点指标应变
    assert base.predict(params) != scaled.predict(params)
    with pytest.raises(ConfigError):
        _make_surrogate(tmp_path, alpha=0.0)


def test_case_direct_dir_routing_modes(tmp_path):
    mod = _s3_module()
    # 缺省：s2 四案在 <s2_dir>/patterns、s3 三案在 <s3_dir>/patterns
    d = mod._case_direct_dir("checker", s2_dir=tmp_path / "s2", s3_dir=tmp_path / "s3")
    assert d == tmp_path / "s2" / "patterns" / "checker"
    d = mod._case_direct_dir("route_full", s2_dir=tmp_path / "s2", s3_dir=tmp_path / "s3")
    assert d == tmp_path / "s3" / "patterns" / "route_full"
    # 质量版：7 案同根
    d = mod._case_direct_dir("route_half", s2_dir=tmp_path / "s2", s3_dir=tmp_path / "s3",
                             patterns_dir=tmp_path / "s4" / "patterns")
    assert d == tmp_path / "s4" / "patterns" / "route_half"
    # 向后兼容：无关键字 = 仓内缺省目录
    assert mod._case_direct_dir("all_empty") == mod.S2_DIR / "patterns" / "all_empty"
    assert mod._case_direct_dir("route_broken") == mod.S3_DIR / "patterns" / "route_broken"


def _write_direct_case(case_dir: Path, s: np.ndarray) -> None:
    """按 stage-2 轮 CSV 合同写两激励 sparams.csv（(n,2,2) 复 S）。"""
    for exc in (1, 2):
        d = case_dir / f"p{exc}"
        d.mkdir(parents=True, exist_ok=True)
        rows = ["freq_hz,re_S1,im_S1,re_S2,im_S2"]
        for k, f in enumerate(FREQ_HZ):
            a, b = complex(s[k, 0, exc - 1]), complex(s[k, 1, exc - 1])
            rows.append(f"{float(f)!r},{a.real!r},{a.imag!r},{b.real!r},{b.imag!r}")
        (d / "sparams.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")


def test_direct_cases_assembly_matches_metrics_contract(tmp_path):
    mod = _s3_module()
    layout = mod.build_layout()
    rng = np.random.default_rng(9)
    names = list({**mod.stage2_patterns(), **mod.stage3_patterns()}.keys())
    truth: dict[str, np.ndarray] = {}
    for name in names:
        s = 0.3 * (rng.normal(size=(3, 2, 2)) + 1j * rng.normal(size=(3, 2, 2)))
        truth[name] = s
        _write_direct_case(tmp_path / "patterns" / name, s)
    cases = mod._direct_cases(layout, FREQ_HZ, s2_dir=tmp_path, s3_dir=tmp_path,
                              patterns_dir=tmp_path / "patterns")
    assert len(cases) == 7
    for (params, metrics), name in zip(cases, names, strict=True):
        assert params["topology_key"] == layout.topology_key
        expect = mod.metrics_from_s(truth[name])
        assert metrics == expect
        assert {"s11_db_min", "s21_db_at_fc"} <= set(metrics)


def test_build_layout_grid_option_scales_port_count():
    mod = _s3_module()
    s2 = mod._stage2_module()
    assert s2.build_layout().n_ports == 150  # 缺省 6×6 与 runs/mapes_s2·s4 同拓扑
    big = s2.build_layout(10)
    assert big.n_ports == 446 and big.n_load_ports == 444  # ⑦ 口径
    assert big.via_slots == ((0, 9, "via_ground"), (9, 0, "via_ground"))
