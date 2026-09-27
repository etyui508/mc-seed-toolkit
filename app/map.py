#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把查到的坐标画成一张 SVG 地图（浏览器直接打开，不用装任何东西）。

为什么要这个：一排排坐标看不出来"哪个近、在哪个方向、要走几趟"，
画成图一眼就明白。纯手写 SVG，不依赖第三方库。

命令行：
  python3 app/map.py --last 3 --out 记录/导出/地图.svg
"""
import argparse
import datetime
import html
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import export                                          # noqa: E402

W, H = 820, 820                 # 画布
PAD = 64                        # 四周留白（放刻度和方向）

# 不同维度用不同颜色，图例里能对上
COLORS = {"主世界": "#4ea1ff", "下界": "#ff7a59", "末地": "#c678dd", "": "#8b93a3"}


def nice_step(span, max_labels=8):
    """挑一个好读的刻度间隔（500 / 1000 / 2000 …）
    max_labels 按栏宽定 —— 窄栏少放几个刻度，不然数字挤成一团。"""
    for step in (100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000):
        if span / step <= max_labels:
            return step
    return 100000


def build(points, title="MC 种子工具包 · 结构地图"):
    """points: [{'x','z','dim','note'}]  ->  SVG 文本"""
    if not points:
        return None
    # 主世界 / 下界 / 末地是三个不同的坐标空间，混在一张图上比例尺会被拉爆
    # （主世界动辄上万格，末地就一千多），所以按维度分栏画。
    groups = {}
    for p in points:
        groups.setdefault(p.get("dim") or "主世界", []).append(p)
    if len(groups) == 1:
        return _panel(list(groups)[0], list(groups.values())[0], title, W, H, ox=0, oy=0)
    panels = list(groups.items())[:3]
    pw = (W - (len(panels) - 1) * 12) // len(panels)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
             f'viewBox="0 0 {W} {H}" font-family="-apple-system,Segoe UI,Microsoft YaHei,sans-serif">',
             f'<rect width="{W}" height="{H}" fill="#171a21"/>',
             f'<text x="20" y="30" fill="#dee2e6" font-size="19" font-weight="600">'
             f'{html.escape(title)}</text>',
             f'<text x="20" y="50" fill="#8b93a3" font-size="12">'
             f'{len(points)} 个点 · 按维度分栏（三个空间坐标不是一回事） · '
             f'生成于 {datetime.datetime.now():%Y-%m-%d %H:%M}</text>']
    for i, (dim, pts) in enumerate(panels):
        x0 = i * (pw + 12)
        # 坐标直接算成绝对值（不用 <g transform>）—— 这样任何 SVG 渲染器都认，简单省事
        parts.append(_panel(dim, pts, "", pw, H - 210, body_only=True, ox=x0, oy=62,
                            short_labels=True))
    # 多栏时点旁边只写编号，完整说明放底部图例 —— 不然一行说明比一整栏还宽，会溢到隔壁
    parts.append(f'<text x="20" y="{H - 128}" fill="#8b93a3" font-size="13">'
                 f'点在哪里（编号跟图上的数字对应）：</text>')
    y = H - 106
    col_w = (W - 40) // 2
    for i, p in enumerate(points, 1):
        col, row = divmod(i - 1, 8)
        px = 24 + col * col_w
        py = y + row * 17
        if py > H - 8:
            break
        color = COLORS.get(p.get("dim", ""), COLORS[""])
        label = f'{i}. [{p.get("dim","")}] {p["x"]},{p["z"]}'
        # 图例里已经有坐标了，说明里再把"goto x z"去掉，免得重复
        note = re.sub(r"^\s*goto\s+(-?\d+)\s+(-?\d+)\s*", "",
                      str(p.get("note", "")))[:25]
        parts.append(f'<circle cx="{px+4}" cy="{py-4}" r="4" fill="{color}"/>')
        parts.append(f'<text x="{px+13}" y="{py}" fill="#c9d1d9" font-size="11">'
                     f'{html.escape(label)}  {html.escape(note)}</text>')
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def _panel(dim, points, title, w, h, body_only=False, ox=0, oy=0, short_labels=False):
    """画一栏（一个维度）"""
    W, H, PAD = w, h, 52
    xs = [p["x"] for p in points]
    zs = [p["z"] for p in points]
    pad_r = max(120, int(max(max(xs) - min(xs), max(zs) - min(zs)) * 0.08))
    x0, x1 = min(xs) - pad_r, max(xs) + pad_r
    z0, z1 = min(zs) - pad_r, max(zs) + pad_r
    span = max(x1 - x0, z1 - z0)
    step = nice_step(span, max(3, int((w - 2 * PAD) / 62)))

    def sx(x):                                  # 世界 x -> 画布 x
        return ox + PAD + (x - x0) / span * (W - 2 * PAD)

    def sz(z):                                  # 世界 z -> 画布 y（z 越大越往下，和 F3 一致）
        return oy + PAD + (z - z0) / span * (H - 2 * PAD)

    parts = []
    if not body_only:
        parts += [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
            f'viewBox="0 0 {W} {H}" font-family="-apple-system,Segoe UI,Microsoft YaHei,sans-serif">',
            f'<rect width="{W}" height="{H}" fill="#171a21"/>',
            f'<text x="20" y="30" fill="#dee2e6" font-size="19" font-weight="600">'
            f'{html.escape(title)}</text>',
            f'<text x="20" y="50" fill="#8b93a3" font-size="12">{len(points)} 个点 · '
            f'范围约 {span} 格 · 生成于 {datetime.datetime.now():%Y-%m-%d %H:%M}</text>',
        ]
    parts.append(f'<text x="{ox + PAD}" y="{oy + 20}" fill="{COLORS.get(dim, COLORS[""])}" '
                 f'font-size="15" font-weight="600">{html.escape(dim)}（{len(points)} 个）</text>')

    # 网格 + 刻度
    start_x = int(x0 // step) * step
    x = start_x
    while x <= x1:
        px = sx(x)
        parts.append(f'<line x1="{px:.1f}" y1="{oy+PAD}" x2="{px:.1f}" y2="{oy+H-PAD}" stroke="#262b36"/>')
        parts.append(f'<text x="{px:.1f}" y="{oy+H-PAD+18}" fill="#6c7574" font-size="11" '
                     f'text-anchor="middle">{x}</text>')
        x += step
    z = int(z0 // step) * step
    while z <= z1:
        pz = sz(z)
        parts.append(f'<line x1="{ox+PAD}" y1="{pz:.1f}" x2="{ox+W-PAD}" y2="{pz:.1f}" stroke="#262b36"/>')
        parts.append(f'<text x="{ox+PAD-8}" y="{pz+4:.1f}" fill="#6c7574" font-size="11" '
                     f'text-anchor="end">{z}</text>')
        z += step

    # 方向和比例尺
    parts.append(f'<text x="{ox+W/2}" y="{oy+PAD-14}" fill="#6c7574" font-size="11" '
                 f'text-anchor="middle">北 ↑（z 减小）</text>')
    bar = step
    bx, by = ox + PAD, oy + H - 24
    parts.append(f'<line x1="{bx}" y1="{by}" x2="{bx + bar/span*(W-2*PAD):.1f}" y2="{by}" '
                 f'stroke="#8b93a3" stroke-width="2"/>')
    parts.append(f'<text x="{bx + bar/span*(W-2*PAD) + 8:.1f}" y="{by+4}" fill="#8b93a3" '
                 f'font-size="11">{bar} 格</text>')

    # 点（同一坐标的点错开一点，免得完全重叠）
    seen = {}
    for i, p in enumerate(points, 1):
        key = (p["x"], p["z"])
        n = seen.get(key, 0)
        seen[key] = n + 1
        cx, cy = sx(p["x"]) + n * 7, sz(p["z"]) + n * 7
        color = COLORS.get(p.get("dim", ""), COLORS[""])
        parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="6" fill="{color}" '
                     f'fill-opacity="0.85" stroke="#171a21" stroke-width="1.5"/>')
        label = (f"{i}" if short_labels
                 else f'{i}. {html.escape(str(p.get("short") or p.get("note", ""))[:22])}')
        parts.append(f'<text x="{cx+10:.1f}" y="{cy+4:.1f}" fill="#c9d1d9" font-size="11">'
                     f'{label if short_labels else label}</text>')

    if not body_only:
        parts.append("</svg>")
    return "\n".join(parts) + ("" if body_only else "\n")


def collect(rows, per_row=40):
    """把几条查询结果里的点汇总（太多就每类留前 per_row 个）"""
    points = []
    for r in rows:
        for pt in export.parse_gotos(r.get("text", "")):
            note = pt["note"]
            short = note.split("goto")[-1].strip() if "goto" in note else note
            points.append({"x": pt["x"], "z": pt["z"], "dim": pt["dim"],
                           "note": note, "short": short})
    return points[:600]


def main():
    p = argparse.ArgumentParser(description="把查询结果画成 SVG 地图")
    p.add_argument("--last", type=int, default=1)
    p.add_argument("--out", default=None)
    a = p.parse_args()
    rows = export.load(a.last)
    points = collect(rows)
    if not points:
        print("❌ 没找到可画的坐标（先跑一条查询）")
        return 1
    svg = build(points)
    out = a.out or os.path.join(ROOT, "记录", "导出",
                                f"地图-{datetime.datetime.now():%Y%m%d-%H%M%S}.svg")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(svg)
    print(f"✅ 画好了：{os.path.relpath(out, ROOT)}（{len(points)} 个点）")
    print("   用浏览器打开就能看（Chrome/Edge 双击也行）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
