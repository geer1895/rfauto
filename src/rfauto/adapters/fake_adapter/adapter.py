"""fake_adapter.adapter —— FakeAdapter 主类（SimulatorAdapter 解析近似实现）。

自 adapters/fake_adapter.py 单文件巨石按职责域拆分（aurora_h W4-S2，T2 范式/
AU-1 工艺）：solve() per-model 派发分支引用的各族 sparams 函数/族常量从兄弟
子模块显式导入（名入本模块 globals——patch 门面名经 AU-1 扇出同步落位，
monkeypatch 缝逐位保持）；类体逐字节搬迁，零逻辑改动。
"""

from __future__ import annotations

import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import skrf

from rfauto.core.errors import (
    ModelBuildError,
    SimulationFailedError,
)
from rfauto.core.interfaces import (
    AdapterCapabilities,
    SimulatorAdapter,
    SolveReport,
)

from .antenna_family import (
    _ANT2_TEMPLATES,
    _ARRAY_TEMPLATES,
    _EEP_TEMPLATES,
    _MMWAVE_SERIES_TEMPLATES,
    _antenna2_sparams,
    _array_sparams,
    _dipole_sparams,
    _eep_sparams,
    _mmwave_series_sparams,
    _patch_sparams_1port,
)
from .calibration import (
    load_fake_calibration,
)
from .capacitor_family import (
    _interdigital_cap_sparams,
    _mim_cap_sparams,
)
from .coupler_family import (
    _branchline_2sect_sparams,
    _branchline_sparams,
    _cline_coupler_sparams,
    _coupled_line_sparams,
    _lange_sparams,
    _stepped_impedance_sparams,
    _wilkinson_sparams_2port,
    _wilkinson_sparams_3port,
)
from .fault import (
    FaultInjection,
)
from .filter_family import (
    _C3_TEMPLATES,
    _HAIRPIN_F0_CORR,
    _HAIRPIN_QE_CORR,
    _c3_l_via_anchor_h,
    _c3_sparams,
    _coupled_bpf_sparams,
    _hairpin_sparams,
)
from .inductor_family import (
    _octagonal_spiral_sparams,
)
from .slotline_family import (
    _coil_nfc_sparams,
    _marchand_balun_sparams,
    _msl_slot_transition_sparams,
    _slotline_route_a_sparams,
    _slotline_route_b_sparams,
)
from .tl_family import (
    _atten_pi_sparams,
    _atten_t_sparams,
    _bend_sparams,
    _cps_sparams,
    _cpw_sparams,
    _gysel_sparams,
    _mline_sparams,
    _msl_cpw_sparams,
    _msl_siw_taper_sparams,
    _ratrace_sparams,
    _siw_sparams,
    _sma_launcher_sparams,
    _suspended_stripline_sparams,
    _tjunc_sparams,
    _via_sparams,
    _wstep_sparams,
)

# ─── FakeAdapter 实现 ─────────────────────────────────────────────────────────

class FakeAdapter(SimulatorAdapter):
    """解析近似仿真适配器。

    无需 HFSS 许可证，基于闭式公式返回合成 S 参数。
    支持故障注入以测试错误处理路径。

    Parameters
    ----------
    model_type : str
        "wilkinson" | "branchline"，决定使用的解析模型。
    n_ports : int
        端口数。wilkinson 模型：2（向后兼容）或 3（完整隔离度）。
        默认 2，P2 调优循环应显式设 3。
    fault : FaultInjection | None
        故障注入配置。
    freq_ghz : tuple[float, float, int]
        频率范围 (start, stop, num_points)。
    z0 : float
        参考阻抗，默认 50 Ω。
    f0_ghz : float
        中心频率（GHz），默认 2.4。
    """

    def __init__(
        self,
        model_type: str = "wilkinson",
        fault: FaultInjection | None = None,
        freq_ghz: tuple[float, float, int] = (1.0, 4.0, 201),
        z0: float = 50.0,
        n_ports: int = 2,
        f0_ghz: float = 2.4,
        seed: int = 42,
    ) -> None:
        self.model_type = model_type
        self.fault = fault or FaultInjection()
        self.freq_ghz = freq_ghz
        self.z0 = z0
        self.n_ports = n_ports
        self.f0_ghz = f0_ghz
        # 阻抗计算用层叠（v0 物理映射）；配方变量里的 substrate 字符串优先
        self._substrate_name = "rogers4350b_h0.508"
        # 种子化随机：同配置可复现（C4；原先用全局 np.random 不可复现）
        self._rng = np.random.default_rng(seed)
        self._connected = False
        self._variables: dict[str, str] = {}
        self._network: skrf.Network | None = None

    # ─── SimulatorAdapter 接口实现 ───────────────────────────────────────────

    def connect(self, settings: dict[str, Any]) -> None:
        """幂等连接——FakeAdapter 无需真实连接。"""
        if self.fault.fail_connect:
            from rfauto.core.errors import ConnectFailedError
            raise ConnectFailedError(
                "FakeAdapter 故障注入：connect() 失败",
                details={"fault": "fail_connect"},
            )
        self._connected = True

    def open_or_create_project(self, path: str | Path, design_name: str) -> None:
        """FakeAdapter 无项目概念，静默通过。"""
        if not self._connected:
            raise RuntimeError("未连接，请先调用 connect()")

    def set_variables(self, vars: dict[str, str]) -> None:
        """记录设计变量（FakeAdapter 用于后续解析计算）。"""
        if not self._connected:
            raise RuntimeError("未连接，请先调用 connect()")
        self._variables.update(vars)

    def build_and_setup(
        self,
        builder: Callable[[SimulatorAdapter], None],
        setup: Any,
    ) -> None:
        """执行构建器 + 故障注入。"""
        if not self._connected:
            raise RuntimeError("未连接，请先调用 connect()")

        if self.fault.fail_build:
            raise ModelBuildError(
                "FakeAdapter 故障注入：build_and_setup() 建模失败",
                details={"fault": "fail_build", "variables": self._variables},
            )

        # 调用 builder 回调（通常用于记录构建步骤）
        builder(self)

    def _parse_variable(self, name: str, default: float) -> float:
        """从变量中解析数值（带单位剥离）。"""
        for var_name in [name, name.replace("_mm", "")]:
            if var_name in self._variables:
                try:
                    val_str = self._variables[var_name].strip()
                    if val_str.endswith("mm"):
                        val_str = val_str[:-2]
                    elif val_str.endswith("m"):
                        val_str = val_str[:-1]
                    return float(val_str)
                except (ValueError, AttributeError):
                    continue
        return default

    def _parse_list_variable(self, name: str, default: list[float]) -> list[float]:
        """解析列表型变量（coupled_bpf 的 widths_mm/gaps_mm）：list/tuple 直接取，
        字符串按逗号切分（容忍方括号与 mm 后缀）；缺失/不可解析回退 default。"""
        raw = self._variables.get(name)
        if raw is None:
            return list(default)
        if isinstance(raw, (list, tuple)):
            try:
                return [float(v) for v in raw]
            except (TypeError, ValueError):
                return list(default)
        text = str(raw).strip().strip("[]()")
        out: list[float] = []
        for item in text.split(","):
            token = item.strip()
            if token.endswith("mm"):
                token = token[:-2]
            if not token:
                continue
            try:
                out.append(float(token))
            except ValueError:
                return list(default)
        return out if out else list(default)

    def _compute_f0_from_variables(self, eps_eff: float | None = None) -> float:
        """从变量中动态计算谐振频率（GHz，λ/4 反推）。

        按物理角色 resonator_length_mm 取谐振段长度（arm_len_mm /
        patch_len_mm 等候选，见 core/physics_roles.py）；无长度变量时
        使用 init 指定的 f0_ghz。

        eps_eff：联合校准锚（A1）——来自 configs/fake_calibration.yaml；
        未提供时由调用方以 synthesis.forward_z0 按线宽物理计算后传入，
        缺省 3.28（branchline 真机 HFSS 校准值）。
        """
        _C = 3.0e8  # 光速 m/s
        # branchline 真机校准（2026-08-31）：arm_len≈17.2mm@2.4GHz → εeff≈3.28。
        _EPS_EFF = eps_eff if eps_eff is not None else 3.28

        from rfauto.core.physics_roles import resolve_role

        arm_len_mm = resolve_role(
            "resonator_length_mm", self._variables,
            candidates=("arm_len_mm", "arm_len"),
        )
        if arm_len_mm is not None:
            arm_len_m = arm_len_mm * 1e-3
            f0_hz = _C / (4 * arm_len_m * math.sqrt(_EPS_EFF))
            return f0_hz / 1e9
        return self.f0_ghz

    def _wilkinson_s11_min(
        self, series_w_mm: float, shunt_w_mm: float, f0_ghz: float,
        stackup_name: str | None = None,
    ) -> tuple[float, float]:
        """由线宽物理计算 Wilkinson 的带内最小反射（线幅值）与 εeff。

        一阶失配模型：两段 λ/4 线（目标阻抗 Zt=Z0·√2 与 Z0）的实现阻抗
        由 synthesis.forward_z0（skrf MLine HJ）给出，反射系数按最坏
        叠加合成，再叠加结寄生底噪 0.12（T 型结/阶梯不连续性/端口效应，
        一阶公式未建模——真机校准锚：HFSS 名义点 -12.93dB / 最优
        -15.8dB 与本模型 -13.0/-15.8 对齐，2026-09-03 v0）。
        这是 fake 对调参变量（series_w/shunt_w）的排序响应来源
        （v0 修复：旧版公式里线宽根本没进公式）。
        """
        from rfauto.core.synthesis import Stackup, forward_z0

        stackup = Stackup.from_materials_yaml(
            stackup_name or self._substrate_name)
        zt = self.z0 * math.sqrt(2)
        z_series, eps_eff = forward_z0(series_w_mm, f0_ghz, stackup)
        z_shunt, _ = forward_z0(shunt_w_mm, f0_ghz, stackup)
        gamma_s = abs((z_series - zt) / (z_series + zt))
        gamma_sh = abs((z_shunt - self.z0) / (z_shunt + self.z0))
        s11_min = math.hypot(gamma_s + gamma_sh, 0.12)
        return min(s11_min, 0.68), eps_eff

    def solve(self, setup_name: str, timeout_s: int = 3600) -> SolveReport:
        """解析求解——基于闭式公式返回合成 S 参数。"""
        import time

        if not self._connected:
            raise RuntimeError("未连接，请先调用 connect()")

        if self.fault.fail_solve:
            raise SimulationFailedError(
                "FakeAdapter 故障注入：solve() 求解失败",
                details={"fault": "fail_solve", "setup": setup_name},
            )

        # 模拟延迟
        if self.fault.slow_solve_s > 0:
            time.sleep(self.fault.slow_solve_s)

        # 生成频率轴
        f_start, f_stop, f_pts = self.freq_ghz
        freq = skrf.Frequency(f_start, f_stop, f_pts, unit="GHz")

        # 根据模型类型计算 S 参数
        # 联合校准锚（A1）：configs/fake_calibration.yaml per-model 覆盖；
        # v0 起 wilkinson 的 s11 深度由线宽失配物理计算，常数锚只留
        # eps_eff / eps_eff_scale（s11_floor_db/s11_edge_scale 已废除
        # 2026-09-23 df4a）。
        cal = load_fake_calibration().get(self.model_type, {})
        if isinstance(self._variables.get("substrate"), str):
            self._substrate_name = self._variables["substrate"]

        if self.model_type == "wilkinson":
            from rfauto.core.physics_roles import resolve_role

            series_w = resolve_role(
                "impedance_line_width_mm", self._variables, default=0.33)
            shunt_w = resolve_role(
                "shunt_line_width_mm", self._variables, default=1.10)
            s11_min_lin, eps_eff_series = self._wilkinson_s11_min(
                series_w, shunt_w, self.f0_ghz, self._substrate_name)
            # 位置锚（2026-09-23 用户拍板，乘法缩放语义）：eps_eff_scale 对 HJ
            # 物理推导值乘 K=3.54/2.725 的频率尺度修正（openEMS 名义谷位
            # 2.2GHz λ/4 反推；HJ 参考点 series 臂 εeff≈2.725@2.4GHz）——
            # 谷位下移 ×√(2.725/3.54)=0.8774，对齐 openEMS 名义口径。
            # 缺省 1.0=无锚旧行为逐位不变；绝对键 eps_eff 若存在仍优先。
            eps_scale = float(cal.get("eps_eff_scale", 1.0))
            f0_ghz = self._compute_f0_from_variables(
                eps_eff=cal.get("eps_eff", eps_eff_series * eps_scale))
            if self.n_ports == 3:
                s_data = _wilkinson_sparams_3port(
                    freq.f / 1e9, z0=self.z0, f0_ghz=f0_ghz, rng=self._rng,
                    s11_min_lin=s11_min_lin,
                )
            else:
                s_data = _wilkinson_sparams_2port(
                    freq.f / 1e9, z0=self.z0, f0_ghz=f0_ghz, rng=self._rng,
                    s11_min_lin=s11_min_lin,
                )
        elif self.model_type == "branchline":
            # f0 同样由 arm_len 变量驱动（λ/4 关系），参数变化有真实响应
            # 真机校准：S11 深度依赖于 series_w/shunt_w
            f0_ghz = self._compute_f0_from_variables(eps_eff=cal.get("eps_eff"))
            series_w = self._parse_variable("series_w_mm", default=1.87)
            shunt_w = self._parse_variable("shunt_w_mm", default=1.11)
            s_data = _branchline_sparams(
                freq.f / 1e9, z0=self.z0, f0_ghz=f0_ghz,
                series_w_mm=series_w, shunt_w_mm=shunt_w,
            )
        elif self.model_type == "patch":
            # 贴片天线：patch_len → λ/2 谐振频率；feed_offset/patch_w →
            # 馈电匹配深度（谐振腔一阶模型，v0 修复：旧版 feed_offset
            # 签名里有、公式里没用）。
            from rfauto.core.physics_roles import resolve_role

            patch_len = resolve_role(
                "resonator_length_mm", self._variables,
                candidates=("patch_len_mm", "patch_len"), default=40.0)
            feed_offset = resolve_role(
                "feed_offset_mm", self._variables, default=10.0)
            patch_w = resolve_role(
                "patch_width_mm", self._variables, default=30.0)
            lambda0_mm = 300.0 / self.f0_ghz
            # 一阶谐振腔模型：R_edge ≈ 60λ0/W，R_in = R_edge·sin²(π·off/L)
            # （off=feed_offset 自贴片中心沿谐振轴起算——openEMS 官方口径
            # x=-off 同基，#154 单源化 2026-10-03；忽略 G12 与有限 h 修正）
            r_edge = 60.0 * lambda0_mm / patch_w
            r_in = r_edge * math.sin(math.pi * feed_offset / patch_len) ** 2
            gamma_in = abs((r_in - self.z0) / (r_in + self.z0))
            s_data = _patch_sparams_1port(
                freq.f / 1e9, z0=self.z0, f0_ghz=self.f0_ghz,
                patch_len_mm=patch_len,
                feed_offset_mm=feed_offset,
                patch_w_mm=patch_w,
                eps_eff=cal.get("eps_eff", 2.33),
                s11_min_lin=gamma_in,
            )
        elif self.model_type == "mline":
            # 均匀微带线（WP2.1 锚）：w → εeff（skrf HJ 闭式）→ 相速/损耗。
            # 数据工厂/仲裁探针口径：变量驱动真实响应（w 变→εeff 变→相位斜率变）。
            from rfauto.adapters.openems_templates import template_meta
            from rfauto.core.physics_roles import resolve_role
            from rfauto.core.synthesis import Stackup, forward_z0

            w = resolve_role("line_width_mm", self._variables,
                             candidates=("w_mm",), default=1.113)
            line_len = resolve_role("line_length_mm", self._variables,
                                    candidates=("line_len_mm",), default=40.0)
            stackup = Stackup.from_materials_yaml(
                self._substrate_name or "rogers4350b_h0.508")
            _, eps_eff = forward_z0(w, self.f0_ghz, stackup)
            s_data = _mline_sparams(
                freq.f / 1e9, eps_eff=eps_eff, line_len_mm=line_len,
                tan_d=float(template_meta("mline")["substrate"].get("tan_d", 0.0037)),
            )
        elif self.model_type == "cpw":
            # 均匀共面波导（WP2.1 锚族）：w/gap → εeff（CPWG 共形映射
            # 闭式，#198 参照系修正：openEMS 官方口径 z-min=PEC 强制地，
            # 实际结构是 CPWG，无地 skrf CPW 口径作废）→ 相速/损耗
            from rfauto.core.physics_roles import resolve_role
            from rfauto.core.synthesis import Stackup

            w = resolve_role("line_width_mm", self._variables,
                             candidates=("w_mm",), default=0.849)
            gap = resolve_role("gap_width_mm", self._variables,
                               candidates=("gap_mm",), default=0.2)
            line_len = resolve_role("line_length_mm", self._variables,
                                    candidates=("line_len_mm",), default=40.0)
            stackup = Stackup.from_materials_yaml(
                self._substrate_name or "rogers4350b_h0.508")
            from rfauto.core.calculators import _cpwg_ri
            eps_eff = _cpwg_ri(w, gap, stackup.thickness_mm,
                               stackup.epsilon_r)[0]
            s_data = _cpw_sparams(
                freq.f / 1e9, eps_eff=eps_eff, line_len_mm=line_len,
                tan_d=stackup.loss_tangent)
        elif self.model_type == "dipole":
            # 半波振子（WP1.3 官方口径重写后）：L → λ/2 自由空间谐振
            # 闭式 → 单端口谐振谷（数据工厂语义：谷位随 L 精确移动）
            from rfauto.core.physics_roles import resolve_role

            dip_len = resolve_role(
                "resonator_length_mm", self._variables,
                candidates=("dipole_len_mm",), default=58.0)
            s_data = _dipole_sparams(
                freq.f / 1e9, dipole_len_mm=dip_len, z0=self.z0)
        elif self.model_type == "stripline":
            # 均匀带状线（WP2.1 锚族）：TEM 模 εeff=εr（精确，无色散
            # 一阶项）→ 相速/损耗闭式同 mline
            from rfauto.core.physics_roles import resolve_role
            from rfauto.core.synthesis import Stackup

            line_len = resolve_role("line_length_mm", self._variables,
                                    candidates=("line_len_mm",), default=40.0)
            stackup = Stackup.from_materials_yaml(
                self._substrate_name or "rogers4350b_h0.508")
            s_data = _mline_sparams(
                freq.f / 1e9, eps_eff=stackup.epsilon_r,
                line_len_mm=line_len, tan_d=stackup.loss_tangent)
        elif self.model_type == "cps":
            # 共面带 CPS（C9 传输线族 II）：w/gap → εeff（无地有限厚基板共形
            # 映射闭式 _cps_ri，refs §11；#154 同名参数逐参对语义：w_mm=单带宽、
            # gap_mm=两带间缝，与 openEMS _cps_lines 同口径）→ 相速/损耗闭式
            # 同 mline（匹配端接 LumpedPort R=Z0 → S11≈0 口径）
            from rfauto.core.calculators import _cps_ri
            from rfauto.core.physics_roles import resolve_role
            from rfauto.core.synthesis import Stackup

            w = resolve_role("line_width_mm", self._variables,
                             candidates=("w_mm",), default=2.95)
            gap = resolve_role("gap_width_mm", self._variables,
                               candidates=("gap_mm",), default=0.5)
            line_len = resolve_role("line_length_mm", self._variables,
                                    candidates=("line_len_mm",), default=40.0)
            stackup = Stackup.from_materials_yaml(
                self._substrate_name or "rogers4350b_h0.508")
            eps_eff = _cps_ri(w, gap, stackup.thickness_mm,
                              stackup.epsilon_r)[0]
            s_data = _cps_sparams(
                freq.f / 1e9, eps_eff=eps_eff, line_len_mm=line_len,
                tan_d=stackup.loss_tangent)
        elif self.model_type == "suspended_stripline":
            # 悬置带线（C9 传输线族 II）：w/b（基板厚=stackup h 居中对称填充）
            # → εeff（共形电容比闭式 _suspended_stripline_ri，两支精确极限锚
            # 回到 stripline）→ 相速/损耗闭式同 mline
            from rfauto.core.calculators import _suspended_stripline_ri
            from rfauto.core.physics_roles import resolve_role
            from rfauto.core.synthesis import Stackup

            w = resolve_role("line_width_mm", self._variables,
                             candidates=("w_mm",), default=0.9058)
            b_cav = self._parse_variable("b_mm", default=1.016)
            line_len = resolve_role("line_length_mm", self._variables,
                                    candidates=("line_len_mm",), default=40.0)
            stackup = Stackup.from_materials_yaml(
                self._substrate_name or "rogers4350b_h0.508")
            eps_eff = _suspended_stripline_ri(
                w, b_cav, stackup.thickness_mm, stackup.epsilon_r)[0]
            s_data = _suspended_stripline_sparams(
                freq.f / 1e9, eps_eff=eps_eff, line_len_mm=line_len,
                tan_d=stackup.loss_tangent)
        elif self.model_type == "siw":
            # 直 SIW 线段（siw-family 首族）：w/d/s → w_eff（Cassivi 2002
            # 等效宽度闭式，内部证据档 §1）→ 等效 RWG TE10
            # 色散 γ（复数支含 tanδ）；#154 同名参数逐参对语义：w_mm=两过孔
            # 列心距、d_mm=过孔直径、s_mm=过孔心距、line_len_mm=两端口面间距
            # ——与 openEMS _siw_lines 同口径
            from rfauto.core.calculators import siw_effective_width_mm
            from rfauto.core.physics_roles import resolve_role
            from rfauto.core.synthesis import Stackup

            w = resolve_role("line_width_mm", self._variables,
                             candidates=("w_mm",), default=12.1317)
            # d/s 无角色词表条目（suspended_stripline 的 b_mm 同例）：按名直读
            d = self._parse_variable("d_mm", default=0.6)
            s_pitch = self._parse_variable("s_mm", default=1.0)
            line_len = resolve_role("line_length_mm", self._variables,
                                    candidates=("line_len_mm",),
                                    default=63.0724)
            stackup = Stackup.from_materials_yaml(
                self._substrate_name or "rogers4350b_h0.508")
            weff = siw_effective_width_mm(w, d, s_pitch)
            s_data = _siw_sparams(
                freq.f / 1e9, weff_mm=weff, line_len_mm=line_len,
                tan_d=stackup.loss_tangent, epsilon_r=stackup.epsilon_r)
        elif self.model_type == "msl_siw_taper":
            # MSL 锥形过渡+SIW 直段（SIW 族第二成员，df6 A2）：w/d/s 沿用 siw
            # 语义（#154 同名参数逐参对语义）+ taper_len_mm/siw_len_mm；
            # w50/w_end 按 Z_PV 闭式链本通道精算（w_eff 单源，#1c 禁抄毫米数
            # ——与 openEMS 渲染层同链同参，非参数故逐通道精算）
            from rfauto.core.calculators import (
                siw_beta_rad_m,
                siw_effective_width_mm,
            )
            from rfauto.core.physics_roles import resolve_role
            from rfauto.core.synthesis import Stackup, inverse_width

            w = resolve_role("line_width_mm", self._variables,
                             candidates=("w_mm",), default=12.1317)
            # d/s/taper_len 无角色词表条目（siw d/s 同例）：按名直读
            d = self._parse_variable("d_mm", default=0.6)
            s_pitch = self._parse_variable("s_mm", default=1.0)
            taper_len = self._parse_variable("taper_len_mm", default=10.5121)
            siw_len = resolve_role("line_length_mm", self._variables,
                                   candidates=("siw_len_mm",),
                                   default=63.0724)
            stackup = Stackup.from_materials_yaml(
                self._substrate_name or "rogers4350b_h0.508")
            weff = siw_effective_width_mm(w, d, s_pitch)
            beta, _fc = siw_beta_rad_m(weff, stackup.epsilon_r, self.f0_ghz)
            if not (math.isfinite(beta) and beta > 0.0):
                raise ValueError(
                    f"msl_siw_taper: f0={self.f0_ghz}GHz 低于 TE10 截止 "
                    f"fc10={_fc:.4f}GHz")
            z_te = (2.0 * math.pi * self.f0_ghz * 1e9
                    * 1.25663706212e-6 / beta)
            z_pv = (2.0 * stackup.thickness_mm * 1e-3 * z_te
                    / (weff * 1e-3))
            w50, _z50, st50 = inverse_width(50.0, self.f0_ghz, stackup)
            if st50 != "ok":
                raise ValueError(
                    f"msl_siw_taper: 50Ω 线宽反解未自洽（{st50!r}）")
            w_end, _zend, stend = inverse_width(z_pv, self.f0_ghz, stackup)
            if stend != "ok":
                raise ValueError(
                    f"msl_siw_taper: Z_PV={z_pv:.4f}Ω 线宽反解未自洽"
                    f"（{stend!r}）")
            s_data = _msl_siw_taper_sparams(
                freq.f / 1e9, weff_mm=weff, siw_len_mm=siw_len,
                taper_len_mm=taper_len, w50_mm=w50, w_end_mm=w_end,
                h_mm=stackup.thickness_mm, epsilon_r=stackup.epsilon_r,
                tan_d=stackup.loss_tangent, z_ref=self.z0,
                f_mid_ghz=self.f0_ghz)
        elif self.model_type == "msl_cpw":
            # MSL↔CPWG 过渡（WP2.5 Tier 2，2026-09-16 正式注册）：wstep 式两段
            # 等长理想 TL 级联——微带段 skrf HJ MLine（w_msl）、CPWG 段共形映射
            # 闭式 _cpwg_ri（w_cpw/gap）；#154 同名参数逐参对语义：w_msl_mm/
            # w_cpw_mm/gap_cpw_mm/line_len_mm 与 openEMS _msl_cpw_lines 同口径
            # （理想=突变对接，渐变区 trans_len 不进理想级联）
            from rfauto.core.calculators import _cpwg_ri
            from rfauto.core.physics_roles import resolve_role
            from rfauto.core.synthesis import Stackup

            # resolve_role 显式候选名：数值/带单位字符串都可解析（_parse_variable
            # 对裸数值 .strip() 抛 AttributeError 静默回退默认值——尺度律测试传数值）
            w_msl = resolve_role("line_width_mm", self._variables,
                                 candidates=("w_msl_mm",), default=1.1134)
            w_cpw = resolve_role("step_width_mm", self._variables,
                                 candidates=("w_cpw_mm",), default=0.849)
            gap = resolve_role("gap_width_mm", self._variables,
                               candidates=("gap_cpw_mm",), default=0.2)
            line_len = resolve_role("line_length_mm", self._variables,
                                    candidates=("line_len_mm",), default=40.0)
            stackup = Stackup.from_materials_yaml(
                self._substrate_name or "rogers4350b_h0.508")
            f_mid = skrf.Frequency(self.f0_ghz, self.f0_ghz, 1, unit="GHz")
            m1 = skrf.media.MLine(frequency=f_mid, w=w_msl * 1e-3,
                                  h=stackup.thickness_mm * 1e-3,
                                  ep_r=stackup.epsilon_r)
            eps2, z2 = _cpwg_ri(w_cpw, gap, stackup.thickness_mm,
                                stackup.epsilon_r)
            s_data = _msl_cpw_sparams(
                freq.f / 1e9,
                eps_eff1=float(np.real(m1.ep_reff[0])), eps_eff2=float(eps2),
                z1=float(abs(m1.z0[0])), z2=float(z2),
                seg_len_mm=line_len / 2.0,
                tan_d=stackup.loss_tangent, z_ref=self.z0)
        elif self.model_type == "sma_launcher":
            # SMA 边缘弹射（WP2.5 Tier 2，2026-09-16 正式注册）：同轴段（PTFE
            # 填充 TEM εeff=er_fill 精确、Z0=(60/√εr)·ln(r_o/r_i) 闭式）+ 微带段
            # （skrf HJ MLine @w_msl）理想级联；coax_len=shell_len、msl_len=
            # line_len（openEMS _sma_launcher_lines 同口径，#154）。理想弹射
            # 寄生为零，引擎-理想偏差即弹射寄生（文献曲线门在真机侧）
            from rfauto.core.physics_roles import resolve_role
            from rfauto.core.synthesis import Stackup

            def _var(name: str, default: float) -> float:
                return float(resolve_role(name, self._variables,
                                          candidates=(name,), default=default))

            w_msl = _var("w_msl_mm", 1.1134)
            r_i = _var("r_i_mm", 0.635)
            r_o = _var("r_o_mm", 2.1244)
            er_fill = _var("er_fill", 2.1)
            shell_len = _var("shell_len_mm", 5.0)
            line_len = _var("line_len_mm", 40.0)
            tan_d_fill = _var("tan_d_fill", 0.0)   # PTFE tanδ（变体，nominal 无耗）
            if not (r_i > 0.0 and r_o > r_i and er_fill > 1.0):
                raise ValueError(
                    f"sma_launcher fake: 同轴几何/填充非法 r_i={r_i} r_o={r_o} "
                    f"er_fill={er_fill}（须 0<r_i<r_o、εr>1）")
            z_coax = 60.0 / math.sqrt(er_fill) * math.log(r_o / r_i)
            stackup = Stackup.from_materials_yaml(
                self._substrate_name or "rogers4350b_h0.508")
            f_mid = skrf.Frequency(self.f0_ghz, self.f0_ghz, 1, unit="GHz")
            m2 = skrf.media.MLine(frequency=f_mid, w=w_msl * 1e-3,
                                  h=stackup.thickness_mm * 1e-3,
                                  ep_r=stackup.epsilon_r)
            s_data = _sma_launcher_sparams(
                freq.f / 1e9, eps_eff_coax=float(er_fill),
                eps_eff_msl=float(np.real(m2.ep_reff[0])),
                z_coax=float(z_coax), z_msl=float(abs(m2.z0[0])),
                coax_len_mm=shell_len, msl_len_mm=line_len,
                tan_d=stackup.loss_tangent, z_ref=self.z0,
                tan_d_coax=tan_d_fill)
        elif self.model_type == "wstep":
            # 微带宽度阶跃（WP2.2 基元）：两段 HJ 闭式 TL 的 ABCD 级联
            # （理想阶跃=仅阻抗跳变；w→εeff/Z0 各自独立进判据）
            from rfauto.core.physics_roles import resolve_role
            from rfauto.core.synthesis import Stackup

            w1 = resolve_role("line_width_mm", self._variables,
                              candidates=("w1_mm",), default=1.1134)
            w2 = resolve_role("step_width_mm", self._variables,
                              candidates=("w2_mm",), default=1.897)
            line_len = resolve_role("line_length_mm", self._variables,
                                    candidates=("line_len_mm",), default=40.0)
            stackup = Stackup.from_materials_yaml(
                self._substrate_name or "rogers4350b_h0.508")
            f_mid = skrf.Frequency(self.f0_ghz, self.f0_ghz, 1, unit="GHz")
            m1 = skrf.media.MLine(frequency=f_mid, w=w1 * 1e-3,
                                  h=stackup.thickness_mm * 1e-3,
                                  ep_r=stackup.epsilon_r)
            m2 = skrf.media.MLine(frequency=f_mid, w=w2 * 1e-3,
                                  h=stackup.thickness_mm * 1e-3,
                                  ep_r=stackup.epsilon_r)
            s_data = _wstep_sparams(
                freq.f / 1e9,
                eps_eff1=float(np.real(m1.ep_reff[0])),
                eps_eff2=float(np.real(m2.ep_reff[0])),
                z1=float(abs(m1.z0[0])), z2=float(abs(m2.z0[0])),
                seg_len_mm=line_len / 2.0,
                tan_d=stackup.loss_tangent, z_ref=self.z0)
        elif self.model_type == "tjunc":
            # 微带 T 接头（WP2.2 基元）：理想结点+三条 HJ 线裁判，
            # 三端口 (n,3,3)。全臂同宽 50Ω，εeff 走 HJ 闭式。
            from rfauto.core.physics_roles import resolve_role
            from rfauto.core.synthesis import Stackup

            w = resolve_role("line_width_mm", self._variables,
                             candidates=("w_feed_mm",), default=1.1134)
            tl = resolve_role("line_length_mm", self._variables,
                              candidates=("through_len_mm",), default=25.0)
            bl = resolve_role("branch_length_mm", self._variables,
                              candidates=("branch_len_mm",), default=20.0)
            stackup = Stackup.from_materials_yaml(
                self._substrate_name or "rogers4350b_h0.508")
            f_mid = skrf.Frequency(self.f0_ghz, self.f0_ghz, 1, unit="GHz")
            media = skrf.media.MLine(frequency=f_mid, w=w * 1e-3,
                                     h=stackup.thickness_mm * 1e-3,
                                     ep_r=stackup.epsilon_r)
            eps_eff = float(np.real(media.ep_reff[0]))
            s_data = _tjunc_sparams(
                freq.f / 1e9, z_arm=self.z0, eps_eff=eps_eff,
                through_len_mm=tl, branch_len_mm=bl,
                tan_d=stackup.loss_tangent, z_ref=self.z0)
        elif self.model_type == "bend":
            # 微带直角弯折（WP2.2 基元）：理想级联（同宽两段），
            # εeff 走 HJ 闭式；弯角寄生是引擎唯一反射源
            from rfauto.core.physics_roles import resolve_role
            from rfauto.core.synthesis import Stackup

            w = resolve_role("line_width_mm", self._variables,
                             candidates=("w_mm",), default=1.1134)
            a = resolve_role("line_length_mm", self._variables,
                             candidates=("arm_len_mm",), default=20.0)
            stackup = Stackup.from_materials_yaml(
                self._substrate_name or "rogers4350b_h0.508")
            f_mid = skrf.Frequency(self.f0_ghz, self.f0_ghz, 1, unit="GHz")
            media = skrf.media.MLine(frequency=f_mid, w=w * 1e-3,
                                     h=stackup.thickness_mm * 1e-3,
                                     ep_r=stackup.epsilon_r)
            eps_eff = float(np.real(media.ep_reff[0]))
            s_data = _bend_sparams(
                freq.f / 1e9, eps_eff=eps_eff, arm_len_mm=a,
                z_arm=self.z0, tan_d=stackup.loss_tangent, z_ref=self.z0)
        elif self.model_type == "via":
            # 过孔过渡（WP2.2 收官）：理想过孔=两馈线直接级联，
            # εeff 走 HJ 闭式；过孔+反焊盘寄生是引擎唯一偏差源
            from rfauto.core.physics_roles import resolve_role
            from rfauto.core.synthesis import Stackup

            w = resolve_role("line_width_mm", self._variables,
                             candidates=("w_mm",), default=1.1134)
            feed = resolve_role("line_length_mm", self._variables,
                                default=60.0)
            stackup = Stackup.from_materials_yaml(
                self._substrate_name or "rogers4350b_h0.508")
            f_mid = skrf.Frequency(self.f0_ghz, self.f0_ghz, 1, unit="GHz")
            media = skrf.media.MLine(frequency=f_mid, w=w * 1e-3,
                                     h=stackup.thickness_mm * 1e-3,
                                     ep_r=stackup.epsilon_r)
            eps_eff = float(np.real(media.ep_reff[0]))
            s_data = _via_sparams(
                freq.f / 1e9, eps_eff=eps_eff, feed_len_mm=feed,
                z_feed=self.z0, tan_d=stackup.loss_tangent, z_ref=self.z0)
        elif self.model_type == "atten_pi":
            # π 型衰减器（WP2.3 首族）：理想电阻网络 ABCD 闭式
            # （电阻值由 E4 attenuator_pi 同源公式给出，平坦无频响）
            from rfauto.core.physics_roles import resolve_role

            atten = resolve_role("attenuation_db", self._variables,
                                 candidates=("atten_db",), default=10.0)
            s_data = _atten_pi_sparams(freq.f / 1e9, atten_db=atten,
                                       z_ref=self.z0)
        elif self.model_type == "atten_t":
            # T 型衰减器（WP2.3 横向变体）：理想电阻网络 ABCD 闭式
            from rfauto.core.physics_roles import resolve_role

            atten = resolve_role("attenuation_db", self._variables,
                                 candidates=("atten_db",), default=10.0)
            s_data = _atten_t_sparams(freq.f / 1e9, atten_db=atten,
                                      z_ref=self.z0)
        elif self.model_type == "ratrace":
            # rat-race 环形电桥（WP2.3）：理想 180° 混合环裁判
            # （窄带理想化——匹配/均分/隔离在 f0 处准确）
            s_data = _ratrace_sparams(freq.f / 1e9, z_ref=self.z0)
        elif self.model_type == "gysel":
            # Gysel 功分器（WP2.3 横向变体）：理想六节环 f0 闭式裁判
            # （#206 理论核验轮：均分 -3dB 同相/全匹配/输出互隔离；
            # 参数敏感度由引擎对照提供，fake 为确定性理想裁判）
            s_data = _gysel_sparams(freq.f / 1e9, z_ref=self.z0)
        elif self.model_type in ("hairpin", "hairpin_alt"):
            # 发夹线带通滤波器（WP2.3 滤波器族；2026-09-16 收口 A4 接通电气通道）：
            # arm_len→f0（λg/2 反演，εeff 走 HJ；同 hairpin_arm_len_mm 闭式的精确逆）
            # + gap_mm/gaps_mm→k（KJ 闭式 hairpin_k_from_gap_mm；#154 与渲染同语义：
            # 相邻谐振器外臂缝，逐缝列表优先）+ tap_frac→Q_e（抽头闭式
            # hairpin_qe_from_tap_frac × 真机修正 c(τ) _HAIRPIN_QE_CORR）
            # → hairpin_coupling_matrix → 耦合矩阵理想频响。设计链几何下与 C13
            # 理想响应逐位一致（单测 ≤1e-9）；gap↑→带宽单调窄、τ→0.5→Q_e↑（单测）。
            # hairpin_alt（2026-09-18 w2g，交替取向根修变体）：同一电气通道，唯一差异
            # = gap→k **不乘**同向结构修正 c(gap)（该表是同向 U 相消效应的真机标定，
            # 对交替取向不适用；c_alt≈1 为预声明假设，待真机 k(gap) 图谱判读）。
            from rfauto.adapters.openems_templates import (
                HAIRPIN_ALT_NOMINAL,
                HAIRPIN_NOMINAL,
            )
            from rfauto.core.coupled_microstrip import (
                hairpin_k_from_gap_mm,
                hairpin_qe_from_tap_frac,
            )
            from rfauto.core.physics_roles import resolve_role
            from rfauto.core.synthesis import Stackup, forward_z0

            is_alt = self.model_type == "hairpin_alt"
            nominal = HAIRPIN_ALT_NOMINAL if is_alt else HAIRPIN_NOMINAL
            w = resolve_role("line_width_mm", self._variables,
                             candidates=("w_mm",),
                             default=float(nominal["w_mm"]))
            arm_len = resolve_role("resonator_length_mm", self._variables,
                                   candidates=("arm_len_mm",))
            raw_order = self._variables.get("order",
                                            nominal["order"])
            try:
                order = int(float(raw_order))
            except (TypeError, ValueError):
                order = int(nominal["order"])
            stackup = Stackup.from_materials_yaml(
                self._substrate_name or "rogers4350b_h0.508")
            # εeff/KJ 一律用无耗准静态 Stackup（与 hairpin_arm_len_mm/coupled_microstrip
            # 同口径）：materials.yaml 的 tanδ 会让 skrf ep_reff 偏 −0.19%（f0 偏 +0.1%），
            # 设计几何便无法逐位复现 C13 理想响应（2026-09-16 A4 实测 max|ΔS|=0.079）
            stackup = Stackup(name=stackup.name, epsilon_r=stackup.epsilon_r,
                              thickness_mm=stackup.thickness_mm)
            f0_ghz = self.f0_ghz
            if arm_len is not None and arm_len > 0.0:
                _, eps_eff = forward_z0(w, self.f0_ghz, stackup)
                # λg/2 反演（hairpin_arm_len_mm 的精确逆）：c/(2·L·√εeff)，再乘真机
                # 谐振修正 c_f0（B2 pt4：U 弯+开路端等效缩短使 EM 谐振高于闭式 +3.7%）
                # 单位 Hz → GHz（同 _compute_f0_from_variables 的 /1e9 口径）
                f0_ghz = _HAIRPIN_F0_CORR * (299792458.0 / (2.0 * arm_len * 1e-3
                                                            * math.sqrt(eps_eff))) / 1e9
            # gap→k：gaps_mm 列表（长度 order−1）优先，否则标量 gap_mm 等缝；
            # KJ 在设计 f0 处求值（与 hairpin_design_from_order 同口径，往返精确）。
            # W4④（2026-09-17）：乘 hairpin 结构经验修正 c(gap)=k_EM/k_KJ（并排同向 U
            # 相邻臂开路端对齐 → 电/磁耦合反号相消，N=2 弱抽头真机标定表
            # core.coupled_microstrip.HAIRPIN_KGAP_TABLE_MM，c≈0.12-0.26、k_EM 上限 ~0.0155；
            # 闭式本身经 NGSolve 独立核实无误）；域外 clamp 取端点 c（fake 前向裁判的
            # 显式假设，非外推口径——设计反解 hairpin_gap_mm_from_k 仍 raise）。
            gaps = self._parse_list_variable("gaps_mm", [])
            if len(gaps) != order - 1:
                gap = resolve_role("gap_width_mm", self._variables,
                                   candidates=("gap_mm",),
                                   default=float(nominal["gap_mm"]))
                gaps = [float(gap)] * (order - 1)
            k_list = [hairpin_k_from_gap_mm(g_mm, w, self.f0_ghz,
                                            stackup.epsilon_r,
                                            stackup.thickness_mm,
                                            structural_correction=not is_alt,
                                            extrapolate="clamp")
                      for g_mm in gaps]
            raw_tau = self._variables.get("tap_frac",
                                          nominal["tap_frac"])
            try:
                tau = float(raw_tau)
            except (TypeError, ValueError):
                tau = float(nominal["tap_frac"])
            c0, c1 = _HAIRPIN_QE_CORR
            qe = hairpin_qe_from_tap_frac(tau) * (c0 + c1 * tau)
            s_data = _hairpin_sparams(freq.f / 1e9, f0_ghz=f0_ghz,
                                      order=order, z_ref=self.z0,
                                      k_list=k_list, qe=qe)
        elif self.model_type == "varactor_bpf":
            # 变容管调谐 BPF（M-5 首个半有源模板，2026-09-27 注册）：谐振族
            # 「谷位等效伸缩」惯例的 C(V) 版——arm_len/εeff 固定，偏置 V 经
            # 突变结 C(V)=Cj0/√(1+V/φ) 进主谐振方程 tan(βL)=−ωCZ0
            # （core/varactor.py 单源）解 f0(C(V))，响应=hairpin 耦合矩阵理想
            # 频响平移到 f0(C(V))。耦合链纯 KJ（gap→k structural_correction=
            # False——同向 U 的 c(gap) 修正是 hairpin 真机标定（W4④），本族
            # **预声明不转移**，与 hairpin_alt 同制度）。抽头链 τ→Q_e 走
            # **loaded 廓线** branch B（2026-09-29 P0 修复，与设计链同一新函数
            # 单源 varactor_tap_qe_loaded——旧 hairpin 无载廓线闭式（βL=π）
            # 与本族 βL∈(π/2,π) 节点不等位，外耦失配 3-1139×，审计 P0；
            # τ 语义自 C 端计 #154）。变量名与渲染同名同语义
            # （#154）；cj0_pf/phi_v/bias_v 只进 f0(C(V)) 不进导体几何。
            from rfauto.adapters.openems_templates import VARACTOR_BPF_NOMINAL
            from rfauto.core.coupled_microstrip import hairpin_k_from_gap_mm
            from rfauto.core.physics_roles import resolve_role
            from rfauto.core.synthesis import Stackup, forward_z0
            from rfauto.core.varactor import (
                C0,
                abrupt_junction_capacitance_pf,
                varactor_line_f0_ghz,
                varactor_tap_qe_loaded,
            )

            nominal = VARACTOR_BPF_NOMINAL
            w = resolve_role("line_width_mm", self._variables,
                             candidates=("w_mm",),
                             default=float(nominal["w_mm"]))
            arm_len = resolve_role("resonator_length_mm", self._variables,
                                   candidates=("arm_len_mm",),
                                   default=float(nominal["arm_len_mm"]))
            raw_order = self._variables.get("order", nominal["order"])
            try:
                order = int(float(raw_order))
            except (TypeError, ValueError):
                order = int(nominal["order"])
            stackup = Stackup.from_materials_yaml(
                self._substrate_name or "rogers4350b_h0.508")
            # 无耗准静态 Stackup（hairpin 同口径：tanδ 会偏移 εeff ~0.2%，
            # 设计几何无法逐位复现理想响应）
            stackup = Stackup(name=stackup.name, epsilon_r=stackup.epsilon_r,
                              thickness_mm=stackup.thickness_mm)
            _, eps_eff = forward_z0(w, self.f0_ghz, stackup)
            cj0 = float(resolve_role("cj0_pf", self._variables,
                                     candidates=("cj0_pf",),
                                     default=float(nominal["cj0_pf"])))
            phi = float(resolve_role("phi_v", self._variables,
                                     candidates=("phi_v",),
                                     default=float(nominal["phi_v"])))
            bias = float(resolve_role("bias_v", self._variables,
                                      candidates=("bias_v",),
                                      default=float(nominal["bias_v"])))
            c_v = abrupt_junction_capacitance_pf(bias, cj0, phi)
            f0_bias = varactor_line_f0_ghz(c_v, float(arm_len), self.z0,
                                           eps_eff)
            gaps = self._parse_list_variable("gaps_mm", [])
            if len(gaps) != order - 1:
                gap = resolve_role("gap_width_mm", self._variables,
                                   candidates=("gap_mm",),
                                   default=float(nominal["gap_mm"]))
                gaps = [float(gap)] * (order - 1)
            k_list = [hairpin_k_from_gap_mm(g_mm, w, self.f0_ghz,
                                            stackup.epsilon_r,
                                            stackup.thickness_mm,
                                            structural_correction=False)
                      for g_mm in gaps]
            raw_tau = self._variables.get("tap_frac", nominal["tap_frac"])
            try:
                tau = float(raw_tau)
            except (TypeError, ValueError):
                tau = float(nominal["tap_frac"])
            # loaded 廓线抽头外耦（P0 同步）：βL 在本档工作点 f0(C(V)) 求值
            # ——偏压耦合固变（C↑ ⇒ βL↓ ⇒ 同 τ 下 Q_e↑），与渲染同口径
            beta_l = (2.0 * math.pi * f0_bias * 1e9 * math.sqrt(eps_eff)
                      * float(arm_len) * 1e-3 / C0)
            qe = varactor_tap_qe_loaded(tau, beta_l)
            s_data = _hairpin_sparams(freq.f / 1e9, f0_ghz=f0_bias,
                                      order=order, z_ref=self.z0,
                                      k_list=k_list, qe=qe)
        elif self.model_type == "coupled_bpf":
            # 平行耦合 BPF（WP2.3 BPF 族锚，2026-09-14 注册）：几何列表
            # widths_mm/gaps_mm（与 openEMS 渲染同索引同语义，#154）→ KJ
            # 偶/奇模电气量 → 电路级联裁判同源闭式 _coupled_bpf_sparams。
            # 列表变量可为 list/tuple 或 "a,b,c" / "[a, b, c]" 字符串。
            from rfauto.adapters.openems_templates import COUPLED_BPF_NOMINAL
            from rfauto.core.physics_roles import resolve_role
            from rfauto.core.synthesis import Stackup

            widths = self._parse_list_variable(
                "widths_mm", list(COUPLED_BPF_NOMINAL["widths_mm"]))
            gaps = self._parse_list_variable(
                "gaps_mm", list(COUPLED_BPF_NOMINAL["gaps_mm"]))
            res_len = resolve_role(
                "resonator_length_mm", self._variables,
                candidates=("res_len_mm",),
                default=float(COUPLED_BPF_NOMINAL["res_len_mm"]))
            feed_len = resolve_role(
                "line_length_mm", self._variables,
                candidates=("feed_len_mm",),
                default=float(COUPLED_BPF_NOMINAL["feed_len_mm"]))
            stackup = Stackup.from_materials_yaml(
                self._substrate_name or "rogers4350b_h0.508")
            s_data = _coupled_bpf_sparams(
                freq.f / 1e9, widths_mm=widths, gaps_mm=gaps,
                res_len_mm=res_len, feed_len_mm=feed_len,
                f0_ghz=self.f0_ghz, er=stackup.epsilon_r,
                h_mm=stackup.thickness_mm, z_ref=self.z0)
        elif self.model_type in _C3_TEMPLATES:
            # C3 滤波器族 II（交指/梳状/SIR，2026-09-15 注册）：几何参数
            # （缝列表与渲染同索引同语义，#154）→ KJ 倒置器 → 并联谐振 J 链
            # 裁判同源闭式 _c3_sparams。列表变量可为 list/tuple 或字符串。
            from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL
            from rfauto.core.physics_roles import resolve_role
            from rfauto.core.synthesis import Stackup

            nominal = TEMPLATE_NOMINAL[self.model_type]
            c3_params: dict[str, Any] = {}
            for key, default in nominal.items():
                if isinstance(default, list):
                    c3_params[key] = self._parse_list_variable(key, list(default))
                elif key == "order":
                    raw_order = self._variables.get("order", default)
                    try:
                        c3_params[key] = int(float(raw_order))
                    except (TypeError, ValueError):
                        c3_params[key] = int(default)
                else:
                    c3_params[key] = float(resolve_role(
                        key, self._variables, candidates=(key,),
                        default=float(default)))
            stackup = Stackup.from_materials_yaml(
                self._substrate_name or "rogers4350b_h0.508")
            # 过孔电感开关（登记⑨+R1 校准 df5-c3fix；G-06 改道 2026-10-04）：
            # 缺省 0.0=理想短路（旧名义逐位不变，旧黄金钉保持）；变量
            # "l_via_h" 显式开启——"auto"=经锚注册表 c3.l_via_h.openems-hfss-v1
            # 解析（本模块 _c3_l_via_anchor_h 惰性+模块级缓存，回退字面 0.125nH
            # HFSS 仲裁校准值，真机裁判口径，原 G-P 几何值高估已弃），数值=指定
            # 电感（H）。补偿后的再生名义几何配 l_via_h="auto" 裁判时谐振回 f0。
            lv_raw = self._variables.get("l_via_h")
            l_via: float = 0.0
            if lv_raw is not None:
                l_via = (_c3_l_via_anchor_h() if isinstance(lv_raw, str)
                         and lv_raw.strip().lower() == "auto"
                         else float(lv_raw))
            s_data = _c3_sparams(
                freq.f / 1e9, self.model_type, c3_params,
                f0_ghz=self.f0_ghz, er=stackup.epsilon_r,
                h_mm=stackup.thickness_mm, z_ref=self.z0, l_via_h=l_via)
        elif self.model_type in ("cline_coupler", "lange", "branchline_2sect"):
            # §C4 耦合器族 II（2026-09-16 注册）：几何 → HJ/KJ 电气量 → 偶/奇模
            # 裁判同源闭式（cline 真非同步相速；lange 四线等效理想；两节分支线
            # 二分频响）。变量名与 openEMS 渲染同名同语义（#154）；
            # w_feed_mm 只进几何。
            from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL
            from rfauto.core.physics_roles import resolve_role
            from rfauto.core.synthesis import Stackup

            nominal = TEMPLATE_NOMINAL[self.model_type]
            c4: dict[str, float] = {
                key: float(resolve_role(key, self._variables, candidates=(key,),
                                        default=float(default)))
                for key, default in nominal.items()}
            stackup = Stackup.from_materials_yaml(
                self._substrate_name or "rogers4350b_h0.508")
            common = {"f0_ghz": self.f0_ghz, "er": stackup.epsilon_r,
                      "h_mm": stackup.thickness_mm, "z_ref": self.z0}
            if self.model_type == "cline_coupler":
                s_data = _cline_coupler_sparams(
                    freq.f / 1e9, w_mm=c4["w_mm"], gap_mm=c4["gap_mm"],
                    coupled_len_mm=c4["coupled_len_mm"], **common)
            elif self.model_type == "lange":
                s_data = _lange_sparams(
                    freq.f / 1e9, w_mm=c4["w_mm"], gap_mm=c4["gap_mm"],
                    finger_len_mm=c4["finger_len_mm"], **common)
            else:
                s_data = _branchline_2sect_sparams(
                    freq.f / 1e9, w_main_mm=c4["w_main_mm"],
                    w_out_mm=c4["w_out_mm"], w_mid_mm=c4["w_mid_mm"],
                    sect_len_mm=c4["sect_len_mm"],
                    branch_len_mm=c4["branch_len_mm"], **common)
        elif self.model_type in ("stepped_impedance", "coupled_line"):
            # 初始模板补注册（2026-09-16）：阶梯阻抗线（HJ (Z,εeff) → cosim
            # ABCD 级联）/ 耦合线（KJ 偶/奇模 → 4 端口 port4 端接 50Ω 化 3 端口）。
            # 变量名与渲染同名同语义（#154）；n_segments 整数解析同 helix_turns。
            from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL
            from rfauto.core.physics_roles import resolve_role
            from rfauto.core.synthesis import Stackup

            nominal = TEMPLATE_NOMINAL[self.model_type]
            geom: dict[str, Any] = {}
            for key, default in nominal.items():
                value = resolve_role(key, self._variables, candidates=(key,),
                                     default=float(default))
                geom[key] = (round(float(value)) if key == "n_segments"
                             else float(value))
            stackup = Stackup.from_materials_yaml(
                self._substrate_name or "rogers4350b_h0.508")
            common = {"f0_ghz": self.f0_ghz, "er": stackup.epsilon_r,
                      "h_mm": stackup.thickness_mm, "z_ref": self.z0}
            if self.model_type == "stepped_impedance":
                s_data = _stepped_impedance_sparams(
                    freq.f / 1e9, z1_width_mm=geom["z1_width_mm"],
                    z2_width_mm=geom["z2_width_mm"], seg_len_mm=geom["seg_len_mm"],
                    n_segments=geom["n_segments"],
                    feed_w_mm=geom.get("feed_w_mm"), **common)
            else:
                s_data = _coupled_line_sparams(
                    freq.f / 1e9, coupled_len_mm=geom["coupled_len_mm"],
                    line_w_mm=geom["line_w_mm"], gap_mm=geom["gap_mm"], **common)
        elif self.model_type in _ANT2_TEMPLATES:
            # 天线族 II（§10.3 C1，2026-09-14 注册）：几何参数 → 闭式设计函数
            # 精确逆 f0 → 一阶谐振电路（设计口径裁判；R/Q 常数未标定不进锚）
            from rfauto.adapters.openems_templates import ANTENNA2_NOMINAL
            from rfauto.core.physics_roles import resolve_role
            from rfauto.core.synthesis import Stackup

            nominal = ANTENNA2_NOMINAL[self.model_type]
            params: dict[str, Any] = {}
            for key, default in nominal.items():
                value = resolve_role(key, self._variables, candidates=(key,),
                                     default=float(default))
                params[key] = (round(float(value)) if key == "helix_turns"
                               else float(value))
            stackup = Stackup.from_materials_yaml(
                self._substrate_name or "rogers4350b_h0.508")
            s_data = _antenna2_sparams(
                freq.f / 1e9, self.model_type, params, z0=self.z0,
                er=stackup.epsilon_r, h_mm=stackup.thickness_mm,
                eps_eval_ghz=self.f0_ghz)
        elif self.model_type in _ARRAY_TEMPLATES:
            # §10.3 C2 阵列族（2026-09-15 注册）：几何参数 → 单元设计式精确逆 f0
            # → 一阶串联谐振（设计口径裁判；R/Q 一阶常数未标定不进锚）
            from rfauto.adapters.openems_templates import ARRAY_NOMINAL
            from rfauto.core.physics_roles import resolve_role
            from rfauto.core.synthesis import Stackup

            nominal = ARRAY_NOMINAL[self.model_type]
            arr_params: dict[str, Any] = {
                key: float(resolve_role(key, self._variables, candidates=(key,),
                                        default=float(default)))
                for key, default in nominal.items()}
            stackup = Stackup.from_materials_yaml(
                self._substrate_name or "rogers4350b_h0.508")
            s_data = _array_sparams(
                freq.f / 1e9, self.model_type, arr_params, z0=self.z0,
                er=stackup.epsilon_r, h_mm=stackup.thickness_mm)
        elif self.model_type in _EEP_TEMPLATES:
            # §DP-4 P3 EEP 阵列族（2026-09-24 注册）：几何参数 → 单元设计式
            # 精确逆 f0 → 一阶谐振对角 + 一阶互耦非对角（κ=−30dB 常数不进锚、
            # 相位=k0·d_ij 几何驱动；设计口径裁判）
            from rfauto.adapters.openems_templates import EEP_NOMINAL
            from rfauto.core.physics_roles import resolve_role
            from rfauto.core.synthesis import Stackup

            nominal = EEP_NOMINAL[self.model_type]
            eep_params: dict[str, Any] = {
                key: float(resolve_role(key, self._variables, candidates=(key,),
                                        default=float(default)))
                for key, default in nominal.items()}
            stackup = Stackup.from_materials_yaml(
                self._substrate_name or "rogers4350b_h0.508")
            s_data = _eep_sparams(
                freq.f / 1e9, self.model_type, eep_params, z0=self.z0,
                er=stackup.epsilon_r, h_mm=stackup.thickness_mm)
        elif self.model_type in ("slotline", "slotline_lumped",
                                 "msl_slot_transition", "marchand_balun"):
            # 槽线族（2026-09-18 w1b 注册）：几何 → 槽线闭式 γ（core/slotline，
            # 域外显式报错不外推）→ 各路线 fake 裁判（路线 A 匹配线/路线 B 并联
            # 抽头 #250/过渡 Knorr 一阶等效/巴伦两节对称耦合段电路级）。变量名与
            # 渲染同名同语义（#154）；h_mm=模板参数（设计点 1.524，理由见
            # SLOTLINE_NOMINAL 注）——禁用 stackup.thickness_mm（0.508 落闭式域外）。
            from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL
            from rfauto.core.physics_roles import resolve_role
            from rfauto.core.synthesis import Stackup

            stackup = Stackup.from_materials_yaml(
                self._substrate_name or "rogers4350b_h0.508")
            nominal = TEMPLATE_NOMINAL[self.model_type]
            fam: dict[str, float] = {
                key: float(resolve_role(key, self._variables, candidates=(key,),
                                        default=float(default)))
                for key, default in nominal.items()
                if isinstance(default, (int, float))}
            fam["er"] = stackup.epsilon_r
            fam["tan_d"] = stackup.loss_tangent
            fam["f0_ghz"] = self.f0_ghz
            common = {"er": fam["er"], "tan_d": fam["tan_d"],
                      "f0_ghz": fam["f0_ghz"]}
            if self.model_type == "slotline":
                s_data = _slotline_route_a_sparams(
                    freq.f / 1e9, w_mm=fam["w_mm"],
                    line_len_mm=fam["line_len_mm"], h_mm=fam["h_mm"], **common)
            elif self.model_type == "slotline_lumped":
                s_data = _slotline_route_b_sparams(
                    freq.f / 1e9, w_mm=fam["w_mm"],
                    line_len_mm=fam["line_len_mm"], h_mm=fam["h_mm"],
                    r_port_ohm=self._variables.get("r_port_ohm"), **common)
            elif self.model_type == "msl_slot_transition":
                s_data = _msl_slot_transition_sparams(
                    freq.f / 1e9, w_slot_mm=fam["w_slot_mm"],
                    x_port_mm=fam["x_port_mm"], h_mm=fam["h_mm"], **common)
            else:
                s_data = _marchand_balun_sparams(
                    freq.f / 1e9, w_slot_mm=fam["w_slot_mm"], h_mm=fam["h_mm"],
                    **common)
        elif self.model_type in _MMWAVE_SERIES_TEMPLATES:
            # §MMWAVE_SERIES_ARRAY（2026-09-26 df7 C10d 注册）：几何参数 →
            # 单元设计式精确逆 f0 → 一阶谐振吸收谷（谷位进判据；R/Q 一阶
            # 常数未标定不进锚）。er/h_mm 走模板名义毫米波板（RO3003 类，
            # #154 同名同语义；禁 stackup 缺省 0.508 板——78GHz 非物理厚）
            from rfauto.adapters.openems_templates import MMWAVE_SERIES_NOMINAL
            from rfauto.core.physics_roles import resolve_role

            nominal = MMWAVE_SERIES_NOMINAL
            mm_params: dict[str, Any] = {
                key: (int(float(resolve_role(key, self._variables,
                                             candidates=(key,),
                                             default=float(default))))
                      if key == "n_elem" else
                      float(resolve_role(key, self._variables,
                                         candidates=(key,),
                                         default=float(default))))
                for key, default in nominal.items()}
            s_data = _mmwave_series_sparams(freq.f / 1e9, mm_params,
                                            z0=self.z0)
        elif self.model_type == "coil_nfc":
            # NFC 线圈族（2026-09-26 df7 C10b 注册）：几何 → core Mohan
            # current_sheet 闭式 L → 外匹配电容 → 串联 RLC 一阶 f0 谷 +
            # Q 定宽（未标定，_coil_nfc_sparams docstring 如实声明）。变量
            # 名与渲染同名同语义（#154）；f0 由 L·C 自洽涌现（线圈谐振是
            # 几何+外配电容的因变量，不读 recipe f0_ghz）。
            from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL
            from rfauto.core.physics_roles import resolve_role

            nominal = TEMPLATE_NOMINAL["coil_nfc"]
            n_turns = resolve_role("n_turns", self._variables,
                                   candidates=("n_turns",),
                                   default=float(nominal["n_turns"]))
            d_out_mm = resolve_role("d_out_mm", self._variables,
                                    candidates=("d_out_mm",),
                                    default=float(nominal["d_out_mm"]))
            w_mm = resolve_role("w_mm", self._variables,
                                candidates=("w_mm",),
                                default=float(nominal["w_mm"]))
            s_mm = resolve_role("s_mm", self._variables,
                                candidates=("s_mm",),
                                default=float(nominal["s_mm"]))
            s_data = _coil_nfc_sparams(
                freq.f / 1e9, z0=self.z0, n_turns=int(float(n_turns)),
                d_out_mm=float(d_out_mm), w_mm=float(w_mm), s_mm=float(s_mm))
        elif self.model_type == "octagonal_spiral":
            # 八角螺旋电感族（2026-10-23 aurora_k K11 注册）：几何 → core
            # Mohan current_sheet 闭式 L → 匝间寄生 C_par 一阶 → 并联寄生
            # 谐振自洽 S11（未标定，_octagonal_spiral_sparams docstring 如实
            # 声明）。变量名与渲染/CALC 同名同语义（#154，全 μm IPD 口径）；
            # f0/SRF 由 L·C_par 自洽涌现（不读 recipe f0_ghz）。
            from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL
            from rfauto.core.physics_roles import resolve_role

            nominal = TEMPLATE_NOMINAL["octagonal_spiral"]
            n_turns = resolve_role("n_turns", self._variables,
                                   candidates=("n_turns",),
                                   default=float(nominal["n_turns"]))
            din_um = resolve_role("din_um", self._variables,
                                  candidates=("din_um",),
                                  default=float(nominal["din_um"]))
            w_um = resolve_role("w_um", self._variables,
                                candidates=("w_um",),
                                default=float(nominal["w_um"]))
            s_um = resolve_role("s_um", self._variables,
                                candidates=("s_um",),
                                default=float(nominal["s_um"]))
            s_data = _octagonal_spiral_sparams(
                freq.f / 1e9, z0=self.z0, n_turns=int(float(n_turns)),
                din_um=float(din_um), w_um=float(w_um), s_um=float(s_um))
        elif self.model_type == "mim_cap":
            # MIM 叠层电容族（2026-10-23 aurora_k K12 注册）：几何 → core
            # 平行板闭式 C → 一阶串联寄生（R_s/L_s）→ 自洽 1 端口 S11
            # （未标定，_mim_cap_sparams docstring 如实声明）。变量名与
            # 渲染/CALC 同名同语义（#154，全 μm IPD 口径）；SRF 由 L_s·C
            # 自洽涌现（不读 recipe f0_ghz）。
            from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL
            from rfauto.core.physics_roles import resolve_role

            nominal = TEMPLATE_NOMINAL["mim_cap"]
            w_um = resolve_role("w_um", self._variables,
                                candidates=("w_um",),
                                default=float(nominal["w_um"]))
            l_um = resolve_role("l_um", self._variables,
                                candidates=("l_um",),
                                default=float(nominal["l_um"]))
            d_um = resolve_role("d_um", self._variables,
                                candidates=("d_um",),
                                default=float(nominal["d_um"]))
            er_diel = resolve_role("er_diel", self._variables,
                                   candidates=("er_diel",),
                                   default=float(nominal["er_diel"]))
            s_data = _mim_cap_sparams(
                freq.f / 1e9, z0=self.z0, w_um=float(w_um),
                l_um=float(l_um), d_um=float(d_um), er_diel=float(er_diel))
        elif self.model_type == "interdigital_cap":
            # 叉指电容族（2026-10-23 aurora_k K12 注册）：几何 → core 侧壁
            # sum-of-capacitances 闭式 C（±50% 精度类如实声明）→ 一阶串联
            # 寄生（R_s/L_s）→ 2 端口串联口径解析 S（K8 Z12 提取链同口径，
            # 未标定，_interdigital_cap_sparams docstring 如实声明）。变量
            # 名与渲染/CALC 同名同语义（#154，全 μm IPD 口径）；SRF 由
            # L_s·C 自洽涌现（不读 recipe f0_ghz）。
            from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL
            from rfauto.core.physics_roles import resolve_role

            nominal = TEMPLATE_NOMINAL["interdigital_cap"]
            n_fingers = int(float(resolve_role(
                "n_fingers", self._variables, candidates=("n_fingers",),
                default=float(nominal["n_fingers"]))))
            lf_um = resolve_role("lf_um", self._variables,
                                 candidates=("lf_um",),
                                 default=float(nominal["lf_um"]))
            wf_um = resolve_role("wf_um", self._variables,
                                 candidates=("wf_um",),
                                 default=float(nominal["wf_um"]))
            sf_um = resolve_role("sf_um", self._variables,
                                 candidates=("sf_um",),
                                 default=float(nominal["sf_um"]))
            e_tip_um = resolve_role("e_tip_um", self._variables,
                                    candidates=("e_tip_um",),
                                    default=float(nominal["e_tip_um"]))
            s_data = _interdigital_cap_sparams(
                freq.f / 1e9, z0=self.z0, n_fingers=n_fingers,
                lf_um=float(lf_um), wf_um=float(wf_um), sf_um=float(sf_um),
                e_tip_um=float(e_tip_um))
        else:
            raise ValueError(f"未知模型类型: {self.model_type}")

        # 故障注入：非被动 S 参数
        if self.fault.passivity_violation:
            # 强制使某些频点的 |S| > 1
            s_data[0, 0, 0] = 1.5 + 0j  # S11 > 1 → passivity violation

        # 创建 skrf.Network
        self._network = skrf.Network(
            frequency=freq,
            s=s_data,
            z0=self.z0,
        )

        return SolveReport(
            success=True,
            passes=1,
            delta_s_final=0.001,
            wall_time_s=0.01,
            message=f"FakeAdapter 解析求解完成 ({self.model_type})",
        )

    def get_sparams(self) -> skrf.Network:
        """返回合成的 S 参数网络。"""
        if self._network is None:
            raise RuntimeError("尚未求解，请先调用 solve()")
        return self._network

    def export_touchstone(
        self,
        path: str | Path,
        contract: Any = None,
    ) -> Path:
        """导出 Touchstone 文件。"""
        if self._network is None:
            raise RuntimeError("尚未求解，请先调用 solve()")

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        # 契约校验（如果提供）—— 兼容 AdsExchangeContract 与 TouchstoneContract
        if contract is not None:
            from rfauto.core.contracts import AdsExchangeContract, TouchstoneContract
            tc = contract.touchstone if isinstance(contract, AdsExchangeContract) else contract
            if isinstance(tc, TouchstoneContract) and self._network.nports != len(tc.port_order):
                from rfauto.core.errors import ContractViolationError
                raise ContractViolationError(
                    f"端口数不匹配：契约 {len(tc.port_order)}，"
                    f"网络 {self._network.nports}",
                )

        self._network.write_touchstone(str(path))
        return path

    def get_far_field(self, setup_name: str, freq_ghz: float = 2.4) -> dict[str, Any] | None:
        "FakeAdapter 远场数据（解析近似）。返回理想贴片天线方向图近似。"
        import numpy as np
        theta = np.linspace(0, 180, 37).tolist()
        phi = np.linspace(0, 360, 73).tolist()
        gain_db = [float(10 * np.log10(max(np.cos(np.radians(t)), 0.01))) for t in theta]
        return {"theta": theta, "phi": phi, "gain_db": gain_db, "pattern_type": "cosine_approx", "freq_ghz": freq_ghz}

    def close(self, save: bool = True) -> None:
        """关闭会话。"""
        self._connected = False
        self._network = None

    def capabilities(self) -> AdapterCapabilities:
        """FakeAdapter 能力声明。"""
        return AdapterCapabilities(
            supports_wave_port=False,
            supports_lumped_port=True,
            supports_field_export=False,
            supports_convergence_report=True,
            supports_touchstone_export=True,
            supports_headless_solve=True,
            supports_optimetrics=False,
        )

    def health_check(self) -> bool:
        """健康检查——FakeAdapter 始终健康。"""
        return self._connected

    def ensure_connected(self) -> None:
        """自愈重连（缺口 4 R5）——FakeAdapter 无真实会话，直接复连。"""
        self._connected = True
