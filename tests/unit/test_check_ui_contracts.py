"""UI 前后端契约门提取器单元回归（aurora_f 审查波 2 P3-1 正式化；
aurora_h W5-S1 R3 #9 扩查询参数维度 C 向）。

scripts/check_ui_contracts.py 此前全仓零测试引用（SUMMARY 的"负向自证"
无落盘测试载体）——提取器若被改坏（字符类收窄/归一漂移）门会假绿静默
放行调用面漂移。本文件把审查席 16 例探针
（内部证据档）正式化：

1. 三形态提取（反引号模板串 / 引号字面量+拼接链 / 查询串截断）+ 注释
   噪声消音 + 已知漏报/误报形态现行语义如实钉（改窄改宽都须重审契约
   覆盖面）；
2. norm_call/norm_route 归一口径（{param}/${...}/占位符→"*"、查询串
   截断、尾斜杠补 "*"）；
3. 两豁免表棘轮（DANGLING 零基线；UNCONSUMED 只删不加——现值 ⊆ 已知
   五键集，逐条理由非空）；
4. 负向自证常态化：合成悬空调用 → main() rc=1；空路由表 → rc=2 诚实
   降级；vendor/ 排除；实树活体 main() rc=0 + 双向对账子集关系。
5. 查询参数 C 向（aurora_h W5-S1）：前端查询串四形态参数名提取（字面/
   拼接链/模板值位/局部查询构造变量三通道）+ 值位占位无害与整段委托
   降级语义；server 端 AST 消费面（直取/别名/下标/f-string 循环动态键
   解析）；DANGLING_PARAM 零基线与 UNSENT_PARAM 只删不加棘轮；合成负向
   （悬空参数/未登记未传 → rc=1）；实树活体（前端参数 ⊆ server 消费、
   未传豁免==实算未传集双向零陈旧）。

node-free 纯函数测试（extract_calls/norm_call 直测），零网络零 pytest
外依赖；脚本经 importlib 按路径装载（不污染 sys.path，无 stdlib 遮蔽面）。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "scripts" / "check_ui_contracts.py"

_spec = importlib.util.spec_from_file_location("_check_ui_contracts_under_test", _SCRIPT)
cc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cc)


# ── 1. 三形态提取（16 例探针正式化）─────────────────────────────────────

# (label, js 片段, 期望归一调用形态集)——期望值=审查席探针实测现行语义。
# known_miss/known_false_positive 条目为**如实钉**：现行提取器的已知漏报/
# 误报形态（审查报告 P3-1 原文），任一方向的行为变化都必须重审契约覆盖，
# 不许在无台账的情况下静默漂移。
_EXTRACT_CASES = [
    ("template_basic",
     "fetch(`/api/runs/${id}`)",
     {"/api/runs/*"}),
    ("template_query_truncated",
     "fetch(`/api/sparams/${encodeURIComponent(x)}?mode=${m}`)",
     {"/api/sparams/*"}),
    ("quote_concat_chain",
     'fetch("/api/runs/diff?a=" + encodeURIComponent(a) + "&b=" + '
     'encodeURIComponent(b))',
     {"/api/runs/diff"}),
    ("quote_concat_prefix",
     'api("/api/" + name)',
     {"/api/*"}),
    ("single_quote",
     "fetch('/api/solvers')",
     {"/api/solvers"}),
    ("help_text_noise_excluded",
     "const h = `See /api/runs for details`;",
     set()),
    ("template_prefix_text_concat",
     'const u = `base` + `/api/runs`;',
     {"/api/runs"}),
    ("variable_base_known_miss",
     'const B="/api"; fetch(B + "/runs")',
     set()),
    ("comment_quoted_known_false_positive",
     '// fetch("/api/ghost") 历史注释',
     {"/api/ghost"}),
    ("comment_backtick_known_false_positive",
     "/* `/api/ghost2` */",
     {"/api/ghost2"}),
    ("multiline_template",
     "const u = `/api/calculators/run`;",
     {"/api/calculators/run"}),
    ("plus_number_literal_placeholder",
     'fetch("/api/runs?limit=" + 500)',
     {"/api/runs"}),
    ("ternary_both_branches",
     'fetch(cond ? "/api/smith/external" : `/api/smith/${id}`)',
     {"/api/smith/*", "/api/smith/external"}),
    ("template_leading_newline_known_miss",
     "const u = `\n/api/runs`;",
     set()),
    ("array_join_known_miss",
     'const segs = ["/api", "runs"].join("/")',
     set()),
    ("nested_quotes_in_concat",
     'fetch("/api/loop/board/" + encodeURIComponent(id) + "?full=1")',
     {"/api/loop/board/*"}),
]


class TestExtractorThreeForms:
    @pytest.mark.parametrize(("label", "js", "expected"), _EXTRACT_CASES,
                             ids=[c[0] for c in _EXTRACT_CASES])
    def test_extract_case(self, label, js, expected):
        del label
        assert cc.extract_calls(js) == expected

    def test_extract_returns_set_dedup(self):
        # 同形态重复调用去重（返回集语义）
        js = 'fetch("/api/solvers"); fetch("/api/solvers")'
        assert cc.extract_calls(js) == {"/api/solvers"}

    def test_non_api_paths_filtered(self):
        # 非 /api/ 起点字面量不进结果（拼接链终段归一后仍按前缀过滤）
        assert cc.extract_calls('x("/other/runs" + y + "/api")') == set()


# ── 2. 归一口径（两侧同款单源）─────────────────────────────────────────

class TestNormalization:
    @pytest.mark.parametrize(("raw", "expected"), [
        ("/api/runs?limit=500", "/api/runs"),                # 查询串截断
        ("/api/sparams/${encodeURIComponent(sel.value)}",
         "/api/sparams/*"),                                  # 模板表达式→*
        ("/api/runs/diff?a=\x00&b=\x00", "/api/runs/diff"),  # 占位符入查询串
        ("/api/reports/content?path=", "/api/reports/content"),
        ("/api/runs/", "/api/runs/*"),                       # 尾斜杠=拼接前缀
    ])
    def test_norm_call(self, raw, expected):
        assert cc.norm_call(raw) == expected

    @pytest.mark.parametrize(("route", "expected"), [
        ("/api/runs/{run_id}/figs/{name:path}", "/api/runs/*/figs/*"),
        ("/api/smith/{run_id}", "/api/smith/*"),
        ("/api/smith/external", "/api/smith/external"),  # 字面段不受参数归一影响
    ])
    def test_norm_route(self, route, expected):
        assert cc.norm_route(route) == expected


# ── 3. 两豁免表棘轮（只收不放）─────────────────────────────────────────

# UNCONSUMED_ALLOWLIST 已知集（2026-10-18 审查波 2 时点；2026-10-23
# aurora_j W1-S3 台账背书加 /api/solvers/viz——view_solvers 无消费 fetch
# 清偿后端点保留为服务端能力面）：只可删（前端接入清偿）不可加（新死
# 路由须台账背书）——新条目必红，删条目绿。
_KNOWN_UNCONSUMED = {
    "/api/tune/events/stream",
    "/api/campaign_queue/events/stream",
    "/api/events/stream",
    "/api/edb_status",
    "/api/solvers/viz",
}


class TestAllowlistRatchets:
    def test_dangling_baseline_empty(self):
        assert cc.DANGLING_ALLOWLIST == {}, (
            "悬空豁免表零基线被破坏——出现条目即违规（须理由+台账背书）")

    def test_unconsumed_only_delete_no_add(self):
        added = set(cc.UNCONSUMED_ALLOWLIST) - _KNOWN_UNCONSUMED
        assert not added, (
            f"无消费豁免只可删不可加（新死路由须台账背书）: {sorted(added)}")

    def test_unconsumed_entries_carry_reasons(self):
        for key, reason in cc.UNCONSUMED_ALLOWLIST.items():
            assert isinstance(reason, str) and reason.strip(), (
                f"豁免条目缺理由: {key}")


# ── 4. 负向自证常态化 ──────────────────────────────────────────────────

def _tmp_env(monkeypatch, tmp_path: Path, js_files: dict[str, str],
             routes: list[str]) -> None:
    """合成契约门输入（monkeypatch 逐测还原）：tmp static 目录 + 路由表。"""
    static = tmp_path / "static"
    static.mkdir()
    for name, src in js_files.items():
        p = static / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(src, encoding="utf-8")
    server = tmp_path / "server.py"
    server.write_text(
        "".join(f'Route("{r}", endpoint)\n' for r in routes),
        encoding="utf-8")
    monkeypatch.setattr(cc, "STATIC_DIR", static)
    monkeypatch.setattr(cc, "SERVER_PY", server)


class TestNegativeSelfProof:
    def test_dangling_call_rc1(self, tmp_path, monkeypatch, capsys):
        _tmp_env(
            monkeypatch, tmp_path,
            {"view_x.js": 'fetch("/api/ghost_endpoint");\n'
                          "fetch(`/api/runs/${id}`);\n"},
            ["/api/runs/{run_id}"])
        rc = cc.main()
        out = capsys.readouterr().out
        assert rc == 1
        assert "/api/ghost_endpoint" in out
        assert "[FAIL]" in out

    def test_vendor_dir_excluded(self, tmp_path, monkeypatch, capsys):
        _tmp_env(
            monkeypatch, tmp_path,
            {"view_x.js": 'fetch("/api/runs");\n',
             "vendor/x.js": 'fetch("/api/ghost_in_vendor");\n'},
            ["/api/runs"])
        rc = cc.main()
        out = capsys.readouterr().out
        assert rc == 0
        assert "ghost_in_vendor" not in out

    def test_unconsumed_route_rc1(self, tmp_path, monkeypatch, capsys):
        # 空前端 + 未登记路由 → 无消费端点方向同样红（双向对账）
        _tmp_env(monkeypatch, tmp_path, {}, ["/api/orphan"])
        rc = cc.main()
        out = capsys.readouterr().out
        assert rc == 1
        assert "/api/orphan" in out

    def test_unconsumed_allowlisted_passes(self, tmp_path, monkeypatch):
        # 豁免表条目不红（exemption 路径在档）
        _tmp_env(monkeypatch, tmp_path, {}, ["/api/edb_status"])
        assert cc.main() == 0

    def test_empty_routes_rc2_skip(self, tmp_path, monkeypatch):
        # 路由表解析为空 → 诚实降级 SKIP（环境类非门红）
        _tmp_env(monkeypatch, tmp_path,
                 {"view_x.js": 'fetch("/api/runs");\n'}, [])
        assert cc.main() == 2


class TestLiveGateOnRealTree:
    def test_real_tree_gate_green(self, capsys):
        rc = cc.main()
        capsys.readouterr()
        assert rc == 0, "实树活体门红——调用面/路由面漂移须先行清偿"

    def test_frontend_calls_subset_of_routes(self):
        calls = cc.collect_frontend_calls()
        routes = cc.collect_server_routes()
        assert calls, "前端调用提取为空（提取器或静态目录异常）"
        assert routes, "路由表解析为空"
        dangling = calls - routes
        assert not dangling, f"悬空调用: {sorted(dangling)}"


# ── 5. 查询参数 C 向（aurora_h W5-S1，R3 立项 #9）──────────────────────

class TestFrontendQueryParamExtraction:
    """前端查询串四形态参数名提取（frontend_query_params 直测）。"""

    def test_literal_query(self):
        js = 'fetch("/api/runs?limit=500")'
        assert cc.frontend_query_params(js) == {"/api/runs": {"limit"}}

    def test_concat_query_value_placeholder_harmless(self):
        # 值位占位（path=\x00）无害——参数名在 = 左侧提取（W5-S1 修正语义）
        js = 'fetch("/api/fs/list?path=" + encodeURIComponent(p))'
        assert cc.frontend_query_params(js) == {"/api/fs/list": {"path"}}

    def test_concat_chain_two_params(self):
        js = ('fetch("/api/runs/diff?a=" + encodeURIComponent(a) + '
              '"&b=" + encodeURIComponent(b))')
        assert cc.frontend_query_params(js) == {"/api/runs/diff": {"a", "b"}}

    def test_template_value_position(self):
        js = "fetch(`/api/sparams/${encodeURIComponent(x)}?mode=${m}`)"
        assert cc.frontend_query_params(js) == {"/api/sparams/*": {"mode"}}

    def test_urlsearchparams_interpolation(self):
        js = ('const q = new URLSearchParams({x_param: x, grid_n: n});'
              'fetch(`/api/runs/${id}/dashboard?${q}`)')
        assert cc.frontend_query_params(js) == {
            "/api/runs/*/dashboard": {"grid_n", "x_param"}}

    def test_var_set_append(self):
        # view_queue 实例形态：URLSearchParams 字面量 + 条件 .set 追加
        js = ('const q = new URLSearchParams({root: r});'
              'q.set("machine", m);'
              'fetch("/api/campaign_queue?" + q)')
        assert cc.frontend_query_params(js) == {
            "/api/campaign_queue": {"machine", "root"}}

    def test_ternary_template_fragment(self):
        # view_data 实例形态：三元模板段 `&model=${…}` 插进字面查询串
        js = ('const q = m ? `&model=${encodeURIComponent(m)}` : "";'
              'fetch(`/api/datasets/${n}/preview?limit=20${q}`)')
        assert cc.frontend_query_params(js) == {
            "/api/datasets/*/preview": {"limit", "model"}}

    def test_no_query_empty_set(self):
        assert cc.frontend_query_params('fetch("/api/solvers")') == {
            "/api/solvers": set()}

    def test_bare_delegate_degrades_to_none(self):
        # 整段委托（?+fn()）：名位=不可解析占位 → 该调用诚实降级 None
        js = ('fetch("/api/loop/board/" + encodeURIComponent(id) + "?" + '
              'buildQuery())')
        assert cc.frontend_query_params(js) == {"/api/loop/board/*": None}

    def test_none_poisons_route_across_calls(self):
        # 同路由一路径已解析+一调用降级 → 路由级 None（两向判定保守跳出）
        js = ('fetch("/api/x?a=1");'
              'fetch("/api/x?" + buildQuery())')
        assert cc.frontend_query_params(js) == {"/api/x": None}


class TestServerQueryParamExtraction:
    """server 端 handler 查询参数消费面（AST 直测：直取/别名/下标/f-string
    循环动态键解析——fieldviz f"s{ax}"→sx/sy/sz 实例）。"""

    def _handler(self, tmp_path: Path, src: str, func: str = "h"):
        p = tmp_path / "mod.py"
        p.write_text(src, encoding="utf-8")
        return cc._handler_query_params(p, func, {})

    def test_direct_get_with_default(self, tmp_path):
        found, names, unres = self._handler(tmp_path, (
            "async def h(request):\n"
            "    return request.query_params.get(\"limit\", 50)\n"))
        assert (found, names, unres) == (True, {"limit"}, False)

    def test_alias_and_subscript(self, tmp_path):
        found, names, unres = self._handler(tmp_path, (
            "async def h(request):\n"
            "    q = request.query_params\n"
            "    a = q.get(\"a\", \"\")\n"
            "    b = q[\"b\"]\n"
            "    return a + b\n"))
        assert (found, names, unres) == (True, {"a", "b"}, False)

    def test_fstring_loop_dynamic_keys(self, tmp_path):
        # routes/fieldviz.py api_field_view 同款：for ax in ("x","y","z")
        found, names, unres = self._handler(tmp_path, (
            "async def h(request):\n"
            "    q = request.query_params\n"
            "    out = {}\n"
            "    for ax in (\"x\", \"y\", \"z\"):\n"
            "        if q.get(f\"s{ax}\"):\n"
            "            out[ax] = q.get(f\"s{ax}\")\n"
            "    return out\n"))
        assert (found, names, unres) == (True, {"sx", "sy", "sz"}, False)

    def test_unresolvable_dynamic_key_flags(self, tmp_path):
        found, names, unres = self._handler(tmp_path, (
            "async def h(request):\n"
            "    return request.query_params.get(make_key())\n"))
        assert (found, names, unres) == (True, set(), True)

    def test_missing_handler_not_found(self, tmp_path):
        found, names, unres = self._handler(
            tmp_path, "x = 1\n", func="absent")
        assert (found, names, unres) == (False, set(), False)


# ── 6. 参数两豁免表棘轮（C 向；只收不放）───────────────────────────────

# UNSENT_PARAM_ALLOWLIST 已知集（2026-10-19 aurora_h W5-S1 建门时点）：
# 只可删（前端接入清偿）不可加（新未传参数须台账背书）——新条目必红。
_KNOWN_UNSENT = {
    "/api/field/*#engine", "/api/field/*#sx", "/api/field/*#sy",
    "/api/field/*#sz",
    "/api/farfield#limit", "/api/field#limit", "/api/inbox#limit",
    "/api/loop/boards#limit", "/api/pareto_runs#limit",
    "/api/uq/samples#limit",
    "/api/anchors#path", "/api/anchors/*#path",
    "/api/model3d#path", "/api/tune/trials#run_id",
}


class TestParamAllowlistRatchets:
    def test_dangling_param_baseline_empty(self):
        assert cc.DANGLING_PARAM_ALLOWLIST == {}, (
            "悬空参数豁免表零基线被破坏——出现条目即违规（须理由+台账背书）")

    def test_unsent_only_delete_no_add(self):
        added = set(cc.UNSENT_PARAM_ALLOWLIST) - _KNOWN_UNSENT
        assert not added, (
            f"未传豁免只可删不可加（新未传参数须台账背书）: {sorted(added)}")

    def test_unsent_entries_carry_reasons(self):
        for key, reason in cc.UNSENT_PARAM_ALLOWLIST.items():
            assert isinstance(reason, str) and reason.strip(), (
                f"未传豁免条目缺理由: {key}")
            assert "#" in key, f"未传豁免键须为 {{路由}}#{{参数}} 形态: {key}"


# ── 7. 参数门合成负向 + 实树活体 ────────────────────────────────────────

def _patch_param_collectors(monkeypatch, fe: dict, fe_deg: list[str],
                            sv: dict, sv_unres: set[str]) -> None:
    """合成 C 向采集面（A/B 向采集器不动——路径向由既有合成测试管辖）。"""
    monkeypatch.setattr(cc, "collect_frontend_query_params",
                        lambda: (dict(fe), list(fe_deg)))
    monkeypatch.setattr(cc, "collect_server_query_params",
                        lambda: (dict(sv), set(sv_unres)))


class TestParamGateSynthetic:
    def test_dangling_param_rc1(self, tmp_path, monkeypatch, capsys):
        del tmp_path
        _patch_param_collectors(
            monkeypatch, {"/api/runs": {"limit", "ghost"}}, [],
            {"/api/runs": {"limit"}}, set())
        rc = cc.main()
        out = capsys.readouterr().out
        assert rc == 1
        assert "/api/runs#ghost" in out
        assert "悬空参数" in out
        assert "[FAIL]" in out

    def test_dangling_param_allowlisted_passes(self, tmp_path, monkeypatch,
                                               capsys):
        del tmp_path
        monkeypatch.setattr(cc, "DANGLING_PARAM_ALLOWLIST",
                            {"/api/runs#ghost": "测试豁免"})
        _patch_param_collectors(
            monkeypatch, {"/api/runs": {"limit", "ghost"}}, [],
            {"/api/runs": {"limit"}}, set())
        assert cc.main() == 0
        capsys.readouterr()

    def test_unsent_param_rc1(self, tmp_path, monkeypatch, capsys):
        del tmp_path
        # server 新收 ghost、前端不传且未登记 → 未传方向红（棘轮必红面；
        # 键避开实树 UNSENT_PARAM_ALLOWLIST 现有条目）
        _patch_param_collectors(
            monkeypatch, {"/api/field/*": {"dump"}}, [],
            {"/api/field/*": {"dump", "ghost"}}, set())
        rc = cc.main()
        out = capsys.readouterr().out
        assert rc == 1
        assert "/api/field/*#ghost" in out
        assert "未传参数" in out

    def test_unsent_allowlisted_passes(self, tmp_path, monkeypatch, capsys):
        del tmp_path
        _patch_param_collectors(
            monkeypatch, {"/api/field/*": {"dump"}}, [],
            {"/api/field/*": {"dump", "ghost"}}, set())
        # 登记面在档（临时注入——monkeypatch 逐测还原，不污染实树棘轮）
        monkeypatch.setattr(
            cc, "UNSENT_PARAM_ALLOWLIST",
            {**cc.UNSENT_PARAM_ALLOWLIST, "/api/field/*#ghost": "测试豁免"})
        assert cc.main() == 0
        capsys.readouterr()

    def test_degraded_route_skips_both_directions(self, tmp_path, monkeypatch,
                                                  capsys):
        del tmp_path
        # 前端整段委托降级路由：两向都跳出（打注记不打红，#105 诚实降级）
        _patch_param_collectors(
            monkeypatch, {"/api/x": None}, ["/api/x"],
            {"/api/x": {"a", "b"}}, set())
        rc = cc.main()
        out = capsys.readouterr().out
        assert rc == 0
        assert "降级" in out

    def test_unconsumed_route_params_exempt(self, tmp_path, monkeypatch,
                                            capsys):
        del tmp_path
        # 无消费豁免路由的参数面由 B 向管辖——server 收了 root 不进未传红
        # （A/B 向采集器同场合成，豁免表临时注入）
        monkeypatch.setattr(cc, "collect_server_routes",
                            lambda: {"/api/stream"})
        monkeypatch.setattr(cc, "collect_frontend_calls", lambda: set())
        monkeypatch.setattr(
            cc, "UNCONSUMED_ALLOWLIST", {"/api/stream": "测试豁免"})
        _patch_param_collectors(
            monkeypatch, {}, [], {"/api/stream": {"root"}}, set())
        assert cc.main() == 0
        capsys.readouterr()


class TestLiveParamGateOnRealTree:
    def test_real_tree_param_collectors_zero_degradation(self):
        _, fe_deg = cc.collect_frontend_query_params()
        _, sv_unres = cc.collect_server_query_params()
        assert not fe_deg, f"实树前端查询降级面非空: {fe_deg}"
        assert not sv_unres, f"实树 server 动态键降级面非空: {sorted(sv_unres)}"

    def test_real_tree_frontend_params_subset_of_server(self):
        fe, fe_deg = cc.collect_frontend_query_params()
        sv, _ = cc.collect_server_query_params()
        assert not fe_deg
        for route, ps in fe.items():
            assert ps is not None
            extra = ps - sv.get(route, set())
            assert not extra, f"悬空参数（{route}）: {sorted(extra)}"

    def test_real_tree_unsent_exactly_allowlist(self):
        # 双向零陈旧钉：实算未传集==UNSENT_PARAM_ALLOWLIST——前端开始传=
        # 条目陈旧须删；server 新收=未登记必红（配合只删不加棘轮）
        fe, _ = cc.collect_frontend_query_params()
        sv, sv_unres = cc.collect_server_query_params()
        unsent: set[str] = set()
        for route, sp in sv.items():
            if route in cc.UNCONSUMED_ALLOWLIST or route in sv_unres:
                continue
            fp = fe.get(route)
            if fp is None:
                continue
            unsent |= {f"{route}#{p}" for p in sp - fp}
        assert unsent == set(cc.UNSENT_PARAM_ALLOWLIST), (
            f"未传豁免表与实算未传集漂移："
            f"陈旧须删 {sorted(set(cc.UNSENT_PARAM_ALLOWLIST) - unsent)} / "
            f"未登记 {sorted(unsent - set(cc.UNSENT_PARAM_ALLOWLIST))}")
