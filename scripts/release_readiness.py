#!/usr/bin/env python3
"""B 组发布类"一条命令可发布、但绝不发布"（用户 2026-09-16 口径，方案
F4 MCP 发布 / F6 公开榜单 / H1 开源 PDK / H3 方法学材料 / 6.6 基准集 / 5.6 生态抽取 / H6 SBOM 清单）。

红线（最高优先）：
- 本脚本**没有任何发布通道**：只有 ``--check``（就绪度校验，exit 0=就绪）
  与 ``--build``（本地产物落 runs/release_staging/<item>/，不出仓库）。
  不 git push/tag、不 twine upload、不 gh release、无任何对外网络调用；
  发布动作永远由用户手动执行（README「发布就绪与手动发布步骤」一节）。
- 数字铁律 7：榜单/清单/图表里的一切数字只从 runs/ 既有 JSON 读出并原值
  搬运（排序与文本格式化除外，零算术改写）。
- 离线：--check 全程只读仓库；--build 的子进程仅
  ``python -m build --no-isolation``（本地 hatchling，不拉网）与
  ``twine check``（纯本地元数据校验）。

用法：
    python scripts/release_readiness.py --check          # 七节 PASS/FAIL 表
    python scripts/release_readiness.py --build          # 七节产物到 staging
    python scripts/release_readiness.py --check --build  # 先校验后构建
    python scripts/release_readiness.py --sdist-hygiene  # 单节：sdist 成员卫生（质量门/CI，0dd⑤）
    # 可选：--staging <dir>（默认 runs/release_staging）
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import html
import importlib.util
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tomllib

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STAGING = REPO_ROOT / "runs" / "release_staging"
BENCHMARK_DIR = REPO_ROOT / "runs" / "benchmark"
MESH_CONV_JSON = BENCHMARK_DIR / "mline_mesh_convergence.json"
WP39_SUMMARY = REPO_ROOT / "runs" / "wp39_mvp" / "summary.json"
DATASET_REGISTRY = REPO_ROOT / "runs" / "datasets"
TEMPLATES_DIR = REPO_ROOT / "docs" / "templates"
RECIPES_DIR = REPO_ROOT / "recipes"
RF_REF_DOC = REPO_ROOT / "docs" / "rf_template_references.md"
LICENSE_FILE = REPO_ROOT / "LICENSE"
CITATION_FILE = REPO_ROOT / "CITATION.cff"
ECOSYSTEM_DOC = REPO_ROOT / "docs" / "release" / "ecosystem_extraction.md"
PAPER_OUTLINE = REPO_ROOT / "docs" / "paper" / "outline.md"
PAPER_FIGURES_SCRIPT = REPO_ROOT / "scripts" / "paper_figures.py"
PYPROJECT = REPO_ROOT / "pyproject.toml"

# 5.6 生态抽取最小口径的候选模块（可独立复用；依赖边界由 AST 实测）
ECOSYSTEM_CANDIDATES = [
    "src/rfauto/core/synthesis.py",
    "src/rfauto/core/calculators.py",
    "src/rfauto/core/objectives.py",
    "src/rfauto/core/anchor_benchmark.py",
    "src/rfauto/infra/visualization.py",
    "src/rfauto/service/dataset_insights.py",
]


# ─── 结果模型 ───────────────────────────────────────────────────────────────

@dataclass
class Item:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class Section:
    key: str
    title: str
    items: list[Item] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        return "PASS" if self.items and all(i.ok for i in self.items) else "FAIL"


# ─── 通用工具 ───────────────────────────────────────────────────────────────

def _load_script_module(mod_name: str) -> Any:
    """按路径加载 scripts/<mod_name>.py（同源复用其常量/函数，不复制漂移）。"""
    path = REPO_ROOT / "scripts" / f"{mod_name}.py"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def asyncio_run(coro: Any) -> Any:
    import asyncio

    return asyncio.run(coro)


def _rel(path: Path) -> str:
    """仓库相对 posix 路径；不在仓库内（tmp staging/测试 fixture）时回退绝对路径。"""
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


# 目录版编码检查额外跳过的二进制后缀（check_encoding.SKIP_SUFFIXES 面向 git 跟踪源文件，
# 不含数据集/图表产物格式）
EXTRA_BINARY_SUFFIXES = {".parquet", ".h5", ".hdf5", ".npz", ".npy", ".gz", ".tar", ".whl", ".pyc"}


def scan_dir_sensitive(root: Path) -> list[str]:
    """对目录递归跑脱敏正则（BLACKLIST 从 scripts/scan_sensitive.py 同源加载）。"""
    import re

    mod = _load_script_module("scan_sensitive")
    pats = [re.compile(p, re.IGNORECASE) for p in mod.BLACKLIST]
    violations: list[str] = []
    for f in sorted(root.rglob("*")):
        if not f.is_file() or f.suffix not in (".py", ".yaml", ".yml", ".json", ".md", ".txt", ".html"):
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for p in pats:
            for m in p.finditer(text):
                rel = f.relative_to(root)
                violations.append(f"{rel}:{m.start()}: {m.group()}")
    return violations


def check_dir_encoding(root: Path) -> list[str]:
    """目录版 UTF-8 无 BOM 检查（SKIP_SUFFIXES/has_bom 从 scripts/check_encoding.py 同源加载）。"""
    mod = _load_script_module("check_encoding")
    bad: list[str] = []
    for f in sorted(root.rglob("*")):
        if not f.is_file() or f.suffix.lower() in mod.SKIP_SUFFIXES or f.suffix.lower() in EXTRA_BINARY_SUFFIXES:
            continue
        rel = f.relative_to(root)
        try:
            if mod.has_bom(f):
                bad.append(f"{rel}: UTF-8 BOM")
            f.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            bad.append(f"{rel}: 非 UTF-8（{exc}）")
        except OSError as exc:
            bad.append(f"{rel}: 读取失败（{exc}）")
    return bad


def load_pyproject_project() -> dict[str, Any]:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return dict(data.get("project") or {})


def write_json_deterministic(path: Path, payload: Any) -> None:
    """确定性 JSON 落盘：sort_keys + ensure_ascii=False + UTF-8 无 BOM，无时间戳。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_sha256sums(root: Path) -> Path:
    """对 root 下所有文件写 SHA256SUMS.txt（相对路径排序，确定性）。"""
    lines = []
    for f in sorted(p for p in root.rglob("*") if p.is_file()):
        if f.name == "SHA256SUMS.txt":
            continue
        lines.append(f"{sha256_file(f)}  {f.relative_to(root).as_posix()}")
    out = root / "SHA256SUMS.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def _reset_dir(path: Path) -> Path:
    """清空重建 staging 自管子目录（白名单点名，不碰他物）。"""
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _run_offline(cmd: list[str], timeout_s: int = 600) -> tuple[bool, str]:
    """跑本离子进程；非零退出返回 (False, stderr 尾部)——不吞错（#122）。"""
    proc = subprocess.run(
        cmd, cwd=str(REPO_ROOT), capture_output=True, text=True,
        timeout=timeout_s, check=False,
    )
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-800:]
        return False, f"exit={proc.returncode}: {tail}"
    return True, (proc.stdout or "")[-800:]


# ─── 数据源（F6 榜单 / H3 图共用，全部只读） ─────────────────────────────────

def collect_benchmark_sources() -> list[Path]:
    return sorted(BENCHMARK_DIR.glob("*_engine_benchmark.json"))


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_leaderboard_payload() -> dict[str, Any]:
    """从 runs/ 既有 JSON 组装榜单数据（字段原值搬运，零算术改写、零时间戳）。"""
    sources: list[dict[str, str]] = []
    anchors: list[dict[str, Any]] = []
    for path in collect_benchmark_sources():
        data = read_json(path)
        # metrics/criteria 整块原值搬运（各锚键集不同：atten/ratrace 为 delta_eps_pct，
        # msl_cpw/via 为 delta_eps1/2_pct）——不挑字段即不引入选择偏差
        anchors.append({
            "anchor": data.get("anchor"),
            "gate_version": data.get("gate_version"),
            "captured_at": data.get("captured_at"),
            "verdict": data.get("verdict"),
            "metrics": data.get("metrics") or {},
            "criteria": data.get("criteria") or {},
            "source": _rel(path),
        })
        sources.append({"path": _rel(path), "sha256": sha256_file(path)})
    anchors.sort(key=lambda r: str(r.get("anchor")))

    mesh_rows: list[dict[str, Any]] = []
    if MESH_CONV_JSON.exists():
        data = read_json(MESH_CONV_JSON)
        sources.append({"path": _rel(MESH_CONV_JSON), "sha256": sha256_file(MESH_CONV_JSON)})
        for entry in data.get("entries") or []:
            mesh_rows.append({
                "mesh_mm": entry.get("mesh_mm"),
                "ok": entry.get("ok"),
                "s11_max_db": entry.get("s11_max_db"),
                "eps_eff": entry.get("eps_eff"),
                "delta_vs_hj_pct": entry.get("delta_vs_hj_pct"),
                "delta_vs_gold_pct": entry.get("delta_vs_gold_pct"),
                "wall_s": entry.get("wall_s"),
            })
        mesh_rows.sort(key=lambda r: (r.get("mesh_mm") is None, r.get("mesh_mm")))

    wp39: dict[str, Any] | None = None
    if WP39_SUMMARY.exists():
        data = read_json(WP39_SUMMARY)
        sources.append({"path": _rel(WP39_SUMMARY), "sha256": sha256_file(WP39_SUMMARY)})
        problems = []
        for name in sorted(data.get("problems") or {}):
            p = (data.get("problems") or {})[name]
            problems.append({
                "problem": p.get("problem", name),
                "verdict": p.get("verdict"),
                "budget_ok": p.get("budget_ok"),
                "wallclock_ok": p.get("wallclock_ok"),
                "cost_ok": p.get("cost_ok"),
                "wallclock_ratio": p.get("wallclock_ratio"),
                "degradation_pct": p.get("degradation_pct"),
                "n_evals_candidate": p.get("n_evals_candidate"),
                "n_evals_baseline": p.get("n_evals_baseline"),
            })
        wp39 = {"schema": data.get("schema"), "problems": problems}

    return {
        "kind": "rfauto_public_leaderboard",
        "note": "全部数值为 runs/ 既有 JSON 的原值搬运（本生成器零算术改写）；"
                "verdict/门限语义见各源文件 criteria 与 开发注记 对应教训编号。",
        "sources": sources,
        "anchors": anchors,
        "mesh_convergence": mesh_rows,
        "wp39_factory": wp39,
    }


# ─── 七节实现 ───────────────────────────────────────────────────────────────

def sec_f4_mcp(staging: Path, build: bool) -> Section:
    """F4 MCP 发布包：pyproject 元数据 + MCP 清单 + sdist/wheel + twine check。"""
    sec = Section("f4_mcp", "F4 MCP 发布包")
    proj = load_pyproject_project()

    missing = [k for k in ("name", "version", "description", "readme", "license", "authors", "keywords", "classifiers")
               if not proj.get(k)]
    sec.items.append(Item(
        "pyproject 发布元数据齐全", not missing,
        "缺 " + ", ".join(missing) if missing else
        f"name={proj.get('name')} version={proj.get('version')} authors/keywords/classifiers 就绪"))
    if "urls" not in proj:
        sec.notes.append("project.urls 待用户补公开仓库 URL（不编造 URL，F4 followUp）")

    # AU-1 批3 拆分（2026-09-30）：facade + mcp_tools/ 工具组包聚合口径
    _mcp_srcs = [
        REPO_ROOT / "src" / "rfauto" / "mcp_server.py",
        *sorted((REPO_ROOT / "src" / "rfauto" / "mcp_tools").glob("*.py")),
    ]
    tool_count_src = len([
        line for f in _mcp_srcs for line in f.read_text(encoding="utf-8").splitlines()
        if line.startswith("@mcp.tool")])
    tools: list[dict[str, Any]] = []
    try:
        from rfauto.mcp_server import mcp as fastmcp_instance

        tools = [
            {"name": t.name, "description": t.description or "",
             "parameters": t.parameters or {}, "tags": sorted(str(x) for x in (t.tags or ()))}
            for t in asyncio_run(fastmcp_instance.list_tools())
        ]
        empty_desc = [t["name"] for t in tools if not t["description"]]
        ok = bool(tools) and len(tools) == tool_count_src and not empty_desc
        sec.items.append(Item(
            "MCP 工具面可枚举且与源码装饰器数一致", ok,
            f"运行时 {len(tools)} 个 / 源码 @mcp.tool {tool_count_src} 个"
            + (f"；空描述：{empty_desc}" if empty_desc else "")))
    except ImportError as exc:
        sec.items.append(Item("MCP 工具面可枚举且与源码装饰器数一致", False,
                              f"fastmcp/rfauto 不可导入：{exc}（pip install -e '.[mcp]'）"))

    # console script（w1a-shell-front，2026-09-18）：pyproject [project.scripts]
    # rfauto-mcp → rfauto.mcp_server:main，且目标可解析为可调用（真检查，不再是注记）
    scripts = proj.get("scripts") or {}
    target = str(scripts.get("rfauto-mcp") or "")
    main_ok = False
    if target == "rfauto.mcp_server:main":
        try:
            main_ok = callable(getattr(importlib.import_module("rfauto.mcp_server"), "main", None))
        except Exception:
            main_ok = False
    sec.items.append(Item(
        "console script rfauto-mcp 指向 mcp_server.main 且可调用", main_ok,
        f"[project.scripts] rfauto-mcp = {target!r}" + ("（main() 可调用）" if main_ok
        else "——需为 'rfauto.mcp_server:main' 且 main() 存在；用户仍可 python -m rfauto.mcp_server")))

    has_build = importlib.util.find_spec("build") is not None
    has_twine = importlib.util.find_spec("twine") is not None
    missing_tools = [n for n, ok in (("build", has_build), ("twine", has_twine)) if not ok]
    sec.items.append(Item(
        "build/twine 本地可用", not missing_tools,
        "build/twine 已在 .venv（E 盘）" if not missing_tools
        else "缺 " + ", ".join(missing_tools) + "——pip install build twine hatchling 进 .venv"))

    if not build:
        return sec

    # 产物 1：MCP 清单（工具名/描述/参数 schema 从注册表自动导出，按名排序确定性）
    manifest = {
        "kind": "rfauto_mcp_manifest",
        "source": "rfauto.mcp_server（fastmcp 注册表自动导出，非手写）",
        "tool_count": len(tools),
        "tools": sorted(tools, key=lambda t: t["name"]),
    }
    write_json_deterministic(staging / "mcp" / "manifest.json", manifest)
    sec.outputs.append("runs/release_staging/mcp/manifest.json")

    # 产物 2：sdist+wheel（--no-isolation：用本地 hatchling，不拉网）
    dist_dir = _reset_dir(staging / "dist")
    ok_build, msg_build = _run_offline(
        [sys.executable, "-m", "build", "--no-isolation", "--outdir", str(dist_dir)],
        timeout_s=900)
    artifacts = sorted(dist_dir.glob("*")) if dist_dir.exists() else []
    has_sdist = any(p.suffix == ".gz" for p in artifacts)
    has_wheel = any(p.suffix == ".whl" for p in artifacts)
    sec.items.append(Item(
        "python -m build 产 sdist+wheel", ok_build and has_sdist and has_wheel,
        msg_build.strip().splitlines()[-1] if msg_build.strip() else
        f"{len(artifacts)} 个产物（sdist={has_sdist} wheel={has_wheel}）"))

    # 产物 3：twine check（纯本地元数据/长描述渲染校验，无上传）
    if artifacts:
        ok_twine, msg_twine = _run_offline(
            [sys.executable, "-m", "twine", "check", *[str(p) for p in artifacts]])
        sec.items.append(Item(
            "twine check PASS", ok_twine,
            "PASSED" if ok_twine else msg_twine.strip().splitlines()[-1] if msg_twine.strip() else "FAIL"))
    else:
        sec.items.append(Item("twine check PASS", False, "无产物可校验"))

    # 产物 4：sdist/wheel 成员卫生（发布包不得含参考区/内部文档/运行数据/密钥配置）
    leaks = dist_member_leaks(artifacts)
    sec.items.append(Item(
        "sdist/wheel 成员卫生（无参考区/内部文档/runs/密钥配置）", not leaks,
        "0 泄漏" if not leaks else f"{len(leaks)} 处：{leaks[:8]}"))
    sec.outputs.append("runs/release_staging/dist/（sdist+wheel，仅本地）")
    return sec


# 发布包禁入片段（与 pyproject [tool.hatch.build.targets.sdist].exclude 对应并更严）
DIST_FORBIDDEN_FRAGMENTS = (
    "/.hypothesis/", "/.zcode/", "/ads_reference/", "/pyaedt_reference/", "/runs/",
    "/.venv/", "chat_settings", "/_tmp_", "/ledger.md", "/todo.md", "/项目规约.md",
    "/AGENT-HANDOFF", "/uv.lock", "/skills/",
)


def dist_member_leaks(artifacts: list[Path]) -> list[str]:
    """列出 sdist(tar.gz)/wheel(zip) 中命中禁入片段的成员名（确定性排序）。"""
    import tarfile
    import zipfile

    leaks: list[str] = []
    for art in artifacts:
        names: list[str] = []
        if art.suffix == ".gz":
            with tarfile.open(art) as t:
                names = t.getnames()
        elif art.suffix == ".whl":
            with zipfile.ZipFile(art) as z:
                names = z.namelist()
        for n in names:
            probe = "/" + n
            if any(frag in probe for frag in DIST_FORBIDDEN_FRAGMENTS):
                leaks.append(f"{art.name}:{n}")
    return sorted(leaks)


def sec_sdist_hygiene(staging: Path) -> Section:
    """sdist 成员卫生单节（0dd⑤：接质量门/CI quality job）。

    与 F4 --build 全量的差别：只构建 sdist（``--sdist``，不产 wheel、
    不做 twine check、不导 MCP manifest），成员判定复用同一
    DIST_FORBIDDEN_FRAGMENTS（与 F4 产物 4 同源，不复制漂移）。
    本地 sdist 构建约 1 分钟量级，适合逐 PR 质量门。
    """
    sec = Section("sdist_hygiene", "sdist 成员卫生")
    has_build = importlib.util.find_spec("build") is not None
    has_hatchling = importlib.util.find_spec("hatchling") is not None
    missing = [n for n, ok in (("build", has_build), ("hatchling", has_hatchling)) if not ok]
    sec.items.append(Item(
        "build/hatchling 本地后端可用", not missing,
        "就绪（--no-isolation，不拉网）" if not missing
        else "缺 " + ", ".join(missing) + "——pip install build hatchling"))
    if missing:
        return sec

    dist_dir = _reset_dir(staging / "dist")
    ok_build, msg_build = _run_offline(
        [sys.executable, "-m", "build", "--sdist", "--no-isolation",
         "--outdir", str(dist_dir)],
        timeout_s=900)
    artifacts = sorted(dist_dir.glob("*.tar.gz"))
    sec.items.append(Item(
        "python -m build --sdist 产 sdist", ok_build and bool(artifacts),
        (msg_build.strip().splitlines()[-1] if not ok_build and msg_build.strip()
         else f"{len(artifacts)} 个 sdist")))
    if not artifacts:
        return sec

    leaks = dist_member_leaks(artifacts)
    sec.items.append(Item(
        "sdist 成员卫生（无参考区/内部文档/runs/密钥配置）", not leaks,
        "0 泄漏" if not leaks else f"{len(leaks)} 处：{leaks[:8]}"))
    sec.outputs.append(f"{_rel(dist_dir)}/（sdist，仅本地）")
    return sec


def run_sdist_hygiene(staging: Path) -> int:
    """--sdist-hygiene 单节入口：只跑成员卫生节并给退出码（质量门消费）。"""
    sec = sec_sdist_hygiene(staging)
    ok = sec.status == "PASS"
    print("== rfauto sdist 成员卫生（质量门单节；红线：仅本地构建，绝不发布） ==")
    for it in sec.items:
        print(f"    [{'ok' if it.ok else 'NG'}] {it.name}: {it.detail}")
    for o in sec.outputs:
        print(f"    [产物] {o}")
    print("结论：" + ("PASS——sdist 成员卫生达标" if ok
                    else "FAIL——不凑绿（#122），按上表明细修复后重跑"))
    return 0 if ok else 1


def sec_f6_leaderboard(staging: Path, build: bool) -> Section:
    """F6 公开榜单：离线静态 HTML+JSON，数字 100% 出自 runs/ 文件。"""
    sec = Section("f6_leaderboard", "F6 公开榜单")
    bench_files = collect_benchmark_sources()
    sec.items.append(Item(
        "引擎基准 JSON 数据源", len(bench_files) >= 1,
        f"{len(bench_files)} 个：{[p.name for p in bench_files]}"))
    mesh_ok = MESH_CONV_JSON.exists()
    sec.items.append(Item("网格收敛 JSON 数据源", mesh_ok,
                          _rel(MESH_CONV_JSON) if mesh_ok else "缺 mline_mesh_convergence.json"))
    sec.items.append(Item("WP3.9 工厂 summary 数据源", WP39_SUMMARY.exists(),
                          _rel(WP39_SUMMARY) if WP39_SUMMARY.exists()
                          else "缺 runs/wp39_mvp/summary.json"))
    if not build:
        return sec

    payload = build_leaderboard_payload()
    out_dir = _reset_dir(staging / "leaderboard")
    json_path = out_dir / "leaderboard.json"
    write_json_deterministic(json_path, payload)
    html_text = render_leaderboard_html(payload)
    (out_dir / "index.html").write_text(html_text, encoding="utf-8")
    sec.outputs.extend(["runs/release_staging/leaderboard/leaderboard.json",
                        "runs/release_staging/leaderboard/index.html"])

    # 确定性自检：同输入重跑逐字节一致（无时间戳设计）
    payload2 = build_leaderboard_payload()
    same = (json.dumps(payload, ensure_ascii=False, sort_keys=True)
            == json.dumps(payload2, ensure_ascii=False, sort_keys=True))
    sec.items.append(Item("榜单生成确定性（同输入逐字节一致）", same,
                          "leaderboard.json 重跑一致" if same else "两次生成不一致"))
    return sec


def render_leaderboard_html(payload: dict[str, Any]) -> str:
    """静态 HTML（内联样式、无外链、离线可开）；数值 str() 原值渲染。"""
    e = html.escape

    def table(headers: list[str], rows: list[list[Any]]) -> str:
        head = "".join(f"<th>{e(h)}</th>" for h in headers)
        body = "".join(
            "<tr>" + "".join(f"<td>{e('' if v is None else str(v))}</td>" for v in row) + "</tr>"
            for row in rows)
        return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"

    def kv(d: Any) -> str:
        return json.dumps(d, ensure_ascii=False, sort_keys=True) if isinstance(d, dict) else str(d)

    anchor_rows = [[a.get("anchor"), a.get("gate_version"), a.get("captured_at"), a.get("verdict"),
                    kv(a.get("metrics")), kv(a.get("criteria")), a.get("source")]
                   for a in payload.get("anchors") or []]
    mesh_rows = [[r.get("mesh_mm"), r.get("ok"), r.get("eps_eff"), r.get("delta_vs_hj_pct"),
                  r.get("delta_vs_gold_pct"), r.get("s11_max_db"), r.get("wall_s")]
                 for r in payload.get("mesh_convergence") or []]
    wp = payload.get("wp39_factory") or {}
    wp_rows = [[p.get("problem"), p.get("verdict"), p.get("budget_ok"), p.get("wallclock_ok"),
                p.get("cost_ok"), p.get("wallclock_ratio"), p.get("degradation_pct"),
                p.get("n_evals_candidate"), p.get("n_evals_baseline")]
               for p in wp.get("problems") or []]
    src_rows = [[s.get("path"), s.get("sha256")] for s in payload.get("sources") or []]

    parts = [
        "<!DOCTYPE html><html lang=\"zh\"><head><meta charset=\"utf-8\">",
        "<title>rfauto 公开基准榜单（静态离线页）</title>",
        "<style>body{font-family:sans-serif;margin:2rem;max-width:72rem}",
        "table{border-collapse:collapse;margin:1rem 0;width:100%}",
        "th,td{border:1px solid #bbb;padding:4px 8px;text-align:left;font-size:0.9rem}",
        "th{background:#f0f0f0}h1{font-size:1.4rem}h2{font-size:1.1rem;margin-top:2rem}",
        ".note{color:#555;font-size:0.85rem}</style></head><body>",
        "<h1>rfauto 公开基准榜单（静态离线页）</h1>",
        f"<p class=\"note\">{e(str(payload.get('note')))}</p>",
        "<p class=\"note\">本页由 scripts/release_readiness.py --build 离线生成；"
        "无托管、无上传。发布由用户手动执行（README「发布就绪与手动发布步骤」）。</p>",
        "<h2>1. 引擎基准锚（runs/benchmark/*_engine_benchmark.json）</h2>",
        table(["anchor", "gate_version", "captured_at", "verdict",
               "metrics（原值）", "criteria（原值）", "source"], anchor_rows),
        "<h2>2. mline 网格收敛（runs/benchmark/mline_mesh_convergence.json）</h2>",
        table(["mesh_mm", "ok", "eps_eff", "delta_vs_hj_pct", "delta_vs_gold_pct", "s11_max_db", "wall_s"], mesh_rows),
        "<h2>3. WP3.9 模板工厂基准（runs/wp39_mvp/summary.json）</h2>",
        table(["problem", "verdict", "budget_ok", "wallclock_ok", "cost_ok",
               "wallclock_ratio", "degradation_pct", "n_evals_candidate", "n_evals_baseline"], wp_rows),
        "<h2>数据来源（文件 + SHA256）</h2>",
        table(["source", "sha256"], src_rows),
        "</body></html>",
    ]
    return "\n".join(parts)


def _iter_template_metas() -> list[tuple[str, dict[str, Any]]]:
    import yaml

    out = []
    for meta_path in sorted(TEMPLATES_DIR.glob("*/meta.yaml")):
        data = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
        out.append((meta_path.parent.name, data))
    return out


def sec_h1_pdk(staging: Path, build: bool) -> Section:
    """H1 开源 PDK 包：模板库+recipes+参考摘录+LICENSE/CITATION+哈希清单。"""
    sec = Section("h1_pdk", "H1 开源 PDK 包")
    metas = []
    parse_errors: list[str] = []
    for name, data in _iter_template_metas():
        metas.append((name, data))
        if not isinstance(data, dict):
            parse_errors.append(name)
    sec.items.append(Item(
        "模板库 meta.yaml 可解析（≥30）", len(metas) >= 30 and not parse_errors,
        f"{len(metas)} 个模板" + (f"；解析失败：{parse_errors}" if parse_errors else "")))
    recipes = sorted(RECIPES_DIR.glob("*.yaml"))
    sec.items.append(Item("recipes 配方存在", len(recipes) >= 1, f"{len(recipes)} 个 yaml"))
    sec.items.append(Item(
        "参考文档与 LICENSE 存在", RF_REF_DOC.exists() and LICENSE_FILE.exists(),
        f"{_rel(RF_REF_DOC)} / LICENSE"))
    cit_ok = False
    cit_detail = "缺 CITATION.cff"
    if CITATION_FILE.exists():
        import yaml

        cit = yaml.safe_load(CITATION_FILE.read_text(encoding="utf-8")) or {}
        proj = load_pyproject_project()
        cit_ok = (str(cit.get("cff-version")) == "1.2.0"
                  and str(cit.get("version")) == str(proj.get("version")))
        cit_detail = (f"cff {cit.get('cff-version')} version={cit.get('version')} "
                      f"(pyproject {proj.get('version')})")
    sec.items.append(Item("CITATION.cff 有效且与 pyproject 版本同步", cit_ok, cit_detail))
    if not build:
        return sec

    pdk = _reset_dir(staging / "pdk")
    # 素材复制（全部只读打包，零内容改写）
    for name, _meta in metas:
        src = TEMPLATES_DIR / name / "meta.yaml"
        dst = pdk / "templates" / name / "meta.yaml"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
    rec_dir = pdk / "recipes"
    rec_dir.mkdir(parents=True, exist_ok=True)
    for r in recipes:
        shutil.copyfile(r, rec_dir / r.name)
    (pdk / "references").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(RF_REF_DOC, pdk / "references" / "rf_template_references.md")
    shutil.copyfile(LICENSE_FILE, pdk / "LICENSE")
    shutil.copyfile(CITATION_FILE, pdk / "CITATION.cff")

    # PDK README（模板表从 meta.yaml 读，零手写数字）
    rows = []
    for name, data in metas:
        sub = data.get("substrate") or {}
        rows.append("| {} | {} | {} | {} | {} |".format(
            name, data.get("template", name), data.get("f0_ghz", ""),
            sub.get("er", ""), sub.get("h_mm", "")))
    readme = "\n".join([
        "# rfauto RF PDK（开源模板库包，离线打包产物）",
        "",
        "由 `scripts/release_readiness.py --build` 从仓库只读打包；数字全部来自",
        "`docs/templates/*/meta.yaml` 原值，打包器零改写。**本包不出仓库**——发布",
        "由用户手动执行（仓库 README「发布就绪与手动发布步骤」一节）。",
        "",
        "## 结构",
        "",
        f"- `templates/<name>/meta.yaml`：模板元数据（{len(metas)} 个）",
        f"- `recipes/*.yaml`：配方（{len(recipes)} 个）",
        "- `references/rf_template_references.md`：官方例口径全文（Ansys/openEMS",
        "  官方例参数、端口/网格铁律、验收基准 dB 值；打包时逐字节复制）",
        "- `LICENSE`（MIT）、`CITATION.cff`、`SHA256SUMS.txt`（本清单）",
        "",
        "## 模板清单",
        "",
        "| 目录 | template | f0_ghz | er | h_mm |",
        "|---|---|---|---|---|",
        *rows,
        "",
        "线宽/几何一律以 rfauto 综合内核（skrf HJ）按基底精算，禁止直接沿用",
        "任何来源的毫米数（仓库 项目规约.md 规则 1c）。",
        "",
    ])
    (pdk / "README.md").write_text(readme, encoding="utf-8")

    # 哈希清单（README 之后生成，自含 SHA256SUMS）
    write_sha256sums(pdk)
    n_files = len([p for p in pdk.rglob("*") if p.is_file()])
    sec.outputs.append("runs/release_staging/pdk/（含 SHA256SUMS.txt）")

    # 包内容脱敏+编码双检必须 PASS
    sens = scan_dir_sensitive(pdk)
    enc = check_dir_encoding(pdk)
    sec.items.append(Item(
        "PDK 包脱敏扫描 PASS", not sens,
        "0 violation" if not sens else f"{len(sens)} 处：{sens[:5]}"))
    sec.items.append(Item(
        "PDK 包编码检查 PASS（UTF-8 无 BOM）", not enc,
        "0 问题" if not enc else f"{len(enc)} 处：{enc[:5]}"))
    sec.items.append(Item(
        "PDK 包文件数与哈希清单", n_files >= len(metas) + len(recipes) + 4,
        f"{n_files} 个文件（模板 {len(metas)} + 配方 {len(recipes)} + 参考/许可/引用/清单）"))
    return sec


def sec_h3_paper(staging: Path, build: bool) -> Section:
    """H3 方法学发表材料：论文骨架 + 图表脚本产物（不写正文、不投稿）。"""
    sec = Section("h3_paper", "H3 方法学发表材料")
    sec.items.append(Item(
        "论文骨架 docs/paper/outline.md", PAPER_OUTLINE.exists(),
        _rel(PAPER_OUTLINE) if PAPER_OUTLINE.exists() else "缺 outline.md"))
    sec.items.append(Item(
        "图表脚本 scripts/paper_figures.py", PAPER_FIGURES_SCRIPT.exists(),
        _rel(PAPER_FIGURES_SCRIPT) if PAPER_FIGURES_SCRIPT.exists()
        else "缺 paper_figures.py"))
    bench_files = collect_benchmark_sources()
    sec.items.append(Item(
        "图表数据源存在", len(bench_files) >= 1 and MESH_CONV_JSON.exists() and WP39_SUMMARY.exists(),
        f"基准 {len(bench_files)} + 收敛 + wp39"))
    if not build:
        return sec

    figs = _reset_dir(staging / "paper" / "figs")
    ok, msg = _run_offline(
        [sys.executable, str(PAPER_FIGURES_SCRIPT), "--outdir", str(figs)], timeout_s=300)
    produced = sorted(p.name for p in figs.glob("*")) if figs.exists() else []
    sec.items.append(Item(
        "出图（paper_figures.py，离线 Agg）", ok and len(produced) >= 1,
        f"{len(produced)} 个产物" if ok else msg.strip().splitlines()[-1] if msg.strip() else "无产物"))
    sec.outputs.append("runs/release_staging/paper/figs/")
    return sec


def sec_dataset(staging: Path, build: bool) -> Section:
    """6.6 基准集导出包：只导公开集；私有集/GT 逐点标注绝不入包。"""
    sec = Section("dataset", "6.6 基准集导出包")
    import yaml

    try:
        from rfauto.service.dataset_insights import export_hf_dataset
    except ImportError as exc:
        sec.items.append(Item("export-hf 服务面可导入", False, str(exc)))
        return sec
    sec.items.append(Item("export-hf 服务面可导入", True, "rfauto.service.dataset_insights.export_hf_dataset"))

    registry_manifests: list[dict[str, Any]] = []
    for mp in sorted(DATASET_REGISTRY.glob("*/dataset_manifest.yaml")):
        data = yaml.safe_load(mp.read_text(encoding="utf-8")) or {}
        data["__dir"] = mp.parent.name
        registry_manifests.append(data)
    publics = [m for m in registry_manifests if m.get("visibility") == "public"]
    privates = [m for m in registry_manifests if m.get("visibility") != "public"]
    sec.items.append(Item(
        "数据集注册表可读", len(registry_manifests) >= 1,
        f"{len(registry_manifests)} 个数据集（public {len(publics)} / private {len(privates)}）"))

    # 运行时拒绝验证：private 集不带 allow_private 导出必须被拒（防误发布，源码级口径）
    rejects: list[str] = []
    for m in privates:
        r = export_hf_dataset(str(m.get("name") or m["__dir"]), out_dir=DATASET_REGISTRY,
                             allow_private=False)
        if not r.get("ok"):
            rejects.append(str(m.get("name") or m["__dir"]))
    sec.items.append(Item(
        "私有集默认拒绝导出（运行时验证）", len(rejects) == len(privates),
        f"{len(rejects)}/{len(privates)} 个被正确拒绝：{rejects}"))
    sec.notes.append(
        "公开集为空时本节判定仍可为 PASS（判的是导出通道与防污染机制；"
        "内容公开与否是用户决策）——见 EXPORT_STATUS.json 如实记录。")

    if not build:
        return sec

    ds_dir = _reset_dir(staging / "dataset")
    exported: list[str] = []
    for m in publics:
        name = str(m.get("name") or m["__dir"])
        r = export_hf_dataset(name, out_dir=DATASET_REGISTRY, license="")
        if not r.get("ok"):
            sec.items.append(Item(f"导出公开集 {name}", False,
                                  "; ".join(str(x) for x in (r.get("errors") or ["未知错误"]))))
            continue
        src_hf = DATASET_REGISTRY / m["__dir"] / "hf"
        dst = ds_dir / name
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src_hf, dst)
        write_sha256sums(dst)
        _write_dataset_datasheet(ds_dir, m, dst)
        exported.append(name)

    status = {
        "kind": "rfauto_dataset_export_status",
        "n_registry": len(registry_manifests),
        "n_public": len(publics),
        "n_private": len(privates),
        "exported": sorted(exported),
        "note": "私有集/GT 逐点标注绝不入包（export_hf_dataset 默认拒绝 + 本脚本不传 allow_private）。"
                "公开集为空属内容决策待用户执行：rfauto datasets visibility <name> public 后重跑 --build。",
    }
    write_json_deterministic(ds_dir / "EXPORT_STATUS.json", status)
    if not exported:
        _write_dataset_datasheet(ds_dir, None, None)
    sec.outputs.append("runs/release_staging/dataset/")
    enc = check_dir_encoding(ds_dir)
    sec.items.append(Item("数据集包编码检查", not enc,
                          "0 问题" if not enc else f"{len(enc)} 处：{enc[:5]}"))
    return sec


def _write_dataset_datasheet(ds_dir: Path, manifest: dict[str, Any] | None, exported_to: Path | None) -> Path:
    """datasheet.md：字段/来源/许可/双集防污染说明（全部取自 manifest，零新数字）。"""
    if manifest is None:
        text = "\n".join([
            "# rfauto 基准数据集 datasheet（占位说明）",
            "",
            "**当前注册表没有 public 数据集，本包未包含任何数据行**（防误发布：",
            "`export_hf_dataset` 对 private 数据集默认拒绝导出，本脚本亦不使用",
            "`allow_private` 旁路）。",
            "",
            "用户将某数据集公开后重跑即可入包：",
            "",
            "    rfauto datasets visibility <name> public",
            "    python scripts/release_readiness.py --build",
            "",
            "双集防污染说明（对将来入包的数据集同样生效）：",
            "",
            "- 只允许 `visibility: public` 的数据集进入本包；private 集默认拒绝导出；",
            "- GT 逐点私有标注不入包：数据行 parquet 无逐点 ground truth 列，",
            "  manifest 中的 `ground_truth` 块仅为聚合统计（行数/阈值/解锁状态），",
            "  随 HF 数据卡 `rfauto:` 嵌套键如实导出；",
            "- `source_runs` 逐 run 记录来源（run_id + n_points），provenance 可溯。",
            "",
        ])
        path = ds_dir / "datasheet.md"
        path.write_text(text, encoding="utf-8")
        return path

    name = manifest.get("name")
    columns = manifest.get("columns") or []
    source_runs = manifest.get("source_runs") or []
    src_lines = [f"- `{r.get('run_id')}`（{r.get('n_points')} 点）" for r in source_runs]
    col_lines = [f"- `{c}`" for c in columns]
    text = "\n".join([
        f"# rfauto 公开基准数据集 datasheet：{name}",
        "",
        f"- schema_version：{manifest.get('schema_version')}",
        f"- 可见性：{manifest.get('visibility')}（公开集，export_hf_dataset 放行）",
        f"- 行数/点数：{manifest.get('n_rows')} 行 / {manifest.get('n_points')} 点",
        "",
        "## 字段（列即数据行 schema，原值）",
        "",
        *col_lines,
        "",
        "## 来源 runs（provenance 可溯）",
        "",
        *src_lines,
        "",
        "## 许可",
        "",
        "未在导出时指定 license（本脚本不替用户决定）。用户发布前必须显式",
        "选择并写入 HF 数据卡（推荐口径由用户定，如 CC-BY-4.0 / MIT）。",
        "",
        "## 双集防污染说明",
        "",
        "- 只允许 `visibility: public` 的数据集进入本包；private 集默认拒绝导出；",
        "- GT 逐点私有标注不入包（见注册表 `ground_truth.policy`）；",
        "- 校验和见本目录 `SHA256SUMS.txt`。",
        "",
    ])
    path = exported_to / "datasheet.md" if exported_to else ds_dir / "datasheet.md"
    path.write_text(text, encoding="utf-8")
    return path


def sec_ecosystem(staging: Path, build: bool) -> Section:
    """5.6 生态抽取（最小口径）：可复用模块清单+抽取方案+依赖边界 AST 证据。"""
    sec = Section("ecosystem", "5.6 生态抽取")
    sec.items.append(Item(
        "抽取方案 docs/release/ecosystem_extraction.md", ECOSYSTEM_DOC.exists(),
        _rel(ECOSYSTEM_DOC) if ECOSYSTEM_DOC.exists()
        else "缺 docs/release/ecosystem_extraction.md"))

    boundaries: dict[str, Any] = {}
    missing: list[str] = []
    for rel in ECOSYSTEM_CANDIDATES:
        path = REPO_ROOT / rel
        if not path.exists():
            missing.append(rel)
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        tops: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    tops.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                tops.add(node.module.split(".")[0])
        stdlib = sorted(t for t in tops if t in getattr(sys, "stdlib_module_names", frozenset()))
        rfauto = sorted(t for t in tops if t == "rfauto")
        third = sorted(t for t in tops if t not in stdlib and t != "rfauto")
        boundaries[rel] = {"third_party": third, "stdlib": stdlib, "rfauto": rfauto}
    sec.items.append(Item(
        "候选模块存在且可 AST 解析", not missing and bool(boundaries),
        f"{len(boundaries)} 个模块" + (f"；缺：{missing}" if missing else "")))
    if not build:
        return sec

    eco = _reset_dir(staging / "ecosystem")
    payload = {
        "kind": "rfauto_ecosystem_import_boundaries",
        "method": "ast.walk 顶层 import 收集（含函数内），stdlib 判据 sys.stdlib_module_names",
        "modules": boundaries,
        "note": "依赖边界实测证据（非断言）；抽取方案见 docs/release/ecosystem_extraction.md。",
    }
    write_json_deterministic(eco / "import_boundaries.json", payload)
    sec.outputs.append("runs/release_staging/ecosystem/import_boundaries.json")
    return sec


# ─── H6 SBOM 清单 ────────────────────────────────────────────────────────────

def _pep508_name(requirement: str) -> str:
    """PEP 508 需求串 → 规范化包名（PEP 503：小写、连续 ``-_.`` 折叠为 ``-``）。"""
    import re

    raw = re.split(r"[<>=!~;\[\s(]", requirement.strip(), maxsplit=1)[0]
    return re.sub(r"[-_.]+", "-", raw).strip().lower()


def build_sbom_payload() -> dict[str, Any]:
    """生成 CycloneDX 1.5 兼容 JSON 文档（H6；零新依赖、确定性、无时间戳）。

    组件口径：``metadata.component`` = 项目自身（type=application，与
    pyproject 同名同版）；``components`` = pyproject ``[project].dependencies``
    直接依赖逐条（type=library，版本号取自当前运行环境 importlib.metadata——
    环境缺装时该组件省略 version 字段并计入 unresolved，**绝不编造版本号**）。
    计数（声明/已解析）经 ``metadata.properties`` 携带（CycloneDX 合法扩展位，
    不发明顶层键，保持文档对标准校验器兼容）。确定性：serialNumber=
    ``uuid5(name:version)``（名字空间派生，非随机），无 timestamp——同仓同
    环境重跑逐字节一致（--build 双生成自检）。
    """
    import uuid
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as md_version

    proj = load_pyproject_project()
    name = str(proj.get("name") or "rfauto")
    version = str(proj.get("version") or "")
    deps = [str(d) for d in (proj.get("dependencies") or [])]

    self_ref = f"pkg:pypi/{name}@{version}" if version else f"pkg:pypi/{name}"
    components: list[dict[str, Any]] = []
    for dep in sorted(_pep508_name(d) for d in deps):
        try:
            dep_version = md_version(dep)
        except PackageNotFoundError:  # 环境缺装：组件保留、version 省略（不编造）
            purl = f"pkg:pypi/{dep}"
            components.append(
                {"type": "library", "name": dep, "purl": purl, "bom-ref": purl})
            continue
        purl = f"pkg:pypi/{dep}@{dep_version}"
        components.append({"type": "library", "name": dep, "version": dep_version,
                           "purl": purl, "bom-ref": purl})

    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": "urn:uuid:" + str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"rfauto-sbom:{name}:{version}")),
        "version": 1,
        "metadata": {
            "component": {"type": "application", "name": name, "version": version,
                          "purl": self_ref, "bom-ref": self_ref},
            "tools": [{"vendor": "rfauto",
                       "name": "scripts/release_readiness.py#build_sbom_payload",
                       "version": version}],
            "properties": [
                {"name": "rfauto:sbom:scope", "value": "project-self+direct-dependencies"},
                {"name": "rfauto:direct-dependencies-declared", "value": str(len(deps))},
                {"name": "rfauto:direct-dependencies-resolved",
                 "value": str(sum(1 for c in components if "version" in c))},
                {"name": "rfauto:sbom:deterministic",
                 "value": "no-timestamp; serialNumber=uuid5(name:version)"},
            ],
        },
        "components": components,
    }


def sec_h6_sbom(staging: Path, build: bool) -> Section:
    """H6 SBOM 清单：CycloneDX 1.5 兼容 JSON（零新依赖；--check 只断言可生成）。"""
    sec = Section("h6_sbom", "H6 SBOM 清单")
    proj = load_pyproject_project()
    name = str(proj.get("name") or "")
    deps = [str(d) for d in (proj.get("dependencies") or [])]
    sec.items.append(Item(
        "pyproject 直接依赖可枚举（≥1）", len(deps) >= 1,
        f"{len(deps)} 条 [project].dependencies"))
    try:
        payload = build_sbom_payload()
    except Exception as exc:
        sec.items.append(Item("SBOM 可生成且含项目自身与直接依赖计数", False,
                              f"生成失败：{exc}"))
        return sec

    meta_comp = payload.get("metadata", {}).get("component", {})
    props = {p["name"]: p["value"] for p in payload["metadata"]["properties"]}
    self_ok = (meta_comp.get("type") == "application"
               and meta_comp.get("name") == name
               and meta_comp.get("version") == str(proj.get("version")))
    sec.items.append(Item(
        "SBOM 含项目自身（metadata.component 与 pyproject 同名同版）", self_ok,
        f"component={meta_comp.get('name')}@{meta_comp.get('version')}"))

    declared = int(props["rfauto:direct-dependencies-declared"])
    resolved = int(props["rfauto:direct-dependencies-resolved"])
    counts_ok = (declared == len(deps)
                 and len(payload["components"]) == len(deps)
                 and 0 <= resolved <= declared)
    sec.items.append(Item(
        "SBOM 直接依赖计数与 pyproject 一致（组件逐条对应）", counts_ok,
        f"声明 {declared} / 已解析 {resolved} / 组件 {len(payload['components'])}"))
    missing = [c["name"] for c in payload["components"] if "version" not in c]
    sec.items.append(Item(
        "直接依赖在当前环境全部可解析（缺装如实 FAIL，不编造版本）",
        resolved == declared and not missing,
        "全部已解析" if not missing else f"缺装 {len(missing)} 个：{missing}"))

    if not build:
        return sec

    sbom_dir = _reset_dir(staging / "sbom")
    write_json_deterministic(sbom_dir / "rfauto.cdx.json", payload)
    sec.outputs.append("runs/release_staging/sbom/rfauto.cdx.json")
    # 确定性自检：同输入重生成逐字节一致（无时间戳设计，与 F6 榜单同口径）
    payload2 = build_sbom_payload()
    same = (json.dumps(payload, ensure_ascii=False, sort_keys=True)
            == json.dumps(payload2, ensure_ascii=False, sort_keys=True))
    sec.items.append(Item("SBOM 生成确定性（同输入逐字节一致）", same,
                          "rfauto.cdx.json 重跑一致" if same else "两次生成不一致"))
    return sec


# ─── 汇总入口 ───────────────────────────────────────────────────────────────

SECTIONS = [
    ("f4_mcp", "F4 MCP 发布包", sec_f4_mcp),
    ("f6_leaderboard", "F6 公开榜单", sec_f6_leaderboard),
    ("h1_pdk", "H1 开源 PDK 包", sec_h1_pdk),
    ("h3_paper", "H3 方法学发表材料", sec_h3_paper),
    ("dataset", "6.6 基准集导出包", sec_dataset),
    ("ecosystem", "5.6 生态抽取", sec_ecosystem),
    ("h6_sbom", "H6 SBOM 清单", sec_h6_sbom),
]


def run(mode_check: bool, mode_build: bool, staging: Path) -> int:
    report: dict[str, Any] = {
        "kind": "rfauto_release_readiness_report",
        "mode": ("check+" if mode_check else "") + ("build" if mode_build else ""),
        "redline": {
            "publish_channel": "none——无 publish 子命令；不 git push/tag、不 twine upload、"
                               "不 gh release、无任何对外网络上传",
            "network": "离线；子进程仅 python -m build --no-isolation（本地 hatchling）与 twine check",
            "outputs": "全部产物落 runs/release_staging/（gitignore 内），不出仓库",
        },
        "sections": [],
    }
    all_pass = True
    print("== rfauto 发布就绪度（七节；红线：可发布、绝不发布） ==")
    for key, title, fn in SECTIONS:
        sec = fn(staging, build=mode_build)
        ok = sec.status == "PASS"
        all_pass = all_pass and ok
        report["sections"].append({
            "key": key, "title": title, "status": sec.status,
            "items": [vars(i) for i in sec.items],
            "outputs": sec.outputs, "notes": sec.notes,
        })
        print(f"[{sec.status}] {title}")
        for it in sec.items:
            print(f"    [{'ok' if it.ok else 'NG'}] {it.name}: {it.detail}")
        for n in sec.notes:
            print(f"    [note] {n}")
        for o in sec.outputs:
            print(f"    [产物] {o}")
    report["all_pass"] = all_pass
    report_path = staging / "check_report.json"
    write_json_deterministic(report_path, report)
    print(f"报告：{_rel(report_path)}")
    print("结论：" + ("七节全 PASS（发布通道就绪；发布动作由用户手动执行）" if all_pass
                    else "存在 FAIL——不凑绿（#122），按上表明细修复后重跑"))
    return 0 if all_pass else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="rfauto 发布就绪度校验与本地产物构建（绝不发布）")
    parser.add_argument("--check", action="store_true", help="七节就绪度校验（任何 FAIL 则 exit 1）")
    parser.add_argument("--build", action="store_true", help="七节产物落 runs/release_staging/（不出仓库）")
    parser.add_argument("--sdist-hygiene", action="store_true",
                        help="单节：只构建 sdist 并做成员卫生扫描（质量门/CI quality job 接"
                             "入，0dd⑤；约 1 分钟，不拖七节全量）")
    parser.add_argument("--staging", default=str(DEFAULT_STAGING), help="产物目录（默认 runs/release_staging）")
    args = parser.parse_args(argv)
    if args.sdist_hygiene:
        return run_sdist_hygiene(Path(args.staging))
    if not args.check and not args.build:
        parser.print_help()
        return 2
    return run(args.check, args.build, Path(args.staging))


if __name__ == "__main__":
    sys.exit(main())
