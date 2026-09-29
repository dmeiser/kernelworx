import { Linter } from 'eslint'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
const configModule = await import('./eslint.config.js')
const baseConfig = configModule.default
const linter = new Linter()
const file = process.argv[2]
const code = readFileSync(file, 'utf8')
const cfg = baseConfig.map(c => (c && c.rules) ? {...c, rules: {...c.rules, complexity: ['error', 0]}} : c)
const messages = linter.verify(code, cfg, { filename: file })
for (const m of messages) if (m.ruleId === 'complexity') console.log(m.line+':'+m.column+'  '+m.message)
