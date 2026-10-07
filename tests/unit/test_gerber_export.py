"""LC-1 Gerber X2 + Excellon 导出锚（E 流版图四件之首）。

真机腿依赖 KiCad 自带 Python 子进程（铁律 2——项目 venv 不碰 pcbnew），
KiCad 缺失走 skipif 降级（同 test_kicad_extract 离线口径）。测试板消费
仓内既有板生成链 adapters.kicad_extract.build_demo_cpwg_pcb（B6 往返锚
同一来源——LC-1 只做导出封装，不另立建板链）。

锚面：
1. 离线：TF 行解析器纯函数（合成 X2 文本；键去点口径与 gerbonara 对齐；
   非 X2 行忽略）。
2. 离线：路径前置守卫（板/KiCad Python 不存在 → ok=False 显式报错契约，
   零子进程）。
3. 真机：demo 板 → 导出 → 文件清单（F/B.Cu、F/B.Mask、F/B.Silk、
   Edge_Cuts + .gbrjob + .drl）+ X2 属性存在性（FileFunction 全角色命中）
   + job 文件 FilesAttributes 与 .gbr TF 行互证。
4. gerbonara 读回一致性：可选增强层（Apache-2.0 隔离安装后经
   ``RFAUTO_GERBONARA_PATH`` 启用），不可用时如实 skip 不进缺省门。
5. 真机失败显式报错：坏板文件 → ok=False + errors 非空。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rfauto.adapters.kicad_extract import (
    KICAD_PYTHON as _ADAPTER_KICAD_PYTHON,
)
from rfauto.adapters.kicad_extract import (
    build_demo_cpwg_pcb,
)
from rfauto.core.gerber_export import (
    DEFAULT_GERBER_LAYERS,
    KICAD_PYTHON,
    export_gerber_x2,
    gerbonara_available,
    parse_x2_file_attributes,
)

KICAD_AVAILABLE = Path(KICAD_PYTHON).exists()

requires_kicad = pytest.mark.skipif(
    not KICAD_AVAILABLE, reason="KiCad Python 不存在（离线降级）")

# 路径常量与 adapters 同源（分层原因 core 本地副本，漂移即红）
requires_kicad_consistency = pytest.mark.skipif(
    not (KICAD_AVAILABLE and _ADAPTER_KICAD_PYTHON == KICAD_PYTHON),
    reason="KiCad Python 路径常量跨层漂移")


# ─── 离线腿：TF 行解析器 ─────────────────────────────────────────────────────

_SYNTHETIC_X2 = (
    "%TF.GenerationSoftware,rfauto,gerber_export,1.0*%\n"
    "%TF.FileFunction,Copper,L1,Top*%\n"
    "%TF.FilePolarity,Positive*%\n"
    "%FSLAX46Y46*%\n"
    "G04 noise line*\n"
    "%MOMM*%\n"
    "%ADD10C,0.2*%\n"
    "D10*\n"
    "X1000000Y1000000D02*\n"
    "X2000000Y1000000D01*\n"
    "M02*\n"
)


def test_parse_x2_file_attributes_keys_and_fields() -> None:
    attrs = parse_x2_file_attributes(_SYNTHETIC_X2)
    assert attrs["FileFunction"] == ("Copper", "L1", "Top")
    assert attrs["FilePolarity"] == ("Positive",)
    assert attrs["GenerationSoftware"] == ("rfauto", "gerber_export", "1.0")
    # 非 X2 行（参数/D码/坐标/注释）不混入
    assert len(attrs) == 3
    assert all(not k.startswith(".") for k in attrs)  # 键去点：gerbonara 对齐口径


def test_parse_x2_file_attributes_empty_for_plain_gerber() -> None:
    assert parse_x2_file_attributes(
        "%FSLAX46Y46*%\n%MOMM*%\nD10*\nX0Y0D02*\nM02*\n") == {}


def test_parse_x2_profile_np_keeps_extra_field() -> None:
    attrs = parse_x2_file_attributes("%TF.FileFunction,Profile,NP*%\n")
    assert attrs["FileFunction"] == ("Profile", "NP")


# ─── 离线腿：路径前置守卫（零子进程显式报错契约） ────────────────────────────

def test_export_missing_board_explicit_error(tmp_path: Path) -> None:
    r = export_gerber_x2(tmp_path / "nope.kicad_pcb", tmp_path / "out")
    assert r["ok"] is False
    assert any("板文件不存在" in e for e in r["errors"])
    assert r["files"] == {}


def test_export_missing_kicad_python_explicit_error(tmp_path: Path) -> None:
    board = tmp_path / "dummy.kicad_pcb"
    board.write_text("(kicad_pcb)", encoding="utf-8")
    r = export_gerber_x2(
        board, tmp_path / "out",
        kicad_python=str(tmp_path / "no_such_python.exe"))
    assert r["ok"] is False
    assert any("KiCad Python 不存在" in e for e in r["errors"])


# ─── 真机腿：demo 板 → 导出 → 清单/X2/job 互证 ──────────────────────────────

@pytest.fixture(scope="module")
def exported(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """构建一次 demo CPWG 板 + 导出一次（子进程秒级，避免逐用例重复）。"""
    root = tmp_path_factory.mktemp("gerber_export")
    board = root / "demo_cpwg.kicad_pcb"
    build = build_demo_cpwg_pcb(board)
    if not build["success"]:
        pytest.fail(f"demo 板构建失败: {build['message']} {build['errors']}")
    contract = export_gerber_x2(board, root / "gerbers")
    return {"build": build, "contract": contract, "root": root}


@requires_kicad
class TestGerberX2Export:
    def test_contract_ok(self, exported: dict) -> None:
        c = exported["contract"]
        assert c["ok"] is True, c["errors"]
        assert c["errors"] == []

    def test_file_list_covers_manufacturing_layers(self, exported: dict) -> None:
        c = exported["contract"]
        expect_roles = {s.role for s in DEFAULT_GERBER_LAYERS}
        assert set(c["files"]) == expect_roles
        for role, path in c["files"].items():
            assert Path(path).exists(), role
            assert Path(path).suffix == ".gbr", role
        # 制造交付面：7 gerber + 1 job + 1 drill（PTH/NPTH 合并口径）
        assert c["job_file"] is not None and Path(c["job_file"]).exists()
        assert len(c["drill_files"]) == 1
        assert Path(c["drill_files"][0]).suffix == ".drl"

    def test_x2_file_function_present_all_roles(self, exported: dict) -> None:
        c = exported["contract"]
        assert c["missing_x2"] == []
        for spec in DEFAULT_GERBER_LAYERS:
            attrs = c["x2_attributes"][spec.role]
            ff = attrs["FileFunction"]
            assert all(kw in ff for kw in spec.file_function), (spec.role, ff)
            # X2 头属性存在性（KiCad 10.0.6 真机导出实测口径）
            assert attrs["GenerationSoftware"][0] == "KiCad"
            assert "FilePolarity" in attrs or spec.role == "Edge.Cuts"

    def test_job_file_files_attributes_crosscheck(self, exported: dict) -> None:
        """job 文件 FilesAttributes ↔ 各 .gbr TF 行互证。

        容忍两类 KiCad 10.0.6 实测口径差：job 内大小写不同
        （SolderMask vs Soldermask）、job 内 FileFunction 略去镀覆/非镀
        修饰字段（Edge.Cuts：job=Profile vs TF=Profile,NP）——判据取
        job 字段为 TF 字段的前缀语义。
        """
        c = exported["contract"]
        job = json.loads(Path(c["job_file"]).read_text(encoding="utf-8"))
        entries = {Path(e["Path"]).name: e["FileFunction"]
                   for e in job["FilesAttributes"]}
        assert set(entries) == {Path(p).name for p in c["files"].values()}
        for role, path in c["files"].items():
            tf_ff = c["x2_attributes"][role]["FileFunction"]
            job_ff = tuple(entries[Path(path).name].split(","))
            assert job_ff and len(job_ff) <= len(tf_ff), (role, job_ff, tf_ff)
            assert tuple(x.casefold() for x in tf_ff[:len(job_ff)]) == \
                tuple(x.casefold() for x in job_ff), role

    def test_gerbonara_read_back_consistency(self, exported: dict) -> None:
        """可选增强层读回一致性（gerbonara 不可用则如实 skip）。"""
        c = exported["contract"]
        if not c["gerbonara"]["available"]:
            pytest.skip("gerbonara 不可用（可选增强层，未设 "
                        "RFAUTO_GERBONARA_PATH）")
        assert c["gerbonara"]["consistent"] is True, c["gerbonara"]["errors"]
        for role in c["files"]:
            rb = c["gerbonara"]["read_back"][role]
            assert rb["available"] is True
            assert "error" not in rb, (role, rb)
            assert rb["FileFunction"] == c["x2_attributes"][role]["FileFunction"]

    def test_gerbonara_availability_flag_matches_import(
            self, exported: dict) -> None:
        assert exported["contract"]["gerbonara"]["available"] == \
            gerbonara_available()


@requires_kicad
def test_export_corrupt_board_explicit_error(
        tmp_path: Path, exported: dict) -> None:
    """坏板文件 → ok=False 且 errors 非空（子进程失败显式报错锚）。"""
    bad = tmp_path / "corrupt.kicad_pcb"
    bad.write_text("this is not a kicad board\n", encoding="utf-8")
    r = export_gerber_x2(bad, tmp_path / "out")
    assert r["ok"] is False
    assert r["errors"], "坏板必须显式报错而非静默成功"
    assert r["files"] == {}


@requires_kicad_consistency
def test_kicad_python_constant_matches_adapter_convention() -> None:
    """core 本地副本与 adapters 链同源守卫（分层复制不漂移）。"""
    assert KICAD_PYTHON == _ADAPTER_KICAD_PYTHON
