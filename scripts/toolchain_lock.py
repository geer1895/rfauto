"""AX-4 工具链 lock 采集/比对脚本（aurora_r R-03；服务单源薄壳，规则 4）。

采集/比对/写盘单源在 src/rfauto/service/toolchain_service.py——本脚本只做
CLI 编排：默认采集本机工具链指纹（HFSS/ADS/openEMS/python 版本 + 关键包
版本，零敏感信息——无安装路径/凭据/主机名）写
configs/toolchain_lock.local.yaml；``--check`` 采集本机现状与 lock 逐项
比对（漂移=服务器版本≠本机，规则 0 拦截面）。

用法（从仓根执行）::

    .venv/Scripts/python.exe scripts/toolchain_lock.py             # 采集写 lock
    .venv/Scripts/python.exe scripts/toolchain_lock.py --check     # 自检比对
    .venv/Scripts/python.exe scripts/toolchain_lock.py --path <p>  # 自定落点

退出码：写模式失败=2；--check：match=0 / drift=1 / unverifiable=2 /
lock 缺失=3（诚实跳过）/ 读取失败=4。

远程流程（规则 0 机器可读门）：服务器侧在同脚本形态下产出探测 dict
（probe_toolchain 形态）回传本机后，调
service.toolchain_service.toolchain_lock_check(probed=<服务器 dict>)
得漂移清单——本脚本只覆盖本机自检形态。

挂账（本席禁改 cli/——无 CLI 正式叶）：处方=cli/domains/remote.py 增
``toolchain-lock`` 子命令消费 service 层两信封入口
（toolchain_lock_write/toolchain_lock_check），远期 MCP 工具同源。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.service.toolchain_service import (  # noqa: E402
    DEFAULT_LOCK_PATH,
    toolchain_lock_check,
    toolchain_lock_write,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="AX-4 工具链 lock 采集/比对"
                    "（configs/toolchain_lock.local.yaml）",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="不写 lock：采集本机现状与既有 lock 逐项比对（漂移=exit 1）",
    )
    parser.add_argument(
        "--path", default=None,
        help=f"lock 文件路径（缺省 {DEFAULT_LOCK_PATH.as_posix()}）",
    )
    args = parser.parse_args(argv)

    if args.check:
        result = toolchain_lock_check(lock_path=args.path)
        print(json.dumps(result, ensure_ascii=False, indent=2,
                         default=str))
        if not result.get("ok", False):
            return 4 if "errors" in result else 3
        if result.get("skipped"):
            return 3
        verdict = result.get("verdict")
        return {"match": 0, "drift": 1, "unverifiable": 2}.get(verdict, 4)

    result = toolchain_lock_write(path=args.path)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
