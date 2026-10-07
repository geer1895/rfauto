"""W3-C RB-ML-1 代理模型注册表——内核+服务面单测（离线，合成 fixture）。

判据覆盖（sa_specs2 §6.3 预声明门值）：
- ③stale 联动（双钉之一在本件：合成 ESD 越界序列→族全版本 stale=
  true+stale_reason=锚指针；champion 读取面拒用；另一钉=e2e 件
  test_w3_c_registry_e2e 的注入通道拒用）；
- ④幂等与并发：重复 upsert 同键同版本不膨胀；并发同键版本号 max+1
  不冲突（双 ModelRegistry 实例跨线程走文件锁）；
- ⑤blob 完整性：sha256 复核不过拒用+reason，不崩溃；
- ⑥旧环境兼容：registry 文件不存在→一切行为=现状；
- ①血缘可查：版本→trained_run_ids→湖行→meta.git_sha 三跳反查
  （合成 run+真实 build_runs_index）；
- 键指纹/三态开关（#277）/配对裁判内核（#273 channel 口径）。

champion→warm-start 注入与配对收益战役（判据②）在 e2e 件。
"""

from __future__ import annotations

import json
import pickle
import sys
import threading
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from rfauto.core.anchor_drift_spc import anchor_drift_spc_report
from rfauto.optimization.model_registry import (
    ModelRegistry,
    canonical_key,
    feature_set_fingerprint,
)
from rfauto.service.lake_service import build_runs_index
from rfauto.service.surrogate_registry_service import (
    judge_registry_warm_start_benefit,
    mark_stale_from_anchor_drift,
    resolve_warm_start_registry_flag,
    surrogate_registry_champion_points,
    surrogate_registry_mark_stale,
    surrogate_registry_query,
    surrogate_registry_set_status,
    surrogate_registry_upsert,
)


class _TinyModel:
    """可 pickle 的最小代理桩（predict 恒等面，供 champion_points 链）。"""

    KIND = "tiny"

    def __init__(self, offset: float = 0.0) -> None:
        self.offset = float(offset)

    def predict(self, params: dict) -> dict:
        return {"s11_db": -20.0 + 10.0 * float(sum(params.values())) + self.offset}


def _key(family: str = "fam", channel: str = "fake",
         names: list[str] | None = None) -> dict:
    return canonical_key(family, channel,
                         feature_set_fingerprint(names or ["p1", "p2"]))


def _reg(tmp_path: Path, name: str = "registry.yaml") -> ModelRegistry:
    return ModelRegistry(registry_path=tmp_path / "knowledge" / name,
                         store_dir=tmp_path / "runs" / ".model_store")


def _heldout(value: float = 0.05, n: int = 4) -> dict:
    return {"metric": "linf", "value": value, "n_points": n}


def _blob(tmp_path: Path, obj: object, name: str = "m.pkl") -> bytes:
    data = pickle.dumps(obj)
    (tmp_path / name).write_bytes(data)
    return data


# ─── 键指纹（spec §6.2-1）────────────────────────────────────────────────────


class TestFeatureSetFingerprint:
    def test_len16_and_stable(self):
        a = feature_set_fingerprint(["p1", "p2"])
        b = feature_set_fingerprint(["p1", "p2"])
        assert len(a) == 16
        assert a == b

    def test_order_sensitive(self):
        assert feature_set_fingerprint(["p1", "p2"]) \
            != feature_set_fingerprint(["p2", "p1"])

    def test_preprocessing_sensitive(self):
        assert feature_set_fingerprint(["p1"], None) \
            != feature_set_fingerprint(["p1"], {"norm": "minmax"})

    def test_names_sensitive(self):
        assert feature_set_fingerprint(["p1"]) \
            != feature_set_fingerprint(["p2"])

    def test_key_rejects_empty_fields(self):
        with pytest.raises(ValueError):
            canonical_key("", "fake", "ab" * 8)


# ─── 判据④：幂等 + 并发 ──────────────────────────────────────────────────────


class TestUpsertIdempotencyAndVersions:
    def test_duplicate_content_no_bloat(self, tmp_path):
        reg = _reg(tmp_path)
        k = _key()
        r1 = reg.upsert(key=k, model_bytes=b"v1",
                        heldout=_heldout(0.1), hyperparams={"a": 1})
        r2 = reg.upsert(key=k, model_bytes=b"v1",
                        heldout=_heldout(0.1), hyperparams={"a": 1})
        assert r1["ok"] and r2["ok"] and r2["deduped"] is True
        assert r2["version"] == r1["version"]
        assert len(reg.load()["entries"][0]["versions"]) == 1

    def test_new_content_max_plus_one(self, tmp_path):
        reg = _reg(tmp_path)
        k = _key()
        v1 = reg.upsert(key=k, model_bytes=b"a", heldout=_heldout(0.1))
        v2 = reg.upsert(key=k, model_bytes=b"b", heldout=_heldout(0.2))
        assert (v1["version"], v2["version"]) == (1, 2)
        rows = reg.query(template_family="fam")
        assert [r["version"] for r in rows] == [1, 2]

    def test_explicit_version_replace_in_place(self, tmp_path):
        reg = _reg(tmp_path)
        k = _key()
        reg.upsert(key=k, model_bytes=b"a", heldout=_heldout(0.1))
        r = reg.upsert(key=k, model_bytes=b"b", heldout=_heldout(0.2),
                       version=1)
        assert r["version"] == 1 and r["deduped"] is False
        assert len(reg.load()["entries"][0]["versions"]) == 1

    def test_heldout_mandatory(self, tmp_path):
        reg = _reg(tmp_path)
        with pytest.raises(ValueError, match="heldout"):
            reg.upsert(key=_key(), model_bytes=b"a", heldout=None)
        with pytest.raises(ValueError):
            reg.upsert(key=_key(), model_bytes=b"a",
                       heldout={"metric": "linf", "value": 0.1})  # 缺 n_points


class TestConcurrentUpsertVersions:
    def test_two_instances_threads_no_version_conflict(self, tmp_path):
        """判据④并发钉：双实例（各自 RLock）×2 线程同键并发 upsert——
        版本号 max+1 在文件锁下不冲突，恰好 1..4 无重复。"""
        registry_path = tmp_path / "knowledge" / "registry.yaml"
        store_dir = tmp_path / "runs" / ".model_store"
        k = _key()
        errors: list[str] = []
        versions: list[int] = []

        def _worker(tag: str) -> None:
            reg = ModelRegistry(registry_path=registry_path,
                                store_dir=store_dir)
            try:
                res = reg.upsert(key=k, model_bytes=f"payload-{tag}".encode(),
                                 heldout=_heldout(0.1 + 0.01 * len(versions)))
                versions.append(int(res["version"]))
            except Exception as exc:  # pragma: no cover - 失败要显眼
                errors.append(f"{tag}: {exc}")

        threads = [threading.Thread(target=_worker, args=(t,))
                   for t in ("a", "b", "c", "d")]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors, errors
        assert sorted(versions) == [1, 2, 3, 4]
        doc = ModelRegistry(registry_path=registry_path,
                            store_dir=store_dir).load()
        assert len(doc["entries"]) == 1
        assert len(doc["entries"][0]["versions"]) == 4


# ─── champion 生命周期 + 判据③ stale 读取面守卫 ─────────────────────────────


class TestChampionLifecycleAndStaleGuard:
    def test_first_champion_then_challenger(self, tmp_path):
        reg = _reg(tmp_path)
        k = _key()
        r1 = reg.upsert(key=k, model_bytes=b"a", heldout=_heldout(0.1))
        r2 = reg.upsert(key=k, model_bytes=b"b", heldout=_heldout(0.2))
        assert r1["entry"]["status"] == "champion"
        assert r2["entry"]["status"] == "challenger"
        ch = reg.champion(k)
        assert ch["ok"] and ch["entry"]["version"] == 1

    def test_stale_champion_refused_with_reason(self, tmp_path):
        """判据③钉一：合成 ESD 越界序列→族全版本 stale=true+锚指针。"""
        reg = _reg(tmp_path)
        k1 = _key(family="fam", channel="fake")
        k2 = _key(family="fam", channel="hfss")
        reg.upsert(key=k1, model_bytes=b"a", heldout=_heldout(0.1))
        reg.upsert(key=k2, model_bytes=b"b", heldout=_heldout(0.1))
        drift = anchor_drift_spc_report(
            [0.1, 0.2, -0.1, 0.05, -0.2, 0.15, 0.1, -0.05,
             8.0, 8.1, 7.9, 8.05, 8.2], sigma=1.0, target=0.0)
        assert drift["verdict"] == "drifted"
        res = mark_stale_from_anchor_drift("fam", drift, anchor_id="f0_2.4G",
                                           registry_path=reg.registry_path,
                                           store_dir=reg.store_dir)
        assert res["ok"] and res["action"] == "marked_stale"
        assert res["n_marked"] == 2
        for row in reg.query(template_family="fam"):
            assert row["stale"] is True
            assert "anchor_drift:drifted:f0_2.4G" in row["stale_reason"]
        ch = reg.champion(k1)
        assert ch["ok"] is False and ch["reason"] == "stale"
        assert "anchor_drift" in ch["stale_reason"]

    def test_non_drifted_verdict_noop(self, tmp_path):
        reg = _reg(tmp_path)
        reg.upsert(key=_key(), model_bytes=b"a", heldout=_heldout(0.1))
        res = mark_stale_from_anchor_drift(
            "fam", {"verdict": "stable"},
            registry_path=reg.registry_path, store_dir=reg.store_dir)
        assert res["action"] == "noop" and res["n_marked"] == 0
        # 单证据线（上限 warning）不标 stale（保守不升级，SPC 既有语义）
        warning = {"verdict": "warning", "fired_lines": ["esd"]}
        res = mark_stale_from_anchor_drift(
            "fam", warning, registry_path=reg.registry_path,
            store_dir=reg.store_dir)
        assert res["action"] == "noop"
        assert all(r["stale"] is False for r in reg.query())

    def test_promote_clears_stale_revalidation_semantics(self, tmp_path):
        """复验通过后显式 promote 回 champion（清 stale）——spec §6.2-2②。"""
        reg = _reg(tmp_path)
        k = _key()
        reg.upsert(key=k, model_bytes=b"a", heldout=_heldout(0.1))
        reg.mark_family_stale("fam", "anchor_drift:drifted:x:esd")
        assert reg.champion(k)["reason"] == "stale"
        setres = surrogate_registry_set_status({
            "template_family": "fam", "channel": "fake",
            "feature_names": ["p1", "p2"],
            "version": 1, "status": "champion", "clear_stale": True,
            "registry_path": reg.registry_path,
            "store_dir": reg.store_dir})
        assert setres["ok"], setres
        ch = reg.champion(k)
        assert ch["ok"] and ch["entry"]["stale"] is False
        # 重训新版本不静默顶替 stale champion（须显式 promote）
        r2 = reg.upsert(key=k, model_bytes=b"b", heldout=_heldout(0.2))
        assert r2["entry"]["status"] == "challenger"

    def test_retire(self, tmp_path):
        reg = _reg(tmp_path)
        k = _key()
        reg.upsert(key=k, model_bytes=b"a", heldout=_heldout(0.1))
        reg.set_version_status(k, 1, "retired")
        assert reg.champion(k)["reason"] == "no_champion"


# ─── 判据⑤：blob 完整性 ─────────────────────────────────────────────────────


class TestBlobIntegrity:
    def _entry(self, tmp_path):
        reg = _reg(tmp_path)
        r = reg.upsert(key=_key(), model=_TinyModel(1.5), heldout=_heldout())
        return reg, r["entry"]

    def test_tamper_refused_not_crash(self, tmp_path):
        reg, entry = self._entry(tmp_path)
        blob = Path(entry["blob_path"])
        blob.write_bytes(blob.read_bytes() + b"tampered")
        res = reg.load_entry_model(entry)
        assert res["ok"] is False
        assert res["reason"] == "blob_sha256_mismatch"
        assert "期望" in res["detail"]

    def test_missing_blob_refused(self, tmp_path):
        reg, entry = self._entry(tmp_path)
        Path(entry["blob_path"]).unlink()
        res = reg.load_entry_model(entry)
        assert res["ok"] is False and res["reason"] == "blob_missing"

    def test_store_dir_fallback_recovers_display_path_drift(self, tmp_path):
        """blob_path 展示路径失配（如 cwd 漂移）→ store_dir 内容寻址兜底。"""
        reg, entry = self._entry(tmp_path)
        broken = dict(entry, blob_path="nowhere/lost.pkl")
        res = reg.load_entry_model(broken)
        assert res["ok"] is True

    def test_unpickle_garbage_refused(self, tmp_path):
        """sha 一致但内容非 pickle（sha 复核过了才到反序列化层）→ 拒用。"""
        from rfauto.optimization.model_registry import sha256_bytes

        reg, entry = self._entry(tmp_path)
        garbage = b"not a pickle at all"
        Path(entry["blob_path"]).write_bytes(garbage)
        entry["model_blob_sha256"] = sha256_bytes(garbage)
        res = reg.load_entry_model(entry)
        assert res["ok"] is False and res["reason"] == "unpickle_failed"


# ─── 判据⑥：旧环境兼容（registry 文件不存在→行为=现状）───────────────────────


class TestEmptyRegistryZeroDegradation:
    def test_missing_file_behaviors(self, tmp_path):
        reg = _reg(tmp_path)
        assert reg.load() == {"schema_version": 1, "entries": []}
        assert reg.query() == []
        ch = reg.champion(_key())
        assert ch["ok"] is False and ch["reason"] == "no_champion"
        # 首次 upsert 照常工作
        r = reg.upsert(key=_key(), model_bytes=b"a", heldout=_heldout())
        assert r["ok"] and r["version"] == 1
        # blob 落 runs/.model_store（gitignored 面）
        assert ".model_store" in r["entry"]["blob_path"]

    def test_corrupt_file_honest_error(self, tmp_path):
        reg = _reg(tmp_path)
        reg.registry_path.parent.mkdir(parents=True, exist_ok=True)
        reg.registry_path.write_text("entries: [ {broken", encoding="utf-8")
        with pytest.raises(ValueError):
            reg.query()
        svc = surrogate_registry_query({
            "registry_path": reg.registry_path,
            "store_dir": reg.store_dir})
        assert svc["ok"] is False

    def test_query_on_missing_via_service(self, tmp_path):
        svc = surrogate_registry_query({
            "registry_path": tmp_path / "nope.yaml",
            "store_dir": tmp_path / "store"})
        assert svc["ok"] is True and svc["n_rows"] == 0


# ─── 判据①：血缘三跳反查（合成 run + 真实湖索引）─────────────────────────────


class TestLineageThreeHops:
    def test_version_to_run_ids_to_meta_git_sha(self, tmp_path, monkeypatch):
        runs_dir = tmp_path / "runs"
        run_a = runs_dir / "runA"
        run_a.mkdir(parents=True)
        (run_a / "meta.json").write_text(json.dumps({
            "model": "fam", "adapter": "fake", "study_name": "s1",
            "status": "ok", "git_sha": "abc1234commit"}), encoding="utf-8")
        idx = build_runs_index(runs_dir=runs_dir,
                               db_path=tmp_path / "idx.duckdb")
        assert idx["ok"] and idx["n_rows"] == 1

        reg = _reg(tmp_path)
        model_file = tmp_path / "model.pkl"
        model_file.write_bytes(pickle.dumps({"m": 1}))
        payload = {
            "template_family": "fam", "channel": "fake",
            "feature_names": ["p1", "p2"],
            "model_path": str(model_file),
            "heldout": _heldout(0.03, 5),
            "hyperparams": {"kind": "poly_ridge"},
            "trained_run_ids": ["runA"],
            "render_commit": "def5678render",
            "registry_path": reg.registry_path,
            "store_dir": reg.store_dir,
        }
        up = surrogate_registry_upsert(payload)
        assert up["ok"], up
        q = surrogate_registry_query({
            "template_family": "fam", "lake_join": True,
            "db_path": tmp_path / "idx.duckdb", "runs_dir": str(runs_dir),
            "registry_path": reg.registry_path,
            "store_dir": reg.store_dir})
        assert q["ok"] and q["n_rows"] == 1
        row = q["rows"][0]
        # 三跳：版本行 → trained_run_ids → 湖行 → meta.git_sha
        assert row["trained_run_ids"] == ["runA"]
        assert row["render_commit"] == "def5678render"
        assert row["lake_runs"], row
        assert row["lake_runs"][0]["run_id"] == "runA"
        assert row["lake_runs"][0]["git_sha"] == "abc1234commit"
        assert row["heldout"] == {"metric": "linf", "value": 0.03,
                                  "n_points": 5}

    def test_lake_join_missing_db_skipped_honestly(self, tmp_path):
        reg = _reg(tmp_path)
        reg.upsert(key=_key(), model_bytes=b"a", heldout=_heldout(),
                   trained_run_ids=["runX"])
        q = surrogate_registry_query({
            "lake_join": True, "db_path": tmp_path / "absent.duckdb",
            "registry_path": reg.registry_path,
            "store_dir": reg.store_dir})
        assert q["ok"] is True
        assert q["lake_join"]["joined"] is False
        assert "不存在" in q["lake_join"]["note"]

    def test_verify_blob_flag(self, tmp_path):
        reg, entry = TestBlobIntegrity._entry(self, tmp_path)
        blob = Path(entry["blob_path"])
        blob.write_bytes(blob.read_bytes() + b"x")
        q = surrogate_registry_query({
            "verify_blob": True, "registry_path": reg.registry_path,
            "store_dir": reg.store_dir})
        assert q["ok"] and q["rows"][0]["blob_ok"] is False
        assert q["rows"][0]["blob_reason"] == "blob_sha256_mismatch"


# ─── 消费面①：champion_points（键指纹精确匹配 + stale 拒用=判据③钉二）────────


class TestChampionPoints:
    def _recipe(self, tmp_path: Path) -> Path:
        recipe = {
            "model": "w3c_tiny_family",
            "objectives": [
                {"metric": "s11_db", "band": [2.3, 2.5],
                 "op": "max_below", "value": -15}],
            "optimization": {"params": {
                "p1": {"low": 0.0, "high": 1.0},
                "p2": {"low": 0.0, "high": 1.0}}},
        }
        p = tmp_path / "tiny_recipe.yaml"
        p.write_text(yaml.safe_dump(recipe, allow_unicode=True),
                     encoding="utf-8")
        return p

    def _champion_registry(self, tmp_path: Path, family: str = "w3c_tiny_family"):
        reg = _reg(tmp_path)
        reg.upsert(key=_key(family=family), model=_TinyModel(0.0),
                   heldout=_heldout())
        return reg

    def test_points_deterministic_and_shape(self, tmp_path):
        rp = self._recipe(tmp_path)
        reg = self._champion_registry(tmp_path)
        kw = {"registry_path": reg.registry_path, "store_dir": reg.store_dir}
        a = surrogate_registry_champion_points(str(rp), "fake", **kw)
        b = surrogate_registry_champion_points(str(rp), "fake", **kw)
        assert a["ok"] and b["ok"]
        assert len(a["points"]) == 3
        assert a["points"] == b["points"]  # 同输入同输出（C4 可复现红线）
        for pt in a["points"]:
            assert set(pt["params"]) == {"p1", "p2"}
            for v in pt["params"].values():
                assert 0.0 <= v <= 1.0
        assert a["champion"]["heldout"]["metric"] == "linf"

    def test_no_champion_refused(self, tmp_path):
        rp = self._recipe(tmp_path)
        res = surrogate_registry_champion_points(
            str(rp), "fake", registry_path=tmp_path / "no.yaml",
            store_dir=tmp_path / "s")
        assert res["ok"] is False and res["reason"] == "no_champion"

    def test_fingerprint_mismatch_no_false_reuse(self, tmp_path):
        """特征集演进=新键：注册表键是 p3 特征集，配方是 p1/p2 → 失配不模糊
        复用（spec §6.4 键漂移分流）。"""
        rp = self._recipe(tmp_path)
        reg = _reg(tmp_path)
        reg.upsert(key=_key(family="w3c_tiny_family",
                            names=["p1", "p2", "p3"]),
                   model=_TinyModel(), heldout=_heldout())
        res = surrogate_registry_champion_points(
            str(rp), "fake", registry_path=reg.registry_path,
            store_dir=reg.store_dir)
        assert res["ok"] is False and res["reason"] == "no_champion"

    def test_stale_refused_double_pin_two(self, tmp_path):
        """判据③钉二：stale 后 champion_points 拒用（注入源拒绝=无点可入队）。"""
        rp = self._recipe(tmp_path)
        reg = self._champion_registry(tmp_path)
        reg.mark_family_stale("w3c_tiny_family", "anchor_drift:drifted:x:esd")
        res = surrogate_registry_champion_points(
            str(rp), "fake", registry_path=reg.registry_path,
            store_dir=reg.store_dir)
        assert res["ok"] is False and res["reason"] == "stale"
        assert res["stale_reason"]

    def test_direct_mark_stale_service(self, tmp_path):
        reg = self._champion_registry(tmp_path)
        res = surrogate_registry_mark_stale({
            "template_family": "w3c_tiny_family",
            "stale_reason": "manual:x",
            "registry_path": reg.registry_path,
            "store_dir": reg.store_dir})
        assert res["ok"] and res["n_marked"] == 1
        assert res["revalidation"]["required"] is True


# ─── service upsert 校验 + 三态开关（#277）───────────────────────────────────


class TestUpsertPayloadValidation:
    def test_missing_heldout_refused(self, tmp_path):
        res = surrogate_registry_upsert({
            "template_family": "f", "channel": "fake",
            "feature_names": ["p1"], "model_path": "nowhere.pkl",
            "registry_path": tmp_path / "r.yaml",
            "store_dir": tmp_path / "s"})
        assert res["ok"] is False

    def test_missing_model_path_refused(self, tmp_path):
        res = surrogate_registry_upsert({
            "template_family": "f", "channel": "fake",
            "feature_names": ["p1"], "heldout": _heldout(),
            "model_path": str(tmp_path / "absent.pkl"),
            "registry_path": tmp_path / "r.yaml",
            "store_dir": tmp_path / "s"})
        assert res["ok"] is False and "model_path" in res["errors"][0]

    def test_missing_fingerprint_source_refused(self, tmp_path):
        res = surrogate_registry_upsert({
            "template_family": "f", "channel": "fake",
            "heldout": _heldout(),
            "model_path": str(_blob(tmp_path, 1, "x.pkl")),
            "registry_path": tmp_path / "r.yaml",
            "store_dir": tmp_path / "s"})
        assert res["ok"] is False


class TestTriStateResolver:
    def test_explicit_wins_over_env(self, monkeypatch):
        monkeypatch.setenv("RFAUTO_WARM_START_REGISTRY", "0")
        assert resolve_warm_start_registry_flag(True) is True
        monkeypatch.setenv("RFAUTO_WARM_START_REGISTRY", "1")
        assert resolve_warm_start_registry_flag(False) is False

    def test_env_tier(self, monkeypatch):
        monkeypatch.delenv("RFAUTO_WARM_START_REGISTRY", raising=False)
        monkeypatch.setattr(Path, "cwd", Path.cwd, raising=False)
        assert resolve_warm_start_registry_flag(None) is False
        monkeypatch.setenv("RFAUTO_WARM_START_REGISTRY", "true")
        assert resolve_warm_start_registry_flag(None) is True
        monkeypatch.setenv("RFAUTO_WARM_START_REGISTRY", "banana")
        assert resolve_warm_start_registry_flag(None) is False

    def test_config_tier(self, tmp_path, monkeypatch):
        monkeypatch.delenv("RFAUTO_WARM_START_REGISTRY", raising=False)
        cfg = tmp_path / "configs"
        cfg.mkdir()
        (cfg / "settings.yaml").write_text(
            yaml.safe_dump({"tune": {"warm_start_registry": True}}),
            encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        assert resolve_warm_start_registry_flag(None) is True
        (cfg / "settings.yaml").write_text(
            yaml.safe_dump({"tune": {"warm_start_registry": False}}),
            encoding="utf-8")
        assert resolve_warm_start_registry_flag(None) is False


# ─── 配对裁判内核（判据②的判读语义，#273 channel 口径）───────────────────────


class TestJudgeBenefit:
    def test_pass_by_first_cost_improvement(self):
        pairs = {
            "s1": {"injected_first": 0.2, "baseline_first": 1.0},
            "s2": {"injected_first": 0.3, "baseline_first": 1.2},
            "s3": {"injected_first": 0.25, "baseline_first": 1.1},
        }
        v = judge_registry_warm_start_benefit(pairs, channel="fake")
        assert v["verdict"] == "PASS" and v["pass"] is True
        assert v["median_improvement_pct"] >= 30.0
        assert v["channel"] == "fake" and v["n_pairs"] == 3
        assert v["n_censored"] == 0

    def test_pass_by_trials_to_target_reduction(self):
        pairs = {
            "s1": {"injected_first": 1.0, "baseline_first": 1.0,
                   "injected_ttt": 2, "baseline_ttt": 8},
            "s2": {"injected_first": 1.0, "baseline_first": 1.0,
                   "injected_ttt": 3, "baseline_ttt": 9},
            "s3": {"injected_first": 1.0, "baseline_first": 1.0,
                   "injected_ttt": 2, "baseline_ttt": 7},
        }
        v = judge_registry_warm_start_benefit(pairs, channel="fake")
        assert v["verdict"] == "PASS"
        assert v["median_improvement_pct"] == 0.0  # cost 持平→走 ttt 分支

    def test_no_improvement_honest_fail(self):
        pairs = {
            "s1": {"injected_first": 1.0, "baseline_first": 1.0},
            "s2": {"injected_first": 1.1, "baseline_first": 1.0},
            "s3": {"injected_first": 0.95, "baseline_first": 1.0},
        }
        v = judge_registry_warm_start_benefit(pairs, channel="fake")
        assert v["verdict"] == "FAIL" and v["pass"] is False
        assert "如实 FAIL" in v["why"]

    def test_censored_pairs_counted(self):
        pairs = {
            "s1": {"injected_first": 0.2, "baseline_first": 1.0},
            "s2": {"injected_first": None, "baseline_first": 1.0},
            "s3": {"injected_first": 0.3, "baseline_first": None},
        }
        v = judge_registry_warm_start_benefit(pairs, channel="openems")
        assert v["n_censored"] == 2 and v["n_pairs"] == 3
        assert v["verdict"] == "PASS"  # 唯一有效对 80% 改善
        assert v["channel"] == "openems"

    def test_custom_threshold(self):
        pairs = {"s1": {"injected_first": 0.9, "baseline_first": 1.0}}
        v = judge_registry_warm_start_benefit(pairs, threshold_pct=5.0)
        assert v["verdict"] == "PASS"
        v2 = judge_registry_warm_start_benefit(pairs, threshold_pct=20.0)
        assert v2["verdict"] == "FAIL"


# ─── CLI 三态开关接线（不新增叶，计数零）─────────────────────────────────────


class TestTuneCliFlag:
    def test_tune_help_renders_with_flag(self):
        """--help 真跑不炸（#305）；rich 窄端截断旗标名——按 help 文本+
        旗标前缀钉（截断形态 warm-start-regis…）。"""
        from typer.testing import CliRunner

        from rfauto.cli.domains.workflow import app

        runner = CliRunner()
        # COLUMNS=200 宽渲染：rich 窄表截断点随平台 CJK 宽度计算漂移
        # （Linux CI 截断位比 Windows 更早，截断前缀钉假红，2026-10-07
        # 首跑实证）——强制宽端让旗标完整渲染，断言语义跨平台稳定
        result = runner.invoke(app, ["tune", "--help"],
                               env={"COLUMNS": "200"})
        assert result.exit_code == 0
        flat = result.output.replace("\n", "").replace(" ", "")
        # 宽端无截断：旗标全名+help 关键词钉（真跑不炸=#305 主判据）
        assert "代理模型注册表" in flat and "warm-start" in flat
        assert "--warm-start-regis" in flat
        assert "--no-warm-start-r" in flat

    def test_non_single_path_explicit_flag_not_silent(self, tmp_path):
        """显式开关走非单目标路径：如实提示不静默（#122）；--json 下提示走
        stderr、stdout 信封保持纯净。"""
        from typer.testing import CliRunner

        from rfauto.cli.domains.workflow import app

        recipe = tmp_path / "r.yaml"
        recipe.write_text(yaml.safe_dump({
            "model": "wilkinson_power_divider",
            "objectives": [{"metric": "s11_db", "band": [2.3, 2.5],
                            "op": "max_below", "value": -15}],
            "optimization": {"params": {
                "arm_len_mm": {"low": 18.0, "high": 23.0}}},
        }), encoding="utf-8")
        runner = CliRunner()
        result = runner.invoke(app, [
            "tune", str(recipe), "--multi", "--detach",
            "--warm-start-registry", "--json"])
        # detach 拒绝非单目标后台化（既有语义）→ 退出码 1，但三态开关的
        # "仅单目标路径生效"提示必须已如实发出（#122 不静默）
        assert result.exit_code == 1
        combined = (result.output or "") + (
            getattr(result, "stderr", "") or "")
        assert "仅单目标路径生效" in combined
