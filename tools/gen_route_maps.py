#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SOLOTRIP-QD 真实地理路线地图生成器
- 从 index.html 的 DAYS 数据读取每天带坐标的节点
- 下载 CARTO 底图瓦片(© OpenStreetMap contributors © CARTO)拼成真实地图
- 用 OSRM 公共 API 计算路段实际行车路线(失败时退化为直线)
- 按 S/A/B/固定 配色绘制节点与路线, 输出 assets/route-XX.png
"""
import json, math, os, re, time, urllib.parse
import requests
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(ROOT, "index.html")
OUTDIR = os.path.join(ROOT, "assets")
TILECACHE = os.path.join(ROOT, "tools", ".tilecache")
OSRMCACHE = os.path.join(ROOT, "tools", ".osrmcache.json")
os.makedirs(TILECACHE, exist_ok=True)

FONT_B = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
FONT_R = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"

# 与 index.html 保持一致
COLOR = {"s": "#24a875", "a": "#4b83f4", "b": "#e6a12e", "lock": "#f05c58"}
TITLES = {
    "21": "老城 / 里院",
    "22": "老城海滨 → 八大关 → 五四",
    "23": "青啤 → 大鲍岛里院",
    "24": "崂山仰口 → 石老人",
    "25": "石老人 · 返程",
}
SHORT = {
    "青岛胶东机场": "机场",
    "桔子酒店（栈桥火车站店）": "酒店",
    "圣弥厄尔大教堂": "教堂",
    "里院乐赏区 / 看院落结构": "里院乐赏区",
    "里院·十号房": "十号房",
    "里院·拾叁院": "拾叁院",
    "大鲍岛里院记忆博物馆": "里院记忆馆",
    "有余里（有空再去）": "有余里",
    "青岛啤酒博物馆": "青啤博物馆",
    "大学路 / 黄县路": "大学路/黄县路",
    "洗浴 / SPA（待定）": "SPA",
    "八大关电动观光车": "八大关观光车",
    "第二海水浴场": "二浴",
    "网约车 → 仰口": None,
}
PRIO_TEXT = {"s": "S", "a": "A", "b": "B", "lock": "固定"}
AIRPORT = "胶东机场"


def short_name(n):
    if n in SHORT:
        return SHORT[n]
    return n


def extract_days():
    src = open(INDEX, encoding="utf-8").read()
    m = re.search(r"const DAYS=(\[.*?\]);", src, re.S)
    return json.loads(m.group(1))


def zoom_for(span_deg, target_px=1050):
    # px = span * 256 * 2^z / 360
    z = math.ceil(math.log2(target_px * 360.0 / (span_deg * 256)))
    return max(12, min(17, z))


def deg2num(lat, lng, z):
    lat_r = math.radians(lat)
    n = 2.0 ** z
    x = (lng + 180.0) / 360.0 * n
    y = (1.0 - math.asinh(math.tan(lat_r)) / math.pi) / 2.0 * n
    return x, y


def tile_url(z, x, y):
    return f"https://tile.openstreetmap.de/{z}/{int(x)}/{int(y)}.png"


def get_tile(z, x, y):
    key = f"{z}_{x}_{y}.png"
    p = os.path.join(TILECACHE, key)
    if os.path.exists(p) and os.path.getsize(p) > 500:
        return p
    url = tile_url(z, x, y)
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=20, headers={"User-Agent": "SOLOTRIP-QD/1.0 (personal trip tool)"})
            if r.status_code == 200 and len(r.content) > 500:
                open(p, "wb").write(r.content)
                return p
        except Exception:
            pass
        time.sleep(1.2)
    return None


def osrm_route(p1, p2):
    """p1,p2 = (lat,lng). 返回 [(lng,lat),...] 或 None"""
    cache = {}
    if os.path.exists(OSRMCACHE):
        cache = json.load(open(OSRMCACHE, encoding="utf-8"))
    key = f"{round(p1[0],5)},{round(p1[1],5)}>{round(p2[0],5)},{round(p2[1],5)}"
    if key in cache:
        return cache[key]
    url = (f"https://router.project-osrm.org/route/v1/driving/{p1[1]},{p1[0]};{p2[1]},{p2[0]}"
           "?overview=full&geometries=geojson")
    res = None
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "SOLOTRIP-QD/1.0"})
        if r.status_code == 200:
            j = r.json()
            if j.get("code") == "Ok" and j.get("routes"):
                res = j["routes"][0]["geometry"]["coordinates"]
    except Exception:
        res = None
    cache[key] = res
    json.dump(cache, open(OSRMCACHE, "w", encoding="utf-8"))
    time.sleep(1.0)
    return res


def draw_map(day):
    did = day["id"]
    # 节点(带坐标, 排除机场), 保持事件顺序
    nodes = []
    seen = set()
    for e in day["events"]:
        t, label, name, p, lat, lng, g = e
        if lat and lng and AIRPORT not in name and (name, lat, lng) not in seen:
            seen.add((name, lat, lng))
            nodes.append({"name": name, "lat": lat, "lng": lng, "p": p, "sub": False})
    extras = []
    for ex in day.get("mapExtra") or []:
        extras.append({"name": ex["name"], "lat": ex["lat"], "lng": ex["lng"],
                       "p": ex.get("p", "b"), "sub": True})
    # 若有与主线重叠的 extra 就不再重复画
    extras = [x for x in extras if not any(abs(x["lat"]-n["lat"]) < 1e-4 and abs(x["lng"]-n["lng"]) < 1e-4 for n in nodes)]

    allpts = nodes + extras
    if not allpts:
        return None
    lats = [p["lat"] for p in allpts]
    lngs = [p["lng"] for p in allpts]
    span_lat = max(lats) - min(lats)
    span_lng = max(lngs) - min(lngs)
    pad = max(span_lat, span_lng) * 0.22 + 0.002
    bbox = (min(lngs) - pad, min(lats) - pad, max(lngs) + pad, max(lats) + pad)  # lng1,lat1,lng2,lat2
    # 最小视野: 保证小范围也有街道上下文, 避免单点图过大
    MIN_SPAN = 0.035
    if bbox[2] - bbox[0] < MIN_SPAN:
        c = (bbox[0] + bbox[2]) / 2
        bbox = (c - MIN_SPAN / 2, bbox[1], c + MIN_SPAN / 2, bbox[3])
    if bbox[3] - bbox[1] < MIN_SPAN:
        c = (bbox[1] + bbox[3]) / 2
        bbox = (bbox[0], c - MIN_SPAN / 2, bbox[2], c + MIN_SPAN / 2)

    z = zoom_for(bbox[2] - bbox[0])
    x1, y1 = deg2num(bbox[3], bbox[0], z)  # 左上
    x2, y2 = deg2num(bbox[1], bbox[2], z)  # 右下
    xi1, yi1, xi2, yi2 = math.floor(x1), math.floor(y1), math.ceil(x2), math.ceil(y2)

    # 拼接瓦片
    tw = (xi2 - xi1 + 1) * 256
    th = (yi2 - yi1 + 1) * 256
    mosaic = Image.new("RGB", (tw, th), "#dfe7eb")
    ok = 0
    for tx in range(xi1, xi2 + 1):
        for ty in range(yi1, yi2 + 1):
            tp = get_tile(z, tx, ty)
            if tp:
                im = Image.open(tp).convert("RGB")
                mosaic.paste(im, ((tx - xi1) * 256, (ty - yi1) * 256))
                ok += 1
    if ok == 0:
        return None

    # 裁剪到 bbox
    def to_px(lat, lng):
        fx, fy = deg2num(lat, lng, z)
        return (fx - xi1) * 256, (fy - yi1) * 256
    cx1, cy1 = to_px(bbox[3], bbox[0])
    cx2, cy2 = to_px(bbox[1], bbox[2])
    cx1, cy1, cx2, cy2 = int(cx1), int(cy1), int(cx2), int(cy2)
    crop = mosaic.crop((cx1, cy1, cx2, cy2))

    # 缩放
    target_w = 1200
    scale = target_w / crop.width
    target_h = int(crop.height * scale)
    img = crop.resize((target_w, target_h), Image.LANCZOS)
    def px(lat, lng):
        if lat is None or lng is None:
            import traceback; traceback.print_stack()
            raise ValueError(f"px got None: lat={lat} lng={lng}")
        fx, fy = deg2num(lat, lng, z)
        return ((fx - xi1) * 256 - cx1) * scale, ((fy - yi1) * 256 - cy1) * scale

    draw = ImageDraw.Draw(img, "RGBA")
    fb = ImageFont.truetype(FONT_B, 22)
    fb_s = ImageFont.truetype(FONT_B, 18)
    fr = ImageFont.truetype(FONT_R, 17)
    fr_s = ImageFont.truetype(FONT_R, 14)

    # ---- 路线(按节点顺序, 每段按起点优先级着色) ----
    def seg_color(p):
        return COLOR.get(p, COLOR["a"])
    for i in range(len(nodes) - 1):
        a, b = nodes[i], nodes[i + 1]
        if abs(a["lat"] - b["lat"]) < 1e-5 and abs(a["lng"] - b["lng"]) < 1e-5:
            continue
        geom = osrm_route((a["lat"], a["lng"]), (b["lat"], b["lng"]))
        if geom and len(geom) > 1:
            pts = [px(pt[1], pt[0]) for pt in geom]
        else:
            pts = [px(a["lat"], a["lng"]), px(b["lat"], b["lng"])]
        c = seg_color(a["p"])
        draw.line(pts, fill=(255, 255, 255, 235), width=11, joint="curve")
        draw.line(pts, fill=c + "e6", width=6, joint="curve")
        # 中间转折点画小箭头指示方向
        for k in range(1, len(pts) - 1):
            p0, p1, p2 = pts[k - 1], pts[k], pts[k + 1]
            v1 = (p1[0] - p0[0], p1[1] - p0[1])
            v2 = (p2[0] - p1[0], p2[1] - p1[1])
            l1 = math.hypot(*v1); l2 = math.hypot(*v2)
            if l1 < 1 or l2 < 1:
                continue
            u1 = (v1[0] / l1, v1[1] / l1); u2 = (v2[0] / l2, v2[1] / l2)
            dot = u1[0] * u2[0] + u1[1] * u2[1]
            if dot < 0.92:  # 有明显转弯
                d = (u2[0] + u1[0], u2[1] + u1[1])
                dl = math.hypot(*d) or 1
                d = (d[0] / dl, d[1] / dl)
                cx, cy = p1
                tip = (cx + d[0] * 15, cy + d[1] * 15)
                b1 = (cx + d[0] * 15 - d[1] * 7, cy + d[1] * 15 + d[0] * 7)
                b2 = (cx + d[0] * 15 + d[1] * 7, cy + d[1] * 15 - d[0] * 7)
                draw.polygon([tip, b1, b2], fill=(255, 255, 255, 255))
                draw.polygon([tip, b1, b2], outline=c + "ff", width=2)

    # ---- 节点 ----
    # 处理同坐标节点: 后到的往右下偏移并画虚线连接
    used_pos = {}
    for idx, nd in enumerate(nodes, 1):
        key = (round(nd["lat"], 5), round(nd["lng"], 5))
        off = used_pos.get(key, (0, 0))
        used_pos[key] = (off[0] + 30, off[1] + 30)
        x, y = px(nd["lat"], nd["lng"])
        x, y = int(x) + off[0], int(y) + off[1]
        c = COLOR.get(nd["p"], COLOR["a"])
        r = 15
        if off != (0, 0):
            ox, oy = px(nd["lat"], nd["lng"])
            draw.line([int(ox), int(oy), x - r, y - r], fill=(80, 100, 110, 180), width=2)
            draw.line([int(ox), int(oy), x - r, y - r], fill=(255, 255, 255, 200), width=4)
        draw.ellipse([x - r, y - r, x + r, y + r], fill=c, outline="white", width=4)
        txt = str(idx)
        tw = draw.textlength(txt, font=fb)
        draw.text((x - tw / 2, y - 14), txt, font=fb, fill="white")
        label = short_name(nd["name"]) or nd["name"]
        lw = draw.textlength(label, font=fb_s)
        lx = x + r + 7
        ly = y - 12
        draw.rectangle([lx - 3, ly - 2, lx + lw + 3, ly + 24], fill=(255, 255, 255, 210))
        draw.text((lx, ly), label, font=fb_s, fill=(23, 36, 46, 255))
    for nd in extras:
        x, y = px(nd["lat"], nd["lng"])
        x, y = int(x), int(y)
        c = COLOR.get(nd["p"], COLOR["b"])
        r = 9
        draw.ellipse([x - r, y - r, x + r, y + r], outline=c, width=3)
        label = short_name(nd["name"]) or nd["name"]
        lw = draw.textlength(label, font=fr_s)
        lx = x + r + 6
        ly = y - 8
        draw.rectangle([lx - 3, ly - 2, lx + lw + 3, ly + 19], fill=(255, 255, 255, 200))
        draw.text((lx, ly), label, font=fr_s, fill=(88, 110, 122, 255))

    # ---- 标题 ----
    title = f"09/{did} · {TITLES.get(did, '')}"
    tw = draw.textlength(title, font=fb) + 24
    draw.rounded_rectangle([14, 14, 14 + tw, 48], radius=10, fill=(255, 255, 255, 235))
    draw.text((26, 20), title, font=fb, fill=(23, 36, 46, 255))

    # ---- 图例(左下) ----
    legend = [("s", "S"), ("a", "A"), ("b", "B"), ("lock", "固定")]
    lx, ly = 16, img.height - 34
    seg = [("s", "S"), ("a", "A"), ("b", "B"), ("lock", "固定")]
    total_w = 0
    parts = []
    for p, t in seg:
        c = COLOR[p]
        w = draw.textlength(t, font=fb_s) + 26
        parts.append((c, t, w))
        total_w += w + 12
    bgw = total_w + 18
    draw.rounded_rectangle([lx, ly, lx + bgw, ly + 30], radius=10, fill=(255, 255, 255, 235))
    xx = lx + 12
    for c, t, w in parts:
        draw.ellipse([xx, ly + 8, xx + 13, ly + 21], fill=c, outline="white", width=2)
        draw.text((xx + 19, ly + 7), t, font=fb_s, fill=(23, 36, 46, 255))
        xx += w + 12

    # ---- 署名(右下) ----
    attr = "© OpenStreetMap contributors"
    aw = draw.textlength(attr, font=fr_s) + 12
    draw.rounded_rectangle([img.width - 14 - aw, img.height - 30, img.width - 14, img.height - 6],
                           radius=8, fill=(255, 255, 255, 200))
    draw.text((img.width - 14 - aw + 6, img.height - 27), attr, font=fr_s, fill=(90, 105, 115, 255))

    out = os.path.join(OUTDIR, f"route-{did}.png")
    img.save(out)
    print(f"route-{did}.png  {img.size}  nodes={len(nodes)} extras={len(extras)}")
    return out


def main():
    days = extract_days()
    for d in days:
        draw_map(d)


if __name__ == "__main__":
    main()
