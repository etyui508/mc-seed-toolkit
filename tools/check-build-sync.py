#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""产物与源码同步检查：out/ 里那些二进制，真的是这份源码编出来的吗？

为什么需要它：包里分发的 out/*.class、out/findstruct 是**先编好再打包**的，
而更新时客户端只会比对"已装文件 vs 新包清单"的哈希 —— 万一源码改了、产物忘了
重编，谁都不会发现，于是发出去的就是旧代码编的老二进制。

怎么判：build-all.sh 编完之后会写一份 out/.build-id（所有源码的内容哈希）。
这里重新算一遍，对不上就是"改了没重编"。

  python3 tools/check-build-sync.py            # 检查（对不上退出码 1）
  python3 tools/check-build-sync.py --record   # 记下当前源码的指纹（编完就调它）
  python3 tools/check-build-sync.py -v         # 连每个源码文件一起列出来

没有 .build-id 的老包不拦人，只打一句提醒（退回按修改时间看一眼）。
"""
import argparse
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "out")
BUILD_ID = os.path.join(OUT, ".build-id")

# 参与编译的源码：Java 那几支 + C 那支（findstruct）
SOURCES = ("*.java",)


def source_files():
    import glob
    out = []
    for pat in SOURCES:
        out += glob.glob(os.path.join(HERE, pat))
    for name in ("findstruct.c",):
        p = os.path.join(HERE, name)
        if os.path.isfile(p):
            out.append(p)
    return sorted(out)


def fingerprint():
    h = hashlib.sha256()
    for path in source_files():
        rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        with open(path, "rb") as fh:
            h.update(hashlib.sha256(fh.read()).digest())
    return h.hexdigest()[:32]


def artifact_of(java):
    """这个 .java 编出来的 .class 大概在哪（找得到就比时间，找不到就跳过）"""
    base = os.path.splitext(os.path.basename(java))[0]
    for cand in (os.path.join(OUT, base + ".class"),
                 os.path.join(OUT, "26.3", base + ".class")):
        if os.path.isfile(cand):
            return cand
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--record", action="store_true", help="记下当前源码的指纹")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    fp = fingerprint()
    if args.record:
        os.makedirs(OUT, exist_ok=True)
        with open(BUILD_ID, "w", encoding="utf-8") as fh:
            fh.write(fp + "\n")
        print(f"记下构建指纹 {fp}（{len(source_files())} 个源码文件）")
        return 0

    old = ""
    if os.path.isfile(BUILD_ID):
        with open(BUILD_ID, encoding="utf-8") as fh:
            old = fh.read().strip()

    if args.verbose:
        for path in source_files():
            art = artifact_of(path)
            print(f"  {os.path.relpath(path, ROOT):34} -> "
                  f"{os.path.relpath(art, ROOT) if art else '（没有对应产物）'}")

    if old:
        if old == fp:
            print(f"✅ 产物与源码同步（指纹 {fp}）")
            return 0
        print("❌ out/ 里的产物不是这份源码编出来的：")
        print(f"   源码指纹 {fp}")
        print(f"   产物指纹 {old}")
        print("   → 跑 bash tools/build-all.sh 重编（findstruct 另外编），"
              "编完它会自动更新指纹")
        return 1

    # 还没有指纹：退回按修改时间提示一下，但不拦人（解压/克隆出来的包时间戳不可靠）
    stale = [p for p in source_files()
             if os.path.splitext(p)[1] == ".java"
             and (art := artifact_of(p)) and os.path.getmtime(p) > os.path.getmtime(art)]
    if stale:
        print("⚠ 没有 out/.build-id，按修改时间看这些源码比产物新：")
        for p in stale:
            print("   ", os.path.relpath(p, ROOT))
        print("   （时间戳不一定靠谱，建议跑一次 build-all.sh 重新记指纹）")
        return 0
    print("（没有 out/.build-id，这次只按修改时间看了一眼：没有明显不同步）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
