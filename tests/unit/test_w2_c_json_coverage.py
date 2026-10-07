"""W2-C（VI-5 批A+批B，2026-10-05）+ W6-B（批C 余件 86，2026-10-06）``--json`` 归一常驻门：
探针内联棘轮 + 34 命令双路径冒烟 + 86 命令参数化冒烟批。

规格=runs/research_seats_20261004/sp_specs6/SPECS.md §VI-5；批席位判据：
1. 棘轮门（探针逻辑内联，禁 runs/ 工件依赖）：批A 后 WITHOUT_JSON≤110、
   批B 后 ≤87（防回潮棘轮，#325 家法逐批收窄；并发席新增无 --json 命令
   也会打红本门——这正是规格"新命令必须带 --json"惯例的钉面）；
   批C（W6-B 席）后收紧 ≤1——全树仅剩结构性豁免 ui（阻塞式 uvicorn
   serve，无单发输出面，W6-B REPORT.md §豁免清单同账）；
2. 每命令 ≥1 条 --json 双路径冒烟（成功信封+失败信封同构）——离线确定性：
   真实服务面（validate/bands/bench/fab 离线链/sweep fake）+ 服务注入
   （monkeypatch，#139：run/refine 等重路径只钉 CLI 接线不真跑）；
   批C 86 件走参数化冒烟批（真实离线面优先、payload 重面注入）；
3. CLI 计数零变（只加旗标不加命令——本文件不复制计数锚，零变由
   test_check_numbers/test_cli 权威；本席 git diff 零 @command 增删）。

形态说明（REPORT.md 同账）：34 件中 22 件为 rich 缺省命令（run/tune/sweep/
validate/refine/replay/report/datasets query/runs compare 共 9 件真切换 +
旗标组合正交分支），12 件自始即 JSON 信封直出（runs stats/runs export-
tracking/bands 8/fab 9/bench 5 的 _emit 缺省 json_output=True 路线）——后者
``--json`` 为归一兼容旗标：接受但两形态同输出（缺省路径逐字节不变铁纪律
优先于纯切换形态，避免"缺省变空输出"回归）。
批C 86 件同两形态分型：39 件兼容位（缺省即 JSON 直出/信封）+ 47 件真切换
（缺省 rich 逐字节不动）；campaign plan/event、template-spec draft 的失败
面自始即 _emit 信封（json_output 缺省 True）——该三处缺省路径逐字节不动，
--json 只切换成功面（W6-B bytecmp 实测抓出并修正的回归点）。

缺省路径逐字节不变：runs/w2_phase2/w2c/_bytecmp.py 工作树 vs git HEAD
worktree 双跑比对 17 用例全等（12 命令，含成功+失败路径），结果快照
bytecmp_results.json（本测试不依赖该工件，离线自洽）；W6-B 批 20 用例
（18 命令，含批 C 新面成功+失败路径）同法全等，快照
runs/w6_phase6/w6b/bytecmp_results.json（本测试不依赖该工件，离线自洽）。
"""

from __future__ import annotations

import inspect
import json
import sqlite3
import sys
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

import typer

from rfauto.cli.main import app as root_app

# ── 批席位命令名单（规格 §VI-5 批A 11 + 批B 23，逐字节=SPECS 原文） ──────────
BATCH_A = [
    "run", "tune", "sweep", "validate", "refine", "replay", "report",
    "datasets query", "runs compare", "runs stats", "runs export-tracking",
]
BATCH_B = [
    "bands env-delta-t", "bands env-find", "bands env-get", "bands env-list",
    "bands env-points", "bands env-uq-axis", "bands find", "bands get",
    "bands spec-bounds",
    "fab audit", "fab catalog", "fab draw", "fab export", "fab go",
    "fab pack", "fab pipeline", "fab rules", "fab snapshot",
    "bench agentbench", "bench consistency", "bench goldset", "bench level2",
    "bench prompt-regression",
]
W2C_TARGETS = BATCH_A + BATCH_B

# 棘轮门值（规格预声明：批A 后 ≤110、批B 后 ≤87；基线 2026-10-05 实测 121；
# 批C（W6-B 席 2026-10-06）后全树仅剩结构性豁免 ui → 收紧到 1（只降不升）
RATCHET_BATCH_A = 110
RATCHET_BATCH_B = 1

# 批C（W6-B）结构性豁免清单（与 runs/w6_phase6/w6b/REPORT.md §豁免清单同账）：
# ui=阻塞式 uvicorn serve（人工核验台长驻进程），无单发 JSON 输出面。
W6B_EXEMPT = ["ui"]

# 批C 席位命令名单（86 件=探针 87 − 豁免 ui，逐条=SPECS §VI-5 批C 余量）
W6B_TARGETS = [
    "agent apply", "agent propose", "aging report", "aging simulate",
    "aging verdict", "audit", "cache clear", "campaign event", "campaign list",
    "campaign plan", "certify", "chat", "constraints check", "correlate",
    "datasets annotate", "datasets coverage", "datasets discover-workdir",
    "datasets export-hf", "datasets import-workdir", "datasets materialize",
    "datasets visibility", "doctor", "electrothermal", "export-report-pdf",
    "farfield list", "farfield view", "firmware beam", "firmware dpd",
    "firmware varactor", "hfss-import", "inbox", "jobs cancel", "jobs status",
    "kicad drc", "kicad extract", "link", "models docs", "models list",
    "nfc evaluate", "nfc q", "nfc synth", "nfmeas ffs-info", "nfmeas nf2ff",
    "p0", "parasitic", "pdn analyze", "pdn gate", "pdn select", "port-gate",
    "preflight gates", "preflight run", "profile run", "profile status",
    "rag explain", "rag index", "rag query", "rationale search",
    "recipe migrate", "recipe skill", "repro", "sar report", "sensitivity",
    "si mixed", "si report", "simci", "solid-import", "solvers add",
    "solvers list", "solvers qucsator-mline", "solvers viz", "stats cpk",
    "stats guardband", "stats weibull", "study inject", "surrogate analyze",
    "surrogate uq", "template-spec draft", "tolerance", "topology",
    "tuning-report", "uq design-center",
    "uq robustness", "uq temp-zone", "uq yield-at", "vna-replay", "warm-start",
]


# ── 探针（内联自 sn_platform_deepen/_json_cov.py 同一逻辑，禁 runs/ 依赖） ───
def _walk(a: typer.Typer, prefix: str = "") -> dict[str, bool]:
    """全 CLI 树叶命令 → 是否带 --json 旗标（参数名含 json 即计，探针原口径）。"""
    out: dict[str, bool] = {}
    for info in a.registered_commands:
        cb = info.callback
        name = info.name or cb.__name__.replace("_", "-")
        full = (prefix + " " + name).strip() if prefix else name
        sig = inspect.signature(cb)
        has_json = any("json" in (pname or "") for pname in sig.parameters)
        out[full] = has_json
    for g in a.registered_groups:
        inst = getattr(g, "typer_instance", None) or g
        if not isinstance(inst, typer.Typer):
            inst = getattr(inst, "typer_instance", None)
        if inst is None:
            continue
        out.update(_walk(inst, (prefix + " " + g.name).strip() if prefix else g.name))
    return out


def _missing_json() -> list[str]:
    leaves = _walk(root_app)
    return sorted(name for name, has in leaves.items() if not has)


class TestJsonCoverageRatchet:
    """判据1：WITHOUT_JSON 棘轮（防回潮；新命令无 --json 即红）。"""

    def test_batch_a_ratchet_110(self):
        missing = _missing_json()
        assert len(missing) <= RATCHET_BATCH_A, (
            f"WITHOUT_JSON={len(missing)} > 批A 棘轮 {RATCHET_BATCH_A}：{missing}")

    def test_batch_b_ratchet_1(self):
        missing = _missing_json()
        assert len(missing) <= RATCHET_BATCH_B, (
            f"WITHOUT_JSON={len(missing)} > 批C 收紧棘轮 {RATCHET_BATCH_B}：{missing}")

    def test_w6b_exempt_exactly(self):
        """批C 后缺旗标集合=结构性豁免清单（并发席新增无 --json 命令即红=规格钉面）。"""
        missing = _missing_json()
        assert missing == W6B_EXEMPT, (
            f"缺 --json 集合 {missing} ≠ 豁免清单 {W6B_EXEMPT}"
            "（新命令必须带 --json；豁免须先入 W6B_EXEMPT 并在 REPORT.md 记因）")

    def test_w2c_34_targets_all_have_json(self):
        leaves = _walk(root_app)
        no_json = [t for t in W2C_TARGETS if not leaves.get(t)]
        assert not no_json, f"批席位 34 件存在缺 --json：{no_json}"

    def test_w6b_86_targets_all_have_json(self):
        leaves = _walk(root_app)
        no_json = [t for t in W6B_TARGETS if not leaves.get(t)]
        assert not no_json, f"批C 86 件存在缺 --json：{no_json}"

    def test_w6b_targets_no_overlap(self):
        """批C 名单与批A/B 零交叠（清单卫生；全树叶数完备性归共享计数面，不在此钉）。"""
        assert not (set(W2C_TARGETS) & set(W6B_TARGETS))

    # CLI 计数零变（判据3）不设绝对数断言：并发席位在同一工作树在制（本批
    # 会话内实测 221→224→226 漂移，均他轨新增命令），绝对数锚由共享面
    # test_check_numbers/test_cli 在合流时权威收口；本席零增删由 git diff
    # 核验（REPORT.md 记录：7 文件 diff 零 @command/add_typer 增删）。


# ── 冒烟基建 ──────────────────────────────────────────────────────────────────

RECIPE = {
    "model": "wilkinson_power_divider",
    "schema_version": 1,
    "params": {"arm_len_mm": {"value": 20.5, "unit": "mm"}},
    "setup": {"freq_range_ghz": [1.5, 3.5], "points": 11},
    "objectives": [
        {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15},
    ],
    # tune/sweep/refine 需可优化参数（optimization.params 或 params.bounds）
    "optimization": {
        "params": {"arm_len_mm": {"low": 18.0, "high": 23.0}},
    },
}


@pytest.fixture(autouse=True)
def _isolated_runs(tmp_path, monkeypatch):
    """chdir + 临时 optuna storage + 关缓存（#144：优化循环类测试必须隔离）。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RFAUTO_CACHE", "off")
    db_dir = tmp_path / "runs" / ".optuna"
    db_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "rfauto.optimization.optimizer.get_storage_path",
        lambda: f"sqlite:///{(db_dir / 'optuna.db').as_posix()}",
    )


@pytest.fixture
def recipe_path(tmp_path):
    p = tmp_path / "recipe.yaml"
    p.write_text(yaml.safe_dump(RECIPE), encoding="utf-8")
    return p


def _invoke(args: list[str]):
    return CliRunner().invoke(root_app, args)


def _envelope(result) -> dict:
    """--json 模式输出必须可解析为 JSON 信封（fab warn 行走 stderr 前置容许）。"""
    out = result.output
    assert out.strip(), f"空输出（exit={result.exit_code}）"
    return json.loads(out[out.index("{"):])


def _assert_success(result) -> dict:
    assert result.exit_code == 0, f"exit={result.exit_code}\n{result.output[:400]}"
    payload = _envelope(result)
    assert payload.get("ok") is True, f"成功信封 ok 非 True：{list(payload)[:8]}"
    return payload


def _assert_failure(result) -> dict:
    assert result.exit_code == 1, f"exit={result.exit_code}\n{result.output[:400]}"
    payload = _envelope(result)
    assert payload.get("ok") is False, "失败信封 ok 非 False"
    # 同构承载三形态：errors 列表（_emit 契约）/ error 单键（bands 族服务）/
    # reasons 列表（bench 门族 FAIL 信封，AD-1 口径）
    assert (payload.get("errors") or payload.get("error")
            or payload.get("reasons")), "失败信封须带 errors/error/reasons"
    return payload


# ══ 批A（11 件）：门禁/CI 主消费面 ═══════════════════════════════════════════


class TestBatchA:
    def test_run_json_success_and_failure(self, recipe_path, monkeypatch):
        """run --json：正常路径成功/失败信封同构（服务注入，#139 不真跑）。"""
        monkeypatch.setattr(
            "rfauto.service.api.run_once",
            lambda recipe, adapter_name="fake": {
                "ok": True, "run_id": "w2c_r1", "run_dir": "runs/w2c_r1",
                "cost": 0.12, "metrics": {"s11_db": -12.3}})
        r = _invoke(["run", str(recipe_path), "--json"])
        payload = _assert_success(r)
        assert payload["run_id"] == "w2c_r1"

        monkeypatch.setattr(
            "rfauto.service.api.run_once",
            lambda recipe, adapter_name="fake": {"ok": False, "errors": ["注入失败"]})
        r = _invoke(["run", str(recipe_path), "--json"])
        payload = _assert_failure(r)
        assert "注入失败" in payload["errors"][0]

    def test_run_json_dryrun_real_success_and_failure(self, recipe_path):
        """run --json --dry-run：真实校验面（零求解零 runs/ 写）。"""
        _assert_success(_invoke(["run", str(recipe_path), "--dry-run", "--json"]))
        _assert_failure(_invoke(["run", "no_such_recipe.yaml", "--dry-run", "--json"]))

    def test_run_json_detach_envelope(self, recipe_path, monkeypatch):
        """run --json --detach：旗标组合正交（W1-D 面上叠加信封出口）。"""
        monkeypatch.setattr(
            "rfauto.service.api.run_once_async",
            lambda recipe, adapter_name="fake": {
                "ok": True, "job_id": "job_w2c", "state": "running"})
        payload = _assert_success(_invoke(["run", str(recipe_path), "--detach", "--json"]))
        assert payload["job_id"] == "job_w2c"

    def test_tune_json_dryrun_dual_real(self, recipe_path):
        """tune --json --dry-run：真实校验（成功+失败信封；不执行优化）。"""
        _assert_success(_invoke(["tune", str(recipe_path), "--dry-run", "--json"]))
        payload = _assert_failure(_invoke(["tune", "no_such.yaml", "--dry-run", "--json"]))
        assert payload["errors"]

    def test_tune_json_single_path_envelope(self, recipe_path, monkeypatch):
        """tune --json 单目标路径：start_tune 注入（成功+失败信封）。"""
        monkeypatch.setattr(
            "rfauto.service.api.start_tune",
            lambda **kw: {"ok": True, "study_name": "w2c_s", "run_id": "w2c_t1",
                          "trials_total": 2, "trials_completed": 2,
                          "trials_pruned": 0, "best_cost": 0.3,
                          "best_params": {"arm_len_mm": 20.5}, "elapsed_s": 0.01})
        _assert_success(_invoke(["tune", str(recipe_path), "--max-trials", "2", "--json"]))

        monkeypatch.setattr(
            "rfauto.service.api.start_tune",
            lambda **kw: {"ok": False, "errors": ["注入失败"]})
        _assert_failure(_invoke(["tune", str(recipe_path), "--json"]))

    def test_tune_json_watch_orthogonal_no_prose(self, recipe_path, monkeypatch):
        """--json × --watch 正交：信封模式下不挂 Live 播报（stdout 只留信封）。"""
        monkeypatch.setattr(
            "rfauto.service.api.start_tune",
            lambda on_trial=None, **kw: {"ok": True, "study_name": "s",
                                         "trials_total": 1, "trials_completed": 1,
                                         "trials_pruned": 0, "best_cost": 0.5})
        r = _invoke(["tune", str(recipe_path), "--watch", "--max-trials", "1", "--json"])
        _assert_success(r)
        assert "trial " not in r.output.split("{")[0]  # 信封前零播报散文

    def test_tune_json_detach_rejection_envelope(self, recipe_path):
        """--json × --detach × --multi：组合拒绝在 --json 下也是信封（exit 1）。"""
        _assert_failure(_invoke(["tune", str(recipe_path), "--detach", "--multi", "--json"]))

    def test_sweep_json_dual_real(self, recipe_path):
        """sweep --json：真实 fake 扫描（小预算秒级）+ 真实失败面。"""
        _assert_success(_invoke([
            "sweep", str(recipe_path), "--method", "grid",
            "--coarse", "3", "--max-combos", "3", "--json"]))
        payload = _assert_failure(_invoke(["sweep", "no_such.yaml", "--json"]))
        assert payload["errors"]

    def test_validate_json_dual_real(self, recipe_path):
        """validate --json：真实校验双路径（最轻门禁消费面）。"""
        _assert_success(_invoke(["validate", str(recipe_path), "--json"]))
        _assert_failure(_invoke(["validate", "no_such.yaml", "--json"]))

    def test_refine_json_failure_real(self, recipe_path):
        _assert_failure(_invoke(["refine", "no_such_run", str(recipe_path), "--json"]))

    def test_refine_json_success_real_one_trial(self, recipe_path):
        """refine --json 真实续调： fabricated meta + 1 trial fake（秒级）。"""
        meta_dir = Path("runs") / "w2c_src"
        meta_dir.mkdir(parents=True, exist_ok=True)
        (meta_dir / "meta.json").write_text(json.dumps(
            {"run_id": "w2c_src", "study_name": "w2c_refine_study"}), encoding="utf-8")
        payload = _assert_success(_invoke(
            ["refine", "w2c_src", str(recipe_path), "--max-trials", "1", "--json"]))
        assert payload.get("ok") is True

    def test_replay_json_failure_real(self):
        _assert_failure(_invoke(["replay", "no_such_run", "--json"]))

    def test_replay_json_success_real_fake_rerun(self, recipe_path):
        """replay --json：fabricated run 目录（meta+快照）→ 真实 fake 重跑。"""
        run_dir = Path("runs") / "w2c_src"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "meta.json").write_text(json.dumps(
            {"run_id": "w2c_src", "adapter": "fake", "schema_version": 1}),
            encoding="utf-8")
        (run_dir / "recipe.snapshot.yaml").write_text(
            yaml.safe_dump(RECIPE), encoding="utf-8")
        payload = _assert_success(_invoke(["replay", "w2c_src", "--json"]))
        assert payload.get("replay_run_id")

    def test_report_json_dual_real(self, tmp_path):
        """report --json：fabricated metrics 真实重建 + 缺 run 失败面。"""
        results = Path("runs") / "w2c_rep" / "results"
        results.mkdir(parents=True, exist_ok=True)
        (results / "metrics.json").write_text(json.dumps(
            {"metrics": {"s11_db": -12.5}, "cost": 0.2}), encoding="utf-8")
        payload = _assert_success(_invoke(["report", "w2c_rep", "--json"]))
        assert payload.get("report")
        _assert_failure(_invoke(["report", "no_such_run", "--json"]))

    def test_datasets_query_json_dual(self, runs_env):
        """datasets query --json：runs_env 物化后真实查询 + 缺数据集失败面。"""
        pytest.importorskip("duckdb", reason="需要 dataset extra（duckdb）")
        pytest.importorskip("pyarrow", reason="需要 dataset extra（pyarrow）")
        from tests.unit._dataset_service_helpers import _materialize_all

        assert _materialize_all("w2c_ds")["ok"]
        payload = _assert_success(_invoke(["datasets", "query", "w2c_ds", "--json"]))
        assert payload.get("n_rows", 0) >= 1
        _assert_failure(_invoke(["datasets", "query", "no_such_ds", "--json"]))

    def test_runs_compare_json_dual_real(self, tmp_path):
        """runs compare --json：fabricated 双 run 指标真实对比 + 失败面。"""
        for rid, v in (("ra", -10.0), ("rb", -20.0)):
            d = Path("runs") / rid / "results"
            d.mkdir(parents=True, exist_ok=True)
            (d / "metrics.json").write_text(json.dumps(
                {"metrics": {"s11_db": v}, "cost": 0.1}), encoding="utf-8")
        payload = _assert_success(_invoke(["runs", "compare", "ra", "rb", "--json"]))
        assert payload["data"]["run_a"] == "ra"
        _assert_failure(_invoke(["runs", "compare", "no_a", "no_b", "--json"]))

    def test_runs_compare_json_provenance_failure_envelope(self):
        """runs compare --json --provenance：失败也信封（缺省 rich 红字不变）。"""
        _assert_failure(_invoke(
            ["runs", "compare", "no_a", "no_b", "--provenance", "--json"]))

    def test_runs_stats_json_dual_real(self, tmp_path):
        """runs stats --json（归一兼容位）：缺省即信封，双路径同构。"""
        db = tmp_path / "reg.sqlite"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE runs (run_id TEXT, model TEXT, adapter TEXT,"
                     " status TEXT, timestamp TEXT, metrics TEXT)")
        conn.execute("INSERT INTO runs VALUES ('r1','mline','fake','done',"
                     "'2026-10-05T00:00:00','{}')")
        conn.commit()
        conn.close()
        payload = _assert_success(_invoke(["runs", "stats", "--db", str(db), "--json"]))
        assert payload.get("total") == 1
        # 无 --json 形态同输出（兼容旗标语义），失败面同构
        assert json.loads(_invoke(["runs", "stats", "--db", str(db)]).output)["total"] == 1
        _assert_failure(_invoke(["runs", "stats", "--db",
                                 str(tmp_path / "missing.sqlite"), "--json"]))

    def test_runs_export_tracking_json_dual_real(self, tmp_path):
        """runs export-tracking --json（归一兼容位）：真实导出 + 失败面。"""
        run_dir = Path("runs") / "w2c_exp"
        (run_dir / "trials").mkdir(parents=True, exist_ok=True)
        (run_dir / "meta.json").write_text(json.dumps(
            {"run_id": "w2c_exp", "model": "mline", "adapter": "fake"}),
            encoding="utf-8")
        (run_dir / "trials" / "trial_0.json").write_text(json.dumps({
            "trial_number": 0, "params": {"arm_len_mm": 20.5},
            "metrics": {"s11_db": -12.0}, "cost": 0.1,
            "cache_hit": False, "feasible": True}), encoding="utf-8")
        out_dir = tmp_path / "tracking"
        payload = _assert_success(_invoke([
            "runs", "export-tracking", "w2c_exp",
            "--out-dir", str(out_dir), "--json"]))
        assert payload.get("n_trials", 0) >= 1
        _assert_failure(_invoke(["runs", "export-tracking", "no_such_run", "--json"]))


# ══ 批B：bands 8（D9 注册表只读面；bands list 自始有 --json 不在本批） ═══════


class TestBatchBBands:
    def test_bands_get_json_dual(self):
        _assert_success(_invoke(["bands", "get", "gpp_n78", "--json"]))
        _assert_failure(_invoke(["bands", "get", "no_such_band", "--json"]))

    def test_bands_find_json_success(self):
        payload = _assert_success(_invoke(["bands", "find", "2.45", "--json"]))
        assert payload.get("ok") is True  # 覆盖查询无失败模式（空结果如实 ok=True）

    def test_bands_spec_bounds_json_dual(self):
        _assert_success(_invoke(["bands", "spec-bounds", "gpp_n78", "--json"]))
        _assert_failure(_invoke(["bands", "spec-bounds", "no_such_band", "--json"]))

    def test_bands_env_list_json_success(self):
        payload = _assert_success(_invoke(["bands", "env-list", "--json"]))
        assert payload.get("count", 0) >= 1

    def test_bands_env_get_json_dual(self):
        _assert_success(_invoke(["bands", "env-get", "aec_q100_grade1", "--json"]))
        _assert_failure(_invoke(["bands", "env-get", "no_such_env", "--json"]))

    def test_bands_env_find_json_success(self):
        _assert_success(_invoke(["bands", "env-find", "25.0", "--json"]))

    def test_bands_env_delta_t_json_dual(self):
        _assert_success(_invoke(["bands", "env-delta-t", "aec_q100_grade1", "--json"]))
        _assert_failure(_invoke(["bands", "env-delta-t", "no_such_env", "--json"]))

    def test_bands_env_uq_axis_json_dual(self):
        _assert_success(_invoke(["bands", "env-uq-axis", "aec_q100_grade1", "--json"]))
        _assert_failure(_invoke(["bands", "env-uq-axis", "no_such_env", "--json"]))

    def test_bands_env_points_json_dual(self):
        _assert_success(_invoke(["bands", "env-points", "aec_q100_grade1", "--json"]))
        _assert_failure(_invoke(["bands", "env-points", "no_such_env", "--json"]))


# ══ 批B：fab 9（自始 JSON 信封直出；离线链真实双路径 + 服务注入 #139） ═══════


def _write_vars(tmp_path: Path) -> Path:
    p = tmp_path / "vars.json"
    p.write_text(json.dumps({
        "part_id": "w2c_part", "rev": "A",
        "variables": {"h_mm": "2.0", "w_mm": "30.0", "l_mm": "40.0"}}),
        encoding="utf-8")
    return p


def _write_dims(tmp_path: Path) -> Path:
    """经真实 snapshot 产出 dims.json（尺寸真源链，不手写_dims）。"""
    from rfauto.service.fab_export_service import fab_snapshot

    vars_p = _write_vars(tmp_path)
    dims_p = tmp_path / "dims.json"
    r = fab_snapshot(str(vars_p), str(dims_p))
    assert r.get("ok"), r.get("errors")
    return dims_p


class TestBatchBFab:
    def test_fab_go_json_success_real_offline_chain(self, tmp_path):
        """fab go --json：--vars 离线全链（snapshot→draw→audit→pack）真实成功。"""
        payload = _assert_success(_invoke([
            "fab", "go", "--vars", str(_write_vars(tmp_path)),
            "--out", str(tmp_path / "go_out"), "--json"]))
        assert payload.get("ok") is True

    def test_fab_go_json_missing_args_envelope(self):
        """fab go --json 无 --vars/--project：入参缺失也信封（exit 2 语义保持）。"""
        r = _invoke(["fab", "go", "--json"])
        assert r.exit_code == 2
        payload = _envelope(r)
        assert payload.get("ok") is False and payload.get("errors")

    def test_fab_pipeline_json_success_real(self, tmp_path):
        """fab pipeline --json：离线端到端轻量链真实成功（vars→dims→DXF→审计→打包）。"""
        _assert_success(_invoke([
            "fab", "pipeline", "--vars", str(_write_vars(tmp_path)),
            "--work", str(tmp_path / "work"),
            "--out", str(tmp_path / "pipe_out"), "--json"]))
    # pipeline 失败路径：服务层缺文件抛 FileNotFoundError（非信封，服务层零改
    # 前提下的既有形态）——失败信封经注入钉 CLI 接线：

    def test_fab_pipeline_json_failure_envelope(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "rfauto.service.fab_export_service.fab_pipeline",
            lambda *a, **kw: {"ok": False, "errors": ["注入失败"]})
        _assert_failure(_invoke([
            "fab", "pipeline", "--vars", str(tmp_path / "nope.json"),
            "--work", str(tmp_path / "w"), "--json"]))

    def test_fab_snapshot_json_success_real(self, tmp_path):
        _assert_success(_invoke([
            "fab", "snapshot", "--vars", str(_write_vars(tmp_path)),
            "--out", str(tmp_path / "dims.json"), "--json"]))

    def test_fab_snapshot_json_failure_envelope(self, tmp_path, monkeypatch):
        # 服务层缺文件抛裸 FileNotFoundError（既有形态，服务层零改）；信封
        # 失败路径经注入钉 CLI 接线（#139）
        monkeypatch.setattr(
            "rfauto.service.fab_export_service.fab_snapshot",
            lambda *a, **kw: {"ok": False, "errors": ["注入失败"]})
        _assert_failure(_invoke([
            "fab", "snapshot", "--vars", str(tmp_path / "nope.json"),
            "--out", str(tmp_path / "d.json"), "--json"]))

    def test_fab_draw_json_success_real(self, tmp_path):
        _assert_success(_invoke([
            "fab", "draw", "--dims", str(_write_dims(tmp_path)),
            "--out", str(tmp_path / "w2c.dxf"), "--json"]))

    def test_fab_draw_json_failure_envelope(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "rfauto.service.fab_export_service.fab_draw",
            lambda *a, **kw: {"ok": False, "errors": ["注入失败"]})
        _assert_failure(_invoke([
            "fab", "draw", "--dims", str(tmp_path / "nope.json"),
            "--out", str(tmp_path / "x.dxf"), "--json"]))

    def test_fab_audit_json_dual_real(self, tmp_path):
        """fab audit --json：真实 dims 包成功 + 缺包失败面（服务原生信封）。"""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "dims.json").write_text(
            _write_dims(tmp_path).read_text(encoding="utf-8"), encoding="utf-8")
        _assert_success(_invoke(["fab", "audit", "--package", str(pkg), "--json"]))
        _assert_failure(_invoke(["fab", "audit", "--package",
                                 str(tmp_path / "no_pkg"), "--json"]))

    def test_fab_pack_json_dual_real(self, tmp_path):
        """fab pack --json：真实组装成功 + --force-fail 审计 FAIL 信封（exit 1）。"""
        dims = _write_dims(tmp_path)
        _assert_success(_invoke([
            "fab", "pack", "--dims", str(dims),
            "--out", str(tmp_path / "pack_out"), "--json"]))
        r = _invoke(["fab", "pack", "--dims", str(dims),
                     "--out", str(tmp_path / "pack_ff"), "--force-fail", "--json"])
        assert r.exit_code == 1
        assert _envelope(r).get("ok") is False

    def test_fab_rules_json_success(self):
        """fab rules --json：纯静态规则库展示（无离线失败模式——坏文件回退缺省，
        信封 ok=True 如实；双路径由成功信封+兼容等价钉覆盖）。"""
        _assert_success(_invoke(["fab", "rules", "--json"]))

    def test_fab_catalog_json_success(self):
        """fab catalog --json：纯静态标准库（零入参零失败模式，同上口径）。"""
        _assert_success(_invoke(["fab", "catalog", "--json"]))

    def test_fab_export_json_dual_envelope(self, tmp_path, monkeypatch):
        """fab export --json：真机面（AEDT 启动）禁入测试——双路径注入钉接线
        （#139；真机发射面由 real_edt 体系另行覆盖）。"""
        monkeypatch.setattr(
            "rfauto.service.fab_export_service.fab_export_geometry",
            lambda *a, **kw: {"ok": True, "out_dir": str(tmp_path / "x")})
        _assert_success(_invoke([
            "fab", "export", "--out", str(tmp_path / "x"), "--json"]))

        monkeypatch.setattr(
            "rfauto.service.fab_export_service.fab_export_geometry",
            lambda *a, **kw: {"ok": False, "needs": ["aedt"], "errors": ["缺 AEDT"]})
        r = _invoke(["fab", "export", "--out", str(tmp_path / "y"), "--json"])
        assert r.exit_code == 2  # needs → 2（环境缺失语义保持）
        assert _envelope(r).get("ok") is False


# ══ 批B：bench 5（门自洽正控——真实离线双路径：PASS=0 / FAIL=1 信封） ════════


class TestBatchBBench:
    def test_bench_goldset_json_dual_real(self):
        """bench goldset --json：缺省参考回放 PASS + 阈值收紧 FAIL 同构。"""
        _assert_success(_invoke(["bench", "goldset", "--json"]))
        payload = _assert_failure(_invoke(["bench", "goldset", "--min-tsa", "2.0",
                                           "--json"]))
        assert payload.get("gate") == "FAIL"

    def test_bench_agentbench_json_dual_real(self):
        _assert_success(_invoke(["bench", "agentbench", "--json"]))
        payload = _assert_failure(_invoke(["bench", "agentbench",
                                           "--require-private", "--json"]))
        assert payload.get("gate") == "FAIL"

    def test_bench_level2_json_dual_real(self):
        """bench level2 --json：缺省十句确定性参考链（零 LLM 零网络，秒级）。"""
        _assert_success(_invoke(["bench", "level2", "--json"]))
        payload = _assert_failure(_invoke(["bench", "level2", "--min-success", "99",
                                           "--json"]))
        assert payload.get("gate") == "FAIL"

    def test_bench_prompt_regression_json_dual_real(self, tmp_path):
        """bench prompt-regression --json：双 prompt 文件离线差分 + 同指纹 FAIL。"""
        pa = tmp_path / "prompt_a.txt"
        pb = tmp_path / "prompt_b.txt"
        pc = tmp_path / "prompt_a2.txt"
        pa.write_text("prompt A", encoding="utf-8")
        pb.write_text("prompt B", encoding="utf-8")
        pc.write_text("prompt A", encoding="utf-8")  # 与 A 同指纹（sha256 一致）
        base = ["bench", "prompt-regression", "--prompt-a", str(pa),
                "--prompt-b", str(pb), "--no-persist", "--json"]
        _assert_success(_invoke(base))
        # 防空转判据：两版 prompt 指纹相同=无差可回归 → FAIL（服务预声明口径）
        payload = _assert_failure(_invoke([
            "bench", "prompt-regression", "--prompt-a", str(pa),
            "--prompt-b", str(pc), "--no-persist", "--json"]))
        assert payload.get("gate") == "FAIL"

    def test_bench_consistency_json_dual_real(self, tmp_path):
        """bench consistency --json：fabricated trials 真实 pass^k（PASS/FAIL）。"""

        def task(tid: str) -> dict:
            return {"id": tid, "family": "template_render", "level": 1,
                    "prompt": f"任务 {tid}",
                    "expected": {"calls": [{"tool": "list_solvers", "args": {}}],
                                 "artifacts": ["s_params"]}}

        def trial(tid: str, ok: bool) -> dict:
            return {"id": tid,
                    "trajectory": [{"tool": "list_solvers", "args": {}}],
                    "artifacts": ["s_params"] if ok else []}

        set_path = tmp_path / "bench.yaml"
        set_path.write_text(yaml.safe_dump(
            {"version": 1, "tasks": [task("t1")]}, allow_unicode=True),
            encoding="utf-8")
        trials_path = tmp_path / "trials.json"
        trials_path.write_text(json.dumps([
            trial("t1", True), trial("t1", True), trial("t1", False),
        ]), encoding="utf-8")
        base = ["bench", "consistency", "--trials", str(trials_path),
                "--public-set", str(set_path), "--json"]
        # 3 trial 2 pass：pass^2 = C(2,2)/C(3,2) = 1/3 → 缺省门 PASS、
        # min-pass-hat-k=0.9 时 FAIL（同 test_pass_at_k CLI 口径）
        _assert_success(_invoke([*base, "--k", "2"]))
        payload = _assert_failure(_invoke([*base, "--k", "2",
                                           "--min-pass-hat-k", "0.9"]))
        assert payload.get("gate") == "FAIL"


# ══ 批C（W6-B，86 件机械批）：参数化 --json 双路径冒烟 ═══════════════════════
# 表结构：(case_id, argv, inject, payload, fail, keys)
#   argv    成功路径参数（不含 --json；占位符由 _w6b_fixtures 展开）
#   inject  服务注入目标 "module.attr"（#139：payload 重/真机面只钉 CLI 接线）
#   payload 注入成功信封；fail="INJECT" 时同一目标改注失败信封
#   fail    None=无离线失败面（成功冒烟+兼容等价，批B fab rules 先例）|
#           "INJECT" | ["args", ...]（真实 argv 失败路径，+--json 须信封 exit 1）
#   keys    成功信封须含的键（() = 仅要求可解析）
_W6B_FAIL_PAYLOAD = {"ok": False, "errors": ["注入失败"]}

W6B_SMOKE = [
    # ── bands_uq 域（10）──
    ("campaign-plan", ["campaign", "plan", "@recipe@"], None, None,
     ["campaign", "plan", "@missing@"], ("ok", "stages")),
    ("campaign-list", ["campaign", "list"], None, None, None, ("ok", "campaigns")),
    ("farfield-list", ["farfield", "list"], None, None, None, ("ok", "runs")),
    ("farfield-view", ["farfield", "view", "@runid@"],
     "rfauto.service.nf2ff_service.farfield_view",
     {"ok": True, "run_id": "w6b_run", "dmax_db": 5.0},
     ["farfield", "view", "no_such_run"], ("ok",)),
    ("template-spec-draft", ["template-spec", "draft", "mline"], None, None,
     ["template-spec", "draft", "no_such_tpl"], ("ok",)),
    ("uq-yield-at", ["uq", "yield-at", "@samples@", "--tol", "arm_len_mm=0.1",
                     "--at", "arm_len_mm=20.0", "--n", "200"],
     "rfauto.service.uq_service.surrogate_yield_at",
     {"ok": True, "yield_rate": 0.9, "nominal_params": {}}, "INJECT", ("ok",)),
    ("uq-design-center", ["uq", "design-center", "@samples@", "--tol",
                          "arm_len_mm=0.1", "--n-mc", "200"],
     "rfauto.service.uq_service.yield_design_center",
     {"ok": True, "best_params": {}}, "INJECT", ("ok",)),
    ("uq-temp-zone", ["uq", "temp-zone", "@samples@", "aec_q100_grade1",
                      "--tol", "arm_len_mm=0.1", "--n", "200"],
     "rfauto.service.uq_service.temperature_zone_yield",
     {"ok": True, "yield_rate": 0.9}, "INJECT", ("ok",)),
    ("uq-robustness", ["uq", "robustness", "@samples@", "--spec",
                       "s11_db_max_in_band,le,-5", "--n-mc", "200"],
     "rfauto.service.robustness_service.robustness_report",
     {"ok": True, "yield_rate": 0.95}, "INJECT", ("ok",)),
    # ── jobs 域（5）──
    ("jobs-status", ["jobs", "status"], None, None, None, ("ok", "runs")),
    ("jobs-cancel", ["jobs", "cancel", "@jobid@"],
     "rfauto.service.job_registry.get_job_registry", "REG",
     ["jobs", "cancel", "no_such_job"], ("ok", "state")),
    ("cache-clear", ["cache", "clear"], None, None, None, ("ok", "removed")),
    ("link", ["link", "@runid@"], "rfauto.service.api.run_link",
     {"ok": True, "snp_path": "x.s2p", "rounds_completed": 2,
      "summary": {"results": []}}, "INJECT", ("ok",)),
    ("export-report-pdf", ["export-report-pdf", "@runid@"],
     "GETMETRICS2", None, ["export-report-pdf", "no_such_run"], ("ok",)),
    # ── pdn/aging 域（6，payload JSON 面注入）──
    ("pdn-analyze", ["pdn", "analyze", "@payload@"],
     "rfauto.service.pdn_service.pdn_analyze",
     {"ok": True, "n_peaks": 1}, "INJECT", ("ok",)),
    ("pdn-select", ["pdn", "select", "@payload@"],
     "rfauto.service.pdn_service.pdn_select",
     {"ok": True, "picked": []}, "INJECT", ("ok",)),
    ("pdn-gate", ["pdn", "gate", "@payload@"],
     "rfauto.service.pdn_service.pdn_gate",
     {"ok": True, "verdict": "PASS"}, "INJECT", ("ok",)),
    ("aging-simulate", ["aging", "simulate", "@payload@"],
     "rfauto.service.aging_service.aging_simulate",
     {"ok": True, "detune_pct": 0.1}, "INJECT", ("ok",)),
    ("aging-verdict", ["aging", "verdict", "@payload@"],
     "rfauto.service.aging_service.aging_eol_verdict",
     {"ok": True, "verdict": "PASS"}, "INJECT", ("ok",)),
    ("aging-report", ["aging", "report", "@payload@"],
     "rfauto.service.aging_service.aging_report",
     {"ok": True, "sections": 4}, "INJECT", ("ok",)),
    # ── chain/study 域（5）──
    ("p0", ["p0", "@recipe@"], "rfauto.service.api.run_p0_experiment",
     {"ok": True, "verdict": "PASS", "correlation": {"spearman_rho": 0.9},
      "cross_fidelity": {}, "elapsed_s": 0.1, "gate": "on"}, "INJECT", ("ok",)),
    ("sensitivity", ["sensitivity", "@recipe@", "--samples", "8"],
     "rfauto.service.api.run_sensitivity",
     {"ok": True, "method": "sobol", "n_samples": 8,
      "sensitivity": {"arm_len_mm": {"S1": 0.8, "ST": 0.9}}}, "INJECT", ("ok",)),
    ("tuning-report", ["tuning-report", "@runid@"],
     "rfauto.service.api.generate_enhanced_report",
     {"ok": True, "report": "x.md", "report_text": "ok"}, "INJECT", ("ok",)),
    ("audit", ["audit"], None, None, None, ("ok", "entries")),
    ("audit-quality", ["audit", "--quality"], None, None, None, ("ok",)),
    # ── lake 域（4）──
    ("constraints-check", ["constraints", "check", "@cfg@"], None, None,
     None, ("ok",)),
    ("certify", ["certify", "@samples@", "--param", "arm_len_mm=20.0"],
     "rfauto.service.certify_design.certify_design",
     {"ok": True, "verdict": "PASS"}, "INJECT", ("ok",)),
    ("solid-import", ["solid-import", "fake.stl"],
     "rfauto.service.solid_import_service.import_solid_payload",
     {"ok": True, "kind": "metal"}, ["solid-import", "missing.stl"], ("ok",)),
    ("port-gate", ["port-gate", "@payload@"],
     "rfauto.service.port_gate_service.port_gate_from_json",
     {"ok": True, "verdict": "PASS"}, "INJECT", ("ok",)),
    # ── surrogate/datasets 域（9）──
    ("surrogate-analyze", ["surrogate", "analyze", "--study", "@study@"],
     "rfauto.service.api.analyze_surrogate",
     {"ok": True, "data": {"n_samples": 8, "n_params": 1, "best_cost": 0.1,
                           "best_params": {}, "prediction_error": 0.01,
                           "param_importance": {}}},
     ["surrogate", "analyze"], ("ok",)),
    ("surrogate-uq", ["surrogate", "uq", "@samples@", "--tol",
                      "arm_len_mm=0.1", "--n", "200"],
     "rfauto.service.uq_service.surrogate_yield",
     {"ok": True, "yield_rate": 0.9}, "INJECT", ("ok",)),
    ("datasets-materialize", ["datasets", "materialize", "--name", "w6b_ds"],
     "rfauto.service.dataset_service.materialize_dataset",
     {"ok": True, "name": "w6b_ds", "n_points": 1, "n_rows": 1, "n_dup": 0,
      "dataset_dir": "runs/datasets/w6b_ds"},
     ["datasets", "materialize", "--name", "w6b_ds"], ("ok",)),
    ("datasets-discover-workdir", ["datasets", "discover-workdir",
                                   "--runs-root", "@runsroot@"], None, None,
     None, ("ok",)),
    ("datasets-import-workdir", ["datasets", "import-workdir", "--name",
                                 "w6b_iw"],
     "rfauto.service.dataset_service.import_workdir_runs",
     {"ok": True, "name": "w6b_iw", "n_points": 1, "n_rows": 1, "n_dup": 0,
      "n_candidates": 1, "n_curves": 1, "dataset_dir": "d"}, "INJECT", ("ok",)),
    ("datasets-coverage", ["datasets", "coverage", "w6b_ds"],
     "rfauto.service.dataset_insights.dataset_coverage",
     {"ok": True, "coverage": {}}, "INJECT", ("ok",)),
    ("datasets-annotate", ["datasets", "annotate", "w6b_ds"],
     "rfauto.service.dataset_insights.annotate_ground_truth",
     {"ok": True, "ground_truth": {}}, "INJECT", ("ok",)),
    ("datasets-visibility", ["datasets", "visibility", "w6b_ds", "public"],
     "rfauto.service.dataset_insights.set_dataset_visibility",
     {"ok": True, "visibility": "public"}, "INJECT", ("ok",)),
    ("datasets-export-hf", ["datasets", "export-hf", "w6b_ds"],
     "rfauto.service.dataset_insights.export_hf_dataset",
     {"ok": True, "hf_dir": "d", "files": []}, "INJECT", ("ok",)),
    # ── system 域（3）──
    ("doctor", ["doctor", "--extras"], None, None, None, ("summary",)),
    ("models-list", ["models", "list"], None, None,
     ["models", "list", "--schema", "no_such_model"], ("ok", "models")),
    ("models-docs", ["models", "docs", "mline"], None, None,
     ["models", "docs", "no_such_model"], ("ok",)),
    # ── scattered 域（8）──
    ("electrothermal", ["electrothermal", "@payload@"],
     "rfauto.service.electrothermal_service.run_wilkinson_electrothermal",
     {"ok": True, "dt_k": 1.0}, "INJECT", ("ok",)),
    ("parasitic", ["parasitic", "@payload@"],
     "rfauto.service.parasitic_service.extract_interconnect_rlc",
     {"ok": True, "stage": "done"}, "INJECT", ("ok",)),
    ("topology", ["topology", "--f0", "2.45", "--fbw", "0.08"], None, None,
     ["topology", "--f0", "2.45", "--fbw", "0.08",
      "--proposer", "no_such_proposer"], ("ok",)),
    ("vna-replay", ["vna-replay", "@s2p@"],
     "rfauto.service.api.vna_offline_replay",
     {"ok": True, "correlation": {"is_correlated": True}},
     "INJECT", ("ok",)),
    ("rationale-search", ["rationale", "search", "阻抗", "--runs-dir",
                          "@runsroot@"],
     "rfauto.service.rationale_memory.search_runs_rationale",
     {"ok": True, "hits": [], "n_entries": 0}, "INJECT", ("ok", "hits")),
    ("rag-index", ["rag", "index", "--docs", "@docsdir@", "--runs",
                   "@runsroot@"], None, None, None, ("ok",)),
    ("rag-query", ["rag", "query", "阻抗", "--docs", "@docsdir@", "--runs",
                   "@runsroot@"], None, None, None, ("ok",)),
    ("rag-explain", ["rag", "explain", "阻抗", "--docs", "@docsdir@", "--runs",
                     "@runsroot@"], None, None, None, ("ok",)),
    # ── agent/kicad 域（5）──
    ("hfss-import", ["hfss-import", "p.aedt"],
     "rfauto.service.v3_services.hfss_import_recipe",
     {"ok": True, "spec": {}, "recipe": {}}, "INJECT", ("ok",)),
    ("agent-propose", ["agent", "propose", "@recipe@"],
     "rfauto.service.api.agent_propose",
     {"ok": True, "token": "tok", "effective_params": {}}, "INJECT", ("ok",)),
    ("agent-apply", ["agent", "apply", "@recipe@", "--token", "tok"],
     "rfauto.service.api.agent_apply",
     {"ok": True, "run_id": "w6b_r", "metrics": {"s11_db": -12.0}},
     "INJECT", ("ok",)),
    ("kicad-drc", ["kicad", "drc", "board.kicad_pcb"],
     "rfauto.adapters.kicad_drc.run_drc_kicad", "DRC_OK",
     "DRC_FAIL", ("ok",)),
    ("kicad-extract", ["kicad", "extract", "board.kicad_pcb"],
     "rfauto.service.kicad_em_service.extract_pcb_facts",
     {"ok": True, "traces": [], "zones": [], "footprints": [],
      "board": {"layer_count": 2}}, "INJECT", ("ok",)),
    # ── report_mmt 域（8）──
    ("nfmeas-ffs-info", ["nfmeas", "ffs-info", "x.ffs"],
     "rfauto.service.nf_measurement_service.ffs_info",
     {"ok": True, "n_freqs": 1}, None, ("ok",)),
    ("nfmeas-nf2ff", ["nfmeas", "nf2ff", "@npz@"],
     "rfauto.core.nf_transform.planar_nf_to_farfield",
     {"theta_deg": [0.0], "phi_deg": [0.0], "pattern_db": [[0.0]],
      "window": "kaiser", "validity_max_deg": 80.0}, None, ()),
    ("nfc-evaluate", ["nfc", "evaluate", "square", "4", "10", "100", "100"],
     None, None, None, ()),
    ("nfc-synth", ["nfc", "synth", "400", "square", "4", "100", "100"],
     None, None, None, ()),
    ("nfc-q", ["nfc", "q", "13.56", "400", "2", "--m-nh", "10", "--l2-nh",
               "400", "--r2-ohm", "2"], None, None, None, ()),
    ("sar-report", ["sar", "report", "@npz@"],
     "rfauto.service.sar_service.sar_load_field_npz",
     {"ok": True, "peak_sar_1g": 0.1}, None, ("ok",)),
    ("si-report", ["si", "report", "@s2p@"],
     "rfauto.service.si_channel_service.si_channel_report",
     {"ok": True, "metrics": {}}, "INJECT", ("ok",)),
    ("si-mixed", ["si", "mixed", "@s4p@"],
     "rfauto.service.si_channel_service.mixed_mode_metrics",
     {"ok": True, "ild_db": []}, "INJECT", ("ok",)),
    # ── preflight/profile 域（4）──
    ("preflight-run", ["preflight", "run"], None, None, None, ("verdict",)),
    ("preflight-gates", ["preflight", "gates"], None, None, None, ("gates",)),
    ("profile-status", ["profile", "status"], None, None, None, ("ok",)),
    ("profile-run", ["profile", "run", "--pid", "1", "--duration", "1"],
     "rfauto.service.profile_service.profile_run",
     {"ok": True, "out": "runs/profile/x.svg"}, "INJECT", ("ok",)),
    # ── recipe 域（3）──
    ("recipe-migrate", ["recipe", "migrate", "@recipe@"], None, None,
     ["recipe", "migrate", "@missing@"], ("ok",)),
    ("recipe-skill", ["recipe", "skill", "@recipe@"], None, None,
     ["recipe", "skill", "@missing@"], ("ok",)),
    ("repro", ["repro", "@runid@"], "rfauto.service.api.repro_export",
     {"ok": True, "message": "done", "files": ["a"], "output_dir": "d"},
     ["repro", "no_such_run"], ("ok",)),
    # ── solvers 域（7）──
    ("solvers-list", ["solvers", "list"],
     "rfauto.service.r3_services.list_registered_solvers",
     {"ok": True, "solvers": [{"type": "fake", "class": "FakeAdapter",
                               "available": True, "n_visualizations": 0}]},
     None, ("ok", "solvers")),
    ("solvers-viz", ["solvers", "viz"], None, None, None, ("ok",)),
    ("solvers-add", ["solvers", "add", "w6b_solver", "--type", "fake"],
     None, None, None, ("ok",)),
    ("solvers-qucsator-mline", ["solvers", "qucsator-mline", "--w-mm", "1.113",
                                "--freqs-ghz", "2.5"],
     "rfauto.service.qucsator_service.solve_mline_three_way",
     {"ok": True, "threeway": {"verdict": {"passed": True}}}, "INJECT", ("ok",)),
    ("simci", ["simci", "@recipesdir@"],
     "rfauto.service.sim_ci_service.nightly_regression",
     {"ok": True, "n_done": 1, "n_recipes": 1, "n_regressions": 0,
      "run_id": "w6b_ci", "run_dir": "runs/w6b_ci", "regressions": []},
     "INJECT", ("ok",)),
    ("inbox", ["inbox"], None, None,
     ["inbox", "--approve", "tok"], ("ok", "pending")),
    ("chat", ["chat", "你好"],
     "rfauto.service.r3_services.AgentChat", "CHAT",
     None, ("ok", "text")),
    # ── stats 域（3）──
    ("stats-guardband", ["stats", "guardband", "5.0", "--u95", "0.4",
                         "--tu", "6.0"], None, None, None, ("ok",)),
    ("stats-cpk", ["stats", "cpk", "--samples", "1,2,3,4,5", "--lsl", "0",
                   "--usl", "10"], None, None,
     ["stats", "cpk", "--samples", "x"], ("ok",)),
    ("stats-weibull", ["stats", "weibull", "--failures", "100,200,300"],
     None, None, None, ("ok",)),
    # ── firmware 域（3）──
    ("firmware-beam", ["firmware", "beam", "--bits", "2", "--file",
                       "@beampayload@"], None, None, None, ("ok", "bits")),
    ("firmware-varactor", ["firmware", "varactor", "--file", "@varpayload@"],
     None, None, None, ("ok", "bit_width")),
    ("firmware-dpd", ["firmware", "dpd", "--file", "@dpdpayload@"],
     None, None, None, ("ok", "verdict")),
    # ── workflow/ui 域（2）──
    ("tolerance", ["tolerance", "@recipe@", "--samples", "20"],
     "rfauto.service.api.run_tolerance",
     {"ok": True, "run_id": "w6b_t", "n_samples": 20, "yield_rate": 1.0,
      "n_pass": 20, "n_fail": 0, "stats": {}}, "INJECT", ("ok",)),
    ("warm-start", ["warm-start", "w6b_ds", "@recipe@"],
     "rfauto.service.warm_start_data.run_optimization_warm_start_from_dataset",
     {"ok": True, "warm_start_n": 2, "trials_completed": 1, "best_cost": 0.1,
      "warm_start_data": {}, "best_params": {}}, "INJECT", ("ok",)),
]

# 覆盖关系式：表 84 件（audit-quality 为 audit 变体）覆盖 83 命令
# + 3 专测（campaign-event/correlate/study-inject，stateful 夹具）= 86 全覆盖
_W6B_DEDICATED = {"campaign-event", "correlate", "study-inject"}
_W6B_SMOKE_CMDS = {c[0] for c in W6B_SMOKE} - {"audit-quality"}
assert len(W6B_TARGETS) == 86
assert {t.replace(" ", "-") for t in W6B_TARGETS} == (
    _W6B_SMOKE_CMDS | _W6B_DEDICATED)


def _w6b_fixtures(tmp_path: Path, monkeypatch) -> dict[str, str]:
    """批C 冒烟物料：全部落 tmp（#144 隔离）。"""
    fx: dict[str, str] = {}
    rp = tmp_path / "recipe.yaml"
    rp.write_text(yaml.safe_dump(RECIPE), encoding="utf-8")
    fx["@recipe@"] = str(rp)
    fx["@missing@"] = str(tmp_path / "no_such.yaml")
    # samples.json（test_uq_service 同款 schema，12 点小样本）
    import random

    rng = random.Random(7)
    bounds = {"arm_len_mm": [18.0, 23.0]}
    samples = []
    for _ in range(12):
        L = float(rng.uniform(*bounds["arm_len_mm"]))
        samples.append({"params": {"arm_len_mm": L},
                        "metrics": {"s11_db_max_in_band":
                                    -20.0 + 5.0 * (L - 20.0) ** 2}})
    sp = tmp_path / "samples.json"
    sp.write_text(json.dumps({"bounds": bounds,
                              "objectives": [{"metric": "s11_db",
                                              "band": [2.3, 2.5],
                                              "op": "max_below", "value": -15}],
                              "samples": samples}), encoding="utf-8")
    fx["@samples@"] = str(sp)
    fx["@runid@"] = "w6b_run"
    fx["@jobid@"] = "w6b_job"
    fx["@study@"] = "w6b_study"
    pp = tmp_path / "payload.json"
    pp.write_text("{}", encoding="utf-8")
    fx["@payload@"] = str(pp)
    cfg = tmp_path / "cfg.json"
    cfg.write_text("{}", encoding="utf-8")
    fx["@cfg@"] = str(cfg)
    # Touchstone 最小件（RI；.s2p 9 列 / .s4p 17 列，两频点）
    s2p = tmp_path / "w6b.s2p"
    s2p.write_text("# GHz S RI R 50\n1.0 1 0 0 0 0 0 0 0\n2.0 1 0 0 0 0 0 0 0\n",
                   encoding="utf-8")
    fx["@s2p@"] = str(s2p)
    s4p = tmp_path / "w6b.s4p"
    row = " ".join(["1", "0"] * 8)
    s4p.write_text(f"# GHz S RI R 50\n1.0 {row}\n2.0 {row}\n", encoding="utf-8")
    fx["@s4p@"] = str(s4p)
    # nf2ff 近场 npz（8x8 栅格，1mm 间距，10GHz）
    import numpy as np

    n = 8
    axis = (np.arange(n) - n / 2) * 1e-3
    npz = tmp_path / "nf.npz"
    np.savez(npz, x_m=axis, y_m=axis, freq_hz=1e10,
             ex=np.ones((n, n), dtype=complex), ey=np.zeros((n, n), dtype=complex),
             z0_m=0.0)
    fx["@npz@"] = str(npz)
    docs = tmp_path / "docs_empty"
    docs.mkdir(exist_ok=True)
    (docs / "note.md").write_text("# 笔记\n阻抗匹配 50 欧。\n", encoding="utf-8")
    fx["@docsdir@"] = str(docs)
    runs_root = tmp_path / "runs_root"
    runs_root.mkdir(exist_ok=True)
    fx["@runsroot@"] = str(runs_root)
    fx["@recipesdir@"] = str(tmp_path)
    beam = tmp_path / "beam.json"
    beam.write_text(json.dumps({"element_ids": [1, 2], "x_mm": [0.0, 1.0],
                                "y_mm": [0.0, 0.0],
                                "phase_target_deg": [0.0, 90.0]}), encoding="utf-8")
    fx["@beampayload@"] = str(beam)
    var = tmp_path / "var.json"
    var.write_text(json.dumps({"f_targets_ghz": [2.4, 2.45], "line_len_mm": 40,
                               "z0_ohm": 50, "ereff": 1.9, "cj0_pf": 2.0,
                               "phi_v": 0.7, "v_ref_v": 5.0, "bit_width": 8}),
                   encoding="utf-8")
    fx["@varpayload@"] = str(var)
    dpd = tmp_path / "dpd.json"
    dpd.write_text(json.dumps({"coeffs": [[{"re": 1.0, "im": 0.0}]],
                               "x": [{"re": 0.5, "im": 0.0}],
                               "word_bits": 8, "frac_bits": 6}), encoding="utf-8")
    fx["@dpdpayload@"] = str(dpd)
    return fx


def _w6b_patch_inject(monkeypatch, target: str, payload) -> None:
    """服务注入（#139）：target="module.attr"；特医标记走专用桩。"""
    import copy
    from types import SimpleNamespace

    if target == "rfauto.service.job_registry.get_job_registry":
        fail_mode = isinstance(payload, dict) and payload.get("ok") is False

        class _FakeReg:
            def cancel(self, job_id):
                return None if fail_mode else {"state": "cancelled"}

        monkeypatch.setattr(target, lambda: _FakeReg())
        return
    if target == "rfauto.core.nf_transform.planar_nf_to_farfield":
        # CLI 对返回值逐键调 .tolist() → 须回 ndarray 载荷（dict deepcopy 不可用）
        import numpy as np

        monkeypatch.setattr(target, lambda *a, **kw: {
            "theta_deg": np.arange(2, dtype=float),
            "phi_deg": np.array([0.0]),
            "pattern_db": [[0.0, 0.0]],
            "window": "kaiser", "validity_max_deg": 80.0})
        return
    if target == "rfauto.adapters.kicad_drc.run_drc_kicad":
        passed = payload == "DRC_OK"
        fake = SimpleNamespace(passed=passed,
                               n_errors=0 if passed else 2, n_warnings=0,
                               violations=[])
        monkeypatch.setattr(target, lambda pcb: fake)
        return
    if target == "rfauto.service.r3_services.AgentChat":
        class _FakeChat:
            def __init__(self, *a, **kw):
                pass

            def chat(self, message):
                return {"text": f"echo:{message}", "action": "help"}

        monkeypatch.setattr(target, _FakeChat)
        return
    if target == "GETMETRICS2":  # export-report-pdf 双依赖注入（service+infra）
        fail_mode = isinstance(payload, dict) and payload.get("ok") is False
        monkeypatch.setattr(
            "rfauto.service.api.get_metrics",
            lambda run_id: (copy.deepcopy(payload) if fail_mode else
                            {"ok": True, "data": {"metrics": {"s11_db": -12.0}}}))
        monkeypatch.setattr("rfauto.infra.report.export_report_pdf",
                            lambda *a, **kw: "runs/w6b_run/report.pdf")
        return
    body = payload if isinstance(payload, dict) else {"ok": True}
    monkeypatch.setattr(target, lambda *a, **kw: copy.deepcopy(body))


class TestBatchCW6bSmoke:
    """判据2 批C：86 件参数化 --json 双路径冒烟（成功信封 + 失败信封同构）。"""

    @pytest.mark.parametrize("case", W6B_SMOKE, ids=[c[0] for c in W6B_SMOKE])
    def test_w6b_json_smoke(self, case, tmp_path, monkeypatch):
        cid, argv, inject, payload, fail, keys = case
        fx = _w6b_fixtures(tmp_path, monkeypatch)
        expand = lambda xs: [fx.get(x, x) for x in xs]  # noqa: E731

        if inject:
            _w6b_patch_inject(monkeypatch, inject, payload)
        r = _invoke([*expand(argv), "--json"])
        assert r.exit_code == 0, f"{cid} exit={r.exit_code}\n{r.output[:400]}"
        success = _envelope(r)
        if "ok" in success:  # 信封形态要求 ok=True；非信封直出（preflight gates/
            assert success.get("ok") is True  # nf2ff/nfc 等）只要求可解析+键集
        for k in keys:
            assert k in success, f"{cid} 成功信封缺键 {k}：{list(success)[:8]}"

        if fail in ("INJECT", "DRC_FAIL"):
            # INJECT=同目标改注失败信封；DRC_FAIL=kicad drc 特医（对象桩失败态）
            assert inject, f"{cid} 注入失败路径须有 inject 目标"
            _w6b_patch_inject(monkeypatch, inject,
                              _W6B_FAIL_PAYLOAD if fail == "INJECT" else fail)
            fr = _invoke([*expand(argv), "--json"])
        elif fail:
            if inject:
                # 成功注入仍在位时先翻成失败信封——argv-fail 只考 CLI 失败接线
                _w6b_patch_inject(monkeypatch, inject, _W6B_FAIL_PAYLOAD)
            fr = _invoke([*expand(fail), "--json"])
        else:
            return
        _assert_failure(fr)

    def test_w6b_jobs_status_by_id_json(self):
        """jobs status <id> --json：未知 job 走 poll_job state=unknown（ok=True 兼容位）。"""
        r = _invoke(["jobs", "status", "w6b_unknown", "--json"])
        assert r.exit_code == 0
        assert _envelope(r).get("state") == "unknown"

    def test_w6b_agent_apply_badparams_json(self, tmp_path):
        """agent apply --params 非法 JSON：--json 下也是信封（exit 1）。"""
        rp = tmp_path / "recipe.yaml"
        rp.write_text(yaml.safe_dump(RECIPE), encoding="utf-8")
        _assert_failure(_invoke(["agent", "apply", str(rp), "--token", "t",
                                 "--params", "not json", "--json"]))

    def test_w6b_campaign_event_json_dual(self, tmp_path):
        """campaign event --json：plan→event 真实状态机双路径（成功+非法阶段）。"""
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(yaml.safe_dump(RECIPE), encoding="utf-8")
        out_dir = tmp_path / "camp"
        plan = _assert_success(_invoke(
            ["campaign", "plan", str(recipe),
             "--out-dir", str(out_dir), "--json"]))
        assert plan.get("plan_path")
        _assert_success(_invoke(["campaign", "event", str(out_dir),
                                 "calibrate", "skip", "--json"]))
        _assert_failure(_invoke(["campaign", "event", str(out_dir),
                                 "no_such_stage", "skip", "--json"]))

    def test_w6b_study_inject_json_dual(self, monkeypatch):
        """study inject --json：成功接线注入（新 study 无已出现参数，service
        拒注如实 ok=False——故成功面走 #139 注入）+ 缺 study 真实失败信封。"""
        import rfauto.service.api as api_mod

        real_inject = api_mod.study_inject
        monkeypatch.setattr(
            "rfauto.service.api.study_inject",
            lambda study, params, source="human": {
                "ok": True, "study_name": study, "trial_number": 0,
                "source": source})
        payload = _assert_success(_invoke(
            ["study", "inject", "w6b_study", '{"arm_len_mm": 20.5}', "--json"]))
        assert payload.get("study_name") == "w6b_study"
        # 还原真实 service：缺 study 走真实失败信封
        monkeypatch.setattr("rfauto.service.api.study_inject", real_inject)
        _assert_failure(_invoke(["study", "inject", "no_such_study_w6b",
                                 '{"a": 1}', "--json"]))

    def test_w6b_doctor_main_json_exit_semantics(self, monkeypatch):
        """doctor --json 主面：全 ok → exit 0；有缺项 → exit 1（门语义钉，
        检查项注入确定化——真机探测结果随本机环境漂移，不进门）。"""
        checks_ok = {"ok": True,
                     "checks": [{"name": "x", "status": "ok", "detail": "d"}]}
        monkeypatch.setattr("rfauto.service.api.doctor", lambda: checks_ok)
        r = _invoke(["doctor", "--json"])
        assert r.exit_code == 0
        assert _envelope(r).get("checks")[0]["status"] == "ok"

        checks_bad = {"ok": True,
                      "checks": [{"name": "x", "status": "missing", "detail": "d"}]}
        monkeypatch.setattr("rfauto.service.api.doctor", lambda: checks_bad)
        r2 = _invoke(["doctor", "--json"])
        assert r2.exit_code == 1

    def test_w6b_correlate_json_dual(self, tmp_path):
        """correlate --json：同文件自比对成功（exit 0）+ 缺文件失败信封（exit 1）。"""
        s2p = tmp_path / "w6b_c.s2p"
        s2p.write_text("# GHz S RI R 50\n1.0 1 0 0 0 0 0 0 0\n"
                       "2.0 1 0 0 0 0 0 0 0\n", encoding="utf-8")
        _assert_success(_invoke(["correlate", str(s2p), str(s2p), "--json"]))
        _assert_failure(_invoke(["correlate", "missing.s2p", str(s2p), "--json"]))

    def test_w6b_doctor_env_json(self):
        """doctor --env --json：信息性报告信封（恒 exit 0 语义保持）。"""
        r = _invoke(["doctor", "--env", "--json"])
        assert r.exit_code == 0
        assert "checks" in _envelope(r)

    def test_w6b_compat_flag_default_equivalence(self):
        """兼容位抽样：farfield list / preflight gates 有无 --json 输出同形（批B 法）。"""
        a = _invoke(["farfield", "list"]).output
        b = _invoke(["farfield", "list", "--json"]).output
        assert a == b and a.strip()
        a2 = _invoke(["preflight", "gates"]).output
        b2 = _invoke(["preflight", "gates", "--json"]).output
        assert a2 == b2 and a2.strip()
