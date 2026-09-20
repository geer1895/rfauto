"""B-27 真机证据脚本：真实 .aedt → spec → 配方草案 → 渲染往返（只读副本）。

真机安全
--------
1. 只在工程**副本**上打开（tempfile 目录），绝不 save/另存/修改用户 .aedt；
2. 独立非图形 AEDT 会话，remove_lock=False，读完 release（不保存）；
3. 硬超时：父进程看门狗在 --timeout 秒内强杀子进程树（taskkill /T），
   子进程内还有一层线程级超时先报错（--import-timeout，默认 timeout-30s）。

用法::

    .venv\\Scripts\\python.exe scripts\\hfss_import_roundtrip.py
    .venv\\Scripts\\python.exe scripts\\hfss_import_roundtrip.py --project hfss_projects\\trl_09mm_line123.aedt --version 2025.1

退出码：0=往返成功；1=失败/超时（JSON 的 error 说明原因）。
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

_DEFAULT_PROJECT = _ROOT / "hfss_projects" / "trl_09mm_line123.aedt"


def _build_payload(project: str, args: argparse.Namespace) -> dict:
    """只读导入 → 草案 → 渲染往返，汇总成可落盘的证据 dict。"""
    from rfauto.adapters.hfss_import import import_project_recipe

    result = import_project_recipe(
        project,
        args.design,
        version=args.version or None,
        non_graphical=True,
        model_name=args.model_name,
        timeout_s=args.import_timeout,
    )
    spec = result.get("spec") or {}
    validation = result.get("validation") or {}
    recipe = result.get("recipe") or {}
    return {
        "ok": bool(result.get("ok")),
        "error": result.get("error"),
        "project": project,
        "excluded_derived": result.get("excluded_derived"),
        "spec": {
            "design": spec.get("design"),
            "read_only_copy": spec.get("read_only_copy"),
            "source_locked": spec.get("source_locked"),
            "n_variables": len(spec.get("variables") or {}),
            "parametrics": spec.get("parametrics"),
            "setup": spec.get("setup"),
            "ports": spec.get("ports"),
        },
        "recipe": recipe,
        "render_roundtrip": {
            "ok": validation.get("ok"),
            "errors": validation.get("errors"),
            "warnings": validation.get("warnings"),
            "hfss_variables": validation.get("hfss_variables"),
        },
    }


def _run_worker(args: argparse.Namespace) -> int:
    payload = _build_payload(args.project, args)
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    if args.result:
        Path(args.result).write_text(text, encoding="utf-8")
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text, flush=True)
    # pyaedt 的 gRPC 线程会让解释器退不干净：结果已落盘后强制退出
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0 if payload["ok"] else 1)


def _kill_tree(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True, check=False)
    else:  # pragma: no cover - 非 Windows
        import signal

        with contextlib.suppress(ProcessLookupError):
            os.killpg(os.getpgid(pid), signal.SIGKILL)


def _run_parent(args: argparse.Namespace) -> int:
    import tempfile

    with tempfile.TemporaryDirectory(prefix="b27_roundtrip_") as tmp:
        result_path = os.path.join(tmp, "result.json")
        log_path = os.path.join(tmp, "worker.log")
        cmd = [
            sys.executable, str(Path(__file__).resolve()), "--worker",
            "--project", args.project, "--result", result_path,
            "--timeout", str(args.timeout),
            "--import-timeout", str(max(30.0, args.timeout - 30.0)),
            "--model-name", args.model_name,
        ]
        if args.design:
            cmd += ["--design", args.design]
        if args.version:
            cmd += ["--version", args.version]

        timed_out = False
        with open(log_path, "w", encoding="utf-8") as log:
            proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
            try:
                proc.wait(timeout=args.timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                _kill_tree(proc.pid)
                with contextlib.suppress(Exception):
                    proc.wait(timeout=30)

        payload = None
        if os.path.exists(result_path):
            with contextlib.suppress(Exception):
                payload = json.loads(Path(result_path).read_text(encoding="utf-8"))
        if payload is None:
            log_tail = ""
            with contextlib.suppress(Exception):
                log_tail = Path(log_path).read_text(encoding="utf-8")[-2000:]
            payload = {
                "ok": False,
                "timeout": timed_out,
                "project": args.project,
                "error": (f"子进程超时（>{args.timeout:.0f}s），已强杀进程树"
                          if timed_out else "子进程未产出结果（见 worker 日志）"),
                "worker_log_tail": log_tail,
            }

    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    return 0 if payload.get("ok") else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=str(_DEFAULT_PROJECT),
                        help="真实 .aedt 路径（只在副本上打开）")
    parser.add_argument("--design", default=None, help="设计名（多设计工程）")
    parser.add_argument("--version", default=None,
                        help="AEDT 版本（缺省自动探测本机安装）")
    parser.add_argument("--model-name", default="custom_hfss")
    parser.add_argument("--timeout", type=float, default=300.0,
                        help="硬超时秒数（父进程强杀，默认 300）")
    parser.add_argument("--import-timeout", type=float, default=270.0,
                        help="子进程内读取超时（默认 270，留收尾余量）")
    parser.add_argument("--out", default=None, help="证据 JSON 落盘路径")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--result", default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if not Path(args.project).exists():
        print(json.dumps({"ok": False, "error": f"工程文件不存在: {args.project}"},
                         ensure_ascii=False))
        return 1
    return _run_worker(args) if args.worker else _run_parent(args)


if __name__ == "__main__":
    raise SystemExit(main())
