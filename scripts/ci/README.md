# scripts/ci — CI 通道资产

## 分工：三条通道各归其位（D-DOC-3 更正）

| 通道 | 触发 | 耗时 | 判据 | 定位 |
|---|---|---|---|---|
| `post-receive`（本目录，经 `install-hooks.ps1` 装到发布仓 bare 库 hooks/） | 每次 `git push release` | 秒级~分钟级 | stage1：检出 `.tmp/ci-worktree` 跑隔离 pytest（不依赖活体服务）；stage2：读 `.tmp/token_ent.txt` 打**本机 8000 活体 enterprise 实例**跑 evalshield-ci-gate。**本地钩子不建仿真库、不做 LICENSE 注入** | **阻断面**——push 即验，失败在 remote 回显 `FAIL` |
| 托管 CI（`.github/workflows/ci.yml` / `.gitlab-ci.yml`） | push/PR 到托管远端 | 分钟级 | stage2 在 CI 环境**自建仿真库**（inti.sql + ci-bootstrap.sql），以 `EVALSHIELD_CI_LICENSE_TEXT` secret 注入 LICENSE 起服（或 job 内自签 Key），再跑 evalshield-ci-gate | **远端门禁面**——本机不可复现的注入链路由托管环境验证 |
| `package-gate.ps1`（本目录） | 手动（发版前必跑，日常建议每日一次） | 分钟级 | P1 全量后端 pytest → P2 release_oss 出包 + 打包面用例 → P3 前端 vitest + EDITION=enterprise 构建 → P4 OSS 源码商业字面量残留扫描（F1） | **深度回归面**——出包/前端/全量测试一次性验证，不进钩子（太重会拖死 push 体验） |

> 口径澄清：旧版 README 把「stage2 建仿真库 + LICENSE_TEXT 注入」错记在本地 `post-receive` 行——那是托管 CI 的判据；本地钩子 stage2 依赖 8000 活体实例与 `.tmp/token_ent.txt`（见 `post-receive` 头部维护说明）。两条通道的 License 前置各不相同，不可混写。

## 文件清单

- `post-receive` — 发布仓钩子脚本（T1）
- `pre-receive` — 非快进拒绝钩子（OBS-3：管控 master/tags，force push 覆盖发布历史即拒）
- `install-hooks.ps1` — 钩子安装器（T1，双钩子循环部署、先验 LF 后拷贝；`-Local` 装本地提交闸门 `pre-commit` 到 `.git/hooks/`）
- `pre-commit` — 本地提交闸门（第 0 层：密钥哨兵 sk-*/私钥/.lic 拒入库 + 商业目录白名单闸门 + 优化12 §11.4/T9 机制硬化（调 `backend/scripts/pre_commit_checks.py`：inti.sql 只追加/骤减阻断、tc260.yaml 块式形状、三 lint、锁 1/2/3）；逃生门 `EVALSHIELD_SKIP_PRECOMMIT=1`，细粒度 `INTI_GATE_SKIP=1` / `FREEZE_EXEMPT=<工单号>`）
- `lint_doc_paths.py` — DOC-01：文档路径 lint（优化12 §11.4-2，md 反引号引用的带前缀仓库路径做存在性校验；默认扫 `优化12详细开发.md`，历史版本文档误引不回填）；与 `mechanism-lints` job（`.github/workflows/ci.yml`）同挂 SHAPE-01 `backend/scripts/lint_std_yaml_shape.py`、ALIGN-01 `lint_std_bank_align.py`、SYNC-01 `sync_inti_sql.py`、PRECOMMIT-01 `pre_commit_checks.py` 空跑
- `publish-oss.ps1` — 公共 OSS 仓发布（仓库清理方案 §4 固化：产物新鲜度 + P4 双口径扫描 + 零历史全新 init + 空仓断言；先 `-DryRun` 后实发）
- `ci-bootstrap.sql` — 仿真库引导种子：admin 用户 + SUPER_ADMIN 角色补种 + 绑定 + PRJ-CI 项目（T2，幂等）
- `package-gate.ps1` — 深度回归通道（T3），四段判据见上表；含 §4.3 两核对点定稿注释
- **ES9 六门禁 + KEY-01 脚本（优化9 §8 FRZ / §14 G2·G5 / BUG-ES9-005·009；优化14 §5.5.3-4）**，挂 `.github/workflows/ci.yml` 的 `freeze-checks`（G5）与 `security-db`（G2）两 job：
  - `check_engine_freeze.sh` — FRZ-01 + D-19：engines/ 新增 .py 与 registry 登记行变更必须带 `freeze-exempt:`；三层判据（untracked / 工作区 diff / commit 区间 `--since <rev>` 默认 HEAD~1）；本地逃生门 `FREEZE_EXEMPT=<工单号>`（CI 不设）
  - `check_csv_guard.sh` — CSV-02：csv.writer/writerow 所在函数体必须含防护符号（单源 `backend/app/utils/csv_safe.py::esc_csv`；delivery.py 本地 `_csv_cell` 登记为"已防护非单源"现状）；导出面清单见脚本头注释
  - `check_hardcoded_numbers.sh` — STD-03：监管比较语义的 0.85/0.6 裸写禁止；单源 = config.py `JUDGE_AGREEMENT_THRESHOLD` + services/standards.py；已知违规 4 条入 BASELINE（修复后必须同步删除基线）
  - `check_license_module_spelling.py` — FRZ-04：scripts/issue_license.py 与 app/enterprise/license.py 契约核心五字段（license_no/edition/features/expires_at/fp）双侧在位 + 消费键集 ⊆ 签发键集（AST 提取）
  - `check_no_private_key.py` — KEY-01（阻断，优化14 §5.5.3-4）：四断言=①跟踪路径不得命中 .pem/.key/.lic/.keys/ ②跟踪代码文件（py/js/json/yaml/yml）不得含私钥 PEM 块 ③忽略-跟踪矛盾回归预防（白名单 backend/tests/_legacy/）④pre-commit 密钥哨兵在位自检；与 .gitignore 治理口径注释块同 commit 合入（R4）
  - `check_blacklist_single_source.py` — FRZ-02：依赖黑名单单源 `config/scope-freeze.yaml`，对 scan_targets 逐源 grep 判定 + 黑名单字面量不得内联复制进其他脚本。【现状说明】本仓库为传统前端仓 + `backend/requirements.txt`，**无 pyproject.toml / uv.lock**（方案 §14 早期假设），yaml 中该两源标 `optional: true` 跳过；AGENTS.md 锁 2/3 的 grep 模式与本脚本口径一致，故未改动 AGENTS.md
  - `export_tenant_matrix.py` — TEN-02：扫 backend/tests 租户号字面量 → stdout markdown + `verification/es9/tenant_matrix.json`；与方案 §0.4 号段表对账（ES9 规划段/复用登记/号表外登记/哨兵号排除四层判据，见脚本 docstring）
- 上游脚本：`../evalshield-ci-gate.sh`（转调 backend/scripts/evalshield_cli.py gate）、`../release_oss.sh`（纯静态出包，不依赖 8000 活体）

## 签发与密钥 SOP（优化7 T3）

四步签发流程（签发者本机执行，工具 = `backend/scripts/license_cli.py`，已 gitignore 永不入库）：

1. **收指纹**：客户机执行 `python -c "from app.enterprise.license import machine_fingerprint; print(machine_fingerprint())"`（backend/ 目录下，或装机页展示）；
2. **sign**：`python backend/scripts/license_cli.py sign --customer <租户名> --days 365 --features multi_tenant whitelabel --fp <指纹> --out <客户>.lic`；
3. **verify**：`python backend/scripts/license_cli.py verify --file <客户>.lic` 必须 OK 才交付；
4. **台账登记**：写入 LicenseLedger（Admin 后台 License 台账页），截图归档到交付工单。

密钥卫生：
- 私钥口令**每季轮换**：改口令 = 重做 `license_cli.py backup --out license-keys-backup.enc` → 产物存两份（加密盘 + 离线介质）；`restore --file <备份> --out <临时目录>` 抽验签 `issued` 一致后删除；
- `.gitignore` 已覆盖 `*.lic` / `.keys/` / `license-keys-backup.enc` / `.tmp/`；`pre-commit` 哨兵对 sk-32hex 与 PEM 私钥块拒入库（逃生门仅限误报，勿绕过真值）；
- 发布面脱敏兜底见 `release_oss.sh` [3b] 段 + `publish-oss.ps1` 防呆 2b。

## 交付 SOP（优化7 T8-2 · 企业版 tar 交付物清单固化）

交付 tar 必含四件套（`publish` 流水线产物 + 人工装配），清单与包内 sha256 manifest 一致（T8-3 判据）：

| # | 交付物 | 来源 | 装配方式 |
|---|---|---|---|
| 1 | 企业版镜像包 `dist/images/*.tar` + `manifest.txt` | `scripts/build-multiarch.sh` 导出 | publish 流水线产物 |
| 2 | 客户许可证 `<客户>.lic` | 本 README「签发与密钥 SOP」四步流程 | 收机器指纹→sign→verify→台账截图归档 |
| 3 | 装机脚本 `scripts/deploy/install-enterprise.sh` | 仓库固化（T8-1） | 随包，客户机执行：校验→gen .env→起服→12 项内嵌自检 |
| 4 | 支持政策一页纸 `docs/support-policy.md` | 模板（T8-3），`__TBD__` 由销售填充 | 装配前人工确认价签已填 |

装机验收口径（对客演示）：
1. 干净 Linux/WSL 跑 `install-enterprise.sh`，脚本尾步打印 health/edition/登录页/license 入口四项 PASS；
2. 浏览器打开前端 → admin 一次性口令登录 → **强制改密页**（T4）；
3. 首页引导条显示机器指纹 →「复制给服务商」→ 上传随包 `.lic` → 激活成功横幅消失（T7-7b）；
4. `python -m pytest backend/tests/test_security_selfcheck.py -q` 12 项全绿随交付报告留档（T8-4）。

人工 checklist（脚本不代办）：超管一次性口令走加密通道单独发送；DeepSeek/旧模型 Key 现场确认已吊销；主体名/商标替换（挂起项）随签约裁决执行。
