#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""英文界面里还会不会漏出中文（English leak scan）。

每个界面字符串都要能翻；漏一个，英文用户就看到一个中文。这个自测**开一个真 pty**，
用英文用户的身份把整个菜单走一圈（查结构 → 设置 → 协议 → 导出 → 回滚 → 检查更新 →
反馈 → 退出），然后逐行数屏幕上剩下的中文：

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
               # 日志里那几个占位符是写进文件的字面量（打码用），也是故意的
               "<种子>", "<路径>", "<用户>", "<存档路径>", "<观测文件>",
               # 选语言那屏：语言名照惯例用**它自己的语言**写（中文 / English）
               "1) 中文   2) English",
               # 框太窄时路径会被截成 "记录/坐标记录.…"，那也是真路径
               "记录/坐标记录.", "坐标记录.…", "坐标记录记", "记录/算种子记录.", "记录/日志.",
               "语言 / Language", "1) 中文   2) English   [")
_MASK = {tok: "<path>" for tok in INTENTIONAL}

# 主菜单上依次要点的：结构 / 设置 / 协议 / 导出 / 回滚 / 检查更新 / 反馈 / 退出
MAIN_SEQ = ["2", "3", "6", "7", "8", "4", "5", "0"]

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
    text, rc = ttydrive.drive(["bash", "run.sh"], tour_answer, cwd=box,
                              env=env, timeout=900)
    done = ttydrive.looks_done(text)

    lines = [ln.rstrip() for ln in text.splitlines()]
    hits = [(i, ln) for i, ln in enumerate(lines, 1)
            if CJK.search(mask_intentional(ln))]

    print(f"英文会话输出 {len(lines)} 行，其中 {len(hits)} 行含中文"
          f"（{len(hits) * 100 // max(len(lines), 1)}%），退出码 {rc}")
    if hits:
        print("---- 还漏中文的行 ----")
        for i, ln in hits:
            print(f"{i:>4}| {ln[:120]}")
    if not done:
        print("\n⚠ 这一圈没走到底（没看到退出前那句「再见 / Bye」）—— 界面提示可能变了，"
              "脚本要对一下；这种情况下的中文行数不算数")
    if not args.keep:
        T.shutil.rmtree(box, ignore_errors=True)
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
