"""DP-11 P1：LibreVNA SCPI 命令映射单源钉（criteria.md G2）。

- 命令常量集中在 measurement/librevna.py 一个模块（grep 钉：命令串不得
  散落消费方）；
- TRACe:DATA? / TRACe:LIST? 解析与官方 ProgrammingGuide 示例逐字节一致；
- 未知型号显式 ValueError 不静默；
- LibreVNAInterface 接进 VNAInterface 协议（connect→calibrate→capture→
  close）走注入 transport（#139：零网络零硬件）。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from rfauto.measurement import librevna
from rfauto.measurement.librevna import (
    CMD_ACQ_FINISHED_Q,
    CMD_CAL_ACTIVE_Q,
    CMD_IDN,
    CMD_TRACE_DATA_Q,
    CMD_TRACE_LIST_Q,
    LibreVNADriver,
    LibreVNAInterface,
    check_known_model,
    parse_trace_data,
    parse_trace_list,
)

# 官方 ProgrammingGuide §VNA:TRACe:DATA 示例应答（逐字节口径）
_OFFICIAL_SAMPLE = (
    "[1e+6,0.400172,0.0377869],[6.67556e+8,-0.0922281,-0.00990373],"
    "[1.33411e+9,-0.0341439,-0.0331184],"
)


class _ScriptedTransport:
    """脚本化 transport：按序应答/记录写序列（无 socket 无 pyvisa）。"""

    def __init__(self, responses: dict[str, str]):
        self.responses = responses
        self.queries: list[str] = []
        self.written: list[str] = []
        self.closed = False

    def query(self, command: str) -> str:
        self.queries.append(command)
        key = next((k for k in self.responses if command.startswith(k)), None)
        if key is None:
            raise AssertionError(f"未声明的 query: {command!r}")
        return self.responses[key]

    def write(self, command: str) -> None:
        self.written.append(command)

    def close(self) -> None:
        self.closed = True


class TestSingleSourceCommands:
    """命令集单源：消费方不得散落命令字面量（grep 钉）。"""

    def test_command_constants_shape(self):
        # 命令常量与官方节名逐条对应（出处见 librevna.py 注释）
        assert CMD_IDN == "*IDN?"
        assert CMD_ACQ_FINISHED_Q == "VNA:ACQuisition:FINished?"
        assert CMD_CAL_ACTIVE_Q == "VNA:CALibration:ACTIVE?"
        assert CMD_TRACE_LIST_Q == "VNA:TRACe:LIST?"
        assert CMD_TRACE_DATA_Q == "VNA:TRACe:DATA?"

    def test_commands_not_scattered_outside_module(self):
        """命令字面量不得出现在 librevna.py/vna_adapter.py 之外的 src 消费方。"""
        src = Path(librevna.__file__).parent
        offenders: list[str] = []
        for py in src.glob("*.py"):
            if py.name in ("librevna.py",):
                continue
            text = py.read_text(encoding="utf-8")
            if re.search(r'"VNA:(TRACe|ACQuisition|CALibration|FREQuency)', text):
                offenders.append(py.name)
        assert offenders == []

    def test_unknown_model_raises_explicitly(self):
        with pytest.raises(ValueError, match="未知 VNA 型号"):
            check_known_model("copper_mountain_m5k")  # 暂缓型号：显式报错
        # 白名单内（含空串=纯 raw SCPI 逃生口）不报错
        for model in ("librevna", "pna", "fieldfox", "znb", "zva",
                      "nanovna2", "mock", ""):
            check_known_model(model)

    def test_default_port_documented(self):
        assert librevna.LIBREVNA_DEFAULT_PORT == 19542


class TestTraceParsing:
    """TRACe:DATA?/LIST? 应答解析（官方示例逐字节）。"""

    def test_parse_trace_data_official_sample(self):
        freq, values = parse_trace_data(_OFFICIAL_SAMPLE)
        assert freq[0] == 1e6
        assert values[0] == complex(0.400172, 0.0377869)
        assert values[1] == complex(-0.0922281, -0.00990373)
        assert freq[2] == 1.33411e9
        assert len(freq) == len(values) == 3

    def test_parse_trace_data_empty_raises(self):
        with pytest.raises(ValueError, match="无可解析元组"):
            parse_trace_data("")

    def test_parse_trace_list(self):
        assert parse_trace_list("S11,S12,S21,S22") == \
            ["S11", "S12", "S21", "S22"]
        with pytest.raises(ValueError):
            parse_trace_list("  ")


class TestDriver:
    """驱动行为：扫频序列/单次触发轮询/校准态/SNP 组装。"""

    def _driver(self, calibrated="SOLT", finished="TRUE"):
        transport = _ScriptedTransport({
            CMD_IDN: "LibreVNA,LibreVNA-GUI,SN00042,1.0.4",
            CMD_ACQ_FINISHED_Q: finished,
            CMD_CAL_ACTIVE_Q: calibrated,
            CMD_TRACE_LIST_Q: "S11,S12,S21,S22",
            f"{CMD_TRACE_DATA_Q} S11":
                "[1e9,0.1,0.0],[2e9,0.2,0.1],",
            f"{CMD_TRACE_DATA_Q} S12":
                "[1e9,0.0,-0.9],[2e9,0.0,-0.9],",
            f"{CMD_TRACE_DATA_Q} S21":
                "[1e9,0.0,-0.9],[2e9,0.0,-0.9],",
            f"{CMD_TRACE_DATA_Q} S22":
                "[1e9,0.03,0.09],[2e9,-0.1,0.0],",
        })
        return LibreVNADriver(transport), transport

    def test_idn_roundtrip(self):
        driver, _ = self._driver()
        assert driver.idn.startswith("LibreVNA,")

    def test_setup_sweep_writes_official_commands(self):
        driver, transport = self._driver()
        driver.setup_sweep(1e9, 3e9, 5, 1000.0)
        assert transport.written == [
            "VNA:FREQuency:START 1000000000.000000",
            "VNA:FREQuency:STOP 3000000000.000000",
            "VNA:ACQuisition:POINTS 5",
            "VNA:ACQuisition:IFBW 1000.000000",
        ]

    def test_trigger_single_sweep_true(self):
        driver, transport = self._driver()
        assert driver.trigger_single_sweep(timeout_s=1.0) is True
        assert "VNA:ACQuisition:SINGLE TRUE" in transport.written
        assert "VNA:ACQuisition:RUN" in transport.written

    def test_trigger_timeout_returns_false(self):
        driver, _ = self._driver(finished="FALSE")
        assert driver.trigger_single_sweep(timeout_s=0.1) is False

    def test_calibration_state(self):
        driver, _ = self._driver(calibrated="SOLT")
        assert driver.is_calibrated() is True
        assert driver.active_calibration() == "SOLT"
        driver2, _ = self._driver(calibrated="")
        assert driver2.is_calibrated() is False

    def test_get_snp_network_assembles_full_matrix(self):
        driver, _ = self._driver()
        net = driver.get_snp_network()
        assert net.nports == 2
        assert len(net.f) == 2
        assert net.s[0, 0, 0] == complex(0.1, 0.0)
        assert net.s[0, 1, 0] == net.s[0, 0, 1] == complex(0.0, -0.9)
        assert driver.missing_traces == []

    def test_partial_traces_marked_missing(self):
        transport = _ScriptedTransport({
            CMD_TRACE_LIST_Q: "S11,S21",
            f"{CMD_TRACE_DATA_Q} S11": "[1e9,0.1,0.0],",
            f"{CMD_TRACE_DATA_Q} S21": "[1e9,0.0,-0.9],",
        })
        driver = LibreVNADriver(transport)
        net = driver.get_snp_network()
        assert net.nports == 2
        assert driver.missing_traces == ["S12", "S22"]
        assert net.s[0, 0, 1] == 0.0  # 未测元素零填充（掩码由 adapter 补）


class TestLibreVNAInterface:
    """VNAInterface 协议接入（vna_capture 只读复用）。"""

    def _interface(self, calibrated="SOLT"):
        driver, transport = TestDriver()._driver(calibrated=calibrated)
        from rfauto.measurement.vna_capture import VNAConfig

        return LibreVNAInterface(
            VNAConfig(address="host:19542", model="librevna"), driver=driver
        ), transport

    def test_connect_calibrate_capture_close(self):
        iface, transport = self._interface()
        assert iface.connect() is True
        cal = iface.calibrate()
        assert cal["ok"] and cal["calibrated"] is True
        assert "CAL:ACTIVE=SOLT" in cal["detail"]
        net = iface.capture()
        assert net is not None and net.nports == 2
        iface.close()
        assert transport.closed is True
        assert iface._connected is False

    def test_connect_requires_driver(self):
        iface = LibreVNAInterface(driver=None)
        assert iface.connect() is False

    def test_uncalibrated_reported(self):
        iface, _ = self._interface(calibrated="")
        iface.connect()
        cal = iface.calibrate()
        assert cal["ok"] and cal["calibrated"] is False

    def test_probe_capabilities_driver_label(self):
        iface, _ = self._interface()
        iface.connect()
        caps = iface.probe_capabilities()
        assert caps["driver"] == "librevna"
        assert caps["idn"].startswith("LibreVNA,")
