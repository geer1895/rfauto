"""PCB 旁路：IPC-2581 / Gerber 交付提示（与机加包隔离）."""

from __future__ import annotations

from pathlib import Path

PCB_DELIVERABLE_CHECKLIST = [
    "# PCB / 介质板 交付（与机加包隔离）",
    "",
    "- [ ] IPC-2581（推荐，PyEDB export_to_ipc2581）",
    "- [ ] 或 Gerber + 钻孔 + 叠层说明",
    "- [ ] 板框 DXF（若要外形铣）",
    "- [ ] 材料/厚度/铜厚（叠层变量为真源）",
    "- [ ] 阻抗控制要求（若需要）",
    "",
    "注意：ODB++ 符号表常为 µm，IPC 为 mm——单位必须书面写明。",
    "禁止把信号层 Gerber 与机加加工图混成一张。",
]


def write_pcb_checklist(out_dir: str | Path) -> Path:
    p = Path(out_dir) / "pcb_deliverable_checklist.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(PCB_DELIVERABLE_CHECKLIST) + "\n", encoding="utf-8")
    return p
