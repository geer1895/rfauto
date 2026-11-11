"""citi_service：CITIfile 结构化解析的服务包装（aurora_q 席位 Q-X35）。

规则 4 服务层 JSON 进出单源：core/citi_parser（纯内核，Q-X35 单源）的
结构化输出经本层三函数转 JSON 信封；CLI/MCP 是薄壳。信封一律走
envelope 构造器（AU-2 契约，禁裸 dict）。

- :func:`citi_info`       包级结构化信息（header/version/segments 概览 +
  可选完整值表）——解析失败=error 信封（非 CITI 文件不猜）；
- :func:`citi_read_segments` 数据段解码值读取（按段名过滤；complex 值
  JSON 形态=[re, im] 对；undecodable 段带 raw_records 与
  decode_status）；
- :func:`citi_network_probe` skrf 桥接探针：CITI 内嵌 S 参数数据段 →
  skrf.Network 组装（可选功能——**条件匹配时才可桥**）。桥接条件全列
  预声明：S[i,j] 复数值段齐套（方阵全元存在）、独立变量（频率）值表
  存在、除频率外无多值扫描参数；任一不满足 → skipped 信封如实给
  reason（不产半成品 Network）。z0 取 PortZ[k]/Zo[k] 值段（有则用，
  无则缺省 50Ω 并在信封注明来源）。skrf 惰性导入（cli 叶延迟导入同
  款纪律）；仅读不写（观测面，#105）。

零真机零网络（#139 族）：全离线纯解析；不落盘任何文件（除调用方显式
传路径的读取）。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from rfauto.core.citi_parser import (
    PARSER_SCHEMA_VERSION,
    CitiPackage,
    CitiParseError,
    package_to_dict,
    parse_citi_file,
    segment_to_dict,
)
from rfauto.service.envelope import error_envelope, ok_envelope, skipped_envelope

__all__ = [
    "citi_info",
    "citi_network_probe",
    "citi_read_segments",
]

#: skrf 桥接可识别的端口阻抗段名形态（PortZ[k] / PORTZ[k] / Zo[k]）
_PORTZ_RE = re.compile(r"^(?:PortZ|PORTZ|Zo)\[(\d+)\]$")
#: S 参数段名形态（S[i,j] 与 1 端口裸 S）
_S_MATRIX_RE = re.compile(r"^S\[(\d+),(\d+)\]$")


def _load_packages(path: str | Path) -> tuple[list[CitiPackage], None] | tuple[
        None, dict[str, Any]]:
    """读+解析 → (packages, None) 或 (None, error_envelope)。"""
    p = Path(path)
    if not p.exists():
        return None, error_envelope(f"CITI 文件不存在: {p}")
    try:
        return parse_citi_file(p), None
    except CitiParseError as exc:
        return None, error_envelope(f"CITI 解析失败: {exc}")


def citi_info(path: str | Path, *, max_values: int | None = None) -> dict:
    """包级结构化信息信封。

    ``max_values``：单值列截断上限（None=不截断）；截断时该列带
    ``values_truncated: true`` 与 ``n_values`` 全量计数——概览面不整列
    打印时防信封膨胀，截断是显式声明的（不冒充完整）。

    信封含 ``schema="citi/<N.0>"`` 自描述复合键（R-22 schema 升位批
    补键；解析产物为包列表，键由信封携带——skill_service 同款先例）。
    """
    packages, err = _load_packages(path)
    if err is not None:
        return err
    dicts = [package_to_dict(pkg, package_index=i, n_packages=len(packages))
             for i, pkg in enumerate(packages)]
    if max_values is not None:
        for d in dicts:
            for var in d["variables"]:
                if var["values"] is not None and len(var["values"]) > max_values:
                    var["values"] = var["values"][:max_values]
                    var["values_truncated"] = True
            for seg in d["segments"]:
                for dep in seg["dependent_vars"]:
                    if dep["values"] and len(dep["values"]) > max_values:
                        dep["values"] = dep["values"][:max_values]
                        dep["values_truncated"] = True
                iv = seg["independent_var"]
                if iv is not None and iv["values"] and len(iv["values"]) > max_values:
                    iv["values"] = iv["values"][:max_values]
                    iv["values_truncated"] = True
    summary = [{
        "version": d["version"],
        "version_keyword": d["version_keyword"],
        "name": d["name"],
        "n_segments": len(d["segments"]),
        "n_warnings": len(d["metadata"]["warnings"]),
        "segment_names": [s["var_name"] for s in d["segments"]],
    } for d in dicts]
    return ok_envelope(path=str(path),
                       schema=f"citi/{PARSER_SCHEMA_VERSION}",
                       packages=dicts, n_packages=len(dicts),
                       summary=summary)


def citi_read_segments(
    path: str | Path,
    names: list[str] | None = None,
    *,
    include_raw: bool = False,
) -> dict:
    """数据段解码值读取信封（按段名过滤，None=全段）。

    ``include_raw``：undecodable 段是否带 raw_records（缺省 False——
    概览消费方只要状态；要原文显式声明）。未命中的段名如实回显。
    """
    packages, err = _load_packages(path)
    if err is not None:
        return err
    wanted = [n for n in (names or [])]
    segments: list[dict] = []
    for i, pkg in enumerate(packages):
        for seg in pkg.segments:
            sd = segment_to_dict(seg)
            sd["package_index"] = i
            if wanted and sd["var_name"] not in wanted:
                continue
            if not include_raw:
                sd.pop("raw_records", None)
            segments.append(sd)
    missing = [n for n in wanted
               if n not in {s["var_name"] for s in segments}]
    return ok_envelope(path=str(path), n_segments=len(segments),
                       segments=segments, missing_names=missing)


def citi_network_probe(path: str | Path) -> dict:
    """skrf 桥接探针信封：CITI 内嵌 S 参数段 → Network 概览（只读）。

    桥接条件（预声明，任一不满足 → skipped + reason）：
      1. 包内有可解码复数值段（value_kind=="complex"）；
      2. S[i,j] 形态段名构成完整方阵（n×n 全元存在）；
      3. 独立变量（频率）值表存在且与 S 段长度一致；
      4. 除频率外无多值扫描参数（VAR occurrences>1 视为多值扫描——
         参数扫面 CITI 本服务不桥，如实跳过）。

    成功信封带网络概览计数（n_ports/n_freq/f 范围/z0 来源），不序列化
    Network 本体（体量大，消费方经本函数确认可桥后自行走 skrf 生态）。
    """
    packages, err = _load_packages(path)
    if err is not None:
        return err
    probe: dict[str, Any] = {"packages_checked": len(packages),
                             "bridged_packages": []}
    bridged: list[dict] = []
    skipped: list[dict] = []
    for i, pkg in enumerate(packages):
        # 条件 4：除频率外多值扫描参数 → 不桥
        sweep_vars = [v for v in pkg.variables
                      if v.occurrences > 1 and v.name.lower() not in
                      ("freq", "frequency")
                      and v.values is not None
                      and len(v.values) > 1]
        if sweep_vars:
            skipped.append({"package_index": i,
                            "reason": "存在多值扫描参数 "
                                      + ",".join(v.name for v in sweep_vars)
                                      + "（参数扫面 CITI 不桥接）"})
            continue
        freq = None
        indep_seg = next((s for s in pkg.segments
                          if s.independent_var is not None
                          and s.independent_var.values), None)
        if indep_seg is not None:
            freq = indep_seg.independent_var.values
        s_entries: dict[tuple[int, int], list[complex]] = {}
        z0_entries: dict[int, list[float]] = {}
        for seg in pkg.segments:
            for dep in seg.dependent_vars:
                if dep.values is None:
                    continue
                m = _S_MATRIX_RE.match(dep.name)
                if m and dep.value_kind == "complex":
                    s_entries[(int(m.group(1)), int(m.group(2)))] = dep.values
                z = _PORTZ_RE.match(dep.name)
                if z and len(dep.values) and dep.value_kind in ("float",
                                                                "complex"):
                    vals = dep.values
                    z0_entries[int(z.group(1))] = [
                        v.real if isinstance(v, complex) else float(v)
                        for v in vals]
        if not s_entries:
            skipped.append({"package_index": i,
                            "reason": "无可解码 S[i,j] 复数值段"})
            continue
        ports = max(max(i, j) for (i, j) in s_entries)
        missing = [(r, c) for r in range(1, ports + 1)
                   for c in range(1, ports + 1)
                   if (r, c) not in s_entries]
        if missing:
            skipped.append({"package_index": i,
                            "reason": f"S 矩阵缺元 {missing[:4]}（方阵不齐套）"})
            continue
        n_freq = len(next(iter(s_entries.values())))
        if freq is None:
            skipped.append({"package_index": i,
                            "reason": "独立变量（频率）值表不存在"})
            continue
        if len(freq) != n_freq:
            skipped.append({"package_index": i,
                            "reason": f"频率点数 {len(freq)} 与 S 段长度 "
                                      f"{n_freq} 不一致"})
            continue
        declared_unit = (indep_seg.independent_var.unit or "HZ")
        unit = declared_unit.strip().lower()
        if unit not in ("hz", "khz", "mhz", "ghz"):
            # skrf 不认的单位 → 回落 Hz（值即按 Hz 解释）并显式声明
            unit = "hz"
            unit_fallback = True
        else:
            unit_fallback = False
        try:
            import numpy as np
            import skrf
            from skrf.frequency import Frequency
        except ImportError as exc:  # pragma: no cover（skrf 是核心依赖）
            return error_envelope(f"skrf 不可用: {exc}")
        s_arr = np.zeros((n_freq, ports, ports), dtype=complex)
        for (r, c), vals in s_entries.items():
            s_arr[:, r - 1, c - 1] = np.asarray(vals, dtype=complex)
        if z0_entries and set(z0_entries) == set(range(1, ports + 1)):
            z0 = np.zeros((n_freq, ports), dtype=complex)
            for k, vals in z0_entries.items():
                z0[:, k - 1] = np.asarray(vals, dtype=complex)
            z0_source = "PortZ/Zo segment"
        else:
            z0 = np.full((n_freq, ports), 50.0, dtype=complex)
            z0_source = "default 50 ohm"
        frequency = Frequency.from_f(np.asarray(freq, dtype=float), unit=unit)
        network = skrf.Network(frequency=frequency, s=s_arr, z0=z0)
        bridged.append({
            "package_index": i,
            "name": pkg.name,
            "n_ports": ports,
            "n_freq": n_freq,
            "f_min_hz": float(freq[0]),
            "f_max_hz": float(freq[-1]),
            "freq_unit_declared": indep_seg.independent_var.unit,
            "freq_unit_used": unit,
            "freq_unit_fallback": unit_fallback,
            "z0_source": z0_source,
            "network_summary": {
                "n_ports": network.nports,
                "n_freq": len(network.f),
                "s_shape": list(network.s.shape),
            },
        })
    probe["bridged_packages"] = bridged
    probe["skipped_packages"] = skipped
    if not bridged:
        reasons = "; ".join(s["reason"] for s in skipped) or "无可桥接包"
        return skipped_envelope(
            f"skrf 桥接条件不满足（{reasons}）", **probe)
    return ok_envelope(path=str(path), **probe)
