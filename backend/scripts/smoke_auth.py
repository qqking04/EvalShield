# -*- coding: utf-8 -*-
"""认证授权与 RBAC 冒烟测试。
覆盖：登录成功/失败、/me、RBAC 越权拒绝、API Key 认证、刷新令牌、改密。
"""

import sys

sys.path.insert(0, ".")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)

PASS = 0
FAIL = 0


def check(name: str, cond: bool, detail: str = ""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  -> {detail}")


# 1. 健康检查
r = client.get("/api/health")
check("健康检查", r.status_code == 200 and r.json().get("code") == 0, r.text[:200])

# 2. admin 登录成功
r = client.post(
    "/api/auth/login",
    json={"username": "admin", "password": "EvalShield@123"},
)
body = r.json()
check("admin 登录成功", r.status_code == 200 and body.get("code") == 0, r.text[:200])
admin_token = body["data"]["access_token"]
admin_refresh = body["data"]["refresh_token"]
check("登录返回 access+refresh", bool(admin_token) and bool(admin_refresh))

# 3. 错误密码
r = client.post(
    "/api/auth/login", json={"username": "admin", "password": "wrong-pass-123"}
)
check("错误密码被拒", r.status_code == 401 or (r.json().get("code") != 0), r.text[:200])

H = {"Authorization": f"Bearer {admin_token}"}

# 4. /me 返回角色与权限
r = client.get("/api/auth/me", headers=H)
me = r.json()["data"]
check("me.is_super_admin=True", me.get("is_super_admin") is True)
check("me.roles 含 SUPER_ADMIN", "SUPER_ADMIN" in me.get("roles", []))
check(
    "me.perms 覆盖 admin:user",
    "admin:user" in me.get("perms", []),
    str(me.get("perms"))[:200],
)
check(
    "me.perms 覆盖 admin:*",
    "admin:*" in me.get("perms", []),
    str(me.get("perms"))[:200],
)

# 5. 无令牌访问受保护接口
r = client.get("/api/auth/me")
check("无令牌访问 /me 被拒", r.status_code == 401, r.text[:200])

# 6. admin 访问管理接口（有权限）
r = client.get("/api/admin/users", headers=H)
check(
    "admin 访问用户列表",
    r.status_code == 200 and r.json().get("code") == 0,
    r.text[:200],
)

# 7. tester 登录
r = client.post(
    "/api/auth/login",
    json={"username": "tester", "password": "EvalShield@123"},
)
body = r.json()
check("tester 登录成功", r.status_code == 200 and body.get("code") == 0, r.text[:200])
tester_token = body["data"]["access_token"]
TH = {"Authorization": f"Bearer {tester_token}"}
r = client.get("/api/auth/me", headers=TH)
tme = r.json()["data"]
check("tester 非超管", tme.get("is_super_admin") is False)
check(
    "tester 权限不含 admin:*",
    "admin:*" not in tme.get("perms", []),
    str(tme.get("perms"))[:200],
)

# 8. RBAC 越权：tester 访问管理接口 → 403
r = client.get("/api/admin/users", headers=TH)
check(
    "tester 访问管理接口被拒(403)",
    r.status_code == 403,
    f"status={r.status_code} {r.text[:200]}",
)

# 9. tester 不能创建用户（写权限同样受控）
r = client.post(
    "/api/admin/users",
    headers=TH,
    json={"username": "hacker", "password": "Hacker@123", "display_name": "入侵者"},
)
check("tester 创建用户被拒", r.status_code == 403, r.text[:200])

# 10. API Key 认证：admin 创建 key
r = client.post("/api/admin/api-keys", headers=H, json={"key_name": "冒烟测试Key"})
kb = r.json()
check("创建 API Key", r.status_code == 200 and kb.get("code") == 0, r.text[:200])
plain_key = kb["data"]["api_key"]
check("API Key 明文仅返回一次", plain_key.startswith(kb["data"]["key_prefix"]))
r = client.get("/api/auth/me", headers={"X-API-Key": plain_key})
check(
    "API Key 认证 /me",
    r.status_code == 200 and r.json()["data"]["username"] == "admin",
    r.text[:200],
)

# 11. 刷新令牌
r = client.post("/api/auth/refresh", json={"refresh_token": admin_refresh})
check("刷新令牌", r.status_code == 200 and r.json().get("code") == 0, r.text[:200])
new_access = r.json()["data"]["access_token"]
r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {new_access}"})
check("新 access 可用", r.status_code == 200, r.text[:200])

# 12. 修改密码 → 用新密码重登 → 改回
r = client.post(
    "/api/auth/change-password",
    headers=H,
    json={
        "old_password": "EvalShield@123",
        "new_password": "EvalShield@456",
        "confirm_password": "EvalShield@456",
    },
)
check("修改密码", r.status_code == 200 and r.json().get("code") == 0, r.text[:200])
r = client.post(
    "/api/auth/login", json={"username": "admin", "password": "EvalShield@456"}
)
check("新密码可登录", r.status_code == 200, r.text[:200])
new_admin_token = r.json()["data"]["access_token"]
H = {"Authorization": f"Bearer {new_admin_token}"}
r = client.post(
    "/api/auth/change-password",
    headers=H,
    json={
        "old_password": "EvalShield@456",
        "new_password": "EvalShield@123",
        "confirm_password": "EvalShield@123",
    },
)
check("密码改回", r.status_code == 200, r.text[:200])
r = client.post(
    "/api/auth/login", json={"username": "admin", "password": "EvalShield@123"}
)
check("原密码恢复可登录", r.status_code == 200, r.text[:200])

# 13. 审计日志已写入（admin 可查）
r = client.get("/api/admin/audit-logs", headers=H, params={"page": 1, "page_size": 10})
al = r.json()
check("审计日志查询", r.status_code == 200 and al.get("code") == 0, r.text[:200])
check(
    "审计含 user.login 记录",
    any(x.get("action") == "user.login" for x in al.get("data", {}).get("items", [])),
)

print(f"\n==== 认证与 RBAC 冒烟结果：{PASS} 通过 / {FAIL} 失败 ====")
sys.exit(1 if FAIL else 0)
