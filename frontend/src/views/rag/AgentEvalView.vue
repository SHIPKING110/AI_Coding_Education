<script setup lang="ts">
/**
 * Agent 行为评测：工具序列 / 拒答 / 关键事实 的自动化回归。
 * 与检索评测同一权限域（rag_eval_*）；运行由后台线程驱动真实对话链路，进度轮询。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import ConfirmDialog from '@/components/ConfirmDialog.vue'
import PageHead from '@/components/PageHead.vue'
import RagTabs from '@/components/RagTabs.vue'
import { listEvalModels, type RagEvalModel } from '@/api/ragAdmin'
import {
  addCase,
  addCasesBulk,
  compareRuns,
  createRun,
  createSet,
  deleteCase,
  deleteSet,
  getRun,
  listCases,
  listResults,
  listRuns,
  listSets,
  seedDefault,
  setHumanScore,
  updateCase,
  type AgentEvalCase,
  type AgentEvalCompare,
  type AgentEvalResult,
  type AgentEvalRun,
  type AgentEvalSet,
} from '@/api/agentEval'

const loading = ref(false)
const error = ref('')
const msg = ref('')

const sets = ref<AgentEvalSet[]>([])
const activeSet = ref<AgentEvalSet | null>(null)

// —— 用例 ——
const cases = ref<AgentEvalCase[]>([])
const caseTotal = ref(0)
const casePage = ref(1)
const casePageSize = 20

// —— 运行 ——
const runs = ref<AgentEvalRun[]>([])
const runTotal = ref(0)
const runPage = ref(1)
const runPageSize = 10
const activeRun = ref<AgentEvalRun | null>(null)
const results = ref<AgentEvalResult[]>([])
const resultTotal = ref(0)
const resultPage = ref(1)
const resultPageSize = 20
const onlyBad = ref(false)
const compare = ref<AgentEvalCompare | null>(null)
const baseRunId = ref('')
const evalModels = ref<RagEvalModel[]>([])
const runForm = ref<{ model_config_id: string }>({ model_config_id: '' })

const tab = ref<'cases' | 'runs'>('cases')

// —— 用例编辑弹窗 ——
const caseDialog = ref(false)
const caseForm = ref({
  id: '',
  query: '',
  expected_tools: '',
  allowed_extra_tools: '',
  forbidden_tools: '',
  expect_abstain: false,
  expected_facts: '',
  split: 'regression',
  business_criticality: 'normal',
  notes: '',
  messages: '',
})
const bulkDialog = ref(false)
const bulkText = ref('')
const setDialog = ref(false)
const setForm = ref({ name: '', description: '' })

const confirmState = ref({ open: false, title: '', message: '', danger: false, onOk: () => {} })
function confirmWith(title: string, message: string, onOk: () => void, danger = false) {
  confirmState.value = { open: true, title, message, danger, onOk }
}

const isRunning = computed(() => {
  const s = activeRun.value?.status
  return s === 'pending' || s === 'running'
})
const progressPct = computed(() => Math.max(0, Math.min(100, activeRun.value?.progress ?? 0)))
const casePageCount = computed(() => Math.max(1, Math.ceil(caseTotal.value / casePageSize)))
const runPageCount = computed(() => Math.max(1, Math.ceil(runTotal.value / runPageSize)))
const resultPageCount = computed(() => Math.max(1, Math.ceil(resultTotal.value / resultPageSize)))
const gateState = computed(() => activeRun.value?.gate?.gate || '')
const overall = computed(() => activeRun.value?.metrics?.overall || {})
const frozen = computed(() => activeRun.value?.metrics?.splits?.frozen || null)
const baseCandidates = computed(() =>
  runs.value.filter((r) => r.status === 'done' && r.id !== activeRun.value?.id),
)

let pollTimer: number | undefined
let pollRunId = ''
let pollBusy = false

function stopPoll() {
  if (pollTimer !== undefined) {
    window.clearInterval(pollTimer)
    pollTimer = undefined
  }
  pollRunId = ''
  pollBusy = false
}
onBeforeUnmount(stopPoll)

function pct(v: number | null | undefined): string {
  return v == null ? '—' : `${(v * 100).toFixed(1)}%`
}

// —— 加载 ——
async function loadSets() {
  loading.value = true
  error.value = ''
  try {
    sets.value = await listSets()
    if (!activeSet.value && sets.value.length) await selectSet(sets.value[0])
    if (!sets.value.length) {
      cases.value = []
      runs.value = []
      activeRun.value = null
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

async function selectSet(s: AgentEvalSet) {
  activeSet.value = s
  stopPoll()
  activeRun.value = null
  results.value = []
  compare.value = null
  casePage.value = 1
  runPage.value = 1
  await Promise.all([loadCases(), loadRuns()])
}

async function loadCases(page = casePage.value) {
  if (!activeSet.value) return
  try {
    const data = await listCases(activeSet.value.id, { page, page_size: casePageSize })
    cases.value = data.items
    caseTotal.value = data.total
    casePage.value = data.page
  } catch (e) {
    error.value = e instanceof Error ? e.message : '用例加载失败'
  }
}

async function loadRuns(page = runPage.value) {
  if (!activeSet.value) return
  try {
    const data = await listRuns(activeSet.value.id, { page, page_size: runPageSize })
    runs.value = data.items
    runTotal.value = data.total
    runPage.value = data.page
  } catch (e) {
    error.value = e instanceof Error ? e.message : '运行记录加载失败'
  }
}

async function loadEvalModels() {
  try {
    evalModels.value = await listEvalModels()
  } catch {
    evalModels.value = []
  }
  const ids = new Set(evalModels.value.map((m) => m.id))
  if (!ids.has(runForm.value.model_config_id)) {
    runForm.value.model_config_id = evalModels.value[0]?.id || ''
  }
}

async function loadResults(runId: string, page = resultPage.value) {
  try {
    const data = await listResults(runId, {
      page,
      page_size: resultPageSize,
      only_bad: onlyBad.value || undefined,
    })
    results.value = data.items
    resultTotal.value = data.total
    resultPage.value = data.page
  } catch (e) {
    error.value = e instanceof Error ? e.message : '结果加载失败'
  }
}

// —— 运行与轮询 ——
async function startRun() {
  if (!activeSet.value) return
  error.value = ''
  try {
    const run = await createRun(activeSet.value.id, {
      model_config_id: runForm.value.model_config_id || null,
    })
    msg.value = '评测已启动'
    activeRun.value = run
    results.value = []
    resultTotal.value = 0
    compare.value = null
    tab.value = 'runs'
    await loadRuns(1)
    startPoll(run.id)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '启动失败'
  }
}

function startPoll(runId: string) {
  stopPoll()
  pollRunId = runId
  pollTimer = window.setInterval(() => void refreshRun(runId), 2000)
  void refreshRun(runId)
}

async function refreshRun(runId: string) {
  if (pollBusy || pollRunId !== runId) return
  pollBusy = true
  try {
    const data = await getRun(runId)
    if (pollRunId !== runId) return
    activeRun.value = data.run
    if (data.run.status !== 'running' && data.run.status !== 'pending') {
      stopPoll()
      msg.value = data.run.status === 'done' ? '评测完成' : `评测失败：${data.run.error || ''}`
      await Promise.all([loadResults(runId, 1), loadRuns(1)])
    }
  } catch {
    /* 下一轮重试 */
  } finally {
    pollBusy = false
  }
}

async function openRun(run: AgentEvalRun) {
  activeRun.value = run
  compare.value = null
  baseRunId.value = ''
  resultPage.value = 1
  await loadResults(run.id, 1)
  if (run.status === 'running' || run.status === 'pending') startPoll(run.id)
  else stopPoll()
}

async function runCompare() {
  if (!activeRun.value || !baseRunId.value) return
  try {
    compare.value = await compareRuns(activeRun.value.id, baseRunId.value)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '对比失败'
  }
}

// —— 复核 ——
async function markResult(r: AgentEvalResult, score: number) {
  try {
    const updated = await setHumanScore(r.id, { score })
    const idx = results.value.findIndex((x) => x.id === r.id)
    if (idx >= 0) results.value[idx] = updated
  } catch (e) {
    error.value = e instanceof Error ? e.message : '复核失败'
  }
}

// —— 用例维护 ——
function openCaseDialog(c: AgentEvalCase | null) {
  caseForm.value = {
    id: c?.id || '',
    query: c?.query || '',
    expected_tools: (c?.expected_tools || []).join(', '),
    allowed_extra_tools: (c?.allowed_extra_tools || []).join(', '),
    forbidden_tools: (c?.forbidden_tools || []).join(', '),
    expect_abstain: c?.expect_abstain || false,
    expected_facts: (c?.expected_facts || []).join(', '),
    split: c?.split || 'regression',
    business_criticality: c?.business_criticality || 'normal',
    notes: c?.notes || '',
    messages: c?.messages ? JSON.stringify(c.messages, null, 2) : '',
  }
  caseDialog.value = true
}

function splitList(s: string): string[] {
  return s
    .split(/[,，、\n]/)
    .map((x) => x.trim())
    .filter(Boolean)
}

async function saveCase() {
  if (!activeSet.value) return
  if (!caseForm.value.query.trim()) {
    error.value = '问题不能为空'
    return
  }
  let messages: { role: string; content: string }[] | null = null
  if (caseForm.value.messages.trim()) {
    try {
      messages = JSON.parse(caseForm.value.messages)
    } catch {
      error.value = '多轮脚本不是合法 JSON'
      return
    }
  }
  const payload = {
    query: caseForm.value.query.trim(),
    messages,
    expected_tools: splitList(caseForm.value.expected_tools),
    allowed_extra_tools: splitList(caseForm.value.allowed_extra_tools),
    forbidden_tools: splitList(caseForm.value.forbidden_tools),
    expect_abstain: caseForm.value.expect_abstain,
    expected_facts: splitList(caseForm.value.expected_facts),
    split: caseForm.value.split,
    business_criticality: caseForm.value.business_criticality,
    notes: caseForm.value.notes,
  }
  try {
    if (caseForm.value.id) await updateCase(caseForm.value.id, payload)
    else await addCase(activeSet.value.id, payload)
    caseDialog.value = false
    msg.value = '用例已保存'
    await Promise.all([loadCases(), loadSets()])
  } catch (e) {
    error.value = e instanceof Error ? e.message : '保存失败'
  }
}

function removeCase(c: AgentEvalCase) {
  confirmWith('删除用例', `删除后不可恢复：${c.query.slice(0, 40)}…`, async () => {
    try {
      await deleteCase(c.id)
      await Promise.all([loadCases(), loadSets()])
    } catch (e) {
      error.value = e instanceof Error ? e.message : '删除失败'
    }
  }, true)
}

/** 极简 CSV 解析（支持引号转义/换行），返回行数组 */
function parseCsvRows(text: string): string[][] {
  const rows: string[][] = []
  let row: string[] = []
  let cell = ''
  let inQuotes = false
  const src = (text || '').replace(/\r\n?/g, '\n')
  for (let i = 0; i < src.length; i++) {
    const ch = src[i]
    if (inQuotes) {
      if (ch === '"') {
        if (src[i + 1] === '"') {
          cell += '"'
          i++
        } else inQuotes = false
      } else cell += ch
      continue
    }
    if (ch === '"') {
      inQuotes = true
    } else if (ch === ',') {
      row.push(cell)
      cell = ''
    } else if (ch === '\n') {
      row.push(cell)
      rows.push(row)
      row = []
      cell = ''
    } else {
      cell += ch
    }
  }
  if (cell.length || row.length) {
    row.push(cell)
    rows.push(row)
  }
  return rows.filter((r) => r.some((c) => (c || '').trim() !== ''))
}

/** CSV → 用例 payload 数组；表头兼容中英文，组内多值用 | / 、 ； 分隔 */
function csvToCasePayloads(text: string): Record<string, unknown>[] {
  const rows = parseCsvRows(text)
  if (rows.length < 2) throw new Error('CSV 至少需要表头 + 1 行数据')
  const header = rows[0].map((h) => h.trim().toLowerCase())
  const idx = (name: string) => header.indexOf(name)
  const pick = (row: string[], name: string): string => {
    const i = idx(name)
    return i >= 0 ? (row[i] || '').trim() : ''
  }
  const listOf = (s: string): string[] =>
    (s || '')
      .split(/[|、；;\n]/)
      .map((x) => x.trim())
      .filter(Boolean)
  const boolOf = (s: string): boolean => /^(1|true|yes|y|是)$/i.test((s || '').trim())
  if (idx('query') < 0) throw new Error('CSV 表头缺少 query 列')
  return rows.slice(1).map((row) => ({
    query: pick(row, 'query'),
    expected_tools: listOf(pick(row, 'expected_tools')),
    allowed_extra_tools: listOf(pick(row, 'allowed_extra_tools')),
    forbidden_tools: listOf(pick(row, 'forbidden_tools')),
    expect_abstain: boolOf(pick(row, 'expect_abstain')),
    expected_facts: listOf(pick(row, 'expected_facts')),
    split: pick(row, 'split') || 'regression',
    business_criticality: pick(row, 'business_criticality') || 'normal',
    notes: pick(row, 'notes'),
    messages: pick(row, 'messages') ? JSON.parse(pick(row, 'messages')) : null,
  }))
}

async function importBulk() {
  if (!activeSet.value) return
  const text = bulkText.value.trim()
  if (!text) {
    error.value = '请粘贴 JSON 数组或 CSV 内容'
    return
  }
  let payloads: Record<string, unknown>[]
  try {
    if (text.startsWith('[') || text.startsWith('{')) {
      const parsed: unknown = JSON.parse(text)
      if (!Array.isArray(parsed)) throw new Error('需要 JSON 数组')
      payloads = parsed as Record<string, unknown>[]
    } else {
      payloads = csvToCasePayloads(text)
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : '解析失败'
    return
  }
  try {
    const r = await addCasesBulk(activeSet.value.id, payloads)
    msg.value = `导入完成：新增 ${r.created}，跳过重复 ${r.skipped}，坏行 ${r.errors.length}`
    bulkDialog.value = false
    bulkText.value = ''
    await Promise.all([loadCases(1), loadSets()])
  } catch (e) {
    error.value = e instanceof Error ? e.message : '导入失败'
  }
}

function exportCsvTemplate() {
  const header =
    'query,expected_tools,allowed_extra_tools,forbidden_tools,expect_abstain,expected_facts,split,business_criticality,notes,messages'
  const sample =
    '我这周有几节课？,my_schedule_overview,,,false,,frozen,critical,课表查询,\n' +
    '帮我预测下个学期成绩排名,,,,true,,frozen,critical,应拒答,'
  const blob = new Blob([header + '\n' + sample], { type: 'text/csv;charset=utf-8' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = 'agent-eval-import-template.csv'
  a.click()
  URL.revokeObjectURL(a.href)
}

async function doSeed() {
  try {
    const r = await seedDefault()
    msg.value = `默认用例：新增 ${r.created}，已存在 ${r.skipped}`
    await loadSets()
    const target = sets.value.find((s) => s.id === r.set_id)
    if (target) await selectSet(target)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '载入失败'
  }
}

function addSet() {
  setForm.value = { name: '', description: '' }
  setDialog.value = true
}

async function saveSet() {
  if (!setForm.value.name.trim()) {
    error.value = '集合名称不能为空'
    return
  }
  try {
    const s = await createSet({ name: setForm.value.name.trim(), description: setForm.value.description })
    setDialog.value = false
    await loadSets()
    const target = sets.value.find((x) => x.id === s.id)
    if (target) await selectSet(target)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '创建失败'
  }
}

function removeSet(s: AgentEvalSet) {
  confirmWith('删除评测集', `将删除「${s.name}」及其全部用例与运行记录，不可恢复。`, async () => {
    try {
      await deleteSet(s.id)
      if (activeSet.value?.id === s.id) {
        activeSet.value = null
        activeRun.value = null
      }
      await loadSets()
    } catch (e) {
      error.value = e instanceof Error ? e.message : '删除失败'
    }
  }, true)
}

function toolDiffLabel(r: AgentEvalResult): string {
  const expected = r.expected_tools.join(' → ') || (r.metrics?.expect_abstain ? '（应拒答）' : '（无工具）')
  const actual = (r.tool_calls || []).map((t) => t.name).join(' → ') || '（未调用工具）'
  return `${expected} ⇢ ${actual}`
}

onMounted(async () => {
  await loadSets()
  void loadEvalModels()
})
</script>

<template>
  <div class="page">
    <PageHead title="Agent 行为评测" eyebrow="EVALUATION" sub="工具编排回归：期望工具序列 / 禁用工具 / 应拒答 / 关键事实，发布前闸门校验">
      <template #actions>
        <button class="btn ghost" @click="doSeed">载入默认用例</button>
        <button class="btn" @click="addSet">新建评测集</button>
      </template>
    </PageHead>
    <RagTabs />

    <p v-if="error" class="notice err">{{ error }}</p>
    <p v-if="msg" class="notice ok">{{ msg }}</p>

    <div class="layout">
      <aside class="sets">
        <div v-for="s in sets" :key="s.id" class="set-card" :class="{ active: activeSet?.id === s.id }" @click="selectSet(s)">
          <div class="set-name">{{ s.name }}</div>
          <div class="set-meta">{{ s.case_count ?? 0 }} 条用例</div>
          <button class="set-del" title="删除评测集" @click.stop="removeSet(s)">✕</button>
        </div>
        <div v-if="!sets.length && !loading" class="sets-empty">还没有评测集，点右上「载入默认用例」开始</div>
      </aside>

      <main v-if="activeSet" class="main">
        <div class="tabs">
          <button :class="{ on: tab === 'cases' }" @click="tab = 'cases'">用例（{{ caseTotal }}）</button>
          <button :class="{ on: tab === 'runs' }" @click="tab = 'runs'">运行（{{ runTotal }}）</button>
        </div>

        <!-- 用例 -->
        <section v-if="tab === 'cases'" class="panel">
          <div class="panel-head">
            <span class="panel-title">用例列表</span>
            <span class="spacer" />
            <button class="btn ghost sm" @click="bulkDialog = true">批量导入</button>
            <button class="btn sm" @click="openCaseDialog(null)">新增用例</button>
          </div>
          <table class="tbl">
            <thead>
              <tr>
                <th>问题</th>
                <th>期望工具序列</th>
                <th>split</th>
                <th>关键级</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="c in cases" :key="c.id">
                <td class="q">
                  {{ c.query }}
                  <div v-if="c.expect_abstain" class="tag warn">应拒答</div>
                  <div v-if="c.messages" class="tag">多轮 {{ c.messages.filter((m) => m.role === 'user').length }} 问</div>
                </td>
                <td class="mono">{{ c.expected_tools.join(' → ') || '—' }}</td>
                <td><span class="tag" :class="{ frozen: c.split === 'frozen' }">{{ c.split }}</span></td>
                <td>{{ c.business_criticality }}</td>
                <td class="ops">
                  <button class="link" @click="openCaseDialog(c)">编辑</button>
                  <button class="link danger" @click="removeCase(c)">删除</button>
                </td>
              </tr>
              <tr v-if="!cases.length"><td colspan="5" class="empty">暂无用例</td></tr>
            </tbody>
          </table>
          <div class="pager">
            <button :disabled="casePage <= 1" @click="loadCases(casePage - 1)">上一页</button>
            <span>{{ casePage }} / {{ casePageCount }}</span>
            <button :disabled="casePage >= casePageCount" @click="loadCases(casePage + 1)">下一页</button>
          </div>
        </section>

        <!-- 运行 -->
        <section v-else class="panel">
          <div class="panel-head">
            <span class="panel-title">运行记录</span>
            <span class="spacer" />
            <select v-model="runForm.model_config_id" class="sel">
              <option value="">平台默认模型</option>
              <option v-for="m in evalModels" :key="m.id" :value="m.id">{{ m.name }}（{{ m.model }}）</option>
            </select>
            <button class="btn sm" :disabled="isRunning || !caseTotal" @click="startRun">启动评测</button>
          </div>

          <div v-if="isRunning" class="progress">
            <div class="bar"><i :style="{ width: progressPct + '%' }" /></div>
            <span>{{ isRunning ? `${activeRun?.stage || 'running'} · ${activeRun?.processed_cases ?? 0}/${activeRun?.total_cases ?? 0}` : '' }}</span>
          </div>

          <table class="tbl">
            <thead>
              <tr><th>时间</th><th>状态</th><th>通过率</th><th>工具召回</th><th>序列</th><th>闸门</th><th>操作</th></tr>
            </thead>
            <tbody>
              <tr v-for="r in runs" :key="r.id" :class="{ selected: activeRun?.id === r.id }">
                <td>{{ r.created_at ? new Date(r.created_at).toLocaleString() : '—' }}</td>
                <td>{{ r.status }}<span v-if="r.status === 'running'" class="tag"> {{ r.progress }}%</span></td>
                <td>{{ pct(r.metrics?.overall?.pass_rate) }}</td>
                <td>{{ pct(r.metrics?.overall?.tool_recall) }}</td>
                <td>{{ pct(r.metrics?.overall?.seq_score) }}</td>
                <td><span class="gate" :class="r.gate?.gate || ''">{{ r.gate?.gate || '—' }}</span></td>
                <td class="ops"><button class="link" @click="openRun(r)">查看</button></td>
              </tr>
              <tr v-if="!runs.length"><td colspan="7" class="empty">还没有运行，先「启动评测」</td></tr>
            </tbody>
          </table>
          <div class="pager">
            <button :disabled="runPage <= 1" @click="loadRuns(runPage - 1)">上一页</button>
            <span>{{ runPage }} / {{ runPageCount }}</span>
            <button :disabled="runPage >= runPageCount" @click="loadRuns(runPage + 1)">下一页</button>
          </div>

          <!-- 运行详情 -->
          <div v-if="activeRun && activeRun.status === 'done'" class="detail">
            <div class="detail-head">
              <span class="panel-title">运行详情</span>
              <span class="gate" :class="gateState">{{ gateState || '—' }}</span>
              <span class="dim">{{ activeRun.id }}</span>
              <span class="spacer" />
              <select v-model="baseRunId" class="sel">
                <option value="">选择基线运行对比</option>
                <option v-for="r in baseCandidates" :key="r.id" :value="r.id">
                  {{ r.created_at ? new Date(r.created_at).toLocaleString() : r.id }}
                </option>
              </select>
              <button class="btn ghost sm" :disabled="!baseRunId" @click="runCompare">对比</button>
            </div>

            <div class="kpis">
              <div class="kpi"><b>{{ pct(overall.pass_rate) }}</b><span>通过率</span></div>
              <div class="kpi"><b>{{ pct(overall.tool_recall) }}</b><span>工具召回</span></div>
              <div class="kpi"><b>{{ pct(overall.tool_precision) }}</b><span>工具精确率</span></div>
              <div class="kpi"><b>{{ pct(overall.seq_score) }}</b><span>序列得分</span></div>
              <div class="kpi"><b>{{ pct(overall.abstention_rate) }}</b><span>应拒答率</span></div>
              <div class="kpi"><b>{{ pct(overall.fact_coverage) }}</b><span>事实覆盖</span></div>
              <div v-if="frozen" class="kpi frozen"><b>{{ pct(frozen.seq_score) }}</b><span>冻结集序列</span></div>
            </div>
            <ul v-if="activeRun.gate?.reasons?.length" class="gate-reasons">
              <li v-for="(reason, i) in activeRun.gate.reasons" :key="i">{{ reason }}</li>
            </ul>

            <div v-if="compare" class="compare">
              <div class="panel-title">对比基线 {{ compare.base.id.slice(0, 8) }}…</div>
              <table class="tbl small">
                <thead><tr><th>指标</th><th>基线</th><th>本次</th><th>Δ</th></tr></thead>
                <tbody>
                  <tr v-for="(d, k) in compare.overall_diff" :key="k">
                    <td>{{ k }}</td>
                    <td>{{ pct(d.base) }}</td>
                    <td>{{ pct(d.now) }}</td>
                    <td :class="d.delta >= 0 ? 'up' : 'down'">{{ (d.delta * 100).toFixed(1) }}pp</td>
                  </tr>
                </tbody>
              </table>
              <div v-if="compare.changes.length" class="changes">
                <div class="panel-title">逐条变化（{{ compare.changes.length }}）</div>
                <div v-for="c in compare.changes" :key="c.case_id" class="change">
                  <span class="gate" :class="c.now">{{ c.was }} → {{ c.now }}</span>
                  <span>{{ c.query }}</span>
                  <span class="dim">{{ c.old_type }} → {{ c.new_type }}</span>
                </div>
              </div>
            </div>

            <div class="panel-head">
              <span class="panel-title">逐条结果</span>
              <span class="spacer" />
              <label class="check"><input v-model="onlyBad" type="checkbox" @change="loadResults(activeRun.id, 1)" /> 只看异常</label>
            </div>
            <table class="tbl">
              <thead>
                <tr><th>问题</th><th>期望 ⇢ 实际</th><th>判定</th><th>复核</th></tr>
              </thead>
              <tbody>
                <tr v-for="r in results" :key="r.id">
                  <td class="q">{{ r.query }}</td>
                  <td class="mono small">{{ toolDiffLabel(r) }}</td>
                  <td>
                    <span class="badge" :class="r.metrics?.passed ? 'pass' : 'fail'">
                      {{ r.metrics?.bad_case_type || '—' }}
                    </span>
                    <div v-if="r.error" class="dim err-text">{{ r.error }}</div>
                  </td>
                  <td class="ops">
                    <button class="link" :class="{ on: r.human_score === 1 }" @click="markResult(r, 1)">好</button>
                    <button class="link danger" :class="{ on: r.human_score === 0 }" @click="markResult(r, 0)">坏</button>
                  </td>
                </tr>
                <tr v-if="!results.length"><td colspan="4" class="empty">暂无结果</td></tr>
              </tbody>
            </table>
            <div class="pager">
              <button :disabled="resultPage <= 1" @click="loadResults(activeRun.id, resultPage - 1)">上一页</button>
              <span>{{ resultPage }} / {{ resultPageCount }}</span>
              <button :disabled="resultPage >= resultPageCount" @click="loadResults(activeRun.id, resultPage + 1)">下一页</button>
            </div>
          </div>
        </section>
      </main>
    </div>

    <!-- 用例编辑 -->
    <div v-if="caseDialog" class="overlay" @click.self="caseDialog = false">
      <div class="dialog">
        <h3>{{ caseForm.id ? '编辑用例' : '新增用例' }}</h3>
        <label>问题 *<textarea v-model="caseForm.query" rows="2" /></label>
        <div class="row">
          <label>期望工具（有序，逗号分隔）<input v-model="caseForm.expected_tools" placeholder="find_students, student_progress" /></label>
          <label>允许的额外工具<input v-model="caseForm.allowed_extra_tools" placeholder="student_evaluations" /></label>
        </div>
        <div class="row">
          <label>禁用工具<input v-model="caseForm.forbidden_tools" placeholder="delete_skill_file" /></label>
          <label>关键事实（关键词）<input v-model="caseForm.expected_facts" placeholder="张小明" /></label>
        </div>
        <div class="row">
          <label>split
            <select v-model="caseForm.split">
              <option value="tuning">tuning</option>
              <option value="regression">regression</option>
              <option value="frozen">frozen</option>
            </select>
          </label>
          <label>关键级
            <select v-model="caseForm.business_criticality">
              <option value="normal">normal</option>
              <option value="critical">critical</option>
            </select>
          </label>
          <label class="check"><input v-model="caseForm.expect_abstain" type="checkbox" /> 应拒答</label>
        </div>
        <label>多轮脚本（JSON 数组，可留空）<textarea v-model="caseForm.messages" rows="3" placeholder='[{"role":"user","content":"我带了哪些班？"}, …]' /></label>
        <label>备注<input v-model="caseForm.notes" /></label>
        <div class="dialog-ops">
          <button class="btn ghost" @click="caseDialog = false">取消</button>
          <button class="btn" @click="saveCase">保存</button>
        </div>
      </div>
    </div>

    <!-- 批量导入 -->
    <div v-if="bulkDialog" class="overlay" @click.self="bulkDialog = false">
      <div class="dialog">
        <h3>批量导入用例（JSON 数组 或 CSV）</h3>
        <p class="dim">
          自动识别格式：以 <code>[</code> 开头按 JSON 解析，否则按 CSV 解析。CSV 表头为
          query, expected_tools, allowed_extra_tools, forbidden_tools, expect_abstain, expected_facts, split, business_criticality, notes, messages；
          工具/关键词多值用 <code>|</code> 分隔，messages 为 JSON 字符串。
          <button class="link" @click="exportCsvTemplate">下载 CSV 模板</button>
        </p>
        <textarea v-model="bulkText" rows="10" class="mono" placeholder='JSON：[{"query": "我这周有几节课？", "expected_tools": ["my_schedule_overview"]}]&#10;CSV：query,expected_tools,...&#10;     我这周有几节课？,my_schedule_overview,...' />
        <div class="dialog-ops">
          <button class="btn ghost" @click="bulkDialog = false">取消</button>
          <button class="btn" @click="importBulk">导入</button>
        </div>
      </div>
    </div>

    <!-- 新建评测集 -->
    <div v-if="setDialog" class="overlay" @click.self="setDialog = false">
      <div class="dialog small">
        <h3>新建评测集</h3>
        <label>名称 *<input v-model="setForm.name" placeholder="如：秋冬学期回归集" /></label>
        <label>描述<input v-model="setForm.description" /></label>
        <div class="dialog-ops">
          <button class="btn ghost" @click="setDialog = false">取消</button>
          <button class="btn" @click="saveSet">创建</button>
        </div>
      </div>
    </div>

    <ConfirmDialog
      :visible="confirmState.open"
      :title="confirmState.title"
      :message="confirmState.message"
      :danger="confirmState.danger"
      @confirm="confirmState.open = false; confirmState.onOk()"
      @cancel="confirmState.open = false"
    />
  </div>
</template>

<style scoped>
.page { padding: 20px 24px 60px; }
.notice { margin: 10px 0; padding: 8px 12px; border-radius: 8px; font-size: 13px; }
.notice.err { background: #fef2f2; color: #b91c1c; border: 1px solid #fecaca; }
.notice.ok { background: #f0fdf4; color: #166534; border: 1px solid #bbf7d0; }
.layout { display: flex; gap: 16px; margin-top: 12px; align-items: flex-start; }
.sets { width: 220px; flex: none; display: flex; flex-direction: column; gap: 8px; }
.set-card { position: relative; padding: 10px 12px; border: 1px solid var(--line); border-radius: 10px; background: var(--surface); cursor: pointer; transition: border-color .15s, box-shadow .15s; }
.set-card:hover { border-color: var(--brand); }
.set-card.active { border-color: var(--brand); box-shadow: 0 1px 6px rgba(99, 102, 241, .18); }
.set-name { font-weight: 700; font-size: 13.5px; }
.set-meta { font-size: 12px; color: var(--ink-2); margin-top: 2px; }
.set-del { position: absolute; top: 6px; right: 6px; border: none; background: transparent; color: var(--ink-3); cursor: pointer; font-size: 12px; }
.set-del:hover { color: #dc2626; }
.sets-empty { font-size: 12.5px; color: var(--ink-3); padding: 8px; }
.main { flex: 1; min-width: 0; }
.tabs { display: flex; gap: 6px; margin-bottom: 10px; }
.tabs button { padding: 6px 14px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); cursor: pointer; font-size: 13px; }
.tabs button.on { border-color: var(--brand); color: var(--brand-strong); font-weight: 700; background: #f5f6ff; }
.panel { border: 1px solid var(--line); border-radius: 12px; background: var(--surface); padding: 14px; }
.panel-head { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.panel-title { font-weight: 700; font-size: 13.5px; }
.spacer { flex: 1; }
.btn { padding: 6px 14px; border-radius: 8px; border: 1px solid var(--brand); background: var(--brand); color: #fff; font-size: 13px; cursor: pointer; }
.btn.ghost { background: transparent; color: var(--brand-strong); }
.btn.sm { padding: 4px 10px; font-size: 12.5px; }
.btn:disabled { opacity: .5; cursor: not-allowed; }
.sel { padding: 5px 8px; border: 1px solid var(--line); border-radius: 8px; font-size: 12.5px; background: var(--surface); }
.tbl { width: 100%; border-collapse: collapse; font-size: 13px; }
.tbl th { text-align: left; font-size: 12px; color: var(--ink-2); padding: 6px 8px; border-bottom: 1px solid var(--line); white-space: nowrap; }
.tbl td { padding: 7px 8px; border-bottom: 1px solid var(--line); vertical-align: top; }
.tbl tr.selected td { background: #f5f6ff; }
.tbl.small { font-size: 12.5px; }
.q { max-width: 320px; }
.mono { font-family: ui-monospace, monospace; font-size: 12px; }
.small { font-size: 12px; }
.empty { text-align: center; color: var(--ink-3); padding: 16px 0; }
.ops { white-space: nowrap; }
.link { border: none; background: transparent; color: var(--brand-strong); cursor: pointer; font-size: 12.5px; padding: 2px 4px; }
.link.danger { color: #dc2626; }
.link.on { font-weight: 700; text-decoration: underline; }
.tag { display: inline-block; margin-left: 6px; padding: 1px 7px; border-radius: 999px; font-size: 11px; background: #eef2ff; color: #4338ca; }
.tag.warn { background: #fef9c3; color: #a16207; }
.tag.frozen { background: #fee2e2; color: #b91c1c; }
.gate { padding: 1px 8px; border-radius: 999px; font-size: 11.5px; background: #f1f5f9; color: var(--ink-2); }
.gate.pass { background: #dcfce7; color: #15803d; }
.gate.fail { background: #fee2e2; color: #b91c1c; }
.gate.skip { background: #fef9c3; color: #a16207; }
.pager { display: flex; align-items: center; gap: 10px; justify-content: flex-end; margin-top: 8px; font-size: 12.5px; }
.pager button { padding: 3px 10px; border: 1px solid var(--line); border-radius: 6px; background: var(--surface); cursor: pointer; }
.pager button:disabled { opacity: .45; cursor: not-allowed; }
.progress { display: flex; align-items: center; gap: 10px; margin: 4px 0 10px; font-size: 12.5px; color: var(--ink-2); }
.bar { flex: 1; height: 8px; border-radius: 999px; background: #eef2f7; overflow: hidden; }
.bar i { display: block; height: 100%; background: var(--brand); transition: width .4s; }
.detail { margin-top: 18px; border-top: 1px dashed var(--line); padding-top: 14px; }
.detail-head { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.dim { color: var(--ink-3); font-size: 12px; }
.kpis { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; }
.kpi { min-width: 96px; padding: 8px 12px; border: 1px solid var(--line); border-radius: 10px; text-align: center; }
.kpi b { display: block; font-size: 17px; }
.kpi span { font-size: 11.5px; color: var(--ink-2); }
.kpi.frozen { border-color: #fca5a5; }
.gate-reasons { margin: 6px 0; padding-left: 18px; font-size: 12.5px; color: #b91c1c; }
.compare { margin: 12px 0; padding: 10px 12px; border: 1px solid var(--line); border-radius: 10px; background: #fafbff; }
.up { color: #15803d; }
.down { color: #b91c1c; }
.change { display: flex; gap: 10px; align-items: center; font-size: 12.5px; padding: 3px 0; }
.badge { padding: 2px 8px; border-radius: 6px; font-size: 11.5px; background: #f1f5f9; }
.badge.pass { background: #dcfce7; color: #15803d; }
.badge.fail { background: #fee2e2; color: #b91c1c; }
.err-text { color: #b91c1c; }
.check { display: inline-flex; align-items: center; gap: 5px; font-size: 12.5px; color: var(--ink-2); }
.overlay { position: fixed; inset: 0; z-index: 3000; background: rgba(15, 23, 42, .45); display: flex; align-items: center; justify-content: center; }
.dialog { width: 620px; max-width: calc(100vw - 40px); max-height: 84vh; overflow: auto; background: var(--surface); border-radius: 14px; padding: 18px 20px; display: flex; flex-direction: column; gap: 10px; }
.dialog.small { width: 400px; }
.dialog h3 { margin: 0 0 4px; font-size: 15px; }
.dialog label { display: flex; flex-direction: column; gap: 4px; font-size: 12.5px; color: var(--ink-2); flex: 1; }
.dialog input, .dialog textarea, .dialog select { padding: 7px 9px; border: 1px solid var(--line); border-radius: 8px; font-size: 13px; background: #fff; }
.dialog .row { display: flex; gap: 10px; }
.dialog-ops { display: flex; justify-content: flex-end; gap: 8px; margin-top: 4px; }
</style>
