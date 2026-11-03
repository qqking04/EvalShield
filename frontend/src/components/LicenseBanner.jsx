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
import { Alert, Button, Space, Upload, message } from 'antd'
import { KeyOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import http from '../api/http'
import { useAuth } from '../auth'
import { useEdition } from '../edition/EditionContext'

// 优化7 T7-7b/7c：License 全局引导条（与 T5 横幅同一组件，三态 + 未激活引导态复用）。
// - inactive：enterprise 形态且无生效 license → 显示机器指纹 +「复制给服务商」+ 上传 .lic；
// - grace / revoked：沿用 T5 橙/红横幅语义。
// community / saas 形态不渲染（无 license 概念）。
export default function LicenseBanner() {
  const { edition, license, refresh: refreshEdition } = useEdition()
  const { user } = useAuth()
  const navigate = useNavigate()
  const [status, setStatus] = useState(null) // /api/license/status（仅未激活探测用）
  const [activating, setActivating] = useState(false)

  const isEnterprise = edition === 'enterprise'
  const phase = license?.phase

  const loadStatus = useCallback(async () => {
    try {
      const d = await http.get('/license/status', { silent: true })
      setStatus(d)
    } catch {
      /* 接口不可达（community 构建等）→ 不显示引导 */
    }
  }, [])

  // 未激活判定：企业形态 + edition 探测里 license 无效 + status 接口确认可达
  const inactive =
    isEnterprise &&
    user?.is_super_admin &&
    (phase === undefined || phase === null || license?.valid === false) &&
    status &&
    (status.status === 'INACTIVE' || !status.license_no) &&
    status.edition === 'community' // 后端空态回落 community

  useEffect(() => {
    // 仅企业形态 + 超管 + license 探测为无效/无相位时才查状态接口；三态横幅走 /api/edition
    if (isEnterprise && user?.is_super_admin && (phase == null || license?.valid === false)) {
      loadStatus()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isEnterprise, user?.is_super_admin, phase, license?.valid])

  if (!isEnterprise || !user) return null

  const copyFp = async () => {
    const fp = status?.machine_fp || ''
    if (!fp) return
    try {
      await navigator.clipboard.writeText(fp)
      message.success('机器指纹已复制，发送给服务商获取 .lic 授权文件')
    } catch {
      message.info(fp)
    }
  }

  // antd5 Upload beforeUpload 首参即 File（与 LicenseAdmin 口径一致）
  const handleActivate = (file) => {
    const reader = new FileReader()
    reader.onload = async () => {
      setActivating(true)
      try {
        await http.post('/license/activate', { license_text: String(reader.result || '').trim() })
        message.success('License 激活成功')
        await Promise.all([loadStatus(), refreshEdition()])
      } catch {
        /* 拦截器已提示 */
      } finally {
        setActivating(false)
      }
    }
    reader.readAsText(file)
    return false // 阻止自动上传
  }

  if (inactive) {
    return (
      <Alert
        type="info"
        banner
        showIcon
        icon={<KeyOutlined />}
        message={
          <Space size={12} wrap style={{ width: '100%', justifyContent: 'space-between' }}>
            <span>
              企业版尚未激活。将机器指纹发送给服务商获取 <code>.lic</code> 授权文件后上传激活；
              也可直接前往{' '}
              <a onClick={() => navigate('/license')} style={{ fontWeight: 600 }}>
                License 管理
              </a>{' '}
              页。
            </span>
            <Space size={8}>
              {status?.machine_fp && (
                <Button size="small" onClick={copyFp}>
                  复制机器指纹
                </Button>
              )}
              <Upload accept=".lic,text/plain" showUploadList={false} beforeUpload={handleActivate}>
                <Button size="small" type="primary" icon={<KeyOutlined />} loading={activating}>
                  上传 .lic 激活
                </Button>
              </Upload>
            </Space>
          </Space>
        }
        style={{ padding: '8px 24px' }}
      />
    )
  }

  if (phase === 'grace') {
    return (
      <Alert
        type="warning"
        banner
        showIcon
        message={
          <span>
            授权已到期，处于 <strong>{license?.grace_remaining_days ?? 30}</strong> 天只读宽限期，系统暂停写入。
            请尽快在{' '}
            <a onClick={() => navigate('/license')} style={{ fontWeight: 600 }}>
              License 管理
            </a>{' '}
            页续证恢复全部功能。
          </span>
        }
        style={{ padding: '8px 24px' }}
      />
    )
  }

  if (phase === 'revoked') {
    return (
      <Alert
        type="error"
        banner
        showIcon
        message={
          user?.is_super_admin ? (
            <Space size={12} wrap style={{ width: '100%', justifyContent: 'space-between' }}>
              <span>
                授权已超宽限停服，仅超管可登录。请立即到{' '}
                <a onClick={() => navigate('/license')} style={{ fontWeight: 600 }}>
                  License 管理
                </a>{' '}
                页激活新证恢复系统。
              </span>
              <Upload accept=".lic,text/plain" showUploadList={false} beforeUpload={handleActivate}>
                <Button size="small" danger type="primary" icon={<KeyOutlined />} loading={activating}>
                  上传 .lic 激活
                </Button>
              </Upload>
            </Space>
          ) : (
            <span>授权已过期，系统已停服，请联系服务商续证。</span>
          )
        }
        style={{ padding: '8px 24px' }}
      />
    )
  }

  return null
}
