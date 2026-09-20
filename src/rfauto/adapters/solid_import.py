"""B3 实体导入适配层：STL 三角网格 → CSX 原语分类（可注入 render 脚本的行）。

分类路线（确定性顺序，禁止静默近似——每条 payload 必带 approximation.kind +
volume_rel_err + 是否依赖求解时 STL 路径）：
1. **box**：全部面法向轴对齐且 |V_mesh−V_bbox|/V_bbox ≤ 1e-9 →
   ``AddBox``（精确）；
2. **linpoly**：恰两个 z 层、层边界顶点集一致（凸包提取，CAD 帽面扇形的
   中心点自动剔除），面积×高 vs 网格散度体积一致 → ``AddLinPoly``（精确；
   N 边棱柱本体）；
3. **cylinder**：两平行圆环层（LSQ 半径残差 ≤1e-3）且层数 ≥16 →
   ``AddCylinder``（半径 LSQ 近似，volume_rel_err 如实申报；CAD 圆柱网格化
   的原生口径。低 N 圆-like 棱柱落路线 2 走精确 AddLinPoly，不近似的就不近似）；
4. **polyhedron_reader**：其余网格 → ``AddPolyhedronReader(stl_path)``
   （openEMS 官方原生 STL 导入，venv CSXCAD 绑定 docstring 实测「reads a STL
   or PLY file」；须给出 stl_path，且该路线依赖求解时 STL 文件存在——
   requires_stl_at_solve_time=True）。体素盒并集为替代路线，留 followUp。

CSX 坐标单位：米（与本仓 openems_templates 渲染脚本同口径，mm→m 显式 /1000）。
STEP/.stp 不在本层（CSXCAD 只读 STL/PLY，venv 无 OCP/steputils），service 层
显式拒绝。

D14/热族互操作（只注记不改 core/thermo_mech.py）：payload 的 bbox/volume 与
service.scale_solid_payload(payload, 1+CTE·ΔT) 对应 thermo_mech 的
scale_dimension / update_template_geometry 热膨胀链。
"""

from __future__ import annotations

from typing import Any

import numpy as np

from rfauto.core.solid_mesh import SolidMesh, SolidMeshError

_MM_PER_M = 1000.0
#: 轴对齐盒/棱柱的体积一致门（相对）；解析网格（整数坐标 float32）实测 0。
_EXACT_VOL_TOL = 1e-9
#: 圆环判定：LSQ 半径残差（max|dist−r|/r）与最少层顶点数。
_RING_LSQ_TOL = 1e-3
_RING_MIN_VERTICES = 16
#: 凸层角序重构的合法前提（非凸层角序面积不对 → 体积门红 → 引擎路线）。

_APPROX_EXACT = "exact"
_APPROX_LSQ_RADIUS = "lsq_radius"
_APPROX_ENGINE_STL = "engine_stl"


def _to_m(values) -> list[float]:
    """mm → m（显式单位换算；返回 Python float 列表，JSON 安全）。"""
    arr = np.asarray(values, dtype=float)
    return [float(v) / _MM_PER_M for v in arr.reshape(-1)]


def _axis_aligned_box_route(mesh: SolidMesh, name: str, material: str
                            ) -> dict[str, Any] | None:
    """路线 1：轴对齐盒 → AddBox（精确）。"""
    normals = mesh.face_normals
    nondeg = np.linalg.norm(normals, axis=1) > 0.0
    if not bool(np.all(nondeg)):
        return None
    absn = np.abs(normals[nondeg])
    # 轴对齐 ⇔ 每个法向至多一个显著分量（次小分量 ≈ 0）
    sorted_absn = np.sort(absn, axis=1)
    axis_aligned = bool(np.all(sorted_absn[:, 1] <= 1e-9))
    if not axis_aligned:
        return None
    lo, hi = mesh.bbox_mm
    volume = mesh.volume_mm3
    box_volume = float(np.prod(hi - lo))
    if box_volume <= 0.0:
        return None
    rel_err = abs(volume - box_volume) / box_volume
    if rel_err > _EXACT_VOL_TOL:
        return None
    return _payload(
        kind="box", primitive="AddBox", name=name, material=material,
        approximation={"kind": _APPROX_EXACT, "volume_rel_err": rel_err},
        requires_stl=False, stl_path=None,
        bbox_mm=(lo, hi), volume_mm3=volume,
        csx_args_m={"start": _to_m(lo), "stop": _to_m(hi)})


def _z_layer_routes(mesh: SolidMesh, name: str,
                    material: str) -> dict[str, Any] | None:
    """路线 2/3：恰两个 z 层的棱柱 → AddLinPoly（精确）或 AddCylinder（LSQ）。

    层边界用凸包提取（CAD 帽面扇形三角化的中心点在凸包内部，自动剔除）；
    上下层边界顶点集须同形同位（逐行 lexsort 对比），否则落引擎路线。
    """
    from scipy.spatial import ConvexHull, QhullError

    flat = mesh.triangles_mm.reshape(-1, 3)
    quant = np.round(flat, 6)
    z_values = np.unique(quant[:, 2])
    if z_values.size != 2:
        return None
    z0, z1 = float(z_values[0]), float(z_values[1])
    if not z1 > z0:
        return None
    height = z1 - z0
    layer_ids = (np.round(flat[:, 2] / 1e-6).astype(np.int64) ==
                 np.round(z0 / 1e-6).astype(np.int64))

    def layer_boundary(is_bottom: bool) -> np.ndarray | None:
        """层合并顶点 → 凸包边界（**原始坐标**：量化只做身份合并，几何
        计算用原值，否则面积门被量化误差打穿）。"""
        select = layer_ids if is_bottom else ~layer_ids
        q2d = quant[select][:, :2]
        o2d = flat[select][:, :2]
        if q2d.shape[0] < 3:
            return None
        _, first = np.unique(q2d, axis=0, return_index=True)
        merged = o2d[first]
        if merged.shape[0] < 3:
            return None
        try:
            hull = ConvexHull(merged)
        except QhullError:
            return None
        return merged[hull.vertices]  # qhull 2D：CCW 有序边界

    bottom_b = layer_boundary(True)
    top_b = layer_boundary(False)
    if (bottom_b is None or top_b is None
            or bottom_b.shape != top_b.shape):
        return None
    order = lambda p: p[np.lexsort((p[:, 1], p[:, 0]))]  # noqa: E731
    # 层边界顶点集一致（同形同位；CAD 上下层网格化不一致 → 引擎路线）
    if not np.allclose(order(bottom_b), order(top_b), rtol=0.0, atol=1e-6):
        return None
    volume = mesh.volume_mm3
    if volume <= 0.0:
        return None
    n_layer = int(bottom_b.shape[0])

    ring = _ring_fit(bottom_b)
    if ring is not None and n_layer >= _RING_MIN_VERTICES:
        # 路线 3：高 N 圆环 → AddCylinder（半径 LSQ，近似如实申报）
        cx, cy, radius, lsq_residual = ring
        ideal = math_pi_radius_volume(radius, height)
        rel_err = abs(volume - ideal) / volume
        return _payload(
            kind="cylinder", primitive="AddCylinder", name=name,
            material=material,
            approximation={"kind": _APPROX_LSQ_RADIUS,
                           "volume_rel_err": rel_err,
                           "ring_lsq_residual": lsq_residual,
                           "n_ring_vertices": n_layer},
            requires_stl=False, stl_path=None,
            bbox_mm=mesh.bbox_mm, volume_mm3=volume,
            csx_args_m={"start": [cx / _MM_PER_M, cy / _MM_PER_M, z0 / _MM_PER_M],
                        "stop": [cx / _MM_PER_M, cy / _MM_PER_M, z1 / _MM_PER_M],
                        "radius": radius / _MM_PER_M})

    # 路线 2：N 边棱柱 → AddLinPoly（凸包 CCW 序；体积门不过 → None 落引擎路线）
    area = _shoelace(bottom_b)
    if area <= 0.0:
        return None
    rel_err = abs(volume - area * height) / volume
    if rel_err > _EXACT_VOL_TOL:
        return None
    points_x_m = [float(p[0]) / _MM_PER_M for p in bottom_b]
    points_y_m = [float(p[1]) / _MM_PER_M for p in bottom_b]
    return _payload(
        kind="linpoly", primitive="AddLinPoly", name=name, material=material,
        approximation={"kind": _APPROX_EXACT, "volume_rel_err": rel_err,
                       "n_layer_vertices": n_layer},
        requires_stl=False, stl_path=None,
        bbox_mm=mesh.bbox_mm, volume_mm3=volume,
        # CSXCAD 绑定实测：AddLinPoly 的 points 是 [xs, ys] 两列（.pyx 断言
        # len(points)==2；docstring 的 "(N,2) array" 说法与断言不符，以实测为准）
        csx_args_m={"points": [points_x_m, points_y_m], "norm_dir": 2,
                    "elevation": z0 / _MM_PER_M, "length": height / _MM_PER_M})


def _ring_fit(points_xy: np.ndarray) -> tuple[float, float, float, float] | None:
    """层边界点 → (cx, cy, r, LSQ 残差)：半径最小二乘 + 圆度门。"""
    center = points_xy.mean(axis=0)
    dist = np.linalg.norm(points_xy - center, axis=1)
    radius = float(np.sqrt(np.mean(dist * dist)))
    if radius <= 0.0:
        return None
    residual = float(np.max(np.abs(dist - radius)) / radius)
    if residual > _RING_LSQ_TOL:
        return None
    return float(center[0]), float(center[1]), radius, residual


def math_pi_radius_volume(radius_mm: float, height_mm: float) -> float:
    """理想圆柱体积 πr²h（LSQ 路线的申报基准；np.pi 精度）。"""
    return float(np.pi * radius_mm * radius_mm * height_mm)


def _shoelace(ordered_xy: np.ndarray) -> float:
    """有序多边形面积的绝对值（shoelace）。"""
    x = ordered_xy[:, 0]
    y = ordered_xy[:, 1]
    return float(abs(np.dot(x, np.roll(y, -1)) - np.dot(np.roll(x, -1), y)) / 2.0)


def _payload(*, kind: str, primitive: str, name: str, material: str,
             approximation: dict[str, Any], requires_stl: bool,
             stl_path: str | None, bbox_mm: tuple[np.ndarray, np.ndarray],
             volume_mm3: float, csx_args_m: dict[str, Any]) -> dict[str, Any]:
    lo, hi = bbox_mm
    return {
        "kind": kind,
        "primitive": primitive,
        "name": name,
        "material": material,
        "approximation": approximation,
        "requires_stl_at_solve_time": requires_stl,
        "stl_path": stl_path,
        "bbox_mm": {"lo": [float(v) for v in lo], "hi": [float(v) for v in hi]},
        "volume_mm3": volume_mm3,
        "csx_args_m": csx_args_m,
    }


def classify_solid(mesh: SolidMesh, *, name: str = "solid",
                   material: str = "metal", stl_path: str | None = None) -> dict[str, Any]:
    """SolidMesh → 单条 CSX 原语 payload（分类器，路线见模块 docstring）。

    非盒/柱/棱柱网格必须给 stl_path（PolyhedronReader 引擎路线在生成行时
    需要文件路径），否则显式 ValueError——禁止静默近似。
    """
    box = _axis_aligned_box_route(mesh, name, material)
    if box is not None:
        return box
    prism = _z_layer_routes(mesh, name, material)
    if prism is not None:
        return prism
    if stl_path is None:
        raise ValueError(
            f"网格 {name!r} 不是轴对齐盒/两 z 层棱柱，走 PolyhedronReader 引擎"
            "路线需要 stl_path（求解时读 STL 文件）；禁止静默近似")
    return _payload(
        kind="polyhedron_reader", primitive="AddPolyhedronReader", name=name,
        material=material,
        approximation={"kind": _APPROX_ENGINE_STL, "volume_rel_err": 0.0},
        requires_stl=True, stl_path=stl_path,
        bbox_mm=mesh.bbox_mm, volume_mm3=mesh.volume_mm3,
        # CSXCAD 实测：PolyhedronReader 按文件原生数字读入
        # （不知道单位），故必须挂 AddTransform('Scale', 1e-3) 把 mm 映到 m；
        # 变换只作用于 IsInside（网格器消费面），GetBoundBox 仍报原生 mm——
        # render 脚本的网格线须由 payload bbox_mm/1000 推导，勿读原语 bbox。
        csx_args_m={"filename": str(stl_path), "file_units": "mm",
                    "scale_to_m": 1.0 / _MM_PER_M})


# ─── CSX 行生成 / 直接应用（#212 离线审计两用）────────────────────────────────


def _prop_var(material: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch == "_" else "_"
                   for ch in str(material))
    return f"_solid_import_{safe}"


def csx_lines(payloads: list[dict[str, Any]], *, csx_var: str = "CSX") -> list[str]:
    """payload 列表 → 可注入 render 脚本几何段的 CSX 代码行。

    同 material 共享一条属性；坐标全部米（repr 全精度，往返无损）。
    exec 环境须已绑定 ``csx_var``（如模板脚本里的 CSX）。
    """
    lines: list[str] = []
    prop_seen: set[str] = set()
    prim_seq = 0
    for payload in payloads:
        material = str(payload["material"])
        var = _prop_var(material)
        if var not in prop_seen:
            prop_seen.add(var)
            lines.append(f"{var} = {csx_var}.AddMetal({material!r})")
        args = payload["csx_args_m"]
        if payload["kind"] == "box":
            lines.append(f"{var}.AddBox(start={args['start']!r}, "
                         f"stop={args['stop']!r})")
        elif payload["kind"] == "cylinder":
            lines.append(f"{var}.AddCylinder(start={args['start']!r}, "
                         f"stop={args['stop']!r}, radius={args['radius']!r})")
        elif payload["kind"] == "linpoly":
            lines.append(f"{var}.AddLinPoly(points={args['points']!r}, "
                         f"norm_dir={args['norm_dir']}, "
                         f"elevation={args['elevation']!r}, "
                         f"length={args['length']!r})")
        elif payload["kind"] == "polyhedron_reader":
            prim_var = f"_solid_prim_{prim_seq}"
            prim_seq += 1
            # mm 文件 → m 引擎域：挂 Scale 变换（GetBoundBox 不随变换，
            # IsInside/网格器按变换后坐标，CSXCAD 实测）
            lines.append(f"{prim_var} = {var}.AddPolyhedronReader("
                         f"{str(args['filename'])!r})")
            lines.append(f"{prim_var}.AddTransform('Scale', "
                         f"{args['scale_to_m']!r})")
        else:  # pragma: no cover - 分类器只产四种 kind
            raise SolidMeshError(f"未知 payload kind: {payload['kind']!r}")
    return lines


def apply_solids(csx: Any, payloads: list[dict[str, Any]]) -> list[Any]:
    """直接把 payload 应用到 ContinuousStructure（离线审计用，不经 exec）。"""
    props: dict[str, Any] = {}
    prims: list[Any] = []
    for payload in payloads:
        material = str(payload["material"])
        prop = props.get(material)
        if prop is None:
            prop = csx.AddMetal(material)
            props[material] = prop
        args = payload["csx_args_m"]
        kind = payload["kind"]
        if kind == "box":
            prims.append(prop.AddBox(start=args["start"], stop=args["stop"]))
        elif kind == "cylinder":
            prims.append(prop.AddCylinder(start=args["start"], stop=args["stop"],
                                          radius=args["radius"]))
        elif kind == "linpoly":
            prims.append(prop.AddLinPoly(points=args["points"],
                                         norm_dir=int(args["norm_dir"]),
                                         elevation=args["elevation"],
                                         length=args["length"]))
        elif kind == "polyhedron_reader":
            prim = prop.AddPolyhedronReader(str(args["filename"]))
            # mm 文件 → m 引擎域（IsInside/网格器消费面；见分类器注记）
            prim.AddTransform("Scale", float(args["scale_to_m"]))
            prims.append(prim)
        else:  # pragma: no cover
            raise SolidMeshError(f"未知 payload kind: {kind!r}")
    return prims
