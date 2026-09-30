const fs = require('fs')
const src = fs.readFileSync('src/views/teachers/TeachersView.vue', 'utf8')
const codes = new Map()
for (const ch of src) {
  const c = ch.codePointAt(0)
  // skip common ASCII and CJK ranges
  const isCommon = (c >= 32 && c < 127) || c === 10 || c === 13 || c === 9
  const isCJK = (c >= 0x4e00 && c <= 0x9fff) || (c >= 0x3000 && c <= 0x303f) || (c >= 0xff00 && c <= 0xffef)
  if (!isCommon && !isCJK) {
    codes.set(c, (codes.get(c) || 0) + 1)
  }
}
console.log('unusual codepoints (U+xxxx : count):')
for (const [c, n] of codes) {
  console.log(`U+${c.toString(16).toUpperCase().padStart(4, '0')} : ${n}`)
}
console.log('total unusual:', [...codes.values()].reduce((a, b) => a + b, 0))