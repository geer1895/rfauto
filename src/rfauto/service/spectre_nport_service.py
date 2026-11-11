"""Spectre ``nport`` 交接片段生成服务（aurora_r R-18 / VB-9 IC 侧互操作位）。

EM 侧（rfauto 导出的 Touchstone sNp）→ IC 侧（Spectre 网表）的单行交接
件：读 sNp 嗅探端口数（rank 三规则，core/touchstone_parser 单源）→ 与
请求端口数/节点端子数一致性校验 → 生成 Spectre ``nport`` 实例行。

前置门证据（语法原文出处——docstring 引用即本服务语法唯一依据，禁凭
记忆扩展）：

- **主源（官方 Reference 原文，本席 2026-11-10 实测可达）**：
  ``Spectre Circuit Simulator Reference — Component Statements Part III``,
  September 2003, Product Version 5.0, (c) Cadence Design Systems, Inc.，
  镜像 URL ``http://eece.cu.edu.eg/~fhussien/Spectre_tutorial.pdf``
  （PDF 页 585-589 = 文档页 583-587，"Linear N Port (nport)" 节；
  目录条目 "Linear N Port (nport) ... 583"）。逐字引文：

  Instance Definition::

      Name  t1  b1  [t2]  [b2] ... ModelName parameter=value ...
      Name  t1  b1  [t2]  [b2] ... nport parameter=value ...
      Terminals must be given in pairs.

  Sample Instance Statement（model 引用形）::

      x1 (a1 0 b1 0 b3 0) ndata file="sparam2.data"

  Sample Model Statement::

      model ndata nport file="sparam.data" scale=1

  Instance Parameters（逐字）: ``file``——"S-parameter data file name."；
  ``datafmt``——"The format of the S-parameter data file. If this
  parameter is not given, Spectre will try to detect the format by
  itself. Possible values are spectre, touchstone or citi."；
  ``interp``——"Method to interpolate s-parameter data. Possible values
  are spline, rational or linear."；``scale=1``——"Frequency scale
  factor."。Description（逐字）："Each pair of terminals in the nport
  instance statement represents one port." / "the terminals must be
  given in pairs and there must be at least one pair. The order of the
  pairs is the same as the order of the ports in the data file. Any
  missing ports should be skipped." / "In addition to Spectre's native
  format, the S, Y, or Z-parameters can be in Touchstone or CITIfile
  format"。

- **旁证（2020 v19.1 官方 Reference，Analysis Statements 卷）**：镜像
  ``https://ee.kpi.ua/~yv/edu/ok/book/spectre_refManual.pdf``——全局
  option ``nport_default_interp`` "Possible values are spline, rational,
  linear, bbspice, and auto_switch"（interp 词表向后兼容）；sp 分析节
  "an ASCII model file that can later be read-in by a nport component"。
  本服务只产出 v5.0 逐字验证过的参数（file/datafmt/interp/scale），
  新版新增参数（bbspice/filetype 等）一律不产——官方原文未逐字核到
  新卷 Component Statements 前，禁凭二手转述扩展（R-18 前置门纪律；
  检索引擎摘要与论坛帖的 ``filetype=`` 形态属二手转述，不采）。

失败语义（#105/#122 显式不静默）：文件不存在/不可读/rank 冲突不可解
（宁 UNKNOWN 不误判，touchstone_service 同口径）/请求端口数≠文件端口
数/节点端子数≠2×端口数/词表外 datafmt/interp/非法实例名/路径含空白或
``$``/``"`` 字符（Spectre 网表按空白分词、``$`` 触发行注释，引号内
路径才安全）→ error 信封（errors 恒 list[str]）。

真机验收如实登记：本机无 Cadence/Spectre，生成片段**未经真 Spectre
运行验证**——信封 ``spectre_run_verified`` 恒 False + ``verification_
note`` 带 UNVERIFIED-LOCAL（VB-9 前置门原文要求）。

纯只读：不落盘、零网络、零真机、run 湖零写入；零新依赖（仅消费
core 解析器与 service/envelope）。本模块不设 ``__all__``（无 __all__
的非门面文件不进 tests/gold/public_api.json——touchstone_service/
sdf_service 同款先例，新模块零金快照漂移；公开名申报走席位任务书
public_api 申报制，由主代合流决定是否升格）。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from rfauto.core.spice_netlist_parser import (
    GROUND_ALIASES,
    parse_spice_netlist_text,
    parse_spice_number,
)
from rfauto.core.touchstone_parser import TouchstoneParseError, sniff_touchstone
from rfauto.service.envelope import error_envelope, ok_envelope

#: datafmt 词表（v5.0 官方逐字："Possible values are spectre, touchstone
#: or citi."）——缺省不产该参数（官方："Spectre will try to detect the
#: format by itself"）。
_DATAFMT_VOCAB = ("spectre", "touchstone", "citi")

#: interp 词表（v5.0 官方逐字："Possible values are spline, rational or
#: linear."）——缺省不产该参数（Spectre 内建缺省 spline）。
_INTERP_VOCAB = ("spline", "rational", "linear")

#: 实例名合法性（Spectre 标识符保守子集：字母开头，字母数字下划线）。
_INSTANCE_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")

#: 网表 token 危险字符：空白（分词）、``$``（行注释触发）、``"``（破坏
#: 引号包裹）。路径与节点名一律拒绝并显式报错（不静默改写）。
_TOKEN_UNSAFE_CHARS = ' \t\r\n\f\v$"'


def _token_unsafe(name: str, kind: str) -> str | None:
    """节点/路径 token 安全检查 → 违规原因（None=安全）。"""
    if not name:
        return f"{kind}为空串"
    if any(ch in _TOKEN_UNSAFE_CHARS for ch in name):
        return (
            f"{kind}含空白/$/引号字符（Spectre 网表按空白分词、$ 触发行"
            f"注释）: {name!r}"
        )
    return None


def _syntax_source_block() -> dict[str, Any]:
    """语法原文出处块（信封可溯源——docstring 同源，单一事实两处呈现）。"""
    return {
        "document": (
            "Spectre Circuit Simulator Reference — Component Statements "
            "Part III, September 2003, Product Version 5.0, "
            "(c) Cadence Design Systems, Inc."
        ),
        "section": "Linear N Port (nport)（文档页 583-587）",
        "url": "http://eece.cu.edu.eg/~fhussien/Spectre_tutorial.pdf",
        "instance_definition": (
            "Name  t1  b1  [t2]  [b2] ... nport parameter=value ... "
            "— Terminals must be given in pairs."
        ),
        "sample_instance_statement": 'x1 (a1 0 b1 0 b3 0) ndata file="sparam2.data"',
        "sample_model_statement": 'model ndata nport file="sparam.data" scale=1',
        "secondary_source": (
            "Spectre Circuit Simulator Reference — Analysis Statements, "
            "January 2020, Product Version 19.1 "
            "(https://ee.kpi.ua/~yv/edu/ok/book/spectre_refManual.pdf)："
            "nport_default_interp Possible values are spline, rational, "
            "linear, bbspice, and auto_switch（interp 词表向后兼容旁证）"
        ),
        "scope_note": (
            "只产出 v5.0 官方逐字验证参数（file/datafmt/interp/scale）；"
            "新版新增参数不产（官方原文未逐字核到前禁凭二手转述扩展）"
        ),
    }


def _verification_note() -> str:
    """UNVERIFIED-LOCAL 如实登记文案（VB-9 前置门原文要求）。"""
    return (
        "UNVERIFIED-LOCAL: 本机无 Cadence/Spectre，生成片段未经真 "
        "Spectre 运行验证；语法依据=官方 Reference v5.0 原文逐字引文"
        "（见 syntax_source），IC 侧首次使用时建议以 2 端口小网表冒烟"
        "核对端口配对与 file 参数解析"
    )


def generate_nport_instance(
    path: str | Path,
    *,
    instance_name: str = "nport1",
    expected_n_ports: int | None = None,
    nodes: Sequence[str] | None = None,
    ref_node: str = "gnd",
    datafmt: str | None = None,
    interp: str | None = None,
    scale: float | None = None,
) -> dict[str, Any]:
    """sNp 文件 → Spectre ``nport`` 实例行信封（ok/error 同构）。

    Args:
        path: Touchstone sNp 文件路径（文件参数按原样写入 ``file="..."``；
            含空白/``$``/``"`` → error 信封——网表分词与注释语法约束）。
        instance_name: 实例名（缺省 ``nport1``；字母开头标识符）。
        expected_n_ports: 请求端口数——给出时必须与文件 rank 一致，
            否则 error 信封（端口数一致性校验主体）。
        nodes: 显式端子表（扁平、按端口序两两成对：``[t1, b1, t2, b2,
            ...]``，官方 "Terminals must be given in pairs"）——长度必须
            = 2×文件端口数；缺省自动生成 ``p<i>`` + ``ref_node`` 占位
            （IC 侧按实际电路改名，信封 ``nodes`` 键承载可改写清单）。
        ref_node: 自动生成端子时的参考节点名（缺省 ``gnd``；round-trip
            解析按接地别名归一为 ``0``——解析器单源行为，信封如实回传）。
        datafmt: 可选 ``spectre|touchstone|citi``（v5.0 词表）；缺省不产
            （官方文档：Spectre 自动探测格式）。
        interp: 可选 ``spline|rational|linear``（v5.0 词表）；缺省不产。
        scale: 可选频率缩放因子（>0）；缺省不产。

    Returns:
        ok 信封：``snippet``（单行实例语句）、``instance_name``/``nodes``/
        ``params``/``n_ports``/``format``（Touchstone 版本+参考阻抗 r_ref
        等交接约定字段）/``roundtrip``（rfauto spectre 解析器往返自证）/
        ``syntax_source``（语法原文出处+逐字引文）/``spectre_run_verified``
        （恒 False）+ ``verification_note``（UNVERIFIED-LOCAL）。失败→
        error 信封（errors 恒 list[str]，附已获得的诊断字段）。
    """
    # —— 入参静态校验（与文件无关的先做，错误信息不混文件 IO 噪声）——
    if not _INSTANCE_NAME_RE.match(str(instance_name)):
        return error_envelope(
            f"实例名非法（需字母开头标识符）: {instance_name!r}",
            instance_name=str(instance_name),
        )
    if datafmt is not None and str(datafmt).lower() not in _DATAFMT_VOCAB:
        return error_envelope(
            f"datafmt={datafmt!r} 不在词表 {_DATAFMT_VOCAB}"
            "（官方 v5.0 逐字词表，禁凭记忆扩展）",
            instance_name=str(instance_name),
        )
    if interp is not None and str(interp).lower() not in _INTERP_VOCAB:
        return error_envelope(
            f"interp={interp!r} 不在词表 {_INTERP_VOCAB}"
            "（官方 v5.0 逐字词表，禁凭记忆扩展）",
            instance_name=str(instance_name),
        )
    if scale is not None:
        try:
            scale_val = float(scale)
        except (TypeError, ValueError):
            return error_envelope(f"scale 非数值: {scale!r}",
                                  instance_name=str(instance_name))
        if not scale_val > 0:
            return error_envelope(f"scale 必须为正数: {scale!r}",
                                  instance_name=str(instance_name))
    else:
        scale_val = None
    path_str = str(path)
    if (unsafe := _token_unsafe(path_str, "文件路径")) is not None:
        return error_envelope(unsafe, instance_name=str(instance_name))
    if (unsafe := _token_unsafe(str(ref_node), "参考节点名")) is not None:
        return error_envelope(unsafe, instance_name=str(instance_name),
                              ref_node=str(ref_node))

    # —— sNp 嗅探（端口数 rank 三规则单源；错误归一 error 信封）——
    try:
        sniff = sniff_touchstone(path)
    except TouchstoneParseError as exc:
        return error_envelope(f"Touchstone 嗅探失败: {exc}",
                              path=path_str,
                              instance_name=str(instance_name))
    rank = sniff["rank"]
    n_ports = rank["n_ports"]
    if n_ports is None:
        return error_envelope(
            "Touchstone rank 推断冲突/不可解（宁 UNKNOWN 不误判）——"
            "不产 nport 实例行",
            path=path_str,
            instance_name=str(instance_name),
            rank=rank,
        )
    n_ports = int(n_ports)

    # —— 端口数一致性校验（VB-9 验收主体）——
    if expected_n_ports is not None and int(expected_n_ports) != n_ports:
        return error_envelope(
            f"端口数不一致: 请求 {int(expected_n_ports)} vs 文件 "
            f"{n_ports}（{path_str}）",
            path=path_str,
            instance_name=str(instance_name),
            expected_n_ports=int(expected_n_ports),
            file_n_ports=n_ports,
        )

    # —— 端子表构建（官方："Terminals must be given in pairs"）——
    if nodes is not None:
        nodes_list = [str(n) for n in nodes]
        if len(nodes_list) != 2 * n_ports:
            return error_envelope(
                f"端子数不一致: 显式 nodes {len(nodes_list)} 个 vs "
                f"2×端口数 {2 * n_ports}（每端口信号+参考两两成对）",
                path=path_str,
                instance_name=str(instance_name),
                n_ports=n_ports,
                nodes=len(nodes_list),
            )
        for node in nodes_list:
            if (unsafe := _token_unsafe(node, "节点名")) is not None:
                return error_envelope(unsafe, path=path_str,
                                      instance_name=str(instance_name))
    else:
        nodes_list = []
        for i in range(1, n_ports + 1):
            nodes_list.append(f"p{i}")
            nodes_list.append(str(ref_node))

    # —— 片段生成（v5.0 Instance Definition 逐字形态）——
    params: dict[str, str] = {"file": f'"{path_str}"'}
    if datafmt is not None:
        params["datafmt"] = str(datafmt).lower()
    if interp is not None:
        params["interp"] = str(interp).lower()
    if scale_val is not None:
        params["scale"] = (
            str(int(scale_val)) if scale_val == int(scale_val)
            else repr(scale_val)
        )
    param_tail = " ".join(f"{k}={v}" for k, v in params.items())
    snippet = (
        f"{instance_name} ({' '.join(nodes_list)}) nport {param_tail}"
    )

    # —— 往返自证（best-effort 观测面：rfauto spectre 解析器还原逐项）——
    roundtrip = _roundtrip_block(snippet, instance_name, nodes_list,
                                 path_str, params)

    p = Path(path)
    return ok_envelope(
        instance_name=str(instance_name),
        path=path_str,
        path_abs=str(p.resolve()),
        master="nport",
        n_ports=n_ports,
        terminals_per_port=2,
        terminals=2 * n_ports,
        nodes=nodes_list,
        ref_node=str(ref_node),
        params=params,
        snippet=snippet,
        format={
            "version": sniff["version"],
            "freq_unit": sniff["freq_unit"],
            "param_type": sniff["param_type"],
            "data_format": sniff["data_format"],
            "r_ref": sniff["r_ref"],
        },
        rank={
            "n_ports": n_ports,
            "n_disagreements": len(rank["disagreements"]),
        },
        roundtrip=roundtrip,
        syntax_source=_syntax_source_block(),
        spectre_run_verified=False,
        verification_note=_verification_note(),
    )


def _roundtrip_block(
    snippet: str,
    instance_name: str,
    nodes_list: list[str],
    path_str: str,
    params: dict[str, str],
) -> dict[str, Any]:
    """生成片段 → rfauto spectre 解析器往返自证（best-effort 观测面）。

    还原核对：实例名/端子（接地别名归一后——解析器 ``gnd``→``0`` 单源
    行为，期望端子同法归一后再比）/master（``nport``——解析器未收录该
    master 时按 N 类兜底归档但 ``model`` 字段保留原名）/file 参数（引号
    剥离后与写入路径逐字一致）/其余参数（数值型经 SPICE 数值解析后
    比较——``scale=2`` 回读 2.0 与写入串 "2" 语义等值）。自证失败不改
    变 ok 语义（生成成立即 ok=True），``roundtrip.verified=False`` 如实
    回传。
    """
    parsed = parse_spice_netlist_text(snippet, "spectre")
    elements = parsed["elements"]
    if len(elements) != 1:
        return {
            "verified": False,
            "note": f"往返解析得 {len(elements)} 个元件（预期 1）",
        }
    el = elements[0]
    file_param = el["params"].get("file")
    nodes_normalized = [
        "0" if n.lower() in GROUND_ALIASES else n for n in nodes_list
    ]
    params_ok = True
    for k, v in params.items():
        if k == "file":
            continue
        got = el["params"].get(k)
        expected = parse_spice_number(v)
        if expected is None:
            expected = v
        params_ok = params_ok and got == expected
    checks = {
        "name": el["name"] == instance_name,
        "nodes": el["nodes"] == nodes_normalized,
        "master": el["model"] == "nport",
        "file_param": (
            isinstance(file_param, str)
            and file_param.strip('"') == path_str
        ),
        "params": params_ok,
    }
    return {
        "verified": all(checks.values()),
        "checks": checks,
        "name": el["name"],
        "nodes": el["nodes"],
        "master": el["model"],
        "params": dict(el["params"]),
        "kind": el["kind"],
        "n_parser_warnings": len(parsed["warnings"]),
    }
