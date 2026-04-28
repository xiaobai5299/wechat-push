import os

def get_wechat_corpid():
    return os.environ.get("WECHAT_CORPID", "")

def get_wechat_secret():
    return os.environ.get("WECHAT_SECRET", "")

def get_wechat_agentid():
    return os.environ.get("WECHAT_AGENTID", "")