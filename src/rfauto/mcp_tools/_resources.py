"""VB-6 SKILL 包经 MCP resources/prompts 暴露（aurora_r Wave2 席 R-13，
2026-11-10；提案源 runs/aurora_q/qx40_vbridge/PROPOSALS.md VB-6）。

设计要点：
- **零新工具**：``@mcp.tool`` 正则面零增量，工具数 200 不变（铁律+
  test_mcp_server 主钉自证）；本模块只有资源/模板/提示词三类组件。
- **七静态资源**：``skill://<name>/SKILL.md`` 逐包显式 ``@mcp.resource``
  装饰器注册（一个装饰器行=list_resources() 一个条目，R5-02 双口径
  ——装饰器正则 vs 注册面——同笔同移，check_mcp_resources_vs_source
  恒一致）；包名面=skills/ 目录实测（测试钉实测清单与注册清单逐位
  一致，新增包不注册即红=棘轮）。装饰器按包名字典序书写=注册序
  确定性排序。
- **references/ 子路径**：URI 模板 ``skill://{name}/references/{path*}``
  走 ``add_template`` 程序化注册——资源模板不进 list_resources() 也
  不进 ``@mcp.resource`` 正则面（计数双口径零扰动）；读取时守卫全量
  复核（穿越/越界/绝对路径/背斜杠/超大/缺失一律拒），目录内容读时
  实测（新文件无需重注册）。
- **守卫单源**：``resolve_skill_file``/``read_skill_text`` 纯函数，
  测试直钉；越界判定=解析（resolve）后仍在 SKILL 包目录内（符号链接
  /联接逃逸一并拦截）；单文件上限 SKILL_MAX_BYTES=2 MiB。
- **三条工作流提示词**：既有工具调用序列固化（解析器集群使用流/
  EM bench 任务流/配方草稿捕获流）；铁律 7——零物理数值字面量，
  文本经"数字+物理单位"正则扫描钉（tests/unit/test_mcp_skill_resources.py）。
- 本文件不进信封纪律面（资源/提示词返回原文或抛 SkillResourceError，
  由 fastmcp 转成 ResourceError/NotFoundError 协议错误）。
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

from fastmcp.resources.template import ResourceTemplate

from rfauto.mcp_tools._core import mcp as mcp

# ─── 守卫常量与错误 ──────────────────────────────────────────────────────────

#: 单资源文件大小上限（2 MiB；调度面参数，非物理数值）。
SKILL_MAX_BYTES = 2 * 1024 * 1024

#: skill:// URI scheme 前缀（本模块资源/模板统一口径）。
SKILL_URI_SCHEME = "skill://"

#: SKILL 包名合法形态（目录名直用，禁点段/分隔符/盘符——"..\"、".."、
#: 绝对路径在本形态下天然不可表达）。
_PACKAGE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


class SkillResourceError(ValueError):
    """skill:// 资源守卫拒绝（穿越/越界/绝对路径/超大/缺失统一入口）。"""


def _skills_root() -> Path:
    """skills/ 目录锚（本文件 src/rfauto/mcp_tools/ 三层深，parents[3]
    =仓根；与 terminology 资源同锚惯例——CWD 无关）。"""
    return Path(__file__).resolve().parents[3] / "skills"


def _validate_package_name(name: str, root: Path) -> str:
    """包名合法性+存在性（越界=不在 skills/ 实测包清单内）。"""
    if not isinstance(name, str) or not name or name.strip() != name:
        raise SkillResourceError(f"非法 SKILL 包名: {name!r}")
    if not _PACKAGE_NAME_RE.match(name):
        raise SkillResourceError(
            f"SKILL 包名含非法字符（分隔符/点段/盘符面拒绝）: {name!r}")
    pkg_dir = root / name
    if not (pkg_dir.is_dir() and (pkg_dir / "SKILL.md").is_file()):
        raise SkillResourceError(
            f"未知 SKILL 包（不在 skills/ 实测清单内）: {name!r}")
    return name


def _validate_rel_path(rel: str) -> PurePosixPath:
    """相对路径合法性（posix 段校验；穿越/绝对/背斜杠/空段一律拒）。"""
    if not isinstance(rel, str) or not rel or rel.strip() != rel:
        raise SkillResourceError(f"非法资源相对路径: {rel!r}")
    if "\\" in rel:
        raise SkillResourceError(f"背斜杠分隔符禁入（统一 posix 面）: {rel!r}")
    if rel.startswith("/") or re.match(r"^[A-Za-z]:", rel):
        raise SkillResourceError(f"绝对路径/盘符禁入: {rel!r}")
    parts = rel.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise SkillResourceError(
            f"路径含空段/点段/穿越段（'..' 一律拒）: {rel!r}")
    if "\x00" in rel:
        raise SkillResourceError(f"路径含 NUL: {rel!r}")
    return PurePosixPath(*parts)


def resolve_skill_file(name: str, rel: str, *, root: Path | None = None) -> Path:
    """解析 skill:// 包内相对路径→实际文件（守卫单源，测试直钉）。

    越界判定=resolve() 后仍在 SKILL 包目录内（符号链接/目录联接逃逸
    一并拦截）；存在性=is_file() 实测。违规一律 SkillResourceError。
    """
    r = Path(root) if root is not None else _skills_root()
    r = r.resolve()
    pkg = _validate_package_name(name, r)
    posix_rel = _validate_rel_path(rel)
    pkg_dir = r / pkg
    target = pkg_dir.joinpath(*posix_rel.parts).resolve()
    pkg_resolved = pkg_dir.resolve()
    if target != pkg_resolved and not target.is_relative_to(pkg_resolved):
        raise SkillResourceError(
            f"解析后路径越出 SKILL 包目录（越界拒）: {name!r} / {rel!r}")
    if not target.is_file():
        raise SkillResourceError(f"资源文件不存在: {name!r} / {rel!r}")
    return target


def read_skill_text(path: Path) -> str:
    """读文本（UTF-8），单文件超 SKILL_MAX_BYTES 拒。"""
    size = path.stat().st_size
    if size > SKILL_MAX_BYTES:
        raise SkillResourceError(
            f"资源文件超大拒读（>{SKILL_MAX_BYTES} 字节上限）: "
            f"{path.name}（{size} 字节）")
    return path.read_text(encoding="utf-8")


def list_skill_packages(*, root: Path | None = None) -> list[str]:
    """skills/ 实测 SKILL 包清单（字典序确定性排序）。"""
    r = Path(root) if root is not None else _skills_root()
    return sorted(
        p.name for p in r.iterdir()
        if p.is_dir() and (p / "SKILL.md").is_file())


def read_skill_md(name: str, *, root: Path | None = None) -> str:
    """读 SKILL 包主文档（守卫单源薄包装）。"""
    return read_skill_text(resolve_skill_file(name, "SKILL.md", root=root))


# ─── 七静态资源：skill://<name>/SKILL.md（包名字典序=注册序确定性） ───────────
# 一个 @mcp.resource 装饰器行=list_resources() 一个条目（R5-02 双口径同笔
# 同移）；描述串静态（注册零 I/O——skills/ 缺失不炸注册面，读时守卫拒）。


@mcp.resource(f"{SKILL_URI_SCHEME}rfauto-branchline-coupler/SKILL.md",
              description="SKILL 包 rfauto-branchline-coupler 主文档"
                          "（分支线耦合器族；references/ 子路径走 skill_reference 模板）",
              mime_type="text/markdown")
def skill_md_rfauto_branchline_coupler_resource() -> str:
    return read_skill_md("rfauto-branchline-coupler")


@mcp.resource(f"{SKILL_URI_SCHEME}rfauto-cpw/SKILL.md",
              description="SKILL 包 rfauto-cpw 主文档"
                          "（共面波导族；references/ 子路径走 skill_reference 模板）",
              mime_type="text/markdown")
def skill_md_rfauto_cpw_resource() -> str:
    return read_skill_md("rfauto-cpw")


@mcp.resource(f"{SKILL_URI_SCHEME}rfauto-mline-synthesis/SKILL.md",
              description="SKILL 包 rfauto-mline-synthesis 主文档"
                          "（微带综合族；references/ 子路径走 skill_reference 模板）",
              mime_type="text/markdown")
def skill_md_rfauto_mline_synthesis_resource() -> str:
    return read_skill_md("rfauto-mline-synthesis")


@mcp.resource(f"{SKILL_URI_SCHEME}rfauto-patch-antenna/SKILL.md",
              description="SKILL 包 rfauto-patch-antenna 主文档"
                          "（贴片天线族；references/ 子路径走 skill_reference 模板）",
              mime_type="text/markdown")
def skill_md_rfauto_patch_antenna_resource() -> str:
    return read_skill_md("rfauto-patch-antenna")


@mcp.resource(f"{SKILL_URI_SCHEME}rfauto-pifa/SKILL.md",
              description="SKILL 包 rfauto-pifa 主文档"
                          "（PIFA 族；references/ 子路径走 skill_reference 模板）",
              mime_type="text/markdown")
def skill_md_rfauto_pifa_resource() -> str:
    return read_skill_md("rfauto-pifa")


@mcp.resource(f"{SKILL_URI_SCHEME}rfauto-wilkinson-power-divider/SKILL.md",
              description="SKILL 包 rfauto-wilkinson-power-divider 主文档"
                          "（威尔金森功分器族；references/ 子路径走 skill_reference 模板）",
              mime_type="text/markdown")
def skill_md_rfauto_wilkinson_power_divider_resource() -> str:
    return read_skill_md("rfauto-wilkinson-power-divider")


@mcp.resource(f"{SKILL_URI_SCHEME}veriloga-authoring/SKILL.md",
              description="SKILL 包 veriloga-authoring 主文档"
                          "（Verilog-A 编写法；references/ 子路径走 skill_reference 模板）",
              mime_type="text/markdown")
def skill_md_veriloga_authoring_resource() -> str:
    return read_skill_md("veriloga-authoring")


# ─── references/ 子路径模板（add_template 程序化注册：不进 list_resources ────
# 也不进 @mcp.resource 正则面——计数双口径零扰动；读时守卫全量复核）。


def _skill_reference_read(name: str, path: str) -> str:
    """模板读函数：skill://{name}/references/{path*} → 守卫读取。"""
    return read_skill_text(resolve_skill_file(name, "references/" + path))


_skill_reference_template = mcp.add_template(
    ResourceTemplate.from_function(
        fn=_skill_reference_read,
        uri_template=f"{SKILL_URI_SCHEME}{{name}}/references/{{path*}}",
        name="skill_reference",
        description="SKILL 包 references/ 子路径只读读取"
                    "（skill://<包名>/references/<相对路径>；穿越/越界/超大一律拒）",
        mime_type="text/markdown",
    )
)

# ─── 三条工作流提示词（既有工具调用序列固化；零物理数值字面量—— ─────────────
# 文本不含"数字+物理单位"字面量，扫描钉在 test_mcp_skill_resources.py）。

_PROMPT_PARSER_CLUSTER = """\
解析器集群使用流（只读面，零副作用；全部走既有 MCP 工具，零物理数值）：
- 先 `format_overview` 看格式速览，确定文件族与可解析域。
- 网表与约束类按域转发：SPICE 用 `spice_netlist_parse`，Verilog 用
  `verilog_netlist_parse`，Liberty 用 `liberty_parse`，SDC 用 `sdc_parse`，
  IBIS 用 `ibis_parse`。
- 波形与测量类：CITI 用 `citi_info`，Touchstone 用 `touchstone_info`，
  VCD 用 `vcd_parse`，SDF 用 `sdf_parse`。
- 版图与制造类：SPEF 用 `spef_parse`，LEF/DEF 用 `lef_def_parse`，
  GDSII 用 `gdsii_parse`，封装测试用 `odbpp_report`/`bsdl_report`。
- 二线查询按需跟进：`spef_net_detail`、`sdf_cell_detail`、
  `gdsii_hierarchy`、`gdsii_layers`、`vcd_report`、`stil_pattern_detail`。
- 一致性校验：DRC 规则用 `drc_rules_parse`，LVS 对比用
  `lvs_compare_files`，Gerber/钻孔配对用 `gerber_excellon_pair_check`，
  制造检查用 `ipc356_fab_pair_check`。
- 大输出先走裁面旋钮（top 类参数）再全量；结论以信封 ok/error 为准，
  失败如实上报不臆测；不产出任何物理数字，数值只由确定性内核给出。"""

_PROMPT_EM_BENCH_FLOW = """\
EM bench 任务流（只编排既有工具，不替数值内核做任何决定）：
- 开工体检：`doctor` 看环境，`em_doctor_check` 看引擎健康。
- 选型与校验：`list_models` 选模型，`validate_recipe` 校验配方；
  引擎计划面用 `em_sweep_plan`（执行面不在此流）。
- 提交与轮询：正式任务 `create_run_async` 后台提交，`poll_job`/
  `wait_job` 轮询，长跑不空转阻塞；单发调试用 `create_run`。
- 收尾判读：`get_metrics` 取指标，`get_run_artifacts` 盘产物，
  跨 run 对比用 `compare_runs`。
- 引擎一致性面：`em_metrics_from_run` 读指标、`em_diff_runs` 做差异、
  `runs_verify` 做校验；判读门 FAIL/PARTIAL 如实采纳不凑绿。
- 报告面：`design_report` 回放成文，`agentbench_regression`/
  `goldset_regression` 做基准回归；`report_narrative` 只做叙述层。
- 物理数字一律来自求解器/综合器/评判器产出；模型只编排与解释。"""

_PROMPT_RECIPE_DRAFT_FLOW = """\
配方草稿捕获流（沙箱纪律：草稿只进沙箱，不改工作区配方文件）：
- 起草：`draft_recipe_from_spec` 从 spec 生成配方草稿。
- 校验：`validate_recipe`；红了改草稿再验，直到 ok 才进下一步。
- 试跑：`create_run` 小规模验证；`rf_critique_point` 做确定性批评
  （critique 是 service 层确定性函数），`rf_propose_params` 只出参数建议，
  `rf_spec_cost` 只读规格代价面。
- 迭代：上 `start_tune`/`run_sweep` 前先确认目标与边界写在配方里；
  采样用 `rf_run_sampler`，自验证用 `autotune_self_verify`。
- 纪律：任何自主修改只能落沙箱草稿路径，promote 走既有三层门；
  禁止把草稿直接写回工作区 recipes/；全程零物理数值字面量。"""


@mcp.prompt
def skill_parser_cluster_flow() -> str:
    """解析器集群使用流：格式速览→按域转发→二线查询→一致性校验。"""
    return _PROMPT_PARSER_CLUSTER


@mcp.prompt
def em_bench_task_flow() -> str:
    """EM bench 任务流：体检→校验→提交轮询→判读→报告的既定工具序列。"""
    return _PROMPT_EM_BENCH_FLOW


@mcp.prompt
def recipe_draft_capture_flow() -> str:
    """配方草稿捕获流：起草→校验→试跑→迭代的沙箱纪律工具序列。"""
    return _PROMPT_RECIPE_DRAFT_FLOW

# 本模块故意不设 __all__（check_public_api 口径：无 __all__ 记私有，
# 不进 public_api 金快照——与 mcp_tools/resources.py 同惯例；facade
# re-export 不依赖源模块 __all__）。
