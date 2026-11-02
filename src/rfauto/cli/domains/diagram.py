"""diagram 子应用（电路图绘制面；aurora_o T-O1 接线席，2026-10-31）。

叶 link：RF 链路框图 .drawio 生成（"算画同源"第一件——产出**原生
可编辑** drawio 工程图而非截图：每级框内标级名+本级增益/NF+该级之后
级联累计 ΣG·ΣNF（Friis 公式），链尾级联总计框；mxGraph XML 格式开放
规范（JGraph，Apache-2.0），装配器自研零复制）。数字全部来自确定性
内核（core/budget.py LinkBudget——Friis 级联单源，铁律 7 禁手抄数字）。
零数值逻辑转发 service/diagram_service（规则 4）；带 --json（信封契约）。

叶 testsetup（aurora_o T-O6 接线席，2026-11-01）：射频测试连接图 .drawio
生成（与 link 互补的纯声明式一极——仪器卡/端口点/正交连线/校准面标记，
图上损耗/长度=用户 JSON 原值原样标注零换算；零数值逻辑转发
service/diagram_testsetup_service，带 --json）。

叶 annotate（aurora_o T-O8 接线席，2026-11-01）：评审标注双层 .drawio
生成（底图层锁定+标注层三件组：三色圈/编号/右侧意见栏/虚线关联——
底图两族：既有 .drawio 层级锁定 / 外部 PNG-JPEG 位图底图五旗标锁；
意见文本/优先级/区域=标注 JSON 原值原样标注零换算；零数值逻辑转发
service/diagram_annotation_service，带 --json）。

叶 stackup（aurora_o T-O3 接线席，2026-11-01）：PCB 叠层横截面图 .drawio
生成（层带高度∝厚度比例尺+材料/厚度/εr/zmin 标注+线宽双箭头标注；
标注数字=叠层 JSON 原值原样零换算，可选 --width-synth 线宽走
core/synthesis.nominal_width_mm 单源——数字逐位直通零手抄；零数值逻辑
转发 service/diagram_stackup_service，带 --json）。aurora_p A5
（2026-11-01）加 --preview PATH 可选旗标：同一叠层输入另出 3D 等轴预览
PNG（core/stackup_preview，matplotlib 自绘、ASCII 标注、确定性逐字节）；
缺省不给旗标时 .drawio 输出与信封零变化。

叶 schematic（aurora_p A1 接线席，2026-11-01）：引脚级原理图 .drawio
生成（与既有框图级五叶互补：元件符号带引脚点子 cell、连线引脚到引脚、
网名标注在连线上；输入=ADS 网表（模板族渲染或 .net 文件二选一）；
网表参数原值原样标注零换算；零数值逻辑转发
service/schematic_diagram_service，带 --json）。

叶 to-svg（aurora_p C3 接线席，2026-11-01）：.drawio → 静态 SVG 纯 Python
渲染（报告/服务器场景无 draw.io 桌面 GUI 的看图件；v1 初级形态=框+连线+
文字直映射：vertex→矩形+文字、edge→直线/折线、layer→<g> 分组；几何=
drawio 坐标直映射零重算、文字=value 原值原样；样式支持子集为
core/drawio_svg 常量表单源，不支持形态（image/曲线边/rotation 等）降级
占位框+warnings 显式列出；压缩页显式报错；零数值逻辑转发
service/drawio_svg_service，带 --json）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import typer

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import _emit_usage_error as _emit_usage_error
from rfauto.cli.domains._core import _load_json_file as _load_json_file
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console
from rfauto.service.envelope import error_envelope

diagram_app = typer.Typer(
    help="电路图绘制六叶（前五叶出原生可编辑 .drawio 工程图，算画同源；"
         "to-svg 出静态 SVG 看图件）："
         "link=RF 链路框图（每级标增益/NF，Friis 级联内核单源）；"
         "testsetup=射频测试连接图（仪器卡+连线，标注=输入原值）；"
         "annotate=评审标注双层（底图锁定+三色意见栏）；"
         "stackup=PCB 叠层横截面（层带∝厚度，线宽可选综合单源）；"
         "schematic=引脚级原理图（ADS 网表，元件带引脚点+引脚到引脚连线"
         "+网名标注）；"
         "to-svg=.drawio→SVG 纯 Python 渲染（服务器/报告无 GUI 看图件，"
         "框+连线+文字坐标直映射，不支持样式降级占位+warnings）")
app.add_typer(diagram_app, name="diagram")


@diagram_app.command("link")
def diagram_link_cmd(
    chain: str = typer.Option(
        None, "--chain",
        help="级表 JSON 串（数组，顺序=信号流向，级 schema 严格三键 "
             "name/gain_db/nf_db；与 --chain-file 恰给一）"),
    chain_file: str = typer.Option(
        None, "--chain-file",
        help="级表 JSON 文件路径（内容=同一 schema 的数组；与 --chain "
             "恰给一）"),
    out: str = typer.Option(
        ..., "--out", help="输出 .drawio 路径（父目录须已存在）"),
    title: str = typer.Option(
        None, "--title", help="图标题文本（缺省用内核缺省标题）"),
    json_output: bool = typer.Option(
        False, "--json", help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """生成 RF 链路框图 .drawio：级表 → 原生可编辑工程图（每级标数字）。

    示例（--chain 值为 JSON 数组，元素形如
    {"name":"LNA","gain_db":20,"nf_db":0.8}）：
    rfauto diagram link --chain <级表JSON> --out link.drawio

    数字单源：级联累计（Friis）全部来自确定性内核
    （core/budget.py LinkBudget），本叶零数值逻辑（薄壳转发
    service/diagram_service）。确定性：同输入两次运行文件逐字节相同。
    """
    from rfauto.service.diagram_service import generate_link_diagram

    if bool(chain) == bool(chain_file):
        _emit_usage_error(
            "--chain 与 --chain-file 恰给一（互斥且必给一）",
            json_output=json_output)
        return
    if chain_file:
        from pathlib import Path

        p = Path(chain_file)
        if not p.exists():
            _emit_usage_error(f"级表文件不存在: {p}", json_output=json_output)
            return
        try:
            chain = p.read_text(encoding="utf-8")
        except OSError as exc:
            _emit_usage_error(f"级表文件不可读: {exc}", json_output=json_output)
            return
    try:
        stages = json.loads(chain)
    except ValueError as exc:
        _emit_usage_error(f"--chain 不是合法 JSON: {exc}",
                          json_output=json_output)
        return

    result = generate_link_diagram(stages, out, title=title)
    if json_output:
        _emit(result, "链路框图生成失败", json_output=True)
        return
    if not result.get("ok"):
        console.print("[red]✗ 链路框图生成失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)

    console.print(
        f"[bold]RF 链路框图[/bold]  {result['n_stages']} 级  "
        f"级联 ΣG={result['gain_total_db']:.2f} dB  "
        f"ΣNF={result['nf_total_db']:.2f} dB（Friis，内核单源）")
    for i, st in enumerate(result.get("stages") or [], 1):
        console.print(
            f"  #{i} {st['name']}  G={st['gain_db']:.2f} dB  "
            f"NF={st['nf_db']:.2f} dB  "
            f"ΣG={st['cumulative_gain_db']:.2f} dB  "
            f"ΣNF={st['cumulative_nf_db']:.2f} dB")
    console.print(f"[green]✓ 已写出[/green] {result['out_path']}"
                  "（draw.io/VS Code Draw.io 插件可打开编辑）")


@diagram_app.command("testsetup")
def diagram_testsetup_cmd(
    scene: str = typer.Option(
        None, "--scene",
        help="场景 JSON 串（顶层四键 title/instruments/connections/notes："
             "仪器卡严格六键 id/kind/label/role/ports/note、连接边严格五键 "
             "from/to/cable/cal_plane/label、注记卡两键 text/anchor；"
             "与 --scene-file 恰给一）"),
    scene_file: str = typer.Option(
        None, "--scene-file",
        help="场景 JSON 文件路径（内容=同一 schema 的对象；与 --scene "
             "恰给一）"),
    out: str = typer.Option(
        ..., "--out", help="输出 .drawio 路径（父目录须已存在）"),
    title: str = typer.Option(
        None, "--title", help="图标题文本（缺省用场景 title，再缺省内核标题）"),
    json_output: bool = typer.Option(
        False, "--json", help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """生成射频测试连接图 .drawio：声明式场景 → 原生可编辑工程图
    （仪器卡+端口点+正交连线+校准面标记+注记）。

    示例：rfauto diagram testsetup --scene-file scene.json --out
    testsetup.drawio（scene.json=声明式场景对象，顶层四键
    title/instruments/connections/notes：仪器卡给 id/kind/label/ports，
    连接边给 from/to 与 cable 标注）。

    纯声明式生成器：图上损耗/长度数字=用户 JSON 原值原样标注（零换算
    零 dB 运算，铁律 7），端口引用不存在/未声明端口显式报错（拓扑正确性
    第一验收面）。本叶零数值逻辑（薄壳转发
    service/diagram_testsetup_service）。确定性：同输入两次运行文件逐
    字节相同。
    """
    from rfauto.service.diagram_testsetup_service import (
        generate_testsetup_diagram,
    )

    if bool(scene) == bool(scene_file):
        _emit_usage_error(
            "--scene 与 --scene-file 恰给一（互斥且必给一）",
            json_output=json_output)
        return
    if scene_file:
        payload = _load_json_file(scene_file, "场景文件", json_output=json_output)
    else:
        try:
            payload = json.loads(scene)
        except ValueError as exc:
            _emit_usage_error(f"--scene 不是合法 JSON: {exc}",
                              json_output=json_output)
            return

    result = generate_testsetup_diagram(payload, out, title=title)
    if json_output:
        _emit(result, "测试连接图生成失败", json_output=True)
        return
    if not result.get("ok"):
        console.print("[red]✗ 测试连接图生成失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)

    console.print(
        f"[bold]测试连接图[/bold]  仪器 {result['n_instruments']} 台  "
        f"连接 {result['n_connections']} 条  "
        f"注记 {result['n_notes']} 条（声明式场景，标注零换算）")
    for w in result.get("warnings") or []:
        console.print(f"  [yellow]! {w}[/yellow]")
    console.print(f"[green]✓ 已写出[/green] {result['out_path']}"
                  "（draw.io/VS Code Draw.io 插件可打开编辑）")


@diagram_app.command("annotate")
def diagram_annotate_cmd(
    source: str = typer.Option(
        ..., "--source",
        help="底图路径（.drawio=形态 A 既有图层级锁定；.png/.jpg=形态 B "
             "外部位图底图；只读不覆盖——评审原稿不可变）"),
    annotations: str = typer.Option(
        ..., "--annotations",
        help="标注 JSON 串（顶层 summary+annotations 两键或裸数组，标注卡"
             "严格六键 id/region/priority/label/comment/target；以 @ 开头"
             "则读 JSON 文件路径，如 @ann.json）"),
    out: str = typer.Option(
        ..., "--out", help="输出 .drawio 路径（父目录须已存在；禁与 "
                           "--source 同路径——覆盖原稿显式报错）"),
    reviewer: str = typer.Option(
        None, "--reviewer", help="评审人署名（写入意见卡 reviewer 属性，"
                                 "可省）"),
    image_size: str = typer.Option(
        None, "--image-size",
        help="形态 B 显式像素尺寸 WxH（图片头解析失败兜底，如 1280x720）"),
    json_output: bool = typer.Option(
        False, "--json", help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """生成评审标注双层 .drawio：底图+标注表 → 底图层锁定+标注层三件组。

    示例：rfauto diagram annotate --source link.drawio --annotations
    @ann.json --out annotated.drawio（标注卡给 id/region/priority/label/
    comment，target 指底图被审元素 id，优先级三色映射 high=红/medium=橙/
    low=绿）。

    底图锁定语义（drawio 编辑器行为级）：形态 A=层 cell locked 属性、
    形态 B=底图 cell 五旗标 style 锁——评审人在 draw.io 中拖不动被审
    图元；意见文本/优先级/区域坐标=标注 JSON 原值原样标注（零换算零
    dB 运算，铁律 7），target 指错对象显式报错。本叶零数值逻辑（薄壳
    转发 service/diagram_annotation_service）。确定性：同输入两次运行
    文件逐字节相同。
    """
    from rfauto.service.diagram_annotation_service import annotate_diagram

    payload: object
    if annotations.startswith("@"):
        ann_path = annotations[1:]
        if not ann_path.strip():
            _emit_usage_error(
                "--annotations @ 后缺文件路径", json_output=json_output)
            return
        p = Path(ann_path)
        if not p.exists():
            _emit_usage_error(f"标注文件不存在: {p}", json_output=json_output)
            return
        try:
            payload = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            _emit_usage_error(f"标注文件不可读: {exc}", json_output=json_output)
            return
    else:
        try:
            payload = json.loads(annotations)
        except ValueError as exc:
            _emit_usage_error(f"--annotations 不是合法 JSON: {exc}",
                              json_output=json_output)
            return

    size: tuple[int, int] | None = None
    if image_size:
        m = re.fullmatch(r"(\d+)[xX](\d+)", image_size.strip())
        if not m:
            _emit_usage_error(
                "--image-size 格式应为 WxH（如 1280x720）",
                json_output=json_output)
            return
        size = (int(m.group(1)), int(m.group(2)))

    result = annotate_diagram(
        source, payload, out, reviewer=reviewer or None, image_size=size)
    if json_output:
        _emit(result, "评审标注生成失败", json_output=True)
        return
    if not result.get("ok"):
        console.print("[red]✗ 评审标注生成失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)

    console.print(
        f"[bold]评审标注图[/bold]  形态 {result['form']}  "
        f"标注 {result['n_annotations']} 条  "
        f"target 指示边 {result['n_target_edges']} 条"
        f"（底图锁定 base_locked={result['base_locked']}，"
        f"标注层 {result['layers']['annot']}）")
    for w in result.get("warnings") or []:
        console.print(f"  [yellow]! {w}[/yellow]")
    console.print(f"[green]✓ 已写出[/green] {result['out_path']}"
                  "（draw.io 打开：底图不可拖动，标注层可编辑）")


@diagram_app.command("stackup")
def diagram_stackup_cmd(
    stackup: str = typer.Option(
        None, "--stackup",
        help="叠层 JSON 串（顶层三键 title/layers/width_annotations：层卡"
             "严格五键 name/kind/thickness_mm/material/er（kind 枚举 signal/"
             "plane/dielectric）、线宽标注严格三键 layer/width_mm/note；"
             "与 --stackup-file 恰给一）"),
    stackup_file: str = typer.Option(
        None, "--stackup-file",
        help="叠层 JSON 文件路径（内容=同一 schema 的对象；与 --stackup "
             "恰给一）"),
    out: str = typer.Option(
        ..., "--out", help="输出 .drawio 路径（父目录须已存在）"),
    title: str = typer.Option(
        None, "--title", help="图标题文本（缺省用叠层 title，再缺省内核标题）"),
    width_synth: str = typer.Option(
        None, "--width-synth",
        help="合成单源线宽规格 JSON（对象或对象数组，严格键 layer/z0_ohm/"
             "freq_ghz/stackup_name/digits/note/materials_path，前四必填；"
             "stackup_name=configs/materials.yaml 层叠键，线宽经 "
             "core/synthesis.nominal_width_mm 单源算出后原值标注）"),
    preview: str = typer.Option(
        None, "--preview",
        help="可选：另出 3D 等轴预览 PNG 到此路径（父目录须已存在；同一叠层"
             "输入，层 slab 高度∝厚度同比例尺 200px/mm，图内标注=输入原值、"
             "一律 ASCII；缺省不给则不出图，.drawio 输出零变化）"),
    json_output: bool = typer.Option(
        False, "--json", help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """生成 PCB 叠层横截面图 .drawio：声明式叠层 → 原生可编辑工程图
    （层带高度∝厚度+材料/厚度/εr/zmin 标注+线宽双箭头标注）。

    示例：rfauto diagram stackup --stackup-file stackup.json --out
    stackup.drawio（stackup.json=声明式叠层对象，layers 自顶向下给
    name/kind/thickness_mm，介质层可给 material/er）；加
    --width-synth 传对象（键 layer/z0_ohm/freq_ghz/stackup_name）
    则线宽走 core/synthesis.nominal_width_mm 单源；加 --preview
    stackup.png 另出 3D 等轴预览 PNG（报告附件/快速视检件）。

    数字单源：层带标注=叠层 JSON 原值原样（零换算，铁律 7）；合成线宽=
    nominal_width_mm 返回值逐位直通（零手抄），信封逐条回显 source。
    本叶零数值逻辑（薄壳转发 service/diagram_stackup_service）。确定性：
    同输入两次运行文件逐字节相同（.drawio 与预览 PNG 均是）。
    """
    from rfauto.service.diagram_stackup_service import (
        generate_stackup_diagram,  # lazy: startup-cost（cli 注册根轻载，见 docs/explanation/lazy-import-conventions.md）
    )

    if bool(stackup) == bool(stackup_file):
        _emit_usage_error(
            "--stackup 与 --stackup-file 恰给一（互斥且必给一）",
            json_output=json_output)
        return
    if stackup_file:
        p = Path(stackup_file)
        if not p.exists():
            _emit_usage_error(f"叠层文件不存在: {p}", json_output=json_output)
            return
        try:
            stackup = p.read_text(encoding="utf-8")
        except OSError as exc:
            _emit_usage_error(f"叠层文件不可读: {exc}", json_output=json_output)
            return
    try:
        payload = json.loads(stackup)
    except ValueError as exc:
        _emit_usage_error(f"叠层 JSON 不合法: {exc}", json_output=json_output)
        return
    synth: object = None
    if width_synth is not None:
        try:
            synth = json.loads(width_synth)
        except ValueError as exc:
            _emit_usage_error(f"--width-synth 不是合法 JSON: {exc}",
                              json_output=json_output)
            return

    result = generate_stackup_diagram(payload, out, title=title,
                                      width_synthesis=synth)
    # --preview（aurora_p A5）：.drawio 成功后同输入另出 3D 等轴 PNG；缺省
    # None 时本段零动作（既有输出与信封逐字节不变）
    preview_result: dict | None = None
    if preview is not None and result.get("ok"):
        from rfauto.service.diagram_stackup_service import (
            generate_stackup_preview,  # lazy: startup-cost（cli 注册根轻载，见 docs/explanation/lazy-import-conventions.md）
        )

        preview_result = generate_stackup_preview(payload, preview, title=title)
    if json_output:
        if preview_result is not None:
            result = {**result, "preview": preview_result}
            if not preview_result.get("ok"):
                # 预览失败=本次请求未完整达成：顶层翻失败信封（.drawio 已写出的
                # 回显字段与 preview 子信封原样保留，不隐瞒不凑绿）
                result = error_envelope(
                    [f"3D 预览生成失败: {e}"
                     for e in preview_result.get("errors") or []],
                    **{k: v for k, v in result.items() if k != "ok"})
        _emit(result, "叠层图生成失败", json_output=True)
        return
    if not result.get("ok"):
        console.print("[red]✗ 叠层图生成失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)

    # markup 纪律（campaign 叶 ge8e 同款）：人读分支动态段（层名/kind/
    # warnings 可含 "[...]"）一律 rich.markup.escape，防被当样式标签吞掉
    from rich.markup import escape

    console.print(
        f"[bold]PCB 叠层图[/bold]  {result['n_layers']} 层  "
        f"线宽标注 {result['n_width_annotations']} 条"
        "（层带高度∝厚度；标注=输入原值/合成单源）")
    for lay in result.get("layers") or []:
        er = f"  εr {lay['er']}" if lay.get("er") is not None else ""
        console.print(escape(
            f"  #{lay['index']} {lay['name']} [{lay['kind']}]  "
            f"{lay['thickness_mm']} mm{er}  zmin={lay['zmin_mm']} mm"))
    for ann in result.get("width_annotations") or []:
        console.print(escape(
            f"  线宽 {ann['layer']}: {ann['width_mm']} mm（{ann['source']}）"))
    for w in result.get("warnings") or []:
        console.print(f"  [yellow]! {escape(w)}[/yellow]")
    console.print(f"[green]✓ 已写出[/green] {escape(result['out_path'])}"
                  "（draw.io/VS Code Draw.io 插件可打开编辑）")
    if preview_result is not None:
        if not preview_result.get("ok"):
            console.print("[red]✗ 3D 预览生成失败[/red]")
            for err in preview_result.get("errors") or []:
                console.print(f"  [red]- {escape(err)}[/red]")
            raise typer.Exit(code=1)
        canvas = preview_result.get("canvas") or {}
        console.print(escape(
            f"  3D 预览 {canvas.get('w_px')}x{canvas.get('h_px')}px  "
            f"{preview_result['n_layers']} 层  总厚 "
            f"{preview_result['total_thickness_text']} {preview_result['unit']}"
            "（等轴投影；slab 高度∝厚度，标注=输入原值）"))
        for w in preview_result.get("warnings") or []:
            console.print(f"  [yellow]! {escape(w)}[/yellow]")
        console.print(f"[green]✓ 预览已写出[/green] "
                      f"{escape(preview_result['out_path'])}")


@diagram_app.command("schematic")
def diagram_schematic_cmd(
    net: str = typer.Option(
        None, "--net",
        help="ADS 网表文件路径（.net 文本；与 --family 恰给一）"),
    family: str = typer.Option(
        None, "--family",
        help="模板族名 wilkinson_snp 或 branchline_cascade（经族渲染器出"
             "网表再建图；与 --net 恰给一，且须配 --snp）"),
    snp: str = typer.Option(
        None, "--snp",
        help="Touchstone 路径（--family 形态必给；仅渲染器需读元信息时才"
             "访问文件——图面只消费其路径文本）"),
    params: str = typer.Option(
        None, "--params",
        help="族渲染器参数 JSON 串（对象，如 sweep/fstart/fstop/npoints/"
             "unit 与 n_ports/z0；可省）"),
    out: str = typer.Option(
        ..., "--out", help="输出 .drawio 路径（父目录须已存在）"),
    title: str = typer.Option(
        None, "--title", help="图标题文本（缺省用内核缺省标题）"),
    json_output: bool = typer.Option(
        False, "--json", help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """生成引脚级原理图 .drawio：ADS 网表 → 元件带引脚点+引脚到引脚
    连线+网名标注（与既有框图级电路图互补的原理图一极）。

    示例：rfauto diagram schematic --family branchline_cascade --snp
    demo.s4p --out schem.drawio；或直接给网表文件：rfauto diagram
    schematic --net netlist.net --out schem.drawio。

    图上参数（Z/E/F/Num 等与网名）=网表原值原样标注（零换算零数值解析，
    铁律 7）；网表严格校验（未知行/缺节点/缺必备参数显式报错）；悬空
    引脚红色虚线显式标记（无静默悬空）。本叶零数值逻辑（薄壳转发
    service/schematic_diagram_service）。确定性：同输入两次运行文件逐
    字节相同。
    """
    from rfauto.service.schematic_diagram_service import (
        generate_schematic_diagram,  # lazy: startup-cost（cli 注册根轻载，见 docs/explanation/lazy-import-conventions.md）
    )

    if bool(net) == bool(family):
        _emit_usage_error(
            "--net 与 --family 恰给一（互斥且必给一）",
            json_output=json_output)
        return
    if family and not snp:
        _emit_usage_error(
            "--family 形态需配 --snp（Touchstone 路径）",
            json_output=json_output)
        return
    synth: object = None
    if params is not None:
        try:
            synth = json.loads(params)
        except ValueError as exc:
            _emit_usage_error(f"--params 不是合法 JSON: {exc}",
                              json_output=json_output)
            return
        if not isinstance(synth, dict):
            _emit_usage_error(
                "--params 必须是 JSON 对象（族渲染器关键字参数）",
                json_output=json_output)
            return

    result = generate_schematic_diagram(
        out, netlist_path=net or None, family=family or None,
        snp_path=snp or None, params=synth, title=title or None)
    if json_output:
        _emit(result, "引脚级原理图生成失败", json_output=True)
        return
    if not result.get("ok"):
        console.print("[red]✗ 引脚级原理图生成失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)

    # markup 纪律（campaign 叶家法）：人读分支动态段（元件名/网名/warnings
    # 可含 "[...]"）一律 rich.markup.escape，防被当样式标签吞掉
    from rich.markup import escape

    console.print(
        f"[bold]引脚级原理图[/bold]  来源 {result['source']}  "
        f"元件 {result['n_components']}（Port {result['n_ports']}）  "
        f"信号网 {result['n_nets_signal']}  连线 {result['n_wires']} 条  "
        f"地桩 {result['n_ground_stubs']} 条"
        f"（引脚到引脚连线，网名=网表原值）")
    for comp in result.get("components") or []:
        console.print(escape(
            f"  {comp['kind']}:{comp['name']}  列 {comp['column']}  "
            f"行 {comp['row']}  节点 {'|'.join(comp['nodes'])}"))
    for w in result.get("warnings") or []:
        console.print(f"  [yellow]! {escape(w)}[/yellow]")
    console.print(f"[green]✓ 已写出[/green] {escape(result['out_path'])}"
                  "（draw.io/VS Code Draw.io 插件可打开编辑）")


@diagram_app.command("to-svg")
def diagram_to_svg_cmd(
    source: str = typer.Option(
        ..., "--source",
        help="输入 .drawio 路径（未压缩 mxfile；只读不改——draw.io 压缩页"
             "显式报错，请先在 draw.io 中取消压缩另存）"),
    out: str = typer.Option(
        ..., "--out",
        help="输出 .svg 路径（父目录须已存在；禁与 --source 同路径——覆盖"
             "原稿显式报错）"),
    page: int = typer.Option(
        0, "--page", help="页序号（0 起，缺省首页；多页 .drawio 逐页单出）"),
    json_output: bool = typer.Option(
        False, "--json", help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """渲染 .drawio 为静态 SVG：mxGraph XML → 纯 Python SVG（服务器/报告
    场景无 draw.io 桌面 GUI 的看图件）。

    示例：rfauto diagram to-svg --source link.drawio --out link.svg

    v1 初级形态（支持子集=core/drawio_svg 常量表单源）：vertex=矩形
    （fillColor/strokeColor/strokeWidth/rounded/dashed/opacity）+文字
    （value 原值原样，fontSize/fontColor/align/verticalAlign）、edge=直线/
    折线（mxGeometry points 中继点）、layer=<g> 分组；几何=drawio 坐标
    直映射零重算。不支持形态（image/曲线边/rotation 等）降级占位框+
    warnings 显式列出（不静默不炸）。本叶零数值逻辑（薄壳转发
    service/drawio_svg_service）。确定性：同输入两次运行文件逐字节相同。
    """
    from rfauto.service.drawio_svg_service import (
        render_drawio_svg,  # lazy: startup-cost（cli 注册根轻载，见 docs/explanation/lazy-import-conventions.md）
    )

    result = render_drawio_svg(source, out, page_index=page)
    if json_output:
        _emit(result, "SVG 渲染失败", json_output=True)
        return

    # markup 纪律（campaign 叶家法）：人读分支动态段（页名/路径/warnings
    # 可含 "[...]"）一律 rich.markup.escape，防被当样式标签吞掉
    from rich.markup import escape

    if not result.get("ok"):
        console.print("[red]✗ SVG 渲染失败[/red]")
        for err in result.get("errors", []):
            console.print(f"  [red]- {escape(err)}[/red]")
        raise typer.Exit(code=1)

    console.print(
        f"[bold].drawio→SVG[/bold]  页 {result['page_index']}"
        f"/{result['n_pages']}（{escape(result['diagram_name'])}）  "
        f"vertex {result['n_vertices']}  edge {result['n_edges']}  "
        f"层 {result['n_layers']}  降级占位 {result['n_degraded']}"
        "（几何=drawio 坐标直映射，文字=value 原值）")
    for w in result.get("warnings") or []:
        console.print(f"  [yellow]! {escape(w)}[/yellow]")
    console.print(f"[green]✓ 已写出[/green] {escape(result['out_path'])}"
                  "（浏览器/报告可直接内嵌查看）")
