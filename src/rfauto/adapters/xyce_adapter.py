"""F-L.2 Xyce-WSL 电路级适配器（Sandia Xyce 开源 SPICE 通道，WSL 桥）。

定位：EMSolverRegistry 的**电路级**通道——与 qucsator（N7 准静态线路级）
同层互补。Xyce 是器件级 SPICE 族求解器，本通道为其后续 HB/振荡器面
（master plan F-L.2 HB）铺驱动地基；**本期 v0 只做 DC/.tran/.ac 三基本
分析的网表驱动 + rlc_lowpass 一锚，.HB 分析登记不实现**（如实不虚报，
supported_templates 仅 ("rlc_lowpass",)）。

部署口径（2026-09-29 wf:xyce-build 实测）：Xyce 7.11（DEVELOPMENT
opensource，MPI 版 libmpi.so.40）装在 **WSL 默认发行版 Ubuntu**，WSL 侧
可执行 ``/home/pc/apps/xyce/bin/Xyce``。Windows 侧经
``wsl.exe -d <distro> --exec bash -c "..."`` 驱动；网表/产物直接落
/mnt/<盘> 映射的仓内 runs/ 工作目录（网表小，零拷贝）。不可达时报错指引
构建脚本 ``tools/xyce_stack_build.sh``。

与 spice_netlist.resolve_xyce_exe 的分工（勿混用）：那是 **Windows 原生
Xyce.exe** 探测钩子（env ``RFAUTO_XYCE_BIN`` → PATH，本机无安装、恒不可
用）；本模块 :func:`resolve_xyce_exe` 是 **WSL 侧**驱动通道（显式参数 →
env ``RFAUTO_XYCE_EXE`` → 默认 /home/pc/apps/xyce/bin/Xyce）。两条链 env
变量名不同、语义不同（Windows exe vs WSL 路径）。

输出格式标定（2026-09-29 真机 7.11 实测，#215 纪律：不凭想象写 API）：
- ``.print ac ...`` → ``<netlist>.FD.prn``（ASCII 列式表：
  ``Index FREQ Re(V(3)) Im(V(3))``，复数以 Re/Im 双列输出）；
- ``.print tran ...`` → ``<netlist>.prn``（``Index TIME V(2)``，实数单列）；
- ``.print dc ...`` → ``<netlist>.prn``（``Index V(2)``，无自变量列——
  扫描源值不在列内，需要轴时打印被扫源电压）；
- 尾行一律 ``End of Xyce(TM) Simulation``；
- ``-r`` rawfile 缺省**二进制**，``.options output rawformat=ascii`` 实测
  不改变格式——本通道不消费 rawfile，``.print`` 的 prn 列式表是唯一解析面
  （实测最稳）。

wsl.exe 管道输出是 UTF-16LE（#271 家族），解码见 :func:`decode_wsl_bytes`；
MSYS 路径转换坑（#ge2①）只影响 git-bash 直调，Python subprocess 原生
CreateProcess 无此层。

诚实边界：solve 产物是**电压传函 H(f)=V(out)/V1**（RLC 低通锚），非 S
参数——s_params 恒 None、supports_touchstone_export=False，不虚报
（#122 口径）；HB/优化面 v0 不承诺。

分层：adapters，仅依赖 em_solver_base（注册基类）+ stdlib/numpy；供后续
service 层编排调用。注册照 qucsator 同款（EMSolverType.XYCE + 模块导入
即注册，注册 hunk 未合入的树态自动跳过——宁缺不脏）。
"""

from __future__ import annotations

import contextlib
import csv
import logging
import os
import re
import shlex
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

import numpy as np

from rfauto.adapters.em_solver_base import (
    EMSolverAdapter,
    EMSolverConfig,
    EMSolverResult,
    SolverCapabilities,
)

logger = logging.getLogger(__name__)

#: WSL 默认发行版（2026-09-29 实测 ``wsl -l -v``：Ubuntu（默认，26.04）+
#: rfauto-ubuntu（Palace 专用）；Xyce 装在默认发行版）。
DEFAULT_WSL_DISTRO = "Ubuntu"

#: WSL 侧 Xyce 可执行缺省路径（wf:xyce-build 安装位实测）。
DEFAULT_XYCE_WSL_EXE = "/home/pc/apps/xyce/bin/Xyce"

#: 不可达时报错指引的构建脚本（仓内相对路径）。
XYCE_STACK_BUILD_HINT = "tools/xyce_stack_build.sh"


class XyceError(RuntimeError):
    """Xyce 通道执行失败（解析/运行/前置校验任一环节，显式不静默）。"""


# --------------------------------------------------------------------------- #
# 可执行解析与 WSL 桥
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class XyceExeSpec:
    """Xyce 可执行规格（WSL 侧路径 + 发行版；均为字符串面，Windows Path
    无法表达 /home/... 故不落 Path）。"""

    wsl_path: str
    distro: str = DEFAULT_WSL_DISTRO


def resolve_xyce_exe(
    explicit: str | None = None, *, distro: str | None = None
) -> XyceExeSpec:
    """选定 Xyce WSL 可执行：显式参数 → env ``RFAUTO_XYCE_EXE`` → 缺省
    ``/home/pc/apps/xyce/bin/Xyce``。

    只做路径选定（纯字符串面，不探测 WSL——可达性验证在
    :func:`verify_xyce_reachable`）。注意 env 变量是 ``RFAUTO_XYCE_EXE``
    （WSL 路径），与 spice_netlist 的 ``RFAUTO_XYCE_BIN``（Windows exe）
    是两条独立链。
    """
    path = explicit
    if path is None:
        path = os.environ.get("RFAUTO_XYCE_EXE", "").strip() or None
    if path is None:
        path = DEFAULT_XYCE_WSL_EXE
    path = str(path).strip()
    if not path:
        raise XyceError("Xyce WSL 路径解析为空串（显式参数/env 均不可为空白）")
    return XyceExeSpec(wsl_path=path, distro=str(distro or DEFAULT_WSL_DISTRO))


#: 子进程运行器注入点：``(argv, timeout_s) -> CompletedProcess``（bytes 输出，
#: 解码统一走 :func:`decode_wsl_bytes`——wsl.exe 管道输出 UTF-16LE，#271）。
Runner = Callable[[list[str], float], subprocess.CompletedProcess]


def _default_runner(argv: list[str], timeout_s: float) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, timeout=timeout_s, check=False)


def decode_wsl_bytes(raw: bytes) -> str:
    """解码 wsl.exe 管道输出：UTF-16LE（含 NUL）→ 剥 NUL 后按 utf-16-le；
    否则按 utf-8 replace（#271 家族口径；WSL 桥公共工具，冒烟脚本 ngspice
    腿同用）。"""
    if not raw:
        return ""
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff") or b"\x00" in raw:
        body = raw[2:] if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else raw
        return body.decode("utf-16-le", errors="replace").replace("\x00", "")
    return raw.decode("utf-8", errors="replace")


def wsl_bash_argv(spec: XyceExeSpec, script: str) -> list[str]:
    """组装 ``wsl -d <distro> --exec bash -c <script>`` argv（公共工具）。"""
    return ["wsl.exe", "-d", spec.distro, "--exec", "bash", "-c", script]


def verify_xyce_reachable(
    spec: XyceExeSpec | None = None,
    *,
    timeout_s: float = 60.0,
    runner: Runner | None = None,
) -> XyceExeSpec:
    """探测 WSL 发行版内 Xyce 可执行在位且可执行（``test -x``）。

    不可达抛 FileNotFoundError（附 ``RFAUTO_XYCE_EXE`` 与
    ``tools/xyce_stack_build.sh`` 指引；锚是裁判，不静默降级）。
    """
    spec = spec or resolve_xyce_exe()
    run = (runner or _default_runner)(
        wsl_bash_argv(spec, f"test -x {shlex.quote(spec.wsl_path)}"), timeout_s
    )
    if run.returncode != 0:
        raise FileNotFoundError(
            f"WSL({spec.distro}) 内 Xyce 可执行不可达: {spec.wsl_path} "
            f"(rc={run.returncode})；可设 RFAUTO_XYCE_EXE 指向 WSL 侧 Xyce "
            f"可执行，或按 {XYCE_STACK_BUILD_HINT} 构建安装"
        )
    return spec


def xyce_version(
    spec: XyceExeSpec | None = None,
    *,
    timeout_s: float = 60.0,
    runner: Runner | None = None,
) -> str | None:
    """Xyce 版本串（best-effort，永不抛错——观测性 #105 纪律）。"""
    try:
        spec = spec or resolve_xyce_exe()
        run = (runner or _default_runner)(
            wsl_bash_argv(spec, f"{shlex.quote(spec.wsl_path)} -v"), timeout_s
        )
    except Exception:
        return None
    m = re.search(r"Xyce\s+\S+", decode_wsl_bytes(run.stdout) + decode_wsl_bytes(run.stderr))
    return m.group(0) if m else None


_DRIVE_SEG_RE = re.compile(r"^[A-Za-z]:[\\/]?$")


def windows_to_wsl_path(path: str | Path) -> str:
    """Windows 盘符绝对路径 → WSL ``/mnt/<盘>/...`` 路径（纯函数）。

    非盘符布局（POSIX 根/相对路径/UNC）显式 ValueError——历史教训 df5
    E-MED-6：静默提取出空串得 /mnt// 坏路径。
    """
    parts = Path(path).parts
    if not parts or _DRIVE_SEG_RE.fullmatch(parts[0]) is None:
        raise ValueError(
            f"windows_to_wsl_path 仅支持 Windows 盘符绝对路径，收到 {str(path)!r}"
        )
    drive = "".join(ch for ch in parts[0] if ch.isalnum()).lower()
    rest = "/".join(parts[1:])
    return "/mnt/" + drive + ("/" + rest if rest else "")


@dataclass
class XyceRunResult:
    """一次 Xyce 子进程运行的结果（stdout/stderr 已解码）。"""

    rc: int
    stdout: str
    stderr: str
    wall_time_s: float
    netlist_path: Path
    timed_out: bool = False


def run_xyce(
    netlist_path: str | Path,
    *,
    spec: XyceExeSpec | None = None,
    distro: str | None = None,
    timeout_s: float = 300.0,
    extra_args: tuple[str, ...] = (),
    runner: Runner | None = None,
) -> XyceRunResult:
    """在 WSL 内运行 Xyce 网表（工作目录 = 网表所在目录，产物就地落盘）。

    命令形态：``wsl -d <distro> --exec bash -c "cd <dir> && <exe> [args] <name>"``。
    网表必须在 Windows 盘符路径（mnt/<盘> 可达）；超时返回
    ``timed_out=True`` 的结果（不抛，由调用方定夺——观测性 #105）。
    """
    netlist = Path(netlist_path)
    if not netlist.is_file():
        raise XyceError(f"网表不存在: {netlist}")
    spec = spec or resolve_xyce_exe(distro=distro)
    wsl_dir = windows_to_wsl_path(netlist.resolve().parent)
    script = (
        f"cd {shlex.quote(wsl_dir)} && {shlex.quote(spec.wsl_path)} "
        + " ".join(shlex.quote(a) for a in extra_args)
        + " "
        + shlex.quote(netlist.name)
    )
    t0 = time.time()
    try:
        run = (runner or _default_runner)(wsl_bash_argv(spec, script), timeout_s)
    except subprocess.TimeoutExpired:
        return XyceRunResult(
            rc=-1, stdout="", stderr=f"Xyce 求解超时（>{timeout_s}s）",
            wall_time_s=round(time.time() - t0, 1),
            netlist_path=netlist, timed_out=True,
        )
    return XyceRunResult(
        rc=run.returncode,
        stdout=decode_wsl_bytes(run.stdout),
        stderr=decode_wsl_bytes(run.stderr),
        wall_time_s=round(time.time() - t0, 3),
        netlist_path=netlist,
    )


# --------------------------------------------------------------------------- #
# 网表渲染（纯函数；数值一律 %.17g SI 字面量——双精度往返无损，解析侧与
# 解析传函共享同一 double，规避单位后缀歧义）
# --------------------------------------------------------------------------- #


def _num(value: float) -> str:
    """SI 纯指数字面量（%.17g 保证 double 往返一致；−0.0 归一）。"""
    v = float(value)
    if v == 0.0:
        v = 0.0
    return f"{v:.17g}"


def render_netlist(
    *,
    title: str,
    element_lines: list[str],
    analysis_lines: list[str],
    print_lines: list[str],
) -> str:
    """组装 Xyce（SPICE 族）网表文本：标题注释 → 元件 → 分析 → 打印 → .end。

    纯字符串组装（LF 行尾，尾单换行）；非 ASCII 标题在写盘 encode("ascii")
    时显式报错（#89：工具文件零非 ASCII）。
    """
    lines = [f"* {title}", *element_lines, *analysis_lines, *print_lines, ".end", ""]
    return "\n".join(lines)


def render_rlc_ac_netlist(
    r_ohm: float,
    l_henry: float,
    c_farad: float,
    *,
    fstart_hz: float = 1e3,
    fstop_hz: float = 1e6,
    points_per_decade: int = 49,
    print_node: str = "3",
    title: str = "rfauto F-L.2 Xyce rlc_lowpass ac anchor",
) -> str:
    """渲染 RLC 低通（V1-R-L-C 对地 C 取电压）AC 对数扫频网表。

    结构：``V1 1 0 AC 1`` → ``R1 1 2`` → ``L1 2 3`` → ``C1 3 0`` →
    ``.AC dec <ppd> <fstart> <fstop>`` → ``.print ac v(<node>)``。
    传函解析式（三方对照裁判用）：``H(w)=1/(1 - w^2*L*C + j*w*R*C)``。
    """
    if r_ohm <= 0:
        raise ValueError(f"R 必须为正（Ω）: {r_ohm}")
    if l_henry <= 0:
        raise ValueError(f"L 必须为正（H）: {l_henry}")
    if c_farad <= 0:
        raise ValueError(f"C 必须为正（F）: {c_farad}")
    if fstart_hz <= 0 or fstop_hz <= fstart_hz:
        raise ValueError(f"频段须 0<fstart<fstop: {fstart_hz}, {fstop_hz}")
    if int(points_per_decade) < 1:
        raise ValueError(f"每十倍程点数须 ≥1: {points_per_decade}")
    return render_netlist(
        title=title,
        element_lines=[
            "V1 1 0 AC 1",
            f"R1 1 2 {_num(r_ohm)}",
            f"L1 2 3 {_num(l_henry)}",
            f"C1 3 0 {_num(c_farad)}",
        ],
        analysis_lines=[
            f".AC dec {int(points_per_decade)} {_num(fstart_hz)} {_num(fstop_hz)}"
        ],
        print_lines=[f".print ac v({print_node})"],
    )


def render_rc_tran_netlist(
    *,
    v_step: float = 1.0,
    r_ohm: float = 1e3,
    c_farad: float = 1e-9,
    t_step_s: float = 1e-7,
    t_stop_s: float = 1e-5,
    print_node: str = "2",
    title: str = "rfauto F-L.2 Xyce rc_step tran",
) -> str:
    """渲染 RC 阶跃瞬态网表（PWL 陡升源；终态 V(node)→v_step，τ=RC）。"""
    if v_step == 0:
        raise ValueError("v_step 不可为 0（PWL 陡升语义）")
    if r_ohm <= 0 or c_farad <= 0:
        raise ValueError(f"R/C 必须为正: {r_ohm}, {c_farad}")
    if t_step_s <= 0 or t_stop_s <= t_step_s:
        raise ValueError(f"须 0<t_step<t_stop: {t_step_s}, {t_stop_s}")
    ramp = t_step_s / 100.0  # 陡升沿（<<τ 即可，τ=RC=1us >> 1ns）
    return render_netlist(
        title=title,
        element_lines=[
            f"V1 1 0 PWL(0 0 {ramp:.17g} 0 {2 * ramp:.17g} {_num(v_step)} "
            f"{_num(t_stop_s * 2)} {_num(v_step)})",
            f"R1 1 2 {_num(r_ohm)}",
            f"C1 2 0 {_num(c_farad)}",
        ],
        analysis_lines=[f".tran {_num(t_step_s)} {_num(t_stop_s)}"],
        print_lines=[f".print tran v({print_node})"],
    )


def render_divider_dc_netlist(
    *,
    v_source: float = 10.0,
    r1_ohm: float = 1e3,
    r2_ohm: float = 1e3,
    print_node: str = "2",
    title: str = "rfauto F-L.2 Xyce divider dc",
) -> str:
    """渲染分压器 DC 扫描网表（扫 V1 0→v_source 十一步；终态 v(node) 半压）。"""
    if v_source == 0:
        raise ValueError("v_source 不可为 0（扫描语义）")
    if r1_ohm <= 0 or r2_ohm <= 0:
        raise ValueError(f"R1/R2 必须为正: {r1_ohm}, {r2_ohm}")
    step = v_source / 10.0
    return render_netlist(
        title=title,
        element_lines=[
            f"V1 1 0 {_num(v_source)}",
            f"R1 1 2 {_num(r1_ohm)}",
            f"R2 2 0 {_num(r2_ohm)}",
        ],
        analysis_lines=[f".DC V1 0 {_num(v_source)} {_num(step)}"],
        print_lines=[f".print dc v({print_node})"],
    )


# --------------------------------------------------------------------------- #
# prn 列式表解析（2026-09-29 真机 7.11 标定，格式见模块 docstring）
# --------------------------------------------------------------------------- #

_RE_COL_RE = re.compile(r"^Re\((.+)\)$")
_IM_COL_RE = re.compile(r"^Im\((.+)\)$")
_INDEP_NAMES = frozenset({"TIME", "FREQ"})
_FOOTER_PREFIX = "End of Xyce"


def prn_path_for(netlist_path: str | Path, *, ac: bool) -> Path:
    """``.print`` 产物路径（真机标定）：AC → ``<netlist>.FD.prn``；
    tran/dc → ``<netlist>.prn``（无中缀）。"""
    p = Path(netlist_path)
    return p.with_name(p.name + (".FD.prn" if ac else ".prn"))


def parse_prn(text: str) -> dict[str, Any]:
    """解析 Xyce ``.print`` 产物（prn/FD.prn 同构列式表）。

    格式：首行表头 ``Index`` + 若干数据列；列名三态——``Re(X)``/``Im(X)``
    相邻成对的复数列、``TIME``/``FREQ`` 自变量列（至多一个）、其余实数列。
    数据行全数值；尾行 ``End of Xyce(TM) Simulation`` 及其后内容忽略；
    列数不符/无数据行/表头非法/重复列名 → XyceError（不静默，#316 方向：
    坏文件多报）。

    Returns:
        ``{"indep": str | None, "vars": [names], "index": np.ndarray,
        "data": {name: np.ndarray(complex)}}``
    """
    lines = text.splitlines()
    header_idx = next((i for i, ln in enumerate(lines) if ln.strip()), None)
    if header_idx is None:
        raise XyceError("prn 为空（Xyce 未产出 .print 数据或被 error 中断）")
    header = lines[header_idx].split()
    if header[0] != "Index":
        raise XyceError(f"prn 表头首列须为 Index，收到 {header[0]!r}")
    cols = header[1:]
    indep: str | None = None
    vars_real: list[str] = []
    complex_pairs: dict[str, int] = {}
    pair_names: list[str] = []  # 追加式（含重复）——重复检测不能走 dict 键
    k = 0
    while k < len(cols):
        m_re = _RE_COL_RE.match(cols[k])
        if m_re:
            name = m_re.group(1)
            m_im = _IM_COL_RE.match(cols[k + 1]) if k + 1 < len(cols) else None
            if m_im is None or m_im.group(1) != name:
                raise XyceError(f"prn 复数列 Re({name}) 缺少配对 Im 列")
            complex_pairs[name] = k
            pair_names.append(name)
            k += 2
            continue
        if _IM_COL_RE.match(cols[k]):
            raise XyceError(f"prn 复数列 {cols[k]} 缺少前导 Re 列")
        name = cols[k]
        if name.upper() in _INDEP_NAMES:
            if indep is not None:
                raise XyceError(f"prn 出现多个自变量列: {indep} 与 {name}")
            indep = name
        else:
            vars_real.append(name)
        k += 1
    # 重复列名显式报错（审查分片 1 P3-6③，#316 多报方向）：Xyce 同名双列
    # 打印时 cols.index 首列命中会让第二列被静默别名、复数对被 dict 覆盖
    # ——坏文件多报，不静默。
    data_names = [*vars_real, *pair_names]
    if indep is not None:
        data_names.append(indep)
    dupes = sorted({n for n in data_names if data_names.count(n) > 1})
    if dupes:
        raise XyceError(f"prn 存在重复列名（静默别名禁绝）: {dupes}")
    n_cols = 1 + len(cols)
    idx_out: list[int] = []
    col_vals: list[list[float]] = []
    for raw in lines[header_idx + 1:]:
        line = raw.strip()
        if not line:
            continue
        if line.startswith(_FOOTER_PREFIX):
            break
        try:
            vals = [float(tok) for tok in line.split()]
        except ValueError as exc:
            raise XyceError(f"prn 数据行含非数值令牌: {line!r} ({exc})") from exc
        if len(vals) != n_cols:
            raise XyceError(f"prn 数据行列数 {len(vals)} != 表头 {n_cols}: {line!r}")
        idx_out.append(int(vals[0]))
        col_vals.append(vals[1:])
    if not idx_out:
        raise XyceError("prn 无数据行（Xyce 未产出 .print 数据或被 error 中断）")
    arr = np.array(col_vals, dtype=float)
    data: dict[str, np.ndarray] = {}
    for name in vars_real:
        j = cols.index(name)
        data[name] = arr[:, j] + 0j
    for name, j in complex_pairs.items():
        data[name] = arr[:, j] + 1j * arr[:, j + 1]
    if indep is not None:
        data[indep] = arr[:, cols.index(indep)] + 0j
    return {
        "indep": indep,
        "vars": vars_real + [n for n in complex_pairs],
        "index": np.array(idx_out, dtype=np.int64),
        "data": data,
    }


def read_prn(path: str | Path) -> dict[str, Any]:
    """读取 prn 文件并解析（:func:`parse_prn` 的文件入口）。"""
    return parse_prn(Path(path).read_text(encoding="utf-8", errors="replace"))


# --------------------------------------------------------------------------- #
# 适配器（EMSolverRegistry 注册面；solve 产物 = RLC 低通电压传函 H(f)，非 S 参数）
# --------------------------------------------------------------------------- #

_NETLIST_NAME = "xyce_rlc_ac.cir"
_TRANSFER_CSV_NAME = "xyce_rlc_transfer.csv"
_TRANSFER_CSV_HEADER = ("freq_hz", "re_H", "im_H", "db_H")

#: rlc_lowpass 锚缺省参数（= 三方对照冒烟 scripts/xyce_smoke_threeway.py 同源；
#: f0=1/(2π√(LC))≈15.9kHz、Q=√(L/C)/R=10，谐振峰落在扫频段内）。
RLC_ANCHOR_DEFAULTS: dict[str, float] = {
    "r_ohm": 10.0,
    "l_henry": 1e-3,
    "c_farad": 1e-7,
}


def rlc_lowpass_transfer(freq_hz: np.ndarray, r_ohm: float, l_henry: float,
                         c_farad: float) -> np.ndarray:
    """RLC 低通传函闭式 ``H=1/(1-w^2*L*C + j*w*R*C)``（三方对照解析腿）。"""
    w = 2.0 * np.pi * np.asarray(freq_hz, dtype=float)
    return 1.0 / (1.0 - w * w * l_henry * c_farad + 1j * w * r_ohm * c_farad)


class XyceAdapter(EMSolverAdapter):
    """Xyce-WSL 电路级适配器（子进程批处理 + prn 解析，qucsator 同构）。

    solve() 链：build_geometry 渲染 rlc_lowpass AC 网表（LF 字节落盘）→
    WSL 单次子进程 → ``<netlist>.FD.prn`` 解析 → 电压传函 H(f) + 产物 CSV
    落盘。s_params 恒 None（传函非 S 参数，不虚报）。
    """

    # 能力声明（如实，2026-09-29；电路级 SPICE 通道不虚报 EM 面）：
    #   - 端口：V/I 器件引脚，非 EM 波端口/集总端口边界 → wave/lumped=False；
    #   - 材料：RLC 集总元件（lumped_element）；v0 无介质/PEC 模型面；
    #   - Touchstone：v0 无 S 参数产物 → False（传函 CSV 为准）；
    #   - 场导出/收敛报告/optimetrics/nf2ff/SAR：电路级无对应实现 → False；
    #   - dimension："circuit"（电路级，非 2d/3d 场求解）；
    #   - 模板：v0 仅 rlc_lowpass 锚；HB 登记不实现；
    #   - license：开源（GPL 系列例外条目）→ False；
    #   - parallel_backends：适配器不透传 MPI 开关 → 空元组（不虚报引擎
    #     理论并行能力，口径同 openems）。
    CAPABILITIES: ClassVar[SolverCapabilities] = SolverCapabilities(
        solver_type="xyce",
        supports_wave_port=False,
        supports_lumped_port=False,
        supports_field_export=False,
        supports_convergence_report=False,
        supports_touchstone_export=False,
        supports_headless_solve=True,
        supports_optimetrics=False,
        dimension="circuit",
        material_models=("lumped_element",),
        parallel_backends=(),
        supports_sar=False,
        supports_nf2ff=False,
        supports_lumped_elements=True,
        supported_templates=("rlc_lowpass",),
        requires_license=False,
        availability_gate="wsl_exe",
    )

    def __init__(self, config: EMSolverConfig):
        super().__init__(config)
        extra = config.extra_params or {}
        self._exe_wsl: str | None = config.exe_path or extra.get("xyce_exe_wsl")
        self._distro: str | None = extra.get("wsl_distro")
        self._run_timeout_s: float = float(extra.get("run_timeout_s", 300.0))
        self._spec: XyceExeSpec | None = None
        self._netlist_path: Path | None = None
        self._geometry: dict[str, Any] = {}
        self._last_error: str | None = None

    # ── 生命周期 ────────────────────────────────────────────────────────────

    def connect(self) -> bool:
        try:
            spec = resolve_xyce_exe(self._exe_wsl, distro=self._distro)
            self._spec = verify_xyce_reachable(spec)
        except (FileNotFoundError, XyceError, OSError) as exc:
            self._last_error = str(exc)
            logger.error("%s", self._last_error)
            return False
        self._connected = True
        return True

    def is_available(self) -> bool:
        try:
            verify_xyce_reachable(resolve_xyce_exe(self._exe_wsl, distro=self._distro))
        except Exception:
            return False
        return True

    # ── 配置生成 ────────────────────────────────────────────────────────────

    def build_geometry(self, geometry: dict[str, Any]) -> bool:
        """渲染 rlc_lowpass 锚 AC 网表到 working_dir/xyce_rlc_ac.cir（LF）。

        geometry 契约（v0 仅 rlc_lowpass 一锚）:
            template: "rlc_lowpass"     —— 其他值显式 NOT_SUPPORTED
            params: {r_ohm, l_henry, c_farad} —— 可选，缺省 RLC_ANCHOR_DEFAULTS
            fstart_hz / fstop_hz / points_per_decade —— 可选
                                           （缺省 1e3/1e6/49，冒烟锚同源）
        """
        if not self._connected:
            return False
        template = str(geometry.get("template", "rlc_lowpass"))
        if template not in self.CAPABILITIES.supported_templates:
            self._last_error = (
                f"NOT_SUPPORTED: Xyce v0 仅支持 "
                f"{self.CAPABILITIES.supported_templates} 模板，收到 {template!r}"
                "（.HB 分析面登记未实现，见适配器 docstring）"
            )
            logger.error("%s", self._last_error)
            return False
        params = dict(geometry.get("params") or {})
        r = float(params.get("r_ohm", RLC_ANCHOR_DEFAULTS["r_ohm"]))
        lh = float(params.get("l_henry", RLC_ANCHOR_DEFAULTS["l_henry"]))
        cf = float(params.get("c_farad", RLC_ANCHOR_DEFAULTS["c_farad"]))
        fstart = float(geometry.get("fstart_hz", 1e3))
        fstop = float(geometry.get("fstop_hz", 1e6))
        ppd = int(geometry.get("points_per_decade", 49))
        try:
            text = render_rlc_ac_netlist(
                r, lh, cf, fstart_hz=fstart, fstop_hz=fstop, points_per_decade=ppd,
            )
        except ValueError as exc:
            self._last_error = f"rlc_lowpass 网表渲染失败: {exc}"
            logger.error("%s", self._last_error)
            return False
        workdir = Path(self._config.working_dir or ".")
        workdir.mkdir(parents=True, exist_ok=True)
        self._netlist_path = workdir / _NETLIST_NAME
        self._netlist_path.write_bytes(text.encode("ascii"))  # LF，零 CRLF 风险
        self._geometry = {
            "template": template,
            "params": {"r_ohm": r, "l_henry": lh, "c_farad": cf},
            "fstart_hz": fstart, "fstop_hz": fstop, "points_per_decade": ppd,
        }
        return True

    # ── 求解与解析 ──────────────────────────────────────────────────────────

    def solve(self, timeout_s: int = 600) -> EMSolverResult:
        """单激励电路求解（AC 对数扫频）→ 电压传函 H(f) + 传函 CSV 落盘。"""
        if not self._connected:
            return EMSolverResult(success=False, message="Not connected")
        if self._netlist_path is None or not self._netlist_path.exists():
            return EMSolverResult(success=False, message="build_geometry() 未生成网表")
        prn_path = prn_path_for(self._netlist_path, ac=True)
        prn_path.unlink(missing_ok=True)  # 防陈旧产物混入（真跑复用目录口径）
        timeout = float(timeout_s) if timeout_s else self._run_timeout_s
        try:
            run = run_xyce(
                self._netlist_path, spec=self._spec, timeout_s=timeout,
            )
        except (XyceError, ValueError, OSError) as exc:
            return EMSolverResult(success=False, message=f"Xyce 启动失败: {exc}")
        err_tail = "; ".join(
            ln.strip() for ln in run.stderr.splitlines() if ln.strip()
        )[-300:]
        if run.timed_out:
            return EMSolverResult(
                success=False, wall_time_s=run.wall_time_s,
                message=f"Xyce 求解超时（>{timeout}s）: {err_tail}",
            )
        if run.rc != 0 or not prn_path.is_file():
            return EMSolverResult(
                success=False, wall_time_s=run.wall_time_s,
                message=f"Xyce 运行失败（rc={run.rc}）: {err_tail or run.stdout[-300:]}",
            )
        try:
            parsed = read_prn(prn_path)
        except XyceError as exc:
            return EMSolverResult(success=False, wall_time_s=run.wall_time_s,
                                  message=f"Xyce prn 解析失败: {exc}")
        if parsed["indep"] is None or parsed["indep"].upper() != "FREQ":
            return EMSolverResult(
                success=False, wall_time_s=run.wall_time_s,
                message=f"prn 缺 FREQ 自变量列（indep={parsed['indep']!r}）",
            )
        if not parsed["vars"]:
            return EMSolverResult(success=False, wall_time_s=run.wall_time_s,
                                  message="prn 无打印变量列")
        var = parsed["vars"][0]
        h = np.asarray(parsed["data"][var], dtype=complex)
        freq_hz = np.asarray(parsed["data"][parsed["indep"]].real, dtype=float)
        self._write_products(Path(self._config.working_dir or "."), freq_hz, h)
        n = len(freq_hz)
        p = self._geometry.get("params", {})
        message = (
            f"Xyce solve ok（{n} 点 AC 电压传函 H=V(out)/V1，非 S 参数；"
            f"engine={xyce_version(self._spec) or 'unknown'}）"
        )
        return EMSolverResult(
            success=True,
            freq_ghz=freq_hz / 1e9,
            s_params=None,
            field_data={
                "transfer_h": h,
                "freq_hz": freq_hz,
                "template": self._geometry.get("template", "rlc_lowpass"),
                "params": dict(p),
                "print_var": var,
            },
            wall_time_s=run.wall_time_s,
            message=message,
        )

    def _write_products(self, workdir: Path, freq_hz: np.ndarray,
                        h: np.ndarray) -> None:
        """落盘传函 CSV（观测性 #105：写失败仅告警，不回滚内存结果）。"""
        with open(workdir / _TRANSFER_CSV_NAME, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(_TRANSFER_CSV_HEADER)
            with np.errstate(divide="ignore"):
                db = 20.0 * np.log10(np.abs(h))
            for i in range(len(freq_hz)):
                w.writerow([freq_hz[i], h[i].real, h[i].imag, db[i]])

    def get_sparams(self) -> tuple[Any, Any] | None:
        """v0 无 S 参数产物（电压传函非 S 参数，如实 None 不虚报）。"""
        return None

    def close(self) -> None:
        self._connected = False
        self._netlist_path = None
        self._geometry = {}

    # ── 6g 产物视图协议 ────────────────────────────────────────────────────

    def visualizations(self) -> list[dict[str, Any]]:
        workdir = self._config.working_dir or "."
        return [
            {"kind": "circuit", "spec": {"file": str(Path(workdir) / _NETLIST_NAME),
                                         "format": "spice-xyce"}},
            {"kind": "sparams", "spec": {"file": str(Path(workdir) / _TRANSFER_CSV_NAME)}},
        ]

    def supported_output_formats(self) -> list[str]:
        return ["csv"]


# --------------------------------------------------------------------------- #
# 注册（qucsator 同款：枚举键存在才注册全局——宁缺不脏；导入即注册不阻塞）
# --------------------------------------------------------------------------- #


def _resolve_solver_type_key() -> Any:
    """解析注册键：EMSolverType.XYCE（已合入）或 None（未合入）。"""
    from rfauto.adapters.em_solver_base import EMSolverType
    return getattr(EMSolverType, "XYCE", None)


def register_xyce(registry: Any = None, *, type_key: Any = None) -> bool:
    """注册到全局/指定 EMSolverRegistry（键缺失且未显式传 type_key 时跳过
    → False，不抛错不污染全局注册表——观测性 #105 + #362 注册表面纪律）。"""
    from rfauto.adapters.em_solver_base import EMSolverRegistry, get_global_registry
    target = registry if isinstance(registry, EMSolverRegistry) else get_global_registry()
    key = type_key if type_key is not None else _resolve_solver_type_key()
    if key is None:
        logger.debug("xyce 注册跳过：EMSolverType.XYCE 尚未合入（注册 hunk 待应用）")
        return False
    target.register(key, XyceAdapter)
    return True


"""Register on import (same pattern as qucsator/vna; never blocks import)."""
with contextlib.suppress(Exception):
    register_xyce()
