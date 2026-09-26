# ruff: noqa: F821
"""KiCad P-Cell 库（子进程方式）。

设计原则：
- 所有 KiCad 操作通过子进程调用 KiCad 自带 Python（3.11）
- 输入/输出通过 JSON 文件交换
- P-Cell 参数化：trace/coupled-line/pad/via/ground/launch
- 模块化：每个 P-Cell 是独立函数，可单独调用

使用方式：
    from rfauto.adapters.kicad_pcell import generate_pcb
    result = generate_pcb(
        output_path="output.kicad_pcb",
        traces=[{"start": [0,0], "end": [10,0], "width": 1.0, "layer": "F.Cu"}],
        vias=[{"position": [5,5], "drill": 0.5, "pad": 1.0}],
    )
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# KiCad Python 路径
KICAD_PYTHON = r"E:\KiCad\bin\python.exe"
KICAD_SITE_PACKAGES = r"E:\KiCad\bin\Lib\site-packages"


@dataclass
class Trace:
    """走线描述。"""
    start: list[float]  # [x, y] mm
    end: list[float]    # [x, y] mm
    width: float        # mm
    layer: str = "F.Cu"

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": self.start,
            "end": self.end,
            "width": self.width,
            "layer": self.layer,
        }


@dataclass
class Via:
    """过孔描述。"""
    position: list[float]  # [x, y] mm
    drill: float           # mm
    pad: float             # mm
    layers: list[str] = field(default_factory=lambda: ["F.Cu", "B.Cu"])

    def to_dict(self) -> dict[str, Any]:
        return {
            "position": self.position,
            "drill": self.drill,
            "pad": self.pad,
            "layers": self.layers,
        }


@dataclass
class Pad:
    """焊盘描述。"""
    position: list[float]  # [x, y] mm
    size: list[float]      # [width, height] mm
    shape: str = "rect"    # "rect" | "oval" | "circle"
    layer: str = "F.Cu"

    def to_dict(self) -> dict[str, Any]:
        return {
            "position": self.position,
            "size": self.size,
            "shape": self.shape,
            "layer": self.layer,
        }


@dataclass
class PCBDesign:
    """PCB 设计描述。"""
    board_size: list[float] = field(default_factory=lambda: [50.0, 30.0])  # mm
    traces: list[Trace] = field(default_factory=list)
    vias: list[Via] = field(default_factory=list)
    pads: list[Pad] = field(default_factory=list)
    edge_cuts: list[list[float]] = field(default_factory=list)  # 轮廓点

    def to_dict(self) -> dict[str, Any]:
        return {
            "board_size": self.board_size,
            "traces": [t.to_dict() for t in self.traces],
            "vias": [v.to_dict() for v in self.vias],
            "pads": [p.to_dict() for p in self.pads],
            "edge_cuts": self.edge_cuts,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PCBDesign:
        """从 JSON 反序列化（CLI kicad pcb 入口）。缺必填键时报 KeyError。"""
        traces = [Trace(
            start=t["start"], end=t["end"], width=t["width"],
            layer=t.get("layer", "F.Cu"),
        ) for t in data.get("traces", [])]
        vias = [Via(
            position=v["position"], drill=v["drill"], pad=v["pad"],
            layers=v.get("layers", ["F.Cu", "B.Cu"]),
        ) for v in data.get("vias", [])]
        pads = [Pad(
            position=p["position"], size=p["size"],
            shape=p.get("shape", "rect"), layer=p.get("layer", "F.Cu"),
        ) for p in data.get("pads", [])]
        return cls(
            board_size=data.get("board_size", [50.0, 30.0]),
            traces=traces, vias=vias, pads=pads,
            edge_cuts=data.get("edge_cuts", []),
        )


@dataclass
class PCBGenerationResult:
    """PCB 生成结果。"""
    success: bool
    output_path: str | None = None
    message: str = ""
    n_traces: int = 0
    n_vias: int = 0
    n_pads: int = 0
    # DP-7 P3：导出前 DFM 门报告（core.fab_check，best-effort #105——
    # 不阻塞导出；检查未跑/内部失败时为 None 或 ran=False 留痕）。
    dfm: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "output_path": self.output_path,
            "message": self.message,
            "n_traces": self.n_traces,
            "n_vias": self.n_vias,
            "n_pads": self.n_pads,
            "dfm": self.dfm,
        }


def generate_pcb(
    output_path: str | Path,
    design: PCBDesign,
    kicad_python: str | None = None,
) -> PCBGenerationResult:
    """生成 KiCad PCB 文件。

    通过子进程调用 KiCad Python，避免 Python 版本冲突。

    Args:
        output_path: 输出 .kicad_pcb 文件路径
        design: PCB 设计描述
        kicad_python: KiCad Python 路径（默认取模块常量 KICAD_PYTHON）

    Returns:
        PCBGenerationResult
    """
    output_path = Path(output_path)
    python_exe = kicad_python or KICAD_PYTHON

    # DP-7 P3：导出前 DFM 门（best-effort，#105——绝不阻塞导出，失败留痕
    # None/ran=False；剖面缺失或形状非法静默降级）。
    dfm_report: dict[str, Any] | None = None
    try:
        from rfauto.core.fab_check import best_effort_dfm_for_design
        dfm_report = best_effort_dfm_for_design(design.to_dict())
    except Exception:
        dfm_report = None

    if not Path(python_exe).exists():
        return PCBGenerationResult(
            success=False,
            message=f"KiCad Python 不存在: {python_exe}",
            dfm=dfm_report,
        )

    # 创建临时 JSON 输入文件
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
        json.dump(design.to_dict(), f, ensure_ascii=False, indent=2)
        input_json = f.name

    try:
        # 生成 KiCad Python 脚本
        script = _generate_kicad_script(input_json, str(output_path))

        # 通过子进程执行
        result = subprocess.run(
            [python_exe, "-c", script],
            capture_output=True,
            text=True,
            timeout=30,
            env={"PATH": f"E:\\KiCad\\bin;E:\\KiCad\\bin\\DLLs;{__import__('os').environ.get('PATH', '')}"},
        )

        if result.returncode != 0:
            return PCBGenerationResult(
                success=False,
                message=f"KiCad 执行失败: {result.stderr[:500]}",
                dfm=dfm_report,
            )

        return PCBGenerationResult(
            success=True,
            output_path=str(output_path),
            message="PCB 生成成功",
            n_traces=len(design.traces),
            n_vias=len(design.vias),
            n_pads=len(design.pads),
            dfm=dfm_report,
        )

    except subprocess.TimeoutExpired:
        return PCBGenerationResult(success=False, message="生成超时",
                                   dfm=dfm_report)
    except Exception as e:
        return PCBGenerationResult(success=False, message=str(e),
                                   dfm=dfm_report)
    finally:
        # 清理临时文件
        Path(input_json).unlink(missing_ok=True)


def _generate_kicad_script(input_json: str, output_pcb: str) -> str:
    """生成 KiCad Python 脚本。"""
    return f'''
import sys
sys.path.insert(0, r"{KICAD_SITE_PACKAGES}")
import json
import pcbnew

# 读取设计数据
with open(r"{input_json}", "r", encoding="utf-8") as f:
    pcb_data = json.load(f)

# 创建 PCB
board = pcbnew.BOARD()

# 添加走线
for trace in pcb_data.get("traces", []):
    start = trace["start"]
    end = trace["end"]
    width = trace["width"]
    layer = trace.get("layer", "F.Cu")

    track = pcbnew.PCB_TRACK(board)
    track.SetStart(pcbnew.VECTOR2I(int(start[0] * 1e6), int(start[1] * 1e6)))
    track.SetEnd(pcbnew.VECTOR2I(int(end[0] * 1e6), int(end[1] * 1e6)))
    track.SetWidth(int(width * 1e6))

    # 设置层
    if layer == "F.Cu":
        track.SetLayer(pcbnew.F_Cu)
    elif layer == "B.Cu":
        track.SetLayer(pcbnew.B_Cu)

    board.Add(track)

# 添加过孔
for via_data in pcb_data.get("vias", []):
    pos = via_data["position"]
    drill = via_data["drill"]
    pad = via_data["pad"]

    via = pcbnew.PCB_VIA(board)
    via.SetPosition(pcbnew.VECTOR2I(int(pos[0] * 1e6), int(pos[1] * 1e6)))
    via.SetDrill(int(drill * 1e6))
    via.SetWidth(int(pad * 1e6))
    board.Add(via)

# 添加焊盘
for pad_data in pcb_data.get("pads", []):
    pos = pad_data["position"]
    size = pad_data["size"]
    shape = pad_data.get("shape", "rect")
    layer = pad_data.get("layer", "F.Cu")

    footprint = pcbnew.FOOTPRINT(board)
    footprint.SetPosition(pcbnew.VECTOR2I(int(pos[0] * 1e6), int(pos[1] * 1e6)))

    pad = pcbnew.PAD(footprint)
    pad.SetSize(pcbnew.VECTOR2I(int(size[0] * 1e6), int(size[1] * 1e6)))

    if shape == "rect":
        pad.SetShape(pcbnew.PAD_SHAPE_RECT)
    elif shape == "oval":
        pad.SetShape(pcbnew.PAD_SHAPE_OVAL)
    elif shape == "circle":
        pad.SetShape(pcbnew.PAD_SHAPE_CIRCLE)

    if layer == "F.Cu":
        pad.SetLayerSet(pcbnew.LSET(pcbnew.F_Cu))
    elif layer == "B.Cu":
        pad.SetLayerSet(pcbnew.LSET(pcbnew.B_Cu))

    footprint.Add(pad)
    board.Add(footprint)

# 保存
board.Save(r"{output_pcb}")
print(f"PCB saved: {output_pcb}")
print(f"Traces: {len(pcb_data.get('traces', []))}")  # noqa: F821
print(f"Vias: {len(pcb_data.get('vias', []))}")  # noqa: F821
print(f"Pads: {len(pcb_data.get('pads', []))}")  # noqa: F821
'''


def create_microstrip_pcb(
    output_path: str | Path,
    width_mm: float,
    length_mm: float,
    substrate_name: str = "rogers4350b_h0.508",
) -> PCBGenerationResult:
    """创建微带线 PCB（常用快捷函数）。

    Args:
        output_path: 输出路径
        width_mm: 线宽 (mm)
        length_mm: 线长 (mm)
        substrate_name: 基板名称

    Returns:
        PCBGenerationResult
    """
    design = PCBDesign(
        board_size=[length_mm + 10, width_mm + 10],
        traces=[
            Trace(
                start=[5, 5],
                end=[5 + length_mm, 5],
                width=width_mm,
                layer="F.Cu",
            )
        ],
    )
    return generate_pcb(output_path, design)
