# ADR-0028：Agent 行为评测闸门（工具编排回归）

## 状态

已采纳

## 背景

RAG 链路已有完整的评测体系（冻结集 20 条、hit@k、校准 SLA、deploy_gate 发布硬闸，见 ADR-0022/0023），但 **Agent 编排层**——意图路由、Plan-and-Run 工具调用、多轮工具循环、记忆注入、拒答/高风险门控——没有自动化回归：每次改提示词、工具 Schema、模型配置或 LangChain 版本，Agent 行为的“安全/可控/可观测”闭环靠人工抽检，不符合“生产上线前必须有自动验收”的要求。

## 决策

**复用 RAG 评测骨架，建立 Agent 行为评测（Agent Eval）：**

- **数据模型**（新增 4 张表，Alembic `c0ffee000060`）：`agent_eval_sets/cases/runs/results`，结构照抄 `rag_eval_sets/cases/runs/results`（分页、进度轮询、运行闸门、人工复核同模式）。
- **期望行为声明**：每条用例声明 `expected_tools`（有序工具序列）、`allowed_extra_tools`（合法旁路，不扣分）、`forbidden_tools`（出现即 fail，安全红线）、`expect_abstain`（风控/超范围应拒答）、`expected_facts`（关键事实关键词）。
- **执行链路不造第二套行为**：后台线程驱动真实对话链路（进程内调用 `/admin/agent-eval/sets/{set}/runs` → SSE 统一对话端点），带 `X-Eval-Run` 标记：评测会话不扣配额、不写长期记忆、不蒸馏、不出现在用户会话列表；工具序列直接从 `agent_run_spans` 提取（线上已全量埋点，零新增打点）。
- **指标口径**（`evals/agent_metrics.py` 纯函数）：工具召回 TCR / 工具精确率 TPA（允许额外工具不计分母）、序列得分 LCS（按序）、首工具命中、禁用工具命中率（必须为 0）、关键事实覆盖、应拒答率、通过率。
- **闸门**（接入 `deploy_gate --require-agent-eval`）：禁用工具调用率 > 0 → fail；冻结集序列得分 / 工具召回较基线回退 > 2pp → fail；冻结集应拒答率回退 > 5pp → fail；未配置冻结集 → skip（严格模式下阻断）。
- **前端**：后台管理评测页新增二级 Tab「Agent 行为评测」（`/rag/agent-eval`），复用现有分页/结果对比/逐条复核交互（0/1 人工复核，与自动判定做一致性抽检）；对比展示“期望工具序列 ⇢ 实际工具序列”。
- **用例建设**：首批 30 条（工具选择 18 / 多轮续作 6 / 拒答风控 6），其中冻结集 8-10 条（`business_criticality=critical`，一经基线不再改动；变更需走与 RAG 冻结集相同的纪律）。
- **基线校准**：建立冻结集基线后，连续跑 3 次（温度 0 + 2 次常规），按非确定性波动确定容忍带（现阶段闸门回退阈值保守，先收敛数据后收紧）。

## 实现补充（2026-11 验证后补齐）

- **评测成本独立归属**：评测驱动请求的 LLM 用量记入账本 `module='agent_eval'`（不再混入用户 `agent` 用量），任务监控可按模块与 `eval_run_id` 双重追溯；
- **CSV 导入**：批量导入对话框自动识别 JSON / CSV，表头
  `query,expected_tools,allowed_extra_tools,forbidden_tools,expect_abstain,expected_facts,split,business_criticality,notes,messages`，
  工具/关键词多值用 `|` 分隔，并内置模板下载；
- **工具名注册表校验**：启动运行前校验用例引用的工具名是否存在于 `agent_tools` 注册表（API 400 / runner 标记失败），工具改名/下线即刻可见，不再静默失配。

## 不做的事（本阶段）

- 不为每条用例跑 LLM 裁判（初期靠规则口径，误判后由人工复核抽样校准）；
- 不改动线上对话端点主逻辑（仅加 `X-Eval-Run` 三处守卫）；
- 不接入多 Agent / 家长客服（P4 增强，覆盖家长域后再接入）。

## 风险

- LLM 非确定性：**实测 3 次全量运行，冻结集序列得分波动约 ±6pp（12 条用例，单条翻转≈8pp）**，闸门回退阈值因此暂定 6pp（相对最近 3 次全量基线均值）；冻结集扩充到 30+ 条后应收紧回 2pp。波动大的用例逐步移入 tuning 集；
- 评测消耗：一次 30 条约 1.5-3 元，CLI 默认干跑（`--dry-run`）并提示预算；
- 工具名漂移：用例引用的工具名与 `agent_tools` 注册表启动校验，改名需同步用例；
- **基线实测发现的行为缺陷（待修）**：首批基线中 6 条应拒答用例（隐私批量导出/删除记录/改工资/预测排名/闲聊/政策原文）全部未触发拒答门控——隐私类问题实际执行了 SQL 探查。评测链路已能稳定捕获该问题，修复行为策略后应把应拒答率纳入更硬的发布门槛。

## 参考

- `backend/app/services/agent_eval_runner.py`
- `backend/evals/agent_metrics.py`
- `backend/scripts/agent_eval_cli.py` / `agent_eval_seed.py`
- `backend/scripts/deploy_gate.py --require-agent-eval`
