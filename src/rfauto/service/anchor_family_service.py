"""anchor_family_service：锚族覆盖盘点与 pointer 锚批量补挂计划（XC-T）。

round15 口径：「锚族」批量挂法 + **每模板至少 1 pointer 锚** + 每新增
2 模板配 1 锚族。本模块只做**计划面**（盘点+骨架生成），不写锚注册表——
knowledge/anchors.yaml 运行时只读、写入只经人工 commit；骨架锚 status=awaiting_data（DP-3 预声明扩展：骨架
如实登记、仲裁数据回填后翻 active/experimental）。

覆盖判定口径：
- 锚 ``template_family`` 列表逐项对模板注册表（adapters TEMPLATE_NOMINAL
  键集）精确匹配；
- ``*`` 通配族=全局锚（ coupled_microstrip/mmt/cps.gamma_er 等内核级），
  **不计入任何单模板覆盖**，单列 wildcard 报告；
- 未匹配注册表的具名族（如 ``c3``/``mmt``）按声明的族名如实列出（可能
  指向未注册模板名=断链线索，不臆测归并）。

首批指针锚候选表（:data:`POINTER_BATCH_CANDIDATES`）：全部选自**当前
零覆盖**模板，且各有 core 闭式内核作为对照量（锚 quantity 的裁判参照），
出处随行（坑号/docs 指针）。``pointer_anchor_batch_plan`` 输出可直接
人工 commit 的 YAML 骨架块文本（values 留空待仲裁回填）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rfauto.service.envelope import ok_envelope

_SOURCE = "rfauto.service.anchor_family_service"

#: 首批 pointer 锚候选（XC-T 首件，2026-10-03）。全部为当前零覆盖模板；
#: kernel_ref=对照闭式内核（core 单源）；refs=判读口径出处（坑号/docs）。
#: ge8e X5 批（2026-10-04）撤出 3 席：siw/slotline/ratrace 已由 analytic
#: 闭式恒等锚覆盖（siw.fc_te10_ghz/slotline.z0_ohm/ratrace.ring_z_ohm+
#: r_ring_mm.closedform-v1）——本表不变式=只含零覆盖模板（test 钉）；三族
#: 的引擎对分歧指针（openems-hfss 双值）语义仍有效，未来批可按 pointer
#: 通道重新立项（与闭式档并存不冲突，anchor_id 不同席）。
#: Phase 4 W4-E 锚批（2026-10-05）撤出 4 席：cps/coupled_bpf/hairpin/
#: suspended_stripline 已由 analytic 锚覆盖（cps.z0_ohm+cps.eps_eff/
#: coupled_bpf.cheb_g/hairpin.cheb_g+suspended_stripline.z0_ohm+
#: eps_eff 等 closedform-v1，xcheb_bpf4/hairpin_alt/varactor_bpf 同批
#: 闭式席）；同批补 3 席新候选（embedded_ms/cline_coupler/wstep，均零
#: 覆盖+core 闭式对照在档；embedded_ms/cline_coupler=X5 §四.5 原名单，
#: wstep=阶梯一阶 Γ 理想值对照）维持首批 ≥8 不变式。撤出 4 族的引擎对
#: 分歧指针语义仍有效（hairpin 交替取向耦合峰位指针涉 TODO 0dk/0cv 物理
#: 结论在档），未来批可按 pointer 通道重新立项（与闭式档并存不冲突）。
POINTER_BATCH_CANDIDATES: tuple[dict[str, Any], ...] = (
    {"template": "mline", "anchor_id": "mline.eps_eff.openems-hfss-v1",
     "quantity": {"name": "mline_eps_eff_dev_pct", "unit": "percent",
                  "metric": "eps_eff",
                  "semantics": "均匀微带 εeff 引擎对分歧指针（S21 相位斜率/"
                               "β 提取口径）；对照=synthesis.forward_z0"},
     "kernel_ref": "rfauto.core.synthesis.forward_z0",
     "refs": "#162（β 金标准）/docs/rf_template_references.md"},
    # cpw 已由 W6-F 注册锚（cpw.z0_ohm.closedform-v1，ANCHORS 60）——
    # 候选条目移除（2026-10-06：零覆盖候选表只含未注册模板）
    {"template": "lange", "anchor_id": "lange.s31_coupling.openems-hfss-v1",
     "quantity": {"name": "lange_s31_coupling_dev_db", "unit": "dB",
                  "metric": "coupling_at_f0_db",
                  "semantics": "lange 耦合度 @f0 引擎对分歧指针；对照=3dB"
                               "耦合闭式目标（有效域窄 #281 平台口径随行）"},
     "kernel_ref": "rfauto.core（3dB 耦合目标带）",
     "refs": "#335（lange 仲裁 ΔS 阶梯）/#311（指缝网格）"},
    {"template": "dipole", "anchor_id": "dipole.f_res.openems-hfss-v1",
     "quantity": {"name": "dipole_f_res_dev_pct", "unit": "percent",
                  "metric": "f_res",
                  "semantics": "半波振子谐振频率引擎对分歧指针；对照=λ/2 "
                               "闭式（端效应修正随 meta 注记）"},
     "kernel_ref": "rfauto.core（λ/2 谐振闭式）",
     "refs": "#249（PEC 镜像 Prad 双计修正）/#174（馈点场图先验）"},
    {"template": "helix", "anchor_id": "helix.gain_db.openems-hfss-v1",
     "quantity": {"name": "helix_gain_db_dev_db", "unit": "dB",
                  "metric": "gain_db",
                  "semantics": "轴向模螺旋增益引擎对分歧指针；对照=Kraus 闭式"
                               "（core/helix_axial.kraus_performance，Balanis "
                               "§10.3.1 转引；名义点落 Kraus 失效域如实注）"},
     "kernel_ref": "rfauto.core.helix_axial.kraus_performance",
     "refs": "ge8e X5 批 followUp（Kraus 域外设计点待重综合）"},
    {"template": "embedded_ms",
     "anchor_id": "embedded_ms.z0_ohm.openems-hfss-v1",
     "quantity": {"name": "embedded_ms_z0_dev_pct", "unit": "percent",
                  "metric": "z0_ohm",
                  "semantics": "嵌埋微带 Z0 引擎对分歧指针；对照=准静态"
                               "部分电容闭式（core/embedded_line."
                               "embedded_ms_quasistatic，isl_shielded."
                               "eps_eff.closedform-v1 同族闭式上游）"},
     "kernel_ref": "rfauto.core.embedded_line.embedded_ms_quasistatic",
     "refs": "ge8e X5 §四.5 候选名单/isl_shielded 同族先例（TA Wave C 席）"},
    {"template": "cline_coupler",
     "anchor_id": "cline_coupler.s31_coupling.openems-hfss-v1",
     "quantity": {"name": "cline_coupler_s31_coupling_dev_db", "unit": "dB",
                  "metric": "coupling_at_f0_db",
                  "semantics": "耦合线 3dB 电桥耦合度 @f0 引擎对分歧指针；"
                               "对照=KJ 偶奇模闭式（core/coupled_microstrip）"
                               "3dB 目标（有效域窄 #281 平台口径随行）"},
     "kernel_ref": "rfauto.core.coupled_microstrip（KJ 闭式）",
     "refs": "#335（ΔS 阶梯收敛先审）/#310（耦合间隙镜像建面）"},
    {"template": "wstep", "anchor_id": "wstep.s11_step.openems-hfss-v1",
     "quantity": {"name": "wstep_s11_step_dev_db", "unit": "dB",
                  "metric": "s11_at_step_db",
                  "semantics": "50→35Ω 单阶梯 |S11| 引擎对分歧指针；对照="
                               "一阶小反射理想 Γ=(Z2−Z1)/(Z2+Z1)=−15.1dB"
                               "（阶梯结寄生使引擎值偏离一阶理想——指针语义"
                               "即记该分歧）；对照宽=synthesis.inverse_width"
                               " 双宽闭式"},
     "kernel_ref": "rfauto.core.synthesis.inverse_width",
     "refs": "registry wstep 注记（理想 Γ=-15.1dB，inverse_width 精算）"},
)

_BATCH_DEFAULT = 8
"""首批最少模板数（任务书 ≥8；候选表 7 条全量输出由 batch_size 控制）。"""


def _template_registry() -> dict[str, Any]:
    """模板注册表（惰性导入 adapters；键集=TEMPLATE_NOMINAL）。"""
    from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL

    return dict(TEMPLATE_NOMINAL)


def anchor_family_coverage() -> dict[str, Any]:
    """每模板锚覆盖盘点（XC-T 计划面第一探针，只读注册表）。

    Returns::

        {"ok": True,
         "n_templates": N, "n_anchors": M,
         "covered": [有 ≥1 具名锚的模板...],
         "uncovered": [零具名锚覆盖的模板...],
         "coverage_ratio": covered/n_templates,
         "wildcard_anchors": [{anchor_id, template_family}...]（``*`` 全局锚）,
         "families_outside_registry": [{family, anchor_id}...]（具名族不在
           模板注册表=断链线索，如实列出）}
    """
    from rfauto.infra.anchors_store import load_anchors

    templates = _template_registry()
    anchor_set = load_anchors()
    covered: set[str] = set()
    wildcard: list[dict[str, Any]] = []
    outside: list[dict[str, Any]] = []
    n_anchors = 0
    for rec in anchor_set.records:
        n_anchors += 1
        fams = [str(f) for f in (rec.raw.get("template_family") or [])]
        if "*" in fams:
            wildcard.append({"anchor_id": rec.raw.get("anchor_id"),
                             "template_family": fams})
            continue
        for fam in fams:
            if fam in templates:
                covered.add(fam)
            else:
                outside.append({"family": fam,
                                "anchor_id": rec.raw.get("anchor_id")})
    tpl = set(templates)
    uncovered = sorted(tpl - covered)
    return ok_envelope(
        n_templates=len(tpl),
        n_anchors=n_anchors,
        covered=sorted(covered),
        uncovered=uncovered,
        coverage_ratio=(len(covered) / len(tpl)) if tpl else None,
        wildcard_anchors=wildcard,
        families_outside_registry=outside,
        source=_SOURCE,
    )


def pointer_anchor_batch_plan(batch_size: int = _BATCH_DEFAULT,
                              candidates: tuple[dict[str, Any], ...] | None = None,
                              ) -> dict[str, Any]:
    """首批 pointer 锚补挂计划：骨架清单+可人工 commit 的 YAML 块文本。

    骨架形态（anchors/v1 schema 同构）：kind=pointer、values 留空
    （{openems: null, hfss: null}）、status=awaiting_data（DP-3 预声明
    扩展）、consumers=[]（零消费指针锚）。anchor_id 与既有注册表查重，
    撞名条目剔除并如实报告（不静默跳过）。
    """
    from rfauto.infra.anchors_store import load_anchors

    cands = tuple(candidates) if candidates is not None \
        else POINTER_BATCH_CANDIDATES
    if not isinstance(batch_size, int) or batch_size <= 0:
        raise ValueError(f"batch_size 必须为正整数，得到 {batch_size!r}")
    existing = {rec.raw.get("anchor_id") for rec in load_anchors().records}
    plan: list[dict[str, Any]] = []
    skipped_collisions: list[str] = []
    for cand in cands:
        if len(plan) >= batch_size:
            break
        aid = str(cand["anchor_id"])
        if aid in existing:
            skipped_collisions.append(aid)
            continue
        q = cand["quantity"]
        plan.append({
            "anchor_id": aid,
            "kind": "pointer",
            "template_family": [str(cand["template"])],
            "engine_pair": {"calibrated": "openems", "referee": "hfss"},
            "quantity": {"name": q["name"], "unit": q["unit"],
                         "metric": q["metric"], "semantics": q["semantics"],
                         "values": {"openems": None, "hfss": None}},
            "kernel_ref": str(cand["kernel_ref"]),
            "refs": str(cand["refs"]),
            "proposed_status": "awaiting_data",
        })
    return ok_envelope(
        batch_size=batch_size,
        n_planned=len(plan),
        plan=plan,
        skipped_collisions=skipped_collisions,
        write_policy="本面只产骨架文本；anchors.yaml 写入只经人工 commit"
                        "+ 同步 EXPECTED_ANCHORS 单源",
        source=_SOURCE,
    )


def render_pointer_batch_yaml(plan: dict[str, Any]) -> str:
    """计划 → anchors/v1 追加块 YAML 文本（人工复核后 commit 用）。"""
    import yaml

    entries = []
    for item in plan.get("plan", []):
        q = item["quantity"]
        entries.append({
            "anchor_id": item["anchor_id"],
            "kind": "pointer",
            "template_family": item["template_family"],
            "engine_pair": item["engine_pair"],
            "quantity": {
                "name": q["name"], "unit": q["unit"], "metric": q["metric"],
                "semantics": q["semantics"],
                "values": {"openems": None, "hfss": None},
            },
            "value": None,
            "uncertainty": None,
            "domain": None,
            "provenance": {
                "kernel_ref": item["kernel_ref"],
                "refs": item["refs"],
                "registered_by": "XC-T 首批补挂计划（骨架，数据回填后翻 "
                                 "experimental/active）",
            },
            "fallback": "none",
            "status": "awaiting_data",
            "consumers": [],
        })
    header = ("# XC-T 首批 pointer 锚补挂骨架（由 anchor_family_service."
              "pointer_anchor_batch_plan 生成；人工复核+仲裁数据回填后翻状态）")
    body = yaml.safe_dump({"anchors": entries}, allow_unicode=True,
                          sort_keys=False, width=100)
    return header + "\n" + body


def annotate_first_batch_cards(plan: dict[str, Any],
                               templates_dir: str | Path) -> list[Path]:
    """首批模板卡 meta.yaml 追加锚族补挂注记行（**只增不改**）。

    每卡追加一行 YAML 注释（不进数据模型，零消费面影响）；已在的注记
    （按 anchor_id 探测）不重复追加。返回实际写入的 meta.yaml 路径表。
    """
    root = Path(templates_dir)
    written: list[Path] = []
    for item in plan.get("plan", []):
        fam = str((item.get("template_family") or [""])[0])
        meta = root / fam / "meta.yaml"
        if not meta.exists():
            continue
        text = meta.read_text(encoding="utf-8")
        marker = f"XC-T 锚族补挂注记: {item['anchor_id']}"
        if marker in text:
            continue
        line = f"# {marker}（pointer 骨架，待仲裁数据回填；2026-10-03 席B5）\n"
        if not text.endswith("\n"):
            text += "\n"
        meta.write_text(text + line, encoding="utf-8")
        written.append(meta)
    return written
