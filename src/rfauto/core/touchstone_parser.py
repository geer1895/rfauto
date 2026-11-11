"""Touchstone（.sNp）结构化解析内核（aurora_q 席位 Q-X64，2026-11-08）。

把 #248（skrf 只按扩展名推断 rank）、#287（dB 写出/读回频率 ulp 噪声—
interp1d bounds）、#309（4×4 模态数据按端口边界数命名 .s2p）三次 ad-hoc
修复**单源化**为确定性内核：格式嗅探 + rank 三规则推断（冲突如实报
disagreement 不猜，宁 UNKNOWN 不误判）+ 三格式解码（RI/MA/DB 表驱动）
+ 频轴对齐工具 + Σ模数形状判定 + skrf 桥。既有消费者（adapters/hfss_
adapter.infer_touchstone_port_count 等）后续席位逐步迁移，本席零改既有
消费方。

铁律 7：本模块 = 确定性文本解析内核——所有数值只由本文件代码产出，
零网络零真机零 LLM。核心推断逻辑纯 Python（math.isqrt 等），skrf 只在
:func:`to_skrf_network` 最终桥接时惰性导入（导入失败 ImportError 透传
fail-loud——skrf 是仓内既有依赖）。

格式口径（三层出处）：
1. Touchstone 2.0 规范（IBIS Open Forum 2009-04-24 批准版；microwaves101
   encyclopedias/snp-format 公开转述同口径）：
   - v1.0：option line ``# <freq_unit> <param> <format> R <n> [N]``；
     1 端口每行 ``freq S11(2)``；2 端口**每频率单行 9 值、legacy 列序
     S11 S21 S12 S22**（与矩阵行列序相反的历史约定）；N≥3 端口每频率
     占 ``n·ceil(n/4)`` 行、仅首行带频率、行内至多 4 个参量、整体**行主序**
     S11 S12 … S1n S21 …（与 skrf 行主序填充一致）；noise data 段每行
     5 值 ``freq NFmin(dB) |Γopt| ∠Γopt(deg) Rn(归一)``（Γopt 恒 MA 形态）。
   - v2.0：``[Version] 2.0`` + option line + 关键字块（[Number of Ports]/
     [Two-Port Data Order] rows_12_21|rows_21_12/[Number of Frequencies]/
     [Matrix Format] Full|Upper|Lower|…/[Reference] 逐端口/[Network Data]/
     [Number of Noise Frequencies]/[Noise Data]/[End]）；数据每频率
     ``2n²+1`` token（跨行 continuation 同型累积，[Network Data] 与
     [Noise Data] 均可省缺——skrf parse_network 缺省 True 同口径）；
     2 端口行主序缺省（本实现按规范默认 rows_12_21，缺关键字时带警告
     ——skrf 同场景按 legacy 列序解，两者口径差如实登记见 warnings）。
2. #248 实证（hfss_adapter.infer_touchstone_port_count 先例）：rank 推断
   不能只看首行值数 ``(V-1)//2``（2 端口 9 值被误判 4 端口）——须按
   "到下一同值数行之前的块行数"消歧。
3. #287/#294 实证：dB 形式写出/读回频率带 ~1e-7 Hz 浮点噪声——对拍前
   频轴对齐：同栅 rtol 直接比对 / 异栅 argmin 真最近邻 + 端点 ulp 容差
   （禁 searchsorted 越位一格）。

rank 三规则按序（任务书契约）：
  ①文件名 ``.sNp`` 的 N（N≤9 可信；≥10 记录但不可信不进共识）；
  ②首行值数推（v1.0：值数→候选集 {3→1}、{9→2|4|5|…}、{7→3}——单规则
    不完备，交③消歧；v2.0：首行 token 数 ``2n²+1`` 直接解 n）；
  ③块结构交叉验证（v1.0 块行数 = n·ceil(n/4) 直接定 n；v2.0 总 token
    流按 ``2n²+1`` 分组交叉验证）。
  ②③内容共识冲突 → n_ports=None + disagreements（宁 UNKNOWN 不误判）；
  内容共识与①文件名冲突 → 内容为准 + disagreement 登记（#248 口径：
  扩展名由实际端口数决定）。

诚实语义（#122 族）：无 option line / 结构违规 → fail-loud
TouchstoneParseError（service 层转 error 信封）；rank 冲突不猜、
s_matrix=None；[Matrix Format] 非 Full → 如实登记不解析矩阵；noise 段
按 5 值行形态登记原文不深解析；v2.0 缺 [Two-Port Data Order] 的 2 端口
文件按规范默认行主序解码并带 skrf 口径差警告。

本模块不设 ``__all__``（无 __all__ 的非门面文件不进
tests/gold/public_api.json——sdf_parser/sdf_service 同款先例，新模块零
金快照漂移）。
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

import numpy as np


class TouchstoneParseError(ValueError):
    """Touchstone 结构违规（无 option line/解码失败/rank 冲突不可解析）。"""


#: 解析输出 schema 版本（键集/字段形状变更时升位）。
PARSER_SCHEMA_VERSION = "1.0"


#: 频率单位 → Hz 换算表（option line 首 token，大小写不敏感；表驱动）。
_FREQ_UNIT_MULT: dict[str, float] = {
    "HZ": 1.0,
    "KHZ": 1e3,
    "MHZ": 1e6,
    "GHZ": 1e9,
    "THZ": 1e12,
}

#: 合法参数类型（option line 第 2 token）。
_PARAM_TYPES = ("S", "Y", "Z", "H", "G")

#: 合法数据格式（option line 第 3 token）。
_DATA_FORMATS = ("DB", "MA", "RI")

#: 文件名 .sNp 的 N 可信上限（任务书契约：N≤9 可信）。
_FILENAME_N_TRUSTED_MAX = 9

#: rank 推断搜索上限（v1.0 实用范围；hfss_adapter._MAX_INFER_PORTS 同口径）。
_MAX_INFER_PORTS = 64

#: v1.0 2 端口 legacy 列序（S11 S21 S12 S22）→ 行主序放置位置表：
#: flat = [S11, S21, S12, S22]（列序），行主序 M[0,0]=flat0、M[1,0]=flat1、
#: M[0,1]=flat2、M[1,1]=flat3。
_LEGACY_2PORT_PLACE = ((0, 0), (1, 0), (0, 1), (1, 1))

#: 文件名 rank 推断正则（.sNp / .SNp 大小写不敏感）。
_SNP_SUFFIX_RE = re.compile(r"^\.s(\d+)p$", re.IGNORECASE)

#: v2.0 关键字行正则（[Keyword] 值…；大小写不敏感）。
_V2_KEYWORD_RE = re.compile(
    r"^\[(?P<key>[a-z][a-z0-9 -]*)\]\s*(?P<val>.*)$", re.IGNORECASE)


# ── 文本读入与行扫描（sniff/parse 共用的单遍确定性扫描） ─────────────────────


def _read_text(path: Path) -> str:
    """读文件文本：utf-8-sig 优先（BOM 剥离），Latin-1 兜底（sdf_service 同款）。"""
    data = path.read_bytes()
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _scan_text(text: str, warnings: list[str]) -> dict[str, Any]:
    """单遍扫描 → option line / v2 关键字块 / 数据行 / noise 段行。

    - 注释行（'!' 起，任意位置）跳过；行内 '!' 起注释截断；
    - v2.0 关键字行（[Keyword] 形态）收进 keywords dict（大小写不敏感）；
    - 数据行收进 rows（token 列表序）；[Noise Data] 标记后的数据行单独
      收进 noise_rows（v2.0 noise 段；无标记 → noise_rows 恒空，尾部
      token 由 parse 按组数余量判定）；
    - version 只在扫描完后推断（避免数据行先于 [Version] 出现的时序错判
      ——数据行 v1/v2 形态统一收 rows，按最终版本选择解释）。
    """
    option_raw: str | None = None
    keywords: dict[str, str] = {}
    rows: list[list[str]] = []
    noise_rows: list[list[str]] = []
    in_noise = False
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        kw = _V2_KEYWORD_RE.match(stripped)
        if kw is not None:
            key = kw.group("key").lower()
            keywords[key] = kw.group("val").strip()
            if key == "noise data":
                in_noise = True
            continue
        if stripped.startswith("!"):
            continue
        if stripped.startswith("#"):
            if option_raw is None:
                option_raw = stripped
            else:
                warnings.append("重复 option line，按首条解（余者忽略）")
            continue
        body = _strip_comment(stripped).strip()
        if not body:
            continue
        if in_noise:
            noise_rows.append(body.split())
        else:
            rows.append(body.split())
    return {
        "option_raw": option_raw,
        "keywords": keywords,
        "rows": rows,
        "noise_rows": noise_rows,
    }


def _strip_comment(line: str) -> str:
    """去行内注释（'!' 起、行尾止）——v1.0/v2.0 通用（v2.0 continuation '!'
    在行尾，剥后对 token 累积无影响）。"""
    return line.split("!", 1)[0]


def _parse_option_line(line: str, warnings: list[str]) -> dict[str, Any]:
    """option line → 格式四元组（缺 token 按规范缺省 GHZ S MA R 50 补，带警告）。

    顺序无关扫描（``# R 50 GHZ S RI`` 变体同解）；data_format/param_type
    只取首个（多次出现按首个，余者忽略）；R n 二元组；尾缀 N = noise
    旗标；IL/RL = v2.0 混合模态 option line（矩阵数值结构同 S，语义如实
    登记不展开）。
    """
    tokens = line.split("#", 1)[1].split()
    fmt: dict[str, Any] = {
        "freq_unit": "GHZ",
        "param_type": "S",
        "data_format": "MA",
        "r_ref": 50.0,
        "noise_flag": False,
        "mixed_mode": False,
    }
    if not tokens:
        warnings.append("option line 无有效 token，按规范缺省 GHZ S MA R 50 解")
        return fmt
    if tokens[0].upper() not in _FREQ_UNIT_MULT:
        warnings.append(
            f"option line 首 token {tokens[0]!r} 非频率单位，按缺省 GHZ 解")
    else:
        fmt["freq_unit"] = tokens[0].upper()
    rest = tokens[1:]
    have_format = False
    have_param = False
    for idx, tok in enumerate(rest):
        up = tok.upper()
        if up in _DATA_FORMATS and not have_format:
            fmt["data_format"] = up
            have_format = True
        elif up in _PARAM_TYPES and not have_param:
            fmt["param_type"] = up
            have_param = True
        elif up == "R" and idx + 1 < len(rest):
            try:
                fmt["r_ref"] = float(rest[idx + 1])
            except ValueError:
                warnings.append(
                    f"option line R 后非数字 {rest[idx + 1]!r}，参考阻抗按 50")
        elif up == "N":
            fmt["noise_flag"] = True
        elif up in ("IL", "RL"):
            fmt["mixed_mode"] = True
    return fmt


# ── rank 三规则推断 ──────────────────────────────────────────────────────────


def _filename_rank(path: Path) -> tuple[int | None, bool, str | None]:
    """文件名 .sNp → (N, 可信, 注记)。非 .sNp 后缀 → (None, False, 注记)。"""
    suffix = path.suffix
    m = _SNP_SUFFIX_RE.match(suffix)
    if not m:
        return None, False, f"后缀 {suffix!r} 非 .sNp 形态，规则①无证据"
    n = int(m.group(1))
    if 1 <= n <= _FILENAME_N_TRUSTED_MAX:
        return n, True, None
    return n, False, (
        f"文件名 N={n} >{_FILENAME_N_TRUSTED_MAX}，按任务书契约不可信（不进共识）")


def _infer_rank_first_line_v1(
    first_count: int | None,
) -> tuple[list[int] | None, str | None]:
    """v1.0 首行值数 → 候集（单规则不完备：9 值歧义 2|4|5|…，交③消歧）。"""
    if first_count is None:
        return None, "零数据行，规则②无证据"
    if first_count == 3:
        return [1], None
    if first_count == 7:
        return [3], None
    if first_count == 9:
        # 2 端口（单行 9 值）与 N≥4（首行 1+2·min(n,4)=9）共享形态
        return list(range(2, _MAX_INFER_PORTS + 1)), None
    if first_count == 1:
        return [], "首行仅频率无参量值，rank 无候选"
    # 单行折叠全矩阵形态（aurora_r M-8 2026-11-10 补：v1.0 亦允许每频点
    # 1+2n² 单行折叠——3 端口=19/4 端口=33/…；fuzz 合成器与部分工具导出
    # 即此形态，#248 扩展名-rank 契约的词表补全）。n=√((count-1)/2) 为整
    # 数且 ≥3 才认定（9 值二义已在上分支按 2 端口 RI 单行处理）。
    if first_count > 9 and (first_count - 1) % 2 == 0:
        n_fold = round(((first_count - 1) / 2) ** 0.5)
        if (n_fold >= 3 and n_fold <= _MAX_INFER_PORTS
                and 2 * n_fold * n_fold + 1 == first_count):
            return [n_fold], None
    return None, f"首行值数 {first_count} 不匹配 v1.0 任何端口形态（3/7/9/折叠 2n²+1）"


def _infer_rank_first_line_v2(
    first_count: int | None,
) -> tuple[list[int] | None, str | None]:
    """v2.0 首行 token 数 = 2n²+1 直接解 n（任务书规则② 2.0 口径）。"""
    if first_count is None:
        return None, "零数据行，规则②无证据"
    if first_count < 3 or (first_count - 1) % 2 != 0:
        return None, (
            f"首行 token 数 {first_count} 非 2n²+1 形态（疑似 continuation 截断）")
    entries = (first_count - 1) // 2
    n = math.isqrt(entries)
    if n * n != entries:
        return None, (
            f"首行 token 数 {first_count}（(V-1)/2={entries} 非完全平方）"
            "不匹配 2n²+1")
    return [n], None


def _block_period(counts: list[int]) -> int | None:
    """块行数 = 首行到下一同值数行之前的行数（无重复到尾 → 全部行数）。

    v1.0 N≥3 时恰 = n·ceil(n/4)（仅频率首行带频率值、同频块内其余行值数
    恒异于首行——#248 实证口径）；1/2 端口每频率单行 → 1。
    """
    if not counts:
        return None
    first = counts[0]
    block = 1
    while block < len(counts) and counts[block] != first:
        block += 1
    return block


def _infer_rank_block_v1(
    counts: list[int],
) -> tuple[list[int] | None, int | None, str | None]:
    """v1.0 块结构 → 候选集（块行数 n·ceil(n/4) 直接定 n）+ 实测块行数。"""
    if not counts:
        return None, None, "零数据行，规则③无证据"
    first = counts[0]
    block = _block_period(counts)
    if first == 3 and block == 1:
        return [1], block, None
    if first == 9 and block == 1:
        return [2], block, None
    if first == 7:
        if block == 3:
            return [3], block, None
        return None, block, f"首行 7 值（3 端口形态）但块行数 {block}≠3，结构不一致"
    if first == 9:
        for n in range(4, _MAX_INFER_PORTS + 1):
            if block == n * (-(-n // 4)):  # ceil 整除惯语
                return [n], block, None
        return None, block, f"块行数 {block} 不匹配任何 n 的 n·ceil(n/4) 形态"
    # 单行折叠全矩阵形态（aurora_r M-8 2026-11-10，与规则②补丁同款词表：
    # v1.0 每频点 1+2n² 单行折叠——3 端口=19/4 端口=33；块行数恒 1）
    if first > 9 and (first - 1) % 2 == 0 and block == 1:
        n_fold = round(((first - 1) / 2) ** 0.5)
        if (n_fold >= 3 and n_fold <= _MAX_INFER_PORTS
                and 2 * n_fold * n_fold + 1 == first):
            return [n_fold], block, None
    return None, block, f"首行值数 {first} 不匹配 v1.0 任何端口形态（含折叠 2n²+1）"


def _infer_rank_block_v2(
    total_tokens: int, declared_nfreq: int | None,
) -> tuple[list[int] | None, str | None]:
    """v2.0 总 token 流按 2n²+1 分组交叉验证 → 候选集（任务书规则③ 2.0 口径）。"""
    if declared_nfreq is not None and declared_nfreq >= 1 \
            and total_tokens % declared_nfreq == 0:
        g = total_tokens // declared_nfreq
        if g >= 3 and (g - 1) % 2 == 0:
            entries = (g - 1) // 2
            n = math.isqrt(entries)
            if n * n == entries:
                return [n], None
    # 无 declared_nfreq / 声明不整除：按可分组形态穷举（多解=歧义如实）
    hits: list[int] = []
    for n in range(1, _MAX_INFER_PORTS + 1):
        g = 2 * n * n + 1
        if total_tokens >= g and total_tokens % g == 0:
            hits.append(n)
    if len(hits) == 1:
        return hits, None
    if len(hits) > 1:
        return hits, f"总 token 数 {total_tokens} 可被多个 2n²+1 整除（{hits}）——歧义"
    return None, f"总 token 数 {total_tokens} 不匹配任何 2n²+1 分组"


def _consensus(
    set_a: list[int], set_b: list[int],
    label_a: str, label_b: str, disagreements: list[str],
) -> int | None:
    """两规则候集求交：恰一解=共识；零解=冲突（disagreement 登记）；多解=歧义。"""
    inter = sorted(set(set_a) & set(set_b))
    if len(inter) == 1:
        return inter[0]
    if len(inter) == 0:
        disagreements.append(
            f"{label_a}候选{set_a[:8]} 与 {label_b}候选{set_b[:8]} 无交集（冲突）")
        return None
    disagreements.append(
        f"{label_a}∩{label_b}={inter[:8]} 仍歧义（宁 UNKNOWN 不猜）")
    return None


def _v1_split_noise_rows(rows: list[list[str]]) -> tuple[list[list[str]], list[list[str]]]:
    """v1.0 行序 → (矩阵行, noise 段行)：尾部**连续** 5 值行整段归 noise。

    v1.0 noise data 段布局 = 矩阵数据之后、EOF 之前的连续 5 值行（freq
    NFmin(dB) |Γopt| ∠Γopt(deg) Rn）；合法矩阵行值数（3/7/9/…偶数）恒
    ≠5，故尾部 5 值连续段无歧义。前置剥离——rank 推断与矩阵解析都只看
    矩阵行，noise 段混入会打红块结构/结构校验。
    """
    k = 0
    while k < len(rows) and len(rows[len(rows) - 1 - k]) == 5:
        k += 1
    if k == 0:
        return rows, []
    return rows[:len(rows) - k], rows[len(rows) - k:]


def _resolve_rank(
    sniff: dict[str, Any], warnings: list[str],
) -> dict[str, Any]:
    """rank 三规则按序共识（内容 ②∩③ → declared 关键字 → ①文件名参战）。"""
    keywords: dict[str, str] = sniff["_keywords"]
    version = sniff["version"]
    rows: list[list[str]] = sniff["_rows"]
    if version != "2.0":
        rows, _v1_noise = _v1_split_noise_rows(rows)
    disagreements: list[str] = []

    fn_rank, fn_trusted, fn_note = _filename_rank(Path(sniff["path"]))

    if version == "2.0":
        flat = [t for row in rows for t in row]
        declared_nfreq = _kw_int(keywords, "number of frequencies", warnings)
        first_count = len(rows[0]) if rows else None
        fl_cands, fl_note = _infer_rank_first_line_v2(first_count)
        fb_cands, fb_note = _infer_rank_block_v2(len(flat), declared_nfreq)
        rule_block = {"block": None, "candidates": fb_cands, "note": fb_note}
    else:
        counts = [len(r) for r in rows]
        first_count = counts[0] if counts else None
        fl_cands, fl_note = _infer_rank_first_line_v1(first_count)
        fb_cands, block_seen, fb_note = _infer_rank_block_v1(counts)
        rule_block = {"block": block_seen, "candidates": fb_cands, "note": fb_note}
    rule_first = {"value_count": first_count, "candidates": fl_cands,
                  "note": fl_note}

    # ②③内容共识（双边求交；单边采信有版本前提——宁 UNKNOWN 不误判）：
    #   v1.0 规则②单规则不完备（9 值歧义 2|4|5|…）→ ②单独不可采信；
    #   v2.0 规则②=2n²+1 直接解（完备）→ ②单独可采信；③两版皆完备。
    content_n: int | None = None
    resolution = "unknown"
    if fl_cands is not None and fb_cands is not None:
        content_n = _consensus(fl_cands, fb_cands, "规则②首行值数",
                               "规则③块结构", disagreements)
        resolution = "content_consensus" if content_n is not None else "conflict"
    elif fb_cands is not None:
        content_n = fb_cands[0] if len(fb_cands) == 1 else None
        if content_n is not None:
            resolution = "content_consensus"
        if fl_note:
            warnings.append(f"规则②首行值数缺证据/歧义：{fl_note}")
    elif fl_cands is not None:
        if version == "2.0" and len(fl_cands) == 1:
            content_n = fl_cands[0]
            resolution = "content_consensus"
            if fb_note:
                warnings.append(f"规则③块结构缺证据/歧义：{fb_note}"
                                "（v2.0 规则② 2n²+1 直接解可单独采信）")
        else:
            if fb_note:
                warnings.append(f"规则③块结构缺证据/歧义：{fb_note}")
            warnings.append(
                "v1.0 规则②单规则不完备且规则③无证据——宁 UNKNOWN 不误判")
    else:
        for note in (fl_note, fb_note):
            if note:
                warnings.append(note)

    # v2.0 [Number of Ports] 关键字 = 独立第四证据参战（声明可错，数据不会）
    declared = _kw_int(keywords, "number of ports", warnings)
    if declared is not None:
        if content_n is None and resolution != "conflict":
            content_n = declared
            resolution = "declared_keyword_only"
            warnings.append(
                f"内容规则不可解，n_ports 按 v2.0 [Number of Ports]={declared} 采信")
        elif content_n is None:
            disagreements.append(
                f"v2.0 [Number of Ports]={declared} 与内容规则冲突态并存——"
                "冲突优先，不采信声明（宁 UNKNOWN）")
        elif declared != content_n:
            disagreements.append(
                f"v2.0 [Number of Ports]={declared} 与内容推断 {content_n} 冲突"
                "（内容为准——关键字声明可错，数据不会）")
            content_n = None
            resolution = "conflict"

    # ①文件名证据（N≤9 可信）参战：与内容共识冲突 → 内容为准 + 登记（#248）
    if fn_trusted and content_n is not None and fn_rank != content_n:
        disagreements.append(
            f"文件名 .s{fn_rank}p 推断 N={fn_rank} 与内容推断 N={content_n} 冲突"
            "（内容为准——#248 口径：扩展名由实际端口数决定）")
        resolution = "content_consensus_filename_conflict"

    return {
        "rule_filename": fn_rank,
        "rule_filename_trusted": fn_trusted,
        "rule_filename_note": fn_note,
        "rule_first_line": rule_first,
        "rule_block": rule_block,
        "declared_keyword": declared,
        "n_ports": content_n,
        "resolution": resolution,
        "disagreements": disagreements,
    }


def _kw_int(keywords: dict[str, str], key: str, warnings: list[str]) -> int | None:
    """v2.0 关键字整数值（缺键 None；不可解析 → 警告 + None）。"""
    raw = keywords.get(key)
    if raw is None:
        return None
    first = raw.split()[0] if raw.split() else ""
    try:
        return int(first)
    except ValueError:
        warnings.append(f"[{key}] 值不可解析: {raw!r}（如实弃用）")
        return None


# ── 嗅探 ─────────────────────────────────────────────────────────────────────


def sniff_touchstone(path: str | Path) -> dict[str, Any]:
    """格式嗅探（公开面）：option line 四元组 + 版本 + v2.0 关键字块 +
    rank 三规则证据。返回 dict 去除内部态键（``_`` 前缀）——JSON 安全，
    不含矩阵数值与原始行。失败形态见 :func:`_sniff_core`。"""
    return {k: v for k, v in _sniff_core(path).items() if not k.startswith("_")}


def _sniff_core(path: str | Path) -> dict[str, Any]:
    """格式嗅探（内部全量态）：公开面见 :func:`sniff_touchstone`。

    返回 dict 含内部态键（``_keywords``/``_rows``/``_noise_rows``——原始
    token 行，parse 原地消费不进 JSON 面）；公开键形态与
    :func:`sniff_touchstone` 一致::

        {"path", "version": "1.0"|"2.0", "version_source",
         "freq_unit", "param_type", "data_format", "r_ref",
         "noise_flag", "mixed_mode", "option_line_raw",
         "v2": {"declared_n_ports", "declared_n_freqs", "two_port_order",
                "matrix_format", "reference_tokens", "network_data_marker",
                "noise_data_marker", "declared_n_noise_freqs",
                "mixed_mode_order", "other_keywords"},
         "rank": {...三规则证据+resolution+disagreements},
         "n_data_rows", "n_noise_rows", "warnings"}

    失败（不存在/不可读/空文件/无 option line）→ TouchstoneParseError
    fail-loud（service 层转 error 信封）。
    """
    p = Path(path)
    if not p.exists():
        raise TouchstoneParseError(f"Touchstone 文件不存在: {p}")
    try:
        text = _read_text(p)
    except OSError as exc:
        raise TouchstoneParseError(f"Touchstone 文件不可读: {exc}") from exc
    if not text.strip():
        raise TouchstoneParseError(f"Touchstone 文件为空: {p}")

    warnings: list[str] = []
    scan = _scan_text(text, warnings)
    if scan["option_raw"] is None:
        raise TouchstoneParseError(
            f"Touchstone 无 option line（'# GHz S RI R 50' 形态首行）: {p}")

    keywords = scan["keywords"]
    version = "1.0"
    version_source = "default"
    raw_version = keywords.get("version")
    if raw_version is not None:
        parts = raw_version.split()
        version = parts[0] if parts else "2.0"
        version_source = "keyword"
    elif any(k in keywords for k in (
            "number of ports", "network data", "matrix format", "reference")):
        version = "2.0"
        version_source = "structure"
        warnings.append("无 [Version] 关键字但含 v2.0 关键字块，按 2.0 结构推断")

    fmt = _parse_option_line(scan["option_raw"], warnings)
    if fmt["param_type"] not in _PARAM_TYPES:
        warnings.append(
            f"参数类型 {fmt['param_type']!r} 超出 {list(_PARAM_TYPES)}，"
            "数值结构按同型解（如实登记）")

    sniff: dict[str, Any] = {
        "path": str(p),
        "version": version,
        "version_source": version_source,
        "freq_unit": fmt["freq_unit"],
        "param_type": fmt["param_type"],
        "data_format": fmt["data_format"],
        "r_ref": fmt["r_ref"],
        "noise_flag": fmt["noise_flag"] or bool(keywords.get("noise data")),
        "mixed_mode": fmt["mixed_mode"],
        "option_line_raw": scan["option_raw"],
        "v2": {
            "declared_n_ports": _kw_int(keywords, "number of ports", warnings),
            "declared_n_freqs": _kw_int(
                keywords, "number of frequencies", warnings),
            "two_port_order": _kw_two_port_order(keywords, warnings),
            "matrix_format": _kw_word(keywords, "matrix format"),
            "reference_tokens": keywords.get("reference", "").split(),
            "network_data_marker": "network data" in keywords,
            "noise_data_marker": "noise data" in keywords,
            "declared_n_noise_freqs": _kw_int(
                keywords, "number of noise frequencies", warnings),
            "mixed_mode_order": keywords.get("mixed-mode order", "").split() or None,
            "other_keywords": sorted(
                k for k in keywords if k not in (
                    "version", "number of ports", "number of frequencies",
                    "two-port data order", "matrix format", "reference",
                    "network data", "noise data",
                    "number of noise frequencies", "mixed-mode order", "end")),
        },
        "n_data_rows": len(scan["rows"]),
        "n_noise_rows": len(scan["noise_rows"]),
        "warnings": warnings,
    }
    for unknown_key in sniff["v2"]["other_keywords"]:
        warnings.append(f"未识别 v2.0 关键字 [{unknown_key}]，如实跳过")
    # keywords/rows 内部态供 parse 复用（非 JSON 面——parse 原地消费）
    sniff["_keywords"] = keywords
    sniff["_rows"] = scan["rows"]
    sniff["_noise_rows"] = scan["noise_rows"]
    sniff["rank"] = _resolve_rank(sniff, warnings)
    return sniff


def _kw_two_port_order(keywords: dict[str, str], warnings: list[str]) -> str | None:
    """v2.0 [Two-Port Data Order] → rows_12_21|rows_21_12（缺关键字 None=规范默认）。"""
    raw = keywords.get("two-port data order")
    if raw is None:
        return None
    return "rows_21_12" if "21_12" in raw.lower() else "rows_12_21"


def _kw_word(keywords: dict[str, str], key: str) -> str | None:
    """v2.0 关键字单词值（[Matrix Format] Full 等；缺键 None）。"""
    raw = keywords.get(key)
    if raw is None:
        return None
    parts = raw.split()
    return parts[0].lower() if parts else None


# ── 数据解码（表驱动三格式） ─────────────────────────────────────────────────


def _decode_pair(values: list[float], data_format: str) -> complex:
    """单参量 2 值 → complex（RI 直取 / MA 幅角(deg) / DB=20log10|S| 换算）。

    换算表驱动已知量：DB −20 dB → |S|=10^(−20/20)=0.1（测试钉）。
    """
    if data_format == "RI":
        return complex(values[0], values[1])
    magnitude = values[0]
    angle_rad = math.radians(values[1])
    if data_format == "MA":
        return magnitude * complex(math.cos(angle_rad), math.sin(angle_rad))
    if data_format == "DB":
        lin = 10.0 ** (magnitude / 20.0)
        return lin * complex(math.cos(angle_rad), math.sin(angle_rad))
    raise TouchstoneParseError(f"未知数据格式: {data_format}")  # pragma: no cover


def _place_flat_into_matrix(
    pairs: list[complex], n: int, legacy_2port: bool,
) -> list[list[complex]]:
    """2n² 个参量复值 → (n,n) 矩阵（行主序；2 端口 legacy 列序重排）。"""
    matrix = [[0j] * n for _ in range(n)]
    if legacy_2port and n == 2:
        # flat = [S11, S21, S12, S22]（列序）→ 行主序放置
        for flat_idx, (row, col) in enumerate(_LEGACY_2PORT_PLACE):
            matrix[row][col] = pairs[flat_idx]
        return matrix
    idx = 0
    for row in range(n):
        for col in range(n):
            matrix[row][col] = pairs[idx]
            idx += 1
    return matrix


def _parse_v1_data(
    data_rows: list[list[str]], n: int, data_format: str, freq_mult: float,
    fold_form: bool = False,
) -> tuple[list[float], list[list[list[complex]]]]:
    """v1.0 数据行 → (freqs_hz, s 矩阵序列)。结构违规 fail-loud（宁不错位）。"""
    freqs: list[float] = []
    matrices: list[list[list[complex]]] = []
    legacy_2port = n == 2
    # 折叠单行形态（aurora_r M-8 2026-11-10）：v1.0 每频点 1+2n² 单行折叠
    # 对任意 n 统一走单行路径（n≥3 经典分块路径仅 non-fold 分派）
    if fold_form:
        expected = 1 + 2 * n * n
        for row_no, row in enumerate(data_rows, start=1):
            if len(row) != expected:
                raise TouchstoneParseError(
                    f"v1.0 {n} 端口折叠数据行应 {expected} 值，行 {row_no} 实 "
                    f"{len(row)}（结构违规，宁 fail-loud 不错位解析）")
            freqs.append(float(row[0]) * freq_mult)
            vals = [float(v) for v in row[1:]]
            pairs = [_decode_pair(vals[2 * k:2 * k + 2], data_format)
                     for k in range(n * n)]
            matrices.append(_place_flat_into_matrix(pairs, n, legacy_2port))
        return freqs, matrices
    if n <= 2:
        expected = 1 + 2 * n * n
        for row_no, row in enumerate(data_rows, start=1):
            if len(row) != expected:
                raise TouchstoneParseError(
                    f"v1.0 {n} 端口数据行应 {expected} 值，行 {row_no} 实 "
                    f"{len(row)}（结构违规，宁 fail-loud 不错位解析）")
            freqs.append(float(row[0]) * freq_mult)
            vals = [float(v) for v in row[1:]]
            pairs = [_decode_pair(vals[2 * k:2 * k + 2], data_format)
                     for k in range(n * n)]
            matrices.append(_place_flat_into_matrix(pairs, n, legacy_2port))
        return freqs, matrices
    # n≥3：块 = n·ceil(n/4) 行，仅首行带频率，值行主序摊平
    per_block = n * (-(-n // 4))
    if len(data_rows) % per_block != 0:
        raise TouchstoneParseError(
            f"v1.0 {n} 端口数据行数 {len(data_rows)} 非 {per_block}"
            f"（块行数）整数倍（结构违规，宁 fail-loud 不错位解析）")
    expected_flat = 2 * n * n
    for block_start in range(0, len(data_rows), per_block):
        block = data_rows[block_start:block_start + per_block]
        freqs.append(float(block[0][0]) * freq_mult)
        flat_tokens: list[str] = list(block[0][1:])
        for row in block[1:]:
            flat_tokens.extend(row)
        if len(flat_tokens) != expected_flat:
            raise TouchstoneParseError(
                f"v1.0 {n} 端口频率块（行 {block_start + 1} 起）应 "
                f"{expected_flat} 值，实 {len(flat_tokens)}（结构违规）")
        vals = [float(v) for v in flat_tokens]
        pairs = [_decode_pair(vals[2 * k:2 * k + 2], data_format)
                 for k in range(n * n)]
        matrices.append(_place_flat_into_matrix(pairs, n, False))
    return freqs, matrices


def _parse_v2_data(
    tokens: list[str], n: int, data_format: str, freq_mult: float,
    declared_nfreq: int | None, legacy_2port: bool, warnings: list[str],
) -> tuple[list[float], list[list[list[complex]]], list[str]]:
    """v2.0 token 流 → (freqs_hz, s 矩阵序列, noise 段余 token)。

    每频率 ``2n²+1`` token（freq + 2n² 值），continuation 跨行同型累积；
    [Number of Frequencies] 声明数与实际组数不符 → fail-loud（声明是结构
    契约，静默吞会错位）。
    """
    group = 2 * n * n + 1
    if len(tokens) < group:
        raise TouchstoneParseError(
            f"v2.0 {n} 端口数据 token {len(tokens)} < 单频率组 {group}"
            "（结构违规）")
    if declared_nfreq is not None:
        n_freqs = declared_nfreq
        expected_total = n_freqs * group
        if len(tokens) < expected_total:
            raise TouchstoneParseError(
                f"v2.0 [Number of Frequencies]={n_freqs} 需 {expected_total} "
                f"token，实 {len(tokens)}（结构违规）")
    else:
        n_freqs = len(tokens) // group
        remainder = len(tokens) % group
        if remainder:
            warnings.append(
                f"v2.0 无 [Number of Frequencies]，token {len(tokens)} 按 "
                f"{group} 分组余 {remainder}——余量按 noise 段候选登记")
    noise_tokens = tokens[n_freqs * group:]
    freqs: list[float] = []
    matrices: list[list[list[complex]]] = []
    n_pairs = n * n
    for g_idx in range(n_freqs):
        chunk = tokens[g_idx * group:(g_idx + 1) * group]
        freqs.append(float(chunk[0]) * freq_mult)
        vals = [float(v) for v in chunk[1:]]
        pairs = [_decode_pair(vals[2 * k:2 * k + 2], data_format)
                 for k in range(n_pairs)]
        matrices.append(_place_flat_into_matrix(pairs, n, legacy_2port))
    return freqs, matrices, noise_tokens


def _register_noise_rows(
    rows: list[list[str]], declared: int | None, warnings: list[str],
) -> dict[str, Any]:
    """noise 段行 → 如实登记（5 值行形态 freq NFmin(dB) |Γopt| ∠Γopt Rn；
    Γopt 恒 MA 形态；不深解析语义细节——任务书已知限制）。"""
    if not rows:
        return {"present": False, "n_points": 0, "rows": [], "note": None}
    widths = sorted({len(r) for r in rows})
    notes: list[str] = []
    if widths != [5]:
        notes.append(f"noise 候选行值数集合 {widths} 非 5 值形态，如实登记不判性")
        warnings.append(notes[-1])
    if declared is not None and len(rows) != declared:
        msg = (f"noise 行数 {len(rows)} 与 [Number of Noise Frequencies]="
               f"{declared} 声明不一致")
        notes.append(msg)
        warnings.append(msg)
    parsed_rows: list[list[float]] = []
    for row in rows:
        try:
            parsed_rows.append([float(v) for v in row])
        except ValueError:
            parsed_rows.append([float("nan")] * len(row))
            warnings.append(
                f"noise 行含非数值 token，按 NaN 登记: {' '.join(row)[:60]}")
    return {
        "present": True,
        "n_points": len(rows),
        "rows": parsed_rows,
        "note": "；".join(notes) if notes else
                "按 5 值行形态登记（freq NFmin(dB) |Γopt| ∠Γopt(deg) Rn），"
                "Γopt 恒 MA 形态，未做语义解析",
    }


# ── 解析 ─────────────────────────────────────────────────────────────────────


def parse_touchstone(path: str | Path) -> dict[str, Any]:
    """Touchstone 文件 → 结构化输出（任务书契约形状）::

        {"schema": "touchstone/<N.0>",   # 自描述复合键（R-22 升位批补键）
         "format": {"version", "freq_unit", "param_type", "data_format",
                    "r_ref", "option_line_raw", "v2"(关键字块)},
         "n_ports": int|None,          # rank 三规则共识（冲突=None）
         "n_freqs": int, "freqs_hz": [float],
         "s_matrix": np.ndarray(nf,n,n) complex | None,
         "port_z": [float]（逐端口，r_ref 或 v2.0 [Reference]）,
         "noise": {"present", "n_points", "rows", "note"},
         "rank": {...三规则证据+resolution+disagreements},
         "stats": {"n_warnings": int},  # R-22 升位批补键（warnings 在）
         "warnings": [...]}

    rank 冲突 → n_ports=None、s_matrix=None（宁 UNKNOWN 不误判）；
    [Matrix Format] 非 Full → s_matrix=None + 警告（如实登记不解析）。
    """
    sniff = _sniff_core(path)
    warnings = list(sniff["warnings"])
    scan_rows: list[list[str]] = sniff["_rows"]
    scan_noise_rows: list[list[str]] = sniff["_noise_rows"]
    fmt = {
        "version": sniff["version"],
        "version_source": sniff["version_source"],
        "freq_unit": sniff["freq_unit"],
        "param_type": sniff["param_type"],
        "data_format": sniff["data_format"],
        "r_ref": sniff["r_ref"],
        "noise_flag": sniff["noise_flag"],
        "mixed_mode": sniff["mixed_mode"],
        "option_line_raw": sniff["option_line_raw"],
        "v2": sniff["v2"],
    }
    n_ports = sniff["rank"]["n_ports"]
    freq_mult = _FREQ_UNIT_MULT[fmt["freq_unit"]]
    freqs: list[float] = []
    mats: list[list[list[complex]]] | None = None
    noise: dict[str, Any] = {"present": False, "n_points": 0, "rows": [],
                             "note": None}

    # v2.0 矩阵格式守卫：仅 Full 解析，其余如实登记
    matrix_format = sniff["v2"]["matrix_format"]
    non_full = (sniff["version"] == "2.0" and matrix_format is not None
                and matrix_format != "full")

    if n_ports is not None and not non_full:
        legacy_2port = (
            sniff["version"] == "2.0" and n_ports == 2
            and sniff["v2"]["two_port_order"] == "rows_21_12")
        if sniff["v2"]["two_port_order"] is None and sniff["version"] == "2.0" \
                and n_ports == 2:
            warnings.append(
                "v2.0 2 端口文件缺 [Two-Port Data Order]——按规范默认 "
                "rows_12_21（行主序）解码；注意 skrf 同场景按 legacy 列序"
                "（rows_21_12）解，对拍需注意口径差")
        if sniff["version"] == "2.0":
            flat = [t for row in scan_rows for t in row]
            freqs, mats, tail_tokens = _parse_v2_data(
                flat, n_ports, fmt["data_format"], freq_mult,
                sniff["v2"]["declared_n_freqs"], legacy_2port, warnings)
            # noise 段：[Noise Data] 标记行 + 数据尾部余量 token（5 值/点
            # 形态）——统一走 _register_noise_rows（宽度/声明数/NaN 如实）
            noise_rows_raw: list[list[str]] = [list(r) for r in scan_noise_rows]
            if tail_tokens:
                if len(tail_tokens) % 5 == 0:
                    noise_rows_raw.extend(
                        tail_tokens[i:i + 5] for i in range(0, len(tail_tokens), 5))
                else:
                    noise_rows_raw.append(list(tail_tokens))
            if noise_rows_raw:
                noise = _register_noise_rows(
                    noise_rows_raw, sniff["v2"]["declared_n_noise_freqs"],
                    warnings)
                noise["note"] = (
                    "v2.0 [Noise Data] 标记段/数据尾部余量 token 按 noise 段"
                    "登记（5 值/点形态 freq NFmin(dB) |Γopt| ∠Γopt(deg) Rn）"
                    "，未做语义解析" + (
                        "；" + noise["note"] if noise["note"] else ""))
        else:
            matrix_rows, v1_noise_rows = _v1_split_noise_rows(scan_rows)
            fold_form = bool(
                n_ports is not None and n_ports >= 3
                and (sniff["rank"].get("rule_block") or {}).get("block") == 1)
            freqs, mats = _parse_v1_data(
                matrix_rows, n_ports, fmt["data_format"], freq_mult,
                fold_form=fold_form)
            noise = _register_noise_rows(
                v1_noise_rows, sniff["v2"]["declared_n_noise_freqs"], warnings)
    elif non_full:
        warnings.append(
            f"v2.0 [Matrix Format]={matrix_format} 非 Full——如实登记，"
            "矩阵不解析（任务书已知限制：关键字矩阵格式支持度）")

    matrices_out = None
    if mats is not None and n_ports is not None:
        matrices_out = np.array(mats, dtype=complex).reshape(
            len(freqs), n_ports, n_ports)

    # port_z：v2.0 [Reference] 逐端口优先，否则 r_ref 广播
    port_z: list[float] | None = None
    if n_ports is not None:
        ref_tokens = sniff["v2"]["reference_tokens"]
        refs: list[float] = []
        if ref_tokens:
            try:
                refs = [float(t) for t in ref_tokens]
            except ValueError:
                warnings.append(
                    f"v2.0 [Reference] token 非数字 {ref_tokens[:4]}，按 r_ref 广播")
                refs = []
        if refs:
            if len(refs) == n_ports:
                port_z = refs
            elif len(refs) == 1:
                port_z = [refs[0]] * n_ports
            else:
                warnings.append(
                    f"v2.0 [Reference] 数 {len(refs)} 与端口数 {n_ports} 不符，"
                    "按 r_ref 广播（如实登记）")
        if port_z is None:
            port_z = [float(fmt["r_ref"])] * n_ports

    return {
        # 自描述键统一口径（R-22 schema 升位批）：``"<域>/<N.0>"`` 复合键。
        "schema": f"touchstone/{PARSER_SCHEMA_VERSION}",
        "format": fmt,
        "n_ports": n_ports,
        "n_freqs": len(freqs),
        "freqs_hz": freqs,
        "s_matrix": matrices_out,
        "port_z": port_z,
        "noise": noise,
        "rank": sniff["rank"],
        "stats": {"n_warnings": len(warnings)},
        "warnings": warnings,
    }




def _float_chunks(tokens: list[str], width: int | None) -> list[list[float]]:
    """token 串 → float 分块（width=None 不分组原样转；失败按 NaN 如实）。"""
    out: list[list[float]] = []
    if width is None:
        try:
            return [[float(t) for t in tokens]]
        except ValueError:
            return [[float("nan")] * len(tokens)]
    for start in range(0, len(tokens), width):
        chunk = tokens[start:start + width]
        try:
            out.append([float(t) for t in chunk])
        except ValueError:
            out.append([float("nan")] * len(chunk))
    return out


# ── 频轴对齐（#287/#294 单源化） ─────────────────────────────────────────────


def align_freq_axis(
    a: list[float] | np.ndarray,
    b: list[float] | np.ndarray,
    rtol: float = 1e-9,
    allow_endpoint_extrap: bool = True,
) -> dict[str, Any]:
    """对拍前频轴对齐（#287 单源化；#294 同款语义）。

    - 同栅（长度相等且逐点 ``|Δf| ≤ rtol·max(|a|,|b|)``）→ 直接比对面，
      mode="same_grid"，indices=恒等；
    - 异栅 → 每点 argmin 真最近邻（**禁 searchsorted**——#294 越位一格把
      逐频 1e-16 dB 假差报成斜率假差），匹配判据同 rtol 容差（端点 ulp
      噪声 ~1e-7 Hz@1e9 Hz 即被此容差覆盖——端点 ulp 容差语义）；
    - 超出对方频段且差超容差的点：allow_endpoint_extrap=True 时仍保留
      （对齐到最近端点值，供下游微量外推——#287 口径）；False 时丢弃并
      如实进 unmatched_a 记录。

    返回 JSON 安全 dict::

        {"mode", "n_matched", "indices_b"（保留 a 点对应的 b 下标）,
         "a_aligned", "b_aligned"（对齐后的频率列表 Hz）,
         "unmatched_a": [{"f", "nearest_b", "delta_hz"}],
         "unmatched_b", "duplicate_matches", "rtol"}

    空输入 → TouchstoneParseError（对齐无意义，fail-loud）。
    """
    arr_a = np.asarray(a, dtype=float).ravel()
    arr_b = np.asarray(b, dtype=float).ravel()
    if arr_a.size == 0 or arr_b.size == 0:
        raise TouchstoneParseError("align_freq_axis 输入频轴为空（对齐无意义）")

    def _tol(x: float, y: float) -> float:
        return rtol * max(abs(x), abs(y))

    if arr_a.size == arr_b.size:
        tol_vec = rtol * np.maximum(np.abs(arr_a), np.abs(arr_b))
        same = bool(np.all(np.abs(arr_a - arr_b) <= tol_vec))
    else:
        same = False
    if same:
        return {
            "mode": "same_grid",
            "n_matched": int(arr_a.size),
            "indices_b": list(range(arr_a.size)),
            "a_aligned": [float(v) for v in arr_a],
            "b_aligned": [float(v) for v in arr_b],
            "unmatched_a": [],
            "unmatched_b": [],
            "duplicate_matches": [],
            "rtol": rtol,
        }

    indices: list[int] = []
    a_aligned: list[float] = []
    b_aligned: list[float] = []
    unmatched_a: list[dict[str, Any]] = []
    used_b: set[int] = set()
    dup: list[int] = []
    for f in arr_a:
        j = int(np.argmin(np.abs(arr_b - f)))
        delta = abs(float(arr_b[j]) - float(f))
        within = delta <= _tol(float(f), float(arr_b[j]))
        if within or allow_endpoint_extrap:
            # within=常规匹配/端点 ulp 容差内；否则=端点外推保留
            # （allow_endpoint_extrap=True 时对齐最近端点供下游微量外推）
            if j in used_b:
                dup.append(j)
            used_b.add(j)
            indices.append(j)
            a_aligned.append(float(f))
            b_aligned.append(float(arr_b[j]))
            if not within:
                unmatched_a.append({
                    "f": float(f), "nearest_b": float(arr_b[j]),
                    "delta_hz": delta, "kept_by": "endpoint_extrap",
                })
        else:
            unmatched_a.append({
                "f": float(f), "nearest_b": float(arr_b[j]),
                "delta_hz": delta, "kept_by": None,
            })
    unmatched_b = [float(arr_b[k]) for k in range(arr_b.size) if k not in used_b]
    return {
        "mode": "nearest",
        "n_matched": len(indices),
        "indices_b": indices,
        "a_aligned": a_aligned,
        "b_aligned": b_aligned,
        "unmatched_a": unmatched_a,
        "unmatched_b": unmatched_b,
        "duplicate_matches": dup,
        "rtol": rtol,
    }


# ── Σ模数形状判定（#309 单源化） ─────────────────────────────────────────────


def detect_mode_data_shape(
    path: str | Path, n_ports_declared: int | None,
) -> dict[str, Any]:
    """文件名 .sNp 的 N 与内容数据形状互证（#309 单源化）。

    ``n_ports_declared`` = 声明口径（HFSS 端口**边界**数）；Touchstone 导出
    的是**Σ模数**矩阵——多模波端口按边界数命名会把 4×4 模态数据写成
    .s2p（#309：skrf 按扩展名推断 rank 抛 IndexError）。判定：

    - 内容与文件名一致 → "consistent"；
    - 内容 > 文件名 → "data_exceeds_filename" + 建议 ``文件名应改 .s4p
      形态``（Σ模数口径）；
    - 内容 < 文件名 → "data_below_filename" + 建议改小（#248 场景：1 端口
      数据写成 .s2p）；
    - 内容 UNKNOWN → "unknown_data_shape"（宁 UNKNOWN 不误判）。
    """
    sniff = sniff_touchstone(path)
    rank = sniff["rank"]
    content_n = rank["n_ports"]
    filename_n = rank["rule_filename"]
    filename_trusted = rank["rule_filename_trusted"]
    result: dict[str, Any] = {
        "path": str(Path(path)),
        "filename_n": filename_n,
        "filename_trusted": filename_trusted,
        "content_n": content_n,
        "n_ports_declared": n_ports_declared,
        "verdict": None,
        "suggested_filename": None,
        "disagreements": list(rank["disagreements"]),
        "warnings": list(sniff["warnings"]),
    }
    if content_n is None:
        result["verdict"] = "unknown_data_shape"
        return result
    if not filename_trusted:
        result["verdict"] = "filename_untrusted"
    elif filename_n == content_n:
        result["verdict"] = "consistent"
    elif content_n > filename_n:
        result["verdict"] = "data_exceeds_filename"
        result["suggested_filename"] = f".s{content_n}p"
        result["warnings"].append(
            f"数据形状 {content_n}×{content_n} 超出文件名 .s{filename_n}p——"
            f"建议改名 .s{content_n}p（#309：Σ模数口径，多模波端口按边界数"
            "命名会让 skrf reshape 抛错）")
    else:
        result["verdict"] = "data_below_filename"
        result["suggested_filename"] = f".s{content_n}p"
        result["warnings"].append(
            f"数据形状 {content_n}×{content_n} 低于文件名 .s{filename_n}p——"
            f"建议改名 .s{content_n}p（#248：1 端口写成 .s2p 时 skrf reshape 抛错）")
    if n_ports_declared is not None and n_ports_declared != content_n:
        result["disagreements"].append(
            f"声明端口数 {n_ports_declared} 与内容数据形状 {content_n} 不符"
            "（多模波端口按边界数声明时属预期——Σ模数口径，#309）")
    return result


# ── 矩阵健康统计（无源性，如实统计不做硬门） ─────────────────────────────────


def matrix_health(s_matrix: np.ndarray | None, eps: float = 1e-3) -> dict[str, Any]:
    """逐频最大特征值模统计（无源性 ``|max eig| ≤ 1+ε`` 如实统计不做硬门）。

    s_matrix=None（rank 冲突/不支持矩阵格式）→ {"available": False, ...}
    如实；复矩阵逐频求 ``max|eig(S_f)|``——1 端口 1×1 退化形态照常计算
    （1×1 eig 合法）。
    """
    if s_matrix is None:
        return {
            "available": False,
            "eps": eps,
            "threshold": 1.0 + eps,
            "n_freqs": 0,
            "max_eig_max": None,
            "n_passive_freqs": None,
            "passive_ratio": None,
            "note": "s_matrix 未解析（rank 冲突/不支持矩阵格式），健康统计不可用",
        }
    arr = np.asarray(s_matrix, dtype=complex)
    if arr.ndim != 3 or arr.shape[0] == 0 or arr.shape[1] != arr.shape[2]:
        return {
            "available": False,
            "eps": eps,
            "threshold": 1.0 + eps,
            "n_freqs": 0,
            "max_eig_max": None,
            "n_passive_freqs": None,
            "passive_ratio": None,
            "note": f"s_matrix 形态 {tuple(arr.shape)} 非逐频方阵序列，"
                    "健康统计不可用",
        }
    max_eigs = np.array([
        float(np.max(np.abs(np.linalg.eigvals(arr[k])))) for k in range(arr.shape[0])
    ])
    threshold = 1.0 + eps
    passive = max_eigs <= threshold
    return {
        "available": True,
        "eps": eps,
        "threshold": threshold,
        "n_freqs": int(arr.shape[0]),
        "max_eig_max": float(np.max(max_eigs)),
        "n_passive_freqs": int(np.count_nonzero(passive)),
        "passive_ratio": float(np.count_nonzero(passive)) / float(arr.shape[0]),
        "note": "无源性如实统计（|max eig|≤1+ε），不做硬门——判据语义见任务书",
    }


# ── skrf 桥 ──────────────────────────────────────────────────────────────────


def to_skrf_network(parsed: dict[str, Any]):  # -> skrf.Network（惰性类型）
    """解析结果 → skrf.Network（frequency/s 复矩阵/z0；skrf 失败 ImportError 透传）。

    s_matrix 未解析（rank 冲突/不支持矩阵格式）→ ValueError fail-loud
    （宁拒不错，core/deembed Z 参数退化拒答同款语义）。
    """
    import skrf  # 惰性：仅桥接时需要（skrf 是仓内既有依赖）

    s = parsed.get("s_matrix")
    if s is None:
        raise ValueError(
            "s_matrix 未解析（rank UNKNOWN/冲突/不支持矩阵格式），无法构建"
            " skrf 网络——不猜（宁 UNKNOWN 不误判）")
    freqs = np.asarray(parsed["freqs_hz"], dtype=float)
    if freqs.size == 0:
        raise ValueError("freqs_hz 为空，无法构建 skrf 网络")
    port_z = parsed.get("port_z")
    if not port_z:
        z0: Any = 50.0
    elif len(set(port_z)) == 1:
        z0 = float(port_z[0])
    else:
        z0 = [float(v) for v in port_z]
    frequency = skrf.Frequency.from_f(freqs, unit="hz")
    return skrf.Network(
        frequency=frequency,
        s=np.asarray(s, dtype=complex),
        z0=z0,
    )
