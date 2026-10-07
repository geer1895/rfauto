"""oe_templates 渲染管线逐字节恒等抽样钉（AU-1 批1 快照转正，ge6 followUp 批1）.

AU-1 批1（openems_templates.py 821KB → oe_templates/ 包 23 子模块）的
验收以一次性字节钉门（787 消费测试）+ runs/au1_split/ 快照落档——拆分
后渲染逐字节恒等只有当时的一次性证据。本守卫把**渲染字节恒等**转正常驻
抽样钉：四族代表模板（wilkinson/lange/ms_patch/hairpin，各落不同
render_<family> 子模块，名义参数+band×0.8..1.2+meta 网格）的渲染输出
sha256 金快照在 ``tests/gold/oe_templates_render_bytes.json``，任何触碰
渲染管线的改动（拆分回摆/isort 重排/字面量漂移）即红。

**改渲染输出=显式评审动作**：有意改动后重钉金快照并与消费面测试同批
（模板字节漂移会连带 test_layout_p2 金文本等消费钉），重钉命令::

    .venv/Scripts/python.exe tests/unit/test_oe_templates_render_bytes.py --write-gold
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_GOLD = _REPO / "tests" / "gold" / "oe_templates_render_bytes.json"

src_dir = _REPO / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

#: 抽样面：四族各一（分落不同 render_<family> 子模块，名义参数真传入——
#: ge5 审查 B P1-1 口径：META 存键名、值在 TEMPLATE_NOMINAL）。
SAMPLE_TEMPLATES = ("wilkinson", "lange", "ms_patch", "hairpin")


def _render_inputs() -> dict:
    from rfauto.adapters.openems_templates import TEMPLATE_META, TEMPLATE_NOMINAL

    inputs: dict[str, dict] = {}
    for t in SAMPLE_TEMPLATES:
        meta = TEMPLATE_META[t]
        f0 = float(meta["f0_ghz"])
        inputs[t] = {
            "params": dict(TEMPLATE_NOMINAL.get(t, {})),
            "band": [0.8 * f0, 1.2 * f0],
            "mesh": float(meta.get("mesh_resolution_mm") or 0.4),
        }
    return inputs


def _render_sha(t: str, spec: dict) -> str:
    from rfauto.adapters.openems_templates import render_script

    text = render_script(t, dict(spec["params"]),
                         (float(spec["band"][0]), float(spec["band"][1])),
                         mesh_resolution_mm=float(spec["mesh"]))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.mark.parametrize("template", SAMPLE_TEMPLATES)
def test_render_bytes_identical_to_gold(template: str):
    """渲染输出 sha256 逐字节=金快照（拆分恒等的常驻抽样证据）。"""
    gold = json.loads(_GOLD.read_text(encoding="utf-8"))
    spec = gold["templates"][template]
    assert _render_sha(template, spec) == spec["sha256"], (
        f"{template} 渲染字节漂移：oe_templates 渲染管线被改动——"
        "消费面（test_layout_p2 金文本等）须同批复核，重钉=显式评审动作")


def test_gold_inputs_match_live_registry():
    """金快照记录的渲染输入（params/band/mesh）与现注册表一致——防
    「金哈希对、输入悄悄换」的错位钉（#222 家族：钉的必须是同一实验）。"""
    gold = json.loads(_GOLD.read_text(encoding="utf-8"))
    live = _render_inputs()
    for t in SAMPLE_TEMPLATES:
        assert gold["templates"][t]["params"] == live[t]["params"], t
        assert gold["templates"][t]["band"] == pytest.approx(live[t]["band"]), t
        assert gold["templates"][t]["mesh"] == pytest.approx(live[t]["mesh"]), t


def test_render_deterministic_same_process():
    """同进程连渲两次逐字节同（渲染管线确定性自证，金哈希的前提）。"""
    live = _render_inputs()
    spec = live["wilkinson"]
    from rfauto.adapters.openems_templates import render_script

    a = render_script("wilkinson", dict(spec["params"]),
                      tuple(spec["band"]), mesh_resolution_mm=spec["mesh"])
    b = render_script("wilkinson", dict(spec["params"]),
                      tuple(spec["band"]), mesh_resolution_mm=spec["mesh"])
    assert a == b


if __name__ == "__main__":
    if "--write-gold" not in sys.argv:
        print(__doc__)
        print("用法: python tests/unit/test_oe_templates_render_bytes.py "
              "--write-gold")
        sys.exit(0)
    inputs = _render_inputs()
    gold = {"schema": "rfauto-oe-templates-render-bytes-v1",
            "note": "AU-1 批1 拆分逐字节恒等的常驻抽样钉；重钉=显式评审",
            "templates": {
                t: {**spec, "sha256": _render_sha(t, spec)}
                for t, spec in inputs.items()
            }}
    _GOLD.write_text(json.dumps(gold, ensure_ascii=False, indent=1) + "\n",
                     encoding="utf-8")
    print(f"gold written: {_GOLD.name} "
          f"({len(gold['templates'])} templates)")
