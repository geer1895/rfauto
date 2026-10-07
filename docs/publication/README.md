# docs/publication — 公开出版与引用面

本目录收口"对外出版"类产物（公开面模板不算内部账本）。任何文件在进入
公开仓/外发前必须过发布审查三问（逐文件归属、敏感信息扫描、干净环境可用
性实测）——扫描器 clean 不豁免人工三问。

## 内容

| 文件/目录 | 用途 | 消费方 |
|-----------|------|--------|
| `zenodo.metadata.json` | Zenodo deposit 元数据（**由 `CITATION.cff` 经服务层导出器生成**，公开仓 release 面把它放仓根 `.zenodo.json` 即被 Zenodo release 工作流拾取） | release 自动归档 |
| `joss/paper.md` | JOSS 投稿骨架（JOSS 规格式：front matter+Summary+Statement of need） | 学术路径 |
| `joss/paper.bib` | 参考文献桩（提交前逐条对出版社记录核实，禁止凭记忆引） | 学术路径 |
| `joss/figures.md` | 图目清单（每图：内容/生成来源/可复现命令位/状态） | 学术路径 |
| `ROADMAP.md` | 公开路线图+Good First Issues | 社区基建（PR-12） |

## DOI 闭环用法（零上传铁律）

元数据导出与校验走服务层（`src/rfauto/service/zenodo_service.py`）：

```bash
# 导出（只写本地文件，永不联网）：
python -c "from rfauto.service.zenodo_service import export_zenodo_metadata; \
export_zenodo_metadata('CITATION.cff', out_path='.zenodo.json')"

# 校验（CITATION.cff 必填字段 + 与 pyproject 版本同步）：
python -c "from rfauto.service.zenodo_service import validate_citation_metadata; \
print(validate_citation_metadata())"
```

规则：

1. **本面永不真实上传**——Zenodo 归档只发生在公开仓 release 流程里由用户
   显式执行；概念 DOI 由 Zenodo 首次发布后分配，任何文件**不得手工编造
   DOI 号**（`zenodo.metadata.json` 的 DOI 位留空就是留空）。
2. `zenodo.metadata.json` 是**导出产物**：公开仓 `CITATION.cff` 变更后必须
   重导出再入库（单源= CITATION.cff，本文件不许手改版本号/标题）。
3. `repository-code` 未填只记 warning 不判失败（不编造 URL）；首次公开
   归档前补齐。

## 学术路径（JOSS）

- 顺序：先 arXiv software paper（可引用预印本），后 JOSS 类期刊
  （要求足够长的公开仓历史）。
- 作者/单位/日期在 `paper.md` 的 `[[...]]` 占位处提交前补填——本仓**不预填**
  真实姓名。
- 图遵循 `joss/figures.md` 的四条铁律：可复现、公开安全、诚实、可访问。
