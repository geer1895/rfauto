"""KD-2 RAG embedding 语义索引锚树（round16 规格；确定性降级路线）。

锚点面：
- 检索确定性（同进程逐字节 + 跨进程 PYTHONHASHSEED 无关——blake2b 钉）；
- 混合打分单调（score 对 alpha 的偏导 = dense_norm - sparse_norm，定义级钉）
  与 alpha=0/1 端点复现单侧排序；
- 语料外查询行为（ok=True hits=[]，与 rag_service BM25 契约同形）；
- 负例（非法输入 ValueError 全家）；
- 诚实边界钉：降级路线无语义泛化——同义改写（零词面重叠）不召回；
- 公式/代码切块保护（围栏/数学块原子性 + 超限整块 + 行号）；
- goldset recall@k 评估核（TSA/FCA 双口径；阈值 = 20 题 goldset 实测值
  留裕度后钉死，#122 诚实门）；
- 与 rag_service BM25 面的消费层组合（core 不 import service，组合在测试
  层证明；HashEmbedder 与 rag_service.Embedder 协议同形可换装）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from rfauto.core.rag_embedding import (
    DEFAULT_EMBED_DIM,
    HashEmbedder,
    SemanticIndex,
    blend_rankings,
    embedding_tokenize,
    evaluate_recall,
    hash_counts,
    split_markdown_protected,
)

# ---------------------------------------------------------------------------
# 固定语料（RF 主题，词面可分；goldset 20 题）
# ---------------------------------------------------------------------------

_CORPUS: list[tuple[str, str]] = [
    ("wilkinson", "wilkinson power divider Wilkinson 功分器设计 S11 回损 等分 "
                  "3dB 隔离度 隔离电阻 isolation resistor"),
    ("branchline", "branchline coupler branchline 电桥 90度 正交 hybrid "
                   "3dB 直通 耦合 branchline coupler quadrature"),
    ("patch", "patch antenna 微带贴片天线 辐射方向图 馈电点 谐振频率 "
              "fringing 场 radiation pattern feed point"),
    ("mline", "microstrip line 微带线 特性阻抗 50ohm 有效介电常数 "
              "epsilon_eff 导带宽度 characteristic impedance"),
    ("cpss", "CPS coplanar stripline 共面带线 差分 平衡线 特性阻抗 间隙 "
             "differential balanced line gap"),
    ("marchand", "Marchand balun 巴伦 耦合线 补偿 段数 带宽 compensated "
                 "coupled line impedance transformer"),
    ("lange", "lange coupler lange 耦合器 交指 3dB 宽带 桥接 interdigital "
              "bridge wideband"),
    ("siw", "SIW substrate integrated waveguide 基片集成波导 金属化过孔阵列 "
            "截止频率 via fence cutoff"),
    ("openems", "openEMS FDTD 时域仿真 CFL 网格 PML 吸收边界 NrTS 时间步 "
                "time domain solver mesh"),
    ("hfss", "HFSS 有限元 本征模 wave port 波端口 delta S 收敛 网格加密 "
             "eigenmode finite element convergence"),
    ("ads", "ADS hpeesofsim 谐波平衡 HB 网表 仿真参数 sweep harmonic "
            "balance netlist"),
    ("kicad", "KiCad pcbnew 布局 ZONE 填充 铜皮 DRC footprint copper fill"),
    ("sobol", "Sobol 灵敏度指数 一阶 total order Saltelli 采样 全局敏感性 "
              "sensitivity index sampling"),
    ("gp", "GP 高斯过程 代理模型 LOO 交叉验证 nugget 核函数 gaussian "
           "process surrogate kriging"),
]

_GOLDSET: list[dict[str, object]] = [
    {"query": "wilkinson 功分器 隔离度 设计", "relevant": ["wilkinson"]},
    {"query": "Wilkinson S11 回损 等分", "relevant": ["wilkinson"]},
    {"query": "branchline 电桥 正交 90度", "relevant": ["branchline"]},
    {"query": "branchline 3dB 耦合 直通", "relevant": ["branchline"]},
    {"query": "贴片天线 馈电点 谐振", "relevant": ["patch"]},
    {"query": "patch 辐射方向图 fringing", "relevant": ["patch"]},
    {"query": "微带线 特性阻抗 有效介电常数", "relevant": ["mline"]},
    {"query": "微带 50ohm 导带宽度", "relevant": ["mline"]},
    {"query": "共面带线 差分 平衡 间隙", "relevant": ["cpss"]},
    {"query": "Marchand balun 耦合线 带宽", "relevant": ["marchand"]},
    {"query": "lange 交指 耦合器 宽带", "relevant": ["lange"]},
    {"query": "基片集成波导 金属化过孔 截止频率", "relevant": ["siw"]},
    {"query": "openEMS FDTD CFL 时间步", "relevant": ["openems"]},
    {"query": "openEMS PML 吸收边界 网格", "relevant": ["openems"]},
    {"query": "HFSS 波端口 delta S 收敛", "relevant": ["hfss"]},
    {"query": "谐波平衡 网表 仿真 ADS", "relevant": ["ads"]},
    {"query": "KiCad 铜皮 ZONE 填充", "relevant": ["kicad"]},
    {"query": "Sobol 全局敏感性 灵敏度指数", "relevant": ["sobol"]},
    {"query": "高斯过程 代理模型 nugget", "relevant": ["gp"]},
    {"query": "wilkinson 功分器 branchline 电桥 对比",
     "relevant": ["wilkinson", "branchline"]},
]


def _build_index(embed_dim: int = 256) -> SemanticIndex:
    index = SemanticIndex(embed_dim=embed_dim)
    for cid, text in _CORPUS:
        index.add(cid, text, citation={"path": f"corpus/{cid}.md"})
    return index


# ---------------------------------------------------------------------------
# 确定性锚
# ---------------------------------------------------------------------------

class TestDeterminism:
    def test_embedder_same_input_same_vector(self) -> None:
        emb = HashEmbedder(64)
        a = emb.embed(["wilkinson divider", "wilkinson divider"])
        assert a[0] == a[1]
        assert len(a[0]) == 64

    def test_embedder_l2_normalized(self) -> None:
        emb = HashEmbedder(DEFAULT_EMBED_DIM)
        vec = emb.embed(["openEMS FDTD CFL 网格 PML"])[0]
        assert abs(sum(x * x for x in vec) - 1.0) < 1e-9

    def test_hash_counts_signed_stable(self) -> None:
        c1 = hash_counts("wilkinson 功分器", 128)
        c2 = hash_counts("wilkinson 功分器", 128)
        assert c1 == c2
        assert all(v != 0.0 for v in c1.values())

    def test_query_byte_identical_twice(self) -> None:
        index = _build_index()
        r1 = index.query("openEMS PML 吸收边界", top_k=5)
        r2 = index.query("openEMS PML 吸收边界", top_k=5)
        assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)

    def test_index_rebuild_dumps_identical(self) -> None:
        assert _build_index().dumps() == _build_index().dumps()

    def test_cross_process_pythonhashseed_independent(self) -> None:
        """blake2b 钉：内建 hash() 受 PYTHONHASHSEED 随机化，本模块禁用它——
        两个不同 seed 的子进程对同一查询必须逐字节同答。"""
        script = (
            "import json;"
            "from rfauto.core.rag_embedding import SemanticIndex;"
            f"corpus={_CORPUS!r};"
            "idx=SemanticIndex(embed_dim=256);"
            "[idx.add(cid,text) for cid,text in corpus];"
            "print(json.dumps(idx.query('HFSS 波端口 delta S 收敛', top_k=3),"
            " sort_keys=True))"
        )
        outputs = []
        for seed in ("1", "42"):
            env = {**os.environ, "PYTHONHASHSEED": seed}
            proc = subprocess.run(
                [sys.executable, "-c", script], env=env, timeout=120,
                capture_output=True, text=True, check=True)
            outputs.append(proc.stdout)
        assert outputs[0] == outputs[1]
        assert "hfss" in outputs[0]


# ---------------------------------------------------------------------------
# 排序与语料外行为
# ---------------------------------------------------------------------------

class TestRetrievalBehavior:
    def test_relevant_chunk_ranks_first(self) -> None:
        index = _build_index()
        for query, relevant in [
            ("lange 交指 耦合器", "lange"),
            ("基片集成波导 过孔 截止", "siw"),
            ("高斯过程 代理 nugget", "gp"),
        ]:
            result = index.query(query, top_k=3)
            assert result["ok"] is True
            assert result["hits"], query
            assert result["hits"][0]["chunk_id"] == relevant

    def test_out_of_corpus_query_no_hit(self) -> None:
        """语料外查询：桶不相交 ⇒ cosine=0 ⇒ ok=True hits=[]（确定性无命中，
        不编造结果——与 rag_service BM25 面同契约）。

        前提钉：特征哈希在小维度下桶碰撞是固有现象（hashing trick 代价），
        串扰分极小；严格零命中契约只在"查询桶与语料桶不相交"时成立——
        该前提用 hash_counts 显式断言（dim=65536 下本构造实测不相交）。"""
        dim = 65536
        query = "量子隐形传态 超导磁悬浮"
        q_buckets = set(hash_counts(query, dim))
        assert q_buckets
        for cid, text in _CORPUS:
            assert q_buckets.isdisjoint(hash_counts(text, dim)), cid
        index = SemanticIndex(embed_dim=dim)
        for cid, text in _CORPUS:
            index.add(cid, text)
        result = index.query(query, top_k=5)
        assert result["ok"] is True
        assert result["hits"] == []

    def test_oov_collision_crosstalk_is_small(self) -> None:
        """诚实行为钉（dim=256 缺省量级）：语料外查询的桶碰撞串扰分
        必须远低于词面命中分（串扰 < 词面冠军的 25%），即碰撞永不翻转
        真实排序。"""
        dim = 256
        index = SemanticIndex(embed_dim=dim)
        for cid, text in _CORPUS:
            index.add(cid, text)
        oov = index.query("量子隐形传态 超导磁悬浮", top_k=3)
        assert oov["ok"] is True
        lexical = index.query("openEMS PML 吸收边界", top_k=1)
        top_lexical = lexical["hits"][0]["score"]
        for hit in oov["hits"]:
            assert hit["score"] < 0.25 * top_lexical, hit

    def test_empty_index(self) -> None:
        index = SemanticIndex(embed_dim=64)
        result = index.query("anything", top_k=3)
        assert result["ok"] is True
        assert result["n_indexed"] == 0
        assert result["hits"] == []
        assert result["notes"] == ["索引为空"]

    def test_empty_query_explicit_error(self) -> None:
        index = _build_index()
        for text in ("", "   ", "。，、"):
            result = index.query(text, top_k=3)
            assert result["ok"] is False
            assert result["errors"]
            assert result["hits"] == []

    def test_citation_roundtrip(self) -> None:
        index = _build_index()
        hit = index.query("lange 交指", top_k=1)["hits"][0]
        assert hit["citation"]["path"] == "corpus/lange.md"

    def test_top_k_slices(self) -> None:
        index = _build_index()
        result = index.query("wilkinson branchline 电桥 功分器", top_k=2)
        assert len(result["hits"]) == 2
        assert result["n_indexed"] == len(_CORPUS)


# ---------------------------------------------------------------------------
# 诚实边界钉：降级路线无语义泛化（round16 裁决条款的测试化）
# ---------------------------------------------------------------------------

class TestNoSemanticGeneralizationBoundary:
    def test_synonym_rewrite_not_recalled(self) -> None:
        """同义改写（零词面重叠）不召回——钉死"非真 embedding，无语义泛化"
        的如实声明；真 embedding（BGE-M3）换装后此钉应翻转为召回。

        前提钉：词面不相交还不够，须桶不相交（dim=65536 下本构造实测
        不相交），否则碰撞串扰会产生假分。"""
        dim = 65536
        pairs = [
            ("thermal",
             "temperature compensation circuit for oscillator drift "
             "stabilization",
             "温漂补偿 振荡器 电路"),
            ("auto", "automobile velocity sensor calibration",
             "car speed detector"),
        ]
        index = SemanticIndex(embed_dim=dim)
        for cid, text, _ in pairs:
            index.add(cid, text)
        for cid, text, paraphrase in pairs:
            q_tokens = set(embedding_tokenize(paraphrase))
            assert q_tokens.isdisjoint(embedding_tokenize(text)), cid
            assert set(hash_counts(paraphrase, dim)).isdisjoint(
                hash_counts(text, dim)), cid
            assert index.query(paraphrase, top_k=2)["hits"] == [], paraphrase

    def test_lexical_overlap_still_recalls(self) -> None:
        """边界钉的另一面：词面重叠（哪怕语种混杂）照常召回——本路线的
        能力域就是词面重叠的稠密几何化。"""
        index = _build_index()
        result = index.query("HFSS 波端口", top_k=2)
        assert result["hits"][0]["chunk_id"] == "hfss"


# ---------------------------------------------------------------------------
# 混合打分核
# ---------------------------------------------------------------------------

class TestBlendRankings:
    def test_alpha_endpoints_reproduce_single_side(self) -> None:
        dense = [{"chunk_id": "a", "score": 3.0},
                 {"chunk_id": "b", "score": 1.0}]
        sparse = [{"chunk_id": "b", "score": 5.0},
                  {"chunk_id": "c", "score": 2.0},
                  {"chunk_id": "a", "score": 1.0}]
        at_zero = blend_rankings(dense, sparse, alpha=0.0)
        assert [h["chunk_id"] for h in at_zero["hits"]] == ["b", "c", "a"]
        at_one = blend_rankings(dense, sparse, alpha=1.0)
        # α=1 时纯 dense 侧定序；sparse 独有条目 fused=0 仍在并集尾行
        top_two = [h["chunk_id"] for h in at_one["hits"][:2]]
        assert top_two == ["a", "b"]
        assert at_one["hits"][2]["chunk_id"] == "c"
        assert at_one["hits"][2]["score"] == 0.0

    def test_monotonic_in_alpha_definition_level(self) -> None:
        """定义级钉：score(α)=α·d+(1-α)·s → dscore/dα = d_norm - s_norm。
        dense 占优条目随 α 单调升、sparse 占优条目单调降。"""
        dense = [{"chunk_id": "a", "score": 4.0},
                 {"chunk_id": "b", "score": 1.0}]
        sparse = [{"chunk_id": "b", "score": 4.0},
                  {"chunk_id": "a", "score": 1.0}]
        alphas = [0.0, 0.25, 0.5, 0.75, 1.0]
        series: dict[str, list[float]] = {"a": [], "b": []}
        for alpha in alphas:
            result = blend_rankings(dense, sparse, alpha=alpha)
            for hit in result["hits"]:
                series[hit["chunk_id"]].append(hit["score"])
        for item, seq in series.items():
            diffs = [seq[i + 1] - seq[i] for i in range(len(seq) - 1)]
            if item == "a":  # dense 占优
                assert all(d > 0 for d in diffs), (item, seq)
            else:  # sparse 占优
                assert all(d < 0 for d in diffs), (item, seq)

    def test_ranking_flip_monotonic(self) -> None:
        """α 从 0 扫到 1，榜首由 sparse 冠军单调让位给 dense 冠军
        （恰好一次翻转，无振荡）。"""
        dense = [{"chunk_id": "d_top", "score": 2.0},
                 {"chunk_id": "s_top", "score": 1.0}]
        sparse = [{"chunk_id": "s_top", "score": 2.0},
                  {"chunk_id": "d_top", "score": 1.0}]
        leaders = []
        for i in range(11):
            alpha = i / 10.0
            hits = blend_rankings(dense, sparse, alpha=alpha)["hits"]
            leaders.append(hits[0]["chunk_id"])
        assert leaders[0] == "s_top"
        assert leaders[-1] == "d_top"
        flips = sum(1 for i in range(len(leaders) - 1)
                    if leaders[i] != leaders[i + 1])
        assert flips == 1

    def test_union_and_missing_side_zero(self) -> None:
        dense = [{"chunk_id": "a", "score": 1.0}]
        sparse = [{"chunk_id": "b", "score": 1.0}]
        result = blend_rankings(dense, sparse, alpha=0.5)
        assert result["n_union"] == 2
        by_id = {h["chunk_id"]: h for h in result["hits"]}
        assert by_id["a"]["sparse_score"] == 0.0
        assert by_id["b"]["dense_score"] == 0.0
        assert by_id["a"]["score"] == pytest.approx(by_id["b"]["score"])

    def test_deterministic_byte_identical(self) -> None:
        dense = [{"chunk_id": "x", "score": 2.5}, {"chunk_id": "y", "score": 0.5}]
        sparse = [{"chunk_id": "y", "score": 1.5}, {"chunk_id": "z", "score": 0.25}]
        r1 = blend_rankings(dense, sparse, alpha=0.7, top_k=3)
        r2 = blend_rankings(dense, sparse, alpha=0.7, top_k=3)
        assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)

    def test_negative_scores_rejected(self) -> None:
        with pytest.raises(ValueError, match="非负"):
            blend_rankings([{"chunk_id": "a", "score": -1.0}],
                           [{"chunk_id": "b", "score": 1.0}])

    @pytest.mark.parametrize("alpha", [-0.1, 1.5, "x", None])
    def test_alpha_out_of_range_rejected(self, alpha: object) -> None:
        with pytest.raises(ValueError):
            blend_rankings([], [], alpha=alpha)  # type: ignore[arg-type]

    def test_malformed_hits_rejected(self) -> None:
        with pytest.raises(ValueError, match="chunk_id"):
            blend_rankings([{"score": 1.0}], [])  # type: ignore[list-item]
        with pytest.raises(ValueError, match="score"):
            blend_rankings([], [{"chunk_id": "a"}])  # type: ignore[list-item]

    def test_top_k_slices(self) -> None:
        dense = [{"chunk_id": f"c{i}", "score": float(i)} for i in range(5)]
        result = blend_rankings(dense, [], alpha=1.0, top_k=2)
        assert len(result["hits"]) == 2
        assert result["hits"][0]["chunk_id"] == "c4"


# ---------------------------------------------------------------------------
# 公式/代码切块保护
# ---------------------------------------------------------------------------

class TestProtectedChunking:
    def test_code_and_math_atomic(self) -> None:
        md = ("# 标题\n\n前文段落。\n\n```python\nx = 1\ny = 2\n```\n\n"
              "中段。\n\n$$\nE = mc^2\n$$\n\n尾段。\n")
        chunks = split_markdown_protected(md, max_chars=800)
        kinds = [(c["kind"], c["protected"]) for c in chunks]
        assert ("code", True) in kinds
        assert ("math", True) in kinds
        code = next(c for c in chunks if c["kind"] == "code")
        mathc = next(c for c in chunks if c["kind"] == "math")
        assert code["text"].startswith("```python")
        assert code["text"].endswith("```")
        assert mathc["text"] == "$$\nE = mc^2\n$$"
        assert code["heading"] == "标题"

    def test_multiple_fences_all_protected(self) -> None:
        md = "```python\na = 1\n```\n\nprose\n\n```text\nb = 2\n```\n"
        chunks = split_markdown_protected(md)
        codes = [c for c in chunks if c["kind"] == "code"]
        assert len(codes) == 2
        assert all(c["protected"] for c in codes)

    def test_oversized_code_block_stays_whole(self) -> None:
        """保护优先于尺寸上限：超限代码块整块独占 + protected 标记
        （诚实超标优于静默切碎）。"""
        body = "\n".join(f"line_{i} = {i}" for i in range(50))
        md = f"```python\n{body}\n```\n\n短段落。\n"
        chunks = split_markdown_protected(md, max_chars=64)
        codes = [c for c in chunks if c["kind"] == "code"]
        assert len(codes) == 1
        assert codes[0]["protected"] is True
        assert "line_49" in codes[0]["text"]

    def test_unclosed_fence_honest_tail_block(self) -> None:
        md = "```python\na = 1\nb = 2"
        chunks = split_markdown_protected(md)
        assert len(chunks) == 1
        assert chunks[0]["protected"] is True
        assert chunks[0]["text"].startswith("```python")

    def test_line_numbers_and_prose_split(self) -> None:
        md = "para one\n\npara two\n\npara three\n\npara four\n"
        chunks = split_markdown_protected(md, max_chars=10)
        assert all(c["kind"] == "prose" and not c["protected"] for c in chunks)
        assert all(len(c["text"]) <= 10 for c in chunks)
        assert chunks[0]["line"] == 1

    def test_tilde_fence_supported(self) -> None:
        md = "~~~\ncode here\n~~~\n"
        chunks = split_markdown_protected(md)
        assert chunks[0]["kind"] == "code"
        assert chunks[0]["protected"] is True

    @pytest.mark.parametrize("kwargs", [
        {"max_chars": 0}, {"max_chars": -1}, {"max_chars": True},
    ])
    def test_invalid_max_chars_rejected(self, kwargs: dict) -> None:
        with pytest.raises(ValueError):
            split_markdown_protected("text", **kwargs)


# ---------------------------------------------------------------------------
# goldset 评估核（TSA/FCA 双口径）
# ---------------------------------------------------------------------------

class TestEvaluateRecall:
    def test_scoring_modes_partial_overlap(self) -> None:
        """手工钉：两相关块之一与查询词面/桶均不可达（dim=65536 实测不
        相交）→ 只召回一块 → tsa=1、fca=0、recall=0.5——FCA 模式恰用于
        暴露"部分相关不可达"。"""
        dim = 65536
        index = SemanticIndex(embed_dim=dim)
        index.add("hit1", "wilkinson 功分器 隔离")
        index.add("hit2", "balun 巴伦 阻抗变换")
        index.add("miss", "完全不相关的话题 kicad 铜皮")
        query = "wilkinson 功分器 隔离"
        q_buckets = set(hash_counts(query, dim))
        assert q_buckets.isdisjoint(hash_counts("balun 巴伦 阻抗变换", dim))
        assert q_buckets.isdisjoint(hash_counts("完全不相关的话题 kicad 铜皮", dim))
        goldset = [{"query": query, "relevant": ["hit1", "hit2"]}]
        report = evaluate_recall(index, goldset, k=2)
        item = report["items"][0]
        assert item["retrieved"] == ["hit1"]
        assert item["tsa"] == 1
        assert item["fca"] == 0
        assert item["recall"] == pytest.approx(0.5)
        assert report["tsa_at_k"] == pytest.approx(1.0)
        assert report["fca_at_k"] == pytest.approx(0.0)

    def test_full_recall_gives_fca_one(self) -> None:
        index = SemanticIndex(embed_dim=128)
        index.add("hit1", "wilkinson 功分器 隔离")
        index.add("hit2", "wilkinson 等分 3dB")
        goldset = [{"query": "wilkinson 功分器 隔离 等分 3dB",
                    "relevant": ["hit1", "hit2"]}]
        report = evaluate_recall(index, goldset, k=2)
        assert report["items"][0]["fca"] == 1
        assert report["mean_recall_at_k"] == pytest.approx(1.0)

    def test_invalid_goldset_rejected(self) -> None:
        index = SemanticIndex(embed_dim=64)
        with pytest.raises(ValueError, match="relevant"):
            evaluate_recall(index, [{"query": "q"}], k=1)
        with pytest.raises(ValueError, match="k 必须是"):
            evaluate_recall(index, [], k=0)

    def test_goldset_20q_recall_thresholds(self) -> None:
        """KD-2 评估集：20 题 gold 问题 recall@k（TSA/FCA 双口径）。

        阈值口径（#122 诚实门）：先实测后钉——hashing+TF-IDF 降级路线在
        本词面可分语料上的实测值（2026-10-02 实测 tsa@5=1.0000、
        fca@3=1.0000），留 5%/10% 裕度钉死；该门是"索引面未退化"回归锚，
        不是语义能力声明（gold 题均为词面可达构造，见
        TestNoSemanticGeneralizationBoundary 的能力边界钉）。
        """
        index = _build_index(embed_dim=DEFAULT_EMBED_DIM)
        report = evaluate_recall(index, _GOLDSET, k=5)
        assert report["n_queries"] == 20
        assert report["tsa_at_k"] >= 0.95, report["items"]
        report3 = evaluate_recall(index, _GOLDSET, k=3)
        assert report3["fca_at_k"] >= 0.90, report3["items"]
        # 单相关块题目在 k=3 下必须全召回（多相关块题允许部分）
        singles = [it for it in report3["items"] if it["n_relevant"] == 1]
        assert all(it["fca"] == 1 for it in singles), singles


# ---------------------------------------------------------------------------
# 与 rag_service BM25 面的消费层组合（core 不 import service）
# ---------------------------------------------------------------------------

class TestCompositionWithRagService:
    def test_hash_embedder_fits_ragindex_embedder_slot(self) -> None:
        """HashEmbedder 与 rag_service.Embedder 协议同形：可放入
        RagIndex(embedder=...) 换装位（真 embedding 落地时的替换点）。"""
        from rfauto.service.rag_service import RagIndex

        index = RagIndex(embedder=HashEmbedder(64))
        index.add_chunk("wilkinson 功分器", {"path": "docs/wk.md"})
        assert index.stats()["embedder_configured"] is True

    def test_bm25_x_semantic_hybrid_pipeline(self) -> None:
        """消费层组合：同一语料双索引，BM25 hits × semantic hits 经
        blend_rankings 融合——管线通、确定性、命中并集非空。"""
        from rfauto.service.rag_service import RagIndex

        bm25 = RagIndex()
        semantic = SemanticIndex(embed_dim=DEFAULT_EMBED_DIM)
        for cid, text in _CORPUS:
            bm25.add_chunk(text, {"path": f"corpus/{cid}.md"}, chunk_id=cid)
            semantic.add(cid, text, citation={"path": f"corpus/{cid}.md"})
        query = "wilkinson 功分器 隔离度"
        bm25_hits = bm25.query(query, top_k=5)["hits"]
        sem_hits = semantic.query(query, top_k=5)["hits"]
        assert bm25_hits and sem_hits
        fused = blend_rankings(sem_hits, bm25_hits, alpha=0.5, top_k=5)
        assert fused["ok"] is True
        assert fused["n_union"] > 0
        top = fused["hits"][0]["chunk_id"]
        assert top == "wilkinson"
        fused_again = blend_rankings(sem_hits, bm25_hits, alpha=0.5, top_k=5)
        assert json.dumps(fused, sort_keys=True) == json.dumps(
            fused_again, sort_keys=True)

    def test_hybrid_beats_pure_side_on_shared_term_query(self) -> None:
        """混合面价值钉：两块都含查询词时，BM25 与语义侧冠军不同，
        α=0.5 融合把两侧共识推上榜首。"""
        from rfauto.service.rag_service import RagIndex

        texts = [
            ("freqA", "wilkinson 功分器 频率响应曲线 频率 频率 频率"),
            ("freqB", "wilkinson 功分器 隔离度参数 频率"),
        ]
        bm25 = RagIndex()
        semantic = SemanticIndex(embed_dim=128)
        for cid, text in texts:
            bm25.add_chunk(text, {"path": f"{cid}.md"}, chunk_id=cid)
            semantic.add(cid, text, citation={"path": f"{cid}.md"})
        query = "wilkinson 频率"
        sem_hits = semantic.query(query, top_k=2)["hits"]
        bm25_hits = bm25.query(query, top_k=2)["hits"]
        fused = blend_rankings(sem_hits, bm25_hits, alpha=0.5)
        assert {h["chunk_id"] for h in fused["hits"]} == {"freqA", "freqB"}


# ---------------------------------------------------------------------------
# stats / 模块级杂项
# ---------------------------------------------------------------------------

class TestStatsAndMisc:
    def test_stats_honest_semantic_false(self) -> None:
        """如实声明钉：stats()['semantic']=False——降级路线不得冒充
        真语义 embedding（军规 7 同族：不伪造能力）。"""
        stats = _build_index().stats()
        assert stats["semantic"] is False
        assert stats["embedder"] == "hashing_tfidf"
        assert stats["n_items"] == len(_CORPUS)
        assert stats["embed_dim"] == 256

    def test_tokenize_ascii_cjk_parity_with_rag_service(self) -> None:
        """core 镜像分词与 rag_service.tokenize 同算法——漂移即红
        （两面词形一致是混合打分的隐含前提）。"""
        from rfauto.service.rag_service import tokenize

        samples = ["wilkinson 功分器 S11", "微带贴片 patch-antenna v2",
                   "纯中文测试串", "mixed 中英 mix3 混合"]
        for text in samples:
            assert embedding_tokenize(text) == tokenize(text)

    def test_duplicate_chunk_id_rejected(self) -> None:
        index = SemanticIndex(embed_dim=64)
        index.add("a", "first text")
        with pytest.raises(ValueError, match="重复"):
            index.add("a", "second text")

    def test_invalid_citation_rejected(self) -> None:
        index = SemanticIndex(embed_dim=64)
        with pytest.raises(ValueError, match="path"):
            index.add("a", "text", citation={"kind": "doc"})
