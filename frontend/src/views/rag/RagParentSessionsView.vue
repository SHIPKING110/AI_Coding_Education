<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import PageHead from '@/components/PageHead.vue'
import RagTabs from '@/components/RagTabs.vue'
import { getParentSession, listParentSessions } from '@/api/ragAdmin'

const loading = ref(false)
const error = ref('')
const items = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const status = ref('')
const risk = ref('')
const selected = ref<any>(null)
const detailLoading = ref(false)

const totalPages = ref(1)

const STATUS_LABEL: Record<string, string> = {
  open: '进行中',
  closed: '已解决',
  escalated: '已转人工',
}
const ROLE_LABEL: Record<string, string> = {
  user: '家长',
  assistant: 'AI 客服',
  staff: '人工客服',
}

function statusLabel(v: string | null | undefined) {
  return v ? STATUS_LABEL[v] || v : '—'
}
function roleLabel(v: string | null | undefined) {
  return v ? ROLE_LABEL[v] || v : '—'
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await listParentSessions({
      page: page.value,
      page_size: pageSize,
      status: status.value || undefined,
      risk: risk.value === '' ? undefined : risk.value === 'true',
    })
    items.value = res.items
    total.value = res.total
    totalPages.value = Math.max(1, Math.ceil(total.value / pageSize))
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

async function open(t: any) {
  selected.value = t
  detailLoading.value = true
  try {
    selected.value = await getParentSession(t.thread_id)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载详情失败'
  } finally {
    detailLoading.value = false
  }
}

function changePage(delta: number) {
  page.value = Math.max(1, Math.min(totalPages.value, page.value + delta))
  void load()
}
function resetAndLoad() {
  page.value = 1
  void load()
}

function fmt(iso: string | null | undefined) {
  return iso ? iso.slice(0, 19).replace('T', ' ') : '-'
}

// 家长客服的 tokens 仅为「回复字数/2」的粗略估算，单独标注以免管理员误读
const estTokens = computed(() => {
  const msgs = selected.value?.messages || []
  return msgs.reduce((sum: number, m: any) => sum + (m.role === 'assistant' ? (m.tokens || 0) : 0), 0)
})

onMounted(load)
</script>

<template>
  <div>
    <PageHead title="家长会话" eyebrow="PARENT SESSIONS" sub="家长客服会话线程、消息记录与知识检索证据">
      <template #actions>
        <button class="btn" :disabled="loading" @click="load">{{ loading ? '刷新中…' : '刷新' }}</button>
      </template>
    </PageHead>

    <RagTabs />

    <p v-if="error" class="error">{{ error }}</p>

    <section class="toolbar">
      <label>会话状态
        <select v-model="status" @change="resetAndLoad">
          <option value="">全部</option>
          <option value="open">进行中</option>
          <option value="closed">已解决</option>
          <option value="escalated">已转人工</option>
        </select>
      </label>
      <label>风险
        <select v-model="risk" @change="resetAndLoad">
          <option value="">全部</option>
          <option value="true">仅风险会话</option>
          <option value="false">无风险</option>
        </select>
      </label>
    </section>

    <section class="panel">
      <table class="table">
        <thead>
          <tr>
            <th>更新时间</th>
            <th>会话线程</th>
            <th>状态</th>
            <th>风险</th>
            <th>消息数</th>
            <th>检索次数</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="t in items" :key="t.thread_id">
            <td class="mono">{{ fmt(t.updated_at) }}</td>
            <td class="mono" :title="t.thread_id">{{ (t.thread_id || '').slice(0, 8) }}</td>
            <td>
              <span class="tag" :class="t.status === 'escalated' ? 'bad' : t.status === 'closed' ? 'ok' : 'pending'">
                {{ statusLabel(t.status) }}
              </span>
            </td>
            <td>
              <span v-if="t.risk_flag" class="tag bad">有风险</span>
              <span v-else class="muted">—</span>
            </td>
            <td>{{ t.message_count }}</td>
            <td>{{ t.trace_count }}</td>
            <td><button class="mini" @click="open(t)">详情</button></td>
          </tr>
          <tr v-if="!items.length"><td colspan="7" class="muted">暂无会话</td></tr>
        </tbody>
      </table>
      <div class="pager">
        <span class="muted">共 {{ total }} 条</span>
        <button class="mini" :disabled="page <= 1" @click="changePage(-1)">上一页</button>
        <span>第 {{ page }} / {{ totalPages }} 页</span>
        <button class="mini" :disabled="page >= totalPages" @click="changePage(1)">下一页</button>
      </div>
    </section>

    <aside v-if="selected" class="drawer">
      <div class="drawer-head">
        <div>
          <h3>会话详情</h3>
          <p class="muted mono">线程 {{ (selected.thread?.id || selected.thread_id || '').slice(0, 8) }}</p>
        </div>
        <button class="mini" @click="selected = null">关闭</button>
      </div>

      <p v-if="detailLoading" class="muted">加载中…</p>
      <template v-else>
        <div class="meta-grid">
          <div><span>会话状态</span><b>{{ statusLabel(selected.thread?.status) }}</b></div>
          <div><span>风险标记</span><b>{{ selected.thread?.risk_flag ? '有风险' : '无' }}</b></div>
          <div><span>创建时间</span><b class="mono">{{ fmt(selected.thread?.created_at) }}</b></div>
          <div><span>最近更新</span><b class="mono">{{ fmt(selected.thread?.updated_at) }}</b></div>
          <div><span>消息条数</span><b>{{ selected.messages?.length || 0 }}</b></div>
          <div><span>检索证据</span><b>{{ selected.traces?.length || 0 }} 次</b></div>
          <div><span>回复 Token（估算）</span><b>≈ {{ estTokens.toLocaleString() }}（按字数估算，仅供参考）</b></div>
        </div>

        <div class="panel-head"><h3>消息记录</h3><span class="muted">{{ selected.messages?.length || 0 }} 条</span></div>
        <div class="timeline">
          <div v-for="m in selected.messages" :key="m.id" class="msg" :class="m.role">
            <div class="msg-head">
              <span class="tag" :class="m.role === 'assistant' ? 'ok' : m.role === 'staff' ? 'pending' : ''">{{ roleLabel(m.role) }}</span>
              <span class="muted mono">{{ fmt(m.created_at) }}</span>
              <span v-if="m.role === 'assistant' && m.tokens" class="muted">≈ {{ m.tokens }} tok（估算）</span>
            </div>
            <p>{{ (m.content || '').slice(0, 400) }}</p>
          </div>
          <div v-if="!selected.messages?.length" class="muted">暂无消息</div>
        </div>

        <div class="panel-head"><h3>检索证据（知识库命中）</h3><span class="muted">{{ selected.traces?.length || 0 }} 次</span></div>
        <div class="trace-list">
          <div v-for="t in selected.traces" :key="t.trace_id" class="trace">
            <span class="tag" :class="t.rag_status === 'error' ? 'bad' : t.rag_status === 'no_hit' ? 'pending' : 'ok'">
              {{ t.rag_status }}
            </span>
            <span class="mono">{{ (t.trace_id || '').slice(0, 10) }}</span>
            <span class="muted">{{ t.latency_ms }} ms</span>
          </div>
          <div v-if="!selected.traces?.length" class="muted">无检索记录</div>
        </div>
      </template>
    </aside>
  </div>
</template>

<style scoped>
.btn { padding: 8px 14px; border-radius: 9px; border: 1px solid var(--brand); background: var(--brand); color: #fff; font-weight: 600; cursor: pointer; font-size: 13px; }
.toolbar { display: flex; gap: 16px; align-items: center; margin-bottom: 12px; flex-wrap: wrap; }
.toolbar label { display: flex; gap: 6px; align-items: center; font-size: 12.5px; color: var(--ink-2); }
.toolbar select { padding: 8px 10px; border: 1px solid var(--line); border-radius: 9px; background: var(--surface); color: var(--ink); }
.panel { background: var(--surface); border: 1px solid var(--line); border-radius: 14px; padding: 16px; box-shadow: var(--shadow-sm); }
.table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.table th, .table td { text-align: left; padding: 8px 6px; border-bottom: 1px solid var(--line); vertical-align: top; }
.table th { color: var(--ink-3); font-weight: 600; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11.5px; }
.muted { color: var(--ink-3); font-size: 12px; }
.mini { padding: 4px 9px; border: 1px solid var(--line); background: var(--surface); border-radius: 7px; cursor: pointer; font-size: 11.5px; color: var(--ink-2); }
.tag { display: inline-block; padding: 2px 8px; border-radius: 999px; background: #f1f5f9; color: var(--ink-3); font-size: 11px; }
.tag.ok { background: var(--success-soft); color: #047857; }
.tag.bad { background: #fef2f2; color: #b91c1c; }
.tag.pending { background: #fef3c7; color: #92400e; }
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
.timeline { display: flex; flex-direction: column; gap: 10px; max-height: 340px; overflow: auto; }
.msg { border: 1px solid var(--line); border-radius: 10px; padding: 10px; }
.msg.user { background: #f8fafc; }
.msg.assistant { background: #fff; }
.msg.staff { background: #fffbeb; }
.msg-head { display: flex; gap: 8px; align-items: center; margin-bottom: 6px; flex-wrap: wrap; }
.msg p { font-size: 12.5px; line-height: 1.6; white-space: pre-wrap; }
.trace-list { display: flex; flex-direction: column; gap: 8px; }
.trace { display: flex; gap: 10px; align-items: center; border: 1px solid var(--line); border-radius: 8px; padding: 8px; font-size: 12.5px; }
@media (max-width: 1100px) { .drawer { left: 20px; width: auto; } }
</style>
