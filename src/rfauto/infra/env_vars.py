"""RFAUTO_* 环境变量目录（QW-12 单一清单的机器可读面）。

docs/env_vars.md 是人读参考页；本模块是 doctor --env 校验与同步测试的
单一事实来源。两处由 tests/unit/test_env_vars.py 的双向集合对账钉住——
新增环境变量必须同批更新目录与本参考页（#97 文档-代码同 commit 惯例）。

条目从全仓 `git grep -o "RFAUTO_[A-Z0-9_]+"` 实测归纳（2026-09-26，47 个；
排除一个跨行截断伪影）。2026-10-04 E3-4（ge8e 审查批）补登 remote 凭据
两键（09-28 多机 WP 晚于该次盘点）。kind 语义：
- ``path``：指向文件系统路径/安装根——设了就验存在性（missing 记 problem）；
- ``flag``：行为开关（truthy 放行/开启语义）；
- ``knob``：数值/字符串旋钮（超时/端口/标签等）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Kind = Literal["path", "flag", "knob"]


@dataclass(frozen=True)
class EnvVarSpec:
    """单个环境变量条目（purpose 与 docs/env_vars.md 行保持一致）。"""

    name: str
    kind: Kind
    category: str
    purpose: str


_ENV_VAR_CATALOG: tuple[EnvVarSpec, ...] = (
    # ── 求解器/工具链路径 ────────────────────────────────────────────────
    EnvVarSpec("RFAUTO_AEDT_PATH", "path", "solver", "AEDT 安装根（HFSS/PyAEDT 链）"),
    EnvVarSpec("RFAUTO_HPEESOF_DIR", "path", "solver", "ADS 安装根（hpeesofsim 链）"),
    EnvVarSpec("RFAUTO_OPENEMS_BIN", "path", "solver", "openEMS 可执行/绑定定位"),
    EnvVarSpec("RFAUTO_NGSPICE_BIN", "path", "solver", "ngspice 可执行"),
    EnvVarSpec("RFAUTO_XYCE_BIN", "path", "solver", "Xyce 可执行（WSL 场景）"),
    EnvVarSpec("RFAUTO_QUCSATOR_BIN", "path", "solver", "qucsatorRF 可执行"),
    EnvVarSpec("RFAUTO_PALACE_EXE", "path", "solver", "Palace 可执行（WSL）"),
    EnvVarSpec("RFAUTO_MEEP_PYTHON", "path", "solver", "Meep 专用解释器（CI-only 冻结面）"),
    EnvVarSpec("RFAUTO_ELMER_BIN", "path", "solver", "ElmerGrid/ElmerSolver 可执行"),
    EnvVarSpec("RFAUTO_ELMER_BIN_ENV", "knob", "solver", "Elmer 进程环境变量注入"),
    EnvVarSpec("RFAUTO_COMSOL_ROOT", "path", "solver", "COMSOL 安装根（mph 桥）"),
    EnvVarSpec("RFAUTO_LICENSE_SERVER", "knob", "solver", "商业 license 服务器探测目标"),
    EnvVarSpec("RFAUTO_OPENEMS_EXE", "path", "legacy", "P0 历史实验面（遗留）"),
    EnvVarSpec("RFAUTO_OPENEMS_MESH", "knob", "legacy", "P0 历史实验网格档（遗留）"),
    # ── infra/config ────────────────────────────────────────────────────
    EnvVarSpec("RFAUTO_WORKSPACE_DIR", "path", "infra", "工作区根目录"),
    EnvVarSpec("RFAUTO_WORKSPACE", "path", "infra", "工作区根目录（兼容旧名）"),
    EnvVarSpec("RFAUTO_REGISTRY_DB", "path", "infra", "run 注册库（duckdb 路径）"),
    EnvVarSpec("RFAUTO_REGISTRY_PG_DSN", "knob", "infra", "Postgres DSN（可选后端；值含凭据不回显）"),
    EnvVarSpec("RFAUTO_JOB_REGISTRY_DB", "path", "infra", "任务注册库路径"),
    EnvVarSpec("RFAUTO_TIMEOUT_S", "knob", "infra", "通用超时秒数"),
    EnvVarSpec("RFAUTO_GRPC_PORT", "knob", "infra", "AEDT gRPC 端口"),
    EnvVarSpec("RFAUTO_LOG_LEVEL", "knob", "infra", "日志级别"),
    EnvVarSpec("RFAUTO_MAX_CONCURRENT", "knob", "infra", "并发上限"),
    EnvVarSpec("RFAUTO_DEFAULT_UNIT", "knob", "infra", "缺省单位制"),
    EnvVarSpec("RFAUTO_CACHE", "knob", "infra", "ResultCache 开关/路径口径"),
    EnvVarSpec("RFAUTO_SOLVERS_YAML", "path", "infra", "solvers 配置文件覆盖"),
    EnvVarSpec("RFAUTO_FS_ROOT", "knob", "infra", "fs_list/recipe_view 允许根（os.pathsep 多根；缺省 cwd）"),
    # ── 行为开关 ────────────────────────────────────────────────────────
    EnvVarSpec(
        "RFAUTO_CALCULATORS_ALLOW_EXPERIMENTAL", "flag", "behavior",
        "实验计算器键放行（缺省拒绝）",
    ),
    EnvVarSpec("RFAUTO_SKIP_RUN", "flag", "behavior", "模板层跳过真跑（离线审计态）"),
    EnvVarSpec("RFAUTO_NRTS", "knob", "behavior", "覆盖渲染 NrTS（时窗旋钮）"),
    EnvVarSpec("RFAUTO_REGEN_GOLDEN", "flag", "behavior", "金快照重生成开关（评审后重钉）"),
    EnvVarSpec("RFAUTO_AGENTBENCH_PRIVATE_SET", "flag", "behavior", "agent 基准私有集放行"),
    EnvVarSpec("RFAUTO_PALACE_ITEST", "flag", "behavior", "Palace WSL 真跑集成 opt-in 门"),
    EnvVarSpec("RFAUTO_PEC_MIRROR", "flag", "behavior", "PEC 镜像修正总开关"),
    EnvVarSpec("RFAUTO_PEC_MIRROR_BEGIN", "knob", "behavior", "PEC 镜像修正 z 起始（幂等链）"),
    EnvVarSpec("RFAUTO_PEC_MIRROR_END", "knob", "behavior", "PEC 镜像修正 z 结束（幂等链）"),
    # ── 战役/仲裁旋钮 ───────────────────────────────────────────────────
    EnvVarSpec("RFAUTO_HFSS_SOLVE_TIMEOUT_S", "knob", "campaign", "HFSS 单解超时秒数"),
    EnvVarSpec("RFAUTO_C4_ARB_TAG", "knob", "campaign", "C4 仲裁战役标签"),
    EnvVarSpec("RFAUTO_C4_ARB_DELTA_S", "knob", "campaign", "C4 仲裁 ΔS 目标"),
    EnvVarSpec("RFAUTO_C4_ARB_MAX_PASSES", "knob", "campaign", "C4 仲裁最大 passes"),
    EnvVarSpec("RFAUTO_MAPES_G0_TAG", "knob", "campaign", "MAPES G0 战役标签"),
    EnvVarSpec("RFAUTO_MAPES_G0_DELTA_S", "knob", "campaign", "MAPES G0 ΔS 目标"),
    EnvVarSpec("RFAUTO_MAPES_G0_MAX_PASSES", "knob", "campaign", "MAPES G0 最大 passes"),
    EnvVarSpec("RFAUTO_MAPES_M_TAG", "knob", "campaign", "MAPES M 战役标签"),
    EnvVarSpec("RFAUTO_MAPES_M_DELTA_S", "knob", "campaign", "MAPES M ΔS 目标"),
    EnvVarSpec("RFAUTO_MAPES_M_MAX_PASSES", "knob", "campaign", "MAPES M 最大 passes"),
    # ── 远程多机（多机协同 WP v0；E3-4 ge8e 审查批补登，两键漏登于 09-28 WP）──
    EnvVarSpec(
        "RFAUTO_REMOTE_SSH_USER", "knob", "remote",
        "SSH 用户名（凭据面=local yaml 覆盖优先，env 为无 yaml 场景回退）",
    ),
    EnvVarSpec(
        "RFAUTO_REMOTE_SSH_PASSWORD", "knob", "remote",
        "SSH 密码（凭据面=local yaml 覆盖优先，env 为无 yaml 场景回退；值不回显）",
    ),
    EnvVarSpec(
        "RFAUTO_SSH_STRICT", "flag", "remote",
        "SSH 主机钥严格模式（E3-3 TOFU 折中：缺省 AutoAdd+首连指纹落档告警；"
        "设 1=无落档指纹/指纹不匹配即拒连）",
    ),
    # ── PySR/Julia ──────────────────────────────────────────────────────
    EnvVarSpec("RFAUTO_JULIA_DEPOT", "path", "pysr", "Julia depot 定位（PySR 锚拟合）"),
    EnvVarSpec("RFAUTO_JULIA_UP", "flag", "pysr", "Julia 升级开关（PySR 锚拟合）"),
    # ── 工具链门（ge1 批新增面，审查轨 A P2-2 补登）────────────────────
    EnvVarSpec("RFAUTO_GITLEAKS_BIN", "path", "tooling", "gitleaks 可执行定位（pre-commit 门）"),
    EnvVarSpec("RFAUTO_GITLEAKS_STRICT", "flag", "tooling", "gitleaks 缺失即 fail（缺省警告放行）"),
    EnvVarSpec("RFAUTO_GITLEAKS_PY", "path", "tooling", "钩子 launcher 内 python 定位（install_git_hooks 生成）"),
    EnvVarSpec("RFAUTO_KICAD_PYTHON", "path", "tooling", "KiCad 自带 Python 定位（mTRL/kicad_extract/kicad_drc/kicad_pcell 子进程面统一口径）"),
)

#: 只读掩码清单：值可能含凭据，报告面永不回显原文。
_MASKED_VARS: frozenset[str] = frozenset({"RFAUTO_REGISTRY_PG_DSN"})


def env_var_catalog() -> tuple[EnvVarSpec, ...]:
    """目录条目（稳定排序：category 内按名称）。"""
    return tuple(sorted(_ENV_VAR_CATALOG, key=lambda s: (s.category, s.name)))


def build_env_report(environ: dict[str, str] | None = None) -> list[dict[str, object]]:
    """逐条目体检行（纯函数，environ 可注入便于测试）。

    行契约：{name, kind, category, purpose, set, state, detail}；
    state：path 类 set→"ok"/"missing"，未设→"default"；其余 set→"set"，
    未设→"default"。detail 不含任何变量原文（掩码面），path 类仅含路径。
    """
    env = dict(os.environ if environ is None else environ)
    rows: list[dict[str, object]] = []
    for spec in env_var_catalog():
        raw = env.get(spec.name)
        is_set = raw is not None and raw != ""
        state = "default"
        detail = "未设置（走 configs 缺省）"
        # is_set 已蕴含 raw 非空非 None；再显式判 None 供 mypy strict 类型收窄
        if is_set and raw is not None:
            if spec.kind == "path":
                exists = Path(raw).exists()
                state = "ok" if exists else "missing"
                detail = f"路径存在性={exists}：{raw}"
            elif spec.kind == "flag":
                state = "set"
                detail = "已设置（truthy 语义由消费者定义）"
            else:  # knob：值不回显（防凭据/环境串漏），只报已设
                state = "set"
                detail = "<set>"
        rows.append(
            {
                "name": spec.name,
                "kind": spec.kind,
                "category": spec.category,
                "purpose": spec.purpose,
                "set": is_set,
                "state": state,
                "detail": detail,
            }
        )
    return rows
