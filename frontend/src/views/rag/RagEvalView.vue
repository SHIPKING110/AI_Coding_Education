<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import PageHead from '@/components/PageHead.vue'
import RagTabs from '@/components/RagTabs.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import {
  addEvalCase,
  addEvalCasesBulk,
  createEvalRun,
  createEvalSet,
  deleteEvalCase,
  deleteEvalSet,
  generateEvalCases,
  getEvalRun,
  listEvalCases,
  listEvalModels,
  listEvalRuns,
  listEvalSets,
  setEvalResultHumanScore,
  updateEvalCase,
  type RagEvalCase,
  type RagEvalModel,
  type RagEvalResult,
  type RagEvalRun,
  type RagEvalSet,
} from '@/api/ragAdmin'

const sets = ref<RagEvalSet[]>([])
const activeSet = ref<RagEvalSet | null>(null)
const cases = ref<RagEvalCase[]>([])
const caseTotal = ref(0)
const casePage = ref(1)
const casePageSize = ref(20)
const evalModels = ref<RagEvalModel[]>([])
const runs = ref<RagEvalRun[]>([])
const activeRun = ref<RagEvalRun | null>(null)
const results = ref<RagEvalResult[]>([])
const loading = ref(false)
const error = ref('')
const msg = ref('')
const pending = ref<{ title: string; message: string; run: () => void | Promise<void> } | null>(null)

function ask(title: string, message: string, run: () => void | Promise<void>) {
  pending.value = { title, message, run }
}
async function confirmPending() {
  const p = pending.value
  pending.value = null
  if (p) await p.run()
}

const newSet = ref({ name: '', description: '', domain: 'agent_teacher', owner_id: '' })
const newCase = ref({ query: '', relevant: '', gt_answer: '', notes: '', query_type: 'fact' })
const runForm = ref({
  top_k: 5,
  rerank: true,
  retrieval_mode: 'auto',
  answer_eval: false,
  generation_config_id: '',
  judge_config_id: '',
})
const genForm = ref({ doc_ids: '', count: 10, use_llm: false })
// 批量导入
interface ImportParseResult {
  rows: Record<string, unknown>[]
  errors: string[]
  files: string[]
}

const importText = ref('')
const importSource = ref('import')
const importMsg = ref('')
const importError = ref('')
const importErrors = ref<string[]>([])
const importLoading = ref(false)
const importPreview = ref<ImportParseResult | null>(null)
const skipDuplicates = ref(true)

function errMsg(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

function normalizeImportRow(row: any): Record<string, unknown> {
  if (!row || typeof row !== 'object' || Array.isArray(row)) throw new Error('行必须是对象')
  const query = String(row.query ?? row['用户问题'] ?? '').trim()
  if (!query) throw new Error('query（用户问题）不能为空')
  const toArray = (v: any): string[] => {
    if (Array.isArray(v)) return v.map((x) => String(x).trim()).filter(Boolean)
    if (typeof v === 'string') return v.split(/[;；]/).map((x) => x.trim()).filter(Boolean)
    return []
  }
  return {
    query,
    relevant: toArray(row.relevant ?? row['应命中文档'] ?? row['相关文档']),
    answerability: String(row.answerability ?? 'unlabeled').trim(),
    split: String(row.split ?? 'regression').trim(),
    business_criticality: String(row.business_criticality ?? 'normal').trim(),
    gt_answer: String(row.gt_answer ?? row['标准答案'] ?? '').trim(),
    gt_keywords: toArray(row.gt_keywords ?? row['关键词']),
    query_type: String(row.query_type ?? 'fact').trim() || 'fact',
    difficulty: String(row.difficulty ?? 'normal').trim() || 'normal',
    notes: String(row.notes ?? row['备注'] ?? '').trim(),
    source: String(row.source ?? importSource.value ?? 'import').trim() || 'import',
  }
}

function parseRowsWithIndex(items: any[], label: string): ImportParseResult {
  const rows: Record<string, unknown>[] = []
  const errors: string[] = []
  items.forEach((item, idx) => {
    try {
      rows.push(normalizeImportRow(item))
    } catch (e) {
      errors.push(`${label} 第 ${idx + 1} 条：${errMsg(e)}`)
    }
  })
  return { rows, errors, files: [label] }
}

function parseImportText(text: string, label = '粘贴内容'): ImportParseResult {
  const t = text.trim()
  if (!t) return { rows: [], errors: [], files: [label] }
  if (t.startsWith('[')) {
    let arr: any
    try {
      arr = JSON.parse(t)
    } catch (e) {
      return { rows: [], errors: [`${label}：JSON 解析失败（${errMsg(e)}）`], files: [label] }
    }
    if (!Array.isArray(arr)) {
      return { rows: [], errors: [`${label}：JSON 顶层必须是数组`], files: [label] }
    }
    return parseRowsWithIndex(arr, label)
  }
  const lines = t.split(/\r?\n/).map((l) => l.trim()).filter(Boolean)
  if (lines.length && lines[0].startsWith('{')) {
    const rows: Record<string, unknown>[] = []
    const errors: string[] = []
    lines.forEach((line, idx) => {
      try {
        rows.push(normalizeImportRow(JSON.parse(line)))
      } catch (e) {
        errors.push(`${label} 第 ${idx + 1} 行：${errMsg(e)}`)
      }
    })
    return { rows, errors, files: [label] }
  }
  if (lines.length < 2) {
    return { rows: [], errors: [`${label}：CSV 至少需要表头 + 1 行数据`], files: [label] }
  }
  const header = splitCsvLine(lines[0])
  const rows: Record<string, unknown>[] = []
  const errors: string[] = []
  for (let i = 1; i < lines.length; i++) {
    const cols = splitCsvLine(lines[i])
    const obj: Record<string, string> = {}
    header.forEach((h, idx) => (obj[h.trim()] = (cols[idx] ?? '').trim()))
    try {
      rows.push(normalizeImportRow(obj))
    } catch (e) {
      errors.push(`${label} 第 ${i + 1} 行：${errMsg(e)}`)
    }
  }
  return { rows, errors, files: [label] }
}

function splitCsvLine(line: string): string[] {
  const out: string[] = []
  let cur = ''
  let inQ = false
  for (let i = 0; i < line.length; i++) {
    const ch = line[i]
    if (ch === '"') {
      if (inQ && line[i + 1] === '"') { cur += '"'; i++; continue }
      inQ = !inQ
      continue
    }
    if (ch === ',' && !inQ) { out.push(cur); cur = ''; continue }
    cur += ch
  }
  out.push(cur)
  return out
}

async function onImportFiles(e: Event) {
  const input = e.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  input.value = ''
  await processImportFiles(files)
}

async function onImportDrop(e: DragEvent) {
  const files = Array.from(e.dataTransfer?.files ?? [])
  if (files.length) await processImportFiles(files)
}

async function processImportFiles(files: File[]) {
  if (!files.length) return
  importError.value = ''
  importMsg.value = ''
  importErrors.value = []
  const merged: ImportParseResult = { rows: [], errors: [], files: [] }
  for (const file of files) {
    if (file.size > 10 * 1024 * 1024) {
      merged.errors.push(`${file.name}：文件超过 10MB`)
      continue
    }
    try {
      const text = await file.text()
      const parsed = parseImportText(text, file.name)
      merged.rows.push(...parsed.rows)
      merged.errors.push(...parsed.errors)
      merged.files.push(file.name)
    } catch (err) {
      merged.errors.push(`${file.name}：读取失败（${errMsg(err)}）`)
    }
  }
  importPreview.value = merged
  importText.value = ''
}

function onImportTextInput() {
  importPreview.value = null
}

function clearImport() {
  importText.value = ''
  importPreview.value = null
  importMsg.value = ''
  importError.value = ''
  importErrors.value = []
}

async function importCases() {
  if (!activeSet.value) { importError.value = '请先选择评测集'; return }
  importMsg.value = ''
  importError.value = ''
  importErrors.value = []
  let rows: Record<string, unknown>[] = []
  let parseErrors: string[] = []
  if (importPreview.value) {
    rows = importPreview.value.rows
    parseErrors = importPreview.value.errors
  } else {
    const parsed = parseImportText(importText.value)
    rows = parsed.rows
    parseErrors = parsed.errors
  }
  if (!rows.length) {
    importError.value = parseErrors.length
      ? `没有可导入的有效用例（${parseErrors.length} 条解析失败）`
      : '没有可导入的用例'
    importErrors.value = parseErrors
    return
  }
  if (rows.length > 500) { importError.value = '单次导入最多 500 条，请分批'; return }
  importLoading.value = true
  try {
    const r = await addEvalCasesBulk(activeSet.value.id, {
      cases: rows,
      skip_duplicates: skipDuplicates.value,
    })
    const parts = [`已导入 ${r.created} 条`]
    if (r.skipped_duplicates) parts.push(`跳过重复 ${r.skipped_duplicates} 条`)
    if (r.failed) parts.push(`失败 ${r.failed} 条`)
    importMsg.value = parts.join('，')
    importErrors.value = [
      ...parseErrors,
      ...r.errors.map((x) => `第 ${x.index} 条：${x.error}`),
    ]
    importPreview.value = null
    importText.value = ''
    const nextPage = Math.max(1, Math.ceil((caseTotal.value + r.created) / casePageSize.value))
    await loadCases(activeSet.value.id, nextPage)
  } catch (e) {
    importError.value = e instanceof Error ? e.message : '导入失败'
  } finally {
    importLoading.value = false
  }
}

function downloadTemplate() {
  const header = ['query', 'relevant', 'answerability', 'split', 'business_criticality', 'gt_answer', 'gt_keywords', 'query_type', 'difficulty', 'notes', 'source']
  const example = [
    '如何办理退费？',
    '退费政策文档',
    '请到前台提交退费申请，3-5 个工作日到账。',
    '前台;退费申请;3-5个工作日',
    'policy',
    'normal',
    '示例行，导入前请删除',
    'batch-2026-06',
  ]
  const esc = (v: string) => `"${v.replace(/"/g, '""')}"`
  const csv = '\ufeff' + [header, example].map((row) => row.map(esc).join(',')).join('\r\n')
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'rag-eval-import-template.csv'
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

const STAGE_LABELS: Record<string, string> = {
  pending: '排队中',
  retrieval_off: '关闭重排检索',
  retrieval_on: '开启重排检索',
  answer: '生成并评判答案',
  done: '已完成',
  failed: '失败',
}

const metricsOn = computed(() => activeRun.value?.metrics?.on || null)
const metricsOff = computed(() => activeRun.value?.metrics?.off || null)
const isRunning = computed(() => {
  const s = activeRun.value?.status
  return s === 'pending' || s === 'running'
})
const progressPct = computed(() => {
  const p = activeRun.value?.progress
  return typeof p === 'number' ? Math.max(0, Math.min(100, p)) : 0
})
const processedCases = computed(() => activeRun.value?.processed_cases ?? 0)
const totalCases = computed(() => activeRun.value?.total_cases ?? 0)
const stageLabel = computed(() => {
  const s = activeRun.value?.stage || activeRun.value?.status || ''
  return STAGE_LABELS[s] || s || '准备中'
})
const casePageCount = computed(() => Math.max(1, Math.ceil(caseTotal.value / casePageSize.value)))

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

async function refreshRun(runId: string, stopWhenDone = true) {
  if (pollBusy || pollRunId !== runId) return
  pollBusy = true
  try {
    const data = await getEvalRun(runId)
    if (pollRunId !== runId) return
    activeRun.value = data.run
    results.value = data.results
    if (stopWhenDone && data.run.status !== 'running' && data.run.status !== 'pending') {
      stopPoll()
      msg.value = data.run.status === 'done' ? '评测完成' : '评测失败'
      if (activeSet.value) runs.value = await listEvalRuns(activeSet.value.id)
    }
  } catch {
    // 单次轮询失败不打断；下一轮继续
  } finally {
    pollBusy = false
  }
}

function startPoll(runId: string) {
  stopPoll()
  pollRunId = runId
  pollTimer = window.setInterval(() => void refreshRun(runId), 2000)
  void refreshRun(runId)
}

onBeforeUnmount(stopPoll)

async function loadSets() {
  loading.value = true
  error.value = ''
  try {
    sets.value = await listEvalSets()
    if (!activeSet.value && sets.value.length) await selectSet(sets.value[0])
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

async function loadCases(setId: string, page = casePage.value) {
  const data = await listEvalCases(setId, { page, page_size: casePageSize.value })
  cases.value = data.items
  caseTotal.value = data.total
  casePage.value = data.page
}

async function loadEvalModels(ownerId?: string | null) {
  try {
    evalModels.value = await listEvalModels(ownerId)
  } catch {
    evalModels.value = []
  }
  const ids = new Set(evalModels.value.map((m) => m.id))
  if (!ids.has(runForm.value.generation_config_id)) {
    runForm.value.generation_config_id = evalModels.value[0]?.id || ''
  }
  if (!ids.has(runForm.value.judge_config_id) || runForm.value.judge_config_id === runForm.value.generation_config_id) {
    runForm.value.judge_config_id = evalModels.value.find((m) => m.id !== runForm.value.generation_config_id)?.id || ''
  }
}

async function selectSet(s: RagEvalSet) {
  stopPoll()
  activeSet.value = s
  activeRun.value = null
  results.value = []
  casePage.value = 1
  runForm.value.generation_config_id = ''
  runForm.value.judge_config_id = ''
  try {
    await Promise.all([
      loadCases(s.id, 1),
      listEvalRuns(s.id).then((r) => { runs.value = r }),
      loadEvalModels(s.owner_id),
    ])
    const latestRunning = runs.value.find((r) => r.status === 'running' || r.status === 'pending')
    if (latestRunning) await openRun(latestRunning)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  }
}

async function createSet() {
  if (!newSet.value.name.trim()) return
  try {
    const s = await createEvalSet({
      name: newSet.value.name,
      description: newSet.value.description,
      domain: newSet.value.domain,
      owner_id: newSet.value.owner_id || undefined,
    })
    msg.value = '评测集已创建'
    newSet.value = { name: '', description: '', domain: 'agent_teacher', owner_id: '' }
    await loadSets()
    await selectSet(s)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '创建失败'
  }
}

async function removeSet(s: RagEvalSet) {
  ask('删除评测集', `删除评测集「${s.name}」及其全部用例？此操作不可恢复。`, async () => {
    try {
      await deleteEvalSet(s.id)
      if (activeSet.value?.id === s.id) activeSet.value = null
      await loadSets()
    } catch (e) {
      error.value = e instanceof Error ? e.message : '删除失败'
    }
  })
}

async function addCase() {
  if (!activeSet.value || !newCase.value.query.trim()) return
  try {
    await addEvalCase(activeSet.value.id, {
      query: newCase.value.query,
      relevant: newCase.value.relevant.split(/[,，\n]/).map((x) => x.trim()).filter(Boolean),
      gt_answer: newCase.value.gt_answer,
      notes: newCase.value.notes,
      query_type: newCase.value.query_type,
    })
    msg.value = '用例已添加'
    newCase.value = { query: '', relevant: '', gt_answer: '', notes: '', query_type: 'fact' }
    const nextPage = Math.max(1, Math.ceil((caseTotal.value + 1) / casePageSize.value))
    await loadCases(activeSet.value.id, nextPage)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '添加失败'
  }
}

async function removeCase(c: RagEvalCase) {
  ask('删除用例', `删除用例「${c.query.slice(0, 24)}${c.query.length > 24 ? '…' : ''}」？`, async () => {
    try {
      await deleteEvalCase(c.id)
      if (activeSet.value) {
        const nextPage = cases.value.length === 1 && casePage.value > 1 ? casePage.value - 1 : casePage.value
        await loadCases(activeSet.value.id, nextPage)
      }
    } catch (e) {
      error.value = e instanceof Error ? e.message : '删除失败'
    }
  })
}

// 用例行内编辑：补标 relevant、调整可答性/分层/关键度，避免“删除再导入”
const editingCaseId = ref<string | null>(null)
const editCaseForm = ref({
  query: '',
  relevantText: '',
  answerability: 'unlabeled',
  split: 'regression',
  business_criticality: 'normal',
})
function startEditCase(c: RagEvalCase) {
  editingCaseId.value = c.id
  editCaseForm.value = {
    query: c.query,
    relevantText: (c.relevant || []).join('，'),
    answerability: c.answerability || 'unlabeled',
    split: c.split || 'regression',
    business_criticality: c.business_criticality || 'normal',
  }
}
function cancelEditCase() {
  editingCaseId.value = null
}
async function saveEditCase(c: RagEvalCase) {
  const relevant = editCaseForm.value.relevantText
    .split(/[,，、]/)
    .map((s) => s.trim())
    .filter(Boolean)
  try {
    await updateEvalCase(c.id, {
      query: editCaseForm.value.query,
      relevant,
      answerability: editCaseForm.value.answerability,
      split: editCaseForm.value.split,
      business_criticality: editCaseForm.value.business_criticality,
    })
    editingCaseId.value = null
    msg.value = '用例已更新'
    if (activeSet.value) await loadCases(activeSet.value.id, casePage.value)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '更新失败'
  }
}
function answerabilityLabel(v: string | undefined) {
  return v === 'answerable' ? '可答' : v === 'unanswerable' ? '不可答' : '未标注'
}
function splitLabel(v: string | undefined) {
  return v === 'frozen' ? '冻结' : v === 'tuning' ? '调参' : '回归'
}
function criticalityLabel(v: string | undefined) {
  return v === 'critical' ? '关键' : v === 'important' ? '重要' : '普通'
}

async function startRun() {
  if (!activeSet.value) return
  if (runForm.value.answer_eval) {
    if (!runForm.value.generation_config_id || !runForm.value.judge_config_id) {
      error.value = '答案质量评测需要分别选择生成模型与评测模型'
      return
    }
    if (runForm.value.generation_config_id === runForm.value.judge_config_id) {
      error.value = '生成模型与评测模型不能是同一个配置'
      return
    }
    const gen = evalModels.value.find((m) => m.id === runForm.value.generation_config_id)
    const judge = evalModels.value.find((m) => m.id === runForm.value.judge_config_id)
    if (gen && judge && gen.model.trim().toLowerCase() === judge.model.trim().toLowerCase()) {
      error.value = '生成模型与评测模型不能使用同一个模型'
      return
    }
  }
  error.value = ''
  try {
    const run = await createEvalRun(activeSet.value.id, {
      top_k: runForm.value.top_k,
      rerank: runForm.value.rerank,
      retrieval_mode: runForm.value.retrieval_mode,
      answer_eval: runForm.value.answer_eval,
      generation_config_id: runForm.value.answer_eval ? runForm.value.generation_config_id || undefined : undefined,
      judge_config_id: runForm.value.answer_eval ? runForm.value.judge_config_id || undefined : undefined,
    })
    msg.value = '评测已启动，正在后台运行'
    activeRun.value = run
    results.value = []
    startPoll(run.id)
    runs.value = await listEvalRuns(activeSet.value.id)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '启动失败'
  }
}

async function generateCases() {
  if (!activeSet.value || !genForm.value.doc_ids.trim()) return
  try {
    const r = await generateEvalCases(activeSet.value.id, {
      doc_ids: genForm.value.doc_ids.split(/[,，\n]/).map((x) => x.trim()).filter(Boolean),
      count: genForm.value.count,
      use_llm: genForm.value.use_llm,
    })
    msg.value = `已生成 ${r.created} 条候选用例，请复核`
    genForm.value.doc_ids = ''
    const nextPage = Math.max(1, Math.ceil((caseTotal.value + r.created) / casePageSize.value))
    await loadCases(activeSet.value.id, nextPage)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '生成失败'
  }
}

// 人工复核打分（0-5）：用于与 LLM Judge 计算 Cohen's Kappa，作为裁判可信度闸门
const editingResultId = ref<string | null>(null)
const humanScoreForm = ref({ score: '', judge: '', reason: '' })
function cancelHumanScore() {
  editingResultId.value = null
  humanScoreForm.value = { score: '', judge: '', reason: '' }
}
async function submitHumanScore(r: RagEvalResult) {
  const s = Number(humanScoreForm.value.score)
  if (!Number.isInteger(s) || s < 0 || s > 5) {
    error.value = '请输入 0-5 的整数分'
    return
  }
  try {
    await setEvalResultHumanScore(r.id, {
      score: s,
      judge: humanScoreForm.value.judge || '',
      reason: humanScoreForm.value.reason || '',
    })
    const runId = activeRun.value?.id || r.run_id
    editingResultId.value = null
    humanScoreForm.value = { score: '', judge: '', reason: '' }
    await openRun({ id: runId } as RagEvalRun)
    msg.value = '人工评分已保存，裁判一致性已重算'
  } catch (e) {
    error.value = e instanceof Error ? e.message : '评分失败'
  }
}

async function openRun(r: RagEvalRun) {
  stopPoll()
  try {
    const data = await getEvalRun(r.id)
    activeRun.value = data.run
    results.value = data.results
    if (data.run.status === 'running' || data.run.status === 'pending') startPoll(data.run.id)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  }
}

async function gotoCasePage(page: number) {
  if (!activeSet.value) return
  const target = Math.min(Math.max(1, page), casePageCount.value)
  if (target === casePage.value) return
  try {
    await loadCases(activeSet.value.id, target)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  }
}

async function changeCasePageSize() {
  if (!activeSet.value) return
  try {
    await loadCases(activeSet.value.id, 1)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  }
}

function pct(v: number | undefined | null) {
  return v == null ? '-' : `${Math.round(v * 100)}%`
}
function fixed(v: number | undefined | null) {
  return v == null ? '-' : Number(v).toFixed(3)
}

onMounted(loadSets)
</script>

<template>
  <div>
    <PageHead title="评测中心" eyebrow="RAG EVAL" sub="Q-DOC 检索指标、重排 A/B 与 Bad Case 分类">
      <template #actions>
        <button class="btn ghost" :disabled="loading" @click="loadSets">{{ loading ? '刷新中…' : '刷新' }}</button>
      </template>
    </PageHead>

    <RagTabs />

    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="msg" class="ok">{{ msg }}</p>

    <section class="two-col">
      <div class="panel">
        <div class="panel-head"><h3>评测集</h3></div>
        <div class="set-list">
          <button v-for="s in sets" :key="s.id" class="set-item" :class="{ on: activeSet?.id === s.id }" @click="selectSet(s)">
            <span>{{ s.name }}</span>
            <span class="muted">{{ s.domain }}</span>
            <span class="mini danger" @click.stop="removeSet(s)">删</span>
          </button>
          <div v-if="!sets.length" class="muted">暂无评测集</div>
        </div>
        <div class="create-box">
          <input v-model="newSet.name" placeholder="评测集名称" />
          <input v-model="newSet.description" placeholder="说明（可选）" />
          <select v-model="newSet.domain">
            <option value="agent_teacher">agent_teacher</option>
            <option value="parent_service">parent_service</option>
          </select>
          <input v-model="newSet.owner_id" placeholder="owner_id（可选）" />
          <button class="btn" @click="createSet">新建评测集</button>
        </div>
      </div>

      <div class="panel">
        <div class="panel-head"><h3>运行评测</h3><span class="muted">{{ activeSet?.name || '请选择评测集' }}</span></div>
        <div class="run-form">
          <label>top_k <input v-model.number="runForm.top_k" type="number" min="1" max="50" /></label>
          <label>检索模式
            <select v-model="runForm.retrieval_mode">
              <option value="auto">跟随当前配置</option>
              <option value="dense">Dense（关闭 Hybrid）</option>
              <option value="hybrid">Hybrid（Dense + BM25 + RRF）</option>
            </select>
          </label>
          <label class="check"><input v-model="runForm.rerank" type="checkbox" /> 启用 rerank（同时跑 off/on 对比）</label>
          <label class="check"><input v-model="runForm.answer_eval" type="checkbox" /> 答案质量评测（LLM 裁判）</label>
          <label class="model-pick">生成模型
            <select v-model="runForm.generation_config_id" :disabled="!runForm.answer_eval">
              <option value="" disabled>请选择生成模型</option>
              <option v-for="m in evalModels" :key="m.id" :value="m.id" :disabled="m.id === runForm.judge_config_id">
                {{ m.name }}（{{ m.model }}）
              </option>
            </select>
          </label>
          <label class="model-pick">评测模型
            <select v-model="runForm.judge_config_id" :disabled="!runForm.answer_eval">
              <option value="" disabled>请选择评测模型</option>
              <option v-for="m in evalModels" :key="m.id" :value="m.id" :disabled="m.id === runForm.generation_config_id">
                {{ m.name }}（{{ m.model }}）
              </option>
            </select>
          </label>
          <button class="btn" :disabled="!activeSet || !caseTotal" @click="startRun">开始评测</button>
        </div>
        <p class="field-hint">
          生成模型负责基于检索片段作答；评测模型负责裁判打分。答案质量评测建议选择不同厂商/不同模型，降低同源偏好；两者不能相同。
          检索指标（hit@k / MRR / recall）不调用 LLM，未勾选答案质量评测时模型选择不生效。
        </p>
        <div v-if="runForm.answer_eval && evalModels.length < 2" class="warn">
          当前 owner 只配置了 {{ evalModels.length }} 个模型，无法同时选择生成与评测模型。请先在「设置 → 模型配置」中补充至少两个模型。
        </div>
        <div class="muted">评测会同时跑 rerank=off 与 rerank=on，输出对比与逐条 Bad Case。</div>
        <div class="muted" style="margin-top:6px">
          评测产生的 LLM 调用（生成回答 / 裁判打分）已归因到「用量与成本」模块 <b>rag_eval</b>，
          <RouterLink class="doc-link" to="/usage">去用量与成本查看成本 ↗</RouterLink>
        </div>
      </div>
    </section>

    <section v-if="activeSet" class="panel">
      <div class="panel-head">
        <h3>用例（{{ caseTotal }}）</h3>
        <label class="muted">每页
          <select v-model.number="casePageSize" class="page-size" @change="changeCasePageSize">
            <option :value="20">20</option>
            <option :value="50">50</option>
            <option :value="100">100</option>
          </select>
        </label>
      </div>
      <details class="manual-add">
        <summary>单条添加 / 从分片生成（可选，批量导入请用下方）</summary>
        <div class="case-form">
          <input v-model="newCase.query" placeholder="用户问题" />
          <input v-model="newCase.relevant" placeholder="应命中文档标题，逗号分隔" />
          <input v-model="newCase.gt_answer" placeholder="标准答案（可选）" />
          <input v-model="newCase.notes" placeholder="备注（可选）" />
          <button class="btn" @click="addCase">添加用例</button>
        </div>
        <div class="case-form gen-form">
          <input v-model="genForm.doc_ids" placeholder="从文档分片生成：doc_id，逗号分隔" />
          <input v-model.number="genForm.count" type="number" min="1" max="100" />
          <label class="check"><input v-model="genForm.use_llm" type="checkbox" /> LLM 生成</label>
          <button class="btn ghost" :disabled="!genForm.doc_ids.trim()" @click="generateCases">生成候选用例</button>
        </div>
        <p class="field-hint">
          字段说明：<b>用户问题</b>=评测输入；<b>应命中文档</b>=相关文档标题（用于 hit@k / MRR，需与知识库标题一致）；
          <b>标准答案</b>=可选，用于答案质量评测；<b>备注</b>=来源/预期 Bad Case。<b>分片生成</b>=从已有文档分片自动生成候选用例（辅助，不是导入字段）。
        </p>
      </details>

      <div class="import-box" @dragover.prevent @drop.prevent="onImportDrop">
        <div class="panel-head" style="margin:0 0 8px">
          <h3>批量导入用例</h3>
          <div class="import-actions">
            <button class="mini" type="button" @click="downloadTemplate">下载 CSV 模板</button>
            <a class="doc-link" href="/docs/rag-eval-spec" target="_blank" rel="noopener">导入格式与合规说明 ↗</a>
          </div>
        </div>
        <div class="case-form gen-form">
          <label class="upload-btn">
            <input type="file" multiple accept=".jsonl,.json,.csv,.txt" hidden @change="onImportFiles" />
            选择文件（可多选，JSONL / JSON / CSV）
          </label>
          <input v-model="importSource" placeholder="批次号/来源（写入 source）" style="max-width:220px" />
          <label class="check"><input v-model="skipDuplicates" type="checkbox" /> 跳过重复 query</label>
          <button class="btn" :disabled="importLoading || (!importText.trim() && !importPreview?.rows.length)" @click="importCases">
            {{ importLoading ? '导入中…' : '导入数据' }}
          </button>
          <button v-if="importText || importPreview" class="mini" type="button" @click="clearImport">清空</button>
        </div>
        <div v-if="importPreview" class="import-preview">
          <b>已选择 {{ importPreview.files.length }} 个文件，解析出 {{ importPreview.rows.length }} 条有效用例</b>
          <span v-if="importPreview.errors.length" class="warn-text">，{{ importPreview.errors.length }} 条解析失败</span>
          <div class="preview-list">
            <span v-for="(row, idx) in importPreview.rows.slice(0, 3)" :key="idx" class="preview-chip">
              {{ String(row.query).slice(0, 36) }}{{ String(row.query).length > 36 ? '…' : '' }}
            </span>
            <span v-if="importPreview.rows.length > 3" class="muted">等 {{ importPreview.rows.length }} 条</span>
          </div>
        </div>
        <textarea
          v-model="importText"
          rows="5"
          class="import-area"
          placeholder='也可直接粘贴：JSONL（每行一个）/ JSON 数组 / CSV。示例：{"query":"如何办理退费？","relevant":["退费政策文档"],"gt_answer":"...","notes":"...","query_type":"policy"}'
          @input="onImportTextInput"
        />
        <p v-if="importError" class="error" style="margin:8px 0 0">{{ importError }}</p>
        <p v-if="importMsg" class="ok" style="margin:8px 0 0">{{ importMsg }}</p>
        <ul v-if="importErrors.length" class="import-error-list">
          <li v-for="(err, idx) in importErrors.slice(0, 20)" :key="idx">{{ err }}</li>
          <li v-if="importErrors.length > 20" class="muted">…还有 {{ importErrors.length - 20 }} 条错误未展示</li>
        </ul>
        <p class="muted" style="margin-top:8px">
          导入前请完成数据脱敏（详见格式说明）；单次上限 500 条，追加不覆盖；默认按 query 去重，重复用例会跳过。
          批次号仅写入 <b>source</b> 作来源标记，不会自动分组。
        </p>
      </div>

      <table class="table">
        <thead><tr><th>query</th><th>relevant</th><th>可答性</th><th>分层</th><th>关键度</th><th>类型</th><th>来源</th><th></th></tr></thead>
        <tbody>
          <tr v-for="c in cases" :key="c.id">
            <template v-if="editingCaseId === c.id">
              <td colspan="8">
                <div class="case-edit">
                  <label>query<input v-model="editCaseForm.query" /></label>
                  <label>relevant（逗号分隔标题）<input v-model="editCaseForm.relevantText" placeholder="文档标题A，文档标题B" /></label>
                  <label>可答性
                    <select v-model="editCaseForm.answerability">
                      <option value="answerable">可答</option>
                      <option value="unanswerable">不可答</option>
                      <option value="unlabeled">未标注</option>
                    </select>
                  </label>
                  <label>分层
                    <select v-model="editCaseForm.split">
                      <option value="regression">回归</option>
                      <option value="tuning">调参</option>
                      <option value="frozen">冻结</option>
                    </select>
                  </label>
                  <label>关键度
                    <select v-model="editCaseForm.business_criticality">
                      <option value="normal">普通</option>
                      <option value="important">重要</option>
                      <option value="critical">关键</option>
                    </select>
                  </label>
                  <button class="mini ok" @click="saveEditCase(c)">保存</button>
                  <button class="mini ghost" @click="cancelEditCase">取消</button>
                </div>
              </td>
            </template>
            <template v-else>
              <td>{{ c.query }}</td>
              <td class="muted">{{ (c.relevant || []).join('、') || '-' }}</td>
              <td><span class="tag" :class="c.answerability === 'answerable' ? 'ok' : c.answerability === 'unanswerable' ? 'pending' : ''">{{ answerabilityLabel(c.answerability) }}</span></td>
              <td><span class="tag" :class="c.split === 'frozen' ? 'bad' : ''">{{ splitLabel(c.split) }}</span></td>
              <td><span class="tag" :class="c.business_criticality === 'critical' ? 'bad' : c.business_criticality === 'important' ? 'pending' : ''">{{ criticalityLabel(c.business_criticality) }}</span></td>
              <td>{{ c.query_type }}</td>
              <td>{{ c.source }}</td>
              <td>
                <button class="mini" @click="startEditCase(c)">编辑</button>
                <button class="mini danger" @click="removeCase(c)">删除</button>
              </td>
            </template>
          </tr>
          <tr v-if="!cases.length"><td colspan="8" class="muted">暂无用例</td></tr>
        </tbody>
      </table>
      <div class="pager">
        <button class="mini" :disabled="casePage <= 1" @click="gotoCasePage(casePage - 1)">上一页</button>
        <span class="muted">第 {{ casePage }} / {{ casePageCount }} 页</span>
        <button class="mini" :disabled="casePage >= casePageCount" @click="gotoCasePage(casePage + 1)">下一页</button>
      </div>
    </section>

    <section v-if="activeSet" class="panel">
      <div class="panel-head"><h3>运行记录</h3></div>
      <table class="table">
        <thead><tr><th>状态</th><th>top_k</th><th>模式</th><th>模型（生成 / 评测）</th><th>配置版本</th><th>hit@3 off → on</th><th>MRR off → on</th><th>时间</th><th></th></tr></thead>
        <tbody>
          <tr v-for="r in runs" :key="r.id">
            <td>
              <span class="tag" :class="r.status === 'done' ? 'ok' : r.status === 'failed' ? 'bad' : 'pending'">
                {{ STAGE_LABELS[r.status] || r.status }}
              </span>
              <div v-if="r.status === 'running' || r.status === 'pending'" class="run-mini">
                {{ STAGE_LABELS[r.stage] || r.stage }} · 本阶段 {{ r.processed_cases }}/{{ r.total_cases }} · {{ r.progress }}%
              </div>
            </td>
            <td>{{ r.top_k }}</td>
            <td class="muted">{{ r.retrieval_mode || 'auto' }}</td>
            <td class="muted">{{ r.generation_model || '默认' }} / {{ r.judge_model || '默认' }}</td>
            <td>{{ r.config_version ?? '-' }}</td>
            <td>{{ fixed(r.metrics?.off?.['hit@3']) }} → {{ fixed(r.metrics?.on?.['hit@3']) }}</td>
            <td>{{ fixed(r.metrics?.off?.mrr) }} → {{ fixed(r.metrics?.on?.mrr) }}</td>
            <td class="mono">{{ r.created_at?.slice(0, 16).replace('T', ' ') }}</td>
            <td><button class="mini" @click="openRun(r)">详情</button></td>
          </tr>
          <tr v-if="!runs.length"><td colspan="9" class="muted">暂无运行记录</td></tr>
        </tbody>
      </table>
    </section>

    <section v-if="activeRun" class="panel">
      <div class="panel-head">
        <h3>评测结果</h3>
        <span class="tag" :class="activeRun.status === 'done' ? 'ok' : activeRun.status === 'failed' ? 'bad' : 'pending'">
          {{ STAGE_LABELS[activeRun.status] || activeRun.status }}
        </span>
      </div>
      <div v-if="isRunning" class="eval-progress">
        <div class="progress-track"><div class="progress-fill" :style="{ width: progressPct + '%' }"></div></div>
        <div class="progress-meta">
          <span>{{ stageLabel }}</span>
          <span>本阶段 {{ processedCases }} / {{ totalCases }} 条 · {{ progressPct }}%</span>
        </div>
        <p class="muted">评测在后台运行，可离开页面；重新进入会继续显示进度。</p>
      </div>
      <p v-if="activeRun.error" class="error">{{ activeRun.error }}</p>
      <div v-if="activeRun.metrics?.gate?.gate === 'fail'" class="warn">
        验收闸门未通过：{{ (activeRun.metrics.gate.reasons || []).join('；') }}
      </div>
      <p v-else-if="activeRun.metrics?.gate?.gate === 'pass'" class="muted">验收闸门通过（冻结集/关键用例无回退，无依据回答率与异常率未超限）。</p>
      <div v-if="activeRun.metrics" class="metrics">
        <div class="metric"><span>hit@3 (off)</span><b>{{ fixed(metricsOff?.['hit@3']) }}</b></div>
        <div class="metric"><span>hit@3 (on)</span><b>{{ fixed(metricsOn?.['hit@3']) }}</b></div>
        <div class="metric"><span>MRR (off)</span><b>{{ fixed(metricsOff?.mrr) }}</b></div>
        <div class="metric"><span>MRR (on)</span><b>{{ fixed(metricsOn?.mrr) }}</b></div>
        <div class="metric"><span>Context Precision@5 (on)</span><b>{{ fixed(metricsOn?.['precision@5']) }}</b></div>
        <div class="metric"><span>Context Recall@5 (on)</span><b>{{ fixed(metricsOn?.['recall@5']) }}</b></div>
        <div class="metric"><span>nDCG@5 (on)</span><b>{{ fixed(metricsOn?.['ndcg@5']) }}</b></div>
        <div v-if="metricsOn?.error_cases" class="metric"><span>检索异常（不计入指标）</span><b class="error">{{ metricsOn.error_cases }}</b></div>
        <div v-if="activeRun.metrics?.critical?.cases" class="metric"><span>关键用例 hit@3 (on)</span><b>{{ fixed(activeRun.metrics.critical?.['hit@3']) }}</b></div>
        <div v-if="activeRun.metrics?.frozen?.cases" class="metric"><span>冻结集 hit@3 (on)</span><b>{{ fixed(activeRun.metrics.frozen?.['hit@3']) }}</b></div>
        <div class="metric"><span>答案关键词命中（可答）</span><b>{{ pct(activeRun.metrics?.answer?.answerable?.keyword_hit ?? activeRun.metrics?.answer?.keyword_hit) }}</b></div>
        <div v-if="activeRun.metrics?.answer?.unanswerable?.abstention_rate != null || activeRun.metrics?.answer?.unanswerable?.keyword_hit != null" class="metric"><span>不可答拒答率</span><b>{{ pct(activeRun.metrics.answer.unanswerable.abstention_rate ?? activeRun.metrics.answer.unanswerable.keyword_hit) }}</b></div>
        <div v-if="activeRun.metrics?.answer?.answerable?.citation_coverage != null" class="metric"><span>引用覆盖率（可答）</span><b>{{ pct(activeRun.metrics.answer.answerable.citation_coverage) }}</b></div>
        <div v-if="activeRun.metrics?.answer?.answerable?.invalid_citation_rate != null" class="metric"><span>无效引用率（可答）</span><b>{{ pct(activeRun.metrics.answer.answerable.invalid_citation_rate) }}</b></div>
        <div v-if="activeRun.metrics?.answer?.unsupported_answer_rate != null" class="metric"><span>无依据回答率</span><b :class="{ error: (activeRun.metrics.answer.unsupported_answer_rate ?? 0) > 0.01 }">{{ pct(activeRun.metrics.answer.unsupported_answer_rate) }}</b></div>
        <div class="metric"><span>答案正确性</span><b>{{ fixed(activeRun.metrics?.answer?.correctness) }}</b></div>
        <div class="metric"><span>忠实度</span><b>{{ fixed(activeRun.metrics?.answer?.faithfulness) }}</b></div>
        <div class="metric"><span>完整性</span><b>{{ fixed(activeRun.metrics?.answer?.completeness) }}</b></div>
        <div class="metric"><span>逻辑性</span><b>{{ fixed(activeRun.metrics?.answer?.logic) }}</b></div>
        <div v-if="activeRun.metrics?.calibration?.pairs" class="metric"><span>裁判-人工 Kappa（{{ activeRun.metrics.calibration.pairs }} 对）</span><b :class="{ error: activeRun.metrics.calibration.kappa != null && activeRun.metrics.calibration.kappa < 0.6 }">{{ activeRun.metrics.calibration.kappa ?? '样本不足' }}</b></div>
      </div>
      <p v-if="activeRun.metrics" class="muted">
        <template v-if="metricsOn?.answerable_cases != null">
          检索指标仅统计可答用例（{{ metricsOn.answerable_cases }} 条）；
          不可答 {{ metricsOn.unanswerable_cases ?? 0 }} 条、未标注 {{ metricsOn.unlabeled_cases ?? 0 }} 条单列，不计入命中率；
          检索异常 {{ metricsOn.error_cases ?? 0 }} 条单列且不计入质量指标。
        </template>
        <template v-else>
          该运行生成于指标口径升级前，未区分不可答/未标注用例；建议重跑以获取修正后的指标。
        </template>
      </p>
      <p v-if="metricsOn?.retrieval_modes" class="muted">
        检索模式分布（on）：<span v-for="(count, mode) in metricsOn.retrieval_modes" :key="mode" class="mode-chip">{{ mode }} × {{ count }}</span>
      </p>
      <table class="table">
        <thead><tr><th>query</th><th>ranked</th><th>relevant</th><th>Bad Case</th><th>关键词</th><th>正确性</th><th>人工复核</th><th>检索链</th></tr></thead>
        <tbody>
          <tr v-for="r in results" :key="r.id">
            <td>{{ r.query }}</td>
            <td class="muted">{{ r.ranked.join('、') || '-' }}</td>
            <td class="muted">{{ r.relevant.join('、') || '-' }}</td>
            <td><span class="tag" :class="r.bad_case_type === 'ok' ? 'ok' : 'bad'">{{ r.bad_case_type || '-' }}</span></td>
            <td>{{ pct(r.metrics?.answer?.keyword_hit) }}</td>
            <td>{{ fixed(r.metrics?.answer?.judge?.correctness) }}</td>
            <td>
              <span v-if="editingResultId === r.id" class="human-score-row">
                <input v-model.number="humanScoreForm.score" type="number" min="0" max="5" placeholder="0-5" />
                <input v-model="humanScoreForm.judge" placeholder="裁判" />
                <button class="mini ok" @click="submitHumanScore(r)">保存</button>
                <button class="mini ghost" @click="cancelHumanScore">取消</button>
              </span>
              <span v-else-if="r.human_score != null" class="tag ok">
                人工 {{ r.human_score }} 分
                <span v-if="r.human_judge" class="muted">（{{ r.human_judge }}）</span>
              </span>
              <span v-else>
                <button class="mini" @click="editingResultId = r.id">评分</button>
              </span>
            </td>
            <td class="muted ellipsis">{{ r.retrieval_summary }}</td>
          </tr>
          <tr v-if="!results.length"><td colspan="8" class="muted">暂无逐条结果（运行中或未完成）</td></tr>
        </tbody>
      </table>
    </section>
  </div>
  <ConfirmDialog
    :visible="!!pending"
    :title="pending?.title || ''"
    :message="pending?.message || ''"
    confirm-text="删除"
    danger
    @confirm="confirmPending"
    @cancel="pending = null"
  />
</template>

<style scoped>
.btn { padding: 8px 14px; border-radius: 9px; border: 1px solid var(--brand); background: var(--brand); color: #fff; font-weight: 600; cursor: pointer; font-size: 13px; }
.btn.ghost { background: var(--surface); color: var(--brand-strong); border-color: var(--line); }
.btn:disabled { opacity: .6; cursor: default; }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; }
.panel { background: var(--surface); border: 1px solid var(--line); border-radius: 14px; padding: 16px; margin-bottom: 16px; box-shadow: var(--shadow-sm); }
.panel-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.panel-head h3 { font-size: 14px; font-weight: 800; }
.eval-progress { margin-bottom: 12px; padding: 10px 12px; border: 1px solid var(--line); border-radius: 10px; background: var(--surface-2, var(--surface)); }
.progress-track { height: 8px; border-radius: 999px; background: var(--line); overflow: hidden; }
.progress-fill { height: 100%; border-radius: 999px; background: var(--brand); transition: width .4s ease; }
.progress-meta { display: flex; justify-content: space-between; gap: 12px; margin-top: 7px; font-size: 12.5px; color: var(--ink); }
.eval-progress .muted { margin-top: 5px; font-size: 12px; }
.run-mini { margin-top: 4px; font-size: 11px; color: var(--muted); white-space: nowrap; }
.set-list { display: flex; flex-direction: column; gap: 6px; margin-bottom: 12px; }
.set-item { display: flex; justify-content: space-between; align-items: center; gap: 8px; padding: 9px 10px; border: 1px solid var(--line); border-radius: 9px; background: var(--surface); cursor: pointer; text-align: left; }
.set-item.on { border-color: var(--brand); background: var(--brand-soft); }
.create-box, .case-form, .run-form { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.create-box input, .create-box select, .case-form input, .run-form input { padding: 8px 10px; border: 1px solid var(--line); border-radius: 9px; background: var(--surface); color: var(--ink); font-size: 12.5px; }
.create-box input:first-child, .case-form input:first-child { flex: 1; min-width: 180px; }
.run-form label { display: flex; gap: 6px; align-items: center; font-size: 12.5px; }
.run-form select { padding: 7px 9px; border: 1px solid var(--line); border-radius: 9px; background: var(--surface); color: var(--ink); font-size: 12.5px; max-width: 220px; }
.model-pick { flex-direction: column; align-items: flex-start !important; gap: 4px !important; }
.case-edit { display: flex; gap: 10px; flex-wrap: wrap; align-items: flex-end; }
.case-edit label { display: flex; flex-direction: column; gap: 4px; font-size: 11.5px; color: var(--ink-3); }
.case-edit input, .case-edit select { padding: 6px 8px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); color: var(--ink); font-size: 12px; }
.case-edit label:nth-child(2) input { min-width: 240px; }
.page-size { margin-left: 4px; padding: 3px 6px; border: 1px solid var(--line); border-radius: 6px; background: var(--surface); color: var(--ink); font-size: 11.5px; }
.pager { display: flex; align-items: center; justify-content: flex-end; gap: 10px; margin-top: 10px; }
.warn { color: #b45309; background: #fffbeb; padding: 9px 12px; border-radius: 9px; font-size: 12px; margin-bottom: 10px; }
.table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.table th, .table td { text-align: left; padding: 8px 6px; border-bottom: 1px solid var(--line); }
.table th { color: var(--ink-3); font-weight: 600; }
.muted { color: var(--ink-3); font-size: 12px; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11.5px; }
.mini { padding: 4px 9px; border: 1px solid var(--line); background: var(--surface); border-radius: 7px; cursor: pointer; font-size: 11.5px; }
.mini.danger { color: #b91c1c; border-color: #fecaca; }
.tag { display: inline-block; padding: 2px 8px; border-radius: 999px; background: #f1f5f9; color: var(--ink-3); font-size: 11px; }
.tag.ok { background: var(--success-soft); color: #047857; }
.tag.bad { background: #fef2f2; color: #b91c1c; }
.tag.pending { background: #fffbeb; color: #b45309; }
.metrics { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 10px; margin-bottom: 14px; }
.metric { background: #f8fafc; border-radius: 10px; padding: 10px; display: flex; flex-direction: column; gap: 4px; }
.metric span { color: var(--ink-3); font-size: 11.5px; }
.metric b { font-size: 18px; }
.error { color: #b91c1c; background: #fef2f2; padding: 10px 12px; border-radius: 10px; margin-bottom: 12px; }
.ok { color: #047857; background: var(--success-soft); padding: 10px 12px; border-radius: 10px; margin-bottom: 12px; }
.ellipsis { max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.human-score-row { display: flex; gap: 6px; align-items: center; font-size: 12px; }
.human-score-row input[type='number'] { width: 44px; padding: 4px 6px; border: 1px solid var(--line); border-radius: 7px; background: var(--surface); color: var(--ink); font-size: 12px; }
.human-score-row input:not([type='number']) { width: 64px; padding: 4px 6px; border: 1px solid var(--line); border-radius: 7px; background: var(--surface); color: var(--ink); font-size: 12px; }
.field-hint { margin: 8px 0 4px; font-size: 11.5px; color: var(--ink-3); line-height: 1.7; background: #f8fafc; border-radius: 8px; padding: 8px 10px; }
.field-hint b { color: var(--ink-2); }
.import-box { border: 1px dashed var(--line); border-radius: 12px; padding: 12px; margin: 10px 0 14px; background: var(--surface); }
.manual-add { margin: 10px 0 4px; border: 1px solid var(--line); border-radius: 10px; background: var(--surface); }
.manual-add summary { cursor: pointer; padding: 9px 12px; font-size: 12.5px; font-weight: 600; color: var(--brand-strong); user-select: none; }
.manual-add[open] summary { border-bottom: 1px solid var(--line); margin-bottom: 10px; }
.manual-add .case-form { padding: 0 12px; }
.import-box .panel-head h3 { font-size: 13.5px; }
.import-actions { display: flex; align-items: center; gap: 10px; }
.import-preview { margin: 8px 0; padding: 8px 10px; border-radius: 9px; background: #f8fafc; font-size: 12px; }
.warn-text { color: #b45309; }
.preview-list { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
.preview-chip { padding: 2px 8px; border-radius: 999px; background: var(--surface); border: 1px solid var(--line); font-size: 11px; }
.import-error-list { margin: 8px 0 0; padding-left: 18px; max-height: 160px; overflow: auto; color: #b91c1c; font-size: 11.5px; line-height: 1.7; }
.import-area { width: 100%; margin-top: 6px; padding: 10px; border: 1px solid var(--line); border-radius: 9px; font-size: 12px; font-family: ui-monospace, Menlo, monospace; background: var(--surface); color: var(--ink); resize: vertical; }
.upload-btn { padding: 7px 12px; border-radius: 9px; border: 1px solid var(--brand); background: var(--brand-soft); color: var(--brand-strong); font-size: 12.5px; font-weight: 600; cursor: pointer; }
.doc-link { color: var(--brand-strong); font-size: 12px; text-decoration: none; font-weight: 600; }
.doc-link:hover { text-decoration: underline; }
@media (max-width: 1100px) { .two-col { grid-template-columns: 1fr; } .metrics { grid-template-columns: 1fr 1fr 1fr; } }
</style>
