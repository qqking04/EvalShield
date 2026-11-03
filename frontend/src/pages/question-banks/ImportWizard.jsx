/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import { useEffect, useRef, useState } from 'react'
import { Modal, Steps, Upload, Button, Table, Tag, Typography, Alert, Progress, Space, message } from 'antd'
import { InboxOutlined } from '@ant-design/icons'
import * as api from '../../api/questionBanks'
import tokens from '../../theme/tokens'

// ES9-P-09（§4.1.3）：导入向导 —— Modal Steps 3 步（选择文件 → 导入执行 → 结果确认）。
// 轮询 GET /api/question-imports/:job（2s 间隔），组件卸载以 AbortController 取消在途请求。
const { Dragger } = Upload

export default function ImportWizard({ open, bankId, onClose, onDone }) {
  const [step, setStep] = useState(0)
  const [file, setFile] = useState(null)
  const [job, setJob] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const abortRef = useRef(null)

  // 卸载/关闭时终止轮询（含 setTimeout 排期与在途请求）
  const stopPolling = () => {
    clearTimeout(abortRef.current?.timer)
    abortRef.current?.abort()
    abortRef.current = null
  }
  useEffect(() => stopPolling, [])

  const reset = () => {
    stopPolling()
    setStep(0)
    setFile(null)
    setJob(null)
    setSubmitting(false)
  }

  const pollJob = (jobId) => {
    const ac = new AbortController()
    abortRef.current = ac
    const tick = async () => {
      if (ac.signal.aborted) return
      try {
        const data = await api.getImportJob(jobId, { signal: ac.signal })
        if (ac.signal.aborted) return
        setJob(data)
        if (data?.status === 'succeeded' || data?.status === 'failed') {
          setStep(2)
          if (data?.status === 'succeeded') onDone?.()
          // 同步到详情页「导入记录」Tab（会话内）
          window.dispatchEvent(new CustomEvent('es-question-import-done', { detail: { id: data?.job_id || jobId, ...data } }))
          return
        }
      } catch (e) {
        if (ac.signal.aborted || e?.name === 'CanceledError' || e?.code === 'ERR_CANCELED') return
      }
      // 2s 后再探
      abortRef.current = ac
      ac.timer = setTimeout(tick, 2000)
    }
    tick()
  }

  const handleUpload = async () => {
    if (!file) {
      message.warning('请先选择 CSV / JSONL 文件')
      return
    }
    setSubmitting(true)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const data = await api.createImport(bankId, fd)
      setStep(1)
      pollJob(data?.job_id || data?.id)
    } catch {
      /* 拦截器已提示 */
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal
      title="导入题目"
      open={open}
      onCancel={() => {
        reset()
        onClose()
      }}
      footer={
        step === 0
          ? [
              <Button key="c" onClick={() => { reset(); onClose() }}>取消</Button>,
              <Button key="u" type="primary" loading={submitting} disabled={!file} onClick={handleUpload}>
                开始导入
              </Button>,
            ]
          : step === 2
            ? [
                <Button key="f" type="primary" onClick={() => { reset(); onClose() }}>
                  完成
                </Button>,
              ]
            : null
      }
      destroyOnClose
      maskClosable={false}
    >
      <Steps
        size="small"
        current={step}
        style={{ marginBottom: 16 }}
        items={[{ title: '选择文件' }, { title: '导入执行' }, { title: '结果确认' }]}
      />
      {step === 0 && (
        <Dragger
          accept=".csv,.jsonl"
          maxCount={1}
          beforeUpload={(f) => {
            setFile(f)
            return false // 手动提交
          }}
          onRemove={() => setFile(null)}
        >
          <p className="ant-upload-drag-icon">
            <InboxOutlined style={{ color: tokens.primary }} />
          </p>
          <p style={{ color: tokens.text1 }}>点击或拖拽 CSV / JSONL 文件到此区域</p>
          <p style={{ color: tokens.text3, fontSize: 12 }}>
            列 schema：category, sub_category, attack_vector, split, text, expected_behavior, expected_answer, language, source, tags
          </p>
        </Dragger>
      )}
      {step === 1 && (
        <Space direction="vertical" style={{ width: '100%' }}>
          <Typography.Text style={{ color: tokens.text2 }}>
            状态：{job?.status === 'running' ? '解析入库中…' : job?.status === 'pending' ? '排队中…' : '等待进度…'}
          </Typography.Text>
          <Progress
            percent={job?.total ? Math.round(((job.processed ?? job.imported ?? 0) / job.total) * 100) : 0}
            status="active"
            strokeColor={tokens.primary}
          />
        </Space>
      )}
      {step === 2 && (
        <Space direction="vertical" style={{ width: '100%' }}>
          {job?.status === 'succeeded' ? (
            <Alert
              type="success"
              showIcon
              message={`导入完成：成功 ${job.imported ?? 0} 题${job.total ? ` / 共 ${job.total} 行` : ''}${job.duplicated ? `，去重 ${job.duplicated} 行` : ''}`}
            />
          ) : (
            <Alert type="error" showIcon message={`导入作业结束（${job?.status || 'unknown'}），请检查错误明细`} />
          )}
          {(job?.errors || []).length > 0 && (
            <Table
              size="small"
              rowKey={(r, i) => `${r.row}-${i}`}
              dataSource={job.errors}
              pagination={{ pageSize: 8, size: 'small' }}
              columns={[
                { title: '行号', dataIndex: 'row', key: 'row', width: 72 },
                {
                  title: '代码',
                  dataIndex: 'code',
                  key: 'code',
                  width: 120,
                  render: (v) => <Tag color="orange">{v}</Tag>,
                },
                {
                  title: '信息',
                  dataIndex: 'message',
                  key: 'message',
                  render: (v) => (
                    <Typography.Text style={{ color: tokens.text2 }} ellipsis={{ tooltip: v }}>
                      {v}
                    </Typography.Text>
                  ),
                },
              ]}
            />
          )}
        </Space>
      )}
    </Modal>
  )
}
