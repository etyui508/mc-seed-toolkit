#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把模组按游戏版本整理成：

  mods/
    1.16.5/
      seedhelper-1.1.0.jar              ← 记录模组
      archive-world-downloader-1.16.5.jar ← 下载器
      说明.txt
    1.17.1/
      …

只整理"两个都齐了"的版本；缺一个的会列出来提醒。
"""
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MODS = os.path.join(ROOT, "mods")
MULTI = os.path.join(MODS, "multi")
DLS = os.path.join(ROOT, ".build-cache", "downloaders")
README = "要装的东西.txt"


def ver_key(v):
    m = re.match(r"^(\d+)\.(\d+)(?:\.(\d+))?$", v)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)) if m else (0, 0, 0)


def main():
    seedhelpers = {}
    for f in os.listdir(MULTI) if os.path.isdir(MULTI) else []:
        m = re.match(r"seedhelper-1\.1\.0\+(\S+)\.jar$", f)
        if m:
            seedhelpers[m.group(1)] = os.path.join(MULTI, f)
    downloaders = {}
    for f in os.listdir(DLS) if os.path.isdir(DLS) else []:
        if f.endswith(".jar") and "__" in f:
            ver, name = f.split("__", 1)
            downloaders[ver] = (os.path.join(DLS, f), name)
    # 1.20.5+ 我们用打过补丁的 SWD（修了"服务器地址带端口就崩"），优先用它
    for f in os.listdir(MULTI) if os.path.isdir(MULTI) else []:
        m = re.match(r"simple-world-downloader-(\S+)-swdpathfix\.jar$", f)
        if m:
            downloaders[m.group(1)] = (os.path.join(MULTI, f), f)

    ready = sorted(set(seedhelpers) & set(downloaders), key=ver_key)
    only_sh = sorted(set(seedhelpers) - set(downloaders), key=ver_key)
    only_dl = sorted(set(downloaders) - set(seedhelpers), key=ver_key)

    os.makedirs(MODS, exist_ok=True)
    for ver in ready:
        folder = os.path.join(MODS, ver)
        os.makedirs(folder, exist_ok=True)
        shutil.copy2(seedhelpers[ver], os.path.join(folder, "seedhelper-1.1.0.jar"))
        dl_path, dl_name = downloaders[ver]
        shutil.copy2(dl_path, os.path.join(folder, dl_name))
        with open(os.path.join(folder, README), "w", encoding="utf-8") as fh:
            fh.write(
                f"Minecraft {ver}（Fabric）要装的两个模组\n"
                + "=" * 44 + "\n\n"
                "把这两个 jar 都复制到 .minecraft\\mods\\ 里面：\n\n"
                f"  1) seedhelper-1.1.0.jar\n"
                "     记录模组：自动记末地柱子 / 史莱姆区块 / 哈希种子 / 群系\n\n"
                f"  2) {dl_name}\n"
                "     下载器：把服务器地图存到本地（算种子必须要它）\n\n"
                "还要装 Fabric API（去 Modrinth 搜 fabric-api，挑对应版本的）。\n\n"
                "几个注意：\n"
                f"  · 这两个都是给 {ver} 编的，装到别的版本上游戏会报错\n"
                "  · 两个缺一不可：只有下载器只能下地图，只有记录模组没地图可算\n"
                "  · 装好之后：进服 → 开下载器飞一圈（末地中央岛一定要去）→ 回主菜单选 1 算种子\n")
    print(f"整理好 {len(ready)} 个版本：" + ", ".join(ready))
    if only_sh:
        print("只有记录模组、还缺下载器的：" + ", ".join(only_sh))
    if only_dl:
        print("只有下载器、记录模组还没编好的：" + ", ".join(only_dl))
    return 0


if __name__ == "__main__":
    sys.exit(main())
