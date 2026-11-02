r"""FNO（谱卷积版）神经算子代理（阶段 6.3 E3 插件，continuation-plan :245/:482）。

学习「几何参数 + 频率 → S11(dB) 全频段曲线」的算子：参数经 lifting MLP 升到
通道维后，叠 N 个 1D Fourier 层——rfft（频率维）→ 可学习复权重 × 截断模数
→ irfft——加逐点线性旁路，末端 project MLP 输出曲线。与 fno_lite（Fourier
特征拼接 MLP，逐点独立映射）的区别：谱卷积在频率维全局混合信息，谐振谷的
位置/形状泛化是 FNO 的设计目标。E3 验收口径（方案 :482）：既有锚数据集上
标量 ρ 不劣于 poly_ridge（A/B 见 scripts/wp34_neural_operator_ab.py）。

标准 FNO 形态出处（T-N18 升格补引）：Li et al., "Fourier Neural Operator
for Parametric Partial Differential Equations", arXiv:2010.08895 (ICLR 2021)
——Fourier 层=rFFT 谱域线性变换×模数截断→iRFFT+逐点线性旁路+激活，即本件
_FourierLayer 实现的形态。电磁域主力化佐证（aurora_n 调研席
runs/aurora_n/recon/surrogate_recon.md §5.1）：自由form电磁散射神经算子
（https://pubs.acs.org/apchd5/article/10/5/1547/336043/ ）、超表面波前优化
FNO+伴随（https://www.sciencedirect.com/science/article/pii/S258900422402772X ）、
电机电磁仿真 FNO（https://par.nsf.gov/biblio/10634656 ）、DA-FNO
（https://arxiv.org/html/2508.17238v1 ）。

GPU 升级位（T-N18 注记）：本件当前全程 CPU 张量（缺省档 width=32/
n_modes=8/n_layers=3/epochs=600，CPU 秒-分级）。上 GPU 时改三处即可、
接口不变：①`fit`/`predict_curve` 里 `xt/yt` 与 `net` 同 `.to(device)`；
②训练档放大（width/epochs/curve_samples 随显存上调）；③大批量数据可换
DataLoader minibatch（此时确定性钉=固定种子+关 shuffle 或显式排序，跨
设备/线程数浮点非逐位，如实声明）。真实档标定见
runs/aurora_n/w3_tn18/（probe_output_r1.txt）。

torch 为可选 extra（`pip install rfauto[torch]`），未安装显式报错（不走静默
降级）。确定性：固定种子 + 全批训练（无 DataLoader 洗牌），CPU 秒-分级；
训练期 loss 逐 epoch 检测 NaN/Inf（发散立即停止报错，不产出坏模型，
T-N18 验收④）；predict 纯函数语义（同参数同输出，base 契约 C4）。
"""

from __future__ import annotations

import math
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
        epochs = int(self.config.get("epochs", 600))
        lr = float(self.config.get("lr", 5e-3))
        opt = torch.optim.Adam(net.parameters(), lr=lr)
        loss_fn = nn.MSELoss()
        loss = None
        for epoch in range(epochs):
            opt.zero_grad()
            loss = loss_fn(net(xt), yt)
            loss.backward()
            opt.step()
            loss_val = float(loss.detach())
            if not math.isfinite(loss_val):
                # 训练发散检测停（T-N18 验收④）：NaN/Inf 立即停止，不静默
                # 返回输出 NaN 的坏模型（#122 诚实纪律——显式报错+fit_info）。
                self.fit_info = {
                    "kind": self.KIND, "diverged": True,
                    "diverged_at_epoch": epoch + 1,
                    "epochs_requested": epochs,
                    "final_loss": loss_val,
                    "n_curves": len(curves),
                    "lr": lr,
                }
                raise RuntimeError(
                    f"fno fit 训练发散：epoch {epoch + 1} loss={loss_val} "
                    f"（NaN/Inf）——已停止训练，不产出模型；常见原因=样本曲线"
                    f"含 NaN/Inf 或学习率过大（lr={lr}）。fit_info 见 "
                    "model.fit_info")
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
