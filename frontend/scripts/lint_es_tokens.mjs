/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司. All rights reserved.
 * SPDX-License-Identifier: BUSL-1.1
 * ES 令牌执法扫描（优化12 §10.2 v2.2 / §11.4-3，方案 §10 T7）：
 *   裸 hex（/(#[0-9a-fA-F]{3,8})\b/）只允许出现在唯一令牌源 gate.jsx。
 * 范围口径（V8"对新增/变更文件零命中"）：
 *   - 新增文件（git 未跟踪 / 状态 A）：全文扫描；
 *   - 变更文件（M）：仅扫 `git diff HEAD -U0` 的新增行——存量裸 hex 属 M7"只立界不改存量"面；
 *   - 豁免：gate.jsx（令牌定义处）与注释行（//、*、/*、{/* *\/），以及行尾 `es-token-allow` 标记。
 * 零依赖：仅 Node 内置 + git。命中 → stdout 文件:行号清单，退出码 1。
 * 用法：node scripts/lint_es_tokens.mjs [--changed]（默认即 --changed；--all 全量扫 src/；
 *       --base <ref> 扫 ref...HEAD 提交区间新增行——CI 面增量口径，V8）
 */
import { execFileSync } from 'node:child_process'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const FRONTEND_ROOT = join(fileURLToPath(import.meta.url), '..', '..') // frontend/
const SRC = 'src'
const HEX_RE = /(#[0-9a-fA-F]{3,8})\b/
const WHITELIST = ['pages/es11/gate.jsx'] // 相对 src/（正斜杠口径），唯一令牌源
const EXTS = ['.js', '.jsx']

const isWhitelisted = (file) => {
  const rel = relative(SRC, file).replace(/\\/g, '/')
  return WHITELIST.some((w) => rel === w || rel.endsWith('/' + w))
}

const git = (args) =>
  execFileSync('git', args, {
    cwd: FRONTEND_ROOT, encoding: 'utf8', maxBuffer: 32 * 1024 * 1024,
    stdio: ['ignore', 'pipe', 'ignore'], // 屏蔽 CRLF 提示等 stderr 噪音（真错误在异常 message 里）
  })

function collectTargets() {
  const baseIdx = process.argv.indexOf('--base')
  const base = baseIdx >= 0 ? process.argv[baseIdx + 1] : null
  const mode = process.argv.includes('--all') ? 'all' : (base ? 'base' : 'changed')
  const targets = [] // { file: 相对 frontend 的路径, addedLines: null=全文 | Set<number> }
  if (mode === 'all') {
    const walk = (dir) => {
      for (const name of readdirSync(join(FRONTEND_ROOT, dir))) {
        const p = join(dir, name)
        const st = statSync(join(FRONTEND_ROOT, p))
        if (st.isDirectory()) walk(p)
        else if (EXTS.some((e) => p.endsWith(e))) targets.push({ file: p, addedLines: null })
      }
    }
    walk(SRC)
    return { mode, targets }
  }
  if (mode === 'base') {
    // CI 面：工作树干净，git status 无增量可扫；改扫 base...HEAD 提交区间
    //（A 全扫 / M 只扫新增行），口径与 --changed 一致（V8"新增/变更零命中"）。
    let out
    try { out = git(['diff', '--name-status', `${base}...HEAD`, '--', SRC]) }
    catch { console.error(`lint:tokens 无法执行 git diff ${base}...HEAD（确认 base ref 可达，CI 需 fetch-depth: 0 或显式 fetch base）`); process.exit(2) }
    for (const ln of out.split('\n').filter(Boolean)) {
      const [xy, ...rest] = ln.split('\t')
      const path = rest.join('\t').replace(/^frontend\//, '')
      if (!EXTS.some((e) => path.endsWith(e)) || xy === 'D') continue
      if (xy === 'A') targets.push({ file: path, addedLines: null })
      else {
        const added = diffAddedLines(path, `${base}...HEAD`)
        if (added !== null) targets.push({ file: path, addedLines: added })
      }
    }
    return { mode, targets, base }
  }
  // porcelain：' M'/'M ' 变更，'??'/' A' 新增；输出路径相对仓库根，剥掉 frontend/ 前缀
  const status = git(['status', '--porcelain', '--', SRC])
    .split('\n')
    .filter(Boolean)
    .map((l) => ({
      xy: l.slice(0, 2).trim(),
      path: l.slice(3).trim().replace(/^"|"$/g, '').replace(/^frontend\//, ''),
    }))
  for (const { xy, path } of status) {
    if (!EXTS.some((e) => path.endsWith(e))) continue
    if (xy === '??' || xy === 'A') {
      targets.push({ file: path, addedLines: null }) // 新增文件全扫
    } else if (/M|D|C|U/.test(xy) && xy !== 'D') {
      const added = diffAddedLines(path)
      if (added !== null) targets.push({ file: path, addedLines: added }) // 变更文件只扫新增行
    }
  }
  return { mode, targets }
}

/** 解析 `git diff <range|HEAD> -U0 -- path` 的 hunk 头，返回新增行号集合（工作树口径）。 */
function diffAddedLines(path, range = 'HEAD') {
  let out
  try { out = git(['diff', range, '-U0', '--', path]) } catch { return null }
  if (!out.trim()) return new Set() // 仅 mode/type 变化等
  const lines = new Set()
  for (const m of out.matchAll(/^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@/gm)) {
    const start = Number(m[1])
    const count = m[2] === undefined ? 1 : Number(m[2])
    for (let i = 0; i < count; i++) lines.add(start + i)
  }
  return lines
}

const isCommentLine = (line) => {
  const t = line.trim()
  return (
    t.startsWith('//') || t.startsWith('*') || t.startsWith('/*') ||
    t.startsWith('*/') || t.startsWith('{/*') || t.includes('es-token-allow')
  )
}

function scan() {
  const { mode, targets, base } = collectTargets()
  const violations = []
  for (const { file, addedLines } of targets) {
    if (isWhitelisted(file)) continue
    let text
    try { text = readFileSync(join(FRONTEND_ROOT, file), 'utf8') } catch { continue } // 已删除/重命名
    const lines = text.split(/\r?\n/)
    lines.forEach((line, idx) => {
      const no = idx + 1
      if (addedLines !== null && !addedLines.has(no)) return
      if (!HEX_RE.test(line) || isCommentLine(line)) return
      violations.push(`${file}:${no}: ${line.trim().slice(0, 100)}`)
    })
  }
  const scope = mode === 'all' ? '全量 src/'
    : mode === 'base' ? `提交区间 ${base}...HEAD ${targets.length} 文件`
    : `git 变更面 ${targets.length} 文件`
  if (violations.length) {
    console.error(`lint:tokens FAIL（${scope}）裸 hex ${violations.length} 处（令牌源请用 import { ES } from '.../es11/gate'）：`)
    for (const v of violations) console.error('  ' + v)
    process.exit(1)
  }
  console.log(`lint:tokens OK（${scope}）：裸 hex 零命中`)
}

scan()
