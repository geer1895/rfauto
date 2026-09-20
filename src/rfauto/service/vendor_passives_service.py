"""C15 厂商被动元件库 service（JSON 进出）: registry 盘点/匹配链偏差/条目登记。

方案依据: "SimSurfing/Coilcraft 接入元件
registry（自谐振/ESR 元数据），模型按厂商条款走下载器不入 git"。
验收口径: "LNA 匹配网络真实电感 S2P vs 理想 lumped 偏差量化报告"。

三个入口（CLI/MCP 薄壳归 WP3.3，本轮只落 service）:
- list_vendor_parts: registry 逐条盘点（ok/unverified/file_missing/
  hash_mismatch 状态，缺文件 skip-not-fail）;
- run_match_deviation: 匹配网络闭式解（core.matching.synthesize_l_match）
  指定槽位替换为真实元件 S2P 阻抗曲线 → 偏差量化报告（Δmatch_depth_dB、
  L_eff/L_nom、SRF/f0、最佳匹配频点偏移）;
- register_model_entry: 下载器/测试把模型条目登记进 catalog（哈希必填，
  synthetic 例外）。

数值只在确定性内核（core.vendor_passives / core.matching / skrf）；
LLM 不产生物理数字。网络只在 scripts/vendor_passive_download.py。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from rfauto.core.matching import synthesize_match_network
from rfauto.core.vendor_passives import (
    ImpedanceCurve,
    VendorPartEntry,
    default_catalog_path,
    load_impedance_curve,
    load_part,
    match_deviation_report,
    read_catalog,
    sha256_file,
    validate_catalog,
    write_catalog,
)

__all__ = [
    "list_vendor_parts",
    "register_model_entry",
    "run_match_deviation",
]


def _jsonable(obj: Any) -> Any:
    """dict/ndarray/复数 → 严格 JSON 结构（inf→None, ndarray→list）。

    bool 须先于 int 判定（bool 是 int 子类）。与 active_chain_service 同款。
    """
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return _jsonable(obj.tolist())
    if isinstance(obj, (complex, np.complexfloating)):
        return {"re": round(float(obj.real), 9), "im": round(float(obj.imag), 9)}
    if isinstance(obj, (float, np.floating)):
        f = float(obj)
        return None if not np.isfinite(f) else round(f, 9)
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    if isinstance(obj, Path):
        return str(obj)
    return obj


def list_vendor_parts(
    catalog_path: str | Path | None = None,
    directory: str | Path | None = None,
) -> dict[str, Any]:
    """registry 盘点：逐条状态 + 条目元数据（缺文件 skip-not-fail，绝不抛）。"""
    path = Path(catalog_path) if catalog_path is not None else default_catalog_path()
    d = Path(directory) if directory is not None else path.parent
    parts: list[dict[str, Any]] = []
    try:
        entries = read_catalog(path)
    except KeyError as exc:
        return _jsonable({"catalog": str(path), "exists": False, "parts": [], "error": str(exc)})
    statuses = {status.part_id: status for status in validate_catalog(path, d)}
    for part_id, entry in entries.items():
        status = statuses.get(part_id)
        parts.append(_jsonable({
            "part_id": part_id,
            "status": status.status if status is not None else "unknown",
            "status_detail": status.detail if status is not None else "",
            **entry.to_dict(),
        }))
    return _jsonable({
        "catalog": str(path),
        "directory": str(d),
        "n_parts": len(parts),
        "parts": parts,
    })


def run_match_deviation(
    z_source: float,
    z_load: float,
    f0_ghz: float,
    slot_index: int,
    response: str = "low_pass",
    topology: str = "L",
    model_file: str | Path | None = None,
    part_id: str | None = None,
    catalog_path: str | Path | None = None,
    directory: str | Path | None = None,
    freqs_ghz: list[float] | None = None,
) -> dict[str, Any]:
    """匹配链真元件偏差报告（JSON）。

    槽位来源二选一：model_file（直接给 Touchstone 路径）或 part_id
    （经 registry 严格加载，provenance 门生效）。
    """
    given = [name for name, value in (("model_file", model_file), ("part_id", part_id)) if value]
    if len(given) != 1:
        raise ValueError(f"model_file 与 part_id 必须二选一，实际 {given!r}")
    if model_file is not None:
        curve: ImpedanceCurve = load_impedance_curve(Path(model_file))
        model_ref: str = str(model_file)
    else:
        loaded = load_part(str(part_id), catalog_path=catalog_path, directory=directory)
        curve = loaded.curve
        model_ref = f"registry:{part_id}"
    result = synthesize_match_network(topology, z_source, z_load, f0_ghz, response=response)
    if not (0 <= int(slot_index) < len(result.elements)):
        raise ValueError(
            f"slot_index={slot_index} 越界：{topology} 匹配共 {len(result.elements)} 个元件槽位"
        )
    report = match_deviation_report(
        result,
        {int(slot_index): curve},
        None if freqs_ghz is None else np.asarray(freqs_ghz, dtype=float),
    )
    payload = report.to_dict()
    payload["model_ref"] = model_ref
    payload["curve_diag"] = {
        "n_ports": curve.n_ports,
        "z0": curve.z0,
        "n_freq": int(curve.freqs_hz.size),
        "series_crosscheck_rel": curve.series_crosscheck_rel,
    }
    return _jsonable(payload)


def register_model_entry(
    catalog_path: str | Path,
    part_id: str,
    vendor: str,
    mpn: str,
    part_type: str,
    nominal_value: float,
    model_file: str,
    sha256: str | None = None,
    srf_ghz: float | None = None,
    esr_ohm: float | None = None,
    source_url: str = "",
    license_note: str = "",
    synthetic: bool = False,
    downloaded_at: str | None = None,
    replace: bool = False,
) -> dict[str, Any]:
    """登记/更新一条元件索引（下载器 --register 与测试共用路径）。

    真实厂商条目 sha256 必填（provenance 门，core 层硬错）；同 ID 已存在且
    replace=False → ValueError（防误覆盖）。
    """
    path = Path(catalog_path)
    entries: dict[str, VendorPartEntry] = {}
    if path.exists():
        entries = read_catalog(path)
    if part_id in entries and not replace:
        raise ValueError(f"part_id 已存在（replace=True 才可覆盖）: {part_id}")
    entry = VendorPartEntry.from_dict(part_id, {
        "vendor": vendor,
        "mpn": mpn,
        "type": part_type,
        "nominal_value": nominal_value,
        "model_file": model_file,
        "srf_ghz": srf_ghz,
        "esr_ohm": esr_ohm,
        "sha256": sha256,
        "source_url": source_url,
        "license_note": license_note,
        "synthetic": synthetic,
        "downloaded_at": downloaded_at,
    })
    if sha256 is not None:
        model_path = path.parent / model_file
        if model_path.exists():
            actual = sha256_file(model_path)
            if actual != sha256:
                raise ValueError(f"登记哈希与文件不符: catalog={sha256} actual={actual}（{model_path}）")
    entries[part_id] = entry
    write_catalog(path, entries)
    return _jsonable({
        "catalog": str(path),
        "registered": entry.to_dict(),
        "n_parts": len(entries),
    })
