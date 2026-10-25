"""em_doctor_service：自定义 EM 模型清单体检器（K5，aurora_k 战役，P12/F8）。

用户实测病灶（反馈 §6.1 P12/P13，2026-10-23）：用户用自写 pyaedt 脚本建模
八角电感——端口 aperture z 覆盖 0–190 而金属层在 200.2–205.2 μm（**aperture
根本没包含金属**），工程照样能建、能解、能导出 Touchstone，得到
L≈0.135 nH（等效短路）假结果；HFSS 的 ``ValidateDesign`` 只查语法/拓扑/
材料，不查端口语义。另两族：植球把信号短到地（S21≈−99.6 dB）、0.2 μm
薄层扫掠建成 15 μm 竖墙（SRF 6.3→0.95 GHz）。本模块给自定义模型一个
pre-solve 几何/端口语义检查器：**清单 dict 进 → 体检报告 dict 出**，纯几何
数值判定，零真机零 AEDT 依赖（铁律 7：判据是确定性数值规则，不产数字）。

检查清单 = 反馈 §6.3 表 16 项（本 docstring 末尾有逐项归属表）。v1 裁定：
**面向已有清单数据可判定的子集**；需要打开 AEDT 工程的活体几何/面 ID 检查
（真体布尔交/面赋值/模式解）是 v2，v1 输出 SKIP(v2) 如实标注不硬凑（#122）。

模型清单（model inventory）schema（YAML/JSON 同构，单位缺省 um）::

    units: um                  # um|mm|m（μm/meter 归一收录；全部坐标同一
                               #   单位；容差随单位定标）
    domain: {bbox: [x0,y0,z0, x1,y1,z1]}          # 求解域（on_boundary 自洽用）
    device_topology: series    # series|shunt（连通分量期望缺省派生源）
    connectivity: {signal: 1, ground: 1}           # 期望连通分量数（显式覆盖）
    objects:                   # 对象清单（金属/介质，net 语义 P13）
      - name: coil
        bbox: [x0,y0,z0, x1,y1,z1]
        net: signal            # signal|ground|other（金属必属一 net）
        kind: metal            # metal|dielectric（缺省 metal——异 net 交叠
                               #   检查只对 metal；介质层务必标 dielectric）
        material: Au           # 可选（信息字段）
        thickness_z: 5.0       # 可选：声明薄层厚（#11 竖墙守卫）
    ports:
      - name: P1
        plane: {axis: y, at: -700}
        aperture_bbox: [x0,y0,z0, x1,y1,z1]        # 平面轴两坐标=平面位置
        integration_line: {start: [x,y,z], end: [x,y,z]}   # 可选
        num_modes: 1           # 可选（v1 不判——#14 v2）
        on_boundary: true      # 缺省 true：声明端口面贴求解域边界
        gap: 30                # 可选：CPW 隙宽（3×gap 空气余量建议用）
    stackup:                   # 可选：叠层（z 范围+厚度；#6/#11 用）
      - {name: GaAs, thickness: 200.0, material: GaAs, z_range: [0.0, 200.0]}
      - {name: FM,   thickness: 5.0,   material: Au,  z_range: [200.2, 205.2],
         bbox: [x0,y0,z0,x1,y1,z1]}   # bbox 可选=横向范围（缺省全域假设）
    keepouts:                  # 可选：禁入矩形（#12 植球/柱净距）
      - name: feed_slot
        rect: [x0,y0,x1,y1]    # xy 矩形
        z_range: [z0,z1]       # 可选：限 z 层面
        clearance: 30          # 可选：净距告警阈值（同单位）
        applies_to: [bump_17]  # 可选：检查对象名清单（缺省=全部对象）
    sparams: results/dut.s2p   # 可选：S 参数文件（相对清单目录解析）
    run_dir: runs/20261023_…   # 可选：run 目录（新鲜度校验，K4 verify_run）

pyaedt 侧导出示例（用户脚本尾部 ~10 行即可产出清单；bounding_box 返回
模型单位 [x0,y0,z0,x1,y1,z1]，units 字段直接用 model_units；**AEDT 长词
注意**：meter 直收归一为 m，mil/cm/in 不做倍数换算——需手改 um/mm/m，
报错点名指引（mil 请手改 um，1mil=25.4μm））::

    NETS = {"coil": "signal", "feed_l": "signal", "gnd_ring": "ground", ...}
    objs = [{"name": n, "bbox": list(app.modeler[n].bounding_box),
             "net": NETS.get(n, "other"),
             "kind": "metal" if n not in DIELECTRICS else "dielectric"}
            for n in app.modeler.object_names]
    manifest = {"units": app.modeler.model_units, "objects": objs,
                "domain": {"bbox": list(app.modeler["Region"].bounding_box)},
                "ports": PORTS, "stackup": STACK}
    import json; json.dump(manifest, open("model_manifest.json", "w"),
                           indent=1, ensure_ascii=False)

bbox 近似的语义边界（如实声明，多处检查共用的局限）：

- 连通分量（#7）用 **bbox 2D 投影接触图**——跨层金属在 xy 投影上重叠即算
  连通（高估连通：投影重叠但层间无过孔也算通）；低估不存在于该近似下。
  真接触图需活体几何（v2）。
- 异 net 交叠（#8）用 **3D bbox 交叠体积**——L 形/凹形对象的 bbox 可能
  交叠而实体不交（假阳性方向）；零体积贴面只 WARN（bbox 近似下可能是真
  短路）。真体布尔交（P9 体互穿）需活体几何（v2）。
- 薄层厚度（#11）只核 **bbox z 跨度 vs 声明 h**——竖墙家族（z 跨度≠h）
  正是该判据的靶形态。

16 项归属表（反馈 §6.3 表编号 → v1/v2）：

==== ================ ==========================================================
表#  检查             v1 裁定
==== ================ ==========================================================
 1   端口面在域边界   v2（活体 face center vs region bbox）；清单侧 on_boundary
                       自洽性由 #2 检查部分覆盖
 2   端口面不叠辐射   **v1 部分**：on_boundary 声明 vs 域 bbox 自洽；辐射面
                       叠加核查需面 ID（v2）
 3   aperture 含金属  **v1**：aperture z 覆盖 vs 金属 bbox z（+3×gap 空气余
                       量建议）
 4   aperture 落在地金 v2（2D point-in-polygon，清单无多边形几何）
 5   积分线跨地↔信号  **v1**：端点落点 vs net 标注对象 bbox
 6   叠层延伸到端口面 **v1**：叠层 z/横向范围 vs 端口平面坐标
 7   信号/地连通分量  **v1**（bbox 2D 投影近似，见上）
 8   异 net 交叠=0    **v1**（3D bbox 交叠体积，见上）
 9   体只共面不互穿   v2（真体布尔交；bbox 近似在 #8）
10   混材料 unite     v2（体积对账需活体）
11   薄层 z 厚度==h   **v1**（对象 thickness_z + 叠层 thickness/z_range）
12   植球净距/keepout **v1**（keepout 矩形 vs 对象 xy 投影 + 净距）
13   盖板窗口 vs pad  v2（开窗几何不在清单 schema）
14   端口模式数/Z0/IL v2（需求解后端口解）
15   S 参数物理 sanity **v1**（passivity σmax/互易 |Sij−Sji|——判定口径复用
                       edb_health_gate 因子单源，含 1e-9 边界余量家法）
16   结果新鲜度       **v1**（run_dir → runs_verify_service.verify_run，K4）
==== ================ ==========================================================

verdict 规则：任一 FAIL → FAIL（``ok=False``，CLI 退出码 1）；仅 WARN/SKIP
→ PASS（WARN 不翻转门——净距建议/地网分裂等属提示级）。每条检查带
``catches``（"会抓到的真实问题"，反馈表原文口吻）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope

# 注意：本模块**不定义 __all__**——公开 API 快照（scripts/check_public_api）
# 只登记带 __all__ 的模块（edb_health_gate 同款口径，新模块出生不触发
# --generate 评审动作）。

#: 报告 schema 标识（JSON 消费面稳定钉）。
SCHEMA = "em-doctor-v1"

#: 清单 schema 版本（形状变更时升位）。
MANIFEST_SCHEMA_VERSION = 1

# 状态词汇（四态：SKIP 含"数据缺席"与"v2 活体检查"两种 reason）。
PASS = "PASS"
FAIL = "FAIL"
WARN = "WARN"
SKIP = "SKIP"

#: v2 活体检查的 SKIP 标记（消费方可按此过滤 v2 面）。
V2_TAG = "v2"

NET_SIGNAL = "signal"
NET_GROUND = "ground"
NET_OTHER = "other"
_VALID_NETS = frozenset({NET_SIGNAL, NET_GROUND, NET_OTHER})
_METAL_NETS = frozenset({NET_SIGNAL, NET_GROUND})

#: 单位归一（μ 字形变体收编；AEDT 长词 meter 直收归一为 m——纯映射不做
#: 倍数换算）与接触容差缺省（清单单位制）：接触=两 bbox 间隙 ≤ tol 视为
#: 贴连（AEDT bbox 通常精确落格，0.5 量级只吸收浮点/舍入；可用清单
#: tolerances.contact 显式覆盖）。
_UNIT_ALIASES = {"um": "um", "μm": "um", "mm": "mm", "m": "m", "meter": "m"}
_UNIT_CONTACT_TOL = {"um": 0.5, "mm": 5e-4, "m": 5e-7}

#: AEDT 长词拒收指路（不在纯映射别名表——mil/in/cm 需倍数换算或无容差
#: 定标表，别名表不做倍数，拒收并在报错里点名手改路径，不留裸 "需
#: um|mm|m" 让用户自己猜换算）。meter 不在此表（上表直收）。
_UNIT_REJECT_HINTS = {
    "mil": "mil 请手改 um（1mil=25.4μm）",
    "cm": "cm 无容差定标表，请手改 mm（1cm=10mm）",
    "in": "in 请手改 mm（1in=25.4mm）",
}

#: 薄层厚度守卫容差（#11）：|bbox z 跨度 − h| ≤ max(rel·h, abs) 为过。
#: rel=1%（几何建模惯例精度）；abs 按清单单位制定标（um 制=1e-3 即 1nm，
#: mm 制=1e-6 同为 1nm——单位盲会让 mm 制清单放水 1000 倍，K20 审查 P2-1）。
_THICKNESS_REL_TOL = 0.01
_THICKNESS_ABS_TOL = {"um": 1e-3, "mm": 1e-6, "m": 1e-9}

#: aperture 金属覆盖硬判据的 z 覆盖余量=接触容差同源（不另造数）。
#: 3×gap 空气余量是**建议**（WARN 级），出处=反馈 P12 不变量第 2 条
#: （"衬底 + 金属 + 金属上方 3×隙空气"——用户 13:05→19:29 修复实测：
#: 金属顶 205.2 + 3×30 = 295.2 即修复后 aperture 顶）。
_AIR_MARGIN_GAP_FACTOR = 3.0

#: 反馈 §6.3 表"会抓到的真实问题"原文（人话描述，报告逐条回带）。
_CATCHES: dict[int, str] = {
    1: "内部波端口 PEC 错误",
    2: "端口模被外场吸收",
    3: "13:05 的 L≈0.135 nH 短路",
    4: "模式泄漏/端口阻抗错",
    5: "模式/符号错、负电阻",
    6: "空气悬空 CPW、台阶不连续",
    7: "pad-finger 短路（S21≈0 dB）",
    8: "植球短信号（S21≈−99 dB）",
    9: "桥柱压入金属→求解失败",
    10: "Au 层静默消失",
    11: "0.2 μm SNV 建成竖墙",
    12: "球球相撞、球压引线",
    13: "探针不可达",
    14: "模式错、参考面错",
    15: "L≈0、S21≈0、负 R",
    16: "旧 Touchstone 冒充新结果",
}


# ---------------------------------------------------------------------------
# 几何小工具（纯函数；bbox=（lo, hi）三元组对）
# ---------------------------------------------------------------------------

def _ax_index(axis: Any, where: str) -> int:
    """轴向名 → 0/1/2（x/y/z）；非法值 ValueError 带定位。"""
    text = str(axis).strip().lower()
    if text not in ("x", "y", "z"):
        raise ValueError(f"{where}: plane.axis 需 x|y|z，实际 {axis!r}")
    return {"x": 0, "y": 1, "z": 2}[text]


def _parse_bbox(value: Any, where: str) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """6 数 bbox → (lo, hi)（lo<=hi 逐轴强制；非法 ValueError）。"""
    if not isinstance(value, (list, tuple)) or len(value) != 6:
        raise ValueError(f"{where}: bbox 需 6 数 [x0,y0,z0,x1,y1,z1]，实际 {value!r}")
    try:
        nums = [float(v) for v in value]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{where}: bbox 含非数值: {value!r}") from exc
    lo = tuple(min(nums[i], nums[i + 3]) for i in range(3))
    hi = tuple(max(nums[i], nums[i + 3]) for i in range(3))
    return lo, hi


def _parse_point(value: Any, where: str) -> tuple[float, float, float]:
    """3 数点 → 三元组。"""
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"{where}: 点坐标需 3 数 [x,y,z]，实际 {value!r}")
    try:
        return float(value[0]), float(value[1]), float(value[2])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{where}: 点坐标含非数值: {value!r}") from exc


def _overlap_1d(a_lo: float, a_hi: float, b_lo: float, b_hi: float) -> float:
    """1D 区间交叠长度（不相交为 0）。"""
    return max(0.0, min(a_hi, b_hi) - max(a_lo, b_lo))


def _gap_1d(a_lo: float, a_hi: float, b_lo: float, b_hi: float) -> float:
    """1D 区间间隙（相交为 0）。"""
    return max(0.0, b_lo - a_hi, a_lo - b_hi)


def _bbox_volume_overlap(
    a: tuple[tuple[float, ...], tuple[float, ...]],
    b: tuple[tuple[float, ...], tuple[float, ...]],
) -> float:
    """3D bbox 交叠体积（不相交为 0）。"""
    vol = 1.0
    for i in range(3):
        ov = _overlap_1d(a[0][i], a[1][i], b[0][i], b[1][i])
        if ov <= 0.0:
            return 0.0
        vol *= ov
    return vol


def _boxes_touch(
    a: tuple[tuple[float, ...], tuple[float, ...]],
    b: tuple[tuple[float, ...], tuple[float, ...]],
    *,
    tol: float,
    axes: tuple[int, ...] = (0, 1, 2),
) -> bool:
    """bbox 接触判定：给定轴集上每轴间隙 ≤ tol（任一轴超 tol 即不接触）。

    axes=(0,1)=xy 投影接触（#7 连通近似）；axes=(0,1,2)=3D 接触。
    """
    return all(
        _gap_1d(a[0][i], a[1][i], b[0][i], b[1][i]) <= tol for i in axes)


def _point_in_box(
    point: tuple[float, float, float],
    box: tuple[tuple[float, ...], tuple[float, ...]],
    *,
    tol: float,
) -> bool:
    """点落在 bbox 内（各向含 tol 外扩——积分线端点落在金属表面边上）。"""
    return all(box[0][i] - tol <= point[i] <= box[1][i] + tol for i in range(3))


def _components(names: list[str], edges: list[tuple[str, str]]) -> list[list[str]]:
    """并查集连通分量（成员列表按输入序，确定性输出）。"""
    parent: dict[str, str] = {n: n for n in names}

    def find(x: str) -> str:
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:  # 路径压缩
            parent[x], x = root, parent[x]
        return root

    for a, b in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra
    groups: dict[str, list[str]] = {}
    for n in names:
        groups.setdefault(find(n), []).append(n)
    return sorted(groups.values(), key=lambda g: names.index(g[0]))


# ---------------------------------------------------------------------------
# 清单归一（load 与 run 共用；错误逐条收集多报不放过 #316）
# ---------------------------------------------------------------------------

class _Model:
    """归一化清单（内部容器；只读快照，检查器全部从这里读）。"""

    def __init__(self, raw: dict[str, Any], errors: list[str]) -> None:
        m = raw
        self.raw = m
        units_raw = str(m.get("units", "um")).strip()
        self.units = _UNIT_ALIASES.get(units_raw)
        if self.units is None:
            hint = _UNIT_REJECT_HINTS.get(units_raw.lower())
            if hint:
                errors.append(f"units {units_raw!r} 不收：{hint}")
            else:
                errors.append(f"units 需 um|mm|m，实际 {units_raw!r}")
            self.units = "um"
        tol_cfg = m.get("tolerances") if isinstance(m.get("tolerances"), dict) else {}
        try:
            override = float(tol_cfg["contact"]) if "contact" in tol_cfg else None
        except (TypeError, ValueError):
            override = None
            errors.append("tolerances.contact 非数值，已忽略并回退单位缺省")
        self.contact_tol = override if override is not None else _UNIT_CONTACT_TOL[self.units]
        self.volume_tol = self.contact_tol ** 3  # 同源立方：跨单位物理一致

        self.domain: tuple[tuple[float, ...], tuple[float, ...]] | None = None
        dom = m.get("domain")
        if isinstance(dom, dict) and "bbox" in dom:
            try:
                self.domain = _parse_bbox(dom["bbox"], "domain")
            except ValueError as exc:
                errors.append(str(exc))

        self.objects: list[dict[str, Any]] = []
        for i, o in enumerate(m.get("objects") or []):
            where = f"objects[{i}]"
            if not isinstance(o, dict) or not str(o.get("name", "")).strip():
                errors.append(f"{where}: 需为含 name 的对象")
                continue
            name = str(o["name"])
            try:
                box = _parse_bbox(o.get("bbox"), f"objects[{i}]({name})")
            except ValueError as exc:
                errors.append(str(exc))
                continue
            net = str(o.get("net", NET_OTHER)).strip().lower() or NET_OTHER
            if net not in _VALID_NETS:
                errors.append(
                    f"objects[{i}]({name}): net 需 signal|ground|other，实际 {net!r}")
                net = NET_OTHER
            kind = str(o.get("kind", "metal")).strip().lower() or "metal"
            if kind not in ("metal", "dielectric"):
                errors.append(
                    f"objects[{i}]({name}): kind 需 metal|dielectric，实际 {kind!r}"
                    "（已按 metal 处理）")
                kind = "metal"
            thickness = o.get("thickness_z")
            if thickness is not None:
                try:
                    thickness = float(thickness)
                except (TypeError, ValueError):
                    errors.append(f"objects[{i}]({name}): thickness_z 非数值，已忽略")
                    thickness = None
            self.objects.append({
                "name": name, "box": box, "net": net, "kind": kind,
                "material": str(o.get("material", "")) or None,
                "thickness_z": thickness,
            })

        self.ports: list[dict[str, Any]] = []
        for i, p in enumerate(m.get("ports") or []):
            where = f"ports[{i}]"
            if not isinstance(p, dict) or not str(p.get("name", "")).strip():
                errors.append(f"{where}: 需为含 name 的端口")
                continue
            name = str(p["name"])
            plane = p.get("plane")
            if not isinstance(plane, dict) or "axis" not in plane or "at" not in plane:
                errors.append(f"{where}({name}): plane 需 {{axis, at}}")
                continue
            try:
                axis = _ax_index(plane["axis"], f"{where}({name})")
                at = float(plane["at"])
            except (TypeError, ValueError) as exc:
                errors.append(f"{where}({name}): {exc}")
                continue
            try:
                aperture = _parse_bbox(
                    p.get("aperture_bbox"), f"{where}({name}) aperture_bbox")
            except ValueError as exc:
                errors.append(str(exc))
                continue
            il = p.get("integration_line")
            il_parsed: tuple[tuple[float, float, float], ...] | None = None
            if il is not None:
                if not isinstance(il, dict) or "start" not in il or "end" not in il:
                    errors.append(
                        f"{where}({name}): integration_line 需 {{start,end}}，已忽略")
                else:
                    try:
                        il_parsed = (
                            _parse_point(il["start"], f"{where}({name}) IL start"),
                            _parse_point(il["end"], f"{where}({name}) IL end"))
                    except ValueError as exc:
                        errors.append(str(exc))
            gap = p.get("gap")
            if gap is not None:
                try:
                    gap = float(gap)
                except (TypeError, ValueError):
                    errors.append(f"{where}({name}): gap 非数值，已忽略")
                    gap = None
            self.ports.append({
                "name": name, "axis": axis, "at": at, "aperture": aperture,
                "integration_line": il_parsed, "on_boundary": bool(
                    p.get("on_boundary", True)),
                "num_modes": p.get("num_modes"), "gap": gap,
            })

        self.stackup: list[dict[str, Any]] = []
        for i, layer in enumerate(m.get("stackup") or []):
            where = f"stackup[{i}]"
            if not isinstance(layer, dict) or not str(layer.get("name", "")).strip():
                errors.append(f"{where}: 需为含 name 的层")
                continue
            name = str(layer["name"])
            zr = layer.get("z_range")
            z_range: tuple[float, float] | None = None
            if isinstance(zr, (list, tuple)) and len(zr) == 2:
                try:
                    z_range = (float(zr[0]), float(zr[1]))
                except (TypeError, ValueError):
                    errors.append(f"{where}({name}): z_range 非数值对，已忽略")
            thickness = layer.get("thickness")
            if thickness is not None:
                try:
                    thickness = float(thickness)
                except (TypeError, ValueError):
                    errors.append(f"{where}({name}): thickness 非数值，已忽略")
                    thickness = None
            bbox = None
            if "bbox" in layer:
                try:
                    bbox = _parse_bbox(layer["bbox"], f"{where}({name}) bbox")
                except ValueError as exc:
                    errors.append(str(exc))
            self.stackup.append({
                "name": name, "thickness": thickness, "z_range": z_range,
                "material": str(layer.get("material", "")) or None, "bbox": bbox,
            })

        self.keepouts: list[dict[str, Any]] = []
        for i, ko in enumerate(m.get("keepouts") or []):
            where = f"keepouts[{i}]"
            if not isinstance(ko, dict) or not str(ko.get("name", "")).strip():
                errors.append(f"{where}: 需为含 name 的禁入区")
                continue
            name = str(ko["name"])
            rect = ko.get("rect")
            if not isinstance(rect, (list, tuple)) or len(rect) != 4:
                errors.append(
                    f"{where}({name}): rect 需 4 数 [x0,y0,x1,y1]，本条忽略")
                continue
            try:
                rx0, ry0, rx1, ry1 = (float(v) for v in rect)
            except (TypeError, ValueError):
                errors.append(f"{where}({name}): rect 含非数值，本条忽略")
                continue
            zr = ko.get("z_range")
            z_range: tuple[float, float] | None = None
            if isinstance(zr, (list, tuple)) and len(zr) == 2:
                try:
                    z_range = (float(zr[0]), float(zr[1]))
                except (TypeError, ValueError):
                    z_range = None
                    errors.append(f"{where}({name}): z_range 非数值对，已忽略")
            clearance = ko.get("clearance")
            if clearance is not None:
                try:
                    clearance = float(clearance)
                except (TypeError, ValueError):
                    clearance = None
                    errors.append(f"{where}({name}): clearance 非数值，已忽略")
            applies = ko.get("applies_to")
            if applies is not None and not isinstance(applies, list):
                errors.append(f"{where}({name}): applies_to 需对象名列表，已忽略")
                applies = None
            self.keepouts.append({
                "name": name,
                "rect": (min(rx0, rx1), min(ry0, ry1), max(rx0, rx1), max(ry0, ry1)),
                "z_range": z_range, "clearance": clearance,
                "applies_to": [str(a) for a in applies] if applies else None,
            })

        conn = m.get("connectivity")
        self.connectivity: dict[str, int] = {}
        if isinstance(conn, dict):
            for key, val in conn.items():
                if isinstance(val, bool) or not isinstance(val, int) or val < 1:
                    errors.append(
                        f"connectivity.{key} 需 ≥1 整数，实际 {val!r}，已忽略")
                    continue
                self.connectivity[str(key)] = int(val)
        self.device_topology = m.get("device_topology")
        if self.device_topology not in (None, "series", "shunt"):
            errors.append(
                f"device_topology 需 series|shunt，实际 {self.device_topology!r}"
                "（已忽略；连通分量期望需显式 connectivity）")
            self.device_topology = None
        self.sparams = str(m["sparams"]) if m.get("sparams") else None
        self.run_dir = str(m["run_dir"]) if m.get("run_dir") else None

    @property
    def metals(self) -> list[dict[str, Any]]:
        return [o for o in self.objects if o["kind"] == "metal"]


def load_model_manifest(path: str | Path) -> dict[str, Any]:
    """读清单文件（.json / .yaml / .yml）→ 信封 ``{ok, manifest, path}``。

    归一化校验失败 → error 信封（errors 逐条列出定位到条目的问题，多报
    不放过 #316）；清单是检查器的输入面，条目畸形必须先修再体检。
    """
    # #140：PathLike 入参第一行收敛
    p = Path(path)
    if not p.is_file():
        return error_envelope(f"清单文件不存在: {p}", path=str(p))
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        return error_envelope(f"清单不可读: {exc}", path=str(p))
    if p.suffix.lower() == ".json":
        try:
            raw = json.loads(text)
        except ValueError as exc:
            return error_envelope(f"清单 JSON 解析失败: {exc}", path=str(p))
    elif p.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml  # 懒加载（agent_sandbox 同款惯例）

            raw = yaml.safe_load(text)
        except Exception as exc:  # yaml 异常族宽（YAMLError/ImportError）
            return error_envelope(f"清单 YAML 解析失败: {exc}", path=str(p))
    else:
        return error_envelope(
            f"清单需 .json/.yaml/.yml 文件，实际后缀 {p.suffix!r}", path=str(p))
    if not isinstance(raw, dict):
        return error_envelope(
            f"清单根节点需为映射（对象/端口/叠层），实际 {type(raw).__name__}",
            path=str(p))
    errors: list[str] = []
    _Model(raw, errors)
    if errors:
        return error_envelope(errors, path=str(p), manifest=raw)
    return ok_envelope(manifest=raw, path=str(p))


# ---------------------------------------------------------------------------
# 检查器（每条独立可测；返回 dict 行 {check, table_ref, status, ...}）
# ---------------------------------------------------------------------------

def _row(
    check: str, table_ref: int, status: str, detail: str,
    *, items: list[dict[str, Any]] | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """检查行构造（catches=反馈表"会抓到的真实问题"原文）。"""
    row: dict[str, Any] = {
        "check": check,
        "table_ref": table_ref,
        "title": _TITLES[table_ref],
        "status": status,
        "catches": _CATCHES[table_ref],
        "detail": detail,
    }
    if items:
        row["items"] = items
    if evidence:
        row["evidence"] = evidence
    return row


def _worst(statuses: list[str]) -> str:
    for st in (FAIL, WARN, PASS):
        if st in statuses:
            return st
    return SKIP


#: 16 项表检查标题（反馈 §6.3 第 2 列原文）。
_TITLES: dict[int, str] = {
    1: "端口面在求解域边界，非内部 sheet",
    2: "端口面不叠加 Radiation（on_boundary 自洽）",
    3: "aperture 含衬底+金属+上方空气",
    4: "aperture 两端落在地金属上",
    5: "积分线跨\"地→信号\"",
    6: "衬底/叠层延伸到端口面",
    7: "信号/地网络连通分量",
    8: "不同 net 交叠体积 = 0",
    9: "体只共面、不互穿",
    10: "混材料 unite 分层",
    11: "薄层 z 厚度 == h",
    12: "植球净距/keep-out",
    13: "盖板窗口 vs pad/探针",
    14: "端口模式数/Z0/IL",
    15: "S 参数物理 sanity",
    16: "结果文件新鲜度",
}


def _check_port_on_boundary(m: _Model) -> dict[str, Any]:
    """表#2（兼 #1 清单侧）：on_boundary 声明 vs 域 bbox 自洽。"""
    if not m.ports:
        return _row("port_on_boundary", 2, SKIP, "清单未声明端口")
    if m.domain is None:
        return _row(
            "port_on_boundary", 2, SKIP,
            "清单未声明 domain bbox——on_boundary 自洽校验需要域范围"
            "（补 domain.bbox 即可激活本检查）")
    tol = m.contact_tol
    items: list[dict[str, Any]] = []
    for p in m.ports:
        axis, at = p["axis"], p["at"]
        lateral = tuple(i for i in range(3) if i != axis)
        on_face = (abs(at - m.domain[0][axis]) <= tol
                   or abs(at - m.domain[1][axis]) <= tol)
        within = all(
            p["aperture"][0][i] >= m.domain[0][i] - tol
            and p["aperture"][1][i] <= m.domain[1][i] + tol for i in lateral)
        axis_name = "xyz"[axis]
        dom_lo, dom_hi = m.domain[0][axis], m.domain[1][axis]
        if p["on_boundary"]:
            if not on_face:
                item = {
                    "port": p["name"], "status": FAIL,
                    "detail": (f"声明 on_boundary=true 但端口面 {axis_name}={at}"
                               f" 不在域 bbox 面（{axis_name}∈[{dom_lo}, {dom_hi}]）"
                               "上——内部 sheet 波端口需要 PEC 背衬（内部"
                               "端口无背衬时 HFSS 警告端口模不干净），且端口面"
                               "不得叠辐射（面 ID 活体核查=v2）")}
            elif not within:
                item = {
                    "port": p["name"], "status": FAIL,
                    "detail": (f"aperture 横向越出域面（端口 {p['name']} 的"
                               " aperture 需落在域 bbox 面内）")}
            else:
                item = {
                    "port": p["name"], "status": PASS,
                    "detail": (f"端口面 {axis_name}={at} 贴域边界，aperture"
                               " 横向在域面内；辐射边界叠加核查需面 ID（v2）")}
        else:
            if on_face:
                item = {
                    "port": p["name"], "status": WARN,
                    "detail": (f"端口面 {axis_name}={at} 实际在域边界上但声明"
                               " on_boundary=false——建议贴边并让该面免辐射"
                               "（端口面与真空域边界重合、其余面"
                               "PEC 作端口壁）")}
            else:
                item = {
                    "port": p["name"], "status": PASS,
                    "detail": (f"内部波端口声明自洽（{axis_name}={at} 在域内）"
                               "；内部端口需 PEC 背衬——背衬活体核查"
                               "=v2")}
        items.append(item)
    status = _worst([i["status"] for i in items])
    n_fail = sum(1 for i in items if i["status"] == FAIL)
    detail = (f"{len(m.ports)} 个端口逐一核验"
              + (f"，{n_fail} 个 FAIL" if n_fail else "，全部自洽"))
    return _row("port_on_boundary", 2, status, detail, items=items)


def _check_aperture_covers_metal(m: _Model) -> dict[str, Any]:
    """表#3：aperture 窗口必须**捕获**端口导体（+3×gap 空气余量建议）。

    语义（照用户修复后参考模型校准）：aperture z 窗口须与端口面横窗内的
    金属 z 范围**相交**（捕获信号+邻近地）——13:05 病灶（aperture 0–190
    vs 金属 200.2–205.2）= 窗口内零金属，端口激励不到导体，解出
    L≈0.135 nH。窗口**外**金属（盖板/远端回流结构，z 与窗口不交）属
    正常有意排除——用户修复后模型（aperture 顶 295.2、盖板 300 起）即
    此形态，只记信息注记不判红；窗口含地但无信号金属（aperture 可能截
    掉信号导体）→ WARN。z 面端口（顶/底馈）无"竖直覆盖"语义，覆盖判定
    需 2D 面几何（v2 如实注记）。横窗选择：金属**跨越端口平面**且面内
    横向（非竖直轴）与 aperture 有交叠——z 是被检维度不参与选窗；
    aperture 边落金属上属正常形态（表#4 的靶）。
    """
    if not m.ports:
        return _row("aperture_covers_metal", 3, SKIP, "清单未声明端口")
    tol = m.contact_tol
    vertical = 2
    items: list[dict[str, Any]] = []
    for p in m.ports:
        axis, at = p["axis"], p["at"]
        ap = p["aperture"]
        select_axes = tuple(
            i for i in range(3) if i != axis and i != vertical)
        cover_check = axis != vertical
        # 横窗内金属：跨越端口平面（bbox 覆盖平面坐标）且面内横向与
        # aperture 窗口有交叠
        window_metals = [
            o for o in m.metals
            if o["box"][0][axis] <= at + tol and o["box"][1][axis] >= at - tol
            and all(_overlap_1d(o["box"][0][i], o["box"][1][i],
                                ap[0][i], ap[1][i]) > tol for i in select_axes)]
        if not window_metals:
            items.append({
                "port": p["name"], "status": FAIL,
                "detail": ("端口横窗内无任何金属导体——端口激励不到导体："
                           "HFSS 照样能建能解能导出，得到等效开路/短路的假"
                           "结果（0.135 nH 家族；ValidateDesign 不查端口语义）")})
            continue
        if not cover_check:
            items.append({
                "port": p["name"], "status": PASS,
                "detail": (f"z 面端口横窗含金属 {len(window_metals)} 个；"
                           "孔径竖直覆盖判定需 2D 面几何（v2 如实注记）")})
            continue
        # 捕获=金属 z 范围与 aperture z 窗口相交；窗口外金属=有意排除
        captured = [
            o for o in window_metals
            if _overlap_1d(o["box"][0][2], o["box"][1][2],
                           ap[0][2], ap[1][2]) > tol]
        excluded = [o for o in window_metals if o not in captured]
        if not captured:
            names = ", ".join(
                f"{o['name']}(z∈[{o['box'][0][2]:g}, {o['box'][1][2]:g}])"
                for o in excluded)
            items.append({
                "port": p["name"], "status": FAIL,
                "detail": (
                    f"aperture z 窗口 [{ap[0][2]:g}, {ap[1][2]:g}] 不含任何"
                    f"金属——横窗内金属 {names} 全部落在窗口外=13:05 实例"
                    "同款（aperture 0–190 vs 金属 200.2–205.2，解出 "
                    "L≈0.135 nH 等效短路）；HFSS ValidateDesign 只查语法"
                    "不查端口语义，本项必须在建模阶段拦截")})
            continue
        detail = (f"aperture z [{ap[0][2]:g}, {ap[1][2]:g}] 捕获窗口内金属"
                  f" {len(captured)} 个")
        if excluded:
            detail += (f"；{len(excluded)} 个窗口外金属如实注记（"
                       + ", ".join(o["name"] for o in excluded)
                       + "——盖板/远端回流结构属正常有意排除；若误排馈电"
                         "导体请修 aperture）")
        status = PASS
        if (not any(o["net"] == NET_SIGNAL for o in captured)
                and any(o["net"] == NET_GROUND for o in captured)):
            status = WARN
            detail += ("；窗口含地金属但无信号金属——aperture 可能截掉"
                       "了信号导体（对照积分线端点核）")
        metal_top = max(o["box"][1][2] for o in captured)
        if p["gap"]:
            required = metal_top + _AIR_MARGIN_GAP_FACTOR * p["gap"]
            margin = ap[1][2] - metal_top
            if ap[1][2] < required - tol:
                status = WARN
                detail += (
                    f"；金属上方空气余量 {margin:g} < 3×gap="
                    f"{_AIR_MARGIN_GAP_FACTOR * p['gap']:g}（建议 aperture 顶="
                    f"{required:g}——P12 不变量第 2 条：衬底+金属+上方 3×隙空气，"
                    "余量不足可能截断端口模）")
            else:
                detail += f"；上方空气余量 {margin:g} ≥ 3×gap ✓"
        else:
            detail += "；端口未声明 gap——3×gap 空气余量建议未评"
        items.append({"port": p["name"], "status": status, "detail": detail})
    status = _worst([i["status"] for i in items])
    return _row("aperture_covers_metal", 3, status,
                f"{len(m.ports)} 个端口逐一核验", items=items)


def _check_integration_line(m: _Model) -> dict[str, Any]:
    """表#5：积分线端点落点 vs net 标注对象（一端地、一端信号）。"""
    tol = m.contact_tol
    with_il = [p for p in m.ports if p["integration_line"] is not None]
    if not m.ports:
        return _row("integration_line_nets", 5, SKIP, "清单未声明端口")
    if not with_il:
        return _row("integration_line_nets", 5, SKIP,
                    "全部端口未声明 integration_line（补 start/end 即可激活）")
    items: list[dict[str, Any]] = []
    for p in with_il:
        start, end = p["integration_line"]  # type: ignore[misc]
        resolved: list[set[str] | None] = []
        for point in (start, end):
            nets = {o["net"] for o in m.metals if _point_in_box(point, o["box"], tol=tol)}
            resolved.append(nets or None)
        s_nets, e_nets = resolved
        if s_nets is None or e_nets is None:
            bad = "起点" if s_nets is None else "终点"
            items.append({
                "port": p["name"], "status": FAIL,
                "detail": (
                    f"积分线{bad}未落在任何金属上（13:05 实例：积分线在 "
                    "z=102.6 的衬底内部）——模式/符号错、负电阻的来源；"
                    "积分线应从地边沿跨到信号边沿、z 在金属层中心")})
            continue
        s_sig = NET_SIGNAL in s_nets
        e_sig = NET_SIGNAL in e_nets
        s_gnd = NET_GROUND in s_nets
        e_gnd = NET_GROUND in e_nets
        if s_sig == e_sig:
            same = sorted(s_nets | e_nets)
            items.append({
                "port": p["name"], "status": FAIL,
                "detail": (
                    f"积分线两端未跨\"地→信号\"（两端命中 net={'+'.join(same)}"
                    "——两侧同为信号或同为地/其他）；"
                    "积分线接错是模式/符号错与负电阻的直接来源")})
            continue
        if not (s_gnd or e_gnd):
            other = "终点" if s_sig else "起点"
            items.append({
                "port": p["name"], "status": FAIL,
                "detail": (
                    f"积分线{other}未落在地金属（命中 net="
                    f"{sorted(e_nets if s_sig else s_nets)}）——积分线应从"
                    "地边沿跨到信号边沿")})
            continue
        items.append({
            "port": p["name"], "status": PASS,
            "detail": (f"积分线跨地↔信号（起点 net={sorted(s_nets)}/"
                       f"终点 net={sorted(e_nets)}）✓")})
    status = _worst([i["status"] for i in items])
    return _row("integration_line_nets", 5, status,
                f"{len(with_il)}/{len(m.ports)} 个端口带积分线", items=items)


def _check_stackup_reaches_port(m: _Model) -> dict[str, Any]:
    """表#6：叠层 z 范围覆盖端口窗口 + 声明横向范围的层延伸到端口面。"""
    if not m.ports:
        return _row("stackup_reaches_port", 6, SKIP, "清单未声明端口")
    if not m.stackup:
        return _row("stackup_reaches_port", 6, SKIP, "清单未声明叠层")
    tol = m.contact_tol
    with_z = [lay for lay in m.stackup if lay["z_range"]]
    if not with_z:
        return _row("stackup_reaches_port", 6, SKIP,
                    "叠层条目均未声明 z_range（补层 z 范围即可激活）")
    z_lo = min(lay["z_range"][0] for lay in with_z)  # type: ignore[index]
    z_hi = max(lay["z_range"][1] for lay in with_z)  # type: ignore[index]
    lateral_named = [lay for lay in m.stackup if lay["bbox"] is not None]
    items: list[dict[str, Any]] = []
    for p in m.ports:
        axis, at = p["axis"], p["at"]
        ap = p["aperture"]
        overlap = _overlap_1d(ap[0][2], ap[1][2], z_lo, z_hi)
        if overlap <= tol:
            items.append({
                "port": p["name"], "status": FAIL,
                "detail": (
                    f"端口窗口 z [{ap[0][2]:g}, {ap[1][2]:g}] 与叠层总范围 "
                    f"[{z_lo:g}, {z_hi:g}] 零交叠——空气悬空 CPW/台阶不连续"
                    "（衬底/叠层必须沿信号方向延伸到端口面，"
                    "不能出现\"空气悬空 CPW\"）")})
            continue
        short_layers = [
            lay for lay in lateral_named
            if not (lay["bbox"][0][axis] <= at + tol  # type: ignore[index]
                    and lay["bbox"][1][axis] >= at - tol)]  # type: ignore[index]
        if short_layers:
            names = ", ".join(
                f"{lay['name']}({lay['bbox'][0][axis]:g}..{lay['bbox'][1][axis]:g})"  # type: ignore[index]
                for lay in short_layers)
            items.append({
                "port": p["name"], "status": FAIL,
                "detail": (f"叠层 {names} 未延伸到端口面 {'xyz'[axis]}={at}——"
                           "台阶不连续/悬空")})
            continue
        detail = (f"端口窗口与叠层 z 交叠 {overlap:g}；"
                  f"{len(lateral_named)} 层声明横向范围均延伸到端口面"
                  if lateral_named else
                  f"端口窗口与叠层 z 交叠 {overlap:g}（各层未声明横向范围，"
                  "按全域假设）")
        items.append({"port": p["name"], "status": PASS, "detail": detail})
    status = _worst([i["status"] for i in items])
    return _row("stackup_reaches_port", 6, status,
                f"{len(m.ports)} 个端口逐一核验", items=items)


def _net_components(m: _Model, net: str) -> list[list[str]]:
    """同名 net 的 bbox 2D 投影接触图连通分量（#7 近似）。"""
    objs = [o for o in m.objects if o["net"] == net]
    names = [o["name"] for o in objs]
    edges: list[tuple[str, str]] = []
    for i in range(len(objs)):
        for j in range(i + 1, len(objs)):
            if _boxes_touch(objs[i]["box"], objs[j]["box"],
                            tol=m.contact_tol, axes=(0, 1)):
                edges.append((names[i], names[j]))
    return _components(names, edges)


def _check_net_connectivity(m: _Model) -> dict[str, Any]:
    """表#7：信号/地网络连通分量（bbox 2D 投影近似，见 docstring 局限）。"""
    if not m.objects:
        return _row("net_connectivity", 7, SKIP, "清单未声明对象")
    sig = _net_components(m, NET_SIGNAL)
    gnd = _net_components(m, NET_GROUND)
    evidence: dict[str, Any] = {
        "approximation": "bbox 2D 投影接触图（跨层投影重叠即算连通=高估方向；"
                         "真接触图需活体几何 v2）",
        "signal_components": len(sig), "signal_members": sig,
        "ground_components": len(gnd), "ground_members": gnd,
    }
    expected_sig: int | None = m.connectivity.get(NET_SIGNAL)
    if expected_sig is None and m.device_topology == "series":
        expected_sig = 2  # 反馈 P13：串联器件（IDC/MIM 家族）信号网恰 2 分量
    if expected_sig is None and m.device_topology == "shunt":
        expected_sig = 1
    if expected_sig is None:
        return _row(
            "net_connectivity", 7, SKIP,
            f"未声明期望分量数（connectivity.signal 或 device_topology）——"
            f"如实报告观测：信号 {len(sig)} 分量、地 {len(gnd)} 分量",
            evidence=evidence)
    items: list[dict[str, Any]] = [{
        "net": NET_SIGNAL,
        "status": PASS if len(sig) == expected_sig else FAIL,
        "detail": (f"信号网 {len(sig)} 分量（期望 {expected_sig}）："
                   + " / ".join("+".join(g) for g in sig)
                   + ("——分量数不符=railA/railB 意外短接"
                      "（S21≈0 dB、串联电阻为负）或信号路径断裂"
                      if len(sig) != expected_sig else " ✓")),
    }]
    expected_gnd = m.connectivity.get(NET_GROUND, 1)
    if gnd:
        items.append({
            "net": NET_GROUND,
            "status": PASS if len(gnd) == expected_gnd else WARN,
            "detail": (f"地网 {len(gnd)} 分量（期望 {expected_gnd}）："
                       + " / ".join("+".join(g) for g in gnd)
                       + ("——地网分裂（盖板/地环不连通风险；经植球/过孔"
                          "连通属正常形态，bbox 近似下如实提示不硬判）"
                          if len(gnd) != expected_gnd else " ✓")),
        })
    status = _worst([i["status"] for i in items])
    return _row("net_connectivity", 7, status,
                f"信号 {len(sig)}/{expected_sig}、地 {len(gnd)}/{expected_gnd}",
                items=items, evidence=evidence)


def _check_net_overlap(m: _Model) -> dict[str, Any]:
    """表#8：异 net 金属 3D bbox 交叠体积=0（贴面 WARN，见 docstring 局限）。"""
    metals = m.metals
    if len(metals) < 2:
        return _row("net_overlap", 8, SKIP, "清单金属对象不足 2 个，无跨 net 对可判")
    pairs_fail: list[str] = []
    pairs_warn: list[str] = []
    vol_tol = m.volume_tol
    tol = m.contact_tol
    for i in range(len(metals)):
        for j in range(i + 1, len(metals)):
            a, b = metals[i], metals[j]
            if a["net"] == b["net"]:
                continue  # 同 net 交叠（unite 前形态/P9 体互穿）=表#9 v2 面
            vol = _bbox_volume_overlap(a["box"], b["box"])
            if vol > vol_tol:
                pairs_fail.append(
                    f"{a['name']}({a['net']}) × {b['name']}({b['net']})"
                    f" 交叠体积 {vol:g}")
            elif _boxes_touch(a["box"], b["box"], tol=tol):
                pairs_warn.append(f"{a['name']}({a['net']}) × {b['name']}({b['net']})")
    n_cross = sum(
        1 for i in range(len(metals)) for j in range(i + 1, len(metals))
        if metals[i]["net"] != metals[j]["net"])
    if not n_cross:
        return _row("net_overlap", 8, PASS, "无跨 net 金属对（平凡真）")
    if pairs_fail:
        return _row(
            "net_overlap", 8, FAIL,
            "异 net 金属交叠：" + "；".join(pairs_fail)
            + "——实测病灶：植球把信号短到地（S21≈−99.6 dB，修复后 −14.9 dB）、"
              "pad 与偶指共面接触（S21≈0 dB）；每个金属体必须属于一个 net，"
              "不同 net 交叠体积=0", evidence={"pairs": pairs_fail})
    if pairs_warn:
        return _row(
            "net_overlap", 8, WARN,
            "异 net 金属 bbox 贴面（净距≈0）：" + "；".join(pairs_warn)
            + "——bbox 近似下可能是真短路（异 net 金属面接触即短路），"
              "真体布尔核查=v2", evidence={"pairs": pairs_warn})
    return _row("net_overlap", 8, PASS,
                f"{n_cross} 个跨 net 金属对零交叠 ✓（bbox 近似）")


def _check_thin_layer(m: _Model) -> dict[str, Any]:
    """表#11：薄层 z 厚度==声明 h（对象 thickness_z + 叠层 thickness/z_range）。"""
    targets: list[dict[str, str | float]] = []
    for o in m.objects:
        if o["thickness_z"] is not None:
            targets.append({
                "what": f"对象 {o['name']}", "declared": o["thickness_z"],
                "span": o["box"][1][2] - o["box"][0][2]})
    for layer in m.stackup:
        if layer["thickness"] is not None and layer["z_range"] is not None:
            targets.append({
                "what": f"叠层 {layer['name']}", "declared": layer["thickness"],
                "span": layer["z_range"][1] - layer["z_range"][0]})
    if not targets:
        return _row(
            "thin_layer_thickness", 11, SKIP,
            "清单未声明任何薄层厚度（objects[].thickness_z 或 stackup[]"
            ".thickness+z_range）")
    bad: list[str] = []
    for t in targets:
        declared, span = float(t["declared"]), float(t["span"])  # type: ignore[arg-type]
        abs_tol = _THICKNESS_ABS_TOL.get(m.units, 1e-3)
        limit = max(_THICKNESS_REL_TOL * abs(declared), abs_tol)
        if abs(span - declared) > limit:
            bad.append(f"{t['what']}: 声明 h={declared:g} 但 z 跨度={span:g}")
    if bad:
        return _row(
            "thin_layer_thickness", 11, FAIL,
            "薄层厚度不符：" + "；".join(bad)
            + "——扫掠竖墙家族（0.2 μm SiNx 截面被建成 15 μm 高竖墙，SRF 从 "
              "6.3 崩到 0.95 GHz）；薄层 bbox z 厚必须==h，不符换向"
              "或报错", evidence={"tolerance": f"rel {_THICKNESS_REL_TOL:g} / "
                                 f"abs {abs_tol:g}（{m.units} 制）"})
    abs_tol_pass = _THICKNESS_ABS_TOL.get(m.units, 1e-3)
    return _row("thin_layer_thickness", 11, PASS,
                f"{len(targets)} 项薄层厚度逐一相符（rel "
                f"{_THICKNESS_REL_TOL:g}/abs {abs_tol_pass:g} {m.units} 制容差）")


def _check_keepout(m: _Model) -> dict[str, Any]:
    """表#12：keepout 矩形 vs 对象 xy 投影（侵入 FAIL/净距不足 WARN）。"""
    if not m.keepouts:
        return _row("keepout_clearance", 12, SKIP, "清单未声明 keepouts")
    tol = m.contact_tol
    fails: list[str] = []
    warns: list[str] = []
    unknown_refs: list[str] = []
    for ko in m.keepouts:
        rx0, ry0, rx1, ry1 = ko["rect"]
        if ko["applies_to"] is not None:
            by_name = {o["name"]: o for o in m.objects}
            scope = []
            for ref in ko["applies_to"]:
                if ref in by_name:
                    scope.append(by_name[ref])
                else:
                    unknown_refs.append(f"keepout {ko['name']} → {ref}")
        else:
            scope = list(m.objects)
        for o in scope:
            box = o["box"]
            if ko["z_range"] is not None and _overlap_1d(
                    box[0][2], box[1][2], ko["z_range"][0],
                    ko["z_range"][1]) <= tol:
                continue
            ox0, oy0 = box[0][0], box[0][1]
            ox1, oy1 = box[1][0], box[1][1]
            ov_x = _overlap_1d(ox0, ox1, rx0, rx1)
            ov_y = _overlap_1d(oy0, oy1, ry0, ry1)
            if ov_x > tol and ov_y > tol:
                fails.append(
                    f"对象 {o['name']}（net={o['net']}）侵入 keepout "
                    f"{ko['name']}（矩形 x[{rx0:g},{rx1:g}] y[{ry0:g},{ry1:g}]）")
                continue
            if ko["clearance"] is not None:
                dx = _gap_1d(ox0, ox1, rx0, rx1)
                dy = _gap_1d(oy0, oy1, ry0, ry1)
                dist = (dx * dx + dy * dy) ** 0.5
                if 0.0 < dist <= ko["clearance"] + tol:
                    warns.append(
                        f"对象 {o['name']} 距 keepout {ko['name']} 净距 "
                        f"{dist:g} ≤ 声明清距 {ko['clearance']:g}")
    status = FAIL if fails else (WARN if warns or unknown_refs else PASS)
    parts: list[str] = []
    if fails:
        parts.append("侵入：" + "；".join(fails)
                     + "——实测病灶：Ø80 植球压在 CPW 信号引线上，球顶把信号"
                       "经球短到盖板（S21≈−99.6 dB；按\"植球外接框 ∩ 信号引线"
                       "矩形\"剔除候选后恢复 −14.9 dB）")
    if warns:
        parts.append("净距告警：" + "；".join(warns))
    if unknown_refs:
        parts.append("清单引用了不存在的对象：" + "；".join(unknown_refs))
    if not parts:
        parts.append(f"{len(m.keepouts)} 个 keepout 全部清距 ✓")
    return _row("keepout_clearance", 12, status, "；".join(parts))


def _check_sparam_sanity(m: _Model, manifest_dir: Path | None) -> dict[str, Any]:
    """表#15：S 参数物理 sanity（passivity σmax/互易——edb_health_gate 单源）。"""
    if not m.sparams:
        return _row(
            "sparam_sanity", 15, SKIP,
            "清单未声明 sparams——S 参数物理 sanity 未评（可带求解产物路径"
            "复检；sign/SRF 类指标语义判定属 metric registry 后续扩展，本项"
            "检查 v1 收 passivity/互易两物理不变量）")
    raw = Path(m.sparams)
    path = raw if raw.is_absolute() or manifest_dir is None else manifest_dir / raw
    if not path.is_file():
        return _row("sparam_sanity", 15, FAIL,
                    f"sparams 文件不存在: {path}——清单声明了但文件缺席")
    # 判定口径单源复用 edb_health_gate（#376 边界余量家法/掩码纪律同源，
    # 别重写）：skrf 懒加载 + 形态校验 + 两物理不变量因子。
    from rfauto.service.edb_health_gate import (
        _load_touchstone_gate,
        _passivity_factor,
        _reciprocity_factor,
    )

    errors: list[str] = []
    state, _freq, s_matrix = _load_touchstone_gate(path, errors)
    if state == "env":
        return _row("sparam_sanity", 15, WARN,
                    f"skrf 不可用（环境类），S 参数在档但不可判读: {errors}")
    if state != "found":
        return _row(
            "sparam_sanity", 15, FAIL,
            f"Touchstone 解析失败/形状非法（证据损坏方向 #316）: {path}"
            + (f"——{errors}" if errors else ""))
    factors = [_passivity_factor(s_matrix), _reciprocity_factor(s_matrix)]
    details = [f"{f['factor']}: {f['status']}（{f['detail']}）" for f in factors]
    statuses = [f["status"] for f in factors]
    if "FAIL" in statuses:
        status = FAIL
    elif "UNKNOWN" in statuses:
        status = WARN  # 不可证实不冒充 FAIL/PASS（#122）
    else:
        status = PASS
    return _row("sparam_sanity", 15, status,
                "；".join(details) + "（判定规则沿用 edb_health_gate）",
                evidence={"path": str(path), "factors": factors})


def _check_result_freshness(m: _Model) -> dict[str, Any]:
    """表#16：结果新鲜度（run_dir → runs_verify_service.verify_run，K4 单源）。

    新鲜度是观测面不阻塞 doctor 主路径（模块 #105 惯例）：verify_run 的
    OSError 族（盘面/权限/竞态文件消失）包 try 降级为 SKIP 行如实登记，
    不让体检报告整个炸掉。
    """
    if not m.run_dir:
        return _row("result_freshness", 16, SKIP,
                    "清单未声明 run_dir——结果新鲜度未评（``runs verify`` "
                    "链路可直接复检）")
    from rfauto.service.runs_verify_service import resolve_run_dir, verify_run

    try:
        result = verify_run(resolve_run_dir(m.run_dir))
    except Exception as exc:  # 观测面故障（OSError 族宽）不阻断主路径（#105）
        return _row("result_freshness", 16, SKIP,
                    f"新鲜度校验面故障（非阻断）: {exc}——``runs verify`` "
                    "链路可直接复检",
                    evidence={"run_dir": m.run_dir})
    status_word = str(result.get("status", "error"))
    issues = result.get("issues") or []
    stale_kinds = ("stale_replaced", "missing", "sidecar_mismatch",
                   "manifest_corrupt")
    if status_word == "stale":
        bad = [i for i in issues if str(i.get("kind")) in stale_kinds]
        detail = ("run 产物新鲜度未通过：" + "；".join(
            f"{i.get('kind')}: {i.get('path')}（{i.get('detail', '')}）"
            for i in bad) + "——实测病例：13:05 的旧 Touchstone 冒充 19:29 新 "
            "run，交付过 L≈0.135 nH 错误结论")
        return _row("result_freshness", 16, FAIL, detail,
                    evidence={"run_dir": m.run_dir, "verify": result})
    if status_word == "error":
        return _row("result_freshness", 16, FAIL,
                    f"run 目录校验失败: {result.get('errors')}",
                    evidence={"run_dir": m.run_dir})
    if status_word == "legacy":
        return _row(
            "result_freshness", 16, WARN,
            "run 无 manifest.json（老 run/未接线链路）——新鲜度校验不可用，"
            "按 legacy 提示",
            evidence={"run_dir": m.run_dir})
    untracked = [i for i in issues if str(i.get("kind", "")).startswith("untracked")]
    detail = "run 产物新鲜度 fresh ✓"
    if untracked:
        detail += f"（含 {len(untracked)} 条未登记新增 Touchstone，信息级）"
    return _row("result_freshness", 16, PASS, detail,
                evidence={"run_dir": m.run_dir})


def _v2_row(check: str, table_ref: int, reason: str) -> dict[str, Any]:
    """v2 活体检查的 SKIP 行（如实标注 unsupported_v2 不硬凑，#122）。"""
    row = _row(check, table_ref, SKIP,
               f"{reason}——需要活体几何/面 ID（AEDT 工程面数据），清单数据"
               "不足以判定，v2（活体检查）登记")
    row["reason_tag"] = V2_TAG
    return row


#: v2 检查行（固定六条：表#1/#4/#9/#10/#13/#14）。
_V2_CHECKS: tuple[tuple[str, int, str], ...] = (
    ("port_face_position", 1,
     "face center vs region bbox 的活体面级定位（清单侧 on_boundary 自洽已由"
     "表#2 检查部分覆盖）"),
    ("aperture_ground_coverage", 4,
     "aperture 两端落在地金属上需 2D point-in-polygon（清单无多边形几何）"),
    ("body_intersection", 9,
     "体只共面不互穿需真体布尔交（bbox 交叠近似已由表#8 检查承担）"),
    ("material_reconciliation", 10,
     "混材料 unite 分层需活体材料/体积对账"),
    ("lid_window", 13, "盖板开窗 vs pad/探针几何不在清单 schema"),
    ("port_modes", 14, "端口模式数/Z0/积分线长度判定需求解后端口解"),
)


def run_em_doctor(
    manifest: dict[str, Any],
    *,
    manifest_dir: str | Path | None = None,
) -> dict[str, Any]:
    """清单 dict → 体检报告 dict（16 项逐项 + verdict；纯函数检查器主体）。

    Args:
        manifest: 模型清单（schema 见模块 docstring；未经 :func:
            `load_model_manifest` 校验的 dict 也可入参——归一化错误落
            manifest FAIL 行，不抛异常 #105）。
        manifest_dir: 清单所在目录（sparams 相对路径解析锚；CLI/加载器
            传入，直接调用可省）。

    Returns:
        ``{schema, verdict, ok, checks: [...16 行...], summary, manifest_path?}``
        ——任一 FAIL → verdict=FAIL/ok=False（CLI 退出码 1）；仅 WARN/SKIP
        → PASS；每行带 table_ref（反馈 §6.3 表编号）/catches（会抓到的
        真实问题原文）/detail/items/evidence。
    """
    norm_errors: list[str] = []
    model = _Model(manifest if isinstance(manifest, dict) else {}, norm_errors)
    base_dir = Path(manifest_dir) if manifest_dir is not None else None

    checks: list[dict[str, Any]] = []
    if norm_errors:
        checks.append({
            "check": "manifest", "table_ref": 0, "title": "清单自身",
            "status": FAIL, "catches": "清单条目畸形",
            "detail": "清单归一化失败（下列条目先修再体检）：" + "；".join(
                norm_errors[:20]),
        })
    for check in (
        _check_port_on_boundary,
        _check_aperture_covers_metal,
        _check_integration_line,
        _check_stackup_reaches_port,
        _check_net_connectivity,
        _check_net_overlap,
        _check_thin_layer,
        _check_keepout,
    ):
        checks.append(check(model))
    checks.append(_check_sparam_sanity(model, base_dir))
    checks.append(_check_result_freshness(model))
    for check_id, table_ref, reason in _V2_CHECKS:
        checks.append(_v2_row(check_id, table_ref, reason))
    # 报告行序=反馈表编号序（manifest 行置首，v2 行按编号归位；消费面稳定钉）
    checks.sort(key=lambda r: (r["table_ref"] != 0, r["table_ref"]))

    statuses = [str(c["status"]) for c in checks]
    verdict = FAIL if FAIL in statuses else PASS
    summary = {
        "n_pass": statuses.count(PASS),
        "n_fail": statuses.count(FAIL),
        "n_warn": statuses.count(WARN),
        "n_skip": statuses.count(SKIP),
        "n_skip_v2": sum(1 for c in checks if c.get("reason_tag") == V2_TAG),
    }
    # 域报告 ok 键构建后补赋（edb_health_gate 同款口径：ok=verdict==PASS，
    # 非门禁判据——CLI 按其决定退出码）。
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "verdict": verdict,
        "units": model.units,
        "checks": checks,
        "summary": summary,
    }
    if base_dir is not None:
        report["manifest_dir"] = str(base_dir)
    if norm_errors:
        report["errors"] = norm_errors
    report["ok"] = verdict == PASS
    return report


def doctor_from_file(path: str | Path) -> dict[str, Any]:
    """CLI 入口：清单文件 → 体检报告（load + run 组合）。"""
    loaded = load_model_manifest(path)
    if not loaded.get("ok"):
        return loaded  # error 信封（CLI 退出码 1）
    return run_em_doctor(
        loaded["manifest"], manifest_dir=Path(loaded["path"]).parent)
