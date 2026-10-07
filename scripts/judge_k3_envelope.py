# ge8 K-3 coupled_line 机制分离批 · 判读输入面 envelope.json 回退读（审查 R6-1）。
#
# 原缺陷（R6-1，P2）：runs/ge8_k3mech/judge_k3.py 的 campaign_gates 只读
# seat_dir/verdict.json——本次批该文件不存在（launcher 直调通道无判读共用
# 尾），三座真实通道状态记在 envelope.json（verdict=PARTIAL、exec_rc=1、
# reason 明言"solve_success=False 降档"）→ campaign_* 门全 null、三座
# usable_for_mech=true / status=OK，判据 §4"任一座位 PARTIAL→该座如实记"
# 在判读产物中缺一行对账。
#
# 本模块 = 判读输入面修复（纯函数 + 薄 CLI）：
# - verdict.json 存在 → 按原口径消费（status/nrts_converged/g5_health）；
# - verdict.json 缺失 → envelope.json 回退：verdict=PARTIAL/exec_rc!=0 →
#   通道级 status="PARTIAL"（降档如实，不凑 OK 也不冒充 FAIL——产物优先于
#   退出码口径，机械数值门照算）；verdict=FAIL → "FAIL"（阻断 usable）；
# - 两档全缺 → 相关字段 None（best-effort 如实，#122）。
# 归档零改写：本模块不写 runs/ge8_k3mech/ 下任何文件（含既有 judge_k3.py），
# 输出只落显式 --out 指定路径。
#
# 用法（仓根）：.venv/Scripts/python.exe scripts/judge_k3_envelope.py \
#   --batch-dir runs/ge8_k3mech [--out <json 路径>]
from __future__ import annotations

import argparse
import json
from pathlib import Path

#: 通道级 PASS 侧的 envelope verdict 白名单（其余非空值一律降档/阻断）
_ENVELOPE_PASS = "PASS"
_FAIL = "FAIL"
_PARTIAL = "PARTIAL"


def _read_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def campaign_gates_with_envelope(seat_dir: Path) -> dict:
    """座位通道级门（verdict.json 优先，缺失回退 envelope.json）。

    返回键（judge_k3.campaign_gates 消费键的超集）：
    - campaign_verdict_status: "PASS"/"PARTIAL"/"FAIL"/原文/None；
    - campaign_source: "verdict.json" | "envelope.json" | None；
    - exec_rc / envelope_verdict / solve_success / envelope_reason：
      envelope 通道独有（verdict.json 通道为 None）；
    - nrts_converged_ok / nrts_reason / g5_health_ok：verdict.json 通道
      原样，envelope 通道恒 None（该文件不含此二门，如实缺档）；
    - g2_products/g3_finite/g3_passive/s_max/n_points：由调用方按
      sparams.csv 数据面另行填充（本函数只管通道状态文件面）。
    """
    gates: dict = {
        "campaign_verdict_status": None,
        "campaign_source": None,
        "exec_rc": None,
        "envelope_verdict": None,
        "solve_success": None,
        "envelope_reason": None,
        "nrts_converged_ok": None,
        "nrts_reason": None,
        "g5_health_ok": None,
    }
    vj = _read_json(seat_dir / "verdict.json")
    if vj is not None:
        nrts = vj.get("nrts_converged") or {}
        gates.update({
            "campaign_verdict_status": vj.get("status"),
            "campaign_source": "verdict.json",
            "nrts_converged_ok": nrts.get("ok"),
            "nrts_reason": nrts.get("reason"),
            "g5_health_ok": (vj.get("g5_health") or {}).get("ok"),
        })
        return gates

    env = _read_json(seat_dir / "envelope.json")
    if env is None:
        return gates
    env_verdict = env.get("verdict")
    exec_rc = env.get("exec_rc")
    if env_verdict == _ENVELOPE_PASS:
        status: str | None = _ENVELOPE_PASS
    elif env_verdict == _FAIL:
        status = _FAIL
    elif env_verdict is None:
        status = None
    else:
        # 降档语义沿 envelope reason（如"solve_success=False 降档"）：
        # 引擎退出码非零但产物已回拉 → PARTIAL，如实不凑 OK
        status = _PARTIAL
    gates.update({
        "campaign_verdict_status": status,
        "campaign_source": "envelope.json",
        "exec_rc": exec_rc,
        "envelope_verdict": env_verdict,
        # solve_success 判据：显式 verdict=PASS 且退出码为 0 才算成功；
        # reason 文本只作留痕（不解析自然语言判门）
        "solve_success": bool(env_verdict == _ENVELOPE_PASS and exec_rc == 0),
        "envelope_reason": env.get("reason"),
    })
    return gates


def seat_status_from_gates(gates: dict, numeric_gates_ok: bool,
                           hygiene_ok: bool) -> str:
    """座位状态判定（判据 §4：任一座位 PARTIAL→该座如实记降档态）。

    - 数据面（sparams 缺失）→ "MISSING"；
    - 通道显式 FAIL → "CAMPAIGN_GATE_ISSUE"（阻断）；
    - 通道显式 PARTIAL → "CAMPAIGN_PARTIAL"（降档：机械数值门照算、
      usable_for_mech 由数据完整性决定，但座位不再是 OK）；
    - 其余（通道 PASS 或字段 None 如实缺档）→ 数据门过="OK"。
    """
    if not numeric_gates_ok:
        return "MISSING"
    status = gates.get("campaign_verdict_status")
    if status == _FAIL:
        return "CAMPAIGN_GATE_ISSUE"
    if status == _PARTIAL:
        return "CAMPAIGN_PARTIAL" if hygiene_ok else "CAMPAIGN_GATE_ISSUE"
    return "OK" if hygiene_ok else "CAMPAIGN_GATE_ISSUE"


def usable_for_mech(gates: dict) -> bool | None:
    """机械判读可用性（通道面）：显式 False 才阻断；None 如实缺档不阻断
    （judge_k3 原口径）；PARTIAL 不阻断数据消费（产物优先于退出码），
    降档由 seat_status_from_gates 如实记账。"""
    status = gates.get("campaign_verdict_status")
    return status != _FAIL


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser(
        description="ge8 K-3 通道级门对账（verdict.json 缺档回退 envelope.json，R6-1）")
    ap.add_argument("--batch-dir", default=str(repo / "runs" / "ge8_k3mech"))
    ap.add_argument("--out", default=None,
                    help="输出 JSON 路径（缺省只打印；归档目录零改写）")
    args = ap.parse_args()
    batch = Path(args.batch_dir)
    seats = ["x1_gapmesh", "x2a_len204", "x2b_len208"]
    account: dict = {"batch": batch.name, "seats": {}}
    for name in seats:
        gates = campaign_gates_with_envelope(batch / name)
        status = seat_status_from_gates(gates, numeric_gates_ok=True,
                                        hygiene_ok=True)
        account["seats"][name] = {
            "campaign": gates,
            "seat_status_channel_only": status,
            "usable_for_mech_channel": usable_for_mech(gates),
        }
    text = json.dumps(account, ensure_ascii=False, indent=1)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
