"""SIREN 坐标场代理（注册键 "siren"，aurora_n W3 T-N19）。

sin 激活隐式神经表示（Implicit Neural Representation, INR）参数化的
**场级代理**——"坐标 → 场值"形态，与既有"参数 → 指标/曲线"代理族
（poly_ridge/gp/fno/deeponet/...）正交：本件的 fit/predict 契约里
``params`` 装载**空间坐标**（(x,y) 或 (x,y,z)，经 config["coord_keys"]
声明），``metrics`` 装载**场值**（metrics[config["field_key"]]，实数或
复数）。出处：Sitzmann et al., "Implicit Neural Representations with
Periodic Activation Functions"（SIREN, arXiv:2006.09661, ICLR 2020）——
网络 Φ(x)=Wₙ(ϕₙ₋₁∘…∘ϕ₀)(x)+bₙ，ϕᵢ(xᵢ)=sin(Wᵢxᵢ+bᵢ)（论文式 (4)，
ar5iv 全文实读核对 2026-10-29）。

初始化方案（论文 §3.2 原文 + 官方实现双重核对）：
- 论文主文：隐层 "we propose to draw weights with c=6 so that
  wᵢ∼𝒰(−√(6/n),√(6/n))"（正弦激活输入保持单位标准差）；第一层
  "we propose to initialize the first layer of the sine network with
  weights so that the sine function sin(ω₀·Wx+b) spans multiple periods
  over [−1,1]. We found ω₀=30 to work well for all the applications in
  this work."（ω₀ 只折进第一层激活）；
- 官方实现（vsitzmann/siren modules.py，源码实读）等价形态：激活一律
  sin(ω₀·z)，第一层 ``W∼𝒰(−1/n,1/n)``（first_layer_sine_init，注释
  "See paper sec. 3.2, final paragraph, and supplement Sec. 1.5 for
  discussion of factor 30"），隐层/输出层 ``W∼𝒰(−√(6/n)/ω₀,√(6/n)/ω₀)``
  （sine_init）——ω₀ 折叠位置与论文主文互相等价（主文 ω₀ 只进第一层、
  隐层权直接 √(6/n)；官方实现 ω₀ 进全部激活、隐层权除以 ω₀）。本件取
  官方实现形态（社区事实标准）；偏置不初始化（与官方一致，只动 weight）。

复数场：论文 §4.3 Helmholtz 解口径原文 "To accommodate a complex-valued
solution, we configure the network to output two values, interpreted as
the real and imaginary parts."——本件训练值含 complex → 自动复数模式
（输出 2 通道 re/im，predict 返回 python complex；field_mode 记入
fit_info）；实/复混杂训练值 → ValueError 不静默强制（#122）。

契约适配（T-N19 最小可用形态）：**单场 SIREN**（一个场一个网络）——
本契约的 params 是坐标、不是器件参数，场不随器件参数变化；多场/参数化
条件化（hypernetwork 类）不在本席（升级位）。无原生不确定度，
uncertainty() 走 base 缺省 None（不伪造 σ）。场值不做输出标准化（实机
大幅值场升级位）；坐标按 bounds 逐轴归一到 [−1,1]（论文 Ω 域语义；
未显式给 bounds 时由训练样本坐标逐轴 min/max 推断并记 fit_info），
越界坐标 clip=边界持延（家族口径，同 fno）。

确定性（红线）：torch.manual_seed(seed) + 全批 Adam（无 DataLoader 洗
牌）→ 同配置同样本两次 fit，predict 逐位相等（CPU 同平台；跨平台 BLAS
轨迹漂移如实声明，只互比不钉绝对值，#247 家法）。训练期 loss 逐 epoch
检测 NaN/Inf（发散立即停止报错，不产出坏模型，fno 家法/T-N18 验收④同
款）；坐标含 NaN/Inf 在数据准备期显式拒绝（field 值坏数据走 loss 通道
暴露）。

用法::

    model = surrogate_registry.create("siren", config={
        "coord_keys": ["x", "y"],   # 缺省 ["x","y"]；(x,y,z) 场写三维
        "field_key": "field",       # 缺省 "field"
        "bounds": {"x": (0, 1), "y": (0, 1)},  # 可省=训练样本坐标推断
        "w0": 30.0, "n_hidden": 3, "width": 64,
        "epochs": 1000, "lr": 1e-3, "seed": 42,
    })
    info = model.fit([{"params": {"x": 0.1, "y": 0.2},
                       "metrics": {"field": 0.5}}, ...])
    v = model.predict({"x": 0.3, "y": 0.4})   # {"field": float|complex}

规模边界（训练时长纪律，T-N19）：单场全批训练 CPU 秒-分级（Win11 CPU
实测，跨机只作量级参照，runs/aurora_n/w3_tn19/probe_output.txt+
probe_realtier.txt+probe_complex.txt）——单测档（N=1024/width32/
n_hidden2/epochs600）实测 ~0.4s、复数场同档 ~2.3s、真实档（N=1024/
width64/n_hidden3/epochs1000）实测 ~1-3s、N=2048 档 ~1s。GPU 升级位
同 fno（net/数据 .to(device) + 训练档放大；此时确定性钉跨设备不逐位，
如实声明）。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from rfauto.optimization.surrogate.base import (
    SurrogateModel,
    surrogate_registry,
)

__all__ = ["SirenFieldSurrogate"]

#: 单次 fit 最少训练点数（INR 场重建低于此规模无意义，显式拒绝）
_MIN_POINTS = 8


@surrogate_registry.register("siren")
class SirenFieldSurrogate(SurrogateModel):
    """SIREN 坐标场代理：predict({坐标}) → {field_key: 场值}。

    config:
        coord_keys: 坐标参数名列表（缺省 ["x", "y"]；(x,y,z) 场声明三维；
            fit/predict 的 params 键集合必须与之完全一致，缺失/多余键
            ValueError——坐标维度错显式报错）
        field_key: metrics 里存场值的键（缺省 "field"）
        bounds: {coord: (lo, hi)} 归一化基准（可省缺=训练样本逐轴
            min/max 推断，推断结果记 fit_info["bounds"]）
        w0: ω₀ 第一层频率（缺省 30.0，论文口径；须 >0。ω₀ 决定可表示
            空间频率带——场谱内容已知时按需下调，本席标定场（k=6/单位长）
            用 w0=15 显著优于 30，见 runs/aurora_n/w3_tn19/ 扫描证据）
        n_hidden: sin 隐层数（缺省 3；末端恒为无激活线性输出层，论文式
            (4) 的 Wₙ…+bₙ 外层）
        width: 隐层通道数（缺省 64）
        epochs: 全批 Adam 训练轮数（缺省 1000）
        lr: 学习率（缺省 1e-3；5e-3 在 width64/n_hidden3 实测可失稳进
            频谱噪声（probe_output.txt real_default 行），缺省取稳态档）
        seed: 初始化种子（缺省 42，可复现）

    场值语义：实数样本 → 实数模式（predict 返回 float）；任一样本为
    complex → 复数模式（输出 2 通道 re/im，predict 返回 complex，论文
    §4.3 口径）；实/复混杂 → ValueError。坐标含 NaN/Inf → ValueError；
    场值含 NaN/Inf → 训练 loss 发散检测停（RuntimeError+fit_info）。
    """

    KIND = "siren"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        cfg = self.config
        coord_keys = cfg.get("coord_keys", ["x", "y"])
        if (not isinstance(coord_keys, list) or not coord_keys
                or not all(isinstance(k, str) and k for k in coord_keys)):
            raise ValueError(
                f"coord_keys 须为非空 str 列表，得 {coord_keys!r}")
        if len(set(coord_keys)) != len(coord_keys):
            raise ValueError(f"coord_keys 含重复键：{coord_keys!r}")
        self._coord_keys: list[str] = list(coord_keys)
        field_key = cfg.get("field_key", "field")
        if not isinstance(field_key, str) or not field_key:
            raise ValueError(f"field_key 须为非空 str，得 {field_key!r}")
        self._field_key = field_key
        w0 = cfg.get("w0", 30.0)
        if isinstance(w0, bool) or not isinstance(w0, (int, float)) or w0 <= 0:
            raise ValueError(f"w0（ω₀）须为 >0 数值，得 {w0!r}")
        self._w0 = float(w0)
        n_hidden = cfg.get("n_hidden", 3)
        if (isinstance(n_hidden, bool) or not isinstance(n_hidden, int)
                or n_hidden < 1):
            raise ValueError(
                f"n_hidden（sin 隐层数）须为 ≥1 整数，得 {n_hidden!r}")
        self._n_hidden = int(n_hidden)
        width = cfg.get("width", 64)
        if isinstance(width, bool) or not isinstance(width, int) or width < 1:
            raise ValueError(f"width 须为 ≥1 整数，得 {width!r}")
        self._width = int(width)
        epochs = cfg.get("epochs", 1000)
        if (isinstance(epochs, bool) or not isinstance(epochs, int)
                or epochs < 1):
            raise ValueError(f"epochs 须为 ≥1 整数，得 {epochs!r}")
        self._epochs = int(epochs)
        lr = cfg.get("lr", 1e-3)
        if isinstance(lr, bool) or not isinstance(lr, (int, float)) or lr <= 0:
            raise ValueError(f"lr 须为 >0 数值，得 {lr!r}")
        self._lr = float(lr)
        seed = cfg.get("seed", 42)
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError(f"seed 须为 int，得 {seed!r}")
        self._seed = int(seed)
        bounds = cfg.get("bounds")
        if bounds is not None:
            if not isinstance(bounds, dict):
                raise ValueError(f"bounds 须为 dict 或 None，得 {bounds!r}")
            if set(bounds) != set(self._coord_keys):
                raise ValueError(
                    "bounds 键须与 coord_keys 完全一致 "
                    f"（{sorted(self._coord_keys)}），得 {sorted(bounds)}")
            for k, v in bounds.items():
                try:
                    lo, hi = (float(v[0]), float(v[1]))
                except (TypeError, ValueError, IndexError) as exc:
                    raise ValueError(
                        f"bounds[{k!r}] 须为 (lo, hi) 数值对，得 {v!r}") from exc
                if not (math.isfinite(lo) and math.isfinite(hi) and lo < hi):
                    raise ValueError(
                        f"bounds[{k!r}] 须为有限 lo<hi，得 {(lo, hi)!r}")
        self._bounds_cfg: dict[str, tuple[float, float]] | None = (
            {k: (float(v[0]), float(v[1])) for k, v in bounds.items()}
            if bounds is not None else None)
        self._field_mode = "real"
        self._bounds_eff: dict[str, tuple[float, float]] = {}
        self._net: Any = None
        self.fit_info: dict[str, Any] = {}

    def _ensure_torch(self):
        try:
            import torch
            return torch
        except ImportError as exc:  # 可选依赖缺失：显式报错（不走静默降级）
            raise RuntimeError(
                "siren 需要 torch：pip install rfauto[torch] 或 "
                "pip install torch --index-url "
                "https://download.pytorch.org/whl/cpu") from exc

    # ---- 坐标归一（[−1,1] 域，论文 sin(ω₀·Wx+b) 多周期语义的坐标前提） ──

    def _unit_coords(self, coords: np.ndarray) -> np.ndarray:
        cols = []
        for j, k in enumerate(self._coord_keys):
            lo, hi = self._bounds_eff[k]
            cols.append(np.clip(
                2.0 * (coords[:, j] - lo) / max(hi - lo, 1e-12) - 1.0,
                -1.0, 1.0))
        return np.stack(cols, axis=1)

    def _collect_points(
            self, samples: list[dict[str, Any]],
    ) -> list[tuple[dict[str, float], Any]]:
        """抽取含 field_key 的训练点；params 键集=coord_keys 严格对账。"""
        pool: list[tuple[dict[str, float], Any]] = []
        for s in samples:
            m = s.get("metrics") or {}
            if self._field_key not in m:
                continue
            p = s.get("params") or {}
            if set(p) != set(self._coord_keys):
                raise ValueError(
                    f"坐标维度错：params 键 {sorted(p)} 与 coord_keys "
                    f"{sorted(self._coord_keys)} 不一致（缺失/多余键一律"
                    "拒绝，坐标场代理不做静默对齐）")
            pool.append((p, m[self._field_key]))
        if len(pool) < _MIN_POINTS:
            raise ValueError(
                f"场样本不足：含 metrics['{self._field_key}'] 的样本 "
                f"{len(pool)} < {_MIN_POINTS}")
        return pool

    def _build_net(self, torch: Any, nn: Any, n_in: int, n_out: int) -> Any:
        """构造 SIREN 网络（论文式 (4)：n_hidden×sin 层 + 线性输出层）。"""
        w0 = self._w0
        width = self._width
        n_hidden = self._n_hidden

        class _SirenNet(nn.Module):
            def __init__(self) -> None:
                super().__init__()
                self.first = nn.Linear(n_in, width)
                self.hidden = nn.ModuleList(
                    nn.Linear(width, width) for _ in range(n_hidden - 1))
                self.out = nn.Linear(width, n_out)
                # 官方实现口径：全部 Linear 先过 sine_init（隐层
                # ±√(6/fan_in)/ω₀），再对第一层重初始化（±1/fan_in）；
                # bias 不动（官方只初始化 weight）。
                for m in self.modules():
                    if isinstance(m, nn.Linear):
                        self._sine_init(m)
                self._sine_init(self.first, first_layer=True)

            @staticmethod
            def _sine_init(m: Any, first_layer: bool = False) -> None:
                with torch.no_grad():
                    fan_in = m.weight.size(-1)
                    bound = (1.0 / fan_in if first_layer
                             else math.sqrt(6.0 / fan_in) / w0)
                    m.weight.uniform_(-bound, bound)

            def forward(self, x: Any) -> Any:
                h = torch.sin(w0 * self.first(x))
                for lyr in self.hidden:
                    h = torch.sin(w0 * lyr(h))
                return self.out(h)

        return _SirenNet()

    # ---- 契约实现 ----

    def fit(self, samples: list[dict[str, Any]]) -> dict[str, Any]:
        torch = self._ensure_torch()
        from torch import nn

        torch.manual_seed(self._seed)
        pool = self._collect_points(samples)

        # 场值通道：实/复模式判定（混杂拒绝）+ 数值校验（bool/str 拒绝）
        vals = [v for _p, v in pool]
        for v in vals:
            if isinstance(v, bool) or not isinstance(v, (int, float, complex)):
                raise ValueError(
                    f"场值须为 int/float/complex 数值，得 "
                    f"{type(v).__name__}（{v!r}）——siren 不做静默类型强制")
        has_cplx = any(isinstance(v, complex) for v in vals)
        if has_cplx and not all(isinstance(v, complex) for v in vals):
            raise ValueError(
                "场值实/复混杂：siren 复数模式要求全部训练值为 complex"
                "（论文 §4.3 双通道 re/im 口径），不做静默强制——实/复样本"
                "请分场训练")
        n_out = 2 if has_cplx else 1
        self._field_mode = "complex" if has_cplx else "real"

        coords = np.array(
            [[float(p[k]) for k in self._coord_keys] for p, _v in pool],
            dtype=float)
        if not np.isfinite(coords).all():
            raise ValueError(
                "坐标含 NaN/Inf——数据准备期显式拒绝（场值坏数据才走训练"
                "loss 发散检测通道）")
        # 归一化基准：显式 bounds 或训练样本逐轴推断（INR Ω 域语义）
        if self._bounds_cfg is not None:
            self._bounds_eff = dict(self._bounds_cfg)
        else:
            self._bounds_eff = {
                k: (float(coords[:, j].min()), float(coords[:, j].max()))
                for j, k in enumerate(self._coord_keys)}
        unit = self._unit_coords(coords)
        if has_cplx:
            y = np.array([[float(np.real(v)), float(np.imag(v))]
                          for v in vals], dtype=float)
        else:
            y = np.array([[float(v)] for v in vals], dtype=float)

        net = self._build_net(torch, nn, unit.shape[1], n_out)
        xt = torch.tensor(unit, dtype=torch.float32)
        yt = torch.tensor(y, dtype=torch.float32)
        opt = torch.optim.Adam(net.parameters(), lr=self._lr)
        loss_fn = nn.MSELoss()
        loss = None
        for epoch in range(self._epochs):
            opt.zero_grad()
            loss = loss_fn(net(xt), yt)
            loss.backward()
            opt.step()
            loss_val = float(loss.detach())
            if not math.isfinite(loss_val):
                # 训练发散检测停（fno 家法/T-N18 验收④）：NaN/Inf 立即
                # 停止，不静默产出输出 NaN 的坏模型（#122 诚实纪律）。
                self.fit_info = {
                    "kind": self.KIND, "diverged": True,
                    "diverged_at_epoch": epoch + 1,
                    "epochs_requested": self._epochs,
                    "final_loss": loss_val,
                    "n_points": len(pool),
                    "lr": self._lr,
                }
                raise RuntimeError(
                    f"siren fit 训练发散：epoch {epoch + 1} "
                    f"loss={loss_val}（NaN/Inf）——已停止训练，不产出模型；"
                    f"常见原因=场值样本含 NaN/Inf 或学习率过大"
                    f"（lr={self._lr}）。fit_info 见 model.fit_info")
        self._net = net
        info = self._mark_fitted(len(pool))
        info.update({
            "coord_keys": list(self._coord_keys),
            "field_key": self._field_key,
            "field_mode": self._field_mode,
            "n_points": len(pool),
            "bounds_inferred": self._bounds_cfg is None,
            "bounds": {k: list(v) for k, v in self._bounds_eff.items()},
            "w0": self._w0,
            "n_hidden": self._n_hidden,
            "width": self._width,
            "epochs": self._epochs,
            "lr": self._lr,
            "seed": self._seed,
            "final_loss": float(loss.detach()),
        })
        self.fit_info = info
        return info

    def _check_fitted(self) -> None:
        if not self.fitted:
            raise RuntimeError("代理未拟合，先调用 fit()")

    def predict(self, params: dict[str, float]) -> dict[str, Any]:
        """坐标 → 场值（{field_key: float|complex}；纯函数语义）。"""
        self._check_fitted()
        torch = self._ensure_torch()
        if set(params) != set(self._coord_keys):
            raise ValueError(
                f"坐标维度错：params 键 {sorted(params)} 与 coord_keys "
                f"{sorted(self._coord_keys)} 不一致（缺失/多余键一律拒绝）")
        coords = np.array(
            [[float(params[k]) for k in self._coord_keys]], dtype=float)
        if not np.isfinite(coords).all():
            raise ValueError("坐标含 NaN/Inf——拒绝预测")
        unit = torch.tensor(self._unit_coords(coords), dtype=torch.float32)
        with torch.no_grad():
            out = self._net(unit).numpy()[0]
        if self._field_mode == "complex":
            return {self._field_key: complex(float(out[0]), float(out[1]))}
        return {self._field_key: float(out[0])}
