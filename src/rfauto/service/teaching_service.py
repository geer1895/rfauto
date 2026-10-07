"""EP-5 教学模式三件服务面（物理推导节+教科书反向索引+参数化自测题库）。

规格 研究扩充 round18 §二 EP-5：capability_cards
加"物理与推导"节（+敏感度数据）+教科书反向索引（Pozar/Balanis/Cameron
章节→模块）+参数化自测题库；首批 ≥8 卡。

**铁律 7 合规口径**：

- 题库**答案只由确定性内核产出**（``solve`` 闭式/repo kernel 现算，
  ``check_answer`` 即时求值比对——题面参数化，答案永不内置）；
- **物理数字全部带出处**：每张卡的推导（``physics.derivations[].source``）
  与每道题的 ``source`` 都指回仓内已核来源（docs/rf_template_references.md
  的官方例对照口径 / knowledge/rules.yaml / 逐式在 docstring 的内核模块），
  出处锚文本由 tests/unit/test_teaching_service.py 逐条对 grounding 文件
  核验（教科书作者名必须在 references/rules 文件在场——引用链可复核，
  不接受 LLM 自编出处）；
- 敏感度排序用 **order（名次）+ basis（依据）** 而非臆造幅值：名次来自
  可复核的闭式恒等式（如 λ/4 恒等式 |∂lnf₀/∂lnL|≡1）与 repo 已核机制
  （c(gap) 真机图谱）；幅值分数留给归属面的 Sobol 数据管线
  （capability_cards 导出器的 knowledge/sensitivity_rankings.yaml 契约）。

**卡面接线说明**：capability cards（docs/capability_cards/*.md）由
scripts/capability_cards_export.py 离线生成（该导出器与 docs/capability_
cards/ 不在本席文件面）；教学节数据落 docs/templates/<t>/meta.yaml 的
``teaching:`` 块（模板卡本体），本模块提供加载/校验/markdown 渲染消费面；
导出器接入留 scripts 归属面批次（如实登记，不双写生成物）。

**教科书反向索引**（``TEXTBOOK_INDEX``）：教科书章节→仓内模板/模块映射，
章节串与 docs/rf_template_references.md 已核口径逐字同源（测试钉）。

接口纪律：dict/JSON 进出；题库 ``solve`` 为模块内确定性函数；零网络零
LLM 零随机。
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
TEMPLATES_DIR = REPO_ROOT / "docs" / "templates"

TEACHING_SCHEMA = "rfauto-teaching/v1"

__all__ = [
    "QUIZ_BANK",
    "TEACHING_SCHEMA",
    "TEXTBOOK_INDEX",
    "check_answer",
    "list_teaching_templates",
    "load_teaching",
    "render_quiz",
    "render_teaching_markdown",
    "textbook_index",
]

# ─── 加载与校验 ──────────────────────────────────────────────────────────────


def load_teaching(template: str) -> dict[str, Any]:
    """模板卡 ``teaching:`` 块加载+schema 校验（缺块 ValueError 如实）。"""
    if not isinstance(template, str) or not template.strip():
        raise ValueError("template 必须为非空字符串")
    import yaml

    path = TEMPLATES_DIR / template / "meta.yaml"
    if not path.is_file():
        raise ValueError(f"模板卡不存在：{path}")
    meta = yaml.safe_load(path.read_text(encoding="utf-8"))
    teaching = (meta or {}).get("teaching")
    if not isinstance(teaching, dict):
        raise ValueError(f"模板 {template} 无 teaching 块（首批未填卡如实缺）")
    if teaching.get("schema") != TEACHING_SCHEMA:
        raise ValueError(f"模板 {template} teaching.schema 必须={TEACHING_SCHEMA}")
    physics = teaching.get("physics")
    if not isinstance(physics, dict) or not physics.get("summary"):
        raise ValueError(f"模板 {template} teaching.physics.summary 必须非空")
    deriv = physics.get("derivations")
    if not isinstance(deriv, list) or not deriv:
        raise ValueError(f"模板 {template} physics.derivations 必须为非空列表")
    for i, d in enumerate(deriv):
        if not isinstance(d, dict):
            raise ValueError(f"{template}.derivations[{i}] 必须为 dict")
        for key in ("claim", "formula", "source"):
            if not isinstance(d.get(key), str) or not d[key].strip():
                raise ValueError(f"{template}.derivations[{i}].{key} 必须为非空字符串")
    ranking = teaching.get("sensitivity_ranking")
    if not isinstance(ranking, list) or not ranking:
        raise ValueError(f"模板 {template} sensitivity_ranking 必须为非空列表")
    orders = []
    for i, r in enumerate(ranking):
        if not isinstance(r, dict):
            raise ValueError(f"{template}.sensitivity_ranking[{i}] 必须为 dict")
        for key in ("param", "basis"):
            if not isinstance(r.get(key), str) or not r[key].strip():
                raise ValueError(f"{template}.sensitivity_ranking[{i}].{key} 必须为非空字符串")
        order = r.get("order")
        if isinstance(order, bool) or not isinstance(order, int) or order < 1:
            raise ValueError(f"{template}.sensitivity_ranking[{i}].order 必须为正整数名次")
        orders.append(order)
    if sorted(orders) != list(range(1, len(ranking) + 1)):
        raise ValueError(f"模板 {template} sensitivity_ranking 名次必须为 1..N 连续（确定性全序）")
    return dict(teaching)


def list_teaching_templates() -> list[str]:
    """已填教学卡的模板清单（docs/templates/<t>/meta.yaml 带 teaching 块）。"""
    out: list[str] = []
    if not TEMPLATES_DIR.is_dir():
        return out
    for d in sorted(TEMPLATES_DIR.iterdir()):
        meta = d / "meta.yaml"
        if not d.is_dir() or not meta.is_file():
            continue
        try:
            import yaml

            data = yaml.safe_load(meta.read_text(encoding="utf-8")) or {}
        except OSError:
            continue
        if isinstance(data, dict) and isinstance(data.get("teaching"), dict):
            out.append(d.name)
    return out


def render_teaching_markdown(template: str) -> str:
    """教学卡 → markdown 节（"物理与推导"+"敏感性排序"两节，卡面消费形态）。"""
    t = load_teaching(template)
    lines = [f"## 物理与推导（{template}）", ""]
    lines.append(t["physics"]["summary"])
    lines.append("")
    for d in t["physics"]["derivations"]:
        lines.append(f"- {d['claim']}：`{d['formula']}`")
        lines.append(f"  出处：{d['source']}")
    lines.append("")
    lines.append("## 敏感性排序（名次+依据，幅值分待 Sobol 数据管线）")
    lines.append("")
    for r in sorted(t["sensitivity_ranking"], key=lambda x: int(x["order"])):
        lines.append(f"{r['order']}. `{r['param']}` —— {r['basis']}")
    return "\n".join(lines)


# ─── 教科书反向索引（章节串与 rf_template_references.md 已核口径同源）────────

TEXTBOOK_INDEX: tuple[dict[str, Any], ...] = (
    {
        "textbook": "D.M. Pozar, Microwave Engineering, 4th ed.",
        "chapter": "Ch.7 例 7.2（Wilkinson 功分器设计例）",
        "topics": ["Wilkinson 功分器", "λ/4 臂", "隔离电阻 2Z0"],
        "templates": ["wilkinson", "nway_wilkinson"],
        "modules": ["src/rfauto/core/synthesis.py"],
        "grounding": "docs/rf_template_references.md §1（Ansys 官方 FDTD 例同源）",
    },
    {
        "textbook": "D.M. Pozar, Microwave Engineering, 4th ed.",
        "chapter": "Ch.7（正交混合 branch-line 与 180° hybrid ring：repo 已核口径 §7.5 ratrace / §7.6 耦合线与 Lange）",
        "topics": ["branchline 正交混合", "rat-race 180° 混合环", "耦合线定向耦合器", "Lange 电桥"],
        "templates": ["branchline", "branchline_2sect", "ratrace", "cline_coupler", "lange", "gysel", "tjunc"],
        "modules": ["src/rfauto/core/synthesis.py"],
        "grounding": "docs/rf_template_references.md §13.1-§13.2 与 ratrace 权威口径节",
    },
    {
        "textbook": "C.A. Balanis, Antenna Theory: Analysis and Design, 3rd ed.",
        "chapter": "Ch.4 Linear Wire Antennas（半波偶极子谐振输入阻抗 ≈73+j42.5 Ω）",
        "topics": ["偶极子", "单极子", "谐振长度/输入阻抗"],
        "templates": ["dipole", "monopole", "ifa", "pifa"],
        "modules": ["src/rfauto/core/synthesis.py"],
        "grounding": "docs/rf_template_references.md 馈电阻节（谐振阻抗 ~73Ω 口径）",
    },
    {
        "textbook": "C.A. Balanis, Antenna Theory: Analysis and Design, 3rd ed.",
        "chapter": "Ch.13 Horn Antennas（最优厚度档 δ_H=3λ/8、δ_E=λ/4）",
        "topics": ["角锥喇叭", "口径场设计"],
        "templates": ["pyramid_horn"],
        "modules": ["src/rfauto/core/horn_synthesis.py"],
        "grounding": "docs/rf_template_references.md ME-7（σh=√1.5、σe=1 缺省综合档）",
    },
    {
        "textbook": "C.A. Balanis, Antenna Theory: Analysis and Design, 3rd ed.",
        "chapter": "Ch.14 Microstrip Antennas（传输线/腔模型）",
        "topics": ["贴片宽度 W", "εeff 薄线式", "ΔL 边缘延伸"],
        "templates": ["patch", "ms_patch", "ms_ring_patch", "patch_array_1x4", "patch_array_2x2"],
        "modules": ["src/rfauto/core/synthesis.py"],
        "grounding": "docs/rf_template_references.md C2 阵列族（W=c/(2f0)·√(2/(εr+1)) 已核）",
    },
    {
        "textbook": "J.-S. Hong & M.J. Lancaster, Microstrip Filters for RF/Microwave Applications, Wiley 2001",
        "chapter": "§5 耦合谐振器测量节（k=(f₂²−f₁²)/(f₂²+f₁²) 恒等式；外部 Q 群时延法）",
        "topics": ["耦合系数", "外部 Q", "发夹/交指滤波器综合"],
        "templates": ["hairpin", "hairpin_alt", "interdigital", "combline", "coupled_bpf", "sir_bpf"],
        "modules": ["src/rfauto/core/synthesis.py"],
        "grounding": "docs/rf_template_references.md §11.2/§15（Makimoto-Yamashita 耦合谐振章同口径）",
    },
    {
        "textbook": "S.G. Orfanidis, Electromagnetic Waves & Antennas",
        "chapter": "Ch.21 口径面天线（增益 21.4.2/口径效率 21.4.3/设计方程 21.5.1）",
        "topics": ["角锥喇叭增益", "口径效率", "最优尺寸设计方程"],
        "templates": ["pyramid_horn"],
        "modules": ["src/rfauto/core/horn_synthesis.py"],
        "grounding": "docs/rf_template_references.md ME-7（式号逐条在 docstring；Ex.21.5.1/21.5.2 锚）",
    },
    {
        "textbook": "E. Hammerstad & Ø. Jensen (IEEE MTT-S 1980)；E. Hammerstad (1975)",
        "chapter": "微带线综合模型（HJ 精确闭式）",
        "topics": ["微带 Z0/εeff 正反解", "线宽综合"],
        "templates": ["mline", "wstep", "bend", "via", "stripline", "suspended_stripline"],
        "modules": ["src/rfauto/core/synthesis.py"],
        "grounding": "docs/rf_template_references.md §1（微带综合公式口径「不拍脑袋」）与 R005 线宽定案",
    },
    {
        "textbook": "Qucs technical document §12（Gupta 部分电容口径）",
        "chapter": "共面波导/共面条带闭式",
        "topics": ["CPW/CPS Z0 与 εeff", "填充比"],
        "templates": ["cpw", "cps", "msl_cpw", "fgcpw"],
        "modules": ["src/rfauto/core/synthesis.py"],
        "grounding": "docs/rf_template_references.md CPW 闭式节（与 _cpwg_ri 逐式吻合已核）",
    },
)


def textbook_index(textbook: str | None = None) -> dict[str, Any]:
    """教科书反向索引查询（textbook=None 全表；给定则子串过滤，大小写不敏）。"""
    rows = list(TEXTBOOK_INDEX)
    if textbook is not None:
        key = textbook.lower()
        rows = [r for r in rows if key in r["textbook"].lower()]
    return {
        "schema": TEACHING_SCHEMA,
        "n_rows": len(rows),
        "rows": rows,
    }


# ─── 参数化自测题库（答案只由确定性内核现算——铁律 7）────────────────────────

_C_MM_GHZ = 299.792458  # mm·GHz（光速实用制，repo synthesis 同值）


def _solve_mline_z0(p: dict[str, float]) -> float:
    from rfauto.core.synthesis import Stackup, forward_z0

    z0, _ = forward_z0(p["w_mm"], p["f0_ghz"], Stackup("quiz", p["er"], p["h_mm"]))
    return float(z0)


def _solve_patch_w(p: dict[str, float]) -> float:
    # Balanis Ch.14 传输线模型：W = c/(2 f0)·√(2/(εr+1))
    return _C_MM_GHZ / (2.0 * p["f0_ghz"]) * math.sqrt(2.0 / (p["er"] + 1.0))


def _solve_wilkinson_arm_len(p: dict[str, float]) -> float:
    from rfauto.core.synthesis import synthesize_wilkinson

    return float(synthesize_wilkinson(f0_ghz=p["f0_ghz"], z0_ohm=p["z0_ohm"]).params["arm_len_mm"])


def _solve_wilkinson_zt(p: dict[str, float]) -> float:
    # λ/4 臂阻抗 = √2·Z0（Pozar 例 7.2；repo synthesize_wilkinson 同式）
    return math.sqrt(2.0) * p["z0_ohm"]


def _solve_qwt_impedance(p: dict[str, float]) -> float:
    # λ/4 阻抗变换器：Z_t = √(Z0·ZL)（Pozar Ch.5 阻抗匹配）
    return math.sqrt(p["z0_ohm"] * p["zl_ohm"])


def _solve_coupling_k(p: dict[str, float]) -> float:
    # 耦合谐振器模分裂恒等式 k=(f₂²−f₁²)/(f₂²+f₁²)（Hong & Lancaster §5）
    f1, f2 = sorted((float(p["f1_ghz"]), float(p["f2_ghz"])))
    return (f2**2 - f1**2) / (f2**2 + f1**2)


def _solve_dipole_rin(p: dict[str, float]) -> float:
    # 半波偶极子谐振输入电阻 ≈73Ω（Balanis Ch.4 文献常数；题面 len_frac=0.5 才有效）
    if abs(float(p["len_frac"]) - 0.5) > 1e-9:
        raise ValueError("本锚只定义在半波（len_frac=0.5）口径")
    return 73.0


def _solve_horn_gain(p: dict[str, float]) -> float:
    from rfauto.core.horn_synthesis import horn_gain_direct

    out = horn_gain_direct(
        a_mm=p["a_mm"], b_mm=p["b_mm"], a1_mm=p["a1_mm"], b1_mm=p["b1_mm"],
        l_mm=p["l_flare_mm"], f_ghz=p["f_ghz"],
    )
    return float(out["gain_db"])


def _solve_ratrace_circumference(p: dict[str, float]) -> float:
    from rfauto.core.synthesis import synthesize_ratrace_model

    return float(
        synthesize_ratrace_model(z0_ohm=p["z0_ohm"], freq_ghz=p["f0_ghz"]).params["r_ring_mm"]
    ) * 2.0 * math.pi


#: 题库（statement 以 str.format(**params) 参数化；solve=确定性内核现算）
QUIZ_BANK: tuple[dict[str, Any], ...] = (
    {
        "id": "Q-MLINE-Z0",
        "topic": "微带线特征阻抗",
        "statement": (
            "rogers4350b 板（εr={er}、h={h_mm}mm）上 {f0_ghz} GHz 的微带线，"
            "线宽 {w_mm} mm，按 Hammerstad-Jensen 模型特征阻抗 Z0 是多少（Ω）？"
        ),
        "params": {"er": 3.66, "h_mm": 0.508, "f0_ghz": 2.5, "w_mm": 1.113},
        "solve": _solve_mline_z0,
        "tolerance_rel": 0.01,
        "unit": "Ω",
        "source": (
            "Hammerstad-Jensen 模型（本仓 core/synthesis.py 正向锁死 "
            "model='hammerstadjensen'；口径出处 docs/rf_template_references.md §1）"
        ),
    },
    {
        "id": "Q-PATCH-W",
        "topic": "贴片宽度（传输线模型）",
        "statement": (
            "εr={er} 基板上 {f0_ghz} GHz 矩形贴片天线，按 Balanis 传输线模型"
            "宽度 W = c/(2f₀)·√(2/(εr+1)) 是多少（mm）？"
        ),
        "params": {"er": 3.66, "f0_ghz": 2.4},
        "solve": _solve_patch_w,
        "tolerance_rel": 0.005,
        "unit": "mm",
        "source": (
            "Balanis, Antenna Theory (3rd ed.), Ch.14 Microstrip Antennas"
            "（docs/rf_template_references.md C2 阵列族节已核同式）"
        ),
    },
    {
        "id": "Q-WILK-ARM",
        "topic": "Wilkinson λ/4 臂长",
        "statement": (
            "50Ω 系统 {f0_ghz} GHz Wilkinson 功分器（rogers4350b 板），"
            "λ/4 臂长（臂线宽自身 εeff 口径）是多少（mm）？"
        ),
        "params": {"f0_ghz": 2.5, "z0_ohm": 50.0},
        "solve": _solve_wilkinson_arm_len,
        "tolerance_rel": 0.01,
        "unit": "mm",
        "source": (
            "Pozar, Microwave Engineering (4th ed.), Ch.7 例 7.2"
            "（docs/rf_template_references.md §1；本仓 core/synthesis."
            "synthesize_wilkinson XA-3 迭代序：εeff 取臂线宽自身）"
        ),
    },
    {
        "id": "Q-WILK-ZT",
        "topic": "Wilkinson 臂阻抗",
        "statement": (
            "{z0_ohm} Ω 系统 Wilkinson 功分器的两根 λ/4 臂特征阻抗是多少（Ω）？"
        ),
        "params": {"z0_ohm": 50.0},
        "solve": _solve_wilkinson_zt,
        "tolerance_rel": 0.005,
        "unit": "Ω",
        "source": (
            "Pozar, Microwave Engineering (4th ed.), Ch.7 例 7.2"
            "（臂 √2·Z0、隔离电阻 2Z0；docs/rf_template_references.md §1 同源）"
        ),
    },
    {
        "id": "Q-QWT-Z",
        "topic": "λ/4 阻抗变换器",
        "statement": (
            "{z0_ohm} Ω 主线接 {zl_ohm} Ω 负载，λ/4 变换段特征阻抗 Z=√(Z0·ZL) 是多少（Ω）？"
        ),
        "params": {"z0_ohm": 50.0, "zl_ohm": 75.0},
        "solve": _solve_qwt_impedance,
        "tolerance_rel": 0.005,
        "unit": "Ω",
        "source": "Pozar, Microwave Engineering (4th ed.), Ch.5 阻抗匹配与调谐（λ/4 变换器标准结论）",
    },
    {
        "id": "Q-HAIRPIN-K",
        "topic": "耦合谐振器模分裂",
        "statement": (
            "耦合谐振器对双模谐振于 {f1_ghz} GHz 与 {f2_ghz} GHz，"
            "按 k=(f₂²−f₁²)/(f₂²+f₁²) 求耦合系数 k（无量纲）。"
        ),
        "params": {"f1_ghz": 2.475, "f2_ghz": 2.525},
        "solve": _solve_coupling_k,
        "tolerance_rel": 0.01,
        "unit": "",
        "source": (
            "J.-S. Hong & M.J. Lancaster, Microstrip Filters (Wiley 2001), §5 "
            "耦合谐振器测量节（docs/rf_template_references.md §11.2 已核；"
            "Makimoto-Yamashita 耦合谐振章同口径）"
        ),
    },
    {
        "id": "Q-DIPOLE-RIN",
        "topic": "半波偶极子输入电阻",
        "statement": (
            "长度 0.5λ（len_frac={len_frac}）的细半波偶极子，谐振输入电阻约多少（Ω）？"
        ),
        "params": {"len_frac": 0.5},
        "solve": _solve_dipole_rin,
        "tolerance_rel": 0.03,
        "unit": "Ω",
        "source": (
            "Balanis, Antenna Theory (3rd ed.), Ch.4 Linear Wire Antennas"
            "（谐振输入阻抗 ≈73+j42.5 Ω；docs/rf_template_references.md 馈电阻节 '~73Ω' 口径）"
        ),
    },
    {
        "id": "Q-HORN-GAIN",
        "topic": "角锥喇叭增益",
        "statement": (
            "WR-90 馈电角锥喇叭（a={a_mm}、b={b_mm}、口径 {a1_mm}×{b1_mm} mm、"
            "喇叭长 {l_flare_mm} mm）@ {f_ghz} GHz，口径场模型增益是多少（dB）？"
        ),
        "params": {
            "a_mm": 22.86, "b_mm": 10.16,
            "a1_mm": 76.40094536120978, "b1_mm": 57.54769444861163,
            "l_flare_mm": 45.48234099926676, "f_ghz": 10.0,
        },
        "solve": _solve_horn_gain,
        "tolerance_rel": 0.005,
        "unit": "dB",
        "source": (
            "S.G. Orfanidis, Electromagnetic Waves & Antennas, Ch.21"
            "（增益 21.4.2；docs/rf_template_references.md ME-7，式号逐条在 "
            "core/horn_synthesis.py docstring；名义设计点=15dB 综合目标）"
        ),
    },
    {
        "id": "Q-RATRACE-RING",
        "topic": "rat-race 环周长",
        "statement": (
            "{z0_ohm} Ω 系统 {f0_ghz} GHz rat-race（环阻抗 √2·Z0、周长 1.5λg），"
            "环周长是多少（mm；λg 取环线宽自身 εeff）？"
        ),
        "params": {"z0_ohm": 50.0, "f0_ghz": 2.5},
        "solve": _solve_ratrace_circumference,
        "tolerance_rel": 0.01,
        "unit": "mm",
        "source": (
            "Pozar, Microwave Engineering (4th ed.), §7.5（180° hybrid ring；"
            "docs/rf_template_references.md ratrace 权威口径节；本仓 core/"
            "synthesis.synthesize_ratrace_model 闭式：环 √2·Z0、周长 1.5λg）"
        ),
    },
)

_QUIZ_BY_ID = {q["id"]: q for q in QUIZ_BANK}


def render_quiz(qid: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """题目渲染（参数替换 + 出处随行；未知 id ValueError）。"""
    quiz = _QUIZ_BY_ID.get(qid)
    if quiz is None:
        raise ValueError(f"未知题目 id：{qid}（题库共 {len(_QUIZ_BY_ID)} 题）")
    merged = dict(quiz["params"])
    if params:
        merged.update(params)
    return {
        "id": quiz["id"],
        "topic": quiz["topic"],
        "statement": quiz["statement"].format(**merged),
        "params": merged,
        "unit": quiz["unit"],
        "source": quiz["source"],
        "tolerance_rel": quiz["tolerance_rel"],
    }


def check_answer(qid: str, answer: Any, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """答题判定：期望值由确定性内核按（可覆盖的）参数现算——答案永不内置。

    返回 {correct, expected, rel_err, tolerance_rel, unit, source}；
    answer 必须>0 有限数（相对误差语义）；answer 缺失 ValueError。
    """
    quiz = _QUIZ_BY_ID.get(qid)
    if quiz is None:
        raise ValueError(f"未知题目 id：{qid}")
    if isinstance(answer, bool) or not isinstance(answer, (int, float)):
        raise ValueError("answer 必须为数值（bool 拒收）")
    ans = float(answer)
    if not math.isfinite(ans) or ans <= 0.0:
        raise ValueError("answer 必须为正有限数（相对误差语义）")
    merged = dict(quiz["params"])
    if params:
        merged.update(params)
    expected = float(quiz["solve"](merged))
    rel_err = abs(ans - expected) / abs(expected)
    return {
        "id": quiz["id"],
        "correct": bool(rel_err <= quiz["tolerance_rel"]),
        "expected": expected,
        "rel_err": rel_err,
        "tolerance_rel": quiz["tolerance_rel"],
        "unit": quiz["unit"],
        "source": quiz["source"],
        "params": merged,
    }
