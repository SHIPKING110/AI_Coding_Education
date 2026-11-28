<script setup lang="ts">
import { computed, ref } from 'vue'

import { QUESTION_TYPE_LABELS } from '@/api/assignment'
import type { AttemptItemResult, PracticeAttemptOut } from '@/api/questionBank'

const props = defineProps<{
  attempt: PracticeAttemptOut
  title?: string
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'retry'): void
}>()

const result = computed(() => props.attempt.result)
const items = computed(() => result.value?.items ?? [])
const activeIdx = ref(0)
const activeItem = computed(() => items.value[activeIdx.value] ?? null)
function selectItem(i: number) {
  activeIdx.value = i
}
const normalized = computed(() => result.value?.normalized_score ?? (result.value?.total_score ? Math.round(((result.value?.score ?? 0) / result.value.total_score) * 100) : 0))
const rating = computed(() => result.value?.rating ?? null)
const typeEntries = computed(() => Object.entries(result.value?.type_stats ?? {}))

function typeLabel(type: string): string {
  return QUESTION_TYPE_LABELS[type as keyof typeof QUESTION_TYPE_LABELS] ?? type
}

function answerText(type: string, value: unknown): string {
  if (value === null || value === undefined || value === '') return '未作答'
  if (Array.isArray(value)) {
    if (type === 'multiple_choice') {
      return value.map((x) => String.fromCharCode(65 + Number(x))).join('、')
    }
    return value.join('、')
  }
  if (typeof value === 'boolean') return value ? '正确' : '错误'
  if (type === 'single_choice') return String.fromCharCode(65 + Number(value))
  return String(value)
}

function itemState(item: AttemptItemResult): string {
  if (item.is_correct === true) return '正确'
  if (item.is_correct === false) return '错误'
  return '待自评'
}

function itemClass(item: AttemptItemResult): string {
  if (item.is_correct === true) return 'ok'
  if (item.is_correct === false) return 'bad'
  return 'neutral'
}
</script>

<template>
  <div class="result-panel">
    <div class="result-hero">
      <div class="score-block">
        <strong>{{ normalized }}</strong>
        <span>满分 100</span>
      </div>
      <div class="hero-main">
        <div class="hero-title">
          {{ title || attempt.paper_title || (attempt.mode === 'exam' ? '模拟考试' : '练习') }}
          <span v-if="rating" class="rating" :class="rating === '达标' ? 'pass' : 'fail'">{{ rating }}</span>
        </div>
        <p>
          原始得分 {{ result?.score ?? 0 }} / {{ result?.total_score ?? 0 }} ·
          答对 {{ result?.correct_count ?? 0 }} / {{ result?.question_count ?? 0 }} 题
        </p>
      </div>
      <div class="hero-actions">
        <button class="btn" @click="emit('retry')">再练一次</button>
        <button class="btn primary" @click="emit('close')">完成</button>
      </div>
    </div>

    <div class="type-grid">
      <div v-for="[type, stat] in typeEntries" :key="type" class="type-card">
        <div class="type-head">
          <span>{{ typeLabel(type) }}</span>
          <strong>{{ Math.round((stat.correct_rate ?? (stat.total ? stat.correct / stat.total : 0)) * 100) }}%</strong>
        </div>
        <div class="type-bar">
          <span :style="{ width: `${Math.round((stat.correct_rate ?? (stat.total ? stat.correct / stat.total : 0)) * 100)}%` }" />
        </div>
        <small>答对 {{ stat.correct }} / {{ stat.total }}</small>
      </div>
    </div>

    <div class="review-list">
      <h3>答案解析</h3>
      <div class="q-grid" role="tablist" aria-label="题号导航">
        <button
          v-for="(item, i) in items"
          :key="item.id"
          type="button"
          class="q-chip"
          :class="[itemClass(item), { active: i === activeIdx }]"
          @click="selectItem(i)"
        >
          {{ item.order_no }}
        </button>
      </div>
      <article v-if="activeItem" class="review-item">
        <div class="review-head">
          <span class="review-no" :class="{ 'bad-no': activeItem.is_correct === false }">第 {{ activeItem.order_no }} 题 · {{ typeLabel(activeItem.type) }}</span>
          <span class="review-state" :class="itemClass(activeItem)">
            {{ itemState(activeItem) }} · {{ activeItem.score }}/{{ activeItem.max_score }} 分
          </span>
        </div>
        <p class="review-line"><strong>你的答案：</strong>{{ answerText(activeItem.type, activeItem.user_answer) }}</p>
        <p class="review-line"><strong>正确答案：</strong>{{ answerText(activeItem.type, activeItem.correct_answer) }}</p>
        <pre v-if="activeItem.reference_code" class="ref-code">{{ activeItem.reference_code }}</pre>
        <p v-if="activeItem.analysis" class="review-line"><strong>解析：</strong>{{ activeItem.analysis }}</p>
        <div v-if="activeItem.knowledge_points?.length" class="kp-row">
          <span v-for="kp in activeItem.knowledge_points" :key="kp">{{ kp }}</span>
        </div>
      </article>
    </div>
  </div>
</template>

<style scoped>
.result-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.result-hero {
  display: flex;
  align-items: center;
  gap: 18px;
  padding: 18px 20px;
  border-radius: 16px;
  background: linear-gradient(135deg, #0f2e2b, #17605a);
  color: #ecfdf5;
}
.score-block {
  display: flex;
  flex-direction: column;
  align-items: center;
  min-width: 96px;
  padding: 10px 14px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.12);
  border: 1px solid rgba(255, 255, 255, 0.18);
}
.score-block strong {
  font-size: 38px;
  line-height: 1;
  font-family: ui-monospace, Consolas, monospace;
  color: #fde68a;
}
.score-block span {
  margin-top: 4px;
  font-size: 11px;
  color: #a7f3d0;
}
.hero-main {
  flex: 1;
  min-width: 0;
}
.hero-title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 18px;
  font-weight: 700;
}
.rating {
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 12px;
}
.rating.pass {
  background: #bbf7d0;
  color: #14532d;
}
.rating.fail {
  background: #fecaca;
  color: #7f1d1d;
}
.hero-main p {
  margin-top: 6px;
  font-size: 12.5px;
  color: #cbd5e1;
}
.hero-actions {
  display: flex;
  gap: 8px;
}
.hero-actions .btn {
  background: rgba(255, 255, 255, 0.14);
  border-color: rgba(255, 255, 255, 0.24);
  color: #f8fafc;
}
.hero-actions .btn.primary {
  background: #e7b75b;
  border-color: #e7b75b;
  color: #1f2937;
}
.type-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 10px;
}
.type-card {
  padding: 12px 14px;
  border-radius: 12px;
  background: var(--surface);
  border: 1px solid var(--line);
}
.type-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12.5px;
  color: var(--ink-3);
}
.type-head strong {
  color: var(--ink);
  font-size: 15px;
}
.type-bar {
  height: 6px;
  margin: 8px 0 6px;
  border-radius: 999px;
  background: #e5e7eb;
  overflow: hidden;
}
.type-bar span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #2f6f73, #4fb3a9);
}
.type-card small {
  font-size: 11px;
  color: var(--ink-3);
}
.q-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 10px 0 14px;
}
.q-chip {
  min-width: 34px;
  height: 34px;
  padding: 0 8px;
  border-radius: 9px;
  border: 1px solid var(--line, #e2e8f0);
  background: #f8fafc;
  color: #334155;
  font-weight: 700;
  font-size: 13px;
  cursor: pointer;
}
.q-chip.ok {
  background: #ecfdf5;
  border-color: #86efac;
  color: #15803d;
}
.q-chip.bad {
  background: #fef2f2;
  border-color: #fca5a5;
  color: #dc2626;
}
.q-chip.active {
  outline: 2px solid #172554;
  outline-offset: 1px;
}
.review-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 50vh;
  overflow-y: auto;
}
.review-list h3 {
  font-size: 15px;
  color: var(--ink);
}
.review-item {
  padding: 14px 16px;
  border-radius: 12px;
  background: var(--surface);
  border: 1px solid var(--line);
}
.review-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 8px;
}
.review-no {
  font-weight: 700;
  font-size: 13px;
}
.review-state {
  padding: 3px 9px;
  border-radius: 999px;
  font-size: 11.5px;
}
.review-state.ok {
  background: #dcfce7;
  color: #166534;
}
.review-state.bad {
  background: #fee2e2;
  color: #991b1b;
}
.review-state.neutral {
  background: #fef3c7;
  color: #92400e;
}
.review-line {
  margin: 4px 0;
  font-size: 12.5px;
  line-height: 1.65;
  color: var(--ink-2);
  white-space: pre-wrap;
}
.review-list .bad-no {
  color: #b91c1c;
  font-weight: 700;
}
.ref-code {
  margin: 8px 0;
  padding: 10px 12px;
  border-radius: 8px;
  background: #0f172a;
  color: #e2e8f0;
  font-size: 12px;
  overflow: auto;
}
.kp-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}
.kp-row span {
  padding: 3px 9px;
  border-radius: 999px;
  background: #eef2f7;
  color: #475569;
  font-size: 11px;
}
</style>
