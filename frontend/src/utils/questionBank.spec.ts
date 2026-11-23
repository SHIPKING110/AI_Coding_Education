import { describe, expect, it } from 'vitest'

import { answerFromText, answerToText } from './questionBank'

describe('questionBank answer conversion', () => {
  it('converts single choice index and letter', () => {
    expect(answerToText('single_choice', 1)).toBe('B')
    expect(answerFromText('single_choice', 'C')).toBe(2)
    expect(answerFromText('single_choice', '')).toBeNull()
  })

  it('converts multiple choice index list and letters', () => {
    expect(answerToText('multiple_choice', [2, 0, 2])).toBe('C,A,C')
    expect(answerFromText('multiple_choice', 'b, a, b')).toEqual([0, 1])
    expect(answerFromText('multiple_choice', '')).toBeNull()
  })

  it('converts judgement values', () => {
    expect(answerToText('judgement', true)).toBe('正确')
    expect(answerToText('judgement', false)).toBe('错误')
    expect(answerFromText('judgement', '√')).toBe(true)
    expect(answerFromText('judgement', '错误')).toBe(false)
  })

  it('keeps programming and fill answers as text', () => {
    expect(answerToText('programming', 'print(1)')).toBe('print(1)')
    expect(answerFromText('programming', 'print(1)')).toBe('print(1)')
    expect(answerFromText('code_fill', '  ')).toBeNull()
  })
})

