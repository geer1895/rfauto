"""T-O1 链路框图 .drawio 生成器钉（aurora_o，2026-10-31）。

六验收钉（任务书口径）：
1. XML 结构合法——xml.etree 解析 + mxfile>diagram>mxGraphModel>root 结构
   断言（mxGraph 开放格式，出处见 core/link_diagram.py docstring）；
2. drawio 语义——每 vertex cell 必带 mxGeometry(x/y/w/h)、每 edge cell
   必带 source/target 且引用存在 id（draw.io viewer 语义核对离线形态）；
3. 数字单源——图内数字 == 独立构造的内核 LinkBudget 计算值经
   core.link_diagram.format_db 格式化后逐位（铁律 7，禁手抄）；
4. 确定性——同输入两跑 XML/文件逐字节相同（id 按索引、零时间戳）；
5. 负例——空链/非有限 gain（nan/inf）/缺键/负 NF 显式报错（内核
   ValueError + service ok=False 错误信封，不静默不凑绿）；
6. CLI——``rfauto diagram link`` 双路径（--json 信封同构 + rich 路径），
   usage 类错误 exit 2 / service 失败 exit 1（_emit_usage_error 契约）。
"""

from __future__ import annotations

import json
import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from typer.testing import CliRunner

from rfauto.cli.main import app as root_app
from rfauto.core.budget import LinkBudget
from rfauto.core.link_diagram import (
    build_link_diagram_xml,
    compute_link_chain,
    format_db,
)
from rfauto.service.diagram_service import generate_link_diagram

CHAIN = [
    {"name": "LNA", "gain_db": 20.0, "nf_db": 0.8},
    {"name": "滤波器", "gain_db": -2.0, "nf_db": 2.0},
    {"name": "Mixer", "gain_db": -7.0, "nf_db": 7.0},
]

_src_dir = Path(__file__).resolve().parents[2] / "src"
if _src_dir.exists() and str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))


# ─── 内核单源（验收③前置：compute_link_chain == LinkBudget 直算） ────────────


def _kernel_direct(chain: list[dict]):
    """独立构造内核 LinkBudget（不经过 link_diagram 面）作对拍基准。"""
    budget = LinkBudget()
    for st in chain:
        budget.add_stage(st["name"], gain_db=st["gain_db"],
                         nf_db=st["nf_db"])
    return budget.compute()


def test_compute_link_chain_matches_kernel_linkbudget():
    res = _kernel_direct(CHAIN)
    computed = compute_link_chain(CHAIN)
    assert computed["cascade_gain_db"] == res.cascade_gain_db
    assert computed["cascade_nf_db"] == res.cascade_nf_db
    for view, st in zip(computed["stages"], res.stages, strict=True):
        assert view["name"] == st.name
        assert view["gain_db"] == st.gain_db
        assert view["nf_db"] == st.nf_db
        assert view["cumulative_gain_db"] == st.cumulative_gain_db
        assert view["cumulative_nf_db"] == st.cumulative_nf_db


# ─── 验收①②：XML 结构与 drawio 语义 ────────────────────────────────────────


def _parse(xml_text: str) -> ET.Element:
    return ET.fromstring(xml_text)  # 结构非法即抛 ParseError=红


def _stage_ids(root: ET.Element) -> list[str]:
    return [c.get("id") for c in root.iter("mxCell")
            if (c.get("id") or "").startswith("stage")]


def test_xml_structure_valid():
    root = _parse(build_link_diagram_xml(CHAIN))
    assert root.tag == "mxfile"
    diagrams = root.findall("diagram")
    assert len(diagrams) == 1
    model = diagrams[0].find("mxGraphModel")
    assert model is not None
    mx_root = model.find("root")
    assert mx_root is not None
    cells = mx_root.findall("mxCell")
    ids = {c.get("id") for c in cells}
    # mxGraph 基 cell（root 恒含 id=0 与 id=1 parent=0）
    assert {"0", "1"} <= ids
    cell1 = next(c for c in cells if c.get("id") == "1")
    assert cell1.get("parent") == "0"
    # 级框数=级数、总计框、标题
    assert len(_stage_ids(mx_root)) == len(CHAIN)
    assert "cascade" in ids and "title" in ids


def test_vertices_have_geometry_edges_have_source_target():
    root = _parse(build_link_diagram_xml(CHAIN))
    all_ids = {c.get("id") for c in root.iter("mxCell")}
    vertices = [c for c in root.iter("mxCell") if c.get("vertex") == "1"]
    edges = [c for c in root.iter("mxCell") if c.get("edge") == "1"]
    assert len(vertices) == len(CHAIN) + 2  # 级框 + 总计框 + 标题
    assert len(edges) == len(CHAIN)  # 级间 n-1 + 末级→总计框
    for v in vertices:
        geom = v.find("mxGeometry")
        assert geom is not None, f"vertex {v.get('id')} 缺 mxGeometry"
        for attr in ("x", "y", "width", "height"):
            assert geom.get(attr) is not None
    for e in edges:
        assert e.get("source") in all_ids, f"edge {e.get('id')} source 悬空"
        assert e.get("target") in all_ids, f"edge {e.get('id')} target 悬空"
    # 连线序=信号流向：stage_i→stage_{i+1}，末级→cascade
    edge_pairs = [(e.get("source"), e.get("target")) for e in edges]
    stages = _stage_ids(root)
    for i in range(len(stages) - 1):
        assert (stages[i], stages[i + 1]) in edge_pairs
    assert (stages[-1], "cascade") in edge_pairs


def test_xml_escapes_special_chars_in_name():
    tricky = [{"name": 'A<B>&"X"漂', "gain_db": 1.0, "nf_db": 1.0}]
    root = _parse(build_link_diagram_xml(tricky))
    stage0 = next(c for c in root.iter("mxCell") if c.get("id") == "stage0")
    assert stage0.get("value").startswith('A<B>&"X"漂\n')


# ─── 验收③：数字单源（图内数字==内核计算值逐位） ────────────────────────────


def test_numbers_single_source_bit_exact():
    res = _kernel_direct(CHAIN)
    xml_text = build_link_diagram_xml(CHAIN)
    root = _parse(xml_text)
    cells = {c.get("id"): c for c in root.iter("mxCell")}
    for i, st in enumerate(res.stages):
        value = cells[f"stage{i}"].get("value")
        assert (f"G={format_db(st.gain_db)} dB  "
                f"NF={format_db(st.nf_db)} dB") in value
        assert (f"ΣG={format_db(st.cumulative_gain_db)} dB  "
                f"ΣNF={format_db(st.cumulative_nf_db)} dB") in value
    cascade_value = cells["cascade"].get("value")
    assert (f"ΣG={format_db(res.cascade_gain_db)} dB  "
            f"ΣNF={format_db(res.cascade_nf_db)} dB") in cascade_value
    # 教科书锚（budget.py docstring 同族钉值）：20/0.8 → -2/2 → -7/7
    # = G_tot 11 dB、NF_tot 1.04 dB（Friis 手算锚，防内核/渲染双错同源）
    assert format_db(res.cascade_gain_db) == "11.00"
    assert format_db(res.cascade_nf_db) == "1.04"


# ─── 验收④：确定性（同输入两跑逐字节） ─────────────────────────────────────


def test_determinism_two_runs_byte_identical(tmp_path):
    xml1 = build_link_diagram_xml(CHAIN)
    xml2 = build_link_diagram_xml(CHAIN)
    assert xml1 == xml2
    out1 = tmp_path / "a.drawio"
    out2 = tmp_path / "b.drawio"
    assert generate_link_diagram(CHAIN, out1)["ok"] is True
    assert generate_link_diagram(CHAIN, out2)["ok"] is True
    assert out1.read_bytes() == out2.read_bytes()
    assert out1.read_text(encoding="utf-8") == xml1


# ─── 验收⑤：负例显式报错 ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "bad_chain",
    [
        [],                                                     # 空链
        [{"name": "A", "gain_db": float("nan"), "nf_db": 1.0}],  # NaN gain
        [{"name": "A", "gain_db": float("inf"), "nf_db": 1.0}],  # +inf gain
        [{"name": "A", "gain_db": float("-inf"), "nf_db": 1.0}],  # -inf gain
        [{"name": "A", "gain_db": 10.0}],                        # 缺 nf_db
        [{"name": "", "gain_db": 10.0, "nf_db": 1.0}],           # 空名
        [{"gain_db": 10.0, "nf_db": 1.0}],                       # 缺 name
        [{"name": "A", "gain_db": 10.0, "nf_db": -1.0}],         # 负 NF 非物理
        [{"name": "A", "gain_db": 10.0, "nf_db": 1.0, "x": 1}],  # 多余键
        [{"name": "A", "gain_db": "20", "nf_db": 1.0}],          # 数字串
        "not-a-list",                                            # 非列表
    ],
)
def test_negatives_service_error_envelope(tmp_path, bad_chain):
    out = tmp_path / "neg.drawio"
    result = generate_link_diagram(bad_chain, out)
    assert result["ok"] is False
    assert result["errors"] and isinstance(result["errors"], list)
    assert not out.exists(), "失败路径不得落产物"


def test_negatives_kernel_raises_valueerror():
    with pytest.raises(ValueError):
        compute_link_chain([])
    with pytest.raises(ValueError):
        build_link_diagram_xml(
            [{"name": "A", "gain_db": float("nan"), "nf_db": 1.0}])


# ─── 验收⑥：service 信封数字与 CLI 双路径 ───────────────────────────────────


def test_service_success_envelope_numbers_match_kernel(tmp_path):
    out = tmp_path / "ok.drawio"
    result = generate_link_diagram(CHAIN, out, title="接收前端")
    assert result["ok"] is True
    res = _kernel_direct(CHAIN)
    assert result["n_stages"] == len(CHAIN)
    assert result["gain_total_db"] == res.cascade_gain_db
    assert result["nf_total_db"] == res.cascade_nf_db
    assert Path(result["out_path"]).exists()
    assert "接收前端" in out.read_text(encoding="utf-8")


def test_service_missing_parent_dir_explicit_error(tmp_path):
    out = tmp_path / "no_such_dir" / "x.drawio"
    result = generate_link_diagram(CHAIN, out)
    assert result["ok"] is False
    assert "目录不存在" in result["errors"][0]


def _invoke(args: list[str]):
    return CliRunner().invoke(root_app, args)


def _envelope(result) -> dict:
    out = result.output
    assert out.strip(), f"空输出（exit={result.exit_code}）"
    payload, _ = json.JSONDecoder().raw_decode(out[out.index("{"):])
    return payload


def test_cli_link_json_success(tmp_path):
    out = tmp_path / "cli.drawio"
    r = _invoke(["diagram", "link", "--chain", json.dumps(CHAIN),
                 "--out", str(out), "--json"])
    assert r.exit_code == 0, r.output[:400]
    payload = _envelope(r)
    assert payload["ok"] is True
    assert payload["n_stages"] == len(CHAIN)
    assert out.exists()
    _parse(out.read_text(encoding="utf-8"))


def test_cli_link_rich_success(tmp_path):
    out = tmp_path / "rich.drawio"
    r = _invoke(["diagram", "link", "--chain", json.dumps(CHAIN),
                 "--out", str(out)])
    assert r.exit_code == 0, r.output[:400]
    assert "已写出" in r.output
    assert "ΣNF=1.04" in r.output  # rich 面数字同为内核值
    assert out.exists()


def test_cli_link_service_failure_exit1_json_envelope(tmp_path):
    out = tmp_path / "neg.drawio"
    r = _invoke(["diagram", "link", "--chain", "[]",
                 "--out", str(out), "--json"])
    assert r.exit_code == 1
    payload = _envelope(r)
    assert payload["ok"] is False
    assert payload["errors"]


def test_cli_link_usage_errors_exit2(tmp_path):
    # 非法 JSON → usage exit 2（--json 下也必须 JSON 信封，#ge1㉙ 契约）
    r = _invoke(["diagram", "link", "--chain", "{bad json",
                 "--out", str(tmp_path / "x.drawio"), "--json"])
    assert r.exit_code == 2
    assert _envelope(r)["ok"] is False
    # --chain 与 --chain-file 双给 → 互斥 usage exit 2
    chain_file = tmp_path / "chain.json"
    chain_file.write_text(json.dumps(CHAIN), encoding="utf-8")
    r = _invoke(["diagram", "link", "--chain", "[]",
                 "--chain-file", str(chain_file),
                 "--out", str(tmp_path / "y.drawio"), "--json"])
    assert r.exit_code == 2
    # --chain-file 走文件路径成功（与 --chain 同 schema）
    out = tmp_path / "file.drawio"
    r = _invoke(["diagram", "link", "--chain-file", str(chain_file),
                 "--out", str(out), "--json"])
    assert r.exit_code == 0, r.output[:400]
    assert out.exists()


def test_format_db_fixed_precision():
    assert format_db(20.0) == "20.00"
    assert format_db(-7.1) == "-7.10"  # 固定 2 位（确定性渲染；不测 .5 中点
    # ——二进制浮点存储使边界舍入方向不可靠，#118 不赌格式化实现）
    assert format_db(1.043837349052967) == "1.04"


def test_nan_never_reaches_xml():
    with pytest.raises(ValueError):
        build_link_diagram_xml(
            [{"name": "A", "gain_db": math.nan, "nf_db": math.nan}])
