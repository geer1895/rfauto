"""DP-10 超表面/FSS 离线内核（P1：纯函数零 IO，规格 规格深案 §DP-10）。

四个子面（判据预声明 runs/df6_dp10ms/criteria.md，实现前冻结）：

1. LUT schema（MetasurfaceLUT）：单元波导模拟器扫频产物的统一载体，
   JSON（元数据+数组）+ CSV（长表）双载体互转；interp=pchip；
   run_dir provenance（#320 口径：真机行必须带产物目录指针，合成 LUT
   置空串并标 origin="synthetic"）。
2. 布局综合闭式（确定性内核， 硬规则 7——物理数字只出在这里）：
   - 反射阵（点馈）：φ_mn = k0·(R_mn − r_mn·û_beam) mod 2π
     （Huang-Encinar《Reflectarray Antennas》空间相位延迟式；
     R_mn=馈相心到单元距离）；
   - 透射阵（点馈，MM-6）：φ_mn = k0·(|F−r| − r·û_out) mod 2π（与反射阵
     同形——透射几何=反射几何对口径面的镜像，路径延迟账相同；差异=
     域守卫 û_out[2]<0 + LUT 消费走 s21 载体）；
   - 平面波照明（反射或透射/编码面统一）：φ_mn = k0·(û_in − û_out)·r_mn
     mod 2π（光栅条件；规格书透射式 φ_mn=−k0(r·û0) 是其法向入射特例，
     相位集合 mod 2π 等价；透射阵专用档 required_phase_transmitarray_
     plane_wave 另设——出射/照明方向取物理传播方向并设域守卫）；
   - 逐单元 LUT 最近邻反查（圆周距离）+ b-bit 相位量化（取整到 2π/2^b 栅格）。
3. 量化口径：σ²=(π/2^b)²/3（副瓣基底）；增益损失 10·log10(sinc²(1/2^b))
   （均匀量化误差复相干因子 E[e^{jε}]² 的精确期望；文献带 1/2/3-bit≈
   3/0.6/0.2dB，J5=±1dB 带，两口径差异如实记档）。
4. Luukkonen/Costa EC 闭式（FSS 屏带心初值，arXiv:0705.3548 eq.3/4 +
   TM 栅阻抗换算）：贴片阵 C=(2D/π)·ε0·εeff·ln(csc(πg/2D))、线网
   L=μ0·D/(2π)·ln(csc(πw/2D))、εeff=(1+εr)/2；介质 TL+栅阻抗 ABCD 级联
   S 参数；JC 缝（带通口径）=shunt 支路 LC 并联（f0 呈开路→全透）。

名义尺寸闭式（#252/#1c，渲染与 TEMPLATE_NOMINAL 的单源）也收在本模块：
ms_patch Hammerstad εeff 不动点、ms_cross/ms_jcross λg 口径。本模块零
文件读写零环境依赖——真机 LUT 的 ingest 由 service 层另接（P3）。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, fields
from typing import Any, ClassVar

import numpy as np
from scipy.interpolate import PchipInterpolator

#: LUT schema 版本（recipe_version/schema_version 双版本语义先例 #106：
#: 这是 LUT 载体版本，不是插件参数版本）。v2（MM-3，2026-10-02，规格
#: 规格深案 §C-2）：追加 s21_db/s21_phase_deg
#: 透射载体（GSTC 对拍通道）；from_dict/from_csv 兼容读 v1 旧载体
#: （s21=None），只追加不改既有字段语义。
LUT_SCHEMA = "metasurface_lut/v2"
#: v1 旧载体版本串（只读兼容用；写出恒为 v2）
_LUT_SCHEMA_V1 = "metasurface_lut/v1"
#: 相位插值口径（冻结于 criteria §1b）
LUT_INTERP = "pchip"
#: 真空波阻抗（方胞波导模拟器 TEM 口径的匹配参考，Ω）
ETA0_OHM = 376.730313668
C0_M_S = 299792458.0
EPS0_F_M = 8.854187817e-12
MU0_H_M = 4e-7 * math.pi

_J1B_PHASE_DEG_MAX = 10.0
_J1B_AMP_DB_MAX = 0.5
_J1_COVERAGE_DEG_MIN = 300.0


# ─── LUT schema ──────────────────────────────────────────────────────────────


@dataclass
class MetasurfaceLUT:
    """单元 LUT：cell_id/f0/substrate/params/provenance/freq 网格/|S|dB+解缠相位。

    数组形状统一 (n_sweep, n_freq)：s11_db=|S11| dB、s11_phase_deg=解缠
    相位（度，np.unwrap 口径）。v2 追加透射载体 s21_db/s21_phase_deg
    （同形状，可 None=v1 旧行未采集透射——GSTC 对拍通道消费，MM-3）。
    sweep_values 严格升序；interp=pchip。
    存储相位可能含 px 轴 ±360° 分支切割跳变（逐行频轴解缠的伪象，T13
    实证）——覆盖/插值/反查一律走本模块圆周原语（arc_coverage_deg/
    unwrap_sweep_axis_deg/lut_lookup_phase），禁对存储列直接 max−min 或
    差值插值。
    """

    cell_id: str
    f0_ghz: float
    substrate_key: str
    sweep_key: str
    sweep_values: np.ndarray
    freq_ghz: np.ndarray
    s11_db: np.ndarray
    s11_phase_deg: np.ndarray
    params: dict[str, Any] = field(default_factory=dict)
    run_dir: str = ""
    origin: str = "synthetic"
    validity: dict[str, Any] = field(default_factory=dict)
    gate: dict[str, Any] = field(default_factory=dict)
    # v2 追加（MM-3 §C-2）：透射载体，None=v1 旧行（兼容读，#106）；
    # 必须成对给出（validate 裁决），形状=(n_sweep, n_freq) 同 s11
    s21_db: np.ndarray | None = None
    s21_phase_deg: np.ndarray | None = None

    def __post_init__(self) -> None:
        self.sweep_values = np.asarray(self.sweep_values, dtype=float)
        self.freq_ghz = np.asarray(self.freq_ghz, dtype=float)
        self.s11_db = np.asarray(self.s11_db, dtype=float)
        self.s11_phase_deg = np.asarray(self.s11_phase_deg, dtype=float)
        if self.s21_db is not None:
            self.s21_db = np.asarray(self.s21_db, dtype=float)
        if self.s21_phase_deg is not None:
            self.s21_phase_deg = np.asarray(self.s21_phase_deg, dtype=float)

    # ── 校验 ──
    def validate(self) -> list[str]:
        """schema 校验，返回问题清单（空=合格）；不抛错由调用方裁决。"""
        problems: list[str] = []
        if not self.cell_id:
            problems.append("cell_id 为空")
        if self.sweep_values.ndim != 1 or self.sweep_values.size < 2:
            problems.append("sweep_values 需 ≥2 个的一维升序数组")
        elif bool(np.any(np.diff(self.sweep_values) <= 0)):
            problems.append("sweep_values 非严格升序")
        if self.freq_ghz.ndim != 1 or self.freq_ghz.size < 3:
            problems.append("freq_ghz 需 ≥3 个频点（pchip 需要区间内点）")
        shape = (self.sweep_values.size, self.freq_ghz.size)
        if self.s11_db.shape != shape:
            problems.append(f"s11_db 形状 {self.s11_db.shape} != {shape}")
        if self.s11_phase_deg.shape != shape:
            problems.append(f"s11_phase_deg 形状 {self.s11_phase_deg.shape} != {shape}")
        # v2：透射载体成对出现且同形状（None=v1 旧行合法）
        if (self.s21_db is None) != (self.s21_phase_deg is None):
            problems.append("s21_db/s21_phase_deg 须成对给出（v2 载体）")
        if self.s21_db is not None and self.s21_db.shape != shape:
            problems.append(f"s21_db 形状 {self.s21_db.shape} != {shape}")
        if self.s21_phase_deg is not None and self.s21_phase_deg.shape != shape:
            problems.append(f"s21_phase_deg 形状 {self.s21_phase_deg.shape} != {shape}")
        if self.interp != LUT_INTERP:
            problems.append(f"interp={self.interp!r} != {LUT_INTERP!r}")
        if self.origin not in ("synthetic", "openems_wg_sim", "hfss_floquet"):
            problems.append(f"origin={self.origin!r} 非法")
        if self.origin != "synthetic" and not self.run_dir:
            # #320：真机行必须带产物目录 provenance
            problems.append("非合成 LUT 缺 run_dir provenance")
        return problems

    @property
    def interp(self) -> str:
        return LUT_INTERP

    # ── JSON 载体 ──
    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"schema": LUT_SCHEMA}
        for f in fields(self):
            v = getattr(self, f.name)
            d[f.name] = v.tolist() if isinstance(v, np.ndarray) else v
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=1, sort_keys=True)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> MetasurfaceLUT:
        known = {f.name for f in fields(cls)}
        missing = known - set(d) - {"s21_db", "s21_phase_deg"}
        if missing:
            raise ValueError(f"LUT dict 缺字段 {sorted(missing)}")
        extra = set(d) - known - {"schema"}
        if extra:
            raise ValueError(f"LUT dict 多余字段 {sorted(extra)}")
        # #106 v1→v2 兼容：v1 旧载体（无 s21 字段）合法读入 → s21=None；
        # 未知版本串仍显式拒绝
        if d.get("schema") not in (LUT_SCHEMA, _LUT_SCHEMA_V1):
            raise ValueError(
                f"schema={d.get('schema')!r} 不在 "
                f"({LUT_SCHEMA!r}, {_LUT_SCHEMA_V1!r}) 兼容集")
        s21_db = d.get("s21_db")
        s21_ph = d.get("s21_phase_deg")
        return cls(
            cell_id=d["cell_id"],
            f0_ghz=float(d["f0_ghz"]),
            substrate_key=str(d["substrate_key"]),
            sweep_key=str(d["sweep_key"]),
            sweep_values=np.asarray(d["sweep_values"], dtype=float),
            freq_ghz=np.asarray(d["freq_ghz"], dtype=float),
            s11_db=np.asarray(d["s11_db"], dtype=float),
            s11_phase_deg=np.asarray(d["s11_phase_deg"], dtype=float),
            params=dict(d.get("params") or {}),
            run_dir=str(d.get("run_dir") or ""),
            origin=str(d.get("origin") or "synthetic"),
            validity=dict(d.get("validity") or {}),
            gate=dict(d.get("gate") or {}),
            s21_db=None if s21_db is None else np.asarray(s21_db, dtype=float),
            s21_phase_deg=None if s21_ph is None else np.asarray(s21_ph, dtype=float),
        )

    @classmethod
    def from_json(cls, text: str) -> MetasurfaceLUT:
        return cls.from_dict(json.loads(text))

    # ── CSV 长表载体（# key=value 注释头 + sweep,freq,db,phase 列；
    #    v2 有 s21 载体时为 6 列，无 s21（v1 旧行）保持 4 列旧格式）──
    _CSV_BASE_HEADER: ClassVar[list[str]] = [
        "sweep_value", "freq_ghz", "s11_db", "s11_phase_deg"]
    _CSV_S21_HEADER: ClassVar[list[str]] = ["s21_db", "s21_phase_deg"]

    def to_csv(self) -> str:
        head = "#" + json.dumps(self.to_dict(), ensure_ascii=False,
                                sort_keys=True) + "\n"
        has_s21 = self.s21_db is not None
        cols = self._CSV_BASE_HEADER + (self._CSV_S21_HEADER if has_s21 else [])
        rows = [",".join(cols)]
        for i, sv in enumerate(self.sweep_values):
            for j, fv in enumerate(self.freq_ghz):
                vals = [f"{float(sv)!r}", f"{float(fv)!r}",
                        f"{float(self.s11_db[i, j])!r}",
                        f"{float(self.s11_phase_deg[i, j])!r}"]
                if has_s21:
                    vals += [f"{float(self.s21_db[i, j])!r}",
                             f"{float(self.s21_phase_deg[i, j])!r}"]
                rows.append(",".join(vals))
        return head + "\n".join(rows) + "\n"

    @classmethod
    def from_csv(cls, text: str) -> MetasurfaceLUT:
        lines = text.strip().splitlines()
        if not lines or not lines[0].startswith("#"):
            raise ValueError("CSV 缺 # 注释头（双载体约定）")
        d = json.loads(lines[0][1:])
        header = lines[1].split(",")
        if header == cls._CSV_BASE_HEADER:
            pass  # v1 4 列旧格式：s21 载体缺席，from_dict 兼容路径
        elif header == cls._CSV_BASE_HEADER + cls._CSV_S21_HEADER:
            pass  # v2 6 列
        else:
            raise ValueError(f"CSV 列头漂移: {header}")
        n_col = len(header)
        body = [ln.split(",") for ln in lines[2:] if ln.strip()]
        for r in body:
            if len(r) != n_col:
                raise ValueError(f"CSV 行列数 {len(r)} != 表头 {n_col}")
        sv = sorted({float(r[0]) for r in body})
        fv = sorted({float(r[1]) for r in body})
        db = np.empty((len(sv), len(fv)))
        ph = np.empty((len(sv), len(fv)))
        si = {v: i for i, v in enumerate(sv)}
        fi = {v: i for i, v in enumerate(fv)}
        t_db = np.empty((len(sv), len(fv))) if n_col == 6 else None
        t_ph = np.empty((len(sv), len(fv))) if n_col == 6 else None
        for r in body:
            i, j = si[float(r[0])], fi[float(r[1])]
            db[i, j] = float(r[2])
            ph[i, j] = float(r[3])
            if n_col == 6:
                t_db[i, j] = float(r[4])
                t_ph[i, j] = float(r[5])
        d["sweep_values"], d["freq_ghz"], d["s11_db"], d["s11_phase_deg"] = (
            sv, fv, db, ph)
        if n_col == 6:
            d["s21_db"], d["s21_phase_deg"] = t_db, t_ph
        return cls.from_dict(d)

    # ── 判据面 ──
    def phase_coverage_deg(self) -> float:
        """f0（取最近频点）处扫描的真实圆周相位覆盖（度，分支切割免疫）。

        criteria §1c 冻结原文为「max−min，解缠域」——T13 实证
        （runs/dp10_j2j3/launch_ready.md §1.1）该口径对 launch_sweep.load_lut
        逐行频轴解缠的 px 轴 ±360° 分支切割跳变失真：fine 存储列 max−min
        358.09° 伪值 vs 真实圆周覆盖 100.90°（原始 sparams.csv 双路径独立
        复核一致）。周期量的正确度量=360°−最大圆周间隙（arc_coverage_deg
        单源，T26 移入内核）。旧口径保留为 phase_span_deg()（诊断面）；
        四四八归档 verdict 零改写（#325），本度量自 T26 起为 J1c 门与
        coverage_gate 的计算口径。
        """
        j = int(np.argmin(np.abs(self.freq_ghz - self.f0_ghz)))
        return arc_coverage_deg(self.s11_phase_deg[:, j])

    def phase_span_deg(self) -> float:
        """旧口径诊断：f0 列存储值的 max−min 跨度（度）。

        对含 ±360° 分支切割跳变的列被系统性抬升（T13：fine 实测 358.09°
        存储伪值）——只作新旧度量对照/诊断，不作门判据。
        """
        j = int(np.argmin(np.abs(self.freq_ghz - self.f0_ghz)))
        col = self.s11_phase_deg[:, j]
        return float(np.max(col) - np.min(col))

    def coverage_gate(self) -> dict[str, Any]:
        """J1c 覆盖门（≥300°，criteria §1c）：只算数值与判定，不跑仿真。

        度量=T26 起为真实圆周覆盖（phase_coverage_deg → arc_coverage_deg
        单源；旧 max−min 口径对分支切割列失真，T13 实证，见该 docstring）。
        """
        cov = self.phase_coverage_deg()
        return {"phase_coverage_deg": cov,
                "threshold_deg": _J1_COVERAGE_DEG_MIN,
                "verdict": "PASS" if cov >= _J1_COVERAGE_DEG_MIN else "FAIL"}


# ── 相位处理原语 ─────────────────────────────────────────────────────────────


def unwrap_phase_deg(phases_deg: np.ndarray) -> np.ndarray:
    """解缠相位（度）：np.unwrap（弧度域）往返，跨 2π 跳变消除。"""
    return np.degrees(np.unwrap(np.radians(np.asarray(phases_deg, dtype=float))))


def unwrap_sweep_axis_deg(phases_deg: np.ndarray) -> np.ndarray:
    """沿扫描（px）轴的圆周连续化解缠：相邻差折回最短角差后累积。

    T13 定案（runs/dp10_j2j3/launch_ready.md §1.1）：launch_sweep.load_lut
    的解缠发生在逐行频轴，px 轴 ±180° cut 穿越在存储列里留下 ±360° 级
    伪跳变（fine 实测 +358.09° @px 6.7988→6.8125）——本原语把每对相邻
    样本的差 wrap 到 [−180,180) 再累积，输出列与输入 mod 360 逐点相等、
    相邻差全部 ∈[−180,180)（圆周连续）。pchip 相位插值与跨度类诊断必须在
    本连续域进行（跨跳变插值会扫过整 360° 伪摆幅）。
    """
    a = np.asarray(phases_deg, dtype=float)
    out = np.array(a, dtype=float)
    if a.ndim != 1 or a.size < 2:
        return out
    wrapped = (np.diff(a) + 180.0) % 360.0 - 180.0
    out[1:] = out[0] + np.cumsum(wrapped)
    return out


def arc_coverage_deg(phases_deg: np.ndarray) -> float:
    """真实圆周相位覆盖（度）= 360°−最大圆周间隙（对分支切割免疫，单源）。

    周期量的覆盖正确口径（T13/T26 单源，原实现 runs/dp10_j2j3/launch_j2.py
    驱动侧已迁入本内核）：样本 mod 360 排序后，覆盖=360°减去最大圆周间隙
    （含首尾 wrap 间隙）。max−min 口径（phase_span_deg）对含 ±360° 分支
    切割跳变的列失真（fine 存储列 358.09° 伪值 vs 真实圆周 100.90°，T13
    双路径复核一致）。样本 <2 或全同相位覆盖=0。
    """
    v = np.mod(np.asarray(phases_deg, dtype=float).ravel(), 360.0)
    if v.size < 2:
        return 0.0
    v.sort()
    gaps = np.diff(v)
    return float(360.0 - max(float(gaps.max()), float(v[0]) + 360.0 - float(v[-1])))


def lut_interp_pchip(lut: MetasurfaceLUT, sweep_value: float,
                     f0_ghz: float | None = None) -> tuple[float, float]:
    """pchip 插值单点 (|S|dB, 相位 deg)：对扫描轴在 f0（缺省 LUT.f0）插值。

    相位在扫描轴圆周连续化域插值（unwrap_sweep_axis_deg 先行——T13：存储列
    的 ±360° 分支切割跳变不折回时，跨跳变插值会扫过整 360° 伪摆幅）。
    返回相位与网格存储值 mod 360 一致（绝对分支可平移 k·360°：周期消费者
    无感——lut_lookup_phase 按圆周距离、fpa_antenna 腔方程含 2π·n 松弛）。
    """
    j = int(np.argmin(np.abs(lut.freq_ghz - (lut.f0_ghz if f0_ghz is None
                                             else f0_ghz))))
    ph = PchipInterpolator(lut.sweep_values,
                           unwrap_sweep_axis_deg(lut.s11_phase_deg[:, j]))
    db = PchipInterpolator(lut.sweep_values, lut.s11_db[:, j])
    return float(db(sweep_value)), float(ph(sweep_value))


def lut_interp_s21_pchip(lut: MetasurfaceLUT, sweep_value: float,
                         f0_ghz: float | None = None) -> tuple[float, float]:
    """s21 载体 pchip 插值单点 (|T|dB, 相位 deg)——lut_interp_pchip 透射版（v2 追加）。

    缺 s21 载体（v1 旧行/未采集透射）显式 ValueError；相位在扫描轴圆周
    连续化域插值（unwrap_sweep_axis_deg 先行，T13 同纪律）。(dB, deg) 出
    参配 gstc.t_r_from_db_phase 构成 LUT→GSTC 复透射通道桥（MM-3 §C-2）。
    """
    if lut.s21_db is None or lut.s21_phase_deg is None:
        raise ValueError(
            f"LUT {lut.cell_id!r} 无 s21 载体（v1 旧行/未采集透射）——"
            "透射通道需 schema v2 的 s21_db/s21_phase_deg 列")
    j = int(np.argmin(np.abs(lut.freq_ghz - (lut.f0_ghz if f0_ghz is None
                                             else f0_ghz))))
    ph = PchipInterpolator(lut.sweep_values,
                           unwrap_sweep_axis_deg(lut.s21_phase_deg[:, j]))
    db = PchipInterpolator(lut.sweep_values, lut.s21_db[:, j])
    return float(db(sweep_value)), float(ph(sweep_value))


def _circ_diff_deg(a: float, b: float) -> float:
    """相位圆周距离（度，0..180）。"""
    d = (a - b) % 360.0
    return min(d, 360.0 - d)


def lut_lookup_phase(lut: MetasurfaceLUT,
                     target_phase_deg: float) -> dict[str, float]:
    """逐单元最近邻反查：目标相位（mod 360 圆周距离）最近的 LUT 网格点。

    返回 {"sweep_value", "phase_deg"}——判据 J1a 的确定性定义：
    最近邻由圆周距离唯一决定（并列取 sweep 较小者，量化前的约定）。
    """
    j = int(np.argmin(np.abs(lut.freq_ghz - lut.f0_ghz)))
    col = lut.s11_phase_deg[:, j]
    dist = np.array([_circ_diff_deg(target_phase_deg, float(v)) for v in col])
    i = int(np.argmin(dist))
    return {"sweep_value": float(lut.sweep_values[i]),
            "phase_deg": float(col[i])}


def lut_lookup_phase_s21(lut: MetasurfaceLUT,
                         target_phase_deg: float) -> dict[str, float]:
    """逐单元最近邻反查（s21 透射载体）——lut_lookup_phase 的透射版（MM-6 差异③）。

    透射阵布局综合消费的是单元**透射**相位响应：反查列=f0 处
    s21_phase_deg（非 s11）；最近邻同样按圆周距离唯一决定（并列取 sweep
    较小者）。缺 s21 载体（v1 旧行/未采集透射）显式 ValueError——透射
    通道拿 s11 载体反查是"反射相位冒充透射相位"的静默错（ carriers 独立
    采集，逐点可差任意角度），必须硬拒绝。
    """
    if lut.s21_db is None or lut.s21_phase_deg is None:
        raise ValueError(
            f"LUT {lut.cell_id!r} 无 s21 载体（v1 旧行/未采集透射）——"
            "透射阵反查需 schema v2 的 s21_db/s21_phase_deg 列（MM-6 差异③）")
    j = int(np.argmin(np.abs(lut.freq_ghz - lut.f0_ghz)))
    col = lut.s21_phase_deg[:, j]
    dist = np.array([_circ_diff_deg(target_phase_deg, float(v)) for v in col])
    i = int(np.argmin(dist))
    return {"sweep_value": float(lut.sweep_values[i]),
            "phase_deg": float(col[i])}


def quantize_phase_deg(target_phase_deg: float, bits: int) -> float:
    """b-bit 相位量化（取整到 2π/2^b 栅格，度域）。bits≥1。"""
    if bits < 1:
        raise ValueError(f"bits={bits} 须 ≥1")
    step = 360.0 / (2 ** bits)
    return round(target_phase_deg / step) * step


# ─── 布局综合闭式（确定性内核， 硬规则 7）──────────────────────────────


def _k0_rad_m(f0_ghz: float) -> float:
    return 2.0 * math.pi * (f0_ghz * 1e9) / C0_M_S


def required_phase_reflectarray(
    positions_m: np.ndarray,
    feed_pos_m: np.ndarray,
    u_beam: np.ndarray,
    f0_ghz: float,
) -> np.ndarray:
    """反射阵（点馈）所需单元反射相位（度，mod 360）。

    φ_mn = k0·(R_mn − r_mn·û_beam) mod 2π（Huang-Encinar 空间相位延迟式；
    R_mn=|r_mn−r_feed|，û_beam 单位主波束向量，反射侧）。positions_m
    (N,3) 单元位置（z=口径面），feed_pos_m (3,) 馈电相心。
    """
    pos = np.atleast_2d(np.asarray(positions_m, dtype=float))
    u = np.asarray(u_beam, dtype=float)
    u = u / float(np.linalg.norm(u))
    r = np.asarray(feed_pos_m, dtype=float)
    ranges = np.linalg.norm(pos - r, axis=1)
    phi = _k0_rad_m(f0_ghz) * (ranges - pos @ u)
    return np.degrees(phi) % 360.0


def required_phase_plane_wave(
    positions_m: np.ndarray,
    u_in: np.ndarray,
    u_out: np.ndarray,
    f0_ghz: float,
) -> np.ndarray:
    """平面波照明所需单元相位（度，mod 360）——反射/透射统一光栅条件。

    φ_mn = k0·(û_in − û_out)·r_mn mod 2π。透射编码面法向入射特例
    û_in=(0,0,−1)、û_out=(sinθcosφ, sinθsinφ, cosθ)：φ_mn=−k0·r·û_out+const
    （规格书口径 mod 2π 等价）；反射（û_out 反射侧）同式。本批软平面
    照明（û_in=(0,0,−1)，自 +z 向下）即用此式。
    """
    pos = np.atleast_2d(np.asarray(positions_m, dtype=float))
    ui = np.asarray(u_in, dtype=float)
    uo = np.asarray(u_out, dtype=float)
    ui = ui / float(np.linalg.norm(ui))
    uo = uo / float(np.linalg.norm(uo))
    phi = _k0_rad_m(f0_ghz) * ((ui - uo) * pos).sum(axis=1)
    return np.degrees(phi) % 360.0


def _normalize_unit(v: np.ndarray, name: str) -> np.ndarray:
    """归一化方向向量；零向量显式拒绝（透射阵域守卫共用）。"""
    u = np.asarray(v, dtype=float).ravel()
    if u.size != 3:
        raise ValueError(f"{name} 需为 (3,) 方向向量，得 shape={u.shape}")
    n = float(np.linalg.norm(u))
    if not n > 0.0:
        raise ValueError(f"{name} 为零向量，非法")
    return u / n


def _require_transmit_side(u: np.ndarray, name: str) -> np.ndarray:
    """差异①域守卫：方向必须指向 −z 半空间（û[2]<0 严格）。

    透射阵的出射束穿口径面进入馈源对侧（−z）半空间；z 分量 ≥0（含掠射
    z=0，不定义半空间束）显式 ValueError。反射阵（required_phase_
    reflectarray）的束在馈侧、无此守卫——两入口非互换即此。
    """
    if not float(u[2]) < 0.0:
        raise ValueError(
            f"{name} z 分量={float(u[2]):.6g} 须 <0（透射束在馈源对侧 −z "
            "半空间，MM-6 差异①域守卫；反射侧向量请改用反射阵入口）")
    return u


def required_phase_transmitarray(
    positions_m: np.ndarray,
    feed_pos_m: np.ndarray,
    u_out: np.ndarray,
    f0_ghz: float,
) -> np.ndarray:
    """透射阵（点馈）所需单元透射相位（度，mod 360）——MM-6 §A-6。

    φ_mn = k0·(|F−r| − r·û_out) mod 2π（规格式原文；与反射阵 Huang-Encinar
    式同形：透射几何=反射几何对口径面的镜像，馈→单元→远场的路径延迟账
    相同——镜像对拍钉见 tests/unit/test_transmitarray_phase.py）。û_out
    为**物理透射方向**（单位向量，z 分量 <0，域守卫强制，差异①）；
    R=|r−F|，馈相心 feed_pos_m 在 +z 侧。锚：馈源后退（法向+广角）退化
    为 −k0·r·û_out（mod 2π 常数）。
    """
    pos = np.atleast_2d(np.asarray(positions_m, dtype=float))
    u = _require_transmit_side(_normalize_unit(u_out, "u_out"), "u_out")
    r = np.asarray(feed_pos_m, dtype=float).ravel()
    ranges = np.linalg.norm(pos - r, axis=1)
    phi = _k0_rad_m(f0_ghz) * (ranges - pos @ u)
    return np.degrees(phi) % 360.0


def required_phase_transmitarray_plane_wave(
    positions_m: np.ndarray,
    u_in: np.ndarray,
    u_out: np.ndarray,
    f0_ghz: float,
) -> np.ndarray:
    """透射阵平面波照明档所需单元透射相位（度，mod 360）——MM-6 差异②。

    φ_mn = k0·(û_in − û_out)·r_mn mod 2π，û_in/û_out 均**物理传播方向**
    （照明自 +z 侧向下 û_in[2]<0；透射束 û_out[2]<0，双域守卫强制）。
    法向入射 û_in=(0,0,−1) 退化为规格书透射式 φ=−k0·r·û_out（mod 2π
    常数）——§A-6 锚同式。

    差异②记档（#122 如实，不凑规格字面）：规格原文"平面波照明档相位梯度
    符号相反（required_phase_plane_wave 为反射约定）"。物理上反射/透射
    光栅条件在 z=0 口径面上同号（口径面只感受切向分量，dφ/dr_t=−k0·û_t
    决定束向，反射/透射同一关系）；"符号相反"的可实现形态=**方向向量
    约定相反**：required_phase_plane_wave 的透射特例 docstring 以馈侧
    约定（û_out z 分量>0）书写，本入口取物理透射方向（z<0，守卫强制）
    ——同一波束的馈侧约定向量与物理向量 z 镜像，馈侧向量传入本入口被
    域守卫拒绝（负例钉 tests/unit/test_transmitarray_phase.py）。若按
    "整体反号"字面实现（φ=+k0·(û_out−û_in)·r=+k0·r·û_out 法向），波束
    将打到镜像侧、且与 §A-6 自身锚（退化 −k0·r·û 对拍）矛盾——按锚与
    既有测试冻结口径（test_phase_and_law_identity_transmission）实现。
    """
    pos = np.atleast_2d(np.asarray(positions_m, dtype=float))
    ui = _normalize_unit(u_in, "u_in")
    if not float(ui[2]) < 0.0:
        raise ValueError(
            f"u_in z 分量={float(ui[2]):.6g} 须 <0（透射阵照明自 +z 侧向下，"
            "MM-6 差异②域守卫）")
    uo = _require_transmit_side(_normalize_unit(u_out, "u_out"), "u_out")
    phi = _k0_rad_m(f0_ghz) * ((ui - uo) * pos).sum(axis=1)
    return np.degrees(phi) % 360.0


def synthesize_layout(
    n_x: int,
    n_y: int,
    period_m: float,
    f0_ghz: float,
    lut: MetasurfaceLUT,
    *,
    feed_pos_m: np.ndarray | None = None,
    u_in: np.ndarray | None = None,
    u_beam: np.ndarray,
    bits: int = 0,
) -> list[dict[str, Any]]:
    """布局综合：闭式目标相位 →（可选 b-bit 量化）→ LUT 最近邻反查。

    返回逐单元参数表（cell_map 同构：i/j/x_m/y_m/px 目标相位/量化相位/
    反查值/反查相位）。bits=0 不量化。feed_pos_m 给出=点馈反射阵；
    否则平面波照明（u_in 缺省 (0,0,−1) 软平面口径）。纯函数零 IO。
    """
    if n_x < 1 or n_y < 1:
        raise ValueError(f"n_x/n_y 须 ≥1，得 {n_x}/{n_y}")
    if period_m <= 0:
        raise ValueError("period_m 须 >0")
    problems = lut.validate()
    if problems:
        raise ValueError(f"LUT 不合格: {problems}")
    if bits and lut.coverage_gate()["verdict"] != "PASS":
        # 量化要求 LUT 覆盖 0..360 全域；覆盖不足量化误差失控——显式拒绝
        raise ValueError("bits>0 要求 LUT 相位覆盖 ≥300°（J1c 门）")
    xs = (np.arange(n_x) - (n_x - 1) / 2.0) * period_m
    ys = (np.arange(n_y) - (n_y - 1) / 2.0) * period_m
    xx, yy = np.meshgrid(xs, ys, indexing="ij")
    pos = np.stack([xx.ravel(), yy.ravel(), np.zeros(n_x * n_y)], axis=1)
    if feed_pos_m is not None:
        phi = required_phase_reflectarray(pos, np.asarray(feed_pos_m, float),
                                          u_beam, f0_ghz)
    else:
        phi = required_phase_plane_wave(
            pos, np.asarray(u_in, float) if u_in is not None
            else np.array([0.0, 0.0, -1.0]), u_beam, f0_ghz)
    cells: list[dict[str, Any]] = []
    for k in range(pos.shape[0]):
        tgt = float(phi[k])
        q = quantize_phase_deg(tgt, bits) if bits else tgt
        hit = lut_lookup_phase(lut, q)
        cells.append({
            "i": int(k % n_x), "j": int(k // n_x),
            "x_m": float(pos[k, 0]), "y_m": float(pos[k, 1]),
            "phase_target_deg": tgt,
            "phase_quantized_deg": q if bits else None,
            "sweep_value": hit["sweep_value"],
            "phase_achieved_deg": hit["phase_deg"],
        })
    return cells


def synthesize_layout_transmitarray(
    n_x: int,
    n_y: int,
    period_m: float,
    f0_ghz: float,
    lut: MetasurfaceLUT,
    *,
    feed_pos_m: np.ndarray | None = None,
    u_in: np.ndarray | None = None,
    u_out: np.ndarray,
    bits: int = 0,
) -> list[dict[str, Any]]:
    """透射阵布局综合：闭式目标相位 →（可选 b-bit 量化）→ LUT s21 载体反查。

    MM-6 §A-6：目标相位走 required_phase_transmitarray（feed_pos_m 给出，
    点馈）或 required_phase_transmitarray_plane_wave（否则，u_in 缺省
    (0,0,−1) 软平面口径）；差异③=LUT 消费走 **s21 透射载体**
    （lut_lookup_phase_s21），v1 旧行（无 s21）显式拒绝。bits>0 的量化
    覆盖门同样按 s21 列裁决（既有 coverage_gate 读 s11 列，透射阵不适用
    ——禁改其语义，此处独立按 arc_coverage_deg 判）。返回逐单元参数表
    （schema 同 synthesize_layout，另加 carrier="s21" 标记）。纯函数零 IO。
    """
    if n_x < 1 or n_y < 1:
        raise ValueError(f"n_x/n_y 须 ≥1，得 {n_x}/{n_y}")
    if period_m <= 0:
        raise ValueError("period_m 须 >0")
    if lut.s21_db is None or lut.s21_phase_deg is None:
        raise ValueError(
            f"LUT {lut.cell_id!r} 无 s21 载体（v1 旧行/未采集透射）——透射阵"
            "布局综合需 schema v2 s21 载体（MM-6 差异③）")
    problems = lut.validate()
    if problems:
        raise ValueError(f"LUT 不合格: {problems}")
    if bits:
        j0 = int(np.argmin(np.abs(lut.freq_ghz - lut.f0_ghz)))
        cov = arc_coverage_deg(lut.s21_phase_deg[:, j0])
        if cov < _J1_COVERAGE_DEG_MIN:
            raise ValueError(
                f"bits>0 要求 s21 载体相位覆盖 ≥{_J1_COVERAGE_DEG_MIN:.0f}°"
                f"（J1c 门，s21 列实测 {cov:.2f}°）")
    xs = (np.arange(n_x) - (n_x - 1) / 2.0) * period_m
    ys = (np.arange(n_y) - (n_y - 1) / 2.0) * period_m
    xx, yy = np.meshgrid(xs, ys, indexing="ij")
    pos = np.stack([xx.ravel(), yy.ravel(), np.zeros(n_x * n_y)], axis=1)
    if feed_pos_m is not None:
        phi = required_phase_transmitarray(pos, np.asarray(feed_pos_m, float),
                                           u_out, f0_ghz)
    else:
        phi = required_phase_transmitarray_plane_wave(
            pos, np.asarray(u_in, float) if u_in is not None
            else np.array([0.0, 0.0, -1.0]), u_out, f0_ghz)
    cells: list[dict[str, Any]] = []
    for k in range(pos.shape[0]):
        tgt = float(phi[k])
        q = quantize_phase_deg(tgt, bits) if bits else tgt
        hit = lut_lookup_phase_s21(lut, q)
        cells.append({
            "i": int(k % n_x), "j": int(k // n_x),
            "x_m": float(pos[k, 0]), "y_m": float(pos[k, 1]),
            "phase_target_deg": tgt,
            "phase_quantized_deg": q if bits else None,
            "sweep_value": hit["sweep_value"],
            "phase_achieved_deg": hit["phase_deg"],
            "carrier": "s21",
        })
    return cells


def phase_quantization_mse_rad2(bits: int) -> float:
    """b-bit 均匀量化的均方相位误差（rad²）= (π/2^b)²/3（副瓣基底口径，冻结）。"""
    if bits < 1:
        raise ValueError(f"bits={bits} 须 ≥1")
    return (math.pi / (2 ** bits)) ** 2 / 3.0


def quantization_loss_db(bits: int) -> float:
    """量化增益损失（正值 dB）= −10·log10(sinc²(1/2^b))（E[e^{jε}]² 精确期望）。

    文献带（规格书 §1）：1/2/3-bit≈3/0.6/0.2dB；本口径 3.92/0.91/0.22
    全落 ±1dB 带（J5）。sinc(x)=sin(πx)/(πx)。
    """
    if bits < 1:
        raise ValueError(f"bits={bits} 须 ≥1")
    x = 1.0 / (2 ** bits)
    sinc = math.sin(math.pi * x) / (math.pi * x)
    return -10.0 * math.log10(sinc * sinc)


# ─── 名义尺寸闭式（#252/#1c 单源；渲染与 TEMPLATE_NOMINAL 同源消费）──────────


def ms_patch_eps_eff(w_mm: float, er: float, h_mm: float) -> float:
    """Hammerstad 薄板 εeff 闭式（反射阵方贴片设计口径）。"""
    if w_mm <= 0 or er <= 1 or h_mm <= 0:
        raise ValueError(f"非法输入 w={w_mm} er={er} h={h_mm}")
    return (er + 1) / 2 + (er - 1) / 2 / math.sqrt(1 + 12 * h_mm / w_mm)


def ms_patch_resonant_len_mm(f0_ghz: float, er: float, h_mm: float) -> float:
    """方贴片谐振边长（mm）：λ0/(2√εeff(w)) 以 w=边长解不动点（2 次迭代收敛）。"""
    lam0_mm = C0_M_S / (f0_ghz * 1e9) * 1e3
    w = lam0_mm / (2 * math.sqrt((er + 1) / 2))
    for _ in range(16):
        w = lam0_mm / (2 * math.sqrt(ms_patch_eps_eff(w, er, h_mm)))
    return w


def ms_screen_eps_eff(er: float) -> float:
    """FSS 屏 εeff=(1+εr)/2（单侧基板加载，Luukkonen eq.3 口径）。"""
    return (1.0 + er) / 2.0


def ms_cross_arm_len_mm(f0_ghz: float, er: float) -> float:
    """十字偶极子臂长（中心→尖端，mm）：总跨=λ0/(2√εeff)（半波谐振）。"""
    lam0_mm = C0_M_S / (f0_ghz * 1e9) * 1e3
    return lam0_mm / (4.0 * math.sqrt(ms_screen_eps_eff(er)))


def ms_jcross_slot_dims_mm(f0_ghz: float, er: float) -> dict[str, float]:
    """Jerusalem cross 缝初值（mm）：主缝=λg/4、端枝=λg/8（λg=λ0/√εeff）。

    JC 缝=带通口径（缝隙谐振全透）：电长度初值按半波口径分配主缝+双端枝；
    真机带心修正（openEMS LUT 一轮）归 P3——EC 闭环见 fss_* 函数。
    """
    lam0_mm = C0_M_S / (f0_ghz * 1e9) * 1e3
    lamg_mm = lam0_mm / math.sqrt(ms_screen_eps_eff(er))
    return {"slot_len_mm": lamg_mm / 4.0, "stub_len_mm": lamg_mm / 8.0}


def ms_ring_patch_dims_mm(f0_ghz: float, er: float) -> dict[str, float]:
    """双谐振方环+内贴片单元的环几何初值（mm；J2 fallback 预登记单元）。

    口径（criteria §1c 预登记 fallback 的闭式初值，#1c/#252 单源）：环空腔
    void=0.4λ0（屏族 0.4λ0 周期口径，ms_cross/ms_jcross period 同式）、环线宽
    ring_w=λg/40（ms_jcross 缝宽口径）、环外边 ring_outer=void+2·ring_w；
    εeff=ms_screen_eps_eff(er)（(1+εr)/2 单侧基板加载）。内贴片谐振边长复用
    ms_patch_resonant_len_mm（Hammerstad 不动点），不在此重复实现。初值语义
    =几何骨架闭式（谐振由段④ LUT 扫描实证，J1c 门≥300° 裁决）。
    """
    lam0_mm = C0_M_S / (f0_ghz * 1e9) * 1e3
    lamg_mm = lam0_mm / math.sqrt(ms_screen_eps_eff(er))
    void_mm = round(0.4 * lam0_mm, 4)
    ring_w_mm = round(lamg_mm / 40.0, 4)
    return {"void_mm": void_mm, "ring_w_mm": ring_w_mm,
            "ring_outer_mm": round(void_mm + 2.0 * ring_w_mm, 4)}


# ─── Luukkonen/Costa EC 闭式（FSS 屏带心初值）────────────────────────────────


def fss_patch_grid_capacitance_f(period_m: float, gap_m: float,
                                 eps_eff: float) -> float:
    """容性贴片阵等效电容（F/胞）：C=(2D/π)ε0εeff·ln(csc(πg/2D))。

    arXiv:0705.3548 eq.4 α=(k_eff·D/π)ln(csc) + TM 栅阻抗 Z=−jη_eff/2α
    换算（法向 TM）；eps_eff=(1+εr)/2（eq.3）。要求 g≪D（稠密栅有效域）。
    """
    if period_m <= 0 or not 0 < gap_m < period_m:
        raise ValueError(f"要求 0<gap<period，得 {gap_m}/{period_m}")
    x = math.pi * gap_m / (2 * period_m)
    return (2 * period_m / math.pi) * EPS0_F_M * eps_eff * math.log(1 / math.sin(x))


def fss_mesh_grid_inductance_h(period_m: float, wire_m: float) -> float:
    """感性线网等效电感（H/胞）：L=μ0·D/(2π)·ln(csc(πw/2D))（对偶口径）。"""
    if period_m <= 0 or not 0 < wire_m < period_m:
        raise ValueError(f"要求 0<wire<period，得 {wire_m}/{period_m}")
    x = math.pi * wire_m / (2 * period_m)
    return MU0_H_M * period_m / (2 * math.pi) * math.log(1 / math.sin(x))


def fss_screen_sparams(
    freq_hz: np.ndarray,
    grid_kind: str,
    period_m: float,
    eps_eff: float,
    *,
    gap_m: float | None = None,
    wire_m: float | None = None,
    parallel_lc: tuple[float, float] | None = None,
    slab_eps: float = 1.0,
    slab_h_m: float = 0.0,
) -> dict[str, np.ndarray]:
    """FSS 屏 S 参数（法向，ABCD 级联纯函数）：空气 TL − 栅 shunt − 基板 TL − 空气。

    grid_kind：'patch'（shunt Z=1/jωC，C 由 period+gap 闭式）| 'mesh'
    （shunt Z=jωL，L 由 period+wire 闭式）| 'parallel_lc'（JC 缝带通口径：
    shunt 支路=LC 并联，Z=(jωL)∥(1/jωC) 在 f0 呈开路→全透；实心屏 DC/
    高频呈短路→反射，(L,C) 由 parallel_lc 显式给出，
    fss_jcross_parallel_lc 定带心）。slab：基板 TL 段（eps_r=slab_eps、
    厚 slab_h_m；eps=1/h=0 退化无板）。返回 {"s11_db","s21_db","s21"}。
    口径注记（离线冒烟实证）：shunt 支路若用**串联** LC，谐振=短路=带阻
   陷（f0 处 S21 谷）——JC 缝是带通口径，必须并联谐振（shunt 开路）。
    """
    if grid_kind not in ("patch", "mesh", "parallel_lc"):
        raise ValueError(f"grid_kind={grid_kind!r} 非法")
    f = np.atleast_1d(np.asarray(freq_hz, dtype=float))
    om = 2 * np.pi * f
    if grid_kind == "patch":
        if gap_m is None:
            raise ValueError("grid_kind='patch' 需 gap_m")
        c_f = fss_patch_grid_capacitance_f(period_m, gap_m, eps_eff)
        z = 1.0 / (1j * om * c_f)
    elif grid_kind == "mesh":
        if wire_m is None:
            raise ValueError("grid_kind='mesh' 需 wire_m")
        z = 1j * om * fss_mesh_grid_inductance_h(period_m, wire_m)
    else:
        if parallel_lc is None:
            raise ValueError("grid_kind='parallel_lc' 需 parallel_lc=(L,C)")
        l_h, c_f = parallel_lc
        z = (1j * om * l_h) * (1.0 / (1j * om * c_f)) / (
            1j * om * l_h + 1.0 / (1j * om * c_f))
    z0 = ETA0_OHM
    eta_sl = z0 / math.sqrt(slab_eps) if slab_eps > 0 else z0
    beta_sl = 2 * np.pi * f / C0_M_S * math.sqrt(slab_eps)
    s11 = np.empty(f.size, dtype=complex)
    s21 = np.empty(f.size, dtype=complex)
    for i in range(f.size):
        abcd = _abcd_tl(eta_sl, beta_sl[i], slab_h_m / 2)
        abcd = abcd @ _abcd_shunt(z[i])
        abcd = abcd @ _abcd_tl(eta_sl, beta_sl[i], slab_h_m / 2)
        den = (abcd[0, 0] + abcd[0, 1] / z0 + abcd[1, 0] * z0 + abcd[1, 1])
        s21[i] = 2.0 / den
        s11[i] = ((abcd[0, 0] + abcd[0, 1] / z0 - abcd[1, 0] * z0
                   - abcd[1, 1]) / den)
    with np.errstate(divide="ignore"):
        return {"s11_db": 20 * np.log10(np.abs(s11)),
                "s21_db": 20 * np.log10(np.abs(s21)),
                "s21": s21}


def _abcd_tl(z_c: float, beta_rad_m: float, d_m: float) -> np.ndarray:
    th = beta_rad_m * d_m
    return np.array([[math.cos(th), 1j * z_c * math.sin(th)],
                     [1j * math.sin(th) / z_c, math.cos(th)]], dtype=complex)


def _abcd_shunt(z: complex) -> np.ndarray:
    return np.array([[1.0, 0.0], [1.0 / z, 1.0]], dtype=complex)


def fss_jcross_parallel_lc(period_m: float, slot_w_m: float,
                           target_f0_hz: float) -> tuple[float, float]:
    """JC 缝带通 EC：L 由缝宽/周期线网闭式；C=1/(ω0²L) 定带心（初值口径）。

    返回 (L, C)：shunt 支路 LC **并联**，f0 处呈开路→全透（带通）；
    C→缝端枝几何的映射是真机 LUT 修正环（P3）的标定对象——本函数只钉
    带心初值的确定性来源。
    """
    l_h = fss_mesh_grid_inductance_h(period_m, slot_w_m)
    om0 = 2 * math.pi * target_f0_hz
    return l_h, 1.0 / (om0 * om0 * l_h)


def ec_resonance_peak_f(fss: dict[str, np.ndarray],
                        freq_hz: np.ndarray) -> float:
    """|S21| 峰位（Hz）——EC 自洽钉：设计带心的 L、C 级联后峰=f0。"""
    return float(freq_hz[int(np.argmax(fss["s21_db"]))])


def lut_summary(lut: MetasurfaceLUT) -> dict[str, Any]:
    """LUT 概要（gate 记录/判读报告面）：覆盖、门、来源 provenance。"""
    return {"cell_id": lut.cell_id, "f0_ghz": lut.f0_ghz,
            "substrate_key": lut.substrate_key, "origin": lut.origin,
            "run_dir": lut.run_dir, "n_sweep": int(lut.sweep_values.size),
            "n_freq": int(lut.freq_ghz.size), "interp": lut.interp,
            "validity": dict(lut.validity), "gate": dict(lut.gate)}


# ─── PRS 供体接口（LM-1 FPA 桥；纯增量：只增函数，零改既有行为）──────────────


def lut_prs_reflectance(lut: MetasurfaceLUT, sweep_value: float,
                        f0_ghz: float | None = None) -> dict[str, float]:
    """LM-1 PRS 供体：LUT 单点反射系数 → FPA 闭式入参 (R, phi_PRS)。

    s11_db 本就是 |Γ| 的 dB 载体——|Γ|=10^(s11_db/20)（幅度）、
    R=|Γ|²=10^(s11_db/10)（功率反射率，0..1）、phi_PRS=解缠相位（度）。
    本接口只做单位换算+插值（lut_interp_pchip 同口径，f0 缺省 lut.f0_ghz），
    **不改任何既有函数行为**（LM-1 纯增量硬边界）。返回
    {"r_amp", "r_power", "phase_deg"}；输出直接作
    rfauto.core.fpa_antenna 的 (r=R 功率反射率, phi_prs_deg) 入参。
    R=1（s11_db=0 全反 ideal PRS）时 fpa_antenna.directivity/resonance_q
    会拒绝（R∈[0,1) 口径）——调用方在 LUT 扫描网格上取 R<1 的单元即可。
    """
    db, ph = lut_interp_pchip(lut, sweep_value, f0_ghz)
    r_amp = 10.0 ** (db / 20.0)
    return {"r_amp": r_amp, "r_power": r_amp * r_amp, "phase_deg": ph}
