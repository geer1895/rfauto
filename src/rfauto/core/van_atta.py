"""Van Atta 回射阵内核（配对拓扑 + 回射恒等式 + skrf 级联双路径 + 等长容差门）。

法源（铁律 5：来源写 docstring；裁判=独立路径互证，#118）：

- 拓扑与回射原理：E. D. Sharp & M. A. Diab, "Van Atta Reflector Array",
  IRE Transactions on Antennas and Propagation, vol. 8, no. 4, pp. 436-438
  (July 1960), DOI 10.1109/TAP.1960.1144877（2026-09-27 检索多源互证，
  引用链见 研究扩充 round4 [28]）；原始专利
  L. C. Van Atta, "Electromagnetic Reflector", US 2,908,002 (1959)。
  回射阵（retrodirective array）教科书口径：单元成对等长传输线互连，
  重辐射波前自动共轭、峰指回来波方向。
- 验证全分解（任务书规格，避免整体全波）：单元 S × skrf 等长线级联 ×
  阵因子——回射恒等式用 :func:`rfauto.core.array_synthesis.array_factor`
  数值验证，级联相位表用 skrf connect 级联 vs 闭式（含多次反射级数）
  双路径逐位对照。
- KiCad 链接口登记（本模块不做，属后续 fab 批）：开源参考板
  tryuan99/van-atta-x-4x4-pcb 对接 = 用 KiCad 侧提取的等长走线长度回填
  :class:`VanAttaArray` 的 ``line_lengths_lambda``（配对表+线长表即布线
  网表语义，λ 单位）→ :func:`equal_length_gate` 即成 fab 等长门；
  :func:`vanatta_wiring_table` 输出布线表供对账。

约定钉死（全模块一致，多版本相位约定中选此一种）：

- 单元位置居中（λ 单位）：x_n = (n − (N−1)/2)·d，n = 0..N−1，
  d = spacing_lambda；镜像配对 pair(n) = N−1−n 满足 x_pair(n) = −x_n。
- 扫描面：阵轴 x、扫描面含阵轴，方向余弦 u = sin θ（θ 自侧向
  broadside 起量）。k = 2π/λ 已按 λ 归一，全部相位无量纲弧度。
- 入射口径：来自 θ 的平面波在单元 n 上的接收相位
  v_n = e^{+j·2π·u·x_n}（朝源方向相位超前）。
- 回射恒等式（闭式推证）：信号 v_n 经线（相位 φ_line = 2π·L，L 为线长
  λ 数）自单元 pair(n) 重辐射，出射权重 w_m = v_pair(m)·e^{jφ_pair(m)}；
  镜像配对下 w_m = e^{−jku·x_m}·e^{jφ}（相位共轭斜坡），出射阵因子
  AF(u') = Σ_m w_m·e^{+jku'x_m} = e^{jφ}·Σ_m e^{jk(u'−u)x_m}
  峰恰在 u' = u（θ' = θ）——回射（Sharp-Diab 1960）。
- 奇数 N：中心元自配对 (c, c) 直通（信号经自身线回自身重辐射），
  w_c = e^{jφ_c}·e^{jku·0} 与 u 无关（各向同性自项），峰位不变——
  直通口径自洽（镜面恒等式对其余元逐元成立）。
- 自定义配对：允许任意对合置换（involution，含不动点），属研究面
  （what-if 拓扑）；回射恒等式与等长无倾斜不变量**仅对镜像配对预声明**
  （x_pair = −x 是推导的承重结构），自定义配对报告如实给实测不担保。

等长失配的诚实物理结论（1b 立规：先验模型再下结论；推导记档）：
线 k 的长度误差 δ_k = 2π·ΔL_k 对两个传播方向同相（互易），故出射相位
误差剖面 e(x_i) = e(x_{pair(i)}) = δ_k 关于口径中心**严格对称** → 奇
（线性）分量恒等于 0 → 波前倾斜恰为 0（精确，非小量近似），残效 =
相干增益损失 |⟨e^{jδφ}⟩|（镜像配对下 |AF(u)| = |Σ e^{j2πL_pair(m)}|
为精确恒等式，见 :func:`reradiated_af_peak`）。倾斜只出现在奇分量非零
的误差剖面（逐元独立误差的半 Van Atta/有源共轭变体），通用估计器
:func:`wavefront_tilt_estimate`（最小二乘斜率 → Δu = −slope/2π）覆盖
该面。λ/16 门 ↔ 任两线相位差 < 22.5°；相对均值的相位偏差至多取半
（<11.25°）→ 相干增益 ≥ cos(11.25°) ≈ 0.981 → 损耗 ≤ ~0.17 dB
（|⟨e^{jδ}⟩| ≥ cos(max|δ|) 对 |δ| ≤ π/2 成立）。

双路径（#118，不自证）：

- 相位表：skrf connect 级联（DefinedGammaZ0 等长线 + 参数化单元 S）vs
  闭式 T = τ²·e^{−jφ}/(1 − γ_l²·e^{−2jφ})（几何级数多次反射求和；
  γ_l 为单元线侧反射），预声明门 rel ≤ 1e-12。skrf line 传输 =
  e^{−γd}（DefinedGammaZ0 gamma=2πj、d=L_λ 时 S21 = e^{−j2πL}，2026-09-27
  探针实测钉死），闭式同号同约定。
- 回射角：array_factor 数值扫角 argmax vs 闭式 u' = u，预声明 ±0.5°
  带（等长完美线；网格分辨率限，缺省 20001 点实测 max|Δθ| ≈ 3e-3°）。

纯算法零 IO（skrf 仅在显式调用的级联路径内 import，butler_matrix 同族
惯例）；numpy 复数组进出，报告 JSON 可序列化（数值 0.0 合法，判缺失
一律 is not None，#364④；bool 显式拒收，df7+⑯）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from rfauto.core.array_synthesis import array_factor

#: 等长门惯例口径：max|ΔL| < λ/16 → PASS（相位误差 < 22.5°，参数可显式覆盖）
EQUAL_LENGTH_TOL_LAMBDA = 1.0 / 16.0
#: 回射角预声明验收带（deg，等长完美线）
RETRO_ANGLE_BAND_DEG = 0.5
#: 双路径互证预声明门（复数相对差）
TOL_DUAL_PATH = 1e-12
#: 相位剖面"对称"判定阈（rad/λ；镜像配对下拟合斜率为浮点零 ~1e-17）
_SYM_SLOPE_TOL = 1e-10
#: 双路径相对差分母的复数下限（防 0 除；退化 |closed|→0 时按 abs 差计）
_COMPLEX_FLOOR = 1e-300
#: 零和判定阈（与 array_synthesis._validate_weights 的拒收阈同值对齐）
_ZERO_SUM_TOL = 1e-12
#: 复权重拆分的公共旋转 e^{−jπ/4}：理想共轭斜坡权重（对称位置）虚部
#: 严格反对称 → ΣIm ≡ 0（φ=0 标称情形必触发 array_factor 的零和守卫）；
#: 旋转后 ΣRe = ΣIm = |Σw|/√2，双部件同时离开守卫（全局相位乘回复原）。
_SPLIT_ROTATION = np.exp(-1j * math.pi / 4.0)


def _finite(value, name: str) -> float:
    """入参收敛为有限 float；bool 显式拒收（float(True)=1.0 静默污染，df7+⑯）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数")
    return out


def _positive(value, name: str) -> float:
    """入参收敛为有限正 float，非法即显式报错。"""
    out = _finite(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须 >0")
    return out


def _check_index(value, name: str, n_elements: int) -> int:
    """配对端口号收敛：0..n−1 的严格整数（float/bool/str 一律 ValueError）。"""
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ValueError(f"{name} 须为 0..{n_elements - 1} 的整数，收到 {value!r}")
    idx = int(value)
    if not 0 <= idx < n_elements:
        raise ValueError(f"{name} 越界：{idx} 不在 0..{n_elements - 1}")
    return idx


def mirror_pairing(n_elements: int) -> tuple[tuple[int, int], ...]:
    """镜像配对表：pair(n) = N−1−n；奇数 N 中心元自配对 (c, c) 直通。

    返回按 i < pair(i) 升序的 (i, pair(i)) 元组（自配对 i == j），
    覆盖全部 N 个单元恰一次（对合置换 involution）。
    """
    if isinstance(n_elements, bool) or not isinstance(n_elements, (int, np.integer)):
        raise ValueError(f"n_elements 须为整数，收到 {n_elements!r}")
    n = int(n_elements)
    if n < 2:
        raise ValueError(f"n_elements 至少为 2，收到 {n}")
    pairs = []
    for i in range(n // 2):
        pairs.append((i, n - 1 - i))
    if n % 2 == 1:
        pairs.append((n // 2, n // 2))
    return tuple(pairs)


@dataclass(frozen=True)
class VanAttaArray:
    """Van Atta 阵静态拓扑（不可变；配对表 + 线长表，λ 单位）。

    pairing：对合置换表（(i, j) 元组序列，覆盖 0..N−1 恰一次；i == j 为
    直通自配对）；line_lengths_lambda：与 pairing 同序的线长（λ 数，
    >=0，0.0 = 全等长参考零相位）。JSON 可序列化经 :meth:`to_dict`。
    """

    n_elements: int
    spacing_lambda: float
    pairing: tuple[tuple[int, int], ...]
    line_lengths_lambda: tuple[float, ...]

    @property
    def center_index(self) -> int | None:
        """奇数 N 的中心元下标；偶数 N 为 None（判缺失 is not None）。"""
        if self.n_elements % 2 == 1:
            return self.n_elements // 2
        return None

    def positions_lambda(self) -> np.ndarray:
        """居中单元位置（λ 单位）：x_n = (n − (N−1)/2)·d。"""
        idx = np.arange(self.n_elements, dtype=float)
        return (idx - (self.n_elements - 1) / 2.0) * self.spacing_lambda

    def pair_of(self, element: int) -> int:
        """单元 element 的对端（自配对返回自身；对合置换双向可查）。"""
        for i, j in self.pairing:
            if element == i:
                return j
            if element == j:
                return i
        raise ValueError(f"单元 {element} 不在配对表中")  # pragma: no cover - 结构性守卫

    def line_length_of(self, element: int) -> float:
        """馈入单元 element 的线长（该单元所在对的线长，λ 数）。"""
        for (i, j), length in zip(self.pairing, self.line_lengths_lambda, strict=True):
            if element in (i, j):
                return length
        raise ValueError(f"单元 {element} 不在配对表中")  # pragma: no cover - 结构性守卫

    def to_dict(self) -> dict:
        """JSON 可序列化 dict（tuple → list）。"""
        return {
            "n_elements": self.n_elements,
            "spacing_lambda": self.spacing_lambda,
            "pairing": [list(p) for p in self.pairing],
            "line_lengths_lambda": list(self.line_lengths_lambda),
        }


def build_vanatta_array(
    n_elements: int,
    spacing_lambda: float = 0.5,
    line_lengths_lambda=None,
    pairing=None,
) -> VanAttaArray:
    """构造并校验 Van Atta 阵拓扑（边界：N<2 / d<=0 / 非整数配对 → ValueError）。

    n_elements：单元数（>=2 整数；奇数走中心元直通口径）；spacing_lambda：
    单元间距 d/λ（>0）；pairing：缺省镜像配对（:func:`mirror_pairing`），
    自定义须为对合置换（每单元恰出现一次，端口号严格整数——float/bool/
    越界即 ValueError）；line_lengths_lambda：缺省全 0（全等长参考），
    自定义须与配对表等长且逐条有限 >=0。
    """
    if isinstance(n_elements, bool) or not isinstance(n_elements, (int, np.integer)):
        raise ValueError(f"n_elements 须为整数，收到 {n_elements!r}")
    n = int(n_elements)
    if n < 2:
        raise ValueError(f"n_elements 至少为 2，收到 {n}")
    d = _positive(spacing_lambda, "spacing_lambda")

    if pairing is None:
        pairs = mirror_pairing(n)
    else:
        raw = list(pairing)
        seen: list[int] = []
        for k, entry in enumerate(raw):
            try:
                items = list(entry)
            except TypeError as exc:
                raise ValueError(f"pairing[{k}] 须为二元序列，收到 {entry!r}") from exc
            if len(items) != 2:
                raise ValueError(f"pairing[{k}] 须恰为 2 元素，收到 {items!r}")
            a = _check_index(items[0], f"pairing[{k}][0]", n)
            b = _check_index(items[1], f"pairing[{k}][1]", n)
            if a in seen or b in seen:
                raise ValueError(f"pairing[{k}] 端口重复（对合置换要求每单元恰一次）：{items!r}")
            seen.extend((a, b))
        if sorted(seen) != list(range(n)):
            raise ValueError(f"pairing 未覆盖全部单元：出现 {sorted(seen)}，须为 0..{n - 1}")
        pairs = tuple((int(a), int(b)) for a, b in raw)

    if line_lengths_lambda is None:
        lengths = tuple(0.0 for _ in pairs)
    else:
        raw_len = list(line_lengths_lambda)
        if len(raw_len) != len(pairs):
            raise ValueError(
                f"line_lengths_lambda 长度 {len(raw_len)} 须与配对数 {len(pairs)} 一致"
            )
        lengths = tuple(_finite(v, f"line_lengths_lambda[{k}]") for k, v in enumerate(raw_len))
        for k, v in enumerate(lengths):
            if v < 0.0:
                raise ValueError(f"line_lengths_lambda[{k}] 必须 >=0（物理线长），收到 {v}")
    return VanAttaArray(n_elements=n, spacing_lambda=d, pairing=pairs, line_lengths_lambda=lengths)


def vanatta_wiring_table(array: VanAttaArray) -> dict:
    """布线表（JSON dict）：配对 + 线长（λ 单位）——KiCad 链回填语义的接口。"""
    return {
        "n_elements": array.n_elements,
        "spacing_lambda": array.spacing_lambda,
        "lines": [
            {
                "pair_index": k,
                "element_a": pair[0],
                "element_b": pair[1],
                "through": pair[0] == pair[1],
                "length_lambda": length,
            }
            for k, (pair, length) in enumerate(
                zip(array.pairing, array.line_lengths_lambda, strict=True)
            )
        ],
    }


# ─── 回射恒等式（入射相位 → 出射激励 → AF 复用验证）──────────────────────────


def incident_phases(array: VanAttaArray, theta_deg: float) -> np.ndarray:
    """来自 theta_deg 的平面波在各元上的接收相位复向量 v_n = e^{+j·2π·u·x_n}。

    u = sin θ（约定见模块 docstring）；|θ| > 90° 显式报错（asin 域外）。
    """
    th = _finite(theta_deg, "theta_deg")
    if abs(th) > 90.0:
        raise ValueError(f"theta_deg 须在 [-90, 90]，收到 {th}")
    u = math.sin(math.radians(th))
    return np.exp(2j * np.pi * u * array.positions_lambda())


def vanatta_excitations(array: VanAttaArray, theta_deg: float) -> np.ndarray:
    """重辐射出射激励 w_m = v_pair(m)·e^{j·2π·L_pair(m)}（长度 1 复向量）。

    信号自 pair(m) 接收、经其所在线（相位 2π·L）自单元 m 重辐射；
    镜像配对 + 等长下 = 相位共轭斜坡 e^{−jku·x_m}·e^{jφ}（回射恒等式，
    模块 docstring 闭式推证）。线长失配经 L_pair(m) 自然进入。
    """
    v = incident_phases(array, theta_deg)
    w = np.empty(array.n_elements, dtype=complex)
    for m in range(array.n_elements):
        p = array.pair_of(m)
        w[m] = v[p] * np.exp(2j * np.pi * array.line_length_of(m))
    return w


def _af_complex(u_grid, w: np.ndarray, spacing_lambda: float) -> np.ndarray:
    """复权重阵因子（array_factor 复用 + 零和守卫旁路）。

    首选：权重乘公共旋转 e^{−jπ/4} 后拆 Re/Im 两次实权重调用（线性性：
    AF(w) = e^{+jπ/4}·[AF(wr.re) + j·AF(wr.im)]，butler_matrix 同族惯例；
    旋转使 ΣRe/ΣIm 各 = |Σw|/√2，避开 _validate_weights 的零和拒收——
    该守卫为 normalize 语义设，对 normalize=False 的共轭斜坡权重是伪拒）。
    Σw ≈ 0 的 Dirichlet 零点方向（如 N=8/d=0.5 的 θ=30°，此时回射峰
    |AF(u)|=N 完全良好）旋转救不了，走同核直算旁路
    （Σ w_n·e^{j2πd·u·n}，与 array_factor 同式，仅全局相位约定差）。
    """
    u_arr = np.asarray(u_grid, dtype=float)
    wr = w * _SPLIT_ROTATION
    if (
        abs(float(wr.real.sum())) > _ZERO_SUM_TOL
        and abs(float(wr.imag.sum())) > _ZERO_SUM_TOL
    ):
        af = array_factor(
            u_arr, wr.real, spacing_lambda=spacing_lambda, scan_direction_cosine=0.0, normalize=False
        )
        af = af + 1j * array_factor(
            u_arr, wr.imag, spacing_lambda=spacing_lambda, scan_direction_cosine=0.0, normalize=False
        )
        return af * np.conj(_SPLIT_ROTATION)
    # Dirichlet 零点旁路：同核直算（n 按几何序 0..N−1，全局相位不影响模与 argmax）
    idx = np.arange(w.size, dtype=float)
    kernel = np.exp(1j * 2.0 * np.pi * spacing_lambda * np.outer(idx, u_arr))
    return w @ kernel


def reradiated_af_peak(
    array: VanAttaArray, theta_deg: float, n_points: int = 20001
) -> dict:
    """重辐射阵因子数值扫角：|AF(u')| argmax 与闭式 u' = u 对照。

    阵因子复用 :func:`rfauto.core.array_synthesis.array_factor`（复权重
    经 :func:`_af_complex` 的旋转拆分/直算旁路，见其 docstring）。
    normalize=False 保持 |AF| 绝对标度。返回 JSON dict（含 u=θ 方向的
    |AF|，供相干增益恒等式复核：镜像配对下
    |AF(u)| = |Σ_m e^{j2π·L_pair(m)}| 精确成立）。
    """
    if isinstance(n_points, bool) or not isinstance(n_points, (int, np.integer)) or n_points < 1001:
        raise ValueError(f"n_points 须为 >=1001 的整数，收到 {n_points!r}")
    n_points = int(n_points)
    u = math.sin(math.radians(_finite(theta_deg, "theta_deg")))
    w = vanatta_excitations(array, theta_deg)
    u_grid = np.linspace(-1.0, 1.0, n_points)
    af = _af_complex(u_grid, w, array.spacing_lambda)
    idx = int(np.argmax(np.abs(af)))
    u_peak = float(u_grid[idx])
    theta_peak = math.degrees(math.asin(max(-1.0, min(1.0, u_peak))))
    af_at_incident = float(np.abs(af[int(np.argmin(np.abs(u_grid - u)))]))
    return {
        "theta_deg": float(theta_deg),
        "u": u,
        "u_peak": u_peak,
        "theta_peak_deg": theta_peak,
        "angle_error_deg": theta_peak - float(theta_deg),
        "af_peak_abs": float(np.abs(af[idx])),
        "af_at_incident_abs": af_at_incident,
    }


def verify_retroreflection(
    array: VanAttaArray,
    theta_deg_list=None,
    n_points: int = 20001,
) -> list[dict]:
    """多角度回射恒等式验证（缺省 θ ∈ [−60°, 60°] 均匀 7 点，任务书判据）。"""
    if theta_deg_list is None:
        thetas = [-60.0, -40.0, -20.0, 0.0, 20.0, 40.0, 60.0]
    else:
        thetas = [float(t) for t in theta_deg_list]
    if not thetas:
        raise ValueError("theta_deg_list 不能为空")
    return [reradiated_af_peak(array, t, n_points=n_points) for t in thetas]


# ─── 等长容差面（门 + 相位误差剖面 + 波前倾斜估计 + 相干增益）─────────────────


def equal_length_gate(
    line_lengths_lambda, tol_lambda: float = EQUAL_LENGTH_TOL_LAMBDA
) -> dict:
    """等长约束门：线长极差 spread = max(L) − min(L) < tol_lambda → PASS。

    口径钉死：tol 约束的是**任意两线之差**（fab 等长匹配惯例读法，
    缺省 λ/16 ↔ 任两线相位差 < 22.5°）；相对均值的相位偏差至多取
    spread/2（<11.25°）→ 相干增益 ≥ cos(11.25°) ≈ 0.981（损耗
    ≤ ~0.17 dB，|⟨e^{jδ}⟩| ≥ cos(max|δ|) 对 |δ| ≤ π/2 成立）。
    返回 {"mean_lambda", "spread_lambda", "max_phase_error_deg"（任两线
    相位差）, "tol_lambda", "passed"}；空表显式报错（无约束可检）。
    严格小于号：spread 恰等于容差判 FAIL（钉死不模糊）。
    """
    lengths = np.asarray(
        [_finite(v, f"line_lengths_lambda[{k}]") for k, v in enumerate(line_lengths_lambda)],
        dtype=float,
    )
    if lengths.size == 0:
        raise ValueError("line_lengths_lambda 不能为空")
    tol = _positive(tol_lambda, "tol_lambda")
    spread = float(np.max(lengths) - np.min(lengths))
    return {
        "mean_lambda": float(np.mean(lengths)),
        "spread_lambda": spread,
        "max_phase_error_deg": 360.0 * spread,
        "tol_lambda": tol,
        "passed": bool(spread < tol),
    }


def phase_error_profile(array: VanAttaArray) -> np.ndarray:
    """出射相位误差剖面 δφ_n = 2π·(L_pair(n) − L̄)（rad，长度 N）。

    镜像配对下该剖面关于口径中心严格对称（奇分量 ≡ 0，模块 docstring
    推导）——该对称性是"失配不倾斜"不变量的承重结构。
    """
    lengths = np.asarray(array.line_lengths_lambda, dtype=float)
    dev = lengths - float(np.mean(lengths))
    out = np.empty(array.n_elements, dtype=float)
    for m in range(array.n_elements):
        for k, (i, j) in enumerate(array.pairing):
            if m in (i, j):
                out[m] = 2.0 * np.pi * dev[k]  # dev 按配对索引，m 按单元索引
                break
    return out


def wavefront_tilt_estimate(
    positions_lambda, phase_errors_rad, theta_deg: float | None = None
) -> dict:
    """相位误差 → 波前倾斜闭式估计（通用面，覆盖奇分量非零的误差剖面）。

    对 (x, δφ) 做最小二乘直线拟合 δφ ≈ a·x + b：线性相位斜坡 a
    （rad/λ）使出射波前偏转 Δu = −a/(2π)（符号钉死：误差相位随位置
    递增 → 波前向 −u 偏转；闭式推导见出射核 e^{jk(u'−u)x}·e^{ja·x}）。
    theta_deg 给定时折算角度偏转 tilt_deg = asin(u+Δu) − asin(u)（deg；
    u+Δu 出可见区 [−1,1] 时 tilt_deg=None，判缺失 is not None）。
    另报 rms_rad（剖面 RMS）与 intercept_rad。
    """
    x = np.asarray(positions_lambda, dtype=float)
    dphi = np.asarray(phase_errors_rad, dtype=float)
    if x.shape != dphi.shape or x.ndim != 1 or x.size < 2:
        raise ValueError(
            f"positions/phase_errors 须为同长一维数组（>=2 点），收到 {x.shape} vs {dphi.shape}"
        )
    if not bool(np.all(np.isfinite(x))) or not bool(np.all(np.isfinite(dphi))):
        raise ValueError("positions/phase_errors 含非有限值")
    xc = x - float(np.mean(x))
    denom = float(np.sum(xc**2))
    slope = float(np.sum(xc * (dphi - float(np.mean(dphi))))) / denom if denom > 0.0 else 0.0
    intercept = float(np.mean(dphi)) - slope * float(np.mean(x))
    du = -slope / (2.0 * np.pi)
    tilt_deg = None
    if theta_deg is not None:
        th = _finite(theta_deg, "theta_deg")
        if abs(th) > 90.0:
            raise ValueError(f"theta_deg 须在 [-90, 90]，收到 {th}")
        u_new = math.sin(math.radians(th)) + du
        if abs(u_new) <= 1.0:
            tilt_deg = math.degrees(math.asin(u_new)) - th
    return {
        "slope_rad_per_lambda": slope,
        "intercept_rad": intercept,
        "du": du,
        "rms_rad": float(np.sqrt(float(np.mean(dphi**2)))),
        "tilt_deg": tilt_deg,
    }


def coherence_gain(phase_errors_rad) -> float:
    """相干增益因子 |⟨e^{jδφ}⟩|（∈[0,1]；共模相位不损耗，模自动免疫）。"""
    dphi = np.asarray(phase_errors_rad, dtype=float)
    if dphi.size == 0:
        raise ValueError("phase_errors_rad 不能为空")
    if not bool(np.all(np.isfinite(dphi))):
        raise ValueError("phase_errors_rad 含非有限值")
    return float(np.abs(np.mean(np.exp(1j * dphi))))


# ─── skrf 级联面（单元 S + 等长线 Line → connect 级联 → 相位表）───────────────


def element_s_matrix(gamma_ant: complex = 0j, gamma_line: complex = 0j, tau: float = 1.0):
    """单元 2 端口 S（端口序 (天线侧, 线侧)）：[[Γ_a, τ], [τ, γ_l]]。

    gamma_ant：天线侧反射（参数化，|·|<=1）；gamma_line：线侧反射
    （|·|<=1）；tau：天线↔线直通系数（实数 [0,1]，理想 1）。物理性守卫
    显式报错；理想缺省 = 匹配直通。
    """
    ga = complex(gamma_ant)
    gl = complex(gamma_line)
    if not (math.isfinite(ga.real) and math.isfinite(ga.imag)):
        raise ValueError("gamma_ant 必须有限")
    if not (math.isfinite(gl.real) and math.isfinite(gl.imag)):
        raise ValueError("gamma_line 必须有限")
    if abs(ga) > 1.0 or abs(gl) > 1.0:
        raise ValueError("反射系数模须 <=1（无源）")
    t = _finite(tau, "tau")
    if not 0.0 <= t <= 1.0:
        raise ValueError(f"tau 须在 [0, 1]，收到 {t}")
    return np.array([[ga, t], [t, gl]], dtype=complex)


def _pair_network(array: VanAttaArray, pair_index: int, gamma_ant: complex, gamma_line: complex,
                  tau: float):
    """第 pair_index 对的级联 2 端口网络（端口序 (ant_i, ant_j)，skrf）。

    链：elem_i(ant 外口) —线— elem_j(ant 外口)，skrf connect 逐口级联
    （探针实测语义见模块 docstring；线 = DefinedGammaZ0(gamma=2πj) 的
    line(d=L_λ)，S21 = e^{−j2π·L}，与闭式同约定）。
    """
    import skrf as rf  # 局部导入：core 其余路径零 skrf 依赖（butler_matrix 同族惯例）

    length = array.line_lengths_lambda[pair_index]
    freq = rf.Frequency(1.0, 1.0, 1, "GHz")
    media = rf.media.DefinedGammaZ0(frequency=freq, z0=50.0, gamma=2j * np.pi)

    def _elem_net():
        s = element_s_matrix(gamma_ant=gamma_ant, gamma_line=gamma_line, tau=tau)
        return rf.Network(
            f=[1.0], f_unit="GHz", s=s.reshape(1, 2, 2), z0=[50.0, 50.0], name="elem"
        )

    line = media.line(d=length, unit="m", z0=50.0)
    cur = rf.network.connect(_elem_net(), 1, line, 0)
    cur = rf.network.connect(cur, 1, _elem_net(), 1)
    return cur


def build_vanatta_network(
    array: VanAttaArray, gamma_ant: complex = 0j, gamma_line: complex = 0j, tau: float = 1.0
):
    """全阵 skrf 网络：各对级联 2 端口 concat 后按自然端口序重排（N 端口）。

    外部端口 = 天线馈端口 0..N−1（自然序）；对间无耦合（块对角精确 0）。
    奇数 N 的自配对（直通）对网络双端口同指中心元天线（链两端各一），
    重排取首现端口、别名端口弃选——端口 0 的 S 已含整环交互，物理面
    自洽；偶数 N 无此别名。
    """
    import skrf as rf  # 局部导入（同族惯例）

    pair_nets = [
        _pair_network(array, k, gamma_ant, gamma_line, tau) for k in range(len(array.pairing))
    ]
    big = rf.network.concat_ports(pair_nets)
    # concat_ports 按口索引交错：[p0(对0), p0(对1), ..., p1(对0), p1(对1), ...]
    labels = [p[0] for p in array.pairing] + [p[1] for p in array.pairing]
    order = [labels.index(e) for e in range(array.n_elements)]
    s = big.s[:, order, :][:, :, order]
    z0 = big.z0[:, order]
    return rf.Network(f=big.f, f_unit="GHz", s=s, z0=z0, name="vanatta")


def transmission_table_closed(
    array: VanAttaArray, gamma_ant: complex = 0j, gamma_line: complex = 0j, tau: float = 1.0
) -> list[dict]:
    """闭式端口传输相位表（路径 A）：逐对含多次反射几何级数。

    T = τ²·e^{−jφ}/(1 − γ_l²·e^{−2jφ})（φ = 2π·L；分母 = 线两端 γ_l 间
    往返反射级数和）；天线口反射 S_ii = Γ_a + τ²·γ_l·e^{−2jφ}/(1 − γ_l²·
    e^{−2jφ})。γ_l = 0 退化为理想直通 τ²·e^{−jφ}。复数条目原样返回，
    JSON 化由调用方（service 层）折 [re, im]。
    """
    ga = complex(gamma_ant)
    gl = complex(gamma_line)
    t = float(tau)
    table = []
    for k, ((i, j), length) in enumerate(
        zip(array.pairing, array.line_lengths_lambda, strict=True)
    ):
        phi = 2.0 * np.pi * float(length)
        denom = 1.0 - gl * gl * np.exp(-2j * phi)
        t_fwd = (t * t) * np.exp(-1j * phi) / denom
        refl = ga + (t * t) * gl * np.exp(-2j * phi) / denom
        table.append(
            {
                "pair_index": k,
                "element_i": int(i),
                "element_j": int(j),
                "line_length_lambda": float(length),
                "t_forward": complex(t_fwd),  # ant_i → ant_j
                "t_reverse": complex(t_fwd),  # 互易同值
                "s_reflect_i": complex(refl),
                "s_reflect_j": complex(refl),
            }
        )
    return table


def transmission_table_skrf(
    array: VanAttaArray, gamma_ant: complex = 0j, gamma_line: complex = 0j, tau: float = 1.0
) -> list[dict]:
    """skrf 级联端口传输相位表（路径 B）：逐对从级联网络读 S 参数。"""
    table = []
    for k in range(len(array.pairing)):
        i, j = array.pairing[k]
        net = _pair_network(array, k, gamma_ant, gamma_line, tau)
        table.append(
            {
                "pair_index": k,
                "element_i": int(i),
                "element_j": int(j),
                "line_length_lambda": float(array.line_lengths_lambda[k]),
                "t_forward": complex(net.s[0, 1, 0]),  # S21: ant_i → ant_j
                "t_reverse": complex(net.s[0, 0, 1]),  # S12: ant_j → ant_i
                "s_reflect_i": complex(net.s[0, 0, 0]),
                "s_reflect_j": complex(net.s[0, 1, 1]),
            }
        )
    return table


def _complex_rel_max(table_a: list[dict], table_b: list[dict]) -> float:
    """双路径复数逐条目相对差的最大值（|a−b|/max(|a|, floor)）。"""
    if len(table_a) != len(table_b):
        raise ValueError(f"双路径表行数不一致：{len(table_a)} vs {len(table_b)}")
    worst = 0.0
    for ra, rb in zip(table_a, table_b, strict=True):
        for key in ("t_forward", "t_reverse", "s_reflect_i", "s_reflect_j"):
            va = complex(ra[key])
            vb = complex(rb[key])
            diff = abs(va - vb)
            denom = max(abs(va), _COMPLEX_FLOOR)
            worst = max(worst, diff / denom)
    return worst


@dataclass(frozen=True)
class VanAttaReport:
    """Van Atta 全面验证报告（判据全部预声明，数值如实不凑绿）。

    判据（预声明）：
    - 回射角：各 θ 实测 argmax 与 θ 差 ≤0.5°（等长完美线，网格分辨率限）；
    - 双路径：相位表 skrf vs 闭式 max rel ≤1e-12（#118 主判据）；
    - 等长门：线长极差 max(L)−min(L) < λ/16（tol 显式参数）；
    - 相位剖面奇分量：镜像配对下拟合斜率 |a| < 1e-10 rad/λ（失配不倾斜
      不变量的数值面）。
    dual_path_max_rel=None 表示未跑级联路径（verify_vanatta dual_path=False），
    此时 all_pass 如实 False（未跑不判 PASS，#122 精神）。
    """

    n_elements: int
    spacing_lambda: float
    thetas_deg: tuple
    theta_peak_deg: tuple
    angle_error_deg: tuple
    af_peak_abs: tuple
    af_at_incident_abs: tuple
    angle_band_deg: float
    table_pair_count: int
    dual_path_max_rel: float | None
    equal_length_spread_lambda: float
    equal_length_tol_lambda: float
    length_gate_pass: bool
    rms_phase_error_rad: float
    coherence_gain: float
    tilt_slope_rad_per_lambda: float
    tilt_du: float
    phase_profile_symmetric: bool

    @property
    def all_pass(self) -> bool:
        """全部预声明判据通过（dual_path 未跑 → False，见类 docstring）。"""
        angles_ok = max(abs(e) for e in self.angle_error_deg) <= self.angle_band_deg
        dual_ok = self.dual_path_max_rel is not None and self.dual_path_max_rel <= TOL_DUAL_PATH
        return bool(
            angles_ok
            and dual_ok
            and self.length_gate_pass
            and self.phase_profile_symmetric
        )

    def to_dict(self) -> dict:
        """JSON 可序列化 dict（tuple → list；None 原样）。"""
        return {
            "n_elements": self.n_elements,
            "spacing_lambda": self.spacing_lambda,
            "thetas_deg": list(self.thetas_deg),
            "theta_peak_deg": list(self.theta_peak_deg),
            "angle_error_deg": list(self.angle_error_deg),
            "af_peak_abs": list(self.af_peak_abs),
            "af_at_incident_abs": list(self.af_at_incident_abs),
            "angle_band_deg": self.angle_band_deg,
            "table_pair_count": self.table_pair_count,
            "dual_path_max_rel": self.dual_path_max_rel,
            "equal_length_spread_lambda": self.equal_length_spread_lambda,
            "equal_length_tol_lambda": self.equal_length_tol_lambda,
            "length_gate_pass": self.length_gate_pass,
            "rms_phase_error_rad": self.rms_phase_error_rad,
            "coherence_gain": self.coherence_gain,
            "tilt_slope_rad_per_lambda": self.tilt_slope_rad_per_lambda,
            "tilt_du": self.tilt_du,
            "phase_profile_symmetric": self.phase_profile_symmetric,
            "all_pass": self.all_pass,
        }


def verify_vanatta(
    array: VanAttaArray,
    theta_deg_list=None,
    n_points: int = 20001,
    dual_path: bool = True,
) -> VanAttaReport:
    """端到端验证：回射扫角 + 等长门 + 相位剖面 + skrf 级联双路径互证。

    dual_path=False 跳过 skrf 级联（dual_path_max_rel=None，all_pass 如实
    False——未跑不判 PASS）。
    """
    if not isinstance(dual_path, bool):
        raise ValueError("dual_path 须为 bool")
    scan = verify_retroreflection(array, theta_deg_list, n_points=n_points)
    gate = equal_length_gate(array.line_lengths_lambda)
    profile = phase_error_profile(array)
    tilt = wavefront_tilt_estimate(array.positions_lambda(), profile)
    gain = coherence_gain(profile)
    dual_rel: float | None = None
    if dual_path:
        closed = transmission_table_closed(array)
        skrf_tab = transmission_table_skrf(array)
        dual_rel = _complex_rel_max(closed, skrf_tab)
    return VanAttaReport(
        n_elements=array.n_elements,
        spacing_lambda=array.spacing_lambda,
        thetas_deg=tuple(s["theta_deg"] for s in scan),
        theta_peak_deg=tuple(s["theta_peak_deg"] for s in scan),
        angle_error_deg=tuple(s["angle_error_deg"] for s in scan),
        af_peak_abs=tuple(s["af_peak_abs"] for s in scan),
        af_at_incident_abs=tuple(s["af_at_incident_abs"] for s in scan),
        angle_band_deg=RETRO_ANGLE_BAND_DEG,
        table_pair_count=len(array.pairing),
        dual_path_max_rel=dual_rel,
        equal_length_spread_lambda=gate["spread_lambda"],
        equal_length_tol_lambda=gate["tol_lambda"],
        length_gate_pass=gate["passed"],
        rms_phase_error_rad=tilt["rms_rad"],
        coherence_gain=gain,
        tilt_slope_rad_per_lambda=tilt["slope_rad_per_lambda"],
        tilt_du=tilt["du"],
        phase_profile_symmetric=bool(abs(tilt["slope_rad_per_lambda"]) < _SYM_SLOPE_TOL),
    )
