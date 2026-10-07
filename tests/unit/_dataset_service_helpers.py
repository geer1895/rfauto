"""数据集服务测试共享基建——自 test_dataset_service.py 域拆分抽出。

本文件自 tests/unit/test_dataset_service.py 按被测域拆分而得
（W9 席，ge8e 后续批 P3，G1-4 登记伴生件）：纯搬运重构，类名/测试名/断言
逐字节保持，零语义变化。跨域共享基建抽至 tests/unit/_dataset_service_helpers.py
（同 _geometry_audit_helpers 包内导入惯例）；runs_env fixture 经
tests/unit/conftest.py re-export 供 pytest 解析（模块级导入会与测试参数
同名遮蔽触发 F401/F811，conftest 发现是 pytest 的正规机制）。

原模块头注释（拆分前原文，对本文件同样成立）：
构造临时 runs/（假 run：meta.json + trials/*.json + calibration/samples.json），
chdir 隔离零污染（#144）。依赖 duckdb/pyarrow（dataset extra），缺失时整文件
skip（fresh env 下的优雅降级）；缺依赖的显式报错分支用 monkeypatch sys.modules
钉住（#139 教训：不真打外部通道）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _meta(run_id: str, *, model: str, adapter: str = "fake",
          algorithm: str = "tune", study_name: str = "s1",
          seed: int | None = 42, status: str = "done") -> dict:
    return {
        "run_id": run_id, "model": model, "adapter": adapter,
        "algorithm": algorithm, "study_name": study_name, "seed": seed,
        "aedt_version": "fake", "ads_version": "", "git_sha": "abc1234",
        "timestamp": "2026-09-09T00:00:00+00:00", "status": status,
    }


@pytest.fixture
def runs_env(tmp_path, monkeypatch):
    """3+1 个假 run：run_a/run_b 同 study/seed 共享一个相同参数点（验证去重），
    run_c 是 calibration 产物（样本无逐点 cost），run_empty 无任何点级产物。"""
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "runs"
    # run_a：mline，两个 trial
    _write_json(root / "run_a" / "meta.json", _meta("run_a", model="mline"))
    _write_json(root / "run_a" / "trials" / "trial_0.json", {
        "trial_number": 0, "params": {"w_mm": 1.0},
        "metrics": {"s11_db_max_in_band": -10.0}, "cost": 0.05})
    _write_json(root / "run_a" / "trials" / "trial_1.json", {
        "trial_number": 1, "params": {"w_mm": 2.0},
        "metrics": {"s11_db_max_in_band": -20.0}, "cost": 0.5})
    # run_b：同 study/seed；trial_0 与 run_a.trial_0 同参点（应被去重），
    # trial_1 是新点
    _write_json(root / "run_b" / "meta.json", _meta("run_b", model="mline"))
    _write_json(root / "run_b" / "trials" / "trial_0.json", {
        "trial_number": 0, "params": {"w_mm": 1.0},
        "metrics": {"s11_db_max_in_band": -11.0}, "cost": 0.06})
    _write_json(root / "run_b" / "trials" / "trial_1.json", {
        "trial_number": 1, "params": {"w_mm": 3.0},
        "metrics": {"s11_db_max_in_band": -15.0}, "cost": 0.2})
    # run_c：patch_antenna，校准样本（真跑点，无逐点 cost）
    _write_json(root / "run_c" / "meta.json", _meta(
        "run_c", model="patch_antenna", adapter="calibration:openems",
        algorithm="calibration", study_name="calib_c", seed=None))
    _write_json(root / "run_c" / "calibration" / "samples.json", {
        "bounds": {"h_mm": [0.5, 2.5]}, "objectives": [],
        "samples": [
            {"params": {"h_mm": 1.2}, "metrics": {"gain_db": 5.0}},
            {"params": {"h_mm": 2.0}, "metrics": {"gain_db": 6.0}},
        ]})
    # run_empty：只有 meta，无任何点级产物（无产物 run 优雅处理）
    _write_json(root / "run_empty" / "meta.json", _meta("run_empty", model="mline"))
    return tmp_path


def _materialize_all(name: str = "demo"):
    from rfauto.service.dataset_service import materialize_dataset
    return materialize_dataset(None, name=name)


# ---------------------------------------------------------------------------
# ⑤ 单次 run 产物分支（api.run_once 通道，WP3.4 patch HFSS GT 战役）
# ---------------------------------------------------------------------------

def _write_touchstone(path: Path, n_ports: int) -> None:
    """合成 n 端口无源 Touchstone（skrf 写盘，健康门可读不误拦）：对角
    |S|=0.3，非对角均分 0.5——任一端口数下最大奇异值 0.8 < 1 无源。"""
    import numpy as np
    import skrf

    freq = skrf.Frequency(2.0, 3.0, 5, unit="GHz")
    s = np.zeros((5, n_ports, n_ports), dtype=complex)
    for i in range(n_ports):
        s[:, i, i] = 0.3
    if n_ports > 1:
        off = 0.5 / (n_ports - 1)
        for i in range(n_ports):
            for j in range(n_ports):
                if i != j:
                    s[:, i, j] = off
    path.parent.mkdir(parents=True, exist_ok=True)
    skrf.Network(frequency=freq, s=s, z0=50.0).write_touchstone(str(path))
