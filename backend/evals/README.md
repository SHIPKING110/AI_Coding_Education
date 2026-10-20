# Agent 工作台评估套件

对 **RAG 检索/答案质量** 与 **Agent 工具选择/任务完成** 做可复现的定量评估。目标是让「改了 Prompt/检索策略/模型」这类改动**有数据可依**，而不是凭感觉。

## 目录

```
evals/
├── metrics.py               # 纯函数指标（可单测，无外部依赖）
├── run_rag_eval.py          # RAG 检索评估（对真实知识库跑，含重排 A/B）
├── run_agent_eval.py        # Agent 工具选择评估
└── datasets/
    ├── rag_seed.jsonl       # RAG 查询种子集（relevant 用文档标题标注）
    └── agent_seed.jsonl     # Agent 任务种子集（expect/forbid 工具）
```

## 快速开始（容器内）

```bash
# 1) 指标单测（无需数据库）
python -m pytest tests/test_eval_metrics.py -q

# 2) RAG 检索评估（先把数据集里的文档标题对应的文件上传入库并「启用」）
python -m evals.run_rag_eval --owner <你的用户名> --dataset evals/datasets/rag_seed.jsonl --top-k 5

# 3) Agent 工具选择评估
python -m evals.run_agent_eval --owner <你的用户名> --dataset evals/datasets/agent_seed.jsonl
```

## 数据集格式（我们逐步共建）

### RAG（`rag_seed.jsonl`）
每行一条 JSON：
```json
{"query": "用户会怎么问", "relevant": ["应命中的文档标题1", "标题2"], "notes": "为什么这样标注"}
```
- `relevant` 用**文档标题**（与检索命中 `hit['title']` 对齐），无需关心内部 doc_id。
- 建议覆盖三类：**事实召回**（问细节）、**多片段召回**（答案散落多处）、**反例**（应检索不到，`relevant: []`）。

### Agent（`agent_seed.jsonl`）
每行一条 JSON：
```json
{"task": "用户会怎么说", "expect_tools": ["应调用的工具"], "forbid_tools": ["不该调用的工具"], "notes": "..."}
```
- 工具名见 `app/services/agent_tools.py`（如 `my_schedule_overview`、`find_students`、`student_progress`）。
- 覆盖：**单工具**、**多工具组合**、**闲聊不调工具**（`expect_tools: []` + `forbid_tools`）。

## 指标口径

| 指标 | 含义 |
|------|------|
| hit@k | 前 k 条是否命中至少 1 个相关文档 |
| recall@k | 前 k 条覆盖的相关文档比例 |
| precision@k | 前 k 条里相关占比 |
| MRR | 首个相关命中的排名倒数 |
| nDCG@k | 归一化折损累计增益（考虑相关项排位） |
| 重排增益 | rerank=on 相对 off 的各项 delta（回答「重排有没有用」） |
| 工具 P/R | 工具调用精确率/召回率；漏调/误调列表 |

## 答案质量（LLM 裁判，第二步）

检索指标只衡量「有没有捞到对的内容」。**答案质量**（faithfulness 忠实度、answer relevance 相关性）用裁判模型打分：给定 `问题 + 检索片段 + 回答`，让裁判输出维度分。将在 `run_rag_eval.py` 增加 `--judge` 选项，复用已配置的对话模型。

## 共建流程（一步一步来）

1. **定范围**：先各挑 10~20 条**高质量**种子（宁少勿滥），跑通指标；
2. **对齐标注**：逐条人工确认 `relevant` / `expect_tools`，模糊的标注丢弃或写清 `notes`；
3. **锁定基线**：记录当前版本各项指标，作为后续改动的对照；
4. **迭代扩样**：每次真实使用中发现的「错例」补一条进数据集（难例最有价值）；
5. **回归**：改动后重跑，指标不降才合入。

> 原则：**质量 > 数量**。50 条精标胜过 500 条粗标；每条标注都要能解释「为什么相关/为什么该调这个工具」。

## 与生产的衔接

- 检索链自带诊断（`retrieval_summary`：向量召回 N 条 → 重排精排），评估报告逐条打印，便于定位是「召回没捞到」还是「重排排错」。
- 指标脚本只读，不改数据；可安全对生产库运行。
