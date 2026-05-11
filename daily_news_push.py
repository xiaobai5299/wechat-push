"""
企业微信新闻推送 - textcard版
抓取 CLS 新闻 → 生成HTML → 推送到GitHub Pages → 发送textcard到企业微信
支持分时段推送：
  午盘 12:45 → 当天 00:00~12:45
  盘前 8:45 → 前一天 12:45~当天 8:45
"""
import requests
import logging
import hashlib
import re
import os
import base64
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== 企业微信配置 ====================
CORPID = os.environ.get("WECHAT_CORPID", "")
SECRET = os.environ.get("WECHAT_SECRET", "")
AGENTID = os.environ.get("WECHAT_AGENTID", "")
TO_USER = os.environ.get("WECHAT_TOUSER", "")

# ==================== GitHub Pages 配置 ====================
GITHUB_TOKEN = os.environ.get("GH_TOKEN", "")
GITHUB_REPO = "xiaobai5299/wechat-push"
PAGES_URL = "https://xiaobai5299.github.io/wechat-push/"


class WeChatAPI:
    def __init__(self, corpid, secret, agentid):
        self.corpid = corpid
        self.secret = secret
        self.agentid = agentid
        self.access_token = None

    def _get_token(self):
        url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={self.corpid}&corpsecret={self.secret}"
        res = requests.get(url).json()
        if "access_token" in res:
            self.access_token = res["access_token"]
            return self.access_token
        else:
            raise Exception(f"获取access_token失败: {res}")

    def send_textcard(self, to_user, title, description, url):
        """发送文本卡片消息（个人微信可正常显示）"""
        if not self.access_token:
            self._get_token()
        api_url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={self.access_token}"
        if isinstance(to_user, list):
            to_user = "|".join(to_user)
        data = {
            "touser": to_user,
            "msgtype": "textcard",
            "agentid": self.agentid,
            "textcard": {
                "title": title,
                "description": description,
                "url": url,
                "btntxt": "查看详情"
            }
        }
        res = requests.post(api_url, json=data).json()
        if res.get("errcode") == 0:
            logger.info(f"Textcard消息发送成功: {to_user}")
            return True
        else:
            logger.error(f"Textcard消息发送失败: {res}")
            return False


class ClsSpider:
    def __init__(self):
        self.api_url = "https://www.cls.cn/v1/roll/get_roll_list"
        self.all_news_data = []
        self.keywords_config = {
            "猪肉涨价": {
                "keywords": ["猪肉", "猪价", "生猪", "肉价上涨", "猪周期", "猪肉价格", "猪瘟", "能繁母猪", "仔猪"]
            },
            "A股重组": {
                "keywords": ["重组", "收购", "并购", "资产注入", "股权转让", "借壳", "合并", "重大资产"]
            },
            "订单": {
                "keywords": ["订单", "中标", "合同", "签约", "大单"]
            }
        }
        self.stock_code_pattern = re.compile(r'[60|30|00|68]\d{4}')
        self.stock_name_pattern = re.compile(
            r'[\u4e00-\u9fa5]{2,4}(?:股份|集团|科技|控股|生物|医药|证券|银行|保险|能源|汽车|地产)'
        )

    def _generate_sign(self, params):
        sorted_keys = sorted(k for k in params if k != "sign")
        query_string = "&".join(f"{k}={params[k]}" for k in sorted_keys if params[k] is not None)
        return hashlib.md5(hashlib.sha1(query_string.encode()).hexdigest().encode()).hexdigest()

    def extract_title_content(self, content):
        if content.startswith("【") and "】" in content:
            end_idx = content.find("】")
            return content[1:end_idx].strip(), content[end_idx + 1:].strip()
        return "", content.strip()

    def has_stock_info(self, text):
        return bool(self.stock_code_pattern.search(text) or self.stock_name_pattern.search(text))

    def check_order_amount(self, text):
        for pattern in [r'(\d+\.?\d*)\s*亿', r'(\d+\.?\d*)\s*千万', r'(\d+\.?\d*)\s*万',
                        r'逾\s*\d+', r'超\s*\d+', r'达\s*\d+']:
            if re.search(pattern, text):
                return True
        return False

    def classify_news(self, title, body):
        text = f"{title} {body}".lower()
        for kw in self.keywords_config["猪肉涨价"]["keywords"]:
            if kw in text:
                return "猪肉涨价"
        for kw in self.keywords_config["订单"]["keywords"]:
            if kw in text and self.check_order_amount(text):
                return "订单"
        for kw in self.keywords_config["A股重组"]["keywords"]:
            if kw in text and self.has_stock_info(text):
                return "A股重组"
        return "其他"

    def extract_future_time(self, text):
        """从新闻内容中提取未来的确切时间节点（严格大于今天）"""
        today = datetime.now()
        candidates = []

        for m in re.finditer(r'(\d{4})年(\d{1,2})月(\d{1,2})日', text):
            try:
                d = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                candidates.append((d, m.group(0)))
            except:
                pass

        for m in re.finditer(r'(\d{4})-(\d{2})-(\d{2})', text):
            try:
                d = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                candidates.append((d, m.group(0)))
            except:
                pass

        for m in re.finditer(r'(\d{1,2})月(\d{1,2})日', text):
            month_str, day_str = m.group(1), m.group(2)
            try:
                d = datetime(today.year, int(month_str), int(day_str))
                label = m.group(0)
                already_exists = any(c[1].endswith(f"年{label}") for c in candidates)
                if not already_exists:
                    candidates.append((d, label))
            except:
                pass

        for m in re.finditer(r'(?:预计|将于|拟于|计划|定于|将在)?(\d{1,2})月(?![0-9])(?:份)?', text):
            month_str, month_num = m.group(1), int(m.group(1))
            prefix = text[:m.start()]
            last_pause = max(prefix.rfind('。'), prefix.rfind('；'), prefix.rfind('，'), 0)
            surrounding = text[last_pause:m.end() + 5]
            year_match = re.search(r'(\d{4})年', surrounding)
            if year_match:
                year = int(year_match.group(1))
                if year < today.year:
                    continue
                d = datetime(year, month_num, 1)
            else:
                d = datetime(today.year, month_num, 1)
            if f"{month_str}月" not in [c[1] for c in candidates]:
                candidates.append((d, f"{month_str}月"))

        quarter_map = {
            "Q1": (1, "Q1"), "Q2": (4, "Q2"), "Q3": (7, "Q3"), "Q4": (10, "Q4"),
            "第一季度": (1, "第一季度"), "第二季度": (4, "第二季度"),
            "第三季度": (7, "第三季度"), "第四季度": (10, "第四季度"),
        }
        for keyword, (month, label) in quarter_map.items():
            if keyword in text:
                d = datetime(today.year, month, 1)
                candidates.append((d, label))

        if "上半年" in text:
            candidates.append((datetime(today.year, 1, 1), "上半年"))
        if "下半年" in text:
            candidates.append((datetime(today.year, 7, 1), "下半年"))

        for m in re.finditer(r'(\d{4})年', text):
            year = int(m.group(1))
            if year > today.year:
                candidates.append((datetime(year, 1, 1), m.group(0)))

        for m in re.finditer(r'(?:^|[^0-9])(20\d{2})(?:/|、|，|。|\s|$)', text):
            year = int(m.group(1))
            if year > today.year:
                label = f"{year}年"
                if label not in [c[1] for c in candidates]:
                    candidates.append((datetime(year, 1, 1), label))

        if "明年" in text:
            candidates.append((datetime(today.year + 1, 1, 1), "明年"))
        if "后年" in text:
            candidates.append((datetime(today.year + 2, 1, 1), "后年"))

        future_times = []
        for d, label in candidates:
            if d.date() > today.date():
                if label not in future_times:
                    future_times.append(label)
            elif d.year == today.year and d.month > today.month and label.endswith("月"):
                if label not in future_times:
                    future_times.append(label)

        future_times_sorted = sorted(future_times, key=lambda x: (
            int(re.search(r'(\d{4})', x).group(1)) if re.search(r'(\d{4})', x) else 0,
            int(re.search(r'(?<!\d)(\d{1,2})月', x).group(1)) if re.search(r'(?<!\d)(\d{1,2})月', x) else 0
        ))
        return future_times_sorted

    def process_data(self, roll_data, target_date, start_hour=None, end_hour=None):
        if not roll_data:
            return 0
        saved = 0
        for item in roll_data:
            ctime = item.get("ctime", 0)
            publish_time = datetime.fromtimestamp(ctime)
            # 日期过滤
            if publish_time.strftime("%Y-%m-%d") != target_date:
                continue
            # 小时过滤
            if start_hour is not None and publish_time.hour < start_hour:
                continue
            if end_hour is not None and publish_time.hour > end_hour:
                continue

            content = item.get("content", "")
            title, body = self.extract_title_content(content)
            event_type = self.classify_news(title, body)

            if event_type == "其他":
                continue

            future_times = []
            if event_type == "猪肉涨价":
                pass
            if event_type in ["A股重组", "订单"]:
                future_times = self.extract_future_time(body)
                if not future_times:
                    continue

            self.all_news_data.append({
                "时间": publish_time.strftime("%Y-%m-%d %H:%M"),
                "类型": event_type,
                "标题": title,
                "内容": body,
                "未来时间": future_times
            })
            saved += 1
        return saved

    def run(self, target_date, start_hour=None, end_hour=None):
        self.all_news_data = []
        start_ts = int(datetime.strptime(
            f"{target_date} {start_hour or 0:02d}:00:00", "%Y-%m-%d %H:%M:%S"
        ).timestamp())
        end_ts = int(datetime.strptime(
            f"{target_date} {end_hour or 23:02d}:59:59", "%Y-%m-%d %H:%M:%S"
        ).timestamp())
        cursor = end_ts
        page = 1
        total = 0
        while True:
            params = {
                "app": "CailianpressWeb",
                "lastTime": cursor,
                "last_time": cursor,
                "os": "web",
                "refresh_type": "1",
                "rn": "50",
                "sv": "8.4.6"
            }
            params["sign"] = self._generate_sign(params)
            resp = requests.get(self.api_url, params=params, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code != 200:
                break
            data = resp.json()
            if data.get("errno") != 0:
                break
            roll_list = data.get("data", {}).get("roll_data", [])
            if not roll_list:
                break
            saved = self.process_data(roll_list, target_date, start_hour, end_hour)
            total += saved
            min_ctime = min(item["ctime"] for item in roll_list)
            if min_ctime < start_ts:
                break
            cursor = min(min_ctime, cursor - 1)
            page += 1
        return self.all_news_data


def generate_html(news_data, target_date, push_mode):
    """生成完整新闻HTML页面"""
    related = [n for n in news_data if n["类型"] != "其他"]

    pork = [n for n in related if n["类型"] == "猪肉涨价"]
    mna = [n for n in related if n["类型"] == "A股重组"]
    order = [n for n in related if n["类型"] == "订单"]

    type_config = {
        "猪肉涨价": {"emoji": "🐷", "color": "#e74c3c"},
        "A股重组": {"emoji": "🔄", "color": "#e67e22"},
        "订单": {"emoji": "📦", "color": "#27ae60"}
    }

    now = datetime.now()
    if push_mode == "afternoon":
        sub_title = f"午盘推送 | 新闻范围：当天 00:00~12:45"
        page_title = "午盘新闻推送"
    else:
        sub_title = f"盘前推送 | 新闻范围：前一天 12:45~当天 8:45"
        page_title = "盘前新闻推送"

    news_items_html = ""
    for label, items in [("猪肉涨价", pork), ("A股重组", mna), ("订单", order)]:
        if not items:
            continue
        cfg = type_config[label]
        news_items_html += f'<div class="section"><h2 class="section-title">{cfg["emoji"]} {label}（{len(items)}条）</h2>'

        for i, n in enumerate(items):
            title = n['标题'] if n['标题'] else ""
            body = n['内容'] if n['内容'] else ""
            news_time = n.get('时间', '')
            future_times = n.get('未来时间', [])

            body_html = body
            for ft in future_times:
                if ft in body_html:
                    body_html = body_html.replace(ft, f'<span class="future-highlight">{ft}</span>')

            time_below_html = ""
            if future_times:
                times_str = "、".join(future_times)
                time_below_html = f'<div class="future-time">⏰ 新闻提及未来时间：{times_str}</div>'

            title_html = f'<div class="news-title">{title}</div>' if title else ""

            news_items_html += f"""
                <div class="news-card">
                    <div class="news-number">{i+1}</div>
                    <div class="news-content">
                        <div class="news-meta">
                            <span class="type-badge" style="background:{cfg['color']};color:#fff">{label}</span>
                            <span class="news-time">{news_time}</span>
                        </div>
                        {title_html}
                        <div class="news-body">{body_html}</div>
                        {time_below_html}
                    </div>
                </div>"""

        news_items_html += '</div>'

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{page_title} - {target_date}</title>
<style>
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#f5f5f5;padding:20px;color:#333}}
  .container{{max-width:800px;margin:0 auto}}
  .header{{text-align:center;margin-bottom:20px;padding:20px;background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;border-radius:12px}}
  .header h1{{font-size:22px;margin-bottom:5px}}
  .header .date{{font-size:14px;opacity:0.9}}
  .header .stats{{margin-top:10px;font-size:14px}}
  .section{{margin-bottom:15px}}
  .section-title{{font-size:18px;color:#2c3e50;margin-bottom:10px;padding-bottom:8px;border-bottom:2px solid #eee}}
  .news-card{{display:flex;background:#fff;border-radius:10px;padding:15px;margin-bottom:10px;box-shadow:0 1px 4px rgba(0,0,0,0.06)}}
  .news-number{{width:28px;height:28px;background:#667eea;color:#fff;border-radius:50%;text-align:center;line-height:28px;font-size:13px;font-weight:bold;margin-right:12px;flex-shrink:0}}
  .news-content{{flex:1}}
  .news-meta{{display:flex;align-items:center;gap:8px;margin-bottom:6px}}
  .type-badge{{display:inline-block;padding:2px 10px;border-radius:12px;font-size:12px;font-weight:bold}}
  .news-time{{font-size:12px;color:#999}}
  .news-title{{font-size:16px;font-weight:bold;margin-bottom:6px;line-height:1.4}}
  .news-body{{font-size:14px;color:#555;line-height:1.8}}
  .future-time{{margin-top:6px;font-size:13px;color:#e67e22}}
  .future-highlight{{color:#e67e22;font-weight:bold;border-bottom:1px dashed #e67e22}}
  .footer{{text-align:center;color:#bbb;font-size:12px;margin-top:20px;padding:15px 0}}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>📊 {page_title}</h1>
    <div class="date">{sub_title}</div>
    <div class="stats">相关新闻 {len(related)} 条 | 🐷猪肉{len(pork)} | 🔄重组{len(mna)} | 📦订单{len(order)}</div>
  </div>
  {news_items_html}
  <div class="footer">🤖 自动生成 · 数据来源：财联社</div>
</div>
</body>
</html>"""
    return html


def generate_summary(news_data, push_mode):
    """生成textcard的描述文字"""
    related = [n for n in news_data if n["类型"] != "其他"]
    if not related:
        return "暂无相关新闻", "暂无相关新闻"

    pork = sum(1 for n in related if n["类型"] == "猪肉涨价")
    mna = sum(1 for n in related if n["类型"] == "A股重组")
    order = sum(1 for n in related if n["类型"] == "订单")

    mode_text = "午盘" if push_mode == "afternoon" else "盘前"
    card_title = f"📊 {mode_text}新闻推送 - {datetime.now().strftime('%Y-%m-%d')}"

    lines = [
        f"相关新闻：{len(related)}条",
        f"🐷猪肉涨价：{pork}条",
        f"🔄A股重组：{mna}条",
        f"📦订单：{order}条",
    ]

    for i, n in enumerate(related[:3]):
        title_text = n['标题'][:30] if n['标题'] else "无标题"
        lines.append(f"{i+1}. {title_text}")

    return card_title, "\n".join(lines)


def upload_to_github(html_content, filename):
    """将HTML上传到GitHub仓库根目录"""
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{filename}"

    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    resp = requests.get(api_url, headers=headers)
    sha = resp.json().get("sha") if resp.status_code == 200 else None

    content_base64 = base64.b64encode(html_content.encode('utf-8')).decode('utf-8')
    body = {
        "message": f"更新新闻 {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "content": content_base64
    }
    if sha:
        body["sha"] = sha

    resp = requests.put(api_url, headers=headers, json=body)
    if resp.status_code in [200, 201]:
        print(f"✅ HTML已上传: {filename}")
        return True
    else:
        print(f"❌ 上传失败: {resp.json()}")
        return False


if __name__ == "__main__":
    PUSH_MODE = os.environ.get("PUSH_MODE", "morning")
    now = datetime.now()
    spider = ClsSpider()

    if PUSH_MODE == "morning":
        # 盘前 8:45：前一天 12:45 ~ 今天 8:45
        yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        today = now.strftime("%Y-%m-%d")

        print(f"📅 盘前推送：抓取 {yesterday} 12:45~23:59 和 {today} 00:00~8:45")
        news_yesterday = spider.run(yesterday, start_hour=12, end_hour=23)
        news_today = spider.run(today, start_hour=0, end_hour=8)
        news_data = news_yesterday + news_today

        # 文件名用今天的日期 + morning
        filename = f"{today}-morning.html"
        page_date = f"{yesterday} 12:45 ~ {today} 8:45"
    else:
        # 午盘 12:45：当天 0:00 ~ 12:45
        today = now.strftime("%Y-%m-%d")
        print(f"📅 午盘推送：抓取 {today} 00:00~12:45")
        news_data = spider.run(today, start_hour=0, end_hour=12)

        filename = f"{today}-afternoon.html"
        page_date = f"{today} 00:00~12:45"

    print(f"✅ 共抓取 {len(news_data)} 条新闻")

    html_content = generate_html(news_data, page_date, PUSH_MODE)

    print("📤 上传到 GitHub Pages...")
    # 上传当次推送的专属页面
    upload_to_github(html_content, filename)
    # # 同时更新首页
    # upload_to_github(html_content, "index.html")

    # 本次推送的完整 URL
    page_url = f"{PAGES_URL}{filename}"

    print("📤 发送消息...")
    api = WeChatAPI(CORPID, SECRET, AGENTID)
    card_title, description = generate_summary(news_data, PUSH_MODE)

    result = api.send_textcard(TO_USER, card_title, description, page_url)
    print(f"发送结果: {result}")

    # print("完成测试")
