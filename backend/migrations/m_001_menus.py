"""idempotent 迁移：menus + role_menus + system_settings + login_attempts 扩展

evalshield=# \d system_users
id, username, email, ...

执行：python backend/migrations/m_001_menus.py
"""
import sys; sys.path.insert(0, r"e:\code\EvalShield\backend")
from app.database import SessionLocal, engine
from sqlalchemy import text

db = SessionLocal()

print("=" * 60)
print("MIGRATION: m_001_menus + role_menus + system_settings + login_attempts")
print("=" * 60)

# 1. 建 menus 表（含 parent_id 自关联 + sort + visible + type）
db.execute(text("""
CREATE TABLE IF NOT EXISTS menus (
    id SERIAL PRIMARY KEY,
    parent_id INTEGER REFERENCES menus(id) ON DELETE CASCADE,
    path VARCHAR(128) NOT NULL,          -- 前端路由 path 片段，如 /admin/roles
    component VARCHAR(256),               -- 前端组件路径（动态路由用），如 pages/admin/Roles
    icon VARCHAR(64),                     -- icon 名（Ant Design icon）
    title VARCHAR(64) NOT NULL,           -- 菜单标题
    perm VARCHAR(64),                     -- 所需权限码，如 admin:role
    sort_order INTEGER NOT NULL DEFAULT 0,
    visible BOOLEAN NOT NULL DEFAULT true,
    menu_type VARCHAR(16) NOT NULL DEFAULT 'menu',  -- menu / button / dir
    remark VARCHAR(256),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_menus_parent ON menus(parent_id);
CREATE INDEX IF NOT EXISTS idx_menus_perm ON menus(perm);
CREATE INDEX IF NOT EXISTS idx_menus_path ON menus(path) WHERE deleted_at IS NULL;
"""))
print("✅ menus 表 OK")

# 2. role_menus 表
db.execute(text("""
CREATE TABLE IF NOT EXISTS role_menus (
    id SERIAL PRIMARY KEY,
    role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    menu_id INTEGER NOT NULL REFERENCES menus(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(role_id, menu_id)
);
CREATE INDEX IF NOT EXISTS idx_role_menus_role ON role_menus(role_id);
CREATE INDEX IF NOT EXISTS idx_role_menus_menu ON role_menus(menu_id);
"""))
print("✅ role_menus 表 OK")

# 3. system_settings 表
db.execute(text("""
CREATE TABLE IF NOT EXISTS system_settings (
    id SERIAL PRIMARY KEY,
    setting_group VARCHAR(32) NOT NULL,   -- 密码策略/登录策略/邮件/存储/限流/网关
    setting_key VARCHAR(64) NOT NULL,
    setting_value TEXT,
    value_type VARCHAR(16) NOT NULL DEFAULT 'string',  -- string / integer / boolean / json
    description VARCHAR(256),
    is_secret BOOLEAN NOT NULL DEFAULT false,
    updated_by INTEGER,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(setting_group, setting_key)
);
"""))
print("✅ system_settings 表 OK")

# 4. login_attempts 检查是否已存在
exists = db.execute(text(
    "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='login_attempts')"
)).scalar()
print(f"✅ login_attempts 表: {'已存在' if exists else '不存在（无需创建）'}")

db.commit()

# ========== SEED: 将 MainLayout.jsx 里的菜单灌入 menus 表 ==========
# 层级：dir (系统管理 parent) + menu (所有业务菜单 + 系统子菜单)
SEED_MENUS = [
    # === 业务顶级菜单（parent_id=NULL） ===
    (None, '/dashboard', 'pages/Dashboard', 'DashboardOutlined', '仪表盘', 'dashboard:view', 1, 'menu', '业务首页'),
    (None, '/projects', 'pages/Projects', 'ProjectOutlined', '项目管理', 'project:read', 2, 'menu', '项目列表'),
    (None, '/tasks', 'pages/Tasks', 'ScheduleOutlined', '任务中心', 'task:read', 3, 'menu', '任务列表'),
    (None, '/cases', 'pages/assets/CasesTab', 'FolderOpenOutlined', '资产中心', 'case:read', 4, 'menu', '用例/场景/数据集'),
    (None, '/eval', 'pages/EvalCenter', 'ExperimentOutlined', '评测中心', 'eval:read', 5, 'menu', '评测列表'),
    (None, '/reports', 'pages/Reports', 'FileTextOutlined', '报告中心', 'report:read', 6, 'menu', '报告列表'),
    (None, '/defects', 'pages/Defects', 'SafetyCertificateOutlined', '缺陷管理', 'defect:read', 7, 'menu', '缺陷列表'),
    (None, '/environments', 'pages/Environments', 'CloudServerOutlined', '环境管理', 'project:read', 8, 'menu', '测试环境'),
    (None, '/recordings', 'pages/Recordings', 'SwapOutlined', 'UI 录制', 'case:read', 9, 'menu', 'UI 录制'),
    (None, '/ai/automation', 'pages/AIAutomation', 'ThunderboltOutlined', 'AI 自动化', 'task:create', 10, 'menu', 'AI 自动化生成'),
    (None, '/ai/discover', 'pages/AIDiscover', 'CompassOutlined', 'AI 自动探测', 'task:create', 11, 'menu', 'AI Discover'),
    (None, '/documents/import', 'pages/DocImport', 'UploadOutlined', '文档导入', 'case:create', 12, 'menu', '文档导入'),
    (None, '/billing', 'pages/Billing', 'WalletOutlined', '计费管理', 'billing:read', 13, 'menu', '计费'),
    (None, '/models', 'pages/Models', 'CloudServerOutlined', '模型网关', 'model:read', 14, 'menu', '模型配置'),

    # === 系统管理 dir (parent_id=NULL, type=dir) ===
    (None, '/admin', None, 'SettingOutlined', '系统管理', 'admin:*', 100, 'dir', '系统管理目录'),
]

# 先灌顶级菜单（不含系统子菜单，子菜单在 step 灌完拿到 admin dir id 再插）
for parent_id, path, comp, icon, title, perm, sort, mtype, remark in SEED_MENUS:
    db.execute(text("""
        INSERT INTO menus (parent_id, path, component, icon, title, perm, sort_order, menu_type, remark)
        VALUES (:parent, :path, :comp, :icon, :title, :perm, :sort, :type, :remark)
        ON CONFLICT DO NOTHING
    """), {"parent": parent_id, "path": path, "comp": comp, "icon": icon,
           "title": title, "perm": perm, "sort": sort, "type": mtype, "remark": remark})

# 取 admin dir id
admin_dir = db.execute(text("SELECT id FROM menus WHERE path='/admin' AND menu_type='dir'")).fetchone()
admin_dir_id = admin_dir[0] if admin_dir else None
print(f"\nadmin dir id = {admin_dir_id}")

# === 系统管理子菜单 ===
SYS_SUBMENUS = [
    (admin_dir_id, '/admin/users',    'pages/admin/Users',    'UserOutlined',      '用户管理',   'admin:user', 1, 'menu', None),
    (admin_dir_id, '/admin/roles',    'pages/admin/Roles',    'TeamOutlined',      '角色权限',   'admin:role', 2, 'menu', None),
    (admin_dir_id, '/admin/perms',    'pages/admin/Permissions','LockOutlined',    '权限字典',   'admin:perm', 3, 'menu', 'NEW'),
    (admin_dir_id, '/admin/menus',    'pages/admin/Menus',    'MenuOutlined',      '菜单管理',   'admin:menu', 4, 'menu', 'NEW - P0'),
    (admin_dir_id, '/admin/dicts',    'pages/admin/Dicts',    'DatabaseOutlined',  '数据字典',   'admin:dict', 5, 'menu', None),
    (admin_dir_id, '/admin/settings', 'pages/admin/Settings', 'ControlOutlined',   '系统参数',   'admin:setting',6,'menu', 'NEW'),
    (admin_dir_id, '/admin/api-keys', 'pages/admin/ApiKeys',  'KeyOutlined',       'API 密钥',   'admin:api_key',7,'menu', None),
    (admin_dir_id, '/admin/audit',    'pages/admin/AuditLogs','AuditOutlined',     '审计日志',   'admin:audit', 8, 'menu', None),
    (admin_dir_id, '/admin/login-logs','pages/admin/LoginLogs','LoginOutlined',    '登录日志',   'admin:log',   9, 'menu', 'NEW'),
    (admin_dir_id, '/admin/orgs',     'pages/admin/Orgs',     'ApartmentOutlined', '组织机构',   'admin:org',  10, 'menu', None),
]
for parent_id, path, comp, icon, title, perm, sort, mtype, remark in SYS_SUBMENUS:
    db.execute(text("""
        INSERT INTO menus (parent_id, path, component, icon, title, perm, sort_order, menu_type, remark)
        VALUES (:parent, :path, :comp, :icon, :title, :perm, :sort, :type, :remark)
        ON CONFLICT DO NOTHING
    """), {"parent": parent_id, "path": path, "comp": comp, "icon": icon,
           "title": title, "perm": perm, "sort": sort, "type": mtype, "remark": remark})

db.commit()

# ========== 打印 seed 结果 ==========
print("\n=== menus 表种子数据 ===")
all_menus = db.execute(text("""
    SELECT id, parent_id, path, title, perm, menu_type, sort_order FROM menus
    WHERE deleted_at IS NULL ORDER BY parent_id NULLS FIRST, sort_order
""")).fetchall()
for row in all_menus:
    print(f"  id={row[0]:3d} parent={row[1]} path={row[2]:25s} title={row[3]:8s} perm={row[4] or '-':20s} type={row[5]} sort={row[6]}")
print(f"\nmenus 总数: {len(all_menus)}")

# ========== 给 SUPER_ADMIN/ADMIN 角色灌 role_menus ==========
roles_seed = [
    ('SUPER_ADMIN', all_menus),
    ('ADMIN', all_menus),  # admin 也有全部菜单
]
for role_code, menus in roles_seed:
    role_id = db.execute(text("SELECT id FROM roles WHERE role_code=:c"), {"c": role_code}).scalar()
    if role_id is None:
        continue
    for (mid, _, _, _, _, _, _) in menus:
        db.execute(text("""
            INSERT INTO role_menus (role_id, menu_id) VALUES (:rid, :mid)
            ON CONFLICT DO NOTHING
        """), {"rid": role_id, "mid": mid})
    print(f"  role_menus: {role_code} 绑定 {len(menus)} 条菜单")

# ========== system_settings 默认值 ==========
SETTINGS_SEED = [
    ('password', 'min_length', '8', 'integer', '密码最小长度', False),
    ('password', 'require_uppercase', 'true', 'boolean', '需大写', False),
    ('password', 'require_number', 'true', 'boolean', '需数字', False),
    ('password', 'expire_days', '90', 'integer', '密码过期天数', False),
    ('login', 'max_failures', '5', 'integer', '登录失败锁定次数', False),
    ('login', 'lockout_minutes', '30', 'integer', '锁定时长(分钟)', False),
    ('login', 'mfa_required', 'false', 'boolean', '强制 MFA', False),
    ('session', 'ttl_seconds', '7200', 'integer', 'JWT access_token TTL', False),
    ('email', 'smtp_host', '', 'string', 'SMTP 服务器', False),
    ('email', 'smtp_port', '465', 'integer', 'SMTP 端口', False),
    ('email', 'smtp_user', '', 'string', 'SMTP 用户', False),
    ('email', 'smtp_password', '', 'string', 'SMTP 密码', True),
    ('storage', 'default_provider', 'local', 'string', '存储提供商', False),
    ('discover', 'target_source', 'TEST_ENVIRONMENTS', 'string', 'Discover 白名单来源', False),
]
for group, key, val, vtype, desc, secret in SETTINGS_SEED:
    db.execute(text("""
        INSERT INTO system_settings (setting_group, setting_key, setting_value, value_type, description, is_secret)
        VALUES (:g, :k, :v, :t, :d, :s)
        ON CONFLICT DO NOTHING
    """), {"g": group, "k": key, "v": val, "t": vtype, "d": desc, "s": secret})
print(f"\nsystem_settings 种子: {len(SETTINGS_SEED)} 条")

db.commit()
db.close()
print("\n✅ MIGRATION COMPLETE")
