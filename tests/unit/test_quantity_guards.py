"""R11 Top3 quantity 守卫铺广度接线测试（aurora_q Q-W8-4）。

背景：``validate_quantity_args``（core/quantity.py，fail-closed 量纲守卫）
R11 实测 src 零调用方——"防线建成未上岗"。本批把守卫家族铺到 CLI 高频
**数量语义参数**面（points/n_trials/limit/max_iter/top_k/count 类）：

- 单元面：:func:`rfauto.service.arg_guard_service.validate_count_args`
  （计数伴生守卫，与 validate_quantity_args 同构的非抛出错误清单；分层
  落位=service——壳层业务消费一律走 service，shell-below-service 棘轮
  禁 cli→core 直连，core/quantity.py 本体零改动）；
- 接线面：12 个高频 CLI 叶负/零边界钉（``--flag=-1``/``--flag=0`` →
  usage error（exit 2）+ error 信封——``_emit_usage_error`` 单源出口，
  #ge1㉙ JSON 信道禁裸文本）；合法值锚值钉（既有路径零变化）；
- 棘轮面：CLI 面 ``validate_count_args`` 调用点计数只收不放（后续批次
  接线新叶必须扩 WIRED_LEAVES 并抬计数——分批表见
  runs/aurora_q/qw84_stats/wiring_ledger.md）。

负值入参形态注记：CLI 里 ``--limit -1``（空格形）被 click 解析器拦截为
未知选项（typer usage 档，exit 2，先于叶函数体——既有面，非本批改动）；
守卫本体可达形态是等号形 ``--limit=-1``——接线钉一律用等号形直击叶内守卫。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from rfauto.cli.main import app
from rfauto.service.arg_guard_service import validate_count_args

runner = CliRunner()

#: 本批接线的 CLI 叶清单（叶=命令路径；分批台账见
#: runs/aurora_q/qw84_stats/wiring_ledger.md——后续批次接线即扩本表）。
WIRED_LEAVES: list[str] = [
    "db query",             # --limit
    "lake query",           # --limit
    "report",               # --limit（jobs.py 批量面；单 run 面零变化）
    "uq yield-at",          # --n（MC 抽样数）
    "uq design-center",     # --n-levels --max-iter --n-mc
    "bands env-points",     # --n（采样点数）
    "template-spec recommend",  # --top-k
    "al propose",           # --k（下限 0，帮助契约 ≥0）--n-candidates --max-rows
    "tune",                 # --max-trials --n-gen --pop-size
    "p0",                   # --coarse --fine --baseline --edge-samples --cross-samples
    "mo run",               # --n-eval --n-obj（下限 2）--n-init --batch-size --n-candidates --mc-samples
    "topology",             # --n-trials
]

#: 守卫调用点棘轮下限（Q-W8-4 批后实测 12；只收不放——后续批次接线抬本值）。
WIRED_CALLSITE_RATCHET = 12


# ────────────────────────── 单元面：validate_count_args ──────────────────────


class TestValidateCountArgs:
    def test_negative_and_zero_rejected_default_floor_one(self):
        assert validate_count_args({"--limit": -1}) == ["--limit 必须 ≥1（得 -1）"]
        assert validate_count_args({"--limit": 0}) == ["--limit 必须 ≥1（得 0）"]

    def test_positive_values_pass(self):
        assert validate_count_args({"--limit": 1, "--n": 10000}) == []

    def test_none_skipped_optional_params_untouched(self):
        """可选数量参数缺席（None）零过问——内核缺省路径零变化。"""
        assert validate_count_args({"--n-init": None, "--limit": 5}) == []

    def test_bool_rejected_int_subclass_trap(self):
        errs = validate_count_args({"--n": True})
        assert errs == ["--n 必须是整数数量（拒 bool），得 True"]

    def test_non_int_rejected_fail_closed(self):
        for bad in ("5", 5.0, [5]):
            errs = validate_count_args({"--n": bad})
            assert len(errs) == 1 and "必须是整数数量" in errs[0], bad

    def test_minimums_override_per_name(self):
        errs = validate_count_args({"--k": 0, "--limit": 0},
                                   minimums={"--k": 0})
        # --k 下限 0 → 0 过（帮助契约"≥0"）；--limit 下限缺省 1 → 0 拒
        assert errs == ["--limit 必须 ≥1（得 0）"]
        assert validate_count_args({"--k": -1}, minimums={"--k": 0}) == [
            "--k 必须 ≥0（得 -1）"]

    def test_minimum_kwarg_global_floor(self):
        assert validate_count_args({"--n-eval": 1}, minimum=2) == [
            "--n-eval 必须 ≥2（得 1）"]
        assert validate_count_args({"--n-eval": 2}, minimum=2) == []

    def test_message_carries_name_floor_value(self):
        errs = validate_count_args({"--top-k": -3})
        assert errs == ["--top-k 必须 ≥1（得 -3）"]

    def test_placement_service_layer_gold_snapshot_frozen(self):
        """分层落位钉：守卫住 service 层（壳层业务消费一律走 service，
        shell-below-service 棘轮禁 cli→core 直连）；core/quantity.py 本体
        零改动（__all__ 被 tests/gold/public_api.json 冻结——Q-W8-4 禁改
        金快照；R11 防线本体 validate_quantity_args 仍在原位）。"""
        from rfauto.core import quantity

        assert not hasattr(quantity, "validate_count_args")  # 内核面零改动
        assert "validate_quantity_args" in quantity.__all__  # R11 防线本体仍在

        import json as _json
        from pathlib import Path as _Path

        gold = _json.loads(
            (_Path(__file__).resolve().parents[2] / "tests" / "gold"
             / "public_api.json").read_text(encoding="utf-8"))
        # 新 service 模块无 __all__（非门面）→ 不进快照（零金漂移）
        assert "service/arg_guard_service.py" not in gold.get("files", {})

    def test_empty_args_pass(self):
        assert validate_count_args({}) == []


# ────────────────────────── 接线面：12 叶负/零边界钉 ──────────────────────────

#: （叶名, 负例参数组, 零例参数组）——JSON 信道断言信封（缺省即 JSON 的叶
#: 不加旗标；旗标叶带 --json）。mo run 下限 2（帮助契约"≥2"），零例用 1。
_LEAF_CASES: list[tuple[str, list[str], list[str]]] = [
    ("db query",
     ["db", "query", "SELECT 1", "--limit=-1", "--json"],
     ["db", "query", "SELECT 1", "--limit=0", "--json"]),
    ("lake query",
     ["lake", "query", "--limit=-1", "--json"],
     ["lake", "query", "--limit=0", "--json"]),
    ("report",
     ["report", "--all", "--limit=-1", "--json"],
     ["report", "--all", "--limit=0", "--json"]),
    ("uq yield-at",
     ["uq", "yield-at", "x.json", "--n=-1"],
     ["uq", "yield-at", "x.json", "--n=0"]),
    ("uq design-center",
     ["uq", "design-center", "x.json", "--n-mc=-1"],
     ["uq", "design-center", "x.json", "--n-mc=0"]),
    ("bands env-points",
     ["bands", "env-points", "industrial_grade_40_85", "--n=-1"],
     ["bands", "env-points", "industrial_grade_40_85", "--n=0"]),
    ("template-spec recommend",
     ["template-spec", "recommend", "--f0-ghz", "2.4", "--top-k=-1", "--json"],
     ["template-spec", "recommend", "--f0-ghz", "2.4", "--top-k=0", "--json"]),
    ("al propose",
     ["al", "propose", "--k=-1", "--json"],
     ["al", "propose", "--n-candidates=0", "--json"]),
    ("tune",
     ["tune", "recipe.yaml", "--max-trials=-1", "--json"],
     ["tune", "recipe.yaml", "--max-trials=0", "--json"]),
    ("p0",
     ["p0", "recipe.yaml", "--coarse=-1", "--json"],
     ["p0", "recipe.yaml", "--coarse=0", "--json"]),
    ("mo run",
     ["mo", "run", "--n-eval=-1", "--json"],
     ["mo", "run", "--n-eval=1", "--json"]),
    ("topology",
     ["topology", "--f0", "2.4", "--fbw", "0.1", "--n-trials=-1"],
     ["topology", "--f0", "2.4", "--fbw", "0.1", "--n-trials=0"]),
]


def _assert_usage_error_envelope(result) -> None:
    """usage error 契约钉：exit 2 + JSON 信道 error 信封（ok=False + errors）。"""
    assert result.exit_code == 2, result.output
    data = json.loads(result.output)
    assert data["ok"] is False
    assert isinstance(data["errors"], list) and data["errors"]
    assert all(isinstance(e, str) for e in data["errors"])


@pytest.mark.parametrize("leaf,neg_args,zero_args", _LEAF_CASES,
                         ids=[c[0] for c in _LEAF_CASES])
class TestWiredLeafBoundaries:
    def test_negative_value_rejected(self, leaf, neg_args, zero_args,
                                     tmp_path, monkeypatch):
        """-1 边界钉：负值显式拒绝（usage error 信封 + exit 2）。"""
        monkeypatch.chdir(tmp_path)  # #144 家法：叶级测试隔离真实 runs/
        _assert_usage_error_envelope(runner.invoke(app, neg_args))

    def test_zero_value_rejected(self, leaf, neg_args, zero_args,
                                 tmp_path, monkeypatch):
        """0 边界钉：floor 1 的叶零值同样显式拒绝（mo run floor 2 → 1 也拒）。"""
        monkeypatch.chdir(tmp_path)
        _assert_usage_error_envelope(runner.invoke(app, zero_args))


class TestWiredLeafLegalAnchors:
    """合法值锚值钉——既有路径零变化（每叶锚值=既有测试面同口径）。"""

    def test_db_query_legal_limit_passes(self, tmp_path):
        db = str(tmp_path / "reg.sqlite")
        assert runner.invoke(
            app, ["db", "init", "--db", db, "--json"]).exit_code == 0
        r = runner.invoke(app, [
            "db", "query", "SELECT run_id FROM runs", "--db", db,
            "--limit=3", "--json"])
        assert r.exit_code == 0, r.output
        data = json.loads(r.output)
        assert data["ok"] is True and data["row_count"] == 0

    def test_bands_env_points_legal_n(self):
        r = runner.invoke(app, [
            "bands", "env-points", "industrial_grade_40_85", "--n=3", "--json"])
        assert r.exit_code == 0, r.output
        data = json.loads(r.output)
        assert data["ok"] is True and data["count"] == 3

    def test_template_spec_recommend_legal_top_k(self):
        r = runner.invoke(app, [
            "template-spec", "recommend", "--f0-ghz", "2.4",
            "--top-k=2", "--json"])
        assert r.exit_code == 0, r.output
        assert json.loads(r.output)["ok"] is True

    def test_topology_legal_n_trials_default(self):
        """topology 合法 n_trials（缺省 80，无 --campaign 不消费）路径零变化。"""
        r = runner.invoke(app, ["topology", "--f0", "2.4", "--fbw", "0.1"])
        assert r.exit_code == 0, r.output
        assert json.loads(r.output)["ok"] is True

    def test_al_propose_k_zero_passes_guard_service_rejects(self):
        """--k 下限 0（帮助契约"≥0"）：0 过守卫 → 既有 service 拒绝面
        （缺样本来源，exit 1 信封）逐字节不变——floor-0 边界语义钉。"""
        r = runner.invoke(app, ["al", "propose", "--k=0", "--json"])
        assert r.exit_code == 1, r.output  # 非 2=守卫未开火（0 合法）
        data = json.loads(r.output)
        assert data["ok"] is False
        assert any("样本来源" in e for e in data["errors"])


# ────────────────────────── 棘轮面：只收不放 ─────────────────────────────────


class TestWiringRatchet:
    def test_leaf_list_shape(self):
        assert len(WIRED_LEAVES) == 12
        assert len(set(WIRED_LEAVES)) == len(WIRED_LEAVES)

    def test_wired_callsites_ratchet(self):
        """src/rfauto/cli 下 validate_count_args 调用点 ≥ 棘轮下限（只收不放）。

        后续批次接线新叶 → 扩 WIRED_LEAVES + 抬 WIRED_CALLSITE_RATCHET
        （同笔登记 runs/aurora_q/qw84_stats/wiring_ledger.md 分批表）。
        """
        cli_root = Path(__file__).resolve().parents[2] / "src" / "rfauto" / "cli"
        count = 0
        for py in sorted(cli_root.rglob("*.py")):
            text = py.read_text(encoding="utf-8")
            count += text.count("validate_count_args(")
        assert count >= WIRED_CALLSITE_RATCHET, (
            f"validate_count_args 调用点 {count} < 棘轮 {WIRED_CALLSITE_RATCHET}"
            "——守卫面只许增不许减（R11 Top3 铺广度棘轮）")

    def test_leaves_parametrization_covers_ledger(self):
        """接线钉参数化清单与 WIRED_LEAVES 台账一一对应（防两表漂移）。"""
        assert [c[0] for c in _LEAF_CASES] == WIRED_LEAVES
