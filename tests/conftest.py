"""Pytest 全局 fixtures。"""

import importlib.util
import os
import sys
from pathlib import Path

import pytest

# ── CSXCAD/openEMS 绑定缺失环境的文件级跳过 ──────────────────────────────────
# CSXCAD/openEMS Python 绑定无 PyPI wheel，需从 openEMS 源码编译进 venv
# （见 docs/openems_build_guide.md）。下列测试文件验证 CSXCAD 级几何结构/
# 网格/渲染产物，缺绑定时无法运行——整文件 skip，纯 Python 逻辑测试不受
# 影响；绑定就位时全部照常运行。
_CSXCAD_TEST_MODULES = frozenset({
    # 依据公开仓独立环境全量门的 ModuleNotFoundError: CSXCAD 失败集圈定
    "test_antenna2_templates.py",
    "test_array_templates.py",
    "test_coupled_bpf_template.py",
    "test_hairpin_alt_template.py",
    "test_hairpin_template.py",
    "test_interdigital_template.py",
    "test_marchand_via_ab.py",
    "test_msl_cpw_template.py",
    "test_openems_real_bundle_offline.py",
    "test_openems_slotline_port.py",
    "test_openems_templates_bridge.py",
    "test_pcell_dsl.py",
    "test_proposal_chain.py",
    "test_sir_bpf_template.py",
    "test_sma_launcher_template.py",
    "test_solid_import.py",
    "test_slotline_template.py",
    "test_stepped_coupled_line_specs.py",
    "test_suspended_stripline_template.py",
    "test_template_geometry_audit.py",
    "test_combline_template.py",
    "test_coupler2_templates.py",
    "test_cps_template.py",
    "test_gysel_miter_ab.py",
    "test_gysel_template.py",
    "test_kicad_board_render.py",
    "test_ratrace_cylindrical.py",
    "test_ratrace_template.py",
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
    })
    for item in items:
        name = Path(str(item.fspath)).name
        if not by_name_csxcad and name in _CSXCAD_TEST_MODULES:
            item.add_marker(skip_csxcad)
        if not by_name_ngspice and name in _NGSPICE_TEST_MODULES:
            item.add_marker(skip_ngspice)
        if on_linux_ci and (name, item.name) in linux_numeric:
            item.add_marker(skip_numeric)


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
