import { Linter } from 'eslint'
import { readFileSync } from 'node:fs'
const configModule = await import('./eslint.config.js')
const baseConfig = configModule.default
const linter = new Linter()
const file = process.argv[2]
const code = readFileSync(file, 'utf8')
const cfg = baseConfig.map(c => (c && c.rules) ? {...c, rules: {...c.rules, complexity: ['error', 0]}} : c)
const messages = linter.verify(code, cfg, { filename: file })
const lines = code.split('\n')
for (const m of messages) if (m.ruleId === 'complexity' && +m.message.match(/complexity of (\d+)/)[1] > 5) {
  const fn = lines.slice(m.line-1, m.line+1).join(' ')
  console.log(`${m.line}:${m.column}  ${m.message}  ||  ${fn.slice(0,80)}`)
}
