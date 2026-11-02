"""参数化 VF 宏模型邻域插值（T-N15，aurora_n W2；pole_residue 触发③落地）。

定位（proposal runs/aurora_n/recon/PROPOSALS.md T-N15 的最小可用形态）：
    "参数→曲线"邻域代理的工程化封装——N 个参数样本点各做一次固定极点基
    读出（逐样本 {留数, d, e} 表），新参数点在参数空间做邻域局部线性插值
    得到曲线，附样本凸包外推判据。注册键 ``vf_parametric``（SurrogateModel
    契约），与 pole_residue 同基座并列。

选型声明（任务书预声明 a 案；b 案否决）：
    a 案（本模块）：固定极点基（pole_residue.default_pole_basis，频带内对数
    栅格、严格左半平面）——逐样本在**同一基**上闭式 LS 读出留数/常数项，
    极点与参数无关，样本间系数天然对齐，插值良定义。
    b 案（逐样本 skrf VectorFitting + 极点匹配）：否决。VF 各样本极点集无
    对应关系且数值散布极端（开发期探针 runs/aurora_n/w2_tn15/
    probe_selection.py 实测：同族 4 样本 (2 实+3 对) VF 极点虚部跨
    1e0..1e15 GHz 量级、两样本触 N_max=100 非收敛告警、病态条件数 1e17）
    ——Hungarian/贪心匹配在极点漂移下脆弱，且匹配后插值对匹配误差无界。
    故本模块不调用 skrf VF；macromodel 的单数据集 VF 链（阶数搜索/无源化/
    SPICE 导出）不在本席范围。

与既有面的关系（复用优于自造，拟合内核零复制）：
    - 极点基/闭式读出/模型评估/theta 换算全部复用 pole_residue（单源）：
      default_pole_basis / fit_residues / evaluate_pole_residue /
      model_to_theta / theta_to_model；本模块新增=①逐样本批量化读出表
      ②参数空间邻域局部线性插值头（区别于 pole_residue 的全局 ridge/mlp
      回归头）③样本凸包外推判据 ④vf_parametric 注册键。
    - 无源性容差 PASSIVITY_TOL 经 pole_residue.passivity_verdict 单源
      （其自 core.macromodel 导入），本模块不设第二常量源。

插值数学（等效核视角，确定性零随机）：
    评估对 theta 线性（y = A(f)·theta），故 theta 空间的仿射组合与曲线空间
    的同权仿射组合逐点等价——响应级插值形态完全由"等效核权重"决定：
    局部线性（LOESS 式）加权 LS 的截距等价权 w̃ 满足 Σw̃=1，对**仿射**
    theta(param) 逐位精确回收（k ≥ d+1 仿射无关时）。权 = W·X·(XᵀWX)⁻¹e₁，
    W=距离^(-power)（IDW-squared 缺省），查询点即中心（设计阵 [1, x_i−q]）。
    精确命中分支：查询点与某样本参数重合（归一化距离 < 1e-12）时直接返回
    该样本读出系数——训练点回代与逐点直接拟合逐位一致（测试钉住）。
    系数层病态说明：固定基读出在非基内真极点族上系数含近消去结构（伪留数），
    但等效核只做权和非求解，系数表各行为同一 LS 的健康输出（探针
    probe_calib.py 实测内点响应级 RMSE 3.4e-3..7.5e-3，逐点直接拟合地板
    ~1e-5），曲线/系数仿射等价保证无额外病态放大。

外推判据（T-N3 band_edge_verdict 同款 warn 语义，不阻断预测）：
    新参数点（归一化空间）在样本凸包外（带 1e-9 容差的半空间判）→
    param_extrapolation=extrapolation_warn；凸包内/边界=ok。1-D 参数取
    样本区间；d≥2 用 scipy ConvexHull（scipy 为既有核心依赖，零新增）；
    退化点集（共线/低维）QhullError 时如实降级 bbox 判（hull_kind=
    bbox_fallback——bbox 是凸包的保守外接，可能漏报"包内 hull 外"的点，
    消费方对 hull_kind=bbox_fallback 的 warn 应理解为下界）。warn 档
    供消费方降权/拒绝采信，本模块预测不因此阻断。

确定性红线（AGENTS 7）：极点基/列均衡/LS/等效核权重全链闭式零随机；
argsort 用 stable 序；同配置同数据两跑 fit/predict/verdict 逐位一致
（测试钉住）。config["seed"] 为契约占位位（int 校验后不消费——本实现
无任何随机源，值不影响输出，见 fit docstring）。

负例契约（验收④，显式报错不静默）：
    - 有效曲线样本 N<3 → ValueError（邻域插值至少 3 点）；
    - 样本/predict 的 params 与 bounds 键集不匹配（缺键/多键）→ ValueError
      （有意严于 pole_residue 的缺键补中点——邻域插值语义下静默补点会
      伪造置信度）；曲线缺失/非复数可转/长度不符按基类契约跳过（对应
      真机失败 trial），跳过计数进 fit 返回值。

多端口增量（aurora_p D2；设计半页 runs/aurora_p/d2/DESIGN.md）：
    **扩既有键**（config 新增 ``n_ports``，缺省 1）——零新注册键零注册面
    改动。``n_ports=1``（或缺省）走 v1 单端口原路径**逐字节**（s11_curve、
    theta 布局、info/predict 键面全不变，既有钉零改动全绿为门）；
    ``n_ports≥2`` 进多端口模式：

    - 模型：S_ij(s)=Σ_k r_ij,k(θ)/(s−p_k)+d_ij(θ)+e_ij(θ)·s——**公共极点
      跨条目共享**（固定基与 θ 无关，条目间系数天然对齐，v1 选型 a 案的
      多端口直推广），**逐条目**走 pole_residue.fit_residues 闭式 LS
      （拟合内核零复制零新写）。
    - 互易按构造（红线）：只参数化上三角 P(P+1)/2 条目（r_ij=r_ji），
      predict 对称填充 ⇒ S=Sᵀ 逐位成立（green_op 先例）；reciprocal 不可
      配=按设计定死。非互易输入样本按 (S+Sᵀ)/2 对称化进 fit 并如实报告
      ``max_reciprocity_residual_train``（不静默不拒绝，green_op 同款）。
    - 数据形态：metrics 键=``s_matrix``（复用 green_operator.RESPONSE_KEY
      单源，复数栈 (n_freq, P, P)）；曲线/矩阵缺失、形状不符、含非有限值
      的行按基类契约跳过计数；params 键集不匹配仍显式 ValueError。
    - theta 布局：条目块拼接 concat(model_to_theta(entry_p))——每块
      2·n_poles+4 维，theta_to_model 逐块直接复用（零新逆映射）。评估对
      θ 线性 ⇒ 等效核插值论证逐字适用（同 local_linear_weights 单源）。
    - 无源性：passivity_verdict 单源**逐成员**消费（单源不支持 4-D 栈——
      每样本 (n_freq,P,P) 3-D 调用后聚合 sigma_max=max / λmin=min /
      passive=all，``n_members`` 如实透出；聚合语义=单源 docstring
      "任一成员任一频点违例即整批判非无源"，不复制公式）。
    - 多端口主面：``predict_matrix`` / ``predict_matrix_with_verdict``
      （(n_freq,P,P) 栈）；``predict_curve`` 多端口模式返回 S11 条目
      （[0,0]，1-D 便捷面）；``predict`` 出逐上三角条目
      ``s{i}{j}_db_max/min_in_band`` 键（green_op 命名单源复用）。
"""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy.spatial import ConvexHull, QhullError

from .base import SurrogateModel, surrogate_registry
from .green_operator import RESPONSE_KEY, _entry_name
from .pole_residue import (
    CURVE_KEY,
    default_pole_basis,
    evaluate_pole_residue,
    fit_residues,
    model_to_theta,
    passivity_verdict,
    theta_to_model,
)

__all__ = [
    "ParamVFSurrogate",
    "convex_hull_verdict",
    "local_linear_weights",
]

#: 归一化参数空间的凸包判容差（半空间判据的数值零位）。
_HULL_TOL = 1e-9
#: 精确命中判容差（归一化参数距离，训练点回代逐位一致分支）。
_EXACT_HIT_TOL = 1e-12
#: 有效曲线样本下限（验收④负例阈值）。
_MIN_CURVES = 3


# ─── 邻域等效核（局部线性加权 LS 的等价权重） ────────────────────────────────


def local_linear_weights(
    sample_x: np.ndarray, x_query: np.ndarray, k_neighbors: int = 4,
    power: float = 2.0,
) -> tuple[np.ndarray, np.ndarray, bool]:
    """局部线性（LOESS 式）加权 LS 的等效核权重。

    数学：查询点为中心的设计阵 X=[[1, x_i−q]]，权 W=diag(dist^(-power))，
    截距等价权 w̃ = W·X·(XᵀWX)⁻¹e₁（Σw̃=1，对仿射数据逐位精确）。
    精确命中（最近距离 < 1e-12）→ 该样本独占权 1（训练点回代逐位一致）。

    返回 (weights 全长 N、neighbor_idx 升距序、exact_hit)；
    ValueError：形状/维度不匹配、k<1、power<=0、非有限值。
    """
    pts = np.asarray(sample_x, dtype=float)
    q = np.asarray(x_query, dtype=float)
    if pts.ndim != 2 or pts.shape[0] == 0:
        raise ValueError(
            f"local_linear_weights：sample_x 须为非空 (N, d) 二维数组，"
            f"实得 shape {pts.shape}")
    n_dim = pts.shape[1]
    if q.shape != (n_dim,):
        raise ValueError(
            f"local_linear_weights：x_query 维度 {q.shape} ≠ 样本维度 "
            f"({n_dim},)")
    if not np.isfinite(pts).all() or not np.isfinite(q).all():
        raise ValueError("local_linear_weights：样本/查询点含非有限值")
    if int(k_neighbors) < 1:
        raise ValueError("local_linear_weights：k_neighbors 至少为 1")
    if power <= 0:
        raise ValueError("local_linear_weights：power 必须为正")
    k = min(int(k_neighbors), pts.shape[0])
    dists = np.linalg.norm(pts - q[None, :], axis=1)
    idx = np.argsort(dists, kind="stable")[:k]
    weights = np.zeros(pts.shape[0], dtype=float)
    if dists[idx[0]] < _EXACT_HIT_TOL:
        weights[idx[0]] = 1.0
        return weights, idx, True
    local = pts[idx] - q[None, :]
    design = np.column_stack([np.ones(k), local])
    w_d = dists[idx] ** (-float(power))
    gram = design.T @ (design * w_d[:, None])
    unit = np.zeros(gram.shape[0], dtype=float)
    unit[0] = 1.0
    # gram 对称半正定；近奇异（k=d+1 共线等）走 min-norm 仍确定性
    coef = np.linalg.lstsq(gram, unit, rcond=None)[0]
    weights[idx] = w_d * (design @ coef)
    return weights, idx, False


# ─── 样本凸包外推判据（归一化参数空间） ──────────────────────────────────────


def convex_hull_verdict(
    sample_x: np.ndarray, x_query: np.ndarray, tol: float = _HULL_TOL,
) -> dict[str, Any]:
    """查询点是否落在样本参数凸包内（归一化空间，warn 档判据）。

    返回 verdict dict：param_extrapolation = ok|extrapolation_warn /
    hull_kind = interval(1-D)|convex_hull(d≥2)|bbox_fallback（退化点集
    QhullError 的保守外接降级）/ margin（带符号距离，≤0 在包内/边界，
    >tol 判外）/ tol / n_dim / n_samples。
    """
    pts = np.asarray(sample_x, dtype=float)
    q = np.asarray(x_query, dtype=float)
    if pts.ndim != 2 or pts.shape[0] == 0:
        raise ValueError(
            f"convex_hull_verdict：sample_x 须为非空 (N, d) 二维数组，"
            f"实得 shape {pts.shape}")
    if tol <= 0:
        raise ValueError("convex_hull_verdict：tol 必须为正")
    n_dim = pts.shape[1]
    if q.shape != (n_dim,):
        raise ValueError(
            f"convex_hull_verdict：x_query 维度 {q.shape} ≠ 样本维度 "
            f"({n_dim},)")
    if n_dim == 1:  # 1-D：样本区间即凸包，闭式判
        lo, hi = float(pts[:, 0].min()), float(pts[:, 0].max())
        margin = max(lo - float(q[0]), float(q[0]) - hi)
        kind = "interval"
    else:
        kind, margin = "convex_hull", None
        try:
            hull = ConvexHull(pts)
            margin = float((hull.equations[:, :n_dim] @ q
                            + hull.equations[:, n_dim]).max())
        except QhullError:
            # 退化点集（共线/低维）：bbox 保守外接降级（如实标注 hull_kind）
            kind = "bbox_fallback"
            margin = float(max(
                (q - pts.max(axis=0)).max(), (pts.min(axis=0) - q).max()))
    outside = bool(margin > tol)
    return {
        "param_extrapolation": "extrapolation_warn" if outside else "ok",
        "hull_kind": kind,
        "margin": margin,
        "tol": float(tol),
        "n_dim": int(n_dim),
        "n_samples": int(pts.shape[0]),
    }


# ─── 曲线代理（kind="vf_parametric"，SurrogateModel 契约） ───────────────────


def _to_db(curve: np.ndarray) -> np.ndarray:
    floor = 1e-30
    return 20.0 * np.log10(np.maximum(np.abs(curve), floor))


@surrogate_registry.register("vf_parametric")
class ParamVFSurrogate(SurrogateModel):
    """参数→固定极点基系数→邻域插值→S 曲线的物理先验代理（T-N15）。

    契约与样本格式（与 pole_residue 同构）：
        samples = [{"params": {param: value},
                    "metrics": {"s11_curve": 复数 S11(f) 数组（Hz 栅格，
                                与 config 频带/点数一致）}}]
    曲线缺失/非复数可转/长度不符的行按基类契约跳过（计数进 fit 返回值）；
    **有曲线的行** params 必须与 bounds 键集完全一致，否则 ValueError
    （负例④：参数维度不匹配显式报错）。

    config:
        bounds: {param: (low, high)}（必填；参数线性映射到 [-1,1]）
        freq_grid_ghz: (f_lo, f_hi) 曲线频带（GHz，必填）
        n_freq: 训练栅格点数（默认 81，须 ≥ 极点数+4——fit_residues 容量）
        n_real_poles / n_cmplx_pairs / zeta: 极点基形态（默认 2/3/0.7，
            与 pole_residue 同缺省；固定基在拟合/预测两态共用）
        k_neighbors: 邻域样本数（默认 4；自动抬到 max(k, d+1) 保证
            仿射可解，封顶 N）
        idw_power: 距离权指数（默认 2.0，IDW-squared）
        seed: 契约占位位（int；本实现全链闭式零随机，值不影响输出）
        n_ports: 端口数 P（默认 1=v1 单端口原路径；≥2=多端口矩阵模式，
            样本 metrics 键 s_matrix=(n_freq,P,P) 复数栈，互易上三角
            按构造，详见模块 docstring 多端口节）
    """

    KIND = "vf_parametric"

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        bounds = self.config.get("bounds")
        if not bounds:
            raise ValueError("ParamVFSurrogate：config['bounds'] 必填")
        self.bounds = {k: (float(v[0]), float(v[1])) for k, v in bounds.items()}
        for name, (lo, hi) in self.bounds.items():
            if not lo < hi:
                raise ValueError(
                    f"ParamVFSurrogate：bounds[{name!r}] 须 low < high"
                    f"（实得 {lo}, {hi}）")
        self.param_names = sorted(self.bounds)
        grid = self.config.get("freq_grid_ghz")
        if not grid or len(grid) != 2 or float(grid[1]) <= float(grid[0]):
            raise ValueError(
                "ParamVFSurrogate：config['freq_grid_ghz'] 须为 "
                "(f_lo, f_hi) 且 f_lo < f_hi")
        self.f_lo_hz = float(grid[0]) * 1e9
        self.f_hi_hz = float(grid[1]) * 1e9
        self.n_freq = int(self.config.get("n_freq", 81))
        self.n_real_poles = int(self.config.get("n_real_poles", 2))
        self.n_cmplx_pairs = int(self.config.get("n_cmplx_pairs", 3))
        self.zeta = float(self.config.get("zeta", 0.7))
        self.k_neighbors = int(self.config.get("k_neighbors", 4))
        self.idw_power = float(self.config.get("idw_power", 2.0))
        self.seed = int(self.config.get("seed", 42))  # 契约占位，零随机不消费
        # 多端口增量（D2）：n_ports 缺省 1=v1 单端口原路径逐字节；≥2=矩阵模式
        self.n_ports = int(self.config.get("n_ports", 1))
        if self.n_ports < 1:
            raise ValueError(
                f"ParamVFSurrogate：config['n_ports'] 须 ≥1（实得 "
                f"{self.n_ports}）")
        self._nport_mode = self.n_ports >= 2
        # 互易按构造：上三角条目序（含对角），predict 对称填充（green_op 先例）
        self._pairs = ([(i, j) for i in range(self.n_ports)
                        for j in range(i, self.n_ports)]
                       if self._nport_mode else None)
        # 极点基仅由 config 决定 → 构造期建立并校验容量（fail fast，
        # 容量口径=fit_residues 的 n_freq ≥ n_poles+4）
        self._poles = default_pole_basis(
            self.f_lo_hz, self.f_hi_hz, self.n_real_poles,
            self.n_cmplx_pairs, self.zeta)
        if self.n_freq < len(self._poles) + 4:
            raise ValueError(
                f"ParamVFSurrogate：n_freq={self.n_freq} 不足以支撑 "
                f"{len(self._poles)} 极点基（fit_residues 需 ≥ "
                f"{len(self._poles) + 4}）")
        self._freq_hz: np.ndarray | None = None
        self._theta_table: np.ndarray | None = None
        self._sample_x: np.ndarray | None = None
        self._k_eff: int | None = None

    # ── 内部 ──
    def _check_params(self, params: dict[str, float], where: str) -> None:
        """params 键集与 bounds 严格一致校验（负例④：维度不匹配显式报错）。"""
        given = set(params)
        want = set(self.param_names)
        if given != want:
            raise ValueError(
                f"{where}：params 键集与 bounds 不匹配（缺="
                f"{sorted(want - given)}，多={sorted(given - want)}）")

    def _norm_params(self, params: dict[str, float]) -> np.ndarray:
        x = []
        for k in self.param_names:
            lo, hi = self.bounds[k]
            half = 0.5 * (hi - lo)
            try:
                val = float(params[k])
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"ParamVFSurrogate：params[{k!r}] 不可转 float") from exc
            x.append((val - 0.5 * (lo + hi)) / (half if half else 1.0))
        return np.array(x, dtype=float)

    def _theta_at(self, x_query: np.ndarray) -> np.ndarray:
        weights, idx, exact = local_linear_weights(
            self._sample_x, x_query, self._k_eff, self.idw_power)
        if exact:
            return self._theta_table[idx[0]].copy()
        return weights @ self._theta_table

    # ── SurrogateModel 契约 ──
    def fit(self, samples: list[dict[str, Any]]) -> dict[str, Any]:
        if not samples:
            raise ValueError("ParamVFSurrogate.fit：无样本")
        if self._nport_mode:
            return self._fit_nport(samples)
        self._freq_hz = np.linspace(self.f_lo_hz, self.f_hi_hz, self.n_freq)
        xs: list[np.ndarray] = []
        thetas: list[np.ndarray] = []
        readout_rms: list[float] = []
        n_skipped = 0
        for idx, sample in enumerate(samples):
            metrics = sample.get("metrics") or {}
            raw = metrics.get(CURVE_KEY)
            if raw is None:
                n_skipped += 1
                continue
            try:
                curve = np.asarray(raw, dtype=complex)
            except (TypeError, ValueError):
                n_skipped += 1
                continue
            if curve.ndim != 1 or len(curve) != self.n_freq:
                n_skipped += 1
                continue
            params = sample.get("params") or {}
            # 负例④：有曲线的行参数维度不匹配 → 显式报错（不静默跳过）
            self._check_params(params, f"ParamVFSurrogate.fit：样本 {idx}")
            model = fit_residues(self._freq_hz, curve, self._poles)
            thetas.append(model_to_theta(model))
            xs.append(self._norm_params(params))
            readout_rms.append(model["rms"])
        if len(thetas) < _MIN_CURVES:
            raise ValueError(
                f"ParamVFSurrogate.fit：有效曲线样本 {len(thetas)} < "
                f"{_MIN_CURVES}（邻域插值至少需 {_MIN_CURVES} 点；跳过 "
                f"{n_skipped} 行）")
        self._theta_table = np.vstack(thetas)
        self._sample_x = np.vstack(xs)
        self._k_eff = min(max(self.k_neighbors, len(self.param_names) + 1),
                          len(thetas))
        readout_stack = np.vstack([
            evaluate_pole_residue(
                self._freq_hz, self._poles, m["residues"], m["d"], m["e"])
            for m in (theta_to_model(th, self._poles) for th in thetas)])
        info = self._mark_fitted(len(thetas))
        info.update({
            "n_curves": len(thetas),
            "n_skipped": n_skipped,
            "n_param_dims": len(self.param_names),
            "n_poles": len(self._poles),
            "k_eff": self._k_eff,
            "max_fit_rms": max(readout_rms),
            "passivity": passivity_verdict(readout_stack),
            "hull_kind": convex_hull_verdict(self._sample_x,
                                             self._sample_x[0])["hull_kind"],
            # hull_kind 借判据函数读出（查询点取首样本，只为取 hull 形态旗标）
            "interpolation": "local_linear_equivalent_kernel",
        })
        return info

    # ── 多端口模式（D2：公共极点跨条目共享 + 逐条目留数 LS + 互易按构造） ──
    def _fit_nport(self, samples: list[dict[str, Any]]) -> dict[str, Any]:
        """多端口 fit：s_matrix 样本逐条目闭式读出 + 条目块 theta 拼接。

        与 v1 单端口路径完全独立（v1 逐字节不受影响）；校验语义与 v1 同款：
        params 键集不匹配显式 ValueError（负例④），矩阵缺失/形状不符/
        含非有限值的行按基类契约跳过计数。
        """
        self._freq_hz = np.linspace(self.f_lo_hz, self.f_hi_hz, self.n_freq)
        xs: list[np.ndarray] = []
        thetas: list[np.ndarray] = []
        readout_rms: list[float] = []
        n_skipped = 0
        recip_resid = 0.0
        for idx, sample in enumerate(samples):
            metrics = sample.get("metrics") or {}
            raw = metrics.get(RESPONSE_KEY)
            if raw is None:
                n_skipped += 1
                continue
            try:
                s_stack = np.asarray(raw, dtype=complex)
            except (TypeError, ValueError):
                n_skipped += 1
                continue
            if (s_stack.ndim != 3
                    or s_stack.shape != (self.n_freq, self.n_ports,
                                         self.n_ports)):
                n_skipped += 1
                continue
            if not np.all(np.isfinite(s_stack)):
                n_skipped += 1
                continue
            params = sample.get("params") or {}
            # 负例④同款：有矩阵的行参数维度不匹配 → 显式报错（不静默跳过）
            self._check_params(params, f"ParamVFSurrogate.fit：样本 {idx}")
            # 互易按构造：样本对称化 (S+Sᵀ)/2（green_op 先例），非互易量如实报告
            asym = float(np.max(np.abs(
                s_stack - np.swapaxes(s_stack, 1, 2))))
            recip_resid = max(recip_resid, asym)
            s_sym = 0.5 * (s_stack + np.swapaxes(s_stack, 1, 2))
            blocks = []
            rms_max = 0.0
            for i, j in self._pairs:  # 逐条目闭式 LS（公共极点基单源）
                model = fit_residues(self._freq_hz, s_sym[:, i, j],
                                     self._poles)
                blocks.append(model_to_theta(model))
                rms_max = max(rms_max, model["rms"])
            thetas.append(np.concatenate(blocks))
            xs.append(self._norm_params(params))
            readout_rms.append(rms_max)
        if len(thetas) < _MIN_CURVES:
            raise ValueError(
                f"ParamVFSurrogate.fit：有效 {RESPONSE_KEY} 样本 "
                f"{len(thetas)} < {_MIN_CURVES}（邻域插值至少需 "
                f"{_MIN_CURVES} 点；跳过 {n_skipped} 行）")
        self._theta_table = np.vstack(thetas)
        self._sample_x = np.vstack(xs)
        self._k_eff = min(max(self.k_neighbors, len(self.param_names) + 1),
                          len(thetas))
        # 无源性：passivity_verdict 单源逐成员消费（单源不支持 4-D 栈——
        # 每样本 (n_freq,P,P) 3-D 调用后按单源批语义聚合，不复制公式）
        member_verdicts = [passivity_verdict(
            self._matrix_from_theta(th)) for th in thetas]
        agg = dict(member_verdicts[0])
        agg["sigma_max_in_band"] = max(
            v["sigma_max_in_band"] for v in member_verdicts)
        agg["lambda_min_i_minus_ssh"] = min(
            v["lambda_min_i_minus_ssh"] for v in member_verdicts)
        agg["passive"] = all(v["passive"] for v in member_verdicts)
        agg["n_members"] = len(member_verdicts)
        info = self._mark_fitted(len(thetas))
        info.update({
            "n_curves": len(thetas),
            "n_skipped": n_skipped,
            "n_param_dims": len(self.param_names),
            "n_ports": self.n_ports,
            "n_entries": len(self._pairs),
            "n_theta": int(self._theta_table.shape[1]),
            "k_eff": self._k_eff,
            "max_fit_rms": max(readout_rms),
            "passivity": agg,
            "max_reciprocity_residual_train": recip_resid,
            "hull_kind": convex_hull_verdict(self._sample_x,
                                             self._sample_x[0])["hull_kind"],
            "interpolation": "local_linear_equivalent_kernel",
        })
        return info

    def _matrix_from_theta(
            self, theta: np.ndarray,
            freq_hz: np.ndarray | None = None) -> np.ndarray:
        """条目块 theta → 复数 S 矩阵栈 (n_freq, P, P)（互易对称填充）。"""
        freq = self._freq_hz if freq_hz is None else freq_hz
        block = 2 * len(self._poles) + 4
        out = np.zeros((len(freq), self.n_ports, self.n_ports), dtype=complex)
        for p, (i, j) in enumerate(self._pairs):
            model = theta_to_model(theta[p * block:(p + 1) * block],
                                   self._poles)
            col = evaluate_pole_residue(freq, self._poles, model["residues"],
                                        model["d"], model["e"])
            out[:, i, j] = col
            if i != j:
                out[:, j, i] = col  # 同一数值双写 ⇒ S=Sᵀ 逐位成立
        return out

    def predict_matrix(self, params: dict[str, float],
                       freq_ghz: np.ndarray | None = None) -> np.ndarray:
        """多端口主面：预测参数对应的复数 S 矩阵栈 (n_freq, P, P)。

        freq_ghz 缺省=训练栅格（带内解析延拓面同 v1）；互易按构造 ⇒
        返回栈逐位对称（S=Sᵀ）。
        """
        if not self._fitted:
            raise RuntimeError("ParamVFSurrogate.predict_matrix：先 fit")
        self._check_params(params, "ParamVFSurrogate.predict_matrix")
        theta = self._theta_at(self._norm_params(params))
        freq_hz = (self._freq_hz if freq_ghz is None
                   else np.asarray(freq_ghz, dtype=float) * 1e9)
        return self._matrix_from_theta(theta, freq_hz)

    def predict_matrix_with_verdict(
            self, params: dict[str, float],
            freq_ghz: np.ndarray | None = None) -> dict[str, Any]:
        """多端口 predict_curve_with_verdict 对应面：矩阵栈 + 凸包外推判据。"""
        return {
            "matrix": self.predict_matrix(params, freq_ghz),
            "param_extrapolation": self.param_extrapolation_verdict(params),
        }

    def _predict_nport(self, params: dict[str, float]) -> dict[str, Any]:
        """多端口标量面：逐上三角条目 db_max/min（green_op 命名单源复用）。"""
        s = self.predict_matrix(params)
        db = _to_db(s)
        out: dict[str, Any] = {}
        for i, j in self._pairs:
            name = _entry_name(i, j, self.n_ports)
            out[f"{name}_db_max_in_band"] = float(db[:, i, j].max())
            out[f"{name}_db_min_in_band"] = float(db[:, i, j].min())
        out["param_extrapolation"] = self.param_extrapolation_verdict(params)[
            "param_extrapolation"]
        return out

    def param_extrapolation_verdict(
            self, params: dict[str, float]) -> dict[str, Any]:
        """参数点的样本凸包外推判据（warn 档；不阻断预测）。"""
        if not self._fitted:
            raise RuntimeError(
                "ParamVFSurrogate.param_extrapolation_verdict：先 fit")
        self._check_params(params, "ParamVFSurrogate.param_extrapolation_verdict")
        return convex_hull_verdict(self._sample_x, self._norm_params(params))

    def predict_curve(self, params: dict[str, float],
                      freq_ghz: np.ndarray | None = None) -> np.ndarray:
        """预测参数对应的复数 S11(f)（freq_ghz 缺省=训练栅格；带内解析延拓）。

        多端口模式下返回 S11 条目（矩阵 [0,0]，1-D 便捷面；全矩阵走
        predict_matrix 主面）。
        """
        if self._nport_mode:
            return self.predict_matrix(params, freq_ghz)[:, 0, 0]
        if not self._fitted:
            raise RuntimeError("ParamVFSurrogate.predict_curve：先 fit")
        self._check_params(params, "ParamVFSurrogate.predict_curve")
        theta = self._theta_at(self._norm_params(params))
        model = theta_to_model(theta, self._poles)
        freq_hz = (self._freq_hz if freq_ghz is None
                   else np.asarray(freq_ghz, dtype=float) * 1e9)
        return evaluate_pole_residue(freq_hz, self._poles, model["residues"],
                                     model["d"], model["e"])

    def predict_curve_with_verdict(
            self, params: dict[str, float],
            freq_ghz: np.ndarray | None = None) -> dict[str, Any]:
        """预测曲线 + 凸包外推判据合并面（"predict 新参数点的曲线+外推判据"）。"""
        return {
            "curve": self.predict_curve(params, freq_ghz),
            "param_extrapolation": self.param_extrapolation_verdict(params),
        }

    def predict(self, params: dict[str, float]) -> dict[str, Any]:
        if self._nport_mode:
            return self._predict_nport(params)
        curve = self.predict_curve(params)
        db = _to_db(curve)
        return {"s11_db_max_in_band": float(db.max()),
                "s11_db_min_in_band": float(db.min()),
                "param_extrapolation":
                    self.param_extrapolation_verdict(params)[
                        "param_extrapolation"]}

    def uncertainty(self, params: dict[str, float]) -> None:
        """无原生逐点不确定度（单头确定性模型，不伪造 σ——#122 诚实纪律）。"""
        return None
