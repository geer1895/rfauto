"""aurora_n O5 竞赛持久门钉（2026-10-31）：competition run CLI 叶 + 服务面。

zero_wiring REGISTRY O5 欠账清偿钉：T-N5 标量竞赛架（competition_scalar）
运行时门（service/competition_service + cli/domains/competition.py）。
覆盖：e2e 信封形状 / 确定性（同 seed 剥离 elapsed_s 逐位）/ 负例四形态
（未知引擎/未知族/重复引擎/常数目标 #195）/ botorch_ei opt-in 面 /
族注册面 / CLI --json 信封与 --out 落盘。
"""

from __future__ import annotations

import json

import pytest

from rfauto.service.competition_service import (
    BUILTIN_PROBLEM_FACTORIES,
    register_problem_factory,
    run_competition,
    strip_elapsed_s,
)

# 信封契约形状（AU-2 构造器单源）——本文件全部信封经构造器产出
ENVELOPE_OK_KEYS = {"ok"}


@pytest.fixture(autouse=True)
def _restore_scalar_registry():
    """竞赛引擎注册表快照恢复（本文件 opt-in/注册动作零外溢——test_
    botorch_engine.py 同款 autouse 钉；不恢复必打红后序字母序文件的
    test_competition_scalar 注册序断言）。"""
    import rfauto.optimization.competition_scalar as comp_mod

    before = dict(comp_mod.SCALAR_ENGINE_REGISTRY)
    yield
    comp_mod.SCALAR_ENGINE_REGISTRY.clear()
    comp_mod.SCALAR_ENGINE_REGISTRY.update(before)


_DEFAULT = object()


def _tiny(engines=_DEFAULT, problems=None, n_eval=8, seeds=(0,)):
    """小预算竞赛（快面：单族单 seed 8 点；engines 哨兵透传缺省语义）。"""
    return run_competition(
        ["tpe"] if engines is _DEFAULT else engines,
        problems if problems is not None else ["concave2d"],
        n_eval=n_eval, seeds=list(seeds))


class TestServiceEnvelope:
    """e2e 信封形状与缺省语义。"""

    def test_tiny_run_ok_envelope(self):
        res = _tiny()
        assert isinstance(res, dict) and res.get("ok") is True
        assert set(res) >= {"schema", "engines", "problems", "n_eval",
                            "seeds", "n_runs", "result", "report_md",
                            "elapsed_s", *ENVELOPE_OK_KEYS}
        assert res["schema"] == "competition-scalar-v1"
        kernel = res["result"]
        assert kernel["n_eval"] == 8
        assert kernel["stages"] == {"stage1_horizon": 4, "stage2_horizon": 8}
        assert len(kernel["runs"]) == 1
        run0 = kernel["runs"][0]
        assert run0["n_evals_used"] == 8
        for key in ("best_half", "best_final", "auc_half", "auc"):
            assert isinstance(run0[key], float)
        # report_md 与内核报表同源（含标题与三套排名表）
        assert res["report_md"].startswith(
            "# T-N5 单目标优化器族竞赛报表")
        assert "## 排名" in res["report_md"]

    def test_default_engines_are_registered_face(self):
        """缺省引擎=SCALAR_ENGINE_REGISTRY 注册序全量（botorch_ei 不在缺省）。"""
        from rfauto.optimization.competition_scalar import list_scalar_engines

        res = _tiny(engines=None)
        assert res["engines"] == list_scalar_engines()
        assert "botorch_ei" not in res["engines"]  # opt-in 臂不进缺省面
        assert res["n_runs"] == len(res["engines"])

    def test_default_problems_are_builtin_four(self):
        res = run_competition(["tpe"], None, n_eval=4, seeds=[0])
        assert res["problems"] == list(BUILTIN_PROBLEM_FACTORIES)
        assert len(res["problems"]) == 4

    def test_kernel_shape_two_stage_shares_trajectory(self):
        """两阶段共享轨迹（同一条 runs 记录双截点记分，不重跑）。"""
        res = _tiny(engines=["tpe", "gp"], n_eval=8)
        kernel = res["result"]
        assert len(kernel["runs"]) == 2  # 2 引擎×1 族×1 seed，无重跑翻倍
        for stage in ("ranking_stage1", "ranking_stage2", "ranking_target"):
            assert {r["engine"] for r in kernel[stage]} == {"tpe", "gp"}


class TestDeterminism:
    """确定性：同 seed 重跑剥离 elapsed_s 逐位一致。"""

    def test_same_seed_rerun_bitwise_after_strip(self):
        args = dict(engines=["tpe", "cmaes"], problems=["rastrigin2d"],
                    n_eval=10, seeds=[0, 1])
        a = run_competition(*[], **args)
        b = run_competition(*[], **args)
        sa = json.dumps(strip_elapsed_s(a["result"]), sort_keys=True)
        sb = json.dumps(strip_elapsed_s(b["result"]), sort_keys=True)
        assert sa == sb  # 剥离 elapsed_s 后逐位
        # elapsed_s 本身不进钉（墙钟实测字段）
        assert "elapsed_s" not in sa

    def test_strip_elapsed_s_recursive(self):
        payload = {"a": 1, "elapsed_s": 0.5, "runs": [{"elapsed_s": 1.0, "v": 2}]}
        assert strip_elapsed_s(payload) == {"a": 1, "runs": [{"v": 2}]}

    def test_seed_change_changes_trajectory(self):
        a = _tiny(engines=["tpe"], n_eval=10, seeds=(0,))
        b = _tiny(engines=["tpe"], n_eval=10, seeds=(1,))
        ja = json.dumps(strip_elapsed_s(a["result"]), sort_keys=True)
        jb = json.dumps(strip_elapsed_s(b["result"]), sort_keys=True)
        assert ja != jb  # 不同 seed 轨迹不同（确定性≠常数）


class TestNegatives:
    """负例四形态（全部信封化不抛裸异常）。"""

    def test_unknown_engine(self):
        res = _tiny(engines=["nosuch"])
        assert res["ok"] is False
        assert any("未知引擎" in e and "nosuch" in e for e in res["errors"])
        assert "可用" in res["errors"][0]

    def test_duplicate_engine_rejected(self):
        res = _tiny(engines=["tpe", "tpe"])
        assert res["ok"] is False
        assert any("重复" in e for e in res["errors"])

    def test_unknown_problem_family(self):
        res = _tiny(problems=["nosuchfam"])
        assert res["ok"] is False
        assert any("未知问题族" in e and "nosuchfam" in e for e in res["errors"])

    def test_constant_objective_rejected(self, monkeypatch, tmp_path):
        """常数目标拒跑（#195 常数陷阱语义经族注册面注入）。"""
        from rfauto.optimization.competition_scalar import ScalarProblem

        def _const():
            return ScalarProblem(
                name="const2d", bounds={"x0": (0.0, 1.0), "x1": (0.0, 1.0)},
                objective_fn=lambda p: 1.0, target=0.5, known_optimum=0.0)

        register_problem_factory("const2d", _const)
        try:
            res = _tiny(problems=["const2d"])
        finally:
            BUILTIN_PROBLEM_FACTORIES.pop("const2d", None)
        assert res["ok"] is False
        assert any("退化常数目标" in e and "#195" in e for e in res["errors"])

    def test_bad_n_eval_and_seeds(self):
        assert run_competition(["tpe"], ["concave2d"], n_eval=0,
                               seeds=[0])["ok"] is False
        assert run_competition(["tpe"], ["concave2d"], n_eval=5,
                               seeds=[])["ok"] is False
        assert run_competition(["tpe"], ["concave2d"], n_eval="x",
                               seeds=[0])["ok"] is False


class TestBotorchOptIn:
    """botorch_ei opt-in 面：显式点名即注册；缺席环境报安装指引。"""

    def test_explicit_name_optin_when_available(self):
        pytest.importorskip("botorch")
        from rfauto.optimization.botorch_engine import BOTORCH_ENGINE_NAME
        from rfauto.optimization.competition_scalar import SCALAR_ENGINE_REGISTRY

        if BOTORCH_ENGINE_NAME not in SCALAR_ENGINE_REGISTRY:
            # 本测试进程首次 opt-in（幂等面在 botorch_engine 自身钉）
            res = _tiny(engines=["botorch_ei"], n_eval=8)
            assert res["ok"] is True
            assert res["engines"] == ["botorch_ei"]
        # 注册后同进程可达（幂等：重复点名不重复注册不报错）
        res2 = _tiny(engines=["botorch_ei"], n_eval=6)
        assert res2["ok"] is True

    def test_botorch_absent_error_has_install_hint(self, monkeypatch):
        """未装 botorch 的错误面带安装指引（monkeypatch 探针钉死缺席分支）。"""
        import rfauto.optimization.botorch_engine as be

        monkeypatch.setattr(be, "is_botorch_available", lambda: False)
        from rfauto.optimization.competition_scalar import SCALAR_ENGINE_REGISTRY

        if "botorch_ei" in SCALAR_ENGINE_REGISTRY:
            pytest.skip("botorch_ei 已注册（进程内先前测试 opt-in）——缺席"
                        "分支不可达，注册面幂等契约由 botorch_engine 钉守")
        res = _tiny(engines=["botorch_ei"], n_eval=8)
        assert res["ok"] is False
        assert any("rfauto[botorch]" in e for e in res["errors"])


class TestProblemFactoryFace:
    """族注册面（Python 编程层）。"""

    def test_register_and_consume_custom_family(self):
        from rfauto.optimization.competition_scalar import ScalarProblem

        calls = []

        def _quad():
            def obj(p):
                calls.append(1)
                return (p["x0"] - 0.3) ** 2 + 0.01 * (p["x1"] - 0.7) ** 2
            return ScalarProblem(
                name="o5_quad", bounds={"x0": (0.0, 1.0), "x1": (0.0, 1.0)},
                objective_fn=obj, target=0.01, known_optimum=0.0)

        register_problem_factory("o5_quad", _quad)
        try:
            assert "o5_quad" in BUILTIN_PROBLEM_FACTORIES
            res = _tiny(problems=["o5_quad"], n_eval=6)
            assert res["ok"] is True and res["problems"] == ["o5_quad"]
            assert calls  # 目标函数确实被消费
        finally:
            BUILTIN_PROBLEM_FACTORIES.pop("o5_quad", None)

    def test_register_non_callable_rejected(self):
        with pytest.raises(ValueError):
            register_problem_factory("o5_bad", 42)  # type: ignore[arg-type]


class TestCliLeaf:
    """CLI 叶：--json 信封与 --out 落盘（chdir 隔离防污染真实 runs/）。"""

    def test_cli_json_envelope_and_out_files(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        from typer.testing import CliRunner

        from rfauto.cli.main import app

        runner = CliRunner()
        out_dir = tmp_path / "comp_out"
        r = runner.invoke(
            app, ["competition", "run", "--engines", "tpe", "--problems",
                  "concave2d", "--n-eval", "6", "--seeds", "0",
                  "--out", str(out_dir), "--json"])
        assert r.exit_code == 0, r.output
        envelope = json.loads(r.output)
        assert envelope["ok"] is True
        assert envelope["engines"] == ["tpe"]
        # 报表双件落盘（持久门本体）
        md = out_dir / "report.md"
        js = out_dir / "report.json"
        assert md.exists() and js.exists()
        kernel = json.loads(js.read_text(encoding="utf-8"))
        assert kernel["schema"] == "competition-scalar-v1"
        assert envelope["result"] == kernel  # 信封 result 与落盘件同源
        assert "## 排名" in md.read_text(encoding="utf-8")

    def test_cli_default_out_is_runs_competition(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)  # #144 家法：chdir 隔离，禁污染真实 runs/
        from typer.testing import CliRunner

        from rfauto.cli.main import app

        runner = CliRunner()
        r = runner.invoke(
            app, ["competition", "run", "--engines", "tpe", "--problems",
                  "rosenbrock2d", "--n-eval", "6", "--seeds", "0", "--json"])
        assert r.exit_code == 0, r.output
        assert (tmp_path / "runs" / "competition" / "report.md").exists()
        assert (tmp_path / "runs" / "competition" / "report.json").exists()

    def test_cli_failure_envelope_json(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        from typer.testing import CliRunner

        from rfauto.cli.main import app

        runner = CliRunner()
        r = runner.invoke(
            app, ["competition", "run", "--engines", "nosuch", "--n-eval",
                  "6", "--json"])
        assert r.exit_code == 1  # service 信封失败=exit 1（usage 类才是 2）
        envelope = json.loads(r.output)
        assert envelope["ok"] is False
        assert envelope["errors"]

    def test_cli_human_face_mentions_rankings(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        from typer.testing import CliRunner

        from rfauto.cli.main import app

        runner = CliRunner()
        r = runner.invoke(
            app, ["competition", "run", "--engines", "tpe", "--problems",
                  "concave2d", "--n-eval", "6", "--seeds", "0",
                  "--out", str(tmp_path / "o")])
        assert r.exit_code == 0, r.output
        assert "阶段一" in r.output and "阶段二" in r.output

    def test_cli_seeds_parse_error_exit2(self, monkeypatch, tmp_path):
        """usage 类错误=exit 2（#ge1㉙ 契约：--json 下也必须 JSON 信封）。"""
        monkeypatch.chdir(tmp_path)
        from typer.testing import CliRunner

        from rfauto.cli.main import app

        runner = CliRunner()
        r = runner.invoke(
            app, ["competition", "run", "--engines", "tpe", "--n-eval", "6",
                  "--seeds", "a,b", "--json"])
        assert r.exit_code == 2
        envelope = json.loads(r.output)
        assert envelope["ok"] is False
