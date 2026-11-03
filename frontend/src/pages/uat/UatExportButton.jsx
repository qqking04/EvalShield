/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import React, { useState } from 'react'
import { Button, Dropdown, Tooltip, message } from 'antd'
import { DownloadOutlined } from '@ant-design/icons'
import { downloadBlob } from '../../api/http'
import { useIsCommunity } from '../../edition/EditionContext'

const EXT = { pdf: 'pdf', word: 'docx', md: 'md', html: 'html' }

/* UAT 导出下拉（列表与详情共用）：community 形态 pdf/word 置灰「升级解锁」。 */
export default function UatExportButton({ projectId, reportId, reportNo, status, compact }) {
  const community = useIsCommunity()
  const [busy, setBusy] = useState('')
  const label =
    status === 'FINALIZED' ? '导出终版' : status === 'DRAFT' || status === 'REJECTED' ? '导出草稿（含水印）' : '导出'

  const doExport = async (format) => {
    setBusy(format)
    try {
      await downloadBlob(
        `/projects/${projectId}/uat-reports/${reportId}/export`,
        { format },
        `${reportNo || `uat-${reportId}`}.${EXT[format]}`,
      )
      message.success('已开始下载')
    } catch {
      /* http 拦截器/downloadBlob 已提示 */
    } finally {
      setBusy('')
    }
  }

  const items = ['pdf', 'word', 'md', 'html'].map((f) => {
    const locked = community && (f === 'pdf' || f === 'word')
    return {
      key: f,
      disabled: locked || !!busy,
      label: locked ? (
        <Tooltip title="升级解锁">
          <span>{f.toUpperCase()}</span>
        </Tooltip>
      ) : (
        f.toUpperCase()
      ),
    }
  })

  return (
    <Dropdown menu={{ items, onClick: ({ key }) => doExport(key) }} trigger={['click']}>
      <Button size={compact ? 'small' : undefined} type="link" icon={<DownloadOutlined />} loading={!!busy}>
        {label}
      </Button>
    </Dropdown>
  )
}
