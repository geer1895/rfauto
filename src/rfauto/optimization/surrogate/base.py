"""代理模型接口（v0 契约层）。

设计目标（接口化要求）：任何外部正向代理模型——无论是内置的
空间映射/GP，还是第三方 NN（如法动 SOTA）、他人自定义模型——都通过实现
SurrogateModel 并注册进 SurrogateRegistry 接入 tune/校准链路，框架其余
部分只依赖基类契约。

最小契约：
    model = MySurrogate(config=...)
    info = model.fit(samples)          # samples: [{"params": {...}, "metrics": {...}}]
    metrics = model.predict(params)    # 返回与 objectives 指标同名的 dict
    sigma = model.uncertainty(params)  # 可选；返回 None 表示无不确定性估计

用法（第三方）：
    from rfauto.optimization.surrogate import SurrogateModel, surrogate_registry

    @surrogate_registry.register("my_nn")
    class MySurrogate(SurrogateModel):
        KIND = "my_nn"
        def fit(self, samples): ...
        def predict(self, params): ...
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

__all__ = ["SurrogateModel", "SurrogateRegistry", "surrogate_registry"]


class SurrogateModel(ABC):
    """正向代理模型基类（粗筛用，不承担最终结论——精算永远走真机通道）。

    契约说明：
    - params/metrics 均为"参数名 → 数值"的平铺 dict，与配方
      optimization.params / SpecEvaluator 指标键一致；
    - fit 的 samples 里 metrics 缺失或非数值的条目应被实现方忽略
      （对应真机失败 trial）；
    - predict 必须是纯函数语义（同参数同输出），可复现性红线（C4）。
    """

    #: 代理种类标识（注册键；子类必须覆盖）
    KIND: str = ""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config: dict[str, Any] = dict(config or {})
        self._fitted = False

    @abstractmethod
    def fit(self, samples: list[dict[str, Any]]) -> dict[str, Any]:
        """用采样数据拟合代理，返回拟合信息 dict（至少含 n_samples）。"""

    @abstractmethod
    def predict(self, params: dict[str, float]) -> dict[str, Any]:
        """预测给定参数的指标（metrics 同构 dict）。"""

    def uncertainty(self, params: dict[str, float]) -> dict[str, float] | None:
        """预测不确定性（如 ±σ）；默认无（返回 None）。"""

    def predict_with_std(
        self, params: dict[str, float],
    ) -> dict[str, tuple[float, float | None]]:
        """预测 + 不确定度合并面（DP-16 U3：mean±σ，variance 透出）。

        返回 {metric: (mean, std|None)}；模型未实现 uncertainty（基类
        默认 None，如 poly_ridge/gbdt）时 std=None——调用方对 None 如实
        标注"无原生逐点不确定度"，不得伪造 0（#122 诚实纪律）。
        """
        mean = self.predict(params)
        std = self.uncertainty(params)
        if std is None:
            return {k: (float(v), None) for k, v in mean.items()}
        return {k: (float(v), (float(std[k]) if k in std else None))
                for k, v in mean.items()}

    @property
    def fitted(self) -> bool:
        return self._fitted

    def _mark_fitted(self, n_samples: int) -> dict[str, Any]:
        self._fitted = True
        return {"kind": self.KIND, "n_samples": n_samples}


class SurrogateRegistry:
    """代理模型注册表（基类+注册表模式，同 EMSolverRegistry）。"""

    def __init__(self) -> None:
        self._factories: dict[str, Callable[..., SurrogateModel]] = {}

    def register(
        self, kind: str, factory: Callable[..., SurrogateModel] | None = None,
    ) -> Callable:
        """注册代理工厂（可作装饰器：@registry.register("my_nn")）。"""

        def _wrap(cls: Callable[..., SurrogateModel]) -> Callable[..., SurrogateModel]:
            self._factories[kind] = cls
            return cls

        if factory is not None:
            _wrap(factory)
            return factory
        return _wrap

    def create(self, kind: str, **kwargs: Any) -> SurrogateModel:
        if kind not in self._factories:
            raise KeyError(
                f"未注册的代理类型: {kind}，可用: {sorted(self._factories)}")
        return self._factories[kind](**kwargs)

    def available(self) -> list[str]:
        return sorted(self._factories)


surrogate_registry = SurrogateRegistry()
