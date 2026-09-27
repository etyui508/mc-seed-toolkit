#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""扫存档里的方块（末地船 / 刷怪笼 / 传送门）"""
import argparse
import os

import config as cfgmod
import engine
from .base import Structure

def run_cli(args):
    cmd = engine.JAVA_CMD + ["-cp", engine.OUT, "BlockFind", cfgmod.adapt_path(args.save)] + args.block
    print(engine.run(cmd).strip())


def run_interactive(st, ctx):
    save = (ctx.ask("存档目录: ") or "").strip()
    blocks = (ctx.ask("方块 id（空格分隔，默认 dragon_wall_head）: ") or "").strip()
    args_blocks = blocks.split() if blocks else ["minecraft:dragon_wall_head"]
    engine.run_and_log(run_cli, argparse.Namespace(save=save, block=args_blocks),
                       f"扫存档 {os.path.basename(save.rstrip('/'))} {args_blocks}")


STRUCT = Structure(no=30, name="扫存档里的方块", hint="末地船 / 刷怪笼 / 传送门",
                   runner=run_interactive, cli=run_cli)
