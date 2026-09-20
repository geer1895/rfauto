"""实体网格内核：纯 numpy STL 解析与闭合网格度量（零新依赖）。

STEP/STL 导入能力的内核层。
依赖对账（实测）：venv 里的 trimesh 5.1.0 仅是 fdtdx 的传递依赖
（pyproject/uv.lock 均未声明），本内核**禁止消费它**——STL 解析用纯 numpy
自写（binary + ASCII 两种格式），零新依赖、零网络。

格式口径（STL 规范）：
- binary：80 字节头 + uint32 三角计数 + 每三角 50 字节
  （法向 3×float32 + 三顶点 9×float32 + uint16 属性字节数），文件总长
  必须恰为 84 + 50×n，长度不匹配即显式报错（坏头检测）；
- ASCII：``solid ... facet normal .. outer loop / vertex .. / endloop /
  endfacet / endsolid`` 行结构，逐 vertex 行取三个浮点。

单位口径（显式，#218）：STL 数字按 **mm** 读入（CAD 惯例），SolidMesh 全部
度量以 mm 计；转 m 由 adapters/solid_import.py 负责（/1000）。STEP/.stp 不被
CSXCAD 支持（venv 绑定 docstring 实测：CSPrimPolyhedronReader 只读 STL/PLY；
OCP/steputils 均未安装），在 service 层显式拒绝并登记 followUp。

度量口径：
- 体积：散度定理 V = |Σ v0·(v1×v2)|/6（符号体积 >0 即法向朝外）；
- 水密（watertight）：顶点按 1e-6 mm（nm 级）量化合并后，每条无向边恰被
  两个三角共享，且定向一致（每条有向边与其反向各恰出现一次）；
- 边流形（edge manifold）：每条无向边 ≤2 个三角（弱于水密）；
- 连通分量：共享量化顶点的三角经并查集聚类。
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np

#: 顶点身份量化步长（mm）：nm 级，吸收 float32 STL 的写出口径差异。
VERTEX_QUANTUM_MM = 1e-6

_BINARY_HEADER_BYTES = 80
_BINARY_COUNT_OFFSET = 80
_BINARY_TRI_BYTES = 50
_BINARY_MIN_LEN = _BINARY_HEADER_BYTES + 4


class SolidMeshError(ValueError):
    """STL 解析/度量失败（显式报错语义，service 层翻译成 ok=False）。"""


@dataclass(frozen=True)
class SolidMesh:
    """三角网格（mm）：immutable 度量容器，属性惰性计算后即确定。"""

    triangles_mm: np.ndarray  # (n, 3, 3) float

    # ── 基本量 ───────────────────────────────────────────────────────────

    @property
    def n_triangles(self) -> int:
        return int(self.triangles_mm.shape[0])

    @property
    def bbox_mm(self) -> tuple[np.ndarray, np.ndarray]:
        flat = self.triangles_mm.reshape(-1, 3)
        return flat.min(axis=0), flat.max(axis=0)

    @property
    def signed_volume_mm3(self) -> float:
        """散度定理符号体积（>0 = 法向朝外）。"""
        v0 = self.triangles_mm[:, 0, :]
        v1 = self.triangles_mm[:, 1, :]
        v2 = self.triangles_mm[:, 2, :]
        return float(np.sum(np.einsum("ij,ij->i", v0, np.cross(v1, v2))) / 6.0)

    @property
    def volume_mm3(self) -> float:
        return abs(self.signed_volume_mm3)

    @property
    def face_normals(self) -> np.ndarray:
        """单位面法向 (n,3)；零面积三角给零向量。"""
        e1 = self.triangles_mm[:, 1, :] - self.triangles_mm[:, 0, :]
        e2 = self.triangles_mm[:, 2, :] - self.triangles_mm[:, 0, :]
        raw = np.cross(e1, e2)
        norm = np.linalg.norm(raw, axis=1, keepdims=True)
        return np.divide(raw, norm, out=np.zeros_like(raw), where=norm > 0.0)

    @property
    def n_degenerate_triangles(self) -> int:
        e1 = self.triangles_mm[:, 1, :] - self.triangles_mm[:, 0, :]
        e2 = self.triangles_mm[:, 2, :] - self.triangles_mm[:, 0, :]
        area2 = np.linalg.norm(np.cross(e1, e2), axis=1)
        scale = max(float(np.max(np.abs(self.triangles_mm))), 1.0)
        return int(np.sum(area2 <= 1e-12 * scale * scale))

    # ── 拓扑（顶点量化合并后判定）────────────────────────────────────────

    def _quantized_vertex_ids(self) -> np.ndarray:
        """3n 个顶点 → 合并后的整数 id（量化坐标字典序去重）。"""
        flat = self.triangles_mm.reshape(-1, 3)
        quant = np.round(flat / VERTEX_QUANTUM_MM).astype(np.int64)
        _, ids = np.unique(quant, axis=0, return_inverse=True)
        return ids.reshape(-1, 3)  # (n, 3) 三角的三个顶点 id

    @property
    def _edge_table(self) -> dict[tuple[int, int], int]:
        """无向边 → 出现次数；同时校验定向一致性时复用 _directed_edges。"""
        faces = self._quantized_vertex_ids()
        table: dict[tuple[int, int], int] = {}
        for a, b, c in faces:
            for u, v in ((a, b), (b, c), (c, a)):
                key = (u, v) if u < v else (v, u)
                table[key] = table.get(key, 0) + 1
        return table

    @property
    def _directed_edge_counts(self) -> tuple[dict[tuple[int, int], int],
                                             dict[tuple[int, int], int]]:
        """(有向边计数, 其反向边计数)——定向一致性判定用。"""
        faces = self._quantized_vertex_ids()
        fwd: dict[tuple[int, int], int] = {}
        rev: dict[tuple[int, int], int] = {}
        for a, b, c in faces:
            for u, v in ((a, b), (b, c), (c, a)):
                fwd[(u, v)] = fwd.get((u, v), 0) + 1
                rev[(v, u)] = rev.get((v, u), 0) + 1
        return fwd, rev

    @property
    def is_edge_manifold(self) -> bool:
        return all(count <= 2 for count in self._edge_table.values())

    @property
    def is_watertight(self) -> bool:
        """水密 = 每条无向边恰 2 个三角 且 定向一致（每条有向边恰 1 次，
        其反向也恰 1 次）。缺面/重叠面/未定向网格都判 False。"""
        fwd, rev = self._directed_edge_counts
        if set(fwd) != set(rev):
            return False
        return all(count == 1 for count in fwd.values())

    @property
    def component_labels(self) -> list[int]:
        """三角的连通分量标签（共享量化顶点即连通；并查集，0 起连续编号）。"""
        faces = self._quantized_vertex_ids()
        n_vertex = int(faces.max()) + 1 if faces.size else 0
        parent = list(range(n_vertex))

        def find(i: int) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for a, b, c in faces:
            for u, v in ((a, b), (b, c)):
                ru, rv = find(int(u)), find(int(v))
                if ru != rv:
                    parent[ru] = rv
        tri_labels = [find(int(f[0])) for f in faces]
        remap: dict[int, int] = {}
        out: list[int] = []
        for label in tri_labels:
            if label not in remap:
                remap[label] = len(remap)
            out.append(remap[label])
        return out

    @property
    def n_connected_components(self) -> int:
        return len(set(self.component_labels))

    # ── 变换 ─────────────────────────────────────────────────────────────

    def scaled(self, factor: float) -> SolidMesh:
        """均匀缩放（与 core/thermo_mech.scale_dimension 同语义）。"""
        return SolidMesh(np.asarray(self.triangles_mm, dtype=float) * float(factor))


# ─── 解析（binary / ASCII 自动判别）──────────────────────────────────────────


def _try_parse_binary(data: bytes) -> list[tuple[list[float], list[list[float]]]] | None:
    """binary STL 候选解析：长度校验失败返回 None（转 ASCII 路线）。"""
    if len(data) < _BINARY_MIN_LEN:
        return None
    (n_tri,) = struct.unpack_from("<I", data, _BINARY_COUNT_OFFSET)
    expected = _BINARY_MIN_LEN + _BINARY_TRI_BYTES * n_tri
    if len(data) != expected:
        return None
    facets: list[tuple[list[float], list[list[float]]]] = []
    offset = _BINARY_MIN_LEN
    for _ in range(n_tri):
        values = struct.unpack_from("<12fH", data, offset)
        normal = list(values[0:3])
        verts = [list(values[3 + 3 * k:6 + 3 * k]) for k in range(3)]
        facets.append((normal, verts))
        offset += _BINARY_TRI_BYTES
    return facets


def _parse_ascii(data: bytes) -> list[tuple[list[float], list[list[float]]]]:
    """ASCII STL 解析：逐 vertex 行取浮点，按 3 个一组成三角。"""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SolidMeshError(
            f"STL 解析失败：既不是合法 binary STL（长度校验不过），"
            f"也不是可解码的 ASCII STL（{exc}）") from exc
    vertices: list[list[float]] = []
    for raw_line in text.splitlines():
        parts = raw_line.split()
        if len(parts) == 4 and parts[0] == "vertex":
            try:
                vertices.append([float(parts[1]), float(parts[2]), float(parts[3])])
            except ValueError as exc:
                raise SolidMeshError(f"ASCII STL vertex 行非法: {raw_line!r}") from exc
    if not vertices:
        raise SolidMeshError("ASCII STL 未解析到任何 vertex 行（缺 facet/vertex 结构）")
    if len(vertices) % 3 != 0:
        raise SolidMeshError(
            f"ASCII STL 顶点数 {len(vertices)} 不是 3 的倍数（facet 结构破损）")
    return [([], vertices[3 * k:3 * k + 3]) for k in range(len(vertices) // 3)]


def parse_stl_bytes(data: bytes) -> SolidMesh:
    """bytes → SolidMesh（binary 优先：长度校验恰合即按 binary 读）。"""
    facets = _try_parse_binary(data)
    if facets is None:
        facets = _parse_ascii(data)
    tris = np.asarray([verts for _, verts in facets], dtype=float)
    if tris.ndim != 3 or tris.shape[0] == 0:
        raise SolidMeshError("STL 未解析到任何三角")
    return SolidMesh(tris.reshape(-1, 3, 3))


def parse_stl_file(path: str | Path) -> SolidMesh:
    """文件路径 → SolidMesh（缺文件 FileNotFoundError 原样上抛）。"""
    return parse_stl_bytes(Path(path).read_bytes())


def solid_mesh_from_triangles(triangles) -> SolidMesh:
    """(n,3,3) 数组/嵌套列表 → SolidMesh（给计算器网格路线复用解析度量）。"""
    tris = np.asarray(triangles, dtype=float)
    if tris.ndim != 3 or tris.shape[1:] != (3, 3):
        raise SolidMeshError(f"triangles 须为 (n,3,3)，收到 shape {tris.shape}")
    return SolidMesh(tris)
