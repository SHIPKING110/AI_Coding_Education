<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

import { buildPpt, pptChatStream, pptDownloadUrl, type PptChatStage, type PptPhase } from '@/api/report'
import { renderMarkdown } from '@/utils/markdown'

const props = defineProps<{
  visible: boolean
  reportId: string
  reportTitle: string
  periodLabel: string
}>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'built', url: string): void }>()

interface PptOption {
  id: string
  label: string
  recommended?: boolean
  action: Record<string, unknown>
}
interface ChatMsg {
  role: 'user' | 'assistant'
  content: string
  options?: PptOption[]
}
interface OutlineItem {
  id: string
  title: string
  kind: string
  note: string
}
interface SectionItem {
  id: string
  title: string
  body: string
}

const STEPS = [
  { key: 'outline', label: '大纲', hint: '分析数据 → 确认页面结构' },
  { key: 'copy', label: '文案', hint: '逐页确认文字内容' },
  { key: 'layout', label: '排版', hint: '配色与视觉建议' },
  { key: 'export', label: '导出', hint: '生成并下载 PPT' },
] as const
type StepKey = (typeof STEPS)[number]['key']

// 思考过程的固定阶段（后端 SSE 逐条推送 phase 事件）
const PHASES: { key: string; label: string }[] = [
  { key: 'read', label: '读取报告数据与统计' },
  { key: 'analyze', label: '分析统计数据' },
  { key: 'model', label: 'AI 模型生成内容' },
  { key: 'stream', label: '接收并整理结果' },
]
const ACTION_TYPES = new Set([
  'apply_theme',
  'apply_outline',
  'apply_sections',
  'add_page',
  'remove_page',
  'go_stage',
  'build_ppt',
  'regen',
  'send',
])
const THEMES: { v: 'brand' | 'cyan' | 'deep'; n: string }[] = [
  { v: 'brand', n: '品牌蓝' },
  { v: 'cyan', n: '天青' },
  { v: 'deep', n: '深蓝' },
]

const step = ref<StepKey>('outline')
const stepIndex = computed(() => STEPS.findIndex((s) => s.key === step.value))

const messages = ref<ChatMsg[]>([])
const streamBuf = ref('')
const streaming = ref(false)
const busy = ref(false)
const error = ref('')

const outline = ref<OutlineItem[]>([])
const sections = ref<SectionItem[]>([])
const theme = ref<'brand' | 'cyan' | 'deep'>('brand')
const resultUrl = ref('')
const chatEl = ref<HTMLDivElement | null>(null)

const phaseKey = ref('')
const elapsed = ref(0)
let phaseTimer: ReturnType<typeof setInterval> | null = null

const KIND_OPTIONS = [
  { value: 'bullets', label: '要点卡' },
  { value: 'prose', label: '散文段' },
  { value: 'table', label: '数据表' },
  { value: 'bar', label: '柱状图' },
  { value: 'stats', label: '数据卡' },
]

const canBuild = computed(() => outline.value.length > 0)
const currentPhaseLabel = computed(
  () => PHASES.find((p) => p.key === phaseKey.value)?.label || '准备中',
)

watch(
  () => props.visible,
  (v) => {
    if (v) reset()
    else stopPhaseTimer()
  },
)
onBeforeUnmount(stopPhaseTimer)

function reset() {
  step.value = 'outline'
  messages.value = [
    {
      role: 'assistant',
      content:
        '我会基于本报告的统计数据与总结正文，和你一起把 PPT 做成 **大纲 → 文案 → 排版 → 导出** 四步。\n\n'
        + '- 统计数据一定用**图表**呈现，文案只留关键结论\n'
        + '- 每步我都会给出可点击的推荐选项，你点一下就能推进\n\n'
        + '点下面按钮开始，或直接输入你的想法。',
      options: [
        { id: 'start', label: '分析数据并生成大纲（推荐）', recommended: true, action: { type: 'regen', stage: 'outline' } },
      ],
    },
  ]
  streamBuf.value = ''
  streaming.value = false
  busy.value = false
  error.value = ''
  outline.value = []
  sections.value = []
  theme.value = 'brand'
  resultUrl.value = ''
  phaseKey.value = ''
  elapsed.value = 0
}

function stopPhaseTimer() {
  if (phaseTimer) {
    clearInterval(phaseTimer)
    phaseTimer = null
  }
}
function startPhaseTimer() {
  stopPhaseTimer()
  elapsed.value = 0
  phaseTimer = setInterval(() => {
    elapsed.value += 1
  }, 1000)
}

async function scrollBottom() {
  await nextTick()
  if (chatEl.value) chatEl.value.scrollTop = chatEl.value.scrollHeight
}

function extractJson(text: string): Record<string, unknown> | null {
  const m = text.match(/```json\s*([\s\S]*?)```/i) || text.match(/```\s*([\s\S]*?)```/)
  if (!m) return null
  try {
    return JSON.parse(m[1].trim())
  } catch {
    return null
  }
}
function stripJson(text: string): string {
  return text.replace(/```json[\s\S]*?```/gi, '').replace(/```[\s\S]*?```/g, '').trim()
}

/** 校验模型给的选项：只保留系统能真正执行的动作 */
function sanitizeOptions(raw: unknown): PptOption[] {
  if (!Array.isArray(raw)) return []
  const out: PptOption[] = []
  raw.forEach((o, i) => {
    if (!o || typeof o !== 'object') return
    const opt = o as Record<string, unknown>
    const action = (opt.action || {}) as Record<string, unknown>
    if (!ACTION_TYPES.has(String(action.type))) return
    const label = String(opt.label || '').trim()
    if (!label) return
    out.push({
      id: String(opt.id || `o${i + 1}`),
      label,
      recommended: Boolean(opt.recommended),
      action,
    })
  })
  return out.slice(0, 4)
}

/** 无模型选项时按当前步骤给出可执行的回退选项，保证始终有引导 */
function fallbackOptions(): PptOption[] {
  if (step.value === 'outline') {
    return [
      { id: 'f1', label: '确认大纲，生成文案（推荐）', recommended: true, action: { type: 'go_stage', stage: 'copy' } },
      { id: 'f2', label: '重新生成大纲', action: { type: 'regen', stage: 'outline' } },
      { id: 'f3', label: '直接生成 PPT', action: { type: 'build_ppt', theme: theme.value } },
    ]
  }
  if (step.value === 'copy') {
    return [
      { id: 'f1', label: '进入排版，选配色（推荐）', recommended: true, action: { type: 'go_stage', stage: 'layout' } },
      { id: 'f2', label: '重新生成文案', action: { type: 'regen', stage: 'copy' } },
      { id: 'f3', label: '直接生成 PPT', action: { type: 'build_ppt', theme: theme.value } },
    ]
  }
  if (step.value === 'layout') {
    return [
      { id: 'f1', label: '按推荐主题生成 PPT（推荐）', recommended: true, action: { type: 'build_ppt', theme: theme.value } },
      { id: 'f2', label: '换成深蓝主题', action: { type: 'apply_theme', theme: 'deep' } },
      { id: 'f3', label: '换成天青主题', action: { type: 'apply_theme', theme: 'cyan' } },
    ]
  }
  return []
}

function applyOutlineData(items: OutlineItem[]) {
  if (!items.length) return
  outline.value = items.map((it, i) => ({
    id: it.id || `s${i + 1}`,
    title: it.title || `第 ${i + 1} 页`,
    kind: it.kind || 'bullets',
    note: it.note || '',
  }))
  const map = new Map(sections.value.map((s) => [s.id, s]))
  sections.value = outline.value.map((o) => map.get(o.id) ?? { id: o.id, title: o.title, body: '' })
}
function applySectionsData(list: SectionItem[]) {
  if (!list.length) return
  sections.value = list.map((s, i) => ({
    id: s.id || `s${i + 1}`,
    title: s.title || '',
    body: s.body || '',
  }))
}

/** 解析模型结果并应用：大纲 / 文案 / 主题，返回选项 */
function applyResult(full: string): PptOption[] {
  const data = extractJson(full)
  if (!data) return []
  if (Array.isArray(data.outline)) applyOutlineData(data.outline as OutlineItem[])
  if (Array.isArray(data.sections)) applySectionsData(data.sections as SectionItem[])
  if (typeof data.theme === 'string' && THEMES.some((t) => t.v === data.theme)) {
    theme.value = data.theme as 'brand' | 'cyan' | 'deep'
  }
  return sanitizeOptions(data.options)
}

function stageForStep(): PptChatStage {
  if (step.value === 'outline') return 'outline'
  if (step.value === 'copy') return 'copy'
  if (step.value === 'layout') return 'layout'
  return 'chat'
}

/** 调用流式对话；完成后解析结果、生成选项气泡 */
async function runStream(stage: PptChatStage, message: string) {
  if (streaming.value) return
  if (message.trim()) messages.value.push({ role: 'user', content: message.trim() })
  error.value = ''
  streaming.value = true
  streamBuf.value = ''
  phaseKey.value = 'read'
  startPhaseTimer()
  await scrollBottom()
  let full = ''
  try {
    await pptChatStream(
      props.reportId,
      { stage, message, outline: outline.value, sections: sections.value },
      (delta) => {
        full += delta
        streamBuf.value = full
        scrollBottom()
      },
      undefined,
      (p: PptPhase) => {
        phaseKey.value = p.key
      },
    )
    const options = applyResult(full)
    const shown = stripJson(full) || '已根据你的要求更新。'
    messages.value.push({
      role: 'assistant',
      content: shown,
      options: options.length ? options : fallbackOptions(),
    })
  } catch (e: any) {
    error.value = e?.message || 'AI 定制失败'
  } finally {
    streaming.value = false
    streamBuf.value = ''
    stopPhaseTimer()
    await scrollBottom()
  }
}

const userInput = ref('')

function sendChat() {
  if (!userInput.value.trim()) return
  const msg = userInput.value
  userInput.value = ''
  runStream(stageForStep(), msg)
}

// —— 动作执行器：系统真正做得到的操作 ——
function runAction(opt: PptOption) {
  const a = opt.action
  switch (a.type) {
    case 'apply_theme':
      if (THEMES.some((t) => t.v === a.theme)) theme.value = a.theme as 'brand' | 'cyan' | 'deep'
      noteAction(`已切换为「${THEMES.find((t) => t.v === theme.value)?.n}」配色`)
      break
    case 'apply_outline':
      applyOutlineData((a.outline as OutlineItem[]) || [])
      noteAction('已按你的选择更新大纲')
      break
    case 'apply_sections':
      applySectionsData((a.sections as SectionItem[]) || [])
      noteAction('已按你的选择更新文案')
      break
    case 'add_page': {
      const id = `s${Date.now()}`
      outline.value.push({
        id,
        title: String(a.title || '新页面'),
        kind: String(a.kind || 'bullets'),
        note: String(a.note || ''),
      })
      sections.value.push({ id, title: String(a.title || '新页面'), body: '' })
      step.value = 'outline'
      noteAction(`已新增页面「${a.title || '新页面'}」`)
      break
    }
    case 'remove_page': {
      const title = String(a.title || '')
      const target = outline.value.find((o) => o.title === title)
      if (target) {
        outline.value = outline.value.filter((o) => o.id !== target.id)
        sections.value = sections.value.filter((s) => s.id !== target.id)
        noteAction(`已删除页面「${title}」`)
      } else {
        noteAction(`未找到页面「${title}」，请确认标题`)
      }
      break
    }
    case 'go_stage':
      if (['outline', 'copy', 'layout', 'export'].includes(String(a.stage))) {
        step.value = a.stage as StepKey
        noteAction(`已进入「${STEPS.find((s) => s.key === step.value)?.label}」步骤`)
      }
      break
    case 'regen': {
      const s = ['outline', 'copy', 'layout'].includes(String(a.stage))
        ? (a.stage as PptChatStage)
        : stageForStep()
      runStream(s, '')
      break
    }
    case 'build_ppt':
      if (typeof a.theme === 'string' && THEMES.some((t) => t.v === a.theme)) {
        theme.value = a.theme as 'brand' | 'cyan' | 'deep'
      }
      doBuild()
      break
    case 'send':
      runStream(stageForStep(), String(a.prompt || ''))
      break
  }
}

function noteAction(text: string) {
  messages.value.push({ role: 'assistant', content: text, options: fallbackOptions() })
  scrollBottom()
}

function addOutline() {
  const id = `s${Date.now()}`
  outline.value.push({ id, title: '新页面', kind: 'bullets', note: '' })
  sections.value.push({ id, title: '新页面', body: '' })
}
function removeOutline(id: string) {
  outline.value = outline.value.filter((o) => o.id !== id)
  sections.value = sections.value.filter((s) => s.id !== id)
}
function moveOutline(id: string, dir: -1 | 1) {
  const i = outline.value.findIndex((o) => o.id === id)
  const j = i + dir
  if (i < 0 || j < 0 || j >= outline.value.length) return
  const arr = [...outline.value]
  ;[arr[i], arr[j]] = [arr[j], arr[i]]
  outline.value = arr
}

function splitItems(body: string): string[] {
  return body
    .split(/[。；;\n]+/)
    .map((s) => s.trim())
    .filter(Boolean)
    .slice(0, 8)
}

/** 组装后端 slides 规格：数据类页面交给后端自动注入（保证图表） */
function toSlides() {
  const slides: Record<string, unknown>[] = []
  for (const o of outline.value) {
    const sec = sections.value.find((s) => s.id === o.id)
    const body = (sec?.body || '').trim()
    if (['table', 'bar', 'stats', 'data', 'chart', 'trend'].includes(o.kind)) continue
    if (o.kind === 'prose') {
      slides.push({ kind: 'prose', title: o.title, text: body || o.note })
    } else {
      const items = splitItems(body)
      slides.push({ kind: 'bullets', title: o.title, items: items.length ? items : [o.note || o.title] })
    }
  }
  return slides
}

async function doBuild() {
  if (!props.reportId || busy.value) return
  busy.value = true
  error.value = ''
  try {
    const r = await buildPpt(props.reportId, {
      title: props.reportTitle,
      theme: theme.value,
      slides: toSlides(),
    })
    resultUrl.value = r.ppt_url
    step.value = 'export'
    messages.value.push({
      role: 'assistant',
      content: 'PPT 已生成，统计已用表格与图表呈现。可在右侧下载或预览；如需调整可继续对话后重新生成。',
      options: [
        { id: 'again', label: '重新调整（回到排版）', action: { type: 'go_stage', stage: 'layout' } },
        { id: 'copy', label: '修改文案再生成', action: { type: 'go_stage', stage: 'copy' } },
      ],
    })
    emit('built', r.ppt_url)
    await scrollBottom()
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || '生成失败'
  } finally {
    busy.value = false
  }
}

function close() {
  emit('close')
}
</script>

<template>
  <div v-if="visible" class="ppt-builder-overlay" @click.self="close">
    <div class="ppt-builder">
      <header class="pb-head">
        <div class="pb-head-main">
          <h2>AI 定制 PPT</h2>
          <p class="pb-sub">{{ reportTitle }} · {{ periodLabel }}</p>
        </div>
        <button class="pb-close" @click="close" title="关闭">×</button>
      </header>

      <ol class="pb-steps">
        <li
          v-for="(s, i) in STEPS"
          :key="s.key"
          class="pb-step"
          :class="{ active: s.key === step, done: i < stepIndex }"
        >
          <span class="pb-step-no">{{ i < stepIndex ? '✓' : i + 1 }}</span>
          <span class="pb-step-txt"><b>{{ s.label }}</b><em>{{ s.hint }}</em></span>
        </li>
      </ol>

      <div class="pb-body">
        <!-- 左：对话 -->
        <section class="pb-chat">
          <div ref="chatEl" class="pb-msgs">
            <div v-for="(m, i) in messages" :key="i" class="pb-msg" :class="m.role">
              <div class="pb-bubble" v-html="renderMarkdown(m.content)" />
            </div>

            <!-- 思考过程面板 -->
            <div v-if="streaming" class="pb-thinking">
              <div class="pb-think-head">
                <span class="spinner" />
                <span class="pb-think-label">{{ currentPhaseLabel }}…</span>
                <span class="pb-think-time">{{ elapsed }}s</span>
              </div>
              <ul class="pb-think-steps">
                <li
                  v-for="p in PHASES"
                  :key="p.key"
                  :class="{
                    done: PHASES.findIndex((x) => x.key === phaseKey) > PHASES.findIndex((x) => x.key === p.key),
                    active: p.key === phaseKey,
                  }"
                >
                  <span class="dot" />{{ p.label }}
                </li>
              </ul>
              <p class="pb-think-hint">当前模型较慢，通常需要 1–2 分钟，请稍候…</p>
              <div v-if="streamBuf" class="pb-bubble streaming" v-html="renderMarkdown(stripJson(streamBuf))" />
            </div>
          </div>

          <p v-if="error" class="pb-error">{{ error }}</p>

          <!-- 选项气泡：可点击执行，标注推荐 -->
          <div v-if="!streaming && messages.length" class="pb-options">
            <button
              v-for="opt in messages[messages.length - 1]?.options || []"
              :key="opt.id"
              class="pb-option"
              :class="{ recommended: opt.recommended }"
              :disabled="busy"
              @click="runAction(opt)"
            >
              <span v-if="opt.recommended" class="rec-badge">推荐</span>
              {{ opt.label }}
            </button>
          </div>

          <div class="pb-input">
            <textarea
              v-model="userInput"
              rows="2"
              placeholder="也可以直接说你的想法，例如：把第二页改成图表、多加一页亮点…"
              @keydown.enter.exact.prevent="sendChat"
            />
            <button class="btn primary small" :disabled="streaming || !userInput.trim()" @click="sendChat">发送</button>
          </div>
        </section>

        <!-- 右：当前阶段工作区 -->
        <section class="pb-work">
          <template v-if="step === 'outline'">
            <div class="pb-work-head">
              <h3>大纲（可直接修改）</h3>
              <button class="btn ghost small" @click="addOutline">+ 加一页</button>
            </div>
            <div v-if="!outline.length" class="pb-empty">
              <p>还没有大纲。点下方按钮，AI 会基于统计数据给出建议页面结构。</p>
              <button class="btn primary" :disabled="streaming" @click="runStream('outline', '')">分析数据并生成大纲</button>
            </div>
            <div v-else class="pb-outline">
              <div v-for="(o, i) in outline" :key="o.id" class="pb-outline-item">
                <span class="pb-idx">{{ i + 1 }}</span>
                <div class="pb-outline-fields">
                  <input v-model="o.title" class="pb-in" placeholder="页标题" />
                  <select v-model="o.kind" class="pb-sel">
                    <option v-for="k in KIND_OPTIONS" :key="k.value" :value="k.value">{{ k.label }}</option>
                  </select>
                  <input v-model="o.note" class="pb-in note" placeholder="这页讲什么 / 用什么图" />
                </div>
                <div class="pb-outline-ops">
                  <button class="icon-btn" title="上移" @click="moveOutline(o.id, -1)">↑</button>
                  <button class="icon-btn" title="下移" @click="moveOutline(o.id, 1)">↓</button>
                  <button class="icon-btn danger" title="删除" @click="removeOutline(o.id)">×</button>
                </div>
              </div>
            </div>
            <div v-if="outline.length" class="pb-work-actions">
              <button class="btn ghost small" :disabled="streaming" @click="runStream('outline', '')">重新生成</button>
              <button class="btn primary" @click="step = 'copy'">确认大纲，下一步 →</button>
            </div>
          </template>

          <template v-else-if="step === 'copy'">
            <div class="pb-work-head"><h3>文案（可直接修改）</h3></div>
            <div v-if="!outline.length" class="pb-empty"><p>请先完成大纲。</p></div>
            <template v-else>
              <div class="pb-sections">
                <div v-for="s in sections" :key="s.id" class="pb-section">
                  <div class="pb-section-title">{{ s.title || '（未命名）' }}</div>
                  <textarea v-model="s.body" rows="3" placeholder="该页文案，留空则该页只展示标题" />
                </div>
              </div>
              <div class="pb-work-actions">
                <button class="btn ai small" :disabled="streaming" @click="runStream('copy', '')">AI 生成/润色文案</button>
                <button class="btn ghost small" @click="step = 'outline'">← 返回大纲</button>
                <button class="btn primary" @click="step = 'layout'">确认文案，下一步 →</button>
              </div>
            </template>
          </template>

          <template v-else-if="step === 'layout'">
            <div class="pb-work-head"><h3>排版与配色</h3></div>
            <p class="pb-hint">选主题配色（统计图表与表格会自动生成，无需手填）。</p>
            <div class="pb-themes">
              <button
                v-for="t in THEMES"
                :key="t.v"
                class="pb-theme"
                :class="[t.v, { on: theme === t.v }]"
                @click="theme = t.v"
              >
                <span class="swatch" />{{ t.n }}
              </button>
            </div>
            <div class="pb-work-actions">
              <button class="btn ghost small" :disabled="streaming" @click="runStream('layout', '')">让 AI 选配色并给建议</button>
              <button class="btn ghost small" @click="step = 'copy'">← 返回文案</button>
              <button class="btn primary" :disabled="busy || !canBuild" @click="doBuild">
                {{ busy ? '生成中…' : '生成 PPT →' }}
              </button>
            </div>
          </template>

          <template v-else>
            <div class="pb-work-head"><h3>导出</h3></div>
            <div v-if="resultUrl" class="pb-export">
              <p class="pb-ok">✓ PPT 已生成</p>
              <a class="btn primary" :href="pptDownloadUrl(resultUrl)" target="_blank" rel="noopener">下载 / 预览 PPT</a>
              <button class="btn ghost" @click="step = 'layout'">← 返回调整</button>
            </div>
            <div v-else class="pb-empty">
              <p>还没有生成。请先在大纲/文案确认后回到「排版」页生成。</p>
              <button class="btn ghost" @click="step = 'layout'">← 返回排版</button>
            </div>
          </template>
        </section>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ppt-builder-overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.42);
  z-index: 1300;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 3vh 2vw;
}
.ppt-builder {
  width: min(1180px, 96vw);
  height: min(820px, 94vh);
  background: var(--surface, #fff);
  border-radius: 18px;
  box-shadow: 0 24px 60px rgba(15, 23, 42, 0.3);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.pb-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 22px 12px;
  border-bottom: 1px solid var(--line, #e5e7eb);
}
.pb-head h2 { margin: 0; font-size: 18px; }
.pb-sub { margin: 2px 0 0; font-size: 12.5px; color: var(--ink-3, #94a3b8); }
.pb-close {
  border: none; background: transparent; font-size: 24px; line-height: 1;
  color: var(--ink-3, #94a3b8); cursor: pointer; border-radius: 8px; padding: 4px 10px;
}
.pb-close:hover { background: #f1f5f9; color: var(--ink, #0f172a); }
.pb-steps {
  list-style: none; display: flex; gap: 10px; margin: 0; padding: 12px 22px;
  border-bottom: 1px solid var(--line, #e5e7eb); background: #f8fafc;
}
.pb-step { display: flex; align-items: center; gap: 8px; flex: 1; opacity: 0.55; }
.pb-step.active { opacity: 1; }
.pb-step.done { opacity: 0.85; }
.pb-step-no {
  width: 24px; height: 24px; border-radius: 999px; flex: none;
  display: inline-flex; align-items: center; justify-content: center;
  background: #e2e8f0; color: #475569; font-size: 12px; font-weight: 700;
}
.pb-step.active .pb-step-no { background: linear-gradient(135deg, #6366f1, #06b6d4); color: #fff; }
.pb-step.done .pb-step-no { background: #10b981; color: #fff; }
.pb-step-txt { display: flex; flex-direction: column; }
.pb-step-txt b { font-size: 13px; }
.pb-step-txt em { font-size: 11px; color: var(--ink-3, #94a3b8); font-style: normal; }
.pb-body { flex: 1; display: grid; grid-template-columns: 42% 58%; min-height: 0; }
.pb-chat { border-right: 1px solid var(--line, #e5e7eb); display: flex; flex-direction: column; min-height: 0; }
.pb-msgs { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 10px; }
.pb-msg { display: flex; }
.pb-msg.user { justify-content: flex-end; }
.pb-bubble {
  max-width: 88%; padding: 10px 13px; border-radius: 12px; font-size: 13.5px;
  line-height: 1.6; word-break: break-word;
}
.pb-msg.assistant .pb-bubble { background: #f1f5f9; color: var(--ink, #0f172a); border-top-left-radius: 4px; }
.pb-msg.user .pb-bubble { background: linear-gradient(135deg, #6366f1, #06b6d4); color: #fff; border-top-right-radius: 4px; }
.pb-bubble :deep(p) { margin: 0 0 6px; }
.pb-bubble :deep(p:last-child) { margin-bottom: 0; }
.pb-bubble :deep(h1), .pb-bubble :deep(h2), .pb-bubble :deep(h3), .pb-bubble :deep(h4) {
  margin: 8px 0 4px; font-size: 14px; line-height: 1.4;
}
.pb-bubble :deep(ul), .pb-bubble :deep(ol) { margin: 4px 0; padding-left: 18px; }
.pb-bubble :deep(li) { margin: 2px 0; }
.pb-bubble :deep(code) {
  background: rgba(15, 23, 42, 0.08); padding: 1px 5px; border-radius: 5px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12.5px;
}
.pb-bubble :deep(pre.md-code) {
  background: #0f172a; color: #e2e8f0; padding: 10px 12px; border-radius: 8px;
  overflow-x: auto; margin: 6px 0;
}
.pb-bubble :deep(pre.md-code code) { background: transparent; color: inherit; padding: 0; }
.pb-bubble :deep(blockquote) {
  margin: 6px 0; padding: 4px 10px; border-left: 3px solid #c7d2fe; color: #475569;
}
.pb-msg.user .pb-bubble :deep(code) { background: rgba(255, 255, 255, 0.22); }
.pb-bubble.streaming { background: #eef2ff; margin-top: 8px; }
.pb-thinking {
  background: #f8fafc; border: 1px dashed #cbd5e1; border-radius: 12px; padding: 12px 14px;
}
.pb-think-head { display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 600; color: #4f46e5; }
.pb-think-time { margin-left: auto; color: #64748b; font-variant-numeric: tabular-nums; }
.spinner {
  width: 14px; height: 14px; border-radius: 50%;
  border: 2px solid #c7d2fe; border-top-color: #4f46e5; animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
.pb-think-steps { list-style: none; margin: 10px 0 6px; padding: 0; display: flex; flex-direction: column; gap: 4px; }
.pb-think-steps li { display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: #94a3b8; }
.pb-think-steps li .dot { width: 8px; height: 8px; border-radius: 50%; background: #cbd5e1; flex: none; }
.pb-think-steps li.active { color: #4f46e5; font-weight: 600; }
.pb-think-steps li.active .dot { background: #4f46e5; box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.15); }
.pb-think-steps li.done { color: #10b981; }
.pb-think-steps li.done .dot { background: #10b981; }
.pb-think-hint { margin: 4px 0 0; font-size: 11.5px; color: #94a3b8; }
.pb-error { margin: 0; padding: 8px 16px; color: #dc2626; font-size: 12.5px; background: #fef2f2; }
.pb-options { display: flex; flex-wrap: wrap; gap: 8px; padding: 8px 16px 4px; }
.pb-option {
  display: inline-flex; align-items: center; gap: 6px; border: 1px solid #c7d2fe;
  background: #fff; color: #4f46e5; border-radius: 999px; padding: 6px 14px;
  font-size: 12.5px; cursor: pointer; transition: all 0.15s;
}
.pb-option:hover { background: #eef2ff; }
.pb-option.recommended { background: linear-gradient(135deg, #6366f1, #06b6d4); color: #fff; border-color: transparent; }
.pb-option:disabled { opacity: 0.5; cursor: default; }
.rec-badge {
  background: rgba(255, 255, 255, 0.28); color: #fff; border-radius: 999px;
  padding: 0 6px; font-size: 10.5px; font-weight: 700;
}
.pb-input { border-top: 1px solid var(--line, #e5e7eb); padding: 10px 12px; display: flex; gap: 8px; align-items: flex-end; }
.pb-input textarea { flex: 1; resize: none; border: 1px solid var(--line, #e5e7eb); border-radius: 10px; padding: 8px 10px; font-size: 13px; font-family: inherit; }
.pb-work { padding: 16px 20px; overflow-y: auto; display: flex; flex-direction: column; min-height: 0; }
.pb-work-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.pb-work-head h3 { margin: 0; font-size: 15px; }
.pb-hint { color: var(--ink-3, #94a3b8); font-size: 12.5px; margin: 0 0 12px; }
.pb-empty { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 14px; color: var(--ink-3, #94a3b8); text-align: center; }
.pb-outline { display: flex; flex-direction: column; gap: 8px; }
.pb-outline-item { display: flex; gap: 10px; align-items: flex-start; border: 1px solid var(--line, #e5e7eb); border-radius: 10px; padding: 8px 10px; }
.pb-idx { width: 22px; height: 22px; border-radius: 6px; background: #eef2ff; color: #4f46e5; font-size: 12px; font-weight: 700; display: inline-flex; align-items: center; justify-content: center; flex: none; margin-top: 4px; }
.pb-outline-fields { flex: 1; display: flex; flex-direction: column; gap: 6px; }
.pb-in, .pb-sel { border: 1px solid var(--line, #e5e7eb); border-radius: 8px; padding: 6px 9px; font-size: 13px; font-family: inherit; }
.pb-in.note { color: #64748b; font-size: 12.5px; }
.pb-sel { width: 120px; }
.pb-outline-ops { display: flex; flex-direction: column; gap: 4px; }
.icon-btn { border: 1px solid var(--line, #e5e7eb); background: #fff; border-radius: 6px; width: 26px; height: 22px; cursor: pointer; font-size: 12px; color: #475569; }
.icon-btn.danger { color: #dc2626; }
.pb-work-actions { margin-top: auto; padding-top: 14px; display: flex; gap: 10px; justify-content: flex-end; flex-wrap: wrap; }
.pb-sections { display: flex; flex-direction: column; gap: 12px; }
.pb-section { border: 1px solid var(--line, #e5e7eb); border-radius: 10px; padding: 10px 12px; }
.pb-section-title { font-weight: 600; font-size: 13.5px; margin-bottom: 6px; }
.pb-section textarea { width: 100%; resize: vertical; border: 1px solid var(--line, #e5e7eb); border-radius: 8px; padding: 8px 10px; font-size: 13px; font-family: inherit; box-sizing: border-box; }
.pb-themes { display: flex; gap: 10px; }
.pb-theme { display: flex; align-items: center; gap: 8px; border: 1px solid var(--line, #e5e7eb); border-radius: 10px; padding: 10px 14px; background: #fff; cursor: pointer; font-size: 13px; }
.pb-theme .swatch { width: 16px; height: 16px; border-radius: 5px; }
.pb-theme.brand .swatch { background: #615fff; }
.pb-theme.cyan .swatch { background: #00b8db; }
.pb-theme.deep .swatch { background: #312e81; }
.pb-theme.on { border-color: #615fff; box-shadow: 0 0 0 3px rgba(97, 95, 255, 0.15); }
.pb-export { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 14px; }
.pb-ok { color: #10b981; font-weight: 700; font-size: 16px; }
</style>
