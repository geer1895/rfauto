"""meep_sampling：Meep mline 锚批量采样扩容编排（A1 子项，JSON 进出）。

定位：A1 Meep 腿的「采样扩容」服务层落点。把 w_mm × line_len_mm 笛卡尔积
+ **显式共享频点网格**批量渲染成 Meep 仿真脚本集（每点一目录）+ manifest.json
（点序/参数/脚本相对路径/预期产物名/共享网格/层叠），并同产 samples.json
（{'samples':[{'params':{w_mm,line_len_mm}}],'bounds':{...}}）作代理采样
喂 active_learning.propose_next_points（≥5 点、kind 须支持 uncertainty——
点数不足由其显式报错，本服务不重复守门）。

口径与边界：
- 纯离线：直接调 meep_adapter.render_mline_script **纯字符串内核**，不起
 子进程、不依赖本机 Meep（本机 Windows 无 Meep，CI Linux 真跑属后续项）；
- 共享网格：全批同一 freqs_ghz（compare_beta_three_way 三腿网格对齐前提），
 校验与 MeepSolver.build_geometry 同款（≥2 点/正值/严格递增）；
- 批量上限 MAX_BATCH_POINTS=256（防爆量，超限显式报错，零落盘）；
- 分层：service → adapters 合法（cli/mcp 薄壳后置，本服务不做 re-export）；
- 不改 dataset_service：E1 以 runs/ meta.json 为源，CI 回收后走既有
 materialize；本模块只产 manifest/samples，不写 runs/。
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path
from typing import Any

from rfauto.adapters.meep_adapter import (
  MEEP_LENGTH_UNIT_M,
  default_stackup,
  render_mline_script,
)
from rfauto.core.synthesis import Stackup

#: 批量点数上限（笛卡尔积 len(w)×len(l)；超限显式报错，防爆量）
MAX_BATCH_POINTS = 256

#: 落盘文件名契约（与 MeepSolver.build_geometry / solve 产物同名）
SCRIPT_NAME = "meep_mline_sim.py"
MANIFEST_NAME = "manifest.json"
SAMPLES_NAME = "samples.json"
#: 每点预期求解产物（两激励子进程 ×（S 参数 + β），MeepSolver.solve 契约）
EXPECTED_OUTPUTS: tuple[str, ...] = (
  "meep_sparams_p1.csv",
  "meep_sparams_p2.csv",
  "meep_port_beta_p1.csv",
  "meep_port_beta_p2.csv",
)
#: 采样参数名（samples.json params/bounds 键；与 build_geometry params 契约同名）
PARAM_NAMES: tuple[str, str] = ("w_mm", "line_len_mm")


# ─── 校验（显式报错，不静默吞） ───────────────────────────────────────────────

def _validate_positive_list(values: Any, name: str) -> list[float]:
  """参数网格：非空、全部为正的数值列表。"""
  if not isinstance(values, (list, tuple)) or len(values) == 0:
    raise ValueError(f"{name} 须为非空列表: {values!r}")
  out: list[float] = []
  for v in values:
    fv = float(v)
    if not fv > 0:
      raise ValueError(f"{name} 必须为正（mm）: {fv}")
    out.append(fv)
  return out


def validate_shared_freqs_ghz(freqs_ghz: Any) -> list[float]:
  """共享频点网格校验（与 MeepSolver.build_geometry 同款：≥2/正值/严格递增）。"""
  if not isinstance(freqs_ghz, (list, tuple)):
    raise ValueError(f"freqs_ghz 须为列表: {freqs_ghz!r}")
  fs = [float(f) for f in freqs_ghz]
  if len(fs) < 2:
    raise ValueError(f"频点网格须 ≥2 点（DF=0 高斯源退化）: {fs[:5]}")
  if any(f <= 0 for f in fs):
    raise ValueError("频点必须为正（GHz）")
  if any(b <= a for a, b in itertools.pairwise(fs)):
    raise ValueError(f"频点网格须严格递增: {fs[:5]}")
  return fs


def _resolve_stackup(stackup: dict[str, Any] | None) -> Stackup:
  """层叠覆盖 → Stackup（缺省 rogers4350b 锚；与 build_geometry 同键）。"""
  base = default_stackup()
  st_in = dict(stackup or {})
  st = Stackup(
    name=str(st_in.get("name", base.name)),
    epsilon_r=float(st_in.get("epsilon_r", base.epsilon_r)),
    thickness_mm=float(st_in.get("thickness_mm", base.thickness_mm)),
    loss_tangent=float(st_in.get("loss_tangent", base.loss_tangent)),
  )
  if st.epsilon_r < 1.0:
    raise ValueError(f"epsilon_r 必须 ≥1: {st.epsilon_r}")
  if st.thickness_mm <= 0:
    raise ValueError(f"thickness_mm 必须为正: {st.thickness_mm}")
  return st


def _stackup_dict(st: Stackup) -> dict[str, Any]:
  return {
    "name": st.name,
    "epsilon_r": st.epsilon_r,
    "thickness_mm": st.thickness_mm,
    "loss_tangent": st.loss_tangent,
  }


# ─── 批量编排主函数 ────────────────────────────────────────────────────────────

def build_mline_sampling_batch(
  w_mm: list[float],
  line_len_mm: list[float],
  freqs_ghz: list[float],
  out_dir: str | Path,
  *,
  resolution: float,
  stackup: dict[str, Any] | None = None,
  dpml_mm: float = 2.0,
  src_gap_mm: float = 2.0,
  margin_x_mm: float | None = None,
  air_top_mm: float | None = None,
  length_unit_m: float = MEEP_LENGTH_UNIT_M,
) -> dict[str, Any]:
  """w_mm × line_len_mm 笛卡尔积 → 批量 Meep mline 脚本 + manifest + samples。

  点序：行主序（外层 w_mm、内层 line_len_mm），idx 从 0 起，目录名 4 位
  零填充（``out_dir/0000/meep_mline_sim.py``）。全部校验通过后才落盘——
  超限/非法网格零产物。

  返回（JSON 可序列化）::

    {"ok": True, "n_points": N, "out_dir": ..., "manifest": <path>,
     "samples": <path>, "shared_freqs_ghz": [...]}
  """
  ws = _validate_positive_list(w_mm, "w_mm")
  ls = _validate_positive_list(line_len_mm, "line_len_mm")
  n_points = len(ws) * len(ls)
  if n_points > MAX_BATCH_POINTS:
    raise ValueError(
      f"批量点数 {n_points}（{len(ws)}×{len(ls)}）超过上限 "
      f"{MAX_BATCH_POINTS}——拆批或缩网格")
  fs_ghz = validate_shared_freqs_ghz(freqs_ghz)
  st = _resolve_stackup(stackup)
  if resolution <= 0:
    raise ValueError(f"分辨率必须为正: {resolution}")
  freqs_hz = [f * 1e9 for f in fs_ghz]

  # 先全量渲染到内存（任一点渲染失败 → 零落盘）
  rendered: list[tuple[int, float, float, str]] = []
  for idx, (w, ln) in enumerate(itertools.product(ws, ls)):
    script = render_mline_script(
      w, ln, st, freqs_hz,
      resolution=float(resolution),
      dpml_mm=float(dpml_mm),
      src_gap_mm=float(src_gap_mm),
      margin_x_mm=margin_x_mm,
      air_top_mm=air_top_mm,
      length_unit_m=float(length_unit_m),
    )
    rendered.append((idx, w, ln, script))

  root = Path(out_dir)
  root.mkdir(parents=True, exist_ok=True)
  points: list[dict[str, Any]] = []
  samples: list[dict[str, Any]] = []
  for idx, w, ln, script in rendered:
    dir_name = f"{idx:04d}"
    point_dir = root / dir_name
    point_dir.mkdir(parents=True, exist_ok=True)
    (point_dir / SCRIPT_NAME).write_text(script, encoding="utf-8")
    params = {"w_mm": w, "line_len_mm": ln}
    points.append({
      "idx": idx,
      "dir": dir_name,
      "params": params,
      "script": f"{dir_name}/{SCRIPT_NAME}",
      "expected_outputs": [f"{dir_name}/{name}" for name in EXPECTED_OUTPUTS],
    })
    samples.append({"params": dict(params)})

  manifest: dict[str, Any] = {
    "kind": "meep_mline_sampling_batch",
    "template": "mline",
    "n_points": n_points,
    "grid": {"w_mm": ws, "line_len_mm": ls, "order": "w_mm-major"},
    "shared_freqs_ghz": fs_ghz,
    "stackup": _stackup_dict(st),
    "render_options": {
      "resolution": float(resolution),
      "dpml_mm": float(dpml_mm),
      "src_gap_mm": float(src_gap_mm),
      "margin_x_mm": margin_x_mm,
      "air_top_mm": air_top_mm,
      "length_unit_m": float(length_unit_m),
    },
    "script_name": SCRIPT_NAME,
    "run_hint": f"python3 {SCRIPT_NAME} --excite-port {{1|2}}（每点两激励子进程）",
    "points": points,
  }
  manifest_path = root / MANIFEST_NAME
  manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
               encoding="utf-8")

  samples_doc: dict[str, Any] = {
    "samples": samples,
    "bounds": {
      "w_mm": [min(ws), max(ws)],
      "line_len_mm": [min(ls), max(ls)],
    },
    "objectives": [],
    "note": ("Meep mline 采样扩容批（A1 子项）：metrics 待 CI 真跑回收后并入；"
         "propose_next_points 需 ≥5 点且 kind 支持 uncertainty"),
  }
  samples_path = root / SAMPLES_NAME
  samples_path.write_text(json.dumps(samples_doc, ensure_ascii=False, indent=2),
              encoding="utf-8")
  return {
    "ok": True,
    "n_points": n_points,
    "out_dir": str(root),
    "manifest": str(manifest_path),
    "samples": str(samples_path),
    "shared_freqs_ghz": fs_ghz,
  }


def load_batch_manifest(out_dir: str | Path) -> dict[str, Any]:
  """读回批 manifest（JSON dict；不存在即 FileNotFoundError，不静默）。"""
  path = Path(out_dir) / MANIFEST_NAME
  if not path.exists():
    raise FileNotFoundError(f"manifest 不存在: {path}")
  return json.loads(path.read_text(encoding="utf-8"))
