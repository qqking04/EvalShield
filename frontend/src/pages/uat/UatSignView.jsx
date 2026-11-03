/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import React, { useEffect, useState } from 'react'
import { Alert, Button, Input, Modal, Result, Space, Spin, Typography, message } from 'antd'
import { useParams } from 'react-router-dom'
import { publicGetUat, publicSignUat } from '../../api/uat'
import UatSections from './UatSections'
import './uat.css'

/* ES9 UAT 免登录客户签署页（路由 /s/uat/:token，照 ShareReport.jsx 范式）。 */
export default function UatSignView() {
  const { token } = useParams()
  const [state, setState] = useState('loading') // loading | ok | invalid | error
  const [detail, setDetail] = useState(null)
  const [errMsg, setErrMsg] = useState('')
  const [name, setName] = useState('')
  const [busy, setBusy] = useState('')
  const [done, setDone] = useState('')

  useEffect(() => {
    publicGetUat(token)
      .then((resp) => {
        const body = resp?.data
        if (resp?.status === 200 && body && (body.code === 0 || body.content)) {
          setDetail(body?.data || body)
          setState('ok')
        } else if (resp?.status === 400 || body?.code === 'ES9-UAT-0005') {
          setErrMsg(body?.message || '签署链接已过期或已使用')
          setState('invalid')
        } else {
          setErrMsg(body?.message || `加载失败(${resp?.status})`)
          setState('error')
        }
      })
      .catch(() => setState('error'))
  }, [token])

  const submit = (verdict) => {
    if (!name.trim()) {
      message.warning('请填写签署人姓名')
      return
    }
    const run = async (note) => {
      setBusy(verdict)
      try {
        const resp = await publicSignUat(token, { name: name.trim(), verdict, note })
        const body = resp?.data
        if (resp?.status === 200 && (body?.code === 0 || body?.status)) {
          setDone(verdict === 'REJECTED' ? '已拒收，等待供应商整改' : '签署完成，等待供应商归档')
        } else if (body?.code === 'ES9-UAT-0005') {
          setErrMsg(body?.message || '签署链接已过期或已使用')
          setState('invalid')
        } else {
          message.error(body?.message || '签署失败，请稍后重试')
        }
      } catch {
        message.error('网络异常，请稍后重试')
      } finally {
        setBusy('')
      }
    }
    if (verdict === 'REJECTED') {
      let reason = ''
      Modal.confirm({
        title: '拒收验收报告',
        content: (
          <Input.TextArea
            rows={3}
            placeholder="拒收理由（必填）"
            onChange={(e) => { reason = e.target.value }}
          />
        ),
        okText: '确认拒收',
        okButtonProps: { danger: true },
        onOk: () => {
          if (!reason.trim()) {
            message.error('拒收理由必填')
            return Promise.reject()
          }
          return run(reason.trim())
        },
      })
    } else {
      run(null)
    }
  }

  if (state === 'loading') {
    return (
      <div style={{ textAlign: 'center', paddingTop: 140 }}>
        <Spin size="large" tip="加载中...">
          <div style={{ minHeight: 80, minWidth: 80 }} />
        </Spin>
      </div>
    )
  }
  if (state === 'invalid') {
    return (
      <Result status="warning" title="签署链接已失效" subTitle={errMsg || '链接无效、已过期或已被使用，请联系供应商重新发出。'} />
    )
  }
  if (state === 'error' || !detail) {
    return <Result status="error" title="加载失败" subTitle={errMsg || '请稍后重试'} />
  }
  if (done) {
    return <Result status="success" title={done} subTitle={`报告编号 ${detail.report_no}`} />
  }

  const hash = detail.content?.report_hash || ''
  const acc = detail.acceptance || {}

  return (
    <div style={{ background: '#F2F3F5', minHeight: '100vh', paddingBottom: 96 }}>
      <div style={{ maxWidth: 876, margin: '0 auto', padding: '16px 0' }}>
        <Alert
          type="info"
          showIcon
          message="本页面为只读验收文档，数据加密传输，不存储本地"
          description={
            <span className="mono" style={{ fontSize: 12 }}>
              {detail.report_no}　v{detail.uat_version ?? 1}
              {hash ? `　哈希尾号 ${hash.slice(-8)}` : ''}
              {acc.signer_vendor?.name ? `　供方已签署：${acc.signer_vendor.name}` : ''}
            </span>
          }
          style={{ marginBottom: 16 }}
        />
        <div className="uat-paper uat-doc">
          <h1>{detail.title}</h1>
          <div className="uat-doc-sub">UAT 验收报告　v{detail.uat_version ?? 1}</div>
          <UatSections payload={detail.content} />
        </div>

        {/* 底部签署表单 */}
        <div style={{ maxWidth: 820, margin: '16px auto 0', background: '#fff', borderRadius: 8, padding: '16px 24px', boxShadow: '0 2px 8px rgba(0,0,0,.08)' }}>
          <Space wrap align="baseline">
            <Typography.Text strong>客方签署人</Typography.Text>
            <Input
              style={{ width: 260 }}
              placeholder="姓名（必填）"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <Button
              type="primary"
              loading={busy === 'PASSED'}
              disabled={!name.trim() || !!busy}
              onClick={() => submit('PASSED')}
            >
              签署验收
            </Button>
            <Button
              danger
              loading={busy === 'REJECTED'}
              disabled={!name.trim() || !!busy}
              onClick={() => submit('REJECTED')}
            >
              拒收
            </Button>
          </Space>
          <Typography.Paragraph type="secondary" style={{ margin: '8px 0 0', fontSize: 12 }}>
            签署为单次操作：提交后本链接立即失效。请核对 §1–§8 全部内容与报告哈希后再签署。
          </Typography.Paragraph>
        </div>
      </div>
    </div>
  )
}
