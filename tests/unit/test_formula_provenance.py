"""KD-1 公式 provenance 注册表锚树（specs 研究扩充 round16 KD-1）。

五面锚（KD-1 载体裁决=三载体缺一即漂移）：
1. 一致性门——YAML ↔ 仓级 AST 扫描逐条目相等：docstring 出处改动未再生=红、
   注册表孤儿条目（docstring 标记已消失）=红、新标记未收集=红；
2. 幂等门——render(fresh) 与盘上文件逐字节一致（同树二跑 diff=0，无时间戳字段）；
3. schema 负例（条目缺键/多键/坏枚举/formula_id 重复/manual 键面）+ 路径发现
   （显式 > env 设置即信 > canonical）；
4. 查询面 formula_provenance(symbol/file/module/kind) 过滤语义 + 覆盖摘要；
5. XC-P 并轨——10 内核标记覆盖下限 + 共享标识符包含钉（XC-P refs 中与内核
   docstring 同现的 DOI/arXiv id 必须进本表 refs）+ 分工注记在档；tmp 树
   收集行为（标记→条目/指针/裸"参考"证据守卫/精度档案镜像剥离/漂移可检出）。

铁律 7 锚：本测试零物理数字断言——只核对"注册表声明与 docstring 声明一致"
与"查询行为语义正确"；出处可达性等声明面真伪由文献面（HFSS 仲裁/独立来源）
看管，本注册表是转录面不是数值裁判。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.core.formula_provenance import (
    FORMULA_PROVENANCE_ENV,
    FormulaProvenanceSchemaError,
    _bare_ref_has_evidence,
    default_formula_provenance_yaml_path,
    formula_provenance,
    load_formula_provenance,
    provenance_summary,
    render_formula_provenance_yaml,
    resolve_formula_provenance_yaml_path,
    scan_formula_provenance,
    scan_repo_formula_provenance,
)
from rfauto.core.precision_profiles import KERNEL_MODULES

_REPO_ROOT = Path(__file__).resolve().parents[2]
_YAML_PATH = _REPO_ROOT / "knowledge" / "formula_provenance.yaml"


def _norm(text: str) -> str:
    return text.replace("\r\n", "\n")


@pytest.fixture(scope="module")
def fresh() -> list[dict]:
    return scan_repo_formula_provenance(_REPO_ROOT)


@pytest.fixture(scope="module")
def registry() -> dict:
    return load_formula_provenance(_YAML_PATH)


# ─── 1. 一致性门：YAML × docstring 扫描逐条目对照（防漂移主门）────────────────

def test_registry_matches_fresh_scan(registry, fresh):
    """docstring 出处改动未再生注册表=红；孤儿条目（标记已消失）=红。"""
    on_disk = registry["entries"]
    if on_disk != fresh:
        disk_ids = [e["formula_id"] for e in on_disk]
        fresh_ids = [e["formula_id"] for e in fresh]
        orphans = sorted(set(disk_ids) - set(fresh_ids))
        missed = sorted(set(fresh_ids) - set(disk_ids))
        drifted = sorted(
            e["formula_id"] for e in on_disk if e not in fresh
        )
        pytest.fail(
            "KD-1 注册表与 docstring 扫描漂移——先再生："
            "python scripts/collect_formula_provenance.py\n"
            f"孤儿条目={orphans}\n未收集标记={missed}\n内容漂移={drifted[:10]}"
        )


def test_registry_entry_files_exist_on_disk(registry):
    """文件级孤儿 sanity：每个 kernel_file 必须真实存在（重命名/删除后未再生=红）。"""
    missing = [
        e["kernel_file"]
        for e in registry["entries"]
        if not (_REPO_ROOT / e["kernel_file"]).is_file()
    ]
    assert missing == [], f"注册表引用了不存在的内核文件: {sorted(set(missing))}"


# ─── 2. 幂等门：再生渲染逐字节一致 ───────────────────────────────────────────

def test_collector_idempotent_render(registry, fresh):
    """render(scan()) 与盘上文件逐字节一致——同树二跑 diff=0（幂等契约）。"""
    rendered = render_formula_provenance_yaml(fresh, registry["manual_entries"])
    assert _norm(_YAML_PATH.read_text(encoding="utf-8")) == _norm(rendered)


def test_collector_script_check_mode_passes():
    """薄壳 --check 端到端：注册表在档且无漂移 → exit 0（再生后忘提交=红）。"""
    import subprocess

    proc = subprocess.run(
        [sys.executable, str(_REPO_ROOT / "scripts" / "collect_formula_provenance.py"), "--check"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, f"--check 漂移（须再生注册表）:\n{proc.stdout}\n{proc.stderr}"


def test_coding_metasurface_registered_with_refs():
    """A-16（2026-10-04）：coding_metasurface 模块 docstring 分节头
    "权威口径"→"权威口径："（对齐 MARKER_LINE_RE 收集面）后入册——
    Cui 2014 / Liang 2016 引文行必须进 refs（此前裸分节头无冒号未入册）。"""
    hits = formula_provenance(module="rfauto.core.coding_metasurface")
    assert hits, "coding_metasurface 出处未入册（A-16 再生遗漏）"
    refs = [r for e in hits for r in e["refs"]]
    assert any("2014" in r for r in refs), refs  # Cui 2014 Light Sci Appl
    assert any("2016" in r for r in refs), refs  # Liang 2016 Sci Rep


# ─── 3. schema 负例 + 路径发现 ────────────────────────────────────────────────

def _base_entry() -> dict:
    return {
        "formula_id": "x:foo:01",
        "kernel_file": "src/rfauto/core/x.py",
        "module": "rfauto.core.x",
        "symbol": "foo",
        "kind": "source",
        "marker": "来源：",
        "claim_line": "来源：Pozar §1.1",
        "claim_block": "来源：Pozar §1.1",
        "refs": [],
        "source_doi": None,
        "eq_no": "§1.1",
        "expr": None,
        "access_status": None,
        "verified_by": "t",
        "origin": "docstring",
    }


def _write_registry(tmp_path, payload: dict) -> Path:
    import yaml

    p = tmp_path / "fp.yaml"
    p.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return p


def test_schema_negative_cases(tmp_path):
    """缺键/多键/坏枚举/formula_id 重复/manual 越权键 → FormulaProvenanceSchemaError。"""
    bad_missing = _base_entry()
    del bad_missing["eq_no"]
    bad_extra = _base_entry()
    bad_extra["oops"] = 1
    bad_kind = _base_entry()
    bad_kind["kind"] = "citation"
    dup_a, dup_b = _base_entry(), _base_entry()
    manual_bad = {"formula_id": "m:1", "claim_line": "x", "verified_by": "t", "note2": "越权"}
    for payload in (
        {"schema_version": 1, "entries": [bad_missing], "manual_entries": []},
        {"schema_version": 1, "entries": [bad_extra], "manual_entries": []},
        {"schema_version": 1, "entries": [bad_kind], "manual_entries": []},
        {"schema_version": 1, "entries": [dup_a, dup_b], "manual_entries": []},
        {"schema_version": 1, "entries": [], "manual_entries": [manual_bad]},
    ):
        p = _write_registry(tmp_path, payload)
        with pytest.raises(FormulaProvenanceSchemaError):
            load_formula_provenance(p)


def test_manual_entry_roundtrip_preserved(tmp_path):
    """manual_entries 人工补录区被加载与再生渲染逐字保留（人工可补契约）。"""
    manual = {
        "formula_id": "manual:itu_p676:01",
        "kernel_file": "src/rfauto/core/itu_atmosphere.py",
        "module": "rfauto.core.itu_atmosphere",
        "symbol": "<module>",
        "kind": "source",
        "marker": "文献：",
        "claim_line": "文献：ITU-R P.676-13 逐线吸收系数表（人工补录示例）",
        "claim_block": "文献：ITU-R P.676-13 逐线吸收系数表（人工补录示例）",
        "refs": ["ITU-R P.676-13"],
        "source_doi": None,
        "eq_no": None,
        "expr": None,
        "access_status": "verified",
        "verified_by": "人工补录（示例）",
        "origin": "manual",
    }
    p = _write_registry(tmp_path, {"schema_version": 1, "entries": [], "manual_entries": [manual]})
    loaded = load_formula_provenance(p)
    assert loaded["manual_entries"] == [manual]
    again = render_formula_provenance_yaml([], loaded["manual_entries"])
    p2 = tmp_path / "fp2.yaml"
    p2.write_text(again, encoding="utf-8")
    assert load_formula_provenance(p2)["manual_entries"] == [manual]


def test_path_resolution_explicit_env_canonical(tmp_path, monkeypatch):
    """显式入参 > env（设置即信，缺失不静默回退）> canonical。"""
    # env 设置即信：指向不存在路径 → FileNotFoundError（不静默回退 canonical）
    missing = tmp_path / "nope.yaml"
    monkeypatch.setenv(FORMULA_PROVENANCE_ENV, str(missing))
    with pytest.raises(FileNotFoundError):
        load_formula_provenance(None)
    # 显式入参压过 env
    good = _write_registry(tmp_path, {"schema_version": 1, "entries": [_base_entry()],
                                      "manual_entries": []})
    data = load_formula_provenance(good)
    assert data["entries"][0]["formula_id"] == "x:foo:01"
    # canonical 可解析且落在仓内 knowledge/
    monkeypatch.delenv(FORMULA_PROVENANCE_ENV, raising=False)
    assert resolve_formula_provenance_yaml_path(None) == default_formula_provenance_yaml_path()
    assert resolve_formula_provenance_yaml_path(None).parent.name == "knowledge"


# ─── 4. 查询面 ────────────────────────────────────────────────────────────────

def test_query_surface_filters(registry):
    """symbol/file/module/kind 过滤语义 + entries 注入与 path 读档一致。"""
    entries = registry["entries"]
    hits = formula_provenance("abcd_series", "emi_filter.py", entries=entries)
    assert len(hits) == 1
    assert hits[0]["module"] == "rfauto.core.emi_filter"
    assert hits[0]["kernel_file"].endswith("/emi_filter.py")
    # 全路径精确匹配（file 查询语义=该文件全部条目）
    full = hits[0]["kernel_file"]
    assert formula_provenance(file=full, entries=entries) == [
        e for e in entries if e["kernel_file"] == full
    ]
    # symbol="..."
    assert all(e["symbol"] == "<module>" for e in formula_provenance(symbol="<module>", entries=entries))
    # kind 过滤：pointer 块恒等于单行 claim_line
    pointers = formula_provenance(kind="pointer", entries=entries)
    assert pointers and all(e["claim_block"] == e["claim_line"] for e in pointers)
    # module 过滤
    mods = formula_provenance(module="rfauto.core.conductor_loss", entries=entries)
    assert mods and all(e["module"] == "rfauto.core.conductor_loss" for e in mods)
    # 未知键域 → 空（不抛）
    assert formula_provenance("no_such_symbol", entries=entries) == []
    # 组合过滤
    assert formula_provenance("<module>", kind="source", entries=entries) == [
        e for e in entries if e["symbol"] == "<module>" and e["kind"] == "source"
    ]


def test_provenance_summary_consistent(registry):
    """覆盖摘要与注册表内容自洽（如实口径报告面）。"""
    s = provenance_summary(entries=registry["entries"])
    assert s["entries"] == len(registry["entries"])
    assert s["files"] == len({e["kernel_file"] for e in registry["entries"]})
    assert s["by_kind"].get("source", 0) + s["by_kind"].get("pointer", 0) == s["entries"]
    assert sum(s["by_access"].values()) == s["entries"]
    assert s["kernel_files"] == sorted(set(s["kernel_files"]))


# ─── 5. XC-P 并轨（分工互补 + 共享标识符包含钉）───────────────────────────────

def _xcp_kernel_registry_entries(registry, dotted: str) -> list[dict]:
    return [e for e in registry["entries"] if e["module"] == dotted]


def _xcp_identifiers(refs: list[str]) -> list[str]:
    """XC-P refs 里的 DOI/arXiv 标识（arXiv 去 vN 基底化，与收集器口径对齐）。"""
    out = []
    for ref in refs:
        for m in re.finditer(r"10\.\d{4,9}/[^\s，。；、（）)\"']+", ref):
            out.append(m.group(0).rstrip(".,;）"))
        for m in re.finditer(r"arXiv:([0-9]{4}\.[0-9]{4,5})(?:v[0-9]+)?", ref):
            out.append(f"arXiv:{m.group(1)}")
    return out


def test_xcp_kernel_marker_coverage_floor(registry, fresh):
    """有标记必有条目：每个 XC-P 内核若 docstring 存在出处标记，注册表必有其条目；
    并钉覆盖下限（首批 10 内核中 ≥5 个有标记条目——只升不降）。"""
    covered = 0
    for kid, dotted in KERNEL_MODULES.items():
        fresh_hits = [e for e in fresh if e["module"] == dotted]
        reg_hits = _xcp_kernel_registry_entries(registry, dotted)
        if fresh_hits:
            assert reg_hits, (
                f"XC-P 内核 {kid}（{dotted}）docstring 有出处标记但注册表无条目——再生注册表"
            )
            covered += 1
    assert covered >= 5, f"XC-P 内核出处覆盖数回落（现 {covered}，首批 ≥5）"


def test_xcp_shared_identifier_inclusion(registry):
    """共享标识符包含钉：XC-P refs 的 DOI/arXiv id 若与该内核 docstring 同现
    （出现在 KD-1 claim 块内），必须被收集进该内核条目的 refs——两表同源不漂移。"""
    xcp = load_precision_profiles_safe()
    pinned = 0
    for kid, spec in xcp["kernels"].items():
        dotted = KERNEL_MODULES[kid]
        entries = _xcp_kernel_registry_entries(registry, dotted)
        blocks = "\n".join(e["claim_block"] for e in entries)
        # arXiv 基底化（去 vN）后比对——收集器原样保留版本号，XC-P 两侧口径对齐
        ref_bases = set()
        for e in entries:
            for r in e["refs"]:
                ref_bases.add(
                    re.sub(r"v[0-9]+$", "", r) if r.startswith("arXiv:") else r
                )
        for ident in _xcp_identifiers(spec["refs"]):
            if ident in blocks:
                assert ident in ref_bases, (
                    f"XC-P 内核 {kid} 的共享标识 {ident} 出现在 docstring 声明块内，"
                    f"但未进 KD-1 refs——抽取器回归或注册表过期"
                )
                pinned += 1
    # 首批已知同现对（ridged arXiv 数值锚 + conductor Hall-Huray DOI）必须被钉住
    assert pinned >= 2, f"共享标识符钉数回落（现 {pinned}，首批 ≥2）"


def load_precision_profiles_safe() -> dict:
    from rfauto.core.precision_profiles import load_precision_profiles

    return load_precision_profiles(_REPO_ROOT / "knowledge" / "precision_profiles.yaml")


def test_division_of_labor_note_present():
    """分工注记在档：注册表头与查询单源 docstring 均声明 KD-1=出处 / XC-P=精度。"""
    header = _YAML_PATH.read_text(encoding="utf-8").split("schema_version:", 1)[0]
    assert "XC-P" in header and "precision_profiles.yaml" in header
    assert "出处" in header and "精度" in header
    import rfauto.core.formula_provenance as fp_mod

    assert "XC-P" in (fp_mod.__doc__ or "")


def test_precision_mirror_lines_not_collected(registry):
    """XC-P「精度档案」镜像行是 XC-P 载体——不得混进本注册表的声明块。"""
    contaminated = [
        e["formula_id"]
        for e in registry["entries"]
        if "精度档案" in e["claim_block"] or "精度档案" in e["claim_line"]
    ]
    assert contaminated == []


# ─── 6. tmp 树收集行为（收集器语义单测，不依赖仓 docstring 现状）───────────────

def test_tmp_tree_collection_semantics(tmp_path):
    """标记→条目 / 指针 / 裸"参考"证据守卫 / docstring 改动→漂移可检出。"""
    core = tmp_path / "src" / "rfauto" / "core"
    core.mkdir(parents=True)
    (core / "demo_kernel.py").write_text(
        '"""演示内核。\n\n来源：Pozar, Microwave Engineering, §1.1（趋肤深度）。\n\n'
    '法源（铁律 5）：\n- Harris 1978, Proc. IEEE 66(1)（窗谱）。\n"""\n'
        "def beta(x):\n"
        '    """相位常数。\n\n    出处见模块 docstring（Kerns NBS Monograph 162, 1981）。\n'
        '    参考（不做门判）。本行是 prose 用法应被剔除。\n    参考：docs/spec.md §A-1。\n'
        '    """\n'
        "    return x\n",
        encoding="utf-8",
    )
    entries = scan_formula_provenance(core, module_prefix="rfauto.core",
                                      kernel_file_base=tmp_path)
    ids = {e["formula_id"] for e in entries}
    # 模块级两条 source（来源 + 法源）+ 函数级 1 指针 + 1 有效裸参考；prose 参考被剔
    assert "demo_kernel:<module>:01" in ids
    assert "demo_kernel:<module>:02" in ids
    assert any(e["kind"] == "pointer" and e["symbol"] == "beta" for e in entries)
    # 裸"参考（不做门判）"无证据被剔：任何条目的 claim_line 都不是它；
    # 剔除后序号回退——带证据的"参考：docs/…"占 beta:02 槽位
    assert not any(e["claim_line"].startswith("参考（不做门判）") for e in entries)
    kept_ref = [e for e in entries if e["symbol"] == "beta" and e["marker"].startswith("参考")]
    assert [e["formula_id"] for e in kept_ref] == ["demo_kernel:beta:02"]
    assert "docs/" in kept_ref[0]["claim_block"]
    # 抽取面：§ 锚 / 引文行 / source_doi
    src1 = next(e for e in entries if e["formula_id"] == "demo_kernel:<module>:01")
    assert src1["eq_no"] == "§1.1"
    src2 = next(e for e in entries if e["formula_id"] == "demo_kernel:<module>:02")
    assert any("Harris 1978" in r for r in src2["refs"])
    # DOI 抽取与幂等：同树二跑渲染逐字节一致
    rendered1 = render_formula_provenance_yaml(entries)
    entries2 = scan_formula_provenance(core, module_prefix="rfauto.core",
                                       kernel_file_base=tmp_path)
    assert render_formula_provenance_yaml(entries2) == rendered1
    # docstring 改动未再生 → 渲染文本变化（一致性门可检出）
    (core / "demo_kernel.py").write_text(
        (core / "demo_kernel.py").read_text(encoding="utf-8").replace(
            "§1.1", "§1.2（修订）"),
        encoding="utf-8",
    )
    entries3 = scan_formula_provenance(core, module_prefix="rfauto.core",
                                       kernel_file_base=tmp_path)
    assert render_formula_provenance_yaml(entries3) != rendered1


def test_bare_ref_evidence_guard_unit():
    """裸"参考"证据守卫单点：有 § 锚/docs/ 链接=收；纯 prose=剔。"""
    assert _bare_ref_has_evidence("参考：docs/plan.md §A-9")
    assert _bare_ref_has_evidence("参考：ITU-R S.733-2（G/T）")
    assert not _bare_ref_has_evidence("参考（不做门判）。返回 dict 供消费。")
