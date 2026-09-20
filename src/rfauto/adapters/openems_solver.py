"""openEMS 求解器适配器（模块化实现）。

基于 thliebig/openEMS（FDTD 电磁求解器）。
GitHub: https://github.com/thliebig/openEMS

使用方式：
- 子进程调用 openEMS 命令行
- 生成 CSXCAD 脚本文件
- 解析 CSV 输出获取 S 参数
"""

from __future__ import annotations

import contextlib
import hashlib
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np

from rfauto.adapters.em_solver_base import (
  EMSolverAdapter,
  EMSolverConfig,
  EMSolverResult,
  EMSolverType,
  get_global_registry,
)


class OpenEMSSolver(EMSolverAdapter):
  """openEMS FDTD 求解器适配器。"""

  def __init__(self, config: EMSolverConfig):
    super().__init__(config)
    self._exe_path: str | None = config.exe_path
    self._working_dir: Path | None = None

  def connect(self) -> bool:
    """连接到 openEMS（检查可执行文件）。"""
    exe = self._exe_path or self._find_exe()
    if exe is None or not Path(exe).exists():
      return False
    self._exe_path = exe
    self._connected = True
    return True

  def is_available(self) -> bool:
    """检查 openEMS 是否可用。"""
    exe = self._exe_path or self._find_exe()
    return exe is not None and Path(exe).exists()

  def _find_exe(self) -> str | None:
    """查找 openEMS 可执行文件。"""
    import os
    import shutil

    bin_dir = os.environ.get("RFAUTO_OPENEMS_BIN")
    candidates = ["openEMS", "openEMS.exe"]
    if bin_dir:
      candidates.insert(0, str(Path(bin_dir) / "openEMS.exe"))
    candidates += [
      "E:/openEMS/install/bin/openEMS.exe",
      "C:/openEMS/openEMS.exe",
    ]
    for candidate in candidates:
      if shutil.which(candidate):
        return candidate
    # 检查直接路径
    for candidate in candidates:
      if Path(candidate).exists():
        return candidate
    return None

  def build_geometry(self, geometry: dict[str, Any]) -> bool:
    """构建几何模型（生成 CSXCAD 脚本）。

    Args:
      geometry: 几何描述，两种形态
        - 模板化（推荐）: {"template": "wilkinson"|"patch", "params": {...},
                 "substrate": {"er": 3.66, "h_mm": 0.508}(可选)}
        - 自定义: {"layer_stack":..., "traces":..., "ports":...}
         （无模板时生成占位脚本，几何部分留待模板补齐）
    """
    if not self._connected:
      return False

    # 创建工作目录
    self._working_dir = Path(self._config.working_dir or "runs/openems_temp")
    self._working_dir.mkdir(parents=True, exist_ok=True)

    # 生成 CSXCAD 脚本
    script = self._generate_csxcad_script(geometry)
    script_path = self._working_dir / "simulation.py"
    script_path.write_text(script, encoding="utf-8")

    return True

  def _generate_csxcad_script(self, geometry: dict[str, Any]) -> str:
    """生成 CSXCAD Python 脚本（模板化 or 占位）。"""
    from rfauto.adapters.openems_templates import render_script

    template = geometry.get("template")
    if template:
      return render_script(
        template,
        geometry.get("params", {}),
        self._config.freq_range_ghz,
        mesh_resolution_mm=self._config.mesh_resolution_mm,
        substrate=geometry.get("substrate"),
        far_field=bool(geometry.get("far_field", False)),
        sar=bool(geometry.get("sar", False)),
      )

    # 无模板：保留占位（原行为），明确失败点在绑定 import
    freq_min, freq_max = self._config.freq_range_ghz
    mesh_res = self._config.mesh_resolution_mm

    return f'''#!/usr/bin/env python3
"""openEMS 自动生成的仿真脚本（占位：无模板，需补齐几何）。"""
import sys

try:
  import CSXCAD # noqa: F401
  import openEMS # noqa: F401
except ImportError:
  print("ERROR: openEMS Python bindings not found")
  sys.exit(1)

# 仿真参数
freq_min = {freq_min}e9 # Hz
freq_max = {freq_max}e9 # Hz
mesh_res = {mesh_res}e-3 # m

raise SystemExit("rfauto: 自定义几何模板尚未接入，请使用 template=wilkinson|patch")
'''

  def solve(self) -> EMSolverResult:
    """执行 openEMS 仿真。

    提速：FDTD 主循环单核且每时间步强制刷 et 文件（I/O bound），
    真机一跑几十分钟。相同仿真脚本（模板+参数+网格+频段的全部组合）
    的结果逐位复用磁盘缓存——零精度损失，重跑从几十分钟到毫秒级。
    extra_params={"cache": False} 可关闭（如要验证无缓存行为）。
    """
    if not self._connected or self._working_dir is None:
      return EMSolverResult(success=False, message="未连接或未构建几何")

    script_path = self._working_dir / "simulation.py"
    if not script_path.exists():
      return EMSolverResult(success=False, message="仿真脚本不存在")

    cached = self._load_cached(script_path)
    if cached is not None:
      return cached

    # 绑定编译到其他 Python 时可在 configs/solvers.yaml extra_params.python_exe 指定
    python_exe = self._config.extra_params.get("python_exe") or sys.executable

    # 绑定扩展模块运行时依赖 install/bin 下的 CSXCAD.dll 等。Windows/Py3.8+
    # 单靠 PATH 不保证 .pyd 的 DLL 依赖解析，须经 os.add_dll_directory——
    # 用 runner 引导脚本注入，模板脚本保持纯净。
    runner_path = self._working_dir / "_rfauto_runner.py"
    if self._exe_path:
      exe_dir = str(Path(self._exe_path).resolve().parent)
      runner_path.write_text(
        "import os\n"
        "import runpy\n"
        "import sys\n"
        f"os.add_dll_directory({exe_dir!r})\n"
        f"os.environ['PATH'] = {exe_dir!r} + os.pathsep + os.environ.get('PATH', '')\n"
        "runpy.run_path(sys.argv[1], run_name='__main__')\n",
        encoding="utf-8",
      )

    try:
      cmd = [python_exe]
      if runner_path.exists():
        cmd += [str(runner_path.resolve()), str(script_path.resolve())]
      else:
        cmd.append(str(script_path.resolve()))
      # 默认 max_iterations*10；真实谐振结构（高 Q）跑满衰减可远超
      # 默认值，用 extra_params={"solve_timeout_s": ...} 放开
      timeout_s = self._config.extra_params.get(
        "solve_timeout_s", self._config.max_iterations * 10
      )
      result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout_s,
        cwd=str(self._working_dir.resolve()),
      )

      if result.returncode != 0:
        # 产物优先于退出码：绑定库在解释器退出段偶发非零退出，
        # 但 CSV 已完整落盘（实测）——解析成功即接受。
        parsed_early = self._parse_output()
        if parsed_early.success:
          self._store_cached(script_path, parsed_early)
          return parsed_early
        # 完整 stderr 落盘（#208 教训：多 run 轮转脚本失败在
        # 后段时，500 字符截断把真错误吞掉，只能整轮重跑归因）
        try:
          (self._working_dir / "_last_stderr.log").write_text(
            result.stderr or "", encoding="utf-8")
          (self._working_dir / "_last_stdout.log").write_text(
            result.stdout or "", encoding="utf-8")
        except Exception:
          pass # 诊断落盘失败不影响主错误路径
        tail = (result.stderr or "")[-4000:]
        return EMSolverResult(
          success=False,
          message=(f"openEMS 执行失败 (rc={result.returncode})，"
               f"完整日志: {self._working_dir / '_last_stderr.log'}\n"
               f"{tail}"),
        )

      # 解析输出
      parsed = self._parse_output()
      if parsed.success:
        self._store_cached(script_path, parsed)
      return parsed

    except subprocess.TimeoutExpired:
      return EMSolverResult(success=False, message="仿真超时")
    except Exception as e:
      return EMSolverResult(success=False, message=str(e))

  def _cache_dir(self) -> Path | None:
    """缓存目录；extra_params 显式关闭时返回 None。"""
    if not self._config.extra_params.get("cache", True):
      return None
    base = self._config.extra_params.get("cache_dir", "runs/openems_cache")
    return Path(base)

  # 缓存 schema 版本：条目格式/解析口径变化时递增，使旧缓存整体失效
  _CACHE_SCHEMA = "rfauto-openems-cache-v2"

  def _cache_key(self, script_path: Path) -> str:
    """缓存键 = 仿真脚本全文 + 引擎标识 + schema 版本的哈希。

    脚本覆盖模板/参数/网格/频段/激励；引擎版本防"脚本相同但
    openEMS 升级后拿到旧引擎结果"的陈旧命中。
    """
    h = hashlib.sha256()
    h.update(self._CACHE_SCHEMA.encode())
    h.update(script_path.read_bytes())
    h.update(self._engine_stamp().encode())
    return h.hexdigest()

  def _engine_stamp(self) -> str:
    """openEMS 绑定版本（best-effort，取不到时用空串不阻塞）。"""
    with contextlib.suppress(Exception):
      from importlib.metadata import version

      return version("openEMS")
    return ""

  def _load_cached(self, script_path: Path) -> EMSolverResult | None:
    cache_dir = self._cache_dir()
    if cache_dir is None:
      return None
    npz_path = cache_dir / f"{self._cache_key(script_path)}.npz"
    if not npz_path.exists():
      return None
    try:
      with np.load(npz_path) as data:
        return EMSolverResult(
          success=True,
          freq_ghz=data["freq_ghz"],
          s_params=data["s_params"],
          message="仿真完成（缓存复用）",
        )
    except Exception:
      return None # 缓存损坏按 miss 处理，重算兜底

  def _store_cached(self, script_path: Path, result: EMSolverResult) -> None:
    cache_dir = self._cache_dir()
    if cache_dir is None:
      return
    try:
      cache_dir.mkdir(parents=True, exist_ok=True)
      final_path = cache_dir / f"{self._cache_key(script_path)}.npz"
      tmp_path = final_path.with_name(final_path.name + ".tmp")
      with open(tmp_path, "wb") as fh:
        np.savez_compressed(
          fh,
          freq_ghz=np.asarray(result.freq_ghz),
          s_params=np.asarray(result.s_params),
        )
      tmp_path.replace(final_path)
    except Exception:
      with contextlib.suppress(Exception):
        (cache_dir / f"{self._cache_key(script_path)}.npz.tmp").unlink()
      # 缓存写入失败不影响仿真结果（best-effort）

  def _parse_output(self) -> EMSolverResult:
    """解析 openEMS 输出。

    主路 = Touchstone（.s4p 等，skrf 读取，N 端口全矩阵——
    ratrace 官方激励轮转产物）；CSV 降兼容分支。
    far_field/sar 产物（WP4.1）best-effort 附带：解析失败不影响
    S 参数主路（观测性 best-effort #105）。
    """
    # Touchstone 优先（N 端口全矩阵，skrf 天然支持）
    snp_files = sorted(self._working_dir.rglob("*.s?p"))
    if snp_files:
      try:
        import skrf

        net = skrf.Network(str(snp_files[0]))
        return EMSolverResult(
          success=True,
          freq_ghz=net.f * 1e-9,
          s_params=net.s,
          far_field=self._parse_farfield(),
          sar=self._parse_sar(),
          message="仿真完成（Touchstone 主路）",
        )
      except Exception as e:
        return EMSolverResult(
          success=False, message=f"Touchstone 解析失败: {e}")
    # 查找 CSV 输出文件（模板脚本在 fdtd/ 子目录内运行，rglob 覆盖）。
    # 显式优先 sparams.csv：模板可能产出辅助 CSV（如 mline 锚的
    # port_beta.csv、远场 farfield_cut.csv），按文件名排序会误抢主产物。
    csv_files = sorted(self._working_dir.rglob("*.csv"))
    if not csv_files:
      return EMSolverResult(success=False, message="未找到输出文件")
    sparams_files = [p for p in csv_files if p.name == "sparams.csv"]
    target = sparams_files[0] if sparams_files else csv_files[0]

    # 解析第一个 CSV 文件
    try:
      data = np.loadtxt(str(target), delimiter=',', skiprows=1)
      freq_hz = data[:, 0]
      s11 = data[:, 1] + 1j * data[:, 2]
      s21 = data[:, 3] + 1j * data[:, 4]

      freq_ghz = freq_hz / 1e9
      n_freq = len(freq_ghz)
      if data.shape[1] >= 9:
        # 3 端口模板（wilkinson/branchline/coupled_line）：S11/S21/S31
        # 来自 port1 激励 run，S23 来自 port3 激励 run（双激励）。
        # 部分矩阵（未测元素置零）——仅用于带内指标提取（SpecEvaluator
        # 只读 s[0,0]/s[1,0]/s[2,0]/s[1,2]），不作为完整 S 矩阵使用。
        s31 = data[:, 5] + 1j * data[:, 6]
        s23 = data[:, 7] + 1j * data[:, 8]
        s_params = np.zeros((n_freq, 3, 3), dtype=complex)
        s_params[:, 0, 0] = s11
        s_params[:, 1, 0] = s21
        s_params[:, 2, 0] = s31
        s_params[:, 1, 2] = s23
        s_params[:, 2, 1] = s23 # 互易
      else:
        s_params = np.zeros((n_freq, 2, 2), dtype=complex)
        s_params[:, 0, 0] = s11
        s_params[:, 1, 0] = s21
        s_params[:, 0, 1] = s21 # 互易
        s_params[:, 1, 1] = s11 # 对称

      return EMSolverResult(
        success=True,
        freq_ghz=freq_ghz,
        s_params=s_params,
        far_field=self._parse_farfield(),
        sar=self._parse_sar(),
        message="仿真完成",
      )
    except Exception as e:
      return EMSolverResult(success=False, message=f"解析失败: {e}")

  # ─── WP4.1/D4：nf2ff 远场与 SAR 产物 ─────────────────────────────────────

  def _parse_farfield(self) -> dict[str, Any] | None:
    """解析 nf2ff 远场产物（farfield_meta.json + 切面指标）。

    best-effort：产物不存在 → None；解析失败 → {"ok": False, ...}。
    切面指标（HPBW/前后比）由 core.farfield 确定性内核计算。
    """
    if self._working_dir is None:
      return None
    try:
      from rfauto.core.farfield import (
        FARFIELD_META_NAME,
        find_artifacts,
        parse_farfield_cut_csv,
        summarize_cut,
      )

      found = find_artifacts(self._working_dir)
      meta_path = found.get(FARFIELD_META_NAME)
      if meta_path is None:
        return None
      import json

      meta = json.loads(meta_path.read_text(encoding="utf-8"))
      if not meta.get("ok"):
        return {"ok": False, "error": str(meta.get("error", "unknown"))}
      cuts_out: list[dict[str, Any]] = []
      cut_path = found.get("farfield_cut.csv")
      if cut_path is not None:
        for cut in parse_farfield_cut_csv(cut_path):
          s = summarize_cut(cut["theta_deg"], cut["e_norm"])
          cuts_out.append({
            "phi_deg": cut["phi_deg"],
            "n_theta": int(cut["theta_deg"].size),
            **s,
          })
      return {"ok": True, "meta": meta, "cuts": cuts_out}
    except Exception as e:
      return {"ok": False, "error": str(e)}

  def _parse_sar(self) -> dict[str, Any] | None:
    """解析 SAR 产物（sar.csv，官方 IEEE_62704 1g 平均口径）。"""
    if self._working_dir is None:
      return None
    try:
      from rfauto.core.farfield import SAR_CSV_NAME, find_artifacts

      path = find_artifacts(self._working_dir).get(SAR_CSV_NAME)
      if path is None:
        return None
      rows: dict[str, float] = {}
      with open(path, encoding="utf-8") as fh:
        header = fh.readline()
        if not header.strip().lower().startswith("metric"):
          return {"ok": False, "error": "sar.csv 表头不符"}
        for line in fh:
          parts = line.strip().split(",")
          if len(parts) >= 2:
            try:
              rows[parts[0]] = float(parts[1])
            except ValueError:
              continue
      return {"ok": True, "values": rows}
    except Exception as e:
      return {"ok": False, "error": str(e)}

  def get_nf2ff(self) -> dict[str, Any]:
    """nf2ff 远场产物（WP4.1；最近一次 solve 的工作目录，JSON 进出）。"""
    parsed = self._parse_farfield()
    if parsed is None:
      return {"ok": False, "error": "无远场产物（需 far_field=True 渲染并真跑）"}
    return parsed

  def get_sar(self) -> dict[str, Any]:
    """SAR 产物（WP4.1/D4；需 sar=True 渲染并真跑，JSON 进出）。"""
    parsed = self._parse_sar()
    if parsed is None:
      return {"ok": False, "error": "无 SAR 产物（需 sar=True 渲染并真跑）"}
    return parsed

  def get_sparams(self) -> tuple[np.ndarray, np.ndarray]:
    """获取 S 参数。"""
    result = self.solve()
    if not result.success:
      raise RuntimeError(result.message)
    return result.freq_ghz, result.s_params

  def close(self) -> None:
    """关闭求解器。"""
    self._connected = False


# 注册到全局注册表
def register_openems():
  """注册 openEMS 求解器到全局注册表。"""
  registry = get_global_registry()
  registry.register(EMSolverType.OPENEMS, OpenEMSSolver)


# 自动注册
with contextlib.suppress(Exception):
  register_openems()
