/** 文案编辑框高度自适应（autogrow-edit）
 *
 * v-autogrow：textarea 内容高度自适应，输入/回填/窗口变化时按 scrollHeight
 * 自动撑高，超过上限后内部滚动，避免长文案被压成小框或溢出。
 */
import type { Directive } from 'vue'

const MAX_HEIGHT = 340
const MIN_HEIGHT = 64

function fit(el: HTMLTextAreaElement) {
  el.style.overflowY = 'hidden'
  el.style.height = 'auto'
  const h = Math.max(MIN_HEIGHT, Math.min(el.scrollHeight, MAX_HEIGHT))
  el.style.height = `${h}px`
  el.style.overflowY = el.scrollHeight > MAX_HEIGHT ? 'auto' : 'hidden'
}

function onInput(e: Event) {
  fit(e.target as HTMLTextAreaElement)
}

export const autogrow: Directive<HTMLTextAreaElement> = {
  mounted(el) {
    el.classList.add('autogrow-ta')
    requestAnimationFrame(() => fit(el))
    el.addEventListener('input', onInput)
    // v-model 程序回填（AI 回填/撤销修改/载入编辑）不触发 input，用 updated + ResizeObserver 兜底
    const ro = new ResizeObserver(() => fit(el))
    ro.observe(el)
    ;(el as unknown as { __autogrowRo?: ResizeObserver }).__autogrowRo = ro
  },
  updated(el) {
    requestAnimationFrame(() => fit(el))
  },
  unmounted(el) {
    el.removeEventListener('input', onInput)
    ;(el as unknown as { __autogrowRo?: ResizeObserver }).__autogrowRo?.disconnect()
  },
}

export default autogrow
