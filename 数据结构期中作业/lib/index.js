'use strict'

/**
 * dsh-digital-logic-expert —— dsh (DeepSeek Harness) Cordis 插件入口。
 *
 * 职责单一：递归发现 skills/ 目录下的所有 SKILL.md，并通过
 * ctx.skills.registerProvider 注册为 Skill Provider。
 * 与 skill2dsh 生成的插件（如 dsh-chinese-traditional-wisdom-skill）保持同一契约：
 *   - provider.name 为非空字符串
 *   - candidates 列表中每项 name 满足 /^[a-z0-9]+(?:-[a-z0-9]+)*$/
 *   - 每项 candidate.provider === provider.name
 *   - get(name) 返回对应 SKILL.md 的正文（含 frontmatter）
 */

const fs = require('fs')
const path = require('path')

const PROVIDER_NAME = 'digital-logic-expert'
const NAME_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/

function* walk(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) yield* walk(full)
    else if (entry.isFile() && entry.name === 'SKILL.md') yield full
  }
}

function discoverSkills(root) {
  const candidates = []
  const bodies = new Map()
  for (const file of walk(root)) {
    const body = fs.readFileSync(file, 'utf8')
    // 从 frontmatter 读取 name；缺失时退化为目录名
    let name = path.basename(path.dirname(file))
    const m = body.match(/^---\r?\n([\s\S]*?)\r?\n---/)
    if (m) {
      const nm = m[1].match(/^name:\s*(\S+)\s*$/m)
      if (nm) name = nm[1].trim()
    }
    if (!NAME_RE.test(name)) continue
    candidates.push({ name, provider: PROVIDER_NAME, path: file })
    bodies.set(name, body)
  }
  return { candidates, bodies }
}

const skillsRoot = path.join(__dirname, '..', 'skills')
const { candidates, bodies } = discoverSkills(skillsRoot)

const provider = {
  name: PROVIDER_NAME,
  description: '数字逻辑全流程智能助教：知识点问答 + 电路分析/设计/调优/验证闭环',
  candidates,
  get(name) {
    if (!bodies.has(name)) throw new Error(`skill not found: ${name}`)
    return bodies.get(name)
  },
}

// Cordis 插件契约：导出 apply(ctx)
function apply(ctx) {
  ctx.skills.registerProvider(provider)
}

module.exports = { name: PROVIDER_NAME, apply, provider }
