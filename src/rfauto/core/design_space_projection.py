"""DS-1 设计空间投影报告（round19 P3，ge8c 席C6）——sweep→feasibility 二维投影。

定位（round19 口径"sweep→feasibility 二维投影（复用 pod_rom，零新依赖）
+不可行成因标注（bounds verdict 作标签）"）：

- **投影**：参数矩阵逐列 z-score 归一（零方差列如实降权置零，不炸）→
  去均值 SVD（numpy，``pod_rom.pod_basis`` 同族自实现、零 sklearn 依赖）
  → 前二主坐标 + 解释方差比。SVD 符号二义性用**确定性符号约定**钉住
  （每个右奇异向量取绝对值最大分量非负——跨 numpy 版本坐标可复现）；
- **feasibility 标注**：逐点 verdict（core/bounds.BoundVerdict 词表：
  unreachable/marginal/reachable/undefined，或调用方自定义枚举）原样作
  标签；逐标签簇摘要（投影面质心/散布）+ 不可行成因计数（unreachable/
  marginal 即"成因标签"）；
- **诚实边界**：投影是**可视化辅助**不是判据（铁律 7：本模块不产出物理
  数字，只对确定性输入做线性代数变换）；undefined 标签如实入账不冒充
  可行/不可行。

负例（空点集/参数键不齐/非数值参数）显式报错；同输入两次输出逐位一致。
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

__all__ = [
    "PROJECTION_SCHEMA",
    "project_design_space",
    "render_projection_markdown",
]

#: 投影报告 schema 标识（JSON 消费面稳定钉）。
PROJECTION_SCHEMA = "rfauto-design-space-projection-v1"

#: bounds verdict 词表（core/bounds 语义；其余字符串原样收不作枚举扩权）。
_KNOWN_VERDICTS = ("unreachable", "marginal", "reachable", "undefined")


def _sign_fix(u: Any, vt: Any) -> tuple[Any, Any]:
    """确定性符号约定：每分量绝对值最大载荷为正（消 SVD 符号二义性）。"""
    import numpy as np

    idx = np.argmax(np.abs(vt), axis=1)
    signs = np.sign(vt[np.arange(vt.shape[0]), idx])
    signs[signs == 0] = 1.0
    return u * signs, vt * signs[:, None]


def project_design_space(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """sweep 点集 → 二维 PCA 投影 + feasibility 标注（JSON 进出）。

    Args:
        rows: [{"params": {param: float}, "verdict": str?, ...}]——params
            键集必须全行一致（缺失键显式报错，不静默插值）；verdict 缺省
            "undefined"。

    Returns: {ok, schema, n_points, params, explained_variance_ratio,
        coords: [{point_id, x, y, verdict}], label_summary: {verdict: {
        n, centroid_xy, spread, share}}, n_zero_variance_dims, note}
    """
    import numpy as np

    if not rows:
        raise ValueError("rows 不可为空（空数据集无投影对象）")
    keys = sorted(rows[0]["params"])
    if not keys:
        raise ValueError("params 不可为空")
    mat = np.empty((len(rows), len(keys)), dtype=float)
    verdicts: list[str] = []
    for i, row in enumerate(rows):
        params = row.get("params")
        if not isinstance(params, Mapping) or sorted(params) != keys:
            raise ValueError(f"row {i} params 键集不一致（须全行 {keys}）")
        for j, k in enumerate(keys):
            v = params[k]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or \
                    not math.isfinite(float(v)):
                raise ValueError(f"row {i} param {k!r} 非有限数值: {v!r}")
            mat[i, j] = float(v)
        verdicts.append(str(row.get("verdict") or "undefined"))

    means = mat.mean(axis=0)
    stds = mat.std(axis=0)
    zero_var = stds <= 0.0
    n_zero_dims = int(zero_var.sum())
    # 去均值协方差 PCA（pod_rom.pod_basis 同口径：只去均值不做 z-score——
    # z-score 会把"簇间分离"抹平成与噪声同尺度，破坏 feasibility 结构的
    # 投影可分性；量纲敏感性在 note 如实声明，归一变体属消费面选择）。
    centered = mat - means
    # SVD 主成分（行向量 = 样本）：X = U S Vt
    u, s, vt = np.linalg.svd(centered, full_matrices=False)
    u, vt = _sign_fix(u, vt)
    k = min(2, u.shape[1])
    coords2 = u[:, :k] * s[:k]
    if k < 2:
        coords2 = np.hstack([coords2, np.zeros((coords2.shape[0], 1))])
    var_total = float(np.sum(s * s))
    evr = [float((s[i] * s[i]) / var_total) if var_total > 0 else 0.0
           for i in range(min(2, len(s)))]
    while len(evr) < 2:
        evr.append(0.0)

    coords = [
        {"point_id": f"d{i:04d}", "x": float(coords2[i, 0]),
         "y": float(coords2[i, 1]), "verdict": verdicts[i]}
        for i in range(len(rows))
    ]
    summary: dict[str, dict[str, Any]] = {}
    for label in sorted(set(verdicts)):
        sel = [c for c in coords if c["verdict"] == label]
        xs = [c["x"] for c in sel]
        ys = [c["y"] for c in sel]
        cx = sum(xs) / len(xs)
        cy = sum(ys) / len(ys)
        spread = math.sqrt(
            sum((x - cx) ** 2 + (y - cy) ** 2
                 for x, y in zip(xs, ys, strict=True))
            / len(sel)) if len(sel) else 0.0
        summary[label] = {
            "n": len(sel),
            "share": len(sel) / len(rows),
            "centroid_xy": [cx, cy],
            "spread": spread,
            "is_infeasibility_tag": label in ("unreachable", "marginal"),
        }
    return {
        "ok": True,
        "schema": PROJECTION_SCHEMA,
        "n_points": len(rows),
        "params": keys,
        "explained_variance_ratio": evr,
        "coords": coords,
        "label_summary": summary,
        "n_zero_variance_dims": n_zero_dims,
        "loadings": {k: [float(vt[j, 0]), float(vt[j, 1])]
                     for j, k in enumerate(keys)},
        "note": ("存在零方差维（如实入账）；去均值协方差 PCA（量纲敏感，"
                 "z-score 变体属消费面选择）；投影是可视化辅助非判据"
                 if n_zero_dims else
                 "去均值协方差 PCA（量纲敏感，z-score 变体属消费面选择）；"
                 "投影是可视化辅助非判据；verdict 语义沿 core/bounds 词表"),
    }


def render_projection_markdown(result: Mapping[str, Any]) -> str:
    """投影 → Markdown（坐标表 + 标签簇摘要；只渲染不新造判断）。"""
    if not result.get("ok"):
        return f"# 设计空间投影\n\n- 投影失败：{result.get('errors')}\n"
    evr = result.get("explained_variance_ratio") or [0.0, 0.0]
    lines = [
        "# 设计空间投影（sweep→feasibility 二维）", "",
        f"- 点数：{result.get('n_points')}；参数：{result.get('params')}",
        f"- 解释方差比：PC1={evr[0]:.4f}，PC2={evr[1]:.4f}", "",
        "| 标签 | 点数 | 份额 | 质心 (x, y) | 散布 | 不可行成因 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for label, s in sorted((result.get("label_summary") or {}).items()):
        tag = "是" if s.get("is_infeasibility_tag") else "否"
        lines.append(
            f"| {label} | {s['n']} | {s['share']:.2%} "
            f"| ({s['centroid_xy'][0]:.3f}, {s['centroid_xy'][1]:.3f}) "
            f"| {s['spread']:.3f} | {tag} |")
    lines += ["", f"> {result.get('note', '')}", ""]
    return "\n".join(lines)
