/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import { useMemo } from 'react'
import { Button } from 'antd'
import { LockOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { tokens } from '../theme/tokens'
import { MONO_FONT } from '../theme'

// 商业版升级引导页（方案 §4-F4）：社区版用户访问商业功能时的统一落点。
// 文案原则：陈述限制 + 下一步，不道歉、不煽情。
// 色彩纪律：#165DFF 仅用于主按钮与焦点环；对比表不加彩色底、商业列仅加粗列名。

const PRICING_URL = 'https://github.com/evalshield/evalshield#pricing'

const KIND_COPY = {
  discover: {
    title: 'AI 自动发现',
    desc: '自动遍历目标系统的接口与页面，生成候选测试用例。社区版可手动维护用例，商业版支持批量发起与任务编排。',
    community: ['单条用例手工编写', '任务逐一创建执行'],
    commercial: ['AI 批量发现用例', '发现任务队列与进度追踪'],
  },
  src_audit: {
    title: '源码审计',
    desc: '导入被测系统源码做白盒安全评估。社区版支持黑盒测试，商业版解锁源码级审计与报告。',
    community: ['黑盒用例执行与报告', '标准引擎测评'],
    commercial: ['源码导入与静态审计', '白盒审计报告导出'],
  },
  batch: {
    title: '合规映射与批量任务',
    desc: '将测试结果映射到监管条款并批量生成合规结论。社区版逐条查看结果，商业版支持批量映射与台账导出。',
    community: ['单任务结果查看', '基础报告导出'],
    commercial: ['合规条款批量映射', 'License 台账与批量导出'],
  },
  report_compare: {
    title: '报告对比',
    desc: '将多份测试报告并排对比分数与用例差异。社区版查看单份报告，商业版支持多报告对比。',
    community: ['单份报告完整查看', '历史趋势留存'],
    commercial: ['多报告并排对比', '差异高亮与导出'],
  },
  cost: {
    title: '成本看板',
    desc: '统计模型调用的 token 消耗与费用。社区版不采集成本数据，商业版提供多维成本看板。',
    community: ['执行记录逐条查看', '基础用量统计'],
    commercial: ['按模型/项目成本归集', '费用趋势与预算提醒'],
  },
  model_compare: {
    title: '模型横评',
    desc: '同一测评集在多个模型上并行跑分对比。社区版单模型测评，商业版支持多模型横向对比。',
    community: ['单模型任务执行', '单项报告输出'],
    commercial: ['多模型同集并跑', '横评矩阵与排名'],
  },
  billing: {
    title: '账单管理',
    desc: '查看订阅账单与用量明细。社区版自部署无计费，商业订阅版提供账单与发票管理。',
    community: ['本地部署自由使用', '核心测试能力全量可用'],
    commercial: ['订阅账单与用量明细', '多空间统一计费视图'],
  },
  defects: {
    title: '缺陷跟踪',
    desc: '将失败用例沉淀为缺陷单并流转状态。社区版查看失败结果，商业版支持缺陷生命周期管理。',
    community: ['失败用例即时查看', '执行日志留存'],
    commercial: ['缺陷单创建与流转', '缺陷与用例双向关联'],
  },
  recordings: {
    title: '执行录屏',
    desc: '回放 UI 测试执行过程的屏幕录制。社区版保留截图结果，商业版提供全程录屏归档回放。',
    community: ['步骤截图与结果留存', '执行日志查看'],
    commercial: ['全程视频录制', '关键节点定位回放'],
  },
  regulations: {
    title: '法规库',
    desc: '内置监管法规条文供用例关联引用。社区版支持自定义条款，商业版提供预置法规库更新。',
    community: ['手工维护测试标准', '用例自由标注'],
    commercial: ['预置法规全文检索', '条文版本化更新订阅'],
  },
  orgs: {
    title: '组织管理',
    desc: '多级组织与跨空间成员治理。社区版单空间协作，商业版支持组织树与统一成员目录。',
    community: ['单空间成员邀请', '角色权限分配'],
    commercial: ['多级组织树管理', '跨空间成员与配额治理'],
  },
  security_assets: {
    title: '安全样本库',
    desc: '维护越狱攻击样本与 PII 检测规则资产。社区版可运行内置样本，商业版支持样本库自定义管理。',
    community: ['内置样本执行测评', '安全结果报告'],
    commercial: ['越狱样本库增删改', 'PII 规则自定义维护'],
  },
  license_ledger: {
    title: 'License 台账',
    desc: '查看企业授权明细与席位用量。社区版无需 License，商业部署提供台账与到期提醒。',
    community: ['社区条款自由使用', '开源版本全量核心能力'],
    commercial: ['授权席位台账', '到期提醒与续期记录'],
  },
}

const FALLBACK_COPY = {
  title: '商业版功能',
  desc: '该功能属于商业版能力，社区版不包含。可查看商业版差异后返回继续使用现有功能。',
  community: ['社区版核心测试能力可用', '数据本地留存'],
  commercial: ['解锁该商业功能', '批量处理与高级报告'],
}

// 淡入动画：prefers-reduced-motion 时禁用（无 motion 类则保持静态）
const FADE_CSS = `
@keyframes es-upgrade-fade { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
.es-upgrade-enter { animation: es-upgrade-fade 240ms ease-out both; }
@media (prefers-reduced-motion: reduce) { .es-upgrade-enter { animation: none; } }
.es-upgrade-primary:focus-visible { outline: 1px solid #165DFF; outline-offset: 2px; }
`

export default function UpgradeEmpty({ kind, onBack }) {
  const navigate = useNavigate()
  const copy = KIND_COPY[kind] || FALLBACK_COPY

  const handleBack = () => {
    if (onBack) onBack()
    else if (window.history.length > 1) navigate(-1)
    else navigate('/')
  }

  const panelStyle = useMemo(() => ({
    maxWidth: 640,
    margin: '64px auto',
    padding: '32px 36px 28px',
    background: tokens.bgPanel,
    border: `1px solid ${tokens.border}`,
    borderRadius: 6,
  }), [])

  return (
    <section
      className="es-upgrade-enter"
      aria-labelledby="es-upgrade-title"
      style={panelStyle}
    >
      <style>{FADE_CSS}</style>

      {/* 等宽小标签：明示当前版本形态 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
        <LockOutlined style={{ color: tokens.text3, fontSize: 13 }} aria-hidden="true" />
        <span
          style={{
            fontFamily: MONO_FONT,
            fontSize: 11,
            letterSpacing: '0.12em',
            color: tokens.text3,
            border: `1px solid ${tokens.border}`,
            borderRadius: 2,
            padding: '2px 8px',
          }}
        >
          EDITION · COMMUNITY
        </span>
      </div>

      <h2 id="es-upgrade-title" style={{ margin: '0 0 8px', fontSize: 20, fontWeight: 600, color: tokens.text1 }}>
        {copy.title}
      </h2>
      <p style={{ margin: '0 0 24px', fontSize: 13, lineHeight: 1.7, color: tokens.text2 }}>
        {copy.desc}
      </p>

      {/* 2 列价值对比表：不加彩色底，商业列仅列名加粗 */}
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13, marginBottom: 28 }}>
        <caption className="ant-sr-only" style={{ position: 'absolute', width: 1, height: 1, overflow: 'hidden', clip: 'rect(0,0,0,0)' }}>
          社区版与商业版能力对比
        </caption>
        <thead>
          <tr>
            <th scope="col" style={{ textAlign: 'left', fontWeight: 400, color: tokens.text3, padding: '0 12px 10px 0', borderBottom: `1px solid ${tokens.border}`, width: 96 }}>
              能力
            </th>
            <th scope="col" style={{ textAlign: 'left', fontWeight: 400, color: tokens.text3, padding: '0 12px 10px 0', borderBottom: `1px solid ${tokens.border}` }}>
              社区版（当前）
            </th>
            <th scope="col" style={{ textAlign: 'left', fontWeight: 700, color: tokens.text1, padding: '0 0 10px 0', borderBottom: `1px solid ${tokens.border}` }}>
              商业版
            </th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td style={{ padding: '12px 12px 12px 0', color: tokens.text3, verticalAlign: 'top' }}>包含</td>
            <td style={{ padding: '12px 12px 12px 0', color: tokens.text2, verticalAlign: 'top' }}>
              <ul style={{ margin: 0, paddingLeft: 18, listStyleType: 'none' }}>
                {copy.community.map((t) => <li key={t} style={{ marginBottom: 4 }}>{t}</li>)}
              </ul>
            </td>
            <td style={{ padding: '12px 0', color: tokens.text2, verticalAlign: 'top' }}>
              <ul style={{ margin: 0, paddingLeft: 18, listStyleType: 'none' }}>
                {copy.commercial.map((t) => <li key={t} style={{ marginBottom: 4 }}>{t}</li>)}
              </ul>
            </td>
          </tr>
        </tbody>
      </table>

      <div style={{ display: 'flex', gap: 12 }}>
        <Button
          type="primary"
          className="es-upgrade-primary"
          href={PRICING_URL}
          target="_blank"
          rel="noopener noreferrer"
          style={{ backgroundColor: '#165DFF', borderColor: '#165DFF', color: '#fff' }}
        >
          查看商业版
        </Button>
        <Button onClick={handleBack}>返回</Button>
      </div>
    </section>
  )
}
