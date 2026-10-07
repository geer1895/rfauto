"""超表面族（ms_patch/ms_cross/ms_jcross/ms_array_NxN）（AU-1 自 openems_templates.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass
from .grid import _fd_nrts_defaults, _fd_nrts_override_block
from .registry import _DEFAULT_SUB, TEMPLATE_META, TEMPLATE_NOMINAL

# ─── §MS_METASURFACE 超表面/FSS 族（2026-09-24 df6 DP-10，文末注册块）─────────
# 规格与判据：规格深案 §DP-10 +
# runs/df6_dp10ms/criteria.md（预声明冻结）。离线内核=core/metasurface_lut.py
# （名义尺寸闭式单源 #252/#1c：本段只消费不重复实现）。
#
# 波导模拟器技巧（法向入射≡无限阵@θ=0，官方 Parallel Plate Waveguide 教程
# 口径）：
# - 域=单胞方形截面：x 对壁 PEC（E∥x 为法向场，兼容）、y 对壁 PMC
#   （E∥x 为切向场，兼容）——TEM 平面波，E∥x 极化前提（y 极化互换 PEC/PMC）；
# - 激励/读出（2026-10-01 ge5 修复，runs/ge5_msjcross/audit.md §E）：
#   三单元族同修：ms_patch/cross/jcross 全部=soft plane 激励（exc_type=0，
#   官方 PPW 教程同源）+ 每侧双 E 探针对精确 F/B 分解（_wg_readout_block
#   单源垫片；ms_patch 反射口径用 _WgProbePairRefl 对调 uf）——原全口径
#   电阻片=测量面并联 Z0 负载，能量预算破损+相位 Möbius 像，已废；
# - ms_patch（反射型）：z 底=地面 PEC 边界，片在空气侧，|S11|≈1 的相位
#   即反射阵 LUT（幅相分离口径：幅度非 ≈1 线性=读出判废信号；探针面去嵌
#   常数项不进扫 px 差分）；
# - ms_cross/ms_jcross（透射型 FSS）：屏在基板顶，读出面在屏两侧空气区，
#   S21=传输（带阻/带通），底边界 MUR。
# 极化前提双处注明（meta extraction + 渲染脚本注释）；斜入射与无限阵
# 仲裁走 HFSS Floquet（J4，真机轨）。
MS_UNIT_TEMPLATES: tuple[str, ...] = (
    "ms_patch", "ms_cross", "ms_jcross", "ms_ring_patch")
METASURFACE_TEMPLATES: tuple[str, ...] = (*MS_UNIT_TEMPLATES, "ms_array_NxN")
#: 无端口模板（软平面照明散射体，audit ②/③ 独立分支）：
PORTLESS_TEMPLATES: tuple[str, ...] = ("ms_array_NxN",)
#: 波导模拟器对壁 BC（x0,x1,y0,y1）——unit 三件（E∥x 前提，见上）
_TEMPLATE_WALL_BC: dict[str, tuple[str, str, str, str]] = {
    "ms_patch": ("PEC", "PEC", "PMC", "PMC"),
    "ms_cross": ("PEC", "PEC", "PMC", "PMC"),
    "ms_jcross": ("PEC", "PEC", "PMC", "PMC"),
    "ms_ring_patch": ("PEC", "PEC", "PMC", "PMC"),
}


def _ms_gap_midlines(lo: float, hi: float, n: int = 3) -> list[float]:
    """1-D 缝隙 [lo,hi] 的 n+1 等分内部点（#311 缝中点精确入网口径：
    SmoothMesh 不细分 <NEAR 区间——显式 AddLine 恒保留）。"""
    if hi <= lo:
        raise ValueError(f"缝隙区间非法 [{lo}, {hi}]")
    return [lo + (hi - lo) * k / (n + 1) for k in range(1, n + 1)]


#: CalcPort 兼容垫片源码（ms_cross/ms_jcross 波导模拟器读出共享单源；
#: 从首版 jcross 修复批（2cc744d）内联字节原样提取——两模板渲染输出
#: 逐字节同源，改此处即同改两模板渲染字面，钉测试/字节对照照 gate）。
_WG_PROBE_PAIR_CLASS_SRC = '''
class _WgProbePair(object):
    """CalcPort 兼容垫片：同侧双 E 探针对 + 精确 β 方向求解（TEM 空气区）。

    E 探针=全口径 x 向线积分（weight=-1，LumpedPort ut 同构造）；探针自由
    悬浮不扰动场。F/B 分解：E_a=F+B·e1、E_b=F·p+B/p（p=e^(-jβΔz)）——
    判读口径 runs/ge5_msjcross/criteria.md；能量门=|S11|²+|S21|²∈[0.90,1.02]
    （单模子带 f≤0.95·c/(2b)，带顶多模污染区只报告）。
    """

    def __init__(self, dom_x, za, zb, pair, forward_as_ref=False):
        self._a = 2 * dom_x
        self._za = za
        self._zb = zb
        self._pair = pair
        self._fwd_ref = forward_as_ref
        self.start = np.array([-dom_x, 0.0, za])
        self.stop = np.array([dom_x, 0.0, zb])
        self.uf_inc = None
        self.uf_ref = None

    def CalcPort(self, sim_path, freq, ref_impedance=None,
                 ref_plane_shift=None, signal_type="pulse"):
        def _rd(_p):
            _ls = open(_p).read().splitlines()
            return np.array([[float(x) for x in _l.split()] for _l in _ls
                             if not _l.startswith("%") and _l.strip()])
        _t = _rd(os.path.join(sim_path, "u" + self._pair + "a"))[:, 0]
        _dt = _t[1] - _t[0]
        _Ea_t = -_rd(os.path.join(sim_path, "u" + self._pair + "a"))[:, 1] / self._a
        _Eb_t = -_rd(os.path.join(sim_path, "u" + self._pair + "b"))[:, 1] / self._a
        _dz = self._zb - self._za
        _F = np.zeros(len(freq), complex)
        _B = np.zeros(len(freq), complex)
        for _j, _fq in enumerate(freq):
            _Ea = np.sum(_Ea_t * np.exp(-2j * np.pi * _fq * _t)) * _dt
            _Eb = np.sum(_Eb_t * np.exp(-2j * np.pi * _fq * _t)) * _dt
            _beta = 2 * np.pi * _fq / 299792458.0
            _den = np.exp(-1j * _beta * _dz) - np.exp(1j * _beta * _dz)
            _f = (_Eb - _Ea * np.exp(1j * _beta * _dz)) / _den
            _F[_j] = _f
            _B[_j] = _Ea - _f
        if self._fwd_ref:
            # port2 垫片：footer S21=_port2.uf_ref/_port1.uf_inc——uf_ref 载
            # 前行波 F2（对 port2 而言=到达波口径的物理透射）
            self.uf_inc = _F
            self.uf_ref = _F
        else:
            self.uf_inc = _F
            self.uf_ref = _B
'''


def _wg_readout_block(lay: dict[str, Any], reflection: bool = False) -> str:
    """波导模拟器读出段（soft plane 激励+4 E 线探针+垫片装配）单源。

    ms_cross/ms_jcross 共享（ge5 修法，runs/ge5_msjcross/audit.md §E/I：
    全口径 LumpedPort 电阻片=测量面并联 Z0 负载，能量预算破损）。lay 取
    z_src/z_1a/z_1b/z_2a/z_2b（米，ms_unit_layout 单源）。

    reflection=True（2026-10-01 ge5 ms_patch 读出修复移植）：单探针对反射
    口径——lay 只取 z_src/z_1a/z_1b；_WgProbePairRefl 子类在 CalcPort 后
    对调 uf（基类 uf_inc=+z 行波/uf_ref=−z 行波，反射单元 DUT 在探针下方，
    入射=−z 照明波、反射=+z 回波）→ footer S11=uf_ref/uf_inc=Γ；
    _port2=_port1 别名（单端口 fallback 契约，S21 列≡S11）。
    reflection=False 输出与既有两模板渲染逐字节相同（跨模板字节钉保零破损）。
    """
    if reflection:
        return f'''# ── soft plane 激励（官方 PPW 教程 exc_type=0 口径；双向透明）──
Z_SRC = {lay["z_src"]!r}   # 激励面（探针对上方 λ0/16）
Z_1A = {lay["z_1a"]!r}   # 探针对近端（soft plane 侧）
Z_1B = {lay["z_1b"]!r}   # 探针对远端（贴片侧，对内距 λ0/16）
_exc_wg = CSX.AddExcitation("wg_exc", exc_type=0,
                            exc_val=np.array([1.0, 0.0, 0.0]))
_exc_wg.AddBox((-DOM_X, -DOM_Y, Z_SRC), (DOM_X, DOM_Y, Z_SRC), priority=5)
for _nm, _zp in (("1a", Z_1A), ("1b", Z_1B)):
    _u = CSX.AddProbe("u" + _nm, p_type=0, weight=-1)
    _u.AddBox(np.array([-DOM_X, 0.0, _zp]), np.array([DOM_X, 0.0, _zp]))

{_WG_PROBE_PAIR_CLASS_SRC}
class _WgProbePairRefl(_WgProbePair):
    """反射口径垫片（ms_patch 读出修复专用）：基类 uf_inc=+z 行波、
    uf_ref=−z 行波——反射单元 DUT 在探针对下方，入射=−z 照明波、
    反射=+z 回波，CalcPort 后对调使 S11=uf_ref/uf_inc=Γ。"""

    def CalcPort(self, sim_path, freq, ref_impedance=None,
                 ref_plane_shift=None, signal_type="pulse"):
        _WgProbePair.CalcPort(self, sim_path, freq, ref_impedance,
                              ref_plane_shift, signal_type)
        self.uf_inc, self.uf_ref = self.uf_ref, self.uf_inc

_port1 = _WgProbePairRefl(DOM_X, Z_1A, Z_1B, "1")
_port2 = _port1   # 单端口反射模板：footer 的 single-port fallback 口径（S21 列≡S11）
'''
    return f'''# ── soft plane 激励（官方 PPW 教程 exc_type=0 口径；双向透明）──
Z_SRC = {lay["z_src"]!r}   # 激励面（距 z 底 MUR λ0/16，#253 内缩口径）
Z_1A = {lay["z_1a"]!r}   # 下探针对近端（屏下游侧）
Z_1B = {lay["z_1b"]!r}   # 下探针对远端（对内距 λ0/16）
Z_2A = {lay["z_2a"]!r}   # 上探针对近端（屏上游侧）
Z_2B = {lay["z_2b"]!r}   # 上探针对远端
_exc_wg = CSX.AddExcitation("wg_exc", exc_type=0,
                            exc_val=np.array([1.0, 0.0, 0.0]))
_exc_wg.AddBox((-DOM_X, -DOM_Y, Z_SRC), (DOM_X, DOM_Y, Z_SRC), priority=5)
for _nm, _zp in (("1a", Z_1A), ("1b", Z_1B), ("2a", Z_2A), ("2b", Z_2B)):
    _u = CSX.AddProbe("u" + _nm, p_type=0, weight=-1)
    _u.AddBox(np.array([-DOM_X, 0.0, _zp]), np.array([DOM_X, 0.0, _zp]))

{_WG_PROBE_PAIR_CLASS_SRC}
_port1 = _WgProbePair(DOM_X, Z_1A, Z_1B, "1")
_port2 = _WgProbePair(DOM_X, Z_2A, Z_2B, "2", forward_as_ref=True)
'''

def _ms_refl_z(h_m: float, lam0_m: float) -> dict[str, Any]:
    """反射单元（ms_patch/ms_ring_patch）读出面 z 单源（2026-10-01 ge5 段①）。

    soft plane 激励 + 双 E 探针对（对内距 λ0/16，|sin βΔz|=sin(π/8)=0.38
    条件数同 jcross 档），全部 λ0 分数面——z 值与单胞面内几何完全解耦。
    """
    z_feed = h_m + lam0_m / 4     # DUT 参考面（贴片上方 λ0/4，去嵌/UI 口径保留）
    z_1a = z_feed + lam0_m / 32   # 上探针（近 soft plane）
    z_1b = z_1a - lam0_m / 16     # 下探针（对内距 λ0/16，跨 z_feed 对称）
    z_src = z_1a + lam0_m / 16    # soft plane 激励面
    z_top = z_src + lam0_m / 8    # 平面上方 λ0/8 余量再 MUR
    return {"z_feed": z_feed, "z_1a": z_1a, "z_1b": z_1b,
            "z_src": z_src, "z_top": z_top,
            "z_lines": [z_1b, z_1a, z_src, z_top]}


def ms_unit_layout(template: str, params: dict[str, Any],
                   freq_range_ghz: tuple[float, float], base_m: float,
                   h_m: float) -> dict[str, Any]:
    """单元三件几何/端口/域单源（siw_layout 同款；米制；渲染期守卫在本层）。

    返回 dict：period/屏几何/dom_x/dom_y/z 各面/近场线 x/y（米，字面注入）/
    min_gap_m/r_port（η0·a/b，方胞=η0）。守卫违反抛 ValueError（#266 口径：
    不许静默粗网格）。
    """
    from rfauto.core.metasurface_lut import ETA0_OHM

    # 激励面内缩守卫（#253 单源 raise 型，R4-2；只校验不改几何——λ0 分数面
    # 现状充裕，本门防未来接入照抄缺省静默内缩不足）
    from .inset_guard import assert_excitation_inset

    near_m = base_m / float(params.get("_near_ratio", 4) or 4)
    period = float(params.get("period_mm", 14.9896)) * 1e-3
    if period <= 0:
        raise ValueError("period_mm 须 >0")
    lam0_m = 299792458.0 / ((freq_range_ghz[0] + freq_range_ghz[1]) / 2 * 1e9)

    def _gap_guard(min_gap_m: float, what: str) -> None:
        if min_gap_m < 3 * near_m:
            raise ValueError(
                f"{template}: {what} {min_gap_m * 1e3:.4f}mm < 3·NEAR"
                f"({3 * near_m * 1e3:.4f}mm，#266 守卫)——加密网格或放宽几何")

    def _gap_mid(gaps: list[tuple[float, float]]) -> list[float]:
        out: list[float] = []
        for lo, hi in gaps:
            out.extend(_ms_gap_midlines(lo, hi, 3))
        return out

    if template == "ms_patch":
        px = float(params.get("px_mm", 8.5406)) * 1e-3
        py = float(params.get("py_mm", 8.5406)) * 1e-3
        if not 0 < px < period or not 0 < py < period:
            raise ValueError(
                f"ms_patch: 贴片须在胞内 0<px,py<period（{px},{py} vs {period}）")
        gap_x = (period - px) / 2
        gap_y = (period - py) / 2
        _gap_guard(min(gap_x, gap_y), "胞缘缝")
        # 读出探针面（2026-10-01 ge5 ms_patch 读出修复，jcross/cross 同族移植，
        # runs/ge5_msfam/criteria.md §0/§2）：soft plane 激励面 + 双 E 探针对
        # ——反射口径 S11=Γ（入射=−z 照明波/反射=+z 回波，垫片子类对调 uf）。
        # 全部为自由悬浮无源面，域内零电阻片（_ms_refl_z 单源）。
        z = _ms_refl_z(h_m, lam0_m)
        # 反射族最近吸收边界=顶 MUR（底=PEC 地）：激励面→顶 MUR 内缩=λ0/8
        assert_excitation_inset(z["z_top"] - z["z_src"], base_m,
                                label=f"{template} 激励面→顶 MUR 内缩")
        near_x = [-px / 2, px / 2]
        near_y = [-py / 2, py / 2]
        near_x += _gap_mid([(-period / 2, -px / 2), (px / 2, period / 2)])
        near_y += _gap_mid([(-period / 2, -py / 2), (py / 2, period / 2)])
        return {"period": period, "dom_x": period / 2, "dom_y": period / 2,
                "z_lines": z["z_lines"], "z_feed": z["z_feed"],
                "z_src": z["z_src"], "z_1a": z["z_1a"], "z_1b": z["z_1b"],
                "z_top": z["z_top"], "near_x": near_x, "near_y": near_y,
                "min_gap_m": min(gap_x, gap_y),
                "r_port": ETA0_OHM * period / period,
                "px": px, "py": py}

    if template == "ms_ring_patch":
        # 双谐振方环+内贴片（DP-10 §1c 预登记 fallback，ge5 J2 战役段③注册）：
        # 环几何=core 闭式单源 ms_ring_patch_dims_mm（void=0.4λ0、ring_w=λg/40、
        # ring_outer=void+2·ring_w）；内贴片 px=LUT 扫描变量（名义=贴片谐振
        # 不动点闭式）。读出=ms_patch 同族反射口径（_ms_refl_z 单源）。
        from rfauto.core.metasurface_lut import ms_patch_resonant_len_mm, ms_ring_patch_dims_mm

        er = float(params.get("er", 3.66))   # 缺省=族 nominal（调用方经
        # TEMPLATE_NOMINAL 携带；空 params 直调仅测试路径）
        px = float(params.get(
            "patch_px_mm",
            round(ms_patch_resonant_len_mm(10.0, er, h_m * 1e3), 4))) * 1e-3
        dims = ms_ring_patch_dims_mm(
            (freq_range_ghz[0] + freq_range_ghz[1]) / 2, er)
        void = dims["void_mm"] * 1e-3          # 空腔全边长（米）
        ring_w = dims["ring_w_mm"] * 1e-3
        ring_o = dims["ring_outer_mm"] * 1e-3  # 环外边全边长（米）
        half_v = void / 2                      # 空腔半边=环内缘（半坐标）
        half_o = ring_o / 2                    # 环外缘（半坐标）
        if not 0 < px < void:
            raise ValueError(
                f"ms_ring_patch: 内贴片须在环空腔内 0<px<void"
                f"（{px * 1e3:.4f} vs {void * 1e3:.4f}mm）")
        gap_patch = half_v - px / 2        # 贴片缘→环内缘缝
        gap_edge = period / 2 - half_o     # 环外缘→胞缘缝
        _gap_guard(min(gap_patch, gap_edge), "环-贴片/环-胞缝")
        z = _ms_refl_z(h_m, lam0_m)
        # 反射族最近吸收边界=顶 MUR：激励面→顶 MUR 内缩=λ0/8（#253 守卫）
        assert_excitation_inset(z["z_top"] - z["z_src"], base_m,
                                label=f"{template} 激励面→顶 MUR 内缩")
        near_x = [-px / 2, px / 2, -half_o, half_o, -half_v, half_v]
        near_y = [-px / 2, px / 2, -half_o, half_o, -half_v, half_v]
        near_x += _gap_mid([(px / 2, half_v), (-half_v, -px / 2),
                            (half_o, period / 2), (-period / 2, -half_o)])
        near_y += _gap_mid([(px / 2, half_v), (-half_v, -px / 2),
                            (half_o, period / 2), (-period / 2, -half_o)])
        return {"period": period, "dom_x": period / 2, "dom_y": period / 2,
                "z_lines": z["z_lines"], "z_feed": z["z_feed"],
                "z_src": z["z_src"], "z_1a": z["z_1a"], "z_1b": z["z_1b"],
                "z_top": z["z_top"], "near_x": near_x, "near_y": near_y,
                "min_gap_m": min(gap_patch, gap_edge),
                "r_port": ETA0_OHM * period / period,
                "px": px, "void": void, "ring_w": ring_w,
                "ring_outer": ring_o}

    if template == "ms_cross":
        period = float(params.get("period_mm", 11.9917)) * 1e-3
        arm = float(params.get("arm_len_mm", 4.91)) * 1e-3
        arm_w = float(params.get("arm_w_mm", 0.982)) * 1e-3
        if not 0 < 2 * arm < period or not 0 < arm_w < 2 * arm:
            raise ValueError("ms_cross: 臂须在胞内且宽 < 全跨")
        tip_gap = period - 2 * arm
        _gap_guard(tip_gap, "邻臂尖缝")
        g_air = lam0_m / 4
        z_feed_lo = -g_air           # 下游空气区参考面（几何/UI 口径保留）
        z_feed_hi = h_m + g_air      # 上游空气区参考面（几何/UI 口径保留）
        z_bot = z_feed_lo - lam0_m / 8
        z_top = z_feed_hi + lam0_m / 8
        # 读出探针面（2026-10-01 ge5 同族修复，runs/ge5_msfam/criteria.md
        # §0；与 ms_jcross 修复批同式）：soft plane 激励面 + 每侧双 E 探针
        # 对（对内距 λ0/16）。全部为自由悬浮无源面，域内零电阻片。
        z_src = z_bot + lam0_m / 16          # 激励面距 z 底 MUR λ0/16（≥2·BASE）
        # 传输族最近吸收边界=z 底 MUR：内缩=λ0/16（#253 守卫，注释口径升 raise）
        assert_excitation_inset(z_src - z_bot, base_m,
                                label=f"{template} 激励面→底 MUR 内缩")
        z_1a = z_feed_lo + lam0_m / 32       # 下对近端（屏下游侧空气区）
        z_1b = z_1a - lam0_m / 16            # 下对远端
        z_2b = z_feed_hi - lam0_m / 32       # 上对远端（屏上游侧空气区）
        z_2a = z_2b - lam0_m / 16            # 上对近端
        near_x = [-arm, arm, -arm_w / 2, arm_w / 2]
        near_y = [-arm, arm, -arm_w / 2, arm_w / 2]
        near_x += _gap_mid([(arm, period / 2), (-period / 2, -arm)])
        near_y += _gap_mid([(arm, period / 2), (-period / 2, -arm)])
        return {"period": period, "dom_x": period / 2, "dom_y": period / 2,
                "z_lines": [z_bot, z_src, z_1b, z_1a, h_m, z_2a, z_2b, z_top],
                "z_feed_lo": z_feed_lo, "z_feed_hi": z_feed_hi,
                "z_src": z_src, "z_1a": z_1a, "z_1b": z_1b,
                "z_2a": z_2a, "z_2b": z_2b,
                "z_bot": z_bot, "z_top": z_top, "near_x": near_x,
                "near_y": near_y, "min_gap_m": tip_gap,
                "r_port": ETA0_OHM * period / period,
                "arm": arm, "arm_w": arm_w}

    if template == "ms_jcross":
        period = float(params.get("period_mm", 11.9917)) * 1e-3
        slot_len = float(params.get("slot_len_mm", 4.91)) * 1e-3
        slot_w = float(params.get("slot_w_mm", 0.491)) * 1e-3
        stub_len = float(params.get("stub_len_mm", 2.455)) * 1e-3
        if not 0 < slot_len < period or not 0 < slot_w < slot_len:
            raise ValueError("ms_jcross: 缝尺寸非法")
        stub_tip = slot_w / 2 + stub_len
        edge_gap = period / 2 - slot_len / 2
        tip_gap_y = period / 2 - stub_tip
        _gap_guard(min(edge_gap, tip_gap_y), "屏缝")
        g_air = lam0_m / 4
        z_feed_lo = -g_air           # 屏下游空气区参考面（几何/UI 口径保留）
        z_feed_hi = h_m + g_air      # 屏上游空气区参考面（几何/UI 口径保留）
        z_bot = z_feed_lo - lam0_m / 8
        z_top = z_feed_hi + lam0_m / 8
        # 读出探针面（2026-10-01 ge5 修复，runs/ge5_msjcross/audit.md §G）：
        # soft plane 激励面 + 每侧双 E 探针对（对内距 λ0/16，方向求解条件数
        # 全带 |sin βΔz|≥0.29）。全部为自由悬浮无源面，域内零电阻片。
        z_src = z_bot + lam0_m / 16          # 激励面距 z 底 MUR λ0/16（≥2·BASE）
        # 传输族最近吸收边界=z 底 MUR：内缩=λ0/16（#253 守卫，注释口径升 raise）
        assert_excitation_inset(z_src - z_bot, base_m,
                                label=f"{template} 激励面→底 MUR 内缩")
        z_1a = z_feed_lo + lam0_m / 32       # 下对近端（屏下游侧空气区）
        z_1b = z_1a - lam0_m / 16            # 下对远端
        z_2b = z_feed_hi - lam0_m / 32       # 上对远端（屏上游侧空气区）
        z_2a = z_2b - lam0_m / 16            # 上对近端
        # 缝缘近场线（ge5 2026-10-01 方向修复：屏 90° 旋转——主缝沿 y、端枝
        # 沿 x。F3 实验（runs/ge5_msjcross/criteria.md §7）：x 缝+E∥x 是槽缝
        # FSS 非耦合极化（全带无峰）；y 缝+E∥x（缝垂直驱动）峰现形且与载板
        # PSSFSS 吻合。参数名义值旋转不变。近场线 x/y 轴互换同源。
        near_x = [-slot_w / 2, slot_w / 2,
                  -(slot_w / 2 + stub_len), slot_w / 2 + stub_len]
        near_y = [-slot_len / 2, slot_len / 2,
                  -slot_len / 2 + slot_w, slot_len / 2 - slot_w]
        near_x += _gap_mid([(slot_w / 2 + stub_len, period / 2),
                            (-period / 2, -(slot_w / 2 + stub_len))])
        near_y += _gap_mid([(slot_len / 2, period / 2),
                            (-period / 2, -slot_len / 2)])
        return {"period": period, "dom_x": period / 2, "dom_y": period / 2,
                "z_lines": [z_bot, z_src, z_1b, z_1a, h_m, z_2a, z_2b, z_top],
                "z_feed_lo": z_feed_lo, "z_feed_hi": z_feed_hi,
                "z_src": z_src, "z_1a": z_1a, "z_1b": z_1b,
                "z_2a": z_2a, "z_2b": z_2b,
                "z_bot": z_bot, "z_top": z_top, "near_x": near_x,
                "near_y": near_y, "min_gap_m": min(edge_gap, tip_gap_y),
                "r_port": ETA0_OHM * period / period,
                "slot_len": slot_len, "slot_w": slot_w, "stub_len": stub_len}

    raise ValueError(f"ms_unit_layout: 未知单元模板 {template!r}")


def _ms_patch_lines(p: dict[str, Any]) -> str:
    """反射阵方贴片单元（DP-10）：接地基板+零厚方贴片，soft plane+探针对反射读出。

    读出（2026-10-01 ge5 ms_patch 读出修复，runs/ge5_msjcross/audit.md §D/E
    定性：原全口径 LumpedPort 电阻片=测量面并联 Z0 负载（能量预算破损），
    反射相位为片负载 Möbius 像——jcross/cross 修法
    同族移植：soft plane 激励 + 双 E 探针对（_WgProbePairRefl 对调 uf）。
    """
    lay = p["_ms_layout"]
    return f'''# ms_patch 波导模拟器单元（E∥x 极化前提；y 极化需互换 PEC/PMC 对壁）
PX = {lay["px"]!r}
PY = {lay["py"]!r}
patch = CSX.AddMetal("patch")
patch.AddBox((-PX / 2, -PY / 2, H_SUB), (PX / 2, PY / 2, H_SUB), priority=10)

# 读出（ge5 同族修复）：soft plane 激励 + 双 E 探针对反射分解——域内零电阻片
# （原全口径 LumpedPort 电阻片=测量面并联 Z0 负载+相位 Möbius 像，见审计）
{_wg_readout_block(lay, reflection=True)}'''


def _ms_cross_lines(p: dict[str, Any]) -> str:
    """FSS 带阻十字偶极子单元（DP-10）：正交双极化稳定，屏=基板顶零厚十字。

    读出（2026-10-01 ge5 同族修复，runs/ge5_msfam/criteria.md §0）：soft plane
    激励 + 双 E 探针对方向求解——域内零电阻片（原全口径 LumpedPort 电阻片=
    测量面并联 Z0 负载，能量预算破损，同 ms_jcross 病灶，audit §E）。
    方向：金属偶极子臂谐振由 E∥臂驱动（与槽缝 FSS 的 E⊥缝长轴判据相反），
    十字 90° 旋转自映射——E∥x 驱动 x 臂即耦合极化，无需旋转。
    """
    lay = p["_ms_layout"]
    return f'''# ms_cross 波导模拟器单元（E∥x 极化前提；x 臂为受激臂，y 臂=正交极化对偶臂）
ARM = {lay["arm"]!r}
ARM_W = {lay["arm_w"]!r}
cross = CSX.AddMetal("cross")
cross.AddBox((-ARM, -ARM_W / 2, H_SUB), (ARM, ARM_W / 2, H_SUB), priority=10)
cross.AddBox((-ARM_W / 2, -ARM, H_SUB), (ARM_W / 2, ARM, H_SUB), priority=10)
for _prim in cross.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)

# 读出（ge5 同族修复）：soft plane 激励 + 双 E 探针对方向求解——域内零电阻片
# （原全口径 LumpedPort 电阻片=测量面并联 Z0 负载，能量预算破损，见审计）
{_wg_readout_block(lay)}'''


def _ms_ring_patch_lines(p: dict[str, Any]) -> str:
    """双谐振方环+内贴片反射单元（DP-10 §1c 预登记 fallback，ge5 段③注册）。

    几何：方环=外方减内空腔的 4 条带盒（tile 无重叠，cross/patch 同 priority
    10 惯例）+ 中心方贴片；环几何 core 闭式单源（ms_ring_patch_dims_mm），
    贴片边长=LUT 扫描变量。读出=ms_patch 同族反射口径（soft plane+双 E 探针
    对+_WgProbePairRefl 对调 uf，段①移植自 jcross 修法）。
    """
    lay = p["_ms_layout"]
    return f'''# ms_ring_patch 波导模拟器单元（E∥x 极化前提；y 极化需互换 PEC/PMC 对壁）
# 双谐振方环+内贴片（DP-10 §1c 预登记 fallback；环几何 core/metasurface_lut
# 单源 ms_ring_patch_dims_mm：void=0.4λ0、ring_w=λg/40、ring_outer=void+2·ring_w）
VOID = {lay["void"] / 2!r}   # 空腔半边=环内缘（半坐标）
RW = {lay["ring_w"]!r}
RO = {lay["ring_outer"] / 2!r}   # 环外缘（半坐标）
PX = {lay["px"]!r}
ring = CSX.AddMetal("ring")
ring.AddBox((-RO, -RO, H_SUB), (RO, -VOID, H_SUB), priority=10)
ring.AddBox((-RO, VOID, H_SUB), (RO, RO, H_SUB), priority=10)
ring.AddBox((-RO, -VOID, H_SUB), (-VOID, VOID, H_SUB), priority=10)
ring.AddBox((VOID, -VOID, H_SUB), (RO, VOID, H_SUB), priority=10)
patch = CSX.AddMetal("patch")
patch.AddBox((-PX / 2, -PX / 2, H_SUB), (PX / 2, PX / 2, H_SUB), priority=10)
for _prim in ring.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)

# 读出（ge5 反射口径，ms_patch 同族）：soft plane 激励 + 双 E 探针对反射分解
# ——域内零电阻片（段①同款，_WgProbePairRefl 对调 uf 使 S11=Γ）
{_wg_readout_block(lay, reflection=True)}'''


def ms_jcross_metal_boxes(period: float, slot_len: float, slot_w: float,
                          stub_len: float) -> list[tuple[float, float, float, float]]:
    """JC 缝屏金属分解（纯函数）：胞面减「主缝+4 端枝」互联孔径 → y 条带金属盒。

    孔洞：主缝 |x|≤S/2,|y|≤w/2；端枝 x∈[±(S/2−w),±S/2]、
    y∈[±w/2,±(w/2+T)]（与主缝共边互联=单孔径）。返回 (x0,y0,x1,y1) 米制。
    """
    a = period
    s, w, t = slot_len, slot_w, stub_len
    strips: list[tuple[float, float, float, float]] = []
    # 按条带下缘 y 界键控的孔洞 x 区间（#212 实测抓错版：端枝孔原被切进
    # 邻带——带内孔与带缘对位错一格，金属补集面积差 4·w·t）
    stub_metal = [(-a / 2, -s / 2), (-s / 2 + w, s / 2 - w), (s / 2, a / 2)]
    slot_metal = [(-a / 2, -s / 2), (s / 2, a / 2)]
    holes: dict[float, list[tuple[float, float]]] = {
        -(w / 2 + t): stub_metal,   # 带 [−(w/2+T), −w/2]：−y 端枝孔
        -w / 2: slot_metal,          # 带 [−w/2, w/2]：主缝孔
        w / 2: stub_metal,           # 带 [w/2, w/2+T]：+y 端枝孔
        # [w/2+T, a/2] 无键=全金属条带
    }
    # 条带界必须含全部孔洞 y 缘（含无键的 w/2+t 全金属带界），否则末带
    # 合并进端枝带、端枝孔洞越切到胞缘（#212 实测抓出的第一版错误形态）
    ys = sorted({*holes, w / 2 + t})
    bands = ([(-a / 2, ys[0])]
             + [(ys[i], ys[i + 1]) for i in range(len(ys) - 1)]
             + [(ys[-1], a / 2)])
    for y0, y1 in bands:
        xs_list = holes.get(y0)  # 带下缘=孔洞 y 界的带按孔洞 x 分段
        if xs_list is None:
            strips.append((-a / 2, y0, a / 2, y1))
            continue
        for x0, x1 in xs_list:
            strips.append((x0, y0, x1, y1))
    return strips


def _ms_jcross_lines(p: dict[str, Any]) -> str:
    """FSS 带通 Jerusalem cross 缝单元（DP-10）：互联缝孔径，屏=孔洞补集盒。

    方向（2026-10-01 ge5 方向修复，runs/ge5_msjcross/criteria.md §7）：主缝
    沿 **y**、端枝沿 x——E∥x 波导模拟器 TEM 对缝垂直驱动（F3 实验：x 缝
    E∥x 非耦合极化全带无峰；y 缝峰现形且与载板 PSSFSS 吻合）。ms_jcross_
    metal_boxes 纯函数保持「函数 x=缝长轴」的分解语义不变，本层发射时做
    (x,y)→(y,x) 旋转；参数名义值（λg/4 缝）旋转不变。
    """
    lay = p["_ms_layout"]
    boxes = ms_jcross_metal_boxes(lay["period"], lay["slot_len"],
                                  lay["slot_w"], lay["stub_len"])
    # (x,y)→(y,x) 旋转发射（主缝沿 y；见 docstring 方向修复注）
    body = "\n".join(
        f"screen.AddBox(({y0!r}, {x0!r}, H_SUB), ({y1!r}, {x1!r}, H_SUB), priority=10)"
        for x0, y0, x1, y1 in boxes)
    return f'''# ms_jcross 波导模拟器单元（E∥x 极化前提；互联 JC 缝=带通孔径，Marcuvitz
# 网格 EC 初值口径：主缝 λg/4 + 端枝 λg/8，core/metasurface_lut 单源）
# 方向（ge5 修复）：主缝沿 y（E∥x 缝垂直驱动，F3 实验；x 缝为非耦合极化）
# 读出（ge5 修复）：soft plane 激励 + 双 E 探针对方向求解——域内零电阻片
# （原全口径 LumpedPort 电阻片=测量面并联 Z0 负载，能量预算破损，见审计）
screen = CSX.AddMetal("jc_screen")
{body}
for _prim in screen.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)

# ── soft plane 激励（官方 PPW 教程 exc_type=0 口径；双向透明）──
Z_SRC = {lay["z_src"]!r}   # 激励面（距 z 底 MUR λ0/16，#253 内缩口径）
Z_1A = {lay["z_1a"]!r}   # 下探针对近端（屏下游侧）
Z_1B = {lay["z_1b"]!r}   # 下探针对远端（对内距 λ0/16）
Z_2A = {lay["z_2a"]!r}   # 上探针对近端（屏上游侧）
Z_2B = {lay["z_2b"]!r}   # 上探针对远端
_exc_wg = CSX.AddExcitation("wg_exc", exc_type=0,
                            exc_val=np.array([1.0, 0.0, 0.0]))
_exc_wg.AddBox((-DOM_X, -DOM_Y, Z_SRC), (DOM_X, DOM_Y, Z_SRC), priority=5)
for _nm, _zp in (("1a", Z_1A), ("1b", Z_1B), ("2a", Z_2A), ("2b", Z_2B)):
    _u = CSX.AddProbe("u" + _nm, p_type=0, weight=-1)
    _u.AddBox(np.array([-DOM_X, 0.0, _zp]), np.array([DOM_X, 0.0, _zp]))

class _WgProbePair(object):
    """CalcPort 兼容垫片：同侧双 E 探针对 + 精确 β 方向求解（TEM 空气区）。

    E 探针=全口径 x 向线积分（weight=-1，LumpedPort ut 同构造）；探针自由
    悬浮不扰动场。F/B 分解：E_a=F+B·e1、E_b=F·p+B/p（p=e^(-jβΔz)）——
    判读口径 runs/ge5_msjcross/criteria.md；能量门=|S11|²+|S21|²∈[0.90,1.02]
    （单模子带 f≤0.95·c/(2b)，带顶多模污染区只报告）。
    """

    def __init__(self, dom_x, za, zb, pair, forward_as_ref=False):
        self._a = 2 * dom_x
        self._za = za
        self._zb = zb
        self._pair = pair
        self._fwd_ref = forward_as_ref
        self.start = np.array([-dom_x, 0.0, za])
        self.stop = np.array([dom_x, 0.0, zb])
        self.uf_inc = None
        self.uf_ref = None

    def CalcPort(self, sim_path, freq, ref_impedance=None,
                 ref_plane_shift=None, signal_type="pulse"):
        def _rd(_p):
            _ls = open(_p).read().splitlines()
            return np.array([[float(x) for x in _l.split()] for _l in _ls
                             if not _l.startswith("%") and _l.strip()])
        _t = _rd(os.path.join(sim_path, "u" + self._pair + "a"))[:, 0]
        _dt = _t[1] - _t[0]
        _Ea_t = -_rd(os.path.join(sim_path, "u" + self._pair + "a"))[:, 1] / self._a
        _Eb_t = -_rd(os.path.join(sim_path, "u" + self._pair + "b"))[:, 1] / self._a
        _dz = self._zb - self._za
        _F = np.zeros(len(freq), complex)
        _B = np.zeros(len(freq), complex)
        for _j, _fq in enumerate(freq):
            _Ea = np.sum(_Ea_t * np.exp(-2j * np.pi * _fq * _t)) * _dt
            _Eb = np.sum(_Eb_t * np.exp(-2j * np.pi * _fq * _t)) * _dt
            _beta = 2 * np.pi * _fq / 299792458.0
            _den = np.exp(-1j * _beta * _dz) - np.exp(1j * _beta * _dz)
            _f = (_Eb - _Ea * np.exp(1j * _beta * _dz)) / _den
            _F[_j] = _f
            _B[_j] = _Ea - _f
        if self._fwd_ref:
            # port2 垫片：footer S21=_port2.uf_ref/_port1.uf_inc——uf_ref 载
            # 前行波 F2（对 port2 而言=到达波口径的物理透射）
            self.uf_inc = _F
            self.uf_ref = _F
        else:
            self.uf_inc = _F
            self.uf_ref = _B

_port1 = _WgProbePair(DOM_X, Z_1A, Z_1B, "1")
_port2 = _WgProbePair(DOM_X, Z_2A, Z_2B, "2", forward_as_ref=True)
'''

def _fmt_float_list(values: list[float]) -> str:
    return "[" + ", ".join(repr(float(v)) for v in values) + "]"


def ms_array_layout(params: dict[str, Any],
                    freq_range_ghz: tuple[float, float], base_m: float,
                    h_m: float) -> dict[str, Any]:
    """ms_array_NxN 几何/照明/域单源（米制；cell_map 覆盖完备+邻胞间隙守卫）。

    cell_map：n_y 行 × n_x 列的逐单元参数表（每胞 dict：px_mm/py_mm 必填，
    cell_id 可选且仅接受 "ms_patch"）。n_x/n_y 与 cell_map 行列数逐维相等
    （覆盖完备守卫，违反抛 ValueError）。照明=软平面（法向入射 E∥x）；
    阵为有限口径（侧向 MUR，无 PEC/PMC 对壁——那是单胞无限阵技巧）。
    """
    near_m = base_m / float(params.get("_near_ratio", 4) or 4)
    period = float(params.get("period_mm", 14.9896)) * 1e-3
    n_x = int(params.get("n_x", 3))
    n_y = int(params.get("n_y", 3))
    cell_map = params.get("cell_map")
    if (not isinstance(cell_map, list) or len(cell_map) != n_y
            or any(not isinstance(row, list) or len(row) != n_x
                   for row in cell_map)):
        raise ValueError(
            f"ms_array_NxN: cell_map 覆盖不完备（需 {n_y} 行 × {n_x} 列）")
    lam0_m = 299792458.0 / ((freq_range_ghz[0] + freq_range_ghz[1]) / 2 * 1e9)
    # ms_ring_patch 阵胞（ge5 段③，runs/ge5_j2fb）：环几何=core 闭式派生
    # （全阵同环，贴片逐胞变），导体 extent=ring_outer 非贴片边长
    from rfauto.core.metasurface_lut import ms_ring_patch_dims_mm

    _ring_dims = None
    cells: list[dict[str, Any]] = []
    min_edge_gap = float("inf")
    min_neighbor_gap = float("inf")
    for j in range(n_y):
        for i in range(n_x):
            cell = cell_map[j][i]
            if not isinstance(cell, dict):
                raise ValueError(
                    f"ms_array_NxN: cell_map[{j}][{i}] 非参数表")
            cid = cell.get("cell_id", "ms_patch")
            if cid == "ms_patch":
                px = float(cell["px_mm"]) * 1e-3
                py = float(cell["py_mm"]) * 1e-3
                ring_half_o = ring_half_v = None
            elif cid == "ms_ring_patch":
                if _ring_dims is None:
                    _ring_dims = ms_ring_patch_dims_mm(
                        (freq_range_ghz[0] + freq_range_ghz[1]) / 2,
                        float(params.get("er", 3.66)))
                    # 环外缘→胞缘缝守卫（环=导体 extent，全阵同值）
                    _ring_edge = (period
                                  - _ring_dims["ring_outer_mm"] * 1e-3) / 2
                    if _ring_edge < 2 * near_m:
                        raise ValueError(
                            f"ms_array_NxN: ms_ring_patch 环外缘-胞缘缝 "
                            f"{_ring_edge * 1e3:.4f}mm < 2·NEAR（#266 族守卫）")
                px = float(cell["patch_px_mm"]) * 1e-3
                py = px
                ring_half_o = _ring_dims["ring_outer_mm"] * 1e-3 / 2
                ring_half_v = _ring_dims["void_mm"] * 1e-3 / 2
            else:
                raise ValueError(
                    f"ms_array_NxN: cell_map[{j}][{i}] cell_id={cid!r} "
                    "不在本渲染器单元库（当前=ms_patch|ms_ring_patch）")
            if not 0 < px < period or not 0 < py < period:
                raise ValueError(
                    f"ms_array_NxN: cell_map[{j}][{i}] 贴片须在胞内")
            edge = min((period - px) / 2, (period - py) / 2)
            if ring_half_o is None and edge < 2 * near_m:
                raise ValueError(
                    f"ms_array_NxN: cell_map[{j}][{i}] 胞缘缝 "
                    f"{edge * 1e3:.4f}mm < 2·NEAR（#266 族守卫）")
            min_edge_gap = min(min_edge_gap, edge)
            x0 = (i - (n_x - 1) / 2) * period
            y0 = (j - (n_y - 1) / 2) * period
            if i + 1 < n_x:
                nb = period - (px + float(cell_map[j][i + 1].get(
                    "px_mm", cell_map[j][i + 1].get("patch_px_mm",
                                                    px))) * 1e-3) / 2
                if ring_half_o is not None:
                    nb = min(nb, period - _ring_dims["ring_outer_mm"] * 1e-3)
                min_neighbor_gap = min(min_neighbor_gap, nb)
            if j + 1 < n_y:
                nb = period - (py + float(cell_map[j + 1][i].get(
                    "py_mm", cell_map[j + 1][i].get("patch_px_mm",
                                                    px))) * 1e-3) / 2
                if ring_half_o is not None:
                    nb = min(nb, period - _ring_dims["ring_outer_mm"] * 1e-3)
                min_neighbor_gap = min(min_neighbor_gap, nb)
            cells.append({"i": i, "j": j, "x": x0, "y": y0,
                          "px": px, "py": py,
                          **({"ring": {"half_o": ring_half_o,
                                       "half_v": ring_half_v}}
                             if ring_half_o is not None else {})})
    if min_neighbor_gap < 2 * near_m:
        raise ValueError(
            f"ms_array_NxN: 邻胞间隙 {min_neighbor_gap * 1e3:.4f}mm < 2·NEAR"
            f"（criteria §4.2 守卫）")
    side_margin = lam0_m / 4
    dom_x = n_x * period / 2 + side_margin
    dom_y = n_y * period / 2 + side_margin
    z_exc = h_m + lam0_m / 4           # 软平面照明（法向入射，E∥x）
    z_top = z_exc + lam0_m / 8         # 平面上方余量再 MUR
    near_x: list[float] = []
    near_y: list[float] = []
    for c in cells:
        near_x += [c["x"] - c["px"] / 2, c["x"] + c["px"] / 2]
        near_y += [c["y"] - c["py"] / 2, c["y"] + c["py"] / 2]
        if "ring" in c:
            near_x += [c["x"] - c["ring"]["half_o"],
                       c["x"] + c["ring"]["half_o"],
                       c["x"] - c["ring"]["half_v"],
                       c["x"] + c["ring"]["half_v"]]
            near_y += [c["y"] - c["ring"]["half_o"],
                       c["y"] + c["ring"]["half_o"],
                       c["y"] - c["ring"]["half_v"],
                       c["y"] + c["ring"]["half_v"]]
    return {"n_x": n_x, "n_y": n_y, "period": period, "cells": cells,
            "dom_x": dom_x, "dom_y": dom_y, "z_exc": z_exc, "z_top": z_top,
            "near_x": sorted(set(near_x)), "near_y": sorted(set(near_y)),
            "min_edge_gap_m": min_edge_gap,
            "min_neighbor_gap_m": min_neighbor_gap}


def ms_array_render(template: str, params: dict[str, Any],
                    freq_range_ghz: tuple[float, float],
                    mesh_resolution_mm: float = 0.0,
                    substrate: dict[str, Any] | None = None) -> str:
    """ms_array_NxN 整脚本渲染器（无端口软平面照明 + nf2ff 散射远场）。

    口径（DP-10 §4/J2）：有限 N×N 反射阵；地面=z 底 PEC 边界（地连续由
    边界构造性保证）；贴片零厚在基板顶；上方 λ0/4 空气隙处置软激励平面
    （exc_type=0 全口径，官方 PPW 教程口径；法向入射 E∥x 极化前提），
    平面与阵之间置 nf2ff 盒（反射方向远场，J2 判读面）。
    无端口无 sparams.csv——产物=farfield_cut.csv/farfield3d.csv/
    farfield_meta.json/array_meta.json（观测链 best-effort #105）。
    nf2ff 记录=直构六面闭合零镜像（ge7 ffrender 修复，runs/ge6_ffdbg/
    replay_findings.md 定案：CreateNF2FFBox 的 BC 推导 PEC 镜像在悬空
    Box 底面错位 0.131λ0 → θ=0 宽瓣伪象抢峰；详见脚本内注记）。
    """
    substrate = substrate or _DEFAULT_SUB
    f0 = (freq_range_ghz[0] + freq_range_ghz[1]) / 2 * 1e9
    fc = max((freq_range_ghz[1] - freq_range_ghz[0]) / 2 * 1e9, 1e6)
    er = float(substrate["er"])
    h_m = float(params.get("h_mm", substrate["h_mm"])) * 1e-3
    tan_d = float(substrate.get("tan_d", 1e-3))
    base_m = (3e8 / ((f0 + fc) * (er ** 0.5)) / 50 if not mesh_resolution_mm
              else float(mesh_resolution_mm) * 1e-3)
    _nrts = int(params.get("_nrts", 100000) or 100000)
    # F-D NrTS/EndCriteria 缺省接线（wf:nrts-fix）：本渲染器只经 render_script
    # 早分发/直调到达，_fd_nrts_defaults 在此恰调一次（主路径已跳过 PORTLESS）
    _fd_max_time_ns = _fd_nrts_defaults(template, params)
    _fd_end_criteria_src = (
        f", EndCriteria={float(params['_end_criteria'])!r}"
        if "_end_criteria" in params else "")
    _fd_nrts_block = (
        _fd_nrts_override_block(_fd_max_time_ns) if _fd_max_time_ns else "")
    lay = ms_array_layout(params, freq_range_ghz, base_m, h_m)
    near_m = base_m / float(params.get("_near_ratio", 4) or 4)

    def _cell_box(c: dict[str, Any]) -> str:
        """单胞盒字面：ms_patch=贴片 1 盒；ms_ring_patch=环 4 条带+贴片 5 盒。"""
        x0, y0 = c["x"], c["y"]
        px, py = c["px"], c["py"]
        out = [f'patch.AddBox(({x0 - px / 2!r}, {y0 - py / 2!r}, '
               f'H_SUB), ({x0 + px / 2!r}, {y0 + py / 2!r}, H_SUB), '
               f'priority=10)']
        if "ring" in c:
            ho, hv = c["ring"]["half_o"], c["ring"]["half_v"]
            out = [f'patch.AddBox(({x0 - ho!r}, {y0 - ho!r}, '
                   f'H_SUB), ({x0 + ho!r}, {y0 - hv!r}, H_SUB), priority=10)',
                   f'patch.AddBox(({x0 - ho!r}, {y0 + hv!r}, '
                   f'H_SUB), ({x0 + ho!r}, {y0 + ho!r}, H_SUB), priority=10)',
                   f'patch.AddBox(({x0 - ho!r}, {y0 - hv!r}, '
                   f'H_SUB), ({x0 - hv!r}, {y0 + hv!r}, H_SUB), priority=10)',
                   f'patch.AddBox(({x0 + hv!r}, {y0 - hv!r}, '
                   f'H_SUB), ({x0 + ho!r}, {y0 + hv!r}, H_SUB), priority=10)',
                   out[0]]
        return "\n".join(out)

    cell_boxes = "\n".join(_cell_box(c) for c in lay["cells"])
    near_x_txt = _fmt_float_list(lay["near_x"])
    near_y_txt = _fmt_float_list(lay["near_y"])
    cell_map_literal = repr(params.get("cell_map"))
    return f'''#!/usr/env/python3
"""openEMS script (rfauto {template} template auto-generated, official-method mesh)."""
import csv
import json
import os

# CSXCAD/openEMS 扩展模块的依赖 DLL 不在 Python 3.8+ 的 PATH 搜索里，
# 必须 add_dll_directory（2026-09-03 审计实测）。
_OE_BIN = os.environ.get("RFAUTO_OPENEMS_BIN", r"E:\\\\openEMS\\\\install\\\\bin")
if os.path.isdir(_OE_BIN):
    os.environ["PATH"] = _OE_BIN + os.pathsep + os.environ.get("PATH", "")
    os.add_dll_directory(_OE_BIN)

import numpy as np
from CSXCAD import ContinuousStructure
from openEMS import openEMS
from openEMS.nf2ff import nf2ff as _NF2FF

F0 = {f0!r}
FC = {fc!r}
ER = {er!r}
H_SUB = {h_m!r}
TAND = {tan_d!r}
BASE = {base_m!r}   # 网格 base：λ_sub/50 @F_MAX（官方口径）或显式覆盖
NEAR = {near_m!r}   # 近场区 = base/_near_ratio
DOM_X = {lay["dom_x"]!r}
DOM_Y = {lay["dom_y"]!r}
Z_EXC = {lay["z_exc"]!r}   # 软平面照明面（λ0/4 空气隙上）
Z_TOP = {lay["z_top"]!r}
N_X = {lay["n_x"]}
N_Y = {lay["n_y"]}

CSX = ContinuousStructure()
FDTD = openEMS(NrTS={_nrts!r}{_fd_end_criteria_src})   # 官方口径：不设 EndCriteria，能量判据停机{'；EndCriteria=显式停机判据（F-D 接线/旋钮）' if _fd_end_criteria_src else ''}
FDTD.SetCSX(CSX)
FDTD.SetGaussExcite(F0, FC)
# 有限阵：侧/顶 MUR 吸收；z 底 PEC=反射阵地板（地连续由边界构造性保证）
FDTD.SetBoundaryCond(["MUR", "MUR", "MUR", "MUR", "PEC", "MUR"])

mesh = CSX.GetGrid()
# 贴片缘精确入网（#198）+ 胞缘缝内部线（#311 口径），全轴 BASE 平滑
for _x in {near_x_txt}:
    mesh.AddLine("x", _x)
for _y in {near_y_txt}:
    mesh.AddLine("y", _y)
mesh.AddLine("x", np.array([-DOM_X, DOM_X]))
mesh.AddLine("y", np.array([-DOM_Y, DOM_Y]))
mesh.AddLine("z", np.linspace(0, H_SUB, 5))
mesh.AddLine("z", np.array([Z_EXC, Z_TOP]))
mesh.SmoothMeshLines("x", NEAR)
mesh.SmoothMeshLines("y", NEAR)
mesh.SmoothMeshLines("z", BASE)
# 近重合网格线守卫（#152）：平滑后按最小间距 1µm 去重
for _ax in ("x", "y", "z"):
    _ls = np.asarray(mesh.GetLines(_ax), dtype=float)
    _keep = [_ls[0]]
    for _v in _ls[1:]:
        if _v - _keep[-1] > 1e-6:
            _keep.append(_v)
    mesh.SetLines(_ax, np.array(_keep))

sub = CSX.AddMaterial("substrate", epsilon=ER,
                      kappa=TAND * 2 * np.pi * F0 * 8.854187817e-12 * ER)
sub.AddBox((-DOM_X, -DOM_Y, 0), (DOM_X, DOM_Y, H_SUB), priority=0)
patch = CSX.AddMetal("patches")
{cell_boxes}
for _prim in patch.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)

# ── 软平面照明（法向入射 E∥x；exc_type=0 官方 PPW 教程口径）──
# E∥x 极化前提（y 极化需改 exc_val 向量）；软源双向发射：向下照明阵列，
# 向上穿 nf2ff 盒顶后被 MUR 吸收（盒在照明面下方，不测照明面直射场）。
_exc = CSX.AddExcitation("inc_plane", exc_type=0,
                         exc_val=np.array([1.0, 0.0, 0.0]))
_exc.AddBox((-DOM_X, -DOM_Y, Z_EXC), (DOM_X, DOM_Y, Z_EXC), priority=0)

# ── nf2ff 盒（域缩 4×网格；阵与照明面之间）——直构六面闭合（ge6_ffdbg 定案）──
# 不用 FDTD.CreateNF2FFBox：其按 FDTD 边界条件自动推导 directions/mirror
# （绑定源 openEMS.pyx L435-483：BC=PEC 侧 directions=False 且 mirror=1，
# 镜像 pos=盒 start 面）。本模板盒底面悬空在贴片上方（结构性避让基底/
# 贴片穿面），自动镜像平面落在悬空底面 z=H_SUB+4·BASE 而非真实 PEC 地
# z=0（偏 3.924mm=0.131λ0@10GHz）→ 错相位镜像 contribution 污染组合、
# 注入 θ=0 宽瓣伪象抢峰（runs/ge6_ffdbg/replay_findings.md §0/§4 同参
# 重放实锤；镜像@z=0 口径 R4 实证束/镜面比坍缩不采用）。
# 修法=直构 nf2ff 类记闭合 6 面 + 全零镜像（严格等效原理：闭合面零镜像，
# 入射场贡献经 extinct 定理自消）。**ge8b 批起底面剔除（K-6 立项销账）**：
# directions 底面（z start）=False——①K-6 五面口径 vs ge6 六面 cpp 重放
# 逐点全对齐（rel_diff≈4e-6，runs/k6_ff_forensic/crosscheck_final.json），
# 底面通量对上半球判读指标零贡献；②省底面记录 ~91GB/档（E 盘曾差 1.2GB
# 零余量）；③ge8 踩坑10（nf2ff C++ 法向启发式 center 缺省出盒）的失真源
# 头消除。面文件序随此为五面：E_1..E_4=侧+顶、无 E_5 底（判读消费 z 顶面
# 按 E_5 取的旧兼容已由 directions 字面驱动自适应）。
_FF_MARGIN = 4 * BASE
_FF = _NF2FF(
    CSX, "nf2ff",
    np.array([-DOM_X + _FF_MARGIN, -DOM_Y + _FF_MARGIN, H_SUB + _FF_MARGIN]),
    np.array([DOM_X - _FF_MARGIN, DOM_Y - _FF_MARGIN, Z_EXC - _FF_MARGIN]),
    directions=[True, True, True, True, False, True], mirror=[0] * 6)

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
{_fd_nrts_block}FDTD.Run(os.path.join(_THIS_DIR, "fdtd"), verbose=0, cleanup=True)

# ── 远场计算 + 阵 meta 落盘（best-effort，#105：失败不阻塞进程）──
try:
    _f_res = float(F0)
    _THETA_CUT = np.arange(-90.0, 91.0, 1.0)
    _PHI_CUT = [0.0, 90.0]
    _ffr = _FF.CalcNF2FF(os.path.join(_THIS_DIR, "fdtd"), _f_res,
                         _THETA_CUT, _PHI_CUT)
    _Dmax = float(np.atleast_1d(_ffr.Dmax)[0])
    _meta = {{
        "ok": True, "template": {template!r},
        "n_x": N_X, "n_y": N_Y,
        "period_mm": {lay["period"] * 1e3!r},
        "cell_map": {cell_map_literal},
        "f0_ghz": F0 / 1e9,
        "dmax_linear": _Dmax,
        "dmax_dbi": 10.0 * np.log10(max(_Dmax, 1e-300)),
        "polarization": "E parallel x (normal incidence)",
        "farfield_semantics": "total outgoing field (specular + shaped beam)"
    }}
    with open(os.path.join(_THIS_DIR, "array_meta.json"), "w",
              encoding="utf-8") as _mh:
        json.dump(_meta, _mh, ensure_ascii=False, indent=1)
    print("rfauto ms_array farfield done: Dmax =", _Dmax)
except Exception as _ffe:
    try:
        with open(os.path.join(_THIS_DIR, "array_meta.json"), "w",
                  encoding="utf-8") as _mh:
            json.dump({{"ok": False, "error": str(_ffe)}}, _mh,
                      ensure_ascii=False)
    except Exception:
        pass
    print("rfauto ms_array farfield 链失败（不阻塞）:", _ffe)
print("rfauto openEMS simulation done")
'''


def ms_geometry_spec(template: str, params: dict[str, Any],
                     substrate: dict[str, Any]) -> dict[str, Any]:
    """MS 族 geometry_spec（UI 3D 预览，mm；early-dispatch 自 geometry_spec）。

    审计契约消费点：test_meta_yaml_identity 校验 spec_ports 数 == meta
    n_ports；test_nominal_params_cover_geometry_inputs 只要求不抛错。
    ms_array_NxN 无端口（ports=[]，n_ports=0 口径）。
    """
    if template in MS_UNIT_TEMPLATES:
        band = (9.75, 10.25)
        base_m = 0.4e-3  # 审计档 base（UI 预览不需真网格）
        h_m = float(params.get("h_mm", substrate["h_mm"])) * 1e-3
        lay = ms_unit_layout(template, params, band, base_m, h_m)
        period_mm = lay["period"] * 1e3
        z_feed_mm = {k: lay[k] * 1e3 for k in ("z_feed", "z_feed_lo",
                                               "z_feed_hi") if k in lay}
        if template == "ms_patch":
            boxes = [
                {"name": "substrate", "material": "substrate",
                 "start_mm": [-period_mm / 2, -period_mm / 2, 0.0],
                 "stop_mm": [period_mm / 2, period_mm / 2, h_m * 1e3]},
                {"name": "patch", "material": "metal",
                 "start_mm": [-lay["px"] * 1e3 / 2, -lay["py"] * 1e3 / 2,
                              h_m * 1e3],
                 "stop_mm": [lay["px"] * 1e3 / 2, lay["py"] * 1e3 / 2, h_m * 1e3]},
                {"name": "soft_exc_plane（soft plane 激励面）", "material": "metal",
                 "start_mm": [-period_mm / 2, -period_mm / 2,
                              lay["z_src"] * 1e3],
                 "stop_mm": [period_mm / 2, period_mm / 2, lay["z_src"] * 1e3]},
            ]
            ports = [{"name": "Port1（探针对反射读出 Γ，_WgProbePairRefl）",
                      "pos_mm": [0.0, 0.0, lay["z_1a"] * 1e3],
                      "dir": [0.0, 0.0, -1.0]}]
        if template == "ms_ring_patch":
            boxes = [
                {"name": "substrate", "material": "substrate",
                 "start_mm": [-period_mm / 2, -period_mm / 2, 0.0],
                 "stop_mm": [period_mm / 2, period_mm / 2, h_m * 1e3]},
                {"name": "ring（方环=4 条带盒，外边=ring_outer）",
                 "material": "metal",
                 "start_mm": [-lay["ring_outer"] * 1e3 / 2,
                              -lay["ring_outer"] * 1e3 / 2, h_m * 1e3],
                 "stop_mm": [lay["ring_outer"] * 1e3 / 2,
                             lay["ring_outer"] * 1e3 / 2, h_m * 1e3]},
                {"name": "patch（内贴片，边长=patch_px）", "material": "metal",
                 "start_mm": [-lay["px"] * 1e3 / 2, -lay["px"] * 1e3 / 2,
                              h_m * 1e3],
                 "stop_mm": [lay["px"] * 1e3 / 2, lay["px"] * 1e3 / 2,
                             h_m * 1e3]},
                {"name": "soft_exc_plane（soft plane 激励面）", "material": "metal",
                 "start_mm": [-period_mm / 2, -period_mm / 2,
                              lay["z_src"] * 1e3],
                 "stop_mm": [period_mm / 2, period_mm / 2, lay["z_src"] * 1e3]},
            ]
            ports = [{"name": "Port1（探针对反射读出 Γ，_WgProbePairRefl）",
                      "pos_mm": [0.0, 0.0, lay["z_1a"] * 1e3],
                      "dir": [0.0, 0.0, -1.0]}]
        elif template == "ms_cross":
            arm_mm = lay["arm"] * 1e3
            arm_w_mm = lay["arm_w"] * 1e3
            boxes = [
                {"name": "substrate", "material": "substrate",
                 "start_mm": [-period_mm / 2, -period_mm / 2, 0.0],
                 "stop_mm": [period_mm / 2, period_mm / 2, h_m * 1e3]},
                {"name": "cross_x", "material": "metal",
                 "start_mm": [-arm_mm, -arm_w_mm / 2, h_m * 1e3],
                 "stop_mm": [arm_mm, arm_w_mm / 2, h_m * 1e3]},
                {"name": "cross_y", "material": "metal",
                 "start_mm": [-arm_w_mm / 2, -arm_mm, h_m * 1e3],
                 "stop_mm": [arm_w_mm / 2, arm_mm, h_m * 1e3]},
                {"name": "feed_sheet_lo", "material": "metal",
                 "start_mm": [-period_mm / 2, -period_mm / 2,
                              z_feed_mm["z_feed_lo"]],
                 "stop_mm": [period_mm / 2, period_mm / 2,
                             z_feed_mm["z_feed_lo"]]},
                {"name": "feed_sheet_hi", "material": "metal",
                 "start_mm": [-period_mm / 2, -period_mm / 2,
                              z_feed_mm["z_feed_hi"]],
                 "stop_mm": [period_mm / 2, period_mm / 2,
                             z_feed_mm["z_feed_hi"]]},
            ]
            ports = [
                {"name": "Port1（TEM 片端口 R=η0，馈）",
                 "pos_mm": [0.0, 0.0, z_feed_mm["z_feed_lo"]],
                 "dir": [1.0, 0.0, 0.0]},
                {"name": "Port2（TEM 片端口 R=η0，收）",
                 "pos_mm": [0.0, 0.0, z_feed_mm["z_feed_hi"]],
                 "dir": [1.0, 0.0, 0.0]},
            ]
        elif template == "ms_jcross":
            boxes = [
                {"name": "substrate", "material": "substrate",
                 "start_mm": [-period_mm / 2, -period_mm / 2, 0.0],
                 "stop_mm": [period_mm / 2, period_mm / 2, h_m * 1e3]},
                {"name": "jc_screen（JC 缝屏，孔洞补集盒）", "material": "metal",
                 "start_mm": [-period_mm / 2, -period_mm / 2, h_m * 1e3],
                 "stop_mm": [period_mm / 2, period_mm / 2, h_m * 1e3]},
                {"name": "feed_sheet_lo", "material": "metal",
                 "start_mm": [-period_mm / 2, -period_mm / 2,
                              z_feed_mm["z_feed_lo"]],
                 "stop_mm": [period_mm / 2, period_mm / 2,
                             z_feed_mm["z_feed_lo"]]},
                {"name": "feed_sheet_hi", "material": "metal",
                 "start_mm": [-period_mm / 2, -period_mm / 2,
                              z_feed_mm["z_feed_hi"]],
                 "stop_mm": [period_mm / 2, period_mm / 2,
                             z_feed_mm["z_feed_hi"]]},
            ]
            ports = [
                {"name": "Port1（TEM 片端口 R=η0，馈）",
                 "pos_mm": [0.0, 0.0, z_feed_mm["z_feed_lo"]],
                 "dir": [1.0, 0.0, 0.0]},
                {"name": "Port2（TEM 片端口 R=η0，收）",
                 "pos_mm": [0.0, 0.0, z_feed_mm["z_feed_hi"]],
                 "dir": [1.0, 0.0, 0.0]},
            ]
        return {"template": template, "substrate": substrate, "boxes": boxes,
                "ports": ports, "elements": []}
    if template == "ms_array_NxN":
        h_m = float(params.get("h_mm", substrate["h_mm"])) * 1e-3
        lay = ms_array_layout(params, (9.75, 10.25), 0.4e-3, h_m)
        n_mm_x = lay["n_x"] * lay["period"] * 1e3
        n_mm_y = lay["n_y"] * lay["period"] * 1e3
        boxes = [
            {"name": "substrate", "material": "substrate",
             "start_mm": [-n_mm_x / 2, -n_mm_y / 2, 0.0],
             "stop_mm": [n_mm_x / 2, n_mm_y / 2, h_m * 1e3]},
            {"name": "patches（cell_map 逐单元）", "material": "metal",
             "start_mm": [-n_mm_x / 2, -n_mm_y / 2, h_m * 1e3],
             "stop_mm": [n_mm_x / 2, n_mm_y / 2, h_m * 1e3]},
            {"name": "excitation_plane（软平面照明）", "material": "metal",
             "start_mm": [-n_mm_x / 2, -n_mm_y / 2, lay["z_exc"] * 1e3],
             "stop_mm": [n_mm_x / 2, n_mm_y / 2, lay["z_exc"] * 1e3]},
        ]
        return {"template": template, "substrate": substrate, "boxes": boxes,
                "ports": [], "elements": []}
    raise ValueError(f"ms_geometry_spec: 未知模板 {template!r}")


# ─── §MS_METASURFACE 注册（TEMPLATE_META/TEMPLATE_NOMINAL 文末注册块，#304 口径）
# 名义尺寸闭式（#252 禁抄毫米数；core/metasurface_lut 单源，互证钉在
# test_metasurface_templates.py；src 侧 nominal=导入期闭式计算非手抄）：
# - ms_patch：period=λ0/2=15.0（0.5λ0 口径）；px=py=方贴片谐振边长
#   λ0/(2√εeff(w)) 不动点（Hammerstad εeff，er=3.66/h=1.524）；
#   h=1.524（60mil 板材数据，X 波段反射阵常用厚度→相位覆盖宽）。
# - ms_cross：period=0.4λ0=12.0；臂长=总跨/2=λ0/(4√εeff)、
#   εeff=(1+εr)/2 单侧基板加载（Luukkonen eq.3 口径）；臂宽=总跨/10。
# - ms_jcross：period=12.0；主缝=λg/4、端枝=λg/8、缝宽=λg/40
#   （λg=λ0/√εeff；Marcuvitz 网格 EC 初值口径，带心真机修正归 P3）。
# - ms_array_NxN：演示名义务 3×3（真机 15×15 战役走参数注入，预算见
#   任务书）；cell_map=三值 px 图样证明逐单元驱动（cell_id 显式）。
def _ms_nominal() -> tuple[float, float, float]:
    """闭式 nominal 计算（core 单源导入收口在函数内，scipy 链惰性）。"""
    from rfauto.core.metasurface_lut import ms_cross_arm_len_mm, ms_jcross_slot_dims_mm, ms_patch_resonant_len_mm

    px = round(ms_patch_resonant_len_mm(10.0, 3.66, 1.524), 4)
    arm = round(ms_cross_arm_len_mm(10.0, 3.66), 4)
    jc = ms_jcross_slot_dims_mm(10.0, 3.66)
    return px, arm, round(jc["stub_len_mm"], 4)


_MS_PATCH_NOM_PX, _MS_CROSS_NOM_ARM, _MS_JCROSS_NOM_STUB = _ms_nominal()
_MS_LAM0_MM = 299792458.0 / 10e9 * 1e3
_MS_EPS_EFF_SCREEN = (1.0 + 3.66) / 2.0
_MS_LAMG_MM = _MS_LAM0_MM / (_MS_EPS_EFF_SCREEN ** 0.5)

MS_PATCH_META: dict[str, Any] = {
    "f0_ghz": 10.0, "n_ports": 1,
    "extraction": "S11 @ 双 E 探针对反射分解（soft plane 激励 exc_type=0；探针"
                  "对=贴片上方空气区 2 只全口径 E 线探针，对内距 λ0/16，精确 "
                  "β=2πf/c 分解 F/B 后 _WgProbePairRefl 对调 uf——入射=−z 照明"
                  "波、反射=+z 回波，footer 契约/sparams.csv 5 列 schema 不变，"
                  "_port2=_port1 别名 S21 列≡S11）。波导模拟器≡无限阵@θ=0，"
                  "E∥x 极化前提；|S11|≈1 的 argΓ 逐 px 入反射相位 LUT（探针面"
                  "去嵌相位常数项不进扫 px 差分）；健康判据=|Γ| 线性域 ≈1（空"
                  "波导标定 EN=|Γ|²≈1.0 平坦）。无耗接地结构幅度读出 «1 = 读出"
                  "判废信号。（2026-10-01 ge5 ms_patch 读出修复：原全口径 "
                  "LumpedPort 电阻片=测量面并联 Z0 负载，反射相位为片负载 "
                  "Möbius 像，runs/ge5_msjcross/audit.md §D/E + 六百八十"
                  "七）",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["px_mm", "py_mm", "period_mm", "h_mm"],
    "topology": "反射阵方贴片单元：接地基板（z 底 PEC 边界）+ 零厚方贴片；单胞方形"
                "域 x 对壁 PEC / y 对壁 PMC（TEM 平面波）；贴片上方 λ0/4 空气区置"
                "双 E 探针对（自由悬浮无源）+ 探针对上方 soft plane 激励面，"
                "域内零电阻片",
    "param_semantics": "px_mm=E 向（x）谐振边长（LUT 扫描变量），py_mm=非谐振宽（y），"
                       "period_mm=单胞周期（方形域边长），h_mm=基板厚；er/tan_d 走 "
                       "substrate/nominal（材料属性不改导体）",
    "mesh_note": "0=自动 λ_sub/50@F_MAX；贴片缘精确入网+胞缘缝 3+ 中点入网（#311）；"
                 "NEAR≤最小胞缘缝/3 渲染期守卫（#266）；全轴 ≥10µm",
    "smoke_note": "离线审计先行（#212，test_metasurface_templates）；波导模拟器扫"
                  "描战役（粗 21+细 41 点）发射面见 战役任务书；"
                  "读出修复后重扫见 runs/ge5_j2fb/（J2 fallback 战役段②）",
}
_MS_PATCH_NOM_PERIOD = round(_MS_LAM0_MM / 2, 4)   # λ0/2（#252 闭式非手抄）
MS_PATCH_NOMINAL: dict[str, Any] = {
    "px_mm": _MS_PATCH_NOM_PX, "py_mm": _MS_PATCH_NOM_PX,
    "period_mm": _MS_PATCH_NOM_PERIOD, "h_mm": 1.524,
    "er": 3.66, "tan_d": 0.0037,
}

MS_CROSS_META: dict[str, Any] = {
    "f0_ghz": 10.0, "n_ports": 2,
    "extraction": "S11/S21 @ 双 E 探针对方向求解（soft plane 激励 exc_type=0；"
                  "探针对=屏两侧空气区各 2 只全口径 E 线探针，对内距 λ0/16，"
                  "精确 β=2πf/c 分解 F/B——footer 垫片 _port1/_port2 契约"
                  "不变）。波导模拟器≡无限阵@θ=0，E∥x 极化前提；S21 谷=带阻"
                  "（十字偶极子半波谐振）；J3 vs PSSFSS Δf≤0.3GHz 或 ≤5% 真机"
                  "轨判。能量门=|S11|²+|S21|²∈[0.90,1.02]（单模子带 "
                  "f≤0.95·c/(2b)；带顶多模污染区只报告不设门）。（2026-10-01 "
                  "ge5 同族修复：原全口径 LumpedPort 电阻片=测量面并联 Z0 负载，"
                  "runs/ge5_msjcross/audit.md §E）",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["arm_len_mm", "arm_w_mm", "period_mm", "h_mm"],
    "topology": "FSS 带阻十字偶极子单元：基板顶零厚正交双十字臂（x 臂=受激臂，"
                "y 臂=正交极化对偶臂；金属偶极子 E∥臂耦合，无需槽缝族的方向"
                "旋转）；单胞 PEC/PMC 对壁域；屏两侧 λ0/4 空气区各置双 E 探针"
                "对（自由悬浮无源）+ z 底 MUR 上方 soft plane 激励面",
    "param_semantics": "arm_len_mm=臂长（中心→尖端，总跨=2·arm 半波谐振），"
                       "arm_w_mm=臂宽，period_mm=单胞周期，h_mm=基板厚；"
                       "er/tan_d 走 substrate/nominal",
    "mesh_note": "0=自动 λ_sub/50@F_MAX；臂缘精确入网+邻臂尖缝 3+ 中点入网；"
                 "NEAR≤邻臂尖缝/3 渲染期守卫；全轴 ≥10µm",
    "smoke_note": "离线审计先行（#212）；带阻谐振闭式互证（λ0/2√εeff 口径）；"
                  "真机波导模拟器 smoke（空波导 EN 标定+真屏带阻谷+裁判对拍）"
                  "判据 runs/ge5_msfam/criteria.md §2",
}
MS_CROSS_NOMINAL: dict[str, Any] = {
    "arm_len_mm": _MS_CROSS_NOM_ARM,
    "arm_w_mm": round(_MS_CROSS_NOM_ARM / 5, 4),  # 臂宽=臂长/5（=总跨/10 闭式）
    "period_mm": round(0.4 * _MS_LAM0_MM, 4),     # 0.4λ0（无光栅瓣口径闭式）
    "h_mm": 0.508,
    "er": 3.66, "tan_d": 0.0037,
}

MS_JCROSS_META: dict[str, Any] = {
    "f0_ghz": 10.0, "n_ports": 2,
    "extraction": "S11/S21 @ 双 E 探针对方向求解（soft plane 激励 exc_type=0；"
                  "探针对=屏两侧空气区各 2 只全口径 E 线探针，对内距 λ0/16，"
                  "精确 β=2πf/c 分解 F/B——footer 垫片 _port1/_port2 契约"
                  "不变）。波导模拟器≡无限阵@θ=0，E∥x 极化前提；S21 峰=带通"
                  "（JC 缝互联孔径谐振）；J3 vs PSSFSS Δf≤0.3GHz 或 ≤5% 真机"
                  "轨判。能量门=|S11|²+|S21|²∈[0.90,1.02]（单模子带 "
                  "f≤0.95·c/(2b)；带顶多模污染区只报告不设门）。（2026-10-01 "
                  "ge5 修复：原全口径 LumpedPort 电阻片=测量面并联 Z0 负载，"
                  "空波导 EN 0.38 vs 解析 0.556，读出作废，"
                  "runs/ge5_msjcross/audit.md）",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["slot_len_mm", "slot_w_mm", "stub_len_mm", "period_mm", "h_mm"],
    "topology": "FSS 带通 Jerusalem cross 缝单元：零厚金属屏（胞面减互联孔径盒"
                "分解）+ 主缝端 4 枝端加载；单胞 PEC/PMC 对壁域；屏两侧 λ0/4 "
                "空气区各置双 E 探针对（自由悬浮无源）+ z 底 MUR 上方 soft "
                "plane 激励面",
    "param_semantics": "slot_len_mm=主缝全长（**y 向**，ge5 2026-10-01 方向修复："
                       "E∥x 需缝垂直驱动，F3 实验 criteria §7），slot_w_mm=缝宽"
                       "（主缝与端枝同宽），stub_len_mm=端枝长（**±x 向**，与主缝"
                       "共边互联），period_mm=单胞周期，h_mm=基板厚；er/tan_d 走 "
                       "substrate/nominal",
    "mesh_note": "0=自动 λ_sub/50@F_MAX；缝缘精确入网+屏缘缝 3+ 中点入网；"
                 "NEAR≤最小屏缝/3 渲染期守卫；孔径盒逐面入网（#174）；全轴 ≥10µm",
    "smoke_note": "离线审计先行（#212）；EC 自洽钉（shunt 并联 LC 峰=f0）在 "
                  "test_metasurface_lut；真机带心修正（openEMS LUT 一轮）归 P3",
}
MS_JCROSS_NOMINAL: dict[str, Any] = {
    "slot_len_mm": round(_MS_LAMG_MM / 4, 4),
    "slot_w_mm": round(_MS_LAMG_MM / 40, 4),
    "stub_len_mm": _MS_JCROSS_NOM_STUB,
    "period_mm": round(0.4 * _MS_LAM0_MM, 4),     # 0.4λ0（同 ms_cross 口径）
    "h_mm": 0.508,
    "er": 3.66, "tan_d": 0.0037,
}

_MS_ARRAY_CELL_MAP = [
    [{"cell_id": "ms_patch", "px_mm": 6.0, "py_mm": 6.0},
     {"cell_id": "ms_patch", "px_mm": 7.5, "py_mm": 7.5},
     {"cell_id": "ms_patch", "px_mm": 9.0, "py_mm": 9.0}],
    [{"cell_id": "ms_patch", "px_mm": 7.5, "py_mm": 7.5},
     {"cell_id": "ms_patch", "px_mm": 9.0, "py_mm": 9.0},
     {"cell_id": "ms_patch", "px_mm": 6.0, "py_mm": 6.0}],
    [{"cell_id": "ms_patch", "px_mm": 9.0, "py_mm": 9.0},
     {"cell_id": "ms_patch", "px_mm": 6.0, "py_mm": 6.0},
     {"cell_id": "ms_patch", "px_mm": 7.5, "py_mm": 7.5}],
]

MS_ARRAY_META: dict[str, Any] = {
    "f0_ghz": 10.0, "n_ports": 0,
    "extraction": "无端口（软平面照明散射体）：产物=farfield_cut.csv/"
                  "farfield3d.csv/farfield_meta.json/array_meta.json；"
                  "J2 峰值方向 vs 闭式 φ_mn 指向 ≤3°（真机轨）；farfield=总出射"
                  "场（镜面反射+赋形波束，判读面在 J2 分解）",
    "max_time_ns": 60.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["n_x", "n_y", "period_mm", "cell_map", "h_mm"],
    "topology": "有限 N×N 反射阵（ms_patch 单元平铺）：接地基板（z 底 PEC 边界）"
                "+ cell_map 逐单元贴片表；上方 λ0/4 空气隙软激励平面照明；"
                "侧向 MUR（有限口径，无 PEC/PMC 对壁——那是单胞无限阵技巧）",
    "param_semantics": "n_x/n_y=x/y 向胞数，period_mm=胞周期，cell_map=n_y 行 ×"
                       " n_x 列逐单元参数表（每胞 px_mm/py_mm/cell_id），"
                       "h_mm=基板厚；n 与 cell_map 行列数逐维相等（覆盖完备守卫）；"
                       "er/tan_d 走 substrate/nominal",
    "mesh_note": "0=自动 λ_sub/50@F_MAX；全部贴片缘精确入网；胞缘/邻胞缝 ≥2·NEAR"
                 " 渲染期守卫；1µm 近重合去重（#152）；全轴 ≥10µm；演示名义 3×3，"
                 "真机 15×15 预算（~4×10⁷ cells 小时级/轮，#328 CSXCAD exec 实测"
                 "口径）见 战役任务书",
    "smoke_note": "离线审计先行（#212）；真机 solo 单飞（#246/#261）",
}
MS_ARRAY_NOMINAL: dict[str, Any] = {
    "n_x": 3, "n_y": 3, "period_mm": _MS_PATCH_NOM_PERIOD,
    "cell_map": _MS_ARRAY_CELL_MAP,
    "h_mm": 1.524,
    "er": 3.66, "tan_d": 0.0037,
}

TEMPLATE_META["ms_patch"] = MS_PATCH_META
TEMPLATE_NOMINAL["ms_patch"] = MS_PATCH_NOMINAL
TEMPLATE_META["ms_cross"] = MS_CROSS_META
TEMPLATE_NOMINAL["ms_cross"] = MS_CROSS_NOMINAL
TEMPLATE_META["ms_jcross"] = MS_JCROSS_META
TEMPLATE_NOMINAL["ms_jcross"] = MS_JCROSS_NOMINAL

# ── ms_ring_patch（双谐振方环+内贴片，DP-10 §1c 预登记 fallback；ge5 J2
#    战役段③注册，runs/ge5_j2fb）：名义全部闭式精算（#1c/#252，core 单源），
#    环几何 ms_ring_patch_dims_mm（void=0.4λ0、ring_w=λg/40、ring_outer=
#    void+2·ring_w——ms_cross/jcross 0.4λ0 屏周期与 JC 缝宽口径族内同源），
#    内贴片=ms_patch_resonant_len_mm 不动点（复用不重复实现）。LUT 扫描变量
#    =patch_px_mm（贴片谐振扫过 f0 为主谐振段，环/槽环境=第二谐振——双谐振
#    宽摆幅机理，段④ J1c ≥300° 门实证裁决）。
MS_RING_PATCH_META: dict[str, Any] = {
    "f0_ghz": 10.0, "n_ports": 1,
    "extraction": "S11 @ 双 E 探针对反射分解（soft plane 激励 exc_type=0；探针"
                  "对=贴片上方空气区 2 只全口径 E 线探针，对内距 λ0/16，精确 "
                  "β=2πf/c 分解 F/B 后 _WgProbePairRefl 对调 uf——入射=−z 照明"
                  "波、反射=+z 回波，footer 契约/sparams.csv 5 列 schema 不变，"
                  "_port2=_port1 别名 S21 列≡S11；与 ms_patch 段①修复同族读"
                  "出，空波导标定 EN≈1.0+闭式相位 0.19° 实证 runs/ge5_j2fb/"
                  "stage2/smoke_report.json）。波导模拟器≡无限阵@θ=0，E∥x 极化"
                  "前提；|S11|≈1 的 argΓ 逐 patch_px 入反射相位 LUT；健康判据="
                  "|Γ| 线性域 ≈1",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["patch_px_mm", "period_mm", "h_mm"],
    "topology": "双谐振反射阵单元：接地基板（z 底 PEC 边界）+ 零厚方环（外边"
                " ring_outer=void+2·ring_w，内空腔 void=0.4λ0，环宽 λg/40）+ "
                "环心方贴片（边长=LUT 扫描变量）；单胞方形域 x 对壁 PEC / y 对"
                "壁 PMC（TEM 平面波）；贴片上方 λ0/4 空气区置双 E 探针对（自由"
                "悬浮无源）+ 探针对上方 soft plane 激励面，域内零电阻片",
    "param_semantics": "patch_px_mm=环心方贴片边长（=py，LUT 扫描变量），"
                       "period_mm=单胞周期（方形域边长），h_mm=基板厚；环几何"
                       "（void/ring_w/ring_outer）=core 闭式派生非声明参数；"
                       "er 进环闭式（εeff=(1+εr)/2）+基板材料，tan_d 只进材料",
    "mesh_note": "0=自动 λ_sub/50@F_MAX；贴片缘/环内外缘精确入网+环-贴片缝与"
                 "环-胞缝 3+ 中点入网（#311）；NEAR≤最小缝/3 渲染期守卫（#266）；"
                 "全轴 ≥10µm",
    "smoke_note": "离线审计先行（#212，test_metasurface_templates）；段④ J1c "
                  "扫描（粗 21 点档+圆周覆盖门 ≥300°）发射面=runs/ge5_j2fb/"
                  "stage2/campaign_j2fb.py --template ms_ring_patch",
}
MS_RING_PATCH_NOMINAL: dict[str, Any] = {
    "patch_px_mm": _MS_PATCH_NOM_PX,   # 内贴片谐振边长（core 不动点，同 ms_patch）
    "period_mm": _MS_PATCH_NOM_PERIOD,  # λ0/2 阵格（同 ms_patch 口径）
    "h_mm": 1.524,
    "er": 3.66, "tan_d": 0.0037,
}
TEMPLATE_META["ms_ring_patch"] = MS_RING_PATCH_META
TEMPLATE_NOMINAL["ms_ring_patch"] = MS_RING_PATCH_NOMINAL

TEMPLATE_META["ms_array_NxN"] = MS_ARRAY_META
TEMPLATE_NOMINAL["ms_array_NxN"] = MS_ARRAY_NOMINAL
