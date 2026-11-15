/** 从 axios 风格错误中提取后端 detail 文本；非字符串（对象/校验数组等）回退 fallback。 */
export function apiErrorDetail(e: unknown, fallback: string): string {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  return typeof detail === 'string' ? detail : fallback
}

/** 从 axios 风格错误中提取 HTTP 状态码（无则 undefined）。 */
export function apiErrorStatus(e: unknown): number | undefined {
  const status = (e as { response?: { status?: unknown } })?.response?.status
  return typeof status === 'number' ? status : undefined
}

/** 从任意异常对象中提取可展示文本（Error.message 优先，否则 String 化）。 */
export function errorMessage(e: unknown): string {
  if (e instanceof Error && e.message) return e.message
  return typeof e === 'string' ? e : String(e)
}
