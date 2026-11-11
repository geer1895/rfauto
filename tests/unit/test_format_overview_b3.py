"""T-Q5 批 3 接线席 Q-W9-3（aurora_q 方向 C）——ADS .ds 速览扩位单测。

覆盖面（任务书 ≥22 条之二）：
- ads_ds kind 探测三通道（扩展名/magic 兜底/存根形态）+ 二进制 magic
  先于文本 magic（gdsii 先例同序）；
- 结构钉（stats/entities/summary——侦察实测字段：magic_form/byte_order_
  marker/format_version/n_variables + variable_names）；
- 存根形态（15B 空数据集占位件）；
- 确定性（同文件双跑逐字节同）；
- 负例（垃圾冒充 .ds/截断头/非 EEsof）显式报错信封；
- 侦察结论钉（magic 常量字节面=探针实测；结论内联零证据区依赖）。

侦察纪律出处：.ds 为 ADS 二进制 dataset 格式——magic/结构经
本机 ADS 2027 安装树 examples 六样例只读探针实测（探针与结论档
runs/aurora_q/qw93_stats/probe_ds.py，零写入零执行 ADS 二进制）；
fixtures 为手搭小样例（禁用真机文件进仓——厂商内容零入库同纪律）。
"""

from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

from rfauto.service.format_overview_service import (
    FORMAT_OVERVIEW_VERSION,
    SCHEMA_VERSIONS,
    SUPPORTED_KINDS,
    detect_format_kind,
    overview_format,
    overview_format_json,
)

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "format_overview"
_DS = _FIXTURES / "minimal_dataset.ds"

#: 侦察实测 magic 双形态（六样例：四全量+两存根；探针档 qw93_stats）。
RECON_FULL_MAGIC = b"EEsof dataset\r\n\x1a\xfe\xed\xfa\xce"
RECON_STUB_MAGIC = b"HP EEsof data\r\n"

_OK_KEYS = {"ok", "kind", "schema_version", "framework_version", "path",
            "stats", "entities", "summary"}


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_full_ds(path: Path, *, names: list[str], version: int = 3) -> None:
    """手搭全量形态 .ds（侦察口径：20B 头+0x20 字节序+0x24 版本+0x200 对齐
    首块+STRINGDATA 变量名）。"""
    raw = bytearray(RECON_FULL_MAGIC)
    raw += b"\x00" * 12
    raw += b"DCBA"
    raw += struct.pack("<I", version)
    raw += b"\x00" * (0x200 - len(raw))
    raw += b"STRINGDATA\x00"
    for name in names:
        raw += name.encode("utf-8") + b"\x00"
    raw += b"\x00" * 8
    path.write_bytes(bytes(raw))


# ---------------------------------------------------------------------------
# kind 探测三通道 + magic 序
# ---------------------------------------------------------------------------

def test_detect_ads_ds_by_extension() -> None:
    assert detect_format_kind(_DS) == "ads_ds"


def test_detect_ads_ds_extension_case_insensitive(tmp_path: Path) -> None:
    upper = tmp_path / "DATASET.DS"
    upper.write_bytes(_DS.read_bytes())
    assert detect_format_kind(upper) == "ads_ds"
    env = overview_format(upper)
    assert env["ok"] is True and env["kind"] == "ads_ds"


def test_detect_ads_ds_full_magic_without_extension(tmp_path: Path) -> None:
    """扩展名缺失时 EEsof 全量 magic 兜底（原字节读面——utf-8 解码对
    0xFE 等非 UTF-8 字节有损，探测必须走 _magic_head_bytes）。"""
    bare = tmp_path / "no_extension"
    bare.write_bytes(_DS.read_bytes())
    assert detect_format_kind(bare) == "ads_ds"


def test_detect_ads_ds_stub_magic(tmp_path: Path) -> None:
    """存根形态（15B 空数据集占位件）扩展名有无双路均命中。"""
    stub = tmp_path / "momentum.ds"
    stub.write_bytes(RECON_STUB_MAGIC)
    assert detect_format_kind(stub) == "ads_ds"
    bare = tmp_path / "no_extension"
    bare.write_bytes(RECON_STUB_MAGIC)
    assert detect_format_kind(bare) == "ads_ds"


def test_detect_ads_ds_binary_magic_precedes_text_magic(
        tmp_path: Path) -> None:
    """二进制 EEsof magic 先于文本格式扫描（gdsii 批 2 先例同序）——正文
    夹 "(kicad_pcb" 也不得误路由。"""
    trick = tmp_path / "trick"
    trick.write_bytes(RECON_FULL_MAGIC + b"(kicad_pcb fake body)")
    assert detect_format_kind(trick) == "ads_ds"


def test_b3_registry_snapshot() -> None:
    """批 3 registry 快照（#231 惯例席位自钉）：ads_ds 1.0 在册。"""
    assert SCHEMA_VERSIONS["ads_ds"] == "1.0"
    assert "ads_ds" in SUPPORTED_KINDS
    assert FORMAT_OVERVIEW_VERSION == "1.2"


# ---------------------------------------------------------------------------
# 结构钉（侦察实测字段）
# ---------------------------------------------------------------------------

def test_ads_ds_structure_pins() -> None:
    env = overview_format(_DS)
    assert set(env) == _OK_KEYS
    assert env["ok"] is True and env["kind"] == "ads_ds"
    assert env["schema_version"] == "1.0"
    stats = env["stats"]
    assert stats["magic_form"] == "full"
    assert stats["byte_order_marker"] == "DCBA"
    assert stats["format_version"] == 3
    assert stats["file_size_bytes"] == _DS.stat().st_size
    assert stats["n_variables"] == 4
    # STRINGDATA 变量名原样透传（首串=系统哨兵名，零语义过滤——侦察实测）
    assert env["entities"]["variable_names"] == [
        "DATAMANAGER_INDEX", "S(1,1)", "S(2,1)", "HPvar_top_0"]
    assert "EEsof dataset v3" in env["summary"]
    assert "专有布局未解" in env["summary"]  # 如实边界：数值块不承诺


def test_ads_ds_variable_name_parsing_rules(tmp_path: Path) -> None:
    """STRINGDATA 解析规则钉：首个空段=终止；变量名在列表序原样。"""
    p = tmp_path / "names.ds"
    _write_full_ds(p, names=["A", "B_2", "长名字"])
    env = overview_format(p)
    assert env["ok"] is True
    assert env["entities"]["variable_names"] == ["A", "B_2", "长名字"]
    assert env["stats"]["n_variables"] == 3


def test_ads_ds_stub_structure_pins(tmp_path: Path) -> None:
    """存根形态结构钉：15B 空数据集——marker/version=None、零变量。"""
    p = tmp_path / "stub.ds"
    p.write_bytes(RECON_STUB_MAGIC)
    env = overview_format(p)
    assert env["ok"] is True and env["kind"] == "ads_ds"
    stats = env["stats"]
    assert stats["magic_form"] == "stub"
    assert stats["byte_order_marker"] is None
    assert stats["format_version"] is None
    assert stats["file_size_bytes"] == 15
    assert stats["n_variables"] == 0
    assert env["entities"] == {"variable_names": []}


def test_ads_ds_format_version_read(tmp_path: Path) -> None:
    """0x24 版本字段直读（侦察实测值域 3/4——v4 样例 TEST_LPF_HBamp）。"""
    p = tmp_path / "v4.ds"
    _write_full_ds(p, names=["X"], version=4)
    env = overview_format(p)
    assert env["ok"] is True
    assert env["stats"]["format_version"] == 4


def test_ads_ds_deterministic_sha256() -> None:
    """同文件双跑速览 JSON 逐字节同（确定性验收钉）。"""
    a, b = overview_format_json(_DS), overview_format_json(_DS)
    assert a == b
    assert _sha256(a) == _sha256(b)
    assert overview_format(_DS) == overview_format(_DS)


# ---------------------------------------------------------------------------
# 负例（坏文件显式报错信封，非异常裸抛）
# ---------------------------------------------------------------------------

def test_ads_ds_garbage_error_envelope(tmp_path: Path) -> None:
    """垃圾内容冒充 .ds → 错误信封（kind 已判定如实归属）。"""
    bad = tmp_path / "garbage.ds"
    bad.write_bytes(b"not an eesof dataset at all")
    env = overview_format(bad)
    assert env["ok"] is False
    assert env["kind"] == "ads_ds"
    assert env["errors"]


def test_ads_ds_truncated_header_error_envelope(tmp_path: Path) -> None:
    """全量 magic 后头不完整（<40 字节）→ 错误信封。"""
    bad = tmp_path / "trunc.ds"
    bad.write_bytes(RECON_FULL_MAGIC + b"\x00" * 4)
    env = overview_format(bad)
    assert env["ok"] is False and env["kind"] == "ads_ds"
    assert "不完整" in "\n".join(env["errors"])


def test_ads_ds_empty_file_error_envelope(tmp_path: Path) -> None:
    bad = tmp_path / "empty.ds"
    bad.write_bytes(b"")
    env = overview_format(bad)
    assert env["ok"] is False and env["errors"]


# ---------------------------------------------------------------------------
# 侦察结论钉（探针实测结论在档）
# ---------------------------------------------------------------------------

def test_ads_ds_recon_constants_pin() -> None:
    """侦察结论钉：magic 常量字节面=探针实测（六样例，零写入零执行）。"""
    from rfauto.service.format_overview_service import (
        _ADS_DS_FULL_MAGIC,
        _ADS_DS_STUB_MAGIC,
    )
    assert _ADS_DS_FULL_MAGIC == RECON_FULL_MAGIC
    assert _ADS_DS_STUB_MAGIC == RECON_STUB_MAGIC


def test_ads_ds_recon_probe_facts_inlined() -> None:
    """侦察结论内联钉（Q-R2 P2-1 改造）：探针实测的字节事实直接以常量
    内联本测试，零 runs/ 证据区文件依赖——证据区属可清理工作区资产，
    原"探针档存在性"断言会在证据清理后变假红（无代码变更的门红）。
    出处注记：探针档 qw93_stats/probe_ds.py（2026-11 aurora_q Q-W9-3，
    本机 ADS 2027 安装树六样例只读实测，零写入零执行）；其
    FULL_MAGIC/STUB_MAGIC 与本文件 RECON_* 常量逐字节同（手搭先例）。"""
    # 全量形态：ASCII 头 b"EEsof dataset\r\n"（15B）+ 5B 链尾标记，共 20B。
    assert RECON_FULL_MAGIC.startswith(b"EEsof dataset\r\n")
    assert RECON_FULL_MAGIC.endswith(b"\x1a\xfe\xed\xfa\xce")
    assert len(RECON_FULL_MAGIC) == 20
    # 存根形态：15B 空数据集占位件头，恰为 b"HP EEsof data\r\n"。
    assert RECON_STUB_MAGIC == b"HP EEsof data\r\n"
    assert len(RECON_STUB_MAGIC) == 15


def test_ads_ds_json_round_trip() -> None:
    """规范序列化可回读（json.loads 还原信封）。"""
    back = json.loads(overview_format_json(_DS))
    assert back["ok"] is True and back["kind"] == "ads_ds"
    assert back["stats"]["n_variables"] == 4
