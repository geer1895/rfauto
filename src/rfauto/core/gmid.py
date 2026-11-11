"""gm/ID 查表定尺寸确定性内核（AX-7，aurora_r R-19 席；思想级重写零搬运）。

出处与许可口径（runs/aurora_q/qx40_vbridge/AUTHOR_SURVEY.md AX-7 行）：
API 契约形态（lookup / size / size_from_ft + 首调建表缓存）仿 gmoverid-skill
（146★，README 挂 MIT 徽章但 LICENSE 文件 404 = 无许可仓）的**思想级**范式，
本文件全部代码为本仓重写，零文件搬运；PTM/PDK 模型文件不进仓（AUTHOR_SURVEY
§3-5 红线）。gm/ID 方法论内核：gm/ID 为单自变量枢轴量——同 (L, gm/ID) 点的
ID/W、gm/gds、fT、VGS 四量与 W 无关（单位宽度建表一次，任意 W 缩放），本内核
以"单位宽度建表 + ID/W 归一"落实该不变量（test 钉 W 无关性）。

表格式（YAML 落盘，schema 键+版本键+来源键）::

    schema: rfauto-gmid-table-v1        # 格式版本键
    table_version: 1
    source:                              # 来源键（name/kind/precision/params）
      name: ekv_synthetic_mos
      kind: synthetic                    # synthetic | external（真机注入）
      precision: ...                     # 精度归属声明
      params: {...}
    sweep: {w_unit_m, f_char_hz, vgs_start_v, vgs_stop_v, vgs_step_v, refine}
    l_um: [...]                          # L 轴（µm，严格递增）
    gmid_per_v: [...]                    # gm/ID 轴（V^-1，严格递增）
    columns: [id_w_a_per_m, gm_gds, f_t_hz, vgs_v]
    values:                              # values[i].rows[j] 对应 (l_um[i], gmid_per_v[j])
      - {l_um: 0.18, rows: [[id_w, gm_gds, f_t, vgs], ...]}

三 API（#118 独立口径对拍见 tests/unit/test_gmid.py）：
    lookup(table, l_m, gmid_per_v)       双线性插值；越界=夹到边界端点+flag（不静默外推）
    size(table, l_m, 两维 of {id, gm, w}) 反解 W/L/VGS
    size_from_ft(table, f_t_hz, l_m)     按 fT 反查 gm/ID → 行（可附带 id 反解 W）

数值陷阱守卫（调研对位 gmoverid-skill 的 _fall_mask 折返防护，思想级）：
gm/ID vs VGS 在真实器件上峰值两侧双值——建表器对每条 L 曲线只保留峰值之后的
反型下降支（_fall_branch），双值区静默混入会让查表反解错支；gmid 网格未被
扫描覆盖时显式报错（不静默截断）。

真机通道挂账（刻意不实现，处方）：ADS/ngspice 特性化真跑 = 用户侧脚本注入——
按 AGENTS 规则 0/0b（ADS 走 hpeesofsim 链路、服务器优先）实现满足
``CharacterizationSource`` 协议的适配器：对每个 (W, L, VGS, f) 点做特性化仿真
（ID-VGS 扫描提 gm/gds，Cgg 提 fT），返回 SI 单位四键字典
``{"id": A, "gm": S, "gds": S, "cgg": F}``，再以
``get_or_build_table(source, source_meta={"name": "ads_<工艺>_<器件>",
"kind": "external", ...}, cache_dir=...)`` 建表缓存。真实 PDK/PTM 表一律不进
仓，表文件落 runs/ 或用户本地缓存目录。计算器键注册（core/calculators）同样
刻意挂账不做——341/342 数字链不动，是否注册归合流批评审。

public_api 口径：本模块**不设 __all__**（scripts/check_public_api.py 政策：
无 __all__ 文件记私有、快照不含 = 零漂移），公开面即下方顶层公开函数/类，
翻公开名属显式评审动作。

精度归属：内置合成源为**教科书闭式合成晶体管**（EKV 平滑过渡 + 平方律 +
沟长调制，系数=SI 定义常数与教科书公开量级值），精度归属=合成教学级、**非
PDK 级**——绝对数值（fT/增益量级）不构成工艺承诺，确定性内核的职责是
"查表-反解-闭式自洽"（对拍钉在 tests/unit/test_gmid.py）。
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import yaml

#: 表格式版本键（schema 不匹配 = 显式报错，不静默兼容）
SCHEMA = "rfauto-gmid-table-v1"
TABLE_VERSION = 1

#: 行四列（YAML columns 键序 = values 行内序）
_COLUMNS: tuple[str, ...] = ("id_w_a_per_m", "gm_gds", "f_t_hz", "vgs_v")

#: SI 定义常数（2019 SI，教科书公开物理常数；非拟合参数）
_BOLTZMANN_J_PER_K = 1.380649e-23
_ELEMENTARY_CHARGE_C = 1.602176634e-19


# ---------------------------------------------------------------------------
# 特性化数据源协议与内置合成源
# ---------------------------------------------------------------------------
class CharacterizationSource(Protocol):
    """特性化数据源协议：``callable(W_m, L_m, VGS_V, f_Hz) -> dict``。

    返回字典必须含四键（SI 单位）：

    - ``id``：漏极电流（A），必须 > 0（gm/ID 在 id=0 无定义；纯平方律源在
      VTH 以下返回 0 不可用，请用 EKV 型平滑闭式或丢弃零流点）
    - ``gm``：跨导（S），> 0
    - ``gds``：输出电导（S），> 0
    - ``cgg``：总栅电容（F），> 0（fT = gm/(2*pi*cgg)）

    契约说明：偏置条件（VDS、温度、器件极性/工艺族）烘焙进闭包/对象，
    并必须如实写进 ``source_meta``（来源键）——查表内核只见四键。
    """

    def __call__(self, w_m: float, l_m: float, vgs_v: float,
                 f_hz: float) -> dict[str, float]:
        """返回该 (W, L, VGS, f) 点的器件量四键字典。"""
        ...


def _softplus(x: float) -> float:
    """ln(1+e^x)，溢出安全（x>33 走渐近 x）。"""
    if x > 33.0:
        return x
    return math.log1p(math.exp(x))


def _sigmoid(x: float) -> float:
    """1/(1+e^-x)，溢出安全（两侧分支）。"""
    if x >= 0.0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


@dataclass(frozen=True)
class SyntheticMosSource:
    """内置合成 NMOS 特性化源（教科书闭式；**合成教学级精度，非 PDK 级**）。

    模型（Saturation 区， textbooks 公开闭式，零第三方模型文件）：

    - EKV 型平滑过渡电流：``ID = I_spec * s^2 * (1 + lambda*VDS)``，其中
      ``s = ln(1 + exp((VGS-VT0)/(2*n*UT)))``、``I_spec = 2*(n*UT)^2*KP*(W/L)``
      ——强反型渐近精确退化为 Shichman-Hodges 平方律
      ``ID = (KP/2)(W/L)(VGS-VT0)^2 (1+lambda*VDS)``，弱反型退化为指数律
      （gm/ID -> 1/(n*UT)），中等反型平滑过渡（EKV 教科书单参数近似）。
    - 沟长调制：``lambda(L) = lambda_v_per_v_per_um * (1um / L)``（教科书
      lambda 反比于 L 的量级惯例）。
    - gm = dID/dVGS、gds = dID/dVDS 按上式解析微分；gm/ID 与 CLM 无关
      （强反型 = 2/Vov，教科书结论，测试钉）。
    - 栅电容（fT 用，教学级准静态近似）：``Cgg = (2/3)*W*L*Cox + 2*W*Cov``
      （饱和区沟道电荷 2/3 因子 + 两侧重叠）。

    系数默认值 = 教科书公开量级值（0.18um 量级理想化教学工艺：KP=300uA/V^2、
    Cox=10fF/um^2、n=1.3），**不对应任何真实 PDK**；绝对数值不构成工艺承诺。
    """

    vt0_v: float = 0.4
    kp_a_per_v2: float = 3.0e-4
    n_sub: float = 1.3
    temp_k: float = 300.0
    lambda_v_per_v_per_um: float = 0.1
    cox_f_per_um2: float = 10.0
    cov_f_per_um: float = 0.2
    vds_v: float = 0.9

    def __post_init__(self) -> None:
        for name in ("kp_a_per_v2", "n_sub", "temp_k", "cox_f_per_um2",
                     "cov_f_per_um"):
            if getattr(self, name) <= 0.0:
                raise ValueError(f"SyntheticMosSource.{name} 必须 > 0")
        if self.lambda_v_per_v_per_um < 0.0:
            raise ValueError("SyntheticMosSource.lambda_v_per_v_per_um 必须 >= 0")

    @property
    def ut_v(self) -> float:
        """热电压 UT = kT/q（SI 定义常数）。"""
        return _BOLTZMANN_J_PER_K * self.temp_k / _ELEMENTARY_CHARGE_C

    def source_meta(self) -> dict[str, Any]:
        """来源键（YAML source 块）：kind=synthetic + 全参数落盘。"""
        return {
            "name": "ekv_synthetic_mos",
            "kind": "synthetic",
            "precision": ("teaching-grade synthetic closed form "
                          "(EKV smooth + square law + CLM); not PDK-grade"),
            "params": asdict(self),
        }

    def __call__(self, w_m: float, l_m: float, vgs_v: float,
                 f_hz: float) -> dict[str, float]:
        """CharacterizationSource 协议实现（f_hz 仅按契约接收，准静态模型不消费）。"""
        if w_m <= 0.0 or l_m <= 0.0:
            raise ValueError(f"W/L 必须 > 0，收到 W={w_m!r} L={l_m!r}")
        del f_hz  # 准静态教学模型与 f 无关；真机源在此做频率点仿真
        n_ut = self.n_sub * self.ut_v
        x = (vgs_v - self.vt0_v) / (2.0 * n_ut)
        s = _softplus(x)
        sig = _sigmoid(x)
        lambda_l = self.lambda_v_per_v_per_um * 1.0e-6 / l_m
        clm = 1.0 + lambda_l * self.vds_v
        i_spec = 2.0 * n_ut * n_ut * self.kp_a_per_v2 * (w_m / l_m)
        id_a = i_spec * s * s * clm
        gm = i_spec * s * sig / n_ut * clm
        gds = id_a * lambda_l / clm
        cox = self.cox_f_per_um2 * 1.0e-2  # fF/um^2 -> F/m^2（1e-15/1e-12）
        cov = self.cov_f_per_um * 1.0e-9  # fF/um -> F/m（1e-15/1e-6）
        cgg = (2.0 / 3.0) * w_m * l_m * cox + 2.0 * w_m * cov
        return {"id": id_a, "gm": gm, "gds": gds, "cgg": cgg}


# ---------------------------------------------------------------------------
# 结果对象
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class GmIdRow:
    """lookup 单行结果（四列 + 如实 flag）。

    Attributes:
        l_m: 沟长（m，请求值；越界时=夹到的边界值）
        gmid_per_v: gm/ID（V^-1，请求值；越界时=夹到的边界值）
        id_w_a_per_m: 单位宽度电流 ID/W（A/m，数值上等于 uA/um）
        gm_gds: 本征增益 gm/gds（V/V）
        f_t_hz: 特征频率 fT = gm/(2*pi*Cgg)（Hz）
        vgs_v: 栅源偏置（V）
        clamped_axes: 被夹到边界的轴名元组（空元组=网格内插值，无外推）
    """

    l_m: float
    gmid_per_v: float
    id_w_a_per_m: float
    gm_gds: float
    f_t_hz: float
    vgs_v: float
    clamped_axes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """service 层 JSON 直出形态。"""
        return {
            "l_m": self.l_m, "gmid_per_v": self.gmid_per_v,
            "id_w_a_per_m": self.id_w_a_per_m, "gm_gds": self.gm_gds,
            "f_t_hz": self.f_t_hz, "vgs_v": self.vgs_v,
            "clamped_axes": list(self.clamped_axes),
        }


@dataclass(frozen=True)
class GmIdSizeResult:
    """size / size_from_ft 反解结果。

    Attributes:
        w_m: 反解沟宽（m）；size_from_ft 未给 id 时为 None（欠定，如实 None）
        l_m: 沟长（m，请求值）
        gmid_per_v: 反解出的 gm/ID 工作点（V^-1）
        vgs_v: 该工作点栅源偏置（V）
        id_w_a_per_m: 单位宽度电流（A/m）
        gm_gds: 本征增益（V/V）
        f_t_hz: 特征频率（Hz）
        clamped_axes: 越界夹取轴名元组（含 l 轴与 gmid 轴）
    """

    w_m: float | None
    l_m: float
    gmid_per_v: float
    vgs_v: float
    id_w_a_per_m: float
    gm_gds: float
    f_t_hz: float
    clamped_axes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """service 层 JSON 直出形态。"""
        return {
            "w_m": self.w_m, "l_m": self.l_m, "gmid_per_v": self.gmid_per_v,
            "vgs_v": self.vgs_v, "id_w_a_per_m": self.id_w_a_per_m,
            "gm_gds": self.gm_gds, "f_t_hz": self.f_t_hz,
            "clamped_axes": list(self.clamped_axes),
        }


# ---------------------------------------------------------------------------
# 表对象与落盘
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class GmIdTable:
    """gm/ID 查表：轴 (L, gm/ID) + 四列网格值（numpy 承载，YAML 落盘）。

    四列语义与 W 无关（gm/ID 方法论不变量）：同 (L, gm/ID) 点的
    id_w/gm_gds/f_t/vgs 对任意 W 成立；W 反解走 ``size``（W = id / id_w）。
    """

    source: dict[str, Any]
    sweep: dict[str, Any]
    l_um: np.ndarray  # (n_l,) 严格递增
    gmid_per_v: np.ndarray  # (n_g,) 严格递增
    id_w_a_per_m: np.ndarray  # (n_l, n_g)
    gm_gds: np.ndarray  # (n_l, n_g)
    f_t_hz: np.ndarray  # (n_l, n_g)
    vgs_v: np.ndarray  # (n_l, n_g)

    def to_dict(self) -> dict[str, Any]:
        """YAML 可落盘字典（columns 键序 = 行内序；无时间戳，确定性）。"""
        values: list[dict[str, Any]] = []
        for i, l_val in enumerate(self.l_um.tolist()):
            rows = [[float(self.id_w_a_per_m[i, j]), float(self.gm_gds[i, j]),
                     float(self.f_t_hz[i, j]), float(self.vgs_v[i, j])]
                    for j in range(self.gmid_per_v.size)]
            values.append({"l_um": l_val, "rows": rows})
        return {
            "schema": SCHEMA,
            "table_version": TABLE_VERSION,
            "source": self.source,
            "sweep": self.sweep,
            "l_um": self.l_um.tolist(),
            "gmid_per_v": self.gmid_per_v.tolist(),
            "columns": list(_COLUMNS),
            "values": values,
        }

    def save_yaml(self, path: str | Path) -> Path:
        """落盘 YAML（父目录自动创建；UTF-8 显式编码）。"""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        text = yaml.safe_dump(self.to_dict(), sort_keys=False,
                              allow_unicode=True, default_flow_style=False)
        p.write_text(text, encoding="utf-8")
        return p

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GmIdTable:
        """从字典校验重构（schema/版本/形状/有限性显式报错）。"""
        if data.get("schema") != SCHEMA:
            raise ValueError(
                f"schema 不匹配：期望 {SCHEMA!r}，收到 {data.get('schema')!r}")
        if data.get("table_version") != TABLE_VERSION:
            raise ValueError(
                f"table_version 不匹配：期望 {TABLE_VERSION}，"
                f"收到 {data.get('table_version')!r}")
        if tuple(data.get("columns") or ()) != _COLUMNS:
            raise ValueError(
                f"columns 不匹配：期望 {list(_COLUMNS)}，收到 {data.get('columns')!r}")
        source = data.get("source")
        if not isinstance(source, dict) or not str(source.get("name") or "").strip():
            raise ValueError("source 块缺失或 name 为空（来源键必填）")
        sweep = data.get("sweep")
        if not isinstance(sweep, dict):
            raise ValueError("sweep 块缺失")
        l_um = np.asarray(data["l_um"], dtype=float)
        gmid = np.asarray(data["gmid_per_v"], dtype=float)
        if l_um.ndim != 1 or l_um.size < 1:
            raise ValueError("l_um 必须为非空一维数组")
        if gmid.ndim != 1 or gmid.size < 2:
            raise ValueError("gmid_per_v 必须为长度 >=2 的一维数组")
        if not np.all(np.diff(l_um) > 0.0):
            raise ValueError("l_um 必须严格递增")
        if not np.all(np.diff(gmid) > 0.0):
            raise ValueError("gmid_per_v 必须严格递增")
        if np.any(l_um <= 0.0) or np.any(gmid <= 0.0):
            raise ValueError("l_um / gmid_per_v 必须全为正")
        values = data.get("values")
        if not isinstance(values, list) or len(values) != l_um.size:
            raise ValueError(
                f"values 行数({len(values) if isinstance(values, list) else 'NA'})"
                f" != l_um 长度({l_um.size})")
        cols = {k: np.empty((l_um.size, gmid.size), dtype=float)
                for k in _COLUMNS}
        for i, entry in enumerate(values):
            if not isinstance(entry, dict) or "rows" not in entry:
                raise ValueError(f"values[{i}] 缺 rows 块")
            rows = entry["rows"]
            if len(rows) != gmid.size:
                raise ValueError(
                    f"values[{i}].rows 长度({len(rows)}) != gmid_per_v 长度({gmid.size})")
            for j, row in enumerate(rows):
                if len(row) != len(_COLUMNS):
                    raise ValueError(
                        f"values[{i}].rows[{j}] 列数({len(row)}) != {len(_COLUMNS)}")
                for k, key in enumerate(_COLUMNS):
                    cols[key][i, j] = float(row[k])
        for key in _COLUMNS:
            if not np.all(np.isfinite(cols[key])):
                raise ValueError(f"列 {key} 含非有限值（不静默收 NaN）")
        if np.any(cols["id_w_a_per_m"] <= 0.0):
            raise ValueError("列 id_w_a_per_m 必须全为正（size 反解 W 的前提）")
        return cls(source=source, sweep=sweep, l_um=l_um, gmid_per_v=gmid,
                   id_w_a_per_m=cols["id_w_a_per_m"], gm_gds=cols["gm_gds"],
                   f_t_hz=cols["f_t_hz"], vgs_v=cols["vgs_v"])

    @classmethod
    def load_yaml(cls, path: str | Path) -> GmIdTable:
        """从 YAML 读回（safe_load；校验走 from_dict）。"""
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"表文件不是映射：{path}")
        return cls.from_dict(data)


# ---------------------------------------------------------------------------
# 建表器
# ---------------------------------------------------------------------------
def _require_keys(d: dict[str, float], l_m: float, vgs_v: float) -> None:
    missing = [k for k in ("id", "gm", "gds", "cgg") if k not in d]
    if missing:
        raise ValueError(
            f"特性化源返回缺键 {missing}（协议要求 id/gm/gds/cgg 四键；"
            f"L={l_m} VGS={vgs_v}）")


def _gmid_of(d: dict[str, float]) -> float:
    return float(d["gm"]) / float(d["id"])


def _row_of(d: dict[str, float], w_unit_m: float,
            vgs_v: float) -> tuple[float, float, float, float]:
    """源点 -> (id_w, gm_gds, f_t, vgs) 四元组。"""
    gm = float(d["gm"])
    gds = float(d["gds"])
    cgg = float(d["cgg"])
    if gds <= 0.0:
        raise ValueError(f"源返回 gds<=0（VGS={vgs_v}），gm/gds 无定义")
    if cgg <= 0.0:
        raise ValueError(f"源返回 cgg<=0（VGS={vgs_v}），fT 无定义")
    id_w = float(d["id"]) / w_unit_m
    return id_w, gm / gds, gm / (2.0 * math.pi * cgg), float(vgs_v)


def _vgs_grid(start: float, stop: float, step: float) -> np.ndarray:
    """确定性 VGS 扫描网格（终点精确收进；步长 > 0）。"""
    if step <= 0.0 or stop <= start:
        raise ValueError(
            f"vgs 扫描参数非法：start={start!r} stop={stop!r} step={step!r}")
    n = math.floor((stop - start) / step + 1e-9)
    grid = start + step * np.arange(n + 1, dtype=float)
    grid = grid[grid <= stop + 1e-12]
    if grid[-1] < stop - 1e-12:
        grid = np.append(grid, stop)
    grid[-1] = stop
    return grid


def _characterize(source: CharacterizationSource, w_unit_m: float, l_m: float,
                  f_char_hz: float, vgs_grid: np.ndarray) -> tuple[
        np.ndarray, np.ndarray, list[tuple[float, float, float]]]:
    """单 L 全 VGS 扫描特性化：返回 (vgs, gmid, [(id_w, gm_gds, f_t)]）。"""
    vgs_list: list[float] = []
    gmid_list: list[float] = []
    rows: list[tuple[float, float, float]] = []
    for vgs in vgs_grid.tolist():
        d = source(w_unit_m, l_m, vgs, f_char_hz)
        _require_keys(d, l_m, vgs)
        id_a = float(d["id"])
        if not (id_a > 0.0 and math.isfinite(id_a)):
            raise ValueError(
                f"特性化源返回 id<=0 或非有限（L={l_m} VGS={vgs}）——gm/ID 无定义；"
                "请丢弃零流点或改用平滑闭式源")
        gmid = _gmid_of(d)
        if not (math.isfinite(gmid) and gmid > 0.0):
            raise ValueError(f"gm/ID 非正或非有限（L={l_m} VGS={vgs}）")
        vgs_list.append(vgs)
        gmid_list.append(gmid)
        rows.append(_row_of(d, w_unit_m, vgs))
    return np.asarray(vgs_list), np.asarray(gmid_list), rows


def _fall_branch(vgs: np.ndarray, gmid: np.ndarray,
                 rows: list[tuple[float, float, float]]) -> tuple[
        np.ndarray, np.ndarray, list[tuple[float, float, float]]]:
    """_fall_mask 折返防护：只保留 gm/ID 峰值之后的非增下降支。

    真实器件 gm/ID vs VGS 峰值两侧双值；查表反解要求单值支，故丢弃亚阈
    上升支（含峰前所有点），并对下降支内的浮点噪声/源非单调抖动做非增
    过滤（高于运行最小值的点丢弃）。返回 (vgs, gmid, rows) 下降支。
    """
    peak = int(np.argmax(gmid))
    keep: list[int] = [peak]
    for i in range(peak + 1, gmid.size):
        if gmid[i] <= gmid[keep[-1]]:
            keep.append(i)
    if len(keep) < 2:
        raise ValueError(
            "gm/ID 下降支不足 2 点（扫描区间未进入反型下降段）——请加宽 vgs 扫描")
    idx = np.asarray(keep, dtype=int)
    return vgs[idx], gmid[idx], [rows[i] for i in keep]


def _check_branch_coverage(gmid_branch: np.ndarray,
                           gmid_grid: np.ndarray, l_m: float) -> None:
    """gmid 网格必须被下降支覆盖（两端），不满足显式报错。"""
    b_max = float(gmid_branch[0])  # 下降支首点=最大
    b_min = float(gmid_branch[-1])
    g_lo = float(gmid_grid[0])
    g_hi = float(gmid_grid[-1])
    if g_hi > b_max + 1e-9:
        raise ValueError(
            f"gmid 网格上端 {g_hi} V^-1 超出源可达峰值 {b_max:.6g} V^-1"
            f"（L={l_m}）——请加宽 vgs 低端扫描或收紧网格")
    if g_lo < b_min - 1e-9:
        raise ValueError(
            f"gmid 网格下端 {g_lo} V^-1 低于源可达最小 {b_min:.6g} V^-1"
            f"（L={l_m}）——请加宽 vgs 高端扫描（vgs_stop）")


def _solve_vgs_for_gmid(source: CharacterizationSource, w_unit_m: float,
                        l_m: float, f_char_hz: float, gmid_target: float,
                        gmid_asc: np.ndarray, vgs_asc: np.ndarray) -> float:
    """在相邻扫描点括号内二分求 VGS（下降支上 gmid(VGS)=target）。

    下降支语义：gmid 随 VGS 单调**递减**（_fall_branch 输出）；括号按
    VGS 数值序取端点，gmid(v_lo) >= target >= gmid(v_hi)。
    """
    n = gmid_asc.size
    hi = int(np.searchsorted(gmid_asc, gmid_target))
    hi = min(max(hi, 1), n - 1)
    lo = hi - 1
    va, vb = sorted((float(vgs_asc[lo]), float(vgs_asc[hi])))
    # va < vb（VGS 数值序）；gmid(va) >= target >= gmid(vb)
    for _ in range(200):
        vm = 0.5 * (va + vb)
        if vb - va <= 1e-15 * max(1.0, abs(vm)):
            return vm
        d = source(w_unit_m, l_m, vm, f_char_hz)
        _require_keys(d, l_m, vm)
        if _gmid_of(d) > gmid_target:
            va = vm  # gmid 仍偏高 -> 根在更高 VGS 处
        else:
            vb = vm
    return 0.5 * (va + vb)


def _validate_build_inputs(l_grid_m: Any, gmid_grid_per_v: Any,
                           w_unit_m: float, f_char_hz: float,
                           source_meta: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    if w_unit_m <= 0.0 or f_char_hz <= 0.0:
        raise ValueError("w_unit_m / f_char_hz 必须 > 0")
    if not isinstance(source_meta, dict) or not str(
            source_meta.get("name") or "").strip():
        raise ValueError("source_meta 必须含非空 name（来源键）")
    l_arr = np.asarray(l_grid_m, dtype=float)
    g_arr = np.asarray(gmid_grid_per_v, dtype=float)
    if l_arr.ndim != 1 or l_arr.size < 1 or not np.all(np.diff(l_arr) > 0.0) \
            or np.any(l_arr <= 0.0):
        raise ValueError("l_grid_m 必须为严格递增的正一维数组")
    if g_arr.ndim != 1 or g_arr.size < 2 or not np.all(np.diff(g_arr) > 0.0) \
            or np.any(g_arr <= 0.0):
        raise ValueError("gmid_grid_per_v 必须为严格递增的正一维数组（长度 >=2）")
    return l_arr, g_arr


def build_gmid_table(source: CharacterizationSource, *,
                     source_meta: dict[str, Any],
                     l_grid_m: Any, gmid_grid_per_v: Any,
                     w_unit_m: float = 1.0e-6, f_char_hz: float = 1.0e6,
                     vgs_start_v: float = 0.0, vgs_stop_v: float = 1.8,
                     vgs_step_v: float = 2.0e-3,
                     refine: bool = True) -> GmIdTable:
    """扫描特性化 -> fall-mask 下降支 -> gmid 网格分箱 -> 表对象。

    Args:
        source: 特性化数据源（协议见 ``CharacterizationSource``）。
        source_meta: 来源键（name/kind/precision/params；外部源必填）。
        l_grid_m: L 轴（m，严格递增）。
        gmid_grid_per_v: gm/ID 轴（V^-1，严格递增，长度 >=2）。
        w_unit_m: 单位宽度建表宽（默认 1um；四列与 W 无关，W 只进归一基准）。
        f_char_hz: 特性化频率点（按源协议传递；准静态源不消费）。
        vgs_start_v/vgs_stop_v/vgs_step_v: VGS 扫描（确定性网格）。
        refine: True（默认）时每个 gmid 网格节点在相邻扫描点括号内二分回解
            VGS（额外调用源，节点行=源直接评估，无插值误差）；False 时节点
            行由扫描点线性插值（省调用，节点值带插值误差——两档行为均如实
            记录在 sweep.refine）。

    Returns:
        GmIdTable（纯数据对象，可落盘/查表/反解）。

    Raises:
        ValueError: 网格/sweep 参数非法、源缺键/零流点、gmid 网格未被
            下降支覆盖（不静默截断）。
    """
    l_arr, g_arr = _validate_build_inputs(l_grid_m, gmid_grid_per_v,
                                          w_unit_m, f_char_hz, source_meta)
    vgs_grid = _vgs_grid(vgs_start_v, vgs_stop_v, vgs_step_v)
    n_l, n_g = l_arr.size, g_arr.size
    cols = {k: np.empty((n_l, n_g), dtype=float) for k in _COLUMNS}
    for il in range(n_l):
        l_m = float(l_arr[il])
        vgs_s, gmid_s, rows_s = _characterize(source, w_unit_m, l_m,
                                              f_char_hz, vgs_grid)
        vgs_b, gmid_b, rows_b = _fall_branch(vgs_s, gmid_s, rows_s)
        _check_branch_coverage(gmid_b, g_arr, l_m)
        gmid_asc = gmid_b[::-1]
        vgs_asc = vgs_b[::-1]
        rows_asc = {key: np.asarray([r[k] for r in rows_b])[::-1]
                    for k, key in enumerate(("id_w", "gm_gds", "f_t"))}
        for ig in range(n_g):
            g = float(g_arr[ig])
            if refine:
                vgs_star = _solve_vgs_for_gmid(source, w_unit_m, l_m,
                                               f_char_hz, g, gmid_asc, vgs_asc)
                d = source(w_unit_m, l_m, vgs_star, f_char_hz)
                _require_keys(d, l_m, vgs_star)
                row = _row_of(d, w_unit_m, vgs_star)
            else:
                vgs_star = float(np.interp(g, gmid_asc, vgs_asc))
                row = (float(np.interp(g, gmid_asc, rows_asc["id_w"])),
                       float(np.interp(g, gmid_asc, rows_asc["gm_gds"])),
                       float(np.interp(g, gmid_asc, rows_asc["f_t"])),
                       vgs_star)
            for k, key in enumerate(_COLUMNS):
                cols[key][il, ig] = row[k]
    sweep = {
        "w_unit_m": float(w_unit_m), "f_char_hz": float(f_char_hz),
        "vgs_start_v": float(vgs_start_v), "vgs_stop_v": float(vgs_stop_v),
        "vgs_step_v": float(vgs_step_v), "refine": bool(refine),
    }
    return GmIdTable(source=source_meta, sweep=sweep, l_um=l_arr * 1.0e6,
                     gmid_per_v=g_arr, id_w_a_per_m=cols["id_w_a_per_m"],
                     gm_gds=cols["gm_gds"], f_t_hz=cols["f_t_hz"],
                     vgs_v=cols["vgs_v"])


# ---------------------------------------------------------------------------
# 查表与反解
# ---------------------------------------------------------------------------
def _bracket(grid: np.ndarray, x: float) -> tuple[int, int, float, bool]:
    """升序网格括号：返回 (i0, i1, frac, clamped)。越界=端点夹取+flag。"""
    if x < grid[0]:
        return 0, 0, 0.0, True
    if x > grid[-1]:
        return grid.size - 1, grid.size - 1, 0.0, True
    i1 = int(np.searchsorted(grid, x))
    if i1 <= 0:
        return 0, 0, 0.0, False
    if i1 >= grid.size:
        return grid.size - 1, grid.size - 1, 0.0, False
    i0 = i1 - 1
    span = grid[i1] - grid[i0]
    frac = 0.0 if span <= 0.0 else (x - grid[i0]) / span
    return i0, i1, float(min(max(frac, 0.0), 1.0)), False


def _interp_row_at_gmid(table: GmIdTable, il: int,
                        gmid: float) -> tuple[tuple[float, float, float, float], bool]:
    """在 L 行 il 内沿 gmid 轴线性插值四列（越界夹取+flag）。"""
    g = table.gmid_per_v
    i0, i1, frac, clamped = _bracket(g, gmid)
    row = tuple(
        float(getattr(table, col)[il, i0])
        + frac * (float(getattr(table, col)[il, i1])
                  - float(getattr(table, col)[il, i0]))
        for col in _COLUMNS)
    return (row[0], row[1], row[2], row[3]), clamped


def lookup(table: GmIdTable, l_m: float, gmid_per_v: float) -> GmIdRow:
    """查表：(L, gm/ID) -> 行（双线性插值；越界=端点夹取+flag，不静默外推）。

    Args:
        table: 表对象（``build_gmid_table`` / ``GmIdTable.load_yaml`` 产物）。
        l_m: 沟长（m）。
        gmid_per_v: gm/ID 工作点（V^-1）。

    Returns:
        GmIdRow；``clamped_axes`` 非空 = 请求点越界、值=最近边界端点
        （nearest-with-flag，如实不静默）。
    """
    if not (math.isfinite(l_m) and math.isfinite(gmid_per_v)):
        raise ValueError("lookup 入参必须有限")
    l_grid = table.l_um
    l_val = l_m * 1.0e6  # m -> um（表内轴单位）
    clamped: list[str] = []
    li0, li1, frac_l, c_l = _bracket(l_grid, l_val)
    if c_l:
        clamped.append("l")
    row0, c_g0 = _interp_row_at_gmid(table, li0, gmid_per_v)
    row1, c_g1 = _interp_row_at_gmid(table, li1, gmid_per_v)
    if c_g0 or c_g1:
        clamped.append("gmid")
    row = tuple(a + frac_l * (b - a) for a, b in zip(row0, row1, strict=True))
    return GmIdRow(l_m=l_m, gmid_per_v=gmid_per_v, id_w_a_per_m=row[0],
                   gm_gds=row[1], f_t_hz=row[2], vgs_v=row[3],
                   clamped_axes=tuple(dict.fromkeys(clamped)))


def _columns_at_l(table: GmIdTable, l_m: float) -> tuple[dict[str, np.ndarray], list[str]]:
    """L 轴插值出该 L 的四列（沿 gmid 网格；越界夹取+flag）。"""
    l_val = l_m * 1.0e6
    li0, li1, frac_l, c_l = _bracket(table.l_um, l_val)
    clamped = ["l"] if c_l else []
    cols = {col: getattr(table, col)[li0]
            + frac_l * (getattr(table, col)[li1]
                        - getattr(table, col)[li0])
            for col in _COLUMNS}
    return cols, clamped


def _invert_column(x_grid: np.ndarray, y: np.ndarray,
                   y_target: float) -> tuple[float, bool]:
    """单调列反解：首个括号线性插值；出界=端点+flag（不静默外推）。

    表构造器（build_gmid_table）产出的列在其模型类下单调；注入的第三方表
    若非单调，取表序首个括号（行为确定性并在 docstring 声明）。
    """
    for i in range(y.size - 1):
        y0, y1 = float(y[i]), float(y[i + 1])
        if (y0 - y_target) * (y1 - y_target) <= 0.0 and y1 != y0:
            frac = (y_target - y0) / (y1 - y0)
            frac = min(max(frac, 0.0), 1.0)
            x0, x1 = float(x_grid[i]), float(x_grid[i + 1])
            return x0 + frac * (x1 - x0), False
    # 出界：夹最近端点
    if y_target < float(y[0]) or y_target > float(y[-1]):
        if abs(y_target - float(y[0])) <= abs(y_target - float(y[-1])):
            return float(x_grid[0]), True
        return float(x_grid[-1]), True
    return float(x_grid[0]), True  # 理论不可达（括号必中其一）；防御性端点


def size(table: GmIdTable, *, l_m: float, id_a: float | None = None,
         gm_s: float | None = None, w_m: float | None = None) -> GmIdSizeResult:
    """反解定尺寸：{id, gm, w} 任给两维 + L -> (W, L, VGS, gmid, ...)。

    - (id, gm)：gmid = gm/id 直查行，W = id/ID_W；
    - (id, w)：ID/W 目标反解 gmid 列（下降支单调）；
    - (gm, w)：gm/W 目标反解 gm/W 列。

    Args:
        table: 表对象。
        l_m: 沟长（m；方法论五步流的第二拍由设计者先定 L）。
        id_a/gm_s/w_m: 三维任给两维（漏电流 A / 跨导 S / 沟宽 m），其余为 None。

    Returns:
        GmIdSizeResult（w_m 恒有值；clamped_axes 如实携带越界 flag）。

    Raises:
        ValueError: 给的维数 != 2、入参非正或非有限。
    """
    given = {"id": id_a, "gm": gm_s, "w": w_m}
    present = [k for k, v in given.items() if v is not None]
    if len(present) != 2:
        raise ValueError(
            f"size 必须且只能给 id/gm/w 三维中的两维（收到 {present}）"
            "——方法论：gm/ID 枢轴量 + L 先行")
    for k, v in given.items():
        if v is not None and not (math.isfinite(v) and v > 0.0):
            raise ValueError(f"size.{k} 必须为正有限，收到 {v!r}")
    clamped: list[str] = []
    if id_a is not None and gm_s is not None:
        gmid = gm_s / id_a
        row = lookup(table, l_m, gmid)
        clamped.extend(row.clamped_axes)
        w_val = id_a / row.id_w_a_per_m
    else:
        cols, c_l = _columns_at_l(table, l_m)
        clamped.extend(c_l)
        if id_a is not None and w_m is not None:
            target = id_a / w_m
            gmid, c_g = _invert_column(table.gmid_per_v,
                                       np.asarray(cols["id_w_a_per_m"]), target)
        elif gm_s is not None and w_m is not None:
            target = gm_s / w_m
            gm_w_col = table.gmid_per_v * np.asarray(cols["id_w_a_per_m"])
            gmid, c_g = _invert_column(table.gmid_per_v, gm_w_col, target)
        else:  # pragma: no cover — 维数校验已挡
            raise ValueError("unreachable")
        if c_g:
            clamped.append("gmid")
        row = lookup(table, l_m, gmid)
        clamped.extend(row.clamped_axes)
        w_val = w_m if w_m is not None else id_a / row.id_w_a_per_m
    return GmIdSizeResult(
        w_m=float(w_val), l_m=l_m, gmid_per_v=row.gmid_per_v,
        vgs_v=row.vgs_v, id_w_a_per_m=row.id_w_a_per_m, gm_gds=row.gm_gds,
        f_t_hz=row.f_t_hz, clamped_axes=tuple(dict.fromkeys(clamped)))


def size_from_ft(table: GmIdTable, *, f_t_hz: float, l_m: float,
                 id_a: float | None = None) -> GmIdSizeResult:
    """按 fT 反查：fT 目标 + L（可附带 id）-> gm/ID 工作点行（/W）。

    fT 列在 gm/ID 轴上随 gmid 增大而减小（弱反型 fT->0）；反解取表序首个
    括号。fT 目标超出该 L 的 fT 范围时=端点夹取+flag（不静默外推）。

    Args:
        table: 表对象。
        f_t_hz: fT 目标（Hz，> 0）。
        l_m: 沟长（m）。
        id_a: 可选漏电流（A）——给了才反解 W（欠定维度如实 None）。

    Returns:
        GmIdSizeResult（w_m=None 当 id_a 未给）。
    """
    if not (math.isfinite(f_t_hz) and f_t_hz > 0.0):
        raise ValueError(f"f_t_hz 必须为正有限，收到 {f_t_hz!r}")
    if id_a is not None and not (math.isfinite(id_a) and id_a > 0.0):
        raise ValueError(f"id_a 必须为正有限，收到 {id_a!r}")
    cols, c_l = _columns_at_l(table, l_m)
    clamped: list[str] = ["l"] if c_l else []
    gmid, c_g = _invert_column(table.gmid_per_v,
                               np.asarray(cols["f_t_hz"]), f_t_hz)
    if c_g:
        clamped.append("gmid")
    row = lookup(table, l_m, gmid)
    clamped.extend(row.clamped_axes)
    w_val = None if id_a is None else id_a / row.id_w_a_per_m
    return GmIdSizeResult(
        w_m=w_val, l_m=l_m, gmid_per_v=row.gmid_per_v, vgs_v=row.vgs_v,
        id_w_a_per_m=row.id_w_a_per_m, gm_gds=row.gm_gds, f_t_hz=row.f_t_hz,
        clamped_axes=tuple(dict.fromkeys(clamped)))


# ---------------------------------------------------------------------------
# 首调建表 + 缓存（指纹缓存键 + 表文件 mtime 失效；run_store/result_cache 风格）
# ---------------------------------------------------------------------------
_TABLE_MEMO: dict[str, GmIdTable] = {}


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name)


def _cache_fingerprint(source_meta: dict[str, Any], sweep: dict[str, Any],
                       l_grid_m: Any, gmid_grid_per_v: Any) -> str:
    payload = {"schema": SCHEMA, "source": source_meta, "sweep": sweep,
               "l_grid_m": [float(x) for x in np.atleast_1d(l_grid_m)],
               "gmid_grid_per_v": [float(x) for x in np.atleast_1d(gmid_grid_per_v)]}
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _memo_key(path: Path) -> str | None:
    """进程内 memo 键 = 路径|mtime_ns|size（表文件 mtime+指纹缓存键）。"""
    try:
        st = path.stat()
    except OSError:
        return None
    return f"{path}|{st.st_mtime_ns}|{st.st_size}"


def _prune_memo(path: Path, keep: str) -> None:
    prefix = f"{path}|"
    stale = [k for k in _TABLE_MEMO if k.startswith(prefix) and k != keep]
    for k in stale:
        _TABLE_MEMO.pop(k, None)


def clear_table_cache() -> None:
    """清空进程内表 memo（测试/换源显式调用）。"""
    _TABLE_MEMO.clear()


def get_or_build_table(source: CharacterizationSource, *, cache_dir: str | Path,
                       source_meta: dict[str, Any] | None = None,
                       l_grid_m: Any = None, gmid_grid_per_v: Any = None,
                       w_unit_m: float = 1.0e-6, f_char_hz: float = 1.0e6,
                       vgs_start_v: float = 0.0, vgs_stop_v: float = 1.8,
                       vgs_step_v: float = 2.0e-3,
                       refine: bool = True) -> GmIdTable:
    """首调建表+缓存：指纹寻址 YAML 落盘，命中直读，缺失重建。

    缓存键三件套（result_cache 内容寻址风格的 gm/ID 落地）：

    - **指纹**：sha256(canonical json(source_meta + sweep + 两轴网格)) 进
      文件名——源身份/参数/网格任一变化 = 新文件 = 必 miss；
    - **表文件 mtime+size**：进程内 memo 键——同进程重复调用零解析开销；
      表文件被外部改动（mtime/size 变）= memo 失效重读磁盘（不静默用旧值）；
    - **文件缺失**：重建并落盘（真机源重建=重新特性化，代价如实落在源侧）。

    Args:
        source: 特性化数据源（SyntheticMosSource 可省 source_meta）。
        cache_dir: 缓存目录（真机表建议 runs/ 或用户本地目录，**不进仓**）。
        source_meta: 来源键；None 时仅 SyntheticMosSource 可自报。
        其余参数: 透传 ``build_gmid_table``（两轴网格必填）。

    Raises:
        ValueError: 外部源未提供 source_meta，或建表参数非法。
    """
    if l_grid_m is None or gmid_grid_per_v is None:
        raise ValueError("l_grid_m / gmid_grid_per_v 必填（查表轴显式声明）")
    if source_meta is None:
        if isinstance(source, SyntheticMosSource):
            source_meta = source.source_meta()
        else:
            raise ValueError(
                "外部特性化源必须显式提供 source_meta（来源键 name/kind/precision）")
    sweep = {"w_unit_m": float(w_unit_m), "f_char_hz": float(f_char_hz),
             "vgs_start_v": float(vgs_start_v), "vgs_stop_v": float(vgs_stop_v),
             "vgs_step_v": float(vgs_step_v), "refine": bool(refine)}
    fp = _cache_fingerprint(source_meta, sweep, l_grid_m, gmid_grid_per_v)
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"gmid_{_safe_name(str(source_meta['name']))}_{fp[:16]}.yaml"
    key = _memo_key(path)
    if key is not None:
        hit = _TABLE_MEMO.get(key)
        if hit is not None:
            return hit
        table = GmIdTable.load_yaml(path)
        _TABLE_MEMO[key] = table
        _prune_memo(path, key)
        return table
    table = build_gmid_table(source, source_meta=source_meta, l_grid_m=l_grid_m,
                             gmid_grid_per_v=gmid_grid_per_v, w_unit_m=w_unit_m,
                             f_char_hz=f_char_hz, vgs_start_v=vgs_start_v,
                             vgs_stop_v=vgs_stop_v, vgs_step_v=vgs_step_v,
                             refine=refine)
    table.save_yaml(path)
    key = _memo_key(path)
    if key is not None:
        _TABLE_MEMO[key] = table
    return table
