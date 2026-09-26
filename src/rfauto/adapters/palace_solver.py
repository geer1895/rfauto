"""Palace FEM solver adapter (Direction 5)。

Palace（AWS Labs，Apache-2.0，FEM/libCEED）微波 S 参数提取适配器。

2026-09-22 按 Palace v0.18.1 官方口径对齐（实测取证见
runs/palace_spike/schema_fix_plan.md，取证源=官方 config-schema.json（tag
v0.18.1）/docs/src/run.md/palace/models/postoperatorcsv.cpp）：
- build_geometry(): 生成 Palace JSON 配置——官方五分节
  Problem/Model/Domains/Boundaries/Solver（顶层键集由此固定），
  Problem.Type="Driven"；材料段（Domains.Materials）与端口/边界段
  （Boundaries.WavePort/LumpedPort/PEC 等）由调用方按官方 schema 透传，
  材料必须带 Attributes 域标签绑定（适配器不造默认域标签/材料数值）。
  网格文件（gmsh .msh）由调用方经 geometry["mesh_file"] 提供，网格坐标
  单位经 geometry["mesh_l0_m"]（Model.L0，米）显式声明——Palace 是 FEM
  求解器，网格生成属 gmsh 域（诚实边界，不做隐式降级）。
- solve(): 子进程执行 `<exe> <CONFIG 绝对路径>`（官方 CLI：配置文件是
  位置参数，不存在 -config 旗标；docs/src/run.md），exe 可为官方 Linux
  二进制也可为 Windows 侧 WSL wrapper（命令面对 wrapper 透明）；解析
  `<Problem.Output>/port-S.csv`（v0.18.1 后处理 S 参数文件，dB 幅值+
  度相位列，频率列 GHz）为 (n, n_ports, n_ports) 线性复数矩阵；单激励
  run 仅激励列有测量值，未测条目零填并在 message 报告已测清单。
- 多激励 S 矩阵（2026-09-22 消账 PENDING #3，源码+真跑双取证见
  runs/palace_spike/df5_multiexcite_criteria.md）：官方**单 run 多激励**
  （drivensolver.cpp L154 主循环激励外层×频率内层，每激励扫全频段）；
  port-S.csv 单文件逐激励列块（postoperatorcsv.cpp InitializePortS：列
  = f (GHz) + 逐激励 e × 逐端口 o 交替 |S[o][e]| (dB)/arg(S[o][e])
  (deg.)，仅 `IsMultipleSimple()`（每组恰 1 端口）才创建）。config 契约
  =每端口 `Excitation: <自身 Index>`（utils/configfile.cpp ParsePortExcitation
  L416：bool/非负整数→组索引，缺省 0 不激励）。build 期守卫拒绝
  多端口共享激励组（该形态 IsMultipleSimple()==false → port-S.csv 必不
  产出，run rc=0 静默——Case B 真跑实证），激励组索引≠端口 Index 时
  warning（官方归一化不适用，S 列按激励组索引）。解析按 (o,e) 列标签
  回填全矩阵；已测掩码经 get_measured_mask() 结构化透出（#314 口径）。
- exe 解析链（resolve_palace_exe，2026-09-23 WSL2 通道落地，判据见
  runs/palace_spike/bridge_criteria.md §1）：① env `RFAUTO_PALACE_EXE`
  （显式绝对路径，指向 Windows wrapper `palace.cmd` 或原生二进制——存在
  即用，不存在则 warning+不可用，不静默落回）；② 仓库
  `tools/palace-install/bin/`（win32 命中 `palace.cmd`/`palace.bat`，
  非 Windows 命中 `palace`；wrapper 由 scripts/palace_wsl_wrapper.py 生成，
  内部走 `wsl -d rfauto-ubuntu --exec` + WSLENV 传 config 路径）；③ PATH
  which（官方二进制名候选）。EMSolverConfig.exe_path 显式传参仍是最高权威。
  PENDING_BINARY #2 消账：`convergence_threshold` **维持不映射**
  Solver.Driven.AdaptiveTol——官方 schema（v0.18.1 config-schema.json）与
  源码（utils/configfile.cpp DrivenSolverData / models/romoperator.cpp）
  实证 AdaptiveTol 是"自适应快频扫 ROM 插值误差容差"且 0=关闭自适应逐点
  全阶求解（缺省 0.0），与"求解收敛阈值"语义不同；映射会把缺省 run 从
  逐点全阶静默翻转为 ROM 扫频（还触 Restart≠1 与 adaptive 互斥的
  MFEM_VERIFY 硬约束）。如需 ROM 自适应扫频，走 Solver 透传面显式声明。
- visualizations(): 声明 model3d（网格文件）与 sparams 产物（6g 协议）。

安装说明见 knowledge/compat_matrix.yaml palace 条目：官方无 Windows 预编译
（零 release 资产），本机经 WSL2 发行版 rfauto-ubuntu 源码构建 v0.18.1
（构建/验证实录 runs/palace_spike/wsl_validation.md，官方例 7 案 10/10 门
PASS），Windows 侧经 tools wrapper 端到端真跑闭环（bridge_smoke.md）。
"""

from __future__ import annotations

import contextlib
import csv
import json
import logging
import os
import re
import subprocess
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, ClassVar

from rfauto.adapters.em_solver_base import (
    EMSolverAdapter,
    EMSolverConfig,
    EMSolverResult,
    SolverCapabilities,
)

logger = logging.getLogger(__name__)

# 官方 v0.18.1 口径常量（出处：scripts/schema/config-schema.json + docs/src/run.md
# + palace/models/postoperatorcsv.cpp，均 tag v0.18.1 实测，2026-09-22）
_PALACE_CONFIG_FILENAME = "palace_config.json"
_PALACE_OUTPUT_DIR = "postpro"  # Problem.Output 官方缺省目录
_PALACE_SPARAM_CSV = "port-S.csv"  # Driven S 参数文件（v0.18.1 起此名，非 palace.csv）
# 官方配置顶层五分节（config-schema.json 顶层 required）
OFFICIAL_TOP_LEVEL_KEYS = ("Problem", "Model", "Domains", "Boundaries", "Solver")
# 官方 Boundaries 分节合法子键（config-schema.json Boundaries.properties）
OFFICIAL_BOUNDARY_KEYS = (
    "Absorbing", "Conductivity", "FloquetPort", "FluxLoop", "Ground",
    "Impedance", "LumpedPort", "PEC", "PMC", "Periodic", "Postprocessing",
    "RationalImpedance", "SurfaceCurrent", "Terminal", "WavePort",
    "WavePortPEC", "ZeroCharge",
)
# 适配器声明支持透传的端口边界（能力位 supports_wave_port/lumped_port 的事实依据）
_PORT_BOUNDARY_KEYS = ("WavePort", "LumpedPort")
# port-S.csv 列标签形态：|S[o][e]| (dB) / arg(S[o][e]) (deg.)
_S_PARAM_COL_RE = re.compile(r"\[\s*(\d+)\s*\]\s*\[\s*(\d+)\s*\]")

# ── exe 解析链（bridge_criteria.md §1，2026-09-23 WSL2 通道落地）────────────
_PALACE_ENV_VAR = "RFAUTO_PALACE_EXE"
# PATH which 候选：官方二进制名 palace-<ARCH>.bin（docs/src/run.md）+ 常见
# 包装脚本名（现行探测链，缺省行为不变）
_WHICH_CANDIDATES = ("palace", "palace.exe", "palace-x86_64.bin", "palace-arm64.bin")
# 仓库安装目录（tools/ 不入 git；存在才参与探测）
_TOOLS_BIN_SUBDIR = Path("tools") / "palace-install" / "bin"
# 目录内 wrapper 名按平台区分：bash 脚本 `palace` 在 Windows 不可执行，禁止命中
_WIN_WRAPPER_NAMES = ("palace.cmd", "palace.bat")
_POSIX_WRAPPER_NAMES = ("palace",)


def _tools_bin_dir() -> Path | None:
    """仓库内 Palace 安装目录（editable 安装布局下 repo 根=src 上三级；否则 None）。"""
    root = Path(__file__).resolve().parents[3]
    cand = root / _TOOLS_BIN_SUBDIR
    return cand if cand.is_dir() else None


def _probe_tools_bin() -> str | None:
    """第 2 级探测：仓库安装目录内的平台 wrapper（单测可 monkeypatch 隔离）。"""
    d = _tools_bin_dir()
    if d is None:
        return None
    names = _WIN_WRAPPER_NAMES if os.name == "nt" else _POSIX_WRAPPER_NAMES
    for name in names:
        p = d / name
        if p.is_file():
            return str(p)
    return None


def resolve_palace_exe(environ: Mapping[str, str] | None = None) -> str | None:
    """Palace 启动器三级解析链（优先级与 env 语义，判据 bridge_criteria §1）。

    1. env ``RFAUTO_PALACE_EXE``：显式绝对路径（Windows wrapper
       ``palace.cmd`` 或原生二进制）——存在即用；**不存在则 warning 并返回
       None（显式指定坏了就显式不可用，不静默落回探测链）**。
    2. 仓库 ``tools/palace-install/bin/``（win32: ``palace.cmd``/``palace.bat``；
       其他平台: ``palace``）。
    3. PATH which（候选含官方二进制名 palace-<ARCH>.bin，现行行为）。

    ``EMSolverConfig.exe_path`` 显式传参仍由 connect()/is_available() 保持
    最高权威，本函数只负责"未显式传参"时的探测。
    """
    import shutil

    env = os.environ if environ is None else environ
    explicit = env.get(_PALACE_ENV_VAR)
    if explicit:
        if Path(explicit).is_file():
            return str(explicit)
        logger.warning(
            "%s=%r 指向不存在的路径——显式指定优先，判不可用（不落回探测链）",
            _PALACE_ENV_VAR, explicit,
        )
        return None
    probed = _probe_tools_bin()
    if probed:
        return probed
    for c in _WHICH_CANDIDATES:
        resolved = shutil.which(c)
        if resolved:
            # 返回 which 解析后的绝对路径（裸候选名会让
            # is_available/connect 的 Path.exists() 门误判不可用）
            return resolved
    return None


class PalaceSolver(EMSolverAdapter):
    """Palace FEM solver adapter。

    Follows same subprocess + result file pattern as OpenEMSSolver.
    """

    # A5 能力声明（如实，2026-09-12 逐行核对；2026-09-22 schema 对齐后复核）：
    #   - 端口：geometry["ports"] 以官方 Boundaries 端口组 dict 透传
    #     （{"WavePort":[...]/"LumpedPort":[...]}，适配器不构造端口几何）
    #     → wave/lumped 均 True；
    #   - 材料：Domains.Materials 由调用方必填透传（须带 Attributes），
    #     适配器不造默认材料；
    #   - 场导出/收敛报告/optimetrics/nf2ff/SAR：适配器无对应实现 → False；
    #   - Touchstone：_parse_palace_csv 仅解析 port-S.csv（CSV），无 Touchstone
    #     写出 → False；supported_output_formats() 已按实际实现如实只报 csv；
    #   - 多激励 S 矩阵：官方单 run 多激励（每端口 Excitation:<Index>
    #     真跑取证全 (n,2,2) 掩码+互易 |S12−S21|=0）；
    #   - 模板：无模板机制（网格 .msh 由调用方提供）→ 空元组；
    #   - 并行：subprocess 不传 MPI 开关 → 空元组；license：Apache-2.0 → False。
    CAPABILITIES: ClassVar[SolverCapabilities] = SolverCapabilities(
        solver_type="palace",
        supports_wave_port=True,
        supports_lumped_port=True,
        supports_field_export=False,
        supports_convergence_report=False,
        supports_touchstone_export=False,
        supports_headless_solve=True,
        supports_optimetrics=False,
        dimension="3d",
        material_models=("pec", "lossless_dielectric"),
        parallel_backends=(),
        supports_sar=False,
        supports_nf2ff=False,
        supports_lumped_elements=False,
        supported_templates=(),
        requires_license=False,
        availability_gate="exe_path",
    )

    def __init__(self, config: EMSolverConfig):
        super().__init__(config)
        self._exe_path: str | None = config.exe_path
        self._config_file: Path | None = None
        self._mesh_file: str | None = None  # Model.Mesh 单源（C-LOW ②）
        self._last_measured_mask: list[tuple[int, int]] | None = None

    def connect(self) -> bool:
        exe = self._exe_path or self._find_exe()
        if exe is None or not Path(exe).exists():
            return False
        self._exe_path = exe
        self._connected = True
        return True

    def is_available(self) -> bool:
        exe = self._exe_path or self._find_exe()
        return exe is not None and Path(exe).exists()

    def _find_exe(self) -> str | None:
        return resolve_palace_exe()

    # ── 配置生成（Palace v0.18.1 官方 JSON schema 五分节）──────────────────

    def _result_csv_path(self) -> Path:
        """官方 Driven S 参数结果路径：<working_dir>/<Problem.Output>/port-S.csv。"""
        workdir = Path(self._config.working_dir or ".")
        return workdir / _PALACE_OUTPUT_DIR / _PALACE_SPARAM_CSV

    @staticmethod
    def _validate_port_excitations(ports: Mapping[str, Any]) -> str | None:
        """端口激励组校验（build 期 fail-fast；官方口径实证 df5_multiexcite_
        criteria.md §1-§2）。

        官方语义（utils/configfile.cpp ParsePortExcitation L416 + 归一化
        L1001-1055 + models/portexcitations.hpp IsMultipleSimple L134）：
        - Excitation 缺省/false→0（不激励）、true→1、非负整数→激励组索引；
        - port-S.csv 仅当每个激励组恰 1 端口（IsMultipleSimple）才产出。

        返回 None=通过；返回字符串=拒绝理由。多端口共享同一激励组 → 必拒
        （该形态 port-S.csv 必不产出，官方 run rc=0 静默——Case B 真跑
        实证，等到 solve 后报"未产出"会白烧一次完整求解）。激励组索引≠端口
        Index 且官方归一化不适用 → warning（合法但 S 列按激励组索引，不与
        端口轴对齐）。
        """
        groups: dict[int, list[tuple[str, Any]]] = {}
        for key in _PORT_BOUNDARY_KEYS:
            for port in ports.get(key) or []:
                if not isinstance(port, dict):
                    continue  # 形态错误由透传 schema 校验/官方解析报错
                val = port.get("Excitation", 0)
                if isinstance(val, bool):
                    val = int(val)  # 官方：true→1 / false→0
                if not isinstance(val, int) or val < 0:
                    return (
                        f"端口 Index={port.get('Index')!r} 的 Excitation 须为 "
                        f"bool 或非负整数（官方 ParsePortExcitation 口径），"
                        f"收到: {val!r}"
                    )
                if val:
                    groups.setdefault(val, []).append((key, port.get("Index")))
        for ex_idx, members in sorted(groups.items()):
            if len(members) > 1:
                detail = ", ".join(f"{k}#{i}" for k, i in members)
                return (
                    f"激励组 {ex_idx} 含 {len(members)} 个端口（{detail}）：官方 "
                    "IsMultipleSimple()==false，port-S.csv 必不产出（"
                    "Case B 真跑实证）；S 参数提取请为每个端口指定互异激励"
                    "索引（Excitation: <自身 Index>）"
                )
        if len(groups) > 1:
            if any(ex != member_idx
                   for ex, members in groups.items()
                   for (_member_key, member_idx) in members):
                logger.warning(
                    "激励组索引与端口 Index 不一致且官方归一化不适用"
                    "（configfile.cpp L1023 仅全 组==Index 或单组==1 时归一化）"
                    "——port-S.csv 的 S[o][e] 列将按激励组索引排列，不与端口轴"
                    "对齐；推荐每端口 Excitation: <自身 Index>"
                )
        elif groups:
            ex_idx, members = next(iter(groups.items()))
            _first_key, first_idx = members[0]
            if ex_idx != 1 and ex_idx != first_idx:
                # 单组且 ex∉{1, Index}：归一化 valid 判定不过（L1023），S 列
                # 按原始组索引错位
                logger.warning(
                    "单激励组索引 %s 与端口 Index %s 不一致且不会被官方归一化"
                    "——S[o][e] 列将按激励组索引 %s 排列；推荐 Excitation: "
                    "<自身 Index>", ex_idx, first_idx, ex_idx,
                )
        return None

    def build_geometry(self, geometry: dict[str, Any]) -> bool:
        """生成 Palace 求解配置（palace_config.json，官方五分节 schema）。

        geometry 契约:
            mesh_file: str        —— gmsh .msh 网格文件路径（必填，官方建议绝对路径）
            mesh_l0_m: float      —— 网格坐标单位（Model.L0，相对米；mm 网格传
                                     1.0e-3）。缺省不写入（官方默认 1e-6=μm），
                                     仅 warning 提示——适配器不臆测网格单位
            materials: [...]      —— 必填，官方 Domains.Materials 段透传，
                                     逐项必须含 Attributes（网格域标签绑定）
            ports: dict           —— 可选，官方 Boundaries 端口组：
                                     {"WavePort": [...], "LumpedPort": [...]}
            boundaries: dict      —— 可选，官方 Boundaries 其余子键（如 PEC）
            freq_range_ghz:       —— 来自 EMSolverConfig（官方扫频频率单位 GHz）
        """
        if not self._connected:
            return False
        mesh_file = geometry.get("mesh_file")
        if not mesh_file:
            logger.error("Palace 需要 geometry['mesh_file']（gmsh 网格），未提供")
            return False
        materials = geometry.get("materials")
        if not materials:
            logger.error(
                "Palace 需要 geometry['materials']（官方 Domains.Materials，"
                "逐项须含 Attributes 域标签绑定），未提供——适配器不造默认材料"
            )
            return False
        for mat in materials:
            if not isinstance(mat, dict) or "Attributes" not in mat:
                logger.error(
                    "Palace Domains.Materials 每项必须含官方键 'Attributes'"
                    "（网格域标签绑定），收到: %r", mat,
                )
                return False
        boundaries = dict(geometry.get("boundaries") or {})
        unknown_bnd = [k for k in boundaries if k not in OFFICIAL_BOUNDARY_KEYS]
        if unknown_bnd:
            logger.error("Palace Boundaries 含官方 schema 之外子键: %s", unknown_bnd)
            return False
        ports = geometry.get("ports") or {}
        if not isinstance(ports, dict):
            logger.error(
                "Palace geometry['ports'] 须为官方 Boundaries 端口组 dict "
                "（如 {'WavePort': [...], 'LumpedPort': [...]}），收到: %r",
                type(ports).__name__,
            )
            return False
        unknown_port = [k for k in ports if k not in _PORT_BOUNDARY_KEYS]
        if unknown_port:
            logger.error("Palace ports 含官方 Boundaries 之外子键: %s", unknown_port)
            return False
        exc_err = self._validate_port_excitations(ports)
        if exc_err:
            logger.error("%s", exc_err)
            return False
        freq = self._config.freq_range_ghz
        # 官方推荐扫频接口 Solver.Driven.Samples（线性采样，单位 GHz）；
        # 顶层直写 MinFreq/MaxFreq/FreqStep 已被官方标 Deprecated
        driven: dict[str, Any] = {
            "Samples": [{
                "Type": "Linear",
                "MinFreq": float(freq[0]),
                "MaxFreq": float(freq[1]),
                "NSample": int(self._config.max_iterations),
            }],
        }
        config: dict[str, Any] = {
            "Problem": {"Type": "Driven", "Output": _PALACE_OUTPUT_DIR},
            "Model": {"Mesh": str(mesh_file)},
            "Domains": {"Materials": list(materials)},
            "Boundaries": {**boundaries, **ports},
            "Solver": {"Driven": driven},
        }
        mesh_l0_m = geometry.get("mesh_l0_m")
        if mesh_l0_m is not None:
            config["Model"]["L0"] = float(mesh_l0_m)
        else:
            logger.warning(
                "geometry['mesh_l0_m'] 未提供：Model.L0 按官方默认 1e-6（μm）"
                "缺省——mm 网格须显式传 1.0e-3，否则坐标尺度错 1000 倍"
            )
        cfg_path = Path(self._config.working_dir or ".") / _PALACE_CONFIG_FILENAME
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
        self._config_file = cfg_path
        self._mesh_file = str(mesh_file)  # Model.Mesh 单源，visualizations 同源
        return True

    @staticmethod
    def _clean_proc_text(text: str) -> str:
        """wsl.exe 管道输出是 UTF-16LE（#271 家族）：text=True 按 locale 解码
        后 ASCII 文本呈 ``a\\x00b\\x00`` 形态——剥 NUL 即恢复可读（best-effort，
        #105：观测清洗不阻塞主路径）。"""
        if text and "\x00" in text:
            return text.replace("\x00", "")
        return text

    def solve(self, timeout_s: int = 3600) -> EMSolverResult:
        """Run Palace via subprocess; parse <Output>/port-S.csv → S 参数。

        官方 CLI（docs/src/run.md）：配置文件是位置参数 CONFIG_FILE，
        不存在 -config 旗标。命令面保持 `[exe, config绝对路径]` 两元——
        exe 可为原生二进制（Linux/WSL 内直接跑）或 Windows 侧 WSL wrapper
        （palace.cmd 自行完成路径转换与 lib 环境），本方法不感知通道差异。
        工作目录契约：wrapper 经 wsl.exe cwd 继承映射，Palace 相对 Output
        目录落回同一 Windows 工作目录，_result_csv_path() 无需改动。
        """
        if not self._connected:
            return EMSolverResult(success=False, message="Not connected")
        if self._config_file is None:
            return EMSolverResult(success=False,
                                  message="build_geometry() 未生成求解配置")
        cmd = [str(self._exe_path), str(self._config_file.resolve())]
        workdir = self._config.working_dir or "."
        # 失败清掩码（round6 A3-③，#316 方向=多报不放过）：新一次 solve
        # 起跑即作废上一轮掩码——超时/启动失败/非零退出/结果缺失/解析失败
        # 任一路径下 get_measured_mask() 都不得把上一轮的掩码当本轮的
        # （陈旧掩码+零填 S 矩阵正是 #314 掩码口径要拦的组合）
        self._last_measured_mask = None
        t0 = time.time()
        try:
            proc = subprocess.run(
                cmd, cwd=workdir, capture_output=True, text=True,
                timeout=timeout_s, check=False,
            )
        except subprocess.TimeoutExpired:
            return EMSolverResult(success=False, message=f"Palace 超时（>{timeout_s}s）")
        except OSError as e:
            return EMSolverResult(success=False, message=f"Palace 启动失败: {e}")
        wall = time.time() - t0
        if proc.returncode != 0:
            stderr_tail = self._clean_proc_text(proc.stderr)[-400:]
            return EMSolverResult(success=False, wall_time_s=round(wall, 1),
                                  message=f"Palace 退出码 {proc.returncode}: {stderr_tail}")
        result_csv = self._result_csv_path()
        if not result_csv.exists():
            return EMSolverResult(success=False, wall_time_s=round(wall, 1),
                                  message=f"Palace 未产出 {result_csv}"
                                          "（官方 Driven S 参数文件；核对端口配置）")
        try:
            freq_ghz, s, measured = self._parse_palace_csv_masked(result_csv)
        except Exception as e:
            return EMSolverResult(success=False, wall_time_s=round(wall, 1),
                                  message=f"{_PALACE_SPARAM_CSV} 解析失败: {e}")
        self._last_measured_mask = list(measured)
        return EMSolverResult(
            success=True, freq_ghz=freq_ghz, s_params=s,
            wall_time_s=round(wall, 1),
            message=(f"Palace solve ok; port-S.csv 已测条目(1-based (o,e))={measured}"
                     "；未测条目为零填占位，判据不得当测量值"),
        )

    @staticmethod
    def _parse_palace_csv_masked(path: Path) -> tuple[Any, Any, list[tuple[int, int]]]:
        """解析官方 port-S.csv（v0.18.1 postoperatorcsv.cpp 口径）→ (freq, S, 掩码)。

        列：``idx``, ``f (GHz)``，随后逐激励 e × 逐端口 o 交替
        ``|S[o][e]| (dB)`` / ``arg(S[o][e]) (deg.)``。频率列直读 GHz；
        dB/度 → 线性复数；按列标签回填 s[:, o-1, e-1]（端口索引 1-based）。
        单激励 run 仅激励列有测量值——未测条目零填（诚实占位），已测
        清单随第三返回值给出，下游判据不得把零填当测量值（#314 掩码口径）。
        """
        import numpy as np

        with open(path, encoding="utf-8") as f:
            rows = list(csv.reader(f))
        if len(rows) < 2:
            raise ValueError("结果为空")
        header = [h.strip() for h in rows[0]]
        freq_col = next((i for i, h in enumerate(header)
                         if h.lower().startswith("f (ghz)") or h.lower() == "f"), None)
        if freq_col is None:
            raise ValueError(f"未找到频率列 f (GHz)，表头: {header[:8]}")
        # S 列对：(o, e) → (dB 列号, 相位列号)
        db_cols: dict[tuple[int, int], int] = {}
        arg_cols: dict[tuple[int, int], int] = {}
        for i, h in enumerate(header):
            if i == freq_col:
                continue
            m = _S_PARAM_COL_RE.search(h)
            if not m:
                continue
            o, e = int(m.group(1)), int(m.group(2))
            hl = h.lower()
            if "(db)" in hl:
                db_cols[(o, e)] = i
            elif "deg" in hl:
                arg_cols[(o, e)] = i
        measured = sorted(set(db_cols) & set(arg_cols))
        if not measured:
            raise ValueError(f"未找到 |S[o][e]| (dB)/arg(S[o][e]) (deg.) 列对，表头: {header[:8]}")
        n_ports = max(max(o for o, _ in measured), max(e for _, e in measured))
        freqs: list[float] = []
        s_rows: list[list[complex]] = []
        for r in rows[1:]:
            if not r or not r[freq_col].strip():
                continue
            freqs.append(float(r[freq_col]))
            row = [0j] * (n_ports * n_ports)
            for (o, e) in measured:
                db = float(r[db_cols[(o, e)]])
                deg = float(r[arg_cols[(o, e)]])
                mag = 10.0 ** (db / 20.0)
                row[(o - 1) * n_ports + (e - 1)] = mag * np.exp(1j * np.radians(deg))
            s_rows.append(row)
        n = len(freqs)
        freq_ghz = np.array(freqs)  # 官方频率列已是 GHz，不再换算
        s = np.array(s_rows, dtype=complex).reshape(n, n_ports, n_ports)
        return freq_ghz, s, measured

    @classmethod
    def _parse_palace_csv(cls, path: Path) -> tuple[Any, Any]:
        """兼容薄包装（#315 口径）：旧 2 元组签名，不含测量掩码。"""
        freq_ghz, s, _measured = cls._parse_palace_csv_masked(path)
        return freq_ghz, s

    def get_sparams(self) -> Any:
        """读取最近一次 solve 的结果文件（<Output>/port-S.csv）。"""
        result = self._result_csv_path()
        if not result.exists():
            return None
        return self._parse_palace_csv(result)

    def get_measured_mask(self) -> list[tuple[int, int]] | None:
        """最近一次 solve 的已测 (o, e) 条目清单（1-based；#314 掩码口径）。

        未 solve 过或最近一次解析失败 → None。port-S.csv 未覆盖的条目在
        s_params 中为零填占位（如单激励 run 的非激励列、显式激励组索引
        错位时的空档），下游判据不得把零填当测量值——消费掩码清单判读。
        """
        if not self._last_measured_mask:
            return None
        return list(self._last_measured_mask)

    def close(self) -> None:
        self._connected = False

    # ── 6g 产物视图协议 ─────────────────────────────────────────────────────

    def visualizations(self) -> list[dict[str, Any]]:
        workdir = self._config.working_dir or "."
        # Model.Mesh 单源（C-LOW ②）：mesh_file 只来自 build_geometry 的
        # geometry["mesh_file"]（即写进 config Model.Mesh 的同一值），
        # 不再读 extra_params 第二源；build 前调用返回空串。
        mesh = self._mesh_file or ""
        return [
            {"kind": "model3d", "spec": {"mesh_file": mesh, "format": "gmsh"}},
            {"kind": "sparams",
             "spec": {"file": str(Path(workdir) / _PALACE_OUTPUT_DIR / _PALACE_SPARAM_CSV)}},
        ]

    def supported_output_formats(self) -> list[str]:
        # 实际产物仅 CSV（官方 port-S.csv 解析链）；无 Touchstone 写出——
        # 6g 遗留缺省声明已按实现如实修正（C-LOW ③，消费者
        # r3_services.list_solver_visualizations 透出 output_formats）。
        return ["csv"]


# 注册到全局注册表（与 openems_solver 同模式：模块导入即注册）
def register_palace() -> None:
    """注册 Palace 求解器到全局注册表。"""
    from rfauto.adapters.em_solver_base import EMSolverType, get_global_registry
    registry = get_global_registry()
    registry.register(EMSolverType.PALACE, PalaceSolver)


"""Register on import (same pattern as openems_solver; never blocks import)."""
with contextlib.suppress(Exception):
    register_palace()
