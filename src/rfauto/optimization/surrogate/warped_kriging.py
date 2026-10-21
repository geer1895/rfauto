"""EC-16 HEBO 式 input warping + 确定性 ARD-GP（Kumaraswamy 固定超参）。

池 P3 圈定件（架构批 W5-S22；ecosystem §二 EC-16）。法源：
- HEBO（Cowen-Rivers et al., "Engineering design optimisation with
  HEBO", 2020/2022，huawei-noah/HEBO）：输入空间扭曲（beta/Kumaraswamy
  核）让 GP 的"均匀分辨率"假设迁就目标函数的异质灵敏度——典型 RF 场景
  （频率/长度参数在自然空间内对数型变化）在单元空间近 0 处变化陡峭，
  直接 SE-GP 分辨率不足；
- Kumaraswamy CDF 作为扭曲函数：F(x; a, b) = 1 − (1 − x^b)^(1/a)
  （Kumaraswamy 1980；HEBO 用其近似 Beta 核，零 Bessel 函数依赖）。
  单调满射 [0,1]→[0,1]，(a,b)=(1,1) 为恒等（缺省=退化为普通 GP）。

确定性铁律（ecosystem 表格原文"确定性 Kumaraswamy 固定超参，不引依赖"）：
- 扭曲超参 (a,b) 逐维由 config 显式给出，**不做学习**（HEBO 原版逐迭代
  重学 beta 核；本档是固定超参退化，行为可预声明——诚实边界，非 HEBO
  全量复刻）；
- GP 底座 = optimization.surrogate.gp_det（MLE 档，固定初值 L-BFGS-B，
  同数据逐位可复现，C4）；
- 零新依赖（numpy/scipy 均为核心依赖）。

注册即生效（基类+注册表模式，规则 3）：``surrogate_registry.create(
"warped_kriging", config={...})``；纯增量键，既有 kind 消费面
（surrogate_loop/trust_region/calibration_service）零改动。

合成裁判验收口径（ecosystem 表格"#207 合成裁判验收"）：见
tests/unit/test_warped_kriging.py——陡峭函数（√x 型）的恒等 warp 与
√warp 的 NRMSE 对照（已知真值回收，#118 双源：闭式函数本身即真值）。
"""

from __future__ import annotations

from typing import Any

import numpy as np

from rfauto.optimization.surrogate.base import (
    SurrogateModel,
    surrogate_registry,
)
from rfauto.optimization.surrogate.gp_det import DetGaussianProcess, fit_mle

__all__ = ["WarpedKrigingSurrogate", "kumaraswamy_warp",
           "kumaraswamy_warp_inverse"]


def kumaraswamy_warp(
    x: np.ndarray | float, a: float = 1.0, b: float = 1.0,
) -> np.ndarray | float:
    """Kumaraswamy CDF 扭曲 F(x)=1−(1−x^b)^(1/a)（单调满射 [0,1]→[0,1]）。

    (a,b)=(1,1) 为恒等；标量入对标量返回（ndarray/float 双态，纯函数）。
    """
    xa = np.clip(np.asarray(x, dtype=float), 0.0, 1.0)
    out = 1.0 - np.power(np.clip(1.0 - xa ** float(b), 0.0, 1.0),
                         1.0 / float(a))
    return float(out) if np.isscalar(x) else out


def kumaraswamy_warp_inverse(
    u: np.ndarray | float, a: float = 1.0, b: float = 1.0,
) -> np.ndarray | float:
    """扭曲的解析逆：u = 1−(1−x^b)^(1/a) ⇒ x = [1−(1−u)^a]^(1/b)。"""
    ua = np.clip(np.asarray(u, dtype=float), 0.0, 1.0)
    inner = np.clip(1.0 - np.power(1.0 - ua, float(a)), 0.0, 1.0)
    out = np.power(inner, 1.0 / float(b))
    return float(out) if np.isscalar(u) else out


def _warp_rows(
    x_unit: np.ndarray, names: list[str],
    warp: dict[str, tuple[float, float]],
) -> np.ndarray:
    out = np.array(x_unit, dtype=float, copy=True)
    for j, n in enumerate(names):
        a, b = warp.get(n, (1.0, 1.0))
        out[:, j] = kumaraswamy_warp(out[:, j], a=a, b=b)
    return out


@surrogate_registry.register("warped_kriging")
class WarpedKrigingSurrogate(SurrogateModel):
    """Kumaraswamy 扭曲输入 + 确定性 ARD-SE GP（EC-16，opt-in 新键）。

    config:
        bounds: {param: (low, high)}（必填，单元归一化基准）。
        warp: {param: (a, b) 或 {"a":…, "b":…}} 逐维扭曲超参（固定不学习）；
            缺席维度 = 恒等 (1,1)。
        kernel: "se"（缺省；底座另支持 "matern52"）。
        optimize_nugget: 是否 MLE 联合优化噪声档（缺省 True）。
        metrics: 要建模的指标键列表（缺省 = fit 样本全部数值键并集，
            同 smt_kriging 约定；有效点 <3 的键跳过不硬拟）。
    """

    KIND = "warped_kriging"

    def _unit_row(self, params: dict[str, float]) -> np.ndarray:
        return np.array([
            np.clip((float(params.get(n, lo)) - lo) / max(hi - lo, 1e-12),
                    0.0, 1.0)
            for n, (lo, hi) in ((n, self.bounds[n]) for n in self.names)])

    def _warped_row(self, params: dict[str, float]) -> np.ndarray:
        return _warp_rows(self._unit_row(params)[None, :],
                          self.names, self.warp)[0]

    def fit(self, samples: list[dict[str, Any]]) -> dict[str, Any]:
        self.bounds = {k: tuple(v) for k, v in self.config["bounds"].items()}
        self.names = sorted(self.bounds)
        self.warp: dict[str, tuple[float, float]] = {}
        for n, spec in (self.config.get("warp") or {}).items():
            if isinstance(spec, dict):
                self.warp[n] = (float(spec["a"]), float(spec["b"]))
            else:
                self.warp[n] = (float(spec[0]), float(spec[1]))
        kind = str(self.config.get("kernel", "se"))
        keys = self.config.get("metrics") or sorted({
            k for s in samples
            for k, v in s.get("metrics", {}).items()
            if isinstance(v, (int, float))})
        xw = _warp_rows(
            np.array([self._unit_row(s["params"]) for s in samples]),
            self.names, self.warp)
        self.models: dict[str, DetGaussianProcess] = {}
        for key in keys:
            y = np.array([float(s["metrics"].get(key, np.nan))
                          for s in samples])
            mask = np.isfinite(y)
            if mask.sum() < 3:
                continue  # 键不存在/全 NaN——跳过不硬拟（同 smt_kriging 约定）
            params = fit_mle(xw[mask], y[mask], kind=kind,
                             optimize_nugget=bool(
                                 self.config.get("optimize_nugget", True)))
            self.models[key] = DetGaussianProcess(xw[mask], y[mask],
                                                  params, kind)
        return self._mark_fitted(len(samples))

    def _check_fitted(self) -> None:
        if not self.fitted:
            raise RuntimeError("代理未拟合，先调用 fit()")

    def predict(self, params: dict[str, float]) -> dict[str, Any]:
        self._check_fitted()
        x = self._warped_row(params)[None, :]
        return {key: float(gp.predict(x)[0][0])
                for key, gp in self.models.items()}

    def uncertainty(self, params: dict[str, float]) -> dict[str, float]:
        self._check_fitted()
        x = self._warped_row(params)[None, :]
        return {key: float(np.sqrt(max(gp.predict(x)[1][0], 0.0)))
                for key, gp in self.models.items()}
