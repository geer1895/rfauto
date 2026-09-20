"""SPICE 网表渲染/运行/解析（ngspice 真机参考链 + Xyce 可用性探测）。

A3（场-路协同，验收列"对照 ngspice 参考解"）的执行器：

- 把谐波平衡锚的**同一物理电路**（R/L/C/二极管/单音源，core.circuit_hb
 元件数据类为容器）渲染为 ngspice 瞬态网表（.tran + .meas AVG + .four）；
- 子进程批处理运行（``ngspice_con -b``，标准 SPICE 命令行，无 GUI）；
- 解析 stdout 的 Fourier 表与 Measurements 行为结构化数据，供 linkage 层
 与 core.circuit_hb 的 HB 解对拍。

ngspice 口径标定（ngspice-47 本机实测）：
- ``.four`` Magnitude 列 = 谐波**峰值**幅度（1V 正弦经 50/50 分压报 0.5）；
- 相位以**正弦**为 0° 参考（1V 正弦报 0°，即余弦参考相位 +90°）；
- 分析窗 = 瞬态数据的最后 ``No. Periods`` 个周期（Gridsize 缺省 200）；
- 环境无 ngspice 时 ``.four`` 输出 "Error: ... No transient data"——本模块
 将含 "Error"/"failed" 的行收集进 ``errors``，由调用方判定，不静默。

.AC S 参数通道标定（D13 第三方交叉验证；ngspice-47 本机实测）：
- ``wrdata`` 在 AC 分析下每个请求向量写**三列**（freq, real, imag），空格
 分隔、无表头；``set numdgt=15`` 后数值 15 位有效数字；
- 任意频轴在 .control 内**逐频字面量** ``ac lin 1 <f> <f>`` + ``wrdata``
 追加（``set appendwrite``）——不用 compose/$& 向量展开：$& 字符串化走 %g
 仅 6 位有效数字，实测把 1.390625GHz 量化成 1.39062GHz 造成 3.6ppm 频轴
 漂移；字面量路径频轴逐点精确（rel=0）；
- V 源分支电流方向 = 标准 SPICE 约定（从 n+ 经源流向 n-），故逐端口激励
 提取 ``Y[i, j] = -i(v_i)``（j 为激励端口）——与 core.macromodel
 ``_mna_ac_s`` 的端口电流口径（流入网络为正）精确互证（串联 R-L 闭式
 Y=(1/Z)[[1,-1],[-1,1]] 逐点吻合）；
- Y→S 数学与 core.macromodel ``replay_spice_subcircuit_s`` 同口径
 （S = D⁻¹(I−Z₀Y)(I+Z₀Y)⁻¹D），端口布局/z0 推断复用
 ``core.macromodel.spice_subcircuit_port_info``（同一解析器，单源真值）。

Xyce 通道：本机无 Xyce 二进制（GitHub Release 仅源码与说明，无 Windows
安装产物），只提供 :func:`resolve_xyce_exe`/:func:`xyce_available` 探测钩子；
**渲染器不实现**——Xyce 网表语法（Ylin 等）须对照 Xyce Reference Guide
后补，禁止凭想象写 API（#215 纪律，同 COMSOL）。

分层：adapters，可 import core（元件数据类）；供 linkage 编排调用。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import numpy as np

from rfauto.core.circuit_hb import (
  HBCapacitor,
  HBCircuit,
  HBDiode,
  HBInductor,
  HBResistor,
  HBVSource,
)
from rfauto.core.macromodel import compare_s_matrices, spice_subcircuit_port_info

#: 工作区随带 ngspice 的缺省位置（tools/ngspice；不存在时回落 PATH 探测）。
_WORKSPACE_NGSPICE = Path(__file__).resolve().parents[3] / "tools" / "ngspice" / (
  "Spice64/bin"
)

_NGSPICE_EXE_CANDIDATES = ("ngspice_con.exe", "ngspice_con", "ngspice.exe", "ngspice")
_XYCE_EXE_CANDIDATES = ("Xyce.exe", "Xyce", "xyce.exe", "xyce")


# --------------------------------------------------------------------------- #
# 可执行文件解析
# --------------------------------------------------------------------------- #

def _exe_from_dir(directory: Path) -> Path | None:
  for name in _NGSPICE_EXE_CANDIDATES:
    cand = directory / name
    if cand.is_file():
      return cand
  return None


def resolve_ngspice_exe(explicit: str | Path | None = None) -> Path:
  """解析 ngspice 可执行文件：显式参数 → ``RFAUTO_NGSPICE_BIN``（exe 或
  目录）→ 工作区 ``tools/ngspice`` → PATH。

  全部落空抛 FileNotFoundError（附配置指引；锚是裁判，不静默降级）。
  """
  candidates: list[Path] = []
  if explicit is not None:
    candidates.append(Path(explicit))
  env = os.environ.get("RFAUTO_NGSPICE_BIN", "")
  if env:
    candidates.append(Path(env))
  candidates.append(_WORKSPACE_NGSPICE)
  for cand in candidates:
    if cand.is_dir():
      exe = _exe_from_dir(cand)
      if exe is not None:
        return exe
    elif cand.is_file():
      return cand
  for name in _NGSPICE_EXE_CANDIDATES:
    found = shutil.which(name)
    if found:
      return Path(found)
  raise FileNotFoundError(
    "未找到 ngspice 可执行文件；可设 RFAUTO_NGSPICE_BIN 指向 ngspice_con.exe "
    "或其所在目录（工作区随带: tools/ngspice/Spice64/bin）"
  )


def ngspice_available(explicit: str | Path | None = None) -> bool:
  """ngspice 是否可用（best-effort，永不抛错——观测性 #105 纪律）。"""
  try:
    return resolve_ngspice_exe(explicit).is_file()
  except Exception:
    return False


def resolve_xyce_exe(explicit: str | Path | None = None) -> Path:
  """解析 Xyce 可执行文件：显式参数 → ``RFAUTO_XYCE_BIN`` → PATH。

  落空抛 FileNotFoundError。本机当前无 Xyce 安装（探测钩子为 A3 的
  可替换组件留位；渲染器待 Xyce Reference Guide 对照后补，见模块 docstring）。
  """
  candidates: list[Path] = []
  if explicit is not None:
    candidates.append(Path(explicit))
  env = os.environ.get("RFAUTO_XYCE_BIN", "")
  if env:
    candidates.append(Path(env))
  for cand in candidates:
    if cand.is_dir():
      for name in _XYCE_EXE_CANDIDATES:
        if (cand / name).is_file():
          return cand / name
    elif cand.is_file():
      return cand
  for name in _XYCE_EXE_CANDIDATES:
    found = shutil.which(name)
    if found:
      return Path(found)
  raise FileNotFoundError(
    "未找到 Xyce 可执行文件；可设 RFAUTO_XYCE_BIN 指向 Xyce.exe 或其所在目录"
  )


def xyce_available(explicit: str | Path | None = None) -> bool:
  """Xyce 是否可用（best-effort，永不抛错）。"""
  try:
    return resolve_xyce_exe(explicit).is_file()
  except Exception:
    return False


# --------------------------------------------------------------------------- #
# 网表渲染（同一物理电路 → ngspice 瞬态）
# --------------------------------------------------------------------------- #

def _num(value: float) -> str:
  """SPICE 数值字面量（纯指数形式，规避单位后缀解析歧义）。"""
  v = float(value)
  if v == 0.0:
    v = 0.0 # 归一 −0.0（相位→TD 换算会产生 −0）
  return f"{v:.12g}"


def render_ngspice_netlist(
  circuit: HBCircuit,
  output_path: str | Path,
  node_names: list[str],
  *,
  tstop_s: float,
  tmax_s: float,
  tstep_s: float | None = None,
  tstart_s: float = 0.0,
  method: str = "gear",
  four_nodes: list[str] | None = None,
  meas_avg: dict[str, str] | None = None,
  meas_from_s: float | None = None,
  title: str = "rfauto A3 field-circuit nonlinear reference",
) -> Path:
  """渲染 ngspice 瞬态网表（.tran + .meas AVG + .four）。

  Args:
    circuit: 物理电路（仅支持 R/L/C/二极管/单音电压源；含 HBEmNPort
      时报错——ngspice 无通用 N 端口 Y 器件，参考链以物理等效 RLC
      渲染，等价性由 linkage 单测钉死）。
    node_names: 节点号 → 网表节点名（下标 0 应为 "0"=地）。
    tstop_s/tmax_s/tstart_s: 瞬态终时/最大步长/起存时刻。
    tstep_s: 打印步长（缺省 tmax_s）。
    method: 数值积分法（"gear"——检波器类锐脉冲电路无梯形振铃）。
    four_nodes: 做 .four 的节点名清单（缺省全部非地节点）。
    meas_avg: {输出名: 节点名} 的 AVG 测量（``.meas tran <名> AVG v(<节点>)``）。
    meas_from_s: AVG 测量窗口起点（缺省 tstop/2——须为周期整数倍，
      由调用方保证稳态）。

  Returns:
    网表路径。
  """
  if node_names[0] != "0":
    raise ValueError("node_names[0] 必须是 '0'（地）")
  name_of = {i: nm for i, nm in enumerate(node_names)}
  lines: list[str] = [f"* {title}"]
  lines.append(".options reltol=1e-4 abstol=1e-12 vntol=1e-9")
  diode_models: list[str] = []
  elem_count: dict[str, int] = {}

  def _prefix(p: str) -> str:
    elem_count[p] = elem_count.get(p, 0) + 1
    return f"{p}{elem_count[p]}"

  for el in circuit.elements:
    if isinstance(el, HBVSource):
      # SIN(VO VA FREQ TD)：VO=直流偏置（TRAN 中由 SIN 主导）；
      # TD 由余弦参考相位换算：sin(ω(t−TD)) 的余弦相位 = −ω·TD − 90°
      td_s = -((el.phase_deg + 90.0) / 360.0) / circuit.f0_hz
      lines.append(
        f"{_prefix('V')} {name_of[el.node_plus]} {name_of[el.node_minus]} "
        f"DC {_num(el.dc)} SIN(0 {_num(el.amp)} {_num(circuit.f0_hz)} {_num(td_s)})"
      )
    elif isinstance(el, HBResistor):
      lines.append(
        f"{_prefix('R')} {name_of[el.node_a]} {name_of[el.node_b]} {_num(el.resistance)}"
      )
    elif isinstance(el, HBCapacitor):
      lines.append(
        f"{_prefix('C')} {name_of[el.node_a]} {name_of[el.node_b]} {_num(el.capacitance)}"
      )
    elif isinstance(el, HBInductor):
      lines.append(
        f"{_prefix('L')} {name_of[el.node_a]} {name_of[el.node_b]} {_num(el.inductance)}"
      )
    elif isinstance(el, HBDiode):
      model_name = f"DMOD{len(diode_models) + 1}"
      diode_models.append(
        f".model {model_name} D(Is={_num(el.is_sat)} N={_num(el.emission_n)})"
      )
      lines.append(
        f"{_prefix('D')} {name_of[el.node_anode]} {name_of[el.node_cathode]} {model_name}"
      )
    else:
      raise TypeError(
        f"ngspice 参考网表不支持元件 {type(el).__name__}"
        "（EM N 端口以物理等效 RLC 渲染，见模块 docstring）"
      )
  lines.extend(diode_models)
  tstep = tstep_s if tstep_s is not None else tmax_s
  lines.append(
    f".tran {_num(tstep)} {_num(tstop_s)} {_num(tstart_s)} {_num(tmax_s)}"
  )
  if meas_avg:
    win_from = meas_from_s if meas_from_s is not None else tstop_s / 2.0
    for meas_name, node in meas_avg.items():
      lines.append(
        f".meas tran {meas_name} AVG v({node}) from={_num(win_from)} to={_num(tstop_s)}"
      )
  if four_nodes is None:
    four_nodes = [nm for nm in node_names[1:]]
  if four_nodes:
    spec = " ".join(f"v({nm})" for nm in four_nodes)
    lines.append(f".four {_num(circuit.f0_hz)} {spec}")
  lines.append(".end")
  out = Path(output_path)
  out.parent.mkdir(parents=True, exist_ok=True)
  out.write_text("\n".join(lines) + "\n", encoding="ascii")
  return out


# --------------------------------------------------------------------------- #
# 运行与解析
# --------------------------------------------------------------------------- #

def run_ngspice(
  netlist_path: str | Path,
  *,
  exe: str | Path | None = None,
  timeout_s: float = 300.0,
) -> dict[str, Any]:
  """批处理运行 ngspice（``-b``），返回 {stdout, stderr, returncode, errors}。

  ``errors`` = stdout/stderr 中含 Error/failed/warning 级关键字的行
  （ngspice 电路错误常伴随 rc=0，rc 不足为凭——.four 失败实测只打印
  "Error: ... No transient data"，须显式收集）。
  """
  exe_path = resolve_ngspice_exe(exe)
  netlist_path = Path(netlist_path)
  proc = subprocess.run(
    [str(exe_path), "-b", str(netlist_path)],
    capture_output=True,
    text=True,
    timeout=timeout_s,
    cwd=str(netlist_path.parent),
    check=False,
  )
  flag_lines = [
    ln.strip()
    for ln in (proc.stdout + "\n" + proc.stderr).splitlines()
    if re.search(r"\b(Error|failed|warning)\b", ln, re.IGNORECASE)
  ]
  return {
    "stdout": proc.stdout,
    "stderr": proc.stderr,
    "returncode": int(proc.returncode),
    "errors": flag_lines,
  }


_FOUR_HEADER_RE = re.compile(r"Fourier analysis for (.+?):")
_MEAS_RE = re.compile(r"^(\S+)\s*=\s*([-+0-9.eE]+)\s+from=", re.MULTILINE)


def _parse_float(tok: str) -> float | None:
  try:
    return float(tok)
  except ValueError:
    return None


def parse_ngspice_output(stdout: str) -> dict[str, Any]:
  """解析 ngspice 批处理 stdout：.four 傅里叶表 + .meas 测量行。

  返回::

    {
     "fourier": {signal: {"dc": float, "harmonics": {k: {
        "frequency_hz": float, "magnitude": float, "phase_deg": float}}}},
     "meas": {name: float},
    }

  ``signal`` 为 .four 目标 ``v(<node>)`` 的节点名；Magnitude 为谐波峰值
  幅度、phase 为正弦参考口径（见模块 docstring 标定）。
  """
  fourier: dict[str, dict[str, Any]] = {}
  current: str | None = None
  in_table = False
  for raw in stdout.splitlines():
    line = raw.strip()
    m = _FOUR_HEADER_RE.search(line)
    if m:
      inner = m.group(1).strip()
      if inner.startswith("v(") and inner.endswith(")"):
        inner = inner[2:-1]
      current = inner
      fourier[current] = {"dc": None, "harmonics": {}}
      in_table = False
      continue
    if current is None:
      continue
    if line.startswith("Harmonic") and "Magnitude" in line:
      in_table = True
      continue
    if not in_table or not line:
      continue
    fields = line.split()
    if len(fields) < 4:
      continue
    if not fields[0].isdigit():
      continue
    freq = _parse_float(fields[1])
    mag = _parse_float(fields[2])
    phase = _parse_float(fields[3])
    if mag is None:
      continue
    idx = int(fields[0])
    if idx == 0:
      fourier[current]["dc"] = mag
      continue
    fourier[current]["harmonics"][idx] = {
      "frequency_hz": float(freq or 0.0),
      "magnitude": mag,
      "phase_deg": float(phase or 0.0),
    }
  meas = {m.group(1): float(m.group(2)) for m in _MEAS_RE.finditer(stdout)}
  return {"fourier": fourier, "meas": meas}


def ngspice_phase_to_cosine(phase_deg_sin_ref: float) -> float:
  """ngspice 相位（正弦参考）→ 余弦参考相位（度，wrap 到 (−180, 180]）。

  标定依据（ngspice-47 实测）：1V 正弦源 .four 报 phase=0°，而余弦参考
  下正弦的相位是 −90°——ngspice 相位比余弦参考大 90°，故减 90° 还原。
  """
  return float((phase_deg_sin_ref - 90.0 + 180.0) % 360.0 - 180.0)


def transient_plan_for(
  f0_hz: float, *, n_periods_total: int = 2000, n_periods_meas: int = 500,
  samples_per_period_max: float = 400.0,
) -> dict[str, float]:
  """按周期数规划瞬态（tstop/tmax/AVG 窗口），保证 meas 窗口为整周期。

  tmax ≈ 周期/``samples_per_period_max``（1GHz → 2.5ps）；AVG 窗口
  [tstop − n_meas·T, tstop] 为整周期数（DC 均值无整周期偏置）。
  """
  period = 1.0 / f0_hz
  tstop = n_periods_total * period
  t_from = (n_periods_total - n_periods_meas) * period
  tmax = period / samples_per_period_max
  return {
    "tstop_s": tstop,
    "tstart_s": 0.0,
    "tmax_s": tmax,
    "meas_from_s": t_from,
  }


# --------------------------------------------------------------------------- #
# .AC S 参数通道（D13 第三方交叉验证；core 禁 import adapters，编排在 adapters）
# --------------------------------------------------------------------------- #

class NgspiceAcError(RuntimeError):
  """ngspice .AC S 参数通道执行失败（渲染/运行/解析任一环节，显式不静默）。"""


#: .AC wrdata 输出精度（manual: numdgt>6 走 %.15e 格式；实测 15 位）。
_AC_NUMDGT = 15
#: ngspice-47 二端电阻**硬下限**（真机实测：|R|<1e-12Ω 被钳位到 1e-12 并打
#: "Warning: Value of resistor ... is too small, set to 1.000000e-12"，手册无可配置
#: 选项）。skrf 状态空间综合的泄漏电阻 Rp=1/|Re(pole)| 对远带外实极点可低至
#: 1e-24Ω，钳位后该状态贡献放大 ~1e11 倍→S 矩阵垃圾（1 端口 RLC 实测
#: max|ΔS|=3.9e10）。对策 = 改写为自控 VCCS（MNA 戳完全等价，core 回放实证
#: max|ΔS|=0.0；ngspice 对 3e22 S 跨导无钳位），见 rewrite_subfloor_resistors。
NGSPICE_RESISTOR_FLOOR_OHM = 1e-12
#: xval 段的 verifier 标识（与回放自检的 "replay_selfcheck" 区分两条证据链）。
XVAL_VERIFIER_NGSPICE_AC = "third_party_ngspice_ac"
#: xval 定性声明（防把第三方对拍与回放自检混为一谈）。
_XVAL_NOTE = (
  "第三方 ngspice .AC 交叉验证（third-party xval）：导出子电路经 .INCLUDE 进外层 deck，"
  "逐端口 1V AC 激励真跑 ngspice（.control 内逐频 ac lin 1 f f + wrdata 复数落盘），"
  "按 Y[i,j]=-i(v_i)（ngspice-47 真机标定）装配 Y 矩阵并转 S，与参考 S 参数做 FSV"
  "（D12 内核）评级。它与 core.macromodel 的『回放自检』（纯 Python MNA）是两条独立"
  "证据链；|R|<1e-12Ω 的电阻按 MNA 等价改写为自控 VCCS 以规避 ngspice 硬下限钳位"
  "（改写清单随结果返回）；Xyce 无本机二进制，维持探测钩子不实现渲染器（#215）。"
)


def rewrite_subfloor_resistors(
  text: str, *, floor_ohm: float = NGSPICE_RESISTOR_FLOOR_OHM
) -> tuple[str, list[dict[str, Any]]]:
  """把 ``|R| < floor_ohm`` 的简单二端电阻行改写为自控 VCCS（``G a b a b 1/R``）。

  电阻的 MNA 导纳戳与 "电流 a→b = (1/R)·(V(a)−V(b))" 的 VCCS 戳逐元相同，
  故改写在电路语义上**完全等价**（core.macromodel 回放实证 max|ΔS|=0.0），
  仅规避 ngspice 的电阻硬下限钳位（见 NGSPICE_RESISTOR_FLOOR_OHM）。只处理
  ``Rname a b <纯浮点>`` 四令牌行（skrf 导出格式）；其余行原样保留。返回
  (新文本, 改写清单 [{name, nodes, value_ohm, replaced_by}])。
  """
  out: list[str] = []
  items: list[dict[str, Any]] = []
  for line in text.splitlines():
    tokens = line.split()
    if len(tokens) == 4 and tokens[0] and tokens[0][0].upper() == "R" and not line.lstrip().startswith("*"):
      try:
        val = float(tokens[3])
      except ValueError:
        out.append(line)
        continue
      if val != 0.0 and abs(val) < float(floor_ohm):
        a, b = tokens[1], tokens[2]
        new_name = f"Grw_{tokens[0]}"
        out.append(f"{new_name} {a} {b} {a} {b} {1.0 / val:.17g}")
        items.append({"name": tokens[0], "nodes": [a, b], "value_ohm": val, "replaced_by": new_name})
        continue
    out.append(line)
  return "\n".join(out) + "\n", items


def render_ngspice_ac_sparam_deck(
  output_path: str | Path,
  *,
  subckt_include: str,
  subckt_name: str,
  pins: list[str],
  port_nodes: list[str],
  ref_nodes: list[str | None],
  freq_hz: Any,
  excited_port: int,
  wrdata_name: str,
  title: str = "rfauto D13 third-party SPICE .AC xval",
) -> Path:
  """渲染第三方 .AC 对拍外层 deck（单端口激励；每端口一个 deck 一次运行）。

  结构（ngspice-47 真机标定，见模块 docstring）：.INCLUDE 子电路 → X1 实例
  （节点序 = 子电路 pin 序）→ 逐端口 1V/0V AC 源（激励端口 AC 1，其余 AC 0
  =理想短路）→ .control 内 ``set numdgt=15`` + **逐频字面量**
  ``ac lin 1 <f> <f>`` + ``wrdata`` 追加（%.17g 字面量直写 deck——不用
  compose/$& 向量展开：$& 字符串化走 %g 仅 6 位有效数字，实测把
  1.390625GHz 量化成 1.39062GHz 造成 3.6ppm 频轴漂移；字面量路径频轴
  逐点精确 rel=0）。
  """
  if not 0 <= int(excited_port) < len(port_nodes):
    raise NgspiceAcError(f"excited_port={excited_port} 超出端口范围 [0, {len(port_nodes)})")
  freq = np.asarray(freq_hz, dtype=float).ravel()
  if freq.size == 0 or not np.all(np.isfinite(freq)) or np.any(freq <= 0.0):
    raise NgspiceAcError("freq_hz 必须为非空、有限且 > 0 Hz 的数组")
  # 实例节点序 = 子电路 pin 序（deck 节点名直接沿用 pin 名，命名空间独立）
  x_nodes = " ".join(pins)
  lines: list[str] = [f"* {title}", f".include {subckt_include}", f"X1 {x_nodes} {subckt_name}"]
  for i, (pn, rn) in enumerate(zip(port_nodes, ref_nodes, strict=True)):
    ref = rn if rn is not None else "0"
    mag = "1" if i == int(excited_port) else "0"
    lines.append(f"V{i + 1} {pn} {ref} AC {mag}")
  i_vecs = " ".join(f"i(v{i + 1})" for i in range(len(port_nodes)))
  lines.extend([
    ".control",
    f"set numdgt={_AC_NUMDGT}",
    "set appendwrite",
  ])
  for v in freq:
    fv = f"{float(v):.17g}"
    lines.append(f" ac lin 1 {fv} {fv}")
    lines.append(f" wrdata {wrdata_name} {i_vecs}")
  lines.extend([
    "quit",
    ".endc",
    ".end",
    "",
  ])
  out = Path(output_path)
  out.parent.mkdir(parents=True, exist_ok=True)
  out.write_text("\n".join(lines), encoding="ascii")
  return out


def parse_ngspice_wrdata_ac(text: str, *, n_vectors: int | None = None) -> tuple[np.ndarray, np.ndarray]:
  """解析 ngspice ``wrdata`` 的 AC 复数输出 → (freq[nf], values[n_vec, nf])。

  格式（ngspice-47 实测标定）：每行 = 每个请求向量三列 (freq, real, imag)，
  空格分隔、无表头；行内各三列的 freq 列必须一致（不一致=文件损坏，显式报错）。
  """
  rows: list[list[float]] = []
  for raw in text.splitlines():
    line = raw.strip()
    if not line:
      continue
    try:
      rows.append([float(tok) for tok in line.split()])
    except ValueError as exc:
      raise NgspiceAcError(f"wrdata 行含非数值令牌: {raw!r} ({exc})") from exc
  if not rows:
    raise NgspiceAcError("wrdata 输出为空（ngspice 未产出数据或被 error 中断）")
  n_cols = len(rows[0])
  if n_cols == 0 or n_cols % 3 != 0:
    raise NgspiceAcError(f"wrdata 列数 {n_cols} 不是 3 的倍数（AC 复数输出每向量 3 列）")
  n_vec = n_cols // 3
  if n_vectors is not None and n_vec != int(n_vectors):
    raise NgspiceAcError(f"wrdata 向量数 {n_vec} != 期望 {n_vectors}")
  freq = np.zeros(len(rows), dtype=float)
  vals = np.zeros((n_vec, len(rows)), dtype=complex)
  for r, row in enumerate(rows):
    if len(row) != n_cols:
      raise NgspiceAcError(f"wrdata 第 {r + 1} 行列数 {len(row)} != 首行 {n_cols}")
    for v in range(n_vec):
      f_v, re_v, im_v = row[3 * v : 3 * v + 3]
      if v == 0:
        freq[r] = f_v
      elif f_v != freq[r]:
        raise NgspiceAcError(
          f"wrdata 第 {r + 1} 行第 {v + 1} 向量频率列 {f_v} 与首向量 {freq[r]} 不一致"
        )
      vals[v, r] = complex(re_v, im_v)
  return freq, vals


def _y_to_s_same_as_replay(y: np.ndarray, z0_list: list[float]) -> np.ndarray:
  """Y→S 转换（与 core.macromodel ``_mna_ac_s`` 末段同一公式/口径）：
  S = D⁻¹(I−Z₀Y)(I+Z₀Y)⁻¹D，D=diag(√z₀)。"""
  z0_arr = np.asarray(z0_list, dtype=float)
  d_root = np.sqrt(z0_arr)
  z0d = np.diag(z0_arr)
  ident = np.eye(y.shape[-1])
  s_out = np.zeros_like(y)
  for k in range(y.shape[0]):
    x = np.linalg.solve((ident + z0d @ y[k]).T, (ident - z0d @ y[k]).T).T
    s_out[k] = x * (d_root[None, :] / d_root[:, None])
  return s_out


def _ngspice_version(exe: str | Path) -> str | None:
  """ngspice 版本串（best-effort，#105：观测性不得阻塞主路径）。"""
  try:
    proc = subprocess.run(
      [str(exe), "--version"], capture_output=True, text=True, timeout=30.0, check=False
    )
    m = re.search(r"ngspice-\d+", proc.stdout + proc.stderr)
    return m.group(0) if m else None
  except Exception:
    return None


def run_ngspice_ac_sparam(
  subckt_path: str | Path,
  freq_hz: Any,
  z0: Any = None,
  *,
  work_dir: str | Path,
  exe: str | Path | None = None,
  timeout_s: float = 300.0,
  rewrite_small_resistors: bool = True,
  resistor_floor_ohm: float = NGSPICE_RESISTOR_FLOOR_OHM,
) -> dict[str, Any]:
  """第三方 ngspice .AC 重建子电路 S 矩阵（逐端口激励；**真机对拍通道**）。

  子电路端口布局/参考阻抗与回放自检同口径
  （``core.macromodel.spice_subcircuit_port_info``）；子电路复制进
  ``work_dir``（缺省把 |R|<``resistor_floor_ohm`` 的电阻做 MNA 等价 VCCS
  改写以规避 ngspice 硬下限钳位，清单随 ``resistor_rewrite`` 返回）后逐端口
  渲染 deck → ``run_ngspice`` 真跑 → wrdata 复数解析 →
  ``Y[i, j] = -i(v_i)``（ngspice-47 真机标定的符号约定）装配 [nf, n, n] Y →
  转 S。任一环节失败抛 :class:`NgspiceAcError`（不静默；best-effort 包装见
  :func:`xval_macromodel_spice`）。

  返回 dict：``status``/``tool``/``subckt_name``/``n_ports``/``port_nodes``/
  ``ref_nodes``/``z0_ohm``/``z0_source``/``freq_hz``/``y``/``s``（复数
  ndarray）/``runs``（逐端口 deck/wrdata/returncode/错误行）/
  ``resistor_rewrite``/``work_dir``/``subckt_copy``/``note``。
  """
  sub = Path(subckt_path)
  if not sub.is_file():
    raise NgspiceAcError(f"子电路文件不存在: {sub}")
  wd = Path(work_dir)
  wd.mkdir(parents=True, exist_ok=True)
  freq = np.asarray(freq_hz, dtype=float).ravel()
  if freq.size == 0 or not np.all(np.isfinite(freq)) or np.any(freq <= 0.0):
    raise NgspiceAcError("freq_hz 必须为非空、有限且 > 0 Hz 的数组")

  info = spice_subcircuit_port_info(sub, z0) # 端口布局/z0 与回放自检同口径（非法网表显式报错）
  exe_path = resolve_ngspice_exe(exe)
  n_ports = int(info["n_ports"])
  sub_copy = wd / "dut.sp"
  if rewrite_small_resistors:
    rewritten, rw_items = rewrite_subfloor_resistors(
      sub.read_text(encoding="utf-8", errors="replace"), floor_ohm=resistor_floor_ohm
    )
    sub_copy.write_text(rewritten, encoding="utf-8")
  else:
    rw_items = []
    shutil.copyfile(sub, sub_copy)
  resistor_rewrite = {
    "enabled": bool(rewrite_small_resistors),
    "floor_ohm": float(resistor_floor_ohm),
    "n_rewritten": len(rw_items),
    "items": rw_items,
  }

  y = np.zeros((int(freq.size), n_ports, n_ports), dtype=complex)
  runs: list[dict[str, Any]] = []
  for j in range(n_ports):
    deck = wd / f"xval_port{j + 1}.cir"
    wrdata_name = f"xval_port{j + 1}.data"
    wrdata_path = wd / wrdata_name
    wrdata_path.unlink(missing_ok=True) # appendwrite 模式：先清陈旧数据防串档
    render_ngspice_ac_sparam_deck(
      deck,
      subckt_include="dut.sp",
      subckt_name=str(info["subckt_name"]),
      pins=list(info["pins"]),
      port_nodes=list(info["port_nodes"]),
      ref_nodes=list(info["ref_nodes"]),
      freq_hz=freq,
      excited_port=j,
      wrdata_name=wrdata_name,
    )
    res = run_ngspice(deck, exe=exe_path, timeout_s=timeout_s)
    fatal = [ln for ln in res["errors"] if re.search(r"\b(Error|failed)\b", ln, re.IGNORECASE)]
    runs.append({
      "port": j + 1,
      "deck": str(deck),
      "wrdata": str(wrdata_path),
      "returncode": int(res["returncode"]),
      "errors": res["errors"],
    })
    if res["returncode"] != 0 or fatal:
      raise NgspiceAcError(
        f"ngspice .AC 运行失败（端口 {j + 1}，rc={res['returncode']}）：{fatal or res['errors']}"
      )
    if not wrdata_path.is_file():
      raise NgspiceAcError(f"ngspice 未产出 wrdata 文件: {wrdata_path}")
    text = wrdata_path.read_text(encoding="ascii", errors="replace")
    freq_out, vals = parse_ngspice_wrdata_ac(text, n_vectors=n_ports)
    if not np.allclose(freq_out, freq, rtol=1e-9, atol=0.0):
      rel_dev = float(np.max(np.abs(freq_out - freq) / freq))
      raise NgspiceAcError(f"wrdata 频率轴与请求轴不一致（max 相对偏差 {rel_dev:.3e}）")
    # Y[i, j] = -i(v_i)：激励端口 j，端口 i 流入网络电流 = 源支路电流取负
    # （ngspice-47 真机标定：串联 R-L 闭式 Y=(1/Z)[[1,-1],[-1,1]] 逐点互证）
    y[:, :, j] = -vals.T

  s = _y_to_s_same_as_replay(y, list(info["z0_ohm"]))
  return {
    "status": "ok",
    "tool": {"exe": str(exe_path), "version": _ngspice_version(exe_path)},
    "subckt_name": info["subckt_name"],
    "n_ports": n_ports,
    "port_nodes": list(info["port_nodes"]),
    "ref_nodes": list(info["ref_nodes"]),
    "z0_ohm": list(info["z0_ohm"]),
    "z0_source": info["z0_source"],
    "freq_hz": [float(x) for x in freq],
    "y": y,
    "s": s,
    "runs": runs,
    "resistor_rewrite": resistor_rewrite,
    "work_dir": str(wd),
    "subckt_copy": str(sub_copy),
    "note": _XVAL_NOTE,
  }


def xval_macromodel_spice(
  s_reference: Any,
  freq_hz: Any,
  subckt_path: str | Path,
  z0: Any = None,
  *,
  work_dir: str | Path,
  exe: str | Path | None = None,
  timeout_s: float = 300.0,
  rewrite_small_resistors: bool = True,
) -> dict[str, Any]:
  """第三方 SPICE 对拍（ngspice .AC）→ D12 FSV 评级（best-effort，不抛异常）。

  验收口径（冻结验收列）：
  "ngspice/Xyce 回放 vs 原 S 参数 FSV（D12）评级 ≥Good"。``s_reference``
  为原始 S 矩阵（复数 ndarray ``[nf, n, n]``）；对拍 S 由
  :func:`run_ngspice_ac_sparam` 真跑重建；FSV/误差摘要用
  ``core.macromodel.compare_s_matrices``（与 fit_macromodel.fsv 同口径）。

  失败语义（#105/#122：best-effort + 如实）：基础设施失败（无 ngspice、
  网表非法、运行/解析失败、FSV 频点不足）→ ``status="error"`` 且
  ``gdm_at_least_good=False``，绝不抛出、绝不伪造通过。
  """
  try:
    run = run_ngspice_ac_sparam(
      subckt_path, freq_hz, z0, work_dir=work_dir, exe=exe, timeout_s=timeout_s,
      rewrite_small_resistors=rewrite_small_resistors,
    )
    cmp = compare_s_matrices(run["freq_hz"], s_reference, run["s"])
  except Exception as exc: # best-effort 包装：失败如实上报给调用方判定
    return {
      "status": "error",
      "verifier": XVAL_VERIFIER_NGSPICE_AC,
      "error": f"{type(exc).__name__}: {exc}",
      "gdm_at_least_good": False,
      "note": _XVAL_NOTE,
    }
  return {
    "status": "ok",
    "verifier": XVAL_VERIFIER_NGSPICE_AC,
    "tool": run["tool"],
    "subckt_name": run["subckt_name"],
    "n_ports": run["n_ports"],
    "n_points": int(cmp["n_points"]),
    "z0_ohm": run["z0_ohm"],
    "z0_source": run["z0_source"],
    "fsv": cmp["fsv"],
    "xval_vs_reference": cmp["error"],
    "worst_gdm_grade": cmp["fsv"]["worst_gdm_grade"],
    "worst_response": cmp["fsv"]["worst_response"],
    "gdm_at_least_good": bool(cmp["fsv"]["gdm_at_least_good"]),
    "resistor_rewrite": run["resistor_rewrite"],
    "runs": run["runs"],
    "work_dir": run["work_dir"],
    "s": [
      [[[float(v.real), float(v.imag)] for v in row] for row in mat] for mat in run["s"]
    ],
    "note": _XVAL_NOTE,
  }
