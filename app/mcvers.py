#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
版本支持表：哪些版本能用什么手段算种子

三个信号来源，各自对版本的要求不一样：

  ① 末地柱子（10 根黑曜石柱）→ 16 bit
     从 1.9（末地重做）开始就是这个公式，一路到 26.3 都没变：
         key = java.util.Random(世界种子).nextLong() & 0xFFFF
         sizes = 0..9 按 Random(key) 洗牌；第 i 根柱子（半径 42，角度 -π + π/10·i）
         高度 = 76 + sizes[i]*3，半径 = 2 + sizes[i]/3
     验证过：1.16.5（SpikeFeature）、1.21.10、26.3（EndSpikeFeature）三个版本代码逐行一致。

  ② 结构摆放（每个结构 3~8 bit）
     1.13 起是数据驱动的 random_spread：
         regionX = floorDiv(chunkX, spacing)
         Random(regionX*341873128712 + regionZ*132897987541 + seed + salt)
         偏移 = spread_type 决定（linear / triangular）
     1.13~26.3 这套参数（salt/spacing/separation）基本没变，我们逐版本核对过：
     26.3 和 1.21.10 的 20 个结构集**完全一致**，26.3 只多了一个 abandoned_camp。
     1.12 及以前是另一套老算法（不是 random_spread），本工具暂时只做"柱子"那部分。

  ③ 哈希种子 sha256(种子) → 定死高 16 位并 100% 校验
     客户端收到的"hashed seed"（1.16 起登录包里有），要用记录模组抓。
     26.3 里还是 BiomeManager.obfuscateSeed（sha256），机制没变。

另外：结构计算器里的"群系检查"用 cubiomes，cubiomes 只支持到 1.21（冬季更新）。
1.21.4+ 我们按 1.21 近似（结果实测仍然对得上）；26.x 没有 worldgen 支持 → 只能给列候选，
不能做群系检查。破解种子本身不依赖 cubiomes（摆放算法是自己实现的），所以 26.3 也能破解。
"""
import re

# 界面文字走语言表；查不到就原样显示中文（这个模块的 note / 汇总行都会打到屏幕上）
import i18n
_ = i18n.t

# 菜单里列出来的代表性版本（想用别的版本直接手输版本号即可）
MILESTONES = [
    "26.4-snapshot-1", "26.3", "26.2", "26.1.2", "26.1",
    "1.21.10", "1.21.9", "1.21.4", "1.21.3", "1.21.1", "1.21",
    "1.20.6", "1.20.4", "1.20", "1.19.4", "1.19",
    "1.18.2", "1.18", "1.17.1", "1.17", "1.16.5", "1.16",
    "1.15.2", "1.14.4", "1.13.2", "1.12.2", "1.11.2", "1.10.2", "1.9.4",
]

# 每个版本的末地城/末地船模板尺寸会不会变？船预测器靠游戏本体跑，所以只要版本有 Fabric 就行
SHIP_SUPPORTED = ("1.21.10",)      # 目前只在这一版上编译过


def parse(ver):
    """版本号 -> (主, 次) 或者 (年份, 月份)；不认识返回 None"""
    if not ver:
        return None
    s = str(ver).strip()
    m = re.match(r"^(\d+)\.(\d+)", s)
    if not m:
        return None
    a, b = int(m.group(1)), int(m.group(2))
    if a >= 26:                    # 26.1 / 26.3 这种年份版本号
        return (a, b)
    return (a, b)


def _ge(ver, a, b):
    p = parse(ver)
    return bool(p) and p >= (a, b)


def _new_naming(ver):
    p = parse(ver)
    return bool(p) and p[0] >= 26


def features(ver):
    """这个版本能用到哪些环节（给界面提示用）"""
    p = parse(ver)
    f = {"pillars": False, "struct": False, "hash": False,
         "cubiomes": "none", "ship": False, "note": ""}
    if not p:
        f["note"] = _("版本号没看懂")
        return f
    new = _new_naming(ver)
    # ① 末地柱子：1.9 起（26.x 当然也有）
    f["pillars"] = new or _ge(ver, 1, 9)
    # ② 结构 random_spread：1.13 起
    f["struct"] = new or _ge(ver, 1, 13)
    # ③ 登录包里的哈希种子：1.16 起
    f["hash"] = new or _ge(ver, 1, 16)
    # cubiomes 的 worldgen 支持范围（能不能做群系检查 / 找结构）
    if new:
        f["cubiomes"] = "none"
        f["note"] = _("cubiomes 还不支持 26.x 的世界生成 → 结构计算只能按 1.21 近似列候选；"
                                "但破解种子不受影响（摆放算法是自己实现的）")
        f["cubiomes_ver"] = "1.21"
    elif _ge(ver, 1, 21):
        f["cubiomes"] = "approx"          # 1.21.2+ 按 1.21 算
        f["cubiomes_ver"] = "1.21"
        if not _ge(ver, 1, 21) or p > (1, 21):
            f["note"] = _("cubiomes 最新只到 1.21，这里按 1.21 近似（实测位置仍然对得上）")
    elif _ge(ver, 1, 7):
        f["cubiomes"] = "exact"
        f["cubiomes_ver"] = ver
    else:
        f["cubiomes"] = "none"
    f["ship"] = any(ver.startswith(v) for v in SHIP_SUPPORTED)
    # ④ 结构参数分版本：这几处的"盐/间距"在 1.18 改过，
    #    本工具的参数表是按 1.18+ 那套写的，老版本会算偏。
    if not new and p and p < (1, 18):
        old_note = _("1.17 及以前：村庄、下界废弃传送门、沙漠水井、紫水晶洞、"
                             "末地折跃门、末地小岛的摆放参数和现在不一样 —— 这几种结构"
                             "算出来的位置会偏，别的结构不受影响（种子本身也能正常解出）")
        f["note"] = (f["note"] + "；" + old_note) if f.get("note") else old_note
        f["struct_partial"] = [_("村庄"), _("废弃传送门(下界)"), _("沙漠水井"),
                               _("紫水晶洞"), _("末地折跃门"), _("末地小岛")]
    return f


def summary_line(ver):
    """一行说明这个版本的支持情况"""
    f = features(ver)
    if not parse(ver):
        return _("  {ver}：版本号没看懂", ver=ver)
    bits = []
    bits.append(_("柱子✓") if f["pillars"] else _("柱子✗"))
    bits.append(_("结构✓") if f["struct"] else _("结构✗(老算法)"))
    bits.append(_("哈希✓") if f["hash"] else _("哈希✗"))
    cube = _({"exact": "世界生成✓", "approx": "世界生成≈1.21", "none": "世界生成✗"}[f["cubiomes"]])
    bits.append(cube)
    if f["ship"]:
        bits.append(_("末地船✓"))
    return f"  {ver:16s} " + "  ".join(bits)


def cubiomes_version(ver):
    """给 findstruct 用的 MCVER 值（cubiomes 认识的那个）"""
    f = features(ver)
    if f["cubiomes"] == "none":
        return "1.21"
    return f.get("cubiomes_ver") or ver


if __name__ == "__main__":
    print(_("版本支持表（1.9 ~ 26.3）："))
    for v in MILESTONES:
        print(summary_line(v))
