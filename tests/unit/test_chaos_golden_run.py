"""R5 混沌档：黄金 run steady state + 产物故障注入 → 断言 fail-closed。

（月计划 E 流 R5 / B4 韧性批；判读链=service/health_service.health_check_run
→ core/solve_health 九因子 verdict 链，全部离线合成、零真机零网络。）

正控（先证明 fixture 本身健康，再注入——否则注入红可能是 fixture 坏）：
黄金 run 装齐 openEMS 单激励产物族（sparams.csv 掩码载体 + trials cost +
引擎 log timestep + port_beta.csv εeff + meta.json）→ verdict=healthy。

四类故障注入与 fail-closed 断言方向（不凑绿：注入维度因子必须
FAIL/UNKNOWN，绝不 PASS；FAIL 证据必须 verdict=unhealthy）：

1. 截断引擎日志（et/ht/log 时间轴产物家族）：timestep 因子不再 PASS
   （无记录 → UNKNOWN，#152 产物缺失不误报语义）；
2. 损坏 sparams.csv（掩码载体=证据本体）：S 参数因子族全不 PASS +
   errors 留痕 + **不回退 Touchstone**（round5 C-F1：即使健康 Touchstone
   在场，损坏 csv 也不许静默顶替——注入双产物验证）；
3. 零填充（激励体积死 #174 / cost 退化常数 #195）：verdict=unhealthy
   硬 FAIL，因子级 excitation/cost_distribution=FAIL；
4. 杀进程模拟（求解中死=半行 csv + 半截 meta.json）：S 因子不 PASS +
   errors 留痕 + meta 摘要缺席如实暴露（"有 trials/无 meta" 在跑签名，
   meta.json 结束才落盘——#144 口径）。
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from rfauto.service.health_service import health_check_run

_C0 = 299792458.0
_EPS_EFF = 2.33
_N_FREQ = 32


# ---------------------------------------------------------------------------
# 黄金 steady-state fixture
# ---------------------------------------------------------------------------

def _write_sparams_csv(path: Path, *, zero: bool = False) -> None:
    """2 端口健康 sparams.csv（openEMS 单激励 5 列 schema；zero=全零注入）。"""
    freq = np.linspace(2.0e9, 3.0e9, _N_FREQ)
    if zero:
        s11 = np.zeros(_N_FREQ, dtype=complex)
        s21 = np.zeros(_N_FREQ, dtype=complex)
    else:
        s11 = 0.1 * np.exp(1j * np.linspace(-0.5, 0.5, _N_FREQ))   # ≈−20dB
        s21 = 0.7071067811865476 * np.exp(1j * np.linspace(-2.0, -3.0, _N_FREQ))
    lines = ["freq_hz,s11_re,s11_im,s21_re,s21_im"]
    # .tolist() 转 Python float：numpy 2 的 repr 是 np.float64(...) 字面量，
    # np.loadtxt 解析不了（测试件自身产物的坑，非被测链路）
    for f, a, b in zip(freq.tolist(), s11.tolist(), s21.tolist(),
                       strict=True):
        lines.append(f"{f!r},{a.real!r},{a.imag!r},{b.real!r},{b.imag!r}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_port_beta(path: Path) -> None:
    """port_beta.csv：双端口 β 对应同 εeff=2.33（probe 比值 1.0≠1.04 窗）。"""
    freq = np.linspace(2.0e9, 3.0e9, _N_FREQ)
    beta = 2.0 * math.pi * freq * math.sqrt(_EPS_EFF) / _C0
    lines = ["freq_hz,beta1_rad_per_m,beta2_rad_per_m"]
    for f, b in zip(freq.tolist(), beta.tolist(), strict=True):
        lines.append(f"{f!r},{b!r},{b!r}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_golden_run(root: Path, run_id: str = "golden_ss") -> Path:
    """黄金 steady-state run：G11 九因子无 FAIL 无 WARN 的合成稳态产物族。"""
    run_dir = root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "meta.json").write_text(json.dumps({
        "run_id": run_id, "model": "wilkinson_power_divider",
        "adapter": "openems", "status": "finished",
    }, ensure_ascii=False), encoding="utf-8")
    _write_sparams_csv(run_dir / "results" / "sparams.csv")
    trials = run_dir / "trials"
    trials.mkdir(exist_ok=True)
    for i, cost in enumerate([3.9, 2.1, 0.5, 1.2, 3.3, 0.8]):  # 非退化 6 点
        (trials / f"trial_{i}.json").write_text(json.dumps({
            "trial_number": i, "cost": cost}), encoding="utf-8")
    (run_dir / "fdtd").mkdir(exist_ok=True)
    (run_dir / "fdtd" / "engine.log").write_text(
        "[openEMS] FDTD timestep is: 1.7e-13 s\n"
        "[openEMS] FDTD timestep is: 1.7e-13 s\n", encoding="utf-8")
    _write_port_beta(run_dir / "results" / "port_beta.csv")
    return run_dir


def _report(tmp_path: Path, run_id: str = "golden_ss") -> dict:
    return health_check_run(run_id, runs_dir=tmp_path)


def _factor_map(report: dict) -> dict:
    return {f["factor"]: f["status"] for f in report.get("factors") or []}


def _assert_s_family_not_pass(statuses: dict) -> None:
    """S 参数因子族（依赖 sparams.csv 证据的四个因子）全不 PASS。"""
    for name in ("excitation", "passivity", "reciprocity", "gain"):
        assert statuses.get(name) != "PASS", \
            f"证据损坏后 {name} 因子仍 PASS=凑绿（fail-closed 违约）"


# ---------------------------------------------------------------------------
# 正控：黄金 fixture 本身必须 healthy（否则注入红不可归因）
# ---------------------------------------------------------------------------

class TestGoldenSteadyState:
    def test_golden_run_is_healthy_positive_control(self, tmp_path):
        build_golden_run(tmp_path)
        report = _report(tmp_path)
        assert report["ok"] is True, report.get("errors")
        assert report["verdict"] == "healthy"
        statuses = _factor_map(report)
        assert statuses["excitation"] == "PASS"
        assert statuses["cost_distribution"] == "PASS"
        assert statuses["timestep"] == "PASS"
        assert statuses["passivity"] == "PASS"
        assert json.dumps(report, ensure_ascii=False)  # JSON 友好契约


# ---------------------------------------------------------------------------
# 注入①：截断引擎日志（et/时间轴产物家族）
# ---------------------------------------------------------------------------

class TestTruncatedLogInjection:
    def test_truncated_log_timestep_factor_not_pass(self, tmp_path):
        run_dir = build_golden_run(tmp_path)
        log = run_dir / "fdtd" / "engine.log"
        text = log.read_text(encoding="utf-8")
        log.write_text(text[: len(text) // 2], encoding="utf-8")  # 半行截断
        report = _report(tmp_path)
        statuses = _factor_map(report)
        # 半行截断：首行完好+次行成残行 → 仅 1 条有效记录 → UNKNOWN
        #（不足 2 条无法比较 min/max 比，#152 不误报；精确钉取代 !=PASS）
        assert statuses["timestep"] == "UNKNOWN"
        # 截断只伤时间轴：UNKNOWN 非 FAIL 非 WARN → verdict 不降级，
        # 收窄断言到具体值（P3-8：原 in (healthy,suspect,unhealthy) 恒真）
        assert report["verdict"] == "healthy"

    def test_fully_truncated_log_zero_timestep_records(self, tmp_path):
        build_golden_run(tmp_path)
        run_dir = tmp_path / "golden_ss"
        (run_dir / "fdtd" / "engine.log").write_text("", encoding="utf-8")
        report = _report(tmp_path)
        assert _factor_map(report)["timestep"] == "UNKNOWN"
        assert report["verdict"] == "healthy"  # 缺失不误报，其余因子全 PASS


# ---------------------------------------------------------------------------
# 注入②：损坏 sparams.csv（掩码载体=证据损坏，不回退 Touchstone）
# ---------------------------------------------------------------------------

class TestCorruptedCsvInjection:
    def test_binary_garbage_csv_fails_closed_no_touchstone_fallback(
            self, tmp_path):
        run_dir = build_golden_run(tmp_path)
        csv_path = run_dir / "results" / "sparams.csv"
        csv_path.write_bytes(b"\x00\x01\xff garbage,not,numbers\r\n\x01\x02\r\n")
        # 同时在场一份"健康" Touchstone：损坏 csv 也不许被静默顶替
        _write_touchstone_healthy(run_dir / "results" / "params.s2p")
        report = _report(tmp_path)
        statuses = _factor_map(report)
        _assert_s_family_not_pass(statuses)
        errors = " ".join(report.get("errors") or [])
        assert "sparams.csv" in errors, "损坏必须 errors 留痕（#316 多报方向）"
        assert "不回退" in errors

    def test_wrong_column_count_csv_rejected(self, tmp_path):
        run_dir = build_golden_run(tmp_path)
        (run_dir / "results" / "sparams.csv").write_text(
            "freq_hz,s11_re\n2.0e9,0.1\n", encoding="utf-8")
        report = _report(tmp_path)
        _assert_s_family_not_pass(_factor_map(report))
        assert report.get("errors")


def _write_touchstone_healthy(path: Path) -> None:
    """健康 2 端口 Touchstone（dB/角度经典格式，S21≈−3dB）——回退诱饵。"""
    freq = np.linspace(2.0e9, 3.0e9, _N_FREQ)
    lines = ["# GHZ S DB R 50"]
    for f in freq.tolist():
        f_ghz = f / 1e9
        lines.append(
            f"{f_ghz:.9f} -20 0 -3 -90 "
            f"-3 -90 -20 0")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# 注入③：零填充（激励体积死 / cost 退化）
# ---------------------------------------------------------------------------

class TestZeroFillInjection:
    def test_zero_filled_sparams_excitation_dead_unhealthy(self, tmp_path):
        run_dir = build_golden_run(tmp_path)
        _write_sparams_csv(run_dir / "results" / "sparams.csv", zero=True)
        report = _report(tmp_path)
        statuses = _factor_map(report)
        assert statuses["excitation"] == "FAIL", "全零 S=激励体积死（#174）必须 FAIL"
        assert report["verdict"] == "unhealthy", \
            "FAIL 证据在场上 verdict 不许 healthy/suspect"

    def test_zero_filled_cost_constant_degenerate_unhealthy(self, tmp_path):
        run_dir = build_golden_run(tmp_path)
        trials = run_dir / "trials"
        for p in sorted(trials.glob("trial_*.json")):
            data = json.loads(p.read_text(encoding="utf-8"))
            data["cost"] = 2.0  # 恒常数（#195 退化）
            p.write_text(json.dumps(data), encoding="utf-8")
        report = _report(tmp_path)
        statuses = _factor_map(report)
        assert statuses["cost_distribution"] == "FAIL"
        assert report["verdict"] == "unhealthy"


# ---------------------------------------------------------------------------
# 注入④：杀进程模拟（半写产物 = 求解中死亡现场）
# ---------------------------------------------------------------------------

class TestKilledProcessInjection:
    def test_mid_write_death_fails_closed(self, tmp_path):
        """半行 csv + 半截 meta.json：证据损坏 + 记账缺席都必须如实浮出。"""
        run_dir = build_golden_run(tmp_path)
        csv_path = run_dir / "results" / "sparams.csv"
        lines = csv_path.read_text(encoding="utf-8").splitlines()
        csv_path.write_text("\n".join(lines[: len(lines) // 2]) + "\n2.5e9,0.0",
                            encoding="utf-8")  # 尾行撕裂（列数不足）
        meta = run_dir / "meta.json"
        meta.write_text('{"run_id": "golden_ss", "sta', encoding="utf-8")
        report = _report(tmp_path)
        statuses = _factor_map(report)
        _assert_s_family_not_pass(statuses)
        assert report.get("errors"), "撕裂产物必须 errors 留痕"
        assert "meta" not in report, \
            "meta 撕裂=摘要缺席必须如实暴露（不可用残缺 meta 凑摘要）"

    def test_inflight_signature_no_meta_no_fake_summary(self, tmp_path):
        """在跑签名（有 trials/无 meta，#144）：健康产物不虚判，摘要缺席。"""
        build_golden_run(tmp_path)
        (tmp_path / "golden_ss" / "meta.json").unlink()
        report = _report(tmp_path)
        assert report["verdict"] == "healthy"  # 产物族完整，体检面如实健康
        assert "meta" not in report, "无 meta 不许伪造摘要键"


# ---------------------------------------------------------------------------
# 多故障叠加：FAIL 不被 UNKNOWN 稀释
# ---------------------------------------------------------------------------

class TestStackedInjections:
    def test_zero_fill_plus_corrupt_csv_still_unhealthy(self, tmp_path):
        run_dir = build_golden_run(tmp_path)
        run_dir2 = run_dir  # 同一现场：csv 先撕裂再零填充写坏
        _ = run_dir2
        (run_dir / "results" / "sparams.csv").write_bytes(
            b"\x00garbage\r\n\r\n\x01")
        trials = run_dir / "trials"
        for p in sorted(trials.glob("trial_*.json")):
            data = json.loads(p.read_text(encoding="utf-8"))
            data["cost"] = 7.0
            p.write_text(json.dumps(data), encoding="utf-8")
        report = _report(tmp_path)
        assert report["verdict"] == "unhealthy"
        statuses = _factor_map(report)
        assert statuses["cost_distribution"] == "FAIL"
        _assert_s_family_not_pass(statuses)
