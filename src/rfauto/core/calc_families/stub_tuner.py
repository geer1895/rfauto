"""并联支节调配器族（aurora72 A3-B 席域 1，R7 第二梯队 T3）。

两键：stub_tuner_double（双支节并联调配：归一电纳解析解 + 禁区
g>csc²(βd) 判定 + ABCD 级联 |Γ| 回代） / stub_tuner_triple（三支节级联
消除禁区：首支节旁路/旋转双路线确定性规则，任意无源负载有解）。

与既有匹配面的边界（语义防撞，R7 §③ T3 三重搜索证据）
--------------------------------------------------------
- t_match（t_match_design/t_match_impedance）= 三元件集总 L 型网络；
  本族只做**分布参数并联支节**拓扑。
- quarter_wave_transformer / klopfenstein_taper = λ/4 变换/渐变线；
  本族不碰阻抗变换器。
- rf_match/synthesis.py 的微带综合面 = 模板级几何综合；本族只做
  **双/三支节调配拓扑的解析解**（单支节不在 R7 T3 立项口径，如实
  不做）。

物理口径（docstring 写死，#1c/#300 出处纪律）
----------------------------------------------
归一化负载导纳 y_L = Z0/Z_L = g + jb（并联支节=导纳法自然口径），
全部公式归一到 Z0（Pozar *Microwave Engineering* §5.3 双支节调配）：

- 支节只提供纯电纳：支节处总电纳 u = b + b_s1 可取任意实数（开路支节
  b_s=tan(βl)、短路支节 b_s=−cot(βl) 值域均覆盖全实轴）。
- 经间距 d（t=tan βd）变换：y2 = (y + jt)/(1 + jyt)，展开取实部
  g2 = g(1+t²)/[(1−tu)² + t²g²]。令 g2=1：
      (1−tu)² = g·[1 + t²(1−g)] ≡ D
  有实解 ⟺ D ≥ 0 ⟺ g ≤ 1 + 1/t² = csc²(βd) ≡ g_max——即**禁区**
  g > csc²(βd)（λ/8 间距 βd=45° → g_max=2，Pozar 经典口径；3λ/8
  βd=135° 同为 2）。判据与 Smith 图旋转电导圆等价（测试钉解析式）。
- 解：u = [1 ∓ √D]/t，取 |u| 最小支（最小电纳工程规则，确定性）；
  b_s1 = u − b；y2 = 1 + j·b2 → b_s2 = −b2。
- 支节长度：开路 l/λ = atan(b_s)/(2π) mod 0.5；短路 tan(βl) = −1/b_s
  → l/λ = atan(−1/b_s)/(2π) mod 0.5（b_s=0 短路支节=λ/4 开路器）。
- 三支节（等间距 d）：确定性两路线——①首支节旁路：y_b = T(y_a,t)
  且 Re(y_b) ≤ g_max → b_s1=0，按双支节解后两支节；②首支节旋转：
  g_a ≤ g_max 时取 u1 使 g2=1（u1=[1∓√D]/t 取 |u1| 最小支），g_a >
  g_max 时取 u1=1/t（可达 g2 上峰=(1+t²)/(t²g_a)<1<g_max，必可解），
  再按双支节解后两支节。任意 r_L>0 负载有解（u1→∞ 时 g2→0），
  测试 200 随机负载全匹配。

验证（in-output xcheck + 测试侧独立重算，#118 不自证）
------------------------------------------------------
- ABCD 级联回代：[线(stub1_deg)→并联 jb_s1→线(间距)→并联 jb_s2]
  （三支节再加一节）终接 z_L，z_in=(Az_L+B)/(Cz_L+D)，|Γ_in| 应为
  机器精度级（in-output gamma_in_abs + matched 旗标；测试侧独立重算
  ABCD 逐位回收）。
- 禁区边界解析式：g_max=csc²(βd)：45°→2.0、135°→2.0、60°→4/3
  测试侧独立常数。
- 支节长度恒等式：tan(βl)=b_s（开路）/−cot(βl)=b_s（短路）测试侧
  回代；b_s=0 短路→0.25λ。

守卫：rl_ohm>0（纯电抗负载 |Γ|=1 在 Smith 图边缘，调配问题退化，
显式拒绝）；z0_ohm>0；xl_ohm 有限任意；spacing_deg ∈ [5,175] 且
≠90°（tan 奇点；λ/8=45°、3λ/8=135° 主用例）；stub1_deg ∈ [0,180)；
stub_type ∈ {"open","short"}；越界一律显式拒绝。禁区负载不拒绝，
如实返回 solvable=False + 禁区数据（调配器诊断面，参照 #274 门常量
分派纪律——"无解"是结果不是输入错误）。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import register_calculator
from .thermal import _finite

_SOURCES = {
    "double": "Pozar Microwave Engineering §5.3 双支节调配（禁区 csc²(βd) 口径）；"
              "ABCD 级联回代为测试侧独立实现",
    "triple": "Pozar §5.3 三支节调配（首支节旁路/旋转消除禁区）；确定性路线规则"
              "为本仓口径（docstring 写死）",
}


# ─── 共享闭式 helper（纯函数，无 IO）─────────────────────────────────────────

def _normalize_y(rl_ohm: float, xl_ohm: float, z0_ohm: float) -> complex:
    """归一化负载导纳 y_L = Z0/Z_L = g + jb。"""
    z_l = complex(rl_ohm, xl_ohm)
    return z0_ohm / z_l


def _transform_y(y: complex, t: float) -> complex:
    """无损线长 βd（t=tan βd）向输入端看去的导纳变换 y_in=(y_L+jt)/(1+jy_L t)。"""
    return (y + 1j * t) / (1.0 + 1j * y * t)


def _g_max(t: float) -> float:
    """双支节禁区边界 g_max = 1 + 1/t² = csc²(βd)。"""
    return 1.0 + 1.0 / (t * t)


def _solve_double_from(g: float, b: float, t: float) -> tuple[float, complex] | None:
    """双支节闭式：输入 (g,b) 与 t → (b_s1, y2) 或 None（禁区 D<0）。

    u=[1∓√D]/t 取 |u| 最小支；返回的 y2 = T(g+j u, t)（g2 应=1）。
    """
    d_val = g * (1.0 + t * t * (1.0 - g))
    if d_val < -1e-12:
        return None
    root = math.sqrt(max(d_val, 0.0))
    u = min([(1.0 - root) / t, (1.0 + root) / t], key=abs)
    y2 = _transform_y(complex(g, u), t)
    return u - b, y2


def _stub_len_over_lambda(b_s: float, stub_type: str) -> float:
    """支节电纳 → 长度（λ 归一，(0,0.5] 口径；b_s=0 开路→0、短路→0.25）。"""
    if stub_type == "open":
        beta_l = math.atan(b_s)
    else:
        beta_l = math.pi / 2.0 if b_s == 0.0 else math.atan(-1.0 / b_s)
        if beta_l < 0.0:
            beta_l += math.pi
    return (beta_l / (2.0 * math.pi)) % 0.5


def _stub_len_or_null(b_s: float | None, stub_type: str) -> float | None:
    if b_s is None:
        return None
    return round(_stub_len_over_lambda(b_s, stub_type), 12)


def _abcd_gamma(rl_ohm: float, xl_ohm: float, z0_ohm: float,
                sections: list[tuple[str, float]]) -> float:
    """ABCD 级联 |Γ_in|（归一化；sections 从输入端到负载序）。"""
    a_m, b_m, c_m, d_m = 1.0 + 0j, 0j, 0j, 1.0 + 0j
    for kind, value in sections:
        if kind == "line":
            m00 = m11 = complex(math.cos(value), 0.0)
            m01 = m10 = 1j * math.sin(value)
        else:  # shunt
            m00, m01, m10, m11 = 1.0 + 0j, 0j, 1j * value, 1.0 + 0j
        a_n = a_m * m00 + b_m * m10
        b_n = a_m * m01 + b_m * m11
        c_n = c_m * m00 + d_m * m10
        d_n = c_m * m01 + d_m * m11
        a_m, b_m, c_m, d_m = a_n, b_n, c_n, d_n
    z_l = complex(rl_ohm, xl_ohm) / z0_ohm
    z_in = (a_m * z_l + b_m) / (c_m * z_l + d_m)
    return abs((z_in - 1.0) / (z_in + 1.0))


def _validate_common(params: dict[str, Any]) -> tuple[float, float, float, float, float, str]:
    """公共入参守卫与解析：→ (rl, xl, z0, t, th1_rad, stub_type)。"""
    rl = _finite(params["rl_ohm"], "rl_ohm")
    xl = _finite(params["xl_ohm"], "xl_ohm")
    z0 = _finite(params.get("z0_ohm", 50.0), "z0_ohm")
    spacing_deg = _finite(params.get("spacing_deg", 45.0), "spacing_deg")
    stub1_deg = _finite(params.get("stub1_deg", 0.0), "stub1_deg")
    stub_type = str(params.get("stub_type", "open"))
    if rl <= 0.0:
        raise ValueError(
            f"stub_tuner: rl_ohm 必须 >0（纯电抗负载 |Γ|=1 调配问题退化，"
            f"显式拒绝），得到 {params['rl_ohm']!r}")
    if z0 <= 0.0:
        raise ValueError(f"stub_tuner: z0_ohm 必须 >0，得到 {params.get('z0_ohm')!r}")
    if not 5.0 <= spacing_deg <= 175.0 or abs(spacing_deg - 90.0) < 1e-12:
        raise ValueError(
            f"stub_tuner: spacing_deg 须 ∈[5,175] 且 ≠90°（tan 奇点；λ/8=45°、"
            f"3λ/8=135° 主用例），得到 {params.get('spacing_deg')!r}")
    if not 0.0 <= stub1_deg < 180.0:
        raise ValueError(
            f"stub_tuner: stub1_deg 须 ∈[0,180)，得到 {params.get('stub1_deg')!r}")
    if stub_type not in ("open", "short"):
        raise ValueError(
            f"stub_tuner: stub_type 须 'open'|'short'，得到 {stub_type!r}")
    return rl, xl, z0, math.tan(math.radians(spacing_deg)), math.radians(stub1_deg), stub_type


# ─── 键 1：双支节并联调配 ────────────────────────────────────────────────────

@register_calculator(
    "stub_tuner_double",
    "双支节并联调配器：归一电纳解析解（Pozar §5.3）——负载导纳 y_L=Z0/Z_L"
    "=g+jb，支节总电纳 u 自由 → 经间距 t=tanβd 变换 g2=g(1+t²)/[(1−tu)²+"
    "t²g²]，g2=1 ⟺ (1−tu)²=g[1+t²(1−g)]，有解 ⟺ g ≤ csc²(βd)=g_max"
    "（λ/8 间距禁区 g>2 经典口径；禁区负载如实返 solvable=False+边界"
    "数据不拒绝）；解 u=[1∓√D]/t 取 |u| 最小支，b_s1=u−b、b_s2=−Im(y2)，"
    "开路/短路支节长度 l/λ（回代 tan/cot 恒等）；ABCD 级联 |Γ_in| 回代"
    "机器精度级（matched 旗标）。stub1_deg 可旋转负载出禁区。锚：g_max"
    "(45°)=2.0、g_max(60°)=4/3 解析钉；可调区随机负载独立 ABCD 回收",
    (("rl_ohm", "float Ω 负载电阻实部（>0；纯电抗负载退化显式拒绝）"),
     ("xl_ohm", "float Ω 负载电抗（有限任意，可负）"),
     ("z0_ohm", "float Ω 传输线特性阻抗（>0，缺省 50）"),
     ("spacing_deg", "float deg 支节间距电长度 βd（∈[5,175] 且 ≠90°，缺省 "
      "45=λ/8；3λ/8=135 同禁区）"),
     ("stub1_deg", "float deg 负载→第一支节线长电长度（∈[0,180)，缺省 0="
      "负载在首支节；可旋转负载出禁区）"),
     ("stub_type", "str 支节终端类型 'open'|'short'（缺省 open）")),
    required=("rl_ohm", "xl_ohm"),
)
def stub_tuner_double(rl_ohm: float, xl_ohm: float, z0_ohm: float = 50.0,
                      spacing_deg: float = 45.0, stub1_deg: float = 0.0,
                      stub_type: str = "open") -> dict[str, Any]:
    rl, xl, z0, t, th1, stype = _validate_common(locals())
    y_load = _normalize_y(rl, xl, z0)
    # 旋转 stub1_deg：负载导纳经线段变到首支节位置
    y_a = _transform_y(y_load, math.tan(th1)) if th1 != 0.0 else y_load
    g_a, b_a = y_a.real, y_a.imag
    g_lim = _g_max(t)
    forbidden = bool(g_a > g_lim)
    sol = _solve_double_from(g_a, b_a, t)
    solvable = sol is not None
    b_s1: float | None = None
    b_s2: float | None = None
    gamma_abs: float | None = None
    matched = False
    z_in: complex | None = None
    if solvable:
        b_s1, y2 = sol
        b_s2 = -y2.imag
        gamma_abs = _abcd_gamma(rl, xl, z0, [
            ("shunt", b_s2), ("line", math.atan(t)),
            ("shunt", b_s1), ("line", th1)])
        matched = bool(gamma_abs < 1e-9)
    d_val = g_a * (1.0 + t * t * (1.0 - g_a))
    if solvable:
        zin_note = (
            "闭式解与 ABCD 回代双路线；gamma_in_abs 应为机器精度级"
            "（测试侧独立 ABCD 重算逐位回收）")
    else:
        zin_note = (
            "负载在禁区（g>csc²(βd)），双支节无解如实报告——增大 stub1_deg "
            "旋转负载（g 沿等 |Γ| 圆变化）或改用 stub_tuner_triple")
    return {
        "solvable": solvable,
        "matched": matched,
        "forbidden": forbidden,
        "g_load_at_stub1": round(g_a, 12),
        "b_load_at_stub1": round(b_a, 12),
        "g_max": round(g_lim, 12),
        "forbidden_margin": round(g_lim - g_a, 12),
        "d_discriminant": round(d_val, 12),
        "b_s1": None if b_s1 is None else round(b_s1, 12),
        "b_s2": None if b_s2 is None else round(b_s2, 12),
        "l1_over_lambda": _stub_len_or_null(b_s1, stype),
        "l2_over_lambda": _stub_len_or_null(b_s2, stype),
        "spacing_deg": round(math.degrees(math.atan(t)), 9),
        "stub1_deg": round(math.degrees(th1), 9),
        "stub_type": stype,
        "z0_ohm": z0,
        "gamma_in_abs": None if gamma_abs is None else round(gamma_abs, 15),
        "note": zin_note,
        "source": _SOURCES["double"],
    }


# ─── 键 2：三支节并联调配 ────────────────────────────────────────────────────

@register_calculator(
    "stub_tuner_triple",
    "三支节并联调配器（等间距级联）：首支节旁路/旋转双路线消除双支节禁区"
    "——①Re[T(y_a,t)] ≤ g_max → b_s1=0 按双支节解后两支节；②否则首支节"
    "取总电纳 u1 使 g2=1（g_a≤g_max，u1=[1∓√D]/t 取 |u1| 最小支）或 "
    "u1=1/t 取可达电导上峰 (1+t²)/(t²g_a)<1<g_max（g_a>g_max），再解后"
    "两支节——任意 r_L>0 负载有解。route 字段如实报告路线（bypass_first/"
    "rotate_first）；ABCD 四节级联 |Γ_in| 回代机器精度级。锚：双支节禁区"
    "负载（如 z_L=10+j10 Ω@50Ω，g=2.5>2）三支节 matched=True；200 随机"
    "负载全匹配",
    (("rl_ohm", "float Ω 负载电阻实部（>0）"),
     ("xl_ohm", "float Ω 负载电抗（有限任意，可负）"),
     ("z0_ohm", "float Ω 传输线特性阻抗（>0，缺省 50）"),
     ("spacing_deg", "float deg 相邻支节间距电长度 βd（∈[5,175] 且 ≠90°，"
      "缺省 45=λ/8）"),
     ("stub1_deg", "float deg 负载→第一支节线长电长度（∈[0,180)，缺省 0）"),
     ("stub_type", "str 支节终端类型 'open'|'short'（缺省 open）")),
    required=("rl_ohm", "xl_ohm"),
)
def stub_tuner_triple(rl_ohm: float, xl_ohm: float, z0_ohm: float = 50.0,
                      spacing_deg: float = 45.0, stub1_deg: float = 0.0,
                      stub_type: str = "open") -> dict[str, Any]:
    rl, xl, z0, t, th1, stype = _validate_common(locals())
    y_load = _normalize_y(rl, xl, z0)
    y0 = _transform_y(y_load, math.tan(th1)) if th1 != 0.0 else y_load
    g_lim = _g_max(t)
    th_sp = math.atan(t)

    y_b = _transform_y(y0, t)
    if y_b.real <= g_lim:
        route = "bypass_first"
        b_s1 = 0.0
        ya = y_b
        sol = _solve_double_from(ya.real, ya.imag, t)
        if sol is None:  # 理论不可达（y_b.real ≤ g_max ⟺ D≥0）；防御
            raise ValueError(
                f"stub_tuner_triple: 旁路路线判据与闭式解不一致（g="
                f"{ya.real!r}），请报告")
    else:
        g_a, b_a = y0.real, y0.imag
        if g_a <= g_lim:
            d_val = g_a * (1.0 + t * t * (1.0 - g_a))
            root = math.sqrt(max(d_val, 0.0))
            u1 = min([(1.0 - root) / t, (1.0 + root) / t], key=abs)
        else:
            u1 = 1.0 / t
        route = "rotate_first"
        b_s1 = u1 - b_a
        ya = _transform_y(complex(g_a, u1), t)
        sol = _solve_double_from(ya.real, ya.imag, t)
        if sol is None:  # 构造保证可解；防御
            raise ValueError(
                f"stub_tuner_triple: 旋转路线后双支节无解（g={ya.real!r}），"
                "请报告")
    b_s2 = sol[0]  # _solve_double_from 首元素=b_s2=u2−Im(ya)（u2=支节处总电纳）
    u2 = b_s2 + ya.imag
    y_after2 = _transform_y(complex(ya.real, u2), t)
    b_s3 = -y_after2.imag
    gamma_abs = _abcd_gamma(rl, xl, z0, [
        ("shunt", b_s3), ("line", th_sp),
        ("shunt", b_s2), ("line", th_sp),
        ("shunt", b_s1), ("line", th1)])
    return {
        "solvable": True,
        "matched": bool(gamma_abs < 1e-9),
        "route": route,
        "g_load_at_stub1": round(y0.real, 12),
        "b_load_at_stub1": round(y0.imag, 12),
        "g_max": round(g_lim, 12),
        "b_s1": round(b_s1, 12),
        "b_s2": round(b_s2, 12),
        "b_s3": round(b_s3, 12),
        "l1_over_lambda": _stub_len_or_null(b_s1, stype),
        "l2_over_lambda": _stub_len_or_null(b_s2, stype),
        "l3_over_lambda": _stub_len_or_null(b_s3, stype),
        "spacing_deg": round(math.degrees(th_sp), 9),
        "stub1_deg": round(math.degrees(th1), 9),
        "stub_type": stype,
        "z0_ohm": z0,
        "gamma_in_abs": round(gamma_abs, 15),
        "note": (
            "三支节无禁区（任意 r_L>0 有解）；bypass_first=首支节旁路由后"
            "两支节完成调配，rotate_first=首支节旋转出双支节禁区；"
            "b_s3=0（开路支节零长/短路支节 λ/4）为合法退化解"),
        "source": _SOURCES["triple"],
    }
