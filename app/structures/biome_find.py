#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""找最近的某群系（蘑菇岛 / 雪原 / 诡异森林…）"""
import argparse

import engine
import state
from .base import Structure

def run_cli(args):
    dim = engine.DIM_IDS[args.dim]
    out = engine.run([engine.FINDSTRUCT, "biomefind", str(state.SEED), str(dim), str(args.center[0]), str(args.center[1]),
               str(args.radius), args.name, str(args.step)])
    print(out.strip())


def run_interactive(st, ctx):
    name = (ctx.ask("群系名（如 warped_forest / mushroom_fields / snowy_plains）: ") or "").strip()
    dim = (ctx.ask("维度 [overworld/nether/end]（默认 overworld）: ") or "overworld").strip()
    center = ctx.ask_center()
    radius = ctx.number("搜索半径（默认 1500 格）: ", 1500)
    engine.run_and_log(run_cli,
                       argparse.Namespace(name=name, dim=dim, center=center, radius=radius, step=64),
                       f"找群系 {name} 中心{center}")


STRUCT = Structure(no=28, name="找最近的某群系", hint="蘑菇岛 / 雪原 / 诡异森林…",
                   runner=run_interactive, cli=run_cli)
