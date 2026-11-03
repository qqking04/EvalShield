# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""修复建议匹配器：根据引擎编码 / OWASP 类别 / 风险等级匹配标准化修复建议。

知识库优先级：
1. backend/data/security_recommendations.json（外置，可运维热更新）
2. 内置兜底表（文件缺失/损坏时保证报告始终有建议输出）
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger("evalshield.remediation")

_KB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "security_recommendations.json",
)


class RemediationMatcher:
    """修复建议匹配器（无数据库依赖，纯知识库驱动）。"""

    def __init__(self, kb_path: str | None = None):
        self._kb_path = kb_path or _KB_PATH
        self.knowledge_base: dict[str, Any] = self._load_knowledge_base()

    def _load_knowledge_base(self) -> dict[str, Any]:
        try:
            with open(self._kb_path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and data:
                return data
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("加载修复建议知识库失败: %s，使用内置默认值", e)
        return self._builtin_knowledge_base()

    @staticmethod
    def _builtin_knowledge_base() -> dict[str, Any]:
        return {
            "SECURITY_TEST": {
                "A01": {
                    "critical": "实施严格的身份验证和授权机制，确保所有受保护端点均需有效 Token。",
                    "high": "检查并修复越权漏洞，实施基于角色的访问控制（RBAC）。",
                    "medium": "增加权限校验日志，便于审计追踪。",
                },
                "A03": {
                    "critical": "启用参数化查询或 ORM，彻底杜绝 SQL 注入。",
                    "high": "对所有用户输入进行转义和过滤，启用 Content-Security-Policy 防止 XSS。",
                    "medium": "增加输入验证白名单机制。",
                },
                "A05": {
                    "critical": "关闭调试端点与详细报错回显，生产环境禁用目录列表与默认凭证。",
                    "high": "收敛安全配置基线：移除未使用的功能、端口与默认账号，敏感信息不落日志。",
                    "medium": "定期核对配置项与 CIS 基线差异并整改。",
                },
                "A06": {
                    "critical": "立即升级存在已知漏洞的组件版本，并对受影响接口做临时虚拟补丁。",
                    "high": "建立依赖清单（SBOM），升级含漏洞组件至安全版本并回归验证。",
                    "medium": "接入依赖漏洞扫描（SCA），纳入 CI 定期检测过期组件。",
                },
                "A07": {
                    "critical": "重构认证流程：强制多因素认证、失效会话管理与登录失败锁定。",
                    "high": "修复凭证填充弱点：启用验证码/速率限制，密码策略符合复杂度要求。",
                    "medium": "补充认证事件审计日志，监控异常登录行为。",
                },
            },
            "HTTP_SECURITY_HEADERS": {
                "critical": "立即为全站启用 HSTS 与 CSP，杜绝降级明文访问与任意脚本注入。",
                "high": "补齐安全响应头：Strict-Transport-Security、Content-Security-Policy、X-Frame-Options、X-Content-Type-Options、Referrer-Policy。",
                "medium": "在网关/反向代理统一注入安全响应头，并纳入上线检查清单。",
            },
            "TLS_CHECK": {
                "critical": "证书无效或已过期将导致传输不可信，立即更换证书并校验证书链完整性。",
                "high": "禁用 SSLv3/TLS 1.0/1.1 与 RC4/DES/3DES 等弱算法，仅保留 TLS 1.2+ 强加密套件。",
                "medium": "配置证书到期自动监控与续期机制，避免临期未感知。",
            },
            "STATIC_SECRET_SCAN": {
                "critical": "前端泄露高权限密钥（如私钥/AWS Key）应立即吊销并轮换，排查泄露面。",
                "high": "移除 JS 中硬编码的 API Key/Token/密码，改为服务端签发短期凭证；对已泄露密钥执行轮换。",
                "medium": "在 CI 中加入密钥扫描（如 gitleaks）阻断硬编码密钥进入前端产物。",
            },
            "RBAC_TEST": {
                "critical": "存在系统性越权放行，立即在所有受保护接口强制服务端鉴权并复核权限模型。",
                "high": "修复越权接口：按角色白名单校验访问权限，未授权请求返回 401/403。",
                "medium": "补齐鉴权矩阵测试用例，将 RBAC 校验纳入接口回归。",
            },
            "CREDENTIAL_STORAGE_TEST": {
                "critical": "凭证以明文存储于前端且无 HttpOnly 保护，立即改为 HttpOnly+Secure Cookie 会话。",
                "high": "勿在 localStorage 存放 Token/密码：改用 HttpOnly Cookie 或内存态短期令牌，防 XSS 窃取。",
                "medium": "为会话 Cookie 增加 Secure/SameSite 属性，缩短令牌有效期。",
            },
            "PUBLIC_ENDPOINT_TEST": {
                "critical": "公开接口存在未授权数据批量导出能力，立即加鉴权与速率限制并评估泄露影响。",
                "high": "为公开端点补充参数校验与最小权限返回，禁止未授权访问敏感字段。",
                "medium": "对公开接口做响应字段脱敏与分页上限约束。",
            },
            "FUNCTIONAL_DEFECT_TEST": {
                "critical": "业务数据缺陷涉及资金/核心单据一致性，立即止血并数据修复。",
                "high": "修复业务逻辑缺陷：补齐输入校验、状态机约束与幂等处理，并回归验证。",
                "medium": "补充业务场景用例覆盖边界数据组合，纳入每日回归。",
            },
            "_default": {
                "critical": "该问题可直接导致系统被完全控制或大规模数据泄露，建议立即修复并进行渗透复测。",
                "high": "该问题可被利用进行未授权访问或数据泄露，建议尽快修复并加强安全测试覆盖。",
                "medium": "该问题可被用于信息收集或辅助攻击，建议纳入迭代计划修复。",
                "low": "影响较小，建议修复以提升安全基线。",
            },
        }

    def match(self, engine_code: str, risk_level: str, finding: dict | None = None) -> str:
        """匹配修复建议：引擎级 → OWASP 级 → 风险等级兜底。"""
        finding = finding or {}
        owasp = str(finding.get("owasp_id") or "")[:3]
        engine_kb = self.knowledge_base.get(engine_code) or {}

        # 1) 引擎 + OWASP 类别精确匹配
        if owasp and isinstance(engine_kb.get(owasp), dict):
            owasp_kb = engine_kb[owasp]
            if risk_level in owasp_kb:
                return str(owasp_kb[risk_level])
            # 该 OWASP 下其它等级建议也比没有强
            for lvl in ("critical", "high", "medium", "low"):
                if lvl in owasp_kb:
                    return str(owasp_kb[lvl])

        # 2) 引擎级按风险等级匹配（HTTP_SECURITY_HEADERS 等直接挂在引擎下）
        if risk_level in engine_kb and isinstance(engine_kb[risk_level], str):
            return str(engine_kb[risk_level])

        # 3) 全局默认表
        default_kb = self.knowledge_base.get("_default") or {}
        if risk_level in default_kb:
            return str(default_kb[risk_level])
        for lvl in ("critical", "high", "medium", "low"):
            if lvl in default_kb:
                return str(default_kb[lvl])

        return "建议参考 OWASP Top 10 修复指南进行修复，并补充对应安全测试用例验证。"
