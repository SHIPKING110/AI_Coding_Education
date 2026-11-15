# ADR-0023：家长客服检索维持 Hybrid（Dense vs Hybrid A/B 结论）

- 状态：已采纳
- 日期：2026-11-12
- 关联：ADR-0022、CONTEXT.md、frontend/src/docs/rag-eval-spec.md

## 背景（Context）

ADR-0022 将评测口径对齐生产家长索引（`parent_knowledge__5e052e93b24a`，`parent_mode=True`）后，需要在同集合、同配置下回答：生产默认检索模式应保持 Hybrid（向量 + 关键词 + RRF），还是切回纯 Dense。判定规则预先约定：Dense 需在主指标 hit@3 上赢 ≥2pp 才切换，否则维持 Hybrid。

## 决策（Decision）

**维持 Hybrid 为生产默认模式。** A/B 实测（行舟-家长客服回归集 51 条，parent_mode=True，top_k=5，rerank=on，仅检索、不调 LLM）：

| 指标（rerank on） | Hybrid | Dense | 差值 |
|---|---|---|---|
| hit@1 | 0.7073 | 0.6341 | −7.3pp |
| hit@3 | **0.9268** | **0.8049** | **−12.2pp** |
| recall@5 | 0.9146 | 0.8049 | −11.0pp |
| MRR | 0.8049 | 0.7154 | −9.0pp |
| nDCG@5 | 0.8269 | 0.7374 | −9.0pp |
| 冻结集 hit@3（20 条） | 1.0000 | 0.8500 | −15.0pp |
| 关键用例 hit@3（14 条） | 1.0000 | 0.8571 | −14.3pp |

Dense 在全部主/次指标与冻结/关键切片上均落后，且冻结集单条回退即触发闸门 fail；裁定维持 Hybrid，不做切换。

## 后果（Consequences）

- 生产 `hybrid_enabled=true` 保持不变，无需配置变更。
- Dense 保留为评测可选模式，用于排查「向量本身」问题（召回骤降时对照基线）。
- 注意：Dense 模式下仍有少量用例回落到 hybrid 模式（多意图 auto 拆分路径，51 条中 1-7 条），指标按实际 `retrieval_mode` 分布记录，不影响结论方向。
- 后续任何检索链路改动（分块、重排、标题加成）都应以本次 Hybrid 基线（运行 f775fd92 / 6eb5971c）为回退对比基准。
