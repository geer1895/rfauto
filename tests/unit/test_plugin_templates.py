"""DP-17 O1 单测——插件三件套：cookiecutter 模板渲染→注册→dry-run。

判据（runs/df6_dp17/criteria.md §O1）：
- 两模板（solver_adapter/template_family）渲染产物 compile 通过；
- 适配器包 import 即注册（字符串类型键）+ check_adapter_contract 通过
  + EMSolverConfig dry-run（connect/build/solve/get_sparams/close）跑通；
- 模板族包 import 后满足 models.registry 注册契约（name/params_model/
  build 钩子）；
- 注册表快照 finally 还原（#362：reload/注册污染不外溢）。

cookiecutter 不在本 venv（#222 实测）——用最小 {{ cookiecutter.x }}
占位符渲染器替代（同名文件/目录占位一并替换），真实 cookiecutter 行为
由 README 快速开始节人工路径覆盖。
"""

from __future__ import annotations

import compileall
import importlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from rfauto.adapters.em_solver_base import (
    EMSolverConfig,
    get_global_registry,
)
from rfauto.service.adapter_kit import check_adapter_contract

_TOOLS = Path(__file__).resolve().parents[2] / "tools" / "plugin_templates"


def _render_text(text: str, ctx: dict[str, str]) -> str:
    for key, value in ctx.items():
        for form in (f"{{{{ cookiecutter.{key} }}}}",
                     f"{{{{cookiecutter.{key}}}}}"):
            text = text.replace(form, str(value))
    return text


def render_template(template_dir: Path, out_dir: Path,
                    overrides: dict[str, str] | None = None) -> Path:
    """最小 cookiecutter 渲染（占位符替换；cookiecutter.json 交叉引用
    用有界迭代收敛）。"""
    ctx: dict[str, str] = {}
    raw = json.loads((template_dir / "cookiecutter.json").read_text(
        encoding="utf-8"))
    ctx.update({k: str(v) for k, v in raw.items()})
    if overrides:
        ctx.update(overrides)
    for _ in range(4):  # 交叉引用（project_slug 引 adapter_name 等）
        changed = False
        for key, value in list(ctx.items()):
            if "{{" in value:
                new = _render_text(value, ctx)
                if new != value:
                    ctx[key] = new
                    changed = True
        if not changed:
            break
    assert not any("{{" in v for v in ctx.values()), "上下文未收敛"

    dest_root = out_dir / _render_text("{{cookiecutter.project_slug}}", ctx)
    for path in sorted(template_dir.rglob("*")):
        rel = path.relative_to(template_dir)
        if rel.parts[0] == "cookiecutter.json":
            continue
        rel_rendered = _render_text(str(rel).replace("\\", "/"), ctx)
        dest = out_dir / rel_rendered
        if path.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(
                _render_text(path.read_text(encoding="utf-8"), ctx),
                encoding="utf-8")
    return dest_root


@pytest.fixture
def registry_snapshot():
    """适配器+模型注册表快照/还原（#362：测试污染不外溢）。"""
    from rfauto.adapters import em_solver_base
    from rfauto.models import registry as models_registry

    snap = {
        "adapters": dict(em_solver_base.get_global_registry()._solvers),
        "adapters_flag": em_solver_base._adapter_plugins_loaded,
        "models": dict(models_registry._registry),
        "models_flag": models_registry._plugins_loaded,
    }
    yield snap
    em_solver_base.get_global_registry()._solvers = snap["adapters"]
    em_solver_base._adapter_plugins_loaded = snap["adapters_flag"]
    models_registry._registry = snap["models"]
    models_registry._plugins_loaded = snap["models_flag"]


class TestSolverAdapterTemplate:
    def test_render_compile_register_dry_run(self, tmp_path,
                                             registry_snapshot):
        pkg_root = render_template(_TOOLS / "solver_adapter", tmp_path)
        # 渲染产物无残留占位符
        for f in pkg_root.rglob("*"):
            if f.is_file():
                assert "{{" not in f.read_text(encoding="utf-8")
        # compile 全树
        assert compileall.compile_dir(str(pkg_root), quiet=1)

        # import 即注册（字符串类型键）
        sys.path.insert(0, str(pkg_root))
        try:
            importlib.import_module("rfauto_my_solver")
            reg = get_global_registry()
            assert reg.is_registered("my_solver")
            cls = reg.lookup("my_solver")
            contract = check_adapter_contract(cls)
            assert contract["ok"] is True, contract["missing"]

            # fake 通道最小 dry-run（确定性合成谱）
            ad = reg.create("my_solver", EMSolverConfig(
                solver_type="my_solver", freq_range_ghz=(1.0, 5.0)))
            assert ad.connect() is True
            assert ad.build_geometry({"w_mm": 3.0}) is True
            result = ad.solve()
            assert result.success is True
            freq, sparams = ad.get_sparams()
            assert freq.shape == (201,)
            assert sparams.shape == (201, 1, 1)
            assert abs(sparams[0, 0, 0]) == pytest.approx(0.1)
            ad.close()
            # param_semantics 声明面在场（#154）
            assert hasattr(cls, "param_semantics")
        finally:
            sys.path.remove(str(pkg_root))
            sys.modules.pop("rfauto_my_solver", None)

    def test_entry_point_declared_in_pyproject(self, tmp_path):
        pkg_root = render_template(_TOOLS / "solver_adapter", tmp_path)
        pyproject = (pkg_root / "pyproject.toml").read_text(encoding="utf-8")
        assert '[project.entry-points."rfauto.adapters"]' in pyproject
        assert 'my_solver = "rfauto_my_solver:MySolverAdapter"' in pyproject


class TestTemplateFamilyTemplate:
    def test_render_compile_and_model_contract(self, tmp_path,
                                               registry_snapshot):
        pkg_root = render_template(_TOOLS / "template_family", tmp_path)
        assert compileall.compile_dir(str(pkg_root), quiet=1)

        sys.path.insert(0, str(pkg_root))
        try:
            plugin_mod = importlib.import_module("rfauto_my_model.plugin")
            from rfauto.models import registry as models_registry

            plugin_cls = plugin_mod.MyModelPlugin
            assert plugin_cls.name == "my_model"
            params = plugin_cls.params_model(w_mm=2.0, line_len_mm=30.0)
            assert params.er == pytest.approx(4.4)  # schema 缺省生效
            # 注册契约（pip 装后经 rfauto.models entry-point 类形式注册；
            # 测试内等价手动注册验证契约）
            models_registry.register(plugin_cls)
            assert models_registry.get("my_model") is plugin_cls

            # build 钩子：参数归一 + 设计变量登记（stub 适配器）
            class _StubAd:
                def __init__(self):
                    self.vars: dict = {}

                def set_variables(self, mapping):
                    self.vars.update(mapping)

            stub = _StubAd()
            plugin_cls().build(stub, {"w_mm": 2.0, "line_len_mm": 30.0})
            assert stub.vars == {"w": 2.0, "line_len": 30.0}
        finally:
            sys.path.remove(str(pkg_root))
            for name in ("rfauto_my_model", "rfauto_my_model.plugin",
                         "rfauto_my_model.schema"):
                sys.modules.pop(name, None)

    def test_entry_point_declared_in_pyproject(self, tmp_path):
        pkg_root = render_template(_TOOLS / "template_family", tmp_path)
        pyproject = (pkg_root / "pyproject.toml").read_text(encoding="utf-8")
        assert '[project.entry-points."rfauto.models"]' in pyproject
        assert "my_model = \"rfauto_my_model.plugin:MyModelPlugin\"" \
            in pyproject


class TestTemplateDocs:
    @pytest.mark.parametrize("tpl", ["solver_adapter", "template_family"])
    def test_readmes_carry_pit_warnings(self, tmp_path, tpl):
        pkg_root = render_template(_TOOLS / tpl, tmp_path / tpl)
        readme = (pkg_root / "README.md").read_text(encoding="utf-8")
        assert "#362" in readme, f"{tpl} README 缺 #362 重装警告"
        assert "#154" in readme, f"{tpl} README 缺 param_semantics 声明"
        assert "#304" in readme, f"{tpl} README 缺消费者清单"


class TestMetricBenchmarkTemplate:
    """cookiecutter 第三件：metric/benchmark 插件（B3 批，月计划 H 流）。

    判据：渲染产物 compile 通过；任务集过 load_bench_set 结构校验；
    provider 回放 → run_agentbench_regression 自洽正控（两轴满分、门绿）；
    metrics 指标提取确定性（同输入同输出+边界拒收）；无 entry-point 组
    （基准面无发现口——诚实口径，README 明示）。
    """

    def test_render_compile_load_score(self, tmp_path):
        pkg_root = render_template(_TOOLS / "metric_benchmark", tmp_path)
        for f in pkg_root.rglob("*"):
            if f.is_file():
                assert "{{" not in f.read_text(encoding="utf-8")
        assert compileall.compile_dir(str(pkg_root), quiet=1)

        set_path = (pkg_root / "bench_sets" / "my_bench_public.yaml")
        assert set_path.is_file()
        from rfauto.service.agent_bench import (
            evaluate_agentbench,
            load_bench_set,
            run_agentbench_regression,
        )

        bench = load_bench_set(set_path)
        assert bench["ok"], bench.get("errors")

        sys.path.insert(0, str(pkg_root))
        try:
            mod = importlib.import_module("rfauto_my_bench")
            # provider 回放 → 回归门自洽正控
            report = run_agentbench_regression(
                trajectory_provider=mod.provider.reference_provider,
                public_path=set_path)
            assert report["ok"], report.get("reasons")

            # evaluate_agentbench 同 records 打分：两轴满分（回放=期望）
            from rfauto.service.agent_bench import goldset_expected_tools

            records = [mod.provider.reference_provider(t)
                       | {"id": t["id"]}
                       for t in bench["tasks"]]
            result = evaluate_agentbench(records, public_path=set_path)
            assert result["ok"] and result["unknown_ids"] == []
            assert result["combined"]["abstraction"] == pytest.approx(1.0)
            assert result["combined"]["execution"] == pytest.approx(1.0)
            # 任务 id 前缀防撞主仓公开集
            ids = {t["id"] for t in bench["tasks"]}
            assert all(i.startswith("my_bench") for i in ids)
            assert goldset_expected_tools(bench), "任务集应声明期望工具面"

            # metrics：确定性（同输入同输出）+ 边界拒收
            f = [1e9, 2e9, 2.4e9, 3e9]
            s11 = [-2.0, -8.0, -20.0, -5.0]
            assert mod.metrics.resonance_freq_ghz(f, s11) \
                == pytest.approx(2.4)
            assert mod.metrics.resonance_freq_ghz(f, s11) \
                == mod.metrics.resonance_freq_ghz(f, s11)
            assert mod.metrics.s21_at_ghz_db(f, [-1, -2, -3, -4], 2.2) \
                == pytest.approx(-2.5)
            with pytest.raises(ValueError):
                mod.metrics.resonance_freq_ghz([1.0], [-1.0])  # 点数不足
            with pytest.raises(ValueError):
                mod.metrics.resonance_freq_ghz(f, [True, -8, -20, -5])
        finally:
            sys.path.remove(str(pkg_root))
            for name in ("rfauto_my_bench", "rfauto_my_bench.metrics",
                         "rfauto_my_bench.provider"):
                sys.modules.pop(name, None)

    def test_no_entry_point_group_declared(self, tmp_path):
        pkg_root = render_template(_TOOLS / "metric_benchmark", tmp_path)
        pyproject = (pkg_root / "pyproject.toml").read_text(encoding="utf-8")
        assert "entry-points" not in pyproject, \
            "基准面当前无发现口——任务书/README 诚实口径，不得造假接线"

    def test_readme_documents_explicit_consumption(self, tmp_path):
        pkg_root = render_template(_TOOLS / "metric_benchmark", tmp_path)
        readme = (pkg_root / "README.md").read_text(encoding="utf-8")
        assert "load_bench_set" in readme
        assert "run_agentbench_regression" in readme
        assert "铁律 7" in readme  # 数值纪律声明


class TestRenderModule:
    """tools/plugin_templates/render.py（docs/plugins.md 引用的内置渲染器）。

    与本文件内嵌 _render_text 同语义——同模板同参数渲染产物逐字节一致。
    """

    def _load_module(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "b3_plugin_templates_render", _TOOLS / "render.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_render_matches_embedded_renderer(self, tmp_path):
        mod = self._load_module()
        got = mod.render_template(_TOOLS / "template_family",
                                  tmp_path / "via_module")
        want = render_template(_TOOLS / "template_family",
                               tmp_path / "via_embedded")
        got_files = {p.relative_to(got): p.read_bytes()
                     for p in got.rglob("*") if p.is_file()}
        want_files = {p.relative_to(want): p.read_bytes()
                      for p in want.rglob("*") if p.is_file()}
        assert got_files.keys() == want_files.keys()
        assert got_files == want_files

    def test_cli_list_and_unknown_rc(self):

        mod = self._load_module()
        assert mod.main(["--list"]) == 0
        assert mod.main(["not_a_template"]) == 2

    def test_cli_set_override(self, tmp_path):
        import io
        from contextlib import redirect_stdout

        mod = self._load_module()
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = mod.main(["metric_benchmark", "--out", str(tmp_path),
                           "--set", "bench_name=demo_bench"])
        assert rc == 0
        assert (tmp_path / "rfauto-demo_bench-bench" / "bench_sets" /
                "demo_bench_public.yaml").is_file()
