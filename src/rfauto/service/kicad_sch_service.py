"""KiCad 原理图生成 + 一致性闭环服务面（T-Q22，JSON 进出，规则 4）。

编排三层（adapters/kicad_sch_gen 纯 s-expr 面之上）：

1. **SchSpec schema**（Pydantic 严格契约）：``components[{ref,value,lib_id,
   footprint?,pins?}] + nets[{name, pins:[{ref,pin}]}]``——任务书钉死的最小
   可用形态（仓内既有网表形态侦察结论：compose 的 rfauto-netlist-v1 是 RF
   模板专用 connections 对形态，不含元件/引脚字典，故 T-Q22 自立 SchSpec；
   后续如需互通，在此加投影函数，不改 compose）；
2. **生成 + round-trip 二值证书**（Weave 思想）：render → 落盘 →
   :func:`rfauto.adapters.kicad_sch_gen.readback_nets` 独立回读 → 与 SchSpec
   逐 net 比对 → ``{pass, diff}``——证书 PASS 是"生成正确"的确定性判据，
   生成器几何 bug（stub 落错脚/label 错名/槽位碰撞）必然现形。比对 fold
   走通用件 :mod:`rfauto.service.roundtrip_certificate`（T-Q23 显性化：
   三族 diff 确定性排序+pass 判定单源；kicad 词表经 DiffNaming 注入，
   同输入证书逐字节同——runs/aurora_q/qcad2/ 快照双跑实证）；
3. **kicad-cli ERC 子进程**（铁律 2 同型：CLI 可执行文件子进程，不 import
   pcbnew）：``kicad-cli sch erc --exit-code-violations`` → exit code 口径
   （KiCad 10.0.6 实测：0=无违例；**5=存在违例**（错误或警告）；
   3=原理图加载失败）→ :func:`parse_erc_report` 解析 rpt → 信封计数。

诚实边界（本席交付范围）：生成器+ERC 解析+证书+单测；**智能布局/SchGen
LLM 生成/DRC ``--schematic-parity`` 全闭环=后续席位**（parity 需 .kicad_pcb
配对工程，登记衔接点：生成面落此处的 out_path，PCB 面由 layout 家族接）。
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from rfauto.adapters.kicad_sch_gen import (
    GenComponent,
    GenNet,
    SchGridLayout,
    parse_erc_report,
    readback_nets,
    render_schematic,
)
from rfauto.service.envelope import error_envelope, ok_envelope, skipped_envelope
from rfauto.service.roundtrip_certificate import DiffNaming, fold_diff, is_pass

__all__ = [
    "ERC_EXIT_LOAD_FAILED",
    "ERC_EXIT_VIOLATIONS",
    "SCH_SPEC_SCHEMA",
    "SchComponent",
    "SchNet",
    "SchPinRef",
    "SchSpec",
    "generate_schematic",
    "round_trip_certificate",
    "run_erc",
    "spec_to_gen",
]

#: SchSpec 载荷 schema 串（与 compose 的 rfauto-netlist-v1 同惯例）。
SCH_SPEC_SCHEMA = "rfauto-sch-spec-v1"

#: kicad-cli ``sch erc --exit-code-violations`` 下"存在违例"的退出码
#: （KiCad 10.0.6 实测；0=无违例）。
ERC_EXIT_VIOLATIONS = 5
#: 原理图加载失败的退出码（KiCad 10.0.6 实测）。
ERC_EXIT_LOAD_FAILED = 3


# ---------------------------------------------------------------------------
# SchSpec schema（Pydantic 严格契约；extra=forbid 抓拼写漂移）
# ---------------------------------------------------------------------------


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SchPinRef(_Strict):
    """网络内引脚引用（元件位号 + 引脚号）。"""

    ref: str = Field(min_length=1)
    pin: str = Field(min_length=1)


class SchComponent(_Strict):
    """元件（位号/值/lib_id/可选封装/可选显式引脚集）。"""

    ref: str = Field(min_length=1)
    value: str = ""
    lib_id: str = Field(min_length=1)
    footprint: str = ""
    #: 显式额外引脚号（∪ nets 引用集）；缺省=完全从 nets 推导。
    pins: list[str] = Field(default_factory=list)


class SchNet(_Strict):
    """网络（名 + 引脚引用表；≥1 引脚）。"""

    name: str = Field(min_length=1)
    pins: list[SchPinRef] = Field(min_length=1)

    @field_validator("pins")
    @classmethod
    def _pins_unique(cls, v: list[SchPinRef]) -> list[SchPinRef]:
        seen: set[tuple[str, str]] = set()
        for p in v:
            key = (p.ref, p.pin)
            if key in seen:
                raise ValueError(f"net 内引脚重复: {key}")
            seen.add(key)
        return v


class SchSpec(_Strict):
    """原理图规格（元件表 + 网络表；round-trip 证书的真值源）。"""

    components: list[SchComponent] = Field(min_length=1)
    nets: list[SchNet] = Field(default_factory=list)

    @field_validator("components")
    @classmethod
    def _refs_unique(cls, v: list[SchComponent]) -> list[SchComponent]:
        seen: set[str] = set()
        for c in v:
            if c.ref in seen:
                raise ValueError(f"元件位号重复: {c.ref!r}")
            seen.add(c.ref)
        return v

    @field_validator("nets")
    @classmethod
    def _nets_unique(cls, v: list[SchNet]) -> list[SchNet]:
        seen: set[str] = set()
        for n in v:
            if n.name in seen:
                raise ValueError(f"网络名重复: {n.name!r}")
            seen.add(n.name)
        return v


def spec_from_payload(payload: SchSpec | dict[str, Any]) -> SchSpec:
    """dict 载荷 → SchSpec（钉 schema 串；Pydantic 模型直通）。

    dict 形态必须带 ``schema == "rfauto-sch-spec-v1"``（与 compose
    rfauto-netlist-v1 同惯例，防形态漂移静默张冠李戴）；SchSpec 实例直通。
    """
    if isinstance(payload, SchSpec):
        return payload
    if not isinstance(payload, dict):
        raise ValueError(
            f"spec 载荷必须为 dict/SchSpec: {type(payload).__name__}")
    if str(payload.get("schema")) != SCH_SPEC_SCHEMA:
        raise ValueError(
            f"spec schema 必须为 {SCH_SPEC_SCHEMA!r}，得到 "
            f"{payload.get('schema')!r}")
    body = {k: v for k, v in payload.items() if k != "schema"}
    return SchSpec.model_validate(body)


def spec_to_gen(spec: SchSpec) -> tuple[list[GenComponent], list[GenNet]]:
    """SchSpec → 生成器投影（GenComponent/GenNet；net 内引用越界在此拦截）。"""
    refs = {c.ref for c in spec.components}
    for net in spec.nets:
        for p in net.pins:
            if p.ref not in refs:
                raise ValueError(
                    f"net {net.name!r} 引用未声明元件 {p.ref!r}")
    comps = [GenComponent(ref=c.ref, value=c.value, lib_id=c.lib_id,
                          footprint=c.footprint, pins=tuple(c.pins))
             for c in spec.components]
    nets = [GenNet(name=n.name, pins=tuple((p.ref, p.pin) for p in n.pins))
            for n in spec.nets]
    return comps, nets


# ---------------------------------------------------------------------------
# round-trip 二值证书（Weave 思想；比对 fold=通用件 T-Q23 复用）
# ---------------------------------------------------------------------------

#: kicad 词表（三族 kind 名 + 字段名与 T-Q22 既有证书逐字段同形——
#: 零行为变化锚：同输入证书逐字节同）。
_KICAD_DIFF_NAMING = DiffNaming(
    key_name="net",
    missing_kind="missing_net",
    extra_kind="extra_net",
    mismatch_kind="pin_mismatch",
    expected_items_name="expected_pins",
    readback_items_name="readback_pins",
    mismatch_missing_items_name="missing_pins",
    mismatch_extra_items_name="extra_pins",
)


def round_trip_certificate(spec: SchSpec | dict[str, Any],
                           sch_text: str) -> dict[str, Any]:
    """生成文本回读 vs SchSpec 逐 net 比对 → 二值证书（不凑绿）。

    返回 ``{pass, diff, n_nets_expected, n_nets_readback, unnamed_pins}``；
    diff 条目形态：``missing_net``（spec 有回读无）/ ``extra_net``（回读有
    spec 无）/ ``pin_mismatch``（同名 net 引脚集不等，symmetric diff 逐侧
    列出）——全部确定性排序（同输入同 diff；fold=通用件单源）。
    """
    sp = spec_from_payload(spec)
    expected: dict[str, list[tuple[str, str]]] = {}
    for net in sp.nets:
        expected[net.name] = sorted((p.ref, p.pin) for p in net.pins)
    rb = readback_nets(sch_text)
    diff = fold_diff(expected, rb.nets, naming=_KICAD_DIFF_NAMING)
    return {"pass": is_pass(diff), "diff": diff,
            "n_nets_expected": len(expected), "n_nets_readback": len(rb.nets),
            "unnamed_pins": rb.unnamed_pins}


# ---------------------------------------------------------------------------
# 生成编排（信封进出）
# ---------------------------------------------------------------------------


def generate_schematic(
    spec: SchSpec | dict[str, Any],
    out_path: str | Path,
    *,
    layout: SchGridLayout | None = None,
    certificate: bool = True,
) -> dict[str, Any]:
    """SchSpec → .kicad_sch 落盘 + round-trip 证书（信封返回）。

    Args:
        spec: SchSpec / dict 载荷（schema 串钉校验）。
        out_path: 输出 .kicad_sch 路径（父目录必须已存在）。
        layout: 声明式网格布局参数（缺省=SchGridLayout() 单源钉）。
        certificate: 生成后是否跑 round-trip 证书（缺省 True；False 仅
          生成——供诊断绕过，正式路径恒带证书）。

    Returns:
        ok 信封：``out_path/bytes/n_components/n_nets/certificate``；
        证书 FAIL 时 **ok=True 但 certificate.pass=False**（生成动作成立、
        一致性不达标如实上报——消费方以 certificate.pass 为准）；
        输入非法 → error 信封。
    """
    try:
        sp = spec_from_payload(spec)
        comps, nets = spec_to_gen(sp)
        text = render_schematic(comps, nets, layout)
    except (ValueError, TypeError) as exc:
        return error_envelope(f"SchSpec 非法: {exc}")
    out = Path(out_path)
    try:
        out.write_text(text, encoding="utf-8", newline="\n")
    except OSError as exc:
        return error_envelope(f"写出失败 {out}: {exc}")
    cert: dict[str, Any] | None = None
    if certificate:
        cert = round_trip_certificate(sp, text)
    return ok_envelope(
        out_path=str(out),
        bytes=len(text.encode("utf-8")),
        n_components=len(sp.components),
        n_nets=len(sp.nets),
        certificate=cert,
    )


# ---------------------------------------------------------------------------
# kicad-cli ERC 子进程封装
# ---------------------------------------------------------------------------


def run_erc(
    sch_path: str | Path,
    *,
    cli_path: str | Path | None = None,
    timeout_s: float = 120.0,
    exit_code_violations: bool = True,
) -> dict[str, Any]:
    """``kicad-cli sch erc`` 子进程 → rpt 解析 → 信封（单测全 mock）。

    退出码口径（KiCad 10.0.6 实测，runs/aurora_q/qcad1_smoke/）：
    - ``0``=无违例；``5``=存在违例（``--exit-code-violations`` 下，错误或
      警告均算；缺省开启与任务书"exit 5=有错误"口径对齐）；``3``=原理图
      加载失败。其余退出码如实透传 ``exit_code`` 不强判。

    信封语义：ERC 运行成立（rc 0/5）= **ok=True**，违例计数在
    ``error_count/warning_count``（违例不是服务失败）；rc=3 → **ok=False**
    （加载失败=通道故障）；kicad-cli 未找到 → skipped 信封（前置不满足）。
    """
    from rfauto.service.layout_step_service import resolve_kicad_cli

    sch = Path(sch_path)
    if not sch.is_file():
        return error_envelope(f"原理图文件不存在: {sch}")
    cli = resolve_kicad_cli(cli_path)
    if cli is None:
        return skipped_envelope("kicad-cli 未找到（设 RFAUTO_KICAD_CLI 或安装 KiCad）")
    rpt = sch.with_suffix(".erc.rpt")
    args = [str(cli), "sch", "erc", "--output", str(rpt)]
    if exit_code_violations:
        args.append("--exit-code-violations")
    args.append(str(sch))
    try:
        proc = subprocess.run(args, capture_output=True, text=True,
                              timeout=timeout_s, check=False)
    except subprocess.TimeoutExpired:
        return error_envelope(f"kicad-cli sch erc 超时（{timeout_s}s）: {sch}")
    except OSError as exc:
        return error_envelope(f"kicad-cli 启动失败: {exc}")
    if proc.returncode == ERC_EXIT_LOAD_FAILED:
        return error_envelope(
            f"kicad-cli 原理图加载失败（exit {proc.returncode}）: {sch}",
            exit_code=proc.returncode,
            stderr=(proc.stderr or "").strip() or None)
    parsed = parse_erc_report(rpt.read_text(encoding="utf-8")
                              if rpt.is_file() else "")
    fields: dict[str, Any] = dict(
        exit_code=proc.returncode,
        report_path=str(rpt) if rpt.is_file() else None,
        **{k: v for k, v in parsed.items() if k != "ok"})
    if not parsed.get("ok"):
        # rc 0/5 但报告解析失败（格式漂移）——如实降级 error（不伪造计数）
        return error_envelope(
            parsed.get("errors") or ["ERC 报告解析失败"], **fields)
    return ok_envelope(**fields)
