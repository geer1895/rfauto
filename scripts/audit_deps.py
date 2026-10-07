"""依赖漏洞门（QM-4，2026-10-02）——pip-audit 包装，扫依赖面已知漏洞（PyPI JSON API/OSV）。

用法：.venv/Scripts/python.exe scripts/audit_deps.py [--json <out>] [--raw-json <out>]
      [--requirements <req.txt>] [--timeout-s 1800]
- 缺省审计当前环境（pip-audit env 模式）；--requirements 审计 lock 导出的
  requirements.txt（CI 接线形态：uv export --format requirements-txt → 本门，
  round16 QM-4 规格"扫 uv.lock"的落地面）。
- 豁免表 EXEMPT 逐条带裁决理由+复审日期（ISO）；复审过期未复审的豁免本身
  判红（强制复审语义，round16 规格"豁免带理由+复审日期"）。
- 豁免外漏洞=门红（exit 1）；审计本体跑不起来（如网络不可达，OSV 查询失败）
  =诚实降级 skip（exit 2），不假装绿（判别式=pip-audit stdout 是否产出合法
  JSON——漏洞命中时 rc=1 但 JSON 照常产出，故 JSON 缺失即审计失败）。
- 与 P-3 license_gate（scripts/license_gate.py）同型：自动扫描是证据面，不
  替代人工裁决；漏洞修复升版属依赖本体变更，留主代理裁决（本门只报告）。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

REPORT_SCHEMA = "qm4/audit_deps_report/1"

#: 逐条豁免裁决表（键 = "<PEP503 包名>:<漏洞 ID>"；漏洞 ID 为 PYSEC-*/GHSA-*/CVE-*）。
#: 每条必须带 reason（裁决理由）与 review_date（复审到期日，ISO 8601）；
#: 复审日期过期后豁免失效→门红并点名"豁免过期"，强制人工复审后再续期。
#: 首表为空=首跑未发现需豁免项（2026-10-02 首跑结果见 runs/qm4）。
EXEMPT: dict[str, dict[str, str]] = {}


def normalize_name(name: str) -> str:
    """PEP503 归一（大小写折叠 + -_. 折叠）——豁免键匹配用（license_gate 同款）。"""
    import re as _re

    return _re.sub(r"[-_.]+", "-", name).lower()


def exempt_key(package: str, vuln_id: str) -> str:
    return f"{normalize_name(package)}:{vuln_id.strip()}"


def lookup_exempt(package: str, vuln_id: str,
                  table: dict[str, dict[str, str]] | None = None) -> dict[str, str] | None:
    """按归一键查豁免条目；无条目返回 None。"""
    t = EXEMPT if table is None else table
    return t.get(exempt_key(package, vuln_id))


def exemption_expired(entry: dict[str, str], today: date) -> bool:
    """复审语义：today > review_date 即过期（当日仍有效）。条目缺 review_date 视为过期。"""
    raw = entry.get("review_date", "")
    if not raw:
        return True
    try:
        return today > date.fromisoformat(raw)
    except ValueError:
        return True  # 日期格式坏=无法复审=按过期处置（不静默放行）


def pip_audit_version() -> str:
    import importlib.metadata as im

    try:
        return im.version("pip-audit")
    except Exception:  # 观测性字段 best-effort（#105），缺失不阻塞门
        return "unknown"


def build_command(requirements: str | Path | None = None) -> list[str]:
    """构造 pip-audit 命令行（离线可测）。"""
    cmd = [sys.executable, "-m", "pip_audit", "--format", "json",
           "--progress-spinner", "off"]
    if requirements is not None:
        # --no-deps：lock 导出面（uv export）已展平全树，且含全平台标记变体，
        # pip-audit 缺省的 pip 依赖解析会 ResolutionImpossible（首跑实证
        # 2026-10-02）——锁面审计一律跳过解析按清单直查。
        cmd += ["-r", str(requirements), "--no-deps"]
    return cmd


def run_pip_audit(requirements: str | Path | None = None,
                  timeout_s: int = 1800) -> tuple[dict | None, str | None]:
    """跑 pip-audit 取 JSON 报告；返回 (解析后的 JSON, None) 或 (None, 失败原因)。

    判别式：漏洞命中时 pip-audit rc=1 但 stdout 照常输出合法 JSON——
    故以"stdout 是否产出合法 JSON"区分"审计完成"与"审计失败"。
    """
    cmd = build_command(requirements)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return None, f"pip-audit 超时（>{timeout_s}s）"
    except OSError as exc:
        return None, f"pip-audit 启动失败：{exc}"
    if proc.stdout.strip():
        try:
            return json.loads(proc.stdout), None
        except json.JSONDecodeError as exc:
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-5:]
            return None, f"pip-audit 输出非合法 JSON（{exc}）：...{' | '.join(tail)}"
    tail = (proc.stderr or "").strip().splitlines()[-5:]
    reason = "pip-audit 无 JSON 输出"
    if tail:
        reason += f"（rc={proc.returncode}）：...{' | '.join(tail)}"
    return None, reason


def evaluate(doc: dict, today: date | None = None,
             table: dict[str, dict[str, str]] | None = None) -> dict:
    """把 pip-audit JSON 文档判读成门报告（schema=REPORT_SCHEMA）；零 IO 可离线测。"""
    today = today or date.today()
    deps = doc.get("dependencies", []) or []
    vulnerabilities: list[dict] = []
    skipped_deps: list[dict] = []
    n_exemptions_expired = 0
    for dep in deps:
        name = str(dep.get("name", "?"))
        version = str(dep.get("version", "?"))
        skip_reason = dep.get("skip_reason")
        if skip_reason:
            skipped_deps.append({"name": name, "version": version,
                                 "skip_reason": str(skip_reason)})
        for v in dep.get("vulns", []) or []:
            vid = str(v.get("id", "?"))
            entry = lookup_exempt(name, vid, table)
            item = {
                "package": name,
                "version": version,
                "id": vid,
                "aliases": list(v.get("aliases", []) or []),
                "fix_versions": list(v.get("fix_versions", []) or []),
                "description": str(v.get("description", "")),
                "exempt": False,
                "exempt_expired": False,
                "exempt_reason": None,
                "exempt_review_date": None,
            }
            if entry is not None:
                item["exempt_reason"] = entry.get("reason", "")
                item["exempt_review_date"] = entry.get("review_date", "")
                if exemption_expired(entry, today):
                    item["exempt_expired"] = True
                    n_exemptions_expired += 1
                else:
                    item["exempt"] = True
            vulnerabilities.append(item)

    unexempted = [v for v in vulnerabilities if not v["exempt"]]
    # 多库去重口径：pip-audit 2.10.1 同时查 PyPI JSON API 与 OSV，同一 PYSEC
    # 双源各记一条（别名集略异）——原始条目保留（证据保真），summary 另报
    # 唯一 (包, 漏洞 ID) 数作为修复工作量口径。
    unique_pairs = {(normalize_name(v["package"]), v["id"]) for v in vulnerabilities}
    status = "red" if unexempted else "green"
    return {
        "schema": REPORT_SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": status,
        "mode": "env",
        "pip_audit_version": pip_audit_version(),
        "summary": {
            "dependencies_scanned": len(deps),
            "dependencies_skipped": len(skipped_deps),
            "vulnerabilities_total": len(vulnerabilities),
            "vulnerabilities_unique": len(unique_pairs),
            "exempted": len(vulnerabilities) - len(unexempted),
            "unexempted": len(unexempted),
            "exemptions_expired": n_exemptions_expired,
        },
        "vulnerabilities": vulnerabilities,
        "skipped_dependencies": skipped_deps,
        "exempt_table": {k: dict(v) for k, v in (EXEMPT if table is None else table).items()},
        "degradation": {"skipped": False, "reason": None},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="依赖漏洞门（pip-audit 包装，QM-4）")
    parser.add_argument("--json", default=None, help="门报告 JSON 落盘路径")
    parser.add_argument("--raw-json", default=None, help="pip-audit 原始 JSON 留档路径")
    parser.add_argument("--requirements", default=None,
                        help="审计指定 requirements.txt（lock 导出面）而非当前环境")
    parser.add_argument("--timeout-s", type=int, default=1800, help="pip-audit 子进程超时秒数")
    args = parser.parse_args(argv)

    doc, err = run_pip_audit(requirements=args.requirements, timeout_s=args.timeout_s)
    if doc is None:
        report = {
            "schema": REPORT_SCHEMA,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "status": "skipped",
            "mode": "requirements" if args.requirements else "env",
            "pip_audit_version": pip_audit_version(),
            "summary": {"dependencies_scanned": 0, "dependencies_skipped": 0,
                        "vulnerabilities_total": 0, "vulnerabilities_unique": 0,
                        "exempted": 0, "unexempted": 0, "exemptions_expired": 0},
            "vulnerabilities": [],
            "skipped_dependencies": [],
            "exempt_table": {k: dict(v) for k, v in EXEMPT.items()},
            "degradation": {"skipped": True, "reason": err},
        }
        if args.json:
            Path(args.json).write_text(
                json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[audit-deps] SKIP——审计未能执行（不判绿不判红）：{err}")
        return 2

    if args.raw_json:
        Path(args.raw_json).write_text(
            json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")

    report = evaluate(doc)
    report["mode"] = "requirements" if args.requirements else "env"
    if args.json:
        Path(args.json).write_text(
            json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    s = report["summary"]
    print(f"[audit-deps] 已扫描 {s['dependencies_scanned']} 个依赖"
          f"（跳过 {s['dependencies_skipped']}）；"
          f"漏洞 {s['vulnerabilities_total']}"
          f"（去重 {s['vulnerabilities_unique']}；"
          f"豁免 {s['exempted']} / 未豁免 {s['unexempted']}）；"
          f"status={report['status']}")
    for v in report["vulnerabilities"]:
        if v["exempt"]:
            continue
        tag = " [豁免过期，须复审]" if v["exempt_expired"] else ""
        fix = "、".join(v["fix_versions"]) or "无已发布修复版本"
        print(f"  - {v['package']}=={v['version']}: {v['id']}"
              f"（{'/'.join(v['aliases']) or '无别名'}）修复建议={fix}{tag}")
    return 1 if report["status"] == "red" else 0


if __name__ == "__main__":
    raise SystemExit(main())
