# ADR-0010：本地 Qwen3-Embedding-0.6B + Chroma 持久化作为 RAG 底座

日期：2026-09-21
状态：已接受

## 背景

Agent 对话要支持 RAG（可开关、可引用）。embedding 指定用本地 `Qwen3-Embedding-0.6B`
（已存在于 `backend/models/Qwen3-Embedding-0.6B/`，sentence-transformers 布局，含 `1_Pooling/`）。
当前环境**未安装** `torch / transformers / sentence-transformers`；`chromadb` 已装。

## 决策

- **Embedding 运行方式**：安装 `sentence-transformers`，CPU 加载 `backend/models/Qwen3-Embedding-0.6B`，
  完全本地推理（0.6B，CPU 足够快）。
- **向量库**：Chroma **本地持久化**（`PersistentClient`，目录 `backend/data/chroma`），零运维。
- **切块**：用模型自带 tokenizer 按 **token** 切，窗口 512、重叠 100。
- **元数据**：`owner_id / visibility(private|plaza) / doc_id / kb_scope / source / page`，单一 collection + 过滤。

## 否决的备选

- 走 API embedding：与「本地模型」要求不符，且引入外部依赖与费用，否决。
- Chroma server：单机演示无需独立服务，运维成本高，否决。
- 按字符切块：中文按字符与语义边界不齐，改用 tokenizer 切分，否决。

## 后果

- `pyproject.toml` 的 `ai` extra 增加 `sentence-transformers`（连带 torch，约 2.5GB+，需用户联网安装）。
- 新增 `services/embedding.py`（本地模型加载 + 切块）与 `services/vector_store.py`（Chroma 封装）。
- 用户贴出的 `config.json` 架构名为 `Qwen3ForCausalLM`（生成式），但目录含 `1_Pooling/modules.json`，
  按 sentence-transformers 加载；若加载失败以实际 `modules.json` 为准。
