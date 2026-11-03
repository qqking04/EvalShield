/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// P1：行业评估模板选择器 — 一键套用 5 行业引擎组合+阈值
import { useEffect, useState } from 'react'
import { Select, Space, Tag, Typography } from 'antd'
import http from '../../api/http'

const INDUSTRY_CN = {
  GOVERNMENT: '政务', FINANCE: '金融', MEDICAL: '医疗', EDUCATION: '教育', MEDIA: '媒体',
}

export default function IndustryTemplateSelector({ onApply, style }) {
  const [templates, setTemplates] = useState([])
  const [value, setValue] = useState(null)

  useEffect(() => {
    http.get('/industry-templates')
      .then((d) => setTemplates(d?.items || []))
      .catch(() => setTemplates([]))
  }, [])

  if (!templates.length) return null

  return (
    <Space direction="vertical" size={4} style={{ width: '100%', ...style }}>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        行业评估模板（可选）：选择后自动填充引擎组合与阈值
      </Typography.Text>
      <Select
        allowClear
        value={value}
        placeholder="选择行业模板一键套用"
        style={{ width: '100%' }}
        optionFilterProp="label"
        onChange={(id) => {
          setValue(id)
          const tpl = templates.find((t) => t.id === id)
          if (tpl && onApply) onApply(tpl)
        }}
        options={templates.map((t) => ({
          value: t.id,
          label: (
            <Space size={6}>
              <Tag color="cyan">{INDUSTRY_CN[t.industry_name] || t.industry_name}</Tag>
              <span>{t.template_name}</span>
              <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                {(t.engine_config?.engines || []).join(' / ')}
              </Typography.Text>
            </Space>
          ),
        }))}
      />
    </Space>
  )
}
