import os
import subprocess
from pathlib import Path

# KiCad 自带 Python 3.11（pcbnew ABI 只兼容其自带解释器）。
# 缺省按 Windows 官方安装位推断，可用环境变量 RFAUTO_KICAD_PYTHON 覆盖。
KICAD_PYTHON = os.environ.get("RFAUTO_KICAD_PYTHON",
                              r"C:\Program Files\KiCad\10.0\bin\python.exe")
KICAD_SITE_PACKAGES = os.path.join(os.path.dirname(KICAD_PYTHON),
                                   "Lib", "site-packages")

def generate_minimal_pcb(output_path: str) -> dict:
    """生成最小 .kicad_pcb 文件（KiCad 10.0.6 API）。"""
    script_code = f'''
import sys
sys.path.insert(0, r"{KICAD_SITE_PACKAGES}")
import pcbnew

# 创建新 PCB
board = pcbnew.BOARD()

# 设置板子轮廓 (50mm x 30mm)
# KiCad 10 使用 SHAPE_POLY_SET
outline = board.GetBoardOutline()
outline.Clear()
outline.Append(0, 0)
outline.Append(50000000, 0)       # 50mm
outline.Append(50000000, 30000000)  # 30mm
outline.Append(0, 30000000)
outline.SetClosed(True)
board.UpdateBoardOutline(outline)

# 添加一个简单的走线 (F.Cu层)
track = pcbnew.PCB_TRACK(board)
track.SetStart(pcbnew.VECTOR2I(5000000, 5000000))   # 5mm, 5mm
track.SetEnd(pcbnew.VECTOR2I(45000000, 5000000))    # 45mm, 5mm
track.SetWidth(1000000)  # 1mm 线宽
track.SetLayer(pcbnew.F_Cu)
board.Add(track)

# 添加一个过孔
via = pcbnew.PCB_VIA(board)
via.SetCenter(pcbnew.VECTOR2I(25000000, 15000000))  # 25mm, 15mm
via.SetDrill(500000)   # 0.5mm 钻孔
via.SetWidth(1000000)  # 1mm 焊盘
board.Add(via)

# 保存
board.Save(r"{output_path}")
print(f"PCB saved to: {output_path}")
print(f"Board size: 50mm x 30mm")
print(f"Tracks: 1 (1mm wide, F.Cu)")
print(f"Vias: 1 (0.5mm drill)")
'''

    result = subprocess.run(
        [KICAD_PYTHON, "-c", script_code],
        capture_output=True,
        text=True,
        timeout=30,
    )

    return {
        "success": result.returncode == 0,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "output_path": output_path,
    }


if __name__ == "__main__":
    output = str(Path(__file__).resolve().parents[1] / "parts" / "test_minimal.kicad_pcb")
    print("Generating minimal .kicad_pcb file...")
    result = generate_minimal_pcb(output)
    print(f"Success: {result['success']}")
    if result['stdout']:
        print(f"Output: {result['stdout']}")
    if result['stderr']:
        print(f"Errors: {result['stderr']}")
