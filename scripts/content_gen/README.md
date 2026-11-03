# EvalShield 推广文章自动生成器

每次运行自动生成一篇**短文案（800–900 字）+ 一条社媒短钩子**，**每次运行**主题都不同
（不限于每天——同日多跑也依次轮换）。写作规矩（硬门禁/回扣收口/标题反套路/痛点库/去 AI 味）
**全部集中在 `article_prompt_lite.txt` 这一个提示词文件里**，脚本只负责喂动态变量
（日期、当日选题、当日主线痛点、需避开的最近标题）。改文风只动提示词，不碰脚本。

> 短文案不含任何联系方式/品牌名；数字只允许来自提示词口径卡（几乎为零常量），脚本不再注入
> `facts.json`，从源头杜绝编数。人工发布前自行核对事实并补 CTA。

## 文件
- `generate_article.py` — 主生成器（纯标准库，无第三方依赖）
- `article_prompt_lite.txt` — **唯一提示词事实源**（v11 无品牌名精简版，被脚本原样当 system
  prompt 读入）；改文风/门禁/痛点写法都动这里
- `article_prompt.txt` — 长文完整版提示词（手动路径用，脚本不读）
- `content_calendar.json` — 选题日历（增删条目即换内容方向；每次运行以 `当年第几天 % 条数`
  为起点、避开最近用过的主题）
- `pain_points.json` — 企业真实痛点库（人群/真实处境/业务代价/触发时机/我方能力）。脚本每次
  运行只从中**选 1 条**当全文主体注入（不是全部）。加/改痛点动这里。
- `facts.json` — 旧长文路径的事实库；当前短文案脚本已不再读取（保留给 `article_prompt.txt` 手动路径）
- `.env.example` — 环境变量示例
- `output/YYYY-MM-DD/` — 按日期归档，文件名带主题 id 便于同日多跑并存：
  `article-<topic_id>-*.md`、`social-<topic_id>-*.md`、`meta-<topic_id>.json`
- `output/_run_history.json` — 跨运行追加历史（topic_id + 标题），驱动"每次运行主题不重复"

## 用法
```bash
cd scripts/content_gen
export OPENAI_API_KEY=sk-xxx            # 真跑必填（见 .env.example）
python generate_article.py              # 生成今天
python generate_article.py --dry-run    # 只看拼好的提示词，不调网络
python generate_article.py --mock       # 本地无网络出样例（验证流程，正文标 [MOCK]）
python generate_article.py --date 2026-11-03 --force   # 补某天 / 覆盖
python generate_article.py --list-topics# 查看选题日历
```

## 一键生成（Windows 双击）
双击 `文案一键生成.bat` 即生成一篇新短文案到 `output\当天日期\`，**每点一次换一篇**
（自动轮换选题与主线痛点，同日多跑不覆盖）。要点：
- 真跑需要密钥：把同目录 `.env.example` 复制为 `.env`，填 `OPENAI_API_KEY`（脚本会自动读 `.env`，
  不必再配系统环境变量）。没配密钥会提示并失败。
- 想先看拼装效果、不联网：在命令行运行 `文案一键生成.bat --dry-run`；本地无网样例用
  `--mock`。可附加任意 `generate_article.py` 参数（如 `--date 2026-11-03 --force`）。
- `.bat` 内文保持纯 ASCII（中文提示由 Python 输出），以免 cmd 在 GBK 代码页下解析出错——改这个
  文件时不要往里写中文。

### 轮换怎么保证不重复
- **选题**：以「当年第几天 % 条数」为起点，按 `_run_history.json` 避开最近用过的主题（轮遍
  全部才回到起点）；同一天多次运行依次拿到不同主题，互不覆盖。
- **标题变体**：同选题内按 `(doy // 条数) % 变体数` 轮换（不用 `doy % 变体数`——会和选题
  下标同余锁死）；再把最近已用标题喂给模型要求避开。
- **主线痛点**：按**运行次数** `(run_index + run_index // 痛点数) % 痛点数` 选（`run_index` =
  历史条数）。不用「当年第几天 % 痛点数」——那样会和选题的 `%18` 同周期锁死成"每个选题永远配
  同一条痛点"。加 `run_index // 痛点数` 漂移项后，实测 90 次运行 18 条痛点全轮到、
  (选题,痛点) 组合持续变化，同日多跑也换痛点。
- **内容类型 A/C/R**：脚本按 `当年第几天 % 3` 算好直接喂，与提示词同口径，免得模型自算漂移。

## 定时运行

### Linux / macOS（cron，每天 08:30）
```cron
30 8 * * * cd /path/to/EvalShield/scripts/content_gen && OPENAI_API_KEY=sk-xxx /usr/bin/python generate_article.py >> output/run.log 2>&1
```

### Windows（任务计划程序，每天 08:30）
```
程序或脚本:  python
添加参数:    "E:\code\EvalShield\scripts\content_gen\generate_article.py"
起始于:      E:\code\EvalShield\scripts\content_gen
```
或一次性用 schtasks 注册：
```bat
schtasks /Create /TN EvalShieldArticle /TR "python E:\code\EvalShield\scripts\content_gen\generate_article.py" /SC DAILY /ST 08:30
```

## 上线前人工把关（建议保留这道关）
生成器不做自动发布。每天产出后建议人工：
1. 通读去口播感、确认没有口径卡之外的数字；
2. 核对引用的外部工具/标准描述无误；
3. 短文案本身不含联系方式——按各平台规则自行补 CTA（评论区/私信引导或主页链接）；
4. 再复制到各平台发布。

## 说明
本工具只做内容生成，不改动后端 `app/engines/` 等受工程锁保护目录，不引入 i18n/支付依赖。
