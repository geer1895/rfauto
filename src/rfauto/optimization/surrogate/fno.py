r"""FNO（谱卷积版）神经算子代理（可选插件）。

学习「几何参数 + 频率 → S11(dB) 全频段曲线」的算子：参数经 lifting MLP 升到
通道维后，叠 N 个 1D Fourier 层——rfft（频率维）→ 可学习复权重 × 截断模数
→ irfft——加逐点线性旁路，末端 project MLP 输出曲线。与 fno_lite（Fourier
特征拼接 MLP，逐点独立映射）的区别：谱卷积在频率维全局混合信息，谐振谷的
位置/形状泛化是 FNO 的设计目标。E3 验收口径（方案 :482）：既有锚数据集上
标量 ρ 不劣于 poly_ridge（A/B 见 scripts/wp34_neural_operator_ab.py）。

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


@surrogate_registry.register("fno")
class FNOSurrogate(SurrogateModel):
    """谱卷积 FNO 曲线代理：predict_curve(params) → 全频段 S11(dB)。

    config:
        bounds: {param: (low, high)}（必填，归一化基准）
        freq_grid: [f_min_ghz, f_max_ghz]（曲线定义域）
        curve_samples: 训练/预测曲线重采样点数（默认 128）
        width: Fourier 层通道数（默认 32）
        n_modes: 截断保留的 Fourier 模数（默认 8，自动截到 T//2+1）
        n_layers: Fourier 层数（默认 3）
        epochs: 全批 Adam 训练轮数（默认 600，CPU 秒级）
        lr: 学习率（默认 5e-3）
        seed: 初始化种子（默认 42，可复现）
        curve_key: metrics 里存曲线的键（默认 s11_curve_db）

    predict 返回带内标量（band=fitted 频率网格全域）：
        s11_db_min_in_band（谷深，#195/#197 显式指标名）+
        s11_curve_max_in_band（fno_lite 兼容键）。
    """

    KIND = "fno"

    def _ensure_torch(self):
        try:
            import torch
            return torch
        except ImportError as exc:  # 可选依赖缺失：显式报错
            raise RuntimeError(
                "fno 需要 torch：pip install rfauto[torch] 或 "
                "pip install torch --index-url "
                "https://download.pytorch.org/whl/cpu") from exc

    # ---- 数据准备（与 fno_lite 同口径：bounds 归一化 + 曲线重采样） ----

    def _prepare(self) -> None:
        cfg = self.config
        self.bounds = {k: tuple(v) for k, v in cfg["bounds"].items()}
        self.names = sorted(self.bounds)
        f_lo, f_hi = (float(v) for v in cfg["freq_grid"])
        self.curve_key = str(cfg.get("curve_key", "s11_curve_db"))
        self.n_curve = int(cfg.get("curve_samples", 128))
        self.freq_grid = np.linspace(f_lo, f_hi, self.n_curve)
        # 频率坐标通道归一化（与 fno_lite 同约定：除以 f_hi）
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

    def _build_net(self, torch: Any, nn: Any, n_in: int) -> Any:
        """构造 FNO 网络（lifting → N×Fourier 层 → project）。"""
        width = int(self.config.get("width", 32))
        n_modes = int(self.config.get("n_modes", 8))
        n_layers = int(self.config.get("n_layers", 3))
        m = min(n_modes, self.n_curve // 2 + 1)

        class _FourierLayer(nn.Module):
            def __init__(self) -> None:
                super().__init__()
                scale = 1.0 / (width * width)
                self.weights = nn.Parameter(
                    scale * torch.randn(m, width, width, dtype=torch.cfloat))
                self.pointwise = nn.Linear(width, width)

            def forward(self, x: Any) -> Any:  # x: (B, T, C)
                t = x.shape[1]
                x_ft = torch.fft.rfft(x, dim=1)            # (B, T//2+1, C)
                out_ft = torch.zeros_like(x_ft)
                out_ft[:, :m, :] = torch.einsum(
                    "bfi,fio->bfo", x_ft[:, :m, :], self.weights)
                return torch.nn.functional.gelu(
                    torch.fft.irfft(out_ft, n=t, dim=1) + self.pointwise(x))

        class _FNONet(nn.Module):
            def __init__(self) -> None:
                super().__init__()
                self.lift = nn.Sequential(
                    nn.Linear(n_in, width), nn.GELU(),
                    nn.Linear(width, width))
                self.layers = nn.ModuleList(
                    _FourierLayer() for _ in range(n_layers))
                self.project = nn.Sequential(
                    nn.Linear(width, width), nn.GELU(), nn.Linear(width, 1))

            def forward(self, x: Any) -> Any:  # (B, T, n_in) → (B, T)
                h = self.lift(x)
                for layer in self.layers:
                    h = layer(h)
                return self.project(h).squeeze(-1)

        return _FNONet()

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

        # 输入 (B, T, P+1)：参数广播到频率网格 + 频率坐标通道
        n_pts = len(self.freq_grid)
        x = np.empty((len(kept), n_pts, len(self.names) + 1), dtype=float)
        x[:, :, :len(self.names)] = unit[:, None, :]
        x[:, :, -1] = self._freq_norm[None, :]

        net = self._build_net(torch, nn, x.shape[2])
        xt = torch.tensor(x, dtype=torch.float32)
        yt = torch.tensor(curves, dtype=torch.float32)
        opt = torch.optim.Adam(net.parameters(),
                               lr=float(self.config.get("lr", 5e-3)))
        loss_fn = nn.MSELoss()
        epochs = int(self.config.get("epochs", 600))
        loss = None
        for _ in range(epochs):
            opt.zero_grad()
            loss = loss_fn(net(xt), yt)
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
        x = np.empty((1, len(grid), len(self.names) + 1), dtype=float)
        x[0, :, :len(self.names)] = self._unit_row(params)
        x[0, :, -1] = f_norm
        with torch.no_grad():
            y = self._net(torch.tensor(x, dtype=torch.float32)).numpy()[0]
        return {"freq_ghz": grid.tolist(), "s11_db": y.tolist()}

    def predict(self, params: dict[str, float]) -> dict[str, float]:
        """带内标量（band=fitted 频率网格全域，见类 docstring）。"""
        self._check_fitted()
        curve = self.predict_curve(params)
        vals = np.asarray(curve["s11_db"], dtype=float)
        return {"s11_db_min_in_band": float(vals.min()),
                "s11_curve_max_in_band": float(vals.max())}
