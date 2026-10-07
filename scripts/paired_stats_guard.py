"""配对实验统计守卫（T15-B10 = Z-9 并档；SPECS3 §3.1 单入口）。

背景坑族（预声明门语义，防"裁判数字先自证"缺位）：

- #294 家族：ulp 级浮点差被报成"斜率/差异"——CI 含 0 一律
  ``not_assertable``（差异不可断言）；
- #281 家族：平台内 0.1dB 漂移报成频移——CI 不含 0 但效应量低于调用方
  显式声明的 MDE（最小可感效应，配对 d 单位）一律 ``below_mde``
  （统计显著但工程无意义）；
- #367 家族：同源数字互证出假差异——本守卫只吃**独立两臂配对样本**
  （成对语义由调用方保证：逐 trial 同序配对），不做同源重算比对。

三档确定性判读（不设"PASS=有差异"的诱导）：

1. bootstrap CI95 含 0 → ``not_assertable``；
2. CI 不含 0 但 |effect_size| < MDE → ``below_mde``；
3. 否则 → ``assertable``（带 CI+effect+snr）。

MDE 无缺省值（预声明纪律：每战役用前必须声明）——CI 不含 0 而调用方
未传 MDE → 显式 ValueError（宁可拒跑不可无预声明）。CI 含 0 时 MDE
不参与判读（传不传均可）。

内核规格（SPECS3 §3.1 原文）：输入=配对两臂 CSV（列 arm,value[,seed]，
逐 trial 同序配对由调用方保证）；输出={mean_diff, bootstrap_ci95（10k
重采样 seed=0 固定）, effect_size（配对 d=mean_diff/sd(diff)）,
snr=|mean_diff|/noise_sigma, verdict}；noise_sigma=sd(diff)（ddof=1，
配对噪声 σ）。

落点纪律：scripts 面（argparse CLI，不进 typer/CLI 计数）；消费面接线
（战役判读模板替代裸 mean diff）随首个新战役（spec"轻接线"条款）。
确定性：同输入两次运行输出逐字节一致（铁律 7；测试钉 seed 两次对拍）。
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

#: 守卫输出 schema 标识（消费者据此识别）。
SCHEMA = "rfauto-paired-stats-guard/1"

#: bootstrap 重采样次数与固定种子（spec 原文：10k 重采样 seed=0）。
N_BOOT = 10_000
BOOT_SEED = 0

#: CI 置信水平（spec：bootstrap_ci95）。
CI_LEVEL = 0.95

#: 判读三档（唯一合法 verdict 词表）。
VERDICTS = ("not_assertable", "below_mde", "assertable")


def parse_paired_csv(text: str, arm_a: str | None = None,
                     arm_b: str | None = None) -> dict[str, Any]:
    """配对两臂 CSV 文本 → 两臂数值序列（文件序逐行配对）。

    合同：表头必含 ``arm`` 与 ``value`` 列（可选 ``seed`` 列，解析但
    不参与配对语义——成对语义由调用方保证）；两臂行数必须相等且各值
    可转 float。返回 {arm_a, arm_b, values_a, values_b, n_pairs}。
    """
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ValueError("CSV 缺表头（需要 arm,value 两列）")
    fields = [(f or "").strip() for f in reader.fieldnames]
    if "arm" not in fields or "value" not in fields:
        raise ValueError(f"CSV 表头必须含 arm 与 value 列，得 {fields!r}")
    name_map = {orig: strip for orig, strip in
                zip(reader.fieldnames, fields, strict=True) if strip}
    arms: dict[str, list[float]] = {}
    for row in reader:
        arm = (row[name_map["arm"]] or "").strip()
        raw = (row[name_map["value"]] or "").strip()
        if not arm or not raw:
            raise ValueError(f"CSV 存在空 arm/value 行：arm={arm!r} value={raw!r}")
        try:
            val = float(raw)
        except ValueError as exc:
            raise ValueError(f"value 不可转 float：{raw!r}") from exc
        arms.setdefault(arm, []).append(val)
    labels = sorted(arms)
    if arm_a is not None and arm_b is not None:
        for want in (arm_a, arm_b):
            if want not in arms:
                raise ValueError(f"指定臂 {want!r} 不在 CSV 臂集合 {labels!r} 中")
        labels = [arm_a, arm_b]
    elif arm_a is not None or arm_b is not None:
        raise ValueError("arm_a 与 arm_b 必须同时指定或同时缺省")
    if len(labels) != 2:
        raise ValueError(f"配对守卫恰好需要两臂，得 {len(labels)} 臂：{labels!r}")
    va, vb = arms[labels[0]], arms[labels[1]]
    if len(va) != len(vb):
        raise ValueError(
            f"两臂行数不等（成对语义由调用方保证）：{labels[0]}={len(va)} "
            f"vs {labels[1]}={len(vb)}")
    if len(va) < 2:
        raise ValueError(f"配对样本 n={len(va)} < 2：sd(diff) 不可估，拒绝判读")
    return {"arm_a": labels[0], "arm_b": labels[1],
            "values_a": va, "values_b": vb, "n_pairs": len(va)}


def paired_bootstrap_ci(diffs: np.ndarray, *, n_boot: int = N_BOOT,
                        seed: int = BOOT_SEED,
                        ci_level: float = CI_LEVEL) -> tuple[float, float]:
    """配对差向量 → bootstrap 均值 CI（分块重采样，固定种子确定性）。

    分块生成重采样索引（每块 1000 个重采样）以约束内存；分块方式固定，
    随机流与一次性整块生成不同但**自身可复现**（同输入两次逐位一致，
    测试钉对拍）。常数差向量退化处理：重采样均值恒等于常数，CI=点值。
    """
    n = diffs.shape[0]
    rng = np.random.default_rng(seed)
    means = np.empty(n_boot, dtype=np.float64)
    chunk = 1000
    done = 0
    while done < n_boot:
        take = min(chunk, n_boot - done)
        idx = rng.integers(0, n, size=(take, n))
        means[done:done + take] = diffs[idx].mean(axis=1)
        done += take
    alpha = (1.0 - ci_level) / 2.0
    low, high = np.percentile(means, [100.0 * alpha, 100.0 * (1.0 - alpha)])
    return float(low), float(high)


def paired_stats_guard(values_a: list[float], values_b: list[float],
                       mde: float | None = None, *,
                       arm_a: str = "a", arm_b: str = "b",
                       n_boot: int = N_BOOT, seed: int = BOOT_SEED,
                       ) -> dict[str, Any]:
    """配对两臂 → 统计守卫判读（三档确定性，spec §3.1 门语义）。

    - CI 含 0 → ``not_assertable``（#294/#367 家族：ulp 级差/同源互证
      差异不可断言）；
    - CI 不含 0 且 MDE 缺省 → ValueError（宁可拒跑不可无预声明）；
    - CI 不含 0 且 |effect_size| < MDE → ``below_mde``（#281 家族：
      统计显著但低于最小可感效应）；
    - 否则 → ``assertable``。

    effect_size=配对 d=mean_diff/sd(diff)（ddof=1）；noise_sigma=sd(diff)；
    snr=|mean_diff|/noise_sigma。sd(diff)=0（常数差）时 effect_size/snr
    记 None 并显式注记（常数非零差按一致性效应判读，CI=点值）。
    """
    if len(values_a) != len(values_b):
        raise ValueError("两臂长度不等——配对语义由调用方保证（逐 trial 同序）")
    n = len(values_a)
    if n < 2:
        raise ValueError(f"配对样本 n={n} < 2：sd(diff) 不可估，拒绝判读")
    if mde is not None and float(mde) <= 0:
        raise ValueError(f"MDE 必须为正数，得 {mde!r}")
    a = np.asarray(values_a, dtype=np.float64)
    b = np.asarray(values_b, dtype=np.float64)
    diffs = a - b
    mean_diff = float(diffs.mean())
    sd_diff = float(diffs.std(ddof=1))
    ci_low, ci_high = paired_bootstrap_ci(diffs, n_boot=n_boot, seed=seed)

    effect_size: float | None = None
    snr: float | None = None
    constant_note: str | None = None
    if sd_diff > 0.0:
        effect_size = mean_diff / sd_diff
        snr = abs(mean_diff) / sd_diff
    else:
        constant_note = ("sd(diff)=0 常数差：effect_size/snr 不可估（记 "
                         "None 不虚构）；bootstrap CI 退化为点值")

    ci_contains_zero = (ci_low <= 0.0 <= ci_high)
    notes: list[str] = []
    if constant_note:
        notes.append(constant_note)
    if ci_contains_zero:
        verdict = "not_assertable"
        reason = (f"bootstrap CI95 含 0（区间 [{ci_low:.6g}, {ci_high:.6g}]）"
                  "——差异不可断言（#294 ulp 级差/#367 同源互证防误报向）")
    elif mde is None:
        raise ValueError(
            "CI 不含 0 而未声明 MDE（最小可感效应）——预声明纪律：每战役"
            "用前必须显式传入 MDE，宁可拒跑不可无预声明（spec §3.1 ④）")
    elif effect_size is not None and abs(effect_size) < float(mde):
        verdict = "below_mde"
        reason = (f"CI95 不含 0 但 |effect_size|={abs(effect_size):.4g} < "
                  f"MDE={float(mde):g}（配对 d 单位）——统计显著但工程无意义"
                  "（#281 平台内漂移防误报向）")
    elif sd_diff == 0.0:
        # 常数非零差分支（审查 P1-1，2026-10-05）：sd(diff)=0 时配对 d 无定义
        # （effect_size=None），MDE 门无从比较——**常数差恰是 #294/#287 族
        # ulp 级系统偏移的最常见形态**，不得落"可断言"。三态如实：
        # 全零=恒等（差异可断言且无工程量）；非零常数=可疑系统偏移
        # （requires_investigation，留人工定位）。
        if all(x == 0.0 for x in diffs):
            verdict = "assertable"
            reason = ("全部配对差恒等于 0——逐位一致（最强断言形态；"
                      "sd=0 且非零差不存在）")
        else:
            verdict = "requires_investigation"
            reason = (f"配对差为非零常数（sd=0，值={diffs[0]:.6g}）：配对 d "
                      "无定义、MDE 门不适用——疑似 ulp 级系统偏移（#294/#287 "
                      "族），须人工归因（来源/双源仲裁）后才能断言")
    else:
        verdict = "assertable"
        effect_desc = (f"effect_size={abs(effect_size):.4g}"
                       if effect_size is not None else "常数一致性差")
        reason = f"CI95 不含 0 且 |effect_size| 达 MDE（{effect_desc}）——差异可断言"
    return {
        "schema": SCHEMA,
        "n_pairs": n,
        "arm_a": arm_a,
        "arm_b": arm_b,
        "mean_diff": mean_diff,
        "ci95_low": ci_low,
        "ci95_high": ci_high,
        "effect_size": effect_size,
        "noise_sigma": sd_diff,
        "snr": snr,
        "mde": float(mde) if mde is not None else None,
        "verdict": verdict,
        "reason": reason,
        "notes": notes,
        "bootstrap": {"n_boot": int(n_boot), "seed": int(seed),
                      "ci_level": CI_LEVEL},
    }


def guard_csv_text(text: str, mde: float | None = None, *,
                   arm_a: str | None = None, arm_b: str | None = None,
                   ) -> dict[str, Any]:
    """CSV 文本一步到判读（parse+guard 薄组合，CLI/测试共用）。"""
    parsed = parse_paired_csv(text, arm_a=arm_a, arm_b=arm_b)
    return paired_stats_guard(
        parsed["values_a"], parsed["values_b"], mde,
        arm_a=parsed["arm_a"], arm_b=parsed["arm_b"])


def _build_parser() -> argparse.ArgumentParser:
    """CLI 参数面（独立函数供测试扫描自写 help 文本：禁左右方括号与百分号）。"""
    parser = argparse.ArgumentParser(
        prog="paired_stats_guard",
        description=("配对两臂 CSV 统计守卫：bootstrap CI95 + 配对 d 三档判读"
                     "（not_assertable / below_mde / assertable）。"
                     "成对语义由调用方保证：逐 trial 同序配对。"))
    parser.add_argument("--csv", required=True,
                        help="输入 CSV 路径（表头必含 arm 与 value 列，"
                             "可选 seed 列）")
    parser.add_argument("--mde", type=float, default=None,
                        help="最小可感效应 MDE（配对 d 单位，无缺省值；"
                             "CI 含 0 时可省，CI 不含 0 时必填否则拒跑）")
    parser.add_argument("--arm-a", default=None,
                        help="指定甲臂名（缺省取两臂名字典序第一）")
    parser.add_argument("--arm-b", default=None,
                        help="指定乙臂名（缺省取两臂名字典序第二）")
    parser.add_argument("--json-out", default=None,
                        help="判读 JSON 落盘路径（缺省只打印 stdout）")
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI 入口（scripts 面，argparse，help 文本禁方括号与百分号）。"""
    parser = _build_parser()
    args = parser.parse_args(argv)
    text = Path(args.csv).read_text(encoding="utf-8")
    try:
        report = guard_csv_text(text, args.mde,
                                arm_a=args.arm_a, arm_b=args.arm_b)
    except ValueError as exc:
        payload = {"schema": SCHEMA, "ok": False,
                   "error": f"拒跑：{exc}"}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                       encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
