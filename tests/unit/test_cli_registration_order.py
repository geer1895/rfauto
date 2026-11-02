"""CLI/MCP 注册序金快照守卫（AU-1 批3 快照转正，ge6 followUp 批3）.

钉住三面注册序（防后续拆分/新增**静默漂移**——AU-1 批3 机械拆分曾把
mcp_server 拆成 facade+mcp_tools/ 包，typer→click 树与工具注册序是当时
before/after 快照的对账面；本守卫把该对账转正常驻门）：

- CLI：typer app 经 ``typer.main.get_command`` 落成 click 树——顶层
  命令/组的注册序 + 全树叶命令的**深度优先注册序**（click 的
  ``commands`` 是插入序 dict，顺序即注册序；AD-1 2026-10-02 bench
  prompt-regression +1 重钉；PT-1/2/3 2026-10-02 stats
  guardband/cpk/weibull +3 重钉；PT-6 2026-10-02 firmware
  beam/varactor/dpd +3 重钉；LC-2 2026-10-02 pcell
  list/show/eval/render +4 重钉；AD-4 2026-10-02 bench
  consistency +1 重钉；X2 2026-10-04 profile status/run +2 重钉）；
- MCP：``mcp.list_tools()`` 的 132 工具名注册序 + ``list_resources()``
  （x3-wiring 2026-10-04 W7 台账①态接线批 +9 重钉）。

金快照在 ``tests/gold/cli_registration_order.json`` 与
``tests/gold/mcp_registration_order.json``；顺序漂移（拆分子包时注册序
重排/装饰器顺序调整/新增命令插队）即红。**新增命令是显式评审动作**：
重钉命令见下方 regen 说明。

金快照重生成（新命令/组合入并有意重排后跑一次，随代码同 commit）::

    .venv/Scripts/python.exe tests/unit/test_cli_registration_order.py --write-gold
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_GOLD_DIR = _REPO / "tests" / "gold"
_GOLD_CLI = _GOLD_DIR / "cli_registration_order.json"
_GOLD_MCP = _GOLD_DIR / "mcp_registration_order.json"

src_dir = _REPO / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))


def _cli_tree_snapshot() -> dict:
    """click 树顺序快照（runs/au1_cli_split/snapshot.py 同款走法）。

    返回 {"top_level": [名...按注册序], "leaf_paths": ["rfauto ...",
    ...深度优先序], "n_leaves": int, "n_top": int}。
    """
    from typer.main import get_command

    from rfauto.cli import main as cli_main

    top: list[str] = []
    leaves: list[str] = []

    def walk(cmd, path: str) -> int:
        n_leaves = 0
        if hasattr(cmd, "commands"):
            for name, sub in cmd.commands.items():
                child_path = f"{path} {name}"
                if len(path.split()) == 1:
                    top.append(name)          # 顶层注册序
                n_leaves += walk(sub, child_path)
        else:
            leaves.append(path)
            n_leaves = 1
        return n_leaves

    root = get_command(cli_main.app)
    n_leaves = walk(root, "rfauto")
    return {"top_level": top, "leaf_paths": leaves, "n_leaves": n_leaves,
            "n_top": len(top)}


def _mcp_snapshot() -> dict:
    """MCP 工具/资源注册序快照（list_tools 返回序=注册序）。"""
    pytest.importorskip("fastmcp")
    import asyncio

    from rfauto import mcp_server

    tools = asyncio.run(mcp_server.mcp.list_tools())
    resources = asyncio.run(mcp_server.mcp.list_resources())
    return {"tool_names_order": [t.name for t in tools],
            # 资源身份取 uri（str(Resource) 的 repr 含对象地址——跨进程
            # 不稳定，金快照会假红）
            "resources": sorted(str(getattr(r, "uri", r)) for r in resources)}


def test_cli_top_level_registration_order():
    """89 顶层命令/组注册序逐位=金快照（新增/重排=显式评审+重钉）。"""
    gold = json.loads(_GOLD_CLI.read_text(encoding="utf-8"))
    snap = _cli_tree_snapshot()
    assert snap["n_top"] == len(gold["top_level"]), (
        f"顶层命令数漂移: {snap['n_top']} != {len(gold['top_level'])}")
    assert snap["top_level"] == gold["top_level"], (
        "CLI 顶层注册序漂移（拆分/新增/重排须显式评审+重钉金快照）")


def test_cli_leaf_paths_registration_order():
    """叶命令深度优先注册序逐位=金快照（E2-8：失败消息改动态 len 防再陈旧）。"""
    gold = json.loads(_GOLD_CLI.read_text(encoding="utf-8"))
    snap = _cli_tree_snapshot()
    assert snap["n_leaves"] == 297, (
        f"叶命令数漂移: {snap['n_leaves']} != 297（check_numbers CLI 口径；"
        "aurora_p G2 2026-11-02 remote board +1 重钉——服务器队列看板叶"
        "（方向 G\"服务器队列可视化（remote 面板增强为实时队列看板）\""
        "闭合：四源 probe/status/queue/mutex 既有 service 读面纯聚合——"
        "单快照=机器表+队列任务表+互斥状态+异常降级行；单叶双形态——缺省"
        "一次性快照零循环零落盘逐字节同 service 直调，--refresh N 显式"
        "循环 Ctrl+C 优雅停轮间隔下限复用 speculative_watch_service."
        "MIN_INTERVAL_S 单源，--json-out 用户显式路径快照导出；#105 单源"
        "失败降级行留痕不炸板，凭据/主机名不落信封——机器只以注册表键名"
        "出现，零数值逻辑转发新建 service/remote_board_service，带 "
        "--json）；上锚="
        "aurora_p G1 2026-11-02 cal-wizard trl +1 重钉——TRL 校准件设计"
        "向导叶（方向 G\"TRL/校准件设计的用户向导面（当前只有内核+CLI）\""
        "闭合：频带+介质三口径 → Thru/Reflect/Line 设计单——λg/4 Line、"
        "8:1 覆盖三态核算、多 Line 等比分带、Reflect 短路/开路建议；"
        "--out-dir 落盘设计单 JSON/calkit 定义 YAML/测试连接图 .drawio "
        "三件固定名；设计数学=新建 core/trl_design 教科书锚在内核 "
        "docstring、微带 εeff 走 synthesis 单源，零数值逻辑转发新建 "
        "service/cal_wizard_service，带 --json）；上锚="
        "aurora_p F2 2026-11-02 watchdog watch +1 重钉——seat 粒度三证判活 "
        "CLI 出口叶（T-O12 service/watchdog_service 常驻形态接线：单叶双"
        "形态——一次性视图=缺省动作零后台线程零文件写逐字节同 service 直调；"
        "--watch 常驻循环显式开启，jsonl 落白名单 runs/watchdog/，Ctrl+C "
        "优雅停；target 三形态透传 pid/census 指纹/None 产物证；轮间隔下限"
        "复用 speculative_watch_service.MIN_INTERVAL_S 单源，零数值逻辑"
        "转发既有 service/watchdog_service，带 --json）；上锚="
        "aurora_p C3 2026-11-01 diagram to-svg +1 重钉——.drawio→SVG 纯 "
        "Python 渲染叶（报告/服务器场景无 draw.io 桌面 GUI 的看图件：框+"
        "连线+文字坐标直映射零重算（铁律 7），样式支持子集常量表单源 "
        "core/drawio_svg，不支持形态降级占位框+warnings 显式回显，压缩页"
        "显式报错，UserObject 包装 label 原样渲染（placeholders 替换 v2 "
        "不做）；XML 读面走 T-O2 core/drawio_xml + 渲染端补扫，"
        "零数值逻辑转发 service/drawio_svg_service，带 --json）；上锚="
        "aurora_p A1 2026-11-01 diagram schematic +1 重钉——引脚级原理图 "
        ".drawio 生成叶（与既有框图级五叶互补：元件符号带引脚点子 cell、"
        "连线引脚到引脚、网名标注在连线上；输入=ADS 网表——模板族渲染或 "
        ".net 文件二选一；网表参数原值原样标注零换算（铁律 7）；XML 走 T-O2"
        " core/drawio_xml 内核，解析器装配=新建 core/schematic_diagram，"
        "零数值逻辑转发 service/schematic_diagram_service，带 --json）；上锚="
        "aurora_o T-O4 2026-11-01 ads-circuit +3 重钉——ADS 前仿链人机回路三叶"
        "（用户核心需求'画电路图→带入 ADS 仿真→人工调参回路'：J1 diagram 出图"
        " UserObject 三件组 p_<key>/unit_<key>/src_<key> → J2 draw.io Edit Data "
        "改值 → J3 run 读图→三态合参[--params>图值>族缺省]→渲染→hpeesofsim→"
        "解析→指标→对拍 → J4 反标注 annot_sim 层上图 → J5 迭代；annotate 叶="
        "离线重放只反标注不重跑；MVP 钉死 wilkinson_snp/branchline_cascade "
        "两族，HB/有源两模板 out-of-spec 显式；零数值逻辑转发 "
        "service/circuit_sim_service，全叶带 --json）；上锚="
        "aurora_o T-O3 2026-11-01 diagram stackup +1 重钉——PCB 叠层横截面图"
        " .drawio 生成叶（层带高度正比厚度比例尺+材料/厚度/er/zmin 标注+线宽"
        "双箭头标注；标注数字=叠层 JSON 原值原样零换算（铁律 7），可选 "
        "--width-synth 线宽走 core/synthesis.nominal_width_mm 单源逐位直通，"
        "XML 走 T-O2 core/drawio_xml 内核，零数值逻辑转发 "
        "service/diagram_stackup_service，带 --json）；上锚="
        "aurora_o T-O8 2026-11-01 diagram annotate +1 重钉——评审标注双层"
        " .drawio 生成叶（底图层锁定+标注层三件组：三色圈/编号/右侧意见栏/"
        "虚线关联；底图两族=既有 .drawio 层级 locked / 外部 PNG-JPEG 位图 "
        "style 五旗标锁；意见文本/优先级/区域=标注 JSON 原值原样标注零换算"
        "（铁律 7），target 指错对象显式报错，形态规格单源 runs/aurora_o/"
        "design_specs/T-O8_ANNOTATION_SPEC.md，零数值逻辑转发 "
        "service/diagram_annotation_service，带 --json）；上锚="
        "aurora_o T-O6 2026-11-01 diagram testsetup +1 重钉——射频测试连接图"
        " .drawio 生成叶（与 T-O1 互补的纯声明式一极：仪器卡/端口点子 cell/"
        "正交连线/校准面 ▎CAL 子 label/注记，图上损耗/长度=用户 JSON 原值"
        "原样标注零换算（铁律 7），端口引用完整性四负例显式报错，XML 走 T-O2"
        " core/drawio_xml 内核，零数值逻辑转发 "
        "service/diagram_testsetup_service，带 --json）；上锚="
        "aurora_o T-O5 2026-11-01 design-report +1 重钉——设计回放与总结报告叶"
        "（六节 md 单文件：目标摘要/轨迹回放/最终设计与门表/电路图/敏感性/"
        "复现命令，优化族 run 此前无报告出口本叶补主缺口；门表单目标拆分调 "
        "core/objectives cost 语义单源、缺键 UNKNOWN 不凑 PASS；provenance="
        "bare_number_fields 全模型判零，零数值逻辑转发 "
        "service/design_replay_report，带 --json）；上锚="
        "aurora_o T-O1 2026-10-31 diagram link +1 重钉——RF 链路框图 .drawio "
        "生成叶（算画同源第一件：原生可编辑 mxGraph 工程图，每级标增益/NF+"
        "级联累计（Friis 公式），数字=内核单源 core/budget.py LinkBudget，"
        "XML 装配自研 core/link_diagram 零第三方依赖零 AGPL 复制，零数值"
        "逻辑转发 service/diagram_service，带 --json）；上锚="
        "aurora_n O4 2026-10-31 al propose +1 重钉——主动学习采样提议叶"
        "（T-N9 宿主 propose_next_points 运行时门，zero_wiring REGISTRY O4 "
        "旧面欠账清偿；三形态样本装载 samples.json/数据集/run trials，缺省"
        "σ 求和旧路径逐字节转发 + --acquisition 采集三族 lcb/ucb/ei/sigma "
        "+ registry σ 源 + conformal_fallback，零数值逻辑转发 "
        "service/al_service，带 --json）；上锚="
        "aurora_n O5 2026-10-31 competition run +1 重钉——单目标优化器族竞赛"
        "持久门叶（T-N5 标量竞赛架运行时门，zero_wiring REGISTRY O5 欠账清偿"
        "；同预算同 seed 组竞赛 AUC 两阶段+达标次数三套排名，内置合成 4 族与"
        "首榜同源，botorch_ei 显式点名 opt-in，零数值逻辑转发 "
        "service/competition_service，带 --json）；上锚="
        "aurora_n O1 2026-10-31 mo run +1 重钉——多目标 BO 合成族环叶（T-N13 "
        "MultiObjectiveBO 运行时门，zero_wiring REGISTRY O1 欠账清偿；内置"
        "合成族 kind/n_eval 预算/mt_gp 缺省代理→HV 曲线+帕累托前沿+采集轨迹"
        "信封，零数值逻辑转发 service/mo_bo_service，带 --json）；上锚="
        "aurora_n T-N20 2026-10-29 surrogate export-onnx +1 重钉——torch 系"
        "代理（fno/deep_ensemble/siren）现场重拟合并导出 ONNX 叶（kind+"
        "samples+config JSON→fit→dynamo 导出器 opset18→protobuf "
        "deterministic 规范化落盘，导出-回代对拍内置，零数值逻辑转发 "
        "service/surrogate_export_service，带 --json）；上锚="
        "aurora_k K18 2026-10-23 em diff +1 重钉——run 目录级四面对比叶"
        "（P17/F13：替代手工 diff .aedt 文本——meta params 逐键/K5 模型清单"
        "按 name 逐项[aperture z 验收靶]/Touchstone S 参数同栅对拍/K4 新鲜"
        "度交叉，零逻辑转发 service/em_diff_service，带 --json）；上锚="
        "aurora_k K10 2026-10-23 em sweep +1 重钉——DOE/矩阵编排叶（P16/F9："
        "cases.yaml 笛卡尔全积展开→逐 case 串行执行[内存闸+janitor 资源防线]"
        "→summary.csv/json 汇总，零逻辑转发 service/em_sweep_service，带 "
        "--json）；上锚=aurora_k K8 2026-10-23 em deembed+metrics +2 重钉"
        "——THRU 对称半拆"
        "双边去嵌叶+串联/并联器件 Z12/Y11 指标提取叶（反馈 F6/P14，零逻辑"
        "薄壳直连 core/deembed K8 扩展纯函数面，calc_vna oracle 叶 A-11 同"
        "款只读出口，全叶带 --json）；上锚=aurora_k K5 2026-10-23 em doctor"
        " +1 重钉——自定义 EM 模型清单体检叶（P12/F8：清单驱动的 pre-solve "
        "几何/端口语义检查器，零 AEDT 依赖，带 --json）；上锚=aurora_k K4 "
        "2026-10-23 runs verify +1 重钉——run 产物新鲜度校验叶"
        "（manifest 收官指纹 vs 盘上 Touchstone，P11/F7 交付错配防线，带 "
        "--json）；上锚=aurora_e W3-S4 2026-10-19 campaign digest +1 重钉"
        "——战役终态 zh 摘要聚合叶（campaign 域内追加，手动单节触发，全带 "
        "--json）；上锚=aurora_g W8-S4 2026-10-19 +3 重钉——verdict-summary "
        "顶层叶（verdict 人读摘要出口）+ runs compare-batch（多 run 收官对"
        "账）+ datasets profile（数据集一键画像），全叶带 --json）")
    assert snap["leaf_paths"] == gold["leaf_paths"], (
        "CLI 叶命令注册序漂移（同族段内次序是 AU-1B4 钉的镜像面）")


def test_mcp_tool_and_resource_order():
    """132 个 MCP 工具注册序 + 资源清单=金快照（批3 拆分对账面转正）。"""
    gold = json.loads(_GOLD_MCP.read_text(encoding="utf-8"))
    snap = _mcp_snapshot()
    assert len(snap["tool_names_order"]) == 166, (
        f"MCP 工具数漂移: {len(snap['tool_names_order'])} != 166"
        "（check_numbers MCP 口径；aurora_p 席 B2 2026-11-01 +2 重钉——"
        "ads_circuit_annotate（annotate 叶 v2 扩展位落位，离线反标注，"
        "零逻辑转发 circuit_sim_service.annotate_circuit_diagram）+"
        "design_report（CLI design-report 叶同源设计回放报告，零逻辑转发 "
        "design_replay_report.generate_design_report）；上锚="
        "aurora_o 开放池席 o_ads 2026-11-01 +2 重钉——"
        "ads_circuit_diagram/ads_circuit_run（T-O4 ADS 前仿链 MCP 两面，"
        "T-O4_ADS_UX_SPEC §5.1 v1 列项，CLI ads-circuit 域同源，零逻辑转发 "
        "service/circuit_sim_service；annotate 叶留 v2 最小面）；上锚="
        "aurora_n MCP 接线补齐席 2026-10-31 +4 重钉——"
        "surrogate_export_onnx（T-N20 ONNX 导出，CLI surrogate export-onnx "
        "同源）+surrogate_uq（代理 MC UQ，uq_service.surrogate_yield 同形）"
        "+al_propose（O4 T-N9 采集三族运行时门）+competition_run（O5 T-N5 "
        "标量竞赛架运行时门；持久落盘面留 CLI 叶，MCP 零写盘）；上锚="
        "aurora_n O1 2026-10-31 mo_run +1 重钉——"
        "多目标 BO 合成族环工具（T-N13 MultiObjectiveBO 运行时门，zero_wiring "
        "REGISTRY O1 欠账清偿，零逻辑转发 service/mo_bo_service）；上锚="
        "aurora_l Wave-C C1 2026-10-23 em 族五只读"
        "薄壳 +5 重钉——em_doctor_check/runs_verify/em_diff_runs/"
        "em_metrics_from_run/em_sweep_plan（反馈 F5：runs/ 历史、质量门判读、"
        "收敛门结论直喂 Agent；零逻辑转发 em_doctor/runs_verify/em_diff/"
        "em_metrics/em_sweep service 单源，sweep 执行面不上 MCP）；上锚="
        "edb 快车道 2026-10-08 edb_emit_spec/edb_build_solve/edb_status +3；"
        "上锚=W6 2026-10-06 start_tune/run_sweep/preflight_run +3）")
    assert snap["tool_names_order"] == gold["tool_names_order"], (
        "MCP 工具注册序漂移")
    assert snap["resources"] == gold["resources"], "MCP 资源清单漂移"


def _write_gold() -> None:
    _GOLD_DIR.mkdir(parents=True, exist_ok=True)
    cli = _cli_tree_snapshot()
    _GOLD_CLI.write_text(
        json.dumps(cli, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    mcp = _mcp_snapshot()
    _GOLD_MCP.write_text(
        json.dumps(mcp, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    print(f"gold written: {_GOLD_CLI.name} (top={cli['n_top']}, "
          f"leaves={cli['n_leaves']}), {_GOLD_MCP.name} "
          f"(tools={len(mcp['tool_names_order'])})")


if __name__ == "__main__":
    if "--write-gold" in sys.argv:
        _write_gold()
    else:
        print(__doc__)
        print("用法: python tests/unit/test_cli_registration_order.py "
              "--write-gold")
