"""Q-W8-3 CLI 退出码契约审计测试（aurora_q R11 Top2 吸收批）。

审计器=scripts/audit_cli_exit_codes.py（gh 退出码机制吸收，#288 静默降级
家族对照面）。契约三档（_core.py _emit/_emit_usage_error 单源惯例）：

  0=成功 / 1=业务失败（信封 ok=False）/ 2=用法错误（typer.BadParameter 同档）

门形态（W2-C 家法：探针内联，禁 runs/ 工件依赖）：
- 全 CLI 面 rc 字面量 ∈ {0,1,2}（越界即红——硬门）；
- 裸 sys.exit/os._exit 零容忍（契约出口=typer.Exit）；
- 动态退出码逐点静态求界，界 ⊆ {0,1,2}；site 集合棘轮（新点必显式评估）；
- 静默降级嫌疑叶（except-pass × 全路径 rc 恒 0）计数棘轮只收不放；
- 合成模块负例：越界/裸退出/嫌疑分类/动态求界四类注入逐一检出。

不跑真 CLI 子进程（枚举走 typer 注册面内存形态，301 叶零副作用）。
"""

from __future__ import annotations

import ast
import importlib.util
import json
import textwrap
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "audit_cli_exit_codes.py"
_SPEC = importlib.util.spec_from_file_location("audit_cli_exit_codes", _SCRIPT)
audit_mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(audit_mod)

# ── 棘轮常量（只收不放；有意抬门须同笔说明并更新此处） ─────────────────────
#: 静默降级嫌疑叶上限（基线实测 0——契约已净；新嫌疑出现即红）
SUSPECT_RATCHET = 0
#: 动态退出码 site 名单（基线实测 2：fab ok_code 形参缺省 0、loop 状态映射 0/1，
#: 均已静态求界 ⊆ 契约；新增动态点必须入本名单并写明求界依据）
DYNAMIC_SITE_ALLOWLIST = {
    ("src\\rfauto\\cli\\fab_app.py", 49),
    ("src\\rfauto\\cli\\domains\\loop.py", 114),
}


def _synthetic_index(monkeypatch: pytest.MonkeyPatch, sources: dict[str, str]):
    """合成 CLI 模块索引注入：sources {stem: 源码} → tmp 盘 _CliIndex。"""
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="qw83_synth_"))
    files = []
    for stem, src in sources.items():
        f = tmp / f"{stem}.py"
        f.write_text(textwrap.dedent(src), encoding="utf-8")
        files.append(f)
    monkeypatch.setattr(audit_mod, "cli_module_files", lambda: files)
    return audit_mod._CliIndex()


# ────────────────────────── 注册面枚举 ──────────────────────────


class TestEnumeration:
    def test_leaf_enumeration_matches_check_numbers_anchor(self):
        """叶枚举与权威计数单源对拍（#97 数字链；check_numbers.count_cli
        同口径=click 解析去重实注册展开）。"""
        import importlib.util as _ilu

        cn_spec = _ilu.spec_from_file_location(
            "check_numbers_gate",
            Path(__file__).resolve().parents[2] / "scripts" / "check_numbers.py")
        cn = _ilu.module_from_spec(cn_spec)
        cn_spec.loader.exec_module(cn)
        leaves = audit_mod.enumerate_cli_leaves()
        assert len(leaves) == cn.count_cli()
        assert len(leaves) >= 300  # 量级守卫（防枚举意外塌缩成空过门）

    def test_leaf_entries_have_module_and_func(self):
        leaves = audit_mod.enumerate_cli_leaves()
        assert all(e["module"].startswith("rfauto.cli.") for e in leaves)
        assert all(e["func"] for e in leaves)
        paths = [e["path"] for e in leaves]
        assert len(paths) == len(set(paths)), "叶路径必须唯一（对拍锚前提）"


# ────────────────────────── 契约硬门（全 CLI 面） ──────────────────────────


class TestContractGates:
    def test_all_rc_literals_within_contract(self):
        """全 CLI 面 Exit/typer 机制映射的 rc 字面量 ∈ {0,1,2}——越界即红。"""
        report = audit_mod.audit_cli_exit_codes()
        assert report["violations"] == [], (
            f"退出码契约越界 {len(report['violations'])} 处: "
            f"{report['violations'][:5]}")

    def test_no_bare_exit_in_cli_face(self):
        """裸 sys.exit/os._exit 零容忍（契约出口=typer.Exit；可测试性）。"""
        report = audit_mod.audit_cli_exit_codes()
        assert report["bare_exit_sites"] == [], (
            f"裸退出 {report['bare_exit_sites'][:5]}")

    def test_dynamic_exit_sites_all_bounded(self):
        """动态退出码逐点静态求界且界 ⊆ 契约——不可求界=violation 级。"""
        report = audit_mod.audit_cli_exit_codes()
        for site in report["dynamic_sites"]:
            b = site.get("bounded")
            assert b is not None, f"动态退出码不可求界: {site}"
            assert set(b) <= audit_mod.ALLOWED_RC, f"动态退出码越界: {site}"

    def test_dynamic_site_allowlist_ratchet(self):
        """动态 site 集合棘轮：新出现动态点必须显式入名单+写明求界依据。"""
        report = audit_mod.audit_cli_exit_codes()
        actual = {(s["file"], s["line"]) for s in report["dynamic_sites"]}
        assert actual <= DYNAMIC_SITE_ALLOWLIST, (
            f"新动态退出码 site 未评估入名单: {actual - DYNAMIC_SITE_ALLOWLIST}")

    def test_silent_degradation_suspects_ratchet(self):
        """静默降级嫌疑叶棘轮（except-pass × 全路径 rc 恒 0）——只收不放。"""
        report = audit_mod.audit_cli_exit_codes()
        assert len(report["suspects"]) <= SUSPECT_RATCHET, (
            f"静默降级嫌疑叶超棘轮: {[s['path'] for s in report['suspects']]}")

    def test_rc_distribution_sums_to_leaf_count(self):
        """rc 分布计数与叶总数闭合（报告自洽）。"""
        report = audit_mod.audit_cli_exit_codes()
        assert sum(report["rc_distribution"].values()) == report["leaf_count"]
        assert sum(report["leaf_classes"].values()) == report["leaf_count"]


# ────────────────────────── 合成模块负例 ──────────────────────────


class TestSyntheticNegativeExamples:
    def test_out_of_range_rc_literal_detected(self, monkeypatch):
        """负例：Exit(code=3) 字面量越界 → violations 检出（3 ∉ {0,1,2}）。"""
        index = _synthetic_index(monkeypatch, {
            "synbad": '''
                import typer

                def leaf_bad():
                    if True:
                        raise typer.Exit(code=3)
            ''',
        })
        leaves = [{"path": "leaf_bad", "name": "leaf_bad",
                   "module": "synthetic.synbad", "func": "leaf_bad"}]
        report = audit_mod._audit_with_index(index, leaves)
        assert len(report["violations"]) == 1
        assert report["violations"][0]["codes"] == [3]

    def test_bare_sys_exit_detected(self, monkeypatch):
        """负例：裸 sys.exit(1) → bare_exit_sites 检出（契约出口=typer.Exit）。"""
        index = _synthetic_index(monkeypatch, {
            "synbare": '''
                import sys

                def leaf_bare():
                    sys.exit(1)
            ''',
        })
        leaves = [{"path": "leaf_bare", "name": "leaf_bare",
                   "module": "synthetic.synbare", "func": "leaf_bare"}]
        report = audit_mod._audit_with_index(index, leaves)
        assert len(report["bare_exit_sites"]) == 1

    def test_suspect_leaf_except_pass_never_fails(self, monkeypatch):
        """负例：except-pass 吞噬 × 全路径 rc 恒 0 → 嫌疑叶检出。"""
        index = _synthetic_index(monkeypatch, {
            "synsuspect": '''
                def _helper_swallow():
                    try:
                        pass
                    except Exception:
                        pass

                def leaf_suspect():
                    _helper_swallow()
            ''',
        })
        leaves = [{"path": "leaf_suspect", "name": "leaf_suspect",
                   "module": "synthetic.synsuspect", "func": "leaf_suspect"}]
        report = audit_mod._audit_with_index(index, leaves)
        assert len(report["suspects"]) == 1
        assert report["suspects"][0]["path"] == "leaf_suspect"

    def test_swallow_with_business_fail_not_suspect(self, monkeypatch):
        """正例辨析：有 Exit(1) 失败路径的吞噬叶不算嫌疑（会失败≠静默）。"""
        index = _synthetic_index(monkeypatch, {
            "synok": '''
                import typer

                def leaf_ok():
                    try:
                        pass
                    except Exception:
                        pass
                    raise typer.Exit(code=1)
            ''',
        })
        leaves = [{"path": "leaf_ok", "name": "leaf_ok",
                   "module": "synthetic.synok", "func": "leaf_ok"}]
        report = audit_mod._audit_with_index(index, leaves)
        assert report["suspects"] == []
        assert report["per_leaf"][0]["class"] == "can_fail"

    def test_dynamic_bound_via_param_default_and_callee_returns(
            self, monkeypatch):
        """动态求界两形态：形参缺省回查（ok_code 形态）+被调函数 return
        字面量回查（_rc_of_status 形态）——合成复刻两条真机路径。"""
        index = _synthetic_index(monkeypatch, {
            "syndyn": '''
                import typer

                def _rc_of_status(status):
                    return 0 if status == "completed" else 1

                def _emit(result, ok_code=0):
                    if not result.get("ok"):
                        raise typer.Exit(code=2 if result.get("needs") else 1)
                    raise typer.Exit(code=ok_code)

                def leaf_dyn(flag):
                    _emit({"ok": flag}, ok_code=0)
                    raise typer.Exit(code=_rc_of_status(str(flag)))
            ''',
        })
        leaves = [{"path": "leaf_dyn", "name": "leaf_dyn",
                   "module": "synthetic.syndyn", "func": "leaf_dyn"}]
        report = audit_mod._audit_with_index(index, leaves)
        dyn = {(d["expr"], tuple(sorted(d["bounded"] or [])))
               for d in report["dynamic_sites"]}
        assert ("ok_code", (0,)) in dyn, f"形参缺省求界缺失: {dyn}"
        assert ("_rc_of_status(str(flag))", (0, 1)) in dyn, (
            f"被调 return 求界缺失: {dyn}")
        # 叶可达 rc：0(隐式) ∪ {1,2}(IfExp) ∪ {0,1}(_rc_of_status)
        assert report["per_leaf"][0]["rc_codes"] == [0, 1, 2]

    def test_typer_bad_parameter_maps_to_usage_rc2(self, monkeypatch):
        """typer.BadParameter → 用法错误档 rc=2（click 机制映射，与 Exit(2)
        同档入契约模型）。"""
        index = _synthetic_index(monkeypatch, {
            "synbadparam": '''
                import typer

                def leaf_param(x):
                    if not x:
                        raise typer.BadParameter("x required")
            ''',
        })
        leaves = [{"path": "leaf_param", "name": "leaf_param",
                   "module": "synthetic.synbadparam", "func": "leaf_param"}]
        report = audit_mod._audit_with_index(index, leaves)
        assert report["per_leaf"][0]["rc_codes"] == [0, 2]
        assert report["per_leaf"][0]["class"] == "usage_only"


# ────────────────────────── 折叠/解析原语 ──────────────────────────


class TestPrimitives:
    @pytest.mark.parametrize("src,expected", [
        ("0", {0}), ("1", {1}), ("2", {2}),
        ("2 if result.get('needs') else 1", {1, 2}),
        ("0 if a else (1 if b else 2)", {0, 1, 2}),
        ("ok_code", None),
        ("'x'", None),
    ])
    def test_fold_int(self, src, expected):
        tree = ast.parse(src, mode="eval")
        assert audit_mod._fold_int(tree.body) == expected

    @pytest.mark.parametrize("src,kind,codes", [
        ("typer.Exit(code=1)", "exit", {1}),
        ("typer.Exit(2)", "exit", {2}),
        ("typer.Exit()", "exit", {0}),
        ("Exit(code=ok_code)", "exit", None),
        ("sys.exit(1)", "bare", None),
        ("os._exit(0)", "bare", None),
        ("typer.BadParameter('x')", "other", {2}),
        ("typer.UsageError('x')", "other", {2}),
        ("typer.Abort()", "other", {1}),
        ("ValueError('x')", "other", None),
    ])
    def test_exit_call_code_classification(self, src, kind, codes):
        tree = ast.parse(src, mode="eval").body
        got_codes, got_kind = audit_mod._exit_call_code(tree)
        assert got_kind == kind
        assert got_codes == codes


# ────────────────────────── 共享契约单源钉 ──────────────────────────


class TestSharedHelpers:
    def test_core_emit_helpers_contract_codes(self):
        """_core.py 共享出口契约钉：_emit 失败路径 Exit(1)、
        _emit_usage_error Exit(2)——三档惯例的单源（审计器语义基准）。"""
        core = Path(__file__).resolve().parents[2] / "src" / "rfauto" / "cli" \
            / "domains" / "_core.py"
        tree = ast.parse(core.read_text(encoding="utf-8"))
        codes_by_fn: dict[str, set[int]] = {}
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            codes: set[int] = set()
            for sub in ast.walk(node):
                if isinstance(sub, ast.Raise) and isinstance(sub.exc, ast.Call):
                    got, kind = audit_mod._exit_call_code(sub.exc)
                    if kind == "exit" and got is not None:
                        codes |= got
            codes_by_fn[node.name] = codes
        assert 1 in codes_by_fn["_emit"], "_emit 失败路径必须 Exit(1)"
        assert codes_by_fn["_emit_usage_error"] == {2}, (
            "_emit_usage_error 必须 Exit(2)")
        assert 2 not in codes_by_fn["_emit"], "_emit 不越过 usage 档（2 留给 usage）"


# ────────────────────────── 报告落盘 ──────────────────────────


class TestReportWriter:
    def test_write_report_roundtrip(self, tmp_path):
        report = audit_mod.audit_cli_exit_codes()
        json_path, md_path = audit_mod.write_report(report, tmp_path)
        assert json_path.exists() and md_path.exists()
        loaded = json.loads(json_path.read_text(encoding="utf-8"))
        assert loaded["leaf_count"] == report["leaf_count"]
        md = md_path.read_text(encoding="utf-8")
        assert "CLI 退出码契约审计报告" in md
        assert "## rc 分布" in md
        assert "## 动态退出码 site" in md
        assert "## 静默降级嫌疑叶" in md

    def test_main_reports_contract_clean_rc0(self, tmp_path, capsys):
        """脚本自守契约：全绿审计自身退出码 0（--json 摘要含报告路径）。"""
        rc = audit_mod.main(["--out", str(tmp_path), "--json"])
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["violations"] == 0
        assert payload["suspects"] == 0
        assert (tmp_path / "cli_exit_code_audit.json").exists()
