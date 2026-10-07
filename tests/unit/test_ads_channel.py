"""项目 A 测试——ADS 通道选择器（M→A→B→C）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from rfauto.linkage.ads_channel import (
    probe_channel_availability,
    select_ads_channel,
)


@pytest.fixture()
def ads27_dir(tmp_path: Path) -> Path:
    """模拟真机 ADS 2027 安装（bin 下有 mcp server + hpeesofsim）。

    目录名取现役安装 E:/ADS/ADS27 的短年形态（2026-09-18 实测），同时钉住
    version_probe 短年 → "2027" 归一（rm-ads-wp43 治理）。
    """
    bin_dir = tmp_path / "ADS27" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "ads-mcp.exe").write_bytes(b"stub")
    (bin_dir / "hpeesofsim.exe").write_bytes(b"stub")
    return tmp_path / "ADS27"


@pytest.fixture()
def ads2024_dir(tmp_path: Path) -> Path:
    """模拟旧版 ADS（无官方 MCP、无 Python API 门槛达标）。"""
    bin_dir = tmp_path / "ADS2024" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "hpeesofsim.exe").write_bytes(b"stub")
    return tmp_path / "ADS2024"


class TestProbe:
    def test_2027_all_present(self, ads27_dir):
        probed = probe_channel_availability(ads27_dir, "2027")
        assert probed["m"]["available"]
        assert probed["a"]["available"]
        assert probed["b"]["available"]
        assert probed["c"]["available"]

    def test_old_version_m_a_unavailable(self, ads2024_dir):
        probed = probe_channel_availability(ads2024_dir, "2024")
        assert probed["m"]["available"] is False
        assert probed["a"]["available"] is False
        assert probed["b"]["available"]
        assert probed["c"]["available"]

    def test_version_numeric_year_comparison(self, ads2024_dir):
        """B-3/S3：版本门槛按数字年份比较，不走字符串序。

        "999" 字符串序 ≥"2027" 为 True（'9'>'2'）→ 假可用；数字年份 999<
        2027 如实 False。"2027.1" 点分形态主段 2027 ≥ 门槛 True（字符串序
        亦 True 但属巧合口径）。垃圾串如实 False 不臆断。
        """
        probed = probe_channel_availability(ads2024_dir, "999")
        assert probed["a"]["available"] is False
        probed2 = probe_channel_availability(ads2024_dir, "2027.1")
        assert probed2["a"]["available"] is True
        probed3 = probe_channel_availability(ads2024_dir, "garbage")
        assert probed3["a"]["available"] is False


class TestSelect:
    def test_2027_prefers_matrix_order(self, ads27_dir, monkeypatch):
        """2027 矩阵 channel=[b,c]（M 未通过评估前不进候选），应选 b。"""
        monkeypatch.delenv("RFAUTO_HPEESOF_DIR", raising=False)
        result = select_ads_channel(ads27_dir)
        assert result["ok"]
        assert result["channel"] == "b"
        assert result["version"] == "2027"
        assert result["candidates"] == ["b", "c"]
        assert result["errors"] == []

    def test_prefer_m_when_available(self, ads27_dir):
        result = select_ads_channel(ads27_dir, prefer="m")
        assert result["ok"]
        assert result["channel"] == "m"

    def test_prefer_unavailable_rejects_not_degrades(self, ads2024_dir):
        """显式 prefer 不可用时报错而非静默降级（audit > convenience）。"""
        result = select_ads_channel(ads2024_dir, prefer="m")
        assert result["ok"] is False
        assert any("m" in e for e in result["errors"])

    def test_unconfigured_ads_fails_cleanly(self, tmp_path, monkeypatch):
        monkeypatch.delenv("RFAUTO_HPEESOF_DIR", raising=False)
        monkeypatch.chdir(tmp_path)  # 隔离本机 configs/settings.local.yaml
        result = select_ads_channel(None)
        assert result["ok"] is False
        assert result["errors"]

    def test_unknown_channel_rejected(self, ads27_dir):
        result = select_ads_channel(ads27_dir, prefer="x")
        assert result["ok"] is False

    def test_missing_ads_dir(self, tmp_path):
        result = select_ads_channel(tmp_path / "no_such")
        assert result["ok"] is False
