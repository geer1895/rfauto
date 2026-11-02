"""Pytest 全局 fixtures。"""

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

# ── CLI --help 渲染跨平台一致化（2026-11-02；Linux CI 11 红根修）─────────────
# typer.rich_utils 在 **import 时**读 env 定模块常量：GITHUB_ACTIONS/FORCE_COLOR/
# PY_COLORS 任一存在 → FORCE_TERMINAL=True（rich_utils.py L78-84），CliRunner
# 捕获的 --help 夹带 ANSI 转义并按缺省 80 列折行——Linux CI 实证 '--warm-start-regis'
# /'--json'/'--stackup' 等旗标断言被转义序列或折行切断（test_edb_cli_mcp/
# test_stackup_diagram/test_w3_c_model_registry 等 11 件），本地 Windows 开发机无
# 这些 env 故从不复现。两键均为 typer 官方开关：_TYPER_FORCE_DISABLE_TERMINAL 强制
# FORCE_TERMINAL=False；TERMINAL_WIDTH→MAX_WIDTH。必须在任何 typer import 之前
# 生效（conftest 是 pytest 加载链里最早可控点；pytest 自身及其插件不 import typer），
# setdefault 保留显式外设。断言零放松：旗标文本本体仍逐字匹配。
os.environ.setdefault("_TYPER_FORCE_DISABLE_TERMINAL", "1")
os.environ.setdefault("TERMINAL_WIDTH", "200")

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
    "test_k11_octagonal_spiral.py", "test_k12_ipc_caps.py",
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


# ── linux_numeric：BLAS/浮点逐位轨迹跨平台漂移的诚实 skip 清单（§C3）──────
# 清单内用例的数值基线钉在 Windows 开发机（逐位/极窄容差断言），Linux CI
# 上同版本 numpy/scipy 也漂（优化器迭代数/模型选型边界/残差末位）——处置
# 口径是诚实 skip 而非放宽断言；数值基线本体仍由 Windows 门全量把守。
# Windows/其他平台此钩子 no-op（清单条目在 Windows 照常执行）。
_LINUX_NUMERIC_TEST_IDS = frozenset({
    # aurora_k/l 新测试首次上 Linux CI 的数值轨迹漂移（2026-10-26 清账）
    "tests/unit/test_afs_service.py::test_sweep_multiresonance_dict_callback_full_chain",
    "tests/unit/test_comsol_close_bundle.py::TestAfsRealcaseCore::"
    "test_core_runs_full_chain_on_synthetic_callback",
    "tests/unit/test_coupling_matrix.py::test_high_order_n15_two_tz_fails_honestly",
    "tests/unit/test_ecc_metrics.py::test_pattern_diagonal_identity_and_bounds",
    "tests/unit/test_gstc.py::TestCrosscheck::test_full_band_default_and_gate_fail_verdict",
    "tests/unit/test_hfss_hairpin_anchor.py::test_line_modes_replays_archived_g2200_bitwise",
    "tests/unit/test_macromodel_replay.py::test_replay_skrf_export_n4_matches_closed_form",
    "tests/unit/test_macromodel_replay.py::test_replay_skrf_export_reference_pins_mode",
    "tests/unit/test_marchand_two_section.py::test_reference_mode_output_sha256_unchanged",
    "tests/unit/test_marchand_two_section.py::test_synthesis_deterministic_and_explicit_zc",
    "tests/unit/test_nf_measurement.py::test_gum_temp_fd_sensitivities",
    "tests/unit/test_rwg_mmt_refinement.py::TestIrisRefinementComparisonDefault::"
    "test_golden_default_s2x2",
    "tests/unit/test_symbolic_fit.py::test_holdout_selection_requires_mask_and_prefers_parsimony",
    "tests/unit/test_synthesis_bpf_polish_backsub.py::test_bpf_n13_boundary_smoke_both_families",
    "tests/unit/test_synthesis_bpf_polish_backsub.py::test_bpf_n15_two_tz_unconverged_gate_two_sided",
    "tests/unit/test_tma_array.py::test_kernel_sll_metrics_descending_grid_equals_ascending",
    "tests/unit/test_w1s3_lange_stepped.py::test_lange_promotion_byte_parity_and_single_object",
    "tests/unit/test_w4s4_core_margin.py::test_ctle_gain_at_phase_and_consistency",
    "tests/unit/test_w6s3_core_domains.py::test_mti_notch_peak_bit_exact_and_periodic",
    # CI 第 2 轮增量（2026-10-26，上轮被同文件早失败/分布掩盖）：
    "tests/unit/test_w4_a_sm_core.py::test_fd_default_path_zero_change_regression_pin",
    "tests/unit/test_warped_kriging.py::TestWarpedKrigingBenchmark::test_warp_improves_steep_function_recovery",
    "tests/unit/test_warped_kriging.py::TestWarpedKrigingBenchmark::test_deterministic_and_bounds_clipped",
    # 公开仓 CI 修复（2026-11-02，四分片实证；CI 与本地 numpy 2.4.6/scipy
    # 1.18.1/sklearn 1.9.1 逐位同版——纯 OpenBLAS 轨迹漂移）：GP 后验/鲁棒 BO
    # 金快照逐位；green_stamp data_free 小网络 600 epoch 梯度轨迹（残差门/
    # GMRES 减半占比/三档共表达均随轨迹分叉）；批量采集 wins 多数门。
    "tests/unit/test_saas_gp_posterior.py::TestDefaultMapEquivalence::test_golden_bitwise",
    "tests/unit/test_tn14_robust_bo.py::TestDefaultEquivalence::test_default_trace_frozen",
    "tests/unit/test_green_stamp.py::test_data_free_residual_descends",
    "tests/unit/test_green_stamp.py::test_gmres_iteration_table_gate",
    "tests/unit/test_green_stamp.py::test_three_tiers_share_expression",
    "tests/unit/test_gp_batch_acquisition.py::TestBatchAucGate::"
    "test_batch_auc_not_worse_than_pointwise_majority_seeds",
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


# ── aurora_m s17：pypssfss/Julia 会话启动期主线程预热（单进程串行门冻结根治）──
# 症状：单进程串行跑 tests/unit（含 -m 'not tier_c' 日常门口径）在 ~4-9min 处
# 死锁，冻结点漂移到随机序里**第一个真实 GET /api/solvers 请求**（W1-8 两轮
# runs/aurora_m/w1_8/serial_hang_evidence.json + s17 seed12345 复现第三例：
# test_ui_auth.py:66，py-spy 实锤主线程卡 TestClient portal.call、anyio
# worker 卡 pypssfss 模块导入的 Julia 侧 seval）。
# 机理：/api/solvers → list_registered_solvers 的适配器可用性探测在
# run_in_threadpool 的 worker 线程内惰性 ``import pypssfss``（juliacall 进程
# 内嵌 Julia；rfauto.adapters 包 __init__ 无条件注册 PSSFSS，故该探测恒在
# 链上）。干净进程该嵌入 ~3-8s 完成（s17 minrepro/julia_thread_probe 实测）；
# 被此前测试交互污染的进程里同一嵌入挂死（同 200 前置文件字母序绿 vs
# seed12345 随机序冻，s17 E1 对照）。W1-8 原归因"TestClient return 无 with
# 线程泄漏"被 s17 证伪：with/return 两形态线程曲线逐位一致、34 文件簇单独
# 跑 827 条 116s 全绿——portal 线程是受害者不是泄漏源。
# 根治：会话启动期（进程最干净态，collection 之前）主线程预热一次 → 之后
# 请求内 ``import pypssfss`` 恒命中 sys.modules 缓存，任何污染态都不再触发
# Julia 嵌入。缺装环境（公开仓默认）find_spec 零开销直通；预热失败不阻塞
# 会话（#105 best-effort 纪律）。成本：+~4s/+~700MB RSS/进程（Julia 常驻）。
# RFAUTO_TEST_NO_JULIA_PREWARM=1 可关（诊断 A/B 用）。


def pytest_sessionstart(session):
    # ── CLI 注册序规范化（2026-11-02；docs 漂移 1 红根修，先于 Julia 预热）──
    # rfauto.cli.domains._core.app 是全进程共享的根 Typer 应用，域模块在
    # **模块 import 时**把各自子应用 add_typer 上去——注册序=import 序。
    # tests/unit 有 6 个文件在模块级直接 import 域模块（如 test_w2_a_campaign
    # 的 `from rfauto.cli.domains.bands_uq import campaign_app`）：xdist worker
    # 里若它们先于 rfauto.cli.main 被收集导入，共享根 app 的注册序即被永久
    # 扰乱 → 进程内 docs_site/reference/cli.md 重生成顺序漂移（CI run
    # 41463250971 shard1 实证 test_check_green_on_committed_docs_site 红：
    # sparams-compare/calc 块易位）。conftest 在收集前 canonical 导入
    # rfauto.cli.main（其内部按 main.py 固定序导入全部域模块），此后测试模块
    # 的域导入全是 sys.modules 缓存命中，注册序恒定；独立脚本/CI docs-drift
    # job（全新解释器）天然同序。
    importlib.import_module("rfauto.cli.main")
    if os.environ.get("RFAUTO_TEST_NO_JULIA_PREWARM") == "1":
        return
    try:
        if importlib.util.find_spec("pypssfss") is None:
            return
        from rfauto.adapters.pssfss_adapter import load_pypssfss

        load_pypssfss()
    except Exception:
        pass  # 预热 best-effort：缺 depot/坏环境时放行原路径（is_available 面）


#: Z-6 flaky 隔离（ENV_FLAKY 分级）参数：known_flaky 用例的最大重跑次数。
_FLAKY_RERUNS = 2
#: 重跑隔离总开关（显式意图门，opt-in 口径）：仅 RFAUTO_FLAKY_RERUN=1 时
#: known_flaky 才映射为 pytest.mark.flaky。缺省（含全量终门/并行门）一律
#: 单次执行，失败即回归如实计数。
_FLAKY_RERUN_ENV = "RFAUTO_FLAKY_RERUN"


# ── aurora_m W1-8：tier 分层 marker（纯元数据，不改任何门缺省行为）─────────
# 名单 = tests/fixtures/test_tiers.yaml（committed，scripts/generate_tier_marks.py
# 生成，只存 B+C；A 层不加标记=缺省不在名单即 A）。tier_b/tier_c 仅供调度面
# （scripts/gate_daily.py 的 -m 过滤）消费——终门永远全量（v2 口径零改动），
# 夜门口径不变。名单文件缺席（CI/公开仓干净环境）→ 不加标记=全量语义
# （诚实降级：行为==终门口径，不 skip 不报错——tests/unit/test_tier_marks.py 钉）。
_TIERS_FIXTURE = Path(__file__).parent / "fixtures" / "test_tiers.yaml"


def load_tier_sets(path=None):
    """读 test_tiers.yaml → (tier_b, tier_c) nodeid 集合。

    诚实降级：文件缺席/损坏（CI/公开仓干净环境）→ (∅, ∅)=不加标记=全量
    语义（行为==终门口径，不 skip 不报错）。
    """
    import yaml  # 惰性：conftest 启动路径零新增硬依赖

    p = Path(path) if path is not None else _TIERS_FIXTURE
    try:
        with open(p, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        tier_b = set((data.get("tier_b") or {}).get("nodeids") or [])
        tier_c = set((data.get("tier_c") or {}).get("nodeids") or [])
    except (OSError, yaml.YAMLError, AttributeError, TypeError):
        return set(), set()
    return tier_b, tier_c


def apply_tier_markers(items, path=None):
    """给收集项施加 tier_b/tier_c marker（A 层不加=缺省）；返回 (b, c) 计数。

    marker 纯元数据：不加 deselect、不加 skip——任何不带 -m 过滤的运行
    （终门/夜门/CI）收集集与行为零变化。
    """
    tier_b, tier_c = load_tier_sets(path)
    n_b = n_c = 0
    for item in items:
        nid = item.nodeid
        if nid in tier_c:
            item.add_marker(pytest.mark.tier_c)
            n_c += 1
        elif nid in tier_b:
            item.add_marker(pytest.mark.tier_b)
            n_b += 1
    # 观测性（#105 best-effort，env 门控）：调度面（gate_daily）按段聚合
    # 真实施加计数——pytest -q 终端不吐 "N deselected" 行，汇总行此路取数。
    out = os.environ.get("RFAUTO_TIER_COUNTS_OUT")
    if out:
        try:
            with open(out, "a", encoding="utf-8") as f:
                f.write(json.dumps({"applied_b": n_b, "applied_c": n_c,
                                    "n_items": len(items),
                                    "pid": os.getpid()}) + "\n")
        except OSError:
            pass
    return n_b, n_c


def pytest_collection_modifyitems(config, items):
    # aurora_m W1-8：tier 分层标记先行（观测性同律 #105——分层是调度增强，
    # 绝不阻塞测试主路径；失败降级为告警+全量语义）
    try:
        apply_tier_markers(items)
    except Exception:
        import warnings

        warnings.warn("tier marker 施加失败（按全量语义继续）", stacklevel=1)

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

    # ── linux_numeric 消费（BLAS/浮点轨迹跨平台漂移，仅 Linux 生效）──────
    if sys.platform.startswith("linux"):
        skip_numeric = pytest.mark.skip(
            reason="BLAS/浮点逐位轨迹跨平台漂移——数值基线钉在 Windows"
                   "（linux_numeric 清单诚实 skip，非放宽断言）")
        for item in items:
            if item.nodeid in _LINUX_NUMERIC_TEST_IDS:
                item.add_marker(skip_numeric)


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


# ── T5 conftest fixture 库（aurora_g W8-S3 首批）───────────────────────────
# 背景：`_isolated` 同名复制 55 份（R1 审计 §面4：conftest fixture 9 vs
# 本地散装 446）——同一套"chdir 落 tmp"模板手工复制，任何一份修 bug 都
# 不会同步到其余副本。本节把最高频两种形态收口为单源；迁移文件保留一行
# autouse 适配器（``def _isolated(isolated): yield``）——autouse 语义与
# 测试函数签名零变化，隔离实现单源化。
# 棘轮：tests/unit/test_conftest_fixture_hygiene.py AST 扫描禁止本地重写
# 隔离体；剩余未迁移文件在该测试 ALLOWLIST 只可删不可加。
# 分批口径：首批 top-10（7 份纯 chdir + 3 份 chdir+cache_off）；
# 二批 next-10（W9-S4：6 份纯 chdir + 3 份 chdir+cache_off + 1 份
# 专用超集 isolated+mkdir runs）；三批 next-10（W10-S3：6 份纯 chdir +
# 3 份 chdir+cache_off + 1 份专用超集 isolated+job 注册表重置）；
# 四批 next-10（W14-S1）；五批 next-10（W15-S3：4 份纯 chdir +
# 4 份 chdir+cache_off（2 份带 RFAUTO_REGISTRY_DB 清位增量）+ 2 份
# 专用超集 isolated+KiCad 钉 / isolated+env 集合清位）；
# 六批（aurora_h W2-S4，2026-10-19）：余量 28 份全部收编为单源适配器
# （纯 chdir / chdir+cache_off 一行委托；kicad/sim_ci/rest/optuna 等
# 专用超集 = 依赖公共 fixture 后保留专用增量），棘轮 ALLOWLIST 清零——
# tests/unit/test_conftest_fixture_hygiene.py 三个方向全绿为收编门。


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """cwd 隔离单源（形态①：仅 chdir，原 30 份本地 `_isolated` 的公共体）。

    用法（迁移文件）：保留本地 autouse 适配器一行，体委托本 fixture::

        @pytest.fixture(autouse=True)
        def _isolated(isolated):
            yield

    新写测试可直接参数注入 ``def test_xxx(isolated):``。
    """
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def isolated_cache_off(tmp_path, monkeypatch):
    """cwd 隔离+结果缓存关闭单源（形态②：chdir+RFAUTO_CACHE=off，原 ~20 份）。

    RFAUTO_CACHE=off 语义：被测链路禁读/禁写结果缓存（run 复用类测试
    需要真实执行路径，见 #158 口径的反向面）。
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RFAUTO_CACHE", "off")
    return tmp_path
