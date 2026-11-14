/**
 * Mermaid 图渲染（本地打包，动态 import 懒加载，不依赖 CDN）。
 * 渲染失败的块保留源码并显示错误原因 + 重试；成功后将 .md-mermaid 标记为 rendered（隐藏源码）。
 */

let mermaidPromise: Promise<any> | null = null

function loadMermaid(): Promise<any> {
  if (!mermaidPromise) {
    mermaidPromise = import('mermaid').then((m) => {
      const mm = m.default
      mm.initialize({
        startOnLoad: false,
        theme: 'neutral',
        securityLevel: 'strict',
        fontFamily: 'inherit',
      })
      return mm
    })
  }
  return mermaidPromise
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

let seq = 0

/** 渲染 root 内所有未处理的 .md-mermaid 块（流式输出时可在每次更新后调用，已渲染的会跳过）。 */
export async function renderMermaidNodes(root: ParentNode | null | undefined): Promise<void> {
  if (!root) return
  const boxes = Array.from(root.querySelectorAll<HTMLElement>('.md-mermaid'))
  if (!boxes.length) return

  let mm: any = null
  try {
    mm = await loadMermaid()
  } catch {
    /* 加载失败时按块显示错误 */
  }

  for (const box of boxes) {
    const state = box.dataset.mermaidState
    if (state === 'done' || state === 'rendering') continue
    const src = box.querySelector('.mermaid-src')?.textContent || ''
    const target = box.querySelector<HTMLElement>('.mermaid-render')
    if (!target || !src.trim()) continue

    box.dataset.mermaidState = 'rendering'
    const id = `md-mermaid-${++seq}`
    try {
      if (!mm) throw new Error('图表渲染库加载失败')
      const { svg, bindFunctions } = await mm.render(id, src)
      target.innerHTML = svg
      try {
        bindFunctions?.(target)
      } catch {
        /* 节点交互绑定失败不影响渲染 */
      }
      box.classList.add('rendered')
      box.dataset.mermaidState = 'done'
    } catch (e) {
      document.getElementById(id)?.remove()
      box.dataset.mermaidState = 'error'
      target.innerHTML =
        `<div class="md-mermaid-error">` +
        `<span>图表渲染失败：${escapeHtml(e instanceof Error ? e.message : String(e) || '未知错误')}</span>` +
        `<button class="md-mermaid-retry" type="button">重试</button>` +
        `</div>`
    }
  }
}

/** 给容器绑定「重试」点击代理（重复调用安全）。 */
export function bindMermaidRetry(root: HTMLElement | null | undefined): void {
  if (!root || root.dataset.mermaidBound === '1') return
  root.dataset.mermaidBound = '1'
  root.addEventListener('click', (e) => {
    const btn = (e.target as HTMLElement | null)?.closest<HTMLElement>('.md-mermaid-retry')
    if (!btn) return
    const box = btn.closest<HTMLElement>('.md-mermaid')
    if (!box) return
    box.dataset.mermaidState = ''
    const target = box.querySelector<HTMLElement>('.mermaid-render')
    if (target) target.innerHTML = ''
    void renderMermaidNodes(root)
  })
}

const observedRoots = new WeakSet<Element>()

/**
 * 监听容器 DOM 变化并自动渲染（含重试代理绑定）。
 * 覆盖 v-html 整体刷新、历史消息 push、流式追加等所有时序，重复调用安全。
 */
export function observeMermaid(root: ParentNode | null | undefined): void {
  const el = root as Element | null
  if (!el || observedRoots.has(el)) return
  observedRoots.add(el)
  bindMermaidRetry(el as HTMLElement)
  let timer: number | undefined
  const mo = new MutationObserver(() => {
    if (timer) window.clearTimeout(timer)
    timer = window.setTimeout(() => void renderMermaidNodes(el), 250)
  })
  mo.observe(el, { childList: true, subtree: true })
}
