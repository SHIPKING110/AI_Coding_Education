/**
 * 本地时间工具。
 *
 * 背景：排课时间是"北京标准时间"业务语义。前端必须全程使用本地时间，
 * 发送时传【无时区后缀的本地 naive 字符串】，避免 toISOString() 转 UTC
 * 导致日期/星期偏移（例如 08-28 09:00 本地 → UTC 08-28 01:00，跨日后日期错位）。
 */

export function pad2(n: number): string {
  return String(n).padStart(2, '0')
}

/** Date -> 本地 `YYYY-MM-DD` */
export function dayKey(d: Date): string {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`
}

/** Date -> 本地 naive `YYYY-MM-DDTHH:mm:ss`（不带 Z，服务器按本地时区解释） */
export function toLocalNaiveIso(d: Date): string {
  return `${dayKey(d)}T${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`
}

/**
 * 解析后端返回的时间字符串（可能带时区偏移，如 `2026-08-28T09:00:00+08:00`）
 * 为本地 Date。
 */
export function parseServerTime(iso: string): Date {
  return new Date(iso)
}

/** Date -> 本地 `HH:mm` */
export function fmtHM(d: Date): string {
  return `${pad2(d.getHours())}:${pad2(d.getMinutes())}`
}

/** 后端时间串 -> 本地 `HH:mm` */
export function fmtHMFromIso(iso: string): string {
  return fmtHM(parseServerTime(iso))
}

/** 后端时间串 -> 本地 `M月D日 HH:mm` */
export function fmtDateTimeFromIso(iso: string): string {
  const d = parseServerTime(iso)
  return `${d.getMonth() + 1}月${d.getDate()}日 ${fmtHM(d)}`
}

/** 后端时间串 -> 本地日期 `YYYY-MM-DD`（避免对偏移串直接 slice） */
export function dayKeyFromIso(iso: string): string {
  return dayKey(parseServerTime(iso))
}

/** 今天（本地） */
export function today(): Date {
  return new Date()
}

/** 所在周的周一（本地） */
export function mondayOf(d: Date): Date {
  const r = new Date(d)
  const diff = (r.getDay() + 6) % 7 // 周一=0
  r.setDate(r.getDate() - diff)
  r.setHours(0, 0, 0, 0)
  return r
}

export function addDays(d: Date, n: number): Date {
  const r = new Date(d)
  r.setDate(r.getDate() + n)
  return r
}

export function addMinutes(d: Date, n: number): Date {
  return new Date(d.getTime() + n * 60000)
}

/** 中文星期名，1=周一 ... 7=周日 */
export function weekdayName(weekday: number): string {
  return `周${['一', '二', '三', '四', '五', '六', '日'][weekday - 1]}`
}

/** Date -> 本地 `yyyy年M月d日`（中文日期，页面展示用，比 yyyy/MM/dd 更美观） */
export function fmtCnDate(d: Date): string {
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日`
}

/** 后端时间串 / 日期串 -> `yyyy年M月d日`（兼容带时间的 ISO 串） */
export function fmtCnDateFromIso(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = parseServerTime(iso)
  if (Number.isNaN(d.getTime())) return ''
  return fmtCnDate(d)
}

/** `yyyy-M-d` / ISO 日期串 -> `yyyy年M月d日`（纯日期字符串，不按时间解析避免时区偏移） */
export function fmtCnDateKey(key: string | null | undefined): string {
  if (!key) return ''
  const m = /^(\d{4})-(\d{1,2})-(\d{1,2})/.exec(String(key))
  if (!m) return String(key)
  return `${Number(m[1])}年${Number(m[2])}月${Number(m[3])}日`
}

/** `yyyy-M-d` 起止 -> `yyyy年M月d日 ~ yyyy年M月d日` */
export function fmtCnPeriod(start: string | null | undefined, end: string | null | undefined): string {
  if (!start && !end) return ''
  if (start && !end) return fmtCnDateKey(start)
  if (!start && end) return fmtCnDateKey(end)
  return `${fmtCnDateKey(start)} ~ ${fmtCnDateKey(end)}`
}
