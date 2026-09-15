#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""下载 GUIDES/DAYS 里所有 Wikimedia 图片到 assets/img/ 并压缩。
输出 url -> 本地路径 的映射 json, 供改写 index.html 使用。"""
import json, os, re, time, urllib.parse
import requests
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(ROOT, "index.html")
IMGDIR = os.path.join(ROOT, "assets", "img")
os.makedirs(IMGDIR, exist_ok=True)
UA = {"User-Agent": "SOLOTRIP-QD/1.0 (personal trip tool; contact: self)"}

src = open(INDEX, encoding="utf-8").read()

# 收集所有图片 URL: gallery src + day cover
urls = []
for m in re.finditer(r'"src":\s*"(https://commons\.wikimedia\.org/wiki/Special:FilePath/[^"]+)"', src):
    u = m.group(1).split("?")[0]  # 去掉 ?width=1400
    if u not in urls:
        urls.append(u)
for m in re.finditer(r'"cover":\s*"(https://commons\.wikimedia\.org/wiki/Special:FilePath/[^"]+)"', src):
    u = m.group(1).split("?")[0]
    if u not in urls:
        urls.append(u)
print("unique urls:", len(urls))

# 文件名: 用 File 名做 slug
def slug(url):
    fn = urllib.parse.unquote(url.rsplit("/", 1)[-1])
    fn = fn.rsplit(".", 1)[0]
    fn = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", fn).strip("-")[:60]
    return fn or "img"

mapping = {}
for i, u in enumerate(urls):
    fn = slug(u)
    local = f"assets/img/{fn}.jpg"
    p = os.path.join(ROOT, local)
    if os.path.exists(p) and os.path.getsize(p) > 2000:
        mapping[u] = local
        continue
    ok = False
    for attempt in range(3):
        try:
            r = requests.get(u + "?width=1400", timeout=40, headers=UA)
            if r.status_code == 200 and len(r.content) > 3000:
                tmp = p + ".tmp"
                open(tmp, "wb").write(r.content)
                im = Image.open(tmp).convert("RGB")
                if im.width > 1200:
                    im = im.resize((1200, int(im.height * 1200 / im.width)), Image.LANCZOS)
                im.save(p, "JPEG", quality=82, optimize=True)
                os.remove(tmp)
                mapping[u] = local
                ok = True
                print(f"[{i+1}/{len(urls)}] OK  {fn}  {im.size}")
                break
        except Exception as e:
            print(f"[{i+1}] retry {fn}: {e}")
        time.sleep(2)
    if not ok:
        print(f"[{i+1}] FAIL {u}")
    time.sleep(0.8)

json.dump(mapping, open(os.path.join(ROOT, "tools", "img_mapping.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("done, mapped:", len(mapping))
