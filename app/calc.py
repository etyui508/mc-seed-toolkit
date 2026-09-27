#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""结构计算器（薄壳）。

真正干活的是 structures/ 里的模块 —— 一个结构一个文件，
菜单和命令行都只是"查表 + 把活派给对应的模块"。

直接跑（交互菜单）:  python3 app/calc.py
一条命令出结果:      python3 app/calc.py struct --name 海底神殿 --center 0 0 --radius 2000
                     python3 app/calc.py ships --center 0 0 --radius 20000
"""
import argparse
import contextlib
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))          # app/ 目录
ROOT = os.path.dirname(HERE)                               # 工具包根目录
sys.path.insert(0, HERE)

import config as cfgmod
import engine
import state
import ui
from structures import ALL, by_no
from structures import biome_at, biome_find, end_city_clean, end_ship, end_ship_scan
from structures import overview, probe, scan_block, slime, stronghold
from structures.base import Context          # 菜单和结构模块共用同一套交互接口

# 老编号（以前是 90~97）也认，悄悄换成新编号。
# 注意：老的 17（末地船·扫存档）不在这里 —— 新编号里 17 是紫水晶洞，不能抢。
LEGACY_MENU = {"90": "5", "91": "25", "92": "27", "93": "28",
               "94": "29", "95": "30", "96": "26", "97": "23"}

LOG_FILE = engine.LOG_FILE


def _load_state():
    cfg = cfgmod.load()
    ver = os.environ.get("MCVER") or (cfg.get("mc") and str(cfg["mc"]))
    state.setup(seed=cfg.get("seed"), show_seed=cfg.get("show_seed"), ver=ver)


_load_state()


# ---------------------------------------------------------------- 交互菜单
def menu():
    def ask(prompt, default=None, allow_empty=False):
        try:
            raw = input(ui.prompt_char() + prompt).strip()
        except EOFError:
            return ""
        if not raw:
            if default is not None:
                return default
            if allow_empty:
                return ""
            return ""
        return raw

    def ask_center(default=(0, 0)):
        while True:
            raw = ask(f"中心坐标（默认 {default[0]} {default[1]}，直接回车用默认）: ")
            if not raw:
                return default
            parts = [p for p in raw.replace(",", " ").replace("~", " ").split()
                     if re.fullmatch(r"-?\d+(\.\d+)?", p)]
            if len(parts) >= 2:
                return int(float(parts[0])), int(float(parts[1]))
            print("  要两个数字，比如 1234 -567（或直接回车用默认）")

    def ask_dist():
        raw = ask("最短距离（回车=不限，想找没被搜过的就填，比如 5000；"
                  "想限定区间就写 5000-20000）: ")
        if not raw:
            return 0, 0
        m = re.fullmatch(r"(\d+)\s*[-~～,到]\s*(\d+)", raw)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            return (a, b) if a <= b else (b, a)
        if raw.isdigit():
            return int(raw), 0
        print("  没看懂这个距离（要写数字），按“不限”处理")
        return 0, 0

    ctx = Context(ask, ask_center, ask_dist)
    # ---- 顶部：种子 + 版本 ----
    note = ""
    if state.USER_VER and state.VER_FEAT.get("cubiomes") == "none":
        note = "cubiomes 不认识这个世界生成，按 1.21 近似列候选"
    elif (state.USER_VER and state.VER_FEAT.get("cubiomes") == "approx"
          and str(state.USER_VER) not in ("1.21", "1.21.1")):
        note = "世界生成按 1.21 近似"
    print()
    print(ui.kv([("种子", ui.s(state.masked(), "val")),
                 ("版本", ui.s(state.USER_VER or "（没选）", "val"))], key_width=4, gap=1))
    if note:
        print(ui.warn(note))
    # 版本本身的提醒（比如 1.17 及以前有几种结构参数不同）也要让用户看到
    extra = (state.VER_FEAT or {}).get("note") or ""
    if extra and extra not in note:
        print(ui.warn(extra))

    # ---- 原版结构：3 列网格 ----
    structs, specials = grouped()
    grid, row = [], []
    for st in structs:
        cell = ui.s(f"{st.no:>2}", "key") + " " + st.name
        row.append(ui.pad(cell, 20))
        if len(row) == 3:
            grid.append("".join(row).rstrip())
            row = []
    if row:
        grid.append("".join(row).rstrip())
    print()
    print(ui.box(grid, title=f"原版结构 {structs[0].no}~{structs[-1].no}  （直接输编号查询）"))

    # ---- 特殊功能 ----
    print(ui.menu(f"特殊功能 {specials[0].no}~{specials[-1].no}",
                  [(str(st.no), st.name, st.hint) for st in specials],
                  footer="0 = 返回主菜单   （结果都会存到 记录/坐标记录.txt）"))
    print()
    choice = input(ui.prompt_char() + "选一个: ").strip()
    if choice == "0" or not choice:
        return False

    # 老编号悄悄换算成新编号
    if choice in LEGACY_MENU:
        print(ui.info(f"老编号 {choice} → 现在排在第 {LEGACY_MENU[choice]} 项"))
        choice = LEGACY_MENU[choice]
    if not choice.isdigit():
        print(ui.err("没这个选项"))
        return True
    st = by_no(int(choice))
    if st is None:
        print(ui.err("没这个选项"))
        return True
    st.run(ctx)
    return True


def grouped():
    """(原版结构, 特殊功能)"""
    return [s for s in ALL if s.no <= 22], [s for s in ALL if s.no > 22]


# ---------------------------------------------------------------- 命令行
def build_parser():
    p = argparse.ArgumentParser(description="MC 种子工具包 · 结构计算器")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("struct", help="查某类结构（海底神殿 / 末地城 / 村庄…）")
    s.add_argument("--name", default=None)
    s.add_argument("--center", nargs=2, type=int, default=[0, 0])
    s.add_argument("--from", dest="from_dim", choices=["nether", "overworld"], default="nether")
    s.add_argument("--radius", type=int, default=3000)
    s.add_argument("--top", type=int, default=8)
    s.add_argument("--min-dist", type=int, default=0)
    s.add_argument("--max-dist", type=int, default=0)
    s.set_defaults(func=probe.run_cli)

    s = sub.add_parser("stronghold", help="要塞 / 末地门")
    s.add_argument("--center", nargs=2, type=int, required=True)
    s.add_argument("--top", type=int, default=8)
    s.add_argument("--min-dist", type=int, default=0)
    s.add_argument("--max-dist", type=int, default=0)
    s.set_defaults(func=stronghold.run_cli)

    s = sub.add_parser("endcity", help="末地城（挑没被搜过的）")
    s.add_argument("--clean", action="store_true")
    s.add_argument("--clean-dist", type=int, default=1000)
    s.add_argument("--min-dist", type=int, default=4000)
    s.add_argument("--top", type=int, default=12)
    s.set_defaults(func=end_city_clean.run_cli)

    s = sub.add_parser("biome", help="查某点群系")
    s.add_argument("--at", nargs="+", type=int, required=True)
    s.add_argument("--dim", choices=list(engine.DIM_IDS), default="overworld")
    s.set_defaults(func=biome_at.run_cli)

    s = sub.add_parser("find-biome", help="找最近的某群系")
    s.add_argument("--name", required=True)
    s.add_argument("--dim", choices=list(engine.DIM_IDS), default="overworld")
    s.add_argument("--center", nargs=2, type=int, required=True)
    s.add_argument("--radius", type=int, default=1500)
    s.add_argument("--step", type=int, default=64)
    s.set_defaults(func=biome_find.run_cli)

    s = sub.add_parser("slime", help="史莱姆区块")
    s.add_argument("--center", nargs=2, type=int, required=True)
    s.add_argument("--radius", type=int, default=512)
    s.add_argument("--top", type=int, default=12)
    s.set_defaults(func=slime.run_cli)

    s = sub.add_parser("overview", help="一次列出周围所有结构")
    s.add_argument("--center", nargs=2, type=int, required=True)
    s.add_argument("--radius", type=int, default=3000)
    s.add_argument("--top", type=int, default=15)
    s.add_argument("--min-dist", type=int, default=0)
    s.add_argument("--max-dist", type=int, default=0)
    s.add_argument("--all", action="store_true")
    s.set_defaults(func=overview.run_cli)

    s = sub.add_parser("scan", help="扫存档找方块")
    s.add_argument("--save", required=True)
    s.add_argument("--block", nargs="+", default=["minecraft:dragon_wall_head"])
    s.set_defaults(func=scan_block.run_cli)

    s = sub.add_parser("shipscan", help="扫存档找末地船（靠龙头，不用种子）")
    s.add_argument("--save", required=True)
    s.set_defaults(func=end_ship_scan.run_cli)

    s = sub.add_parser("ships", help="末地船（用种子直接算）")
    s.add_argument("--center", nargs=2, type=int, default=[0, 0])
    s.add_argument("--radius", type=int, default=20000)
    s.add_argument("--top", type=int, default=20)
    s.add_argument("--min-dist", type=int, default=0)
    s.add_argument("--max-dist", type=int, default=0)
    s.set_defaults(func=end_ship.run_cli)
    return p


def main():
    for i, a in enumerate(sys.argv):
        if a == "--seed" and i + 1 < len(sys.argv):
            state.SEED = int(sys.argv[i + 1])
            del sys.argv[i:i + 2]
            break
    if state.SEED is None:
        # scan / shipscan 是扫存档的，压根用不到种子
        needs_seed = len(sys.argv) > 1 and sys.argv[1] not in ("scan", "shipscan")
        if needs_seed:
            print("还没有种子：先跑 app/tool.py 选 1 算种子，或者用 --seed <种子> 临时指定。")
            print("（'scan' / 'shipscan' 这两个是扫存档的，不用种子，可以直接跑）")
            return

    if len(sys.argv) == 1:
        print(ui.info(f"每次的结果都会追加保存到 记录/{os.path.basename(LOG_FILE)}"))
        try:
            while menu():
                print()
        except (EOFError, KeyboardInterrupt):
            print()
        print()
        print(ui.ok("记录文件：" + LOG_FILE))
        print("  " + ui.info("纯文本，用记事本直接打开就能看，历史记录都在里面"))
        if sys.stdin.isatty():
            input("\n按回车关闭…")
        return

    args = build_parser().parse_args()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        args.func(args)
    text = buf.getvalue()
    sys.stdout.write(engine.pretty(text))
    # 命令行模式也记一笔，不然"结果都会存到 坐标记录.txt"对不上，
    # 而且主菜单 7【导出结果】就看不到命令行的查询
    engine.log_result(_label(args), text)


def _label(args):
    """给这次查询起个名字，写进记录里"""
    name = getattr(args, "name", None) or getattr(args, "cmd", "")
    if getattr(args, "center", None):
        name += f" 中心{tuple(args.center)}"
    if getattr(args, "save", None):
        tag = os.path.basename(str(args.save).rstrip("/").rstrip("\\"))
        name += f" {tag}"
    return name.strip()


if __name__ == "__main__":
    main()
