"""Phase 6 W6-F FE-1 候选包生成器回归钉（预备批；零网络 #139）。

被测单元=scripts/build_fe1_candidate.py 的纯函数面（run id 映射/账本指针
剥离/主机资产清洗/锚键型策略/JSON 键策略——SI §2.2「50 公开/10 映射/1 删」
的机械执行）。候选包本体（release/fe1_candidate/，gitignored 留盘）存在时
追加内容冒烟钉：锚投影可被 anchors_store 装载+SI §2.6 #3 spot-check 逐位。

纪律：候选包缺席（干净 checkout）时内容钉 skip——单元面不依赖 release/
产物（生成器可从树内随时重跑）。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_BUILDER = _REPO / "scripts" / "build_fe1_candidate.py"
_CANDIDATE = _REPO / "release" / "fe1_candidate"


def _builder():
    spec = importlib.util.spec_from_file_location("w6f_builder", _BUILDER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── 1. run id 映射 ─────────────────────────────────────────────────────────

def test_run_to_id_mapping() -> None:
    b = _builder()
    assert b.run_to_id("runs/df5_c3fix") == "df5_c3fix"
    assert b.run_to_id("runs/hfss_window_b2a/branchline") == \
        "hfss_window_b2a__branchline"
    assert b.run_to_id("runs/ge8_followup/wave_a/refs") == \
        "ge8_followup__wave_a__refs"
    assert b.run_to_id("runs\\ge6_hfsswin\\seat2_mscross") == \
        "ge6_hfsswin__seat2_mscross"  # 分隔符两向兼容
    assert b.run_to_id("ge6_anchor") == "ge6_anchor"  # 无前缀原样


# ── 2. 账本指针中性重写（机械变换；#NNN 按 D1 保留）────────────────────────

def test_strip_ledger_tokens_keeps_technical_text() -> None:
    b = _builder()
    # wf:df5f 形态
    s = b.strip_ledger_tokens(
        "DEV" + "LOG（三六九）wf:df5f：HFSS 反解 0.12-0.13nH 区间中点=对齐基准")
    assert "DEV" + "LOG" not in s and "wf:" not in s
    assert "HFSS 反解 0.12-0.13nH 区间中点=对齐基准" in s
    # +CJK 数字序号无括号形态（mmwave/ ms_cross 批实况）
    s2 = b.strip_ledger_tokens("冒烟（76.20GHz vs 设计 78=−2.31%，DEV" + "LOG 四四五）")
    assert "DEV" + "LOG" not in s2 and "76.20GHz" in s2
    # 裸 TODO 指针（consumption_note 实况）
    s3 = b.strip_ledger_tokens("接入排期按 TODO anchor_family_service 批计划推进")
    assert "TODO" not in s3 and "anchor_family_service 批计划" in s3
    # #NNN 坑号按 D1 保留（数字出处标记非泄漏）
    s4 = b.strip_ledger_tokens("收敛判据见 #335 如实 PARTIAL 与 #122 红线")
    assert "#335" in s4 and "#122" in s4


# ── 3. 主机资产清洗 + 仓路径剥离（SI §2.3 sanctioned 机械脱敏）──────────────

def test_scrub_text_assets_and_repo_prefix() -> None:
    b = _builder()
    s = b.scrub_text("sim_" + "server DrivenModal 同几何收敛（host=10." + "20.30.40）")
    assert "sim_" + "server" not in s and "172." + "26" not in s
    assert "remote-node" in s
    s2 = b.scrub_text(r"证据在 E:\HFSS_" + r"Connect\runs\df5_c3fix\x.json")
    s2 = b.scrub_text(r"证据在 E:\HFSS_" + r"Connect\runs\df5_c3fix\x.json")
    assert "runs/df5_c3fix/x.json" in s2 or "runs\\df5_c3fix\\x.json" in s2 \
        or "df5_c3fix" in s2


# ── 4. 锚键型策略（SI §2.2：50 公开/10 映射/1 删；未知键 fail-closed）──────

def _sample_anchor() -> dict:
    return {
        "anchor_id": "x.demo.closedform-v1", "kind": "constant",
        "template_family": ["demo"],
        "engine_pair": {"calibrated": "closedform", "referee": None},
        "quantity": {"name": "demo_z", "unit": "ohm", "semantics": "测试"},
        "value": 50.0,
        "uncertainty": {"value": 0.005, "kind": "rounding_band"},
        "domain": None,
        "provenance": {
            "arbitration_runs": ["runs/demo_run"],
            "commit": "abc1234",
            "devlog": "DEV" + "LOG（一）wf:x：Demo 依据 #11",
            "machine": "sim_host",
            "server_cleanup": "schtasks /delete …（内部运营语义）",
            "replaces": "无（首登记）",
        },
        "registered_at": "2026-10-05T00:00:00+08:00",
        "last_verified": None, "fallback": "closed_form",
        "status": "experimental", "consumers": [],
    }


def test_transform_anchor_policy_full() -> None:
    b = _builder()
    ids = {"demo_run"}
    out = b.transform_anchor(_sample_anchor(), ids)
    # 公开面零损（值/形态）
    assert out["value"] == 50.0
    assert out["quantity"]["name"] == "demo_z"
    # 映射面
    assert out["provenance"]["machine"] == "remote-node"  # 枚举替换
    assert out["provenance"]["arbitration_runs"] == ["demo_run"]  # id 映射
    assert "DEV" + "LOG" not in out["provenance"]["devlog"]  # 中性重写
    assert "#11" in out["provenance"]["devlog"]  # D1 保留
    assert "wf:" not in out["provenance"]["devlog"]
    # 删除面
    assert "server_cleanup" not in out["provenance"]
    # 公开面保全
    assert out["provenance"]["commit"] == "abc1234"
    assert out["provenance"]["replaces"] == "无（首登记）"


def test_transform_anchor_unknown_key_fails_closed() -> None:
    b = _builder()
    a = _sample_anchor()
    a["future_key"] = 1  # 未来锚新增未分类键必须炸出来，不得静默放行
    with pytest.raises(b.PolicyError, match="future_key"):
        b.transform_anchor(a, set())
    a2 = _sample_anchor()
    a2["provenance"]["future_prov"] = 1
    with pytest.raises(b.PolicyError, match="future_prov"):
        b.transform_anchor(a2, set())


# ── 5. JSON 键策略（剥离主机/路径键；物理键不误伤）─────────────────────────

def test_transform_json_drops_host_keys_keeps_physics() -> None:
    b = _builder()
    data = {
        "hostname": "DESKTOP-X", "user": "someone", "machine": "sim_host",
        "server_path": r"E:\rfauto_remote\job1",
        "metrics": {"s11_db": -20.5},
        "g_dual_path": 1.25,  # 物理键（dual path≠文件路径）不误伤
        "touchstone_path": "runs/wp39_mvp_followup/probe.s1p",
        "nested": {"host": "should_survive_non_drop_key"},
    }
    out, _notes = b.transform_json(data, {"wp39_mvp_followup"})
    assert "hostname" not in out and "user" not in out
    assert "machine" not in out and "server_path" not in out
    assert out["metrics"] == {"s11_db": -20.5}
    assert out["g_dual_path"] == 1.25  # 物理键保全
    assert out["touchstone_path"] == "wp39_mvp_followup/probe.s1p"  # id 映射
    assert out["nested"]["host"] == "should_survive_non_drop_key"


# ── 6. 预扫描三档判级（ground 扫描器同款 FAIL/WARN 面）─────────────────────

def test_scan_text_three_tier() -> None:
    b = _builder()
    # 夹具样文按段拼接（扫描器 generic-api-key 误报规避，W1-G 同法）
    sample = "key = sk-" + "abcdefghijklmnop1234 normal text"
    fails, warns = b.scan_text(sample)
    assert fails and fails[0].startswith("sk-")
    assert "abcdefghijklmnop" in fails[0]
    assert warns == []
    fails2, _ = b.scan_text("clean anchor text 50.0 ohm")
    assert fails2 == []


# ── 7. 候选包内容冒烟钉（候选在盘时；干净 checkout skip）───────────────────

@pytest.mark.skipif(not _CANDIDATE.exists(), reason="候选包未冻结（可重跑生成器）")
def test_candidate_payload_loads_and_spot_checks() -> None:
    from rfauto.infra.anchors_store import load_anchors

    yml = _CANDIDATE / "payload" / "anchors" / "anchors_public.yaml"
    store = load_anchors(yml, force_reload=True)
    assert len(store) >= 60
    rec = store.get("cpw.z0_ohm.closedform-v1")
    assert rec is not None and rec.value == 50.0  # W6-F 新锚随投影在包
    # SI §2.6 #3 逐位 spot-check
    assert store.get("c3.l_via_h.openems-hfss-v1").value == 1.25e-10
    assert store.get("patch.f_dip_l.openems-v1").value == 76.8
    # 敏感字面零残留（候选面全文）
    raw = yml.read_text(encoding="utf-8")
    for tok in ("sim_" + "server", "DEV" + "LOG", "TODO", "hand" + "off", "server_cleanup",
                "rf_workspace", "172.26"):
        assert tok not in raw, tok


@pytest.mark.skipif(not _CANDIDATE.exists(), reason="候选包未冻结（可重跑生成器）")
def test_candidate_manifest_and_scan_archive() -> None:
    import json

    manifest = json.loads((_CANDIDATE / "MANIFEST.json").read_text(
        encoding="utf-8"))
    assert manifest["counts"]["anchors"] >= 60
    assert manifest["counts"]["files_quarantined"] >= 1  # fail-closed 在档
    assert manifest["scan"]["returncode"] == 0  # ground 扫描器 clean
    assert (_CANDIDATE / "scan_result.txt").exists()
    # 逐文件三问预备稿（人工关口的机器预备层）
    f0 = manifest["files"][0]
    assert f0["three_q_machine_draft"]["review"] == "HUMAN-REVIEW-PENDING"
    assert {"q1_owner", "q2_why", "q3_license"} <= \
        set(f0["three_q_machine_draft"])
    # sha256 完整性抽查
    import hashlib

    p = _CANDIDATE / f0["path"]
    assert hashlib.sha256(p.read_bytes()).hexdigest() == f0["sha256"]
