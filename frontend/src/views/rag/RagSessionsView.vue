<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import PageHead from '@/components/PageHead.vue'
import RagTabs from '@/components/RagTabs.vue'
import { getAgentRun, getAgentSession, listAgentSessions, type AgentRun, type AgentSessionSummary } from '@/api/agentOps'

const loading = ref(false)
const error = ref('')
const items = ref<AgentSessionSummary[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const q = ref('')
const agentId = ref('')
const selectedId = ref<string | null>(null)
const detailLoading = ref(false)
const detail = ref<{ conversation: any; messages: any[]; runs: AgentRun[] } | null>(null)
const selectedRun = ref<{ run: AgentRun; spans: any[] } | null>(null)

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await listAgentSessions({
      q: q.value || undefined,
      agent_id: agentId.value || undefined,
      page: page.value,
      page_size: pageSize,
    })
    items.value = res.items
    total.value = res.total
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

async function open(conv: AgentSessionSummary) {
  selectedId.value = conv.conversation_id
  detailLoading.value = true
  detail.value = null
  selectedRun.value = null
  try {
    detail.value = await getAgentSession(conv.conversation_id)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载会话详情失败'
  } finally {
    detailLoading.value = false
  }
}

async function openRun(runId: string) {
  try {
    selectedRun.value = await getAgentRun(runId)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载运行详情失败'
  }
}

function search() {
  page.value = 1
  void load()
}
function changePage(delta: number) {
  page.value = Math.max(1, Math.min(totalPages.value, page.value + delta))
  void load()
}
function fmt(iso: string | null | undefined) {
  return iso ? iso.slice(0, 19).replace('T', ' ') : '-'
}

onMounted(load)
</script>

<template>
  <div>
    <PageHead title="会话观测" eyebrow="SESSION OBSERVABILITY" sub="Agent 会话 → 轮次 → 执行详情三级钻取">
      <template #actions>
        <button class="btn" :disabled="loading" @click="load">{{ loading ? '刷新中…' : '刷新' }}</button>
      </template>
    </PageHead>

    <RagTabs />

    <p v-if="error" class="error">{{ error }}</p>

    <section class="toolbar">
      <input v-model="q" placeholder="搜索会话标题" @keyup.enter="search" />
      <select v-model="agentId" @change="search">
        <option value="">全部 Agent</option>
        <option value="assistant">assistant</option>
        <option value="report_ppt">report_ppt</option>
        <option value="class_parent_ppt">class_parent_ppt</option>
      </select>
      <button class="btn" @click="search">查询</button>
    </section>

    <section class="panel">
      <table class="table">
        <thead>
          <tr><th>更新时间</th><th>会话</th><th>Agent</th><th>消息</th><th>轮次</th><th>成功/错误</th><th>RAG 使用</th><th>意图</th><th></th></tr>
        </thead>
        <tbody>
          <tr v-for="s in items" :key="s.conversation_id">
            <td class="mono">{{ fmt(s.updated_at) }}</td>
            <td class="query">{{ s.title }}</td>
            <td>{{ s.agent_id }}</td>
            <td>{{ s.message_count }}</td>
            <td>{{ s.run_count }}</td>
            <td>{{ s.ok_runs }} / {{ s.error_runs }}</td>
            <td>{{ s.rag_used }} / {{ s.needs_rag }}</td>
            <td class="muted">{{ s.intents.map(i => i.intent).join(', ') || '-' }}</td>
            <td><button class="mini" @click="open(s)">详情</button></td>
          </tr>
          <tr v-if="!items.length"><td colspan="9" class="muted">暂无会话</td></tr>
        </tbody>
      </table>
      <div class="pager">
        <span class="muted">共 {{ total }} 条</span>
        <button class="mini" :disabled="page <= 1" @click="changePage(-1)">上一页</button>
        <span>{{ page }} / {{ totalPages }}</span>
        <button class="mini" :disabled="page >= totalPages" @click="changePage(1)">下一页</button>
      </div>
    </section>

    <aside v-if="selectedId" class="drawer">
      <div class="drawer-head">
        <div>
          <h3>{{ detail?.conversation?.title || '会话详情' }}</h3>
          <p class="muted mono">{{ selectedId }}</p>
        </div>
        <button class="mini" @click="selectedId = null; detail = null; selectedRun = null">关闭</button>
      </div>

      <p v-if="detailLoading" class="muted">加载中…</p>
      <template v-else-if="detail">
        <div class="meta-grid">
          <div><span>Agent</span><b>{{ detail.conversation.agent_id }}</b></div>
          <div><span>阶段</span><b>{{ detail.conversation.stage }}</b></div>
          <div><span>消息数</span><b>{{ detail.messages.length }}</b></div>
          <div><span>轮次</span><b>{{ detail.runs.length }}</b></div>
        </div>

        <div class="panel-head"><h3>消息时间线</h3></div>
        <div class="timeline">
          <div v-for="m in detail.messages" :key="m.id" class="msg" :class="m.role">
            <div class="msg-head">
              <span class="tag">{{ m.role }}</span>
              <span class="muted mono">{{ fmt(m.created_at) }}</span>
              <button v-if="m.run_id" class="mini" @click="openRun(m.run_id)">查看运行</button>
            </div>
            <p>{{ (m.content || '').slice(0, 300) }}</p>
          </div>
        </div>

        <div class="panel-head"><h3>轮次列表</h3></div>
        <div class="run-list">
          <button v-for="r in detail.runs" :key="r.run_id" class="run-item" @click="openRun(r.run_id)">
            <span>{{ r.intent }}</span>
            <span class="muted">{{ r.task_kind }}</span>
            <span class="tag" :class="r.status === 'ok' ? 'ok' : 'bad'">{{ r.status }}</span>
            <span class="muted">{{ r.latency_ms }} ms</span>
          </button>
        </div>

        <div v-if="selectedRun" class="run-detail">
          <div class="panel-head"><h3>轮次详情：{{ selectedRun.run.run_id }}</h3></div>
          <div class="meta-grid">
            <div><span>意图</span><b>{{ selectedRun.run.intent }}</b></div>
            <div><span>RAG 决策</span><b>{{ selectedRun.run.rag_decision }}</b></div>
            <div><span>状态</span><b>{{ selectedRun.run.status }}</b></div>
            <div><span>耗时</span><b>{{ selectedRun.run.latency_ms }} ms</b></div>
          </div>
          <div class="panel-head"><h3>Spans</h3></div>
          <div class="span-list">
            <div v-for="s in selectedRun.spans" :key="s.span_id" class="span">
              <span class="tag">{{ s.span_type }}</span>
              <strong>{{ s.name }}</strong>
              <span class="muted">{{ s.latency_ms }} ms · {{ s.status }}</span>
              <p v-if="s.summary" class="muted">{{ s.summary }}</p>
            </div>
            <div v-if="!selectedRun.spans.length" class="muted">无 span</div>
          </div>
        </div>
      </template>
    </aside>
  </div>
</template>

<style scoped>
.btn { padding: 8px 14px; border-radius: 9px; border: 1px solid var(--brand); background: var(--brand); color: #fff; font-weight: 600; cursor: pointer; font-size: 13px; }
.toolbar { display: flex; gap: 10px; align-items: center; margin-bottom: 12px; flex-wrap: wrap; }
.toolbar input, .toolbar select { padding: 8px 10px; border: 1px solid var(--line); border-radius: 9px; background: var(--surface); color: var(--ink); }
.panel { background: var(--surface); border: 1px solid var(--line); border-radius: 14px; padding: 16px; box-shadow: var(--shadow-sm); }
.table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.table th, .table td { text-align: left; padding: 8px 6px; border-bottom: 1px solid var(--line); vertical-align: top; }
.table th { color: var(--ink-3); font-weight: 600; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11.5px; }
.muted { color: var(--ink-3); font-size: 12px; }
.query { max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mini { padding: 4px 9px; border: 1px solid var(--line); background: var(--surface); border-radius: 7px; cursor: pointer; font-size: 11.5px; color: var(--ink-2); }
.tag { display: inline-block; padding: 2px 8px; border-radius: 999px; background: #f1f5f9; color: var(--ink-3); font-size: 11px; }
.tag.ok { background: var(--success-soft); color: #047857; }
.tag.bad { background: #fef2f2; color: #b91c1c; }
.pager { display: flex; gap: 10px; align-items: center; justify-content: flex-end; margin-top: 12px; }
.error { color: #b91c1c; background: #fef2f2; padding: 10px 12px; border-radius: 10px; margin-bottom: 12px; }
.drawer { position: fixed; right: 20px; top: 20px; bottom: 20px; width: min(720px, 52vw); background: var(--surface); border: 1px solid var(--line); border-radius: 16px; box-shadow: var(--shadow-lg); padding: 18px; overflow: auto; z-index: 80; }
.drawer-head { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
.drawer-head h3 { font-size: 16px; font-weight: 800; line-height: 1.4; }
.meta-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 14px 0; }
.meta-grid div { background: #f8fafc; border-radius: 10px; padding: 9px 10px; display: flex; flex-direction: column; gap: 3px; }
.meta-grid span { color: var(--ink-3); font-size: 11.5px; }
.meta-grid b { font-size: 12.5px; word-break: break-all; }
.panel-head { display: flex; align-items: center; justify-content: space-between; margin: 14px 0 8px; }
.panel-head h3 { font-size: 14px; font-weight: 800; }
.timeline { display: flex; flex-direction: column; gap: 10px; max-height: 320px; overflow: auto; }
.msg { border: 1px solid var(--line); border-radius: 10px; padding: 10px; }
.msg.user { background: #f8fafc; }
.msg.assistant { background: #fff; }
.msg-head { display: flex; gap: 8px; align-items: center; margin-bottom: 6px; flex-wrap: wrap; }
.msg p { font-size: 12.5px; line-height: 1.6; white-space: pre-wrap; }
.run-list { display: flex; flex-direction: column; gap: 8px; }
.run-item { display: flex; gap: 10px; align-items: center; padding: 8px 10px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); cursor: pointer; text-align: left; }
.run-detail { margin-top: 14px; border-top: 1px solid var(--line); padding-top: 12px; }
.span-list { display: flex; flex-direction: column; gap: 8px; }
.span { border: 1px solid var(--line); border-radius: 8px; padding: 8px; font-size: 12.5px; }
.span p { margin-top: 4px; }
@media (max-width: 1100px) { .drawer { left: 20px; width: auto; } }
</style>
