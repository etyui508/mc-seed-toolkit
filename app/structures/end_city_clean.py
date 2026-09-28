#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""末地城（挑没被搜过的）：按离折跃门落点的距离排"""
import argparse
import math

import engine
from .base import Structure

def run_cli(args):
    hits, _extra = engine.run_find(0, 0, 45000, 4000, args.min_dist, nobiome=True)
    cities = []
    for name, items in hits.items():
        if "末地城" in name:
            cities = items
    if not cities:
        print("没算到末地城")
        return
    gateways = engine.load_gateways()
    scored = []
    for x, z, d in cities:
        d0 = math.hypot(x, z)
        dg = engine.gateway_dist(x, z, gateways)
        if args.clean and dg < args.clean_dist:
            continue
        scored.append((x, z, int(d0), int(dg)))
    scored.sort(key=lambda t: (-t[3] if args.clean else t[2]))
    print(f"\n[末地] 末地城 {len(scored)} 个（{'按离折跃门落点最远排序' if args.clean else '按距离排序'}）")
    for i, (x, z, d0, dg) in enumerate(scored[:args.top], 1):
        print(f"  {i}. goto {x} {z}   距中心 {d0} 格   离最近折跃门落点 {dg} 格")
    print("  提示：离落点 1000 格以上、偏 45° 方向的城最可能没被搜过")


def run_interactive(st, ctx):
    clean = (ctx.ask("只要离折跃门落点远的（更可能没被搜过）? [Y/n]: ") or "y").lower() != "n"
    top = ctx.number("要几个（默认 12）: ", 12)
    engine.run_and_log(run_cli,
                       argparse.Namespace(clean=clean, clean_dist=1000, min_dist=4000, top=top),
                       f"末地城 clean={clean} top={top}")


STRUCT = Structure(no=25, name="末地城（挑没被搜过的）", hint="按离折跃门落点远近排",
                   runner=run_interactive, cli=run_cli)
