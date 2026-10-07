"""XN-7 工具情报监控（round19 P3，ge8c 席C6）——release notes 扫描→能力差对照账本。

定位（round19 口径"AEDT/ADS/Optuna/skrf/openEMS release notes 定期扫描→
能力差对照表自动更新（KD-5 论文监控的姊妹件）"）：

- **接口面**（本席登记级交付，零真网）：目标工具注册表 + GitHub Releases
  API 查询 URL 构造 + 响应解析 + 本机已装版本探测 + 差异对照 + JSONL 账本
  登记。**单测全部 mock 通道**（litwatch_service ``_http_get`` 单点先例：
  默认通道收敛模块级单函数，测试经参数注入 canned 响应；真实抓取=CLI/
  script 手动触发，本模块零 CLI 依赖、不 import 网络 SDK）。
- **本机版本探测**：pip 可见包走 ``importlib.metadata``（optuna/scikit-rf/
  ansys-aedt-core）；非 pip 形态（ADS 安装树/openEMS 自建二进制）如实
  ``installed=None``（探测方法标注 local_install_probe，缺省不猜）——调用
  方可用 ``known_versions`` 显式传入。
- **诚实边界**（KD-5 同款纪律）：远端最新版只作 ``candidate`` 登记——
  是否升级/引入新 API 必须人工核对 release notes 原文，本管线只负责
  "发现与登记"；差异状态 unknown（本机版本不可探）如实记录不硬判。

账本：JSONL 追加、同 (tool, latest_tag) 幂等去重（重复登记跳过并计数）。
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

__all__ = [
    "TOOL_INTEL_SCHEMA",
    "TOOL_TARGETS",
    "build_releases_url",
    "detect_installed_version",
    "parse_release_payload",
    "render_intel_markdown",
    "scan_tools",
]

#: 情报账本契约版本。
TOOL_INTEL_SCHEMA = "rfauto-tool-intel-v1"

HttpGet = Callable[[str, float], bytes]

#: 默认 HTTP 单点（测试 monkeypatch/参数注入钉通道；本模块自身零真网调用
# 发起方——只有显式调用 scan_tools(http_get=默认) 才触网）。
def _http_get(url: str, timeout_s: float) -> bytes:
    import urllib.request

    req = urllib.request.Request(
        url, headers={"Accept": "application/vnd.github+json",
                      "User-Agent": "rfauto-tool-intel"})
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return resp.read()


#: 目标工具注册表（round19 五件）；pip_pkg=None = 非 pip 形态。
TOOL_TARGETS: dict[str, dict[str, Any]] = {
    "aedt": {"pip_pkg": "ansys-aedt-core", "pip_aliases": ["pyaedt"],
             "repo": "ansys/pyaedt",
             "note": "AEDT 自动化面；别名 pyaedt（旧发行名）"},
    "ads": {"pip_pkg": None, "pip_aliases": [], "repo": None,
            "note": "Keysight ADS 无公开 releases API；local_install_probe"},
    "optuna": {"pip_pkg": "optuna", "pip_aliases": [], "repo": "optuna/optuna",
               "note": "优化器内核（warm_start/sampler API 演进关注面）"},
    "skrf": {"pip_pkg": "scikit-rf", "pip_aliases": ["skrf"],
             "repo": "scikit-rf/scikit-rf",
             "note": "Touchstone/网络面（rank 推断等坑族关注面）"},
    "openems": {"pip_pkg": None, "pip_aliases": [], "repo": None,
                "note": "openEMS 自建绑定无 PyPI releases；local_install_probe"},
}

#: releases API 查询超时（秒）。
DEFAULT_TIMEOUT_S = 20.0


def build_releases_url(repo: str) -> str:
    """GitHub Releases latest 端点（repo 形态校验 owner/name）。"""
    parts = str(repo).strip("/").split("/")
    if len(parts) != 2 or not all(parts):
        raise ValueError(f"repo must be 'owner/name': {repo!r}")
    return f"https://api.github.com/repos/{parts[0]}/{parts[1]}/releases/latest"


def parse_release_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """GitHub release JSON → 账本条目字段（缺 tag 如实记 None 不硬造）。"""
    body = str(payload.get("body") or "")
    return {
        "latest_tag": payload.get("tag_name") or None,
        "release_name": payload.get("name") or None,
        "published_at": payload.get("published_at") or None,
        "prerelease": bool(payload.get("prerelease")),
        "body_excerpt": body[:600],
    }


def detect_installed_version(
    tool: str,
    known_versions: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """本机已装版本探测（pip 元数据；非 pip 形态如实 None）。"""
    if tool not in TOOL_TARGETS:
        raise KeyError(f"未登记工具: {tool!r}（可用 {sorted(TOOL_TARGETS)}）")
    if known_versions:
        provided = known_versions.get(tool)
        if isinstance(provided, str) and provided.strip():
            return {"installed": provided, "method": "caller_provided"}
        # 显式传 None/空 = 调用方声明不可探 → 直落 local_install_probe，
        # 不再尝试 pip 元数据（省一次误探）
        if tool in known_versions:
            return {"installed": None, "method": "local_install_probe"}
    target = TOOL_TARGETS[tool]
    candidates = [target["pip_pkg"], *target["pip_aliases"]]
    for pkg in filter(None, candidates):
        try:
            from importlib.metadata import PackageNotFoundError
            from importlib.metadata import version as _version

            return {"installed": _version(pkg), "method": f"importlib:{pkg}"}
        except PackageNotFoundError:
            continue
        except Exception as exc:  # 元数据损坏如实记录
            return {"installed": None, "method": f"importlib_error:{exc}"}
    return {"installed": None, "method": "local_install_probe"}


def _diff_status(installed: str | None, latest: str | None) -> str:
    if installed is None or latest is None:
        return "unknown"
    norm = lambda s: s.lstrip("vV").strip()  # noqa: E731 - tag 前缀归一
    return "up_to_date" if norm(installed) == norm(latest) else "behind"


def scan_tools(
    tools: list[str] | None = None,
    *,
    ledger_path: str | Path = "runs/tool_intel/candidates.jsonl",
    http_get: HttpGet | None = None,
    known_versions: Mapping[str, str] | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    now: str | None = None,
) -> dict[str, Any]:
    """工具情报扫描 → 差异对照 + 账本登记（JSON 进出；通道可注入）。

    - ``http_get`` 注入 canned 响应即为离线 mock（#139：测试必注入，禁真网）；
      GitHub 面返回非 2xx/非 JSON → 该工具 status=fetch_failed 如实留痕；
    - 无 repo 的目标（ads/openems）→ status=local_only（仅本机版本探测）；
    - 账本同 (tool, latest_tag) 幂等去重。
    """
    from rfauto.service.envelope import error_envelope, ok_envelope

    get = http_get if http_get is not None else _http_get
    want = list(tools) if tools else sorted(TOOL_TARGETS)
    for t in want:
        if t not in TOOL_TARGETS:
            return error_envelope(
                f"未登记工具: {t!r}（可用 {sorted(TOOL_TARGETS)}）")

    ledger_file = Path(ledger_path)
    seen: set[tuple[str, str]] = set()
    if ledger_file.is_file():
        for line in ledger_file.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
                seen.add((str(rec.get("tool")), str(rec.get("latest_tag"))))
            except json.JSONDecodeError:
                continue  # 坏行跳过（宁缺毋滥）

    ts = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    entries: list[dict[str, Any]] = []
    duplicates = 0
    for tool in want:
        target = TOOL_TARGETS[tool]
        det = detect_installed_version(tool, known_versions)
        entry: dict[str, Any] = {
            "tool": tool,
            "installed": det["installed"],
            "probe_method": det["method"],
            "status": "candidate",
            "diff": "unknown",
            "scanned_at": ts,
            "repo": target["repo"],
        }
        if target["repo"] is None:
            entry["status"] = "local_only"
            entry["note"] = target["note"]
        else:
            try:
                url = build_releases_url(str(target["repo"]))
                payload = json.loads(get(url, timeout_s))
                entry.update(parse_release_payload(payload))
                entry["diff"] = _diff_status(det["installed"],
                                             entry["latest_tag"])
                entry["url"] = url
            except Exception as exc:  # 网络面异常如实留痕，不炸批次
                entry["status"] = "fetch_failed"
                entry["note"] = str(exc)[:300]
        key = (tool, str(entry.get("latest_tag")))
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        entries.append(entry)

    if entries and ledger_file.parent:
        ledger_file.parent.mkdir(parents=True, exist_ok=True)
        with open(ledger_file, "a", encoding="utf-8") as fh:
            for e in entries:
                fh.write(json.dumps(e, ensure_ascii=False, sort_keys=True)
                         + "\n")

    return ok_envelope(
        schema=TOOL_INTEL_SCHEMA,
        ledger=str(ledger_file),
        n_scanned=len(want),
        n_new=len(entries),
        n_duplicates=duplicates,
        entries=entries,
        note="远端最新版仅 candidate 登记；升级/新 API 采用须人工核对原文",
    )


def render_intel_markdown(result: Mapping[str, Any]) -> str:
    """扫描结果 → Markdown 对照表（只渲染，不新造判断）。"""
    if not result.get("ok"):
        return f"# 工具情报\n\n- 扫描失败：{result.get('errors')}\n"
    lines = [
        "# 工具情报对照（candidate 登记）", "",
        "| 工具 | 本机 | 远端 tag | diff | 状态 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for e in result.get("entries") or []:
        lines.append(
            f"| {e['tool']} | {e.get('installed') or '未知'} "
            f"| {e.get('latest_tag') or '—'} | {e.get('diff')} "
            f"| {e.get('status')} |")
    lines += ["", f"> 账本：{result.get('ledger')}",
              f"> {result.get('note', '')}", ""]
    return "\n".join(lines)
