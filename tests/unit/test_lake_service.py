"""F3（df7）runs/ 湖索引+分层压实 MVP 测试。

判据（规格预声明）：
- 索引：tmp 造合成战役目录（多 run/多形态）→ build_runs_index 行数/
  字段正确 + 缺失 meta 跳过如实（NULL 不臆造）+ 幂等重建行数不变；
  query_runs_index 参数化过滤（template/adapter/study/campaign/日期段）；
  duckdb 缺装显式报缺（monkeypatch 钉住通道 #139）。
- 压实：tmp 迷你战役（meta+csv+二进制杂项）→ pack → verify 全绿 →
  restore 后逐字节对比（filecmp/哈希）；同内容重打包 pack_sha256 逐位
  一致（确定性排序+归一化 tar 头）。
- 篡改检测：篡改 pack 一个字节 → verify ok=False（整包锚/解压面抓出）；
  篡改清单单文件 sha256 → verify 逐文件定位该文件 FAIL、其余 ok。
- 绝不覆盖：restore 目标已存在（目录/文件）→ 拒；清单含穿越路径 →
  预检拒绝且目标目录零创建（#325/#326 绝不重写历史同构）。

chdir 隔离零污染（#144）；依赖 duckdb（dataset extra）与 zstandard
（冷层压实），缺失时诚实 skip / 显式报缺分支用 monkeypatch 钉住。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

pytest.importorskip("duckdb", reason="湖索引需要 dataset extra（duckdb）")
pytest.importorskip("zstandard", reason="冷层压实需要 zstandard（tar.zst）")

import filecmp

from rfauto.service import lake_service
from rfauto.service.lake_service import (
    build_runs_index,
    pack_campaign,
    query_runs_index,
    restore_campaign,
    verify_campaign,
)

# ---------------------------------------------------------------------------
# 合成 runs/ 湖与迷你战役目录
# ---------------------------------------------------------------------------

def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _meta(model: str, adapter: str, study: str,
          ts: str) -> dict:
    return {"run_id": "x", "model": model, "adapter": adapter,
            "study_name": study, "status": "done", "timestamp": ts,
            "seed": 42}


@pytest.fixture
def lake_env(tmp_path, monkeypatch):
    """合成 runs/ 湖：一级战役+二级点+独立 run+run_meta 变体+损坏 meta
    +纯工具目录。chdir 隔离（#144），索引库落 tmp。"""
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "runs"
    # 战役 camp_a：两个二级 run 点（meta 齐备，其一有 verdict.json）
    _write_json(root / "camp_a" / "pt1" / "meta.json",
                _meta("mline", "fake", "s1", "2026-08-01T10:00:00+00:00"))
    _write_json(root / "camp_a" / "pt1" / "verdict.json",
                {"verdict": "healthy", "factors": []})
    _write_json(root / "camp_a" / "pt1" / "results" / "params.s2p",
                {"dummy": True})
    _write_json(root / "camp_a" / "pt2" / "meta.json",
                _meta("cpw", "openems", "s2", "2026-09-15T10:00:00+00:00"))
    # 独立 run（一级 run 点，depth=1）
    _write_json(root / "solo_run" / "meta.json",
                _meta("patch_antenna", "hfss", "s3",
                      "2026-09-20T08:00:00+00:00"))
    # run_meta.json 变体（外部工具链口径）
    _write_json(root / "camp_a" / "pt_runmeta" / "run_meta.json",
                _meta("wilkinson", "fake", "s4", "2026-09-10T00:00:00+00:00"))
    # 损坏 meta（存在但解析失败 → has_meta True、字段 NULL，不阻塞）
    bad = root / "camp_a" / "pt_corrupt"
    bad.mkdir(parents=True)
    (bad / "meta.json").write_text("{not-json", encoding="utf-8")
    # 纯工具目录（无任何 meta/verdict → 字段 NULL 如实）
    (root / "datasets").mkdir(parents=True)
    return tmp_path


def _mini_campaign(root: Path) -> None:
    """迷你战役：meta+csv+二进制杂项+嵌套子目录+中文名文件。"""
    _write_json(root / "campaign_x" / "pt1" / "meta.json", _meta(
        "mline", "fake", "s1", "2026-09-01T00:00:00+00:00"))
    (root / "campaign_x" / "pt1" / "results").mkdir(parents=True)
    (root / "campaign_x" / "pt1" / "results" / "sparams.csv").write_text(
        "freq_hz,s11_db\n2.0e9,-10.5\n2.1e9,-12.0\n", encoding="utf-8")
    (root / "campaign_x" / "pt1" / "results" / "blob.bin").write_bytes(
        bytes(range(256)) * 8)
    (root / "campaign_x" / "pt1" / "网格说明.md").write_text(
        "# 网格\nNEAR=BASE/4\n", encoding="utf-8")
    _write_json(root / "campaign_x" / "pt2" / "meta.json", _meta(
        "cpw", "openems", "s2", "2026-09-02T00:00:00+00:00"))
    (root / "campaign_x" / "pt2" / "criteria.md").write_text(
        "# 预声明判据\n谷深<=-20dB\n", encoding="utf-8")


def _tree_files(root: Path) -> dict[str, bytes]:
    """目录树逐文件字节表（相对 posix 路径 → 内容）。"""
    out: dict[str, bytes] = {}
    for current, _dirs, filenames in os.walk(root):
        for filename in filenames:
            abs_path = Path(current) / filename
            out[abs_path.relative_to(root).as_posix()] = abs_path.read_bytes()
    return out


# ---------------------------------------------------------------------------
# 索引面
# ---------------------------------------------------------------------------

class TestBuildRunsIndex:
    def test_rows_fields_and_honest_nulls(self, lake_env):
        db = lake_env / "lake.duckdb"
        r = build_runs_index(lake_env / "runs", db_path=db)
        assert r["ok"], r.get("errors")
        # 7 目录全入索引：camp_a + 4 点 + solo_run + datasets
        assert r["n_rows"] == 7
        assert r["n_meta_rows"] == 5   # pt1/pt2/solo_run/pt_runmeta/pt_corrupt
        assert r["n_verdict_rows"] == 1
        q = query_runs_index(db_path=db)
        assert q["ok"]
        rows = {row["path"]: row for row in q["rows"]}
        # 实测字段正确
        pt1 = rows["camp_a/pt1"]
        assert pt1["template"] == "mline" and pt1["adapter"] == "fake"
        assert pt1["study"] == "s1" and pt1["status"] == "done"
        assert pt1["created_ts"] == "2026-08-01T10:00:00+00:00"
        assert str(pt1["created_date"]) == "2026-08-01"
        assert pt1["campaign"] == "camp_a" and pt1["depth"] == 2
        assert pt1["has_meta"] and pt1["meta_source"] == "meta.json"
        assert pt1["has_verdict"] and pt1["verdict"] == "healthy"
        assert pt1["size_bytes"] > 0 and pt1["n_files"] == 3
        # 独立 run：depth=1、campaign NULL
        solo = rows["solo_run"]
        assert solo["depth"] == 1 and solo["campaign"] is None
        assert solo["template"] == "patch_antenna"
        # run_meta.json 变体：meta_source 如实标注
        pt_rm = rows["camp_a/pt_runmeta"]
        assert pt_rm["has_meta"] and pt_rm["meta_source"] == "run_meta.json"
        assert pt_rm["template"] == "wilkinson"
        # 损坏 meta：存在即 has_meta=True，字段 NULL（缺失跳过如实）
        bad = rows["camp_a/pt_corrupt"]
        assert bad["has_meta"] and bad["meta_source"] == "meta.json"
        assert bad["template"] is None and bad["study"] is None
        # 纯工具目录：全 NULL 但目录本身在册（size/n_files 实测）
        ds = rows["datasets"]
        assert not ds["has_meta"] and ds["template"] is None
        assert ds["size_bytes"] == 0 and ds["n_files"] == 0

    def test_idempotent_rebuild_same_rows(self, lake_env):
        db = lake_env / "lake.duckdb"
        r1 = build_runs_index(lake_env / "runs", db_path=db)
        r2 = build_runs_index(lake_env / "runs", db_path=db)
        assert r1["ok"] and r2["ok"]
        assert r1["n_rows"] == r2["n_rows"] == 7
        q = query_runs_index(db_path=db)
        assert q["n_rows"] == 7  # drop-create 重建无残留

    def test_missing_runs_dir_zero_value_no_db(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        r = build_runs_index(tmp_path / "nope")
        assert r["ok"] and r["n_rows"] == 0
        assert "runs 目录不存在" in (r.get("note") or "")
        assert not (tmp_path / "runs" / ".lake_index.duckdb").exists()

    def test_duckdb_missing_explicit_error(self, lake_env, monkeypatch):
        monkeypatch.setitem(sys.modules, "duckdb", None)
        r = build_runs_index(lake_env / "runs",
                             db_path=lake_env / "lake.duckdb")
        assert not r["ok"]
        assert "rfauto[dataset]" in r["errors"][0]


class TestQueryRunsIndex:
    def test_filters_and_date_range(self, lake_env):
        db = lake_env / "lake.duckdb"
        assert build_runs_index(lake_env / "runs", db_path=db)["ok"]

        def q(**kw):
            r = query_runs_index(db_path=db, **kw)
            assert r["ok"], r.get("errors")
            return [row["path"] for row in r["rows"]]

        assert q(template="mline") == ["camp_a/pt1"]
        assert q(adapter="openems") == ["camp_a/pt2"]
        assert q(study="s3") == ["solo_run"]
        assert q(campaign="camp_a") == [
            "camp_a/pt1", "camp_a/pt2", "camp_a/pt_corrupt",
            "camp_a/pt_runmeta"]  # path 排序
        # 日期段（created_date 闭区间）
        assert set(q(date_from="2026-09-01", date_to="2026-09-30")) == {
            "camp_a/pt2", "solo_run", "camp_a/pt_runmeta"}
        assert q(date_from="2026-08-01", date_to="2026-08-31") == \
            ["camp_a/pt1"]
        # limit 截断
        limited = query_runs_index(db_path=db, limit=2)
        assert limited["ok"] and limited["n_rows"] == 2
        # 组合过滤
        assert q(campaign="camp_a", adapter="openems") == ["camp_a/pt2"]

    def test_bad_date_and_missing_db(self, lake_env):
        db = lake_env / "lake.duckdb"
        assert build_runs_index(lake_env / "runs", db_path=db)["ok"]
        bad = query_runs_index(db_path=db, date_from="2026/09/01")
        assert not bad["ok"] and "日期段非法" in bad["errors"][0]
        missing = query_runs_index(db_path=lake_env / "nope.duckdb")
        assert not missing["ok"] and "不存在" in missing["errors"][0]


# ---------------------------------------------------------------------------
# 压实/校验/恢复面
# ---------------------------------------------------------------------------

@pytest.fixture
def packed_env(tmp_path, monkeypatch):
    """迷你战役 → 打包产物（pack/manifest 路径挂 fixture 返回）。"""
    monkeypatch.chdir(tmp_path)
    campaign = tmp_path / "runs" / "campaign_x"
    _mini_campaign(tmp_path / "runs")
    pack = tmp_path / "packs" / "campaign_x.tar.zst"
    r = pack_campaign(campaign, pack)
    assert r["ok"], r.get("errors")
    return {"campaign": campaign, "pack": pack,
            "manifest": Path(r["manifest_path"]), "result": r}


class TestPackVerifyRestore:
    def test_verify_green_after_pack(self, packed_env):
        """pack → verify 全绿（整包锚+逐文件全 ok）。"""
        v = verify_campaign(packed_env["pack"], packed_env["manifest"])
        assert v["ok"], v.get("errors")
        assert v["pack_sha256_ok"]
        assert v["n_fail"] == 0 and v["n_ok"] == 6
        assert all(f["ok"] for f in v["files"])

    def test_restore_roundtrip_byte_identical(self, packed_env, tmp_path):
        """restore → 逐字节对比（filecmp/哈希）：恢复树与原战役全等。"""
        target = tmp_path / "restored" / "campaign_x"
        r = restore_campaign(packed_env["pack"], packed_env["manifest"],
                             target)
        assert r["ok"], r.get("errors")
        assert r["n_verified"] == r["n_files"] == 6
        src_files = _tree_files(packed_env["campaign"])
        dst_files = _tree_files(target)
        assert src_files == dst_files  # 内容逐字节全等（含中文名/二进制）
        for rel in src_files:
            assert filecmp.cmp(packed_env["campaign"] / rel, target / rel,
                               shallow=False)

    def test_pack_deterministic_same_content_same_sha(self, packed_env,
                                                      tmp_path):
        """确定性排序+归一化 tar 头：同内容重打包 pack_sha256 逐位一致，
        清单（除 created_at）逐位一致。"""
        pack2 = tmp_path / "packs" / "campaign_x_again.tar.zst"
        r2 = pack_campaign(packed_env["campaign"], pack2)
        assert r2["ok"]
        assert r2["pack_sha256"] == packed_env["result"]["pack_sha256"]
        m1 = json.loads(packed_env["manifest"].read_text(encoding="utf-8"))
        m2 = json.loads(Path(r2["manifest_path"]).read_text(encoding="utf-8"))
        m1.pop("created_at")
        m2.pop("created_at")
        m1.pop("pack_file")  # 两次打包产物文件名本就不同
        m2.pop("pack_file")
        assert m1 == m2

    def test_verify_catches_pack_byte_tamper(self, packed_env):
        """篡改 pack 一个字节 → verify ok=False（整包锚/解压面抓出）。"""
        data = bytearray(packed_env["pack"].read_bytes())
        data[-1] ^= 0xFF  # 翻转最后一字节
        packed_env["pack"].write_bytes(bytes(data))
        v = verify_campaign(packed_env["pack"], packed_env["manifest"])
        assert not v["ok"]
        assert v["errors"] or v["n_fail"] > 0

    def test_verify_localizes_manifest_sha_tamper(self, packed_env):
        """篡改清单单文件 sha256 → verify 逐文件定位：该文件 FAIL、
        其余 ok、整包锚不受影响（pack 未动）。"""
        manifest = json.loads(
            packed_env["manifest"].read_text(encoding="utf-8"))
        victim = next(f for f in manifest["files"]
                      if f["path"].endswith("sparams.csv"))
        victim["sha256"] = "0" * 64
        packed_env["manifest"].write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        v = verify_campaign(packed_env["pack"], packed_env["manifest"])
        assert not v["ok"]
        assert v["pack_sha256_ok"]
        assert v["n_fail"] == 1
        failed = [f for f in v["files"] if not f["ok"]]
        assert len(failed) == 1
        assert failed[0]["path"] == victim["path"]
        assert "sha256 不符" in failed[0]["reason"]

    def test_restore_refuses_existing_target(self, packed_env, tmp_path):
        """恢复目标已存在 → 拒（目录/文件皆拒，绝不覆盖）。"""
        target_dir = tmp_path / "restored" / "x1"
        r1 = restore_campaign(packed_env["pack"], packed_env["manifest"],
                              target_dir)
        assert r1["ok"]
        r2 = restore_campaign(packed_env["pack"], packed_env["manifest"],
                              target_dir)
        assert not r2["ok"] and "拒绝恢复" in r2["errors"][0]
        # 目标路径是文件同样拒
        file_target = tmp_path / "restored_file"
        file_target.parent.mkdir(parents=True, exist_ok=True)
        file_target.write_text("occupied", encoding="utf-8")
        r3 = restore_campaign(packed_env["pack"], packed_env["manifest"],
                              file_target)
        assert not r3["ok"] and "拒绝恢复" in r3["errors"][0]

    def test_restore_rejects_traversal_manifest(self, packed_env, tmp_path):
        """清单含穿越路径 → 预检拒绝，目标目录零创建（写面防线）。"""
        manifest = json.loads(
            packed_env["manifest"].read_text(encoding="utf-8"))
        manifest["files"][0]["path"] = "../evil.bin"
        bad_manifest = tmp_path / "evil.manifest.json"
        bad_manifest.write_text(json.dumps(manifest, ensure_ascii=False),
                                encoding="utf-8")
        target = tmp_path / "restored" / "evil"
        r = restore_campaign(packed_env["pack"], bad_manifest, target)
        assert not r["ok"]
        assert "非法相对路径" in r["errors"][0]
        assert not target.exists()

    def test_restore_refuses_tampered_pack(self, packed_env, tmp_path):
        """整包哈希不符 → 恢复预检拒绝（内容寻址锚，绝不半恢复）。"""
        data = bytearray(packed_env["pack"].read_bytes())
        data[len(data) // 2] ^= 0x01
        packed_env["pack"].write_bytes(bytes(data))
        target = tmp_path / "restored" / "tampered"
        r = restore_campaign(packed_env["pack"], packed_env["manifest"],
                             target)
        assert not r["ok"]
        assert not target.exists()

    def test_pack_missing_dir_and_zstandard(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        missing = pack_campaign(tmp_path / "nope", tmp_path / "x.tar.zst")
        assert not missing["ok"] and "不存在" in missing["errors"][0]
        campaign = tmp_path / "camp"
        campaign.mkdir()
        (campaign / "a.txt").write_text("hi", encoding="utf-8")
        monkeypatch.setitem(sys.modules, "zstandard", None)
        no_zst = pack_campaign(campaign, tmp_path / "y.tar.zst")
        assert not no_zst["ok"]
        assert "zstandard" in no_zst["errors"][0]

    def test_default_manifest_path_and_db_default_name(self, tmp_path):
        """缺省清单落点 <pack>.manifest.json；索引库缺省名
        runs/.lake_index.duckdb（口径钉）。"""
        assert lake_service._manifest_path_for(
            Path("out/campaign.tar.zst")).as_posix() == \
            "out/campaign.tar.zst.manifest.json"
        assert lake_service.default_lake_index_db_path().as_posix() == \
            "runs/.lake_index.duckdb"
