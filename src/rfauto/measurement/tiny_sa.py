"""MS-7 tinySA 频谱仪通道（**硬件门=mock 先行**，真机通道禁触发）。

规格（round15 MS-8 / ge8b 席6 任务书 MS-7）：串口命令映射仿
measurement/librevna.py 单源模式——命令常量、语义注释、应答解析全部
集中本模块；driver 只消费本模块表面。

**硬件门裁决**：设备未购、命令集原文未在装
环境逐条核verify——本批只交付：
- mock 数据面（确定性合成频谱：噪声地板+可配 tone 表，固定 seed 逐位
  可复现）；
- 命令映射与应答解析（ASCII/binary 双路，mock 上往返自洽测试钉）；
- 真机 serial 传输层骨架 + **双重硬件门**（构造参数 ``allow_real=True``
  **且** 环境变量 ``RFAUTO_TINYSA_ALLOW_REAL=1`` 同时满足才允许打开串口，
  缺一抛 :class:`HardwareGateLocked`）——门未裁前真机通道不可触发。

协议口径（诚实边界）：命令名/应答格式按 tinySA 官方 wiki "Remote
Operation / Protocol" 页公开描述登记（``scan f1 f2 points`` 二进制回读
= 12 字节头 f1/f2(u32 LE, Hz)+points(u16 LE) + points×int16 LE dBm；
``frequencies`` ASCII Hz 列表；``pause``/``resume`` 冻结/恢复扫描供
``sdata`` 稳定回读）。**主源逐字核对未做**（wiki 今日不可达，见汇报），
登记值以「待真机核verify」标注——门开前不作为真机依据，门开时逐条
对照固件实测后回填。mock 通道与解析器往返自洽不受此影响。

消费面约定：与本仓 VNA 链（vna_capture.MockVNAInstrument）同款鸭子类型
``query``/``write``/``close`` 表面，但 tinySA 是频谱仪（功率迹线，无
S 参数），不接入 VNAInterface——独立 TinySASpectrum 数据面。
"""

from __future__ import annotations

import contextlib
import os
import struct
from dataclasses import dataclass, field
from typing import Any

import numpy as np

#: 命令常量（单源；语义=tinySA wiki Remote Operation 页口径，待真机核verify）
CMD_VERSION = "version"        # 固件版本字符串
CMD_VBAT = "vbat"              # 电池电压（mV，ASCII）
CMD_PAUSE = "pause"            # 冻结扫描（sdata 稳定回读前提）
CMD_RESUME = "resume"          # 恢复扫描
CMD_SCAN = "scan"              # "scan f1 f2 points" → 二进制谱（见下）
CMD_SCANRAW = "scanraw"        # 同 scan 的原始变体（同应答格式）
CMD_SDATA_BIN = "sdata"        # 最后一次扫描的二进制回读
CMD_FREQS = "frequencies"      # "frequencies f1 f2 n" → ASCII Hz 列表

#: 二进制 scan 应答头（f1 u32 LE Hz、f2 u32 LE Hz、points u16 LE）＝12 字节
_SCAN_HEADER_FMT = "<IIH"
_SCAN_HEADER_SIZE = struct.calcsize(_SCAN_HEADER_FMT)

#: 硬件门环境变量名（真机通道第二重门）
ENV_ALLOW_REAL = "RFAUTO_TINYSA_ALLOW_REAL"

#: mock 缺省参数（确定性）
MOCK_IDN = "tinySA,mock,SN0000,FW1.0"
MOCK_NOISE_FLOOR_DBM = -95.0
MOCK_RBW_HZ = 100.0e3


class HardwareGateLocked(RuntimeError):
    """真机硬件门未开（allow_real + 环境变量双条件不满足）。"""


def parse_frequencies(response: str) -> np.ndarray:
    """``frequencies`` ASCII 应答 → Hz 数组（空白分隔浮点，容忍多余空白）。"""
    parts = str(response).split()
    if not parts:
        raise ValueError("frequencies 应答为空")
    return np.asarray([float(p) for p in parts], dtype=float)


def parse_scan_binary(blob: bytes, *,
                      expect_points: int | None = None,
                      expect_start_hz: float | None = None,
                      expect_stop_hz: float | None = None
                      ) -> tuple[np.ndarray, np.ndarray]:
    """解析 ``scan``/``sdata`` 二进制应答 → (freqs_hz, levels_dbm)。

    格式（登记口径，见模块 docstring 诚实边界）：12 字节头
    ``<f1 u32 LE><f2 u32 LE><points u16 LE>`` + points×int16 LE dBm。
    expect_* 校验头一致性（防串台/截断），不符显式 ValueError。
    """
    data = bytes(blob)
    if len(data) < _SCAN_HEADER_SIZE:
        raise ValueError(
            f"scan 应答短于 12 字节头（{len(data)} B，非 tinySA 二进制格式？）")
    f1, f2, npts = struct.unpack_from(_SCAN_HEADER_FMT, data)
    if expect_points is not None and int(npts) != int(expect_points):
        raise ValueError(
            f"scan 头点数 {npts} ≠ 期望 {expect_points}（串台/截断）")
    if expect_start_hz is not None and abs(f1 - float(expect_start_hz)) > 1.0:
        raise ValueError(
            f"scan 头 f1={f1} Hz ≠ 期望 {expect_start_hz} Hz")
    if expect_stop_hz is not None and abs(f2 - float(expect_stop_hz)) > 1.0:
        raise ValueError(
            f"scan 头 f2={f2} Hz ≠ 期望 {expect_stop_hz} Hz")
    payload = data[_SCAN_HEADER_SIZE:]
    if len(payload) < 2 * int(npts):
        raise ValueError(
            f"scan 载荷不足：期望 {2 * int(npts)} B，实际 {len(payload)} B")
    levels = np.frombuffer(payload[:2 * int(npts)], dtype="<i2",
                           count=int(npts)).astype(float)
    freqs = np.linspace(float(f1), float(f2), int(npts))
    return freqs, levels


def build_scan_binary(f1_hz: float, f2_hz: float,
                      levels_dbm: np.ndarray) -> bytes:
    """构造 scan 应答字节串（mock 供数 + 解析器往返测试同一格式单源）。"""
    levels = np.asarray(levels_dbm, dtype=float)
    head = struct.pack(_SCAN_HEADER_FMT, round(f1_hz),
                       round(f2_hz), levels.size)
    body = np.round(levels).astype("<i2").tobytes()
    return head + body


@dataclass
class TinySASpectrum:
    """一次扫描的频谱数据面（频率 Hz / 电平 dBm，元数据随行）。"""

    freqs_hz: np.ndarray
    levels_dbm: np.ndarray
    start_hz: float
    stop_hz: float
    points: int
    rbw_hz: float | None = None
    idn: str = ""
    notes: list[str] = field(default_factory=list)

    def peak(self) -> tuple[float, float]:
        """峰值 (freq_hz, level_dbm)（确定性 argmax）。"""
        i = int(np.argmax(self.levels_dbm))
        return float(self.freqs_hz[i]), float(self.levels_dbm[i])


class MockTinySATransport:
    """确定性 mock 传输（鸭子类型同真机 serial 表面）。

    合成谱 = 常值噪声地板（高斯起伏，固定 seed）+ 可配 tone 表
    ``{freq_hz: dbm}``（	rbw 内能量归到最近频点，供峰值/找信号测试）。
    query/write 记账同 MockVNAInstrument 惯例。
    """

    def __init__(self, *, seed: int = 20261003,
                 noise_floor_dbm: float = MOCK_NOISE_FLOOR_DBM,
                 rbw_hz: float = MOCK_RBW_HZ,
                 tones: dict[float, float] | None = None,
                 idn: str = MOCK_IDN,
                 vbat_mv: int = 3900):
        self.seed = int(seed)
        self.noise_floor_dbm = float(noise_floor_dbm)
        self.rbw_hz = float(rbw_hz)
        self.tones = {float(f): float(v) for f, v in (tones or {}).items()}
        self.idn = str(idn)
        self.vbat_mv = int(vbat_mv)
        self.written: list[str] = []
        self._paused = False
        self._sweep: tuple[float, float, int] | None = None

    # ── 传输表面（与真机 SerialTransport 同形）─────────────────────────────
    def write(self, command: str) -> None:
        cmd = str(command).strip()
        self.written.append(cmd)
        if cmd == CMD_PAUSE:
            self._paused = True
        elif cmd == CMD_RESUME:
            self._paused = False

    def query(self, command: str) -> str:
        cmd = str(command).strip()
        self.written.append(cmd)
        if cmd == CMD_VERSION:
            return self.idn
        if cmd == CMD_VBAT:
            return str(self.vbat_mv)
        if cmd.startswith(CMD_FREQS):
            parts = cmd.split()
            if len(parts) != 4:
                raise ValueError(f"{CMD_FREQS} 语法：frequencies f1 f2 n")
            f1, f2, n = float(parts[1]), float(parts[2]), int(parts[3])
            return " ".join(
                f"{v:.6f}" for v in np.linspace(f1, f2, n))
        raise ValueError(f"mock 未实现的 ASCII 命令: {cmd!r}")

    def query_binary(self, command: str,
                     n_bytes: int | None = None) -> bytes:
        """scan/sdata 二进制回读（确定性合成谱）。"""
        cmd = str(command).strip()
        self.written.append(cmd)
        parts = cmd.split()
        if cmd == CMD_SDATA_BIN:
            if self._sweep is None:
                raise ValueError("sdata 前无 scan（mock 无历史扫描）")
            f1, f2, n = self._sweep
        elif parts[:1] in ([CMD_SCAN], [CMD_SCANRAW]):
            if len(parts) != 4:
                raise ValueError(f"{parts[0]} 语法：{parts[0]} f1 f2 points")
            f1, f2, n = float(parts[1]), float(parts[2]), int(parts[3])
            self._sweep = (f1, f2, n)
        else:
            raise ValueError(f"mock 未实现的二进制命令: {cmd!r}")
        if n <= 1:
            raise ValueError(f"points 须 ≥2，实际 {n}")
        freqs = np.linspace(f1, f2, n)
        rng = np.random.default_rng(
            self.seed + round(f1) + round(f2) + n)
        levels = (self.noise_floor_dbm
                  + rng.normal(0.0, 1.0, size=n))
        for tf, tv in self.tones.items():
            idx = int(np.argmin(np.abs(freqs - tf)))
            if abs(freqs[idx] - tf) <= max(self.rbw_hz,
                                           (f2 - f1) / max(n - 1, 1)):
                levels[idx] = np.maximum(levels[idx], tv)
        return build_scan_binary(f1, f2, levels)

    def close(self) -> None:
        self._paused = False


class SerialTransport:
    """真机 serial 传输骨架（**双重硬件门**，门未裁不可用）。

    打开条件：构造参数 ``allow_real=True`` **且** 环境变量
    ``RFAUTO_TINYSA_ALLOW_REAL=1``，缺一即抛 :class:`HardwareGateLocked`
    （连串口枚举都不做——门未裁前真机通道零触发）。pyserial 惰性导入。
    """

    def __init__(self, port: str, baudrate: int = 115200,
                 timeout_s: float = 5.0, *,
                 allow_real: bool = False):
        self.port = str(port)
        self.baudrate = int(baudrate)
        self.timeout_s = float(timeout_s)
        gate_ok = bool(allow_real) and \
            os.environ.get(ENV_ALLOW_REAL, "") == "1"
        if not gate_ok:
            raise HardwareGateLocked(
                f"tinySA 真机通道被硬件门锁定（allow_real={allow_real}, "
                f"env {ENV_ALLOW_REAL}={os.environ.get(ENV_ALLOW_REAL)!r}）—"
                "门未裁决，真机通道禁触发")
        self._serial: Any = None

    def _ensure_open(self) -> None:
        if self._serial is None:
            import serial  # 惰性：门开后才需要 pyserial

            self._serial = serial.Serial(
                self.port, self.baudrate, timeout=self.timeout_s)

    def write(self, command: str) -> None:
        self._ensure_open()
        assert self._serial is not None
        self._serial.write((str(command) + "\n").encode("ascii"))

    def query(self, command: str) -> str:
        self.write(command)
        assert self._serial is not None
        line = self._serial.readline().decode("ascii", errors="replace")
        if not line:
            raise ConnectionError(f"tinySA 无应答: {command!r}")
        return line.rstrip("\r\n")

    def query_binary(self, command: str,
                     n_bytes: int | None = None) -> bytes:
        self.write(command)
        assert self._serial is not None
        want = _SCAN_HEADER_SIZE + 2 * int(n_bytes) if n_bytes else None
        data = self._serial.read(want) if want else self._serial.read(4096)
        if not data:
            raise ConnectionError(f"tinySA 二进制无应答: {command!r}")
        return bytes(data)

    def close(self) -> None:
        if self._serial is not None:
            with contextlib.suppress(Exception):
                self._serial.close()
            self._serial = None


class TinySADriver:
    """tinySA 命令映射驱动（命令集单源；鸭子类型同 mock/真机传输）。"""

    def __init__(self, transport: Any):
        self._transport = transport
        self.written: list[str] = []

    def _write(self, command: str) -> None:
        self.written.append(command)
        self._transport.write(command)

    def close(self) -> None:
        close_fn = getattr(self._transport, "close", None)
        if callable(close_fn):
            close_fn()

    def idn(self) -> str:
        return str(self._transport.query(CMD_VERSION)).strip()

    def vbat_mv(self) -> int:
        return int(float(self._transport.query(CMD_VBAT)))

    def setup_sweep(self, start_hz: float, stop_hz: float, points: int) -> None:
        """设置扫描参数（tinySA 无独立设置命令——记录在驱动侧随 scan 下发）。"""
        if points <= 1:
            raise ValueError(f"points 须 ≥2，实际 {points}")
        if not 0.0 < float(start_hz) < float(stop_hz):
            raise ValueError(
                f"频率窗非法：0 < start < stop 须成立，得到 "
                f"({start_hz}, {stop_hz})")
        self._sweep = (float(start_hz), float(stop_hz), int(points))

    def capture_spectrum(self, *, frozen: bool = True) -> TinySASpectrum:
        """采集一帧频谱（pause → scan → resume，官方口径的稳定回读序列）。

        frozen=True（缺省）执行 pause/resume 包夹；False 直采不冻结。
        """
        sweep = getattr(self, "_sweep", None)
        if sweep is None:
            raise ValueError("先 setup_sweep 再 capture_spectrum")
        f1, f2, n = sweep
        notes: list[str] = []
        if frozen:
            self._write(CMD_PAUSE)
        scan_cmd = f"{CMD_SCAN} {f1:.6f} {f2:.6f} {n}"
        self.written.append(scan_cmd)  # 二进制回读也留痕（命令序列可审计）
        blob = self._transport.query_binary(scan_cmd,
                                            n_bytes=_SCAN_HEADER_SIZE + 2 * n)
        if frozen:
            self._write(CMD_RESUME)
        notes.append("protocol=wiki-registered; pending on-device verify")
        freqs, levels = parse_scan_binary(
            blob, expect_points=n, expect_start_hz=f1, expect_stop_hz=f2)
        return TinySASpectrum(
            freqs_hz=freqs, levels_dbm=levels, start_hz=f1, stop_hz=f2,
            points=n, rbw_hz=getattr(self._transport, "rbw_hz", None),
            idn=self.idn(), notes=notes)
