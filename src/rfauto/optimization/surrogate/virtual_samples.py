"""v2 物理先验 NN 代理增量二：虚拟样本生成器（W4-4 机制层最小闭环）。

语义锚点（docs/surrogate_calibration_design.md §7.2 借鉴点 2 原文）：
    "虚拟样本增强：锚点间 IDW/双线性插值 + 置信度加权，9 个真实样本
    撑起大范围预测（决赛通孔实测）。v1 若样本不足时启用；注意防泄露
    （验证集锚点隔离，其代码已有开关设计）。"
即 physics-informed 数据增广：在稀疏真实（锚点）样本之间合成"物理合法
但不来自真实仿真"的训练样本，缓和小样本过拟合。本模块 = 该语义的机制层
最小闭环（生成器 + 无源性判据 + 确定性种子），不含消费侧加权训练本体
（W4-3 裁定不越界；接口点 = 样本字典可选权重键 ``VIRTUAL_WEIGHT_KEY``，
PoleResidueSurrogate/NNSurrogate.fit 现阶段忽略该键，加权消费属后续增量）。

与 nn_model.PHYSICS_AUGMENTERS 的关系（并列正交，非复用非扩展）：
    PHYSICS_AUGMENTERS 是特征增广（对每个已有样本的输入空间补充领域特征，
    改变网络"学什么"），虚拟样本是数据增广（向样本集补充新样本，改变网络
    "从哪些点学"）——两机制正交且天然组合：虚拟样本进入 NNSurrogate.fit
    后与真实样本走同一条增广器特征化路径，本侧不对 nn_model 做任何改动。

数据完整性红线（#144 家法）：
    本模块是纯函数——只读入参、只返回新构造的 dict/list，零文件系统写入
    （不 import 任何 I/O 面），产出即用即弃；测试全程内存构造。虚拟样本
    绝不落 runs/ 数据湖、绝不混入校准数据集落盘链路。

确定性红线（AGENTS 7）：
    生成全程 np.random.default_rng(seed) 单源驱动（锚点对/插值比/缩放
    系数），无 LLM/神经网络参与；同种子两跑逐位一致（测试钉住）。

判据单源（#296 幂等直通纪律）：
    无源性判定复用 pole_residue.passivity_verdict（其容差再单源于
    core.macromodel.PASSIVITY_TOL）——本模块不实现第二套无源性判据；
    曲线键复用 pole_residue.CURVE_KEY（不另立第二常量）。

约束族（形态自选，物理语义注记）：
  A. ``anchor_blend``（锚点对 IDW 凸组合插值，默认族——§7.2 本义）：
     虚拟参数点取锚点对的凸组合 x_v=(1-t)·x_i+t·x_j（归一化空间，凸组合
     保证不外推出锚点包络——design doc §6 外推失真风控）；曲线/标量
     metrics 按全锚点 IDW 权重（w_k ∝ 1/d^p，归一化后非负和一）凸组合。
     物理合法性：无源集逐频点凸（σmax 凸性 ⇒ σmax(Σ w_k·S_k) ≤
     Σ w_k·σmax(S_k) ≤ 1），故无源锚点的凸组合严格无源；物理语义：局部
     平滑响应假设下锚点间响应的一阶插值估计——"合法但不来自真实仿真"。
     两项探针实证的设计裁定（W4-4 收口 2×2 分解实验，详见交付报告）：
     ① 曲线权重=全锚点 IDW（本实现）在表征偏差主导的现实 regime 4 抽样
     均值最优；② 曲线权重=参数对同权（双线性变体）与近邻对限制各在
     "基精确+强非线性"人工 regime 略优但整体混合——两者以旋钮留面
     （k_nearest 限制候选对距），默认走 §7.2 本义。混合偏差的诚实边界：
     凸组合曲线在非线性参数→曲线映射下带 O(h²) 单侧（Jensen 型）偏置，
     无消费侧加权时可能退化——regime 边界数字见收口实验与交付报告。
     防泄露：虚拟参数点与任何锚点/已生成虚拟点的归一化距离 < min_rel_dist
     时弃置（虚拟点不得落在锚点上——验证集锚点隔离语义的生成端守护）。
  B. ``port_scale``（端口无源缩放族，选装 n_scale>0）：
     S_v(f) = α·S_i(f)，α∈(0,1]。物理语义：端口串接匹配衰减器（|S21|=√α
     的匹配衰减网络级联后 S11 恰乘 α）——幅值整体收缩、无源性严格保持；
     几何参数不变（衰减元件在几何参数空间之外）。诚实注记：同参数异
     曲线样本对确定性"参数→曲线"映射是不可学习的冲突样本，本族提供的是
     幅值鲁棒正则样本而非新几何信息——默认关闭（n_scale=0），启用需
     自行评估对映射一致性的影响。
     （未选族注记：共轭对称族 S(-f)=conj(S(f)) 对正频栅格采样不产生
     独立信息——实系统谱对称意味着镜像即同一器件；已知解析核的延迟族
     exp(-2πjf·τ)（端口参考面外推）同为参数不变的曲线空间扰动，与 B
     同属"不带新几何信息"类，机制层不重复落。）

判据语义（"生成样本必须过 passivity_verdict"）：
    曲线模式（锚点含 CURVE_KEY）下，锚点曲线先逐一过无源性判据（脏锚点
    ValueError 点名——#316 兜底方向选"多报"不选"放过"），生成曲线再逐一
    过判据（无源锚点的凸组合按凸性定理必过，该闸是数值安全网，触发即
    深层错误）。标量模式（无 CURVE_KEY）无曲线可判，不涉无源性。
"""

from __future__ import annotations

from typing import Any

import numpy as np

from .pole_residue import CURVE_KEY, passivity_verdict

__all__ = [
    "VIRTUAL_WEIGHT_KEY",
    "generate_virtual_samples",
]

#: 样本字典上的可选置信度权重键（W4-3 预留接口点；消费面现阶段忽略）。
#: 语义：值域 [0, 1]，越大越可信——blend 族 = 1 − 到最近锚点的归一化距离
#: （越贴锚点越可信，中点最不可信），scale 族 = α（衰减越深越偏离真器件）。
VIRTUAL_WEIGHT_KEY = "virtual_weight"

#: 虚拟样本出处注记键（family/anchors/插值比或 α），消费方与审计面可读。
VIRTUAL_META_KEY = "virtual"


def _normalized(params: dict[str, float], keys: list[str],
                bounds: dict[str, tuple[float, float]] | None) -> np.ndarray:
    """参数字典 → 归一化向量（bounds 给定按 bounds，否则按原值直通）。"""
    vals = []
    for k in keys:
        v = float(params[k])
        if bounds is None:
            vals.append(v)
        else:
            lo, hi = bounds[k]
            vals.append((v - lo) / (hi - lo) if hi > lo else 0.0)
    return np.array(vals, dtype=float)


def _denormalized(x: np.ndarray, keys: list[str],
                  bounds: dict[str, tuple[float, float]] | None) -> dict[str, float]:
    """归一化向量 → 参数字典（_normalized 的精确逆映射）。"""
    out: dict[str, float] = {}
    for k, xv in zip(keys, x, strict=False):
        if bounds is None:
            out[k] = float(xv)
        else:
            lo, hi = bounds[k]
            out[k] = float(lo + xv * (hi - lo)) if hi > lo else float(lo)
    return out


def _blend_metrics(anchors: list[dict[str, Any]],
                   weights: np.ndarray, keys: list[str]) -> dict[str, Any]:
    """按凸权重混合锚点 metrics：曲线键逐点凸组合，全锚点共有且全数值的
    标量键线性凸组合；缺失/非数值键不伪造（如实省略）。"""
    out: dict[str, Any] = {}
    for k in keys:
        if k == CURVE_KEY:
            stack = np.vstack([np.asarray(a["metrics"][k], dtype=complex)
                               for a in anchors])
            out[k] = weights @ stack
            continue
        vals = [a["metrics"][k] for a in anchors]
        if all(isinstance(v, (int, float)) and not isinstance(v, bool)
               for v in vals):
            out[k] = float(weights @ np.array(vals, dtype=float))
    return out


def generate_virtual_samples(
    samples: list[dict[str, Any]], *,
    bounds: dict[str, tuple[float, float]] | None = None,
    n_blend: int = 8,
    n_scale: int = 0,
    seed: int = 42,
    idw_power: float = 2.0,
    k_nearest: int | None = None,
    min_rel_dist: float = 0.05,
    blend_t_range: tuple[float, float] = (0.3, 0.7),
    scale_alpha_range: tuple[float, float] = (0.5, 0.9),
) -> list[dict[str, Any]]:
    """从稀疏真实锚点样本合成虚拟样本（§7.2 机制层，纯函数零 I/O）。

    输入锚点即 SurrogateModel 契约同构样本
    ``[{"params": {...}, "metrics": {...}}]``，产出同构字典列表可直接
    ``samples + generate_virtual_samples(samples, ...)`` 追加进
    PoleResidueSurrogate/NNSurrogate.fit（另附 VIRTUAL_WEIGHT_KEY /
    VIRTUAL_META_KEY 两个信息键，消费方现阶段忽略）。

    曲线模式（全部锚点含 CURVE_KEY）下无源性判据全链启用：锚点逐一判
    （脏锚点 ValueError 点名），生成逐一判（凸性下不可触发的安全网）。
    标量模式（无锚点含 CURVE_KEY）只做参数/标量凸组合插值。

    参数：
        bounds: 参数归一化空间（距离/插值/去重都在该空间做）；None 时
            用原值空间（调用方须自行保证参数量纲可比）。
        n_blend: anchor_blend 族数量（凸组合插值，默认 8）。
        n_scale: port_scale 族数量（匹配衰减器缩放，默认 0=关闭）；
            不得超过锚点数（每锚点至多一条，避免同参数多族冲突叠加）。
        seed: 随机源种子（同种子两跑逐位一致）。
        idw_power: IDW 距离幂次（全锚点 w_k ∝ 1/d^p，曲线/标量混合权重）。
        k_nearest: 候选对的近邻数限制；None（缺省）= 全域随机对（§7.2
            本义）。给定正整数时锚点 i 的候选伙伴只取其 k 近邻——局部插值
            降低非线性映射下的二阶混合偏差，但域覆盖杠杆随之下降（2×2
            探针权衡，见族 A 注记）。
        min_rel_dist: 虚拟参数点与锚点/已生成虚拟点的最小归一化距离
            （防泄露守护：虚拟点不得落在锚点上）。
        blend_t_range: 锚点对凸组合插值比范围（须含于 (0,1) 且不触 0/1，
            默认 (0.3, 0.7)——贴边即近锚点重复，由去重守护兜底）。
        scale_alpha_range: port_scale 缩放系数范围（须含于 (0,1]）。

    返回：虚拟样本字典列表（可能少于 n_blend + n_scale——去重守护弃置
    近重复候选；弃置不静默伪造，数量即 len(返回值)）。

    异常：锚点数 <2、参数键集不一致、曲线有无不一致、曲线等长性破坏、
    bounds 覆盖不全、脏锚点（非无源曲线）、生成曲线判据失败、
    n_scale 超锚点数、区间参数非法——一律 ValueError 点名。
    """
    if len(samples) < 2:
        raise ValueError("generate_virtual_samples：至少需要 2 个锚点样本")
    if not 0.0 < blend_t_range[0] < blend_t_range[1] < 1.0:
        raise ValueError("blend_t_range 须为 0 < lo < hi < 1")
    if not 0.0 < scale_alpha_range[0] <= scale_alpha_range[1] <= 1.0:
        raise ValueError("scale_alpha_range 须为 0 < lo <= hi <= 1")
    if idw_power <= 0:
        raise ValueError("idw_power 必须为正")
    if k_nearest is not None and int(k_nearest) < 1:
        raise ValueError("k_nearest 须为 None 或正整数")
    if min_rel_dist < 0:
        raise ValueError("min_rel_dist 不能为负")
    if n_blend < 0 or n_scale < 0:
        raise ValueError("n_blend/n_scale 不能为负")

    keys = sorted(samples[0].get("params") or {})
    if not keys:
        raise ValueError("generate_virtual_samples：锚点 params 不得为空")
    for idx, s in enumerate(samples):
        if sorted(s.get("params") or {}) != keys:
            raise ValueError(
                f"generate_virtual_samples：锚点 {idx} 参数键集与锚点 0 不一致")
    if bounds is not None:
        missing = [k for k in keys if k not in bounds]
        if missing:
            raise ValueError(
                f"generate_virtual_samples：bounds 未覆盖参数键 {missing}")

    has_curve = [CURVE_KEY in (s.get("metrics") or {}) for s in samples]
    if any(has_curve) and not all(has_curve):
        raise ValueError(
            "generate_virtual_samples：CURVE_KEY 必须全锚点都有或都没有"
            "（混合形态的插值语义不定义）")
    if n_scale > len(samples):
        raise ValueError(
            f"generate_virtual_samples：n_scale={n_scale} 超过锚点数 "
            f"{len(samples)}（每锚点至多一条缩放样本）")

    if has_curve[0]:
        n_freq = len(samples[0]["metrics"][CURVE_KEY])
        curves = []
        for idx, s in enumerate(samples):
            try:
                c = np.asarray(s["metrics"][CURVE_KEY], dtype=complex)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"generate_virtual_samples：锚点 {idx} 的 {CURVE_KEY} "
                    f"不可转为复数曲线") from exc
            if c.ndim != 1 or len(c) != n_freq:
                raise ValueError(
                    f"generate_virtual_samples：锚点 {idx} 曲线长度 "
                    f"{len(c)} ≠ 锚点 0 的 {n_freq}")
            verdict = passivity_verdict(c)
            if not verdict["passive"]:
                raise ValueError(
                    f"generate_virtual_samples：锚点 {idx} 曲线非无源"
                    f"（σmax={verdict['sigma_max_in_band']:.6g} > 1+tol，"
                    f"脏数据不进虚拟样本——#316 多报不放过）")
            curves.append(c)
        curves_mat = np.vstack(curves)
    else:
        curves_mat = None

    pts = np.vstack([_normalized(s["params"], keys, bounds)
                     for s in samples])
    common_metric_keys = sorted(set(samples[0].get("metrics") or {})
                                .intersection(
                                    *(set(s.get("metrics") or {})
                                      for s in samples[1:])))
    rng = np.random.default_rng(seed)
    out: list[dict[str, Any]] = []
    made_pts: list[np.ndarray] = []

    # ── 族 A：anchor_blend（锚点对 IDW 凸组合插值，§7.2 本义） ─────────────
    # 候选对缺省全域随机（k_nearest=None）；k_nearest 给定时限制为近邻对
    #（局部插值旋钮——权衡注记见模块 docstring 族 A）。曲线权重=全锚点
    # IDW（w ∝ 1/d^idw_power，归一化非负和一）——§7.2"IDW 插值"本义，
    # 2×2 分解探针中现实 regime 均值最优（W4-4 报告）。
    n_anchor = len(samples)
    k_eff = (int(min(max(int(k_nearest), 1), n_anchor - 1))
             if k_nearest is not None else None)
    max_attempts = max(n_blend, 1) * 8
    attempts = 0
    while len(made_pts) < n_blend and attempts < max_attempts:
        attempts += 1
        i = int(rng.integers(0, n_anchor))
        if k_eff is None:
            j = int(rng.integers(0, n_anchor))
            if j == i:
                continue
        else:
            d_to_i = np.sqrt(((pts - pts[i]) ** 2).sum(axis=1))
            d_to_i[i] = np.inf
            near = np.argsort(d_to_i, kind="stable")[:k_eff]
            j = int(near[int(rng.integers(0, k_eff))])
        t = rng.uniform(*blend_t_range)
        x_v = (1.0 - t) * pts[i] + t * pts[j]
        dists_anchor = np.sqrt(((pts - x_v) ** 2).sum(axis=1))
        d_min = float(dists_anchor.min())
        if d_min < min_rel_dist:
            continue
        if made_pts:
            d_made = float(np.sqrt(
                ((np.vstack(made_pts) - x_v) ** 2).sum(axis=1)).min())
            if d_made < min_rel_dist:
                continue
        w = 1.0 / np.maximum(dists_anchor, 1e-300) ** idw_power
        if not np.isfinite(w).all() or w.sum() <= 0.0:
            continue
        weights = w / w.sum()
        metrics = _blend_metrics(samples, weights, common_metric_keys)
        if curves_mat is not None:
            verdict = passivity_verdict(metrics[CURVE_KEY])
            if not verdict["passive"]:
                raise ValueError(
                    "generate_virtual_samples：生成曲线未过无源性判据"
                    f"（σmax={verdict['sigma_max_in_band']:.6g}；无源锚点的"
                    f"凸组合按凸性必无源，此为深层错误——请查锚点数据）")
        out.append({
            "params": _denormalized(x_v, keys, bounds),
            "metrics": metrics,
            VIRTUAL_WEIGHT_KEY: float(max(1.0 - d_min, 0.0)),
            VIRTUAL_META_KEY: {
                "family": "anchor_blend",
                "anchors": [int(i), int(j)],
                "t": float(t),
            },
        })
        made_pts.append(x_v)

    # ── 族 B：port_scale（匹配衰减器缩放，选装） ──────────────────────────
    if n_scale > 0:
        for i in rng.permutation(n_anchor)[:n_scale]:
            alpha = rng.uniform(*scale_alpha_range)
            if curves_mat is not None:
                metrics = {CURVE_KEY: alpha * curves_mat[i]}
                verdict = passivity_verdict(metrics[CURVE_KEY])
                if not verdict["passive"]:
                    raise ValueError(
                        "generate_virtual_samples：缩放曲线未过无源性判据"
                        f"（σmax={verdict['sigma_max_in_band']:.6g}；"
                        f"α≤1 的无源曲线缩放按 |αS|=α|S| 必无源，此为深层"
                        f"错误——请查锚点数据）")
            else:
                metrics = {
                    k: float(alpha * float(v))
                    for k, v in (samples[i].get("metrics") or {}).items()
                    if isinstance(v, (int, float))
                    and not isinstance(v, bool)}
            out.append({
                "params": dict(samples[i]["params"]),
                "metrics": metrics,
                VIRTUAL_WEIGHT_KEY: float(alpha),
                VIRTUAL_META_KEY: {
                    "family": "port_scale",
                    "anchors": [int(i)],
                    "alpha": float(alpha),
                },
            })
    return out
