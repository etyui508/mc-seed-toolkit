#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把工具包打成 zip（会保留 Unix 执行权限，并自动排除配置/缓存/记录）。

用法: python3 make-zip.py [--lite] [输出路径]
      --lite 打包"精简版"：不带随包的 runtime/ Java（体积小，用系统/启动器的 Java）
"""
import os
import stat
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))          # app/ 目录
ROOT = os.path.dirname(HERE)                               # 工具包根目录（打包对象）
EXCLUDE_DIRS = {"__pycache__", "logs", "记录", ".git", ".build-cache", "build"}
EXCLUDE_FILES = {".mc-tool.json", ".tool-config.json", "坐标记录.txt", "算种子记录.txt",
                 "struct-hints.txt", "seed-confirmed.txt", "coordinates.txt", "portal-info.txt",
                 "observations-merged.txt", ".seedcalc-obs.txt"}
EXCLUDE_PREFIX = (".cache-gateways-", ".end_gateways")
# 两个版本的说明各带各的：精简版别把"U 盘版（自带 Java）"那份带上，完整版也别带"精简版"那份
EXECUTABLE = ("out/findstruct", "out/findstruct.exe", "run.sh",
              "tools/build-all.sh", "tools/build-cubiomes.sh", "tools/build-findstruct-win.sh",
              "tools/install-to-wsl.sh", "app/make-zip.py")


def mode_for(rel):
    """zip 里给文件记权限：解压后这些必须还能直接执行（自带 JRE 的 bin/ 也算）"""
    if rel in EXECUTABLE:
        return 0o755
    if rel.startswith("runtime/") and "/bin/" in rel:
        return 0o755        # 自带的 java / keytool 等等
    if rel.endswith((".sh", ".py")):
        return 0o755
    return 0o644


def main():
    argv = sys.argv[1:]
    lite = "--lite" in argv
    top_override = None
    rest = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--lite":
            i += 1
        elif a == "--name" and i + 1 < len(argv):
            top_override = argv[i + 1]
            i += 2
        elif a.startswith("--name="):
            top_override = a.split("=", 1)[1]
            i += 1
        else:
            rest.append(a)
            i += 1
    default = "mc-seed-toolkit-lite.zip" if lite else "mc-seed-toolkit.zip"
    out = rest[0] if rest else os.path.join(os.path.dirname(ROOT), default)
    count = 0
    # 解压后是一个文件夹，别把文件散一地（--name 可以改这个文件夹的名字）
    top = top_override or os.path.basename(ROOT)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            if lite:
                dirs[:] = [d for d in dirs if d != "runtime"]
            for name in sorted(files):
                full = os.path.join(root, name)
                rel = os.path.relpath(full, ROOT).replace(os.sep, "/")
                if name in EXCLUDE_FILES or name.startswith(EXCLUDE_PREFIX):
                    continue
                mode = mode_for(rel)
                info = zipfile.ZipInfo(f"{top}/{rel}")
                info.external_attr = (stat.S_IFREG | mode) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                with open(full, "rb") as fh:
                    z.writestr(info, fh.read())
                count += 1
    size = os.path.getsize(out)
    print(f"打包完成: {out}（{count} 个文件，{size / 1024:.0f} KB）")
    print("已自动排除：本地配置、种子缓存、坐标记录")


if __name__ == "__main__":
    main()
