"""REST 面裸 ``{"ok": ...}`` 字面棘轮门（aurora_d REST-B 席，2026-10-14）。

照 CLI 棘轮形态（test_cli_envelope_ratchet.py，#325 家法同式只收不放）：
REST 双文件面（``service/rest_api.py`` + ``service/sdk.py``——
test_rest_api.py::TestLayerGuard 同域口径）下 ``{"ok"`` 字面出现次数
**只许减少不许增加**。信封契约冻结口径（test_envelope_contract 的
AST 守卫）只数 ``return {dict}`` 直返形，本文件补文本字面口径——
两守卫互补，防"包一层的裸字面"回潮。

棘轮帽（RATCHET_CAP）= REST-B 收编批后实测 5（收编前 6）。调整规则：
- 新 REST 端点/SDK 方法的响应信封一律走 ``_ok``/``_error`` 传输面出口
  （``_ok`` 本体已走 ok_envelope 构造器，线形逐字节不变）；
- 降低棘轮=同笔把站点改走构造器后调小本值；调大本值=违约（新字面上
  来直接红）。

结构性豁免台账（改形即破坏线上契约，AU-2 域升版另立票；文本计数假阳性
随数入帽——CLI 棘轮先例）：
- rest_api.py 模块 docstring 2 处=线形契约记载（文本非代码）；
- rest_api.py ``_error()`` 1 处=REST 传输面错误信封
  ``{"ok": false, "error": {"code", "message"}}``（对象形 error，与
  service 层 errors 列表契约不同形；OpenAPI ErrorEnvelope schema 与
  SDK ``_error_from`` 解析器同此形——构造器化=破坏线形）；
- rest_api.py ``validate_openapi_spec`` docstring 1 处=构造器输出自述；
- sdk.py ``HttpTransport`` 1 处=非 JSON 错误体兜底重构 REST 错误信封
  （必须落 code/message 对象形喂 ``_error_from``）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

src_dir = Path(__file__).resolve().parents[2] / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

SRC_DIR = src_dir / "rfauto" / "service"

# REST 面双文件（传输壳 + SDK；命名面与 test_rest_api 分层守卫一致）
REST_FACE_FILES = ("rest_api.py", "sdk.py")

# 棘轮帽（2026-10-14 REST-B 收编批后实测=5；收编前 6，只降不升）
RATCHET_CAP = 5


def _count_bare_ok_literals() -> tuple[int, list[str]]:
    """逐文件统计 REST 面 ``{"ok"`` 字面出现次数（原文文本计数）。"""
    per_file: list[str] = []
    total = 0
    for name in REST_FACE_FILES:
        path = SRC_DIR / name
        n = path.read_text(encoding="utf-8").count('{"ok"')
        if n:
            per_file.append(f"  service/{name}: {n}")
            total += n
    return total, per_file


def test_rest_bare_ok_envelope_ratchet():
    """裸 ``{"ok"`` 字面计数 ≤ 棘轮帽（只收不放；明细随失败消息落出）。"""
    total, per_file = _count_bare_ok_literals()
    assert total <= RATCHET_CAP, (
        f'REST 面裸 {{"ok": ...}} 字面计数超棘轮帽（{total} > {RATCHET_CAP}）'
        "——新端点响应信封必须走 rest_api._ok/_error 传输面出口，"
        "禁止再造裸 dict 信封（aurora_d REST-B，ENGH 棘轮家法同式）。"
        "降低本棘轮=同笔把站点改走构造器（输出逐字节不变）后调小 "
        "RATCHET_CAP；调大=违约。当前计数明细：\n" + "\n".join(per_file))


def test_ratchet_cap_matches_current_tree():
    """帽值与树面实测一致（防帽值漂移失真：改站点必须同笔调帽）。"""
    total, _ = _count_bare_ok_literals()
    assert total == RATCHET_CAP, (
        f"棘轮帽 {RATCHET_CAP} 与树面实测 {total} 不一致——收编/回潮后"
        "必须同笔校准 RATCHET_CAP（只许调小）")


# ── 收编站点线形回归钉（构造器化后输出契约不变；零网络零仿真）───────────────

def test_ok_envelope_wire_shape_unchanged():
    """收编钉：``_ok`` 线形逐字节不变（ok/data 键集与键序；构造器化零行为变更）。"""
    from rfauto.service.rest_api import _ok

    payload = {"x": 1, "nested": {"a": [1, 2]}}
    body = json.loads(_ok(payload).body.decode("utf-8"))
    assert body == {"ok": True, "data": payload}
    assert list(body) == ["ok", "data"]  # 键序=线形契约（success envelope）
