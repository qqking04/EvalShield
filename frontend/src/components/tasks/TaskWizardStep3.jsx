/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// U8-1：新建/编辑任务向导 — Step 3「关联用例 + 提交」（自 pages/Tasks.jsx 抽出，行为零变更）
import { Alert, Button, Divider, Form, Input, InputNumber, Select, Space, Tag, Typography } from 'antd'
import { FileDoneOutlined, MinusCircleOutlined, PlusOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import { ENGINE_NAME_MAP } from '../../constants/enums'
import { tokens } from '../../theme/tokens'

// ES8 M5：质量门禁指标/算子下拉（与后端 quality_gate.GATE_METRICS / GATE_OPS 一致）
const GATE_METRIC_OPTIONS = [
  { value: 'pass_rate', label: '通过率 pass_rate' },
  { value: 'critical_defects', label: '严重缺陷数 critical_defects' },
  { value: 'hallucination_rate', label: '幻觉率 hallucination_rate' },
  { value: 'injection_success_rate', label: '注入安全率 injection_success_rate' },
]
const GATE_OP_OPTIONS = [
  { value: 'gte', label: '≥' },
  { value: 'gt', label: '>' },
  { value: 'lte', label: '≤' },
  { value: 'lt', label: '<' },
]

export default function TaskWizardStep3({
  editing,
  selectedEngines,
  selectedProjectId,
  requiredCategories,
  filteredCases,
  needsTaskCaseIds,
  triggerMode,
  setTriggerMode,
}) {
  const selectedEnginesArr = selectedEngines || []
  return (
    <>
      {needsTaskCaseIds && (
        <Form.Item name="case_ids" label={<span>执行用例<Tag color="blue" style={{ marginLeft: 6 }}>任务级共享</Tag></span>}
          extra={selectedProjectId ? `已按引擎类型过滤：${requiredCategories.join(' / ')} 共 ${filteredCases.length} 条` : '请先选择项目'}>
          <Select mode="multiple" allowClear disabled={!selectedProjectId} optionFilterProp="label"
            placeholder={selectedProjectId ? '选择本次任务要执行的用例' : '请先选择项目'}
            options={filteredCases.map((c) => ({ value: c.id, label: `${c.case_no || `#${c.id}`} ${c.title || ''}` }))}
            suffixIcon={<FileDoneOutlined />} />
        </Form.Item>
      )}
      <Form.Item name="description" label="任务描述">
        <Input.TextArea rows={2} />
      </Form.Item>
      <Form.Item name="trigger_mode" label="触发方式" initialValue="MANUAL">
        <Select onChange={setTriggerMode}
          options={[
            { value: 'MANUAL', label: '手动执行（创建后手动点"执行"）' },
            { value: 'SCHEDULED', label: '定时执行（按 cron 自动触发）' },
          ]} />
      </Form.Item>
      {triggerMode === 'SCHEDULED' && (
        <Form.Item name="schedule_cron" label="Cron 表达式（5 段：分 时 日 月 周）"
          rules={[{ validator: (_, v) => {
            if (!v || !v.trim()) return Promise.reject(new Error('定时模式必须填写 Cron'))
            const parts = v.trim().split(/\s+/)
            if (parts.length !== 5) return Promise.reject(new Error('Cron 必须 5 段（分 时 日 月 周）'))
            return Promise.resolve()
          }}]}
          extra="示例：0 9 * * 1-5 表示工作日每天 09:00">
          <Input placeholder="如 0 9 * * 1-5" />
        </Form.Item>
      )}
      {/* ES8 M5：质量门禁区（任务终态时按规则评估，任一不满足 → gate_result=FAILED） */}
      <Divider orientation="left" style={{ margin: '12px 0', borderColor: tokens.border }}>
        <Space size={4}>
          <SafetyCertificateOutlined style={{ color: tokens.primary }} />
          <span>质量门禁</span>
          <Typography.Text style={{ color: tokens.text3, fontSize: 12 }}>（可选：不配置则任务不设门禁）</Typography.Text>
        </Space>
      </Divider>
      <Form.List name="gate_rules">
        {(fields, { add, remove }) => (
          <>
            {fields.map(({ key, name, ...rest }) => (
              <Space key={key} align="baseline" style={{ display: 'flex', marginBottom: 4 }}>
                <Form.Item {...rest} name={[name, 'metric']} style={{ marginBottom: 8 }}
                  rules={[{ required: true, message: '选择指标' }]}>
                  <Select placeholder="指标" style={{ width: 240 }} options={GATE_METRIC_OPTIONS} />
                </Form.Item>
                <Form.Item {...rest} name={[name, 'op']} style={{ marginBottom: 8 }}
                  rules={[{ required: true, message: '选择算子' }]}>
                  <Select placeholder="条件" style={{ width: 72 }} options={GATE_OP_OPTIONS} />
                </Form.Item>
                <Form.Item {...rest} name={[name, 'threshold']} style={{ marginBottom: 8 }}
                  rules={[{ required: true, message: '填写阈值' }]}>
                  <InputNumber placeholder="阈值" style={{ width: 110 }} step={0.01} />
                </Form.Item>
                <MinusCircleOutlined style={{ color: tokens.text3 }} onClick={() => remove(name)} />
              </Space>
            ))}
            <Form.Item style={{ marginBottom: 12 }}>
              <Button type="dashed" block icon={<PlusOutlined />}
                onClick={() => add({ metric: 'pass_rate', op: 'gte', threshold: 0.9 })}
                disabled={fields.length >= 20}>
                添加门禁规则（每条为必须满足的通过条件）
              </Button>
            </Form.Item>
          </>
        )}
      </Form.List>
      {/* Step 3 引擎 × 关联提示：让用户清楚当前选择了什么引擎、关联了什么 category 的 case */}
      {selectedEnginesArr.length > 0 && (
        <Alert type="info" showIcon style={{ marginBottom: 12 }}
          message={
            <Space wrap>
              <span>本次任务引擎：</span>
              {selectedEnginesArr.map((e) => <Tag key={e} color="blue">{ENGINE_NAME_MAP[e] || e}</Tag>)}
              {requiredCategories.length > 0 && (
                <><span>自动关联用例类别：</span>{requiredCategories.map((c) => <Tag key={c} color="green">{c}</Tag>)}</>
              )}
              {needsTaskCaseIds && filteredCases.length === 0
                ? <span style={{ color: '#faad14' }}>⚠️ 当前项目暂无 {requiredCategories.join('/')} 类用例（0 条），可直接提交（稍后到"用例管理"创建用例再回来关联），也可先创建用例</span>
                : needsTaskCaseIds
                  ? <span style={{ color: '#52c41a' }}>✅ 下方可选择具体用例</span>
                  : <span style={{ color: '#faad14' }}>⚪ 所选引擎走 eval_set_id 配置（Step 2），跳过用例选择</span>}
            </Space>
          }
        />
      )}
      <Alert type="success" showIcon
        message={editing ? <span>任务配置已更新，点击"保存修改"完成编辑</span> : <span>任务配置已完成，点击"提交任务"创建任务 → 回到任务列表手动点"执行"启动</span>} />
    </>
  )
}
