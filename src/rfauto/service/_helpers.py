"""service 层跨模块微助手单源（S2-8 单源化批，review_ge8e 2026-10-04）。

载荷解析/审计读取等零业务逻辑的微助手自此单源：存量四份近逐字节拷贝
（humidity_drift vs cryo_materials 逐字节同；aging/glass_weave_skew 仅
docstring 异，出自 内部证据档 S2-8 实测
diff）收敛至此。消费侧以别名 import 保持原调用名（``_num``/``_err``/
``_require_payload_dict``）不变、调用点零改动；本地副本按 #116 治理纪律
删净防遮蔽（回归钉=tests/unit/test_service_payload_helpers.py 单源身份
断言 + 本地 def 消失文本钉）。

与 envelope.py 的分工：本模块**不造信封形状**——失败信封一律经
``error_envelope`` 构造器产出（信封契约 §4：新代码禁止裸 ok 字面量），
``err_envelope`` 只是它的可选 schema 版本戳变体；本模块只收入参收敛与
审计文件枚举。

数字出处：本模块零物理数字（内核立规注记 规则 7）——纯入参校验与文件读取。
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope

__all__ = [
    "err_envelope",
    "load_run_trials",
    "optional_num",
    "parse_num",
    "require_payload_dict",
    "safe_run_id",
]


def err_envelope(
    errors: Any, schema_version: str | None = None
) -> dict[str, Any]:
    """失败信封单源：``error_envelope`` 的可选 schema 版本戳变体。

    Args:
        errors: str / 可迭代[str] / None——经 normalize_errors 恒以
            ``list[str]`` 落键。
        schema_version: 给出时在信封上加 ``schema_version`` 戳
            （humidity_drift/cryo_materials 误差信封的历史形状键集：
            ok/schema_version/errors）；None 时与 ``error_envelope``
            完全同形（aging/glass_weave_skew 口径）。
    """
    env = error_envelope(errors)
    if schema_version is None:
        return env
    stamped: dict[str, Any] = {"schema_version": schema_version}
    stamped.update(env)
    return stamped


def require_payload_dict(payload: Any) -> dict[str, Any]:
    """payload 必须是 JSON 对象；否则 ValueError（调用方收敛为失败信封）。"""
    if not isinstance(payload, dict):
        raise ValueError(f"payload 必须是 JSON 对象，实际 {type(payload).__name__}")
    return payload


def safe_run_id(run_id: Any) -> str | None:
    """run_id 路径段守卫单源（aurora_g W1-S1，R1 审计 P9-13 v9 Top1）。

    背景（内部证据档 §面6）：同一 UI service 面内
    ``RUNS_DIR / run_id`` 拼接 10 处仅 read_run_events/append_run_event/
    run_fig_file 3 处设防，run_detail/tune_trials/calibration_view/
    sparams_series/field_view/smith_view/_run_dir_or_error（pareto/
    feasibility 链）+ nf2ff_service.farfield_view 8 处零清洗——真机实证
    ``curl --path-as-is /api/runs/..`` 直通仓根触发全仓 rglob 枚举
    （worker 阻塞 >12s + 目录结构泄漏；非回环绑定+--expose-runs 升级）。

    判据=既有三守卫并集（append_run_event 的 W6-S26 P2-2 NUL 模式 +
    run_fig_file 的 ``..`` 子串口径）：
      空串 / 含 ``/`` / 含 ``\\\\`` / 含 NUL（``\\x00``）/ 等于 ``.`` 或
      ``..`` / **含** ``..`` 子串（拒 ``..x``/``a..b`` 变体，对齐
      run_fig_file 既有白名单口径）。

    Returns:
        str | None: 合法单段目录名（strip 后）原样返回；非法返回 None
        ——失败面（error 信封 / 404）由调用方按各自契约构造，本函数
        零信封零抛错（纯入参判定，与 parse_num 同纪律）。

    合法 run_id 全是单段目录名（日期前缀 run 目录），``..`` 子串口径
    零误伤面（审计 §面6 P9-13 结论）。
    """
    s = str(run_id).strip()
    if (not s or "/" in s or "\\" in s or "\x00" in s
            or s in (".", "..") or ".." in s):
        return None
    return s


def parse_num(
    value: Any,
    name: str,
    errors: list[str],
    *,
    positive: bool = False,
    nonneg: bool = False,
    accept_str: bool = True,
) -> float | None:
    """入参收敛为有限 float（bool 显式拒收 df7+⑯；#140/#364④ 判缺失 is not None）。

    ``accept_str``（F-13 批 2 策略参，SPECS §3.2；core/num_utils.coerce_float
    契约 §5 同族形态）：缺省 True=float() 收敛接受数字字符串（单源现行为
    逐位不变）；False=严格 isinstance 拒收非 int/float（emc/metasurface
    原本地副本语义保真——数字字符串记 error 不静默转数）。
    """
    if value is None:
        errors.append(f"{name} 缺失")
        return None
    if isinstance(value, bool):
        errors.append(f"{name} 不接受 bool（float(True)=1.0 静默污染）")
        return None
    if not accept_str and not isinstance(value, (int, float)):
        errors.append(f"{name} 必须是实数，实际 {value!r}")
        return None
    try:
        val = float(value)
    except (TypeError, ValueError):
        errors.append(f"{name} 必须是数字，实际 {value!r}")
        return None
    if not math.isfinite(val):
        errors.append(f"{name} 必须为有限数，实际 {value!r}")
        return None
    if positive and val <= 0.0:
        errors.append(f"{name} 必须 >0，实际 {val!r}")
        return None
    if nonneg and val < 0.0:
        errors.append(f"{name} 必须 >=0，实际 {val!r}")
        return None
    return val


def optional_num(
    value: Any, name: str, errors: list[str], *, positive: bool = False, nonneg: bool = False
) -> float | None:
    """可选数值（键缺失/None=不启用该节；给了值但非法记 error）。"""
    if value is None:
        return None
    return parse_num(value, name, errors, positive=positive, nonneg=nonneg)


def load_run_trials(run_dir: str | Path) -> list[dict[str, Any]]:
    """读 run 的 trials/*.json 审计文件（单源 loader）。

    口径（campaign_dashboard._load_trials / ui_service._load_run_trials
    的公共体，S2-8②）：按文件名排序、坏文件跳过、目录缺失返回空表；
    **不**按 trial_number 重排（v3_services._load_run_trials 的排序差异
    属其消费面语义，未并入——表序由各消费侧自理）。
    """
    tdir = Path(run_dir) / "trials"  # #140 PathLike 收敛
    if not tdir.is_dir():
        return []
    trials: list[dict[str, Any]] = []
    for f in sorted(tdir.glob("trial_*.json")):
        try:
            trials.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            continue
    return trials
