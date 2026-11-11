"""aurora_n 远程探测面板回归钉（/api/remote/status + #q-remote-probe 块）。

覆盖面（全离线，#139：探活/SSH 通道一律 monkeypatch 桩钉死，绝不真连网；
node 行为钉缺 node skip）：

1. UI 端点薄壳契约（TestClient）：
   - stub ``remote_status`` → 信封逐键透传（规则 4 薄壳：handler 零逻辑）；
   - ``?machine=`` 参数转发（无参=None 语义）；
   - 真服务链（stub ``load_remote_machines``/``probe_machine``/``_ssh_status``
     ——facade setattr 扇出）：无登记机器=machines[] 如实、登记机器=探活
     端口表+SSH 认证态透传、未知机器名=error 信封（非 500）；
   - **零凭据回显**（递归扫信封键：password/secret/token 族恒缺席——
     env 变量名出现在 hint 文案属指引非凭据，放行）。
2. JS 纯函数行为钉（node 真执行）：probePortBadge 三态 / probePortRowHtml
   （OPEN 带时延 / CLOSED 无时延 / XSS 插值转义）/ probeIssueKind 六路分型。
3. 源码钉（免 node）：路由注册与 re-export 同一性（#116）、线程池卸载、
   ✗ 豁免点恒 1（不可达红字不带 ✗ 字面）、setInterval 联合计数不被本席
   触碰（零自动轮询的源码面）、探测块接线（容器/请求字面量/手动刷新）。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

src_dir = Path(__file__).resolve().parents[2] / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from starlette.testclient import TestClient

import rfauto.service.remote_service as rsvc
from rfauto.ui.server import create_ui_app

_STATIC = Path(__file__).resolve().parents[2] / "src" / "rfauto" / "ui" / "static"
_QUEUE = _STATIC / "pages" / "view_queue.js"
_NODE = shutil.which("node")

# lab_server 注册表实况五端口形态（configs/remote_machines.yaml 语义名+号）；
# open/latency 为桩值——形态（键集/子键）与服务契约逐键对齐。
_PROBE_PORTS = {
    "ssh": {"port": 22, "open": True, "latency_ms": 1.2},
    "rdp": {"port": 3389, "open": True, "latency_ms": 0.9},
    "ansys_license": {"port": 1055, "open": True, "latency_ms": 1.1},
    "ads_license": {"port": 27009, "open": False, "latency_ms": 3001.4},
    "smb": {"port": 445, "open": True, "latency_ms": 1.0},
}


def _probe_row(**kw) -> dict:
    """remote_status 信封 machines[0] 实况形态基线（零凭据字段）。"""
    row = {
        "name": "lab_server",
        "host": "192.0.2.10",
        "reachable": True,
        "probe_s": 0.05,
        "ports": dict(_PROBE_PORTS),
        "ssh": {"auth": "missing_credentials",
                "hint": "设置 RFAUTO_REMOTE_SSH_USER/RFAUTO_REMOTE_SSH_PASSWORD"
                        " 或 configs/remote_machines.local.yaml（ssh_user/ssh_key_path）"},
    }
    row.update(kw)
    return row


@pytest.fixture()
def client():
    return TestClient(create_ui_app())


# ─── UI 端点薄壳契约（TestClient） ───────────────────────────────────────────

class TestEndpointThinShell:
    def test_probe_envelope_passthrough(self, client, monkeypatch):
        """薄壳直渲染：stub 服务返回 → 响应逐键透传（handler 零加工）。"""
        payload = {"ok": True, "machines": [_probe_row()]}
        monkeypatch.setattr(rsvc, "remote_status", lambda machine=None: payload)
        r = client.get("/api/remote/status")
        assert r.status_code == 200
        assert r.json() == payload

    def test_machine_query_forwarded(self, client, monkeypatch):
        """?machine= 转发：显式名原样、无参=None（缺省=唯一登记机器语义）。"""
        seen: list = []
        monkeypatch.setattr(
            rsvc, "remote_status",
            lambda machine=None: (seen.append(machine), {"ok": True,
                                                        "machines": []})[1])
        client.get("/api/remote/status?machine=lab_server")
        assert seen[-1] == "lab_server"
        client.get("/api/remote/status")
        assert seen[-1] is None

    def test_no_registered_machines_real_service_path(self, client,
                                                      monkeypatch):
        """真服务链（无网络）：注册表空 → machines=[] 如实（零配置零行为）。"""
        monkeypatch.setattr(rsvc, "load_remote_machines", lambda *a, **k: {})
        r = client.get("/api/remote/status").json()
        assert r["ok"] is True and r["machines"] == []

    def test_real_path_ports_and_ssh_passthrough(self, client, monkeypatch):
        """真服务链（探活/SSH 桩）：五端口表+SSH 认证态逐键透传（面板数据源）。"""
        monkeypatch.setattr(
            rsvc, "load_remote_machines",
            lambda *a, **k: {"lab_server": SimpleNamespace()})
        monkeypatch.setattr(
            rsvc, "probe_machine",
            lambda cfg, **k: {"name": "lab_server",
                              "host": "192.0.2.10",
                              "reachable": True, "ports": dict(_PROBE_PORTS),
                              "probe_s": 0.05})
        monkeypatch.setattr(
            rsvc, "_ssh_status",
            lambda cfg: {"auth": "missing_credentials", "hint": "hint-text"})
        r = client.get("/api/remote/status").json()
        assert r["ok"] is True
        m = r["machines"][0]
        assert m["name"] == "lab_server" and m["reachable"] is True
        assert set(m["ports"]) == set(_PROBE_PORTS)
        assert m["ports"]["ads_license"]["open"] is False
        assert m["ssh"]["auth"] == "missing_credentials"

    def test_unknown_machine_error_envelope_not_500(self, client, monkeypatch):
        """未知机器名：RemoteConfigError → error 信封（resources_panel_view
        同口径；HTTP 200 + ok=False，不 500 不裸 traceback）。"""
        monkeypatch.setattr(
            rsvc, "load_remote_machines",
            lambda *a, **k: {"lab_server": SimpleNamespace()})
        r = client.get("/api/remote/status?machine=nope")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is False
        assert body["errors"] and "未登记" in body["errors"][0]

    def test_envelope_zero_credentials(self, client, monkeypatch):
        """零凭据回显：信封递归扫键，凭据族键恒缺席（env 变量名出现在
        hint 文案属指引非凭据；service 不猜不试契约的 UI 面复核）。"""
        monkeypatch.setattr(rsvc, "remote_status",
                            lambda machine=None: {"ok": True,
                                                  "machines": [_probe_row()]})
        body = client.get("/api/remote/status").json()

        def _scan(node) -> None:
            if isinstance(node, dict):
                for k, v in node.items():
                    kl = str(k).lower()
                    assert not any(
                        bad in kl for bad in
                        ("password", "secret", "token", "private_key")), k
                    _scan(v)
            elif isinstance(node, list):
                for v in node:
                    _scan(v)

        _scan(body)


# ─── 端点装配钉（路由注册/线程池） ───────────────────────────────────────────

class TestEndpointWiring:
    def test_reexport_is_identity(self):
        """server 薄 re-export 同一对象（#116 教训：只透传不重定义）。"""
        from rfauto.ui import campaign_app, server

        assert server.api_remote_status is campaign_app.api_remote_status

    def test_route_registered(self):
        server_src = (Path(__file__).resolve().parents[2] / "src" / "rfauto"
                      / "ui" / "server.py").read_text(encoding="utf-8")
        assert 'Route("/api/remote/status", api_remote_status)' in server_src

    def test_probe_chain_off_event_loop(self):
        """同步探测链下沉线程池（TCP×5+SSH echo 最坏 45s 级不得停摆事件循环
        ——api_remote_resources 同款形态源码钉）。钉调用形态 ``await
        run_in_threadpool(``（只查 import 行会被"调用点摘除"变异穿透——
        M6 实证：import 字面幸存而调用改直连仍过弱钉，收紧到 await 调用）。"""
        import inspect

        from rfauto.ui import campaign_app

        assert inspect.iscoroutinefunction(campaign_app.api_remote_status)
        src = inspect.getsource(campaign_app.api_remote_status)
        assert "await run_in_threadpool(" in src
        assert "remote_status" in src


# ─── JS 纯函数行为钉（node 真执行） ──────────────────────────────────────────

def _run_node_js(js: str) -> str:
    r = subprocess.run(
        [_NODE, "--input-type=module", "-e", js],
        capture_output=True, text=True, timeout=60, cwd=str(_STATIC),
    )
    assert r.returncode == 0, f"node 执行失败:\n{r.stderr[-2500:]}"
    return r.stdout


@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestJsProbePins:
    def test_probe_port_badge_threestate(self):
        out = _run_node_js(
            "const m = await import('./pages/view_queue.js');\n"
            "const errs = [];\n"
            "if (m.probePortBadge(true) !== \"<span class='badge ok'>OPEN</span>\")"
            " errs.push('open');\n"
            "if (m.probePortBadge(false) !== \"<span class='badge err'>CLOSED</span>\")"
            " errs.push('closed');\n"
            "for (const bad of [undefined, null, 'yes', 1, 0])\n"
            "  if (m.probePortBadge(bad) !== \"<span class='badge muted'>—</span>\")"
            " errs.push('unk:' + bad);\n"
            "if (errs.length) throw new Error(errs.join('; '));\n"
            "console.log('ok:badge');\n")
        assert "ok:badge" in out

    def test_probe_port_row_html(self):
        out = _run_node_js(
            "const m = await import('./pages/view_queue.js');\n"
            "const errs = [];\n"
            "let r = m.probePortRowHtml('ssh', 22, true, 1.234);\n"
            "if (!r.includes('<td>ssh</td>') || !r.includes('<td>22</td>') ||"
            " !r.includes('OPEN</span>') || !r.includes('<td>1.2ms</td>'))"
            " errs.push('open:' + r);\n"
            "r = m.probePortRowHtml('rdp', 3389, false, 3001.4);\n"
            "if (!r.includes('CLOSED') || r.includes('ms</td>'))"
            " errs.push('closed:' + r);\n"
            "r = m.probePortRowHtml('x', 1, null, 5);\n"
            "if (!r.includes('muted') || r.includes('ms</td>'))"
            " errs.push('unk:' + r);\n"
            "r = m.probePortRowHtml('<img src=x onerror=alert(1)>', 22, true, 1);\n"
            "if (r.includes('<img') || !r.includes('&lt;img')) errs.push('xss:' + r);\n"
            "r = m.probePortRowHtml(null, null, false, null);\n"
            "if (!r.includes('<td></td>')) errs.push('null:' + r);\n"
            "if (errs.length) throw new Error(errs.join('; '));\n"
            "console.log('ok:row');\n")
        assert "ok:row" in out

    def test_probe_issue_kind_six_way(self):
        out = _run_node_js(
            "const m = await import('./pages/view_queue.js');\n"
            "const errs = [];\n"
            "const k = (a, b, c) => m.probeIssueKind(a, b, c);\n"
            "if (k(false, null, null) !== 'no_machine') errs.push('no_machine');\n"
            "if (k(true, false, 'missing_credentials') !== 'unreachable')"
            " errs.push('prec');\n"
            "if (k(true, true, 'missing_credentials') !== 'ssh_missing')"
            " errs.push('ssh_missing');\n"
            "if (k(true, true, 'failed') !== 'ssh_failed') errs.push('ssh_failed');\n"
            "if (k(true, true, 'ok') !== 'ok') errs.push('ok');\n"
            "if (k(true, null, 'ok') !== 'unknown') errs.push('unknown');\n"
            "if (errs.length) throw new Error(errs.join('; '));\n"
            "console.log('ok:kind');\n")
        assert "ok:kind" in out

    def test_node_check_view_queue(self):
        r = subprocess.run([_NODE, "--check", str(_QUEUE)],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, f"node --check view_queue.js:\n{r.stderr[-2000:]}"

    def test_i18n_probe_keys_bilingual(self):
        keys = [
            "queue.probe_title", "queue.probe_refresh", "queue.probe_refreshing",
            "queue.probe_refresh_aria", "queue.probe_loading_aria",
            "queue.probe_th_port", "queue.probe_th_num", "queue.probe_th_state",
            "queue.probe_th_latency", "queue.probe_probe_s_tpl",
            "queue.probe_ssh_lead", "queue.probe_ssh_ok",
            "queue.probe_ssh_registered", "queue.probe_ssh_missing",
            "queue.probe_ssh_failed", "queue.probe_unreachable",
            "queue.probe_cli_hint", "queue.probe_table_caption",
            "queue.probe_no_ports",
        ]
        out = _run_node_js(
            "const m = await import('./pages/i18n.js');\n"
            "const want = " + json.dumps(keys) + ";\n"
            "const errs = [];\n"
            "for (const k of want) {\n"
            "  const e = m.LOCALES[k];\n"
            "  if (!e || typeof e.zh !== 'string' || !e.zh) errs.push('zh:' + k);\n"
            "  if (!e || typeof e.en !== 'string' || !e.en) errs.push('en:' + k);\n"
            "}\n"
            "if (errs.length) throw new Error(errs.join('; '));\n"
            "console.log('ok:keys:' + want.length);\n")
        assert "ok:keys:19" in out


# ─── 源码钉（免 node；跨席计数钉与合流面） ────────────────────────────────────

class TestSourcePins:
    def test_queue_x_exempt_site_count_unchanged(self):
        """✗ 豁免点恒 1（跨席计数钉）——不可达红字不带 ✗ 字面（badge 形态
        res_reach_bad 既有豁免例外同 W2-S4；本席新增红字面走纯色 span）。"""
        q = _QUEUE.read_text(encoding="utf-8")
        assert q.count("color:var(--err)'>✗") == 1

    def test_no_new_timer_zero_polling(self):
        """零自动轮询（源码面）：pages/ 全域 setInterval 联合计数不被本席
        触碰（本探测块零定时器——刷新只走显式按钮）。"""
        union = "\n".join(
            p.read_text(encoding="utf-8")
            for p in sorted((_STATIC / "pages").glob("*.js")))
        assert union.count("setInterval(") == 2

    def test_probe_block_wiring(self):
        """探测块接线：容器/请求字面量（含 "?"，契约门归一口径）/页载拉取/
        手动刷新钮/kitBtnBusy 单源/纯函数导出全在位。"""
        q = _QUEUE.read_text(encoding="utf-8")
        assert "id='q-remote-probe'" in q
        assert '"/api/remote/status?"' in q
        assert "loadProbe(); // aurora_n" in q
        assert "kitBtnBusy" in q
        assert "export function probePortBadge(" in q
        assert "export function probePortRowHtml(" in q
        assert "export function probeIssueKind(" in q
        assert "_probeBusy" in q  # 在飞守卫（防双击并发重复打服务器）

    def test_probe_failure_state_honest_source(self):
        """失败态诚实（源码面）：不可达红字 + CLI 指路 + 无机器如实行。"""
        q = _QUEUE.read_text(encoding="utf-8")
        assert 't("queue.probe_unreachable")' in q
        assert 't("queue.probe_cli_hint")' in q
        assert 't("queue.res_no_machine")' in q  # 无登记机器复用既有键
        assert "var(--err)" in q  # 红字面（unreachable 分支）

    def test_w2s4_merge_surface_intact(self):
        """W2-S4 资源面板同文件共存（合流双向钉——本席增量不碰既有面）。"""
        q = _QUEUE.read_text(encoding="utf-8")
        assert "id='q-resources'" in q
        assert '"/api/remote/resources?"' in q
        assert "function renderResPanel()" in q
        assert "export const RES_STALE_S = 120;" in q

    def test_handler_error_envelope_source(self):
        """handler 错误路径源码钉：RemoteConfigError → error_envelope
        （未知机器名不 500；信封语义与 resources_panel_view 同族）。"""
        src = (Path(__file__).resolve().parents[2] / "src" / "rfauto" / "ui"
               / "campaign_app.py").read_text(encoding="utf-8")
        assert "except RemoteConfigError as exc:" in src
        assert "error_envelope" in src


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
