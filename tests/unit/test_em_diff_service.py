"""em diff 服务面测试（aurora_k K18 席，2026-10-23；反馈 P17/F13）。

覆盖四节：params 逐键/模型清单按 name（**用户验收场景复现**：aperture z
0–190 → 0–295.2 必须一眼可见）/S 参数同栅对拍（#287/#294 家法：同栅直通
+异栅 argmin 最近邻+不相交如实 skip）/K4 新鲜度交叉。缺节如实 skip
（不伪造空 diff）；同 run 自 diff 恒零。

隔离纪律（#144）：全部 run 目录落 pytest tmp_path（绝对路径入参，不经
runs_root 收敛），零 runs/ 湖污染。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

from rfauto.cli.main import app as root_app
from rfauto.service.em_diff_service import (
    DIFF_SECTIONS,
    diff_runs,
    to_text,
)

# ── 合成 run 目录工厂（meta params + K5 模型清单 + Touchstone 可独立开关） ────

_BASE_PARAMS = {"mesh_mm": 0.5, "er": 12.85, "tan_d": 0.006}


def _manifest(*, aperture_zmax: float = 190.0, extra_port: bool = False,
              drop_object: str | None = None) -> dict:
    """八角电感族 K5 清单（用户 ind_wp 形态：aperture z 覆盖是验收靶）。"""
    objects = [
        {"name": "coil", "bbox": [-100, -100, 200.2, 100, 100, 205.2],
         "net": "signal", "kind": "metal", "material": "Au"},
        {"name": "gnd_ring", "bbox": [-300, -300, 0, 300, 300, 5],
         "net": "ground", "kind": "metal"},
    ]
    if drop_object:
        objects = [o for o in objects if o["name"] != drop_object]
    ports = [
        {"name": "P1", "plane": {"axis": "y", "at": -700},
         "aperture_bbox": [-120, -700, 0.0, 120, -698, aperture_zmax],
         "num_modes": 1, "on_boundary": True, "gap": 30},
    ]
    if extra_port:
        ports.append(
            {"name": "P2", "plane": {"axis": "y", "at": 700},
             "aperture_bbox": [-120, 698, 0.0, 120, 700, aperture_zmax],
             "num_modes": 1, "on_boundary": True, "gap": 30})
    return {
        "units": "um",
        "domain": {"bbox": [-700, -700, -50, 700, 700, 250]},
        "objects": objects,
        "ports": ports,
        "stackup": [
            {"name": "GaAs", "thickness": 200.0, "material": "GaAs",
             "z_range": [0.0, 200.0]},
            {"name": "FM", "thickness": 5.0, "material": "Au",
             "z_range": [200.2, 205.2]},
        ],
    }


def _write_touchstone(run_dir: Path, *, band_shift_db: float = 0.0,
                      drop_point: bool = False) -> None:
    """合成 2 端口 Touchstone：S11 −10 dB（可选 [2.3,2.5] GHz 带内平移
    band_shift_db）、S21 −1 dB；drop_point=抽掉带内一点（异栅最近邻用）。"""
    import skrf

    f = np.linspace(1e9, 5e9, 81)
    if drop_point:
        f = np.delete(f, 40)
    freq = skrf.Frequency.from_f(f, unit="hz")
    s11 = np.full(len(f), 10 ** (-10 / 20), dtype=complex)
    s21 = np.full(len(f), 10 ** (-1 / 20), dtype=complex)
    if band_shift_db:
        band = (f >= 2.3e9) & (f <= 2.5e9)
        s11[band] = s11[band] * 10 ** (band_shift_db / 20)
    s = np.zeros((len(f), 2, 2), dtype=complex)
    s[:, 0, 0] = s11
    s[:, 1, 1] = s11
    s[:, 0, 1] = s21
    s[:, 1, 0] = s21
    net = skrf.Network(frequency=freq, s=s, z0=50)
    out = run_dir / "results" / "params.s2p"
    out.parent.mkdir(parents=True, exist_ok=True)
    net.write_touchstone(str(out))


def _mk_run(tmp_path: Path, name: str, *, params: dict | None = _BASE_PARAMS,
            manifest: dict | None = None, touchstone: bool = True,
            band_shift_db: float = 0.0, drop_point: bool = False,
            k4_manifest_sha: str | None = None) -> Path:
    """合成一个 run 目录（各数据面独立开关；缺面=缺节测试形态）。"""
    d = tmp_path / name
    d.mkdir(parents=True)
    meta: dict = {"adapter": "hfss", "model": "ind_wp", "status": "done"}
    if params is not None:
        meta["params"] = params
    (d / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    if manifest is not None:
        (d / "model_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    if touchstone:
        _write_touchstone(d, band_shift_db=band_shift_db, drop_point=drop_point)
    if k4_manifest_sha is not None:
        (d / "manifest.json").write_text(json.dumps({
            "run_id": name,
            "touchstones": {"results/params.s2p": {"sha256": k4_manifest_sha}},
        }, ensure_ascii=False), encoding="utf-8")
    return d


# ── 用户验收场景（P17 原文靶） ───────────────────────────────────────────────


class TestUserAcceptance:
    def test_aperture_z_change_visible(self, tmp_path: Path):
        """ind_wp（旧）vs ind_wp_fix2（新）：aperture z 0–190 → 0–295.2
        必须在文本渲染里一眼可见（P17 验收原文）。"""
        a = _mk_run(tmp_path, "ind_wp", manifest=_manifest(aperture_zmax=190.0))
        b = _mk_run(tmp_path, "ind_wp_fix2",
                    manifest=_manifest(aperture_zmax=295.2))
        result = diff_runs(a, b, at_ghz=[2.4])
        assert result["ok"] is True
        rows = [r for r in result["model_changes"]
                if r["group"] == "ports" and r["name"] == "P1"]
        assert len(rows) == 1
        row = rows[0]
        assert row["kind"] == "change"
        assert row["fields"]["aperture_bbox"]["old"][5] == 190.0
        assert row["fields"]["aperture_bbox"]["new"][5] == 295.2
        text = to_text(result)
        assert "aperture_bbox z: 0–190 → 0–295.2" in text
        assert result["summary"]["n_model_changes"] == 1

    def test_sparam_band_shift_worst_in_band(self, tmp_path: Path):
        """已知 S 曲线带内平移 3 dB → worst_dev=3 dB 且 worst_freq 落带内。"""
        a = _mk_run(tmp_path, "run_a", touchstone=True)
        b = _mk_run(tmp_path, "run_b", touchstone=True, band_shift_db=3.0)
        result = diff_runs(a, b, at_ghz=[2.4])
        sp = result["sparam_diff"]
        assert sp["status"] == "ok"
        assert sp["alignment"] == "same_grid"
        assert sp["worst_sparam"] == "S11"
        assert sp["worst_dev_db"] == pytest.approx(3.0, abs=0.01)
        assert 2.3e9 <= sp["worst_freq_hz"] <= 2.5e9
        # @2.4 GHz 定点读数：S11 差=3 dB、S21 差=0
        req = sp["at_points"][0]
        assert req["kind"] == "requested"
        assert req["requested_hz"] == pytest.approx(2.4e9)
        assert req["s11_dev_db"] == pytest.approx(3.0, abs=0.01)
        assert req["s21_dev_db"] == pytest.approx(0.0, abs=1e-6)
        text = to_text(result)
        assert "最大偏差 3" in text
        assert "@2.4 GHz" in text


# ── params 节 ───────────────────────────────────────────────────────────────


class TestParamsSection:
    def test_added_removed_changed(self, tmp_path: Path):
        a = _mk_run(tmp_path, "a", params={"mesh_mm": 0.5, "er": 12.85,
                                           "tan_d": 0.006})
        b = _mk_run(tmp_path, "b", params={"mesh_mm": 0.3, "er": 12.85,
                                           "loss_tangent": 0.002})
        result = diff_runs(a, b)
        assert result["params_status"] == "ok"
        by_key = {r["key"]: r for r in result["params_changes"]}
        assert set(by_key) == {"mesh_mm", "tan_d", "loss_tangent"}
        assert by_key["mesh_mm"]["kind"] == "changed"
        assert by_key["mesh_mm"]["old"] == 0.5
        assert by_key["mesh_mm"]["new"] == 0.3
        assert by_key["tan_d"]["kind"] == "removed"
        assert by_key["loss_tangent"]["kind"] == "added"
        assert by_key["loss_tangent"]["new"] == 0.002

    def test_same_run_zero_diff(self, tmp_path: Path):
        """同 run 自 diff：四节全零（NaN/bool 恒等语义的回归钉）。"""
        d = _mk_run(tmp_path, "same", manifest=_manifest(),
                    k4_manifest_sha="0" * 64)
        result = diff_runs(d, d)
        assert result["ok"] is True
        assert result["params_changes"] == []
        assert result["model_changes"] == []
        assert result["sparam_diff"]["status"] == "ok"
        assert result["sparam_diff"]["worst_dev_db"] == pytest.approx(0.0)
        # K4 指纹与盘上一致（sha 不可能对上——同 run 双侧各算各的，且
        # 记录值 0*64 与实际不符 → 双侧同为 stale，但两侧一致即交叉成立）
        assert result["freshness"]["a"]["status"] == \
            result["freshness"]["b"]["status"]


# ── manifest 节 ─────────────────────────────────────────────────────────────


class TestManifestSection:
    def test_port_and_object_add_remove(self, tmp_path: Path):
        a = _mk_run(tmp_path, "a", manifest=_manifest())
        b = _mk_run(tmp_path, "b",
                    manifest=_manifest(extra_port=True, drop_object="gnd_ring"))
        result = diff_runs(a, b)
        rows = result["model_changes"]
        add = [r for r in rows if r["kind"] == "add"]
        rem = [r for r in rows if r["kind"] == "remove"]
        assert [(r["group"], r["name"]) for r in add] == [("ports", "P2")]
        assert [(r["group"], r["name"]) for r in rem] == \
            [("objects", "gnd_ring")]
        text = to_text(result)
        assert "端口 P2: B 新增" in text
        assert "对象 gnd_ring: B 无此条" in text

    def test_stackup_thickness_change(self, tmp_path: Path):
        a = _mk_run(tmp_path, "a", manifest=_manifest())
        man = _manifest()
        man["stackup"][1]["thickness"] = 5.2
        man["stackup"][1]["z_range"] = [200.2, 205.4]
        b = _mk_run(tmp_path, "b", manifest=man)
        result = diff_runs(a, b)
        row = next(r for r in result["model_changes"]
                   if r["group"] == "stackup")
        assert row["name"] == "FM"
        assert row["fields"]["thickness"] == {"old": 5.0, "new": 5.2}
        assert "z: 200.2–205.2 → 200.2–205.4" in to_text(result)

    def test_one_side_missing_manifest_skip(self, tmp_path: Path):
        a = _mk_run(tmp_path, "a", manifest=_manifest())
        b = _mk_run(tmp_path, "b", manifest=None)
        result = diff_runs(a, b)
        assert result["model_status"] == "skip"
        assert "B 侧无" in result["model_skip_reason"]
        assert result["manifest_files"]["a"] is not None
        assert result["manifest_files"]["b"] is None

    def test_corrupt_manifest_skip_not_fake(self, tmp_path: Path):
        """清单损坏 → 该节 skip 如实（不伪造空 diff 冒充可比）。"""
        a = _mk_run(tmp_path, "a", manifest=_manifest())
        b = _mk_run(tmp_path, "b", manifest=None)
        (b / "model_manifest.json").write_text("{不是 JSON", encoding="utf-8")
        result = diff_runs(a, b)
        assert result["model_status"] == "skip"
        assert "装载失败" in result["model_skip_reason"]


# ── sparams 节（#287/#294 频栅对齐家法） ─────────────────────────────────────


class TestSparamsSection:
    def test_nearest_neighbor_alignment(self, tmp_path: Path):
        """B 栅抽一点 → 异栅 argmin 最近邻配对（80/81 点入拍）。"""
        a = _mk_run(tmp_path, "a", touchstone=True)
        b = _mk_run(tmp_path, "b", touchstone=True, drop_point=True)
        result = diff_runs(a, b)
        sp = result["sparam_diff"]
        assert sp["status"] == "ok"
        assert sp["alignment"] == "nearest_neighbor"
        assert sp["n_points_a"] == 81
        assert sp["n_points_b"] == 80
        assert sp["n_matched"] == 80
        assert any("异栅最近邻配对" in n for n in sp["notes"])

    def test_disjoint_grid_skip(self, tmp_path: Path):
        """频段不相交 → skip 如实（不硬凑空对拍）。"""
        a = _mk_run(tmp_path, "a", touchstone=True)
        b = _mk_run(tmp_path, "b", touchstone=True)
        import skrf

        net = skrf.Network(str(b / "results" / "params.s2p"))
        net.frequency.f[:] = net.frequency.f + 20e9  # 平移出公共带
        net.write_touchstone(str(b / "results" / "params.s2p"))
        result = diff_runs(a, b)
        assert result["sparam_diff"]["status"] == "skip"
        assert "不相交" in result["sparam_diff"]["reason"]

    def test_port_count_mismatch_skip(self, tmp_path: Path):
        import skrf

        a = _mk_run(tmp_path, "a", touchstone=True)
        b = _mk_run(tmp_path, "b", touchstone=False)
        f = skrf.Frequency.from_f(np.linspace(1e9, 5e9, 41), unit="hz")
        s = (0.1 * np.ones((41, 1, 1))).astype(complex)
        net = skrf.Network(frequency=f, s=s, z0=50)
        (b / "results").mkdir(exist_ok=True)
        net.write_touchstone(str(b / "results" / "params.s1p"))
        result = diff_runs(a, b)
        sp = result["sparam_diff"]
        assert sp["status"] == "skip"
        assert "端口数不同" in sp["reason"]


# ── 空频栅守卫（R4 审查 P3：空数组进对拍核会 IndexError/ValueError）─────────


class _StubNet:
    """最小网络 stub（.f/.s/.nports 三件套——_diff_sparams 只消费这些）。"""

    def __init__(self, f) -> None:
        self.f = np.asarray(f, dtype=float)
        self.nports = 2
        self.s = np.zeros((len(self.f), 2, 2), dtype=complex)


class TestSparamsEmptyGridGuard:
    def test_empty_freq_a_skips(self) -> None:
        """A 侧空频栅 → skip 带说明（守卫前 skip 理由读 f[0] 必 IndexError）。"""
        from rfauto.service.em_diff_service import _diff_sparams

        result = _diff_sparams(_StubNet([]), _StubNet([1e9, 2e9]), [])
        assert result["status"] == "skip"
        assert "频点为空" in result["reason"]
        assert "A 0 点" in result["reason"]

    def test_empty_freq_b_and_both_empty_skip(self) -> None:
        """B 侧空频栅（守卫前空 argmin 必 ValueError）与双侧全空同样 skip
        ——双侧全空在旧链路会 allclose(∅,∅)=True 假同栅后 argmax 炸。"""
        from rfauto.service.em_diff_service import _diff_sparams

        result = _diff_sparams(_StubNet([1e9, 2e9]), _StubNet([]), [])
        assert result["status"] == "skip"
        assert "B 0 点" in result["reason"]
        both = _diff_sparams(_StubNet([]), _StubNet([]), [])
        assert both["status"] == "skip"
        assert "频点为空" in both["reason"]


# ── 节选择 / 缺节 / 新鲜度 ──────────────────────────────────────────────────


class TestSectionsAndFreshness:
    def test_sections_filter_freshness_always(self, tmp_path: Path):
        a = _mk_run(tmp_path, "a", manifest=_manifest())
        b = _mk_run(tmp_path, "b", manifest=_manifest(aperture_zmax=295.2))
        result = diff_runs(a, b, sections=("sparams",))
        assert result["params_status"] == "not_requested"
        assert result["params_changes"] == []
        assert result["model_status"] == "not_requested"
        assert result["sparam_diff"]["status"] == "ok"
        assert set(result["freshness"]) == {"a", "b"}

    def test_bare_run_all_sections_skip(self, tmp_path: Path):
        """无 params/清单/Touchstone 的裸 run → 三节全 skip 且原因非空。"""
        d = _mk_run(tmp_path, "bare", params=None, manifest=None,
                    touchstone=False)
        result = diff_runs(d, d)
        for status_key, reason_key in (
                ("params_status", "params_skip_reason"),
                ("model_status", "model_skip_reason")):
            assert result[status_key] == "skip"
            assert result[reason_key]
        assert result["sparam_diff"]["status"] == "skip"
        assert result["sparam_diff"]["reason"]
        assert result["freshness"]["a"]["status"] == "legacy"

    def test_freshness_stale_cross(self, tmp_path: Path):
        """K4 指纹不符 → 该侧 stale 如实回带（P11/F7 交叉线）。"""
        a = _mk_run(tmp_path, "a", k4_manifest_sha="0" * 64)
        b = _mk_run(tmp_path, "b")
        result = diff_runs(a, b)
        assert result["freshness"]["a"]["status"] == "stale"
        assert result["freshness"]["b"]["status"] == "legacy"
        assert result["summary"]["freshness"] == {"a": "stale", "b": "legacy"}

    def test_unknown_section_rejected(self, tmp_path: Path):
        a = _mk_run(tmp_path, "a")
        result = diff_runs(a, a, sections=("bogus",))
        assert result["ok"] is False
        assert any("未知对比节" in e for e in result["errors"])

    def test_missing_run_dir_error(self, tmp_path: Path):
        result = diff_runs(tmp_path / "ghost", tmp_path / "ghost2")
        assert result["ok"] is False
        assert result["errors"]


# ── 人读渲染 ────────────────────────────────────────────────────────────────


class TestToText:
    def test_no_rich_markup_brackets(self, tmp_path: Path):
        """纯文本渲染禁 rich markup 方括号（CLI console.print 直出防注入）。"""
        a = _mk_run(tmp_path, "a", manifest=_manifest())
        b = _mk_run(tmp_path, "b",
                    manifest=_manifest(aperture_zmax=295.2, extra_port=True))
        text = to_text(diff_runs(a, b))
        assert "[" not in text
        assert text.startswith("em diff")

    def test_skip_sections_rendered(self, tmp_path: Path):
        d = _mk_run(tmp_path, "bare", params=None, manifest=None,
                    touchstone=False)
        text = to_text(diff_runs(d, d))
        assert "本节跳过" in text
        assert "本节未选" not in text


# ── CLI 冒烟 ────────────────────────────────────────────────────────────────


class TestCliDiff:
    def test_json_envelope(self, tmp_path: Path):
        a = _mk_run(tmp_path, "ind_wp", manifest=_manifest())
        b = _mk_run(tmp_path, "ind_wp_fix2",
                    manifest=_manifest(aperture_zmax=295.2))
        result = CliRunner().invoke(
            root_app, ["em", "diff", str(a), str(b), "--at-ghz", "2.4",
                       "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["ok"] is True
        assert payload["summary"]["n_model_changes"] == 1
        assert payload["sparam_diff"]["status"] == "ok"

    def test_text_output(self, tmp_path: Path):
        a = _mk_run(tmp_path, "ind_wp", manifest=_manifest())
        b = _mk_run(tmp_path, "ind_wp_fix2",
                    manifest=_manifest(aperture_zmax=295.2))
        result = CliRunner().invoke(root_app, ["em", "diff", str(a), str(b)])
        assert result.exit_code == 0, result.output
        assert "em diff" in result.output
        assert "0–190 → 0–295.2" in result.output

    def test_usage_error_unknown_section(self, tmp_path: Path):
        a = _mk_run(tmp_path, "a")
        result = CliRunner().invoke(
            root_app, ["em", "diff", str(a), str(a), "--sections", "bogus",
                       "--json"])
        assert result.exit_code == 2
        payload = json.loads(result.output)
        assert payload["ok"] is False

    def test_usage_error_bad_at_ghz(self, tmp_path: Path):
        a = _mk_run(tmp_path, "a")
        result = CliRunner().invoke(
            root_app, ["em", "diff", str(a), str(a), "--at-ghz", "abc",
                       "--json"])
        assert result.exit_code == 2
        payload = json.loads(result.output)
        assert payload["ok"] is False

    def test_missing_dir_json_envelope(self, tmp_path: Path):
        result = CliRunner().invoke(
            root_app, ["em", "diff", str(tmp_path / "ghost"),
                       str(tmp_path / "ghost2"), "--json"])
        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["ok"] is False
        assert payload["errors"]


def test_diff_sections_constant_order():
    """节名全集顺序稳定（CLI help 与渲染顺序的镜像面）。"""
    assert DIFF_SECTIONS == ("params", "manifest", "sparams", "freshness")
