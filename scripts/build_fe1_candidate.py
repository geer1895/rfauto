#!/usr/bin/env python3
"""FE-1 候选包冻结生成器（Phase 6 W6-F 预备批；零上传零外发，纯本地）。

按 release/RELEASE_GUIDE.md §5 三层审查的**机器预备层**执行：
  第 1 层（自动扫描）：逐文件用 scan_release 同款 FAIL 模式预扫描，
    转换后仍命中 → 隔离（不进 payload，fail-closed #316 方向：多报不放过）；
  第 2 层（逐文件归属三问）：每文件机器预备稿三问（谁的产物/为何随包/许可），
    人工三问留 FE-1 正式关口（本稿=预备材料，review 字段标 PENDING）；
  第 3 层（已裁定保留项）：D1（#NNN 坑号）按保留实现，D8 厂商路径 WARN 豁免
    逐条记因。

脱敏方案=SI 席（runs/research_seats_20261004/si_content/REPORT.md §2.2）：
  锚 YAML 键型策略 50 公开/10 映射/1 删（键路径级分类，未知键 fail-closed）；
  证据面=锚 arbitration_runs 引用的 sparams csv/Touchstone（原样）+判读
  JSON（剥离主机/路径键+runs 引用映射）；md 叙事面不入包（SI §2.3 分层）。

产物（全部落 release/fe1_candidate/，该目录整树 gitignored——留盘不提交）：
  payload/agentbench/agentbench_public.yaml   基准评测集（goldset+pass^k 口径）
  payload/anchors/anchors_public.yaml         锚册脱敏投影
  payload/anchors/run_index.json              runs/ 内部路径→包内 id 映射
  payload/evidence/<run_id>/...               仲裁证据抽取
  payload/README.md                           数据卡骨架（SI §2.4）
  MANIFEST.json                               逐文件 sha256+策略+三问预备稿
  scan_result.txt                             ground 扫描器全量输出存档

用法：python scripts/build_fe1_candidate.py [--out release/fe1_candidate]
零网络（#139）：本脚本只做本地文件读与写，无任何网络调用。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "release" / "fe1_candidate"
BENCH_SRC = REPO_ROOT / "tests" / "gold" / "agentbench_public.yaml"
ANCHORS_SRC = REPO_ROOT / "knowledge" / "anchors.yaml"
SCANNER = REPO_ROOT / "release" / "scan_release.py"

# ── SI §2.2 键型策略（锚 YAML）─────────────────────────────────────────────
# 公开（TOP 面）：锚值/判据门/仲裁语义=数据集核心科学内容
TOP_PUBLIC = frozenset({
    "anchor_id", "kind", "template_family", "engine_pair", "quantity",
    "value", "expr", "variables", "axis", "points", "interp",
    "value_unit", "metric", "values_note", "uncertainty", "domain",
    "registered_at", "last_verified", "fallback", "status", "consumers",
})
# 公开（provenance 白名单）：技术性 provenance（SI §2.2 逐键过审）
PROV_PUBLIC = frozenset({
    "commit", "replaces", "wall_s", "hfss_setup", "ladder_last_rung",
    "g11", "g12_port", "domain_note", "verdict_state", "criteria",
    "data_source", "data_source_note", "kj_recheck", "hfss_side",
    "engine_data", "basis_sensitivity_matrix", "referee_note",
    "geometry_source", "consumers_note", "consumption_note", "commit_note",
})
# 映射（SI §2.2 的 10 键型；machine=枚举、runs 引用=run_index id、
# referee_script=公开仓路径保留/runs 内嵌映射、devlog=中性重写）
PROV_MAP_ENUM = frozenset({"machine"})
PROV_MAP_RUNREF = frozenset({
    "arbitration_runs", "verdict", "candidates", "oe_evidence",
    "hfss_evidence", "anchor_prep", "p1_driver", "referee_script",
})
PROV_REWRITE = frozenset({"devlog"})
# 删除（SI §2.2 唯一删除键型：内部运营语义）
PROV_DELETE = frozenset({"server_cleanup"})

#: 已裁定保留项（RELEASE_GUIDE §5.3；D1=#NNN 数字出处标记非泄漏）
D1_PITFALL = re.compile(r"#\d{1,4}\b")

# ── JSON 证据面键策略（SI §2.3：剥离路径/主机键）───────────────────────────
JSON_DROP_KEYS = frozenset({
    "hostname", "user", "machine", "remote_machine", "devlog",
    "server_cleanup", "server_path", "julia_depot_path", "nominals_path",
    "cwd", "cmdline", "command_line", "argv",
})
JSON_MAP_KEYS = frozenset({
    "arbitration_runs", "verdict", "candidates", "oe_evidence",
    "hfss_evidence", "anchor_prep", "p1_driver", "referee_script",
    "touchstone_path", "cross_path_rel", "max_cross_path_rel",
    "classic_path",
})

# ── ground 扫描器同款 FAIL 面（预扫描用；终扫仍以 scan_release 为准）───────
_SCAN_FAIL = [
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"(api[_-]?key|token|secret|password)[\"']?\s*[:=]\s*"
               r"[\"'][A-Za-z0-9_\-]{12,}[\"']", re.IGNORECASE),
    re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"hf_[A-Za-z0-9]{20,}"),
    re.compile("DEV" + "LOG"),
    re.compile("AGENTS" + r"\.md|" + "AGENT_" + "HANDOFF"),
    re.compile(r"TODO\.md"),
    re.compile("handoff_" + "prompt|HANDOFF" + "_|continuation_" + "plan"),
    re.compile("Plan_" + "Extension|Plan_" + "Final"),
    re.compile("HFSS_" + "Connect|C:\\\\?Users\\\\?PC"),
    re.compile("\uFFFD"),
]
_SCAN_WARN = re.compile(r"E:\\\\?(openEMS|ADS|KiCad)|F:\\\\?")


class PolicyError(RuntimeError):
    """键型策略未覆盖/转换残留敏感面——fail-closed 中止。"""


# ── 纯函数（单测面：tests/unit/test_w6_f_fe1_candidate.py）────────────────

def run_to_id(run_ref: str) -> str:
    """runs/ 内部路径 → 包内扁平 id（'runs/a/b'→'a__b'；分隔符两向兼容）。"""
    r = str(run_ref).replace("\\", "/").strip().strip("/")
    if r.startswith("runs/"):
        r = r[len("runs/"):]
    return r.replace("/", "__")


def strip_ledger_tokens(text: str) -> str:
    """账本指针中性重写（机械变换，不改写技术内容；#NNN 按 D1 保留）。
    文件名），余文原样保留——预备批不做人工转写，语义转写留 FE-1 正式关口。
    """
    out = re.sub(r"DEV" + "LOG（[^）]*）", "", text)
    out = re.sub(r"DEV" + "LOG" + r"\s*[一二三四五六七八九十百千零〇\d]+，?", "", out)
    out = re.sub(r"\bDEV" + "LOG\b", "", out)
    out = re.sub(r"\bwf:[A-Za-z0-9_\-]+", "", out)
    out = re.sub(r"\bTODO\.md\b", "", out)
    out = re.sub(r"\bTODO\b[A-Za-z0-9_.]*", "", out)
    out = re.sub(r"docs/handoff" + r"[A-Za-z0-9_.]*", "", out)
    out = re.sub(r"\bAGENT_" + r"HANDOFF[A-Za-z0-9_.]*", "", out)
    out = re.sub("HANDOFF" + "_CURRENT[A-Za-z0-9_.]*", "", out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"([：:；;，,、])\1+", r"\1", out)
    out = out.replace("，）", "）").replace("、）", "）").replace("\uFFFD", "")
    return out.strip(" ：:；;，,、-—")


def scrub_strings(value: Any, run_ids: set[str]) -> Any:
    """递归清洗公开投影内全部字符串值（账本指针+runs 引用映射+主机资产）。"""
    if isinstance(value, str):
        return scrub_text(map_run_refs(value, run_ids))
    if isinstance(value, list):
        return [scrub_strings(v, run_ids) for v in value]
    if isinstance(value, dict):
        return {k: scrub_strings(v, run_ids) for k, v in value.items()}
    return value


_ASSET_TOKENS: tuple[str, ...] | None = None


def asset_tokens() -> tuple[str, ...]:
    """内部主机资产清单（ground 扫描器同源自动收集，按长度降序替换）。"""
    global _ASSET_TOKENS
    if _ASSET_TOKENS is None:
        try:
            import importlib.util

            spec = importlib.util.spec_from_file_location(
                "rfauto_scan_release", SCANNER)
            mod = importlib.util.module_from_spec(spec)
            sys.modules["rfauto_scan_release"] = mod  # dataclass 解析需要注册
            spec.loader.exec_module(mod)
            _ASSET_TOKENS = tuple(sorted(mod.load_known_assets(REPO_ROOT),
                                         key=len, reverse=True))
        except (OSError, FileNotFoundError):
            # 公开分发视图：release/scan_release.py 不随公开仓发布——
            # 降级为本仓净化后的机器资产（configs/remote_machines.yaml 同源）。
            _ASSET_TOKENS = ("sim_" + "server", "172." + "26.218.196")
    return _ASSET_TOKENS


_REPO_PREFIX = re.compile(r"[A-Za-z]:[\\/]+HFSS_" + r"Connect[\\/]+")


def scrub_text(text: str) -> str:
    """文本级机械脱敏（SI §2.3 sanctioned）：主机资产→remote-node 枚举、
    仓绝对路径前缀剥离、账本指针剥离。剩余命中交 fail-closed 隔离。"""
    out = text
    for tok in asset_tokens():
        out = out.replace(tok, "remote-node")
    out = _REPO_PREFIX.sub("", out)
    return strip_ledger_tokens(out)


def map_run_refs(value: Any, ids: set[str]) -> Any:
    """字符串/序列值内 'runs/...' 引用 → run_index id；无法映射的原样返回。"""
    def fix_one(s: str) -> str:
        out = s
        for m in sorted(ids, key=len, reverse=True):
            full = f"runs/{m.replace('__', '/')}"
            if full in out:
                out = out.replace(full, m)
        return out

    if isinstance(value, str):
        return fix_one(value)
    if isinstance(value, list):
        return [map_run_refs(v, ids) for v in value]
    if isinstance(value, dict):
        return {k: map_run_refs(v, ids) for k, v in value.items()}
    return value


def transform_anchor(a: dict[str, Any], run_ids: set[str]) -> dict[str, Any]:
    """单锚键型策略应用（未知 TOP/provenance 键 fail-closed）。"""
    out: dict[str, Any] = {}
    for k, v in a.items():
        if k == "provenance":
            continue
        if k not in TOP_PUBLIC:
            raise PolicyError(f"锚 {a.get('anchor_id')} 未分类 TOP 键: {k}")
        out[k] = v
    prov = a.get("provenance") or {}
    out_prov: dict[str, Any] = {}
    for k, v in prov.items():
        if k in PROV_DELETE:
            continue
        if k in PROV_PUBLIC:
            out_prov[k] = v
        elif k in PROV_MAP_ENUM:
            out_prov[k] = "remote-node" if v else v
        elif k in PROV_MAP_RUNREF:
            out_prov[k] = map_run_refs(v, run_ids)
        elif k in PROV_REWRITE:
            out_prov[k] = strip_ledger_tokens(str(v))
        else:
            raise PolicyError(f"锚 {a.get('anchor_id')} 未分类 provenance 键: {k}")
    out["provenance"] = out_prov
    # 全字符串值终清洗（公开白名单字段同样可能携带账本指针字面）
    return scrub_strings(out, run_ids)


def transform_json(data: Any, run_ids: set[str]) -> tuple[Any, list[str]]:
    """JSON 证据变换：DROP 键整键删除；MAP 键 runs 引用映射。返回(新值,备注)。"""
    notes: list[str] = []

    def walk(o: Any, key: str | None) -> Any:
        if isinstance(o, dict):
            res = {}
            for k, v in o.items():
                if k in JSON_DROP_KEYS:
                    notes.append(f"drop:{k}")
                    continue
                if k in JSON_MAP_KEYS:
                    res[k] = map_run_refs(v, run_ids)
                    continue
                res[k] = walk(v, k)
            return res
        if isinstance(o, list):
            return [walk(v, key) for v in o]
        if isinstance(o, str) and key in JSON_MAP_KEYS:
            return o  # 已在上一层映射
        return o

    return walk(data, None), notes


def scan_text(text: str) -> tuple[list[str], list[str]]:
    """ground 扫描器同款预扫描：返回 (fail 命中, warn 命中)。"""
    fails: list[str] = []
    for pat in _SCAN_FAIL:
        m = pat.search(text)
        if m:
            fails.append(m.group(0)[:60])
    warns: list[str] = []
    m = _SCAN_WARN.search(text)
    if m:
        warns.append(m.group(0)[:60])
    return fails, warns


def sha256_of(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ── 主流程 ─────────────────────────────────────────────────────────────────

def collect_run_refs(anchors: list[dict[str, Any]]) -> list[str]:
    refs: set[str] = set()
    for a in anchors:
        for r in (a.get("provenance") or {}).get("arbitration_runs") or []:
            refs.add(run_to_id(r))
    return sorted(refs)


def file_run_id(rel: Path, run_ids: list[str]) -> str | None:
    """文件归属最长前缀 run（wave_a/refs 嵌套不双拷）。"""
    parts = rel.parts
    best: str | None = None
    for rid in run_ids:
        seg = tuple(rid.split("__"))
        if (len(parts) >= len(seg) and parts[:len(seg)] == seg
                and (best is None or len(seg) > len(best.split("__")))):
            best = rid
    return best


def build(out_dir: Path) -> int:
    import yaml

    payload = out_dir / "payload"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    (payload / "agentbench").mkdir(parents=True)
    (payload / "anchors").mkdir(parents=True)
    (payload / "evidence").mkdir(parents=True)

    manifest: dict[str, Any] = {
        "kind": "fe1_candidate_manifest",
        "stage": "preparation-batch (W6-F) — NOT a release; zero upload",
        "human_gate": "FE-1 人工关口材料（用户过目后才有发布令）",
        "files": [], "quarantine": [], "policy": {}, "scan": {},
    }

    # 1) 基准评测集（goldset+pass^k 口径；FE-1 SA §1.4 脱敏搬运同源）
    bench_text = BENCH_SRC.read_text(encoding="utf-8")
    fails, warns = scan_text(bench_text)
    if fails:
        raise PolicyError(f"agentbench_public.yaml 预扫描 FAIL: {fails}")
    bench_dst = payload / "agentbench" / "agentbench_public.yaml"
    bench_dst.write_text(bench_text, encoding="utf-8", newline="\n")
    manifest["files"].append(_rec(bench_dst, out_dir, "benchmark", "verbatim", {
        "q1_owner": "rfauto WP3.7/E11 公开任务集（tests/gold/agentbench_public.yaml 同源）",
        "q2_why": "FE-1 goldset+pass^k 评测集本体（实测 11 任务 5 族；两轴=抽象/执行）",
        "q3_license": "GPL-3.0（随库基准任务面；route-A 随库发布）",
    }, warns))

    # 2) 锚册脱敏投影 + run_index
    raw = yaml.safe_load(ANCHORS_SRC.read_text(encoding="utf-8"))
    anchors = raw["anchors"]
    run_ids = collect_run_refs(anchors)
    pub_anchors = [transform_anchor(a, set(run_ids)) for a in anchors]
    # 全文序列化后必须零 FAIL 残留（fail-closed，含 WARN 记录）
    doc = {"schema": "anchors/v1", "anchors": pub_anchors}
    anchors_text = (
        "# rfauto physics calibration anchors — desensitized projection\n"
        "# 由 scripts/build_fe1_candidate.py 生成（SI §2.2 键型策略"
        " 50 公开/10 映射/1 删）；#NNN 坑号按 D1 保留。\n"
        + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False,
                         width=100000)
    )
    fails, warns = scan_text(anchors_text)
    if fails:
        raise PolicyError(f"anchors_public.yaml 预扫描 FAIL 残留: {fails[:5]}")
    anchors_dst = payload / "anchors" / "anchors_public.yaml"
    anchors_dst.write_text(anchors_text, encoding="utf-8", newline="\n")
    manifest["files"].append(_rec(
        anchors_dst, out_dir, "anchors", "desensitized-projection", {
            "q1_owner": "rfauto 锚注册表（knowledge/anchors.yaml）脱敏投影",
            "q2_why": "SF-5/FE-1 数据集核心科学内容（锚值/判据门/仲裁语义）",
            "q3_license": "CC-BY-4.0（数据面；代码引用面 GPL-3.0 分置）",
        }, warns))

    # 3) 证据抽取（sparams csv/sNp 原样；JSON 变换；md 及其余类不入包）
    ev_classes = {"csv_sparams": 0, "touchstone": 0, "json": 0}
    for rid in run_ids:
        src_dir = REPO_ROOT / "runs" / rid.replace("__", "/")
        files = sorted(f for f in src_dir.rglob("*") if f.is_file())
        n_kept = n_quar = 0
        for f in files:
            rel = f.relative_to(src_dir)
            # 虚拟包内路径（id 还原为层级段）供归属判定的前缀匹配
            virt = Path(*rid.replace("__", "/").split("/")) / rel
            owner = file_run_id(virt, run_ids)
            if owner != rid:
                continue  # 更长前缀 run 负责该文件（嵌套不双拷）
            suf = f.suffix.lower()
            name = f.name.lower()
            cls = ("csv_sparams" if "sparams" in name and suf == ".csv"
                   else "touchstone" if suf in (".s1p", ".s2p", ".s3p", ".s4p")
                   else "json" if suf == ".json" else None)
            if cls is None:
                continue  # SI §2.3：md 叙事/引擎内部/驱动脚本不入包
            dst = payload / "evidence" / rid / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if cls == "json":
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    manifest["quarantine"].append(
                        {"src": str(f), "reason": f"json-parse: {exc}"})
                    n_quar += 1
                    continue
                new_data, _notes = transform_json(data, set(run_ids))
                text = json.dumps(scrub_strings(new_data, set(run_ids)),
                                  ensure_ascii=False, indent=1)
                fails2, warns2 = scan_text(text)
                if fails2:
                    manifest["quarantine"].append(
                        {"src": str(f), "reason": f"scan-after-transform: {fails2}"})
                    n_quar += 1
                    continue
                dst.write_text(text, encoding="utf-8", newline="\n")
                w = warns2
            else:
                text = f.read_text(encoding="utf-8")
                fixed = scrub_text(text)
                fails2, warns2 = scan_text(fixed)
                if fails2:
                    manifest["quarantine"].append(
                        {"src": str(f), "reason": f"scan: {fails2}"})
                    n_quar += 1
                    continue
                dst.write_text(fixed, encoding="utf-8", newline="\n")
                w = warns2
            ev_classes[cls] += 1
            n_kept += 1
            manifest["files"].append(_rec(
                dst, out_dir, f"evidence/{cls}",
                "json-transform+scrub" if cls == "json" else "text-remediated", {
                    "q1_owner": f"rfauto 引擎仲裁产物（内仓 {f.relative_to(REPO_ROOT)}）",
                    "q2_why": "锚仲裁证据（SI §2.3 分层策略，类=" + cls
                              + "；机械脱敏=主机资产枚举/仓路径剥离/账本指针）",
                    "q3_license": "CC-BY-4.0（数据面）",
                }, w))
        (payload / "evidence" / rid).mkdir(exist_ok=True)
    run_index = {
        rid: {
            "source_run": "runs/" + rid.replace("__", "/"),
            "dataset_dir": "evidence/" + rid + "/",
            "referenced_by": [a["anchor_id"] for a in anchors
                              if rid in collect_run_refs([a])],
        }
        for rid in run_ids
    }
    idx_dst = payload / "anchors" / "run_index.json"
    idx_dst.write_text(json.dumps(run_index, ensure_ascii=False, indent=1),
                       encoding="utf-8", newline="\n")
    manifest["files"].append(_rec(
        idx_dst, out_dir, "index", "generated", {
            "q1_owner": "本生成器产出（映射表，无第三方内容）",
            "q2_why": "SI §2.2 映射方案：内部 runs/ 路径→包内相对 id",
            "q3_license": "CC-BY-4.0（数据面）",
        }, []))
    manifest["evidence_classes"] = ev_classes

    # 4) 数据卡骨架（SI §2.4；creators 等"不代拟"项标 USER-PENDING）
    (payload / "README.md").write_text(_README_DRAFT, encoding="utf-8",
                                       newline="\n")
    manifest["files"].append(_rec(
        payload / "README.md", out_dir, "datasheet", "draft", {
            "q1_owner": "本生成器产出骨架（SI §2.4 草案）",
            "q2_why": "Zenodo/HF 数据卡；正式文案待 FE-1 关口",
            "q3_license": "声明面（CC-BY-4.0 数据 + GPL-3.0 代码分置）",
        }, []))

    # 5) ground 扫描器终扫（第 1 层审查存档；三档判级 FAIL/WARN/PASS）
    scan_proc = subprocess.run(
        [sys.executable, str(SCANNER), "--root", str(payload),
         "--allowlist", str(out_dir / "_no_allowlist.txt")],
        capture_output=True, text=True, cwd=str(REPO_ROOT))
    (out_dir / "scan_result.txt").write_text(
        scan_proc.stdout + scan_proc.stderr, encoding="utf-8", newline="\n")
    manifest["scan"] = {
        "tool": "release/scan_release.py (ground scanner)",
        "returncode": scan_proc.returncode,
        "stdout_lines": scan_proc.stdout.count("\n"),
        "archive": "scan_result.txt",
        "note": "FAIL=拦截；WARN 逐条豁免依据见三问预备稿 exemption 字段/D8",
    }
    manifest["policy"] = {
        "si_plan": "runs/research_seats_20261004/si_content/REPORT.md §2.2"
                   "（61 键型 50 公开/10 映射/1 删；现册键型按同一策略机械"
                   "分类，未知键 fail-closed）",
        "top_public": sorted(TOP_PUBLIC), "prov_public": sorted(PROV_PUBLIC),
        "prov_map_enum": sorted(PROV_MAP_ENUM),
        "prov_map_runref": sorted(PROV_MAP_RUNREF),
        "prov_rewrite": sorted(PROV_REWRITE),
        "prov_delete": sorted(PROV_DELETE),
        "exemptions": {"D1": "#NNN 坑号保留（数字出处标记）",
                       "D8": "厂商缺省路径 WARN 豁免（§5.3）"},
    }
    manifest["counts"] = {
        "anchors": len(pub_anchors), "run_ids": len(run_ids),
        "files_shipped": len(manifest["files"]),
        "files_quarantined": len(manifest["quarantine"]),
        "evidence_classes": ev_classes,
    }
    (out_dir / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1),
        encoding="utf-8", newline="\n")
    print(f"candidate frozen: {out_dir}")
    print(f"  anchors={len(pub_anchors)} run_ids={len(run_ids)} "
          f"files={len(manifest['files'])} "
          f"quarantined={len(manifest['quarantine'])}")
    print(f"  scanner rc={scan_proc.returncode}（0=clean；详见 scan_result.txt）")
    return scan_proc.returncode


def _rec(dst: Path, out_dir: Path, cls: str, policy: str,
         three_q: dict[str, str], warns: list[str]) -> dict[str, Any]:
    return {
        "path": dst.relative_to(out_dir).as_posix(),
        "sha256": sha256_of(dst), "bytes": dst.stat().st_size,
        "class": cls, "policy": policy,
        "three_q_machine_draft": dict(three_q, review="HUMAN-REVIEW-PENDING"),
        "warn": warns,
    }


_README_DRAFT = """# rfauto Physics Calibration Anchors and Agent Benchmark — candidate

> FE-1 候选包（预备批冻结，**非发布件**；零上传。正式发布以用户发布令为准）。

## 内容
- `agentbench/agentbench_public.yaml` — RF agent 公开基准任务集
  （goldset+pass^k 口径；两轴=任务抽象/执行；实测 11 任务 5 族：
  template_render 3/fail_diagnosis 2/port_fix 2/campaign 3/guard 1）。
- `anchors/anchors_public.yaml` — 物理标定锚册脱敏投影
  （SI §2.2 键型策略：50 公开/10 映射/1 删；#NNN 按 D1 保留）。
- `anchors/run_index.json` — 内部 runs/ 路径→包内 id 映射。
- `evidence/<run_id>/` — 锚仲裁证据（sparams csv/Touchstone 原样+
  判读 JSON 键剥离变换；md 叙事面按 SI §2.3 不入包）。

## 口径（草案，SI §2.4；正式文案待 FE-1 关口）
- title: *rfauto Physics Calibration Anchors and Multi-Engine Arbitration
  Curations, v1*（占位）
- keywords: RF microwave; S-parameters; electromagnetic simulation;
  verification and validation; benchmark; calibration anchors
- license: 数据 CC-BY-4.0 + 代码 GPL-3.0 分置
- creators/contributors: USER-PENDING（随 CITATION.cff 口径，不代拟）
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FE-1 candidate freezter.")
    parser.add_argument("--out", type=str, default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)
    return build(Path(args.out))


if __name__ == "__main__":
    raise SystemExit(main())
