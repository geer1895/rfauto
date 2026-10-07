"""SpaceClaim / Discovery 修复端口（解耦）.

无 Ansys 时生成可执行 **SpaceClaim 脚本**（scscript / 录制式 Python），
有 SpaceClaim 安装时可挂接 COM/命令行（原型标注 TODO：装机后接线）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .base import GeometryExportPort  # noqa: F401  # 结构同族


@dataclass
class HealRequest:
    input_step: Path
    output_step: Path
    max_gap_mm: float = 0.001
    remove_small_faces: bool = True
    simplify: bool = False  # RF 保守
    log_path: Path | None = None


@dataclass
class HealResult:
    ok: bool
    mode: str  # script | live
    output: str = ""
    script_path: str = ""
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


SPACECLAIM_SCRIPT_TEMPLATE = '''# SpaceClaim / Discovery Model 脚本（由 rfauto fab 生成）
# 用法：SpaceClaim 脚本编辑器粘贴运行，或挂接 scdm 命令行
# 目标：导入 STEP → 检查/愈合 → 导出 STEP（禁止激进简化）

import os
from SpaceClaim import API  # 实际以本机 SC API 为准

INPUT = r"{input_step}"
OUTPUT = r"{output_step}"
MAX_GAP = {max_gap_mm}
SIMPLIFY = {simplify}
REMOVE_SMALL = {remove_small_faces}

def main():
    # 1) 导入
    # API.Import(INPUT)
    # 2) Prepare: Heal 模型（保留孔/倒角；禁止 delete holes）
    # API.Heal(gap=MAX_GAP, simplify=SIMPLIFY, removeSmallFaces=REMOVE_SMALL)
    # 3) 导出
    # API.Export(OUTPUT)
    print("SpaceClaim heal script: implement API calls for your SC version")
    print("IN=", INPUT)
    print("OUT=", OUTPUT)
    print("MAX_GAP=", MAX_GAP)

if __name__ == "__main__":
    main()
'''


class SpaceClaimScriptHealer:
    """默认端口：生成脚本（可离线、可审计）."""

    name = "spaceclaim_script"

    def heal(self, req: HealRequest) -> HealResult:
        script = SPACECLAIM_SCRIPT_TEMPLATE.format(
            input_step=str(req.input_step),
            output_step=str(req.output_step),
            max_gap_mm=req.max_gap_mm,
            simplify=str(req.simplify),
            remove_small_faces=str(req.remove_small_faces),
        )
        sp = req.output_step.with_suffix(".spaceclaim.heal.py")
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(script, encoding="utf-8")
        notes = [
            "已生成 SpaceClaim 修复脚本；无 SC 环境不会自动改几何。",
            "RF 保守：simplify=False，不删孔/倒角。",
            "接线：安装 SpaceClaim 后用命令行/API 执行该脚本。",
        ]
        if req.log_path:
            req.log_path.write_text("\n".join(notes) + f"\nscript={sp}\n", encoding="utf-8")
        return HealResult(
            ok=True,
            mode="script",
            output=str(req.output_step),
            script_path=str(sp),
            notes=notes,
        )


class NullHealer:
    """占位：跳过 SpaceClaim（走内置 conservative heal）."""

    name = "none"

    def heal(self, req: HealRequest) -> HealResult:
        return HealResult(
            ok=True,
            mode="none",
            output=str(req.output_step),
            notes=["跳过 SpaceClaim；使用 adapters.fab_export.hfss_export.conservative_heal_kwargs"],
        )


class SpaceClaimLiveHealer:
    """真机端口：检测安装后调用（未接线则回退 script）."""

    name = "spaceclaim_live"

    def heal(self, req: HealRequest) -> HealResult:
        # 常见安装探测（版本号硬编码清单为原型遗留，审查项 R14：装机接线
        # 时应改为按 HKLM\\SOFTWARE\\ANSYS, Inc. 注册表枚举）
        candidates = [
            r"C:\Program Files\ANSYS Inc\v261\scdm\SpaceClaim.exe",
            r"C:\Program Files\ANSYS Inc\v251\scdm\SpaceClaim.exe",
        ]
        found = next((p for p in candidates if Path(p).exists()), None)
        if not found:
            r = SpaceClaimScriptHealer().heal(req)
            r.mode = "script_fallback"
            r.notes.append("未检测到 SpaceClaim，已回退脚本模式")
            return r
        # 真调用留给装机环境（避免误起 GUI）
        r = SpaceClaimScriptHealer().heal(req)
        r.notes.append(f"检测到 {found}；请用 GUI/命令行执行脚本（避免误启动）")
        return r
