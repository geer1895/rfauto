"""RegistryKit：name→object 注册表轻量基类（R1 T6 统一脚手架试点）。

背景（内部证据目录 §面5/T6）：全仓 35+ 注册面、
20 个 Registry 类里 ``_registry dict + register()/get()/keys()`` 同构
手写 11 处。本模块把该同构收敛为一个百行级 Generic 基类——注册表
新增面直接继承/组合本 Kit，不再各写一遍 dict+装饰器样板。

**本体位置（架构批 W2-S3 下沉）**：R1_arch_audit_v3 §5 扩面三件中
Calculator（core/calc_families/registry.py）与 Budget（core/error_budget.py）
两注册表住 core 层——分层契约（.importlinter layers，"core is a stable
dependency-free leaf"）禁止 core 反向 import infra；Kit 为零第三方依赖的
纯 stdlib 泛型容器，故本体自 infra/registry_kit.py 下沉至本模块（分层
合法的最低层），infra 侧保留 re-export 兼容入口（同一类对象非拷贝，
既有 ``from rfauto.infra.registry_kit import RegistryKit`` 的 13 处消费面
导入路径逐字节不变）。新代码一律从本模块导入。

三种注册形态（同一方法收口）::

    reg = RegistryKit(label="子检查")

    @reg.register("name")            # 形态①：显式名键装饰器
    def fn(...): ...

    @reg.register                    # 形态②：裸装饰器（键取 obj.name，
    class Impl:                      # 缺失回退 obj.__name__）
        name = "impl"

    reg.register("name", obj)        # 形态③：直调登记（返回 obj 原样）

读取/消费::

    reg.get("name")                  # 缺名 KeyError（文案带 label+可用键）
    reg.get("name", default=None)    # 缺名回退缺省值
    reg.create("name", **kwargs)     # 取出并调用（工厂/类注册面实例化）
    reg.keys()                       # 已注册键（缺省字典序；ordered=True
                                     # =登记序，枚举键面用）

设计约束：
- **行为保真优先**：重名策略（报错 vs 静默覆盖）、缺名文案经构造参数
  逐项保真——试点迁移面（LintCheckRegistry/SurrogateRegistry/
  EngineRegistry）对外可观测行为与迁移前逐字节一致；
- **注册序敏感面免责（#362）**：本 Kit 是纯数据容器，不做任何 import
  副作用/entry-point 发现——注册仍由各模块 import 期显式执行，reload
  语义与迁移前相同（新模块命名空间=新 Kit 实例=空表）；
- 暂不声明 ``__all__``：public_api 金快照口径下无 ``__all__`` 记私有，
  并行合流期不动共享金快照（是否转正公开面由合流席位统一裁定）。

键泛化扩展（架构批 W2-S3，R1 扩面三件）：
- ``allow_non_str_keys=True``：键面放开为任意 hashable（EMSolverRegistry
  的 ``dict[EMSolverType, cls]`` 枚举键∪自定义 EDA 字符串键既有口径）；
  缺省 False 保持 str 键强校验（非字符串键/空键 TypeError）逐字节不变；
- ``ordered=True``：``keys()`` 返回**登记序**（EMSolver list_available 的
  dict 序历史语义；枚举键∪字符串键混排不可互比排序，sorted 会 TypeError）；
  缺省 False 保持字典序（全部既有面）；
- ``{keys_list}`` 缺名文案占位符：get() 的 format 额外注入 ``keys_list=``
  整键列表对象——Budget/Calculator 历史缺名文案是 ``{sorted(...)}`` 的
  **列表 repr 形态**（带方括号引号），与既有 ``{keys}`` 逗号连接形态并存，
  未引用该占位符的模板不受影响（str.format 忽略多余 kwargs）。
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

V = TypeVar("V")

_MISSING = object()
"""get() 缺省哨兵：区分"调用方显式传 default=None"与"未传 default"。"""


class RegistryKit(Generic[V]):
    """轻量 name→object 注册表（register/get/keys/create 七件套）。

    参数：
        label: 条目称谓（进错误文案，如 "子检查"/"代理类型"）；
        key_attr: 裸装饰器形态取键的属性名（缺省 "name"，类键注册面惯例）；
        allow_overwrite: 重名注册策略——False（缺省）= ValueError 视为
            编程错误（LintCheck/CALCULATOR 惯例）；True = 静默覆盖
            （EMSolver/surrogate 历史语义，迁移保真用）；
        missing_fmt: 缺名 KeyError 文案模板（可用占位符 {label}/{key}/
            {keys}/{keys_list}）——迁移面历史文案经此保真；
        dup_fmt: 重名 ValueError 文案模板（占位符同上；缺省
            "{label}重复注册: {key}"）——扩面三批（W15-S3）新增：
            TemplateSpec/Budget 等历史面文案经此保真，缺省不改动
            试点面任何既有报错；
        allow_non_str_keys: 键面放开为任意 hashable（缺省 False=str 键
            强校验）——W2-S3 新增，EMSolverRegistry 枚举键∪自定义字符串
            键历史口径的迁移保真用；
        ordered: keys() 口径——False（缺省）=字典序（全部既有面）；
            True=登记序（dict 插入序）——W2-S3 新增，EMSolver
            list_available 历史 dict 序保真用。
    """

    def __init__(
        self,
        *,
        label: str = "条目",
        key_attr: str = "name",
        allow_overwrite: bool = False,
        missing_fmt: str = "未注册的{label}: {key}（可用: {keys}）",
        dup_fmt: str = "{label}重复注册: {key}",
        allow_non_str_keys: bool = False,
        ordered: bool = False,
    ) -> None:
        self._items: dict[Any, V] = {}
        self._label = label
        self._key_attr = key_attr
        self._allow_overwrite = allow_overwrite
        self._missing_fmt = missing_fmt
        self._dup_fmt = dup_fmt
        self._allow_non_str_keys = allow_non_str_keys
        self._ordered = ordered

    # ── 注册（三形态同一入口） ────────────────────────────────────────────

    def register(self, key_or_obj: str | V, obj: V | None = None) -> Any:
        """注册（形态见模块 docstring）。

        显式名键形态（key 为 str）在装饰器工厂创建时**即刻验重**——
        迁移面 LintCheckRegistry 的原时序（register("名") 即报，不等
        函数应用）；键被占用后在 deco 应用时二次验重防窗口期抢占。
        直调形态（obj 给定）在 allow_non_str_keys=True 时接受任意
        hashable 键（EMSolver 枚举键面），False 时维持非字符串键
        TypeError 历史校验。
        """
        if obj is None and isinstance(key_or_obj, str):
            key = key_or_obj
            self._ensure_free(key)

            def deco(fn: V) -> V:
                self._ensure_free(key)
                self._items[key] = fn
                return fn

            return deco
        if obj is None:  # 形态②：裸装饰器（键取属性）
            return self.bare_register(key_or_obj)
        if not self._allow_non_str_keys and not isinstance(key_or_obj, str):
            # 形态③：直调登记（非 str 键且未放开键面 → 历史校验）
            raise TypeError(
                f"{self._label}注册键须为字符串，得 "
                f"{type(key_or_obj).__name__}（裸装饰器请直接 "
                f"reg.register(obj)）")
        self.insert(key_or_obj, obj)
        return obj

    def bare_register(self, obj: V) -> V:
        """裸装饰器登记：键取 ``getattr(obj, key_attr)``，缺失回退
        ``obj.__name__``，两者皆无 → TypeError（原手写面此处置为
        AttributeError 裸奔，此处显式化）。返回 obj 原样（装饰器兼容）。
        """
        key = getattr(obj, self._key_attr, None)
        if not isinstance(key, str) or not key:
            key = getattr(obj, "__name__", None)
        if not isinstance(key, str) or not key:
            raise TypeError(
                f"{self._label}注册缺键：{obj!r} 既无 "
                f"{self._key_attr!r} 属性也无 __name__")
        self.insert(key, obj)
        return obj

    def insert(self, key: str, obj: V) -> None:
        """直写登记口（键校验+重名策略+落表）。allow_non_str_keys=True
        时键校验放开为 hashable（不可哈希由 dict 自然抛 TypeError）。
        """
        if (not self._allow_non_str_keys
                and (not isinstance(key, str) or not key)):
            raise TypeError(
                f"{self._label}注册键须为非空字符串，得 {key!r}")
        self._ensure_free(key)
        self._items[key] = obj

    # ── 读取/消费 ─────────────────────────────────────────────────────────

    def get(self, key: str, default: Any = _MISSING) -> Any:
        """按键取注册对象；缺名 KeyError（文案=label+key+可用键序表，
        {keys}=逗号连接、{keys_list}=整列表 repr——两占位符并存覆盖
        两类历史文案形态），传 default（含 None）则缺名回退不抛。
        """
        if key in self._items:
            return self._items[key]
        if default is not _MISSING:
            return default
        raise KeyError(self._missing_fmt.format(
            label=self._label, key=key,
            keys=self._keys_txt(), keys_list=self.keys()))

    def keys(self) -> list[Any]:
        """已注册键（缺省字典序；ordered=True=登记序）——测试断言/
        快照对账统一走这里。
        """
        if self._ordered:
            return list(self._items)
        return sorted(self._items)

    def create(self, key: str, *args: Any, **kwargs: Any) -> Any:
        """取出并调用（工厂/类注册面的实例化口径；等价 get(key)(*a, **kw)）。"""
        return self.get(key)(*args, **kwargs)

    # ── 维护/对账 ─────────────────────────────────────────────────────────

    def unregister(self, key: str) -> V | None:
        """注销（测试清理用）；缺名静默 no-op，与 dict.pop(k, None) 同语义。
        返回被注销对象或 None。
        """
        return self._items.pop(key, None)

    def snapshot(self) -> dict[Any, V]:
        """注册面快照拷贝（金快照/消费者对账用；改动不回注本体）。"""
        return dict(self._items)

    def __contains__(self, key: object) -> bool:
        return key in self._items

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Any:
        return iter(self.keys())

    # ── 内部 ──────────────────────────────────────────────────────────────

    def _keys_txt(self) -> str:
        """{keys} 占位符渲染（逗号连接可用键）；非 str 键 str() 化兜底，
        str 键面输出与 ", ".join(keys()) 逐字节一致。
        """
        return ", ".join(
            k if isinstance(k, str) else str(k) for k in self.keys())

    def _ensure_free(self, key: str) -> None:
        if not self._allow_overwrite and key in self._items:
            raise ValueError(self._dup_fmt.format(
                label=self._label, key=key,
                keys=self._keys_txt(), keys_list=self.keys()))
