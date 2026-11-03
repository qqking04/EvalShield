import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'

// ES9-P-16：'echarts' 裸导入重定向到按需注册单点模块（regex 精确匹配，
// 不误伤 echarts/core、echarts/charts 等子路径导入）
const echartsOnDemand = fileURLToPath(new URL('./src/utils/echarts.js', import.meta.url))

// EvalShield 前端构建配置：开发代理到后端 127.0.0.1:8000
// EDITION=community 时（默认），构建产物在运行期以 __EDITION__ 触发商业模块的前端降级门控
export default defineConfig({
  resolve: {
    alias: [
      { find: /^echarts$/, replacement: echartsOnDemand },
    ],
  },
  plugins: [react()],
  define: {
    __EDITION__: JSON.stringify(process.env.EDITION || 'community'),
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.js',
    css: false,
    // 本机 jsdom + 全量 antd 页面渲染较慢（ES9 UAT 详情/向导），放宽默认 5s
    testTimeout: 30000,
    // 全量 17 文件并发收集导致 jsdom 时序抖动（Queue.test 偶发 fail），关闭文件级并行
    fileParallelism: false,
    coverage: {
      provider: 'v8',
      // ES8-BUG-008：阈值口径对准本次补齐契约测试的 7 个核心页面组件
      include: [
        'src/pages/review/Queue.jsx',
        'src/pages/Tasks.jsx',
        'src/pages/reports/ReportsList.jsx',
        'src/pages/question-banks/QuestionBanksList.jsx',
        'src/pages/Dashboard.jsx',
        'src/pages/admin/AiConfig.jsx',
        'src/pages/eval/TargetRegistryTab.jsx',
      ],
      reporter: ['text', 'text-summary'],
      thresholds: { lines: 60 },
    },
  },
  server: {
    port: process.env.DEV_PORT ? Number(process.env.DEV_PORT) : 5173,
    proxy: {
      '/api': {
        target: process.env.API_TARGET || 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  preview: {
    port: process.env.PREVIEW_PORT ? Number(process.env.PREVIEW_PORT) : 8173,
    proxy: {
      '/api': {
        target: process.env.API_TARGET || 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    // ES9-P-16：构建日志输出每个 chunk 的 gzip 体积（CI/人工核对入口阈值用）
    reportCompressedSize: true,
    // 关键：把产物目录从默认的 assets/ 改成 static/
    // 原因：Vite 默认产物目录叫 assets/，恰好与 React Router 的 /assets 路由重名
    // nginx 访问 /assets 时会把它当物理目录处理 → 301 加斜杠 + 丢端口 → 403
    // 改名为 static/ 后 nginx 不再把 /assets 当物理目录，try_files 直接回退到 index.html
    assetsDir: 'static',
    chunkSizeWarningLimit: 1500,
    rollupOptions: {
      output: {
        // ES9-P-16：manualChunks 域拆分（vendor 四组，入口 chunk 只留应用代码）
        // 注意：'echarts' 已被上方 alias 重定向到 src/utils/echarts.js，
        // 字符串表按包名匹配不到该源码文件，必须函数式显式归组，
        // 否则按需注册模块会被打进 index chunk，把整个 echarts 库静态拉进首屏。
        manualChunks(id) {
          const p = id.split('\\').join('/')
          if (p.includes('src/utils/echarts.js')) return 'vendor-echarts'
          if (p.includes('node_modules/echarts') || p.includes('node_modules/zrender')) return 'vendor-echarts'
          if (p.includes('node_modules/react-router') || p.includes('node_modules/@remix-run')) return 'vendor-router'
          if (p.includes('node_modules/react') || p.includes('node_modules/react-dom') || p.includes('node_modules/scheduler')) return 'vendor-react'
          // ES11-R-2：vendor-antd 1.61MB 超警告线。只拆「叶子包」
          // （被 antd 依赖但自身不回依赖 antd/rc-*，避免循环 chunk 警告）：
          // icons-svg 是图标 SVG 数据集大头，dayjs 为日期库。
          // rc-*/antd 主体互有依赖，保持同 chunk 不拆。
          if (p.includes('node_modules/@ant-design/icons-svg')) return 'vendor-icons-svg'
          if (p.includes('node_modules/dayjs')) return 'vendor-dayjs'
          if (p.includes('node_modules/antd') || p.includes('node_modules/@ant-design') || p.includes('node_modules/rc-')) return 'vendor-antd'
        },
      },
    },
  },
})