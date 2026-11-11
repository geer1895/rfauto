"""B 组发布类"可发布、绝不发布"就绪脚本单测（scripts/release_readiness.py）。

口径（全部确定性、离线、chdir 无关——路径以 monkeypatch 模块常量注入 tmp）：
- 红线自证：无 publish 子命令（argparse 选项集白名单）、子进程命令常量不含
  upload/push/tag/release、源码不 import 任何 HTTP 客户端；socket.connect 阻断下
  check 节照常跑通（#139 钉通道）；
- 清单生成确定性（PDK SHA256SUMS/manifest、MCP manifest、榜单 payload 两次逐字节一致）；
- 私有集拒绝入包（运行时真调 export_hf_dataset，被拒零落盘）与公开集正路径入包；
- 脱敏扫描/编码检查接线（BLACKLIST/SKIP_SUFFIXES 同源加载）；
- sdist/wheel 成员卫生判定；build 步骤可 mock（命令行断言）；exit 语义。
"""

from __future__ import annotations

import ast
import io
import json
import socket
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest
import yaml

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import release_readiness as rr

SOURCE_PATH = SCRIPTS / "release_readiness.py"
SOURCE = SOURCE_PATH.read_text(encoding="utf-8")


# ─── 红线自证 ───────────────────────────────────────────────────────────────

def test_cli_has_only_check_and_build_no_publish():
    # 未知 --publish / publish 子命令必须被 argparse 拒绝；无参数=打印帮助（exit 2），非发布
    with pytest.raises(SystemExit):
        rr.main(["--publish"])
    with pytest.raises(SystemExit):
        rr.main(["publish"])
    assert rr.main([]) == 2


def test_subprocess_command_constants_contain_no_publish_verbs():
    """AST 收集所有 _run_offline([...])/subprocess.run([...]) 的字面量参数，禁入发布动词。"""
    tree = ast.parse(SOURCE)
    consts: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fname = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if fname not in {"_run_offline", "run"}:
            continue
        if node.args and isinstance(node.args[0], ast.List):
            for elt in node.args[0].elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    consts.add(elt.value)
    assert consts, "应至少收集到 build/twine check 的命令常量"
    forbidden = {"upload", "push", "tag", "release", "publish"}
    assert not (consts & forbidden), consts & forbidden
    assert {"-m", "build", "--no-isolation", "twine", "check"} <= consts


def test_source_imports_no_http_clients():
    tree = ast.parse(SOURCE)
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module.split(".")[0])
    assert not (mods & {"requests", "httpx", "urllib", "http", "socket", "aiohttp", "twine", "build"})


def test_check_sections_run_with_socket_blocked(monkeypatch, tmp_path):
    """#139：对外连接钉死（loopback 放行——Windows asyncio Proactor self-pipe 用
    127.0.0.1 socketpair，属事件循环机制非网络调用）；check 模式不依赖 runs/ 的
    节必须照常跑通。"""
    real_connect = socket.socket.connect

    def _no_external(self, address, *args, **kwargs):  # pragma: no cover - 分支单纯
        host = address[0] if isinstance(address, tuple) else address
        if host in ("127.0.0.1", "::1", "localhost"):
            return real_connect(self, address, *args, **kwargs)
        raise AssertionError(f"release_readiness 不得发起外部网络连接: {host!r}")

    monkeypatch.setattr(socket.socket, "connect", _no_external)
    for fn in (rr.sec_f4_mcp, rr.sec_h1_pdk, rr.sec_ecosystem):
        sec = fn(tmp_path, build=False)
        assert sec.items, fn.__name__
    # F4 check 模式不产 dist（无 build 子进程）
    assert not (tmp_path / "dist").exists()


def test_f4_console_script_item_is_real_check(tmp_path):
    """w1a-shell-front：F4 的 console script 判定从"如实注记"改为真检查——
    pyproject [project.scripts] rfauto-mcp = rfauto.mcp_server:main 且 main() 可调用。"""
    sec = rr.sec_f4_mcp(tmp_path, build=False)
    item = next(i for i in sec.items if "console script" in i.name)
    assert item.ok is True, item.detail
    assert "rfauto.mcp_server:main" in item.detail
    assert "main() 可调用" in item.detail


# ─── 汇总/exit 语义 ─────────────────────────────────────────────────────────

def _stub_section(key: str, ok: bool):
    def _fn(staging: Path, build: bool) -> rr.Section:
        sec = rr.Section(key, key)
        sec.items.append(rr.Item("stub", ok, "stub"))
        return sec

    return _fn


def test_run_exit_code_and_report(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(rr, "SECTIONS", [("a", "A", _stub_section("a", True)),
                                         ("b", "B", _stub_section("b", False))])
    assert rr.run(True, False, tmp_path) == 1
    report = json.loads((tmp_path / "check_report.json").read_text(encoding="utf-8"))
    assert report["all_pass"] is False
    assert "none" in report["redline"]["publish_channel"]
    assert [s["status"] for s in report["sections"]] == ["PASS", "FAIL"]
    out = capsys.readouterr().out
    assert "存在 FAIL" in out

    monkeypatch.setattr(rr, "SECTIONS", [("a", "A", _stub_section("a", True))])
    assert rr.run(True, True, tmp_path) == 0
    assert rr.run(False, True, tmp_path) == 0


# ─── 脱敏/编码接线 ──────────────────────────────────────────────────────────

def test_sensitive_scan_and_encoding_check_wiring(tmp_path):
    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "a.md").write_text("普通模板说明 er=3.66\n", encoding="utf-8")
    assert rr.scan_dir_sensitive(clean) == []
    assert rr.check_dir_encoding(clean) == []

    dirty = tmp_path / "dirty"
    dirty.mkdir()
    # 脏样本运行时拼接（拆词）：源码字面不得命中仓库级 scan_sensitive 行内正则
    # （CI quality job 扫全仓 .py；正则 `.` 行内贪婪，同一行出现即命中）
    leak_text = " ".join(["Key" + "sight", "confidential", "inter" + "nal", "note"]) + "\n"
    (dirty / "leak.md").write_text(leak_text, encoding="utf-8")
    (dirty / "bom.yaml").write_bytes(b"\xef\xbb\xbfkey: v\n")
    hits = rr.scan_dir_sensitive(dirty)
    assert hits and hits[0].startswith("leak.md:")
    enc = rr.check_dir_encoding(dirty)
    assert any("bom.yaml" in e and "BOM" in e for e in enc)


# ─── PDK 清单确定性 ─────────────────────────────────────────────────────────

@pytest.fixture
def pdk_fixture(monkeypatch, tmp_path):
    version = rr.load_pyproject_project()["version"]
    templates = tmp_path / "templates"
    for name, f0 in (("mline", 2.5), ("patch", 2.45)):
        d = templates / name
        d.mkdir(parents=True)
        (d / "meta.yaml").write_text(yaml.safe_dump({
            "template": name, "f0_ghz": f0, "n_ports": 2,
            "substrate": {"er": 3.66, "h_mm": 0.508}}, sort_keys=False), encoding="utf-8")
    recipes = tmp_path / "recipes"
    recipes.mkdir()
    (recipes / "demo.yaml").write_text("model: mline\n", encoding="utf-8")
    ref = tmp_path / "ref.md"
    ref.write_text("# ref\n", encoding="utf-8")
    lic = tmp_path / "LICENSE"
    lic.write_text("MIT\n", encoding="utf-8")
    cit = tmp_path / "CITATION.cff"
    cit.write_text(f"cff-version: 1.2.0\nversion: {version}\ntitle: x\n", encoding="utf-8")
    monkeypatch.setattr(rr, "TEMPLATES_DIR", templates)
    monkeypatch.setattr(rr, "RECIPES_DIR", recipes)
    monkeypatch.setattr(rr, "RF_REF_DOC", ref)
    monkeypatch.setattr(rr, "LICENSE_FILE", lic)
    monkeypatch.setattr(rr, "CITATION_FILE", cit)
    return tmp_path


def test_pdk_build_deterministic_and_clean(pdk_fixture, tmp_path):
    s1, s2 = tmp_path / "s1", tmp_path / "s2"
    sec1 = rr.sec_h1_pdk(s1, build=True)
    sec2 = rr.sec_h1_pdk(s2, build=True)
    # 2 模板 <30：模板数判定如实 FAIL，其余（脱敏/编码/清单）必须 PASS
    by_name = {i.name: i for i in sec1.items}
    assert by_name["PDK 包脱敏扫描 PASS"].ok
    assert by_name["PDK 包编码检查 PASS（UTF-8 无 BOM）"].ok
    assert by_name["CITATION.cff 有效且与 pyproject 版本同步"].ok
    assert not by_name["模板库 meta.yaml 可解析（≥30）"].ok
    sums1 = (s1 / "pdk" / "SHA256SUMS.txt").read_text(encoding="utf-8")
    sums2 = (s2 / "pdk" / "SHA256SUMS.txt").read_text(encoding="utf-8")
    assert sums1 == sums2 and "templates/mline/meta.yaml" in sums1
    readme = (s1 / "pdk" / "README.md").read_text(encoding="utf-8")
    assert "| mline | mline | 2.5 | 3.66 | 0.508 |" in readme
    assert (s1 / "pdk" / "references" / "rf_template_references.md").exists()
    del sec2


# ─── 数据集：私有拒绝 / 公开入包 ────────────────────────────────────────────

def _write_manifest(reg: Path, name: str, visibility: str, **extra):
    d = reg / name
    d.mkdir(parents=True, exist_ok=True)
    manifest = {"schema_version": "2.0", "name": name, "visibility": visibility,
                "format": "parquet", "columns": ["run_id", "cost"],
                "source_runs": [{"run_id": "r1", "n_points": 2}],
                "n_rows": 2, "n_points": 2, **extra}
    (d / "dataset_manifest.yaml").write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return d


def test_private_dataset_is_rejected_and_nothing_exported(monkeypatch, tmp_path):
    reg = tmp_path / "registry"
    _write_manifest(reg, "secret_campaign", "private")
    monkeypatch.setattr(rr, "DATASET_REGISTRY", reg)
    staging = tmp_path / "staging"
    sec = rr.sec_dataset(staging, build=True)
    by_name = {i.name: i for i in sec.items}
    assert by_name["私有集默认拒绝导出（运行时验证）"].ok
    assert "secret_campaign" in by_name["私有集默认拒绝导出（运行时验证）"].detail
    status = json.loads((staging / "dataset" / "EXPORT_STATUS.json").read_text(encoding="utf-8"))
    assert status["n_private"] == 1 and status["n_public"] == 0 and status["exported"] == []
    assert not list((staging / "dataset").rglob("*.parquet"))
    assert not (reg / "secret_campaign" / "hf").exists()  # 被拒即零落盘
    assert (staging / "dataset" / "datasheet.md").exists()
    # 脚本源码不得出现 allow_private=True 旁路（私有集绝不入包的静态自证）
    assert "allow_private=True" not in SOURCE


def test_public_dataset_exported_with_checksums(monkeypatch, tmp_path):
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    reg = tmp_path / "registry"
    d = _write_manifest(reg, "open_bench", "public")
    pq.write_table(pa.table({"run_id": ["r1", "r1"], "cost": [0.5, 0.25]}), d / "points.parquet")
    monkeypatch.setattr(rr, "DATASET_REGISTRY", reg)
    staging = tmp_path / "staging"
    sec = rr.sec_dataset(staging, build=True)
    assert sec.status == "PASS", [vars(i) for i in sec.items if not i.ok]
    out = staging / "dataset" / "open_bench"
    assert (out / "data" / "train-00000-of-00001.parquet").exists()
    assert (out / "README.md").exists()
    sums = (out / "SHA256SUMS.txt").read_text(encoding="utf-8")
    assert "data/train-00000-of-00001.parquet" in sums
    sheet = (out / "datasheet.md").read_text(encoding="utf-8")
    assert "open_bench" in sheet and "`run_id`" in sheet and "private 集默认拒绝导出" in sheet
    status = json.loads((staging / "dataset" / "EXPORT_STATUS.json").read_text(encoding="utf-8"))
    assert status["exported"] == ["open_bench"]


# ─── 榜单 payload：原值搬运 + 确定性 ─────────────────────────────────────────

def test_leaderboard_payload_verbatim_and_deterministic(monkeypatch, tmp_path):
    bench = tmp_path / "benchmark"
    bench.mkdir()
    (bench / "zeta_engine_benchmark.json").write_text(json.dumps({
        "anchor": "zeta", "gate_version": "20260915", "captured_at": "2026-09-15",
        "verdict": "PASS", "metrics": {"delta_eps_pct": 0.961, "s11_db_band_max": -12.77},
        "criteria": {"delta_eps_pct_abs_le": 2.0}}), encoding="utf-8")
    (bench / "alpha_engine_benchmark.json").write_text(json.dumps({
        "anchor": "alpha", "verdict": "FAIL", "metrics": {"delta_eps2_pct": -1.04}, "criteria": {}}),
        encoding="utf-8")
    mesh = bench / "mline_mesh_convergence.json"
    mesh.write_text(json.dumps({"entries": [
        {"mesh_mm": 0.4, "ok": True, "eps_eff": 2.88281, "delta_vs_hj_pct": 1.058},
        {"mesh_mm": 0.0, "ok": True, "eps_eff": 2.91836, "delta_vs_hj_pct": 2.304}]}), encoding="utf-8")
    wp = tmp_path / "summary.json"
    wp.write_text(json.dumps({"schema": "wp39_mvp_summary_v1", "problems": {
        "mline": {"problem": "mline", "verdict": "FAIL", "wallclock_ratio": 1.2482}}}), encoding="utf-8")
    monkeypatch.setattr(rr, "BENCHMARK_DIR", bench)
    monkeypatch.setattr(rr, "MESH_CONV_JSON", mesh)
    monkeypatch.setattr(rr, "WP39_SUMMARY", wp)
    monkeypatch.setattr(rr, "REPO_ROOT", tmp_path)

    p1 = rr.build_leaderboard_payload()
    p2 = rr.build_leaderboard_payload()
    assert p1 == p2
    assert [a["anchor"] for a in p1["anchors"]] == ["alpha", "zeta"]  # 按名排序
    zeta = p1["anchors"][1]
    assert zeta["metrics"] == {"delta_eps_pct": 0.961, "s11_db_band_max": -12.77}  # 原值整块
    assert zeta["criteria"] == {"delta_eps_pct_abs_le": 2.0}
    assert [r["mesh_mm"] for r in p1["mesh_convergence"]] == [0.0, 0.4]
    assert p1["wp39_factory"]["problems"][0]["wallclock_ratio"] == 1.2482
    assert len(p1["sources"]) == 4 and all(len(s["sha256"]) == 64 for s in p1["sources"])

    html_text = rr.render_leaderboard_html(p1)
    assert "0.961" in html_text and "-1.04" in html_text and "1.2482" in html_text
    assert "<script" not in html_text and "http" not in html_text  # 静态、无外链
    sec = rr.sec_f6_leaderboard(tmp_path / "staging", build=True)
    assert sec.status == "PASS"
    assert (tmp_path / "staging" / "leaderboard" / "index.html").exists()


# ─── sdist/wheel 成员卫生 ────────────────────────────────────────────────────

def test_dist_member_leaks_detects_reference_dirs(tmp_path):
    sdist = tmp_path / "rfauto-0.0.0.tar.gz"
    with tarfile.open(sdist, "w:gz") as t:
        for name in ("rfauto-0.0.0/src/rfauto/a.py", "rfauto-0.0.0/ads_reference/doc.md",
                     "rfauto-0.0.0/.hypothesis/x", "rfauto-0.0.0/_tmp_probe.py"):
            data = b"x"
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    wheel = tmp_path / "rfauto-0.0.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as z:
        z.writestr("rfauto/a.py", "x")
        z.writestr("rfauto-0.0.0.dist-info/METADATA", "x")
    leaks = rr.dist_member_leaks([sdist, wheel])
    assert len(leaks) == 3
    assert all(x.startswith("rfauto-0.0.0.tar.gz:") for x in leaks)
    assert any("ads_reference" in x for x in leaks)
    assert any(".hypothesis" in x for x in leaks)
    assert any("_tmp_probe.py" in x for x in leaks)


# ─── --sdist-hygiene 单节质量门入口（0dd⑤：接 CI quality job） ────────────────

def _make_sdist(out_dir: Path, member_names: list[str]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    sdist = out_dir / "rfauto-0.0.0.tar.gz"
    with tarfile.open(sdist, "w:gz") as t:
        for name in member_names:
            info = tarfile.TarInfo(f"rfauto-0.0.0/{name}")
            info.size = 1
            t.addfile(info, io.BytesIO(b"x"))


def test_sdist_hygiene_gate_pass_and_fail(monkeypatch, tmp_path, capsys):
    """--sdist-hygiene：干净 sdist→exit 0；混入禁入成员→exit 1（不凑绿）。

    _run_offline 打 mock 产合成 sdist——单测不真跑 build（真跑验收见
    scripts/release_readiness.py --sdist-hygiene 本地实测）。
    """
    def fake_run_clean(cmd: list[str], timeout_s: int = 600):
        out = Path(cmd[cmd.index("--outdir") + 1])
        _make_sdist(out, ["src/rfauto/a.py", "README.md"])
        return True, "ok"

    monkeypatch.setattr(rr, "_run_offline", fake_run_clean)
    assert rr.main(["--sdist-hygiene", "--staging", str(tmp_path / "stg_ok")]) == 0
    out = capsys.readouterr().out
    assert "0 泄漏" in out and "PASS" in out

    def fake_run_leak(cmd: list[str], timeout_s: int = 600):
        out = Path(cmd[cmd.index("--outdir") + 1])
        _make_sdist(out, ["src/rfauto/a.py", "ads_reference/doc.md"])
        return True, "ok"

    monkeypatch.setattr(rr, "_run_offline", fake_run_leak)
    assert rr.main(["--sdist-hygiene", "--staging", str(tmp_path / "stg_leak")]) == 1
    out = capsys.readouterr().out
    assert "ads_reference" in out and "FAIL" in out


def test_sdist_hygiene_missing_backend_reports_fail(monkeypatch, tmp_path, capsys):
    """build 后端缺失：如实 FAIL（exit 1），不伪绿。"""
    real_find_spec = rr.importlib.util.find_spec

    def fake_find_spec(name: str, *a, **k):
        if name == "build":
            return None
        return real_find_spec(name, *a, **k)

    monkeypatch.setattr(rr.importlib.util, "find_spec", fake_find_spec)
    assert rr.main(["--sdist-hygiene", "--staging", str(tmp_path / "stg")]) == 1
    assert "缺 build" in capsys.readouterr().out


# ─── F4 build 步骤可 mock（不真跑 build/twine）+ MCP 清单确定性 ───────────────

def test_f4_build_steps_mockable_and_manifest_deterministic(monkeypatch, tmp_path):
    pytest.importorskip("fastmcp")
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], timeout_s: int = 600):
        calls.append(cmd)
        if "build" in cmd:
            out = Path(cmd[cmd.index("--outdir") + 1])
            out.mkdir(parents=True, exist_ok=True)
            (out / "rfauto-0.0.0.tar.gz").write_bytes(b"")
            (out / "rfauto-0.0.0-py3-none-any.whl").write_bytes(b"")
        return True, "ok"

    monkeypatch.setattr(rr, "_run_offline", fake_run)
    monkeypatch.setattr(rr, "dist_member_leaks", lambda artifacts: [])

    sec1 = rr.sec_f4_mcp(tmp_path / "s1", build=True)
    sec2 = rr.sec_f4_mcp(tmp_path / "s2", build=True)
    assert sec1.status == "PASS", [vars(i) for i in sec1.items if not i.ok]
    build_cmd = next(c for c in calls if "build" in c)
    assert "--no-isolation" in build_cmd and "--outdir" in build_cmd
    twine_cmd = next(c for c in calls if "twine" in c)
    assert twine_cmd[twine_cmd.index("twine") + 1] == "check"
    assert all("upload" not in c for c in calls)

    m1 = (tmp_path / "s1" / "mcp" / "manifest.json").read_text(encoding="utf-8")
    m2 = (tmp_path / "s2" / "mcp" / "manifest.json").read_text(encoding="utf-8")
    assert m1 == m2
    manifest = json.loads(m1)
    names = [t["name"] for t in manifest["tools"]]
    assert names == sorted(names) and len(names) == manifest["tool_count"]
    # AU-1 批3 拆分（2026-09-30）：源码装饰器数口径=facade + mcp_tools/ 聚合
    # （与 scripts/release_readiness.py sec_f4_mcp 同口径）
    _mcp_srcs = [
        rr.REPO_ROOT / "src" / "rfauto" / "mcp_server.py",
        *sorted((rr.REPO_ROOT / "src" / "rfauto" / "mcp_tools").glob("*.py")),
    ]
    src_count = sum(1 for f in _mcp_srcs for line
                    in f.read_text(encoding="utf-8").splitlines()
                    if line.startswith("@mcp.tool"))
    assert manifest["tool_count"] == src_count
    assert all(t["description"] for t in manifest["tools"])
    del sec2
