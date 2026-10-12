import { defineStore } from 'pinia'
import { ref } from 'vue'

export interface Toast {
  id: number
  kind: 'error' | 'success' | 'info'
  text: string
}

let seq = 1

export const useToastStore = defineStore('toast', () => {
  const toasts = ref<Toast[]>([])

  function push(kind: Toast['kind'], text: string, ttl = 5000) {
    const id = seq++
    toasts.value.push({ id, kind, text })
    if (ttl > 0) {
      setTimeout(() => dismiss(id), ttl)
    }
  }

  function dismiss(id: number) {
    toasts.value = toasts.value.filter((t) => t.id !== id)
  }

  function error(text: string) {
    push('error', text, 8000)
  }

  function success(text: string) {
    push('success', text, 3500)
  }

  function info(text: string) {
    push('info', text, 4000)
  }

  return { toasts, push, dismiss, error, success, info }
})

/** 从 axios 错误中提取后端中文 detail，弹错误 toast；返回提取到的文本 */
export function toastApiError(e: unknown, fallback = '操作失败，请稍后重试'): string {
  // 动态导入避免循环依赖
  const text =
    (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail ??
    fallback
  const msg = typeof text === 'string' ? text : fallback
  try {
    useToastStore().error(msg)
  } catch {
    /* store 未初始化时忽略 */
  }
  return msg
}
