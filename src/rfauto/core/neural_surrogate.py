r"""神经代理内核（neural surrogate，aurora_r R-05 / B1：Alpha-RF 第一层"神经仿真器"）。

任务来源
--------
aurora_q 作者生态调研吸收（runs/aurora_q/qx40_vbridge/AUTHOR_SURVEY.md）指向的
Alpha-RF（arXiv:2603.00104）两层架构：第一层=神经仿真器（代理：参数 → S 参数
频响），第二层=搜索/RL。本模块只落**第一层（代理内核）**，不做搜索/RL。

分层与依赖
----------
core 层叶子：模块 import 面**只有 numpy+scipy**（scipy.special.erf 单个
函数，gelu 的 numpy 对拍实现用）；torch 是**函数体内懒加载**的可选依赖——
未安装时训练/推理/LOO 调用返回结构化 unavailable 信封（如实，不抛裸错，
不走 deeponet 式 RuntimeError）。torch 无关内核（数据集构建/归一化/spec/
切分/LOO 聚合/纯 numpy 前向）零 torch 可全测。不 import 任何上层
（.importlinter 分层契约；core 不可 import service——信封为同形约定
dict，不经 service.envelope 构造器）。

复数输出双头口径（spec 二选一，本模块钉 re_im）
------------------------------------------------
S 参数复数输出采用**实虚双头**（每通道 re/im 各占 T 列）：
- 幅相双头的相位列在 ±π 缠绕处 2π 跳变，回归损失在跳变带病态；
- dB 幅度列在 |S|→0 处发散（深谷 -60 dB 量级，#195 族语义）；
- re/im 是复数的线性双射，无缠绕无发散；dB/相位等物理量由消费方对
  预测复数做确定性换算（本模块不产出物理换算数字，铁律 7 同向）。
``OUTPUT_HEAD = "re_im"`` 钉死并写进 spec；幅相头若日后立项另立 head
键值，不与本键共存。

数据布局
--------
样本 = (params dict, curves dict)：``curves[c]`` = 共享频栅 ``freqs_hz``
上的复数序列（或 ``{"re": [...], "im": [...]}``）。
:func:`build_sparam_dataset` 对齐为 X (n×d) + Y (n×m)，m = 2·|channels|·T
（channels 按 sorted 序、每通道先 re 后 im 各 T 列）；``channel_offsets``
记录每通道 re/im 列偏移。频栅要求逐样本长度一致且显式共享（**不静默
插值**——重采样是消费方的显式决策）。结构违例（键集不一致/长度不符/
非数值化）返回 error 信封点名样本；数值违例（NaN/±Inf）整点丢弃并计数
（与 dataset_service n_nonfinite_skipped 同口径）。

归一化窗口（纯函数 + 逆变换）
----------------------------
min-max（center=列最小、scale=列宽）与 standard（center=列均值、
scale=列标准差 ddof=0）两档；|scale| < 1e-12 的退化维度走单位尺度
（窗口内恒映射 0、逆变换回 center，可逆）。**不 clip**——窗外值线性
外推且逆变换仍成立（clip 破坏可逆性）。"逐位回收钉"的诚实口径：浮点
``(x-c)/s·s+c`` 对任意 x 不保证 IEEE 逐位相等，本模块的钉 = ①2 的幂
窗宽格点逐位相等（``==`` 断言）+ ②一般值 ≤1e-15 相对误差 + ③spec/
norm 参数 JSON 往返逐位（repr 往返精确）。

确定性
------
torch 面：``manual_seed(spec.seed)`` + ``set_num_threads(1)`` + 全批训练
（无 DataLoader 洗牌/dropout）+ float64 + eval 推理——同机同 torch 版本
逐位可复现；跨设备/跨 torch 版本不承诺逐位（诚实边界）。train/val 切分
与归一化窗口**只 fit 训练行**（val/LOO 泄漏防线）。

#118 独立口径对拍
----------------
:func:`mlp_forward_numpy` 是 torch 前向的**独立裁判**（同 state 同输入，
纯 numpy 手写算子 vs torch 算子，两条无共享代码路径）：测试钉两者
≤1e-12 一致；激活公式逐一对照（gelu 用 exact erf 形式 = torch
``nn.GELU`` 缺省 ``approximate="none"``）。

诚实边界
--------
- **CNN 档未实现**（Alpha-RF 足迹图输入）：只有 :class:`CNNSpec` 数据
  占位与结构化 not_implemented 信封——挂账主代（Alpha-RF 化用批次）。
- **不注册 surrogate_registry**：注册面属 optimization 层（上层），本
  模块只给出信封形状契约，B1"与 surrogate_loop 同接口"的消费接线由
  上层后续批次落（挂账）。
- **无 service 薄壳**：core 信封已是 JSON 进出形态（纯 dict + float
  列表），尚无 CLI/MCP 消费者——薄壳随首个消费面挂账（接口不需要即不
  预建，规则 4 的"先写 service 函数"适用于接 UI/CLI 的那一刻）。
- 网络权重来源=注入样本的确定性拟合；本模块自身不产生任何物理数字
  （铁律 7：物理数值只出自求解器/数据工厂通道，训练数据是唯一来源）。
- torch 安装口径（官方 CPU 轮）：``pip install torch --index-url
  https://download.pytorch.org/whl/cpu``；pyproject 的 torch extra 注册
  挂账主代（本席不碰 pyproject/uv.lock）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.special import erf

__all__ = [
    "ACTIVATIONS",
    "NORMALIZATION_KINDS",
    "OUTPUT_HEAD",
    "TORCH_INSTALL_HINT",
    "CNNSpec",
    "MLPSpec",
    "NormalizationSpec",
    "aggregate_loo_metrics",
    "apply_normalization",
    "build_cnn_surrogate",
    "build_sparam_dataset",
    "derive_mlp_spec",
    "fit_neural_surrogate",
    "fit_normalization",
    "loo_evaluate_mlp",
    "loo_folds",
    "mlp_forward_numpy",
    "mlp_spec_from_dict",
    "mlp_spec_to_dict",
    "predict_mlp",
    "split_train_val",
    "torch_available",
    "undo_normalization",
    "validate_mlp_spec",
]

#: 归一化窗口档位（新档须同时补 fit/apply/undo 与单测）
NORMALIZATION_KINDS = ("minmax", "standard")

#: MLP 支持的激活（新激活须同时补 _torch_activation/_activation_numpy 与单测）
ACTIVATIONS = ("tanh", "relu", "silu", "gelu")

#: 复数输出双头口径（钉死值，见模块 docstring"复数输出双头口径"节）
OUTPUT_HEAD = "re_im"

#: torch 官方 CPU 轮安装口径（unavailable 信封 install_hint 键携带）
TORCH_INSTALL_HINT = (
    "pip install torch --index-url https://download.pytorch.org/whl/cpu"
)

#: 退化维度判据（列尺度绝对下限；物理参数窗宽低于此视作常数通道）
_SCALE_EPS = 1e-12


# ─── 归一化窗口（纯函数 + 逆变换） ───────────────────────────────────────────


@dataclass(frozen=True)
class NormalizationSpec:
    """归一化窗口参数（纯数据，JSON 可序列化）。

    min-max 档：center=列最小、scale=列宽；standard 档：center=列均值、
    scale=列标准差（ddof=0）。退化维度（|scale| < 1e-12）在 apply/undo
    中按单位尺度处理（窗口内恒 0，逆变换回 center）。
    """

    kind: str
    center: tuple[float, ...]
    scale: tuple[float, ...]

    def to_dict(self) -> dict[str, Any]:
        """JSON 形态（tuple→list；float 经 repr 往返逐位精确）。"""
        return {
            "kind": self.kind,
            "center": list(self.center),
            "scale": list(self.scale),
        }

    @staticmethod
    def from_dict(d: Mapping[str, Any]) -> NormalizationSpec:
        """从 JSON 形态重建（float 逐位回收）。"""
        return NormalizationSpec(
            kind=str(d["kind"]),
            center=tuple(float(v) for v in d["center"]),
            scale=tuple(float(v) for v in d["scale"]),
        )


def fit_normalization(
    x: np.ndarray, kind: str = "minmax",
) -> NormalizationSpec:
    """从数据阵 (n×d) 拟合归一化窗口（纯函数，无状态副作用）。

    退化维度（列宽/列标准差 < 1e-12）scale 原样存 0 值——apply/undo 按
    单位尺度处理，保证可逆且窗口内恒 0。
    """
    if kind not in NORMALIZATION_KINDS:
        raise ValueError(
            f"未知归一化档: {kind!r}，可用: {NORMALIZATION_KINDS}")
    arr = np.asarray(x, dtype=np.float64)
    if arr.ndim != 2 or arr.shape[0] < 1 or arr.shape[1] < 1:
        raise ValueError("fit_normalization 需要 (n≥1, d≥1) 的二维数据阵")
    if kind == "minmax":
        center = arr.min(axis=0)
        scale = arr.max(axis=0) - center
    else:  # standard
        center = arr.mean(axis=0)
        scale = arr.std(axis=0)
    return NormalizationSpec(
        kind=kind,
        center=tuple(float(v) for v in center),
        scale=tuple(float(v) for v in scale),
    )


def _effective_scale(spec: NormalizationSpec) -> np.ndarray:
    """退化维度（|scale| < eps）换单位尺度 1.0（可逆性守卫）。"""
    s = np.asarray(spec.scale, dtype=np.float64)
    return np.where(np.abs(s) < _SCALE_EPS, 1.0, s)


def apply_normalization(spec: NormalizationSpec, x: np.ndarray) -> np.ndarray:
    """正变换（纯函数）：最后一维须等于窗口维数；不 clip。"""
    center = np.asarray(spec.center, dtype=np.float64)
    eff = _effective_scale(spec)
    arr = np.asarray(x, dtype=np.float64)
    if arr.shape[-1] != center.shape[0]:
        raise ValueError(
            f"输入最后一维 {arr.shape[-1]} 与窗口维数 {center.shape[0]} 不一致")
    return (arr - center) / eff


def undo_normalization(spec: NormalizationSpec, xn: np.ndarray) -> np.ndarray:
    """逆变换（纯函数）：apply 的解析逆，一般值回收 ≤1e-15 相对误差。"""
    center = np.asarray(spec.center, dtype=np.float64)
    eff = _effective_scale(spec)
    arr = np.asarray(xn, dtype=np.float64)
    if arr.shape[-1] != center.shape[0]:
        raise ValueError(
            f"输入最后一维 {arr.shape[-1]} 与窗口维数 {center.shape[0]} 不一致")
    return arr * eff + center


# ─── 模型规格声明（纯数据 spec，不含权重） ───────────────────────────────────


@dataclass(frozen=True)
class MLPSpec:
    """MLP 档规格（纯数据；权重由训练面产出，state 与 spec 分离）。

    output_head 钉 "re_im"（见模块 docstring 双头口径节）；hidden 为
    隐层宽度序列（tuple 保不可变/可哈希）。
    """

    n_inputs: int
    n_outputs: int
    hidden: tuple[int, ...] = (32, 32)
    activation: str = "tanh"
    output_head: str = OUTPUT_HEAD
    epochs: int = 1500
    lr: float = 5e-3
    weight_decay: float = 0.0
    seed: int = 42


@dataclass(frozen=True)
class CNNSpec:
    """CNN 档规格**占位**（Alpha-RF 足迹图输入；未实现，挂账主代）。

    只声明数据形状（足迹图 rows×cols × 频点维），build_cnn_surrogate
    对任何 CNNSpec 返回结构化 not_implemented 信封——规格先行、实现
    后补（Alpha-RF 化用批次），避免"有 spec 无档"被误当可用能力。
    """

    n_freq: int
    footprint_rows: int
    footprint_cols: int
    channels: int = 8
    kernel_size: int = 3
    depth: int = 2
    seed: int = 42


def validate_mlp_spec(spec: MLPSpec) -> list[str]:
    """spec 校验（纯函数）：返回错误清单（空=合法）。"""
    errors: list[str] = []
    if spec.n_inputs < 1:
        errors.append(f"n_inputs 必须 ≥1（得到 {spec.n_inputs}）")
    if spec.n_outputs < 1:
        errors.append(f"n_outputs 必须 ≥1（得到 {spec.n_outputs}）")
    if not spec.hidden or any(h < 1 for h in spec.hidden):
        errors.append(f"hidden 必须为非空正整数序列（得到 {spec.hidden!r}）")
    if spec.activation not in ACTIVATIONS:
        errors.append(
            f"未知激活 {spec.activation!r}，可用: {ACTIVATIONS}")
    if spec.output_head != OUTPUT_HEAD:
        errors.append(
            f"output_head 只支持 {OUTPUT_HEAD!r}（得到 {spec.output_head!r}；"
            "幅相头未立项，见模块 docstring 双头口径）")
    if spec.epochs < 1:
        errors.append(f"epochs 必须 ≥1（得到 {spec.epochs}）")
    if spec.lr <= 0:
        errors.append(f"lr 必须 >0（得到 {spec.lr}）")
    if spec.weight_decay < 0:
        errors.append(
            f"weight_decay 必须 ≥0（得到 {spec.weight_decay}）")
    return errors


def mlp_spec_to_dict(spec: MLPSpec) -> dict[str, Any]:
    """JSON 形态（hidden tuple→list）。"""
    d: dict[str, Any] = {
        "n_inputs": spec.n_inputs,
        "n_outputs": spec.n_outputs,
        "hidden": list(spec.hidden),
        "activation": spec.activation,
        "output_head": spec.output_head,
        "epochs": spec.epochs,
        "lr": spec.lr,
        "weight_decay": spec.weight_decay,
        "seed": spec.seed,
    }
    return d


def mlp_spec_from_dict(d: Mapping[str, Any]) -> MLPSpec:
    """从 JSON 形态重建（hidden list→tuple；float 逐位回收）。"""
    return MLPSpec(
        n_inputs=int(d["n_inputs"]),
        n_outputs=int(d["n_outputs"]),
        hidden=tuple(int(h) for h in d["hidden"]),
        activation=str(d["activation"]),
        output_head=str(d.get("output_head", OUTPUT_HEAD)),
        epochs=int(d["epochs"]),
        lr=float(d["lr"]),
        weight_decay=float(d.get("weight_decay", 0.0)),
        seed=int(d["seed"]),
    )


def derive_mlp_spec(
    dataset: Mapping[str, Any], **over: Any,
) -> MLPSpec:
    """从 build_sparam_dataset 的 ok 信封派生 spec（n_inputs/n_outputs 自动）。

    over 透传 MLPSpec 其余字段（hidden/epochs/lr/...）。信封不 ok 或缺
    键抛 ValueError（编程错误面；数据条件面错误由 fit/predict 信封承载）。
    """
    if not (isinstance(dataset, Mapping) and dataset.get("ok") is True):
        raise ValueError("dataset 需为 build_sparam_dataset 的 ok 信封")
    n_inputs = len(dataset["param_names"])
    n_outputs = int(dataset["n_outputs"])
    return MLPSpec(n_inputs=n_inputs, n_outputs=n_outputs, **over)


# ─── 数据集构建器（(params, sparams 频响) 对齐） ─────────────────────────────


def _curve_to_re_im(value: Any, n_grid: int, where: str) -> tuple[np.ndarray, np.ndarray]:
    """单样本单通道曲线值 → (re, im) 实数组（结构违例抛 ValueError）。"""
    if isinstance(value, Mapping):
        re = np.asarray(value.get("re"), dtype=np.float64)
        im = np.asarray(value.get("im"), dtype=np.float64)
        if re.shape != (n_grid,) or im.shape != (n_grid,):
            raise ValueError(
                f"{where}: re/im 长度须为 {n_grid}"
                f"（得到 re={re.shape} im={im.shape}）")
        return re, im
    arr = np.asarray(value, dtype=complex)
    if arr.ndim != 1 or arr.shape != (n_grid,):
        raise ValueError(
            f"{where}: 曲线长度须为 {n_grid}（得到 shape={arr.shape}）")
    return np.real(arr), np.imag(arr)


def build_sparam_dataset(
    samples: Sequence[Mapping[str, Any]],
    *,
    freqs_hz: Sequence[float],
    curve_keys: Sequence[str] | None = None,
    param_names: Sequence[str] | None = None,
) -> dict[str, Any]:
    """把 (params, curves) 样本集对齐为 X/Y 数据阵（ok/error 信封）。

    Args:
        samples: 每项 ``{"params": {名: 数值}, "curves": {通道: 复数序列
            或 {"re": [...], "im": [...]}}}``；所有样本 param 键集与
            curves 键集必须一致（结构违例→error 信封点名）。
        freqs_hz: 共享频栅（显式共享，不静默插值；长度=每通道点数 T）。
        curve_keys: 输出通道序（缺省 sorted）；输出列序=通道 sorted 序、
            每通道先 re 后 im 各 T 列。
        param_names: 输入列序（缺省 sorted；显式给定时须与样本键集一致）。

    Returns:
        ok 信封：``{"ok": True, "freqs_hz", "n_grid", "param_names",
        "channels", "channel_offsets", "n_outputs", "n_samples",
        "n_dropped", "dropped", "X", "Y"}``（X/Y 为 float 嵌套 list，
        JSON 可序列化）；error 信封：``{"ok": False, "errors": [...]}``。
        NaN/±Inf 参数或曲线值整点丢弃（不进 X/Y），dropped 记原索引与
        原因（dataset_service n_nonfinite_skipped 同口径）。
    """
    freqs = np.asarray(freqs_hz, dtype=np.float64)
    if freqs.ndim != 1 or freqs.size < 1 or not np.all(np.isfinite(freqs)):
        return {"ok": False, "errors": [
            f"freqs_hz 须为一维非空有限数组（得到 shape={freqs.shape}）"]}
    n_grid = int(freqs.size)
    if not samples:
        return {"ok": False, "errors": ["samples 为空：至少需要 1 个样本"]}
    for idx, s in enumerate(samples):
        if not (isinstance(s, Mapping) and isinstance(s.get("params"), Mapping)
                and isinstance(s.get("curves"), Mapping)):
            return {"ok": False, "errors": [
                f"样本 {idx} 结构违例：需含 params/curves 两个 dict"]}

    keys_all = {k for s in samples for k in s["curves"]}
    for idx, s in enumerate(samples):
        missing = keys_all - set(s["curves"])
        if missing:
            return {"ok": False, "errors": [
                f"样本 {idx} curves 键集不一致：缺 {sorted(missing)}"]}

    pnames = sorted({k for s in samples for k in s["params"]}) \
        if param_names is None else list(param_names)
    for idx, s in enumerate(samples):
        if set(s["params"]) != set(pnames):
            return {"ok": False, "errors": [
                f"样本 {idx} params 键集 {sorted(s['params'])} 与 "
                f"param_names {sorted(pnames)} 不一致"]}
    if not pnames:
        return {"ok": False, "errors": ["param_names 为空"]}

    channels = sorted(keys_all) if curve_keys is None else list(curve_keys)
    if not channels:
        return {"ok": False, "errors": ["curve_keys 为空"]}
    offsets = {c: {"re_offset": 2 * i * n_grid, "im_offset": (2 * i + 1) * n_grid}
               for i, c in enumerate(channels)}
    n_outputs = 2 * len(channels) * n_grid

    x_rows: list[list[float]] = []
    y_rows: list[list[float]] = []
    dropped: list[dict[str, Any]] = []
    for idx, s in enumerate(samples):
        reason: str | None = None
        row_x: list[float] = []
        for name in pnames:
            try:
                v = float(s["params"][name])
            except (TypeError, ValueError) as exc:
                return {"ok": False, "errors": [
                    f"样本 {idx} 参数 {name} 非数值化失败: {exc}"]}
            if not np.isfinite(v):
                reason = f"参数 {name} 非有限（{s['params'][name]!r}）"
                break
            row_x.append(v)
        if reason is None:
            row_y: list[float] = []
            for c in channels:
                try:
                    re, im = _curve_to_re_im(
                        s["curves"][c], n_grid, f"样本 {idx} 通道 {c}")
                except (TypeError, ValueError) as exc:
                    reason = str(exc)
                    break
                if not (np.all(np.isfinite(re)) and np.all(np.isfinite(im))):
                    reason = f"通道 {c} 含非有限值"
                    break
                row_y.extend(re.tolist())
                row_y.extend(im.tolist())
        if reason is not None:
            dropped.append({"index": idx, "reason": reason})
            continue
        x_rows.append(row_x)
        y_rows.append(row_y)
    if not x_rows:
        return {"ok": False, "errors": [
            "全部样本被丢弃（非有限值），无可训练数据集",
            *[d["reason"] for d in dropped]],
            "n_dropped": len(dropped), "dropped": dropped}
    return {
        "ok": True,
        "freqs_hz": freqs.tolist(),
        "n_grid": n_grid,
        "param_names": list(pnames),
        "channels": channels,
        "channel_offsets": offsets,
        "n_outputs": n_outputs,
        "n_samples": len(x_rows),
        "n_dropped": len(dropped),
        "dropped": dropped,
        "X": x_rows,
        "Y": y_rows,
    }


# ─── 切分与 LOO 口径（纯函数） ───────────────────────────────────────────────


def split_train_val(
    n: int, *, val_frac: float = 0.2, seed: int = 0,
) -> tuple[np.ndarray, np.ndarray]:
    """确定性 train/val 下标切分（default_rng(seed) 置换后排序）。

    n=1 时 val 为空数组（单点全训）；n≥2 时 val 至少 1 点且 train ≥1。
    """
    if n < 1:
        raise ValueError(f"n 必须 ≥1（得到 {n}）")
    if not (0.0 <= val_frac < 1.0):
        raise ValueError(f"val_frac 须在 [0, 1)（得到 {val_frac}）")
    perm = np.random.default_rng(seed).permutation(n)
    n_val = 0 if val_frac == 0.0 else max(1, round(val_frac * n))
    n_val = min(n_val, n - 1)
    return np.sort(perm[n_val:]), np.sort(perm[:n_val])


def loo_folds(n: int) -> list[tuple[np.ndarray, np.ndarray]]:
    """LOO 折划分（纯函数）：n 个 (train_idx, val_idx)，val 恒单点。"""
    if n < 2:
        raise ValueError(f"LOO 需要 n≥2（得到 {n}）")
    folds: list[tuple[np.ndarray, np.ndarray]] = []
    for i in range(n):
        train = np.array([j for j in range(n) if j != i], dtype=np.int64)
        folds.append((train, np.array([i], dtype=np.int64)))
    return folds


def aggregate_loo_metrics(
    y_true: np.ndarray, y_pred: np.ndarray,
) -> dict[str, Any]:
    """LOO/holdout 指标聚合（纯函数，列口径，单位无关）。

    返回 rmse_per_column/rmse_total 与逐列 Pearson ρ；常数列（std=0）
    的 ρ 如实记 None（不伪造 0/1）。#118 对拍：测试用手工双重循环钉。
    """
    t = np.asarray(y_true, dtype=np.float64)
    p = np.asarray(y_pred, dtype=np.float64)
    if t.shape != p.shape or t.ndim != 2 or t.shape[0] < 1:
        raise ValueError(
            f"y_true/y_pred 须为同形 (n≥1, m) 二维阵（得到 {t.shape} vs {p.shape}）")
    err = p - t
    rmse_cols = np.sqrt(np.mean(err * err, axis=0))
    rho_cols: list[float | None] = []
    for j in range(t.shape[1]):
        tc, pc = t[:, j], p[:, j]
        if np.std(tc) == 0.0 or np.std(pc) == 0.0:
            rho_cols.append(None)
            continue
        rho_cols.append(float(np.corrcoef(tc, pc)[0, 1]))
    return {
        "n_folds": int(t.shape[0]),
        "rmse_per_column": [float(v) for v in rmse_cols],
        "rmse_total": float(np.sqrt(np.mean(err * err))),
        "pearson_rho_per_column": rho_cols,
    }


# ─── 纯 numpy 前向（torch 前向的独立裁判，#118） ────────────────────────────


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-z))


def _activation_numpy(z: np.ndarray, name: str) -> np.ndarray:
    """激活的 numpy 实现（与 torch 算子逐式对照，见模块 docstring）。"""
    if name == "tanh":
        return np.tanh(z)
    if name == "relu":
        return np.maximum(z, 0.0)
    if name == "silu":
        return z * _sigmoid(z)
    if name == "gelu":
        # exact erf 形式 = torch nn.GELU 缺省 approximate="none"
        return 0.5 * z * (1.0 + erf(z / np.sqrt(2.0)))
    raise ValueError(f"未知激活 {name!r}，可用: {ACTIVATIONS}")


def mlp_forward_numpy(
    state: Mapping[str, Any], spec: MLPSpec, xn: np.ndarray,
) -> np.ndarray:
    """纯 numpy MLP 前向（权重来自 state；**不经 torch**）。

    定位：torch 前向的独立对拍裁判（#118，两条无共享代码路径）+ 无
    torch 环境的部署面前置（state 为纯 list 权重，可 JSON 携带）。
    隐层按 spec.activation，输出层线性（re_im 双头）。结构违例抛
    ValueError（输入维/层宽/激活名不匹配）。
    """
    if not isinstance(state, Mapping):
        raise ValueError("state 须为 Mapping（含 layers 列表）")
    layers = state.get("layers")
    if not (isinstance(layers, list) and layers):
        raise ValueError("state 须为含非空 layers 列表的 dict")
    a = np.asarray(xn, dtype=np.float64)
    one = a.ndim == 1
    if one:
        a = a[None, :]
    if a.shape[-1] != spec.n_inputs:
        raise ValueError(
            f"输入维 {a.shape[-1]} 与 spec.n_inputs={spec.n_inputs} 不一致")
    for idx, layer in enumerate(layers):
        w = np.asarray(layer["W"], dtype=np.float64)
        b = np.asarray(layer["b"], dtype=np.float64)
        if w.ndim != 2 or w.shape[0] != b.shape[0] or w.shape[1] != a.shape[-1]:
            raise ValueError(
                f"层 {idx} 形状违例：W={w.shape} b={b.shape} 输入={a.shape}")
        a = a @ w.T + b
        if idx < len(layers) - 1:
            a = _activation_numpy(a, spec.activation)
    if a.shape[-1] != spec.n_outputs:
        raise ValueError(
            f"输出维 {a.shape[-1]} 与 spec.n_outputs={spec.n_outputs} 不一致")
    return a[0] if one else a


# ─── torch 懒加载训练/推理面 ────────────────────────────────────────────────


def _load_torch() -> Any:
    """torch 懒加载（函数体内 import；缺失返回 None，不抛裸错）。"""
    try:
        import torch
    except ImportError:
        return None
    return torch


def torch_available() -> bool:
    """torch 可用性探测（true=训练/推理/LOO 面可用）。"""
    return _load_torch() is not None


def _unavailable_envelope(action: str) -> dict[str, Any]:
    """torch 缺失的结构化 unavailable 信封（如实，不抛裸错）。"""
    return {
        "ok": False,
        "errors": [
            f"neural_surrogate.{action}: torch 未安装（可选依赖）——"
            f"安装口径：{TORCH_INSTALL_HINT}"],
        "unavailable": True,
        "install_hint": TORCH_INSTALL_HINT,
    }


def _dataset_arrays(dataset: Mapping[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    """ok 数据集信封 → (X, Y) 数组（非 ok/缺键抛 ValueError）。"""
    if not (isinstance(dataset, Mapping) and dataset.get("ok") is True):
        raise ValueError("dataset 需为 build_sparam_dataset 的 ok 信封")
    x = np.asarray(dataset["X"], dtype=np.float64)
    y = np.asarray(dataset["Y"], dtype=np.float64)
    if x.ndim != 2 or y.ndim != 2 or x.shape[0] != y.shape[0] or x.shape[0] < 1:
        raise ValueError("dataset X/Y 形状违例（需同行数非空二维阵）")
    return x, y


def _error_envelope(action: str, errors: Sequence[str]) -> dict[str, Any]:
    """数据/规格条件面错误信封（核心面自定义同形 dict）。"""
    return {"ok": False, "errors": [str(e) for e in errors], "action": action}


def _build_torch_mlp(torch: Any, spec: MLPSpec) -> tuple[Any, list[Any]]:
    """按 spec 构建双头 MLP（float64；返回 (Sequential, Linear 列表)）。"""
    acts = {"tanh": torch.nn.Tanh, "relu": torch.nn.ReLU,
            "silu": torch.nn.SiLU, "gelu": torch.nn.GELU}
    blocks: list[Any] = []
    linears: list[Any] = []
    d = int(spec.n_inputs)
    for h in spec.hidden:
        lin = torch.nn.Linear(d, int(h), dtype=torch.float64)
        linears.append(lin)
        blocks.extend([lin, acts[spec.activation]()])
        d = int(h)
    out = torch.nn.Linear(d, int(spec.n_outputs), dtype=torch.float64)
    linears.append(out)
    blocks.append(out)
    return torch.nn.Sequential(*blocks), linears


def _state_from_linears(torch: Any, linears: list[Any]) -> dict[str, Any]:
    """Linear 权重 → JSON 可序列化 state（list 嵌套，float64 精度）。"""
    return {"layers": [
        {"W": lin.weight.detach().numpy().tolist(),
         "b": lin.bias.detach().numpy().tolist()}
        for lin in linears]}


def _load_state_into_linears(
    torch: Any, linears: list[Any], state: Mapping[str, Any],
) -> None:
    """state 权重回载（copy_ 就位，无随机性——predict 不依赖 seed）。"""
    layers = state["layers"]
    if len(layers) != len(linears):
        raise ValueError(
            f"state 层数 {len(layers)} 与架构层数 {len(linears)} 不一致")
    for lin, layer in zip(linears, layers, strict=True):
        with torch.no_grad():  # 叶子参数 in-place 写须在 no_grad 下（copy_ 守卫）
            lin.weight.copy_(torch.tensor(layer["W"], dtype=torch.float64))
            lin.bias.copy_(torch.tensor(layer["b"], dtype=torch.float64))


def _train_torch_mlp(
    torch: Any, xn: np.ndarray, yn: np.ndarray, spec: MLPSpec,
) -> tuple[Any, list[Any], list[float]]:
    """全批 Adam 训练（固定 seed/单线程/无洗牌 → 同机逐位可复现）。"""
    torch.manual_seed(int(spec.seed))
    torch.set_num_threads(1)
    model, linears = _build_torch_mlp(torch, spec)
    opt = torch.optim.Adam(
        model.parameters(), lr=float(spec.lr),
        weight_decay=float(spec.weight_decay))
    xt = torch.tensor(xn, dtype=torch.float64)
    yt = torch.tensor(yn, dtype=torch.float64)
    hist: list[float] = []
    for _ in range(int(spec.epochs)):
        opt.zero_grad()
        loss = torch.nn.functional.mse_loss(model(xt), yt)
        loss.backward()
        opt.step()
        hist.append(float(loss.detach()))
    model.eval()
    return model, linears, hist


def _channel_rmse(
    y_true_raw: np.ndarray, y_pred_raw: np.ndarray,
    channels: Sequence[str], offsets: Mapping[str, Mapping[str, int]],
    n_grid: int,
) -> dict[str, float]:
    """逐复数通道物理量纲 RMSE（re/im 合成复差后取模，#121 单位显式）。"""
    out: dict[str, float] = {}
    for c in channels:
        r0 = int(offsets[c]["re_offset"])
        i0 = int(offsets[c]["im_offset"])
        diff = ((y_pred_raw[:, r0:r0 + n_grid] - y_true_raw[:, r0:r0 + n_grid])
                + 1j * (y_pred_raw[:, i0:i0 + n_grid]
                        - y_true_raw[:, i0:i0 + n_grid]))
        out[c] = float(np.sqrt(np.mean(np.abs(diff) ** 2)))
    return out


def fit_neural_surrogate(
    dataset: Mapping[str, Any], spec: MLPSpec,
    *, val_frac: float = 0.2, split_seed: int | None = None,
) -> dict[str, Any]:
    """拟合神经代理（torch 懒加载；返回 fit 信封，predict_mlp 直接消费）。

    流程：torch 探测（缺失→unavailable 信封）→ spec/数据校验（违例→
    error 信封）→ 确定性 train/val 切分 → 归一化窗口**只 fit 训练行**
    （泄漏防线）→ 全批 Adam 训练 → 权重落 state（纯 list）→ 物理
    量纲 train/val 指标（逐复数通道 RMSE）。

    信封关键字段：``state``（权重）、``norm_x``/``norm_y``（窗口）、
    ``spec``、``param_names``/``channels``/``freqs_hz``/``channel_offsets``
    （predict 所需全部上下文）、``loss_history``、``train``/``val``。
    """
    torch = _load_torch()
    if torch is None:
        return _unavailable_envelope("fit_neural_surrogate")
    spec_errors = validate_mlp_spec(spec)
    if spec_errors:
        return _error_envelope("fit_neural_surrogate", spec_errors)
    try:
        x, y = _dataset_arrays(dataset)
    except ValueError as exc:
        return _error_envelope("fit_neural_surrogate", [str(exc)])
    if spec.n_inputs != x.shape[1]:
        return _error_envelope("fit_neural_surrogate", [
            f"spec.n_inputs={spec.n_inputs} 与数据列数 {x.shape[1]} 不一致"])
    if spec.n_outputs != y.shape[1]:
        return _error_envelope("fit_neural_surrogate", [
            f"spec.n_outputs={spec.n_outputs} 与数据列数 {y.shape[1]} 不一致"])

    n = x.shape[0]
    train_idx, val_idx = split_train_val(
        n, val_frac=val_frac,
        seed=spec.seed if split_seed is None else int(split_seed))
    norm_x = fit_normalization(x[train_idx], "minmax")
    norm_y = fit_normalization(y[train_idx], "minmax")

    model, linears, hist = _train_torch_mlp(
        torch, apply_normalization(norm_x, x[train_idx]),
        apply_normalization(norm_y, y[train_idx]), spec)
    state = _state_from_linears(torch, linears)

    channels = list(dataset["channels"])
    offsets = dataset["channel_offsets"]
    n_grid = int(dataset["n_grid"])
    with torch.no_grad():
        pred_train_raw = undo_normalization(
            norm_y, model(torch.tensor(
                apply_normalization(norm_x, x[train_idx]),
                dtype=torch.float64)).numpy())
        val_block: dict[str, Any] | None = None
        if val_idx.size > 0:
            pred_val_raw = undo_normalization(
                norm_y, model(torch.tensor(
                    apply_normalization(norm_x, x[val_idx]),
                    dtype=torch.float64)).numpy())
            val_block = {
                "n_val": int(val_idx.size),
                "rmse_per_channel": _channel_rmse(
                    y[val_idx], pred_val_raw, channels, offsets, n_grid),
            }

    return {
        "ok": True,
        "kind": "neural_surrogate_mlp",
        "output_head": OUTPUT_HEAD,
        "spec": mlp_spec_to_dict(spec),
        "state": state,
        "norm_x": norm_x.to_dict(),
        "norm_y": norm_y.to_dict(),
        "param_names": list(dataset["param_names"]),
        "channels": channels,
        "freqs_hz": list(dataset["freqs_hz"]),
        "channel_offsets": {c: dict(offsets[c]) for c in channels},
        "n_grid": n_grid,
        "n_train": int(train_idx.size),
        "n_val": int(val_idx.size),
        "train": {
            "rmse_per_channel": _channel_rmse(
                y[train_idx], pred_train_raw, channels, offsets, n_grid),
        },
        "val": val_block,
        "loss_history": hist,
    }


def predict_mlp(
    fit_env: Mapping[str, Any], params: Mapping[str, float],
) -> dict[str, Any]:
    """神经代理推理（torch 懒加载；fit 信封全上下文自足）。

    返回 ok 信封 ``{"ok": True, "curves": {通道: {"re": [...], "im":
    [...]}} , "freqs_hz", "channels"}``——re/im 为物理量纲（逆归一化
    后），复数 = re + 1j·im 由消费方合成。torch 缺失→unavailable 信封；
    fit 信封形状违例/参数缺名→error 信封点名。
    """
    torch = _load_torch()
    if torch is None:
        return _unavailable_envelope("predict_mlp")
    required = ("state", "norm_x", "norm_y", "param_names", "spec")
    if not (isinstance(fit_env, Mapping) and fit_env.get("ok") is True
            and fit_env.get("kind") == "neural_surrogate_mlp"
            and all(k in fit_env for k in required)):
        return _error_envelope("predict_mlp", [
            "fit_env 需为 fit_neural_surrogate 的 ok 信封"
            f"（缺键：{[k for k in required if k not in fit_env]}）"])
    missing = [p for p in fit_env["param_names"] if p not in params]
    if missing:
        return _error_envelope("predict_mlp", [
            f"params 缺名: {missing}（需要 {list(fit_env['param_names'])}）"])
    try:
        spec = mlp_spec_from_dict(fit_env["spec"])
        norm_x = NormalizationSpec.from_dict(fit_env["norm_x"])
        norm_y = NormalizationSpec.from_dict(fit_env["norm_y"])
    except (KeyError, TypeError, ValueError) as exc:
        return _error_envelope("predict_mlp", [f"fit_env 字段违例: {exc}"])
    if spec.n_inputs != len(fit_env["param_names"]):
        return _error_envelope("predict_mlp", [
            f"fit_env spec.n_inputs={spec.n_inputs} 与 param_names 数 "
            f"{len(fit_env['param_names'])} 不一致"])

    x = np.array([[float(params[p]) for p in fit_env["param_names"]]])
    xn = apply_normalization(norm_x, x)
    model, linears = _build_torch_mlp(torch, spec)
    _load_state_into_linears(torch, linears, fit_env["state"])
    model.eval()
    with torch.no_grad():
        yn = model(torch.tensor(xn, dtype=torch.float64)).numpy()
    y = undo_normalization(norm_y, yn)[0]

    n_grid = int(fit_env["n_grid"])
    curves = {
        c: {"re": y[int(o["re_offset"]):int(o["re_offset"]) + n_grid].tolist(),
            "im": y[int(o["im_offset"]):int(o["im_offset"]) + n_grid].tolist()}
        for c, o in fit_env["channel_offsets"].items()}
    return {
        "ok": True,
        "kind": "neural_surrogate_mlp",
        "curves": curves,
        "freqs_hz": list(fit_env["freqs_hz"]),
        "channels": list(fit_env["channels"]),
    }


def loo_evaluate_mlp(
    dataset: Mapping[str, Any], spec: MLPSpec, *, max_folds: int | None = None,
) -> dict[str, Any]:
    """LOO 评估（torch 懒加载；逐折重训、归一化只 fit 折内训练行）。

    返回 ok 信封：``loo``（aggregate_loo_metrics 列口径聚合）+
    ``per_fold``（逐折逐通道物理量纲 RMSE）。``max_folds`` 限折数
    （成本守卫，前 max_folds 折）；torch 缺失→unavailable 信封。
    """
    torch = _load_torch()
    if torch is None:
        return _unavailable_envelope("loo_evaluate_mlp")
    spec_errors = validate_mlp_spec(spec)
    if spec_errors:
        return _error_envelope("loo_evaluate_mlp", spec_errors)
    try:
        x, y = _dataset_arrays(dataset)
    except ValueError as exc:
        return _error_envelope("loo_evaluate_mlp", [str(exc)])
    if spec.n_inputs != x.shape[1] or spec.n_outputs != y.shape[1]:
        return _error_envelope("loo_evaluate_mlp", [
            f"spec 维数（{spec.n_inputs}/{spec.n_outputs}）与数据"
            f"（{x.shape[1]}/{y.shape[1]}）不一致"])
    n = x.shape[0]
    if n < 2:
        return _error_envelope("loo_evaluate_mlp", [
            f"LOO 需要 n≥2 个样本（得到 {n}）"])
    folds = loo_folds(n)
    if max_folds is not None:
        folds = folds[:max(0, int(max_folds))]
    if not folds:
        return _error_envelope("loo_evaluate_mlp", [
            f"max_folds 需 ≥1（得到 {max_folds}）"])

    channels = list(dataset["channels"])
    offsets = dataset["channel_offsets"]
    n_grid = int(dataset["n_grid"])
    preds = np.zeros_like(y)
    per_fold: list[dict[str, Any]] = []
    for train_idx, val_idx in folds:
        norm_x = fit_normalization(x[train_idx], "minmax")
        norm_y = fit_normalization(y[train_idx], "minmax")
        model, _linears, _hist = _train_torch_mlp(
            torch, apply_normalization(norm_x, x[train_idx]),
            apply_normalization(norm_y, y[train_idx]), spec)
        with torch.no_grad():
            yn = model(torch.tensor(
                apply_normalization(norm_x, x[val_idx]),
                dtype=torch.float64)).numpy()
        row = undo_normalization(norm_y, yn)[0]
        preds[val_idx[0]] = row
        per_fold.append({
            "index": int(val_idx[0]),
            "rmse_per_channel": _channel_rmse(
                y[val_idx], row[None, :], channels, offsets, n_grid),
        })
    eval_idx = np.array([int(f[1][0]) for f in folds], dtype=np.int64)
    return {
        "ok": True,
        "kind": "neural_surrogate_mlp",
        "n_folds": len(folds),
        "loo": aggregate_loo_metrics(y[eval_idx], preds[eval_idx]),
        "per_fold": per_fold,
        "spec": mlp_spec_to_dict(spec),
        "param_names": list(dataset["param_names"]),
        "channels": channels,
    }


def build_cnn_surrogate(spec: CNNSpec) -> dict[str, Any]:
    """CNN 档入口（**占位**）：结构化 not_implemented 信封，不抛裸错。

    Alpha-RF 足迹图输入面（足印 rows×cols × 频点）留 spec 位置，实现
    挂账主代（Alpha-RF 化用批次）——调用方按 ``not_implemented`` 键
    分支，不得把本档当可用能力。
    """
    return {
        "ok": False,
        "errors": [
            "neural_surrogate.build_cnn_surrogate: CNN 档未实现"
            "（Alpha-RF 足迹图输入，挂账主代）——spec 已声明，实现后补"],
        "not_implemented": True,
        "spec": {
            "n_freq": spec.n_freq,
            "footprint_rows": spec.footprint_rows,
            "footprint_cols": spec.footprint_cols,
        },
    }
