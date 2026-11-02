"""ads_circuit_diagram/ads_circuit_run/ads_circuit_annotate（ADS 前仿链
MCP 薄壳）（aurora_o 开放池席 o_ads 件4，2026-11-01；aurora_p 席 B2 补
annotate 反标注面，2026-11-01；T-O4_ADS_UX_SPEC §5.1 v1 列项+扩展位）。

CLI ads-circuit 域（cli/domains/ads_circuit.py 三叶）的 MCP 三面：
diagram（J1 出图，零 ADS 接触）+ run（J3+J4 一条龙）+ annotate（离线
反标注，只上图不重跑——spec §5.1 v2 扩展位落位）。

零数值逻辑转发 service/circuit_sim_service 同名函数（规则 4）；信封
同构（ok+errors）；网表数值只出自确定性渲染器（铁律 7）。mutating 面
如实声明：三工具写盘（out/out_dir 参数指向的路径），零删除零改稿
（diagram 原图/SnP 只读——circuit_sim_run 契约）。真机求解走
ads_netlist 正规 env 入口（#272/#295 由既有链处理，本壳零绕行）。
"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import mcp as mcp


@mcp.tool
def ads_circuit_diagram(
    family: str,
    snp: str,
    out: str,
    params: dict[str, Any] | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    """ADS 前仿链出图（ads-circuit 域）：族+Touchstone → 参数化电路图 .drawio。

    J1 出图（不触 ADS）：模板族 → UserObject 三件组（p_<key>/unit_<key>/
    src_<key>）参数化电路图，draw.io 右键元件卡 Edit Data 改 p_* 值=改参
    唯一交互形态。四族枚举见 family 参数（cascade 须 4 端口 SnP；有源
    两族出图需 params 显式给必给参数）。写盘面=``out`` 指向的 .drawio
    文件（父目录须已存在）；SnP 只读。同输入两次运行文件逐字节相同
    （确定性）。失败 → ok=False errors 信封。

    Args:
        family: 模板族名（四族：wilkinson_snp/branchline_cascade/
            active_chain_sparam/loadpull_hb）
        snp: Touchstone 文件路径（端口数实读，图上端口卡数=实读 N）
        out: 输出 .drawio 路径（父目录须已存在）
        params: 参数覆盖 JSON 对象（flat dotted 键如 {"theta_in_deg": 55}
            或嵌套 {"sweep": {"fstart": 1.6}}；缺省=族缺省值；sweep 频带
            三项留空上图=随 SnP 频带语义）
        title: 图标题文本（缺省用内核缺省标题）

    Returns:
        dict: {ok, out_path, family, n_ports, n_params, values: {key:
        {value, source}}}
    """
    from rfauto.service.circuit_sim_service import generate_circuit_diagram
    from rfauto.service.envelope import error_envelope

    try:
        return generate_circuit_diagram(family, snp, out, params=params,
                                        title=title)
    except Exception as e:
        return error_envelope(f"{type(e).__name__}: {e}")


@mcp.tool
def ads_circuit_run(
    diagram: str,
    snp: str,
    out_dir: str,
    params: dict[str, Any] | None = None,
    family: str | None = None,
    ads_dir: str | None = None,
    compare: bool = True,
    gate: float | None = None,
) -> dict[str, Any]:
    """ADS 前仿链一条龙（ads-circuit 域）：读图→三态合参→渲染→求解→指标→对拍→反标注。

    J3+J4 一条龙（渲染网表→hpeesofsim→解析→系统指标→反标注上图）：
    三态优先级 --params JSON > 图值 > 族缺省（逐键带来源回显 effective
    节）；网表数值只出自确定性渲染器（铁律 7）；求解走 ads_netlist 正规
    env 入口（#272/#295 既有链处理，真机 solo #246）。写盘面=out_dir
    工作目录；diagram 与 SnP 只读（原稿是模板）。反标注 annot_sim 层
    幂等替换不堆积，draw.io 重开即见指标（J5 迭代）。ADS 段失败如实
    ok=False 降级反标注（不虚构指标，#105）。

    Args:
        diagram: 电路图 .drawio 路径（只读；须 ads_circuit_diagram 产物）
        snp: Touchstone 文件路径（网表 File 来源；须纯 ASCII 路径）
        out_dir: 工作目录（必填——缺省拒跑防 cwd 相对落真实 runs/ 湖）
        params: 参数覆盖 JSON 对象（三态最高优先：--params > 图值 >
            族缺省；flat dotted 或嵌套 sweep 形态）
        family: 显式族名核对（与图内 family 不一致=报错防张冠李戴；
            缺省=信图内标注）
        ads_dir: ADS 安装根（缺省 env RFAUTO_HPEESOF_DIR → settings）
        compare: 是否对拍（SnP 直通/级联闭式参考，缺省开启）
        gate: 对拍门 max|ΔS| 上限（缺省 1e-3）

    Returns:
        dict: {ok, family, netlist_path, result_path,
        annotated_diagram_path, effective, sweep, metrics, compare, ads,
        warnings, annotated}
    """
    from rfauto.service.circuit_sim_service import circuit_sim_run
    from rfauto.service.envelope import error_envelope

    try:
        return circuit_sim_run(
            diagram, snp_path=snp, out_dir=out_dir, params_override=params,
            family=family, ads_dir=ads_dir, compare=compare, gate=gate)
    except Exception as e:
        return error_envelope(f"{type(e).__name__}: {e}")


@mcp.tool
def ads_circuit_annotate(
    diagram: str,
    result: str,
    out: str,
    curves: bool = False,
) -> dict[str, Any]:
    """ADS 前仿链离线反标注（ads-circuit 域）：原图+结果 JSON → 指标上图，不重跑仿真。

    消费 ads_circuit_run 产物 <family>_circuit_result.json（含 circuit
    节=指标源），指标卡写进 annot_sim 层（幂等替换不堆积）；原图零
    改动。ADS 段失败只装 error 头卡（不虚构指标）。同图同 result 两次
    反标注逐字节相同。curves=True 时另嵌 sim_g 曲线卡（result 无
    curves 节如实跳过）。写盘面=out 的 .drawio（父目录须已存在；须异于
    diagram，禁覆盖原稿）。缺文件/缺 circuit 节 → ok=False 信封。

    Args:
        diagram: 原图 .drawio 路径（只读；可为已反标注图）
        result: circuit_result JSON 路径（须 ads_circuit_run 产物；裸
            run_ads_template 的 <family>_result.json 无指标不消费）
        out: 输出 .drawio 路径（父目录须已存在；须异于 diagram）
        curves: 是否嵌入 S 参数曲线卡（opt-in 缺省关=行为同既有；result
            无 circuit.curves 节时 warnings 如实注记不出卡）

    Returns:
        dict: {ok, out_path, n_cards, annot_layer}
    """
    from rfauto.service.circuit_sim_service import annotate_circuit_diagram
    from rfauto.service.envelope import error_envelope

    try:
        return annotate_circuit_diagram(diagram, result, out,
                                        with_curves=curves)
    except Exception as e:
        return error_envelope(f"{type(e).__name__}: {e}")
