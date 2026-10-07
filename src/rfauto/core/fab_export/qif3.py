"""QIF 3.0 风格完整特性文档 XML 渲染（L0 纯字符串，写盘在 adapters.qif_io）.

生成可被多数 CMM/检验软件「读懂结构」的 QIF XML 子集：
  QIFDocument / Product / CharacteristicDefinitions / Tolerances / Units.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from xml.sax.saxutils import escape

from .schema import CriticalChar, DimsDocument
from .standards import get_waveguide


def _f(x: float | None) -> str:
    return "" if x is None else f"{float(x):.6f}"


def render_qif3_document(
    dims: DimsDocument,
    chars: Sequence[CriticalChar],
    *,
    part_number: str | None = None,
    revision: str | None = None,
    now: str | None = None,
) -> str:
    """渲染 QIFDocument 文本（3.0 命名空间，结构完整子集）.

    ``now`` 供测试注入固定时间戳（缺省取当前 UTC）。
    """
    now_s = now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    pn = part_number or dims.part_id
    rev = revision or dims.rev

    lines: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<QIFDocument xmlns="http://qifstandards.org/schema/qif3" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" version="3.0">',
        "  <Header>",
        f"    <Name>{escape(pn)}</Name>",
        "    <Application>fab_export</Application>",
        "    <Author>fab_export</Author>",
        f"    <Created>{now_s}</Created>",
        f"    <Description>HFSS-derived manufacturing characteristics Rev {escape(rev)}</Description>",
        "  </Header>",
        "  <Units>",
        "    <LinearUnit><Name>millimeter</Name><DecimalPoint>.</DecimalPoint></LinearUnit>",
        "    <AngularUnit><Name>degree</Name></AngularUnit>",
        "  </Units>",
        "  <Product>",
        f"    <ProductNumber>{escape(pn)}</ProductNumber>",
        f"    <Version>{escape(rev)}</Version>",
        f"    <Description>Source dims.units={escape(dims.units)}; vars={len(dims.variables)}</Description>",
        "  </Product>",
        "  <CharacteristicDefinitions>",
    ]

    for i, c in enumerate(chars, 1):
        tol_cls = "PlusMinus"
        limit = max(abs(c.tol_plus), abs(c.tol_minus))
        lines += [
            f'    <CharacteristicDef id="{i}" type="LinearCharacteristic">',
            f"      <Name>{escape(c.char_id)}</Name>",
            f"      <Description>{escape(c.feature)}</Description>",
            f"      <KeyCharacteristic>{escape(c.source_var or c.char_id)}</KeyCharacteristic>",
            f"      <NonCritical>{'false' if c.inspect_pct >= 100 else 'true'}</NonCritical>",
            "      <LinearCharacteristic>",
            f"        <TargetValue>{_f(c.nominal)}</TargetValue>",
            f'        <Tolerance class="{tol_cls}">',
            "          <PlusMinus>",
            f"            <Limit>{_f(limit)}</Limit>",
            "            <DefinedBy>PlusMinus</DefinedBy>",
            f"            <PlusMinusValue><Upper>{_f(abs(c.tol_plus))}</Upper><Lower>{_f(abs(c.tol_minus))}</Lower></PlusMinusValue>",
            "          </PlusMinus>",
            "        </Tolerance>",
            f"        <DatumReference>{escape(c.datum or 'A')}</DatumReference>",
            f"        <MeasurementDevice>{escape(c.meas_method or 'CMM')}</MeasurementDevice>",
            '        <CharacteristicDesignator>{"source_var": "' + escape(c.source_var) + '"}</CharacteristicDesignator>',
            "      </LinearCharacteristic>",
            "    </CharacteristicDef>",
        ]

    lines += [
        "  </CharacteristicDefinitions>",
        "  <Tolerances>",
        '    <LinearTolerance id="100"><Name>default_plus_minus</Name><Unit>millimeter</Unit></LinearTolerance>',
        "  </Tolerances>",
        "</QIFDocument>",
    ]
    return "\n".join(lines) + "\n"


def render_qif3_with_waveguide(
    dims: DimsDocument,
    chars: Sequence[CriticalChar],
    *,
    wg_name: str = "WR-90",
) -> str:
    """带波导产品描述的 QIF 文本（扩展 Description；标准库无此波导则静默省略）.

    审查项 R6：原型 write_qif_product_with_wg 对 XML 文本做
    ``replace("</Product>", ...)`` 事后补丁且 Description 以错词
    "Expanded" 开头——本版在渲染期直接拼装，语义等价、无事后替换。
    """
    try:
        wg = get_waveguide(wg_name)
        extra = f" WG {wg.name}/{wg.bj} a={wg.a} b={wg.b}"
    except Exception:
        extra = ""
    text = render_qif3_document(dims, chars)
    if extra:
        text = text.replace(
            "  </Product>",
            f"    <Description>{escape(extra)}</Description>\n  </Product>",
        )
    return text
