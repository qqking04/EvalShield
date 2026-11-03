# -*- coding: utf-8 -*-
"""数据库初始化脚本：建表 + 种子数据。

用法：python scripts/seed.py [--reset]
- 默认只建缺失表并写入缺失种子数据（幂等）。
- --reset 将 DROP 全部表后重建（危险操作，仅开发用）。
"""

from __future__ import annotations

import os
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 保证可导入 app 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models import (  # noqa: E402
    ApiKey,
    BillingQuota,
    DataDict,
    DictItem,
    Organization,
    Permission,
    Project,
    Role,
    RolePermission,
    SystemUser,
    TestEngine,
    UserRole,
)
from app.security import hash_password  # noqa: E402
from app.utils.no import gen_no  # noqa: E402


# ---------------------------------------------------------------------------
# 权限点定义（模块:动作口径，与 deps.require_permission 一致）
# ---------------------------------------------------------------------------
PERMISSIONS: list[tuple[str, str, str, str]] = [
    # (perm_code, perm_name, module, type)
    ("dashboard:view", "查看仪表盘", "dashboard", "MENU"),
    ("project:*", "项目管理（全部）", "project", "ACTION"),
    ("project:create", "创建项目", "project", "ACTION"),
    ("project:read", "查看项目", "project", "ACTION"),
    ("project:update", "编辑项目", "project", "ACTION"),
    ("project:delete", "删除项目", "project", "ACTION"),
    ("task:*", "任务管理（全部）", "task", "ACTION"),
    ("task:create", "创建任务", "task", "ACTION"),
    ("task:read", "查看任务", "task", "ACTION"),
    ("task:execute", "执行/取消任务", "task", "ACTION"),
    ("task:update", "编辑任务", "task", "ACTION"),
    ("task:delete", "删除任务", "task", "ACTION"),
    ("case:*", "用例管理（全部）", "case", "ACTION"),
    ("case:create", "创建用例", "case", "ACTION"),
    ("case:read", "查看用例", "case", "ACTION"),
    ("case:update", "编辑用例", "case", "ACTION"),
    ("case:delete", "删除用例", "case", "ACTION"),
    ("dataset:*", "数据集管理（全部）", "dataset", "ACTION"),
    ("dataset:create", "创建数据集", "dataset", "ACTION"),
    ("dataset:read", "查看数据集", "dataset", "ACTION"),
    ("dataset:delete", "删除数据集", "dataset", "ACTION"),
    ("scenario:*", "场景管理（全部）", "scenario", "ACTION"),
    ("scenario:create", "创建场景", "scenario", "ACTION"),
    ("scenario:read", "查看场景", "scenario", "ACTION"),
    ("scenario:delete", "删除场景", "scenario", "ACTION"),
    ("report:*", "报告管理（全部）", "report", "ACTION"),
    ("report:read", "查看报告", "report", "ACTION"),
    ("report:export", "导出报告", "report", "ACTION"),
    ("eval:*", "评测管理（全部）", "eval", "ACTION"),
    ("eval:create", "创建评测", "eval", "ACTION"),
    ("eval:read", "查看评测", "eval", "ACTION"),
    ("eval:execute", "执行评测", "eval", "ACTION"),
    ("model:*", "模型网关管理（全部）", "model", "ACTION"),
    ("model:create", "创建模型配置", "model", "ACTION"),
    ("model:read", "查看模型配置", "model", "ACTION"),
    ("model:update", "编辑模型配置", "model", "ACTION"),
    ("model:delete", "删除模型配置", "model", "ACTION"),
    ("model:test", "测试模型连接", "model", "ACTION"),
    ("engine:*", "引擎管理（全部）", "engine", "ACTION"),
    ("engine:read", "查看引擎", "engine", "ACTION"),
    ("engine:execute", "执行引擎", "engine", "ACTION"),
    ("notification:*", "通知管理（全部）", "notification", "ACTION"),
    ("notification:read", "查看通知", "notification", "ACTION"),
    ("asset:*", "资产库管理（全部）", "asset", "ACTION"),
    ("asset:read", "查看资产", "asset", "ACTION"),
    ("cost:export", "导出成本报告", "cost", "ACTION"),
    ("admin:*", "系统管理（全部）", "admin", "ACTION"),
    ("admin:user", "用户管理", "admin", "ACTION"),
    ("admin:role", "角色管理", "admin", "ACTION"),
    ("admin:perm", "权限管理", "admin", "ACTION"),
    ("admin:dict", "数据字典", "admin", "ACTION"),
    ("admin:audit", "审计日志", "admin", "ACTION"),
]

# 角色定义：(code, name, type, is_system, perms关键字集合)
ROLES: list[dict] = [
    {
        "code": "SUPER_ADMIN",
        "name": "超级管理员",
        "type": "BUILTIN",
        "is_system": True,
        "perms": ["*"],
    },
    {
        "code": "ADMIN",
        "name": "测试管理员",
        "type": "BUILTIN",
        "is_system": True,
        "perms": [
            "dashboard",
            "project",
            "task",
            "case",
            "dataset",
            "scenario",
            "report",
            "eval",
            "model",
            "engine",
            "notification",
            "asset",
            "admin",
        ],
    },
    {
        "code": "TESTER",
        "name": "测试工程师",
        "type": "BUILTIN",
        "is_system": True,
        "perms": [
            "dashboard",
            "project",
            "task",
            "case",
            "dataset",
            "scenario",
            "report",
            "eval",
        ],
    },
    {
        "code": "VIEWER",
        "name": "只读查看者",
        "type": "BUILTIN",
        "is_system": True,
        # 精确权限口径：只有 read 类 + dashboard:view，绝无 create/update/delete/execute/export
        # 与 deps.require_permission 一致，VIEWER 任何写操作都应 403
        "perms": [
            "dashboard:view",
            "project:read",
            "task:read",
            "case:read",
            "report:read",
            "dataset:read",
            "model:read",
            "engine:read",
            "eval:read",
            "defect:read",
            "dictionary:read",
            "notification:read",
            "asset:read",
        ],
        "perm_mode": "explicit",  # 精确 perm_code 列表（不走模块关键字展开）
    },
]

# 数据字典定义：(code, name, type, is_system, items)
DATA_DICTS: list[dict] = [
    {
        "code": "TEST_CATEGORY",
        "name": "测试类别",
        "type": "SYSTEM",
        "is_system": True,
        "items": [
            ("UI 测试", "UI", "traditional"),
            ("API 测试", "API", "traditional"),
            ("性能测试", "PERF", "traditional"),
            ("数据流测试", "DATAFLOW", "traditional"),
            ("幻觉测试", "HALLUCINATION", "ai"),
            ("越狱红队", "REDTEAM", "ai"),
            ("RAG 测试", "RAG", "ai"),
            ("多轮一致性", "MULTITURN", "ai"),
            ("伦理合规", "ETHICS", "ai"),
            ("平台化评测", "EVAL", "ai"),
            ("Agent 用例生成", "CASE_GEN", "engineering"),
            ("脚本自愈", "SELF_HEAL", "engineering"),
            ("缺陷预测", "DEFECT_PREDICT", "engineering"),
        ],
    },
    {
        "code": "TASK_STATUS",
        "name": "任务状态",
        "type": "SYSTEM",
        "is_system": True,
        "items": [
            ("待执行", "PENDING", "default"),
            ("执行中", "RUNNING", "processing"),
            ("取消中", "CANCELING", "warning"),
            ("成功", "SUCCESS", "success"),
            ("失败", "FAILED", "error"),
            ("已取消", "CANCELLED", "warning"),
        ],
    },
    {
        "code": "ENGINE_TYPE",
        "name": "引擎类型",
        "type": "SYSTEM",
        "is_system": True,
        "items": [
            ("传统测试", "TRADITIONAL", "blue"),
            ("AI 测试", "AI", "purple"),
            ("AI 工程化", "ENGINEERING", "cyan"),
        ],
    },
    {
        "code": "CASE_SEVERITY",
        "name": "用例严重级别",
        "type": "SYSTEM",
        "is_system": True,
        "items": [
            ("致命", "P0", "error"),
            ("严重", "P1", "error"),
            ("重要", "P2", "warning"),
            ("一般", "P3", "processing"),
            ("轻微", "P4", "default"),
        ],
    },
    {
        "code": "CASE_SOURCE",
        "name": "用例来源",
        "type": "SYSTEM",
        "is_system": True,
        "items": [
            ("手工创建", "MANUAL", ""),
            ("AI 生成", "AI_GEN", ""),
            ("Agent 生成", "AGENT_GEN", ""),
            ("导入", "IMPORT", ""),
        ],
    },
    {
        "code": "NOTIFY_TYPE",
        "name": "通知类型",
        "type": "SYSTEM",
        "is_system": True,
        "items": [
            ("系统通知", "SYSTEM", ""),
            ("任务通知", "TASK", ""),
            ("告警", "ALERT", "error"),
            ("审批", "APPROVAL", "warning"),
        ],
    },
    {
        "code": "MODEL_PROVIDER",
        "name": "模型提供商",
        "type": "SYSTEM",
        "is_system": True,
        "items": [
            ("OpenAI", "OPENAI", ""),
            ("百度千帆", "BAIDU", ""),
            ("通义千问", "DASHSCOPE", ""),
            ("DeepSeek", "DEEPSEEK", ""),
            ("火山方舟", "VOLCENGINE", ""),
            ("本地模型", "LOCAL", ""),
        ],
    },
]

# 13 类引擎种子
ENGINES: list[tuple[str, str, str, str, str]] = [
    (
        "UI_TEST",
        "UI 自动化测试引擎",
        "TRADITIONAL",
        "UI",
        "基于浏览器自动化执行 UI 用例：打开/点击/输入/断言，支持截图证据。",
    ),
    (
        "API_TEST",
        "API 接口测试引擎",
        "TRADITIONAL",
        "API",
        "执行 REST/HTTP 接口用例：方法/路径/头/体，断言状态码与响应字段。",
    ),
    (
        "PERF_TEST",
        "性能测试引擎",
        "TRADITIONAL",
        "PERF",
        "HTTP 压测：并发/总请求数/QPS/延迟分位，输出性能指标。",
    ),
    (
        "DATAFLOW_TEST",
        "数据流测试引擎",
        "TRADITIONAL",
        "DATAFLOW",
        "场景端到端数据流验证：步骤链、变量提取与传递、数据一致性断言。",
    ),
    (
        "HALLUCINATION_TEST",
        "幻觉测试引擎",
        "AI",
        "HALLUCINATION",
        "构造有明确答案的问题集，比对模型输出与参考答案，识别捏造事实。",
    ),
    (
        "REDTEAM_TEST",
        "越狱与安全红队引擎",
        "AI",
        "REDTEAM",
        "覆盖直接越狱、角色扮演逃逸、间接注入、有害内容生成、数据泄露探测。",
    ),
    (
        "RAG_TEST",
        "RAG 正确性测试引擎",
        "AI",
        "RAG",
        "评估检索命中率、上下文相关性、答案引用正确率（忠实度/完整度）。",
    ),
    (
        "MULTI_TURN_TEST",
        "多轮一致性测试引擎",
        "AI",
        "MULTITURN",
        "多轮对话的记忆保持、指代消解与逻辑一致性检测。",
    ),
    (
        "ETHICS_TEST",
        "伦理合规测试引擎",
        "AI",
        "ETHICS",
        "内容安全、隐私保护、公平偏见、合规红线四类伦理场景检测。",
    ),
    (
        "EVAL_ENGINE",
        "平台化评测引擎",
        "AI",
        "EVAL",
        "统一评测框架：评测集 + 裁判模式，产出总分与逐项评分，支持横向对比。",
    ),
    (
        "CASE_GEN",
        "AI Agent 自动生成用例引擎",
        "ENGINEERING",
        "CASE_GEN",
        "输入需求/接口/页面描述，自动生成覆盖正常/边界/异常路径的用例。",
    ),
    (
        "SELF_HEAL",
        "脚本自愈引擎",
        "ENGINEERING",
        "SELF_HEAL",
        "失败用例根因分析 → 自动修复（重试/重定位/修正断言），并生成自愈报告。",
    ),
    (
        "DEFECT_PREDICT",
        "缺陷预测引擎",
        "ENGINEERING",
        "DEFECT_PREDICT",
        "基于历史执行数据预测缺陷风险，输出风险评分与热点模块。",
    ),
]


# ---------------------------------------------------------------------------
# 建表 / 种子
# ---------------------------------------------------------------------------
def create_tables() -> None:
    """创建全部表（已存在则跳过）。"""
    Base.metadata.create_all(bind=engine)
    print(f"[OK] 建表完成，共 {len(Base.metadata.tables)} 张表")


def seed_permissions(db) -> None:
    added = 0
    for code, name, module, ptype in PERMISSIONS:
        if not db.query(Permission).filter(Permission.perm_code == code).first():
            db.add(
                Permission(
                    perm_code=code, perm_name=name, module=module, perm_type=ptype
                )
            )
            added += 1
    db.commit()
    print(f"[OK] 权限点：新增 {added}，共 {db.query(Permission).count()} 条")


def seed_roles(db) -> None:
    added = 0
    for r in ROLES:
        role = db.query(Role).filter(Role.role_code == r["code"]).first()
        if role is None:
            role = Role(
                role_code=r["code"],
                role_name=r["name"],
                role_type=r["type"],
                is_system=r["is_system"],
                tenant_id=1,
            )
            db.add(role)
            db.flush()
            added += 1
        # 绑定权限
        is_explicit = r.get("perm_mode") == "explicit"
        if r["perms"] == ["*"]:
            perm_codes = [p.perm_code for p in db.query(Permission).all()]
        elif is_explicit:
            # 精确 perm_code 列表：直接用（如 VIEWER 的只读白名单）
            perm_codes = list(r["perms"])
        else:
            perm_codes = []
            for pcode in r["perms"]:
                perm_codes += [
                    p.perm_code
                    for p in db.query(Permission)
                    .filter(Permission.module == pcode)
                    .all()
                ]
        # VIEWER (perm_mode=explicit)：先清空再精确绑定 — 防止历史脏数据残留写权限
        if is_explicit:
            db.query(RolePermission).filter(RolePermission.role_id == role.id).delete()
            db.flush()
            added_perm = 0
            for code in sorted(set(perm_codes)):
                # 白名单：只绑定 PERMISSIONS 里存在的 perm_code（过滤 dict/read 等尚未注册的）
                exists = db.query(Permission).filter(Permission.perm_code == code).first()
                if exists:
                    db.add(RolePermission(role_id=role.id, perm_code=code))
                    added_perm += 1
            print(f"    角色 {r['code']}：先清空后绑定 {added_perm} 条（perm_mode=explicit）")
        else:
            # 去重后绑定
            added_perm = 0
            for code in sorted(set(perm_codes)):
                if (
                    code in (p.perm_code for p in db.query(Permission).all())
                    and not db.query(RolePermission)
                    .filter(
                        RolePermission.role_id == role.id, RolePermission.perm_code == code
                    )
                    .first()
                ):
                    db.add(RolePermission(role_id=role.id, perm_code=code))
                    added_perm += 1
            print(f"    角色 {r['code']}：绑定权限 {added_perm} 条")
    db.commit()
    print(f"[OK] 角色：新增 {added}，共 {db.query(Role).count()} 个角色")


def seed_admin(db) -> None:
    # admin（超级管理员，独立创建）
    # 优化7 T4 / ES7-F-2 修复：说明书 §4.3 双分支均置 must_change_pwd=true——
    # INIT_ADMIN_PASSWORD 显式提供口令时仅免随机打印，**不豁免**首登强制改密
    # （部署工单常以该变量交付口令，原实现恰落在豁免分支致整批绕过 T4 控制）。
    admin = db.query(SystemUser).filter(SystemUser.username == "admin").first()
    if admin is None:
        init_pwd = os.environ.get("INIT_ADMIN_PASSWORD", "").strip()
        random_mode = not init_pwd
        if random_mode:
            init_pwd = secrets.token_urlsafe(12)
        # ES7-D-1 修复：随机口令默认**不落 stdout**——容器 stdout 经 docker daemon
        # 持久化日志可读出（D6 判据「一次性口令不落任何持久化日志」）。
        # 开发/本地脚本场景显式 SEED_ALLOW_RANDOM_PWD_PRINT=1 才恢复打印。
        allow_print = os.environ.get("SEED_ALLOW_RANDOM_PWD_PRINT", "").strip().lower() in ("1", "true", "yes")
        admin = SystemUser(
            user_no=gen_no("U"),
            username="admin",
            display_name="超级管理员",
            password_hash=hash_password(init_pwd),
            user_type="INTERNAL",
            status="ACTIVE",
            email="admin@evalshield.local",
            tenant_id=1,
            must_change_pwd=True,
        )
        db.add(admin)
        db.flush()
        super_role = db.query(Role).filter(Role.role_code == "SUPER_ADMIN").first()
        if super_role:
            db.add(UserRole(user_id=admin.id, role_id=super_role.id, tenant_id=1))
        db.commit()
        print("[OK] admin 已创建（首次登录将强制修改密码）")
        if random_mode and allow_print:
            print("=" * 60)
            print("[admin 初始口令]（仅本次打印，请妥善保存）：")
            print(f"    {init_pwd}")
            print("    首次登录系统将强制修改密码。")
            print("=" * 60)
        elif random_mode:
            print("[WARN] admin 随机口令未打印（ES7-D-1：不落持久化日志）。")
            print("[WARN] 正确流程：装机前由部署工单生成 INIT_ADMIN_PASSWORD 写入 .env；")
            print("[WARN] 若已发生无口令可交付，删除 admin 行并注入 INIT_ADMIN_PASSWORD 重跑 seed。")
    else:
        print("[OK] admin 已存在，跳过")

    # ES7-D-2 修复：演示账号（tester/test111，固定弱口令）加开关——
    # SEED_DEMO_ACCOUNTS=1/0 显式控制；未设置时默认仅 community 形态创建，
    # enterprise/saas 生产装机不再默认在场。
    edition = os.environ.get("EDITION", "enterprise").strip().lower()
    demo_flag = os.environ.get("SEED_DEMO_ACCOUNTS", "").strip().lower()
    seed_demo = demo_flag in ("1", "true", "yes") if demo_flag else (edition == "community")

    # tester（演示账号，独立创建）
    tester_role = db.query(Role).filter(Role.role_code == "TESTER").first()
    if seed_demo:
        tester = db.query(SystemUser).filter(SystemUser.username == "tester").first()
        if tester is None:
            tester = SystemUser(
                user_no=gen_no("U"),
                username="tester",
                display_name="测试工程师（演示）",
                password_hash=hash_password("EvalShield@123"),
                user_type="INTERNAL",
                status="ACTIVE",
                email="tester@evalshield.local",
                tenant_id=1,
            )
            db.add(tester)
            db.flush()
            if tester_role:
                db.add(UserRole(user_id=tester.id, role_id=tester_role.id, tenant_id=1))
            db.commit()
            print("[OK] tester 已创建")
        else:
            print("[OK] tester 已存在，跳过")

        # test111（BUG-15 修复：测试方案约定账号，独立创建）
        test111 = db.query(SystemUser).filter(SystemUser.username == "test111").first()
        if test111 is None:
            test111 = SystemUser(
                user_no=gen_no("U"),
                username="test111",
                display_name="测试用户111",
                password_hash=hash_password("123456"),
                user_type="TENANT",
                status="ACTIVE",
                email="test111@test.com",
                tenant_id=1,
                mfa_enabled=False,
                login_fail_count=0,
            )
            db.add(test111)
            db.flush()
            if tester_role:
                db.add(UserRole(user_id=test111.id, role_id=tester_role.id, tenant_id=1))
            db.commit()
            print("[OK] test111 已创建")
        else:
            print("[OK] test111 已存在，跳过")
        # ES7-D-2：话术按实际口令模式条件化（admin 不再谎报固定口令）
        print("[OK] 内置账号就绪：admin(初始化口令见上/部署工单) / tester(EvalShield@123) / test111(123456)")
    else:
        print("[OK] 演示账号（tester/test111）按形态跳过（EDITION=%s，SEED_DEMO_ACCOUNTS 可显式开启）" % edition)


def seed_dicts(db) -> None:
    added = 0
    for d in DATA_DICTS:
        dict_row = db.query(DataDict).filter(DataDict.dict_code == d["code"]).first()
        if dict_row is None:
            dict_row = DataDict(
                dict_code=d["code"],
                dict_name=d["name"],
                dict_type=d["type"],
                is_system=d["is_system"],
            )
            db.add(dict_row)
            db.flush()
            added += 1
        for label, value, ext_color in d["items"]:
            if (
                not db.query(DictItem)
                .filter(DictItem.dict_id == dict_row.id, DictItem.item_value == value)
                .first()
            ):
                db.add(
                    DictItem(
                        dict_id=dict_row.id,
                        item_label=label,
                        item_value=value,
                        ext={"color": ext_color} if ext_color else None,
                    )
                )
    db.commit()
    print(f"[OK] 数据字典：新增 {added} 个字典")


def seed_engines(db) -> None:
    added = 0
    for code, name, etype, category, desc in ENGINES:
        if not db.query(TestEngine).filter(TestEngine.engine_code == code).first():
            db.add(
                TestEngine(
                    engine_code=code,
                    engine_name=name,
                    engine_type=etype,
                    category=category,
                    description=desc,
                    version="1.0.0",
                    status="ENABLED",
                    is_system=True,
                )
            )
            added += 1
    db.commit()
    print(f"[OK] 引擎注册表：新增 {added} 个，共 {db.query(TestEngine).count()} 个引擎")


def seed_org_and_quota(db) -> None:
    if not db.query(Organization).filter(Organization.org_no.isnot(None)).first():
        db.add(
            Organization(
                org_no=gen_no("ORG"), org_name="测试中心", tenant_id=1, sort_order=1
            )
        )
    if not db.query(BillingQuota).filter(BillingQuota.tenant_id == 1).first():
        db.add(
            BillingQuota(
                tenant_id=1,
                plan="ENTERPRISE",
                task_quota=10000,
                eval_quota=5000,
                storage_quota_mb=10240,
                api_calls_quota=1000000,
                expires_at=datetime.now(timezone.utc) + timedelta(days=365),
            )
        )
    db.commit()
    print("[OK] 组织与计费配额初始化完成")


def main(reset: bool = False) -> None:
    if reset:
        print("[WARN] 正在重置全部表...")
        Base.metadata.drop_all(bind=engine)
    create_tables()
    from app.database import SessionLocal as _SL

    db = _SL()
    try:
        seed_permissions(db)
        seed_roles(db)
        seed_admin(db)
        seed_dicts(db)
        seed_engines(db)
        seed_org_and_quota(db)
    finally:
        db.close()
    print("\n初始化全部完成 ✓")


if __name__ == "__main__":
    main(reset="--reset" in sys.argv)
