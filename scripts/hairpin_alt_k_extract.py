"""hairpin_alt 逐点 k 提取（双口径：k_split 主判 + k_Z 旁证）+ c 标尺 HFSS 仲裁锚任务书。

登记（排空五轮 followUp）：解锁 alt 口径逐点 k 提取/HFSS 仲裁 1-2 点锚
c 标尺。语境与实际缺口（见 tests/unit/test_hairpin_alt_k_extract.py 同源）：

  已有  scripts/hairpin_alt_ksplit.py（wf:hairpin-alt-extract）——alt 口径 k_split
        逐点提取本体（5 点：2 可分裂 + 3 合并区间化）；
  已有  scripts/hfss_hairpin_anchor.py（0.5/2.2 锚）+ scripts/hfss_hairpin_eigen_ext.py
        （ANCHORED_4PTS：0.8/1.1328 补锚）——c 标尺已有 4 点锚定 c_true；
  本缺  ①跨档案**逐点 k 汇总表**（每条曲线独立提取、双口径同表、置信注记逐点
        标注）——含 trunc100k 截断变体曲线（NrTS 触顶 |S11|max>1，#262 族）与
        350k 正式曲线分行如实留痕；
        ②**k_Z 阻抗差值口径**列（(Z0e−Z0o)/(Z0e+Z0o)，#361⑥）与 ±0.5Ω 噪声
        放大（SNL）逐点定量——openEMS 归档 sparams 只有 2 端口谐振响应、无耦
        合线对端口仿真，**引擎实测 k_Z 不存在**，逐点只报 KJ 闭式（全点，与
        hairpin_k_from_gap_mm 同源自证）+ HFSS line2t 实测（仅锚点 0.5/2.2），
        角色按 #361⑥ 钉死=旁证不作门；
        ③下一轮 HFSS 仲裁的**锚任务书**（选点规则预声明写死，真机脚本主代理
        后定）。

口径（先于数据写死）：
  主判 k_split = 2·|f2−f1|/(f2+f1)（复用 hairpin_alt_ksplit.alt_ksplit_point，
  峰检/邻域守卫/pull 修正/合并区间全同源）；主判依据=#361⑥"k 标尺主判用本征
  分裂 k_split=eigen 口径"，主判口径=k_split_eigen（alt 同源）。
  k_Z = (Z0e−Z0o)/(Z0e+Z0o)：KJ 闭式逐点（core/coupled_microstrip，Kirschning-
  Jansen 1984）+ HFSS line2t 模阻抗实测（锚点，Zvi=√(Zpi·Zpv) 重构，#361⑤）。
  SNL 警告规则（#361⑥"±0.5Ω 噪声→±30% 量级"）：对 Z0e/Z0o 注入 ±noise 单边
  与最坏对（两阻抗反号）扰动，最坏对相对漂移 ≥30% 判"k_Z SNL 支配"（warning，
  不作门）。

锚选点规则（预声明写死，确定性）：
  n1 响应面中部点：未锚 gap 中离"已锚 gap 中位数"最近者（并列取小 gap）——
     补 c(gap) 线内插覆盖最弱处；实际选出 1.6mm（唯一未锚点）。
  n2 k 最大可判点：k_split 已解析点中 k_split 最大者（最强耦端 κ 最小=模型
     失配最大处，复仲裁验证 κ 复现性）；实际选出 0.5mm（ANCHORED_4PTS 已锚，
     角色=复仲裁）。

产物（新目录，旧档零改写）：
  runs/hairpin_alt_k_extract/k_points.json        逐点表（6 条曲线×双口径×注记）
  runs/hairpin_alt_k_extract/hfss_anchor_plan.json 锚任务书（几何/验证量/预期区间/门）

运行（纯离线，零仿真，runs/ 只读）：
  .venv/Scripts/python.exe scripts/hairpin_alt_k_extract.py --analyze
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np

_SCRIPTS = Path(__file__).resolve().parent
_REPO = _SCRIPTS.parent
sys.path.insert(0, str(_REPO / "src"))

from rfauto.core.coupled_microstrip import (  # noqa: E402
    coupled_microstrip_even_odd_ohm,
    hairpin_k_from_gap_mm,
)


def _load_aks():
    """按路径加载 scripts/hairpin_alt_ksplit.py（复用 k_split 逐点提取本体）。"""
    spec = importlib.util.spec_from_file_location(
        "_hairpin_alt_ksplit", str(_SCRIPTS / "hairpin_alt_ksplit.py"))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


aks = _load_aks()

RUNS_ROOT = _REPO / "runs"
DEFAULT_ROOT = RUNS_ROOT / "hairpin_kgap_refix"
DEFAULT_OUT = RUNS_ROOT / "hairpin_alt_k_extract"
ANCHOR_V1 = RUNS_ROOT / "hairpin_hfss_anchor" / "hairpin_anchor.json"
ANCHOR_EIGEN_EXT = RUNS_ROOT / "hairpin_hfss_anchor" / "eigen_ext" / "eigen_ext_result.json"

# 逐点曲线清单（每条=独立提取行；trunc100k 为同 gap 的 NrTS 截断变体，单独成行留痕）
CURVES: list[dict] = [
    {"pt": "kgapalt_g0500", "curve_json": None, "curve_key": "kgapalt_g0500"},
    {"pt": "kgapalt_g0800", "curve_json": None, "curve_key": "kgapalt_g0800"},
    {"pt": "kgapalt_g11328", "curve_json": None, "curve_key": "kgapalt_g11328"},
    {"pt": "kgapalt_g1600", "curve_json": None, "curve_key": "kgapalt_g1600"},
    {"pt": "kgapalt_g2200", "curve_json": None, "curve_key": "kgapalt_g2200"},
    {"pt": "kgapalt_g11328_trunc100k", "curve_json": "kgap_curve_g11328_trunc100k.json",
     "curve_key": "kgapalt_g11328_trunc100k"},
]
# 正式 5 点图（trunc100k 变体不入 gap 图谱，只作逐点行留痕）
MAP_GAPS = [0.5, 0.8, 1.1328, 1.6, 2.2]

PRIMARY_CALIBER = "k_split"
K_Z_NOISE_OHM = 0.5          # #361⑥ 阻抗噪声幅度（Ω）
K_Z_SNL_WARNING_PCT = 30.0   # 最坏对漂移 ≥30% 判 SNL 支配（#361⑥"±30% 量级"）
ANCHOR_GATE_PCT = 15.0       # 主判 ±15% 门（与 ANCHORED_4PTS 判别带同值）
REPRODUCE_GATE_PCT = 5.0     # 复仲裁点本征重现门（预声明；自适应网格余量，非实测分布）
# NrTS 截断签名阈值：max|S11| 超无源界 >0.1% 判截断假象（#262/#343 实测签名
# +2.04%=1.0204；EndCriteria 干净停机（g1600/g2200 早停 250k）实测 ≤+0.01%=
# DFT 数值噪声级，不判截断——介于其间如实记 overshoot 留痕）
TRUNC_OVERSHOOT_TOL = 1e-3

ANCHOR_SELECTION_RULE = {
    "n_slots": 2,
    "n1_middle": "响应面中部点：未锚 gap 中离已锚 gap 中位数最近者，并列取小 gap",
    "n2_kmax": "k 最大可判点：k_split 已解析点中 k_split 最大者，并列取小 gap；"
               "已锚则角色=复仲裁（κ 复现性验证）",
    "dedup": "n1 与 n2 选出同一点时 n2 顺延 k 序次优点（slot 序去重）",
}


# ── k_Z 阻抗差值口径（旁证；纯函数）──────────────────────────────────


def k_z_from_impedances(z0e_ohm: float, z0o_ohm: float) -> float:
    """k_Z=(Z0e−Z0o)/(Z0e+Z0o)（#361⑥ 同式）；要求 Z0e>Z0o>0（偶模阻抗较高，#307）。"""
    ze, zo = float(z0e_ohm), float(z0o_ohm)
    if not (ze > zo > 0.0):
        raise ValueError(f"Z0e/Z0o 病态（{ze}, {zo}）；要求 Z0e>Z0o>0")
    return float((ze - zo) / (ze + zo))


def k_z_noise_drift_pct(z0e_ohm: float, z0o_ohm: float,
                        noise_ohm: float = K_Z_NOISE_OHM) -> dict:
    """阻抗噪声 → k_Z 相对漂移（#361⑥ SNL 放大实证，确定性穷举符号组合）。

    n>0 时弱耦点最坏组合分子可变负（k 塌缩为 0）——该组合漂移记 100% 上限。
    Returns:
        {"k_z": ..., "single_sided_max_pct": 单边（只扰一个阻抗）最大漂移,
         "worst_pair_pct": 最坏对（两阻抗反号）漂移, "per_combo_pct": [...]}
    """
    n = float(noise_ohm)
    if n <= 0.0:
        raise ValueError("noise_ohm 须 >0")
    k0 = k_z_from_impedances(z0e_ohm, z0o_ohm)
    combos: list[dict] = []
    for dz_e, dz_o in ((n, 0.0), (-n, 0.0), (0.0, n), (0.0, -n),
                       (n, -n), (-n, n)):
        num = (float(z0e_ohm) + dz_e) - (float(z0o_ohm) + dz_o)
        den = (float(z0e_ohm) + dz_e) + (float(z0o_ohm) + dz_o)
        k1 = num / den
        drift = 100.0 if k1 <= 0.0 else abs(k1 / k0 - 1.0) * 100.0
        combos.append({"dz_e_ohm": dz_e, "dz_o_ohm": dz_o,
                       "k_z": float(k1), "drift_pct": float(drift)})
    single = [c["drift_pct"] for c in combos if (c["dz_e_ohm"], c["dz_o_ohm"]) in
              ((n, 0.0), (-n, 0.0), (0.0, n), (0.0, -n))]
    worst_pair = max(c["drift_pct"] for c in combos
                     if c["dz_e_ohm"] * c["dz_o_ohm"] < 0)
    return {"k_z": k0, "noise_ohm": n,
            "single_sided_max_pct": float(max(single)),
            "worst_pair_pct": float(worst_pair),
            "per_combo_pct": combos}


def kj_impedances(gap_mm: float, w_mm: float = 1.1117) -> dict:
    """KJ 闭式逐点 Z0e/Z0o/k_Z（core 同源自证：k_Z 闭式 ≡ hairpin_k_from_gap_mm）。"""
    ze, zo, eps_e, eps_o = coupled_microstrip_even_odd_ohm(
        float(w_mm), float(gap_mm), 2.5)
    kz = k_z_from_impedances(ze, zo)
    k_core = hairpin_k_from_gap_mm(float(gap_mm), float(w_mm), 2.5)
    if abs(kz / k_core - 1.0) > 1e-9:
        raise AssertionError(
            f"gap={gap_mm}: k_Z 闭式 {kz} 与 core hairpin_k_from_gap_mm {k_core} 不一致")
    return {"z0e_ohm": float(ze), "z0o_ohm": float(zo),
            "delta_z0_ohm": float(ze - zo), "k_z_kj": kz,
            "eps_eff_even": float(eps_e), "eps_eff_odd": float(eps_o)}


# ── 逐点提取（每条曲线独立一行）──────────────────────────────────────


def _read_s11_max(path: Path) -> float:
    """sparams.csv → max|S11|（截断签名自证：>1 即 #262 族 NrTS 触顶假象）。"""
    import csv

    with open(path, encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    arr = np.array([[float(x) for x in r[:5]] for r in rows[1:]])
    return float(np.max(np.abs(arr[:, 1] + 1j * arr[:, 2])))


def extract_point(curve: dict, root: Path, qe: float, q_u: float,
                  curve_rec: dict, anchors: dict[float, dict],
                  kz_noise_ohm: float = K_Z_NOISE_OHM) -> dict:
    """单条曲线独立提取：k_split 主判（复用 alt_ksplit_point）+ k_Z 旁证 + 逐点注记。

    Args:
        curve: {"pt", "curve_json", "curve_key"}（trunc100k 变体读自己的 curve json）。
        root: 归档根（runs/hairpin_kgap_refix）。
        qe, q_u: tau043 同源单腔标定（对称模型参照界用）。
        curve_rec: 该曲线的归档 k_EM 行（k_kj/k_em/method/verdict）。
        anchors: gap → HFSS 锚 dict（k_split_eigen/line k_Z 等，无锚缺省）。
    """
    pt = curve["pt"]
    work = root / pt
    calib = json.loads((work / "calib.json").read_text(encoding="utf-8"))
    gap = float(calib["calib_params"]["gap_mm"])
    w = float(calib["calib_params"]["w_mm"])
    if abs(gap - float(curve_rec["gap_mm"])) > 1e-9:
        raise AssertionError(f"{pt}: calib gap {gap} 与曲线档案 {curve_rec['gap_mm']} 不一致")
    k_kj = float(curve_rec["k_kj"])
    if abs(hairpin_k_from_gap_mm(gap, w, 2.5) / k_kj - 1.0) > 1e-6:
        raise AssertionError(f"{pt}: core 复算 k_KJ 与归档 {k_kj} 不一致")

    s11_max = _read_s11_max(work / "sparams.csv")
    s11_overshoot = max(0.0, s11_max - 1.0)
    truncated = s11_overshoot > TRUNC_OVERSHOOT_TOL
    f, s21 = aks.read_sparams_csv(work / "sparams.csv")
    res = aks.alt_ksplit_point(
        f, s21, qe, q_u, k_kj,
        k_ref=(float(curve_rec["k_em"])
               if curve_rec.get("k_em") is not None else None),
        k_ref_method=str(curve_rec.get("method")),
        k_ref_verdict=str(curve_rec.get("verdict")))

    kjz = kj_impedances(gap, w)
    snl = k_z_noise_drift_pct(kjz["z0e_ohm"], kjz["z0o_ohm"],
                              noise_ohm=kz_noise_ohm)
    kz = {
        "k_kj": kjz["k_z_kj"], "z0e_ohm": kjz["z0e_ohm"], "z0o_ohm": kjz["z0o_ohm"],
        "delta_z0_ohm": kjz["delta_z0_ohm"],
        "k_hfss_line2t": None, "z0e_hfss_ohm": None, "z0o_hfss_ohm": None,
        "snl": {"noise_ohm": snl["noise_ohm"],
                "single_sided_max_pct": snl["single_sided_max_pct"],
                "worst_pair_pct": snl["worst_pair_pct"],
                "snl_dominant": bool(snl["worst_pair_pct"] >= K_Z_SNL_WARNING_PCT)},
    }
    anc = anchors.get(gap)
    if anc is not None and anc.get("line") is not None:
        ln = anc["line"]
        kz["k_hfss_line2t"] = float(ln["k_z"])
        kz["z0e_hfss_ohm"] = float(ln["z0e_ohm"])
        kz["z0o_hfss_ohm"] = float(ln["z0o_ohm"])

    notes: list[str] = []
    mp = res["mode_pair"]
    if res["k_split"] is not None:
        notes.append(f"双峰 {mp['quality']}（谷深 {mp['valley_depth_db']:.2f}dB）"
                     f"→ k_split 主判出值")
    else:
        notes.append("SINGLE_PEAK_MERGED（k·Q_L≲1 物理合并）→ 区间化"
                     " [k_ref(归档), k_merge(对称模型参照上界)]")
    if truncated:
        notes.append(f"NrTS 触顶截断（max|S11|={s11_max:.4f}>1，超界 "
                     f"{s11_overshoot * 100:.2f}%>{TRUNC_OVERSHOOT_TOL * 100:.1f}%，"
                     "#262 族假象）→ 本曲线提取不采信（untrusted），仅留痕")
    elif s11_overshoot > 0.0:
        notes.append(f"max|S11|={s11_max:.4f} 超无源界 {s11_overshoot * 100:.3f}%"
                     "（数值噪声级，EndCriteria 干净停机，不判截断）")
    if str(curve_rec.get("verdict")) == "WIDTH_FAIL":
        notes.append(f"归档 k_ref 为 {curve_rec.get('method')}/WIDTH_FAIL 档"
                     "（对称模型失配高估）——仅作区间下界，不作置信来源")
    if anc is not None:
        ks_e = anc["eigen"]["k_split_eigen"]
        merged_verdict = anc.get("merged_verdict")
        if res["k_split"] is not None:
            dev = (res["k_split"] / ks_e - 1.0) * 100.0
            notes.append(f"锚定：k_split vs HFSS eigen {dev:+.1f}%"
                         f"（±{ANCHOR_GATE_PCT:.0f}% 门"
                         f"{'内' if abs(dev) <= ANCHOR_GATE_PCT else '外'}）")
        if merged_verdict == "SPLIT_MERGE_IS_RESOLUTION":
            notes.append("HFSS 本征证合并=响应面分辨极限（非伪象/非物理简并，"
                         "本征证据）")
    if kz["snl"]["snl_dominant"]:
        notes.append(f"k_Z SNL 支配：ΔZ0={kz['delta_z0_ohm']:.2f}Ω，±{K_Z_NOISE_OHM}Ω "
                     f"最坏对漂移 {kz['snl']['worst_pair_pct']:.0f}%（#361⑥，"
                     "旁证不作门）")

    primary = None if truncated else res["k_split"]
    return {
        "pt_id": pt,
        "gap_mm": gap, "w_mm": w,
        "params": {"order": calib["calib_params"].get("order"),
                   "arm_len_mm": calib["calib_params"].get("arm_len_mm"),
                   "arm_gap_mm": calib["calib_params"].get("arm_gap_mm"),
                   "tap_frac": calib["calib_params"].get("tap_frac"),
                   "mesh_mm": calib.get("mesh_mm"),
                   "window_ghz": calib.get("window_ghz"),
                   "f0_ghz": calib.get("f0_ghz"), "fbw": calib.get("fbw"),
                   "nr_ts": calib.get("nr_ts")},
        "in_gap_map": gap in MAP_GAPS and not truncated,
        "max_abs_s11": s11_max, "s11_overshoot": s11_overshoot,
        "truncated": truncated,
        "k_split": {
            "value": res["k_split"], "k_sq": res["k_split_sq"],
            "pull_corrected": res["k_split_pull_corrected"],
            "quality": mp["quality"], "valley_depth_db": mp["valley_depth_db"],
            "f1_ghz": mp["f1_ghz"], "f2_ghz": mp["f2_ghz"],
            "merged": res["merged"],
            "k_merge_symmodel": res["k_merge_symmodel"],
            "k_plausible_interval": res["k_plausible_interval"],
            "k_quantization": res["k_quantization"],
        },
        "k_z": kz,
        "k_em_archived": {"value": curve_rec.get("k_em"),
                          "method": curve_rec.get("method"),
                          "verdict": curve_rec.get("verdict"),
                          "c_kgap": curve_rec.get("c_kgap")},
        "k_kj": k_kj,
        "anchor": (None if anc is None else {
            "k_split_eigen_hfss": anc["eigen"]["k_split_eigen"],
            "kappa_suggest": anc.get("kappa"),
            "dev_split_vs_eigen_pct": ((res["k_split"] / anc["eigen"]["k_split_eigen"] - 1.0) * 100.0
                                       if res["k_split"] is not None else None),
            "dev_pull_corrected_vs_eigen_pct": (
                (float(res["k_split_pull_corrected"]) / anc["eigen"]["k_split_eigen"] - 1.0) * 100.0
                if res["k_split_pull_corrected"] is not None else None),
            "source": anc.get("source")}),
        "primary_value": primary,
        "primary_interval": (None if primary is not None
                             else res["k_plausible_interval"]),
        "confidence_notes": notes,
    }


def load_anchors() -> dict[float, dict]:
    """汇集两批 HFSS 锚（0.5/2.2=hairpin_anchor；0.8/1.1328=eigen_ext），只读。"""
    anchors: dict[float, dict] = {}
    if ANCHOR_V1.exists():
        v1 = json.loads(ANCHOR_V1.read_text(encoding="utf-8"))
        for g, vp in v1["verdict"]["points"].items():
            anchors[float(g)] = {
                "eigen": {"k_split_eigen": vp["eigen"]["k_split_eigen"]},
                "line": (vp.get("line") or None),
                "kappa": v1["verdict"]["kappa_by_gap"].get(g),
                "source": "runs/hairpin_hfss_anchor/hairpin_anchor.json",
            }
    if ANCHOR_EIGEN_EXT.exists():
        e2 = json.loads(ANCHOR_EIGEN_EXT.read_text(encoding="utf-8"))
        for g, vp in e2["verdict"]["points"].items():
            anchors[float(g)] = {
                "eigen": {"k_split_eigen": vp["k_split_eigen"]},
                "line": None,
                "kappa": vp.get("kappa_lin"),
                "merged_verdict": vp.get("merged_verdict"),
                "source": "runs/hairpin_hfss_anchor/eigen_ext/eigen_ext_result.json",
            }
    return anchors


def analyze(root: Path = DEFAULT_ROOT, kz_noise_ohm: float = K_Z_NOISE_OHM) -> dict:
    """逐点主入口：6 条曲线独立提取 → 汇总表 + 曲线级 verdict + 锚任务书数据。"""
    curve_main = json.loads((root / "kgap_curve.json").read_text(encoding="utf-8"))
    qe, q_u = float(curve_main["qe_em"]), float(curve_main["q_u"])
    recs: dict[str, dict] = {str(p["pt"]): p for p in curve_main["points"]}
    trunc_json = root / "kgap_curve_g11328_trunc100k.json"
    if trunc_json.exists():
        tc = json.loads(trunc_json.read_text(encoding="utf-8"))
        for p in tc["points"]:
            recs[str(p["pt"])] = p
    anchors = load_anchors()

    rows = [extract_point(c, root, qe, q_u, recs[c["pt"]], anchors,
                          kz_noise_ohm=float(kz_noise_ohm))
            for c in CURVES]

    # 曲线级 verdict（主判口径标注；#361⑥）
    map_rows = [r for r in rows if r["in_gap_map"]]
    n_resolved = sum(1 for r in map_rows if r["k_split"]["quality"] == "resolved")
    n_shallow = sum(1 for r in map_rows if r["k_split"]["quality"] == "shallow_valley")
    n_merged = sum(1 for r in map_rows if r["k_split"]["merged"])
    anchored = {r["gap_mm"]: r["anchor"]["k_split_eigen_hfss"]
                for r in rows if r["anchor"] is not None}
    c_true = {r["gap_mm"]: r["anchor"]["k_split_eigen_hfss"] / r["k_kj"]
              for r in rows if r["anchor"] is not None}
    kz_rows = [r for r in rows if r["k_z"]["snl"]["snl_dominant"]]
    verdict = {
        "primary_caliber": PRIMARY_CALIBER,
        "primary_basis": "k_split 与 HFSS 仲裁主判同源（k_split_eigen；"
                         "#361⑥ k 标尺主判=本征分裂口径）",
        "k_z_role": "corroboration_only（旁证不作门，#361⑥）；openEMS 归档无耦合线对"
                    "端口仿真→无引擎实测 k_Z，逐点只报 KJ 闭式（全点）+HFSS line2t"
                    "（锚点 0.5/2.2）",
        "k_z_snl_rule": f"±{K_Z_NOISE_OHM}Ω 最坏对漂移 ≥{K_Z_SNL_WARNING_PCT:.0f}% 判"
                        "SNL 支配（warning 不作门）",
        "per_point_extracted": True,
        "n_curves": len(rows),
        "n_map_points": len(map_rows),
        "n_split_resolved": n_resolved,
        "n_split_shallow": n_shallow,
        "n_merged": n_merged,
        "n_untrusted_truncation": sum(1 for r in rows if r["truncated"]),
        "anchored_gaps": sorted(anchored),
        "c_true_anchored": {str(g): c_true[g] for g in sorted(c_true)},
        "kz_snl_dominant_gaps": sorted(float(r["gap_mm"]) for r in kz_rows),
        "kz_dual_basis_gaps": sorted(float(r["gap_mm"]) for r in rows
                                     if r["k_z"]["k_hfss_line2t"] is not None),
    }
    return {"verdict": verdict, "points": rows,
            "qe_qu_prior": {"qe": qe, "q_u": q_u,
                            "source": "runs/hairpin_kgap_refix/kgap_curve.json（tau043）"}}


# ── 锚选点（预声明规则，确定性）──────────────────────────────────────


def select_anchor_candidates(rows: list[dict]) -> list[dict]:
    """锚选点（ANCHOR_SELECTION_RULE 写死；确定性，并列取小 gap）。

    n1 响应面中部点：未锚（无 HFSS eigen 锚且 in_gap_map）的 gap 离已锚 gap
       中位数最近者——补 c(gap) 内插覆盖最弱处。
    n2 k 最大可判点：k_split 已解析（primary_value 非 None）点中 k_split 最大
       者——最强耦端 κ 最小（模型失配最大），复仲裁验证 κ 复现性。
    """
    anchored_gaps = sorted(float(r["gap_mm"]) for r in rows
                           if r["anchor"] is not None and r["in_gap_map"])
    if not anchored_gaps:
        return []
    med = float(np.median(anchored_gaps))
    unanchored = sorted((float(r["gap_mm"]), r["pt_id"]) for r in rows
                        if r["anchor"] is None and r["in_gap_map"])
    resolvable = sorted(((float(r["primary_value"]), float(r["gap_mm"]), r["pt_id"])
                         for r in rows if r["primary_value"] is not None),
                        key=lambda t: (-t[0], t[1]))
    picks: list[dict] = []
    picked_ids: set[str] = set()
    if unanchored:
        g, pt = min(unanchored, key=lambda t: (abs(t[0] - med), t[0]))
        picks.append({"slot": "n1_middle", "rule": ANCHOR_SELECTION_RULE["n1_middle"],
                      "gap_mm": g, "pt_id": pt,
                      "detail": f"已锚中位 {med:.4f}mm；未锚集 "
                                f"{[u[0] for u in unanchored]}"})
        picked_ids.add(pt)
    for kmax, g, pt in resolvable:   # n2 与 n1 重合时顺延次优（slot 序去重）
        if pt in picked_ids:
            continue
        role = ("复仲裁（该点已锚：κ 复现性验证）" if g in anchored_gaps
                else "首次锚定")
        picks.append({"slot": "n2_kmax_resolved",
                      "rule": ANCHOR_SELECTION_RULE["n2_kmax"],
                      "gap_mm": g, "pt_id": pt,
                      "k_split_openems": kmax, "role": role})
        picked_ids.add(pt)
        break
    return picks


def build_anchor_plan(result: dict, root: Path = DEFAULT_ROOT) -> dict:
    """HFSS 仲裁锚任务书（真机脚本主代理后定；本函数只产数据契约）。"""
    rows = result["points"]
    by_gap = {float(r["gap_mm"]): r for r in rows}
    picks = select_anchor_candidates(rows)
    c_true = {float(g): v for g, v in result["verdict"]["c_true_anchored"].items()}
    anchored_gaps = sorted(c_true)
    candidates = []
    for pick in picks:
        r = by_gap[pick["gap_mm"]]
        expected: dict = {}
        if pick["slot"] == "n1_middle":
            # κ 线内插预测（c_true 对 gap 线性内插 × k_KJ）±15% 门 + openEMS 参照区间
            c_pred = float(np.interp(pick["gap_mm"],
                                     np.asarray(anchored_gaps, dtype=float),
                                     np.asarray([c_true[g] for g in anchored_gaps])))
            k_pred = c_pred * float(r["k_kj"])
            expected = {
                "basis": "κ 线（c_true 锚定线）对 gap 线性内插 × k_KJ；±15% 门"
                         "（ANCHORED_4PTS 判别带同值）",
                "c_true_interp": c_pred,
                "k_pred": k_pred,
                "k_pred_interval_pct": ANCHOR_GATE_PCT,
                "openems_plausible_interval": r["k_split"]["k_plausible_interval"],
            }
        else:
            prev = r["anchor"]["k_split_eigen_hfss"]
            expected = {
                "basis": "已锚点复仲裁：与既有本征值比对（重现门）+κ 复现性",
                "k_eigen_previous": prev,
                "kappa_previous": r["anchor"]["kappa_suggest"],
                "reproduce_gate_pct": REPRODUCE_GATE_PCT,
                "reproduce_gate_note": "预声明工程余量（同配置自适应网格变动，"
                                       "非实测分布）；超门记 DEGRADED 并入 κ "
                                       "不确定度预算，不事后改门（#122）",
            }
        candidates.append({
            **pick,
            "geometry": {"template": "hairpin_alt", **r["params"],
                         "w_mm": r["w_mm"], "gap_mm": r["gap_mm"]},
            "hfss_quantities_to_verify": {
                "primary": "k_split_eigen=2|f2−f1|/(f2+f1)（裸对无损本征，先例"
                           " scripts/hfss_hairpin_eigen_ext.py 逐键同配置：4 模齐"
                           "全/双模过带/无带内第三模 intruder/band_sanity）",
                "optional_driven_s21": "n_peaks 与 openEMS 合并判定同形态核对"
                                       + ("（预期 n_peaks=1）" if r["k_split"]["merged"]
                                          else "（预期 n_peaks=2）"),
                "optional_line2t_kz": "偶/奇模阻抗 Z0e/Z0o（Zvi=√(Zpi·Zpv) 重构，"
                                      "#361⑤）——k_Z 旁证列；SNL 警告在案不作门",
            },
            "expected": expected,
            "cost_basis": {"solve_s_per_point": 26, "wall_s_per_point": 75,
                           "source": "runs/hairpin_hfss_anchor/eigen_ext 实测"
                                     "（solve_s 24.8-26.2/wall_s 64.9-75.5）"},
        })
    return {
        "task": "hairpin_alt c 标尺 HFSS 仲裁 1-2 点锚（登记：TODO 排空五轮段）",
        "status": "plan_only（真机脚本主代理后定；本文件为数据契约非可执行脚本）",
        "selection_rule": ANCHOR_SELECTION_RULE,
        "anchored_state": {"gaps": anchored_gaps,
                           "c_true": {str(g): c_true[g] for g in anchored_gaps},
                           "sources": ["runs/hairpin_hfss_anchor/hairpin_anchor.json",
                                       "runs/hairpin_hfss_anchor/eigen_ext/"
                                       "eigen_ext_result.json"]},
        "candidates": candidates,
        "notes": ["n1 与 n2 重合时按 slot 序去重；候选不足 n_slots 如实少选",
                  "主判门 ±15%（与 ANCHORED_4PTS 同值）；k_Z 只作旁证（#361⑥）",
                  "本任务书由 scripts/hairpin_alt_k_extract.py 确定性产出"],
    }


# ── CLI（旧档零改写，产物落新目录）──────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analyze", action="store_true",
                        help="读归档 6 曲线 sparams.csv → 逐点双口径提取（零仿真）")
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    parser.add_argument("--out", default=str(DEFAULT_OUT),
                        help="产物目录（新档；旧档零改写）")
    parser.add_argument("--kz-noise-ohm", type=float, default=K_Z_NOISE_OHM,
                        help="k_Z SNL 扰动幅度（#361⑥ 缺省 0.5Ω）")
    args = parser.parse_args()
    if not args.analyze:
        parser.print_help()
        return
    result = analyze(Path(args.root), args.kz_noise_ohm)
    plan = build_anchor_plan(result, Path(args.root))
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_k = out_dir / "k_points.json"
    out_k.write_text(json.dumps(
        {**result, "generated_by": "scripts/hairpin_alt_k_extract.py --analyze"},
        indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    out_p = out_dir / "hfss_anchor_plan.json"
    out_p.write_text(json.dumps(plan, indent=1, ensure_ascii=False, default=str),
                     encoding="utf-8")

    vd = result["verdict"]
    print(f"逐点表 {vd['n_curves']} 条曲线（gap 图 {vd['n_map_points']} 点 + "
          f"截断变体 {vd['n_untrusted_truncation']}）："
          f"resolved {vd['n_split_resolved']} / shallow {vd['n_split_shallow']} / "
          f"merged {vd['n_merged']}", flush=True)
    print(f"主判口径={vd['primary_caliber']}（k_Z 旁证不作门）；"
          f"SNL 支配 gap={vd['kz_snl_dominant_gaps']}；"
          f"双 basis（KJ+HFSS line2t）gap={vd['kz_dual_basis_gaps']}", flush=True)
    print(f"已锚 {vd['anchored_gaps']}，c_true="
          f"{ {g: round(v, 4) for g, v in vd['c_true_anchored'].items()} }", flush=True)
    for c in plan["candidates"]:
        print(f"锚候选 {c['slot']}: gap={c['gap_mm']}mm（{c['pt_id']}）", flush=True)
    print(f"k_points: {out_k}\nanchor_plan: {out_p}", flush=True)


if __name__ == "__main__":
    main()
