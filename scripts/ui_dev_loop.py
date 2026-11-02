"""UI 离线开发回路（aurora_i R1 采纳 #4，hfssq-ui-kit 思想；W3.5-K3 席）。

一个极简静态服务（stdlib http.server，零新依赖）把 rfauto 前端
``src/rfauto/ui/static/`` 与 mock 数据信封拼成**无后端可跑**的 UI 开发
回路——改样式/布局/i18n 不必起真 `rfauto ui`（更不必有 runs 数据）：

    python scripts/ui_dev_loop.py                 # 起服务（缺省 8643）
    python scripts/ui_dev_loop.py --list          # 看已收录端点
    python scripts/ui_dev_loop.py --capture http://127.0.0.1:8699
                                                  # 从真 UI 采样脱敏入库

- UI 本体伺服在 ``/``（直开 ``http://127.0.0.1:<port>/``）；
- mock 信封伺服在 ``/api/<端点>``（响应带 ``X-RFAUTO-Mock: hit`` 头；
  未收录端点回 ``ok:false`` 信封 + ``X-RFAUTO-Mock: miss``——前端走
  既有错误信封呈现，不白屏）；
- 同一信封镜像伺服在 ``/mock/api/<端点>``（配前端 apiFetch 的
  ``?mock=1`` 查询参数开关——同源场景；跨源场景（任意静态伺服 +
  ``?mock=http://127.0.0.1:8643/api``）由 mock 响应的 CORS ``*`` 支持；
- mock 文件缺省 ``runs/aurora_i/ui_mock_data.json``（gitignored 证据区
  ——mock 读数不进 git、禁止当真值，纪律见 docs/how-to/ui-offline-dev.md）；
  缺失时自动落一份内置合成样例（结构照真实信封，身份全合成），
  ``--capture`` 可随时从真 UI 重采。

纪律（#122 同族）：mock 数据是**结构样例**不是物理真值——判读/文档
数字一律以真引擎/真服务产出为准。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import request as _urlrequest

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATIC = REPO_ROOT / "src" / "rfauto" / "ui" / "static"
DEFAULT_MOCK = REPO_ROOT / "runs" / "aurora_i" / "ui_mock_data.json"
DEFAULT_PORT = 8643

#: --capture 采样端点（GET；前端首屏/高频只读面，W3.5-K3 实测选点）。
CAPTURE_ENDPOINTS = (
    "runs?limit=3",
    "solvers",
    "recipes",
    "calibration",
    "metric-glossary",
)

_MOCK_HEADER = "X-RFAUTO-Mock"
_TS_FIX = "2026-10-19T00:00:00+00:00"
_RUN_ID_RE = re.compile(r"^\d{8}_\d{6}_[0-9a-f]+$")


# ── mock 信封装载与采样 ────────────────────────────────────────────────

def load_mock_map(mock_path: Path) -> dict:
    """读 mock 文件；缺失时落内置合成样例再读（返回 endpoints 映射）。"""
    if not mock_path.exists():
        sample = _builtin_sample()
        mock_path.parent.mkdir(parents=True, exist_ok=True)
        mock_path.write_text(
            json.dumps(sample, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8")
        print(f"[init] mock 文件缺失，已落内置合成样例: {mock_path}")
    data = json.loads(mock_path.read_text(encoding="utf-8"))
    eps = data.get("endpoints") if isinstance(data, dict) else None
    return eps if isinstance(eps, dict) else {}


def _sanitize(obj, counter: dict):
    """递归脱敏：run_id 合成化、timestamp 固定（结构键保形）。"""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k == "run_id" and isinstance(v, str) and _RUN_ID_RE.match(v):
                counter["n"] = counter.get("n", 0) + 1
                out[k] = f"mock_run_{counter['n']:03d}"
            elif k == "timestamp" and isinstance(v, str):
                out[k] = _TS_FIX
            else:
                out[k] = _sanitize(v, counter)
        return out
    if isinstance(obj, list):
        return [_sanitize(x, counter) for x in obj]
    return obj


def capture(base_url: str, mock_path: Path) -> int:
    """从运行中的真 UI 采样 CAPTURE_ENDPOINTS，脱敏后并入 mock 文件。"""
    base = base_url.rstrip("/")
    eps: dict = {}
    for ep in CAPTURE_ENDPOINTS:
        key = "/api/" + ep.split("?")[0]
        url = f"{base}/api/{ep}"
        with _urlrequest.urlopen(url, timeout=30) as r:
            eps[key] = _sanitize(json.loads(r.read().decode("utf-8")), {})
        print(f"[capture] {key} <- {url}")
    merged: dict = {"endpoints": {}}
    if mock_path.exists():
        try:
            merged = json.loads(mock_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            print(f"[capture] 旧 mock 文件不可解析，重建: {mock_path}")
        merged.setdefault("endpoints", {})
    merged["endpoints"].update(eps)
    merged.setdefault("_meta", {})
    merged["_meta"].update({
        "purpose": "UI 离线开发回路 mock 信封（scripts/ui_dev_loop.py --capture）",
        "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "sanitize": "run_id/timestamp 已合成化；结构键与真实信封同形",
    })
    mock_path.parent.mkdir(parents=True, exist_ok=True)
    mock_path.write_text(
        json.dumps(merged, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    print(f"[capture] {len(eps)} 端点已并入 {mock_path}")
    return 0


def _builtin_sample() -> dict:
    """内置合成样例（clean checkout 无 runs/ 时自足；结构照真实信封）。"""
    glossary = None
    try:
        from rfauto.service.metric_glossary_service import list_metric_glossary

        glossary = list_metric_glossary()  # 知识库单源（提交面，非敏感）
    except Exception:
        glossary = None  # 离线自足：rfauto 不可导入时用合成两键
    if not (isinstance(glossary, dict) and glossary.get("ok")):
        glossary = {
            "ok": True, "schema_version": "1.0", "schema": "metric-glossary/v1",
            "count": 2, "keys": ["s11_db_max_in_band", "s21_db@f0"],
            "gate_ops": ["max_below", "min_above", "abs_le", "bool_true"],
            "entries": [
                {"metric_id": "s11_db_max_in_band", "unit": "dB"},
                {"metric_id": "s21_db@f0", "unit": "dB"},
            ],
        }
    return {
        "_meta": {
            "purpose": "UI 离线开发回路内置合成样例（scripts/ui_dev_loop.py）",
            "sanitize": "全合成身份；结构键照真实信封",
        },
        "endpoints": {
            "/api/runs": {
                "ok": True,
                "runs": [
                    {"run_id": "mock_run_001", "model": "wilkinson_power_divider",
                     "adapter": "", "status": "done",
                     "timestamp": _TS_FIX, "metrics": {}},
                    {"run_id": "mock_run_002", "model": "patch_antenna",
                     "adapter": "openems", "status": "done",
                     "timestamp": _TS_FIX, "metrics": {}},
                ],
                "contract_check": {"contract": "list_runs", "ok": True,
                                   "errors": [], "schema_version": 2},
            },
            "/api/solvers": {
                "ok": True,
                "solvers": [
                    {"type": "openems", "class": "OpenEMSSolver",
                     "available": True, "n_visualizations": 0},
                    {"type": "hfss", "class": "HfssAdapter",
                     "available": False, "n_visualizations": 0},
                ],
            },
            "/api/recipes": {
                "ok": True,
                "recipes": [
                    {"path": "recipes/mock_wilkinson_v1.yaml", "kind": "original",
                     "model": "wilkinson_power_divider", "n_params": 4,
                     "n_objectives": 1, "freq_range": [2.0, 3.0]},
                ],
            },
            "/api/calibration": {
                "ok": True,
                "runs": [
                    {"run_id": "mock_cal_001", "model": "wilkinson_power_divider",
                     "adapter": "calibration:openems", "verdict": "PASS",
                     "rho": 0.9, "n_samples": 10, "n_failures": 0,
                     "mesh_resolution_mm": 0.5, "surrogate_kind": None},
                ],
            },
            "/api/metric-glossary": glossary,
        },
    }


# ── 静态+mock 复合伺服 ────────────────────────────────────────────────

def make_handler(static_dir: Path, mock_map: dict):
    """构造 handler 类：静态面走 SimpleHTTPRequestHandler 本体，
    /api（及镜像 /mock/api）走 mock 信封面。"""

    class DevLoopHandler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(static_dir), **kw)

        # 静态面默认 cache 头对开发回路偏激进——mock/页面一律 no-store，
        # 改完刷新即见（hfssq-ui-kit 同款回路手感）。
        def end_headers(self):
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def _mock_key(self, raw_path: str) -> str | None:
            """路径归一到 mock 键：/api/x 与 /mock/api/x、/mock/x → /api/x。"""
            path = raw_path.split("?", 1)[0]
            if path.startswith("/mock/"):
                path = path[len("/mock"):]
            if not path.startswith("/api/"):
                return None
            return path

        def _send_mock(self, key: str | None):
            body = mock_map.get(key) if key else None
            if body is None:
                payload = {
                    "ok": False,
                    "error": (f"mock 未收录该端点: {key or '非 /api 路径'}"
                              "（--list 查看已收录；--capture 从真 UI 采样）"),
                    "errors": ["mock_miss"],
                }
                code, mark = 404, "miss"
            else:
                payload, code, mark = body, 200, "hit"
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type",
                             "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header(_MOCK_HEADER, mark)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(raw)
            print(f"[mock] {self.command} {self.path} -> {mark}")

        def do_GET(self):
            key = self._mock_key(self.path)
            if key is not None or self.path.startswith("/mock/api"):
                self._send_mock(key)
                return
            super().do_GET()

        def do_POST(self):
            if self._mock_key(self.path) is not None:
                raw = json.dumps({
                    "ok": False,
                    "error": "mock 通道仅伺服 GET 采样信封；写端点请起真 rfauto ui",
                    "errors": ["mock_get_only"],
                }).encode("utf-8")
                self.send_response(405)
                self.send_header("Content-Type",
                                 "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header(_MOCK_HEADER, "post-rejected")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(raw)
                return
            self.send_error(404, "dev loop only serves static + mock GET")

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers",
                             "Authorization, Content-Type")
            self.end_headers()

        def log_message(self, fmt, *args):  # 静态面降噪：静默默认访问日志
            pass

    return DevLoopHandler


def serve(port: int, static_dir: Path, mock_map: dict) -> int:
    handler = make_handler(static_dir, mock_map)
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    print(f"[dev-loop] UI 本体   http://127.0.0.1:{port}/  (static={static_dir})")
    print(f"[dev-loop] mock 通道 http://127.0.0.1:{port}/api/<端点>"
          f"  (镜像 /mock/api/<端点>)")
    print(f"[dev-loop] 已收录 {len(mock_map)} 端点: {', '.join(sorted(mock_map))}")
    print("[dev-loop] Ctrl+C 停止；mock 读数是结构样例，禁止当真值判读")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[dev-loop] bye")
    finally:
        server.server_close()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="rfauto UI 离线开发回路（静态前端 + mock 信封伺服）")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT,
                    help=f"监听端口（缺省 {DEFAULT_PORT}）")
    ap.add_argument("--static", default=str(DEFAULT_STATIC),
                    help="前端静态目录（缺省 src/rfauto/ui/static）")
    ap.add_argument("--mock", default=str(DEFAULT_MOCK),
                    help="mock 信封文件（缺省 runs/aurora_i/ui_mock_data.json）")
    ap.add_argument("--capture", metavar="BASE_URL", default=None,
                    help="从运行中的真 UI（如 http://127.0.0.1:8699）采样"
                         "脱敏并入 mock 文件后退出（不起服务）")
    ap.add_argument("--list", action="store_true",
                    help="列出 mock 已收录端点后退出")
    args = ap.parse_args(argv)

    mock_path = Path(args.mock)
    if args.capture:
        return capture(args.capture, mock_path)
    mock_map = load_mock_map(mock_path)
    if args.list:
        for k in sorted(mock_map):
            env = mock_map[k]
            hint = env.get("ok", "-") if isinstance(env, dict) else "-"
            print(f"{k}  (ok={hint})")
        return 0
    static_dir = Path(args.static)
    if not (static_dir / "index.html").exists():
        print(f"[dev-loop] 静态目录缺 index.html: {static_dir}", file=sys.stderr)
        return 2
    return serve(args.port, static_dir, mock_map)


if __name__ == "__main__":
    raise SystemExit(main())
