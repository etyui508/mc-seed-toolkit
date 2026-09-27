#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""末地船：只用种子算，不用下载存档"""
import argparse

import engine
import state
from .base import Structure

def run_cli(args):
    """末地船：不用下载存档，直接用种子把每座末地城跑一遍游戏本体的生成器"""
    try:
        import shipgen
    except Exception as e:
        print(f"读不了 shipgen.py：{e}")
        return
    ok, why = shipgen.available()
    if not ok:
        print("这个功能现在用不了：" + why)
        print("（正常情况下包里的 out/findstruct 就能算，不用装游戏；")
        print("  它是我们照游戏字节码复刻的生成器，没有的话才退回用游戏本体）")
        return

    win = engine.window_text(args.min_dist, args.max_dist)
    print(f"先在半径 {args.radius} 格内列出末地城…")
    hits, _raw = engine.run_find(args.center[0], args.center[1], args.radius, 4000,
                          args.min_dist, args.max_dist, nobiome=True)
    cities = {}
    for name, items in hits.items():
        if "末地城" not in name:
            continue
        for x, z, d in items:
            cities[(x >> 4, z >> 4)] = d
    if not cities:
        print("这个范围里没查到末地城（末地城只在离末地中心 1000 格以外生成）")
        if win:
            print("（也可能是距离窗口卡掉了）")
        return
    order = sorted(cities.items(), key=lambda kv: kv[1])
    print(f"范围内共 {len(order)} 座末地城，正在一座座算有没有船（只列有船的）…")
    ships, err = shipgen.predict(state.SEED, [k for k, _ in order], mcver=state.USER_VER)
    if err:
        print("算不了：" + err)
        return
    if not ships:
        print("这个范围里的末地城都没有船（或者半径太小了）")
        return
    ships.sort(key=lambda s: cities.get((s["cx"], s["cz"]), 1 << 30))
    ships = ships[:args.top]
    base = shipgen.base_heights(state.SEED, [(s["cx"], s["cz"]) for s in ships])

    print(f"\n[末地] 末地船：{len(ships)} 条（种子直接算的，不用下载存档；按离末地中心远近排）")
    for i, s in enumerate(ships, 1):
        by = base.get((s["cx"], s["cz"]), 64)
        g = s["goto"]
        d = cities.get((s["cx"], s["cz"]), -1)
        rot = shipgen.ROT_CN.get(s["rot"], s["rot"])
        print(f"  {i:2d}. goto {g[0]} {g[2]}   距末地中心 {d} 格   "
              f"城块 ({s['cx']},{s['cz']}) 朝向 {rot}")
        head = shipgen.shift_y(s["head"], by)
        ely = shipgen.shift_y(s["elytra"], by)
        c1 = shipgen.shift_y(s["chest1"], by)
        c2 = shipgen.shift_y(s["chest2"], by)
        print(f"      龙头 ({head[0]},{head[1]},{head[2]})"
              f"   鞘翅 ({ely[0]},{ely[1]},{ely[2]})"
              f"   宝箱 ({c1[0]},{c1[1]},{c1[2]}) ({c2[0]},{c2[1]},{c2[2]})")
    print("\n提示：船头那个龙头就是标志物；两个宝箱里是船的宝藏（鞘翅挂在那面墙上的展示框里）。")
    print("      y 是算出来的，误差不超过一两格（地形高低不影响 x/z）。")


def run_interactive(st, ctx):
    center = ctx.ask_center((0, 0))
    radius = ctx.number("搜索半径（默认 20000 格）: ", 20000)
    min_dist, max_dist = ctx.ask_dist()
    top = ctx.number("最多列几条船（默认 20）: ", 20)
    engine.run_and_log(run_cli,
                       argparse.Namespace(center=center, radius=radius, top=top,
                                          min_dist=min_dist, max_dist=max_dist),
                       f"末地船 中心{center} 半径{radius} 距离{min_dist}~{max_dist}")


STRUCT = Structure(no=23, name="末地船", hint="只用种子算，不用下载存档",
                   runner=run_interactive, cli=run_cli)
