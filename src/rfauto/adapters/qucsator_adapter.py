"""N7 qucsatorRF 电路级适配器（DP-14 §14.2；开源电路仿真器通道）。

定位：EMSolverRegistry 的**电路级**通道（qucs-S 项目的 qucsator_rf，
GPL）——与 openEMS/Meep（全波 FDTD）互补：微带传输线类结构在电路级
按准静态+色散闭式模型求解，秒级零网格，适合名义点快速对照与采样扩容。

**部署口径（本机真机可用）**：Qucs-S 26.1.1 win64 便携包
（ra3xdh/qucs_s release，sha256 80025a24…b3ef1c 实测对上）自带
``bin/qucsator_rf.exe``（版本串 Qucsator 1.0.7 fork；模拟器源码为
qucs_s 的 git submodule ra3xdh/qucsator_rf）。安装位置 E 盘
（工作区工具链落盘约定）：``E:\\tools\\qucsatorRF\\bin``。

可执行解析链（同 spice_netlist.resolve_ngspice_exe 口径）：显式参数 →
env ``RFAUTO_QUCSATOR_BIN``（exe 或目录）→ configs/solvers.yaml
``qucsator`` 条目 exe_path → 工作区 ``tools/qucsatorRF/bin`` → PATH。
全落空抛 FileNotFoundError（锚是裁判，不静默降级）。

网表语法标定（2026-09-24 对照 qucsator_rf-develop 源码 + 本机真跑；
#215 纪律：不凭想象写 API）：
- **动作行必须带点前缀**（parse_netlist.ypp ActionLine 语法）：
  ``.SP:SP1 Type="lin" Start=... Stop=... Points=...``——不带点被解析成
  组件行，报 "invalid definition type `SP'"；
- 基板组件定义名是 ``SUBST``（非经典 qucs 的 ``Subst``、非 qucs-S GUI
  的 MSUB 名）：属性 er/h/t/tand/rho/D；**rho 为 SI Ω·m**（铜
  2.2e-8）——误用 Ω·mm²/m 口径（0.022）会让导体损耗模型爆掉
  （|S21|→4e-4）并触发其单位混写的 skin-depth WARNING；D=导体表面
  粗糙度（m）；
- MLIN：W/L/Subst/Model(缺省 Hammerstad 准静态)/DispModel(缺省
  Kirschning 色散)；物理链（msline.cpp calcPropagation）= 准静态
  ZlEff/ErEff → 色散修正 → 损耗 → β=√εeff(f)·2πf/c0；
- **SP 分析必须有显式 Pac 端口**（缺 Pac 报 "0 `Pac' definitions
  found, at least 1 required"）：``Pac:P1 _net0 gnd Num=1 Z=50 f=...``；
- 产物 dataset：``<Qucs Dataset ...>`` + ``<indep frequency N>`` +
  ``<dep S[i,j] frequency>`` 块；复数单 token ``re±jim``、纯实数单
  token（解析器两者都收）；
- 确定性：同网表两次运行 dataset **逐字节相同**（真机实测，本模块
  判据 4b 即按逐位口径）。

诚实边界（KJ vs HJ 口径差，#122 如实）：
- qucsator MLIN = 准静态（Hammerstad 系）+ **Kirschning-Jansen 频率
  色散**；skrf HJ（core.synthesis.forward_z0，openEMS 线宽综合同源）
  为纯准静态、无色散项。qucsator vs HJ 之差含**物理口径差**（色散项），
  非适配器 bug——三方对照时 per-pair 互差如实分账报告；
- 经典 qucs 的 MSTEP/MTEE 等不连续性 v1 不承诺（见
  NOT_SUPPORTED_ELEMENTS）；模板面 v1 仅 mline 锚（见 SUPPORTED_TEMPLATES）。

β 三方对照：泛化内核 :func:`compare_beta_triad`（腿名参数化；判定数学
与 meep_adapter.compare_beta_three_way 同款 sym-rel-diff + tol 门），
HJ 腿直接复用 meep_adapter.hj_beta_series（单一事实来源）。

分层：adapters，import core.synthesis 与同层 meep_adapter（HJ 腿内核）；
供 service.qucsator_service 编排调用。
"""

from __future__ import annotations

import contextlib
import csv
import itertools
import logging
import math
import os
import re
import shutil
import subprocess
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, ClassVar

import numpy as np

from rfauto.adapters.em_solver_base import (
    EMSolverAdapter,
    EMSolverConfig,
    EMSolverResult,
    SolverCapabilities,
)
from rfauto.core.synthesis import Stackup

logger = logging.getLogger(__name__)

_C0_M_S = 299792458.0

#: 工作区随带 qucsatorRF 的缺省位置（工具链落 E 盘工作区的仓内约定）。
_WORKSPACE_QUCSATOR = Path(__file__).resolve().parents[3] / "tools" / "qucsatorRF" / "bin"

#: N7 安装探测落点（E:\qucsatorRF 或 E:\tools\qucsatorRF；
#: 字面量兜底先例同 resolve_openems_exe 的 E:\openEMS 字面量）。
_DRIVE_INSTALL_QUCSATOR = (Path("E:/tools/qucsatorRF/bin"), Path("E:/qucsatorRF/bin"))

_QUCSATOR_EXE_CANDIDATES = ("qucsator_rf.exe", "qucsator_rf", "qucsatorRF.exe", "qucsatorRF")

#: v1 支持的模板（与 MeepSolver.supported_templates 同口径，如实不虚报）。
SUPPORTED_TEMPLATES: tuple[str, ...] = ("mline",)

#: v1 **不承诺**的微带族元件（网表渲染未覆盖，显式拒绝不静默）。
#: qucsatorRF 实际还有 MLCROS/MSTEER 等更多——此处列 v1 明确被请求即拒的
#: 常用族；未列出的任意模板/元件同样走模板名白名单拒绝。
NOT_SUPPORTED_ELEMENTS: tuple[str, ...] = (
    "MSTEP", "MTEE", "MCROS", "MCORN", "MBEND", "MBEND2", "MSLANT", "MSPIRAL",
    "MCOUPLED", "MCLIN", "MLANG", "MGAP", "MOPEN", "MRSTUB", "MLSC", "ML2S",
    "MLAYV", "MVIA", "MLIN2", "SIR", "MCFOLD", "MSUBST",
)

#: mline 锚 openEMS 金锚 β（rad/m）——runs/benchmark/mline_mauto/port_beta.csv
#: （W=1.113mm、auto 网格、2.25–2.75GHz、#162 β 金标准 schema）冻结值；
#: 与 tests/unit/test_meep_adapter.py::_OPENEMS_GOLDEN 同源（测试互检防漂移）。
_OPENEMS_GOLDEN_MLINE = {2.25: 80.55376868947421, 2.5: 89.50940246779182,
                         2.75: 98.45637105318495}


def openems_golden_beta_mline() -> dict[float, float]:
    """openEMS mline 金锚 β 冻结值（GHz → rad/m；runs/ 只读引用，零仿真）。"""
    return dict(_OPENEMS_GOLDEN_MLINE)


# --------------------------------------------------------------------------- #
# 可执行文件解析（spice_netlist.resolve_ngspice_exe 同构）
# --------------------------------------------------------------------------- #

def _exe_from_dir(directory: Path) -> Path | None:
    for name in _QUCSATOR_EXE_CANDIDATES:
        cand = directory / name
        if cand.is_file():
            return cand
    return None


def _exe_from_solvers_yaml() -> Path | None:
    """configs/solvers.yaml 的 ``qucsator`` 条目 exe_path（settings 面次之）。"""
    try:
        from rfauto.adapters.em_solver_base import load_solvers_config
        cfg = load_solvers_config().get("qucsator")
    except Exception:  # best-effort：配置面缺失不影响 env/工作区/PATH 链（#105）
        return None
    if cfg and cfg.exe_path:
        return Path(cfg.exe_path)
    return None


def resolve_qucsator_exe(explicit: str | Path | None = None) -> Path:
    """解析 qucsatorRF 可执行：显式参数 → ``RFAUTO_QUCSATOR_BIN``（exe 或
    目录）→ configs/solvers.yaml ``qucsator`` 条目 → 工作区
    ``tools/qucsatorRF/bin`` → PATH。

    全部落空抛 FileNotFoundError（附配置指引；锚是裁判，不静默降级）。
    """
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(Path(explicit))
    env = os.environ.get("RFAUTO_QUCSATOR_BIN", "")
    if env:
        candidates.append(Path(env))
    yaml_exe = _exe_from_solvers_yaml()
    if yaml_exe is not None:
        candidates.append(yaml_exe)
    candidates.append(_WORKSPACE_QUCSATOR)
    candidates.extend(_DRIVE_INSTALL_QUCSATOR)
    for cand in candidates:
        if cand.is_dir():
            exe = _exe_from_dir(cand)
            if exe is not None:
                return exe
        elif cand.is_file():
            return cand
    for name in _QUCSATOR_EXE_CANDIDATES:
        found = shutil.which(name)
        if found:
            return Path(found)
    raise FileNotFoundError(
        "未找到 qucsatorRF 可执行文件；可设 RFAUTO_QUCSATOR_BIN 指向 qucsator_rf.exe "
        "或其所在目录（工作区随带: tools/qucsatorRF/bin，Qucs-S 26.1.1 便携包）"
    )


def qucsator_available(explicit: str | Path | None = None) -> bool:
    """qucsatorRF 是否可用（best-effort，永不抛错——观测性 #105 纪律）。"""
    try:
        return resolve_qucsator_exe(explicit).is_file()
    except Exception:
        return False


def qucsator_version(exe: str | Path | None = None) -> str | None:
    """qucsatorRF 版本串（best-effort；缺省无版本输出时如实 None）。"""
    try:
        exe_path = resolve_qucsator_exe(exe)
        proc = subprocess.run(
            [str(exe_path), "-v"], capture_output=True, text=True, timeout=30.0, check=False
        )
    except Exception:
        return None
    m = re.search(r"Qucsator\s+\S+", proc.stdout + proc.stderr)
    return m.group(0) if m else None


# --------------------------------------------------------------------------- #
# 网表渲染（纯函数；MSUB(=SUBST 定义名)+MLIN+Pac+.SP，语法见模块 docstring 标定）
# --------------------------------------------------------------------------- #

def _num(value: float) -> str:
    """SI 纯指数字面量（qucsatorRF 对裸 SI 数值解析无歧义，规避单位后缀风险）。"""
    v = float(value)
    if v == 0.0:
        v = 0.0  # 归一 −0.0
    return f"{v:.17g}"


def render_mline_netlist(
    w_mm: float,
    line_len_mm: float,
    stackup: Stackup,
    freqs_hz: list[float],
    *,
    z0_ref: float = 50.0,
    title: str = "rfauto N7 qucsatorRF mline anchor",
) -> str:
    """渲染 mline 锚 qucsatorRF 网表（纯字符串，不落盘不执行）。

    结构（语法标定见模块 docstring）：SUBST 基板 → MLIN 线体
    （Hammerstad 准静态 + Kirschning 色散）→ 两只 Pac 端口（SP 分析
    必需）→ ``.SP`` 线性频扫。数值一律 SI 纯指数（_num）；字符串属性
    （Subst/Model/DispModel/Type）带引号。

    Args:
        w_mm: 线宽（mm）。
        line_len_mm: 线长（mm）。
        stackup: 层叠（er/h/tand/rho 进 SUBST；t 定金属厚 35um）。
        freqs_hz: 严格递增频点（Hz），≥2 点；SP 网格 = linspace(首, 末, N)。
        z0_ref: 端口参考阻抗（Ω，缺省 50）。
        title: 网表首行注释。

    Returns:
        网表文本。
    """
    if w_mm <= 0:
        raise ValueError(f"线宽必须为正（mm）: {w_mm}")
    if line_len_mm <= 0:
        raise ValueError(f"线长必须为正（mm）: {line_len_mm}")
    if not 1.0 < float(stackup.epsilon_r) <= 100.0:
        raise ValueError(f"er 必须在 (1, 100]（qucsatorRF SUBST 值域）: {stackup.epsilon_r}")
    if stackup.thickness_mm <= 0:
        raise ValueError(f"基板厚必须为正（mm）: {stackup.thickness_mm}")
    if stackup.loss_tangent < 0:
        raise ValueError(f"损耗正切必须非负: {stackup.loss_tangent}")
    if stackup.rho <= 0:
        raise ValueError(f"金属电阻率必须为正（SI Ω·m）: {stackup.rho}")
    freqs = [float(f) for f in freqs_hz]
    if len(freqs) < 2:
        raise ValueError("至少 2 个频点")
    if any(f <= 0 for f in freqs):
        raise ValueError(f"频点必须为正（Hz）: {freqs[:5]}")
    if any(b <= a for a, b in itertools.pairwise(freqs)):
        raise ValueError(f"频点网格须严格递增: {freqs[:5]}")
    f_center = 0.5 * (freqs[0] + freqs[-1])
    metal_t_m = 3.5e-5  # 35um 铜箔标称（qucs 惯例缺省；SUBST.t）
    lines = [
        f"# {title}",
        f"# nominal: er={stackup.epsilon_r} h_mm={stackup.thickness_mm} "
        f"tand={stackup.loss_tangent} rho={stackup.rho} t_m={metal_t_m} "
        f"w_mm={w_mm} l_mm={line_len_mm} (quasi-static: Hammerstad, dispersion: Kirschning)",
        f"SUBST:SUB1 er={_num(stackup.epsilon_r)} h={_num(stackup.thickness_mm * 1e-3)} "
        f"t={_num(metal_t_m)} tand={_num(stackup.loss_tangent)} "
        f"rho={_num(stackup.rho)} D=0",
        f"MLIN:MLIN1 _net0 _net1 W={_num(w_mm * 1e-3)} L={_num(line_len_mm * 1e-3)} "
        f'Subst="SUB1" Model="Hammerstad" DispModel="Kirschning"',
        f"Pac:P1 _net0 gnd Num=1 Z={_num(z0_ref)} f={_num(f_center)}",
        f"Pac:P2 _net1 gnd Num=2 Z={_num(z0_ref)} f={_num(f_center)}",
        f'.SP:SP1 Type="lin" Start={_num(freqs[0])} Stop={_num(freqs[-1])} '
        f"Points={len(freqs)}",
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# dataset 解析（<Qucs Dataset> 格式；标定见模块 docstring）
# --------------------------------------------------------------------------- #

_CPLX_TOKEN_RE = re.compile(r"^([+-]?[0-9.eE+-]+)([+-])j([0-9.eE+-]+)$")
_REAL_TOKEN_RE = re.compile(r"^[+-]?[0-9.eE+-]+$")
_INDEP_RE = re.compile(r"^<indep\s+(\S+)\s+(\d+)>")
_DEP_RE = re.compile(r"^<dep\s+(\S+)\s+(\S+)")


def _parse_dataset_token(tok: str) -> complex:
    m = _CPLX_TOKEN_RE.match(tok)
    if m:
        im_sign = 1.0 if m.group(2) == "+" else -1.0
        return complex(float(m.group(1)), im_sign * float(m.group(3)))
    if _REAL_TOKEN_RE.match(tok):
        return complex(float(tok), 0.0)
    raise QucsatorError(f"dataset 含无法解析的数值令牌: {tok!r}")


class QucsatorError(RuntimeError):
    """qucsatorRF 通道执行失败（渲染/运行/解析任一环节，显式不静默）。"""


def parse_qucs_dataset(text: str) -> dict[str, Any]:
    """解析 qucsatorRF dataset 文本 → ``{"freq_hz": [nf], "S": {(i,j): [nf]}}``。

    格式（2026-09-24 真机标定）：``<indep frequency N>`` 块给出频轴（纯实
    数 token，每行可多个）；随后每块 ``<dep S[i,j] frequency>`` 给出复数
    token（``re±jim`` 单 token）或纯实数 token，块内值数必须等于频点数
    （不一致=文件损坏，显式报错不静默）。
    """
    freqs: list[float] = []
    s: dict[tuple[int, int], list[complex]] = {}
    cur_indep: str | None = None
    cur_dep: tuple[int, int] | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("<indep"):
            m = _INDEP_RE.match(line)
            if not m:
                raise QucsatorError(f"indep 块头无法解析: {line!r}")
            cur_indep, cur_dep = m.group(1), None
            continue
        if line.startswith("<dep"):
            m = _DEP_RE.match(line)
            if not m:
                raise QucsatorError(f"dep 块头无法解析: {line!r}")
            name = m.group(1)
            mm = re.match(r"^S\[(\d+),(\d+)\]$", name)
            if mm is None:
                cur_dep = None  # 非 S 变量（V/I 等）读面暂不收，跳过块体
            else:
                cur_dep = (int(mm.group(1)), int(mm.group(2)))
                s.setdefault(cur_dep, [])
            continue
        if line.startswith("</"):
            cur_indep, cur_dep = None, None
            continue
        toks = line.split()
        if cur_indep is not None:
            for tok in toks:
                freqs.append(float(_parse_dataset_token(tok).real))
        elif cur_dep is not None:
            s[cur_dep].extend(_parse_dataset_token(tok) for tok in toks)
    n = len(freqs)
    if n == 0:
        raise QucsatorError("dataset 无频点（qucsator 未产出数据或被 error 中断）")
    for key, vals in s.items():
        if len(vals) != n:
            raise QucsatorError(
                f"S[{key[0]},{key[1]}] 值数 {len(vals)} != 频点数 {n}（dataset 损坏）"
            )
    return {
        "freq_hz": np.array(freqs, dtype=float),
        "S": {k: np.array(v, dtype=complex) for k, v in s.items()},
    }


def read_qucs_dataset(path: str | Path) -> dict[str, Any]:
    """读取 dataset 文件并解析（:func:`parse_qucs_dataset` 的文件入口）。"""
    return parse_qucs_dataset(Path(path).read_text(encoding="utf-8", errors="replace"))


# --------------------------------------------------------------------------- #
# β 提取与三方对照确定性内核
# --------------------------------------------------------------------------- #

def beta_from_s21(
    freq_hz: np.ndarray,
    s21: np.ndarray,
    line_len_m: float,
    *,
    beta_branch_ref_ghz: np.ndarray | list[float] | None = None,
) -> np.ndarray:
    """从 S21 相位提取传播常数 β（rad/m）：β = −unwrap(∠S21)/L。

    相位分支选择：unwrap 后的相位可能整体差 2π·k（|βL|>π 时首点被卷绕）
    ——以 ``beta_branch_ref_ghz``（HJ 闭式 β 预估，GHz 网格对齐）在带中点
    定 k，把 β 平移回物理分支。参照只选分支，不参与数值：平移后的 β 全部
    来自 qucsator 相位。S21 含零点/非有限值时 ValueError（不静默）。
    """
    freq_hz = np.asarray(freq_hz, dtype=float)
    s21 = np.asarray(s21, dtype=complex)
    if line_len_m <= 0:
        raise ValueError(f"线长必须为正（m）: {line_len_m}")
    if freq_hz.shape != s21.shape or freq_hz.size == 0:
        raise ValueError(f"频点/S21 形状不一致或为空: {freq_hz.shape} vs {s21.shape}")
    if not np.all(np.isfinite(s21)) or np.any(np.abs(s21) == 0.0):
        raise ValueError("S21 含非有限值或零点（相位无定义），显式拒绝")
    phi = np.unwrap(np.angle(s21))
    beta_raw = -phi / float(line_len_m)
    if beta_branch_ref_ghz is not None:
        ref = np.asarray(beta_branch_ref_ghz, dtype=float)
        if ref.shape != beta_raw.shape:
            raise ValueError(f"分支参照 β 网格长度 {ref.size} != 频点数 {beta_raw.size}")
        mid = beta_raw.size // 2
        k = round((float(ref[mid]) - float(beta_raw[mid])) * float(line_len_m)
                  / (2.0 * math.pi))
        beta_raw = beta_raw + 2.0 * math.pi * k / float(line_len_m)
    return beta_raw


def _sym_rel_diff(a: float, b: float) -> float:
    """对称相对差 |a−b| / mean(|a|,|b|)（meep_adapter 同款"互差"口径）。"""
    denom = (abs(a) + abs(b)) / 2.0
    if denom == 0.0:
        return 0.0
    return abs(a - b) / denom


class BetaTriadReport:
    """β 互差判定结果（腿名参数化；与 meep 版字段同构）。"""

    def __init__(self, *, n_freq: int, tol_rel: float, max_pairwise_rel: float,
                 per_pair_max_rel: dict[str, float], worst_freq_ghz: float,
                 culprit_pair: str, passed: bool):
        self.n_freq = n_freq
        self.tol_rel = tol_rel
        self.max_pairwise_rel = max_pairwise_rel
        self.per_pair_max_rel = dict(per_pair_max_rel)
        self.worst_freq_ghz = worst_freq_ghz
        self.culprit_pair = culprit_pair
        self.passed = passed

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_freq": self.n_freq,
            "tol_rel": self.tol_rel,
            "max_pairwise_rel": self.max_pairwise_rel,
            "per_pair_max_rel": dict(self.per_pair_max_rel),
            "worst_freq_ghz": self.worst_freq_ghz,
            "culprit_pair": self.culprit_pair,
            "passed": self.passed,
        }

    def __repr__(self) -> str:  # pragma: no cover —— 诊断便利
        return (f"BetaTriadReport(passed={self.passed}, "
                f"max_pairwise_rel={self.max_pairwise_rel:.4f}, "
                f"culprit={self.culprit_pair})")


def compare_beta_triad(
    freq_ghz: np.ndarray | list[float],
    legs: dict[str, np.ndarray | list[float]],
    *,
    tol_rel: float = 0.05,
) -> BetaTriadReport:
    """β 多腿互差判定（泛化确定性内核；A1/N7 同判据：互差 ≤ tol_rel）。

    与 meep_adapter.compare_beta_three_way 同判定数学（sym rel diff、
    全频点取最大、culprit 对报告），但腿名参数化——qucsator 腿不必伪装
    成 "meep"。腿数 ≥2；所有腿同网格等长、全有限、β>0（物理传播常数），
    违者 ValueError（静默吞掉等于假绿）。
    """
    if len(legs) < 2:
        raise ValueError(f"至少 2 条腿，收到 {len(legs)}")
    freq = np.asarray(freq_ghz, dtype=float)
    arrays = {name: np.asarray(v, dtype=float) for name, v in legs.items()}
    n = len(freq)
    for name, arr in arrays.items():
        if arr.shape != freq.shape:
            raise ValueError(f"腿 {name} 长度 {arr.size} != 频点数 {n}")
    if n == 0:
        raise ValueError("空频点网格")
    for name, arr in arrays.items():
        if not np.all(np.isfinite(arr)):
            raise ValueError(f"腿 {name} 含 NaN/Inf")
        if np.any(arr <= 0):
            raise ValueError(f"腿 {name} 含非正值（β 必须为正）")
    names = list(arrays)
    pairs = [(names[i], names[j]) for i in range(len(names)) for j in range(i + 1, len(names))]
    per_pair: dict[str, float] = {}
    worst_pair = ""
    worst_val = -1.0
    worst_freq = 0.0
    for a, b in pairs:
        diffs = np.array([_sym_rel_diff(float(x), float(y))
                          for x, y in zip(arrays[a], arrays[b], strict=True)])
        i = int(np.argmax(diffs))
        per_pair[f"{a}-{b}"] = float(diffs[i])
        if diffs[i] > worst_val:
            worst_val = float(diffs[i])
            worst_pair = f"{a}-{b}"
            worst_freq = float(freq[i])
    return BetaTriadReport(
        n_freq=n,
        tol_rel=float(tol_rel),
        max_pairwise_rel=worst_val,
        per_pair_max_rel=per_pair,
        worst_freq_ghz=worst_freq,
        culprit_pair=worst_pair,
        passed=worst_val <= float(tol_rel),
    )


# ─── 适配器 ──────────────────────────────────────────────────────────────────

_NETLIST_NAME = "qucsator_mline.net"
_DATASET_NAME = "qucsator_dataset.dat"
_SPARAMS_CSV_NAME = "qucsator_sparams.csv"
_BETA_CSV_NAME = "qucsator_port_beta.csv"
_TOUCHSTONE_NAME = "qucsator_mline.s2p"

_SPARAMS_CSV_HEADER = ("freq_hz", "re_S11", "im_S11", "re_S21", "im_S21")
_BETA_CSV_HEADER = ("freq_hz", "beta_rad_per_m")


class QucsatorAdapter(EMSolverAdapter):
    """qucsatorRF 电路级适配器（子进程批处理 + dataset 解析，spice_netlist 同构）。

    solve() 链：渲染网表（build_geometry 已落盘）→ ``qucsator_rf -i
    netlist -o dataset`` 单次子进程 → dataset 解析 → 全 2×2 S 矩阵 +
    β（S21 相位，HJ 定分支）→ 同构产物落盘（openEMS #162 schema 的
    sparams/port_beta CSV + skrf Touchstone .s2p）。
    """

    # A5 能力声明（如实，2026-09-24 逐条核对；电路级通道不虚报 EM 面）：
    #   - 端口：Pac 电路端口，非 EM 波端口/集总端口边界 → wave/lumped=False；
    #   - 材料：SUBST er+tand（无耗/有耗介质）；金属以 rho 电阻率建模（非
    #     PEC 边界）→ 不声明 pec；
    #   - Touchstone：solve 落盘 .s2p（skrf）→ True；
    #   - 场导出/收敛报告/optimetrics/nf2ff/SAR：电路级无对应实现 → False；
    #   - dimension："circuit"（电路级，非 2d/3d 场求解）；
    #   - 模板：v1 仅 mline 锚 → ("mline",)；license：GPL 开源 → False。
    CAPABILITIES: ClassVar[SolverCapabilities] = SolverCapabilities(
        solver_type="qucsator",
        supports_wave_port=False,
        supports_lumped_port=False,
        supports_field_export=False,
        supports_convergence_report=False,
        supports_touchstone_export=True,
        supports_headless_solve=True,
        supports_optimetrics=False,
        dimension="circuit",
        material_models=("lossless_dielectric", "lossy_dielectric"),
        parallel_backends=(),
        supports_sar=False,
        supports_nf2ff=False,
        supports_lumped_elements=False,
        supported_templates=SUPPORTED_TEMPLATES,
        requires_license=False,
        availability_gate="exe_path",
    )

    def __init__(self, config: EMSolverConfig):
        super().__init__(config)
        self._exe_path: str | None = config.exe_path
        self._netlist_path: Path | None = None
        self._geometry: dict[str, Any] = {}
        self._last_error: str | None = None

    # ── 生命周期 ────────────────────────────────────────────────────────────

    def connect(self) -> bool:
        try:
            exe = self._exe_path or resolve_qucsator_exe()
        except FileNotFoundError:
            return False
        if not Path(exe).is_file():
            return False
        self._exe_path = str(exe)
        self._connected = True
        return True

    def is_available(self) -> bool:
        try:
            exe = self._exe_path or resolve_qucsator_exe()
        except FileNotFoundError:
            return False
        return Path(exe).is_file()

    # ── 配置生成 ────────────────────────────────────────────────────────────

    def build_geometry(self, geometry: dict[str, Any]) -> bool:
        """渲染 mline 锚网表到 working_dir/qucsator_mline.net。

        geometry 契约（v1 仅 mline 锚 2 端口）:
            template: "mline"           —— 其他值显式 NOT_SUPPORTED（返回
                                           False 且 message 带标记，不静默）
            params: {w_mm, line_len_mm} —— 可选，缺省取 openEMS 模板锚同源默认
            stackup: {epsilon_r, thickness_mm, loss_tangent, name} —— 可选
            freqs_ghz: [f1, ...]        —— 可选显频点（与 openEMS 网格对齐），
                                           缺省 freq_range_ghz 均匀 n_freq 点
            n_freq: int                 —— 可选（默认 41；≥2）
            z0_ref: float               —— 可选端口参考阻抗（默认 50）
        """
        if not self._connected:
            return False
        template = str(geometry.get("template", "mline"))
        if template not in SUPPORTED_TEMPLATES:
            self._last_error = (
                f"NOT_SUPPORTED: qucsatorRF v1 仅支持 {SUPPORTED_TEMPLATES} 模板，"
                f"收到 {template!r}（微带不连续性族 {NOT_SUPPORTED_ELEMENTS[:8]}… 等 "
                "v1 不承诺，见适配器 docstring）"
            )
            logger.error("%s", self._last_error)
            return False
        try:
            from rfauto.adapters.meep_adapter import mline_anchor_defaults
            defaults = mline_anchor_defaults()
        except Exception:  # pragma: no cover —— meep 侧缺省表不可得时字面量兜底
            defaults = {"w_mm": 1.113, "line_len_mm": 40.0}
        params = dict(geometry.get("params") or {})
        w_mm = float(params.get("w_mm", defaults["w_mm"]))
        line_len_mm = float(params.get("line_len_mm", defaults["line_len_mm"]))
        if w_mm <= 0 or line_len_mm <= 0:
            self._last_error = f"mline 几何参数必须为正: w_mm={w_mm} line_len_mm={line_len_mm}"
            logger.error("%s", self._last_error)
            return False
        st_in = geometry.get("stackup") or {}
        try:
            from rfauto.adapters.meep_adapter import default_stackup
            anchor_st = default_stackup()
        except Exception:  # pragma: no cover
            anchor_st = Stackup(name="rogers4350b", epsilon_r=3.66, thickness_mm=0.508,
                                loss_tangent=0.0037)
        st = Stackup(
            name=str(st_in.get("name", anchor_st.name)),
            epsilon_r=float(st_in.get("epsilon_r", anchor_st.epsilon_r)),
            thickness_mm=float(st_in.get("thickness_mm", anchor_st.thickness_mm)),
            loss_tangent=float(st_in.get("loss_tangent", anchor_st.loss_tangent)),
            rho=float(st_in.get("rho", anchor_st.rho)),
        )
        n_freq = int(geometry.get("n_freq", 41))
        freqs_ghz = geometry.get("freqs_ghz")
        lo, hi = self._config.freq_range_ghz
        fs = ([float(f) for f in freqs_ghz] if freqs_ghz is not None
              else list(np.linspace(lo, hi, n_freq)))
        if len(fs) < 2:
            self._last_error = f"频点网格须 ≥2 点: {fs[:5]}"
            logger.error("%s", self._last_error)
            return False
        if any(f <= 0 for f in fs) or any(b <= a for a, b in itertools.pairwise(fs)):
            self._last_error = f"频点须为正且严格递增: {fs[:5]}"
            logger.error("%s", self._last_error)
            return False
        try:
            text = render_mline_netlist(
                w_mm, line_len_mm, st, [f * 1e9 for f in fs],
                z0_ref=float(geometry.get("z0_ref", 50.0)),
            )
        except ValueError as exc:
            self._last_error = f"mline 网表渲染失败: {exc}"
            logger.error("%s", self._last_error)
            return False
        workdir = Path(self._config.working_dir or ".")
        workdir.mkdir(parents=True, exist_ok=True)
        self._netlist_path = workdir / _NETLIST_NAME
        self._netlist_path.write_text(text, encoding="ascii")
        self._geometry = {"template": template, "params": {"w_mm": w_mm,
                                                           "line_len_mm": line_len_mm},
                          "freqs_ghz": fs, "stackup": asdict(st)}
        return True

    # ── 求解与解析 ──────────────────────────────────────────────────────────

    def solve(self, timeout_s: int = 600) -> EMSolverResult:
        """单激励电路求解（SP 频扫）→ 全 2×2 S 矩阵 + β + 同构产物落盘。"""
        if not self._connected:
            return EMSolverResult(success=False, message="Not connected")
        if self._netlist_path is None or not self._netlist_path.exists():
            return EMSolverResult(success=False, message="build_geometry() 未生成网表")
        workdir = Path(self._config.working_dir or ".")
        dataset_path = workdir / _DATASET_NAME
        t0 = time.time()
        try:
            proc = subprocess.run(
                [str(self._exe_path), "-i", self._netlist_path.name,
                 "-o", dataset_path.name],
                cwd=str(workdir), capture_output=True, text=True,
                timeout=timeout_s, check=False,
            )
        except subprocess.TimeoutExpired:
            return EMSolverResult(success=False,
                                  message=f"qucsatorRF 求解超时（>{timeout_s}s）")
        except OSError as exc:
            return EMSolverResult(success=False, message=f"qucsatorRF 启动失败: {exc}")
        wall = round(time.time() - t0, 1)
        # rc 不足为凭 + 错误行显式收集（ngspice 同款纪律；checker 错误实测 rc=127）
        err_lines = [
            ln.strip() for ln in (proc.stdout + "\n" + proc.stderr).splitlines()
            if re.search(r"(error|Error|ERROR|failed|WARNING)", ln)
        ]
        if proc.returncode != 0 or not dataset_path.is_file():
            detail = "; ".join(err_lines[-5:]) or f"rc={proc.returncode}"
            return EMSolverResult(success=False, wall_time_s=wall,
                                  message=f"qucsatorRF 运行失败（rc={proc.returncode}）: {detail}")
        try:
            parsed = read_qucs_dataset(dataset_path)
        except QucsatorError as exc:
            return EMSolverResult(success=False, wall_time_s=wall,
                                  message=f"qucsatorRF dataset 解析失败: {exc}")
        freq_hz = parsed["freq_hz"]
        missing = [k for k in ((1, 1), (1, 2), (2, 1), (2, 2)) if k not in parsed["S"]]
        if missing:
            return EMSolverResult(success=False, wall_time_s=wall,
                                  message=f"dataset 缺 S 分量: {missing}")
        n = len(freq_hz)
        s = np.zeros((n, 2, 2), dtype=complex)
        for (i, j), arr in parsed["S"].items():
            s[:, i - 1, j - 1] = arr
        # β：S21 相位提取，HJ 闭式定 2π 分支（见 beta_from_s21；分支参照不进数值）
        w_mm = float(self._geometry["params"]["w_mm"])
        line_len_mm = float(self._geometry["params"]["line_len_mm"])
        try:
            from rfauto.adapters.meep_adapter import hj_beta_series
            beta_ref = hj_beta_series(w_mm, freq_hz / 1e9, _stackup_from(self._geometry))
        except Exception as exc:  # pragma: no cover —— HJ 腿不可得时不阻塞 S 主路
            beta_ref = None
            logger.warning("HJ 分支参照不可得（%s），按零分支解卷绕", exc)
        try:
            beta = beta_from_s21(
                freq_hz, s[:, 1, 0], line_len_mm * 1e-3,
                beta_branch_ref_ghz=beta_ref,
            )
        except ValueError as exc:
            return EMSolverResult(success=False, wall_time_s=wall,
                                  message=f"β 提取失败: {exc}")
        eeff = (beta * _C0_M_S / (2.0 * math.pi * freq_hz)) ** 2
        self._write_products(workdir, freq_hz, s, beta)
        message = (f"qucsatorRF solve ok（{n} 频点，电路级 SP）；"
                   "β=S21 相位提取（KJ 色散口径，与 HJ 准静态存在物理口径差）")
        if err_lines:
            message += f"；引擎消息: {'; '.join(err_lines[-3:])}"
        return EMSolverResult(
            success=True, freq_ghz=freq_hz / 1e9, s_params=s,
            field_data={"beta_rad_per_m": beta, "epsilon_eff": eeff,
                        "line_len_mm": line_len_mm, "w_mm": w_mm,
                        "disp_model": "Kirschning", "quasi_static_model": "Hammerstad"},
            wall_time_s=wall, message=message,
        )

    def _write_products(self, workdir: Path, freq_hz: np.ndarray,
                        s: np.ndarray, beta: np.ndarray) -> None:
        """落盘同构产物：openEMS #162 schema CSV ×2 + skrf Touchstone .s2p。"""
        csv_path = workdir / _SPARAMS_CSV_NAME
        with open(csv_path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(_SPARAMS_CSV_HEADER)
            for i in range(len(freq_hz)):
                w.writerow([freq_hz[i], s[i, 0, 0].real, s[i, 0, 0].imag,
                            s[i, 1, 0].real, s[i, 1, 0].imag])
        beta_path = workdir / _BETA_CSV_NAME
        with open(beta_path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(_BETA_CSV_HEADER)
            for i in range(len(freq_hz)):
                w.writerow([freq_hz[i], beta[i]])
        touch_path = workdir / _TOUCHSTONE_NAME
        try:
            import skrf

            net = skrf.Network(
                frequency=skrf.Frequency.from_f(freq_hz, unit="Hz"),
                s=s, z0=50.0,
            )
            net.write_touchstone(str(touch_path), form="ri")
        except Exception as exc:  # 观测性面：Touchstone 失败不回滚 S/β 产物（#105）
            logger.warning("Touchstone 导出失败（CSV 产物保留）: %s", exc)

    @staticmethod
    def _read_products(workdir: Path) -> tuple[Any, Any] | None:
        """重读 sparams/port_beta CSV → (freq_ghz, s(n,2,2)) / None。"""
        csv_path = workdir / _SPARAMS_CSV_NAME
        if not csv_path.is_file():
            return None
        try:
            with open(csv_path, encoding="utf-8") as fh:
                rows = list(csv.reader(fh))
            header = [h.strip() for h in rows[0]]
            if tuple(header) != _SPARAMS_CSV_HEADER:
                return None
            freqs: list[float] = []
            srows: list[tuple[complex, complex]] = []
            for r in rows[1:]:
                if not r or not r[0].strip():
                    continue
                freqs.append(float(r[0]))
                srows.append((complex(float(r[1]), float(r[2])),
                              complex(float(r[3]), float(r[4]))))
        except Exception:
            return None
        s = np.zeros((len(freqs), 2, 2), dtype=complex)
        for i, (s11, s21) in enumerate(srows):
            s[i, 0, 0] = s11
            s[i, 1, 0] = s21
        # 互易补齐 + S22 对角补齐（电路级 2 端口互易网络；dataset 已全矩阵实测，
        # CSV 读面缺 S12/S22 时按互易/对称重建——遮蔽字段见 #314 掩码纪律：
        # 本通道 dataset 面为全矩阵实测，无补齐歧义）
        s[:, 0, 1] = s[:, 1, 0]
        s[:, 1, 1] = s[:, 0, 0]
        return np.array(freqs) / 1e9, s

    def get_sparams(self) -> tuple[Any, Any] | None:
        """读取最近一次 solve 的 S 参数（与 MeepSolver 同约定）。"""
        out = self._read_products(Path(self._config.working_dir or "."))
        return (out[0], out[1]) if out is not None else None

    def get_beta(self) -> tuple[Any, Any] | None:
        """读取最近一次 solve 的 β（rad/m）。"""
        beta_path = Path(self._config.working_dir or ".") / _BETA_CSV_NAME
        if not beta_path.is_file():
            return None
        try:
            with open(beta_path, encoding="utf-8") as fh:
                rows = list(csv.reader(fh))
            if tuple(h.strip() for h in rows[0]) != _BETA_CSV_HEADER:
                return None
            freqs = [float(r[0]) for r in rows[1:] if r and r[0].strip()]
            betas = [float(r[1]) for r in rows[1:] if r and r[0].strip()]
        except Exception:
            return None
        return np.array(freqs) / 1e9, np.array(betas)

    def close(self) -> None:
        self._connected = False
        self._netlist_path = None
        self._geometry = {}

    # ── 6g 产物视图协议 ────────────────────────────────────────────────────

    def visualizations(self) -> list[dict[str, Any]]:
        workdir = self._config.working_dir or "."
        return [
            {"kind": "circuit", "spec": {"file": str(Path(workdir) / _NETLIST_NAME),
                                         "format": "qucs-netlist"}},
            {"kind": "sparams", "spec": {"file": str(Path(workdir) / _SPARAMS_CSV_NAME)}},
        ]

    def supported_output_formats(self) -> list[str]:
        return ["touchstone", "csv"]


def _stackup_from(geometry: dict[str, Any]) -> Stackup:
    """从 build_geometry 存档重建 Stackup（β 分支参照用）。"""
    st = dict(geometry.get("stackup") or {})
    return Stackup(
        name=str(st.get("name", "rogers4350b")),
        epsilon_r=float(st.get("epsilon_r", 3.66)),
        thickness_mm=float(st.get("thickness_mm", 0.508)),
        loss_tangent=float(st.get("loss_tangent", 0.0037)),
        rho=float(st.get("rho", 1.724e-8)),
    )


# --------------------------------------------------------------------------- #
# 注册（em_solver_base 的 QUCSATOR 枚举行 = 注册 hunk 文本交付，本模块兼容
# 两种树态：hunk 已合入 → 注册枚举键；未合入 → 跳过全局注册——字符串键会让
# r3_services.list_registered_solvers 的 stype.value 崩，宁缺不脏）
# --------------------------------------------------------------------------- #

def _resolve_solver_type_key() -> Any:
    """解析注册键：EMSolverType.QUCSATOR（hunk 已合入）或 None（未合入）。"""
    from rfauto.adapters.em_solver_base import EMSolverType
    return getattr(EMSolverType, "QUCSATOR", None)


def register_qucsator(registry: Any = None, *, type_key: Any = None) -> bool:
    """注册到全局/指定 EMSolverRegistry。

    返回是否完成注册（枚举键缺失且未显式传 type_key 时跳过 → False，
    不抛错不污染全局注册表——观测性 #105 + #362 注册表面纪律）。
    """
    from rfauto.adapters.em_solver_base import EMSolverRegistry, get_global_registry
    target = registry if isinstance(registry, EMSolverRegistry) else get_global_registry()
    key = type_key if type_key is not None else _resolve_solver_type_key()
    if key is None:
        logger.debug(
            "qucsator 注册跳过：EMSolverType.QUCSATOR 尚未合入（注册 hunk 待应用）"
        )
        return False
    target.register(key, QucsatorAdapter)
    return True


"""Register on import (same pattern as meep/palace/vna; never blocks import).
hunk 未合入的当前树态下为 no-op（枚举键缺失 → 跳过）。"""
with contextlib.suppress(Exception):
    register_qucsator()
