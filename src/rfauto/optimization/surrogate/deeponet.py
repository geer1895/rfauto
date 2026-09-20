r"""DeepONet 神经算子代理（可选插件）。

学习「几何参数 + 频率 → S11(dB) 全频段曲线」的算子，经典 branch×trunk
架构：branch 网络把归一化几何参数映射为 p 维基系数，trunk 网络把频率坐标
映射为 p 维基函数取值，输出 = Σ_k branch_k(params)·trunk_k(f) + 偏置——
算子学习（Lu et al. 2021）的低秩分解。trunk 输入用 Fourier 特征编码
[f, sin(2πkf), cos(2πkf)]（k=1..K）缓解 MLP 谱偏置：合成 Q=30 谐振族离线
实测（15 条曲线，held-out x=0.7）无编码 rms 1.62dB/谷深 −6.0 vs 真 −16.5，
K=8+depth=3 后 rms 0.67dB/谷深 −14.7——默认值据此定，非拍脑袋。与
fno_lite（Fourier 特征拼接 MLP）的对照分支：显式的参数/频率基分解。
E3 验收口径（方案 :482）：既有锚数据集上标量 ρ 不劣于 poly_ridge（A/B 见
scripts/wp34_neural_operator_ab.py）。

torch 为可选 extra（`pip install rfauto[torch]`），未安装显式报错（不走静默
降级）。确定性：固定种子 + 全批训练（无 DataLoader 洗牌），CPU 秒-分级；
predict 纯函数语义（同参数同输出，base 契约 C4）。
"""

from __future__ import annotations

from typing import Any

import numpy as np

from rfauto.optimization.surrogate.base import SurrogateModel, surrogate_registry


def _resample_curve(s11_db: np.ndarray, f_src: np.ndarray, n: int) -> np.ndarray:
    """把任意频点网格上的曲线线性重采样到 n 点均匀网格。"""
    return np.interp(np.linspace(f_src[0], f_src[-1], n), f_src, s11_db)


def _trunk_features(freq_norm: np.ndarray, n_feat: int) -> np.ndarray:
    """trunk 输入特征 (T, 1+2K)：[f, sin(2πk f), cos(2πk f), k=1..K]；K=0 退化为 [f]。"""
    cols = [freq_norm]
    for k in range(1, int(n_feat) + 1):
        cols.append(np.sin(2 * np.pi * k * freq_norm))
        cols.append(np.cos(2 * np.pi * k * freq_norm))
    return np.stack(cols, axis=-1)


@surrogate_registry.register("deeponet")
class DeepONetSurrogate(SurrogateModel):
    """branch×trunk 内积曲线代理：predict_curve(params) → 全频段 S11(dB)。

    config:
        bounds: {param: (low, high)}（必填，归一化基准）
        freq_grid: [f_min_ghz, f_max_ghz]（曲线定义域）
        curve_samples: 训练/预测曲线重采样点数（默认 128）
        p: 基维数（branch 输出/trunk 输出维，默认 32）
        hidden: branch/trunk 隐层宽度（默认 64）
        depth: branch/trunk 各自隐层层数（默认 3）
        trunk_fourier_feats: trunk 频率 Fourier 特征阶数 K（默认 8；0=裸频率）
        epochs: 全批 Adam 训练轮数（默认 1500，CPU 秒级）
        lr: 学习率（默认 5e-3）
        seed: 初始化种子（默认 42，可复现）
        curve_key: metrics 里存曲线的键（默认 s11_curve_db）

    predict 返回带内标量（band=fitted 频率网格全域）：
        s11_db_min_in_band（谷深，#195/#197 显式指标名）+
        s11_curve_max_in_band（fno_lite 兼容键）。
    """

    KIND = "deeponet"

    def _ensure_torch(self):
        try:
            import torch
            return torch
        except ImportError as exc:  # 可选依赖缺失：显式报错
            raise RuntimeError(
                "deeponet 需要 torch：pip install rfauto[torch] 或 "
                "pip install torch --index-url "
                "https://download.pytorch.org/whl/cpu") from exc

    # ---- 数据准备（与 fno/fno_lite 同口径：bounds 归一化 + 曲线重采样） ----

    def _prepare(self) -> None:
        cfg = self.config
        self.bounds = {k: tuple(v) for k, v in cfg["bounds"].items()}
        self.names = sorted(self.bounds)
        f_lo, f_hi = (float(v) for v in cfg["freq_grid"])
        self.curve_key = str(cfg.get("curve_key", "s11_curve_db"))
        self.n_curve = int(cfg.get("curve_samples", 128))
        self.freq_grid = np.linspace(f_lo, f_hi, self.n_curve)
        self._freq_norm = (self.freq_grid / f_hi) if f_hi else self.freq_grid

    def _unit_row(self, params: dict[str, float]) -> np.ndarray:
        return np.array([
            np.clip((float(params.get(n, lo)) - lo) / max(hi - lo, 1e-12), 0.0, 1.0)
            for n, (lo, hi) in ((n, self.bounds[n]) for n in self.names)])

    def _collect_curves(self, samples: list[dict[str, Any]]) -> np.ndarray:
        curves = []
        for s in samples:
            raw = s.get("metrics", {}).get(self.curve_key)
            if raw is None:
                continue
            c = np.asarray(raw, dtype=float)
            src = np.linspace(self.freq_grid[0], self.freq_grid[-1], len(c))
            curves.append(_resample_curve(c, src, self.n_curve))
        if len(curves) < 5:
            raise ValueError(
                f"曲线样本不足（需 ≥5 条含 {self.curve_key} 的样本）")
        return np.stack(curves)  # (B, T)

    def _build_net(self, torch: Any, nn: Any, n_params: int,
                   n_trunk_in: int) -> Any:
        """branch(参数→p) × trunk(频率特征→p) 内积 + 偏置。"""
        p = int(self.config.get("p", 32))
        hidden = int(self.config.get("hidden", 64))
        depth = int(self.config.get("depth", 3))

        def _mlp(n_in: int, n_out: int) -> Any:
            layers: list[Any] = []
            dim = n_in
            for _ in range(depth):
                layers += [nn.Linear(dim, hidden), nn.GELU()]
                dim = hidden
            layers += [nn.Linear(dim, n_out)]
            return nn.Sequential(*layers)

        class _DeepONetNet(nn.Module):
            def __init__(self) -> None:
                super().__init__()
                self.branch = _mlp(n_params, p)
                self.trunk = _mlp(n_trunk_in, p)
                self.bias = nn.Parameter(torch.zeros(1))

            def forward(self, u: Any, f: Any) -> Any:  # → (N, 1)
                return (self.branch(u) * self.trunk(f)).sum(
                    -1, keepdim=True) + self.bias

        return _DeepONetNet()

    # ---- 契约实现 ----

    def fit(self, samples: list[dict[str, Any]]) -> dict[str, Any]:
        torch = self._ensure_torch()
        from torch import nn

        torch.manual_seed(int(self.config.get("seed", 42)))
        self._prepare()
        curves = self._collect_curves(samples)           # (B, T)
        kept = [s for s in samples
                if self.curve_key in s.get("metrics", {})]
        unit = np.stack([self._unit_row(s["params"]) for s in kept])  # (B, P)

        # 逐点展开（同 fno_lite 口径）：每条曲线 × 全频率网格 → (N, P)/(N, F)
        n_pts = len(self.freq_grid)
        self._n_ff = int(self.config.get("trunk_fourier_feats", 8))
        trunk_in = _trunk_features(self._freq_norm, self._n_ff)   # (T, F)
        u = np.repeat(unit, n_pts, axis=0)                        # (N, P)
        f = np.tile(trunk_in, (len(kept), 1))                     # (N, F)
        y = curves.reshape(-1)                                    # (N,)

        net = self._build_net(torch, nn, len(self.names), trunk_in.shape[1])
        ut = torch.tensor(u, dtype=torch.float32)
        ft = torch.tensor(f, dtype=torch.float32)
        yt = torch.tensor(y[:, None], dtype=torch.float32)
        opt = torch.optim.Adam(net.parameters(),
                               lr=float(self.config.get("lr", 5e-3)))
        loss_fn = nn.MSELoss()
        epochs = int(self.config.get("epochs", 1500))
        loss = None
        for _ in range(epochs):
            opt.zero_grad()
            loss = loss_fn(net(ut, ft), yt)
            loss.backward()
            opt.step()
        self._net = net
        self._mark_fitted(len(curves))
        return {"kind": self.KIND, "n_curves": len(curves),
                "n_curve_points": n_pts,
                "final_loss": float(loss.detach())}

    def _check_fitted(self) -> None:
        if not self.fitted:
            raise RuntimeError("代理未拟合，先调用 fit()")

    def predict_curve(self, params: dict[str, float],
                      n_points: int | None = None) -> dict[str, Any]:
        """预测全频段 S11(dB) 曲线（返回 freq_ghz/s11_db 数组）。"""
        self._check_fitted()
        torch = self._ensure_torch()

        grid = (self.freq_grid if n_points is None
                else np.linspace(self.freq_grid[0], self.freq_grid[-1],
                                 int(n_points)))
        f_hi = float(self.freq_grid[-1])
        f_norm = (grid / f_hi) if f_hi else grid
        u = torch.tensor(self._unit_row(params)[None, :].repeat(len(grid), 0),
                         dtype=torch.float32)
        f = torch.tensor(_trunk_features(f_norm, self._n_ff), dtype=torch.float32)
        with torch.no_grad():
            y = self._net(u, f).numpy()[:, 0]
        return {"freq_ghz": grid.tolist(), "s11_db": y.tolist()}

    def predict(self, params: dict[str, float]) -> dict[str, float]:
        """带内标量（band=fitted 频率网格全域，见类 docstring）。"""
        self._check_fitted()
        curve = self.predict_curve(params)
        vals = np.asarray(curve["s11_db"], dtype=float)
        return {"s11_db_min_in_band": float(vals.min()),
                "s11_curve_max_in_band": float(vals.max())}
