const fs = require('fs')
const path = require('path')
const ts = require('typescript')
const { resolveVueCompilerOptions, createVueLanguagePlugin } = require('@vue/language-core')

const targets = [
  'src/views/teachers/TeachersView.vue',
  'src/views/students/StudentsView.vue',
  'src/views/classes/ClassesView.vue',
]
const vueCompilerOptions = resolveVueCompilerOptions({})
vueCompilerOptions.plugins = []
const languagePlugin = createVueLanguagePlugin(ts, {}, vueCompilerOptions, (f) => f)

for (const rel of targets) {
  const filePath = path.resolve(rel)
  const src = fs.readFileSync(filePath, 'utf8')
  const snapshot = { getText: (s, e) => src.slice(s, e), getLength: () => src.length, getChangeRange: () => undefined }
  const virtual = languagePlugin.createVirtualCode(filePath, 'vue', snapshot)
  let found = null
  const walk = (node) => {
    const arr = node.embeddedCodes
    const sub = typeof arr === 'function' ? arr() : arr
    if (sub) {
      for (const ec of sub) {
        if (/^script/.test(ec.id)) {
          const snap = ec.snapshot
          const len = snap && snap.getLength ? snap.getLength() : undefined
          if (len !== undefined) {
            found = snap.getText(0, len)
            return
          }
        }
        walk(ec)
      }
    }
  }
  walk(virtual)
  const fname = 'script_' + path.basename(rel).replace('.vue', '')
  if (found) {
    fs.writeFileSync(fname + '.ts', found)
    const lines = found.split('\n')
    // print the scriptSetup boundary line
    const debugLine = lines.findIndex((l) => l.includes('PartiallyEnd'))
    console.log('###', rel, 'lines', lines.length, 'partiallyEnd at', debugLine + 1)
    if (debugLine >= 0) {
      console.log('   before:', JSON.stringify(lines.slice(Math.max(0, debugLine - 3), debugLine)))
      console.log('   boundary:', JSON.stringify(lines[debugLine]))
    }
  } else {
    console.log('###', rel, 'NO script virtual')
  }
}