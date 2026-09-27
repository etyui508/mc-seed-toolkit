#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""联网实测：GitHub 全挂的时候，自动更新能不能自己退到备用站跑完。

做法：造一个"老版本"的工具目录，把 github.com 整个掐掉（模拟国内直连不上），
然后跑真的 updater.update() —— 真的去线上拿清单、真的下包、真的替换文件。

跑法：python3 tools/tests/test_fallback_live.py
（要联网；没网的话会直接说"跳过"）
"""
import os
import shutil
import sys
import tempfile
import time
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "app"))

import updater                                        # noqa: E402


def make_old_install(tmp):
    root = os.path.join(tmp, "toolkit")
    for rel, body in (("app/VERSION", "1.0.0\n"), ("app/tool.py", "# 旧代码\n"),
                      (".mc-tool.json", '{"seed":123}\n'), ("记录/我的坐标.txt", "别动我\n")):
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)
    updater.ROOT = root
    updater.RECORDS = os.path.join(root, "记录")
    updater.BACKUP_DIR = os.path.join(updater.RECORDS, ".update-backup")
    updater.DIFF_DIR = os.path.join(updater.RECORDS, "更新日志")
    updater.MANAGED_FILE = os.path.join(updater.RECORDS, ".managed-files.json")
    updater.VERSION_FILE = os.path.join(root, "app", "VERSION")
    return root


def main():
    tmp = tempfile.mkdtemp(prefix="mc-fallback-live-")
    ok = True
    try:
        root = make_old_install(tmp)

        real_open = updater._open

        def no_github(url, timeout=None, headers=None):
            if "github.com" in url or "githubusercontent" in url:
                raise urllib.error.URLError("模拟：GitHub 连不上")
            return real_open(url, timeout=timeout, headers=headers)

        updater._open = no_github

        print("== 模拟：GitHub 全挂，只留自己的域名备用站 ==", flush=True)
        t0 = time.time()
        changed, msg = updater.update(verbose=True)
        print(f"update() -> {changed} | {msg} | 用时 {time.time() - t0:.1f}s", flush=True)

        def say(name, cond, extra=""):
            nonlocal ok
            ok = ok and bool(cond)
            print(("  ✅ " if cond else "  ❌ ") + name + (f"   {extra}" if extra else ""))

        say("更新成功", changed, msg)
        say("版本号换成线上的了",
            open(updater.VERSION_FILE, encoding="utf-8").read().strip() != "1.0.0",
            open(updater.VERSION_FILE, encoding="utf-8").read().strip())
        say("程序文件真的换了",
            open(os.path.join(root, "app", "tool.py"), encoding="utf-8").read() != "# 旧代码\n")
        say("种子配置没被动",
            open(os.path.join(root, ".mc-tool.json"), encoding="utf-8").read() == '{"seed":123}\n')
        say("坐标记录没被动",
            open(os.path.join(root, "记录", "我的坐标.txt"), encoding="utf-8").read() == "别动我\n")
        say("旧文件有备份", os.path.isdir(updater.BACKUP_DIR)
            and bool(os.listdir(updater.BACKUP_DIR)))
        say("写了更新差异日志", os.path.isdir(updater.DIFF_DIR)
            and bool(os.listdir(updater.DIFF_DIR)))
        count = sum(len(fs) for _r, _d, fs in os.walk(os.path.join(root, "app")))
        say("app/ 下文件齐了（含 structures/ 那些模块）", count >= 45, f"{count} 个")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n=== " + ("全部通过" if ok else "有失败项") + " ===")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
