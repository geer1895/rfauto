"""W3-A RB-WN-1 湖语义压缩三件套单测（合成小湖 fixture，全离线零网络）。

判据映射（sa_specs2 §5.3 预声明门值，runs/w3_phase3/criteria.md W3-A）：
- 判据 1 golden 零改写（#325）：dry-run 清单/删除清单 ∩ 保护面=∅ 脚本断言
  + apply（合成 fixture 上）前后保护面字节零变；
- 判据 2 等效无损（VF 摘要）：L∞_linear ≤5e-3 → lossless_equivalent；
  超界如实 bounded_lossy 带 linf 值；不带误差界的摘要不落盘；
- 判据 3 去重零信息损失：去重后 et/ht 字节读回==去重前（sha256 复核）+
  硬链接计数 st_nlink≥2；
- 判据 4 可逆性：manifest 重放可重建原始目录布局（链接回填，模拟面）。
真实湖面零触碰（dry-run 只读报告见 runs/w3_phase3/w3a/，破坏性动作等用户窗）。
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from rfauto.cli.main import app
from rfauto.infra.lake_blob_store import (
    blob_rel_path,
    maybe_dedup_workdir_et_ht,
)
from rfauto.service.lake_compact_service import (
    LINF_LOSSLESS_THRESHOLD,
    _rational_response,
    apply_et_ht_dedup,
    apply_h5_retention,
    plan_et_ht_dedup,
    plan_h5_retention,
    read_sparams_summary,
    sparams_summary,
)
from rfauto.service.sim_ci_service import BASELINE_SCHEMA

runner = CliRunner()

_OLD = 3 * 86400.0  # meta 落盘 3 天前（越 min_age_h=24 缺省线）


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_hashes(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for current, _dirs, files in os.walk(root):
        for name in files:
            p = Path(current) / name
            out[p.relative_to(root).as_posix()] = _sha(p)
    return out


def _age_file(path: Path, seconds: float = _OLD) -> None:
    st = path.stat()
    os.utime(path, (st.st_atime - seconds, st.st_mtime - seconds))


def _write_run(run_dir: Path, *, status: str | None, h5: bytes = b"H5DATA",
                et: list[bytes] | None = None, ht: bytes | None = None,
                extra: dict[str, bytes] | None = None,
                aged: bool = True) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "field.h5").write_bytes(h5)
    if status is not None:
        meta = run_dir / "meta.json"
        meta.write_text(json.dumps({"status": status,
                                    "timestamp": "2026-09-01T00:00:00"}),
                        encoding="utf-8")
        if aged:
            _age_file(meta)
    for i, payload in enumerate(et or [], start=1):
        p = run_dir / f"port_ut_{i}.et"
        p.write_bytes(payload)
        if aged:
            _age_file(p)
    if ht is not None:
        p = run_dir / "port_ut_1.ht"
        p.write_bytes(ht)
        if aged:
            _age_file(p)
    for name, payload in (extra or {}).items():
        p = run_dir / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(payload)
        if aged:
            _age_file(p)


def _sparams_csv(path: Path, *, notch: bool = False) -> None:
    """合成 2端口 sparams.csv（5 列 schema，101 点 1-3GHz）。

    平滑档=有理函数响应（单极点型，VF 低阶即可达 -40dB rms → 阶梯首档
    早停，避开病态定阶）；notch 档在 s21 上乘深窄谷（VF 低阶不可表 →
    有界有损路径）。
    """
    import numpy as np

    f = np.linspace(1.0, 3.0, 101)
    x = f - 2.0
    s11 = 0.3 / (1.0 + 1j * x / 0.5)
    s21 = (0.9 + 0.2j * x) / (1.0 + 0.4j * x)
    if notch:
        s21 = s21 * (1.0 - 0.99999 * np.exp(-((x) / 0.05) ** 2))
    rows = ["freq_hz,s11_re,s11_im,s21_re,s21_im"]
    for k in range(f.size):
        rows.append(f"{f[k] * 1e9:.6e},{s11[k].real:.9e},"
                    f"{s11[k].imag:.9e},{s21[k].real:.9e},{s21[k].imag:.9e}")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


@pytest.fixture()
def mini_lake(tmp_path: Path) -> dict[str, Path]:
    """合成小湖：锚证据/基线/golden 名字启发/在跑/新近/三档可删候选全形态。"""
    runs = tmp_path / "runs"
    et_payload = b"TRANSIENT-ET-1" * 64
    ht_payload = b"TRANSIENT-HT-1" * 64
    # 锚证据目录（指针指向其内 verdict 文件——整目录保留语义）
    anchor = runs / "anchor_ev_x"
    _write_run(anchor, status="done", et=[et_payload],
               extra={"hfss_side/verdict.json": b"{}"})
    # simci golden 基线 run（XD-5 pin 面）
    _write_run(runs / "pt_simci", status="done")
    # 名字启发保留（review token）
    _write_run(runs / "golden_review_x", status="done")
    # campaign_a：三档候选
    camp = runs / "campaign_a"
    judged = camp / "pt_judged"
    _write_run(judged, status="judged",
               et=[et_payload, et_payload], ht=ht_payload)  # et 重复对
    _sparams_csv(judged / "sparams.csv")
    analyzed = camp / "pt_analyzed"
    _write_run(analyzed, status="analyzed", h5=b"H5-ANALYZED",
               extra={"verdict.json": b"{\"verdict\": \"PASS\"}"})
    done_only = camp / "pt_done"
    _write_run(done_only, status="done", h5=b"H5-DONE")
    inflight = camp / "pt_inflight"
    _write_run(inflight, status=None, h5=b"H5-INFLIGHT", et=[et_payload])
    recent = camp / "pt_recent"
    _write_run(recent, status="judged", h5=b"H5-RECENT", aged=False)
    # campaign_b：aggressive 档候选（done 无判读产物）
    camp_b = runs / "campaign_b"
    _write_run(camp_b / "pt_old_done", status="done", h5=b"H5-B",
               et=[b"UNIQUE-ET-B" * 32])
    # 指针源（tmp 治内，隔离真仓 knowledge）
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "anchors.yaml").write_text(
        yaml.safe_dump({"anchors": [{
            "anchor_id": "a1",
            "provenance": {
                "arbitration_runs": ["runs/anchor_ev_x/hfss_side/verdict.json"],
            },
        }]}, allow_unicode=True), encoding="utf-8")
    (knowledge / "simci_baseline.yaml").write_text(
        yaml.safe_dump({"schema": BASELINE_SCHEMA,
                        "pinned_run_id": "pt_simci",
                        "model_run_ids": {"mline": "pt_simci"}},
                       allow_unicode=True), encoding="utf-8")
    pointers = [(knowledge / "anchors.yaml", "anchor_evidence"),
                (knowledge / "simci_baseline.yaml", "baseline_ref")]
    return {"runs": runs, "pointers": pointers, "knowledge": knowledge,
            "judged": judged, "analyzed": analyzed, "done": done_only,
            "inflight": inflight, "recent": recent,
            "anchor": anchor, "simci": runs / "pt_simci"}


class TestH5Retention:
    def test_tiers_material_and_protection(self, mini_lake):
        plan = plan_h5_retention(mini_lake["runs"], tier="medium",
                                 pointer_sources=mini_lake["pointers"])
        assert plan["ok"] is True
        assert plan["golden_rewrite_audit"]["violations"] == []
        run_names = {r["run_dir"].split("/")[-1] for r in plan["delete"]}
        # 保护面零进删除清单（判据 1 的规划面）
        assert "anchor_ev_x" not in run_names
        assert "pt_simci" not in run_names
        assert "golden_review_x" not in run_names
        assert "pt_inflight" not in run_names  # 无 meta=在跑，任何档不可删
        assert "pt_recent" not in run_names  # min_age_h 内=新近，不动
        # medium 档：judged/analyzed 可删，done-only 不可
        assert "pt_judged" in run_names and "pt_analyzed" in run_names
        assert "pt_done" not in run_names
        assert run_names  # 非空清单
        # 三档单调（材料不替裁）：conservative ⊆ medium ⊆ aggressive
        tiers = plan["tiers"]
        assert tiers["conservative"]["n_delete"] <= tiers["medium"]["n_delete"]
        assert tiers["medium"]["n_delete"] <= tiers["aggressive"]["n_delete"]
        assert tiers["aggressive"]["n_delete"] > tiers["medium"]["n_delete"]
        # conservative 档连 analyzed（status 语义）可删——两种状态都收
        assert tiers["conservative"]["n_delete"] >= 2

    def test_golden_zero_rewrite_dryrun_and_apply(self, mini_lake, tmp_path):
        """判据 1（#325 红线）：dry-run 零写；apply 后保护面字节零变。"""
        runs = mini_lake["runs"]
        before = _tree_hashes(runs)
        plan = plan_h5_retention(runs, tier="medium",
                                 pointer_sources=mini_lake["pointers"])
        assert _tree_hashes(runs) == before  # dry-run 零写面
        manifest = tmp_path / "h5_manifest.json"
        result = apply_h5_retention(plan, manifest_path=manifest,
                                    runs_root=runs)
        assert result["ok"] is True, result.get("errors")
        after = _tree_hashes(runs)
        # 保护面（锚/基线/名字启发/在跑/新近）逐文件字节零变
        protected_prefixes = ("anchor_ev_x", "pt_simci", "golden_review_x",
                              "campaign_a/pt_inflight", "campaign_a/pt_recent")
        for rel, digest in before.items():
            if rel.startswith(protected_prefixes):
                assert after.get(rel) == digest, f"保护面被改: {rel}"
        # 删除的恰是 plan 点名文件；manifest 可审计
        for row in plan["delete"]:
            assert not (runs / row["path"]).exists()
        assert manifest.is_file()
        body = json.loads(manifest.read_text(encoding="utf-8"))
        assert body["n_entries"] == len(plan["delete"])
        assert all(e["operation_commit"] is not None for e in body["entries"])
        # 二次 apply：清单已空，零删
        plan2 = plan_h5_retention(runs, tier="medium",
                                  pointer_sources=mini_lake["pointers"])
        result2 = apply_h5_retention(plan2, manifest_path=manifest,
                                     runs_root=runs)
        assert result2["ok"] is True and result2["n_deleted"] == 0

    def test_keep_recent_n_exempts_newest(self, mini_lake):
        plan = plan_h5_retention(mini_lake["runs"], tier="medium",
                                 keep_recent_n=1,
                                 pointer_sources=mini_lake["pointers"])
        run_names = {r["run_dir"].split("/")[-1] for r in plan["delete"]}
        # campaign_a 候选里最新（timestamp 字典序）的 pt_judged 被豁免
        assert "pt_judged" not in run_names
        assert "pt_analyzed" in run_names


class TestEtHtDedup:
    def test_plan_stats(self, mini_lake):
        plan = plan_et_ht_dedup(mini_lake["runs"],
                                pointer_sources=mini_lake["pointers"])
        assert plan["ok"] is True
        assert plan["n_dup_files"] >= 1  # pt_judged 的 et 重复对
        assert plan["bytes_dup_total"] >= 13 * 64
        assert plan["n_protected"] >= 1  # anchor_ev_x 的 et 受保护计数

    def test_apply_hardlink_and_bytes_readback(self, mini_lake):
        """判据 3：去重零信息损失（sha256 读回一致 + st_nlink≥2）。"""
        runs = mini_lake["runs"]
        judged = mini_lake["judged"]
        et_files = sorted(judged.glob("*.et"))
        before_bytes = {p.name: p.read_bytes() for p in et_files}
        result = apply_et_ht_dedup(runs, pointer_sources=mini_lake["pointers"])
        assert result["ok"] is True, result.get("errors")
        assert result["n_linked"] >= 2
        for p in et_files:
            assert p.read_bytes() == before_bytes[p.name]  # 字节读回一致
            assert os.stat(p).st_nlink >= 2  # 硬链接计数
        # blob store 布局 {et,ht}/<sha256 前 16>
        import hashlib as _hl

        digest = _hl.sha256(before_bytes[et_files[0].name]).hexdigest()
        blob = runs / ".blob_store" / Path(blob_rel_path("et", digest))
        assert blob.is_file() and blob.name == digest[:16]
        # 保护面 et（anchor_ev_x）零触碰（未被链接，独立 inode）
        anchor_et = next(mini_lake["anchor"].glob("*.et"))
        assert os.stat(anchor_et).st_nlink == 1

    def test_manifest_replay_rebuilds_layout(self, mini_lake, tmp_path):
        """判据 4（可逆性）：manifest 重放从 blob store 链接回填。"""
        from rfauto.infra.lake_blob_store import (
            blob_store_root,
            dedup_tree_et_ht,
            restore_et_ht_from_manifest,
        )

        runs = mini_lake["runs"]
        protected = set(_pointer_norms(mini_lake["runs"],
                                       mini_lake["pointers"]))
        from rfauto.service.lake_compact_service import _inflight_dir_norms

        protected |= _inflight_dir_norms(runs)
        result = dedup_tree_et_ht(runs, blob_store_root(runs),
                                  protected_norm=protected, min_age_h=24.0,
                                  manifest_path=tmp_path / "dedup_m.json")
        assert result["ok"] is True, result.get("errors")
        manifest = tmp_path / "dedup_m.json"
        assert manifest.is_file()
        body = json.loads(manifest.read_text(encoding="utf-8"))
        assert body["entries"], "manifest 应有去重条目"
        # 模拟重建：回填到新目录（测试面模拟，不触碰原湖）
        target = tmp_path / "rebuilt_runs"
        restored = restore_et_ht_from_manifest(manifest, target_root=target)
        assert restored["ok"] is True, restored.get("errors")
        for entry in body["entries"]:
            back = target / entry["path"]
            assert back.is_file()
            assert _sha(back) == entry["sha256"]  # 字节读回一致

    def test_increment_hook_env_gated(self, tmp_path, monkeypatch):
        work = tmp_path / "fdtd"
        work.mkdir()
        payload = b"HOOK-ET" * 128
        (work / "port_ut_1.et").write_bytes(payload)
        store = tmp_path / "store"
        monkeypatch.delenv("RFAUTO_LAKE_DEDUP_ET_HT", raising=False)
        assert maybe_dedup_workdir_et_ht(work, store_root=store) is None
        assert not store.exists()  # 缺省零副作用
        monkeypatch.setenv("RFAUTO_LAKE_DEDUP_ET_HT", "1")
        out = maybe_dedup_workdir_et_ht(work, store_root=store)
        assert out is not None and out["n_linked"] == 1
        p = work / "port_ut_1.et"
        assert p.read_bytes() == payload
        assert os.stat(p).st_nlink >= 2


class TestVfSummary:
    def test_lossless_equivalent_and_readback(self, mini_lake):
        """判据 2：平滑族 L∞≤5e-3 → lossless_equivalent（误差界在档）。"""
        out = sparams_summary(mini_lake["judged"])
        assert out["ok"] is True, out.get("errors")
        assert out["fidelity_class"] == "lossless_equivalent"
        assert out["linf_error_linear"] <= LINF_LOSSLESS_THRESHOLD
        path = mini_lake["judged"] / "sparams.vf.json"
        assert path.is_file()
        body = json.loads(path.read_text(encoding="utf-8"))
        for key in ("schema_version", "n_poles", "poles", "residues",
                    "d_coeff", "freq_band", "linf_error_linear",
                    "linf_error_db", "rms_error", "fidelity_class",
                    "passivity_state", "provenance"):
            assert key in body, f"摘要缺 spec 键: {key}"
        assert body["provenance"]["source_csv_sha256"] == \
            _sha(mini_lake["judged"] / "sparams.csv")
        # 消费面：零解压读回 + 重建模型逼近已测元素
        read = read_sparams_summary(mini_lake["judged"])
        assert read["ok"] is True
        import numpy as np

        from rfauto.service.health_service import _parse_sparams_csv_masked
        from rfauto.service.lake_compact_service import s_model_from_summary

        freq, s_orig, mask = _parse_sparams_csv_masked(
            mini_lake["judged"] / "sparams.csv")
        s_recon = s_model_from_summary(read["summary"], freq)
        diff = np.abs(s_recon - s_orig)
        assert float(diff[:, mask].max()) <= LINF_LOSSLESS_THRESHOLD

    def test_bounded_lossy_reports_honest_bound(self, tmp_path, mini_lake):
        """深谷族不硬压：超界如实标 bounded_lossy 带 linf 值。"""
        run = tmp_path / "runs_notch" / "pt_notch"
        run.mkdir(parents=True)
        _sparams_csv(run / "sparams.csv", notch=True)
        (run / "meta.json").write_text(json.dumps({"status": "judged"}),
                                       encoding="utf-8")
        out = sparams_summary(run)
        assert out["ok"] is True, out.get("errors")
        assert out["fidelity_class"] == "bounded_lossy"
        assert out["linf_error_linear"] > LINF_LOSSLESS_THRESHOLD
        body = json.loads((run / "sparams.vf.json").read_text(
            encoding="utf-8"))
        assert body["fidelity_class"] == "bounded_lossy"
        assert body["linf_error_linear"] == out["linf_error_linear"]

    def test_fit_failure_writes_nothing(self, tmp_path):
        """不带误差界的摘要不落盘：源不可解析 → error 信封且零写面。"""
        run = tmp_path / "runs_bad" / "pt_bad"
        run.mkdir(parents=True)
        (run / "sparams.csv").write_text("not,a,csv\nx,y,z,z,z\n",
                                         encoding="utf-8")
        out = sparams_summary(run)
        assert out["ok"] is False
        assert not (run / "sparams.vf.json").exists()

    def test_reconstruction_matches_kernel_model_response(self):
        """重建口径与内核 model_response 等价（#118 独立回收钉）。"""
        import numpy as np
        import skrf
        from skrf.vectorFitting import VectorFitting

        from rfauto.core.macromodel import _poles_residues, model_response

        f = np.linspace(1e9, 3e9, 64)
        s11 = 0.3 * np.exp(-((f / 1e9 - 2.0) / 0.4) ** 2) \
            * np.exp(1j * 0.7 * (f / 1e9 - 2.0))
        s21 = np.sqrt(np.maximum(1.0 - np.abs(s11) ** 2, 0.0)) \
            * np.exp(-1j * 2 * np.pi * f / 1e9 * 0.15)
        s = np.zeros((f.size, 2, 2), dtype=complex)
        s[:, 0, 0] = s11
        s[:, 1, 0] = s21
        s[:, 0, 1] = s21
        s[:, 1, 1] = s11
        net = skrf.Network(frequency=f, s=s, z0=50.0)
        vf = VectorFitting(net)
        vf.vector_fit(n_poles_real=2, n_poles_cmplx=4)
        pr = _poles_residues(vf, 2)
        flat = pr["constant_coeff"]
        d_coeff = [[flat[i * 2 + j] for j in range(2)] for i in range(2)]
        recon = _rational_response(pr["poles_rad_s"], pr["residues"],
                                   d_coeff, f, 2)
        kernel = model_response(vf, f, 2)
        assert np.max(np.abs(recon - kernel)) < 1e-9

    def test_index_column_vf_summary(self, mini_lake, tmp_path):
        sparams_summary(mini_lake["judged"])  # 造摘要
        db = tmp_path / "lake.duckdb"
        from rfauto.service.lake_service import build_runs_index, query_runs_index

        built = build_runs_index(mini_lake["runs"], db_path=db)
        assert built["ok"] is True
        rows = query_runs_index(db, limit=100)["rows"]
        by_name = {row["path"]: row.get("vf_summary") for row in rows}
        assert by_name["campaign_a/pt_judged"] == "lossless_equivalent"
        assert by_name["campaign_a/pt_done"] is None  # 无摘要如实 NULL


def _pointer_norms(runs: Path, pointers) -> set[str]:
    from rfauto.service.lake_compact_service import extract_pointer_dirs

    return set(extract_pointer_dirs(runs, pointers).keys())


class TestCliCompact:
    def test_help_true_run(self):
        result = runner.invoke(app, ["lake", "compact", "--help"])
        assert result.exit_code == 0, result.output
        assert "--apply" in result.output
        assert "dry-run" in result.output

    def test_dryrun_default_zero_write(self, mini_lake):
        before = _tree_hashes(mini_lake["runs"])
        result = runner.invoke(app, [
            "lake", "compact", "--runs-root", str(mini_lake["runs"]),
            "--json"])
        assert result.exit_code == 0, result.output
        assert _tree_hashes(mini_lake["runs"]) == before  # 缺省纯读
        payload = json.loads(result.output)
        assert payload["ok"] is True
        assert payload["golden_rewrite_audit"]["violations"] == []

    def test_apply_refused_without_golden_pin(self, mini_lake, tmp_path):
        result = runner.invoke(app, [
            "lake", "compact", "--runs-root", str(mini_lake["runs"]),
            "--baseline-path", str(tmp_path / "no_baseline.yaml"),
            "--apply", "--json"])
        assert result.exit_code == 2
        assert "XD-5" in result.output or "pin" in result.output
        assert (mini_lake["judged"] / "field.h5").exists()  # 零删

    def test_apply_with_pinned_golden_and_manifest(self, mini_lake, tmp_path):
        runs = mini_lake["runs"]
        before = _tree_hashes(runs)
        manifest = tmp_path / "cli_h5_manifest.json"
        result = runner.invoke(app, [
            "lake", "compact", "--runs-root", str(runs),
            "--baseline-path", str(mini_lake["knowledge"]
                                   / "simci_baseline.yaml"),
            "--manifest", str(manifest), "--apply", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["ok"] is True and payload["n_deleted"] >= 2
        assert manifest.is_file()
        after = _tree_hashes(runs)
        for rel, digest in before.items():
            if rel.startswith(("anchor_ev_x", "pt_simci",
                               "golden_review_x")):
                assert after.get(rel) == digest, f"保护面被改: {rel}"

    def test_apply_dedup_under_same_interlock(self, mini_lake, tmp_path):
        runs = mini_lake["runs"]
        judged = mini_lake["judged"]
        et_before = {p.name: p.read_bytes() for p in judged.glob("*.et")}
        result = runner.invoke(app, [
            "lake", "compact", "--runs-root", str(runs),
            "--baseline-path", str(mini_lake["knowledge"]
                                   / "simci_baseline.yaml"),
            "--dedup-et-ht", "--apply", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["dedup"]["n_linked"] >= 2
        for p in judged.glob("*.et"):
            assert p.read_bytes() == et_before[p.name]
            assert os.stat(p).st_nlink >= 2


@pytest.mark.parametrize("tier", ["conservative", "medium", "aggressive"])
def test_all_tiers_plan_ok(mini_lake, tier):
    plan = plan_h5_retention(mini_lake["runs"], tier=tier,
                             pointer_sources=mini_lake["pointers"])
    assert plan["ok"] is True
    assert plan["golden_rewrite_audit"]["violations"] == []
