"""numpy 系代理 ONNX 导出内核（aurora_p D5——onnx.helper 自研转换层）。

一句话：把已拟合 **numpy 系**代理（poly_ridge/huber_ridge/pod_rom/nn/
rff_gp/green_op 六键）用 ``onnx.helper`` 手写图导出为 ONNX 模型——
**零新依赖**（onnx/onnxruntime 已在 [onnx] extra 树内；sklearn-onnx 等
新包一律不引入）。torch 系三键（fno/deep_ensemble/siren）继续走
``onnx_export.export_onnx``（T-N20 路径**零变化**——本模块只读分派，
不改其任何行为，既有钉零改动全绿是本席验收门）。

覆盖面=**诚实边界表**（单源 ``coverage_table``，全 24 注册键逐键判定，
表驱动钉 tests/unit/test_onnx_numpy_export.py 消费；详版带理由的表见
runs/aurora_p/d5/COVERAGE.md）：

- **可转换（本席 builder，6 键）**：predict 数学形态 = 纯 MatMul/Gemm +
  逐元素激活（tanh/cos）+ 线性后处理（db/Max/Min）——poly_ridge/
  huber_ridge（特征展开+线性读出）、pod_rom（标量退化 1 点场+场键 POD
  基线性重构）、nn（tanh MLP 集成，**限 augmenter=polynomial_cross
  档**——wilkinson_rf 档含 core.synthesis 物理闭式 ``forward_z0``，
  图内不可表达，显式报错+指引）、rff_gp（cos 随机傅里叶特征+线性读
  出）、green_op（poly 特征/tanh MLP 头→re/im 复数重组→|S|→dB→带内
  max/min，全部标准算子）；
- **可转换未实施（3 键）**：conformal/ensemble（组合器——基础键可导出
  后即可组合）/gnn_geom（权重 predict 期 rng 生成需采样前移改造）；
- **不可转换（10 键）**：核方法 GP/Kriging 族（mt_gp/saas_gp/svgp/
  smt_kriging/smt_mfk/warped_kriging——预测含核矩阵线性求解 R⁻¹y，ONNX
  标准算子无 solve/inverse）、gbdt（ai.onnx.ml 树算子域=自定义算子面）、
  pole_residue/ngo_stamp_rf（复数 S 装配+逐频线性求解）、vf_parametric
  （迭代拟合+物理投影）、mapes_pixel_analytic（0/1 拓扑动态装配）；
- **torch 系未覆盖（2 键）**：fno_lite/deeponet（torch net 可 dynamo
  导出，但扩 SUPPORTED_KINDS 牵动既有钉文案——本席不动 torch 面，留
  后续席位扩面+金钉同笔重生成）；
- **未分类键**：后续席位新增注册键未进本表时，分派面显式报错（表驱动
  诚实边界，不静默）。

导出语义口径（与 T-N20 torch 面同哲学）：
- **输入=原始单位参数向量**（与 predict 入参同构；归一化进图）——
  poly_ridge/huber_ridge/pod_rom/rff_gp=[0,1] clip 进图、nn=无 clip 标
  准化进图（与 ``_vectorize`` 逐位同构）、green_op=[-1,1] 中心化无 clip
  （与 ``_norm_params`` 同构）；
- **输出=单张量 ``metrics``**（M,）＝predict dict 按 meta
  ``metric_names`` 序展平（green_op=2P² 交错 [max,min]；pod_rom 场键附
  ``field:<key>`` 输出（L,)）——消费侧按 meta 还原 dict；
- **字节确定性**：onnx.helper 定序构建 + ``SerializeToString(
  deterministic=True)`` 规范化（复用 T-N20 的 ``_canonicalize_onnx_bytes``
  单源）→ 同权重两跑 sha256 一致；
- **对拍**：onnxruntime 逐探针 allclose（容差同 T-N20 PARITY_RTOL/
  PARITY_ATOL）；onnxruntime 缺席=对拍跳过并如实注记（checker 仍必过，
  不阻塞导出——verify=False 时跳过对拍与 checker 无关，checker 恒跑）。

数值纪律（铁律 7）：本模块零物理数字产出——导出图数值=已拟合权重的确
定性函数；max_abs_diff 是 numpy float64 与 ONNX float32 两条浮点路径的
实测差。既有路径零改动：只读各键 fit 产物属性，不改任何拟合/预测内核。

用法::

    from rfauto.optimization.surrogate.onnx_numpy_export import (
        export_onnx_auto, export_onnx_numpy)

    m = surrogate_registry.create("poly_ridge", config={...}); m.fit(samples)
    res = export_onnx_auto(m, "runs/xxx/poly.onnx")   # 按键种类分派
    # torch 键同入口 → 既有 dynamo 路径；不可转换键显式报错列覆盖面
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from rfauto.optimization.surrogate.onnx_export import (
    DEFAULT_OPSET,
    PARITY_ATOL,
    PARITY_RTOL,
    SUPPORTED_KINDS,
    _canonicalize_onnx_bytes,
    _ensure_onnx,
    _ensure_onnxruntime,
    export_onnx,
)

__all__ = [
    "NUMPY_EXPORTABLE_KINDS",
    "NUMPY_PENDING_KINDS",
    "NUMPY_UNSUPPORTED_KINDS",
    "TORCH_UNCOVERED_KINDS",
    "classify_kind",
    "coverage_table",
    "export_onnx_auto",
    "export_onnx_numpy",
]

#: numpy 可转换键（本席 builder 面；字母序）
NUMPY_EXPORTABLE_KINDS = (
    "green_op",
    "huber_ridge",
    "nn",
    "pod_rom",
    "poly_ridge",
    "rff_gp",
)

#: 可转换但本席未实施（组合器/采样前移改造/在飞席位键）——键→原因
NUMPY_PENDING_KINDS = {
    "conformal": "组合器：predict=base.predict 委托（基础键可导出后组合），"
                 "q 仅进 uncertainty 不进 predict",
    "ensemble": "组合器：softmax 加权成员组合——成员全为可导出键后可组合",
    "gnn_geom": "形态可静态化但权重在 predict 期 rng 生成（需采样前移导出"
                "期改造）+max 池化+逐轮 concat——改造越本席边界",
    "lnn_cfc": "CfC 递归展开：predict 期步数/时窗可变（n_points/t_end 参数"
               "化，图须随步数展开定不了静态形）；同波在飞席位键——转换评"
               "估权归 LNN 交付席",
}

#: 不可转换键——键→原因（predict 数学形态决定，诚实边界）
NUMPY_UNSUPPORTED_KINDS = {
    "gbdt": "sklearn 树集成：TreeEnsembleRegressor 属 ai.onnx.ml 自定义算"
            "子域（禁 sklearn-onnx 新依赖红线，手写树遍历越界）",
    "mapes_pixel_analytic": "解析物理模型按 0/1 拓扑快照动态装配——非拟合"
                            "参数映射，图形态随拓扑离散跳变",
    "mt_gp": "多任务 GP：预测含核矩阵线性求解（R⁻¹y）——ONNX 标准算子无 "
             "solve/inverse",
    "ngo_stamp_rf": "λ̂ 物理域投影+Y(λ̂,ω) 精确装配+逐频线性求解"
                    "（solve_s_matrix 精确口径）",
    "pole_residue": "Y(λ̂,ω) 复数极点基装配+逐频复线性求解（solve_s_matrix）",
    "saas_gp": "SAAS GP：核方法后验线性求解",
    "smt_kriging": "SMT Kriging：相关向量 R⁻¹y 线性求解",
    "smt_mfk": "多保真 Kriging：核求解+逐级方差预测",
    "svgp": "变分 GP：诱导点后验含核矩阵求解",
    "vf_parametric": "迭代向量拟合+ConvexHull/λ̂ 物理域投影",
    "warped_kriging": "warping 变换+Kriging 核矩阵求解",
}

#: torch 系但 T-N20 未覆盖键（可 dynamo 导出；扩 SUPPORTED_KINDS 牵动既有
#: 钉文案——本席 torch 面零变化红线，留后续席位扩面+金钉同笔重生成）
TORCH_UNCOVERED_KINDS = ("deeponet", "fno_lite")

#: nn 键可导出的增广器档（polynomial_cross=纯乘积交叉项可入图；
#: wilkinson_rf=core.synthesis 物理闭式 forward_z0 图内不可表达）
_NN_AUGMENTER_SUPPORTED = "polynomial_cross"

#: 未分类键的显式报错文案（表驱动诚实边界；后续席位新增键须补表）
_UNCLASSIFIED_HINT = (
    "键未进 ONNX 导出覆盖表（onnx_numpy_export.coverage_table）——"
    "新注册键交付时须同笔补分类行（诚实边界，不静默）")


def coverage_table() -> dict[str, str]:
    """全注册键→分类单源（表驱动钉消费；新键缺行=未分类）。

    分类四值面：``torch``（既有路径）/ ``numpy``（本席 builder）/
    ``pending``（可转换未实施）/ ``unsupported``（不可转换）；
    torch 未覆盖键单列 ``torch_uncovered``。键序=字母序（确定性）。
    """
    table: dict[str, str] = {}
    for k in SUPPORTED_KINDS:
        table[k] = "torch"
    for k in NUMPY_EXPORTABLE_KINDS:
        table[k] = "numpy"
    for k in NUMPY_PENDING_KINDS:
        table[k] = "pending"
    for k in NUMPY_UNSUPPORTED_KINDS:
        table[k] = "unsupported"
    for k in TORCH_UNCOVERED_KINDS:
        table[k] = "torch_uncovered"
    return dict(sorted(table.items()))


def classify_kind(kind: str) -> str:
    """键→分类值（未分类键抛 ValueError 列覆盖面——分派面/服务面共用）。"""
    table = coverage_table()
    if kind not in table:
        surface = ", ".join(sorted(table))
        raise ValueError(
            f"ONNX 导出：代理 kind={kind!r} {_UNCLASSIFIED_HINT}"
            f"——当前覆盖面: {surface}")
    return table[kind]


# ─── 图构建小工具（onnx.helper 定序直拼；float32 权重初始化器） ─────────────


class _Graph:
    """ONNX 图构建器（节点/初始化器定序追加——两跑同字节的前提）。"""

    def __init__(self, onnx: Any) -> None:
        self._onnx = onnx
        self.nodes: list[Any] = []
        self.inits: list[Any] = []
        self._i = 0

    def node(self, op: str, ins: list[str], n_out: int = 1,
             **attrs: Any) -> list[str]:
        """追加节点（自动命名输出张量；返回输出名列表）。"""
        self._i += 1
        outs = [f"t{self._i}" for _ in range(n_out)]
        self.nodes.append(self._onnx.helper.make_node(
            op, ins, outs, name=f"{op.lower()}_{self._i}", **attrs))
        return outs

    def const_f32(self, name: str, arr: Any) -> str:
        """float32 初始化器（numpy_helper 落字节，确定性）。"""
        arr = np.asarray(arr, dtype=np.float32)
        self.inits.append(self._onnx.numpy_helper.from_array(arr, name))
        return name

    def const_i64(self, name: str, arr: Any) -> str:
        arr = np.asarray(arr, dtype=np.int64)
        self.inits.append(self._onnx.numpy_helper.from_array(arr, name))
        return name


def _finish_graph(
    onnx: Any, g: _Graph, out_path: Path, opset: int,
    inputs: list[tuple[str, list[int]]], outputs: list[tuple[str, list[int]]],
) -> str:
    """组装模型→落盘→deterministic 规范化→sha256（T-N20 同法单源）。"""
    graph = onnx.helper.make_graph(
        g.nodes, "rfauto_numpy_export",
        [onnx.helper.make_tensor_value_info(n, onnx.TensorProto.FLOAT, shp)
         for n, shp in inputs],
        [onnx.helper.make_tensor_value_info(n, onnx.TensorProto.FLOAT, shp)
         for n, shp in outputs],
        initializer=g.inits,
    )
    model = onnx.helper.make_model(
        graph, producer_name="rfauto-onnx-numpy-export",
        opset_imports=[onnx.helper.make_opsetid("", opset)])
    # IR 版本与 torch 面（T-N20 dynamo 导出实测 ir_version=10）对齐——
    # 新 onnx 包缺省 IR 高于现役 onnxruntime 支持面（实测 IR14 载入被拒）
    model.ir_version = 10
    onnx.checker.check_model(model)
    out_path = Path(out_path)
    if out_path.parent != Path(""):
        out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(model.SerializeToString())
    return _canonicalize_onnx_bytes(out_path)


def _unit_clip_chain(g: _Graph, params: str, lo: np.ndarray,
                     hi: np.ndarray) -> str:
    """[0,1] 归一链（poly_ridge/pod_rom/rff_gp 的 _unit 同构；clip 进图）。"""
    lo_c = g.const_f32("norm_lo", lo)
    span = g.const_f32("norm_span", np.maximum(hi - lo, 1e-12))
    zero = g.const_f32("clip_zero", np.array(0.0))
    one = g.const_f32("clip_one", np.array(1.0))
    sub, = g.node("Sub", [params, lo_c])
    div, = g.node("Div", [sub, span])
    unit, = g.node("Clip", [div, zero, one])
    return unit


def _norm_center_chain(g: _Graph, params: str, mid: np.ndarray,
                       half: np.ndarray) -> str:
    """[-1,1] 中心化链（green_op._norm_params 同构；无 clip——忠实）。"""
    mid_c = g.const_f32("norm_mid", mid)
    half_c = g.const_f32("norm_half", np.where(half > 0, half, 1.0))
    sub, = g.node("Sub", [params, mid_c])
    x, = g.node("Div", [sub, half_c])
    return x


def _poly_ridge_features(g: _Graph, unit: str, p: int,
                         order: int) -> str:
    """poly_ridge._features 同序特征 [1, x, x², x_i·x_j（i<j）]（F,）。"""
    ones = g.const_f32("feat_ones", np.ones(1))
    parts = [ones, unit]
    if order >= 2:
        sq, = g.node("Mul", [unit, unit])
        parts.append(sq)
        for i in range(p):
            for j in range(i + 1, p):
                idx = g.const_i64(f"feat_idx_{p*i+j}", np.array([i]))
                a, = g.node("Gather", [unit, idx])
                idx2 = g.const_i64(f"feat_idx2_{p*i+j}", np.array([j]))
                b, = g.node("Gather", [unit, idx2])
                cross, = g.node("Mul", [a, b])
                parts.append(cross)
    out, = g.node("Concat", parts, axis=0)
    return out


def _green_poly_features(g: _Graph, x: str, p: int, degree: int) -> str:
    """green_operator._poly_features 同序特征（≤degree 全单项式，
    combinations_with_replacement 序）。"""
    from itertools import combinations_with_replacement

    parts: list[str] = []
    feat_idx = 0
    for d in range(0, int(degree) + 1):
        for combo in combinations_with_replacement(range(p), d):
            if d == 0:
                parts.append(g.const_f32(f"gp_feat_{feat_idx}", np.ones(1)))
            else:
                vals: list[str] = []
                for k, pos in enumerate(combo):
                    idx = g.const_i64(f"gp_idx_{feat_idx}_{k}",
                                      np.array([pos]))
                    v, = g.node("Gather", [x, idx])
                    vals.append(v)
                acc = vals[0]
                for v in vals[1:]:
                    m, = g.node("Mul", [acc, v])
                    acc = m
                parts.append(acc)
            feat_idx += 1
    out, = g.node("Concat", parts, axis=0)
    return out


def _mlp_chain(g: _Graph, x: str, net: Any, tag: str) -> str:
    """_MLP（nn_model，tanh 3 层）前向链（w1..b3 权重快照→初始化器）。"""
    h1a, = g.node("MatMul", [x, g.const_f32(f"{tag}_w1", net.w1)])
    h1b, = g.node("Add", [h1a, g.const_f32(f"{tag}_b1", net.b1)])
    h1, = g.node("Tanh", [h1b])
    h2a, = g.node("MatMul", [h1, g.const_f32(f"{tag}_w2", net.w2)])
    h2b, = g.node("Add", [h2a, g.const_f32(f"{tag}_b2", net.b2)])
    h2, = g.node("Tanh", [h2b])
    oa, = g.node("MatMul", [h2, g.const_f32(f"{tag}_w3", net.w3)])
    o, = g.node("Add", [oa, g.const_f32(f"{tag}_b3", net.b3)])
    return o


def _probes(bounds: dict[str, tuple[float, float]],
            keys: list[str]) -> list[dict[str, float]]:
    """探针点（域中点+角点+两对称内点，与 T-N20 对拍同口径）。"""
    out = []
    for frac in (0.5, 0.0, 1.0, 0.25, 0.75):
        out.append({k: float(bounds[k][0] + frac * (bounds[k][1]
                                                    - bounds[k][0]))
                    for k in keys})
    return out


def _verify_numpy(
    model: Any, path: Path, metric_names: list[str], bounds: dict,
    keys: list[str], field_names: list[str] | None = None,
) -> dict[str, Any]:
    """导出-回代对拍：numpy 原生 predict vs onnxruntime（测试面独立复算
    同法；onnxruntime 缺席=跳过注记不阻塞，#105 best-effort）。"""
    ort = _ensure_onnxruntime()
    if ort is None:
        return {"verified": False,
                "verify_note": "onnxruntime 缺席，导出-回代对拍跳过"
                               "（pip install onnxruntime 可启用）"}
    import onnxruntime as ort_run

    sess = ort_run.InferenceSession(str(path),
                                    providers=["CPUExecutionProvider"])
    input_name = sess.get_inputs()[0].name
    field_names = field_names or []
    max_diff = 0.0
    all_close = True
    probes = _probes(bounds, keys)
    for probe in probes:
        native_map = model.predict(probe)
        native = np.asarray([float(native_map[k]) for k in metric_names],
                            dtype=np.float64)
        vec = np.asarray([float(probe[k]) for k in keys], dtype=np.float32)
        outs = sess.run(None, {input_name: vec})
        got = np.asarray(outs[0], dtype=np.float64)
        diff = float(np.max(np.abs(native - got)))
        max_diff = max(max_diff, diff)
        if not np.allclose(native, got, rtol=PARITY_RTOL, atol=PARITY_ATOL):
            all_close = False
        for fi, fkey in enumerate(field_names, start=1):
            f_native = np.asarray(
                model.predict_field(fkey, probe)["values"], dtype=np.float64)
            f_got = np.asarray(outs[fi], dtype=np.float64)
            d = float(np.max(np.abs(f_native - f_got)))
            max_diff = max(max_diff, d)
            if not np.allclose(f_native, f_got,
                               rtol=PARITY_RTOL, atol=PARITY_ATOL):
                all_close = False
    return {"verified": bool(all_close), "max_abs_diff": max_diff,
            "rtol": PARITY_RTOL, "atol": PARITY_ATOL,
            "n_probes": len(probes)}


def _export_common(model: Any, kind: str, path: Path, opset: int,
                   metric_names: list[str], bounds: dict, keys: list[str],
                   g: _Graph, outputs: list[tuple[str, list[int]]],
                   extra_meta: dict[str, Any],
                   head_tensors: list[str],
                   field_names: list[str] | None = None,
                   verify: bool = True) -> dict[str, Any]:
    """收尾公共面：图输出接线+落盘规范化+结果信封+对拍（各 builder 共用）。"""
    onnx = _ensure_onnx()
    for out_name, src in zip([o[0] for o in outputs], head_tensors,
                             strict=True):
        if out_name != src:
            g.nodes.append(onnx.helper.make_node(
                "Identity", [src], [out_name],
                name=f"identity_out_{out_name}"))
    sha = _finish_graph(onnx, g, path, opset,
                        [("params", [len(keys)])], outputs)
    result: dict[str, Any] = {
        "ok": True,
        "kind": kind,
        "path": str(path),
        "sha256": sha,
        "opset": int(opset),
        "input": {"name": "params", "dtype": "float32",
                  "shape": [len(keys)]},
        "output": {"name": outputs[0][0]},
        "exporter": "numpy-builder",
        "metric_names": list(metric_names),
        **extra_meta,
    }
    if len(outputs) > 1:
        result["extra_outputs"] = [
            {"name": n, "shape": list(shp)} for n, shp in outputs[1:]]
    if verify:
        ver = _verify_numpy(model, path, metric_names, bounds, keys,
                            field_names=field_names)
        result.update(ver)
        if not ver.get("verified", False) and "max_abs_diff" in ver:
            raise RuntimeError(
                f"导出-回代对拍超容差（max_abs_diff={ver['max_abs_diff']}"
                f" > rtol={PARITY_RTOL}/atol={PARITY_ATOL} 口径）——onnx "
                "文件已落盘但不可信，请勿消费")
    return result


# ─── 键 builder（只读 fit 产物；predict 数学形态→onnx.helper 图） ───────────


def _build_ridge_family(model: Any, kind: str, path: Path,
                        opset: int, verify: bool) -> dict[str, Any]:
    """poly_ridge/huber_ridge：特征展开+逐指标线性读出（共用 builder）。"""
    onnx = _ensure_onnx()
    g = _Graph(onnx)
    names = list(model.names)
    p = len(names)
    lo = np.array([model.bounds[n][0] for n in names])
    hi = np.array([model.bounds[n][1] for n in names])
    unit = _unit_clip_chain(g, "params", lo, hi)
    feats = _poly_ridge_features(g, unit, p,
                                 int(getattr(model, "effective_order",
                                             model.order)))
    metric_names = list(model.models.keys())
    coefs = np.stack([np.asarray(model.models[k], dtype=np.float64)
                      for k in metric_names], axis=1)   # (F, M)
    mm, = g.node("MatMul", [feats, g.const_f32("coef_stack", coefs)])
    return _export_common(model, kind, path, opset, metric_names,
                          model.bounds, names, g, [("metrics", [None])],
                          {"param_names": names,
                           "order": int(getattr(model, "effective_order",
                                                model.order)),
                           "native_call": "predict(params_dict)"},
                          head_tensors=[mm], verify=verify)


def _build_pod_rom(model: Any, kind: str, path: Path,
                   opset: int, verify: bool) -> dict[str, Any]:
    """pod_rom：标量=退化 1 点场链；场键=POD 基线性重构（逐键输出）。"""
    onnx = _ensure_onnx()
    g = _Graph(onnx)
    names = list(model.names)
    p = len(names)
    lo = np.array([model.bounds[n][0] for n in names])
    hi = np.array([model.bounds[n][1] for n in names])
    unit = _unit_clip_chain(g, "params", lo, hi)
    feats = _poly_ridge_features(g, unit, p,
                                 int(getattr(model, "effective_order",
                                             model.order)))
    metric_names = list(model.models.keys())
    per_key: list[str] = []
    for ki, k in enumerate(metric_names):
        m = model.models[k]
        beta = g.const_f32(f"beta_{ki}", np.asarray(m["beta"]))
        modes_t = g.const_f32(f"modes_t_{ki}",
                              np.asarray(m["modes"]).T)     # (r, L)
        mean = g.const_f32(f"mean_{ki}",
                           np.broadcast_to(np.asarray(m["mean"], float),
                                           (np.asarray(m["modes"]).shape[1],)))
        h, = g.node("MatMul", [feats, beta])
        h2, = g.node("MatMul", [h, modes_t])
        v, = g.node("Add", [h2, mean])
        per_key.append(v)
    outputs: list[tuple[str, list[int]]] = []
    heads: list[str] = []
    if per_key:
        concat, = g.node("Concat", per_key, axis=0)
        outputs.append(("metrics", [len(metric_names)]))
        heads.append(concat)
    field_names = list(getattr(model, "field_keys", []) or [])
    for fi, fkey in enumerate(field_names):
        m = model.field_models[fkey]
        beta = g.const_f32(f"fbeta_{fi}", np.asarray(m["beta"]))
        modes_t = g.const_f32(f"fmodes_t_{fi}", np.asarray(m["modes"]).T)
        mean = g.const_f32(f"fmean_{fi}", np.asarray(m["mean"], float))
        h, = g.node("MatMul", [feats, beta])
        h2, = g.node("MatMul", [h, modes_t])
        v, = g.node("Add", [h2, mean])
        outputs.append((f"field:{fkey}", [None]))
        heads.append(v)
    if not outputs:
        raise ValueError(
            "pod_rom ONNX 导出：无任何可导出输出（标量 metrics 与场键均空"
            "——拟合面如实跳过键所致），请检查样本指标键")
    if per_key:
        return _export_common(model, kind, path, opset, metric_names,
                              model.bounds, names, g, outputs,
                              {"param_names": names,
                               "field_keys": field_names,
                               "n_modes": dict(model.n_modes_used),
                               "native_call": "predict(params_dict)（场键="
                                              "predict_field(key, "
                                              "params_dict)['values']）"},
                              head_tensors=heads, field_names=field_names,
                              verify=verify)
    return _export_common_fields_only(model, kind, path, opset, names, g,
                                      outputs, field_names, heads, verify)


def _export_common_fields_only(model: Any, kind: str, path: Path,
                               opset: int, names: list[str], g: _Graph,
                               outputs: list[tuple[str, list[int]]],
                               field_names: list[str],
                               head_tensors: list[str],
                               verify: bool) -> dict[str, Any]:
    """pod_rom 无标量指标、仅场键形态（对拍走场键输出面）。"""
    onnx = _ensure_onnx()
    for out_name, src in zip([o[0] for o in outputs], head_tensors,
                             strict=True):
        if out_name != src:
            g.nodes.append(onnx.helper.make_node(
                "Identity", [src], [out_name],
                name=f"identity_out_{out_name}"))
    sha = _finish_graph(onnx, g, path, opset,
                        [("params", [len(names)])], outputs)
    result: dict[str, Any] = {
        "ok": True, "kind": kind, "path": str(path), "sha256": sha,
        "opset": int(opset),
        "input": {"name": "params", "dtype": "float32", "shape": [len(names)]},
        "output": {"name": outputs[0][0]},
        "exporter": "numpy-builder",
        "metric_names": [],
        "param_names": names, "field_keys": field_names,
        "n_modes": dict(model.n_modes_used),
        "native_call": "predict_field(key, params_dict)['values']",
    }
    if len(outputs) > 1:
        result["extra_outputs"] = [
            {"name": n, "shape": list(shp)} for n, shp in outputs[1:]]
    if verify:
        ort = _ensure_onnxruntime()
        if ort is None:
            result["verified"] = False
            result["verify_note"] = (
                "onnxruntime 缺席，导出-回代对拍跳过"
                "（pip install onnxruntime 可启用）")
            return result
        import onnxruntime as ort_run

        sess = ort_run.InferenceSession(str(path),
                                        providers=["CPUExecutionProvider"])
        input_name = sess.get_inputs()[0].name
        max_diff = 0.0
        all_close = True
        for probe in _probes(model.bounds, names):
            vec = np.asarray([float(probe[k]) for k in names],
                             dtype=np.float32)
            outs = sess.run(None, {input_name: vec})
            for fi, fkey in enumerate(field_names):
                f_native = np.asarray(
                    model.predict_field(fkey, probe)["values"],
                    dtype=np.float64)
                f_got = np.asarray(outs[fi], dtype=np.float64)
                d = float(np.max(np.abs(f_native - f_got)))
                max_diff = max(max_diff, d)
                if not np.allclose(f_native, f_got,
                                   rtol=PARITY_RTOL, atol=PARITY_ATOL):
                    all_close = False
        result.update({"verified": bool(all_close),
                       "max_abs_diff": max_diff, "rtol": PARITY_RTOL,
                       "atol": PARITY_ATOL,
                       "n_probes": len(_probes(model.bounds, names))})
        if not result["verified"]:
            raise RuntimeError(
                f"导出-回代对拍超容差（max_abs_diff={result['max_abs_diff']}"
                f" > rtol={PARITY_RTOL}/atol={PARITY_ATOL} 口径）——onnx "
                "文件已落盘但不可信，请勿消费")
    return result


def _build_nn(model: Any, kind: str, path: Path,
              opset: int, verify: bool) -> dict[str, Any]:
    """nn：polynomial_cross 增广+标准化→tanh MLP 集成→均值→反标准化。"""
    onnx = _ensure_onnx()
    if str(getattr(model, "augmenter_name", "")) != _NN_AUGMENTER_SUPPORTED:
        raise ValueError(
            f"nn ONNX 导出仅支持 augmenter={_NN_AUGMENTER_SUPPORTED!r} 档"
            f"（纯乘积交叉项可入图），实测 augmenter="
            f"{getattr(model, 'augmenter_name', None)!r}——wilkinson_rf 等"
            "物理增广含 core.synthesis 闭式（forward_z0）图内不可表达，"
            "请以该档重新拟合后导出（或走本仓 python 推理路径）")
    names = list(model._x_names)
    base = [n for n in names if not str(n).startswith("cross__")]
    # 增广名重建校验（名字即规格：cross__a__b = params[a]*params[b]；
    # 解析歧义（参数名含 cross__/__ 等）显式拒绝不猜）
    expected_aug = [f"cross__{base[i]}__{base[j]}"
                    for i in range(len(base))
                    for j in range(i + 1, len(base))]
    expected_aug = sorted(expected_aug)
    aug = names[len(base):]
    if aug != expected_aug or any(str(n).startswith("cross__")
                                  for n in base):
        raise ValueError(
            f"nn ONNX 导出：特征名与 polynomial_cross 形态不符——实测特征面"
            f"{names}（增广名解析歧义/非该档特征面，诚实拒绝不猜）")
    g = _Graph(onnx)
    feats_parts: list[str] = ["params"]
    for ai, aname in enumerate(aug):
        a, b = aname.split("cross__", 1)[1].split("__", 1)
        ia = g.const_i64(f"nn_cross_a_{ai}", np.array([base.index(a)]))
        ib = g.const_i64(f"nn_cross_b_{ai}", np.array([base.index(b)]))
        va, = g.node("Gather", ["params", ia])
        vb, = g.node("Gather", ["params", ib])
        prod, = g.node("Mul", [va, vb])
        feats_parts.append(prod)
    if len(feats_parts) > 1:
        feats, = g.node("Concat", feats_parts, axis=0)
    else:
        feats = "params"
    mu = g.const_f32("nn_x_mean", model._x_mean)
    sd = g.const_f32("nn_x_std", model._x_std)
    sub, = g.node("Sub", [feats, mu])
    xn, = g.node("Div", [sub, sd])
    member_outs = [_mlp_chain(g, xn, net, f"nn_m{k}")
                   for k, net in enumerate(model._models)]
    if len(member_outs) > 1:
        # 集成堆叠：1D→(1,M) 逐成员 Reshape 后 Concat（ONNX 无 Stack 算子）
        rows = []
        for k, mo in enumerate(member_outs):
            shp = g.const_i64(f"nn_row_{k}",
                              np.array([1, len(model.metric_keys)]))
            r, = g.node("Reshape", [mo, shp])
            rows.append(r)
        stacked, = g.node("Concat", rows, axis=0)
        axes = g.const_i64("nn_mean_axes", np.array([0]))
        mean, = g.node("ReduceMean", [stacked, axes], keepdims=0)
    else:
        mean = member_outs[0]
    ys = g.const_f32("nn_y_std", model._y_std)
    ym = g.const_f32("nn_y_mean", model._y_mean)
    scaled, = g.node("Mul", [mean, ys])
    out, = g.node("Add", [scaled, ym])
    metric_names = list(model.metric_keys)
    return _export_common(model, kind, path, opset, metric_names,
                          model.bounds, base, g, [("metrics", [None])],
                          {"param_names": base,
                           "augmenter": _NN_AUGMENTER_SUPPORTED,
                           "n_ensemble": len(model._models),
                           "native_call": "predict(params_dict)"},
                          head_tensors=[out], verify=verify)


def _build_rff_gp(model: Any, kind: str, path: Path,
                  opset: int, verify: bool) -> dict[str, Any]:
    """rff_gp：[0,1] 归一→cos 随机傅里叶特征→线性读出→仿射（逐指标分支）。"""
    onnx = _ensure_onnx()
    g = _Graph(onnx)
    names = list(model.names)
    lo = np.array([model.bounds[n][0] for n in names])
    hi = np.array([model.bounds[n][1] for n in names])
    unit = _unit_clip_chain(g, "params", lo, hi)
    metric_names = list(model._models.keys())
    per_key: list[str] = []
    n_feat_used: dict[str, int] = {}
    for ki, k in enumerate(metric_names):
        m = model._models[k]
        if m.get("constant"):
            cv = g.const_f32(f"rff_const_{ki}",
                             np.array([float(m["y_mean"])]))
            per_key.append(cv)
            continue
        d_feat = int(np.asarray(m["omega"]).shape[0])
        n_feat_used[k] = d_feat
        omega_t = g.const_f32(f"rff_omega_t_{ki}",
                              np.asarray(m["omega"]).T)      # (d, D)
        bias = g.const_f32(f"rff_b_{ki}", np.asarray(m["b"]))
        w = g.const_f32(f"rff_w_{ki}",
                        np.asarray(m["w"], float).reshape(-1, 1))  # (D,1)
        y_std = g.const_f32(f"rff_ys_{ki}", np.array([float(m["y_std"])]))
        y_mean = g.const_f32(f"rff_ym_{ki}", np.array([float(m["y_mean"])]))
        scale = g.const_f32(f"rff_scale_{ki}",
                            np.array([np.sqrt(2.0 / d_feat)]))
        proj, = g.node("MatMul", [unit, omega_t])
        pb, = g.node("Add", [proj, bias])
        z, = g.node("Cos", [pb])
        zs, = g.node("Mul", [z, scale])
        dot, = g.node("MatMul", [zs, w])
        s1, = g.node("Mul", [dot, y_std])
        v, = g.node("Add", [s1, y_mean])
        per_key.append(v)
    concat, = g.node("Concat", per_key, axis=0)
    return _export_common(model, kind, path, opset, metric_names,
                          model.bounds, names, g,
                          [("metrics", [len(metric_names)])],
                          {"param_names": names,
                           "n_features": n_feat_used,
                           "native_call": "predict(params_dict)"},
                          head_tensors=[concat], verify=verify)


def _build_green_op(model: Any, kind: str, path: Path,
                    opset: int, verify: bool) -> dict[str, Any]:
    """green_op：特征/MLP 头→re/im 复数重组→|S|→dB→带内 max/min。"""
    from rfauto.optimization.surrogate.green_operator import (
        _DB_FLOOR,
        _entry_name,
    )

    onnx = _ensure_onnx()
    g = _Graph(onnx)
    names = list(model.param_names)
    p = len(names)
    mid = np.array([0.5 * (model.bounds[n][0] + model.bounds[n][1])
                    for n in names])
    half = np.array([0.5 * (model.bounds[n][1] - model.bounds[n][0])
                     for n in names])
    x = _norm_center_chain(g, "params", mid, half)
    if str(model.head_kind) == "ridge":
        feats = _green_poly_features(g, x, p, int(model.poly_degree))
        y, = g.node("MatMul", [feats,
                               g.const_f32("go_w_ridge",
                                           np.asarray(model._w_ridge))])
    else:
        y = _mlp_chain(g, x, model._net, "go_mlp")
    y_raw, = g.node("Add", [g.node("Mul", [y,
                                           g.const_f32("go_y_std",
                                                       model._y_std)])[0],
                             g.const_f32("go_y_mean", model._y_mean)])
    n_freq, n_pairs = int(model.n_freq), len(model._pairs)
    half_len = n_freq * n_pairs
    s_lo = g.const_i64("go_split_lo", np.array([0]))
    s_hi = g.const_i64("go_split_mid", np.array([half_len]))
    s_end = g.const_i64("go_split_end", np.array([2 * half_len]))
    s_ax = g.const_i64("go_split_ax", np.array([0]))
    re_i, = g.node("Slice", [y_raw, s_lo, s_hi, s_ax])
    im_i, = g.node("Slice", [y_raw, s_hi, s_end, s_ax])
    shape2 = g.const_i64("go_shape2",
                         np.array([n_freq, n_pairs]))
    re2d, = g.node("Reshape", [re_i, shape2])
    im2d, = g.node("Reshape", [im_i, shape2])
    r2, = g.node("Mul", [re2d, re2d])
    i2, = g.node("Mul", [im2d, im2d])
    mag, = g.node("Sqrt", [g.node("Add", [r2, i2])[0]])
    floor = g.const_f32("go_floor", np.array([float(_DB_FLOOR)]))
    floored, = g.node("Max", [mag, floor])
    db, = g.node("Mul", [g.node("Log", [floored])[0],
                         g.const_f32("go_db_scale",
                                     np.array([20.0 / np.log(10.0)]))])
    expand = np.zeros((n_pairs, p * p))
    for kk, (i, j) in enumerate(model._pairs):
        expand[kk, i * p + j] = 1.0
        if bool(model.reciprocal) and i != j:
            expand[kk, j * p + i] = 1.0
    grid, = g.node("MatMul", [db, g.const_f32("go_expand", expand)])
    ax0 = g.const_i64("go_ax0", np.array([0]))
    mx, = g.node("ReduceMax", [grid, ax0], keepdims=0)
    mn, = g.node("ReduceMin", [grid, ax0], keepdims=0)
    # max/min 交错堆叠：1D→(1,P²) Reshape 后 Concat（ONNX 无 Stack 算子）
    row_shp = g.const_i64("go_row_shp", np.array([1, p * p]))
    mx_r, = g.node("Reshape", [mx, row_shp])
    mn_r, = g.node("Reshape", [mn, row_shp])
    stacked, = g.node("Concat", [mx_r, mn_r], axis=0)
    tr, = g.node("Transpose", [stacked], perm=[1, 0])
    out, = g.node("Reshape", [tr, g.const_i64(
        "go_out_shape", np.array([2 * p * p]))])
    metric_names: list[str] = []
    for i in range(p):
        for j in range(p):
            nm = _entry_name(i, j, p)
            metric_names.append(f"{nm}_db_max_in_band")
            metric_names.append(f"{nm}_db_min_in_band")
    return _export_common(model, kind, path, opset, metric_names,
                          model.bounds, names, g,
                          [("metrics", [2 * p * p])],
                          {"param_names": names,
                           "n_ports": p, "n_freq": n_freq,
                           "reciprocal": bool(model.reciprocal),
                           "head": str(model.head_kind),
                           "native_call": "predict(params_dict)"},
                          head_tensors=[out], verify=verify)


_BUILDERS = {
    "green_op": _build_green_op,
    "huber_ridge": _build_ridge_family,
    "nn": _build_nn,
    "pod_rom": _build_pod_rom,
    "poly_ridge": _build_ridge_family,
    "rff_gp": _build_rff_gp,
}


def export_onnx_numpy(
    model: Any,
    out_path: str | Path,
    *,
    opset_version: int = DEFAULT_OPSET,
    verify: bool = True,
) -> dict[str, Any]:
    """已拟合 numpy 系代理 → ONNX 模型文件（本席 builder 面）。

    Args:
        model: 已拟合代理（KIND ∈ NUMPY_EXPORTABLE_KINDS；各键 fit 产物
            属性只读消费——models/_models/_net/bounds/_x_mean 等）。
        out_path: ONNX 输出路径（父目录自动创建；deterministic 规范形态）。
        opset_version: ONNX opset（缺省 18，与 torch 面同 DEFAULT_OPSET）。
        verify: 导出-回代对拍（onnxruntime 缺席=跳过并注记，不阻塞）。

    Returns:
        ``{"ok": True, "kind", "path", "sha256", "opset", "input",
        "output", "metric_names", ...}``——消费侧按 metric_names 序把
        metrics 向量还原成 predict dict（pod_rom 场键附 extra_outputs/
        field:<key>）。

    Raises:
        ValueError: kind 不在 numpy 可转换面（列覆盖面+指引）；nn 非 rogue
            polynomial_cross 增广档；pod_rom 零可导出输出。
        RuntimeError: 未拟合；对拍开启且实测超容差（不产出虚假 ok）。
    """
    kind = str(getattr(model, "KIND", "") or "")
    if kind not in NUMPY_EXPORTABLE_KINDS:
        raise ValueError(
            f"numpy ONNX 导出不支持代理 kind={kind!r}——numpy 可转换面: "
            f"{', '.join(NUMPY_EXPORTABLE_KINDS)}；torch 系面: "
            f"{', '.join(SUPPORTED_KINDS)}（走 export_onnx）；其余键见 "
            "coverage_table()（可转换未实施/不可转换逐键原因）")
    if not getattr(model, "fitted", False):
        raise RuntimeError("代理未拟合，先调用 fit() 再导出")
    return _BUILDERS[kind](model, kind, Path(out_path),
                           int(opset_version), bool(verify))


def export_onnx_auto(
    model: Any,
    out_path: str | Path,
    *,
    opset_version: int = DEFAULT_OPSET,
    verify: bool = True,
) -> dict[str, Any]:
    """按键种类分派的导出入口（torch 键→既有路径零变化；numpy 键→builder）。

    - torch 系三键（fno/deep_ensemble/siren）：原样委托
      ``onnx_export.export_onnx``（本席零改动红线——返回面/字节面不变）；
    - numpy 可转换六键：``export_onnx_numpy`` builder 面；
    - pending/unsupported 键：显式 ValueError 列逐键原因+python 推理指引；
    - 未分类键：显式 ValueError（表驱动诚实边界——新键交付须补表）。
    """
    kind = str(getattr(model, "KIND", "") or "")
    cls = classify_kind(kind)
    if cls == "torch":
        return export_onnx(model, out_path, opset_version=opset_version,
                           verify=verify)
    if cls == "numpy":
        return export_onnx_numpy(model, out_path,
                                 opset_version=opset_version, verify=verify)
    if cls == "pending":
        raise ValueError(
            f"ONNX 导出：kind={kind!r} 可转换但未实施——原因: "
            f"{NUMPY_PENDING_KINDS[kind]}；消费请走本仓 python 推理路径"
            "（surrogate_registry.create + predict），组合器面留后续席位")
    if cls == "torch_uncovered":
        raise ValueError(
            f"ONNX 导出：kind={kind!r} 为 torch 系但 T-N20 未覆盖——扩面牵动"
            "既有钉（SUPPORTED_KINDS 文案钉），本席 torch 面零变化红线；"
            "消费请走 export_onnx 支持面: "
            f"{', '.join(SUPPORTED_KINDS)} 或 python 推理路径")
    reason = NUMPY_UNSUPPORTED_KINDS.get(kind, "")
    raise ValueError(
        f"ONNX 导出不支持代理 kind={kind!r}（predict 数学形态不可标准算子"
        f"表达）——原因: {reason}；消费请走本仓 python 推理路径"
        "（surrogate_registry.create + predict）；当前可导出面: torch 系 "
        f"{', '.join(SUPPORTED_KINDS)} + numpy 系 "
        f"{', '.join(NUMPY_EXPORTABLE_KINDS)}")
