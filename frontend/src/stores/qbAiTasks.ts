import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import {
  getQbAiTask,
  listActiveQbAiTasks,
  startSetTagTask,
  startSetValidateTask,
  type QbAiTask,
} from '@/api/questionBank'
import { useToastStore } from '@/stores/toast'

const POLL_MS = 2000

/**
 * 题库 AI 批量任务（校准 / 打标）的全局状态：
 * - 任务一旦启动，轮询在所有页面持续进行，切换 tab / 路由不丢；
 * - 右下角浮窗（QbAiTasksDock）展示进度；
 * - 重新进入页面时 restore() 恢复运行中的任务。
 */
export const useQbAiTasksStore = defineStore('qbAiTasks', () => {
  const tasks = ref<Record<string, QbAiTask>>({})
  let pollTimer: ReturnType<typeof setInterval> | null = null

  const list = computed(() =>
    Object.values(tasks.value).sort((a, b) => a.created_at.localeCompare(b.created_at)),
  )
  const running = computed(() => list.value.filter((task) => task.status === 'running'))

  function tasksForSet(setId: string) {
    return list.value.filter((task) => task.meta?.set_id === setId)
  }

  function upsert(task: QbAiTask) {
    tasks.value[task.id] = task
  }

  function ensurePolling() {
    if (pollTimer) return
    pollTimer = setInterval(() => {
      void poll()
    }, POLL_MS)
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  async function poll() {
    const active = running.value
    if (!active.length) {
      stopPolling()
      return
    }
    const toast = useToastStore()
    for (const task of active) {
      try {
        const fresh = await getQbAiTask(task.id)
        upsert(fresh)
        if (fresh.status === 'done') {
          const label = fresh.kind === 'tag' ? 'AI 知识点打标' : 'AI 校准'
          const succeeded = fresh.kind === 'tag' ? fresh.result?.tagged : fresh.result?.applied
          const failed = fresh.result?.failed ?? 0
          toast.success(`${label}完成：成功 ${succeeded ?? fresh.total} 题${failed ? `，失败 ${failed} 题` : ''}`)
        } else if (fresh.status === 'error') {
          toast.error(`AI 任务失败：${fresh.error ?? '未知错误'}`)
        }
      } catch {
        // 单次轮询失败不中断
      }
    }
  }

  async function restore() {
    try {
      const active = await listActiveQbAiTasks()
      for (const task of active) upsert(task)
      if (active.length) ensurePolling()
    } catch {
      // 服务不可达时静默
    }
  }

  async function startValidate(setId: string, questionIds: string[]) {
    const res = await startSetValidateTask(setId, { apply: true, question_ids: questionIds })
    try {
      upsert(await getQbAiTask(res.task_id))
    } catch {
      // 已创建，后续轮询会补上
    }
    ensurePolling()
    return res
  }

  async function startTag(setId: string, questionIds: string[]) {
    const res = await startSetTagTask(setId, { question_ids: questionIds })
    try {
      upsert(await getQbAiTask(res.task_id))
    } catch {
      // 已创建，后续轮询会补上
    }
    ensurePolling()
    return res
  }

  function dismiss(taskId: string) {
    delete tasks.value[taskId]
  }

  return { tasks, list, running, tasksForSet, restore, startValidate, startTag, dismiss }
})