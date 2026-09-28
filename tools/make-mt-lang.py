#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 app/lang/mt.json —— 「人机翻译版」界面文字（主菜单彩蛋 Yes ③ 用的）。

这不是人写的译文，是**机器硬凑**的：先把几个关键词换成早期机翻腔的说法
（种子→籽、末地→结束、要塞→强壮的保有地…），再往中文字与中文字之间塞空格
—— 那种「一 个 字 一 个 空 格」的观感。

几条规矩：
  · 英文、路径、{占位符} 一律不碰（挨着它们不塞空格），免得把程序自己
    认的字符串弄坏；
  · 日志事件（"log:" 开头的键）**不翻** —— 彩蛋归彩蛋，反馈日志得让人看得懂；
  · 没覆盖到的句子照 i18n 的老规矩回落成中文，不会留空。

    python3 tools/make-mt-lang.py            # 重新生成
    python3 tools/make-mt-lang.py --check    # 只比对，不写文件（发布前查有没有忘跑）
"""
import argparse
import json
import os
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EN = os.path.join(ROOT, "app", "lang", "en.json")
MT = os.path.join(ROOT, "app", "lang", "mt.json")

# 关键词替换表：左 = 正经说法，右 = 机翻说法。按顺序应用，长的写前面。
TERMS = (
    ("我的世界", "雷时东"),
    ("Minecraft", "雷时东"),
    ("世界种子", "世界的籽"),
    ("海底神殿", "海洋的纪念碑"),
    ("试炼密室", "审判的密室"),
    ("远古城市", "古老的城市"),
    ("要塞", "强壮的保有地"),
    ("鞘翅", "鞘的翅"),
    ("群系", "生物群的群"),
    ("客户端", "客户的端"),
    ("反推", "反向推出"),
    ("回滚", "滚回去"),
    ("剪贴板", "剪贴的板"),
    ("出错", "错误已经发生"),
    ("末地", "结束"),
    ("末影", "结束"),
    ("种子", "籽"),
    ("结构", "建筑物"),
)

# 手写覆盖：机器凑不出来的、或者想留个彩蛋记号的那几句
OVERRIDES = {
    # 开屏副标题直接换成那串机翻产物（本来就是彩蛋，不指望它还说人话）
    "从下载的存档破出世界种子，再用种子算结构坐标": "雷时东雷时东粉末雷时东滚木",
}


def is_wide(ch):
    return unicodedata.east_asian_width(ch) in ("W", "F")


def has_cjk(text):
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def space_out(text):
    """中文字和中文字之间塞一个空格。英文、路径、{占位符} 边上不动。"""
    out = []
    prev = False
    for ch in text:
        wide = is_wide(ch)
        if wide and prev:
            out.append(" ")
        out.append(ch)
        prev = wide
    return "".join(out)


def garble(text):
    text = str(text)
    if text in OVERRIDES:
        return OVERRIDES[text]
    for zh, mt in TERMS:
        text = text.replace(zh, mt)
    return space_out(text)


def build():
    with open(EN, encoding="utf-8") as fh:
        table = json.load(fh)
    out = {}
    for key, value in table.items():
        if not isinstance(value, str):
            continue
        if key.startswith("log:"):
            continue          # 日志保持中文，别把反馈日志也搅了
        if not has_cjk(key):
            continue          # 本来就是英文/符号的，不动
        out[key] = garble(key)
    return dict(sorted(out.items()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只比对，不写文件")
    args = ap.parse_args()

    new = build()
    text = json.dumps(new, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    try:
        with open(MT, encoding="utf-8") as fh:
            old = fh.read()
    except OSError:
        old = ""

    if args.check:
        if old == text:
            print(f"✅ mt.json 是最新的（{len(new)} 条）")
            return 0
        print(f"❌ mt.json 和 en.json 对不上，请重跑：python3 tools/make-mt-lang.py",
              file=sys.stderr)
        return 1

    with open(MT, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"写入 {os.path.relpath(MT, ROOT)}（{len(new)} 条，"
          f"跳过日志键和纯英文句子）")
    for probe in ("主菜单", "计算种子", "种子", "从下载的存档破出世界种子，再用种子算结构坐标"):
        if probe in new:
            print(f"  {probe}  ->  {new[probe]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
