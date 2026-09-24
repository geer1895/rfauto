"""conftest CSXCAD skip 清单钉（round5 E-HIGH-2，e80d12a 防回退）。

tests/conftest.py 的 ``_CSXCAD_TEST_MODULES`` 是"渲染 exec 内嵌
``from CSXCAD import``"测试文件的唯一 skip 通道：漏登记的文件在干净环境
（无 CSXCAD wheel 的公开仓 CI）ModuleNotFoundError **红而非 skip**
（2026-09-22 test_siw_template.py 实测复发，同 f47f5e0 公开仓先例）。
本钉断言清单含全部已知 exec-CSXCAD 文件——新增此类测试文件必须同步登记。
"""

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

#: 已知在测试体内 exec 渲染脚本（内嵌 from CSXCAD import）的文件全集——
#: 任一从 _CSXCAD_TEST_MODULES 消失即本钉红（防回退）。成员表=内部 17 条与
#: 公开仓 release/rfauto_public/tests/conftest.py 实测 28 条的并集（29 条；
#: 公开仓成员生成依据=公开仓独立环境全量门的 ModuleNotFoundError: CSXCAD
#: 失败集圈定，round6 E-M1 差集实测 12 条 public-only 本机全部在盘）。
_EXEC_CSXCAD_MODULES = (
    "test_antenna2_templates.py",
    "test_array_templates.py",
    "test_combline_template.py",
    "test_coupled_bpf_template.py",
    "test_coupler2_templates.py",
    "test_cps_template.py",
    "test_gysel_miter_ab.py",
    "test_gysel_template.py",
    "test_hairpin_alt_template.py",
    "test_hairpin_template.py",
    "test_interdigital_template.py",
    "test_kicad_board_render.py",
    "test_marchand_via_ab.py",
    "test_msl_cpw_template.py",
    "test_openems_real_bundle_offline.py",
    "test_openems_slotline_port.py",
    "test_openems_templates_bridge.py",
    "test_pcell_dsl.py",
    "test_proposal_chain.py",
    "test_ratrace_cylindrical.py",
    "test_ratrace_template.py",
    "test_sir_bpf_template.py",
    "test_siw_template.py",
    "test_sma_launcher_template.py",
    "test_solid_import.py",
    "test_slotline_template.py",
    "test_stepped_coupled_line_specs.py",
    "test_suspended_stripline_template.py",
    "test_template_geometry_audit.py",
)


def test_exec_member_table_is_complete_union():
    """成员表本身必须等于内部∩公开仓实测并集（29 条）——表残缺即守卫
    面缩水（round6 E-M1 实证：表只有 1 条时 12 条漏登记抓不住）。"""
    public = REPO / "release" / "rfauto_public" / "tests" / "conftest.py"
    if not public.exists():
        return  # 公开仓快照不在盘（裁剪环境）时跳过对拍，表内断言仍生效
    import re
    text = public.read_text(encoding="utf-8")
    m = re.search(r"_CSXCAD_TEST_MODULES = frozenset\(\{(.*?)\}\)", text, re.S)
    assert m is not None
    public_members = set(re.findall(r'"(test_[^"]+\.py)"', m.group(1)))
    assert public_members <= set(_EXEC_CSXCAD_MODULES), (
        f"公开仓实测 exec 成员未列全: {sorted(public_members - set(_EXEC_CSXCAD_MODULES))}"
    )


def _conftest_csxcad_modules() -> frozenset[str]:
    spec = importlib.util.spec_from_file_location(
        "_rfauto_conftest_under_test", REPO / "tests" / "conftest.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._CSXCAD_TEST_MODULES


def test_exec_csxcad_modules_registered_in_skip_list():
    registered = _conftest_csxcad_modules()
    for name in _EXEC_CSXCAD_MODULES:
        assert name in registered, (
            f"{name} 渲染 exec 内嵌 from CSXCAD import，必须登记进 "
            "tests/conftest.py _CSXCAD_TEST_MODULES（干净环境否则红而非 "
            "skip，e80d12a）")


def test_skip_list_entries_exist_on_disk():
    """清单条目必须是 tests/ 下真实存在的文件（防改名后残留死条目）。"""
    registered = _conftest_csxcad_modules()
    on_disk = {p.name for p in (REPO / "tests").rglob("test_*.py")}
    missing = sorted(registered - on_disk)
    assert not missing, f"清单条目在 tests/ 下不存在: {missing}"
