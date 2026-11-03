/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// ScreenshotGallery.jsx —— 失败截图缩略图网格 + 放大预览（v2.0 BUG-003）
import { Image, Badge, Empty, Typography } from 'antd'
import { CameraOutlined } from '@ant-design/icons'

const { Text } = Typography

// 截图路径 → 可访问 URL：仅使用后端下发的签名 url（/api/evidence/ 裸路径
// 无 es_sig 签名会被 secure_static 401 拒绝，故不再前端拼兜底 URL；
// url 缺失时渲染 fallback 灰图，s.path 仅作展示/排查参考）
function shotUrl(s) {
  return s.url || ''
}

/**
 * 截图展示组件
 * @param {Array} screenshots - [{case_id, path, url}]
 * @param {string|number} caseId - 当前用例 ID（可选，过滤用）
 */
export default function ScreenshotGallery({ screenshots = [], caseId }) {
  const filtered = (caseId === null || caseId === undefined || caseId === '')
    ? screenshots
    : screenshots.filter((s) => s.case_id === caseId)

  if (!filtered.length) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无截图" />
  }

  return (
    <div>
      <div style={{ marginBottom: 8 }}>
        <Badge count={filtered.length} style={{ backgroundColor: '#1890ff' }}>
          <CameraOutlined style={{ fontSize: 18, marginRight: 8 }} />
        </Badge>
        <Text strong>失败截图（{filtered.length} 张）</Text>
      </div>
      <Image.PreviewGroup>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {filtered.map((s, i) => (
            <Image
              key={i}
              src={shotUrl(s)}
              width={120}
              height={90}
              style={{ objectFit: 'cover', border: '1px solid #d9d9d9', borderRadius: 4, cursor: 'pointer' }}
              fallback="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mN8/+F/PQAJpAN4lFLyMAAAAABJRU5ErkJggg=="
            />
          ))}
        </div>
      </Image.PreviewGroup>
    </div>
  )
}
