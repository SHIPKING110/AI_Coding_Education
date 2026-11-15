import { describe, expect, it } from 'vitest'

import { apiErrorDetail, apiErrorStatus, errorMessage } from './errors'

describe('errors utils', () => {
  it('apiErrorDetail 提取字符串 detail', () => {
    const e = { response: { data: { detail: '用户名已存在' } } }
    expect(apiErrorDetail(e, '兜底')).toBe('用户名已存在')
  })

  it('apiErrorDetail 对非字符串 detail（校验数组/对象）回退 fallback', () => {
    const arr = { response: { data: { detail: [{ msg: 'bad' }] } } }
    expect(apiErrorDetail(arr, '兜底')).toBe('兜底')
    const obj = { response: { data: { detail: { msg: 'x' } } } }
    expect(apiErrorDetail(obj, '兜底')).toBe('兜底')
  })

  it('apiErrorDetail 对任意异常形态安全回退', () => {
    expect(apiErrorDetail(null, '兜底')).toBe('兜底')
    expect(apiErrorDetail(undefined, '兜底')).toBe('兜底')
    expect(apiErrorDetail('plain string', '兜底')).toBe('兜底')
    expect(apiErrorDetail(new Error('boom'), '兜底')).toBe('兜底')
  })

  it('apiErrorStatus 提取数字状态码，否则 undefined', () => {
    expect(apiErrorStatus({ response: { status: 404 } })).toBe(404)
    expect(apiErrorStatus({ response: { status: 'x' } })).toBeUndefined()
    expect(apiErrorStatus(new Error('boom'))).toBeUndefined()
    expect(apiErrorStatus(null)).toBeUndefined()
  })

  it('errorMessage 优先 Error.message，其次字符串，最后 String 化', () => {
    expect(errorMessage(new Error('超时'))).toBe('超时')
    expect(errorMessage('直接字符串')).toBe('直接字符串')
    expect(errorMessage(123)).toBe('123')
    expect(errorMessage(null)).toBe('null')
  })
})
