/**
 * 极简、安全（先转义再渲染）的 Markdown 渲染器，覆盖 AI 对话常用语法：
 * 标题 / 加粗 / 斜体 / 行内代码 / 代码块 / 表格 / 有序·无序列表 / 引用 / 链接。
 * 不引入外部依赖，输出前对 HTML 做转义，避免 XSS。
 */
export function renderMarkdown(input: string): string {
  if (!input) return ''
  const escapeHtml = (s: string) =>
    s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

  const inline = (s: string): string => {
    let t = escapeHtml(s)
    t = t.replace(/`([^`]+)`/g, '<code>$1</code>')
    t = t.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    t = t.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
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

  const lines = input.replace(/\r\n/g, '\n').split('\n')
  const out: string[] = []
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
    // GFM 表格：表头行 + 分隔行 + 数据行
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
      out.push(
        `<pre class="md-code"><code data-lang="${escapeHtml(lang)}">${escapeHtml(
          code.join('\n'),
        )}</code></pre>`,
      )
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
      out.push(`<blockquote>${inline(line.replace(/^>\s?/, ''))}</blockquote>`)
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
  return out.join('')
}
