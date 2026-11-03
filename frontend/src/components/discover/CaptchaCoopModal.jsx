/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import { Modal, Input, Space, Typography, Button, Alert } from 'antd'
import { useEffect, useRef, useState } from 'react'
import { C, MONO } from './consoleTheme'

const { Text } = Typography

const TYPE_HINT = {
  CAPTCHA: '请输入图中字符',
  SMS: '请输入短信验证码',
  QR: '请扫码后点击「已完成」',
  SLIDER: '请完成滑块后点击「已完成」',
  OTP: '请输入动态口令',
  DIALOG: '请在下方浏览器中处理弹框',
  MANUAL: '请在下方浏览器中手动完成登录流程',
}

// 无 deadline 时按此兜底展示静态时长提示（与后端 DISCOVER_HUMAN_WAIT_TIMEOUT 保持一致）
const DEFAULT_TTL_SEC = 300

// 人机协作模态框：截图展示 + 剩余时间倒计时 + 重试序号 + 输入注入 + 超时/错误反馈（产品通用需求 FC-05）
export default function CaptchaCoopModal({ request, jobId, onDone, onDismiss }) {
  const [value, setValue] = useState('')
  const [ws, setWs] = useState('')
  const [uname, setUname] = useState('')
  const [pwd, setPwd] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState('')
  const [expired, setExpired] = useState(false)
  const [remainSec, setRemainSec] = useState(null)
  const deadlineRef = useRef(null)
  const timerRef = useRef(null)

  const open = !!request
  const type = request?.type || 'CAPTCHA'
  const hint = request?.hint || TYPE_HINT[type] || '请按提示完成验证'
  const needInput = request?.require_input !== false && type !== 'DIALOG' && type !== 'MANUAL'
  const attempt = request?.attempt || 1
  // 需要在弹窗附带浏览器中"亲手操作"的类型：本类不会自动填值
  const browserInteract = type === 'DIALOG' || type === 'MANUAL'
  // 图形验证码场景：允许用户一并修正/选择 工作区、用户名、密码（登录页无对应字段时后端自动忽略）
  const fullCred = type === 'CAPTCHA'

  // 每次弹框（新的 request）重置内部状态
  useEffect(() => {
    if (open) {
      setValue('')
      setSubmitError('')
      setExpired(false)
      setRemainSec(null)
      deadlineRef.current = request?.deadline ? Number(request.deadline) : null
    } else {
      deadlineRef.current = null
      setRemainSec(null)
    }
  }, [open, request?.deadline, request?.image])

  // 剩余时间倒计时（基于后端下发的 deadline 毫秒时间戳，轮询迟到打开也准确）
  useEffect(() => {
    if (!timerRef.current) {
      timerRef.current = setInterval(() => {
        if (!open) return
        const dl = deadlineRef.current
        if (!dl) return
        const remain = Math.floor((dl - Date.now()) / 1000)
        setRemainSec(Math.max(0, remain))
        if (remain <= 0) setExpired(true)
      }, 1000)
    }
    return () => {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
  }, [open])

  const submit = async (mode = 'normal') => {
    setSubmitError('')
    setSubmitting(true)
    try {
      const { default: http } = await import('../../api/http')
      // skip=跳过；manualdone=已在浏览器内手动完成（不填值，直接让后端重采登录态）；DIALOG/MANUAL → __DONE__
      let payloadValue
      if (mode === 'skip') payloadValue = '__SKIP__'
      else if (mode === 'manualdone') payloadValue = '__MANUAL_DONE__'
      else payloadValue = needInput ? value : '__DONE__'
      await http.post(`/ai/discover/${jobId}/submit-human`, {
        type,
        value: payloadValue,
        tenant_code: ws || undefined,
        username: uname || undefined,
        password: pwd || undefined,
      })
      setValue('')
      onDone?.()
    } catch (e) {
      setSubmitError((e?.response?.data?.message) || e?.message || '提交失败，请重试')
    } finally {
      setSubmitting(false)
    }
  }

  const showCountdown = remainSec !== null
  const countdownWarn = showCountdown && remainSec <= 30 && !expired
  const ttlText = showCountdown ? `剩余 ${remainSec}s` : '（长时间未操作将自动超时）'

  return (
    <Modal
      open={open}
      title={<span style={{ color: C.amber }}>🤖 人机验证 · 需要你的协助{attempt > 1 ? ` · 第 ${attempt} 次尝试` : ''}</span>}
      onCancel={() => onDismiss?.()}
      footer={null}
      width={520}
      closable
      maskClosable={false}
      styles={{ content: { background: C.panel, border: `1px solid ${C.panelBorder}` }, header: { background: C.panel } }}
    >
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        {/* 明确提示：还有多久 / 会超时 */}
        <div
          style={{
            padding: '6px 10px', borderRadius: 4, fontSize: 12,
            background: expired ? '#4a0e0e' : countdownWarn ? '#3a2a0a' : C.panel,
            border: `1px solid ${expired ? '#b33' : countdownWarn ? '#bb8800' : C.panelBorder}`,
            color: expired ? '#ff7b7b' : countdownWarn ? '#e6b800' : C.dim,
          }}
        >
          {expired
            ? '⏱ 等待超时：本次人机协作已终止，探测任务失败。'
            : `⏱ ${showCountdown ? '剩余时间提示' : '时间提示'}：${ttlText}`}
          {countdownWarn && !expired ? ' · 请尽快输入' : ''}
        </div>

        <Text style={{ color: C.dim, fontSize: 13, lineHeight: 1.6 }}>{hint}</Text>
        {browserInteract && (
          <div
            style={{
              padding: '8px 12px', borderRadius: 6, fontSize: 13, lineHeight: 1.5,
              background: '#14263c', border: '1px solid #2c6aa0', color: '#9fd0ff',
            }}
          >
            🛠 此类型<b>不会自动填值</b>：请在下方弹窗附带的浏览器窗口中完成操作
            {type === 'DIALOG' ? '（如选择工作区/确认弹框）' : '（如手动登录/扫码）'}，
            完成后点击右上角「已完成」即可继续。
          </div>
        )}
        {request?.image && (
          <div style={{ border: `1px solid ${C.panelBorder}`, borderRadius: 6, padding: 8, textAlign: 'center', background: '#fff' }}>
            <img src={`data:image/png;base64,${request.image}`} alt="人机协助" style={{ maxWidth: '100%' }} />
          </div>
        )}
        {needInput && fullCred && (
          <>
            <Space.Compact style={{ width: '100%' }}>
              <Input
                value={ws}
                onChange={(e) => setWs(e.target.value)}
                placeholder="工作区 / 租户（可选）"
                style={{ background: '#0d1420', borderColor: C.panelBorder, color: C.text, fontFamily: MONO }}
                disabled={expired}
                autoComplete="off"
              />
              <Input
                value={uname}
                onChange={(e) => setUname(e.target.value)}
                placeholder="用户名"
                style={{ background: '#0d1420', borderColor: C.panelBorder, color: C.text, fontFamily: MONO }}
                disabled={expired}
                autoComplete="off"
              />
            </Space.Compact>
            <Input
              value={pwd}
              type="password"
              onChange={(e) => setPwd(e.target.value)}
              placeholder="密码"
              style={{ background: '#0d1420', borderColor: C.panelBorder, color: C.text, fontFamily: MONO }}
              disabled={expired}
              autoComplete="off"
            />
          </>
        )}
        {needInput && (
          <Input
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder={fullCred ? '验证码（图中字符）' : '输入验证内容'}
            style={{ background: '#0d1420', borderColor: C.panelBorder, color: C.text, fontFamily: MONO }}
            onPressEnter={() => value && submit('normal')}
            disabled={expired}
            autoFocus
          />
        )}
        {/* 仍在等待且未填值时，若已在浏览器内自行操作完成，可跳过输入直接继续 */}
        {needInput && !value && !expired && (
          <div style={{ color: C.dim, fontSize: 12, lineHeight: 1.5 }}>
            若你已<b>在下方浏览器中手动完成登录/验证</b>，无需填写上方内容，直接点「已在浏览器中登录完成」继续 →
          </div>
        )}
        {/* 提交错误内联提示 */}
        {submitError && (
          <Alert type="error" showIcon message={submitError} style={{ fontSize: 12 }} />
        )}
        <Space style={{ width: '100%', justifyContent: 'flex-end', flexWrap: 'wrap' }}>
          <Button onClick={() => submit('manualdone')} disabled={submitting || expired}>
            已在浏览器中登录完成
          </Button>
          <Button onClick={() => submit('skip')} disabled={submitting || expired}>跳过</Button>
          <Button
            type="primary"
            danger={submitError}
            loading={submitting}
            disabled={expired || (needInput && !value)}
            onClick={() => submit('normal')}
            style={{ background: C.amber, borderColor: C.amber, color: '#000' }}
          >
            {needInput ? '提交并继续' : '已完成'}
          </Button>
        </Space>
      </Space>
    </Modal>
  )
}