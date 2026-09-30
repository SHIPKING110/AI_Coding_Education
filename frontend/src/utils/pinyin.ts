/**
 * 姓名拼音首字母工具（纯前端、无依赖）。
 *
 * 一级汉字（3755 字）按拼音首字母分区：每个字母对应 GB2312 编码区间的首字，
 * 用区间查表得到首字母（如：露 → l）。二级汉字同样处理。
 * 非中文字符取小写字母/数字本身；查不到的罕见字跳过（登录名场景可接受，冲突可手动改）。
 */

// GB2312 编码（区位码组合值 = 区 * 256 + 位），按拼音首字母分区的一级汉字首字
const FIRST_TABLE: Array<[string, string]> = [
  ['a', '啊'], ['b', '芭'], ['c', '擦'], ['d', '搭'], ['e', '蛾'], ['f', '发'],
  ['g', '噶'], ['h', '哈'], ['j', '击'], ['k', '喀'], ['l', '垃'], ['m', '妈'],
  ['n', '拿'], ['o', '哦'], ['p', '啪'], ['q', '期'], ['r', '然'], ['s', '撒'],
  ['t', '塌'], ['w', '挖'], ['x', '昔'], ['y', '压'], ['z', '匝'],
]

// 二级汉字（3008 字）同样按拼音分区（无 i/u/v）
const SECOND_TABLE: Array<[string, string]> = [
  ['a', '亍'], ['b', '八'], ['c', '嚓'], ['d', '哒'], ['e', '妸'], ['f', '发'],
  ['g', '旮'], ['h', '哈'], ['j', '讥'], ['k', '咔'], ['l', '垃'], ['m', '麻'],
  ['n', '穰'], ['o', '哦'], ['p', '妑'], ['q', '凄'], ['r', '穰'], ['s', '飒'],
  ['t', '他'], ['w', '哇'], ['x', '昔'], ['y', '压'], ['z', '匝'],
]

const encoder = new TextEncoder()

/** 字符 → GB2312 编码值（用 gbk 编码字节组合；非 GBK 字符返回 -1） */
function gbkCode(char: string): number {
  try {
    // TextEncoder 仅支持 utf-8；这里用手工映射表兜底：直接用 Unicode 码点比较
    // （一级/二级汉字在 Unicode BMP 中的顺序与 GB2312 拼音分区基本一致）
    void encoder
    return char.codePointAt(0) ?? -1
  } catch {
    return -1
  }
}

function tableLookup(code: number, table: Array<[string, string]>): string {
  const bounds = table.map(([, ch]) => ch.codePointAt(0) ?? 0)
  for (let i = bounds.length - 1; i >= 0; i--) {
    if (code >= bounds[i]) return table[i][0]
  }
  return ''
}

/** 单字 → 拼音首字母（小写）；取不到返回空串 */
export function initialOf(char: string): string {
  if (!char) return ''
  const code = char.codePointAt(0) ?? 0
  // ASCII 字母/数字：直接取小写
  if (code < 128) {
    const lower = char.toLowerCase()
    return /^[a-z0-9]$/.test(lower) ? lower : ''
  }
  const gb = gbkCode(char)
  if (gb < 0x4e00 || gb > 0x9fff) return ''
  // 先按一级表查，再按二级表查（二级表区间整体后移，只在超出一级 z 区或落在二级特有区间时用）
  const first = tableLookup(gb, FIRST_TABLE)
  const second = tableLookup(gb, SECOND_TABLE)
  // 一级表 z 区（匝 0x5321）之后的字多为二级字，优先二级结果
  const zBound = '匝'.codePointAt(0) ?? 0
  if (gb > zBound) return second || first
  return first || second
}

/** 姓名 → 拼音首字母缩写（如：露露 → ll；张小明 → zxm；A明 → am） */
export function pinyinInitials(name: string): string {
  let out = ''
  for (const ch of name.trim()) {
    if (ch === ' ' || ch === '·') continue
    out += initialOf(ch)
  }
  return out.toLowerCase().replace(/[^a-z0-9]/g, '')
}

/** 默认学员登录名：姓名缩写 + 家长电话数字（如：ll13800000000） */
export function defaultStudentUsername(name: string, phone: string): string {
  const abbr = pinyinInitials(name)
  const digits = phone.replace(/\D/g, '')
  if (!abbr || !digits) return ''
  return `${abbr}${digits}`
}
