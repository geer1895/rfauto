"""失败指纹解释器（DP-17 W2）——run 目录 → 确定性根因族候选（无 LLM）。

链路：特征采集（复用 health_check_run G11 面 + W1 verdict 工件读取器 +
本模块确定性检测器）→ playbook.yaml 指纹匹配（多指纹 AND）→ 输出
{命中规则、证据、取证命令、坑号链}。多证并击只出**候选根因族列表**
（按命中指纹数降序），不下黑箱单一结论（#122 如实口径：判据只对在场
证据下结论，无证据如实 no_hit 不硬凑）。

指纹词表与 knowledge/diagnostics/playbook.yaml 的 detector_vocab 一一
对应；规则引用未知指纹 → 该规则 skip 如实计数（#321 思想）。
服务层 JSON 进出（规则 4）；全程只读 runs/ 证据面。
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from rfauto.service.health_service import (
    _load_sparams_csv,
    health_check_run,
)
from rfauto.service.league_service import (
    _is_verdict_artifact,
    _verdict_from_artifact_dict,
)

logger = logging.getLogger(__name__)

#: playbook 缺省路径（锚定仓根，cwd 无关）
DEFAULT_PLAYBOOK_PATH = Path(__file__).resolve().parents[3] / "knowledge" / \
    "diagnostics" / "playbook.yaml"

#: G11 factor → 指纹（status 门限见 _HEALTH_FACTOR_FINGERPRINTS）
_HEALTH_FACTOR_FINGERPRINTS: dict[str, tuple[str, str]] = {
    # factor: (fingerprint_id, 触发 status)
    "passivity": ("sparam_passivity_violation", "FAIL"),
    "reciprocity": ("sparam_reciprocity_fail", "FAIL"),
    "timestep": ("health_timestep_collapse", "FAIL"),
    "cost_distribution": ("health_cost_degenerate", "FAIL"),
    "excitation": ("health_excitation_dead", "FAIL"),
    "probe_scale": ("health_probe_scale_warn", "WARN"),
    "power_balance": ("health_power_balance_fail", "FAIL"),
    "thermal_plausibility": ("health_thermal_fail", "FAIL"),
}

#: et 尾段衰减比阈值：末 10% 时窗均值幅度 / 全程峰值
_ET_TAIL_RATIO_THRESHOLD = 0.05

#: 日志/JSON 扫描上限（有界，防大产物拖垮）
_LOG_FILE_CAP_BYTES = 200_000
_LOG_LINE_CAP = 2000
_JSON_FILE_CAP_BYTES = 1_000_000

#: *.err/*.log 确定性正则（症状指纹）
_LOG_PATTERNS: dict[str, str] = {
    "pyaedt_release_error": r"release_desktop|关闭\s*AEDT\s*失败",
    "hfss_selection_error":
        r"Objects or Faces selected do not exist|list index out of range",
}

#: unite 不完整判定键（attempt 工件惯例字段）
_UNITE_FALSY = {"", "false", "0", "none", "null"}


def load_playbook(path: str | Path | None = None) -> dict[str, Any]:
    """加载 playbook.yaml（schema 校验轻量；缺失/坏 YAML → ok=False）。"""
    p = Path(path) if path is not None else DEFAULT_PLAYBOOK_PATH
    if not p.is_file():
        return {"ok": False, "reason": f"playbook 不存在: {p}", "rules": []}
    try:
        import yaml
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"ok": False, "reason": f"playbook 解析失败: {exc}",
                "rules": []}
    if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
        return {"ok": False, "reason": "playbook 缺 rules 列表", "rules": []}
    return {"ok": True, "path": str(p), "schema": data.get("schema"),
            "detector_vocab": list(data.get("detector_vocab") or []),
            "rules": data["rules"]}


# ---------------------------------------------------------------------------
# 确定性检测器（指纹 → 在场证据）
# ---------------------------------------------------------------------------

def _detect_et_tail(run_dir: Path) -> dict[str, Any]:
    """et 尾段衰减比：末 10% 时窗均值幅度 / 全程峰值（未衰减=截断指纹）。"""
    for cand in (run_dir / "fdtd" / "et", run_dir / "et"):
        if cand.is_file():
            values: list[float] = []
            try:
                with open(cand, encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        parts = line.split()
                        if len(parts) == 2:
                            try:
                                values.append(abs(float(parts[1])))
                            except ValueError:
                                continue
            except OSError as exc:
                return {"fingerprint": None, "error": str(exc)}
            if len(values) < 20:
                return {"fingerprint": None, "et_path": str(cand),
                        "note": "样本过少不判"}
            peak = max(values) or 0.0
            tail = values[int(len(values) * 0.9):]
            ratio = (sum(tail) / len(tail)) / peak if peak > 0 else 0.0
            fired = ratio > _ET_TAIL_RATIO_THRESHOLD
            return {
                "fingerprint": "fdtd_tail_not_decayed" if fired else None,
                "et_path": str(cand),
                "tail_ratio": round(ratio, 6),
                "threshold": _ET_TAIL_RATIO_THRESHOLD,
            }
    return {"fingerprint": None, "note": "无 et 产物"}


def _detect_sparams_zerofill(run_dir: Path) -> dict[str, Any]:
    """sparams.csv 单激励部分矩阵：掩码存在未测的非对角元 → 指纹在场。"""
    errors: list[str] = []
    try:
        loaded = _load_sparams_csv(run_dir, errors)
    except Exception:
        loaded = None
    if loaded is None:
        return {"fingerprint": None, "note": "无 sparams.csv 产物"}
    _freq, _s, mask = loaded
    n = mask.shape[0] if mask is not None else 0
    if n == 0:
        return {"fingerprint": None, "note": "掩码缺失"}
    unmeasured_pairs = sorted(
        f"S{p + 1}{q + 1}" for p in range(n) for q in range(n)
        if p != q and not mask[p, q])
    measured_diag = int(sum(1 for i in range(n) if mask[i, i]))
    if unmeasured_pairs and measured_diag:
        return {
            "fingerprint": "sparam_partial_matrix_zerofill",
            "n_ports": int(n),
            "unmeasured_offdiag": unmeasured_pairs,
            "measured_diagonal": measured_diag,
        }
    return {"fingerprint": None, "n_ports": int(n),
            "note": "全矩阵已测或掩码形态未知"}


def _detect_log_patterns(run_dir: Path) -> dict[str, Any]:
    """顶层 *.err/*.log 有界扫描 → 确定性正则指纹。"""
    hits: dict[str, list[str]] = {}
    for name in sorted(os.listdir(run_dir)):
        if not (name.endswith(".err") or name.endswith(".log")):
            continue
        path = run_dir / name
        try:
            if path.stat().st_size > _LOG_FILE_CAP_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = text.splitlines()[:_LOG_LINE_CAP]
        for fp_id, pattern in _LOG_PATTERNS.items():
            if re.search(pattern, "\n".join(lines)):
                evidence = next(
                    (ln.strip()[:160] for ln in lines
                     if re.search(pattern, ln)), "")
                hits.setdefault(fp_id, []).append(f"{name}: {evidence}")
    return {"hits": hits}


def _detect_unite_artifacts(run_dir: Path) -> dict[str, Any]:
    """顶层 *.json 扫 unite_result/objects_after_unite → unite 不完整指纹。"""
    evidence: list[str] = []
    for name in sorted(os.listdir(run_dir)):
        if not name.endswith(".json"):
            continue
        path = run_dir / name
        try:
            if path.stat().st_size > _JSON_FILE_CAP_BYTES:
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        unite = data.get("unite_result")
        objs = data.get("helix_objects_after_unite",
                        data.get("objects_after_unite"))
        unite_false = unite is not None and (
            str(unite).strip().lower() in _UNITE_FALSY)
        objs_bad = isinstance(objs, int) and objs > 1
        if unite_false:
            evidence.append(
                f"{name}: unite_result={unite!r}, objects_after={objs!r}")
        elif objs_bad:
            evidence.append(f"{name}: objects_after_unite={objs}")
    if evidence:
        return {"fingerprint": "unite_incomplete", "evidence": evidence}
    return {"fingerprint": None}


def _detect_verdict_artifacts(run_dir: Path) -> dict[str, Any]:
    """逐个 verdict 工件（与 W1 同一文件名过滤+形态读取器，全部枚举）。"""
    found: list[dict[str, Any]] = []
    for name in sorted(os.listdir(run_dir)):
        if not _is_verdict_artifact(name):
            continue
        try:
            data = json.loads((run_dir / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        verdict, shape = _verdict_from_artifact_dict(data)
        if verdict is None:
            continue
        raw_key = ("verdict" if isinstance(data.get("verdict"), str)
                   else "overall")
        found.append({
            "file": name,
            "verdict": verdict,
            "verdict_raw": str(data.get(raw_key, ""))[:160],
            "shape": shape,
        })
    return {"artifacts": found}


def collect_run_features(run_dir: str | Path) -> dict[str, Any]:
    """run 目录 → 特征与指纹证据（只读；缺产物如实 note 不硬凑）。"""
    run_dir = Path(run_dir)
    if not run_dir.is_dir():
        return {"ok": False, "reason": f"run 目录不存在: {run_dir}"}

    features: dict[str, Any] = {"run_dir": str(run_dir)}
    fingerprints: dict[str, Any] = {}

    meta = None
    meta_path = run_dir / "meta.json"
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except ValueError:
            meta = None
    if isinstance(meta, dict):
        features["meta"] = {
            k: meta.get(k) for k in ("run_id", "adapter", "model", "status")
            if meta.get(k) is not None}
        if str(meta.get("status") or "").strip().lower() == "failed":
            fingerprints["meta_status_failed"] = {
                "evidence": "meta.json status=failed"}

    # G11 体检面（复用 health_check_run；单点失败不传染，#105）
    try:
        health = health_check_run(run_dir.name, runs_dir=run_dir.parent)
        features["health"] = {"verdict": health.get("verdict"),
                              "factors": health.get("factors", [])}
        for factor in health.get("factors", []):
            mapping = _HEALTH_FACTOR_FINGERPRINTS.get(factor.get("factor"))
            if mapping and factor.get("status") == mapping[1]:
                fp_id, trigger = mapping
                fingerprints[fp_id] = {
                    "evidence": str(factor.get("detail", ""))[:160],
                    "source": f"health_check_run {factor.get('factor')}"
                              f"={trigger}"}
    except Exception as exc:
        features["health"] = {"error": f"{type(exc).__name__}: {exc}"}

    for detector, result in (
        ("sparams", _detect_sparams_zerofill(run_dir)),
        ("et_tail", _detect_et_tail(run_dir)),
        ("logs", _detect_log_patterns(run_dir)),
        ("unite", _detect_unite_artifacts(run_dir)),
        ("verdicts", _detect_verdict_artifacts(run_dir)),
    ):
        features[detector] = result

    # 单指纹检测器结果就地登记（指纹 id 与检测结果同名字段）
    for feature_key, fp_id in (
        ("sparams", "sparam_partial_matrix_zerofill"),
        ("et_tail", "fdtd_tail_not_decayed"),
        ("unite", "unite_incomplete"),
    ):
        result = features.get(feature_key)
        if isinstance(result, dict) and result.get("fingerprint") == fp_id:
            fingerprints[fp_id] = {
                k: v for k, v in result.items() if k != "fingerprint"}

    for hit_id, hit_evidence in features.get("logs", {}).get("hits", {}).items():
        fingerprints[hit_id] = {"evidence": hit_evidence[:2]}

    for art in features.get("verdicts", {}).get("artifacts", []):
        v = art["verdict"]
        if v == "FAIL":
            fingerprints.setdefault("verdict_fail_recorded", {
                "evidence": []})["evidence"].append(
                f"{art['file']}: {art['verdict_raw']}")
            if "arbitration" in art["file"]:
                fingerprints.setdefault("arbitration_gate_fail", {
                    "evidence": []})["evidence"].append(
                    f"{art['file']}: {art['verdict_raw']}")
        elif v == "UNDECIDABLE":
            fingerprints.setdefault("verdict_undecidable_recorded", {
                "evidence": []})["evidence"].append(
                f"{art['file']}: {art['verdict_raw']}")

    features["fingerprints"] = dict(sorted(fingerprints.items()))
    return {"ok": True, **features}


# ---------------------------------------------------------------------------
# 指纹匹配（多指纹 AND；多规则并击只出候选族）
# ---------------------------------------------------------------------------

def explain_run(
    run_dir: str | Path,
    playbook_path: str | Path | None = None,
) -> dict[str, Any]:
    """确定性指纹匹配 → {命中规则、证据、取证命令、坑号链、候选族}。

    overall: "no_hit"（零命中，不硬凑）| "candidates"（候选族列表）。
    """
    run_dir = Path(run_dir)
    book = load_playbook(playbook_path)
    if not book.get("ok"):
        return {"ok": False, "reason": book.get("reason"),
                "run_dir": str(run_dir)}

    collected = collect_run_features(run_dir)
    if not collected.get("ok"):
        return {"ok": False, "reason": collected.get("reason"),
                "run_dir": str(run_dir)}
    fingerprints: dict[str, Any] = collected.get("fingerprints", {})
    model = (collected.get("meta") or {}).get("model")

    matched_rules: list[dict[str, Any]] = []
    skipped_rules: list[dict[str, str]] = []
    vocab = set(book.get("detector_vocab") or [])
    for rule in book["rules"]:
        rid = str(rule.get("id") or "?")
        fps = list(rule.get("symptom_fingerprints") or [])
        unknown = [f for f in fps if f not in vocab]
        if unknown:
            skipped_rules.append({"id": rid,
                                  "reason": f"未知指纹: {unknown}"})
            continue
        if not fps:
            skipped_rules.append({"id": rid, "reason": "空指纹集"})
            continue
        missing = [f for f in fps if f not in fingerprints]
        if missing:
            continue
        templates = [str(t) for t in (rule.get("applicable_templates") or [])]
        if model is None and "*" not in templates:
            skipped_rules.append({"id": rid,
                                  "reason": "无 meta.model 且规则非通配"})
            continue
        if model is not None and "*" not in templates and model not in templates:
            continue
        matched_rules.append({
            "id": rid,
            "root_cause_family": rule.get("root_cause_family"),
            "matched_fingerprints": fps,
            "evidence": {f: fingerprints[f] for f in fps},
            "forensic_commands": list(rule.get("forensic_commands") or []),
            "pit_refs": [str(p) for p in (rule.get("pit_refs") or [])],
            "notes": rule.get("notes"),
        })

    matched_rules.sort(key=lambda r: (-len(r["matched_fingerprints"]),
                                      str(r["root_cause_family"])))
    candidates = [r["root_cause_family"] for r in matched_rules]
    return {
        "ok": True,
        "run_dir": str(run_dir),
        "playbook": {"path": book["path"], "schema": book.get("schema"),
                     "n_rules": len(book["rules"])},
        "meta": collected.get("meta"),
        "health_verdict": (collected.get("health") or {}).get("verdict"),
        "fingerprints": fingerprints,
        "matched_rules": matched_rules,
        "candidates": candidates,
        "skipped_rules": skipped_rules,
        "overall": "candidates" if matched_rules else "no_hit",
    }
