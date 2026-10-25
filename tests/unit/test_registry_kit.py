"""RegistryKit 单元测试（R1 T6 统一脚手架试点）。

覆盖四块：
1. Kit 本体七件套：register 三形态（显式名键/裸装饰器/直调）、重名策略
   两档、缺名 KeyError 文案与 default 回退、keys 字典序、create、
   unregister、snapshot、contains/len/iter；
2. 试点面行为保真钉：LintCheckRegistry（重名报错+register 即刻验重时序）、
   SurrogateRegistry（装饰器/直调双形态+重名静默覆盖+缺名历史文案）、
   EngineRegistry（类键裸装饰器+create+available）；扩面二批（W10-S3）：
   TopologyProposerRegistry（类键裸装饰器+缺名历史文案+注销回路）、
   SystemOneRegistry（同名覆盖=换实现+缺名 ProviderUnavailableError）、
   RuntimeRegistry（builtin 内置+缺名历史文案+插件补载后仍报缺）；
3. 键校验：非字符串键/空键/缺键属性显式 TypeError；
4. 扩面三批保真钉（W15-S3）：TemplateSpecRegistry（dup_fmt 历史重名
   文案+describe 保序）、瀑布三段注册表（静默覆盖+缺名历史文案+独立
   命名空间）、FabPortRegistry（二级 kind/name 组合 Kit：缺名 None 回退
   +create 缺名 KeyError+items 登记序迭代）；
5. 扩面四批（aurora_h W2-S3，R1_arch_audit_v3 §5）：Kit 本体下沉
   core/registry_kit.py（infra re-export 同一对象）+键泛化
   （allow_non_str_keys）+登记序 keys（ordered）+{keys_list} 缺名占位符
   新能力自测；BudgetRegistry/EMSolverRegistry/CalculatorRegistry 三面
   历史语义逐字节保真钉（重名/缺名文案、静默覆盖、登记序、恒真
   __bool__、_solvers/_specs 历史存储名缝）。
"""

from __future__ import annotations

import pytest

from rfauto.infra.registry_kit import RegistryKit
from rfauto.optimization.surrogate.base import SurrogateRegistry
from rfauto.service.design_lint_service import LINT_REGISTRY, LintCheckRegistry
from rfauto.service.hierarchical_scheduler import (
    EngineRegistry,
    ParamSearchEngine,
)

# ── 1. Kit 本体 ──────────────────────────────────────────────────────────────


class TestRegisterForms:
    def test_named_decorator_form(self):
        reg: RegistryKit[object] = RegistryKit(label="条目")

        @reg.register("alpha")
        def fn() -> int:
            return 1

        assert reg.get("alpha") is fn
        assert reg.keys() == ["alpha"]

    def test_bare_decorator_form_key_from_name_attr(self):
        reg: RegistryKit[type] = RegistryKit(label="实现")

        @reg.register
        class Impl:
            name = "impl_key"

        assert reg.get("impl_key") is Impl
        assert reg.keys() == ["impl_key"]

    def test_bare_decorator_form_falls_back_to_dunder_name(self):
        reg: RegistryKit[object] = RegistryKit(label="函数")

        @reg.register
        def plain_fn() -> None:
            return None

        assert reg.get("plain_fn") is plain_fn

    def test_direct_call_form_returns_obj(self):
        reg: RegistryKit[object] = RegistryKit(label="条目")
        obj = object()
        returned = reg.register("key", obj)
        assert returned is obj
        assert reg.get("key") is obj


class TestDuplicatePolicy:
    def test_duplicate_raises_valueerror(self):
        reg: RegistryKit[object] = RegistryKit(label="条目")
        reg.register("x", object())
        with pytest.raises(ValueError, match="条目重复注册: x"):
            reg.register("x", object())

    def test_named_decorator_duplicate_eager_at_factory(self):
        """显式名键形态：重名在装饰器工厂创建时即报（不等函数应用）。"""
        reg: RegistryKit[object] = RegistryKit(label="条目")
        reg.register("x", object())
        with pytest.raises(ValueError, match="重复注册"):
            reg.register("x")  # 尚未应用函数即应报

    def test_allow_overwrite_overwrites_silently(self):
        reg: RegistryKit[object] = RegistryKit(
            label="条目", allow_overwrite=True)
        first, second = object(), object()
        reg.register("x", first)
        reg.register("x", second)
        assert reg.get("x") is second
        assert len(reg) == 1

    def test_dup_fmt_preserves_historical_message(self):
        """W15-S3 扩面：dup_fmt 让历史面重名文案逐字节保真（缺省不变）。"""
        reg: RegistryKit[object] = RegistryKit(
            label="模板 spec", dup_fmt="模板 spec 重名注册: {key}")
        reg.register("t", object())
        with pytest.raises(ValueError, match="模板 spec 重名注册: t"):
            reg.register("t", object())
        # 缺省 dup_fmt 行为与既有试点面一致（不因扩参漂移）
        default_reg: RegistryKit[object] = RegistryKit(label="条目")
        default_reg.register("x", object())
        with pytest.raises(ValueError, match="条目重复注册: x"):
            default_reg.register("x", object())


class TestLookup:
    def test_missing_key_error_message_contains_label_and_keys(self):
        reg: RegistryKit[object] = RegistryKit(label="部件")
        reg.register("b", object())
        reg.register("a", object())
        with pytest.raises(KeyError) as excinfo:
            reg.get("nope")
        msg = str(excinfo.value)
        assert "未注册的部件: nope" in msg
        assert "a, b" in msg  # 可用键字典序

    def test_missing_key_default_fallback(self):
        reg: RegistryKit[object] = RegistryKit(label="部件")
        sentinel = object()
        assert reg.get("nope", default=sentinel) is sentinel
        assert reg.get("nope", default=None) is None

    def test_keys_sorted_and_create_calls(self):
        reg: RegistryKit[object] = RegistryKit(label="工厂")
        reg.register("b", lambda *, x: x * 2)
        reg.register("a", lambda *, x: x + 1)
        assert reg.keys() == ["a", "b"]
        assert reg.create("a", x=1) == 2
        assert reg.create("b", x=3) == 6


class TestMaintenanceAndProtocols:
    def test_unregister_pops_or_nops(self):
        reg: RegistryKit[object] = RegistryKit(label="条目")
        obj = object()
        reg.register("x", obj)
        assert reg.unregister("x") is obj
        assert reg.unregister("x") is None  # 缺名 no-op
        assert "x" not in reg

    def test_snapshot_is_copy(self):
        reg: RegistryKit[object] = RegistryKit(label="条目")
        obj = object()
        reg.register("x", obj)
        snap = reg.snapshot()
        assert snap == {"x": obj}
        reg.register("y", object())
        reg.unregister("x")
        assert snap == {"x": obj}  # 快照不随本体变
        assert "y" in reg and "x" not in reg

    def test_contains_len_iter(self):
        reg: RegistryKit[object] = RegistryKit(label="条目")
        reg.register("a", object())
        reg.register("b", object())
        assert "a" in reg and "zz" not in reg
        assert len(reg) == 2
        assert list(reg) == ["a", "b"]

    def test_invalid_key_typeerror(self):
        reg: RegistryKit[object] = RegistryKit(label="条目")
        with pytest.raises(TypeError, match="注册键须为"):
            reg.register(123, object())  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="注册键须为"):
            reg.insert("", object())

    def test_bare_register_without_key_attr_typeerror(self):
        reg: RegistryKit[object] = RegistryKit(label="实现")

        class NoName:
            pass

        # 类必有 __name__；缺键路径只对普通实例触发（回退链双缺）
        with pytest.raises(TypeError, match="注册缺键"):
            reg.bare_register(NoName())


# ── 2. 试点面行为保真钉 ──────────────────────────────────────────────────────


class TestLintCheckRegistryParity:
    def test_is_registry_kit_subclass(self):
        assert isinstance(LINT_REGISTRY, RegistryKit)

    def test_register_and_names(self):
        reg = LintCheckRegistry()
        reg.register("z")(lambda payload: {})
        reg.register("a")(lambda payload: {})
        assert reg.names() == ["a", "z"]
        assert reg.is_registered("a") is True
        assert reg.is_registered("q") is False

    def test_duplicate_rejected_with_historical_message(self):
        reg = LintCheckRegistry()
        reg.register("x")(lambda payload: {})
        with pytest.raises(ValueError, match="子检查重复注册: x"):
            reg.register("x")(lambda payload: {})

    def test_run_dispatches_and_unknown_raises_valueerror(self):
        reg = LintCheckRegistry()
        reg.register("ok_fn")(lambda payload: {"status": "pass"})
        assert reg.run("ok_fn", {}) == {"status": "pass"}
        with pytest.raises(ValueError, match="未知子检查"):
            reg.run("nope", {})


class TestSurrogateRegistryParity:
    def test_is_registry_kit_subclass_with_builtin_keys(self):
        from rfauto.optimization.surrogate.base import surrogate_registry

        assert isinstance(surrogate_registry, RegistryKit)
        # 内置键经模块 import 副作用注册（#362 口径不变：reload=新空表）
        assert "nn" in surrogate_registry  # __contains__（非 .keys() 成员测试）
        assert surrogate_registry.keys() == surrogate_registry.available()

    def test_decorator_and_direct_forms_on_fresh_instance(self):
        reg = SurrogateRegistry()

        @reg.register("kind_a")
        class ModelA:
            def __init__(self, config=None):
                self.config = config

        class ModelB:
            def __init__(self, config=None):
                self.config = config

        returned = reg.register("kind_b", ModelB)
        assert returned is ModelB  # 直调形态返回原对象
        assert reg.available() == ["kind_a", "kind_b"]
        assert isinstance(reg.create("kind_a", config={"k": 1}), ModelA)

    def test_overwrite_allowed_and_missing_message_preserved(self):
        reg = SurrogateRegistry()

        @reg.register("dup")
        class M1:
            pass

        @reg.register("dup")
        class M2:
            pass

        assert reg.get("dup") is M2  # 历史语义：重名静默覆盖
        with pytest.raises(KeyError, match="未注册的代理类型"):
            reg.create("no_such_kind")


class TestEngineRegistryParity:
    def test_builtin_engines_present(self):
        assert set(EngineRegistry.available()) >= {"surrogate", "mcts"}

    def test_missing_engine_message_preserved(self):
        with pytest.raises(KeyError, match="未注册的参数搜索引擎"):
            EngineRegistry.create("no_such_engine_w8s3")

    def test_register_create_unregister_roundtrip(self):
        class DummyEngine(ParamSearchEngine):
            name = "w8s3_dummy_engine"

            def search(self, *, bounds, objectives, evaluate_fn,
                       budget, seed):
                return {"ok": True, "engine": self.name}

        try:
            assert EngineRegistry.register(DummyEngine) is DummyEngine
            engine = EngineRegistry.create("w8s3_dummy_engine")
            assert isinstance(engine, DummyEngine)
            assert "w8s3_dummy_engine" in EngineRegistry.available()
        finally:
            EngineRegistry._kit.unregister("w8s3_dummy_engine")
        assert "w8s3_dummy_engine" not in EngineRegistry.available()


# ── 3. 扩面二批保真钉（W10-S3） ───────────────────────────────────────────────


class TestTopologyProposerRegistryParity:
    def test_builtin_proposers_present(self):
        from rfauto.service.topology_service import TopologyProposerRegistry

        assert set(TopologyProposerRegistry.available()) >= \
            {"rule_based", "llm"}

    def test_missing_proposer_message_preserved(self):
        from rfauto.service.topology_service import TopologyProposerRegistry

        with pytest.raises(KeyError, match="未注册的提议器"):
            TopologyProposerRegistry.create("no_such_proposer_w10s3")

    def test_register_create_unregister_roundtrip(self):
        from rfauto.service.topology_service import (
            TopologyProposer,
            TopologyProposerRegistry,
        )

        class DummyProposer(TopologyProposer):
            name = "w10s3_dummy_proposer"

            def propose(self, spec):
                raise NotImplementedError

        try:
            assert TopologyProposerRegistry.register(DummyProposer) \
                is DummyProposer
            proposer = TopologyProposerRegistry.create(
                "w10s3_dummy_proposer")
            assert isinstance(proposer, DummyProposer)
            assert "w10s3_dummy_proposer" in \
                TopologyProposerRegistry.available()
        finally:
            TopologyProposerRegistry._kit.unregister("w10s3_dummy_proposer")
        assert "w10s3_dummy_proposer" not in \
            TopologyProposerRegistry.available()


class TestSystemOneRegistryParity:
    def test_fresh_instance_overwrite_and_lookup(self):
        from rfauto.service.systemone_service import SystemOneRegistry

        reg = SystemOneRegistry()
        reg.register("w10s3_p", lambda: "A")
        reg.register("w10s3_p", lambda: "B")  # 历史语义：同名覆盖=换实现
        assert reg.create("w10s3_p") == "B"
        assert reg.list_providers() == ["w10s3_p"]
        assert reg.is_registered("w10s3_p") is True
        assert reg.is_registered("w10s3_missing") is False

    def test_missing_provider_error_type_and_message_preserved(self):
        from rfauto.service.systemone_service import (
            ProviderUnavailableError,
            SystemOneRegistry,
        )

        reg = SystemOneRegistry()
        with pytest.raises(ProviderUnavailableError,
                           match="未注册的 System One provider"):
            reg.create("w10s3_missing")

    def test_global_registry_builtins_present(self):
        from rfauto.service.systemone_service import get_systemone_registry

        assert set(get_systemone_registry().list_providers()) >= {
            "deterministic"}


class TestRuntimeRegistryParity:
    def test_builtin_runtime_present(self):
        from rfauto.service.agent_runtime import RuntimeRegistry

        assert "builtin" in RuntimeRegistry.available()

    def test_missing_runtime_message_preserved(self):
        from rfauto.service.agent_runtime import RuntimeRegistry

        with pytest.raises(KeyError, match="未注册的运行时"):
            RuntimeRegistry.create("_no_such_runtime_w10s3")

    def test_register_create_unregister_roundtrip(self):
        from rfauto.service.agent_runtime import (
            AgentRuntime,
            RuntimeRegistry,
        )

        class DummyRuntime(AgentRuntime):
            name = "_w10s3_dummy_runtime"

            def submit(self, request, executor):
                raise NotImplementedError

        try:
            assert RuntimeRegistry.register(DummyRuntime) is DummyRuntime
            runtime = RuntimeRegistry.create("_w10s3_dummy_runtime")
            assert isinstance(runtime, DummyRuntime)
            assert "_w10s3_dummy_runtime" in RuntimeRegistry.available()
        finally:
            RuntimeRegistry._kit.unregister("_w10s3_dummy_runtime")
        assert "_w10s3_dummy_runtime" not in RuntimeRegistry.available()


# ── 4. 扩面三批保真钉（W15-S3） ──────────────────────────────────────────────


class TestTemplateSpecRegistryParity:
    def test_is_registry_kit_subclass_with_builtin_specs(self):
        import rfauto.models.template_specs  # noqa: F401  # 注册副作用
        from rfauto.models.template_spec import TEMPLATE_SPECS

        assert isinstance(TEMPLATE_SPECS, RegistryKit)
        assert len(TEMPLATE_SPECS) > 0  # 声明面 import 即完成注册（#362 口径不变）

    def test_duplicate_rejected_with_historical_message(self):
        from rfauto.models.template_spec import (
            TemplateSpec,
            TemplateSpecRegistry,
        )

        reg = TemplateSpecRegistry()
        spec = TemplateSpec(name="dup_spec", meta={}, synthesizer=lambda: None)
        reg.register(spec)
        with pytest.raises(ValueError, match="模板 spec 重名注册: dup_spec"):
            reg.register(spec)

    def test_missing_message_and_describe_preserved(self):
        from rfauto.models.template_spec import (
            TemplateSpec,
            TemplateSpecRegistry,
        )

        reg = TemplateSpecRegistry()
        with pytest.raises(KeyError, match="未注册的模板 spec: nope"):
            reg.get("nope")
        reg.register(TemplateSpec(
            name="s1", meta={"k": 1}, synthesizer=lambda: None))
        assert reg.describe() == [{
            "name": "s1",
            "components": {
                "render_script": False,
                "synthesizer": True,
                "fake_model": False,
                "hfss_plugin": None,
            },
            "meta_keys": ["k"],
            "physics_roles": {},
        }]


class TestWaterfallRegistryParity:
    def test_three_registries_have_independent_namespaces(self):
        from rfauto.service.agent_safety import (
            GuardRegistry,
            PostHookRegistry,
            PrePolicyRegistry,
        )

        assert GuardRegistry._kit is not PrePolicyRegistry._kit
        assert PrePolicyRegistry._kit is not PostHookRegistry._kit
        assert "sandbox_whitelist" in GuardRegistry.available()
        assert "systemone_prescreen" in PrePolicyRegistry.available()
        assert "deny_by_default" not in PostHookRegistry.available()

    def test_missing_message_and_silent_overwrite_preserved(self):
        from rfauto.service.agent_safety import GuardRegistry, ToolGuard

        with pytest.raises(
                KeyError, match="未注册的瀑布守卫: no_such_w15s3"):
            GuardRegistry.create("no_such_w15s3")

        class _Tmp(ToolGuard):
            name = "w15s3_dup_guard"

            def check(self, event):
                raise NotImplementedError

        try:
            GuardRegistry.register(_Tmp)
            GuardRegistry.register(_Tmp)  # 重名静默覆盖=历史语义
            assert isinstance(GuardRegistry.create("w15s3_dup_guard"), _Tmp)
        finally:
            GuardRegistry._kit.unregister("w15s3_dup_guard")
        assert "w15s3_dup_guard" not in GuardRegistry.available()


class TestFabPortRegistryParity:
    def test_fresh_registry_lookup_and_create_semantics(self):
        from rfauto.adapters.fab_export.base import FabPortRegistry

        reg = FabPortRegistry()
        assert reg.lookup("k", "n") is None  # 缺 kind/缺 name 都回退 None
        with pytest.raises(
                KeyError, match="plugin not registered: kind=k name=n"):
            reg.create("k", "n")

        class _P:
            name = "n"

        reg.register("k", "n", _P)
        assert reg.lookup("k", "n") is _P
        assert isinstance(reg.create("k", "n"), _P)
        assert reg.names("k") == ["n"]
        assert reg.names("absent") == []

    def test_silent_overwrite_and_items_insertion_order(self):
        from rfauto.adapters.fab_export.base import FabPortRegistry

        reg = FabPortRegistry()
        reg.register("k2", "b", lambda: "b1")
        reg.register("k1", "a", lambda: "a1")
        reg.register("k2", "b", lambda: "b2")  # 重名静默覆盖=历史语义
        assert reg.create("k2", "b") == "b2"
        assert [(i.kind, i.name) for i in reg.items()] == [
            ("k2", "b"), ("k1", "a")]  # kind 登记序×name 登记序
        assert reg.names("k2") == ["b"]  # names() 仍字典序


# ── 5. 扩面四批（aurora_h W2-S3）：Kit 下沉 core+键泛化/ordered/keys_list ────


class TestKitCoreHomeAndKeyGeneralization:
    """Kit 本体下沉 + W2-S3 三个基类新能力（键泛化/登记序/keys_list）。"""

    def test_infra_entry_is_reexport_of_core_body(self):
        """infra/registry_kit 兼容入口与 core 本体是同一类对象（非拷贝）。"""
        import rfauto.core.registry_kit as core_kit
        import rfauto.infra.registry_kit as infra_kit

        assert infra_kit.RegistryKit is core_kit.RegistryKit

    def test_keys_list_placeholder_renders_list_repr(self):
        """{keys_list} 占位符=整列表 repr 形态（Budget/Calculator 历史缺名
        文案是 {sorted(...)} 的 f-string，str(list) 带方括号引号）。"""
        reg: RegistryKit[object] = RegistryKit(
            label="条目", missing_fmt="缺: {key}（可用: {keys_list}）")
        reg.register("b", object())
        reg.register("a", object())
        with pytest.raises(KeyError) as excinfo:
            reg.get("nope")
        assert excinfo.value.args[0] == "缺: nope（可用: ['a', 'b']）"

    def test_default_template_ignores_extra_placeholder(self):
        """缺省模板（只引用 {keys}）不受 format 额外 kwargs 影响——既有
        试点面缺名文案逐字节不变。"""
        reg: RegistryKit[object] = RegistryKit(label="部件")
        reg.register("a", object())
        with pytest.raises(KeyError, match="未注册的部件: nope"):
            reg.get("nope")
        with pytest.raises(KeyError) as excinfo:
            reg.get("nope")
        assert "['a']" not in str(excinfo.value)  # 列表 repr 形态未渗入缺省

    def test_allow_non_str_keys_accepts_any_hashable(self):
        """allow_non_str_keys=True：直调/insert 接受任意 hashable 键
        （EMSolver 枚举∪自定义字符串键面）；False 维持 str 键 TypeError。"""
        class _Key:
            pass  # 故意非 str 非 Enum：真正异构键型

        strict: RegistryKit[object] = RegistryKit(label="条目")
        with pytest.raises(TypeError, match="注册键须为字符串"):
            strict.register(_Key(), object())
        loose: RegistryKit[object] = RegistryKit(
            label="条目", allow_non_str_keys=True)
        obj = object()
        key = _Key()  # 同一实例作键（get 按同一对象查）
        loose.register(key, obj)
        assert loose.get(key) is obj
        loose.insert(("t", 1), object())  # tuple 键亦可
        assert len(loose) == 2

    def test_ordered_keys_preserve_insertion_order(self):
        """ordered=True：keys()/迭代=登记序（EMSolver list_available 的
        dict 序历史语义；缺省 False=字典序既有面不变）。"""
        ordered: RegistryKit[object] = RegistryKit(
            label="条目", allow_non_str_keys=True, ordered=True)
        for key in ("z", "a", "m", 3):
            ordered.register(key, object())
        assert ordered.keys() == ["z", "a", "m", 3]
        assert list(ordered) == ["z", "a", "m", 3]
        sorted_reg: RegistryKit[object] = RegistryKit(label="条目")
        for key in ("z", "a", "m"):
            sorted_reg.register(key, object())
        assert sorted_reg.keys() == ["a", "m", "z"]  # 缺省字典序不变

    def test_non_str_dup_message_join_robust(self):
        """allow_overwrite=False×非 str 键的重名文案：{keys} 逗号连接对
        非 str 键 str() 化兜底（不因 join TypeError 炸道）。"""
        reg: RegistryKit[object] = RegistryKit(
            label="条目", allow_non_str_keys=True)
        reg.register(7, object())
        with pytest.raises(ValueError, match="条目重复注册: 7"):
            reg.register(7, object())


class TestBudgetRegistryParity:
    """BudgetRegistry（core/error_budget.py）W2-S3 迁移保真钉。"""

    def test_is_registry_kit_subclass(self):
        from rfauto.core.error_budget import BUDGET_REGISTRY

        assert isinstance(BUDGET_REGISTRY, RegistryKit)

    def test_register_lookup_list_and_kwargs_create(self):
        from rfauto.core.error_budget import BudgetItem, BudgetRegistry

        class _Item(BudgetItem):
            name = "budget.w2s3_par"

            def calc(self, f, context=None):
                import numpy as np

                return np.full(np.asarray(f).shape, 1.0)

        reg = BudgetRegistry()
        assert reg.register(_Item) is _Item  # 返回原类（装饰器用法兼容）
        assert reg.is_registered("budget.w2s3_par") is True
        assert reg.lookup("budget.w2s3_par") is _Item
        assert reg.lookup("budget.absent") is None  # 不抛错
        assert reg.list_names() == ["budget.w2s3_par"]  # 字典序
        inst = reg.create("budget.w2s3_par")  # 缺省构造
        assert inst.name == "budget.w2s3_par"
        assert reg.create("budget.w2s3_par",
                          description="kw 透传").description == "kw 透传"

    def test_duplicate_and_missing_messages_byte_identical(self):
        from rfauto.core.error_budget import BudgetItem, BudgetRegistry

        class _A(BudgetItem):
            name = "budget.alpha"

            def calc(self, f, context=None):
                raise NotImplementedError

        class _B(BudgetItem):
            name = "budget.beta"

            def calc(self, f, context=None):
                raise NotImplementedError

        reg = BudgetRegistry()
        reg.register(_A)
        reg.register(_B)
        with pytest.raises(ValueError) as dup:
            reg.register(_A)
        assert str(dup.value) == "误差源条目重名注册: budget.alpha"
        with pytest.raises(KeyError) as miss:
            reg.create("budget.nope")
        assert miss.value.args[0] == (
            "未注册的误差源条目: budget.nope"
            "（可用: ['budget.alpha', 'budget.beta']）")  # 列表 repr 形态

    def test_empty_class_name_rejected(self):
        from rfauto.core.error_budget import BudgetItem, BudgetRegistry

        class _NoName(BudgetItem):
            name = ""

            def calc(self, f, context=None):
                raise NotImplementedError

        reg = BudgetRegistry()
        with pytest.raises(ValueError) as ei:
            reg.register(_NoName)
        assert str(ei.value) == "注册条目类必须有类级 name"


class TestEMSolverRegistryParity:
    """EMSolverRegistry（adapters/em_solver_base.py）W2-S3 迁移保真钉。"""

    def test_is_registry_kit_subclass_with_builtin_keys(self):
        from rfauto.adapters.em_solver_base import (
            EMSolverRegistry,
            get_global_registry,
        )

        assert isinstance(get_global_registry(), EMSolverRegistry)
        have = {str(getattr(k, "value", k))
                for k in get_global_registry().list_available()}
        assert "openems" in have  # 内置键 import 即注册（fake 由测试装订）

    def test_silent_overwrite_and_insertion_order(self):
        from rfauto.adapters.em_solver_base import EMSolverRegistry, EMSolverType

        reg = EMSolverRegistry()
        reg.register(EMSolverType.FAKE, dict)  # type: ignore[arg-type]
        reg.register(EMSolverType.FAKE, list)  # 重名静默覆盖=历史语义
        reg.register("zzz_str_key", dict)  # 自定义字符串键（entry-point 口径）
        reg.register(EMSolverType.MEEP, dict)  # type: ignore[arg-type]
        assert reg.list_available() == [
            EMSolverType.FAKE, "zzz_str_key", EMSolverType.MEEP]  # 登记序
        assert reg.get(EMSolverType.FAKE) is list  # 覆盖生效

    def test_missing_valueerror_message_byte_identical(self):
        from rfauto.adapters.em_solver_base import EMSolverRegistry, EMSolverType

        reg = EMSolverRegistry()
        with pytest.raises(ValueError) as enum_miss:
            reg.create(EMSolverType.HFSS, None)
        assert str(enum_miss.value) == "未注册的求解器: hfss"  # 取 .value
        with pytest.raises(ValueError) as str_miss:
            reg.create("no_such_str", None)
        assert str(str_miss.value) == "未注册的求解器: no_such_str"

    def test_empty_registry_is_truthy(self):
        """恒真钉：``registry or get_global_registry()`` 形态注册函数
        （q3d/icepak/gpl/elmer 等）依赖空表实例为真——Kit 通用 __len__
        真值会把空实例判 falsy 静默偷写全局表。"""
        from rfauto.adapters.em_solver_base import EMSolverRegistry

        assert bool(EMSolverRegistry()) is True

    def test_solvers_storage_seam(self):
        """_solvers 历史存储名缝：快照/清空/还原/赋值形态逐字节兼容
        （test_adapters_registry_completeness autouse fixture 与
        test_em_solver_discovery registry_guard 既有口径）。"""
        from rfauto.adapters.em_solver_base import EMSolverRegistry

        reg = EMSolverRegistry()
        reg.register("k", dict)
        snap = dict(reg._solvers)
        reg._solvers.clear()
        assert len(reg) == 0
        reg._solvers.update(snap)
        assert reg.is_registered("k")
        reg._solvers = {"only": dict}  # 赋值还原形态
        assert reg.lookup("only") is dict and len(reg) == 1


class TestCalculatorRegistryParity:
    """CalculatorRegistry（core/calc_families/registry.py）W2-S3 迁移保真钉。"""

    def test_is_registry_kit_subclass_with_builtin_keys(self):
        from rfauto.core.calc_families.registry import CALCULATOR_REGISTRY

        assert isinstance(CALCULATOR_REGISTRY, RegistryKit)
        assert len(CALCULATOR_REGISTRY.names()) > 300  # 306+ 键面在册

    def test_duplicate_and_missing_messages_byte_identical(self):
        from rfauto.core.calc_families.registry import (
            CalculatorRegistry,
            CalculatorSpec,
        )

        reg = CalculatorRegistry()
        spec = CalculatorSpec(
            name="dup_calc", description="d",
            func=lambda **kwargs: {}, params=(), required=())
        reg.register(spec)
        with pytest.raises(ValueError) as dup:
            reg.register(spec)
        assert str(dup.value) == "计算器重名注册: dup_calc"
        with pytest.raises(KeyError) as miss:
            reg.get("nope")
        assert miss.value.args[0] == (
            "未注册的计算器: nope（可用: ['dup_calc']）")  # 列表 repr 形态

    def test_get_single_arg_signature_pin(self):
        """历史 get(name) 单参签名钉：多余实参维持 TypeError（不升级为
        Kit 的 default 回退形态）。"""
        from rfauto.core.calc_families.registry import CALCULATOR_REGISTRY

        with pytest.raises(TypeError):
            CALCULATOR_REGISTRY.get("microstrip_analysis", None)  # type: ignore[call-arg]

    def test_names_describe_experimental_filtering(self):
        from rfauto.core.calc_families.registry import (
            CALCULATOR_REGISTRY,
            CalculatorRegistry,
            CalculatorSpec,
        )

        reg = CalculatorRegistry()
        plain = CalculatorSpec(
            name="w2s3_plain", description="d",
            func=lambda **kwargs: {}, params=(), required=())
        exp = CalculatorSpec(
            name="w2s3_exp", description="d",
            func=lambda **kwargs: {}, params=(), required=(),
            experimental=True)
        reg.register(plain)
        reg.register(exp)
        assert reg.names() == ["w2s3_plain"]  # 实验键默认排除
        assert reg.names(include_experimental=True) == [
            "w2s3_exp", "w2s3_plain"]  # 全键字典序
        assert reg.is_experimental("w2s3_exp") is True
        assert reg.is_experimental("w2s3_plain") is False
        with pytest.raises(KeyError):
            reg.is_experimental("absent_calc")  # 与 get 同语义
        rows = {r["name"]: r for r in reg.describe(include_experimental=True)}
        assert rows["w2s3_exp"]["experimental"] is True
        assert rows["w2s3_plain"]["group"] == "其他"  # 表外键落缺省组
        # 全局表消费面同链（describe 随表解析 group 单源）
        assert all(
            isinstance(c["group"], str) and c["group"]
            for c in CALCULATOR_REGISTRY.describe())
