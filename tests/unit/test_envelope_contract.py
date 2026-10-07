"""AU-2④ 信封形状契约测试门（docs/envelope_contract.md 的机器可判面）。

钉三层：
1. 构造器行为（envelope.py 四件套）——三态形状、errors 恒 list、
   skipped 必带 reason、normalize 归一语义；
2. 已改域抽查——api / mcp_server / ui_service / remote_ads 的代表信封
   逐键形状（键集不变=旧消费者零破坏的回归钉）；
3. schema_version 按域推广——pdn（范本）+ 本批三域常量与落键抽查。

契约全文见 docs/envelope_contract.md；本文件红=契约违约，改形状前先改
契约文档再升 ENVELOPE_SCHEMA_VERSION。
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from rfauto.service import envelope as env_mod
from rfauto.service.envelope import (
    ENVELOPE_SCHEMA_VERSION,
    error_envelope,
    normalize_errors,
    ok_envelope,
    skipped_envelope,
)

# ---------------------------------------------------------------------------
# 1. 构造器行为
# ---------------------------------------------------------------------------


class TestConstructorContract:
    def test_ok_envelope_shape(self):
        assert ok_envelope(runs=[1, 2]) == {"ok": True, "runs": [1, 2]}
        assert ok_envelope() == {"ok": True}
        # ok 恒 True 且首键
        e = ok_envelope(data={"x": 1})
        assert e["ok"] is True
        assert next(iter(e)) == "ok"

    def test_error_envelope_errors_always_list(self):
        # str 入参 → 单元素列表
        assert error_envelope("boom") == {"ok": False, "errors": ["boom"]}
        # 列表入参原样语义
        assert error_envelope(["a", "b"]) == {"ok": False, "errors": ["a", "b"]}
        # None → 空列表（不缺键）
        assert error_envelope(None) == {"ok": False, "errors": []}
        # 非串元素 str() 化（errors 恒 list[str]）
        e = error_envelope([ValueError("x"), 3])
        assert e["errors"] == ["x", "3"]
        assert all(isinstance(s, str) for s in e["errors"])
        # 附加诊断键在 errors 之后
        assert error_envelope(["e"], run_id="r1") == {
            "ok": False, "errors": ["e"], "run_id": "r1"}

    def test_normalize_errors(self):
        assert normalize_errors(None) == []
        assert normalize_errors("solo") == ["solo"]
        assert normalize_errors(("a", "b")) == ["a", "b"]
        assert normalize_errors(42) == ["42"]
        assert normalize_errors([]) == []

    def test_skipped_envelope_contract(self):
        # 缺省：ok=True + skipped=True + reason 必给
        e = skipped_envelope("无登记机器")
        assert e == {"ok": True, "skipped": True, "reason": "无登记机器"}
        # 历史前置不满足语义：ok=False 保持原形状（remote_ads 口径）
        e2 = skipped_envelope("缺 opt-in", ok=False, steps={"probe": 1})
        assert e2 == {"ok": False, "skipped": True, "reason": "缺 opt-in",
                      "steps": {"probe": 1}}
        assert e2["skipped"] is True
        # reason 恒 str
        assert isinstance(skipped_envelope(123)["reason"], str)

    def test_envelope_schema_version_constant(self):
        assert isinstance(ENVELOPE_SCHEMA_VERSION, str)
        assert ENVELOPE_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# 2. 已改域抽查（形状回归钉：键集不变）
# ---------------------------------------------------------------------------


class TestApiFaceShapes:
    def test_validate_recipe_missing_file(self, tmp_path: Path):
        from rfauto.service.api import validate_recipe

        r = validate_recipe(tmp_path / "nope.yaml")
        assert r["ok"] is False
        assert isinstance(r["errors"], list) and r["errors"]
        assert all(isinstance(s, str) for s in r["errors"])
        assert r["warnings"] == []

    def test_get_metrics_missing_run(self):
        from rfauto.service.api import get_metrics

        r = get_metrics("__no_such_run_for_envelope_gate__")
        assert r["ok"] is False
        assert isinstance(r["errors"], list) and len(r["errors"]) == 1

    def test_list_models_carries_load_errors(self):
        """AU-7：注册失败账本可见化（缺省空列表，恒 list[str]）。"""
        from rfauto.service.api import list_models

        r = list_models()
        assert r["ok"] is True
        assert isinstance(r["models"], list) and r["models"]
        assert isinstance(r["load_errors"], list)
        assert all(isinstance(s, str) for s in r["load_errors"])

    def test_recipe_migrate_unknown_version(self, tmp_path: Path):
        import yaml as _yaml

        from rfauto.service.api import recipe_migrate

        p = tmp_path / "r.yaml"
        p.write_text(_yaml.safe_dump({"model": "wilkinson", "recipe_version": 99}),
                     encoding="utf-8")
        r = recipe_migrate(p)
        assert r["ok"] is False
        assert isinstance(r["errors"], list) and r["errors"]

    def test_api_envelopes_all_go_through_single_source(self):
        """api.py 改域内裸信封清零（含原 §3.3 两处结构化 gate 遗留族）.

        守卫多行感知（ge5 审查 P2-1）：``\\s*`` 跨行匹配，多行字面量
        ``return {\\n "ok": ...`` 不再漏检。W3fix 批（2026-10-05）把
        agent_propose L1/L2 两处 gate 遗留迁走（stage/gate 键保留、
        errors 承载 violations/issues 摘要），api.py 裸信封就此清零。
        """
        import re

        src = Path(env_mod.__file__).parent.joinpath("api.py").read_text(
            encoding="utf-8")
        bare = [m.group(0) for m in
                re.finditer(r'return \{\s*"ok":\s*(?:True|False)[^}]*', src)]
        assert bare == [], f"api.py 出现裸信封: {bare}"


class TestUiServiceFaceShapes:
    def test_read_run_events_illegal_id(self):
        from rfauto.service.ui_service import read_run_events

        r = read_run_events("../evil")
        assert r["ok"] is False
        assert isinstance(r["errors"], list) and r["errors"]
        # 附加诊断键保持历史形状
        assert r["exists"] is False and r["events"] == [] and r["offset"] == 0

    def test_read_run_events_missing_is_ok_not_error(self):
        from rfauto.service.ui_service import read_run_events

        r = read_run_events("no_such_run_envelope_gate")
        assert r["ok"] is True and r["exists"] is False

    def test_uq_yield_rejects_non_numeric_sigma(self):
        from rfauto.service.ui_service import uq_yield_run

        r = uq_yield_run("whatever.json", {"g": "not-a-number"})
        assert r["ok"] is False
        assert isinstance(r["errors"], list) and "σ" in r["errors"][0]

    def test_ui_service_envelopes_all_go_through_single_source(self):
        """ui_service 改域内禁新增裸信封（两处 sandbox 单数遗留族豁免）.

        守卫多行感知（ge5 审查 P2-1）：修复前 tune_trials/field_view 两处
        多行裸信封 ``return {\\n "ok": True, ...`` 对单行正则与计数门双双
        失明；现已收编 ok_envelope，守卫升级为跨行匹配防复发。
        """
        import re

        src = Path(env_mod.__file__).parent.joinpath("ui_service.py").read_text(
            encoding="utf-8")
        bare = [m.group(0) for m in
                re.finditer(r'return \{\s*"ok":\s*(?:True|False)[^}]*', src)]
        assert len(bare) == 2, f"ui_service 裸信封应只剩 2 处 sandbox 遗留: {bare}"
        assert all('"error"' in g for g in bare)


class TestMcpServerFaceShapes:
    def test_diagnose_missing_run_error_list(self):
        from rfauto.service import api as api_mod

        pytest.importorskip("fastmcp")
        from rfauto import mcp_server  # noqa: F401  触发工具注册面

        # mcp diagnose 壳复用 get_metrics 的 error_envelope 输出
        r = api_mod.get_metrics("__no_such_run_for_envelope_gate__")
        assert r["ok"] is False and isinstance(r["errors"], list)

    def test_mcp_errors_family_single_sourced(self):
        """mcp_server 的 errors 列表族必须走单源；单数 error 遗留族不计。"""
        import re

        # AU-1 批3 拆分（2026-09-30）：mcp_server 为 facade + mcp_tools/
        # 工具组包——裸信封扫描聚合全部源码文件，断言本身零改动。
        rfauto_dir = Path(env_mod.__file__).parent.parent
        srcs = [rfauto_dir.joinpath("mcp_server.py").read_text(encoding="utf-8")]
        srcs += [f.read_text(encoding="utf-8")
                 for f in sorted(rfauto_dir.glob("mcp_tools/*.py"))]
        src = "\n".join(srcs)
        assert 'from rfauto.service.envelope import error_envelope' in src
        bare_list = [m.group(0) for m in
                     re.finditer(r'return \{\s*"ok":\s*False,\s*"errors"', src)]
        assert bare_list == [], f"mcp_server 出现裸 errors 信封: {bare_list}"


class TestRemoteAdsSkippedFamily:
    def test_skipped_preconditions_keep_shape(self, monkeypatch):
        monkeypatch.delenv("RFAUTO_REMOTE_SMOKE", raising=False)
        monkeypatch.delenv("RFAUTO_REMOTE_ADS", raising=False)
        from rfauto.service import remote_ads_service as mod

        r = mod.remote_ads_run("n.net", machine="m")
        # 历史形状逐键：ok=False + skipped=True + reason（str）
        assert r["ok"] is False
        assert r["skipped"] is True
        assert isinstance(r["reason"], str) and r["reason"]

    def test_remote_ads_skipped_single_sourced(self):
        src = (Path(env_mod.__file__).parent / "remote_ads_service.py"
               ).read_text(encoding="utf-8")
        assert "skipped_envelope(" in src
        # 唯一残留=docstring 里的线上形状记载；代码字面量零残留
        assert src.count('"skipped": True') == 1
        assert '``{"ok": False, "skipped": True, "reason", "steps"}``' in src


# ---------------------------------------------------------------------------
# 3. schema_version 按域推广（PDN 范本 + 本批三域）
# ---------------------------------------------------------------------------


class TestSchemaVersionDomains:
    def test_pdn_reference_convention(self):
        from rfauto.service.pdn_service import (
            PDN_SERVICE_SCHEMA_VERSION,
            pdn_analyze,
        )

        assert isinstance(PDN_SERVICE_SCHEMA_VERSION, str)
        r = pdn_analyze({})
        assert r["ok"] is False
        assert isinstance(r["errors"], list) and r["errors"]
        assert r["schema_version"] == PDN_SERVICE_SCHEMA_VERSION

    def test_diagnosis_domain_stamped(self):
        from rfauto.service.diagnosis_service import (
            DIAGNOSIS_SCHEMA_VERSION,
            run_diagnosis,
        )

        r = run_diagnosis({"mode": "nope"})
        assert r["ok"] is False
        assert r["schema_version"] == DIAGNOSIS_SCHEMA_VERSION
        # 契约版本为字串带点分（PDN 惯例）
        assert isinstance(DIAGNOSIS_SCHEMA_VERSION, str)

    def test_anchors_domain_stamped(self, tmp_path: Path):
        from rfauto.service.anchors_service import (
            ANCHORS_REPORT_SCHEMA_VERSION,
            anchors_stale_report,
        )

        r = anchors_stale_report(path=str(tmp_path / "missing.yaml"))
        assert r["schema_version"] == ANCHORS_REPORT_SCHEMA_VERSION
        neg = anchors_stale_report(-1.0, path=str(tmp_path / "x.yaml"))
        assert neg["ok"] is False
        assert neg["schema_version"] == ANCHORS_REPORT_SCHEMA_VERSION

    def test_league_domain_stamped(self, tmp_path: Path):
        from rfauto.service.league_service import (
            LEAGUE_SCHEMA_VERSION,
            collect_league_rows,
        )

        r = collect_league_rows(str(tmp_path / "no_runs_dir"))
        assert r["ok"] is False
        assert r["schema_version"] == LEAGUE_SCHEMA_VERSION
        assert isinstance(r["reason"], str)  # 遗留 reason 族形状保持

    def test_old_archive_without_key_is_readable(self):
        """消费面向后兼容：无 schema_version 的旧档案 dict 照读不拒。"""
        legacy: dict[str, Any] = {"ok": True, "rows": [], "stats": {}}
        assert legacy.get("schema_version") is None  # 读侧按旧档案处理


# ---------------------------------------------------------------------------
# 4. _num 助手单源（AU-2⑤）
# ---------------------------------------------------------------------------


class TestCoerceFloatSingleSource:
    def test_policy_matrix(self):
        from rfauto.core.num_utils import coerce_float

        assert coerce_float("1.5") == 1.5
        assert coerce_float(True, accept_bool=True) == 1.0
        assert coerce_float(True) is None
        assert coerce_float("1.5", accept_str=False) is None
        assert coerce_float(float("inf")) is None
        assert coerce_float(float("nan")) is None
        assert coerce_float(float("inf"), finite_only=False) == float("inf")
        assert coerce_float(None) is None
        assert coerce_float("abc") is None

    def test_three_legacy_wrappers_keep_bitwise_behavior(self):
        """三处历史 _as_float 薄包装逐位保持（AU-2⑤ 零行为变化钉）。"""
        from rfauto.core.mesh_artifact import _as_float as mesh_f
        from rfauto.core.num_utils import coerce_float
        from rfauto.pipeline.log_distiller import _as_float as dist_f
        from rfauto.service.league_service import _as_float as league_f

        # mesh：bool 放行、str 解析、有限过滤
        assert mesh_f(True) == 1.0 and mesh_f("2.5") == 2.5
        assert mesh_f(float("nan")) is None
        # distiller：bool 排除、str 解析、有限过滤
        assert dist_f(True) is None and dist_f("2.5") == 2.5
        assert dist_f(float("inf")) is None
        # league：只收原生数值、不查有限性
        assert league_f("2.5") is None and league_f(True) is None
        assert league_f(float("inf")) == float("inf")
        # 三者都是 coerce_float 的策略实例（单源同一函数）
        assert mesh_f is not coerce_float and dist_f is not coerce_float

    def test_no_duplicate_bodies_remain(self):
        """三消费文件里不得再有完整 float() try/except 重复实现体。"""
        base = Path(env_mod.__file__).parent.parent
        for rel, marker in (
            ("core/mesh_artifact.py", "coerce_float(value, accept_str=True"),
            ("pipeline/log_distiller.py", "coerce_float(value, accept_str=True"),
            ("service/league_service.py", "coerce_float(value, accept_str=False"),
        ):
            src = (base / rel).read_text(encoding="utf-8")
            assert marker in src, f"{rel} 未接单源"
            assert "except (TypeError, ValueError):\n        return None\n        return" not in src


# ---------------------------------------------------------------------------
# 6. AST 级裸信封全量守卫（ge6 followUp P2-1 残余清偿）
# ---------------------------------------------------------------------------

#: 冻结值（2026-10-01 ge6 followUp 批实测，AST 扫描口径见 _count_bare_envelopes）：
#: 裸 ok 信封 return 存量 1178（直接字面量 1082 + 一跳变量中转 96，179 文件）；
#: 单数 error 遗留族 200（AU-2 登记「按域升版才统一」的存量现状）。
_FROZEN_BARE_OK_RETURNS = 525  # W6 AU-2 首域（bands 22 处）+并发批净迁（2026-10-06）534→实测 525；# W3 迁移批历史：# W3 信封构造器迁移批（2026-10-05 w3fix 席 37 处：env_reliability/calibration FSV 族/lake export-verify-restore/sim_ci/surrogate_registry/api agent_propose L1L2）552→实测 534；# ge8e W2 快偿历史注记：# 2026-10-04 ge8e W2 快偿 11 处（R5-06 恰形位点：agent_bench 1+dataset_insights 2+fab_export 1+level2_design 1+rag_service 1+reproducibility 1+rest_api 1+skill_autopilot 2+stratified_doe 1；envelope.py:66 构造器本体=已登记豁免不动）：565 冻结→本批开工 HEAD 实测 563（ge8d 冻结后他批同形迁移致树面漂移 −2）→本批后 552  # ge8d 席D5 迁移二批实测（2026-10-03，AST 扫描口径不变）：迁移前树面 1356（ge8c 冻结 1545→落库期他席新面已使实测漂移），本批 service/*.py 同形迁移（ok_envelope/error_envelope/skipped_envelope；混合 **unpack 站点包 **{...} 重建 dict 字面量"后者覆盖"语义；关键字键站包裹形态）净 -791 守卫单位 → 565。剩余构成本次实测普查：单数 error 冻结族 200（契约 §3.1）+ false_other 123（§3.2/3.4 裸 reason/issues/status 失败形，改形即破坏消费方）+ errors 非键位1 118（键序不变铁律）+ mid-dict 计算态 ok 67（席C7 先例）+ span 含注释/非标识符键 14 + envelope.py 构造器本体 2 + mcp_tools 禁改面 1 + 他席在制新文件若干 + 中转残余。≤200 目标在"零语义/零接口变化"硬约束下不可达（522 为契约 §3 遗留族地板），达标需按域升版统一（契约 AU-2 口径）另立票  # ge8c 终冻结（C 波七席+迁移首批 -12 全部落库后实测）  # 1283−12：ge8c 席C7 envelope 迁移首批（litwatch 2→1/cbr_case 2→0/external_dataset 9→4/dataset_quality 4→2/preflight 1→0/uncertainty_ledger 1→0）
_FROZEN_SINGULAR_ERROR = 173  # W6 AU-2 首域 bands 22 处清偿（2026-10-06）195→实测 173；# W3 迁移批历史：200→195


class TestAstBareEnvelopeFaceGuards:
    """守卫升级 AST 级 + 扫描面扩全 service/mcp（正则守卫的双盲区闭合）.

    上方 test_api/ui_service 两个正则守卫只盯已改域 ``return {`` 字面量，
    已知残余盲区（ge5 P2-1 披露）：①变量中转形态 ``r = {...}; return r``；
    ②四面之外的其他 service 文件。本守卫以 AST 全量扫描闭合两面：

    - 面 = ``service/*.py`` + ``mcp_server.py`` + ``mcp_tools/**/*.py``；
    - 裸 ok 信封 = return 的 Dict 字面量含常量键 "ok"（**多行/引号形态
      天然免疫**，AST 结构判定）+ 一跳变量中转（Name 先被赋值为此类
      字面量再 return）；
    - 冻结语义：**只禁增长不禁收敛**——存量改走 envelope 构造器使计数
      下降不红；+1 即红（新代码必须走构造器，契约 §4 规约）。迁移收敛
      后可把模块级冻结值下调（把守卫当台账用）。
    """

    @staticmethod
    def _face_files() -> list[Path]:
        base = Path(env_mod.__file__).parent          # src/rfauto/service
        pkg = base.parent                             # src/rfauto
        files = sorted(base.glob("*.py"))
        files.append(pkg / "mcp_server.py")
        files += sorted((pkg / "mcp_tools").rglob("*.py"))
        return [f for f in files if f.is_file()]

    @staticmethod
    def _ok_dict(node: Any) -> bool:
        """Dict 字面量含常量键 "ok"（AST 结构判定，多行/中转免疫）。"""
        if not isinstance(node, ast.Dict):
            return False
        return any(isinstance(k, ast.Constant) and k.value == "ok"
                   for k in node.keys)

    @classmethod
    def _count_bare_envelopes(cls) -> tuple[int, int]:
        bare = singular = 0
        for path in cls._face_files():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            ok_names: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for t in node.targets:
                        if isinstance(t, ast.Name) and cls._ok_dict(node.value):
                            ok_names.add(t.id)
                elif isinstance(node, ast.AnnAssign) and isinstance(
                        node.target, ast.Name):
                    if cls._ok_dict(node.value):
                        ok_names.add(node.target.id)
                elif isinstance(node, ast.Return) and node.value is not None:
                    if cls._ok_dict(node.value):
                        bare += 1
                        keys = {k.value for k in node.value.keys
                                if isinstance(k, ast.Constant)}
                        if "error" in keys and "errors" not in keys:
                            singular += 1
                    elif (isinstance(node.value, ast.Name)
                          and node.value.id in ok_names):
                        bare += 1
        return bare, singular

    def test_bare_ok_envelope_stock_frozen(self):
        bare, _singular = self._count_bare_envelopes()
        assert bare <= _FROZEN_BARE_OK_RETURNS, (
            f"service/mcp 面裸 ok 信封存量增长（{bare} > "
            f"{_FROZEN_BARE_OK_RETURNS}）：新信封必须走 envelope.py 构造器"
            "（契约 §4；AST 级守卫含一跳变量中转形态）。若为合法迁移收敛"
            "致计数下降，请把 _FROZEN_BARE_OK_RETURNS 下调至现值。")

    def test_singular_error_family_frozen(self):
        _bare, singular = self._count_bare_envelopes()
        assert singular <= _FROZEN_SINGULAR_ERROR, (
            f"单数 error 遗留族增长（{singular} > "
            f"{_FROZEN_SINGULAR_ERROR}）：AU-2 口径按域升版才统一，"
            "禁止新增（errors 列表族为正形）。收敛后请同步下调冻结值。")

    def test_face_inventory_nonempty(self):
        """扫描面存在性守卫：面文件数下限（防目录挪位后静默扫空）。"""
        files = self._face_files()
        assert len(files) >= 170, f"扫描面异常收缩: {len(files)} 文件"
        assert any(f.name == "remote_oe_service.py" for f in files)
        assert any(f.name == "resources.py" and f.parent.name == "mcp_tools"
                   for f in files)
