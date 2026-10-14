<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import {
  agentChatStream,
  buildConversationPpt,
  createConversation,
  deleteConversation,
  deleteMemory,
  getConversationMaterial,
  getConversationMessages,
  listAgents,
  listConversations,
  listMemories,
  patchConversation,
  shareConversation,
  type AgentInfo,
  type AgentPhase,
  type AgentStage,
  type ChatMessage,
  type ChatOption,
  type ConversationOut,
  type MaterialItem,
} from '@/api/agent'
import { listLLMConfigs, type LLMConfigOut } from '@/api/llm'
import { toastApiError } from '@/stores/toast'
import { listClasses } from '@/api/enrollment'
import { listReports } from '@/api/report'
import {
  collectDoc,
  deleteDoc,
  listMyDocs,
  listPlaza,
  publishDoc,
  retryDoc,
  toggleDocSearch,
  uncollectDoc,
  unpublishDoc,
  uploadDoc,
  type KnowledgeDoc,
} from '@/api/knowledge'
import { renderMarkdown } from '@/utils/markdown'
import {
  createCustomAgent, createMcp, createSkill, deleteCustomAgent, deleteMcp, deleteSkill,
  getAgentGlobal, importSkillBundle, listCustomAgents, listMcps, listSkills, patchCustomAgent, patchMcp, patchSkill,
  getSandbox, previewSkillFile, putAgentGlobal, putSandbox, runSkillScript, testMcp, testSandbox, type AgentMcp, type AgentSkill, type CustomAgent,
} from '@/api/agentExt'

const route = useRoute()
const router = useRouter()

const tab = ref<'chat' | 'mine' | 'plaza' | 'mcp' | 'skill'>('chat')
const sideCollapsed = ref(false)
const agentDrop = ref(true)
const histDrop = ref(true)
const collapsedGroups = ref(new Set<string>())

function toggleGroup(g: string) {
  const s = new Set(collapsedGroups.value)
  if (s.has(g)) s.delete(g)
  else s.add(g)
  collapsedGroups.value = s
}
const agents = ref<AgentInfo[]>([])
const conversations = ref<ConversationOut[]>([])
const selectedAgent = ref('')
const activeConv = ref<ConversationOut | null>(null)
const messages = ref<{ role: string; content: string; citations?: Record<string, unknown> | null; options?: ChatOption[] | null; spec?: ChatMessage['spec'] }[]>([])
const streamBuf = ref('')
const streaming = ref(false)
const phaseLabel = ref('')
const input = ref('')
const useRagOnce = ref(false)
const error = ref('')
const memories = ref<{ id: string; key: string; value: string }[]>([])
const showMemory = ref(false)
const chatEl = ref<HTMLDivElement | null>(null)
const myDocs = ref<KnowledgeDoc[]>([])
const plazaDocs = ref<KnowledgeDoc[]>([])
const kbLoading = ref(false)
const kbError = ref('')
const upFile = ref<File | null>(null)
const upTitle = ref('')
const upDesc = ref('')
const uploading = ref(false)
const creating = ref(false)

const ICONS: Record<string, string> = {
  assistant: 'M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2zM8 9h8M8 12.5h5',
  report: 'M8 2v4M16 2v4M3 10h18M6 6h12a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2zM8 14h8M8 18h5',
  parents: 'M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75',
}
function iconOf(a: AgentInfo): string {
  return ICONS[a.icon] ?? 'M13 2 3 14h7l-1 8 10-12h-7l1-8z'
}

const currentAgent = computed(() => agents.value.find((a) => a.id === selectedAgent.value) || null)

const roadmap = computed<AgentStage[]>(() => currentAgent.value?.stages ?? [])

function stageIndex(key: string | undefined): number {
  return roadmap.value.findIndex((s) => s.key === key)
}

const currentStageIdx = computed(() => {
  const i = stageIndex(activeConv.value?.stage)
  return i >= 0 ? i : 0
})

function stepState(i: number): 'done' | 'current' | 'todo' {
  if (i < currentStageIdx.value) return 'done'
  if (i === currentStageIdx.value) return 'current'
  return 'todo'
}
const grouped = computed(() => {
  const map = new Map<string, ConversationOut[]>()
  for (const c of conversations.value.filter((c) => !selectedAgent.value || c.agent_id === selectedAgent.value)) {
    const ref = c.context_ref as Record<string, unknown>
    const g = String(ref?.title || ref?.id || ref?.class_id || '通用')
    if (!map.has(g)) map.set(g, [])
    map.get(g)!.push(c)
  }
  return [...map.entries()]
})

const readyDocs = computed(() => myDocs.value.filter((d) => d.status === 'ready').length)

onMounted(async () => {
  document.addEventListener('click', onDocClickForMenu)
  try {
    agents.value = await listAgents()
    conversations.value = await listConversations()
    await loadLLMConfigs()
  } catch {
    /* 列表失败不阻塞页面 */
  }
  const q = route.query as Record<string, string>
  if (q.agent) selectedAgent.value = q.agent
  else if (agents.value[0]) selectedAgent.value = agents.value[0].id
  if (q.context) {
    try {
      const ctx = JSON.parse(q.context)
      const agentId = q.agent || selectedAgent.value
      const conv = await createConversation({
        agent_id: agentId,
        context_ref: ctx,
        title: String(ctx.title || '新的对话'),
      })
      conversations.value = await listConversations()
      await openConversation(conv.id)
    } catch {
      /* ignore */
    }
    // 清掉 query：否则每次刷新页面都会按残留参数再建一个空白对话
    void router.replace({ name: 'agents' })
  }
  if (selectedAgent.value) void loadMemories()
})

onUnmounted(() => {
  stopKbPoll()
  document.removeEventListener('click', onDocClickForMenu)
})

watch(selectedAgent, () => void loadMemories())

async function loadMemories() {
  if (!selectedAgent.value) return
  try {
    memories.value = await listMemories(selectedAgent.value)
  } catch {
    memories.value = []
  }
}

let openSeq = 0

async function openConversation(id: string) {
  // 切走前：若当前会话一条消息都没有（空对话组），直接删除，不留空记录
  await abandonIfEmpty(id)
  const seq = ++openSeq
  const conv = conversations.value.find((c) => c.id === id) || null
  activeConv.value = conv
  messages.value = []
  outlineDirty.value = false
  sectionDirty.value = false
  sectionPreview.value = []
  pptResult.value = null
  wsError.value = ''
  pptTitle.value = ''
  material.value = []
  if (!conv) return
  selectedAgent.value = conv.agent_id
  const res = await getConversationMessages(id)
  if (seq !== openSeq) return // 已切到别的会话：丢弃过期响应，避免串话与错误吸底
  if (res.conversation?.stage) conv.stage = res.conversation.stage
  messages.value = res.items.map((m) => ({
    role: m.role, content: stripJsonBlocks(m.content), citations: m.citations,
    options: m.options ?? null, spec: m.spec ?? null,
  }))
  // 工作区同步：素材 + 大纲草稿（如用户没在编辑则跟随最新规格）
  void loadMaterial()
  syncOutlineDraft()
  await scrollBottom()
}

/* —— 工作区（大纲预览编辑 / 素材引用 / 成果生成） —— */
const wsOpen = ref(true)
const wsTab = ref<'outline' | 'material' | 'result'>('outline')
const material = ref<MaterialItem[]>([])
const outlineDraft = ref<{ id?: string; title: string; kind?: string; note?: string }[]>([])
const outlineDirty = ref(false)
const pptTheme = ref('brand')
const pptTitle = ref('')
const building = ref(false)
const pptResult = ref<{ ppt_url: string; download: string; pages: number; theme: string } | null>(null)
const wsError = ref('')

const latestSpec = computed(() => {
  // 多条消息的规格合并（新者优先）：大纲消息只有 outline，文案消息只有 sections
  const merged: NonNullable<ChatMessage['spec']> = {}
  for (let i = messages.value.length - 1; i >= 0; i--) {
    const s = messages.value[i].spec
    if (!s) continue
    for (const k of ['outline', 'sections', 'theme', 'slides'] as const) {
      const v = (s as Record<string, unknown>)[k]
      if (!(merged as Record<string, unknown>)[k] && v) (merged as Record<string, unknown>)[k] = v
    }
    if (merged.outline && merged.sections) break
  }
  return merged.outline || merged.sections ? merged : null
})

const usedCitations = computed(() => {
  const seen = new Map<string, { title: string; text: string; similarity?: number }>()
  for (const m of messages.value) {
    for (const c of citationsOf(m)) {
      const k = `${c.title}::${c.text.slice(0, 60)}`
      if (!seen.has(k)) seen.set(k, c)
    }
  }
  return [...seen.values()].slice(0, 20)
})

function syncOutlineDraft() {
  if (outlineDirty.value) return
  const ol = latestSpec.value?.outline ?? []
  // 新规格没有大纲时保留旧草稿（文案/排版阶段只带 sections，不能把工作区清空）
  if (ol.length) {
    outlineDraft.value = ol.map((o, i) => ({
      id: String(o.id ?? `p${i + 1}`), title: String(o.title ?? `第 ${i + 1} 页`),
      kind: String(o.kind ?? 'bullets'), note: String(o.note ?? ''),
    }))
  }
  const secs = latestSpec.value?.sections ?? []
  if (secs.length && !sectionDirty.value) {
    sectionPreview.value = secs.slice(0, 20).map((s) => ({
      id: s.id != null ? String(s.id) : undefined,
      title: String(s.title ?? ''),
      body: Array.isArray(s.body) ? (s.body as unknown[]).map((x) => String(x)).join('\n') : String((s.body ?? '') as unknown),
      open: false,
    }))
  }
  if (!pptTitle.value && activeConv.value) pptTitle.value = activeConv.value.title
  const t = latestSpec.value?.theme
  if (typeof t === 'string' && ['brand', 'cyan', 'deep'].includes(t)) pptTheme.value = t
}

const sectionPreview = ref<{ id?: string; title: string; body: string; open: boolean }[]>([])
const sectionDirty = ref(false)

function markSectionDirty() {
  sectionDirty.value = true
}

function sendSectionsToAgent() {
  if (!sectionPreview.value.length || streaming.value) return
  const lines = sectionPreview.value.map((s, i) => `${i + 1}. ${s.title}\n${s.body}`.trim())
  sectionDirty.value = false
  void send({
    text: `我已修改文案（共 ${sectionPreview.value.length} 页），请按此文案继续排版：\n${lines.join('\n\n')}`,
    stage: activeConv.value?.stage ?? 'chat',
  })
}

async function loadMaterial() {
  if (!activeConv.value) return
  try {
    const res = await getConversationMaterial(activeConv.value.id)
    material.value = res.items
  } catch {
    material.value = []
  }
}

/* —— 工作台内直接选取素材（报告 / 班级），支持筛选 + 多选 —— */
const matPicking = ref(false)
const matLoading = ref(false)
const reportOptions = ref<{
  id: string; title: string; type: string; period: string; start: string; end: string
}[]>([])
const classOptions = ref<{ id: string; name: string }[]>([])
const pickReportIds = ref<string[]>([])
const pickClassId = ref('')

/* 筛选：时间范围 + 报告类型 */
const matType = ref('')
const matStart = ref('')
const matEnd = ref('')
const REPORT_TYPES = [
  { value: '', label: '全部类型' },
  { value: 'daily', label: '日报' },
  { value: 'weekly', label: '周报' },
  { value: 'quarterly', label: '季度总结' },
  { value: 'yearly', label: '年度总结' },
]

const filteredReports = computed(() => {
  return reportOptions.value.filter((r) => {
    if (matType.value && r.type !== matType.value) return false
    // 期间与筛选窗口有交集即保留（报告 [start,end] 与 [matStart,matEnd] 相交）
    if (matStart.value && r.end && r.end < matStart.value) return false
    if (matEnd.value && r.start && r.start > matEnd.value) return false
    return true
  })
})

const allFilteredSelected = computed(
  () => filteredReports.value.length > 0
    && filteredReports.value.every((r) => pickReportIds.value.includes(r.id)),
)

function toggleReportPick(id: string) {
  const arr = [...pickReportIds.value]
  const i = arr.indexOf(id)
  if (i >= 0) arr.splice(i, 1)
  else arr.push(id)
  pickReportIds.value = arr
}

function toggleSelectAllFiltered() {
  if (allFilteredSelected.value) {
    const ids = new Set(filteredReports.value.map((r) => r.id))
    pickReportIds.value = pickReportIds.value.filter((id) => !ids.has(id))
  } else {
    const set = new Set(pickReportIds.value)
    for (const r of filteredReports.value) set.add(r.id)
    pickReportIds.value = [...set]
  }
}

function resetMatFilters() {
  matType.value = ''
  matStart.value = ''
  matEnd.value = ''
}

function fmtDate(v: unknown): string {
  if (!v) return ''
  const s = String(v)
  return s.length >= 10 ? s.slice(0, 10) : s
}

async function openMatPicker() {
  if (!activeConv.value) return
  matPicking.value = true
  matLoading.value = true
  resetMatFilters()
  try {
    if (activeConv.value.agent_id === 'report_ppt') {
      const res = await listReports({ mine: true, limit: 100 })
      reportOptions.value = (res.items ?? []).map((r) => ({
        id: r.id, title: r.title || '未命名报告', type: String(r.type ?? ''),
        period: `${fmtDate(r.period_start)} ~ ${fmtDate(r.period_end)}`,
        start: fmtDate(r.period_start), end: fmtDate(r.period_end),
      }))
      // 预选当前已绑定的报告
      const ref = activeConv.value.context_ref as Record<string, unknown>
      const cur = ref?.ids
      if (Array.isArray(cur)) pickReportIds.value = cur.map((x) => String(x))
      else if (ref?.id) pickReportIds.value = [String(ref.id)]
      else pickReportIds.value = []
    } else {
      const res = await listClasses({ limit: 100 })
      classOptions.value = (res.items ?? []).map((c) => ({ id: c.id, name: c.name }))
    }
  } catch (e: unknown) {
    wsError.value = e instanceof Error ? e.message : '素材列表加载失败'
  } finally {
    matLoading.value = false
  }
}

async function confirmMatPick() {
  if (!activeConv.value) return
  wsError.value = ''
  try {
    if (activeConv.value.agent_id === 'report_ppt') {
      const picked = reportOptions.value.filter((r) => pickReportIds.value.includes(r.id))
      if (!picked.length) return
      const ref: Record<string, unknown> = {
        kind: 'report',
        ids: picked.map((r) => r.id),
        id: picked[0].id,
        title: picked.map((r) => r.title).join('、'),
        reports: picked.map((r) => ({ id: r.id, title: r.title, type: r.type, period: r.period })),
      }
      await patchConversation(activeConv.value.id, { context_ref: ref })
      activeConv.value.context_ref = ref
    } else {
      const c = classOptions.value.find((x) => x.id === pickClassId.value)
      if (!c) return
      const ref = { kind: 'class_ppt', class_id: c.id, title: c.name }
      await patchConversation(activeConv.value.id, { context_ref: ref })
      activeConv.value.context_ref = ref
    }
    matPicking.value = false
    await loadMaterial()
  } catch (e: unknown) {
    wsError.value = e instanceof Error ? e.message : '素材绑定失败'
  }
}

function outlineMove(i: number, dir: -1 | 1) {
  const j = i + dir
  if (j < 0 || j >= outlineDraft.value.length) return
  const arr = [...outlineDraft.value]
  ;[arr[i], arr[j]] = [arr[j], arr[i]]
  outlineDraft.value = arr
  outlineDirty.value = true
}

function outlineAdd() {
  outlineDraft.value = [...outlineDraft.value, { id: `p${Date.now()}`, title: '新建页面', kind: 'bullets', note: '' }]
  outlineDirty.value = true
}

function sendOutlineToAgent() {
  if (!outlineDraft.value.length || streaming.value) return
  const lines = outlineDraft.value.map((o, i) => `${i + 1}. ${o.title}${o.note ? `（${o.note}）` : ''}`)
  const keys = (currentAgent.value?.stages ?? []).map((s) => s.key)
  const stage = keys.includes('outline_confirm') ? 'outline_confirm' : (keys.includes('outline') ? 'outline' : (activeConv.value?.stage ?? 'chat'))
  outlineDirty.value = false
  void send({
    text: `我已审核并调整了大纲（共 ${outlineDraft.value.length} 页），请按此大纲继续：\n${lines.join('\n')}`,
    stage,
  })
}

async function doBuildPpt(fromOption?: { label: string; theme?: string }) {
  if (!activeConv.value || building.value) return
  if (fromOption?.theme && ['brand', 'cyan', 'deep'].includes(fromOption.theme)) {
    pptTheme.value = fromOption.theme
  }
  // 选项触发的真实生成：先在对话里留一条用户操作记录，再生成
  if (fromOption) {
    messages.value.push({ role: 'user', content: fromOption.label })
    await scrollBottom()
  }
  building.value = true
  wsError.value = ''
  try {
    pptResult.value = await buildConversationPpt(activeConv.value.id, {
      title: pptTitle.value.trim() || undefined,
      theme: pptTheme.value,
      outline: outlineDraft.value.length ? outlineDraft.value : undefined,
      sections: sectionDirty.value
        ? sectionPreview.value.map((s) => ({ id: s.id, title: s.title, body: s.body }))
        : undefined,
    })
    wsTab.value = 'result'
    wsOpen.value = true
    // 对话里同步一条可下载的结果消息：去向明确，不再"不知道去哪下"
    messages.value.push({
      role: 'assistant',
      content: `已生成 PPT（${pptResult.value.theme} 主题，共 ${pptResult.value.pages} 页）。[点击下载 .pptx](${pptResult.value.download})`,
      options: null,
    })
    await scrollBottom()
  } catch (e: unknown) {
    const axiosMsg = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
    wsError.value = (typeof axiosMsg === 'string' && axiosMsg) || (e instanceof Error ? e.message : '生成 PPT 失败')
    messages.value.push({
      role: 'assistant',
      content: `生成 PPT 失败：${wsError.value}。可在右侧工作区「成果」页重试。`,
      options: null,
    })
  } finally {
    building.value = false
  }
}

async function newConversation() {
  if (!selectedAgent.value || creating.value) return
  creating.value = true
  error.value = ''
  try {
    // 新建前先清理空对话：只保留一个空对话组，空的不落库
    await abandonIfEmpty()
    const conv = await createConversation({ agent_id: selectedAgent.value, context_ref: {}, title: '新的对话' })
    conversations.value = await listConversations()
    await openConversation(conv.id)
    tab.value = 'chat'
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : '新建对话失败'
  } finally {
    creating.value = false
  }
}

/** 删除空会话（零消息）：exceptId 指定的除外；静默执行，失败不打扰 */
async function abandonIfEmpty(exceptId?: string) {
  const id = activeConv.value?.id
  if (!id || id === exceptId || messages.value.length > 0) return
  try {
    await deleteConversation(id)
    conversations.value = conversations.value.filter((c) => c.id !== id)
  } catch {
    /* 忽略，后台定时/下次进入再清 */
  }
  activeConv.value = null
  messages.value = []
}

async function removeConversation(id: string) {
  await deleteConversation(id)
  conversations.value = conversations.value.filter((c) => c.id !== id)
  if (activeConv.value?.id === id) {
    activeConv.value = null
    messages.value = []
  }
}

/* —— 对话更多操作：重命名 / 置顶 / 分享 / 多选 / 删除 —— */
const menuId = ref<string | null>(null)
const menuStyle = ref<Record<string, string>>({})
const renamingId = ref<string | null>(null)
const renameText = ref('')
const multiMode = ref(false)
const selectedIds = ref(new Set<string>())

function toggleMenu(id: string, e: MouseEvent) {
  if (menuId.value === id) {
    menuId.value = null
    return
  }
  openMenuAt(id, e.currentTarget as HTMLElement)
}

function openMenuAt(id: string, el: HTMLElement | null) {
  if (!el) return
  const r = el.getBoundingClientRect()
  menuStyle.value = {
    left: `${Math.min(r.left, window.innerWidth - 160)}px`,
    top: `${r.bottom + 6}px`,
  }
  menuId.value = id
}

/** 鼠标悬停「更多操作」图标即自动展开对应功能栏 */
function hoverMenu(id: string, e: MouseEvent) {
  if (menuId.value === id) return
  openMenuAt(id, e.currentTarget as HTMLElement)
}

/** 点击其它区域（菜单与触发图标之外）收起功能栏 */
function onDocClickForMenu(e: MouseEvent) {
  if (!menuId.value) return
  const t = e.target as HTMLElement
  if (t.closest('.conv-menu') || t.closest('.conv-more')) return
  menuId.value = null
}

function onConvRowClick(c: ConversationOut, e: MouseEvent) {
  menuId.value = null
  if (multiMode.value) {
    toggleSelect(c.id)
    return
  }
  if ((e.target as HTMLElement).closest('input')) return
  void openConversation(c.id)
}

function startRename(c: ConversationOut) {
  renamingId.value = c.id
  renameText.value = c.title
  menuId.value = null
}

async function confirmRename(c: ConversationOut) {
  const t = renameText.value.trim().slice(0, 40)
  renamingId.value = null
  if (!t || t === c.title) return
  await patchConversation(c.id, { title: t })
  c.title = t
  if (activeConv.value?.id === c.id) activeConv.value.title = t
}

async function togglePin(c: ConversationOut) {
  menuId.value = null
  await patchConversation(c.id, { pinned: !c.pinned })
  conversations.value = await listConversations()
}

async function shareConv(c: ConversationOut) {
  menuId.value = null
  try {
    const { path } = await shareConversation(c.id)
    const url = `${window.location.origin}${path}`
    try {
      await navigator.clipboard.writeText(url)
      alert(`分享链接已复制：\n${url}`)
    } catch {
      alert(`分享链接：\n${url}`)
    }
  } catch (e: unknown) {
    alert(e instanceof Error ? e.message : '生成分享链接失败')
  }
}

function enterMulti() {
  menuId.value = null
  multiMode.value = true
  selectedIds.value = new Set()
}

function toggleSelect(id: string) {
  const s = new Set(selectedIds.value)
  if (s.has(id)) s.delete(id)
  else s.add(id)
  selectedIds.value = s
}

async function batchPin() {
  for (const id of selectedIds.value) {
    try {
      await patchConversation(id, { pinned: true })
    } catch {
      /* 单条失败跳过 */
    }
  }
  multiMode.value = false
  conversations.value = await listConversations()
}

async function batchDelete() {
  for (const id of selectedIds.value) {
    try {
      await deleteConversation(id)
    } catch {
      /* 单条失败跳过 */
    }
  }
  multiMode.value = false
  conversations.value = conversations.value.filter((c) => !selectedIds.value.has(c.id))
  if (activeConv.value && selectedIds.value.has(activeConv.value.id)) {
    activeConv.value = null
    messages.value = []
  }
}

async function removeMemory(id: string) {
  await deleteMemory(id)
  memories.value = memories.value.filter((m) => m.id !== id)
}

const SPEC_KEYS = ['options', 'outline', 'sections', 'theme', 'slides']

function isAgentPayloadBlock(body: string): boolean {
  // 只有可解析、且含 Agent 载荷键的 json 块才剥离（按钮/工作区由结构化字段渲染）；
  // 普通代码示例原样保留显示
  try {
    const data = JSON.parse(body)
    return !!data && typeof data === 'object' && SPEC_KEYS.some((k) => (data as Record<string, unknown>)[k] !== undefined)
  } catch {
    return /"(options|outline|sections|theme|slides)"\s*:/.test(body)
  }
}

function stripJsonBlocks(content: string): string {
  // 历史消息与流式输出夹带的 Agent 载荷块统一剥离；普通 ``` 代码块保留显示
  let stripped = (content || '').replace(/```json\s*([\s\S]*?)```/g, (m, body: string) =>
    isAgentPayloadBlock(body) ? '' : m,
  )
  // 模型偶发的不带围栏的裸 JSON 动作块（如 {"message": ..., "action": {...}}）同样剥离
  stripped = stripped.replace(/\{[^{}]*"action"\s*:\s*\{[^{}]*\}[^{}]*\}/g, (m) =>
    isAgentPayloadBlock(m) ? '' : m,
  )
  return stripped.trim() || content
}

function stripPartialJson(content: string): string {
  // 流式进行中代码块可能还没闭合：Agent 载荷类（即使未闭合）也隐藏，避免屏闪 JSON
  const stripped = (content || '').replace(/```json\s*([\s\S]*?)(```|$)/g, (m, body: string) =>
    isAgentPayloadBlock(body) ? '' : m,
  )
  return stripped.trim()
}

async function scrollBottom() {
  await nextTick()
  await nextTick()
  snapToBottom()
  // markdown 异步撑高 / 连续渲染时多次确认，直到真正吸底
  await new Promise((r) => setTimeout(r, 200))
  snapToBottom()
  await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))
  snapToBottom()
}

function snapToBottom() {
  const el = chatEl.value
  if (!el) return
  // 直接按容器滚动（不受整页滚动干扰），并校验是否真的到底
  el.scrollTop = el.scrollHeight
  if (el.scrollHeight - el.scrollTop - el.clientHeight > 2) {
    const last = el.querySelector('.msg:last-child') as HTMLElement | null
    if (last) last.scrollIntoView({ block: 'end' })
    el.scrollTop = el.scrollHeight
  }
}

const llmConfigs = ref<LLMConfigOut[]>([])
const activeConfigId = ref<string | null>(null)
async function loadLLMConfigs() {
  try {
    const r = await listLLMConfigs()
    llmConfigs.value = r.items
  } catch {
    llmConfigs.value = []
  }
}
const abortCtrl = ref<AbortController | null>(null)
const lastSend = ref<{ text: string; stage: string } | null>(null)

function pauseStream() {
  abortCtrl.value?.abort()
}

function retryLast() {
  if (!lastSend.value || streaming.value) return
  void send({ text: lastSend.value.text, stage: lastSend.value.stage })
}

async function send(preset?: { text: string; stage?: string }) {
  const text = preset?.text ?? input.value.trim()
  if (!text || !activeConv.value || streaming.value) return
  const targetStage = preset?.stage ?? activeConv.value.stage ?? 'chat'
  if (!preset) input.value = ''
  error.value = ''
  // 记录最后一次发送：失败/超时后可一键重试
  lastSend.value = { text, stage: targetStage }
  messages.value.push({ role: 'user', content: text })
  streaming.value = true
  streamBuf.value = ''
  phaseLabel.value = '准备中'
  await scrollBottom()
  let full = ''
  let timedOut = false
  let doneOptions: ChatOption[] | undefined
  let doneStage: string | undefined
  let doneHasSpec = false
  let doneTitle: string | undefined
  let doneToolTrace: { seq: number; tool: string; args: Record<string, unknown>; ok: boolean; summary: string; error?: string | null }[] | undefined
  let doneToolRounds = 0
  let doneToolDegraded = false
  let doneMcpTrace: { step: string; ok: boolean; ms: number; detail: string }[] | undefined
    if (llmConfigs.value.length === 0) await loadLLMConfigs()
  const once = useRagOnce.value
  useRagOnce.value = false
  abortCtrl.value?.abort()
  const ctrl = new AbortController()
  abortCtrl.value = ctrl
  try {
    await agentChatStream(
      activeConv.value.id,
      { stage: targetStage, message: text, state: {}, ...(once ? { use_rag: true } : {}), ...(activeConfigId.value ? { config_id: activeConfigId.value } : {}) },
      (d) => {
        full += d
        streamBuf.value = full
        scrollBottom()
      },
      ctrl.signal,
      (p: AgentPhase) => {
        phaseLabel.value = p.label
      },
      (info) => {
        doneOptions = info.options
        doneStage = info.stage
        doneHasSpec = !!info.has_spec
        doneTitle = info.title
        doneToolTrace = info.tool_trace
        doneToolRounds = info.tool_rounds ?? 0
        doneToolDegraded = !!info.tool_degraded
        doneMcpTrace = info.mcp_trace
      },
      {
        idleTimeoutMs: 90000,
        onTimeout: () => {
          timedOut = true
        },
      },
    )
    if (doneStage && activeConv.value) {
      activeConv.value.stage = doneStage
      const found = conversations.value.find((c) => c.id === activeConv.value!.id)
      if (found) found.stage = doneStage
    }
    // 后端首轮自动拟标题：同步到当前会话与列表
    if (doneTitle && activeConv.value) {
      activeConv.value.title = doneTitle
      const found = conversations.value.find((c) => c.id === activeConv.value!.id)
      if (found) found.title = doneTitle
    }
    messages.value.push({
      role: 'assistant',
      content: stripJsonBlocks(full),
      options: doneOptions ?? null,
      spec: null,
      citations: (doneToolTrace?.length || doneMcpTrace?.length)
        ? { tools: doneToolTrace, rounds: doneToolRounds, degraded: doneToolDegraded, mcp_trace: doneMcpTrace }
        : undefined,
    })
    if (timedOut) {
      error.value = '连接中断（90 秒无任何响应，含服务端心跳），已保留已生成的内容；可点重试继续'
    }
    if (doneHasSpec && activeConv.value) {
      // 新规格落库后回填（含 outline/sections），工作区随之更新
      try {
        const res = await getConversationMessages(activeConv.value.id)
        messages.value = res.items.map((m) => ({
          role: m.role, content: stripJsonBlocks(m.content), citations: m.citations,
          options: m.options ?? null, spec: m.spec ?? null,
        }))
      } catch {
        /* 保持本地消息 */
      }
    }
    syncOutlineDraft()
  } catch (e: unknown) {
    if (ctrl.signal.aborted) {
      // 用户手动暂停：保留已输出的片段，不报错
      if (full.trim()) {
        messages.value.push({
          role: 'assistant', content: stripJsonBlocks(full), options: doneOptions ?? null,
          citations: (doneToolTrace?.length || doneMcpTrace?.length) ? { tools: doneToolTrace, rounds: doneToolRounds, mcp_trace: doneMcpTrace } : undefined,
        })
      }
    } else {
      error.value = e instanceof Error ? e.message : 'AI 对话失败'
      try { toastApiError(e) } catch { /* ignore */ }

    }
  } finally {
    if (abortCtrl.value === ctrl) abortCtrl.value = null
    streaming.value = false
    streamBuf.value = ''
    conversations.value = await listConversations()
    await scrollBottom()
  }
}

function optionStage(o: ChatOption, fallback: string): string {
  // 兼容两种结构：扁平 {action:'go_stage', stage} 与嵌套 {action:{type,stage}}
  const rec = o as unknown as Record<string, unknown>
  const raw = rec.action
  const a = (typeof raw === 'object' && raw !== null ? raw : {}) as Record<string, unknown>
  if (typeof rec.stage === 'string' && rec.stage) return rec.stage
  if (typeof a.stage === 'string' && a.stage) return a.stage as string
  if (raw === 'build_ppt' || a.type === 'build_ppt') return 'export'
  return fallback
}

function optionAction(o: ChatOption): { type?: string; theme?: string; stage?: string } {
  const rec = o as unknown as Record<string, unknown>
  const raw = rec.action
  if (typeof raw === 'string') {
    return { type: raw, theme: typeof rec.theme === 'string' ? rec.theme : undefined }
  }
  const a = (typeof raw === 'object' && raw !== null ? raw : {}) as Record<string, unknown>
  return {
    type: typeof a.type === 'string' ? a.type : undefined,
    theme: typeof a.theme === 'string' ? a.theme : undefined,
    stage: typeof a.stage === 'string' ? a.stage : undefined,
  }
}

function clickOption(o: ChatOption) {
  if (!activeConv.value || streaming.value || building.value) return
  const act = optionAction(o)
  // build_ppt 选项 = 真实生成：直接调构建接口出文件，不再只发一句话让模型"口头导出"
  if (act.type === 'build_ppt') {
    void doBuildPpt({ label: o.label, theme: act.theme })
    return
  }
  void send({ text: o.label, stage: optionStage(o, activeConv.value.stage) })
}

function gotoStep(step: AgentStage) {
  if (!activeConv.value || streaming.value) return
  if (messages.value.length === 0) {
    void send({ text: `请按【${step.label}】阶段开始推进${step.desc ? `（${step.desc}）` : ''}`, stage: step.key })
  } else {
    void send({ text: `进入【${step.label}】阶段`, stage: step.key })
  }
}

async function toggleRag() {
  if (!activeConv.value) return
  const next = !activeConv.value.rag_enabled
  await patchConversation(activeConv.value.id, { rag_enabled: next })
  activeConv.value.rag_enabled = next
  conversations.value = await listConversations()
}

async function loadKb() {
  kbLoading.value = true
  kbError.value = ''
  try {
    myDocs.value = await listMyDocs()
    plazaDocs.value = await listPlaza()
  } catch (e: unknown) {
    kbError.value = e instanceof Error ? e.message : '知识库加载失败'
  } finally {
    kbLoading.value = false
  }
}

let kbPollTimer: ReturnType<typeof setInterval> | null = null

function stopKbPoll() {
  if (kbPollTimer) {
    clearInterval(kbPollTimer)
    kbPollTimer = null
  }
}

function startKbPoll() {
  stopKbPoll()
  // 有文档还在索引中时自动轮询，直到全部落定（成功即可发布，失败可重试）
  kbPollTimer = setInterval(async () => {
    if (tab.value === 'chat') {
      stopKbPoll()
      return
    }
    try {
      myDocs.value = await listMyDocs()
      if (!myDocs.value.some((d) => d.status === 'pending' || d.status === 'indexing')) stopKbPoll()
    } catch {
      /* 下一轮再试 */
    }
  }, 3000)
}

watch(tab, (t) => {
  if (t === 'mcp' || t === 'skill') void loadExt()
  if (t === 'skill') void loadSandbox()
  if (t !== 'chat') {
    void loadKb().then(() => startKbPoll())
  } else {
    stopKbPoll()
  }
})

async function doRetryDoc(id: string) {
  kbError.value = ''
  try {
    await retryDoc(id)
    await loadKb()
    startKbPoll()
  } catch (e: unknown) {
    kbError.value = e instanceof Error ? e.message : '重试失败'
  }
}

async function doToggleSearch(d: KnowledgeDoc) {
  kbError.value = ''
  try {
    const updated = await toggleDocSearch(d.id)
    d.enabled = updated.enabled
    d.status = updated.status
  } catch (e: unknown) {
    kbError.value = e instanceof Error ? e.message : '切换失败'
  }
}

async function doUpload() {
  if (!upFile.value || !upTitle.value.trim() || !upDesc.value.trim() || uploading.value) return
  uploading.value = true
  kbError.value = ''
  try {
    await uploadDoc(upFile.value, upTitle.value.trim(), upDesc.value.trim())
    upFile.value = null
    upTitle.value = ''
    upDesc.value = ''
    await loadKb()
    startKbPoll()
  } catch (e: unknown) {
    kbError.value = e instanceof Error ? e.message : '上传失败'
  } finally {
    uploading.value = false
  }
}

async function doPublish(id: string) {
  await publishDoc(id)
  await loadKb()
}
async function doUnpublish(id: string) {
  await unpublishDoc(id)
  await loadKb()
}
async function doDeleteDoc(id: string) {
  await deleteDoc(id)
  await loadKb()
}
async function doCollect(d: KnowledgeDoc) {
  if (d.collected) await uncollectDoc(d.id)
  else await collectDoc(d.id)
  await loadKb()
}

function onFileChange(e: Event) {
  const t = e.target as HTMLInputElement
  upFile.value = t.files?.[0] ?? null
  if (upFile.value && !upTitle.value) {
    upTitle.value = upFile.value.name.replace(/\.[^.]+$/, '')
  }
}

function citationsOf(m: { citations?: Record<string, unknown> | null }): { title: string; text: string; similarity?: number }[] {
  const hits = (m.citations as { hits?: { title: string; text: string; similarity?: number }[] } | null)?.hits
  return Array.isArray(hits) ? hits : []
}

const TOOL_LABELS: Record<string, string> = {
  my_schedule_overview: '排课考勤',
  my_teaching_stats: '教学数据',
  list_my_classes: '班级列表',
  find_students: '学员查询',
  student_progress: '学员进度',
  student_evaluations: '评估报告',
  class_evaluation_overview: '班级评估完成情况',
  sql_list_tables: '数据库·表清单',
  sql_describe_table: '数据库·表结构',
  sql_query: '数据库查询',
  run_skill_script: 'Skill脚本执行',
  read_skill_file: 'Skill文件读取',
}

function toolsOf(m: { citations?: Record<string, unknown> | null }): {
  seq: number; tool: string; args: Record<string, unknown>; ok: boolean; summary: string; error?: string | null;
}[] {
  const arr = (m.citations as { tools?: unknown } | null)?.tools
  return Array.isArray(arr) ? (arr as {
    seq: number; tool: string; args: Record<string, unknown>; ok: boolean; summary: string; error?: string | null;
  }[]) : []
}
/* —— MCP 调用链路（citations.mcp_trace）：规划→握手→调用→结果，每步 ok/ms/detail —— */
function mcpTraceOf(m: { citations?: Record<string, unknown> | null }): { step: string; ok: boolean; ms: number; detail: string }[] {
  const arr = (m.citations as { mcp_trace?: unknown } | null)?.mcp_trace
  return Array.isArray(arr) ? (arr as { step: string; ok: boolean; ms: number; detail: string }[]) : []
}

function toolArgsText(args: Record<string, unknown>): string {
  const parts = Object.entries(args ?? {}).map(([k, v]) => {
    if (k === 'period') {
      const labels: Record<string, string> = {
        today: '今天', this_week: '本周', last_week: '上周', this_month: '本月',
        last_month: '上月', this_quarter: '本季度', this_year: '本年度',
        recent_7d: '近7天', recent_30d: '近30天',
      }
      return `周期=${labels[String(v)] ?? String(v)}`
    }
    if (k === 'skill') return `Skill=${String(v)}`
    if (k === 'path') return `${String(v).split('/').pop()}`
    if (k === 'args' && Array.isArray(v)) return v.length ? `参数=${v.join(' ')}` : '无参数'
    return `${k}=${String(v)}`
  })
  return parts.length ? parts.join('，') : '默认参数'
}

/* —— 工具结果里的生成文件（run_skill_script 回传的下载链接）渲染为可点按钮 —— */
function toolFiles(summary: string): { 名?: string; name?: string; 下载?: string; url?: string }[] {
  try {
    const obj = JSON.parse(summary || '')
    const arr = obj?.['生成文件']
    return Array.isArray(arr) ? arr : []
  } catch {
    return []
  }
}

function statusText(d: KnowledgeDoc): string {
  if (d.status === 'ready') return `${d.chunk_count} 块`
  if (d.status === 'pending' || d.status === 'indexing') return progressLabel(d.progress)
  if (d.status === 'failed') return '索引失败'
  return d.status
}

const PROGRESS_STAGES: Record<string, string> = {
  parse: '解析文档',
  chunk: '切块',
  embed: '向量化',
  store: '入库',
}

function progressLabel(p?: { stage: string; percent: number; detail: string } | null): string {
  if (!p) return '排队索引中…'
  const name = PROGRESS_STAGES[p.stage] ?? '索引中'
  return `${name} ${p.percent}%`
}

/* —— Agent 扩展：自定义 Agent / MCP / Skill / 全局设置 —— */
const customAgents = ref<CustomAgent[]>([])
const mcps = ref<AgentMcp[]>([])
const skills = ref<AgentSkill[]>([])
const globMcp = ref<string[]>([])
const globSkill = ref<string[]>([])
const extLoading = ref(false)
const extError = ref('')
const showAgentForm = ref(false)
const editingAgent = ref<CustomAgent | null>(null)
const agentForm = ref({ name: '', description: '', system_prompt: '', supports_rag: true, icon: 'assistant', mcp_ids: [] as string[], skill_ids: [] as string[] })
const showMcpForm = ref(false)
const editingMcp = ref<AgentMcp | null>(null)
const mcpForm = ref({ name: '', kind: 'streamable_http', endpoint: '', description: '', enabled: true })
const showSkillForm = ref(false)
const editingSkill = ref<AgentSkill | null>(null)
const skillForm = ref({ name: '', description: '', content: '', enabled: true })

async function loadExt() {
  extLoading.value = true
  extError.value = ''
  try {
    const [ca, m, s, g] = await Promise.all([listCustomAgents(), listMcps(), listSkills(), getAgentGlobal()])
    customAgents.value = ca
    mcps.value = m
    skills.value = s
    globMcp.value = g.default_mcp_ids || []
    globSkill.value = g.default_skill_ids || []
    // 自定义 Agent 并入左侧可选列表（custom 标记避免与内置混淆）
    for (const c of ca) {
      if (!agents.value.some((a) => a.id === c.agent_id)) {
        agents.value.push({ id: c.agent_id, name: c.name, description: c.description, context_types: [], supports_rag: c.supports_rag, icon: c.icon, stages: c.stages } as AgentInfo)
      }
    }
  } catch (e: unknown) {
    extError.value = e instanceof Error ? e.message : '扩展配置加载失败'
  } finally {
    extLoading.value = false
  }
}

function openAgentCreate() {
  editingAgent.value = null
  agentForm.value = { name: '', description: '', system_prompt: '', supports_rag: true, icon: 'assistant', mcp_ids: [], skill_ids: [] }
  showAgentForm.value = true
}
function openAgentEdit(c: CustomAgent) {
  editingAgent.value = c
  agentForm.value = { name: c.name, description: c.description, system_prompt: c.system_prompt, supports_rag: c.supports_rag, icon: c.icon, mcp_ids: [...(c.mcp_ids || [])], skill_ids: [...(c.skill_ids || [])] }
  showAgentForm.value = true
}
async function saveAgent() {
  if (!agentForm.value.name.trim()) { extError.value = '请填写 Agent 名称'; return }
  const payload = { ...agentForm.value, name: agentForm.value.name.trim(), stages: [{ key: 'chat', label: '智能问答', desc: '直接提问', prompt_stage: 'chat' }] }
  if (editingAgent.value) {
    const updated = await patchCustomAgent(editingAgent.value.agent_id, payload)
    Object.assign(editingAgent.value, updated)
    const hit = agents.value.find((a) => a.id === updated.agent_id)
    if (hit) { hit.name = updated.name; hit.description = updated.description }
  } else {
    const created = await createCustomAgent(payload)
    customAgents.value.unshift(created)
    agents.value.push({ id: created.agent_id, name: created.name, description: created.description, context_types: [], supports_rag: created.supports_rag, icon: created.icon, stages: created.stages } as AgentInfo)
  }
  showAgentForm.value = false
  void loadExt()
}
async function removeAgent(c: CustomAgent) {
  if (!confirm(`删除自定义 Agent「${c.name}」？其历史会话保留，但不可再新建该 Agent 的对话。`)) return
  await deleteCustomAgent(c.agent_id)
  customAgents.value = customAgents.value.filter((x) => x.agent_id !== c.agent_id)
  agents.value = agents.value.filter((a) => a.id !== c.agent_id)
  if (selectedAgent.value === c.agent_id) selectedAgent.value = agents.value[0]?.id ?? ''
}

function openMcpCreate() {
  editingMcp.value = null
  mcpForm.value = { name: '', kind: 'streamable_http', endpoint: '', description: '', enabled: true }
  showMcpForm.value = true
}
function openMcpEdit(m: AgentMcp) {
  editingMcp.value = m
  mcpForm.value = { name: m.name, kind: m.kind || 'streamable_http', endpoint: m.endpoint, description: m.description, enabled: m.enabled }
  showMcpForm.value = true
}
async function saveMcp() {
  if (!mcpForm.value.name.trim()) { extError.value = '请填写 MCP 名称'; return }
  const payload = { ...mcpForm.value, name: mcpForm.value.name.trim(), config: editingMcp.value ? editingMcp.value.config ?? {} : {} }
  if (editingMcp.value) {
    const updated = await patchMcp(editingMcp.value.id, payload)
    Object.assign(editingMcp.value, updated)
  } else {
    mcps.value.unshift(await createMcp(payload))
  }
  showMcpForm.value = false
}
async function removeMcp(m: AgentMcp) {
  if (!confirm(`删除 MCP「${m.name}」？已绑定的 Agent/全局配置将自动失效该项。`)) return
  await deleteMcp(m.id)
  mcps.value = mcps.value.filter((x) => x.id !== m.id)
}
async function toggleMcp(m: AgentMcp) {
  const updated = await patchMcp(m.id, { name: m.name, kind: m.kind, endpoint: m.endpoint, description: m.description, config: m.config, enabled: !m.enabled })
  m.enabled = updated.enabled
}

/* —— MCP 测试连接：握手 + tools/list，结果弹窗展示工具清单与 trace —— */
const showMcpTest = ref(false)
const mcpTestTarget = ref<AgentMcp | null>(null)
const mcpTestLoading = ref(false)
const mcpTestResult = ref<{ ok: boolean; tools: { name: string; description: string }[]; trace: { step: string; ok: boolean; ms: number; detail: string }[] } | null>(null)
async function openMcpTest(m: AgentMcp) {
  mcpTestTarget.value = m
  mcpTestResult.value = null
  mcpTestLoading.value = true
  showMcpTest.value = true
  try {
    mcpTestResult.value = await testMcp(m.id)
  } catch (e: unknown) {
    mcpTestResult.value = { ok: false, tools: [], trace: [{ step: 'test', ok: false, ms: 0, detail: e instanceof Error ? e.message : '测试失败' }] }
  } finally {
    mcpTestLoading.value = false
  }
}

function openSkillCreate() {
  editingSkill.value = null
  skillForm.value = { name: '', description: '', content: '', enabled: true }
  showSkillForm.value = true
}
function openSkillEdit(s: AgentSkill) {
  editingSkill.value = s
  skillForm.value = { name: s.name, description: s.description, content: s.content, enabled: s.enabled }
  showSkillForm.value = true
}
async function saveSkill() {
  if (!skillForm.value.name.trim()) { extError.value = '请填写 Skill 名称'; return }
  if (!skillForm.value.content.trim() && !(editingSkill.value?.files?.length)) { extError.value = '请填写 Skill 指令内容，或上传含 SKILL.md 的文件包（自动回填）'; return }
  const payload = { ...skillForm.value, name: skillForm.value.name.trim() }
  if (editingSkill.value) {
    const updated = await patchSkill(editingSkill.value.id, payload)
    Object.assign(editingSkill.value, updated)
  } else {
    skills.value.unshift(await createSkill(payload))
  }
  showSkillForm.value = false
}
/* —— Skill 直接导入（zip 免新建）+ 文件预览 + 受控运行 —— */
const skillUploading = ref(false)
const skillPreview = ref<{ path: string; text: string } | null>(null)
const skillRunOut = ref<{ skillId: string; path: string; ok: boolean; stdout: string; stderr: string; provider?: string; deps?: string; sandbox_id?: string; phases?: string[]; deps_log?: string } | null>(null)
async function openSkillPreview(s: AgentSkill, path: string) {
  try {
    skillPreview.value = await previewSkillFile(s.id, path)
  } catch (err: unknown) {
    extError.value = err instanceof Error ? err.message : '预览失败'
  }
}
async function onSkillImport(e: Event) {
  const input = e.target as HTMLInputElement
  const f = input.files?.[0]
  input.value = ''
  if (!f) return
  if (f.size > 100 * 1024 * 1024) {
    extError.value = `“${f.name}”(${(f.size / 1048576).toFixed(1)}MB)超过 100MB 上限，请精简后重试（解压后总量 ≤80MB、单文件 ≤10MB）`
    return
  }
  skillUploading.value = true
  try {
    const created = await importSkillBundle(f)
    skills.value.unshift(created)
  } catch (err: unknown) {
    const status = (err as { response?: { status?: number; data?: { detail?: unknown } } })?.response?.status
    const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
    extError.value = status === 413
      ? `上传被网关拒绝（413）：包超过大小上限。请压缩到 100MB 以内（解压后 ≤80MB）再试。${typeof detail === 'string' ? `（${detail}）` : ''}`
      : (typeof detail === 'string' && detail) || (err instanceof Error ? err.message : '导入失败')
  } finally {
    skillUploading.value = false
  }
}
/* —— 沙箱设置（本地受控 / 阿里云函数计算远程） —— */
const sandbox = ref({ provider: 'local', endpoint: '', token: '', timeout_s: 30, enabled: true, workspace_id: '', region: 'cn-beijing', template_code: '' })
const sbHasToken = ref(false)
const sbOpen = ref(false)
const sbLoading = ref(false)
const sbTesting = ref(false)
const sbMsg = ref('')
async function loadSandbox() {
  try {
    const r = await getSandbox()
    sandbox.value = { provider: r.provider, endpoint: r.endpoint, token: '', timeout_s: r.timeout_s, enabled: r.enabled, workspace_id: r.workspace_id, region: r.region, template_code: r.template_code }
    sbHasToken.value = r.has_token
  } catch { /* 保持默认 */ }
}
async function saveSandbox() {
  sbLoading.value = true
  sbMsg.value = ''
  try {
    const r = await putSandbox({ ...sandbox.value, token: sandbox.value.token || undefined } as { provider: string; endpoint: string; token?: string; timeout_s: number; enabled: boolean; workspace_id: string; region: string; template_code: string })
    sandbox.value.token = ''
    sbHasToken.value = r.has_token
    sbMsg.value = '沙箱配置已保存'
  } catch (err: unknown) {
    sbMsg.value = err instanceof Error ? err.message : '保存失败'
  } finally {
    sbLoading.value = false
  }
}
async function testSandboxConn() {
  sbTesting.value = true
  sbMsg.value = ''
  try {
    const r = await testSandbox({ provider: sandbox.value.provider, endpoint: sandbox.value.endpoint, token: sandbox.value.token || undefined, timeout_s: sandbox.value.timeout_s, workspace_id: sandbox.value.workspace_id, region: sandbox.value.region, template_code: sandbox.value.template_code })
    sbMsg.value = r.ok ? `✓ ${r.detail}` : `✕ ${r.detail}`
  } catch (err: unknown) {
    sbMsg.value = `✕ ${err instanceof Error ? err.message : '测试失败'}`
  } finally {
    sbTesting.value = false
  }
}

/* —— 脚本运行弹窗（含参数输入） —— */
const runTarget = ref<{ s: AgentSkill; path: string } | null>(null)
const runArgs = ref('')
const runLoading = ref(false)
function openRunModal(s: AgentSkill, path: string) {
  runTarget.value = { s, path }
  runArgs.value = ''
  runLoading.value = false
}
async function confirmRun() {
  const t = runTarget.value
  if (!t || runLoading.value) return
  runLoading.value = true
  try {
    skillRunOut.value = null
    const args = runArgs.value.trim() ? runArgs.value.trim().split(/\s+/) : []
    const r = await runSkillScript(t.s.id, t.path, args)
    skillRunOut.value = { skillId: t.s.id, path: t.path, ok: r.ok, stdout: r.stdout, stderr: r.stderr, provider: r.provider, deps: (r as { deps?: string }).deps, sandbox_id: (r as { sandbox_id?: string }).sandbox_id, phases: (r as { phases?: string[] }).phases, deps_log: (r as { deps_log?: string }).deps_log }
  } catch (err: unknown) {
    extError.value = err instanceof Error ? err.message : '运行失败'
  } finally {
    runLoading.value = false
  }
}
async function runSkillFile(s: AgentSkill, path: string) {
  openRunModal(s, path)
}
async function removeSkill() {
  const s = deletingSkill.value
  if (!s) return
  deletingSkill.value = null
  await deleteSkill(s.id)
  skills.value = skills.value.filter((x) => x.id !== s.id)
}
const deletingSkill = ref<AgentSkill | null>(null)
function askRemoveSkill(s: AgentSkill) {
  deletingSkill.value = s
}

/* —— Skill 专业结构：SKILL.md / scripts / references / assets，按顶层目录分组展示 —— */
function skillGroups(s: AgentSkill): { dir: string; items: string[] }[] {
  const map = new Map<string, string[]>()
  for (const f of s.files ?? []) {
    const parts = String(f).split('/')
    const dir = parts.length > 1 ? parts.slice(0, -1).join('/') + '/' : '根目录 /'
    if (!map.has(dir)) map.set(dir, [])
    map.get(dir)!.push(String(f))
  }
  const order = (d: string) => d === '根目录 /' ? 0 : d.startsWith('scripts') ? 1 : d.startsWith('references') ? 2 : d.startsWith('assets') ? 3 : 4
  return [...map.entries()]
    .sort((a, b) => order(a[0]) - order(b[0]) || (a[0] < b[0] ? -1 : 1))
    .map(([dir, items]) => ({ dir: `${dir}（${items.length}）`, items: items.slice(0, 100) }))
}
function shortName(f: string): string {
  const base = String(f).split('/').pop() ?? String(f)
  return base.length > 28 ? '…' + base.slice(-27) : base
}
function hasSkillMd(s: AgentSkill): boolean {
  return (s.files ?? []).some((f) => String(f).toLowerCase().endsWith('skill.md'))
}
function countRole(s: AgentSkill, role: 'scripts' | 'refs' | 'assets'): number {
  const files = s.files ?? []
  if (role === 'scripts') return files.filter((f) => /\.(py|js|sh)$/i.test(String(f))).length
  if (role === 'refs') {
    return files.filter((f) => {
      const l = String(f).toLowerCase()
      return !l.endsWith('skill.md') && (l.includes('/references/') || /\.(md|txt)$/.test(l)) && !/\.(py|js|sh)$/.test(l)
    }).length
  }
  return files.filter((f) => {
    const l = String(f).toLowerCase()
    return !l.endsWith('skill.md') && !/\.(py|js|sh|md|txt)$/.test(l) && !l.includes('/references/')
  }).length
}
async function toggleSkill(s: AgentSkill) {
  const updated = await patchSkill(s.id, { name: s.name, description: s.description, content: s.content, enabled: !s.enabled })
  s.enabled = updated.enabled
}

function toggleGlobMcp(id: string) {
  const s = new Set(globMcp.value)
  if (s.has(id)) s.delete(id)
  else s.add(id)
  globMcp.value = [...s]
  void putAgentGlobal({ default_mcp_ids: globMcp.value, default_skill_ids: globSkill.value })
}
function toggleGlobSkill(id: string) {
  const s = new Set(globSkill.value)
  if (s.has(id)) s.delete(id)
  else s.add(id)
  globSkill.value = [...s]
  void putAgentGlobal({ default_mcp_ids: globMcp.value, default_skill_ids: globSkill.value })
}
function toggleAgentPick(arr: string[], id: string): string[] {
  const s = new Set(arr)
  if (s.has(id)) s.delete(id)
  else s.add(id)
  return [...s]
}

function back() {
  router.back()
}

/* —— Mermaid 懒加载渲染：CDN 按需加载，失败则保留源码预览 —— */
let mermaidLoaded = false
function ensureMermaid(): Promise<boolean> {
  if (mermaidLoaded) return Promise.resolve(true)
  if ((window as unknown as { mermaid?: unknown }).mermaid) {
    mermaidLoaded = true
    return Promise.resolve(true)
  }
  return new Promise((resolve) => {
    const s = document.createElement('script')
    s.src = 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js'
    s.onload = () => { mermaidLoaded = true; resolve(true) }
    s.onerror = () => resolve(false)
    document.head.appendChild(s)
  })
}
async function renderMermaid() {
  const els = chatEl.value?.querySelectorAll('.mermaid-render') ?? []
  if (!els.length) return
  const ok = await ensureMermaid()
  if (!ok) return
  const mm = (window as unknown as { mermaid?: { initialize?: (o: unknown) => void; run?: (o: unknown) => Promise<void> } }).mermaid
  try {
    mm?.initialize?.({ startOnLoad: false, theme: 'neutral' })
    await mm?.run?.({ nodes: [...els] as unknown as Element[] })
    els.forEach((el) => {
      const html = (el as HTMLElement).innerHTML
      if (html.includes('mermaid-render') || !html.trim()) return
      const box = el.closest('.md-mermaid')
      box?.classList.add('rendered')
    })
  } catch { /* 保留源码 */ }
}
watch([messages, streamBuf], () => { void nextTick().then(() => renderMermaid()) })
</script>

<template>
  <div class="agents-page">
    <header class="hero slim">
      <button class="back-btn" @click="back">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 18l-6-6 6-6" /></svg>
      </button>
      <span class="hero-mark sm">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2 3 14h7l-1 8 10-12h-7l1-8z" /></svg>
      </span>
      <h2>Agent 工作台</h2>
      <span class="hero-stats inline">
        <span class="stat-i"><b>{{ conversations.length }}</b>会话</span>
        <span class="stat-i"><b>{{ memories.length }}</b>记忆</span>
        <span class="stat-i"><b>{{ readyDocs }}</b>文档</span>
      </span>
      <span class="hero-spacer" />
      <button class="pill-btn sm" :class="{ on: showMemory }" @click="showMemory = !showMemory">长期记忆</button>
    </header>

    <div class="agents-layout">
      <aside class="agents-side" :class="{ rail: sideCollapsed }">
        <div v-if="!sideCollapsed" class="side-full">
        <div class="side-head">
          <div class="side-label">工作台</div>
          <button class="icon-btn" title="收起侧栏" @click="sideCollapsed = true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 18l-6-6 6-6" /></svg>
          </button>
        </div>
        <div class="drop" :class="{ open: agentDrop }">
          <button class="drop-head" @click="agentDrop = !agentDrop">
            <span class="agent-ico sm">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path :d="currentAgent ? iconOf(currentAgent) : 'M13 2 3 14h7l-1 8 10-12h-7l1-8z'" /></svg>
            </span>
            <span class="drop-title">{{ currentAgent?.name ?? '选择 Agent' }}</span>
            <svg class="chev" :class="{ open: agentDrop }" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6" /></svg>
          </button>
          <div v-show="agentDrop" class="drop-body">
        <div class="side-block">
          <div class="agent-list">
            <button
              v-for="a in agents"
              :key="a.id"
              class="agent-card"
              :class="{ on: selectedAgent === a.id }"
              @click="selectedAgent = a.id"
            >
              <span class="agent-ico">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path :d="iconOf(a)" /></svg>
              </span>
              <span class="agent-text">
                <b>{{ a.name }}<em v-if="(a as any).custom" class="custom-tag">自建</em></b>
                <span>{{ a.description }}</span>
              </span>
              <svg v-if="a.supports_rag" class="agent-rag" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" title="支持知识库引用"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" /></svg>
            </button>
            <p v-if="!agents.length" class="empty">暂无可用 Agent</p>
          </div>
        </div>
        </div>
        </div>

        <button class="mini-btn manage-agent" @click="openAgentCreate(); tab = 'chat'">＋ 新建 Agent</button>
        <button class="new-conv" :disabled="!selectedAgent || creating" @click="newConversation">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12h14" /></svg>
          {{ creating ? '创建中…' : '新建对话' }}
        </button>

        <div class="drop grow" :class="{ open: histDrop }">
          <button class="drop-head" @click="histDrop = !histDrop">
            <svg class="drop-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /></svg>
            <span class="drop-title">对话历史（{{ conversations.length }}）</span>
            <svg class="chev" :class="{ open: histDrop }" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6" /></svg>
          </button>
          <div v-show="histDrop" class="drop-body grow">
          <div v-if="multiMode" class="multi-bar">
            <span>已选 {{ selectedIds.size }} 条</span>
            <button class="mini-btn" :disabled="!selectedIds.size" @click="batchPin">置顶</button>
            <button class="mini-btn danger" :disabled="!selectedIds.size" @click="batchDelete">删除</button>
            <button class="mini-btn" @click="multiMode = false">退出</button>
          </div>
        <div class="side-block grow">
          <div class="conv-list">
            <div v-for="[g, items] in grouped" :key="g" class="conv-group">
              <button class="conv-group-title" @click="toggleGroup(g)">
                <svg class="chev" :class="{ open: !collapsedGroups.has(g) }" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6" /></svg>
                <span class="group-name">{{ g }}</span>
                <span class="group-count">{{ items.length }}</span>
              </button>
              <template v-if="!collapsedGroups.has(g)">
              <button
                v-for="c in items"
                :key="c.id"
                class="conv-item"
                :class="{ on: activeConv?.id === c.id }"
                @click="onConvRowClick(c, $event)"
              >
                <input
                  v-if="multiMode"
                  type="checkbox"
                  class="conv-check"
                  :checked="selectedIds.has(c.id)"
                  @click.stop="toggleSelect(c.id)"
                />
                <span v-if="c.pinned" class="conv-pin" title="已置顶">📌</span>
                <span v-if="renamingId === c.id" class="conv-rename" @click.stop>
                  <input
                    v-model="renameText"
                    maxlength="40"
                    @keydown.enter="confirmRename(c)"
                    @keydown.esc="renamingId = null"
                    @click.stop
                  />
                  <button class="mini-btn" @click.stop="confirmRename(c)">定</button>
                </span>
                <span v-else class="conv-title">{{ c.title }}</span>
                <span v-if="c.rag_enabled" class="conv-rag">RAG</span>
                <span
                  class="conv-more"
                  title="更多操作"
                  @click.stop="toggleMenu(c.id, $event)"
                  @mouseenter="hoverMenu(c.id, $event)"
                >
                  <svg viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="1.8" /><circle cx="12" cy="12" r="1.8" /><circle cx="19" cy="12" r="1.8" /></svg>
                </span>
                <Teleport to="body">
                  <div
                    v-if="menuId === c.id"
                    class="conv-menu"
                    :style="menuStyle"
                    @click.stop
                  >
                    <button @click="startRename(c)">重命名</button>
                    <button @click="togglePin(c)">{{ c.pinned ? '取消置顶' : '置顶' }}</button>
                    <button @click="shareConv(c)">分享</button>
                    <button @click="enterMulti()">多选</button>
                    <button class="danger" @click="removeConversation(c.id); menuId = null">删除</button>
                  </div>
                </Teleport>
              </button>
              </template>
            </div>
            <p v-if="!grouped.length" class="empty">暂无对话，点击上方新建</p>
          </div>
        </div>
          </div>
        </div>
        </div>
        <div v-else class="side-rail">
          <button class="icon-btn rail-btn" title="展开 Agent 与历史栏" @click="sideCollapsed = false">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18l6-6-6-6" /></svg>
          </button>
          <button
            v-for="a in agents"
            :key="a.id"
            class="icon-btn rail-btn"
            :class="{ on: selectedAgent === a.id }"
            :title="a.name"
            @click="selectedAgent = a.id; sideCollapsed = false"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path :d="iconOf(a)" /></svg>
          </button>
          <button class="icon-btn rail-btn accent" title="新建对话" :disabled="!selectedAgent" @click="newConversation">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12h14" /></svg>
          </button>
        </div>
      </aside>

      <section class="agents-main">
        <div class="seg">
          <button :class="{ on: tab === 'chat' }" @click="tab = 'chat'">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /></svg>
            对话
          </button>
          <button :class="{ on: tab === 'mine' }" @click="tab = 'mine'">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" /></svg>
            我的知识库
          </button>
          <button :class="{ on: tab === 'plaza' }" @click="tab = 'plaza'">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 21h18M5 21V7l7-4 7 4v14M9 9h.01M9 12h.01M9 15h.01M15 9h.01M15 12h.01M15 15h.01" /></svg>
            广场
          </button>
          <button :class="{ on: tab === 'mcp' }" @click="tab = 'mcp'">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33h.09a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51h.09a1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82v.09a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" /></svg>
            MCP
          </button>
          <button :class="{ on: tab === 'skill' }" @click="tab = 'skill'">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2 3 14h7l-1 8 10-12h-7l1-8z" /></svg>
            Skill
          </button>
        </div>

        <div v-if="showMemory && tab === 'chat'" class="memory-panel">
          <div class="memory-head">
            <span>长期记忆 · {{ currentAgent?.name }}</span>
            <span class="memory-hint">默认按 Agent 隔离，仅你可见</span>
          </div>
          <ul v-if="memories.length">
            <li v-for="m in memories" :key="m.id">
              <b>{{ m.key }}</b><span>{{ m.value }}</span>
              <button class="chip-del" @click="removeMemory(m.id)">×</button>
            </li>
          </ul>
          <p v-else class="empty">暂无长期记忆，对话结束后会自动提炼偏好与事实</p>
        </div>

        <!-- 对话 -->
        <template v-if="tab === 'chat'">
          <div v-if="!activeConv" class="empty-hero">
            <div class="empty-illu">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2 3 14h7l-1 8 10-12h-7l1-8z" /></svg>
            </div>
            <h3>开始你的第一段对话</h3>
            <p>从左侧选择 Agent 并新建对话；或从「报告 / 评估」页一键跳转，自动带入业务上下文。</p>
            <button class="btn primary" :disabled="!selectedAgent || creating" @click="newConversation">
              {{ creating ? '创建中…' : '新建对话' }}
            </button>
          </div>
          <template v-else>
            <div v-if="roadmap.length > 1" class="roadmap">
              <button
                v-for="(s, i) in roadmap"
                :key="s.key"
                class="road-step"
                :class="stepState(i)"
                :title="s.desc"
                @click="gotoStep(s)"
              >
                <span class="road-dot">
                  <svg v-if="stepState(i) === 'done'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5" /></svg>
                  <span v-else>{{ i + 1 }}</span>
                </span>
                <span class="road-label">{{ s.label }}</span>
              </button>
            </div>
            <div v-if="roadmap.length > 1 && !messages.length && !streaming" class="stage-guide">
              <div class="stage-guide-text">
                <b>{{ roadmap[currentStageIdx]?.label ?? '开始' }}</b>
                <span>{{ roadmap[currentStageIdx]?.desc ?? '点击下方按钮让 Agent 按执行链路推进' }}</span>
              </div>
              <button class="btn primary" :disabled="streaming" @click="gotoStep(roadmap[currentStageIdx])">
                开始{{ roadmap[currentStageIdx]?.label ?? '' }}
              </button>
            </div>
            <div class="chat-top">
              <button class="rag-toggle" :class="{ on: activeConv.rag_enabled }" @click="toggleRag">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" /></svg>
                引用知识库：{{ activeConv.rag_enabled ? '开' : '关' }}
              </button>
              <select v-model="activeConfigId" class="model-switch" title="本次对话使用的模型（默认按模块映射）">
                <option :value="null">模型：按模块映射</option>
                <option v-for="c in llmConfigs" :key="c.id" :value="c.id">模型：{{ c.name }}</option>
              </select>
              <label v-if="!activeConv.rag_enabled" class="rag-once">
                <input v-model="useRagOnce" type="checkbox" /> 仅本条
              </label>
              <button v-if="tab === 'chat'" class="rag-toggle" :class="{ on: wsOpen }" @click="wsOpen = !wsOpen" title="大纲 / 素材 / 成果工作区">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3h7v7H3zM14 3h7v4h-7zM14 11h7v10h-7zM3 14h7v7H3z" /></svg>
                工作区
              </button>
            </div>

            <div ref="chatEl" class="chat">
              <div v-for="(m, i) in messages" :key="i" class="msg" :class="m.role">
                <div v-if="m.role === 'assistant'" class="avatar ai">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2 3 14h7l-1 8 10-12h-7l1-8z" /></svg>
                </div>
                <div class="bubble">
                  <div v-html="renderMarkdown(m.content)" />
                  <div v-if="(m.options ?? []).length" class="opt-row">
                    <button
                      v-for="o in (m.options ?? [])"
                      :key="o.id"
                      class="opt-btn"
                      :class="{ rec: o.recommended }"
                      :disabled="streaming"
                      @click="clickOption(o)"
                    >
                      {{ o.recommended ? '★ ' : '' }}{{ o.label }}
                    </button>
                  </div>
                  <details v-if="citationsOf(m).length" class="cite-drop">
                    <summary>
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" /></svg>
                      引用来源（{{ citationsOf(m).length }}）
                    </summary>
                    <div v-for="(c, j) in citationsOf(m)" :key="j" class="cite">
                      <div class="cite-head">
                        《{{ c.title }}》
                        <span v-if="c.similarity != null" class="sim">{{ c.similarity }}</span>
                      </div>
                      <p>{{ c.text.slice(0, 160) }}</p>
                    </div>
                  </details>
                  <details v-if="toolsOf(m).length" class="cite-drop tool-drop">
                    <summary>
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33h.09a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51h.09a1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82v.09a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" /></svg>
                      执行链路（{{ toolsOf(m).length }}）：读文件 / 跑脚本 / 查数据
                      <span v-if="(m.citations as Record<string, unknown>)?.degraded" class="tool-flag">启发式</span>
                    </summary>
                    <p v-if="(m.citations as Record<string, unknown>)?.rounds" class="tool-meta">
                      共规划 {{ (m.citations as Record<string, unknown>).rounds }} 轮
                      <template v-if="(m.citations as Record<string, unknown>)?.degraded"> · 规划器未命中，已自动降级为关键词直连</template>
                    </p>
                    <div v-for="t in toolsOf(m)" :key="t.seq" class="tool-step" :class="{ fail: !t.ok }">
                      <div class="tool-step-head">
                        <span class="tool-dot" :class="{ ok: t.ok, fail: !t.ok }">{{ t.ok ? '✓' : '✕' }}</span>
                        <b>{{ t.seq }}. {{ TOOL_LABELS[t.tool] ?? t.tool }}</b>
                        <span class="tool-args">{{ toolArgsText(t.args) }}</span>
                      </div>
                      <p v-if="t.ok" class="tool-summary">{{ t.summary }}</p>
                      <div v-if="toolFiles(t.summary).length" class="tool-files">
                        <a v-for="(f, fi) in toolFiles(t.summary)" :key="fi" class="file-dl" :href="f['下载'] ?? f.url" download target="_blank" rel="noopener">⬇ {{ f['名'] ?? f.name }}</a>
                      </div>
                      <p v-else class="tool-error">查询失败：{{ t.error }}（已跳过该项，其余数据不受影响）</p>
                    </div>
                  </details>
                  <details v-if="mcpTraceOf(m).length" class="cite-drop tool-drop">
                    <summary>
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33h.09a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51h.09a1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82v.09a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" /></svg>
                      MCP 调用链路（{{ mcpTraceOf(m).length }} 步）
                    </summary>
                    <div v-for="(s, k) in mcpTraceOf(m)" :key="k" class="trace-row" :class="s.ok ? 'ok' : 'fail'">
                      <span class="trace-step">{{ s.step }}</span>
                      <span class="trace-detail">{{ s.detail }}</span>
                      <span class="trace-ms">{{ s.ms }}ms</span>
                    </div>
                  </details>
                </div>
              </div>
              <div v-if="streaming" class="msg assistant">
                <div class="avatar ai"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2 3 14h7l-1 8 10-12h-7l1-8z" /></svg></div>
                <div class="bubble streaming">
                  <div class="thinking-line">
                    <span class="spinner" />{{ phaseLabel }}…
                    <button class="pause-btn" @click="pauseStream">暂停</button>
                  </div>
                  <div v-if="stripPartialJson(streamBuf)" v-html="renderMarkdown(stripPartialJson(streamBuf))" />
                </div>
              </div>
            </div>
            <p v-if="error" class="error-row">
              <span>{{ error }}</span>
              <button v-if="lastSend && !streaming" class="retry-btn" @click="retryLast" title="用上一条消息重试">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 3-6.7L3 8" /><path d="M3 3v5h5" /></svg>
                重试
              </button>
            </p>
            <div class="input-row">
              <textarea v-model="input" rows="1" placeholder="输入你的想法，Enter 发送…" @keydown.enter.exact.prevent="send()" />
              <button v-if="streaming" class="pause-big" @click="pauseStream">
                <svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="5" width="4" height="14" rx="1" /><rect x="14" y="5" width="4" height="14" rx="1" /></svg>
                停止
              </button>
              <button v-else class="send-btn" :disabled="!input.trim()" @click="send()">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 2 11 13M22 2l-7 20-4-9-9-4z" /></svg>
              </button>
            </div>
          </template>
        </template>

        <!-- 我的知识库 -->
        <template v-else-if="tab === 'mine'">
          <div class="kb-scroll">
          <div class="kb-upload">
            <div class="kb-upload-head">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12" /></svg>
              上传文档
              <span>支持 txt / md / pdf / docx</span>
            </div>
            <div class="kb-form">
              <label class="file-drop">
                <input type="file" accept=".txt,.md,.markdown,.pdf,.docx" @change="onFileChange" />
                <span v-if="!upFile">点击选择文件</span>
                <span v-else class="picked">{{ upFile.name }}</span>
              </label>
              <input v-model="upTitle" class="kb-input" placeholder="标题（必填）" maxlength="160" />
              <input v-model="upDesc" class="kb-input" placeholder="描述（必填，广场展示用）" />
              <button class="btn primary" :disabled="uploading || !upFile || !upTitle.trim() || !upDesc.trim()" @click="doUpload">
                {{ uploading ? '上传中…' : '上传并入库' }}
              </button>
            </div>
          </div>
          <p v-if="kbError" class="error">{{ kbError }}</p>
          <p v-if="kbLoading" class="empty">加载中…</p>
          <div class="kb-grid">
            <div v-for="d in myDocs" :key="d.id" class="kb-card">
              <div class="kb-card-top">
                <span class="kb-badge" :class="d.status">{{ statusText(d) }}</span>
                <span class="kb-vis" :class="d.visibility">{{ d.visibility === 'plaza' ? '广场' : '私有' }}</span>
              </div>
              <b class="kb-title">{{ d.title }}</b>
              <p class="kb-desc">{{ d.description }}</p>
              <div class="kb-file">{{ d.file_name }}</div>
              <div v-if="d.status === 'pending' || d.status === 'indexing'" class="kb-progress">
                <div class="kb-progress-track">
                  <div class="kb-progress-fill" :style="{ width: `${d.progress?.percent ?? 5}%` }" />
                </div>
                <span class="kb-progress-text">{{ d.progress?.detail || progressLabel(d.progress) }}</span>
              </div>
              <p v-if="d.error" class="kb-err">{{ d.error }}</p>
              <div class="kb-ops">
                <button v-if="d.status === 'failed'" class="mini-btn warn" @click="doRetryDoc(d.id)">重新索引</button>
                <button
                  v-if="d.status === 'ready'"
                  class="mini-btn switch"
                  :class="{ off: d.enabled === false }"
                  :title="d.enabled === false ? '已关闭检索，点击重新参与' : '参与检索中，点击关闭'"
                  @click="doToggleSearch(d)"
                >
                  <span class="switch-dot" />{{ d.enabled === false ? '检索关' : '检索开' }}
                </button>
                <button v-if="d.visibility === 'private' && d.status === 'ready'" class="mini-btn" @click="doPublish(d.id)">发布到广场</button>
                <button v-if="d.visibility === 'plaza'" class="mini-btn" @click="doUnpublish(d.id)">下架</button>
                <button class="mini-btn danger" @click="doDeleteDoc(d.id)">删除</button>
              </div>
            </div>
          </div>
          <p v-if="!kbLoading && !myDocs.length" class="empty">还没有文档，先上传一份吧</p>
          </div>
        </template>

        <!-- 广场 -->
        <template v-else>
          <p v-if="kbError" class="error">{{ kbError }}</p>
          <p v-if="kbLoading" class="empty">加载中…</p>
          <div class="kb-scroll">
          <div class="kb-grid">
            <div v-for="d in plazaDocs" :key="d.id" class="kb-card">
              <div class="kb-card-top">
                <span class="kb-badge ready">{{ d.chunk_count }} 块</span>
                <span v-if="d.mine" class="kb-vis mine">我的</span>
              </div>
              <b class="kb-title">{{ d.title }}</b>
              <p class="kb-desc">{{ d.description }}</p>
              <div class="kb-ops">
                <button v-if="!d.mine" class="mini-btn" :class="{ on: d.collected }" @click="doCollect(d)">
                  {{ d.collected ? '已收录 · 取消' : '收录到我的库' }}
                </button>
                <span v-else class="kb-file">你发布的文档</span>
              </div>
            </div>
          </div>
          <p v-if="!kbLoading && !plazaDocs.length" class="empty">广场暂无公开文档</p>
          </div>
        </template>

        <!-- MCP：外部工具接入 + 全局默认 -->
        <template v-if="tab === 'mcp'">
          <div class="kb-scroll">
            <div class="ext-hero">
              <div>
                <b>MCP 工具</b>
                <p>接入外部 HTTP 工具（MCP）。勾选「全局默认」即作用于当前账户全部 Agent；也可在 Agent 表单里单独绑定某个 Agent。</p>
              </div>
              <button class="btn primary" @click="openMcpCreate()">＋ 新建 MCP</button>
            </div>
            <p v-if="extError" class="error">{{ extError }}</p>
            <p v-if="extLoading" class="empty">加载中…</p>
            <div class="kb-grid">
              <div v-for="m in mcps" :key="m.id" class="kb-card ext-card">
                <div class="kb-card-top">
                  <span class="kb-badge" :class="m.enabled ? 'ready' : ''">{{ m.enabled ? '启用中' : '已停用' }}</span>
                  <label class="glob-check" title="全局默认：作用于全部 Agent">
                    <input type="checkbox" :checked="globMcp.includes(m.id)" @change="toggleGlobMcp(m.id)" /> 全局
                  </label>
                </div>
                <b class="kb-title">{{ m.name }}</b>
                <p class="kb-desc">{{ m.description || '暂无描述' }}</p>
                <div class="kb-file">{{ m.endpoint || '未填 endpoint' }}</div>
                <div class="kb-kind">{{ m.kind === 'http' ? '普通 HTTP' : 'MCP StreamableHTTP' }}</div>
                <div class="kb-ops">
                  <button class="mini-btn switch" :class="{ off: !m.enabled }" @click="toggleMcp(m)">
                    <span class="switch-dot" />{{ m.enabled ? '启用' : '停用' }}
                  </button>
                  <button class="mini-btn accent" @click="openMcpTest(m)">测试</button>
                  <button class="mini-btn" @click="openMcpEdit(m)">配置</button>
                  <button class="mini-btn danger" @click="removeMcp(m)">删除</button>
                </div>
              </div>
            </div>
            <p v-if="!extLoading && !mcps.length" class="empty">还没有 MCP，先新建一个吧</p>
          </div>
        </template>

        <!-- Skill：本地技能指令 + 全局默认 -->
        <template v-if="tab === 'skill'">
          <div class="kb-scroll">
            <div class="ext-hero">
              <div>
                <b>Skill 技能</b>
                <p>本地技能 = 追加进系统提示的专属指令。勾选「全局默认」即作用于全部 Agent；也可在 Agent 表单里单独绑定。</p>
              </div>
              <button class="btn primary" @click="openSkillCreate()">＋ 新建 Skill</button>
              <label class="btn ghost" title="上传 zip 包直接创建 Skill，无需先新建">
                {{ skillUploading ? '导入中…' : '导入 ZIP' }}
                <input type="file" accept=".zip" hidden @change="onSkillImport" />
              </label>
            </div>
            <div class="sandbox-card">
              <button class="sandbox-head" @click="sbOpen = !sbOpen">
                <b>脚本沙箱：{{ sandbox.provider === 'bailian' ? '阿里云百炼' : '本地受控执行' }}</b>
                <span>{{ sbOpen ? '收起' : '配置' }}</span>
              </button>
              <div v-if="sbOpen" class="sandbox-body">
                <p class="sandbox-desc">本地沙箱无第三方依赖/无网络，仅冒烟测试。切到阿里云百炼后，脚本在云端沙箱跑（可装依赖）。工作空间ID点控制台右上角「默认业务空间」查看；模板 code 填 Sandbox→我的模板里的 templateCode。</p>
                <div class="sandbox-row">
                  <label>提供商
                    <select v-model="sandbox.provider" class="kb-input">
                      <option value="local">本地受控执行（默认）</option>
                      <option value="bailian">阿里云百炼 Sandbox</option>
                    </select>
                  </label>
                  <label>超时（秒）
                    <input v-model.number="sandbox.timeout_s" type="number" min="10" max="120" class="kb-input" />
                  </label>
                </div>
                <template v-if="sandbox.provider === 'bailian'">
                  <div class="sandbox-row">
                    <label>工作空间ID
                      <input v-model="sandbox.workspace_id" class="kb-input" placeholder="点控制台右上角「默认业务空间」查看" />
                    </label>
                    <label>地域
                      <select v-model="sandbox.region" class="kb-input">
                        <option value="cn-beijing">华北2北京（当前仅支持）</option>
                      </select>
                    </label>
                  </div>
                  <label>API Key（sk-…，不填则保留已存）
                    <input v-model="sandbox.token" type="password" class="kb-input" :placeholder="sbHasToken ? '已保存（留空不改）' : 'sk- 开头，Sandbox 页左下角创建'" />
                  </label>
                  <label>模板 code
                    <input v-model="sandbox.template_code" class="kb-input" placeholder="Sandbox → 我的模板 → templateCode" />
                  </label>
                </template>
                <div class="sandbox-ops">
                  <button class="mini-btn" :disabled="sbTesting" @click="testSandboxConn()">{{ sbTesting ? '测试中…' : '测试连通' }}</button>
                  <button class="mini-btn accent" :disabled="sbLoading" @click="saveSandbox()">{{ sbLoading ? '保存中…' : '保存配置' }}</button>
                  <span v-if="sbMsg" class="sandbox-msg">{{ sbMsg }}</span>
                </div>
              </div>
            </div>
            <p v-if="extError" class="error">{{ extError }}</p>
            <p v-if="extLoading" class="empty">加载中…</p>
            <div class="kb-grid">
              <div v-for="s in skills" :key="s.id" class="kb-card ext-card">
                <div class="kb-card-top">
                  <span class="kb-badge" :class="s.enabled ? 'ready' : ''">{{ s.enabled ? '启用中' : '已停用' }}</span>
                  <label class="glob-check" title="全局默认：作用于全部 Agent">
                    <input type="checkbox" :checked="globSkill.includes(s.id)" @change="toggleGlobSkill(s.id)" /> 全局
                  </label>
                </div>
                <b class="kb-title">{{ s.name }}</b>
                <p class="kb-desc">{{ s.description || '暂无描述' }}</p>
                <div class="kb-file">{{ (s.content || '').slice(0, 80) }}</div>
                <details v-if="s.files?.length" class="skill-files">
                  <summary>文件结构（{{ s.files.length }}）· 点击展开</summary>
                  <div class="skill-layout">
                    <span class="layout-chip" :class="hasSkillMd(s) ? 'ok' : 'miss'">SKILL.md{{ hasSkillMd(s) ? '' : ' 缺失' }}</span>
                    <span class="layout-chip" :class="countRole(s, 'scripts') ? 'ok' : ''">scripts {{ countRole(s, 'scripts') }}</span>
                    <span class="layout-chip" :class="countRole(s, 'refs') ? 'ok' : ''">references {{ countRole(s, 'refs') }}</span>
                    <span class="layout-chip" :class="countRole(s, 'assets') ? 'ok' : ''">assets {{ countRole(s, 'assets') }}</span>
                  </div>
                  <div class="skill-file-list">
                    <div v-for="g in skillGroups(s)" :key="g.dir" class="skill-dir">
                      <div class="skill-dir-name">{{ g.dir }}</div>
                      <span v-for="f in g.items" :key="f" class="file-chip-wrap" :title="f">
                        <button class="file-chip" @click="openSkillPreview(s, f)" :title="`预览 ${f}`">{{ shortName(f) }}</button>
                        <button v-if="/\.(py|js|sh)$/i.test(f)" class="file-run" title="沙箱试运行（无第三方依赖/无网络，仅冒烟测试，失败多为缺依赖）" @click="runSkillFile(s, f)">▶</button>
                      </span>
                    </div>
                  </div>
                </details>
                <div v-if="skillRunOut && skillRunOut.skillId === s.id" class="skill-runout" :class="{ fail: !skillRunOut.ok }">
                  <b>{{ skillRunOut.path }} · {{ skillRunOut.ok ? '运行成功' : '运行失败' }}</b>
                  <span class="runout-tag" :class="skillRunOut.provider === 'bailian' ? 'remote' : 'local'">{{ skillRunOut.provider === 'bailian' ? '百炼沙箱' : '本地沙箱' }}</span>
                  <span class="runout-tip">本地沙箱无第三方依赖/无网络，仅冒烟测试；缺参报错时点 ▶ 重新运行并填写参数</span>
                  <pre v-if="skillRunOut.stdout">{{ skillRunOut.stdout }}</pre>
                  <pre v-if="skillRunOut.stderr" class="err">{{ skillRunOut.stderr }}</pre>
                </div>
                <div class="kb-ops">
                  <button class="mini-btn switch" :class="{ off: !s.enabled }" @click="toggleSkill(s)">
                    <span class="switch-dot" />{{ s.enabled ? '启用' : '停用' }}
                  </button>
                  <button class="mini-btn" @click="openSkillEdit(s)">配置</button>
                  <button class="mini-btn danger" @click="askRemoveSkill(s)">删除</button>
                </div>
              </div>
            </div>
            <p v-if="!extLoading && !skills.length" class="empty">还没有 Skill，先新建一个吧</p>
          </div>
        </template>
      </section>

      <aside v-if="tab === 'chat' && !wsOpen" class="ws-rail">
        <button class="icon-btn rail-btn" title="展开工作区（大纲 / 素材 / 成果）" @click="wsOpen = true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 18l-6-6 6-6" /></svg>
        </button>
      </aside>
      <aside v-if="tab === 'chat' && wsOpen" class="ws-side">
        <div class="ws-head">
          <b>工作区</b>
          <span class="ws-sub">大纲预览 · 引用素材 · 成果</span>
          <button class="icon-btn" title="收起工作区" @click="wsOpen = false">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18l6-6-6-6" /></svg>
          </button>
        </div>
        <div class="ws-seg">
          <button :class="{ on: wsTab === 'outline' }" @click="wsTab = 'outline'">大纲</button>
          <button :class="{ on: wsTab === 'material' }" @click="wsTab = 'material'">素材{{ material.length ? `(${material.length})` : '' }}</button>
          <button :class="{ on: wsTab === 'result' }" @click="wsTab = 'result'">成果</button>
        </div>

        <div v-if="wsTab === 'outline'" class="ws-body">
          <p v-if="!outlineDraft.length" class="empty">暂无大纲：先在对话里走完大纲阶段，规格会自动同步到这里审核编辑。</p>
          <div v-else class="ol-list">
            <div v-for="(o, i) in outlineDraft" :key="o.id ?? i" class="ol-item">
              <span class="ol-no">{{ i + 1 }}</span>
              <div class="ol-fields">
                <input v-model="o.title" class="ol-title" maxlength="80" @input="outlineDirty = true" />
                <input v-model="o.note" class="ol-note" placeholder="备注（讲什么/用什么图，可空）" @input="outlineDirty = true" />
              </div>
              <div class="ol-ops">
                <button title="上移" @click="outlineMove(i, -1)">↑</button>
                <button title="下移" @click="outlineMove(i, 1)">↓</button>
                <button title="删除" class="danger" @click="outlineDraft.splice(i, 1); outlineDirty = true">×</button>
              </div>
            </div>
          </div>
          <div v-if="sectionPreview.length" class="ws-label">已生成文案（{{ sectionPreview.length }}），可展开查看、直接改</div>
          <div v-if="sectionPreview.length" class="sec-edit-list">
            <div v-for="(s, i) in sectionPreview" :key="s.id ?? i" class="sec-edit-card">
              <button class="sec-edit-head" @click="s.open = !s.open">
                <b>{{ i + 1 }}. {{ s.title || '未命名页面' }}</b><span>{{ s.open ? '收起' : '展开' }}</span>
              </button>
              <div v-if="s.open" class="sec-edit-body">
                <input v-model="s.title" class="kb-input" placeholder="页面标题" maxlength="80" @input="markSectionDirty" />
                <textarea v-model="s.body" rows="4" class="kb-input" placeholder="本页文案要点" @input="markSectionDirty" />
              </div>
            </div>
            <button class="btn primary sm" :disabled="streaming" @click="sendSectionsToAgent">文案发给 Agent 确认</button>
          </div>
          <div v-if="outlineDraft.length" class="ws-foot">
            <button class="mini-btn" @click="outlineAdd">+ 加一页</button>
            <button class="btn primary sm" :disabled="streaming" @click="sendOutlineToAgent">发送给 Agent 确认</button>
          </div>
        </div>

        <div v-if="wsTab === 'material'" class="ws-body">
          <div class="ws-label-row">
            <span class="ws-label">本次引用的报告 / 评估</span>
            <button class="mini-btn" @click="matPicking ? (matPicking = false) : openMatPicker()">
              {{ matPicking ? '取消' : (material.length ? '更换素材' : '选择素材') }}
            </button>
          </div>
          <div v-if="matPicking" class="mat-picker">
            <p v-if="matLoading" class="empty">加载中…</p>
            <template v-else-if="activeConv?.agent_id === 'report_ppt'">
              <div class="mat-filters">
                <select v-model="matType" class="kb-input">
                  <option v-for="t in REPORT_TYPES" :key="t.value" :value="t.value">{{ t.label }}</option>
                </select>
                <div class="mat-dates">
                  <input v-model="matStart" type="date" class="kb-input" title="起始日期" />
                  <span>~</span>
                  <input v-model="matEnd" type="date" class="kb-input" title="结束日期" />
                </div>
              </div>
              <div class="mat-select-head">
                <button class="mini-btn" @click="toggleSelectAllFiltered">
                  {{ allFilteredSelected ? '取消全选' : '全选当前筛选' }}
                </button>
                <span class="mat-count">已选 {{ pickReportIds.length }} 份（可多选）</span>
              </div>
              <div class="mat-options">
                <label
                  v-for="r in filteredReports"
                  :key="r.id"
                  class="mat-option"
                  :class="{ on: pickReportIds.includes(r.id) }"
                >
                  <input
                    type="checkbox"
                    :checked="pickReportIds.includes(r.id)"
                    @change="toggleReportPick(r.id)"
                  />
                  <span class="mat-option-text">
                    <b>{{ r.title }}</b>
                    <span>{{ r.type }} · {{ r.period }}</span>
                  </span>
                </label>
              </div>
              <p v-if="!reportOptions.length" class="empty">暂无我的报告，先去「报告总结」创建</p>
              <p v-else-if="!filteredReports.length" class="empty">当前筛选无匹配报告，换个条件试试</p>
            </template>
            <template v-else>
              <select v-model="pickClassId" class="kb-input">
                <option value="" disabled>选择一个班级</option>
                <option v-for="c in classOptions" :key="c.id" :value="c.id">{{ c.name }}</option>
              </select>
              <p v-if="!classOptions.length" class="empty">暂无班级，先去「班级管理」创建</p>
            </template>
            <button
              class="btn primary sm"
              :disabled="activeConv?.agent_id === 'report_ppt' ? !pickReportIds.length : !pickClassId"
              @click="confirmMatPick"
            >
              绑定到本会话
            </button>
          </div>
          <p v-if="!material.length && !matPicking" class="empty">当前会话未绑定业务数据，可直接在上方选择，无需跳转模块。</p>
          <div v-for="m in material" :key="m.kind + m.id" class="mat-card">
            <b>{{ m.title }}</b>
            <span>{{ m.kind === 'report' ? '报告' : m.kind === 'class' ? '班级' : '上下文' }}{{ m.type ? ` · ${m.type}` : '' }}{{ m.period ? ` · ${m.period}` : '' }}</span>
            <span v-if="m.stat_count" class="kb-file">统计指标 {{ m.stat_count }} 项</span>
          </div>
          <div class="ws-label">对话中引用的知识库片段（{{ usedCitations.length }}）</div>
          <p v-if="!usedCitations.length" class="empty">暂无引用。打开「引用知识库」后再提问会自动检索。</p>
          <div v-for="(c, i) in usedCitations" :key="i" class="cite">
            <div class="cite-head">《{{ c.title }}》<span v-if="c.similarity != null" class="sim">{{ c.similarity }}</span></div>
            <p>{{ c.text.slice(0, 120) }}</p>
          </div>
        </div>

        <div v-if="wsTab === 'result'" class="ws-body">
          <div class="ws-label">人工审核后生成（可反复修改大纲再生成）</div>
          <input v-model="pptTitle" class="kb-input" placeholder="PPT 标题" maxlength="80" />
          <div class="theme-row">
            <button
              v-for="t in [{ id: 'brand', label: '品牌紫' }, { id: 'cyan', label: '天青' }, { id: 'deep', label: '深邃' }]"
              :key="t.id"
              class="mini-btn"
              :class="{ on: pptTheme === t.id }"
              @click="pptTheme = t.id"
            >{{ t.label }}</button>
          </div>
          <button class="btn primary" :disabled="building || !outlineDraft.length" @click="doBuildPpt()">
            {{ building ? '生成中…' : `生成 PPT${outlineDraft.length ? `（${outlineDraft.length} 页）` : ''}` }}
          </button>
          <p v-if="wsError" class="error">{{ wsError }}</p>
          <div v-if="pptResult" class="ppt-done">
            <b>已生成 · 共 {{ pptResult.pages }} 页（含封面结尾）</b>
            <a class="result-download" :href="pptResult.download" target="_blank" download>下载 .pptx</a>
          </div>
          <p v-if="!outlineDraft.length" class="empty">还没有可用大纲，无法生成。</p>
        </div>
      </aside>
    </div>

    <!-- 自定义 Agent 表单 -->
    <div v-if="showAgentForm" class="overlay" @click.self="showAgentForm = false">
      <div class="modal wide">
        <h2>{{ editingAgent ? '编辑 Agent' : '新建 Agent' }}</h2>
        <label>名称<input v-model="agentForm.name" class="kb-input" maxlength="64" placeholder="如：续费跟进助手" /></label>
        <label>描述<input v-model="agentForm.description" class="kb-input" maxlength="256" placeholder="一句话说明用途" /></label>
        <label>系统提示词<textarea v-model="agentForm.system_prompt" rows="4" class="kb-input" placeholder="这个 Agent 的角色、语气、回答要求…" /></label>
        <label class="check-line"><input v-model="agentForm.supports_rag" type="checkbox" /> 支持引用知识库（RAG）</label>
        <div class="pick-group">
          <b>绑定 MCP（单独作用于此 Agent，全局默认会自动叠加）</b>
          <div class="pick-list">
            <label v-for="m in mcps" :key="m.id" class="pick-item">
              <input type="checkbox" :checked="agentForm.mcp_ids.includes(m.id)" @change="agentForm.mcp_ids = toggleAgentPick(agentForm.mcp_ids, m.id)" />
              {{ m.name }}
            </label>
            <span v-if="!mcps.length" class="empty">暂无 MCP，先去 MCP 页新建</span>
          </div>
        </div>
        <div class="pick-group">
          <b>绑定 Skill</b>
          <div class="pick-list">
            <label v-for="s in skills" :key="s.id" class="pick-item">
              <input type="checkbox" :checked="agentForm.skill_ids.includes(s.id)" @change="agentForm.skill_ids = toggleAgentPick(agentForm.skill_ids, s.id)" />
              {{ s.name }}
            </label>
            <span v-if="!skills.length" class="empty">暂无 Skill，先去 Skill 页新建</span>
          </div>
        </div>
        <p v-if="extError" class="error">{{ extError }}</p>
        <div class="modal-actions">
          <button class="btn ghost" @click="showAgentForm = false">取消</button>
          <button class="btn primary" @click="saveAgent()">保存</button>
        </div>
      </div>
    </div>

    <!-- MCP 表单 -->
    <div v-if="showMcpForm" class="overlay" @click.self="showMcpForm = false">
      <div class="modal">
        <h2>{{ editingMcp ? '配置 MCP' : '新建 MCP' }}</h2>
        <label>名称<input v-model="mcpForm.name" class="kb-input" maxlength="64" /></label>
        <label>类型
          <select v-model="mcpForm.kind" class="kb-input">
            <option value="streamable_http">MCP StreamableHTTP（高德/标准 MCP 服务）</option>
            <option value="http">普通 HTTP（POST webhook）</option>
          </select>
        </label>
        <label>Endpoint<input v-model="mcpForm.endpoint" class="kb-input" placeholder="https://…（对话中按需 POST 调用）" /></label>
        <label>描述<input v-model="mcpForm.description" class="kb-input" maxlength="256" placeholder="这个工具能做什么" /></label>
        <label class="check-line"><input v-model="mcpForm.enabled" type="checkbox" /> 启用</label>
        <div class="modal-actions">
          <button class="btn ghost" @click="showMcpForm = false">取消</button>
          <button class="btn primary" @click="saveMcp()">保存</button>
        </div>
      </div>
    </div>

    <!-- MCP 测试结果 -->
    <div v-if="showMcpTest" class="overlay" @click.self="showMcpTest = false">
      <div class="modal wide">
        <h2>测试连接：{{ mcpTestTarget?.name }}</h2>
        <p v-if="mcpTestLoading" class="empty">握手 + 获取工具清单中…</p>
        <template v-else-if="mcpTestResult">
          <div class="test-status" :class="mcpTestResult.ok ? 'ok' : 'fail'">
            {{ mcpTestResult.ok ? '✓ 连接成功' : '✕ 连接失败' }}
          </div>
          <div v-if="mcpTestResult.tools.length" class="pick-group">
            <b>可用工具（{{ mcpTestResult.tools.length }}）</b>
            <div v-for="t in mcpTestResult.tools" :key="t.name" class="tool-row">
              <b>{{ t.name }}</b><span>{{ t.description }}</span>
            </div>
          </div>
          <div class="pick-group">
            <b>调用链路</b>
            <div v-for="(s, i) in mcpTestResult.trace" :key="i" class="trace-row" :class="s.ok ? 'ok' : 'fail'">
              <span class="trace-step">{{ s.step }}</span>
              <span class="trace-detail">{{ s.detail }}</span>
              <span class="trace-ms">{{ s.ms }}ms</span>
            </div>
          </div>
        </template>
        <div class="modal-actions">
          <button class="btn primary" @click="showMcpTest = false">关闭</button>
        </div>
      </div>
    </div>

    <!-- Skill 表单 -->
    <div v-if="showSkillForm" class="overlay" @click.self="showSkillForm = false">
      <div class="modal">
        <h2>{{ editingSkill ? '配置 Skill' : '新建 Skill' }}</h2>
        <label>名称<input v-model="skillForm.name" class="kb-input" maxlength="64" /></label>
        <label>描述<input v-model="skillForm.description" class="kb-input" maxlength="256" /></label>
        <label>指令内容<textarea v-model="skillForm.content" rows="5" class="kb-input" placeholder="追加进系统提示的指令，如：回答先给结论再列依据…" /></label>
        <label class="check-line"><input v-model="skillForm.enabled" type="checkbox" /> 启用</label>
        <div class="modal-actions">
          <button class="btn ghost" @click="showSkillForm = false">取消</button>
          <button class="btn primary" @click="saveSkill()">保存</button>
        </div>
      </div>
    </div>

    <!-- Skill 删除确认 -->
    <div v-if="deletingSkill" class="overlay" @click.self="deletingSkill = null">
      <div class="modal danger-modal">
        <div class="danger-ico">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" /></svg>
        </div>
        <h2>删除 Skill？</h2>
        <p class="danger-text">将删除「<b>{{ deletingSkill.name }}</b>」及其全部 {{ (deletingSkill.files ?? []).length }} 个配套文件，已绑定该 Skill 的 Agent 与全局配置将自动失效该项。此操作不可恢复。</p>
        <div class="modal-actions">
          <button class="btn ghost" @click="deletingSkill = null">取消</button>
          <button class="btn danger-solid" @click="removeSkill()">确认删除</button>
        </div>
      </div>
    </div>

    <!-- 脚本运行弹窗（含参数） -->
    <div v-if="runTarget" class="overlay" @click.self="runTarget = null">
      <div class="modal">
        <h2>运行脚本</h2>
        <div class="run-path">{{ runTarget.path }}</div>
        <label>运行参数（空格分隔，如 <code>docs/README.md --fix</code>；不需要可留空）
          <input v-model="runArgs" class="kb-input" placeholder="check_annotations.py 需要 path 参数，如 docs/README.md" @keydown.enter="confirmRun()" />
        </label>
        <p class="run-provider">经由：{{ sandbox.provider === 'bailian' ? '百炼沙箱' : '本地沙箱' }}（Skill 页沙箱配置区可切换）</p>
        <p v-if="runTarget && (runTarget.s.files ?? []).some((f) => String(f).split('/').pop()?.toLowerCase().startsWith('requirements'))" class="run-provider">检测到 requirements.txt：百炼沙箱会先自动 pip 安装依赖再运行（模板网络白名单需放行 pypi）</p>
        <div v-if="skillRunOut && skillRunOut.skillId === runTarget.s.id" class="skill-runout" :class="{ fail: !skillRunOut.ok }">
          <b>{{ skillRunOut.ok ? '运行成功' : '运行失败' }}</b>
          <span v-if="skillRunOut.deps" class="runout-tip">✓ {{ skillRunOut.deps }}</span>
          <details v-if="skillRunOut.phases?.length" class="runout-steps">
            <summary>执行过程（{{ skillRunOut.phases.length }} 步）· 含 sandboxID 与依赖日志</summary>
            <div v-for="(p, i) in skillRunOut.phases" :key="i" class="runout-step">{{ p }}</div>
            <pre v-if="skillRunOut.deps_log">{{ skillRunOut.deps_log }}</pre>
          </details>
          <pre v-if="skillRunOut.stdout">{{ skillRunOut.stdout }}</pre>
          <pre v-if="skillRunOut.stderr" class="err">{{ skillRunOut.stderr }}</pre>
        </div>
        <div class="modal-actions">
          <button class="btn ghost" @click="runTarget = null">关闭</button>
          <button class="btn primary" :disabled="runLoading" @click="confirmRun()">{{ runLoading ? '运行中…' : '运行' }}</button>
        </div>
      </div>
    </div>

    <!-- Skill 文件预览 -->
    <div v-if="skillPreview" class="overlay" @click.self="skillPreview = null">
      <div class="modal wide">
        <h2>{{ skillPreview.path }}</h2>
        <pre class="file-preview">{{ skillPreview.text }}</pre>
        <div class="modal-actions">
          <button class="btn primary" @click="skillPreview = null">关闭</button>
        </div>
      </div>
    </div>

    <!-- 自建 Agent 管理入口（对话 tab 下的列表）：纵向列表保证按钮永不挤压 -->
    <div v-if="tab === 'chat' && customAgents.length" class="custom-manage">
      <span class="custom-manage-title">自建 Agent（{{ customAgents.length }}）</span>
      <div class="custom-chips col">
        <div v-for="c in customAgents" :key="c.agent_id" class="custom-row">
          <span class="custom-chip-name">{{ c.name }}</span>
          <span class="custom-row-ops">
            <button class="custom-chip-btn" title="查看配置" @click="openAgentEdit(c); showAgentForm = true">查看配置</button>
            <button title="删除" class="custom-chip-btn danger" @click="removeAgent(c)">删除</button>
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.agents-page { display: flex; flex-direction: column; gap: 16px; }

/* —— 通用按钮（本页） —— */
.btn {
  display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  border: 1px solid var(--line); background: var(--surface); border-radius: var(--radius-sm);
  padding: 9px 18px; font-size: 13px; font-weight: 600; color: var(--ink-2); cursor: pointer; transition: all .15s;
}
.btn:hover:not(:disabled) { border-color: var(--brand); color: var(--brand-strong); }
.btn:disabled { opacity: .55; cursor: not-allowed; }
.btn.primary { border: none; background: var(--brand-gradient); color: #fff; box-shadow: var(--shadow-brand); }
.btn.primary:hover:not(:disabled) { color: #fff; filter: brightness(1.05); }

/* —— 顶部 slim —— */
.hero {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  padding: 8px 14px; border-radius: var(--radius-lg);
  background: var(--brand-gradient-soft); border: 1px solid var(--line);
}
.hero h2 { margin: 0; font-size: 15px; }
.hero-mark.sm { width: 30px; height: 30px; border-radius: 9px; }
.hero-mark.sm svg { width: 15px; height: 15px; }
.hero-stats.inline { display: flex; align-items: center; gap: 12px; margin-left: 6px; }
.stat-i { font-size: 11.5px; color: var(--ink-3); }
.stat-i b { font-size: 13px; color: var(--brand-strong); margin-right: 2px; }
.hero-spacer { flex: 1; }
.pill-btn.sm { padding: 5px 12px; font-size: 12px; }
.hero-left { display: flex; align-items: center; gap: 14px; }
.hero-mark {
  width: 44px; height: 44px; flex-shrink: 0; display: flex; align-items: center; justify-content: center;
  color: #fff; border-radius: 13px; background: var(--brand-gradient); box-shadow: var(--shadow-brand);
}
.hero-mark svg { width: 22px; height: 22px; }
.hero h2 { margin: 0; font-size: 19px; }
.sub { margin: 3px 0 0; font-size: 12.5px; color: var(--ink-3); }
.back-btn {
  width: 34px; height: 34px; flex-shrink: 0; display: flex; align-items: center; justify-content: center;
  border: 1px solid var(--line); background: var(--surface); border-radius: 10px; color: var(--ink-2); cursor: pointer; transition: all .15s;
}
.back-btn:hover { border-color: var(--brand); color: var(--brand-strong); }
.back-btn svg { width: 16px; height: 16px; }
.hero-stats { display: flex; align-items: center; gap: 18px; }
.stat { display: flex; flex-direction: column; align-items: center; line-height: 1.15; }
.stat b { font-size: 18px; color: var(--brand-strong); }
.stat span { font-size: 11px; color: var(--ink-3); }
.pill-btn {
  border: 1px solid var(--line); background: var(--surface); border-radius: var(--radius-pill);
  padding: 7px 16px; font-size: 12.5px; font-weight: 600; color: var(--ink-2); cursor: pointer; transition: all .15s;
}
.pill-btn:hover { border-color: var(--brand); color: var(--brand-strong); }
.pill-btn.on { background: var(--brand-soft); border-color: var(--brand); color: var(--brand-strong); }

/* —— 布局（定高内滚：聊天滚动、输入框永远钉在底部；杜绝页面级横向滚动） —— */
.agents-page { min-width: 0; overflow-x: clip; }
.agents-layout { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 16px; align-items: stretch; }
.agents-layout:has(.ws-side), .agents-layout:has(.ws-rail) { grid-template-columns: auto minmax(0, 1fr) auto; }
.agents-side { width: 300px; }
.agents-side.rail { width: 56px; padding: 12px 8px; align-items: center; }
.side-full { display: flex; flex-direction: column; gap: 14px; min-height: 0; flex: 1; width: 100%; }
.side-rail { display: flex; flex-direction: column; gap: 8px; align-items: center; }
.icon-btn.rail-btn { width: 34px; height: 34px; border-radius: 10px; }
.icon-btn.rail-btn svg { width: 17px; height: 17px; }
.icon-btn.rail-btn.on { border-color: var(--brand); color: var(--brand-strong); background: var(--brand-soft); }
.icon-btn.rail-btn.accent { background: var(--brand-gradient); border: none; color: #fff; }
.icon-btn.rail-btn.accent:disabled { opacity: .45; }
.ws-rail {
  display: flex; flex-direction: column; align-items: center; gap: 8px; padding: 12px 6px;
  background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-lg);
  height: calc(100vh - 158px); min-height: 480px; max-height: calc(100vh - 110px);
}
.agents-side {
  display: flex; flex-direction: column; gap: 14px; padding: 16px; min-width: 0; overflow: hidden;
  background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-lg); box-shadow: var(--shadow-sm);
  height: calc(100vh - 158px); min-height: 480px; max-height: calc(100vh - 110px);
}
.side-head { display: flex; align-items: center; justify-content: space-between; }
/* 下拉区：选择 Agent / 对话历史可收起展开 */
.drop { display: flex; flex-direction: column; min-height: 0; border: 1px solid var(--line); border-radius: var(--radius); background: var(--surface); overflow: hidden; flex-shrink: 0; }
.drop.grow { flex: 1; }
.drop-head {
  display: flex; align-items: center; gap: 8px; width: 100%; cursor: pointer;
  border: none; background: transparent; padding: 9px 10px; font-size: 13px; font-weight: 700; color: var(--ink-1); transition: background .15s;
}
.drop-head:hover { background: var(--bg-soft); }
.drop-title { flex: 1; text-align: left; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.drop-ico { width: 16px; height: 16px; color: var(--ink-3); flex-shrink: 0; }
.chev { width: 15px; height: 15px; color: var(--ink-3); flex-shrink: 0; transition: transform .2s; }
.chev.open { transform: rotate(180deg); }
.drop-body { border-top: 1px solid var(--line-soft); padding: 8px; overflow-y: auto; min-height: 0; }
.drop-body.grow { flex: 1; display: flex; flex-direction: column; }
.agent-ico.sm { width: 28px; height: 28px; border-radius: 8px; }
.agent-ico.sm svg { width: 15px; height: 15px; }
.icon-btn {
  width: 26px; height: 26px; flex-shrink: 0; display: inline-flex; align-items: center; justify-content: center;
  border: 1px solid var(--line); background: var(--surface); border-radius: 8px; color: var(--ink-3); cursor: pointer; transition: all .15s;
}
.icon-btn:hover { border-color: var(--brand); color: var(--brand-strong); }
.icon-btn svg { width: 14px; height: 14px; }
.side-block { display: flex; flex-direction: column; gap: 10px; min-height: 0; }
.side-block.grow { flex: 1; min-height: 0; }
.side-label { font-size: 11.5px; font-weight: 700; color: var(--ink-3); text-transform: uppercase; letter-spacing: .05em; }

.agent-list { display: flex; flex-direction: column; gap: 8px; }
.agent-card {
  display: flex; align-items: center; gap: 10px; text-align: left; cursor: pointer;
  padding: 10px 12px; border: 1px solid var(--line); border-radius: var(--radius); background: var(--surface); transition: all .18s;
}
.agent-card:hover { border-color: var(--brand); transform: translateY(-1px); box-shadow: var(--shadow-sm); }
.agent-card.on { border-color: var(--brand); background: var(--brand-soft); box-shadow: 0 0 0 3px var(--brand-glow); }
.agent-ico {
  width: 36px; height: 36px; flex-shrink: 0; display: flex; align-items: center; justify-content: center;
  border-radius: 10px; color: var(--brand-strong); background: var(--brand-soft);
}
.agent-card.on .agent-ico { color: #fff; background: var(--brand-gradient); }
.agent-ico svg { width: 19px; height: 19px; }
.agent-text { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 1px; }
.agent-text b { font-size: 13.5px; }
.agent-text span { font-size: 11.5px; color: var(--ink-3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.agent-rag { width: 15px; height: 15px; color: var(--accent); flex-shrink: 0; }

.new-conv {
  display: flex; align-items: center; justify-content: center; gap: 8px; padding: 11px;
  border: none; border-radius: var(--radius); background: var(--brand-gradient); color: #fff;
  font-size: 13.5px; font-weight: 700; cursor: pointer; box-shadow: var(--shadow-brand); transition: all .18s;
}
.new-conv:hover:not(:disabled) { transform: translateY(-1px); filter: brightness(1.04); }
.new-conv:disabled { opacity: .55; cursor: not-allowed; box-shadow: none; }
.new-conv svg { width: 16px; height: 16px; }

.conv-list { overflow-y: auto; display: flex; flex-direction: column; gap: 12px; padding-right: 2px; }
.conv-group { display: flex; flex-direction: column; gap: 3px; }
.conv-group-title {
  display: flex; align-items: center; gap: 6px; font-size: 11.5px; font-weight: 700; color: var(--ink-3);
  padding: 3px 4px; border: none; background: transparent; cursor: pointer; border-radius: var(--radius-sm); width: 100%; text-align: left;
}
.conv-group-title:hover { background: var(--bg-soft); color: var(--ink-2); }
.conv-group-title .chev { width: 13px; height: 13px; flex-shrink: 0; transition: transform .2s; }
.conv-group-title .chev.open { transform: rotate(0); }
.conv-group-title .chev:not(.open) { transform: rotate(-90deg); }
.group-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.group-count { font-size: 10.5px; color: var(--ink-light); background: var(--bg-soft); border-radius: 999px; padding: 0 6px; }
.conv-item {
  display: flex; align-items: center; gap: 6px; padding: 7px 10px; border: none; background: transparent;
  border-radius: var(--radius-sm); cursor: pointer; font-size: 13px; color: var(--ink-2); transition: all .15s; text-align: left;
}
.conv-item:hover { background: var(--bg-soft); }
.conv-item.on { background: var(--brand-soft); color: var(--brand-strong); font-weight: 600; }
.conv-title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.conv-rag { font-size: 9.5px; font-weight: 700; color: var(--accent-strong); background: var(--accent-soft); padding: 1px 5px; border-radius: 4px; flex-shrink: 0; }
.conv-more {
  display: none; align-items: center; justify-content: center; flex-shrink: 0;
  width: 24px; height: 24px; border-radius: 6px; color: var(--ink-3); cursor: pointer;
}
.conv-more:hover { background: var(--brand-soft); color: var(--brand-strong); }
.conv-item:hover .conv-more { display: inline-flex; }
.conv-more svg { width: 15px; height: 15px; }
.conv-check { flex-shrink: 0; width: 14px; height: 14px; accent-color: var(--brand); cursor: pointer; }
.conv-pin { flex-shrink: 0; font-size: 12px; }
.conv-rename { display: flex; gap: 4px; flex: 1; min-width: 0; }
.conv-rename input { flex: 1; min-width: 0; border: 1px solid var(--brand); border-radius: 6px; padding: 2px 6px; font-size: 12px; }
.conv-menu {
  position: fixed; z-index: 300; display: flex; flex-direction: column; min-width: 140px;
  background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-sm);
  box-shadow: var(--shadow); padding: 4px;
}
.conv-menu button {
  border: none; background: transparent; text-align: left; cursor: pointer;
  padding: 7px 10px; font-size: 12.5px; color: var(--ink-1); border-radius: 6px;
}
.conv-menu button:hover { background: var(--bg-soft); }
.conv-menu button.danger { color: var(--danger); }
.conv-menu button.danger:hover { background: var(--danger-soft); }
.multi-bar { display: flex; align-items: center; gap: 6px; padding: 6px 8px; font-size: 12px; color: var(--ink-2); border-bottom: 1px solid var(--line-soft); }
.multi-bar span { flex: 1; }

/* —— 主区 —— */
.agents-main {
  display: flex; flex-direction: column; min-width: 0; overflow: hidden; padding: 16px;
  height: calc(100vh - 158px); min-height: 480px; max-height: calc(100vh - 110px);
  background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-lg); box-shadow: var(--shadow-sm);
}
.seg { display: inline-flex; gap: 4px; padding: 4px; background: var(--bg-soft); border-radius: var(--radius-pill); align-self: flex-start; margin-bottom: 14px; flex-shrink: 0; }
.kb-scroll { overflow-y: auto; min-height: 0; padding-bottom: 4px; }
.kb-upload { flex-shrink: 0; }
.roadmap, .stage-guide, .chat-top { flex-shrink: 0; }
.seg button {
  display: flex; align-items: center; gap: 6px; border: none; background: transparent; cursor: pointer;
  padding: 7px 16px; border-radius: var(--radius-pill); font-size: 13px; font-weight: 600; color: var(--ink-3); transition: all .18s;
}
.seg button svg { width: 15px; height: 15px; }
.seg button.on { background: var(--surface); color: var(--brand-strong); box-shadow: var(--shadow-xs); }

.memory-panel { border: 1px solid var(--brand); background: var(--brand-soft); border-radius: var(--radius); padding: 12px 14px; margin-bottom: 12px; font-size: 13px; }
.memory-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; font-weight: 700; color: var(--brand-strong); }
.memory-hint { font-size: 11px; font-weight: 500; color: var(--ink-3); }
.memory-panel ul { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 6px; }
.memory-panel li { display: flex; align-items: baseline; gap: 8px; background: var(--surface); border-radius: var(--radius-sm); padding: 6px 10px; }
.memory-panel li b { color: var(--ink); flex-shrink: 0; }
.memory-panel li span { color: var(--ink-2); flex: 1; }
.chip-del { border: none; background: transparent; color: var(--ink-light); cursor: pointer; font-size: 15px; }
.chip-del:hover { color: var(--danger); }

.empty, .empty-hero { color: var(--ink-3); font-size: 13px; }
.empty { text-align: center; padding: 8px 0; }
.empty-hero { margin: auto; text-align: center; display: flex; flex-direction: column; align-items: center; gap: 12px; padding: 40px 0; }
.empty-hero h3 { margin: 0; font-size: 17px; color: var(--ink); }
.empty-hero p { margin: 0; max-width: 360px; line-height: 1.7; }
.empty-illu {
  width: 72px; height: 72px; display: flex; align-items: center; justify-content: center;
  border-radius: 22px; color: #fff; background: var(--brand-gradient); box-shadow: var(--shadow-brand);
}
.empty-illu svg { width: 34px; height: 34px; }

.chat-top { display: flex; align-items: center; justify-content: flex-end; gap: 10px; padding-bottom: 8px; border-bottom: 1px solid var(--line-soft); margin-bottom: 6px; }

/* —— 执行链路路线图（紧凑化：不挤压对话区） —— */
.roadmap { display: flex; gap: 2px; overflow-x: auto; padding: 2px 2px 6px; margin-bottom: 0; }
.road-step {
  flex: 1 0 auto; min-width: 0; display: flex; align-items: center; gap: 5px; cursor: pointer;
  border: none; background: transparent; padding: 2px 4px; border-radius: var(--radius-sm); transition: background .15s;
}
.road-step:hover { background: var(--bg-soft); }
.road-step:not(:last-child) .road-label::after {
  content: ''; display: inline-block; width: 8px; height: 1.5px; background: var(--line); margin-left: 6px; vertical-align: middle;
}
.road-dot {
  width: 18px; height: 18px; flex-shrink: 0; display: flex; align-items: center; justify-content: center;
  border-radius: 50%; font-size: 10px; font-weight: 700;
  background: var(--bg-soft); color: var(--ink-3);
}
.road-dot svg { width: 11px; height: 11px; }
.road-label { font-size: 11px; color: var(--ink-3); white-space: nowrap; }
.road-step.done .road-dot { background: var(--success-soft); color: #047857; }
.road-step.done .road-label { color: var(--ink-2); }
.road-step.current .road-dot { background: var(--brand-gradient); color: #fff; box-shadow: var(--shadow-brand); }
.road-step.current .road-label { color: var(--brand-strong); font-weight: 700; }

.stage-guide {
  display: flex; align-items: center; gap: 12px; padding: 9px 12px; margin-bottom: 6px;
  border: 1px solid var(--brand); background: var(--brand-soft); border-radius: var(--radius);
}
.stage-guide-text { flex: 1; display: flex; flex-direction: column; gap: 2px; font-size: 13px; }
.stage-guide-text b { color: var(--brand-strong); }
.stage-guide-text span { color: var(--ink-2); font-size: 12.5px; }

/* —— 可执行选项气泡 —— */
.opt-row { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
.opt-btn {
  border: 1px solid var(--brand); background: var(--surface); color: var(--brand-strong);
  border-radius: var(--radius-pill); padding: 6px 14px; font-size: 12.5px; font-weight: 600; cursor: pointer; transition: all .15s;
}
.opt-btn:hover:not(:disabled) { background: var(--brand-soft); transform: translateY(-1px); }
.opt-btn:disabled { opacity: .5; cursor: not-allowed; }
.opt-btn.rec { background: var(--brand-gradient); border: none; color: #fff; box-shadow: var(--shadow-brand); }
.chat-top-title { display: flex; align-items: center; gap: 8px; font-size: 13.5px; font-weight: 700; flex: 1; min-width: 0; }
.dot { width: 8px; height: 8px; border-radius: 50%; background: var(--success); flex-shrink: 0; }
.chat-top-agent { font-size: 11.5px; font-weight: 500; color: var(--ink-3); background: var(--bg-soft); padding: 2px 8px; border-radius: var(--radius-pill); }
.rag-toggle {
  display: flex; align-items: center; gap: 6px; border: 1px solid var(--line); background: var(--surface);
  border-radius: var(--radius-pill); padding: 5px 13px; font-size: 12.5px; color: var(--ink-2); cursor: pointer; transition: all .15s;
}
.rag-toggle svg { width: 14px; height: 14px; }
.rag-toggle.on { background: var(--accent-soft); border-color: var(--accent); color: var(--accent-strong); font-weight: 700; }
.model-switch { padding: 6px 10px; border: 1px solid var(--line); border-radius: 999px; background: var(--surface); font-size: 12.5px; color: var(--ink-2); max-width: 220px; }
.rag-once { font-size: 12.5px; color: var(--ink-3); display: flex; align-items: center; gap: 4px; }

.chat { flex: 1; min-height: 0; overflow-y: auto; overflow-x: hidden; display: flex; flex-direction: column; gap: 14px; padding: 10px 4px; }
.msg { display: flex; gap: 10px; align-items: flex-start; min-width: 0; }
.msg.user { justify-content: flex-end; }
.avatar { width: 30px; height: 30px; flex-shrink: 0; border-radius: 9px; display: flex; align-items: center; justify-content: center; }
.avatar.ai { color: #fff; background: var(--brand-gradient); }
.avatar.ai svg { width: 15px; height: 15px; }
.bubble { max-width: 78%; min-width: 0; padding: 10px 14px; border-radius: 14px; font-size: 13.5px; line-height: 1.68; overflow-wrap: anywhere; word-break: break-word; }
.bubble :deep(pre) { overflow-x: auto; max-width: 100%; }
.bubble :deep(table) { display: block; overflow-x: auto; max-width: 100%; }
.bubble :deep(img) { max-width: 100%; height: auto; }
.bubble :deep(.md-code) {
  background: #0f172a; color: #e2e8f0; border-radius: var(--radius-sm);
  padding: 10px 12px; font-size: 12px; line-height: 1.6; margin: 8px 0;
}
.bubble :deep(.md-code code) { background: transparent; padding: 0; font-family: Consolas, 'Courier New', monospace; white-space: pre; }
.bubble :deep(code) { background: rgba(99, 102, 241, 0.12); padding: 1px 5px; border-radius: 4px; font-size: 12px; font-family: Consolas, 'Courier New', monospace; }
.msg.user .bubble :deep(code) { background: rgba(255, 255, 255, 0.22); }
.bubble :deep(.md-table) { border-collapse: collapse; margin: 8px 0; font-size: 12.5px; }
.bubble :deep(.md-table th), .bubble :deep(.md-table td) { border: 1px solid var(--line); padding: 6px 10px; text-align: left; white-space: nowrap; }
.bubble :deep(.md-table th) { background: var(--brand-soft); color: var(--brand-strong); font-weight: 700; }
.bubble :deep(.md-table tr:nth-child(even) td) { background: var(--surface-alt, #f8faff); }
.bubble :deep(blockquote) { border-left: 3px solid var(--brand); margin: 8px 0; padding: 4px 10px; color: var(--ink-2); background: var(--surface-alt, #f8faff); border-radius: 0 6px 6px 0; }
.bubble :deep(ul), .bubble :deep(ol) { margin: 6px 0; padding-left: 20px; }
.bubble :deep(li) { margin: 2px 0; }
.bubble :deep(h1), .bubble :deep(h2), .bubble :deep(h3), .bubble :deep(h4) { margin: 8px 0 4px; }
.bubble :deep(p) { margin: 4px 0; }
.msg.assistant .bubble { background: var(--bg-soft); border-top-left-radius: 4px; }
.msg.user .bubble { background: var(--brand-gradient); color: #fff; border-top-right-radius: 4px; }
.bubble.streaming { background: var(--brand-soft); }
.thinking-line { display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--brand-strong); font-weight: 600; margin-bottom: 4px; }
.pause-btn { margin-left: auto; border: 1px solid var(--brand); background: var(--surface); color: var(--brand-strong); border-radius: var(--radius-pill); padding: 2px 10px; font-size: 11.5px; cursor: pointer; }
.pause-btn:hover { background: var(--brand-soft); }
.spinner { width: 13px; height: 13px; border-radius: 50%; border: 2px solid var(--brand-glow); border-top-color: var(--brand-strong); animation: spin .8s linear infinite; display: inline-block; }
@keyframes spin { to { transform: rotate(360deg); } }
.cite-drop { margin-top: 10px; border-top: 1px dashed var(--line); padding-top: 6px; }
.cite-drop summary {
  display: inline-flex; align-items: center; gap: 6px; cursor: pointer; user-select: none;
  font-size: 12px; font-weight: 700; color: var(--brand-strong);
  border: 1px solid var(--line); background: var(--surface); border-radius: var(--radius-pill); padding: 3px 12px;
}
.cite-drop summary:hover { border-color: var(--brand); }
.cite-drop summary svg { width: 13px; height: 13px; }
.cite-drop .cite { margin-top: 6px; }
.cite { font-size: 12px; background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-sm); padding: 7px 9px; }
.cite-head { display: flex; align-items: center; gap: 5px; font-weight: 700; color: var(--brand-strong); }
.cite-head svg { width: 13px; height: 13px; }
.sim { margin-left: auto; font-size: 10.5px; font-weight: 600; color: var(--ink-3); background: var(--bg-soft); padding: 1px 6px; border-radius: 4px; }
.cite p { margin: 3px 0 0; color: var(--ink-2); line-height: 1.55; }
/* 业务工具调用轨迹：默认收起，点击展开 */
.tool-drop summary { color: var(--ink-2); }
.tool-drop summary:hover { border-color: var(--accent, #06b6d4); }
.tool-flag { font-size: 10.5px; font-weight: 600; color: #b45309; background: #fef3c7; padding: 1px 7px; border-radius: 4px; }
.tool-meta { font-size: 11.5px; color: var(--ink-3); margin: 6px 0 0; }
.tool-step { margin-top: 6px; font-size: 12px; background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-sm); padding: 7px 9px; }
.tool-step.fail { border-color: #fca5a5; background: #fef2f2; }
.tool-step-head { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.tool-dot { width: 16px; height: 16px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; font-size: 10px; font-weight: 700; color: #fff; }
.tool-dot.ok { background: #10b981; }
.tool-dot.fail { background: #ef4444; }
.tool-step-head b { color: var(--ink-1); }
.tool-args { font-size: 11px; color: var(--ink-3); background: var(--bg-soft); padding: 1px 7px; border-radius: 4px; }
.tool-summary { margin: 5px 0 0; color: var(--ink-2); line-height: 1.55; word-break: break-all; }
.tool-files { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
.file-dl { font-size: 11.5px; font-weight: 700; color: #fff; background: var(--brand); border-radius: 999px; padding: 3px 12px; text-decoration: none; }
.file-dl:hover { filter: brightness(1.1); color: #fff; }
.tool-error { margin: 5px 0 0; color: #b91c1c; line-height: 1.55; }

.error { color: var(--danger); font-size: 12.5px; padding: 4px 0; }
.error-row {
  display: flex; align-items: center; gap: 10px; color: var(--danger); font-size: 12.5px;
  padding: 6px 10px; background: var(--danger-soft); border-radius: var(--radius-sm);
}
.error-row span { flex: 1; }
.retry-btn {
  display: inline-flex; align-items: center; gap: 5px; flex-shrink: 0; cursor: pointer;
  border: 1px solid var(--danger); background: var(--surface); color: var(--danger);
  border-radius: var(--radius-pill); padding: 4px 12px; font-size: 12px; font-weight: 700; transition: all .15s;
}
.retry-btn:hover { background: var(--danger); color: #fff; }
.retry-btn svg { width: 13px; height: 13px; }
.sec-list { display: flex; flex-wrap: wrap; gap: 6px; }
.sec-chip { font-size: 11.5px; color: var(--accent-strong); background: var(--accent-soft); padding: 3px 9px; border-radius: var(--radius-pill); }
.sec-edit-list { display: flex; flex-direction: column; gap: 6px; }
.sec-edit-card { border: 1px solid var(--line); border-radius: var(--radius-sm); overflow: hidden; }
.sec-edit-head { width: 100%; display: flex; align-items: center; justify-content: space-between; gap: 8px; border: none; background: var(--bg-soft); padding: 7px 10px; font-size: 12.5px; cursor: pointer; color: var(--ink-2); }
.sec-edit-head b { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; text-align: left; }
.sec-edit-head span { flex-shrink: 0; font-size: 11px; color: var(--brand-strong); }
.sec-edit-body { display: flex; flex-direction: column; gap: 6px; padding: 8px; }
.sec-edit-body textarea { resize: vertical; min-height: 72px; line-height: 1.6; }
.input-row { display: flex; gap: 8px; align-items: flex-end; border-top: 1px solid var(--line-soft); padding-top: 12px; margin-top: 4px; flex-shrink: 0; }
.input-row textarea {
  flex: 1; resize: none; border: 1px solid var(--line); border-radius: var(--radius); padding: 10px 12px;
  font-size: 13.5px; font-family: inherit; max-height: 120px; transition: border-color .15s;
}
.input-row textarea:focus { outline: none; border-color: var(--brand); box-shadow: 0 0 0 3px var(--brand-glow); }
.send-btn {
  width: 42px; height: 42px; flex-shrink: 0; display: flex; align-items: center; justify-content: center;
  border: none; border-radius: var(--radius); background: var(--brand-gradient); color: #fff; cursor: pointer; transition: all .15s;
}
.send-btn:hover:not(:disabled) { transform: translateY(-1px); filter: brightness(1.05); }
.send-btn:disabled { opacity: .45; cursor: not-allowed; }
.send-btn svg { width: 18px; height: 18px; }
.pause-big {
  display: flex; align-items: center; gap: 6px; flex-shrink: 0; height: 42px; padding: 0 16px;
  border: 1px solid var(--danger); background: var(--danger-soft); color: #b91c1c; border-radius: var(--radius);
  font-size: 13px; font-weight: 700; cursor: pointer; transition: all .15s;
}
.pause-big:hover { background: var(--danger); color: #fff; }
.pause-big svg { width: 15px; height: 15px; }

/* —— 知识库 —— */
.kb-upload { border: 1px solid var(--line); border-radius: var(--radius); padding: 14px; margin-bottom: 14px; background: var(--surface-alt); }
.kb-upload-head { display: flex; align-items: center; gap: 8px; font-size: 14px; font-weight: 700; margin-bottom: 12px; }
.kb-upload-head svg { width: 17px; height: 17px; color: var(--brand-strong); }
.kb-upload-head span { font-size: 11.5px; font-weight: 500; color: var(--ink-3); margin-left: auto; }
.kb-form { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.file-drop {
  grid-column: 1 / -1; display: flex; align-items: center; justify-content: center; gap: 8px; cursor: pointer;
  padding: 14px; border: 1.5px dashed var(--line); border-radius: var(--radius); color: var(--ink-3); font-size: 13px; transition: all .15s;
}
.file-drop:hover { border-color: var(--brand); color: var(--brand-strong); background: var(--brand-soft); }
.file-drop input { display: none; }
.picked { color: var(--brand-strong); font-weight: 600; }
.kb-input { border: 1px solid var(--line); border-radius: var(--radius-sm); padding: 9px 12px; font-size: 13px; font-family: inherit; }
.kb-input:focus { outline: none; border-color: var(--brand); box-shadow: 0 0 0 3px var(--brand-glow); }
.kb-form .btn { grid-column: 1 / -1; justify-self: start; }

.kb-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 12px; }
.kb-card { display: flex; flex-direction: column; gap: 6px; padding: 14px; border: 1px solid var(--line); border-radius: var(--radius); background: var(--surface); transition: all .18s; }
.kb-card:hover { border-color: var(--brand); box-shadow: var(--shadow-sm); transform: translateY(-1px); }
.kb-card-top { display: flex; align-items: center; justify-content: space-between; }
.kb-badge { font-size: 10.5px; font-weight: 700; padding: 2px 8px; border-radius: var(--radius-pill); background: var(--bg-soft); color: var(--ink-3); }
.kb-badge.ready { background: var(--success-soft); color: #047857; }
.kb-badge.failed { background: var(--danger-soft); color: #b91c1c; }
.kb-vis { font-size: 10.5px; font-weight: 700; padding: 2px 8px; border-radius: var(--radius-pill); }
.kb-vis.private { background: var(--bg-soft); color: var(--ink-3); }
.kb-vis.plaza { background: var(--accent-soft); color: var(--accent-strong); }
.kb-vis.mine { background: var(--brand-soft); color: var(--brand-strong); }
.kb-title { font-size: 14px; }
.kb-desc { font-size: 12.5px; color: var(--ink-2); line-height: 1.55; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.kb-file { font-size: 11.5px; color: var(--ink-3); }
.kb-progress { display: flex; flex-direction: column; gap: 4px; margin-top: 2px; }
.kb-progress-track { height: 6px; border-radius: 999px; background: var(--bg-soft); overflow: hidden; }
.kb-progress-fill { height: 100%; border-radius: 999px; background: var(--brand-gradient); transition: width .5s ease; }
.kb-progress-text { font-size: 11px; color: var(--brand-strong); }
.kb-err { font-size: 11.5px; color: var(--danger); }
.kb-ops { display: flex; gap: 6px; margin-top: auto; padding-top: 8px; flex-wrap: wrap; }
.mini-btn {
  border: 1px solid var(--line); background: var(--surface); border-radius: var(--radius-sm); padding: 5px 11px;
  font-size: 12px; font-weight: 600; color: var(--ink-2); cursor: pointer; transition: all .15s;
}
.mini-btn:hover { border-color: var(--brand); color: var(--brand-strong); }
.mini-btn.on { background: var(--brand-soft); border-color: var(--brand); color: var(--brand-strong); }
.mini-btn.warn { border-color: var(--warning); color: #b45309; background: var(--warning-soft); }
.mini-btn.warn:hover { border-color: var(--warning); color: #92400e; }
.mini-btn.danger:hover { border-color: var(--danger); color: var(--danger); background: var(--danger-soft); }
.mini-btn.switch { display: inline-flex; align-items: center; gap: 5px; }
.mini-btn.switch .switch-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--success); }
.mini-btn.switch.off .switch-dot { background: var(--ink-3); }
.mini-btn.switch.off { color: var(--ink-3); }
/* —— 工作区（大纲 / 素材 / 成果） —— */
.ws-side {
  display: flex; flex-direction: column; gap: 10px; padding: 14px; min-width: 0; overflow: hidden;
  background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-lg); box-shadow: var(--shadow-sm);
  height: calc(100vh - 158px); min-height: 480px; max-height: calc(100vh - 110px);
}
.ws-head { display: flex; align-items: baseline; gap: 8px; }
.ws-head b { font-size: 14px; }
.ws-sub { font-size: 11px; color: var(--ink-3); flex: 1; }
.ws-seg { display: flex; gap: 4px; padding: 3px; background: var(--bg-soft); border-radius: var(--radius-pill); flex-shrink: 0; }
.ws-seg button { flex: 1; border: none; background: transparent; cursor: pointer; padding: 6px 4px; border-radius: var(--radius-pill); font-size: 12.5px; font-weight: 600; color: var(--ink-3); }
.ws-seg button.on { background: var(--surface); color: var(--brand-strong); box-shadow: var(--shadow-xs); }
.ws-body { flex: 1; min-height: 0; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; }
.ws-label { font-size: 11.5px; font-weight: 700; color: var(--ink-3); }
.ws-foot { display: flex; gap: 8px; align-items: center; margin-top: auto; padding-top: 8px; position: sticky; bottom: 0; background: var(--surface); }
.btn.sm { padding: 7px 14px; font-size: 12.5px; }
.ol-list { display: flex; flex-direction: column; gap: 6px; }
.ol-item { display: flex; gap: 8px; align-items: flex-start; border: 1px solid var(--line); border-radius: var(--radius-sm); padding: 7px 8px; }
.ol-no { width: 20px; height: 20px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; border-radius: 50%; background: var(--brand-soft); color: var(--brand-strong); font-size: 11px; font-weight: 700; }
.ol-fields { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px; }
.ol-title { border: 1px solid transparent; border-radius: 6px; padding: 3px 6px; font-size: 12.5px; font-weight: 600; width: 100%; }
.ol-title:hover, .ol-title:focus { border-color: var(--line); outline: none; }
.ol-title:focus { border-color: var(--brand); }
.ol-note { border: 1px solid transparent; border-radius: 6px; padding: 3px 6px; font-size: 11.5px; color: var(--ink-2); width: 100%; }
.ol-note:hover, .ol-note:focus { border-color: var(--line); outline: none; }
.ol-note:focus { border-color: var(--brand); }
.ol-ops { display: flex; flex-direction: column; gap: 2px; }
.ol-ops button { border: none; background: transparent; color: var(--ink-3); cursor: pointer; font-size: 12px; line-height: 1.2; padding: 1px 4px; border-radius: 4px; }
.ol-ops button:hover { background: var(--bg-soft); color: var(--brand-strong); }
.ol-ops button.danger:hover { color: var(--danger); background: var(--danger-soft); }
.mat-card { display: flex; flex-direction: column; gap: 2px; border: 1px solid var(--line); border-radius: var(--radius-sm); padding: 8px 10px; font-size: 12.5px; }
.mat-card b { font-size: 13px; }
.mat-card span { color: var(--ink-2); font-size: 12px; }
.ws-label-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.mat-picker { display: flex; flex-direction: column; gap: 8px; border: 1px dashed var(--brand); border-radius: var(--radius-sm); padding: 10px; background: var(--brand-soft); }
.mat-picker select.kb-input { width: 100%; }
.mat-picker .btn { align-self: flex-start; }
.mat-filters { display: flex; flex-direction: column; gap: 6px; }
.mat-dates { display: flex; align-items: center; gap: 6px; }
.mat-dates .kb-input { flex: 1; min-width: 0; }
.mat-dates span { color: var(--ink-3); flex-shrink: 0; }
.mat-select-head { display: flex; align-items: center; gap: 8px; }
.mat-count { font-size: 11.5px; color: var(--ink-3); }
.mat-options { display: flex; flex-direction: column; gap: 4px; max-height: 220px; overflow-y: auto; }
.mat-option {
  display: flex; align-items: center; gap: 8px; padding: 7px 9px; cursor: pointer;
  background: var(--surface); border: 1px solid var(--line-soft); border-radius: var(--radius-sm); transition: all .12s;
}
.mat-option:hover { border-color: var(--brand); }
.mat-option.on { border-color: var(--brand); background: var(--surface); box-shadow: inset 0 0 0 1px var(--brand); }
.mat-option input { flex-shrink: 0; width: 15px; height: 15px; accent-color: var(--brand); cursor: pointer; }
.mat-option-text { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
.mat-option-text b { font-size: 12.5px; color: var(--ink-1); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mat-option-text span { font-size: 11px; color: var(--ink-3); }
.theme-row { display: flex; gap: 6px; }
.ppt-done { display: flex; flex-direction: column; gap: 8px; border: 1px solid var(--success); background: var(--success-soft); border-radius: var(--radius-sm); padding: 10px 12px; font-size: 12.5px; }
.result-download { display: inline-flex; align-items: center; justify-content: center; padding: 8px 14px; border-radius: var(--radius-sm); background: var(--brand-gradient); color: #fff; font-size: 13px; font-weight: 700; text-decoration: none; }
.result-download:hover { filter: brightness(1.05); }

.ext-hero {
  display: flex; align-items: flex-start; justify-content: space-between; gap: 12px;
  padding: 16px 18px; margin-bottom: 14px; border-radius: var(--radius);
  background: linear-gradient(135deg, #eef2ff, #f5f3ff, #ecfeff); border: 1px solid #e0e7ff;
}
.ext-hero b { font-size: 16px; }
.ext-hero p { margin: 4px 0 0; font-size: 12.5px; color: var(--ink-2); max-width: 560px; line-height: 1.6; }
.ext-card { position: relative; }
.glob-check { display: inline-flex; align-items: center; gap: 4px; font-size: 11.5px; font-weight: 700; color: var(--brand-strong); cursor: pointer; }
.glob-check input { accent-color: var(--brand); }
.custom-tag { font-style: normal; font-size: 10px; font-weight: 700; color: var(--brand-strong); background: var(--brand-soft); border-radius: 4px; padding: 1px 5px; margin-left: 6px; }
.manage-agent { align-self: flex-start; margin-bottom: 8px; }
.custom-manage { display: flex; flex-direction: column; align-items: stretch; gap: 8px; padding: 10px 14px; background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); flex-shrink: 0; overflow: visible; }
.custom-manage-title { font-size: 12px; font-weight: 700; color: var(--ink-3); flex-shrink: 0; white-space: nowrap; }
.custom-chips { display: flex; gap: 8px; flex-wrap: wrap; flex: 1; min-width: 0; }
.custom-chips.col { flex-direction: column; align-items: stretch; }
.custom-row { display: flex; align-items: center; gap: 8px; width: 100%; background: var(--brand-soft); border-radius: 10px; padding: 6px 8px 6px 12px; min-width: 0; }
.custom-row-ops { margin-left: auto; display: inline-flex; gap: 6px; flex-shrink: 0; }
.custom-chip { display: inline-flex; align-items: center; gap: 6px; max-width: 100%; font-size: 12.5px; font-weight: 600; background: var(--brand-soft); color: var(--brand-strong); border-radius: 999px; padding: 4px 6px 4px 12px; white-space: nowrap; }
.custom-chip-name { overflow: hidden; text-overflow: ellipsis; max-width: 160px; }
.custom-chip-btn { flex-shrink: 0; border: none; background: var(--surface); border-radius: 999px; padding: 3px 10px; font-size: 11.5px; font-weight: 700; cursor: pointer; color: var(--brand-strong); white-space: nowrap; }
.custom-chip-btn.danger { color: var(--danger); }
.file-chip-wrap { display: inline-flex; align-items: center; gap: 2px; }
.file-run { border: 1px solid var(--line); background: var(--surface); border-radius: 6px; font-size: 10px; cursor: pointer; padding: 2px 6px; color: var(--success, #047857); }
.skill-runout { margin-top: 6px; font-size: 11.5px; border: 1px solid var(--line); border-radius: 8px; padding: 8px; background: #f8fafc; }
.skill-runout.fail { border-color: #fca5a5; background: #fef2f2; }
.skill-runout pre { white-space: pre-wrap; word-break: break-all; margin: 4px 0 0; font-size: 11px; }
.skill-runout pre.err { color: var(--danger); }
.runout-tip { display: block; font-size: 10.5px; font-weight: 500; color: var(--ink-3); margin-top: 2px; }
.runout-tag { display: inline-block; font-size: 10px; font-weight: 800; border-radius: 999px; padding: 1px 8px; margin-left: 6px; background: var(--bg-soft); color: var(--ink-3); }
.runout-tag.remote { background: var(--accent-soft); color: var(--accent-strong); }
.runout-tag.local { background: var(--brand-soft); color: var(--brand-strong); }
.runout-steps { margin-top: 6px; border: 1px dashed var(--line); border-radius: 8px; padding: 4px 8px 8px; }
.runout-steps summary { cursor: pointer; font-size: 11.5px; font-weight: 700; color: var(--brand-strong); }
.runout-step { font-size: 11.5px; color: var(--ink-2); padding: 2px 0; word-break: break-all; }
.run-path { font-size: 12px; color: var(--brand-strong); background: var(--brand-soft); border-radius: 8px; padding: 6px 10px; word-break: break-all; }
.run-provider { font-size: 12px; color: var(--ink-3); margin: 0; }
.sandbox-card { border: 1px solid var(--line); border-radius: var(--radius); margin-bottom: 14px; background: var(--surface-alt); }
.sandbox-head { width: 100%; display: flex; align-items: center; justify-content: space-between; border: none; background: transparent; cursor: pointer; padding: 10px 14px; font-size: 13px; color: var(--ink-1); }
.sandbox-head span { font-size: 12px; color: var(--brand-strong); font-weight: 700; }
.sandbox-body { display: flex; flex-direction: column; gap: 8px; padding: 0 14px 14px; }
.sandbox-desc { font-size: 12px; color: var(--ink-2); line-height: 1.7; margin: 0; }
.sandbox-desc code { background: rgba(99,102,241,.12); padding: 1px 5px; border-radius: 4px; }
.sandbox-row { display: grid; grid-template-columns: 1fr 160px; gap: 8px; }
.sandbox-body label { display: flex; flex-direction: column; gap: 5px; font-size: 12.5px; font-weight: 600; color: var(--ink-2); }
.sandbox-ops { display: flex; align-items: center; gap: 8px; }
.sandbox-msg { font-size: 12px; font-weight: 600; color: var(--brand-strong); }
/* —— 通用渲染格式补齐：徽章/标签/折叠/进度/图表/时间轴/告警/终端 —— */
.bubble :deep(.md-badge) { display: inline-block; font-size: 11px; font-weight: 800; color: #fff; background: var(--brand-gradient); border-radius: 999px; padding: 1px 9px; margin: 0 2px; }
.bubble :deep(.md-tag) { display: inline-block; font-size: 11px; color: var(--brand-strong); background: var(--brand-soft); border-radius: 6px; padding: 1px 8px; margin: 0 2px; }
.bubble :deep(.md-hr) { border: none; border-top: 1px solid var(--line); margin: 10px 0; }
.bubble :deep(.md-math) { font-family: Consolas, monospace; background: rgba(99,102,241,.08); padding: 1px 6px; border-radius: 4px; }
.bubble :deep(.md-math.block) { display: block; text-align: center; padding: 8px; margin: 8px 0; }
.bubble :deep(.md-fold) { border: 1px solid var(--line); border-radius: 8px; margin: 8px 0; background: var(--surface); }
.bubble :deep(.md-fold summary) { cursor: pointer; padding: 7px 11px; font-size: 12.5px; font-weight: 700; color: var(--brand-strong); }
.bubble :deep(.md-fold > div), .bubble :deep(.md-fold > pre) { margin: 0 11px 11px; }
.bubble :deep(.md-copy) { float: right; font-size: 11px; border: 1px solid var(--line); border-radius: 6px; background: var(--surface); cursor: pointer; padding: 1px 8px; }
.bubble :deep(.md-kv-row) { display: flex; gap: 10px; font-size: 12.5px; padding: 4px 0; border-bottom: 1px dashed var(--line); }
.bubble :deep(.md-kv-row b) { min-width: 90px; color: var(--ink-1); }
.bubble :deep(.md-tree) { background: #0f172a; color: #a5f3fc; border-radius: 8px; padding: 10px 12px; font-size: 12px; overflow-x: auto; }
.bubble :deep(.md-terminal) { background: #0f172a; color: #86efac; border-radius: 8px; padding: 10px 12px; font-size: 12px; overflow-x: auto; }
.bubble :deep(.md-alert) { border-radius: 8px; padding: 8px 12px; font-size: 12.5px; margin: 8px 0; }
.bubble :deep(.md-alert.info) { background: #eff6ff; border-left: 3px solid #3b82f6; }
.bubble :deep(.md-alert.warn) { background: #fffbeb; border-left: 3px solid #f59e0b; }
.bubble :deep(.md-alert.error) { background: #fef2f2; border-left: 3px solid #ef4444; }
.bubble :deep(.md-alert.success) { background: #ecfdf5; border-left: 3px solid #10b981; }
.bubble :deep(.md-progress) { display: flex; align-items: center; gap: 8px; margin: 8px 0; font-size: 12px; }
.bubble :deep(.md-progress-track) { flex: 1; height: 8px; background: var(--bg-soft); border-radius: 999px; overflow: hidden; }
.bubble :deep(.md-progress-fill) { height: 100%; background: var(--brand-gradient); border-radius: 999px; }
.bubble :deep(.md-chart-row) { display: flex; align-items: center; gap: 8px; font-size: 12px; margin: 4px 0; }
.bubble :deep(.md-chart-lb) { width: 90px; flex-shrink: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bubble :deep(.md-chart-track) { flex: 1; height: 10px; background: var(--bg-soft); border-radius: 999px; overflow: hidden; }
.bubble :deep(.md-chart-fill) { display: block; height: 100%; background: var(--brand-gradient); }
.bubble :deep(.md-timeline) { border-left: 2px solid var(--brand); margin: 8px 0 8px 6px; padding-left: 12px; display: flex; flex-direction: column; gap: 6px; }
.bubble :deep(.md-tl-item) { display: flex; gap: 8px; font-size: 12.5px; }
.bubble :deep(.md-tl-dot) { width: 8px; height: 8px; border-radius: 50%; background: var(--brand-strong); margin-top: 5px; flex-shrink: 0; }
.bubble :deep(.md-mermaid-head) { font-size: 12px; font-weight: 700; color: var(--brand-strong); margin-bottom: 4px; display: flex; align-items: center; gap: 8px; }
.bubble :deep(.md-mermaid pre) { background: #f8fafc; border: 1px dashed var(--brand); border-radius: 8px; padding: 10px; font-size: 11.5px; overflow-x: auto; }
.bubble :deep(.md-mermaid.rendered pre.mermaid-src) { display: none; }
.bubble :deep(.mermaid-render) { background: #fff; border: 1px solid var(--line); border-radius: 8px; padding: 10px; overflow-x: auto; }
.bubble :deep(.mermaid-render svg) { max-width: 100%; height: auto; }
.bubble :deep(.md-code-wrap) { margin: 8px 0; border-radius: var(--radius-sm); overflow: hidden; border: 1px solid #1e293b; }
.bubble :deep(.md-code-head) { display: flex; align-items: center; justify-content: space-between; background: #1e293b; color: #94a3b8; font-size: 11px; padding: 4px 10px; }
.bubble :deep(.md-code-head .md-copy) { float: none; background: transparent; color: #e2e8f0; border-color: #475569; }
.bubble :deep(.md-code-wrap .md-code) { margin: 0; border-radius: 0; }
.bubble :deep(.md-code.yaml-hl) { color: #bae6fd; }
.bubble :deep(.md-tasks) { list-style: none; padding-left: 4px; }
.bubble :deep(.md-footnotes) { font-size: 11.5px; color: var(--ink-3); border-top: 1px solid var(--line); margin-top: 8px; }
.overlay { position: fixed; inset: 0; background: rgba(15,23,42,.5); display: flex; align-items: center; justify-content: center; z-index: 200; }
.modal { width: 440px; max-width: calc(100vw - 40px); max-height: 86vh; overflow: auto; background: var(--surface); border-radius: 16px; padding: 24px; display: flex; flex-direction: column; gap: 10px; }
.modal.wide { width: 560px; }
.modal h2 { margin: 0 0 6px; font-size: 16px; }
.modal label { display: flex; flex-direction: column; gap: 5px; font-size: 12.5px; font-weight: 600; color: var(--ink-2); }
.check-line { flex-direction: row !important; align-items: center; gap: 6px !important; }
.pick-group b { font-size: 12.5px; }
.pick-list { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
.pick-item { flex-direction: row !important; align-items: center; gap: 5px !important; border: 1px solid var(--line); border-radius: 999px; padding: 4px 10px; font-weight: 500 !important; cursor: pointer; }
.pick-item input { accent-color: var(--brand); }
.mini-btn.accent { border-color: var(--brand); color: var(--brand-strong); background: var(--brand-soft); }
.kb-kind { font-size: 11px; font-weight: 700; color: var(--ink-3); background: #f1f5f9; border-radius: 6px; padding: 2px 8px; display: inline-block; margin-top: 6px; }
.test-status { font-size: 14px; font-weight: 800; border-radius: 10px; padding: 10px 14px; margin-bottom: 10px; }
.test-status.ok { background: #ecfdf5; color: #047857; }
.test-status.fail { background: var(--danger-soft); color: var(--danger); }
.tool-row { display: flex; gap: 8px; align-items: baseline; font-size: 12.5px; padding: 6px 0; border-bottom: 1px dashed var(--line); }
.tool-row b { color: var(--brand-strong); white-space: nowrap; }
.tool-row span { color: var(--ink-3); }
.trace-row { display: flex; gap: 8px; align-items: baseline; font-size: 12px; padding: 6px 8px; border-radius: 8px; margin: 4px 0; background: #f8fafc; }
.trace-row.ok { border-left: 3px solid var(--success); }
.trace-row.fail { border-left: 3px solid var(--danger); }
.trace-step { font-weight: 800; white-space: nowrap; color: var(--ink); }
.trace-row.fail .trace-step { color: var(--danger); }
.trace-detail { flex: 1; color: var(--ink-2); word-break: break-all; line-height: 1.5; }
.trace-ms { color: var(--ink-3); white-space: nowrap; font-size: 11px; }
.skill-files { margin-top: 6px; border: 1px solid var(--line); border-radius: 8px; background: #f8fafc; }
.skill-files summary { cursor: pointer; padding: 6px 10px; font-size: 11.5px; font-weight: 700; color: var(--brand-strong); user-select: none; }
.skill-file-list { display: flex; flex-direction: column; gap: 8px; max-height: 180px; overflow-y: auto; padding: 0 8px 8px; }
.skill-dir { display: block; }
.skill-dir-name { font-size: 11px; font-weight: 800; color: var(--ink-3); padding-top: 4px; margin-bottom: 4px; }
.skill-dir .file-chip-wrap { margin-right: 2px; }
.skill-layout { display: flex; flex-wrap: wrap; gap: 6px; padding: 6px 10px 2px; }
.layout-chip { font-size: 10.5px; font-weight: 700; padding: 2px 9px; border-radius: 999px; background: var(--bg-soft); color: var(--ink-3); }
.layout-chip.ok { background: var(--success-soft); color: #047857; }
.layout-chip.miss { background: var(--danger-soft); color: var(--danger); }
.danger-modal { align-items: center; text-align: center; }
.danger-ico { width: 48px; height: 48px; margin: 0 auto; display: flex; align-items: center; justify-content: center; border-radius: 50%; background: var(--danger-soft); color: var(--danger); }
.danger-ico svg { width: 24px; height: 24px; }
.danger-text { font-size: 13px; color: var(--ink-2); line-height: 1.7; margin: 0; }
.danger-text b { color: var(--danger); }
.btn.danger-solid { border: none; background: var(--danger); color: #fff; }
.btn.danger-solid:hover:not(:disabled) { filter: brightness(1.08); color: #fff; }
.file-chip { border: 1px solid var(--line); background: var(--surface); border-radius: 6px; font-size: 11px; padding: 2px 8px; cursor: pointer; color: var(--brand-strong); max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.file-chip:hover { border-color: var(--brand); }
.file-preview { white-space: pre-wrap; word-break: break-all; font-size: 12px; line-height: 1.6; background: #0f172a; color: #e2e8f0; border-radius: 10px; padding: 14px; max-height: 50vh; overflow: auto; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 8px; }
.btn.ghost { background: var(--surface); border: 1px solid var(--line); }

@media (max-width: 900px) {
  .agents-layout, .agents-layout:has(.ws-side), .agents-layout:has(.ws-rail) { grid-template-columns: 1fr; }
  .agents-side, .agents-side.rail { width: 100%; height: auto; min-height: 0; }
  .side-rail { flex-direction: row; }
  .agents-main, .ws-side, .ws-rail { height: auto; min-height: 0; max-height: none; }
}
</style>
