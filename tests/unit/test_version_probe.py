"""项目 B 测试——HFSS 多版本探测与兼容分级（infra/version_probe）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from rfauto.infra.version_probe import (
    build_to_aedt_version,
    compat_level,
    detect_ads_version,
    detect_aedt_versions,
    load_compat_matrix,
    resolve_aedt_install,
)


@pytest.fixture(autouse=True)
def _clear_ansysem_env(monkeypatch):
    """清掉真机的 ANSYSEM_ROOT* 环境变量，保证探测测试确定性。"""
    import os

    for k in [k for k in os.environ if k.startswith("ANSYSEM_ROOT")]:
        monkeypatch.delenv(k, raising=False)


def _make_install(tmp_path: Path, build: int) -> Path:
    """造一个假安装：<tmp>/vNNN/Win64（模拟 ANSYSEM_ROOT 指向的形态）。"""
    d = tmp_path / f"v{build}" / "Win64"
    d.mkdir(parents=True)
    return d


class TestBuildToVersion:
    @pytest.mark.parametrize("build,expected", [
        (231, "2023.1"),
        (232, "2023.2"),
        (251, "2025.1"),
        (262, "2026.2"),
    ])
    def test_mapping(self, build, expected):
        assert build_to_aedt_version(build) == expected


class TestDetectAedt:
    def test_env_var_detection(self, tmp_path, monkeypatch):
        win64 = _make_install(tmp_path, 231)
        monkeypatch.setenv("ANSYSEM_ROOT231", str(win64))
        # 清掉真机可能存在的其他 ANSYSEM 变量，保证确定性
        for k in list(__import__("os").environ):
            if k.startswith("ANSYSEM_ROOT") and k != "ANSYSEM_ROOT231":
                monkeypatch.delenv(k, raising=False)

        installs = detect_aedt_versions()
        assert len(installs) == 1
        inst = installs[0]
        assert inst["version_id"] == "v231"
        assert inst["aedt_version"] == "2023.1"
        assert inst["path"] == tmp_path / "v231"
        assert inst["source"] == "env:ANSYSEM_ROOT231"

    def test_multi_version_sorted_newest_first(self, tmp_path, monkeypatch):
        import os

        for b in (231, 251, 241):
            monkeypatch.setenv(f"ANSYSEM_ROOT{b}", str(_make_install(tmp_path, b)))
        for k in list(os.environ):
            if k.startswith("ANSYSEM_ROOT") and k not in (
                "ANSYSEM_ROOT231", "ANSYSEM_ROOT241", "ANSYSEM_ROOT251"
            ):
                monkeypatch.delenv(k, raising=False)

        installs = detect_aedt_versions()
        versions = [i["aedt_version"] for i in installs]
        assert versions == sorted(versions, reverse=True)
        assert installs[0]["aedt_version"] == "2025.1"

    def test_nonexistent_paths_filtered(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ANSYSEM_ROOT231", str(tmp_path / "nowhere" / "Win64"))
        assert detect_aedt_versions() == []


class TestResolveAedtInstall:
    def test_explicit_path_parses_version(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ANSYSEM_ROOT231", raising=False)
        vdir = tmp_path / "v251"
        vdir.mkdir()
        inst = resolve_aedt_install(vdir)
        assert inst is not None
        assert inst["aedt_version"] == "2025.1"
        assert inst["source"] == "explicit"

    def test_explicit_path_prefix_matches_probe(self, tmp_path, monkeypatch):
        """显式路径不含 vNNN 时按探测结果前缀匹配。"""
        d = tmp_path / "HFSS_install" / "Win64"
        d.mkdir(parents=True)
        monkeypatch.setenv("ANSYSEM_ROOT231", str(d))
        inst = resolve_aedt_install(tmp_path / "HFSS_install")
        assert inst is not None
        assert inst["aedt_version"] == "2023.1"
        assert inst["source"] == "explicit+probe"

    def test_explicit_missing_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ANSYSEM_ROOT231", raising=False)
        assert resolve_aedt_install(tmp_path / "no_such") is None

    def test_no_explicit_auto_probe(self, tmp_path, monkeypatch):
        import os

        monkeypatch.setenv("ANSYSEM_ROOT241", str(_make_install(tmp_path, 241)))
        for k in list(os.environ):
            if k.startswith("ANSYSEM_ROOT") and k != "ANSYSEM_ROOT241":
                monkeypatch.delenv(k, raising=False)

        inst = resolve_aedt_install(None)
        assert inst is not None
        assert inst["aedt_version"] == "2024.1"
        assert inst["source"] == "auto-probe"

    def test_unparseable_dirname_falls_back(self, tmp_path):
        d = tmp_path / "custom_install"
        d.mkdir()
        inst = resolve_aedt_install(d)
        assert inst is not None
        assert inst["aedt_version"] == "2024.1"
        assert inst["source"] == "explicit-default"


class TestAdsVersion:
    def test_parse_lowercase_four_digit_year(self, tmp_path):
        d = tmp_path / "ads2026"  # 小写目录名同样解析（IGNORECASE）
        d.mkdir()
        assert detect_ads_version(d) == "2026"

    def test_parse_short_year_real_install_name(self, tmp_path):
        # 现役安装 E:/ADS/ADS27 的目录名形态（2026-09-18 实测），短年归一 20xx；
        # 修前返回 None → ads_channel 版本降级 [b,c]
        d = tmp_path / "ADS27"
        d.mkdir()
        assert detect_ads_version(d) == "2027"

    def test_parse_short_year_lowercase(self, tmp_path):
        d = tmp_path / "ads27"
        d.mkdir()
        assert detect_ads_version(d) == "2027"

    def test_three_or_five_digits_unparseable(self, tmp_path):
        for name in ("ADS123", "ADS20277"):
            d = tmp_path / name
            d.mkdir()
            assert detect_ads_version(d) is None, name

    def test_parse_mixed_case(self, tmp_path):
        d = tmp_path / "Keysight ADS2025"
        d.mkdir()
        assert detect_ads_version(d) == "2025"

    def test_unparseable(self, tmp_path):
        d = tmp_path / "some_dir"
        d.mkdir()
        assert detect_ads_version(d) is None

    def test_none_dir(self, tmp_path, monkeypatch):
        # 隔离本机 configs/settings.local.yaml（2026-09-01 起本机已配置 ADS）
        monkeypatch.chdir(tmp_path)
        assert detect_ads_version(None) is None  # 未配置 hpeesof_dir


class TestCompatMatrix:
    def test_matrix_file_exists_and_loads(self):
        matrix = load_compat_matrix()
        assert "aedt" in matrix and "ads" in matrix
        assert matrix["aedt"]["versions"]["2023.1"]["level"] == "verified"

    def test_exact_version_level(self):
        assert compat_level("aedt", "2023.1") == "verified"
        assert compat_level("ads", "2027") == "verified"

    def test_unknown_version_uses_default(self):
        assert compat_level("aedt", "2099.9") == "best_effort"

    def test_matrix_corruption_is_nonfatal(self, monkeypatch):
        from rfauto.infra import version_probe as vp

        monkeypatch.setattr(vp, "_COMPAT_MATRIX_PATH", Path("no/such/file.yaml"))
        assert vp.load_compat_matrix() == {}
        assert compat_level("aedt", "2023.1") == "best_effort"
