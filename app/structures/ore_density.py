#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""矿石分布：看哪个区块的矿石最密集（数的是下载好的存档，不是预测）

和别的模块不一样：这个不需要种子 —— 它把你下载下来的区块逐个数一遍，
按"每个区块有多少矿石"排名。没下载的区块看不见（想比较远的地方先用下载器飞过去）。

为什么要按区块排：挖矿是按区块刷新的，同一片区域里不同区块的矿量能差好几倍，
挑最密的几个区块集中挖，比到处乱挖省时间。
"""
import argparse
import os

import config as cfgmod
import engine
import i18n
from .base import Structure

_ = i18n.t

# 常见矿石：显示名 -> 方块 id 列表（深层变种一起数，不然会漏一半）
ORES = [
    ("钻石", ["minecraft:diamond_ore", "minecraft:deepslate_diamond_ore"]),
    ("远古残骸", ["minecraft:ancient_debris"]),
    ("铁", ["minecraft:iron_ore", "minecraft:deepslate_iron_ore"]),
    ("金", ["minecraft:gold_ore", "minecraft:deepslate_gold_ore",
            "minecraft:nether_gold_ore"]),
    ("红石", ["minecraft:redstone_ore", "minecraft:deepslate_redstone_ore"]),
    ("青金石", ["minecraft:lapis_ore", "minecraft:deepslate_lapis_ore"]),
    ("煤", ["minecraft:coal_ore", "minecraft:deepslate_coal_ore"]),
    ("铜", ["minecraft:copper_ore", "minecraft:deepslate_copper_ore"]),
    ("绿宝石", ["minecraft:emerald_ore", "minecraft:deepslate_emerald_ore"]),
    ("下界石英", ["minecraft:nether_quartz_ore"]),
]

# 存档里可能有哪几个维度（顺序就是打印顺序）
DIMENSIONS = [
    ("主世界", ("region",)),
    ("下界", ("DIM-1", "region")),
    ("末地", ("DIM1", "region")),
]


def _region_dirs(save):
    """把这份存档里真实存在的维度目录列出来：[(维度名, 目录), ...]"""
    out = []
    for name, parts in DIMENSIONS:
        d = os.path.join(save, *parts)
        if os.path.isdir(d):
            out.append((name, d))
    if not out and os.path.isdir(save):
        out.append(("存档根目录", save))      # 下载器把所有维度倒进一个 region 的情况
    return out


def run_cli(args):
    save = args.save
    blocks = args.block
    top = getattr(args, "top", 20)
    ymin = getattr(args, "ymin", None)
    ymax = getattr(args, "ymax", None)
    for name, d in _region_dirs(save):
        cmd = engine.JAVA_CMD + ["-cp", engine.OUT, "OreScan", d] + blocks + ["--top", str(top)]
        if ymin is not None and ymax is not None:
            cmd += ["--y", str(ymin), str(ymax)]
        print(f"【{_(name)}】{d}")
        print(engine.run(cmd).strip())
        print()
    print(_("区块坐标换成方块坐标：x = cx*16 + 8，z = cz*16 + 8（区块中心）"))


def run_interactive(st, ctx):
    save = (ctx.ask(_("存档目录（带 region/ 的那层，回车用设置里的）: ")) or "").strip()
    if not save:
        save = cfgmod.adapt_path(str(cfgmod.load().get("save") or ""))
    if not save or not os.path.isdir(save):
        print("  " + _("这个目录不存在 —— 先在设置里填好存档目录，或者现在手输一个"))
        return

    print()
    for i, (label, _ids) in enumerate(ORES, 1):
        print(f"   {i:2d}) {_(label)}")
    print(f"   {len(ORES) + 1:2d}) {_('手动输方块 id')}")
    raw = (ctx.ask(f"  {_('数哪种矿石？')}[1]: ") or "1").strip()
    if raw.isdigit() and 1 <= int(raw) <= len(ORES):
        label, blocks = ORES[int(raw) - 1]
    elif raw.isdigit() and int(raw) == len(ORES) + 1:
        label = _("自定义")
        blocks = (ctx.ask("  方块 id（空格分隔，例如 minecraft:diamond_ore）: ") or "").split()
        if not blocks:
            print("  " + _("没给方块 id，先不跑了"))
            return
    else:
        label = raw                      # 直接输方块 id 也认（比如想数刷怪笼）
        blocks = raw.split()

    top = ctx.number(f"  {_('列出前几个区块？')}[20]: ", 20)
    depth = (ctx.ask(f"  {_('只看某个 y 范围吗？（回车 = 全部，例如 -64 -16）')}: ")
             or "").strip()
    ymin = ymax = None
    if depth:
        parts = depth.replace(",", " ").split()
        if len(parts) >= 2:
            try:
                ymin, ymax = int(parts[0]), int(parts[1])
            except ValueError:
                print("  " + _("y 范围看不懂，按全部算"))
                ymin = ymax = None

    engine.run_and_log(run_cli,
                       argparse.Namespace(save=save, block=blocks, top=top,
                                          ymin=ymin, ymax=ymax),
                       f"矿石分布 {label} top{top}"
                       + (f" y{ymin}~{ymax}" if ymin is not None else ""))
    print()
    print("  " + _("挑最密的那几个区块，从区块中心往下挖最省事。"))
    print("  " + _("想让结果更全：拿下载器把要比较的范围飞一遍（y 不用管，方块下载到就能数）。"))


STRUCT = Structure(no=31, name="矿石分布", hint="哪个区块的矿最多（数下载好的存档）",
                   runner=run_interactive, cli=run_cli)
