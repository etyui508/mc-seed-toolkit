#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通用探测：按种子查某一种结构（走 out/findstruct）。22 个原版结构都用它。"""
import argparse

import engine
def _all():
    """延迟取注册表（__init__ 建好 ALL 之后才用得到）"""
    from . import ALL
    return ALL


def _key_to_disp():
    return {s.key: s.name for s in _all()}


def run_cli(args):
    # 要塞有自己的输出格式（距你 N 格 + 方位），交给要塞那个模块
    if args.name and "要塞" in args.name and "下界" not in args.name:
        from . import stronghold
        return stronghold.run_cli(argparse.Namespace(
            center=list(args.center), top=getattr(args, "top", 8),
            min_dist=getattr(args, "min_dist", 0), max_dist=getattr(args, "max_dist", 0)))
    # 下界结构：可以让用户直接给主世界（传送门那边）的坐标，这里换算成下界坐标
    cx, cz = args.center
    min_dist, max_dist = args.min_dist, args.max_dist
    radius = args.radius
    if getattr(args, "from_dim", "nether") == "overworld":
        if engine.is_nether_name(args.name):
            cx, cz = engine.overworld_to_nether(cx, cz)
            radius = max(1, radius // 8)
            min_dist = min_dist // 8 if min_dist else 0
            max_dist = max_dist // 8 if max_dist else 0
            print(f"\n（你给的是主世界坐标：({args.center[0]},{args.center[1]}) → 下界 ({cx},{cz})；"
                  f"半径/距离也一起 ÷8 了）")
        else:
            print("\n（--from overworld 只对下界结构有意义：下界要塞 / 堡垒遗迹 / 废弃传送门(下界)）")
    radius = engine.fit_radius(radius, min_dist, max_dist)
    hits, raw = engine.run_find(cx, cz, radius, args.top, min_dist, max_dist)
    # 引擎输出里每条后面带着"群系 xxx"，这里按坐标配上一起显示
    # （退回纯 Java 版时没有这一列，查不到就空着）
    biomes = {(r[2], r[3]): r[5] for r in engine.parse_full(raw)}

    def with_biome(t):
        return biomes.get((t[0], t[1]), "")

    wanted = args.name
    win = engine.window_text(min_dist, max_dist)
    if win:
        print(f"\n（距离窗口：{win}）")
    printed = False
    printed_nether = False
    for disp, _key in [(s.name, s.key) for s in _all()]:
        if wanted and wanted not in disp:
            continue
        for name, items in hits.items():
            if (wanted is None or wanted in name or disp in name
                    or _key_to_disp().get(name) == disp or name == _key):
                engine.print_hits(f"[主世界/下界/末地] {_key_to_disp().get(name, name)}",
                           sorted(items, key=lambda t: t[2]), extra=with_biome, limit=args.top)
                printed = True
                if engine.is_nether_name(name) or engine.is_nether_name(disp):
                    printed_nether = True
    if not printed:
        known = any(args.name in d for d, _ in [(s.name, s.key) for s in _all()]) if args.name else False
        if args.name and known:
            print(f"这个范围里没找到「{args.name}」—— 把搜索半径调大、或者换个中心坐标再试")
            if win:
                print("（也可能就是距离窗口卡掉了 —— 把最短距离调小或直接把距离留空）")
        else:
            print("没找到匹配的结构名。可选：" + "、".join(d for d, _ in [(s.name, s.key) for s in _all()]))
            if win:
                print("（也可能就是距离窗口卡掉了 —— 把半径调大或把最短距离调小再试）")
    if printed_nether:
        print("\n（上面下界那几条是**下界坐标**：×8 就是主世界对应的位置，"
              "比如 goto 536 -392 → 主世界 (4288,-3136)，从那边开传送门能到附近）")


def run_interactive(st, ctx):
    """菜单里选中某个原版结构时走的流程"""
    center = ctx.ask_center((0, 0))
    radius = ctx.number("搜索半径（默认 %d 格）: " % st.radius, st.radius)
    min_dist, max_dist = ctx.ask_dist()
    top = ctx.number("要几个（默认 %d）: " % st.top, st.top)
    if st.nether:
        side = (ctx.ask("你给的中心坐标是哪边的？ 1) 主世界（我按 ÷8 换算到下界）"
                        " 2) 下界（原样用）[默认 1]: ") or "1").strip()
        if side != "2":
            nx, nz = engine.overworld_to_nether(center[0], center[1])
            radius = max(1, radius // 8)
            min_dist = min_dist // 8 if min_dist else 0
            max_dist = max_dist // 8 if max_dist else 0
            print(f"  → 按主世界坐标换算：下界中心 ({nx},{nz})，搜索半径 {radius} 格")
            center = (nx, nz)
        else:
            print("  → 按你给的下界坐标原样算")
    engine.run_and_log(
        run_cli,
        argparse.Namespace(name=st.name, center=list(center), radius=radius, top=top,
                           min_dist=min_dist, max_dist=max_dist, from_dim="nether"),
        f"{st.name} 中心{center} 半径{radius} 距离{min_dist}~{max_dist}")
