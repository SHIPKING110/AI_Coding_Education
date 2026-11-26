<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'

import { getComposeAvailability, type BankSet } from '@/api/questionBank'

const props = defineProps<{
  sets: BankSet[]
  subjects?: string[]
  levels?: string[]
  defaultSubject?: string
  defaultLevel?: string
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'start', payload: {
    kind: 'exam_set' | 'exam_random'
    set_id?: string
    rules?: Record<string, number>
    subject?: string
    level?: string
  }): void
}>()

const tab = ref<'set' | 'random'>('set')
const selectedSetId = ref('')
const form = reactive({
  subject: props.defaultSubject ?? '',
  level: props.defaultLevel ?? '',
  single_choice: 10,
  multiple_choice: 3,
  judgement: 5,
  programming: 1,
})

const availability = ref<Record<string, number> | null>(null)
const availabilityLoading = ref(false)
const TYPE_ROWS = [
  { key: 'single_choice', label: '单选' },
  { key: 'multiple_choice', label: '多选' },
  { key: 'judgement', label: '判断' },
  { key: 'programming', label: '编程' },
] as const

async function loadAvailability() {
  availabilityLoading.value = true
  try {
    availability.value = await getComposeAvailability({
      subject: form.subject || undefined,
      level: form.level || undefined,
    })
  } catch {
    availability.value = null
  } finally {
    availabilityLoading.value = false
  }
}

watch(tab, (value) => {
  if (value === 'random' && !availability.value) void loadAvailability()
})
watch(
  () => [form.subject, form.level],
  () => {
    if (tab.value === 'random') void loadAvailability()
  },
)

const shortages = computed(() => {
  if (!availability.value) return [] as { label: string; need: number; stock: number }[]
  return TYPE_ROWS.map((row) => ({
    label: row.label,
    need: Number(form[row.key] || 0),
    stock: availability.value?.[row.key] ?? 0,
  })).filter((row) => row.need > row.stock)
})

const publishedSets = computed(() => props.sets.filter((s) => s.status === 'published'))
const selectedSet = computed(() => publishedSets.value.find((s) => s.id === selectedSetId.value) ?? null)
const totalCount = computed(
  () =>
    Number(form.single_choice || 0) +
    Number(form.multiple_choice || 0) +
    Number(form.judgement || 0) +
    Number(form.programming || 0),
)

function start() {
  if (tab.value === 'set') {
    if (!selectedSetId.value) return
    emit('start', { kind: 'exam_set', set_id: selectedSetId.value })
    return
  }
  const rules: Record<string, number> = {
    single_choice: Number(form.single_choice) || 0,
    multiple_choice: Number(form.multiple_choice) || 0,
    judgement: Number(form.judgement) || 0,
    programming: Number(form.programming) || 0,
  }
  if (!Object.values(rules).some((v) => v > 0)) return
  if (shortages.value.length) return
  emit('start', {
    kind: 'exam_random',
    rules,
    subject: form.subject || undefined,
    level: form.level || undefined,
  })
}
</script>

<template>
  <div class="modal-mask" @click.self="emit('close')">
    <div class="exam-modal">
      <header class="exam-head">
        <div>
          <span class="eyebrow">EXAM SIMULATION</span>
          <h3>考试模拟</h3>
          <p>满分按 100 分折算，≥ 60 分评定为「达标」；交卷后统一公布答案、解析与题型正确率。</p>
        </div>
        <button class="close-btn" aria-label="关闭" @click="emit('close')">×</button>
      </header>

      <div class="exam-tabs" role="tablist">
        <button type="button" :class="{ active: tab === 'set' }" role="tab" @click="tab = 'set'">套卷测试</button>
        <button type="button" :class="{ active: tab === 'random' }" role="tab" @click="tab = 'random'">随机抽题</button>
      </div>

      <div v-if="tab === 'set'" class="tab-body">
        <label class="field">
          <span>选择已发布套卷</span>
          <select v-model="selectedSetId">
            <option value="">请选择套卷</option>
            <option v-for="s in publishedSets" :key="s.id" :value="s.id">
              {{ s.name }}（{{ s.question_count ?? 0 }} 题{{ s.total_score ? ` · ${s.total_score} 分` : '' }}）
            </option>
          </select>
        </label>
        <div v-if="selectedSet" class="set-summary">
          <div><span>科目</span><strong>{{ selectedSet.subject || '不限' }}</strong></div>
          <div><span>等级</span><strong>{{ selectedSet.level || '不限' }}</strong></div>
          <div><span>题数</span><strong>{{ selectedSet.question_count ?? 0 }}</strong></div>
          <div><span>原始总分</span><strong>{{ selectedSet.total_score ?? '—' }}</strong></div>
        </div>
        <p v-if="publishedSets.length === 0" class="empty">暂无已发布套卷，请先在题库审核并发布。</p>
      </div>

      <div v-else class="tab-body">
        <div class="random-grid">
          <label class="field">
            <span>科目</span>
            <select v-model="form.subject">
              <option value="">不限科目</option>
              <option v-for="s in props.subjects ?? []" :key="s" :value="s">{{ s }}</option>
            </select>
          </label>
          <label class="field">
            <span>等级</span>
            <select v-model="form.level">
              <option value="">不限等级</option>
              <option v-for="l in props.levels ?? []" :key="l" :value="l">{{ l }}</option>
            </select>
          </label>
          <label v-for="row in TYPE_ROWS" :key="row.key" class="field">
            <span>
              {{ row.label }}
              <em v-if="availability" class="stock-tag">库存 {{ availability[row.key] ?? 0 }}</em>
            </span>
            <input
              v-model.number="form[row.key]"
              type="number"
              min="0"
              :class="{ over: Number(form[row.key] || 0) > (availability?.[row.key] ?? Infinity) }"
            />
          </label>
        </div>
        <p class="total-hint">
          本次随机试卷共 {{ totalCount }} 题
          <span v-if="availabilityLoading" class="stock-loading">· 正在读取题库库存…</span>
        </p>
        <ul v-if="shortages.length" class="shortage-list">
          <li v-for="row in shortages" :key="row.label">
            {{ row.label }}题库存不足：需要 {{ row.need }} 题，题库仅 {{ row.stock }} 题，请减少数量或更换科目/等级
          </li>
        </ul>
      </div>

      <footer class="exam-actions">
        <button class="btn" @click="emit('close')">取消</button>
        <button
          class="btn primary"
          :disabled="tab === 'set' ? !selectedSetId : totalCount === 0 || shortages.length > 0"
          @click="start"
        >
          开始考试
        </button>
      </footer>
    </div>
  </div>
</template>

<style scoped>
.modal-mask {
  position: fixed;
  inset: 0;
  z-index: 110;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 18px;
  background: rgba(15, 23, 42, 0.55);
  backdrop-filter: blur(3px);
}
.exam-modal {
  width: min(560px, 100%);
  max-height: calc(100vh - 36px);
  overflow-y: auto;
  border-radius: 18px;
  border: 1px solid #e7dcc6;
  background: #fffdf7;
  box-shadow: 0 24px 80px rgba(15, 23, 42, 0.28);
}
.exam-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  padding: 20px 22px 14px;
  border-bottom: 1px solid #f0e6d3;
  background: #fff;
}
.eyebrow {
  color: #0f766e;
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.16em;
}
.exam-head h3 {
  margin: 4px 0 5px;
  font-size: 19px;
  color: var(--ink);
}
.exam-head p {
  max-width: 430px;
  color: var(--ink-3);
  font-size: 12px;
  line-height: 1.65;
}
.close-btn {
  width: 32px;
  height: 32px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: #fff;
  color: var(--ink-3);
  font-size: 19px;
  cursor: pointer;
}
.exam-tabs {
  display: flex;
  gap: 6px;
  padding: 12px 22px 0;
}
.exam-tabs button {
  padding: 8px 16px;
  border: 1px solid var(--line);
  border-bottom: none;
  border-radius: 10px 10px 0 0;
  background: #f8f5ee;
  color: var(--ink-3);
  font-size: 13px;
  cursor: pointer;
}
.exam-tabs button.active {
  background: #fff;
  color: #0f766e;
  font-weight: 700;
  border-color: #0f766e;
}
.tab-body {
  padding: 16px 22px;
  background: #fff;
  border-top: 1px solid var(--line);
}
.field {
  display: flex;
  flex-direction: column;
  gap: 5px;
  font-size: 12px;
  color: var(--ink-3);
}
.field select,
.field input {
  height: 36px;
  padding: 0 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
  color: var(--ink);
  font-size: 13px;
}
.random-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
.set-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  margin-top: 12px;
}
.set-summary div {
  padding: 10px 12px;
  border-radius: 10px;
  background: #f8f5ee;
  border: 1px solid #eee3cf;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.set-summary span {
  color: var(--ink-3);
  font-size: 11px;
}
.set-summary strong {
  color: #172554;
  font-size: 13px;
}
.total-hint {
  margin-top: 12px;
  color: #92400e;
  font-size: 12px;
}
.stock-tag {
  margin-left: 6px;
  padding: 0 6px;
  border-radius: 999px;
  background: #eef2f7;
  color: #475569;
  font-size: 10.5px;
  font-style: normal;
}
.stock-loading {
  margin-left: 4px;
  color: var(--ink-3);
}
.field input.over {
  border-color: #ef4444;
  background: #fef2f2;
  color: #b91c1c;
}
.shortage-list {
  margin: 8px 0 0;
  padding: 8px 12px 8px 26px;
  border-radius: 9px;
  background: #fef2f2;
  border: 1px solid #fecaca;
  color: #b91c1c;
  font-size: 11.5px;
  line-height: 1.7;
}
.empty {
  margin-top: 12px;
  color: var(--ink-3);
  font-size: 12.5px;
}
.exam-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 14px 22px 18px;
  border-top: 1px solid #f0e6d3;
  background: #fff;
}
</style>
