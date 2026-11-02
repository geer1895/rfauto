"""al_propose —— 主动学习下一批提议面（aurora_n MCP 接线补齐席，2026-10-31）。

zero_wiring 登记欠账清偿：T-N9 宿主 propose_next_points + 采集三族
运行时门（O4 席此前仅落 CLI 叶 ``rfauto al propose``）。数据工厂闭环的
"下一批测什么"回答者：读湖样本（samples.json / 物化数据集 / run
trials 三形态互斥恰给一）提议下一批真机实验点。缺省=σ 求和旧路径
（宿主逐字节转发）；acquisition 给出走采集族（lcb/ucb/ei/sigma）。
零逻辑转发 service/al_service（规则 4：JSON 信封进出；铁律 7：σ 与
score 全部由确定性内核产出，本层零新数值；提议点需真机复验后方可
并入样本集——信封 note 随行）。

文件路径面：samples_path 为本机路径（MCP 客户端与服务器同盘语义）；
本工具只读不落盘（out_dir/runs_root 装载细节不外露，走 service 缺省）。
"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import mcp as mcp


@mcp.tool(
    annotations={
        "destructiveHint": False,
        "idempotentHint": False,
    }
)
def al_propose(
    samples_path: str = "",
    dataset: str = "",
    run: str = "",
    k: int = 5,
    kind: str = "nn",
    acquisition: str = "",
    source: str = "gp",
    beta: float = 2.0,
    xi: float = 0.0,
    n_candidates: int = 500,
    min_dist: float = 0.12,
    seed: int = 42,
    conformal_fallback: bool | None = None,
    max_rows: int = 5000,
) -> dict[str, Any]:
    """提议下一批实验点：读湖样本 → 不确定度×距离（或采集族）→ top-k。

    同 seed 同输入逐位复现（确定性内核）。样本来源三形态互斥恰给一：
    samples_path（bounds 以文件为准）/ dataset（bounds 由观测参数范围
    推导）/ run（同左）；来源未给/多给/不存在 → ok=False 显式报错。
    负例（空样本/空参数域/零数值指标/未知采集名或来源/registry 缺
    kind）全部信封化不抛裸 traceback。

    Args:
        samples_path: samples.json 路径（bounds/samples schema，与
            certify 公差盒同款；与 dataset/run 互斥，恰给一）
        dataset: 物化数据集名（runs/datasets/，走 query_dataset 链读
            params/metrics；与 samples_path/run 互斥，恰给一）
        run: run id（读 runs/<id>/trials/trial_*.json 的 params/metrics；
            与 samples_path/dataset 互斥，恰给一）
        k: 提议点数（下一批预算 N，≥0；缺省 5）
        kind: 代理注册键（legacy σ 路径需支持 uncertainty 或开
            conformal_fallback；registry 来源=注册键；缺省 nn）
        acquisition: 采集函数族：lcb | ucb | ei | sigma；空串=σ 求和
            旧路径（propose_next_points 逐字节转发）
        source: 不确定度来源（采集路径）：gp | bootstrap | nn | registry
            （registry 需 kind=注册键；缺省 gp）
        beta: 置信界系数（lcb/ucb 消费；缺省 2.0）
        xi: EI 探索参数（ei 消费；缺省 0.0）
        n_candidates: LHS 候选池规模（缺省 500）
        min_dist: 与既有样本的最小归一化距离（距离过滤阈值，缺省 0.12）
        seed: 确定性种子（同 seed 逐位复现；缺省 42）
        conformal_fallback: 原生 σ 缺席时代理走 T-N1 共形区间包装
            （None=按路径缺省：legacy False / 采集 True，同各自内核
            缺省；显式 True/False 覆盖——#277 三态语义）
        max_rows: 数据集装载行数上限（超出如实标注 truncated；
            缺省 5000=service DEFAULT_MAX_ROWS）

    Returns:
        dict: ok=True {ok, proposed: [{params, score/uncertainty_score,
        mean, sigma}, ...], n_existing, n_candidates, ...}（键随形态：
        samples_path legacy=宿主信封直通；dataset/run 与采集族追加
        sample_source/source_label/bounds/seed/acquisition/
        uncertainty_source）；失败 {ok: False, errors: [...]}
    """
    from rfauto.service.al_service import al_propose

    return al_propose(
        str(samples_path).strip() or None,
        str(dataset).strip() or None,
        str(run).strip() or None,
        k=k,
        kind=kind,
        acquisition=(str(acquisition).strip() or None),
        source=source,
        beta=beta,
        xi=xi,
        n_candidates=n_candidates,
        min_dist=min_dist,
        seed=seed,
        conformal_fallback=conformal_fallback,
        max_rows=max_rows,
    )
