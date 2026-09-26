"""DP-11 P1：VNA 测量通道适配器（EMSolverAdapter 子类，注册表挂载）。

定位（规格书 DP-11 §1）：数字孪生最短路径的"实测入环"口——**测量=一台
"真机求解器"**，VnaAdapter 以 EMSolverAdapter 子类进注册表，战役/数据集/
健康门零改动复用同一 service JSON 面；fake（仿真侧）与 VNA（仪器侧）同接
口即"仿真-实测相关性"的架构落点。

诚实边界（规格书 §2/CAPABILITIES 纪律）：
- 测量=非仿真：不建几何（build_geometry=N-A 登记）、无网格/预算语义
  （EMSolverConfig 的 mesh_resolution_mm 等字段本通道不消费）；
- 能力声明如实（测量通道 supports_touchstone_export=True 有实现支撑，
  其余仿真侧能力位全 False，material_models=()——测量不建模材料）；
- 校准状态强制留痕（G4 决议）：SENS:CORR:STATE?（PNA/ZNB 族）/
  VNA:CALibration:ACTIVE?（LibreVNA）查得的校准态进 measurement_meta，
  查询失败/未校准记 suspect 不阻塞（结果仍如实产出）。

驱动优先级（单源实现于 measurement/librevna.py，未知型号显式报错）：
  ① LibreVNA 自建命令映射（SCPI-over-TCP 单客户端 socket，官方
     ProgrammingGuide 语义；pyvisa-sim 离线 CI 走注入/`<yaml>@sim` 传输）；
  ② PNA/FieldFox/ZNB/ZVA/NanoVNAv2 走 skrf.vi（vna_capture.DRIVERS）；
  ③ raw SCPI 逃生口（vna_capture._raw_measure，SENS:FREQ:DATA? +
     CALC:DATA:SDAT?）。

夹具去嵌（DP-11 §2）：twoxthru 配置给出 2x-thru 实测件（Touchstone）时，
经 measurement.afr_2xthru（IEEEP370 NZC；对称性/|S21| 平滑预检不过 →
solve 如实 ok=False）剥离 FIX**DUT**FIX。
"""

from __future__ import annotations

import contextlib
import logging
import time
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
import skrf

from rfauto.adapters.em_solver_base import (
    EMSolverAdapter,
    EMSolverConfig,
    EMSolverResult,
    EMSolverType,
    SolverCapabilities,
)

logger = logging.getLogger(__name__)

#: 全局注册表类型键（em_solver_base.EMSolverType.VNA 的值）
SOLVER_TYPE = "vna"


def _vna_settings(config: EMSolverConfig) -> dict[str, Any]:
    """EMSolverConfig.extra_params 中的 VNA 设置（缺省安全值收敛，#140）。"""
    extra = getattr(config, "extra_params", None) or {}
    if not isinstance(extra, dict):
        raise TypeError(f"extra_params 须为 dict，实际 {type(extra).__name__}")
    return extra


class VnaAdapter(EMSolverAdapter):
    """VNA 测量通道（connect → 触发扫频 → capture → 校准核验 → 2x-thru AFR）。

    配置入口 = ``EMSolverConfig``：
    - ``freq_range_ghz``：扫频带（Hz 换算后下发仪器）；
    - ``extra_params``（VNA 专用）：
      - ``address``: 仪器地址——LibreVNA 裸 socket 用 ``host:port``；
        VISA 地址（``TCPIP0::...::INSTR``）走 pyvisa（``visa_library`` 可指
        ``@sim``/<yaml>@sim 供离线 CI，#139：测试零真实网络）；
      - ``model``: librevna|pna|fieldfox|znb|zva|nanovna2|mock|""（空=纯
        raw SCPI）；未知型号显式 ValueError；
      - ``visa_library``: pyvisa ResourceManager 参数（缺省系统默认）；
      - ``n_points``/``ifbw_hz``: 扫频点数与 IF 带宽；
      - ``calkit_id``/``temperature_c``: 测量 meta 留痕；
      - ``twoxthru_path``: 2x-thru 实测件 Touchstone（给定时做 AFR 去嵌）；
      - ``sweep_timeout_s``: 单次扫频轮询上限（超时记 suspect）。
    """

    #: A5 能力声明（就近声明，同 ComsolAdapter/PalaceSolver 惯例；判据
    #: criteria.md G4：测量=非仿真，仿真侧能力位如实全 False）。
    CAPABILITIES: ClassVar[SolverCapabilities | None] = SolverCapabilities(
        solver_type=SOLVER_TYPE,
        supports_wave_port=False,
        supports_lumped_port=False,
        supports_field_export=False,
        supports_convergence_report=False,
        supports_touchstone_export=True,   # export_touchstone 有实现
        supports_headless_solve=True,      # 测量链无头可跑（pyvisa-sim CI 同链）
        supports_optimetrics=False,
        dimension="3d",                    # DUT 为三维实体（测量无求解维度语义）
        material_models=(),                # 测量不建模材料（诚实留空，Elmer 同款）
        parallel_backends=(),
        supports_sar=False,
        supports_nf2ff=False,
        supports_lumped_elements=False,
        supported_templates=(),            # 被测件在台架上，无模板机制
        requires_license=False,
        availability_gate="address",
    )

    def __init__(self, config: EMSolverConfig):
        super().__init__(config)
        self._interface = None            # VNAInterface（含 LibreVNAInterface）
        self._network: skrf.Network | None = None
        self._last_meta: dict[str, Any] | None = None
        self._driver_kind = ""

    # ── 配置解析 ────────────────────────────────────────────────────────────
    @property
    def settings(self) -> dict[str, Any]:
        return _vna_settings(self._config)

    # ── EMSolverAdapter 契约 ────────────────────────────────────────────────
    def connect(self) -> bool:
        """建立仪器连接（驱动优先级见模块 docstring；失败 False 不抛）。"""
        settings = self.settings
        model = settings.get("model", "")
        address = str(settings.get("address", "") or "")
        try:
            if str(model).lower() == "librevna":
                self._interface = self._build_librevna_interface(settings, address)
            else:
                from rfauto.measurement.librevna import check_known_model
                from rfauto.measurement.vna_capture import VNAConfig, VNAInterface

                check_known_model(str(model))
                self._interface = VNAInterface(VNAConfig(
                    address=address, model=str(model),
                    channel=int(settings.get("channel", 1)),
                    n_points=int(settings.get("n_points", 201)),
                    freq_range_ghz=tuple(self._config.freq_range_ghz),
                    if_bandwidth_hz=float(settings.get("ifbw_hz", 1000.0)),
                    mock_source=str(settings.get("mock_source", "")),
                    mock_calibrated=bool(settings.get("mock_calibrated", True)),
                ))
            ok = bool(self._interface.connect())
            self._connected = ok
            self._driver_kind = self._interface_probe_driver()
            return ok
        except Exception as e:
            logger.warning("VNA connect 失败: %s", e)
            self._connected = False
            return False

    def _build_librevna_interface(self, settings: dict[str, Any], address: str):
        """LibreVNA 传输装配：注入 transport > host:port 裸 socket > pyvisa。"""
        from rfauto.measurement.librevna import (
            LIBREVNA_DEFAULT_PORT,
            LibreVNADriver,
            LibreVNAInterface,
            TCPIPSocketTransport,
        )
        from rfauto.measurement.vna_capture import VNAConfig

        transport = settings.get("transport")
        if transport is None:
            if address and "::" not in address and ":" in address:
                host, _, port = address.rpartition(":")
                transport = TCPIPSocketTransport(
                    host, int(port or LIBREVNA_DEFAULT_PORT),
                    timeout_s=float(settings.get("timeout_s", 10.0)))
            else:
                import pyvisa

                rm = pyvisa.ResourceManager(str(settings.get("visa_library", "")))
                transport = rm.open_resource(
                    address, read_termination="\n", write_termination="\n")
        driver = LibreVNADriver(transport)
        return LibreVNAInterface(
            VNAConfig(address=address, model="librevna",
                      freq_range_ghz=tuple(self._config.freq_range_ghz)),
            driver=driver)

    def _interface_probe_driver(self) -> str:
        try:
            caps = self._interface.probe_capabilities()
            return str(caps.get("driver", "unknown"))
        except Exception:
            return "unknown"

    def is_available(self) -> bool:
        """可用性：address 已配置且能完成 connect/close 探测往返。

        无地址（CI 缺省）→ False（不虚报）；探测失败不抛。
        """
        settings = self.settings
        if not str(settings.get("address", "") or "") \
                and settings.get("transport") is None:
            return False
        was_connected = self._connected
        if was_connected:
            return True
        try:
            return bool(self.connect())
        finally:
            if not was_connected:
                self.close()

    def build_geometry(self, geometry: dict[str, Any]) -> bool:
        """测量通道 N-A：不建几何，登记 DUT 描述即成功（规格书 §2 诚实边界）。"""
        self._dut_description = dict(geometry or {})
        return True

    def solve(self) -> EMSolverResult:
        """触发扫频 → capture → 校准态核验 → 2x-thru AFR → EMSolverResult。

        失败路径如实 success=False（未连接/无网络/预检不过），不静默装成功。
        """
        t0 = time.time()
        if not self._connected and not self.connect():
            return EMSolverResult(
                success=False, message="VNA 未连接（connect 失败或未配置 address）")
        settings = self.settings
        suspects: list[str] = []
        meta: dict[str, Any] = {
            "calkit_id": settings.get("calkit_id", ""),
            "temperature_c": settings.get("temperature_c"),
            "driver": self._driver_kind,
            "suspect": suspects,
        }

        # ① 触发扫频（LibreVNA=官方单次扫频序列；其他驱动靠 capture 自身触发）
        driver = getattr(self._interface, "_driver", None)
        if driver is not None and hasattr(driver, "setup_sweep"):
            f0, f1 = (float(self._config.freq_range_ghz[0]) * 1e9,
                      float(self._config.freq_range_ghz[1]) * 1e9)
            driver.setup_sweep(f0, f1, int(settings.get("n_points", 201)),
                               float(settings.get("ifbw_hz", 1000.0)))
            if not driver.trigger_single_sweep(
                    float(settings.get("sweep_timeout_s", 30.0))):
                suspects.append("single sweep FINished? 轮询超时")

        # ② 校准态核验（G4 决议：强制留痕；缺失记 suspect 不阻塞）
        try:
            cal = self._interface.calibrate()
        except Exception as e:
            cal = {"ok": False, "calibrated": False, "detail": str(e)}
        meta["calibrated"] = bool(cal.get("calibrated"))
        meta["calibration_detail"] = str(cal.get("detail", ""))
        if not cal.get("ok"):
            suspects.append("校准态查询失败（SENS:CORR:STATE?/CAL:ACTIVE?）")
        elif not cal.get("calibrated"):
            suspects.append("仪器无激活校准（测量值为未校准原始数据）")

        # ③ capture
        try:
            net = self._interface.capture()
        except Exception as e:
            net = None
            suspects.append(f"capture 异常: {e}")
        if net is None or len(net.f) == 0:
            return EMSolverResult(
                success=False, wall_time_s=time.time() - t0,
                message="VNA capture 未产出网络",
                measurement_meta={**meta, "timestamp": _utc_now()})

        # ④ 2x-thru AFR（配置给定时；预检不过 → ok=False 如实）
        mask = self._full_mask(net)
        t2x_path = settings.get("twoxthru_path", "")
        afr_note: dict[str, Any] = {"applied": False}
        if t2x_path:
            from rfauto.measurement.afr_2xthru import deembed_2xthru

            afr = deembed_2xthru(net, skrf.Network(str(Path(t2x_path))))
            afr_note.update({"applied": bool(afr.get("ok")),
                             "precheck": afr.get("precheck")})
            if not afr.get("ok"):
                suspects.append(str(afr.get("error", "2x-thru 去嵌失败")))
                return EMSolverResult(
                    success=False, wall_time_s=time.time() - t0,
                    message=str(afr.get("error", "2x-thru 预检不过")),
                    measurement_meta={**meta, "timestamp": _utc_now(),
                                      "afr": afr_note})
            net = afr["network"]
            mask = np.ones((net.nports, net.nports), dtype=bool)
        meta["afr"] = afr_note
        if getattr(driver, "missing_traces", None):
            for name in driver.missing_traces:
                i, j = int(name[1]) - 1, int(name[2]) - 1
                mask[i, j] = False
            suspects.append(f"部分迹线缺失（零填充）: {driver.missing_traces}")

        # ⑤ 结果（get_sparams 与 fake/EMSolver 面同契约：solve 后取网络）
        self._network = net
        meta["idn"] = self._safe_idn()
        meta["timestamp"] = _utc_now()
        self._last_meta = meta
        return EMSolverResult(
            success=True,
            freq_ghz=np.asarray(net.f, dtype=float) / 1e9,
            s_params=np.asarray(net.s, dtype=complex),
            measured_mask=mask,
            measurement_meta=meta,
            wall_time_s=time.time() - t0,
            message=(f"VNA 测量完成（{net.nports} 端口 × {len(net.f)} 点，"
                     f"校准={'on' if meta['calibrated'] else 'OFF'}）"),
        )

    @staticmethod
    def _full_mask(net: skrf.Network) -> np.ndarray:
        return np.ones((net.nports, net.nports), dtype=bool)

    def _safe_idn(self) -> str:
        try:
            return str(self._interface.probe_capabilities().get("idn", ""))
        except Exception:
            return ""

    def get_sparams(self) -> tuple[np.ndarray, np.ndarray]:
        """S 参数（EMSolver 面契约：(freq_ghz, s_params)；未求解则先 solve）。"""
        if self._network is None:
            result = self.solve()
            if not result.success:
                raise RuntimeError(result.message)
        return (np.asarray(self._network.f, dtype=float) / 1e9,
                np.asarray(self._network.s, dtype=complex))

    def export_touchstone(self, path: str | Path, contract: Any = None) -> Path:
        """导出测量网络 Touchstone（results/params.sNp 同构产物用）。"""
        if self._network is None:
            raise RuntimeError("尚未测量，请先调用 solve()")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._network.write_touchstone(str(path))
        return path

    def close(self) -> None:
        if self._interface is not None:
            try:
                self._interface.close()
            except Exception:  # pragma: no cover - 关闭容错（#105）
                logger.debug("VNA close 异常（忽略）", exc_info=True)
        self._interface = None
        self._connected = False

    # ── 测量 meta 面（health 门/数据集分支⑥ 消费）────────────────────────────
    @property
    def last_measurement_meta(self) -> dict[str, Any] | None:
        return self._last_meta

    def get_status(self) -> dict[str, Any]:
        status = super().get_status()
        status["config"] = {
            **status.get("config", {}),
            # 测量通道语义：mesh/budget 字段 N-A（如实标注，规格书 §2）
            "mesh_resolution_mm": "N-A (measurement)",
            "address": str(self.settings.get("address", "")),
            "model": str(self.settings.get("model", "")),
        }
        return status


def register_vna(registry: Any = None) -> None:
    """注册到全局 EMSolverRegistry（导入即注册模式，同 openems/comsol）。"""
    from rfauto.adapters.em_solver_base import EMSolverRegistry, get_global_registry

    target = registry if isinstance(registry, EMSolverRegistry) \
        else get_global_registry()
    target.register(EMSolverType.VNA, VnaAdapter)


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


with contextlib.suppress(Exception):
    register_vna()
