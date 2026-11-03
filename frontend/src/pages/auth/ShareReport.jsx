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
import { Card, Input, Button, Row, Col, Spin, Result, App, Statistic } from 'antd'
import { SafetyCertificateOutlined, UnlockOutlined, FileTextOutlined } from '@ant-design/icons'
import { useParams } from 'react-router-dom'
import ReactECharts from 'echarts-for-react'
import axios from 'axios'
import echartsDarkTheme from '../../theme/echarts'
import { fmtDateTimeUtc8 } from '../../utils/datetime'

// 公开请求（无 Authorization 头）
const pub = axios.create({ baseURL: '/api', timeout: 30000 })

function Chart({ title, option }) {
  const merged = { backgroundColor: 'transparent', ...option, tooltip: echartsDarkTheme.tooltip }
  return (
    <Card
      title={title}
      size="small"
      style={{ background: '#11161d', borderColor: '#1f2833', height: '100%' }}
    >
      <ReactECharts
        option={merged}
        style={{ height: 280, width: '100%' }}
        theme={{ ...echartsDarkTheme }}
        notMerge
      />
    </Card>
  )
}

function buildRadar(data) {
  const indicators = data?.indicators || (data?.map?.metrics || [])
  const series = data?.series || [
    { name: '本次', value: data?.values || [] },
  ]
  return {
    radar: {
      indicator: indicators.map((i) => ({ name: i.name || i, max: i.max || 100 })),
      axisLine: { lineStyle: { color: '#1f2833' } },
      splitLine: { lineStyle: { color: '#1f2833' } },
      splitArea: { show: false },
      axisName: { color: '#8ba3b5' },
    },
    series: [
      {
        type: 'radar',
        data: series.map((s, idx) => ({
          name: s.name || `系列${idx + 1}`,
          value: s.value,
          areaStyle: { opacity: 0.15 },
          lineStyle: { width: 2 },
        })),
      },
    ],
    color: echartsDarkTheme.color,
  }
}

function buildPie(data) {
  return {
    series: [
      {
        type: 'pie',
        radius: ['40%', '70%'],
        label: { color: '#8ba3b5' },
        data: data || [],
      },
    ],
    color: echartsDarkTheme.color,
  }
}

function buildBar(data) {
  return {
    grid: { left: 40, right: 20, top: 20, bottom: 40 },
    xAxis: { type: 'category', data: data?.x || [], axisLine: { lineStyle: { color: '#1f2833' } }, axisLabel: { color: '#8ba3b5' } },
    yAxis: { type: 'value', axisLine: { lineStyle: { color: '#1f2833' } }, axisLabel: { color: '#8ba3b5' }, splitLine: { lineStyle: { color: '#1f2833' } } },
    series: [{ type: 'bar', data: data?.y || [], itemStyle: { borderRadius: [2, 2, 0, 0] } }],
    color: echartsDarkTheme.color[0],
  }
}

function buildTrend(data) {
  return {
    grid: { left: 40, right: 20, top: 20, bottom: 40 },
    xAxis: { type: 'category', boundaryGap: false, data: data?.x || [], axisLine: { lineStyle: { color: '#1f2833' } }, axisLabel: { color: '#8ba3b5' } },
    yAxis: { type: 'value', axisLine: { lineStyle: { color: '#1f2833' } }, axisLabel: { color: '#8ba3b5' }, splitLine: { lineStyle: { color: '#1f2833' } } },
    series: [
      {
        type: 'line',
        smooth: true,
        areaStyle: { opacity: 0.15 },
        data: data?.y || [],
      },
    ],
    color: echartsDarkTheme.color[0],
  }
}

export default function ShareReport() {
  const { token } = useParams()
  const [loading, setLoading] = useState(true)
  const [report, setReport] = useState(null)
  const [status, setStatus] = useState('loading') // loading | ok | need_pwd | 404 | error
  const [pwd, setPwd] = useState('')
  const [unlocking, setUnlocking] = useState(false)
  const { message } = App.useApp()

  const load = async (withPwd) => {
    setLoading(true)
    try {
      const headers = withPwd ? { 'X-Share-Password': withPwd } : {}
      const resp = await pub.get(`/public/reports/${token}`, { headers, validateStatus: () => true })
      const data = resp.data
      if (resp.status === 401 && data?.code === 'ES-SHARE-0002') {
        setStatus('need_pwd')
      } else if (resp.status === 404 || data?.code === 'ES-SHARE-0001') {
        setStatus('404')
      } else if (resp.status >= 200 && resp.status < 300) {
        setReport(data?.data || data)
        setStatus('ok')
      } else {
        setStatus('error')
      }
    } catch {
      setStatus('error')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line
  }, [token])

  const doUnlock = async () => {
    if (!pwd) {
      message.error('请输入访问密码')
      return
    }
    setUnlocking(true)
    try {
      const resp = await pub.post(`/public/reports/${token}/unlock`, { password: pwd }, { validateStatus: () => true })
      if (resp.status === 200 || resp.data?.code === 0) {
        message.success('密码正确，正在加载报告')
        load(pwd)
      } else {
        message.error(resp.data?.message || '密码错误')
      }
    } catch {
      message.error('解锁失败')
    } finally {
      setUnlocking(false)
    }
  }

  return (
    <div style={{ minHeight: '100vh', background: '#0b0f14', color: '#e6f7ff' }}>
      {/* 独立顶栏，无侧边栏 */}
      <div className="share-topbar">
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <SafetyCertificateOutlined style={{ color: '#13c2c2', fontSize: 20 }} />
          <span style={{ fontWeight: 600 }}>EvalShield · 测试报告只读视图</span>
        </div>
        <span style={{ color: '#869BAA', fontSize: 12 }}>分享链接仅用于查看</span>
      </div>

      <div style={{ padding: 24 }}>
        {loading && (
          <div style={{ textAlign: 'center', paddingTop: 120 }}>
            <Spin size="large" tip="加载中..." />
          </div>
        )}

        {status === '404' && !loading && (
          <Result
            status="404"
            title="分享链接不存在"
            subTitle="该链接可能已过期、已被停用或地址输入有误。"
          />
        )}

        {status === 'error' && !loading && (
          <Result status="error" title="加载失败" subTitle="请稍后重试或联系分享者" />
        )}

        {status === 'need_pwd' && !loading && (
          <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 120 }}>
            <Card style={{ width: 420, background: '#11161d', borderColor: '#1f2833' }}>
              <div style={{ textAlign: 'center', marginBottom: 20 }}>
                <UnlockOutlined style={{ fontSize: 40, color: '#13c2c2' }} />
              </div>
              <h2 style={{ margin: 0, fontSize: 18, color: '#e6f7ff', borderLeft: '3px solid #13c2c2', paddingLeft: 10 }}>
                该报告已加密
              </h2>
              <p style={{ color: '#8ba3b5', fontSize: 13, marginTop: 8, paddingLeft: 13 }}>请输入分享者提供的访问密码</p>
              <Input.Password
                size="large"
                placeholder="访问密码"
                value={pwd}
                onChange={(e) => setPwd(e.target.value)}
                onPressEnter={doUnlock}
                style={{ marginTop: 16 }}
              />
              <Button
                type="primary"
                block
                size="large"
                loading={unlocking}
                onClick={doUnlock}
                style={{ marginTop: 12, background: '#13c2c2', borderColor: '#13c2c2', color: '#0b0f14', borderRadius: 2 }}
              >
                查看报告
              </Button>
            </Card>
          </div>
        )}

        {status === 'ok' && report && (
          <>
            {/* 报告头 */}
            <Card
              style={{ background: '#11161d', borderColor: '#1f2833', marginBottom: 16 }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 16 }}>
                <div>
                  <div style={{ fontSize: 12, color: '#869BAA', marginBottom: 4 }}>分享报告</div>
                  <h1 style={{ margin: 0, fontSize: 22, color: '#e6f7ff', borderLeft: '3px solid #13c2c2', paddingLeft: 10 }}>
                    {report.title || report.name || '测试报告'}
                  </h1>
                  <div style={{ marginTop: 8, color: '#8ba3b5', fontSize: 13 }}>
                    {report.project_name && <span style={{ marginRight: 16 }}>项目：{report.project_name}</span>}
                    {report.version_name && <span style={{ marginRight: 16 }}>版本：{report.version_name}</span>}
                    {report.generated_at && <span>生成时间：{fmtDateTimeUtc8(report.generated_at)}</span>}
                  </div>
                </div>
                {report.summary && (
                  <div className="mono" style={{ fontSize: 28, color: '#13c2c2', fontWeight: 600 }}>
                    {typeof report.summary === 'number'
                      ? `${report.summary}%`
                      : report.summary.pass_rate != null
                        ? `${report.summary.pass_rate}%`
                        : '—'}
                  </div>
                )}
              </div>
            </Card>

            {/* 四图 */}
            <Row gutter={[16, 16]}>
              <Col xs={24} lg={12}><Chart title="综合能力雷达" option={buildRadar(report.radar || report.quality)} /></Col>
              <Col xs={24} lg={12}><Chart title="结果分布" option={buildPie(report.pie || report.distribution)} /></Col>
              <Col xs={24} lg={12}><Chart title="指标对比" option={buildBar(report.bar || report.metrics)} /></Col>
              <Col xs={24} lg={12}><Chart title="通过率趋势" option={buildTrend(report.trend || report.history)} /></Col>
            </Row>

            {/* Summary */}
            {report.summary && typeof report.summary === 'object' && (
              <Card title="报告摘要" size="small" style={{ background: '#11161d', borderColor: '#1f2833', marginTop: 16 }}>
                <Row gutter={[16, 16]}>
                  {Object.entries(report.summary).map(([k, v]) => (
                    <Col key={k} xs={12} sm={6}>
                      <Statistic
                        title={k}
                        value={v}
                        valueStyle={{ color: '#13c2c2', fontFamily: '"JetBrains Mono", Consolas, monospace' }}
                      />
                    </Col>
                  ))}
                </Row>
              </Card>
            )}

            {/* 底部 */}
            <div style={{ marginTop: 24, textAlign: 'center', color: '#869BAA', fontSize: 12 }}>
              由 EvalShield 生成 · 查看次数 <span className="mono">{report.view_count ?? 'N'}</span>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
