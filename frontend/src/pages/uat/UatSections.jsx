/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import React from 'react'

/* ES9 UAT 八节只读渲染（§3.2 payload 字段级对应；标题与后端 uat_render 一致）。
 * Detail 预览与免登录 SignView 共用，纯展示、无交互。 */

export const SECTION_TITLES = {
  s1: '§1 项目概况',
  s2: '§2 验收范围与依据',
  s3: '§3 验收环境指纹',
  s4: '§4 执行结果汇总',
  s5: '§5 质量门禁结论',
  s6: '§6 性能与安全专项',
  s7: '§7 遗留缺陷与处置意见',
  s8: '§8 验收结论与签核',
}

export const VERDICT_CN = {
  PASSED: '通过',
  CONDITIONAL: '有条件通过',
  REJECTED: '不通过',
  FAILED: '未达标',
  null: '—',
}

export const VERDICT_COLOR = {
  PASSED: 'green',
  CONDITIONAL: 'orange',
  REJECTED: 'red',
  FAILED: 'red',
}

const fmtRate = (v) => (v == null ? '—' : `${(Number(v) * 100).toFixed(2)}%`)
const fmtNum = (v) => (v == null ? '—' : v)

function Section({ id, title, children }) {
  return (
    <section id={id}>
      <h2>{title}</h2>
      {children}
    </section>
  )
}

export function UatSections({ payload, upTo = 8 }) {
  if (!payload?.sections) return null
  const s = payload.sections
  const show = (n) => n <= upTo
  const s1 = s.s1_overview || {}
  const s2 = s.s2_scope || {}
  const s3 = s.s3_environment || {}
  const s4 = s.s4_results || {}
  const s5 = s.s5_gate || {}
  const s6 = s.s6_perf_security || {}
  const s7 = Array.isArray(s.s7_defects) ? s.s7_defects : []
  const s8 = s.s8_conclusion || {}
  const { env, ...envMeta } = s3
  const envRows = Object.entries(env || {})

  return (
    <>
      {show(1) && <Section id="uat-s1" title={SECTION_TITLES.s1}>
        <table>
          <tbody>
            <tr><th>项目 ID</th><td>{fmtNum(s1.project_id)}</td></tr>
            <tr>
              <th>纳入任务</th>
              <td>{(s1.task_nos || []).length ? (s1.task_nos || []).join('、') : '—'}</td>
            </tr>
            <tr><th>UAT 版本</th><td>v{fmtNum(payload.uat_version)}</td></tr>
          </tbody>
        </table>
      </Section>}

      {show(2) && <Section id="uat-s2" title={SECTION_TITLES.s2}>
        <p className="uat-meta">
          验收依据：{s2.criteria_source === 'override' ? '人工覆写标准' : '各任务质量门禁合并'}
          {s2.contract_no ? `　｜　合同编号：${s2.contract_no}` : ''}
        </p>
        <table>
          <thead>
            <tr><th>指标</th><th>比较</th><th>阈值</th></tr>
          </thead>
          <tbody>
            {(s2.criteria || []).map((r, i) => (
              <tr key={i}>
                <td>{r.metric}</td><td>{r.op}</td><td>{r.threshold}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>}

      {show(3) && <Section id="uat-s3" title={SECTION_TITLES.s3}>
        {envRows.length ? (
          <table>
            <tbody>
              {envRows.map(([k, v]) => (
                <tr key={k}><th>{k}</th><td>{fmtNum(v)}</td></tr>
              ))}
            </tbody>
          </table>
        ) : <p className="uat-meta">无环境指纹数据。</p>}
        {(s3.distinct_env_count || 0) > 1 && (
          <p className="uat-conditional-note">
            所选任务报告来自 {s3.distinct_env_count} 套不同环境，请人工确认环境一致性。
          </p>
        )}
      </Section>}

      {show(4) && <Section id="uat-s4" title={SECTION_TITLES.s4}>
        <table>
          <thead>
            <tr><th>任务编号</th><th>任务名称</th><th>用例数</th><th>通过率</th><th>门禁</th><th>开始</th><th>结束</th></tr>
          </thead>
          <tbody>
            {(s4.per_task || []).map((t) => (
              <tr key={t.task_id}>
                <td>{t.task_no}</td>
                <td>{t.title}</td>
                <td>{fmtNum(t.cases)}</td>
                <td>{fmtRate(t.pass_rate)}</td>
                <td>{VERDICT_CN[t.verdict] ?? '—'}</td>
                <td>{fmtNum(t.started_at)}</td>
                <td>{fmtNum(t.finished_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="uat-meta">
          合计用例 {fmtNum(s4.total_cases)}　｜　加权总通过率 {fmtRate(s4.agg_pass_rate)}
        </p>
      </Section>}

      {show(5) && <Section id="uat-s5" title={SECTION_TITLES.s5}>
        <table>
          <thead>
            <tr><th>指标</th><th>比较</th><th>阈值</th><th>实际</th><th>判定</th></tr>
          </thead>
          <tbody>
            {(s5.checks || []).map((c, i) => (
              <tr key={i} className={c.passed ? 'uat-row-pass' : 'uat-row-fail'}>
                <td>{c.metric}</td>
                <td>{c.op}</td>
                <td>{c.threshold}</td>
                <td>{fmtNum(c.actual)}</td>
                <td>{c.passed ? '达标' : '未达标'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p>门禁结论：<strong style={{ color: s5.verdict === 'PASSED' ? 'var(--uat-pass)' : 'var(--uat-reject)' }}>{VERDICT_CN[s5.verdict] ?? '—'}</strong></p>
      </Section>}

      {show(6) && <Section id="uat-s6" title={SECTION_TITLES.s6}>
        <table>
          <thead><tr><th colSpan="2">性能（跨任务用例数加权）</th></tr></thead>
          <tbody>
            <tr><th>RT P50 / P95 / P99</th><td>
              {fmtNum(s6.performance?.rt_p50)} / {fmtNum(s6.performance?.rt_p95)} / {fmtNum(s6.performance?.rt_p99)}
            </td></tr>
            <tr><th>TPS</th><td>{fmtNum(s6.performance?.tps)}</td></tr>
            <tr><th>错误率</th><td>{fmtRate(s6.performance?.error_rate)}</td></tr>
          </tbody>
        </table>
        <table>
          <thead><tr><th colSpan="2">安全</th></tr></thead>
          <tbody>
            <tr><th>风险等级</th><td>{fmtNum(s6.security?.risk_level)}</td></tr>
            <tr><th>风险依据</th><td>{(s6.security?.risk_basis || []).join('；') || '—'}</td></tr>
            <tr><th>红队覆盖率</th><td>{fmtNum(s6.security?.redteam_coverage)}</td></tr>
          </tbody>
        </table>
      </Section>}

      {show(7) && <Section id="uat-s7" title={SECTION_TITLES.s7}>
        {s7.length ? (
          <table>
            <thead>
              <tr><th>缺陷编号</th><th>标题</th><th>严重级</th><th>状态</th><th>处置意见</th></tr>
            </thead>
            <tbody>
              {s7.map((d) => (
                <tr key={d.id}>
                  <td>{d.defect_no}</td>
                  <td>{d.title}</td>
                  <td>{fmtNum(d.severity)}</td>
                  <td>{fmtNum(d.status)}</td>
                  <td>{(() => {
                    const dp = d.disposal
                    if (!dp || typeof dp !== 'object') return dp || '待处置'
                    const parts = []
                    if (dp.deadline) parts.push(`承诺期限 ${dp.deadline}`)
                    if (dp.waiver) parts.push(`豁免：${dp.waiver}`)
                    return parts.join('　') || '待处置'
                  })()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <p className="uat-meta">无未闭环严重级缺陷。</p>}
      </Section>}

      {show(8) && <Section id="uat-s8" title={SECTION_TITLES.s8}>
        <p>建议结论：{VERDICT_CN[s8.verdict_suggested] ?? '—'}</p>
        <p>
          验收结论：
          <strong style={{ color: s8.verdict === 'PASSED' ? 'var(--uat-pass)' : s8.verdict === 'CONDITIONAL' ? 'var(--uat-conditional)' : s8.verdict ? 'var(--uat-reject)' : 'inherit' }}>
            {s8.verdict ? VERDICT_CN[s8.verdict] : '未签核'}
          </strong>
        </p>
        {s8.verdict === 'CONDITIONAL' && s8.note ? (
          <p className="uat-conditional-note">豁免说明：{s8.note}</p>
        ) : s8.note ? <p>签核备注：{s8.note}</p> : null}
        <p className="uat-meta">
          供方签署：{s8.signer_vendor?.name || '—'}{s8.signer_vendor?.signed_at ? `　${s8.signer_vendor.signed_at}` : ''}
          客方签署：{s8.signer_customer?.name || '—'}{s8.signer_customer?.signed_at ? `　${s8.signer_customer.signed_at}` : ''}
        </p>
        {payload.report_hash ? <p className="uat-hash">报告哈希：{payload.report_hash}</p> : null}
      </Section>}
    </>
  )
}

export default UatSections
