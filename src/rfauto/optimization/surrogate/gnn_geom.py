"""AI-2（round14 §三）：几何输入 GNN 代理插件——像素/版图近邻图消息传递。

规格原文："像素/版图→近邻图消息传递；先在 GP_dataset 与仓内 MAPES
像素数据训练；torch-geometric（BSD）可选 extra。验收：锚数据集 ρ 不劣
于 gp_tensor/pod_rom（wp34 同口径）"。

本席交付边界（任务书："训练面可 mock/小图合成——真训练非本席门"）：

- **接口与形状面**：SurrogateModel 契约全实现（fit/predict/uncertainty，
  注册键 ``gnn_geom``），小图合成数据验证（像素 4-邻接图、消息传递
  R 轮、池化、岭回归读出）；
- **numpy 消息传递内核**（零 torch 依赖）：h₀=[占用, 归一坐标]，每轮
  m = tanh(Ā·h·W)（Ā=行归一 4-邻接近邻算子，W=种子化固定随机投影），
  h ← [h, m]；图读出 = concat[mean, max, mean(h₀·m)]（第三项是"节点
  ×邻域"交互特征——纯全局计数特征表达不了的局部形态项）；读出→
  多指标岭回归（闭式）。确定性：W 全走 config.seed 派生的 rng，同参
  同输出（C4）；
- **torch-geometric 通道**：``backend="pyg"`` 时惰性探测 import，缺席
  显式报错指路 extras——接口位落地、路径本身不在本席验证门内
  （真训练超本席门，规格原文）；
- **真数据验收**（锚数据集 ρ 对拍 gp_tensor/pod_rom）= 真训练面，非
  本席门（同规格标注）；合成裁判见 tests/unit/test_gnn_geom.py
  docstring 预声明判据。

铁律 7 对照：代理只产插值预测；物理数字全部来自注入样本的 metrics。
"""

from __future__ import annotations

import importlib.util
import math
from typing import Any

import numpy as np

from rfauto.optimization.surrogate.base import SurrogateModel, surrogate_registry


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _unit_grid_coords(n_rows: int, n_cols: int) -> np.ndarray:
    """像素中心归一坐标 (N, 2) ∈ [0,1]²（行主序）。"""
    ys = np.arange(n_rows, dtype=float) / max(n_rows - 1, 1)
    xs = np.arange(n_cols, dtype=float) / max(n_cols - 1, 1)
    coords = [(y, x) for y in ys for x in xs]
    return np.asarray(coords, dtype=float)


def _adjacency(n_rows: int, n_cols: int) -> np.ndarray:
    """4-邻接 0/1 矩阵 (N, N)（行主序；边界节点邻数<4，行归一由消费方做）。"""
    n = n_rows * n_cols
    a = np.zeros((n, n), dtype=float)
    for r in range(n_rows):
        for c in range(n_cols):
            i = r * n_cols + c
            for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                rr, cc = r + dr, c + dc
                if 0 <= rr < n_rows and 0 <= cc < n_cols:
                    a[i, rr * n_cols + cc] = 1.0
    return a


@surrogate_registry.register("gnn_geom")
class GnnGeomSurrogate(SurrogateModel):
    """几何像素图消息传递代理（numpy 小图内核 + pyg 可选通道位）。"""

    KIND = "gnn_geom"

    #: 消息传递轮数缺省
    DEFAULT_ROUNDS = 2
    #: 随机投影维度缺省
    DEFAULT_HIDDEN = 8

    def _resolve_grid(self) -> tuple[int, int, list[str]]:
        cfg = self.config
        shape = cfg.get("grid_shape")
        if not shape or len(shape) != 2:
            raise ValueError(
                "gnn_geom 需要 config.grid_shape=[n_rows, n_cols]"
                "（params 为行主序像素 p{index}）")
        n_rows, n_cols = int(shape[0]), int(shape[1])
        if n_rows < 1 or n_cols < 1:
            raise ValueError(f"grid_shape 须为正，实得 {shape}")
        keys = [f"p{i}" for i in range(n_rows * n_cols)]
        return n_rows, n_cols, keys

    def fit(self, samples: list[dict[str, Any]]) -> dict[str, Any]:
        cfg = self.config
        seed = int(cfg.get("seed", 20261003))
        rounds = int(cfg.get("n_rounds", self.DEFAULT_ROUNDS))
        hidden = int(cfg.get("hidden_dim", self.DEFAULT_HIDDEN))
        ridge_lam = float(cfg.get("ridge_lam", 1e-3))
        if rounds < 1:
            raise ValueError(f"n_rounds 必须 ≥1，实得 {rounds}")
        if hidden < 1:
            raise ValueError(f"hidden_dim 必须 ≥1，实得 {hidden}")
        if ridge_lam <= 0.0:
            raise ValueError(f"ridge_lam 必须 >0，实得 {ridge_lam}")

        n_rows, n_cols, keys = self._resolve_grid()
        n_nodes = n_rows * n_cols

        # 样本矩阵（缺指标的样本如实忽略——基类契约）
        rows: list[np.ndarray] = []
        targets: list[dict[str, float]] = []
        for s in samples:
            params = s.get("params") or {}
            metrics = {k: float(v) for k, v in (s.get("metrics") or {}).items()
                       if _is_number(v)}
            if not metrics:
                continue
            unknown = {str(k) for k in params} - set(keys)
            if unknown:
                raise ValueError(
                    f"params 键集与 grid_shape={n_rows}x{n_cols} 不符"
                    f"（未知键 {sorted(unknown)[:5]}…；期望 {n_nodes} 个"
                    f"像素键 p0..p{n_nodes - 1}——缺失键按 0 补，未知键"
                    "拒绝以防静默张冠李戴）")
            occ = np.array([float(params.get(k, 0.0)) for k in keys])
            if occ.shape[0] != n_nodes:
                raise ValueError(
                    f"params 键数 {occ.shape[0]} 与 grid_shape 像素数 "
                    f"{n_nodes} 不符")
            rows.append(occ)
            targets.append(metrics)
        if len(rows) < 3:
            raise ValueError("有效样本不足（需 ≥3）")
        self._keys = keys
        self._n_rows, self._n_cols = n_rows, n_cols

        metric_keys = sorted({k for t in targets for k in t})
        self._metric_keys = metric_keys
        X_occ = np.array(rows)                      # (n, N)
        Y = np.array([[t.get(k, np.nan) for k in metric_keys]
                      for t in targets])            # (n, m) 可含 NaN

        embeddings = np.array([
            self._embed(occ, n_rows, n_cols, rounds, hidden, seed)
            for occ in X_occ
        ])
        mask = np.isfinite(Y)
        # 逐指标岭回归（闭式）：w = (GᵀG + λI)⁻¹ Gᵀ y（只用该指标有限样本）
        self._weights: dict[str, np.ndarray] = {}
        self._y_mean: dict[str, float] = {}
        self._resid_std: dict[str, float] = {}
        for j, key in enumerate(metric_keys):
            gmask = mask[:, j]
            if int(gmask.sum()) < 3:
                continue
            Gj = embeddings[gmask]
            yj = Y[gmask, j]
            y_mean = float(np.mean(yj))
            yc = yj - y_mean
            dim = Gj.shape[1]
            a = Gj.T @ Gj + ridge_lam * np.eye(dim)
            w = np.linalg.solve(a, Gj.T @ yc)
            self._weights[key] = w
            self._y_mean[key] = y_mean
            # 残差标准差（同方差假设，诚实标注为全局量）
            self._resid_std[key] = float(np.std(yj - (Gj @ w + y_mean)))
        if not self._weights:
            raise ValueError("无任何指标具备 ≥3 个有效样本，无法拟合")
        self._mark_fitted(len(rows))
        return {"kind": self.KIND,
                "n_samples": len(rows),
                "n_metrics": len(self._weights),
                "n_nodes": n_nodes,
                "n_rounds": rounds,
                "hidden_dim": hidden}

    def _embed(
        self, occ: np.ndarray, n_rows: int, n_cols: int,
        rounds: int, hidden: int, seed: int,
    ) -> np.ndarray:
        """单图前向：消息传递 R 轮 + mean/max/交互池化 → 嵌入向量。"""
        rng = np.random.default_rng(seed)
        coords = _unit_grid_coords(n_rows, n_cols)
        adj = _adjacency(n_rows, n_cols)
        deg = adj.sum(axis=1, keepdims=True)
        deg[deg == 0.0] = 1.0
        adj_norm = adj / deg                                   # 行归一
        h0 = np.column_stack([occ, coords])                    # (N, 3)
        h = h0
        feat = h.shape[1]
        msg_last = np.zeros((h.shape[0], hidden))
        for _ in range(rounds):
            w_mat = rng.normal(0.0, 1.0 / math.sqrt(feat), size=(feat, hidden))
            msg_last = np.tanh(adj_norm @ h @ w_mat)           # (N, hidden)
            h = np.column_stack([h, msg_last])
            feat = h.shape[1]
        interact = h0[:, :1] * msg_last                        # (N, hidden)
        # 交互项 = 占用位 × 末轮邻域消息（"节点×邻域"局部形态特征——
        # 纯全局计数特征表达不了的项）
        return np.concatenate([h.mean(axis=0), h.max(axis=0),
                               interact.mean(axis=0)])

    def _vector(self, params: dict[str, float]) -> np.ndarray:
        if not getattr(self, "fitted", False):
            raise RuntimeError("代理未拟合，先调用 fit()")
        occ = np.array([float(params.get(k, 0.0)) for k in self._keys])
        if occ.shape[0] != len(self._keys):
            raise ValueError("params 键数与 grid_shape 不符")
        return occ

    def predict(self, params: dict[str, float]) -> dict[str, Any]:
        occ = self._vector(params)
        emb = self._embed(
            occ, self._n_rows, self._n_cols,
            int(self.config.get("n_rounds", self.DEFAULT_ROUNDS)),
            int(self.config.get("hidden_dim", self.DEFAULT_HIDDEN)),
            int(self.config.get("seed", 20261003)))
        out: dict[str, Any] = {}
        for key, w in self._weights.items():
            out[key] = float(emb @ w + self._y_mean[key])
        return out

    def uncertainty(self, params: dict[str, float]) -> dict[str, float]:
        """同方差残差 σ（全局量，逐点相同——诚实标注非逐点后验）。"""
        self._vector(params)  # 形状/已拟合守卫
        return {key: float(self._resid_std.get(key, 0.0))
                for key in self._weights}


def pyg_available() -> bool:
    """torch_geometric 可导入性探测（pyg 通道前置检查；不真正 import）。"""
    return importlib.util.find_spec("torch_geometric") is not None


def require_pyg(backend: str) -> None:
    """backend="pyg" 时的显式依赖门（缺席报错指路 extras）。"""
    if str(backend) == "pyg" and not pyg_available():
        raise RuntimeError(
            'backend="pyg" 需要 torch_geometric（BSD；真训练通道，'
            "本席只落接口位）：pip install rfauto[gnn] 或 "
            "pip install torch_geometric；缺省 numpy 内核已覆盖"
            "小图合成验证面")
