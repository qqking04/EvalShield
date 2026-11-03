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
import {
  Table, Button, Space, Tag, Modal, Form, Input, Select, App, Popconfirm, Typography, Alert, Drawer, Card, Row, Col, InputNumber, Tooltip, Empty,
} from 'antd'
import { PlusOutlined, ReloadOutlined, DeleteOutlined, EditOutlined, SearchOutlined, InfoCircleOutlined } from '@ant-design/icons'
import http from '../../api/http'
import { fmtTime } from '../../utils'
import { CASE_CATEGORY_MAP, DATASET_SOURCE_MAP, VISIBILITY_MAP } from '../../constants/enums'
import useDict from '../../hooks/useDict'
const { Text } = Typography

// P2-5：AI 生成数据集弹窗表单（ESM 语法，避免 require）
function AIForm({ projects, categoryOptions, onSubmit }) {
  const [form] = Form.useForm()
  const defaultProjectId = projects?.[0]?.id
  return (
    <Form form={form} layout="vertical" onFinish={onSubmit} initialValues={{ prompt: '登录场景，用户名密码', category: 'API', project_id: defaultProjectId }}>
      <Form.Item name="prompt" label="业务描述（必填）" rules={[{ required: true, message: '请输入业务描述' }]}>
        <Input.TextArea rows={3} placeholder="如：登录场景，用户名密码；订单查询场景；支付场景" />
      </Form.Item>
      <Form.Item name="project_id" label="项目" rules={[{ required: true, message: '请选择项目' }]}>
        <Select allowClear={false} options={(projects || []).map((p) => ({ value: p.id, label: `${p.code} - ${p.name}` }))} />
      </Form.Item>
      <Form.Item name="category" label="类别" initialValue="API">
        <Select options={categoryOptions} />
      </Form.Item>
      <div style={{ color: '#888', fontSize: 12 }}>
        提示：后端将根据业务描述自动提取参数列（如 username/phone/email/order_id），并生成 3 条<b>接近真实业务</b>的示例数据行，可直接用于数据驱动测试。如需更精确的数据，生成后点「编辑」手动补充。
      </div>
    </Form>
  )
}

// =====================================================================
// 数据行编辑器（数据集的实际测试数据）
//   parameters: [{name, type, example}]  参数列定义（表头）
//   value: [{列名: 值, ...}]             每一行为一组实际测试数据
//   用途：数据驱动测试时，引擎按 data_rows 逐行展开执行
// =====================================================================
function DatasetRowsEditor({ value = [], onChange, parameters = [] }) {
  const rows = Array.isArray(value) ? value : []
  // 参数列去重：避免重复列名导致渲染 key 冲突（React 复用 DOM/fiber，值绑定错乱）及字段互相覆盖
  const seen = new Set()
  const cols = (parameters || []).filter((p) => p && p.name && !seen.has(String(p.name).trim()) && seen.add(String(p.name).trim()))

  const setRow = (i, key, v) => {
    const next = rows.map((r, idx) => (idx === i ? { ...r, [key]: v } : r))
    onChange(next)
  }

  const addRow = () => {
    const empty = {}
    cols.forEach((c) => { empty[c.name] = c.type === 'number' ? 0 : c.type === 'boolean' ? true : (c.example != null ? c.example : '') })
    onChange([...rows, empty])
  }

  const removeRow = (i) => onChange(rows.filter((_, idx) => idx !== i))

  const renderCell = (col, row) => {
    const v = row[col.name]
    if (col.type === 'number') {
      return <InputNumber size="small" style={{ width: '100%' }} value={v} onChange={(x) => setRow(row.__i, col.name, x)} />
    }
    if (col.type === 'boolean') {
      return <Select size="small" style={{ width: '100%' }} value={v} allowClear
        options={[{ value: true, label: 'true 是' }, { value: false, label: 'false 否' }]}
        onChange={(x) => setRow(row.__i, col.name, x)} />
    }
    if (col.type === 'json') {
      return <Input size="small" style={{ width: '100%' }} value={typeof v === 'object' ? JSON.stringify(v) : v}
        onChange={(e) => { const t = e.target.value.trim(); let parsed = t; try { parsed = JSON.parse(t) } catch { parsed = t } setRow(row.__i, col.name, parsed) }} />
    }
    return <Input size="small" style={{ width: '100%' }} value={v} placeholder="输入值"
      onChange={(e) => setRow(row.__i, col.name, e.target.value)} />
  }

  return (
    <div style={{ width: '100%' }}>
      {cols.length === 0 && (
        <Alert type="warning" showIcon message="请先在「参数列定义」中添加至少一列（如 username），才能录入实际测试数据行。" />
      )}
      {cols.length > 0 && rows.length === 0 && (
        <Alert type="info" showIcon style={{ marginBottom: 8 }} message="点击下方「添加数据行」录入一组实际测试数据。每行对应一次数据驱动测试执行。" />
      )}
      {cols.length > 0 && (
        <Table
          size="small"
          rowKey="__i"
          dataSource={rows.map((r, i) => ({ ...r, __i: i }))}
          columns={[
            { title: '#', width: 36, align: 'center', render: (_, r) => r.__i + 1 },
            ...cols.map((c) => ({
              title: c.name,
              dataIndex: c.name,
              render: (v, r) => renderCell(c, r),
            })),
            {
              title: '', width: 44, align: 'center',
              render: (_, r) => <DeleteOutlined style={{ color: '#999' }} onClick={() => removeRow(r.__i)} />,
            },
          ]}
          pagination={false}
          scroll={{ x: 'max-content' }}
          footer={() => (
            <Button type="dashed" block icon={<PlusOutlined />} onClick={addRow}>添加数据行</Button>
          )}
        />
      )}
    </div>
  )
}

// 示例值只读展示（title 样式，不可填写；展示存储的示例值或提示文字）
function ExampleTitle({ value }) {
  const has = value !== undefined && value !== null && value !== ''
  return (
    <Text type={has ? undefined : 'secondary'}
      style={{ width: 170, display: 'inline-block', lineHeight: '32px', verticalAlign: 'middle' }}>
      {has ? String(value) : '示例值，如admin'}
    </Text>
  )
}

export default function DatasetsTab({ onDataChanged, initialProjectId }) {
  const { items: categoryOptions } = useDict('case_category')
  const [rows, setRows] = useState([])
  const [projects, setProjects] = useState([])
  const [allCases, setAllCases] = useState([])
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState(null)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()
  const { message } = App.useApp()
  // 监听参数列定义，数据行编辑器随列变化联动
  // 注意：data_rows 不依赖 Form.useWatch（该字段未注册 Form.Item，setFieldValue 不会触发 useWatch 通知），
  // 改用 React state 管理，确保「添加数据行」即时渲染
  const watchedParameters = Form.useWatch('parameters', form)
  const [dataRows, setDataRows] = useState([])

  const [drawerOpen, setDrawerOpen] = useState(false)
  const [currentDataset, setCurrentDataset] = useState(null)
  const [selectedCaseIds, setSelectedCaseIds] = useState([])
  const [drawerLoading, setDrawerLoading] = useState(false)

  // 新增：筛选 + 分页
  const [filters, setFilters] = useState({ project_id: initialProjectId || null, category: null })
  const [pagination, setPagination] = useState({ current: 1, pageSize: 10, total: 0 })

  const load = (p = pagination, extraParams = {}) => {
    const params = { page: p.current, page_size: p.pageSize, ...filters, ...extraParams }
    Object.keys(params).forEach((k) => { if (params[k] === null || params[k] === undefined || params[k] === '') delete params[k] })
    http.get('/datasets', { params }).then((d) => {
      const wrapper = d && d.data ? d.data : d
      setRows(wrapper.items || [])
      setPagination((pp) => ({ ...pp, total: wrapper.total || 0 }))
    }).catch((e) => console.warn(`[DatasetsTab] load failed`, e?.message || e))
  }

  useEffect(() => {
    load()
    http.get('/projects', { params: { page_size: 100 } }).then((d) => setProjects(d.items || [])).catch((e) => console.warn(`[DatasetsTab]`, e?.message || e))
  }, [])

  // FE-06：父组件项目筛选变化时，重置内部类别筛选并回到第 1 页
  useEffect(() => {
    if (initialProjectId !== undefined) {
      const nf = { project_id: initialProjectId || null, category: null }
      setFilters(nf)
      const np = { ...pagination, current: 1 }
      setPagination(np)
      // load 读取的是 state，用显式参数覆盖避免闭包旧值
      const params = { page: 1, page_size: np.pageSize }
      if (initialProjectId) params.project_id = initialProjectId
      http.get('/datasets', { params }).then((d) => {
        const wrapper = d && d.data ? d.data : d
        setRows(wrapper.items || [])
        setPagination((pp) => ({ ...pp, total: wrapper.total || 0 }))
      }).catch((e) => { setRows([]); console.warn('[DatasetsTab] project switch load failed', e?.message || e) })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialProjectId])

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    setDataRows([])
    setModalOpen(true)
  }

  const openEdit = async (row) => {
    setEditing(row)
    form.resetFields()
    let detail = row
    try {
      const d = await http.get(`/datasets/${row.id}`)
      detail = d && d.data ? d.data : (d || row)
    } catch (e) { console.warn('[DatasetsTab] 数据集详情加载失败', e?.message || e) }
    form.setFieldsValue({
      project_id: detail.project_id,
      name: detail.name,
      category: detail.category,
      description: detail.description,
      parameters: Array.isArray(detail.parameters) ? detail.parameters : [],
    })
    setDataRows(Array.isArray(detail.data_rows) ? detail.data_rows : [])
    setModalOpen(true)
  }

  const notifyChanged = () => { if (typeof onDataChanged === 'function') onDataChanged() }

  const submit = async () => {
    const values = await form.validateFields()
    // 数据行必填：至少录入一条实际测试数据才能保存
    if (!Array.isArray(dataRows) || dataRows.length === 0) {
      message.error('请至少录入一条「数据行（实际测试数据）」才能保存数据集')
      return
    }
    // 参数列名唯一性兜底校验（防止重复列名导致数据行输入错乱）
    const paramNames = (values.parameters || []).map((p) => (p && p.name ? String(p.name).trim() : '')).filter(Boolean)
    if (new Set(paramNames).size !== paramNames.length) {
      message.error('参数列定义存在重复列名（' + [...new Set(paramNames)].filter((n) => paramNames.indexOf(n) !== paramNames.lastIndexOf(n)).join('、') + '），请修改后再保存')
      return
    }
    const payload = { ...values, data_rows: dataRows, source: 'MANUAL' }
    setSaving(true)
    try {
      if (editing) {
        await http.put(`/datasets/${editing.id}`, payload)
        message.success('数据集已更新')
      } else {
        await http.post('/datasets', payload)
        message.success('数据集创建成功')
      }
      setModalOpen(false)
      load()
      notifyChanged()
    } catch (err) {
      message.error('保存失败：' + (err?.message || '未知错误'))
    } finally {
      setSaving(false)
    }
  }

  const remove = async (rowId) => {
    await http.delete(`/datasets/${rowId}`)
    message.success('数据集已删除')
    load()
    notifyChanged()
  }

  // D-DEL-FE：批量删除 数据集
  const [selectedRowKeys, setSelectedRowKeys] = useState([])
  const batchRemove = async () => {
    const ids = selectedRowKeys
    if (!ids.length) return
    try {
      const r = await http.post('/datasets/batch-delete', { ids })
      message.success(`已删除 ${r?.deleted ?? ids.length} 条数据集`)
      setSelectedRowKeys([]); load()
    } catch (e) { console.warn(e) }
  }

  // FE-17：分页拉取项目用例池全部用例（后端 page_size ≤ 500，循环翻页避免截断）
  const fetchAllProjectCases = async (projectId) => {
    const pageSize = 500
    const all = []
    let p = 1
    for (;;) {
      const d = await http.get('/cases', { params: { project_id: projectId, page: p, page_size: pageSize } })
      const wrapper = d && d.data ? d.data : d
      const items = wrapper.items || []
      all.push(...items)
      const total = wrapper.total || 0
      if (items.length < pageSize || all.length >= total) break
      p += 1
    }
    return all
  }

  const openDrawer = async (dataset) => {
    setCurrentDataset(dataset)
    setDrawerOpen(true)
    setDrawerLoading(true)
    try {
      // 列表接口不返回 case_ids，先拉取详情获取最新绑定的用例
      let detail = dataset
      try {
        const d = await http.get(`/datasets/${dataset.id}`)
        detail = d && d.data ? d.data : (d || dataset)
      } catch (e) { console.warn('[DatasetsTab] 数据集详情加载失败', e?.message || e) }
      setCurrentDataset(detail)
      const casesData = await fetchAllProjectCases(detail.project_id)
      setAllCases(casesData)
      setSelectedCaseIds(detail.case_ids || [])
    } catch (err) {
      message.error('加载用例列表失败：' + (err?.message || '未知错误'))
    } finally {
      setDrawerLoading(false)
    }
  }

  const saveDataset = async (caseIds) => {
    if (!currentDataset) return
    setDrawerLoading(true)
    try {
      await http.put(`/datasets/${currentDataset.id}`, { ...currentDataset, case_ids: caseIds })
      message.success('数据集已更新')
      setCurrentDataset({ ...currentDataset, case_ids: caseIds, case_count: caseIds.length })
      setSelectedCaseIds(caseIds)
      load()
    } catch (err) {
      message.error('保存失败：' + (err?.message || '未知错误'))
    } finally {
      setDrawerLoading(false)
    }
  }

  const removeCaseFromDataset = async (caseId) => {
    await saveDataset(selectedCaseIds.filter((id) => id !== caseId))
  }

  // 抽屉中「编辑」入口：关闭抽屉并打开编辑弹窗（便于补充数据行等）
  const openEditFromDrawer = () => {
    if (!currentDataset) return
    setDrawerOpen(false)
    openEdit(currentDataset)
  }

  const drawerCaseOptions = allCases
    .filter((c) => !selectedCaseIds.includes(c.id))
    .map((c) => ({ value: c.id, label: `${c.case_no} - ${c.title}` }))

  const projectNameOf = (pid) => {
    const p = (projects || []).find((x) => x.id === pid)
    return p ? `${p.code} ${p.name}` : (pid ?? '-')
  }

  const columns = [
    { title: '数据集编号', dataIndex: 'code', width: 190 },
    { title: '名称', dataIndex: 'name', ellipsis: true },
    { title: '所属项目', dataIndex: 'project_id', width: 200, ellipsis: true, render: (v) => projectNameOf(v) },
    { title: '类别', dataIndex: 'category', width: 130, render: (v) => <Tag>{CASE_CATEGORY_MAP[v] || v}</Tag> },
    { title: '用例数', dataIndex: 'case_count', width: 90, align: 'center' },
    { title: '来源', dataIndex: 'source', width: 120, render: (v) => DATASET_SOURCE_MAP[v] || v },
    { title: '可见性', dataIndex: 'visibility', width: 110, render: (v) => VISIBILITY_MAP[v] || v },
    { title: '创建时间', dataIndex: 'created_at', width: 160, render: (v) => fmtTime(v) },
    {
      title: '操作', width: 240,
      render: (_, row) => (
        <Space size={0}>
          <Button type="link" size="small" onClick={() => openEdit(row)}>编辑</Button>
          <Button type="link" size="small" onClick={() => openDrawer(row)}>查看/编辑用例</Button>
          <Popconfirm title="确认删除该数据集？" onConfirm={() => remove(row.id)}>
            <Button type="link" size="small" danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const datasetCaseColumns = [
    { title: '用例编号', dataIndex: 'case_no', width: 180 },
    { title: '模块', dataIndex: 'module', width: 100, ellipsis: true, render: (v) => (v ? <Tag color="geekblue">{v}</Tag> : '-') },
    { title: '标题', dataIndex: 'title', ellipsis: true },
    { title: '类别', dataIndex: 'category', width: 110, render: (v) => <Tag>{CASE_CATEGORY_MAP[v] || v}</Tag> },
    { title: '操作', width: 80, align: 'center', render: (_, row) => <Button type="link" size="small" danger onClick={() => removeCaseFromDataset(row.id)}>移除</Button> },
  ]

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Alert type="info" showIcon
        message="数据集 = 一组用于数据驱动测试的用例集合 + 参数列（表头） + 数据行（实际测试数据）。新建时先定义「参数列定义」，再按列录入「数据行」，保存后点「查看/编辑用例」把项目用例绑定进来。"
        description="快速体验：新建数据集 → 参数列定义加 2 列（如 username/password，选类型 string）→ 数据行添加 2 组真实数据（admin/123456、test/654321）→ 保存 → 「查看/编辑用例」选几条用例 → 再点「编辑」或详情查看参数列与数据行是否正确回显。" />
      {/* 新增：筛选 Card */}
      <Card size="small" style={{ marginBottom: 0 }}>
        <Row gutter={[12, 12]} align="middle">
          <Col xs={24} sm={8} md={6}>
            <Select allowClear placeholder="按所属项目筛选" style={{ width: '100%' }} options={(projects || []).map((p) => ({ value: p.id, label: `${p.code} - ${p.name}` }))}
              value={filters.project_id} onChange={(v) => { setFilters((f) => ({ ...f, project_id: v })); setPagination((p) => ({ ...p, current: 1 })) }} />
          </Col>
          <Col xs={24} sm={8} md={6}>
            <Select allowClear placeholder="按类别筛选" style={{ width: '100%' }} options={categoryOptions}
              value={filters.category} onChange={(v) => { setFilters((f) => ({ ...f, category: v })); setPagination((p) => ({ ...p, current: 1 })) }} />
          </Col>
          <Col>
            <Space>
              <Button icon={<SearchOutlined />} type="primary" onClick={() => load()}>筛选</Button>
              <Button onClick={() => { setFilters({ project_id: null, category: null }); const np = { ...pagination, current: 1 }; setPagination(np); load(np, { project_id: undefined, category: undefined }) }}>重置</Button>
            </Space>
          </Col>
        </Row>
      </Card>
      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => load()}>刷新</Button>
          <Popconfirm title={`确认批量删除选中的 ${selectedRowKeys.length} 条数据集？`} disabled={!selectedRowKeys.length} onConfirm={batchRemove}>
            <Button danger icon={<DeleteOutlined />} disabled={!selectedRowKeys.length}>批量删除{selectedRowKeys.length > 0 ? ` (${selectedRowKeys.length})` : ''}</Button>
          </Popconfirm>
          <Button icon={<PlusOutlined />} onClick={() => {
            // P2-5：AI 生成数据集 — 简化为 Modal 确认后调用后端，后端直接落库
            Modal.confirm({
              title: 'AI 生成数据集',
              width: 600,
              okText: '生成', cancelText: '取消',
              content: <AIForm prompt="登录场景，用户名密码" projects={projects} categoryOptions={categoryOptions} onSubmit={async (v) => {
                const r = await http.post('/datasets/generate', v);
                message.success(`AI 生成成功：${r.data.name}（${r.data.parameters.length} 参数 / ${r.data.data_rows.length} 数据行）`);
                load();
              }} />,
            });
          }}>AI 生成数据集</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建数据集</Button>
        </Space>
      </div>
      <Table rowKey="id" columns={columns} dataSource={rows}
        rowSelection={{ selectedRowKeys, onChange: setSelectedRowKeys }}
        locale={{ emptyText: <Empty description="暂无数据集" image={Empty.PRESENTED_IMAGE_SIMPLE}><Space><Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建数据集</Button><Button icon={<PlusOutlined />} onClick={() => { Modal.confirm({ title: 'AI 生成数据集', width: 600, okText: '生成', cancelText: '取消', content: <AIForm prompt="登录场景，用户名密码" projects={projects} categoryOptions={categoryOptions} onSubmit={async (v) => { const r = await http.post('/datasets/generate', v); message.success(`AI 生成成功：${r.data.name}（${r.data.parameters.length} 参数 / ${r.data.data_rows.length} 数据行）`); load(); }} /> }) }}>AI 生成数据集</Button></Space></Empty> }}
        pagination={{ ...pagination, showSizeChanger: true, showTotal: (t) => `共 ${t} 条` }} onChange={(p) => { setPagination(p); load(p) }} />
      <Modal title={editing ? '编辑数据集' : '新建数据集'} open={modalOpen} onOk={submit} okText="保存" cancelText="取消" confirmLoading={saving} onCancel={() => setModalOpen(false)} destroyOnHidden width={900} styles={{ body: { maxHeight: '72vh', overflowY: 'auto' } }}>
        <Form form={form} layout="vertical">
          <Form.Item name="project_id" label="所属项目" rules={[{ required: true }]}>
            <Select options={(projects || []).map((p) => ({ value: p.id, label: `${p.code} - ${p.name}` }))} />
          </Form.Item>
          <Form.Item name="name" label="数据集名称" rules={[{ required: true }]}>
            <Input placeholder="如：客服助手 RAG 正确性数据集" />
          </Form.Item>
          <Form.Item name="category" label="类别" rules={[{ required: true }]}>
            <Select options={categoryOptions} />
          </Form.Item>
          <Form.Item name="description" label="描述"><Input.TextArea rows={2} /></Form.Item>
          <Form.Item label="参数列定义" extra="参数列=数据集表头。供「测试用例」的测试数据编辑器从数据集参数列一键导入，生成参数模板（数据驱动测试）">
            <Form.List name="parameters">
              {(fields, { add, remove }) => (
                <Space direction="vertical" size={6} style={{ width: '100%' }}>
                  {fields.map((f) => (
                    <Space key={f.key} align="baseline" style={{ display: 'flex', flexWrap: 'wrap', rowGap: 6 }}>
                      <Form.Item name={[f.name, 'name']} noStyle rules={[
                        { required: true, message: '参数列名必填' },
                        {
                          validator: (_, v) => {
                            if (!v) return Promise.resolve()
                            const all = form.getFieldValue('parameters') || []
                            const same = all.filter((p) => p && p.name && String(p.name).trim() === String(v).trim()).length
                            return same > 1 ? Promise.reject(new Error('参数列名不能重复')) : Promise.resolve()
                          },
                        },
                      ]}>
                        <Input style={{ width: 170 }} placeholder="列名，如 username" />
                      </Form.Item>
                      <Form.Item name={[f.name, 'type']} noStyle>
                        <Select style={{ width: 130 }} placeholder="类型" allowClear
                          options={[
                            { value: 'string', label: 'string 字符串' },
                            { value: 'number', label: 'number 数值' },
                            { value: 'boolean', label: 'boolean 布尔' },
                            { value: 'json', label: 'json 对象' },
                          ]} />
                      </Form.Item>
                      <Form.Item name={[f.name, 'example']} noStyle>
                        <ExampleTitle />
                      </Form.Item>
                      <DeleteOutlined style={{ color: '#999' }} onClick={() => remove(f.name)} />
                    </Space>
                  ))}
                  <Button type="dashed" block icon={<PlusOutlined />} onClick={() => add({ name: '', type: 'string', example: '' })}>添加参数列</Button>
                </Space>
              )}
            </Form.List>
          </Form.Item>
          <Form.Item label="数据行（实际测试数据）" extra="每行一组真实取值，对应一次数据驱动执行。行中的列名须与参数列定义一致">
            <DatasetRowsEditor value={dataRows} onChange={setDataRows} parameters={watchedParameters} />
          </Form.Item>
        </Form>
      </Modal>

      <Drawer title={currentDataset ? `${currentDataset.code} - ${currentDataset.name}` : '数据集详情'} width={760} open={drawerOpen} onClose={() => setDrawerOpen(false)}>
        {currentDataset && (
          <Space direction="vertical" size={14} style={{ width: '100%' }}>
            <Alert type="info" showIcon
              message={<Text strong>什么是「数据集」？</Text>}
              description={
                <span style={{ fontSize: 12, lineHeight: 1.8 }}>
                  数据集 = <Text strong>用例集合</Text>（上方）+ <Text strong>参数列定义</Text>（表头）+ <Text strong>数据行</Text>（真实测试数据）。
                  执行时引擎会<b>用每一行数据分别跑一遍绑定的用例</b>（数据驱动测试）。例如参数列只有 <Text code>id</Text>、
                  数据行有 2 行，则每个用例执行 2 次（id=1、id=2）。
                </span>
              } />
            <Typography.Title level={5} style={{ margin: 0 }}>基本信息</Typography.Title>
            <Typography.Paragraph>
              <Text type="secondary">所属项目：</Text>{(projects.find((p) => p.id === currentDataset.project_id) || {}).name || currentDataset.project_id}
              {'　'}<Text type="secondary">类别：</Text><Tag>{CASE_CATEGORY_MAP[currentDataset.category] || currentDataset.category}</Tag>
              {'　'}<Text type="secondary">创建时间：</Text>{fmtTime(currentDataset.created_at)}
            </Typography.Paragraph>
            <Typography.Title level={5} style={{ margin: 0 }}>添加用例（从项目用例池多选）</Typography.Title>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8, fontSize: 13, color: '#869BAA' }}>
              <span>已选 <Typography.Text strong type="primary">{selectedCaseIds.length}</Typography.Text> 条 / 项目池共 {allCases.length} 条</span>
              {selectedCaseIds.length > 0 && <Button type="link" size="small" onClick={() => saveDataset([])} style={{ padding: 0 }}>清空全部</Button>}
            </div>
            {allCases.length === 0 && (
              <Alert type="warning" showIcon style={{ marginBottom: 8 }}
                message="项目池暂无用例。请先到「测试用例」Tab 为当前项目创建用例（如登录接口用例），保存后再回来「添加用例」绑定。" />
            )}
            <Select mode="multiple" allowClear style={{ width: '100%' }} placeholder="选择要添加到数据集的用例" loading={drawerLoading}
              options={drawerCaseOptions} onChange={(values) => saveDataset([...selectedCaseIds, ...values])} />
            <Typography.Title level={5} style={{ margin: 0 }}>用例列表（共 {selectedCaseIds.length} 条）</Typography.Title>
            <Table size="small" rowKey="id" loading={drawerLoading} columns={datasetCaseColumns}
              dataSource={allCases.filter((c) => selectedCaseIds.includes(c.id))} pagination={{ pageSize: 8, showSizeChanger: false }} />
            <Alert type="success" showIcon style={{ marginBottom: 4 }}
              message={<Text strong>正确用法（数据驱动测试工作流）</Text>}
              description={
                <span style={{ fontSize: 12, lineHeight: 1.8 }}>
                  ① 先在「参数列定义」添加业务列（如 <Text code>username</Text> / <Text code>password</Text> / <Text code>email</Text>）；
                  <br />② 在「数据行」录入多组<b>真实业务数据</b>（如 3 个真实用户：admin / tester01 / viewer02）；
                  <br />③ 上方绑定针对这些数据的用例（如「创建用户」「查询用户」）；
                  <br />④ 执行时引擎按数据行<b>逐行展开</b>：每行数据把用例跑一遍 —— 3 行数据 × N 条用例 = 3N 次测试。
                  <br /><Text type="warning">仅含 <Text code>id</Text> 列、数据行只有 1/2 是占位数据，建议补充业务列与真实数据行后再执行。</Text>
                </span>
              } />
            <Typography.Title level={5} style={{ margin: '12px 0 0' }}>参数列定义（数据驱动表头）</Typography.Title>
            {Array.isArray(currentDataset.parameters) && currentDataset.parameters.length > 0 ? (
              <Table size="small" rowKey={(_, i) => i} pagination={false}
                columns={[
                  { title: '参数列名', dataIndex: 'name', render: (v) => v || '-' },
                  { title: '类型', dataIndex: 'type', render: (v) => ({ string: 'string 字符串', number: 'number 数值', boolean: 'boolean 布尔', json: 'json 对象' }[v] || v || '-') },
                  { title: '示例值', dataIndex: 'example', render: (v) => (v !== undefined && v !== null ? String(v) : '-') },
                ]}
                dataSource={currentDataset.parameters} />
            ) : (
              <Text type="secondary">未配置参数列，暂无数据驱动表头。</Text>
            )}
            <Typography.Title level={5} style={{ margin: 0 }}>数据行（实际测试数据）</Typography.Title>
            {Array.isArray(currentDataset.data_rows) && currentDataset.data_rows.length > 0 ? (
              <Table size="small" rowKey={(_, i) => i} pagination={false}
                columns={(currentDataset.parameters || []).length > 0
                  ? (currentDataset.parameters || []).map((p) => ({ title: p.name, dataIndex: p.name, render: (v) => (v !== undefined && v !== null ? (typeof v === 'object' ? JSON.stringify(v) : String(v)) : '-') }))
                  : (() => {
                    const keys = Object.keys(currentDataset.data_rows[0] || {})
                    return keys.map((k) => ({ title: k, dataIndex: k, render: (v) => (v !== undefined && v !== null ? (typeof v === 'object' ? JSON.stringify(v) : String(v)) : '-') }))
                  })()}
                dataSource={currentDataset.data_rows} />
            ) : (
              <Space>
                <Text type="secondary">未录入数据行。</Text>
                <Button type="link" size="small" style={{ padding: 0 }} onClick={openEditFromDrawer}>点此打开「编辑」弹窗添加数据行</Button>
              </Space>
            )}
          </Space>
        )}
      </Drawer>
    </Space>
  )
}
