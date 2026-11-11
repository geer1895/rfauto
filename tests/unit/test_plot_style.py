"""R11 Top4 论文图风格单源测试（aurora_q Q-W8-4）。

钉四件事：
- 键冻结：STYLE 键集+数值锚显式钉死（改键=显式评审动作）；
- IEEE 出版门：STYLE → publication_standards.check_ieee_rcparams → PASS
  （裁判面独立于被测模块——#118 家法，风格单源必须过仓内既有出版门）；
- contextmanager 零残留：paper_figure_context 进入施加/退出逐键还原
  （含异常路径），apply_paper_style 施加面可观测；
- CJK 豆腐块家族预防：字体栈含 Microsoft YaHei/SimHei 回退 +
  axes.unicode_minus=False（AGENTS 速查·发布批⑩"中文图逐张目检"的
  机制化钉）；
- 消费面冒烟：design_replay pareto 散点走 paper_figure_context 出图
  （Agg 后端+tmp_path，禁真显示；确定性两跑逐字节）+接线存在棘轮。
"""

from __future__ import annotations

import inspect
import json

import pytest

from rfauto.core.plot_style import (
    PAPER_COLORS,
    PAPER_FIGSIZE_DOUBLE,
    PAPER_FIGSIZE_SINGLE,
    STYLE,
    apply_paper_style,
    paper_figure_context,
    style_as_dict,
)

#: STYLE 键集冻结锚（增/删/改名键=改本常量+说明——显式评审动作）。
STYLE_KEYS_FROZEN = frozenset({
    "font.family", "font.sans-serif",
    "font.size", "axes.titlesize", "axes.labelsize",
    "xtick.labelsize", "ytick.labelsize", "legend.fontsize",
    "axes.linewidth", "lines.linewidth", "lines.markersize",
    "grid.linewidth",
    "axes.unicode_minus", "text.usetex",
    "figure.figsize", "figure.facecolor", "figure.dpi",
    "savefig.facecolor", "savefig.edgecolor", "savefig.dpi",
    "axes.prop_cycle",
})


class TestStyleSingleSource:
    def test_style_keys_frozen(self):
        assert frozenset(STYLE) == STYLE_KEYS_FROZEN

    def test_style_values_anchored(self):
        """数值锚（IEEE 地板之上；字体栈与字形守卫逐键）。"""
        assert STYLE["font.size"] == 9.0
        assert STYLE["xtick.labelsize"] == 8.0
        assert STYLE["ytick.labelsize"] == 8.0
        assert STYLE["lines.linewidth"] == 1.0
        assert STYLE["axes.unicode_minus"] is False
        assert STYLE["text.usetex"] is False
        assert STYLE["savefig.dpi"] == 300
        assert STYLE["figure.figsize"] == PAPER_FIGSIZE_SINGLE

    def test_font_stack_has_cjk_fallback(self):
        """CJK 豆腐块家族预防钉：字体栈含 Microsoft YaHei/SimHei 回退，
        首位 DejaVu Sans（跨机确定性 ASCII 面）。"""
        stack = STYLE["font.sans-serif"]
        assert stack[0] == "DejaVu Sans"
        assert "Microsoft YaHei" in stack and "SimHei" in stack

    def test_color_cycle_explicit_tab10_order(self):
        """配色序显式单源（tab10 前六同序——缺省观感零变化）。"""
        colors = list(STYLE["axes.prop_cycle"].by_key()["color"])
        assert colors == PAPER_COLORS
        assert colors[:4] == ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728"]

    def test_figsize_anchors_from_publication_standards(self):
        from rfauto.core.publication_standards import (
            IEEE_COLUMNWIDTH_IN,
            IEEE_FULLWIDTH_IN,
        )

        assert PAPER_FIGSIZE_SINGLE[0] == IEEE_COLUMNWIDTH_IN
        assert PAPER_FIGSIZE_DOUBLE[0] == IEEE_FULLWIDTH_IN

    def test_style_passes_ieee_gate(self):
        """STYLE → 仓内 IEEE 出版门 PASS（裁判面独立，#118 家法）。"""
        from rfauto.core.publication_standards import check_ieee_rcparams

        verdict = check_ieee_rcparams(style_as_dict(), target="column")
        assert verdict["ok"] is True
        assert verdict["verdict"] == "PASS", json.dumps(verdict, ensure_ascii=False)

    def test_style_as_dict_is_copy(self):
        d = style_as_dict()
        d["font.size"] = 42.0
        assert STYLE["font.size"] == 9.0


class TestContextZeroResidue:
    def test_enter_apply_exit_restore(self):
        import matplotlib

        matplotlib.rcParams["font.size"] = 42.0
        matplotlib.rcParams["axes.unicode_minus"] = True
        try:
            with paper_figure_context():
                assert matplotlib.rcParams["font.size"] == 9.0
                assert matplotlib.rcParams["axes.unicode_minus"] is False
            assert matplotlib.rcParams["font.size"] == 42.0
            assert matplotlib.rcParams["axes.unicode_minus"] is True
        finally:
            matplotlib.rcParams["font.size"] = 10.0  # matplotlib 缺省回锚
            matplotlib.rcParams["axes.unicode_minus"] = True

    def test_exception_inside_context_still_restores(self):
        import matplotlib

        before = dict(matplotlib.rcParams)
        with pytest.raises(RuntimeError, match="boom"), paper_figure_context():
            raise RuntimeError("boom")
        assert dict(matplotlib.rcParams) == before  # 异常路径零残留

    def test_overrides_apply_within_scope_only(self):
        import matplotlib

        with paper_figure_context(**{"figure.figsize": (6.0, 4.5)}):
            # matplotlib rcParams 把 figsize 元组归一为 list（形状归一面）
            assert list(matplotlib.rcParams["figure.figsize"]) == [6.0, 4.5]
            assert matplotlib.rcParams["font.size"] == 9.0  # 其余键仍走 STYLE
        assert list(matplotlib.rcParams["figure.figsize"]) != [6.0, 4.5]

    def test_apply_paper_style_sets_then_observed(self):
        """全局施加面：apply 后逐键等于 STYLE（消费方可观测）。

        归一注记：rcParams 对 font.family（str→[str]）与 figure.figsize
        （tuple→list）做形状归一——两键按归一形态断言，其余逐键原值。"""
        import matplotlib

        before = dict(matplotlib.rcParams)
        try:
            apply_paper_style()
            for key, value in STYLE.items():
                got = matplotlib.rcParams[key]
                if key == "font.family":
                    assert got == ["sans-serif"], key
                elif key == "figure.figsize":
                    assert list(got) == list(value), key
                else:
                    assert got == value, key
        finally:
            matplotlib.rcParams.update(before)


class TestConsumerSmoke:
    """消费面冒烟（Agg 后端 + tmp_path，禁真显示）。"""

    def test_pareto_scatter_renders_deterministic_in_paper_style(
            self, tmp_path, monkeypatch):
        """design_replay pareto 散点：接线后同输入两跑逐字节 + 风格生效
        （渲染期 font.size=STYLE 值——rc_context 作用域内）。"""
        import matplotlib

        matplotlib.use("Agg", force=True)
        from rfauto.service.design_replay_report import _render_pareto_scatter

        out1 = tmp_path / "d1" / "pareto_scatter.png"
        out2 = tmp_path / "d2" / "pareto_scatter.png"
        ok1, err1 = _render_pareto_scatter(
            [(0.1, 1.0), (0.2, 0.8), (0.5, 0.6)], [(0.4, 1.2)],
            ["cost", "gain"], out1)
        assert ok1, err1
        ok2, err2 = _render_pareto_scatter(
            [(0.1, 1.0), (0.2, 0.8), (0.5, 0.6)], [(0.4, 1.2)],
            ["cost", "gain"], out2)
        assert ok2, err2
        b1, b2 = out1.read_bytes(), out2.read_bytes()
        assert b1[:8] == b"\x89PNG\r\n\x1a\n"
        assert b1 == b2  # 确定性：同输入两跑逐字节（R11 消费不破确定性）

    def test_render_period_rcparams_match_style(self, tmp_path, monkeypatch):
        """渲染作用域内 rcParams=STYLE（接线生效的直接观测）。"""
        import matplotlib

        matplotlib.use("Agg", force=True)
        seen: dict[str, object] = {}

        from rfauto.core import plot_style

        orig_rc_context = matplotlib.rc_context

        def _spy(rc=None, *a, **k):
            seen.update(rc or {})
            return orig_rc_context(rc, *a, **k)

        monkeypatch.setattr(matplotlib, "rc_context", _spy)
        from rfauto.service.design_replay_report import _render_pareto_scatter

        ok, err = _render_pareto_scatter([(0.0, 0.0)], [], ["x", "y"],
                                         tmp_path / "p.png")
        assert ok, err
        assert seen.get("font.size") == plot_style.STYLE["font.size"]
        assert seen.get("axes.unicode_minus") is False

    def test_pareto_render_source_wired_to_paper_style(self):
        """接线存在棘轮：_render_pareto_scatter 源码消费
        paper_figure_context（拆线=显式评审动作）。"""
        from rfauto.service import design_replay_report as mod

        src = inspect.getsource(mod._render_pareto_scatter)
        assert "paper_figure_context" in src

    def test_plot_style_module_not_in_public_api_gold(self):
        """新模块零金快照漂移钉：core/plot_style.py 无 __all__ 赋值 →
        public_api 快照不含本模块（check_public_api 口径）。"""
        import ast
        from pathlib import Path

        gold = json.loads(
            (Path(__file__).resolve().parents[2] / "tests" / "gold"
             / "public_api.json").read_text(encoding="utf-8"))
        assert "core/plot_style.py" not in gold.get("files", {})
        src = (Path(__file__).resolve().parents[2] / "src" / "rfauto" / "core"
               / "plot_style.py").read_text(encoding="utf-8")
        # 模块面钉：无 __all__ 赋值（AST 判定同 check_public_api 口径；
        # 晋升 __all__ 须同笔重生成金快照——显式评审动作）
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                assert not any(
                    isinstance(t, ast.Name) and t.id == "__all__"
                    for t in node.targets), "plot_style 晋升 __all__ 须重生成金快照"

    @pytest.mark.parametrize("backend", ["Agg"])
    def test_context_with_oo_figure_smoke(self, tmp_path, backend):
        """paper_figure_context + OO API 出图冒烟（Agg；零 pyplot）。"""
        import matplotlib

        matplotlib.use(backend, force=True)
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure

        with paper_figure_context():
            fig = Figure(figsize=PAPER_FIGSIZE_DOUBLE)
            FigureCanvasAgg(fig)
            ax = fig.add_subplot(111)
            ax.plot([0, 1, 2], [0, -1, 4], label="S21 (dB)")  # 负值走 '-'（minus 关）
            ax.legend()
            out = tmp_path / "smoke.png"
            fig.savefig(str(out), format="png")
        assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
