"""edb_lane_service 状态面定向测试（W5 审查批修复钉，全 fake 零真机）。

钉 edb_status 与导出链产物命名契约对齐的两处修正：
- 批后导出 Touchstone 按文件内容反推端口数后**改名 .sNp**（hfss_batch
  导出链：``_export.s2p`` 只是 2 端口占位——4 端口真机产物实为
  ``*_export.s4p``，内部证据档 五件实证）——
  status 面原只认 ``.s2p`` 恒 miss 真实产物（touchstone 列 None + stem
  不登记）；
- .aedb 工程的日志/导出名带 ``.aedb`` 尾缀（hfss_batch 按**工程名**派生：
  ``ansysedt_batch_x.aedb.log``/``x.aedb_export.s4p``）——按裸 stem 归组
  折叠，不折叠则同工程裂成双行（幽灵 stem 行 ``x.aedb`` 的 config/
  touchstone 查找恒空，n_projects 虚高）。

lange 拒绝信封完备性/五族清单/CLI·MCP 接线钉在 test_edb_cli_mcp.py
（单源不复制）；数据集道 E1 指纹钉在 test_dataset_edb_lane.py。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from rfauto.service import edb_lane_service as lane


def _touch(root: Path, name: str) -> Path:
    p = root / name
    p.write_text("x", encoding="utf-8")
    return p


class TestStatusExportTouchstoneSnp:
    def test_s4p_export_visible(self, tmp_path):
        """4 端口批后导出（.s4p）→ touchstone 列命中且 stem 登记。"""
        (tmp_path / "bl.aedb").mkdir()
        _touch(tmp_path, "bl_export.s4p")
        r = lane.edb_status(tmp_path)
        assert r["ok"] is True
        assert r["n_projects"] == 1
        (row,) = r["items"]
        assert row["stem"] == "bl"
        assert row["touchstone"] == str(tmp_path / "bl_export.s4p")

    def test_s2p_export_still_visible(self, tmp_path):
        """2 端口 .s2p（占位扩展名未改名形态）向后兼容同认。"""
        (tmp_path / "pd.aedb").mkdir()
        _touch(tmp_path, "pd_export.s2p")
        (row,) = lane.edb_status(tmp_path)["items"]
        assert row["touchstone"] == str(tmp_path / "pd_export.s2p")

    def test_multi_extension_deterministic_first(self, tmp_path):
        """同 stem 多扩展名（重导出残留）按名字小写序取首个（确定性）。"""
        _touch(tmp_path, "x_export.s2p")
        _touch(tmp_path, "x_export.s4p")
        (row,) = lane.edb_status(tmp_path)["items"]
        assert row["touchstone"] == str(tmp_path / "x_export.s2p")


class TestStatusAedbStemFolding:
    def test_aedb_log_stem_folded_single_row(self, tmp_path):
        """.aedb 工程名派生日志 → 折叠回裸 stem 单行（无 x.aedb 幽灵行），
        solved/双日志/config 查找全命中。"""
        (tmp_path / "x.aedb").mkdir()
        _touch(tmp_path, "x_config.json")
        _touch(tmp_path, "ansysedt_batch_x.aedb.log")
        _touch(tmp_path, "ansysedt_batch_extract_x.aedb.log")
        r = lane.edb_status(tmp_path)
        assert r["ok"] is True
        assert r["n_projects"] == 1
        (row,) = r["items"]
        assert row["stem"] == "x"
        assert row["aedb"] == str(tmp_path / "x.aedb")
        assert row["config_json"] == str(tmp_path / "x_config.json")
        # 日志查找命中 .aedb 尾缀变体（裸名不存在）
        assert row["solve_log"] == str(
            tmp_path / "ansysedt_batch_x.aedb.log")
        assert row["extract_log"] == str(
            tmp_path / "ansysedt_batch_extract_x.aedb.log")
        assert row["solved"] is True

    def test_aedb_export_alias_visible(self, tmp_path):
        """.aedb 工程的批后导出名（x.aedb_export.s4p）经别名键命中。"""
        (tmp_path / "x.aedb").mkdir()
        _touch(tmp_path, "x.aedb_export.s4p")
        _touch(tmp_path, "ansysedt_batch_x.aedb.log")
        (row,) = lane.edb_status(tmp_path)["items"]
        assert row["stem"] == "x"
        assert row["touchstone"] == str(tmp_path / "x.aedb_export.s4p")
        assert row["solved"] is True

    def test_bare_log_preferred_over_aedb_variant(self, tmp_path):
        """裸名与 .aedb 变体并存（.aedt/.aedb 混合求解）→ 裸名优先。"""
        (tmp_path / "x.aedb").mkdir()
        _touch(tmp_path, "ansysedt_batch_x.log")
        _touch(tmp_path, "ansysedt_batch_x.aedb.log")
        (row,) = lane.edb_status(tmp_path)["items"]
        assert row["solve_log"] == str(tmp_path / "ansysedt_batch_x.log")

    def test_mixed_inventory_no_phantom_rows(self, tmp_path):
        """.aedt 工程（裸 stem 产物）+ .aedb 工程（带尾缀产物）同根互不
        干扰，各自单行。"""
        (tmp_path / "a.aedb").mkdir()
        _touch(tmp_path, "a_export.s4p")
        _touch(tmp_path, "ansysedt_batch_a.log")
        (tmp_path / "b.aedb").mkdir()
        _touch(tmp_path, "b.aedb_export.s3p")
        _touch(tmp_path, "ansysedt_batch_b.aedb.log")
        r = lane.edb_status(tmp_path)
        assert r["n_projects"] == 2
        by_stem = {row["stem"]: row for row in r["items"]}
        assert set(by_stem) == {"a", "b"}
        assert by_stem["a"]["touchstone"] == str(tmp_path / "a_export.s4p")
        assert by_stem["b"]["touchstone"] == str(
            tmp_path / "b.aedb_export.s3p")
        assert by_stem["a"]["solved"] is True
        assert by_stem["b"]["solved"] is True
