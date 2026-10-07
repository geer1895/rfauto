"""ratrace 环形网（平面 lines + 柱坐标 k 定标 + cylindrical 渲染）（AU-1 自 openems_templates.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass
from . import _nominal_width  # 50Ω 标称线宽单源（XC-W，惰性：取属性才算）
from .registry import _DEFAULT_SUB

# rat-race 环渲染半径引擎常数（pt8 定标 2026-09-11，#198 同类网格伪象）：
# 0.4mm 网格下 1.5 格宽的曲线环带无法带缘对齐，呈慢波/容性栅格化伪象——
# pt7/pt8 实测 hybrid 中心 ≈2.28GHz（六门在带内低端几乎全过、随 f 单调
# 劣化），pt8 全 4×4 矩阵对理想 (θ,θ,3θ,θ) 环做线性幅值最小二乘得环电长
# 缩放 k=1.0975（z=Z_ring/70.7=0.89；Σ 列口径 1.1025、only-k 1.095，
# 三者 ±0.4%），等效 εeff=3.28 超微带物理上限（εr=3.66，HJ 直线 2.72，
# 直线 70.7Ω 模板 branchline/gysel 均达标）→ 判为网格伪象而非几何问题
# （pt8 受控实验已否决结点/弯折加载假设；HFSS 仲裁 2.465GHz 背书
# verdict.k_attribution=MESH_ARTIFACT，runs/ratrace_arbitration）。
# 渲染半径 = 物理半径 / k，物理 R（synthesis 1.5λg=17.344）与 nominal
# 不变、HFSS 通道不受影响（#219③：k 只落 adapter 渲染层）。
_RATRACE_RING_MESH_K = 1.0975   # pt8 归档锚（0.4mm 档历史定标值，仅存证）

# ── k(BASE) 网格档自适应（2026-09-12 HFSS 仲裁批两点标度，ratrace-k 定版）──
# 0.2mm 收敛核验（runs/ratrace_arbitration/openems_convergence.json）：同一
# k=1.0975 下 hybrid 中心 0.4mm→2.354GHz / 0.2mm→2.5225GHz（均 f_center_avg），
# 网格伪象随细化收敛，一阶标度 k_needed(BASE)=k_cur×F0/f_center(BASE) 给
# 两锚 k(0.2mm)=1.0877、k(0.4mm)=1.1654。(k−1) 两点比值 1.886 ≈ 2^0.915，
# 即 (k−1) ∝ BASE^α 幂律（α=ln((k04−1)/(k02−1))/ln2≈0.915），对 (k−1) 做
# 对数空间两点内插；锚外（默认自动档 BASE≈1.14mm 等）夹到最近锚并打
# clamp 旗，禁止外推。柱坐标（build_ratrace_cylindrical）无阶梯化 k=1，
# 为根治首选（#219/#232）；直角坐标换网格档按本函数标度。
_RATRACE_K_BASE_LO_MM = 0.2
_RATRACE_K_BASE_HI_MM = 0.4
_RATRACE_K_ANCHOR_LO = 1.0877   # k(0.2mm)（openems_convergence.json k_needed_0p2mm）
_RATRACE_K_ANCHOR_HI = 1.1654   # k(0.4mm)（openems_convergence.json k_needed_0p4mm）


def ratrace_ring_mesh_k(base_mm: float) -> float:
    """rat-race 渲染半径补偿因子 k，随直角坐标网格档 BASE（mm）标度。

    k(BASE) = 1 + (k02−1)·((k04−1)/(k02−1))^t，t=(BASE−0.2)/0.2∈[0,1]，
    即 (k−1) 对数空间两点幂律内插（α=log2((k04−1)/(k02−1))≈0.915），
    精确复现两锚；BASE∈[0.2,0.4]mm 外夹到最近锚（禁止外推，默认自动档
    BASE≈1.14mm 落此分支）。仅 openEMS 直角坐标渲染层消费（#219③），
    物理 R/synthesis/HFSS 通道不受影响；柱坐标 k=1 不走本函数。
    """
    b = min(max(float(base_mm), _RATRACE_K_BASE_LO_MM), _RATRACE_K_BASE_HI_MM)
    t = (b - _RATRACE_K_BASE_LO_MM) / (_RATRACE_K_BASE_HI_MM - _RATRACE_K_BASE_LO_MM)
    return 1.0 + (_RATRACE_K_ANCHOR_LO - 1.0) * (
        (_RATRACE_K_ANCHOR_HI - 1.0) / (_RATRACE_K_ANCHOR_LO - 1.0)) ** t


def ratrace_ring_mesh_k_clamped(base_mm: float) -> bool:
    """BASE 是否落在定标域 [0.2,0.4]mm 之外（True=渲染脚本用 clamp 锚）。"""
    b = float(base_mm)
    return b < _RATRACE_K_BASE_LO_MM or b > _RATRACE_K_BASE_HI_MM


def _ratrace_lines(p: dict[str, Any]) -> str:
    # rat-race 环形电桥（WP2.3，#208 理论核验轮+pt5 实测定版）：规范角位
    # Σ=0°（右缘水平馈）、out1=60°（径向馈+弯折，出顶缘）、Δ=120°
    # （径向馈+弯折，出顶缘）、out2=300°（径向馈+弯折，出底缘）——
    # out1/out2 分居 Σ 两侧 λ/4（环相位 90/450），Δ 在 λ/2（180），
    # 大弧 3λ/4 扫过 Δ→out2 之间的左下半区。**out2 不得放 geo 180**：
    # 直径对点是环相位 270=两侧各 3λ/4 的"匹配直通"位置（pt5 实测
    # Σ→out2 -0.54dB 直通 + S11 -11dB 的 3λ/4 倒阻抗特征，#208）。
    # 环带与斜馈线逐网格行栅格化（#198 零台阶）。
    # 行为（Y 矩阵严格推导，见 fake _ratrace_sparams docstring）：
    # Σ 均分→out1/out2 各 -3dB 同相；Δ 隔离；out1↔out2 互隔离。
    # 四端口：Σ excite=1（主 run 唯一激励）；out1/Δ/out2 excite=0 仅
    # 探针（激励轮转由适配器层 excite_port 参数化渲染、进程隔离完成
    # ——Run(cleanup=True) 会删激励属性/CSX 的 C++ 对象，禁用进程内
    # 复用包装器的路线，pt3/pt4 实测 #208）。
    # 门：β±2%、|S21|/|S41| -3±1dB 且差 ≤0.5dB、|S31|(Δ) ≤-20dB、
    # |S11|≤-10dB、|S24|≤-15dB。
    # k(BASE)：网格档自适应补偿（ratrace_ring_mesh_k），render_script 注入
    # _base_mm（mm）；域外档写"未定标档 clamp"注释行（禁止外推）
    _base_mm = float(p.get("_base_mm", 0.4))
    _k_ring = ratrace_ring_mesh_k(_base_mm)
    _k_note = (
        f"# 未定标档 clamp：BASE={_base_mm:.4f}mm ∉ [{_RATRACE_K_BASE_LO_MM!r},"
        f"{_RATRACE_K_BASE_HI_MM!r}]mm，夹到最近锚（禁止外推）"
        if ratrace_ring_mesh_k_clamped(_base_mm) else
        f"# 定标域内：BASE={_base_mm:.4f}mm ∈ [{_RATRACE_K_BASE_LO_MM!r},"
        f"{_RATRACE_K_BASE_HI_MM!r}]mm，(k−1) 幂律内插")
    return f'''import numpy as _np

W_R = {p.get("w_ring_mm", 0.6035)!r} * 1e-3
W_F = {p.get("w_feed_mm", _nominal_width.W50_MM)!r} * 1e-3
# 渲染半径 = 物理半径 / k(BASE)（阶梯环慢波伪象补偿随网格档标度：锚
# k(0.2mm)={_RATRACE_K_ANCHOR_LO!r} / k(0.4mm)={_RATRACE_K_ANCHOR_HI!r}，HFSS 仲裁背书）
{_k_note}
R_RING = {p.get("r_ring_mm", 17.344)!r} * 1e-3 / {_k_ring!r}
ratrace = CSX.AddMetal("ratrace")

# 环带栅格化：逐 y 网格行，行中心处求环带 x 区间（内/外半径）
_R_OUT = R_RING + W_R / 2
_R_IN = R_RING - W_R / 2
_yl = np.asarray(mesh.GetLines("y"))
for _k in range(len(_yl) - 1):
    _ya, _yb = _yl[_k], _yl[_k + 1]
    _yc = 0.5 * (_ya + _yb)
    if abs(_yc) > _R_OUT:
        continue
    _xo = np.sqrt(max(_R_OUT ** 2 - _yc ** 2, 0.0))
    _xi = np.sqrt(max(_R_IN ** 2 - _yc ** 2, 0.0))
    if _xi > 1e-9:
        ratrace.AddBox((-_xo, _ya, H_SUB), (-_xi, _yb, H_SUB), priority=10)
        ratrace.AddBox((_xi, _ya, H_SUB), (_xo, _yb, H_SUB), priority=10)
    else:
        ratrace.AddBox((-_xo, _ya, H_SUB), (_xo, _yb, H_SUB), priority=10)

# Σ 馈（右缘水平，geo 0°）
ratrace.AddBox((R_RING, -W_F / 2, H_SUB), (BOARD, W_F / 2, H_SUB), priority=10)

# out1/Δ/out2 径向馈（geo 60°/120°/300°）+ 弯折竖直引出到顶/底缘
# （MSLPort 端口盒必须轴对齐——径向段在弯折处切台阶接竖直段）
_TAN60 = np.tan(np.deg2rad(60.0))
_Y_M = 0.866 * R_RING + 4.0e-3                       # 弯折点高度
_X_T = 0.5 * R_RING + 4.0e-3 / _TAN60                # 竖直引出段中心 x
_Y_J = 0.866 * R_RING                                # 环中心线结点高度
# 径向线栅格化（pt8 迭代，#212 续）：60° 陡线沿 **y 网格行** 栅格化，
# 每行盒 x 范围 = 线心 x_c ± W_F/(2·sin60°)（水平半宽 0.643mm，
# 垂直投影带宽恰为 W_F）。pt7 画法（沿 x 列、垂直半跨 W_F/(2cos60°)
# =1.11mm、下探到 y_c=0.8R）经离线掩模审计（渲染→exec→CSXCAD 原语
# →细网格掩模出图）实测：每结点留下 ≈1.8mm 向内伸入环孔的金属尖刺
# + ≈2.5×2.2mm 结点焊盘，三结点容性加载把 hybrid 中心压到 ≈2.2GHz
# （pt7 @2.25GHz 六门全过、@2.5 随 f 单调劣化）。行栅格化在环中心线
# 处裁剪（含中心线所在行→与环带必然重叠导通），焊盘缩至 ≈1mm²、
# 无尖刺；弯折端含 Y_M 所在行（与竖直段盒正面积重叠，#174 零缝教训）。
_W_HX = W_F / (2.0 * np.sin(np.deg2rad(60.0)))     # 水平半宽 = W_F/√3


def _stub_rows(_sign_y, _sign_x):
    """径向 stub 逐行盒：_sign_y=+1 顶缘/−1 底缘；_sign_x=+1 右/−1 左。"""
    _y_lo, _y_hi = _Y_J, _Y_M
    for _k in range(len(_yl) - 1):
        _ya, _yb = _yl[_k], _yl[_k + 1]
        _ya_s, _yb_s = sorted((_sign_y * _ya, _sign_y * _yb))
        if _yb_s < _y_lo or _ya_s > _y_hi:
            continue
        _yc = min(max(0.5 * (_ya_s + _yb_s), _y_lo), _y_hi)
        _xc = _sign_x * (0.5 * R_RING + (_yc - _Y_J) / _TAN60)
        ratrace.AddBox((_xc - _W_HX, _ya, H_SUB),
                       (_xc + _W_HX, _yb, H_SUB), priority=10)


_stub_rows(+1, +1)   # out1：geo 60°，出顶缘 x=+X_T
_stub_rows(+1, -1)   # Δ：geo 120°（镜像），出顶缘 x=−X_T
_stub_rows(-1, +1)   # out2：geo 300°=−60°，出底缘 x=+X_T（Σ 另一侧 λ/4，
                     # pt5 实测定版：不得放 geo 180 直径对点=3λ/4 匹配直通）
# 竖直引出段（带 2·NEAR 搭接防弯折缝：#174 零宽度金属缝隙教训）
# 顶缘两条：out1（+x）/Δ（−x）；底缘一条：out2（+x）
ratrace.AddBox((_X_T - W_F / 2, _Y_M - 2 * NEAR, H_SUB),
               (_X_T + W_F / 2, BOARD, H_SUB), priority=10)
ratrace.AddBox((-_X_T - W_F / 2, _Y_M - 2 * NEAR, H_SUB),
               (-_X_T + W_F / 2, BOARD, H_SUB), priority=10)
ratrace.AddBox((_X_T - W_F / 2, -BOARD, H_SUB),
               (_X_T + W_F / 2, -_Y_M + 2 * NEAR, H_SUB), priority=10)

_port1 = MSLPort(CSX, port_nr=1, metal_prop=ratrace,
                 start=np.array([BOARD, -W_F / 2, H_SUB]),
                 stop=np.array([R_RING, W_F / 2, 0]),
                 prop_dir="x", exc_dir="z", excite=1 if {p.get("_excite_port", 1)} == 1 else 0,
                 FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - R_RING) / 3, priority=10)
_port2 = MSLPort(CSX, port_nr=2, metal_prop=ratrace,
                 start=np.array([_X_T - W_F / 2, BOARD, H_SUB]),
                 stop=np.array([_X_T + W_F / 2, _Y_M - 2 * NEAR, 0]),
                 prop_dir="y", exc_dir="z", excite=1 if {p.get("_excite_port", 1)} == 2 else 0,
                 FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - _Y_M) / 3, priority=10)
_port3 = MSLPort(CSX, port_nr=3, metal_prop=ratrace,
                 start=np.array([-_X_T - W_F / 2, BOARD, H_SUB]),
                 stop=np.array([-_X_T + W_F / 2, _Y_M - 2 * NEAR, 0]),
                 prop_dir="y", exc_dir="z", excite=1 if {p.get("_excite_port", 1)} == 3 else 0,
                 FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - _Y_M) / 3, priority=10)
_port4 = MSLPort(CSX, port_nr=4, metal_prop=ratrace,
                 start=np.array([_X_T - W_F / 2, -BOARD, H_SUB]),
                 stop=np.array([_X_T + W_F / 2, -_Y_M + 2 * NEAR, 0]),
                 prop_dir="y", exc_dir="z", excite=1 if {p.get("_excite_port", 1)} == 4 else 0,
                 FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - _Y_M) / 3, priority=10)
for _prim in ratrace.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''

# ─── 柱坐标 rat-race（§10.20 补强①；#219 根治路线）─────────────────────────
# 官方口径（铁律 1c；已核对官方例 + openEMS 作者 discussion #196 定谳）：
#   openEMS(CoordSystem=1) + ContinuousStructure(CoordSystem=1)；(r, a, z) 网格；
#   mesh.AddLine('r'/'a'/'z', ...) / SmoothMeshLines(0/1/2, ...)；
#   mesh.a = linspace(-pi, pi, N) 即「全 2π 闭合网格」——作者原话：要闭合柱
#   网格，alpha 须覆盖整个 0..2π（如 -π..+π）；r 域可为环域（r_min>0，官方
#   Coax_Cylindrical_MG 例 rad_i=10>0 即环域）。端口面 r=R_DOM 贴外边界 PML_8。
# 物理动机（#219）：直角网格把物理 R=17.344mm 的环阶梯化成慢波栅格，0.4mm
#   档引擎常数 k=1.0975（HFSS 仲裁背书为网格伪象）。柱坐标下环带 = 常数 r
#   的精确圆环（r 网格线即内外带缘）、径向馈沿径向栅格化，理论无阶梯化
#   → 渲染半径 = 物理半径（k=1，不做任何补偿）。
# 引擎实测限制（v0.37.0-rc1，本次冒烟日志实证）：柱坐标算子**不支持 MUR**
#   （"Mur ABC Extension is not compatible with cylinder-coords!! skipping"）
#   → 所有吸收面必须用 PML；a 向全 2π 闭合网格由引擎自动周期化。
_CYL_RING_AZIMUTH_DEG = (0.0, 60.0, 120.0, 300.0)
# a 网格 = 600 单元/2π（0.6°）；60° 端口方位角 = 100 单元 → 精确入网。
_CYL_ALPHA_CELLS = 600


def _cyl_alpha_lines() -> tuple[int, float]:
    """全 2π a 网格：返回 (线数, 单元角 da)；端点 -π/+π 同址闭合。"""
    n_cells = int(_CYL_ALPHA_CELLS)
    return n_cells + 1, 2.0 * math.pi / n_cells


def _cyl_azimuths_rad() -> tuple[float, ...]:
    """四端口方位角（弧度）归一化到 [-π, π)（300° ≡ -60°，物理同一处）。"""
    out = []
    for deg in _CYL_RING_AZIMUTH_DEG:
        a = math.radians(deg)
        out.append((a + math.pi) % (2.0 * math.pi) - math.pi)
    return tuple(out)


def build_ratrace_cylindrical(
    p: dict[str, Any],
    *,
    r_dom_m: float = 28.0e-3,
    feed_shift_m: float = 1.0e-3,
    meas_shift_m: float = 5.3e-3,
    excite_port: int = 1,
) -> str:
    """柱坐标 rat-race 几何段（环带 + 四条径向馈 + 四个 MSLPort）。

    环带 = 常数 r 圆环（r∈[R−W_R/2, R+W_R/2]，a 全 2π）；四条馈线沿径向
    （a = 0/60/120/300°，r∈[R, R_DOM]），**逐 r 网格单元**栅格化并令 a 半宽
    = W_F/(2·r_c) → 物理等宽（单盒常数 azimuth 会按 R_DOM/R 锥化，改变端口
    参考阻抗）。端口面 = r=R_DOM 外边界（PML_8）；MSLPort 方位半宽取测量面
    处等宽值，使 U/I 探针恰好覆盖全带。返回脚本 body 文本（网格必须由调用
    方先行构建——body 读网格 r 线）。
    """
    w_ring = float(p.get("w_ring_mm", 0.6035)) * 1e-3
    w_feed = float(p.get("w_feed_mm", _nominal_width.W50_MM)) * 1e-3
    r_ring = float(p.get("r_ring_mm", 17.344)) * 1e-3
    _n_alpha, da = _cyl_alpha_lines()
    az = list(_cyl_azimuths_rad())
    ep = max(1, min(4, int(excite_port)))
    r_meas = max(r_dom_m - meas_shift_m, r_ring)
    half_port = w_feed / (2.0 * r_meas)
    ports = []
    for k, a_k in enumerate(az, start=1):
        ports.append(
            f'_port{k} = MSLPort(CSX, port_nr={k}, metal_prop=ratrace,\n'
            f'                 start=np.array([R_DOM, {a_k!r} - _HALF_PORT, H_SUB]),\n'
            f'                 stop=np.array([R_RING, {a_k!r} + _HALF_PORT, 0.0]),\n'
            f'                 prop_dir="r", exc_dir="z", '
            f'excite={1 if ep == k else 0},\n'
            f'                 FeedShift={feed_shift_m!r}, '
            f'MeasPlaneShift={meas_shift_m!r}, priority=10)\n'
        )
    return (
        f'W_R = {w_ring!r}\n'
        f'W_F = {w_feed!r}\n'
        f'R_RING = {r_ring!r}    # 渲染半径 = 物理半径（柱坐标无阶梯化，k=1）\n'
        f'R_DOM = {r_dom_m!r}\n'
        f'_HALF_PORT = {half_port!r}   # 测量面处等宽 a 半宽（探针覆盖全带）\n'
        f'_DA = {da!r}\n'
        f'_AZ = [{", ".join(repr(a) for a in az)}]\n'
        '\n'
        'ratrace = CSX.AddMetal("ratrace")\n'
        '# 环带：常数 r 的精确圆环（全 2π），r 网格线即内外带缘\n'
        'ratrace.AddBox((R_RING - W_R / 2, -np.pi, H_SUB),\n'
        '               (R_RING + W_R / 2, np.pi, H_SUB), priority=10)\n'
        '# 四条径向馈线：逐 r 网格单元等物理宽段（a 半宽 = W_F/(2·r_c)）\n'
        '_RL = np.asarray(mesh.GetLines("r"))\n'
        'for _ak in _AZ:\n'
        '    for _i in range(len(_RL) - 1):\n'
        '        _ra = max(_RL[_i], R_RING)\n'
        '        _rb = min(_RL[_i + 1], R_DOM)\n'
        '        if _rb - _ra <= 1e-12:\n'
        '            continue\n'
        '        _h = W_F / (_ra + _rb)\n'
        '        ratrace.AddBox((_ra, _ak - _h, H_SUB),\n'
        '                       (_rb, _ak + _h, H_SUB), priority=10)\n'
        + "".join(ports)
        + 'for _prim in ratrace.GetAllPrimitives():\n'
        '    if _prim.GetPriority() < 10:\n'
        '        _prim.SetPriority(10)\n'
    )


def render_ratrace_cylindrical(
    params: dict[str, Any],
    freq_range_ghz: tuple[float, float],
    mesh_resolution_mm: float = 0.0,
    substrate: dict[str, Any] | None = None,
    excite_port: int = 1,
    r_in_mm: float = 12.0,
    r_dom_mm: float = 28.0,
) -> str:
    """渲染柱坐标 rat-race 全脚本（几何/网格/四 MSLPort/单激励列 CSV）。

    与 render_script("ratrace") 同构（9 列 CSV，整 4×4 由 excite_port
    轮转装配），但坐标系为柱坐标（CoordSystem=1）、环半径用物理值（k=1）。
    """
    params = dict(params)
    substrate = substrate or _DEFAULT_SUB
    f0 = (freq_range_ghz[0] + freq_range_ghz[1]) / 2 * 1e9
    fc = max((freq_range_ghz[1] - freq_range_ghz[0]) / 2 * 1e9, 1e6)
    er = float(substrate["er"])
    h_m = float(substrate["h_mm"]) * 1e-3
    tan_d = float(substrate.get("tan_d", 1e-3))
    f_max = f0 + fc
    base_m = (3e8 / (f_max * (er ** 0.5)) / 50 if not mesh_resolution_mm
              else float(mesh_resolution_mm) * 1e-3)
    near_m = base_m / 4
    r_in = float(r_in_mm) * 1e-3
    r_dom = float(r_dom_mm) * 1e-3
    w_ring = float(params.get("w_ring_mm", 0.6035)) * 1e-3
    r_ring = float(params.get("r_ring_mm", 17.344)) * 1e-3
    feed_shift = min(10.0 * near_m, 0.3 * (r_dom - r_ring))
    meas_shift = 0.5 * (r_dom - r_ring)
    n_alpha, _da = _cyl_alpha_lines()
    ep = max(1, min(4, int(excite_port)))
    body = build_ratrace_cylindrical(
        params, r_dom_m=r_dom, feed_shift_m=feed_shift,
        meas_shift_m=meas_shift, excite_port=ep)
    return f'''#!/usr/env/python3
"""openEMS cylindrical rat-race script (rfauto auto-generated, CoordSystem=1).

柱坐标 (r, a, z)：环带 = 常数 r 精确圆环、径向馈 = 常数 azimuth 径向段，
渲染半径 = 物理半径（k=1，无网格伪象补偿，#219 根治路线）。
"""
import csv
import os

# CSXCAD/openEMS 扩展模块依赖 DLL 不在 Python 3.8+ 的 PATH 搜索里
_OE_BIN = os.environ.get("RFAUTO_OPENEMS_BIN", r"E:\\openEMS\\install\\bin")
if os.path.isdir(_OE_BIN):
    os.environ["PATH"] = _OE_BIN + os.pathsep + os.environ.get("PATH", "")
    os.add_dll_directory(_OE_BIN)

import numpy as np
from CSXCAD import ContinuousStructure
from openEMS import openEMS
from openEMS.ports import MSLPort

F0 = {f0!r}
FC = {fc!r}
ER = {er!r}
H_SUB = {h_m!r}
TAND = {tan_d!r}
BASE = {base_m!r}
NEAR = {near_m!r}
AIR_TOP = 5e-3
R_IN = {r_in!r}
R_DOM = {r_dom!r}
CSV_NAME = "sparams.csv"
SIM_PATH = os.path.abspath("fdtd")
CSV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), CSV_NAME)

# ── 柱坐标 FDTD（官方 2D Cylindrical Wave / Bent Patch 口径）──
CSX = ContinuousStructure(CoordSystem=1)
FDTD = openEMS(NrTS=100000, CoordSystem=1)
FDTD.SetCSX(CSX)
FDTD.SetGaussExcite(F0, FC)
# BC 序 = [r-, r+, a-, a+, z-, z+]：a 向全 2π 闭合（作者 #196 定谳，a 边界
# 不参与）；**柱坐标算子不支持 MUR**（引擎实测 "Mur ABC Extension is not
# compatible with cylinder-coords!! skipping" → MUR 静默退化为 PEC）——所有
# 吸收面一律 PML_8：r+ 端口外边界、z+ 顶空气隙；r- 内边界 PEC（环内接地
# 基板，场已衰减）；z- 地面 PEC
FDTD.SetBoundaryCond(["PEC", "PML_8", "PEC", "PEC", "PEC", "PML_8"])

mesh = CSX.GetGrid()
# r 网格：内域 R_IN → 外边界 R_DOM；环带两缘精确入网（常数 r 圆环）
mesh.AddLine("r", [R_IN, {r_ring - w_ring / 2!r}, {r_ring!r},
                   {r_ring + w_ring / 2!r}, R_DOM])
mesh.SmoothMeshLines("r", BASE)
# a 网格：全 2π 均匀闭合（端点 -π/+π 同址）；不 Smooth 以保 60° 对齐
mesh.AddLine("a", np.linspace(-np.pi, np.pi, {n_alpha}))
# z 网格：基板 4 层（官方 substrate_cells=4）+ 顶空气隙
mesh.AddLine("z", np.linspace(0.0, H_SUB, 5))
mesh.AddLine("z", H_SUB + AIR_TOP)
mesh.SmoothMeshLines("z", BASE)
# 网格最小间距守卫（#152）：去重 1µm 内近重合线，防 CFL 时间步塌缩
for _ax in ("r", "a", "z"):
    _ls = np.asarray(mesh.GetLines(_ax), dtype=float)
    _keep = [_ls[0]]
    for _v in _ls[1:]:
        if _v - _keep[-1] > 1e-6:
            _keep.append(_v)
    mesh.SetLines(_ax, np.array(_keep))

sub = CSX.AddMaterial("substrate", epsilon=ER,
                      kappa=TAND * 2 * np.pi * F0 * 8.854187817e-12 * ER)
sub.AddBox((R_IN, -np.pi, 0), (R_DOM, np.pi, H_SUB), priority=0)
{body}

FDTD.Run(SIM_PATH, verbose=0, disable_dumps=True, cleanup=True)

f = np.linspace(F0 - FC, F0 + FC, 401)
_port1.CalcPort(SIM_PATH, f, ref_impedance=50)
_port2.CalcPort(SIM_PATH, f, ref_impedance=50)
_port3.CalcPort(SIM_PATH, f, ref_impedance=50)
_port4.CalcPort(SIM_PATH, f, ref_impedance=50)
_SREF = _port{ep}.uf_inc
S11 = _port1.uf_ref / _SREF
S21 = _port2.uf_ref / _SREF
S31 = _port3.uf_ref / _SREF
S41 = _port4.uf_ref / _SREF
with open(CSV_PATH, "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["freq_hz", "re_S11", "im_S11", "re_S21", "im_S21",
                "re_S31", "im_S31", "re_S41", "im_S41"])
    for _i, _fi in enumerate(f):
        w.writerow([_fi, S11[_i].real, S11[_i].imag, S21[_i].real,
                    S21[_i].imag, S31[_i].real, S31[_i].imag,
                    S41[_i].real, S41[_i].imag])
print("rfauto openEMS cylindrical simulation done")
'''
