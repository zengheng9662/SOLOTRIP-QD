#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在 GitHub Actions runner 上执行: 从 Wikimedia 下载景点图片到 assets/img/
- 输入: tools/img_urls.json (url=Special:FilePath 原链接, file=输出文件名)
- 输出: assets/img/<file> (宽 1200 缩略图, JPEG)
运行环境可达 Wikimedia, 与本地沙箱网络无关。
"""
import json, os, time, urllib.request, urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
items = json.load(open(os.path.join(ROOT, "tools", "img_urls.json"), encoding="utf-8"))
outdir = os.path.join(ROOT, "assets", "img")
os.makedirs(outdir, exist_ok=True)

UA = {"User-Agent": "SOLOTRIP-QD/1.0 (personal trip tool)"}
ok, fail = 0, []
for it in items:
    url = it["url"] + "?width=1200"
    out = os.path.join(outdir, it["file"])
    if os.path.exists(out) and os.path.getsize(out) > 3000:
        ok += 1
        continue
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=UA)
            data = urllib.request.urlopen(req, timeout=60).read()
            if len(data) > 3000:
                with open(out, "wb") as f:
                    f.write(data)
                ok += 1
                print("OK", it["file"], len(data))
                break
        except Exception as e:
            print("retry", it["file"], e)
        time.sleep(2)
    else:
        fail.append(it["file"])
        print("FAIL", it["file"])
    time.sleep(0.5)

print(f"done: ok={ok} fail={len(fail)}")
if fail:
    raise SystemExit(1)
