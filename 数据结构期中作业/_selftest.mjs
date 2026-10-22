// 自测：用 mock 的 ctx.skills 验证「发现 SKILL.md + get() 返回正文」契约。
// 运行：node _selftest.mjs
import { createRequire } from 'node:module'
import assert from 'node:assert/strict'

const require = createRequire(import.meta.url)
const plugin = require('./lib/index.js')

let registered = null
const ctx = { skills: { registerProvider: (p) => { registered = p } } }
plugin.apply(ctx)

// 1. provider 已注册且 name 合法
assert.ok(registered, 'provider 应被注册')
assert.equal(typeof registered.name, 'string')
assert.ok(registered.name.length > 0, 'provider.name 必须非空')
assert.ok(/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(registered.name))

// 2. 候选列表：name 合法、provider 字段一致、无重复
const seen = new Set()
assert.ok(registered.candidates.length >= 1, '至少发现一个 SKILL.md')
for (const c of registered.candidates) {
  assert.ok(/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(c.name), `非法候选名: ${c.name}`)
  assert.equal(typeof c.provider, 'string')
  assert.equal(c.provider, registered.name)
  assert.ok(!seen.has(c.name), `重复候选: ${c.name}`)
  seen.add(c.name)
}

// 3. get() 返回正文且包含 frontmatter 与关键章节
const body = registered.get('digital-logic-expert')
assert.ok(body.startsWith('---'), 'SKILL.md 应以 frontmatter 开头')
assert.ok(body.includes('dlengine.py'), '正文应引用确定性引擎')
assert.ok(body.includes('references/'), '正文应引用知识库')

// 4. 未知名称抛错
assert.throws(() => registered.get('no-such-skill'))

console.log(`selftest OK: provider=${registered.name}, skills=[${registered.candidates.map(c => c.name).join(', ')}]`)
