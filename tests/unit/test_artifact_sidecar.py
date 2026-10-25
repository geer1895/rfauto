"""曲线产物 sidecar 泛化测试（B4，aurora_l Wave-B：R2 Top8）。

K4 的 ``write_touchstone_sidecar`` 只服务 HFSS Touchstone；本批泛化为
``write_artifact_sidecar``（run_id+sha256+导出时间+kind 统一内容）并接到
各适配器解析落盘点：openEMS 主 chokepoint（``_parse_output``，覆盖全部
oe_templates）+ rotation 每轮 CSV（含断点复用补写）+ comsol/ngsolve/mmt/
pssfss/qucsator 各落盘点。消费面：``runs verify`` 增 ``curves_csv`` 段
（存在才记）同款 sha 比对 + sidecar 交叉核对。

全部确定性：合成解析输出/确定性内核（mmt WR-90 秒级），零真机零网络零
runs/ 湖写入。
"""

from __future__ import annotations

import hashlib
import json
import types
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from rfauto.adapters.em_solver_base import (
    EMSolverConfig,
    EMSolverType,
    get_global_registry,
)
from rfauto.adapters.openems_rotation import solve_smatrix_openems
from rfauto.adapters.openems_solver import OpenEMSSolver
from rfauto.service.runs_verify_service import (
    MANIFEST_FILENAME,
    manifest_for_run,
    verify_run,
    write_artifact_sidecar,
    write_manifest,
)

# ── 通用断言辅助 ─────────────────────────────────────────────────────────────


def _assert_sidecar(path: Path, *, kind: str, run_id: str) -> dict[str, Any]:
    """sidecar 在场 + 哈希对 + kind/run_id 归属对的统一断言。"""
    sidecar_path = path.parent / f"{path.name}.meta.json"
    assert sidecar_path.is_file(), f"sidecar 缺失: {sidecar_path}"
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    assert sidecar["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert sidecar["kind"] == kind
    assert sidecar["run_id"] == run_id
    assert sidecar["exported_at"]
    return sidecar


def _write_synth_csv(run_dir: Path, name: str = "sparams.csv") -> None:
    """openEMS 5 列 schema 合成解析输出（test_openems_solver 同构）。"""
    lines = [
        "freq_hz,re_S11,im_S11,re_S21,im_S21",
        "2e9,0.05,0.0,0.7,0.0",
        "3e9,0.1,0.0,0.6,0.0",
    ]
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── openEMS 主 chokepoint（覆盖全部 oe_templates）───────────────────────────


def _connected_solver(tmp_path: Path) -> OpenEMSSolver:
    s = OpenEMSSolver(EMSolverConfig(
        solver_type=EMSolverType.OPENEMS,
        working_dir=str(tmp_path / "openems_run")))
    # 无真实 openEMS 安装的环境也要能 build——直接置 exe 为占位路径
    s._exe_path = str(tmp_path / "openEMS.exe")
    (tmp_path / "openEMS.exe").write_text("", encoding="utf-8")
    assert s.connect()
    return s


class TestOpenEMSChokepoint:
    def test_csv_branch_writes_sidecar(self, tmp_path: Path) -> None:
        """CSV 降兼容分支（全部 oe_templates 共用 _parse_output）：sidecar 在+哈希对。"""
        s = _connected_solver(tmp_path)
        assert s.build_geometry({"template": "wilkinson", "params": {}})
        _write_synth_csv(tmp_path / "openems_run")
        result = s._parse_output()
        assert result.success
        _assert_sidecar(tmp_path / "openems_run" / "sparams.csv",
                        kind="sparams_csv", run_id="openems_run")

    def test_touchstone_main_path_writes_sidecar(self, tmp_path: Path) -> None:
        """#208 Touchstone 主路（.s4p 等）：sidecar kind=touchstone。"""
        import skrf

        s = _connected_solver(tmp_path)
        assert s.build_geometry({"template": "ratrace", "params": {}})
        run_dir = tmp_path / "openems_run"
        freq = skrf.Frequency(2.0, 3.0, 5, unit="Hz")
        rng = np.random.default_rng(42)
        net = skrf.Network(
            frequency=freq,
            s=(rng.normal(size=(5, 4, 4)) + 1j * rng.normal(size=(5, 4, 4))) * 0.1,
            z0=50.0)
        net.write_touchstone(str(run_dir / "ratrace.s4p"))
        result = s._parse_output()
        assert result.success
        _assert_sidecar(run_dir / "ratrace.s4p",
                        kind="touchstone", run_id="openems_run")

    def test_sidecar_failure_does_not_block_parse(self, tmp_path: Path,
                                                  monkeypatch) -> None:
        """best-effort（#105）：sidecar 写入失败只静默，解析主路照常成功。"""
        s = _connected_solver(tmp_path)
        assert s.build_geometry({"template": "wilkinson", "params": {}})
        _write_synth_csv(tmp_path / "openems_run")

        import rfauto.service.runs_verify_service as rvs

        def _boom(*a: Any, **kw: Any) -> dict[str, Any]:
            raise OSError(13, "模拟文件锁占位")

        monkeypatch.setattr(rvs, "write_artifact_sidecar", _boom)
        result = s._parse_output()
        assert result.success, result.message
        assert not (tmp_path / "openems_run" / "sparams.csv.meta.json").exists()


# ── openems_rotation（每轮 CSV + 断点复用补写）───────────────────────────────

FREQ_HZ = (1e9, 2e9)


def _write_round_csv(work_k: Path, k: int,
                     freq_hz: tuple[float, ...] = FREQ_HZ,
                     n_cols: int = 4) -> None:
    header = "freq_hz" + "".join(f",re_S{c + 1}1,im_S{c + 1}1"
                                 for c in range(n_cols))
    rows = [header]
    for m, f in enumerate(freq_hz):
        vals: list[float] = [f]
        for c in range(n_cols):
            vals += [k * 10 + c + m / 10.0, float(k)]
        rows.append(",".join(repr(v) for v in vals))
    (work_k / "sparams.csv").write_text("\n".join(rows) + "\n",
                                        encoding="utf-8")


def _make_fake_run(calls: list[int]):
    def fake_run(cmd, capture_output, text, timeout, cwd):
        work_k = Path(cwd)
        k = int(work_k.name[1:])
        calls.append(k)
        _write_round_csv(work_k, k)
        return types.SimpleNamespace(returncode=0, stderr="")

    return fake_run


@pytest.fixture()
def fake_render(monkeypatch):
    def _render(template, params, freq_range_ghz, mesh_resolution_mm=0.0,
                excite_port=1):
        return f"SCRIPT-{template}-{excite_port}"

    monkeypatch.setattr("rfauto.adapters.openems_templates.render_script",
                        _render)


class TestRotationSidecars:
    def test_every_round_csv_gets_sidecar(self, tmp_path: Path,
                                          monkeypatch) -> None:
        calls: list[int] = []
        monkeypatch.setattr("rfauto.adapters.openems_rotation.subprocess.run",
                            _make_fake_run(calls))
        result = solve_smatrix_openems(
            tmp_path, template="ratrace", params={},
            freq_range_ghz=(1.0, 2.0), n_ports=4, cache=False)
        assert result["ok"] is True, result.get("errors")
        assert calls == [1, 2, 3, 4]
        for k in range(1, 5):
            _assert_sidecar(tmp_path / f"p{k}" / "sparams.csv",
                            kind="sparams_csv", run_id=tmp_path.name)

    def test_resume_backfills_sidecars(self, tmp_path: Path,
                                       monkeypatch, fake_render) -> None:
        """断点复用轮幂等补写：老产物（无 sidecar 代际）重入即补齐归属证据。"""
        calls: list[int] = []
        monkeypatch.setattr("rfauto.adapters.openems_rotation.subprocess.run",
                            _make_fake_run(calls))
        result = solve_smatrix_openems(
            tmp_path, template="ratrace", params={},
            freq_range_ghz=(1.0, 2.0), n_ports=2, cache=False)
        assert result["ok"] is True
        # 模拟历史产物：p1 的 sidecar 缺失（B4 前代际），CSV 在场
        (tmp_path / "p1" / "sparams.csv.meta.json").unlink()
        result2 = solve_smatrix_openems(
            tmp_path, template="ratrace", params={},
            freq_range_ghz=(1.0, 2.0), n_ports=2, cache=False)
        assert result2["ok"] is True
        assert result2["resumed_rounds"] == [1, 2]  # p1 确实走的是断点复用
        assert calls == [1, 2]  # 两轮均未重跑
        _assert_sidecar(tmp_path / "p1" / "sparams.csv",
                        kind="sparams_csv", run_id=tmp_path.name)


# ── mmt（.s2p 特例链：CSV + Touchstone 双产物）───────────────────────────────


class TestMmtSidecars:
    def test_csv_and_s2p_both_get_sidecars(self, tmp_path: Path) -> None:
        """确定性 WR-90 直段求解 → sparams.csv 与 mmt.s2p 双 sidecar（哈希对）。"""
        cfg = EMSolverConfig(solver_type=EMSolverType.MMT,
                             working_dir=str(tmp_path / "mmt_work"))
        adapter = get_global_registry().create(EMSolverType.MMT, cfg)
        straight = {"sections": [{"type": "uniform", "a_mm": 22.86,
                                  "b_mm": 10.16, "length_mm": 20.0}],
                    "freqs_ghz": [10.0, 10.5, 11.0]}
        assert adapter.build_geometry(straight) is True
        result = adapter.solve()
        assert result.success, result.message
        wd = tmp_path / "mmt_work"
        _assert_sidecar(wd / "sparams.csv",
                        kind="sparams_csv", run_id="mmt_work")
        _assert_sidecar(wd / "mmt.s2p", kind="touchstone", run_id="mmt_work")


# ── CSV 链：qucsator / comsol / ngsolve / pssfss（合成产物直落）──────────────


class TestCsvChainSidecars:
    @staticmethod
    def _synth_s(n: int = 2) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        freq_hz = np.array([2e9, 3e9])[:n]
        s = np.zeros((n, 2, 2), dtype=complex)
        s[:, 1, 0] = 0.7
        beta = np.full(n, 45.0)
        return freq_hz, s, beta

    def test_qucsator_products_get_sidecars(self, tmp_path: Path) -> None:
        """qucsator 链（qucsator_sparams.csv + qucsator_mline.s2p）。"""
        from rfauto.adapters.qucsator_adapter import QucsatorAdapter

        adapter = QucsatorAdapter(EMSolverConfig(
            solver_type=EMSolverType.QUCSATOR,
            working_dir=str(tmp_path / "q_work")))
        freq_hz, s, beta = self._synth_s()
        (tmp_path / "q_work").mkdir(parents=True)  # 真实流程 build_geometry 建目录
        adapter._write_products(tmp_path / "q_work", freq_hz, s, beta)
        _assert_sidecar(tmp_path / "q_work" / "qucsator_sparams.csv",
                        kind="sparams_csv", run_id="q_work")
        _assert_sidecar(tmp_path / "q_work" / "qucsator_mline.s2p",
                        kind="touchstone", run_id="q_work")

    def test_comsol_write_csv_gets_sidecar(self, tmp_path: Path) -> None:
        from rfauto.adapters.comsol_adapter import ComsolAdapter

        adapter = ComsolAdapter(EMSolverConfig(
            solver_type=EMSolverType.COMSOL,
            working_dir=str(tmp_path / "work")))
        freq, s, _ = self._synth_s()
        adapter._write_csv(freq, s)
        _assert_sidecar(tmp_path / "work" / "sparams.csv",
                        kind="sparams_csv", run_id="work")

    def test_ngsolve_write_csv_gets_sidecar(self, tmp_path: Path) -> None:
        from rfauto.adapters.ngsolve_adapter import NGSolveAdapter

        adapter = NGSolveAdapter(EMSolverConfig(
            solver_type=EMSolverType.NGSOLVE,
            working_dir=str(tmp_path / "work")))
        freq, s, _ = self._synth_s()
        adapter._write_csv(freq, s)
        _assert_sidecar(tmp_path / "work" / "sparams.csv",
                        kind="sparams_csv", run_id="work")

    def test_pssfss_products_get_sidecars(self, tmp_path: Path) -> None:
        from rfauto.adapters.pssfss_adapter import PssfssAdapter

        adapter = PssfssAdapter(EMSolverConfig(
            solver_type=EMSolverType.PSSFSS,
            working_dir=str(tmp_path / "work")))
        freq_hz, s, _ = self._synth_s()
        adapter._s_full = s
        adapter._network = None  # TS 缺席形态：CSV sidecar 照写
        adapter._write_products(tmp_path / "work",
                                {"freqs_ghz": (freq_hz / 1e9).tolist()}, 0.1)
        _assert_sidecar(tmp_path / "work" / "sparams.csv",
                        kind="sparams_csv", run_id="work")
        assert not (tmp_path / "work" / "pssfss.s2p.meta.json").exists()


# ── 消费面：runs verify 的 curves_csv 段 ─────────────────────────────────────


def _make_csv_run(tmp_path: Path, name: str = "run_b4") -> Path:
    """含 sparams.csv 曲线的最小合成 run（openEMS 5 列 schema）。"""
    run = tmp_path / name
    run.mkdir(parents=True)
    (run / "meta.json").write_text(json.dumps({
        "run_id": name, "adapter": "openems", "model": "wilkinson",
        "status": "done", "template": "wilkinson",
    }), encoding="utf-8")
    _write_synth_csv(run)
    return run


class TestVerifyCurvesCsvSection:
    def test_manifest_records_curves_csv(self, tmp_path: Path) -> None:
        """存在才记：sparams.csv 入 curves_csv 段（sha256 对）；缺席不记。"""
        run = _make_csv_run(tmp_path)
        manifest = manifest_for_run(run)
        assert manifest["curves_csv"]["sparams.csv"]["sha256"] == \
            hashlib.sha256((run / "sparams.csv").read_bytes()).hexdigest()
        assert manifest["curves_csv_count"] == 1
        # 不存在不记不报（Touchstone 专属 run 的 curves_csv 段为空）
        (run / "sparams.csv").unlink()
        assert manifest_for_run(run)["curves_csv"] == {}

    def test_curves_csv_fresh_with_sidecar(self, tmp_path: Path) -> None:
        run = _make_csv_run(tmp_path)
        write_artifact_sidecar(run / "sparams.csv", run_id=run.name,
                               kind="sparams_csv")
        write_manifest(run)
        result = verify_run(run)
        assert result["ok"] is True
        assert result["status"] == "fresh"
        assert result["issues"] == []

    def test_curves_csv_replaced_is_stale(self, tmp_path: Path) -> None:
        """用户病灶形态推广：旧 sparams.csv 顶替新 run 目录的 → 必须红。"""
        run = _make_csv_run(tmp_path)
        write_artifact_sidecar(run / "sparams.csv", run_id=run.name,
                               kind="sparams_csv")
        write_manifest(run)
        (run / "sparams.csv").write_text(
            "freq_hz,re_S11,im_S11,re_S21,im_S21\n2e9,0.9,0.0,0.0,0.0\n",
            encoding="utf-8")
        result = verify_run(run)
        assert result["ok"] is False
        assert result["status"] == "stale"
        kinds = {issue["kind"] for issue in result["issues"]}
        assert "stale_replaced" in kinds
        # sidecar 跟文件走且未同步改写 → 文件级错配证据同时在场
        assert "sidecar_mismatch" in kinds
        assert any(issue["path"] == "sparams.csv" for issue in result["issues"])

    def test_curves_csv_missing_is_stale(self, tmp_path: Path) -> None:
        """漏拷形态：manifest 记录的曲线 CSV 不在盘上 → missing（stale 级）。"""
        run = _make_csv_run(tmp_path)
        write_manifest(run)
        (run / "sparams.csv").unlink()
        result = verify_run(run)
        assert result["ok"] is False
        assert result["status"] == "stale"
        assert any(issue["kind"] == "missing" and issue["path"] == "sparams.csv"
                   for issue in result["issues"])

    def test_old_manifest_without_curves_csv_section_skips(
            self, tmp_path: Path) -> None:
        """老 manifest 兼容：缺 curves_csv 段 → 跳过不报，仍 fresh。"""
        run = _make_csv_run(tmp_path)
        write_manifest(run)
        manifest = json.loads(
            (run / MANIFEST_FILENAME).read_text(encoding="utf-8"))
        manifest.pop("curves_csv", None)
        (run / MANIFEST_FILENAME).write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        result = verify_run(run)
        assert result["ok"] is True
        assert result["status"] == "fresh"

    def test_qucsator_prefix_csv_also_recorded(self, tmp_path: Path) -> None:
        """前缀变体（qucsator_sparams.csv）同入曲线段。"""
        run = tmp_path / "run_q"
        run.mkdir()
        (run / "qucsator_sparams.csv").write_text(
            "freq_hz,re_S11,im_S11,re_S21,im_S21\n2e9,0,0,0.7,0\n",
            encoding="utf-8")
        (run / "port_beta.csv").write_text(
            "freq_hz,beta_rad_per_m\n2e9,45.0\n", encoding="utf-8")
        manifest = manifest_for_run(run)
        assert "qucsator_sparams.csv" in manifest["curves_csv"]
        # port_beta.csv 不在曲线段口径（B4 范围=sparams.csv 形态）
        assert "port_beta.csv" not in manifest["curves_csv"]
        assert manifest["curves_csv_count"] == 1


# ── 泛化 API 本体（薄壳兼容）────────────────────────────────────────────────


class TestWriteArtifactSidecar:
    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            write_artifact_sidecar(tmp_path / "ghost.csv", run_id="x")

    def test_touchstone_shell_backward_compatible(self, tmp_path: Path) -> None:
        """K4 薄壳兼容：write_touchstone_sidecar 签名/键面不变 + kind 标注。"""
        from rfauto.service.runs_verify_service import write_touchstone_sidecar

        run = _make_csv_run(tmp_path)
        snp = run / "params.s1p"
        snp.write_text("# Hz S RI R 50\n1e9 0.1 0.0\n", encoding="utf-8")
        result = write_touchstone_sidecar(
            snp, run_id=run.name, design_name="RFADesign", setup="Setup1")
        assert result["ok"] is True
        sidecar = json.loads(
            (run / "params.s1p.meta.json").read_text(encoding="utf-8"))
        assert sidecar["sha256"] == hashlib.sha256(snp.read_bytes()).hexdigest()
        assert sidecar["design_name"] == "RFADesign"
        assert sidecar["setup"] == "Setup1"
        assert sidecar["kind"] == "touchstone"
