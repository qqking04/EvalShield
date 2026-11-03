/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// ES9 任务十二：超管运维侧「版本形态」管理页
// 能力：当前形态 + .env 漂移检测 / 目标形态影响预览 / 危险确认后切换（写 .env）/ 一键受控重启 + 轮询生效
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Alert, App, Button, Card, Descriptions, Input, Modal, Select, Space, Spin, Tag, Tooltip,Typography,
} from 'antd'
import { ReloadOutlined, SwapOutlined, SyncOutlined } from '@ant-design/icons'
import http from '../../api/http'
import { useAuth } from '../../auth'

const { Text, Paragraph } = Typography

const EDITION_LABEL = { community: '社区版', saas: 'SaaS 版', enterprise: '企业版' }
const label = (v) => (EDITION_LABEL[v] ? `${v}（${EDITION_LABEL[v]}）` : v)

// 前端构建期常量（vite define），与后端运行态对比可判断是否需重新构建前端
const FRONTEND_EDITION = typeof __EDITION__ !== 'undefined' ? __EDITION__ : 'unknown'

export default function EditionOps() {
  const { user } = useAuth()
  const isSuper = !!user?.is_super_admin
  const { message, modal } = App.useApp()

  const [current, setCurrent] = useState(null)
  const [loadingCurrent, setLoadingCurrent] = useState(false)
  const [target, setTarget] = useState(null)
  const [preview, setPreview] = useState(null)
  const [loadingPreview, setLoadingPreview] = useState(false)
  const [switching, setSwitching] = useState(false)
  const [restarting, setRestarting] = useState(false)
  const pollAbort = useRef(false)

  const loadCurrent = useCallback(async () => {
    setLoadingCurrent(true)
    try {
      const d = await http.get('/admin/edition-ops/current')
      setCurrent(d)
    } catch (e) {
      /* 拦截器已提示 */
    } finally {
      setLoadingCurrent(false)
    }
  }, [])

  useEffect(() => {
    if (isSuper) loadCurrent()
  }, [isSuper, loadCurrent])

  useEffect(() => () => { pollAbort.current = true }, [])

  const doPreview = async () => {
    if (!target) { message.warning('请先选择目标形态'); return }
    setLoadingPreview(true)
    setPreview(null)
    try {
      const d = await http.post('/admin/edition-ops/preview', { target })
      setPreview(d)
    } catch (e) {
      /* 拦截器已提示 */
    } finally {
      setLoadingPreview(false)
    }
  }

  // 免登录轮询 /api/edition：重启中断期 fetch 会失败，静默重试直至形态翻转或超时
  const pollEdition = async (expect, prevRuntime) => {
    const deadline = Date.now() + 90000
    while (Date.now() < deadline) {
      if (pollAbort.current) return null
      await new Promise((r) => setTimeout(r, 2000))
      try {
        const r = await fetch('/api/edition', { cache: 'no-store' })
        if (!r.ok) continue
        const j = await r.json()
        const ed = j?.data?.edition
        if (ed && ed !== prevRuntime) return ed
        if (ed === expect) return ed
      } catch (e) {
        /* 服务中断窗口，继续轮询 */
      }
    }
    return null
  }

  const doSwitch = () => {
    if (!preview || !preview.ok_to_switch) { message.warning('请先执行预览且预检通过'); return }
    let confirmText = ''
    modal.confirm({
      title: `切换部署形态 → ${label(target)}`,
      icon: <SwapOutlined />,
      width: 520,
      content: (
        <div>
          <Paragraph>此操作将把 <Text code>backend/.env</Text> 中的 EDITION 改为 <Text code>{target}</Text>（仅写文件，需重启后生效）。</Paragraph>
          {preview.warnings?.length > 0 && (
            <Alert type="warning" showIcon style={{ marginBottom: 8 }}
              message={<ul style={{ margin: 0, paddingLeft: 18 }}>{preview.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>} />
          )}
          <Paragraph>请输入目标形态名 <Text code>{target}</Text> 以确认：</Paragraph>
          <Input placeholder={target} onChange={(e) => { confirmText = e.target.value }} />
        </div>
      ),
      okText: '确认切换',
      okButtonProps: { danger: true },
      onOk: async () => {
        if (confirmText.trim().toLowerCase() !== target) {
          message.error('确认文本与目标形态不一致，已取消')
          throw new Error('confirm-mismatch')
        }
        setSwitching(true)
        try {
          const d = await http.post('/admin/edition-ops/switch', { target, confirm: confirmText.trim().toLowerCase() })
          message.success(`已写入 .env（EDITION=${d.env_file_edition}），运行时仍为 ${d.runtime_edition}，需重启生效`)
          setPreview(null)
          loadCurrent()
        } catch (e) {
          /* 拦截器已提示（含预检失败 409） */
          throw e
        } finally {
          setSwitching(false)
        }
      },
    })
  }

  const doRestart = () => {
    modal.confirm({
      title: '一键受控重启后端',
      icon: <SyncOutlined spin={restarting} />,
      content: (
        <div>
          <Paragraph>将以 <Text code>backend/.env</Text> 中的 EDITION=<Text code>{current?.env_file_edition}</Text> 重新拉起后端进程，<Text strong>服务中断数秒</Text>，所有进行中的请求将失败。</Paragraph>
          <Paragraph type="secondary">重启完成后本页会自动轮询 /api/edition 直至新形态生效。</Paragraph>
        </div>
      ),
      okText: '确认重启',
      okButtonProps: { danger: true },
      onOk: async () => {
        setRestarting(true)
        const prevRuntime = current?.runtime_edition
        try {
          const d = await http.post('/admin/edition-ops/restart', {})
          message.info(`新进程 pid=${d.new_pid} 拉起中，日志：${d.log}`)
          const ed = await pollEdition(d.edition, prevRuntime)
          if (ed) {
            message.success(`重启完成，当前形态：${label(ed)}`)
          } else {
            message.warning('轮询超时：请 1 分钟后手动刷新本页确认服务状态')
          }
        } catch (e) {
          /* 自杀瞬间本进程连接断开属预期，转轮询确认可达性 */
          const ed = await pollEdition(target || current?.env_file_edition, prevRuntime)
          if (ed) message.success(`重启完成，当前形态：${label(ed)}`)
          else message.error('未能确认服务恢复，请检查后端日志')
        } finally {
          setRestarting(false)
          loadCurrent()
        }
      },
    })
  }

  if (!isSuper) {
    return <Alert type="warning" showIcon message="本页面仅超级管理员可操作" description="如需切换部署形态，请联系部署运维人员。" />
  }

  const impact = preview?.impact
  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card
        title="当前部署形态"
        extra={<Button icon={<ReloadOutlined />} onClick={loadCurrent} loading={loadingCurrent}>刷新</Button>}
      >
        {loadingCurrent && !current ? <Spin /> : current && (
          <Descriptions column={2} size="small" bordered>
            <Descriptions.Item label="运行时形态（进程）">
              <Tag color={current.runtime_edition === current.env_file_edition ? 'green' : 'orange'}>{label(current.runtime_edition)}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label=".env 声明形态">
              <Tag>{label(current.env_file_edition || '（未声明）')}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="前端构建常量" span={2}>
              <Tag color={FRONTEND_EDITION === current.runtime_edition ? 'green' : 'purple'}>{label(FRONTEND_EDITION)}</Tag>
              {FRONTEND_EDITION !== current.runtime_edition && (
                <Text type="warning"> 前端为构建期常量，与后端不一致时需重新构建/重启前端 dev server（注入 EDITION 环境变量）。</Text>
              )}
            </Descriptions.Item>
            <Descriptions.Item label="漂移检测" span={2}>
              {current.drift
                ? <Alert type="warning" showIcon message={current.drift_hint} style={{ padding: '2px 10px' }} />
                : <Text type="secondary">无漂移（.env 与运行时一致）</Text>}
            </Descriptions.Item>
            <Descriptions.Item label="商业模块挂载">{current.commercial_mounted ? <Tag color="blue">已挂载</Tag> : <Tag>未挂载</Tag>}</Descriptions.Item>
            <Descriptions.Item label="导航档（NAV_PROFILE）"><Text code>{current.nav_profile}</Text></Descriptions.Item>
            <Descriptions.Item label="License" span={2}>
              {current.license?.valid
                ? <Space><Tag color="green">有效</Tag><Text type="secondary">到期 {current.license.expires_at || '—'} / 阶段 {current.license.phase || '—'}</Text></Space>
                : <Space><Tag color="red">无效</Tag><Text type="secondary">{current.license?.reason || '—'}</Text></Space>}
            </Descriptions.Item>
          </Descriptions>
        )}
      </Card>

      <Card title="形态切换预览与执行">
        <Space wrap style={{ marginBottom: 12 }}>
          <Text>目标形态：</Text>
          <Select
            style={{ width: 220 }}
            placeholder="选择目标形态"
            value={target}
            onChange={(v) => { setTarget(v); setPreview(null) }}
            options={(current?.allowed_editions || ['community', 'saas', 'enterprise']).map((v) => ({ value: v, label: label(v) }))}
          />
          <Button onClick={doPreview} loading={loadingPreview} disabled={!target}>预览影响</Button>
          <Tooltip title={preview ? (preview.ok_to_switch ? '将目标形态写入 .env（需重启生效）' : '预检未通过，禁止切换') : '请先执行预览'}>
            <Button danger icon={<SwapOutlined />} disabled={!preview || !preview.ok_to_switch} loading={switching} onClick={doSwitch}>切换（写 .env）</Button>
          </Tooltip>
          <Tooltip title="以 .env 当前声明重新拉起后端进程（中断数秒）">
            <Button icon={<SyncOutlined />} loading={restarting} onClick={doRestart}>一键重启</Button>
          </Tooltip>
        </Space>

        {loadingPreview && <Spin style={{ display: 'block', margin: '12px auto' }} />}
        {preview && (
          <div>
            {preview.checks?.map((c) => (
              <Alert key={c.key} type={c.ok ? 'success' : 'error'} showIcon style={{ marginBottom: 8 }}
                message={`${c.label}：${c.detail}`} />
            ))}
            {impact && (
              <Descriptions column={1} size="small" bordered style={{ marginBottom: 12 }}>
                <Descriptions.Item label="切换后商业模块">
                  {impact.commercial_mounted_after ? <Tag color="blue">挂载</Tag> : <Tag>断开（社区版）</Tag>}
                  {impact.platform_available_after !== undefined && <> 平台运营区：{impact.platform_available_after ? <Tag color="blue">可用</Tag> : <Tag>不可用</Tag>}</>}
                </Descriptions.Item>
                <Descriptions.Item label={`功能模块（${impact.modules_after?.length ?? 0} 项）`}>
                  {impact.modules_lost?.length > 0 && (
                    <div style={{ marginBottom: 4 }}>
                      <Text type="danger">失去：</Text>
                      {impact.modules_lost.map((m) => <Tag key={m} color="red" style={{ marginBottom: 2 }}>{m}</Tag>)}
                    </div>
                  )}
                  {impact.modules_gained?.length > 0 && (
                    <div><Text type="success">获得：</Text>{impact.modules_gained.map((m) => <Tag key={m} color="green" style={{ marginBottom: 2 }}>{m}</Tag>)}</div>
                  )}
                  {(!impact.modules_lost?.length && !impact.modules_gained?.length) && <Text type="secondary">模块集无变化</Text>}
                </Descriptions.Item>
                <Descriptions.Item label="切换后关闭的导航项">
                  {impact.nav_flags_off_after?.length > 0
                    ? impact.nav_flags_off_after.map((f) => <Tag key={f} style={{ marginBottom: 2 }}>{f}</Tag>)
                    : <Text type="secondary">无（全部导航保留）</Text>}
                </Descriptions.Item>
              </Descriptions>
            )}
            {preview.warnings?.length > 0 && preview.warnings.map((w, i) => (
              <Alert key={i} type="warning" showIcon message={w} style={{ marginBottom: 6 }} />
            ))}
          </div>
        )}
        <Paragraph type="secondary" style={{ marginBottom: 0 }}>
          说明：EDITION 为部署形态（环境变量 + backend/.env + 进程重启决定），切换与重启操作均写入审计日志（admin.edition_switch / admin.edition_restart）。
        </Paragraph>
      </Card>
    </Space>
  )
}
