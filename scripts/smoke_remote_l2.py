"""L2 远程 HFSS 求解冒烟驱动薄壳（真机 opt-in）。

用法（必须显式 opt-in，unit 门零真机）::

    set RFAUTO_REMOTE_SMOKE=1
    .venv\\Scripts\\python.exe scripts\\smoke_remote_l2.py [--machine sim_host]

职责：调 service 层 ``remote_hfss_l2_smoke``（全部编排逻辑在 service，
本脚本只做 ①本机 ansysedt 计数旁证 ②verdict.json 落盘（UTF-8 显式
编码，#89）③退出码（PASS=0 / FAIL=1）。判据口径见该函数 docstring。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from rfauto.service.remote_service import remote_hfss_l2_smoke  # noqa: E402


def count_local_ansysedt() -> int:
    """本机 ansysedt 进程计数（旁证；查询失败返回 -1 不阻塞主路径）。"""
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-Process ansysedt -ErrorAction SilentlyContinue | "
             "Measure-Object).Count"],
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
        )
        return int(proc.stdout.strip() or 0)
    except Exception:
        return -1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="L2 远程 HFSS 求解冒烟（真机 opt-in：RFAUTO_REMOTE_SMOKE=1）",
    )
    parser.add_argument("--machine", default=None,
                        help="注册表机器名（缺省=唯一登记机器）")
    parser.add_argument("--grpc-wait-s", type=float, default=90.0,
                        help="gRPC 端口轮询超时秒数（缺省 90）")
    parser.add_argument("--out-dir", default=None,
                        help="产物目录（缺省 runs/remote_l2/<YYYYMMDD>）")
    args = parser.parse_args()

    local_before = count_local_ansysedt()
    print(f"[l2] 本机 ansysedt 计数（开工前）: {local_before}", flush=True)

    t0 = time.monotonic()
    out = remote_hfss_l2_smoke(
        machine=args.machine, grpc_wait_s=args.grpc_wait_s, out_dir=args.out_dir,
    )
    elapsed = time.monotonic() - t0
    local_after = count_local_ansysedt()

    out["local_ansysedt_before"] = local_before
    out["local_ansysedt_after"] = local_after
    out["wall_s"] = round(elapsed, 1)

    # 产物目录显式解析（与 service 缺省同口径）：skipped 路径也落 verdict
    # 留痕，不写到仓根（ stray 文件陷阱，#96 家族）。
    out_dir = (
        Path(args.out_dir) if args.out_dir is not None
        else REPO / "runs" / "remote_l2" / time.strftime("%Y%m%d")
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    verdict_path = out_dir / "verdict.json"
    verdict_path.write_text(
        json.dumps(out, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    print(json.dumps({
        "ok": out.get("ok"),
        "verdict": out.get("verdict"),
        "reason": out.get("reason"),
        "criteria": out.get("criteria"),
        "touchstone_local": out.get("touchstone_local"),
        "server_ansysedt_after": (out.get("steps", {}).get("cleanup", {})
                                  .get("steps", {}).get("ansysedt_after")),
        "local_ansysedt_after": local_after,
        "wall_s": out["wall_s"],
        "verdict_json": str(verdict_path),
    }, ensure_ascii=False, indent=2, default=str))

    ok = bool(out.get("ok")) and local_after == 0
    if not ok and out.get("ok"):
        print(f"[l2] 注意：verdict PASS 但本机 ansysedt 残留 {local_after} 个",
              file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
