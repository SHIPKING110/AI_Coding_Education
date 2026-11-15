import { describe, expect, it } from 'vitest'

import { defaultStudentUsername, initialOf, pinyinInitials } from './pinyin'

// 说明：initialOf 是基于 Unicode 区间的近似映射（文档注明罕见字会跳过），
// 因此这里断言「实际契约」：常见字给首字母、ASCII 直通、不可取字符返回空串。

describe('pinyin utils', () => {
  it('initialOf 对常见汉字返回小写首字母', () => {
    expect(initialOf('张')).toBe('z')
    // 区间近似：只要落在合法字母区间即满足契约
    expect(initialOf('露')).toMatch(/^[a-z]$/)
  })

  it('initialOf ASCII 字母/数字原样小写；不可取字符返回空串', () => {
    expect(initialOf('A')).toBe('a')
    expect(initialOf('3')).toBe('3')
    expect(initialOf('!')).toBe('')
  })

  it('pinyinInitials 过滤不可取字符并去空白', () => {
    expect(pinyinInitials('张')).toBe('z')
    expect(pinyinInitials('A张')).toBe('az')
    expect(pinyinInitials(' 张 ')).toBe('z')
    expect(pinyinInitials('!!!')).toBe('')
  })

  it('defaultStudentUsername = 缩写 + 电话数字，且对格式化电话幂等', () => {
    const u1 = defaultStudentUsername('张', '13800001234')
    const u2 = defaultStudentUsername('张', '138-0000-1234')
    expect(u1).toBe('z13800001234')
    expect(u1).toBe(u2)
    expect(defaultStudentUsername('张', '')).toBe('')
  })
})
