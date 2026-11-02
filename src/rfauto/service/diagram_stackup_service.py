"""diagram_stackup_service —— PCB 叠层横截面图 .drawio 生成入口（T-O3 席，2026-11-01）。

"算画同源"第四件：声明式叠层（层卡 name/kind/thickness_mm/material/er +
可选线宽标注）→ 横截面 .drawio（层带高度∝厚度比例尺、材料/厚度/εr/zmin
标注、线宽双箭头标注）。

- 装配内核 = core/stackup_diagram.py（叠层校验/布局/标注文本）→
  core/drawio_xml.py（T-O2 通用 mxGraph XML 内核，零第三方依赖零 AGPL
  复制——mxGraph XML 格式开放规范）；
- 本模块只做：入参校验 → 线宽单源注入（可选）→ 内核调用 → 落盘 → JSON
  信封（规则 4：JSON 进出，CLI/MCP 是薄壳）。

线宽数字单源（铁律 7，"算画同源"）——**预声明选型**（2026-11-01 T-O3 席
实读签名后定）：

- ``core/synthesis.nominal_width_mm(z0_ohm, freq_ghz, stackup_name, *,
  digits=4, materials_path=None)`` 的层叠入参是 **materials.yaml 层叠键**
  而非 εr/h 直入——声明式层卡的 er/thickness 无法直接喂入（签名不合）；
- 另一单源 ``lossless_width_mm(z0, f, εr, h)`` 虽收 εr/h，但从声明层**自动
  推导**"哪层介质是参考基板"会对内层带状线（L3 夹在两介质间）静默套用
  微带闭式——模型错误（#1b 先验模型纪律），故**不做自动推导**；
- 选型：①内核线宽标注=用户显式给定值原样标注（铁律 7，零换算）；
  ②单源通道=**显式** materials.yaml 键调 ``nominal_width_mm``
  （:func:`synthesis_width_annotation`；数字逐位直通标注 dict，零手抄），
  信封逐条回显 ``source``（"input" / "synthesis.nominal_width_mm"）+
  合成入参（provenance）；③一致性守卫：合成层叠的 (εr, h) 与标注层
  **相邻**介质声明均不一致（或相邻介质缺 εr）→ warnings 如实提示
  （不改数字、不报错——宁可多报，#316 方向）。

确定性：同输入两次调用逐字节同文件（内核 XML 确定性 + 零时间戳）。
负例（空层/kind 非法/负厚度/引用不存在层/合成键未知等）显式报错——以
ok=False 错误信封出（CLI --json 消费同构信封；不静默、不凑绿）。

3D 等轴预览入口（aurora_p A5，2026-11-01）：:func:`generate_stackup_preview`
——同一叠层输入（RFStackup 实例 / RFStackup YAML 路径经 ``load_stackup`` /
T-O3 声明式 dict 三形态按类型分派）→ core/stackup_preview.py 装配计划 →
matplotlib PNG bytes → 落盘 → 信封（输出路径/层数/总厚/画布/sha256/逐层
回显/warnings）。**不入 ``__all__``**：tests/unit/test_stackup_diagram.py::
test_service_public_surface 钉死本模块 ``__all__`` 恰两名（A1 席重钉、
A5 席零改动门），显式 import 路径 ``from rfauto.service.
diagram_stackup_service import generate_stackup_preview`` 消费（CLI
``diagram stackup --preview`` 即此）。
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any

from rfauto.core.stackup_diagram import build_stackup_plan, format_number
from rfauto.core.stackup_preview import (
    build_preview_plan,
    preview_spec_from_declarative,
    preview_spec_from_rfstackup,
    render_preview_png,
)
from rfauto.core.synthesis import Stackup, nominal_width_mm
from rfauto.service.envelope import error_envelope, ok_envelope

__all__ = ["generate_stackup_diagram", "synthesis_width_annotation"]

#: 线宽标注来源标记（信封 provenance 回显单源）
SOURCE_INPUT = "input"
SOURCE_SYNTHESIS = "synthesis.nominal_width_mm"

#: 3D 预览数据源标记（信封 ``source`` 回显单源；按入参类型分派，不猜）
PREVIEW_SOURCE_RFSTACKUP = "rfstackup"
PREVIEW_SOURCE_RFSTACKUP_YAML = "rfstackup_yaml"
PREVIEW_SOURCE_DECLARATIVE = "declarative"

#: 合成规格严格键（layer/z0_ohm/freq_ghz/stackup_name 必填）
_SYNTH_KEYS = {"layer", "z0_ohm", "freq_ghz", "stackup_name", "digits",
               "note", "materials_path"}
_SYNTH_REQUIRED = ("layer", "z0_ohm", "freq_ghz", "stackup_name")

_WARN_SYNTH_MISMATCH = (
    "线宽标注 {i}（层 {layer!r}）合成层叠 {key!r}（εr={er}, h={h} mm）与"
    "相邻介质层声明不一致或相邻介质缺 εr——线宽数字仍为 nominal_width_mm "
    "单源原值，请核对叠层声明与合成层叠键是否对应")


def _positive_finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} 必须是实数，收到 {value!r}")
    out = float(value)
    if not math.isfinite(out) or out <= 0:
        raise ValueError(f"{name} 必须为 >0 有限实数，收到 {value!r}")
    return out


def _default_synth_note(z0_ohm: float, freq_ghz: float, stackup_name: str) -> str:
    """合成标注缺省 note（provenance 上图：阻抗@频点+单源函数+层叠键）。"""
    return (f"{format_number(z0_ohm)}Ω@{format_number(freq_ghz)}GHz "
            f"nominal_width_mm({stackup_name})")


def synthesis_width_annotation(
    layer: str,
    z0_ohm: float,
    freq_ghz: float,
    stackup_name: str,
    *,
    digits: int | None = 4,
    note: str | None = None,
    materials_path: str | Path | None = None,
) -> dict[str, Any]:
    """合成单源线宽标注：``nominal_width_mm`` 返回值逐位直通标注 dict。

    Args:
        layer: 标注目标层名（须为叠层中 signal/plane 层，内核校验）。
        z0_ohm: 目标阻抗（Ω，>0）。
        freq_ghz: 设计频点（GHz，>0）。
        stackup_name: configs/materials.yaml 层叠键（如 rogers4350b_h0.508）。
        digits: 舍入位数（缺省 4=标称档；None=原值精算）。
        note: 标注说明（None=缺省 provenance 串
            ``"<Z0>Ω@<f>GHz nominal_width_mm(<键>)"``）。
        materials_path: materials.yaml 路径（缺省走发现链）。

    Returns:
        ``{"layer": str, "width_mm": float, "note": str}``——width_mm 即
        ``nominal_width_mm(...)`` 返回值本身（零手抄零二次舍入）。

    Raises:
        ValueError: 入参非法/层叠键未知（KeyError 收敛为 ValueError，
            服务信封统一捕获）。
    """
    if not isinstance(layer, str) or not layer.strip():
        raise ValueError(f"layer 必须是非空字符串，收到 {layer!r}")
    if not isinstance(stackup_name, str) or not stackup_name.strip():
        raise ValueError(
            f"stackup_name 必须是非空字符串（materials.yaml 层叠键），收到 "
            f"{stackup_name!r}")
    z0 = _positive_finite(z0_ohm, "z0_ohm")
    freq = _positive_finite(freq_ghz, "freq_ghz")
    if digits is not None and (isinstance(digits, bool)
                               or not isinstance(digits, int) or digits < 0):
        raise ValueError(f"digits 必须是 ≥0 整数或 None，收到 {digits!r}")
    if note is not None and not isinstance(note, str):
        raise ValueError(f"note 必须是字符串，收到 {type(note)!r}")
    try:
        width = nominal_width_mm(z0, freq, stackup_name, digits=digits,
                                 materials_path=materials_path)
    except KeyError as exc:
        raise ValueError(f"合成层叠键未知：{exc}") from exc
    return {
        "layer": layer,
        "width_mm": width,
        "note": note if note is not None else _default_synth_note(
            z0, freq, stackup_name),
    }


def _normalize_synth_specs(width_synthesis: Any) -> list[dict[str, Any]]:
    """合成规格 → 严格键列表（单 dict 或 dict 列表；负例显式 ValueError）。"""
    if isinstance(width_synthesis, dict):
        raw_specs = [width_synthesis]
    elif isinstance(width_synthesis, (list, tuple)):
        raw_specs = list(width_synthesis)
    else:
        raise ValueError(
            f"width_synthesis 必须是 dict 或 dict 列表，收到 "
            f"{type(width_synthesis)!r}")
    specs: list[dict[str, Any]] = []
    for i, raw in enumerate(raw_specs):
        where = f"width_synthesis[{i}]"
        if not isinstance(raw, dict):
            raise ValueError(f"{where} 必须是 dict，收到 {type(raw)!r}")
        extra = set(raw) - _SYNTH_KEYS
        if extra:
            raise ValueError(
                f"{where} 存在未支持键 {sorted(extra)}；合成规格 schema 严格键 "
                f"{sorted(_SYNTH_KEYS)}")
        for key in _SYNTH_REQUIRED:
            if key not in raw or raw[key] is None:
                raise ValueError(f"{where} 缺必填键 {key!r}")
        specs.append(dict(raw))
    return specs


def _synth_mismatch_warnings(
    stackup: dict[str, Any],
    synth_items: list[tuple[int, dict[str, Any]]],
) -> list[str]:
    """合成层叠 (εr, h) vs 标注层相邻介质声明一致性守卫（warnings，不改数字）。

    synth_items: [(全局标注序号, 归一合成规格), ...]。相邻=标注层前/后
    一层且 kind=dielectric；任一相邻介质 εr 与 h 同时与合成层叠一致
    （isclose rel 1e-9）即视为对应，否则提示。
    """
    layers = stackup.get("layers") or []
    by_name = {lay.get("name"): k for k, lay in enumerate(layers)
               if isinstance(lay, dict)}
    ws: list[str] = []
    for gidx, spec in synth_items:
        st = Stackup.from_materials_yaml(spec["stackup_name"],
                                         spec.get("materials_path"))
        k = by_name.get(spec["layer"])
        matched = False
        for nb in (k - 1, k + 1) if k is not None else ():
            if not 0 <= nb < len(layers):
                continue
            lay = layers[nb]
            if lay.get("kind") != "dielectric" or lay.get("er") is None:
                continue
            if (math.isclose(float(lay["er"]), st.epsilon_r, rel_tol=1e-9)
                    and math.isclose(float(lay["thickness_mm"]),
                                     st.thickness_mm, rel_tol=1e-9)):
                matched = True
                break
        if not matched:
            ws.append(_WARN_SYNTH_MISMATCH.format(
                i=gidx, layer=spec["layer"], key=spec["stackup_name"],
                er=format_number(st.epsilon_r),
                h=format_number(st.thickness_mm)))
    return ws


def generate_stackup_diagram(
    stackup: Any,
    out_path: Any,
    *,
    title: str | None = None,
    width_synthesis: Any = None,
) -> dict[str, Any]:
    """生成 PCB 叠层横截面图 .drawio 文件（声明式叠层 → 原生可编辑工程图）。

    Args:
        stackup: 声明式叠层 dict（顶层三键 title/layers/width_annotations；
            层卡严格五键 name/kind/thickness_mm/material/er、线宽标注严格
            三键 layer/width_mm/note——schema 全文见
            core/stackup_diagram.normalize_stackup）。
        out_path: 输出 .drawio 路径（父目录须已存在；不自动建目录——
            路径错误显式报错而非静默补救）。
        title: 图标题（None 用叠层 title，再 None 用内核缺省标题）。
        width_synthesis: 可选合成单源线宽规格（dict 或 dict 列表，严格键
            layer/z0_ohm/freq_ghz/stackup_name/digits/note/materials_path；
            前四必填）——每条经 :func:`synthesis_width_annotation` 调
            ``nominal_width_mm`` 生成标注，追加在用户 width_annotations 之后。

    Returns:
        成功信封::

            {"ok": True, "out_path": str,
             "n_layers": int, "n_width_annotations": int,
             "layers": [{index, name, kind, thickness_mm, material, er,
                         zmin_mm, height_px}, ...],
             "width_annotations": [{index, layer, width_mm, note, source,
                                    synthesis?}, ...],
             "warnings": [str, ...]}

        ``source`` = "input"（用户显式值原样）/ "synthesis.nominal_width_mm"
        （合成单源；附 ``synthesis`` 入参回显）。失败信封（校验负例/IO
        错误/合成键未知）：``{"ok": False, "errors": [str...]}``。
    """
    synth_specs: list[dict[str, Any]] = []
    n_user = 0
    try:
        payload = stackup
        if width_synthesis is not None:
            synth_specs = _normalize_synth_specs(width_synthesis)
            if not isinstance(stackup, dict):
                raise ValueError(
                    f"stackup 必须是 dict，收到 {type(stackup)!r}")
            base = stackup.get("width_annotations") or []
            if not isinstance(base, (list, tuple)):
                raise ValueError("stackup.width_annotations 必须是列表")
            n_user = len(base)
            synth_anns = [synthesis_width_annotation(
                spec["layer"], spec["z0_ohm"], spec["freq_ghz"],
                spec["stackup_name"], digits=spec.get("digits", 4),
                note=spec.get("note"),
                materials_path=spec.get("materials_path"))
                for spec in synth_specs]
            payload = {**stackup, "width_annotations": [*base, *synth_anns]}
        plan = build_stackup_plan(payload, title=title)
        if not synth_specs:
            # 无合成规格：全部标注=用户显式值（计数取内核校验后的归一面）
            n_user = plan["n_width_annotations"]
        warnings = list(plan["warnings"])
        if synth_specs:
            warnings.extend(_synth_mismatch_warnings(
                payload, [(n_user + j, spec)
                          for j, spec in enumerate(synth_specs)]))
        out = Path(out_path)  # PathLike 入参第一行收敛（#140）
        if out.parent and not out.parent.exists():
            raise ValueError(
                f"输出目录不存在：{out.parent}（请先建目录，不自动补救）")
        out.write_text(plan["xml"], encoding="utf-8")
    except (ValueError, TypeError, OSError) as exc:
        return error_envelope(f"{type(exc).__name__}: {exc}")

    widths: list[dict[str, Any]] = []
    for ann in plan["width_annotations"]:
        entry = dict(ann)
        if ann["index"] < n_user:
            entry["source"] = SOURCE_INPUT
        else:
            spec = synth_specs[ann["index"] - n_user]
            entry["source"] = SOURCE_SYNTHESIS
            entry["synthesis"] = {
                "z0_ohm": spec["z0_ohm"], "freq_ghz": spec["freq_ghz"],
                "stackup_name": spec["stackup_name"],
                "digits": spec.get("digits", 4),
            }
        widths.append(entry)

    return ok_envelope(
        out_path=str(out),
        n_layers=plan["n_layers"],
        n_width_annotations=plan["n_width_annotations"],
        layers=plan["layers"],
        width_annotations=widths,
        warnings=warnings,
    )


# ─── 3D 等轴预览（aurora_p A5） ──────────────────────────────────────────────

#: 信封逐层回显键（装配计划的数值/文本面；faces/colors 几何面不进信封）
_PREVIEW_LAYER_ECHO_KEYS = (
    "index", "name", "kind", "material", "er", "thickness", "thickness_text",
    "zmin", "zmax", "zmin_source", "height_px", "label",
)


def _preview_spec(stackup: Any) -> tuple[dict[str, Any], str, str | None]:
    """入参三形态 → (spec, source 标记, 叠层文件路径或 None)；类型不认显式报错。"""
    if isinstance(stackup, (str, Path)):
        from rfauto.adapters.layout_stack import load_stackup  # lazy: run-path（执行面按需取用）

        typed = Path(stackup)
        return (preview_spec_from_rfstackup(load_stackup(typed)),
                PREVIEW_SOURCE_RFSTACKUP_YAML, str(typed))
    if isinstance(stackup, dict):
        return preview_spec_from_declarative(stackup), PREVIEW_SOURCE_DECLARATIVE, None
    if hasattr(stackup, "layers"):
        return preview_spec_from_rfstackup(stackup), PREVIEW_SOURCE_RFSTACKUP, None
    raise ValueError(
        f"stackup 必须是 RFStackup 实例 / RFStackup YAML 路径 / T-O3 声明式 dict，"
        f"收到 {type(stackup)!r}")


def generate_stackup_preview(
    stackup: Any,
    out_path: Any,
    *,
    title: str | None = None,
) -> dict[str, Any]:
    """生成 PCB 叠层 3D 等轴预览 PNG（报告附件/快速视检件；非可编辑工程图）。

    Args:
        stackup: 三形态按类型分派（不猜）：RFStackup 实例（adapters/
            layout_stack，zmin_m/thickness_m 米制逐层原值直通）；``str``/
            ``Path`` = RFStackup YAML 路径（``load_stackup`` 读入）；``dict``
            = T-O3 声明式叠层（与 :func:`generate_stackup_diagram` 同一输入，
            slab 底 z 由布局几何得出，信封 ``zmin_source="layout"`` 如实
            标记）。
        out_path: 输出 .png 路径（父目录须已存在；不自动建目录）。
        title: 图标题（None 用叠层名/title，再 None 用内核缺省 ASCII 标题；
            非 ASCII 字符在图内 ``\\uXXXX`` 转义并 warnings 提示）。

    Returns:
        成功信封::

            {"ok": True, "out_path": str, "source": str, "stackup_path": str|None,
             "unit": "m"|"mm", "n_layers": int,
             "total_thickness": float, "total_thickness_text": str,
             "title": str, "canvas": {"w_px": int, "h_px": int},
             "png_bytes": int, "png_sha256": str,
             "layers": [{index, name, kind, material, er, thickness,
                         thickness_text, zmin, zmax, zmin_source, height_px,
                         label}, ...],
             "warnings": [str, ...]}

        数字口径（铁律 7）：thickness/zmin/er = 输入原值；total_thickness =
        Σthickness 确定性加法；height_px = thickness × Z 比例尺（几何映射）。
        失败信封（spec 违约/零厚度层/YAML 缺失/画布超限/matplotlib 缺席/IO
        错误）：``{"ok": False, "errors": [str...]}``——不落盘。
    """
    try:
        spec, source, stackup_path = _preview_spec(stackup)
        plan = build_preview_plan(spec, title=title)
        png = render_preview_png(plan)
        out = Path(out_path)  # PathLike 入参第一行收敛（#140）
        if out.parent and not out.parent.exists():
            raise ValueError(
                f"输出目录不存在：{out.parent}（请先建目录，不自动补救）")
        out.write_bytes(png)
    except (ValueError, TypeError, OSError, RuntimeError) as exc:
        return error_envelope(f"{type(exc).__name__}: {exc}")

    return ok_envelope(
        out_path=str(out),
        source=source,
        stackup_path=stackup_path,
        unit=plan["unit"],
        n_layers=plan["n_layers"],
        total_thickness=plan["total_thickness"],
        total_thickness_text=plan["total_thickness_text"],
        title=plan["title"],
        canvas={"w_px": plan["canvas"]["w_px"], "h_px": plan["canvas"]["h_px"]},
        png_bytes=len(png),
        png_sha256=hashlib.sha256(png).hexdigest(),
        layers=[{k: lay[k] for k in _PREVIEW_LAYER_ECHO_KEYS}
                for lay in plan["layers"]],
        warnings=list(plan["warnings"]),
    )
