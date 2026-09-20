"""FNO-lite 神经算子原型（阶段 6.3，CPU 小规模）。

学习"几何参数 + 频率 → S11(dB) 全频段曲线"的算子（DeepONet 式
branch×trunk 思想的紧凑实现：参数分支 + Fourier 频率特征主干拼接 MLP），
根治带内标量指标的平坦化问题——带内最大值只反映曲线一个点。

定位：原型（6.3 完整版=数据集 100+ 点、FNO 谱卷积、GPU）。torch 为
可选 extra（`pip install rfauto[torch]`），未安装显式报错。训练确定性：
固定种子 + 全批 L-BFGS 式小迭代，CPU 即可。
"""

from __future__ import annotations

from typing import Any

import numpy as np

from rfauto.optimization.surrogate.base import SurrogateModel, surrogate_registry


def _fourier_features(freq_norm: np.ndarray, n_freq_feat: int = 8) -> np.ndarray:
    """频率主干特征：[f, sin(2πk f), cos(2πk f), k=1..n]。"""
    feats = [freq_norm]
    for k in range(1, n_freq_feat + 1):
        feats.append(np.sin(2 * np.pi * k * freq_norm))
        feats.append(np.cos(2 * np.pi * k * freq_norm))
    return np.concatenate(feats, axis=-1)


@surrogate_registry.register("fno_lite")
class FNOLiteSurrogate(SurrogateModel):
    """曲线级算子代理：predict_curve(params, freq_ghz) → 全频段 S11(dB)。

    config:
        bounds: {param: (low, high)}
        freq_grid: [f_min_ghz, f_max_ghz]（曲线定义域）
        curve_samples: 训练曲线重采样点数（默认 128）
        hidden: 隐层宽度（默认 64）
        epochs: 训练轮数（默认 300，CPU 秒级）
        seed: 初始化种子（默认 42，可复现）
    """

    KIND = "fno_lite"

    def _ensure_torch(self):
        try:
            import torch
            return torch
        except ImportError as exc:
            raise RuntimeError(
                "fno_lite 需要 torch：pip install rfauto[torch] 或 "
                "pip install torch --index-url "
                "https://download.pytorch.org/whl/cpu") from exc

    def _resample_curve(self, s11_db: np.ndarray, f_src: np.ndarray,
                        n: int) -> np.ndarray:
        return np.interp(np.linspace(f_src[0], f_src[-1], n), f_src, s11_db)

    def fit(self, samples: list[dict[str, Any]]) -> dict[str, Any]:
        import torch
        from torch import nn

        torch.manual_seed(int(self.config.get("seed", 42)))
        cfg = self.config
        self.bounds = {k: tuple(v) for k, v in cfg["bounds"].items()}
        self.names = sorted(self.bounds)
        f_lo, f_hi = (float(v) for v in cfg["freq_grid"])
        n_curve = int(cfg.get("curve_samples", 128))
        hidden = int(cfg.get("hidden", 64))
        epochs = int(cfg.get("epochs", 300))

        self.freq_grid = np.linspace(f_lo, f_hi, n_curve)
        curves = [np.asarray(s["metrics"]["s11_curve_db"], dtype=float)
                  for s in samples if "s11_curve_db" in s.get("metrics", {})]
        curves = [self._resample_curve(c, np.linspace(f_lo, f_hi, len(c)),
                                       n_curve) for c in curves]
        if len(curves) < 5:
            raise ValueError("曲线样本不足（需 ≥5 条含 s11_curve_db 的样本）")

        # 训练集：每条曲线 × 全频率网格展开为 (params, f) → s11_db 点集
        xs, fs, ys = [], [], []
        for s, curve in zip(samples, curves, strict=False):
            if "s11_curve_db" not in s.get("metrics", {}):
                continue
            unit = [np.clip((float(s["params"].get(n, lo)) - lo)
                            / max(hi - lo, 1e-12), 0.0, 1.0)
                    for n, (lo, hi) in ((n, self.bounds[n])
                                        for n in self.names)]
            ff = _fourier_features(self.freq_grid[:, None] / f_hi
                                   if f_hi else self.freq_grid[:, None])
            xs.append(np.tile(np.array(unit), (n_curve, 1)))
            fs.append(ff)
            ys.append(curve[:, None])
        X = np.concatenate(xs)          # (N, n_params)
        F = np.concatenate(fs)          # (N, 1 + 2*n_freq_feat)
        Y = np.concatenate(ys)          # (N, 1)

        torch_X = torch.tensor(np.hstack([X, F]), dtype=torch.float32)
        torch_Y = torch.tensor(Y, dtype=torch.float32)
        net = nn.Sequential(
            nn.Linear(X.shape[1] + F.shape[1], hidden), nn.Tanh(),
            nn.Linear(hidden, hidden), nn.Tanh(),
            nn.Linear(hidden, 1))
        opt = torch.optim.Adam(net.parameters(), lr=1e-3)
        loss_fn = nn.MSELoss()
        net.train()
        for _ in range(epochs):
            opt.zero_grad()
            loss = loss_fn(net(torch_X), torch_Y)
            loss.backward()
            opt.step()
        self._net = net
        self._f_hi = f_hi
        self._mark_fitted(len(curves))
        return {"kind": self.KIND, "n_curves": len(curves),
                "final_loss": float(loss.detach())}

    def _check_fitted(self) -> None:
        if not self.fitted:
            raise RuntimeError("代理未拟合，先调用 fit()")

    def predict_curve(self, params: dict[str, float],
                      n_points: int | None = None) -> dict[str, Any]:
        """预测全频段 S11(dB) 曲线（返回 freq_ghz/s11_db 数组）。"""
        self._check_fitted()
        import torch

        grid = (self.freq_grid if n_points is None
                else np.linspace(self.freq_grid[0], self.freq_grid[-1], n_points))
        unit = [np.clip((float(params.get(n, lo)) - lo) / max(hi - lo, 1e-12),
                        0.0, 1.0)
                for n, (lo, hi) in ((n, self.bounds[n]) for n in self.names)]
        ff = _fourier_features(grid[:, None] / self._f_hi if self._f_hi
                               else grid[:, None])
        x = np.hstack([np.tile(np.array(unit), (len(grid), 1)), ff])
        with torch.no_grad():
            y = self._net(torch.tensor(x, dtype=torch.float32)).numpy()[:, 0]
        return {"freq_ghz": grid.tolist(), "s11_db": y.tolist()}

    def predict(self, params: dict[str, float]) -> dict[str, float]:
        """带内标量兼容：从预测曲线取带内最大 S11(dB)（band 取自 freq_grid 全域）。"""
        self._check_fitted()
        curve = self.predict_curve(params)
        return {"s11_curve_max_in_band": float(np.max(curve["s11_db"]))}
