"""维护者脚手架（SO-审查 §7 P5 / E4 mini，2026-10-05）。

`rfauto dev new-template / new-calculator` 的 service 面：生成骨架文件
+ 消费钉清单（把 /考古知识固化成工具）。adapter_kit.
scaffold_adapter 同款纪律：骨架落盘前 compile() 自检、不覆盖既有文件、
名字非法显式报错。

铁律 7：骨架与清单零物理数字、零计数字面量（计数一律指向单源
`len(TEMPLATE_META)` / `len(EXPECTED)` 口径，勿写死）；E1/E2/E4 的
消费钉知识以 docs/tutorials/extending-rfauto.md 为长版单源，本模块
生成的 CHECKLIST 是落盘速查（两处键集一致由单测钉住）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope

#: 骨架产物 schema 标识。
DEV_SCAFFOLD_SCHEMA = "rfauto-dev-scaffold-v1"

#: 模板消费钉清单（与 extending-rfauto.md §4 表键集一致；零字面计数）。
TEMPLATE_PIN_CHECKLIST: tuple[tuple[str, str], ...] = (
    ("1", "tests/unit/test_template_meta_consistency.py"
          "（TEMPLATE_NOMINAL 键值 ↔ docs/templates/<名>/meta.yaml 逐键一致）"),
    ("2", "tests/unit/test_template_geometry_audit.py"
          "（EXPECTED_TEMPLATES 全量计数，单源 len(TEMPLATE_META)，勿写字面数）"),
    ("3", "tests/unit/test_calculators.py 同款单源口径的三处模板计数字面"
          "（==N 禁，改 len 单源）"),
    ("4", "docs/templates/<名>/meta.yaml 落盘（nominal_params 全部综合引擎精算）"),
    ("5", "可选 template_specs 注册（spec 覆盖面消费方）"),
)

#: 计算器消费钉清单（与 extending-rfauto.md §2 表键集一致；#df6② 五钉）。
CALCULATOR_PIN_CHECKLIST: tuple[tuple[str, str], ...] = (
    ("1", "tests/unit/test_calculators.py 的 EXPECTED 键集"),
    ("2", "tests/unit/test_physics_invariants.py 的每键输入表"),
    ("3", "tests/unit/test_model_docs.py 的文档面"),
    ("4", "tests/unit/test_experimental_calculators.py"
          "（experimental 键；计数用 len(EXPECTED) 单源，勿写字面数）"),
    ("5", "docs 三处文档面的数字实测更新（#97 文档数字与代码实测绑定）"),
)

#: 模板注册两条铁律（历史代价，别再付——extending-rfauto.md §4 同源）。
_TEMPLATE_IRON_RULES: tuple[str, ...] = (
    "名义几何值全部综合引擎精算（微带用 Hammerstad-Jensen 综合，"
    "core/synthesis 单源），禁止从其他模型/文档抄毫米数——手算捷径"
    "造成的名义频偏达 −10% 量级（#1c/#252）。",
    "离线几何审计必过再真跑：渲染脚本 exec 到建模段，判据落在 CSXCAD "
    "实测对象（原语非零体积/端口激励非零/连通性/网格间距）"
    "（#212；docs/tutorials/real-simulation.md 第 3 节）。",
)

_TEMPLATE_META_DRAFT = """# docs/templates/{name}/meta.yaml 草稿（脚手架生成；占位值必须替换）
f0_ghz: <设计频点 GHz>
n_ports: <端口数>
extraction: "<抽取判据一句话>"
params: [<参数名列表，与渲染函数签名一致>]
topology: "<拓扑摘要一句话>"
substrate:
  er: <相对介电常数>
  h_mm: <板厚>
param_semantics: "<逐参数语义一句话（physics_roles 同源，#154）>"
nominal_params: <名义值表——全部综合引擎精算，禁手抄（#1c/#252）>
campaign_capable: <true/false>
campaign_capable_reasons: [<受限原因，仅 false 时>]
"""

_TEMPLATE_RENDER_SKELETON = '''"""{name} 模板渲染骨架（脚手架生成；占位段必须替换后才能真跑）。"""

from __future__ import annotations


def render_script(params, out_dir, mesh_resolution_mm=0.0, nr_ts=None):
    """渲染 {name} 几何（占位骨架——占位段必须替换）。

    铁律：
    1. 名义几何值全部综合引擎精算（core/synthesis 单源），禁手抄毫米数；
    2. 端口/边界/网格口径对照 docs/rf_template_references.md 官方例；
    3. 离线几何审计测试（test_skeleton.py 同款）先过再真跑（#212）。
    """
    raise NotImplementedError("占位骨架：按 docs/tutorials/extending-rfauto.md 第 4 节补齐")
'''

_TEMPLATE_TEST_SKELETON = '''"""{safe} 模板离线几何审计骨架（脚手架生成；#212 制度化占位）。

占位测试默认 xfail——渲染函数补齐后改写判据并移除 xfail：
判据落在 CSXCAD 实测对象（原语非零体积/端口激励非零/连通性/网格间距），
字符串存在性 + compile() 抓不住画法错误（#212 实证）。
"""

from __future__ import annotations

import pytest


@pytest.mark.xfail(reason="脚手架占位：渲染函数补齐后改写为实测判据", strict=True)
def test_{safe}_geometry_audit() -> None:
    raise NotImplementedError("占位：按 docs/tutorials/real-simulation.md 第 3 节补齐")
'''

_CALCULATOR_SKELETON = '''"""<一句话语义> 计算器骨架（脚手架生成；占位段必须替换）。

数值只在确定性内核（铁律 7）：本函数是纯函数，LLM/agent 永不产生
物理数字。出处口径写进 description（#97 文档数字与代码实测绑定）。
"""

from __future__ import annotations

from rfauto.core.calc_families.registry import register_calculator


@register_calculator(
    "{safe}",                       # 键名（CLI/MCP 消费）
    "<一句话语义描述（含口径与出处）>",
    params=(("freq_ghz", "频率 GHz"),),
    required=("freq_ghz",),
    experimental=False,             # True=默认拒跑，需显式放行
    reciprocal=True,                # 非互易器件显式 False
)
def {safe}(**kw):
    """占位骨架：替换为真实闭式（裁判=小步长收敛数值+独立来源解析值，#118）。"""
    raise NotImplementedError("占位骨架：补齐闭式实现与对拍锚")
'''


def _checklist_markdown(title: str, pins: tuple[tuple[str, str], ...],
                        rules: tuple[str, ...] = ()) -> str:
    lines = [f"# {title}", "",
             "> 脚手架生成（service/dev_scaffold_service 单源）；长版见 "
             "docs/tutorials/extending-rfauto.md。", ""]
    if rules:
        lines += ["## 两条铁律", ""]
        lines += [f"- {r}" for r in rules] + [""]
    lines += ["## 消费钉清单（漏了定向测试绿、合流全量门红）", "",
              "| 钉 | 位置 |", "|---|---|"]
    lines += [f"| {n} | {loc} |" for n, loc in pins]
    lines.append("")
    return "\n".join(lines)


def _safe_name(name: str) -> str:
    return "".join(ch for ch in name if ch.isalnum() or ch == "_")


def _write_new(path: Path, content: str, created: list[str],
               skipped: list[str]) -> None:
    """不覆盖既有文件；落盘前 compile() 自检 .py（防空骨架/半成品）。"""
    if path.exists():
        skipped.append(str(path))
        return
    if path.suffix == ".py":
        compile(content, str(path), "exec")  # SyntaxError 向上抛，调用方兜
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    created.append(str(path))


def scaffold_template(name: str, output_dir: str | Path | None = None) -> dict[str, Any]:
    """生成新模板骨架包（meta 草稿 + 渲染/审计测试占位 + 消费钉清单）。

    名字非法或全部产物已存在时显式报错；不覆盖既有文件。
    """
    safe = _safe_name(name)
    if not safe or safe[0].isdigit():
        return error_envelope([f"非法模板名: {name}"])
    out_dir = (Path(output_dir) if output_dir
               else Path("docs") / "templates" / safe)
    created: list[str] = []
    skipped: list[str] = []
    try:
        _write_new(out_dir / "meta.yaml.draft",
                   _TEMPLATE_META_DRAFT.format(name=safe), created, skipped)
        _write_new(out_dir / "render_skeleton.py",
                   _TEMPLATE_RENDER_SKELETON.format(name=safe),
                   created, skipped)
        _write_new(out_dir / "test_skeleton.py",
                   _TEMPLATE_TEST_SKELETON.format(safe=safe), created, skipped)
        _write_new(out_dir / "CHECKLIST.md",
                   _checklist_markdown(
                       f"{safe} 模板注册消费钉清单",
                       TEMPLATE_PIN_CHECKLIST, _TEMPLATE_IRON_RULES),
                   created, skipped)
    except (SyntaxError, OSError) as exc:
        return error_envelope([f"骨架落盘失败: {type(exc).__name__}: {exc}"])
    if not created:
        return error_envelope(
            [f"全部产物已存在，未写任何文件（输出目录: {out_dir})"])
    return ok_envelope(
        schema=DEV_SCAFFOLD_SCHEMA,
        kind="template",
        name=safe,
        out_dir=str(out_dir),
        created=created,
        skipped=skipped,
        next_steps=[
            f"补齐 {out_dir / 'render_skeleton.py'} 占位段（名义值走 "
            "core/synthesis 精算）",
            "按 CHECKLIST.md 五钉逐项落地后跑定向门",
        ],
    )


def scaffold_calculator(name: str, output_dir: str | Path | None = None) -> dict[str, Any]:
    """生成新计算器骨架（@register_calculator 占位 + 消费钉清单）。"""
    safe = _safe_name(name)
    if not safe or safe[0].isdigit():
        return error_envelope([f"非法计算器名: {name}"])
    out_dir = Path(output_dir) if output_dir else Path("scripts") / "scaffold"
    created: list[str] = []
    skipped: list[str] = []
    try:
        _write_new(out_dir / f"{safe}_calculator_skeleton.py",
                   _CALCULATOR_SKELETON.format(safe=safe), created, skipped)
        _write_new(out_dir / f"{safe}_CHECKLIST.md",
                   _checklist_markdown(
                       f"{safe} 计算器注册消费钉清单",
                       CALCULATOR_PIN_CHECKLIST),
                   created, skipped)
    except (SyntaxError, OSError) as exc:
        return error_envelope([f"骨架落盘失败: {type(exc).__name__}: {exc}"])
    if not created:
        return error_envelope(
            [f"全部产物已存在，未写任何文件（输出目录: {out_dir})"])
    return ok_envelope(
        schema=DEV_SCAFFOLD_SCHEMA,
        kind="calculator",
        name=safe,
        out_dir=str(out_dir),
        created=created,
        skipped=skipped,
        next_steps=[
            "把骨架注册段迁入 core/calc_families 相应家族模块（骨架文件"
            "本身不入库）",
            "按 CHECKLIST.md 五钉逐项落地后跑定向门",
        ],
    )
