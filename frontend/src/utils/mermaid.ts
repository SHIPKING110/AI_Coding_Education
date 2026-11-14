/**
 * Mermaid 图渲染（本地打包，动态 import 懒加载，不依赖 CDN）。
 * 渲染失败的块保留源码并显示错误原因 + 重试；成功后将 .md-mermaid 标记为 rendered（隐藏源码）。
 * 渲染成功后图占比容器宽度自适应，点击图或「放大」进入灯箱预览（滚轮缩放 / 拖拽平移 / Esc 关闭）。
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

/* ---------- 图表通用样式（全局注入一次，覆盖所有 v-html 渲染容器） ---------- */

let stylesInjected = false

function ensureDiagramStyles(): void {
  if (stylesInjected || typeof document === 'undefined') return
  stylesInjected = true
  const st = document.createElement('style')
  st.id = 'md-diagram-styles'
  st.textContent = `
.md-mermaid-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.md-mermaid-kind { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; font-weight: 700; color: var(--brand-strong, #4f46e5); }
.md-mermaid-ops { display: inline-flex; align-items: center; gap: 6px; }
.md-mm-btn { display: inline-flex; align-items: center; gap: 4px; padding: 2px 8px; border: 1px solid var(--line, #e2e8f0); border-radius: 6px; background: var(--surface, #fff); color: var(--ink-2, #475569); font-size: 11px; line-height: 18px; cursor: pointer; transition: border-color .15s, color .15s, background .15s, box-shadow .15s; }
.md-mm-btn:hover { border-color: var(--brand, #6366f1); color: var(--brand-strong, #4f46e5); background: #f5f6ff; box-shadow: 0 1px 4px rgba(99,102,241,.15); }
.md-mm-btn:active { transform: translateY(.5px); }
.md-mm-btn svg { width: 12px; height: 12px; flex: none; }
.md-mermaid .mermaid-render { overflow-x: auto; border-radius: 8px; }
.md-mermaid.rendered .mermaid-render { cursor: zoom-in; }
.md-mermaid.rendered .mermaid-render svg { display: block; max-width: none !important; width: 100% !important; height: auto !important; }
.md-diagram-lightbox { position: fixed; inset: 0; z-index: 4000; background: rgba(15,23,42,.82); backdrop-filter: blur(6px); display: flex; flex-direction: column; }
.md-diagram-lightbox .dlg-toolbar { position: absolute; top: 16px; right: 18px; display: flex; align-items: center; gap: 8px; z-index: 3; padding: 6px 8px; border-radius: 12px; background: rgba(15,23,42,.55); border: 1px solid rgba(148,163,184,.25); backdrop-filter: blur(8px); }
.md-diagram-lightbox .dlg-title { font-size: 12.5px; color: #cbd5e1; margin-right: 4px; letter-spacing: .3px; }
.md-diagram-lightbox .dlg-pct { font-size: 12px; color: #e2e8f0; min-width: 44px; text-align: center; font-variant-numeric: tabular-nums; }
.md-diagram-lightbox .dlg-btn { min-width: 32px; height: 30px; padding: 0 10px; border: 1px solid rgba(148,163,184,.3); background: rgba(30,41,59,.6); color: #e2e8f0; border-radius: 8px; font-size: 13px; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; transition: background .15s, border-color .15s; }
.md-diagram-lightbox .dlg-btn:hover { background: rgba(99,102,241,.4); border-color: rgba(129,140,248,.7); }
.md-diagram-lightbox .dlg-stage { position: absolute; inset: 0; overflow: hidden; cursor: grab; touch-action: none; }
.md-diagram-lightbox .dlg-stage.grabbing { cursor: grabbing; }
.md-diagram-lightbox .dlg-inner { position: absolute; left: 0; top: 0; transform-origin: 0 0; will-change: transform; }
.md-diagram-lightbox .dlg-inner svg { display: block; }
.md-diagram-lightbox .dlg-hint { position: absolute; bottom: 14px; width: 100%; text-align: center; font-size: 12px; color: rgba(226,232,240,.6); pointer-events: none; }
`.trim()
  document.head.appendChild(st)
}

/* ---------- 灯箱预览（缩放 / 平移） ---------- */

let lbCleanup: (() => void) | null = null

function clampNum(v: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, v))
}

export function closeDiagramPreview(): void {
  document.querySelectorAll('.md-diagram-lightbox').forEach((el) => el.remove())
  if (lbCleanup) {
    lbCleanup()
    lbCleanup = null
  }
}

export function openDiagramPreview(kind: string, svgHtml: string): void {
  if (typeof document === 'undefined') return
  ensureDiagramStyles()
  closeDiagramPreview()
  const prevOverflow = document.body.style.overflow
  document.body.style.overflow = 'hidden'

  const box = document.createElement('div')
  box.className = 'md-diagram-lightbox'
  box.innerHTML =
    `<div class="dlg-toolbar">` +
    `<span class="dlg-title">${escapeHtml(kind || '图表')}</span>` +
    `<button class="dlg-btn" type="button" data-act="out" title="缩小（-）">−</button>` +
    `<span class="dlg-pct">100%</span>` +
    `<button class="dlg-btn" type="button" data-act="in" title="放大（+）">＋</button>` +
    `<button class="dlg-btn" type="button" data-act="fit" title="适应窗口（双击图恢复）">适应</button>` +
    `<button class="dlg-btn" type="button" data-act="close" title="关闭（Esc）">✕</button>` +
    `</div><div class="dlg-stage"><div class="dlg-inner"></div></div>` +
    `<div class="dlg-hint">滚轮缩放 · 拖拽平移 · 双击图适应窗口 · Esc 关闭</div>`

  const stage = box.querySelector<HTMLElement>('.dlg-stage')!
  const inner = box.querySelector<HTMLElement>('.dlg-inner')!
  const pct = box.querySelector<HTMLElement>('.dlg-pct')!

  const wrap = document.createElement('div')
  wrap.innerHTML = svgHtml
  const svg = wrap.querySelector('svg')
  let baseW = 860
  let baseH = 560
  if (svg) {
    const vb = (svg as SVGSVGElement).viewBox?.baseVal
    if (vb && vb.width > 0 && vb.height > 0) {
      baseW = vb.width
      baseH = vb.height
    } else {
      const r = svg.getBoundingClientRect()
      if (r.width > 0 && r.height > 0) {
        baseW = r.width
        baseH = r.height
      }
    }
    svg.setAttribute('width', String(baseW))
    svg.setAttribute('height', String(baseH))
    svg.style.maxWidth = 'none'
    inner.appendChild(svg)
  }

  const state = { scale: 1, x: 0, y: 0 }
  const apply = () => {
    inner.style.transform = `translate(${state.x}px, ${state.y}px) scale(${state.scale})`
    pct.textContent = `${Math.round(state.scale * 100)}%`
  }
  const fit = () => {
    const vw = Math.max(120, stage.clientWidth - 64)
    const vh = Math.max(120, stage.clientHeight - 96)
    state.scale = clampNum(Math.min(vw / baseW, vh / baseH), 0.05, 4)
    state.x = (stage.clientWidth - baseW * state.scale) / 2
    state.y = (stage.clientHeight - baseH * state.scale) / 2
    apply()
  }
  const zoomAt = (cx: number, cy: number, factor: number) => {
    const next = clampNum(state.scale * factor, 0.05, 8)
    const k = next / state.scale
    state.x = cx - (cx - state.x) * k
    state.y = cy - (cy - state.y) * k
    state.scale = next
    apply()
  }

  stage.addEventListener(
    'wheel',
    (e) => {
      e.preventDefault()
      const r = stage.getBoundingClientRect()
      zoomAt(e.clientX - r.left, e.clientY - r.top, Math.exp(-e.deltaY * 0.0015))
    },
    { passive: false },
  )

  let dragging = false
  let moved = false
  let sx = 0
  let sy = 0
  let ox = 0
  let oy = 0
  stage.addEventListener('pointerdown', (e) => {
    dragging = true
    moved = false
    stage.classList.add('grabbing')
    sx = e.clientX
    sy = e.clientY
    ox = state.x
    oy = state.y
    try {
      stage.setPointerCapture(e.pointerId)
    } catch {
      /* 某些环境不支持指针捕获，不影响拖拽 */
    }
  })
  stage.addEventListener('pointermove', (e) => {
    if (!dragging) return
    const dx = e.clientX - sx
    const dy = e.clientY - sy
    if (Math.abs(dx) + Math.abs(dy) > 4) moved = true
    state.x = ox + dx
    state.y = oy + dy
    apply()
  })
  const endDrag = () => {
    dragging = false
    stage.classList.remove('grabbing')
  }
  stage.addEventListener('pointerup', endDrag)
  stage.addEventListener('pointercancel', endDrag)
  stage.addEventListener('click', (e) => {
    if (!moved && e.target === stage) closeDiagramPreview()
  })
  stage.addEventListener('dblclick', (e) => {
    const r = stage.getBoundingClientRect()
    zoomAt(e.clientX - r.left, e.clientY - r.top, 1.6)
  })

  box.addEventListener('click', (e) => {
    const btn = (e.target as HTMLElement | null)?.closest<HTMLElement>('[data-act]')
    if (!btn) return
    const act = btn.dataset.act
    if (act === 'close') closeDiagramPreview()
    else if (act === 'fit') fit()
    else if (act === 'in') zoomAt(stage.clientWidth / 2, stage.clientHeight / 2, 1.25)
    else if (act === 'out') zoomAt(stage.clientWidth / 2, stage.clientHeight / 2, 0.8)
  })

  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'Escape') closeDiagramPreview()
    else if (e.key === '+' || e.key === '=') zoomAt(stage.clientWidth / 2, stage.clientHeight / 2, 1.25)
    else if (e.key === '-') zoomAt(stage.clientWidth / 2, stage.clientHeight / 2, 0.8)
  }
  window.addEventListener('keydown', onKey)

  document.body.appendChild(box)
  lbCleanup = () => {
    window.removeEventListener('keydown', onKey)
    document.body.style.overflow = prevOverflow
  }
  requestAnimationFrame(fit)
}

/* ---------- 渲染 ---------- */

/** 渲染 root 内所有未处理的 .md-mermaid 块（流式输出时可在每次更新后调用，已渲染的会跳过）。 */
export async function renderMermaidNodes(root: ParentNode | null | undefined): Promise<void> {
  if (!root) return
  const boxes = Array.from(root.querySelectorAll<HTMLElement>('.md-mermaid'))
  if (!boxes.length) return
  ensureDiagramStyles()

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

/** 给容器绑定「重试 / 放大预览」点击代理（重复调用安全）。 */
export function bindMermaidRetry(root: HTMLElement | null | undefined): void {
  if (!root || root.dataset.mermaidBound === '1') return
  root.dataset.mermaidBound = '1'
  root.addEventListener('click', (e) => {
    const target = e.target as HTMLElement | null
    if (!target) return
    const btn = target.closest<HTMLElement>('.md-mermaid-retry')
    if (btn) {
      const box = btn.closest<HTMLElement>('.md-mermaid')
      if (!box) return
      box.dataset.mermaidState = ''
      const targetEl = box.querySelector<HTMLElement>('.mermaid-render')
      if (targetEl) targetEl.innerHTML = ''
      void renderMermaidNodes(root)
      return
    }
    // 放大预览：点「放大」按钮或点已渲染的图
    const zoomBtn = target.closest<HTMLElement>('.md-mermaid-zoom')
    const svgClick = target.closest<SVGElement>('.mermaid-render svg')
    const box = zoomBtn?.closest<HTMLElement>('.md-mermaid') || svgClick?.closest<HTMLElement>('.md-mermaid')
    if (!box) return
    const svg = box.querySelector('.mermaid-render svg')
    if (!svg) return
    openDiagramPreview(box.dataset.kind || '图表', svg.outerHTML)
  })
}

const observedRoots = new WeakSet<Element>()

/**
 * 监听容器 DOM 变化并自动渲染（含重试/预览代理绑定）。
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