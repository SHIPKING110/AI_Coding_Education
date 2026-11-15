import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { toastApiError, useToastStore } from './toast'

describe('toast store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.useFakeTimers()
  })

  it('push 增加 toast，ttl 到期自动移除', () => {
    const store = useToastStore()
    store.push('info', 'hi', 1000)
    expect(store.toasts).toHaveLength(1)
    vi.advanceTimersByTime(1001)
    expect(store.toasts).toHaveLength(0)
  })

  it('error/success/info 快捷方法', () => {
    const store = useToastStore()
    store.error('e')
    store.success('s')
    store.info('i')
    expect(store.toasts.map((t) => t.kind)).toEqual(['error', 'success', 'info'])
  })

  it('dismiss 按 id 移除', () => {
    const store = useToastStore()
    store.push('info', 'a', 0)
    store.push('info', 'b', 0)
    const id = store.toasts[0].id
    store.dismiss(id)
    expect(store.toasts.map((t) => t.text)).toEqual(['b'])
  })

  it('toastApiError 提取后端 detail 并弹 error', () => {
    const store = useToastStore()
    const e = { response: { data: { detail: '用户名已存在' } } }
    const text = toastApiError(e, '兜底')
    expect(text).toBe('用户名已存在')
    expect(store.toasts[0]).toMatchObject({ kind: 'error', text: '用户名已存在' })
    vi.useRealTimers()
  })
})
