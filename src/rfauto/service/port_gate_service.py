"""DP-16 C4 HFSS 端口尺寸收敛前置门（离线/合成面，规格书 §16.1）。

问题（#191 家族/#254 口径）：波端口截面尺寸不足时 HFSS 解出截止倏逝模
假数据（槽线族微带惯例框把槽两侧地短接、γ 随截面单调不收敛）——真扫
之前先用**端口尺寸阶梯**做单频收敛前置门，便宜（每档一个点频单解）。

阶梯口径（判据预声明 runs/df6_dp16/criteria.md；勘误口径：Ansys 官方
8×波宽/10×h 是防端口缘耦合口径，3-5w/4h 是下限惯例）：

- microstrip 族（准 TEM 单模）：宽度 N∈{3,5,8}×w，高度 4×h；
- slotline_balanced 族（槽线/平衡线，#254 换族查表）：宽度 w+2×margin
  （margin∈{20,40,60}mm）、高度 h+2×30mm——对齐
  scripts/hfss_slotline_arbitration.py 的 y±20/40/60、z∓30 三档实跑口径；
- 换族分派按 physics_roles 值查表（family_from_roles），无法识别 → UNKNOWN。

判据（每档 set_variables 换端口面尺寸 → solve → LastAdaptive 单频取
Zpi/Zpv/Zvi + S21@f_probe）：

1. Zvi 自校恒等式（#356⑤）：|Zvi−√(Zpi·Zpv)|/|Zvi| ≤ 1e-6 逐档检查；
2. 末两档 |ΔS21| ≤ 0.05 dB 且 |ΔZ0/Z0| ≤ 2%（Z0 取 Zvi）；
3. verdict：PASS / FAIL（有数值证据违约）/ UNKNOWN（驱动失败/数据缺失/
   多模/族不可识别）——不凑 PASS 不冒充 FAIL（#122）；多模端口 v1 只
   支持单模准 TEM 族，多模如实 UNKNOWN；
4. de-embed meta：调用方显式声明的 l_ext_mm 原样记 meta（消费侧走
   core/deembed.deembed_reference_plane），未声明如实 null（铁律 7：
   服务层不发明几何数值）；
5. 预算 = 档数×点频单解（终档可选全扫一次，study 复用 #158）；
   max_rungs<3 降级取阶梯最高档（收敛比较永远取最大两档）。

驱动注入：PortSolveDriver 协议 + SynthPortDriver（合成序列，单测/回放）
+ HfssPortDriver 薄壳（solve_point 真机实现已回填，2026-09-24 HFSS 轨：
LastAdaptive Modal Solution Data 取 Zpi/Zpv/Zvi + S21，#254④ 口径）。
真机发射走脚本对象注入（license solo #246）；JSON 面 port_gate_from_json
"hfss" 仍拒发（真机不做 JSON 远程发射面）。CLI/MCP 后续接薄壳。
"""

from __future__ import annotations

import cmath
import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "FAMILY_LADDERS",
    "FamilyLadder",
    "HfssPortDriver",
    "PortSolveDriver",
    "PortSolvePoint",
    "Rung",
    "SynthPortDriver",
    "family_from_roles",
    "ladder_rungs",
    "port_gate_from_json",
    "run_port_gate",
]


# ═══ 族阶梯表（#254 换族口径 + 官方勘误口径）══════════════════════════════


@dataclass(frozen=True)
class FamilyLadder:
    """一族器件的端口截面阶梯规则（宽度/高度随档单调增）。

    width_mm/height_mm 由 (线宽 w, 基板厚 h) 按族规则精算：
    - multipliers 型：宽 = N×w（N 逐档）、高 = M×h；
    - margins 型（#254 槽线族）：宽 = w+2×margin_w、高 = h+margin_bot+margin_top。
    """

    family: str
    kind: str  # "multipliers" | "margins"
    width_multipliers: tuple[float, ...] = ()
    height_multipliers: tuple[float, ...] = ()
    width_margins_mm: tuple[float, ...] = ()
    height_margins_mm: tuple[tuple[float, float], ...] = ()
    official_note: str = ""

    def rung(self, index: int, w_mm: float, h_mm: float) -> Rung:
        if self.kind == "multipliers":
            width = self.width_multipliers[index] * w_mm
            height = self.height_multipliers[index] * h_mm
        elif self.kind == "margins":
            mw = self.width_margins_mm[index]
            hb, ht = self.height_margins_mm[index]
            width = w_mm + 2.0 * mw
            height = h_mm + hb + ht
        else:
            raise ValueError(f"未知阶梯规则 kind={self.kind!r}")
        return Rung(index=index, port_width_mm=width, port_height_mm=height)

    def n_rungs(self) -> int:
        if self.kind == "multipliers":
            return len(self.width_multipliers)
        return len(self.width_margins_mm)


@dataclass(frozen=True)
class Rung:
    """单档端口截面（mm）。"""

    index: int
    port_width_mm: float
    port_height_mm: float


#: 微带/准 TEM 单模族：3-5-8×w、4×h（下限惯例；官方 8w/10h 防缘耦合口径）
_MICROSTRIP = FamilyLadder(
    family="microstrip",
    kind="multipliers",
    width_multipliers=(3.0, 5.0, 8.0),
    height_multipliers=(4.0, 4.0, 4.0),
    official_note="Ansys 官方口径：端口宽 ≥8×波宽、高 ≥10×h 防端口缘耦合；"
                  "3-5w/4h 为下限惯例（规格书勘误口径，比扩充池引用更准）",
)

#: 槽线/平衡线族（#254）：截面远大于微带惯例（≥±60/∓30mm 量级），否则
#: 默认外框把槽两侧地短接成封闭波导 → 截止倏逝模假数据
_SLOTLINE_BALANCED = FamilyLadder(
    family="slotline_balanced",
    kind="margins",
    width_margins_mm=(20.0, 40.0, 60.0),
    height_margins_mm=((30.0, 30.0), (30.0, 30.0), (30.0, 30.0)),
    official_note="#254：槽线/平衡线仲裁波端口截面 ≥±60/∓30mm 量级"
                  "（对齐 hfss_slotline_arbitration.py 三档实跑口径）",
)

FAMILY_LADDERS: dict[str, FamilyLadder] = {
    "microstrip": _MICROSTRIP,
    "slotline_balanced": _SLOTLINE_BALANCED,
}


def family_from_roles(physics_roles: dict[str, str] | None) -> str:
    """按 physics_roles 值换族查表（#154：角色稳定、参数名不可信）。

    返回 FAMILY_LADDERS 键或 "unknown"（调用方对 unknown 如实 UNKNOWN）。
    """
    roles = {str(v) for v in (physics_roles or {}).values()}
    if "gap_width_mm" in roles:  # 槽缝类：slotline/CPS/Marchand（#254 换族）
        return "slotline_balanced"
    if roles & {"line_width_mm", "shunt_line_width_mm",
                "impedance_line_width_mm"}:
        return "microstrip"
    return "unknown"


def ladder_rungs(
    family: str, w_mm: float, h_mm: float, max_rungs: int = 3,
) -> tuple[list[Rung], FamilyLadder | None]:
    """族阶梯 → 档列表（超预算降级取最高 max_rungs 档）。"""
    ladder = FAMILY_LADDERS.get(family)
    if ladder is None:
        return [], None
    n = ladder.n_rungs()
    take = min(int(max_rungs), n)
    if take < 2:
        return [], ladder  # 至少两档才能做收敛比较
    return [ladder.rung(i, w_mm, h_mm) for i in range(n - take, n)], ladder


# ═══ 驱动协议 + 合成/真机薄壳 ═══════════════════════════════════════════


@dataclass
class PortSolvePoint:
    """单档单频求解读数（LastAdaptive Modal Solution Data）。

    zpi/zpv/zvi 为模阻抗（Ω，复数）；单模准 TEM 族三者应相等且满足
    Zvi=√(Zpi·Zpv) 恒等式（#356⑤，可实测自校）。s21_* 取传输幅相。
    """

    ok: bool
    freq_ghz: float
    zpi_ohm: complex | None = None
    zpv_ohm: complex | None = None
    zvi_ohm: complex | None = None
    s21_db: float | None = None
    s21_deg: float | None = None
    n_modes: int = 1
    passes: int = 0
    delta_s_final: float | None = None
    error: str | None = None


@runtime_checkable
class PortSolveDriver(Protocol):
    """端口收敛阶梯的可注入驱动（合成 fake 与真 HFSS 薄壳同签名）。"""

    def set_variables(self, vars: dict[str, str]) -> None:
        """换档：改端口面尺寸设计变量（HFSS 即 adapter.set_variables）。"""
        ...

    def solve_point(self, freq_ghz: float) -> PortSolvePoint:
        """点频单解并取 LastAdaptive 模阻抗 + S21（便宜，不做全扫）。"""
        ...

    def driver_label(self) -> str: ...


@dataclass
class SynthPortDriver:
    """合成驱动（单测/回放 fixture，engine 标签如实 synthetic）。

    按档序返回预置序列（z0_ohm 逐档、s21_db 逐档），zvi 恒按
    √(zpi·zpv) 精确构造（自校恒等式逐位成立）；zvi_override 用于构造
    自校违例负例。全 None 序列 → 每档 ok=False（驱动失败负例）。
    """

    z0_sequence: Iterable[complex | None] = ()
    s21_db_sequence: Iterable[float | None] = ()
    n_modes: int = 1
    zvi_override: dict[int, complex] = field(default_factory=dict)
    vars_log: list[dict[str, str]] = field(default_factory=list)
    _i: int = 0

    def set_variables(self, vars: dict[str, str]) -> None:
        self.vars_log.append(dict(vars))

    def solve_point(self, freq_ghz: float) -> PortSolvePoint:
        i = self._i
        self._i += 1
        z0_list = list(self.z0_sequence)
        s21_list = list(self.s21_db_sequence)
        z0 = z0_list[i] if i < len(z0_list) else None
        s21 = s21_list[i] if i < len(s21_list) else None
        if z0 is None:
            return PortSolvePoint(ok=False, freq_ghz=freq_ghz,
                                  n_modes=self.n_modes, error="合成驱动无数据")
        z0c = complex(z0)
        # Zvi=√(Zpi·Zpv) 精确构造（与 _zvi_self_check 同式 → 自校逐位=0）
        zvi = self.zvi_override.get(i, (z0c * z0c) ** 0.5)
        # 单模准 TEM 惯例：三阻抗相等，Zvi=√(Zpi·Zpv) 逐位成立
        return PortSolvePoint(
            ok=True, freq_ghz=freq_ghz, zpi_ohm=z0c, zpv_ohm=z0c, zvi_ohm=zvi,
            s21_db=(float(s21) if s21 is not None else None),
            s21_deg=None, n_modes=self.n_modes)

    def driver_label(self) -> str:
        return "synthetic"


def _extract_modal_port_data(
    hfss: Any, setup_name: str, port_names: tuple[str, ...],
    mode_index: int = 1,
) -> dict[str, Any]:
    """LastAdaptive Modal Solution Data 取数（#254④：Z0 按此面取，CPS/槽线
    仲裁先例同款）。返回 port_data[端口][类别]（复数）+ s_data + n_modes。

    量名解析（原样保留类别键）：Zo/Zpi/Zpv/Zvi/Gamma(P[:mode])、S(Pa,Pb)
    （HFSS 惯例 S(接收, 激励)；多模带 ":m" 后缀，只取 mode_index 模）。
    """
    import re

    import numpy as np

    sol_name = f"{setup_name} : LastAdaptive"
    out: dict[str, Any] = {
        "solution": sol_name, "categories": [], "quantities": {},
        "errors": [], "n_points": None,
        "port_data": {pn: {} for pn in port_names}, "s_data": {},
        "n_modes": {pn: 1 for pn in port_names},
    }
    cats = hfss.post.available_quantities_categories(
        report_category="Modal Solution Data", solution=sol_name)
    out["categories"] = sorted({str(c) for c in (cats or [])})
    # 2025.1 实测类别面（df6 首跑探针 c4_quantity_probe.json）：Gamma/
    # Port Zo/S Parameter——无 Zpi/Zpv/Zvi 独立类别（三定义经端口 CharImp
    # 换定义子解读取，见 HfssPortDriver.char_imp_passes）
    wanted = [c for c in out["categories"]
              if c in ("Gamma", "Port Zo", "S Parameter")]
    cat_prefix = {"Gamma": "Gamma", "Port Zo": "Zo", "S Parameter": "S"}
    pat = re.compile(r"^(?P<cat>[A-Za-z]+)\((?P<args>[^)]*)\)$")
    matched: dict[str, dict[str, Any]] = {}
    for cat in wanted:
        try:
            qs = hfss.post.available_report_quantities(
                report_category="Modal Solution Data", solution=sol_name,
                quantities_category=cat)
        except Exception as exc:
            out["errors"].append(f"{cat}: quantities 枚举失败 {exc!r}")
            continue
        for q in list(qs or []):
            m = pat.match(str(q))
            if m is None or m.group("cat") != cat_prefix[cat]:
                continue
            args = [a.strip() for a in m.group("args").split(",")]
            parsed: list[tuple[str, int]] = []
            for a in args:
                pn, _, ms = a.partition(":")
                parsed.append((pn, int(ms) if ms else 1))
            prefix = cat_prefix[cat]  # 数据键=量名前缀（Zo/Gamma/S）
            if cat != "S Parameter":
                # n_modes：全量计数该端口出现过的模后缀（不过滤，多模如实）
                for pn, mode in parsed:
                    if pn in out["n_modes"]:
                        out["n_modes"][pn] = max(out["n_modes"][pn], mode)
            if any(mode != int(mode_index) for _, mode in parsed):
                continue
            names = tuple(pn for pn, _ in parsed)
            if prefix == "S":
                if len(names) == 2 and names[0] in port_names \
                        and names[1] in port_names:
                    matched[str(q)] = {"cat": prefix, "key": names}
            elif len(names) == 1 and names[0] in port_names:
                matched[str(q)] = {"cat": prefix, "key": names[0]}
    out["quantities"] = {q: v["cat"] for q, v in matched.items()}
    if not matched:
        out["errors"].append("LastAdaptive 无可解析量（端口名不匹配或类别缺失）")
        return out
    sol = hfss.post.get_solution_data(
        expressions=list(matched), setup_sweep_name=sol_name,
        report_category="Modal Solution Data")
    if sol is None:
        out["errors"].append("get_solution_data None")
        return out
    for q, spec in matched.items():
        try:
            _x, re_ = sol.get_expression_data(q, formula="real")
            _x, im_ = sol.get_expression_data(q, formula="imag")
            n = min(len(np.ravel(re_)), len(np.ravel(im_)))
            out["n_points"] = n if out["n_points"] is None else min(
                out["n_points"], n)
            val = complex(float(np.ravel(re_)[0]), float(np.ravel(im_)[0]))
        except Exception as exc:
            out["errors"].append(f"{q}: 读数失败 {exc!r}")
            continue
        if spec["cat"] == "S":
            out["s_data"][spec["key"]] = val
        else:
            out["port_data"][spec["key"]][spec["cat"]] = val
    return out


class HfssPortDriver:
    """真机 HFSS 驱动薄壳（solve_point 真机实现已回填，2026-09-24 HFSS 轨）。

    用法（真机发射路径）::

        from rfauto.adapters.hfss_adapter import HfssAdapter
        adapter = HfssAdapter()
        adapter.connect({"desktop_version": "2025.1", "non_graphical": True})
        adapter.open_or_create_project(project_path, design_name)
        driver = HfssPortDriver(adapter, setup_name="Setup1",
                                port_name="P1", other_port_name="P2")
        report = run_port_gate(driver, template=..., physics_roles=...,
                               line_width_mm=..., substrate_h_mm=...,
                               probe_freq_ghz=...)

    solve_point：单频 setup（Frequency=探针点、MaxDeltaS/MaximumPasses 按
    预声明）→ analyze（watchdog 超时保护）→ LastAdaptive Modal Solution
    Data 取 Zpi/Zpv/Zvi + S(P2,P1)（#254④：Z0 按 Modal Solution Data 取，
    Touchstone 注释恒写 Zpi 不可用）；passes/final_delta_s 从 setup profile
    提取（#335 收敛旁证）。占 HFSS license 席位，与 OE 轨互斥（#246 solo
    单飞）；发射前孤儿清场/finally release_desktop（#245/#265）由调用方
    脚本承担。JSON 面（port_gate_from_json "hfss"）仍不发射——真机发射走
    脚本对象注入。
    """

    def __init__(self, adapter: Any, setup_name: str = "Setup1",
                 port_index: int = 1, mode_index: int = 1, *,
                 port_name: str = "P1", other_port_name: str = "P2",
                 max_delta_s: float = 0.02, max_passes: int = 12,
                 solve_timeout_s: float = 900.0,
                 char_imp_passes: tuple[str, ...] = ("Zpi", "Zpv", "Zvi")
                 ) -> None:
        self.adapter = adapter
        self.setup_name = setup_name
        self.port_index = int(port_index)
        self.mode_index = int(mode_index)
        self.port_name = str(port_name)
        self.other_port_name = str(other_port_name)
        self.max_delta_s = float(max_delta_s)
        self.max_passes = int(max_passes)
        self.solve_timeout_s = float(solve_timeout_s)
        self.char_imp_passes = tuple(str(c) for c in char_imp_passes)

    def set_variables(self, vars: dict[str, str]) -> None:
        self.adapter.set_variables(vars)

    @staticmethod
    def _set_ports_char_imp(hfss: Any, port_names: tuple[str, ...],
                            char_imp: str, mode_index: int) -> None:
        """换端口 CharImp 定义（边界 props Modes.ModeN.CharImp + update）。"""
        targets = {str(n) for n in port_names}
        hit: set[str] = set()
        for b in (getattr(hfss, "boundaries", None) or []):
            nm = str(getattr(b, "name", ""))
            if nm not in targets:
                continue
            modes = (getattr(b, "props", None) or {}).get("Modes") or {}
            mode = modes.get(f"Mode{int(mode_index)}")
            if mode is None:
                raise RuntimeError(
                    f"端口 {nm} 缺 Mode{mode_index} props（CharImp 换档失败）")
            mode["CharImp"] = str(char_imp)
            if not b.update():
                raise RuntimeError(f"端口 {nm} CharImp→{char_imp} 更新失败")
            hit.add(nm)
        missing = targets - hit
        if missing:
            raise RuntimeError(f"端口边界未找到: {sorted(missing)}")

    def solve_point(self, freq_ghz: float) -> PortSolvePoint:
        """点频单解并取 LastAdaptive 模阻抗 + S21（真机实现）。

        CharImp 三定义子解（Zpi/Zpv/Zvi 逐一定义重解读 Port Zo，df6 v2
        口径：Modal 面无三定义类别，renormalize=False 下 Port Zo 按
        CharImp 返回真模阻抗）——Zvi=√(Zpi·Zpv) 恒等式因此可实测自校。
        """
        from rfauto.infra.desktop_guard import run_with_watchdog

        session = getattr(self.adapter, "session", None)
        hfss = getattr(session, "hfss", None)
        if hfss is None:
            raise RuntimeError(
                "HfssPortDriver: adapter 会话未连接（先 connect + "
                "open_or_create_project 再构造 driver）")
        setup = hfss.get_setup(self.setup_name)
        setup.props["Frequency"] = f"{float(freq_ghz):.6f}GHz"
        setup.props["MaxDeltaS"] = self.max_delta_s
        setup.props["MaximumPasses"] = self.max_passes
        setup.update()
        passes, delta_s = None, None
        zo_by_def: dict[str, complex] = {}
        ext_last = None
        err: str | None = None
        try:
            from rfauto.adapters.hfss_adapter import HfssAdapter
            passes, delta_s = HfssAdapter._extract_convergence(setup)
        except Exception:
            pass  # 收敛元数据缺失不阻断取数（#105 best-effort）
        try:
            for ci in self.char_imp_passes:
                self._set_ports_char_imp(
                    hfss, (self.port_name, self.other_port_name), ci,
                    self.mode_index)
                run_with_watchdog(
                    lambda: hfss.analyze(setup=self.setup_name),
                    timeout_s=self.solve_timeout_s,
                    what=f"HfssPortDriver.solve_point@{freq_ghz}GHz[{ci}]")
                ext = _extract_modal_port_data(
                    hfss, self.setup_name,
                    (self.port_name, self.other_port_name),
                    mode_index=self.mode_index)
                ext_last = ext
                if ext["errors"]:
                    err = "; ".join(ext["errors"])
                zo = ext["port_data"].get(self.port_name, {}).get("Zo")
                if zo is not None:
                    zo_by_def[ci] = zo
        except Exception as exc:
            return PortSolvePoint(
                ok=False, freq_ghz=float(freq_ghz), passes=passes,
                delta_s_final=delta_s,
                error=f"Modal Solution Data 提取失败: {exc!r}")
        zpi = zo_by_def.get("Zpi")
        zpv = zo_by_def.get("Zpv")
        zvi = zo_by_def.get("Zvi")
        if not zo_by_def:
            return PortSolvePoint(
                ok=False, freq_ghz=float(freq_ghz), passes=passes,
                delta_s_final=delta_s,
                error=(err or "LastAdaptive 无 Port Zo 读数")
                + f"（类别={ext_last['categories'] if ext_last else 'n/a'}）")
        s21 = None
        if ext_last is not None:
            s21 = (ext_last["s_data"].get(
                (self.other_port_name, self.port_name))
                or ext_last["s_data"].get(
                    (self.port_name, self.other_port_name)))
        s21_db = (20.0 * math.log10(abs(s21))) if s21 is not None else None
        s21_deg = math.degrees(cmath.phase(s21)) if s21 is not None else None
        n_modes = (int(ext_last["n_modes"].get(self.port_name, 1))
                   if ext_last is not None else 1)
        return PortSolvePoint(
            ok=True, freq_ghz=float(freq_ghz), zpi_ohm=zpi, zpv_ohm=zpv,
            zvi_ohm=zvi, s21_db=s21_db, s21_deg=s21_deg,
            n_modes=n_modes, passes=passes, delta_s_final=delta_s,
            error=err)

    def driver_label(self) -> str:
        return "hfss"


# ═══ 阶梯编排 + 判据 ═════════════════════════════════════════════════════

#: 判据阈值（规格书 §16.1 原文；改阈值=改判据，须过判据预声明）
S21_TOL_DB = 0.05
Z0_TOL_REL = 0.02
ZVI_SELF_CHECK_TOL = 1e-6


def _zvi_self_check(point: PortSolvePoint) -> dict[str, Any]:
    """|Zvi−√(Zpi·Zpv)|/|Zvi| ≤ 1e-6（#356⑤ 恒等式实测自校）。"""
    if (point.zvi_ohm is None or point.zpi_ohm is None
            or point.zpv_ohm is None):
        return {"status": "UNKNOWN", "reason": "Zpi/Zpv/Zvi 缺失"}
    zvi = complex(point.zvi_ohm)
    if abs(zvi) == 0.0:
        return {"status": "FAIL", "rel_err": None,
                "reason": "Zvi=0 非物理（端口无能量读数）"}
    expected = (point.zpi_ohm * point.zpv_ohm) ** 0.5  # 主支 √(Zpi·Zpv)
    rel = abs(zvi - expected) / abs(zvi)
    return {"status": "PASS" if rel <= ZVI_SELF_CHECK_TOL else "FAIL",
            "rel_err": rel, "zvi_expected": _fmt_complex(expected)}


def _fmt_complex(z: complex | float | None) -> Any:
    if z is None:
        return None
    z = complex(z)
    return {"re": round(z.real, 9), "im": round(z.imag, 9)}


def run_port_gate(
    driver: PortSolveDriver,
    *,
    line_width_mm: float,
    substrate_h_mm: float,
    probe_freq_ghz: float,
    template: str = "",
    physics_roles: dict[str, str] | None = None,
    family: str | None = None,
    l_ext_mm: float | None = None,
    port_width_var: str = "port_width",
    port_height_var: str = "port_height",
    full_sweep_final: bool = False,
    max_rungs: int = 3,
    s21_tol_db: float = S21_TOL_DB,
    z0_tol_rel: float = Z0_TOL_REL,
) -> dict[str, Any]:
    """端口尺寸收敛阶梯编排（JSON 进出）。

    每档 set_variables 换端口面尺寸 → driver.solve_point(点频) → 记录；
    判据只看最大两档；返回 dict（JSON 安全）。
    """
    fam = str(family) if family else family_from_roles(physics_roles)
    base: dict[str, Any] = {
        "ok": True,
        "gate": "port_size_convergence",
        "template": template,
        "family": fam,
        "probe_freq_ghz": float(probe_freq_ghz),
        "line_width_mm": float(line_width_mm),
        "substrate_h_mm": float(substrate_h_mm),
        "thresholds": {"s21_tol_db": s21_tol_db, "z0_tol_rel": z0_tol_rel,
                       "zvi_self_check_tol": ZVI_SELF_CHECK_TOL},
        "reasons": [],
        "driver": driver.driver_label(),
    }

    if fam not in FAMILY_LADDERS:
        return {**base, "ok": True, "verdict": "UNKNOWN",
                "reasons": [f"physics_roles 无法识别端口族: {fam!r}，"
                            "不猜阶梯（#154 角色口径）"]}

    rungs, ladder = ladder_rungs(fam, float(line_width_mm),
                                 float(substrate_h_mm), max_rungs=max_rungs)
    if not rungs or ladder is None:
        return {**base, "ok": True, "verdict": "UNKNOWN",
                "reasons": ["阶梯档数不足两档，无法做收敛比较"]}

    base["official_note"] = ladder.official_note

    # 预算：档数×点频单解；终档可选全扫一次（本函数只计数不执行全扫——
    # 全扫走既有 solve/sparams 面由调用方复用 #158 study）
    solves_total = len(rungs) + (1 if full_sweep_final else 0)

    rung_reports: list[dict[str, Any]] = []
    for rung in rungs:
        vars_applied = {
            port_width_var: f"{rung.port_width_mm:.6f}mm",
            port_height_var: f"{rung.port_height_mm:.6f}mm",
        }
        driver.set_variables(vars_applied)
        point = driver.solve_point(float(probe_freq_ghz))
        if not point.ok:
            rung_reports.append({
                "index": rung.index,
                "port_width_mm": round(rung.port_width_mm, 6),
                "port_height_mm": round(rung.port_height_mm, 6),
                "vars": vars_applied,
                "point": {"ok": False, "error": point.error},
                "zvi_self_check": {"status": "UNKNOWN",
                                   "reason": "求解失败无读数"},
            })
            continue
        multi_mode = point.n_modes > 1
        rung_reports.append({
            "index": rung.index,
            "port_width_mm": round(rung.port_width_mm, 6),
            "port_height_mm": round(rung.port_height_mm, 6),
            "vars": vars_applied,
            "point": {
                "ok": True,
                "zpi_ohm": _fmt_complex(point.zpi_ohm),
                "zpv_ohm": _fmt_complex(point.zpv_ohm),
                "zvi_ohm": _fmt_complex(point.zvi_ohm),
                "s21_db": point.s21_db,
                "s21_deg": point.s21_deg,
                "n_modes": point.n_modes,
                "passes": point.passes,
                "delta_s_final": point.delta_s_final,
                "multi_mode": multi_mode,
            },
            "zvi_self_check": _zvi_self_check(point),
        })

    # ── 判据收集：reasons 全量如实记录，verdict 末尾按 UNKNOWN > FAIL > PASS 定 ──
    reasons: list[str] = []
    unknown = False
    failed = False

    # 多模：v1 只支持单模准 TEM 族（规格书 §16.1 风险条目）
    if any(r.get("point", {}).get("multi_mode") for r in rung_reports):
        reasons.append("检测到多模端口（n_modes>1）：v1 只支持单模准 TEM 族")
        unknown = True

    # 驱动失败/缺数据：UNKNOWN（无数值证据不判 FAIL）
    failed_rungs = [r for r in rung_reports if not r.get("point", {}).get("ok")]
    if failed_rungs:
        reasons.append(
            f"{len(failed_rungs)} 档求解失败/缺数据（首档 "
            f"#{failed_rungs[0]['index']}: {failed_rungs[0]['point'].get('error')}），"
            "收敛无法判定")
        unknown = True
        failed = True

    # Zvi 自校：比较两档必须全过；违例=模数据病态（#307 族）
    zvi_violated = False
    zvi_bad = [r for r in rung_reports[-2:]
               if r["zvi_self_check"].get("status") == "FAIL"]
    if zvi_bad:
        rel = zvi_bad[0]["zvi_self_check"].get("rel_err")
        reasons.append(
            f"Zvi 自校恒等式违反（|Zvi−√(Zpi·Zpv)|/|Zvi|={rel} > "
            f"{ZVI_SELF_CHECK_TOL}，模数据病态/#307 族）")
        zvi_violated = True

    # 收敛判据：末两档 |ΔS21| ≤ tol 且 |ΔZ0/Z0| ≤ tol
    checks: dict[str, Any] = {}
    s21_violated = False
    z0_violated = False
    incomplete = False
    if len(rung_reports) >= 2 and not failed:
        last, prev = rung_reports[-1], rung_reports[-2]
        s21_a, s21_b = prev["point"].get("s21_db"), last["point"].get("s21_db")
        z0_a = _z0_of(prev["point"])
        z0_b = _z0_of(last["point"])
        if s21_a is not None and s21_b is not None:
            step = abs(s21_b - s21_a)
            checks["s21_step_db"] = step
            if step > s21_tol_db:
                reasons.append(
                    f"末两档 |ΔS21|={step:.4f}dB > {s21_tol_db}dB：端口尺寸"
                    "未收敛（截面过小族/#254 口径）")
                s21_violated = True
        else:
            checks["s21_step_db"] = None
            reasons.append("S21 读数缺失，收敛无法判定")
            incomplete = True
        if z0_a is not None and z0_b is not None and z0_b != 0:
            rel = abs(z0_b - z0_a) / abs(z0_b)
            checks["z0_step_rel"] = rel
            checks["z0_ohm_last"] = z0_b
            if rel > z0_tol_rel:
                reasons.append(
                    f"末两档 |ΔZ0/Z0|={rel:.4%} > {z0_tol_rel:.0%}：阻抗未收敛")
                z0_violated = True
        elif z0_a is not None and z0_b is not None and z0_b == 0:
            checks["z0_step_rel"] = None
            reasons.append("Z0=0 非物理，收敛无法判定")
            incomplete = True
        else:
            checks["z0_step_rel"] = None
            reasons.append("Z0 读数缺失，收敛无法判定")
            incomplete = True

    if unknown or incomplete:
        verdict = "UNKNOWN"  # 数据不可信/不完整：不凑 FAIL 也不凑 PASS（#122）
    elif zvi_violated or s21_violated or z0_violated:
        verdict = "FAIL"  # 有数值证据
    else:
        verdict = "PASS"

    meta_deembed = {
        "l_ext_mm": (float(l_ext_mm) if l_ext_mm is not None else None),
        "method": "rfauto.core.deembed.deembed_reference_plane",
        "note": "端口面外延由调用方声明（建模脚本几何决定）；消费侧按此去嵌；"
                "null=未声明，去嵌不可用（服务层不发明几何数值）",
    }

    return {
        **base,
        "verdict": verdict,
        "reasons": reasons,
        "rungs": rung_reports,
        "checks": checks,
        "budget": {
            "n_rungs": len(rungs),
            "solves_total": solves_total,
            "full_sweep_final": bool(full_sweep_final),
            "study_note": "全扫只终档一次（study 复用 #158）；前置门=档数×点频单解",
        },
        "deembed": meta_deembed,
    }


def _z0_of(point_doc: dict[str, Any]) -> float | None:
    """Z0 取 Zvi（模阻抗自校过才可信；缺失如实 None）。"""
    zvi = point_doc.get("zvi_ohm")
    if not zvi:
        return None
    return abs(complex(zvi["re"], zvi["im"]))


def port_gate_from_json(payload: dict[str, Any]) -> dict[str, Any]:
    """JSON 进出薄编排（CLI/MCP 接此壳）。

    payload.driver:
        - "synthetic"（缺省）：合成序列回放/单测，z0_ohm/s21_db 序列必传；
        - "hfss"：真机驱动薄壳——本批不发射真机，如实 UNKNOWN 拒发。
    """
    kind = str((payload or {}).get("driver", "synthetic"))
    if kind == "hfss":
        return {
            "ok": True, "gate": "port_size_convergence",
            "verdict": "UNKNOWN",
            "reasons": ["hfss 驱动 JSON 面不发射（真机发射走脚本对象注入："
                        "HfssPortDriver 构造 + run_port_gate 对象面；"
                        "license solo #246）"],
        }
    if kind != "synthetic":
        return {"ok": False, "gate": "port_size_convergence",
                "verdict": "UNKNOWN",
                "reasons": [f"未知 driver: {kind!r}（可用 synthetic|hfss）"]}
    driver = SynthPortDriver(
        z0_sequence=payload.get("z0_ohm_sequence") or [],
        s21_db_sequence=payload.get("s21_db_sequence") or [],
        n_modes=int(payload.get("n_modes", 1)),
    )
    return run_port_gate(
        driver,
        line_width_mm=float(payload["line_width_mm"]),
        substrate_h_mm=float(payload["substrate_h_mm"]),
        probe_freq_ghz=float(payload["probe_freq_ghz"]),
        template=str(payload.get("template", "")),
        physics_roles=payload.get("physics_roles") or None,
        family=payload.get("family"),
        l_ext_mm=payload.get("l_ext_mm"),
        full_sweep_final=bool(payload.get("full_sweep_final", False)),
        max_rungs=int(payload.get("max_rungs", 3)),
    )
