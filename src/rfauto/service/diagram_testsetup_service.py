"""diagram_testsetup_service —— 测试连接图 .drawio 生成入口（T-O6 席，2026-11-01）。

"算画同源"第三件：射频测试连接图生成器（VNA/信号源/频谱仪/LISN/DUT
连线——仪器卡+端口点+RF 正交连线+校准面标记+注记；CISPR/传导测试与
S 参数测量场景）。与 T-O1 链路框图互补的两极：**纯声明式生成器**——
零物理内核零公式（铁律 7 的另一面）：图上数字只有用户 JSON 显式给的
线缆损耗/长度标注值，原样标图零换算；第一验收面=拓扑正确性（连接表
↔边集双射、端口引用完整性）。

- 装配内核 = core/testsetup_diagram.py（场景校验/布局/边标签）→
  core/drawio_xml.py（T-O2 通用 mxGraph XML 内核，零第三方依赖零 AGPL
  复制——mxGraph XML 格式开放规范）；
- 本模块只做：入参校验 → 内核调用 → 落盘 → JSON 信封（规则 4：
  JSON 进出，CLI/MCP 是薄壳）。

确定性：同输入两次调用逐字节同文件（内核 XML 确定性 + 零时间戳）。
负例（端口引用不存在/未知 kind/严格键违约等）显式报错——以 ok=False
错误信封出（CLI --json 消费同构信封；不静默、不凑绿）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rfauto.core.testsetup_diagram import build_testsetup_plan
from rfauto.service.envelope import error_envelope, ok_envelope

__all__ = ["generate_testsetup_diagram"]


def generate_testsetup_diagram(
    scene: Any,
    out_path: Any,
    *,
    title: str | None = None,
) -> dict[str, Any]:
    """生成测试连接图 .drawio 文件（声明式场景 → 原生可编辑工程图）。

    Args:
        scene: 声明式场景 dict（顶层四键 title/instruments/connections/
            notes；仪器卡严格六键、连接边严格五键、注记卡严格两键——
            schema 全文见 core/testsetup_diagram.normalize_scene）。
        out_path: 输出 .drawio 路径（父目录须已存在；不自动建目录——
            路径错误显式报错而非静默补救）。
        title: 图标题（None 用场景 title，再 None 用内核缺省标题）。

    Returns:
        成功信封::

            {"ok": True, "out_path": str,
             "n_instruments": int, "n_connections": int, "n_notes": int,
             "instruments": [{id, kind, role, label, ports, note}, ...],
             "warnings": [str, ...]}

        ``warnings`` 逐条可断言（无连接/空端口/同列>2 交叉风险/DUT 奇数
        端口对半提示）。失败信封（校验负例/IO 错误）：
        ``{"ok": False, "errors": [str...]}``。
    """
    try:
        plan = build_testsetup_plan(scene, title=title)
        out = Path(out_path)  # PathLike 入参第一行收敛（#140）
        if out.parent and not out.parent.exists():
            raise ValueError(
                f"输出目录不存在：{out.parent}（请先建目录，不自动补救）")
        out.write_text(plan["xml"], encoding="utf-8")
    except (ValueError, TypeError, OSError) as exc:
        return error_envelope(f"{type(exc).__name__}: {exc}")

    return ok_envelope(
        out_path=str(out),
        n_instruments=plan["n_instruments"],
        n_connections=plan["n_connections"],
        n_notes=plan["n_notes"],
        instruments=plan["instruments"],
        warnings=plan["warnings"],
    )
