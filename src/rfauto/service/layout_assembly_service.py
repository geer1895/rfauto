"""LC-5 装配 BOM 面：KiCad 子进程 pick-place/.pos + BOM 聚合（JSON 进出）。

规格=研究扩充 round15 §四 LC-5："pick-place/.
pos/BOM 聚合/装配图/3D 板"的**最小面**——位号提取 + .pos + BOM 聚合 CSV。
3D 板/装配图属 P3（trimesh 可选），本模块不做（如实收窄）。

铁律 2：**KiCad 一律子进程** ``E:\\KiCad\\bin\\python.exe``——
pcbnew ABI 硬限制绝不 import 进主 venv。本模块零 pcbnew import：几何/
位号提取全部发生在生成的子进程脚本内（脚本落 out_dir 留证据链，自描述），
主进程只收 marker 包夹的 JSON（kicad_extract 同款协议）与解析器解析
（#210/#214 坑族不触碰——不建板不改板，只读）。

解析器解析口径（KiCad 10 实测）：坐标 nm → mm（÷1e6）、
``GetOrientationDegrees()`` 度、``IsFlipped()``→side；字段抽取 best-effort
（#105：单字段异常记 errors 不阻塞主行）。产物：

- ``<stem>.pos``——CSV 放置表（Designator,Val,Package,Mid X,Mid Y,
  Rotation,Layer；KiCad .pos 惯例列序，CSV 逗号分隔自描述）；
- ``<stem>-bom.csv``——聚合 BOM（Refs,Qty,Value,Footprint；按
  (Value, Footprint) 分组、位号字母序、分组排序确定性）。
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from rfauto.adapters.kicad_extract import resolve_kicad_python
from rfauto.service.envelope import error_envelope, ok_envelope

__all__ = [
    "ASSEMBLY_JSON_END",
    "ASSEMBLY_JSON_START",
    "SCRIPT_NAME",
    "aggregate_bom",
    "assembly_payload",
    "build_kicad_script",
    "parse_assembly_stdout",
    "write_bom_csv",
    "write_pos_csv",
]

#: 子进程脚本内 JSON 载荷的 marker（与 kicad_extract 协议同款、独立常量——
#: pcbnew 偶发 stdout 噪声不进载荷）。
ASSEMBLY_JSON_START = "RFAUTO_ASSEMBLY_JSON_START"
ASSEMBLY_JSON_END = "RFAUTO_ASSEMBLY_JSON_END"

#: 生成脚本落盘名（out_dir 内，证据链自描述）。
SCRIPT_NAME = "_rfauto_assembly_export.py"

#: .pos 表列序（KiCad pick-and-place 惯例）。
POS_COLUMNS = ("Designator", "Val", "Package", "Mid X", "Mid Y", "Rotation", "Layer")

#: 聚合 BOM 列序。
BOM_COLUMNS = ("Refs", "Qty", "Value", "Footprint")


def build_kicad_script(pcb_path: str) -> str:
    """生成 KiCad 自带 Python 执行的只读提取脚本（纯函数，可离线审计）。

    只读口径：LoadBoard 后不 SaveBoard（#210/#214 坑族零接触）；逐封装
    try/except 记 errors（#105 best-effort，单个怪封装不拖垮整板）。
    """
    return f'''# rfauto LC-5 装配导出（只读；由 service/layout_assembly_service 生成）
# 目标板：{pcb_path}
import json
import pcbnew

board = pcbnew.LoadBoard(r"{pcb_path}")
rows = []
errors = []
for fp in board.GetFootprints():
    try:
        fields = {{}}
        try:
            for fld in fp.GetFields():
                name = fld.GetName()
                if name in ("Reference", "Value", "Footprint"):
                    continue
                text = fld.GetText()
                if text:
                    fields[name] = text
        except Exception as exc:  # 字段面 best-effort（#105）
            errors.append(f"{{fp.GetReference()}} fields: {{exc}}")
        pos = fp.GetPosition()
        rows.append({{
            "designator": fp.GetReference(),
            "value": fp.GetValue(),
            "footprint": fp.GetFPID().GetUniStringLibId(),
            "x_mm": pos.x / 1e6,
            "y_mm": pos.y / 1e6,
            "rot_deg": float(fp.GetOrientationDegrees()),
            "side": "back" if fp.IsFlipped() else "front",
            "fields": fields,
        }})
    except Exception as exc:  # 单封装解析失败不拖垮整板（#105）
        errors.append(f"footprint: {{exc}}")
rows.sort(key=lambda r: r["designator"])
bbox = None
try:
    bb = board.GetBoardEdgesBoundingBox()
    o, s = bb.GetOrigin(), bb.GetSize()
    bbox = [o.x / 1e6, o.y / 1e6, (o.x + s.x) / 1e6, (o.y + s.y) / 1e6]
except Exception as exc:  # 外框 best-effort，缺如实 null
    errors.append(f"bbox: {{exc}}")
payload = {{"footprints": rows, "board_bbox_mm": bbox, "errors": errors,
            "kicad_version": pcbnew.GetBuildVersion()}}
print("{ASSEMBLY_JSON_START}")
print(json.dumps(payload, ensure_ascii=False))
print("{ASSEMBLY_JSON_END}")
'''


def parse_assembly_stdout(stdout: str) -> dict[str, Any]:
    """子进程 stdout → JSON 载荷（marker 包夹；无 marker/marker 不闭合=显错）。"""
    if ASSEMBLY_JSON_START not in stdout:
        raise ValueError(
            f"子进程输出缺 {ASSEMBLY_JSON_START} marker（脚本未按协议输出）")
    body = stdout.split(ASSEMBLY_JSON_START, 1)[1]
    if ASSEMBLY_JSON_END not in body:
        raise ValueError(f"子进程输出缺 {ASSEMBLY_JSON_END} marker（载荷不闭合）")
    body = body.split(ASSEMBLY_JSON_END, 1)[0].strip()
    data = json.loads(body)
    if not isinstance(data, dict) or not isinstance(data.get("footprints"), list):
        raise ValueError("装配载荷形态非法（缺 footprints 列表）")
    return data


def write_pos_csv(rows: list[dict[str, Any]], path: str | Path) -> Path:
    """放置表 → CSV（KiCad .pos 惯例列序；坐标 4 位小数自描述 mm）。"""
    typed = Path(path)
    with typed.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(POS_COLUMNS)
        for r in rows:
            writer.writerow([
                r.get("designator", ""), r.get("value", ""), r.get("footprint", ""),
                f'{float(r.get("x_mm", 0.0)):.4f}', f'{float(r.get("y_mm", 0.0)):.4f}',
                f'{float(r.get("rot_deg", 0.0)):.2f}', r.get("side", ""),
            ])
    return typed


def aggregate_bom(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """放置行 → 聚合 BOM（(value, footprint) 分组；位号字母序；确定性排序）。"""
    groups: dict[tuple[str, str], list[str]] = {}
    for r in rows:
        key = (str(r.get("value", "")), str(r.get("footprint", "")))
        groups.setdefault(key, []).append(str(r.get("designator", "")))
    out = []
    for (value, footprint), refs in sorted(groups.items()):
        out.append({"refs": sorted(refs), "qty": len(refs),
                    "value": value, "footprint": footprint})
    return out


def write_bom_csv(agg: list[dict[str, Any]], path: str | Path) -> Path:
    """聚合 BOM → CSV（Refs 逗号连接；分组已排序）。"""
    typed = Path(path)
    with typed.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(BOM_COLUMNS)
        for g in agg:
            writer.writerow([",".join(g["refs"]), g["qty"], g["value"], g["footprint"]])
    return typed


def assembly_payload(
    pcb_path: str | Path,
    out_dir: str | Path,
    *,
    kicad_python: str | None = None,
    timeout_s: float = 120.0,
) -> dict[str, Any]:
    """KiCad 子进程装配导出（铁律 2 子进程域；JSON 信封进出）。

    流程：脚本落 ``out_dir`` → 子进程只读提取 → marker JSON 解析 →
    ``<stem>.pos`` + ``<stem>-bom.csv`` 落盘 → 聚合载荷。pcbnew 缺失/
    KiCad 缺装/超时/非零退出=error 信封带 stderr 尾段（不裸 traceback）。
    """
    typed_pcb = Path(pcb_path)
    if not typed_pcb.is_file():
        return error_envelope([f"PCB 文件不存在: {typed_pcb}"])
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    python_exe = resolve_kicad_python(kicad_python)
    script_path = out / SCRIPT_NAME
    script_path.write_text(build_kicad_script(str(typed_pcb)), encoding="utf-8")

    # PATH 前置 KiCad bin（kicad_drc 同款）；继承完整环境（不裸 env 替换，
    # 保留 SYSTEMROOT 等 Windows 子进程必需变量）
    env = dict(os.environ)
    kicad_bin = str(Path(python_exe).parent)
    env["PATH"] = kicad_bin + os.pathsep + env.get("PATH", "")

    try:
        result = subprocess.run(
            [python_exe, str(script_path)],
            capture_output=True, text=True, timeout=timeout_s, env=env,
        )
    except subprocess.TimeoutExpired:
        return error_envelope(
            [f"KiCad 装配导出超时（>{timeout_s}s）；python={python_exe}"])
    except OSError as exc:
        return error_envelope(
            [f"KiCad 子进程启动失败（python={python_exe}）: {exc}",
             "铁律 2：KiCad 走自带 Python 子进程；核对 RFAUTO_KICAD_PYTHON/安装位"])
    if result.returncode != 0:
        return error_envelope(
            [f"KiCad 装配导出失败（rc={result.returncode}）: "
             f"{(result.stderr or '')[-500:]}"])

    try:
        data = parse_assembly_stdout(result.stdout)
    except (ValueError, json.JSONDecodeError) as exc:
        return error_envelope([f"装配载荷解析失败: {exc}"])

    rows = data.get("footprints") or []
    stem = typed_pcb.stem
    pos_path = write_pos_csv(rows, out / f"{stem}.pos")
    agg = aggregate_bom(rows)
    bom_path = write_bom_csv(agg, out / f"{stem}-bom.csv")
    return ok_envelope(
        pcb_file=str(typed_pcb),
        pos_path=str(pos_path),
        bom_path=str(bom_path),
        script_path=str(script_path),
        n_placed=len(rows),
        bom=agg,
        board_bbox_mm=data.get("board_bbox_mm"),
        errors=data.get("errors") or [],
        kicad_version=data.get("kicad_version"),
    )
