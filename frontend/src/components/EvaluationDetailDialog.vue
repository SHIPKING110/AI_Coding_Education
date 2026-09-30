<script setup lang="ts">
/**
 * 评估详情弹窗（M6）：管理端预览 + 家长端查看共用。
 * 以「评估报告单」形式渲染一份评估：封面头 + 周期统计 + 综合/学科/进步/提升/建议。
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'

import {
  blobErrorMessage,
  downloadBlob,
  exportClientEvaluationPdf,
  exportEvaluationPdf,
} from '@/api/evaluation'
import { cleanListishText } from '@/utils/text'
import { fmtCnDateKey, fmtCnPeriod } from '@/utils/date'

export interface EvaluationLike {
  id?: string
  title?: string | null
  status?: string
  period_start?: string
  period_end?: string
  student_name?: string | null
  teacher_name?: string | null
  content?: Record<string, unknown> | null
  stats?: Record<string, unknown> | null
  ppt_url?: string | null
  published_at?: string | null
}

const props = defineProps<{
  visible: boolean
  evaluation: EvaluationLike | null
  /** 是否展示「家长会 PPT 下载」入口（管理端 / 家长端均可） */
  showPpt?: boolean
  /** 家长/学员端传入当前学员 id：走客户端 PDF 导出接口（仅已发布）；缺省走管理端接口 */
  clientStudentId?: string | null
}>()

const emit = defineEmits<{ (e: 'close'): void }>()

const ev = computed(() => props.evaluation ?? ({} as EvaluationLike))

const content = computed(() => (ev.value?.content ?? {}) as Record<string, unknown>)
const stats = computed(() => (ev.value?.stats ?? null) as Record<string, number | null> | null)

const periodText = computed(() => {
  if (!ev.value?.period_start) return ''
  return fmtCnPeriod(str(ev.value.period_start), str(ev.value.period_end))
})

function str(v: unknown): string {
  return typeof v === 'string' ? v : v == null ? '' : String(v)
}

interface SubjectItem {
  name: string
  level: number
  comment: string
}

const subjects = computed<SubjectItem[]>(() => {
  const raw = content.value.subjects
  if (!Array.isArray(raw)) return []
  return raw.map((s) => ({
    name: str((s as Record<string, unknown>).name),
    level: Math.min(5, Math.max(1, Number((s as Record<string, unknown>).level) || 3)),
    comment: str((s as Record<string, unknown>).comment),
  }))
})

const LEVEL_LABELS: Record<number, string> = {
  5: '非常优秀',
  4: '优秀',
  3: '良好',
  2: '需加强',
  1: '待观察',
}

/** 能力雷达图（纯 SVG，无第三方依赖）：3~8 个能力项时展示五维星级分布 */
const radar = computed(() => {
  const subs = subjects.value.filter((s) => s.name.trim())
  if (subs.length < 3 || subs.length > 8) return null
  const cx = 110
  const cy = 100
  const R = 68
  const n = subs.length
  const ang = (i: number) => (Math.PI * 2 * i) / n - Math.PI / 2
  const pt = (i: number, r: number) => ({
    x: cx + Math.cos(ang(i)) * r,
    y: cy + Math.sin(ang(i)) * r,
  })
  const rings = [1, 2, 3, 4, 5].map((level) => ({
    level,
    points: subs
      .map((_, i) => {
        const p = pt(i, (R * level) / 5)
        return `${p.x.toFixed(1)},${p.y.toFixed(1)}`
      })
      .join(' '),
  }))
  const axes = subs.map((_, i) => {
    const p = pt(i, R)
    return { x1: cx, y1: cy, x2: p.x, y2: p.y }
  })
  const dataPoints = subs.map((s, i) => pt(i, (R * Math.min(5, Math.max(1, s.level))) / 5))
  const polygon = dataPoints.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ')
  const labels = subs.map((s, i) => {
    const p = pt(i, R + 17)
    const anchor = p.x < cx - 10 ? 'end' : p.x > cx + 10 ? 'start' : 'middle'
    const y = p.y < cy - 6 ? p.y - 2 : p.y > cy + 6 ? p.y + 9 : p.y + 4
    return { name: s.name, x: p.x, y, anchor }
  })
  return { rings, axes, dataPoints, polygon, labels }
})

const exporting = ref(false)
const exportError = ref('')

/** 下载后端生成的 PDF 报告（服务端渲染，无浏览器页眉页脚/网址）。 */
async function downloadPdf() {
  if (!ev.value?.id || exporting.value) return
  exporting.value = true
  exportError.value = ''
  try {
    const blob = props.clientStudentId
      ? await exportClientEvaluationPdf(props.clientStudentId, String(ev.value.id))
      : await exportEvaluationPdf(String(ev.value.id))
    const base = String(ev.value.title || `${ev.value.student_name ?? '学员'} 学习评估报告`).trim()
    downloadBlob(blob, `${base || '学习评估报告'}.pdf`)
  } catch (e: unknown) {
    exportError.value = (await blobErrorMessage(e)) || 'PDF 生成失败，请稍后重试'
  } finally {
    exporting.value = false
  }
}

function printReport() {
  // 兜底「浏览器打印」：把浏览器页眉中央标题改为评估报告名（打印完成后恢复）。
  // 后端 PDF 导出不受页眉/页脚限制，仅浏览器直接打印需要用户在打印弹窗取消勾选「页眉和页脚」
  const t = String(ev.value?.title || '').trim() || '学习评估报告'
  const prev = document.title
  document.title = `学习评估 · ${t}`
  window.print()
  const restore = () => {
    document.title = prev
    window.removeEventListener('afterprint', restore)
  }
  window.addEventListener('afterprint', restore)
}

const summary = computed(() => cleanListishText(content.value.summary))
const progress = computed(() => cleanListishText(content.value.progress))
const toImprove = computed(() => cleanListishText(content.value.to_improve))
const suggestions = computed(() => cleanListishText(content.value.suggestions))

const progressItems = computed(() => splitItems(progress.value))
const improveItems = computed(() => splitItems(toImprove.value))
const suggestionItems = computed(() => splitItems(suggestions.value))

function splitItems(text: string): string[] {
  if (!text) return []
  return text
    .split(/[；;\n]+/)
    .map((s) => s.trim())
    .filter(Boolean)
}

const statChips = computed(() => {
  if (!stats.value) return []
  const chips: Array<{ label: string; value: string; cls?: string }> = []
  const rate = stats.value.attendance_rate
  if (rate != null) {
    chips.push({ label: '出勤率', value: `${(Number(rate) * 100).toFixed(0)}%`, cls: 'cyan' })
  }
  chips.push({ label: '到课', value: `${stats.value.attended ?? 0} 次` })
  chips.push({ label: '请假', value: `${stats.value.leave ?? 0} 次` })
  chips.push({ label: '课时消耗', value: `${stats.value.consumed_lessons ?? 0} 节` })
  chips.push({ label: '课后反馈', value: `${stats.value.feedback_count ?? 0} 篇` })
  chips.push({ label: '已批改作业', value: `${stats.value.homework_count ?? 0} 份` })
  const scoreRate = stats.value.homework_score_rate
  if (scoreRate != null) {
    chips.push({
      label: '作业得分率',
      value: `${(Number(scoreRate) * 100).toFixed(0)}%`,
      cls: 'green',
    })
  }
  return chips
})

const publishedText = computed(() => {
  const iso = ev.value?.published_at
  if (!iso) return ''
  return fmtCnDateKey(iso)
})

function pptHref(): string {
  return `/uploads/${ev.value?.ppt_url ?? ''}`
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') emit('close')
}

watch(
  () => props.visible,
  (v) => {
    window.removeEventListener('keydown', onKeydown)
    if (v) window.addEventListener('keydown', onKeydown)
    // 弹窗打开时锁定背景滚动；打印时通过 body 类只输出报告单
    document.body.style.overflow = v ? 'hidden' : ''
    document.body.classList.toggle('eval-detail-open', v)
  },
)

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  document.body.style.overflow = ''
  document.body.classList.remove('eval-detail-open')
})
</script>

<template>
  <Teleport to="body">
    <Transition name="eval-fade">
      <div v-if="visible && evaluation" class="eval-overlay" @click.self="emit('close')">
        <div class="eval-modal" role="dialog" aria-modal="true">
          <!-- 封面头 -->
          <div class="eval-cover">
            <div class="cover-deco" />
            <span v-if="ev.status === 'published'" class="cover-stamp">已发布</span>
            <button class="cover-close" title="关闭" @click="emit('close')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M18 6 6 18M6 6l12 12" />
              </svg>
            </button>
            <p class="cover-kicker">学员学习评估报告</p>
            <h2 class="cover-title">{{ ev.title || `${ev.student_name ?? '学员'} 学习评估` }}</h2>
            <div class="cover-meta">
              <span class="meta-chip">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM4 20c0-4 4-6 8-6s8 2 8 6" /></svg>
                {{ ev.student_name || '学员' }}
              </span>
              <span class="meta-chip">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 2v4M16 2v4M3 10h18M5 4h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z" /></svg>
                {{ periodText }}
              </span>
              <span v-if="ev.teacher_name" class="meta-chip">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8" /></svg>
                {{ ev.teacher_name }}
              </span>
            </div>
          </div>

          <!-- 周期统计 -->
          <div v-if="statChips.length" class="eval-stats">
            <div v-for="c in statChips" :key="c.label" class="stat-chip" :class="c.cls">
              <span class="stat-value">{{ c.value }}</span>
              <span class="stat-label">{{ c.label }}</span>
            </div>
          </div>

          <!-- 正文 -->
          <div class="eval-body">
            <section v-if="summary" class="ev-section">
              <h3 class="ev-heading">
                <span class="ev-icon indigo">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M8 13h8M8 17h5" /></svg>
                </span>
                综合表现
              </h3>
              <p class="ev-text">{{ summary }}</p>
            </section>

            <section v-if="subjects.length" class="ev-section">
              <h3 class="ev-heading">
                <span class="ev-icon cyan">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m12 2 3 6.3 6.9 1-5 4.9 1.2 6.8L12 17.8 5.9 21l1.2-6.8-5-4.9 6.9-1z" /></svg>
                </span>
                学科能力
              </h3>
              <div v-if="radar" class="radar-wrap">
                <svg viewBox="0 0 220 196" class="radar-svg" role="img" aria-label="学科能力雷达图">
                  <defs>
                    <linearGradient id="evRadarFill" x1="0" y1="0" x2="1" y2="1">
                      <stop offset="0%" stop-color="#6366f1" stop-opacity="0.5" />
                      <stop offset="100%" stop-color="#06b6d4" stop-opacity="0.4" />
                    </linearGradient>
                  </defs>
                  <polygon
                    v-for="ring in radar.rings"
                    :key="ring.level"
                    :points="ring.points"
                    class="radar-ring"
                    :class="{ strong: ring.level === 5 }"
                  />
                  <line
                    v-for="(a, i) in radar.axes"
                    :key="`ax-${i}`"
                    :x1="a.x1"
                    :y1="a.y1"
                    :x2="a.x2"
                    :y2="a.y2"
                    class="radar-axis"
                  />
                  <polygon :points="radar.polygon" class="radar-data" fill="url(#evRadarFill)" />
                  <circle
                    v-for="(p, i) in radar.dataPoints"
                    :key="`dp-${i}`"
                    :cx="p.x"
                    :cy="p.y"
                    r="3"
                    class="radar-dot"
                  />
                  <text
                    v-for="(l, i) in radar.labels"
                    :key="`lb-${i}`"
                    :x="l.x"
                    :y="l.y"
                    class="radar-label"
                    :text-anchor="l.anchor"
                  >{{ l.name }}</text>
                </svg>
                <div class="radar-legend">
                  <span v-for="lv in 5" :key="lv" class="legend-item">
                    <i class="legend-dot" :class="`lv${lv}`" />
                    {{ lv }} 星 · {{ LEVEL_LABELS[lv] }}
                  </span>
                </div>
              </div>
              <div class="subject-list">
                <div v-for="(s, i) in subjects" :key="i" class="subject-card">
                  <div class="subject-top">
                    <strong>{{ s.name || `能力项 ${i + 1}` }}</strong>
                    <span class="level-badge" :class="`lv${s.level}`">{{ LEVEL_LABELS[s.level] }}</span>
                  </div>
                  <div class="stars" role="img" :aria-label="`评分 ${s.level} / 5`">
                    <span
                      v-for="n in 5"
                      :key="n"
                      class="star"
                      :class="{ on: n <= s.level }"
                    >★</span>
                  </div>
                  <p v-if="s.comment" class="subject-comment">{{ s.comment }}</p>
                </div>
              </div>
            </section>

            <section v-if="progressItems.length" class="ev-section">
              <h3 class="ev-heading">
                <span class="ev-icon green">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m3 17 6-6 4 4 8-8M15 7h6v6" /></svg>
                </span>
                进步亮点
              </h3>
              <ul class="ev-points">
                <li v-for="(p, i) in progressItems" :key="i">{{ p }}</li>
              </ul>
            </section>

            <section v-if="improveItems.length" class="ev-section">
              <h3 class="ev-heading">
                <span class="ev-icon orange">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" /></svg>
                </span>
                待提升项
              </h3>
              <ul class="ev-points">
                <li v-for="(p, i) in improveItems" :key="i">{{ p }}</li>
              </ul>
            </section>

            <section v-if="suggestionItems.length" class="ev-section">
              <h3 class="ev-heading">
                <span class="ev-icon purple">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18h6M10 22h4M12 2a7 7 0 0 0-4 12.7c.6.5 1 1.2 1 2V17h6v-.3c0-.8.4-1.5 1-2A7 7 0 0 0 12 2z" /></svg>
                </span>
                给家长的建议
              </h3>
              <ul class="ev-points">
                <li v-for="(p, i) in suggestionItems" :key="i">{{ p }}</li>
              </ul>
            </section>
          </div>

          <!-- 底部 -->
          <div class="eval-footer">
            <span v-if="publishedText" class="footer-meta">
              {{ ev.teacher_name ? `评估教师：${ev.teacher_name} · ` : '' }}发布于 {{ publishedText }}
            </span>
            <span v-else class="footer-meta">草稿预览 · 内容以最终发布为准</span>
            <div class="footer-ops">
              <button class="pdf-btn" :disabled="exporting" @click="downloadPdf()">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3" /></svg>
                {{ exporting ? '生成中…' : '下载 PDF 报告' }}
              </button>
              <button class="print-btn" :disabled="exporting" @click="printReport()">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9V2h12v7M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2M6 14h12v8H6z" /></svg>
                浏览器打印
              </button>
              <a
                v-if="showPpt && ev.ppt_url"
                class="ppt-btn"
                :href="pptHref()"
                target="_blank"
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3" /></svg>
                下载家长会 PPT
              </a>
              <button class="close-btn" @click="emit('close')">关闭</button>
              <span v-if="exportError" class="export-error">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" /></svg>
                {{ exportError }}
              </span>
              <span class="print-tip">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" /></svg>
                <span>PDF 由后端直接生成（A4 报告单），不含浏览器页眉页脚 / 网址；直接打印纸版时可用「浏览器打印」，并在打印弹窗取消勾选「页眉和页脚」</span>
              </span>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.eval-overlay {
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

.eval-modal {
  width: 640px;
  max-width: 100%;
  max-height: calc(100vh - 48px);
  display: flex;
  flex-direction: column;
  background: var(--surface);
  border-radius: 20px;
  box-shadow: var(--shadow-lg);
  overflow: hidden;
}

/* —— 封面 —— */
.eval-cover {
  position: relative;
  padding: 28px 26px 24px;
  background:
    radial-gradient(560px 220px at -12% -28%, rgba(124, 134, 255, 0.28), transparent 62%),
    radial-gradient(420px 180px at 92% 0%, rgba(0, 184, 219, 0.22), transparent 65%),
    linear-gradient(135deg, #1e1b4b 0%, #312e81 52%, #0e7490 100%);
  color: #f1f5f9;
}

.cover-stamp {
  position: absolute;
  top: 16px;
  right: 58px;
  padding: 4px 12px;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.2em;
  color: #fbbf24;
  border: 1.5px solid rgba(251, 191, 36, 0.75);
  border-radius: 8px;
  transform: rotate(6deg);
  box-shadow: 0 0 0 3px rgba(251, 191, 36, 0.12);
}

.cover-deco {
  position: absolute;
  right: -40px;
  top: -60px;
  width: 200px;
  height: 200px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(99, 102, 241, 0.5), transparent 70%);
  pointer-events: none;
}

.cover-close {
  position: absolute;
  top: 14px;
  right: 14px;
  width: 30px;
  height: 30px;
  border: none;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.14);
  color: #e2e8f0;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background 0.15s;
  z-index: 1;
}
.cover-close:hover {
  background: rgba(255, 255, 255, 0.26);
}
.cover-close svg {
  width: 14px;
  height: 14px;
}

.cover-kicker {
  font-size: 12px;
  letter-spacing: 0.28em;
  color: rgba(241, 245, 249, 0.66);
  margin-bottom: 8px;
}

.cover-title {
  font-size: 21px;
  font-weight: 800;
  letter-spacing: -0.01em;
  margin-bottom: 14px;
  padding-right: 32px;
}

.cover-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.meta-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.12);
  font-size: 12.5px;
  color: rgba(241, 245, 249, 0.92);
}

.meta-chip svg {
  width: 13px;
  height: 13px;
  opacity: 0.85;
}

/* —— 统计 —— */
.eval-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  padding: 16px 26px 4px;
  margin-top: 14px;
}

.stat-chip {
  flex: 1;
  min-width: 86px;
  position: relative;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 11px 8px 10px;
  border-radius: 14px;
  background: #fff;
  border: 1px solid var(--line);
  box-shadow: var(--shadow-xs);
}
.stat-chip::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: var(--brand-gradient);
  opacity: 0.95;
}

.stat-value {
  font-size: 17px;
  font-weight: 800;
  color: var(--ink);
  letter-spacing: -0.01em;
}

.stat-label {
  font-size: 11px;
  color: var(--ink-3);
}

.stat-chip.cyan {
  background: var(--accent-soft);
  border-color: #a5f3fc;
}
.stat-chip.cyan::before {
  background: linear-gradient(90deg, #00b8db, #615fff);
}
.stat-chip.cyan .stat-value {
  color: #0e7490;
}

.stat-chip.green {
  background: var(--success-soft);
  border-color: #86efac;
}
.stat-chip.green::before {
  background: linear-gradient(90deg, #0e9f6e, #06b6d4);
}
.stat-chip.green .stat-value {
  color: #047857;
}

/* —— 正文 —— */
.eval-body {
  flex: 1;
  overflow-y: auto;
  padding: 14px 26px 10px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.ev-section {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.ev-heading {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14.5px;
  font-weight: 700;
  color: var(--ink);
}

.ev-icon {
  width: 26px;
  height: 26px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.ev-icon svg {
  width: 14px;
  height: 14px;
}
.ev-icon.indigo {
  background: var(--brand-soft);
  color: var(--brand-strong);
}
.ev-icon.cyan {
  background: var(--accent-soft);
  color: #0e7490;
}
.ev-icon.green {
  background: var(--success-soft);
  color: #047857;
}
.ev-icon.orange {
  background: var(--warning-soft);
  color: #b45309;
}
.ev-icon.purple {
  background: #f3e8ff;
  color: #7e22ce;
}

.ev-text {
  position: relative;
  font-size: 13.5px;
  line-height: 1.85;
  color: var(--ink-2);
  background: var(--surface-alt);
  border: 1px solid #eef2f7;
  border-left: 3px solid #615fff;
  border-radius: 12px;
  padding: 13px 15px;
  box-shadow: var(--shadow-xs);
}

/* 学科能力 */
.radar-wrap {
  display: flex;
  align-items: center;
  gap: 16px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--surface);
  padding: 12px 16px;
}

.radar-svg {
  width: 220px;
  height: 196px;
  flex-shrink: 0;
}

.radar-ring {
  fill: none;
  stroke: #e2e8f0;
  stroke-width: 1;
}

.radar-ring.strong {
  stroke: #cbd5e1;
  stroke-width: 1.4;
}

.radar-axis {
  stroke: #eef2f7;
  stroke-width: 1;
}

.radar-data {
  stroke: var(--brand);
  stroke-width: 1.6;
  stroke-linejoin: round;
}

.radar-dot {
  fill: #fff;
  stroke: var(--brand);
  stroke-width: 2;
}

.radar-label {
  font-size: 9.5px;
  font-weight: 600;
  fill: var(--ink-2);
}

.radar-legend {
  display: flex;
  flex-direction: column;
  gap: 7px;
  font-size: 12px;
  color: var(--ink-2);
  min-width: 0;
}

.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  white-space: nowrap;
}

.legend-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.legend-dot.lv5 {
  background: #047857;
}

.legend-dot.lv4 {
  background: #059669;
}

.legend-dot.lv3 {
  background: #0e7490;
}

.legend-dot.lv2 {
  background: #d97706;
}

.legend-dot.lv1 {
  background: #dc2626;
}

.subject-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.subject-card {
  position: relative;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 13px 14px 12px 16px;
  background: var(--surface);
  transition:
    border-color 0.15s,
    box-shadow 0.15s;
}
.subject-card::before {
  content: '';
  position: absolute;
  left: 0;
  top: 12px;
  bottom: 12px;
  width: 3px;
  border-radius: 0 999px 999px 0;
  background: var(--brand-gradient);
  opacity: 0.9;
}
.subject-card:hover {
  border-color: #c7d2fe;
  box-shadow: var(--shadow-sm);
}

.subject-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.subject-top strong {
  font-size: 14px;
}

.level-badge {
  font-size: 11px;
  font-weight: 700;
  padding: 3px 10px;
  border-radius: 999px;
}

.level-badge.lv5 {
  background: var(--success-soft);
  color: #047857;
}
.level-badge.lv4 {
  background: #d1fae5;
  color: #059669;
}
.level-badge.lv3 {
  background: var(--accent-soft);
  color: #0e7490;
}
.level-badge.lv2 {
  background: var(--warning-soft);
  color: #b45309;
}
.level-badge.lv1 {
  background: var(--danger-soft);
  color: #b91c1c;
}

.stars {
  display: inline-flex;
  gap: 4px;
  margin-top: 9px;
  padding: 6px 10px;
  background: var(--bg);
  border-radius: 999px;
}

.star {
  font-size: 17px;
  line-height: 1;
  color: #e2e8f0;
  transition: color 0.15s;
}

.star.on {
  color: #f59e0b;
}

.subject-comment {
  margin-top: 8px;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--ink-2);
}

/* 要点列表 */
.ev-points {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.ev-points li {
  position: relative;
  padding-left: 20px;
  font-size: 13.5px;
  line-height: 1.75;
  color: var(--ink-2);
}

.ev-points li::before {
  content: '';
  position: absolute;
  left: 4px;
  top: 9px;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: linear-gradient(135deg, #6366f1, #06b6d4);
}

/* —— 底部 —— */
.eval-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 26px;
  border-top: 1px solid var(--line);
  background: #fbfcfe;
}

.footer-meta {
  font-size: 12px;
  color: var(--ink-3);
}

.footer-ops {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 8px 10px;
}

.ppt-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border-radius: 10px;
  background: linear-gradient(135deg, #6366f1, #06b6d4);
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  transition: filter 0.15s, transform 0.15s;
}
.ppt-btn:hover {
  filter: brightness(1.06);
  transform: translateY(-1px);
}
.ppt-btn svg {
  width: 14px;
  height: 14px;
}

.print-tip {
  font-size: 11px;
  color: var(--ink-3);
  opacity: 0.9;
  max-width: 320px;
  line-height: 1.5;
  display: flex;
  align-items: flex-start;
  gap: 4px;
}

.print-tip svg {
  width: 13px;
  height: 13px;
  flex-shrink: 0;
  margin-top: 1px;
  color: var(--warning);
}

.export-error {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  font-weight: 600;
  color: var(--danger);
  background: var(--danger-soft);
  border-radius: 8px;
  padding: 5px 10px;
}

.export-error svg {
  width: 13px;
  height: 13px;
  flex-shrink: 0;
}

.close-btn {
  padding: 8px 18px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface);
  color: var(--ink-2);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}
.close-btn:hover {
  border-color: var(--brand);
  color: var(--brand-strong);
}

.pdf-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  border: none;
  border-radius: 10px;
  background: linear-gradient(135deg, #6366f1, #06b6d4);
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: filter 0.15s, transform 0.15s, opacity 0.15s;
}
.pdf-btn:hover:not(:disabled) {
  filter: brightness(1.06);
  transform: translateY(-1px);
}
.pdf-btn:disabled {
  opacity: 0.65;
  cursor: not-allowed;
}

.pdf-btn svg {
  width: 14px;
  height: 14px;
}

.print-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface);
  color: var(--ink-2);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}
.print-btn:hover:not(:disabled) {
  border-color: var(--brand);
  color: var(--brand-strong);
}
.print-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.print-btn svg {
  width: 14px;
  height: 14px;
}

/* 过渡 */
.eval-fade-enter-active,
.eval-fade-leave-active {
  transition: opacity 0.2s ease;
}
.eval-fade-enter-active .eval-modal,
.eval-fade-leave-active .eval-modal {
  transition: transform 0.22s ease;
}
.eval-fade-enter-from,
.eval-fade-leave-to {
  opacity: 0;
}
.eval-fade-enter-from .eval-modal,
.eval-fade-leave-to .eval-modal {
  transform: translateY(14px) scale(0.98);
}

@media (max-width: 560px) {
  .eval-cover {
    padding: 20px 18px 16px;
  }
  .eval-stats {
    padding: 12px 18px 0;
  }
  .eval-body {
    padding: 12px 18px 8px;
  }
  .eval-footer {
    padding: 12px 18px;
    flex-wrap: wrap;
  }
  .stat-chip {
    min-width: calc(33% - 8px);
  }
  .radar-wrap {
    flex-direction: column;
    gap: 8px;
  }
  .cover-stamp {
    top: 54px;
    right: 16px;
  }
}
</style>

<style>
/* 打印（报告单导出）：仅当弹窗打开时隐藏应用其余部分，整页输出评估报告 */
@media print {
  body.eval-detail-open {
    background: #fff !important;
  }
  body.eval-detail-open > *:not(.eval-overlay) {
    display: none !important;
  }
  body.eval-detail-open * {
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }
  .eval-overlay {
    position: static !important;
    display: block !important;
    padding: 0 !important;
    background: #fff !important;
    backdrop-filter: none !important;
  }
  .eval-modal {
    width: 100% !important;
    max-width: none !important;
    max-height: none !important;
    border-radius: 0 !important;
    box-shadow: none !important;
    overflow: visible !important;
  }
  .eval-body {
    overflow: visible !important;
  }
  .cover-close {
    display: none !important;
  }
  .eval-footer {
    display: none !important;
  }
  .eval-footer .ppt-btn,
  .eval-footer .print-btn,
  .eval-footer .close-btn {
    display: none !important;
  }
}
</style>
