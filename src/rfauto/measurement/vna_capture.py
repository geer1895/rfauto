"""Direction 3: VNA capture interface (skrf instruments adapter).

缺口修复（#12）：
- skrf 2.x 的 `skrf.vi.Network` 不存在——真机路径现走 `skrf.vi.vna` 驱动类
  （keysight.PNA / keysight.FieldFox / rohde_schwarz.ZNB 等，pyvisa 底座），
  驱动不可用时回退到**完整实现的** raw SCPI 测量（此前 `_raw_measure` 解析后
  恒 return None，真机采集实际不可用）；
- 补 `calibrate()`（校准态查询 + 会话记录）——此前 docstring 宣称协议含
  calibrate 但方法不存在，capture→calibrate→correlate 全链无法走通；
- 录制/回放（JSONL 会话流）保留，L1（无硬件 CI）口径以回放 + mock 仪器覆盖；
  **补强17（§10.22）**：新增 `MockVNAInstrument` mock 仪表驱动（model="mock"，
  从历史 Touchstone 供数，SCPI 表面与 raw 路兼容）与 `run_offline_replay()`
  离线回放回归（历史 .s2p 走完 采集→校准→相关 链，零硬件）。

pyvisa 是可选依赖（extras `vna`）；模块顶层不 import skrf.vi（其依赖 pyvisa，
缺装时 import 即炸），驱动解析延迟到 connect()。
"""

from __future__ import annotations

import contextlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import skrf

if TYPE_CHECKING:
    from rfauto.measurement.calibration import CalibrationKit

# model → skrf.vi.vna 驱动类路径（延迟解析；值为 (module, class)）
DRIVERS: dict[str, tuple[str, str]] = {
    "pna": ("skrf.vi.vna.keysight", "PNA"),
    "fieldfox": ("skrf.vi.vna.keysight", "FieldFox"),
    "znb": ("skrf.vi.vna.rohde_schwarz", "ZNB"),
    "zva": ("skrf.vi.vna.rohde_schwarz", "ZVA"),
}
#: mock 驱动的 model 键（connect() 走 MockVNAInstrument，不经 pyvisa/skrf.vi）
MOCK_MODEL = "mock"


class MockVNAInstrument:
    """Mock 仪表驱动（补强17，§10.22）：从录制的历史 Touchstone 供数。

    L1（无硬件 CI）口径的仪表替身：
    - `query()` 实现与 `VNAInterface._raw_measure` 最小公共命令集兼容的
      SCPI 表面（*IDN? / SENS<x>:CORR:STATE? / SENS<x>:FREQ:DATA? /
      CALC<x>:DATA:SDAT?），数据全部来自构造时注入的历史 skrf.Network；
    - `get_snp_network()` 回放完整 N 端口 Network（capture 的 mock 主路），
      屏蔽该方法（置 None）即可测 raw SCPI 逃生口路径。
    """

    def __init__(self, network: skrf.Network, *,
                 idn: str = "MOCK_VNA,REPLAY,SN0000,FW1.0",
                 calibrated: bool = True):
        self.network = network
        self.idn = idn
        self.calibrated = bool(calibrated)
        self.written: list[str] = []

    @classmethod
    def from_touchstone(cls, path: str | Path, **kwargs: Any) -> MockVNAInstrument:
        """从历史 Touchstone 文件（.s1p/.s2p/...）构造回放源。"""
        net = skrf.Network(str(Path(path)))
        kwargs.setdefault("idn", f"MOCK_VNA,REPLAY,{Path(path).name},FW1.0")
        return cls(net, **kwargs)

    # ── SCPI 表面（与 _raw_measure 消费格式逐一对齐）────────────────────────
    def query(self, command: str) -> str:
        cmd = command.strip()
        if cmd == "*IDN?":
            return self.idn
        if re.fullmatch(r"SENS\d+:CORR:STATE\?", cmd):
            return "1" if self.calibrated else "0"
        if re.fullmatch(r"SENS\d+:FREQ:DATA\?", cmd):
            return ",".join(repr(float(f)) for f in self.network.f)
        if re.fullmatch(r"CALC\d+:DATA:SDAT\?", cmd):
            trace = self.network.s[:, 0, 0]
            pairs: list[str] = []
            for z in trace:
                pairs.append(repr(float(np.real(z))))
                pairs.append(repr(float(np.imag(z))))
            return ",".join(pairs)
        return "0"

    def write(self, command: str) -> None:
        self.written.append(command)

    # ── capture 的 mock 主路 ────────────────────────────────────────────────
    def get_snp_network(self, ports: list[int] | None = None) -> skrf.Network:
        """回放完整 N 端口历史网络（返回副本，防调用方污染回放源）。"""
        return self.network.copy()

    def close(self) -> None:  # pragma: no cover - 无资源可释放
        return None


@dataclass
class VNASession:
    """VNA session recording entry."""
    timestamp: float
    command: str
    response: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class VNAConfig:
    """VNA connection configuration."""
    address: str = ""  # VISA address (e.g., "TCPIP0::192.168.1.1::inst0::INSTR")
    model: str = ""    # DRIVERS 的键："pna" | "fieldfox" | "znb" | "zva" | "mock"（空=纯 raw SCPI）
    timeout_ms: int = 10000
    n_points: int = 201
    freq_range_ghz: tuple[float, float] = (0.1, 10.0)
    if_bandwidth_hz: float = 1000.0
    channel: int = 1   # raw SCPI 模式使用的 channel/calc 编号
    # ── mock 驱动（model="mock"）专用 ────────────────────────────────────────
    mock_source: str = ""      # 历史 Touchstone 文件路径（回放数据源，必填）
    mock_calibrated: bool = True  # SENS<x>:CORR:STATE? 的应答（校准态）


def _resolve_driver(model: str):
    """按 model 解析 skrf.vi.vna 驱动类；未知/未装 pyvisa 返回 None。"""
    entry = DRIVERS.get(model.lower())
    if entry is None:
        return None
    import importlib
    try:
        module = importlib.import_module("skrf.vi.vna")
        obj = module
        for part in entry[0].split(".")[3:]:
            obj = getattr(obj, part)
        return getattr(obj, entry[1])
    except Exception:  # pyvisa 缺装/驱动不存在——回退 raw SCPI
        return None


class VNAInterface:
    """VNA capture interface (protocol: connect → capture → calibrate → close).

    优先 skrf.vi 驱动类；驱动缺失或型号未知时走 raw SCPI 逃生口
    （计划方向 3：FieldFox 等型号 skrf.vi 支持不完整，逃生口是硬需求）。
    """

    def __init__(self, config: VNAConfig | None = None):
        self.config = config or VNAConfig()
        self._instrument = None  # skrf.vi 驱动实例或 pyvisa resource
        self._skrf_driver = False
        self._mock_driver = False
        self._session_log: list[VNASession] = []
        self._connected = False

    # ── 连接 ────────────────────────────────────────────────────────────────

    def connect(self) -> bool:
        """Connect via skrf.vi driver when available, else raw pyvisa."""
        if not self.config.address:
            return False
        try:
            if self.config.model.lower() == MOCK_MODEL:
                if not self.config.mock_source:
                    raise ValueError(
                        "mock 驱动需要 VNAConfig.mock_source 指向历史 Touchstone 文件")
                self._instrument = MockVNAInstrument.from_touchstone(
                    self.config.mock_source, calibrated=self.config.mock_calibrated)
                self._mock_driver = True
                self._skrf_driver = False
                idn = self._instrument.idn
            else:
                driver_cls = _resolve_driver(self.config.model)
                if driver_cls is not None:
                    self._instrument = driver_cls(self.config.address)
                    self._skrf_driver = True
                    idn = f"skrf.vi driver: {driver_cls.__name__}"
                else:
                    import pyvisa
                    rm = pyvisa.ResourceManager()
                    self._instrument = rm.open_resource(self.config.address)
                    self._instrument.timeout = self.config.timeout_ms
                    idn = str(self._instrument.query("*IDN?")).strip()
            self._log("connect", idn)
            self._connected = True
            return True
        except Exception as e:
            self._log("connect_failed", str(e))
            return False

    # ── 能力探测 / 校准 ─────────────────────────────────────────────────────

    def probe_capabilities(self) -> dict[str, Any]:
        """Probe VNA model capabilities（校准类型/点数/格式探测钩子）。"""
        if not self._connected:
            return {"connected": False}
        caps: dict[str, Any] = {
            "connected": True,
            "model": self.config.model,
            "driver": ("mock" if self._mock_driver
                       else ("skrf.vi" if self._skrf_driver else "raw_scpi")),
            "n_points": self.config.n_points,
            "freq_range_ghz": list(self.config.freq_range_ghz),
        }
        with contextlib.suppress(Exception):
            caps["idn"] = str(self.raw_scpi("*IDN?")).strip()
        return caps

    def calibrate(self) -> dict[str, Any]:
        """校准态查询与记录（方向 3：校准后验证 cal kit 定义一致性）。

        真机语义：查询校准修正是否已应用（PNA: SENS:CORR:STATE?）；驱动差异
        以 raw_scpi 逃生口兜底，查询失败不抛错（记录 unknown）。
        """
        if not self._connected:
            return {"ok": False, "calibrated": False, "detail": "not connected"}
        ch = self.config.channel
        try:
            resp = str(self.raw_scpi(f"SENS{ch}:CORR:STATE?")).strip()
            calibrated = resp.upper() in ("1", "ON")
            result = {"ok": True, "calibrated": calibrated, "detail": f"CORR:STATE={resp}"}
        except Exception as e:
            result = {"ok": False, "calibrated": False, "detail": f"query failed: {e}"}
        self._log("calibrate", result["detail"], calibrated=result.get("calibrated"))
        return result

    # ── 采集 ────────────────────────────────────────────────────────────────

    def capture(self, ports: list[int] | None = None) -> skrf.Network | None:
        """Capture S-parameters, preferring skrf.vi driver, falling back to raw SCPI."""
        if not self._connected:
            return None
        try:
            get_snp = getattr(self._instrument, "get_snp_network", None)
            if (self._skrf_driver or self._mock_driver) and callable(get_snp):
                net = self._instrument.get_snp_network(ports=ports or [1, 2])
                self._log("capture", f"driver get_snp_network: {net}")
                return net
            net = self._raw_measure()
            if net is not None:
                self._log("capture", f"raw_scpi: {net}")
                return net
            self._log("capture_failed", "no measurement path produced a Network")
            return None
        except Exception as e:
            self._log("capture_failed", str(e))
            return None

    def raw_scpi(self, command: str) -> str:
        """Raw SCPI command (escape hatch，计划方向 3 硬需求)."""
        if not self._connected or self._instrument is None:
            return ""
        response = self._instrument.query(command)
        self._log("raw_scpi", f"{command} -> {str(response)[:100]}")
        return response

    def _raw_measure(self) -> skrf.Network | None:
        """Raw SCPI S-parameter measurement（完整实现——缺口 #12）。

        PNA/ZNB 兼容的最小公共命令集：
          SENS<x>:FREQ:DATA?   频率数组（Hz）
          CALC<x>:DATA:SDAT?   复数 S 数据（re,im 交替，当前测量 = S11 或激活迹线）
        """
        if self._instrument is None:
            return None
        ch = self.config.channel
        try:
            freq_raw = self._instrument.query(f"SENS{ch}:FREQ:DATA?")
            data_raw = self._instrument.query(f"CALC{ch}:DATA:SDAT?")
            freq = [float(x) for x in str(freq_raw).strip().split(",") if x.strip()]
            values = [float(x) for x in str(data_raw).strip().split(",") if x.strip()]
            if not freq or len(values) < 2:
                return None
            n = min(len(values) // 2, len(freq))
            s = np_complex_pairs(values, n)
            frequency = skrf.Frequency.from_f(freq[:n], unit="hz")
            return skrf.Network(frequency=frequency, s=s.reshape(-1, 1, 1))
        except Exception:
            return None

    def apply_cal_kit(self, calkit, measured_network) -> dict[str, Any]:
        """应用校准套件到测量网络（方向 3：cal kit 按 ID 管理的执行端）。

        calkit: measurement.calibration.load_calkit() 返回的 CalibrationKit。
        响应式 kit（method=NONE + thru 标准件）走归一化去嵌；SOLT/TRL 委托
        apply_calibration。全程写入会话日志。
        """
        from rfauto.measurement.calibration import CalibrationMethod, apply_calibration
        from rfauto.measurement.import_data import MeasurementData

        cal = MeasurementData(network=measured_network, metadata=None,
                              source_file="vna_capture", n_ports=measured_network.nports,
                              freq_range_ghz=(float(measured_network.f[0]) / 1e9,
                                              float(measured_network.f[-1]) / 1e9))
        if calkit.method == CalibrationMethod.NONE and calkit.standards:
            from rfauto.measurement.calibration import apply_response_calibration
            thru = next(s.network for s in calkit.standards
                        if s.standard_type == "through")
            result = apply_response_calibration(cal, thru)
        else:
            result = apply_calibration(cal, calkit)
        self._log("apply_cal_kit", f"kit={calkit.name} calibrated={result.is_calibrated}",
                  calibrated=result.is_calibrated)
        return result.to_dict()

    def close(self) -> None:
        """Close VNA connection."""
        if self._instrument is not None:
            import contextlib
            with contextlib.suppress(Exception):
                close_fn = getattr(self._instrument, "close", None)
                if callable(close_fn):
                    if self._mock_driver:
                        close_fn()
                    elif self._skrf_driver:
                        conn = getattr(self._instrument, "con", None)
                        if conn is not None:
                            with contextlib.suppress(Exception):
                                conn.close()
                    else:
                        close_fn()
        self._connected = False
        self._log("close", "session ended")

    # ── 录制 / 回放 ─────────────────────────────────────────────────────────

    def save_session(self, path: str | Path) -> None:
        """Save session log as JSONL."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for entry in self._session_log:
                f.write(json.dumps({
                    "ts": entry.timestamp,
                    "command": entry.command,
                    "response": entry.response,
                    **entry.metadata,
                }, ensure_ascii=False) + "\n")

    def _log(self, command: str, response: str, **meta: Any) -> None:
        self._session_log.append(VNASession(
            timestamp=time.time(), command=command, response=response, metadata=meta
        ))


def np_complex_pairs(values: list[float], n: int):
    """[re0, im0, re1, im1, ...] → complex ndarray (n,)。"""
    import numpy as np
    return np.array([complex(values[2 * i], values[2 * i + 1]) for i in range(n)], dtype=complex)


def load_session(path: str | Path) -> list[dict[str, Any]]:
    """Load a recorded JSONL session."""
    entries = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def replay_session(session_entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Replay a recorded session (for CI testing)."""
    results = []
    for entry in session_entries:
        cmd = entry.get("command", "")
        if cmd == "connect":
            results.append({"command": cmd, "response": "MOCK_VNA,SN12345,FW1.0", "ok": True})
        elif cmd == "capture":
            results.append({"command": cmd, "response": "mock_sparams", "ok": True})
        elif cmd == "calibrate":
            results.append({"command": cmd, "response": "CORR:STATE=1", "ok": True})
        elif cmd == "close":
            results.append({"command": cmd, "response": "closed", "ok": True})
        else:
            results.append({"command": cmd, "response": entry.get("response", ""), "ok": True})
    return results


# ─── 补强17（§10.22）：离线回放回归——历史 .s2p 走完 采集→校准→相关 链 ─────────

def run_offline_replay(
    measured_s2p: str | Path,
    sim_s2p: str | Path | None = None,
    calkit: CalibrationKit | None = None,
    *,
    threshold_db: float = 3.0,
    config: VNAConfig | None = None,
    session_path: str | Path | None = None,
) -> dict[str, Any]:
    """硬件阻塞下的 VNA 软侧回放回归：采集 → 校准 → 相关 全链（零硬件）。

    - **采集**：model="mock" 经 `MockVNAInstrument` 从历史 Touchstone 供数，
      `capture()` 走驱动主路真实产出 skrf.Network；
    - **校准**：calkit 给定时按套件方法应用（响应式 kit——method=NONE 且含
      thru 标准件——走 thru 归一化去嵌）；None = 原样比对（cal=None）；
    - **相关**：`compute_correlation`（dB 偏差门 + D12 FSV 曲线级等级）。

    单步失败记录进结果不炸链（#105：观测/回归链不得成为故障点）；
    会话 JSONL 落盘为 best-effort（session_path 给定时）。

    Returns:
        dict：{ok, connect, calibrate, capture, calibration, correlation}；
        connect 失败 / capture 无网络时提前返回且 ok=False。
    """
    from rfauto.measurement.calibration import (
        CalibrationMethod,
        apply_calibration,
        apply_response_calibration,
    )
    from rfauto.measurement.correlate import compute_correlation
    from rfauto.measurement.import_data import MeasurementData, import_touchstone

    sim_path = Path(sim_s2p) if sim_s2p is not None else Path(measured_s2p)
    cfg = config or VNAConfig(address="MOCK", model=MOCK_MODEL,
                              mock_source=str(measured_s2p))
    if not cfg.model:
        cfg.model = MOCK_MODEL  # 显式给 config 时兜底走 mock（回放语义）
    if not cfg.mock_source:
        cfg.mock_source = str(measured_s2p)

    result: dict[str, Any] = {
        "ok": False,
        "measured_file": str(measured_s2p),
        "sim_file": str(sim_path),
    }
    vna = VNAInterface(cfg)
    connected = vna.connect()
    result["connect"] = {"ok": connected,
                         "driver": "mock" if vna._mock_driver else "other"}
    if not connected:
        result["error"] = "mock connect failed"
        return result
    try:
        result["calibrate"] = vna.calibrate()
        net = vna.capture()
        if net is None:
            result["capture"] = {"ok": False, "error": "capture produced no Network"}
            result["error"] = "capture failed"
            return result
        result["capture"] = {
            "ok": True,
            "n_ports": int(net.nports),
            "n_points": len(net.f),
            "freq_range_ghz": [float(net.f[0]) / 1e9, float(net.f[-1]) / 1e9],
        }

        measured = MeasurementData(
            network=net, metadata=None, source_file=str(measured_s2p),
            n_ports=net.nports,
            freq_range_ghz=(float(net.f[0]) / 1e9, float(net.f[-1]) / 1e9),
        )
        if calkit is not None:
            thru = None
            if calkit.method == CalibrationMethod.NONE and calkit.standards:
                thru = next((s.network for s in calkit.standards
                             if s.standard_type == "through"), None)
            cal_result = (apply_response_calibration(measured, thru) if thru is not None
                          else apply_calibration(measured, calkit))
            corrected = cal_result.calibrated_network
            if corrected is not None:
                measured = MeasurementData(
                    network=corrected, metadata=measured.metadata,
                    source_file=measured.source_file, n_ports=measured.n_ports,
                    freq_range_ghz=measured.freq_range_ghz)
            result["calibration"] = cal_result.to_dict()
        else:
            result["calibration"] = None

        sim = import_touchstone(sim_path)
        correlation = compute_correlation(sim, measured, threshold_db=threshold_db)
        result["correlation"] = correlation.to_dict()
        result["ok"] = True
    finally:
        vna.close()
        if session_path is not None:
            with contextlib.suppress(Exception):
                vna.save_session(session_path)
    return result
