<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import PageHead from '@/components/PageHead.vue'
import RagTabs from '@/components/RagTabs.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import {
  deleteRagDocument,
  getRagDocument,
  getRagDocumentChunks,
  listKnowledgeBases,
  listRagCollections,
  listRagDocuments,
  reindexRagDocument,
  sweepRagCollections,
  toggleRagDocument,
  toggleRagParentVisible,
  triggerRagSync,
  type RagChunk,
  type RagCollectionStat,
  type RagDoc,
} from '@/api/ragAdmin'

type Tab = 'documents' | 'bases' | 'collections'

const tab = ref<Tab>('documents')
const loading = ref(false)
const error = ref('')
const docs = ref<RagDoc[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const q = ref('')
const statusFilter = ref('')
const visibility = ref('')
const enabledFilter = ref('')
const bases = ref<any[]>([])
const collections = ref<{ active: string; collections: RagCollectionStat[] } | null>(null)
const selected = ref<RagDoc | null>(null)
const chunks = ref<RagChunk[]>([])
const detailLoading = ref(false)
const actionMsg = ref('')
const pending = ref<{ title: string; message: string; danger: boolean; run: () => void | Promise<void> } | null>(null)

function ask(title: string, message: string, run: () => void | Promise<void>, danger = true) {
  pending.value = { title, message, danger, run }
}
async function confirmPending() {
  const p = pending.value
  pending.value = null
  if (p) await p.run()
}

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

async function loadDocs() {
  loading.value = true
  error.value = ''
  try {
    const res = await listRagDocuments({
      q: q.value || undefined,
      status: statusFilter.value || undefined,
      visibility: visibility.value || undefined,
      enabled: enabledFilter.value === '' ? undefined : enabledFilter.value === '1',
      page: page.value,
      page_size: pageSize,
    })
    docs.value = res.items
    total.value = res.total
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

async function loadBases() {
  try {
    bases.value = (await listKnowledgeBases()).items
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  }
}

async function loadCollections() {
  try {
    collections.value = await listRagCollections()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  }
}

async function openDoc(doc: RagDoc) {
  selected.value = doc
  chunks.value = []
  detailLoading.value = true
  try {
    const detail = await getRagDocument(doc.id)
    selected.value = { ...doc, ...detail }
    chunks.value = await getRagDocumentChunks(doc.id)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载详情失败'
  } finally {
    detailLoading.value = false
  }
}

async function reindex(doc: RagDoc) {
  ask('重建索引', `重新索引「${doc.title}」？将重新分片并重建向量。`, async () => {
    try {
      await reindexRagDocument(doc.id)
      actionMsg.value = '已提交重新索引'
      await loadDocs()
    } catch (e) {
      error.value = e instanceof Error ? e.message : '操作失败'
    }
  }, false)
}

async function toggleEnabled(doc: RagDoc) {
  try {
    const next = await toggleRagDocument(doc.id)
    doc.enabled = next.enabled
    actionMsg.value = next.enabled ? '已开启检索' : '已关闭检索'
  } catch (e) {
    error.value = e instanceof Error ? e.message : '操作失败'
  }
}

async function toggleParent(doc: RagDoc) {
  try {
    const next = await toggleRagParentVisible(doc.id)
    doc.visible_to_parents = next.visible_to_parents
    actionMsg.value = next.visible_to_parents ? '已加入家长政策库' : '已移出家长政策库'
  } catch (e) {
    error.value = e instanceof Error ? e.message : '操作失败'
  }
}

async function removeDoc(doc: RagDoc) {
  ask('删除知识文档', `确定删除「${doc.title}」及其全部向量？此操作不可恢复。`, async () => {
    try {
      await deleteRagDocument(doc.id)
      actionMsg.value = '已删除'
      if (selected.value?.id === doc.id) selected.value = null
      await loadDocs()
    } catch (e) {
      error.value = e instanceof Error ? e.message : '删除失败'
    }
  })
}

async function sweep() {
  ask('清理僵尸向量', '清理僵尸向量（源文档已删除但向量库仍残留）？此操作不可恢复。', async () => {
    try {
      const r = await sweepRagCollections(false)
      actionMsg.value = `清理完成：扫描 ${r.scanned} 分片，删除 ${r.deleted} 片`
      await loadCollections()
    } catch (e) {
      error.value = e instanceof Error ? e.message : '清理失败'
    }
  })
}

async function sync() {
  try {
    const r = await triggerRagSync(50)
    actionMsg.value = `同步完成：扫描 ${r.scanned}，重索引 ${r.reindexed}，源文件缺失 ${r.missing_source}`
  } catch (e) {
    error.value = e instanceof Error ? e.message : '同步失败'
  }
}

function search() {
  page.value = 1
  void loadDocs()
}

function changePage(delta: number) {
  page.value = Math.max(1, Math.min(totalPages.value, page.value + delta))
  void loadDocs()
}

function statusClass(s: string) {
  return s === 'ready' ? 'ok' : s === 'failed' ? 'bad' : 'pending'
}

onMounted(() => {
  void loadDocs()
  void loadBases()
  void loadCollections()
})
</script>

<template>
  <div>
    <PageHead title="知识资产" eyebrow="RAG ASSETS" sub="文档接入、虚拟知识库与向量集合运维">
      <template #actions>
        <button class="btn ghost" @click="sync">增量同步</button>
        <button class="btn" :disabled="loading" @click="loadDocs">{{ loading ? '刷新中…' : '刷新' }}</button>
      </template>
    </PageHead>

    <RagTabs />

    <div class="tabs">
      <button :class="{ on: tab === 'documents' }" @click="tab = 'documents'">文档接入</button>
      <button :class="{ on: tab === 'bases' }" @click="tab = 'bases'">知识库管理</button>
      <button :class="{ on: tab === 'collections' }" @click="tab = 'collections'">向量集合</button>
    </div>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="actionMsg" class="ok">{{ actionMsg }}</p>

    <template v-if="tab === 'documents'">
      <section class="toolbar">
        <input v-model="q" placeholder="搜索标题/描述" @keyup.enter="search" />
        <select v-model="statusFilter" @change="search">
          <option value="">全部状态</option>
          <option value="ready">ready</option>
          <option value="indexing">indexing</option>
          <option value="pending">pending</option>
          <option value="failed">failed</option>
        </select>
        <select v-model="visibility" @change="search">
          <option value="">全部可见性</option>
          <option value="private">private</option>
          <option value="plaza">plaza</option>
        </select>
        <select v-model="enabledFilter" @change="search">
          <option value="">检索开关</option>
          <option value="1">已开启</option>
          <option value="0">已关闭</option>
        </select>
        <button class="btn" @click="search">查询</button>
      </section>

      <section class="panel">
        <table class="table">
          <thead>
            <tr><th>标题</th><th>所有者</th><th>可见性</th><th>状态</th><th>分片</th><th>检索</th><th>家长可见</th><th>更新时间</th><th>操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="d in docs" :key="d.id">
              <td><button class="link-btn" @click="openDoc(d)">{{ d.title }}</button></td>
              <td>{{ d.owner_name || d.owner_id.slice(0, 8) }}</td>
              <td>{{ d.visibility }}</td>
              <td><span class="tag" :class="statusClass(d.status)">{{ d.status }}</span></td>
              <td>{{ d.chunk_count }}</td>
              <td><button class="switch" :class="{ on: d.enabled }" @click="toggleEnabled(d)">{{ d.enabled ? '开' : '关' }}</button></td>
              <td><button class="switch" :class="{ on: d.visible_to_parents }" @click="toggleParent(d)">{{ d.visible_to_parents ? '是' : '否' }}</button></td>
              <td class="mono">{{ d.updated_at?.slice(0, 16).replace('T', ' ') }}</td>
              <td class="ops">
                <button class="mini" @click="reindex(d)">重建</button>
                <button class="mini danger" @click="removeDoc(d)">删除</button>
              </td>
            </tr>
            <tr v-if="!docs.length"><td colspan="9" class="muted">暂无文档</td></tr>
          </tbody>
        </table>
        <div class="pager">
          <span class="muted">共 {{ total }} 条</span>
          <button class="mini" :disabled="page <= 1" @click="changePage(-1)">上一页</button>
          <span>{{ page }} / {{ totalPages }}</span>
          <button class="mini" :disabled="page >= totalPages" @click="changePage(1)">下一页</button>
        </div>
      </section>

      <aside v-if="selected" class="drawer">
        <div class="drawer-head">
          <div>
            <h3>{{ selected.title }}</h3>
            <p class="muted">{{ selected.description || '无描述' }}</p>
          </div>
          <button class="mini" @click="selected = null">关闭</button>
        </div>
        <div class="meta-grid">
          <div><span>状态</span><b>{{ selected.status }}</b></div>
          <div><span>分片</span><b>{{ selected.chunk_count }}</b></div>
          <div><span>文件</span><b class="ellipsis">{{ selected.file_name }}</b></div>
          <div><span>索引哈希</span><b class="mono">{{ selected.indexed_hash || '-' }}</b></div>
        </div>
        <p v-if="selected.error" class="error">{{ selected.error }}</p>
        <p v-if="selected.progress" class="muted">进度：{{ selected.progress.stage }} {{ selected.progress.percent }}% {{ selected.progress.detail }}</p>
        <div class="panel-head"><h3>分片预览</h3><span class="muted">{{ chunks.length }} 块</span></div>
        <div v-if="detailLoading" class="muted">加载中…</div>
        <div v-else class="chunk-list">
          <div v-for="c in chunks" :key="c.id" class="chunk">
            <div class="chunk-head">
              <span class="tag">#{{ c.chunk_no }}</span>
              <span class="muted">{{ c.chars }} 字</span>
              <span v-if="c.has_parent" class="tag ok">父子</span>
            </div>
            <p>{{ c.preview }}</p>
          </div>
          <div v-if="!chunks.length" class="muted">暂无分片（可能尚未索引或 embedding 不可用）</div>
        </div>
      </aside>
    </template>

    <section v-else-if="tab === 'bases'" class="grid bases">
      <div v-for="b in bases" :key="b.key" class="card">
        <div class="card-label">{{ b.name }}</div>
        <div class="card-value">{{ b.documents }} 篇 / {{ b.chunks }} 片</div>
        <p class="muted">{{ b.description }}</p>
        <div class="base-meta">
          <span>ready {{ b.ready }}</span>
          <span>failed {{ b.failed }}</span>
          <span>7d 查询 {{ b.queries_7d }}</span>
          <span>零结果 {{ b.zero_result_rate_7d == null ? '-' : Math.round(b.zero_result_rate_7d * 100) + '%' }}</span>
        </div>
      </div>
    </section>

    <section v-else class="panel">
      <div class="panel-head">
        <h3>向量集合</h3>
        <div class="ops">
          <button class="mini" @click="loadCollections">刷新</button>
          <button class="mini danger" @click="sweep">清理僵尸向量</button>
        </div>
      </div>
      <p v-if="collections" class="muted">当前 active：<span class="mono">{{ collections.active }}</span></p>
      <table class="table">
        <thead><tr><th>集合</th><th>分片数</th><th>状态</th></tr></thead>
        <tbody>
          <tr v-for="c in collections?.collections || []" :key="c.name">
            <td class="mono">{{ c.name }}</td>
            <td>{{ c.count }}</td>
            <td><span class="tag" :class="{ ok: c.active }">{{ c.active ? 'active' : '历史' }}</span></td>
          </tr>
          <tr v-if="!collections?.collections.length"><td colspan="3" class="muted">暂无集合</td></tr>
        </tbody>
      </table>
    </section>
  </div>
  <ConfirmDialog
    :visible="!!pending"
    :title="pending?.title || ''"
    :message="pending?.message || ''"
    :danger="pending?.danger"
    :confirm-text="pending?.danger ? '确认执行' : '继续'"
    @confirm="confirmPending"
    @cancel="pending = null"
  />
</template>

<style scoped>
.btn { padding: 8px 14px; border-radius: 9px; border: 1px solid var(--brand); background: var(--brand); color: #fff; font-weight: 600; cursor: pointer; font-size: 13px; }
.btn.ghost { background: var(--surface); color: var(--brand-strong); border-color: var(--line); }
.tabs { display: flex; gap: 8px; margin-bottom: 14px; }
.tabs button { padding: 8px 16px; border: 1px solid var(--line); background: var(--surface); border-radius: 999px; cursor: pointer; font-weight: 600; color: var(--ink-2); }
.tabs button.on { background: var(--brand); color: #fff; border-color: var(--brand); }
.toolbar { display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
.toolbar input, .toolbar select { padding: 8px 10px; border: 1px solid var(--line); border-radius: 9px; background: var(--surface); color: var(--ink); }
.panel { background: var(--surface); border: 1px solid var(--line); border-radius: 14px; padding: 16px; box-shadow: var(--shadow-sm); }
.panel-head { display: flex; align-items: center; justify-content: space-between; margin: 10px 0; }
.panel-head h3 { font-size: 14px; font-weight: 800; }
.table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.table th, .table td { text-align: left; padding: 8px 6px; border-bottom: 1px solid var(--line); vertical-align: middle; }
.table th { color: var(--ink-3); font-weight: 600; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11.5px; }
.muted { color: var(--ink-3); font-size: 12px; }
.ellipsis { max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: inline-block; }
.ops { display: flex; gap: 6px; }
.mini { padding: 4px 9px; border: 1px solid var(--line); background: var(--surface); border-radius: 7px; cursor: pointer; font-size: 11.5px; color: var(--ink-2); }
.mini.danger { color: #b91c1c; border-color: #fecaca; }
.link-btn { border: none; background: none; color: var(--brand-strong); cursor: pointer; font-weight: 600; padding: 0; text-align: left; }
.switch { padding: 3px 9px; border-radius: 999px; border: 1px solid var(--line); background: #f1f5f9; color: var(--ink-3); cursor: pointer; font-size: 11px; }
.switch.on { background: var(--success-soft); color: #047857; border-color: #a7f3d0; }
.tag { display: inline-block; padding: 2px 8px; border-radius: 999px; background: #f1f5f9; color: var(--ink-3); font-size: 11px; }
.tag.ok { background: var(--success-soft); color: #047857; }
.tag.bad { background: #fef2f2; color: #b91c1c; }
.tag.pending { background: #fffbeb; color: #b45309; }
.pager { display: flex; gap: 10px; align-items: center; justify-content: flex-end; margin-top: 12px; }
.error { color: #b91c1c; background: #fef2f2; padding: 10px 12px; border-radius: 10px; margin-bottom: 12px; }
.ok { color: #047857; background: var(--success-soft); padding: 10px 12px; border-radius: 10px; margin-bottom: 12px; }
.drawer { position: fixed; right: 20px; top: 20px; bottom: 20px; width: min(560px, 46vw); background: var(--surface); border: 1px solid var(--line); border-radius: 16px; box-shadow: var(--shadow-lg); padding: 18px; overflow: auto; z-index: 80; }
.drawer-head { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
.drawer-head h3 { font-size: 17px; font-weight: 800; }
.meta-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 14px 0; }
.meta-grid div { background: #f8fafc; border-radius: 10px; padding: 9px 10px; display: flex; flex-direction: column; gap: 3px; }
.meta-grid span { color: var(--ink-3); font-size: 11.5px; }
.meta-grid b { font-size: 12.5px; }
.chunk-list { display: flex; flex-direction: column; gap: 10px; }
.chunk { border: 1px solid var(--line); border-radius: 10px; padding: 10px; }
.chunk-head { display: flex; gap: 8px; align-items: center; margin-bottom: 6px; }
.chunk p { font-size: 12.5px; line-height: 1.6; color: var(--ink-2); white-space: pre-wrap; }
.grid.bases { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }
.card { background: var(--surface); border: 1px solid var(--line); border-radius: 14px; padding: 16px; box-shadow: var(--shadow-sm); }
.card-label { color: var(--ink-3); font-size: 12px; font-weight: 600; }
.card-value { font-size: 21px; font-weight: 800; margin: 8px 0; }
.base-meta { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 10px; color: var(--ink-3); font-size: 11.5px; }
@media (max-width: 1100px) { .grid.bases { grid-template-columns: 1fr; } .drawer { left: 20px; width: auto; } }
</style>
