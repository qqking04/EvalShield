/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import { useCallback, useEffect, useState } from 'react'
import { Card, Col, Empty, Input, Modal, Form, Select, Space, Tag, Typography, Button, Popconfirm, message, Row, Alert, Pagination } from 'antd'
import { PlusOutlined, DatabaseOutlined, DeleteOutlined } from '@ant-design/icons'
import { useNavigate, useSearchParams } from 'react-router-dom'
import * as api from '../../api/questionBanks'
import tokens from '../../theme/tokens'

// ES9-P-09：题库列表页（/question-banks）——卡片栅格 + 新建库 Modal + 搜索。
// 空态文案带下一步动作（引导建库或导入）。
export default function QuestionBanksList() {
  const navigate = useNavigate()
  // 优化12 §8.3：门禁"补题"深链落地（/question-banks?sub=<GBT45654 子类编码>）——
  // 页面按库组织、不支持题级 category 过滤，以提示条定位子类并引导进入题库补题。
  const [searchParams] = useSearchParams()
  const subCode = searchParams.get('sub')
  const [data, setData] = useState({ items: [], total: 0 })
  const [loading, setLoading] = useState(false)
  const [keyword, setKeyword] = useState('')
  // Q-5：服务端分页（此前 page_size:60 硬编码，>60 条无法翻页）
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(12)
  const [createOpen, setCreateOpen] = useState(false)
  const [form] = Form.useForm()

  const load = useCallback(
    (kw, p = 1, ps = 12) => {
      setLoading(true)
      api
        .listBanks({ keyword: kw || undefined, page: p, page_size: ps })
        .then((resp) => {
          const items = Array.isArray(resp) ? resp : resp?.items || []
          setData({ items, total: resp?.total ?? items.length })
        })
        .catch(() => {})
        .finally(() => setLoading(false))
    },
    [],
  )

  useEffect(() => {
    load(keyword, page, pageSize)
  }, [load, keyword, page, pageSize])

  const handleCreate = async () => {
    const values = await form.validateFields()
    await api.createBank(values)
    message.success('题库已创建，可上传 CSV/JSONL 导入题目')
    setCreateOpen(false)
    form.resetFields()
    load(keyword, page, pageSize)
  }

  const handleDelete = async (id) => {
    await api.deleteBank(id)
    message.success('题库已删除')
    load(keyword, page, pageSize)
  }

  return (
    <div>
      {subCode && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message={`门禁“补题”指引：GBT45654 子类 ${subCode} 存在题量缺口`}
          description="进入下方题库详情页补充该子类题目（题目标注对应类别后纳入覆盖统计）；覆盖进度可在“合规对标”页查看。"
          action={
            <Button size="small" onClick={() => navigate('/standards/gbt45654')}>
              回到合规对标
            </Button>
          }
        />
      )}
      <Space style={{ marginBottom: 16, width: '100%', justifyContent: 'space-between' }}>
        <div>
          <Typography.Title level={4} style={{ margin: 0 }}>
            题库与覆盖度
          </Typography.Title>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            题库是发起评测的必经样本源（长期资产、看覆盖度）；评测中心「评测集」为一次性题集，两者独立。
          </Typography.Text>
        </div>
        <Space>
          <Input.Search
            allowClear
            placeholder="搜索题库名称"
            style={{ width: 240 }}
            onSearch={(v) => { setPage(1); setKeyword(v) }}
          />
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
            新建题库
          </Button>
        </Space>
      </Space>
      {!loading && data.items.length === 0 ? (
        <Card>
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={
              <Space direction="vertical">
                <Typography.Text style={{ color: tokens.text2 }}>还没有题库</Typography.Text>
                <Typography.Text style={{ color: tokens.text3 }}>
                  新建题库后，在详情页「导入记录」Tab 上传 TC260 模板 CSV/JSONL 即可开始评测
                </Typography.Text>
              </Space>
            }
          >
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
              创建第一个题库
            </Button>
          </Empty>
        </Card>
      ) : (
        <Row gutter={[16, 16]}>
          {data.items.map((bank) => (
            <Col key={bank.id} xs={24} sm={12} lg={8} xxl={6}>
              <Card
                hoverable
                loading={loading}
                onClick={() => navigate(`/question-banks/${bank.id}`)}
                styles={{ body: { minHeight: 132 } }}
              >
                <Space align="start">
                  <DatabaseOutlined style={{ fontSize: 22, color: tokens.primary, marginTop: 2 }} />
                  <div>
                    <Space>
                      <Typography.Text strong style={{ color: tokens.text1 }}>
                        {bank.name}
                      </Typography.Text>
                      {bank.is_builtin && <Tag color="cyan">内置</Tag>}
                    </Space>
                    <div style={{ color: tokens.text2, fontSize: 12, marginTop: 4 }}>
                      {bank.question_count ?? 0} 题
                      {bank.description ? ` · ${bank.description}` : ''}
                    </div>
                    <div style={{ color: tokens.text3, fontSize: 12, marginTop: 8 }}>
                      {bank.created_at ? String(bank.created_at).slice(0, 10) : ''}
                    </div>
                  </div>
                </Space>
                {!bank.is_builtin && (
                  <Popconfirm
                    title="删除题库将级联删除题目，确认？"
                    onConfirm={(e) => {
                      e?.stopPropagation()
                      handleDelete(bank.id)
                    }}
                    onCancel={(e) => e?.stopPropagation()}
                  >
                    <Button
                      size="small"
                      type="text"
                      danger
                      icon={<DeleteOutlined />}
                      style={{ position: 'absolute', top: 8, right: 8 }}
                      onClick={(e) => e.stopPropagation()}
                    />
                  </Popconfirm>
                )}
              </Card>
            </Col>
          ))}
        </Row>
      )}
      {data.total > pageSize && (
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 16 }}>
          <Pagination
            current={page}
            pageSize={pageSize}
            total={data.total}
            showSizeChanger
            showTotal={(t) => `共 ${t} 个题库`}
            onChange={(p, ps) => { setPage(p); setPageSize(ps) }}
          />
        </div>
      )}
      <Modal title="新建题库" open={createOpen} onOk={handleCreate} onCancel={() => setCreateOpen(false)} destroyOnClose>
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="题库名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input maxLength={128} placeholder="如：TC260 生成式风险题库 v1" />
          </Form.Item>
          <Form.Item name="description" label="说明">
            <Input.TextArea rows={2} maxLength={512} placeholder="题库用途与来源" />
          </Form.Item>
          <Form.Item name="language" label="语言" initialValue="zh">
            <Select
              options={[
                { value: 'zh', label: '中文' },
                { value: 'en', label: '英文' },
                { value: 'mixed', label: '混合' },
              ]}
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
