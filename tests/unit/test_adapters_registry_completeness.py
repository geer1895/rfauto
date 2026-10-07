"""adapters 注册键集完整性测试（审查 M-P0-1 修复批 C）。

对 src/rfauto/adapters/__init__.py docstring 的三类通道承诺做键集级回归：
1. 导入即注册：``import rfauto.adapters`` 后全局 EMSolverRegistry 必含
   REGISTRY_AUTO 全部键（键集断言，非消费尾序钉）；
2. 显式注册通道：REGISTRY_EXPLICIT 的 register 函数向任意注册表实例贡献
   预期键（独立 EMSolverRegistry 实例验证，不污染全局），且模块导入本身
   不产生注册副作用之外的全局键漂移；
3. 幂等：重复 import 与重复调用注册函数均不使注册表键数膨胀
   （slice3 盲区 7 回归钉）；
4. 文件系统全量 import 体检：任何 adapters/*.py 缺**外部**可选依赖时记
   expected-missing（标注依赖名）不算失败；rfauto 内部导入链断裂照常红；
   新增模块必须先登记进三张清单之一（强制注册面决策，防静默漂移）。

#362 铁律：本文件禁止 importlib.reload——幂等断言全部走"重复调用注册
函数"路径（模块缓存下二次 import 不重执行注册体，恰好是幂等的机理）。
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest

from rfauto.adapters import em_solver_base
from rfauto.adapters.em_solver_base import (
    EMSolverAdapter,
    EMSolverRegistry,
    EMSolverType,
    get_global_registry,
    solver_capabilities_for,
)

ADAPTERS_DIR = Path(em_solver_base.__file__).resolve().parent  # __file__ 是 str（#140 口径先 Path() 收敛）

# ─── 注册面清单（唯一事实源，与 adapters/__init__.py docstring 逐字对应）─────

#: 一、导入即注册：模块 →（注册函数名，预期键集）
REGISTRY_AUTO: dict[str, tuple[str, frozenset[str]]] = {
    "openems_solver": ("register_openems", frozenset({"openems"})),
    "meep_adapter": ("register_meep", frozenset({"meep"})),
    "elmer_adapter": ("register_elmer_adapter", frozenset({"elmer"})),
    "palace_solver": ("register_palace", frozenset({"palace"})),
    "comsol_adapter": ("register_comsol", frozenset({"comsol"})),
    "ngsolve_adapter": ("register_ngsolve", frozenset({"ngsolve"})),
    "vna_adapter": ("register_vna", frozenset({"vna"})),
    "qucsator_adapter": ("register_qucsator", frozenset({"qucsator"})),
    "xyce_adapter": ("register_xyce", frozenset({"xyce"})),
    "mmt_adapter": ("register_mmt", frozenset({"mmt"})),
    # EC-20（W2-F 2026-10-05）：PSSFSS 周期结构快档（第 13 注册键）
    "pssfss_adapter": ("register_pssfss", frozenset({"pssfss"})),
}

#: 二、显式注册：模块 →（注册函数名，预期键集）；模块导入本身不注册
REGISTRY_EXPLICIT: dict[str, tuple[str, frozenset[str]]] = {
    "icepak_adapter": ("register_icepak_adapter", frozenset({"icepak"})),
    "q3d_adapter": ("register_q3d_adapter", frozenset({"q3d"})),
    # ge8c 席5 gpl 隔离子包（SV-1/SV-2）：显式注册通道、str 字面键
    # （非 EMSolverType 枚举——r3_services.list_registered_solvers 已双形态
    # 防御，八百一十九终门实证）；许可 fail-closed 门见 adapters/gpl/license_gate
    # stem 形态（discovered=顶层 glob 的 p.stem；gpl/ 子包文件 stem 同顶层平铺）
    "gpl/pypo_adapter": ("register_pypo", frozenset({"pypo"})),
    "gpl/scuff_adapter": ("register_scuff", frozenset({"scuff"})),
}

#: 三、非注册表面（SimulatorAdapter 家族 / ADS 独立协议 / 工具·模板层）：
#: 仅登记存在性，不得向 EMSolverRegistry 贡献键
NON_REGISTRY: dict[str, str] = {
    "gpl/license_gate": "gpl/ 子包许可 fail-closed 双门（ge8c 席5，无注册副作用）",
    "fake_adapter": "SimulatorAdapter 家族（optimization 消费点直连实例化）",
    "hfss_adapter": "SimulatorAdapter 家族",
    "openems_optimizer_adapter": "SimulatorAdapter 家族（openems 优化评估通道）",
    "ads_python_api": "ADS 独立协议（A 档）",
    "ads_netlist": "ADS 独立协议（B 档主通道）",
    "em_solver_base": "注册表本体",
    "hfss_session": "HFSS 会话工具层",
    "hfss_builder_utils": "HFSS 建模工具层",
    "hfss_import": "HFSS 导入互操作",
    "interchange": "版图互换",
    "kicad_board_render": "KiCad 渲染（子进程）",
    "kicad_drc": "KiCad DRC（子进程）",
    "kicad_extract": "KiCad 提取（子进程）",
    "kicad_pcell": "KiCad P-Cell（子进程）",
    "kicad_power_pairs": "KiCad 电源对提取（.kicad_pcb 文本解析，B5-5）",
    "layout_generator": "版图生成",
    "layout_interchange": "版图互换",
    "layout_ports": "版图端口",
    "layout_stack": "叠层",
    "layout_substrate": "基板",
    "openems_adapter": "openEMS 工具层",
    "openems_rotation": "openEMS 旋转装配",
    "openems_slotline_port": "openEMS 槽线端口工具",
    "openems_templates": "openEMS 模板库",
    "slotline_lumped_template": "openEMS 模板",
    "slotline_template": "openEMS 模板",
    "slotline_transitions_template": "openEMS 模板",
    "fdtd_diff": "FDTD 差分工具",
    "spice_netlist": "SPICE 网表",
    "touchstone_interop": "Touchstone 互操作",
    "solid_import": "实体导入",
    "ngsolve_modes": "NGSolve 模式工具",
}

#: 接受 registry 参数的注册函数所属模块（可向独立注册表实例注册）
ACCEPTS_REGISTRY: frozenset[str] = frozenset({
    "elmer_adapter",
    "vna_adapter",
    "qucsator_adapter",
    "xyce_adapter",
    "mmt_adapter",
    "icepak_adapter",
    "q3d_adapter",
    "pssfss_adapter",
})

#: 已知惰性依赖标签（expected-missing 记账展示用；引擎 SDK 均为函数内
#: 惰性 import，本项目核心依赖环境下应全部导入成功、零缺席）
KNOWN_LAZY_DEPS: dict[str, str] = {
    "comsol_adapter": "MPh（COMSOL 桥）",
    "meep_adapter": "meep",
    "ngsolve_adapter": "ngsolve / NGSolve",
    "openems_solver": "openEMS/CSXCAD 绑定",
    "hfss_adapter": "pyaedt（ansys-aedt-core）",
    "icepak_adapter": "pyaedt（ansys-aedt-core）",
    "q3d_adapter": "pyaedt（ansys-aedt-core）",
    "pssfss_adapter": "pypssfss（Julia PSSFSS 桥，extras pssfss）",
}

#: 非 EMSolverAdapter 契约的适配器类（三通道 docstring 承诺的结构反面）
NOT_EMSOLVER_CLASSES: dict[str, str] = {
    "fake_adapter": "FakeAdapter",
    "hfss_adapter": "HfssAdapter",
    "openems_optimizer_adapter": "OpenEMSOptAdapter",
    "ads_python_api": "AdsPythonApiAdapter",
}


def _import_adapter_module(module_name: str) -> tuple[Any | None, str | None]:
    """导入 adapters 子模块；返回 (module, expected_missing_dep)。

    expected_missing_dep 非 None = 缺**外部**可选依赖（裸环境合法缺席，
    记账不失败）；rfauto 内部导入链断裂视为真实缺陷照常抛出——缺依赖
    只豁免第三方包，不豁免仓内坏 import。
    """
    try:
        # 子包键（gpl/pypo_adapter）斜杠转点号——清单键=相对 posix 路径
        return importlib.import_module(
            f"rfauto.adapters.{module_name.replace(chr(47), chr(46))}"), None
    except ImportError as exc:
        missing = getattr(exc, "name", "") or ""
        if missing.startswith("rfauto"):
            raise
        label = KNOWN_LAZY_DEPS.get(module_name) or missing or type(exc).__name__
        return None, label


def _registry_keys(registry: EMSolverRegistry) -> set[str]:
    """注册表键集（str 口径，兼容 str-Enum 键与自定义字符串键）。"""
    return {str(getattr(k, "value", k)) for k in registry.list_available()}


def _all_planned_modules() -> set[str]:
    return set(REGISTRY_AUTO) | set(REGISTRY_EXPLICIT) | set(NON_REGISTRY)


@pytest.fixture(autouse=True)
def _restore_global_registry():
    """全局注册表快照还原（#362② 同族治理）：本文件多处裸调注册函数
    （``fn()`` 缺省注册进全局表——TestIdempotentRegistration 的
    ``_run_all_register_fns_once``），Icepak/Q3D 显式通道键会泄入全局。

    字母序本文件先于 test_hfss_capabilities / test_solver_capabilities 执行，
    泄漏的 q3d 打红其「未注册探针=Q3D」有意契约（2026-10-01 月终门 13 红
    B 组根因）——本 fixture 使 completeness 的注册副作用不外泄：yield 前
    快照全局表内部容器，yield 后还原。"""
    reg = get_global_registry()
    snapshot = dict(reg._solvers)
    yield
    reg._solvers.clear()
    reg._solvers.update(snapshot)


class TestPackageImportKeys:
    """断言①：导入即注册键集（对 docstring 承诺一的键集级钉）。"""

    def test_package_import_registers_all_auto_channels(self):
        import rfauto.adapters  # noqa: F401  幂等导入（sys.modules 命中亦可）

        reg = get_global_registry()
        have = _registry_keys(reg)
        for module_name, (_fn, expected) in REGISTRY_AUTO.items():
            for key in expected:
                assert key in have, (
                    f"{module_name} 应在 import rfauto.adapters 时注册键 {key!r}；"
                    "若该模块因缺可选依赖未导入，应记 expected-missing 而非静默缺键"
                )
                assert reg.lookup(key) is not None

    def test_global_registry_has_no_stray_builtin_keys(self):
        """全局注册表不得出现清单外内置键（三方 entry-point 插件除外的历史
        泄漏会在此红——新内置通道必须先登记 docstring 与本清单）。"""
        import rfauto.adapters  # noqa: F401

        allowed: set[str] = set()
        for _fn, keys in REGISTRY_AUTO.values():
            allowed |= keys
        for _fn, keys in REGISTRY_EXPLICIT.values():
            allowed |= keys  # 显式通道键可由更早执行的测试合法注入全局
        stray = _registry_keys(get_global_registry()) - allowed
        assert not stray, (
            f"注册表出现清单外内置键 {sorted(stray)}——新增注册通道必须先"
            "登记 adapters/__init__.py docstring 与本测试 REGISTRY_* 清单"
        )


class TestExplicitRegisterChannels:
    """断言②：显式注册通道的函数契约（独立注册表实例，零全局污染）。"""

    @pytest.mark.parametrize("module_name", sorted(REGISTRY_EXPLICIT))
    def test_explicit_register_into_fresh_registry(self, module_name: str):
        fn_name, expected = REGISTRY_EXPLICIT[module_name]
        module, missing = _import_adapter_module(module_name)
        if module is None:
            pytest.skip(f"缺外部可选依赖（{missing}），允许缺席")
        reg = EMSolverRegistry()  # 独立实例：验证函数契约本身，零全局污染
        fn = getattr(module, fn_name, None)
        assert fn is not None, f"{module_name} 缺注册函数 {fn_name}"
        ret = fn(reg)
        if isinstance(ret, bool):
            assert ret is True
        assert _registry_keys(reg) == set(expected), (
            f"{module_name}.{fn_name} 应向给定注册表贡献且仅贡献 {sorted(expected)}"
        )
        fn(reg)  # 幂等：同键覆盖，不膨胀
        assert len(_registry_keys(reg)) == len(expected)

    @pytest.mark.parametrize("module_name", sorted(ACCEPTS_REGISTRY))
    def test_param_accepting_register_is_isolated(self, module_name: str):
        """接受 registry 参数的注册函数必须尊重显式传入的注册表实例
        （不偷写全局——观测面隔离契约）。"""
        table = REGISTRY_EXPLICIT if module_name in REGISTRY_EXPLICIT else REGISTRY_AUTO
        fn_name, expected = table[module_name]
        module, missing = _import_adapter_module(module_name)
        if module is None:
            pytest.skip(f"缺外部可选依赖（{missing}），允许缺席")
        reg = EMSolverRegistry()
        getattr(module, fn_name)(reg)
        assert _registry_keys(reg) == set(expected)


class TestIdempotentRegistration:
    """断言③：幂等回归钉（slice3 盲区 7：重复注册键数不得膨胀）。"""

    def test_package_reimport_does_not_inflate_global_registry(self):
        import rfauto.adapters  # noqa: F401

        reg = get_global_registry()
        n0 = len(_registry_keys(reg))
        first = importlib.import_module("rfauto.adapters")
        again = importlib.import_module("rfauto.adapters")
        assert first is again  # 模块缓存：二次导入不重执行注册体
        assert len(_registry_keys(reg)) == n0

    def test_repeated_register_calls_do_not_inflate_global_registry(self):
        """重复执行 __init__ 同款显式注册调用 + 各模块注册函数，第二遍起
        全局键集逐字节不变（register 语义 = 同键覆盖；首遍允许显式通道
        首次入全局，膨胀判定看第二遍增量）。"""
        import rfauto.adapters  # noqa: F401

        reg = get_global_registry()

        def _run_all_register_fns_once() -> None:
            for table in (REGISTRY_AUTO, REGISTRY_EXPLICIT):
                for module_name, (fn_name, _expected) in table.items():
                    module, _missing = _import_adapter_module(module_name)
                    if module is None:
                        continue  # 缺依赖环境：该通道整体缺席，由断言①口径豁免
                    fn = getattr(module, fn_name, None)
                    assert fn is not None, f"{module_name} 缺注册函数 {fn_name}"
                    fn()

        _run_all_register_fns_once()
        after_first = _registry_keys(reg)
        _run_all_register_fns_once()
        assert _registry_keys(reg) == after_first


class TestEnumCoverage:
    """EMSolverType 每个值必须被恰好一个通道声明，或显式归属
    SimulatorAdapter 家族（hfss/fake）——枚举扩值必须同步注册面决策。"""

    def test_every_emsolver_type_is_claimed_by_exactly_one_channel(self):
        claimed: dict[str, list[str]] = {}
        for module_name, (_fn, keys) in REGISTRY_AUTO.items():
            for key in keys:
                claimed.setdefault(key, []).append(f"auto:{module_name}")
        for module_name, (_fn, keys) in REGISTRY_EXPLICIT.items():
            for key in keys:
                claimed.setdefault(key, []).append(f"explicit:{module_name}")
        enum_values = {t.value for t in EMSolverType}
        simulator_family = {"hfss", "fake"}
        unclaimed = enum_values - set(claimed)
        assert unclaimed == simulator_family, (
            f"EMSolverType 新增值 {sorted(unclaimed - simulator_family)} 未在 "
            "REGISTRY_AUTO/REGISTRY_EXPLICIT 登记注册通道——先做注册面决策"
        )
        for key, owners in claimed.items():
            assert len(owners) == 1, f"注册键 {key!r} 被多处声明: {owners}"


class TestModuleInventory:
    """断言④：文件系统全量枚举对照三张清单 + import 体检。"""

    def test_inventory_matches_registration_plan(self):
        # ge8c 起含子包（gpl/ 等）：rglob 相对 posix 路径为模块键（__init__ 排除）
        discovered = {
            q.relative_to(ADAPTERS_DIR).with_suffix("").as_posix()
            for q in ADAPTERS_DIR.rglob("*.py") if q.stem != "__init__"
        }
        # 存量子包层豁免（oe_templates=工具·模板层/fab_export=LC-5 面/
        # sv=可选引擎适配——历史上按目录约定不在注册面清单；gpl/ 不豁免：
        # 其 pypo/scuff 注册键泄入全局表必须显式登记，八百一十九终门实证）
        _SUBPKG_EXEMPT = ("oe_templates/", "fab_export/", "sv/")
        discovered -= {d for d in discovered if d.startswith(_SUBPKG_EXEMPT)}
        planned = _all_planned_modules()
        assert discovered == planned, (
            f"adapters/ 出现未登记模块。仅清单有: {sorted(planned - discovered)}；"
            f"仅目录有: {sorted(discovered - planned)}。新增 adapter 模块必须"
            "先做注册面决策（自动注册/显式注册/非注册面）并同步 "
            "adapters/__init__.py docstring 与本清单"
        )

    def test_all_modules_importable_or_expected_missing(self):
        expected_missing: dict[str, str] = {}
        imported = 0
        for module_name in sorted(_all_planned_modules()):
            module, missing = _import_adapter_module(module_name)
            if module is None:
                expected_missing[module_name] = missing
            else:
                imported += 1
        unattributed = [
            m for m, dep in expected_missing.items()
            if not dep or str(dep).startswith("rfauto")
        ]
        assert not unattributed, f"缺席模块缺外部依赖归因: {unattributed}"
        assert imported + len(expected_missing) == len(_all_planned_modules())
        if expected_missing:  # 缺依赖环境下如实记账（本机 venv 应零缺席）
            print("expected-missing（缺外部可选依赖，允许缺席）:")
            for m, dep in sorted(expected_missing.items()):
                print(f"  {m}: {dep}")


class TestNonRegistryFamily:
    """docstring 承诺三的结构反面：这些适配器类不在 EMSolverAdapter 契约内。"""

    @pytest.mark.parametrize("module_name", sorted(NOT_EMSOLVER_CLASSES))
    def test_adapter_class_is_not_emsolver_contract(self, module_name: str):
        cls_name = NOT_EMSOLVER_CLASSES[module_name]
        module, missing = _import_adapter_module(module_name)
        if module is None:
            pytest.skip(f"缺外部可选依赖（{missing}），允许缺席")
        cls = getattr(module, cls_name, None)
        assert cls is not None, f"{module_name} 缺类 {cls_name}"
        assert not issubclass(cls, EMSolverAdapter), (
            f"{cls_name} 被声明为非注册表面（docstring 承诺三），"
            "却实现了 EMSolverAdapter 契约——通道归属冲突，先改 docstring/清单"
        )


class TestGlobalRegistryLeakHygiene:
    """序敏感回归（2026-10-01 月终门 13 红 B 组）：本文件先跑时裸调注册
    函数曾把 q3d 泄入全局表，打红 test_hfss_capabilities::
    test_q3d_still_undeclared 与 test_solver_capabilities 的「未注册探针=
    Q3D」有意契约——还原 fixture（_restore_global_registry）落地后，本文件
    全部用例（含上方裸调 fn() 的幂等用例）跑完，全局表不得残留显式通道键。
    本类须保持文件内最后定义：删 fixture 或在其前新增裸调用例即在此红。"""

    def test_explicit_channel_keys_not_left_in_global_registry(self):
        reg = get_global_registry()
        # 封闭化前置（全量门实证 2026-10-01）：字母序更早的他文件若把显式
        # 通道键泄入全局表，本测试断言的是「本文件净贡献」而非历史遗留——
        # 先清显式键再断言（fixture 的快照还原仍保证本文件对外零泄漏）。
        for _module_name, keys in REGISTRY_EXPLICIT.values():
            for key in keys:
                reg._solvers.pop(key, None)
        have = _registry_keys(reg)
        for _module_name, keys in REGISTRY_EXPLICIT.values():
            for key in keys:
                assert key not in have, (
                    f"显式通道键 {key!r} 泄入全局注册表——"
                    "_restore_global_registry 快照还原 fixture 失效或被删"
                )
        # 探针语义端到端：Q3D 能力声明保持 KeyError 原语义（未声明不静默）
        with pytest.raises(KeyError):
            solver_capabilities_for(EMSolverType.Q3D)
