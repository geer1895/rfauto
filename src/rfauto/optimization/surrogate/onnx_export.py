"""代理产物 ONNX 标准化导出内核（T-N20，aurora_n W3）。

一句话：把已拟合的 torch 系代理（fno/deep_ensemble/siren 三键）导出为
ONNX 模型文件，供 playground/远程消费脱离 python 训练栈推理；其余键
（numpy/sklearn 系与 torch 未覆盖键）**不支持导出**并显式报错列支持面
（不走静默降级，T-N17 botorch 家法）。

导出 API 口径（2026-10-29 torch 2.14.0+cpu / onnx 1.23.2 / onnxruntime
1.31.1 / onnxscript 0.7.2 实测，runs/aurora_n/w3_tn20/）：

- **导出器=dynamo 通道（torch>=2.9 缺省新导出器）+ opset 18**：fno 谱层
  ``torch.fft.rfft/irfft`` 仅此路径可导——legacy TorchScript 导出器对
  ``aten::fft_rfft`` 全 opset ``UnsupportedOperatorError``（实测登记）；
  torch 过旧（无 dynamo 形参）显式报错，不做静默降级；
- **fno 谱卷积层按导出等价形态重写**：原始前向的「zeros+复 slice_scatter
  赋值」与「复 einsum」均无 ONNX 分解（实测：slice_scatter 复 dtype 不支
  持自动微分分解、aten.einsum 复操作数无注册分解）——导出图改用数学恒等
  的实域形态：复 einsum 按乘法分配律拆 re/im 实 einsum 对 + 频域尾部补零
  移到实域 cat + ``torch.complex`` 单点组装。网络权重**共享原模块参数对象
  （零拷贝）**，恒等性由导出-回代对拍门实测证明（float32 量化误差量级
  ~1e-7，见 PARITY_RTOL/PARITY_ATOL 容差来源注记）；
- **归一化进图**：bounds 归一化（fno/deep_ensemble 的 [0,1] 参数归一、
  siren 的 [-1,1] 坐标归一）打包进导出 wrapper（buffer 常量），ONNX 输入
  =**原始单位**的参数/坐标向量，与 ``model.predict*`` 语义逐位同构——
  消费侧无需复刻预处理；
- **deep_ensemble 输出=(2, T) [均值; σ]**：成员等权均值 + 成员间总体
  std（``correction=0`` ≡ ``np.std(ddof=0)``，与
  ``predict_curve_with_std`` 同口径）；成员仅 1 席时 σ 恒 0（同内核
  uncertainty 语义）；仅支持成员全为 fno 的集成（成员须为 torch 曲线
  代理，非 fno 成员显式报错）；
- **siren 复数场**：复数模式导出 2 通道输出 = re/im（论文 §4.3 双通道
  口径），predict 的 python complex 由消费侧 ``complex(out[0], out[1])``
  重组；
- **字节确定性（红线钉）**：导出器原生序列化含 protobuf map 字段序不定
  （同 proto 两次写出字节漂移、载入后 proto 语义相等——实测登记），
  落盘前 ``onnx.load`` + ``SerializeToString(deterministic=True)`` 规范
  化 → 同权重同输入两跑 sha256 一致；dynamo 导出器的外部数据文件
  （``<path>.data``）随规范化内联，产物**单文件自包含**（playground/
  远程消费只带一个 .onnx）；
- **依赖面**：导出需 torch + onnx + onnxscript（dynamo 导出器运行时），
  全部 lazy import（顶层零重依赖，T-N17 家法）；onnxruntime 仅
  导出-回代对拍（verify）消费，缺席=对拍跳过并如实注记，不阻塞导出。

数值纪律（铁律 7）：本模块不产生物理数字——导出图的数值=已拟合权重的
确定性函数；对拍 max_abs_diff 是两条浮点路径的实测差，非新物理数字。
既有路径零改动：本模块只读模型对象（``_net``/``bounds``/``_freq_norm``/
``_bounds_eff`` 等 fit 产物），不改任何拟合/预测内核。

用法::

    from rfauto.optimization.surrogate.onnx_export import export_onnx

    model = surrogate_registry.create("fno", config={...}); model.fit(samples)
    res = export_onnx(model, "runs/xxx/fno.onnx")
    # res: {"ok", "kind", "path", "sha256", "opset", "input", "output",
    #       "verified", "max_abs_diff", ...}
"""

from __future__ import annotations

import contextlib
import hashlib
from pathlib import Path
from typing import Any

import numpy as np

__all__ = [
    "DEFAULT_OPSET",
    "PARITY_ATOL",
    "PARITY_RTOL",
    "SUPPORTED_KINDS",
    "export_onnx",
]

#: 支持面（torch 系三键；其余键显式报错列本清单）
SUPPORTED_KINDS = ("fno", "deep_ensemble", "siren")

#: 缺省 opset（实测口径：fno 谱层 DFT 分解在 dynamo+18 可导）
DEFAULT_OPSET = 18

#: 导出-回代对拍容差（预声明）：float32 权重 + ONNX DFT/目标算子分解与
#: torch 原生路径的浮点舍入差异，实测量级 ~1e-7（本席单测档）；
#: rtol=1e-4/atol=1e-5 留两个量级余量，实测 max_abs_diff 随行透出。
PARITY_RTOL = 1e-4
PARITY_ATOL = 1e-5


def _ensure_torch():
    """torch lazy import（可选 extra 缺失显式报错，fno 家法文案同源）。"""
    try:
        import torch
        return torch
    except ImportError as exc:
        raise RuntimeError(
            "ONNX 导出需要 torch：pip install rfauto[torch] 或 "
            "pip install torch --index-url "
            "https://download.pytorch.org/whl/cpu") from exc


def _ensure_onnx():
    """onnx lazy import（T-N20 新 extra；缺席=导出面缺席+诚实报错）。"""
    try:
        import onnx
        return onnx
    except ImportError as exc:
        raise RuntimeError(
            "ONNX 导出需要 onnx/onnxscript：pip install rfauto[onnx]（"
            "onnxruntime 可选，仅导出-回代对拍消费）") from exc


def _ensure_onnxruntime():
    """onnxruntime lazy import（仅 verify 消费；缺席返回 None 不抛）。"""
    try:
        import onnxruntime
        return onnxruntime
    except ImportError:
        return None


def _check_fitted(model: Any) -> str:
    """kind 提取 + 支持面判定 + 拟合态守卫（三键共用前置）。"""
    kind = str(getattr(model, "KIND", "") or "")
    if kind not in SUPPORTED_KINDS:
        raise ValueError(
            f"ONNX 导出不支持代理 kind={kind!r}——当前支持面（torch 系"
            f"三键）: {', '.join(SUPPORTED_KINDS)}；其余键（numpy/"
            "sklearn 系与 torch 未覆盖键）不支持导出，消费请走本仓 "
            "python 推理路径（surrogate_registry.create + predict）")
    if not getattr(model, "fitted", False):
        raise RuntimeError("代理未拟合，先调用 fit() 再导出")
    return kind


def _bounds_tensors(names: list[str], bounds: dict[str, tuple[float, float]],
                    torch: Any) -> tuple[Any, Any]:
    """bounds → (lo, hi) float32 张量（names 序）。"""
    lo = torch.tensor([float(bounds[n][0]) for n in names],
                      dtype=torch.float32)
    hi = torch.tensor([float(bounds[n][1]) for n in names],
                      dtype=torch.float32)
    return lo, hi


# ─── fno：谱卷积层导出等价重写（复 einsum → 实 einsum 对） ───────────────────


def _fno_export_net(net: Any, torch: Any) -> Any:
    """_FNONet → 导出等价网络（权重共享零拷贝，前向实域化）。

    与 fno._FNONet.forward 逐算子对账（fno.py :149-153）：
    lift → N×(rfft → 截断×复权重 → irfft + pointwise → gelu) → project；
    唯一差异=Fourier 层频域块的写法（原始 zeros+slice_scatter+复 einsum
    → 实 einsum 对+cat 补零+torch.complex），数学恒等（复乘分配律）。
    """
    from torch import nn

    class _FnoSpectralLayerExport(nn.Module):
        """_FourierLayer 导出等价形态（weights/pointwise 共享原对象）。"""

        def __init__(self, layer: Any) -> None:
            super().__init__()
            self.weights = layer.weights        # (m, width, width) cfloat
            self.pointwise = layer.pointwise
            self.n_modes = int(layer.weights.shape[0])

        def forward(self, x: Any) -> Any:  # x: (B, T, C)
            t = x.shape[1]
            x_ft = torch.fft.rfft(x, dim=1)                  # (B, T//2+1, C)
            head = x_ft[:, :self.n_modes, :]
            wr, wi = self.weights.real, self.weights.imag
            re = (torch.einsum("bfi,fio->bfo", head.real, wr)
                  - torch.einsum("bfi,fio->bfo", head.imag, wi))
            im = (torch.einsum("bfi,fio->bfo", head.real, wi)
                  + torch.einsum("bfi,fio->bfo", head.imag, wr))
            n_tail = x_ft.shape[1] - self.n_modes
            re = torch.cat([re, torch.zeros(x.shape[0], n_tail, re.shape[2])],
                           dim=1)
            im = torch.cat([im, torch.zeros(x.shape[0], n_tail, im.shape[2])],
                           dim=1)
            out_ft = torch.complex(re, im)
            return nn.functional.gelu(
                torch.fft.irfft(out_ft, n=t, dim=1) + self.pointwise(x))

    class _FnoNetExport(nn.Module):
        """_FNONet 导出等价形态（lift/project 共享原对象）。"""

        def __init__(self) -> None:
            super().__init__()
            self.lift = net.lift
            self.layers = nn.ModuleList(
                _FnoSpectralLayerExport(layer) for layer in net.layers)
            self.project = net.project

        def forward(self, x: Any) -> Any:  # (B, T, n_in) → (B, T)
            h = self.lift(x)
            for layer in self.layers:
                h = layer(h)
            return self.project(h).squeeze(-1)

    return _FnoNetExport()


class _FnoCurveExport:
    """fno 导出 wrapper 工厂（归一化进图；输入原始单位参数向量）。"""

    def __call__(self, model: Any, torch: Any) -> tuple[Any, dict[str, Any]]:
        from torch import nn

        names = list(model.names)
        net = _fno_export_net(model._net, torch)
        lo, hi = _bounds_tensors(names, model.bounds, torch)
        freq = torch.as_tensor(np.asarray(model._freq_norm, dtype=np.float32))
        freq = freq.view(1, -1, 1)
        n_params = len(names)

        class _Wrapper(nn.Module):
            """params (P,) → s11_db (T,)；fno._unit_row + predict_curve 同构。"""

            def __init__(self) -> None:
                super().__init__()
                self.net = net
                self.register_buffer("lo", lo)
                self.register_buffer("hi", hi)
                self.register_buffer("freq", freq)

            def forward(self, params: Any) -> Any:
                unit = torch.clamp(
                    (params - self.lo)
                    / torch.clamp(self.hi - self.lo, min=1e-12), 0.0, 1.0)
                xx = torch.cat([
                    unit.view(1, 1, n_params).expand(
                        1, self.freq.shape[1], n_params),
                    self.freq], dim=2)
                return self.net(xx).squeeze(0)      # (T,)

        meta = {
            "param_names": names,
            "freq_ghz": [float(v) for v in model.freq_grid],
            "native_call": "predict_curve(params_dict)['s11_db']",
        }
        return _Wrapper().eval(), meta


# ─── deep_ensemble：成员等权均值+成员间 σ（(2, T)） ──────────────────────────


class _DeepEnsembleCurveExport:
    """deep_ensemble 导出 wrapper 工厂（成员全为 fno 的集成）。"""

    def __call__(self, model: Any, torch: Any) -> tuple[Any, dict[str, Any]]:
        from torch import nn

        names = list(model._bounds)
        lo, hi = _bounds_tensors(names, model._bounds, torch)
        members = [m for m, _rec in getattr(model, "_members", [])]
        if not members:
            raise RuntimeError("deep_ensemble 无幸存成员，不可导出")
        non_fno = [type(m).__name__ for m in members
                   if getattr(m, "KIND", "") != "fno"]
        if non_fno:
            raise ValueError(
                f"deep_ensemble ONNX 导出仅支持成员全为 fno 的集成，实测"
                f"含非 fno 成员: {sorted(set(non_fno))}（base_kind 换族后"
                "成员网络形态不归本席覆盖面）")
        member_nets = nn.ModuleList(
            _fno_export_net(m._net, torch) for m in members)
        freq = torch.as_tensor(
            np.asarray(members[0]._freq_norm, dtype=np.float32)).view(1, -1, 1)
        n_params = len(names)

        class _Wrapper(nn.Module):
            """params (P,) → (2, T) = [成员均值; 成员间 σ（correction=0）]。"""

            def __init__(self) -> None:
                super().__init__()
                self.member_nets = member_nets
                self.register_buffer("lo", lo)
                self.register_buffer("hi", hi)
                self.register_buffer("freq", freq)

            def forward(self, params: Any) -> Any:
                unit = torch.clamp(
                    (params - self.lo)
                    / torch.clamp(self.hi - self.lo, min=1e-12), 0.0, 1.0)
                xx = torch.cat([
                    unit.view(1, 1, n_params).expand(
                        1, self.freq.shape[1], n_params),
                    self.freq], dim=2)
                outs = torch.stack(
                    [net(xx).view(-1) for net in self.member_nets], dim=0)
                mean = outs.mean(dim=0)
                std = outs.std(dim=0, correction=0)    # ≡ np.std(ddof=0)
                return torch.stack([mean, std], dim=0)  # (2, T)

        meta = {
            "param_names": names,
            "freq_ghz": [float(v) for v in members[0].freq_grid],
            "n_members": len(members),
            "dispersion": str(model._dispersion),
            "native_call": "predict_curve_with_std(params_dict)['s11_db'/'s11_db_std']",
        }
        return _Wrapper().eval(), meta


# ─── siren：坐标归一进图（[-1,1] 域） ────────────────────────────────────────


class _SirenFieldExport:
    """siren 导出 wrapper 工厂（坐标归一进图；复数场=2 通道 re/im）。"""

    def __call__(self, model: Any, torch: Any) -> tuple[Any, dict[str, Any]]:
        from torch import nn

        keys = list(model._coord_keys)
        net = model._net
        lo, hi = _bounds_tensors(keys, model._bounds_eff, torch)
        n_coords = len(keys)

        class _Wrapper(nn.Module):
            """coords (D,) → values (n_out,)；real=(1,)，complex=(2,)=re/im。"""

            def __init__(self) -> None:
                super().__init__()
                self.net = net
                self.register_buffer("lo", lo)
                self.register_buffer("hi", hi)

            def forward(self, coords: Any) -> Any:
                unit = torch.clamp(
                    2.0 * (coords - self.lo)
                    / torch.clamp(self.hi - self.lo, min=1e-12) - 1.0,
                    -1.0, 1.0)
                return self.net(unit.view(1, n_coords)).squeeze(0)

        meta = {
            "coord_keys": keys,
            "field_key": str(model._field_key),
            "field_mode": str(model._field_mode),
            "bounds": {k: [float(v[0]), float(v[1])]
                       for k, v in model._bounds_eff.items()},
            "native_call": "predict(coord_dict)[field_key]（complex 模式="
                           "complex(out[0], out[1])）",
        }
        return _Wrapper().eval(), meta


_WRAPPER_FACTORIES = {
    "fno": _FnoCurveExport(),
    "deep_ensemble": _DeepEnsembleCurveExport(),
    "siren": _SirenFieldExport(),
}


def _example_input(model: Any, kind: str, torch: Any) -> Any:
    """示例输入（域中点；与 meta 的 param/coord 序一致，原始单位）。"""
    if kind == "fno":
        vec = [float(np.mean(model.bounds[n])) for n in model.names]
    elif kind == "deep_ensemble":
        vec = [float(np.mean(model._bounds[n])) for n in model._bounds]
    else:
        vec = [float(np.mean(model._bounds_eff[k])) for k in model._coord_keys]
    return torch.tensor(vec, dtype=torch.float32)


def _canonicalize_onnx_bytes(path: Path) -> str:
    """protobuf map 序规范化（deterministic 序列化覆写）+ sha256 落账。

    实测：导出器原生写出对同一 proto 两次字节不同（map 字段序随进程漂
    移），载入后语义相等；此处载入→``SerializeToString(deterministic=
    True)`` 覆写 → 同权重同输入两跑字节一致（验收③钉的实现位）。另：
    - dynamo 导出器会把 initializer 写成外部数据文件（``<path>.data``，
      即便小模型）——``onnx.load`` 缺省把外部数据载入 proto，规范化覆写
      后产物**单文件自包含**，原 ``<path>.data`` 成孤儿，best-effort 清除
      （#105：清除失败不阻塞导出，残留仅多一个无用文件）；
    - 节点 metadata_props 的 ``pkg.torch.onnx.stack_trace`` 内嵌导出器
      源码**行号**（诊断元数据）——本模块源码行移位即牵动全图字节（实测
      登记：权重/图逐位稳定、仅行号串变的跨代码态 sha 漂移一例），规范化
      时剥除（消费侧零影响，跨代码态 sha 稳定）。
    """
    onnx = _ensure_onnx()
    model = onnx.load(str(path))
    for node in model.graph.node:
        props = [p for p in node.metadata_props
                 if p.key == "pkg.torch.onnx.stack_trace"]
        for p in props:
            node.metadata_props.remove(p)
    data = model.SerializeToString(deterministic=True)
    with open(path, "wb") as f:
        f.write(data)
    with contextlib.suppress(OSError):
        Path(str(path) + ".data").unlink(missing_ok=True)
    return hashlib.sha256(data).hexdigest()


def _verify_backtranslate(
    model: Any, kind: str, path: Path, example: Any, torch: Any,
    meta: dict[str, Any],
) -> dict[str, Any]:
    """导出-回代对拍（验收①）：torch 原生 predict vs onnxruntime 推理。

    探针=示例点（域中点）+ bounds 角点/对称点共 5 点（siren 场=坐标域
    角点+中点）；逐点 max_abs_diff 取最大；容差 PARITY_RTOL/PARITY_ATOL
    （预声明，float32 量化误差来源见模块 docstring）。
    """
    ort = _ensure_onnxruntime()
    if ort is None:
        return {"verified": False,
                "verify_note": "onnxruntime 缺席，导出-回代对拍跳过"
                               "（pip install onnxruntime 可启用）"}

    def _probes() -> list[dict[str, float]]:
        if kind == "siren":
            bounds = model._bounds_eff
            keys = list(model._coord_keys)
        elif kind == "deep_ensemble":
            bounds = model._bounds
            keys = list(model._bounds)
        else:
            bounds = model.bounds
            keys = list(model.names)
        mid = {k: float(np.mean(bounds[k])) for k in keys}
        lo_p = {k: float(bounds[k][0]) for k in keys}
        hi_p = {k: float(bounds[k][1]) for k in keys}
        lo_mix = {k: float(bounds[k][0] + 0.25 * (bounds[k][1] - bounds[k][0]))
                  for k in keys}
        hi_mix = {k: float(bounds[k][0] + 0.75 * (bounds[k][1] - bounds[k][0]))
                  for k in keys}
        return [mid, lo_p, hi_p, lo_mix, hi_mix]

    sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    input_name = sess.get_inputs()[0].name
    max_diff = 0.0
    all_close = True
    probes = _probes()
    for probe in probes:
        if kind == "fno":
            native = np.asarray(model.predict_curve(probe)["s11_db"],
                                dtype=np.float64)
        elif kind == "deep_ensemble":
            out = model.predict_curve_with_std(probe)
            native = np.stack([
                np.asarray(out["s11_db"], dtype=np.float64),
                np.asarray(out["s11_db_std"], dtype=np.float64)])
        else:
            val = model.predict(probe)[meta["field_key"]]
            native = (np.asarray([val.real, val.imag], dtype=np.float64)
                      if isinstance(val, complex)
                      else np.asarray([float(val)], dtype=np.float64))
        vec = np.asarray([float(probe[k]) for k in (
            meta["coord_keys"] if kind == "siren" else meta["param_names"])],
            dtype=np.float32)
        got = np.asarray(sess.run(None, {input_name: vec})[0],
                         dtype=np.float64)
        diff = float(np.max(np.abs(native - got)))
        if diff > max_diff:
            max_diff = diff
        if not np.allclose(native, got, rtol=PARITY_RTOL, atol=PARITY_ATOL):
            all_close = False
    return {"verified": bool(all_close), "max_abs_diff": max_diff,
            "rtol": PARITY_RTOL, "atol": PARITY_ATOL,
            "n_probes": len(probes)}


def export_onnx(
    model: Any,
    out_path: str | Path,
    *,
    opset_version: int = DEFAULT_OPSET,
    verify: bool = True,
) -> dict[str, Any]:
    """已拟合 torch 代理 → ONNX 模型文件（T-N20 导出面单源）。

    Args:
        model: 已拟合代理（KIND ∈ SUPPORTED_KINDS；fit 产物 ``_net``/
            ``bounds``/``_freq_norm``/``_bounds_eff`` 只读消费）。
        out_path: ONNX 输出路径（父目录自动创建；落盘字节=protobuf
            deterministic 规范形态，同权重两跑 sha256 一致）。
        opset_version: ONNX opset（缺省 18；fno 谱层实测仅在 dynamo
            导出器可导，legacy 通道不做静默降级）。
        verify: 导出-回代对拍（onnxruntime 缺席=跳过并注记，不阻塞）。

    Returns:
        ``{"ok": True, "kind", "path", "sha256", "opset", "input",
        "output", "verified", ...}``——meta 键（param_names/freq_ghz/
        coord_keys/field_key/field_mode/n_members）随 kind 透出供消费侧
        复原语义。

    Raises:
        ValueError: kind 不在支持面（报错列 SUPPORTED_KINDS）；非 fno
            成员的 deep_ensemble。
        RuntimeError: 未拟合；torch/onnx 缺席；torch 无 dynamo 导出通道；
            对拍开启且实测超容差（不产出虚假 ok）。
    """
    kind = _check_fitted(model)
    torch = _ensure_torch()
    _ensure_onnx()  # 导出前置（canonicalize 也消费）
    wrapper, meta = _WRAPPER_FACTORIES[kind](model, torch)
    example = _example_input(model, kind, torch)

    out_path = Path(out_path)
    if out_path.parent != Path(""):
        out_path.parent.mkdir(parents=True, exist_ok=True)
    in_name = ("coords" if kind == "siren" else "params")
    out_name = {"fno": "s11_db", "deep_ensemble": "curve_mean_std",
                "siren": "values"}[kind]
    try:
        torch.onnx.export(
            wrapper, (example,), str(out_path),
            input_names=[in_name], output_names=[out_name],
            dynamo=True, opset_version=int(opset_version))
    except TypeError as exc:
        raise RuntimeError(
            "torch.onnx.export 无 dynamo 导出通道（torch 过旧）——fno 谱层 "
            "rfft 仅 dynamo 导出器可导（legacy 全 opset 不支持，实测登记），"
            "不做静默降级；请升级 torch>=2.9") from exc

    sha = _canonicalize_onnx_bytes(out_path)

    result: dict[str, Any] = {
        "ok": True,
        "kind": kind,
        "path": str(out_path),
        "sha256": sha,
        "opset": int(opset_version),
        "input": {"name": in_name, "dtype": "float32",
                  "shape": [len(meta.get("param_names",
                                         meta.get("coord_keys", [])))]},
        "output": {"name": out_name},
        "exporter": "dynamo",
        **{k: v for k, v in meta.items() if k != "native_call"},
        "native_call": meta.get("native_call"),
    }
    if verify:
        ver = _verify_backtranslate(model, kind, out_path, example, torch,
                                    meta)
        result.update(ver)
        if not ver.get("verified", False) and "max_abs_diff" in ver:
            raise RuntimeError(
                f"导出-回代对拍超容差（max_abs_diff={ver['max_abs_diff']}"
                f" > rtol={PARITY_RTOL}/atol={PARITY_ATOL} 口径）——onnx "
                "文件已落盘但不可信，请勿消费")
    return result
