# ADR-0022：家长客服评测验收协议（检索口径 / 冻结集 / Kappa / 发布证据）

- 状态：已采纳
- 日期：2026-11-12
- 关联：ADR-0010、ADR-0021、CONTEXT.md、scripts/deploy_gate.py、scripts/sync_eval_case_meta.py

## 背景（Context）

1. **评测口径与生产不一致**：评测运行器调用 `rag.retrieve()` 时未传 `parent_mode`，家长客服评测实际打在系统/教师集合（`knowledge__*`，575 分片）上；生产家长链路走 `parent_mode=True` 的独立家长索引（`parent_knowledge__*`，368 分片，Parent Embedding）。历史数字（hit@3≈0.927）测的不是家长生产索引。
2. **库内标注失真**：线上「家长测评集」51 条用例的 `split` 全为 regression、`business_criticality` 全为 normal、10 条负例被导成 unlabeled（仓库 JSONL 实际为 11 冻结 / 14 关键 / 10 不可答）。冻结/关键切片为空 → 闸门 skip → `make release` 必然被拦。
3. **闸门证据漏洞**：Kappa 只在人工样本 ≥10 对时检查（不复核=不检查）、无依据率只在 answer_eval=on 时存在、首次带切片运行没有 previous 时冻结回退对比形同虚设——几乎没有质量证据的运行也能 pass。
4. **闸门敏感性**：2pp 容忍 vs 11 条冻结集 → 单条翻转 9.1pp，关键 14 条 → 7.1pp，任何单条翻转都会 fail。
5. **发版脚本缺陷**：`make release` 用镜像内系统 `python`（无 sqlalchemy），闸门步骤实际不可用；`python` 必须指向 `/srv/app/.venv/bin/python`。

## 决策（Decision）

### 1. 检索口径（parent_mode）

- `RagEvalRun` 增加 `parent_mode`（默认 False）；评测运行表单提供三态：跟随评测集 / 强制家长索引 / 强制系统集合。
- 未显式指定时按评测集 `domain` 推导（`parent_service` → 家长索引），由 `rag_evaluation.effective_parent_mode()` 统一实现。
- 运行快照记录 `parent_mode` 与实际集合名，运行表「模式 / 口径」列可见。
- 家长客服验收集 domain 修正为 `parent_service`，并改名「行舟-家长客服回归集」。
- **口径修复前的历史基线作废**：数字不可跨版本对比，重建基线。

### 2. 冻结集构成与变更纪律

- 家长客服集冻结集 = 全部 14 条 `business_criticality=critical` + 6 条高频稳定可答用例（原冻结 4 条非关键 + 增补「孩子几岁可以开始学编程」「一节课多长时间」）= **20 条**；调参只用剩余 31 条回归用例。
- 冻结集一经基线**不再修改**；调整冻结用例 = 重建基线。
- 20 条时单条翻转 5pp，仍高于 2pp 容忍线：闸门对单条回退敏感是刻意选择（保守拦截），不引入「翻转 ≥2 条才 fail」的计数规则。

### 3. 人工复核与 Kappa 抽样协议

- 校准维度固定 `correctness`（与闸门实现一致）；`completeness ≤ 3` 清单只用于辅助挑低分层。
- 抽样：按裁判 `correctness` 分层随机 12 条——低（≤2）/ 中（3）/ 高（≥4）各 4 条，负例 ≥ 2 条；单评审（运营负责人本人），0-5 整数分 + 理由。
- 在基线运行上完成复核；换裁判模型必须重新复核。发行候选运行在「同裁判 + 同生成模型 + 同评测集哈希」时自动继承基线的 Kappa（`calibration.inherited_from_run` 可追溯），避免对同配置重复人工打分。目标 Kappa ≥ 0.6（二次加权）。

### 4. 发布证据要求（堵闸门漏洞）

- `scripts/deploy_gate.py` 新增 `--require-answer` / `--require-calibration` / `--require-baseline` 三个硬开关，实现为纯函数 `check_release_evidence()`：
  - `--require-answer`：发行运行必须 `answer_eval=on`（`answer.cases > 0`）；
  - `--require-calibration`：人工 ≥10 对且 Kappa 有定义并 ≥0.6；
  - `--require-baseline`：同集完成运行 ≥2 条（存在可对比基线）。
- `make release` 固定携带三个开关；`python` 改用 `/srv/app/.venv/bin/python`（修复原脚本依赖缺失）。
- 标准发布顺序：基线运行（hybrid + rerank on + answer_eval on，家长口径）→ 人工复核 Kappa → 发行候选运行（同配置）→ `GATE_SET_NAME="行舟-家长客服回归集" make release`。
- 应急豁免仅限不带 GATE_SET_NAME（打印警告）；严格证据模式下闸门 skip 不可用 `--allow-missing` 绕过。

### 5. 数据修复工具

- 新增 `scripts/sync_eval_case_meta.py`：以仓库 JSONL 为唯一事实源，按 query 原地更新 `split / business_criticality / answerability / query_type / difficulty / gt_answer / gt_keywords / notes`，默认 dry-run，`--apply` 写库并记审计 `eval.set.meta_sync`，支持 `--rename` / `--domain`。
- 仓库数据集：`zhouxing_parent_eval.jsonl` 冻结集扩至 20 条（14 关键 + 6 稳定），与库内保持同步。

## 后果（Consequences）

- 正向：家长客服评测与生产链路同口径；冻结/关键切片非空，闸门真正生效；发版具备可验证的质量证据门槛；库内标注与仓库单一事实源对齐。
- 代价：基线前的所有家长集运行不可比，需要重跑基线与 A/B（检索侧不耗 LLM，成本低）；冻结集加固后调参样本从 40 条降到 31 条；`make release` 在人工复核完成前会持续阻断（按设计）。
- 边界：教师集（53 条）不在本次协议范围内，下一轮单独处理冻结策略；混合检索是否保持生产默认由 dense/hybrid A/B 结果决定——已执行，结论见 ADR-0023（维持 Hybrid，dense hit@3 落后 12.2pp）。
