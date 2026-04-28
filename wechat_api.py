import requests
import logging

from core.config import *

logging.basicConfig(level=logging.INFO)

class WeChatAPI:
    def __init__(self, corpid=None, secret=None, agentid=None):
        self.corpid = corpid or get_wechat_corpid()
        self.secret = secret or get_wechat_secret()
        self.agentid = agentid or get_wechat_agentid()
        self.logger = logging.getLogger(__name__)
        self.access_token = None

    def _get_token(self):
        url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={self.corpid}&corpsecret={self.secret}"
        res = requests.get(url).json()
        if "access_token" in res:
            self.access_token = res["access_token"]
            return self.access_token
        else:
            raise Exception(f"获取access_token失败: {res}")

    def send_message(self, to_user, content):
        if not self.access_token:
            self._get_token()
        url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={self.access_token}"
        if isinstance(to_user, list):
            to_user = "|".join(to_user)
        data = {
            "touser": to_user,
            "msgtype": "text",
            "agentid": self.agentid,
            "text": {"content": content}
        }
        res = requests.post(url, json=data).json()
        if res.get("errcode") == 0:
            self.logger.info(f"微信消息发送成功: {to_user}")
            return True
        else:
            self.logger.error(f"微信消息发送失败: {res}")
            return False

    def send_message_markdown(self, to_user, content):
        if not self.access_token:
            self._get_token()
        url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={self.access_token}"
        if isinstance(to_user, list):
            to_user = "|".join(to_user)
        data = {
            "touser": to_user,
            "msgtype": "markdown",
            "agentid": self.agentid,
            "markdown": {"content": content}
        }
        res = requests.post(url, json=data).json()
        if res.get("errcode") == 0:
            self.logger.info(f"微信消息发送成功: {to_user}")
            return True
        else:
            self.logger.error(f"微信消息发送失败: {res}")
            return False


if __name__ == "__main__":
    api = WeChatAPI()

    content = "今日主题：科技创新\n" \
              "相关股票：\n" \
              "- 阿里巴巴 (BABA)：涨幅 +3.5%\n" \
              "- 百度 (BIDU)：跌幅 -1.2%\n" \
              "- 京东 (JD)：涨幅 +0.8%\n" \
              "市场分析：科技板块整体表现强劲，投资者情绪乐观。"

    user = "FanZhe"

    result = api.send_message(user, content)
    print("发送结果:", result)