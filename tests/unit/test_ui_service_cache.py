"""架构批 A2-D：ui_service runs/ 扫描端点缓存行为单测。

覆盖面：
- 缓存原语（_UiScanCache）：TTL 内零重扫（producer 计数桩）/签名变化
  失效/TTL 过期失效/签名不可得直通不落缓存/env 关闭直通不计数；
- 端点级语义：校准清单二跑零重扫；既有 run 目录内新建 gate.json（目录
  mtime 变化）不等 TTL 立即可见；同名文件就地改写 TTL 内读旧值、超龄后
  可见（宁多扫不多旧的兜底面，语义如实钉住）；env RFAUTO_UI_CACHE=0
  全直通；deepcopy 隔离；不同 limit 共享同一全量快照；
- schema 逐字节不变：5 端点新实现（miss/hit/env-off 三路）与改造前旧
  实现参考副本（root 参数化）在同一输入树上 json 逐字节相等；
- h5 探测缓存与 JSON 文件缓存的 (mtime_ns, size) 失效。
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path

import pytest

from rfauto.service import p0_gate_service, ui_scan_cache, ui_service
from rfauto.service.ui_service import (
    _ui_cache_enabled,
    _ui_cache_stats,
    _ui_scan_cache_clear,
    _UiScanCache,
)

h5py = pytest.importorskip("h5py")


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, isolated):
    monkeypatch.delenv("RFAUTO_UI_CACHE", raising=False)
    # R8-ENG2：本套件钉的是 A2-D 扫描缓存原语自身的 TTL/签名语义，与
    # registry 接线层无关——恒走 legacy 全扫路径，隔离自愈回填后台线程
    # 改库引发的指纹/代际重建（registry 行为本体钉在
    # test_r8_eng2_ui_registry.py）。
    monkeypatch.setenv("RFAUTO_UI_REGISTRY", "0")
    _ui_scan_cache_clear()
    yield
    _ui_scan_cache_clear()


def _write_dump(path: Path) -> None:
    """最小 DumpHDF5 形状（_is_field_dump 只辨识 Mesh+FieldData 组名）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(path, "w") as f:
        f.create_group("Mesh")
        f.create_group("FieldData")


def _write_gate(run: Path, verdict: str = "PASS", rho: float = 0.9) -> None:
    calib = run / "calibration"
    calib.mkdir(parents=True, exist_ok=True)
    (calib / "gate.json").write_text(json.dumps({
        "verdict": verdict, "rho": rho, "n_samples": 12, "n_failures": 0,
        "mesh_resolution_mm": 0.45, "surrogate_kind": "gp",
        "loocv": {"rho": rho},
    }), encoding="utf-8")


def _write_meta(run: Path, **kw) -> None:
    doc = {"model": "m", "adapter": "a"}
    doc.update(kw)
    run.mkdir(parents=True, exist_ok=True)
    (run / "meta.json").write_text(json.dumps(doc), encoding="utf-8")


def _rewind_all_ages(seconds: float) -> None:
    """把全部缓存条目的落缓存时刻回拨（快照层+per-run 层同时到期）。

    嵌套产物可见性走双层 TTL（快照层→rescan→per-run 层），测"超龄后可见"
    必须两层一起回拨，否则快照重扫仍命中未到期的 per-run 旧值。
    """
    for cache in (ui_service._DIR_LISTING_CACHE, ui_service._JSON_FILE_CACHE,
                  ui_service._H5_PROBE_CACHE, ui_service._RUN_SCAN_CACHE,
                  ui_service._SNAPSHOT_CACHE):
        for key, ent in list(cache._store.items()):
            cache._store[key] = (ent[0] - seconds, ent[1], ent[2])


def _freeze_fingerprint(monkeypatch) -> None:
    """钉死 _runs_fingerprint 当前值（隔离 NTFS 目录 mtime 懒更新的 racy）。

    TTL/命中计数类断言必须与真实 mtime 可见性解耦：真树上延迟落盘的目录
    mtime 可能在两次调用之间"补涨"造成计划外 miss。钉住后命中/超龄语义
    完全由缓存自身逻辑决定（names 类即刻失效测试不钉，走真实路径）。
    """
    frozen = ui_service._runs_fingerprint()
    monkeypatch.setattr(ui_service, "_runs_fingerprint", lambda: frozen)


# ── 缓存原语 ────────────────────────────────────────────────────────────────


class TestUiScanCachePrimitive:
    @staticmethod
    def _producer_stub():
        calls = {"n": 0}

        def producer():
            calls["n"] += 1
            return {"v": calls["n"]}

        return calls, producer

    def test_hit_within_ttl_no_producer_rerun(self):
        calls, producer = self._producer_stub()
        c = _UiScanCache("t")
        assert c.get(("k",), (1, 2), producer) == {"v": 1}
        assert c.get(("k",), (1, 2), producer) == {"v": 1}  # 命中：producer 不再执行
        assert calls["n"] == 1 and c.hits == 1 and c.misses == 1

    def test_signature_change_invalidates_within_ttl(self):
        calls, producer = self._producer_stub()
        c = _UiScanCache("t")
        c.get(("k",), 1, producer)
        c.get(("k",), 2, producer)  # 签名变化：TTL 内也重扫
        assert calls["n"] == 2 and c.misses == 2

    def test_ttl_expiry_forces_rescan(self):
        calls, producer = self._producer_stub()
        c = _UiScanCache("t")
        c.get(("k",), 1, producer)
        ent = c._store[("k",)]
        c._store[("k",)] = (
            ent[0] - (ui_service._UI_SCAN_TTL_S + 1.0), ent[1], ent[2])
        c.get(("k",), 1, producer)  # 签名未变但超龄：重扫
        assert calls["n"] == 2

    def test_none_signature_never_cached(self):
        calls, producer = self._producer_stub()
        c = _UiScanCache("t")
        c.get(("k",), None, producer)
        c.get(("k",), None, producer)
        assert calls["n"] == 2 and not c._store  # 签名不可得：直通且不落缓存

    def test_env_off_bypasses_and_does_not_count(self, monkeypatch):
        calls, producer = self._producer_stub()
        c = _UiScanCache("t")
        monkeypatch.setenv("RFAUTO_UI_CACHE", "0")
        c.get(("k",), 1, producer)
        c.get(("k",), 1, producer)
        assert calls["n"] == 2 and c.hits == 0 and c.misses == 0

    @pytest.mark.parametrize(("raw", "enabled"), [
        ("0", False), ("false", False), ("off", False), ("no", False),
        ("OFF", False), (" False ", False),
        ("1", True), ("yes", True), ("", True),
    ])
    def test_env_values(self, monkeypatch, raw, enabled):
        monkeypatch.setenv("RFAUTO_UI_CACHE", raw)
        assert _ui_cache_enabled() is enabled

    def test_env_unset_means_enabled(self, monkeypatch):
        monkeypatch.delenv("RFAUTO_UI_CACHE", raising=False)
        assert _ui_cache_enabled() is True


# ── 端点级缓存行为 ──────────────────────────────────────────────────────────


class TestEndpointCacheBehavior:
    def test_second_call_no_rescan(self, monkeypatch):
        run = Path("runs") / "20260101_000000_a"
        _write_gate(run)
        _write_meta(run)
        ui_service.calibration_runs()
        _freeze_fingerprint(monkeypatch)  # 隔离 NTFS mtime 懒更新补涨
        st0 = _ui_cache_stats()["snapshot"]
        r2 = ui_service.calibration_runs()
        st1 = _ui_cache_stats()["snapshot"]
        assert st1["misses"] == st0["misses"]  # TTL 内二跑零重扫
        assert st1["hits"] == st0["hits"] + 1
        assert r2["ok"] and len(r2["runs"]) == 1

    def test_new_run_dir_visible_immediately(self, monkeypatch):
        # 顶层结构变化（新 run 目录）→ 指纹条目名集合变化 → 立即可见
        #（枚举反映当前条目，不依赖目录 mtime，NTFS 懒更新不影响此路径）
        monkeypatch.setattr(ui_scan_cache, "_UI_SCAN_TTL_S", 99999.0)  # T1 解环：常量随定义体迁 ui_scan_cache
        assert ui_service.calibration_runs()["runs"] == []
        _write_gate(Path("runs") / "20260101_000000_a")
        rows = ui_service.calibration_runs()["runs"]
        assert [r["run_id"] for r in rows] == ["20260101_000000_a"]

    def test_nested_gate_stale_until_ttl(self, monkeypatch):
        # 文档化语义：嵌套产物（既有 run 内新落 gate.json）依赖该 run 目录
        # mtime 入指纹——实测 NTFS 目录 mtime 懒更新（racy），TTL 内可能
        # 读旧值；快照层+per-run 层都超龄重扫后可见（宁多扫不多旧的硬保证）。
        # 钉指纹=把"mtime 未补涨"钉成确定性前提，专测缓存自身 TTL 语义。
        run = Path("runs") / "20260101_000000_a"
        run.mkdir(parents=True)
        assert ui_service.calibration_runs()["runs"] == []
        _freeze_fingerprint(monkeypatch)
        _write_gate(run)
        assert ui_service.calibration_runs()["runs"] == []  # TTL 内旧值（如实）
        _rewind_all_ages(ui_service._UI_SCAN_TTL_S + 1.0)
        rows = ui_service.calibration_runs()["runs"]
        assert [r["run_id"] for r in rows] == ["20260101_000000_a"]

    def test_in_place_rewrite_stale_until_ttl(self, monkeypatch):
        # 文档化语义：同名文件就地改写不动目录 mtime/条目名 → TTL 内读旧值；
        # 快照超龄重扫后文件级 (mtime,size) 失效使其读新值（TTL 兜底）
        run = Path("runs") / "20260101_000000_a"
        _write_gate(run, verdict="PASS")
        assert ui_service.calibration_runs()["runs"][0]["verdict"] == "PASS"
        _freeze_fingerprint(monkeypatch)
        _write_gate(run, verdict="FAIL")
        assert ui_service.calibration_runs()["runs"][0]["verdict"] == "PASS"
        _rewind_all_ages(ui_service._UI_SCAN_TTL_S + 1.0)
        assert ui_service.calibration_runs()["runs"][0]["verdict"] == "FAIL"

    def test_env_off_passthrough(self, monkeypatch):
        monkeypatch.setenv("RFAUTO_UI_CACHE", "0")
        runs = Path("runs")
        _write_gate(runs / "20260101_000000_a")
        assert len(ui_service.calibration_runs()["runs"]) == 1
        _write_gate(runs / "20260102_000000_b")
        st0 = _ui_cache_stats()
        rows = ui_service.calibration_runs()["runs"]
        assert (_ui_cache_stats() == st0)  # env 关闭：计数与缓存面全不动
        # 直通：两次调用间新增 run 立即可见（无 TTL 内旧读）
        assert [r["run_id"] for r in rows] == [
            "20260102_000000_b", "20260101_000000_a"]

    def test_deepcopy_isolation(self):
        run = Path("runs") / "20260101_000000_a"
        _write_gate(run)
        _write_meta(run)
        r1 = ui_service.calibration_runs()
        r1["runs"].append({"junk": True})
        r2 = ui_service.calibration_runs()
        assert all("junk" not in r for r in r2["runs"])

    def test_pareto_limit_shares_full_snapshot(self, monkeypatch):
        runs = Path("runs")
        for i in range(3):
            (runs / f"2026010{i + 1}_000000_r{i}" / "results").mkdir(
                parents=True)
        m0 = _ui_cache_stats()["snapshot"]["misses"]
        short = ui_service.pareto_runs(limit=1)
        _freeze_fingerprint(monkeypatch)  # 隔离 NTFS mtime 懒更新补涨
        m1 = _ui_cache_stats()["snapshot"]["misses"]
        long_r = ui_service.pareto_runs(limit=10)
        assert len(short["runs"]) == 1 and len(long_r["runs"]) == 3
        assert m1 == m0 + 1  # 不同 limit 共享同一全量快照（切片在缓存后）
        assert _ui_cache_stats()["snapshot"]["misses"] == m1

    def test_field_runs_new_run_instant(self, monkeypatch):
        # 顶层结构变化：新 run 目录带场 dump → 立即可见（不依赖 mtime）
        monkeypatch.setattr(ui_scan_cache, "_UI_SCAN_TTL_S", 99999.0)  # T1 解环：常量随定义体迁 ui_scan_cache
        assert ui_service.field_runs()["runs"] == []
        _write_dump(Path("runs") / "20260101_000000_a" / "SAR_raw.h5")
        out = ui_service.field_runs()
        assert out["runs"][0]["run_id"] == "20260101_000000_a"
        assert out["runs"][0]["dumps"] == ["SAR_raw.h5"]

    def test_field_runs_nested_dump_stale_until_ttl(self, monkeypatch):
        # 嵌套产物（既有 run 的 fdtd/ 下新增 dump）：NTFS 目录 mtime 懒更新
        # → TTL 内旧值如实；双层 TTL 都超龄重扫后可见且体 dump 先。
        # 钉指纹=确定性前提（同 test_nested_gate_stale_until_ttl）。
        run = Path("runs") / "20260101_000000_a"
        _write_dump(run / "fdtd" / "nf2ff_E_0.h5")
        out1 = ui_service.field_runs()
        assert out1["runs"][0]["n_dumps"] == 1
        _freeze_fingerprint(monkeypatch)
        assert ui_service.field_runs() == out1  # 命中：逐字节同值
        _write_dump(run / "fdtd" / "SAR_raw.h5")
        assert ui_service.field_runs()["runs"][0]["n_dumps"] == 1  # TTL 内旧值
        _rewind_all_ages(ui_service._UI_SCAN_TTL_S + 1.0)
        out3 = ui_service.field_runs()
        assert out3["runs"][0]["n_dumps"] == 2
        # 体 dump 先于 nf2ff 盒面 dump（既有排序契约不变）
        assert out3["runs"][0]["dumps"] == ["SAR_raw.h5", "nf2ff_E_0.h5"]

    def test_h5_probe_cache_invalidates_on_rewrite(self):
        p = Path("d.h5")
        _write_dump(p)
        assert ui_service._is_field_dump(p) is True
        with h5py.File(p, "w") as f:
            f.create_group("Mesh")  # 缺 FieldData → 非 dump（内容+size 变化）
        assert ui_service._is_field_dump(p) is False  # (mtime,size) 变化即刻失效

    def test_json_file_cache_invalidates_on_rewrite(self):
        p = Path("g.json")
        p.write_text('{"v": 1}', encoding="utf-8")
        assert ui_service._cached_json(p) == {"v": 1}
        p.write_text('{"v": 2, "x": 1}', encoding="utf-8")
        assert ui_service._cached_json(p) == {"v": 2, "x": 1}
        assert ui_service._cached_json(p.parent / "nope.json") is None

    def test_stats_shape(self):
        st = _ui_cache_stats()
        # R8-ENG2：registry 索引缓存（reg_index）入观测单源清单
        assert set(st) == {"dir_listing", "json_file", "h5_probe",
                           "run_scan", "snapshot", "reg_index"}
        for v in st.values():
            assert set(v) == {"enabled", "hits", "misses", "entries"}


# ── schema 逐字节不变：旧实现参考副本 vs 新实现 ─────────────────────────────
#
# 参考副本=改造前端点原体（root 参数化），逐字保持扫描/组装/键序。


def _ref_calibration_runs(root: Path) -> dict:
    entries = []
    for run in sorted(root.iterdir(), reverse=True):
        gate_p = run / "calibration" / "gate.json"
        if not run.is_dir() or not gate_p.exists():
            continue
        try:
            gate = json.loads(gate_p.read_text(encoding="utf-8"))
        except Exception:
            continue
        model = adapter = None
        meta_p = run / "meta.json"
        if meta_p.exists():
            try:
                m = json.loads(meta_p.read_text(encoding="utf-8"))
                model, adapter = m.get("model"), m.get("adapter")
            except Exception:
                pass
        loocv = gate.get("loocv") or {}
        entries.append({
            "run_id": run.name, "model": model, "adapter": adapter,
            "verdict": gate.get("verdict"), "rho": loocv.get("rho"),
            "n_samples": gate.get("n_samples"),
            "n_failures": gate.get("n_failures"),
            "mesh_resolution_mm": gate.get("mesh_resolution_mm"),
            "surrogate_kind": gate.get("surrogate_kind"),
        })
    return {"ok": True, "runs": entries}


def _ref_cross_fidelity_view(root: Path) -> dict:
    import glob

    surrogate_evolution = []
    cross_evolution = []
    for run in sorted(root.iterdir()):
        if not run.is_dir():
            continue
        gate_p = run / "calibration" / "gate.json"
        if gate_p.exists():
            try:
                gate = json.loads(gate_p.read_text(encoding="utf-8"))
                loocv = gate.get("loocv") or {}
                surrogate_evolution.append({
                    "run_id": run.name, "rho": loocv.get("rho"),
                    "n_samples": gate.get("n_samples"),
                    "mesh_resolution_mm": gate.get("mesh_resolution_mm"),
                    "verdict": gate.get("verdict"),
                    "surrogate_kind": gate.get("surrogate_kind"),
                })
            except Exception:
                pass
        meta_p = run / "meta.json"
        if meta_p.exists():
            try:
                m = json.loads(meta_p.read_text(encoding="utf-8"))
            except Exception:
                m = {}
            if m.get("algorithm") == "cross_fidelity_gate_from_asset":
                metrics = m.get("metrics") or {}
                cross_evolution.append({
                    "run_id": run.name,
                    "algorithm": m.get("algorithm"),
                    "rho": metrics.get("rho"),
                    "top5_recall": metrics.get("top5_recall"),
                    "n_evaluated": metrics.get("n_evaluated"),
                    "verdict": metrics.get("verdict"),
                })
    for p in sorted(glob.glob(str(root / "p0_*result.json"))):
        try:
            d = json.loads(Path(p).read_text(encoding="utf-8"))
        except Exception:
            continue
        cross_evolution.append({
            "run_id": Path(p).stem, "algorithm": "p0_native",
            "rho": d.get("spearman_rho"),
            "top5_recall": d.get("top5_recall"),
            "n_evaluated": d.get("n_evaluated"),
            "verdict": ("PASS" if (d.get("spearman_rho") or -1)
                        >= p0_gate_service.THRESHOLD_RHO else "FAIL"),
        })
    return {"ok": True, "surrogate_evolution": surrogate_evolution,
            "cross_evolution": cross_evolution}


def _ref_list_reports(root: Path) -> dict:
    entries: list[dict] = []
    if not root.exists():
        return {"ok": True, "reports": []}
    for run in sorted(root.iterdir(), reverse=True):
        if not run.is_dir():
            continue
        model = None
        meta_p = run / "meta.json"
        if meta_p.exists():
            with contextlib.suppress(Exception):
                model = (json.loads(meta_p.read_text(encoding="utf-8"))
                         or {}).get("model")
        for kind, rel in ui_service._REPORT_FILES:
            p = run / rel
            if not p.is_file():
                continue
            try:
                size = p.stat().st_size
                mtime = p.stat().st_mtime
            except OSError:
                continue
            entries.append({
                "run_id": run.name, "kind": kind, "model": model,
                "path": str(p).replace("\\", "/"),
                "size_bytes": size, "mtime": mtime,
            })
    return {"ok": True, "reports": entries}


def _ref_pareto_runs(root: Path, limit: int = 200) -> dict:
    entries: list[dict] = []
    if root.exists():
        run_dirs = sorted((p for p in root.iterdir() if p.is_dir()),
                          reverse=True)
        if len(run_dirs) > ui_service._PARETO_RUNS_SCAN_CAP:
            run_dirs = run_dirs[:ui_service._PARETO_RUNS_SCAN_CAP]
        for run in run_dirs:
            has_front = (run / "results" / "pareto_front.json").is_file()
            trials_dir = run / "trials"
            n_trials = (sum(1 for _ in trials_dir.glob("*.json"))
                        if trials_dir.is_dir() else 0)
            tier = "front" if has_front else ("trials" if n_trials else "single")
            model = adapter = None
            meta_p = run / "meta.json"
            if meta_p.exists():
                with contextlib.suppress(Exception):
                    meta = json.loads(
                        meta_p.read_text(encoding="utf-8")) or {}
                    model, adapter = meta.get("model"), meta.get("adapter")
            entries.append({
                "run_id": run.name, "model": model, "adapter": adapter,
                "tier": tier, "has_pareto": has_front, "n_trials": n_trials,
            })
    tier_rank = {"front": 0, "trials": 1, "single": 2}
    entries.sort(key=lambda e: e["run_id"], reverse=True)
    entries.sort(key=lambda e: tier_rank.get(e["tier"], 3))
    return {"ok": True, "runs": entries[:max(0, int(limit))]}


def _ref_field_runs(root: Path, limit: int = 50) -> dict:
    hits: list[dict] = []
    if root.is_dir():
        for run_dir in sorted(p for p in root.iterdir() if p.is_dir()):
            dumps = _ref_field_candidates(run_dir)
            if not dumps:
                continue
            hits.append({
                "run_id": run_dir.name,
                "dumps": [d.name for d in dumps],
                "n_dumps": len(dumps),
                "has_farfield_h5": ui_service._farfield_h5(run_dir) is not None,
                "mtime": max(d.stat().st_mtime for d in dumps),
            })
    hits.sort(key=lambda h: -h["mtime"])
    return {"ok": True, "runs": hits[: max(1, int(limit))],
            "viz3d_available": ui_service._viz3d_available()}


def _ref_field_candidates(run_dir: Path) -> list[Path]:
    """旧版 _field_dump_candidates 原体（无缓存直读）。"""
    found: list[Path] = []
    for sub in ui_service.FIELD_DUMP_SUBDIRS:
        base = run_dir / sub if sub else run_dir
        if not base.is_dir():
            continue
        found.extend(p for p in sorted(base.glob("*.h5"))
                     if _ref_is_field_dump(p))
    return sorted(found, key=lambda p: (p.name.startswith("nf2ff_"), p.name))


def _ref_is_field_dump(path: Path) -> bool:
    try:
        with h5py.File(path, "r") as h:
            return "Mesh" in h and "FieldData" in h
    except Exception:
        return False


def _dumps(doc) -> str:
    return json.dumps(doc, ensure_ascii=False, separators=(",", ":"))


def _build_fixture_tree(tmp_path: Path) -> Path:
    runs = tmp_path / "runs"
    a = runs / "20260101_000000_a"
    (a / "results").mkdir(parents=True)
    _write_gate(a, verdict="PASS", rho=0.9)
    _write_meta(a, model="wilkinson", adapter="openems")
    (a / "report.md").write_text("# A", encoding="utf-8")
    (a / "results" / "pareto_front.json").write_text("{}", encoding="utf-8")
    _write_dump(a / "SAR_raw.h5")
    b = runs / "20260102_000000_b"
    (b / "trials").mkdir(parents=True)
    for i in range(2):
        (b / "trials" / f"trial_{i}.json").write_text("{}", encoding="utf-8")
    _write_meta(b, model="patch", adapter="fake",
                algorithm="cross_fidelity_gate_from_asset",
                metrics={"rho": 0.7, "top5_recall": 0.8, "verdict": "PASS"})
    (b / "sim_ci_report.md").write_text("# B", encoding="utf-8")
    with h5py.File(b / "not_a_dump.h5", "w") as f:
        f.create_group("other")  # 非 dump：被 field_runs 排除
    c = runs / "20260103_000000_c"
    (c / "calibration").mkdir(parents=True)
    (c / "calibration" / "report.md").write_text("# C", encoding="utf-8")
    _write_dump(c / "fdtd" / "nf2ff_E_0.h5")
    (runs / "p0_native_result.json").write_text(json.dumps({
        "spearman_rho": 0.6, "top5_recall": 0.9, "n_evaluated": 10,
    }), encoding="utf-8")
    (runs / "loose_file.txt").write_text("x", encoding="utf-8")  # 非目录条目
    return runs


class TestSchemaByteIdentity:
    """新旧实现同输入树同输出（json 序列化逐字节相等，含键序与 mtime 浮点）。"""

    ENDPOINTS = (
        ("calibration_runs", lambda: ui_service.calibration_runs()),
        ("cross_fidelity_view", lambda: ui_service.cross_fidelity_view()),
        ("list_reports", lambda: ui_service.list_reports()),
        ("pareto_runs", lambda: ui_service.pareto_runs(limit=200)),
        ("field_runs", lambda: ui_service.field_runs(limit=50)),
    )

    def _refs(self, runs: Path) -> dict:
        return {
            "calibration_runs": _ref_calibration_runs(runs),
            "cross_fidelity_view": _ref_cross_fidelity_view(runs),
            "list_reports": _ref_list_reports(runs),
            "pareto_runs": _ref_pareto_runs(runs, 200),
            "field_runs": _ref_field_runs(runs, 50),
        }

    def _assert_same(self, refs: dict, tag: str) -> None:
        for name, fn in self.ENDPOINTS:
            got = fn()
            assert _dumps(got) == _dumps(refs[name]), f"{tag}:{name}"

    def test_all_endpoints_miss_hit_and_env_off_paths(self,
                                                      tmp_path, monkeypatch):
        _build_fixture_tree(tmp_path)
        # 参考副本与被测实现同走 cwd 相对的 runs/（旧实现嵌相对路径
        # "runs/..."，参考传绝对 root 会让 list_reports 的 path 键不等）
        refs = self._refs(Path("runs"))
        self._assert_same(refs, "miss")  # 首跑（缓存 miss，走全扫描组装）
        self._assert_same(refs, "hit")  # 二跑（TTL 内缓存命中）
        monkeypatch.setenv("RFAUTO_UI_CACHE", "0")
        _ui_scan_cache_clear()
        self._assert_same(refs, "env-off")  # 直通路径

    def test_threshold_monkeypatch_survives_cache(self, tmp_path, monkeypatch):
        # R3-3 单源钉的缓存版补强：verdict 组装每请求现算——先以阈值 0.5
        # 建并缓存 p0 文档快照，改阈值后同树重读 verdict 必须翻转
        _build_fixture_tree(tmp_path)
        monkeypatch.setattr(p0_gate_service, "THRESHOLD_RHO", 0.5)
        r1 = ui_service.cross_fidelity_view()
        e1 = next(e for e in r1["cross_evolution"]
                  if e["run_id"] == "p0_native_result")
        assert e1["verdict"] == "PASS"  # 0.6 ≥ 0.5
        monkeypatch.setattr(p0_gate_service, "THRESHOLD_RHO", 0.9)
        r2 = ui_service.cross_fidelity_view()
        e2 = next(e for e in r2["cross_evolution"]
                  if e["run_id"] == "p0_native_result")
        assert e2["verdict"] == "FAIL"  # 0.6 < 0.9（未吃缓存旧值）
