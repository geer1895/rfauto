"""EC-8 全模板 golden 几何回归仓（W2-S8，架构批）。

对 openEMS 模板注册表（TEMPLATE_META）全部族：以标称参数（TEMPLATE_NOMINAL
——与 docs/templates/<族>/meta.yaml nominal_params 双侧严格相等，钉在
test_template_meta_consistency）+ 缺省网格（meta mesh_resolution_mm=0.0 自动档）
各渲染一次，落盘 golden 快照到 ``tests/golden/template_geometry/<族>.yaml``：

- 渲染脚本全文 sha256（文本面逐字节钉）；
- CSX 几何段摘要：原语按（属性, 类型）计数 + 逐原语包围盒 1e-9 m（nm 级）
  舍入排序哈希——对任意几何改动敏感、对浮点噪声免疫；
- 网格摘要：三轴线数 + 最小间距 + 线坐标 1e-6 m（µm 级）舍入哈希；
- 端口号集合（脚本 ``_portN`` 绑定按对象身份去重）。

体积/信息量取舍：每族 YAML 2-4KB（不存渲染脚本全文 72×10-40KB；逐原语
摘要哈希承载几何全文等价信息，人读计数作差异定位摘要）。快照零时间戳，
同树重算 diff 恒空（幂等）。

渲染守卫（#266 NEAR≤缝/3 族、过孔直径 4·NEAR 族等）对 7 族缺省档拒绝
（combline/interdigital/sir_bpf/ring_resonator/xcheb_bpf4 缝分辨、
isl_shielded/sicl 孔径分辨）——golden 记 ``status: guard_blocked`` + 守卫
原文，如实不伪造哈希、不绕守卫（守卫拒绝本身也被钉住：守卫阈值漂移即红）。

再生成（显式意图门，防误吞真回归）::

    rfauto templates golden-diff --accept
    或 RFAUTO_REGEN_GOLDEN=1 环境变量跑 tests/unit/test_template_golden.py
    （test_golden_regression 先例）。

渲染面只读（openems_templates.render_script 单源），exec 截段口径与
tests/unit/_geometry_audit_helpers.load_geometry 同一手法（「# ── 求解 ──」
标记优先、FDTD.Run( 回退）——本模块不得 import tests（分层），故按同一
公开手法在 service 侧重实现；判断面全部在 CSXCAD 实测对象上（#212 家法）。
"""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from rfauto.adapters.openems_templates import (
    TEMPLATE_META,
    TEMPLATE_NOMINAL,
    render_script,
)

__all__ = [
    "DIGEST_VERSION",
    "GOLDEN_SCHEMA_VERSION",
    "accept_template_golden",
    "build_template_golden",
    "compute_template_digest",
    "diff_template_golden",
    "golden_dir",
    "golden_path",
    "template_band",
]

#: golden 快照 schema 版本（形状变更时升位）
GOLDEN_SCHEMA_VERSION = "rfauto-template-geometry-golden/v1"
#: 摘要算法版本（舍入粒度/字段集变更时升位）
DIGEST_VERSION = 1
#: 审计频带半宽（GHz；_geometry_audit_helpers.BAND_HALF_GHZ 同口径）
_BAND_HALF_GHZ = 0.25
#: 原语包围盒舍入粒度（米；1 nm）
_PRIM_DECIMALS = 9
#: 网格线/最小间距舍入粒度（米；1 µm）
_MESH_DECIMALS = 6

_REPO_ROOT = Path(__file__).resolve().parents[3]
_GOLDEN_SUBDIR = Path("tests") / "golden" / "template_geometry"


def golden_dir() -> Path:
    """golden 快照目录（tests/golden/template_geometry/）。"""
    return _REPO_ROOT / _GOLDEN_SUBDIR


def golden_path(template: str) -> Path:
    """单族 golden 快照文件路径。"""
    return golden_dir() / f"{template}.yaml"


def template_band(template: str) -> tuple[float, float]:
    """模板审计频带（meta f0 ±0.25GHz；_geometry_audit_helpers.band_for 同口径）。"""
    f0 = float(TEMPLATE_META[template]["f0_ghz"])
    return (f0 - _BAND_HALF_GHZ, f0 + _BAND_HALF_GHZ)


def _template_list(templates: list[str] | tuple[str, ...] | None) -> list[str]:
    """None → 全部注册族（排序）；显式名单校验存在性（PathLike 收敛先例）。"""
    if templates is None:
        return sorted(TEMPLATE_META)
    out: list[str] = []
    for name in templates:
        if name not in TEMPLATE_META:
            raise KeyError(f"未知模板 {name!r}（注册表 {len(TEMPLATE_META)} 族）")
        out.append(name)
    return sorted(out)


# ── CSX 实测摘要（判断面在 CSXCAD 实测对象上，#212 家法） ────────────────────


def _prim_record(prop_name: str, kind: str, prim: Any) -> tuple[str, str, str, Any]:
    """单原语 → (记录行, lo, hi, radius)。

    包围盒口径与 _geometry_audit_helpers.extract_primitives 同一（柱/柱壳
    按外径沿非轴两向外扩；Polygon/LinPoly 走 GetBoundBox）。
    """
    ptype = str(prim.GetType())
    radius = None
    if hasattr(prim, "GetStart"):
        start = np.asarray(prim.GetStart(), dtype=float)
        stop = np.asarray(prim.GetStop(), dtype=float)
        lo = np.minimum(start, stop)
        hi = np.maximum(start, stop)
        if ptype in ("5", "6"):
            radius = float(prim.GetRadius())
            outer = radius + (float(prim.GetShellWidth()) / 2.0
                              if ptype == "6" else 0.0)
            axis = int(np.argmax(hi - lo))
            grow = np.array([outer, outer, outer])
            grow[axis] = 0.0
            lo = lo - grow
            hi = hi + grow
    else:
        bb = np.asarray(prim.GetBoundBox(), dtype=float)
        lo, hi = bb[0], bb[1]
    return (prop_name, kind, ptype, (lo, hi, radius))


def _record_line(rec: tuple[str, str, str, Any]) -> str:
    """原语记录 → 规范行（nm 级舍入；排序+拼接后作哈希输入）。"""
    name, kind, ptype, (lo, hi, radius) = rec
    lo_s = ",".join(f"{v:.{_PRIM_DECIMALS}f}" for v in lo)
    hi_s = ",".join(f"{v:.{_PRIM_DECIMALS}f}" for v in hi)
    r_s = "none" if radius is None else f"{radius:.{_PRIM_DECIMALS}f}"
    return f"{name}|{kind}|{ptype}|{lo_s}|{hi_s}|{r_s}"


def _csx_summary(csx: Any) -> dict[str, Any]:
    """CSX 对象 → 几何摘要 dict（计数+包围盒+哈希）。"""
    props: list[dict[str, Any]] = []
    records: list[tuple[str, str, str, Any]] = []
    for i in range(csx.GetQtyProperties()):
        prop = csx.GetProperty(i)
        kind = str(prop.GetTypeString())
        prop_name = str(prop.GetName())
        prim_counts: dict[str, int] = {}
        for prim in prop.GetAllPrimitives():
            ptype = str(prim.GetType())
            prim_counts[ptype] = prim_counts.get(ptype, 0) + 1
            records.append(_prim_record(prop_name, kind, prim))
        props.append({
            "name": prop_name,
            "kind": kind,
            "n": sum(prim_counts.values()),
            "types": dict(sorted(prim_counts.items())),
        })
    records.sort(key=_record_line)
    prim_sha = hashlib.sha256(
        "\n".join(_record_line(r) for r in records).encode("utf-8")).hexdigest()
    if records:
        lo = np.min([r[3][0] for r in records], axis=0)
        hi = np.max([r[3][1] for r in records], axis=0)
        bbox = [round(float(v), _PRIM_DECIMALS) for v in (*lo, *hi)]
    else:
        bbox = []
    return {
        "n_primitives": len(records),
        "props": props,
        "primitives_sha256": prim_sha,
        "bbox_m": bbox,
    }


def _mesh_summary(mesh: Any) -> dict[str, Any]:
    """网格对象 → 三轴线数/最小间距/线坐标哈希。"""
    lines_info: dict[str, dict[str, Any]] = {}
    parts: list[str] = []
    for axis in ("x", "y", "z"):
        arr = np.sort(np.asarray(mesh.GetLines(axis), dtype=float))
        diffs = np.diff(arr)
        lines_info[axis] = {
            "n": int(arr.size),
            "min_gap_m": (round(float(diffs.min()), _MESH_DECIMALS)
                          if diffs.size else None),
        }
        parts.append(axis + "=" + ",".join(
            f"{v:.{_MESH_DECIMALS}f}" for v in arr))
    lines_sha = hashlib.sha256(";".join(parts).encode("utf-8")).hexdigest()
    return {"lines": lines_info, "lines_sha256": lines_sha}


def _port_numbers(scope: dict[str, Any]) -> list[int]:
    """脚本 ``_portN`` 绑定 → 端口号去重集合（对象身份去重，patch 别名并入——
    _geometry_audit_helpers.port_objects 同口径）。"""
    raw: dict[int, Any] = {}
    for key, value in scope.items():
        if key.startswith("_port") and key[5:].isdigit():
            raw.setdefault(int(key[5:]), value)
    seen: dict[int, int] = {}
    for number in sorted(raw):
        seen.setdefault(id(raw[number]), number)
    return sorted(seen.values())


# ── 摘要计算 ─────────────────────────────────────────────────────────────────

#: W5-P3-6（架构批 W1-S4）：会话摘要缓存键补渲染源指纹——旧键
#: (template, DIGEST_VERSION, mesh) 无源成分，开发期改 openems_templates
#: 渲染器或测试 monkeypatch render_script 后同键仍吃会话内旧 digest。
#: _DIGEST_CACHE: dict[tuple[Any, ...], dict[str, Any]]
_DIGEST_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}


def _render_source_fp() -> tuple[int, int, int, int]:
    """render_script 渲染源指纹（纯键成分，值面零变化）。

    =（函数对象 id, 源文件 (mtime_ns,size) 哈希, 代码首行号, 代码对象长度）
    ——改源文件（mtime 变）或换函数对象（monkeypatch，id 变）任一即失效；
    源文件不可得（动态构造函数等）按 (0,0) 计、仍由 id+code 成分兜底。
    """
    code = getattr(render_script, "__code__", None)
    firstline = int(getattr(code, "co_firstlineno", 0) or 0)
    codelen = len(code.co_code) if code else 0
    try:
        import inspect

        st = Path(inspect.getsourcefile(render_script) or "").stat()
        src_sig = hash((st.st_mtime_ns, st.st_size))
    except (OSError, TypeError, ValueError):
        src_sig = 0
    return (id(render_script), src_sig, firstline, codelen)


def compute_template_digest(
    template: str, *, mesh_resolution_mm: float = 0.0,
) -> dict[str, Any]:
    """单族渲染摘要（nominal 参数 + 指定 mesh，缺省 0.0=自动档）。

    返回 golden 快照形状 dict：status=ok（含哈希面）/guard_blocked（渲染
    守卫拒绝，guard_error=守卫原文）/error（几何段 exec/实测异常）。
    同参数结果会话内缓存（load_geometry 先例）；键含渲染源指纹
    （W5-P3-6：改渲染器/monkeypatch 后即刻失效）。
    """
    key = (template, DIGEST_VERSION, float(mesh_resolution_mm),
           *_render_source_fp())
    cached = _DIGEST_CACHE.get(key)
    if cached is not None:
        return copy.deepcopy(cached)
    nominal = dict(TEMPLATE_NOMINAL[template])
    band = template_band(template)
    common = {
        "schema": GOLDEN_SCHEMA_VERSION,
        "template": template,
        "digest_version": DIGEST_VERSION,
        "mesh_resolution_mm": float(mesh_resolution_mm),
        "freq_range_ghz": [round(band[0], 6), round(band[1], 6)],
        "params": nominal,
    }
    try:
        text = render_script(template, dict(nominal), band,
                             mesh_resolution_mm=float(mesh_resolution_mm))
    except ValueError as exc:
        # 渲染期守卫拒绝（#266 缝分辨/孔径分辨/YJ>0 拓扑守卫族）——如实登记
        digest = {**common, "status": "guard_blocked",
                  "guard_error": str(exc)}
        _DIGEST_CACHE[key] = digest
        return copy.deepcopy(digest)
    except Exception as exc:
        # W6-P3-7（架构批 W1-S4）：渲染期非守卫异常（KeyError/TypeError 等
        # 渲染器缺陷面）此前裸穿透让 build/diff 整批中断——与几何段 exec
        # 面同口径落 error 态如实登记，逐族循环不中断（不冒充守卫拒绝）。
        digest = {**common, "status": "error",
                  "error": f"{type(exc).__name__}: {exc}"}
        _DIGEST_CACHE[key] = digest
        return copy.deepcopy(digest)
    digest: dict[str, Any] = {
        **common,
        "status": "ok",
        "script_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }
    try:
        # 几何段截取（FDTD.Run 之前）——槽线族整脚本渲染器有「# ── 求解 ──」
        # 标记优先（load_geometry 同口径；直接截 FDTD.Run( 会留悬空 if）
        marker = text.find("# ── 求解 ──")
        cut = marker if marker >= 0 else text.index("FDTD.Run(")
        head = text[:cut]
        csx_scope: dict[str, Any] = {
            "__name__": "__main__",
            "__file__": str(_REPO_ROOT / "_template_golden_sim.py"),
        }
        exec(compile(head, "template_golden", "exec"), csx_scope)
        digest["csx"] = _csx_summary(csx_scope["CSX"])
        digest["mesh"] = _mesh_summary(csx_scope["mesh"])
        digest["ports"] = _port_numbers(csx_scope)
    except Exception as exc:
        digest = {**common, "status": "error",
                  "error": f"{type(exc).__name__}: {exc}"}
    _DIGEST_CACHE[key] = digest
    return copy.deepcopy(digest)


# ── 快照读写 ─────────────────────────────────────────────────────────────────


def _dump_yaml(digest: dict[str, Any]) -> str:
    # width 禁折行：plain scalar 在 CJK 中段折行时回读会补空格，
    # 破坏 guard_error 原文钉（逐字节相等判据）的往返保真。
    return yaml.safe_dump(
        digest, allow_unicode=True, sort_keys=False,
        default_flow_style=False, width=1_000_000)


def _load_golden(template: str) -> dict[str, Any] | None:
    path = golden_path(template)
    if not path.exists():
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _resolve_templates_arg(
    templates: str | list[str] | tuple[str, ...] | None,
) -> list[str]:
    """CLI 传 ""（未指定）或单族名或名单。"""
    if templates is None or templates == "" or templates == ():
        return sorted(TEMPLATE_META)
    if isinstance(templates, str):
        templates = [templates]
    return _template_list(list(templates))


# ── build / diff / accept ────────────────────────────────────────────────────


def build_template_golden(
    templates: str | list[str] | tuple[str, ...] | None = None,
    *, overwrite: bool = False,
) -> dict[str, Any]:
    """逐族计算+落盘 golden（已存在且未 overwrite → 跳过=断点续建）。

    返回 {templates, written, skipped_existing, blocked, errors, per_family}。
    guard_blocked 族同样落盘（status 忠实记录），不伪造哈希。
    """
    names = _resolve_templates_arg(templates)
    golden_dir().mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    skipped: list[str] = []
    blocked: list[str] = []
    errors: list[str] = []
    per_family: dict[str, dict[str, str]] = {}
    for name in names:
        path = golden_path(name)
        if path.exists() and not overwrite:
            skipped.append(name)
            per_family[name] = {"action": "skipped_existing"}
            continue
        digest = compute_template_digest(name)
        path.write_text(_dump_yaml(digest), encoding="utf-8")
        status = str(digest.get("status"))
        if status == "guard_blocked":
            blocked.append(name)
        elif status == "error":
            errors.append(name)
        written.append(name)
        per_family[name] = {"action": "written", "status": status}
    return {
        "templates": names,
        "n_total": len(names),
        "written": written,
        "skipped_existing": skipped,
        "guard_blocked": blocked,
        "errors": errors,
        "per_family": per_family,
    }


def _diff_one(stored: dict[str, Any], current: dict[str, Any]) -> list[str]:
    """单族 golden vs 当前 → 差异摘要行列表（空=无漂移）。"""
    diffs: list[str] = []
    if stored.get("status") != current.get("status"):
        diffs.append(f"status: {stored.get('status')!r} -> {current.get('status')!r}")
    if stored.get("params") != current.get("params"):
        diffs.append("params: 标称参数漂移（golden "
                     f"{stored.get('params')} -> 当前 {current.get('params')}）")
    if stored.get("mesh_resolution_mm") != current.get("mesh_resolution_mm"):
        diffs.append(f"mesh_resolution_mm: {stored.get('mesh_resolution_mm')}"
                     f" -> {current.get('mesh_resolution_mm')}")
    for key in ("script_sha256",):
        if stored.get(key) != current.get(key):
            diffs.append(f"{key}: {str(stored.get(key))[:12]}.. -> "
                         f"{str(current.get(key))[:12]}..")
    old_csx, new_csx = stored.get("csx"), current.get("csx")
    if old_csx != new_csx:
        if old_csx is None or new_csx is None:
            diffs.append(f"csx: {'缺失于golden' if old_csx is None else '缺失于当前'}")
        else:
            if old_csx.get("n_primitives") != new_csx.get("n_primitives"):
                diffs.append(f"csx.n_primitives: {old_csx.get('n_primitives')}"
                             f" -> {new_csx.get('n_primitives')}")
            old_props = {p.get("name"): p for p in old_csx.get("props", [])}
            new_props = {p.get("name"): p for p in new_csx.get("props", [])}
            for pname in sorted(set(old_props) | set(new_props)):
                o, n = old_props.get(pname), new_props.get(pname)
                if o != n:
                    diffs.append(f"csx.props[{pname}]: {o} -> {n}")
            if old_csx.get("bbox_m") != new_csx.get("bbox_m"):
                diffs.append(f"csx.bbox_m: {old_csx.get('bbox_m')} "
                             f"-> {new_csx.get('bbox_m')}")
            if old_csx.get("primitives_sha256") != new_csx.get("primitives_sha256"):
                diffs.append(f"primitives_sha256: "
                             f"{str(old_csx.get('primitives_sha256'))[:12]}.. -> "
                             f"{str(new_csx.get('primitives_sha256'))[:12]}..")
    old_mesh, new_mesh = stored.get("mesh"), current.get("mesh")
    if old_mesh != new_mesh:
        if old_mesh is None or new_mesh is None:
            diffs.append(f"mesh: {'缺失于golden' if old_mesh is None else '缺失于当前'}")
        else:
            old_l, new_l = old_mesh.get("lines"), new_mesh.get("lines")
            for axis in ("x", "y", "z"):
                if (old_l or {}).get(axis) != (new_l or {}).get(axis):
                    diffs.append(f"mesh.lines.{axis}: "
                                 f"{(old_l or {}).get(axis)} -> {(new_l or {}).get(axis)}")
            if old_mesh.get("lines_sha256") != new_mesh.get("lines_sha256"):
                diffs.append(f"mesh.lines_sha256: "
                             f"{str(old_mesh.get('lines_sha256'))[:12]}.. -> "
                             f"{str(new_mesh.get('lines_sha256'))[:12]}..")
    if stored.get("ports") != current.get("ports"):
        diffs.append(f"ports: {stored.get('ports')} -> {current.get('ports')}")
    for key in ("guard_error", "error"):
        if stored.get(key) != current.get(key):
            diffs.append(f"{key}: {str(stored.get(key))[:80]}.. -> "
                         f"{str(current.get(key))[:80]}..")
    return diffs


def diff_template_golden(
    templates: str | list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """当前渲染 vs golden 逐族对比（只读，零写盘）。

    返回 verdict=clean|drift|missing（clean=全部一致；missing=有族缺
    golden 文件）；drifts 为逐族差异摘要（人读定位面）。
    """
    names = _resolve_templates_arg(templates)
    drifts: dict[str, list[str]] = {}
    missing: list[str] = []
    clean: list[str] = []
    blocked_clean: list[str] = []
    errors: list[str] = []
    for name in names:
        stored = _load_golden(name)
        if stored is None:
            missing.append(name)
            continue
        current = compute_template_digest(name)
        if current.get("status") == "error":
            errors.append(name)
        diffs = _diff_one(stored, current)
        if diffs:
            drifts[name] = diffs
        else:
            clean.append(name)
            if current.get("status") == "guard_blocked":
                blocked_clean.append(name)
    if drifts:
        verdict = "drift"
    elif missing:
        verdict = "missing"
    elif errors:
        verdict = "error"
    else:
        verdict = "clean"
    return {
        "templates": names,
        "n_total": len(names),
        "n_clean": len(clean),
        "n_guard_blocked_clean": len(blocked_clean),
        "n_drift": len(drifts),
        "n_missing": len(missing),
        "n_error": len(errors),
        "verdict": verdict,
        "drifts": drifts,
        "missing": missing,
        "errors": errors,
        "clean": clean,
    }


def accept_template_golden(
    templates: str | list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """重生成 golden（显式意图门：接受当前渲染为新基线，防误吞真回归）。"""
    return build_template_golden(templates, overwrite=True)
