"""T-N8 storage 旋钮单测（aurora_n W1-A）——JournalStorage 接进 run_optimization。

判据（任务书预声明，runs/aurora_n/recon/PROPOSALS.md §T-N8）：
- 缺省 storage="sqlite"=旧路径逐字节等价（get_storage_path() 原样、输出
  键集不变、不进 resolve_storage）；
- storage="journal"：JournalStorage 生效（result.storage_backend="journal"）；
  重启 resume trial 计数一致（每次 run_optimization 新建 JournalStorage
  实例回读同一 journal 文件=跨进程/重启语义）；双进程并发 ask/tell 同
  study 无锁异常（合成目标，subprocess 真双进程）；文件损坏显式报错并
  提示回退 sqlite（fallback_reason 非空，#122 不静默）；
- 未知 storage 值 / journal_path 错配 = ok=False 显性错误；
- #144 chdir 隔离：全部 tmp cwd，journal 文件一律显式 journal_path 落
  tmp_path，禁污染真实 runs/。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import optuna
import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from rfauto.optimization.optimizer import run_optimization
from rfauto.optimization.storage_backends import build_journal_storage

# optuna INFO 日志（逐 trial 一行）不污染门输出
optuna.logging.set_verbosity(optuna.logging.WARNING)


@pytest.fixture
def wilkinson_recipe(tmp_path):
    """最小化 Wilkinson 配方（与 test_batch_optimization.py 同构）。"""
    recipe = {
        "model": "wilkinson_power_divider",
        "params": {
            "f0_ghz": {"value": 2.4, "unit": "GHz"},
            "z0_ohm": {"value": 50, "unit": "ohm"},
            "substrate": "rogers4350b_h0.508",
            "division": "1:1",
            "arm_len_mm": {"value": 20.5},
            "series_w_mm": {"value": 0.33},
            "shunt_w_mm": {"value": 1.10},
        },
        "setup": {"freq_range_ghz": [1.5, 3.5], "points": 101},
        "objectives": [
            {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below",
             "value": -15},
        ],
        "optimization": {
            "params": {
                "arm_len_mm": {"low": 18.0, "high": 23.0},
                "series_w_mm": {"low": 0.25, "high": 0.45},
            },
        },
    }
    path = tmp_path / "wilkinson_pd_v1.yaml"
    path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
    return str(path)


def _run_isolated(tmp_path, monkeypatch, tag: str, recipe: str, **kw):
    """独立 cwd + 私有 storage 跑一轮（#144 chdir 隔离；journal 档显式路径）。"""
    d = tmp_path / tag
    d.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(d)
    monkeypatch.setenv("RFAUTO_CACHE", "off")
    storage = kw.pop("_private_sqlite", None)
    if storage is None:
        db_dir = d / "runs" / ".optuna"
        db_dir.mkdir(parents=True, exist_ok=True)
        storage = f"sqlite:///{(db_dir / 'optuna.db').as_posix()}"
        monkeypatch.setattr(
            "rfauto.optimization.optimizer.get_storage_path",
            lambda: storage)
    result = run_optimization(recipe, adapter_name="fake", **kw)
    return result, storage


class TestStorageKnobDefaultEquivalence:
    """缺省=旧路径逐字节等价（红线 1：旋钮全 opt-in）。"""

    def test_default_and_explicit_sqlite_identical(
            self, tmp_path, monkeypatch, wilkinson_recipe):
        """不传旋钮 vs storage="sqlite"：固定种子同 budget 轨迹+终值一致。

        回显逐字节口径：各自隔离 cwd 下 result["storage"] 恒等于本轮
        get_storage_path() 钉住值（旧行为=result 即 get_storage_path()
        返回串），且不新增 storage_backend 键。
        """
        r_a, url_a = _run_isolated(
            tmp_path, monkeypatch, "legacy", wilkinson_recipe,
            max_trials=5, study_name="eq_probe", seed=42)
        r_b, url_b = _run_isolated(
            tmp_path, monkeypatch, "explicit", wilkinson_recipe,
            max_trials=5, study_name="eq_probe", seed=42, storage="sqlite")
        assert r_a["ok"] and r_b["ok"], (r_a.get("errors"), r_b.get("errors"))
        assert r_a["best_cost"] == r_b["best_cost"]
        assert r_a["best_params"] == r_b["best_params"]
        assert r_a["storage"] == url_a
        assert r_b["storage"] == url_b
        assert "storage_backend" not in r_a
        assert "storage_backend" not in r_b
        assert "storage_fallback_reason" not in r_a
        assert "storage_fallback_reason" not in r_b

    def test_journal_path_with_default_sqlite_rejected(
            self, tmp_path, monkeypatch, wilkinson_recipe):
        """journal_path 与缺省 sqlite 档错配=显式报错（不静默吞参数）。"""
        r, _ = _run_isolated(
            tmp_path, monkeypatch, "mismatch", wilkinson_recipe,
            max_trials=2, journal_path=tmp_path / "j.log")
        assert r["ok"] is False
        assert any("journal_path" in e for e in r["errors"])

    def test_unknown_storage_value_rejected(
            self, tmp_path, monkeypatch, wilkinson_recipe):
        """未知 storage 值=ok=False 显性错误（配置错误必须暴露）。"""
        r, _ = _run_isolated(
            tmp_path, monkeypatch, "badval", wilkinson_recipe,
            max_trials=2, storage="mysql")
        assert r["ok"] is False
        assert any("未知 storage" in e for e in r["errors"])


class TestJournalKnob:
    """storage="journal" 档：生效/持久/resume 计数一致。"""

    def test_journal_mode_runs_and_persists(
            self, tmp_path, monkeypatch, wilkinson_recipe):
        jp = tmp_path / "j" / "optuna_journal.log"
        r, _ = _run_isolated(
            tmp_path, monkeypatch, "journal", wilkinson_recipe,
            max_trials=5, study_name="jn_probe", seed=42,
            storage="journal", journal_path=jp)
        assert r["ok"], r.get("errors")
        assert r["storage_backend"] == "journal"
        assert r["storage"].startswith("journal://")
        assert "storage_fallback_reason" not in r
        # 回显 URL 指向显式 journal 文件（JSON 可序列化描述，非对象）
        assert json.dumps(r)  # 信封可 JSON 序列化（journal:// 字符串面）
        # 新 storage 实例回读同一文件=跨进程可见（持久性）
        study = optuna.load_study(
            study_name="jn_probe", storage=build_journal_storage(jp))
        assert len(study.get_trials(deepcopy=False)) == 5

    def test_journal_resume_trial_count_consistent(
            self, tmp_path, monkeypatch, wilkinson_recipe):
        """确定性钉（任务书：重启 resume trial 计数一致）。

        每次 run_optimization 都从磁盘新建 JournalStorage（重启语义）：
        第二次 run 的 existing_trials 必须=第一次的总量，且两轮合计
        7 trial 全部经新实例回读可见。
        """
        jp = tmp_path / "j" / "resume.log"
        r1, _ = _run_isolated(
            tmp_path, monkeypatch, "resume1", wilkinson_recipe,
            max_trials=4, study_name="rs_probe", seed=42,
            storage="journal", journal_path=jp)
        assert r1["ok"], r1.get("errors")
        assert r1["trials_total"] == 4
        r2, _ = _run_isolated(
            tmp_path, monkeypatch, "resume2", wilkinson_recipe,
            max_trials=3, study_name="rs_probe", seed=43,
            storage="journal", journal_path=jp)
        assert r2["ok"], r2.get("errors")
        assert r2["storage_backend"] == "journal"
        assert r2["existing_trials"] == 4
        assert r2["trials_total"] == 7
        study = optuna.load_study(
            study_name="rs_probe", storage=build_journal_storage(jp))
        trials = study.get_trials(deepcopy=False)
        assert len(trials) == 7
        assert sum(1 for t in trials
                   if t.state == optuna.trial.TrialState.COMPLETE) == 7


class TestJournalCorruptionFallback:
    """负例：journal 文件损坏=显式报错并提示回退 sqlite（不静默）。"""

    def test_corrupted_journal_falls_back_with_reason(
            self, tmp_path, monkeypatch, wilkinson_recipe):
        """合法 journal 追加损坏行 → 回退 SQLite + fallback_reason 非空。

        实测口径（会话探针 probe_tn8_corrupt.py，2026-10-29）：损坏行使
        resolve_storage 探测期回读抛 JSONDecodeError → 回退档如实记账。
        """
        jp = tmp_path / "j" / "corrupt.log"
        r1, _ = _run_isolated(
            tmp_path, monkeypatch, "corrupt_seed", wilkinson_recipe,
            max_trials=2, study_name="cp_probe", seed=42,
            storage="journal", journal_path=jp)
        assert r1["ok"] and r1["storage_backend"] == "journal"
        # 注入损坏行（真 journal + 尾部非 JSON 字节）
        with open(jp, "ab") as f:
            f.write(b"CORRUPTED-LINE-NOT-JSON\n")
        r2, _ = _run_isolated(
            tmp_path, monkeypatch, "corrupt_run", wilkinson_recipe,
            max_trials=2, study_name="cp_probe2", seed=42,
            storage="journal", journal_path=jp)
        assert r2["ok"] is True  # 回退后任务照常完成
        assert r2["storage_backend"] == "sqlite"
        reason = r2["storage_fallback_reason"]
        assert reason and "回退 SQLite" in reason
        assert "storage" in r2  # 回显面=回退后的 sqlite URL
        # 回退档 trial 真实落在 sqlite（结果不是假的 ok）
        assert r2["trials_completed"] == 2

    def test_garbage_journal_falls_back_with_reason(
            self, tmp_path, monkeypatch, wilkinson_recipe):
        jp = tmp_path / "j" / "garbage.log"
        jp.parent.mkdir(parents=True, exist_ok=True)
        jp.write_bytes(b"\x00\x01garbage not a journal\xff" * 10)
        r, _ = _run_isolated(
            tmp_path, monkeypatch, "garbage", wilkinson_recipe,
            max_trials=2, study_name="gb_probe", seed=42,
            storage="journal", journal_path=jp)
        assert r["ok"] is True
        assert r["storage_backend"] == "sqlite"
        assert r["storage_fallback_reason"]


# ---------------------------------------------------------------------------
# 双进程并发 ask/tell 同 study（合成目标，subprocess 真双进程）
# ---------------------------------------------------------------------------

_DRIVER = r'''# -*- coding: utf-8 -*-
"""T-N8 并发驱动：对同一 journal 文件 ask/tell N trial（合成目标 x^2）。"""
import sys

import optuna

optuna.logging.set_verbosity(optuna.logging.WARNING)

from rfauto.optimization.storage_backends import build_journal_storage

journal_path, study_name, n_trials, tag = (
    sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4])

storage = build_journal_storage(journal_path)
study = optuna.create_study(
    study_name=study_name, storage=storage, load_if_exists=True,
    sampler=optuna.samplers.TPESampler(seed=hash(tag) % (2**31)))


def objective(trial):
    x = trial.suggest_float("x", -10.0, 10.0)
    return x * x  # 合成目标（任务书口径），零真机


study.optimize(objective, n_trials=n_trials)
print(f"DONE {tag} n={len(study.get_trials(deepcopy=False))}")
'''


class TestTwoProcessConcurrency:
    """验收草案：双进程并发 ask/tell 同 study 无锁异常（合成目标）。"""

    def test_two_processes_same_journal_no_lock_error(
            self, tmp_path, wilkinson_recipe):
        driver = tmp_path / "_tn8_concurrency_driver.py"
        driver.write_text(_DRIVER, encoding="utf-8")
        jp = tmp_path / "j" / "concurrent.log"
        jp.parent.mkdir(parents=True, exist_ok=True)  # JournalFileBackend 不建父目录
        study_name = "cc_probe"

        procs = []
        for tag in ("procA", "procB"):
            p = subprocess.Popen(
                [sys.executable, str(driver), str(jp), study_name, "5", tag],
                cwd=str(tmp_path), stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding="utf-8")
            procs.append((tag, p))
        outs = []
        for tag, p in procs:
            out, err = p.communicate(timeout=180)
            outs.append((tag, p.returncode, out, err))

        for tag, rc, out, err in outs:
            assert rc == 0, f"{tag} rc={rc}\nstdout={out}\nstderr={err}"
            assert "DONE" in out, f"{tag} 未完成: {out}"
            # 无锁异常面（SQLite 文件锁争用/journal 锁 OSError 均属失败）
            for bad in ("database is locked", "OSError", "WinError",
                        "Traceback"):
                assert bad not in err, f"{tag} stderr 含 {bad}: {err}"

        # 父进程新实例回读：两进程 10 trial 全部落账（零丢失零重复异常）
        study = optuna.load_study(
            study_name=study_name, storage=build_journal_storage(jp))
        trials = study.get_trials(deepcopy=False)
        assert len(trials) == 10
        assert all(t.state == optuna.trial.TrialState.COMPLETE
                   for t in trials)
