"""XD-6 step 契约 lint（圈定形态：独立只读脚本，零 promote 接线）。

出处链（池件裁定 runs/aurora_m/w4_2/xd_pool_verdict.md，W4-2 席）：
- 池登记：runs/pool_reaudit/reaudit_ledger_20261007.json sg_reserve
  open_by_group.XD_10（XD-2/3/4/6/10/12/13/14/15/16）+ TODO §〇 内核行
  "XD 系 P3 池件余量（XD-2 动态扩图/XD-6 step 契约 lint 等，圈定后成席）"。
- 原提案：docs/history/research/research_expansion_20261004_crossdomain_transplant.md
  XD-6——OpenLane2 可复现契约四禁映射（"The same step with the same input
  configuration and same input state must emit the same output"）：
  禁①不改输入文件/禁②不改 config/禁③不依赖外部路径/禁④钉 PRNG seed。
- 原载体 agent_sandbox promote 前置在 aurora_e W6-S29 被放弃（放弃理由
  "污染守卫敏感面"——promote 门是 #317 家族加固面）。本圈定**改载体**：
  独立只读脚本，零 promote/零 src 接线，放弃理由就此不成立化；消费方式=
  手动/CI/席位批前自证（merge_preflight 同位）。禁②（写侧不改 config）
  已由 infra/recipe_guard.py 守卫承担，本件不重复。

三检查：
① 输入哈希前后对拍（禁①）：sha256 清单 + ``--baseline`` 差分
   （mutated/removed/added；#317 配方污染、#276 网表死绝对路径即此类）。
② 外部路径静态扫（禁③）：盘符/UNC/POSIX 系统根/``~/`` 展开形态，
   URL 误报守卫内置（``https://`` 前缀不命中）。
③ 缺 seed 随机性报警（禁④）：随机源 token 命中且无 seed 钉 →
   报警级（不进退出码；配方链 seed 由 CLI 供给 optimizer.SAMPLER_SEED=42
   并记 provenance #158，静态面只报警不定罪）。

退出码（XD-9 audit-stale 同款三态）：0=clean / 1=有违例（①②）/
2=程序性错误。JSON 输出零时间戳（XD-16 逐字节一致教训）——同输入重跑
逐字节同 report，``--baseline`` 对拍因此可靠。

分层：scripts/ 只依赖标准库；消费面（recipes/*.yaml、渲染脚本、ADS 网表、
沙箱草稿）一律只读。用法：
    python scripts/step_contract_lint.py recipes/wilkinson_pd_v1.yaml --json
    python scripts/step_contract_lint.py a.yaml b.py --baseline prev.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

SCHEMA = "step_contract_lint_v1"

# ── 禁③：外部路径形态（OpenLane "不依赖外部路径"）────────────────────────
_EXTERNAL_PATTERNS: tuple[tuple[str, str], ...] = (
    # 盘符形态 E:\ / C:/（#8 上传零敏感同源面；#275/#276/#295 死路径家族）
    (r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]", "drive_letter"),
    # UNC \\server\share（两前导反斜杠+主机名+单反斜杠+共享名首字符）
    (r"\\\\[^\\/\s]+\\[^\\/\s]", "unc"),
    # POSIX 系统根（URL 误报守卫：前面不能是 : / 字母数字——https:// 被拦）
    (
        r"(?<![:\w/)])/(?:home|Users|root|tmp|var|opt|etc|mnt|media|srv|usr"
        r"(?:/local)?)/",
        "posix_root",
    ),
    # ~/ 展开形态（机器相关家目录）
    (r"(?<![\w/])~/", "home_expand"),
)
_EXTERNAL_RE = [(re.compile(p), kind) for p, kind in _EXTERNAL_PATTERNS]

# ── 禁④：随机源 token 与 seed 钉 ────────────────────────────────────────
_RANDOMNESS_RE = re.compile(
    r"\bnp\.random\.\w+"
    r"|\bnumpy\.random\.\w+"
    r"|\brandom\.(?:random|randint|randrange|uniform|choice|choices|shuffle"
    r"|sample|gauss|betavariate|weibullvariate)\b"
    r"|\boptuna\.(?:samplers|create_study)"
    r"|\brng\b",
)
_SEED_PIN_RE = re.compile(
    r"\bseed\s*[:=]"
    r"|\bnp\.random\.seed\("
    r"|\bdefault_rng\(\s*\d"
    r"|\bRandom\(\s*\d"
    r"|\bSAMPLER_SEED\b"
)

_MAX_SNIPPET = 96


def sha256_file(path: Path) -> str:
    """文件 sha256（原始字节流，二进制安全）。"""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _snippet(line: str, col: int) -> str:
    text = line.strip()
    if len(text) <= _MAX_SNIPPET:
        return text
    start = max(0, col - 24)
    return ("..." if start > 0 else "") + text[start:start + _MAX_SNIPPET] + "..."


def scan_external_paths(text: str) -> list[dict]:
    """禁③：静态扫外部路径形态，findings 带 file 留白由调用方补。"""
    findings: list[dict] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for regex, kind in _EXTERNAL_RE:
            for m in regex.finditer(line):
                findings.append({
                    "line": lineno,
                    "col": m.start() + 1,
                    "kind": kind,
                    "rule": "external_path",
                    "snippet": _snippet(line, m.start()),
                })
    return findings


def scan_randomness(text: str) -> list[str]:
    """禁④：随机源 token 命中清单（无序去重，报警级）。"""
    hits = {m.group(0) for m in _RANDOMNESS_RE.finditer(text)}
    return sorted(hits)


def build_manifest(paths: list[Path]) -> dict[str, dict]:
    """输入文件 sha256 清单（键=传入路径原文，跨轮对拍同 cwd 口径）。"""
    manifest: dict[str, dict] = {}
    for p in paths:
        manifest[str(p)] = {"sha256": sha256_file(p), "bytes": p.stat().st_size}
    return dict(sorted(manifest.items()))


def compare_baseline(manifest: dict[str, dict], baseline: dict) -> list[dict]:
    """禁①对拍：当前清单 vs 基线清单，四态差分（同输入态必须同输出）。"""
    findings: list[dict] = []
    base = baseline.get("digests", {})
    for path in sorted(set(base) - set(manifest)):
        findings.append({"file": path, "rule": "input_removed",
                         "detail": "baseline 有而本轮未纳入"})
    for path in sorted(set(manifest) - set(base)):
        findings.append({"file": path, "rule": "input_added",
                         "detail": "本轮新增输入（输入配置态漂移）"})
    for path in sorted(set(manifest) & set(base)):
        old = base[path].get("sha256")
        new = manifest[path].get("sha256")
        if old is not None and new is not None and old != new:
            findings.append({"file": path, "rule": "input_mutated",
                             "detail": f"sha256 {old[:12]}.. -> {new[:12]}.."})
    return findings


def lint_paths(paths: list[Path], baseline: dict | None = None) -> dict:
    """三检查主入口：返回零时间戳 report（同输入重跑逐字节一致）。"""
    digests = build_manifest(paths)
    findings: list[dict] = []
    warnings: list[dict] = []
    for p in paths:
        text = p.read_text(encoding="utf-8", errors="replace")
        for f in scan_external_paths(text):
            findings.append({"file": str(p), **f})
        tokens = scan_randomness(text)
        if tokens and not _SEED_PIN_RE.search(text):
            warnings.append({
                "file": str(p),
                "rule": "randomness_no_seed",
                "tokens": tokens,
                "hint": "随机源无 seed 钉（XD-6 禁④报警级；配方链 seed "
                        "由 CLI optimizer.SAMPLER_SEED=42 供给并记 provenance）",
            })
    if baseline is not None:
        findings.extend(compare_baseline(digests, baseline))
    findings.sort(key=lambda f: (str(f.get("file", "")),
                                 f.get("line", 0), f.get("col", 0)))
    return {
        "ok": True,
        "schema": SCHEMA,
        "verdict": "PASS" if not findings else "FAIL",
        "n_files": len(paths),
        "digests": digests,
        "findings": findings,
        "warnings": sorted(warnings, key=lambda w: str(w["file"])),
    }


def load_baseline(path: Path) -> dict:
    """基线装载与 schema 校验（程序性错误抛 ValueError→main 落 exit 2）。"""
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        raise ValueError(f"baseline schema 非 {SCHEMA}：{path}")
    if not isinstance(doc.get("digests"), dict):
        raise ValueError(f"baseline 缺 digests 清单：{path}")
    return doc


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="step_contract_lint",
        description="XD-6 step 契约 lint（禁①输入哈希对拍/禁③外部路径扫/"
                    "禁④缺 seed 报警；独立只读，零 promote 接线）")
    ap.add_argument("paths", nargs="+",
                    help="step 工件路径（recipe YAML/渲染脚本/网表/沙箱草稿，只读）")
    ap.add_argument("--baseline", default=None,
                    help="上轮 lint report JSON（--baseline 对拍禁①）")
    ap.add_argument("--json", action="store_true",
                    help="JSON report 到 stdout（零时间戳，可作下轮基线）")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    paths = [Path(p) for p in args.paths]
    missing = [str(p) for p in paths if not p.is_file()]
    if missing:
        print(json.dumps({"ok": False, "schema": SCHEMA,
                          "error": f"输入文件不存在：{missing}"},
                         ensure_ascii=False))
        return 2
    baseline = None
    if args.baseline:
        try:
            baseline = load_baseline(Path(args.baseline))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(json.dumps({"ok": False, "schema": SCHEMA,
                              "error": f"基线装载失败：{exc}"},
                             ensure_ascii=False))
            return 2
    try:
        report = lint_paths(paths, baseline=baseline)
    except OSError as exc:
        print(json.dumps({"ok": False, "schema": SCHEMA,
                          "error": f"读面失败：{exc}"}, ensure_ascii=False))
        return 2
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1, sort_keys=True))
    else:
        for f in report["findings"]:
            loc = f"/L{f['line']}C{f['col']}" if "line" in f else ""
            print(f"VIOLATION [{f['rule']}] {f['file']}{loc} "
                  f"{f.get('kind', '')} {f.get('snippet', f.get('detail', ''))}")
        for w in report["warnings"]:
            print(f"WARNING [{w['rule']}] {w['file']} tokens={w['tokens']}")
        print(f"step_contract_lint: {report['verdict']} "
              f"(files={report['n_files']}, findings={len(report['findings'])}, "
              f"warnings={len(report['warnings'])})")
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
