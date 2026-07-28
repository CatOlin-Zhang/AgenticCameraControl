"""
本地授权服务器配置

Skill 通过读取本模块获取本地授权服务器地址，用于:
  - request_cloud_auth()  → POST /api/auth/request
  - poll_auth_status()    → GET  /api/auth/status
"""

import os

# 本地授权服务器地址（可通过环境变量 LOCAL_AUTH_URL 覆盖）
LOCAL_AUTH_URL = os.environ.get("LOCAL_AUTH_URL", "http://127.0.0.1:18899")

# 授权请求超时（秒）
AUTH_REQUEST_TIMEOUT = 10.0

# 轮询间隔（秒）
POLL_INTERVAL = 5.0

# 最大轮询等待时间（秒）
POLL_MAX_WAIT = 120.0
