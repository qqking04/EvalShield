/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import { Modal, Progress, Typography, Button, Space } from 'antd'
import { ArrowUpOutlined } from '@ant-design/icons'
import tokens from '../theme/tokens'

// ES9-P-02：社区版超限升级引导卡（方案 §2.2.3）。
// 后端错误体：{ code: "ES-LIMIT-0001", message, detail: { kind, limit, used, unit, suggest_plan } }。
// 纯展示组件（供测试与命令式弹窗共用），不依赖 http 模块避免循环引用。

const KIND_LABEL = {
  projects_total: '项目总量',
  eval_runs_month: '每月评测次数',
  questions_total: '题库题目总量',
  users_total: '成员数量',
  concurrent_tasks: '并发任务数',
  local_llm: '本地模型接入',
  scheduler: '定时调度',
  question_total: '题库题目',
  tenants: '租户数量',
  orgs: '组织数量',
  platform: '平台运营',
}

export function EditionLimitCard({ detail, fallbackMessage }) {
  const used = Number(detail?.used ?? 0)
  const limit = Number(detail?.limit ?? 0)
  const unit = detail?.unit || ''
  const label = KIND_LABEL[detail?.kind] || '当前功能'
  const percent = limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 100
  return (
    <div data-testid="edition-limit-card" style={{ paddingTop: 4 }}>
      <Typography.Paragraph style={{ marginBottom: 12 }}>
        <Typography.Text strong style={{ color: tokens.text1 }}>
          {label}
        </Typography.Text>
        <Typography.Text style={{ color: tokens.text2 }}> 已达社区版上限</Typography.Text>
      </Typography.Paragraph>
      <Progress
        percent={percent}
        status="exception"
        strokeColor={tokens.danger}
        format={() => `${used}/${limit} ${unit}`}
      />
      <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
        {fallbackMessage || '升级商业版解除限制'}
      </Typography.Paragraph>
    </div>
  )
}

// 命令式入口：http 拦截器识别 ES-LIMIT-* 后调用；同屏仅保留一个弹窗
let openInstance = null
export function showEditionLimitModal({ code, message: msg, detail }) {
  if (openInstance) return
  const planLabel = detail?.suggest_plan === 'enterprise' ? '企业版' : '专业版'
  openInstance = Modal.confirm({
    title: (
      <Space>
        <ArrowUpOutlined style={{ color: tokens.primary }} />
        社区版能力上限
      </Space>
    ),
    icon: null,
    content: <EditionLimitCard detail={detail} fallbackMessage={msg} />,
    okText: `对比版本（建议 ${planLabel}）`,
    okButtonProps: { size: 'small' },
    cancelText: '关闭',
    onOk: () => {
      // /edition-compare 为免登录公开页，整页导航即可达
      window.location.href = '/edition-compare'
    },
    afterClose: () => {
      openInstance = null
    },
  })
}

export default EditionLimitCard
