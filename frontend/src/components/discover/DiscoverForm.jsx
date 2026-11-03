/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import { useEffect, useState } from 'react'
import { Form, Select, Input, Button, Radio, Alert, Collapse, Space, Typography, Tooltip } from 'antd'
import { CompassOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import http from '../../api/http'
import { C, MONO } from './consoleTheme'

const { Text } = Typography

// 探索模式说明（产品视角：帮助用户理解三种模式的行为差异与风险）
const MODE_HELP = {
  READONLY: '仅只读浏览页面，收集自然触发的接口请求，绝不主动提交任何写操作。适合敏感/生产环境的首次摸底。',
  DISCOVER: '只读浏览 + 登录交互，登录后收集已登录态下的接口请求。适合绝大多数常规探测，无写风险。',
  MUTATE: '在只读基础上额外点开「新增 / 编辑」类表单收集字段定义，但依然不点最终提交按钮。可发现更多写接口，风险更高。',
}

// 环境下拉数据源 = GET /projects/{id}/environments（test_environments 表，契约 C13）
export default function DiscoverForm({ onSubmit, submitting, initialValues }) {
  const [form] = Form.useForm()
  const [projects, setProjects] = useState([])
  const [envs, setEnvs] = useState([])
  const [envLoading, setEnvLoading] = useState(false)
  const [err, setErr] = useState('')

  useEffect(() => {
    http
      .get('/projects', { params: { page: 1, page_size: 200 } })
      .then((d) => setProjects((d?.items || []).map((p) => ({ value: p.id, label: p.name }))))
      .catch(() => setErr('项目列表加载失败'))
  }, [])

  // D-03：重新探测预填——回填项目并加载其环境后选中原 url
  useEffect(() => {
    if (!initialValues?.project_id) return undefined
    let cancelled = false
    form.setFieldsValue({
      project_id: initialValues.project_id,
      ...(initialValues.discover_mode ? { discover_mode: initialValues.discover_mode } : {}),
    })
    http.get(`/projects/${initialValues.project_id}/environments`)
      .then((list) => {
        if (cancelled) return
        setEnvs((list || []).map((e) => ({ value: e.base_url, label: `${e.name}（${e.base_url}）` })))
        if (initialValues.url) form.setFieldValue('url', initialValues.url)
      })
      .catch(() => { if (!cancelled) setEnvs([]) })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialValues?.project_id])

  const onProjectChange = async (pid) => {
    form.setFieldValue('url', undefined)
    setEnvs([])
    if (!pid) return
    setEnvLoading(true)
    try {
      const list = await http.get(`/projects/${pid}/environments`)
      setEnvs((list || []).map((e) => ({ value: e.base_url, label: `${e.name}（${e.base_url}）` })))
    } catch {
      setEnvs([])
    } finally {
      setEnvLoading(false)
    }
  }

  const finish = (v) => {
    setErr('')
    if (!v.project_id || !v.url) {
      setErr('请选择项目与被测环境地址')
      return
    }
    onSubmit(v)
  }

  const selectStyle = { background: '#0d1420', borderColor: C.panelBorder, color: C.text }

  return (
    <Form form={form} layout="vertical" onFinish={finish} requiredMark={false}>
      {err && <Alert type="error" showIcon message={err} style={{ marginBottom: 12 }} />}
      <Space size="middle" wrap style={{ display: 'flex' }}>
        <Form.Item name="project_id" label={<span style={{ color: C.dim }}>目标项目</span>} rules={[{ required: true, message: '选择项目' }]} style={{ minWidth: 200 }}>
          <Select options={projects} placeholder="选择项目" onChange={onProjectChange} showSearch style={selectStyle} />
        </Form.Item>
        <Form.Item name="url" label={<span style={{ color: C.dim }}>被测环境（白名单内）</span>} rules={[{ required: true, message: '选择环境地址' }]} style={{ minWidth: 320 }}>
          <Select options={envs} loading={envLoading} placeholder="先选项目，再选已登记环境" style={selectStyle} />
        </Form.Item>
        <Form.Item
          name="discover_mode"
          label={<span style={{ color: C.dim }}>探索模式</span>}
          initialValue="DISCOVER"
          extra={
            <span style={{ color: C.dim, fontSize: 12, lineHeight: 1.6, display: 'block', maxWidth: 560 }}>
              只读：仅浏览页面，记录自然触发的请求，绝不主动提交写操作；标准：浏览 + 登录，收集登录态接口（默认推荐）；深度(写探测)：额外点开新增/编辑表单收集字段定义，仍不提交，可发现更多写接口。
            </span>
          }
        >
          <Radio.Group
            optionType="button"
            buttonStyle="solid"
            defaultValue="DISCOVER"
          >
            {[
              { v: 'READONLY', label: '只读' },
              { v: 'DISCOVER', label: '标准' },
              { v: 'MUTATE', label: '深度(写探测)' },
            ].map(({ v, label }) => (
              <Tooltip key={v} title={MODE_HELP[v]} placement="top">
                <Radio.Button value={v}>{label}</Radio.Button>
              </Tooltip>
            ))}
          </Radio.Group>
        </Form.Item>
      </Space>

      {/* 验证码 / 短信码输入位置说明（产品视角：用户最关心的入口） */}
      <div
        style={{
          display: 'flex', gap: 8, alignItems: 'flex-start',
          background: '#10161f', border: `1px solid ${C.panelBorder}`, borderRadius: 6,
          padding: '8px 12px', marginBottom: 12, fontSize: 12, color: C.dim,
        }}
      >
        <SafetyCertificateOutlined style={{ color: C.amber, marginTop: 1 }} />
        <span style={{ lineHeight: 1.6 }}>
          <Text style={{ color: C.amber, fontWeight: 600 }}>验证码 / 短信码在哪输入？</Text>
          {' '}探测过程中若目标系统出现图形验证码、短信验证码、滑块或扫码，页面会<b style={{ color: C.text }}>自动弹出「人机验证」窗口</b>，
          展示验证码图片并提示输入内容 —— 你直接在该窗口输入验证码/短信码，点「提交并继续」即可，无需事先准备。
          任务状态会显示「等待人工输入」。
        </span>
      </div>

      <Collapse
        ghost
        items={[
          {
            key: 'cred',
            label: <span style={{ color: C.dim, fontSize: 12 }}>高级登录（可选）：API Token / Cookie 直连，跳过浏览器；不填则由「人机验证」窗口在浏览器中手动登录</span>,
            children: (
              <Space size="middle" wrap style={{ display: 'flex' }}>
                <Form.Item name="api_key" label={<span style={{ color: C.dim }}>API Token（优先）</span>} tooltip="目标系统支持 Bearer Token 时填写，直接以该凭证探测，无需登录页交互">
                  <Input.Password placeholder="Bearer Token" style={{ ...selectStyle, minWidth: 220 }} autoComplete="new-password" />
                </Form.Item>
                <Form.Item name="cookie_header" label={<span style={{ color: C.dim }}>Cookie（次优先）</span>} tooltip="粘贴目标系统已登录 Cookie，直接复用会话探测">
                  <Input.Password placeholder="name=value; ..." style={{ ...selectStyle, minWidth: 220 }} autoComplete="new-password" />
                </Form.Item>
              </Space>
            ),
          },
        ]}
      />

      <Button
        type="primary"
        htmlType="submit"
        loading={submitting}
        icon={<CompassOutlined />}
        style={{ background: C.cyan, borderColor: C.cyan, fontWeight: 600, marginTop: 4 }}
      >
        启动自动探测
      </Button>
    </Form>
  )
}
