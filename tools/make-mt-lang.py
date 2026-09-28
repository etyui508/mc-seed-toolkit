#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 app/lang/mt.json —— 「人机翻译版」界面文字（主菜单彩蛋 Yes ③ 用的）。

做法是**真的机翻**，不是手写凑：把 en.json 里现成的英文译文塞回翻译引擎，
再翻成中文。产出的就是那种"看得懂、但哪儿都不对"的句子：

    Quit                    -> 辞职
    Fabric API required     -> 需要结构 API
    Find the world seed     -> 寻找世界种子

为什么绕这一圈：界面本来是中文写的，直接"翻成中文"什么都不会发生。先拿英文
当输入再翻回来，才是用户平时见到的那种机翻。手写凑不出这个味道 —— 也不该由
某个人来决定哪一句"像不像机翻"，交给引擎最公平。

结果一份进 app/lang/mt.json，一份缓存到 tools/mt-cache.json：
以后重跑不用再联网（发布机器连不上 Google 也能重建），同一句也永远是同一个
结果，不会这次发布和下次发布的机翻腔对不上。

    python3 tools/make-mt-lang.py              # 用缓存生成（缺的才联网）
    python3 tools/make-mt-lang.py --refresh    # 全部重翻，忽略缓存
    python3 tools/make-mt-lang.py --check      # 只比对，不写文件（离线）

引擎走 Google 翻译的公开端点。国内直连不通，需要代理：
    MT_PROXY=http://172.28.160.1:7897 python3 tools/make-mt-lang.py
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EN = os.path.join(ROOT, "app", "lang", "en.json")
MT = os.path.join(ROOT, "app", "lang", "mt.json")
CACHE = os.path.join(HERE, "mt-cache.json")

PROXY = os.environ.get("MT_PROXY", "http://172.28.160.1:7897")
ENDPOINT = "https://translate.googleapis.com/translate_a/single"
PACE = 0.30                # 每句之间歇一下，别把公开端点打急眼
RETRIES = 4

# 翻完之后的小替换：引擎把 Minecraft 翻成"我的世界"，但这个彩蛋叫"雷时东"
# （主菜单 9 → Yes ③ 的那句招牌就是它）。只改这一个词，别的一律照引擎的来。
TERMS = (
    ("我的世界", "雷时东"),
    ("Minecraft", "雷时东"),
)

PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
MARKER = "ZQ%dQZ"          # 全大写记号能原样穿过翻译（<PH0>、[[0]]、私有区字符都试过）


def has_cjk(text):
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def protect(text):
    """把 {name} 换成记号，免得引擎把大括号里面也翻了（{path} -> {路径}）"""
    names = PLACEHOLDER.findall(text)
    for i, name in enumerate(names):
        text = text.replace("{%s}" % name, MARKER % i, 1)
    return text, names


def restore(text, names):
    for i, name in enumerate(names):
        text = text.replace(MARKER % i, "{%s}" % name)
    return text


def translate(text):
    """翻一句。成功返回译文，失败抛异常。"""
    query = urllib.parse.urlencode({"client": "dict-chrome-ex", "sl": "en",
                                    "tl": "zh-CN", "dt": "t", "q": text})
    url = ENDPOINT + "?" + query
    last = ""
    for attempt in range(RETRIES):
        done = subprocess.run(["curl", "-s", "-A", "Mozilla/5.0",
                               "-x", PROXY, "--max-time", "60", url],
                              capture_output=True, text=True)
        last = (done.stdout or "").strip()
        if last.startswith("[["):
            data = json.loads(last)
            return "".join(seg[0] for seg in data[0] if seg and seg[0])
        time.sleep(1.5 * (attempt + 1))      # 429 就是被限流了，退一步再来
    raise RuntimeError(f"翻译失败：{last[:80]}")


def machine_zh(english, cache, stats):
    """一句英文 -> 机翻中文（先查缓存）"""
    if english in cache:
        stats["hit"] += 1
        return cache[english]
    protected, names = protect(english)
    # 开头的换行/缩进是排版的一部分，翻译前后都得留着
    lead = protected[:len(protected) - len(protected.lstrip())]
    body = protected.strip()
    out = lead + translate(body) if body else protected
    if any((MARKER % i) in out for i in range(len(names))):
        out = restore(out, names)
    elif names:
        raise RuntimeError(f"占位符被翻译弄丢了：{english!r} -> {out!r}")
    for zh, mt in TERMS:
        out = out.replace(zh, mt)
    cache[english] = out
    stats["new"] += 1
    time.sleep(PACE)
    return out


def build(refresh):
    with open(EN, encoding="utf-8") as fh:
        table = json.load(fh)
    try:
        with open(CACHE, encoding="utf-8") as fh:
            cache = {} if refresh else json.load(fh)
    except OSError:
        cache = {}

    stats = {"hit": 0, "new": 0, "skip": 0}
    out = {}
    for key, english in table.items():
        if not isinstance(english, str) or not english.strip():
            continue
        if key.startswith("log:"):
            continue            # 日志保持中文：彩蛋归彩蛋，反馈日志得让人看得懂
        if not has_cjk(key):
            continue            # 本来就是英文/符号的，不折腾
        out[key] = machine_zh(english, cache, stats)
    return dict(sorted(out.items())), cache, stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="忽略缓存，全部重翻")
    ap.add_argument("--check", action="store_true", help="只比对，不写文件（不联网）")
    args = ap.parse_args()

    try:
        with open(CACHE, encoding="utf-8") as fh:
            cache = json.load(fh)
    except OSError:
        cache = {}

    if args.check:
        # 检查模式完全不联网：拿缓存重算一遍，和盘上的 mt.json 对比
        missing = []
        with open(EN, encoding="utf-8") as fh:
            for key, english in json.load(fh).items():
                if key.startswith("log:") or not has_cjk(key):
                    continue
                if english not in cache:
                    missing.append(key)
        if missing:
            print(f"❌ 缓存里还缺 {len(missing)} 句，先联网生成一次", file=sys.stderr)
            return 1
        want, _cache, _st = build(refresh=False)
        text = json.dumps(want, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        with open(MT, encoding="utf-8") as fh:
            got = fh.read()
        if got == text:
            print(f"✅ mt.json 和缓存一致（{len(want)} 条）")
            return 0
        print("❌ mt.json 和缓存对不上，重跑：python3 tools/make-mt-lang.py",
              file=sys.stderr)
        return 1

    table, cache, stats = build(args.refresh)

    # 排版前先保住开头的空行：mt.json 里那些 "\n  xxx" 是界面的缩进
    text = json.dumps(table, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with open(MT, "w", encoding="utf-8") as fh:
        fh.write(text)
    with open(CACHE, "w", encoding="utf-8") as fh:
        json.dump(dict(sorted(cache.items())), fh, ensure_ascii=False, indent=1)
        fh.write("\n")

    print(f"写入 {os.path.relpath(MT, ROOT)}（{len(table)} 条；"
          f"缓存命中 {stats['hit']}，新翻 {stats['new']}）")
    for probe in ("主菜单", "退出", "设置", "计算种子", "从下载的存档反推世界种子"):
        if probe in table:
            print(f"  {probe}  ->  {table[probe]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
