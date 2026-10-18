"""Pytest 全局 fixtures。"""

import importlib.util
import os
import sys
from pathlib import Path

import pytest

# EC-12（2026-10-06）：openEMS 引擎重建至 E:\openEMS\install\bin——
# 新 .pyd 的依赖 DLL（CSXCAD.dll/fparser.dll/hdf5 2.2 等）在该目录，
# 子进程/测试进程需 PATH 含此目录才能加载（否则 CSXCAD import 即崩）。
_oe_bin = r"E:\openEMS\install\bin"
if os.path.isdir(_oe_bin) and _oe_bin not in os.environ.get("PATH", ""):
    os.environ["PATH"] = _oe_bin + os.pathsep + os.environ.get("PATH", "")

# ── CSXCAD/openEMS 绑定与 ngspice 缺失环境的文件级跳过（自公开仓同源回移）──
# 绑定无 PyPI wheel 需源码编译（docs/openems_build_guide.md）；ngspice 可用
# RFAUTO_NGSPICE_BIN 指定。环境齐备（内部开发机常态）时钩子为 no-op。
_CSXCAD_TEST_MODULES = frozenset({
    "test_antenna2_templates.py", "test_array_templates.py",
    "test_combline_template.py", "test_coupled_bpf_template.py",
    "test_coupler2_templates.py", "test_cps_template.py",
    "test_atten_pi_template.py", "test_atten_t_template.py",
    "test_cpw_template.py", "test_ta_wave_a_templates.py",
    "test_gysel_miter_ab.py", "test_gysel_template.py",
    "test_hairpin_alt_template.py", "test_hairpin_template.py",
    "test_interdigital_template.py", "test_kicad_board_render.py",
    "test_coil_nfc_template.py", "test_eep_templates.py",
    "test_marchand_via_ab.py", "test_metasurface_templates.py",
    "test_mmwave_series_array_template.py", "test_msl_cpw_template.py",
    "test_msl_siw_taper_template.py", "test_nrts_wiring.py",
    "test_openems_real_bundle_offline.py", "test_openems_slotline_port.py",
    "test_openems_real_smoke.py", "test_openems_templates_bridge.py",
    "test_coax_wg_template.py", "test_compose_layout_netlist.py",
    "test_diplexer_ridged_templates.py", "test_layout_sim_service.py",
    "test_oe_phase3_driver.py", "test_pyramid_horn_template.py",
    "test_ring_resonator_template.py", "test_schiffman_qwt_templates.py",
    "test_sicl_nway_templates.py", "test_ta_wave_b_templates.py",
    "test_ta_wave_c_templates.py", "test_varactor_bpf_template.py",
    "test_w2_d_z16.py",
    "test_pcell_dsl.py",
    "test_proposal_chain.py", "test_ratrace_cylindrical.py",
    "test_ratrace_template.py", "test_sir_bpf_template.py",
    "test_siw_template.py", "test_sma_launcher_template.py",
    "test_solid_import.py", "test_slotline_template.py",
    "test_stepped_coupled_line_specs.py",
    "test_suspended_stripline_template.py",
    "test_template_geometry_audit.py",
    "test_template_golden.py",
})
_NGSPICE_TEST_MODULES = frozenset({
    "test_macromodel.py", "test_macromodel_xval.py", "test_spice_netlist.py",
})


def _ngspice_available() -> bool:
    import shutil

    if shutil.which("ngspice"):
        return True
    if os.environ.get("RFAUTO_NGSPICE_BIN"):
        return True
    return (_REPO_ROOT / "tools" / "ngspice" / "Spice64" / "bin").is_dir()


def pytest_configure(config):
    # DP-6：known_flaky marker 注册；Z-6（2026-10-05 W1-E）起该 marker 被
    # pytest_collection_modifyitems 消费——RFAUTO_FLAKY_RERUN=1 显式开启时
    # 映射为 pytest-rerunfailures 的 flaky(reruns=N)（见下方 ENV_FLAKY 分级
    # 注释）。并行守卫冻结期间仍按 flake 流程取证后才允许打此 marker。
    config.addinivalue_line(
        "markers",
        "known_flaky: 已知偶发/并行不安全测试（须附取证理由，禁止掩盖失败）",
    )
    # （openems_compat marker 已撤：EC-12 适配批 2026-10-06 完成 CPWPort
    #  exc_dir 重映射+GetLines 排序适配，无在钉测试——登记见 COMPAT_REGISTRY）


#: Z-6 flaky 隔离（ENV_FLAKY 分级）参数：known_flaky 用例的最大重跑次数。
_FLAKY_RERUNS = 2
#: 重跑隔离总开关（显式意图门，opt-in 口径）：仅 RFAUTO_FLAKY_RERUN=1 时
#: known_flaky 才映射为 pytest.mark.flaky。缺省（含全量终门/并行门）一律
#: 单次执行，失败即回归如实计数。
_FLAKY_RERUN_ENV = "RFAUTO_FLAKY_RERUN"


def pytest_collection_modifyitems(config, items):
    has_csxcad = importlib.util.find_spec("CSXCAD") is not None
    has_ngspice = _ngspice_available()
    if not (has_csxcad and has_ngspice):
        skip_csxcad = pytest.mark.skip(
            reason="CSXCAD/openEMS bindings not installed "
                   "(build from source — see docs/openems_build_guide.md)")
        skip_ngspice = pytest.mark.skip(
            reason="ngspice executable not found "
                   "(set RFAUTO_NGSPICE_BIN or install ngspice)")
        for item in items:
            name = Path(str(item.fspath)).name
            if not has_csxcad and name in _CSXCAD_TEST_MODULES:
                item.add_marker(skip_csxcad)
            if not has_ngspice and name in _NGSPICE_TEST_MODULES:
                item.add_marker(skip_ngspice)

    # ── Z-6：known_flaky 消费（ENV_FLAKY 分级，2026-10-05 W1-E）──
    # 诚实分级铁律——**物理红永不隔离**：
    # 1. 重跑只对显式打 known_flaky marker（附取证理由）的用例生效，且必须
    #    RFAUTO_FLAKY_RERUN=1 显式开启；缺省门/终门/并行门一律单次执行，
    #    失败即回归，如实计数；
    # 2. 未打 marker 的用例在任何配置下都不重跑——物理红（模型错/断言错/
    #    环境真坏）首红就是判定，重跑隔离不得用来"再试一次碰运气"；
    # 3. "首红+重跑绿"只把该次失败**分级**为 ENV_FLAKY（环境类抖动，不计
    #    回归），不改测试本体判定——重跑仍红=物理红，最终 FAIL 照常上报。
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
