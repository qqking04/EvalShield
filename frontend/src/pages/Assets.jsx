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
import { Space, Typography, Card, Tabs, Row, Col, Statistic, Tag, Alert, Button, Collapse, Select, Empty, Progress } from 'antd'
import { useNavigate, useSearchParams } from 'react-router-dom'
import CasesTab from './assets/CasesTab'
import DatasetsTab from './assets/DatasetsTab'
import ScenariosTab from './assets/ScenariosTab'
import http from '../api/http'
import { CASE_CATEGORY_MAP } from '../constants/enums'
const { Text } = Typography

// 覆盖概览单模块卡片渲染
function CoverageModuleCard({ mod, onClick }) {
  const covered = !!mod?.covered
  const passRate = mod?.pass_rate
  return (
    <Card size="small"
      onClick={onClick}
      hoverable={!!onClick}
      style={{ borderColor: covered ? undefined : '#ef4444', borderWidth: covered ? undefined : 1 }}
      styles={{ body: { padding: 12 } }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <Text strong ellipsis style={{ maxWidth: 140 }}>{mod?.module || '-'}</Text>
        {covered
          ? <Tag color="success">已覆盖</Tag>
          : <Tag color="error">未覆盖</Tag>}
      </div>
      <div style={{ fontSize: 12, color: '#8b97a7', lineHeight: 1.9 }}>
        <div>用例 {mod?.case_count ?? 0} ｜ 数据集 {mod?.dataset_count ?? 0}</div>
        <div>场景 {mod?.scenario_count ?? 0} ｜ 评测集 {mod?.eval_set_count ?? 0}</div>
      </div>
      {passRate != null && (
        <Progress size="small" percent={Math.round(Number(passRate) * 100) || 0}
          status={covered ? 'success' : 'exception'}
          style={{ marginTop: 8 }} />
      )}
    </Card>
  )
}

export default function Assets() {
  const [stats, setStats] = useState(null)
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const [projects, setProjects] = useState([])
  const [projectIdFilter, setProjectIdFilter] = useState(null)
  const [coverage, setCoverage] = useState(null)
  const [coverageLoading, setCoverageLoading] = useState(false)
  const [activeTab, setActiveTab] = useState('cases')

  const loadStats = () => {
    http.get('/assets/stats')
      .then((d) => setStats(d && d.data ? d.data : d))
      .catch((e) => console.warn('[Assets] stats load failed', e?.message || e))
  }

  useEffect(() => {
    loadStats()
    http.get('/projects', { params: { page_size: 200 } }).then((d) => setProjects(d.items || [])).catch(() => {})
    // 读取 URL 上的 project_id 作为初始过滤
    const pid = searchParams.get('project_id')
    if (pid) setProjectIdFilter(Number(pid))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 功能覆盖概览：选择具体项目时加载
  useEffect(() => {
    if (!projectIdFilter) { setCoverage(null); return }
    let cancelled = false
    setCoverageLoading(true)
    http.get('/assets/coverage', { params: { project_id: projectIdFilter } })
      .then((d) => { if (!cancelled) setCoverage(d && d.data ? d.data : d) })
      .catch((e) => { if (!cancelled) setCoverage(null); console.warn('[Assets] coverage load failed', e?.message || e) })
      .finally(() => !cancelled && setCoverageLoading(false))
    return () => { cancelled = true }
  }, [projectIdFilter])

  const byCategory = (stats?.cases?.by_category) || {}

  const onProjectFilterChange = (val) => {
    setProjectIdFilter(val || null)
    const np = new URLSearchParams(searchParams)
    if (val) np.set('project_id', val)
    else np.delete('project_id')
    setSearchParams(np, { replace: true })
  }

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <Typography.Title level={4} style={{ margin: 0 }}>资产中心</Typography.Title>
        {/* 项目筛选（从 URL ?project_id=X 自动初始化） */}
        <Select
          allowClear showSearch
          placeholder="全部项目"
          value={projectIdFilter}
          style={{ minWidth: 260 }}
          options={projects.map((p) => ({ value: p.id, label: `${p.code} - ${p.name}` }))}
          filterOption={(input, opt) => String(opt.label || '').toLowerCase().includes(String(input).toLowerCase())}
          onChange={onProjectFilterChange}
        />
      </div>
      <Collapse
        ghost
        defaultActiveKey={['guide']}
        items={[{
          key: 'guide',
          label: <Text strong>新手测试引导：资产中心是做什么的？如何一步步测试？</Text>,
          children: (
            <Space direction="vertical" size={8} style={{ width: '100%' }}>
              <Alert type="info" showIcon message="资产中心用于管理你的「测试用例」「数据集」「数据流场景」三类核心资产，是发起测试任务前的素材准备区。下方统计卡片实时汇总各类资产数量。" />
              <Card size="small" title="建议测试顺序（跟着做就能完成整页验证）" styles={{ body: { padding: 8 } }}>
                <ol style={{ margin: 0, paddingLeft: 20, lineHeight: 1.9 }}>
                  <li><b>测试用例 Tab</b>：先「新建用例」→ 按类别填写内容 → 保存后列表出现 → 点「查看详情」确认只读展示 → 点「编辑」改一处保存 → 「导出/导入」JSON 验证往返一致 → 「快速执行」试跑一次 → 「删除」清理。</li>
                  <li><b>数据集 Tab</b>：新建数据集 → 在「参数列定义」添加列（如 username/password）→ 在「数据行」添加 2 行真实数据 → 保存 → 点「查看/编辑用例」把项目用例加进数据集 → 打开详情确认参数列与数据行正确展示。</li>
                  <li><b>数据流场景 Tab</b>：新建场景 → 依次添加 request→extract→assert 步骤，试试变量 {'{{}}'} 引用 → 保存后列表可见 → 编辑/删除验证。</li>
                  <li><b>评测集 Tab</b>：点「前往评测中心」，验证入口跳转正常，返回后点「刷新统计」看数字是否更新。</li>
                </ol>
              </Card>
            </Space>
          ),
        }]}
      />
      {stats && (
        <Card size="small">
          <Row gutter={[16, 16]}>
            <Col xs={8} sm={8} md={6}><Statistic title="测试用例" value={stats?.cases?.total || 0} /></Col>
            <Col xs={8} sm={8} md={6}><Statistic title="数据集" value={stats?.datasets?.total || 0} /></Col>
            <Col xs={8} sm={8} md={6}><Statistic title="数据流场景" value={stats?.scenarios?.total || 0} /></Col>
            <Col xs={8} sm={8} md={6}><Statistic title="评测集" value={stats?.eval_sets?.total || 0} /></Col>
            <Col xs={24} sm={24} md={12} style={{ display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
              <span style={{ fontSize: 13, color: '#869BAA', marginBottom: 6 }}>用例类别分布</span>
              <span>
                {Object.keys(byCategory).length === 0
                  ? <Tag>暂无</Tag>
                  : Object.entries(byCategory).map(([c, n]) => (
                    <Tag key={c} style={{ marginBottom: 4 }}>{CASE_CATEGORY_MAP[c] || c} × {n}</Tag>
                  ))}
              </span>
            </Col>
          </Row>
        </Card>
      )}
      {/* 功能覆盖概览 + 空态引导 */}
      <Card size="small" title="功能覆盖概览">
        {!projectIdFilter ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="请先在上方选择项目以查看功能覆盖矩阵">
            <Button onClick={() => { const pid = projects?.[0]?.id; if (pid) onProjectFilterChange(pid) }}>选择项目</Button>
          </Empty>
        ) : coverageLoading ? (
          <div style={{ textAlign: 'center', padding: 24, color: '#8b97a7' }}>覆盖矩阵加载中…</div>
        ) : coverage && (coverage.modules?.length || coverage.uncovered?.length) ? (
          <Row gutter={[12, 12]}>
            {(coverage.uncovered || []).map((m, i) =>
              <Col xs={24} sm={12} md={8} lg={6} key={`u-${i}`}><CoverageModuleCard mod={m} onClick={() => setActiveTab('cases')} /></Col>
            )}
            {(coverage.modules || []).map((m, i) =>
              <Col xs={24} sm={12} md={8} lg={6} key={`m-${i}`}><CoverageModuleCard mod={m} onClick={() => setActiveTab('cases')} /></Col>
            )}
          </Row>
        ) : (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="所选项目暂无功能覆盖数据">
            <Button onClick={() => setActiveTab('cases')}>去创建用例</Button>
          </Empty>
        )}
      </Card>
      <Card>
        <Tabs activeKey={activeTab} onChange={setActiveTab}
          items={[
            // FE-06：项目切换时以 projectId 为 key 重挂载子页，重置内部筛选（关键词/模块/状态/严重度）与分页
            { key: 'cases', label: '测试用例', children: <CasesTab key={`cases-${projectIdFilter ?? 'all'}`} onDataChanged={loadStats} initialProjectId={projectIdFilter} /> },
            { key: 'datasets', label: '数据集', children: <DatasetsTab key={`datasets-${projectIdFilter ?? 'all'}`} onDataChanged={loadStats} initialProjectId={projectIdFilter} /> },
            { key: 'scenarios', label: '数据流场景', children: <ScenariosTab key={`scenarios-${projectIdFilter ?? 'all'}`} onDataChanged={loadStats} initialProjectId={projectIdFilter} /> },
            {
              key: 'eval', label: '评测集',
              children: (
                <Space direction="vertical" size={12} style={{ width: '100%', padding: '24px 8px' }}>
                  <Alert type="info" showIcon message="评测集（评测样本 / 威胁样本）的创建、运行与对比在「评测中心」进行，此处提供入口与统计概览。" />
                  <Space wrap>
                    <Button type="primary" onClick={() => navigate('/eval')}>前往评测中心</Button>
                    <Button onClick={loadStats}>刷新统计</Button>
                  </Space>
                </Space>
              ),
            },
          ]}
        />
      </Card>
    </Space>
  )
}
