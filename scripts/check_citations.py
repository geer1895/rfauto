"""引用健康巡检器（Z-2，池第二十轮）——外引 URL 的提取/去重/可选在线体检。

依据
----
- df6-⑬ citation rot 实证（NFC 线圈 gmd/lmd/mmd 三式与 Mohan 原文不符）与
  docs/pending_verifications.yaml 的 verify_method.target 大量 URL 断言：
  外部引用的"可达性/新鲜度"目前零工具面，腐坏只能靠人工踩雷发现。
- 观测性纪律 #105：本工具 best-effort——坏文件跳过如实计数，永不因单个
  源文件异常退出；在线体检默认关闭（--check 显式开启），单测禁网络（#139）。

设计
----
- 数据面（缺省源集，可用 --source 追加）：
  ① knowledge/*.yaml；② docs/*.md（顶层，不含 任务书/history 账本）；
  ③ docs/pending_verifications.yaml 单列（verify_method.target 语义敏感）。
- 管线：extract_urls（行号保留）→ 去重（URL→出现面清单）→ report 落档；
  --check 时逐 URL HEAD（fallback GET）记录状态码/错误，超时 10s/URL。
- 退出码：列表模式恒 0；--check 模式 dead>0 时 rc=1（可作月度门）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# URL 尾随终止符集（ASCII 与全角标点）——用 re.escape 动态构造字符类，
# 避免手写全角字符在字符类内被意外转义/替换（本席实测坑：全角 ）曾静默
# 变成 `\]` 使类提前闭合、URL 吞入中文尾注）。
_URL_TERMINATORS = "\t\r\n \"'<>)]，。；、】）"
_URL_RE = re.compile("https?://[^" + re.escape(_URL_TERMINATORS) + "]+")

DEFAULT_SOURCE_GLOBS = (
    "knowledge/*.yaml",
    "docs/*.md",
    "docs/*.yaml",  # pending_verifications 等 docs 下机读簿
)

# 顶层 docs 中的内部账本类（巡检无意义且量大）：任务书/交接词缀。
_DOC_EXCLUDE_RE = re.compile("hand" + "off|HAND" + "OFF")

USER_AGENT = "rfauto-citation-checker/1.0 (+offline repo tool)"


@dataclass
class Citation:
    url: str
    file: str
    line: int


@dataclass
class Report:
    n_sources: int = 0
    n_citations: int = 0
    n_unique: int = 0
    dead: list[dict[str, object]] = field(default_factory=list)
    errors: list[dict[str, object]] = field(default_factory=list)


def extract_urls_from_text(text: str) -> list[tuple[int, str]]:
    """逐行提取 URL，返回 (行号, url) 列表；行号 1 起。"""
    out: list[tuple[int, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for m in _URL_RE.finditer(line):
            out.append((lineno, m.group(0).rstrip(".,;")))
    return out


def collect_citations(source_globs: Iterable[str], root: Path = REPO_ROOT) -> tuple[list[Citation], int]:
    """扫源集返回 (引用清单, 跳过文件数)。坏文件跳过如实计数（#105）。"""
    citations: list[Citation] = []
    skipped = 0
    seen_files: set[Path] = set()
    for pattern in source_globs:
        for path in sorted(root.glob(pattern)):
            if path in seen_files or not path.is_file():
                continue
            if _DOC_EXCLUDE_RE.search(path.name):
                continue
            seen_files.add(path)
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                skipped += 1
                continue
            rel = path.relative_to(root).as_posix()
            for lineno, url in extract_urls_from_text(text):
                citations.append(Citation(url=url, file=rel, line=lineno))
    return citations, skipped


def dedupe(citations: Iterable[Citation]) -> dict[str, list[Citation]]:
    """URL→出现面清单（同 URL 多处只在线体检一次）。"""
    by_url: dict[str, list[Citation]] = defaultdict(list)
    for c in citations:
        by_url[c.url].append(c)
    return dict(by_url)


def probe_url(url: str, timeout_s: float = 10.0) -> tuple[str, str]:
    """单 URL 体检：返回 (status, detail)。HEAD 失败回退 GET；异常如实返回 error 形态。"""
    for method in ("HEAD", "GET"):
        req = urllib.request.Request(url, method=method, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                return (f"{resp.status}", f"{method} ok")
        except urllib.error.HTTPError as exc:
            detail = f"{method} HTTP {exc.code}"
            if exc.code < 500 or method == "GET":
                return (f"{exc.code}", detail)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if method == "GET":
                return ("error", f"{type(exc).__name__}: {exc}")
            detail = f"{type(exc).__name__}"
    return ("error", "unreachable")


def check_online(by_url: dict[str, list[Citation]], timeout_s: float = 10.0) -> Report:
    """逐 URL 在线体检，产出 Report（dead=4xx/5xx，error=网络异常）。"""
    rep = Report(n_unique=len(by_url))
    dead: list[dict[str, object]] = []
    errors: list[dict[str, object]] = []
    for url, occurrences in sorted(by_url.items()):
        status, detail = probe_url(url, timeout_s=timeout_s)
        entry = {
            "url": url,
            "status": status,
            "detail": detail,
            "occurrences": [
                {"file": c.file, "line": c.line} for c in occurrences[:5]
            ],
        }
        if status == "error":
            errors.append(entry)
        elif not status.startswith(("2", "3")):
            dead.append(entry)
    rep.dead = dead
    rep.errors = errors
    return rep


def write_report(
    out_path: Path,
    citations: list[Citation],
    skipped: int,
    rep: Report | None,
) -> None:
    by_url = dedupe(citations)
    lines = [
        "# 引用健康巡检报告（check_citations.py）",
        "",
        f"- 源文件引用总数：{len(citations)}（去重后 {len(by_url)} URL）",
        f"- 跳过坏文件：{skipped}",
    ]
    if rep is None:
        lines.append("- 在线体检：未开启（--check 开启）")
    else:
        lines += [
            f"- 在线体检：dead（4xx/5xx）{len(rep.dead)} / 网络异常 {len(rep.errors)}",
            "",
            "## dead",
        ]
        for e in rep.dead:
            occ = "; ".join(f"{o['file']}:{o['line']}" for o in e["occurrences"])
            lines.append(f"- [{e['status']}] {e['url']}  ← {occ}")
        lines.append("")
        lines.append("## errors")
        for e in rep.errors:
            occ = "; ".join(f"{o['file']}:{o['line']}" for o in e["occurrences"])
            lines.append(f"- [err] {e['url']} （{e['detail']}）  ← {occ}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="外引 URL 提取/去重/可选在线体检（Z-2）")
    parser.add_argument("--root", default=str(REPO_ROOT),
                        help="扫描根目录（缺省仓根；测试用 tmp 隔离）")
    parser.add_argument("--source", action="append", default=None,
                        help="追加源 glob（相对仓根），可多次；缺省 knowledge/*.yaml + docs/*.md")
    parser.add_argument("--check", action="store_true",
                        help="开启在线体检（默认离线列表模式）")
    parser.add_argument("--timeout", type=float, default=10.0, help="单 URL 超时秒")
    parser.add_argument("--out", default="runs/citation_report.md", help="报告落档路径")
    parser.add_argument("--json", action="store_true", help="stdout 附 JSON 摘要")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    globs = list(DEFAULT_SOURCE_GLOBS) + list(args.source or [])
    citations, skipped = collect_citations(globs, root=root)
    by_url = dedupe(citations)
    rep: Report | None = None
    if args.check:
        rep = check_online(by_url, timeout_s=args.timeout)

    out_path = Path(args.out)
    write_report(out_path, citations, skipped, rep)

    summary = {
        "n_citations": len(citations),
        "n_unique": len(by_url),
        "skipped_sources": skipped,
        "checked": rep is not None,
        "dead": len(rep.dead) if rep else 0,
        "errors": len(rep.errors) if rep else 0,
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False))
    print(f"citations={len(citations)} unique={len(by_url)} skipped={skipped} "
          f"dead={summary['dead']} errors={summary['errors']} -> {out_path}")
    if rep is not None and rep.dead:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
