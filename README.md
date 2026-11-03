# EvalShield 社区版（Community Edition）

![oss-ci](https://github.com/qqking04/EvalShield/actions/workflows/ci.yml/badge.svg)

EvalShield 是 **LLM / AI 应用评测与审计工作台**：数据流测试、用例编排、评测引擎、报告交付的一体化平台。

本仓库为 **社区版（Apache-2.0）**，开箱即用：

```bash
# 后端
cd backend && pip install -r requirements.txt
EDITION=community SECRET_KEY=<强随机值> python -m uvicorn app.main:app

# 前端
cd frontend && npm install && npm run build
```

## 版本形态（open-core）

| 能力 | 社区版（本仓） | 企业版 / SaaS（商业许可） |
|---|---|---|
| 评测引擎、用例管理、报告生成 | ✅ | ✅ |
| 多租户、License 管理、计费 | ❌ | ✅ |
| SaaS 托管、源码审计工作台 | ❌ | ✅ |

商业版入口与功能矩阵见应用内升级引导页（CommercialPlaceholder）。商业许可咨询：提交 Issue，条款详见 [LICENSE](./LICENSE) 中的双许可声明。

## 社区参与

- **Issue**：缺陷、功能建议均可；提交前请检索已有 Issue。
- **PR**：请先开 Issue 讨论；贡献流程与代码规范见 [CONTRIBUTING.md](./CONTRIBUTING.md)（如存在）。
- 本仓库由发布流水线从上游完整代码库**定期快照发布**，不接受直接改商业边界相关代码的 PR。

## 许可

- 社区版代码：Apache-2.0（见 [LICENSE](./LICENSE)）
- 企业版 / SaaS 增量：EvalShield Commercial License（闭源，不在本仓库）

> 本 README 属社区投影文档；深度部署与运维文档随企业版交付。
