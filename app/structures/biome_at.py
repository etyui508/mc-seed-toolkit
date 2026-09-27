#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查某点群系"""
import argparse

import engine
import state
from .base import Structure

def run_cli(args):
    flat = args.at
    pts = list(zip(flat[::2], flat[1::2]))
    dim = engine.DIM_IDS.get(getattr(args, "dim", "overworld"), 0)
    if dim not in (0, -1, 1):
        dim = 0
    cmd = [engine.FINDSTRUCT, "biomedim", str(state.SEED), str(dim)] + [str(v) for p in pts for v in p]
    print(engine.run(cmd).strip())


def run_interactive(st, ctx):
    center = ctx.ask_center()
    dim = (ctx.ask("哪个维度？[overworld/nether/end]（默认 overworld）: ") or "overworld").strip()
    if dim not in engine.DIM_IDS:
        print(f"  没这个维度（{dim}），按主世界算")
        dim = "overworld"
    engine.run_and_log(run_cli, argparse.Namespace(at=[center[0], center[1]], dim=dim),
                       f"群系 {engine.DIM_NAMES.get(dim, dim)} {center}")


STRUCT = Structure(no=27, name="查某点群系", hint="问某个坐标是什么群系",
                   runner=run_interactive, cli=run_cli)
