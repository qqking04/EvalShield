/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import React, { useEffect, useMemo, useRef, useState } from 'react'
import {
  Alert, Badge, Breadcrumb, Button, Input, Modal, Radio, Space, Spin, Tag, Typography, message,
} from 'antd'
import { CopyOutlined } from '@ant-design/icons'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { getUat, signUat, rejectUat, shareUat } from '../../api/uat'
import { useAuth } from '../../auth'
import UatSections, { SECTION_TITLES, VERDICT_COLOR, VERDICT_CN } from './UatSections'
import UatWizard from './UatWizard'
import UatExportButton from './UatExportButton'
import './uat.css'

const STATUS_META = {
  DRAFT: { text: '草稿', color: 'default' },
  VENDOR_SIGNED: { text: '等待客签', color: 'blue' },
  FINALIZED: { text: '已归档', color: 'green' },
  REJECTED: { text: '已拒收', color: 'red' },
}

export default function UatReportDetail() {
  const { reportId } = useParams()
  const [searchParams] = useSearchParams()
  const projectId = Number(searchParams.get('project')) || null
  const navigate = useNavigate()
  const { user } = useAuth()
  const [detail, setDetail] = useState(null)
  const [loading, setLoading] = useState(true)
  const [signOpen, setSignOpen] = useState(false)
  const [signVerdict, setSignVerdict] = useState('PASSED')
  const [signName, setSignName] = useState('')
  const [signNote, setSignNote] = useState('')
  const [signing, setSigning] = useState(false)
  const [rejectOpen, setRejectOpen] = useState(false)
  const [rejectReason, setRejectReason] = useState('')
  const [shareUrl, setShareUrl] = useState('')
  const [shareExpires, setShareExpires] = useState('')
  const [shareBusy, setShareBusy] = useState(false)
  const [wizard, setWizard] = useState(false)
  const [activeSec, setActiveSec] = useState('uat-s1')
  const docRef = useRef(null)

  const load = () => {
    if (!projectId || !reportId) {
      setLoading(false)
      return
    }
    setLoading(true)
    getUat(projectId, reportId)
      .then((data) => setDetail(data))
      .catch(() => setDetail(null))
      .finally(() => setLoading(false))
  }

  useEffect(load, [projectId, reportId]) // eslint-disable-line react-hooks/exhaustive-deps

  // 目录高亮：IntersectionObserver 监听八节
  useEffect(() => {
    if (!detail || !docRef.current) return
    const els = Array.from(docRef.current.querySelectorAll('section[id^="uat-s"]'))
    if (!els.length) return
    const io = new IntersectionObserver(
      (entries) => {
        const vis = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)
        if (vis[0]) setActiveSec(vis[0].target.id)
      },
      { rootMargin: '-10% 0px -70% 0px' },
    )
    els.forEach((el) => io.observe(el))
    return () => io.disconnect()
  }, [detail])

  const status = detail?.acceptance?.status || 'DRAFT'
  const payload = detail?.content || {}
  const suggested = payload?.sections?.s5_gate?.verdict === 'PASSED' ? 'PASSED' : 'CONDITIONAL'

  const chainCrumb = useMemo(() => {
    const chain = detail?.chain || []
    // chain 是从 parent 逐级向前的近因链，反转为 v1 在前
    const items = [...chain].reverse().map((c) => ({
      title: c.id === detail.id ? `v${c.version}` : (
        <Typography.Link onClick={() => navigate(`/uat/${c.id}?project=${projectId}`)}>
          v{c.version} {STATUS_META[c.status]?.text || c.status}
        </Typography.Link>
      ),
    }))
    items.push({
      title: <span>当前 v{detail?.uat_version ?? 1}</span>,
    })
    return items
  }, [detail, navigate, projectId])

  if (loading) {
    return <div style={{ textAlign: 'center', padding: 80 }}><Spin /></div>
  }
  if (!detail) {
    return (
      <Alert
        type="error"
        showIcon
        message="验收报告不存在或无权访问"
        action={<Button size="small" onClick={() => navigate(-1)}>返回</Button>}
        style={{ margin: 24 }}
      />
    )
  }

  const doSign = async () => {
    if (!signName.trim()) {
      message.warning('签署人姓名必填')
      return
    }
    if (signVerdict === 'CONDITIONAL' && !signNote.trim()) {
      message.error('有条件通过必须填写豁免说明（note）')
      return
    }
    setSigning(true)
    try {
      await signUat(projectId, detail.id, {
        name: signName.trim(), verdict: signVerdict, note: signVerdict === 'CONDITIONAL' ? signNote.trim() : null,
      })
      message.success('已签署，等待客户确认')
      setSignOpen(false)
      load()
    } catch { /* 拦截器已提示 */ } finally {
      setSigning(false)
    }
  }

  const doReject = async () => {
    if (!rejectReason.trim()) {
      message.error('拒收理由必填')
      return
    }
    setSigning(true)
    try {
      await rejectUat(projectId, detail.id, { name: (user?.username || '').trim(), reason: rejectReason.trim() })
      message.success('已拒收，可基于此版整改后重生成新版本')
      setRejectOpen(false)
      load()
    } catch { /* 拦截器已提示 */ } finally {
      setSigning(false)
    }
  }

  const doShare = async () => {
    setShareBusy(true)
    try {
      const data = await shareUat(projectId, detail.id)
      setShareUrl(window.location.origin + (data?.url || ''))
      setShareExpires(data?.expires_at || '')
      message.success('客户签署链接已生成（单次使用，30 天有效）')
    } catch { /* 拦截器已提示 */ } finally {
      setShareBusy(false)
    }
  }

  const finalized = status === 'FINALIZED'
  const draftOrRejected = status === 'DRAFT' || status === 'REJECTED'

  return (
    <div style={{ paddingBottom: 72 }}>
      {/* 顶部：编号 + 状态徽标 + 版本链面包屑 */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16, flexWrap: 'wrap', gap: 8 }}>
        <Space size={12}>
          <Button size="small" onClick={() => navigate(projectId ? `/projects/${projectId}` : -1)}>返回</Button>
          <Typography.Title level={4} style={{ margin: 0 }}>{detail.report_no}</Typography.Title>
          <Badge className="uat-badge-anim" status={STATUS_META[status]?.color || 'default'} text={STATUS_META[status]?.text || status} />
          {detail.acceptance?.verdict && (
            <Tag color={VERDICT_COLOR[detail.acceptance.verdict] || 'default'}>
              {VERDICT_CN[detail.acceptance.verdict] || detail.acceptance.verdict}
            </Tag>
          )}
        </Space>
        <Space>
          {(detail.chain?.length > 0) && (
            <Breadcrumb items={chainCrumb} style={{ marginRight: 8 }} />
          )}
          <UatExportButton projectId={projectId} reportId={detail.id} reportNo={detail.report_no} status={status} />
        </Space>
      </div>

      <div style={{ display: 'flex', gap: 24, alignItems: 'flex-start' }}>
        {/* 左目录锚点栏 */}
        <nav className="uat-toc" aria-label="报告目录">
          {Object.entries(SECTION_TITLES).map(([k, title]) => {
            const id = `uat-${k.split('_')[0]}`
            return (
              <a
                key={id}
                id={`toc-${id}`}
                href={`#${id}`}
                className={activeSec === id ? 'active' : ''}
                onClick={(e) => {
                  e.preventDefault()
                  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' })
                }}
              >
                {title}
              </a>
            )
          })}
        </nav>

        {/* 右：纸张文档态 */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            ref={docRef}
            className={`uat-paper uat-doc${draftOrRejected ? ' uat-watermark' : ''}${status === 'REJECTED' ? ' uat-watermark-rejected' : ''}`}
          >
            <h1>{detail.title}</h1>
            <div className="uat-doc-sub">
              UAT 验收报告　v{detail.uat_version ?? 1}　生成于 {(detail.generated_at || '').slice(0, 19).replace('T', ' ')}
            </div>
            <UatSections payload={payload} />
          </div>
        </div>
      </div>

      {/* 吸底签核栏：终态整栏置灰锁定（disabled 非隐藏） */}
      <div className="uat-sign-bar">
        <Space>
          <Button
            type="primary"
            disabled={status !== 'DRAFT'}
            onClick={() => {
              setSignVerdict(suggested === 'PASSED' ? 'PASSED' : 'CONDITIONAL')
              setSignName(user?.username || '')
              setSignNote('')
              setSignOpen(true)
            }}
          >
            签署验收
          </Button>
          {status === 'DRAFT' && (
            <Button danger disabled onClick={() => message.info('供应商未签署前不可拒收')}>拒收</Button>
          )}
          {status === 'VENDOR_SIGNED' && (
            <Button danger onClick={() => { setRejectReason(''); setRejectOpen(true) }}>拒收</Button>
          )}
          {status === 'VENDOR_SIGNED' && !shareUrl && (
            <Button loading={shareBusy} onClick={doShare}>生成客户签署链接</Button>
          )}
          {finalized ? (
            <Button
              disabled={false}
              onClick={() => setWizard(true)}
            >
              基于此版重生成 v{(detail.uat_version ?? 1) + 1}
            </Button>
          ) : status === 'REJECTED' ? (
            <Button onClick={() => setWizard(true)}>整改重生成 v{(detail.uat_version ?? 1) + 1}</Button>
          ) : (
            <Button disabled>基于此版重生成</Button>
          )}
        </Space>
        {shareUrl && status === 'VENDOR_SIGNED' && (
          <Space style={{ marginLeft: 16 }}>
            <Typography.Text copyable={false} className="mono" style={{ fontSize: 12, maxWidth: 360, display: 'inline-block' }} ellipsis>
              {shareUrl}
            </Typography.Text>
            <Button
              size="small"
              icon={<CopyOutlined />}
              onClick={() => { navigator.clipboard?.writeText(shareUrl); message.success('链接已复制') }}
            >
              复制
            </Button>
            {shareExpires && (
              new Date(shareExpires).getTime() < Date.now() ? (
                <Tag color="red">链接已于 {new Date(shareExpires).toLocaleDateString('zh-CN')} 过期，请重新生成</Tag>
              ) : (
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  有效期至 {new Date(shareExpires).toLocaleString('zh-CN')}
                </Typography.Text>
              )
            )}
          </Space>
        )}
      </div>

      {/* 供应商签署 Modal */}
      <Modal
        title="签署验收（供应商）"
        open={signOpen}
        onOk={doSign}
        okText="签署验收"
        confirmLoading={signing}
        onCancel={() => setSignOpen(false)}
        destroyOnClose
      >
        <Space direction="vertical" style={{ width: '100%' }} size={12}>
          <div>
            <Typography.Text strong>验收结论　</Typography.Text>
            <Radio.Group value={signVerdict} onChange={(e) => setSignVerdict(e.target.value)}>
              <Radio value="PASSED">通过</Radio>
              <Radio value="CONDITIONAL">有条件通过</Radio>
            </Radio.Group>
          </div>
          {signVerdict === 'CONDITIONAL' && (
            <div className="uat-note-expand">
              <Input.TextArea
                rows={3}
                placeholder="有条件通过必须填写豁免说明（note）"
                value={signNote}
                onChange={(e) => setSignNote(e.target.value)}
              />
            </div>
          )}
          <Input
            addonBefore="签署人"
            value={signName}
            onChange={(e) => setSignName(e.target.value)}
            placeholder="签署人姓名"
          />
        </Space>
      </Modal>

      {/* 拒收 Modal（reason 必填） */}
      <Modal
        title="拒收验收报告"
        open={rejectOpen}
        onOk={doReject}
        okText="确认拒收"
        okButtonProps={{ danger: true }}
        confirmLoading={signing}
        onCancel={() => setRejectOpen(false)}
        destroyOnClose
      >
        <Input.TextArea
          rows={3}
          placeholder="拒收理由（必填，将留痕于 §8）"
          value={rejectReason}
          onChange={(e) => setRejectReason(e.target.value)}
        />
      </Modal>

      {/* 重生成向导（携原 task_ids，Step2 起步） */}
      <UatWizard
        open={wizard}
        mode="resample"
        projectId={projectId}
        reportId={detail.id}
        initialTaskIds={payload?.task_ids || []}
        onClose={() => setWizard(false)}
        onCreated={(rep) => {
          setWizard(false)
          if (rep?.id) navigate(`/uat/${rep.id}?project=${projectId}`)
          else load()
        }}
      />
    </div>
  )
}
