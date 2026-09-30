const fs = require('fs')
const path = require('path')
const ts = require('typescript')
const { resolveVueCompilerOptions, createVueLanguagePlugin } = require('@vue/language-core')

const filePath = path.resolve('src/views/teachers/TeachersView.vue')
const src = fs.readFileSync(filePath, 'utf8')
const snapshot = {
  getText: (s, e) => src.slice(s, e),
  getLength: () => src.length,
  getChangeRange: () => undefined,
}
const vueCompilerOptions = resolveVueCompilerOptions({})
vueCompilerOptions.plugins = []
const languagePlugin = createVueLanguagePlugin(ts, {}, vueCompilerOptions, (f) => f)
const virtual = languagePlugin.createVirtualCode(filePath, 'vue', snapshot)

let written = false
const walk = (node, depth) => {
  const arr = node.embeddedCodes
  const sub = typeof arr === 'function' ? arr() : arr
  if (sub) {
    for (const ec of sub) {
      const snap = ec.snapshot
      const hasSnap = !!snap
      if (hasSnap && /script/.test(ec.id)) {
        const len = typeof snap.getLength === 'function' ? snap.getLength() : undefined
        const text = len !== undefined ? snap.getText(0, len) : undefined
        if (text !== undefined && !written) {
          fs.writeFileSync(path.resolve('_virt.ts'), text)
          console.log('WROTE script virtual:', ec.id, 'len', text.length, 'depth', depth)
          written = true
        }
      }
      walk(ec, depth + 1)
    }
  }
}
walk(virtual, 0)
if (!written) console.log('no script virtual found')