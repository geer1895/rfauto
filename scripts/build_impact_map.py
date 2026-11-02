"""构建 src 模块 → tests/unit 测试文件 影响面映射（aurora_m W0-2）。

双源映射（并集，宁多勿漏）：
  (a) import 图：AST 解析 tests/unit 全部 .py（含 conftest/_helpers，逐文件 ast.parse，
      不 import 执行）与 src/rfauto 全部模块——收集文件内**所有层级**的 Import/ImportFrom
      （含函数体内延迟 import），解析为 src 模块文件；再对 src 内部依赖图展开传递闭包
      （测试 import service 模块、service 依赖 core 模块 → 改 core 该测试也算受影响）。
  (b) git grep 面（进程内等价实现）：对每个 src 模块派生检索 token（模块 stem 与驼峰变体、
      模块全点路径、__init__.py 的包点路径），在 tests/unit 全部文件文本中做子串扫描——抓
      import 图抓不到的字符串引用（monkeypatch 目标、importlib.import_module、
      getfixturevalue 等）。stem/驼峰 token 有文档频率上限（语料通用词如 "runs" 弃用，
      只保留精确点路径），宁多勿漏但不淹没信号。

conftest 语义：
  - conftest 顶层 import → 下发给目录子树全部测试（收集期依赖）；
  - conftest/测试文件内 @pytest.fixture 体内的 rfauto import → 按 fixture 参数名匹配下发
    （测试函数/本地 fixture 的参数名命中即继承该 fixture 体的依赖；含链式 fixture 的
    fixpoint 闭包）——避免把 tests/conftest.py 里 fixture 体内延迟 import 的
    fake_adapter/run_store 平摊给全部 1151 个测试。

用法：
    .venv/Scripts/python.exe scripts/build_impact_map.py            # 默认输出
    .venv/Scripts/python.exe scripts/build_impact_map.py --out X    # 指定输出路径
    .venv/Scripts/python.exe scripts/build_impact_map.py --force    # 忽略指纹缓存强制重建

增量缓存（W2-1）：构建成功后把全部 src/tests 输入文件的 [size, mtime_ns, sha256] 指纹
写入 runs/aurora_m/.impact_map_fingerprint.json（runs/ gitignored 合规）；下次运行
指纹全等（含 builder 脚本自身哈希）→ 秒回跳过重建，任何输入变化 → 全量重建并刷新指纹。
devtest --scope direct 复用同一指纹但只查 tests 面+src 键集（direct 映射在 src 内容
变化下不变——选择面由 tests 内容与 src 路径集决定，见 check_fresh docstring）。

幂等可重复运行（除 generated_at/git_head 外输出确定）。产出 YAML 顶层：
  generated_at / git_head / stats / _meta / modules（src 模块键 → 测试文件列表，按受影响
  测试数降序；100% src 模块都出现，零覆盖模块登记空列表）。
  modules=传递闭包面（宁多勿漏）；另附 modules_direct=直连面（import 直连+grep，不做 src
  闭包，W2-1 devtest 缺省口径——hub 模块闭包可达全量测试，直连面才是开发循环的实用粒度）。
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO / "src" / "rfauto"
TESTS_UNIT = REPO / "tests" / "unit"
TESTS_ROOT = REPO / "tests"
CONTESTS = ("tests/conftest.py", "tests/unit/conftest.py")
MIN_TOKEN_LEN = 4  # 短于 4 的裸 stem（如 "ui"）子串噪声过大，跳过（点路径 token 不受限）
FINGERPRINT_VERSION = 1
BUILDER_SELF = Path(__file__).resolve()
FINGERPRINT_NAME = ".impact_map_fingerprint.json"


def _list_py(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def collect_file_lists() -> tuple[list[Path], list[Path]]:
    """(src 文件, tests 面文件) 收集单源——构建主路径与指纹新鲜度检查共用。"""
    src_files = [p for p in _list_py(SRC_ROOT) if p.suffix == ".py"]
    surface_files = _list_py(TESTS_UNIT)
    for extra in ("tests/conftest.py", "tests/__init__.py"):
        if (REPO / extra).exists():
            surface_files.append(REPO / extra)
    return src_files, surface_files


# ── 增量指纹（W2-1）───────────────────────────────────────────────────────────


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _fp_entry(p: Path) -> list:
    """[size, mtime_ns, sha256]——检查路径用 stat 快路径，写路径全量哈希（~2300 文件 0.3s 实测）。"""
    st = p.stat()
    return [st.st_size, st.st_mtime_ns, _sha256_file(p)]


def default_fingerprint_path(map_path: Path) -> Path:
    return map_path.parent / FINGERPRINT_NAME


def build_fingerprint(map_path: Path) -> dict:
    src_files, surface_files = collect_file_lists()
    return {
        "version": FINGERPRINT_VERSION,
        "builder_sha256": _sha256_file(BUILDER_SELF),
        "map_name": map_path.name,
        "src": {_rel_key(p): _fp_entry(p) for p in src_files},
        "surface": {_rel_key(p): _fp_entry(p) for p in surface_files},
    }


def _entry_matches(entry: object, p: Path) -> bool:
    """stat 快路径（size+mtime_ns 全等→视为未变）；失配回退内容哈希（git 触 mtime 不误判）。"""
    if not (isinstance(entry, list) and len(entry) == 3):
        return False
    try:
        st = p.stat()
    except OSError:
        return False
    if st.st_size == entry[0] and st.st_mtime_ns == entry[1]:
        return True
    try:
        return _sha256_file(p) == entry[2]
    except OSError:
        return False


def check_fresh(stored: object, map_path: Path, scope: str = "full") -> str:
    """返回 ""=新鲜；否则返回过期原因（人话，直接可打印）。scope: "direct"|"closed"|"full"。

    口径依据：modules_direct 选择面由 tests 面内容（import/grep/fixture）与 src 路径集
    （token 派生+文件存在性解析）决定，与 src 文件**内容**无关——direct 只查 tests 面
    内容+src 键集；closed 的传递闭包沿 src import 图展开，src 内容（import 语句）参与，
    故 closed/full 另查 src 内容。builder 自身哈希入指纹：映射算法变更即全量再生。
    """
    if not isinstance(stored, dict) or stored.get("version") != FINGERPRINT_VERSION:
        return "指纹缺失或版本不识别"
    if not map_path.exists():
        return "映射文件缺失"
    try:
        if _sha256_file(BUILDER_SELF) != stored.get("builder_sha256"):
            return "builder 脚本已更新（映射算法可能变化）"
    except OSError:
        return "builder 脚本不可读"
    src_files, surface_files = collect_file_lists()
    stored_surface = stored.get("surface")
    stored_src = stored.get("src")
    if not isinstance(stored_surface, dict) or not isinstance(stored_src, dict):
        return "指纹结构不完整"
    cur_surface = {_rel_key(p): p for p in surface_files}
    if set(cur_surface) != set(stored_surface):
        return "tests 面文件集变化"
    for key in sorted(cur_surface):
        if not _entry_matches(stored_surface[key], cur_surface[key]):
            return f"tests 面文件变更：{key}"
    cur_src = {_rel_key(p): p for p in src_files}
    if set(cur_src) != set(stored_src):
        return "src 文件集变化（新增/删除）"
    if scope in ("closed", "full"):
        for key in sorted(cur_src):
            if not _entry_matches(stored_src[key], cur_src[key]):
                return f"src 文件变更：{key}（{scope} 口径依赖 src 内容）"
    return ""


def _rel_key(p: Path) -> str:
    return p.resolve().relative_to(REPO).as_posix()


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def _module_dotted(key: str) -> tuple[str, bool]:
    """文件键 → (模块点路径, 是否包 __init__)。src/ 前缀不属包路径（src 布局）。"""
    no_ext = key[: -len(".py")]
    is_pkg = no_ext.endswith("/__init__")
    dotted = no_ext[: -len("/__init__")] if is_pkg else no_ext
    if dotted.startswith("src/"):
        dotted = dotted[len("src/") :]
    return dotted.replace("/", "."), is_pkg


def _collect_candidates(tree: ast.Module | None, mod_dotted: str, is_pkg: bool) -> set[str]:
    """收集文件内所有层级 import 的候选点路径（rfauto/tests 开头由调用方过滤）。

    相对 import 按所在包解析：__init__.py 的包=自身模块名，其余取父包；level L 上溯 L-1。
    ImportFrom 额外生成 `module.name` 候选（抓 `from rfauto.service import dataset_service`
    这类"包内子模块"引用）。

    aurora_n 零覆盖治理席修复（2026-10-30）：绝对 ImportFrom 此前把 base 置成
    node.module 自身再拼 `base.node.module.alias`，候选全部翻倍成垃圾点路径
    （`rfauto.service.rfauto.service.sdk`），`_resolve_under` 解析不到真实文件键
    ——叠加 grep 面 3 字符短 stem（"sdk"）被弃用，sdk.py 被误判 zero-coverage。
    现统一：base=前缀（绝对="）相对=所在包），候选=prefix.module 与
    prefix.module.alias；多余候选由 _resolve_under 按文件存在性过滤，无副作用。
    """
    if tree is None:
        return set()
    pkg = mod_dotted if is_pkg else mod_dotted.rsplit(".", 1)[0] if "." in mod_dotted else ""
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out.add(a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                base = ""
            else:
                parts = pkg.split(".") if pkg else []
                drop = node.level - 1
                if drop > len(parts):
                    continue
                base = ".".join(parts[: len(parts) - drop]) if drop else pkg
                if not base:
                    continue
            prefix = f"{base}." if base else ""
            if node.module:
                out.add(f"{prefix}{node.module}")
            for a in node.names:
                if a.name == "*":
                    continue
                out.add(
                    f"{prefix}{node.module}.{a.name}"
                    if node.module
                    else f"{prefix}{a.name}"
                )
    return out


def _resolve_under(root: Path, root_pkg: str, dotted: str, key_set: set[str]) -> None:
    """点路径 → root 下实际存在的文件键（含沿途各祖先包 __init__，import 语义会执行它们）。"""
    if dotted != root_pkg and not dotted.startswith(root_pkg + "."):
        return
    parts = dotted.split(".")
    for i in range(1, len(parts) + 1):
        rel = "/".join(parts[1:i]) if i > 1 else ""
        if not rel:
            key_set.add(_rel_key(root / "__init__.py"))
            continue
        target = root / rel
        if (target.with_suffix(".py")).exists():
            key_set.add(_rel_key(target.with_suffix(".py")))
        if (target / "__init__.py").exists():
            key_set.add(_rel_key(target / "__init__.py"))


def _camel(stem: str) -> str:
    return "".join(p[:1].upper() + p[1:] for p in stem.split("_") if p)


def _build_fixture_map(
    surfaces: dict[str, ast.Module | None],
) -> dict[str, set[str]]:
    """surface 文件全集中提取 @pytest.fixture → 其体内 rfauto 候选（链式 fixture fixpoint）。"""
    raw: dict[str, tuple[list[str], set[str]]] = {}
    for key, tree in surfaces.items():
        if tree is None:
            continue
        mod_dotted, is_pkg = _module_dotted(key)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not any(
                (isinstance(d, ast.Attribute) and d.attr == "fixture")
                or (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr == "fixture")
                for d in node.decorator_list
            ):
                continue
            cands = {
                c
                for c in _collect_candidates(node, mod_dotted, is_pkg)
                if c == "rfauto" or c.startswith("rfauto.") or c == "tests" or c.startswith("tests.")
            }
            params = [a.arg for a in node.args.posonlyargs + node.args.args + node.args.kwonlyargs]
            prev = raw.get(node.name)
            if prev is not None:
                prev[1].update(cands)
            else:
                raw[node.name] = (params, cands)
    fixmap: dict[str, set[str]] = {name: set(cands) for name, (_p, cands) in raw.items()}
    for _ in range(len(raw) + 1):  # 链式 fixture：fixture g(f2) 继承 f2 的依赖，迭代到不动点
        changed = False
        for name, (params, _c) in raw.items():
            for p in params:
                if p in fixmap and not fixmap[p] <= fixmap[name]:
                    fixmap[name] |= fixmap[p]
                    changed = True
        if not changed:
            break
    return fixmap


def _function_param_names(tree: ast.Module | None) -> set[str]:
    if tree is None:
        return set()
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            a = node.args
            out.update(x.arg for x in a.posonlyargs + a.args + a.kwonlyargs)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="构建 src 模块 → tests/unit 测试文件影响面映射")
    parser.add_argument("--out", default="runs/aurora_m/impact_map.yaml", help="输出 YAML 路径")
    parser.add_argument(
        "--force", action="store_true", help="忽略指纹缓存强制全量重建（缺省输入未变时秒回跳过）"
    )
    args = parser.parse_args(argv)
    out_path = Path(args.out)

    # ── 指纹快路径：输入未变 → 秒回（W2-1 增量缓存）──────────────────────────
    fp_path = default_fingerprint_path(out_path)
    if not args.force and out_path.exists() and fp_path.exists():
        try:
            stored = json.loads(fp_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, ValueError):
            stored = None
        reason = check_fresh(stored, out_path, scope="full")
        if not reason:
            print(f"[build_impact_map] 指纹新鲜（tests 面+src 全未变，builder 一致）→ 跳过重建：{out_path}")
            return 0
        print(f"[build_impact_map] 指纹过期：{reason} → 全量重建…")

    # ── 收集文件面 ────────────────────────────────────────────────────────────
    src_files, surface_files = collect_file_lists()
    src_keys = {_rel_key(p) for p in src_files}
    surface_keys = [_rel_key(p) for p in surface_files]

    src_trees: dict[str, ast.Module | None] = {}
    src_syntax_err: list[str] = []
    for p in src_files:
        key = _rel_key(p)
        try:
            src_trees[key] = ast.parse(_read(p))
        except SyntaxError:
            src_trees[key] = None
            src_syntax_err.append(key)

    surfaces: dict[str, ast.Module | None] = {}
    surf_syntax_err: list[str] = []
    for key in surface_keys:
        try:
            surfaces[key] = ast.parse(_read(REPO / key))
        except SyntaxError:
            surfaces[key] = None
            surf_syntax_err.append(key)

    # ── src 依赖图（边：F import G）─────────────────────────────────────────
    deps: dict[str, set[str]] = {k: set() for k in src_keys}
    for key, tree in src_trees.items():
        mod_dotted, is_pkg = _module_dotted(key)
        for cand in _collect_candidates(tree, mod_dotted, is_pkg):
            if cand == "rfauto" or cand.startswith("rfauto."):
                _resolve_under(SRC_ROOT, "rfauto", cand, deps[key])
        deps[key].discard(key)

    # ── 双源属性集（per surface 文件）────────────────────────────────────────
    own_import: dict[str, set[str]] = {k: set() for k in surface_keys}
    own_grep: dict[str, set[str]] = {k: set() for k in surface_keys}
    surf_edges: dict[str, set[str]] = {k: set() for k in surface_keys}

    for key, tree in surfaces.items():
        mod_dotted, is_pkg = _module_dotted(key)
        for cand in _collect_candidates(tree, mod_dotted, is_pkg):
            if cand == "rfauto" or cand.startswith("rfauto."):
                _resolve_under(SRC_ROOT, "rfauto", cand, own_import[key])
            elif cand == "tests" or cand.startswith("tests."):
                _resolve_under(TESTS_ROOT, "tests", cand, surf_edges[key])
        surf_edges[key].discard(key)

    # grep 面：token → src 模块集（同 stem 跨包重名时并集，宁多勿漏）
    # 三类 token：①裸 stem ②驼峰变体（仅这两个受词频上限约束——语料通用词如 "runs" 会
    #   子串命中数百无关文件）；③模块全点路径（精确，只在真实引用中出现，不设上限）。
    token_map: dict[str, set[str]] = {}
    dotted_tokens: set[str] = set()
    skipped_short = 0
    for mkey in sorted(src_keys):
        stem = mkey.rsplit("/", 1)[-1][: -len(".py")]
        toks: set[str] = set()
        if stem == "__init__":
            pkg = mkey[len("src/rfauto/") : -len("__init__.py")].rstrip("/")
            toks.add("rfauto" if not pkg else "rfauto." + pkg.replace("/", "."))
        else:
            if len(stem) >= MIN_TOKEN_LEN:
                toks.add(stem)
                toks.add(_camel(stem))
            else:
                skipped_short += 1
            toks.add(mkey[len("src/") : -len(".py")].replace("/", "."))
        for t in toks:
            token_map.setdefault(t, set()).add(mkey)
            if t == "rfauto" or t.startswith("rfauto."):
                dotted_tokens.add(t)

    surface_text: dict[str, str] = {k: _read(REPO / k) for k in surface_keys}
    file_tokens: dict[str, set[str]] = {}
    for key, text in surface_text.items():
        if not text:
            continue
        hits = {tok for tok in token_map if tok in text}
        if hits:
            file_tokens[key] = hits
    df: dict[str, int] = {}
    for toks in file_tokens.values():
        for t in toks:
            df[t] = df.get(t, 0) + 1
    df_cap = max(2, int(len(surface_keys) * 0.35))
    dropped_common: set[str] = set()
    for key, toks in file_tokens.items():
        for t in toks:
            if t not in dotted_tokens and df[t] > df_cap:
                dropped_common.add(t)  # 语料通用词 stem：grep 信号淹没在噪声里，仅弃 stem 不弃点路径
                continue
            own_grep[key].update(token_map[t])

    # fixture 依赖按参数名匹配（含 conftest/helper 内定义的 fixture）
    fixmap = _build_fixture_map(surfaces)
    fixture_hits = 0
    for key, tree in surfaces.items():
        for p in _function_param_names(tree):
            if p not in fixmap:
                continue
            fixture_hits += 1
            for cand in fixmap[p]:  # rfauto → src 键；tests → surface 边（fixture 体引 helper 同理传播）
                if cand == "rfauto" or cand.startswith("rfauto."):
                    _resolve_under(SRC_ROOT, "rfauto", cand, own_import[key])
                elif cand == "tests" or cand.startswith("tests."):
                    _resolve_under(TESTS_ROOT, "tests", cand, surf_edges[key])

    # conftest 顶层 import + 文本 grep 命中 → 下发子树全部测试（收集期依赖语义）
    unit_test_keys = [
        k
        for k in surface_keys
        if k.startswith("tests/unit/") and Path(k).name.startswith("test_") and k.endswith(".py")
    ]
    for ckey in CONTESTS:
        if ckey not in surfaces:
            continue
        tree = surfaces[ckey]
        dist: set[str] = set()  # grep 命中不整体下发：conftest 文本里的 rfauto 字面量
        # 几乎都在 fixture 体内，走参数名匹配已覆盖；整体下发会把 fake_adapter 平摊给全部测试
        if tree is not None:  # 仅顶层语句的 import（fixture 体内走参数匹配）
            mod_dotted, is_pkg = _module_dotted(ckey)
            for node in tree.body:
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    for cand in _collect_candidates(ast.Module(body=[node], type_ignores=[]), mod_dotted, is_pkg):
                        if cand == "rfauto" or cand.startswith("rfauto."):
                            _resolve_under(SRC_ROOT, "rfauto", cand, dist)
        for tk in unit_test_keys:
            own_import[tk].update(dist)

    # surface 传播：importer 继承被导入文件的全部属性（测试→helper/helper→测试 均沿边向上）
    def _reachable_edges(start: str) -> set[str]:
        seen: set[str] = set()
        stack = [start]
        while stack:
            cur = stack.pop()
            for nxt in surf_edges[cur]:
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        return seen

    eff_import: dict[str, set[str]] = {}
    eff_grep: dict[str, set[str]] = {}
    for key in surface_keys:
        imp: set[str] = set()
        grp: set[str] = set()
        for f in {key, *_reachable_edges(key)}:
            imp |= own_import[f]
            grp |= own_grep[f]
        eff_import[key] = imp
        eff_grep[key] = grp

    # ── src 传递闭包（import 源与 grep 源分别闭包以保留归因，并集出映射）──────
    def _close(start_set: set[str]) -> set[str]:
        seen: set[str] = set()
        stack = list(start_set)
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(deps.get(cur, ()))
        return seen

    rev_import: dict[str, set[str]] = {k: set() for k in src_keys}
    rev_grep: dict[str, set[str]] = {k: set() for k in src_keys}
    rev_direct: dict[str, set[str]] = {k: set() for k in src_keys}
    for tk in unit_test_keys:
        for m in _close(eff_import[tk]):
            rev_import[m].add(tk)
        for m in _close(eff_grep[tk]):
            rev_grep[m].add(tk)
        for m in eff_import[tk] | eff_grep[tk]:  # 直连面（不做 src 闭包）：W2-1 devtest 缺省口径
            rev_direct[m].add(tk)

    modules: dict[str, list[str]] = {}
    both = import_only = grep_only = 0
    for mkey in sorted(src_keys):
        tests = sorted(rev_import[mkey] | rev_grep[mkey])
        modules[mkey] = tests
        has_i = bool(rev_import[mkey])
        has_g = bool(rev_grep[mkey])
        if has_i and has_g:
            both += 1
        elif has_i:
            import_only += 1
        elif has_g:
            grep_only += 1
    modules_direct = {
        mkey: sorted(rev_direct[mkey]) for mkey in sorted(src_keys) if rev_direct[mkey]
    }

    ordered = dict(sorted(modules.items(), key=lambda kv: (-len(kv[1]), kv[0])))
    counts = [len(v) for v in ordered.values()]
    total_pairs = sum(counts)
    direct_counts = [len(v) for v in modules_direct.values()]
    direct_pairs = sum(direct_counts)

    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.strip()

    n_src = len(src_keys)
    data = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "git_head": head,
        "stats": {
            "src_modules": n_src,
            "unit_test_files": len(unit_test_keys),
            "surface_files_total": len(surface_keys),
            "avg_tests_per_module": round(total_pairs / n_src, 2) if n_src else 0.0,
            "max_tests_per_module": max(counts) if counts else 0,
            "avg_tests_per_module_direct": round(direct_pairs / n_src, 2) if n_src else 0.0,
            "max_tests_per_module_direct": max(direct_counts) if direct_counts else 0,
            "modules_direct_nonempty": len(modules_direct),
            "zero_coverage_modules": sum(1 for c in counts if c == 0),
            "grep_tokens": len(token_map),
            "grep_tokens_skipped_short_stem": skipped_short,
            "grep_tokens_dropped_common": len(dropped_common),
            "grep_df_cap_files": df_cap,
            "fixture_param_matches": fixture_hits,
        },
        "_meta": {
            "method": "双源并集（宁多勿漏）：AST import 图（全层级，含延迟 import）+ src 依赖闭包；"
            "模块 stem/驼峰/包点路径 token 在 tests/unit 文本子串扫描（等价 git grep 面）",
            "source_contrib": {"import_and_grep": both, "import_only": import_only, "grep_only": grep_only},
            "conftest_rule": "conftest 顶层 import 下发目录子树全部测试（收集期依赖）；"
            "fixture 体内 import 按 fixture 参数名匹配下发（链式 fixture fixpoint）；"
            "conftest 文本 grep 命中不整体下发（字面量几乎都在 fixture 体内，避免平摊）",
            "token_rule": f"stem 与驼峰变体 ≥{MIN_TOKEN_LEN} 字符且文档频率 ≤{df_cap} 文件"
            "（语料通用词如 runs 子串命中数百无关文件，弃 stem 保点路径）；"
            "模块全点路径与 __init__.py 包点路径不设上限（只在真实引用中出现）；"
            "__init__.py 用包点路径（子串匹配，父包 __init__ 覆盖其全部子模块引用——"
            "import 语义正确且宁多）；同 stem 跨包重名 grep 并集",
            "surface_scope": "tests/unit/**/*.py + tests/conftest.py + tests/__init__.py；"
            "tests/real_edt、tests/integration、tests/gold(en)、tests/fixtures 不属 unit 门面，排除",
            "syntax_error_files": src_syntax_err + surf_syntax_err,
            "notes": [
                "AST 解析纯 ast.parse，不执行任何测试/src 代码",
                "闭包方向：测试直接依赖的模块沿 src import 边向下展开，改任意传递依赖均算受影响",
                "零测试覆盖模块登记空列表，不允许缺键（100% src 模块出现）",
                "modules=传递闭包面（宁多勿漏，合流/预检口径）；modules_direct=直连面（import 直连+grep，"
                "不做 src 闭包，W2-1 devtest 缺省口径——如 runs_verify_service 直连 ≈9 文件、闭包 ≈1096）",
                "新鲜度=W2-1 内容指纹（.impact_map_fingerprint.json，tests 面+src 哈希+builder 哈希）；"
                "git_head 仅为构建时点信息，不再作过期判据（docs-only 提交不再触发 80s 重建；"
                "direct 口径下 src 内容变化也不触发——直连面与 src 内容无关）",
            ],
        },
        "modules": ordered,
        "modules_direct": dict(sorted(modules_direct.items(), key=lambda kv: (-len(kv[1]), kv[0]))),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    text_out = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120)
    out_path.write_text(text_out, encoding="utf-8")
    fp_path.write_text(
        json.dumps(build_fingerprint(out_path), ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )

    print(f"written: {out_path} ({len(text_out) / 1e6:.1f} MB)")
    print(f"fingerprint: {fp_path}")
    print(f"src_modules={n_src} unit_test_files={len(unit_test_keys)} "
          f"avg={data['stats']['avg_tests_per_module']} max={data['stats']['max_tests_per_module']} "
          f"zero_cov={data['stats']['zero_coverage_modules']}")
    print(f"source_contrib: both={both} import_only={import_only} grep_only={grep_only}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
