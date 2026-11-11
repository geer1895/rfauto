"""devtest：按变更面选择受影响测试并并行执行（aurora_m W2-1 成品）。

    python scripts/devtest.py --changed|--changed-src [--dry-run] [--workers N]
                              [--scope direct|closed] [--lf | --ff]
                              [--staged | --base REF] [-- devtest 透传参数]

流程：git diff 取变更 src 文件（默认 HEAD=工作树+暂存合并视图；--staged 只看暂存；
--base REF 对比指定基线）→ 查 runs/aurora_m/impact_map.yaml 受影响测试清单 →
xdist -n <workers> 并行执行。--dry-run 只打印清单与统计不执行 pytest；`--` 之后的
参数原样透传给 pytest（如 -- -k fast）。

--changed-src（Q-X17 补注册，aurora_q Q-X8 遗留）：与 --changed 同一选择面的
显式 src-only 旗标——只映射 src/ 变更文件的测试面，tests 面自身变更永不进
选择面（映射源本就只收 src/rfauto），并打印被排除的 tests 变更清单使排除面
可见。背景：Q-X8 实测该旗标名未注册时被 parse_known_args 漏进 pytest extra，
pytest 当用法错 exit 4——现注册为正式旗标（未注册旗标漏进 extra 的形态对
任何新旗标名都成立，新旗标必须先在此注册）。

scope 口径：
  direct（缺省）= import 直连 + grep 命中，不做 src 传递闭包——开发循环粒度
    （已知案例：改 runs_verify_service.py → 9 个测试文件，与 2026-10 人工实测 ≈7 量级对齐；
    对比 closed 口径同文件 1069 个——接近全量，只适合合流/预检）；
  closed = 全量传递闭包（宁多勿漏）——hub 模块可达上千文件，真跑前想清楚。

映射新鲜度（W2-1 内容指纹，不再看 git_head——docs-only 提交不再触发重建）：
  指纹=runs/aurora_m/.impact_map_fingerprint.json（全部输入文件 size+mtime+sha256，
  含 builder 自身哈希）。direct 口径只查 tests 面内容+src 键集（direct 映射由 tests
  内容与 src 路径集决定，与 src 内容无关——改 src 代码不触发 80s 重建）；closed 口径
  另查 src 内容（传递闭包随 import 图变）。过期自动调 scripts/build_impact_map.py
  再生；指纹缺失视为过期（删指纹文件即可强制再生，或 builder --force）。

失败缓存模式（W2-2，席位循环迭代红测用）：
  --lf 只重跑上次失败的用例；--ff 先跑上次失败的再跑其余。缓存目录缺省隔离到
  runs/aurora_m/.pytest_cache_devtest（gitignored），不污染仓库根 .pytest_cache，
  也不影响全量门——门脚本自带 -p no:cacheprovider，读写都不经过本缓存。
  --no-cache 关闭隔离注入（沿用 pytest 缺省缓存位置）；--cache-dir 自定目录。

并行纪律（AGENTS.md / aurora_m PLAN §6）：worker 探底不探顶（挂死前科：
8w→20 进程 10.4GB 零计算），缺省 4，硬顶 8；禁与全量终门、重型构建并行真跑。
真跑前打印将跑的文件清单与 worker 数；>150 个测试自动走 pytest @argsfile 通道
（Windows 命令行上限：cmd.exe 8191 字符 / CreateProcess 32767 字符）。

exit code：
  0 = 无 src 变更 / 映射无受影响测试 / dry-run / pytest 全绿
  1 = pytest 有失败（测试红）
  2 = 用法错（参数错、pytest usage 错、选择清单无一可收集）
  3 = 运行异常（pytest 被中断 / 内部错误 / 映射不可用）
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
BUILDER = REPO / "scripts" / "build_impact_map.py"
DEFAULT_MAP = REPO / "runs" / "aurora_m" / "impact_map.yaml"
SECTION = {"direct": "modules_direct", "closed": "modules"}
# 探底不探顶：xdist worker 数从 4 起步，禁止一次开满（AGENTS 红线；8 为硬顶——
# 用户并行纪律：xdist 挂死前科 8w→20 进程 10.4GB，实现类长任务并发上限 3-4）
DEFAULT_WORKERS = 4
MAX_WORKERS = 8
# Windows CreateProcess 命令行上限 32767 字符（cmd.exe 层 8191）；closed 口径 hub 模块
# 1069 文件 ≈ 43k 字符必超，>150 个测试文件一律走 pytest @argsfile 通道（pytest 原生支持）
ARGSFILE_THRESHOLD = 150
DEFAULT_CACHE_DIR = "runs/aurora_m/.pytest_cache_devtest"


def _git(args: list[str]) -> str:
    run = subprocess.run(["git", *args], cwd=str(REPO), capture_output=True, text=True)
    if run.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} 失败：{run.stderr.strip()}")
    return run.stdout


def _head() -> str:
    return _git(["rev-parse", "HEAD"]).strip()


def _changed_src(staged: bool, base: str | None) -> list[str]:
    """git diff 变更 src/rfauto 下 .py 清单（POSIX 相对路径，删除/新增均含）。"""
    spec = ["--cached"] if staged else ([base] if base else ["HEAD"])
    out = _git(["diff", "--name-only", "-z", *spec])
    return sorted(
        {
            p.replace("\\", "/")
            for p in out.split("\0")
            if p and p.replace("\\", "/").startswith("src/rfauto/") and p.endswith(".py")
        }
    )


def _changed_tests(staged: bool, base: str | None) -> list[str]:
    """git diff 变更 tests 面下 .py 清单（--changed-src 排除面报告用；
    与 _changed_src 同一 diff 视图，仅前缀过滤不同）。"""
    spec = ["--cached"] if staged else ([base] if base else ["HEAD"])
    out = _git(["diff", "--name-only", "-z", *spec])
    return sorted(
        {
            p.replace("\\", "/")
            for p in out.split("\0")
            if p and p.replace("\\", "/").startswith("tests/") and p.endswith(".py")
        }
    )


def _ensure_map(map_path: Path, scope: str) -> str:
    """确保映射对 scope 口径新鲜；返回过期原因（""=指纹新鲜，未做任何重建）。

    指纹逻辑单源在 build_impact_map（check_fresh）；再生走 builder 子进程
    （含 --force 复用：结构异常时强制）。"""
    import build_impact_map as bim  # 惰性导入：同目录 helper，指纹格式/新鲜度判定单源

    fp_path = bim.default_fingerprint_path(map_path)
    stored: object = None
    if fp_path.exists():
        try:
            stored = json.loads(fp_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            stored = None
    reason = bim.check_fresh(stored, map_path, scope=scope)
    if reason:
        print(f"[devtest] 映射过期（{reason}）→ 调 build_impact_map.py 再生…")
        run = subprocess.run([sys.executable, str(BUILDER), "--out", str(map_path)], cwd=str(REPO))
        if run.returncode != 0:
            raise SystemExit("impact_map 再生失败")
    return reason


def _load_yaml_full(map_path: Path) -> dict | None:
    """全量 YAML 兜底（快径提取失败时；有 libyaml 用 CSafeLoader ~1.6s，否则 SafeLoader）。"""
    loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    try:
        data = yaml.load(map_path.read_text(encoding="utf-8"), Loader=loader)
    except (yaml.YAMLError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _extract_section_lines(
    map_path: Path, section: str, wanted: set[str]
) -> dict[str, list[str]] | None:
    """行级提取 safe_dump 产物中 section 里 wanted 键的测试清单（24MB 全量解析 12.8s → 快径）。

    产物格式（build_impact_map yaml.safe_dump 输出）：section 顶层键在第 0 列；src 键
    2 空格缩进 `  src/...py:`；测试项 `  - tests/...`；空列表键 `  src/...py: []`。
    任何不符合预期的行形态 → 返回 None（调用方回退全量 YAML 解析，宁慢勿错）。
    """
    hits: dict[str, list[str]] = {}
    in_section = False
    seen_key = False  # section 首行必须是键（值是 mapping 不是 list）
    current: str | None = None  # 仅 wanted 键非 None；非 wanted 键的列表项直接跳过
    try:
        with map_path.open(encoding="utf-8") as fh:
            for raw in fh:
                line = raw.rstrip("\n")
                if not in_section:
                    if line == f"{section}:":
                        in_section = True
                    continue
                if line and not line[0].isspace():
                    break  # 下一顶层键 → section 结束
                if not line:
                    return None  # section 内不应有空行
                if line.startswith("  - "):
                    if not seen_key:
                        return None  # 键行尚未出现 → 值形态不是本映射约定
                    if current is not None:
                        hits[current].append(line[4:])
                    continue
                if line.startswith("  ") and not line.startswith("   "):
                    key_line = line[2:]
                    if key_line.endswith(":"):
                        key = key_line[:-1]
                    elif key_line.endswith(": []"):
                        key = key_line[:-4]
                    else:
                        return None
                    current = key if key in wanted else None
                    seen_key = True
                    if current is not None:
                        hits.setdefault(current, [])
                    continue
                return None  # 更深缩进/折行等非预期形态
    except OSError:
        return None
    return hits if in_section else None


def _select(data: dict, changed: list[str], scope: str) -> tuple[list[str], list[str], dict[str, int]]:
    """全量 YAML 兜底路径的选择（与快径同语义：缺键=未入映射，空列表=零覆盖）。"""
    section = data.get(SECTION[scope])
    if not isinstance(section, dict):
        return [], [], {}  # 交给调用方的结构异常处理（强制再生）
    tests: set[str] = set()
    not_in_map: list[str] = []
    per_file: dict[str, int] = {}
    for src in changed:
        hit = section.get(src)
        if hit is None:
            not_in_map.append(src)
            continue
        per_file[src] = len(hit)
        tests.update(hit)
    return sorted(tests), not_in_map, per_file


def _get_selection(
    map_path: Path, scope: str, changed: list[str]
) -> tuple[list[str], list[str], dict[str, int]]:
    """选择受影响测试：快径行提取 → 全量 YAML 兜底 → 结构异常强制再生一次 → 仍坏则退出。"""
    section = SECTION[scope]
    for attempt in (1, 2):
        hits = _extract_section_lines(map_path, section, set(changed))
        if hits is not None:
            per_file = {k: len(v) for k, v in hits.items()}
            not_in_map = [s for s in changed if s not in hits]
            tests: set[str] = set()
            for v in hits.values():
                tests.update(v)
            return sorted(tests), not_in_map, per_file
        data = _load_yaml_full(map_path)
        tests, not_in_map, per_file = _select(data or {}, changed, scope)
        if data is not None and isinstance(data.get(section), dict):
            return tests, not_in_map, per_file
        if attempt == 1:
            print(f"[devtest] 映射结构异常（缺 {section} 段/解析失败）→ --force 再生…")
            run = subprocess.run(
                [sys.executable, str(BUILDER), "--out", str(map_path), "--force"], cwd=str(REPO)
            )
            if run.returncode != 0:
                raise SystemExit("impact_map 再生失败")
    raise SystemExit(f"impact_map.yaml 缺少 {section} 段且再生后仍缺，请人工检查")


def _run_pytest(
    tests: list[str], workers: int, extra: list[str], cache_dir: str, isolate_cache: bool
) -> int:
    """组装并执行 pytest；返回 devtest 口径 exit code（0/1/2/3，见模块 docstring）。"""
    args = [sys.executable, "-m", "pytest"]
    args_file: str | None = None
    if len(tests) > ARGSFILE_THRESHOLD:  # 超 Windows 命令行安全余量 → pytest 原生 @argsfile
        with tempfile.NamedTemporaryFile(
            "w", suffix=".txt", prefix="devtest_args_", delete=False, encoding="utf-8"
        ) as fh:
            fh.write("\n".join(tests))
            args_file = fh.name
        args.append(f"@{args_file}")
        print(
            f"[devtest] {len(tests)} 个测试 > {ARGSFILE_THRESHOLD} → @argsfile 通道"
            f"（Windows 命令行上限：cmd 8191 / CreateProcess 32767 字符，{len(tests)} 个路径必超）"
        )
    else:
        args.extend(tests)
    args += ["-n", str(workers)]
    if isolate_cache:
        args += ["-o", f"cache_dir={cache_dir}"]  # W2-2：缓存隔离到 runs/，不碰仓库根 .pytest_cache
    args += extra
    print(f"[devtest] pytest -n {workers}（探底不探顶，硬顶 {MAX_WORKERS}；勿与终门/重型构建并行）")
    try:
        rc = subprocess.call(args, cwd=str(REPO))
    finally:
        if args_file:
            Path(args_file).unlink(missing_ok=True)
    if rc == 0:
        return 0
    if rc == 1:
        return 1
    if rc in (4, 5):
        print(f"[devtest] pytest exit {rc}（{'用法/参数错' if rc == 4 else '未收集到任何用例'}）→ 按 exit 2 报告")
        return 2
    print(f"[devtest] pytest exit {rc}（中断/内部错误）→ 按 exit 3 报告")
    return 3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="按变更面选择受影响测试并并行执行（映射：runs/aurora_m/impact_map.yaml）",
        epilog="exit code：0=无事可做/全绿；1=测试红；2=用法错；3=运行异常。详见模块 docstring。",
    )
    parser.add_argument("--changed", action="store_true", help="按 git diff 变更 src 文件选择受影响测试")
    parser.add_argument(
        "--changed-src",
        action="store_true",
        help=(
            "显式 src-only 口径（与 --changed 同选择面）：只映射 src/ 变更文件的测试面，"
            "tests 面自身变更不进选择面并打印排除清单（Q-X8 遗留补注册：旗标名未注册"
            "会被 parse_known_args 漏进 pytest extra 致 pytest exit 4）"
        ),
    )
    parser.add_argument("--staged", action="store_true", help="只看暂存区变更（git diff --cached）")
    parser.add_argument("--base", default=None, help="对比指定 git 基线（默认 HEAD，工作树+暂存合并视图）")
    parser.add_argument(
        "--scope",
        choices=("direct", "closed"),
        default="direct",
        help="direct=import 直连+grep（开发循环，缺省）；closed=全量传递闭包（合流/预检，宁多勿漏）",
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印清单与统计，不执行 pytest")
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"xdist worker 数（缺省 {DEFAULT_WORKERS} 探底不探顶，硬顶 {MAX_WORKERS}——AGENTS 并行纪律）",
    )
    parser.add_argument(
        "--lf", action="store_true", help="失败缓存模式：只重跑上次失败用例（pytest --lf，W2-2）"
    )
    parser.add_argument(
        "--ff", action="store_true", help="失败缓存模式：先跑上次失败再跑其余（pytest --ff，W2-2）"
    )
    parser.add_argument(
        "--cache-dir",
        default=DEFAULT_CACHE_DIR,
        help=f"pytest 缓存目录（缺省 {DEFAULT_CACHE_DIR}，隔离于 runs/ 不污染仓库根，门不受扰）",
    )
    parser.add_argument(
        "--no-cache", action="store_true", help="不注入隔离 cache_dir（沿用 pytest 缺省缓存位置）"
    )
    parser.add_argument("--map", default=str(DEFAULT_MAP), help="映射 YAML 路径")
    args, extra = parser.parse_known_args(argv)
    # argparse 的 parse_known_args 会把 `--` 保留在 extras 首位（透传分隔符）——
    # 若原样转发给 pytest，`--` 成为 pytest 的选项终止符，后续 --collect-only/-q/-p
    # 全部沦为位置路径参数 → 静默 0 收集（W2-1 实测 exit 5，无报错文本）。
    if extra and extra[0] == "--":
        extra = extra[1:]
    map_path = Path(args.map)  # #140：入参第一行 Path() 收敛
    if args.workers < 1:
        parser.error("--workers 必须 >= 1")
    if args.workers > MAX_WORKERS:
        print(
            f"[devtest] --workers {args.workers} 超硬顶 {MAX_WORKERS}"
            "（并行纪律：xdist 挂死前科 8w→20 进程 10.4GB，AGENTS.md 探底不探顶）→ 收敛"
        )
        args.workers = MAX_WORKERS
    if args.staged and args.base:
        parser.error("--staged 与 --base 互斥（二选一）")
    if args.lf and args.ff:
        parser.error("--lf 与 --ff 互斥（只重跑 vs 失败优先，二选一）")
    if not (args.changed or args.changed_src):
        parser.error("缺 --changed/--changed-src（选择模式；--help 看用法）")

    t0 = time.perf_counter()
    changed = _changed_src(args.staged, args.base)
    if not changed:
        print("[devtest] git diff 无 src/rfauto 变更，无事可做")
        return 0
    if args.changed_src:
        # src-only 口径的排除面报告：tests 面自身变更列出不选（选择逻辑本就
        # 只收 src/rfauto——此处使"排除了什么"可见，防误以为 tests 改动丢了）。
        excluded_tests = _changed_tests(args.staged, args.base)
        print(
            f"[devtest] src-only 口径：排除 tests 面自身变更 {len(excluded_tests)} 个"
            "（不进选择面，映射只收 src/rfauto）"
        )
        for t in excluded_tests:
            print(f"  [excluded] {t}")
    stale_reason = _ensure_map(map_path, args.scope)
    tests, not_in_map, per_file = _get_selection(map_path, args.scope, changed)
    overhead = time.perf_counter() - t0
    fresh_note = "指纹新鲜" if not stale_reason else f"已再生（原因：{stale_reason}）"
    print(
        f"[devtest] 映射 {fresh_note}；选择开销 {overhead:.2f}s"
        f"（含指纹检查+清单提取，不含 pytest）"
    )

    print(f"[devtest] 变更 src 文件 {len(changed)} 个（scope={args.scope}）：")
    for src in changed:
        n = per_file.get(src)
        print(f"  {src} -> {'未入映射（新增/删除）' if n is None else f'{n} tests'}")
    print(f"[devtest] 受影响测试合计 {len(tests)} 个（去重后）：")
    for t in tests:
        print(f"  {t}")
    if len(tests) > ARGSFILE_THRESHOLD:
        print(f"[devtest] （> {ARGSFILE_THRESHOLD}，真跑将走 @argsfile 通道）")
    if not_in_map:
        print(f"[devtest] 未入映射 {len(not_in_map)} 个（新建文件请先提交后再生映射）：{not_in_map}")
    if args.dry_run:
        cache_note = f"缓存目录 {args.cache_dir}" if not args.no_cache else "缓存隔离已关闭（--no-cache）"
        print(
            f"[devtest] dry-run 到此为止（去掉 --dry-run 将执行 pytest -n {args.workers}，{cache_note}）"
        )
        return 0
    if not tests:
        print("[devtest] 映射无受影响测试，跳过 pytest")
        return 0
    return _run_pytest(tests, args.workers, extra, args.cache_dir, isolate_cache=not args.no_cache)


if __name__ == "__main__":
    sys.exit(main())
