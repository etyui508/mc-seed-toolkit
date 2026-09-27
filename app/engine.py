#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""引擎层：调用 out/findstruct 和 Java 工具、解析结果、写记录。

结构模块（structures/）都从这里拿数据，自己只管"问用户什么"和"怎么显示"。
"""
import contextlib
import datetime
import io
import json
import math
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import config as cfgmod
import diag
import state
import ui

OUT = os.path.join(ROOT, "out")
LOG_FILE = os.path.join(ROOT, "记录", "坐标记录.txt")
RESULTS_FILE = os.path.join(ROOT, "记录", "结果.jsonl")     # 一行一条，导出功能读它

DIM_NAMES = {"overworld": "主世界", "nether": "下界", "end": "末地"}
DIM_IDS = {"overworld": 0, "nether": -1, "end": 1}

TIER_MAIN = {"海底神殿", "远古城市", "试炼密室", "林地府邸", "要塞（末地门）", "末地城", "村庄",
             "掠夺者前哨", "沙漠神殿", "丛林神殿", "女巫小屋", "雪原小屋", "古迹废墟",
             "下界要塞", "堡垒遗迹"}
TIER_MINOR = {"沉船", "废弃传送门", "海底遗迹", "埋藏的宝藏", "沙漠水井",
              "废弃传送门(下界)", "末地折跃门", "末地小岛"}
NOISY = {"废弃矿井", "紫水晶洞"}
PARALLEL_SCAN_MIN_CHUNKS = 1000

# 解析引擎输出用的（并行扫描合并那步要用）
_HEADER_RE = re.compile(r"^\[([^\]]+)\]\s*([^:：（]+)[：:]\s*(\d+) 个过了群系检查")
_ROW_RE = re.compile(r"^\s+区块 \((-?\d+),(-?\d+)\)\s+方块 \((-?\d+),(-?\d+)\)"
                     r"\s+距中心 (\d+) 格\s*(.*)$")

# 下界结构：坐标要 ÷8 换算
NETHER_NAMES = ("下界要塞", "堡垒遗迹", "废弃传送门(下界)")
def _findstruct_path():
    """按平台挑 cubiomes 工具：Windows 用 findstruct.exe，Linux/WSL 用 findstruct"""
    order = ["findstruct.exe", "findstruct"] if os.name == "nt" else ["findstruct", "findstruct.exe"]
    for name in order:
        cand = os.path.join(OUT, name)
        if os.path.exists(cand):
            return cand
    return os.path.join(OUT, order[0])

def _has_cubiomes():
    """cubiomes 版找结构工具能用吗？（真跑一下确认，Windows 用 .exe）"""
    path = FINDSTRUCT
    if not os.path.exists(path):
        return False
    if os.name != "nt" and not os.access(path, os.X_OK):
        try:
            os.chmod(path, 0o755)             # 解压后可能丢了执行位
        except Exception:
            return False
    try:
        subprocess.run([path], capture_output=True, timeout=15)
        return True                            # 能启动就算可用（无参数会打印用法）
    except Exception:
        return False


FINDSTRUCT = _findstruct_path()
SLIMEFIND = os.path.join(OUT, "SlimeFind")
JAVA = cfgmod.find_java() or "java"
JAVA_CMD = [JAVA, "-Dstdout.encoding=UTF-8", "-Dstderr.encoding=UTF-8",
            "-Dfile.encoding=UTF-8"]
HAS_CUBIOMES = _has_cubiomes()

def run(cmd, quiet=False):
    try:
        r = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")
    except FileNotFoundError:
        if not quiet:
            print(f"没找到 {cmd[0]}。")
            if cmd[0] == JAVA:
                print(cfgmod.java_hint())
        return ""
    except OSError as e:            # 不能执行（Windows 上跑 Linux 版 java / findstruct 就是这里）
        if not quiet:
            print(f"执行失败: {cmd[0]} -> {e}")
            if cmd[0] == JAVA:
                print(cfgmod.java_hint())
        return ""
    if r.returncode != 0 and not quiet:
        print(r.stderr.strip() or r.stdout.strip())
    return r.stdout

def blocks_to_chunks(x, z):
    return math.floor(x / 16), math.floor(z / 16)

def run_and_log(func, args, label):
    """跑一个功能，同时把结果打到屏幕 + 追加到日志文件"""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        func(args)
    text = buf.getvalue()
    if not state.SHOW_SEED and state.SEED is not None:
        text = text.replace(str(state.SEED), cfgmod.mask(state.SEED, False))
    print(_pretty(text), end="")
    log_result(label, text)
    print(ui.info(f"结果已存到 记录/{os.path.basename(LOG_FILE)}"))
    # 诊断日志：记"跑了哪个查询、出来多少行"就够了，具体坐标在 坐标记录.txt 里
    diag.log("查询", 功能=label, 输出行数=len(text.splitlines()))


def log_result(label, text):
    """把结果写进 坐标记录.txt（人看）和 结果.jsonl（导出功能读）"""
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(f"\n===== {datetime.datetime.now():%Y-%m-%d %H:%M:%S}  {label} =====\n")
            fh.write(text if text.endswith("\n") else text + "\n")
    except Exception as e:
        diag.error("写结果记录失败", exc=e, 目标=LOG_FILE)
        print(ui.warn(f"写日志失败: {e}"))
    _append_result(label, text)


def _append_result(label, text):
    """另存一份机器可读的（一行一条 JSON）—— 导出/复制功能读它，不用回头解析文本"""
    try:
        os.makedirs(os.path.dirname(RESULTS_FILE), exist_ok=True)
        with open(RESULTS_FILE, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                 "label": label, "text": text}, ensure_ascii=False) + "\n")
    except Exception:
        pass

def _pretty(text):
    """给引擎吐出来的纯文本加点颜色：标题行、★、群系名（写进日志的仍是纯文本）"""
    raw = str(text)
    out = []
    for line in raw.splitlines():
        stripped = line.strip()
        m = re.match(r"^(\s*\[[^\]]+\])", line)
        if m:
            line = ui.s(m.group(1), "accent") + line[m.end():]
        elif stripped.startswith("【") and "】" in stripped:
            line = re.sub(r"【([^】]+)】", lambda mm: "【" + ui.s(mm.group(1), "accent") + "】", line)
        elif stripped.startswith("（") and stripped.endswith("）"):
            line = ui.s(line, "warn")
        if "★" in line:
            line = line.replace("★", ui.star())
        line = re.sub(r"(goto -?\d+ -?\d+)", lambda mm: ui.s(mm.group(1), "key"), line)
        line = re.sub(r"(群系 [A-Za-z_]+)", lambda mm: ui.s(mm.group(1), "dim"), line)
        out.append(line)
    return "\n".join(out) + ("\n" if raw.endswith("\n") else "")

def parse_struct_output(text):
    """把 findstruct 的输出解析成 {名称: [(x, z, dist), ...]}"""
    result = {}
    name = None
    for line in text.splitlines():
        m = re.match(r"\[([^\]]+)\]\s*([^:：（]+)", line)
        if m:
            name = m.group(2).strip()      # group1 是维度，group2 才是结构名
            result.setdefault(name, [])
            continue
        m = re.match(r"\s+区块 \((-?\d+),(-?\d+)\)\s+方块 \((-?\d+),(-?\d+)\).*?距中心 (\d+)", line)
        if m and name:
            result[name].append((int(m.group(3)), int(m.group(4)), int(m.group(5))))
    return result

def parse_full(text):
    """解析成 [(维度, 名称, 方块x, 方块z, 距离, 备注), ...]"""
    out = []
    dim = name = None
    for line in text.splitlines():
        m = re.match(r"\[([^\]]+)\]\s*([^:：（]+)", line)
        if m:
            dim, name = m.group(1).strip(), m.group(2).strip()
            continue
        m = re.match(r"\s+区块 \((-?\d+),(-?\d+)\)\s+方块 \((-?\d+),(-?\d+)\)\s+距中心 (\d+) 格\s*(.*)", line)
        if m and name:
            out.append((dim, name, int(m.group(3)), int(m.group(4)), int(m.group(5)), m.group(6).strip()))
    return out

def _scan_jobs():
    """开几个进程并行扫。可以用环境变量 MC_SCAN_JOBS 覆盖。"""
    try:
        n = int(os.environ.get("MC_SCAN_JOBS", "0"))
        if n > 0:
            return max(1, min(n, 32))
    except ValueError:
        pass
    return max(1, min(8, os.cpu_count() or 1))

def _run_find_parallel(cx, cz, chunks_radius, top, min_dist, max_dist, nobiome=False):
    """把要扫的方块切成几条**竖条**，每条一个子进程（findrect），再按原来的顺序拼起来。

    距离和距离窗口都由每条自己按"中心区块"算，所以结果和"一个进程扫整片"一样
    （每种结构的最近 top 个一定都在里面）。任何一条出错就返回 None，调用方退回单进程。
    """
    jobs = _scan_jobs()
    jobs = min(jobs, max(1, chunks_radius // 300))
    if jobs < 2:
        return None
    x0, x1 = cx - chunks_radius, cx + chunks_radius
    z0, z1 = cz - chunks_radius, cz + chunks_radius
    width = x1 - x0 + 1
    procs = []
    try:
        # 注意：不能让子进程往管道里写 —— 每条带的输出可能有几 MB，管道只有 64KB，
        # 谁先被读完，其他几条就会卡在写管道上（等于把并行又变回串行）。
        # 所以每个子进程直接写自己的临时文件，跑完再读。
        with tempfile.TemporaryDirectory(prefix="mc-scan-") as tmp:
            for i in range(jobs):
                bx0 = x0 + width * i // jobs
                bx1 = x0 + width * (i + 1) // jobs - 1
                if bx1 < bx0:
                    continue
                out_path = os.path.join(tmp, f"band{i}.txt")
                err_path = out_path + ".err"
                out_fh = open(out_path, "wb")
                err_fh = open(err_path, "wb")
                p = subprocess.Popen(
                    [FINDSTRUCT, "findrect", str(state.SEED), str(bx0), str(z0), str(bx1), str(z1),
                     str(cx), str(cz), str(chunks_radius), str(top), str(min_dist), str(max_dist),
                     "1" if nobiome else "0"],
                    stdout=out_fh, stderr=err_fh)
                procs.append((p, out_fh, err_fh, out_path, err_path))
            if len(procs) < 2:
                return None
            parts = []
            for p, out_fh, err_fh, out_path, err_path in procs:
                p.wait(timeout=1800)
                out_fh.close()
                err_fh.close()
                if p.returncode != 0:
                    with open(err_path, encoding="utf-8", errors="replace") as f:
                        raise RuntimeError(f"findrect 退出码 {p.returncode}: {f.read()[:120]}")
                with open(out_path, encoding="utf-8", errors="replace") as f:
                    parts.append(f.read())
            merged = _merge_findrect(parts, top)
            return merged or None
    except Exception:
        for p, *_rest in procs:
            if p.poll() is None:
                p.kill()
        return None

def _merge_findrect(parts, top):
    """把几条带的输出合成一份"和单进程 find 等价"的输出：
       · 同一种结构的"一共 N 个"把各带相加（每条只报自己那片的数）
       · 行按距离合并，只留最近 top 条（和单进程一样，不然会多出好几倍）"""
    counts, rows, order = {}, {}, []
    for text in parts:
        dim = name = None
        for line in text.splitlines():
            m = _HEADER_RE.match(line)
            if m:
                dim, name, n = m.group(1), m.group(2), int(m.group(3))
                key = (dim, name)
                if key not in counts:
                    order.append(key)
                    counts[key] = 0
                counts[key] += n
                continue
            m = _ROW_RE.match(line)
            if m and dim:
                rows.setdefault((dim, name), []).append((int(m.group(5)), line))
    if not order:
        return ""
    out = []
    for key in order:
        found = counts.get(key, 0)
        items = sorted(rows.get(key, []), key=lambda t: t[0])[:top]
        out.append("")
        out.append(f"[{key[0]}] {key[1]}：{found} 个过了群系检查")
        out.extend(line for _, line in items)
        if found > len(items):
            out.append(f"  …还有 {found - len(items)} 个")
    return "\n".join(out) + "\n"

def run_find(center_x, center_z, radius, top, min_dist=0, max_dist=0, nobiome=False):
    cx, cz = blocks_to_chunks(center_x, center_z)
    chunks_radius = max(1, radius // 16)
    # 扫得大的时候拆成几条竖条、开多个子进程并行扫（引擎支持 findrect）
    # top 大、又要群系的那种（比如"附近结构总览"）不并行：行数会翻好几倍，每行都要算群系
    if HAS_CUBIOMES and chunks_radius >= PARALLEL_SCAN_MIN_CHUNKS and (nobiome or top <= 64):
        with ui.spinner(f"正在扫 {chunks_radius * 16} 格内的结构（并行）"):
            merged = _run_find_parallel(cx, cz, chunks_radius, top, min_dist, max_dist, nobiome)
        if merged:
            return parse_struct_output(merged), merged
        if nobiome:
            nobiome = False      # 并行失败就退回"一个进程扫整片"（那个必然带群系）
    def java_fallback(reason):
        print(f"（{reason}，改用纯 Java 版列候选位置；少了群系检查，位置偶尔会偏）")
        out = run(JAVA_CMD + ["-cp", OUT, "FindStructures", str(state.SEED), str(cx), str(cz),
                              str(chunks_radius)])
        if not out.strip():
            if not cfgmod.check_java(JAVA):
                print()
                print(cfgmod.java_hint())
            else:
                print("\n跑 Java 工具没输出 —— Java 在，但这次它没给出结果（存档/版本对不上也会这样）。")
                print(f"当前用的 Java：{JAVA}")
                print("不行就去主菜单 3【设置】里换一个 Java 路径试试。")
        hits = parse_struct_output(out)
        if min_dist or max_dist:
            # 这个老工具的 t[2] 是"区块距离"，乘 16 换成方块（近似，只能这么筛）
            hits = {k: [t for t in v
                        if t[2] * 16 >= min_dist and (not max_dist or t[2] * 16 <= max_dist)]
                    for k, v in hits.items()}
        return hits, out

    if not HAS_CUBIOMES:
        why = "没找到能用的 findstruct（cubiomes 工具）"
        return java_fallback(why)
    with ui.spinner(f"正在扫 {chunks_radius * 16} 格内的结构"):
        out = run([FINDSTRUCT, "find", str(state.SEED), str(cx), str(cz), str(chunks_radius),
                   str(top), str(min_dist), str(max_dist)])
    if not out.strip():
        return java_fallback("cubiomes 版跑不起来")
    return parse_struct_output(out), out

def load_gateways():
    """末地折跃门落点（缓存到文件，第一次算比较慢）"""
    cache = gateway_cache_path()
    if os.path.exists(cache):
        pts = []
        # 显式 utf-8：Windows 上不写的话会按 GBK 读，容易炸
        with open(cache, encoding="utf-8") as fh:
            for line in fh:
                a = line.split()
                if len(a) == 2:
                    try:
                        pts.append((int(a[0]), int(a[1])))
                    except ValueError:
                        pass                      # 缓存文件坏了一行，忽略就行
        if pts:
            return pts
    print("第一次算折跃门落点，稍等（约 20 秒）…")
    out = run([FINDSTRUCT, "find", str(state.SEED), "0", "0", "2100", "3000", "0"])
    pts, name = [], None
    for line in out.splitlines():
        if line.startswith("["):
            name = line
            continue
        m = re.match(r"\s+区块 \((-?\d+),(-?\d+)\)\s+方块 \((-?\d+),(-?\d+)\)", line)
        if m and name and "折跃门" in name:
            pts.append((int(m.group(3)), int(m.group(4))))
    with open(cache, "w", encoding="utf-8") as fh:
        for x, z in pts:
            fh.write(f"{x} {z}\n")
    print(f"  折跃门落点 {len(pts)} 个，已缓存")
    return pts

def gateway_dist(x, z, gateways):
    return min(math.hypot(x - gx, z - gz) for gx, gz in gateways)

def window_text(min_dist, max_dist):
    """把距离窗口说成人话（都没设就返回空串）"""
    if min_dist and max_dist:
        return f"只要 {min_dist} ~ {max_dist} 格之间的"
    if min_dist:
        return f"只要 {min_dist} 格以外的（远的）"
    if max_dist:
        return f"只要 {max_dist} 格以内的"
    return ""

def fit_radius(radius, min_dist, max_dist):
    """距离窗口比搜索半径还大 -> 一定什么也查不到，自动把半径放大到够用"""
    want = 0
    if max_dist:
        want = max(want, max_dist)
    if min_dist:
        want = max(want, int(min_dist * 1.5))
    if want > radius:
        print(f"（搜索半径 {radius} 格比距离窗口还小，自动放大到 {want} 格）")
        return want
    return radius

def print_hits(title, hits, extra=None, limit=12):
    if not hits:
        print(f"{title}：这个范围里没有")
        return
    print(f"\n{title}（{len(hits)} 个）")
    for i, item in enumerate(hits[:limit], 1):
        x, z, d = item[0], item[1], item[2]
        note = (extra(item) if extra else "") or ""
        print(f"  {i}. goto {x} {z}   距中心 {d} 格" + (f"   {note}" if note else ""))
    if len(hits) > limit:
        print(f"  …还有 {len(hits) - limit} 个")

def is_nether_name(name):
    return bool(name) and any(n in name for n in NETHER_NAMES)

def overworld_to_nether(x, z):
    return x // 8, z // 8

def gateway_cache_path():
    return cfgmod.gateway_cache(state.SEED)



# calc.py 那边用这个名字
pretty = _pretty
