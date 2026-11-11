"""layered_stack 模板族 spec + 几何布局单源（T-Q26d 批 1，aurora_q 席位 Q-X4）。

来源：晶圆键合空腔传输线外部用户实测反馈
（D:/晶圆键合/rfauto_反馈与实测经验.md §3.4 P1 模板族提案 + §2.1 实测锚 +
§2.2/§2.3 建模约定，用户令 2026-11-06 吸收立项）。族语义=**晶圆键合 /
SIW / SICL / 空气腔悬置线**这类「多层叠层 + 挖腔 + 腔壁金属化 + 波端口
落腔体截面」结构——75 模板覆盖平面线/器件（批 2 注册后 76），本族补三维
叠层缺口。

落位判定（任务书 T-Q26d"或 adapters 面按仓内模板惯例判定"）：本模块落
**adapters 面**而非 models/layered_stack/——.importlinter layers 契约
（models 在 adapters 之上，adapters 禁 import models），而 openEMS 渲染器
（oe_templates）与 HFSS 渲染器（hfss_builder_layered）都在 adapters 层，
schema+layout 必须与两引擎同层才能单源（suspended_stripline 先例：模板
族 schema/渲染全落 adapters 面）。批 2 若升格正式注册再议 models 门面。

三件套（本模块=声明与布局单一事实源，两引擎渲染器纯消费）：
- :class:`LayeredStackSpec`——Pydantic 严格契约（extra="forbid"），字段
  缺省值=反馈 §3.4 示例值 + §2.1 实测锚（出处见各 Field description）；
- :func:`layered_stack_layout`——纯函数几何布局（mm，分层围合：每层按腔
  足迹分段，零布尔运算），HFSS plan / openEMS 脚本 / lint 投影三方消费；
- :func:`layered_stack_lint_projection`——geometry_lint 声明式投影
  （service.geometry_lint_service.LintGeometry 兼容 dict；adapters 禁
  import service，故产出 plain dict，由调用方/测试喂 lint_geometry）。

§2.2 真空约定（建模铁律，两引擎同口径）：真空=普通 Box **完全包住**全部
固体（不布尔差、直接重叠）——HFSS validate 对"完全包住"不报错可正常求
解；对"部分相交"（实体穿出真空盒边界）报
``Parts Vacuum and W2_Membrane intersect.`` 求解失败（反馈 §2.2 两情形
实测）。挖腔=**分层围合**（非导体层按腔足迹分段，导体层完整横跨）——
最小实现：不依赖 HFSS 布尔减，纯分段坐标可离线审计，openEMS 侧
CSXCAD 按优先级原语天然免布尔。

坐标约定：z=0 在**导体层顶面**（=strip 所在平面，"带面"）；腔体 z0 为
腔底 z（可为负=带面之下）。v1 族约束（渲染守卫显式拒绝，不静默兜底）：
- 腔体沿传播轴（x）贯通全长（端口落腔体两端截面=模型端面，§2.1 实测
  形态"两端波端口覆盖整个腔截面"）；
- 腔 z 区间完整包含导体层（膜悬置于腔内，键合族定义性质），部分重叠
  拒绝（部分挖膜非本族形态）；
- 腔 z 中心=带面（StripLinePort 对称探针口径：openEMS v0.37
  StripLinePort 电压探针上下对称 ±height，不对称腔无有效 height）；
- 腔宽 > strip 宽（带须悬置于腔内）；
- conductor.layer 指向介质层（v1 strip=介质层顶面零厚 PEC 片；金属层
  作为走线层留批 2）；
- 端口截面=腔体截面（size 缺省自动=腔 w×h；显式给出必须逐位一致——
  §2.3 断言 3 的截面材料分布一致性在建模期即锁死）。

geometry_lint 期望面（批 1 验收核心口径）：名义 spec 六检查 **零 ERROR**
（lint_pass=True）；**恰 2 条 WARN**（port_cross_section_connectivity ×
每端口 1 条，连通域=2）——膜横跨腔截面把端口空气区分为上下两腔是本族
**固有物理形态**（§2.1 实测 |S11|max=-23.5dB 单模传输线正常工作的同款
结构），非建模缺陷；WARN 不拦截，如实保留不豁免（不声明 multimode——
该端口非多模）。

名义默认值出处（铁律 7：零拍脑袋）：
- layers 0.25/0.003/0.05/0.003/0.25、cavity w=0.9 h=0.5 z0=-0.25、
  conductor layer=2 width=0.52、cavity_metalization=0.003
  =反馈 §3.4 spec 示例值（2026-11-06）；
- line_len=5.1mm =§2.1 实测模型"空气腔 0.9×0.5×5.1mm"；
- wafer_width=1.2mm =§5 复现片段 W2_Membrane 宽 1.2mm；
- 频带 85-105GHz =§5 复现片段 create_linear_count_sweep("Setup1","GHz",
  85,105,21) 实测扫频；
- silicon εr=11.9 =§2.1 实测锚（HFSS 内建 "silicon" 材料库同名同值）；
- vacuum_margin=1.0mm =建模余量声明值（非物理设计值，§2.2 完全包住
  形态的最小裕量惯例）。

本模块不带 ``__all__``：按 public_api 快照口径记私有
（tests/gold/public_api.json 零漂移，geometry_lint_service 同款）。
"""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ── 材料表（族内单一事实源；铁律 7：每条带出处）───────────────────────────


class MaterialProps(BaseModel):
    """一个声明材料的物理属性（本族 MATERIALS 表条目）。

    is_metal=True 的材料渲染为金属：HFSS=实体盒（材质名进 HFSS 材料库，
    保声明厚度）+strip/腔壁金属化=零厚 PEC 片；openEMS=零厚 PEC sheet
    （次胞体积金属盒在 FDTD 网格中心采样下可能整层丢失，sheet 落格
    确定性——3µm 金层 RF 等效 PEC）。
    """

    model_config = ConfigDict(extra="forbid")

    er: float = Field(default=1.0, ge=1.0, description="相对介电常数（金属忽略）")
    tan_d: float = Field(default=0.0, ge=0.0, description="损耗角正切（v1 声明值）")
    is_metal: bool = Field(default=False, description="金属判定（渲染形态分派）")
    hfss_material: str = Field(default="", description="HFSS 材料库名（空=pec）")


#: 族内材料表（键=spec layers 材料名；未知材料 ValidationError 列出可用表）
MATERIALS: dict[str, MaterialProps] = {
    "silicon": MaterialProps(
        er=11.9, tan_d=0.0, is_metal=False, hfss_material="silicon"),
    "gold": MaterialProps(
        er=1.0, tan_d=0.0, is_metal=True, hfss_material="gold"),
}

#: silicon εr 出处注记（进 plan/meta 证据链）
MATERIAL_SOURCES: dict[str, str] = {
    "silicon": "εr=11.9：反馈 §2.1 实测锚（_suspended_stripline_ri(w=0.52,"
               " b=0.50, h=0.05, εr=11.9)→εeff=1.59/Z0≈50.2 的实测口径；"
               "HFSS 内建 silicon 材料库同名同值）；tan_d=0 缺省声明"
               "（键合高阻硅衬底损耗留真机批实测）",
    "gold": "晶圆键合 Au 键合层（反馈 §3.4 示例 0.003mm）；3µm 键合金层 "
            "RF 等效 PEC（HFSS=实体 gold 保厚度，openEMS=零厚 PEC sheet）",
}

# ── 名义频带（§2.1/§5 实测锚）────────────────────────────────────────────

#: 缺省频带（GHz）：反馈 §5 复现片段 create_linear_count_sweep(
#: "Setup1", "GHz", 85, 105, 21)——外部用户实测模型的扫频
FREQ_RANGE_GHZ_DEFAULT: tuple[float, float] = (85.0, 105.0)

#: 建模余量（mm，非物理设计值）：真空盒 y/z 方向对叠层的完全包住裕量
VACUUM_MARGIN_MM = 1.0
#: openEMS 横向（y/z）MUR 域余量（×BASE；腔体金属化壁封闭，泄漏≈0，
#: 取 PML_8 厚度同量级作数值裕量）
OE_TRANSVERSE_MARGIN_BASE = 8.0
#: openEMS 传播轴（x）端口馈段长（×BASE；端口面出 PML_8=16·BASE 惯例，
#: #253 激励盒内缩 10·NEAR=2.5·BASE ≥2·BASE 过守卫）
OE_FEED_BASE = 16.0
#: 显式近场网格线最小间距地板（#349，siw/sicl 同值）
MESH_FLOOR_MM = 10e-3   # mm（=10µm）
#: 次胞金属面/介质界面不显式入网的判定（与 MESH_FLOOR_MM 同源口径）：
#: 两界面间距 < MESH_FLOOR_MM 时只保留"结构必需面"（腔壁/膜面/带面）

# ── spec schema（Pydantic 严格契约）──────────────────────────────────────


class CavitySpec(BaseModel):
    """矩形腔（沿传播轴贯通全长）。

    坐标：z=0=导体层顶面（带面）；z0=腔底 z（可为负）。x_center_mm/
    y_center_mm 为声明位置（v1 腔体贯通全长且 y 居中按 wafer 几何自洽，
    非零值渲染守卫拒绝——贯通全长的腔管无 x 位置自由度）。缺省=
    反馈 §3.4 示例值（w=0.9/h=0.5/z0=-0.25 关于带面对称）。
    """

    model_config = ConfigDict(extra="forbid")

    shape: Literal["rect"] = "rect"
    x_center_mm: float = Field(default=0.0, description="腔体沿传播轴中心（"
                               "v1 贯通全长，必须 0）")
    y_center_mm: float = Field(default=0.0, description="腔体横向中心 mm")
    w_mm: float = Field(default=0.9, gt=0.0,
                        description="腔体横向（y）宽度 mm（§3.4 示例 0.9）")
    h_mm: float = Field(default=0.5, gt=0.0,
                        description="腔体 z 向高度 mm（§3.4 示例 0.5）")
    z0_mm: float = Field(default=-0.25, description="腔底 z mm（带面系；"
                         "§3.4 示例 -0.25=关于带面对称）")


class ConductorSpec(BaseModel):
    """载线层声明（v1：介质层顶面零厚 strip 片）。缺省=§3.4 示例值。"""

    model_config = ConfigDict(extra="forbid")

    layer: int = Field(default=2, ge=0,
                       description="载线层序号（layers 0 基索引；§3.4 示例 2）")
    width_mm: float = Field(default=0.52, gt=0.0,
                            description="strip 宽 mm（§3.4 示例 0.52）")
    pattern: Literal["strip"] = "strip"


class StackPortSpec(BaseModel):
    """截面波端口声明（v1：kind=wave / plane=YZ 双端口）。

    size_mm 缺省 None=自动取腔体截面 (w, h)（§2.1 实测形态"波端口覆盖
    整个腔截面"）；显式给出必须与腔体截面逐位一致（§2.3 断言 3 截面
    一致性建模期锁死）。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["wave"] = "wave"
    plane: Literal["YZ"] = "YZ"
    size_mm: tuple[float, float] | None = Field(
        default=None, description="端口截面 (y 尺寸, z 尺寸) mm；None=自动=腔体截面")


class LayeredStackSpec(BaseModel):
    """layered_stack 模板族声明式 spec（批 1 严格契约）。

    缺省=反馈 §3.4 示例值 + §2.1/§5 实测锚（见各 Field description 与
    模块 docstring 出处表）。跨字段几何一致性在 model_validator 内
    fail-loud（渲染前建模期拒绝，K7 哲学：报错而不是解出假结果）。
    """

    model_config = ConfigDict(extra="forbid")

    layers: list[tuple[str, float]] = Field(
        default=[("silicon", 0.25), ("gold", 0.003), ("silicon", 0.05),
                 ("gold", 0.003), ("silicon", 0.25)],
        description="叠层 [(材料名, 厚度 mm)] 从下到上（缺省=§3.4 示例："
        "silicon/gold/silicon/gold/silicon = 0.25/0.003/0.05/0.003/0.25）",
        min_length=1)
    cavity: CavitySpec = Field(
        default_factory=CavitySpec, description="挖腔声明（v1 矩形腔贯通全长；"
        "缺省=§3.4 示例值）")
    conductor: ConductorSpec = Field(
        default_factory=ConductorSpec, description="载线层声明（缺省=§3.4 "
        "示例值）")
    ports: StackPortSpec = Field(
        default_factory=StackPortSpec, description="截面波端口声明（缺省 "
        "wave/YZ，size 自动=腔体截面）")
    cavity_metalization_mm: float = Field(
        default=0.003, ge=0.0,
        description="腔壁金属化名义厚 mm（§3.4 示例 0.003；>0=四壁金属化"
        "（两端截面口不金属化——端口须见腔截面）；渲染形态=零厚 PEC 壁面"
        "片（3µm 涂层 RF 等效，两引擎同口径），0=不金属化")
    line_len_mm: float = Field(
        default=5.1, gt=0.0,
        description="腔管/线长（传播轴全长）mm（§2.1 实测锚 5.1）")
    wafer_width_mm: float = Field(
        default=1.2, gt=0.0,
        description="叠层横向（y）总宽 mm（§5 实测 W2_Membrane 宽 1.2）")
    vacuum_margin_mm: float = Field(
        default=VACUUM_MARGIN_MM, gt=0.0,
        description="真空盒对叠层的完全包住裕量 mm（§2.2 约定，建模余量）")

    @model_validator(mode="after")
    def _validate_geometry(self) -> LayeredStackSpec:
        # 材料表封闭性（未知材料显式列出可用表——strict contract）
        for idx, (mat, thick) in enumerate(self.layers):
            if mat not in MATERIALS:
                raise ValueError(
                    f"layers[{idx}] 未知材料 {mat!r}（可用: "
                    f"{sorted(MATERIALS)}；MATERIALS 表见模块 docstring 出处）")
            if not (math.isfinite(thick) and thick > 0.0):
                raise ValueError(
                    f"layers[{idx}] 厚度必须为正有限，得到 {thick!r}")
        n = len(self.layers)
        ci = self.conductor.layer
        if ci >= n:
            raise ValueError(
                f"conductor.layer={ci} 越界（layers 共 {n} 层，0 基索引）")
        if MATERIALS[self.layers[ci][0]].is_metal:
            raise ValueError(
                f"conductor.layer={ci} 指向金属层 {self.layers[ci][0]!r}"
                "（v1 strip=介质层顶面零厚 PEC 片；金属层作走线层留批 2）")
        # 叠层 z 账（带面系：z=0=导体层顶面）
        z_ranges = stack_z_ranges_mm(self)
        cond_lo, cond_hi = z_ranges[ci]
        cav = self.cavity
        if cav.x_center_mm != 0.0:
            raise ValueError(
                f"cavity.x_center_mm={cav.x_center_mm!r} 必须为 0"
                "（v1 腔体沿传播轴贯通全长，无 x 位置自由度）")
        z_lo, z_hi = cav.z0_mm, cav.z0_mm + cav.h_mm
        stack_lo, stack_hi = z_ranges[0][0], z_ranges[-1][1]
        if z_lo < stack_lo - 1e-12 or z_hi > stack_hi + 1e-12:
            raise ValueError(
                f"腔体 z 区间 [{z_lo!r}, {z_hi!r}] 越出叠层 z 范围 "
                f"[{stack_lo!r}, {stack_hi!r}]（腔必须封闭于叠层内）")
        # 腔完整包含导体层（膜悬置=键合族定义性质；部分重叠拒绝）
        if not (z_lo <= cond_lo + 1e-12 and cond_hi <= z_hi + 1e-12):
            partial = (z_lo < cond_hi - 1e-12 and cond_lo < z_hi - 1e-12)
            if partial:
                raise ValueError(
                    f"腔体 z 区间 [{z_lo!r}, {z_hi!r}] 与导体层 [{cond_lo!r}, "
                    f"{cond_hi!r}] 部分重叠（部分挖膜非本族形态）——腔须完整"
                    "包含导体层（膜悬置）或不相交")
            raise ValueError(
                f"腔体 z 区间 [{z_lo!r}, {z_hi!r}] 未包含导体层 [{cond_lo!r}, "
                f"{cond_hi!r}]——strip 必须穿越腔体衔接两端截面端口（膜悬置）")
        # StripLinePort 对称探针口径：腔 z 中心=带面
        cav_center = z_lo + cav.h_mm / 2.0
        if abs(cav_center - cond_hi) > 1e-9:
            raise ValueError(
                f"腔 z 中心 {cav_center!r} ≠ 带面 {cond_hi!r}（|Δ|>1e-9mm）——"
                "openEMS StripLinePort 电压探针上下对称（±height），腔须关于"
                "带面对称（不对称腔留批 2 LumpedPort 口径）")
        # 腔宽 > strip 宽（带悬置于腔内）
        if not cav.w_mm > self.conductor.width_mm:
            raise ValueError(
                f"腔宽 w={cav.w_mm!r} ≤ strip 宽 {self.conductor.width_mm!r}"
                "——strip 必须悬置于腔内（腔宽>带宽）")
        # 腔宽 < 晶圆宽（腔足印须落在叠层内，两侧留键合环）
        if not self.wafer_width_mm > cav.w_mm:
            raise ValueError(
                f"wafer_width_mm={self.wafer_width_mm!r} ≤ 腔宽 "
                f"{cav.w_mm!r}——腔足印两侧须留键合环（wafer 宽>腔宽）")
        # 端口截面=腔体截面（§2.3 断言 3 建模期锁死）
        auto_size = (cav.w_mm, cav.h_mm)
        size = self.ports.size_mm if self.ports.size_mm is not None else auto_size
        if abs(size[0] - auto_size[0]) > 1e-9 or abs(size[1] - auto_size[1]) > 1e-9:
            raise ValueError(
                f"ports.size_mm={size!r} ≠ 腔体截面 {auto_size!r}——波端口须"
                "覆盖整个腔截面（§2.1 实测形态；截面材料分布一致性=§2.3 断言 3）")
        return self

    # ── 派生账（单源，渲染器与测试共用）────────────────────────────────

    def conductor_index(self) -> int:
        return int(self.conductor.layer)

    def z_ranges_mm(self) -> list[tuple[float, float]]:
        """各层 z 区间（带面系，z=0=导体层顶面）。"""
        return stack_z_ranges_mm(self)


def stack_z_ranges_mm(spec: LayeredStackSpec) -> list[tuple[float, float]]:
    """叠层 z 账单源：带面系（z=0=导体层顶面），从叠层底向上累计。

    底部原点累计再整体平移 Δ=导体层顶面（底部原点系），使带面=0。
    """
    ci = spec.conductor_index()
    cum = 0.0
    ranges_bottom_origin: list[tuple[float, float]] = []
    cond_top_bottom_origin = 0.0
    for idx, (_mat, thick) in enumerate(spec.layers):
        ranges_bottom_origin.append((cum, cum + thick))
        cum += thick
        if idx == ci:
            cond_top_bottom_origin = cum
    shift = cond_top_bottom_origin
    return [(lo - shift, hi - shift) for lo, hi in ranges_bottom_origin]


# ── 几何布局单源（mm；分层围合，零布尔）──────────────────────────────────


def _box(x0: float, x1: float, y0: float, y1: float,
         z0: float, z1: float) -> tuple[float, float, float, float, float, float]:
    return (x0, x1, y0, y1, z0, z1)


def layered_stack_layout(spec: LayeredStackSpec) -> dict[str, Any]:
    """几何布局单源（mm；HFSS plan / openEMS 脚本 / lint 投影三方消费）。

    分层围合（§2.2 真空约定下的最小实现）：每非导体层按腔足印分段
    （y 侧段全高 + 腔足印内保腔外 z 段），导体层完整横跨，零布尔运算。
    产出一手坐标（传播轴=x，横向=y，叠层=z，带面 z=0）：

    - ``stack_solids``：介质/金属层的固体分段盒（含腔足印围合分段）；
    - ``metal_sheets``：零厚金属片（键合金属层折算 sheet + 腔壁金属化
      + strip）——openEMS 直接消费；HFSS 侧金属层用实体盒（保厚度），
      见 :func:`hfss_plan`（hfss_builder_layered）再加工；
    - ``vacuum_box``：§2.2 完全包住盒（x=±line_len/2 与叠层共端面，
      y/z 加 margin——端口面=模型端面=lint ①前提）；
    - ``ports``：双波端口（截面=腔体截面、积分线数值坐标=带面→腔顶壁）；
    - ``feature_lines``：x/y/z 显式网格特征线集（#349 地板守卫后）。
    """
    ci = spec.conductor_index()
    zr = stack_z_ranges_mm(spec)
    cav = spec.cavity
    l_half = spec.line_len_mm / 2.0
    cy = cav.y_center_mm
    cy0, cy1 = cy - cav.w_mm / 2.0, cy + cav.w_mm / 2.0
    cz_lo, cz_hi = cav.z0_mm, cav.z0_mm + cav.h_mm
    cond_lo, cond_hi = zr[ci]
    strip_w = spec.conductor.width_mm
    strip = _box(-l_half, l_half, cy - strip_w / 2.0, cy + strip_w / 2.0,
                 cond_hi, cond_hi)

    # ── 叠层固体分段（分层围合）─────────────────────────────────────────
    solids: list[dict[str, Any]] = []
    seg_seq: dict[tuple[int, str], int] = {}

    def _solid(idx: int, mat: str, box: tuple[float, ...]) -> None:
        key = (idx, mat)
        seq = seg_seq.get(key, 0)
        seg_seq[key] = seq + 1
        suffix = f"_{seq}" if seq else ""
        solids.append({"name": f"layer{idx}_{mat}{suffix}", "layer": idx,
                       "material": mat,
                       "is_metal": MATERIALS[mat].is_metal, "box": box})

    for idx, (mat, _thick) in enumerate(spec.layers):
        lo, hi = zr[idx]
        if idx == ci:
            # 导体层（膜）完整横跨：不挖
            _solid(idx, mat, _box(-l_half, l_half, -spec.wafer_width_mm / 2.0,
                                  spec.wafer_width_mm / 2.0, lo, hi))
            continue
        wy = spec.wafer_width_mm / 2.0
        # y 侧段（腔足印外）：全高
        if cy0 > -wy + 1e-12:
            _solid(idx, mat, _box(-l_half, l_half, -wy, cy0, lo, hi))
        if wy > cy1 + 1e-12:
            _solid(idx, mat, _box(-l_half, l_half, cy1, wy, lo, hi))
        # 腔足印内：保腔外 z 段（层 z 区间与腔 z 区间的非重叠部分）
        if lo < cz_lo - 1e-12:
            _solid(idx, mat, _box(-l_half, l_half, cy0, cy1, lo, cz_lo))
        if hi > cz_hi + 1e-12:
            _solid(idx, mat, _box(-l_half, l_half, cy0, cy1, cz_hi, hi))
        # 腔足印内与腔 z 重叠段=挖除（不产生盒）

    # ── 腔壁金属化（零厚 PEC 片；两端截面口不金属化——端口须见腔截面）──
    walls: list[dict[str, Any]] = []
    t = spec.cavity_metalization_mm
    if t > 0.0:
        walls.append({"name": "cavity_wall_top",
                      "box": _box(-l_half, l_half, cy0, cy1, cz_hi, cz_hi)})
        walls.append({"name": "cavity_wall_bottom",
                      "box": _box(-l_half, l_half, cy0, cy1, cz_lo, cz_lo)})
        # 上腔侧壁（带面→腔顶）：带面上方有腔才存在
        if cz_hi > cond_hi + 1e-12:
            walls.append({"name": "cavity_wall_side_upper_p",
                          "box": _box(-l_half, l_half, cy1, cy1, cond_hi, cz_hi)})
            walls.append({"name": "cavity_wall_side_upper_n",
                          "box": _box(-l_half, l_half, cy0, cy0, cond_hi, cz_hi)})
        # 下腔侧壁（腔底→膜底）
        if cz_lo < cond_lo - 1e-12:
            walls.append({"name": "cavity_wall_side_lower_p",
                          "box": _box(-l_half, l_half, cy1, cy1, cz_lo, cond_lo)})
            walls.append({"name": "cavity_wall_side_lower_n",
                          "box": _box(-l_half, l_half, cy0, cy0, cz_lo, cond_lo)})

    # ── 真空盒（§2.2 完全包住；x 与叠层共端面=端口面=模型端面）──────────
    vac_margin = spec.vacuum_margin_mm
    vacuum = _box(-l_half, l_half,
                  -spec.wafer_width_mm / 2.0 - vac_margin,
                  spec.wafer_width_mm / 2.0 + vac_margin,
                  zr[0][0] - vac_margin, zr[-1][1] + vac_margin)

    # ── 双波端口（截面=腔体截面；积分线=带面→腔顶壁，数值坐标）─────────
    ports: list[dict[str, Any]] = []
    for name, pos in (("Port1", -l_half), ("Port2", l_half)):
        ports.append({
            "name": name, "pos_mm": pos,
            "u_mm": (cy0, cy1), "v_mm": (cz_lo, cz_hi),
            # T-Q26a 口径：积分线=纯数值坐标（model_units mm）；起点=带面
            # （信号导体），终点=腔顶壁（参考导体）——strip→wall 电压口径
            "integration_line_mm": [[pos, cy, cond_hi], [pos, cy, cz_hi]],
        })

    # ── 显式网格特征线（x/y/z；#349 地板守卫在渲染端按轴复检）───────────
    wy = spec.wafer_width_mm / 2.0
    feat_x = sorted({-l_half, l_half})
    feat_y = sorted({cy, cy - strip_w / 2.0, cy + strip_w / 2.0,
                     cy0, cy1, -wy, wy})
    feat_z = sorted({zr[0][0], cz_lo, cond_lo, cond_hi, cz_hi,
                     zr[-1][1]})
    # 次胞界面剔除：与已保留特征线间距 < MESH_FLOOR_MM 的非必需面不入网
    # （3µm 键合层界面/叠层顶与腔顶壁 3µm 近撞——#349 CFL 塌缩守卫；
    # 介质界面体积采样不依赖网格线）。导体层顶/底=带面/膜面=必需面保留。
    feat_z = _drop_subcell_duplicates(feat_z, keep={cond_lo, cond_hi,
                                                    cz_lo, cz_hi})
    feat_x = _drop_subcell_duplicates(feat_x, keep={-l_half, l_half})
    feat_y = _drop_subcell_duplicates(feat_y, keep={cy0, cy1, cy,
                                                    cy - strip_w / 2.0,
                                                    cy + strip_w / 2.0})
    return {
        "spec": spec,
        "z_ranges_mm": zr,
        "line_len_mm": spec.line_len_mm,
        "l_half_mm": l_half,
        "strip": strip,
        "strip_z_mm": cond_hi,
        "stack_solids": solids,
        "metal_sheets": walls,
        "vacuum_box_mm": vacuum,
        "ports": ports,
        "feature_lines_mm": {"x": feat_x, "y": feat_y, "z": feat_z},
        "cavity_mm": {"y0": cy0, "y1": cy1, "z0": cz_lo, "z1": cz_hi,
                      "y_center": cy},
        "materials": {k: v.model_dump() for k, v in MATERIALS.items()},
        "material_sources": dict(MATERIAL_SOURCES),
        "freq_range_ghz_default": FREQ_RANGE_GHZ_DEFAULT,
        "cavity_metalization_mm": spec.cavity_metalization_mm,
    }


def _drop_subcell_duplicates(lines: list[float], *,
                             keep: set[float]) -> list[float]:
    """剔除与必需面间距 < MESH_FLOOR_MM 的次胞界面（保留 keep 集全量）。

    #349 口径：显式网格线最小间距 ≥10µm；近撞面中非结构必需者剔除
    （介质界面体积采样不依赖网格线），必需面（金属面/端口面/膜面）全保。
    """
    out: list[float] = []
    for v in lines:
        if v in keep:
            out.append(v)
            continue
        if all(abs(v - k) >= MESH_FLOOR_MM for k in out):
            out.append(v)
    return sorted(out)


# ── geometry_lint 声明式投影（LintGeometry 兼容 dict；禁 import service）─


def layered_stack_lint_projection(layout: dict[str, Any]) -> dict[str, Any]:
    """layout → service.geometry_lint_service.LintGeometry 兼容 dict。

    adapters 禁 import service（.importlinter layers 契约），故产出
    plain dict（model_units="mm"），由调用方/测试喂
    ``lint_geometry``（service JSON 进出：dict 即可校验形态）。

    投影面=HFSS 真实模型（叠层围合分段 + 真空盒 + strip/壁零厚片 + 双
    波端口；变量表空=全数值 plan，T-Q26a 口径零表达式零裸数暴露）。
    """
    boxes: list[dict[str, Any]] = []
    x0, x1, y0v, y1v, z0v, z1v = layout["vacuum_box_mm"]
    boxes.append({"name": "VacuumBox", "material": "vacuum", "solve_inside": True,
                  "coords": (x0, y0v, z0v, x1, y1v, z1v)})
    for seg in layout["stack_solids"]:
        bx0, bx1, by0, by1, bz0, bz1 = seg["box"]
        boxes.append({
            "name": str(seg["name"]),
            "material": seg["material"],
            "solve_inside": not seg["is_metal"],
            "coords": (bx0, by0, bz0, bx1, by1, bz1),
        })
    for sheet in layout["metal_sheets"]:
        bx0, bx1, by0, by1, bz0, bz1 = sheet["box"]
        boxes.append({"name": sheet["name"], "material": "pec",
                      "solve_inside": False,
                      "coords": (bx0, by0, bz0, bx1, by1, bz1),
                      "is_metal": True})
    sx0, sx1, sy0, sy1, sz0, sz1 = layout["strip"]
    boxes.append({"name": "strip", "material": "pec", "solve_inside": False,
                  "coords": (sx0, sy0, sz0, sx1, sy1, sz1), "is_metal": True})
    port_entries: list[dict[str, Any]] = []
    for pt in layout["ports"]:
        u0, u1 = pt["u_mm"]
        v0, v1 = pt["v_mm"]
        port_entries.append({
            "name": pt["name"], "kind": "wave",
            "sheet": {"axis": "x", "pos": pt["pos_mm"],
                      "u": (u0, u1), "v": (v0, v1)},
            "multimode": False,
        })
    return {"model_units": "mm", "boxes": boxes, "ports": port_entries,
            "variables": []}


# ── 名义设计点反解单源（批 2 Q-X6 注册链；铁律 7：确定性内核数值反解，
#    零手拍。批 1 缺省 strip 宽=反馈锚直取（0.52），批 2 名义账本改由本
#    函数反解给出（TEMPLATE_NOMINAL 归档字面量+测试回代钉，registry
#    "字面量落表"惯例同 suspended_stripline w=0.9058 口径））────────────────


#: Z0 反解独立裁判阈（Ω）：反解后正向复算 |Z0(w*)−目标| 上界（#118：
#: 裁判量=独立第三方面数值，非反解过程自身残差口径）
DESIGN_Z0_JUDGE_OHM = 1e-9
#: 反解二分宽度域（mm）：Z0(w) 在此域严格单调降（悬置闭式共形电容比
#: 单调性，w↑→r_b↑/r_h↑ 但 Z0∝K'/K 单调降——bracket 失败 fail-loud）
DESIGN_W_BOUNDS_MM = (0.02, 2.0)


def design_params(z0_target_ohm: float = 50.0) -> dict[str, Any]:
    """名义设计点反解单源（Z0 目标 → strip 宽，反解自洽链+独立裁判）。

    反解链（全部闭式数值，零手拍）：
    1. 腔高/膜厚/εr 取 spec 缺省（反馈 §3.4/§2.1 实测锚，与本模块
       :class:`LayeredStackSpec` 缺省同源）：b=cavity.h=0.50mm、
       h=导体层（膜）厚 0.05mm、εr=11.9（silicon）；
    2. strip 宽 w 在 :data:`DESIGN_W_BOUNDS_MM` 上对
       ``core.calculators._suspended_stripline_ri(w, b, h, εr)`` 的 Z0
       二分反解（200 步 → 宽度区间机器精度；Z0(w) 严格单调降，
       bracket 失败即 ValueError）；
    3. **独立裁判（#118 家法）**：反解终点正向复算
       ``|Z0(w*) − z0_target| ≤ DESIGN_Z0_JUDGE_OHM``（1e-9 Ω）——
       裁判量与反解残差同源不同面（正向复算），不满足即 fail-loud；
    4. 反馈 §2.1 实测锚对照记录（非手抄：锚点 Z0 由同一闭式现算）：
       HFSS 实测 w=0.52 → Z0≈50.2（|S11|max=−23.5dB 背书 50Ω 点），
       闭式现算值与其偏差进 ``anchor_hfss``（经验锚对照，非严格裁判）。

    Returns
    -------
    dict
        ``params``（TEMPLATE_NOMINAL 同键集几何五键：strip_w_mm/
        line_len_mm/wafer_width_mm/cavity_w_mm/cavity_h_mm，strip_w_mm
        为反解全精度值）+ ``z0_target_ohm``/``z0_achieved_ohm``/
        ``z0_residual_ohm``/``eps_eff`` + ``anchor_hfss`` 对照块 +
        ``source`` 溯源串。
    """
    from rfauto.core.calculators import _suspended_stripline_ri

    spec = LayeredStackSpec()
    b_mm = float(spec.cavity.h_mm)              # 腔高=两"地"间距口径
    h_mm = float(spec.layers[spec.conductor_index()][1])   # 膜厚
    er = float(MATERIALS[spec.layers[spec.conductor_index()][0]].er)

    def _z0(w_mm: float) -> float:
        return float(_suspended_stripline_ri(w_mm, b_mm, h_mm, er)[1])

    w_lo, w_hi = DESIGN_W_BOUNDS_MM
    z_lo, z_hi = _z0(w_lo), _z0(w_hi)
    if not (z_lo > z_hi):                      # 单调降前提（#118 前置校验）
        raise ValueError(
            f"design_params: Z0(w) 在 [{w_lo}, {w_hi}]mm 非单调降"
            f"（Z0({w_lo})={z_lo:.4f}, Z0({w_hi})={z_hi:.4f}）——闭式域假设失效")
    if not (z_hi <= z0_target_ohm <= z_lo):
        raise ValueError(
            f"design_params: 目标 {z0_target_ohm}Ω 超出可达域 "
            f"[{z_hi:.2f}, {z_lo:.2f}]Ω（w∈{DESIGN_W_BOUNDS_MM}mm，"
            f"b={b_mm} h={h_mm} εr={er}）")
    for _ in range(200):
        w_mid = 0.5 * (w_lo + w_hi)
        if _z0(w_mid) > z0_target_ohm:
            w_lo = w_mid
        else:
            w_hi = w_mid
    w_mm = 0.5 * (w_lo + w_hi)
    eps_eff, z0_achieved = _suspended_stripline_ri(w_mm, b_mm, h_mm, er)
    residual = abs(float(z0_achieved) - float(z0_target_ohm))
    if residual > DESIGN_Z0_JUDGE_OHM:
        raise ValueError(
            f"design_params: 反解自洽裁判失败 |Z0(w*)−{z0_target_ohm}|="
            f"{residual:.3e}Ω > {DESIGN_Z0_JUDGE_OHM:g}Ω（#118 独立裁判）")
    # 反馈 §2.1 实测锚对照（锚点 Z0 闭式现算，零手抄；经验锚非严格裁判）
    anchor_w = 0.52
    _, anchor_z0 = _suspended_stripline_ri(anchor_w, b_mm, h_mm, er)
    return {
        "params": {
            "strip_w_mm": float(w_mm),
            "line_len_mm": float(spec.line_len_mm),
            "wafer_width_mm": float(spec.wafer_width_mm),
            "cavity_w_mm": float(spec.cavity.w_mm),
            "cavity_h_mm": float(spec.cavity.h_mm),
        },
        "z0_target_ohm": float(z0_target_ohm),
        "z0_achieved_ohm": float(z0_achieved),
        "z0_residual_ohm": residual,
        "eps_eff": float(eps_eff),
        "anchor_hfss": {
            "w_mm": anchor_w,
            "z0_closed_form_ohm": float(anchor_z0),
            "hfss_measured_z0_ohm": 50.2,
            "source": "反馈 §2.1 实测锚（_suspended_stripline_ri 同参"
                      "调用→εeff≈1.59/Z0≈50.2；HFSS |S11|max=-23.5dB "
                      "背书 50Ω 点）——经验锚对照非严格裁判",
        },
        "source": f"core.calculators._suspended_stripline_ri 数值反解"
                  f"（二分 200 步，w∈{DESIGN_W_BOUNDS_MM}mm；"
                  f"独立裁判 |ΔZ0|≤{DESIGN_Z0_JUDGE_OHM:g}Ω）",
    }
