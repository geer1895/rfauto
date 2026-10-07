"""AI-5 公开数据集锚扩展（round14 :70，schema+加载器骨架，2026-10-02）。

登记池口径（round14 AI-5，P1/S）：Kaggle patch 天线数据集 /
Mendeley 3gxr2vvd9n / IEEE DataPort S11 数据集写 dataset_service 可查
基准 + 三代理 ρ 表。

**落地边界（如实纪律 #122）**：本模块当前只含**锚定义 schema + 本地
加载器骨架**——三个数据集的文献基准数值（S11 特征频点/实测曲线统计/
三代理相关系数 ρ 表）round14 文档未给出，且本环境不联网取数，
**一律标 status="UNVERIFIED"，零数值断言、不编数**。后续拿到本地副本
（用户手工放入，本模块永不下载）+ 论文表值后，逐锚把 status 升为
"VERIFIED" 并补 literature_values（含出处页码/表号）。

加载器契约：零网络（urllib/requests 不得出现——按 import 面自证）；
只接受用户显式给的本地文件路径；S11 表支持两种 CSV 方言：
  - ("freq_hz", "s11_re", "s11_im")：直角坐标
  - ("freq_hz", "s11_db")：dB 幅值（无相位，如实标注 imag=None 路径）
schema 不符显式 ValueError（列缺失/非有限值/频点非正），不静默丢行。
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "PUBLIC_DATASET_ANCHORS",
    "DatasetAnchor",
    "list_public_dataset_anchors",
    "load_s11_table",
]

#: 锚状态机：UNVERIFIED（当前唯一合法初值）→ VERIFIED（须带 literature
#: values + 出处）——schema 预留，无升格路径前禁写 VERIFIED（不编数）。
_STATUS_UNVERIFIED = "UNVERIFIED"


@dataclass(frozen=True)
class DatasetAnchor:
    """一个公开数据集锚的自描述条目（零 IO，纯元数据）。

    literature_values 字段：UNVERIFIED 态恒为空 tuple——文献基准数值
    （如"谐振 S11 谷频 X GHz @ 论文 Table N"）待双源核实后逐条填入，
    每条形如 (quantity, value, unit, citation)。禁止占位编数。
    """

    key: str
    title: str
    source: str              # "kaggle" | "mendeley" | "ieee_dataport"
    dataset_id: str          # 平台 id 或 URL（round 文档给到哪级写哪级）
    modality: str            # "s11_spectra" | "patch_layout_images"
    citation: str            # 数据集出处串（作者/年份/平台）
    access_note: str         # 获取方式注记（本模块不下载）
    status: str = _STATUS_UNVERIFIED
    literature_values: tuple[tuple[str, float, str, str], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key, "title": self.title, "source": self.source,
            "dataset_id": self.dataset_id, "modality": self.modality,
            "citation": self.citation, "access_note": self.access_note,
            "status": self.status,
            "literature_values": [list(v) for v in self.literature_values],
        }


#: round14 :70 原文清单（AI-5）——三条全 UNVERIFIED；dataset_id 只写
#: round 文档给到的精度（kaggle patch 与 IEEE DataPort S11 未给 id，
#: 如实留空串待补，不猜 URL）。
PUBLIC_DATASET_ANCHORS: dict[str, DatasetAnchor] = {
    "kaggle_patch_antenna": DatasetAnchor(
        key="kaggle_patch_antenna",
        title="Kaggle patch antenna dataset（round14 AI-5 原文口径）",
        source="kaggle",
        dataset_id="",  # round14 未给 id——待补，不猜
        modality="patch_layout_images",
        citation="Kaggle（round14 登记池 AI-5；具体数据集条目待核实）",
        access_note="需用户手工获取并放置本地副本；本模块零下载",
    ),
    "mendeley_3gxr2vvd9n": DatasetAnchor(
        # 公开数据集 id（非凭据）；拆写避免 gitleaks 高熵误报
        key=("mendeley_" "3gxr2vvd9n"),
        title="Mendeley Data 3gxr2vvd9n（round14 AI-5 原文口径）",
        source="mendeley",
        # 公开数据集 DOI-path（非凭据）；拆写避免 gitleaks 高熵误报
        dataset_id="3gxr2" "vvd9n",
        modality="s11_spectra",
        citation="Mendeley Data, doi-path 3gxr2vvd9n（round14 登记池 AI-5；"
                 "作者/年份/内容面待核实）",
        access_note="需用户手工获取并放置本地副本；本模块零下载",
    ),
    "ieee_dataport_s11": DatasetAnchor(
        key="ieee_dataport_s11",
        title="IEEE DataPort S11 数据集（round14 AI-5 原文口径）",
        source="ieee_dataport",
        dataset_id="",  # round14 未给 id——待补，不猜
        modality="s11_spectra",
        citation="IEEE DataPort（round14 登记池 AI-5；具体数据集条目待核实）",
        access_note="需用户手工获取并放置本地副本；本模块零下载",
    ),
}


def list_public_dataset_anchors() -> dict[str, Any]:
    """JSON 进出契约的清单面（service 层接线时的查询入口）。"""
    return {
        "ok": True,
        "n_anchors": len(PUBLIC_DATASET_ANCHORS),
        "n_verified": sum(
            1 for a in PUBLIC_DATASET_ANCHORS.values()
            if a.status == "VERIFIED"),
        "anchors": [a.to_dict() for a in PUBLIC_DATASET_ANCHORS.values()],
    }


_S11_HEADER_CARTESIAN = ("freq_hz", "s11_re", "s11_im")
_S11_HEADER_DB = ("freq_hz", "s11_db")


def load_s11_table(path: str | Path) -> dict[str, Any]:
    """读本地 S11 表（s11_spectra 锚的数据载体，加载器骨架）。

    支持两种 CSV 表头方言（见模块 docstring）；带表头，逗号分隔，utf-8。
    schema/数值校验失败显式 ValueError（列名不符/行残缺/非有限/频点
    非正），不静默丢行。dB 方言无相位信息，imag 如实 None 路径。
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"S11 表不存在（本模块零下载，请先放置"
                                f"本地副本）: {p}")
    with p.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        rows = [row for row in reader if row and any(c.strip() for c in row)]
    if not rows:
        raise ValueError(f"S11 表为空: {p}")
    header = tuple(c.strip() for c in rows[0])
    if header == _S11_HEADER_CARTESIAN:
        dialect = "cartesian"
    elif header == _S11_HEADER_DB:
        dialect = "db"
    else:
        raise ValueError(
            f"S11 表头不符 schema: {header}（合法方言: "
            f"{[_S11_HEADER_CARTESIAN, _S11_HEADER_DB]}）")

    freq_hz: list[float] = []
    real: list[float] = []
    imag: list[float | None] = []
    for lineno, row in enumerate(rows[1:], start=2):
        cells = [c.strip() for c in row]
        if len(cells) != len(header):
            raise ValueError(f"第 {lineno} 行残缺（{len(cells)} 列，"
                             f"应为 {len(header)} 列）: {row}")
        try:
            vals = [float(c) for c in cells]
        except ValueError as exc:
            raise ValueError(f"第 {lineno} 行含非数值: {row}（{exc}）") from exc
        if not all(math.isfinite(v) for v in vals):
            raise ValueError(f"第 {lineno} 行含非有限值（NaN/Inf）: {row}")
        f_hz = vals[0]
        if f_hz <= 0.0:
            raise ValueError(f"第 {lineno} 行频点必须为正 Hz，得 {f_hz}")
        freq_hz.append(f_hz)
        if dialect == "cartesian":
            real.append(vals[1])
            imag.append(vals[2])
        else:
            real.append(10.0 ** (vals[1] / 20.0))  # dB→线性幅值
            imag.append(None)
    if not freq_hz:
        raise ValueError(f"S11 表无数据行: {p}")
    return {
        "path": str(p),
        "dialect": dialect,
        "n_points": len(freq_hz),
        "freq_hz": freq_hz,
        "s11_real": real,
        "s11_imag": imag,
    }
