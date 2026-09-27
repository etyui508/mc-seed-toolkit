#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""末地船（扫存档）：靠龙头定位，不用种子"""
import argparse
import os

import engine
import config as cfgmod
from .base import Structure

def run_cli(args):
    """末地船（扫存档版）：在下载的存档里扫龙头，反推出整条船的鞘翅/宝箱坐标。

    不用种子 —— minecraft:dragon_wall_head 只有末地船会天然生成，
    船模板里龙头/鞘翅/宝箱的相对位置是固定的，扫到龙头就能把船的坐标全推出来。
    """
    save = cfgmod.adapt_path((getattr(args, "save", None) or "").strip())
    if not save:
        print("没给存档目录 —— 这个功能要的是下载器写出来的那个文件夹（里面有 region/）")
        return
    if not os.path.isdir(save):
        print(f"目录不存在: {save}")
        return
    if not os.path.isdir(os.path.join(save, "region")) and not save.rstrip("/\\").endswith("region"):
        print(f"⚠ 这个目录里没有 region/ : {save}")
        print("  （要填下载器写出来的存档目录，比如 .minecraft\\versions\\<版本>\\saves\\<服务器名>）")
    print("在存档里扫末地船（靠龙头定位，不用种子）…")
    out = engine.run(engine.JAVA_CMD + ["-cp", engine.OUT, "ShipScan", save])
    text = out.strip()
    print(text)
    if "龙头 0 个" in text or "没扫到龙头" in text:
        print("\n建议：把末地那几片区域也下载一份（末地城一般离末地中心 1000 格以外）。")


def run_interactive(st, ctx):
    import config as cfgmod
    default_save = cfgmod.load().get("save") or ""
    print("这个是在下载的存档里扫龙头找末地船（不用种子）——需要存档目录，里面有 region/ 那个")
    save = (ctx.ask(f"存档目录 [默认 {default_save or '无'}]: ") or default_save).strip()
    tag = os.path.basename(str(save).rstrip("/\\")) or str(save)
    engine.run_and_log(run_cli, argparse.Namespace(save=save), f"末地船(扫存档) {tag}")


STRUCT = Structure(no=24, name="末地船（扫存档）", hint="在下载的存档里扫龙头",
                   runner=run_interactive, cli=run_cli)
