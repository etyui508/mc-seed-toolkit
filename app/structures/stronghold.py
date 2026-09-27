#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""要塞（末地门）：列出最近的要塞和方位距离"""
import argparse
import re

import engine
import state
from .base import Structure

def run_cli(args):
    from . import probe
    cx, cz = engine.blocks_to_chunks(args.center[0], args.center[1])
    min_dist = getattr(args, "min_dist", 0)
    max_dist = getattr(args, "max_dist", 0)
    if not engine.HAS_CUBIOMES:
        print("（没找到 cubiomes 引擎 —— 改用纯 Java 版列候选）")
        probe.run_cli(argparse.Namespace(name="要塞", center=list(args.center), radius=600 * 16,
                                      top=getattr(args, "top", 8),
                                      min_dist=min_dist, max_dist=max_dist))
        return
    out = engine.run([engine.FINDSTRUCT, "find", str(state.SEED), str(cx), str(cz), "600", "12",
               str(min_dist), str(max_dist)])
    block = out.split("要塞")[-1]
    rows = []
    for line in block.splitlines():
        m = re.match(r"\s+#\d+ 方块 \((-?\d+),(-?\d+)\)\s+距你 ([\d.]+) 格\s+(\S*)", line)
        if m:
            rows.append((int(m.group(1)), int(m.group(2)), int(float(m.group(3))), m.group(4)))
    if not rows:
        print("没算出来 —— 距离窗口可能卡太死了，把最短距离调小或者半径调大试试")
        return
    print(f"\n[B] 要塞（末地门在里面）—— 最近的 {min(len(rows), args.top)} 个")
    win = engine.window_text(min_dist, max_dist)
    if win:
        print(f"    距离窗口：{win}")
    for i, (x, z, d, direc) in enumerate(rows[:args.top], 1):
        print(f"  {i}. goto {x} {z}   距你 {d} 格   {direc}")
    print("  到了以后扔末影之眼找传送门房间")


def run_interactive(st, ctx):
    center = ctx.ask_center((0, 0))
    min_dist, max_dist = ctx.ask_dist()
    engine.run_and_log(run_cli,
                       argparse.Namespace(center=center, top=st.top,
                                          min_dist=min_dist, max_dist=max_dist),
                       f"要塞 中心{center} 距离{min_dist}~{max_dist}")


STRUCT = Structure(no=5, name="要塞（末地门）", hint="给出方位和距离",
                   runner=run_interactive, cli=run_cli)
