"""runs/ 面路径单源：cwd 根 ∪ 仓库根双根收敛（R3-9）。

背景（runs/review_ge8e/r3_service/REPORT.md R3-9）：agent_sandbox.SANDBOX_ROOT、
agent_runtime.SESSIONS_DIR、agent_safety.AUDIT_DIR 历史上是 cwd 相对
``Path("runs")/...``——进程 chdir 进仓库子目录（#295 族"从 runs/ 子目录执行"
的驱动脚本）会把沙箱草稿/会话存档/审计日志静默分叉到 ``<子目录>/runs/``。

对照 :mod:`rfauto.infra.recipe_guard` ``protected_recipe_roots`` 的既有双根
形态，runs 面收敛语义（唯一确定，cwd 优先）：

1. ``<cwd>/runs`` 存在 → 用它（仓根运行与测试 chdir tmp 两态不变）；
2. 否则 cwd 在仓库树内且 ``<仓库根>/runs`` 存在 → 收敛回仓库 runs/
   （chdir 进 runs/ 子目录的驱动场景不再分叉）；
3. 否则 → ``<cwd>/runs``（新工作区/测试 tmp 首次写落 cwd，不污染仓库）。

回归钉：tests/unit/test_runs_paths.py——tmp_path chdir 下沙箱草稿落 tmp
而非仓 runs/；chdir 仓库 runs/ 子目录时收敛回仓库 runs/。
分层：infra 只依赖标准库（core 之上、service 之下）。
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["resolve_runs_dir", "runs_root"]

#: src/rfauto/infra/runs_paths.py → parents[3] = 仓库根（recipe_guard 同款）
_REPO_ROOT = Path(__file__).resolve().parents[3]


def runs_root() -> Path:
    """当前生效的 runs 根（绝对路径；语义见模块 docstring 三态）。"""
    cwd_runs = Path.cwd() / "runs"
    if cwd_runs.is_dir():
        return cwd_runs
    try:
        Path.cwd().resolve().relative_to(_REPO_ROOT)
    except (ValueError, OSError):
        return cwd_runs  # cwd 不在仓库树内：cwd 根（测试 tmp 等）
    repo_runs = _REPO_ROOT / "runs"
    if repo_runs.is_dir():
        return repo_runs  # 仓内子目录 chdir：收敛回仓库 runs/（#295 族）
    return cwd_runs


def resolve_runs_dir(rel: str | Path) -> Path:
    """cwd 相对的 ``runs/...`` 路径 → 双根收敛后的绝对路径。

    首段为 ``runs`` 时按 runs 根拼接其余分段；绝对入参原样返回
    （测试/调用方显式注入的绝对目录不受收敛影响）。
    """
    p = Path(rel)
    if p.is_absolute():
        return p
    parts = p.parts[1:] if p.parts and p.parts[0] == "runs" else p.parts
    return runs_root().joinpath(*parts)
