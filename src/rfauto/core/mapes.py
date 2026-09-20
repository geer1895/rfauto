"""MAPES stage-1：像素解析电磁仿真器闭式内核（纯代码 / fake Z_ALL / 零真机）。

依据
----
- Rao et al., arXiv:2511.21274v3 原文实读口径；
- staged 接入路径：stage-1 纯代码先导、predict(params) 平铺契约、
  topology_key + 展平布尔映射约定。

机制（stage-0 实读口径，不凭想象补公式）
----------------------------------------
1. **一次性预处理**：对像素设计域跑一次全波多端口仿真，提取"全端口阻抗
   矩阵" `Z_ALL`——端口含外部 I/O、虚拟像素、对角虚拟像素、地/层间过孔
   四类虚拟端口（统一 50Ω，S→Z 转换）。
2. **占用→对角负载映射**：任意像素图案 `P` 逐端口判定——缺席像素/无过孔
   = 开路（该虚拟端口不接负载），在场 = 短路（`Z_L = 0`），得对角负载
   矩阵 `Z_L(P)`。
3. **Schur 补闭式求检**：把 `Z_ALL` 按 外部端口(1)/虚拟端口(2) 分块，
   由端口关系 `V_2 = -Z_L(P) I_2` 消去虚拟端口：

       Z_MAPES = Z_11 - Z_12 (Z_22 + Z_L(P))^{-1} Z_21

   再 `S = (Z_MAPES - Z_0)(Z_MAPES + Z_0)^{-1}` 得外端口 S 参数。
   **不再做任何全波计算**。
4. **互易/无源**由 Schur 补结构天然保证（`Z_ALL` 互易无源 + 无源对角负载）。

独立裁判（不得自证）
--------------------------
本模块的闭式路径是 `load_network_z`（Z_ALL 分块 + Schur 补）；
:func:`nodal_reference_s` 是**完全独立**的第二条路径：直接对底层物理网络
写节点方程（Kirchhoff + 端口戴维南约束 `V_i + Z_0 I_i = 2 sqrt(Z_0) a_i`），
用 `numpy.linalg.solve` 解全节点方程组取 S——不经过 Z_ALL、不经过 Schur
补。两条路径的一致性在 tests/unit/test_mapes.py 中钉死。

stage-1 边界（诚实声明）
------------------------
- `Z_ALL` 由本模块 :class:`RlcMesh` / :func:`fake_mesh` 合成（显式构造的
  互易无源 RLC 网格），**不是真机提取**；stage-2 才接
  adapters/openems_rotation.py 多端口轮转。
- 像素域端口编号是本模块自定约定 :class:`PixelLayout`（逐像素占位口 +
  4/8 邻域耦合端口 + 过孔槽），**不复刻原文 Fig. 的虚拟端口格点**；原文端口数公式
  `Q = L(6MN-3M-3N+4) + (L-1)MN` 以 :func:`paper_port_count` 保留为参考，
  其 "+4" 物理落位仍是 stage-0 遗留 openQuestion。
- β（虚拟像素占比 0.70-0.85）/α（全局缩放）校准超参**不在 stage-1**，
  走 stage-3 的 #190 校准范式（HFSS 仲裁背书后再定常数）。stage-4 落了
  确定性 α 内核：:class:`MapesModel` keyword-only ``alpha``（频率缩放，
  提取网格上插值）+ :func:`fit_alpha_scaling`（对直接全波案网格搜索 +
  留一验证）；α 数值是否被 HFSS 背书由调用方标注（openEMS 同引擎对拍
  得到的 α 只是 openEMS-internal）。
- 与 `SurrogateModel` 契约兼容（`KIND` + `predict(params) -> metrics`
  平铺 dict + `uncertainty` 返回 None），本模块**不注册**任何 registry。

像素域约定（stage-1 固定，测试钉死）
-----------------------------------
`M x N` 像素矩阵 `P` 的布尔占位。可加载虚拟端口槽按下列顺序连续编号
（0-based，紧随外部 I/O 端口之后）：

1. `pixel`：逐像素占位口 `(r,c)`，`M*N` 个，行主序——**缺席=开路、
   在场=短路**（占用→对角负载字面口径）；
2. `pixel_h`：行内相邻耦合 `(r,c)-(r,c+1)`，`M*(N-1)` 个，行主序；
3. `pixel_v`：列内相邻耦合 `(r,c)-(r+1,c)`，`(M-1)*N` 个，行主序；
4. `diag_main`：对角虚拟像素 `(r,c)-(r+1,c+1)`，`(M-1)*(N-1)` 个；
5. `diag_anti`：反对角虚拟像素 `(r,c+1)-(r+1,c)`，`(M-1)*(N-1)` 个；
6. 过孔槽：`via_slots` 声明顺序（`via_ground` / `via_interlayer`）。

`pixel` 槽的占用 = 该像素自身；`pixel_h/v`、`diag_main/anti` 耦合槽的
占用 = 两端像素**同时在场**（AND）；过孔槽的占用 = 该过孔声明在场。

假设（stage-1，未与原文 Fig. 逐格核对）：把邻域耦合也建成独立加载口，
是为覆盖原文"虚拟像素/对角虚拟像素捕获水平/垂直/对角耦合"的机制；
若原文实际只用"两端像素之间的 gap 口"（无逐像素口），则本约定用
逐像素口近似其中一类——两种口径的端口数都**不等于** `paper_port_count`。
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from itertools import pairwise
from typing import Any, NamedTuple

import numpy as np

from rfauto.core.errors import ConfigError

__all__ = [
    "CATEGORY_DIAG_ANTI",
    "CATEGORY_DIAG_MAIN",
    "CATEGORY_PIXEL",
    "CATEGORY_PIXEL_H",
    "CATEGORY_PIXEL_V",
    "DEFAULT_ALPHA_GRID",
    "DEFAULT_REFERENCE_IMPEDANCE",
    "PASSIVE_FLOOR_OHM",
    "PROBE_MIN_GAP_M",
    "RECIPROCITY_CALIBERS",
    "RECIPROCITY_TARGET_STAGE5C",
    "UI_DRIFT_SNR_EDGES",
    "VIA_GROUND",
    "VIA_INTERLAYER",
    "ZALL_GATE_MIN_EIG_RE",
    "ZALL_GATE_RECIPROCITY_MAX",
    "ZALL_GATE_SIGMA_MAX",
    "LoadSlot",
    "MapesModel",
    "MapesResult",
    "PixelBoardGeom",
    "PixelLayout",
    "PortGeom",
    "RlcMesh",
    "apply_port_gain",
    "apply_sref_recal",
    "assemble_s_from_ui",
    "delay_model_delta",
    "dft_time2freq",
    "fake_mesh",
    "fit_alpha_scaling",
    "fit_reciprocity_gain",
    "gauge_factor",
    "load_network_z",
    "nodal_reference_s",
    "occupancy_to_load",
    "paper_port_count",
    "passive_project_z",
    "pixel_board_geom",
    "port_gamma",
    "port_probe_axes",
    "probe_box_guard",
    "probe_midlines",
    "reciprocity_caliber_matrix",
    "reciprocity_pair_residual",
    "s_to_z",
    "sref_column_factors",
    "sref_etht_column_factors",
    "termination_delta",
    "ui_cross_round_drift",
    "wave_decompose_ui",
    "z_all_gate",
    "z_all_gate_caliber",
    "z_all_quality",
    "z_to_s",
]#: 统一参考阻抗（MAPES 原文口径：虚拟端口与外部端口统一 50Ω）。
DEFAULT_REFERENCE_IMPEDANCE = 50.0

CATEGORY_PIXEL = "pixel"
CATEGORY_PIXEL_H = "pixel_h"
CATEGORY_PIXEL_V = "pixel_v"
CATEGORY_DIAG_MAIN = "diag_main"
CATEGORY_DIAG_ANTI = "diag_anti"
VIA_GROUND = "via_ground"
VIA_INTERLAYER = "via_interlayer"
VIA_KINDS = (VIA_GROUND, VIA_INTERLAYER)

_DB_FLOOR = 1.0e-30


class LoadSlot(NamedTuple):
    """一个可加载的虚拟端口槽位。"""

    category: str
    row: int
    col: int
    label: str
    via_index: int = -1


def paper_port_count(n_rows: int, n_cols: int, n_layers: int = 1) -> int:
    """MAPES 原文端口数公式（arXiv:2511.21274v3 实读）。

    `Q = L(6MN - 3M - 3N + 4) + (L-1)MN`

    仅作参考对照：stage-1 的 :class:`PixelLayout` 采用另一套自定编号约定
    （见模块 docstring），两者端口数**不相等**，"+4" 的物理落位仍是
    stage-0 遗留 openQuestion。
    """
    rows = int(n_rows)
    cols = int(n_cols)
    layers = int(n_layers)
    if rows < 1 or cols < 1:
        raise ConfigError(f"像素矩阵尺寸必须 >=1：n_rows={rows}, n_cols={cols}")
    if layers < 1:
        raise ConfigError(f"层数必须 >=1：n_layers={layers}")
    return layers * (6 * rows * cols - 3 * rows - 3 * cols + 4) + (layers - 1) * rows * cols


def _as_square_complex(value: Any, name: str, *, allow_batch: bool = False) -> np.ndarray:
    arr = np.asarray(value, dtype=complex)
    if allow_batch:
        if arr.ndim not in (2, 3) or arr.shape[-1] != arr.shape[-2]:
            raise ConfigError(f"{name} 必须是方阵或方阵批（(n,n) 或 (f,n,n)）")
    elif arr.ndim != 2 or arr.shape[0] != arr.shape[1]:
        raise ConfigError(f"{name} 必须是方阵：(n,n)，实得 shape={arr.shape}")
    if not allow_batch and arr.shape[0] < 1:
        raise ConfigError(f"{name} 维度必须 >=1，实得 shape={arr.shape}")
    return arr


def _as_bool_matrix(occupancy: Any, n_rows: int, n_cols: int) -> np.ndarray:
    arr = np.asarray(occupancy)
    if arr.shape != (n_rows, n_cols):
        raise ConfigError(f"occupancy 形状必须是 ({n_rows},{n_cols})，实得 {arr.shape}")
    if arr.dtype == bool:
        return arr.astype(bool, copy=True)
    flat = arr.reshape(-1)
    if not np.all(np.isin(flat, (0, 1))):
        raise ConfigError("occupancy 只接受 0/1（或 bool）占位值")
    return arr.astype(bool)


def _as_bool_vector(values: Any, n: int, name: str) -> np.ndarray:
    if values is None:
        if n == 0:
            return np.zeros(0, dtype=bool)
        raise ConfigError(f"缺少 {name}（期望长度 {n} 的 0/1 向量）")
    arr = np.asarray(values)
    if arr.shape != (n,):
        raise ConfigError(f"{name} 形状必须是 ({n},)，实得 {arr.shape}")
    if arr.dtype == bool:
        return arr.astype(bool, copy=True)
    if not np.all(np.isin(arr.reshape(-1), (0, 1))):
        raise ConfigError(f"{name} 只接受 0/1（或 bool）值")
    return arr.astype(bool)


def _as_bool_scalar(value: Any, name: str) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, float, np.integer, np.floating)):
        if float(value) in (0.0, 1.0):
            return bool(value)
        raise ConfigError(f"参数 {name!r} 只接受 0/1，实得 {value!r}")
    raise ConfigError(f"参数 {name!r} 只接受 0/1 数值，实得 {type(value).__name__}")


@dataclass(frozen=True)
class PixelLayout:
    """像素域端口编号约定（stage-1 自定，见模块 docstring）。

    端口编号：`0 .. n_io_ports-1` 为外部 I/O 端口，其后按
    :meth:`load_slots` 顺序为可加载的虚拟/过孔端口。
    """

    n_rows: int
    n_cols: int
    n_layers: int = 1
    n_io_ports: int = 2
    via_slots: tuple[tuple[int, int, str], ...] = ()

    def __post_init__(self) -> None:
        if self.n_rows < 1 or self.n_cols < 1:
            raise ConfigError(f"像素矩阵尺寸必须 >=1：{self.n_rows}x{self.n_cols}")
        if self.n_layers < 1:
            raise ConfigError(f"层数必须 >=1：{self.n_layers}")
        if self.n_io_ports < 1:
            raise ConfigError(f"外部端口数必须 >=1：{self.n_io_ports}")
        for slot in self.via_slots:
            if len(slot) != 3:
                raise ConfigError(f"via_slot 必须是 (row, col, kind)：{slot!r}")
            row, col, kind = slot
            if not (0 <= int(row) < self.n_rows and 0 <= int(col) < self.n_cols):
                raise ConfigError(f"via_slot 越界：{slot!r}（矩阵 {self.n_rows}x{self.n_cols}）")
            if kind not in VIA_KINDS:
                raise ConfigError(f"未知过孔种类 {kind!r}，可用 {VIA_KINDS}")
            if kind == VIA_INTERLAYER and self.n_layers < 2:
                raise ConfigError("单层布局不能声明 via_interlayer（无层间连接可短接）")
        if self.n_load_ports < 1:
            raise ConfigError("布局至少需要一个虚拟/过孔端口（否则无可加载端口）")

    # ------------------------------------------------------------------ #
    # 基本量
    # ------------------------------------------------------------------ #
    @property
    def topology_key(self) -> str:
        """拓扑标识（写入展平参数 dict，往返校验用）。"""
        via_part = (
            ",".join(f"{int(r)}:{int(c)}:{k}" for r, c, k in self.via_slots)
            if self.via_slots
            else "-"
        )
        return (
            f"mapes:px{self.n_rows}x{self.n_cols}x{self.n_layers}"
            f":io{self.n_io_ports}:via[{via_part}]"
        )

    def load_slots(self) -> tuple[LoadSlot, ...]:
        """按固定顺序枚举全部可加载虚拟端口槽。"""
        slots: list[LoadSlot] = []
        for r in range(self.n_rows):
            for c in range(self.n_cols):
                slots.append(LoadSlot(CATEGORY_PIXEL, r, c, f"px_r{r}_c{c}"))
        for r in range(self.n_rows):
            for c in range(self.n_cols - 1):
                slots.append(LoadSlot(CATEGORY_PIXEL_H, r, c, f"h_r{r}_c{c}"))
        for r in range(self.n_rows - 1):
            for c in range(self.n_cols):
                slots.append(LoadSlot(CATEGORY_PIXEL_V, r, c, f"v_r{r}_c{c}"))
        for r in range(self.n_rows - 1):
            for c in range(self.n_cols - 1):
                slots.append(LoadSlot(CATEGORY_DIAG_MAIN, r, c, f"dm_r{r}_c{c}"))
        for r in range(self.n_rows - 1):
            for c in range(self.n_cols - 1):
                slots.append(LoadSlot(CATEGORY_DIAG_ANTI, r, c, f"da_r{r}_c{c}"))
        for k, (r, c, kind) in enumerate(self.via_slots):
            slots.append(LoadSlot(kind, int(r), int(c), f"via{k}_{kind}", k))
        return tuple(slots)

    @property
    def n_load_ports(self) -> int:
        return (
            self.n_rows * self.n_cols
            + self.n_rows * (self.n_cols - 1)
            + (self.n_rows - 1) * self.n_cols
            + 2 * (self.n_rows - 1) * (self.n_cols - 1)
            + len(self.via_slots)
        )

    @property
    def n_ports(self) -> int:
        """Q = 外部 I/O 端口 + 可加载虚拟端口。"""
        return self.n_io_ports + self.n_load_ports

    def slot_categories(self) -> tuple[str, ...]:
        return tuple(slot.category for slot in self.load_slots())

    # ------------------------------------------------------------------ #
    # 占位映射（topology_key + 展平 bool）
    # ------------------------------------------------------------------ #
    def slot_occupancy(self, occupancy: Any, vias: Any = None) -> np.ndarray:
        """图案 `P`（+ 过孔占位）→ 每槽占用布尔向量（短路=1，开路=0）。"""
        pix = _as_bool_matrix(occupancy, self.n_rows, self.n_cols)
        vias_bool = _as_bool_vector(vias, len(self.via_slots), "vias")
        states = np.zeros(self.n_load_ports, dtype=bool)
        for idx, slot in enumerate(self.load_slots()):
            r, c = slot.row, slot.col
            if slot.category == CATEGORY_PIXEL:
                states[idx] = bool(pix[r, c])
            elif slot.category == CATEGORY_PIXEL_H:
                states[idx] = bool(pix[r, c] and pix[r, c + 1])
            elif slot.category == CATEGORY_PIXEL_V:
                states[idx] = bool(pix[r, c] and pix[r + 1, c])
            elif slot.category == CATEGORY_DIAG_MAIN:
                states[idx] = bool(pix[r, c] and pix[r + 1, c + 1])
            elif slot.category == CATEGORY_DIAG_ANTI:
                states[idx] = bool(pix[r, c + 1] and pix[r + 1, c])
            else:
                states[idx] = bool(vias_bool[slot.via_index])
        return states

    def flatten(self, occupancy: Any, vias: Any = None) -> dict[str, Any]:
        """图案 → 展平参数 dict（`topology_key` + `occ{r}_{c}` + `via{k}`）。"""
        pix = _as_bool_matrix(occupancy, self.n_rows, self.n_cols)
        vias_bool = _as_bool_vector(vias, len(self.via_slots), "vias")
        params: dict[str, Any] = {"topology_key": self.topology_key}
        for r in range(self.n_rows):
            for c in range(self.n_cols):
                params[f"occ{r}_{c}"] = float(pix[r, c])
        for k in range(len(self.via_slots)):
            params[f"via{k}"] = float(vias_bool[k])
        return params

    def unflatten(self, params: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
        """展平参数 dict → (像素矩阵, 过孔占位)；非法输入显式报错。"""
        if not isinstance(params, dict):
            raise ConfigError(f"params 必须是 dict，实得 {type(params).__name__}")
        key = params.get("topology_key")
        if key is not None and key != self.topology_key:
            raise ConfigError(
                f"topology_key 不匹配：params={key!r}，布局={self.topology_key!r}")
        pix = np.zeros((self.n_rows, self.n_cols), dtype=bool)
        known = {"topology_key"}
        for r in range(self.n_rows):
            for c in range(self.n_cols):
                name = f"occ{r}_{c}"
                if name not in params:
                    raise ConfigError(f"缺少占位参数 {name!r}")
                pix[r, c] = _as_bool_scalar(params[name], name)
                known.add(name)
        vias_bool = np.zeros(len(self.via_slots), dtype=bool)
        for k in range(len(self.via_slots)):
            name = f"via{k}"
            if name not in params:
                raise ConfigError(f"缺少过孔参数 {name!r}")
            vias_bool[k] = _as_bool_scalar(params[name], name)
            known.add(name)
        unknown = sorted(set(params) - known)
        if unknown:
            raise ConfigError(f"未知参数键：{unknown}")
        return pix, vias_bool


def occupancy_to_load(
    occupancy: Any,
    layout: PixelLayout,
    vias: Any = None,
    *,
    z_short: complex = 0.0,
    z_open: complex = np.inf,
) -> np.ndarray:
    """占用→对角负载 `Z_L(P)`（缺席=开路、在场=短路；stage-1 口径）。

    返回长度 `layout.n_load_ports` 的复向量；开路口以 `np.inf` 表示
    （`load_network_z` 会把这些端口从消去块中**精确移除**，不做大数近似）。
    """
    if not isinstance(layout, PixelLayout):
        raise ConfigError(f"layout 必须是 PixelLayout，实得 {type(layout).__name__}")
    states = layout.slot_occupancy(occupancy, vias)
    loads = np.full(states.shape, complex(z_open), dtype=complex)
    loads[states] = complex(z_short)
    return loads


def load_network_z(
    z_all: Any,
    *,
    n_io: int,
    load_impedances: Any,
) -> np.ndarray:
    """Schur 补闭式：由 Z_ALL 与对角负载求外端口 `Z_MAPES`。

    `Z_MAPES = Z_11 - Z_12 (Z_22 + diag(Z_L))^{-1} Z_21`
    （`V_2 = -Z_L I_2` 消去虚拟端口；开路口 `Z_L=inf` 精确移除）。
    """
    z = _as_square_complex(z_all, "z_all")
    q = z.shape[0]
    n_ext = int(n_io)
    if not (1 <= n_ext <= q):
        raise ConfigError(f"n_io 必须落在 [1, {q}]，实得 {n_io}")
    loads = np.asarray(load_impedances, dtype=complex)
    if loads.shape != (q - n_ext,):
        raise ConfigError(f"load_impedances 长度必须是 {q - n_ext}，实得 {loads.shape}")
    z_ee = z[:n_ext, :n_ext]
    active = np.flatnonzero(np.isfinite(loads))
    if active.size == 0:
        return z_ee.copy()
    z_ev = z[:n_ext, n_ext:]
    z_vv = z[n_ext:, n_ext:]
    z_ve = z[n_ext:, :n_ext]
    block = z_vv[np.ix_(active, active)] + np.diag(loads[active])
    try:
        sol = np.linalg.solve(block, z_ve[active, :])
    except np.linalg.LinAlgError as exc:  # 奇异消去块 → 显式报错而非静默 NaN
        raise ConfigError(f"消去块 (Z_22 + Z_L) 奇异，无法求 Schur 补：{exc}") from exc
    return z_ee - z_ev[:, active] @ sol


def z_to_s(z: Any, *, reference_impedance: float = DEFAULT_REFERENCE_IMPEDANCE) -> np.ndarray:
    """等实参考阻抗 `Z_0` 下的 `S = (Z - Z_0)(Z + Z_0)^{-1}`（支持批）。"""
    zm = np.asarray(z, dtype=complex)
    if zm.ndim not in (2, 3) or zm.shape[-1] != zm.shape[-2]:
        raise ConfigError(f"z 必须是 (n,n) 或 (f,n,n) 方阵，实得 shape={zm.shape}")
    z0 = float(reference_impedance)
    if not np.isfinite(z0) or z0 <= 0.0:
        raise ConfigError(f"reference_impedance 必须是有限正数，实得 {reference_impedance!r}")
    eye = np.eye(zm.shape[-1], dtype=complex)
    try:
        return np.linalg.solve(zm + z0 * eye, zm - z0 * eye)
    except np.linalg.LinAlgError as exc:
        raise ConfigError(f"(Z + Z_0) 奇异，无法转 S：{exc}") from exc


def s_to_z(s: Any, *, reference_impedance: float = DEFAULT_REFERENCE_IMPEDANCE) -> np.ndarray:
    """等实参考阻抗 `Z_0` 下的 `Z = Z_0 (I+S)(I-S)^{-1}`（支持批）。

    stage-2 真机装配入口：openEMS 激励轮转测得的全端口 S 矩阵（统一 50Ω
    端口参考、全端口匹配端接，stage-0 实读口径）经本函数
    转成 `Z_ALL`，再喂 :class:`MapesModel`。与 :func:`z_to_s` 互为逆变换
    （tests/unit/test_mapes_s2.py 钉死往返一致性）。
    """
    sm = np.asarray(s, dtype=complex)
    if sm.ndim not in (2, 3) or sm.shape[-1] != sm.shape[-2]:
        raise ConfigError(f"s 必须是 (n,n) 或 (f,n,n) 方阵，实得 shape={sm.shape}")
    z0 = float(reference_impedance)
    if not np.isfinite(z0) or z0 <= 0.0:
        raise ConfigError(f"reference_impedance 必须是有限正数，实得 {reference_impedance!r}")
    n = sm.shape[-1]
    eye = np.eye(n, dtype=complex)
    try:
        # Z = Z0·B·A^{-1}（A=I-S, B=I+S）右乘逆：转置化为左乘逆
        # Z^T = Z0·(A^T)^{-1}B^T，逐频 solve 后转置回。
        x = np.linalg.solve(
            np.swapaxes(eye - sm, -1, -2), np.swapaxes(eye + sm, -1, -2))
        return z0 * np.swapaxes(x, -1, -2)
    except np.linalg.LinAlgError as exc:
        raise ConfigError(f"(I - S) 奇异，无法转 Z：{exc}") from exc


def z_all_quality(z_all: Any, *, n_io: int, passivity_tol: float = 1.0e-8) -> dict[str, Any]:
    """实测 `Z_ALL` 的互易/无源/条件数逐频诊断（stage-2 验收数字）。

    返回 JSON 友好 dict：
    - ``reciprocity_abs``：逐频 `max|Z - Z^T|`（互易：对称，非共轭转置）；
    - ``reciprocity_rel``：同上除以该频 `max|Z|`（尺度无关）；
    - ``min_eig_re``：逐频 `Re((Z+Z^H)/2)` 最小特征值（无源 ⇔ ≥ -tol）；
    - ``cond_z22`` / ``cond_z``：消去块 `Z_22` 与全矩阵条件数（Schur 数值
      健康度）；``passive``：全频无源布尔。
    """
    z = _as_square_complex(z_all, "z_all", allow_batch=True)
    n_ext = int(n_io)
    q = z.shape[-1]
    if not (1 <= n_ext < q):
        raise ConfigError(f"n_io 必须落在 [1, {q - 1}]（需有虚拟端口），实得 {n_ext}")
    out: dict[str, Any] = {
        "n_freq": int(z.shape[0]),
        "n_ports": int(q),
        "n_io": n_ext,
        "reciprocity_abs": [],
        "reciprocity_rel": [],
        "min_eig_re": [],
        "cond_z22": [],
        "cond_z": [],
    }
    passive = True
    for k in range(z.shape[0]):
        zk = z[k]
        scale = float(np.max(np.abs(zk)))
        rec_abs = float(np.max(np.abs(zk - zk.T)))
        out["reciprocity_abs"].append(rec_abs)
        out["reciprocity_rel"].append(rec_abs / max(scale, _DB_FLOOR))
        herm = 0.5 * (zk + zk.conj().T)
        eig = np.linalg.eigvalsh(herm)
        min_re = float(np.min(eig.real))
        out["min_eig_re"].append(min_re)
        if min_re < -abs(float(passivity_tol)) * max(scale, 1.0):
            passive = False
        out["cond_z22"].append(float(np.linalg.cond(zk[n_ext:, n_ext:])))
        out["cond_z"].append(float(np.linalg.cond(zk)))
    out["passive"] = passive
    out["reciprocity_max_rel"] = float(np.max(out["reciprocity_rel"]))
    out["min_eig_re_min"] = float(np.min(out["min_eig_re"]))
    out["cond_z22_max"] = float(np.max(out["cond_z22"]))
    return out


# --------------------------------------------------------------------------- #
# stage-2 离线 Γ 诊断：openEMS 波分解的纯 numpy 复刻（零仿真、零引擎依赖）
# --------------------------------------------------------------------------- #

def dft_time2freq(t: Any, val: Any, freq_hz: Any) -> np.ndarray:
    """openEMS ``utilities.DFT_time2freq`` 的同式复刻（pulse 单边谱）。

    `f_val[k] = 2·(t[1]−t[0])·Σ_n val[n]·exp(−1j·2π·f_k·t[n])`
    与 vendored ``openEMS/utilities.py`` 的 ``DFT_time2freq``（pulse 分支）
    逐式一致；复刻动机：core 层不得 import vendored 引擎（DLL/版本耦合），
    而已留档的时域 port_ut/port_it 需要可复现的离线再分析（#222 recon）。
    """
    tv = np.asarray(t, dtype=float).reshape(-1)
    vv = np.asarray(val, dtype=float).reshape(-1)
    fv = np.asarray(freq_hz, dtype=float).reshape(-1)
    if tv.shape != vv.shape:
        raise ConfigError(
            f"t 与 val 长度必须一致，实得 {tv.shape[0]} / {vv.shape[0]}")
    if tv.shape[0] < 2:
        raise ConfigError("DFT 至少需要 2 个时间采样点")
    if not np.all(np.isfinite(fv)) or np.any(fv <= 0.0):
        raise ConfigError("freq_hz 必须全为正有限数")
    dt = float(tv[1] - tv[0])
    if not np.isfinite(dt) or dt <= 0.0:
        raise ConfigError(f"时间轴必须单调递增（dt={dt!r}）")
    out = np.zeros(fv.shape[0], dtype=complex)
    for k in range(fv.shape[0]):
        out[k] = np.sum(vv * np.exp(-1j * 2.0 * np.pi * fv[k] * tv))
    return 2.0 * out * dt


def wave_decompose_ui(
    u_tot: Any,
    i_tot: Any,
    *,
    reference_impedance: float = DEFAULT_REFERENCE_IMPEDANCE,
) -> dict[str, np.ndarray]:
    """openEMS ``ports.py`` :meth:`CalcPort` 波分解同式复刻（逐频复向量）。

    `uf_inc = (uf_tot + if_tot·Z0)/2`、`uf_ref = uf_tot − uf_inc`、
    `if_inc = (if_tot + uf_tot/Z0)/2`、`if_ref = if_inc − if_tot`
    （vendored ``openEMS/ports.py`` LumpedPort.CalcPort 字面口径）。
    用于对已留档的时域 port_ut/port_it 做零仿真离线复检。
    """
    z0 = float(reference_impedance)
    if not np.isfinite(z0) or z0 <= 0.0:
        raise ConfigError(f"reference_impedance 必须是有限正数，实得 {reference_impedance!r}")
    uv = np.atleast_1d(np.asarray(u_tot, dtype=complex))
    iv = np.atleast_1d(np.asarray(i_tot, dtype=complex))
    if uv.shape != iv.shape or uv.ndim != 1:
        raise ConfigError(f"u_tot/i_tot 必须是同长一维复向量，实得 {uv.shape} / {iv.shape}")
    uf_inc = 0.5 * (uv + iv * z0)
    uf_ref = uv - uf_inc
    if_inc = 0.5 * (iv + uv / z0)
    if_ref = if_inc - iv
    return {
        "uf_tot": uv, "if_tot": iv,
        "uf_inc": uf_inc, "uf_ref": uf_ref,
        "if_inc": if_inc, "if_ref": if_ref,
    }


def port_gamma(
    u_tot: Any,
    i_tot: Any,
    *,
    reference_impedance: float = DEFAULT_REFERENCE_IMPEDANCE,
    floor: float = 1.0e-30,
) -> np.ndarray:
    """端口端接质量 Γ(ω) = uf_ref/uf_inc（反射/入射电压波比）。

    判读口径（stage-2）：激励轮激励口的 Γ 即该口 S11；非激励口的 Γ 只
    反映"该口 50Ω 端接的吸收质量"——匹配 ≈0、开路 ≈ +1、短路 ≈ −1。
    `|uf_inc|` 低于 `floor` 的频点返回 0（除零保护，#105 同源精神）。
    """
    dec = wave_decompose_ui(
        u_tot, i_tot, reference_impedance=reference_impedance)
    inc = dec["uf_inc"]
    ref = dec["uf_ref"]
    safe = np.abs(inc) > float(floor)
    gamma = np.zeros(inc.shape, dtype=complex)
    gamma[safe] = ref[safe] / inc[safe]
    return gamma


# --------------------------------------------------------------------------- #
# 独立裁判：直接节点法（不经 Z_ALL、不经 Schur 补）
# --------------------------------------------------------------------------- #

def nodal_reference_s(
    y_node: Any,
    *,
    n_io: int,
    load_impedances: Any = None,
    reference_impedance: float = DEFAULT_REFERENCE_IMPEDANCE,
) -> np.ndarray:
    """独立裁判：对底层网络的节点导纳矩阵直接解 Kirchhoff 方程取 S。

    与 :func:`load_network_z` **完全独立**的路径：
    - 未知量 = 全节点电压 `V`；外部端口行用戴维南端口约束
      `V_i + Z_0 (Y_eff V)_i = 2 sqrt(Z_0) a_i`；
    - 虚拟端口行用 `(Y_eff V)_k = 0`；短路负载（`Z_L=0`）作为
      Dirichlet `V_k = 0` 精确消去；开路口不接负载；
    - 逐激励解 `numpy.linalg.solve`，再 `b = (V - Z_0 I)/(2 sqrt(Z_0))`。
    """
    y = np.asarray(y_node, dtype=complex)
    if y.ndim != 2 or y.shape[0] != y.shape[1]:
        raise ConfigError(f"y_node 必须是方阵：(n,n)，实得 shape={y.shape}")
    q = y.shape[0]
    n_ext = int(n_io)
    if not (1 <= n_ext <= q):
        raise ConfigError(f"n_io 必须落在 [1, {q}]，实得 {n_io}")
    z0 = float(reference_impedance)
    if not np.isfinite(z0) or z0 <= 0.0:
        raise ConfigError(f"reference_impedance 必须是有限正数，实得 {reference_impedance!r}")
    n_load = q - n_ext
    if load_impedances is None:
        loads = np.full(n_load, np.inf, dtype=complex)
    else:
        loads = np.asarray(load_impedances, dtype=complex)
        if loads.shape != (n_load,):
            raise ConfigError(f"load_impedances 长度必须是 {n_load}，实得 {loads.shape}")

    y_eff = np.array(y, dtype=complex)
    shorted = np.zeros(q, dtype=bool)
    for k in range(n_load):
        zl = loads[k]
        if not np.isfinite(zl):
            continue
        if abs(zl) == 0.0:
            shorted[n_ext + k] = True
        else:
            y_eff[n_ext + k, n_ext + k] += 1.0 / zl

    free = np.flatnonzero(~shorted)
    n_free = free.size
    mat = np.zeros((n_free, n_free), dtype=complex)
    for a, node in enumerate(free):
        if node < n_ext:
            mat[a, :] = z0 * y_eff[node, free]
            mat[a, a] += 1.0
        else:
            mat[a, :] = y_eff[node, free]

    s = np.zeros((n_ext, n_ext), dtype=complex)
    for j in range(n_ext):
        rhs = np.zeros(n_free, dtype=complex)
        for a, node in enumerate(free):
            if node == j:
                rhs[a] = 2.0 * np.sqrt(z0)
        try:
            v_free = np.linalg.solve(mat, rhs)
        except np.linalg.LinAlgError as exc:
            raise ConfigError(f"节点方程奇异，无法求参考 S：{exc}") from exc
        v = np.zeros(q, dtype=complex)
        v[free] = v_free
        i_net = y_eff @ v
        s[:, j] = (v[:n_ext] - z0 * i_net[:n_ext]) / (2.0 * np.sqrt(z0))
    return s


# --------------------------------------------------------------------------- #
# fake Z_ALL：显式构造的互易无源 RLC 网格
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class RlcMesh:
    """合成 RLC 网格（stage-1 fake 底层物理网络，非真机提取）。

    端口 = 节点到地（节点即端口）。节点间以串联 `R + jωL` 相连，每节点
    对地并联 `G + jωC`。节点导纳 `Y` 对称、Hermitian 部分半正定，故
    `Z_ALL = Y^{-1}` **显式互易且无源**（Re(Z) 半正定）。
    """

    n_ports: int
    edges: tuple[tuple[int, int], ...]
    r_edge: float = 1.0
    l_edge: float = 1.5e-10
    g_node: float = 0.02
    c_node: float = 1.3e-12

    def nodal_admittance(self, freq_hz: float) -> np.ndarray:
        freq = float(freq_hz)
        if not np.isfinite(freq) or freq < 0.0:
            raise ConfigError(f"freq_hz 必须是非负有限数，实得 {freq_hz!r}")
        n = self.n_ports
        y = np.zeros((n, n), dtype=complex)
        y_edge = 1.0 / (self.r_edge + 1j * 2.0 * np.pi * freq * self.l_edge)
        y_shunt = self.g_node + 1j * 2.0 * np.pi * freq * self.c_node
        for i, j in self.edges:
            y[i, i] += y_edge
            y[j, j] += y_edge
            y[i, j] -= y_edge
            y[j, i] -= y_edge
        for i in range(n):
            y[i, i] += y_shunt
        return y

    def z_all(self, freq_hz: float) -> np.ndarray:
        return np.linalg.inv(self.nodal_admittance(freq_hz))

    def reference_s(
        self,
        *,
        n_io: int,
        load_impedances: Any = None,
        freq_hz: float,
        reference_impedance: float = DEFAULT_REFERENCE_IMPEDANCE,
    ) -> np.ndarray:
        return nodal_reference_s(
            self.nodal_admittance(freq_hz),
            n_io=n_io,
            load_impedances=load_impedances,
            reference_impedance=reference_impedance,
        )


def fake_mesh(
    n_ports: int,
    *,
    n_cols: int | None = None,
    r_edge: float = 1.0,
    l_edge: float = 1.5e-10,
    g_node: float = 0.02,
    c_node: float = 1.3e-12,
) -> RlcMesh:
    """近方形二维 4 邻域 RLC 网格（确定性、无随机种子）。"""
    n = int(n_ports)
    if n < 1:
        raise ConfigError(f"n_ports 必须 >=1：{n_ports}")
    cols = int(n_cols) if n_cols else int(np.ceil(np.sqrt(n)))
    cols = max(cols, 1)
    rows = int(np.ceil(n / cols))
    edges: list[tuple[int, int]] = []
    for r in range(rows):
        for c in range(cols):
            i = r * cols + c
            if i >= n:
                continue
            if c + 1 < cols and i + 1 < n:
                edges.append((i, i + 1))
            if r + 1 < rows and i + cols < n:
                edges.append((i, i + cols))
    return RlcMesh(
        n_ports=n,
        edges=tuple(edges),
        r_edge=float(r_edge),
        l_edge=float(l_edge),
        g_node=float(g_node),
        c_node=float(c_node),
    )


# --------------------------------------------------------------------------- #
# stage-2 装配面：像素板端口几何（纯几何映射，引擎无关）
# --------------------------------------------------------------------------- #

#: 端口物理种类（全部为集总探针口；io 口与虚拟口同机械）。
PORT_KIND_LUMPED_V = "lumped_v"
PORT_KIND_LUMPED_GAP = "lumped_gap"


@dataclass(frozen=True)
class PortGeom:
    """一个端口的几何落位（米制坐标；z：0=地面/基板底，h=基板顶贴片面）。

    全部端口为集总探针口：``lumped_v``（竖直贴片-地口：外部 I/O 与
    pixel/via/对角口同机械）与 ``lumped_gap``（贴片间缝隙横向口）。
    start/stop 是集总元盒的对角。
    """

    label: str
    kind: str
    number: int  # 引擎端口号（1 基；= PixelLayout 端口编号 + 1）
    slot_index: int  # 虚拟槽序（occupancy_to_load 向量下标）；-1 = 外部 I/O
    start: tuple[float, float, float]
    stop: tuple[float, float, float]


@dataclass(frozen=True)
class PixelBoardGeom:
    """单层像素 PCB 的装配几何（stage-2 openEMS 渲染的唯一事实源）。

    物理模型（stage-2 自定实现，对应 stage-1 槽语义，见各口注释）：
    - 底面连续地（=z0 PEC 边界）+ 单层基板 + M×N 浮地贴片阵列（永远在场）；
    - `pixel`/`via_ground` 口 = 贴片中心/偏置点的竖直贴片-地探针口
      （在场=金属化过孔短路，缺席=开路——RLC 网格"节点对地口"的字面实现）；
    - `pixel_h/v` 口 = 相邻贴片间缝隙的横向集总口（两端贴片都在场=金属桥
      短路——RLC 网格"节点间串联边"的字面实现）；
    - `diag_main/anti` 口 = 锚在对角像素对各自贴片角区的竖直探针口
      （junction 角区场的探针；stage-1 docstring 已声明对角口为近似约定）。
    参考结构（Z_ALL 提取）= 全贴片、全口开路（探针 50Ω 匹配端接测 S）；
    图案只改负载，不改几何。
    """

    layout: PixelLayout
    cell_m: float
    gap_m: float
    sub_h_m: float
    edge_pad_m: float
    patches: tuple[tuple[float, float, float, float], ...]  # (x0,y0,x1,y1) 行主序
    ports: tuple[PortGeom, ...]  # io1, io2, 随后 load_slots() 序

    @property
    def pitch_m(self) -> float:
        return self.cell_m + self.gap_m

    @property
    def domain(self) -> tuple[float, float, float, float]:
        """基板/地面矩形 (x0,y0,x1,y1)：贴片阵列四周各留 edge_pad。"""
        xs = [p[0] for p in self.patches] + [p[2] for p in self.patches]
        ys = [p[1] for p in self.patches] + [p[3] for p in self.patches]
        return (min(xs) - self.edge_pad_m, min(ys) - self.edge_pad_m,
                max(xs) + self.edge_pad_m, max(ys) + self.edge_pad_m)

    def port_by_number(self, number: int) -> PortGeom:
        for port in self.ports:
            if port.number == number:
                return port
        raise ConfigError(f"端口号 {number} 不在几何中（1..{len(self.ports)}）")


def pixel_board_geom(
    layout: PixelLayout,
    *,
    cell_mm: float = 2.0,
    gap_mm: float = 0.4,
    sub_h_mm: float = 0.508,
    edge_pad_mm: float = 1.0,
    port_half_x_mm: float = 0.1,
    port_half_y_mm: float = 0.15,
    diag_inset_mm: float = 0.25,
) -> PixelBoardGeom:
    """由 :class:`PixelLayout` 装配单层像素板几何（确定性，毫米入参米制出）。

    端口编号 = 布局约定：1/2 为外部 I/O，3..Q 依
    :meth:`PixelLayout.load_slots` 顺序。

    **I/O 口物理落位（stage-2 定稿）**：与虚拟口同机械的竖直贴片-地探针口
    ——io1 在贴片 (0,0) 的 (a/4, a/2)（西中偏置）、io2 在贴片 (M-1,N-1) 的
    (a/2, a/4)（南中偏置），盒边全部复用既有网格阶梯线。这是 MAPES 原文
    "全部端口统一 50Ω"口径的彻底化：首版 MSL 微带馈（三探针相位分解）
    在强失配浮地阵列 + 粗网格下 β/入射波标定失效（实测 |S11|>1 非物理、
    β 偏 2.5 倍），LumpedPort 的局部 u/i 分解无此依赖。

    网格卫生（#152 同源）：各特征盒边线刻意共用坐标——缝隙口横轴半宽取
    port_half_x/port_half_y（与像素口/过孔口盒边重合）、对角锚盒边与
    过孔盒边相接（a/4 处共线），避免两条特征线只差几十 µm 把 CFL 时间步
    压塌（stage-2 首版实测 y 向最小线距 0.043mm → dt=0.103ps → 单轮 FDTD
    撞满时间上限）。
    """
    if not isinstance(layout, PixelLayout):
        raise ConfigError(f"layout 必须是 PixelLayout，实得 {type(layout).__name__}")
    if layout.n_layers != 1:
        raise ConfigError(f"单层板要求 n_layers=1，实得 {layout.n_layers}")
    if any(kind != VIA_GROUND for _, _, kind in layout.via_slots):
        raise ConfigError("单层板只允许 via_ground 过孔槽")
    a = float(cell_mm) * 1e-3
    g = float(gap_mm) * 1e-3
    if a <= 0.0 or g <= 0.0 or g >= a:
        raise ConfigError(f"要求 0 < gap_mm < cell_mm，实得 {cell_mm} / {gap_mm}")
    h = float(sub_h_mm) * 1e-3
    pad = float(edge_pad_mm) * 1e-3
    hx = float(port_half_x_mm) * 1e-3
    hy = float(port_half_y_mm) * 1e-3
    inset = float(diag_inset_mm) * 1e-3
    if inset <= hx or inset <= hy:
        raise ConfigError("diag_inset_mm 必须大于端口盒半宽（锚盒留在贴片内）")
    p = a + g
    m, n = layout.n_rows, layout.n_cols

    def patch(r: int, c: int) -> tuple[float, float, float, float]:
        return (c * p, r * p, c * p + a, r * p + a)

    patches = tuple(patch(r, c) for r in range(m) for c in range(n))

    def vport(label: str, number: int, slot_index: int,
              px: float, py: float, half_y: float | None = None) -> PortGeom:
        hy_eff = half_y if half_y is not None else hy
        return PortGeom(label, PORT_KIND_LUMPED_V, number, slot_index,
                        (px - hx, py - hy_eff, 0.0), (px + hx, py + hy_eff, h))

    ports: list[PortGeom] = []
    # 外部 I/O：角贴片上的竖直探针口（盒边复用阶梯线，零新增网格线）
    ports.append(vport("io1", 1, -1, a / 4.0, a / 2.0))
    ports.append(vport("io2", 2, -1,
                       (n - 1) * p + a / 2.0, (m - 1) * p + a / 4.0))
    for idx, slot in enumerate(layout.load_slots()):
        number = idx + 3
        r, c = slot.row, slot.col
        if slot.category == CATEGORY_PIXEL:
            ports.append(vport(slot.label, number, idx,
                               c * p + a / 2.0, r * p + a / 2.0))
        elif slot.category == CATEGORY_PIXEL_H:
            x0 = c * p + a
            ports.append(PortGeom(
                slot.label, PORT_KIND_LUMPED_GAP, number, idx,
                (x0, r * p + a / 2.0 - hy, h / 2.0),
                (x0 + g, r * p + a / 2.0 + hy, h)))
        elif slot.category == CATEGORY_PIXEL_V:
            y0 = r * p + a
            ports.append(PortGeom(
                slot.label, PORT_KIND_LUMPED_GAP, number, idx,
                (c * p + a / 2.0 - hx, y0, h / 2.0),
                (c * p + a / 2.0 + hx, y0 + g, h)))
        elif slot.category == CATEGORY_DIAG_MAIN:
            # 锚在对角对的左下贴片 (r,c) 的 NE 角区（盒 0.2×0.2mm：
            # y 半宽取 hx 而非 hy，避免与馈线缘线距压到 0.043mm）
            ports.append(vport(slot.label, number, idx,
                               c * p + a - inset, r * p + a - inset,
                               half_y=hx))
        elif slot.category == CATEGORY_DIAG_ANTI:
            # 锚在对角对的右上贴片 (r+1,c+1) 的 SW 角区（同上）
            ports.append(vport(slot.label, number, idx,
                               (c + 1) * p + inset, (r + 1) * p + inset,
                               half_y=hx))
        else:  # via_ground
            ports.append(vport(slot.label, number, idx,
                               c * p + a / 2.0, r * p + a / 4.0))
    return PixelBoardGeom(
        layout=layout, cell_m=a, gap_m=g, sub_h_m=h, edge_pad_m=pad,
        patches=patches, ports=tuple(ports))




def _db(value: Any) -> np.ndarray:
    mag = np.abs(np.asarray(value, dtype=complex))
    return 20.0 * np.log10(np.maximum(mag, _DB_FLOOR))


@dataclass(frozen=True)
class MapesResult:
    """单次图案求检结果（全频段数组）。"""

    topology_key: str
    freq_hz: np.ndarray
    occupancy: np.ndarray
    vias: np.ndarray
    load_impedance: np.ndarray
    z_all: np.ndarray
    z_external: np.ndarray
    s_external: np.ndarray

    @property
    def n_io(self) -> int:
        return int(self.s_external.shape[-1])

    @property
    def n_freq(self) -> int:
        return int(self.s_external.shape[0])

    def summary(self) -> dict[str, Any]:
        """便于落盘的确定性摘要（JSON 友好）。"""
        s_db = _db(self.s_external)
        return {
            "topology_key": self.topology_key,
            "n_freq": self.n_freq,
            "n_io": self.n_io,
            "freq_ghz": [float(f) / 1.0e9 for f in np.atleast_1d(self.freq_hz)],
            "n_occupied_slots": int(np.count_nonzero(np.isfinite(self.load_impedance))),
            "n_open_slots": int(np.count_nonzero(~np.isfinite(self.load_impedance))),
            "s_db": [[[float(x) for x in row] for row in mat] for mat in s_db],
            "s_db_min": float(np.min(s_db)),
            "passive_margin": float(
                1.0 - np.max(np.linalg.norm(self.s_external, ord=2, axis=(-2, -1)))),
            "reciprocity_err": float(np.max(np.abs(
                self.s_external - np.swapaxes(self.s_external, -1, -2)))),
        }


class MapesModel:
    """MAPES 解析像素代理（stage-1）。

    与 `rfauto.optimization.surrogate.SurrogateModel` 的契约同构：
    `KIND` 类属性 + `predict(params) -> dict[str, float]`（纯函数语义）
    + `uncertainty(params) -> None`。本类**不注册**进 `surrogate_registry`
    （stage-3 达标后再注册为"解析代理档"）。
    """

    KIND = "mapes_pixel_analytic"

    def __init__(
        self,
        layout: PixelLayout,
        z_all: Any,
        freq_hz: Any,
        *,
        reference_impedance: float = DEFAULT_REFERENCE_IMPEDANCE,
        alpha: float = 1.0,
    ) -> None:
        if not isinstance(layout, PixelLayout):
            raise ConfigError(f"layout 必须是 PixelLayout，实得 {type(layout).__name__}")
        self.layout = layout
        self.reference_impedance = float(reference_impedance)
        alpha_val = float(alpha)
        if not np.isfinite(alpha_val) or alpha_val <= 0.0:
            raise ConfigError(f"alpha 必须是有限正数（频率缩放因子），实得 {alpha!r}")
        self.alpha = alpha_val
        z = np.asarray(z_all, dtype=complex)
        if z.ndim == 2:
            z = z[None, :, :]
            if np.ndim(freq_hz) != 0:
                raise ConfigError("二维 z_all 只能配标量 freq_hz")
            freqs = np.array([float(freq_hz)], dtype=float)
        elif z.ndim == 3:
            freqs = np.asarray(freq_hz, dtype=float)
            if freqs.ndim != 1 or freqs.shape[0] != z.shape[0]:
                raise ConfigError(
                    f"freq_hz 长度必须等于 z_all 频点数 {z.shape[0]}，实得 {freqs.shape}")
        else:
            raise ConfigError(f"z_all 必须是 (q,q) 或 (f,q,q)，实得 shape={z.shape}")
        q = self.layout.n_ports
        if z.shape[1:] != (q, q):
            raise ConfigError(
                f"z_all 端口数必须等于布局端口数 {q}，实得 {z.shape[1:]}")
        self.freq_hz = freqs
        self._z_all = z

    @property
    def topology_key(self) -> str:
        return self.layout.topology_key

    def uncertainty(self, params: dict[str, Any]) -> None:
        """契约占位：MAPES 为确定性闭式内核，无不确定性估计。"""
        del params
        return None

    def z_all_effective(self) -> np.ndarray:
        """α 频率缩放后实际参与 Schur 补的 Z_ALL（(f,q,q)）。

        stage-3 #190 校准范式的单参数 α：闭式模型在输出频点 f_k 处使用
        提取值 `Z_ALL(α·f_k)`（提取网格上线性插值；越界端点常数钳位——
        高斯激励谱在带边衰减，钳位误差只落在带边一两点，如实记录于
        :func:`fit_alpha_scaling` 报告）。α=1 精确等于原提取（零插值）。
        """
        if self.alpha == 1.0 or self.freq_hz.shape[0] < 2:
            return self._z_all
        grid = self.freq_hz
        f_scaled = self.alpha * grid
        n = grid.shape[0]
        lo = np.clip(np.searchsorted(grid, f_scaled, side="right") - 1, 0, n - 2)
        span = grid[lo + 1] - grid[lo]
        w = np.clip((f_scaled - grid[lo]) / span, 0.0, 1.0)
        return ((1.0 - w)[:, None, None] * self._z_all[lo]
                + w[:, None, None] * self._z_all[lo + 1])

    def evaluate(self, params: dict[str, Any]) -> MapesResult:
        """完整求检：图案 → Z_L → Schur 补 → Z_external/S（全频段）。"""
        occupancy, vias = self.layout.unflatten(params)
        loads = occupancy_to_load(occupancy, self.layout, vias)
        n_io = self.layout.n_io_ports
        z_used = self.z_all_effective()
        z_ext = np.empty((z_used.shape[0], n_io, n_io), dtype=complex)
        for k in range(z_used.shape[0]):
            z_ext[k] = load_network_z(
                z_used[k], n_io=n_io, load_impedances=loads)
        s_ext = z_to_s(z_ext, reference_impedance=self.reference_impedance)
        return MapesResult(
            topology_key=self.topology_key,
            freq_hz=self.freq_hz,
            occupancy=occupancy,
            vias=vias,
            load_impedance=loads,
            z_all=z_used,
            z_external=z_ext,
            s_external=s_ext,
        )

    def predict(self, params: dict[str, Any]) -> dict[str, float]:
        """SurrogateModel 契约：平铺 params → 平铺 metrics（同参数同输出，纯函数语义）。"""
        result = self.evaluate(params)
        s = np.asarray(result.s_external)
        n_io = result.n_io
        center = result.n_freq // 2
        metrics: dict[str, float] = {}
        for i in range(n_io):
            for j in range(n_io):
                metrics[f"s{i + 1}{j + 1}_db_at_fc"] = float(_db(s[center, i, j]))
        if n_io >= 1:
            metrics["s11_db_min"] = float(np.min(_db(s[:, 0, 0])))
        if n_io >= 2:
            metrics["s21_db_at_fc"] = float(_db(s[center, 1, 0]))
            metrics["s21_db_min"] = float(np.min(_db(s[:, 1, 0])))
        metrics["passive_margin"] = float(
            1.0 - np.max(np.linalg.norm(s, ord=2, axis=(-2, -1))))
        metrics["reciprocity_err"] = float(np.max(np.abs(
            s - np.swapaxes(s, -1, -2))))
        return metrics


# --------------------------------------------------------------------------- #
# stage-4：α（全局频率缩放）确定性单参数校准 + 留一验证（#190 校准范式）
# --------------------------------------------------------------------------- #

#: 缺省 α 搜索网格：±10%、步长 0.002（确定性网格搜索，无随机、无优化器依赖）
DEFAULT_ALPHA_GRID: tuple[float, ...] = tuple(
    float(round(v, 4)) for v in np.arange(0.90, 1.10 + 1e-9, 0.002))

_ALPHA_FIT_METRICS = ("s11_db_min", "s21_db_at_fc")


def _alpha_case_errors(
    layout: PixelLayout,
    z_all: np.ndarray,
    freq_hz: np.ndarray,
    cases: list[tuple[dict[str, Any], dict[str, float]]],
    *,
    alpha: float,
    reference_impedance: float,
) -> np.ndarray:
    """逐案逐指标误差矩阵 (n_cases, n_metrics)：闭式(α) − 直接全波（dB）。"""
    model = MapesModel(layout, z_all, freq_hz,
                       reference_impedance=reference_impedance, alpha=alpha)
    out = np.zeros((len(cases), len(_ALPHA_FIT_METRICS)), dtype=float)
    for i, (params, direct) in enumerate(cases):
        pred = model.predict(params)
        for j, key in enumerate(_ALPHA_FIT_METRICS):
            out[i, j] = float(pred[key]) - float(direct[key])
    return out


def fit_alpha_scaling(
    layout: PixelLayout,
    z_all: Any,
    freq_hz: Any,
    cases: Any,
    *,
    reference_impedance: float = DEFAULT_REFERENCE_IMPEDANCE,
    alpha_grid: Any = None,
) -> dict[str, Any]:
    """α 频率缩放的确定性单参数校准（网格搜索）+ 留一交叉验证。

    输入 ``cases`` = ``[(params_flat, direct_metrics), ...]``：``params_flat``
    为 :meth:`PixelLayout.flatten` 展平 dict，``direct_metrics`` 为该图案
    **直接全波**（基准）的 metrics（需含 ``s11_db_min`` 与 ``s21_db_at_fc``，
    与 :meth:`MapesModel.predict` 同键同式）。目标函数（确定性）：

        SSE(α) = Σ_案 Σ_指标 [ (闭式_α − 直接) / w_指标 ]²

    ``w_指标`` = α=1 时该指标逐案误差的 RMS（两指标量纲同为 dB 仍做尺度归一，
    避免深谷 s11_db_min 的大 dB 摆幅淹没 s21@fc）；``w=0`` 的指标（α=1 已
    精确）取 1。留一验证：逐案剔除后重拟 α_i，报告留出案在 α_i 与 α=1 下
    的归一误差。数值只在确定性内核：全部数值只来自闭式内核与真机基准，本函数不产生
    任何物理常数；α 是否被 HFSS 背书（#190）由调用方标注。
    """
    if not isinstance(layout, PixelLayout):
        raise ConfigError(f"layout 必须是 PixelLayout，实得 {type(layout).__name__}")
    z = np.asarray(z_all, dtype=complex)
    freqs = np.asarray(freq_hz, dtype=float)
    if z.ndim != 3 or freqs.ndim != 1 or z.shape[0] != freqs.shape[0]:
        raise ConfigError("fit_alpha_scaling 需要 (f,q,q) 的 z_all 与等长 freq_hz")
    case_list = list(cases)
    if len(case_list) < 2:
        raise ConfigError(f"α 校准至少需要 2 个直接全波案，实得 {len(case_list)}")
    for k, item in enumerate(case_list):
        if not (isinstance(item, tuple) and len(item) == 2 and isinstance(item[1], dict)):
            raise ConfigError(f"cases[{k}] 必须是 (params_flat, direct_metrics) 二元组")
        missing = [m for m in _ALPHA_FIT_METRICS if m not in item[1]]
        if missing:
            raise ConfigError(f"cases[{k}] 直接全波 metrics 缺键 {missing}")
    grid = np.asarray(
        DEFAULT_ALPHA_GRID if alpha_grid is None else alpha_grid, dtype=float)
    if grid.ndim != 1 or grid.shape[0] < 1 or np.any(~np.isfinite(grid)) or np.any(grid <= 0):
        raise ConfigError("alpha_grid 必须是非空正有限一维数组")
    z0 = float(reference_impedance)

    def errors(alpha: float, idx: list[int]) -> np.ndarray:
        sub = [case_list[i] for i in idx]
        return _alpha_case_errors(layout, z, freqs, sub, alpha=alpha,
                                  reference_impedance=z0)

    all_idx = list(range(len(case_list)))
    err1 = errors(1.0, all_idx)
    weights = np.sqrt(np.mean(err1 ** 2, axis=0))
    weights = np.where(weights > 0.0, weights, 1.0)

    def sse(err: np.ndarray) -> float:
        return float(np.sum((err / weights) ** 2))

    curve = [sse(errors(float(a), all_idx)) for a in grid]
    k_best = int(np.argmin(curve))
    alpha_best = float(grid[k_best])
    sse_best = float(curve[k_best])
    sse_1 = sse(err1)
    err_best = errors(alpha_best, all_idx)

    loo: list[dict[str, Any]] = []
    for i in all_idx:
        train = [j for j in all_idx if j != i]
        curve_i = [sse(errors(float(a), train)) for a in grid]
        a_i = float(grid[int(np.argmin(curve_i))])
        held_fit = errors(a_i, [i])[0]
        held_1 = errors(1.0, [i])[0]
        loo.append({
            "case_index": i,
            "alpha_fit": a_i,
            "held_out_norm_err_at_fit": float(np.sqrt(np.sum((held_fit / weights) ** 2))),
            "held_out_norm_err_at_1": float(np.sqrt(np.sum((held_1 / weights) ** 2))),
            "held_out_delta_s11_db_min_at_fit_db": float(held_fit[0]),
            "held_out_delta_s11_db_min_at_1_db": float(held_1[0]),
        })
    loo_alphas = [d["alpha_fit"] for d in loo]
    return {
        "metrics": list(_ALPHA_FIT_METRICS),
        "n_cases": len(case_list),
        "alpha_grid": [float(a) for a in grid],
        "sse_curve": [float(v) for v in curve],
        "metric_weights_rms_at_alpha1": [float(w) for w in weights],
        "alpha_best": alpha_best,
        "sse_at_alpha_best": sse_best,
        "sse_at_alpha_1": sse_1,
        "improvement_ratio": float(sse_1 / sse_best) if sse_best > 0.0 else float("inf"),
        "per_case_err_at_alpha_1": [[float(v) for v in row] for row in err1],
        "per_case_err_at_alpha_best": [[float(v) for v in row] for row in err_best],
        "loo": loo,
        "loo_alpha_min": float(min(loo_alphas)),
        "loo_alpha_max": float(max(loo_alphas)),
        "loo_mean_norm_err_at_fit": float(np.mean(
            [d["held_out_norm_err_at_fit"] for d in loo])),
        "loo_mean_norm_err_at_1": float(np.mean(
            [d["held_out_norm_err_at_1"] for d in loo])),
    }


# --------------------------------------------------------------------------- #
# stage-5：探针装配偏差重推导（零仿真；离线诊断定根因后的
# 通用内核。误差模型与证据链：
# u 探针=盒内单棱采样（主项）、i 探针=z0 对偶环位移拾取（次项、轮相关→旋度）、
# 激励口 SREF 探针偏差→列缩放（轮无关→势场）；逐端口纯相位（对角相似）被
# 实证否证（σmax/min_eig 在相似变换下严格不变）。
# --------------------------------------------------------------------------- #

#: 预声明 Z_ALL 质量门（写死）：
#: 互易 ≤ 1e-3 且全频 min_eig(Re Z) ≥ −1e-6（数值容差）且 σmax(S) ≤ 1.001。
ZALL_GATE_RECIPROCITY_MAX = 1.0e-3
ZALL_GATE_MIN_EIG_RE = -1.0e-6
ZALL_GATE_SIGMA_MAX = 1.001

#: 无源投影 Re(Z) 特征值下限（Ω）：0 太紧会被特征分解舍入打出 1e-16 级负值，
#: 取 1e-6 与质量门数值容差一致。
PASSIVE_FLOOR_OHM = 1.0e-6


def assemble_s_from_ui(
    uf_all: Any,
    if_all: Any,
    *,
    reference_impedance: float = DEFAULT_REFERENCE_IMPEDANCE,
    numerator: str = "current",
    sref_recal: Any = None,
) -> np.ndarray:
    """激励轮转原始 (uf_tot, if_tot) → 全端口 S（重推导装配入口，零仿真）。

    输入 (n_rounds, q, n_freq)：第 k 轮激励端口 k+1、全端口 50Ω 端接；
    `uf_all[k, p]` / `if_all[k, p]` 为端口 p+1 在轮 k 的电压/电流 DFT
    （openEMS ``ReadUIData`` 语义，各档自身时间轴）。返回 (n_freq, q, q)，
    ``S[f, i, k]`` = 轮 k 测得的 S_{i+1,k+1}。

    ``numerator``：
    - ``"wave"``：``b_i = (U_i − Z0·I_i)/2``（引擎波分解原口径；u 单棱采样
      偏差全额进入）；
    - ``"current"``：非激励口 ``b_i = −Z0·I_i``——离散集总电阻定律
      ``U_avg = R·I_total`` 在端接口精确成立（棱均值电压可由总电流单读
      复原），绕开 u 单棱采样主项（诊断档实测互易残差
      5.6× 改善）；激励口对角元仍用波分解（含源，电阻定律不可用）。

    ``sref_recal``（opt-in，缺省 None=行为逐位不变）：SREF 列因子
    ``(n_freq, q)`` 复数，装配后按列回乘 ``S[f, i, k] *= c[f, k]``——与
    "装配前把激励口 ``inc_k`` 除以同一因子"代数等价（列归一化，非对角
    相似变换，σmax/特征值不受"相似不变性"保护）。典型来源
    :func:`sref_column_factors`（端接轮定律 Γ 混合列修正，stage-5c）。
    """
    if numerator not in ("wave", "current"):
        raise ConfigError(f"numerator 只接受 'wave'/'current'，实得 {numerator!r}")
    um = np.asarray(uf_all, dtype=complex)
    im = np.asarray(if_all, dtype=complex)
    if um.ndim != 3 or um.shape != im.shape or um.shape[0] != um.shape[1]:
        raise ConfigError(
            "uf_all/if_all 必须是同形 (n_rounds=q, q, n_freq)，实得 "
            f"{um.shape} / {im.shape}")
    z0 = float(reference_impedance)
    if not np.isfinite(z0) or z0 <= 0.0:
        raise ConfigError(f"reference_impedance 必须是有限正数，实得 {reference_impedance!r}")
    n_rounds, q, _ = um.shape
    inc = 0.5 * (um + im * z0)
    ref = um - inc
    if numerator == "wave":
        num = ref
    else:
        num = (-z0 * im).copy()
        idx = np.arange(n_rounds)
        num[idx, idx, :] = ref[idx, idx, :]  # 激励口对角仍用波分解
    out = np.empty((um.shape[2], q, q), dtype=complex)
    for k in range(n_rounds):
        out[:, :, k] = (num[k] / inc[k, k][None, :]).T  # SREF = 激励口 k 的 uf_inc
    if sref_recal is not None:
        c = np.asarray(sref_recal, dtype=complex)
        if c.ndim != 2 or c.shape != (out.shape[0], q):
            raise ConfigError(
                f"sref_recal 形状必须为 (n_freq, q)=({out.shape[0]}, {q})，"
                f"实得 {c.shape}")
        if not np.all(np.isfinite(c)):
            raise ConfigError("sref_recal 含非有限值")
        out = out * c[:, None, :]
    return out


def fit_reciprocity_gain(
    s: Any,
    *,
    min_coupling: float = 2.0e-5,
) -> tuple[np.ndarray, dict[str, Any]]:
    """互易势场拟合：``log(S_ik/S_ki) = x_i − x_k`` 图加权最小二乘求 x。

    模型：装配腿系统偏差中"轮无关"的部分 = 逐端口复增益（激励口 SREF 偏差
    → 列缩放、探针幅度/相位偏差 → 行+列缩放），在对数域是图上的势场
    ``x_p``；互易给出可观测约束 ``b_ik = log(S_ik/S_ik^T) = x_i − x_k``。
    权重 ``w_ik = min(|S_ik|,|S_ki|)²``（弱耦合对自动降权），
    ``|S| ≤ min_coupling`` 的对不进拟合（无判读力）。返回
    ``(x, info)``：``x`` 形状 (n_freq, q)（复），规范 Σ_p x_p(f) = 0——
    **全局复尺度不可由互易辨识**（须由独立测量标定，见 :func:`gauge_factor`）；
    ``info`` 报告拟合残差（加权 RMS 的中位/最大，即"旋度"残差=轮相关
    拾取项的下界）。
    """
    sm = np.asarray(s, dtype=complex)
    if sm.ndim != 3 or sm.shape[1] != sm.shape[2]:
        raise ConfigError(f"s 必须是 (n_freq, q, q)，实得 shape={sm.shape}")
    nf, q, _ = sm.shape
    if q < 2:
        raise ConfigError(f"q 必须 >=2，实得 {q}")
    iu, il = np.triu_indices(q, k=1)
    mag = np.abs(sm)
    m1, m2 = mag[:, iu, il], mag[:, il, iu]
    w = np.minimum(m1, m2) ** 2
    ok = np.minimum(m1, m2) > float(min_coupling)
    with np.errstate(divide="ignore", invalid="ignore"):
        b = np.log(sm[:, iu, il] / sm[:, il, iu])
    x = np.zeros((nf, q), dtype=complex)
    resid_w: list[float] = []
    for f in range(nf):
        wf = np.where(ok[f], w[f], 0.0)
        if wf.sum() <= 0.0:
            continue
        a = np.zeros((q, q))
        np.add.at(a, (iu, iu), wf)
        np.add.at(a, (il, il), wf)
        np.add.at(a, (iu, il), -wf)
        np.add.at(a, (il, iu), -wf)
        # 均匀 Tikhonov 钉全局规范（Σx→0）；对差分观测无偏
        a += np.eye(q) * (1.0e-12 + 1.0e-8 * wf.sum() / q)
        rhs = np.zeros(q)
        np.add.at(rhs, iu, wf * b[f].real)
        np.add.at(rhs, il, -wf * b[f].real)
        xr = np.linalg.solve(a, rhs)
        rhs_i = np.zeros(q)
        np.add.at(rhs_i, iu, wf * b[f].imag)
        np.add.at(rhs_i, il, -wf * b[f].imag)
        xi = np.linalg.solve(a, rhs_i)
        xf = xr + 1j * xi
        x[f] = xf - xf.mean()
        r = np.abs((x[f][iu] - x[f][il]) - b[f])[ok[f]]
        resid_w.append(float(np.sqrt(np.average(r ** 2, weights=wf[ok[f]]))))
    info = {
        "n_pairs": int(iu.size),
        "n_pairs_used_median": int(np.median([int(np.count_nonzero(ok[f]))
                                              for f in range(nf)])),
        "fit_resid_wrms_median": (float(np.median(resid_w)) if resid_w else 0.0),
        "fit_resid_wrms_max": (float(np.max(resid_w)) if resid_w else 0.0),
    }
    return x, info


def apply_port_gain(s: Any, log_gamma: Any) -> np.ndarray:
    """逐端口复增益回乘：``S'[.., i, k] = S[.., i, k]·exp(log_gamma[f, k])``。"""
    sm = np.asarray(s, dtype=complex)
    x = np.asarray(log_gamma, dtype=complex)
    if sm.ndim != 3 or sm.shape[1] != sm.shape[2]:
        raise ConfigError(f"s 必须是 (n_freq, q, q)，实得 shape={sm.shape}")
    if x.shape != (sm.shape[0], sm.shape[1]):
        raise ConfigError(f"log_gamma 形状必须为 (n_freq, q)，实得 {x.shape}")
    return sm * np.exp(x)[:, None, :]


def gauge_factor(
    freq_hz: Any,
    g0: float,
    tau_s: float,
) -> np.ndarray:
    """全局复规范 ``g(f) = g0·exp(j·2π·f·τ)``（互易不可辨识的全局尺度/相位，
    由独立测量——直接全波干净腿对拍——确定性网格搜索标定，见
    scripts/mapes_s2_zall.py ``reassemble --gauge``）。"""
    f = np.asarray(freq_hz, dtype=float)
    if f.ndim != 1 or f.shape[0] < 1 or np.any(~np.isfinite(f)) or np.any(f < 0):
        raise ConfigError(f"freq_hz 必须是非负有限一维数组，实得 {freq_hz!r}")
    g0v, tau = float(g0), float(tau_s)
    if not np.isfinite(g0v) or g0v <= 0.0:
        raise ConfigError(f"g0 必须是有限正数，实得 {g0!r}")
    if not np.isfinite(tau):
        raise ConfigError(f"tau_s 必须是有限数，实得 {tau_s!r}")
    return g0v * np.exp(1j * 2.0 * np.pi * f * tau)


def reciprocity_pair_residual(s: Any) -> dict[str, np.ndarray]:
    """逐端口对互易残差定位：``max_f |S_ik − S_ki|`` 与耦合量 ``max_f |S_ik|``。

    返回 (i, k) 上三角展平索引 ``pair_i/pair_k``（0 基）及对应残差/耦合数组，
    供坏对定位（同贴片/同类聚集判读，诊断用）。
    """
    sm = np.asarray(s, dtype=complex)
    if sm.ndim != 3 or sm.shape[1] != sm.shape[2]:
        raise ConfigError(f"s 必须是 (n_freq, q, q)，实得 shape={sm.shape}")
    q = sm.shape[1]
    iu, il = np.triu_indices(q, k=1)
    resid = np.abs(sm[:, iu, il] - sm[:, il, iu]).max(axis=0)
    coupling = np.maximum(np.abs(sm[:, iu, il]).max(axis=0),
                          np.abs(sm[:, il, iu]).max(axis=0))
    return {"pair_i": iu, "pair_k": il,
            "residual_max": resid, "coupling_max": coupling}


def passive_project_z(
    z: Any,
    *,
    floor: float = PASSIVE_FLOOR_OHM,
) -> tuple[np.ndarray, dict[str, Any]]:
    """对称 Z 的最小范数无源投影：Re(Z) 特征值钳到 ``floor``（互易精确保持）。

    口径声明（#122）：这是**数值口径**而非物理修复——投影前后的量级差
    （最大特征值钳位、‖ΔZ‖_F 相对量）如实返回，供调用方标注。Z 须对称
    （先 sym 再进来），否则先按 (Z+Zᵀ)/2 对称化。返回 ``(z_proj, info)``。
    """
    zm = np.asarray(z, dtype=complex)
    if zm.ndim not in (2, 3) or zm.shape[-1] != zm.shape[-2]:
        raise ConfigError(f"z 必须是 (q,q) 或 (f,q,q) 方阵，实得 shape={zm.shape}")
    zsym = 0.5 * (zm + np.swapaxes(zm, -1, -2))
    fl = float(floor)
    if not np.isfinite(fl) or fl < 0.0:
        raise ConfigError(f"floor 必须是非负有限数，实得 {floor!r}")
    out = np.empty_like(zsym)
    clip = np.zeros(zsym.shape[0])
    for f in range(zsym.shape[0]):
        r = zsym[f].real
        r = 0.5 * (r + r.T)
        lam, vec = np.linalg.eigh(r)
        lam_c = np.maximum(lam, fl)
        clip[f] = float(np.max(lam_c - lam))
        out[f] = (vec * lam_c) @ vec.T + 1j * zsym[f].imag
    info = {
        "max_eig_clip_ohm": float(clip.max()),
        "rel_fro": float(np.linalg.norm(out - zsym) / max(np.linalg.norm(zsym), _DB_FLOOR)),
        "max_abs_delta_ohm": float(np.abs(out - zsym).max()),
    }
    return out, info


def z_all_gate(
    s: Any,
    *,
    reference_impedance: float = DEFAULT_REFERENCE_IMPEDANCE,
) -> dict[str, Any]:
    """预声明 Z_ALL 质量门（常量写死）：互易/无源/σmax 逐频判定。

    返回逐频与汇总指标 + ``pass`` 布尔（三门同时成立才 True）。数值定义：
    互易 ``max|S−Sᵀ| ≤ ZALL_GATE_RECIPROCITY_MAX``（S 域）；
    ``min_f Re((Z+Zᴴ)/2) ≥ ZALL_GATE_MIN_EIG_RE``（Z = s_to_z(S)）；
    ``σmax(S) ≤ ZALL_GATE_SIGMA_MAX``（逐频谱范数）。
    """
    sm = np.asarray(s, dtype=complex)
    if sm.ndim != 3 or sm.shape[1] != sm.shape[2]:
        raise ConfigError(f"s 必须是 (n_freq, q, q)，实得 shape={sm.shape}")
    z = s_to_z(sm, reference_impedance=reference_impedance)
    rec_pf = np.max(np.abs(sm - np.swapaxes(sm, -1, -2)), axis=(1, 2))
    min_eig = np.array([
        float(np.min(np.linalg.eigvalsh(0.5 * (zk + zk.conj().T)).real))
        for zk in z])
    smax = np.linalg.norm(sm, ord=2, axis=(-2, -1))
    pass_rec = bool(np.all(rec_pf <= ZALL_GATE_RECIPROCITY_MAX))
    pass_pas = bool(np.all(min_eig >= ZALL_GATE_MIN_EIG_RE))
    pass_smax = bool(np.all(smax <= ZALL_GATE_SIGMA_MAX))
    return {
        "gates": {
            "reciprocity_max": ZALL_GATE_RECIPROCITY_MAX,
            "min_eig_re": ZALL_GATE_MIN_EIG_RE,
            "sigma_max": ZALL_GATE_SIGMA_MAX,
        },
        "reciprocity_max": float(rec_pf.max()),
        "reciprocity_perfreq_median": float(np.median(rec_pf)),
        "reciprocity_perfreq_p95": float(np.percentile(rec_pf, 95)),
        "min_eig_re_min": float(min_eig.min()),
        "min_eig_re_median": float(np.median(min_eig)),
        "sigma_max": float(smax.max()),
        "sigma_max_median": float(np.median(smax)),
        "n_freq_reciprocity_pass": int(np.count_nonzero(
            rec_pf <= ZALL_GATE_RECIPROCITY_MAX)),
        "n_freq_passivity_pass": int(np.count_nonzero(
            min_eig >= ZALL_GATE_MIN_EIG_RE)),
        "n_freq_sigma_pass": int(np.count_nonzero(smax <= ZALL_GATE_SIGMA_MAX)),
        "n_freq": int(sm.shape[0]),
        "pass_reciprocity": pass_rec,
        "pass_passivity": pass_pas,
        "pass_sigma_max": pass_smax,
        "pass": bool(pass_rec and pass_pas and pass_smax),
    }


# --------------------------------------------------------------------------- #
# stage-5b：探针装配侧根因修复内核（#257）。定案：同端口
# 跨轮 Z_ui 偏差中位 1.9%/最大 57% 的装配侧根因 = openEMS LumpedPort 探针盒
# （0.2×0.3mm）在 0.6mm 网格下不足 2 格——u 探针（盒横断面中心零宽线）不在
# 网格线上时吸附到最近棱=盒角单棱积分（dump 实证 io1 u 落 (0.4,0.85)、中心
# (0.5,1.0)）；i 探针（激励轴中面）请求 z=h/2 被吸附到 z=0 地面 PEC 对偶环、
# 面积≈3× 盒。修法（离线侧；真机重提取另行执行）：
#   ① probe_midlines：每端口盒三轴中线全部落硬网格线（= u 探针两横轴中心线
#      + i 探针激励轴中面线），探针按 ports.py 字面口径逐位落位；
#   ② probe_box_guard：终网格守卫——每端口盒每轴 [start, mid, stop] 三线
#      齐备（恰 ≥2 格）且中线到任何邻线距离 > 去重阈值（否则渲染脚本的 #152
#      1µm 近重合守卫会把中线吞掉，修复静默失效）；
#   ③ ui_cross_round_drift：跨轮 Z_ui 漂移诊断（装配矩阵类先做跨轮漂移诊断，
#      同端口物理端接轮不变，漂移即探针装配偏差的直接观测量）。
# --------------------------------------------------------------------------- #

#: 渲染脚本近重合线去重阈值（#152 守卫：``_v - _keep[-1] > 1e-6`` 才保留）——
#: 端口盒中线到任何邻线（含自身盒边）的距离必须 **严格大于** 此值才能存活。
PROBE_MIN_GAP_M = 1.0e-6

#: 跨轮漂移按电流信噪分桶的固定桶边（|if| / 该口跨轮中位 |if|）；纯制表口径，
#: 非门限——真机档实测漂移随此量单调（<1% 桶中位 18.8%、≥10 桶中位 1.1%）。
UI_DRIFT_SNR_EDGES: tuple[float, ...] = (1.0e-2, 1.0e-1, 1.0, 10.0)

_AXIS_NAMES = ("x", "y", "z")


def _nanmedian_quiet(a: np.ndarray, axis: int | None = None) -> Any:
    """全 NaN 切片不告警的 nanmedian（rel_floor 剔空整轮/整频时是合法情形）。"""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmedian(a, axis=axis)


def port_probe_axes(port: PortGeom) -> int:
    """端口盒的激励轴下标（0=x / 1=y / 2=z）。

    与 scripts/mapes_s2_zall 渲染器 LumpedPort ``exc_dir`` 同一规则（单一
    事实源）：缝隙横向口按缝隙跨度轴（跨度 g 恒大于横截面 2·hy），竖直
    贴片-地口恒为 z。u 探针沿此轴贯穿、i 探针面法向沿此轴。
    """
    if not isinstance(port, PortGeom):
        raise ConfigError(f"port 必须是 PortGeom，实得 {type(port).__name__}")
    s, t = port.start, port.stop
    if port.kind == PORT_KIND_LUMPED_GAP:
        return 0 if abs(t[0] - s[0]) > abs(t[1] - s[1]) else 1
    return 2


def probe_midlines(geom: PixelBoardGeom) -> tuple[list[float], list[float], list[float]]:
    """每端口盒三轴中线的硬网格线（#257 中心硬线，确定性、排序去重）。

    openEMS ``ports.py`` LumpedPort 探针落位字面口径（vendored 源逐行核对）：
    - u 探针：``u_start = u_stop = 0.5*(start+stop)``（两横轴取盒中心，
      零宽），激励轴从 start 贯穿到 stop——中心坐标不在网格线上时被吸附到
      最近棱（病理档实测落到盒角，单棱积分偏离端口元件内部）；
    - i 探针：``i_start/i_stop`` 横轴取盒全跨、激励轴取 ``0.5*(start+stop)``
      中面——中面不在网格线上时被吸附到最近面（病理档 z=h/2 吸到 z=0 PEC）。
    对每端口盒在 x/y/z 三轴各加一条中线（同时覆盖 u 探针两横轴中心与 i
    探针激励轴中面）；盒边本身已是结构硬线（scripts.mesh_lines），三线齐备
    → 每盒每轴恰 ≥2 格、探针逐位落位。返回 (xs, ys, zs)。
    """
    if not isinstance(geom, PixelBoardGeom):
        raise ConfigError(f"geom 必须是 PixelBoardGeom，实得 {type(geom).__name__}")
    mids: tuple[set[float], set[float], set[float]] = (set(), set(), set())
    for port in geom.ports:
        s, t = port.start, port.stop
        for ax in range(3):
            mids[ax].add(0.5 * (float(s[ax]) + float(t[ax])))
    return (sorted(mids[0]), sorted(mids[1]), sorted(mids[2]))


def probe_box_guard(
    geom: PixelBoardGeom,
    lines: tuple[Any, Any, Any],
    *,
    min_gap_m: float = PROBE_MIN_GAP_M,
) -> dict[str, Any]:
    """终网格 ≥2 格守卫（#257）：逐端口盒逐轴 [start, mid, stop] 三线齐备。

    ``lines`` = 渲染将写入脚本的 (xs, ys, zs) 合并线集（结构线 + 中线，
    平滑前口径——引擎平滑只插线不删线；渲染端 1µm 去重由 ``min_gap_m``
    预检兜底）。判定（逐端口逐轴）：
    - 盒两边线与中线都在线集里（浮点精确成员，中线由同一算式 0.5·(s+t) 生成）；
    - 半跨 0.5·|stop−start| > min_gap_m（零跨盒/亚微米盒 = 探针退化）；
    - 中线到线集中最近邻线的距离 > min_gap_m（否则去重吞中线，修复静默失效）。
    三条同时成立 ⇔ 该轴 ≥2 格且中线平滑/去重后必存活。返回 JSON 友好 dict：
    ``pass``、``violations``（端口号/标签/轴/原因）、``min_half_span_m`` 与
    ``min_mid_gap_m``（全部盒实测最小值）。
    """
    if not isinstance(geom, PixelBoardGeom):
        raise ConfigError(f"geom 必须是 PixelBoardGeom，实得 {type(geom).__name__}")
    if not (isinstance(lines, (tuple, list)) and len(lines) == 3):
        raise ConfigError("lines 必须是 (xs, ys, zs) 三元组")
    gap = float(min_gap_m)
    if not np.isfinite(gap) or gap < 0.0:
        raise ConfigError(f"min_gap_m 必须是非负有限数，实得 {min_gap_m!r}")
    grids = [np.unique(np.asarray(v, dtype=float).reshape(-1)) for v in lines]
    for ax, g in enumerate(grids):
        if g.size < 1:
            raise ConfigError(f"{_AXIS_NAMES[ax]} 轴线集为空")
        if not np.all(np.isfinite(g)):
            raise ConfigError(f"{_AXIS_NAMES[ax]} 轴线集含非有限值")

    def has(g: np.ndarray, v: float) -> bool:
        idx = int(np.searchsorted(g, v))
        return idx < g.size and float(g[idx]) == v

    violations: list[dict[str, Any]] = []
    min_half = float("inf")
    min_mid_gap = float("inf")
    for port in geom.ports:
        s, t = port.start, port.stop
        for ax in range(3):
            lo, hi = float(s[ax]), float(t[ax])
            mid = 0.5 * (lo + hi)
            half = 0.5 * abs(hi - lo)
            min_half = min(min_half, half)
            g = grids[ax]
            reasons: list[str] = []
            if not half > gap:
                reasons.append(f"半跨 {half:.3e}m ≤ 去重阈值 {gap:.1e}m（探针退化，<2 格）")
            for name, v in (("start", lo), ("stop", hi), ("mid", mid)):
                if not has(g, v):
                    reasons.append(f"{name}={v!r} 不在线集（{'缺中心硬线' if name == 'mid' else '缺盒边线'}）")
            if has(g, mid):
                idx = int(np.searchsorted(g, mid))
                left = mid - float(g[idx - 1]) if idx > 0 else float("inf")
                right = float(g[idx + 1]) - mid if idx + 1 < g.size else float("inf")
                near = min(left, right)
                min_mid_gap = min(min_mid_gap, near)
                if not near > gap:
                    reasons.append(f"中线距最近邻线 {near:.3e}m ≤ {gap:.1e}m（去重会吞中线）")
            for reason in reasons:
                violations.append({
                    "port": int(port.number), "label": port.label,
                    "axis": _AXIS_NAMES[ax], "reason": reason,
                })
    return {
        "n_ports": len(geom.ports),
        "min_gap_m": gap,
        "min_half_span_m": (min_half if np.isfinite(min_half) else 0.0),
        "min_mid_gap_m": (min_mid_gap if np.isfinite(min_mid_gap) else 0.0),
        # 信息项（非判定）：线集内全局最小邻距——结构线间的 ULP 级近重合
        # （如 (c+1)·p 与 c·p+a+g 的浮点异算）由渲染端 #152 去重收敛，
        # 探针中线与之相距 min_mid_gap_m，不受影响。
        "min_adjacent_gap_m": {
            _AXIS_NAMES[ax]: (float(np.min(np.diff(g))) if g.size > 1 else None)
            for ax, g in enumerate(grids)
        },
        "n_violations": len(violations),
        "violations": violations,
        "pass": not violations,
    }


def ui_cross_round_drift(
    uf_all: Any,
    if_all: Any,
    *,
    floor: float = 1.0e-30,
    floor_z: float = 1.0e-9,
    rel_floor: float = 0.0,
) -> dict[str, Any]:
    """跨轮 Z_ui 漂移诊断（#257：装配矩阵类先做跨轮漂移诊断；零仿真）。

    输入 (n_rounds=q, q, n_freq)：``uf_all[k, p]`` / ``if_all[k, p]`` 为端口
    p+1 在激励轮 k（激励端口 k+1）的电压/电流 DFT（与 :func:`assemble_s_from_ui`
    同形同义）。物理依据：非激励端口 p 在任何轮都是同一 50Ω 端接，其
    ``Z_ui = uf/if`` 原理上 **轮不变**；实测跨轮漂移是探针装配偏差（吸附
    位移、对偶环面积随激励位置变）的直接观测量——病理档
    同端口跨轮偏差中位 1.9%/最大 57%，装配前先看此量再决定是否重提取。

    量的定义（确定性）：端口 p 只取轮 k≠p（k=p 为激励口，Z_ui 含源不参与）、
    ``|if| > floor`` 的样本；逐频以各轮实/虚部中位为鲁棒中心 ``c(f)``，
    相对偏差 ``|z_k(f) − c(f)| / (|c(f)| + floor_z)``；逐端口报 (轮,频) 上的
    中位与最大，另报 **逐轮频中位的跨轮最大** ``port_max_freqmedian_rel``
    （先对 f 取中位再对 k 取最大：压掉单频尖峰，回答"哪一轮把这口带偏"）。

    信噪分层（真机档实证，2026-09-18 150 轮零仿真复算）：漂移
    随样本电流信噪 ``snr = |if[k,p,f]| / median_k |if[k,p,f]|`` 单调——弱耦合
    远端轮（snr<1%）桶中位 18.8%/最大 17.5，强信号桶（snr≥10）中位 1.1%/最大
    0.19；前者是比值噪声（中线修复不针对它），后者才是探针几何拾取底（修复
    靶点）。故 (a) 恒报 ``snr_buckets``（固定桶边 :data:`UI_DRIFT_SNR_EDGES`
    的 n/中位/p95/最大制表）；(b) ``rel_floor``>0 时把 snr<rel_floor 的样本从
    全部逐端口统计中剔除（缺省 0=全样本）。返回逐端口数组 ``port_median_rel``
    / ``port_max_rel`` / ``port_max_freqmedian_rel``（无有效样本处为 NaN）、
    ``port_zui_abs_median``（Ω，端接量级对照）、``n_valid_samples``，及汇总
    ``median_of_port_median`` / ``max_of_port_max`` / ``max_of_port_max_freqmedian``
    / ``worst_port``（1 基端口号，按 ``port_max_freqmedian_rel``）/
    ``n_ports_defined``。本函数不设门限、不产生物理常数：健康/病理
    判读由调用方对照真机档数字。
    """
    um = np.asarray(uf_all, dtype=complex)
    im = np.asarray(if_all, dtype=complex)
    if um.ndim != 3 or um.shape != im.shape or um.shape[0] != um.shape[1]:
        raise ConfigError(
            "uf_all/if_all 必须是同形 (n_rounds=q, q, n_freq)，实得 "
            f"{um.shape} / {im.shape}")
    fl = float(floor)
    flz = float(floor_z)
    rfl = float(rel_floor)
    if not (np.isfinite(fl) and fl >= 0.0 and np.isfinite(flz) and flz >= 0.0
            and np.isfinite(rfl) and rfl >= 0.0):
        raise ConfigError(
            f"floor/floor_z/rel_floor 必须是非负有限数，实得 "
            f"{floor!r}/{floor_z!r}/{rel_floor!r}")
    q, _, nf = um.shape
    amp = np.abs(im)
    valid = amp > fl
    with np.errstate(divide="ignore", invalid="ignore"):
        z_ui = np.where(valid, um / np.where(valid, im, 1.0), np.nan + 0j)
    port_median = np.full(q, np.nan)
    port_max = np.full(q, np.nan)
    port_max_fmed = np.full(q, np.nan)
    port_zabs = np.full(q, np.nan)
    n_valid = np.zeros(q, dtype=int)
    rel_pool: list[np.ndarray] = []
    snr_pool: list[np.ndarray] = []
    for p in range(q):
        rounds = np.array([k for k in range(q) if k != p], dtype=int)
        if rounds.size == 0:
            continue
        zp = z_ui[rounds, p, :]  # (q-1, nf)
        vp = valid[rounds, p, :]
        ap = amp[rounds, p, :]
        with np.errstate(all="ignore"):
            med_amp = _nanmedian_quiet(np.where(vp, ap, np.nan), axis=0)  # (nf,)
            snr = ap / np.where(med_amp > 0.0, med_amp, np.nan)[None, :]
        snr = np.where(np.isfinite(snr), snr, np.nan)
        if rfl > 0.0:
            vp = vp & np.isfinite(snr) & (snr >= rfl)
        n_valid[p] = int(np.count_nonzero(vp))
        if n_valid[p] == 0:
            continue
        zr = np.where(vp, zp.real, np.nan)
        zi = np.where(vp, zp.imag, np.nan)
        with np.errstate(all="ignore"):
            center = _nanmedian_quiet(zr, axis=0) + 1j * _nanmedian_quiet(zi, axis=0)  # (nf,)
            rel = np.abs(zp - center[None, :]) / (np.abs(center)[None, :] + flz)
        rel = np.where(vp & np.isfinite(rel), rel, np.nan)
        if not np.any(np.isfinite(rel)):
            continue
        port_median[p] = float(_nanmedian_quiet(rel))
        port_max[p] = float(np.nanmax(rel))
        with np.errstate(all="ignore"):
            round_fmed = _nanmedian_quiet(rel, axis=1)  # (q-1,)：每轮的频中位
        if np.any(np.isfinite(round_fmed)):
            port_max_fmed[p] = float(np.nanmax(round_fmed))
        port_zabs[p] = float(_nanmedian_quiet(np.where(vp, np.abs(zp), np.nan)))
        keep = np.isfinite(rel) & np.isfinite(snr)
        rel_pool.append(rel[keep])
        snr_pool.append(snr[keep])
    defined = np.isfinite(port_median)
    n_def = int(np.count_nonzero(defined))
    rel_all = np.concatenate(rel_pool) if rel_pool else np.zeros(0)
    snr_all = np.concatenate(snr_pool) if snr_pool else np.zeros(0)
    edges = (0.0, *UI_DRIFT_SNR_EDGES, np.inf)
    buckets: list[dict[str, Any]] = []
    for lo, hi in pairwise(edges):
        m = (snr_all >= lo) & (snr_all < hi)
        n = int(np.count_nonzero(m))
        buckets.append({
            "snr_lo": float(lo), "snr_hi": (None if not np.isfinite(hi) else float(hi)),
            "n": n,
            "rel_median": (float(np.median(rel_all[m])) if n else None),
            "rel_p95": (float(np.percentile(rel_all[m], 95)) if n else None),
            "rel_max": (float(np.max(rel_all[m])) if n else None),
        })
    out: dict[str, Any] = {
        "n_ports": int(q),
        "n_freq": int(nf),
        "rel_floor": rfl,
        "port_median_rel": port_median,
        "port_max_rel": port_max,
        "port_max_freqmedian_rel": port_max_fmed,
        "port_zui_abs_median": port_zabs,
        "n_valid_samples": n_valid,
        "n_ports_defined": n_def,
        "snr_buckets": buckets,
        "median_of_port_median": None,
        "max_of_port_max": None,
        "max_of_port_max_freqmedian": None,
        "worst_port": None,
    }
    if n_def > 0:
        out["median_of_port_median"] = float(np.median(port_median[defined]))
        out["max_of_port_max"] = float(np.max(port_max[defined]))
        fmed_def = np.isfinite(port_max_fmed)
        if np.any(fmed_def):
            out["max_of_port_max_freqmedian"] = float(np.max(port_max_fmed[fmed_def]))
            out["worst_port"] = int(np.argmax(np.where(defined, port_max_fmed, -np.inf))) + 1
        else:
            out["worst_port"] = int(np.argmax(np.where(defined, port_max, -np.inf))) + 1
    return out


# --------------------------------------------------------------------------- #
# stage-5c：激励口参考面重定标（SREF 探针链自提取）。
# 证据链=150 轮零仿真离线复算（基线与
# 修正后 verdict 逐位一致），误差模型：
#   接收口集总律 u_t=−z0·i_t（离散意义精确，同 stage-5 S1 口径）、探针误差
#   u=e^a·u_t、i=e^b·i_t、m=(a+b)/2 共模、Δ=a−b 差分。定案四条：
#   ① Δ_p(f)=log(median_k[−Z_ui/z0]) 是**纯延时**（Im Δ∝f，R²=0.9998；τ 中位
#      −1.087ps≈采样位差 0.21mm、跨口 std 0.417ps——预期"~1.3ps 量级"
#      在此意义下成立；但近共模，公共延时在互易差分中消去，对 rec 底是
#      二阶小量）；
#   ② num_wav=num_cur+inc^meas 逐样本精确（恒等式）→ wave 口径 = 逐条目
#      精确去 Δ 的 current 口径（rec 1.460e-2→8.965e-3 的解析本质；逐口常数
#      行因子做不到——Δ 逐轮散度主导，实测行因子修正反而变差 1.59e-2）；
#   ③ 激励口 SREF 列误差 = e^{−m_k}/C_k，C_k=cosh(Δ_k/2)+Γ_k·sinh(Δ_k/2)；
#      Γ̂ 由对角元模型恒等式 Ŝ_kk=(sinh+Γcosh)/C 精确双线性反演
#      （Γ̂=(Ŝ·ch−sh)/(ch−Ŝ·sh)；一阶捷径 ch+Ŝ·sh 含 O(Δ²(1−Γ²)) 误差）。
#      wave+列因子 C：rec 8.965e-3→7.077e-3（2.06×，非循环最优）；反演假定
#      端接无源（真机 |Γ̂|max=0.695）且分母不退化（|Δ|≪1 时 ≈1）。
#   ④ 剩余底 = 每口**常数相位规范 m**（SREF 参考面口径差：带内 std
#      3.0e-3、τ_m 中位 −0.17ps 常数项主导、Re~1e-3）——在端接律 Z_ui（m 消去）与对角
#      S_kk（m 消去）中原理性不可见 → 探针链自提取不可辨识；≤5e-3
#      目标**未达**（上限 7.077e-3，2.06×，如实报告）。下一步：et/ht 源参考
#      逐轮精修列、HFSS 逐口仲裁 m、或 S2 互易势场显式标注为数值口径
#      （rec→3.3e-3，循环量）。
# --------------------------------------------------------------------------- #


def termination_delta(
    uf_all: Any,
    if_all: Any,
    *,
    reference_impedance: float = DEFAULT_REFERENCE_IMPEDANCE,
    current_floor: float = 1.0e-30,
    snr_min: float = 0.0,
) -> tuple[np.ndarray, dict[str, Any]]:
    """端接轮定律逐口提取 u/i 探针差分误差 ``Δ_p(f)``（stage-5c，零仿真）。

    模型：接收口（非激励轮）集总律 ``u_t = −z0·i_t`` 离散精确，探针误差
    ``u = e^a·u_t``、``i = e^b·i_t`` → ``Z_ui = e^{a−b}·(−z0)``，故

    ``Δ_p(f) = log(median_k[−Z_ui(k,p,f)/z0])``（k≠p 轮，实/虚部分别取中位）。

    这是 SREF 探针链**自提取**的逐口可观测量（不用互易、不用外部基准）；
    Δ 的物理来源是 u/i 探针采样位置差 → 等效传输段（纯延时，真机档
    τ 中位 −1.087ps、Im 线性 R² 0.9998，见 :func:`delay_model_delta`）。
    **可辨识性边界（如实声明）**：共模
    ``m=(a+b)/2`` 在 Z_ui 中消去（对角 S_kk 中同样消去），本函数不可见、
    任何端接侧自提取都不可辨识——修正上限见 :func:`apply_sref_recal`。

    返回 ``(delta, info)``：``delta`` 形状 (n_freq, q) 复数；``info`` 报告
    有效轮数与无有效样本的 (频, 口) 数（该处 Δ 置 0 = 修正中性，不阻塞）。
    ``current_floor`` 为 |if| 有效性下限；``snr_min``>0 时只取
    |if| ≥ snr_min×该口跨轮中位 |if| 的轮（真机档 ≥10× 桶漂移 0.3% vs
    <1% 桶 18.8%，#282 分层口径）。
    """
    um = np.asarray(uf_all, dtype=complex)
    im = np.asarray(if_all, dtype=complex)
    if um.ndim != 3 or um.shape != im.shape or um.shape[0] != um.shape[1]:
        raise ConfigError(
            "uf_all/if_all 必须是同形 (n_rounds=q, q, n_freq)，实得 "
            f"{um.shape} / {im.shape}")
    z0 = float(reference_impedance)
    if not np.isfinite(z0) or z0 <= 0.0:
        raise ConfigError(f"reference_impedance 必须是有限正数，实得 {reference_impedance!r}")
    fl = float(current_floor)
    smin = float(snr_min)
    if not (np.isfinite(fl) and fl >= 0.0 and np.isfinite(smin) and smin >= 0.0):
        raise ConfigError(
            f"current_floor/snr_min 必须是非负有限数，实得 {current_floor!r}/{snr_min!r}")
    q, _, nf = um.shape
    if q < 2:
        raise ConfigError(f"q 必须 >=2（差分误差需跨轮中位），实得 {q}")
    amp = np.abs(im)
    valid = amp > fl
    med_amp = np.empty((q, nf))
    for p in range(q):
        rounds = np.array([k for k in range(q) if k != p], dtype=int)
        med_amp[p] = _nanmedian_quiet(
            np.where(valid[rounds, p], amp[rounds, p], np.nan), axis=0)
    delta = np.zeros((nf, q), dtype=complex)
    n_used = np.zeros((nf, q), dtype=int)
    n_no_valid = 0
    for p in range(q):
        rounds = np.array([k for k in range(q) if k != p], dtype=int)
        with np.errstate(divide="ignore", invalid="ignore"):
            z = np.where(valid[rounds, p], um[rounds, p] / np.where(
                valid[rounds, p], im[rounds, p], 1.0), np.nan + 0j)
        if smin > 0.0:
            snr = amp[rounds, p] / np.where(med_amp[p][None, :] > 0,
                                            med_amp[p][None, :], np.nan)
            z = np.where(snr >= smin, z, np.nan + 0j)
        for f in range(nf):
            v = np.isfinite(z[:, f])
            n_used[f, p] = int(np.count_nonzero(v))
            if not np.any(v):
                n_no_valid += 1  # Δ=0：修正中性，如实计数不静默扩散
                continue
            med = np.median(z[v, f].real) + 1j * np.median(z[v, f].imag)
            delta[f, p] = np.log(med / (-z0))
    info: dict[str, Any] = {
        "n_freq": int(nf), "n_ports": int(q),
        "current_floor": fl, "snr_min": smin,
        "n_rounds_used_median": float(np.median(n_used)),
        "n_no_valid": int(n_no_valid),
    }
    return delta, info


def delay_model_delta(delta: Any, freq_hz: Any) -> tuple[np.ndarray, dict[str, Any]]:
    """Δ_p(f) 的逐口延迟模型拟合（stage-5c）：``Δ̂ = re_c + j(im_c + 2πf·τ)``。

    每口 3 个实参数（Re 常数 + Im 常数/斜率）：纯 u/i 采样空间偏在该模型下
    ``re_c≈0``、``τ``=等效延时（空间偏 δx = τ·c0/√εeff）。返回
    ``(delta_fit, info)``；``info`` 含逐口 ``tau_s``/``re_const``/``im_const``、
    Im 线性拟合 R²（真机档中位 0.9998 = 纯延时判据）与最大拟合残差。
    真机 150 轮实测 τ 中位 **−1.087ps**（≈u/i 采样位差 0.21mm，预期
    "~1.3ps 量级"在此意义下成立——但跨口 std 仅 0.42ps、近共模，互易差分
    中大部分消去，见 :func:`termination_delta` 与 stage-5c 节注释）。
    """
    dm = np.asarray(delta, dtype=complex)
    if dm.ndim != 2 or dm.shape[0] < 1:
        raise ConfigError(f"delta 必须是 (n_freq, q)，实得 shape={dm.shape}")
    f = np.asarray(freq_hz, dtype=float)
    if f.ndim != 1 or f.shape[0] != dm.shape[0] or not np.all(np.isfinite(f)):
        raise ConfigError(
            f"freq_hz 必须是与 delta 同长的有限一维数组，实得 {freq_hz!r}")
    nf, q = dm.shape
    w = 2.0 * np.pi * f
    tau = np.empty(q)
    im_c = np.empty(q)
    re_c = np.empty(q)
    r2_im = np.empty(q)
    design = np.vstack([np.ones(nf), w]).T
    for p in range(q):
        dre, dim = dm[:, p].real, dm[:, p].imag
        re_c[p] = float(np.median(dre))
        (b0, b1), *_ = np.linalg.lstsq(design, dim, rcond=None)
        im_c[p] = float(b0)
        tau[p] = float(b1)  # 设计阵已用 w=2πf：斜率即 τ（秒），不再除 2π
        ss = float(np.sum((dim - dim.mean()) ** 2))
        r2_im[p] = (1.0 - float(np.sum((dim - (b0 + b1 * w)) ** 2)) / ss
                    if ss > 0 else np.nan)
    dhat = re_c[None, :] + 1j * (im_c[None, :] + w[:, None] * tau[None, :])
    info = {
        "tau_s": tau, "re_const": re_c, "im_const": im_c,
        "r2_imag_linear": r2_im,
        "r2_imag_linear_median": (float(np.nanmedian(r2_im))
                                  if np.any(np.isfinite(r2_im)) else None),
        "resid_max": float(np.max(np.abs(dm - dhat))),
    }
    return dhat, info


def sref_column_factors(delta: Any, s_diag: Any) -> np.ndarray:
    """SREF 混合列因子 ``C_k(f) = cosh(Δ_k/2) + Γ̂_k·sinh(Δ_k/2)``（stage-5c）。

    模型：激励口 ``inc^meas = e^{m_k}·inc_t·C_k``，列误差 ``e^{−m_k}/C_k``；
    ``C_k`` 由端接 Δ_k 与 Γ̂_k 构造。``s_diag`` 取装配 S 的对角 (n_freq, q)，
    Γ̂ 由对角在模型内**精确双线性反演**（非迭代、非一阶近似）：

    ``Ŝ_kk = (sinh(Δ/2)+Γ·cosh(Δ/2))/C_k``（对角 m 消去，对角元模型恒等式）
    ``→ Γ̂ = (Ŝ·ch − sh)/(ch − Ŝ·sh)``，``C = ch + Γ̂·sh``。

    注：一阶捷径 ``ch + Ŝ·sh`` 含 O(Δ²(1−Γ²)) 误差（Γ=±1 才恰等），本函数
    不采用。可辨识部分只有 C_k（Δ 差分），``e^{−m_k}`` 不可辨识（见
    :func:`termination_delta` 边界声明）。反演假定端接网络无源
    （|Γ̂|≤1，真机 150 轮实测 max 0.695）且分母 ``ch − Ŝ·sh`` 不退化
    （|Δ|≪1 时 ≈1）。
    """
    dm = np.asarray(delta, dtype=complex)
    sd = np.asarray(s_diag, dtype=complex)
    if dm.ndim != 2 or dm.shape[0] < 1:
        raise ConfigError(f"delta 必须是 (n_freq, q)，实得 shape={dm.shape}")
    if sd.shape != dm.shape:
        raise ConfigError(
            f"s_diag 必须与 delta 同形 {dm.shape}，实得 {sd.shape}")
    if not (np.all(np.isfinite(dm)) and np.all(np.isfinite(sd))):
        raise ConfigError("delta/s_diag 含非有限值")
    sh, ch = np.sinh(dm / 2.0), np.cosh(dm / 2.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        gamma = (sd * ch - sh) / (ch - sd * sh)
    if not np.all(np.isfinite(gamma)):
        raise ConfigError("Γ̂ 反演出非有限值（ch − Ŝ·sh 退化，Δ 不满足 ≪1）")
    return ch + gamma * sh


def apply_sref_recal(s: Any, column_factors: Any) -> np.ndarray:
    """SREF 列因子回乘：``S'[f, i, k] = S[f, i, k]·C[f, k]``（stage-5c）。

    与 :func:`assemble_s_from_ui` 的 ``sref_recal`` 参数同效（列归一化，
    激励口参考面重定标）。**诚实口径**：只修可辨识部分；剩余每口常数相位
    规范 m 不可自辨识——真机 150 轮
    实测修正上限 rec 1.460e-2→7.077e-3（≤5e-3 目标未达，剩余结构见
    stage-5c 节注释与 m 规范归因）。
    """
    sm = np.asarray(s, dtype=complex)
    if sm.ndim != 3 or sm.shape[1] != sm.shape[2]:
        raise ConfigError(f"s 必须是 (n_freq, q, q)，实得 shape={sm.shape}")
    c = np.asarray(column_factors, dtype=complex)
    if c.ndim != 2 or c.shape != (sm.shape[0], sm.shape[1]):
        raise ConfigError(
            f"column_factors 形状必须为 (n_freq, q)=({sm.shape[0]}, {sm.shape[1]})，"
            f"实得 {c.shape}")
    if not np.all(np.isfinite(c)):
        raise ConfigError("column_factors 含非有限值")
    return sm * c[:, None, :]


def sref_etht_column_factors(
    uf_all: Any,
    if_all: Any,
    freq_hz: Any,
    et_t: Any,
    et_v: Any,
    *,
    reference_impedance: float = DEFAULT_REFERENCE_IMPEDANCE,
) -> tuple[np.ndarray, dict[str, Any]]:
    """et/ht 源参考精修列（预声明口径定义）。

    以归档激励时序 ``et`` 的 DFT 为绝对相位/幅度参考，逐激励口精修 SREF
    参考列的非平滑逐频 wobble（纯离线零仿真；预声明
    "列侧已近极限，预期增益小"）：

    ``E(f) = dft_time2freq(et_t, et_v, f)``（引擎同式 e^{−jωt} 口径）
    ``r_k(f) = inc_k^meas(f)/E(f)``，``inc_k^meas = 0.5(uf[k,k]+z0·if[k,k])``
    ``r̂_k`` = :func:`delay_model_delta` 逐口 3 实参拟合(log r_k)
    ``c_et[f,k] = exp(log r_k(f) − log r̂_k(f)) = r_k(f)/r̂_k(f)``

    符号口径：列污染进**分母**（S = b/inc^meas，inc^meas = inc^true·e^{wob}
    → S = S_true·e^{−wob}），修正回乘 exp(+wob)（与 colC 同向：sref_column_factors
    同样回乘污染因子 C）。等价视角"平滑参考替换"：inc_ref = E·r̂ →
    S_ref = S·(r/r̂)。

    只作用**列**（激励口参考）；行/对角不由本因子触碰（#314 作用域口径）。
    **非循环**：只用激励口对角探针 + et 源转储，不用任何非对角 S/互易残差。
    **可辨识性如实声明**：3 参拟合保留 r_k 的平滑部分（含每口常数规范 m_k
    与纯延时——两者在装配列中原理性不可分），只剥非平滑 wobble；m 规范底
    不归本修正（外部仲裁另行）。真机档 et 跨轮逐字节相同（MD5 实证）→
    源实现逐轮不变，"逐轮精修"即逐激励口列精修。

    返回 ``(factors, info)``：``factors`` 形状 (n_freq, q)（复数列因子，
    经 ``sref_recal``/``apply_sref_recal`` 与 colC 因子乘法复合消费）；
    ``info`` 含 ``e_dft``、wobble 残差统计、相位跨度与 ``tau_s``。
    相位步 > π/2（疑似卷绕/延迟过大）或 et 谱线含零/非有限 → 显式报错
    （不静默退化）。
    """
    um = np.asarray(uf_all, dtype=complex)
    im = np.asarray(if_all, dtype=complex)
    if um.ndim != 3 or um.shape != im.shape or um.shape[0] != um.shape[1]:
        raise ConfigError(
            "uf_all/if_all 必须是同形 (n_rounds=q, q, n_freq)，实得 "
            f"{um.shape} / {im.shape}")
    z0 = float(reference_impedance)
    if not np.isfinite(z0) or z0 <= 0.0:
        raise ConfigError(f"reference_impedance 必须是有限正数，实得 {reference_impedance!r}")
    fv = np.asarray(freq_hz, dtype=float)
    q, _, nf = um.shape
    if fv.ndim != 1 or fv.shape[0] != nf or not np.all(np.isfinite(fv)) or np.any(fv <= 0.0):
        raise ConfigError(f"freq_hz 必须是与 n_freq={nf} 同长的正有限一维数组，实得 {fv.shape}")
    tv = np.asarray(et_t, dtype=float).reshape(-1)
    vv = np.asarray(et_v, dtype=float).reshape(-1)
    if tv.shape != vv.shape or tv.shape[0] < 2:
        raise ConfigError(
            f"et_t/et_v 必须是同长（≥2）时序，实得 {tv.shape[0]} / {vv.shape[0]}")
    if not (np.all(np.isfinite(tv)) and np.all(np.isfinite(vv))):
        raise ConfigError("et_t/et_v 含非有限值")
    e_dft = dft_time2freq(tv, vv, fv)
    if not np.all(np.isfinite(e_dft)) or np.any(np.abs(e_dft) <= 0.0):
        raise ConfigError(
            "et DFT 在分析频轴含零/非有限谱线（记录窗不含完整激励或频轴越界），"
            "源参考不可用")
    idx = np.arange(q)
    inc = 0.5 * (um[idx, idx, :] + z0 * im[idx, idx, :])  # 激励口对角 (q, nf)
    with np.errstate(divide="ignore", invalid="ignore"):
        rho = np.log(inc / e_dft[None, :]).T  # (n_freq, q)
    if not np.all(np.isfinite(rho)):
        raise ConfigError("log(inc^meas/E) 含非有限值（激励口 inc 采样为零/非有限）")
    dphi = float(np.max(np.abs(np.diff(rho.imag, axis=0)))) if nf >= 2 else 0.0
    if dphi > np.pi / 2.0:
        raise ConfigError(
            f"log(inc/E) 逐频相位步最大 {dphi:.3f} rad > π/2（相位轨迹穿越 ±π"
            "卷绕或延迟过大），3 参模型不可辨识，如实报错不静默退化")
    # 卷绕可检测边界（如实声明）：存储 angle 已卷绕时只能查"表观步"——
    # 真实逐频相位步 < π/2 的轨迹不会卷绕、表观步守卫充分；真实步 > π 的
    # 混叠（表观步反而小）从卷绕样本原理上不可分，由使用方保证频轴密度
    # （真机档逐频相位步 ~1e-3 rad，远离该边界）。
    rhohat, fit_info = delay_model_delta(rho, fv)
    wob = rho - rhohat  # 列污染估计（exp(+wob) 回乘；见 docstring 符号口径）
    factors = np.exp(wob)
    info: dict[str, Any] = {
        "n_freq": int(nf), "n_ports": int(q),
        "e_dft": e_dft,
        "wobble_resid_max": float(np.max(np.abs(wob))),
        "wobble_resid_median": float(np.median(np.abs(wob))),
        "phase_span_rad_max": float(np.max(np.ptp(rho.imag, axis=0))),
        "phase_step_rad_max": dphi,
        "tau_s": fit_info["tau_s"],
        "r2_imag_linear_median": fit_info["r2_imag_linear_median"],
        "identifiability": (
            "3 参拟合保留平滑部分（含 m 规范与延时），只剥非平滑 wobble；"
            "m 规范底不可辨识不归本修正；et 跨轮逐字节相同 → 源实现逐轮不变"),
    }
    return factors, info


# --------------------------------------------------------------------------- #
# stage-5c+：互易判读口径显式消费（2026-09-19 口径）。定案：SREF 重定标非循环上限 raw
# 1.460e-2→7.077e-3（≤5e-3 未达），剩余=每口常数相位规范 m 自提取不可辨识；
# S2 互易势场数值口径 rec→3.27e-3 达标但仅"显式标注"未进消费。本节把
# raw/wave/s2 做成判读路径的显式量径（缺省 raw=现状逐位不变，门阈值常量
# 全部不动）；τ 延迟模型口径不纳入消费（挂起为已知事项）。
# --------------------------------------------------------------------------- #

#: 互易判读可用量径（2026-09-19 口径）。``raw``=current-only 原始
#: 装配（缺省，现状）、``wave``=波分解装配、``s2``=S2 互易势场数值口径
#: （循环量）。τ 延迟模型（:func:`delay_model_delta`）**不在枚举内**——
#: 2026-09-19 口径挂起，不纳入消费。
RECIPROCITY_CALIBERS: tuple[str, ...] = ("raw", "wave", "s2")

#: stage-5c 登记的互易修正目标（≤5e-3）。**informational 参照，不是门**：
#: :func:`z_all_gate` 的预声明门（:data:`ZALL_GATE_*` 三常量）原样不动，
#: verdict 两套判据如实并报（``pass*``=预声明门、``reciprocity_target_met``
#: =5e-3 目标），互不改写。
RECIPROCITY_TARGET_STAGE5C = 5.0e-3


def reciprocity_caliber_matrix(
    uf_all: Any,
    if_all: Any,
    *,
    caliber: str = "raw",
    reference_impedance: float = DEFAULT_REFERENCE_IMPEDANCE,
) -> tuple[np.ndarray, dict[str, Any]]:
    """口径显式装配：raw/wave/s2 三档 → ``(S 矩阵, 口径出处 dict)``（零仿真）。

    - ``"raw"``（缺省）：current-only 原始装配（= :func:`assemble_s_from_ui`
      缺省路径逐位一致；150 轮真机 rec 1.460e-2）；
    - ``"wave"``：波分解装配（150 轮真机 rec 8.965e-3；= 逐条目精确去 Δ 的
      current 口径，stage-5c ②恒等式）；
    - ``"s2"``：**S2 数值口径**（循环量，2026-09-19 口径显式消费）：
      wave 装配 → :func:`termination_delta` 端接律 Δ →
      :func:`sref_column_factors` 列因子（= stage-5c 非循环最优 wav+colC）
      → :func:`fit_reciprocity_gain` 互易势场 → :func:`apply_port_gain`。
      150 轮真机 rec→3.2722e-3（wav+colC 口径；
      raw_wave 基变体 3.2615e-3 同达标）。

    **循环性如实声明**：互易势场用互易残差自身定标——连不可辨识的 m 规范
    也一并吸收（这正是"循环"的含义）——只作"数值无源投影"同级的显式标注
    口径，**不是物理修复**；绝对尺度/物理可信度仍须 HFSS 仲裁（#190）。
    τ 延迟模型不在链内（挂起事项）。返回 ``prov`` 携带
    ``caliber`` / ``caliber_circular`` / ``caliber_chain``（s2 档另含
    ``gain_fit`` 拟合残差=旋度下界、``delta_info`` 提取有效性摘要）。
    """
    if caliber not in RECIPROCITY_CALIBERS:
        raise ConfigError(
            f"caliber 只接受 {'/'.join(RECIPROCITY_CALIBERS)}，实得 {caliber!r}"
            "（τ 延迟模型口径挂起，不纳入消费）")
    um = np.asarray(uf_all, dtype=complex)
    im = np.asarray(if_all, dtype=complex)
    z0 = float(reference_impedance)
    if caliber == "raw":
        s = assemble_s_from_ui(um, im, reference_impedance=z0, numerator="current")
        prov: dict[str, Any] = {
            "caliber": caliber,
            "caliber_circular": False,
            "caliber_chain": "assemble_s_from_ui(numerator='current') 原始装配",
        }
        return s, prov
    s = assemble_s_from_ui(um, im, reference_impedance=z0, numerator="wave")
    if caliber == "wave":
        prov = {
            "caliber": caliber,
            "caliber_circular": False,
            "caliber_chain": "assemble_s_from_ui(numerator='wave') 波分解装配",
        }
        return s, prov
    # s2：wav+colC（stage-5c 非循环修正）→ 互易势场（循环步骤，显式标注）
    delta, delta_info = termination_delta(um, im, reference_impedance=z0)
    col = sref_column_factors(delta, np.diagonal(s, axis1=1, axis2=2))
    s_base = apply_sref_recal(s, col)
    x, gain_info = fit_reciprocity_gain(s_base)
    s = apply_port_gain(s_base, x)
    prov = {
        "caliber": caliber,
        "caliber_circular": True,
        "caliber_chain": (
            "wave 装配 → termination_delta → sref_column_factors（wav+colC）"
            "→ fit_reciprocity_gain → apply_port_gain（S2 循环量，数值口径）"),
        "gain_fit": gain_info,
        "delta_info": {
            "n_no_valid": int(delta_info["n_no_valid"]),
            "n_rounds_used_median": float(delta_info["n_rounds_used_median"]),
        },
    }
    return s, prov


def z_all_gate_caliber(
    uf_all: Any,
    if_all: Any,
    *,
    caliber: str = "raw",
    reference_impedance: float = DEFAULT_REFERENCE_IMPEDANCE,
) -> dict[str, Any]:
    """口径显式消费的 Z_ALL 判读 verdict：:func:`z_all_gate` ∘ 口径矩阵 + 出处。

    返回 = :func:`z_all_gate`（预声明门，:data:`ZALL_GATE_*` 常量不动）逐键
    + ``reciprocity_caliber_matrix`` 的口径出处（``caliber`` /
    ``caliber_circular`` / ``caliber_chain``，s2 档另含 ``gain_fit`` /
    ``delta_info``）+ ``reciprocity_target`` / ``reciprocity_target_met``
    （stage-5c ≤5e-3 登记目标，informational，与 ``pass*`` 判据独立并报）。
    全部为 JSON 标量，可直接落 verdict json。缺省 ``caliber="raw"`` 的门
    指标与 ``z_all_gate(assemble_s_from_ui(...))`` 逐位一致（回归钉）。
    """
    s, prov = reciprocity_caliber_matrix(
        uf_all, if_all, caliber=caliber, reference_impedance=reference_impedance)
    out = z_all_gate(s, reference_impedance=reference_impedance)
    out.update(prov)
    out["reciprocity_target"] = RECIPROCITY_TARGET_STAGE5C
    out["reciprocity_target_met"] = bool(
        out["reciprocity_max"] <= RECIPROCITY_TARGET_STAGE5C)
    return out
