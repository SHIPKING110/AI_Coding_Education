<script setup lang="ts">
import { computed, ref, useTemplateRef, watch, nextTick } from 'vue'

import {
  buildPptAgent,
  getPptAgentTitles,
  initPptAgent,
  pptDownloadUrl,
  refinePptAgent,
  submitPptAgentOutline,
  type PptAgentInitOut,
  type PptAgentOutlineItem,
  type PptAgentOutlinePreviewItem,
} from '@/api/evaluation'
import { useAiTasksStore } from '@/stores/aiTasks'

const aiTasks = useAiTasksStore()

const open = ref(false)
const step = ref(0) // 0 init, 1 style, 2 title, 3 outline, 4 focus, 5 suggestion, 6 preview, 7 result
const sessionId = ref('')
const initData = ref<PptAgentInitOut | null>(null)
const busy = ref(false)
const error = ref('')

// Draft
const draft = ref<{
  style: string
  customStyleText: string
  title: string
  outline: PptAgentOutlineItem[]
  focus: string
  customFocus: string
  suggestion: string
  customSuggestion: string
}>({
  style: 'A',
  customStyleText: '',
  title: '',
  outline: [],
  focus: '',
  customFocus: '',
  suggestion: '',
  customSuggestion: '',
})

// Title options from LLM
const titleOpts = ref<string[]>([])

// Messages
const messages = ref<Array<{ role: 'agent' | 'user', text: string }>>([])

// Option UI
const picked = ref('')
const showCustom = ref(false)
const customText = ref('')

// Outline preview (step 6)
const outlinePreview = ref<PptAgentOutlinePreviewItem[]>([])

// Build result
const buildTaskId = ref('')
const buildRecord = ref<Record<string, unknown> | null>(null)
const refineText = ref('')
const refineBusy = ref(false)
const refineErr = ref('')

// Props for init
const initParams = ref<{ class_id: string; period_start: string; period_end: string } | null>(null)
const chatRef = useTemplateRef<HTMLElement>('chatRef')

// Agent 入口并入班级面板流程：面板内选好班级/周期后点「下一步：Agent 定制」打开本弹窗，
// 此时直接从 step 1 开始（跳过原独立入口的班级选择），关闭只关弹窗不关面板。

const curOptions = computed(() => {
  if (!initData.value) return []
  if (step.value === 1) return initData.value.style_options.map((o) => ({ id: o.id, label: o.label, desc: o.desc, hint: '' }))
  if (step.value === 2) return titleOpts.value.map((t, i) => ({ id: String.fromCharCode(65 + i), label: t, desc: '', hint: '' }))
  if (step.value === 4) return initData.value.focus_options.map((o) => ({ id: o.id, label: o.label, desc: o.hint, hint: '' }))
  if (step.value === 5) return initData.value.suggestion_options.map((o) => ({ id: o.id, label: o.label, desc: o.hint, hint: '' }))
  return []
})

const customPlaceholder = computed(() => {
  if (step.value === 1) return '例如：科技感+赛博霓虹、深色商务风'
  if (step.value === 2) return '输入你想要的标题，例如：编程小星球·夏季汇报'
  if (step.value === 4) return '例如：重点突出李明主动帮同学debug 的互助精神'
  if (step.value === 5) return '例如：每天15分钟亲子复盘、周末作品展示'
  return '输入你的要求后点「执行」'
})

/** 对话优化（agent-theme-chat）：话术带入真实班级数据，避免固定流程感 */
const classBrief = computed(() => {
  const d = initData.value
  if (!d) return ''
  const stats = (d.stats ?? {}) as Record<string, unknown>
  const sc = stats.student_count ?? '?'
  const rate = stats.avg_attendance_rate != null ? `${(Number(stats.avg_attendance_rate) * 100).toFixed(0)}%` : '—'
  const avgs = (d.averages ?? []).slice(0, 2).map(([n, v]) => `${n}${Number(v).toFixed(1)}`).join('、')
  const bits = [`${d.class_name}`, `${d.evaluated_count}份评估`, `在读${sc}人`, `出勤${rate}`]
  if (avgs) bits.push(avgs)
  return bits.join(' · ')
})

const agentHeaderSub = computed(() => {
  const base = '每步都有推荐选项，点 ABCD 即可，E 可自定义'
  return classBrief.value ? `${classBrief.value} · ${base}` : base
})

const stepTitle = computed(() => {
  const map: Record<number, string> = {
    1: '选择风格基调',
    2: '拟定标题',
    3: '定制大纲结构',
    4: '重点强调',
    5: '家长建议侧重',
    6: '大纲预览确认',
    7: '生成与预览',
  }
  return map[step.value] || 'Agent 定制'
})

const styleLabelOf = (v: string): string => {
  const id = (v || 'A').split(':')[0].trim()
  if (v.startsWith('custom:')) return `自定义：${draft.value.customStyleText || id}`
  return initData.value?.style_options.find((o) => o.id === id)?.label || id
}

/** 对话优化（agent-theme-chat）：Step6 预览显示已选风格/标题/重点摘要，可回跳修改 */
const confirmSummary = computed(() => {
  const parts: Array<{ k: string; v: string; back: number }> = []
  parts.push({ k: '风格', v: styleLabelOf(draft.value.style), back: 1 })
  if (draft.value.title) parts.push({ k: '标题', v: draft.value.title, back: 2 })
  if (draft.value.focus) parts.push({ k: '重点', v: draft.value.focus, back: 4 })
  if (draft.value.suggestion) parts.push({ k: '家长建议', v: draft.value.suggestion, back: 5 })
  return parts
})

function goBackTo(s: number) {
  step.value = s
}

const agentQuestion = computed(() => {
  if (step.value === 1) return classBrief.value
    ? `「${classBrief.value}」这次家长会想给家长什么感觉？选一个风格，下面会实时预览换肤效果，或点 E 自定义（如深色商务风）。`
    : '本次家长会想给家长什么感觉？选一个风格，或点 E 自定义。'
  if (step.value === 2) return '为你拟了 4 个标题，选一个最喜欢的，或点 E 自定义输入（标题只决定封面文字，不影响排版风格）。'
  if (step.value === 3) return '请选择需要的章节，可勾选/取消，拖动调整顺序。'
  if (step.value === 4) return classBrief.value
    ? `结合「${classBrief.value}」，想重点突出哪一块？选一个方向，或点 E 自由描述（可点名学员事例）。`
    : '想重点突出什么？选一个方向，或点 E 自定义。'
  if (step.value === 5) return '给家长的建议想偏向哪方面？'
  if (step.value === 6) return '这是按你的选择整理的大纲预览，确认后将按此生成精美 PPT。'
  if (step.value === 7) return 'PPT 已在后台生成中，完成后可在右侧预览与下载，也可继续对话微调。'
  return ''
})

const buildTask = computed(() => {
  if (!buildTaskId.value) return null
  return (aiTasks.tasks.find((t) => t.id === buildTaskId.value) as unknown as Record<string, unknown> | undefined) ?? null
})

const buildTaskStatus = computed(() => (buildTask.value as unknown as { status?: string } | null)?.status ?? '')
const buildTaskStage = computed(() => (buildTask.value as unknown as { stage?: string } | null)?.stage ?? '')
const buildTaskError = computed(() => (buildTask.value as unknown as { error?: string } | null)?.error ?? '')
/** Agent 风格真换肤（agent-theme-chat）：四套主题映射到弹窗渐变，与 PPT 调色板同源 */
const STYLE_THEMES: Record<string, { bg: string; chip: string }> = {
  A: { bg: 'linear-gradient(135deg, #7c2d12, #c2410c 55%, #f59e0b)', chip: '#fed7aa' },
  warm: { bg: 'linear-gradient(135deg, #7c2d12, #c2410c 55%, #f59e0b)', chip: '#fed7aa' },
  B: { bg: 'linear-gradient(135deg, #1e3a8a, #1d4ed8 55%, #0284c7)', chip: '#bfdbfe' },
  pro: { bg: 'linear-gradient(135deg, #1e3a8a, #1d4ed8 55%, #0284c7)', chip: '#bfdbfe' },
  C: { bg: 'linear-gradient(135deg, #6b21a8, #a855f7 55%, #ec4899)', chip: '#e9d5ff' },
  playful: { bg: 'linear-gradient(135deg, #6b21a8, #a855f7 55%, #ec4899)', chip: '#e9d5ff' },
  D: { bg: 'linear-gradient(135deg, #0f172a, #334155 60%, #64748b)', chip: '#e2e8f0' },
  minimal: { bg: 'linear-gradient(135deg, #0f172a, #334155 60%, #64748b)', chip: '#e2e8f0' },
}
function styleKeyOf(v: string): string {
  const k = (v || 'A').split(':')[0].trim().toLowerCase()
  // custom:xxx（如“深色商务风”）映射到 D 深色主题，弹窗换肤与 PPT 深色模式同源
  if (k === 'custom') return 'D'
  const m: Record<string, string> = { a: 'A', warm: 'warm', b: 'B', pro: 'pro', c: 'C', playful: 'playful', d: 'D', minimal: 'D' }
  return m[k] ?? 'A'
}
const agentTheme = computed(() => STYLE_THEMES[styleKeyOf(draft.value.style)] ?? STYLE_THEMES.A)
const agentThemeBg = computed(() => agentTheme.value.bg)
const buildRecordPptUrl = computed(() => String((buildRecord.value as Record<string, unknown> | null)?.ppt_url ?? ''))
const buildRecordTitle = computed(() => String((buildRecord.value as Record<string, unknown> | null)?.title ?? draft.value.title ?? '班级家长会 PPT'))
const buildDone = computed(() => buildTaskStatus.value === 'done')
const buildFailed = computed(() => buildTaskStatus.value === 'failed')
const buildRunning = computed(() => !!buildTask.value && !buildDone.value && !buildFailed.value)

const buildStageIndex = computed(() => {
  const st = buildTaskStatus.value
  if (!buildTask.value) return -1
  if (st === 'done') return 3
  if (st === 'failed') return -1
  const s = buildTaskStage.value || ''
  if (s.includes('排队')) return 0
  if (s.includes('排版')) return 2
  return 1
})

function pushAgent(text: string) {
  messages.value.push({ role: 'agent', text })
}

function pushUser(text: string) {
  messages.value.push({ role: 'user', text })
}

/** 打字机逐字渲染（agent-theme-chat）：标题/大纲等 AI 回复不再整段闪现，更像对话 */
let typeTimer: number | null = null
function typewriterTo(full: string) {
  if (typeTimer !== null) {
    window.clearInterval(typeTimer)
    typeTimer = null
  }
  const idx = messages.value.push({ role: 'agent', text: '' }) - 1
  let i = 0
  const step = full.length > 60 ? 2 : 1
  typeTimer = window.setInterval(() => {
    i = Math.min(full.length, i + step)
    messages.value[idx]!.text = full.slice(0, i)
    scrollChat()
    if (i >= full.length && typeTimer !== null) {
      window.clearInterval(typeTimer)
      typeTimer = null
    }
  }, 18)
}

async function start(params: { class_id: string; period_start: string; period_end: string }) {
  initParams.value = params
  open.value = true
  step.value = 0
  busy.value = true
  error.value = ''
  messages.value = []
  outlinePreview.value = []
  buildRecord.value = null
  buildTaskId.value = ''
  titleOpts.value = []
  draft.value = { style: 'A', customStyleText: '', title: '', outline: [], focus: '', customFocus: '', suggestion: '', customSuggestion: '' }
  try {
    const r = await initPptAgent({ class_id: params.class_id, period_start: params.period_start, period_end: params.period_end })
    initData.value = r
    sessionId.value = r.session_id
    draft.value.outline = r.outline_presets.map((o) => ({ ...o }))
    typewriterTo(`已加载「${r.class_name}」· ${r.evaluated_count}份评估已就绪。我们一步步定制你的家长会 PPT，先选风格吧。`)
    step.value = 1
  } catch (e: unknown) {
    const resp = (e as { response?: { status?: number; data?: unknown }; message?: string })?.response
    const d = (resp?.data as { detail?: string } | undefined)?.detail
    if (!resp) {
      error.value = '无法连接后端服务（8000）：请确认后端 uvicorn 已启动后重试'
    } else if (resp.status === 404) {
      error.value = typeof resp.data === 'string' ? `后端接口不存在（404）：${resp.data}` : (d || '后端接口不存在（404），请重启后端后再试')
    } else {
      error.value = d || '初始化失败，请重试'
    }
  } finally {
    busy.value = false
    await nextTick()
    scrollChat()
  }
}

function scrollChat() {
  const el = chatRef.value ?? document.querySelector('.agent-chat')
  if (el) el.scrollTop = el.scrollHeight
}

/** 对话优化（agent-theme-chat）：用户回车发送自定义后自动滚到底，避免对话堆在视口外 */
function afterChat() {
  customText.value = ''
  showCustom.value = false
  nextTick().then(scrollChat)
}

async function pick(id: string) {
  picked.value = id
  showCustom.value = false
  customText.value = ''

  if (step.value === 1) {
    const pickedLabel = initData.value?.style_options.find((o) => o.id === id)?.label || id
    pushUser(`已选 ${id}. ${pickedLabel}`)
    draft.value.style = id
    busy.value = true
    error.value = ''
    try {
      const r = await getPptAgentTitles({ session_id: sessionId.value, style: id })
      titleOpts.value = r.titles
      typewriterTo(`「${pickedLabel}」风格已定，排版会整套换肤，标题只决定封面文字。为你拟了 4 个标题，选一个最喜欢的，或点 E 自定义输入。`)
      step.value = 2
    } catch (e: unknown) {
      // 标题 AI 偶发超时也不阻塞流程：给本地兜底标题，仍可继续下一步
      const cn = initData.value?.class_name || '本班'
      titleOpts.value = [`${cn} 阶段学习汇报`, `看见每一次进步 · ${cn}`, `一起见证成长 · ${cn}`, `${cn} 家长会`]
      typewriterTo('AI 标题生成暂时超时，已给出 4 个推荐标题；也可点 E 自定义输入标题（标题不影响排版风格）。')
      step.value = 2
    } finally {
      busy.value = false
    }
  } else if (step.value === 2) {
    const idx = id.charCodeAt(0) - 65
    draft.value.title = titleOpts.value[idx] || ''
    pushUser(draft.value.title)
    typewriterTo('标题已定，只影响封面文字。接下来定制大纲：勾选需要的章节，可上下调整顺序。')
    step.value = 3
  } else if (step.value === 4) {
    const label = initData.value?.focus_options.find((o) => o.id === id)?.label || id
    draft.value.focus = label
    pushUser(`${id}. ${label}`)
    typewriterTo(`收到，生成时会重点讲「${label}」。最后一步：家长建议想偏向哪方面？`)
    step.value = 5
  } else if (step.value === 5) {
    const label = initData.value?.suggestion_options.find((o) => o.id === id)?.label || id
    draft.value.suggestion = label
    pushUser(`${id}. ${label}`)
    await goPreview()
  }
  await nextTick()
  scrollChat()
}

function pickCustom() {
  const v = customText.value.trim()
  if (!v) return
  if (step.value === 1) {
    draft.value.style = `custom:${v}`
    draft.value.customStyleText = v
    pushUser(`自定义风格：${v}`)
    busy.value = true
    getPptAgentTitles({ session_id: sessionId.value, style: `custom:${v}` }).then((r) => {
      titleOpts.value = r.titles
      typewriterTo('已按你的风格要求拟好标题，请选择或再自定义（标题只决定封面文字）。')
      step.value = 2
      busy.value = false
      nextTick().then(scrollChat)
    }).catch(() => {
      titleOpts.value = [v]
      step.value = 2
      busy.value = false
    })
  } else if (step.value === 2) {
    draft.value.title = v
    titleOpts.value = [v, ...titleOpts.value.slice(0, 3)]
    pushUser(`自定义标题：${v}`)
    typewriterTo('标题已定，只影响封面文字。接下来定制大纲。')
    step.value = 3
  } else if (step.value === 4) {
    draft.value.focus = v
    draft.value.customFocus = v
    pushUser(`自定义重点：${v}`)
    pushAgent('已记录。请选择家长建议侧重。')
    step.value = 5
  } else if (step.value === 5) {
    draft.value.suggestion = v
    draft.value.customSuggestion = v
    pushUser(`自定义建议：${v}`)
    goPreview()
  }
  afterChat()
}

function moveOutline(idx: number, dir: number) {
  const arr = draft.value.outline
  const next = idx + dir
  if (next < 0 || next >= arr.length) return
  const tmp = arr[idx]
  arr[idx] = arr[next]!
  arr[next] = tmp!
  // sync order
  arr.forEach((o, i) => (o.order = i))
}

async function goPreview() {
  busy.value = true
  error.value = ''
  try {
    const r = await submitPptAgentOutline({ session_id: sessionId.value, title: draft.value.title, outline: draft.value.outline })
    outlinePreview.value = r.preview
    step.value = 6
    typewriterTo(`大纲共 ${r.total} 页，已生成预览。确认风格/标题/重点无误后点击「生成精美 PPT」。`)
  } catch (e: unknown) {
    const d = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    error.value = d || '预览失败'
  } finally {
    busy.value = false
  }
}

async function build() {
  busy.value = true
  error.value = ''
  try {
    const task = await buildPptAgent({
      session_id: sessionId.value,
      title: draft.value.title,
      outline: draft.value.outline,
      focus: draft.value.focus || null,
      suggestion_pref: draft.value.suggestion || null,
    })
    buildTaskId.value = task.id
    aiTasks.register(task as unknown as Parameters<typeof aiTasks.register>[0], 'evaluation')
    step.value = 7
    pushAgent('已提交生成任务，可在右侧查看进度，完成后可预览与下载。')
  } catch (e: unknown) {
    const d = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    error.value = d || '提交失败'
  } finally {
    busy.value = false
  }
}

watch(
  () => buildTask.value,
  (t) => {
    if (!t) return
    const tt = t as unknown as { status?: string; result?: Record<string, unknown> }
    if (tt.status === 'done' && tt.result) {
      buildRecord.value = tt.result as Record<string, unknown>
    }
  },
  { deep: true },
)

async function doRefine() {
  const instruction = refineText.value.trim()
  if (!instruction || !buildRecord.value) return
  const recordId = String((buildRecord.value as Record<string, unknown>).record_id || '')
  if (!recordId) {
    refineErr.value = '暂无可微调的生成记录'
    return
  }
  refineBusy.value = true
  refineErr.value = ''
  try {
    const task = await refinePptAgent({ record_id: recordId, instruction })
    aiTasks.register(task as unknown as Parameters<typeof aiTasks.register>[0], 'evaluation')
    pushUser(instruction)
    pushAgent('已提交微调任务，完成后 PPT 将自动更新。')
    refineText.value = ''
  } catch (e: unknown) {
    const d = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    refineErr.value = d || '微调提交失败'
  } finally {
    refineBusy.value = false
  }
}

function prev() {
  if (step.value <= 1) return
  if (step.value === 7) {
    step.value = 6
    return
  }
  step.value -= 1
  if (step.value === 2 && titleOpts.value.length === 0) step.value = 1
}

function close() {
  open.value = false
}

defineExpose({ start })
</script>

<template>
  <Teleport to="body">
    <Transition name="confirm-fade">
      <div v-if="open" class="agent-mask" @click.self="close">
        <div class="agent-win" role="dialog" aria-modal="true" :data-theme="styleKeyOf(draft.style)">
          <div class="agent-header" :style="{ background: agentThemeBg }">
            <div class="agent-header-left">
              <span class="agent-spark">✨</span>
              <div>
                <strong>班级家长会 PPT · Agent 定制</strong>
                <p>{{ agentHeaderSub }}</p>
              </div>
            </div>
            <div class="agent-header-right">
              <span class="step-badge">Step {{ step }}/7 · {{ stepTitle }}</span>
              <button class="agent-close" title="关闭" @click="close">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12" /></svg>
              </button>
            </div>
          </div>

          <div class="agent-body">
            <!-- 左：对话 -->
            <div class="agent-left">
              <div class="agent-steps">
                <span v-for="i in 7" :key="i" class="agent-step-dot" :class="{ on: i === step, done: i < step }">{{ i }}</span>
              </div>

              <div ref="chatRef" class="agent-chat" @wheel.stop @touchmove.stop>
                <div class="chat-date">{{ initData ? `${initData.class_name} · ${initData.evaluated_count} 份评估` : '正在加载班级数据…' }}</div>
                <div v-for="(m, idx) in messages" :key="idx" class="bubble" :class="m.role">
                  <span class="bubble-role">{{ m.role === 'agent' ? 'Agent' : '你' }}</span>
                  <p>{{ m.text }}</p>
                </div>
                <div v-if="busy && step !== 7" class="bubble agent typing">
                  <span class="bubble-role">Agent</span>
                  <p><span class="typing-dots"><i></i><i></i><i></i></span> 正在思考…</p>
                </div>
                <div v-if="step > 0 && agentQuestion" class="bubble agent question">
                  <span class="bubble-role">Agent</span>
                  <p>{{ agentQuestion }}</p>
                </div>
              </div>

              <p v-if="error" class="agent-error">{{ error }}</p>

              <!-- 选项条：A-D 点选 + E 自定义 -->
              <div v-if="step === 1 || step === 2 || step === 4 || step === 5" class="agent-opts">
                <button
                  v-for="o in curOptions"
                  :key="o.id"
                  class="opt-chip"
                  :class="{ on: picked === o.id }"
                  type="button"
                  :disabled="busy"
                  @click="pick(o.id)"
                >
                  <span class="opt-id">{{ o.id }}</span>
                  <span class="opt-label">{{ o.label }}</span>
                  <small v-if="o.desc" class="opt-desc">· {{ o.desc }}</small>
                </button>
                <button
                  class="opt-chip custom"
                  :class="{ on: showCustom }"
                  type="button"
                  @click="showCustom = !showCustom"
                >
                  <span class="opt-id">E</span>
                  <span class="opt-label">✏️ 自定义输入</span>
                </button>
              </div>

              <div v-if="showCustom" class="agent-custom">
                <textarea v-autogrow v-model="customText" :placeholder="customPlaceholder" rows="2" @keydown.enter.exact.prevent="pickCustom" />
                <div class="agent-custom-actions">
                  <button class="c-btn ghost" type="button" @click="showCustom = false">取消</button>
                  <button class="c-btn brand" type="button" :disabled="!customText.trim()" @click="pickCustom">执行</button>
                </div>
                <p class="custom-hint">输入你的要求后点「执行」，效果等同选中一个推荐选项</p>
              </div>

              <div class="agent-nav">
                <button v-if="step > 1 && step < 7" class="c-btn ghost" type="button" @click="prev">上一步</button>
                <span class="agent-nav-hint">点 A-D 直接下一步，点 E 输入你的要求后执行</span>
              </div>
            </div>

            <!-- 右：预览 -->
            <div class="agent-right">
              <!-- Step 3 大纲编辑 -->
              <div v-if="step === 3" class="outline-edit">
                <h4>大纲结构</h4>
                <p class="outline-tip">勾选需要的章节，上下箭头调整顺序</p>
                <div class="outline-list">
                  <div v-for="(o, idx) in draft.outline" :key="o.key" class="outline-row" :class="{ off: !o.enabled }">
                    <label class="outline-check">
                      <input v-model="o.enabled" type="checkbox" />
                      <span class="outline-kicker">{{ o.kicker }}</span>
                      <input v-model="o.title" class="outline-title-input" :placeholder="o.title" />
                    </label>
                    <span class="outline-ops">
                      <button type="button" :disabled="idx === 0" @click="moveOutline(idx, -1)">↑</button>
                      <button type="button" :disabled="idx === draft.outline.length - 1" @click="moveOutline(idx, 1)">↓</button>
                    </span>
                  </div>
                </div>
                <button class="c-btn brand block" type="button" @click="goPreview">确认大纲，进入预览</button>
              </div>

              <!-- Step 6 预览确认 -->
              <div v-else-if="step === 6" class="outline-preview">
                <h4>大纲预览 · {{ outlinePreview.length }} 页</h4>
                <div class="confirm-summary">
                  <button
                    v-for="s in confirmSummary"
                    :key="s.k"
                    class="confirm-chip"
                    type="button"
                    :title="`返回修改${s.k}`"
                    @click="goBackTo(s.back)"
                  >
                    <span class="confirm-k">{{ s.k }}</span>
                    <strong>{{ s.v }}</strong>
                    <span class="confirm-back">改 ›</span>
                  </button>
                </div>
                <div class="preview-list">
                  <div v-for="(p, idx) in outlinePreview" :key="p.key" class="preview-card">
                    <span class="preview-idx">{{ idx + 1 }}</span>
                    <div class="preview-main">
                      <strong>{{ p.title }}</strong>
                      <small>{{ p.kicker }}</small>
                      <p>{{ p.desc }}</p>
                    </div>
                  </div>
                </div>
                <div class="preview-actions">
                  <button class="c-btn ghost" type="button" @click="prev">返回修改</button>
                  <button class="c-btn brand" type="button" :disabled="busy" @click="build">{{ busy ? '提交中…' : '生成精美 PPT' }}</button>
                </div>
              </div>

              <!-- Step 7 生成结果 + 二次编辑 -->
              <div v-else-if="step === 7" class="result-pane">
                <div v-if="buildRunning" class="result-progress">
                  <div class="p-steps">
                    <div v-for="(label, i) in ['排队等待','AI 提炼','排版生成','完成']" :key="label" class="p-step" :class="{ active: i === buildStageIndex, done: buildStageIndex > i }">
                      <span class="p-dot">{{ buildStageIndex > i ? '✓' : i+1 }}</span>
                      <span class="p-label">{{ label }}</span>
                    </div>
                  </div>
                  <p class="p-stage-text">{{ buildTaskStage || '准备中…' }}</p>
                  <button class="c-btn ghost" type="button" @click="aiTasks.cancel(buildTaskId)">取消任务</button>
                </div>
                <div v-else-if="buildFailed" class="result-error">
                  生成失败：{{ buildTaskError || '请重试' }}
                  <button class="c-btn brand" type="button" @click="prev">返回修改并重试</button>
                </div>
                <div v-else-if="buildTaskStatus === 'cancelled'" class="result-cancelled">
                  任务已取消，可返回上一步调整后重新生成，历史记录不受影响。
                  <button class="c-btn brand" type="button" @click="prev">返回上一步</button>
                </div>

                <div v-if="buildRecordPptUrl" class="result-card">
                  <span class="result-badge">已生成</span>
                  <div class="result-info">
                    <strong>{{ buildRecordTitle }}</strong>
                    <span>可预览与下载</span>
                  </div>
                  <a class="result-download" :href="pptDownloadUrl(buildRecordPptUrl)" target="_blank">下载 .pptx</a>
                </div>
                <div v-else-if="!buildTask" class="result-empty">点击「生成精美 PPT」后在此查看进度与下载</div>

                <div v-if="buildRecord" class="refine-box">
                  <h5>对话二次编辑</h5>
                  <p class="refine-tip">例如：把亮点第2条加上李明的例子 / 把封面副标题加“第二学期”</p>
                  <div class="refine-row">
                    <input v-model="refineText" placeholder="输入修改要求后回车或点发送" @keydown.enter="doRefine" />
                    <button class="c-btn brand" type="button" :disabled="refineBusy || !refineText.trim()" @click="doRefine">{{ refineBusy ? '提交中…' : '发送' }}</button>
                  </div>
                  <p v-if="refineErr" class="agent-error small">{{ refineErr }}</p>
                </div>

                <div class="result-outline-mini">
                  <h5>本次大纲</h5>
                  <div v-for="p in outlinePreview" :key="p.key" class="mini-card">
                    <span class="mini-kicker">{{ p.kicker }}</span>
                    <strong>{{ p.title }}</strong>
                  </div>
                </div>
              </div>

              <!-- Step 1/2/4/5 右侧：已选 + 右侧大纲缩略 -->
              <div v-else class="agent-right-placeholder">
                <div v-if="draft.title" class="chosen-title">
                  <small>已选标题</small>
                  <strong>{{ draft.title }}</strong>
                </div>
                <div v-if="draft.outline.length" class="mini-outline">
                  <h5>大纲 · {{ draft.outline.filter(o=>o.enabled).length }} 页</h5>
                  <div v-for="o in draft.outline.filter(x=>x.enabled)" :key="o.key" class="mini-card muted">
                    <span class="mini-kicker">{{ o.kicker }}</span>
                    <strong>{{ o.title }}</strong>
                  </div>
                </div>
                <p v-if="initData" class="placeholder-stats">
                  {{ initData.class_name }} · {{ initData.evaluated_count }}份评估 · {{ String((initData.stats as Record<string,unknown>)?.student_count ?? '') }}名学员
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.agent-mask {
  position: fixed;
  inset: 0;
  z-index: 130;
  background: rgba(15, 23, 42, 0.55);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
}

.agent-win {
  width: min(1160px, 96vw);
  height: min(760px, 94vh);
  background: var(--surface);
  border-radius: 18px;
  box-shadow: var(--shadow-lg);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.agent-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 18px;
  background: linear-gradient(135deg, #312e81, #0e7490);
  color: #fff;
}

.agent-header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.agent-header-left strong {
  font-size: 14.5px;
}

.agent-header-left p {
  font-size: 11.5px;
  opacity: 0.82;
  margin-top: 2px;
}

.agent-spark {
  width: 30px;
  height: 30px;
  border-radius: 9px;
  background: rgba(255, 255, 255, 0.18);
  display: flex;
  align-items: center;
  justify-content: center;
}

.step-badge {
  font-size: 11.5px;
  font-weight: 700;
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.18);
}

.agent-header-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.agent-close {
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.14);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}

.agent-close svg {
  width: 13px;
  height: 13px;
}

.agent-body {
  flex: 1;
  min-height: 0;
  display: flex;
  overflow: hidden;
}

.agent-left {
  flex: 1.25;
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--line);
  min-width: 0;
}

.agent-steps {
  display: flex;
  gap: 6px;
  padding: 10px 14px 6px;
}

.agent-step-dot {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 700;
  background: #e2e8f0;
  color: var(--ink-3);
}

.agent-step-dot.on {
  background: var(--agent-accent, linear-gradient(135deg, #6366f1, #06b6d4));
  color: #fff;
}

/* Agent 风格真换肤（agent-theme-chat）：四套主题变量，头图/气泡/选项同步换色 */
.agent-win[data-theme='A'], .agent-win[data-theme='warm'] { --agent-accent: linear-gradient(135deg, #c2410c, #f59e0b); --agent-chip: #ffedd5; --agent-ink: #9a3412; }
.agent-win[data-theme='B'], .agent-win[data-theme='pro'] { --agent-accent: linear-gradient(135deg, #1d4ed8, #0284c7); --agent-chip: #dbeafe; --agent-ink: #1e40af; }
.agent-win[data-theme='C'], .agent-win[data-theme='playful'] { --agent-accent: linear-gradient(135deg, #a855f7, #ec4899); --agent-chip: #f3e8ff; --agent-ink: #7e22ce; }
.agent-win[data-theme='D'], .agent-win[data-theme='minimal'] { --agent-accent: linear-gradient(135deg, #334155, #64748b); --agent-chip: #f1f5f9; --agent-ink: #334155; }

.agent-step-dot.done {
  background: var(--success-soft);
  color: #047857;
}

.agent-chat {
  flex: 1;
  overflow: auto;
  padding: 10px 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.bubble {
  max-width: 86%;
  padding: 9px 12px;
  border-radius: 12px;
  line-height: 1.5;
}

.bubble.agent {
  background: #eef2ff;
  color: #1e293b;
  border: 1px solid #c7d2fe;
}

.bubble.user {
  background: var(--agent-accent, linear-gradient(135deg, #6366f1, #06b6d4));
  color: #fff;
  align-self: flex-end;
}
.chat-date {
  align-self: center;
  font-size: 11px;
  color: var(--ink-3);
  background: var(--bg);
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 3px 12px;
}
.typing-dots { display: inline-flex; gap: 3px; margin-right: 4px; }
.typing-dots i { width: 6px; height: 6px; border-radius: 50%; background: currentColor; opacity: 0.4; animation: typing-blink 1s infinite; }
.typing-dots i:nth-child(2) { animation-delay: 0.2s; }
.typing-dots i:nth-child(3) { animation-delay: 0.4s; }
@keyframes typing-blink { 0%, 100% { opacity: 0.3; } 50% { opacity: 1; } }

.bubble.question {
  background: #f8fafc;
  border-color: var(--line);
}

.bubble-role {
  font-size: 10.5px;
  font-weight: 700;
  opacity: 0.7;
  display: block;
  margin-bottom: 2px;
}

.bubble p {
  font-size: 13px;
}

.typing p {
  opacity: 0.7;
}

.agent-error {
  margin: 6px 14px 0;
  font-size: 12px;
  color: var(--danger);
  background: var(--danger-soft);
  border-radius: 8px;
  padding: 7px 10px;
}

.agent-error.small {
  margin: 6px 0 0;
}

.agent-opts {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  padding: 10px 14px;
  border-top: 1px solid var(--line);
}

.opt-chip.on {
  border-color: var(--agent-ink, var(--brand));
  background: var(--agent-chip, var(--brand-soft));
  color: var(--agent-ink, var(--brand-strong));
}
.opt-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 7px 11px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: var(--surface);
  font-size: 12.5px;
  cursor: pointer;
  transition: all 0.15s;
}

.opt-chip:hover,
.opt-chip.on {
  border-color: #6366f1;
  background: #eef2ff;
  color: #4338ca;
}

.opt-chip.custom {
  border-style: dashed;
}

.opt-id {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: var(--brand-soft);
  color: var(--brand-strong);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 700;
}

.opt-chip.on .opt-id {
  background: #6366f1;
  color: #fff;
}

.opt-desc {
  color: var(--ink-3);
}

.agent-custom {
  margin: 0 14px 10px;
  padding: 10px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: #f8fafc;
}

.agent-custom textarea {
  width: 100%;
  border: 1px solid var(--line);
  border-radius: 9px;
  padding: 8px 10px;
  font-size: 13px;
  font-family: inherit;
  resize: none;
}

.agent-custom textarea:focus {
  outline: none;
  border-color: #6366f1;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.12);
}

.agent-custom-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 8px;
}

.custom-hint {
  font-size: 11px;
  color: var(--ink-3);
  margin-top: 6px;
}

.agent-nav {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 14px 12px;
  border-top: 1px solid var(--line);
}

.agent-nav-hint {
  font-size: 11.5px;
  color: var(--ink-3);
}

.agent-right {
  flex: 0.95;
  background: #f8fafc;
  overflow: auto;
  padding: 14px;
  min-width: 0;
}

.outline-edit h4,
.outline-preview h4,
.result-pane h5 {
  font-size: 13.5px;
  margin-bottom: 6px;
}

.outline-tip {
  font-size: 11.5px;
  color: var(--ink-3);
  margin-bottom: 10px;
}

.outline-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.outline-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 9px;
  border-radius: 9px;
  border: 1px solid var(--line);
  background: var(--surface);
}

.outline-row.off {
  opacity: 0.45;
}

.outline-check {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  min-width: 0;
}

.outline-kicker {
  font-size: 10px;
  font-weight: 700;
  color: var(--brand-strong);
  background: var(--brand-soft);
  padding: 2px 6px;
  border-radius: 999px;
}

.outline-title-input {
  flex: 1;
  min-width: 0;
  border: none;
  background: transparent;
  font-size: 12.5px;
  font-weight: 600;
}

.outline-title-input:focus {
  outline: none;
}

.outline-ops {
  display: flex;
  gap: 4px;
}

.outline-ops button {
  width: 24px;
  height: 24px;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: var(--surface);
  cursor: pointer;
}

.outline-ops button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.preview-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

/* Step6 确认摘要（agent-theme-chat）：已选风格/标题/重点可回跳修改 */
.confirm-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 10px;
}
.confirm-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: var(--agent-chip, var(--surface));
  font-size: 12px;
  cursor: pointer;
}
.confirm-chip strong {
  font-weight: 700;
  color: var(--agent-ink, var(--ink));
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.confirm-k {
  color: var(--ink-3);
  font-size: 11px;
}
.confirm-back {
  color: var(--agent-ink, var(--brand-strong));
  font-size: 11px;
  font-weight: 700;
}

.preview-card {
  display: flex;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid var(--line);
  background: var(--surface);
}

.preview-idx {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--brand-soft);
  color: var(--brand-strong);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 700;
  flex-shrink: 0;
}

.preview-main strong {
  font-size: 12.5px;
}

.preview-main small {
  font-size: 10px;
  color: var(--brand-strong);
  background: var(--brand-soft);
  padding: 1px 6px;
  border-radius: 999px;
  margin-left: 6px;
}

.preview-main p {
  font-size: 11.5px;
  color: var(--ink-3);
  margin-top: 3px;
}

.preview-actions {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}

.result-progress {
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 10px 12px;
  background: var(--surface);
  margin-bottom: 10px;
}

.p-steps {
  display: flex;
  gap: 8px;
}

.p-step {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

.p-dot {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #e2e8f0;
  color: var(--ink-3);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  font-weight: 700;
}

.p-step.active .p-dot {
  background: #6366f1;
  color: #fff;
}

.p-step.done .p-dot {
  background: var(--success-soft);
  color: #047857;
}

.p-label {
  font-size: 10.5px;
  color: var(--ink-3);
}

.p-stage-text {
  margin-top: 8px;
  font-size: 12px;
  color: var(--ink-2);
}

.result-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid #dbeafe;
  background: #eff6ff;
  margin-bottom: 10px;
}

.result-badge {
  font-size: 11px;
  font-weight: 700;
  padding: 3px 8px;
  border-radius: 999px;
  background: #dbeafe;
  color: #1d4ed8;
}

.result-info {
  flex: 1;
  min-width: 0;
}

.result-info strong {
  font-size: 12.5px;
  display: block;
}

.result-info span {
  font-size: 11px;
  color: var(--ink-3);
}

.result-download {
  padding: 7px 12px;
  border-radius: 9px;
  background: linear-gradient(135deg, #6366f1, #06b6d4);
  color: #fff;
  font-size: 12px;
  font-weight: 600;
  text-decoration: none;
}

.result-error {
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--danger-soft);
  color: var(--danger);
  font-size: 12px;
}

.refine-box {
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 10px 12px;
  background: var(--surface);
  margin-bottom: 10px;
}

.refine-tip {
  font-size: 11px;
  color: var(--ink-3);
  margin-bottom: 6px;
}

.refine-row {
  display: flex;
  gap: 8px;
}

.refine-row input {
  flex: 1;
  padding: 7px 10px;
  border: 1px solid var(--line);
  border-radius: 999px;
  font-size: 12.5px;
}

.refine-row input:focus {
  outline: none;
  border-color: #6366f1;
}

.result-outline-mini {
  border-top: 1px dashed var(--line);
  padding-top: 10px;
}

.result-cancelled {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  font-size: 12.5px;
  color: var(--ink-2);
  background: var(--bg);
  border: 1px dashed var(--line);
  border-radius: 10px;
  padding: 10px 12px;
  margin-bottom: 10px;
}
.progress-ops {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 10px;
}
.progress-ops-hint {
  font-size: 11.5px;
  color: var(--ink-3);
}

.mini-card {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 0;
  border-bottom: 1px solid #f1f5f9;
}

.mini-card strong {
  font-size: 12px;
}

.mini-kicker {
  font-size: 10px;
  font-weight: 700;
  color: var(--brand-strong);
  background: var(--brand-soft);
  padding: 2px 6px;
  border-radius: 999px;
}

.mini-card.muted strong {
  color: var(--ink-3);
}

.agent-right-placeholder {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.chosen-title small {
  font-size: 11px;
  color: var(--ink-3);
}

.chosen-title strong {
  display: block;
  margin-top: 4px;
  font-size: 13px;
}

.placeholder-stats {
  font-size: 11.5px;
  color: var(--ink-3);
}

.c-btn {
  padding: 7px 14px;
  border-radius: 9px;
  border: 1px solid var(--line);
  background: var(--surface);
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
}

.c-btn.brand {
  background: linear-gradient(135deg, #6366f1, #06b6d4);
  color: #fff;
  border-color: transparent;
}

.c-btn.ghost:hover {
  border-color: #6366f1;
  color: #4338ca;
}

.c-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.c-btn.block {
  width: 100%;
  margin-top: 10px;
}

@media (max-width: 860px) {
  .agent-win {
    height: 96vh;
  }
  .agent-body {
    flex-direction: column;
  }
  .agent-left {
    border-right: none;
    border-bottom: 1px solid var(--line);
  }
}
</style>
