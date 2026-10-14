/**
 * 安全 Markdown 渲染器（无外部依赖，先转义防 XSS），覆盖 Agent 通用输出格式：
 * 文本层：标题/加粗斜体/行内码/代码块(+复制)/引用/折叠块/分隔线/任务列表/脚注/LaTeX占位
 * 结构层：GFM表格/JSON.YAML折叠块/键值对/树形(mermaid mindmap透传)/标签徽章
 * 流程层：mermaid 围栏透传为可渲染占位（flowchart/sequence/state/mindmap/gantt）
 * 可视化：chart 围栏 → 简易条形图；progress 围栏 → 进度条；timeline 围栏 → 时间轴
 * 状态层：alert 围栏(diff/warn/error/success)/日志终端块；其余未知围栏按代码块展示
 */
export function renderMarkdown(input: string): string {
  if (!input) return ''
  const escapeHtml = (s: string) =>
    s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

  const inline = (s: string): string => {
    let t = escapeHtml(s)
    // 徽章 :badge[已完成] 标签 :tag[xxx]
    t = t.replace(/:badge\[([^\]]+)\]/g, '<span class="md-badge">$1</span>')
    t = t.replace(/:tag\[([^\]]+)\]/g, '<span class="md-tag">$1</span>')
    // 脚注引用 [^1]
    t = t.replace(/\[\^(\d+)\]/g, '<sup class="md-fnref">$1</sup>')
    t = t.replace(/`([^`]+)`/g, '<code>$1</code>')
    t = t.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    t = t.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
    // LaTeX 行内 \(...\) 与块外 $$..$$ 由 CSS 等宽展示（不引入 KaTeX，保持零依赖）
    t = t.replace(/\\\((.+?)\\\)/g, '<span class="md-math">$1</span>')
    t = t.replace(/\$\$(.+?)\$\$/g, '<div class="md-math block">$1</div>')
    t = t.replace(
      /\[([^\]]+)\]\(((?:https?:\/\/|\/)[^)\s]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener">$1</a>',
    )
    return t
  }

  const splitRow = (line: string): string[] => {
    let t = line.trim()
    if (t.startsWith('|')) t = t.slice(1)
    if (t.endsWith('|')) t = t.slice(0, -1)
    return t.split('|').map((c) => c.trim())
  }
  const isDelimRow = (line: string): boolean => {
    const cells = splitRow(line)
    return cells.length > 0 && cells.every((c) => /^:?-{1,}:?$/.test(c))
  }
  const isTableHeader = (line: string, next: string | undefined): boolean =>
    line.trim().startsWith('|') && next !== undefined && isDelimRow(next)

  // 特殊围栏渲染
  const fenceBlock = (lang: string, code: string): string => {
    const l = (lang || '').toLowerCase()
    const esc = escapeHtml(code)
    if (['mermaid', 'mmd'].includes(l)) {
      const kind = /gantt/.test(code) ? '甘特图' : /sequenceDiagram/.test(code) ? '时序图'
        : /stateDiagram/.test(code) ? '状态机图' : /mindmap/.test(code) ? '思维导图'
        : /graph|flowchart/.test(code) ? '流程图' : '关系图'
      return `<div class="md-mermaid" data-kind="${kind}"><div class="md-mermaid-head">◈ ${kind}（文本预览，可复制源码到 Mermaid Live 查看）</div><pre>${esc}</pre></div>`
    }
    if (l === 'chart') {
      try {
        const data = JSON.parse(code) as { labels?: string[]; values?: number[] }
        const labels = (data.labels ?? []).slice(0, 12)
        const values = (data.values ?? []).slice(0, 12).map(Number)
        const max = Math.max(1, ...values)
        const bars = labels.map((lb, i) => {
          const v = values[i] ?? 0
          const pct = Math.round((v / max) * 100)
          return `<div class="md-chart-row"><span class="md-chart-lb">${escapeHtml(lb)}</span><span class="md-chart-track"><span class="md-chart-fill" style="width:${pct}%"></span></span><b>${v}</b></div>`
        }).join('')
        return `<div class="md-chart">${bars || '<span class="empty">chart 需要 {"labels":[],"values":[]}</span>'}</div>`
      } catch {
        return `<pre class="md-code"><code>${esc}</code></pre>`
      }
    }
    if (l === 'progress') {
      const pct = Math.max(0, Math.min(100, parseInt(code.trim(), 10) || 0))
      return `<div class="md-progress"><div class="md-progress-track"><div class="md-progress-fill" style="width:${pct}%"></div></div><span>${pct}%</span></div>`
    }
    if (l === 'timeline') {
      const items = code.split('\n').map((s) => s.trim()).filter(Boolean)
        .map((s) => `<div class="md-tl-item"><span class="md-tl-dot"></span><span>${inline(s)}</span></div>`).join('')
      return `<div class="md-timeline">${items}</div>`
    }
    if (['alert', 'warn', 'warning', 'error', 'success', 'info'].includes(l)) {
      const cls = l === 'alert' ? 'info' : l.replace('warning', 'warn')
      return `<div class="md-alert ${cls}">${inline(code)}</div>`
    }
    if (l === 'details' || l === 'fold') {
      const [title, ...rest] = code.split('\n')
      return `<details class="md-fold"><summary>${escapeHtml(title || '展开查看')}</summary><div>${inline(rest.join('\n'))}</div></details>`
    }
    if (l === 'kv') {
      const rows = code.split('\n').map((s) => s.trim()).filter(Boolean)
        .map((s) => {
          const idx = s.indexOf(':')
          if (idx < 0) return `<div class="md-kv-row"><span>${inline(s)}</span></div>`
          return `<div class="md-kv-row"><b>${inline(s.slice(0, idx).trim())}</b><span>${inline(s.slice(idx + 1).trim())}</span></div>`
        }).join('')
      return `<div class="md-kv">${rows}</div>`
    }
    if (l === 'tree') {
      return `<pre class="md-tree">${esc}</pre>`
    }
    if (['json', 'yaml', 'yml', 'diff'].includes(l)) {
      const id = `c${Math.random().toString(36).slice(2, 8)}`
      const title = l === 'diff' ? '变更对比' : l.toUpperCase()
      return `<details class="md-fold code-fold" open><summary>${title} · 点击折叠 <button class="md-copy" data-copy="${id}">复制</button></summary><pre class="md-code ${l}" id="${id}"><code>${esc}</code></pre></details>`
    }
    if (['terminal', 'log', 'bash', 'console', 'shell'].includes(l)) {
      return `<pre class="md-terminal">${esc}</pre>`
    }
    return `<pre class="md-code"><code data-lang="${escapeHtml(lang)}">${esc}</code></pre>`
  }

  const lines = input.replace(/\r\n/g, '\n').split('\n')
  const out: string[] = []
  const footnotes: string[] = []
  let listType: 'ul' | 'ol' | null = null
  const closeList = () => {
    if (listType) {
      out.push(`</${listType}>`)
      listType = null
    }
  }
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    if (isTableHeader(line, lines[i + 1])) {
      closeList()
      const head = splitRow(line)
      const n = head.length
      let html = `<table class="md-table"><thead><tr>${head.map((c) => `<th>${inline(c)}</th>`).join('')}</tr></thead><tbody>`
      i += 2
      while (i < lines.length && lines[i].trim().startsWith('|') && !isDelimRow(lines[i])) {
        const cells = splitRow(lines[i])
        while (cells.length < n) cells.push('')
        html += `<tr>${cells.slice(0, n).map((c) => `<td>${inline(c)}</td>`).join('')}</tr>`
        i++
      }
      html += '</tbody></table>'
      out.push(html)
      continue
    }
    const fence = line.match(/^```(\w*)\s*$/)
    if (fence) {
      closeList()
      const lang = fence[1]
      i++
      const code: string[] = []
      while (i < lines.length && !/^```\s*$/.test(lines[i])) {
        code.push(lines[i])
        i++
      }
      i++
      out.push(fenceBlock(lang, code.join('\n')))
      continue
    }
    // 折叠块 :::details 标题 ... :::
    const foldStart = line.match(/^:::\s*details\s*(.*)$/)
    if (foldStart) {
      closeList()
      i++
      const body: string[] = []
      while (i < lines.length && !/^:::\s*$/.test(lines[i])) {
        body.push(lines[i])
        i++
      }
      i++
      out.push(`<details class="md-fold"><summary>${inline(foldStart[1] || '展开查看')}</summary><div>${body.map((b) => `<p>${inline(b)}</p>`).join('')}</div></details>`)
      continue
    }
    const fn = line.match(/^\[\^(\d+)\]:\s*(.*)$/)
    if (fn) {
      footnotes.push(`<li>[${fn[1]}] ${inline(fn[2])}</li>`)
      i++
      continue
    }
    if (/^---+\s*$/.test(line) || /^\*\*\*+\s*$/.test(line)) {
      closeList()
      out.push('<hr class="md-hr" />')
      i++
      continue
    }
    const h = line.match(/^(#{1,6})\s+(.*)$/)
    if (h) {
      closeList()
      const lvl = h[1].length
      out.push(`<h${lvl}>${inline(h[2])}</h${lvl}>`)
      i++
      continue
    }
    if (/^>\s?/.test(line)) {
      closeList()
      const buf: string[] = []
      while (i < lines.length && /^>\s?/.test(lines[i])) {
        buf.push(lines[i].replace(/^>\s?/, ''))
        i++
      }
      out.push(`<blockquote>${buf.map((b) => inline(b)).join('<br/>')}</blockquote>`)
      continue
    }
    // 任务列表 - [ ] / - [x]
    const task = line.match(/^\s*[-*+]\s+\[([ xX])\]\s+(.*)$/)
    if (task) {
      if (listType !== 'ul') {
        closeList()
        out.push('<ul class="md-tasks">')
        listType = 'ul'
      }
      const checked = task[1].toLowerCase() === 'x' ? 'checked' : ''
      out.push(`<li><input type="checkbox" disabled ${checked} />${inline(task[2])}</li>`)
      i++
      continue
    }
    const ul = line.match(/^\s*[-*+]\s+(.*)$/)
    if (ul) {
      if (listType !== 'ul') {
        closeList()
        out.push('<ul>')
        listType = 'ul'
      }
      out.push(`<li>${inline(ul[1])}</li>`)
      i++
      continue
    }
    const ol = line.match(/^\s*\d+[.)]\s+(.*)$/)
    if (ol) {
      if (listType !== 'ol') {
        closeList()
        out.push('<ol>')
        listType = 'ol'
      }
      out.push(`<li>${inline(ol[1])}</li>`)
      i++
      continue
    }
    if (/^\s*$/.test(line)) {
      closeList()
      i++
      continue
    }
    closeList()
    out.push(`<p>${inline(line)}</p>`)
    i++
  }
  closeList()
  if (footnotes.length) {
    out.push(`<ol class="md-footnotes">${footnotes.join('')}</ol>`)
  }
  return out.join('')
}
