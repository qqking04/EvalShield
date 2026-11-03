/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// EnvironmentBlock.jsx —— 报告头环境指纹展示（v2.0 BUG-002）
import { Descriptions, Tag, Typography } from 'antd'
import { DesktopOutlined, ClockCircleOutlined, CloudServerOutlined } from '@ant-design/icons'
import { RiskTag } from './charts'

const { Text } = Typography

/**
 * 环境指纹展示组件
 * @param {Object} environment - 后端返回的 environment 对象
 * @param {string} riskLevel - 风险等级（英文枚举）
 * @param {string} riskBasis - 风险判定依据
 */
export default function EnvironmentBlock({ environment = {}, riskLevel, riskBasis }) {
  const env = environment || {}

  const renderDeps = (deps) => {
    if (!Array.isArray(deps) || deps.length === 0) return <Text type="secondary">未采集</Text>
    return deps.map((d, i) => (
      <Tag key={i} color="blue">{d.name} {d.version}</Tag>
    ))
  }

  const renderDuration = (sec) => {
    if (sec === null || sec === undefined) return '-'
    if (sec < 60) return `${sec}秒`
    const m = Math.floor(sec / 60)
    const s = Math.round(sec % 60)
    return `${m}分${s}秒`
  }

  return (
    <div style={{ marginBottom: 16 }}>
      <Descriptions
        title={<span><CloudServerOutlined style={{ marginRight: 6 }} />运行环境快照</span>}
        bordered
        column={{ xs: 1, sm: 2, md: 3 }}
        size="small"
      >
        <Descriptions.Item label="被测系统版本">
          {env.sut_version || <Text type="secondary">未采集</Text>}
        </Descriptions.Item>
        <Descriptions.Item label="分支 / Commit">
          {env.sut_branch || '-'} / {env.sut_commit || '-'}
        </Descriptions.Item>
        <Descriptions.Item label="被测服务地址">
          {env.sut_url ? (
            <a href={env.sut_url} target="_blank" rel="noreferrer">{env.sut_url}</a>
          ) : <Text type="secondary">未采集</Text>}
        </Descriptions.Item>
        <Descriptions.Item label="操作系统">
          {env.os || <Text type="secondary">未采集</Text>}
        </Descriptions.Item>
        <Descriptions.Item label="浏览器">
          {env.browser || <Text type="secondary">未采集</Text>}
          {env.browser_version ? ` ${env.browser_version}` : ''}
        </Descriptions.Item>
        <Descriptions.Item label="视口分辨率">
          <DesktopOutlined /> {env.viewport || '未采集'}
        </Descriptions.Item>
        <Descriptions.Item label="开始时间">
          <ClockCircleOutlined /> {env.started_at || '-'}
        </Descriptions.Item>
        <Descriptions.Item label="结束时间">
          {env.finished_at || '-'}
        </Descriptions.Item>
        <Descriptions.Item label="总耗时">
          {renderDuration(env.duration_sec)}
        </Descriptions.Item>
        <Descriptions.Item label="依赖版本" span={3}>
          {renderDeps(env.dependencies)}
        </Descriptions.Item>
        {/* 安全报告补全 P2：检测上下文（授权声明/检测账号/检测方法） */}
        {env.authorization && (
          <Descriptions.Item label="授权声明" span={3}>
            {env.authorization}
          </Descriptions.Item>
        )}
        {Array.isArray(env.test_accounts) && env.test_accounts.length > 0 && (
          <Descriptions.Item label="检测账号" span={3}>
            {env.test_accounts.map((a, i) => (
              <Tag key={i} color="cyan">{a.username}{a.display_name ? ` / ${a.display_name}` : ''}{a.role ? ` / ${a.role}` : ''}</Tag>
            ))}
          </Descriptions.Item>
        )}
        {env.test_method && (
          <Descriptions.Item label="检测方法" span={3}>
            {env.test_method}
          </Descriptions.Item>
        )}
      </Descriptions>

      {/* 风险等级展示（含判定依据） */}
      {riskLevel && (
        <div style={{ marginTop: 8, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <Text strong>风险等级：</Text>
          <RiskTag level={riskLevel} />
          {riskBasis && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              （判定依据：{riskBasis}）
            </Text>
          )}
        </div>
      )}
    </div>
  )
}
