#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞书多维表格写入代理 - ChatGPT Actions 中间层
部署后, ChatGPT 自定义 GPT 通过 Actions 调用本服务, 由本服务写入飞书多维表格。
"""
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx, time, os
from datetime import datetime

# ===== 配置(从环境变量读, 不要硬编码) =====
APP_ID = os.getenv("FEISHU_APP_ID", "cli_aa554bd7c3395ce3")
APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")
APP_TOKEN = os.getenv("FEISHU_APP_TOKEN", "O6IfbMyHHaui3HsiiENcgKTPnxb")
TABLE_ID = os.getenv("FEISHU_TABLE_ID", "tblptWtO4QTuv4OB")
PROXY_API_KEY = os.getenv("PROXY_API_KEY", "change-this-to-a-random-string")
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "")

BASE = "https://open.feishu.cn/open-apis"

app = FastAPI(title="Feishu Bitable Proxy")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

_token_cache = {"token": None, "expires": 0}


def get_token() -> str:
    if _token_cache["token"] and time.time() < _token_cache["expires"] - 120:
        return _token_cache["token"]
    r = httpx.post(
        f"{BASE}/auth/v3/tenant_access_token/internal",
        json={"app_id": APP_ID, "app_secret": APP_SECRET},
        timeout=10,
    )
    data = r.json()
    if data.get("code") != 0:
        raise HTTPException(500, f"Feishu token error: {data}")
    _token_cache["token"] = data["tenant_access_token"]
    _token_cache["expires"] = time.time() + data["expire"]
    return _token_cache["token"]


def to_ms_timestamp(value):
    """把 '2026-10-27' 或 '2026-10-27 14:30' 转成毫秒时间戳"""
    if isinstance(value, (int, float)):
        return int(value)
    if not isinstance(value, str):
        return value
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(value, fmt)
            return int(dt.timestamp() * 1000)
        except ValueError:
            continue
    return value


@app.post("/bitable/records")
def create_record(body: dict, x_api_key: str = Header(None)):
    if x_api_key != PROXY_API_KEY:
        raise HTTPException(401, "invalid api key")
    if not APP_SECRET:
        raise HTTPException(500, "FEISHU_APP_SECRET not set")

    # 兼容两种格式: {"fields": {...}} 或平铺的 {...}
    fields = body.get("fields", body)

    # Coze 英文参数名 → 飞书中文列名映射
    NAME_MAP = {
        "ID": "记录ID",
        "DATE": "监测日期",
        "WINDOW": "监测窗口",
        "ACCOUNT": "账户",
        "ADLEVEL": "层级",
        "NAME": "广告组名称",
        "GOAL": "优化目标",
        "STATUS": "投放状态",
        "REACH": "Reach本周",
        "REACH_QOQ": "Reach环比%",
        "FREQ": "Frequency本周",
        "FREQ_QOQ": "Frequency环比%",
        "CTR": "CTR",
        "CTR_QOQ": "CTR环比%",
        "CPM": "CPM",
        "CPM_QOQ": "CPM环比%",
        "NEW_RATIO": "新客占比%",
        "COVERAGE": "覆盖率%",
        "SIGNALS": "命中信号",
        "LEVEL": "分级",
        "CONCLUSION": "诊断结论",
        "ACTION": "处置动作",
        "NEXT_WATCH": "下周观察指标",
    }
    fields = {NAME_MAP.get(k, k): v for k, v in fields.items()}

    # 日期字段自动转毫秒时间戳
    for date_field in ("监测日期", "写入时间"):
        if date_field in fields:
            fields[date_field] = to_ms_timestamp(fields[date_field])

    r = httpx.post(
        f"{BASE}/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records",
        headers={"Authorization": f"Bearer {get_token()}"},
        json={"fields": fields},
        timeout=15,
    )
    result = r.json()
    print(f"[DEBUG] body={body}", flush=True)
    print(f"[DEBUG] feishu_resp={result}", flush=True)
    return result


@app.api_route("/meta/fetch", methods=["GET", "POST"])
async def meta_fetch(request: Request):
    """拉取 Meta 广告账户近 N 天的 ad set 级数据（兼容 query 和 body 传参）"""
    # 从 query 读
    account = request.query_params.get("account", "")
    days = int(request.query_params.get("days", "7"))
    # 从 body 读（如果有）
    try:
        body = await request.json()
        if isinstance(body, dict):
            account = account or body.get("account", "")
            days = body.get("days", days)
    except Exception:
        pass

    if not account:
        raise HTTPException(400, "account is required")
    if not META_ACCESS_TOKEN:
        raise HTTPException(500, "META_ACCESS_TOKEN not set")

    r = httpx.get(
        f"https://graph.facebook.com/v26.0/{account}/insights",
        params={
            "access_token": META_ACCESS_TOKEN,
            "fields": "campaign_name,adset_name,reach,frequency,ctr,cpm,impressions,clicks,spend",
            "level": "adset",
            "date_preset": f"last_{days}d",
            "limit": 100,
        },
        timeout=30,
    )
    return r.json()


@app.get("/health")
def health():
    return {"status": "ok", "app_token": APP_TOKEN[:8] + "..."}
