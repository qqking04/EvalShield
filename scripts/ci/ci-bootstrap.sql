-- EvalShield 托管 CI 引导种子（在 inti.sql 之后执行；不进交付库人工流程）
-- 背景（优化6 §2.2 / A7）：inti.sql 不 seed system_users 与 projects，
--   全新 CI 库中 admin 登录恒 ES-AUTH-0001、ci-gate 恒 ES-CI-0002（无可用项目）。
-- 本文件用 psql -v ON_ERROR_STOP=1 幂等执行，重复运行安全。

-- 1) admin 用户（口令 EvalShield@123；哈希算法与 backend/app/security.py 一致：
--    md5$<16位hex盐>$<md5(盐+明文)hex>；仅 CI 一次性环境使用，无外部暴露面）
INSERT INTO system_users
    (user_no, username, email, password_hash, display_name, user_type,
     status, mfa_enabled, login_fail_count, tenant_id, created_at, updated_at)
VALUES
    ('U-CI-ADMIN', 'admin', 'ci@evalshield.local',
     'md5$0a1b2c3d4e5f6071$b1b05a5d55c930567e8f45efafcb1b3c',
     'admin', 'INTERNAL', 'ACTIVE', FALSE, 0, 1, now(), now())
ON CONFLICT (username) WHERE deleted_at IS NULL DO NOTHING;

-- 2) SUPER_ADMIN 角色（BUILTIN 角色由 backend/scripts/seed.py 落库，inti.sql §3 只
--    seed OWNER；全新 CI 库无此角色 → 先幂等补种。deps.py require_permission 对
--    is_super_admin 直接放行，不依赖 role_permissions 显式授权）
INSERT INTO roles (role_code, role_name, role_type, description, is_system, tenant_id, created_at, updated_at)
VALUES ('SUPER_ADMIN', '超级管理员', 'BUILTIN', '平台超级管理员（CI 引导补种）', TRUE, 1, now(), now())
ON CONFLICT (role_code) WHERE deleted_at IS NULL DO NOTHING;

-- 3) 绑定 SUPER_ADMIN
INSERT INTO user_roles (user_id, role_id, tenant_id, created_at)
SELECT u.id, r.id, 1, now()
FROM system_users u, roles r
WHERE u.username = 'admin' AND u.deleted_at IS NULL
  AND r.role_code = 'SUPER_ADMIN'
ON CONFLICT (user_id, role_id, tenant_id) DO NOTHING;

-- 4) CI 门禁项目（compliance_p1 /ci-gate/run 取租户第一个未删项目）
INSERT INTO projects (code, name, description, owner_id, owner_name,
                      visibility, status, tenant_id, created_at, updated_at)
SELECT 'PRJ-CI', 'CI 门禁项目', '托管 CI 引导种子（优化6 T2）',
       u.id, u.username, 'PRIVATE', 'ACTIVE', 1, now(), now()
FROM system_users u
WHERE u.username = 'admin' AND u.deleted_at IS NULL
ON CONFLICT (code) WHERE deleted_at IS NULL DO NOTHING;
