r"""PK-9 打印介质数据集扩展（PRINT_MATERIALS 扩 DLP 树脂/尼龙）。

规格：研究扩充 round14 §五 PK-9（P3/S-M）：
"PRINT_MATERIALS 扩 DLP 树脂/尼龙 infill（DLR/IMEKO 公开值）"。

**零值诚实登记（#118/#df6-⑨ 引用腐坏纪律）**：规格点名的 DLR/IMEKO
公开值 2026-10-03 检索未获可核原文（web_search_prime 限流+摘要转述
不可逐位核对）——本模块**不登记任何 εr/tanδ 数值**（er_band/tan_d_band
一律 None、状态 NO_VALUE_retrieval_pending），只登记材料/工艺/infill
schema 与检索指针（retrieval_pointers），待回原文逐位核对后按
PRINT_MATERIALS 既有状态档（UNVERIFIED_band / UNVERIFIED_single_source，
core/luneburg_lens.py 先例）升级。**不凭记忆复写文献数值。**

落位说明：core/luneburg_lens.py 为已合流文件（本席禁改），扩展条目落
本新文件；merged_print_materials() 提供只读合并视图（不改动单源 dict）。
consumers（渲染/DB 消费面）后续接 merged 视图即可。

schema（与 PRINT_MATERIALS 条目同构，附加键全部可选）::

    {
      "material": str,
      "process": "DLP" | "SLS" | "MJF" | ...（自由标注，不加枚举硬门）,
      "infill": {"pattern": str, "f_modulates": "er via mix_er_eff"},
      "er_band": (lo, hi) | None,          # None=未登记（本批全部 None）
      "er_band_status": 状态档（见下）,
      "tan_d_band": (lo, hi) | None,       # 可选；None=未登记
      "tan_d_band_status": 状态档 | None,
      "retrieval_pointers": [str, ...],    # 检索指针（本批必给）
      "sources": [str, ...],               # 出处/指针说明（非空）
    }

状态档全集（文案即语义）：``UNVERIFIED_band`` / ``UNVERIFIED_single_source``
（PRINT_MATERIALS 既有档）/ ``NO_VALUE_retrieval_pending``（本批新档：
无值待检索）。纯函数零 IO；不定义 ``__all__``（公开 API 快照口径）。
"""

from __future__ import annotations

import copy
from typing import Any

#: 无值待检索档（本批新状态；数值只能由后续可核原文补登）
STATUS_NO_VALUE_RETRIEVAL_PENDING = "NO_VALUE_retrieval_pending"

#: 合法状态档全集（含 PRINT_MATERIALS 既有档，供 validator 单源）
_ALLOWED_BAND_STATUSES = (
    "UNVERIFIED_band",            # luneburg_lens 既有档：带值未逐源核对
    "UNVERIFIED_single_source",   # luneburg_lens 既有档：单源待证
    STATUS_NO_VALUE_RETRIEVAL_PENDING,
)

#: 值档（band 非 None 时允许的状态——NO_VALUE 档与有值互斥）
_VALUE_BEARING_STATUSES = ("UNVERIFIED_band", "UNVERIFIED_single_source")

_INFPILL_F_MODULATES_CONVENTION = "er via mix_er_eff"

_DLP_RETRIEVAL = [
    "DLR（德国航空航天中心）DLP 光刻树脂微波 εr 实测：检索指针="
    "'DLR DLP resin dielectric characterization microwave'（2026-10-03 "
    "检索限流未获原文，待逐位核对）",
    "IMEKO TC 相关会议（3D 打印材料介电表征）：检索指针="
    "'IMEKO 3D printed dielectric permittivity measurement'",
]
_NYLON_RETRIEVAL = [
    "PA12（SLS/MJF 尼龙）微波 εr 实测：检索指针='PA12 SLS dielectric "
    "constant GHz waveguide/resonator'（2026-10-03 未获可核原文）",
    "PA11 同上（检索指针='PA11 SLS permittivity microwave'）",
]

#: 扩展条目（全部零值登记，见模块 docstring 诚实口径）
PRINT_MATERIALS_EXT: dict[str, dict[str, Any]] = {
    "dlp_standard_resin": {
        "material": "DLP 光敏树脂（standard/通用）",
        "process": "DLP",
        "infill": {"pattern": "solid_or_honeycomb",
                   "f_modulates": _INFPILL_F_MODULATES_CONVENTION},
        "er_band": None,
        "er_band_status": STATUS_NO_VALUE_RETRIEVAL_PENDING,
        "tan_d_band": None,
        "tan_d_band_status": STATUS_NO_VALUE_RETRIEVAL_PENDING,
        "retrieval_pointers": list(_DLP_RETRIEVAL),
        "sources": ["检索未获可核原文——零值登记（本模块 docstring 口径）"],
    },
    "nylon_pa12": {
        "material": "PA12 尼龙（SLS 粉末烧结）",
        "process": "SLS",
        "infill": {"pattern": "solid_powder_sintered",
                   "f_modulates": _INFPILL_F_MODULATES_CONVENTION},
        "er_band": None,
        "er_band_status": STATUS_NO_VALUE_RETRIEVAL_PENDING,
        "tan_d_band": None,
        "tan_d_band_status": STATUS_NO_VALUE_RETRIEVAL_PENDING,
        "retrieval_pointers": list(_NYLON_RETRIEVAL),
        "sources": ["检索未获可核原文——零值登记（本模块 docstring 口径）"],
    },
    "nylon_pa12_mjf": {
        "material": "PA12 尼龙（MJF 多射流熔融）",
        "process": "MJF",
        "infill": {"pattern": "solid_powder_fused",
                   "f_modulates": _INFPILL_F_MODULATES_CONVENTION},
        "er_band": None,
        "er_band_status": STATUS_NO_VALUE_RETRIEVAL_PENDING,
        "tan_d_band": None,
        "tan_d_band_status": STATUS_NO_VALUE_RETRIEVAL_PENDING,
        "retrieval_pointers": list(_NYLON_RETRIEVAL),
        "sources": ["检索未获可核原文——零值登记（本模块 docstring 口径）"],
    },
}


def validate_ext_entry(entry: dict[str, Any], entry_id: str = "<anon>") -> None:
    """条目 schema 校验（非法即 ValueError；-band 可为值对或 None）。

    值对要求 0<lo<hi 且有限；状态档必须在 _ALLOWED_BAND_STATUSES；
    er_band=None 时状态必须为 NO_VALUE_retrieval_pending（值与状态
    一致性守卫——防"有值却挂零值档"或"零值却挂带值档"）。
    """
    where = f"PRINT_MATERIALS_EXT[{entry_id!r}]"
    if not isinstance(entry, dict):
        raise ValueError(f"{where} 必须是 dict")
    for key, typ in (("material", str), ("process", str)):
        if not isinstance(entry.get(key), typ) or not entry.get(key):
            raise ValueError(f"{where}.{key} 必须为非空 str")
    infill = entry.get("infill")
    if not isinstance(infill, dict) or not isinstance(
            infill.get("pattern"), str) or not infill.get("pattern"):
        raise ValueError(f"{where}.infill.pattern 必须为非空 str")
    if infill.get("f_modulates") != _INFPILL_F_MODULATES_CONVENTION:
        raise ValueError(
            f"{where}.infill.f_modulates 必须为 {_INFPILL_F_MODULATES_CONVENTION!r}"
            "（与 PRINT_MATERIALS 约定一致）")

    def _check_band(band: Any, status: Any, name: str, *, optional: bool) -> None:
        if optional and band is None and status is None:
            return  # tan_d 键对整体可省略（schema 附加键）
        if band is None:
            if status != STATUS_NO_VALUE_RETRIEVAL_PENDING:
                raise ValueError(
                    f"{where}.{name}_band=None 时状态必须为 "
                    f"{STATUS_NO_VALUE_RETRIEVAL_PENDING}，得到 {status!r}")
            return
        if status not in _VALUE_BEARING_STATUSES:
            raise ValueError(
                f"{where}.{name}_band 有值时状态必须为值档 "
                f"{_VALUE_BEARING_STATUSES}，得到 {status!r}")
        try:
            lo, hi = (float(band[0]), float(band[1]))
        except (TypeError, ValueError, IndexError) as exc:
            raise ValueError(
                f"{where}.{name}_band 必须为 (lo, hi) 正数对或 None") from exc
        if not (lo > 0.0 and hi > lo):
            raise ValueError(f"{where}.{name}_band 须 0<lo<hi，得到 {(lo, hi)}")

    _check_band(entry.get("er_band"), entry.get("er_band_status"), "er",
                optional=False)
    _check_band(entry.get("tan_d_band"), entry.get("tan_d_band_status"),
                "tan_d", optional=True)
    pointers = entry.get("retrieval_pointers")
    if not isinstance(pointers, list) or not pointers or not all(
            isinstance(p, str) and p for p in pointers):
        raise ValueError(f"{where}.retrieval_pointers 必须为非空 str 列表")
    sources = entry.get("sources")
    if not isinstance(sources, list) or not sources or not all(
            isinstance(s, str) and s for s in sources):
        raise ValueError(f"{where}.sources 必须为非空 str 列表")


for _id, _entry in PRINT_MATERIALS_EXT.items():
    validate_ext_entry(_entry, _id)


def merged_print_materials() -> dict[str, dict[str, Any]]:
    """PRINT_MATERIALS（luneburg 单源，只读）∪ 本批扩展条目的合并视图。

    返回新 dict（深拷贝），不改动任何单源；键冲突显式报错（扩展条目
    与既有条目互斥是本批契约，静默覆盖=数据丢失）。
    """
    from rfauto.core.luneburg_lens import PRINT_MATERIALS

    overlap = sorted(set(PRINT_MATERIALS) & set(PRINT_MATERIALS_EXT))
    if overlap:
        raise ValueError(f"扩展条目与 PRINT_MATERIALS 键冲突: {overlap}")
    merged = {k: copy.deepcopy(v) for k, v in PRINT_MATERIALS.items()}
    merged.update(copy.deepcopy(PRINT_MATERIALS_EXT))
    return merged


def ext_entry_er_band(material_id: str) -> tuple[float, float] | None:
    """按 id 取扩展条目 εr 带（未登记返回 None；未知 id KeyError 带可用集）。"""
    if material_id not in PRINT_MATERIALS_EXT:
        raise KeyError(
            f"未知扩展材料 id: {material_id!r}，可用: {sorted(PRINT_MATERIALS_EXT)}")
    band = PRINT_MATERIALS_EXT[material_id]["er_band"]
    return None if band is None else (float(band[0]), float(band[1]))


def retrieval_status() -> list[dict[str, Any]]:
    """逐条目检索状态报告（消费面/后续补登的工作清单）。"""
    out: list[dict[str, Any]] = []
    for mid, entry in PRINT_MATERIALS_EXT.items():
        out.append({
            "id": mid,
            "material": entry["material"],
            "process": entry["process"],
            "er_registered": entry["er_band"] is not None,
            "er_band_status": entry["er_band_status"],
            "retrieval_pointers": list(entry["retrieval_pointers"]),
        })
    return out
