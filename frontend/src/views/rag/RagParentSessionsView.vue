<script setup lang="ts">
import { onMounted, ref } from 'vue'

import PageHead from '@/components/PageHead.vue'
import RagTabs from '@/components/RagTabs.vue'
import { getParentSession, listParentSessions, type RagTrace } from '@/api/ragAdmin'

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

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await listParentSessions({ page: page.value, page_size: pageSize, status: status.value || undefined, risk: risk.value === '' ? undefined : risk.value === 'true' })
    items.value = res.items
    total.value = res.total
    totalPages.value = Math.max(1, Math.ceil(total.value / pageSize))
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'load failed'
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
    error.value = e instanceof Error ? e.message : 'load detail failed'
  } finally {
    detailLoading.value = false
  }
}

function fmt(iso: string | null | undefined) {
  return iso ? iso.slice(0, 19).replace('T', ' ') : '-'
}

onMounted(load)
</script>

<template>
  <div>
    <PageHead title="家长会话观测" eyebrow="PARENT SESSIONS" sub="家长客服线程、消息与 RAG 检索证据">
      <template #actions>
        <button class="btn" :disabled="loading" @click="load">{{ loading ? 'loading...' : 'refresh' }}</button>
      </template>
    </PageHead>

    <RagTabs />

    <p v-if="error" class="error">{{ error }}</p>

    <section class="toolbar">
      <select v-model="status" @change="page = 1; load()">
        <option value="">all statuses</option>
        <option value="open">open</option>
        <option value="closed">closed</option>
        <option value="escalated">escalated</option>
      </select>
      <select v-model="risk" @change="page = 1; load()">
        <option value="">all risk</option>
        <option value="true">risk only</option>
        <option value="false">no risk</option>
      </select>
    </section>

    <section class="panel">
      <table class="table">
        <thead>
          <tr><th>updated</th><th>thread</th><th>status</th><th>risk</th><th>messages</th><th>traces</th><th></th></tr>
        </thead>
        <tbody>
          <tr v-for="t in items" :key="t.thread_id">
            <td class="mono">{{ fmt(t.updated_at) }}</td>
            <td class="mono">{{ t.thread_id.slice(0, 8) }}</td>
            <td>{{ t.status }}</td>
            <td>{{ t.risk_flag ? 'risk' : '-' }}</td>
            <td>{{ t.message_count }}</td>
            <td>{{ t.trace_count }}</td>
            <td><button class="mini" @click="open(t)">detail</button></td>
          </tr>
          <tr v-if="!items.length"><td colspan="7" class="muted">no sessions</td></tr>
        </tbody>
      </table>
      <div class="pager">
        <span class="muted">total {{ total }}</span>
        <button class="mini" :disabled="page <= 1" @click="page--; load()">prev</button>
        <span>{{ page }} / {{ totalPages }}</span>
        <button class="mini" :disabled="page >= totalPages" @click="page++; load()">next</button>
      </div>
    </section>

    <aside v-if="selected" class="drawer">
      <div class="drawer-head">
        <div>
          <h3>thread {{ selected.thread?.id?.slice(0, 8) }}</h3>
          <p class="muted">{{ selected.thread?.status }}</p>
        </div>
        <button class="mini" @click="selected = null">close</button>
      </div>
      <p v-if="detailLoading" class="muted">loading...</p>
      <template v-else>
        <div class="panel-head"><h3>messages</h3></div>
        <div class="timeline">
          <div v-for="m in selected.messages" :key="m.id" class="msg">
            <div class="msg-head">
              <span class="tag">{{ m.role }}</span>
              <span class="muted mono">{{ fmt(m.created_at) }}</span>
            </div>
            <p>{{ (m.content || '').slice(0, 300) }}</p>
          </div>
        </div>
        <div class="panel-head"><h3>RAG traces</h3><span class="muted">{{ selected.traces?.length || 0 }}</span></div>
        <div class="trace-list">
          <div v-for="t in selected.traces" :key="t.trace_id" class="trace">
            <span class="tag" :class="t.rag_status === 'error' ? 'bad' : t.rag_status === 'no_hit' ? 'pending' : 'ok'">{{ t.rag_status }}</span>
            <span class="mono">{{ t.trace_id }}</span>
            <span class="muted">{{ t.latency_ms }} ms</span>
          </div>
          <div v-if="!selected.traces?.length" class="muted">no traces</div>
        </div>
      </template>
    </aside>
  </div>
</template>

<style scoped>
.btn { padding: 8px 14px; border-radius: 9px; border: 1px solid var(--brand); background: var(--brand); color: #fff; font-weight: 600; cursor: pointer; font-size: 13px; }
.toolbar { display: flex; gap: 10px; align-items: center; margin-bottom: 12px; flex-wrap: wrap; }
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
.panel-head { display: flex; align-items: center; justify-content: space-between; margin: 14px 0 8px; }
.panel-head h3 { font-size: 14px; font-weight: 800; }
.timeline { display: flex; flex-direction: column; gap: 10px; max-height: 320px; overflow: auto; }
.msg { border: 1px solid var(--line); border-radius: 10px; padding: 10px; }
.msg-head { display: flex; gap: 8px; align-items: center; margin-bottom: 6px; flex-wrap: wrap; }
.msg p { font-size: 12.5px; line-height: 1.6; white-space: pre-wrap; }
.trace-list { display: flex; flex-direction: column; gap: 8px; }
.trace { display: flex; gap: 10px; align-items: center; border: 1px solid var(--line); border-radius: 8px; padding: 8px; font-size: 12.5px; }
@media (max-width: 1100px) { .drawer { left: 20px; width: auto; } }
</style>
PY