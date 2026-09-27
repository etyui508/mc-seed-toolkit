#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
种子计算器（需要 Simple World Downloader 下载的存档）

原理：
  1) 末地柱子  -> 16 bit（从下载的末地存档里解方块算出来）
  2) 结构位置  -> 每条 3~8 bit（扫存档里的标志方块：海晶石/幽匿催化体/紫珀/下界砖…）
  3) 史莱姆区块 -> 每条 3.3 bit（如果带上模组写的观测文件）
  4) 客户端哈希种子 -> 定死高 16 位并 100% 验证（模组抓的，有它就能出完整 64 位种子）

用法:
  python3 calc_seed.py <下载的存档目录> [--obs 模组的观测文件] [--no-hash]
"""
import argparse
import datetime
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))          # app/ 目录
ROOT = os.path.dirname(HERE)                               # 工具包根目录
sys.path.insert(0, HERE)
import config as cfgmod
import mcvers
import ui
OUT = os.path.join(ROOT, "out")
DEFAULT_OBS = ""
LOG = os.path.join(ROOT, "记录", "算种子记录.txt")
JAVA = cfgmod.find_java()
JAVA_CMD = ([JAVA, "-Dstdout.encoding=UTF-8", "-Dstderr.encoding=UTF-8", "-Dfile.encoding=UTF-8"]
            if JAVA else [])


def java(cls, *args):
    if not JAVA:
        return "（没有可用的 Java）"
    cmd = JAVA_CMD + ["-cp", OUT, cls] + [str(a) for a in args]
    r = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")
    return r.stdout + r.stderr


# 进度行长这样：##PROGRESS enum 12345 65536
_PROGRESS_RE = re.compile(r"^##PROGRESS\s+(\S+)\s+(\d+)\s+(\d+)\s*$")
_PHASE_NAME = {"enum": "枚举低 48 位候选", "hash": "用哈希定高 16 位"}


def run_with_progress(cmd, extra_env=None):
    """跑一个会报进度的 Java 命令：stderr 里的进度画成进度条，stdout 收着返回。

    以前是一口气跑完再打印，中间几十秒到几分钟屏幕上什么都不动
    —— 用户分不清是在算还是卡死了（"卡在 93%" 那种反馈就是这么来的）。
    """
    import time as _time

    env = dict(os.environ, **(extra_env or {}))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            encoding="utf-8", errors="replace", env=env)
    notes = []
    phase = None
    started = _time.time()
    last_draw = 0.0

    def draw(done, total, final=False):
        nonlocal last_draw
        now = _time.time()
        if not final and now - last_draw < 0.15:
            return
        last_draw = now
        frac = done / total if total else 0
        spent = now - started
        eta = (spent / frac - spent) if frac > 0.01 else 0
        name = _PHASE_NAME.get(phase, phase or "")
        line = (f"  {name}  {ui.bar(frac, 24)} {frac*100:5.1f}%"
                f"   已用 {spent:4.0f}s" + (f"  预计还要 {eta:4.0f}s" if eta else ""))
        sys.stdout.write(ui.CLEAR_LINE + line)
        sys.stdout.flush()

    # stdout 必须另开一个线程读：Java 最后可能一口气打印几 MB 候选列表，
    # 管道塞满（64KB）而我们卡在 stderr 上，就死锁了
    import threading
    bucket = []

    def drain():
        bucket.append(proc.stdout.read())

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    done_phase = False                      # 当前阶段的 100% 报出来了没有
    try:
        for line in proc.stderr:
            m = _PROGRESS_RE.match(line.strip())
            if m:
                phase, done, total = m.group(1), int(m.group(2)), int(m.group(3))
                draw(done, total, final=(done >= total))
                if done >= total:
                    print()
                    done_phase = True
                    started = _time.time()      # 下一阶段重新计时
                else:
                    done_phase = False
            elif line.strip():
                notes.append(line.rstrip())
        proc.wait()
        reader.join(timeout=10)
        out = "".join(bucket)
    finally:
        if proc.poll() is None:
            proc.kill()
        # 收尾：万一最后一帧没报出来（进程被杀/Java 那边没发），
        # 也要把进度条画到底并换行 —— 不然条子停在半路，后面的界面会挤到同一行上
        if not done_phase and phase:
            draw(1.0, 1.0, final=True)
            print()
    if notes:
        print("  " + ui.s("｜".join(notes[-3:]), "dim"))
    return out


def findstruct_path():
    """找结构/群系引擎（复核群系采样点要用它）"""
    order = ["findstruct.exe", "findstruct"] if os.name == "nt" else ["findstruct", "findstruct.exe"]
    for name in order:
        cand = os.path.join(OUT, name)
        if os.path.exists(cand):
            return cand
    return None


def verify_biomes(seed, biomes, limit=200):
    """拿模组记录过的群系采样点复核一下这个种子（不参与筛选，纯验证）"""
    path = findstruct_path()
    if not path:
        print("（复核跳过：没找到 out/findstruct）")
        return
    # 下界/末地的点没法比 —— 引擎这边只算主世界
    other_dim = ("the_end", "small_end_islands", "end_midlands", "end_highlands", "end_barrens",
                 "the_void", "nether_wastes", "soul_sand_valley", "crimson_forest",
                 "warped_forest", "basalt_deltas")
    pts = []
    skipped = 0
    for b in biomes:
        if "=" not in b:
            continue
        xz, name = b.split("=", 1)
        if "," not in xz:
            continue
        name = name.strip().split(":", 1)[-1]
        if name in other_dim:
            skipped += 1
            continue
        try:
            x, z = (int(v) for v in xz.split(",", 1))
        except ValueError:
            continue
        pts.append((x, z, name))
    pts = pts[:limit]
    if not pts:
        return
    cmd = [path, "biome2", str(int(seed))]
    for x, z, _ in pts:
        cmd += [str(x), str(z)]
    try:
        r = subprocess.run(cmd, capture_output=True, encoding="utf-8",
                           errors="replace", timeout=180)
    except Exception as e:
        print(f"（复核跳过：{e}）")
        return
    got = {}
    for line in r.stdout.splitlines():
        m = re.match(r"\((-?\d+),(-?\d+)\) -> (\S+) / (\S+)", line.strip())
        if m:
            got[(int(m.group(1)), int(m.group(2)))] = (m.group(3), m.group(4))
    same, diff = 0, []
    for x, z, want in pts:
        have = got.get((x, z))
        if have is None:
            continue
        if want in have:                       # 两个高度里有一个对上就算对上
            same += 1
        else:
            diff.append(f"({x},{z}) 记录的是 {want}，算出来是 {have[0]}/{have[1]}")
    extra = f"（另有 {skipped} 个点是下界/末地的，跳过）" if skipped else ""
    print(f"记录的 {len(pts)} 个群系点里，和这个种子对得上 {same} 个"
          + (" ✅" if same == len(pts) else f"（{len(pts) - same} 个对不上）") + extra)
    if diff:
        print("  对不上的（多半是你记录时在别的世界，或者服务器改过世界生成）：")
        for d in diff[:8]:
            print("    " + d)
        if len(diff) > 8:
            print(f"    …还有 {len(diff) - 8} 个")


def require_java():
    """没有 Java 就别继续了，直接说清楚怎么修（返回 True 表示可以继续）"""
    global JAVA, JAVA_CMD
    if JAVA and cfgmod.check_java(JAVA):
        return True
    JAVA = cfgmod.find_java()
    if JAVA:
        JAVA_CMD = [JAVA, "-Dstdout.encoding=UTF-8", "-Dstderr.encoding=UTF-8",
                    "-Dfile.encoding=UTF-8"]
        return True
    print(cfgmod.java_hint())
    print("\n（Java 找好了再重新跑一次就行，配置和存档都不会丢）")
    return False


def step(title):
    print(f"\n{'=' * 58}\n{title}\n{'=' * 58}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("save", nargs="+", help="下载的存档目录（含 region/）—— 可以给好几个，合起来算")
    p.add_argument("--obs", nargs="*", default=[], help="模组写的观测文件（可以给好几个）")
    p.add_argument("--no-hash", action="store_true", help="不带哈希种子（那只给低 48 位）")
    args = p.parse_args()

    args.save = [cfgmod.adapt_path(s) for s in args.save]
    args.obs = [cfgmod.adapt_path(o) for o in (args.obs or [])]
    if not require_java():
        return
    lines = []
    report = []

    # 版本提示：1.12 及以前结构摆放是另一套老算法，本工具只能吃柱子那 16 bit
    _ver = cfgmod.load().get("mc")
    if _ver:
        _f = mcvers.features(_ver)
        print(f"（按 {_ver} 算：" + "、".join([
            "柱子✓" if _f["pillars"] else "柱子✗",
            "结构✓" if _f["struct"] else "结构✗（1.12 及以前是另一套摆放算法）",
            "哈希✓" if _f["hash"] else "哈希✗",
        ]) + "）")
        if not _f["struct"]:
            print("⚠ 这个版本的结构摆放本工具还不会算 —— 只靠柱子那 16 bit 基本解不出来，先别指望。")
        lines.append(f"version={_ver}")

    step("① 从存档里解末地柱子（16 bit）")
    pillars = []          # [(存档名, tops, v), ...]
    for sv in args.save:
        if not os.path.isdir(sv):
            print(f"⚠ 存档目录不存在，跳过：{sv}")
            continue
        pillar_out = java("PillarScan", sv)
        print(f"[{os.path.basename(str(sv).rstrip('/'))}] {pillar_out.strip()}")
        report.append(pillar_out.strip())
        m = re.search(r"end_pillars tops=([\d,]+) v=(\d+)", pillar_out)
        if m:
            pillars.append((sv, m.group(1), m.group(2)))
    if not pillars:
        print("\n没解出柱子 -> 先把末地中央岛也下载一份（x/z 在 ±60 以内那一圈）")
        print("没有柱子就只有 16 bit 的缺口，基本解不出来。")
        return
    vs = {v for _, _, v in pillars}
    if len(vs) > 1:
        print(f"⚠ 几份存档解出来的柱子不一致（{sorted(vs)}）—— 可能不是同一个世界，或者有一份没下全；先用第一份的")
    lines.append(f"end_pillars tops={pillars[0][1]} v={pillars[0][2]}")
    if len(pillars) > 1:
        print(f"（{len(pillars)} 份存档都解出了柱子，用的是第一份那份；其余几份的柱子也一致）")

    step("② 扫存档里的结构标志方块（每条 3~8 bit）")
    hints = set()
    for sv in args.save:
        if not os.path.isdir(sv):
            continue
        struct_out = subprocess.run(JAVA_CMD + ["-cp", OUT, "RegionScan", sv],
                                    capture_output=True, encoding="utf-8", errors="replace").stdout
        print(struct_out.strip())
        report.append(struct_out.strip())
        for line in struct_out.splitlines():
            mm = re.match(r"\[[高低]\]\s+(\S+)\s+(\S+)\s+区块 \d+ 个，中心 \((-?\d+),(-?\d+)\) 半径 (\d+)", line.strip())
            if mm and line.strip().startswith("[高]"):
                hints.add(f"struct:{mm.group(1)}:{mm.group(3)},{mm.group(4)},{mm.group(5)}")
    for h in sorted(hints):
        lines.append(h)
    print(f"\n高置信度结构提示 {len(hints)} 条（多份存档合并去重）")

    step("③ 模组的观测数据（史莱姆区块 + 哈希种子 + 群系采样）")
    # 观测文件是"追加"写的，可以喂好几份；同一个区块出现多次就取最大的那个计数
    slime = {}            # "cx,cz" -> 次数
    hashes = {}           # 哈希种子 -> 出现次数
    biomes = []           # ["x,z=minecraft:xxx", ...]  留到最后当"复核轮"用
    for path in args.obs:
        if not os.path.exists(path):
            print(f"⚠ 找不到观测文件：{path}")
            print("  （模组会在 .minecraft\\versions\\<版本>\\seedhelper-observations.txt 写它）")
            continue
        print(f"[{os.path.basename(str(path))}] ", end="")
        n_file = 0
        for raw in open(path, encoding="utf-8"):
            t = raw.strip()
            if t.startswith("hashed_seed="):
                h = t.split("=", 1)[1].strip()
                hashes[h] = hashes.get(h, 0) + 1
            elif t.startswith("slime:"):
                head = t[6:].split()[0]
                cnt = 1
                mm = re.search(r"count=(\d+)", t)
                if mm:
                    cnt = int(mm.group(1))
                slime[head] = max(slime.get(head, 0), cnt)
                n_file += 1
            elif t.startswith("biome:"):
                biomes.append(t[6:].strip())
        print(f"史莱姆行 {n_file} 条，群系采样 {sum(1 for b in biomes) if path == args.obs[-1] else 0} 条")
    if hashes and not args.no_hash:
        best_hash = max(hashes, key=lambda k: hashes[k])
        if len(hashes) > 1:
            print(f"⚠ 观测文件里有 {len(hashes)} 个不同的哈希种子 —— 可能掺了别的世界的记录；"
                  f"用出现最多的那个（{best_hash}）")
        lines.append(f"hashed_seed={best_hash}")
        print(f"拿到哈希种子：hashed_seed={best_hash}（{hashes[best_hash]} 次会话都一致）")
    for key in sorted(slime):
        lines.append(f"slime:{key} count={slime[key]}")
    usable = sum(1 for k, v in slime.items() if v >= 2)
    if slime:
        print(f"史莱姆区块 {len(slime)} 个（其中 {usable} 个看到过 2 次以上，≥2 的才算数）")
    if biomes:
        print(f"另外还有 {len(biomes)} 个群系采样点 —— 最后会拿它们复核一遍种子")
    if not slime and not hashes:
        print("观测文件里没有 hashed_seed / slime 行 —— 检查一下模组是不是没开记录")
    if not args.obs:
        print("没有用模组观测文件 -> 最多只能给到低 48 位")

    tmp = os.path.join(ROOT, "记录", ".seedcalc-obs.txt")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")

    step("④ 开始破解（枚举 2^32 个低 48 位候选）")
    # 把版本传进去：结构摆放参数按版本挑（1.17 及以前村庄是 32 格网格）
    ver = os.environ.get("MCVER") or (cfgmod.load().get("mc") or "")
    out = run_with_progress(JAVA_CMD + ["-cp", OUT, "SeedCracker", "file", tmp],
                            extra_env={"MCVER": str(ver)} if ver else None)
    print(out.strip())
    report.append(out.strip())

    step("结论")
    seeds = re.findall(r"^\s+(-?\d+)\s+\(0x[0-9A-Fa-f]{16}\)", out, re.M)
    if seeds:
        cfgmod.set_seed(seeds[0])
        print("完整种子：")
        for s in seeds:
            print("  " + s)
        print(f"\n已写入本地配置 {cfgmod.CONFIG_PATH} —— 结构计算器（tool.py 选 2）可以直接用了")
        if biomes:
            step("⑤ 复核一轮：拿你记录过的群系采样点验证这个种子")
            verify_biomes(seeds[0], biomes)
    elif "低 48 位候选" in out:
        print("只解出低 48 位（找结构够用）。想要完整 64 位种子：")
        print("  重新用模组跑一次游戏（它会抓客户端的哈希种子），然后 --obs 指到 seedhelper-observations.txt")
        lows = re.findall(r"种子低48位 = (-?\d+)", out)
        if len(lows) == 1:
            print(f"\n  懒人办法：现在就在主菜单 3【设置】里把种子填成 {lows[0]}")
            print("  （结构位置是对的 —— 结构摆放只吃低 48 位；但群系/地形会不准）")
        elif lows:
            print(f"\n  低 48 位候选有 {len(lows)} 个，结构位置没法唯一确定；建议再补几个观测重新算。")
    else:
        print("没解出来。常见原因：")
        print("  1. 服务器改过世界生成（柱子和结构都对不上）")
        print("  2. 结构提示不够（多下载几个海底神殿/试炼密室/远古城市）")
        print("  3. 末地柱子没下全")

    with open(LOG, "a", encoding="utf-8") as fh:
        saves = "  ".join(str(s) for s in args.save)
        fh.write(f"\n===== {datetime.datetime.now():%Y-%m-%d %H:%M:%S}  {saves} =====\n")
        fh.write("\n".join(report) + "\n")
    print(f"\n全过程记录已存到 {LOG}")


if __name__ == "__main__":
    main()
