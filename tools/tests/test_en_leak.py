#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""英文界面里还会不会漏出中文（English leak scan）。

每个界面字符串都要能翻；漏一个，英文用户就看到一个中文。这个自测**开一个真 pty**，
用英文用户的身份走两圈：

  ① 老用户那一圈：查结构 → 设置 → 协议 → 导出 → 回滚 → 检查更新 → 反馈 → 退出；
  ② 首次启动那一圈：配置是空的，语言选择 → 用户协议 → 引导 都会走一遍
     （专门盯"选语言之前"那几屏 —— 开屏和协议卡片也得跟着用户选的语言走）。

两圈都逐行数屏幕上剩下的中文：

    python3 tools/tests/test_en_leak.py            # 快跑（结构半径 300）
    python3 tools/tests/test_en_leak.py --full     # 半径 800，跟线上实测一样
    python3 tools/tests/test_en_leak.py --max 5    # 允许最多 5 行中文（默认 0）

退出码：0 = 没超过允许的中文行数；1 = 超了；2 = 这一圈没走完（测试本身失效了，
比如界面改了导致脚本对不上，这时候"通过"是假通过）。

为什么不用管道喂 stdin：见 tools/tests/ttydrive.py 的说明 —— 管道版会错位，
走到一半就退出还报通过（这个坑真踩过）。
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_integration as T          # noqa: E402  借用它的 sandbox()
import ttydrive                       # noqa: E402

CJK = re.compile(r"[\u4e00-\u9fff]")

# 这些中文是**故意**留在界面上的：目录名 / 文件名 / 程序自己解析的标记。
# 数漏字的时候先把它们抠掉，不然永不为零，就没法当门禁用。
INTENTIONAL = ("记录/坐标记录.txt", "记录/算种子记录.txt", "记录/日志.txt", "记录/导出",
               "记录/", "坐标记录.txt", "算种子记录.txt", "日志.txt", "要装的东西.txt",
               "使用说明.md", "用户协议与隐私政策.md", "反馈包", ".update-backup",
               # 协议文档本身的名字（英文用户看的是 .en.md 那份，文件名仍是中文）
               "用户协议与隐私政策.en.md",
               # 日志里那几个占位符是写进文件的字面量（打码用），也是故意的
               "<种子>", "<路径>", "<用户>", "<存档路径>", "<观测文件>",
               # 选语言那屏：语言名照惯例用**它自己的语言**写（中文 / English）
               "1) 中文   2) English",
               # 框太窄时路径会被截成 "记录/坐标记录.…"，那也是真路径
               "记录/坐标记录.", "坐标记录.…", "坐标记录记", "记录/算种子记录.", "记录/日志.",
               "语言 / Language", "1) 中文   2) English   [")

# 主菜单上依次要点的：结构 / 设置 / 协议 / 导出 / 回滚 / 检查更新 / 反馈 / 退出
MAIN_SEQ = ["2", "3", "6", "7", "8", "4", "5", "0"]

# 选语言那屏是刻意双语的（语言名照惯例用他自己的语言写），不算漏字
_BILINGUAL = ("请选择语言  /  Choose your language", "1) 中文", "2) English",
              "欢迎 / Welcome", "选择语言", "Choose your language")
_MASK = {tok: "<lang>" for tok in _BILINGUAL}
_MASK.update({tok: "<path>" for tok in INTENTIONAL})

# 结构查询的搜索半径（由 main() 按 --full 设）
RADIUS = "300"


def mask_intentional(line):
    for tok, rep in _MASK.items():
        line = line.replace(tok, rep)
    return line


def tour_answer(segment, index, state):
    """看着屏幕回答：这一屏是什么，就敲该敲的那个键。"""
    if re.search(r"0 = back to the main menu|0 = 返回主菜单", segment):
        q = state.setdefault("struct", ["1", "0"])      # 先查海底神殿，再返回
        return q.pop(0) if q else "0"
    if re.search(r"Main menu|主菜单", segment):
        q = state.setdefault("main", list(MAIN_SEQ))
        return q.pop(0) if q else "0"
    if re.search(r"搜索半径|Radius", segment):
        return RADIUS
    if re.search(r"现在更新吗|Update now|更新完成", segment):
        return "n"                                       # 测试里不真的更新
    return ""                                            # 其它一律回车用默认


def first_run_answer(segment, index, state):
    """首次启动那一圈：配置是空的，所以语言 > 协议 > 引导都会走一遍。

    这里专门盯"选语言之前"那几屏 —— 开屏、进度条、用户协议卡片都得等用户
    选完语言再画，否则英文用户第一眼就是一整屏中文（2026-09-29 修的就是这个）。
    """
    if re.search(r"Choose your language|选择语言", segment):
        return "2"                                       # 英文用户
    if re.search(r"Main menu|主菜单", segment):
        return "0"
    return ""                                            # 其余一路回车用默认


def scan(box, answer, env):
    """跑一圈，数屏幕上还剩几行中文"""
    text, rc = ttydrive.drive(["bash", "run.sh"], answer, cwd=box,
                              env=env, timeout=900)
    lines = [ln.rstrip() for ln in text.splitlines()]
    hits = [(i, ln) for i, ln in enumerate(lines, 1)
            if CJK.search(mask_intentional(ln))]
    return text, rc, lines, hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--max", type=int, default=0,
                    help="允许的中文行数上限（默认 0）")
    ap.add_argument("--keep", action="store_true", help="保留沙箱目录")
    args = ap.parse_args()
    global RADIUS
    RADIUS = "800" if args.full else "300"

    findstruct = os.path.join(T.ROOT, "out", "findstruct")
    if not os.path.exists(findstruct) and not os.path.exists(findstruct + ".exe"):
        print("没有 out/findstruct —— 跳过英文漏字扫描（精简版？）")
        return 0

    box = T.sandbox()
    with open(os.path.join(box, ".mc-tool.json"), "w", encoding="utf-8") as fh:
        json.dump({"seed": T.SEED, "mc": T.VER, "lang": "en", "show_seed": False,
                   "agreed": "1:test", "channel": "stable"}, fh)

    env = {"MC_NO_UPDATE": "1", "MCVER": T.VER, "PYTHONUTF8": "1",
           "PYTHONIOENCODING": "utf-8", "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8"}
    text, rc, lines, hits = scan(box, tour_answer, env)
    done = ttydrive.looks_done(text)

    print(f"英文会话输出 {len(lines)} 行，其中 {len(hits)} 行含中文"
          f"（{len(hits) * 100 // max(len(lines), 1)}%），退出码 {rc}")
    if hits:
        print("---- 还漏中文的行 ----")
        for i, ln in hits:
            print(f"{i:>4}| {ln[:120]}")

    # 第二圈：把配置删掉，模拟第一次用（协议 + 引导都要走）
    box2 = T.sandbox()
    os.remove(os.path.join(box2, ".mc-tool.json"))
    text2, rc2, lines2, hits2 = scan(box2, first_run_answer, env)
    done2 = ttydrive.looks_done(text2)
    print(f"\n首次启动那一圈输出 {len(lines2)} 行，其中 {len(hits2)} 行含中文，退出码 {rc2}")
    if hits2:
        print("---- 首次启动还漏中文的行 ----")
        for i, ln in hits2:
            print(f"{i:>4}| {ln[:120]}")
    done = done and done2
    hits = hits + hits2

    if not done:
        print("\n⚠ 这一圈没走到底（没看到退出前那句「再见 / Bye」）—— 界面提示可能变了，"
              "脚本要对一下；这种情况下的中文行数不算数")
    if not args.keep:
        T.shutil.rmtree(box, ignore_errors=True)
        T.shutil.rmtree(box2, ignore_errors=True)
    else:
        print(f"沙箱留着：{box}")
    if not done:
        return 2
    if len(hits) > args.max:
        print(f"\n❌ 超过允许的 {args.max} 行")
        return 1
    print(f"\n✅ 没超过允许的 {args.max} 行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
