# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""IM 群机器人适配器：钉钉 / 飞书 / 企微 三种 markdown 卡片。

三家 payload 结构互异（§4.3）：
- 钉钉：{"msgtype":"markdown","markdown":{"title","text"}}
- 飞书：{"msg_type":"interactive","card":{"header":{"title"},"elements":[{"tag":"div",...}]}}
- 企微：{"msgtype":"markdown","markdown":{"content"}}
机器人自定义关键词加签（secret 签名校验）放后续迭代；本期内 secret 仅作预留不发送。
渠道 config 支持键：url（必填 webhook 地址）/ secret（预留）。
"""

from __future__ import annotations

import json

import httpx

from .base import SEND_TIMEOUT, SendResult


def _markdown_text(msg: dict) -> str:
    """消息正文（事件 + 严重级 + 内容），三家共用。"""
    return (
        f"**{msg.get('title') or 'EvalShield 通知'}**\n\n"
        f"- 事件：{msg.get('event')}\n"
        f"- 级别：{msg.get('severity')}\n\n"
        f"{msg.get('content') or ''}"
    )


def build_payload(kind: str, msg: dict) -> dict:
    """按渠道类型组装 markdown 卡片 payload（三种结构互异）。"""
    title = str(msg.get("title") or "EvalShield 通知")
    text = _markdown_text(msg)
    if kind == "dingtalk":
        return {"msgtype": "markdown", "markdown": {"title": title, "text": text}}
    if kind == "feishu":
        return {
            "msg_type": "interactive",
            "card": {
                "header": {"title": {"tag": "plain_text", "content": title}},
                "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": text}}],
            },
        }
    # wecom（企业微信 markdown 不支持标题字段，首行加粗即标题）
    return {"msgtype": "markdown", "markdown": {"content": f"**{title}**\n{text}"}}


def _make_send(kind: str):
    def send(config: dict, msg: dict) -> SendResult:
        cfg = config or {}
        url = str(cfg.get("url") or "")
        if not url:
            return SendResult(ok=False, error=f"{kind} 渠道缺少 url 配置", retryable=False)
        body = json.dumps(build_payload(kind, msg), ensure_ascii=False)
        try:
            resp = httpx.post(
                url,
                content=body.encode("utf-8"),
                headers={"Content-Type": "application/json"},
                timeout=SEND_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001 —— 网络类失败可重试
            return SendResult(ok=False, error=f"{kind} 请求失败: {exc.__class__.__name__}: {exc}", retryable=True)
        # 三家成功约定：HTTP 2xx 且（如返回 JSON）errcode/code 为 0
        if not 200 <= resp.status_code < 300:
            return SendResult(ok=False, error=f"{kind} 响应 {resp.status_code}", retryable=True)
        try:
            data = resp.json()
        except Exception:  # noqa: BLE001
            return SendResult(ok=True)
        code = data.get("errcode", data.get("code", 0)) if isinstance(data, dict) else 0
        if code not in (0, "0", None):
            return SendResult(ok=False, error=f"{kind} 返回错误: {str(data)[:200]}", retryable=True)
        return SendResult(ok=True)

    return send


send_dingtalk = _make_send("dingtalk")
send_feishu = _make_send("feishu")
send_wecom = _make_send("wecom")
