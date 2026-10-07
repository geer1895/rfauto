"""ADS 网表远跑冒烟驱动薄壳（真机 opt-in：RFAUTO_REMOTE_SMOKE=1）。

判据（预声明，#122——任何一项不过=FAIL 如实附数字）::

    c1 通道 ok=True：hpeesofsim 服务器侧 rc==0（rc 经 PowerShell
       ``exit $LASTEXITCODE`` 透传，exe 缺失/pre-check 失败=rc 3/1）；
    c2 数据集回拉在档且文件数 ≥1（<网表全名>.ds 本地镜像非空；hpeesofsim 以网表全名含扩展名命名数据集）；
    c3 服务器侧批次工作目录已清理（Remove-Item 后 Test-Path 复核=False；
       keep_remote=True 时如实记 skipped 不判 PASS）。

用法（unit 门零真机，必须显式 opt-in）::

    set RFAUTO_REMOTE_SMOKE=1
    .venv\\Scripts\\python.exe scripts\\smoke_remote_ads.py ^
        --netlist <自包含网表路径> [--machine sim_host]

职责：调 service 层 ``remote_ads_run``（编排/判据全在 service，家法照
smoke_remote_l2.py），本脚本只做 ①verdict json 落盘（UTF-8 显式编码，
#89）②退出码（PASS=0 / FAIL=1）。网表要求：自包含或相对依赖随仓在档
（File= 绝对路径会被 #276 检查显式拒绝）。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from rfauto.service.remote_ads_service import remote_ads_run  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "ADS 网表远跑冒烟（真机 opt-in：RFAUTO_REMOTE_SMOKE=1；"
            "判据 c1 rc==0 / c2 数据集回拉非空 / c3 服务器侧已清理）"
        ),
    )
    parser.add_argument("--netlist", required=True,
                        help="本地网表文件路径（自包含或相对依赖在档）")
    parser.add_argument("--machine", default=None,
                        help="注册表机器名（缺省=唯一登记机器）")
    parser.add_argument("--out-dir", default=None,
                        help="回拉产物目录（缺省 runs/remote_ads/<YYYYMMDD>）")
    parser.add_argument("--batch-name", default=None,
                        help="批次目录名（缺省 ads_<uuid8> 唯一化）")
    parser.add_argument("--dataset-stem", default=None,
                        help="数据集名覆盖（缺省=网表文件名主干）")
    parser.add_argument("--exec-timeout-s", type=float, default=600.0,
                        help="同步执行等待上限秒数（缺省 600）")
    parser.add_argument("--extra-files", nargs="*", default=None,
                        help="额外随传文件（平铺进批次目录）")
    parser.add_argument("--keep-remote", action="store_true",
                        help="跳过服务器侧清理（调试留档；任务毕须人工清理）")
    args = parser.parse_args()

    t0 = time.monotonic()
    out = remote_ads_run(
        args.netlist,
        args.machine,
        out_dir=args.out_dir,
        batch_name=args.batch_name,
        dataset_stem=args.dataset_stem,
        exec_timeout_s=args.exec_timeout_s,
        extra_files=args.extra_files,
        keep_remote=args.keep_remote,
    )
    out["wall_s"] = round(time.monotonic() - t0, 1)

    # 判据终判（service 已算，驱动只复核三件齐全后出退出码）
    c = out.get("criteria", {})
    c1 = bool(c.get("c1_rc0")) and out.get("exec_rc") == 0
    c2 = bool(c.get("c2_dataset_nonempty"))
    c3 = bool(c.get("c3_workdir_cleaned")) and not args.keep_remote
    out["smoke_criteria"] = {"c1_rc0": c1, "c2_dataset_nonempty": c2,
                             "c3_workdir_cleaned": c3}
    verdict = "PASS" if (c1 and c2 and c3) else "FAIL"

    out_dir = (
        Path(args.out_dir) if args.out_dir is not None
        else REPO / "runs" / "remote_ads" / time.strftime("%Y%m%d")
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    batch = out.get("batch") or "skip"
    verdict_path = out_dir / f"verdict_{batch}.json"
    verdict_path.write_text(
        json.dumps(out, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    print(json.dumps({
        "verdict": verdict,
        "ok": out.get("ok"),
        "reason": out.get("reason"),
        "machine": out.get("machine"),
        "batch": batch,
        "exec_rc": out.get("exec_rc"),
        "dataset_local": out.get("dataset_local"),
        "cleanup": out.get("steps", {}).get("cleanup"),
        "smoke_criteria": out["smoke_criteria"],
        "wall_s": out["wall_s"],
        "verdict_json": str(verdict_path),
    }, ensure_ascii=False, indent=2, default=str))

    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
