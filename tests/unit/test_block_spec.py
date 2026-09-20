"""E8a 器件模型库单元测试。

验收标准：
① BlockSpec 数据模型 + 类型校验
② DeviceCatalog 从 catalog.yaml 加载
③ 有源器件必须有 NF/P1dB（物理事实）
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rfauto.core.block_spec import BlockSpec, DeviceCatalog, DeviceType

PARTS_DIR = Path(__file__).resolve().parent.parent.parent / "parts"


class TestBlockSpec:
    """BlockSpec 数据模型测试。"""

    def test_passive_device(self):
        b = BlockSpec(
            name="wilkinson", device_type=DeviceType.PASSIVE,
            s_params_path="test.s2p", ports=["in", "out1", "out2"],
        )
        assert b.is_passive()
        assert b.n_ports == 3
        assert b.validate() == []

    def test_active_requires_nf_and_gain(self):
        """有源器件必须有 NF 和 gain。"""
        b = BlockSpec(name="lna", device_type=DeviceType.ACTIVE)
        issues = b.validate()
        assert any("nf_db" in i for i in issues)
        assert any("gain_db" in i for i in issues)

    def test_active_with_all_fields(self):
        b = BlockSpec(
            name="lna", device_type=DeviceType.ACTIVE,
            gain_db=20.0, nf_db=0.8, p1db_dbm=15.0,
        )
        assert b.validate() == []

    def test_mixer_requires_conversion_loss(self):
        """混频器必须有转换损耗。"""
        b = BlockSpec(name="mixer", device_type=DeviceType.MIXER)
        issues = b.validate()
        assert any("conversion_loss_db" in i for i in issues)

    def test_to_dict(self):
        b = BlockSpec(
            name="test", device_type=DeviceType.PASSIVE,
            z0=75.0, ports=["a", "b"],
        )
        d = b.to_dict()
        assert d["z0"] == 75.0
        assert d["ports"] == ["a", "b"]


class TestDeviceCatalog:
    """DeviceCatalog 测试。"""

    def test_from_yaml(self):
        """从 catalog.yaml 加载。"""
        catalog_path = PARTS_DIR / "catalog.yaml"
        if not catalog_path.exists():
            pytest.fail("parts/catalog.yaml 缺失——器件库被移动或损坏，显式失败而非静默跳过")

        catalog = DeviceCatalog.from_yaml(catalog_path)
        assert len(catalog.all) > 0

    def test_get_device(self):
        catalog_path = PARTS_DIR / "catalog.yaml"
        if not catalog_path.exists():
            pytest.fail("parts/catalog.yaml 缺失——器件库被移动或损坏，显式失败而非静默跳过")

        catalog = DeviceCatalog.from_yaml(catalog_path)
        lna = catalog.get("lna_2ghz")
        assert lna.is_active()
        assert lna.gain_db == 20.0
        assert lna.nf_db == 0.8

    def test_list_by_type(self):
        catalog_path = PARTS_DIR / "catalog.yaml"
        if not catalog_path.exists():
            pytest.fail("parts/catalog.yaml 缺失——器件库被移动或损坏，显式失败而非静默跳过")

        catalog = DeviceCatalog.from_yaml(catalog_path)
        passives = catalog.list_devices(DeviceType.PASSIVE)
        actives = catalog.list_devices(DeviceType.ACTIVE)
        assert len(passives) > 0
        assert len(actives) > 0

    def test_unknown_device_raises(self):
        catalog_path = PARTS_DIR / "catalog.yaml"
        if not catalog_path.exists():
            pytest.fail("parts/catalog.yaml 缺失——器件库被移动或损坏，显式失败而非静默跳过")

        catalog = DeviceCatalog.from_yaml(catalog_path)
        with pytest.raises(KeyError):
            catalog.get("nonexistent_device")

    def test_catalog_validate_all(self):
        """catalog 中所有器件应通过校验。"""
        catalog_path = PARTS_DIR / "catalog.yaml"
        if not catalog_path.exists():
            pytest.fail("parts/catalog.yaml 缺失——器件库被移动或损坏，显式失败而非静默跳过")

        catalog = DeviceCatalog.from_yaml(catalog_path)
        for name, spec in catalog.all.items():
            issues = spec.validate()
            assert issues == [], f"{name}: {issues}"
