#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把"能适配的版本"尽量都铺齐：

  1) 从 Modrinth 找每个版本可用的 Fabric 下载器（Archive WDL / Simple World Downloader）
  2) 给每个版本编一份 seedhelper（记录模组）
  3) 按版本整理到 mods/<版本>/，每个文件夹里放齐"这一版该装的两个 jar"

用法：
  python3 tools/build-all-versions.py --plan        # 只看会做哪些版本
  python3 tools/build-all-versions.py               # 真干
  python3 tools/build-all-versions.py --only-dl     # 只下下载器（快）
  python3 tools/build-all-versions.py --only-sh     # 只编记录模组（慢）
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CACHE = os.path.join(ROOT, ".build-cache")
DL_DIR = os.path.join(CACHE, "downloaders")
MODS = os.path.join(ROOT, "mods")
BY_VER = os.path.join(MODS, "按版本装")
API = "https://api.modrinth.com/v2"
UA = {"User-Agent": "mc-seed-toolkit-build/1.0"}

# 记录模组只支持 1.16.5+（1.16 才有客户端哈希种子）
MIN_VER = (1, 16, 5)


def log(*a):
    print(*a, flush=True)


def get_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read().decode())


def download(url, dest, label):
    if os.path.exists(dest) and os.path.getsize(dest) > 10000:
        return dest
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=300) as r, open(dest + ".part", "wb") as fh:
        shutil.copyfileobj(r, fh)
    os.replace(dest + ".part", dest)
    log(f"    ↓ {label}（{os.path.getsize(dest) // 1024} KB）")
    return dest


def ver_key(v):
    m = re.match(r"^(\d+)\.(\d+)(?:\.(\d+))?", str(v))
    if not m:
        return (0, 0, 0)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))


def release_versions(project):
    """某个 Modrinth 项目支持的全部版本（只要 Fabric），返回 {版本: 文件信息}"""
    out = {}
    page = 0
    while True:
        data = get_json(f"{API}/project/{project}/version"
                        f"?loaders=%5B%22fabric%22%5D&limit=100&offset={page * 100}")
        if not data:
            break
        for v in data:
            for gv in v.get("game_versions", []):
                files = [f for f in v.get("files", []) if f["filename"].endswith(".jar")]
                if files and gv not in out:
                    out[gv] = {"url": files[0]["url"], "name": files[0]["filename"],
                               "project": project}
        page += 1
        if page > 5:
            break
    return out


def plan_versions():
    """能适配的版本 = 有下载器的版本 ∩ ≥1.16.5（记录模组的下限）"""
    log("查 Modrinth 上两个下载器各自支持哪些版本 …")
    wdl = release_versions("wdl")
    swd = release_versions("simple-world-downloader")
    log(f"  Archive WDL：{len(wdl)} 个版本；Simple World Downloader：{len(swd)} 个版本")
    merged = {}
    for gv, info in wdl.items():
        merged.setdefault(gv, info)
    for gv, info in swd.items():
        # 同一版本两个都有时，1.20.5+ 用 SWD（我们一直在用），更老的用 WDL
        if ver_key(gv) >= (1, 20, 5) or gv not in merged:
            merged[gv] = info
    keep = {gv: info for gv, info in merged.items()
            if ver_key(gv) >= MIN_VER and not re.search(r"snapshot|pre-|rc-", gv)}
    return dict(sorted(keep.items(), key=lambda kv: ver_key(kv[0])))


def fetch_downloaders(versions):
    log(f"\n① 下载 {len(versions)} 个版本的下载器")
    got = {}
    for gv, info in versions.items():
        dest = os.path.join(DL_DIR, f"{gv}__{info['name']}")
        try:
            download(info["url"], dest, f"{gv} ← {info['name']}")
            got[gv] = dest
        except Exception as e:
            log(f"    ✗ {gv} 失败：{e}")
    log(f"  拿到 {len(got)} 个")
    return got


def build_seedhelpers(versions, java="java"):
    log(f"\n② 编译 {len(versions)} 个版本的记录模组（每个都要下客户端 + remap，慢）")
    todo = list(versions)
    done, failed = [], []
    for i, gv in enumerate(todo, 1):
        log(f"  [{i}/{len(todo)}] {gv}")
        r = subprocess.run([sys.executable, os.path.join(HERE, "build-mods.py"),
                            "--only-seedhelper", gv],
                           capture_output=True, text=True)
        out = r.stdout + r.stderr
        if r.returncode == 0 and f"seedhelper-1.1.0+{gv}.jar" in out:
            done.append(gv)
        else:
            failed.append(gv)
            tail = [l for l in out.strip().splitlines() if "error:" in l or "✗" in l][:2]
            log("    ✗ " + " / ".join(tail)[:160])
    log(f"  编好 {len(done)} 个，失败 {len(failed)} 个")
    if failed:
        log("  失败的：" + ", ".join(failed))
    return done


def organize(versions, downloaders, built):
    """按版本整理：mods/按版本装/<版本>/ 里放该版本该装的两个 jar"""
    log("\n③ 按版本整理到 mods/按版本装/")
    count = 0
    for gv in versions:
        sh_jar = os.path.join(MODS, "multi", f"seedhelper-1.1.0+{gv}.jar")
        dl_jar = downloaders.get(gv)
        if not os.path.exists(sh_jar) or not dl_jar:
            continue
        folder = os.path.join(BY_VER, gv)
        os.makedirs(folder, exist_ok=True)
        shutil.copy2(sh_jar, os.path.join(folder, "seedhelper-1.1.0.jar"))
        shutil.copy2(dl_jar, os.path.join(folder, os.path.basename(dl_jar).split("__")[-1]))
        with open(os.path.join(folder, "说明.txt"), "w", encoding="utf-8") as fh:
            fh.write(
                f"Minecraft {gv}（Fabric）要装的两个模组\n"
                f"{'=' * 40}\n\n"
                f"把这两个 jar 都复制到 .minecraft\\mods\\ 里：\n"
                f"  · seedhelper-1.1.0.jar              —— 记录模组（记柱子/史莱姆/哈希种子）\n"
                f"  · {os.path.basename(dl_jar).split('__')[-1]}  —— 下载器（把服务器地图存到本地）\n\n"
                f"注意：\n"
                f"  1) 两个都要装，缺一个算不出种子\n"
                f"  2) 版本必须对上 —— 这是给 {gv} 编的，装到别的版本上游戏会报错\n"
                f"  3) 还需要 Fabric API（去 Modrinth 搜 fabric-api，挑 {gv} 的）\n"
            )
        count += 1
    log(f"  整理好 {count} 个版本的文件夹")
    return count


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true", help="只列出会做哪些版本")
    ap.add_argument("--only-dl", action="store_true")
    ap.add_argument("--only-sh", action="store_true")
    a = ap.parse_args()

    versions = plan_versions()
    log(f"\n能适配的版本共 {len(versions)} 个：")
    for gv in versions:
        log(f"    {gv:14} ← {versions[gv]['name']}")
    if a.plan:
        return 0

    downloaders = {}
    built = []
    if not a.only_sh:
        downloaders = fetch_downloaders(versions)
    if not a.only_dl:
        built = build_seedhelpers(versions)
    if not a.only_dl:
        organize(versions, downloaders, built)
    return 0


if __name__ == "__main__":
    sys.exit(main())
