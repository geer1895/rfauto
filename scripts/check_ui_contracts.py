"""UI 前后端契约棘轮门（架构批 W2-S5 落地，R1 审计 #6/P8-10 常驻化；
架构批 W5-S1 R3 立项 #9 扩查询参数维度）。

三向对账（只读静态分析，零网络、零 import 前端代码）：
  A. 悬空调用：前端 JS（src/rfauto/ui/static/**/*.js，vendor/ 除外）的
     /api/ 字面调用（单双引号字面量+字符串拼接链+反引号模板串三形态）经
     归一化后，必须 ⊆ server.py Route 表——改名/笔误（路径段、参数串）
     在静态门暴露，不再等真机点击（W7 P2-1 limit 类漂移的防再犯面）。
  B. 无消费端点：server.py Route 表（/api/*）经归一化后，必须被前端调用
     或登记进 UNCONSUMED_ALLOWLIST（带理由）——服务端加端点无人消费
     （死路由）同样报红。
  C. 查询参数两向（R3 立项 #9，架构批 W5-S1——P8-10 "参数面更无守卫"
     的清偿；A 向原"查询串从首个 ? 截断"口径对路径向保持不变）：
     C1 悬空参数：前端调用 URL 查询串里的参数名，按归一化路由对账
        server handler 实际消费的参数名——前端传了 server 不收=红
        （改名/笔误静态暴露）。前端查询串四形态全识别：字面 ?k=v、
        拼接链 "?k="/"&k="、模板 ?k=${v}、局部查询构造变量插值
        （URLSearchParams 对象字面量键 / `?${q}` 模板插 / `.set("k",…)`
        追加 / 三元模板段 `&k=${v}`——单源 _frontend_var_params）。
     C2 未传参数：server handler 消费的参数名（AST 提取：
        request.query_params.get("k")/["k"]、局部别名 q=request.
        query_params 再 q.get("k")、f-string 动态键经 for 循环字面量
        迭代解析——fieldviz f"s{ax}"→sx/sy/sz 实例），前端从不传=
        登记 UNSENT_PARAM_ALLOWLIST（带理由；棘轮见下）。
     诚实降级：前端查询串含不可解析非字面量段（如 "?"+buildQuery()
     整段委托、值位表达式溢出到参数位）或 handler 动态键解析失败/
     handler 不可定位时，该路由跳出参数两向判定并打印注记（#105：
     观察面故障不阻塞 A/B 路径向主判）；实树当前零降级。

归一化口径（两侧同款）：
  - 路由参数 {run_id}/{name:path} → "*"；模板表达式 ${...} → "*"；
    拼接链的非字面量段（encodeURIComponent(x) 等）→ "*"；
  - A/B 向查询串从首个 "?" 起截断（路径段契约先行；参数面由 C 向
    以参数名集合对账承接——不再是无守卫盲区）；
  - 字面量尾随 "/"（拼接前缀形态）补 "*"（/ 边界对齐消音，R1 附录注记）。

棘轮纪律（只收不放）：
  - DANGLING_ALLOWLIST：悬空调用豁免表——**基线必须为空**（当前实测零
    悬空=干净基线，R1 附录原型实测 52 字面端点全部命中）；出现条目即
    违反零基线，须给理由+战役台账背书。
  - UNCONSUMED_ALLOWLIST：无消费端点豁免表——现有条目=服务端兼容层/
    非 UI 消费面（逐条理由见注释）；条目只可删不可加（删=前端接入清偿，
    加=新死路由须台账背书）。
  - DANGLING_PARAM_ALLOWLIST：悬空参数豁免表——**基线必须为空**（同
    DANGLING 纪律）。
  - UNSENT_PARAM_ALLOWLIST：未传参数豁免表（键=f"{归一化路由}#{参数名}"）
    ——现值 15 条=服务端可选能力面（field 切片族 sx/sy/sz+engine、清单
    端点 limit 缺省档、CLI/程序化消费参数如 anchors path）；只可删不可
    加（删=前端接入清偿，加=新未传参数须台账背书）；活体门另钉"登记集
    ==实算未传集"（双向零陈旧：前端开始传=条目陈旧须删，server 新收=
    未登记须红）。

退出码：0=全绿；1=有违例（逐条列出）；2=输入文件不可读（SKIP 诚实
降级，环境类非门红——对齐 merge_preflight 面 14-17 惯例）。
"""

from __future__ import annotations

import ast
import re
import sys
from itertools import product
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = REPO_ROOT / "src" / "rfauto" / "ui" / "static"
SERVER_PY = REPO_ROOT / "src" / "rfauto" / "ui" / "server.py"
UI_PKG_DIR = REPO_ROOT / "src" / "rfauto" / "ui"

# ── 归一化正则（两侧同款单源）─────────────────────────────────────────
_ROUTE_PARAM_RE = re.compile(r"\{[^}]*\}")  # Starlette 路由参数 {run_id}/{name:path}
_TPL_EXPR_RE = re.compile(r"\$\{[^}]*\}")  # JS 模板表达式 ${...}
_TPL_EXPR_G_RE = re.compile(r"\$\{([^}]*)\}")  # 同上带捕获组（C 向参数解析）
# 前端 /api/ 字面起点：引号（含反引号）+ 路径/查询字符（$/字母数字/_-.?&=/）
# （C 向扩 ?&=：查询串字面随首字面量整体入 composite，路径向 norm_call
# 照旧 split("?") 截断，行为对既有 61 形态逐字节不变）
_CALL_START_RE = re.compile(r"""(['"`])(/api/[A-Za-z0-9_\-./$?&=]*)""")
# 拼接链续段：+ 后跟字符串字面量
_CONCAT_LIT_RE = re.compile(r"""(['"])((?:[^'"\\]|\\.)*)\1""")
_CONCAT_OP_RE = re.compile(r"\s*\+\s*")

_PARAM_MARK = "\x00"  # 拼接链非字面量段占位（后归一为 "*"）
_PARAM_MARK_RE = re.compile(re.escape(_PARAM_MARK))
# 参数名合法形态（C 向两向同款校验；值位占位不进名集）
_PARAM_NAME_RE = re.compile(r"[A-Za-z_][\w-]*")
_IDENT_RE = re.compile(r"[A-Za-z_]\w*")

# ── 豁免表（棘轮：只收不放）───────────────────────────────────────────

# 悬空调用豁免——零违例基线（2026-10-18 R1 附录原型实测零悬空），禁止加条目。
DANGLING_ALLOWLIST: dict[str, str] = {}

# 无消费端点豁免——逐条理由；条目只可删（前端接入清偿）不可加（新死路由
# 须台账背书）。键=归一化路由形态。
UNCONSUMED_ALLOWLIST: dict[str, str] = {
    # 统一实时事件流服务端面（架构批 UI-R3）：tune/campaign 前端消费走
    # P-1 按桥 /api/runs/{id}/events/stream（sse.js sseStreamUrl 单源），
    # 三条通用流=server.py 注释自述的"兼容层保留"（server.py:112-119），
    # 前端消费适配留后续席（W5-S23 走查同结论）。
    "/api/tune/events/stream": "统一事件流兼容层——前端 tune 经 P-1 runs 流消费",
    "/api/campaign_queue/events/stream": (
        "统一事件流兼容层——前端 campaign 经 P-1 runs 流消费"),
    "/api/events/stream": "统一事件流全集端点——前端只接 runs 域过滤流",
    # EDB 快车道状态页：消费面在 edb_app 侧 CLI/脚本链（非人工工作台 JS），
    # server.py:171-172 注释自述"照 campaign_app 先例"的独立装配面。
    "/api/edb_status": "EDB 快车道状态面——edb_app 侧消费，非工作台 JS 面",
}

# 悬空参数豁免——零违例基线（C1 向，架构批 W5-S1 建门时实测零悬空），
# 禁止加条目。键=f"{归一化路由}#{参数名}"。
DANGLING_PARAM_ALLOWLIST: dict[str, str] = {}

# 未传参数豁免（C2 向）——server handler 消费、前端工作台 JS 从不传的
# 可选能力面；条目只可删（前端接入清偿）不可加（新未传参数须台账背书）。
# 键=f"{归一化路由}#{参数名}"，逐条理由指向 server 端 docstring/消费语义。
UNSENT_PARAM_ALLOWLIST: dict[str, str] = {
    # fieldviz 场视图：切片/引擎为 deep-link/程序化参数（routes/fieldviz.py
    # api_field_view docstring：sx/sy/sz=切片索引缺省中面、engine 缺省 auto）
    "/api/field/*#engine": "场视图引擎覆盖参——deep-link/程序化面，前端未暴露",
    "/api/field/*#sx": "场视图 x 切片索引——deep-link/程序化面，前端未暴露",
    "/api/field/*#sy": "场视图 y 切片索引——deep-link/程序化面，前端未暴露",
    "/api/field/*#sz": "场视图 z 切片索引——deep-link/程序化面，前端未暴露",
    # 清单类端点 limit：前端吃缺省档（50/200），大窗拉取是程序化消费面
    "/api/farfield#limit": "远场清单窗——前端吃缺省档，程序化消费面",
    "/api/field#limit": "场清单窗——前端吃缺省档，程序化消费面",
    "/api/inbox#limit": "审批收件箱窗——前端吃缺省档，程序化消费面",
    "/api/loop/boards#limit": "执行看板清单窗——前端吃缺省档，程序化消费面",
    "/api/pareto_runs#limit": "Pareto 清单窗——前端吃缺省档，程序化消费面",
    "/api/uq/samples#limit": "UQ 样本清单窗——前端吃缺省档，程序化消费面",
    # 单实体详情参：routes/data.py api_anchors/api_anchor_detail 的 path
    # 重定向参（锚注册表多根支持，前端固定缺省根）
    "/api/anchors#path": "锚清单注册表根重定向参——前端固定缺省根",
    "/api/anchors/*#path": "单锚详情注册表根重定向参——前端固定缺省根",
    # routes/recipes.py api_model3d：GET 分支 path 参（预览深链面），
    # 前端只走 POST 分支（JSON 体）
    "/api/model3d#path": "model3d GET 预览参——前端只走 POST 体分支",
    # routes/tune.py api_tune_trials：run_id 过滤参（跨 run 对比/程序化面）
    "/api/tune/trials#run_id": "trials run 过滤参——前端拉全集，程序化消费面",
    # routes/agent.py api_solvers_viz：solver 过滤参（前端拉全集自过滤）
    "/api/solvers/viz#solver": "可视化清单 solver 过滤参——前端拉全集自过滤",
}


def norm_route(path: str) -> str:
    """路由形态归一：{param} → "*"。"""
    return _ROUTE_PARAM_RE.sub("*", path)


def norm_call(raw: str) -> str:
    """调用形态归一：查询串截断 + 占位符 → "*"。"""
    raw = raw.split("?", 1)[0]
    raw = _TPL_EXPR_RE.sub("*", raw)
    raw = raw.replace(_PARAM_MARK, "*")
    if raw.endswith("/"):
        raw += "*"  # 尾斜杠=拼接前缀（/ 边界对齐，R1 附录注记消音）
    return raw


def _consume_concat_chain(text: str, pos: int, parts: list[str],
                          idents: list[str] | None = None) -> int:
    """从 pos 起消费 `+ <段>` 拼接链：字符串字面量按内容拼接，非字面量
    表达式段（encodeURIComponent(x)/标识符等）记占位符并跳到链上下一
    顶层 "+"（括号深度归零处；顶层 ","/";"/反引号=语句边界同样截断）。
    idents 非 None 时按序收集非字面量段源文本（C 向参数名解析用——
    标识符段可经 _frontend_var_params 变量表解析出参数名）。返回停止位置。
    """
    while True:
        op = _CONCAT_OP_RE.match(text, pos)
        if not op:
            return pos
        pos = op.end()
        if pos >= len(text):
            return pos
        ch = text[pos]
        if ch in "'\"":
            lit = _CONCAT_LIT_RE.match(text, pos)
            if not lit:
                return pos
            parts.append(lit.group(2))
            pos = lit.end()
        elif ch == "`":
            return pos  # 模板段混拼（现库无此形态）——保守截断
        else:
            parts.append(_PARAM_MARK)
            depth = 0
            i = pos
            while i < len(text):
                c = text[i]
                if c in "([{":
                    depth += 1
                elif c in ")]}":
                    if depth == 0:
                        break
                    depth -= 1
                elif depth == 0 and (c in ",;" or c == "`"):
                    break  # 语句/实参边界（非字面量段已整体占位）
                elif c == "+" and depth == 0 and text[i : i + 2] != "++":
                    break
                i += 1
            if idents is not None:
                idents.append(text[pos:i])
            pos = i


def _iter_call_composites(text: str):
    """产出 (composite, idents)：composite=调用串原文（查询串保留、非字面量
    段=\x00 占位），idents=拼接链非字面量段源文本（与 composite 内 \x00
    按出现序对齐）。两通道：反引号模板串（只认 /api/ 起始形态，防帮助
    文案噪声——idents 恒空，模板表达式由 C 向 _TPL_EXPR_RE 通道解析）与
    引号字面量+拼接链。"""
    for m in re.finditer(r"`([^`]*)`", text):
        seg = m.group(1)
        if not seg.startswith("/api/"):
            continue
        yield seg, []
    for m in _CALL_START_RE.finditer(text):
        if m.group(1) == "`":
            continue  # 模板形态已由上通道整段处理
        parts = [m.group(2)]
        idents: list[str] = []
        start = m.end() + (1 if m.end() < len(text) and text[m.end()] == m.group(1) else 0)
        _consume_concat_chain(text, start, parts, idents)
        yield "".join(parts), idents


def extract_calls(text: str) -> set[str]:
    """提取单个 JS 文件的 /api/ 调用形态集（模板串与引号串/拼接链两通道）。"""
    return {
        norm for norm in (norm_call(c) for c, _ in _iter_call_composites(text))
        if norm.startswith("/api/")
    }


# ── C 向：前端查询参数提取 ────────────────────────────────────────────

# 局部查询构造变量三通道单源：
#   ① URLSearchParams 对象字面量键（const q = new URLSearchParams({k: …})）
#   ② 后续条件追加（q.set("k", …)）
#   ③ 三元模板串段（const q = cond ? `&k=${…}` : ""——段以 ? 或 & 起始）
_VAR_QS_INIT_RE = re.compile(
    r"\b(?:const|let|var)\s+(\w+)\s*=\s*new\s+URLSearchParams\s*\(\s*\{")
_VAR_ASSIGN_RE = re.compile(r"\b(?:const|let|var)\s+(\w+)\s*=([^;\n]*);")
_VAR_SET_RE = re.compile(r"\b(\w+)\.set\(\s*['\"](\w+)['\"]")
_QS_KEY_RE = re.compile(r"(\w+)\s*:")
_QS_FRAG_NAME_RE = re.compile(r"[?&](\w+)=")


def _frontend_var_params(text: str) -> dict[str, set[str]]:
    """单文件局部查询构造变量 → 参数名集（三通道并集；仅当变量被插进
    /api/ 查询位才被消费，非查询用途的 .set("k",…) 同名碰撞=多记参数名，
    只在变量同时进查询位时生效——现库零碰撞）。"""
    varmap: dict[str, set[str]] = {}
    for m in _VAR_QS_INIT_RE.finditer(text):
        end = text.find("})", m.end())
        seg = text[m.end(): end if end >= 0 else m.end()]
        varmap.setdefault(m.group(1), set()).update(_QS_KEY_RE.findall(seg))
    for m in _VAR_SET_RE.finditer(text):
        varmap.setdefault(m.group(1), set()).add(m.group(2))
    for m in _VAR_ASSIGN_RE.finditer(text):
        names = {
            k
            for t in re.finditer(r"`([?&][^`]*)`", m.group(2))
            for k in _QS_FRAG_NAME_RE.findall(t.group(1))
        }
        if names:
            varmap.setdefault(m.group(1), set()).update(names)
    return varmap


def _query_params_of(raw: str, varmap: dict[str, set[str]],
                     idents: list[str]) -> set[str] | None:
    """调用 composite 的查询串 → 参数名集；含不可解析段返回 None（诚实
    降级）。`${ident}`/标识符 \x00 段经 varmap 解析（解析成功=并集其参数
    名；失败=占位残留）。占位在值位（k=${v}）无害；溢出到参数位/整段
    委托（?+fn()）=不可解析。"""
    names: set[str] = set()
    # 两通道占位在**整条 composite**上解析（idents 与全文 \x00 按序对齐；
    # 查询段单独截取会吃掉路径位占位的配额造成错位）——变量解析成功=并集
    # 其参数名并抹除段文本；失败=占位残留。路径位的变量段不产名（现库零
    # 此形态；纯标识符进 varmap 才收，encodeURIComponent 类表达式不受扰）。
    def _tpl_sub(mm: re.Match[str]) -> str:
        inner = mm.group(1).strip()
        if _IDENT_RE.fullmatch(inner) and inner in varmap:
            names.update(varmap[inner])
            return ""
        return mm.group(0)

    q = _TPL_EXPR_G_RE.sub(_tpl_sub, raw)
    idents_iter = iter(idents)

    def _ident_sub(_mm: re.Match[str]) -> str:
        ident = next(idents_iter, "").strip()
        if _IDENT_RE.fullmatch(ident) and ident in varmap:
            names.update(varmap[ident])
            return ""
        return _PARAM_MARK

    q = _PARAM_MARK_RE.sub(_ident_sub, q)
    _, sep, q = q.partition("?")
    del sep
    unresolved = False
    for seg in q.split("&"):
        if not seg:
            continue
        k = seg.partition("=")[0].strip()
        # 只有名位含占位/表达式才算不可解析（值位占位如 path=\x00 无害——
        # 参数名已在 = 左侧提取；整段委托（?+fn() 未解析）名位=\x00 → 降级）
        if "${" in k or _PARAM_MARK in k or not _PARAM_NAME_RE.fullmatch(k):
            unresolved = True
            continue
        names.add(k)
    return None if unresolved else names


def frontend_query_params(
        text: str, varmap: dict[str, set[str]] | None = None
) -> dict[str, set[str] | None]:
    """单 JS 文件 → {归一化路由: 参数名集|None}（None=该路由存在不可解析
    查询调用，参数两向判定对它诚实降级）。"""
    if varmap is None:
        varmap = _frontend_var_params(text)
    out: dict[str, set[str] | None] = {}
    for composite, idents in _iter_call_composites(text):
        route = norm_call(composite)
        if not route.startswith("/api/"):
            continue
        ps = _query_params_of(composite, varmap, idents)
        prev = out.get(route, set())
        out[route] = None if prev is None or ps is None else prev | ps
    return out


def collect_frontend_query_params() -> tuple[dict[str, set[str] | None],
                                             list[str]]:
    """全前端（vendor/ 除外）查询参数面：{路由: 参数集|None} + 降级路由
    注记清单（跨文件合并：任一文件该路由不可解析 → 路由级 None）。"""
    merged: dict[str, set[str] | None] = {}
    for p in sorted(STATIC_DIR.rglob("*.js")):
        if "vendor" in p.parts:
            continue
        for route, ps in frontend_query_params(
                p.read_text(encoding="utf-8")).items():
            prev = merged.get(route, set())
            merged[route] = prev if prev is None or ps is None else prev | ps
    degraded = sorted(r for r, ps in merged.items() if ps is None)
    return merged, degraded


# ── C 向：server 端查询参数消费提取（AST）────────────────────────────

_UI_IMPORT_RE = re.compile(r"from rfauto\.ui\.([\w.]+) import (.+)")
_ROUTE_DECL_RE = re.compile(r'Route\("([^"]+)"\s*,\s*([A-Za-z_][\w.]*)')


def _server_import_map(server_text: str) -> dict[str, Path]:
    """server.py 的 rfauto.ui 导入名 → 模块文件路径（handler 定位单源）。
    双候选：`from rfauto.ui.routes import agent as agent_routes` 的别名
    落 routes/agent.py（<mod>/<orig>.py，包内子模块），`from
    rfauto.ui.campaign_app import api_campaign_dashboard` 落 campaign_app.py
    （<mod>.py 直模块）——按文件存在性裁决。"""
    out: dict[str, Path] = {}
    for m in _UI_IMPORT_RE.finditer(server_text):
        parts = m.group(1).split(".")
        for part in m.group(2).split(","):
            part = part.strip()
            if not part or part.startswith("("):
                continue
            orig = alias = part
            if " as " in part:
                orig, alias = (s.strip() for s in part.split(" as ", 1))
            mod_py = UI_PKG_DIR.joinpath(*parts).with_suffix(".py")
            sub_py = UI_PKG_DIR.joinpath(*parts, f"{orig}.py")
            out[alias] = mod_py if mod_py.is_file() else sub_py
    return out


def _handler_query_params(
        module_path: Path, func_name: str,
        _tree_cache: dict[Path, ast.Module | None]) -> tuple[bool, set[str],
                                                             bool]:
    """handler 函数的查询参数消费面：(handler 可定位, 参数名集, 动态键
    不可解析)。识别形态：query_params.get("k")[.get 默认值]、query_params
    ["k"] 下标、局部别名 q=request.query_params 再 q.get/q[...]、f-string
    动态键经所在 for 循环字面量迭代解析（f"s{ax}" × ax∈("x","y","z") →
    sx/sy/sz——fieldviz 实例）。"""
    if module_path not in _tree_cache:
        try:
            _tree_cache[module_path] = ast.parse(
                module_path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            _tree_cache[module_path] = None
    tree = _tree_cache[module_path]
    if tree is None:
        return False, set(), False
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name == func_name), None)
    if fn is None:
        return False, set(), False

    # 局部别名：x = request.query_params（Attribute 链精确到 request 根）
    aliases: set[str] = set()
    for n in ast.walk(fn):
        if (isinstance(n, ast.Assign) and len(n.targets) == 1
                and isinstance(n.targets[0], ast.Name)
                and isinstance(n.value, ast.Attribute)
                and n.value.attr == "query_params"
                and isinstance(n.value.value, ast.Name)
                and n.value.value.id == "request"):
            aliases.add(n.targets[0].id)

    def _is_qp(node: ast.expr) -> bool:
        return (isinstance(node, ast.Name) and node.id in aliases) or (
            isinstance(node, ast.Attribute) and node.attr == "query_params"
            and isinstance(node.value, ast.Name)
            and node.value.id == "request")

    # for 循环字面量迭代变量（f-string 动态键解析域）
    loop_vars: dict[str, tuple[str, ...]] = {}
    for n in ast.walk(fn):
        if (isinstance(n, ast.For) and isinstance(n.target, ast.Name)
                and isinstance(n.iter, (ast.Tuple, ast.List))
                and all(isinstance(e, ast.Constant)
                        and isinstance(e.value, str) for e in n.iter.elts)):
            loop_vars[n.target.id] = tuple(
                e.value for e in n.iter.elts)  # type: ignore[union-attr]

    def _resolve_fstring(node: ast.JoinedStr) -> set[str] | None:
        """f"s{ax}" → {sx, sy, sz}（逐 FormattedValue 经 loop_vars 解析；
        任一分量不可解析 → None）。"""
        slots: list[list[str]] = []
        for v in node.values:
            if isinstance(v, ast.Constant):
                slots.append([str(v.value)])
            elif (isinstance(v, ast.FormattedValue)
                    and isinstance(v.value, ast.Name)
                    and v.value.id in loop_vars):
                slots.append(list(loop_vars[v.value.id]))
            else:
                return None
        return {"".join(parts) for parts in product(*slots)}

    names: set[str] = set()
    unresolved = False
    for n in ast.walk(fn):
        if isinstance(n, ast.Subscript) and _is_qp(n.value):
            if (isinstance(n.slice, ast.Constant)
                    and isinstance(n.slice.value, str)):
                names.add(n.slice.value)
            else:
                unresolved = True
        elif (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr in ("get", "pop") and n.args
                and _is_qp(n.func.value)):
            a0 = n.args[0]
            if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
                names.add(a0.value)
            elif isinstance(a0, ast.JoinedStr):
                got = _resolve_fstring(a0)
                if got is None:
                    unresolved = True
                else:
                    names.update(got)
            else:
                unresolved = True
    return True, names, unresolved


def collect_server_query_params(
) -> tuple[dict[str, set[str]], set[str]]:
    """server.py Route 表（/api/*）→ {归一化路由: 消费参数名集}, 不可解析
    路由集（handler 不可定位/动态键解析失败——参数两向判定对它诚实降级）。"""
    text = SERVER_PY.read_text(encoding="utf-8")
    imports = _server_import_map(text)
    params: dict[str, set[str]] = {}
    unresolved: set[str] = set()
    trees: dict[Path, ast.Module | None] = {}
    for m in _ROUTE_DECL_RE.finditer(text):
        rpath, ref = m.group(1), m.group(2)
        if not rpath.startswith("/api/"):
            continue
        key = norm_route(rpath)
        alias, func = ref.rsplit(".", 1) if "." in ref else (ref, ref)
        mod = imports.get(alias)
        if mod is None:
            unresolved.add(key)
            continue
        found, p, unres = _handler_query_params(mod, func, trees)
        if not found:
            unresolved.add(key)
            continue
        params.setdefault(key, set()).update(p)
        if unres:
            unresolved.add(key)
    return params, unresolved


def collect_frontend_calls() -> set[str]:
    calls: set[str] = set()
    for p in sorted(STATIC_DIR.rglob("*.js")):
        if "vendor" in p.parts:
            continue
        calls |= extract_calls(p.read_text(encoding="utf-8"))
    return calls


def collect_server_routes() -> set[str]:
    text = SERVER_PY.read_text(encoding="utf-8")
    routes = re.findall(r'Route\("([^"]+)"', text)
    return {norm_route(r) for r in routes if r.startswith("/api/")}


def main(argv: list[str] | None = None) -> int:
    del argv
    try:
        calls = collect_frontend_calls()
        routes = collect_server_routes()
        fe_params, fe_degraded = collect_frontend_query_params()
        sv_params, sv_unresolved = collect_server_query_params()
    except OSError as e:
        print(f"[SKIP] UI 契约门：输入不可读（{e}）——诚实降级，环境类非门红")
        return 2
    if not routes:
        print("[SKIP] UI 契约门：server.py 路由表解析为空——诚实降级")
        return 2

    dangling = sorted(c for c in calls if c not in routes)
    dangling = [c for c in dangling if c not in DANGLING_ALLOWLIST]
    unconsumed = sorted(
        r for r in routes if r not in calls and r not in UNCONSUMED_ALLOWLIST)

    # ── C 向：查询参数两向（路径向悬空/无消费路由不重复计——A/B 已红）──
    param_skips = set(sv_unresolved) | set(fe_degraded)
    dangling_params: list[str] = []
    for r, ps in sorted(fe_params.items()):
        if ps is None or r not in sv_params or r in UNCONSUMED_ALLOWLIST:
            continue  # 路由不在 server 表=A 向已红；无消费豁免=B 向管辖
        for p in sorted(ps - sv_params[r]):
            key = f"{r}#{p}"
            if key not in DANGLING_PARAM_ALLOWLIST:
                dangling_params.append(key)
    unsent_params: list[str] = []
    for r, sp in sorted(sv_params.items()):
        if r in UNCONSUMED_ALLOWLIST or r in param_skips:
            continue  # 无消费路由=非工作台契约面；降级路由=诚实跳出
        fp = fe_params.get(r)
        if fp is None:
            continue  # 前端零调用该路由=B 向管辖
        for p in sorted(sp - fp):
            key = f"{r}#{p}"
            if key not in UNSENT_PARAM_ALLOWLIST:
                unsent_params.append(key)

    n_fe = sum(len(ps) for ps in fe_params.values() if ps is not None)
    n_sv = sum(len(ps) for ps in sv_params.values())
    print(f"[UI 契约] 前端调用形态 {len(calls)} · 服务端路由 {len(routes)}"
          f" · 无消费豁免 {len(UNCONSUMED_ALLOWLIST)}"
          f" · 查询参数 前端 {n_fe} · 服务端 {n_sv}"
          f" · 未传豁免 {len(UNSENT_PARAM_ALLOWLIST)}")
    for c in dangling:
        print(f"  悬空调用（前端调用无对应路由）: {c}")
    for r in unconsumed:
        print(f"  无消费端点（路由无前端调用）: {r}")
    for k in dangling_params:
        print(f"  悬空参数（前端传、server 不收）: {k}")
    for k in unsent_params:
        print(f"  未传参数（server 收、前端不传且未登记）: {k}")
    if param_skips:
        print(f"  [注] 参数两向降级路由 {len(param_skips)}"
              f"（动态键/不可解析查询）: {sorted(param_skips)}")
    if dangling:
        print("  处置：修调用路径或（确有理由）登记 DANGLING_ALLOWLIST——"
              "该表基线为空，加条目须台账背书")
    if unconsumed:
        print("  处置：前端接入清偿后删 UNCONSUMED_ALLOWLIST 条目，或"
              "（服务端兼容层/非 UI 面）登记带理由条目——只可删不可加")
    if dangling_params:
        print("  处置：修参数名或（确有理由）登记 DANGLING_PARAM_ALLOWLIST"
              "——该表基线为空，加条目须台账背书")
    if unsent_params:
        print("  处置：前端接入清偿后删 UNSENT_PARAM_ALLOWLIST 条目，或"
              "（可选能力/deep-link/程序化面）登记带理由条目——只可删不可加")
    if dangling or unconsumed or dangling_params or unsent_params:
        print(f"[FAIL] UI 前后端契约门（悬空 {len(dangling)} · 无消费 "
              f"{len(unconsumed)} · 悬空参数 {len(dangling_params)} · "
              f"未登记未传 {len(unsent_params)}）")
        return 1
    print("[PASS] UI 前后端契约门（三向对账零违例：悬空 0 · 未登记无消费 0"
          " · 悬空参数 0 · 未登记未传 0）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
