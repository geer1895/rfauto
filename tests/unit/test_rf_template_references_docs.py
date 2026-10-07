"""rf_template_references.md 三参考节增补钉（B3 批：介质测量/EMC/波导）。

#1c 铁律面：文档串引用的代码路径/测试名必须真实存在；三节内引注的内核导出名抽样实测
（#97：引注与代码同 commit 校验）。
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_DOC = _REPO / "docs" / "rf_template_references.md"


def _doc_text() -> str:
    return _DOC.read_text(encoding="utf-8")


class TestThreeNewSections:
    """§16 介质测量 / §17 EMC / §18 波导三节在场（#146 吞标题防线）。"""

    def test_sections_present(self):
        text = _doc_text()
        for heading in (
            "## 16. 介质测量/材料参数提取（F-A P1，2026-09-28 增补）",
            "## 17. EMC 参考口径（ME-1..3，2026-09-28 增补）",
            "## 18. 波导族参考口径（ME-4..7，2026-09-28 增补）",
        ):
            assert heading in text, f"缺章节标题：{heading}"
        # 既有基线节未被增补破坏（首尾抽两节）
        assert "## 0. 网格/边界/端口面方法学基线" in text
        assert "### 15. c3 耦合/馈耦合标定锚" in text

    def test_section_order_ascending(self):
        nums = [int(m) for m in re.findall(r"^## (\d+)\.", _doc_text(),
                                           flags=re.MULTILINE)]
        assert nums == sorted(nums), f"章节号乱序：{nums}"
        assert nums[-1] == 18


class TestCitedPathsExist:
    """文档引用的仓内代码/测试路径逐条存在（#1c 引源纪律）。"""

    def test_cited_core_modules_exist(self):
        text = _doc_text()
        cited = set(re.findall(r"`?(?:src/rfauto/)?core/([a-z0-9_]+)\.py`?",
                               text))
        assert cited, "文档未引用任何 core 模块（异常）"
        missing = [n for n in sorted(cited)
                   if not (_REPO / "src" / "rfauto" / "core" / f"{n}.py")
                   .is_file()]
        assert not missing, f"文档引用的 core 模块不存在：{missing}"

    def test_cited_service_modules_exist(self):
        text = _doc_text()
        cited = set(re.findall(r"`?(?:src/rfauto/)?service/([a-z0-9_]+)\.py`?",
                               text))
        missing = [n for n in sorted(cited)
                   if not (_REPO / "src" / "rfauto" / "service" / f"{n}.py")
                   .is_file()]
        assert not missing, f"文档引用的 service 模块不存在：{missing}"

    def test_cited_unit_tests_exist(self):
        text = _doc_text()
        cited = set(re.findall(r"`tests/unit/([a-z0-9_]+)\.py`?", text))
        missing = [n for n in sorted(cited)
                   if not (_REPO / "tests" / "unit" / f"{n}.py").is_file()]
        assert not missing, f"文档引用的测试文件不存在：{missing}"


class TestCitedKernelExports:
    """三节引注的内核导出名抽样实测（引注与代码一致，#97）。"""

    def test_dielectric_extract_exports(self):
        from rfauto.core import dielectric_extract as de

        for name in ("extract_gamma_mtrl", "extract_gamma_single_line",
                     "nrw_extract", "baker_jarvis_iter",
                     "ring_resonator_f0_to_er", "gamma_to_er_eff",
                     "er_eff_to_er", "tan_d_from_alpha_d"):
            assert hasattr(de, name), f"dielectric_extract 缺引注导出 {name}"

    def test_emc_exports(self):
        from rfauto.core import emc_radiated, emc_tvs_gate, emi_filter

        assert hasattr(emi_filter, "margin_report")
        assert hasattr(emc_radiated, "radiated_margin")
        assert hasattr(emc_radiated, "fcc_part15b_radiated_limits")
        assert hasattr(emc_radiated, "cispr32_classb_radiated_limits")
        assert emc_tvs_gate.PYPI_EMC2_FAKE_FRIEND  # 假朋友警示常量在场
        assert hasattr(emc_tvs_gate, "IEC61000_4_2_PROVENANCE")
        assert hasattr(emc_tvs_gate, "IEC61000_4_5_PROVENANCE")

    def test_waveguide_exports(self):
        from rfauto.core import horn_synthesis, rw_tables

        assert hasattr(rw_tables, "wr_lookup")
        assert hasattr(horn_synthesis, "synthesize_pyramid_horn")
        # WR-90 表口径（ME-6 名义几何的精算锚）
        rec = rw_tables.wr_lookup("WR-90")
        assert abs(rec.a_mm - 22.86) < 1e-12
        assert abs(rec.b_mm - 10.16) < 1e-12
