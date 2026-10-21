"""new_calc_key 脚手架生成器测试（R1 T6 配套 DX，架构批 W8-S3）。

覆盖：骨架可编译且形态正确（register_calculator 装饰器/required 元组
尾逗号/experimental 口径/无参数形态）、五步清单完整性与口径分派
（EXPECTED vs EXPERIMENTAL_EXPECTED）、校验拒绝路径（非法标识符/
required 引用未声明参数/--out 拒绝覆盖与越界落盘）、落盘成功路径
（monkeypatch CALC_FAMILIES_DIR 到 tmp，不污染 src/）。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "scripts" / "new_calc_key.py"

_SPEC = importlib.util.spec_from_file_location("new_calc_key_mod", _SCRIPT)
new_calc_key = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(new_calc_key)


def _basic_args(key: str = "demo_key", module: str = "demo_family") -> list[str]:
    return [key, "--module", module, "--description", "演示键",
            "--group", "演示分组",
            "--param", "freq_ghz:中心频率GHz",
            "--param", "width_mm:导带宽度mm",
            "--required", "freq_ghz"]


class TestSkeleton:
    def test_skeleton_compiles_and_carries_key(self, capsys):
        rc = new_calc_key.main(_basic_args())
        assert rc == 0
        out = capsys.readouterr().out
        assert out.count('name="demo_key"') == 1
        compile(out.split('════')[0], "<skeleton>", "exec")  # 骨架是合法 Python

    def test_required_tuple_has_trailing_comma(self, capsys):
        """required=("x") 是字符串不是元组——骨架必须尾逗号。"""
        new_calc_key.main(_basic_args())
        out = capsys.readouterr().out
        assert 'required=("freq_ghz",)' in out

    def test_experimental_switches_flag_and_checklist_table(self, capsys):
        new_calc_key.main([*_basic_args(), "--experimental"])
        out = capsys.readouterr().out
        assert "experimental=True," in out
        assert "EXPERIMENTAL_EXPECTED" in out
        assert "→ EXPECTED 集合加" not in out  # 非 experimental 口径文案不出现

    def test_plain_goes_to_expected_table(self, capsys):
        new_calc_key.main(_basic_args())
        out = capsys.readouterr().out
        assert "→ EXPECTED 集合加" in out
        assert "experimental=True," not in out

    def test_no_params_uses_kwargs_form(self, capsys):
        new_calc_key.main(["bare_key", "--module", "bare",
                           "--description", "无参键"])
        out = capsys.readouterr().out
        assert "def bare_key(**_kwargs: float) -> dict[str, Any]:" in out

    def test_skeleton_carries_provenance_discipline(self, capsys):
        """铁律 7/118：骨架必须自带出处纪律注记，不产出物理数字。"""
        new_calc_key.main(_basic_args())
        out = capsys.readouterr().out
        assert "出处" in out
        assert "NotImplementedError" in out


class TestChecklist:
    def test_five_steps_and_gate_files_present(self, capsys):
        new_calc_key.main(_basic_args())
        out = capsys.readouterr().out
        for step in ("第 1 步", "第 2 步", "第 3 步", "第 4 步", "第 5 步"):
            assert step in out
        # 五钉消费者文件全部点名
        for target in ("test_calculators.py", "test_physics_invariants.py",
                       "test_experimental_", "test_model_docs.py",
                       "calc_families/__init__.py", "CALC_GROUP_TABLE"):
            assert target in out
        # 追加尾位口径（注册序=导入序）
        assert "追加尾位" in out

    def test_group_row_emitted(self, capsys):
        new_calc_key.main(_basic_args())
        out = capsys.readouterr().out
        assert '"demo_key": "演示分组",' in out


class TestValidationAndOut:
    def test_bad_key_name_rejected(self):
        with pytest.raises(SystemExit):
            new_calc_key.main(["Bad-Key", "--module", "m",
                               "--description", "x"])

    def test_required_unknown_param_rejected(self):
        with pytest.raises(SystemExit, match="未声明的参数"):
            new_calc_key.main([*_basic_args(), "--required", "ghost_param"])

    def test_param_without_desc_rejected(self):
        with pytest.raises(SystemExit, match="缺描述"):
            new_calc_key.main(["k", "--module", "m", "--description", "x",
                               "--param", "freq_ghz"])

    def test_out_rejects_existing_file(self, tmp_path, monkeypatch):
        target = tmp_path / "demo_family.py"
        target.write_text("x", encoding="utf-8")
        monkeypatch.setattr(new_calc_key, "CALC_FAMILIES_DIR", tmp_path)
        with pytest.raises(SystemExit, match="拒绝覆盖"):
            new_calc_key.main([*_basic_args(), "--out", str(target)])

    def test_out_rejects_outside_calc_families(self, tmp_path, monkeypatch):
        monkeypatch.setattr(new_calc_key, "CALC_FAMILIES_DIR",
                            tmp_path / "calc_families")
        with pytest.raises(SystemExit, match="只允许落"):
            new_calc_key.main([*_basic_args(),
                               "--out", str(tmp_path / "elsewhere.py")])

    def test_out_writes_skeleton_into_calc_families(
            self, tmp_path, monkeypatch, capsys):
        fam = tmp_path / "calc_families"
        fam.mkdir()
        monkeypatch.setattr(new_calc_key, "CALC_FAMILIES_DIR", fam)
        target = fam / "demo_family.py"
        rc = new_calc_key.main([*_basic_args(), "--out", str(target)])
        assert rc == 0
        assert target.exists()
        compile(target.read_text(encoding="utf-8"), "<skeleton>", "exec")

    def test_help_smoke(self):
        """--help 可构建（#305：argparse help 含裸 % 会炸；此处钉住）。"""
        import subprocess
        proc = subprocess.run([sys.executable, str(_SCRIPT), "--help"],
                              capture_output=True, text=True,
                              encoding="utf-8")
        assert proc.returncode == 0
        assert "new_calc_key" in proc.stdout


class TestEmitTemplates:
    """--emit-templates 五钉消费者补丁模板（W15-S3 DX 增强）。"""

    def test_emits_five_template_files_with_anchors(self, tmp_path):
        out_dir = tmp_path / "tpl"
        rc = new_calc_key.main([*_basic_args(),
                                "--emit-templates", str(out_dir)])
        assert rc == 0
        names = sorted(p.name for p in out_dir.iterdir())
        assert names == [
            "01_calc_families_init_import.py.template",
            "02_test_calculators_EXPECTED.py.template",
            "03_test_physics_invariants_inputs.py.template",
            "04_registry_CALC_GROUP_TABLE.py.template",
            "05_template_consumers_and_auto.md.template",
        ]
        blobs = {p.name: p.read_text(encoding="utf-8")
                 for p in out_dir.iterdir()}
        # 每钉都带目标文件锚点与可粘贴代码块
        assert "calc_families/__init__.py" in blobs[
            "01_calc_families_init_import.py.template"]
        assert "from . import demo_family" in blobs[
            "01_calc_families_init_import.py.template"]
        assert "test_calculators.py" in blobs[
            "02_test_calculators_EXPECTED.py.template"]
        assert '"demo_key",' in blobs[
            "02_test_calculators_EXPECTED.py.template"]
        assert "EXPECTED = {" in blobs[
            "02_test_calculators_EXPECTED.py.template"]
        assert "_calculator_inputs" in blobs[
            "03_test_physics_invariants_inputs.py.template"]
        assert '"demo_key": {' in blobs[
            "03_test_physics_invariants_inputs.py.template"]
        assert "CALC_GROUP_TABLE" in blobs[
            "04_registry_CALC_GROUP_TABLE.py.template"]
        assert '"demo_key": "演示分组",' in blobs[
            "04_registry_CALC_GROUP_TABLE.py.template"]
        assert "test_template_meta_consistency" in blobs[
            "05_template_consumers_and_auto.md.template"]
        # 全部钉的自证命令行可辨识
        for blob in blobs.values():
            assert "-m pytest" in blob

    def test_experimental_targets_experimental_table(self, tmp_path):
        out_dir = tmp_path / "tpl"
        new_calc_key.main([*_basic_args(), "--experimental",
                           "--emit-templates", str(out_dir)])
        tpl02 = (out_dir / "02_test_calculators_EXPECTED.py.template"
                 ).read_text(encoding="utf-8")
        assert "EXPERIMENTAL_EXPECTED = {" in tpl02

    def test_no_group_falls_back_to_default_group(self, tmp_path):
        out_dir = tmp_path / "tpl"
        new_calc_key.main(["bare_key", "--module", "bare",
                           "--description", "无组键",
                           "--emit-templates", str(out_dir)])
        tpl04 = (out_dir / "04_registry_CALC_GROUP_TABLE.py.template"
                 ).read_text(encoding="utf-8")
        assert '"bare_key": "其他",' in tpl04

    def test_required_note_present(self, tmp_path):
        out_dir = tmp_path / "tpl"
        new_calc_key.main([*_basic_args(),
                           "--emit-templates", str(out_dir)])
        tpl03 = (out_dir / "03_test_physics_invariants_inputs.py.template"
                 ).read_text(encoding="utf-8")
        assert 'required=("freq_ghz")' in tpl03

    def test_refuses_existing_template_file(self, tmp_path):
        out_dir = tmp_path / "tpl"
        out_dir.mkdir()
        (out_dir / "01_calc_families_init_import.py.template").write_text(
            "x", encoding="utf-8")
        with pytest.raises(SystemExit, match="拒绝覆盖"):
            new_calc_key.main([*_basic_args(),
                               "--emit-templates", str(out_dir)])

    def test_refuses_consumer_tree_dirs(self, tmp_path, monkeypatch):
        monkeypatch.setattr(new_calc_key, "REPO_ROOT", tmp_path)
        (tmp_path / "src").mkdir()
        with pytest.raises(SystemExit, match="消费者树"):
            new_calc_key.main([*_basic_args(),
                               "--emit-templates", str(tmp_path / "src" / "sub")])

    def test_refuses_src_root_itself(self, tmp_path, monkeypatch):
        monkeypatch.setattr(new_calc_key, "REPO_ROOT", tmp_path)
        src = tmp_path / "src"
        src.mkdir()
        with pytest.raises(SystemExit, match="消费者树"):
            new_calc_key.main([*_basic_args(),
                               "--emit-templates", str(src)])
