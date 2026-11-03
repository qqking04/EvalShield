#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""EvalShield 推广文章自动生成器（技术分享向 · 短文案 800–900 字）。

单一事实源＝同目录 article_prompt_lite.txt（v11 无品牌名精简提示词）。本脚本只做
"喂动态变量"这一件事：读入 lite 提示词当 system，把「今天日期 + 当日选题(主题/角度/
读者/内容类型) + 当日主线痛点(从 pain_points.json 里按日序数选 1 条) + 需避开的最近
标题」拼成 user 消息，调用 OpenAI 兼容端点生成一篇短文 + 一条社媒短钩子，落到按日期
归档的目录。

设计口径：
- 写作规矩全在 lite 提示词里（硬门禁/回扣收口/标题反套路/痛点库/AI 检测率），改文风只动
  那一个文件，不碰本脚本。
- 痛点是"池"，每次只锁 1 条当主体（不注入全部）；痛点数据在 pain_points.json，改卖点/加
  痛点直接动那个文件。
- 数字只允许来自 lite 提示词的口径卡（几乎为零常量），脚本不再注入 facts.json，杜绝编数。
- 不注入 CTA/联系方式：短文案不含任何联系方式，人工发布时再自行补（符合"不自动发布"规矩）。

用法：
  python generate_article.py                # 用今天日期，真调 LLM 生成
  python generate_article.py --dry-run      # 只打印拼好的提示词，不调网络
  python generate_article.py --mock         # 本地无网络生成样例（验证流程用，正文标 [MOCK]）
  python generate_article.py --date 2026-10-25 --force
  python generate_article.py --list-topics  # 打印内容日历

环境变量（真调 LLM 时必需）：
  OPENAI_BASE_URL   默认 https://api.deepseek.com/v1
  OPENAI_API_KEY    必填
  OPENAI_MODEL      默认 deepseek-chat

仅用标准库，无第三方依赖。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
LITE_PROMPT_PATH = os.path.join(HERE, "article_prompt_lite.txt")  # 唯一提示词事实源
CALENDAR_PATH = os.path.join(HERE, "content_calendar.json")
PAIN_POINTS_PATH = os.path.join(HERE, "pain_points.json")
DEFAULT_OUTPUT = os.path.join(HERE, "output")
RUN_HISTORY_NAME = "_run_history.json"  # 跨运行追加历史，保证"每次运行"主题不重复（非每天）


# --------------------------------------------------------------------------- #
# 数据加载与选题轮换
# --------------------------------------------------------------------------- #
def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_dotenv(path):
    """从 .env 读 KEY=VALUE 注入 os.environ（已存在的系统环境变量优先，不覆盖）。

    仅为让 `文案一键生成.bat` 双击即可跑：把密钥写进同目录 .env 就行，不必配系统环境变量。
    纯标准库，不引第三方 dotenv。# 开头与空行跳过，值两侧引号去掉。
    """
    if not os.path.isfile(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val


def load_system_prompt():
    """读 lite 提示词当唯一 system prompt；文风/门禁/痛点库全在里面，脚本不改一个字。"""
    with open(LITE_PROMPT_PATH, "r", encoding="utf-8") as f:
        return f.read()


def load_pain_points():
    """企业真实痛点库；文件缺失/损坏时返回空列表，不阻断生成。"""
    if not os.path.isfile(PAIN_POINTS_PATH):
        return []
    try:
        data = load_json(PAIN_POINTS_PATH)
    except Exception:  # noqa: BLE001
        return []
    pts = data.get("pain_points", []) if isinstance(data, dict) else []
    return [p for p in pts if isinstance(p, dict)]


def pick_pain_point(pain_points, run_index):
    """按"第几次运行"选当日主线痛点（只锁 1 条当主体），返回 1 条 dict。

    为什么用 run_index 而不是「今年第几天」：选题本身按 (doy % 18) 轮换，痛点若也用
    (doy % 18)，两者周期相同(gcd=18)会锁死成"每个选题永远只配同一条痛点"(18 天一个死循环，
    只出 18 种组合)。这里用 run_index(=历史运行次数)推进，并加一个漂移项 run//n：每轮满一遍
    就把相位错开 1，从而与选题解耦。实测 72 次运行出 72 种(选题,痛点)组合、18 条痛点全轮到，
    且同一天多次运行也会换痛点（doy 方案同一天只会给同一条）。
    """
    if not pain_points:
        return None
    n = len(pain_points)
    idx = (run_index + run_index // n) % n
    return pain_points[idx]


def render_pain_point(pain):
    """把选中的 1 条痛点渲染成 user 消息里的紧凑块。"""
    if not pain:
        return "（今日无指定主线痛点：按提示词痛点库自行选 1 条最贴选题的当主体）"
    return (
        f"- 人群：{pain.get('persona','')}\n"
        f"- 处境（客户自己的话）：{pain.get('pain','')}\n"
        f"- 不解决的业务代价：{pain.get('cost','')}\n"
        f"- 疼到必须掏钱的时机：{pain.get('trigger','')}\n"
        f"- 我方能对上（定性、勿编数字）：{pain.get('our_answer','')}"
    )


def pick_topic(calendar, date, avoid_ids=()):
    """选题：以「当年第几天 % 条数」为起点向后找第一个"最近没用过"的主题。

    avoid_ids 为最近若干次运行用过的 topic_id；这样即使同一天多次运行，也会依次
    轮到不同主题，直到全部主题用遍才回到起点。avoid 为空时退化为纯日期轮换。
    """
    topics = calendar["topics"]
    n = len(topics)
    start = date.timetuple().tm_yday % n
    avoid = set(avoid_ids)
    for i in range(n):
        cand = topics[(start + i) % n]
        if cand["id"] not in avoid:
            return cand
    return topics[start]


def pick_seed_title(topic, date, n_topics):
    # 用 doy//n_topics 而非 week 或 doy：doy 与选题下标(doy%n_topics)同余会锁死成
    # "每个选题永远只用固定那一个种子标题"；除以选题数后再取模，能让一个选题的多个
    # 种子标题都轮到（实测 60 天内每选题用满 3 个种子，而非 1 个）。
    titles = topic["titles"]
    doy = date.timetuple().tm_yday
    idx = (doy // max(1, n_topics)) % len(titles)
    return titles[idx]


def load_history(output_dir):
    """读跨运行历史（append-only）。文件缺失时从既有 day/meta.json 引导，保证升级连续。"""
    path = os.path.join(output_dir, RUN_HISTORY_NAME)
    recs = []
    if os.path.isfile(path):
        try:
            data = load_json(path)
            if isinstance(data, list):
                recs = [r for r in data if isinstance(r, dict)]
        except Exception:  # noqa: BLE001
            recs = []
    if not recs and os.path.isdir(output_dir):
        for day in sorted(os.listdir(output_dir)):
            meta = os.path.join(output_dir, day, "meta.json")
            if os.path.isfile(meta):
                try:
                    m = load_json(meta)
                    recs.append({
                        "date": m.get("date", day),
                        "topic_id": m.get("topic_id", ""),
                        "title": m.get("title", ""),
                    })
                except Exception:  # noqa: BLE001
                    pass
    return recs


def append_history(output_dir, record):
    """把本次运行追加进历史；封顶最近 200 条，避免无限增长。"""
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, RUN_HISTORY_NAME)
    recs = []
    if os.path.isfile(path):
        try:
            data = load_json(path)
            if isinstance(data, list):
                recs = [r for r in data if isinstance(r, dict)]
        except Exception:  # noqa: BLE001
            recs = []
    recs.append(record)
    recs = recs[-200:]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(recs, f, ensure_ascii=False, indent=2)


def recent_topic_ids(history, n_topics):
    """最近 (n_topics-1) 次用过的主题 id —— 避开它们，保证轮到全部主题前不重复。"""
    k = max(1, n_topics - 1)
    return [r.get("topic_id", "") for r in history[-k:] if r.get("topic_id")]


def recent_titles(history, limit=20):
    """最近已用标题，喂给模型要求避开。"""
    return [r.get("title", "") for r in history[-limit:] if r.get("title")]


# --------------------------------------------------------------------------- #
# 提示词拼装（system＝lite 文件原样；user＝只喂动态变量，覆盖 lite 里的"自算日序数"）
# --------------------------------------------------------------------------- #
CONTENT_TYPES = ["A（authority·立观点：给读者一把评判供应商的尺子）",
                 "C（capability·亮肌肉：讲我们这套具体怎么解一个难点，落在代价与取舍）",
                 "R（result·给结果：读者能拿去汇报/复述的结果，不编数字不虚构客户）"]


def pick_content_type(date):
    """按「今年第几天 % 3」定当日内容类型，与 lite 提示词同口径，脚本算好直接喂，避免模型自算漂移。"""
    return CONTENT_TYPES[date.timetuple().tm_yday % len(CONTENT_TYPES)]


def build_user_prompt(topic, date, seed_title, recent_titles, pain_point, pain_text):
    avoid = "\n".join(f"- {t}" for t in recent_titles) if recent_titles else "（无）"
    date_str = date.strftime("%Y年%m月%d日")
    content_type = pick_content_type(date)
    return f"""今天日期：{date_str}

【重要】下面这几项已由脚本按日序数算好并锁定，直接用，不要再自己按"今年第几天 % 选题数"重算，
也不要换成别的选题/类型/痛点。system 提示词里凡是让你"自算当日角度/类型"的话，一律以本条为准：

- 当日内容类型（三选一，就用这个）：{content_type}
- 当日选题主题：{topic['theme']}
- 当日切入角度：{topic['angle']}
- 目标读者：{topic['reader']}
- 参考标题（只当灵感，别照抄句式；按【标题反套路】重拟一个更具体、更抓人、与下方"已用标题"都不同的新标题）：
  {seed_title}

【今日主线痛点（全文只以这一条为主体，不要铺第二条）】
{pain_text}
用法要求：
- 把这条痛点写成企业里真实发生的处境（带上它的业务代价与触发时机），当全文主线，别写成抽象功能诉求。
- 只在对得上时引用"我方能对上"那栏，且保持定性；不许借痛点编造数字、客户数、跑分，也不许承诺
  "重跑能得到同一判定"（留痕可追溯 ≠ 可复现同一结论，见 system 提示词纠偏#12）。
- 收尾按【回扣收口句】把这条痛点用因果收到"我们这套正好解在这"，不露品牌、不吹、不编数字。

【标题反套路（硬性，治"标题全长一个样"，细则见 system 提示词同名节）】
- 标题角度在 5 种间轮换，相邻两天不同种：① 数字/反差 ② 具体场景 ③ 反常识断言 ④ 直接提问 ⑤ 一个动作/名词。
- "不敢签/签字/背锅/被问住/黑箱/报告"每 5 天最多进 1 次标题；职业风险只进正文落点。
- 与下方"已用标题"比，句式或落点词雷同就换角度重拟。

【已用过的标题（新标题必须与这些都不一样）】
{avoid}

【输出规格（覆盖 system 里的通用描述，以本条为准）】
- 短文案：正文 800–900 汉字，Markdown，最多 0–1 个小标题，先过【出稿前硬门禁】全部可数红线。
- 全文不得出现任何项目名/公司名/产品名/品牌词/官网/链接/二维码/联系方式（邮箱/微信/私信占位都不要）；
  指代系统时用"本系统/该引擎/我们实现的这条链路"。结尾最多一句"评论区或私信聊"，不留任何联系方式。
- 数字只能用 system 口径卡给出的值（几乎为零常量），卡里没有的一律不写、不猜。

严格按以下分隔符输出，标签行不要改动：
===TITLE===
<新标题，单行，无品牌名>
===ARTICLE===
<800–900 字短文 Markdown 正文，无联系方式>
===SOCIAL===
<社媒短钩子：一个真争议点或开放提问，读者能一句表态；无品牌名、无联系方式>
===END===
"""


# --------------------------------------------------------------------------- #
# LLM 调用（OpenAI 兼容）
# --------------------------------------------------------------------------- #
def call_llm(system, user):
    base = os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
    key = os.getenv("OPENAI_API_KEY", "").strip()
    model = os.getenv("OPENAI_MODEL", "deepseek-chat").strip()
    if not key:
        raise SystemExit(
            "缺少 OPENAI_API_KEY 环境变量。请先设置，或用 --mock / --dry-run 验证流程。"
        )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": float(os.getenv("OPENAI_TEMPERATURE", "0.85")),
        "max_tokens": int(os.getenv("OPENAI_MAX_TOKENS", "2600")),
        "stream": False,
    }
    req = urllib.request.Request(
        base + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=int(os.getenv("OPENAI_TIMEOUT", "120"))) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:  # noqa: BLE001
        detail = e.read().decode("utf-8", "ignore")[:500]
        raise SystemExit(f"LLM 调用失败 HTTP {e.code}: {detail}")
    except urllib.error.URLError as e:  # noqa: BLE001
        raise SystemExit(f"网络错误（检查 OPENAI_BASE_URL/代理）: {e.reason}")
    try:
        return body["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        raise SystemExit(f"LLM 响应结构异常: {json.dumps(body)[:400]}")


def parse_output(raw):
    def section(start_marker, end_marker):
        pat = re.escape(start_marker) + r"\s*(.*?)\s*" + re.escape(end_marker)
        m = re.search(pat, raw, re.S)
        return m.group(1).strip() if m else ""

    title = section("===TITLE===", "===ARTICLE===")
    article = section("===ARTICLE===", "===SOCIAL===")
    social = section("===SOCIAL===", "===END===")
    if not (title and article):
        # 容错：模型没严格按格式时，整体当正文
        article = article or raw.strip()
        title = title or "今日技术分享"
    return title, article, social


# --------------------------------------------------------------------------- #
# Mock 生成（无网络自测：产出真实结构与体量，正文标注 MOCK；不含品牌名/联系方式）
# --------------------------------------------------------------------------- #
def mock_generate(topic, date, seed_title, pain_point):
    date_str = date.strftime("%Y-%m-%d")
    ctype = pick_content_type(date)
    persona = (pain_point or {}).get("persona", "做 AI 应用的团队")
    pain = (pain_point or {}).get("pain", "改了东西却不知道有没有把原来对的弄坏")
    cost = (pain_point or {}).get("cost", "返工、救火、被人追问时拿不出东西")
    answer = (pain_point or {}).get("our_answer", "把用例和判分口径固化下来，每次改动重跑同一套")
    title = f"{seed_title}（样例 {date_str}）"
    article = f"""> 本文为 **[MOCK 本地样例，未调用 LLM]**，仅验证流程、结构与体量；正式运行时删除本段，
> 正文由 LLM 依据 lite 提示词生成。当日类型：{ctype}。

{pain}——这大概是{persona}最熟悉的一种难受。

不是不会做，是没法确认。改完一版，谁也说不清原来答对的那些，还答不答得对。等到线上有人
截图来问，才知道坏了。{cost}。

说白了，缺的不是一个更聪明的模型，是一把每次都能重量的尺子。

我们这套的做法很笨：把用例固化下来，把判分口径也固化下来，每次改动就跑同一套。{answer}。
红绿摆在一起，哪几条翻了，一眼看到。

代价也得说清楚。固化意味着维护成本，用例过期了得有人管；判分口径写死了，遇到新场景要改，
不是万能钥匙。这块我们也还在补。

你怕的其实就是"改了不知道坏没坏"——我们这套干脆把这件事变成每次都能重跑的红绿对比，改完
先自己过一遍，心里有底再上。

下次要动手改之前，先问自己一句：这版和上版，我拿什么比？评论区聊聊你现在靠什么撑住这个"比"。
想看这套具体怎么落的，也可以聊。"""
    social = (
        f"改了 prompt 或换了模型底座，你怎么知道没把原来答对的弄坏？"
        f"靠人肉试几条，多半是上线后用户先发现。我们把用例和判分口径固化成能重跑的题库，"
        f"红绿可比——代价是用例得有人维护。你现在靠什么撑住这个'比'？评论区说说。"
    )
    return title, article, social


# --------------------------------------------------------------------------- #
# 落盘
# --------------------------------------------------------------------------- #
def slugify(text):
    # 去掉文件系统非法字符与常见标点，统一折叠为 -，避免标题里的 / : 等被当路径分隔符
    s = re.sub(r'[\\/:*?"<>|#*`>（）()，。、：:！？!?\-—\s]+', "-", text).strip("-")
    return (s[:40] or "article")


def write_outputs(output_dir, date, topic, title, article, social, meta):
    day_dir = os.path.join(output_dir, date.strftime("%Y-%m-%d"))
    os.makedirs(day_dir, exist_ok=True)
    slug = slugify(title)
    tid = topic.get("id", "topic")
    # 文件名带 topic_id：同一天多次运行（不同主题）互不覆盖
    article_path = os.path.join(day_dir, f"article-{tid}-{slug}.md")
    social_path = os.path.join(day_dir, f"social-{tid}-{slug}.md")
    meta_path = os.path.join(day_dir, f"meta-{tid}.json")
    with open(article_path, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n{article}\n")
    with open(social_path, "w", encoding="utf-8") as f:
        f.write(social + "\n")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return day_dir, [article_path, social_path, meta_path]


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def main(argv=None):
    ap = argparse.ArgumentParser(description="EvalShield 推广文章自动生成器")
    ap.add_argument("--date", help="生成日期 YYYY-MM-DD，默认今天")
    ap.add_argument("--output-dir", default=DEFAULT_OUTPUT, help="输出根目录")
    ap.add_argument("--force", action="store_true", help="已存在也重新生成")
    ap.add_argument("--dry-run", action="store_true", help="只打印提示词，不调网络、不写文件")
    ap.add_argument("--mock", action="store_true", help="本地生成样例（无网络，正文标 MOCK）")
    ap.add_argument("--list-topics", action="store_true", help="打印内容日历")
    args = ap.parse_args(argv)

    load_dotenv(os.path.join(HERE, ".env"))
    calendar = load_json(CALENDAR_PATH)
    calendar.pop("_comment", None)

    if args.list_topics:
        for i, t in enumerate(calendar["topics"]):
            print(f"[{i:02d}] {t['id']}  ·  {t['theme']}  ·  {t['angle'][:36]}")
        print(f"\n共 {len(calendar['topics'])} 条选题。每次运行以「当年第几天 % 条数」为起点，"
              f"自动避开最近用过的主题，直到全部轮遍（同日多跑也不重复）。")
        return 0

    if args.date:
        try:
            date = dt.datetime.strptime(args.date, "%Y-%m-%d").date()
        except ValueError:
            raise SystemExit(f"非法日期 {args.date!r}，需 YYYY-MM-DD 且为真实存在的日期")
    else:
        date = dt.date.today()

    n_topics = len(calendar["topics"])
    history = load_history(args.output_dir)
    avoid = recent_topic_ids(history, n_topics)
    topic = pick_topic(calendar, date, avoid)
    seed_title = pick_seed_title(topic, date, n_topics)
    recent = recent_titles(history, 20)
    pain_point = pick_pain_point(load_pain_points(), len(history))
    pain_text = render_pain_point(pain_point)
    system = load_system_prompt()
    user = build_user_prompt(topic, date, seed_title, recent, pain_point, pain_text)

    if args.dry_run:
        print("=" * 70)
        print(f"日期 {date}  选题 {topic['id']}（{topic['theme']}）  内容类型 {pick_content_type(date)[:1]}")
        print(f"种子标题：{seed_title}")
        print(f"主线痛点：{(pain_point or {}).get('id', '（无）')}  最近已用标题避开数：{len(recent)}")
        print("=" * 70)
        print("--- SYSTEM（article_prompt_lite.txt 原样）---\n")
        print(system)
        print("\n--- USER ---\n")
        print(user)
        return 0

    if args.mock:
        title, article, social = mock_generate(topic, date, seed_title, pain_point)
        gen_by = "mock"
    else:
        raw = call_llm(system, user)
        title, article, social = parse_output(raw)
        gen_by = "llm"

    day_dir = os.path.join(args.output_dir, date.strftime("%Y-%m-%d"))
    meta = {
        "date": date.strftime("%Y-%m-%d"),
        "topic_id": topic["id"],
        "theme": topic["theme"],
        "content_type": pick_content_type(date)[:1],
        "pain_id": (pain_point or {}).get("id", ""),
        "seed_title": seed_title,
        "title": title,
        "generated_by": gen_by,
        "system_prompt": os.path.basename(LITE_PROMPT_PATH),
        "note": "短文案不含联系方式；人工发布前自行核对事实并补 CTA。",
    }
    meta_name = f"meta-{topic['id']}.json"
    if os.path.isdir(day_dir) and os.path.isfile(os.path.join(day_dir, meta_name)) and not args.force:
        print(f"今天已生成过该主题（{day_dir}/{meta_name}）；用 --force 覆盖。")
        return 0

    _, paths = write_outputs(args.output_dir, date, topic, title, article, social, meta)
    append_history(args.output_dir, {
        "ts": dt.datetime.now().isoformat(timespec="seconds"),
        "date": date.strftime("%Y-%m-%d"),
        "topic_id": topic["id"],
        "title": title,
    })
    print(f"[{gen_by}] {date} 选题={topic['id']} 标题={title}")
    for p in paths:
        print("  ->", os.path.relpath(p, HERE).replace(os.sep, "/"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
