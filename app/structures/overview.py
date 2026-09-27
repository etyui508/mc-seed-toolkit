#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""附近结构总览：一次把周围所有结构按距离列全"""
import argparse

import engine
from .base import Structure

def run_cli(args):
    """一次列出周围所有结构，按距离混排"""
    cx, cz = args.center
    args.radius = engine.fit_radius(args.radius, args.min_dist, args.max_dist)
    # 主世界：按你给的坐标；下界：按 ÷8 后的坐标（这样距离才有意义）；末地：以末地中心 (0,0) 为基准
    # 距离窗口只用在主世界/下界（下界坐标要 ÷8）；末地的"距中心"是从末地中心算的，跟你在主世界的距离无关，所以不过滤
    ow = engine.parse_full(engine.run_find(cx, cz, args.radius, 5000, args.min_dist, args.max_dist)[1])
    neth = engine.parse_full(engine.run_find(cx // 8, cz // 8, max(args.radius // 8, 600), 5000,
                               args.min_dist // 8, args.max_dist // 8)[1])
    end = engine.parse_full(engine.run_find(0, 0, 8000, 5000, 0)[1])
    rows = ([r for r in ow if r[0] == "主世界"]
            + [r for r in neth if r[0] == "下界"]
            + [r for r in end if r[0] == "末地"])
    if rows:
        # 去掉重名的重复行（同坐标同名称）
        seen = set()
        uniq = []
        for r in rows:
            key = (r[0], r[1], r[2], r[3])
            if key not in seen:
                seen.add(key)
                uniq.append(r)
        rows = uniq

    noise = {}
    for r in rows:
        if r[1] in engine.NOISY:
            noise[r[1]] = noise.get(r[1], 0) + 1
    shown = [r for r in rows if args.all or r[1] in engine.TIER_MAIN or r[1] in engine.TIER_MINOR]
    if not shown:
        print("这个范围里没查到结构（cubiomes 没编的话会少很多，试试加大半径）")
        return

    win = engine.window_text(args.min_dist, args.max_dist)
    print(f"\n附近结构总览：中心 ({args.center[0]},{args.center[1]})，半径 {args.radius} 格"
          f"{'，含噪音结构' if args.all else ''}")
    if win:
        print(f"距离窗口（主世界/下界）：{win}；末地不看这个窗口（末地距离是从末地中心算的）")
    for dim in ("主世界", "下界", "末地"):
        part = sorted([r for r in shown if r[0] == dim], key=lambda r: r[4])
        if not part:
            continue
        note = ""
        if dim == "下界":
            note = f"（下界坐标；你主世界 ({cx},{cz}) 对应下界 ({cx // 8},{cz // 8})）"
        elif dim == "末地":
            note = "（末地坐标，距离按末地中心算的；从末地中心往外数）"
        print(f"\n【{dim}】{len(part)} 个 {note}")
        for i, (_, name, x, z, d, note) in enumerate(part[:args.top], 1):
            tag = "★" if name in engine.TIER_MAIN else "·"
            print(f"  {i:2d}. {tag} {name:<12} goto {x:<8} {z:<8} 距 {d:>5} 格   {note}")
        if len(part) > args.top:
            print(f"      …还有 {len(part) - args.top} 个")
    if noise and not args.all:
        summary = "、".join(f"{k} {v} 个" for k, v in noise.items())
        print(f"\n（{summary} 数量太多，默认省略；加 --all 可以看）")
    print("\n★ = 首选目标，· = 顺路可看")


def run_interactive(st, ctx):
    print("（总览的中心坐标填你**主世界**的位置就行 —— 下界和末地那两段会自动换算）")
    center = ctx.ask_center()
    radius = ctx.number("搜索半径（默认 3000 格）: ", 3000)
    min_dist, max_dist = ctx.ask_dist()
    top = ctx.number("每个维度最多列几个（默认 15）: ", 15)
    show_all = (ctx.ask("连废弃矿井/紫水晶洞这些噪音也显示? [y/N]: ") or "").lower().startswith("y")
    engine.run_and_log(run_cli,
                       argparse.Namespace(center=center, radius=radius, top=top,
                                          min_dist=min_dist, max_dist=max_dist, all=show_all),
                       f"结构总览 中心{center} 半径{radius} 距离{min_dist}~{max_dist}")


STRUCT = Structure(no=26, name="附近结构总览", hint="一次把周围所有结构列全",
                   runner=run_interactive, cli=run_cli)
