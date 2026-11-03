#!/usr/bin/env node
/**
 * strip_fe.js —— 社区版（OSS）前端剥离脚本
 *
 * 用法：node scripts/strip_fe.js <目标前端目录>
 *   目标目录 = 一份 frontend 导出副本（含 src/），脚本就地修改，不碰仓库源目录。
 *
 * 行为（与《版本隔离与商业模块改造方案详细开发方案》§4 F-build 对应）：
 *   1. 物理删除 <target>/src/pages/commercial/ 整目录（商业页面 + 其测试文件）；
 *   2. 把 src/ 下所有指向 pages/commercial/ 的 import/lazy 说明符
 *      改写为指向 src/pages/CommercialPlaceholder.jsx 的同路径引用。
 *
 * 为什么"改写说明符"而不是"删掉引用行"：
 *   App.jsx / Reports.jsx / ReportDetail.jsx 中被 import 绑定的标识符
 *   （AIDiscover、ComplianceTab、SecurityReportView 等）在 JSX 路由/Tab 中仍被使用，
 *   删行会导致构建期 ReferenceError 或运行期白屏。改写后：
 *     - 商业 chunk 不再进入构建图 → 社区包物理不含商业代码（隔离目标达成）；
 *     - 路由结构保留 → 用户点击入口渲染 CommercialPlaceholder → UpgradeEmpty 升级引导页（体验闭环）；
 *     - 若改写遗漏，vite build 会因找不到 ./commercial/X 直接报错 —— 混包变构建期硬错误。
 *
 * 纯 Node 内置模块（fs/path），无第三方依赖。package.json 为 "type": "module"，故用 ESM 语法。
 */
import fs from 'node:fs'
import path from 'node:path'

// ---------- 参数校验 ----------
const target = process.argv[2]
if (!target) {
  console.error('用法: node scripts/strip_fe.js <目标前端目录>')
  process.exit(1)
}
const srcDir = path.join(target, 'src')
if (!fs.existsSync(srcDir) || !fs.statSync(srcDir).isDirectory()) {
  console.error(`目标目录下未找到 src/: ${srcDir}`)
  process.exit(1)
}
const commercialDir = path.join(srcDir, 'pages', 'commercial')
// 优化15 D1：边界外商业页目录（saas-only 平台运营页，带商业 SPDX 头）——与 pages/commercial/ 同口径整目录剔除
const EXTRA_COMMERCIAL_DIRS = [path.join(srcDir, 'pages', 'platform')]
const placeholderAbs = path.join(srcDir, 'pages', 'CommercialPlaceholder') // 无扩展名
if (!fs.existsSync(placeholderAbs + '.jsx')) {
  console.error(`缺少占位组件: ${placeholderAbs}.jsx`)
  process.exit(1)
}

// ---------- 1. 统计并删除 pages/commercial/ ----------
function countFiles(dir) {
  let n = 0
  if (!fs.existsSync(dir)) return 0
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name)
    if (e.isDirectory()) n += countFiles(p)
    else n += 1
  }
  return n
}
const removed = countFiles(commercialDir)
if (removed > 0) {
  fs.rmSync(commercialDir, { recursive: true, force: true })
  console.log(`删除商业页面目录 src/pages/commercial/（${removed} 个文件）`)
} else {
  console.log('目标目录已不含 src/pages/commercial/，跳过删除')
}
for (const dir of EXTRA_COMMERCIAL_DIRS) {
  const n = countFiles(dir)
  if (n > 0) {
    fs.rmSync(dir, { recursive: true, force: true })
    console.log(`删除商业页面目录 ${path.relative(target, dir)}（${n} 个文件）`)
  }
}

// ---------- 2. 改写 import 说明符 ----------
// 匹配形如 './pages/commercial/AIDiscover'、'./commercial/ComplianceTab'、'../commercial/SecurityReportView'
const SPEC_RE = /(["'])((?:\.{1,2}\/)*(?:[^"']*\/)?)commercial\/([A-Za-z0-9_]+)\1/g
// platform 说明符须带相对前缀（./ 或 ../），防误伤 '/api/platform/...' 等接口路径字符串
const PLATFORM_SPEC_RE = /(["'])((?:\.{1,2}\/)+(?:[^"']*\/)?)platform\/([A-Za-z0-9_]+)\1/g

let rewritten = 0
let touchedFiles = 0

function walkFiles(dir, out) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name)
    if (e.isDirectory()) walkFiles(p, out)
    else if (/\.jsx?$/.test(e.name)) out.push(p)
  }
}

const files = []
walkFiles(srcDir, files)

for (const file of files) {
  const before = fs.readFileSync(file, 'utf8')
  if (!/commercial\/|pages\/platform\/|\.\.?\/platform\//.test(before)) continue
  const fileDir = path.dirname(file)
  let rel = path.relative(fileDir, placeholderAbs).split(path.sep).join('/')
  if (!rel.startsWith('.')) rel = './' + rel
  const after = before
    .replace(SPEC_RE, (_m, quote) => quote + rel + quote)
    .replace(PLATFORM_SPEC_RE, (_m, quote) => quote + rel + quote)
  if (after !== before) {
    const n = (before.match(SPEC_RE) || []).length + (before.match(PLATFORM_SPEC_RE) || []).length
    rewritten += n
    touchedFiles += 1
    fs.writeFileSync(file, after)
    console.log(`  改写 ${n} 处: ${path.relative(target, file)}`)
  }
}

// ---------- 3. 商业引擎编码静态映射清除（BUG-5 / 用例 F6 字面判据） ----------
// 私有树保留这些映射（enterprise 历史报告回渲染需要）；OSS 树必须 0 命中：
//   grep -Rn "JAILBREAK" frontend/src（PII_LEAK 为同类商业引擎，一并清除）
const ENGINE_CLEAN = [
  {
    file: path.join(srcDir, 'constants', 'enums.js'),
    pairs: [
      ["  // P0：越狱 / PII 泄露检测引擎\n  JAILBREAK: '越狱检测',\n  PII_LEAK: 'PII 泄露检测',\n", ""],
    ],
  },
  {
    file: path.join(srcDir, 'components', 'tasks', 'engineParams.js'),
    pairs: [
      ["  JAILBREAK: null,\n  PII_LEAK: null,\n", ""],
      [
        `  // P0：越狱检测 / PII 泄露检测（LOCAL fallback，后端 params_schema 优先）
  JAILBREAK: [
    { key: 'target_code', label: '被测系统', type: 'target', required: true },
    { key: 'judge_model', label: '判定模型', type: 'model_config', usage: 'CHAT' },
    { key: 'threshold', label: '通过阈值(0-1)', type: 'number', min: 0, max: 1, default: 0.9 },
    { key: 'max_samples', label: '最大样本数', type: 'number', min: 1, max: 500, default: 100 },
    { key: 'category', label: '攻击类别(可选)', type: 'select', options: ['ROLEPLAY', 'ENCODING', 'CONTEXT_POISON', 'CLASSIC_EN'] },
  ],
  PII_LEAK: [
    { key: 'target_code', label: '被测系统', type: 'target', required: true },
    { key: 'judge_model', label: '判定模型', type: 'model_config', usage: 'CHAT' },
    { key: 'threshold', label: '通过阈值(0-1)', type: 'number', min: 0, max: 1, default: 0.9 },
    { key: 'probe_inputs', label: '探针输入(JSON数组,可选)', type: 'textarea' },
    { key: 'enable_llm_scan', label: '启用 LLM 语义识别', type: 'boolean', default: true },
  ],
`,
        "",
      ],
    ],
  },
  {
    file: path.join(srcDir, 'pages', 'eval', 'reportRenderers.jsx'),
    pairs: [
      ["// U8-2 拆分：JailbreakReport/EthicsReport/PIILeakReport 与各渲染器共用工具迁至 ./renderers/，", "// U8-2 拆分：EthicsReport 与各渲染器共用工具迁至 ./renderers/，"],
      ["import { JailbreakReport } from './renderers/jailbreak'\n", ""],
      ["import { PIILeakReport } from './renderers/pii'\n", ""],
      ["export { RunBanner, GenericItemTable, JailbreakReport, EthicsReport, PIILeakReport }", "export { RunBanner, GenericItemTable, EthicsReport }"],
      ["  JAILBREAK: JailbreakReport,\n  PII_LEAK: PIILeakReport,\n", ""],
    ],
  },
  {
    file: path.join(srcDir, 'pages', 'reports', 'ReportDetail.jsx'),
    pairs: [
      ["  JailbreakReport, PIILeakReport,\n", ""],
      ["  JAILBREAK: JailbreakReport,\n  PII_LEAK: PIILeakReport,\n", ""],
    ],
  },
  {
    // es11 漂移（优化15 D1）：注释提及 JAILBREAK → 中性化改写
    file: path.join(srcDir, 'pages', 'es11', 'RunWorkspace.jsx'),
    pairs: [
      ["（后端仅对 JAILBREAK/REDTEAM_TEST 组装 redteam 数据）", "（后端仅对红队类引擎组装 redteam 数据）"],
    ],
  },
  {
    // es11 漂移（优化15 D1）：测试夹具 JAILBREAK → HALLUCINATION_TEST（社区枚举内引擎码，组件按 code 直显，断言同步）
    file: path.join(srcDir, 'pages', 'es11', 'DimensionBenchmark.test.jsx'),
    pairs: [
      ["{ code: 'JAILBREAK', state: 'N/A' },", "{ code: 'HALLUCINATION_TEST', state: 'N/A' },"],
      ["expect(screen.getByText(/JAILBREAK N\\/A/)).toBeInTheDocument()", "expect(screen.getByText(/HALLUCINATION_TEST N\\/A/)).toBeInTheDocument()"],
      ["expect(screen.getByText(/JAILBREAK N\\/A/).querySelector('.anticon-minus')).toBeTruthy()", "expect(screen.getByText(/HALLUCINATION_TEST N\\/A/).querySelector('.anticon-minus')).toBeTruthy()"],
    ],
  },
]

let engineCleaned = 0
for (const { file, pairs } of ENGINE_CLEAN) {
  if (!fs.existsSync(file)) continue
  const raw = fs.readFileSync(file, 'utf8')
  // 行尾归一：模式串按 LF 书写，CRLF 文件先转换后回写保持原格式
  const crlf = raw.includes('\r\n')
  let text = crlf ? raw.replace(/\r\n/g, '\n') : raw
  for (const [oldStr, newStr] of pairs) {
    if (!text.includes(oldStr)) {
      console.error(`FAIL(BUG-5): ${path.relative(target, file)} 未找到待删片段 "${oldStr.slice(0, 40)}..."（源文件已变动，请同步更新 strip_fe.js）`)
      process.exit(1)
    }
    text = text.replace(oldStr, newStr)
    engineCleaned += 1
  }
  fs.writeFileSync(file, crlf ? text.replace(/\n/g, '\r\n') : text)
  console.log(`  BUG-5 清除映射: ${path.relative(target, file)}`)
}

// 级联：删除仅被上述映射引用的商业渲染器文件
for (const dead of [
  path.join(srcDir, 'pages', 'eval', 'renderers', 'jailbreak.jsx'),
  path.join(srcDir, 'pages', 'eval', 'renderers', 'pii.jsx'),
]) {
  if (fs.existsSync(dead)) {
    fs.rmSync(dead)
    console.log(`  BUG-5 删除级联文件: ${path.relative(target, dead)}`)
  }
}

// 终判据：全 src 0 命中（F6 字面要求）
const leftoverHits = []
for (const file of files) {
  if (!fs.existsSync(file)) continue
  const text = fs.readFileSync(file, 'utf8')
  if (/JAILBREAK|PII_LEAK/.test(text)) leftoverHits.push(path.relative(target, file))
}
if (leftoverHits.length > 0) {
  console.error(`FAIL(BUG-5): 剥离后仍残留商业引擎编码: ${leftoverHits.join(', ')}`)
  process.exit(1)
}
console.log(`BUG-5 清除完成：${engineCleaned} 处映射删除，JAILBREAK/PII_LEAK 全 src 0 命中。`)

console.log(`strip 完成：共改写 import 说明符 ${rewritten} 处（涉及 ${touchedFiles} 个文件）。`)
if (rewritten === 0) {
  console.warn('警告：未发现任何指向 pages/commercial/ 的引用，请确认目标目录是否正确。')
}
