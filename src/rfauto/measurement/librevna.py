"""DP-11 P1：LibreVNA 自建 SCPI 命令映射（**单源**，规格书 §2）。

背景（runs/df6_a3/skrf2x_audit.md）：skrf 2.1.0 的 ``skrf.vi.vna`` 驱动面
只有 PNA/FieldFox/ZNB/ZVA/NanoVNAv2/HP8510——**无 LibreVNA 驱动**，命令
映射必须自建。本模块是 LibreVNA 命令集的唯一事实来源（single source）：
命令常量、语义注释（含官方出处节名）、应答解析全部集中在此，adapter/测试
只消费本模块的表面，不散落命令串。

语义口径（官方 ProgrammingGuide.tex，2026-09-24 自 jankae/LibreVNA@master
``Documentation/UserManual`` 拉取，存档 runs/df6_dp11vna/_progguide.tex）：

- TCP SCPI server **单客户端**：第二连接会把第一连接顶掉（§SCPI Server
  Configuration）；每条 query 的应答以换行结尾。
- ``*IDN?``（§*IDN）→ ``LibreVNA,LibreVNA-GUI,<serial>,<software version>``。
- 扫频（§VNA:ACQuisition:*）：``RUN``/``RUN?``（TRUE/FALSE）、
  ``STOP``、``SINGLE``/``SINGLE?``（TRUE/FALSE，单次扫频模式）、
  ``POINTS``/``POINTS?``、``IFBW``/``IFBW?``、``FINished?``（平均滤波
  达稳态 TRUE/FALSE——单次模式下兼作扫频完成轮询口）。
- 频率（§VNA:FREQuency:*）：``START``/``STOP``（Hz）及其 ``?``。
- 校准（§VNA:CALibration:*）：``ACTIVE?``（当前激活校准类型）、
  ``ACTivate?``（可用类型清单）、``ACTivate <type>``。
- 迹线（§VNA:TRACe:*）：``LIST?``（逗号分隔迹线名，如 ``S11,S12,S21,S22``）、
  ``DATA? <trace>``（应答为 ``[x,real(y),imag(y)],`` 元组序列，仅在末尾
  有换行）。

消费面约定：本驱动与 ``measurement.vna_capture.MockVNAInstrument`` 同款
鸭子类型表面（``query``/``write``/``get_snp_network``/``close``），可直
接塞进 ``VNAInterface._instrument`` 走既有 capture/会话记录链
（vna_capture.py 只读复用，不破坏）。

传输层：真机=裸 TCP socket（单客户端，官方口径，免 VISA 运行时依赖）；
测试=注入任意实现 ``query``/``write`` 的对象（pyvisa-sim 资源，#139：
通道钉死，无真实网络）。
"""

from __future__ import annotations

import contextlib
import re
import socket
import time
from typing import Any

import numpy as np
import skrf

from rfauto.measurement.vna_capture import VNAConfig, VNAInterface

#: model 键（VNAConfig.model 语义）：librevna 走本模块映射；
#: pna/fieldfox/znb/zva 走 skrf.vi（vna_capture.DRIVERS）；nanovna2 走
#: skrf.vi（v2.x 驱动面在装）；mock 走 vna_capture.MockVNAInstrument；
#: 空串=纯 raw SCPI 逃生口。**除此之外的型号显式报错不静默**。
KNOWN_VNA_MODELS: tuple[str, ...] = (
    "librevna", "pna", "fieldfox", "znb", "zva", "nanovna2", "mock", "",
)

#: LibreVNA SCPI 缺省端口（GUI 偏好可改，官方 ``--port`` 参数语义）。
LIBREVNA_DEFAULT_PORT = 19542

# ─── 命令常量（单源；注释=ProgrammingGuide.tex 出处节名）─────────────────────

CMD_IDN = "*IDN?"                                # §*IDN
CMD_ACQ_RUN = "VNA:ACQuisition:RUN"              # §VNA:ACQuisition:RUN
CMD_ACQ_RUN_Q = "VNA:ACQuisition:RUN?"           # §VNA:ACQuisition:RUN
CMD_ACQ_STOP = "VNA:ACQuisition:STOP"            # §VNA:ACQuisition:STOP
CMD_ACQ_SINGLE = "VNA:ACQuisition:SINGLE"        # §VNA:ACQuisition:SINGLE
CMD_ACQ_FINISHED_Q = "VNA:ACQuisition:FINished?"  # §VNA:ACQuisition:FINished
CMD_ACQ_POINTS = "VNA:ACQuisition:POINTS"        # §VNA:ACQuisition:POINTS
CMD_ACQ_IFBW = "VNA:ACQuisition:IFBW"            # §VNA:ACQuisition:IFBW
CMD_FREQ_START = "VNA:FREQuency:START"           # §VNA:FREQuency:START
CMD_FREQ_STOP = "VNA:FREQuency:STOP"             # §VNA:FREQuency:STOP
CMD_CAL_ACTIVE_Q = "VNA:CALibration:ACTIVE?"     # §VNA:CALibration:ACTIVE
CMD_CAL_AVAILABLE_Q = "VNA:CALibration:ACTivate?"  # §VNA:CALibration:ACTivate
CMD_TRACE_LIST_Q = "VNA:TRACe:LIST?"             # §VNA:TRACe:LIST
CMD_TRACE_DATA_Q = "VNA:TRACe:DATA?"             # §VNA:TRACe:DATA?

#: 未校准语义：ACTIVE? 应答为空串/无校准标记（官方"Currently active
#: calibration type"，无校准时为空；防御性再收 NONE/FALSE/OFF）。
_UNCALIBRATED_ACTIVE = ("", "NONE", "FALSE", "OFF")

#: ``[x,re,im],`` 元组解析（应答仅末尾换行，元组间逗号分隔）。
_TUPLE_RE = re.compile(r"\[([^[\]]*)\]")


def check_known_model(model: str) -> str:
    """model 键白名单校验：未知型号显式 ValueError（不静默，规格书 §6 风险条）。"""
    key = str(model or "").strip().lower()
    if key not in KNOWN_VNA_MODELS:
        raise ValueError(
            f"未知 VNA 型号: {model!r}（支持 {', '.join(k for k in KNOWN_VNA_MODELS if k)}；"
            "新型号须先在 measurement.librevna.KNOWN_VNA_MODELS 显式登记命令映射）")
    return key


def parse_trace_data(response: str) -> tuple[np.ndarray, np.ndarray]:
    """解析 ``VNA:TRACe:DATA?`` 应答 → (freq_hz, complex ndarray)。

    官方应答形态（§VNA:TRACe:DATA 示例）::
        [1e+6,0.400172,0.0377869],[6.67556e+8,...],...
    """
    tuples = _TUPLE_RE.findall(str(response))
    if not tuples:
        raise ValueError(f"TRACe:DATA? 应答无可解析元组: {str(response)[:80]!r}")
    freqs: list[float] = []
    values: list[complex] = []
    for tup in tuples:
        parts = [p for p in tup.split(",") if p.strip()]
        if len(parts) < 3:
            raise ValueError(f"元组不足 3 分量（x,re,im）: {tup!r}")
        freqs.append(float(parts[0]))
        values.append(complex(float(parts[1]), float(parts[2])))
    return np.asarray(freqs, dtype=float), np.asarray(values, dtype=complex)


def parse_trace_list(response: str) -> list[str]:
    """解析 ``VNA:TRACe:LIST?`` 应答 → 迹线名列表（``S11,S12,S21,S22``）。"""
    names = [n.strip() for n in str(response).strip().split(",") if n.strip()]
    if not names:
        raise ValueError("TRACe:LIST? 应答为空")
    return names


class TCPIPSocketTransport:
    """LibreVNA SCPI-over-TCP 单客户端 socket 传输（官方口径）。

    单客户端语义由对端（GUI SCPI server）保证：第二连接顶掉第一连接；
    本端只维护一条连接，close 时关闭。应答按行读（官方：每 query 应答
    以换行结尾）。
    """

    def __init__(self, host: str, port: int = LIBREVNA_DEFAULT_PORT,
                 timeout_s: float = 10.0):
        self.host = host
        self.port = int(port)
        self.timeout_s = float(timeout_s)
        self._sock: socket.socket | None = None
        self._rfile: Any = None

    def _ensure_open(self) -> None:
        if self._sock is None:
            sock = socket.create_connection(
                (self.host, self.port), timeout=self.timeout_s)
            self._sock = sock
            self._rfile = sock.makefile("r", encoding="ascii", newline="\n")

    def query(self, command: str) -> str:
        self._ensure_open()
        assert self._sock is not None and self._rfile is not None
        self._sock.sendall((command + "\n").encode("ascii"))
        line = self._rfile.readline()
        if not line:
            raise ConnectionError(f"LibreVNA SCPI 连接无应答: {command!r}")
        return line.rstrip("\r\n")

    def write(self, command: str) -> None:
        self._ensure_open()
        assert self._sock is not None
        self._sock.sendall((command + "\n").encode("ascii"))

    def close(self) -> None:
        if self._rfile is not None:
            with contextlib.suppress(Exception):
                self._rfile.close()
            self._rfile = None
        if self._sock is not None:
            with contextlib.suppress(Exception):
                self._sock.close()
            self._sock = None


class LibreVNADriver:
    """LibreVNA 命令映射驱动（命令集单源；鸭子类型同 MockVNAInstrument）。

    Args:
        transport: 实现 ``query(str)->str`` / ``write(str)->None`` 的对象。
            真机=``TCPIPSocketTransport``；测试=pyvisa-sim 资源（#139 钉）。
    """

    def __init__(self, transport: Any):
        self._transport = transport
        self.written: list[str] = []

    # ── 基础 SCPI 表面（VNAInterface 兼容）──────────────────────────────────
    def query(self, command: str) -> str:
        return str(self._transport.query(command))

    def write(self, command: str) -> None:
        self.written.append(command)
        self._transport.write(command)

    def close(self) -> None:
        close_fn = getattr(self._transport, "close", None)
        if callable(close_fn):
            close_fn()

    @property
    def idn(self) -> str:
        """*IDN? 应答（官方格式 LibreVNA,LibreVNA-GUI,<serial>,<version>）。"""
        return self.query(CMD_IDN).strip()

    # ── 扫频设置与触发（§VNA:FREQuency / §VNA:ACQuisition）──────────────────
    def setup_sweep(self, start_hz: float, stop_hz: float, points: int,
                    ifbw_hz: float) -> None:
        """设置频率跨度/点数/IF 带宽（写序列留痕于 ``written``）。"""
        self.write(f"{CMD_FREQ_START} {float(start_hz):.6f}")
        self.write(f"{CMD_FREQ_STOP} {float(stop_hz):.6f}")
        self.write(f"{CMD_ACQ_POINTS} {int(points)}")
        self.write(f"{CMD_ACQ_IFBW} {float(ifbw_hz):.6f}")

    def trigger_single_sweep(self, timeout_s: float = 30.0) -> bool:
        """单次扫频模式 + 启动 + FINished? 轮询（§VNA:ACQuisition:FINished）。

        超时返回 False（调用方如实记 suspect，不静默装成功）。
        """
        self.write(f"{CMD_ACQ_SINGLE} TRUE")
        self.write(CMD_ACQ_RUN)
        deadline = time.monotonic() + float(timeout_s)
        while time.monotonic() < deadline:
            resp = self.query(CMD_ACQ_FINISHED_Q).strip().upper()
            if resp in ("TRUE", "1", "ON"):
                return True
            time.sleep(0.05)
        return False

    # ── 校准态（§VNA:CALibration:ACTIVE）───────────────────────────────────
    def active_calibration(self) -> str:
        """当前激活校准类型（空串=未校准；防御性再收 NONE/FALSE/OFF）。"""
        return self.query(CMD_CAL_ACTIVE_Q).strip()

    def is_calibrated(self) -> bool:
        return self.active_calibration().upper() not in _UNCALIBRATED_ACTIVE

    # ── 采集（§VNA:TRACe:LIST / §VNA:TRACe:DATA）───────────────────────────
    def capture_traces(self, traces: list[str] | None = None
                       ) -> dict[str, tuple[np.ndarray, np.ndarray]]:
        """逐迹线 ``TRACe:DATA?`` 采集 → {迹线名: (freq_hz, complex 数组)}。"""
        names = traces or parse_trace_list(self.query(CMD_TRACE_LIST_Q))
        out: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        for name in names:
            out[name.strip().upper()] = parse_trace_data(
                self.query(f"{CMD_TRACE_DATA_Q} {name.strip()}"))
        return out

    def get_snp_network(self, ports: list[int] | None = None) -> skrf.Network:
        """全迹线 → N 端口 skrf.Network（VNAInterface.capture 驱动主路契约）。

        端口数由迹线名 S<i>j 的最大下标推断（官方 TRACe:LIST 形如
        S11,S12,S21,S22）；任一 (i,j) 缺迹线时该元素置 0 并在
        ``missing_traces`` 留痕（部分矩阵诚实承载，掩码由 adapter 侧补）。
        """
        self.missing_traces: list[str] = []  # 采集面留痕（adapter 消费）
        traces = self.capture_traces()
        if not traces:
            raise ValueError("LibreVNA 无迹线可采集（TRACe:LIST? 为空）")
        n = 0
        # 迹线名 S<i>j → 端口数 = max(i, j)（S11→1 端口、S21→2 端口…）
        for name in traces:
            m = re.fullmatch(r"S(\d+)(\d+)", name)
            if m:
                n = max(n, int(m.group(1)), int(m.group(2)))
        if n <= 0:
            raise ValueError(f"迹线名非 S<i>j 形态: {sorted(traces)}")
        freqs = next(iter(traces.values()))[0]
        s = np.zeros((len(freqs), n, n), dtype=complex)
        measured = np.zeros((n, n), dtype=bool)
        for name, (f, values) in traces.items():
            m = re.fullmatch(r"S(\d+)(\d+)", name)
            if not m:
                continue
            i, j = int(m.group(1)) - 1, int(m.group(2)) - 1
            if not np.array_equal(f, freqs):
                raise ValueError(f"迹线 {name} 频轴与首迹线不一致（部分采集）")
            s[:, i, j] = values
            measured[i, j] = True
        for i in range(n):
            for j in range(n):
                if not measured[i, j]:
                    self.missing_traces.append(f"S{i + 1}{j + 1}")
        frequency = skrf.Frequency.from_f(freqs, unit="hz")
        return skrf.Network(frequency=frequency, s=s)


# ─── VNAInterface 协议接入（vna_capture.py 只读复用，不破坏既有面）────────────

_UNCAL_ACTIVE = _UNCALIBRATED_ACTIVE


class LibreVNAInterface(VNAInterface):
    """``VNAInterface`` 子类：把 LibreVNADriver 接进既有 capture/会话链。

    vna_capture.VNAInterface 的 connect() 只认 mock/skrf.vi/raw-pyvisa 三路，
    没有 LibreVNA 路径——本子类覆盖 connect/calibrate/probe_capabilities/
    close 四点，其余（capture 走驱动 get_snp_network 主路、raw_scpi 逃生口、
    JSONL 会话录制、save_session）全部继承，不改动基类文件。
    """

    def __init__(self, config: Any = None, driver: LibreVNADriver | None = None):
        super().__init__(config if isinstance(config, VNAConfig) else None)
        self._driver = driver
        self._active_calibration = ""

    def connect(self) -> bool:
        if self._driver is None:
            self._log("connect_failed", "LibreVNA driver 未注入")
            return False
        try:
            idn = self._driver.idn
        except Exception as e:
            self._log("connect_failed", f"{type(e).__name__}: {e}")
            return False
        self._instrument = self._driver
        self._skrf_driver = True   # capture() 走 get_snp_network 驱动主路
        self._mock_driver = False
        self._log("connect", idn)
        self._connected = True
        return True

    def calibrate(self) -> dict[str, Any]:
        """校准态核验（官方 §VNA:CALibration:ACTIVE 口径，非 SENS:CORR:STATE）。"""
        if not self._connected or self._driver is None:
            return {"ok": False, "calibrated": False, "detail": "not connected"}
        try:
            active = self._driver.active_calibration()
            calibrated = active.upper() not in _UNCAL_ACTIVE
            result = {"ok": True, "calibrated": calibrated,
                      "detail": f"CAL:ACTIVE={active or '<empty>'}"}
        except Exception as e:
            result = {"ok": False, "calibrated": False,
                      "detail": f"query failed: {e}"}
        self._active_calibration = active if result["ok"] else ""
        self._log("calibrate", result["detail"], calibrated=calibrated)
        return result

    def probe_capabilities(self) -> dict[str, Any]:
        caps = super().probe_capabilities()
        caps["driver"] = "librevna"
        caps["active_calibration"] = self._active_calibration or None
        return caps

    def close(self) -> None:
        if self._instrument is not None:
            with contextlib.suppress(Exception):
                self._instrument.close()
        self._connected = False
        self._log("close", "session ended")
