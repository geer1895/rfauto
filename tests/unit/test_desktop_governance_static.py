"""桌面治理静态钉（汇总）：杀进程原语单点化 + 逐脚本委托存在性。

不变量（runs/df5_desktop_governance/criteria.md §3）：
- 16 个直接委托脚本的 **subprocess 调用参数里不得再出现 Stop-Process**
  （AST 级断言；杀进程原语单点存在于 src/rfauto/infra/desktop_guard.py）；
- 2 个传递消费者（wp39_followup_run/slotline_transitions）经 provider
  传递受益，引用面不回退；
- hfss_interdigital_check 预检保持 fail-closed（范式参考实现，不代杀）；
- hfss_hairpin_anchor_c8 / hfss_hairpin_eigen_ext 属 cmdline 属主过滤
  点杀形态（无连坐面），禁止回退成 Get-Process 管道无条件杀；
- factory_mf 单源化 + E-MED-5 双件套（solve 看门狗 + release 150s 上限）。
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"

# 直接委托 desktop_guard 的脚本（criteria.md 替换矩阵 #1-#17）
DIRECT_DELEGATORS = [
    "factory_mf_hfss_anchors.py",      # 单源化：三函数上收 + E-MED-5
    "hfss_helix_arbitration.py",
    "hfss_hairpin_anchor.py",
    "hfss_slotline_arbitration.py",
    "hfss_mapes_m_arbitration.py",
    "hfss_mline_probe.py",
    "hfss_mapes_g0_arbitration.py",
    "icepak_electrothermal_case.py",
    "icepak_hfss_loss_e2e.py",
    "hfss_same_geometry_arbitration.py",
    "icepak_convection_case.py",
    "hfss_cps_arbitration.py",
    "hfss_mline_repro_sweep_assert.py",
    "q3d_parasitic_case.py",
    "hfss_ratrace_arbitration.py",
    "wp39_benchmark_run.py",
]

# 功能内注释/docstring 提及"Stop-Process 已废弃"不算违例——只有
# subprocess 调用的字符串常量才会执行。此 helper 收集后者。
_SUBPROCESS_FUNCS = {"run", "Popen", "check_output", "call", "check_call"}


def _subprocess_string_consts(src: str) -> set[str]:
    """AST 收集全部 subprocess.* 调用涉及的字符串常量（含列表元素）。"""
    tree = ast.parse(src)
    consts: set[str] = []

    def _collect(node: ast.AST) -> None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            consts.append(node.value)
        else:
            for child in ast.iter_child_nodes(node):
                _collect(child)

    for call in ast.walk(tree):
        if not isinstance(call, ast.Call):
            continue
        func = call.func
        # subprocess.run(...) / run(...)（from subprocess import run）
        is_sub = (isinstance(func, ast.Attribute)
                  and isinstance(func.value, ast.Name)
                  and func.value.id == "subprocess"
                  and func.attr in _SUBPROCESS_FUNCS)
        is_bare = (isinstance(func, ast.Name) and func.id in _SUBPROCESS_FUNCS)
        if is_sub or is_bare:
            for arg in (*call.args, *[k.value for k in call.keywords]):
                _collect(arg)
    return consts


def _src(name: str) -> str:
    return (SCRIPTS / name).read_text(encoding="utf-8")


def test_direct_delegators_no_stop_process_in_subprocess_args():
    for name in DIRECT_DELEGATORS:
        consts = _subprocess_string_consts(_src(name))
        bad = [c for c in consts if "Stop-Process" in c]
        assert not bad, (
            f"{name}: subprocess 调用参数含杀进程原语 {bad!r}——杀进程必须"
            f"委托 src/rfauto/infra/desktop_guard.py（单源，#245/#265）")


def test_direct_delegators_reference_single_source():
    for name in DIRECT_DELEGATORS:
        src = _src(name)
        assert "kill_orphan_ansysedt_desktops" in src or (
            name == "factory_mf_hfss_anchors.py"
            and "_kill_desktops" in src), (
            f"{name}: 未委托单源 kill_orphan_ansysedt_desktops")
        assert "desktop_guard" in src, (
            f"{name}: 未引用 src/rfauto/infra/desktop_guard 单源模块")


def test_factory_mf_single_sourced_no_local_kill_defs():
    src = _src("factory_mf_hfss_anchors.py")
    tree = ast.parse(src)
    funcs = {n.name for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for gone in ("_kill_desktops", "_list_ansysedt_processes",
                 "_process_alive"):
        assert gone not in funcs, (
            f"factory_mf: 本地 {gone} 应已上收 src/rfauto/infra/"
            "desktop_guard.py（单源化），不得残留本地副本（#116 死副本族）")


def test_transitive_consumers_wiring_intact():
    # wp39_followup_run 经 import wp39_benchmark_run 传递受益
    follow = _src("wp39_followup_run.py")
    assert "runner._kill_desktops()" in follow, (
        "wp39_followup_run: runner._kill_desktops 引用面回退")
    assert "import wp39_benchmark_run as runner" in follow
    # slotline_transitions 经 ARB alias 传递受益
    trans = _src("hfss_slotline_transitions.py")
    assert "_kill_desktops = ARB._kill_desktops" in trans, (
        "slotline_transitions: ARB alias 引用面回退")
    # 收尾扫尾点必须 non-strict（活桌面不连坐已完成战役）
    assert "_kill_desktops(strict=False)" in trans
    for name in ("hfss_hairpin_anchor.py", "hfss_cps_arbitration.py",
                 "hfss_slotline_arbitration.py"):
        assert "_kill_desktops(strict=False)" in _src(name), (
            f"{name}: 收尾扫尾点未传 strict=False（criteria B 类）")


def test_interdigital_check_preflight_fail_closed():
    src = _src("hfss_interdigital_check.py")
    assert "_assert_existing_desktops_none" in src
    assert "raise RuntimeError" in src, "预检必须 fail-closed 抛错"
    bad = [c for c in _subprocess_string_consts(src) if "Stop-Process" in c]
    assert not bad, (
        "hfss_interdigital_check 是不代杀参考实现，不得出现杀进程原语")


def test_cmdline_owned_point_kill_scripts_not_regressed():
    """c8/eigen_ext：cmdline 属主过滤点杀（无连坐面）——禁止回退成
    Get-Process 管道无条件杀；点杀必须带 -Id 参数化 PID。"""
    for name in ("hfss_hairpin_anchor_c8.py", "hfss_hairpin_eigen_ext.py"):
        src = _src(name)
        consts = _subprocess_string_consts(src)
        kill_consts = [c for c in consts if "Stop-Process" in c]
        assert kill_consts, f"{name}: 点杀形态丢失？"
        for c in kill_consts:
            assert "Get-Process" not in c, (
                f"{name}: 出现 Get-Process 管道无条件杀回退（{c!r}）——"
                "属主过滤点杀形态是 #265 底线")
            assert "-Id" in c, f"{name}: 点杀必须 -Id 参数化（{c!r}）"
        assert "cmdline" in src, f"{name}: 属主过滤（cmdline 匹配）丢失"


def test_infra_guard_single_point_semantics():
    src = (REPO / "src" / "rfauto" / "infra" / "desktop_guard.py").read_text(
        encoding="utf-8")
    assert "Stop-Process -Id" in src, "单源点杀原语缺失"
    assert "Get-CimInstance" in src, "单源枚举（pid/ppid/命令行）缺失"
    consts = _subprocess_string_consts(src)
    assert not [c for c in consts
                if "Get-Process" in c and "Stop-Process" in c], (
        "单源内也禁止 Get-Process 管道无条件杀形态")


def test_factory_mf_e_med5_watchdog_and_release_cap():
    src = _src("factory_mf_hfss_anchors.py")
    assert "run_with_watchdog(" in src, "E-MED-5：solve 看门狗缺失"
    assert "release_desktop_capped(" in src, "E-MED-5：release 上限缺失"
    assert 'RFAUTO_HFSS_SOLVE_TIMEOUT_S' in src, (
        "看门狗须走 #145 env 口径 RFAUTO_HFSS_SOLVE_TIMEOUT_S")
    assert "21600" in src, "缺省 6h 上限（interdigital 同款）缺失"
    # release 上限语义在单源侧钉 150s 缺省
    infra_src = (REPO / "src" / "rfauto" / "infra" /
                 "desktop_guard.py").read_text(encoding="utf-8")
    assert "RELEASE_DESKTOP_CAP_S = 150.0" in infra_src


def test_no_unconditional_get_process_kill_anywhere_in_scripts():
    """全 scripts/ 兜底：任何 subprocess 字符串里 'Get-Process' 与
    'Stop-Process' 同串（管道无条件杀形态）即红——防新增脚本回退。"""
    offenders: list[str] = []
    for path in sorted(SCRIPTS.glob("*.py")):
        try:
            consts = _subprocess_string_consts(
                path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - 历史脚本可编译性由 CI 保证
            continue
        if any("Get-Process" in c and "Stop-Process" in c for c in consts):
            offenders.append(path.name)
    assert not offenders, (
        f"scripts/ 出现 Get-Process|Stop-Process 无条件代杀回退：{offenders}"
        f"（#265 误杀他轨合法桌面；必须委托 desktop_guard 单源）")
