#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
末地船预测（不用下载存档，光靠种子算）

原理：末地船是末地城生成时按固定规则摆出来的，规则在游戏本体的
`EndCityPieces`（intermediary 名字 class_3342）里：

  · 随机数 = WorldgenRandom.setLargeFeatureSeed(世界种子, 城市所在区块x, 城市所在区块z)
  · 先抽 1 次 nextInt(4) 决定整座城的朝向（船也跟着转）
  · 然后跑完整座城的布局；每到一个"桥"，如果这条城还没摆过船，就掷
    nextInt(10 - 深度) == 0，中了就把船摆在桥末端再往 (-8..-1, -70..-61) 的方向

我们不是"总结规律"，而是把游戏本体的这段代码直接调用一遍
（tools/ShipFinder.java，编译好的 class 在 out/），所以结果和游戏完全一致。
另外 tools/endcity.c 是同一套逻辑的纯复刻（不用装游戏、不挑版本），两边对拍过
2400 个城的每一段都一模一样；拿真实存档交叉验证时，扫到的龙头 / 宝箱和算出来的也逐格一致。

（下面这条路要本机装过 Minecraft + Fabric，能拿到
  versions/<版本>/.fabric/remappedJars/.../client-intermediary.jar 和启动器库
—— 平时用不着，包里的 out/findstruct 就能算）
"""
import glob
import json
import os
import re
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))          # app/ 目录
ROOT = os.path.dirname(HERE)                               # 工具包根目录
sys.path.insert(0, HERE)
import config as cfgmod

OUT = os.path.join(ROOT, "out")
SIZES = os.path.join(ROOT, "tools", "endcity-sizes.txt")
JAVA_FLAGS = ["-Dstdout.encoding=UTF-8", "-Dstderr.encoding=UTF-8", "-Dfile.encoding=UTF-8"]

# 已经编译好的预测器：目录名 -> 需要的最低 Java 版本
#   1.21.10 那套是对着 Fabric 的 client-intermediary.jar 编的（intermediary 类名）
#   26.3 那套是对着官方未混淆的客户端 jar 编的（net.minecraft.* 官方类名，26.x 起 Mojang 不再混淆）
VARIANTS = [
    ("1.21.10", "17"),
    ("26.3", "25"),
]


def variant_for(mcver):
    """按版本挑编译好的预测器目录；没有就返回 None"""
    if not mcver:
        return None
    v = str(mcver)
    for tag, java_min in VARIANTS:
        if v == tag or v.startswith(tag + ".") or v.startswith(tag):
            d = OUT if tag == "1.21.10" else os.path.join(OUT, tag)
            if os.path.exists(os.path.join(d, "ShipFinder.class")):
                return d, tag, int(java_min)
    # 26.x 的其它小版本（26.1 / 26.2 …）用 26.3 那套
    p = re.match(r"^(\d+)\.", v)
    if p and int(p.group(1)) >= 26:
        d = os.path.join(OUT, "26.3")
        if os.path.exists(os.path.join(d, "ShipFinder.class")):
            return d, "26.3", 25
    return None


def _findstruct_path():
    order = ["findstruct.exe", "findstruct"] if os.name == "nt" else ["findstruct", "findstruct.exe"]
    for name in order:
        cand = os.path.join(OUT, name)
        if os.path.exists(cand):
            return cand
    return os.path.join(OUT, order[0])


# ---------------------------------------------------------------- 游戏本体 classpath
def _version_dirs():
    """所有能用的版本目录：装了 Fabric 的（有 client-intermediary.jar）
       或者官方未混淆的客户端 jar（26.x 起）"""
    found = []
    for mc in cfgmod._minecraft_dirs():
        for vdir in sorted(glob.glob(os.path.join(mc, "versions", "*"))):
            jars = glob.glob(os.path.join(vdir, ".fabric", "remappedJars", "*",
                                          "client-intermediary.jar"))
            if jars:
                found.append((mc, vdir, jars[0], "fabric"))
                continue
            name = os.path.basename(vdir)
            cand = os.path.join(vdir, name + ".jar")
            if os.path.exists(cand) and os.path.getsize(cand) > 5_000_000:
                found.append((mc, vdir, cand, "official"))
    return found


def _libs_for(mc, vdir):
    libs = []
    for jf in sorted(glob.glob(os.path.join(vdir, "*.json"))):
        try:
            data = json.load(open(jf, encoding="utf-8-sig"))
        except Exception:
            continue
        if not data.get("libraries"):
            continue
        for lib in data["libraries"]:
            art = (lib.get("downloads") or {}).get("artifact")
            if not art or "natives" in (lib.get("name") or ""):
                continue
            p = os.path.join(mc, "libraries", art["path"].replace("/", os.sep))
            if os.path.exists(p):
                libs.append(p)
        break
    return libs


def game_classpath(mcver=None, want=None):
    """拼出"游戏本体 + 启动器库"的 classpath；找不到返回 (None, 原因)
       want: "fabric" / "official"；None = 随便（优先 fabric）"""
    cands = _version_dirs()
    if not cands:
        return None, "没找到装了 Fabric（或官方未混淆客户端）的游戏目录"
    # 优先挑版本号对得上的
    pick = None
    if mcver:
        for mc, vdir, jar, kind in cands:
            if str(mcver) in os.path.basename(vdir):
                pick = (mc, vdir, jar, kind)
                break
    if pick is None:
        pick = next((c for c in cands if c[3] == "fabric"), cands[0])
    mc, vdir, jar, kind = pick
    if want and kind != want:
        return None, (f"这个版本只有 {kind} 形式的游戏本体，"
                      f"但预测器需要 {want}（{os.path.basename(vdir)}）")
    jar_tag = os.path.basename(os.path.dirname(jar))     # 例如 minecraft-1.21.10-0.19.3
    if mcver and kind == "fabric" and str(mcver) not in jar_tag:
        return None, (f"游戏版本对不上：只有 {jar_tag} 这一版，"
                      f"末地船预测目前只编译了 1.21.10 和 26.3")
    libs = _libs_for(mc, vdir)
    if not libs:
        return None, "游戏版本 JSON 里没读到启动器库（libraries）"
    return os.pathsep.join([jar] + libs), None


def find_java_for(min_major):
    """找一个版本够新的 Java：26.x 的类要用 Java 25 才能加载，
       包里自带的 21 跑不了，得去启动器自带的运行时里翻。"""
    java = cfgmod.find_java()
    if java and (cfgmod.check_java(java) or 0) >= min_major:
        return java
    best = None
    for mc in cfgmod._minecraft_dirs():
        for pat in ("runtime/*/bin/java", "runtime/*/bin/java.exe",
                    "runtime/*/*/bin/java", "runtime/*/*/bin/java.exe"):
            for c in glob.glob(os.path.join(mc, pat)):
                major = cfgmod.check_java(c)
                if major and major >= min_major:
                    return c
    return best or java


def available():
    """这个功能现在能不能用？（Java + 游戏本体 + 拿来算基点高度的引擎）"""
    # ① 包里自带的引擎：自己复刻的末地城生成器，不用游戏、不用存档、不看版本
    if os.path.exists(_findstruct_path()):
        return True, ""
    # ② 退路：跑游戏本体的生成器（要本机装过 Minecraft，且只编了 1.21.10 / 26.3）
    ver = cfgmod.load().get("mc")
    if not variant_for(ver):
        return False, (f"没找到 out/findstruct（包里自带的引擎）；退路要跑游戏本体，"
                       f"而 {ver} 这一版也没编（目前只有 1.21.10 和 26.3）")
    cp, why = game_classpath(ver)
    if not cp:
        return False, "没找到 out/findstruct（包里自带的引擎），" + why
    return True, ""


# ---------------------------------------------------------------- 基点高度（算 y 用）
def base_heights(seed, cities):
    """每座城的基点 y（船/箱子/鞘翅的 y 都是相对它的），返回 {(cx,cz): y}"""
    path = _findstruct_path()
    if not cities or not os.path.exists(path):
        return {}
    args = []
    for cx, cz in cities:
        args += [str(cx), str(cz)]
    try:
        r = subprocess.run([path, "endbase", str(seed)] + args,
                           capture_output=True, encoding="utf-8", errors="replace", timeout=120)
    except Exception:
        return {}
    out = {}
    for line in r.stdout.splitlines():
        a = line.split()
        if a and a[0] == "BASE" and len(a) >= 5:
            out[(int(a[1]), int(a[2]))] = int(a[4])
    return out


# ---------------------------------------------------------------- 主入口
def _parse_city_lines(text):
    """把 CITY/None 那几行解析成结果列表（引擎版和游戏版输出格式一样）"""
    results = []
    for line in text.splitlines():
        if not line.startswith("CITY "):
            continue
        a = line.split()
        if len(a) < 5 or a[3] != "SHIP":
            continue
        kv = {}
        for tok in a[4:]:
            if "=" in tok:
                k, v = tok.split("=", 1)
                kv.setdefault(k, []).append(v)

        def pt(key, idx=0):
            vals = kv.get(key)
            if not vals:
                return None
            return tuple(int(v) for v in vals[idx].split(","))

        results.append({
            "cx": int(a[1]), "cz": int(a[2]),
            "rot": kv.get("rot", ["?"])[0],
            "box": (tuple(int(v) for v in kv["box"][0].replace("..", ",").split(","))
                    if kv.get("box") else None),
            "goto": pt("goto"),
            "head": pt("head"),
            "elytra": pt("elytra"),
            "chest1": pt("chest", 0),
            "chest2": pt("chest", 1),
            "pieces": int(kv.get("pieces", ["0"])[0]),
        })
    return results


ROT_INDEX = {"0": 0, "1": 1, "2": 2, "3": 3,
             "NONE": 0, "CLOCKWISE_90": 1, "CLOCKWISE_180": 2, "COUNTERCLOCKWISE_90": 3}


def _default_jobs():
    """开几个子进程并行算。可以用环境变量 MC_SHIP_JOBS 覆盖。"""
    try:
        n = int(os.environ.get("MC_SHIP_JOBS", "0"))
        if n > 0:
            return max(1, min(n, 64))
    except ValueError:
        pass
    return max(1, min(8, os.cpu_count() or 1))


def _split_chunks(seq, jobs):
    """连续切片（不是轮流取），这样把各进程的输出拼起来还是原来的顺序"""
    n = len(seq)
    k, m = divmod(n, jobs)
    out, start = [], 0
    for i in range(jobs):
        size = k + (1 if i < m else 0)
        if size:
            out.append(seq[start:start + size])
        start += size
    return out


def _ship_cmd(path, seed, cities):
    cmd = [path, "ship", str(int(seed))]
    for cx, cz in cities:
        cmd += [str(int(cx)), str(int(cz))]
    return cmd


def engine_predict(seed, cities, timeout=300, jobs=None):
    """用包里自带的 findstruct ship 算（我们复刻的生成器：不用游戏、不用存档、不看版本）

    城市多的时候会拆成几份、开几个**子进程并行**跑（一路一个进程，结果按原顺序拼回来）。
    返回 (结果列表, 错误原因)；引擎不在就返回 (None, 原因) 让调用方走退路。
    """
    path = _findstruct_path()
    if not os.path.exists(path):
        return None, "没找到 out/findstruct（包里自带的引擎）"
    if os.name != "nt" and not os.access(path, os.X_OK):
        try:
            os.chmod(path, 0o755)
        except Exception:
            pass

    cities = list(cities)
    if jobs is None:
        jobs = _default_jobs()
    # 每个进程别塞太多城市（命令行长度有限）
    jobs = max(jobs, (len(cities) + 19999) // 20000)
    jobs = max(1, min(jobs, len(cities)))
    chunks = _split_chunks(cities, jobs) if jobs > 1 else [cities]

    if len(chunks) == 1:
        try:
            r = subprocess.run(_ship_cmd(path, seed, cities), capture_output=True,
                               encoding="utf-8", errors="replace", timeout=timeout)
        except subprocess.TimeoutExpired:
            return None, "引擎算超时了（城市太多？把半径调小一点）"
        except OSError as e:
            return None, f"引擎跑不起来（{e}）"
        text = (r.stdout or "") + (r.stderr or "")
        if r.returncode != 0 or not text.strip():
            first = next((ln for ln in text.splitlines() if ln.strip()), "")
            return None, "引擎没给出结果" + (f"：{first[:120]}" if first else "")
        return _parse_city_lines(text), None

    procs = []
    deadline = time.time() + timeout
    try:
        # 每个子进程写自己的临时文件（不能走管道：输出一大，先被读完的那条会把
        # 其他几条堵在写管道上，并行就白做了）
        with tempfile.TemporaryDirectory(prefix="mc-ship-") as tmp:
            for i, chunk in enumerate(chunks):
                out_path = os.path.join(tmp, f"part{i}.txt")
                out_fh = open(out_path, "wb")
                p = subprocess.Popen(_ship_cmd(path, seed, chunk),
                                     stdout=out_fh, stderr=subprocess.STDOUT)
                procs.append((p, out_fh, out_path))
            parts = []
            for p, out_fh, out_path in procs:
                remain = max(1.0, deadline - time.time())
                p.wait(timeout=remain)
                out_fh.close()
                if p.returncode != 0:
                    raise OSError(f"子进程退出码 {p.returncode}")
                with open(out_path, encoding="utf-8", errors="replace") as f:
                    parts.append(f.read())
            text = "".join(parts)
    except subprocess.TimeoutExpired:
        for p, *_rest in procs:
            if p.poll() is None:
                p.kill()
        return None, "引擎算超时了（城市太多？把半径调小一点）"
    except OSError as e:
        for p, *_rest in procs:
            if p.poll() is None:
                p.kill()
        return None, f"引擎跑不起来（{e}）"
    if not text.strip():
        return None, "引擎没给出结果"
    return _parse_city_lines(text), None


def predict(seed, cities, mcver=None, java=None, timeout=900):
    """给一批城市区块，返回 (结果列表, 错误原因)
    结果里每条：{cx, cz, rot, box, goto, head, elytra, chest1, chest2}
    坐标是世界坐标的 x/z；y 是按"基点 64"算的，要真实 y 得再加 (基点y - 64)
    """
    if not cities:
        return [], None
    # ① 优先用包里自带的引擎：不用装游戏、不挑版本、还快
    ships, why = engine_predict(seed, cities)
    if ships is not None:
        return ships, None
    # ② 引擎不在（或者坏了）才退回"跑游戏本体那套"
    vd = variant_for(mcver)
    if not vd:
        return [], f"{why}；退路（跑游戏本体）也没编 {mcver} 这一版（目前只有 1.21.10 和 26.3）"
    classdir, tag, java_min = vd
    java = java or find_java_for(java_min)
    if not java:
        return [], "没有能用的 Java"
    major = cfgmod.check_java(java) or 0
    if major < java_min:
        return [], (f"{tag} 这版预测器要 Java {java_min}+（现在这个是 Java {major}）—— "
                    f"装过 26.x 的话启动器里会自带 Java 25，路径在 .minecraft\\runtime\\ 下面")
    cp, why = game_classpath(mcver, want=("fabric" if tag == "1.21.10" else "official"))
    if not cp:
        return [], why
    cp = classdir + os.pathsep + cp

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as fh:
        for cx, cz in cities:
            fh.write(f"{cx} {cz}\n")
        listfile = fh.name
    try:
        cmd = [java] + JAVA_FLAGS + ["-cp", cp, "ShipFinder",
                                     str(int(seed)), SIZES, "@" + listfile]
        r = subprocess.run(cmd, capture_output=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
        text = (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return [], "算超时了（城市太多？把半径调小一点）"
    finally:
        try:
            os.remove(listfile)
        except Exception:
            pass

    results = []
    for line in text.splitlines():
        if not line.startswith("CITY "):
            continue
        a = line.split()
        if len(a) < 5 or a[3] != "SHIP":
            continue
        kv = {}
        for tok in a[4:]:
            if "=" in tok:
                k, v = tok.split("=", 1)
                kv.setdefault(k, []).append(v)

        def pt(key, idx=0):
            vals = kv.get(key)
            if not vals:
                return None
            return tuple(int(v) for v in vals[idx].split(","))

        results.append({
            "cx": int(a[1]), "cz": int(a[2]),
            "rot": kv.get("rot", ["?"])[0],
            "box": (tuple(int(v) for v in kv["box"][0].replace("..", ",").split(","))
                    if kv.get("box") else None),
            "goto": pt("goto"),
            "head": pt("head"),
            "elytra": pt("elytra"),
            "chest1": pt("chest", 0),
            "chest2": pt("chest", 1),
            "pieces": int(kv.get("pieces", ["0"])[0]),
        })
    if not results and ("Exception" in text or "Error" in text):
        for line in text.splitlines():
            if "Exception" in line or "Error" in line:
                return [], line.strip()[:200]
    return results, None


def shift_y(point, base_y):
    """把"基点 64"的坐标换成真实 y"""
    if not point:
        return None
    return (point[0], point[1] - 64 + base_y, point[2])


ROT_CN = {"NONE": "正", "CLOCKWISE_90": "顺时针90", "CLOCKWISE_180": "180",
          "COUNTERCLOCKWISE_90": "逆时针90",
          "0": "正", "1": "顺时针90", "2": "180", "3": "逆时针90", "?": "?"}


if __name__ == "__main__":
    # 自测：python3 shipgen.py <种子> <区块x> <区块z> ...
    seed = sys.argv[1]
    cities = [(int(sys.argv[i]), int(sys.argv[i + 1])) for i in range(2, len(sys.argv) - 1, 2)]
    ok, why = available()
    print("可用:", ok, why)
    ships, err = predict(seed, cities, mcver=cfgmod.load().get("mc"))
    if err:
        print("出错:", err)
    base = base_heights(seed, [(s["cx"], s["cz"]) for s in ships])
    for s in ships:
        by = base.get((s["cx"], s["cz"]), 64)
        print(f'城 ({s["cx"]},{s["cz"]}) 朝向 {ROT_CN.get(s["rot"], s["rot"])}：'
              f' goto {s["goto"][0]} {s["goto"][2]}'
              f'  龙 {shift_y(s["head"], by)}  鞘翅 {shift_y(s["elytra"], by)}'
              f'  箱 {shift_y(s["chest1"], by)} {shift_y(s["chest2"], by)}')
