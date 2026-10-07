"""cleanup_server_orphans 孤儿判定单测（E3-1，ge8e 审查批 F4 回归钉）。

原缺陷：脚本声明"父已死才算孤儿"但从不核对 PPID——命中任务指纹即
taskkill，父存活的合法桌面同样被点杀（#245 杀前核对/#265 不代杀违约）；
在飞白名单 oe_1a417ed4 硬编码（批次轮换必腐烂）。

修复面回归钉（判定逻辑抽纯函数，脚本薄壳调用）：
- classify_cmdline 三态：白名单 keep / 指纹 candidate / 旁观 skip；
- decide_orphans 三态：父死=点杀名单 / 父活=跳过留痕 / 查询失败=按存活
  保守处理（fail-safe 不杀）；
- collect_whitelist：登记文件 orphan_whitelist（extra 面）+ CLI 汇总，
  缺省空=无白名单；
- parse_census_rows / parent_alive_cmd / SSH 探针 / REPO 锚定。
全离线，零 SSH 零真机。
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

SCRIPT_PATH = (Path(__file__).resolve().parents[2] / "scripts"
               / "cleanup_server_orphans.py")
_spec = importlib.util.spec_from_file_location(
    "_cleanup_server_orphans_under_test", SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
orph = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("_cleanup_server_orphans_under_test", orph)
_spec.loader.exec_module(orph)

from rfauto.infra.remote_machines import RemoteMachineConfig


def _row(pid: int, ppid: int, cmdline: str) -> orph.CensusRow:
    return orph.CensusRow(pid=pid, ppid=ppid, name="ansysedt.exe",
                          cmdline=cmdline,
                          raw=f"PID={pid} NAME=ansysedt.exe PPID={ppid} "
                              f"CMD={cmdline}")


# ─── parse_census_rows ────────────────────────────────────────────────────


def test_parse_census_rows_normal_and_junk():
    out = (
        "PID=101 NAME=ansysedt.exe PPID=202 CMD=E:\\tools\\ansysedt.exe -grpcsrv\n"
        "\n"
        "some other powershell noise\n"
        "PID=not-a-number NAME=x PPID=1 CMD=y\n"
        "PID=103 NAME=python.exe PPID=204 CMD=python _rfauto_runner.py\n"
    )
    rows = orph.parse_census_rows(out)
    assert [r.pid for r in rows] == [101, 103]
    assert [r.ppid for r in rows] == [202, 204]
    assert rows[0].cmdline.startswith("E:")
    assert rows[1].cmdline.endswith("_rfauto_runner.py")


def test_parse_census_rows_empty_and_none():
    assert orph.parse_census_rows("") == []
    assert orph.parse_census_rows(None) == []


# ─── classify_cmdline 三态（E3-1 白名单/指纹/旁观） ───────────────────────


def test_classify_fingerprint_hit_is_candidate():
    assert orph.classify_cmdline(
        r"ansysedt -grpcsrv ... tasks\oe_1a417ed4\hfss", ()) == "candidate"
    assert orph.classify_cmdline("python _rfauto_runner.py blslope", ()) == "candidate"
    assert orph.classify_cmdline("python sim.py dk78r", ()) == "candidate"
    assert orph.classify_cmdline("hfss_side_remote driver", ()) == "candidate"
    assert orph.classify_cmdline("wheeler case", ()) == "candidate"


def test_classify_whitelist_beats_fingerprint():
    """白名单在飞登记绝不进点杀候选（即使同时命中任务指纹）。"""
    assert orph.classify_cmdline(
        r"tasks\oe_1a417ed4\hfss", ("oe_1a417ed4",)) == "keep"


def test_classify_non_task_is_skip():
    assert orph.classify_cmdline("notepad.exe", ()) == "skip"
    assert orph.classify_cmdline("", ()) == "skip"


# ─── collect_whitelist（登记文件 + CLI，缺省空） ──────────────────────────


def test_whitelist_default_empty():
    """缺省空=无白名单（E3-1：硬编码批次号必腐烂，在飞批次须显式声明）。"""
    assert orph.collect_whitelist(None, []) == ()
    cfg = RemoteMachineConfig(name="sim_host", host="h")
    assert orph.collect_whitelist(cfg, []) == ()


def test_whitelist_from_config_extra_list_and_str():
    cfg_list = RemoteMachineConfig(
        name="sim_host", host="h",
        extra={"orphan_whitelist": ["oe_1a417ed4", "k7_final"]})
    assert orph.collect_whitelist(cfg_list, []) == ("oe_1a417ed4", "k7_final")
    cfg_str = RemoteMachineConfig(
        name="sim_host", host="h", extra={"orphan_whitelist": "oe_abc123"})
    assert orph.collect_whitelist(cfg_str, []) == ("oe_abc123",)


def test_whitelist_cli_and_config_merge_dedup_keep_order():
    cfg = RemoteMachineConfig(
        name="sim_host", host="h",
        extra={"orphan_whitelist": ["oe_1a417ed4", "k7_final"]})
    merged = orph.collect_whitelist(cfg, ["k7_final", "oe_20261004"])
    assert merged == ("oe_1a417ed4", "k7_final", "oe_20261004")
    # 空串 token 丢弃
    assert orph.collect_whitelist(None, ["", "oe_x"]) == ("oe_x",)


# ─── decide_orphans 三态（E3-1 核心：父已死才算孤儿） ─────────────────────


def test_decide_parent_dead_is_orphan():
    candidates = [_row(111, 222, r"tasks\oe_9\hfss")]
    orphans, spared = orph.decide_orphans(candidates, lambda _ppid: False)
    assert [o.pid for o in orphans] == [111]
    assert spared == []


def test_decide_parent_alive_spared_with_reason():
    candidates = [_row(111, 222, r"tasks\oe_9\hfss")]
    orphans, spared = orph.decide_orphans(candidates, lambda _ppid: True)
    assert orphans == [], "父存活的合法桌面绝不进点杀名单（#245/#265）"
    assert len(spared) == 1 and spared[0][0].pid == 111
    assert "存活在飞" in spared[0][1]


def test_decide_probe_unknown_treated_as_alive():
    """查询失败=None=未知——按存活保守处理不杀（fail-safe）。"""
    candidates = [_row(111, 222, r"tasks\oe_9\hfss")]
    orphans, spared = orph.decide_orphans(candidates, lambda _ppid: None)
    assert orphans == []
    assert len(spared) == 1 and "保守" in spared[0][1]


def test_decide_mixed_rows_partitioned():
    candidates = [
        _row(1, 10, "blslope"),     # 父死 → 孤儿
        _row(2, 20, "dk78r"),       # 父活 → 留痕
        _row(3, 30, "wheeler"),     # 查询失败 → 留痕
    ]
    table = {10: False, 20: True, 30: None}
    orphans, spared = orph.decide_orphans(candidates, table.get)
    assert [o.pid for o in orphans] == [1]
    assert [s[0].pid for s in spared] == [2, 3]


# ─── parent_alive_cmd + SSH 探针 ──────────────────────────────────────────


def test_parent_alive_cmd_shape():
    cmd = orph.parent_alive_cmd(4321)
    assert "Get-Process -Id 4321" in cmd
    assert "alive" in cmd and "dead" in cmd
    # 单源静态钉兼容：本命令不含 Stop-Process（杀原语仍单点 desktop_guard）
    assert "Stop-Process" not in cmd


class _FakeTransport:
    """按 -Id 查表返回 (rc, stdout) 的假 SshTransport。"""

    def __init__(self, table, boom_pids: tuple[int, ...] = ()):
        self.table = table
        self.boom_pids = boom_pids
        self.commands: list[str] = []

    def run_command(self, command, timeout_s=None):
        self.commands.append(command)
        pid = int(re.search(r"-Id (\d+)", command).group(1))
        if pid in self.boom_pids:
            raise RuntimeError("channel stalled")
        rc, out = self.table[pid]
        return rc, out, ""


def test_parent_probe_alive_dead_unknown():
    t = _FakeTransport({10: (0, "alive\r\n"), 20: (0, "dead\n"),
                        30: (1, ""), 40: (0, "garbage")})
    probe = orph._make_parent_probe(t)
    assert probe(10) is True
    assert probe(20) is False
    assert probe(30) is None, "rc≠0=未知"
    assert probe(40) is None, "输出不可解析=未知"
    assert probe(50) is None, "表外（模拟通道异常）=未知"
    assert t.commands and all("Get-Process -Id" in c for c in t.commands)


def test_parent_probe_transport_exception_returns_none():
    t = _FakeTransport({}, boom_pids=(10,))
    probe = orph._make_parent_probe(t)
    assert probe(10) is None


# ─── 脚本壳回归钉 ─────────────────────────────────────────────────────────


def test_repo_anchor_points_at_repo_root():
    """REPO 锚定修复钉：原 parents[2]=盘根（sys.path 兜底指向不存在的
    <盘>:\\src），现 parents[1]=仓根（scripts/ 的上一级）。"""
    assert Path(__file__).resolve().parents[2] == orph.REPO
    assert (orph.REPO / "scripts" / "cleanup_server_orphans.py").is_file()


def test_fingerprint_pattern_unchanged():
    """指纹面与 ge8d 固化版一致（只修判定链，不扩杀面）。"""
    assert orph.ORPHAN_FINGERPRINT.search("blslope")
    assert orph.ORPHAN_FINGERPRINT.search(r"tasks\oe_x")
    assert orph.ORPHAN_FINGERPRINT.search("tasks/oe_x")
    assert orph.ORPHAN_FINGERPRINT.search("HFSS_SIDE_REMOTE")
    assert not orph.ORPHAN_FINGERPRINT.search("benign_job")
