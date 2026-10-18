"""波导/腔体任意模式闭式谱族（aurora72 A2-C 席域 2，R7 第二梯队 T2；
aurora_e W1-S2 续作收口任务书内"圆波导/矩形腔"两子项）。

六键：circular_cavity_mode_spectrum（TE/TM_mnp 谐振谱：给半径/长度/频段
→ 模式频率列表+主模标识+TE11 波导截止参考） / circular_cavity_mode_chart
（模式图数据：归一化频率-长径比曲线+主模切换交叉点） /
circular_cavity_mode_q（任意 TE/TM_mnp 模式无载 Q：导体闭式+数值积分
路线互证+介质串联合成） / circular_waveguide_mode_prop（圆波导 TE/TM_mn
单频传播解：截止/波导波长/波阻抗/导体+介质衰减/功率容量，W1-S2） /
rectangular_cavity_mode_spectrum（矩形腔 TE/TM_mnp 谐振谱，W1-S2） /
rectangular_cavity_mode_q（矩形腔任意模式无载 Q，W1-S2）。

与既有面的边界（语义防撞，R7 §③ T2 三重搜索证据）
--------------------------------------------------------
- rw_tables = EIA 商品矩形波导表；rwg_mmt = 矩形波导模基 GSM 数值；
  ridged_waveguide = 脊形波导；waveguide_iris/waveguide_lambda_g = 矩形
  TE10 膜片/传播参数面；bethe_hole 内部圆波导截止常数=孔耦合口径——
  本族做**任意模式闭式谱与传播解**（圆波导+圆柱腔+矩形腔；矩形腔为
  R7 T2"留续作"子项，aurora_e W1-S2 收口）。
- cavity.py/cavity_perturbation_shift = 腔体微扰**测量**面；
  material_characterization = 分裂腔/Courtney **材料提取**面——本族是
  它们的**上游模式谱供给**（先定模式再提取）；TE011 空腔频率与
  material_characterization._sc_empty_f0 同仓双源（测试互证）。
- combline_resonator = 同轴腔 TEM 单模；本族是**高阶模谱**面。

物理口径（docstring 写死，#1c/#300 出处纪律）
----------------------------------------------
- 圆柱腔谐振频率（半径 a、长 L、均匀填充 εr；Bessel 零点闭式，Pozar
  *Microwave Engineering* §6.4 圆柱腔 / Collin）：

      TE_mnp: f = c₀/(2π√εr)·√((x'_mn/a)² + (pπ/L)²)   x'_mn = J_m'(x)
      第 n 个正零点（m≥0, n≥1, p≥1——p=0 时 E_t≡0 非物理，显式拒绝）
      TM_mnp: f = c₀/(2π√εr)·√((x_mn/a)² + (pπ/L)²)    x_mn = J_m(x)
      第 n 个正零点（m≥0, n≥1, p≥0——E_z 对端壁为法向，p=0 允许，
      TM010 即经典例）

  主模判据（计算判读非假定）：全谱最低频模式。经典口径 l<2a → TM010、
  l>2a → TE111，交叉长径比 l/2a = π/(2·√(x_01²−x'_11²)) ≈ 1.0154
  （模式图键输出该交叉点，测试钉）。
- 模式图：归一化频率 f·2πa√εr/c₀ = √(x²+(pπa/L)²) 随长径比
  r=l/(2a) 的曲线族（p≥1 模式随 r 单调降、p=0 平坦——测试钉）；主模
  切换点在相邻网格间二分求根（g(r)=f_i(r)−f_j(r) 变号）。
- 无载 Q（导体微扰口径：Q=ωU/P_c；Pozoar §6.4 + Collin 微扰法；本席
  从场表达式独立推导，双路线互证）：
  场表达式（板坐标系 z∈[0,L]，e^{jωt}；幅值 H0/E0 归一，Q 与幅值
  无关）——TE_mnp：H_z=J_m(kρ)cos(mφ)sin(kz·z)、E_t∝sin(kz·z)、
  H_t∝cos(kz·z)；TM_mnp：E_z=J_m(kρ)cos(mφ)cos(kz·z)、E_t∝sin、
  H_t∝cos。U_e=U_m（谐振腔严格定理，测试用数值体积分独立验证场表达
  式正确性）。导体 Q 闭式（Bessel 恒等式化简后；Ls=∫sin²=L/2、
  Lc=∫cos²=L/2，p=0 时 L、0）：

      TE: Qc = ωμ·L·x'²·D·(k²+kz²) / (Rs·[4k⁴·a·Ls + 4kz²m²·Lc/a
              + 4kz²x'²·D])，  D = 1−m²/x'²（J² 因子分子分母消去）
      TM: Qc = I2x·(k²·Lc + kz²·Ls) / (Rs·ωε·(J_{m+1}(x)²·a·k²·Lc
              + 2·I2x))，  I2x = x²·J_{m+1}(x)²/2

      TM010 极限（测试钉，测试侧独立重算）：Qc = (η·k0·a/2Rs)·L/(L+a)
  数值路线（同键输出 q_conductor_numeric）：径向能量/损耗积分用
  scipy.integrate.quad 对同样场表达式直接数值积分（不消费 Bessel 恒
  等式）——q_xcheck_rel_dev 应为 quad 精度级（<1e-9），双路线失配即
  推导有误的显式证据。介质 Q=1/tanδ（tanδ=0 如实返 null）；串联合成
  1/Qu=1/Qc+1/Qd（同 cavity_unloaded_q 口径）。

数值锚（#118 独立来源；锚树 tests/unit/test_a2c_coax_waveguide.py）
- TM010：a=10mm → f=x_01·c₀/(2πa)=11.4743 GHz（x_01=2.4048255577 测试
  侧独立常数）；
- TE011 空腔频率与 material_characterization._sc_empty_f0 同仓双源
  ≤1e-12；TE011/TM111 简并（x'_01=x_11=3.8317）同频逐位；
- 主模判据：l<2a → TM010 主模、l>2a → TE111 主模（经典口径复现）；
  模式图交叉 r≈1.0154（测试侧独立常数式）；
- Q：Ue/Um≈1（谐振定理，数值验证）；Qc 闭式 vs 数值路线 <1e-9；
  Qc∝1/Rs（σ×4→Qc×2）；TE011>TE111（无端壁环流的经典高 Q 性质）；
  TE11 波导截止 x'_11·c₀/(2πa)=0.293·c₀/a 口径；
- εr 标度：全谱频率 ÷√εr（εr=4 → ÷2 逐位）。

守卫：radius_mm/length_mm>0；0<f_min<f_max；epsilon_r≥1；max_modes
整型 1..500（超限显式拒绝要求收窄频段）；模式名形如 'TE011'/'TM010'
（类型+mnp 三位数字，m 可为 0）且 n≥1、TE 的 p≥1（p=0 非物理显式
拒绝）；m≥0/n≥1/p≥0 整型（TE p≥1）；conductivity_s_per_m>0；mu_r>0；
tan_delta≥0；越界一律显式拒绝。
"""

from __future__ import annotations

import math
import re
from functools import lru_cache
from typing import Any

from .registry import C_MM_GHZ, register_calculator
from .thermal import _finite

_MU0 = 1.25663706212e-6
_EPS0 = 8.8541878128e-12
_C0 = 299792458.0  # m/s（与 C_MM_GHZ 同源：C_MM_GHZ·1e6）

_SOURCES = {
    "spec": "Pozar Microwave Engineering §6.4 圆柱腔（Bessel 零点闭式）；Collin",
    "chart": "圆柱腔模式图（归一化频率-长径比曲线族，Pozar §6.4 口径）",
    "q": "导体微扰 Q=ωU/P_c（Pozar §6.4/Collin）；闭式与数值积分双路线互证",
}

_MODE_NAME_RE = re.compile(r"^(TE|TM)(\d)(\d)(\d)$")
# 枚举规模守卫（防组合爆炸；超限显式拒绝要求收窄频段）
_MAX_ENUM_CANDIDATES = 30000
_MAX_ROOT_INDEX = 60


@lru_cache(maxsize=512)
def _te_roots(m: int, n: int) -> tuple[float, ...]:
    """J_m'(x) 前 n 个正零点（scipy jnp_zeros；m=0 时 J_0'=−J_1 同根集，
    scipy 1.18 实测 jnp_zeros(0,n) 直接给出 3.8317/7.0156…）。"""
    from scipy.special import jnp_zeros

    if n < 1 or n > _MAX_ROOT_INDEX:
        raise ValueError(
            f"circular waveguide: 径向序号 n={n} 越域（1..{_MAX_ROOT_INDEX}）")
    return tuple(float(v) for v in jnp_zeros(m, n))


@lru_cache(maxsize=512)
def _tm_roots(m: int, n: int) -> tuple[float, ...]:
    """J_m(x) 前 n 个正零点（scipy jn_zeros）。"""
    from scipy.special import jn_zeros

    if n < 1 or n > _MAX_ROOT_INDEX:
        raise ValueError(
            f"circular waveguide: 径向序号 n={n} 越域（1..{_MAX_ROOT_INDEX}）")
    return tuple(float(v) for v in jn_zeros(m, n))


@lru_cache(maxsize=512)
def _te_root(m: int, n: int) -> float:
    """J_m'(x) 第 n 个正零点 x'_mn。"""
    return _te_roots(m, n)[n - 1]


@lru_cache(maxsize=512)
def _tm_root(m: int, n: int) -> float:
    """J_m(x) 第 n 个正零点 x_mn。"""
    return _tm_roots(m, n)[n - 1]


def _parse_mode_name(name: str) -> tuple[str, int, int, int]:
    """'TE011' → ('TE', 0, 1, 1)；非法/语义越界（TE p=0 等）显式拒绝。"""
    mobj = _MODE_NAME_RE.match(str(name).strip().upper())
    if mobj is None:
        raise ValueError(
            f"模式名 {name!r} 非法——须形如 'TE011'/'TM010'（类型+mnp 三位"
            "数字，m 可为 0）")
    mtype, mm, nn, pp = mobj.group(1), int(mobj.group(2)), int(
        mobj.group(3)), int(mobj.group(4))
    if nn < 1:
        raise ValueError(f"模式名 {name!r}: 径向序号 n 须 ≥1")
    if mtype == "TE" and pp < 1:
        raise ValueError(
            f"模式名 {name!r}: TE_mnp 的 p≥1（p=0 时 E_t≡0，短腔壁圆柱腔"
            "不存在该 TE 模式，显式拒绝）")
    return mtype, mm, nn, pp


def _as_int(value: Any, name: str, lo: int) -> int:
    """整型守卫：接受整数值 float，拒绝非整/越下界。"""
    out = _finite(value, name)
    iout = round(out)
    if abs(out - iout) > 1e-9:
        raise ValueError(f"{name} 必须为整数，得到 {value!r}")
    if iout < lo:
        raise ValueError(f"{name} 必须 ≥{lo}，得到 {value!r}")
    return iout


def _mode_k0(mode_type: str, m: int, n: int, p: int, radius_mm: float,
             length_mm: float, epsilon_r: float) -> tuple[float, float]:
    """模式横向/纵向波数 (k[1/mm], kz[1/mm]) 与根值。"""
    x_root = _te_root(m, n) if mode_type == "TE" else _tm_root(m, n)
    k = x_root / radius_mm
    kz = p * math.pi / length_mm
    return k, kz


def _freq_ghz_from_k0(k_total: float, epsilon_r: float) -> float:
    """k0[1/mm] → f[GHz]：f = c₀·k0/(2π) = C_MM_GHZ·k0/(2π√εr)。"""
    return C_MM_GHZ * k_total / (2.0 * math.pi * math.sqrt(epsilon_r))


# ─── 键 1：TE/TM_mnp 谐振谱 ─────────────────────────────────────────────────

@register_calculator(
    "circular_cavity_mode_spectrum",
    "圆柱腔多模谐振谱：TE/TM_mnp Bessel 零点闭式 f=c₀/(2π√εr)·√((x/a)²+"
    "(pπ/L)²)（TE 用 J_m' 零点 p≥1，TM 用 J_m 零点 p≥0/TM010 经典例），"
    "给半径/长度/频段 → 带内模式频率列表（排序）+全谱主模标识（计算判读"
    "非假定：l<2a→TM010、l>2a→TE111 经典口径复现）+TE11 波导截止参考 "
    "x'_11·c₀/(2πa)。锚：TM010=11.4743GHz@a=10mm；TE011 与 "
    "material_characterization 空腔闭式同仓双源；TE011/TM111 简并同频",
    (("radius_mm", "float mm 腔半径（>0）"),
     ("length_mm", "float mm 腔长（>0）"),
     ("f_min_ghz", "float GHz 频段下缘（>0，<f_max_ghz）"),
     ("f_max_ghz", "float GHz 频段上缘（>f_min_ghz）"),
     ("epsilon_r", "float 腔内均匀填充相对介电常数（≥1，缺省 1）"),
     ("max_modes", "int 带内模式数上限（1..500，缺省 200；超限显式拒绝"
      "要求收窄频段）")),
    required=("radius_mm", "length_mm", "f_min_ghz", "f_max_ghz"),
)
def circular_cavity_mode_spectrum(radius_mm: float, length_mm: float,
                                  f_min_ghz: float, f_max_ghz: float,
                                  epsilon_r: float = 1.0,
                                  max_modes: int = 200) -> dict[str, Any]:
    a = _finite(radius_mm, "radius_mm")
    length = _finite(length_mm, "length_mm")
    f_lo = _finite(f_min_ghz, "f_min_ghz")
    f_hi = _finite(f_max_ghz, "f_max_ghz")
    eps_r = _finite(epsilon_r, "epsilon_r")
    n_cap = _as_int(max_modes, "max_modes", 1)
    if n_cap > 500:
        raise ValueError(
            f"circular_cavity_mode_spectrum: max_modes 必须 ≤500，得到 "
            f"{max_modes!r}（超宽谱请收窄频段，非提高上限）")
    if a <= 0.0:
        raise ValueError(
            f"circular_cavity_mode_spectrum: radius_mm 必须 >0，得到 "
            f"{radius_mm!r}")
    if length <= 0.0:
        raise ValueError(
            f"circular_cavity_mode_spectrum: length_mm 必须 >0，得到 "
            f"{length_mm!r}")
    if f_lo <= 0.0 or f_hi <= f_lo:
        raise ValueError(
            f"circular_cavity_mode_spectrum: 须 0 < f_min_ghz < "
            f"f_max_ghz，得到 {f_min_ghz!r}/{f_max_ghz!r}")
    if eps_r < 1.0:
        raise ValueError(
            f"circular_cavity_mode_spectrum: epsilon_r 必须 ≥1，得到 "
            f"{epsilon_r!r}")

    sqrt_er = math.sqrt(eps_r)
    # 频段上缘对应总波数（1/mm）；k²+kz² = k0²
    k0_max = 2.0 * math.pi * f_hi * sqrt_er / C_MM_GHZ
    x_max = k0_max * a

    candidates: list[tuple[float, str, str, int, int, int]] = []
    for mtype, roots_fn in (("TE", _te_roots), ("TM", _tm_roots)):
        p_min = 1 if mtype == "TE" else 0
        m = 0
        while m <= max(1, math.ceil(x_max)) + 1:
            # 批量取根：逐步加倍直至末根越出 x_max（防漏根）；J_m 首根随
            # m 单调增——首根越出 x_max 即终止整个 m 枚举（含更大 m）
            n_cap_batch = 8
            roots: tuple[float, ...] = ()
            while True:
                if n_cap_batch > _MAX_ROOT_INDEX:
                    roots = roots_fn(m, _MAX_ROOT_INDEX)
                    break
                roots = roots_fn(m, n_cap_batch)
                if roots[-1] > x_max or n_cap_batch >= _MAX_ROOT_INDEX:
                    break
                n_cap_batch *= 2
            if m >= 1 and roots[0] > x_max:
                # 首根单调性只对 m≥1 成立（x'_01=3.8317 > x'_11=1.8412，
                # m=0 是例外——m=0 无根不可终止枚举，须续到 m=1）
                break
            for n, x_root in enumerate(roots, start=1):
                if x_root > x_max:
                    break
                k = x_root / a
                p_hi = int(math.sqrt(max(0.0, k0_max * k0_max - k * k))
                           * length / math.pi) + 1
                for p in range(p_min, p_hi + 1):
                    k_total = math.hypot(k, p * math.pi / length)
                    f_ghz = _freq_ghz_from_k0(k_total, eps_r)
                    if f_lo <= f_ghz <= f_hi:
                        candidates.append(
                            (f_ghz, f"{mtype}{m}{n}{p}", mtype, m, n, p))
                if len(candidates) > _MAX_ENUM_CANDIDATES:
                    raise ValueError(
                        "circular_cavity_mode_spectrum: 候选模式组合爆炸"
                        "（>30000）——频段过宽，请收窄 f_max_ghz")
            m += 1
    candidates.sort(key=lambda item: (item[0], item[1]))
    if len(candidates) > n_cap:
        raise ValueError(
            f"circular_cavity_mode_spectrum: 带内模式数 {len(candidates)} "
            f"> max_modes={n_cap}——频段过宽，请收窄 f_min_ghz/f_max_ghz")

    # 主模判读：全谱最低频模式（枚举覆盖一切 f ≤ f_max，主模必在其中）
    dominant = candidates[0] if candidates else None
    modes = [
        {"mode": item[1], "type": item[2], "m": item[3], "n": item[4],
         "p": item[5], "f_ghz": round(item[0], 9)}
        for item in candidates
    ]
    te11_cutoff = C_MM_GHZ * _te_root(1, 1) / (2.0 * math.pi * a * sqrt_er)
    note = (
        "Bessel 零点闭式谱；主模=全谱最低频模式（计算判读）；p≥1 的 TE "
        "模式与 p=0 的 TM 模式均按口径枚举；模式误指会系统性污染下游"
        "提取（material_characterization 语境）——用本谱先定模式")
    if dominant is not None:
        note += f"；本腔主模={dominant[1]}（f={dominant[0]:.6g} GHz）"
    return {
        "radius_mm": a,
        "length_mm": length,
        "f_min_ghz": f_lo,
        "f_max_ghz": f_hi,
        "epsilon_r": eps_r,
        "n_modes_in_band": len(modes),
        "modes": modes,
        "dominant_mode": None if dominant is None else dominant[1],
        "dominant_f_ghz": None if dominant is None else round(dominant[0], 9),
        "te11_waveguide_cutoff_ghz": round(te11_cutoff, 9),
        "dominant_criterion_note": (
            "经典口径 l<2a → TM010、l>2a → TE111（本键按全谱计算判读，"
            "不按口径假定）"),
        "note": note,
        "source": _SOURCES["spec"],
    }


# ─── 键 2：模式图数据 ───────────────────────────────────────────────────────

@register_calculator(
    "circular_cavity_mode_chart",
    "圆柱腔模式图数据：归一化频率 f·2πa√εr/c₀=√(x²+(pπa/L)²) 随长径比 "
    "r=l/(2a) 的曲线族（TM010 平坦、p≥1 模式单调降——单调性测试钉），"
    "逐格点主模排序+主模切换交叉点（相邻网格变号对二分求根；TE111/TM010 "
    "交叉 r≈1.0154 测试侧独立常数式）。与 spectrum 键单源同式（同根值"
    "helper），测试做跨键一致性互证",
    (("modes", "list[str] 模式名列表（形如 'TM010'；缺省 TM010/TE111/"
      "TM011/TE021/TE012/TM111/TE011/TM021）"),
     ("l_over_2a_min", "float 长径比下缘（>0，<max，缺省 0.2）"),
     ("l_over_2a_max", "float 长径比上缘（≤20，缺省 3.0）"),
     ("n_points", "int 网格点数（2..401，缺省 61）"),
     ("epsilon_r", "float 相对介电常数（≥1，缺省 1；归一化频率已约去）")),
    required=(),
)
def circular_cavity_mode_chart(
    modes: list[str] | None = None,
    l_over_2a_min: float = 0.2,
    l_over_2a_max: float = 3.0,
    n_points: int = 61,
    epsilon_r: float = 1.0,
) -> dict[str, Any]:
    eps_r = _finite(epsilon_r, "epsilon_r")
    if eps_r < 1.0:
        raise ValueError(
            f"circular_cavity_mode_chart: epsilon_r 必须 ≥1，得到 "
            f"{epsilon_r!r}")
    r_lo = _finite(l_over_2a_min, "l_over_2a_min")
    r_hi = _finite(l_over_2a_max, "l_over_2a_max")
    if r_lo <= 0.0 or r_hi <= r_lo:
        raise ValueError(
            f"circular_cavity_mode_chart: 须 0 < l_over_2a_min < "
            f"l_over_2a_max，得到 {l_over_2a_min!r}/{l_over_2a_max!r}")
    if r_hi > 20.0:
        raise ValueError(
            f"circular_cavity_mode_chart: l_over_2a_max 必须 ≤20，得到 "
            f"{l_over_2a_max!r}")
    n_pts = _as_int(n_points, "n_points", 2)
    if n_pts > 401:
        raise ValueError(
            f"circular_cavity_mode_chart: n_points 必须 ≤401，得到 "
            f"{n_points!r}")
    if modes is None:
        mode_names = ["TM010", "TE111", "TM011", "TE021", "TE012",
                      "TM111", "TE011", "TM021"]
    else:
        if not isinstance(modes, (list, tuple)) or len(modes) < 2:
            raise ValueError(
                "circular_cavity_mode_chart: modes 须为 ≥2 个模式名的列表")
        mode_names = [str(name) for name in modes]
    if len(set(mode_names)) != len(mode_names):
        raise ValueError(
            f"circular_cavity_mode_chart: 模式名重复 {mode_names!r}——"
            "显式拒绝")
    parsed = [_parse_mode_name(name) for name in mode_names]

    def _f_norm(mtype: str, mm: int, nn: int, pp: int, r: float) -> float:
        x_root = _te_root(mm, nn) if mtype == "TE" else _tm_root(mm, nn)
        return math.hypot(x_root, pp * math.pi / (2.0 * r))

    ratios = [r_lo + (r_hi - r_lo) * i / (n_pts - 1) for i in range(n_pts)]
    series = []
    for name, (mtype, mm, nn, pp) in zip(mode_names, parsed,
                                            strict=True):
        values = [_f_norm(mtype, mm, nn, pp, r) for r in ratios]
        series.append({
            "mode": name, "type": mtype, "m": mm, "n": nn, "p": pp,
            "x_root": round(_te_root(mm, nn) if mtype == "TE"
                            else _tm_root(mm, nn), 12),
            "f_norm": [round(v, 12) for v in values],
        })
    # 逐格点主模排序 + 主模切换交叉点（变号对二分）
    order_by_r = []
    for i in range(n_pts):
        ranked = sorted(
            range(len(series)),
            key=lambda j: (series[j]["f_norm"][i], series[j]["mode"]))
        order_by_r.append(ranked)
    dominant = [series[j]["mode"] for j in (row[0] for row in order_by_r)]
    crossovers: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for i in range(n_pts - 1):
        for j_a in range(len(series)):
            for j_b in range(j_a + 1, len(series)):
                d1 = (series[j_a]["f_norm"][i]
                      - series[j_b]["f_norm"][i])
                d2 = (series[j_a]["f_norm"][i + 1]
                      - series[j_b]["f_norm"][i + 1])
                if d1 == 0.0 or d1 * d2 < 0.0:
                    pair = tuple(sorted((mode_names[j_a], mode_names[j_b])))
                    if pair in seen_pairs:
                        continue
                    seen_pairs.add(pair)
                    lo, hi = ratios[i], ratios[i + 1]
                    for _ in range(60):
                        mid = 0.5 * (lo + hi)
                        dm = _f_norm(*parsed[j_a], mid) \
                            - _f_norm(*parsed[j_b], mid)
                        if (dm < 0.0) == (d1 < 0.0):
                            lo = mid
                        else:
                            hi = mid
                    r_cross = 0.5 * (lo + hi)
                    crossovers.append({
                        "between": [pair[0], pair[1]],
                        "l_over_2a": round(r_cross, 12),
                        "f_norm": round(
                            _f_norm(*parsed[j_a], r_cross), 12),
                    })
    crossovers.sort(key=lambda item: item["l_over_2a"])
    return {
        "modes": mode_names,
        "epsilon_r": eps_r,
        "l_over_2a_min": r_lo,
        "l_over_2a_max": r_hi,
        "n_points": n_pts,
        "aspect_ratios": [round(r, 12) for r in ratios],
        "series": series,
        "dominant_by_ratio": dominant,
        "crossovers": crossovers,
        "note": (
            "归一化频率已约去 εr 与绝对尺寸（f_ghz = f_norm·C_MM_GHZ/"
            "(2π·a_mm·√εr)）；主模切换点为相邻网格变号对二分求根"
            "（每对只报首次）"),
        "source": _SOURCES["chart"],
    }


# ─── 键 3：任意模式无载 Q（闭式+数值积分双路线）────────────────────────────

def _radial_integrals(mode_type: str, m: int, n: int, radius_m: float,
                      ) -> tuple[float, float, float | None]:
    """数值路线径向积分 (R2m, R2p, R1m)：

    R2m=∫J_m²(kρ)ρdρ、R2p=∫J_m'²(kρ)ρdρ、R1m=∫J_m²(kρ)dρ/ρ（m≥1 才
    需要；m=0 时 R1m=None——1/ρ 项全部带 m² 因子恒零）。scipy.quad
    直接数值积分，不消费任何 Bessel 恒等式。
    """
    from scipy.integrate import quad
    from scipy.special import jv, jvp

    x_root = _te_root(m, n) if mode_type == "TE" else _tm_root(m, n)
    kk = x_root / radius_m

    def _f2(rho: float) -> float:
        val = jv(m, kk * rho)
        return val * val * rho

    def _fp2(rho: float) -> float:
        val = jvp(m, kk * rho)
        return val * val * rho

    def _f_over_rho(rho: float) -> float:
        val = jv(m, kk * rho)
        return val * val / rho

    r2m, _ = quad(_f2, 0.0, radius_m, epsrel=1e-11, limit=400)
    r2p, _ = quad(_fp2, 0.0, radius_m, epsrel=1e-11, limit=400)
    if m >= 1:
        r1m, _ = quad(_f_over_rho, 1e-9 * radius_m, radius_m,
                      epsrel=1e-10, limit=400)
    else:
        r1m = None
    return r2m, r2p, r1m


@register_calculator(
    "circular_cavity_mode_q",
    "圆柱腔任意 TE/TM_mnp 模式无载 Q：导体微扰口径 Q=ωU/P_c（板坐标系"
    "场表达式闭式化简：TE 用 D=1−m²/x'² 恒等式、TM 用 I2x=x²J_{m+1}²/2；"
    "TM010 极限 (ηk0a/2Rs)·L/(L+a) 测试钉）+ 数值积分路线互证"
    "（q_xcheck_rel_dev<1e-9，推导失配即红）+ Ue/Um≈1 谐振定理自检；"
    "介质 Q=1/tanδ（tanδ=0 返 null），1/Qu=1/Qc+1/Qd 串联合成。锚："
    "TE011>TE111（无端壁环流高 Q 性质）；Qc∝1/√σ",
    (("mode_type", "str 'TE' 或 'TM'"),
     ("m", "int 方位序号（≥0；TM010 即 m=0）"),
     ("n", "int 径向序号（≥1）"),
     ("p", "int 轴向序号（TE ≥1——p=0 非物理显式拒绝；TM ≥0）"),
     ("radius_mm", "float mm 腔半径（>0）"),
     ("length_mm", "float mm 腔长（>0）"),
     ("conductivity_s_per_m", "float S/m 导体电导率（>0；Cu=5.8e7）"),
     ("epsilon_r", "float 腔内均匀填充相对介电常数（≥1，缺省 1）"),
     ("mu_r", "float 相对磁导率（>0，缺省 1 非磁性）"),
     ("tan_delta", "float 介质损耗角正切（≥0，缺省 0=无耗）")),
    required=("mode_type", "m", "n", "p", "radius_mm", "length_mm",
              "conductivity_s_per_m"),
)
def circular_cavity_mode_q(mode_type: str, m: int, n: int, p: int,
                           radius_mm: float, length_mm: float,
                           conductivity_s_per_m: float,
                           epsilon_r: float = 1.0, mu_r: float = 1.0,
                           tan_delta: float = 0.0) -> dict[str, Any]:
    mtype = str(mode_type).strip().upper()
    if mtype not in ("TE", "TM"):
        raise ValueError(
            f"circular_cavity_mode_q: mode_type 须为 'TE'/'TM'，得到 "
            f"{mode_type!r}")
    mm = _as_int(m, "m", 0)
    nn = _as_int(n, "n", 1)
    pp = _as_int(p, "p", 1 if mtype == "TE" else 0)
    if mtype == "TE" and pp < 1:
        raise ValueError(
            "circular_cavity_mode_q: TE_mnp 的 p≥1（p=0 时 E_t≡0 非物理，"
            "显式拒绝）")
    a = _finite(radius_mm, "radius_mm")
    length = _finite(length_mm, "length_mm")
    sigma = _finite(conductivity_s_per_m, "conductivity_s_per_m")
    eps_r = _finite(epsilon_r, "epsilon_r")
    mur = _finite(mu_r, "mu_r")
    tand = _finite(tan_delta, "tan_delta")
    if a <= 0.0:
        raise ValueError(
            f"circular_cavity_mode_q: radius_mm 必须 >0，得到 {radius_mm!r}")
    if length <= 0.0:
        raise ValueError(
            f"circular_cavity_mode_q: length_mm 必须 >0，得到 {length_mm!r}")
    if sigma <= 0.0:
        raise ValueError(
            f"circular_cavity_mode_q: conductivity_s_per_m 必须 >0，得到 "
            f"{conductivity_s_per_m!r}")
    if eps_r < 1.0:
        raise ValueError(
            f"circular_cavity_mode_q: epsilon_r 必须 ≥1，得到 {epsilon_r!r}")
    if mur <= 0.0:
        raise ValueError(
            f"circular_cavity_mode_q: mu_r 必须 >0，得到 {mu_r!r}")
    if tand < 0.0:
        raise ValueError(
            f"circular_cavity_mode_q: tan_delta 必须 ≥0，得到 {tan_delta!r}")

    a_m, l_m = a * 1e-3, length * 1e-3
    mu = _MU0 * mur
    eps = _EPS0 * eps_r
    x_root = _te_root(mm, nn) if mtype == "TE" else _tm_root(mm, nn)
    k = x_root / a_m
    kz = pp * math.pi / l_m
    k_total_sq = k * k + kz * kz
    omega = _C0 * math.sqrt(k_total_sq / eps_r)   # rad/s（色散 k²+kz²=k0²εr）
    f_ghz = omega / (2.0 * math.pi) / 1e9
    rs = math.sqrt(math.pi * (omega / (2.0 * math.pi)) * mu / sigma)
    # Lc/Ls：∫cos²(kz z)、∫sin²(kz z)（p=0：L 与 0；p≥1：各 L/2）
    lc = l_m if pp == 0 else l_m / 2.0
    ls = l_m / 2.0 if pp >= 1 else 0.0
    acm = math.pi if mm >= 1 else 2.0 * math.pi   # ∫cos²(mφ)dφ
    r2m, r2p, r1m = _radial_integrals(mtype, mm, nn, a_m)
    r1m_eff = 0.0 if r1m is None else r1m

    # —— 闭式路线（Bessel 恒等式化简，docstring 公式）——
    # TE（J² 因子在分子分母间消去，闭式不含 J 值）：
    #   Qc = ωμ·L·x'²·D·(k²+kz²) / (Rs·[4k⁴·a·Ls + 4kz²m²·Lc/a
    #        + 4kz²x'²·D])，D = 1−m²/x'²，Ls=∫sin²、Lc=∫cos²
    # TM：Qc = I2x·(k²·Lc + kz²·Ls) / (Rs·ωε·(J_{m+1}(x)²·a·k²·Lc
    #        + 2·I2x))，I2x = x²·J_{m+1}(x)²/2
    from scipy.special import jv
    if mtype == "TE":
        d_fac = 1.0 - mm * mm / (x_root * x_root)
        num = (omega * mu * l_m * x_root * x_root * d_fac * k_total_sq)
        den = rs * (
            4.0 * k ** 4 * a_m * ls
            + 4.0 * kz * kz * mm * mm * lc / a_m
            + 4.0 * kz * kz * x_root * x_root * d_fac)
        q_closed = num / den
    else:
        j_next = float(jv(mm + 1, x_root))
        i2x = x_root * x_root * j_next * j_next / 2.0
        q_closed = i2x * (k * k * lc + kz * kz * ls) / (
            rs * omega * eps * (j_next * j_next * a_m * k * k * lc
                                + 2.0 * i2x))

    # —— 数值路线（同场表达式直接积分，不消费恒等式）——
    if mtype == "TE":
        ue = (eps / 4.0) * acm * (
            (omega * mu * mm / (k * k)) ** 2 * ls * r1m_eff
            + (omega * mu / k) ** 2 * ls * r2p)
        um = (mu / 4.0) * acm * (
            (kz / k) ** 2 * lc * r2p
            + (kz * mm / (k * k)) ** 2 * lc * r1m_eff
            + ls * r2m)
        # 侧面（H_t=H_φ+H_z）：J_m²(x')·a·[Ls + (kz·m/(k²a))²·Lc]；
        # 端壁×2（H_t=H_ρ+H_φ，板上 cos=±1 点值无 z 积分）：
        # 2[(kz/k)²R2p + (kz·m/k²)²R1m]
        p_loss = (rs / 2.0) * acm * (
            float(jv(mm, x_root)) ** 2 * a_m
            * (ls + (kz * mm / (k * k * a_m)) ** 2 * lc)
            + 2.0 * ((kz / k) ** 2 * r2p
                     + (kz * mm / (k * k)) ** 2 * r1m_eff))
    else:
        j_next = float(jv(mm + 1, x_root))
        ue = (eps / 4.0) * acm * (
            lc * r2m
            + ls * ((kz / k) ** 2 * r2p
                    + (kz * mm / (k * k)) ** 2 * r1m_eff))
        um = (mu / 4.0) * acm * lc * (
            (omega * eps * mm / (k * k)) ** 2 * r1m_eff
            + (omega * eps / k) ** 2 * r2p)
        p_loss = (rs / 2.0) * acm * (
            (omega * eps / k) ** 2 * j_next ** 2 * a_m * lc
            + 2.0 * ((omega * eps / k) ** 2 * r2p
                     + (omega * eps * mm / (k * k)) ** 2 * r1m_eff))
    ue_over_um = None if um <= 0.0 else ue / um
    q_numeric = omega * (ue + um) / p_loss
    rel_dev = abs(q_closed - q_numeric) / q_closed
    q_d: float | None = None if tand == 0.0 else 1.0 / tand
    q_u = q_closed if q_d is None else q_closed * q_d / (q_closed + q_d)
    return {
        "mode": f"{mtype}{mm}{nn}{pp}",
        "mode_type": mtype,
        "m": mm,
        "n": nn,
        "p": pp,
        "radius_mm": a,
        "length_mm": length,
        "conductivity_s_per_m": sigma,
        "epsilon_r": eps_r,
        "mu_r": mur,
        "tan_delta": tand,
        "f_ghz": round(f_ghz, 9),
        "x_root": round(x_root, 12),
        "rs_ohm_per_sq": round(rs, 15),
        "q_conductor": round(q_closed, 9),
        "q_conductor_numeric": round(q_numeric, 9),
        "q_xcheck_rel_dev": round(rel_dev, 15),
        "ue_over_um": None if ue_over_um is None else round(ue_over_um, 12),
        "q_dielectric": None if q_d is None else round(q_d, 9),
        "q_unloaded": round(q_u, 9),
        "note": (
            "导体 Q 闭式（Bessel 恒等式化简）与数值积分双路线互证；"
            "Ue/Um≈1 为谐振腔储能定理自检（数值精度级）；介质满充均匀"
            "假定；串联合成 1/Qu=1/Qc+1/Qd"),
        "source": _SOURCES["q"],
    }


# ─── 键 4：圆波导 TE/TM_mn 传播解（aurora_e W1-S2 补齐 R7 T2 圆波导子项）───
# 口径（Pozar《Microwave Engineering》§3.4 圆波导/Collin；docstring 写死）：
#   截止：TE_mn fc=x'_mn·c0/(2πa√(εrμr))（x'=J_m' 零点）、TM_mn fc=x_mn·…
#   （TE11 主模 x'_11=1.8412 → fc=0.293·c0/a 经典口径）；工作频率须>fc
#   （截止以下倏逝场不传播，显式拒绝）。
#   β=√(k²−kc²)、λg=2π/β、vp·vg=c0²/(εrμr)（恒等式测试钉）；
#   Z_TE=kη/β、Z_TM=βη/k——TE01/TM11 同根 3.8317 简并 → Z_TE·Z_TM=η²
#   （测试跨调用恒等锚）。
#   导体衰减（微扰 α_c=P_l/(2P)，本席从场表达式独立推导，数值积分双
#   路线互证）：
#     TE_mn: α_c = Rs·kc²·[1+β²m²/(kc⁴a²)] / (kηβaD)，D=1−m²/x'²
#       （Green 恒等式 ∫|∇_tH_z|²=kc²∫|H_z|² + TE 根 J'_m(x')=0 消
#       ∫J'²ρdρ=(a²/2)J_m²(x')D；m=0 退化 α_c=Rs·kc²/(kηβa)——f≫fc
#       渐近 α∝f^(−3/2) 经典 TE0n 低损性质）。
#     TM_mn: α_c = Rs·ωε·J'_m(x)² / (aβ·J_{m+1}(x)²)
#       （Dirichlet 恒等式 ∫J_m²ρdρ=(a²/2)J_{m+1}²(x)）。
#   数值路线：P=½Z·∫|H_t|²dA（E_t=Z·(ẑ×H_t) 波阻抗精确关系）、
#   P_l=(Rs/2)∮|H_t|²dl 侧壁——径向积分 scipy.quad 直积场表达式（复用
#   _radial_integrals，不消费任何 Bessel 恒等式），alpha_c_xcheck_rel_dev
#   应为 quad 精度级。
#   介质衰减 α_d=k²tanδ/(2β)（低损耗均匀填充经典式）。
#   功率容量：P_max=(P/coef²)·(E_br/E_max_per_coef)²；E_max 走横截面
#   2001×361 确定性栅格+两轮交替黄金分割局部精修（TE11 轴线闭式
#   E_max/H0=ωμ/(2kc)——J'_1 与 J_1/z 均在 0 处取极大 ½——测试锚）；
#   E_br 缺省 3e6 V/m 干燥空气工程常数（实际随气压/湿度/表面状态漂移，
#   如实注记非通用常数）。

@register_calculator(
    "circular_waveguide_mode_prop",
    "圆波导模式传播解：TE/TM_mn 单频点截止/波导波长/波阻抗/导体+介质衰减"
    "/功率容量（fc=x·c0/(2πa√(εrμr))，TE11 主模 0.293c0/a 口径；λg=2π/β、"
    "vp·vg=c0²/(εrμr) 恒等；α_c 闭式（TE 用 D=1−m²/x'²、TM 用 J'/J_{m+1} "
    "恒等式）vs 场表达式曲面积分双路线互证；E_max 横截面栅格+局部精修，"
    "TE11 轴线 ωμ/(2kc) 闭式锚；f≤fc 截止显式拒绝）。锚：TE01/TM11 同根 "
    "3.8317 简并 Z_TE·Z_TM=η²；σ×4→α×½；TE01 导体衰减低于 TE11 经典性质",
    (("mode_type", "str 'TE' 或 'TM'"),
     ("m", "int 方位序号（≥0）"),
     ("n", "int 径向序号（≥1）"),
     ("radius_mm", "float mm 波导半径 a（>0）"),
     ("f_ghz", "float GHz 工作频率（须>截止频率，截止以下显式拒绝）"),
     ("conductivity_s_per_m", "float S/m 壁导体电导率（>0；Cu=5.8e7）"),
     ("epsilon_r", "float 填充相对介电常数（≥1，缺省 1）"),
     ("mu_r", "float 填充相对磁导率（>0，缺省 1）"),
     ("tan_delta", "float 填充损耗角正切（≥0，缺省 0）"),
     ("e_br_v_per_m", "float V/m 击穿场强（>0，缺省 3e6 干燥空气工程常数）")),
    required=("mode_type", "m", "n", "radius_mm", "f_ghz",
              "conductivity_s_per_m"),
)
def circular_waveguide_mode_prop(mode_type: str, m: int, n: int,
                                 radius_mm: float, f_ghz: float,
                                 conductivity_s_per_m: float,
                                 epsilon_r: float = 1.0, mu_r: float = 1.0,
                                 tan_delta: float = 0.0,
                                 e_br_v_per_m: float = 3.0e6
                                 ) -> dict[str, Any]:
    import numpy as np
    from scipy.optimize import minimize_scalar
    from scipy.special import jv, jvp

    mtype = str(mode_type).strip().upper()
    if mtype not in ("TE", "TM"):
        raise ValueError(
            f"circular_waveguide_mode_prop: mode_type 须为 'TE'/'TM'，得到 "
            f"{mode_type!r}")
    mm = _as_int(m, "m", 0)
    nn = _as_int(n, "n", 1)
    a = _finite(radius_mm, "radius_mm")
    freq = _finite(f_ghz, "f_ghz")
    sigma = _finite(conductivity_s_per_m, "conductivity_s_per_m")
    eps_r = _finite(epsilon_r, "epsilon_r")
    mur = _finite(mu_r, "mu_r")
    tand = _finite(tan_delta, "tan_delta")
    e_br = _finite(e_br_v_per_m, "e_br_v_per_m")
    if a <= 0.0:
        raise ValueError(
            f"circular_waveguide_mode_prop: radius_mm 必须 >0，得到 "
            f"{radius_mm!r}")
    if freq <= 0.0:
        raise ValueError(
            f"circular_waveguide_mode_prop: f_ghz 必须 >0，得到 {f_ghz!r}")
    if sigma <= 0.0:
        raise ValueError(
            f"circular_waveguide_mode_prop: conductivity_s_per_m 必须 >0，"
            f"得到 {conductivity_s_per_m!r}")
    if eps_r < 1.0:
        raise ValueError(
            f"circular_waveguide_mode_prop: epsilon_r 必须 ≥1，得到 "
            f"{epsilon_r!r}")
    if mur <= 0.0:
        raise ValueError(
            f"circular_waveguide_mode_prop: mu_r 必须 >0，得到 {mu_r!r}")
    if tand < 0.0:
        raise ValueError(
            f"circular_waveguide_mode_prop: tan_delta 必须 ≥0，得到 "
            f"{tan_delta!r}")
    if e_br <= 0.0:
        raise ValueError(
            f"circular_waveguide_mode_prop: e_br_v_per_m 必须 >0，得到 "
            f"{e_br_v_per_m!r}")

    a_m = a * 1e-3
    mu = _MU0 * mur
    eps = _EPS0 * eps_r
    eta = math.sqrt(mu / eps)
    x_root = _te_root(mm, nn) if mtype == "TE" else _tm_root(mm, nn)
    kc = x_root / a_m
    c_med = _C0 / math.sqrt(eps_r * mur)
    fc_ghz = C_MM_GHZ * x_root / (2.0 * math.pi * a * math.sqrt(eps_r * mur))
    if freq <= fc_ghz:
        raise ValueError(
            f"circular_waveguide_mode_prop: f_ghz={freq!r} ≤截止频率 "
            f"fc={fc_ghz:.9g} GHz（{mtype}{mm}{nn} 模截止以下倏逝场不传播，"
            "显式拒绝——调高频率或减小半径）")
    f_hz = freq * 1e9
    omega = 2.0 * math.pi * f_hz
    k = omega / c_med
    beta = math.sqrt(k * k - kc * kc)
    lam0_mm = C_MM_GHZ / freq
    lam_g_mm = 2.0 * math.pi / beta * 1e3
    vp = omega / beta
    vg = c_med * c_med * beta / omega
    z_mode = k * eta / beta if mtype == "TE" else beta * eta / k
    rs = math.sqrt(math.pi * f_hz * mu / sigma)
    alpha_d = k * k * tand / (2.0 * beta)

    a_phi = math.pi if mm >= 1 else 2.0 * math.pi
    _r2m, r2p, r1m = _radial_integrals(mtype, mm, nn, a_m)
    r1m_eff = 0.0 if r1m is None else r1m
    jm = float(jv(mm, x_root))
    if mtype == "TE":
        d_fac = 1.0 - mm * mm / (x_root * x_root)
        alpha_c = rs * kc * kc * (
            1.0 + beta * beta * mm * mm / (kc ** 4 * a_m * a_m)
        ) / (k * eta * beta * a_m * d_fac)
        # 数值路线：P=½Z·∫|H_t|²dA + 侧壁 P_l（quad 直积场表达式）
        p_flow = 0.5 * (k * eta / beta) * a_phi * (
            (beta / kc) ** 2 * r2p
            + (beta * mm / (kc * kc)) ** 2 * r1m_eff)
        p_loss = 0.5 * rs * a_m * jm * jm * a_phi * (
            1.0 + (beta * mm / (kc * kc * a_m)) ** 2)
    else:
        jp = float(jvp(mm, x_root))
        jn1 = float(jv(mm + 1, x_root))
        alpha_c = rs * omega * eps * jp * jp / (beta * a_m * jn1 * jn1)
        p_flow = 0.5 * (beta * eta / k) * a_phi * (omega * eps) ** 2 * (
            r2p / (kc * kc) + mm * mm * r1m_eff / (kc ** 4))
        p_loss = 0.5 * rs * a_m * (omega * eps / kc) ** 2 * jp * jp * a_phi
    alpha_num = p_loss / (2.0 * p_flow)
    rel_dev = abs(alpha_c - alpha_num) / alpha_c

    # E_max 横截面确定性栅格 + 两轮交替黄金分割精修（per 场系数）
    u_grid = np.linspace(1e-9, 1.0, 2001)
    ph_grid = np.linspace(0.0, 2.0 * math.pi, 361)
    xu = x_root * u_grid

    def _e2(pv: float, uv: float) -> float:
        s2 = math.sin(mm * pv) ** 2
        c2 = math.cos(mm * pv) ** 2
        if mtype == "TE":
            t_r = (mm * float(jv(mm, uv)) / uv) ** 2
            t_p = float(jvp(mm, uv)) ** 2
            return (omega * mu / kc) ** 2 * (t_r * s2 + t_p * c2)
        t_z = float(jv(mm, uv)) ** 2
        t_r = float(jvp(mm, uv)) ** 2
        t_p = (mm * float(jv(mm, uv)) / uv) ** 2
        return t_z * c2 + (beta / kc) ** 2 * (t_r * c2 + t_p * s2)

    if mtype == "TE":
        e2_grid = (omega * mu / kc) ** 2 * (
            (mm * jv(mm, xu) / xu) ** 2
            * np.sin(mm * ph_grid)[:, None] ** 2
            + jvp(mm, xu) ** 2 * np.cos(mm * ph_grid)[:, None] ** 2)
    else:
        e2_grid = (
            jv(mm, xu) ** 2 * np.cos(mm * ph_grid)[:, None] ** 2
            + (beta / kc) ** 2 * (
                jvp(mm, xu) ** 2 * np.cos(mm * ph_grid)[:, None] ** 2
                + (mm * jv(mm, xu) / xu) ** 2
                * np.sin(mm * ph_grid)[:, None] ** 2))
    i_ph, i_u = (int(v) for v in np.unravel_index(
        np.argmax(e2_grid), e2_grid.shape))
    pv, uv = float(ph_grid[i_ph]), float(u_grid[i_u])
    du = float(u_grid[1] - u_grid[0])
    dp = float(ph_grid[1] - ph_grid[0])
    for _ in range(2):
        pv_fix = pv
        uv_fix = uv
        res = minimize_scalar(
            lambda t, p0=pv_fix: -_e2(p0, t),
            bounds=(max(1e-9, uv_fix - du), min(1.0, uv_fix + du)),
            method="bounded", options={"xatol": 1e-12})
        uv = float(res.x)
        res = minimize_scalar(
            lambda t, u0=uv: -_e2(t, u0), bounds=(pv - dp, pv + dp),
            method="bounded", options={"xatol": 1e-12})
        pv = float(res.x)
    e_max = math.sqrt(max(_e2(pv, uv), 0.0))
    p_max = p_flow * (e_br / e_max) ** 2

    return {
        "mode": f"{mtype}{mm}{nn}",
        "mode_type": mtype,
        "m": mm,
        "n": nn,
        "x_root": round(x_root, 12),
        "radius_mm": a,
        "f_ghz": freq,
        "epsilon_r": eps_r,
        "mu_r": mur,
        "tan_delta": tand,
        "fc_ghz": round(fc_ghz, 9),
        "f_over_fc": round(freq / fc_ghz, 12),
        "kc_rad_per_m": round(kc, 12),
        "beta_rad_per_m": round(beta, 12),
        "lambda_0_mm": round(lam0_mm, 9),
        "lambda_g_mm": round(lam_g_mm, 9),
        "lambda_g_check_mm": round(
            lam0_mm / math.sqrt(eps_r * mur)
            / math.sqrt(1.0 - (fc_ghz / freq) ** 2), 9),
        "vp_m_per_s": round(vp, 9),
        "vg_m_per_s": round(vg, 9),
        "vp_vg_identity": round(vp * vg / (c_med * c_med), 15),
        "eta_ohm": round(eta, 12),
        "z_mode_ohm": round(z_mode, 9),
        "rs_ohm_per_sq": round(rs, 15),
        "alpha_c_np_per_m": float(alpha_c),
        "alpha_c_db_per_m": round(alpha_c * 8.685889638065035, 12),
        "alpha_c_numeric_np_per_m": float(alpha_num),
        "alpha_c_xcheck_rel_dev": round(rel_dev, 15),
        "alpha_d_np_per_m": float(alpha_d),
        "alpha_total_db_per_m": round(
            (alpha_c + alpha_d) * 8.685889638065035, 12),
        "e_br_v_per_m": e_br,
        "e_max_per_coef_v_per_m": round(e_max, 9),
        "p_flow_per_coef_sq_w": float(p_flow),
        "p_max_w": float(p_max),
        "note": (
            "α_c 闭式（Bessel 恒等式化简）与场表达式曲面积分双路线互证"
            "（alpha_c_xcheck_rel_dev 应为 quad 精度级）；Z=波阻抗口径 "
            "Z_TE=kη/β、Z_TM=βη/k；功率容量=场极大处达 E_br 的口径，"
            "E_br=3e6 V/m 为干燥空气工程常数（实际随气压/湿度/内表面"
            "状态漂移，如实注记）；衰减微扰假定壁损耗≪传输功率"),
        "source": (
            "Pozar Microwave Engineering §3.4 圆波导（Bessel 零点闭式："
            "截止/β/λg/Z_TE/Z_TM/α_c 微扰式）；Collin；α_c 双路线互证与 "
            "E_max 栅格精修为本席独立推导落地"),
    }


# ─── 键 5/6：矩形腔 TE/TM_mnp 谱 + 任意模式 Q（aurora_e W1-S2 补齐 R7 T2
# ─── "矩形腔留续作"子项）────────────────────────────────────────────────────
# 口径（Pozar《Microwave Engineering》§6.3 矩形腔；docstring 写死）：
#   谐振频率（腔 a×b×d mm，均匀填充 εr/μr，分离变量闭式）：
#     f_mnp = (c0/(2√(εrμr)))·√((mπ/a)²+(nπ/b)²+(pπ/d)²)/(π)
#           = (c0/(2√(εrμr)))·√((m/a)²+(n/b)²+(p/d)²)
#     TE_mnp: (m,n)≠(0,0) 且 p≥1（m=n=0 时全部场≡0 非物理，显式拒绝）；
#     TM_mnp: m,n≥1 且 p≥0（p=0 允许——E_z 对端壁法向）。
#   TE101 空腔 f=(c0/2)√(1/a²+1/d²) 与 cavity_perturbation_shift 的空腔
#   f0 同式（同仓双源，测试互证 ≤1e-12）。
#   无载 Q（导体微扰 Q=ω(U_e+U_m)/P_c；六壁切向 H 面积分；场分量可分离
#   → 1-D 因子闭式：Cx=a/2(m≥1)/a(m=0)、Sx=a/2(m≥1)/0(m=0)（sin(0)≡0），
#   y 同规则；Cz=d/2(p≥1)/d(p=0)、Sz=d/2/0）：
#     TE：|E|²=(ωμ/kc²)²·H0²·[ky²cos²(mx)sin²(ny)+kx²sin²(mx)cos²(ny)]
#          ·sin²(pz)；|H|²=H0²·[(kzkx/kc²)²sin·cos·cos+(kzky/kc²)²cos·
#          sin·cos+cos²·cos²·sin²]（各按 x,y,z 分量重组）
#     TM：E_z=E0·sin(mx)sin(ny)cos(pz)，E_t∝kz∇_t、H_t∝ωε(ẑ×∇_t)
#     Ue/Um≈1 谐振腔储能定理 in-output 自检（任何分量系数写错即破坏）。
#   数值路线：同样 1-D 因子改 scipy.quad 直积 sin²/cos²（不走 a/2 闭式
#   短路），q_xcheck_rel_dev 应 <1e-12。介质 Q=1/tanδ（0 如实返 null）、
#   串联合成 1/Qu=1/Qc+1/Qd（同 circular_cavity_mode_q 口径）。

_RECT_ENUM_MAX_CANDIDATES = 30000


@register_calculator(
    "rectangular_cavity_mode_spectrum",
    "矩形腔多模谐振谱：TE/TM_mnp 分离变量闭式 f=(c0/(2√(εrμr)))·√((m/a)²+"
    "(n/b)²+(p/d)²)（TE_mnp: (m,n)≠(0,0) 且 p≥1；TM_mnp: m,n≥1 且 p≥0，"
    "Pozar §6.3），给腔尺寸/频段 → 带内模式频率列表（排序）+全谱主模标识"
    "（计算判读非假定）+TE10 波导截止参考 c0/(2a√(εrμr))。锚：TE101 与 "
    "cavity_perturbation_shift 空腔 f0=(c0/2)√(1/a²+1/d²) 同仓双源；εr "
    "标度全谱 ÷√εr",
    (("a_mm", "float mm 腔 x 边长（>0）"),
     ("b_mm", "float mm 腔 y 边长（>0）"),
     ("d_mm", "float mm 腔 z 边长（>0）"),
     ("f_min_ghz", "float GHz 频段下缘（>0，<f_max_ghz）"),
     ("f_max_ghz", "float GHz 频段上缘（>f_min_ghz）"),
     ("epsilon_r", "float 填充相对介电常数（≥1，缺省 1）"),
     ("mu_r", "float 填充相对磁导率（>0，缺省 1）"),
     ("max_modes", "int 带内模式数上限（1..500，缺省 200；超限显式拒绝"
      "要求收窄频段）")),
    required=("a_mm", "b_mm", "d_mm", "f_min_ghz", "f_max_ghz"),
)
def rectangular_cavity_mode_spectrum(a_mm: float, b_mm: float, d_mm: float,
                                     f_min_ghz: float, f_max_ghz: float,
                                     epsilon_r: float = 1.0,
                                     mu_r: float = 1.0,
                                     max_modes: int = 200
                                     ) -> dict[str, Any]:
    aa = _finite(a_mm, "a_mm")
    bb = _finite(b_mm, "b_mm")
    dd = _finite(d_mm, "d_mm")
    f_lo = _finite(f_min_ghz, "f_min_ghz")
    f_hi = _finite(f_max_ghz, "f_max_ghz")
    eps_r = _finite(epsilon_r, "epsilon_r")
    mur = _finite(mu_r, "mu_r")
    n_cap = _as_int(max_modes, "max_modes", 1)
    if aa <= 0.0 or bb <= 0.0 or dd <= 0.0:
        raise ValueError(
            f"rectangular_cavity_mode_spectrum: 腔尺寸 a/b/d 必须 >0，得到 "
            f"{a_mm!r}/{b_mm!r}/{d_mm!r}")
    if n_cap > 500:
        raise ValueError(
            f"rectangular_cavity_mode_spectrum: max_modes 必须 ≤500，得到 "
            f"{max_modes!r}（超宽谱请收窄频段，非提高上限）")
    if f_lo <= 0.0 or f_hi <= f_lo:
        raise ValueError(
            f"rectangular_cavity_mode_spectrum: 须 0 < f_min_ghz < "
            f"f_max_ghz，得到 {f_min_ghz!r}/{f_max_ghz!r}")
    if eps_r < 1.0:
        raise ValueError(
            f"rectangular_cavity_mode_spectrum: epsilon_r 必须 ≥1，得到 "
            f"{epsilon_r!r}")
    if mur <= 0.0:
        raise ValueError(
            f"rectangular_cavity_mode_spectrum: mu_r 必须 >0，得到 {mu_r!r}")

    v_fac = math.sqrt(eps_r * mur)
    # k_total ≤ 2π f √(εrμr)/c0 → √((m/a)²+…) ≤ 2 f v_fac/C_MM_GHZ [1/mm]
    ksum_max = 2.0 * f_hi * v_fac / C_MM_GHZ
    m_cap = math.floor(ksum_max * aa) + 1
    n_cap_ax = math.floor(ksum_max * bb) + 1

    candidates: list[tuple[float, str]] = []
    for mm in range(0, m_cap + 1):
        for nn in range(0, n_cap_ax + 1):
            lat = (mm / aa) ** 2 + (nn / bb) ** 2
            if mm == 0 and nn == 0:
                continue
            # TE_mnp（p≥1）；p 上限由 √((m/a)²+(n/b)²+(p/d)²)≤ksum_max 直接
            # 给出（ksum_max 与 (m/a) 同量纲，无 π 因子）
            p_hi_te = math.floor(dd * math.sqrt(
                max(0.0, ksum_max * ksum_max - lat)))
            for pp in range(1, p_hi_te + 1):
                f_ghz = C_MM_GHZ / (2.0 * v_fac) * math.sqrt(
                    lat + (pp / dd) ** 2)
                if f_lo <= f_ghz <= f_hi:
                    candidates.append((f_ghz, f"TE{mm}{nn}{pp}"))
            # TM_mnp（m,n≥1，p≥0）
            if mm >= 1 and nn >= 1:
                for pp in range(0, p_hi_te + 1):
                    f_ghz = C_MM_GHZ / (2.0 * v_fac) * math.sqrt(
                        lat + (pp / dd) ** 2)
                    if f_lo <= f_ghz <= f_hi:
                        candidates.append((f_ghz, f"TM{mm}{nn}{pp}"))
            if len(candidates) > _RECT_ENUM_MAX_CANDIDATES:
                raise ValueError(
                    "rectangular_cavity_mode_spectrum: 候选模式组合爆炸"
                    "（>30000）——频段过宽，请收窄 f_max_ghz")
    candidates.sort(key=lambda item: (item[0], item[1]))
    if len(candidates) > n_cap:
        raise ValueError(
            f"rectangular_cavity_mode_spectrum: 带内模式数 {len(candidates)} "
            f"> max_modes={n_cap}——频段过宽，请收窄 f_min_ghz/f_max_ghz")
    dominant = candidates[0] if candidates else None
    te10_cutoff = C_MM_GHZ / (2.0 * aa * v_fac)
    return {
        "a_mm": aa,
        "b_mm": bb,
        "d_mm": dd,
        "f_min_ghz": f_lo,
        "f_max_ghz": f_hi,
        "epsilon_r": eps_r,
        "mu_r": mur,
        "n_modes_in_band": len(candidates),
        "modes": [{"mode": name, "f_ghz": round(f_ghz, 9)}
                  for f_ghz, name in candidates],
        "dominant_mode": None if dominant is None else dominant[1],
        "dominant_f_ghz": (None if dominant is None
                           else round(dominant[0], 9)),
        "te10_waveguide_cutoff_ghz": round(te10_cutoff, 9),
        "dominant_criterion_note": (
            "主模=全谱最低频模式（计算判读）；经典口径 a<d 时 TE101 主模"
            "（本键按全谱计算判读，不按口径假定）"),
        "note": (
            "分离变量闭式谱；p≥1 的 TE 与 p≥0 的 TM 均按口径枚举；TE101 "
            "空腔频率与 cavity_perturbation_shift 空腔 f0 同式（同仓双源）"),
        "source": (
            "Pozar Microwave Engineering §6.3 矩形腔（分离变量闭式谐振"
            "谱；TE/TM 指标规则）"),
    }


def _rect_mode_validations(mtype: str, mm: int, nn: int, pp: int,
                           where: str) -> None:
    """矩形腔模式指标合法性（TE/TM 规则不同，显式拒绝）。"""
    if mtype == "TE":
        if mm == 0 and nn == 0:
            raise ValueError(
                f"{where}: TE_mnp 的 (m,n) 不可同时为 0（全部场≡0 非物理，"
                "显式拒绝）")
        if pp < 1:
            raise ValueError(
                f"{where}: TE_mnp 的 p≥1（p=0 时 E≡0 非物理，显式拒绝）")
    else:
        if mm < 1 or nn < 1:
            raise ValueError(
                f"{where}: TM_mnp 的 m,n ≥1（E_z=sin(mx)sin(ny) 要求，"
                f"得到 m={mm},n={nn} 显式拒绝）")
        if pp < 0:
            raise ValueError(f"{where}: TM_mnp 的 p≥0，得到 {pp!r}")


@register_calculator(
    "rectangular_cavity_mode_q",
    "矩形腔任意 TE/TM_mnp 模式无载 Q：导体微扰 Q=ω(U_e+U_m)/P_c（六壁切向"
    "H 面积分；场分量可分离 → 1-D 因子闭式（Cx=a/2(m≥1)/a(m=0)、Sx=a/2/"
    "0 同规则、Cz=d/2(p≥1)/d(p=0)）+ 同场表达式 scipy.quad 数值因子双路线"
    "互证（rel_dev<1e-12，推导失配即红）+ Ue/Um≈1 谐振定理自检；介质 "
    "Q=1/tanδ（0 返 null），1/Qu=1/Qc+1/Qd。锚：σ×4→Qc×2；f 与谱键 "
    "TE101 同仓双源跨键互证；与 cavity_perturbation_shift 口径互补",
    (("mode_type", "str 'TE' 或 'TM'"),
     ("m", "int x 向序号（TE≥0；TM≥1）"),
     ("n", "int y 向序号（TE≥0；TM≥1；(m,n)=(0,0) TE 显式拒绝）"),
     ("p", "int z 向序号（TE ≥1；TM ≥0）"),
     ("a_mm", "float mm 腔 x 边长（>0）"),
     ("b_mm", "float mm 腔 y 边长（>0）"),
     ("d_mm", "float mm 腔 z 边长（>0）"),
     ("conductivity_s_per_m", "float S/m 壁导体电导率（>0；Cu=5.8e7）"),
     ("epsilon_r", "float 填充相对介电常数（≥1，缺省 1）"),
     ("mu_r", "float 填充相对磁导率（>0，缺省 1）"),
     ("tan_delta", "float 介质损耗角正切（≥0，缺省 0=无耗）")),
    required=("mode_type", "m", "n", "p", "a_mm", "b_mm", "d_mm",
              "conductivity_s_per_m"),
)
def rectangular_cavity_mode_q(mode_type: str, m: int, n: int, p: int,
                              a_mm: float, b_mm: float, d_mm: float,
                              conductivity_s_per_m: float,
                              epsilon_r: float = 1.0, mu_r: float = 1.0,
                              tan_delta: float = 0.0) -> dict[str, Any]:
    from scipy.integrate import quad

    mtype = str(mode_type).strip().upper()
    if mtype not in ("TE", "TM"):
        raise ValueError(
            f"rectangular_cavity_mode_q: mode_type 须为 'TE'/'TM'，得到 "
            f"{mode_type!r}")
    mm = _as_int(m, "m", 0)
    nn = _as_int(n, "n", 0)
    pp = _as_int(p, "p", 0)
    _rect_mode_validations(mtype, mm, nn, pp, "rectangular_cavity_mode_q")
    aa = _finite(a_mm, "a_mm")
    bb = _finite(b_mm, "b_mm")
    dd = _finite(d_mm, "d_mm")
    sigma = _finite(conductivity_s_per_m, "conductivity_s_per_m")
    eps_r = _finite(epsilon_r, "epsilon_r")
    mur = _finite(mu_r, "mu_r")
    tand = _finite(tan_delta, "tan_delta")
    if aa <= 0.0 or bb <= 0.0 or dd <= 0.0:
        raise ValueError(
            f"rectangular_cavity_mode_q: 腔尺寸 a/b/d 必须 >0，得到 "
            f"{a_mm!r}/{b_mm!r}/{d_mm!r}")
    if sigma <= 0.0:
        raise ValueError(
            f"rectangular_cavity_mode_q: conductivity_s_per_m 必须 >0，"
            f"得到 {conductivity_s_per_m!r}")
    if eps_r < 1.0:
        raise ValueError(
            f"rectangular_cavity_mode_q: epsilon_r 必须 ≥1，得到 "
            f"{epsilon_r!r}")
    if mur <= 0.0:
        raise ValueError(
            f"rectangular_cavity_mode_q: mu_r 必须 >0，得到 {mu_r!r}")
    if tand < 0.0:
        raise ValueError(
            f"rectangular_cavity_mode_q: tan_delta 必须 ≥0，得到 "
            f"{tan_delta!r}")

    # 全 SI 组装（ω 为 SI rad/s、k/长度/因子一律 m——混 mm 会差 1e6；
    # 频率出口按 mm·GHz 常数换算）
    a_si, b_si, d_si = aa * 1e-3, bb * 1e-3, dd * 1e-3
    kx = mm * math.pi / a_si
    ky = nn * math.pi / b_si
    kz = pp * math.pi / d_si
    kc2 = kx * kx + ky * ky
    k_total = math.sqrt(kc2 + kz * kz)
    f_hz = _C0 * k_total / (2.0 * math.pi * math.sqrt(eps_r * mur))
    f_ghz = f_hz / 1e9
    omega = 2.0 * math.pi * f_hz
    mu = _MU0 * mur
    eps = _EPS0 * eps_r
    rs = math.sqrt(math.pi * f_hz * mu / sigma)

    def _c(idx: int, length: float) -> float:
        return length / 2.0 if idx >= 1 else length

    def _s(idx: int, length: float) -> float:
        return length / 2.0 if idx >= 1 else 0.0

    cx, cy, cz = _c(mm, a_si), _c(nn, b_si), _c(pp, d_si)
    sx, sy, sz = _s(mm, a_si), _s(nn, b_si), _s(pp, d_si)

    def _assemble(sfx: tuple[float, ...], cfx: tuple[float, ...]
                  ) -> tuple[float, float, float, float, float]:
        """按场分量因子（sx,sy,sz）/（cx,cy,cz）组装 (Ue,Um,Px,Py,Pz)。"""
        nsx, nsy, nsz = sfx
        ncx, ncy, ncz = cfx
        if mtype == "TE":
            ue = eps / 4.0 * (omega * mu / kc2) ** 2 * (
                ky * ky * ncx * nsy * nsz + kx * kx * nsx * ncy * nsz)
            um = mu / 4.0 * (
                (kz * kx / kc2) ** 2 * nsx * ncy * ncz
                + (kz * ky / kc2) ** 2 * ncx * nsy * ncz
                + ncx * ncy * nsz)
            # 六壁损耗：可分离因子已是 ∫dy·∫dz 面积分（勿再加面积前缀）
            px = 2.0 * (rs / 2.0) * (
                (kz * ky / kc2) ** 2 * nsy * ncz + ncy * ncz)
            py = 2.0 * (rs / 2.0) * (
                (kz * kx / kc2) ** 2 * nsx * ncz + ncx * ncz)
            pz = 2.0 * (rs / 2.0) * (
                (kz * kx / kc2) ** 2 * nsx * ncy
                + (kz * ky / kc2) ** 2 * ncx * nsy)
        else:
            ue = eps / 4.0 * (
                nsx * nsy * ncz
                + (kz * kx / kc2) ** 2 * ncx * nsy * nsz
                + (kz * ky / kc2) ** 2 * nsx * ncy * nsz)
            um = mu / 4.0 * (omega * eps / kc2) ** 2 * (
                ky * ky * nsx * ncy * ncz + kx * kx * ncx * nsy * ncz)
            px = 2.0 * (rs / 2.0) * (
                omega * eps * kx / kc2) ** 2 * nsy * ncz
            py = 2.0 * (rs / 2.0) * (
                omega * eps * ky / kc2) ** 2 * nsx * ncz
            pz = 2.0 * (rs / 2.0) * (omega * eps / kc2) ** 2 * (
                ky * ky * nsx * ncy + kx * kx * ncx * nsy)
        return ue, um, px, py, pz

    we, wm, px_c, py_c, pz_c = _assemble((sx, sy, sz), (cx, cy, cz))

    def _q_fac(idx: int, length: float, kind: str) -> float:
        def integrand(t: float) -> float:
            arg = idx * math.pi * t / length
            return (math.sin(arg) ** 2 if kind == "s"
                    else math.cos(arg) ** 2)

        val, _err = quad(integrand, 0.0, length, epsrel=1e-12, limit=200)
        return val

    qsx, qcx = _q_fac(mm, a_si, "s"), _q_fac(mm, a_si, "c")
    qsy, qcy = _q_fac(nn, b_si, "s"), _q_fac(nn, b_si, "c")
    qsz, qcz = _q_fac(pp, d_si, "s"), _q_fac(pp, d_si, "c")
    we_n, wm_n, px_n, py_n, pz_n = _assemble(
        (qsx, qsy, qsz), (qcx, qcy, qcz))

    q_closed = omega * (we + wm) / (px_c + py_c + pz_c)
    q_numeric = omega * (we_n + wm_n) / (px_n + py_n + pz_n)
    rel_dev = abs(q_closed - q_numeric) / q_closed
    ue_over_um = None if wm <= 0.0 else we / wm
    q_d: float | None = None if tand == 0.0 else 1.0 / tand
    q_u = q_closed if q_d is None else q_closed * q_d / (q_closed + q_d)
    return {
        "mode": f"{mtype}{mm}{nn}{pp}",
        "mode_type": mtype,
        "m": mm,
        "n": nn,
        "p": pp,
        "a_mm": aa,
        "b_mm": bb,
        "d_mm": dd,
        "conductivity_s_per_m": sigma,
        "epsilon_r": eps_r,
        "mu_r": mur,
        "tan_delta": tand,
        "f_ghz": round(f_ghz, 9),
        "rs_ohm_per_sq": round(rs, 15),
        "q_conductor": round(q_closed, 9),
        "q_conductor_numeric": round(q_numeric, 9),
        "q_xcheck_rel_dev": round(rel_dev, 15),
        "ue_over_um": None if ue_over_um is None else round(ue_over_um, 12),
        "q_dielectric": None if q_d is None else round(q_d, 9),
        "q_unloaded": round(q_u, 9),
        "note": (
            "导体 Q 闭式（1-D 因子解析）与 quad 数值因子双路线互证；"
            "Ue/Um≈1 为谐振腔储能定理自检；介质满充均匀假定；串联合成 "
            "1/Qu=1/Qc+1/Qd；微扰假定壁损耗≪储能"),
        "source": (
            "Pozar Microwave Engineering §6.3 矩形腔（微扰 Q=ωU/P_c 六壁"
            "积分；分离变量因子闭式）；数值因子路线为本席独立落地"),
    }
