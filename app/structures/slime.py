#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""史莱姆区块（史莱姆农场选址）"""
import argparse

import engine
import state
from .base import Structure

def run_cli(args):
    out = engine.run(engine.JAVA_CMD + ["-cp", engine.OUT, "SlimeFind", str(state.SEED), str(args.center[0]), str(args.center[1]),
               str(args.radius), str(args.top)])
    print(out.strip())
    print("  农场建议：选 3~4 个挨在一起的区块当中心，y 挖到 0 附近做刷怪层")


def run_interactive(st, ctx):
    center = ctx.ask_center()
    radius = ctx.number("搜索半径（默认 512 格）: ", 512)
    top = ctx.number("要几个（默认 12）: ", 12)
    engine.run_and_log(run_cli, argparse.Namespace(center=center, radius=radius, top=top),
                       f"史莱姆区块 中心{center} 半径{radius}")


STRUCT = Structure(no=29, name="史莱姆区块", hint="史莱姆农场选址",
                   runner=run_interactive, cli=run_cli)
