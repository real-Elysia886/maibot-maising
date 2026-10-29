# -*- coding: utf-8 -*-
"""AI 唱歌推理后端自动化测试脚本。"""

import sys
import os
import time
import requests

SERVER_URL = os.environ.get("SING_SERVER_URL", "http://127.0.0.1:9881").rstrip("/")
TOKEN = os.environ.get("SING_API_TOKEN", "")
HEADERS = {"X-Sing-Token": TOKEN} if TOKEN else {}


def test_health():
    print(f"[1/3] 检查服务健康状态: {SERVER_URL}/health ...")
    r = requests.get(f"{SERVER_URL}/health", headers=HEADERS, timeout=5)
    r.raise_for_status()
    print(" -> 服务正常:", r.json())


def test_sing(song_query="晴天", duration=10.0):
    print(f"\n[2/3] 测试点歌推理: '{song_query}' (期望时长: {duration}s) ...")
    t0 = time.time()
    params = {
        "text": song_query,
        "duration": duration,
        "format": "json"
    }
    r = requests.get(f"{SERVER_URL}/sing", params=params, headers=HEADERS, timeout=60)
    cost = time.time() - t0
    r.raise_for_status()
    data = r.json()
    print(f" -> 点歌成功！总耗时: {cost:.2f}s")
    print(f"    歌曲: 《{data.get('song_name')}》 - {data.get('artist')}")
    print(f"    副歌: “{data.get('matched_lyric')}”")
    print(f"    基频探测: {data.get('detected_f0')} Hz [{data.get('f0_category')}]")
    print(f"    变调值: {data.get('pitch_shift'):+d} 半音")
    print(f"    下载路径: {data.get('download_url')}")
    return data


def test_download(download_url):
    print(f"\n[3/3] 验证音频下载: {SERVER_URL}{download_url} ...")
    r = requests.get(f"{SERVER_URL}{download_url}", headers=HEADERS, timeout=10)
    r.raise_for_status()
    print(f" -> 下载成功！音频大小: {len(r.content)} 字节")


if __name__ == "__main__":
    query = sys.argv[1] if len(sys.argv) > 1 else "晴天"
    try:
        test_health()
        res = test_sing(query)
        if res.get("download_url"):
            test_download(res["download_url"])
        print("\n[SUCCESS] 全部自动化测试顺利通过！")
    except Exception as e:
        print(f"\n[FAILED] 测试失败: {e}")
        sys.exit(1)
