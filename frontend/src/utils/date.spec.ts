import { describe, expect, it } from 'vitest'

import {
  addDays,
  addMinutes,
  dayKey,
  fmtCnDate,
  fmtCnDateFromIso,
  fmtCnDateKey,
  fmtCnPeriod,
  fmtHM,
  mondayOf,
  pad2,
  toLocalNaiveIso,
  weekdayName,
} from './date'

describe('date utils', () => {
  it('pad2', () => {
    expect(pad2(5)).toBe('05')
    expect(pad2(12)).toBe('12')
  })

  it('dayKey / toLocalNaiveIso 使用本地时间（不转 UTC，避免跨日偏移）', () => {
    // 用本地构造器创建，任何时区下断言都成立
    const d = new Date(2026, 7, 28, 9, 5, 3)
    expect(dayKey(d)).toBe('2026-08-28')
    expect(toLocalNaiveIso(d)).toBe('2026-08-28T09:05:03')
  })

  it('fmtHM', () => {
    expect(fmtHM(new Date(2026, 0, 1, 7, 30))).toBe('07:30')
  })

  it('mondayOf 返回所在周周一（周日属于当周）', () => {
    // 2026-08-30 是周日，其所在周一是 08-24
    const sunday = new Date(2026, 7, 30, 15, 0)
    const m = mondayOf(sunday)
    expect(dayKey(m)).toBe('2026-08-24')
    expect(m.getHours()).toBe(0)
    // 周一自身不变
    expect(dayKey(mondayOf(new Date(2026, 7, 24, 10, 0)))).toBe('2026-08-24')
  })

  it('addDays / addMinutes', () => {
    const d = new Date(2026, 0, 31, 23, 30)
    expect(dayKey(addDays(d, 1))).toBe('2026-02-01')
    expect(fmtHM(addMinutes(d, 40))).toBe('00:10')
  })

  it('weekdayName', () => {
    expect(weekdayName(1)).toBe('周一')
    expect(weekdayName(7)).toBe('周日')
  })

  it('fmtCnDate / fmtCnDateKey / fmtCnPeriod', () => {
    expect(fmtCnDate(new Date(2026, 7, 28))).toBe('2026年8月28日')
    expect(fmtCnDateKey('2026-8-1')).toBe('2026年8月1日')
    expect(fmtCnDateKey('2026-08-01T05:00:00')).toBe('2026年8月1日')
    expect(fmtCnDateKey(null)).toBe('')
    expect(fmtCnPeriod('2026-08-01', '2026-08-31')).toBe('2026年8月1日 ~ 2026年8月31日')
    expect(fmtCnPeriod('2026-08-01', null)).toBe('2026年8月1日')
    expect(fmtCnPeriod(null, null)).toBe('')
  })

  it('fmtCnDateFromIso 对非法输入返回空串', () => {
    expect(fmtCnDateFromIso(null)).toBe('')
    expect(fmtCnDateFromIso('not-a-date')).toBe('')
    expect(fmtCnDateFromIso('2026-08-28T10:00:00')).toBe('2026年8月28日')
  })
})
