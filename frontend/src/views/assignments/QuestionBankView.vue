<template>
  <div class="qb-view">
    <PageHead title="题库" eyebrow="QUESTION BANK" sub="真题文档导入 → 人工审核 → 发布到练习与模拟考试">
      <template #actions>
        <button v-if="canUpload" class="btn primary" @click="openUpload">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 16V4m0 0 4 4m-4-4-4 4M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" /></svg>
          上传题库文档
        </button>
      </template>
    </PageHead>

    <AssignmentsTabs active="bank" />

    <div v-if="canManage" class="stats-row">
      <div class="stat-card">
        <span class="stat-label">套卷</span>
        <strong>{{ stats.sets }}</strong>
      </div>
      <div class="stat-card">
        <span class="stat-label">题目</span>
        <strong>{{ stats.questions }}</strong>
      </div>
      <div class="stat-card warn">
        <span class="stat-label">待审核</span>
        <strong>{{ stats.pending_review }}</strong>
      </div>
      <div class="stat-tip">解析结果只进入草稿，全部题目审核通过后才能发布到学生端</div>
    </div>

    <div class="qb-workspace">
      <aside class="set-pane">
        <div class="filter-bar">
          <select v-model="filter.institution" class="fld" @change="loadSets">
            <option value="">全部机构</option>
            <option v-for="v in institutions" :key="v" :value="v">{{ v }}</option>
          </select>
          <select v-model="filter.subject" class="fld" @change="loadSets">
            <option value="">全部科目</option>
            <option v-for="v in subjects" :key="v" :value="v">{{ v }}</option>
          </select>
          <select v-model="filter.level" class="fld" @change="loadSets">
            <option value="">全部等级</option>
            <option v-for="v in levels" :key="v" :value="v">{{ v }}</option>
          </select>
          <select v-model="filter.month" class="fld" @change="loadSets">
            <option value="">全部年月</option>
            <option v-for="v in months" :key="v" :value="v">{{ v }}</option>
          </select>
          <select v-model="filter.status" class="fld" @change="loadSets">
            <option value="">全部状态</option>
            <option value="draft">待审核</option>
            <option value="published">已发布</option>
            <option value="archived">已归档</option>
          </select>
        </div>

        <div v-if="loading" class="pane-empty">加载中…</div>
        <div v-else-if="loadError" class="pane-empty">{{ loadError }}</div>
        <div v-else-if="sets.length === 0" class="pane-empty">
          暂无题库套卷{{ canManage ? '，点击右上角上传 DOCX' : '' }}
        </div>
        <div v-else class="set-list">
          <button
            v-for="s in sets"
            :key="s.id"
            class="set-card"
            :class="{ active: s.id === selectedId }"
            @click="selectSet(s.id)"
          >
            <div class="set-top">
              <span class="set-name" :title="s.name">{{ s.name }}</span>
              <span class="stamp" :class="s.status">{{ statusLabel[s.status] }}</span>
            </div>
            <div class="set-meta">
              <span v-if="s.institution">{{ s.institution }}</span>
              <span v-if="s.subject">{{ s.subject }}</span>
              <span v-if="s.level">{{ s.level }}</span>
              <span v-if="s.exam_year">{{ s.exam_year }}</span>
            </div>
            <div class="set-foot">
              <span>{{ s.question_count ?? 0 }} 题</span>
              <span v-if="s.total_score">{{ s.total_score }} 分</span>
              <span v-if="s.issue_count" class="warn-text">
                {{ s.issue_count }} 条提示
              </span>
            </div>
          </button>
        </div>
      </aside>

      <section class="detail-pane">
        <div v-if="detailLoading" class="pane-empty">加载套卷…</div>
        <div v-else-if="!selected" class="pane-empty">从左侧选择一套题库开始审核</div>
        <template v-else>
          <div class="paper-head">
            <div class="paper-title-row">
              <input v-if="canUpload" v-model="selected.name" class="paper-title-input" @blur="saveMeta" />
              <h2 v-else>{{ selected.name }}</h2>
              <span class="stamp large" :class="selected.status">{{ statusLabel[selected.status] }}</span>
            </div>
            <div class="meta-grid">
              <label>机构<input v-model="selected.institution" :disabled="!canUpload" @blur="saveMeta" /></label>
              <label>科目<input v-model="selected.subject" :disabled="!canUpload" @blur="saveMeta" /></label>
              <label>等级<input v-model="selected.level" :disabled="!canUpload" @blur="saveMeta" /></label>
              <label>年月<input v-model="selected.exam_month" type="month" :disabled="!canUpload" @blur="saveMeta" /></label>
            </div>
            <div v-if="validationIssues.length || aiStatus" class="warn-box">
              <div class="warn-head">
                <strong>解析与质检提示</strong>
                <span v-if="validationIssues.length" class="qc-count">
                  {{ validationErrorCount }} 处错误 · {{ validationWarnCount }} 处提示
                </span>
                <span v-if="aiStatus" class="ai-status" :class="{ ok: aiStatus.configured }">
                  {{ aiStatus.configured
                    ? `AI 习题模型：${aiStatus.model}（${aiSourceLabel}）`
                    : 'AI 习题模型未配置：请到 设置 → 模型配置 为「AI 习题」选模型' }}
                </span>
              </div>
              <ul v-if="validationIssues.length" class="qc-list">
                <li
                  v-for="(issue, i) in validationIssues"
                  :key="`${issue.code}-${issue.question_no}-${i}`"
                  class="qc-item"
                  :class="[issue.level, { structural: isStructuralIssue(issue.code) }]"
                  @click="jumpToQuestionNo(issue.question_no)"
                >
                  <span class="qc-badge" :class="issue.level">{{ issue.level === 'error' ? '质检错误' : '质检提示' }}</span>
                  {{ issue.message }}
                  <span v-if="isStructuralIssue(issue.code)" class="structural-hint">（需人工核对文档拆分/题号，AI 无法单题修复）</span>
                </li>
              </ul>
              <div v-if="canReview" class="warn-actions">
                <button
                  v-if="flaggedQuestionIds.length"
                  class="btn ghost"
                  :disabled="aiValidating"
                  @click="onValidateFlagged"
                  title="仅校准质检标记为疑点的题目（质检提示中的“第 n 题”）"
                >
                  {{ aiValidating ? `校准中 ${aiProgress.done}/${aiProgress.total}` : `AI 校准疑点题（${flaggedQuestionIds.length}）` }}
                </button>
                <button class="btn ghost" :disabled="aiValidating || draftCount === 0" @click="onValidateSet" title="对本套全部草稿题逐题校验；大套卷校准耗时较长，建议先确认已为「AI 习题」选模型">
                  {{ aiValidating ? `校准中 ${aiProgress.done}/${aiProgress.total}` : `AI 校准全部题（${draftCount}）` }}
                </button>
                <button class="btn ghost" :disabled="aiTagging || !aiTaggableCount" @click="onTagSet">
                  {{ aiTagging ? `打标中 ${aiProgress.done}/${aiProgress.total}` : `AI 知识点打标（${aiTaggableCount}）` }}
                </button>
              </div>
            </div>
            <div class="paper-actions">
              <button class="btn practice-entry" :disabled="!selected.questions?.length" @click="openPractice">
                刷题练习
              </button>
              <button class="btn practice-entry" :disabled="!selected.questions?.length" @click="aggregateOpen = true">
                综合练习
              </button>
              <button class="btn practice-entry" :disabled="!selected.questions?.length" @click="openExam">
                考试模拟
              </button>
              <button class="btn practice-entry" @click="openRecords">做题记录</button>
              <button class="btn practice-entry" @click="startMarkedPractice('wrong')">错题本</button>
              <button class="btn practice-entry" @click="startMarkedPractice('favorite')">我的收藏</button>
              <button v-if="canReview" class="btn" :disabled="selected.status === 'archived'" @click="onReviewAll">全部通过审核</button>
              <button v-if="canPublish" class="btn primary" :disabled="selected.status === 'published'" @click="onPublish">发布题库</button>
              <button v-if="canAssignment && selected.status === 'published'" class="btn" @click="onToAssignment">生成作业草稿</button>
              <button v-if="canBlueprint" class="btn" @click="openBlueprints">组卷规则</button>
              <button v-if="canArchive" class="btn danger-ghost" :disabled="selected.status === 'archived'" @click="onArchive">归档</button>
              <button v-if="canArchive" class="btn danger-ghost" @click="onDeleteSet">彻底删除</button>
            </div>
          </div>

          <div class="review-layout">
            <div class="q-nav-block">
              <span class="q-nav-label">题号 · {{ selected.questions?.length ?? 0 }} 题</span>
              <nav class="q-index" aria-label="题号">
                <button
                  v-for="(q, idx) in selected.questions"
                  :key="q.id"
                  class="q-no"
                  :class="[q.status, { active: q.id === activeQuestionId, flagged: flaggedOrderNos.has(q.order_no) }]"
                  :title="`${QUESTION_TYPE_LABELS[q.type]} · ${statusLabel[q.status]}`"
                  :aria-current="q.id === activeQuestionId ? 'true' : undefined"
                  @click="activeQuestionId = q.id"
                >
                  {{ idx + 1 }}
                </button>
              </nav>
            </div>

            <div v-if="!activeQuestion" class="pane-empty">这套题库暂无题目</div>
            <article v-else class="q-paper">
              <div class="q-head">
                <div class="q-title">
                  第 {{ activeQuestionIndex + 1 }} 题
                  <span class="q-type">{{ QUESTION_TYPE_LABELS[activeQuestion.type] }}</span>
                  <span class="stamp" :class="activeQuestion.status">{{ statusLabel[activeQuestion.status] }}</span>
                </div>
                <div v-if="canReview" class="q-actions">
                  <button class="btn ghost" :disabled="aiCleaning" @click="onAiClean">
                    {{ aiCleaning ? '清洗中…' : 'AI 清洗' }}
                  </button>
                  <button class="btn ghost" :disabled="aiSingleBusy" @click="onValidateQuestion">
                    {{ aiSingleBusy ? '校准中…' : 'AI 校准' }}
                  </button>
                  <button v-if="activeQuestion.review_note?.startsWith('AI 校准')" class="btn ghost" @click="onRevertAi">
                    撤销校准
                  </button>
                  <button v-if="activeQuestion.review_note?.startsWith('AI 打标')" class="btn ghost" @click="onRevertTag">
                    撤销打标
                  </button>
                  <input v-if="canManage" v-model.number="insertNo" type="number" min="1" class="insert-no" placeholder="插入到第几题(留空追加)" title="输入题号可把新题插入到该位置，后续题号自动后移" />
                  <button v-if="canManage" class="btn ghost" :disabled="saving" @click="onAddQuestion">+ 新增题目</button>
                  <button v-if="canManage" class="btn ghost" :disabled="saving || (selected?.questions?.length ?? 0) <= 1" @click="onDeleteQuestion">删除本题</button>
                  <button v-if="canManage" class="btn ghost" :disabled="saving || repairing" @click="onAutoRepair">{{ repairing ? 'AI 修复中…' : 'AI 一键修复' }}</button>
                  <button class="btn" :disabled="saving" @click="saveQuestion(false)">保存</button>
                  <button class="btn primary" :disabled="saving" @click="saveQuestion(true)">保存并通过</button>
                </div>
              </div>
              <p v-if="activeQuestion.review_note" class="review-note">{{ activeQuestion.review_note }}</p>

              <label class="fld-block">
                <span>题干</span>
                <textarea v-autogrow v-model="edit.stem" rows="4" :disabled="!canReview"></textarea>
              </label>

              <div v-if="['single_choice', 'multiple_choice'].includes(edit.type)" class="options-editor">
                <div class="options-head">
                  <span>选项（每行一个，按 A/B/C/D 顺序）</span>
                  <span class="hint">图片选项可留空文字</span>
                </div>
                <div v-for="(opt, i) in editOptions" :key="i" class="option-row">
                  <span class="opt-label">{{ optionLabel(i) }}</span>
                  <textarea
                    v-autogrow
                    v-model="editOptions[i]"
                    :disabled="!canManage"
                    class="opt-input"
                    rows="1"
                  ></textarea>
                  <img v-for="url in mediaFor(`option:${optionLabel(i)}`)" :key="url" :src="url" class="opt-img" alt="" />
                  <button
                    v-if="canManage && editOptions.length > 2"
                    type="button"
                    class="opt-del"
                    aria-label="删除该选项"
                    @click="removeOption(i)"
                  >
                    ×
                  </button>
                  <button
                    v-if="canManage"
                    type="button"
                    class="opt-merge"
                    :class="{ invisible: i === 0 }"
                    :disabled="i === 0"
                    aria-label="合并到上一项"
                    @click="mergeIntoPrevious(i)"
                  >
                    ↑ 合并到上一项
                  </button>
                </div>
                <div class="options-tail">
                  <button v-if="canManage && editOptions.length < 8" type="button" class="opt-add" @click="addOption">+ 添加选项</button>
                  <button v-if="canManage && editOptions.length > 2" type="button" class="opt-del-last" @click="removeLastOption()">− 删除最后一项</button>
                </div>
              </div>

              <div class="answer-grid">
                <label class="fld-block">
                  <span>答案{{ edit.type === 'multiple_choice' ? '（如 A,C）' : edit.type === 'judgement' ? '（正确/错误）' : '' }}</span>
                  <input v-model="edit.answerText" :disabled="!canManage" :placeholder="edit.type === 'single_choice' ? '如 C' : ''" />
                </label>
                <label class="fld-block small">
                  <span>难度</span>
                  <input v-model.number="edit.difficulty" type="number" min="1" max="10" :disabled="!canManage" />
                </label>
                <label class="fld-block small">
                  <span>分值</span>
                  <input v-model.number="edit.score" type="number" min="1" :disabled="!canManage" />
                </label>
                <label class="fld-block small">
                  <span>语言</span>
                  <select v-model="edit.language" :disabled="!canManage">
                    <option value="">无</option>
                    <option value="python">Python</option>
                    <option value="cpp">C++</option>
                  </select>
                </label>
              </div>

              <label v-if="['programming', 'code_fill'].includes(edit.type)" class="fld-block">
                <span>参考代码</span>
                <textarea v-model="edit.referenceCode" rows="6" class="code-area" :disabled="!canManage"></textarea>
              </label>

              <label class="fld-block">
                <span>解析</span>
                <textarea v-model="edit.analysis" rows="3" :disabled="!canManage"></textarea>
              </label>

              <label class="fld-block">
                <span>知识点（逗号分隔）</span>
                <input v-model="edit.knowledgeText" :disabled="!canManage" placeholder="如 列表, 条件语句" />
              </label>

              <div v-if="activeQuestion.media?.length" class="media-strip">
                <span class="media-label">配图</span>
                <div class="media-items">
                  <figure v-for="m in activeQuestion.media" :key="m.scope + m.url" class="media-item">
                    <img :src="m.url" alt="" />
                    <figcaption>{{ m.scope === 'stem' ? '题干' : m.scope.replace('option:', '选项 ') }}</figcaption>
                  </figure>
                </div>
              </div>

              <details v-if="activeQuestion.source_excerpt" class="source-box">
                <summary>原文对照</summary>
                <pre>{{ activeQuestion.source_excerpt }}</pre>
              </details>
            </article>
          </div>
        </template>
      </section>
    </div>

    <div v-if="blueprintOpen" class="modal-mask" @click.self="blueprintOpen = false">
      <div class="upload-modal">
        <h3>组卷规则</h3>
        <p class="modal-sub">标准模考蓝图：按题型配额从已发布题库随机抽题；学生模考时只会看到规则，不暴露答案。</p>
        <div class="blueprint-list">
          <div v-for="bp in blueprints" :key="bp.id" class="blueprint-row">
            <div>
              <strong>{{ bp.name }}</strong>
              <span class="bp-meta">{{ bp.subject || '不限科目' }} · {{ bp.level || '不限等级' }}</span>
            </div>
            <div class="bp-rules">
              <span v-for="(count, type) in bp.rules" :key="type">{{ typeLabel(type) }} {{ count }}</span>
            </div>
            <button class="btn ghost" @click="removeBlueprint(bp.id)">删除</button>
          </div>
          <p v-if="blueprints.length === 0" class="pane-empty small">暂无规则，先创建一条标准模考蓝图</p>
        </div>
        <div class="bp-form">
          <label>名称<input v-model="blueprintForm.name" placeholder="如 Python 二级标准模考" /></label>
          <label>科目<input v-model="blueprintForm.subject" placeholder="Python" /></label>
          <label>等级<input v-model="blueprintForm.level" placeholder="二级" /></label>
          <label>单选<input v-model.number="blueprintForm.single_choice" type="number" min="0" /></label>
          <label>多选<input v-model.number="blueprintForm.multiple_choice" type="number" min="0" /></label>
          <label>判断<input v-model.number="blueprintForm.judgement" type="number" min="0" /></label>
          <label>编程<input v-model.number="blueprintForm.programming" type="number" min="0" /></label>
        </div>
        <div class="modal-actions">
          <button class="btn" @click="blueprintOpen = false">关闭</button>
          <button class="btn primary" :disabled="blueprintSaving" @click="addBlueprint">添加规则</button>
        </div>
      </div>
    </div>

    <div v-if="uploadOpen" class="modal-mask" @click.self="uploadOpen = false">
      <div class="upload-modal">
        <h3>上传题库文档</h3>
        <p class="modal-sub">支持 DOCX。系统先按试卷标记解析，异常题目进入待审核；全部题目人工复核后才能发布。</p>
        <label class="file-drop">
          <input type="file" accept=".docx" @change="onFileChange" />
          <span>{{ uploadFile?.name || '选择 DOCX 文件' }}</span>
        </label>
        <div class="upload-grid">
          <label>套卷名称<input v-model="uploadMeta.name" placeholder="留空则自动识别" /></label>
          <label>机构<input v-model="uploadMeta.institution" /></label>
          <label>年月<input v-model="uploadMeta.exam_year" type="month" /></label>
          <label>科目<input v-model="uploadMeta.subject" placeholder="Python / C++ / 图形化 / 机器人" /></label>
          <label>等级<input v-model="uploadMeta.level" placeholder="如 二级" /></label>
        </div>
        <ul v-if="uploadWarnings.length" class="upload-warnings">
          <li v-for="w in uploadWarnings" :key="w">{{ w }}</li>
        </ul>
        <div class="modal-actions">
          <button class="btn" @click="uploadOpen = false">取消</button>
          <button class="btn primary" :disabled="uploading" @click="submitUpload">
            {{ uploading ? '解析中…' : '上传并解析' }}
          </button>
        </div>
      </div>
    </div>

    <div v-if="aggregateOpen" class="modal-mask" @click.self="aggregateOpen = false">
      <div class="upload-modal">
        <h3>综合练习</h3>
        <p class="modal-sub">按已发布题库的科目、等级和题型汇总抽题；答对自动进入下一题，答错会加入错题本，也可直接点「下一题」继续。</p>
        <div class="aggregate-form">
          <div class="aggregate-select">
            <span class="select-label">科目</span>
            <SearchableSelect
              v-model="aggregateForm.subject"
              :options="subjectOptions"
              placeholder="不限科目"
              group="qb-aggregate-subject"
            />
          </div>
          <div class="aggregate-select">
            <span class="select-label">等级</span>
            <SearchableSelect
              v-model="aggregateForm.level"
              :options="levelOptions"
              placeholder="不限等级"
              group="qb-aggregate-level"
            />
          </div>
          <label>单选<input v-model.number="aggregateForm.single_choice" type="number" min="0" /></label>
          <label>多选<input v-model.number="aggregateForm.multiple_choice" type="number" min="0" /></label>
          <label>判断<input v-model.number="aggregateForm.judgement" type="number" min="0" /></label>
          <label>编程<input v-model.number="aggregateForm.programming" type="number" min="0" /></label>
        </div>
        <div class="modal-actions">
          <button class="btn" @click="aggregateOpen = false">取消</button>
          <button class="btn primary" :disabled="aggregateLoading" @click="startAggregatePractice">
            {{ aggregateLoading ? '抽题中…' : '开始练习' }}
          </button>
        </div>
      </div>
    </div>

    <TeacherPracticeDialog
      v-if="practiceOpen && practiceAttempt"
      :attempt="practiceAttempt"
      :mode="practiceMode"
      :start-index="practiceStartIndex"
      @close="onPracticeClose"
      @retry="onPracticeRetry"
    />

    <ExamStartDialog
      v-if="examStartOpen"
      :sets="sets"
      :subjects="subjects"
      :levels="levels"
      :default-subject="filter.subject || selected?.subject || ''"
      :default-level="filter.level || selected?.level || ''"
      @close="examStartOpen = false"
      @start="startExam"
    />

    <div v-if="confirmState.visible" class="modal-mask" @click.self="closeConfirm">
      <div class="upload-modal confirm-modal" role="dialog" aria-modal="true">
        <h3 class="confirm-title">{{ confirmState.title }}</h3>
        <p class="confirm-msg">{{ confirmState.message }}</p>
        <div class="confirm-actions">
          <button class="btn" @click="closeConfirm">再想想</button>
          <button class="btn" :class="confirmState.danger ? 'danger' : 'primary'" @click="runConfirm">{{ confirmState.confirmText }}</button>
        </div>
      </div>
    </div>
    <div v-if="recordsOpen" class="modal-mask" @click.self="recordsOpen = false">
      <div class="upload-modal records-modal">
        <div class="records-head">
          <div>
            <h3>做题记录</h3>
            <p class="modal-sub">刷题、综合练习、错题本、套卷/随机考试都会自动记录，可继续未完成的练习或回看解析。</p>
          </div>
          <div class="records-filters">
            <select v-model="recordsKind" class="fld" @change="loadRecords">
              <option value="">全部模式</option>
              <option value="quick">刷题练习</option>
              <option value="aggregate">综合练习</option>
              <option value="marked">错题/收藏</option>
              <option value="exam_set">套卷考试</option>
              <option value="exam_random">随机考试</option>
            </select>
            <select v-model="recordsStatus" class="fld" @change="loadRecords">
              <option value="">全部状态</option>
              <option value="in_progress">进行中</option>
              <option value="evaluated">已完成</option>
            </select>
          </div>
        </div>
        <div v-if="recordsLoading" class="pane-empty">加载中…</div>
        <div v-else-if="records.length === 0" class="pane-empty">还没有做题记录，先开始一次练习吧。</div>
        <div v-else class="records-list">
          <button v-for="item in records" :key="item.id" class="record-row" @click="openRecord(item)">
            <div class="record-main">
              <strong>{{ item.paper_title || kindLabel(item.kind) || '练习' }}</strong>
              <span>{{ kindLabel(item.kind) }} · {{ formatRecordTime(item.started_at) }}</span>
            </div>
            <div class="record-meta">
              <span v-if="item.mode === 'exam' && item.status === 'evaluated'">
                {{ item.normalized_score ?? 0 }} 分
                <em :class="item.rating === '达标' ? 'pass' : 'fail'">{{ item.rating }}</em>
              </span>
              <span v-else-if="item.status === 'evaluated'">
                正确率 {{ Math.round((item.correct_rate ?? 0) * 100) }}%
              </span>
              <span v-else class="pending">进行中 · 继续</span>
            </div>
          </button>
        </div>
        <p v-if="recordsTotal > records.length" class="records-foot">仅展示最近 {{ records.length }} 条，共 {{ recordsTotal }} 条</p>
        <div class="modal-actions">
          <button class="btn" @click="recordsOpen = false">关闭</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import AssignmentsTabs from '@/components/AssignmentsTabs.vue'
import ExamStartDialog from '@/components/ExamStartDialog.vue'
import PageHead from '@/components/PageHead.vue'
import SearchableSelect from '@/components/SearchableSelect.vue'
import TeacherPracticeDialog from '@/components/TeacherPracticeDialog.vue'
import { QUESTION_TYPE_LABELS } from '@/api/assignment'
import {
  aiCleanQuestion,
  aiValidateQuestion,
  archiveBankSet,
  autoRepairBankSet,
  bankSetToAssignment,
  createBankBlueprint,
  createBankQuestion,
  deleteBankBlueprint,
  deleteBankQuestion,
  deleteBankSet,
  getBankSet,
  getBankSetValidation,
  getBankStats,
  getPracticeAttempt,
  getQuestionBankAiStatus,
  importBankDocx,
  listBankBlueprints,
  listBankSets,
  listPracticeAttempts,
  publishBankSet,
  reviewAllQuestions,
  revertAiReview,
  revertAiTag,
  startPracticeAttempt,
  updateBankQuestion,
  updateBankSet,
  type AiStatusOut,
  type AttemptSummary,
  type BankBlueprint,
  type BankIssue,
  type BankQuestion,
  type BankSet,
  type PracticeAttemptOut,
} from '@/api/questionBank'
import { answerFromText, answerToText } from '@/utils/questionBank'
import { useAuthStore } from '@/stores/auth'
import { useQbAiTasksStore } from '@/stores/qbAiTasks'
import { useToastStore } from '@/stores/toast'

const auth = useAuthStore()
const toast = useToastStore()
const router = useRouter()

function hasPerm(key: string): boolean {
  if (['admin', 'staff'].includes(auth.user?.role ?? '')) return true
  return auth.perms?.[key] === true
}

const canUpload = computed(() => hasPerm('question_bank_import'))
const canReview = computed(() => hasPerm('question_bank_review'))
const canPublish = computed(() => hasPerm('question_bank_publish'))
const canAssignment = computed(() => hasPerm('question_bank_assignment'))
const canBlueprint = computed(() => hasPerm('question_bank_blueprint'))
const canArchive = computed(() => hasPerm('question_bank_archive'))
const canManage = computed(
  () =>
    canUpload.value ||
    canReview.value ||
    canPublish.value ||
    canAssignment.value ||
    canBlueprint.value ||
    canArchive.value,
)

const stats = ref({ sets: 0, questions: 0, pending_review: 0 })
const sets = ref<BankSet[]>([])
const loading = ref(false)
const loadError = ref('')
const filter = reactive({ institution: '', subject: '', level: '', month: '', status: '' })

const institutions = computed(() => [...new Set(sets.value.map((s) => s.institution).filter(Boolean))] as string[])
const subjects = computed(() => [...new Set(sets.value.map((s) => s.subject).filter(Boolean))] as string[])
const levels = computed(() => [...new Set(sets.value.map((s) => s.level).filter(Boolean))] as string[])
const months = computed(
  () =>
    [
      ...new Set(
        sets.value
          .map((s) => s.exam_month || (s.exam_year ? String(s.exam_year) : ''))
          .filter(Boolean),
      ),
    ] as string[],
)

const selectedId = ref('')
const selected = ref<BankSet | null>(null)
const confirmState = ref<{
  visible: boolean
  title: string
  message: string
  confirmText: string
  danger: boolean
  onConfirm: (() => Promise<void> | void) | null
}>({ visible: false, title: '', message: '', confirmText: '确定', danger: false, onConfirm: null })
function openConfirm(opts: {
  title: string
  message: string
  confirmText?: string
  danger?: boolean
  onConfirm: () => Promise<void> | void
}) {
  confirmState.value = {
    visible: true,
    title: opts.title,
    message: opts.message,
    confirmText: opts.confirmText ?? '确定',
    danger: opts.danger ?? false,
    onConfirm: opts.onConfirm,
  }
}
function closeConfirm() {
  confirmState.value.visible = false
}
async function runConfirm() {
  const fn = confirmState.value.onConfirm
  confirmState.value.visible = false
  if (fn) await fn()
}
const insertNo = ref<number | null>(null)
const repairing = ref(false)
// 选项编辑器的自适应高度指令：文本内容越多，文本框自动增高
const vAutogrow = {
  mounted(el: HTMLTextAreaElement) {
    const grow = () => {
      el.style.height = 'auto'
      el.style.height = `${el.scrollHeight}px`
    }
    el.addEventListener('input', grow)
    // 初始按内容撑开（下一帧测量，确保布局完成）
    requestAnimationFrame(grow)
  },
  updated(el: HTMLTextAreaElement) {
    el.style.height = 'auto'
    el.style.height = `${el.scrollHeight}px`
  },
}
const detailLoading = ref(false)
const activeQuestionId = ref('')
const activeQuestionIndex = computed(() => selected.value?.questions?.findIndex((q) => q.id === activeQuestionId.value) ?? -1)
const activeQuestion = computed(() => selected.value?.questions?.find((q) => q.id === activeQuestionId.value) ?? null)
const practiceOpen = ref(false)
const practiceStartIndex = ref(0)
const practiceAttempt = ref<PracticeAttemptOut | null>(null)
const practiceMode = ref<'practice' | 'exam'>('practice')
const practiceLoading = ref(false)
const lastSession = ref<{
  kind: 'quick' | 'aggregate' | 'marked' | 'exam_set' | 'exam_random'
  set_id?: string
  rules?: Record<string, number>
  subject?: string
  level?: string
  mark_kind?: 'favorite' | 'wrong'
} | null>(null)
const aggregateOpen = ref(false)
const aggregateLoading = ref(false)
const aggregateForm = reactive({ subject: '', level: '', single_choice: 5, multiple_choice: 3, judgement: 5, programming: 1 })
const examStartOpen = ref(false)
const subjectOptions = computed(() => subjects.value.map((value) => ({ id: value, label: value })))
const levelOptions = computed(() => levels.value.map((value) => ({ id: value, label: value })))

const recordsOpen = ref(false)
const recordsLoading = ref(false)
const records = ref<AttemptSummary[]>([])
const recordsTotal = ref(0)
const recordsKind = ref('')
const recordsStatus = ref('')

const aiStatus = ref<AiStatusOut | null>(null)
const aiSourceLabel = computed(() => {
  const map: Record<string, string> = { module: '模块映射', default: '默认配置', env: '系统环境变量' }
  const source = aiStatus.value?.source ?? ''
  return map[source] ?? '已接通'
})
const validationIssues = ref<BankIssue[]>([])
const validationErrorCount = computed(() => validationIssues.value.filter((i) => i.level === 'error').length)
const validationWarnCount = computed(() => validationIssues.value.filter((i) => i.level !== 'error').length)
const draftCount = computed(() => (selected.value?.questions ?? []).filter((q) => q.status === 'draft').length)
// 集合级结构性问题：章节/总数不符、题号跳跃，AI 单题校准无法修复，需人工调整文档拆分或重新导入
const structuralIssueCodes = new Set(['number_gap', 'section_count_mismatch', 'total_count_mismatch'])
const isStructuralIssue = (code?: string | null) => code != null && structuralIssueCodes.has(code)
const flaggedOrderNos = computed(
  () => new Set(validationIssues.value.map((i) => i.question_no).filter((n): n is number => typeof n === 'number')),
)
const flaggedQuestionIds = computed(() =>
  (selected.value?.questions ?? []).filter((q) => flaggedOrderNos.value.has(q.order_no)).map((q) => q.id),
)
const qbTasks = useQbAiTasksStore()
const aiSingleBusy = ref(false)
const setAiTasks = computed(() => qbTasks.tasksForSet(selected.value?.id ?? ''))
const aiValidating = computed(() =>
  setAiTasks.value.some((t) => t.kind === 'validate' && t.status === 'running'),
)
const aiTagging = computed(() => setAiTasks.value.some((t) => t.kind === 'tag' && t.status === 'running'))
const aiProgress = computed(() => {
  const runningTask = setAiTasks.value.find((t) => t.status === 'running')
  return runningTask ? { done: runningTask.progress, total: runningTask.total } : { done: 0, total: 0 }
})
const aiTaggableCount = computed(() => (selected.value?.questions ?? []).filter((q) => !(q.knowledge_points?.length)).length)

async function openSession(
  payload: {
    kind: 'quick' | 'aggregate' | 'marked' | 'exam_set' | 'exam_random'
    set_id?: string
    rules?: Record<string, number>
    subject?: string
    level?: string
    mark_kind?: 'favorite' | 'wrong'
    exam_minutes?: number
  },
  mode: 'practice' | 'exam',
) {
  if (practiceLoading.value) return
  practiceLoading.value = true
  try {
    const attempt = await startPracticeAttempt({ ...payload, mode })
    practiceAttempt.value = attempt
    practiceMode.value = mode
    practiceStartIndex.value = 0
    lastSession.value = payload
    practiceOpen.value = true
    aggregateOpen.value = false
    examStartOpen.value = false
  } catch (e: unknown) {
    toast.error(actionErrorText(e, mode === 'exam' ? '开始考试失败' : '开始练习失败'))
  } finally {
    practiceLoading.value = false
  }
}

function openPractice() {
  if (!selected.value) return
  practiceStartIndex.value = Math.max(0, activeQuestionIndex.value)
  void openSession({ kind: 'quick', set_id: selected.value.id }, 'practice')
}

async function startMarkedPractice(kind: 'favorite' | 'wrong') {
  await openSession({ kind: 'marked', mark_kind: kind }, 'practice')
}

async function startAggregatePractice() {
  await openSession(
    {
      kind: 'aggregate',
      subject: aggregateForm.subject || undefined,
      level: aggregateForm.level || undefined,
      rules: {
        single_choice: aggregateForm.single_choice,
        multiple_choice: aggregateForm.multiple_choice,
        judgement: aggregateForm.judgement,
        programming: aggregateForm.programming,
      },
    },
    'practice',
  )
}

function openExam() {
  examStartOpen.value = true
}

async function startExam(payload: {
  kind: 'exam_set' | 'exam_random'
  set_id?: string
  rules?: Record<string, number>
  subject?: string
  level?: string
  exam_minutes?: number
}) {
  await openSession(payload, 'exam')
}

async function onPracticeClose() {
  practiceOpen.value = false
  practiceAttempt.value = null
  if (recordsOpen.value) await loadRecords()
}

async function onPracticeRetry() {
  const config = lastSession.value
  practiceOpen.value = false
  practiceAttempt.value = null
  if (!config) return
  await openSession(config, config.kind.startsWith('exam') ? 'exam' : 'practice')
}

async function loadRecords() {
  recordsLoading.value = true
  try {
    const data = await listPracticeAttempts(undefined, {
      limit: 40,
      ...(recordsKind.value ? { kind: recordsKind.value } : {}),
      ...(recordsStatus.value ? { status: recordsStatus.value } : {}),
    })
    records.value = data.items
    recordsTotal.value = data.total
  } catch {
    records.value = []
    recordsTotal.value = 0
  } finally {
    recordsLoading.value = false
  }
}

function openRecords() {
  recordsOpen.value = true
  void loadRecords()
}

async function openRecord(item: AttemptSummary) {
  try {
    const attempt = await getPracticeAttempt(item.id)
    practiceAttempt.value = attempt
    practiceMode.value = attempt.mode
    practiceStartIndex.value = 0
    const rawKind = attempt.kind ?? (attempt.mode === 'exam' ? 'exam_random' : 'quick')
    const kind = rawKind === 'set_practice' ? 'quick' : rawKind
    const meta = (attempt.paper_meta ?? {}) as {
      rules?: Record<string, number>
      subject?: string
      level?: string
      mark_kind?: 'favorite' | 'wrong'
    }
    lastSession.value = {
      kind,
      set_id: attempt.bank_set_id ?? undefined,
      rules: meta.rules,
      subject: meta.subject,
      level: meta.level,
      mark_kind: meta.mark_kind,
    }
    practiceOpen.value = true
    recordsOpen.value = false
  } catch {
    toast.error('读取做题记录失败')
  }
}

function actionErrorText(e: unknown, fallback: string): string {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object' && 'gaps' in detail) {
    const gaps = (detail as { gaps?: Record<string, string> }).gaps ?? {}
    const text = Object.values(gaps).filter(Boolean).join('；')
    if (text) return text
  }
  return (e as Error).message || fallback
}

function kindLabel(kind?: string): string {
  const map: Record<string, string> = {
    quick: '刷题练习',
    aggregate: '综合练习',
    marked: '错题/收藏',
    exam_set: '套卷考试',
    exam_random: '随机考试',
    set_practice: '套卷练习',
  }
  return kind ? map[kind] ?? kind : ''
}

function formatRecordTime(iso: string): string {
  const d = new Date(iso)
  return `${d.getMonth() + 1}月${d.getDate()}日 ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

async function loadAiStatus() {
  try {
    aiStatus.value = await getQuestionBankAiStatus()
  } catch {
    aiStatus.value = null
  }
}

async function onValidateQuestion() {
  const q = activeQuestion.value
  if (!q) return
  aiSingleBusy.value = true
  try {
    const res = await aiValidateQuestion(q.id, true, true)
    Object.assign(q, res.question)
    loadEdit(q)
    const fields = res.changed_fields ?? []
    if (res.applied && fields.length) {
      toast.success(`AI 已应用：${fields.join('、')}，请复核`)
    } else if (res.applied) {
      toast.success('AI 已校准，未发现需要修改的问题')
    } else if (fields.length) {
      toast.success(`AI 已生成校准建议：${fields.join('、')}，请复核`)
    } else {
      toast.success('AI 未发现需要修改的问题')
    }
    if (selected.value) void loadValidation(selected.value.id)
  } catch (e: unknown) {
    toast.error(actionErrorText(e, 'AI 校准失败'))
  } finally {
    aiSingleBusy.value = false
  }
}

async function onValidateSet() {
  if (!selected.value) return
  await runValidate(selected.value.questions ?? [])
}

async function onValidateFlagged() {
  if (!selected.value) return
  const flagged = new Set(flaggedQuestionIds.value)
  const targets = (selected.value.questions ?? []).filter((q) => flagged.has(q.id))
  if (!targets.length) {
    toast.success('没有需要校准的疑点题')
    return
  }
  await runValidate(targets)
}

async function runValidate(targets: BankQuestion[]) {
  if (!targets.length || !selected.value) return
  try {
    await qbTasks.startValidate(
      selected.value.id,
      targets.map((q) => q.id),
    )
    toast.info(`AI 校准已在后台开始（${targets.length} 题），进度见右下角浮窗，可自由切换页面`)
  } catch (e: unknown) {
    toast.error(actionErrorText(e, 'AI 校准启动失败，请检查模型配置'))
  }
}

async function onRevertAi() {
  const q = activeQuestion.value
  if (!q) return
  try {
    const updated = await revertAiReview(q.id)
    Object.assign(q, updated)
    loadEdit(q)
    toast.success('已撤销 AI 校准')
  } catch (e: unknown) {
    toast.error(actionErrorText(e, '撤销失败'))
  } finally {
    if (selected.value) void loadValidation(selected.value.id)
  }
}

async function onRevertTag() {
  const q = activeQuestion.value
  if (!q) return
  try {
    const updated = await revertAiTag(q.id)
    Object.assign(q, updated)
    loadEdit(q)
    toast.success('已撤销 AI 打标')
  } catch (e: unknown) {
    toast.error(actionErrorText(e, '撤销失败'))
  } finally {
    if (selected.value) void loadValidation(selected.value.id)
  }
}

async function onTagSet() {
  if (!selected.value) return
  const ids = (selected.value.questions ?? []).filter((q) => !(q.knowledge_points?.length)).map((q) => q.id)
  if (!ids.length) {
    toast.success('所有题目都已有知识点标签')
    return
  }
  try {
    await qbTasks.startTag(selected.value.id, ids)
    toast.info(`AI 知识点打标已在后台开始（${ids.length} 题），进度见右下角浮窗，可自由切换页面`)
  } catch (e: unknown) {
    toast.error(actionErrorText(e, 'AI 打标启动失败，请检查模型配置'))
  }
}

const doneValidateIds = ref<Set<string>>(new Set())
const validationWatcherPrimed = ref(false)
watch(
  () => setAiTasks.value.map((t) => `${t.id}:${t.status}:${t.progress}`).join('|'),
  () => {
    const done = setAiTasks.value.filter((t) => t.kind === 'validate' && t.status === 'done')
    const previously = doneValidateIds.value
    doneValidateIds.value = new Set(done.map((t) => t.id))
    const newly = done.filter((t) => !previously.has(t.id))
    const running = setAiTasks.value.some((t) => t.status === 'running')
    if (!running && newly.length && selected.value) {
      void refreshSetQuietly()
      void loadValidation(selected.value.id)
    }
    if (!validationWatcherPrimed.value) {
      validationWatcherPrimed.value = true
      return
    }
    for (const t of newly) {
      const applied = t.result?.applied ?? 0
      if (applied) toast.success(`AI 校准完成，已应用修复 ${applied} 题；其余题目仍需人工复核`)
    }
  },
)

const edit = reactive({
  type: '',
  stem: '',
  optionsText: '',
  answerText: '',
  analysis: '',
  difficulty: 3,
  score: 2,
  language: '',
  referenceCode: '',
  knowledgeText: '',
})
const editOptions = ref<string[]>([])
const saving = ref(false)
const aiCleaning = ref(false)

const statusLabel: Record<string, string> = {
  draft: '待审核',
  reviewed: '已审核',
  published: '已发布',
  archived: '已归档',
}

function loadEdit(q: BankQuestion | null) {
  if (!q) return
  edit.type = q.type
  edit.stem = q.stem
  editOptions.value = (q.options ?? []).slice()
  edit.answerText = answerToText(q.type, q.answer)
  edit.analysis = q.analysis ?? ''
  edit.difficulty = q.difficulty
  edit.score = q.score
  edit.language = q.language ?? ''
  edit.referenceCode = q.reference_code ?? ''
  edit.knowledgeText = (q.knowledge_points ?? []).join('，')
}

watch(activeQuestion, (q) => loadEdit(q))

function optionLabel(i: number): string {
  return String.fromCharCode(65 + i)
}

function addOption() {
  if (editOptions.value.length >= 8) {
    toast.info('最多支持 8 个选项')
    return
  }
  editOptions.value.push('')
}

function removeOption(index: number) {
  if (editOptions.value.length <= 2) return
  editOptions.value.splice(index, 1)
}

function removeLastOption() {
  if (editOptions.value.length <= 2) return
  editOptions.value.splice(editOptions.value.length - 1, 1)
}

function mergeIntoPrevious(index: number) {
  if (index <= 0 || index >= editOptions.value.length) return
  editOptions.value[index - 1] = `${editOptions.value[index - 1]}\n${editOptions.value[index]}`.trim()
  editOptions.value.splice(index, 1)
}

function typeLabel(t: string): string {
  return QUESTION_TYPE_LABELS[t as keyof typeof QUESTION_TYPE_LABELS] ?? t
}

function mediaFor(scope: string): string[] {
  return (activeQuestion.value?.media ?? []).filter((m) => m.scope === scope).map((m) => m.url)
}

async function onAddQuestion() {
  if (!selected.value) return
  const orderNo = insertNo.value && insertNo.value > 0 ? insertNo.value : undefined
  saving.value = true
  try {
    const created = await createBankQuestion(selected.value.id, {
      type: activeQuestion.value?.type ?? 'single_choice',
      stem: '',
      order_no: orderNo,
    })
    await refreshSetQuietly()
    const nextQuestion = selected.value?.questions?.find((q) => q.id === created.id)
    if (nextQuestion) {
      activeQuestionId.value = nextQuestion.id
      loadEdit(nextQuestion)
    }
    insertNo.value = null
    toast.success(orderNo ? `已在第 ${orderNo} 题位置插入新题，后续题号已自动重排` : '新题目已建立，请编辑题干与答案')
  } catch {
    toast.error('新建题目失败')
  } finally {
    saving.value = false
  }
}

function onDeleteSet() {
  if (!selected.value) return
  const set = selected.value
  openConfirm({
    title: '彻底删除套卷',
    message: `确定永久删除「${set.name || '该套卷'}」吗？将删除该套卷及其全部题目，历史作答会保留（快照已固化）。此操作不可撤销，如只想下架请改用「归档」。`,
    confirmText: '永久删除',
    danger: true,
    onConfirm: async () => {
      try {
        await deleteBankSet(set.id)
        toast.success('套卷已彻底删除')
        selectedId.value = ''
        selected.value = null
        await loadStats()
        await loadSets()
      } catch {
        toast.error('删除套卷失败')
      }
    },
  })
}

async function onAutoRepair() {
  if (!selected.value) return
  repairing.value = true
  try {
    const res = await autoRepairBankSet(selected.value.id, true)
    await refreshSetQuietly()
    if (selected.value) void loadValidation(selected.value.id)
    const errs = (res.details ?? []).filter((d) => d.status === 'error').length
    let msg = `已重排题号 ${res.renumbered} 题，AI 自动修复 ${res.fixed} 题`
    if (res.needs_review) msg += `，${res.needs_review} 题仍需人工确认`
    if (errs) msg += `，${errs} 题模型调用失败`
    toast.success(msg)
  } catch {
    toast.error('自动修复失败，请检查 AI 模型是否已配置')
  } finally {
    repairing.value = false
  }
}

function onDeleteQuestion() {
  const q = activeQuestion.value
  if (!q || !selected.value || !selected.value.questions) return
  const no = selected.value.questions.findIndex((x) => x.id === q.id) + 1
  openConfirm({
    title: '删除本题',
    message: `确定删除第 ${no} 题吗？删除后其后的题目会自动重新编号；历史作答会保留，但该题不再出现在套卷中。`,
    confirmText: '删除',
    danger: true,
    onConfirm: async () => {
      saving.value = true
      try {
        await deleteBankQuestion(q.id)
        await refreshSetQuietly()
        activeQuestionId.value = ''
        toast.success('题目已删除')
      } catch {
        toast.error('删除题目失败')
      } finally {
        saving.value = false
      }
    },
  })
}

async function loadStats() {
  try {
    stats.value = await getBankStats()
  } catch {
    /* 非管理角色可能无权限，静默 */
  }
}

async function loadSets() {
  loading.value = true
  loadError.value = ''
  try {
    const params: Record<string, string | number> = {}
    if (filter.institution) params.institution = filter.institution
    if (filter.subject) params.subject = filter.subject
    if (filter.level) params.level = filter.level
    if (filter.month) params.exam_month = filter.month
    if (filter.status) params.status = filter.status
    const data = await listBankSets(params)
    sets.value = data.items
    if (!selectedId.value && data.items[0]) {
      await selectSet(data.items[0].id)
    }
  } catch {
    loadError.value = '加载题库失败'
  } finally {
    loading.value = false
  }
}

async function selectSet(id: string) {
  selectedId.value = id
  detailLoading.value = true
  try {
    selected.value = await getBankSet(id)
    activeQuestionId.value = selected.value.questions?.[0]?.id ?? ''
    void loadValidation(id)
  } catch {
    toast.error('加载套卷详情失败')
  } finally {
    detailLoading.value = false
  }
}

async function loadValidation(setId?: string) {
  const target = setId ?? selected.value?.id
  if (!target) {
    validationIssues.value = []
    return
  }
  try {
    const res = await getBankSetValidation(target)
    if (selected.value?.id === target) validationIssues.value = res.issues ?? []
  } catch {
    if (selected.value?.id === target) validationIssues.value = []
  }
}

function jumpToQuestionNo(no?: number | null) {
  if (typeof no !== 'number') return
  const q = (selected.value?.questions ?? []).find((item) => item.order_no === no)
  if (q) activeQuestionId.value = q.id
}

async function saveMeta() {
  if (!selected.value) return
  if (selected.value.exam_month) {
    selected.value.exam_year = Number(selected.value.exam_month.slice(0, 4)) || null
  } else {
    selected.value.exam_year = null
  }
  try {
    const updated = await updateBankSet(selected.value.id, {
      name: selected.value.name,
      institution: selected.value.institution,
      exam_year: selected.value.exam_year,
      exam_month: selected.value.exam_month,
      subject: selected.value.subject,
      level: selected.value.level,
    })
    selected.value = { ...selected.value, ...updated }
    toast.success('套卷信息已保存')
    await loadSets()
  } catch {
    toast.error('保存套卷信息失败')
  }
}

async function saveQuestion(markReviewed = false) {
  const q = activeQuestion.value
  if (!q || !selected.value) return
  saving.value = true
  try {
    const payload: Partial<BankQuestion> = {
      type: edit.type as BankQuestion['type'],
      stem: edit.stem,
      options: ['single_choice', 'multiple_choice'].includes(edit.type)
        ? editOptions.value.map((x) => x.trim()).filter((x) => x.length > 0)
        : null,
      answer: answerFromText(edit.type, edit.answerText),
      analysis: edit.analysis || null,
      difficulty: edit.difficulty,
      score: edit.score,
      language: edit.language || null,
      reference_code: edit.referenceCode || null,
      knowledge_points: edit.knowledgeText
        ? edit.knowledgeText.split(/[，,]/).map((x) => x.trim()).filter(Boolean)
        : [],
    }
    if (markReviewed) payload.status = 'reviewed'
    const updated = await updateBankQuestion(selected.value.id, q.id, payload)
    q.type = updated.type
    q.stem = updated.stem
    q.options = updated.options
    q.answer = updated.answer
    q.analysis = updated.analysis
    q.difficulty = updated.difficulty
    q.score = updated.score
    q.language = updated.language
    q.reference_code = updated.reference_code
    q.knowledge_points = updated.knowledge_points
    q.status = updated.status
    toast.success(markReviewed ? '已保存并通过审核' : '题目已保存')
    if (markReviewed) await refreshSetQuietly()
    else { void loadValidation(selected.value.id); void loadSets() }
  } catch {
    toast.error('保存题目失败')
  } finally {
    saving.value = false
  }
}

async function refreshSetQuietly() {
  if (!selected.value) return
  try {
    const data = await getBankSet(selected.value.id)
    selected.value = data
    await loadSets()
    void loadValidation(selected.value.id)
    await loadStats()
  } catch {
    /* ignore */
  }
}

async function onReviewAll() {
  if (!selected.value) return
  try {
    const res = await reviewAllQuestions(selected.value.id)
    toast.success(`已通过 ${res.reviewed} 道题`)
    await refreshSetQuietly()
    await loadSets()
  } catch {
    toast.error('批量审核失败')
  }
}

async function onPublish() {
  if (!selected.value) return
  try {
    await publishBankSet(selected.value.id)
    toast.success('题库套卷已发布')
    await selectSet(selected.value.id)
    await loadStats()
    await loadSets()
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
    if (detail && typeof detail === 'object' && 'message' in detail) {
      const nums = (detail as { question_numbers?: number[] }).question_numbers ?? []
      toast.error(`${(detail as { message?: string }).message ?? '仍有题目未审核'}：第 ${nums.slice(0, 12).join('、')} 题`)
    } else {
      toast.error('发布失败，请确认全部题目已审核')
    }
  }
}

async function onArchive() {
  if (!selected.value) return
  try {
    await archiveBankSet(selected.value.id)
    toast.success('套卷已归档')
    await loadStats()
    await loadSets()
  } catch {
    toast.error('归档失败')
  }
}

async function onToAssignment() {
  if (!selected.value) return
  try {
    const res = await bankSetToAssignment(selected.value.id, { title: selected.value.name })
    toast.success(`已生成作业草稿：${res.title}（${res.question_count} 题）`)
    router.push({ path: '/assignments', query: { draft: res.assignment_id } })
  } catch (e: unknown) {
    toast.error((e as Error).message || '生成作业草稿失败')
  }
}

// —— 组卷规则 ——
const blueprints = ref<BankBlueprint[]>([])
const blueprintOpen = ref(false)
const blueprintSaving = ref(false)
const blueprintForm = reactive({
  name: '',
  subject: '',
  level: '',
  single_choice: 35,
  multiple_choice: 0,
  judgement: 10,
  programming: 2,
})

async function loadBlueprints() {
  try {
    blueprints.value = await listBankBlueprints()
  } catch {
    blueprints.value = []
  }
}

function openBlueprints() {
  blueprintOpen.value = true
  void loadBlueprints()
}

async function addBlueprint() {
  if (!blueprintForm.name.trim()) {
    toast.error('请填写规则名称')
    return
  }
  blueprintSaving.value = true
  try {
    await createBankBlueprint({
      name: blueprintForm.name.trim(),
      subject: blueprintForm.subject || null,
      level: blueprintForm.level || null,
      rules: {
        single_choice: blueprintForm.single_choice,
        multiple_choice: blueprintForm.multiple_choice,
        judgement: blueprintForm.judgement,
        programming: blueprintForm.programming,
      },
    })
    toast.success('组卷规则已保存')
    blueprintForm.name = ''
    await loadBlueprints()
  } catch (e: unknown) {
    toast.error((e as Error).message || '保存组卷规则失败')
  } finally {
    blueprintSaving.value = false
  }
}

async function removeBlueprint(id: string) {
  try {
    await deleteBankBlueprint(id)
    await loadBlueprints()
  } catch {
    toast.error('删除组卷规则失败')
  }
}

async function onAiClean() {
  const q = activeQuestion.value
  if (!q) return
  aiCleaning.value = true
  try {
    const updated = await aiCleanQuestion(q.id)
    q.type = updated.type
    q.stem = updated.stem
    q.options = updated.options
    q.answer = updated.answer
    q.analysis = updated.analysis
    q.difficulty = updated.difficulty
    q.reference_code = updated.reference_code
    q.review_note = updated.review_note
    q.status = updated.status
    loadEdit(q)
    toast.success('AI 清洗建议已生成，请逐项复核后再通过')
  } catch (e: unknown) {
    toast.error((e as Error).message || 'AI 清洗失败')
  } finally {
    aiCleaning.value = false
  }
}

// —— 上传 ——
const uploadOpen = ref(false)
const uploadFile = ref<File | null>(null)
const uploading = ref(false)
const uploadWarnings = ref<string[]>([])
const uploadMeta = reactive({ name: '', institution: '', exam_year: '', subject: '', level: '' })

function openUpload() {
  uploadFile.value = null
  uploadWarnings.value = []
  uploadMeta.name = ''
  uploadMeta.institution = '中国电子学会'
  uploadMeta.exam_year = ''
  uploadMeta.subject = ''
  uploadMeta.level = ''
  uploadOpen.value = true
}

function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  uploadFile.value = input.files?.[0] ?? null
}

function uploadErrorText(e: unknown): string {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        const row = item as { loc?: unknown[]; msg?: string }
        const field = (row.loc ?? []).filter((x) => x !== 'body').join('.')
        return field ? `${field}: ${row.msg ?? '参数有误'}` : (row.msg ?? '参数有误')
      })
      .join('；')
  }
  return (e as Error).message || '导入失败'
}

async function submitUpload() {
  if (!uploadFile.value) {
    toast.error('请选择 DOCX 文件')
    return
  }
  uploading.value = true
  uploadWarnings.value = []
  try {
    const res = await importBankDocx(uploadFile.value, {
      name: uploadMeta.name || undefined,
      institution: uploadMeta.institution || undefined,
      exam_year: uploadMeta.exam_year || undefined,
      subject: uploadMeta.subject || undefined,
      level: uploadMeta.level || undefined,
    })
    uploadWarnings.value = res.warnings
    toast.success(`导入 ${res.question_count} 道题，待人工审核`)
    uploadOpen.value = false
    await loadStats()
    await loadSets()
    await selectSet(res.set_id)
  } catch (e: unknown) {
    toast.error(uploadErrorText(e))
  } finally {
    uploading.value = false
  }
}

onMounted(async () => {
  if (!auth.user) await auth.fetchMe().catch(() => null)
  await auth.fetchPerms()
  void qbTasks.restore()
  await Promise.all([loadStats(), loadSets(), loadAiStatus()])
})
</script>

<style scoped>
.qb-view {
  min-height: 100%;
}

.stats-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}
.stat-card {
  display: flex;
  align-items: baseline;
  gap: 10px;
  min-width: 118px;
  padding: 10px 16px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 12px;
  box-shadow: var(--shadow-xs);
}
.stat-card.warn strong {
  color: #b45309;
}
.stat-label {
  font-size: 12px;
  color: var(--ink-3);
  font-weight: 600;
}
.stat-card strong {
  font-size: 22px;
  font-family: ui-monospace, 'SFMono-Regular', Consolas, monospace;
  line-height: 1;
}
.stat-tip {
  margin-left: auto;
  font-size: 12px;
  color: var(--ink-3);
}

.qb-workspace {
  display: grid;
  grid-template-columns: 340px minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}
.set-pane,
.detail-pane {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 16px;
  box-shadow: var(--shadow-sm);
  min-height: 520px;
}
.set-pane {
  padding: 14px;
  position: sticky;
  top: 16px;
}
.detail-pane {
  padding: 16px;
  background: #fffdf8;
}
.filter-bar {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  margin-bottom: 12px;
}
.fld {
  width: 100%;
  padding: 7px 9px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
  color: var(--ink-2);
  font-size: 12.5px;
}
.set-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: calc(100vh - 330px);
  overflow: auto;
  padding-right: 2px;
}
.set-card {
  text-align: left;
  padding: 12px 12px 10px;
  border: 1px solid var(--line);
  border-left: 3px solid #d8cbb4;
  border-radius: 10px;
  background: #fffdf8;
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s, transform 0.15s;
}
.set-card:hover {
  border-color: #c9b98f;
  box-shadow: var(--shadow-sm);
}
.set-card.active {
  border-left-color: #b8860b;
  box-shadow: 0 0 0 2px rgba(184, 134, 11, 0.16);
  background: #fffaf0;
}
.set-top {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}
.set-name {
  flex: 1;
  min-width: 0;
  font-weight: 700;
  font-size: 13px;
  color: var(--ink);
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.set-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 10px;
  font-size: 11.5px;
  color: var(--ink-3);
  margin-top: 6px;
}
.set-foot {
  display: flex;
  gap: 10px;
  margin-top: 8px;
  font-size: 11.5px;
  color: var(--ink-2);
  font-family: ui-monospace, 'SFMono-Regular', Consolas, monospace;
}
.warn-text {
  color: #b45309;
}
.stamp {
  flex-shrink: 0;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.04em;
  border: 1px solid transparent;
}
.stamp.draft {
  color: #92400e;
  background: #fef3c7;
  border-color: #f6d365;
}
.stamp.reviewed {
  color: #0f766e;
  background: #ccfbf1;
  border-color: #99f6e4;
}
.stamp.published {
  color: #166534;
  background: #dcfce7;
  border-color: #86efac;
}
.stamp.archived {
  color: var(--ink-3);
  background: var(--bg-soft);
  border-color: var(--line);
}
.stamp.large {
  padding: 5px 12px;
  font-size: 12px;
}
.pane-empty {
  padding: 60px 20px;
  text-align: center;
  color: var(--ink-3);
  font-size: 13px;
}

.paper-head {
  border: 1px solid #e7dcc6;
  border-radius: 12px;
  background: #fffaf0;
  padding: 14px 16px;
  margin-bottom: 14px;
}
.paper-title-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.paper-title-row h2,
.paper-title-input {
  flex: 1;
  min-width: 0;
  font-size: 18px;
  font-weight: 800;
  color: #3f2f14;
  font-family: 'Songti SC', 'Noto Serif SC', 'SimSun', serif;
}
.paper-title-input {
  border: 1px dashed transparent;
  border-radius: 6px;
  background: transparent;
  padding: 4px 6px;
}
.paper-title-input:hover,
.paper-title-input:focus {
  border-color: #d8c48f;
  background: #fff;
  outline: none;
}
.meta-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-top: 10px;
}
.meta-grid label,
.upload-grid label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 11.5px;
  color: #7c6a4a;
  font-weight: 600;
}
.meta-grid input,
.upload-grid input {
  padding: 6px 8px;
  border: 1px solid #e2d5bb;
  border-radius: 7px;
  background: #fff;
  font-size: 12.5px;
  color: var(--ink);
}
.meta-grid input:disabled {
  background: transparent;
  border-color: transparent;
  color: #5c4a2a;
}
.warn-box {
  margin-top: 10px;
  padding: 8px 12px;
  border-radius: 8px;
  background: #fffbeb;
  border: 1px solid #fde68a;
  font-size: 12px;
  color: #92400e;
}
.warn-box ul {
  margin: 4px 0 0;
  padding-left: 18px;
}
.warn-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}
.ai-status {
  font-size: 11px;
  color: #b45309;
}
.ai-status.ok {
  color: #0f766e;
}
.warn-actions {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}
.qc-count {
  font-size: 11px;
  color: #92400e;
  background: #fef3c7;
  border-radius: 999px;
  padding: 1px 9px;
}
.qc-list {
  margin: 6px 0 0;
  padding: 0;
  list-style: none;
  max-height: 180px;
  overflow-y: auto;
}
.qc-item {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  padding: 3px 4px;
  margin-bottom: 1px;
  border-radius: 6px;
  cursor: pointer;
  line-height: 1.5;
}
.qc-item:hover {
  background: #fef3c7;
}
.qc-badge {
  flex-shrink: 0;
  margin-top: 2px;
  padding: 0 6px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 700;
  line-height: 16px;
  background: #fde68a;
  color: #92400e;
}
.qc-badge.error {
  background: #fecaca;
  color: #991b1b;
}
.qc-item.structural {
  background: #fef2f2;
  border: 1px dashed #fca5a5;
}
.structural-hint {
  display: inline-block;
  margin-left: 6px;
  font-size: 10px;
  color: #b91c1c;
  font-weight: 600;
  white-space: nowrap;
}

.confirm-modal {
  width: min(420px, 100%);
  padding: 22px 22px 16px;
}
.confirm-title {
  font-size: 16px;
  color: #172554;
  margin-bottom: 8px;
}
.confirm-msg {
  font-size: 13px;
  line-height: 1.6;
  color: #475569;
}
.confirm-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 18px;
}
.btn.danger {
  background: #dc2626;
  border-color: #dc2626;
  color: #fff;
}
.btn.danger:hover {
  background: #b91c1c;
}
.records-modal {
  width: min(720px, 100%);
}
.records-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.records-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 52vh;
  overflow-y: auto;
  margin-top: 10px;
}
.record-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 11px 13px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: #fff;
  text-align: left;
  cursor: pointer;
}
.record-row:hover {
  border-color: #0f766e;
}
.record-main {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}
.record-main strong {
  font-size: 13px;
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.record-main span {
  font-size: 11.5px;
  color: var(--ink-3);
}
.record-meta {
  flex-shrink: 0;
  font-size: 12.5px;
  color: #172554;
  font-weight: 700;
}
.record-meta em {
  margin-left: 5px;
  padding: 2px 7px;
  border-radius: 999px;
  font-style: normal;
  font-size: 10.5px;
  font-weight: 600;
}
.record-meta em.pass {
  background: #dcfce7;
  color: #166534;
}
.record-meta em.fail {
  background: #fee2e2;
  color: #991b1b;
}
.record-meta .pending {
  color: #b45309;
  font-weight: 600;
}
.records-foot {
  margin-top: 8px;
  font-size: 11.5px;
  color: var(--ink-3);
}
.paper-actions {
  display: flex;
  gap: 8px;
  margin-top: 12px;
  flex-wrap: wrap;
}
.practice-entry {
  border-color: #99f6e4;
  background: #f0fdfa;
  color: #0f766e;
  font-weight: 700;
}
.practice-entry:hover {
  border-color: #2f6f73;
  color: #115e59;
}

.review-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 12px;
  align-items: start;
}
.q-nav-block {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid #eadfc9;
  border-radius: 12px;
  background: #fffdf7;
}
.q-nav-label {
  flex-shrink: 0;
  padding-top: 7px;
  color: var(--ink-3);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
}
.q-index {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  max-height: 200px;
  overflow-y: auto;
  padding-right: 4px;
}
.q-no {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  border: 1px solid var(--line);
  background: #fff;
  color: var(--ink-2);
  font-size: 12px;
  font-weight: 700;
  font-family: ui-monospace, 'SFMono-Regular', Consolas, monospace;
  line-height: 1;
  cursor: pointer;
}
.q-no.reviewed {
  border-color: #99f6e4;
  background: #f0fdfa;
  color: #0f766e;
}
.q-no.published {
  border-color: #86efac;
  background: #f0fdf4;
  color: #166534;
}
.q-no.active {
  outline: 2px solid #b8860b;
  outline-offset: 1px;
}
.q-no.flagged:not(.active) {
  border-color: #f59e0b;
  background: #fffbeb;
  color: #b45309;
}
.q-no.flagged {
  box-shadow: inset 0 -2px 0 #f59e0b;
}
.q-paper {
  border: 1px solid #eadfc9;
  border-radius: 12px;
  background: #fffdf7;
  padding: 16px 18px 20px;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.6);
}
.q-head {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}
.q-title {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 800;
  color: #3f2f14;
  font-size: 14px;
}
.q-type {
  padding: 2px 8px;
  border-radius: 6px;
  background: #f1e7d2;
  color: #7c5a1e;
  font-size: 11px;
  font-weight: 700;
}
.q-actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.review-note {
  margin: 0 0 10px;
  padding: 6px 10px;
  border-radius: 7px;
  background: #fef3c7;
  color: #92400e;
  font-size: 12px;
}
.fld-block {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin-bottom: 10px;
  font-size: 12px;
  color: #7c6a4a;
  font-weight: 600;
}
.fld-block span {
  font-size: 11.5px;
}
.fld-block textarea,
.fld-block input,
.fld-block select {
  width: 100%;
  padding: 8px 10px;
  border: 1px solid #e2d5bb;
  border-radius: 8px;
  background: #fff;
  font-size: 13px;
  color: var(--ink);
  font-family: inherit;
  line-height: 1.6;
  resize: vertical;
}
.fld-block textarea:disabled,
.fld-block input:disabled {
  background: #fbf7ee;
}
.code-area {
  font-family: ui-monospace, 'SFMono-Regular', Consolas, monospace;
  font-size: 12.5px;
  background: #1e293b !important;
  color: #e2e8f0 !important;
  border-color: #0f172a !important;
}
.fld-block textarea.autogrow-ta {
  resize: none;
  overflow-y: hidden;
}
.options-editor {
  margin-bottom: 10px;
  padding: 10px;
  border: 1px dashed #e2d5bb;
  border-radius: 9px;
  background: #fffcf5;
}
.options-head {
  display: flex;
  justify-content: space-between;
  font-size: 11.5px;
  color: #7c6a4a;
  font-weight: 700;
  margin-bottom: 8px;
}
.hint {
  font-weight: 400;
  color: var(--ink-3);
}
.option-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.opt-label {
  width: 20px;
  text-align: center;
  font-weight: 800;
  font-size: 12px;
  color: #7c5a1e;
  font-family: ui-monospace, 'SFMono-Regular', Consolas, monospace;
}
.option-row input {
  flex: 1;
  padding: 7px 9px;
  border: 1px solid #e2d5bb;
  border-radius: 7px;
  font-size: 12.5px;
}
.opt-img {
  width: 42px;
  height: 42px;
  object-fit: contain;
  border: 1px solid var(--line);
  border-radius: 6px;
}
.opt-del {
  flex: none;
  width: 22px;
  height: 22px;
  border: 1px solid #fecaca;
  border-radius: 6px;
  background: #fef2f2;
  color: #dc2626;
  font-size: 13px;
  line-height: 1;
  cursor: pointer;
}
.opt-del:hover {
  background: #fee2e2;
}
.opt-add {
  margin-top: 2px;
  padding: 5px 10px;
  border: 1px dashed #d6c8a8;
  border-radius: 7px;
  background: #fffdf7;
  color: #7c5a1e;
  font-size: 12px;
  cursor: pointer;
}
.opt-add:hover {
  background: #fdf6e3;
}
.opt-input {
  flex: 1;
  padding: 6px 8px;
  border: 1px solid #e2d5bb;
  border-radius: 7px;
  font-size: 12.5px;
  font-family: ui-monospace, 'SFMono-Regular', Consolas, monospace;
  min-height: 34px;
  resize: none;
  overflow: hidden;
  line-height: 1.5;
  box-sizing: border-box;
}
.opt-input:disabled {
  background: #f8fafc;
  color: var(--ink-3);
  cursor: not-allowed;
}
.opt-merge {
  margin-left: 6px;
  padding: 1px 8px;
  border: 1px solid #b45309;
  border-radius: 6px;
  background: #fffbeb;
  color: #92400e;
  font-size: 11px;
  cursor: pointer;
}
.opt-merge:hover {
  background: #fef3c7;
}
.opt-merge.invisible {
  visibility: hidden;
  pointer-events: none;
}
.insert-no {
  width: 150px;
  padding: 7px 9px;
  border: 1px solid #e2d5bb;
  border-radius: 7px;
  font-size: 12.5px;
}
.options-tail {
  display: flex;
  gap: 6px;
  margin-top: 4px;
}
.opt-del-last {
  padding: 5px 10px;
  border: 1px dashed #fca5a5;
  border-radius: 7px;
  background: #fef2f2;
  color: #b91c1e;
  font-size: 12px;
  cursor: pointer;
}
.opt-del-last:hover {
  background: #fee2e2;
}
.answer-grid {
  display: grid;
  grid-template-columns: minmax(0, 2fr) repeat(3, minmax(70px, 1fr));
  gap: 10px;
}
.answer-grid .fld-block {
  margin-bottom: 10px;
}
.media-strip {
  margin: 10px 0;
  padding-top: 10px;
  border-top: 1px dashed #e2d5bb;
}
.media-label {
  font-size: 11.5px;
  font-weight: 700;
  color: #7c6a4a;
}
.media-items {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 8px;
}
.media-item {
  margin: 0;
  text-align: center;
}
.media-item img {
  max-width: 150px;
  max-height: 110px;
  object-fit: contain;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
}
.media-item figcaption {
  font-size: 10.5px;
  color: var(--ink-3);
  margin-top: 3px;
}
.source-box {
  margin-top: 12px;
  border-top: 1px dashed #e2d5bb;
  padding-top: 10px;
  font-size: 12px;
  color: var(--ink-3);
}
.source-box summary {
  cursor: pointer;
  font-weight: 700;
  color: #7c6a4a;
}
.source-box pre {
  margin: 8px 0 0;
  max-height: 220px;
  overflow: auto;
  white-space: pre-wrap;
  font-size: 11.5px;
  line-height: 1.7;
  background: #f8f4ea;
  border: 1px solid #e7dcc6;
  border-radius: 8px;
  padding: 10px;
  color: var(--ink-2);
}
.btn.danger-ghost {
  color: #b91c1c;
  background: #fef2f2;
  border-color: #fecaca;
}
.btn.ghost {
  background: transparent;
  border-color: var(--line);
  color: var(--ink-2);
}

.modal-mask {
  position: fixed;
  inset: 0;
  z-index: 60;
  background: rgba(15, 23, 42, 0.42);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
}
.upload-modal {
  width: min(620px, 100%);
  max-height: 90vh;
  overflow: auto;
  background: #fffdf8;
  border: 1px solid #e7dcc6;
  border-radius: 16px;
  padding: 22px;
  box-shadow: var(--shadow-lg);
}
.upload-modal h3 {
  font-size: 18px;
  color: #3f2f14;
  font-family: 'Songti SC', 'Noto Serif SC', 'SimSun', serif;
}
.modal-sub {
  margin: 6px 0 14px;
  font-size: 12.5px;
  color: var(--ink-3);
  line-height: 1.6;
}
.file-drop {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  border: 1.5px dashed #d8c48f;
  border-radius: 10px;
  background: #fffaf0;
  cursor: pointer;
  font-size: 13px;
  color: #7c5a1e;
  font-weight: 600;
}
.file-drop input {
  display: none;
}
.upload-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  margin-top: 14px;
}
.upload-warnings {
  margin: 12px 0 0;
  padding: 10px 12px 10px 28px;
  border-radius: 8px;
  background: #fffbeb;
  border: 1px solid #fde68a;
  color: #92400e;
  font-size: 12px;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 16px;
}
.blueprint-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 220px;
  overflow: auto;
}
.blueprint-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  border: 1px solid #e7dcc6;
  border-radius: 9px;
  background: #fffaf0;
  font-size: 12.5px;
}
.blueprint-row > div:first-child {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.bp-meta {
  font-size: 11px;
  color: var(--ink-3);
}
.bp-rules {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 8px;
  font-size: 11px;
  color: #7c5a1e;
}

.aggregate-form {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}
.aggregate-select {
  display: flex;
  flex-direction: column;
  gap: 5px;
  min-width: 0;
}
.select-label {
  color: #7c6a4a;
  font-size: 11.5px;
  font-weight: 700;
}
.aggregate-select :deep(.ssel-trigger) {
  width: 100%;
  min-height: 34px;
  border-color: #e2d5bb;
  border-radius: 9px;
  background: #fff;
}
.aggregate-form > label {
  display: flex;
  flex-direction: column;
  gap: 5px;
  color: #7c6a4a;
  font-size: 11.5px;
  font-weight: 700;
}
.aggregate-form > label input {
  padding: 7px 9px;
  border: 1px solid #e2d5bb;
  border-radius: 9px;
  background: #fff;
  color: var(--ink);
  font-size: 13px;
}
.bp-form {
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin-top: 12px;
}
.bp-form label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 11.5px;
  color: #7c6a4a;
  font-weight: 600;
}
.bp-form input {
  padding: 6px 8px;
  border: 1px solid #e2d5bb;
  border-radius: 7px;
  font-size: 12.5px;
}
.pane-empty.small {
  padding: 18px;
}

@media (max-width: 1100px) {
  .qb-workspace {
    grid-template-columns: 290px minmax(0, 1fr);
  }
  .meta-grid,
  .answer-grid {
    grid-template-columns: 1fr 1fr;
  }
}
@media (max-width: 760px) {
  .qb-workspace {
    grid-template-columns: 1fr;
  }
  .set-pane {
    position: static;
  }
  .review-layout {
    grid-template-columns: 1fr;
  }
  .q-nav-block {
    flex-direction: column;
    gap: 8px;
  }
  .q-nav-label {
    padding-top: 0;
  }
  .q-index {
    gap: 5px;
  }
  .q-no {
    width: 28px;
    height: 28px;
  }
  .meta-grid,
  .upload-grid,
  .answer-grid {
    grid-template-columns: 1fr;
  }
}
</style>

