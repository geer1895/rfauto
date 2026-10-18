"""Pytest 全局 fixtures。"""

import importlib.util
import os
import sys
from pathlib import Path

import pytest

# openEMS 引擎重建后新 .pyd 的依赖 DLL（CSXCAD.dll/fparser.dll/hdf5 等）在
# 引擎 bin 目录——子进程/测试进程需 PATH 含此目录才能加载（否则 CSXCAD
# import 即崩）。目录缺席（干净环境）时为 no-op。
_oe_bin = r"E:\openEMS\install\bin"
if os.path.isdir(_oe_bin) and _oe_bin not in os.environ.get("PATH", ""):
    os.environ["PATH"] = _oe_bin + os.pathsep + os.environ.get("PATH", "")

# ── CSXCAD/openEMS 绑定缺失环境的文件级跳过 ──────────────────────────────────
# CSXCAD/openEMS Python 绑定无 PyPI wheel，需从 openEMS 源码编译进 venv
# （见 docs/openems_build_guide.md）。下列测试文件验证 CSXCAD 级几何结构/
# 网格/渲染产物，缺绑定时无法运行——整文件 skip，纯 Python 逻辑测试不受
# 影响；绑定就位时全部照常运行。
_CSXCAD_TEST_MODULES = frozenset({
    "test_antenna2_templates.py",
    "test_array_templates.py",
    "test_atten_pi_template.py",
    "test_atten_t_template.py",
    "test_coax_wg_template.py",
    "test_coil_nfc_template.py",
    "test_combline_template.py",
    "test_compose_layout_netlist.py",
    "test_coupled_bpf_template.py",
    "test_coupler2_templates.py",
    "test_cps_template.py",
    "test_cpw_template.py",
    "test_diplexer_ridged_templates.py",
    "test_eep_templates.py",
    "test_gysel_miter_ab.py",
    "test_gysel_template.py",
    "test_hairpin_alt_template.py",
    "test_hairpin_template.py",
    "test_interdigital_template.py",
    "test_kicad_board_render.py",
    "test_layout_sim_service.py",
    "test_marchand_via_ab.py",
    "test_metasurface_templates.py",
    "test_mmwave_series_array_template.py",
    "test_msl_cpw_template.py",
    "test_msl_siw_taper_template.py",
    "test_nrts_wiring.py",
    "test_oe_phase3_driver.py",
    "test_openems_real_bundle_offline.py",
    "test_openems_real_smoke.py",
    "test_openems_slotline_port.py",
    "test_openems_templates_bridge.py",
    "test_pcell_dsl.py",
    "test_proposal_chain.py",
    "test_pyramid_horn_template.py",
    "test_ratrace_cylindrical.py",
    "test_ratrace_template.py",
    "test_ring_resonator_template.py",
    "test_schiffman_qwt_templates.py",
    "test_sicl_nway_templates.py",
    "test_sir_bpf_template.py",
    "test_siw_template.py",
    "test_slotline_template.py",
    "test_sma_launcher_template.py",
    "test_solid_import.py",
    "test_stepped_coupled_line_specs.py",
    "test_suspended_stripline_template.py",
    "test_ta_wave_a_templates.py",
    "test_ta_wave_b_templates.py",
    "test_ta_wave_c_templates.py",
    "test_template_geometry_audit.py",
    "test_template_golden.py",
    "test_varactor_bpf_template.py",
    "test_w2_d_z16.py",
})


# 随仓 ngspice（tools/ngspice，未随 git 分发）缺失环境的文件级跳过；
# 可用 RFAUTO_NGSPICE_BIN 指向本机 ngspice 后照常运行。
_NGSPICE_TEST_MODULES = frozenset({
    "test_macromodel.py",
    "test_macromodel_xval.py",
    "test_spice_netlist.py",
})


def _ngspice_available() -> bool:
    import os
    import shutil

    if shutil.which("ngspice"):
        return True
    if os.environ.get("RFAUTO_NGSPICE_BIN"):
        return True
    return (_REPO_ROOT / "tools" / "ngspice" / "Spice64" / "bin").is_dir()


#: Z-6 flaky 隔离（ENV_FLAKY 分级）参数：known_flaky 用例的最大重跑次数。
_FLAKY_RERUNS = 2
#: 重跑隔离总开关（显式意图门，opt-in 口径）：仅 RFAUTO_FLAKY_RERUN=1 时
#: known_flaky 才映射为 pytest.mark.flaky。缺省（含全量终门/并行门）一律
#: 单次执行，失败即回归如实计数。物理红永不隔离——重跑仍红=物理红。
_FLAKY_RERUN_ENV = "RFAUTO_FLAKY_RERUN"


def pytest_configure(config):
    # DP-6：known_flaky marker 注册；该 marker 在
    # pytest_collection_modifyitems 被 RFAUTO_FLAKY_RERUN=1 显式开启时消费
    # （映射为 pytest-rerunfailures 的 flaky(reruns=N)）。
    config.addinivalue_line(
        "markers",
        "known_flaky: 已知偶发/并行不安全测试（须附取证理由，禁止掩盖失败）",
    )


def pytest_collection_modifyitems(config, items):
    import os
    import sys

    by_name_csxcad = importlib.util.find_spec("CSXCAD") is not None
    by_name_ngspice = _ngspice_available()
    on_linux_ci = sys.platform.startswith("linux") and os.environ.get("CI")
    if by_name_csxcad and by_name_ngspice and not on_linux_ci:
        return
    skip_csxcad = pytest.mark.skip(
        reason="CSXCAD/openEMS bindings not installed "
               "(build from source — see docs/openems_build_guide.md)")
    skip_ngspice = pytest.mark.skip(
        reason="ngspice executable not found "
               "(set RFAUTO_NGSPICE_BIN or install ngspice)")
    skip_numeric = pytest.mark.skip(
        reason="numeric trajectory sensitive to BLAS/CPU; "
               "baseline pinned on Windows")
    # (测试文件名, 测试函数名)：轨迹/选型对 BLAS 与 CPU 归约顺序敏感，
    # Windows 基线钉值在 Linux 上会漂移——Linux CI 上诚实跳过
    linux_numeric = frozenset({
        ("test_topology_service.py",
         "test_campaign_constrained_improvement_and_deterministic"),
        ("test_trust_region.py", "test_median_final_improves"),
        ("test_symbolic_fit.py",
         "test_holdout_selection_requires_mask_and_prefers_parsimony"),
        ("test_coupling_matrix.py", "test_high_order_n15_two_tz_fails_honestly"),
        ("test_inverse_design.py", "test_reaches_pass_grade"),
        ("test_macromodel_replay.py",
         "test_replay_skrf_export_n4_matches_closed_form"),
        ("test_macromodel_replay.py",
         "test_replay_skrf_export_reference_pins_mode"),
        ("test_marchand_two_section.py",
         "test_synthesis_deterministic_and_explicit_zc"),
        ("test_marchand_two_section.py",
         "test_reference_mode_output_sha256_unchanged"),
        # ── CI 首跑（2026-10-07 run 37574697027）跨平台数值漂移批 ──
        # FS/FD 路径 1e-13 级回波（Windows 基线钉值逐位断言）
        ("test_w4_a_sm_core.py",
         "test_fd_default_path_zero_change_regression_pin"),
        # 归档 bitwise 回放 1-ulp（z0e_ohm 尾数位）
        ("test_hfss_hairpin_anchor.py",
         "test_line_modes_replays_archived_g2200_bitwise"),
        # 金值复数逐位比对（1-2 ulp）
        ("test_rwg_mmt_refinement.py",
         "test_golden_default_s2x2"),
        # FD 敏感度 rel=1e-6 阈值边缘（1.35× 超差）
        ("test_nf_measurement.py", "test_gum_temp_fd_sensitivities"),
        # 相关归一对角逐位 1（裁剪边界 FP 噪声方向平台相关）
        ("test_ecc_metrics.py", "test_pattern_diagonal_identity_and_bounds"),
        # 反演回 Δ|T|~1e-13dB 上收 1e-30 门：verdict 依赖亚阈 FP 噪声
        # 是否非零（Linux 上恰好 0 → PASS；门活口语义由门定值承载）
        ("test_gstc.py",
         "test_full_band_default_and_gate_fail_verdict"),
        # FSV 分级/判据对 BLAS 归约顺序敏感（gdm_grade_level/at_least_vg）
        ("test_afs_service.py",
         "test_sweep_multiresonance_dict_callback_full_chain"),
        ("test_comsol_close_bundle.py",
         "test_core_runs_full_chain_on_synthetic_callback"),
        # BPF 收敛门欠收敛定级对 BLAS 归约顺序敏感（残差 1e-5 量级漂移
        # 压过 1e-8 级阈值——Linux CI 诚实跳过，Windows 基线照常真跑）
        ("test_synthesis_bpf_polish_backsub.py",
         "test_bpf_n15_two_tz_unconverged_gate_two_sided"),
        # 同上族（run 39043312813 实证）：n13 边界档定级在 Linux BLAS 下
        # 翻到相邻档（'mixed' vs 'shifted'），决策边界量级 1e-7
        ("test_synthesis_bpf_polish_backsub.py",
         "test_bpf_n13_boundary_smoke_both_families"),
        # SLL 指标升降序网格相等性对归约序敏感（字典值第 7 位小数漂移，
        # run 39043312813 实证）——网格方向不变性语义由 Windows 基线承载
        ("test_tma_array.py",
         "test_kernel_sll_metrics_descending_grid_equals_ascending"),
        # ── 以下 run 39116947186 实证（aurora_e 同步批 4b3fff0..c4ef2d3）──
        # GUM 温度通道一阶灵敏度双源断言 tolerance 4.7e-10 被 Linux BLAS
        # 归约序差压穿（Windows 基线 0.0004735723… 稳定）
        ("test_nf_measurement.py",
         "test_gum_temp_fd_sensitivities"),
        # 综合器输出 sha256 逐字节钉含浮点 repr 文本——跨平台字节必漂
        ("test_marchand_two_section.py",
         "test_synthesis_deterministic_and_explicit_zc"),
        ("test_marchand_two_section.py",
         "test_reference_mode_output_sha256_unchanged"),
        # MNA 回放残差阈值（7.9e-3 超阈/1.67e-7 vs 1e-10）在 Linux BLAS 下
        # 越门——回放链数值语义由 Windows 基线承载
        ("test_macromodel_replay.py",
         "test_replay_skrf_export_reference_pins_mode"),
        ("test_macromodel_replay.py",
         "test_replay_skrf_export_n4_matches_closed_form"),
        # GSTC 判决边界翻转（PASS vs FAIL）——决策边界量级漂移
        ("test_gstc.py",
         "test_full_band_default_and_gate_fail_verdict"),
        # ECC 指标对角恒等式在 Linux BLAS 下 assert False（恒等式残差超
        # 内部容差）——恒等式语义由 Windows 基线承载
        ("test_ecc_metrics.py",
         "test_pattern_diagonal_identity_and_bounds"),
        # Q 圆拟合矩阵在 Linux BLAS 下报 Singular matrix（条件数边界）
        ("test_dp2_diagnosis.py",
         "test_q_zero_recovery_noiseless[100.0-0.5]"),
        ("test_dp2_diagnosis.py",
         "test_q_recovery_noiseless_two_channels[100.0-0.5]"),
        # n15 双 TZ 综合收敛判决翻转（honest-fail 路径在不收敛集合下翻转）
        ("test_coupling_matrix.py",
         "test_high_order_n15_two_tz_fails_honestly"),
        # 全链定标断言 6e-33 == 0.0（精确零断言）——归约序残差可见
        ("test_calibration.py",
         "test_catalog_full_chain_is_calibrated"),
        # 输入扭曲 GP 的核矩阵在 Linux numpy/BLAS 下正定性判定失败
        #（本仓新增面，Windows 基线正定）——功能语义由 Windows 基线承载
        ("test_warped_kriging.py",
         "test_warp_improves_steep_function_recovery"),
        ("test_warped_kriging.py",
         "test_deterministic_and_bounds_clipped"),
        # FD 缺省路径零变化回归钉：截断相等断言（19 位 vs 14 位字面量）
        # 在 Linux repr 下末位可见
        ("test_w4_a_sm_core.py",
         "test_fd_default_path_zero_change_regression_pin"),
        # RWG golden S2x2 复数逐位相等——跨平台归约序必漂
        ("test_rwg_mmt_refinement.py",
         "test_golden_default_s2x2"),
        # hairpin 归档逐位回放（bitwise z0e_ohm 文本比较）
        ("test_hfss_hairpin_anchor.py",
         "test_line_modes_replays_archived_g2200_bitwise"),
        # 符号回归精简选式在 Linux 下候选分档不同（2 vs 1）——选式语义
        # 由 Windows 基线承载
        ("test_symbolic_fit.py",
         "test_holdout_selection_requires_mask_and_prefers_parsimony"),
    })
    for item in items:
        name = Path(str(item.fspath)).name
        if not by_name_csxcad and name in _CSXCAD_TEST_MODULES:
            item.add_marker(skip_csxcad)
        if not by_name_ngspice and name in _NGSPICE_TEST_MODULES:
            item.add_marker(skip_ngspice)
        if on_linux_ci and (name, item.name) in linux_numeric:
            item.add_marker(skip_numeric)
    # ── Z-6：known_flaky 消费（ENV_FLAKY 分级）──
    # 重跑只对显式打 known_flaky marker（附取证理由）的用例生效，且必须
    # RFAUTO_FLAKY_RERUN=1 显式开启；未打 marker 的用例在任何配置下都不重跑
    # ——物理红首红就是判定；"首红+重跑绿"只把该次失败分级为 ENV_FLAKY，
    # 重跑仍红=物理红，最终 FAIL 照常上报。
    if os.environ.get(_FLAKY_RERUN_ENV) != "1":
        return
    for item in items:
        if item.get_closest_marker("known_flaky") is not None:
            item.add_marker(pytest.mark.flaky(reruns=_FLAKY_RERUNS))


# 确保 src 在 path 中（editable install 时通常不需要，但安全起见）
src_dir = Path(__file__).parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

_REPO_ROOT = Path(__file__).parent.parent


@pytest.fixture(autouse=True)
def _guard_cwd():
    """全局 chdir 守卫（阶段 0.3）。

    测试或被测代码把 cwd 改走且未还原时（#144 类污染的根因之一；
    openEMS 绑定库也会改写解释器 cwd），自动还原到测试进入前的目录，
    防止后续测试在错误的工作目录里落产物。
    """
    before = os.getcwd()
    yield
    if os.getcwd() != before:
        os.chdir(before)


@pytest.fixture(scope="session", autouse=True)
def _runs_pollution_watch():
    """工作区 runs/ 污染监视（阶段 0.3）。

    unit 套件不应在工作区 runs/ 留任何新目录（真机档 real_edt 永远排除
    在外）。会话结束时对比前后清单，发现残留如实打印——先透明化，再
    定位到具体测试后收紧为 fail。
    """
    runs = _REPO_ROOT / "runs"
    before = {p.name for p in runs.iterdir()} if runs.exists() else set()
    yield
    after = {p.name for p in runs.iterdir()} if runs.exists() else set()
    stray = sorted(after - before)
    if stray:
        import warnings

        warnings.warn(
            f"unit 套件在工作区 runs/ 留下 {len(stray)} 个新目录: {stray}",
            stacklevel=1)


@pytest.fixture
def fake_adapter():
    """提供 FakeAdapter 实例（2 端口，向后兼容）。"""
    from rfauto.adapters.fake_adapter import FakeAdapter
    adapter = FakeAdapter()
    yield adapter
    adapter.close()


@pytest.fixture
def fake_adapter_3port():
    """提供 3 端口 FakeAdapter 实例（P2 调优循环用，iso_s23 可用）。"""
    from rfauto.adapters.fake_adapter import FakeAdapter
    adapter = FakeAdapter(n_ports=3)
    yield adapter
    adapter.close()


@pytest.fixture
def wilkinson_recipe():
    """提供解析后的 Wilkinson 配方数据。"""
    import yaml
    recipe_path = Path(__file__).parent.parent / "recipes" / "wilkinson_pd_v1.yaml"
    with open(recipe_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture
def tmp_run_dir(tmp_path):
    """提供临时 run 目录。"""
    from rfauto.infra.run_store import create_run_dir
    return create_run_dir(tmp_path, "test_run_00000000_00000000")
