"""pyproject 依赖钉版健康度审计（架构批 R8 面 6 结论制度化；2026-10-11
A7-D 席）。

R8 侦察结论："核心依赖全 floors + 有意 cap（skrf<3、optuna<6 带 ADR/OP
注记）+ extras 逐个带理由注释与惰性 import 归属；无过期钉版，无需立项。"
本脚本把该核查制度化（可复跑、可挂门），**纯离线**（零网络——上游最新
版本查询与任何升级/放宽 cap 属依赖本体变更，按 scripts/audit_deps.py 同
款口径留主代理裁决，本门只报告与守界）：

- 硬面（棘轮 0，违例即红；只收不放）：
  1. 矛盾声明：同名依赖在核心+extras 间的声明约束无可行版本（floor≥cap
     交叉、互异 == 精钉；语义直查覆盖此三形态，其余异形约束以实装满足
     性双保险）；
  2. venv 实装版本违反任一声明 specifier（check_env_deps.py conflict 类
     的声明面直查子集，双门冗余无害；缺装=missing 类归 check_env_deps）；
  3. extras 理由注释覆盖破棘轮（EXTRA_RATIONALE_RATCHET=0：2026-10-11
     实测 35/35 全有"键上方紧邻注释块或行内注释"；新增 extras 带一句理
     由+惰性 import 归属是既成 house style）。
- 报告面（永不红）：cap 余量（gap_major/gap_minor；near_cap=同 major 且
  距 cap ≤1 个 minor 的口径）、弱 floor（installed 领先 floor ≥2 个
  major）、约束形态分类计数（floor/cap/pin/range/wildcard/none）。

rc：0=绿；1=硬面违例；2=pyproject 不可读/无 project 表（诚实降级）。

用法：
  .venv/Scripts/python.exe scripts/audit_pin_health.py [--pyproject <path>]
      [--json <out>] [--verbose] [--no-env]

--no-env 跳过实装版本核对（纯声明面审计）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import tomllib
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

REPO = Path(__file__).resolve().parents[1]
REPO_DEFAULT = REPO / "pyproject.toml"

REPORT_SCHEMA = "r8/pin_health/1"

#: 硬面棘轮（现值基线 0 冻结，2026-10-11 实测；只收不放）。
CONTRADICTION_RATCHET = 0
INSTALLED_VIOLATION_RATCHET = 0
EXTRA_RATIONALE_RATCHET = 0

_SHAPE_NONE = "none"
_SHAPE_FLOOR = "floor"
_SHAPE_CAP = "cap"
_SHAPE_PIN = "pin"
_SHAPE_RANGE = "range"
_SHAPE_WILDCARD = "wildcard"

_OP_RE = re.compile(r"(===|==|>=|<=|!=|>|<|~=)\s*([^\s,;]+)")


def parse_declared(project: dict) -> dict[str, dict]:
    """[project] 表 → {canonical 名: {specs: [specifier 串], sources: [...]}}。

    纯函数（无 IO）；同名多源各自保留（矛盾检测消费面）。
    解析走 packaging.Requirement 正规口径（`pydantic>=2.5` 无空格形态
    手写 split 会把 specifier 并进名字——首版实测坑，勿回退）。
    """
    declared: dict[str, dict] = {}

    def _add(req_str: str, source: str) -> None:
        r = Requirement(req_str)
        name = canonicalize_name(r.name)
        spec = str(r.specifier)
        ent = declared.setdefault(name, {"specs": [], "sources": []})
        if spec:
            ent["specs"].append(spec)
        if source not in ent["sources"]:
            ent["sources"].append(source)

    for dep in project.get("dependencies") or []:
        _add(str(dep), "core")
    for extra, deps in (project.get("optional-dependencies") or {}).items():
        for dep in deps or []:
            _add(str(dep), f"extras:{extra}")
    return declared


def classify_shape(spec: str) -> str:
    """约束形态分类（单串）：floor/cap/pin/range/wildcard/none。"""
    s = spec.strip()
    if not s:
        return _SHAPE_NONE
    if "*" in s:
        return _SHAPE_WILDCARD
    ops = re.findall(r"===|==|>=|<=|!=|>|<|~=", s)
    if len(ops) > 1:
        return _SHAPE_RANGE
    op = ops[0] if ops else ""
    if op == "==":
        return _SHAPE_PIN
    if op in (">", ">="):
        return _SHAPE_FLOOR
    if op in ("<", "<="):
        return _SHAPE_CAP
    return _SHAPE_RANGE


def _bound(spec: str, op_set: tuple[str, ...]) -> Version | None:
    """spec 中首个属 op_set 的比较版本；无/不可解析返回 None。"""
    for m in _OP_RE.finditer(spec):
        if m.group(1) in op_set:
            raw = m.group(2)
            try:
                return Version(raw[:-2] if raw.endswith(".*") else raw)
            except Exception:
                return None
    return None


def find_contradictions(declared: dict[str, dict]) -> list[str]:
    """矛盾声明（声明面语义直查：互异精钉 / floor≥cap）。人读违规串列表。"""
    issues: list[str] = []
    for name, ent in sorted(declared.items()):
        specs = ent["specs"]
        if len(specs) < 2:
            continue
        pins = {_bound(s, ("==", "===")) for s in specs
                if classify_shape(s) == _SHAPE_PIN}
        pins.discard(None)
        if len(pins) > 1:
            issues.append(f"{name}: 互异精钉 "
                          f"{sorted(str(p) for p in pins)}"
                          f"（sources={ent['sources']}）")
            continue
        floors = [v for s in specs
                  if classify_shape(s) in (_SHAPE_FLOOR, _SHAPE_RANGE)
                  and (v := _bound(s, (">", ">="))) is not None]
        caps = []
        for s in specs:
            if classify_shape(s) not in (_SHAPE_CAP, _SHAPE_RANGE):
                continue
            v = _bound(s, ("<", "<="))
            if v is not None:
                caps.append((v, "<=" in s))
        for f in floors:
            for c, inclusive in caps:
                if (f > c) if inclusive else (f >= c):
                    issues.append(
                        f"{name}: floor {f} 与 cap {c} 不可同时满足"
                        f"（sources={ent['sources']}）")
    return issues


def check_installed(declared: dict[str, dict],
                    installed: dict[str, str]) -> list[str]:
    """实装版本须满足该名下全部声明 specifier；违例逐条列出（纯函数）。"""
    issues: list[str] = []
    for name, ent in sorted(declared.items()):
        if name not in installed:
            continue  # 缺装=missing 类，归 check_env_deps 管（非本门口径）
        for spec in ent["specs"]:
            req = Requirement(f"{name}{(' ' + spec) if spec else ''}")
            try:
                ok = req.specifier.contains(installed[name], prereleases=True)
            except Exception:
                ok = False
            if not ok:
                issues.append(
                    f"{name}: 实装 {installed[name]} 违反声明 "
                    f"'{spec or '(无约束)'}'（sources={ent['sources']}）")
    return issues


def cap_headroom(installed_ver: str, spec: str) -> dict | None:
    """cap 余量（报告面，纯函数）：有 < 上界的声明返回
    {cap, gap_major, gap_minor, near_cap}——near_cap=同 major 且距 cap
    ≤1 个 minor；跨 major 余量以 gap_major 表达（整型 cap 的常态）。"""
    cap = _bound(spec, ("<", "<="))
    if cap is None:
        return None
    try:
        inst = Version(installed_ver)
    except Exception:
        return {"cap": str(cap), "gap_major": None, "gap_minor": None,
                "near_cap": False}
    return {
        "cap": str(cap),
        "gap_major": max(cap.major - inst.major, 0),
        "gap_minor": max(cap.minor - inst.minor, 0)
        if cap.major == inst.major else 0,
        "near_cap": (inst.major == cap.major
                     and 0 <= cap.minor - inst.minor <= 1),
    }


def weak_floors(declared: dict[str, dict],
                installed: dict[str, str]) -> list[str]:
    """弱 floor（报告面，纯函数）：installed 领先 floor ≥2 个 major。"""
    out: list[str] = []
    for name, ent in sorted(declared.items()):
        if name not in installed:
            continue
        for spec in ent["specs"]:
            if classify_shape(spec) != _SHAPE_FLOOR:
                continue
            f = _bound(spec, (">", ">="))
            if f is None:
                continue
            try:
                inst = Version(installed[name])
            except Exception:
                continue
            if inst.major - f.major >= 2:
                out.append(f"{name}: floor >={f} vs 实装 {inst}"
                           f"（领先 {inst.major - f.major} major；"
                           f"sources={ent['sources']}）")
    return out


def extras_missing_rationale(lines: list[str], extra_keys: list[str]
                             ) -> list[str]:
    """extras 理由注释覆盖（house style：键上方紧邻连续注释块或行内注释）。
    返回缺理由的键列表（纯函数，行文本入参）。"""
    missing: list[str] = []
    for key in extra_keys:
        pat = re.compile(r"^" + re.escape(key) + r"\s*=")
        start = next((i for i, ln in enumerate(lines) if pat.match(ln)), None)
        if start is None:
            missing.append(key)
            continue
        if "#" in lines[start]:
            continue
        j = start - 1
        while j >= 0 and lines[j].lstrip().startswith("#"):
            j -= 1
        if j == start - 1:  # 键上方一行注释都没有
            missing.append(key)
    return missing


def shape_counts(declared: dict[str, dict]) -> dict[str, int]:
    """约束形态分类计数（报告面）。"""
    counts: dict[str, int] = {}
    for ent in declared.values():
        for spec in ent["specs"]:
            k = classify_shape(spec)
            counts[k] = counts.get(k, 0) + 1
    return counts


def installed_versions(names: list[str]) -> dict[str, str]:
    """venv 实装版本快照（importlib.metadata；缺装名跳过）。"""
    from importlib.metadata import version
    out: dict[str, str] = {}
    for name in names:
        try:
            out[name] = version(name)
        except Exception:
            continue
    return out


def verdict(report: dict) -> int:
    """报告 → 退出码（0 绿 / 1 硬面红 / 2 环境类 SKIP）。"""
    if report.get("error"):
        return 2
    hard = (len(report.get("contradictions", [])) > CONTRADICTION_RATCHET
            or len(report.get("installed_violations", []))
            > INSTALLED_VIOLATION_RATCHET
            or len(report.get("extras_missing_rationale", []))
            > EXTRA_RATIONALE_RATCHET)
    return 1 if hard else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="pyproject 钉版健康度审计（离线；评估面非升级面）")
    ap.add_argument("--pyproject", default=str(REPO_DEFAULT))
    ap.add_argument("--json", dest="json_out", default="")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--no-env", action="store_true",
                    help="跳过实装版本核对（纯声明面）")
    args = ap.parse_args(argv)

    path = Path(args.pyproject)
    report: dict = {"schema": REPORT_SCHEMA, "pyproject": str(path)}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        project = data["project"]
    except (OSError, KeyError, tomllib.TOMLDecodeError) as exc:
        report["error"] = f"pyproject 不可读/无 project 表: {exc}"
        print(f"[SKIP] {report['error']}")
        return verdict(report)

    declared = parse_declared(project)
    # extras 理由注释走 raw 文本行扫描（tomllib 丢注释）
    lines = path.read_text(encoding="utf-8").splitlines()
    extra_keys = list((project.get("optional-dependencies") or {}).keys())

    report.update({
        "core_deps": len(project.get("dependencies") or []),
        "extras": len(extra_keys),
        "declared_names": len(declared),
        "shape_counts": shape_counts(declared),
        "contradictions": find_contradictions(declared),
        "extras_missing_rationale": extras_missing_rationale(
            lines, extra_keys),
    })

    if not args.no_env:
        installed = installed_versions(sorted(declared))
        report["installed_checked"] = len(installed)
        report["installed_violations"] = check_installed(declared, installed)
        near_cap = []
        for n, ent in sorted(declared.items()):
            if n not in installed:
                continue
            for s in ent["specs"]:
                if classify_shape(s) in (_SHAPE_CAP, _SHAPE_RANGE):
                    h = cap_headroom(installed[n], s)
                    if h is not None:
                        near_cap.append({"name": n, **h})
        report["near_cap"] = near_cap
        report["weak_floors"] = weak_floors(declared, installed)

    rc = verdict(report)
    env_note = (f"实装违例 {len(report.get('installed_violations', []))}"
                if not args.no_env else "--no-env 跳过实装核对")
    print(f"声明 {report['declared_names']} 名（核心 {report['core_deps']}"
          f" + extras {report['extras']}）；形态 {report['shape_counts']}"
          + (f"；实装核对 {report.get('installed_checked', 0)} 名"
             if not args.no_env else ""))
    print(f"矛盾声明 {len(report['contradictions'])} / extras 缺理由 "
          f"{len(report['extras_missing_rationale'])} / {env_note}")
    if not args.no_env:
        cap_json = json.dumps(report.get("near_cap", []),
                              ensure_ascii=False)
        print(f"cap 余量：{cap_json}")
        print(f"弱 floor：{report.get('weak_floors', []) or '无'}")
    if args.verbose:
        for s in report["contradictions"]:
            print(f"  contradiction: {s}")
        for s in report.get("installed_violations", []):
            print(f"  violation: {s}")
        for k in report["extras_missing_rationale"]:
            print(f"  extra 无理由注释: {k}")
    if rc == 1:
        print("[FAIL] 钉版健康度硬面违例（矛盾/实装违例/extras 理由破棘轮；"
              "修复面见上；cap 放宽与升级属依赖本体变更留主代理裁决）")
    else:
        print("[PASS] 钉版健康度（离线评估面；升级/cap 调整不在本门权限）")
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(report, ensure_ascii=False, indent=1),
            encoding="utf-8")
    return rc


if __name__ == "__main__":
    sys.exit(main())
