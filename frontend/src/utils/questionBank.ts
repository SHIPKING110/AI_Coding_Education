/** 题库题目答案在「人工编辑文本」与「后端 JSON 契约」之间转换。 */
export function answerToText(type: string, answer: unknown): string {
  if (type === 'single_choice') return typeof answer === 'number' ? String.fromCharCode(65 + answer) : ''
  if (type === 'multiple_choice') {
    return Array.isArray(answer) ? answer.map((i) => String.fromCharCode(65 + Number(i))).join(',') : ''
  }
  if (type === 'judgement') return answer === true ? '正确' : answer === false ? '错误' : ''
  return typeof answer === 'string' ? answer : ''
}

export function answerFromText(type: string, text: string): unknown {
  const value = text.trim()
  if (type === 'single_choice') {
    const m = value.toUpperCase().match(/[A-H]/)
    return m ? m[0].charCodeAt(0) - 65 : null
  }
  if (type === 'multiple_choice') {
    const letters = [...new Set(value.toUpperCase().match(/[A-H]/g) ?? [])]
    return letters.length ? letters.map((c) => c.charCodeAt(0) - 65).sort((a, b) => a - b) : null
  }
  if (type === 'judgement') {
    if (/(正确|对|√|true)/i.test(value)) return true
    if (/(错误|错|×|false)/i.test(value)) return false
    return null
  }
  return value || null
}

