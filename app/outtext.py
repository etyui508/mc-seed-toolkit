#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""显示层翻译：把**引擎吐出来的中文行**在打印那一刻换成英文。

为什么需要这一层：

  · `out/findstruct` 是 cubiomes 编出来的 C 程序，它的输出里写死了一堆中文
    （`[主世界] 海底神殿：12 个过了群系检查`、`区块 (x,z) 方块 (x,z) 距中心 N 格`…）。
    重新编译它要联网拿 cubiomes 源码，包里没有，所以走显示层翻译。
  · Java 那几支（SeedCracker / RegionScan / PillarScan…）是包里自己编的，
    它们有自己的 `-Dmc.lang=en` 开关，这里只兜底。

原则（重要）：

  · **只改打印出来的那一行**，写进 `记录/日志.txt` 的仍是中文原文 ——
    别的模块（`export.parse_gotos`、`structures/overview.py`）靠中文标记解析，
    谁知道会不会被"翻译"搞坏。
  · 查不到译文的片段原样保留中文，绝不猜。
"""
import re

import i18n

# 维度名（引擎里当分组标签用，只在显示时换）
DIMS = {"主世界": "Overworld", "下界": "Nether", "末地": "End"}

# 方位（findstruct 的 "南东" 这种是拼出来的）
DIRS = {"北": "N", "南": "S", "西": "W", "东": "E"}

# 长句子先换，短词后换 —— 顺序不能乱
PHRASES = (
    ("<种子>", "<seed>"),
    ("下面是过了群系检查的（真的会生成）", "biome-checked only (these really generate)"),
    ("个过了群系检查", "passed the biome check"),
    ("要塞（末地门在要塞里面）", "Stronghold (the End portal is inside)"),
    ("参数不对，看上面的用法", "Bad arguments — see the usage above"),
    ("可能太小，试试加大半径", "maybe too small — try a bigger radius"),
    ("实际位置在附近", "the real spot is within about"),
    ("没找到", "nothing found for"),
    ("距离窗口：", "Distance window: "),
    ("中心区块", "center chunk"),
    ("距中心", "from center"),
    ("距你", "from you"),
    ("每区块一个", "one per chunk"),
    ("一个进程扫整片", "a single process scans the whole area"),
    ("范围内", "in range"),
    ("半径", "radius"),
    ("区块", "chunk"),
    ("方块", "block"),
    ("种子", "Seed"),
    ("群系", "biome"),
    ("步长", "step"),
    ("用法:", "Usage:"),
    ("用法：", "Usage:"),
    ("不认识的版本", "Unknown version"),
    ("用默认", "falling back to"),
    ("真的会生成", "these really generate"),
    ("…还有", "…and"),
    ("近的", "near"),
    ("远的", "far"),
)

# 会出现在引擎输出里的结构名（译文表里有就翻，没有就留着）
NAMES = (
    "要塞（末地门在要塞里面）", "废弃传送门(下界)", "海底神殿", "海底遗迹", "远古城市",
    "试炼密室", "掠夺者前哨", "雪原小屋", "沙漠神殿", "丛林神殿", "女巫小屋",
    "废弃传送门", "沉船", "下界要塞", "堡垒遗迹", "末地城", "末地折跃门", "末地小岛",
    "埋藏的宝藏", "废弃矿井", "沙漠水井", "紫水晶洞", "古迹废墟", "林地府邸",
    "沙漠村庄", "热带草原村庄", "雪原村庄", "针叶林村庄", "平原村庄", "村庄", "桥",
)


def _dirs(text):
    """南东 → SE（findstruct 的方位是两个汉字拼的）"""
    for zh, en in DIRS.items():
        text = text.replace(zh, en)
    return text


_NUM = r"-?\d+(?:\.\d+)?"

# 引擎输出的行是**固定模板**（见 tools/findstruct.c 的 printf），
# 整行对着模板换最准；匹配不上才退回下面的碎片替换。
LINES = (
    # `  #3 方块 (612,4900)  距你 4938.1 格  南东`
    (re.compile(rf"^(?P<pre>\s*)#(?P<i>\d+) 方块 \((?P<x>{_NUM}),(?P<z>{_NUM})\)\s+"
                rf"距你 (?P<d>{_NUM}) 格\s*(?P<dir>[北南东西]*)\s*$"),
     lambda m: f"{m['pre']}#{m['i']} block ({m['x']},{m['z']})  "
               f"{m['d']} blocks from you" + (f"  {_dirs(m['dir'])}" if m["dir"] else "")),
    # `  区块 (3,-2)  方块 (48,-32)  距中心 57 格  群系 deep_cold_ocean`
    (re.compile(rf"^(?P<pre>\s*)区块 \((?P<cx>{_NUM}),(?P<cz>{_NUM})\)\s+"
                rf"方块 \((?P<bx>{_NUM}),(?P<bz>{_NUM})\)\s+"
                rf"距中心 (?P<d>{_NUM}) 格\s*(?P<rest>.*)$"),
     lambda m: f"{m['pre']}chunk ({m['cx']},{m['cz']})  block ({m['bx']},{m['bz']})  "
               f"{m['d']} blocks from center  "
               + re.sub(r"群系\s*([A-Za-z_]+)", r"biome \1", m["rest"])
                 .replace("（群系 ", "(biome ").strip()),
    # `半径 300 方块内没找到 末地城（步长 64，可能太小，试试加大半径）`
    (re.compile(rf"半径 (?P<r>{_NUM}) 方块内没找到 (?P<name>.+?)"
                rf"（步长 (?P<s>{_NUM})，可能太小，试试加大半径）"),
     lambda m: f"Nothing found for {m['name']} within {m['r']} blocks "
               f"(step {m['s']} — maybe too small, try a bigger radius)"),
    # `最近的 末地城：方块 (100,200)，距中心 223 格（步长 64，实际位置在附近 ±32 格内）`
    (re.compile(rf"最近的 (?P<name>.+?)：方块 \((?P<x>{_NUM}),(?P<z>{_NUM})\)，"
                rf"距中心 (?P<d>{_NUM}) 格（步长 (?P<s>{_NUM})，实际位置在附近 ±(?P<w>{_NUM}) 格内）"),
     lambda m: f"Nearest {m['name']}: block ({m['x']},{m['z']}), {m['d']} from center "
               f"(step {m['s']}, the real spot is within about ±{m['w']} blocks)"),
    # `种子 20260928，中心区块 (0,0)，半径 1 区块（16 方块）——下面是过了群系检查的（真的会生成）`
    (re.compile(rf"^种子 (?P<seed>{_NUM})，中心区块 \((?P<cx>{_NUM}),(?P<cz>{_NUM})\)，"
                rf"半径 (?P<n>{_NUM}) 区块（(?P<w>{_NUM}) 方块）"
                rf"——下面是过了群系检查的（真的会生成）$"),
     lambda m: f"Seed {m['seed']}, center chunk ({m['cx']},{m['cz']}), "
               f"radius {_plural(m['n'], 'chunk')} ({_plural(m['w'], 'block')}) — "
               f"biome-checked only (these really generate)"),
    # `范围内的 4 个` / `…还有 9 个`
    (re.compile(r"范围内的 (?P<n>\d+) 个"),
     lambda m: f"{m['n']} in range"),
    (re.compile(r"…还有 (?P<n>\d+) 个"),
     lambda m: f"…and {m['n']} more"),
    (re.compile(r"距离窗口：\s*≥ (?P<n>\d+) 方块（只要远的）"),
     lambda m: f"Distance window: ≥ {m['n']} blocks (far ones only)"),
    (re.compile(r"距离窗口：\s*≤ (?P<n>\d+) 方块"),
     lambda m: f"Distance window: ≤ {m['n']} blocks"),
    (re.compile(r"距离窗口：\s*(?P<a>\d+) ~ (?P<b>\d+) 方块"),
     lambda m: f"Distance window: {m['a']} ~ {m['b']} blocks"),
)


def _plural(n, word):
    return f"{n} {word}" if str(n) in ("1", "1.0") else f"{n} {word}s"


def _blocks(text):
    """`距中心 345 格` 里的 `格` → `blocks`；只换数字后面的那个"""
    return re.sub(r"(?<=[\d.])\s*格", " blocks", text)


def _plural_fix(text):
    """数字后面的 chunk/block/step 该单就单、该复就复（`#3 block` 那种别动）"""
    def fix(m):
        return _plural(m.group(1), m.group(2))
    return re.sub(r"(?<!#)\b(\d+(?:\.\d+)?)\s+(chunk|block|step)\b", fix, text)


def _punct(text):
    """中文标点换英文（引擎里那些全角括号、逗号、破折号）"""
    for zh, en in (("，", ", "), ("（", " ("), ("）", ")"), ("：" , ": "),
                   ("——", " — "), ("、", ", ")):
        text = text.replace(zh, en)
    return text


def _names(text):
    out = []
    for name in NAMES:
        en = i18n.t(name)
        if en != name:                       # 译文表里有，才换
            out.append((name, en))
    for zh, en in out:
        text = text.replace(zh, en)
    return text


def localize(line, lang=None):
    """把一行引擎输出翻成当前语言（默认只有 en 才动）。"""
    if (lang or i18n.current()) != "en":
        return line
    if not line or not re.search(r"[\u4e00-\u9fff]", line):
        return line
    text = _names(line)
    for pattern, fn in LINES:
        if pattern.search(text):
            text = pattern.sub(lambda m: fn(m), text)
    for zh, en in PHRASES:
        text = text.replace(zh, en)
    text = re.sub(r"\[(主世界|下界|末地)\]",
                  lambda m: "[" + DIMS[m.group(1)] + "]", text)
    text = _dirs(text)
    text = _blocks(text)
    text = re.sub(r"(\d+)\s*个", r"\1", text)      # 「还有 3 个」→「and 3」
    text = _plural_fix(text)
    text = _punct(text)
    text = re.sub(r"[ \t]{2,}", "  ", text)
    return text


def localize_text(text, lang=None):
    """整块输出过一遍（保持原来的换行）。"""
    if (lang or i18n.current()) != "en":
        return text
    raw = str(text)
    out = [localize(ln, lang="en") for ln in raw.splitlines()]
    return "\n".join(out) + ("\n" if raw.endswith("\n") else "")
