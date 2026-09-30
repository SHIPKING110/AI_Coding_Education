import { defineStore } from 'pinia'

import { getAiTask as getAssignmentAiTask, listAiTasks as listAssignmentAiTasks, type AiTaskOut as AssignmentAiTaskOut } from '@/api/assignment'
import { cancelEvaluationAiTask, getEvaluationAiTask, listEvaluationAiTasks, type EvaluationAiDraftOut } from '@/api/evaluation'
import { cancelAiTask as cancelAssignmentAiTask } from '@/api/assignment'

type TaskKind = 'assignment' | 'evaluation'
export type UnifiedAiTask = (AssignmentAiTaskOut | EvaluationAiDraftOut) & { taskKind: TaskKind }

/** 任务是否在途（pending/running）：在途才轮询，其余终态直接收敛 */
export function isTaskActive(t: Pick<UnifiedAiTask, 'status'>): boolean {
  return t.status === 'pending' || t.status === 'running'
}

/** 任务是否已终态（done/failed/cancelled）：终态不再轮询 */
export function isTaskTerminal(t: Pick<UnifiedAiTask, 'status'>): boolean {
  return t.status === 'done' || t.status === 'failed' || t.status === 'cancelled'
}

export const useAiTasksStore = defineStore('ai-tasks', {
  state: () => ({
    tasks: [] as UnifiedAiTask[],
    bootstrapped: false,
    timer: null as number | null,
    latestDone: null as UnifiedAiTask | null,
  }),
  getters: {
    runningCount: (state) =>
      state.tasks.filter((t) => t.status === 'pending' || t.status === 'running').length,
    runningTasks: (state) => state.tasks.filter((t) => t.status === 'pending' || t.status === 'running'),
    /** 按任务来源分流：习题任务（assignments API） */
    assignmentRunningCount: (state) =>
      state.tasks.filter(
        (t) => t.taskKind === 'assignment' && (t.status === 'pending' || t.status === 'running'),
      ).length,
    /** 按任务来源分流：评估/班级 PPT 任务（evaluations API） */
    evaluationRunningCount: (state) =>
      state.tasks.filter(
        (t) => t.taskKind === 'evaluation' && (t.status === 'pending' || t.status === 'running'),
      ).length,
  },
  actions: {
    register(task: AssignmentAiTaskOut | EvaluationAiDraftOut, taskKind: TaskKind = 'assignment') {
      const unified = { ...task, taskKind } as UnifiedAiTask
      const i = this.tasks.findIndex((t) => t.id === unified.id)
      if (i >= 0) this.tasks[i] = unified
      else this.tasks.unshift(unified)
      this.ensurePolling()
    },
    async bootstrap() {
      if (this.bootstrapped) {
        this.ensurePolling()
        return
      }
      this.bootstrapped = true
      try {
        const [assignments, evaluations] = await Promise.all([
          listAssignmentAiTasks(20),
          listEvaluationAiTasks(20),
        ])
        this.tasks = [
          ...assignments.map((t) => ({ ...t, taskKind: 'assignment' as const })),
          ...evaluations.map((t) => ({ ...t, taskKind: 'evaluation' as const })),
        ].sort((a, b) => b.created_at.localeCompare(a.created_at))
        this.ensurePolling()
      } catch {
        // 忽略
      }
    },
    ensurePolling() {
      if (this.timer !== null) return
      if (this.runningCount === 0) return
      this.timer = window.setInterval(() => {
        void this.pollOnce()
      }, 1500)
    },
    async pollOnce() {
      const running = this.runningTasks
      if (running.length === 0) {
        this.stopPolling()
        return
      }
      const fresh = await Promise.all(
        running.map((t) => {
          const fetcher = t.taskKind === 'assignment' ? getAssignmentAiTask : getEvaluationAiTask
          // 后端重启会丢内存任务（404）：按“记录丢失”收敛为失败，避免无限转圈（异常自恢复）
          return fetcher(t.id).catch((e: unknown) => {
            const status = (e as { response?: { status?: number } })?.response?.status
            if (status === 404) {
              return {
                ...t,
                status: 'failed',
                stage: '生成失败',
                error: '任务记录已丢失（服务可能已重启），请重新提交',
                finished_at: new Date().toISOString(),
              } as unknown as AssignmentAiTaskOut & EvaluationAiDraftOut
            }
            return null
          })
        }),
      )
      let anyRunning = false
      for (let i = 0; i < fresh.length; i += 1) {
        const t = fresh[i]
        const prev = running[i]
        if (!t) continue
        this.register(t as AssignmentAiTaskOut | EvaluationAiDraftOut, prev.taskKind)
        if (t.status === 'pending' || t.status === 'running') anyRunning = true
        else if (t.status === 'done') this.latestDone = { ...(t as any), taskKind: prev.taskKind }
      }
      if (!anyRunning) this.stopPolling()
    },
    /** 取消任务（task-cancel-recover）：排队中直接取消，生成中标记后收敛；本地先行收敛避免闪烁 */
    async cancel(taskId: string) {
      const target = this.tasks.find((t) => t.id === taskId)
      if (!target || isTaskTerminal(target)) return
      const canceller = target.taskKind === 'assignment' ? cancelAssignmentAiTask : cancelEvaluationAiTask
      try {
        const cancelled = await canceller(taskId)
        this.register(cancelled as AssignmentAiTaskOut & EvaluationAiDraftOut, target.taskKind)
      } catch {
        // 取消接口失败（如 404 记录丢失）：本地同样收敛为已取消，不阻塞用户重试
        this.register(
          { ...target, status: 'cancelled', stage: '任务已取消', finished_at: new Date().toISOString() } as UnifiedAiTask,
          target.taskKind,
        )
      }
    },
    stopPolling() {
      if (this.timer !== null) {
        window.clearInterval(this.timer)
        this.timer = null
      }
    },
    dismissDone() {
      this.latestDone = null
    },
    clear() {
      this.stopPolling()
      this.tasks = []
      this.bootstrapped = false
      this.latestDone = null
    },
  },
})
