"""DP-9 P1：内容寻址缓存（键 + CAS manifest + 零拷贝索引）测试。

覆盖判据 ②（确定性钉）/③（负例矩阵）/④（incomplete 半产物不命中）。
零真机零网络：全部 tmp 目录合成。
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess

import pytest

from rfauto.infra.dag_cache import (
    ARTIFACT_MANIFEST_NAME,
    INVALIDATION_REASONS,
    DagCasIndex,
    compute_key,
    compute_node_key,
    digest_of_files,
    env_fingerprint,
    file_sha256,
    node_components,
    read_artifact_manifest,
    registration_commit_ts,
    render_components,
    sha256_text,
    solve_components,
    uv_lock_sha256,
    verify_artifacts,
    why_miss,
    write_artifact_manifest,
)

# 判据 ②③④ 的载体：键计算（render/solve/node）、CAS manifest、零拷贝索引。


@pytest.fixture
def repo_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[2]


# ─── 判据 ②：确定性钉 ───────────────────────────────────────────────────────

def test_render_key_deterministic_and_order_insensitive() -> None:
    kw = dict(render_script="print(1)", registration_commit_ts="1727000000",
              params_canonical_json='{"a":1,"b":2}', mesh_config={"tier": "mid"},
              engine_version="hfss-2026")
    assert render_components(**kw) == render_components(**kw)
    assert compute_key("render", render_components(**kw)) == \
        compute_key("render", render_components(**kw))
    # params dict 键序不影响 canonical JSON（键稳定语义）
    c1 = render_components(params_canonical_json=json.dumps(
        {"a": 1, "b": 2}, sort_keys=True))
    c2 = render_components(params_canonical_json=json.dumps(
        {"b": 2, "a": 1}, sort_keys=True))
    assert c1 == c2
    assert compute_key("render", c1) == compute_key("render", c2)


def test_render_key_components_separated_for_why_miss() -> None:
    comps = render_components(render_script="x", mesh_config="m")
    assert set(comps) == {"render_script_sha", "registration_commit_ts",
                          "params_canonical_json", "mesh_config",
                          "engine_version"}
    assert comps["render_script_sha"] == sha256_text("x")


def test_node_key_payload_versions_separate_kinds() -> None:
    comps = node_components(input_digests="d", cmd="c")
    rk = compute_key("render", render_components(render_script="s"))
    nk = compute_node_key("node", comps, node_id="p1")
    assert rk != nk  # 载体 kind 分离（render/solve/node 互不串键）
    assert compute_node_key("node", comps, node_id="p1") == nk  # 确定性


# ─── 判据 ③：负例矩阵（翻转任一成分必变键）──────────────────────────────────

def test_negative_matrix_any_component_flip_changes_key() -> None:
    base = dict(render_script="script", registration_commit_ts="1727000000",
                params_canonical_json='{"w":0.5}', mesh_config={"tier": "mid"},
                engine_version="hfss-2026")
    base_key = compute_key("render", render_components(**base))
    flips = [
        {"render_script": "script-V2"},
        {"registration_commit_ts": "1727000001"},
        {"params_canonical_json": '{"w":0.6}'},
        {"mesh_config": {"tier": "fine"}},
        {"engine_version": "hfss-2027"},
    ]
    for flip in flips:
        changed = dict(base)
        changed.update(flip)
        assert compute_key("render", render_components(**changed)) != base_key, (
            f"翻转 {flip} 未改变键（假命中风险）")


def test_negative_matrix_solve_key_flips() -> None:
    base = solve_components(render_artifact_sha256="a" * 64,
                            engine_version="hfss", budget_tier={"nrts": 100})
    assert solve_components(render_artifact_sha256="b" * 64,
                            engine_version="hfss",
                            budget_tier={"nrts": 100}) != base
    assert solve_components(render_artifact_sha256="a" * 64,
                            engine_version="hfss27",
                            budget_tier={"nrts": 100}) != base
    # 预算档必进键（#343/#262 族：不同 NrTS 时窗产物不互串）
    assert solve_components(render_artifact_sha256="a" * 64,
                            engine_version="hfss",
                            budget_tier={"nrts": 200}) != base
    # 预算档 dict 键序不敏感（canonical JSON，同档同键）
    assert solve_components(
        render_artifact_sha256="a" * 64, engine_version="hfss",
        budget_tier={"timeout_s": 9, "nrts": 100},
    ) == solve_components(
        render_artifact_sha256="a" * 64, engine_version="hfss",
        budget_tier={"nrts": 100, "timeout_s": 9},
    )


def test_rerun_trigger_filtering_excludes_component() -> None:
    all_on = ["code", "params", "env", "budget"]
    no_env = ["code", "params", "budget"]
    comps_v1 = dict(node_components(input_digests="d", cmd="c",
                                    env_fingerprint_sha="ENV1"))
    comps_v2 = dict(node_components(input_digests="d", cmd="c",
                                    env_fingerprint_sha="ENV2"))
    up = {"r": "K1"}
    # env 触发器开启：环境指纹变 → 键变
    assert compute_node_key("node", comps_v1, node_id="p", triggers=all_on,
                            upstream_keys=up) != compute_node_key(
        "node", comps_v2, node_id="p", triggers=all_on, upstream_keys=up)
    # env 触发器关闭：环境指纹变 → 键不变（分级语义）
    assert compute_node_key("node", comps_v1, node_id="p", triggers=no_env,
                            upstream_keys=up) == compute_node_key(
        "node", comps_v2, node_id="p", triggers=no_env, upstream_keys=up)
    # 上游键传导：上游键变 → 下游键变（递归重算的键层面保证）
    k_up1 = compute_node_key("node", comps_v1, node_id="p", triggers=all_on,
                             upstream_keys={"r": "K1"})
    k_up2 = compute_node_key("node", comps_v1, node_id="p", triggers=all_on,
                             upstream_keys={"r": "K2"})
    assert k_up1 != k_up2


def test_why_miss_non_empty_with_field_name() -> None:
    stored = render_components(render_script="old", engine_version="v1")
    requested = render_components(render_script="new", engine_version="v1")
    reasons = why_miss(requested, stored)
    assert reasons and any("render_script_sha" in r for r in reasons)
    assert any(INVALIDATION_REASONS["render_script_sha"] in r for r in reasons)
    assert why_miss(requested, None)  # 无可比条目也有解释


# ─── 环境指纹（collect_provenance 复用 + uv.lock sha256）────────────────────

def test_env_fingerprint_shape_and_uv_lock(repo_root) -> None:
    fp = env_fingerprint(repo_root)
    assert set(fp) == {"git_sha", "pip_freeze_sha", "uv_lock_sha256"}
    assert fp["uv_lock_sha256"] == uv_lock_sha256(repo_root)
    lock = repo_root / "uv.lock"
    if lock.is_file():
        manual = hashlib.sha256(lock.read_bytes()).hexdigest()
        assert fp["uv_lock_sha256"] == manual
    assert env_fingerprint(repo_root) == fp          # 同环境确定性


def test_uv_lock_and_registration_ts_best_effort(tmp_path) -> None:
    assert uv_lock_sha256(tmp_path) == ""       # 无 uv.lock → 空串不抛
    assert registration_commit_ts(None) == ""
    assert registration_commit_ts(tmp_path / "ghost.py") == ""


def test_env_fingerprint_git_sha_populated(repo_root) -> None:
    """review-slice4 P3-5：git_sha 组件补全（subprocess git rev-parse
    best-effort #105）。git 环境下=HEAD 短 SHA、两次调用同值（同 HEAD 键
    确定=缓存键不变性）；非 git 环境 → ""（键面与补全前逐位同值）。"""
    fp = env_fingerprint(repo_root)
    ref = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                         cwd=str(repo_root), capture_output=True, text=True)
    if ref.returncode == 0 and ref.stdout.strip():
        assert fp["git_sha"] == ref.stdout.strip()
        assert env_fingerprint(repo_root)["git_sha"] == fp["git_sha"]
    else:
        assert fp["git_sha"] == ""               # 无 git 环境：空串不抛


def test_git_sha_short_best_effort(tmp_path, monkeypatch) -> None:
    """_git_sha_short：非 git 目录 → ""；子进程异常 → ""（#105 不抛穿）；
    env_fingerprint 键面三键不因补值变化（键集钉）。"""
    from rfauto.infra.dag_cache import _git_sha_short

    assert _git_sha_short(tmp_path) == ""
    assert _git_sha_short(tmp_path / "ghost") == ""

    def _boom(*args, **kwargs):
        raise OSError("git unavailable（mock）")

    monkeypatch.setattr(subprocess, "run", _boom)
    assert _git_sha_short() == ""
    fp = env_fingerprint()
    assert set(fp) == {"git_sha", "pip_freeze_sha", "uv_lock_sha256"}
    assert fp["git_sha"] == ""


# ─── 判据 ④：CAS manifest 与 incomplete 语义 ────────────────────────────────

def test_manifest_roundtrip_and_verify(tmp_path) -> None:
    (tmp_path / "out.bin").write_bytes(b"PAYLOAD")
    manifest = write_artifact_manifest(tmp_path, ["out.bin"], complete=True,
                                       node_id="r1", key="K")
    assert manifest.name == ARTIFACT_MANIFEST_NAME
    ok, problems = verify_artifacts(tmp_path)
    assert ok and not problems
    data = read_artifact_manifest(tmp_path)
    assert data["complete"] is True
    assert data["files"][0]["sha256"] == hashlib.sha256(
        b"PAYLOAD").hexdigest()
    # 篡改产物字节 → digest 校验败（Nextflow 加强版）
    (tmp_path / "out.bin").write_bytes(b"TAMPERED")
    ok, problems = verify_artifacts(tmp_path)
    assert not ok and any("digest 不符" in p for p in problems)


def test_incomplete_and_missing_manifest_never_hit(tmp_path) -> None:
    (tmp_path / "a.txt").write_text("x")
    write_artifact_manifest(tmp_path, ["a.txt"], complete=False)
    ok, problems = verify_artifacts(tmp_path)
    assert not ok and any("incomplete" in p for p in problems)
    # manifest 缺失（从未写/被清）→ never-hit 口径
    empty = tmp_path / "nothing_here"
    empty.mkdir()
    ok, problems = verify_artifacts(empty)
    assert not ok and any("清单缺失" in p for p in problems)
    assert verify_artifacts(tmp_path / "ghost")[0] is False


def test_missing_file_changes_digest(tmp_path) -> None:
    (tmp_path / "a.txt").write_text("x")
    d1 = digest_of_files(tmp_path, ["a.txt"])
    d2 = digest_of_files(tmp_path, ["ghost.txt"])
    assert d1 != d2 and d1 and d2          # 缺文件计 MISSING，digest 必变
    assert file_sha256(tmp_path / "ghost.txt") == ""


def test_manifest_write_is_atomic_no_tmp_left(tmp_path) -> None:
    (tmp_path / "a.txt").write_text("x")
    write_artifact_manifest(tmp_path, ["a.txt"])
    leftovers = [p.name for p in tmp_path.iterdir()
                 if ".tmp-" in p.name]
    assert leftovers == []


# ─── 零拷贝索引（只增不改不删；RFAUTO_CACHE 模式语义）────────────────────────

def test_index_store_lookup_hit_zero_copy(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("RFAUTO_CACHE", raising=False)
    run_dir = tmp_path / "run1"
    (run_dir / "results").mkdir(parents=True)
    (run_dir / "results" / "s.csv").write_text("freq,s11\n")
    write_artifact_manifest(run_dir / "results", ["s.csv"])
    index = DagCasIndex(tmp_path / "cache")
    key = "K" * 64
    index.store_index(key, run_dir=run_dir / "results", node_kind="solve",
                      components={"engine_version": "v1"})
    hit = index.lookup(key)
    assert hit["hit"] is True
    assert hit["path"] == str(run_dir / "results")   # 零拷贝引用原 run_dir
    assert hit["manifest"]["complete"] is True


def test_index_lookup_miss_matrix(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("RFAUTO_CACHE", raising=False)
    index = DagCasIndex(tmp_path / "cache")
    # ① 无索引条目 → miss 且 why_miss 非空（判据 ③）
    miss = index.lookup("A" * 64,
                        components={"engine_version": "v1"})
    assert miss["hit"] is False and miss["why_miss"]
    # ② 有索引无 manifest（旧档）→ never-hit
    run_dir = tmp_path / "run_legacy"
    run_dir.mkdir()
    key = "B" * 64
    index.store_index(key, run_dir=run_dir)
    miss2 = index.lookup(key)
    assert miss2["hit"] is False and "清单" in miss2["why_miss"][0]
    # ③ incomplete manifest → miss
    (run_dir / "o.txt").write_text("x")
    write_artifact_manifest(run_dir, ["o.txt"], complete=False)
    miss3 = index.lookup(key)
    assert miss3["hit"] is False and any(
        "incomplete" in p for p in miss3["why_miss"])
    # ④ complete 但产物被篡改 → digest 败 miss（原因非空）
    write_artifact_manifest(run_dir, ["o.txt"], complete=True)
    (run_dir / "o.txt").write_text("TAMPERED")
    miss4 = index.lookup(key)
    assert miss4["hit"] is False and miss4["why_miss"]


def test_index_append_only_first_writer_wins(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("RFAUTO_CACHE", raising=False)
    index = DagCasIndex(tmp_path / "cache")
    key = "C" * 64
    index.store_index(key, run_dir=tmp_path / "a", extra={"epoch": 1})
    first = (tmp_path / "cache" / f"{key}.json").read_text(encoding="utf-8")
    index.store_index(key, run_dir=tmp_path / "b", extra={"epoch": 2})
    assert (tmp_path / "cache" / f"{key}.json").read_text(
        encoding="utf-8") == first          # 只增不改不删


def test_index_modes_off_and_readonly(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("RFAUTO_CACHE", "off")
    off = DagCasIndex(tmp_path / "cache_off")
    assert off.enabled is False
    assert off.store_index("K", run_dir=tmp_path) is None
    res = off.lookup("K")
    assert res["hit"] is False and "旁路" in res["why_miss"][0]

    # readwrite 先写一条；readonly 实例指向同一目录：能读、不能写
    monkeypatch.setenv("RFAUTO_CACHE", "readwrite")
    rw = DagCasIndex(tmp_path / "cache_rw")
    run_dir = tmp_path / "run1"
    run_dir.mkdir()
    (run_dir / "o.txt").write_text("x")
    write_artifact_manifest(run_dir, ["o.txt"])
    rw.store_index("K" * 64, run_dir=run_dir)
    monkeypatch.setenv("RFAUTO_CACHE", "readonly")
    ro = DagCasIndex(tmp_path / "cache_rw")
    assert ro.enabled is True
    hit = ro.lookup("K" * 64)
    assert hit["hit"] is True                        # 只读可读
    assert ro.store_index("K2" * 64, run_dir=run_dir) is None  # 只读不写
    assert not (tmp_path / "cache_rw" / f"{'K2' * 64}.json").exists()
    monkeypatch.setenv("RFAUTO_CACHE", "bogus")
    assert DagCasIndex(tmp_path / "cache_bad")._mode == "readwrite"


def test_index_readwrite_mode_is_default(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("RFAUTO_CACHE", raising=False)
    index = DagCasIndex(tmp_path / "cache")
    assert index.enabled is True and index._mode == "readwrite"


def test_nearest_entry_skips_tmp_residue(tmp_path, monkeypatch) -> None:
    """E3-7（ge8e 审查批 F4）回归钉：`{key}.tmp-{pid}` 残留不进比对面。

    原过滤 `endswith(".tmp-*")` 恒 False（字面 * 不出现在真实文件名）；
    现子串守卫 `.tmp-` 语义正确——tmp 残留（非 json 命名，glob 已排除）
    即使被手工改名为 .json 也不会被当成比对面消费。"""
    monkeypatch.delenv("RFAUTO_CACHE", raising=False)
    cache = tmp_path / "cache"
    index = DagCasIndex(cache)
    # 合法索引一条（比对面）
    (cache / "aaaaaaaa.json").write_text(
        json.dumps({"components": {"tpl": "wilkinson", "er": "4.4"}}),
        encoding="utf-8")
    # tmp 残留（真实命名规约：无 .json 后缀，glob 本就不拾）
    (cache / "bbbbbbbb.tmp-4242").write_text("{broken", encoding="utf-8")
    # 纵深形态：tmp 残留伪装成合法 .json 索引（守卫必须在解析/比对前
    # 剔除——旧死过滤下此条会以 diffs=0 赢得比对，本测试即红）
    (cache / "cccccccc.tmp-4242.json").write_text(
        json.dumps({"components": {"tpl": "patch", "er": "2.2"}}),
        encoding="utf-8")
    best = index._nearest_entry({"tpl": "wilkinson", "er": "4.4"})
    assert best == {"tpl": "wilkinson", "er": "4.4"}
    # 全不同成分：合法条目仍参与比对，tmp 伪装条目不抛不入选
    best2 = index._nearest_entry({"tpl": "patch", "er": "2.2"})
    assert best2 == {"tpl": "wilkinson", "er": "4.4"}
