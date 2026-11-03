/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// U8-1：新建/编辑任务向导 — Step 1「选引擎」（自 pages/Tasks.jsx 抽出，行为零变更）
import { Form, Input, Select, Typography } from 'antd'
import IndustryTemplateSelector from './IndustryTemplateSelector'

export default function TaskWizardStep1({
  form,
  editing,
  projects,
  envs,
  engineOptions,
  engines,
  message,
}) {
  return (
    <>
      <Form.Item name="name" label="任务名称" rules={[{ required: true, message: '请输入任务名称' }]}>
        <Input placeholder="如：智能客服系统回归测试" />
      </Form.Item>
      <Form.Item name="project_id" label="所属项目" rules={[{ required: true, message: '请选择项目' }]}>
        <Select placeholder="选择项目" virtual={false} listHeight={320}
          options={projects.map((p) => ({ value: p.id, label: `${p.code} - ${p.name}` }))} />
      </Form.Item>
      {/* P0-1：执行环境选择（来自 TestEnvironment 新表） */}
      <Form.Item name="env_id" label="执行环境（可选）" extra="选中后自动填充被测系统地址，后端按该环境执行">
        <Select allowClear placeholder="不选则手动填写被测系统地址" virtual={false} listHeight={320}
          options={envs.map((e) => ({
            value: e.id,
            label: `${e.name}${e.is_default ? '（默认）' : ''} — ${e.base_url}`,
          }))}
          onChange={(envId) => {
            if (!envId) {
              form.setFieldsValue({ env_id: null })
              return
            }
            const picked = envs.find((e) => e.id === envId)
            if (picked?.base_url) {
              form.setFieldsValue({
                'config__UI_TEST__base_url': picked.base_url,
                'config__API_TEST__base_url': picked.base_url,
                'config__DATAFLOW_TEST__base_url': picked.base_url,
                env_id: picked.id,
              })
            }
          }}
        />
      </Form.Item>
      <Form.Item name="engines" label="测试引擎（按顺序执行）" rules={[{ required: true, message: '请选择引擎' }]}>
        <Select mode="multiple" placeholder="可选择多个引擎，如 UI_TEST / API_TEST / HALLUCINATION_TEST"
          optionFilterProp="label" options={engineOptions} />
      </Form.Item>
      {/* P1：行业评估模板一键套用 */}
      {!editing && (
        <IndustryTemplateSelector
          style={{ marginBottom: 16 }}
          onApply={(tpl) => {
            const cfg = tpl.engine_config || {}
            const available = (engineOptions || []).map((o) => o.value)
            const picked = (cfg.engines || []).filter((e) => available.includes(e))
            if (picked.length) form.setFieldValue('engines', picked)
            const thresholds = cfg.thresholds || {}
            const patch = {}
            Object.entries(thresholds).forEach(([eng, th]) => {
              if (picked.includes(eng)) patch[`config__${eng}__threshold`] = th
            })
            if (Object.keys(patch).length) form.setFieldsValue(patch)
            message.success(`已套用「${tpl.template_name}」：${picked.join(' / ')}`)
          }}
        />
      )}
      {/* v2.0：被测系统版本指纹手填项（写入 config，报告环境信息区块展示；留空则如实显示"未采集"） */}
      <Form.Item name="sut_version" label="被测系统版本（可选）" extra="如 v1.2.3，写入报告环境指纹">
        <Input placeholder="如：v1.2.3" maxLength={64} allowClear />
      </Form.Item>
      <Form.Item name="sut_branch" label="被测系统分支（可选）" extra="如 release/2026-10">
        <Input placeholder="如：main / release/2026-10" maxLength={64} allowClear />
      </Form.Item>
      <Form.Item name="sut_commit" label="被测系统 Commit（可选）" extra="Git commit hash">
        <Input placeholder="如：a1b2c3d" maxLength={64} allowClear />
      </Form.Item>
      {engines.length === 0 && (
        <Typography.Text type="warning">未获取到可用引擎，请确认后端已启动。</Typography.Text>
      )}
    </>
  )
}
