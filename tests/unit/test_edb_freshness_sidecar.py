"""EDB solve 产物指纹 sidecar 与健康门第 8 判据接线定向测试（aurora_l
Wave-F F2，全 fake 零真机）。

钉三面（C3 普查缺口「result_freshness 已落、链路暂无指纹落点」闭合）：

- 指纹存证：edb_lane_service.edb_touchstone_freshness 在 Touchstone 写盘
  后落 ``<touchstone>.freshness.json``（sha256/mtime/ports/generated_at/
  written_at，K4 runs_verify sidecar 同惯例——文件级自描述），edb_solve
  导出成功且产物在档时自动接线（产物不在档静默跳过不添告警——CLI/MCP
  fake 回执面 ``warnings == []`` 契约保持）；
- gate 接线：edb_loop_launcher 经 ``freshness_sidecar_path`` 单源读
  sidecar → expected 透传健康门第 8 判据——同文件复验 PASS / 内容顶替
  （sha 不符）FAIL / 旧文件顶替（mtime 更早）FAIL；
- SKIP 兼容：sidecar 缺失/损坏/无可核对字段 → expected None → SKIP
  （判据未启用态，不参与 verdict 聚合——增量兼容：verdict 与七判据
  时代逐位一致）。
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from rfauto.service import edb_lane_service as lane
from rfauto.service.edb_loop_launcher import (
    EdbLoopLauncher,
    default_edb_metrics,
)
from rfauto.service.envelope import ok_envelope

TEMPLATE = "edb_power_divider"
F0 = 2.5


# ---------------------------------------------------------------------------
# 合成数据助手（skrf 现场构造，零真机；test_edb_loop_launcher 同款口径：
# 20log10(0.05)=-26.02dB 过 -10dB 门，20log10(0.66)=-3.61dB 落分配窗）
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


def _by_factor(report: dict, factor: str) -> dict:
    """判读报告按 factor 键取判据条目（缺席即断言失败）。"""
    for c in report.get("criteria") or []:
        if isinstance(c, dict) and c.get("factor") == factor:
            return c
    raise AssertionError(f"factor {factor!r} 不在判读报告 criteria")


class _RecordingExtractor:
    """记录判读报告并回退缺省指标口径（metric_extractor 缝注入，报告侧
    断言用——launcher 无报告出口，经缝取单源）。"""

    def __init__(self) -> None:
        self.reports: list[dict] = []

    def __call__(self, report: dict) -> dict[str, float] | None:
        self.reports.append(report)
        return default_edb_metrics(report)


class _FakeBuildSolve:
    """假 edb_build_solve（真机契约同签名）：按 name 写 skrf 合成
    Touchstone（已存在则不重写——顶替类用例先布置产物再评估）+ 可选指纹
    sidecar，回 edb_build_solve 成功信封形态（build/solve 分节）。"""

    def __init__(self, snp_root: Path, s: np.ndarray | None = None,
                 *, write_sidecar: bool = False) -> None:
        self.snp_root = Path(snp_root)
        self.s = s if s is not None else _mk_s(0.05, 0.66)
        self.write_sidecar = write_sidecar

    def __call__(self, template: str, params: dict | None = None,
                 **kw: object) -> dict:
        name = str(kw.get("name") or template)
        snp = self.snp_root / f"{name}_export.s{self.s.shape[-1]}p"
        if not snp.is_file():
            _write_touchstone(snp, self.s, F0)
        sidecar = lane.freshness_sidecar_path(snp)
        if self.write_sidecar and not sidecar.is_file():
            lane.edb_touchstone_freshness(
                snp, n_ports=int(self.s.shape[-1]))
        aedb = self.snp_root / f"{name}.aedb"
        return ok_envelope(
            template=template,
            build={"ok": True, "aedb_path": str(aedb),
                   "config_json_path":
                       str(self.snp_root / f"{name}_config.json"),
                   "warnings": []},
            solve={"ok": True, "project": str(aedb),
                   "solve": {"ok": True, "rc": 0, "timed_out": False,
                             "message": "", "logfile": None,
                             "artifacts": [str(snp)], "elapsed_s": 1.0},
                   "export": {"ok": True, "out_file": str(snp),
                              "n_ports": int(self.s.shape[-1]), "rc": 0,
                              "timed_out": False, "logfile": None,
                              "errors": []},
                   "warnings": []},
        )


@pytest.fixture(autouse=True)
def _isolated_cwd(isolated_cache_off):
    yield


# ─── 指纹存证：writer 内容钉 ─────────────────────────────────────────────────

class TestFreshnessSidecarWriter:
    def test_sidecar_content_pins(self, tmp_path):
        """sidecar 落 <touchstone>.freshness.json：sha256=文件字节摘要、
        generated_at=落盘 mtime（恰等 PASS 语义的构建时刻钉）、ports/
        size/written_at 自描述齐备。"""
        ts = tmp_path / "x_export.s3p"
        ts.write_bytes(b"! synthetic touchstone\n# HZ S RI R 50\n")
        r = lane.edb_touchstone_freshness(ts, n_ports=3)
        assert r["ok"] is True
        sidecar = lane.freshness_sidecar_path(ts)
        assert r["path"] == str(sidecar)
        assert sidecar.is_file()
        raw = json.loads(sidecar.read_text(encoding="utf-8"))
        assert raw["sha256"] == hashlib.sha256(
            ts.read_bytes()).hexdigest()
        assert raw["mtime"] == pytest.approx(ts.stat().st_mtime)
        # generated_at 钉落盘 mtime（健康门 PASS 语义 mtime ≥ 生成时刻，
        # 同一 double 逐位相等=恰等 PASS）
        assert raw["generated_at"] == ts.stat().st_mtime
        assert raw["n_ports"] == 3
        assert raw["size"] == ts.stat().st_size
        assert raw["kind"] == "edb_touchstone_freshness"
        assert raw["generator"] == "rfauto.service.edb_lane_service"
        assert raw["schema_version"] == lane.FRESHNESS_SCHEMA_VERSION
        datetime.fromisoformat(raw["written_at"])  # ISO-8601 可解析

    def test_sidecar_path_naming_single_source(self, tmp_path):
        """命名单源：<touchstone>.freshness.json 后缀直拼（含 .aedb 工程
        名形态原样保留——writer/reader 同函数派生防漂移）。"""
        p = tmp_path / "x.aedb_export.s4p"
        assert lane.freshness_sidecar_path(p) == tmp_path / (
            "x.aedb_export.s4p.freshness.json")

    def test_missing_file_error_envelope(self, tmp_path):
        """产物不存在 → error 信封不抛异常（#105 best-effort 契约）。"""
        r = lane.edb_touchstone_freshness(tmp_path / "nope.s2p")
        assert r["ok"] is False
        assert r["errors"] and "不存在" in r["errors"][0]

    def test_non_int_ports_stored_null(self, tmp_path):
        """n_ports 非 int（含 bool 陷阱）如实存 null，不臆造。"""
        ts = tmp_path / "x_export.s2p"
        ts.write_bytes(b"x")
        for bad in (None, "3", 2.0, True):
            r = lane.edb_touchstone_freshness(ts, n_ports=bad)
            assert r["ok"] is True
            raw = json.loads(lane.freshness_sidecar_path(ts).read_text(
                encoding="utf-8"))
            assert raw["n_ports"] is None, f"n_ports={bad!r} 应存 null"


# ─── 指纹存证：edb_solve 链上自动接线 ────────────────────────────────────────

class _FakeSolveAdapter:
    """EdbAdapter 替身：solve_batch 回属性面齐备的命名空间（零真机）。"""

    def __init__(self, workdir):
        pass

    def solve_batch(self, aedb_path, timeout_s=3600.0):
        return SimpleNamespace(success=True, rc=0, timed_out=False,
                               message="", log_path=None, artifacts=[],
                               elapsed_s=1.0)


class TestSolveChainSidecar:
    def _solve(self, tmp_path: Path, monkeypatch,
               export_raw: dict) -> dict:
        monkeypatch.setattr("rfauto.adapters.edb_adapter.EdbAdapter",
                            _FakeSolveAdapter)
        monkeypatch.setattr(
            "rfauto.adapters.hfss_batch.export_touchstone_after_solve",
            lambda p, **kw: export_raw)
        proj = tmp_path / "demo.aedb"
        proj.mkdir(exist_ok=True)
        return lane.edb_solve(proj)

    def test_solve_writes_sidecar_and_envelope_pointer(
            self, tmp_path, monkeypatch):
        """导出成功且产物在档：sidecar 落盘 + export 节带
        freshness_sidecar 指针（C3「信封未落存证」缺口闭合）+ 零告警。"""
        ts = tmp_path / "demo_export.s3p"
        _write_touchstone(ts, _mk_s(0.05, 0.66), F0)
        r = self._solve(tmp_path, monkeypatch,
                        {"ok": True, "out_file": str(ts), "n_ports": 3,
                         "rc": 0, "timed_out": False, "logfile": None,
                         "errors": []})
        assert r["ok"] is True and r["export"]["ok"] is True
        assert r["export"]["freshness_sidecar"] == str(
            lane.freshness_sidecar_path(ts))
        assert lane.freshness_sidecar_path(ts).is_file()
        assert r["warnings"] == []

    def test_solve_missing_product_silent_skip(self, tmp_path, monkeypatch):
        """导出 ok 但产物不在档（fake 回执/异常链）：静默跳过不添告警
        ——存在性缺陷归健康门 touchstone 判据（CLI/MCP fake 面
        warnings==[] 契约保持），export 节不带指针。"""
        ghost = tmp_path / "ghost_export.s2p"  # 不存在
        r = self._solve(tmp_path, monkeypatch,
                        {"ok": True, "out_file": str(ghost), "n_ports": 2,
                         "rc": 0, "timed_out": False, "logfile": None,
                         "errors": []})
        assert r["ok"] is True
        assert r["warnings"] == []
        assert "freshness_sidecar" not in r["export"]
        assert not lane.freshness_sidecar_path(ghost).exists()


# ─── gate 接线：launcher 读 sidecar → 第 8 判据 ──────────────────────────────

class TestGateWiring:
    def _launcher(self, tmp_path: Path, fake: _FakeBuildSolve,
                  extractor: _RecordingExtractor) -> EdbLoopLauncher:
        return EdbLoopLauncher(
            TEMPLATE, workdir=tmp_path / "lane", build_solve_fn=fake,
            metric_extractor=extractor)

    def test_sidecar_present_freshness_pass(self, tmp_path):
        """sidecar 在档且未顶替：expected 透传 → result_freshness PASS，
        verdict 全 PASS 不被第 8 判据扰动。"""
        fake = _FakeBuildSolve(tmp_path / "lane", write_sidecar=True)
        rec = _RecordingExtractor()
        res = self._launcher(tmp_path, fake, rec).evaluate({"f0_ghz": F0})

        assert res.ok and res.metrics is not None
        assert res.metrics["health_fail_count"] == 0.0
        (report,) = rec.reports
        f = _by_factor(report, "result_freshness")
        assert f["status"] == "PASS"
        assert report["verdict"] == "PASS"
        assert report["summary"]["skip_factors"] == []

    def test_content_tamper_sha_fail(self, tmp_path):
        """内容顶替：sidecar 落证后重写合法但不同内容的 Touchstone
        （mtime 更新 ≥ 生成时刻，仅 sha 失配）→ FAIL 且是唯一红判据。"""
        fake = _FakeBuildSolve(tmp_path / "lane", write_sidecar=True)
        rec1 = _RecordingExtractor()
        assert self._launcher(tmp_path, fake, rec1).evaluate(
            {"f0_ghz": F0}).ok
        snp = Path(str(_by_factor(rec1.reports[0], "touchstone")
                       ["evidence"]["path"]))
        _write_touchstone(snp, _mk_s(0.06, 0.66), F0)  # 篡改内容（合法形态）

        rec2 = _RecordingExtractor()
        res2 = self._launcher(tmp_path, fake, rec2).evaluate({"f0_ghz": F0})
        assert res2.ok  # FAIL 是健康结论非评估失败
        f = _by_factor(rec2.reports[0], "result_freshness")
        assert f["status"] == "FAIL"
        assert "sha256 不符" in f["detail"]
        assert rec2.reports[0]["summary"]["fail_factors"] == [
            "result_freshness"]

    def test_old_file_substitution_mtime_fail(self, tmp_path):
        """旧文件顶替：同内容回拨 mtime 早于构建记录生成时刻（sha 相符）
        → FAIL 点名顶替嫌疑。"""
        fake = _FakeBuildSolve(tmp_path / "lane", write_sidecar=True)
        rec1 = _RecordingExtractor()
        assert self._launcher(tmp_path, fake, rec1).evaluate(
            {"f0_ghz": F0}).ok
        snp = Path(str(_by_factor(rec1.reports[0], "touchstone")
                       ["evidence"]["path"]))
        raw = json.loads(lane.freshness_sidecar_path(snp).read_text(
            encoding="utf-8"))
        stale = float(raw["generated_at"]) - 100.0
        os.utime(snp, (stale, stale))

        rec2 = _RecordingExtractor()
        res2 = self._launcher(tmp_path, fake, rec2).evaluate({"f0_ghz": F0})
        assert res2.ok
        f = _by_factor(rec2.reports[0], "result_freshness")
        assert f["status"] == "FAIL"
        assert "旧文件顶替" in f["detail"]
        assert rec2.reports[0]["summary"]["fail_factors"] == [
            "result_freshness"]

    def test_missing_sidecar_skip_incremental_compat(self, tmp_path):
        """sidecar 缺失（老信封/手构信封）→ expected None → SKIP：不参与
        verdict 聚合（增量兼容钉——fail/unknown 三账与七判据时代逐位
        一致），metrics/cost 不降级。"""
        fake = _FakeBuildSolve(tmp_path / "lane", write_sidecar=False)
        rec = _RecordingExtractor()
        res = self._launcher(tmp_path, fake, rec).evaluate({"f0_ghz": F0})

        assert res.ok and res.metrics is not None
        (report,) = rec.reports
        f = _by_factor(report, "result_freshness")
        assert f["status"] == "SKIP"
        assert report["summary"]["n_skip"] == 1
        assert report["summary"]["skip_factors"] == ["result_freshness"]
        assert report["summary"]["fail_factors"] == []
        assert report["summary"]["unknown_factors"] == []
        assert report["verdict"] == "PASS"
        # cost 未被第 8 判据扰动（=s11 谷深，零 FAIL 零惩罚贡献）
        assert res.metrics["cost"] == pytest.approx(
            res.metrics["s11_dip_db"])

    def test_corrupt_or_empty_sidecar_skip(self, tmp_path):
        """sidecar 损坏（非 JSON）/无可核对字段（空 dict）→ 一律 SKIP
        （best-effort #105：不可读不阻塞评估链，不冒充 FAIL/PASS）。"""
        fake = _FakeBuildSolve(tmp_path / "lane", write_sidecar=True)
        rec1 = _RecordingExtractor()
        assert self._launcher(tmp_path, fake, rec1).evaluate(
            {"f0_ghz": F0}).ok
        snp = Path(str(_by_factor(rec1.reports[0], "touchstone")
                       ["evidence"]["path"]))
        sidecar = lane.freshness_sidecar_path(snp)

        for payload in ("{not json", "{}"):
            sidecar.write_text(payload, encoding="utf-8")
            rec = _RecordingExtractor()
            res = self._launcher(tmp_path, fake, rec).evaluate(
                {"f0_ghz": F0})
            assert res.ok
            assert _by_factor(rec.reports[0],
                              "result_freshness")["status"] == "SKIP"
