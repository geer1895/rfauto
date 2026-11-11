"""layered_stack 族的 HFSS 几何渲染（T-Q26d 批 1，aurora_q 席位 Q-X4）。

两件套：
- :func:`layered_stack_hfss_plan`——spec → HFSS 声明式中间形态 plan
  （纯函数、零 pyaedt 依赖、离线可审计）：固体盒（叠层分层围合分段 +
  §2.2 真空盒完全包住）+ 零厚 PEC 片（strip/腔壁金属化）+ 双波端口
  （截面=腔体截面，**积分线=数值坐标**——T-Q26a 坑①口径）+
  geometry_lint 投影（:func:`rfauto.adapters.layered_stack_spec.
  layered_stack_lint_projection` 透传）。plan 与 lint 投影盒名 1:1
  （可追溯）。
- :func:`build_layered_stack`——plan → pyaedt 会话执行（真机面；零
  pyaedt 模块级依赖，import 延迟到函数内）。波端口积分线在调用 pyaedt
  **之前**经 :func:`rfauto.adapters.hfss_session.validate_integration_line`
  前置校验（T-Q26a 校验器消费：表达式/变量名字符串 → ValueError 参数
  错误，绝不落到 "Failed to create boundary Wave Port" 的误导 traceback）。

§2.2 真空约定（建模铁律，docstring 即约定书）：真空=**普通 Box 完全包住**
全部固体（``material="vacuum"``，不布尔差、直接重叠）——HFSS validate 对
"完全包住"不报错可正常求解；对"部分相交"（实体穿出真空盒边界）报
``Parts Vacuum and W2_Membrane intersect.`` 求解失败（反馈 §2.2 两情形
实测：参考工程 SICL_kongqiang 的 vacuum Box 即此形态，SolveInside=true、
Transparency=1）。挖腔=分层围合（每非导体层按腔足印分段、导体层完整横
跨），零布尔运算（最小实现：不依赖 HFSS subtract，纯分段坐标离线可审
计，与 openEMS 渲染同一布局单源 layered_stack_spec.layered_stack_layout）。

金属渲染形态分派（spec 面 MATERIALS.is_metal）：
- 叠层内金属层（gold 键合层）=**实体盒**（HFSS 材质名，保声明厚度——
  3µm 实体纵横比 0.003/5.1≈5.9e-4 > 1e-5 不触 lint ⑤ 告警）；
- strip / 腔壁金属化=**零厚 PEC 片**（create_box 0mm 厚度=官方推荐
  sheet 形态，wilkinson GROUND 先例；3µm 腔壁涂层 RF 等效 PEC，
  openEMS 侧同口径零厚片）。

波端口（§2.1 实测形态"两端波端口覆盖整个腔截面"）：端口 sheet=腔体
截面矩形（YZ 面、x=±line_len/2=模型端面=真空盒端面——lint ①外边界
重合前提）；积分线=数值坐标 [[x, y_band, z_strip], [x, y_band, z_top]]
（信号导体 strip→参考导体腔顶壁；model_units mm 纯 float）。端口截面
材料分布=线上截面（§2.3 断言 3 建模期由 spec 校验器锁死）。

geometry_lint 闭环（批 1 验收核心）：plan["lint"] 投影 dict 由调用方/
测试喂 ``rfauto.service.geometry_lint_service.lint_geometry``；报告信封
可再喂 :meth:`rfauto.adapters.hfss_adapter.HfssAdapter.build_and_setup`
的 ``geometry_lint_report`` 钩子（T-Q26b 缺省关、显式开启：ERROR 在
build 出口/solve 前抛 ModelBuildError 拦截）。名义 spec 六检查零 ERROR
+ 恰 1 条 WARN（膜横跨腔截面=族固有形态，见 spec 模块 docstring）。

本模块不带 ``__all__``（public_api 快照口径记私有，零漂移）。
"""

from __future__ import annotations

from typing import Any

from rfauto.adapters.layered_stack_spec import (
    LayeredStackSpec,
    layered_stack_layout,
    layered_stack_lint_projection,
)

#: plan 形态标记（build 入口防 hand-crafted plan 绕过，wave_port_cpw 先例）
PLAN_KIND = "layered_stack_hfss_plan"

_PEC = "pec"
_VACUUM = "vacuum"


def _coords_to_origin_sizes(
    coords: tuple[float, float, float, float, float, float],
) -> tuple[list[float], list[float]]:
    """(min6) → (origin[3], sizes[3])（mm 数值；零轴=零厚 sheet 形态）。"""
    x0, x1, y0, y1, z0, z1 = coords
    return ([float(x0), float(y0), float(z0)],
            [float(x1) - float(x0), float(y1) - float(y0),
             float(z1) - float(z0)])


def _plan_object(name: str, material: str,
                 coords: tuple[float, float, float, float, float, float],
                 *, solve_inside: bool) -> dict[str, Any]:
    origin, sizes = _coords_to_origin_sizes(coords)
    return {
        "name": name, "material": material, "coords": tuple(float(v) for v in coords),
        "origin": origin, "sizes": sizes, "solve_inside": solve_inside,
        "is_sheet": any(abs(s) <= 1e-12 for s in sizes),
    }


def layered_stack_hfss_plan(
    spec: LayeredStackSpec | dict[str, Any],
) -> dict[str, Any]:
    """spec → HFSS 声明式 plan（离线中间形态；零 pyaedt 零真机）。

    Returns
    -------
    dict
        ``{"kind", "model_units", "objects", "ports", "lint", "notes"}``：

        - ``objects``：固体/薄片盒列表 ``{name, material, coords, origin,
          sizes, solve_inside, is_sheet}``（coords=六元组 mm，min/max 归一；
          ``is_sheet``=某轴零厚→pyaedt create_box 0mm 厚度形态）；
        - ``ports``：双波端口 ``{name, sheet:{orientation, origin, sizes},
          integration_line, modes, impedance, renormalize, deembed}``；
        - ``lint``：LintGeometry 兼容投影 dict（盒名与 objects 1:1）；
        - ``notes``：§2.2/§2.3 约定书与名义锚出处（进证据链）。
    """
    if isinstance(spec, dict):
        spec = LayeredStackSpec.model_validate(spec)
    lay = layered_stack_layout(spec)

    objects: list[dict[str, Any]] = []
    # 真空盒（§2.2 完全包住，普通 Box 不布尔差；x 与叠层共端面=端口面）
    vx0, vx1, vy0, vy1, vz0, vz1 = lay["vacuum_box_mm"]
    objects.append(_plan_object("VacuumBox", _VACUUM,
                                (vx0, vy0, vz0, vx1, vy1, vz1),
                                solve_inside=True))
    for seg in lay["stack_solids"]:
        bx = seg["box"]
        objects.append(_plan_object(
            str(seg["name"]), str(seg["material"]), bx,
            solve_inside=not bool(seg["is_metal"])))
    for sheet in lay["metal_sheets"]:
        objects.append(_plan_object(sheet["name"], _PEC, sheet["box"],
                                    solve_inside=False))
    objects.append(_plan_object("strip", _PEC, lay["strip"], solve_inside=False))

    ports: list[dict[str, Any]] = []
    for pt in lay["ports"]:
        pos = float(pt["pos_mm"])
        u0, u1 = (float(v) for v in pt["u_mm"])
        v0, v1 = (float(v) for v in pt["v_mm"])
        il = [[float(c) for c in point] for point in pt["integration_line_mm"]]
        ports.append({
            "name": str(pt["name"]),
            "sheet": {"orientation": "YZ",
                      "origin": [pos, u0, v0],
                      "sizes": [u1 - u0, v1 - v0]},
            "integration_line": il,
            "modes": 1,
            "impedance": 50.0,
            "renormalize": True,
            "deembed": 0.0,
        })

    return {
        "kind": PLAN_KIND,
        "model_units": "mm",
        "objects": objects,
        "ports": ports,
        "lint": layered_stack_lint_projection(lay),
        "notes": {
            "vacuum_convention": "§2.2：真空=普通 Box 完全包住全部固体"
                "（不布尔差直接重叠，合法）；部分相交=HFSS validate 报 "
                "'Parts ... intersect.' 求解失败——挖腔用分层围合（每非"
                "导体层按腔足印分段、导体层完整横跨），零布尔运算",
            "port_forms": "§2.3 三静默失败形态由 geometry_lint 六检查覆盖"
                "（①外边界重合 ②邻接 solve-inside 体 ③截面连通性 WARN）"
                "——报告信封经 build_and_setup(geometry_lint_report=) 在 "
                "solve 前拦截",
            "integration_line": "T-Q26a：波端口积分线=数值坐标（model_units "
                "mm），build 入口经 hfss_session.validate_integration_line "
                "前置校验（表达式字符串→ValueError 参数错误，不落 pyaedt "
                "误导 traceback）",
            "nominal_anchors": "§3.4 示例值（layers/cavity/conductor/"
                "metalization）+ §2.1 实测锚（line_len=5.1、silicon εr=11.9、"
                "εeff=1.59/Z0≈50.2）+ §5 锚（wafer_width=1.2、频带 85-105GHz）",
        },
    }


def build_layered_stack(app: Any, plan: dict[str, Any]) -> dict[str, Any]:
    """plan → pyaedt 会话执行（真机面；本批零真机，测试不触本路径）。

    Parameters
    ----------
    app : pyaedt ``Hfss`` 应用对象
        需支持 ``.modeler.create_box(origin, sizes, name, material)`` /
        ``.modeler.create_rectangle(orientation, origin, sizes, name)`` /
        ``.modeler.get_object_faces(name)`` / ``.wave_port(...)``（仓内
        wilkinson 插件与 wave_port_cpw 同接口形态）。
    plan : dict
        :func:`layered_stack_hfss_plan` 产物（kind 守卫，防 hand-crafted
        plan 绕过布局单源）。

    Returns
    -------
    dict
        ``{"objects": {名: 返回名}, "ports": [{name, sheet, face,
        integration_line, ...}]}``——F6 端口报告字段兼容形态。

    Raises
    ------
    ModelBuildError
        plan 形态非法 / 建几何或赋端口失败（pyaedt 异常族收口带上下文）。
    ValueError
        积分线非数值坐标（T-Q26a 前置校验——参数错误，先于任何 pyaedt
        调用）。
    """
    from rfauto.adapters.hfss_session import validate_integration_line
    from rfauto.core.errors import ModelBuildError

    if not isinstance(plan, dict) or plan.get("kind") != PLAN_KIND:
        raise ModelBuildError(
            "build_layered_stack: plan 需为 layered_stack_hfss_plan 的产物"
            f"（kind={PLAN_KIND!r}），实际 kind="
            f"{plan.get('kind') if isinstance(plan, dict) else None!r}——"
            "布局单源在 layered_stack_spec.layered_stack_layout，禁止 "
            "hand-crafted plan 绕过")
    modeler = getattr(app, "modeler", None)
    if modeler is None or not hasattr(modeler, "create_box"):
        raise ModelBuildError(
            "build_layered_stack: app 需为 pyaedt Hfss 形态（含 .modeler）")

    def _q(v: float) -> str:
        """长度值 → 显式单位串（防模型单位漂移；wave_port_cpw 同式）。"""
        return f"{float(v):.10g}mm"

    created: dict[str, str] = {}
    for obj in plan["objects"]:
        origin = [_q(v) for v in obj["origin"]]
        sizes = [_q(v) for v in obj["sizes"]]
        try:
            ret = modeler.create_box(origin=origin, sizes=sizes,
                                     name=obj["name"],
                                     material=str(obj["material"]))
        except Exception as exc:
            raise ModelBuildError(
                f"build_layered_stack: 建实体 {obj['name']} 失败: {exc}",
                details={"name": obj["name"], "origin": origin,
                         "sizes": sizes, "material": obj["material"]}) from exc
        created[str(obj["name"])] = str(ret) if ret else str(obj["name"])

    port_reports: list[dict[str, Any]] = []
    for pt in plan["ports"]:
        name = str(pt["name"])
        sheet_name = f"{name}Sheet"
        sh = pt["sheet"]
        # YZ 面 sheet：origin=[x, y0, z0]，sizes=[y_ext, z_ext]
        # （pyaedt Plane.YZ 本地轴 u→Y、v→Z；x 即 sheet 法向位置）
        origin = [_q(sh["origin"][0]), _q(sh["origin"][1]), _q(sh["origin"][2])]
        sizes = [_q(sh["sizes"][0]), _q(sh["sizes"][1])]
        try:
            sheet = modeler.create_rectangle(
                orientation=str(sh["orientation"]), origin=origin,
                sizes=sizes, name=sheet_name)
        except Exception as exc:
            raise ModelBuildError(
                f"build_layered_stack({name}): 建端口 sheet 失败: {exc}",
                details={"sheet": sheet_name, "origin": origin,
                         "sizes": sizes}) from exc
        if not sheet:
            raise ModelBuildError(
                f"build_layered_stack({name}): create_rectangle 返回空"
                "（pyaedt 建面失败）", details={"sheet": sheet_name})
        try:
            faces = modeler.get_object_faces(sheet_name)
        except Exception as exc:
            raise ModelBuildError(
                f"build_layered_stack({name}): get_object_faces 失败: {exc}",
                details={"sheet": sheet_name}) from exc
        if not faces:
            raise ModelBuildError(
                f"build_layered_stack({name}): sheet {sheet_name} 无面",
                details={"sheet": sheet_name})
        # T-Q26a 坑①前置校验：积分线必须数值坐标（表达式/变量名字符串在
        # 此即 ValueError 参数错误，不落 pyaedt "Failed to create boundary
        # Wave Port" 的误导 traceback）
        line = pt["integration_line"]
        validate_integration_line(line, param=f"{name} integration_line")
        try:
            app.wave_port(assignment=faces[0], name=name,
                          modes=int(pt["modes"]),
                          impedance=float(pt["impedance"]),
                          renormalize=bool(pt["renormalize"]),
                          deembed=float(pt["deembed"]),
                          integration_line=line)
        except Exception as exc:
            raise ModelBuildError(
                f"build_layered_stack({name}): pyaedt wave_port 赋值失败: "
                f"{exc}（接口形态=assignment=face/integration_line=数值"
                "坐标表，T-Q26a 口径）",
                details={"name": name, "sheet": sheet_name, "face": faces[0],
                         "integration_line": line}) from exc
        port_reports.append({
            "port": name, "sheet": sheet_name, "face": faces[0],
            "integration_line": line, "modes": int(pt["modes"]),
            "impedance": float(pt["impedance"]),
            "renormalize": bool(pt["renormalize"]),
            "deembed": float(pt["deembed"]),
        })
    return {"objects": created, "ports": port_reports}
