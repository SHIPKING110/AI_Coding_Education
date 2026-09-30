/**
 * 把 "['a', 'b']" 这类原始数组形态的字符串还原为「；」分隔的整洁文本。
 *
 * 背景：AI 输出的多条目字段（进步亮点/待提升项/家长建议）偶尔以数组形式返回，
 * 旧版本直接 str() 落库后形如 "['已经能够独立完成…', '课堂学习态度认真…']"。
 * 展示前统一清洗，保证分点语义。
 */
export function cleanListishText(text: unknown): string {
  if (text == null) return ''
  if (Array.isArray(text)) {
    return text.map((v) => String(v).trim()).filter(Boolean).join('；')
  }
  const t = String(text).trim()
  if (!/^\[[\s\S]*\]$/.test(t)) return t
  try {
    const parsed = JSON.parse(t)
    if (Array.isArray(parsed)) {
      return parsed.map((v) => String(v).trim()).filter(Boolean).join('；')
    }
  } catch {
    // 非 JSON（如 Python repr 单引号列表），走正则兜底
  }
  const items = [...t.matchAll(/['"]([^'"]+)['"]/g)]
    .map((m) => m[1].trim())
    .filter(Boolean)
  if (items.length > 0) return items.join('；')
  return t
}
