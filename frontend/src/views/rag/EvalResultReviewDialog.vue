<script setup lang="ts">
/**
 * 评测逐条复核弹窗：裁判五维 / 生成回答 / 检索判定 + 人工打分连评。
 * 纯检索运行（未开答案评测）自动切换为「检索视角」，隐藏裁判与打分区域。
 */
import { computed, ref, watch } from 'vue'

import { setEvalResultHumanScore, type RagEvalResult, type RagEvalRun } from '@/api/ragAdmin'

const props = defineProps<{
  visible: boolean
  run: RagEvalRun | null
  /** 当前连评清单（已按父级筛选，如「只看未复核」） */
  results: RagEvalResult[]
  initialIndex: number
  reviewedCount: number
  totalCount: number
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'saved', runId: string): void
}>()

const judgeKeys = ['faithfulness', 'relevance', 'completeness', 'logic', 'correctness'] as const
const judgeShort: Record<string, string> = {
  faithfulness: '忠实', relevance: '相关', completeness: '完整', logic: '逻辑', correctness: '正确',
}
const SPLIT_LABELS: Record<string, string> = { tuning: '调优', regression: '回归', frozen: '冻结' }
const CRIT_LABELS: Record<string, string> = { critical: '关键', important: '重要', normal: '普通' }
const KIND_LABELS: Record<string, string> = { answerable: '可答', unanswerable: '不可答', unlabeled: '未标注' }

const idx = ref(0)
const score = ref('')
const judgeLabel = ref('')
const reason = ref('')
const saving = ref(false)
const formError = ref('')

/**
 * 本次连评会话的清单快照：弹窗打开时从父级清单拍照，会话期间不再变动。
 * 父级在保存后会重新拉取结果（「只看未复核」还会把已评条目过滤掉），
 * 若仍跟随父级清单按索引导航，就会出现跳条、上一/下一条对不上号的问题。
 */
const queue = ref<RagEvalResult[]>([])
const current = computed<RagEvalResult | null>(() => queue.value[idx.value] ?? null)
const ans = computed(() => (current.value?.metrics?.answer ?? null) as Record<string, any> | null)
const judge = computed(() => (ans.value?.judge ?? null) as Record<string, any> | null)
const retrievalOnly = computed(() => props.run?.answer_eval === false && !judge.value)

const hitIds = computed(() => {
  const r = current.value
  if (!r) return new Set<string>()
  const rel = new Set(r.relevant || [])
  return new Set((r.ranked || []).filter((x) => rel.has(x)))
})

watch(
  () => current.value?.id,
  () => {
    formError.value = ''
    score.value = current.value?.human_score != null ? String(current.value.human_score) : ''
    judgeLabel.value = current.value?.human_judge || ''
    reason.value = current.value?.human_reason || ''
  },
  { immediate: true },
)

function judgeTagClass(v: unknown): string {
  if (typeof v !== 'number') return ''
  if (v >= 4) return 'ok'
  if (v >= 3) return 'pending'
  return 'bad'
}

function fixed(v: unknown): string {
  return typeof v === 'number' ? v.toFixed(2).replace(/\.?0+$/, '') : '-'
}

function pct(v: unknown): string {
  return typeof v === 'number' ? `${Math.round(v * 100)}%` : '-'
}

function citationText(a: Record<string, any> | null): string {
  const c = a?.citation
  if (!c || !c.present) return '未引用'
  const list = (c.indices || []).join('、')
  const invalid = (c.invalid || []).length
  return invalid ? `引用[${list}]（含 ${invalid} 个无效编号）` : `引用[${list}]`
}

watch(
  () => props.visible,
  (v) => {
    if (!v) return
    const list = props.results ?? []
    // 快照：会话内只在这个副本上上下翻页，不受父级刷新/过滤影响
    queue.value = list.slice()
    idx.value = Math.min(Math.max(0, props.initialIndex), Math.max(0, list.length - 1))
  },
  { immediate: true },
)

function prev() {
  if (idx.value > 0) idx.value -= 1
}

function next() {
  if (idx.value < queue.value.length - 1) idx.value += 1
}

async function save(andNext: boolean) {
  const r = current.value
  if (!r || saving.value) return
  const s = Number(score.value)
  if (!Number.isInteger(s) || s < 0 || s > 5) {
    formError.value = '请输入 0-5 的整数分'
    return
  }
  saving.value = true
  formError.value = ''
  try {
    await setEvalResultHumanScore(r.id, { score: s, judge: judgeLabel.value || '', reason: reason.value || '' })
    // 把本条结果回写到会话快照，使弹窗内「已复核」提示立即刷新
    const item = queue.value[idx.value]
    if (item) {
      item.human_score = s
      item.human_judge = judgeLabel.value || null
      item.human_reason = reason.value || null
    }
    emit('saved', r.run_id)
    if (andNext) next()
  } catch (e) {
    formError.value = e instanceof Error ? e.message : '评分失败'
  } finally {
    saving.value = false
  }
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') emit('close')
}

watch(
  () => props.visible,
  (v) => {
    window.removeEventListener('keydown', onKeydown)
    if (v) window.addEventListener('keydown', onKeydown)
    document.body.style.overflow = v ? 'hidden' : ''
  },
)
</script>

<template>
  <Teleport to="body">
    <Transition name="rv-fade">
      <div v-if="visible && current" class="rv-overlay" @click.self="emit('close')">
        <div class="rv-modal" role="dialog" aria-modal="true">
          <header class="rv-head">
            <div class="rv-head-main">
              <div class="rv-meta">
                <span class="rv-count">{{ idx + 1 }} / {{ queue.length }}</span>
                <span
                  v-for="chip in [
                    SPLIT_LABELS[current.metrics?.split] ? `split·${SPLIT_LABELS[current.metrics?.split]}` : '',
                    CRIT_LABELS[current.metrics?.business_criticality] ? `criticality·${CRIT_LABELS[current.metrics?.business_criticality]}` : '',
                    KIND_LABELS[current.metrics?.case_kind] ? `kind·${KIND_LABELS[current.metrics?.case_kind]}` : '',
                  ].filter(Boolean)"
                  :key="chip"
                  class="rv-chip"
                >{{ chip }}</span>
                <span class="rv-chip" :class="current.bad_case_type === 'ok' ? 'ok' : 'bad'">
                  {{ current.bad_case_type === 'ok' ? '检索通过' : `Bad Case·${current.bad_case_type || '-'}` }}
                </span>
              </div>
              <h3 class="rv-query">{{ current.query }}</h3>
            </div>
            <button class="rv-close" title="关闭" @click="emit('close')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12" /></svg>
            </button>
          </header>

          <div class="rv-body">
            <p v-if="retrievalOnly" class="rv-note">
              本次运行未开启答案评测（纯检索 A/B）：仅展示检索视角，无裁判分与生成回答。人工复核请选择开启答案评测的运行（如基线运行）。
            </p>

            <!-- 检索判定 -->
            <section class="rv-block">
              <b>检索判定</b>
              <div class="rv-kv">
                <span>检索命中：</span>
                <span class="rv-list">
                  <span
                    v-for="h in current.ranked"
                    :key="h"
                    class="rv-doc"
                    :class="hitIds.has(h) ? 'hit' : ''"
                  >{{ h }}</span>
                  <span v-if="!current.ranked.length" class="muted">无</span>
                </span>
              </div>
              <div class="rv-kv">
                <span>标注相关：</span>
                <span class="rv-list">
                  <span v-for="h in current.relevant" :key="h" class="rv-doc rel">{{ h }}</span>
                  <span v-if="!current.relevant.length" class="muted">无（不可答 / 反例）</span>
                </span>
              </div>
              <p class="rv-line muted">{{ current.retrieval_summary || '无检索诊断' }}</p>
            </section>

            <!-- 裁判评分 -->
            <section v-if="judge" class="rv-block">
              <b>裁判逐项评分（0-5）</b>
              <div class="rv-judge-grid">
                <span v-for="key in judgeKeys" :key="key" class="rv-judge-item">
                  {{ judgeShort[key] }}
                  <strong class="rv-score" :class="judgeTagClass(judge[key])">{{ fixed(judge[key]) }}</strong>
                </span>
              </div>
              <p class="rv-line"><span class="muted">裁判理由：</span>{{ judge.reason || '无' }}</p>
            </section>

            <!-- 生成回答 -->
            <section v-if="ans" class="rv-block">
              <b>生成回答</b>
              <p class="rv-answer">{{ ans.answer || '（无回答）' }}</p>
              <p class="rv-line muted">
                {{ citationText(ans) }} · 关键词命中 {{ pct(ans.keyword_hit) }}
                <template v-if="(ans.keyword_missing || []).length">· 缺失：{{ ans.keyword_missing.join('、') }}</template>
              </p>
            </section>

            <!-- 人工打分 -->
            <section v-if="!retrievalOnly" class="rv-block">
              <b>人工复核</b>
              <p class="rv-rubric">
                打分口径（与裁判 correctness 维度对齐）：回答事实与标准答案一致=5；用例不可答且正确拒答（如「文档未提供」）=5；
                编造或事实错误=0-2；部分一致=3-4。完整性/表达的问题请写入「理由」，不体现在分数上。
              </p>
              <div class="rv-form">
                <label>
                  分数（0-5）
                  <input v-model="score" type="number" min="0" max="5" placeholder="0-5" />
                </label>
                <label>
                  标签（可选）
                  <input v-model="judgeLabel" placeholder="如 correct" />
                </label>
                <label class="grow">
                  理由（可选）
                  <input v-model="reason" placeholder="一句话说明打分依据" />
                </label>
              </div>
              <p v-if="formError" class="rv-error">{{ formError }}</p>
              <p v-else-if="current.human_score != null" class="rv-line ok-text">已复核 {{ current.human_score }} 分（{{ current.human_judge || '无标签' }}）</p>
            </section>
          </div>

          <footer class="rv-foot">
            <span class="rv-progress">已复核 {{ reviewedCount }} / {{ totalCount }}</span>
            <div class="rv-ops">
              <button class="rv-btn" :disabled="idx === 0" @click="prev()">上一条</button>
              <button class="rv-btn" :disabled="idx >= queue.length - 1" @click="next()">下一条</button>
              <template v-if="!retrievalOnly">
                <button class="rv-btn" :disabled="saving" @click="save(false)">保存</button>
                <button class="rv-btn primary" :disabled="saving" @click="save(true)">保存并下一条</button>
              </template>
              <button class="rv-btn ghost" @click="emit('close')">关闭</button>
            </div>
          </footer>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.rv-overlay {
  position: fixed;
  inset: 0;
  z-index: 100;
  background: rgba(15, 23, 42, 0.55);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px 16px;
}

.rv-modal {
  width: 720px;
  max-width: 100%;
  max-height: calc(100vh - 48px);
  display: flex;
  flex-direction: column;
  background: var(--surface);
  border-radius: 18px;
  box-shadow: var(--shadow-lg);
  overflow: hidden;
}

.rv-head {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 18px 22px 14px;
  border-bottom: 1px solid var(--line);
  background: linear-gradient(135deg, #f8faff 0%, #eef6fb 100%);
}

.rv-head-main {
  flex: 1;
  min-width: 0;
}

.rv-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}

.rv-count {
  font-size: 11.5px;
  font-weight: 800;
  color: var(--brand-strong);
  background: var(--brand-soft);
  border-radius: 999px;
  padding: 2px 10px;
}

.rv-chip {
  font-size: 11px;
  font-weight: 600;
  color: var(--ink-3);
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 2px 9px;
  background: var(--surface);
}
.rv-chip.ok {
  color: #1c7d47;
  background: rgba(34, 158, 88, 0.1);
  border-color: transparent;
}
.rv-chip.bad {
  color: #a03028;
  background: rgba(200, 60, 50, 0.1);
  border-color: transparent;
}

.rv-query {
  font-size: 15.5px;
  font-weight: 700;
  line-height: 1.55;
  color: var(--ink);
}

.rv-close {
  flex-shrink: 0;
  width: 30px;
  height: 30px;
  border: none;
  border-radius: 50%;
  background: rgba(15, 23, 42, 0.06);
  color: var(--ink-2);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}
.rv-close:hover {
  background: rgba(15, 23, 42, 0.12);
}
.rv-close svg {
  width: 14px;
  height: 14px;
}

.rv-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px 22px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.rv-note {
  font-size: 12.5px;
  line-height: 1.7;
  color: #8a6413;
  background: rgba(190, 140, 20, 0.1);
  border: 1px solid rgba(190, 140, 20, 0.25);
  border-radius: 10px;
  padding: 9px 12px;
}

.rv-block b {
  display: block;
  font-size: 12.5px;
  margin-bottom: 7px;
  color: var(--ink);
}
.rv-block + .rv-block {
  border-top: 1px dashed var(--line);
  padding-top: 13px;
}

.rv-kv {
  display: flex;
  gap: 6px;
  font-size: 12.5px;
  line-height: 1.9;
}
.rv-kv > span:first-child {
  flex-shrink: 0;
  color: var(--ink-3);
}
.rv-list {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}

.rv-doc {
  font-size: 11.5px;
  padding: 1px 8px;
  border-radius: 6px;
  border: 1px solid var(--line);
  color: var(--ink-2);
  background: var(--surface-alt, #f8fafc);
}
.rv-doc.hit {
  border-color: transparent;
  background: rgba(34, 158, 88, 0.12);
  color: #1c7d47;
  font-weight: 700;
}
.rv-doc.rel {
  border-color: transparent;
  background: rgba(97, 95, 255, 0.1);
  color: var(--brand-strong);
}

.rv-judge-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 18px;
  font-size: 12.5px;
  margin-bottom: 6px;
}
.rv-judge-item {
  display: inline-flex;
  align-items: baseline;
  gap: 5px;
  color: var(--ink-3);
}
.rv-score {
  font-size: 14px;
  color: var(--ink);
}

.rv-line {
  font-size: 12.5px;
  line-height: 1.7;
  margin: 4px 0 0;
}
.rv-line.muted {
  color: var(--ink-3);
}
.ok-text {
  color: #1c7d47;
  font-weight: 600;
}

.rv-answer {
  white-space: pre-wrap;
  font-size: 12.5px;
  line-height: 1.7;
  margin: 0;
  padding: 9px 11px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface-alt, #f8fafc);
  color: var(--ink-2);
  max-height: 240px;
  overflow-y: auto;
}

.rv-form {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}
.rv-rubric {
  margin: 6px 0 10px;
  padding: 7px 10px;
  font-size: 11.5px;
  line-height: 1.7;
  color: var(--ink-3);
  background: #f8fafc;
  border: 1px solid var(--line);
  border-radius: 8px;
}
.rv-form label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 11.5px;
  color: var(--ink-3);
}
.rv-form label.grow {
  flex: 1;
  min-width: 180px;
}
.rv-form input {
  padding: 7px 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
  color: var(--ink);
  font-size: 12.5px;
}
.rv-form label:not(.grow) input {
  width: 110px;
}
.rv-form input:focus {
  outline: none;
  border-color: var(--brand);
  box-shadow: 0 0 0 3px rgba(97, 95, 255, 0.12);
}

.rv-error {
  margin: 8px 0 0;
  font-size: 12px;
  font-weight: 600;
  color: var(--danger);
}

.rv-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 12px 22px;
  border-top: 1px solid var(--line);
  background: #fbfcfe;
}

.rv-progress {
  font-size: 12px;
  font-weight: 700;
  color: var(--ink-3);
}

.rv-ops {
  display: flex;
  gap: 8px;
}

.rv-btn {
  padding: 7px 14px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: var(--surface);
  color: var(--ink-2);
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}
.rv-btn:hover:not(:disabled) {
  border-color: var(--brand);
  color: var(--brand-strong);
}
.rv-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.rv-btn.primary {
  border: none;
  background: var(--brand-gradient, linear-gradient(135deg, #6366f1, #06b6d4));
  color: #fff;
}
.rv-btn.primary:hover:not(:disabled) {
  filter: brightness(1.06);
  color: #fff;
}
.rv-btn.ghost {
  background: transparent;
}

.rv-fade-enter-active,
.rv-fade-leave-active {
  transition: opacity 0.18s ease;
}
.rv-fade-enter-active .rv-modal,
.rv-fade-leave-active .rv-modal {
  transition: transform 0.2s ease;
}
.rv-fade-enter-from,
.rv-fade-leave-to {
  opacity: 0;
}
.rv-fade-enter-from .rv-modal,
.rv-fade-leave-to .rv-modal {
  transform: translateY(12px) scale(0.985);
}

@media (max-width: 560px) {
  .rv-head,
  .rv-body,
  .rv-foot {
    padding-left: 16px;
    padding-right: 16px;
  }
  .rv-foot {
    flex-direction: column;
    align-items: stretch;
  }
  .rv-ops {
    justify-content: flex-end;
  }
}
</style>
