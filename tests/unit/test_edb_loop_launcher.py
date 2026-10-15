"""EDB 快车道优化环发射器单测（service/edb_loop_launcher.py）——全 fake 零真机。

覆盖口径（任务书三场景+契约面）：
- 正常评估：params→假 build/solve（契约信封手构）→真健康门判读→skrf
  现场合成 Touchstone（test_edb_health_gate 同款 form="ri"）→指标从
  判读报告单源提取（cost=FAIL 惩罚+S11 谷深）；
- 判读 FAIL：记惩罚 cost=惩罚×n_fail+谷深，ok 仍 True（FAIL 是健康结论
  非评估失败）；cost 符号钉（任务书"越深越好"：同惩罚下谷越深 cost
  越低——环 min-cost 寻优语义）；
- 发射失败：信封级失败 EvalResult.from_error（工程路径兜底 artifact）/
  异常透传（会话层记账）/判读缺 S11@f0 如实失败（#122 不造数）；
- Protocol 缝：metric_extractor 注入整体接管指标/cost 语义；门参数
  透传（s11_dip_gate_db）；模块属性惰性解析缝（monkeypatch 等价 fake 面）；
- recipe_loop_remote 会话集成：三参数点批量发射→逐点落账（逐点产物名
  带指纹不互踩）→重启零发射完整回放（回放语义保持）→失败点记账+重试。
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from rfauto.service.edb_loop_launcher import (
    DEFAULT_FAIL_PENALTY,
    EdbLoopLauncher,
    HealthMetricExtractor,
    default_edb_metrics,
)
from rfauto.service.envelope import error_envelope, ok_envelope
from rfauto.service.recipe_loop_remote import (
    LEDGER_FILENAME,
    EvalResult,
    LoopLauncher,
    LoopLedger,
    RecipeLoopRemoteSession,
)

TEMPLATE = "edb_power_divider"
F0 = 2.5
POINTS = [{"f0_ghz": 2.4}, {"f0_ghz": 2.5}, {"f0_ghz": 2.6}]


# ---------------------------------------------------------------------------
# 合成数据助手（skrf 现场构造，零真机；量值自洽钉：20log10(0.05)=-26.02dB
# 过 -10dB 门，20log10(0.66)=-3.61dB 落分配窗 [-3.8,-2.5]，
# σmax=d+leg·√2<1.01 无源门内）
# ---------------------------------------------------------------------------

def _mk_s(s11_mag: float, leg_mag: float, n_freq: int = 41) -> np.ndarray:
    """Wilkinson 口径合成 S（3 端口）：对角 s11_mag、馈→双腿 leg_mag、腿间 0。"""
    s = np.zeros((n_freq, 3, 3), dtype=complex)
    for i in range(3):
        s[:, i, i] = s11_mag
    s[:, 0, 1] = s[:, 1, 0] = leg_mag
    s[:, 0, 2] = s[:, 2, 0] = leg_mag
    return s


def _write_touchstone(path: Path, s: np.ndarray, f0_ghz: float) -> Path:
    import skrf

    freq = skrf.Frequency.from_f(
        np.linspace(0.7 * f0_ghz, 1.3 * f0_ghz, len(s)) * 1e9, unit="Hz")
    path.parent.mkdir(parents=True, exist_ok=True)
    skrf.Network(frequency=freq, s=s, z0=50).write_touchstone(
        str(path), form="ri")
    return path


class FakeBuildSolve:
    """假 edb_build_solve（真机契约同签名）：按 params 写 Touchstone 并回
    edb_build_solve 成功信封形态（build/solve 分节）；envelope/exc 供
    信封级失败与异常透传场景注入。"""

    def __init__(
        self,
        snp_root: Path,
        s_for: Callable[[dict], np.ndarray] | None = None,
        *,
        envelope: dict | None = None,
        exc: Exception | None = None,
    ) -> None:
        self.snp_root = Path(snp_root)
        self.s_for = s_for or (lambda p: _mk_s(0.05, 0.66))
        self.envelope = envelope
        self.exc = exc
        self.calls: list[dict] = []

    def __call__(
        self,
        template: str,
        params: dict | None = None,
        workdir: str = "runs/edb_lane",
        name: str | None = None,
        dry_run: bool = False,
        solve: bool = False,
        timeout_s: float = 3600.0,
        export: bool = True,
        **_kw: object,
    ) -> dict:
        if self.exc is not None:
            raise self.exc
        self.calls.append({
            "template": template,
            "params": dict(params or {}),
            "name": name,
            "workdir": workdir,
        })
        if self.envelope is not None:
            return self.envelope
        full = dict(params or {})
        f0 = float(full.get("f0_ghz", F0))
        s = self.s_for(full)
        snp = self.snp_root / f"{name or template}_export.s{s.shape[-1]}p"
        _write_touchstone(snp, s, f0)
        aedb = self.snp_root / f"{name or template}.aedb"
        return ok_envelope(
            template=template,
            build={"ok": True, "aedb_path": str(aedb),
                   "config_json_path":
                       str(self.snp_root / f"{name or template}_config.json"),
                   "warnings": []},
            solve={"ok": True, "project": str(aedb),
                   "solve": {"ok": True, "rc": 0, "timed_out": False,
                             "message": "", "logfile": None,
                             "artifacts": [str(snp)], "elapsed_s": 1.0},
                   "export": {"ok": True, "out_file": str(snp),
                              "n_ports": int(s.shape[-1]), "rc": 0,
                              "timed_out": False, "logfile": None,
                              "errors": []},
                   "warnings": []},
        )


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RFAUTO_CACHE", "off")
    yield


# ─── 契约面 ──────────────────────────────────────────────────────────────────

def test_protocol_conformance_and_name():
    fake = FakeBuildSolve(Path("."))
    launch = EdbLoopLauncher(TEMPLATE, build_solve_fn=fake)
    assert isinstance(launch, LoopLauncher)  # runtime_checkable 协议
    assert launch.name == f"edb:{TEMPLATE}"  # 账本溯源缺省名
    assert EdbLoopLauncher(TEMPLATE, name="edb:custom",
                           build_solve_fn=fake).name == "edb:custom"
    assert isinstance(lambda report: {}, HealthMetricExtractor)


def test_default_metrics_extractor_unit():
    report_pass = {
        "verdict": "PASS",
        "summary": {"n_fail": 0, "n_unknown": 0,
                    "fail_factors": [], "unknown_factors": []},
        "criteria": [
            {"factor": "s11_dip",
             "evidence": {"s11_db_at_f0": -26.021, "gate_db": -10.0}},
            {"factor": "s_split_window",
             "evidence": {"s21_db_at_f0": -3.609, "s31_db_at_f0": -3.61}},
        ],
    }
    m = default_edb_metrics(report_pass, fail_penalty=1e3)
    assert m["s11_dip_db"] == pytest.approx(-26.021)
    assert m["s11_dip_depth_db"] == pytest.approx(26.021)
    assert m["cost"] == pytest.approx(-26.021)  # 零 FAIL→惩罚零贡献
    assert m["health_verdict_fail"] == 0.0
    assert m["s21_db_at_f0"] == pytest.approx(-3.609)
    assert m["s31_db_at_f0"] == pytest.approx(-3.61)

    report_fail = {
        "verdict": "FAIL",
        "summary": {"n_fail": 2, "n_unknown": 1,
                    "fail_factors": ["s11_dip", "passivity"],
                    "unknown_factors": ["port_count"]},
        "criteria": [
            {"factor": "s11_dip", "evidence": {"s11_db_at_f0": -20.0}},
        ],
    }
    m2 = default_edb_metrics(report_fail)
    assert m2["cost"] == pytest.approx(2 * DEFAULT_FAIL_PENALTY - 20.0)
    assert m2["health_verdict_fail"] == 1.0
    assert m2["health_unknown_count"] == 1.0
    assert "s21_db_at_f0" not in m2  # 判据缺席不造数

    # 判读无 S11@f0 读数 / 报告形态非法 → None（调用方转失败态，#122）
    no_s11 = {"verdict": "UNKNOWN",
              "summary": {"n_fail": 0, "n_unknown": 5, "fail_factors": [],
                          "unknown_factors": ["s11_dip"]},
              "criteria": []}
    assert default_edb_metrics(no_s11) is None
    assert default_edb_metrics("junk") is None  # type: ignore[arg-type]


# ─── 正常评估：判读单源指标 + cost 语义 ─────────────────────────────────────

def test_evaluate_normal_path(tmp_path):
    fake = FakeBuildSolve(tmp_path / "lane")
    launch = EdbLoopLauncher(TEMPLATE, workdir=tmp_path / "lane",
                             build_solve_fn=fake)
    res = launch.evaluate({"f0_ghz": F0})

    assert res.ok and res.error is None
    assert res.metrics is not None
    assert res.metrics["s11_dip_db"] == pytest.approx(-26.02, abs=1e-2)
    assert res.metrics["s11_dip_depth_db"] == pytest.approx(26.02, abs=1e-2)
    assert res.metrics["health_fail_count"] == 0.0
    assert res.metrics["health_verdict_fail"] == 0.0
    assert res.metrics["cost"] == pytest.approx(res.metrics["s11_dip_db"])
    assert res.metrics["s21_db_at_f0"] == pytest.approx(-3.61, abs=1e-2)
    assert res.metrics["s31_db_at_f0"] == pytest.approx(-3.61, abs=1e-2)
    # artifact=判读 Touchstone（在档自证）
    assert res.artifact is not None and res.artifact.endswith(".s3p")
    assert Path(res.artifact).exists()
    # 逐点产物名=模板键+参数指纹前缀（确定性，多点不互踩）
    assert fake.calls[0]["template"] == TEMPLATE
    assert fake.calls[0]["name"].startswith(TEMPLATE + "_")


def test_evaluate_gate_fail_penalty(tmp_path):
    """判读 FAIL 记惩罚：cost=惩罚×n_fail+谷深，ok 仍 True（非评估失败）。"""
    fake = FakeBuildSolve(tmp_path / "lane", s_for=lambda p: _mk_s(0.4, 0.42))
    launch = EdbLoopLauncher(TEMPLATE, workdir=tmp_path / "lane",
                             build_solve_fn=fake)
    res = launch.evaluate({"f0_ghz": F0})

    assert res.ok  # FAIL 是健康结论：照常产 metrics（环按惩罚 cost 淘汰）
    m = res.metrics
    assert m["health_fail_count"] == 2.0  # s11_dip + s_split_window
    assert m["health_verdict_fail"] == 1.0
    assert m["s11_dip_db"] == pytest.approx(-7.96, abs=1e-2)
    assert m["cost"] == pytest.approx(2 * DEFAULT_FAIL_PENALTY
                                      + m["s11_dip_db"])
    assert m["cost"] > 0  # 惩罚支配健康点量级


def test_cost_sign_deeper_dip_lower_cost(tmp_path):
    """任务书符号钉（越深越好）：同 FAIL 惩罚下谷越深 cost 越低。"""

    def eval_with(s11_mag: float) -> EvalResult:
        fake = FakeBuildSolve(tmp_path / f"lane_{s11_mag}",
                              s_for=lambda p: _mk_s(s11_mag, 0.42))
        launch = EdbLoopLauncher(TEMPLATE, workdir=tmp_path / f"lane_{s11_mag}",
                                 build_solve_fn=fake)
        return launch.evaluate({"f0_ghz": F0})

    deep = eval_with(0.05)     # -26.02 dB：FAIL 仅分配窗 1 条（s11 门过）
    shallow = eval_with(0.15)  # -16.48 dB：FAIL 同为分配窗 1 条（门仍过）
    assert deep.ok and shallow.ok
    assert deep.metrics["health_fail_count"] \
        == shallow.metrics["health_fail_count"] == 1.0
    assert deep.metrics["cost"] < shallow.metrics["cost"]


# ─── 发射失败：信封失败 from_error / 异常透传 / 缺 S11 如实失败 ─────────────

def test_evaluate_envelope_failure_returns_error(tmp_path):
    bad = error_envelope("ansysedt 缺装：批解发射失败",
                         build={"aedb_path": str(tmp_path / "x.aedb")})
    fake = FakeBuildSolve(tmp_path / "lane", envelope=bad)
    launch = EdbLoopLauncher(TEMPLATE, workdir=tmp_path / "lane",
                             build_solve_fn=fake)
    res = launch.evaluate({"f0_ghz": F0})

    assert not res.ok and res.metrics is None
    assert "ansysedt 缺装" in (res.error or "")
    assert res.artifact == str(tmp_path / "x.aedb")  # 工程路径兜底


def test_evaluate_exception_passthrough(tmp_path):
    """launcher 异常语义与 LocalLoopLauncher 同口径：透传（会话层记账）。"""
    fake = FakeBuildSolve(tmp_path / "lane",
                          exc=RuntimeError("watchdog 真跑 boom"))
    launch = EdbLoopLauncher(TEMPLATE, workdir=tmp_path / "lane",
                             build_solve_fn=fake)
    with pytest.raises(RuntimeError, match="watchdog 真跑 boom"):
        launch.evaluate({"f0_ghz": F0})


def test_evaluate_missing_touchstone_reports_missing_s11(tmp_path):
    """判读无 S11@f0（Touchstone 缺失→UNKNOWN）→ 缺省口径如实失败（#122）。"""
    no_export = ok_envelope(
        template=TEMPLATE,
        build={"ok": True, "aedb_path": str(tmp_path / "x.aedb"),
               "config_json_path": "cfg.json", "warnings": []},
        solve={"ok": True, "project": str(tmp_path / "x.aedb"),
               "solve": {"ok": True, "rc": 0, "timed_out": False,
                         "artifacts": [], "elapsed_s": 1.0},
               "export": None, "warnings": ["导出失败"]},
    )
    fake = FakeBuildSolve(tmp_path / "lane", envelope=no_export)
    launch = EdbLoopLauncher(TEMPLATE, workdir=tmp_path / "lane",
                             build_solve_fn=fake)
    res = launch.evaluate({"f0_ghz": F0})

    assert not res.ok and res.metrics is None
    assert "S11@f0" in (res.error or "")
    assert "s11_dip" in (res.error or "")  # 判读态 unknown/fail 点名
    assert res.artifact == str(tmp_path / "x.aedb")  # 工程路径兜底


# ─── Protocol 缝：提取器接管 / 门参数透传 / 模块属性解析 ────────────────────

def test_custom_extractor_takes_over_metrics(tmp_path):
    """注入 metric_extractor：指标/cost 语义整体接管（缺省键不叠加）。"""

    def extractor(report: dict) -> dict[str, float] | None:
        summary = report.get("summary")
        summary = summary if isinstance(summary, dict) else {}
        raw_fail = summary.get("n_fail")
        n_fail = 0.0 if raw_fail is None else float(raw_fail)
        return {"cost": n_fail * 7.0,
                "my_verdict_ok":
                    1.0 if report.get("verdict") == "PASS" else 0.0}

    fake = FakeBuildSolve(tmp_path / "lane")
    launch = EdbLoopLauncher(TEMPLATE, workdir=tmp_path / "lane",
                             build_solve_fn=fake, metric_extractor=extractor)
    res = launch.evaluate({"f0_ghz": F0})

    assert res.ok
    assert res.metrics == {"cost": 0.0, "my_verdict_ok": 1.0}  # 整体接管
    # 提取器返回 None → 如实失败态
    launch2 = EdbLoopLauncher(
        TEMPLATE, workdir=tmp_path / "lane",
        build_solve_fn=FakeBuildSolve(tmp_path / "lane"),
        metric_extractor=lambda report: None)
    res2 = launch2.evaluate({"f0_ghz": F0})
    assert not res2.ok and "指标提取未产出" in (res2.error or "")


def test_gate_override_plumbed(tmp_path):
    """s11_dip_gate_db 显式门透传健康门（最高优先级覆盖登记表/缺省门）。"""
    fake = FakeBuildSolve(tmp_path / "lane")  # 健康 S11@f0=-26 dB
    launch = EdbLoopLauncher(TEMPLATE, workdir=tmp_path / "lane",
                             build_solve_fn=fake, s11_dip_gate_db=-30.0)
    res = launch.evaluate({"f0_ghz": F0})

    assert res.ok
    assert res.metrics["health_fail_count"] == 1.0  # 仅 s11_dip 一条 FAIL
    assert res.metrics["cost"] == pytest.approx(
        DEFAULT_FAIL_PENALTY + res.metrics["s11_dip_db"])


def test_module_attribute_seam_monkeypatch(tmp_path, monkeypatch):
    """执行体模块属性惰性解析缝：monkeypatch edb_lane_service 等价 fake 面。"""
    from rfauto.service import edb_lane_service

    fake = FakeBuildSolve(tmp_path / "lane")
    monkeypatch.setattr(edb_lane_service, "edb_build_solve", fake)
    launch = EdbLoopLauncher(TEMPLATE, workdir=tmp_path / "lane")
    res = launch.evaluate({"f0_ghz": F0})
    assert res.ok and len(fake.calls) == 1


def test_params_merge_base_overridden(tmp_path):
    """evaluate params 同键覆盖构造器底座（环参数窗逐点注入语义）。"""
    fake = FakeBuildSolve(tmp_path / "lane")
    launch = EdbLoopLauncher(TEMPLATE, params={"f0_ghz": F0, "gap_mm": 6.0},
                             workdir=tmp_path / "lane", build_solve_fn=fake)
    launch.evaluate({"f0_ghz": 2.6})
    assert fake.calls[0]["params"] == {"f0_ghz": 2.6, "gap_mm": 6.0}


# ─── recipe_loop_remote 会话集成：三参数点发射/落账/回放 ────────────────────

def test_session_integration_three_points_and_replay(tmp_path):
    """EdbLoopLauncher 注入 RecipeLoopRemoteSession：三参数点批量发射→
    逐点落账→重启零发射完整回放（回放语义保持）。"""
    run_dir = tmp_path / "run"
    fake1 = FakeBuildSolve(tmp_path / "lane1")
    launch1 = EdbLoopLauncher(TEMPLATE, workdir=tmp_path / "lane1",
                              build_solve_fn=fake1)
    session1 = RecipeLoopRemoteSession(run_dir, launch1)
    outcomes = session1.evaluate_batch([dict(p) for p in POINTS])

    assert [o["action"] for o in outcomes] == ["launched"] * 3
    assert len(fake1.calls) == 3  # 评估一次=一次求解发射
    for o in outcomes:
        assert o["metrics"]["s11_dip_db"] == pytest.approx(-26.02, abs=1e-2)
        assert isinstance(o["metrics"]["cost"], float)
    assert len({c["name"] for c in fake1.calls}) == 3  # 逐点产物不互踩

    stats1 = session1.stats
    assert stats1["launcher"] == launch1.name == f"edb:{TEMPLATE}"
    assert stats1["n_launched"] == 3
    assert stats1["n_ledger_done"] == 3 and stats1["n_ledger_failed"] == 0

    # 重启：同 run_dir 重开会话 → 全命中 done 记录零发射，metrics 逐位一致
    fake2 = FakeBuildSolve(tmp_path / "lane2")
    launch2 = EdbLoopLauncher(TEMPLATE, workdir=tmp_path / "lane2",
                              build_solve_fn=fake2)
    session2 = RecipeLoopRemoteSession(run_dir, launch2)
    outcomes2 = session2.evaluate_batch([dict(p) for p in POINTS])

    assert fake2.calls == []  # 零发射
    assert [o["action"] for o in outcomes2] == ["replayed"] * 3
    for o1, o2 in zip(outcomes, outcomes2, strict=True):
        assert o2["metrics"] == o1["metrics"]
    assert session2.stats["n_launched"] == 0
    assert session2.stats["n_replayed"] == 3


def test_session_failure_recorded_then_retried(tmp_path):
    """信封级失败经会话如实落 failed 账本（#122）并上抛；重启失败点重试。"""
    bad = error_envelope("批解失败：rc=103 端口片交叠",
                         build={"aedb_path": "x/y.aedb"})
    run_dir = tmp_path / "run"
    session = RecipeLoopRemoteSession(
        run_dir,
        EdbLoopLauncher(TEMPLATE, workdir=tmp_path / "lane1",
                        build_solve_fn=FakeBuildSolve(
                            tmp_path / "lane1", envelope=bad)))
    with pytest.raises(RuntimeError, match="rc=103"):
        session.evaluate({"f0_ghz": F0})
    ledger = LoopLedger(run_dir / LEDGER_FILENAME)
    assert ledger.count_status("failed") == 1
    assert "rc=103" in (ledger.records[0].get("error") or "")

    # 重启健康 launcher：失败点重试（不跳过，failed 不进幂等表）
    healthy = FakeBuildSolve(tmp_path / "lane2")
    session2 = RecipeLoopRemoteSession(
        run_dir, EdbLoopLauncher(TEMPLATE, workdir=tmp_path / "lane2",
                                 build_solve_fn=healthy))
    outcomes = session2.evaluate_batch([{"f0_ghz": F0}])
    assert [o["action"] for o in outcomes] == ["launched"]
    assert len(healthy.calls) == 1
