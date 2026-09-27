#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一配置：种子/版本/存档路径 存在本地文件里，脚本运行时按变量取，
不再把种子写死在代码里（分享脚本、截图都不会漏）。

配置文件： 就在本脚本同目录下的 .mc-tool.json
"""
import glob
import json
import os
import re
import shutil
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))          # app/ 目录（程序本体）
ROOT = os.path.dirname(HERE)                               # 工具包根目录
RECORDS = os.path.join(ROOT, "记录")                        # 运行记录 / 缓存统一放这里
try:                                                        # 写记录前先保证目录在
    os.makedirs(RECORDS, exist_ok=True)
except OSError:
    pass

# 配置文件放根目录（老版本也在根目录，继续原地读）
CONFIG_PATH = os.path.join(ROOT, ".mc-tool.json")
LEGACY_PATH = os.path.join(ROOT, ".tool-config.json")

DEFAULTS = {
    "seed": None,          # 世界种子（整数）
    "mc": None,            # 游戏版本，比如 "1.21.10"
    "save": None,          # 下载器存出来的存档目录
    "obs": "",              # 模组写的观测文件（seedhelper-observations.txt），首次会让你填
    "show_seed": False,    # 界面里要不要显示完整种子
    "java": None,          # java 可执行文件路径（自动找，找不到可以手填）
    "agreed": "",          # 同意过哪一版用户协议（"1:2026-09-27 04:00"）
    "channel": "stable",   # 更新通道：stable（稳定版）/ beta（测试版）
}


# ---------------------------------------------------------------- Java 探测
JAVA_MIN_MAJOR = 17          # 工具是 --release 17 编译的，低于这个跑不起来
_JAVA_CACHE = []             # 本进程里缓存一块儿，别每次都去启动 java


def check_java(path):
    """这个 java 真的能跑吗？能跑返回主版本号（int），不能跑返回 None。

    注意：这里会真的执行一次 `java -version`——光看文件存不存在不够，
    U 盘里的 Linux 版 java 在 Windows 上、32 位 java 在 64 位系统上都是"存在但跑不了"。
    """
    if not path or not os.path.isfile(path):
        return None
    if os.name != "nt" and not os.access(path, os.X_OK):
        try:                       # zip 解压出来常常丢了执行位，补一下
            os.chmod(path, 0o755)
        except Exception:
            return None
    try:
        r = subprocess.run([path, "-version"], capture_output=True, timeout=20)
    except Exception:
        return None
    txt = (r.stdout or b"") + (r.stderr or b"")
    m = re.search(rb'version "(\d+)(?:\.(\d+))?', txt)
    if not m:
        return None
    major = int(m.group(1))
    if major == 1 and m.group(2):          # 老版号 1.8.0_xxx
        major = int(m.group(2))
    return major


def _minecraft_dirs():
    """所有可能装着 Minecraft 的目录（官方启动器 / PCL / 别的启动器的 .minecraft）"""
    appdata = os.environ.get("APPDATA") or os.path.expanduser(r"~\AppData\Roaming")
    found = []

    def add(path):
        if not path:
            return
        path = os.path.abspath(path)
        if os.path.isdir(path) and os.path.basename(path).lower() == ".minecraft" \
                and path not in found:
            found.append(path)

    # ① 常见位置
    add(os.path.join(appdata, ".minecraft"))
    add(os.path.expanduser(r"~\.minecraft"))
    # ② 从配置里记的存档/观测文件往上找（存档一定在 .minecraft\versions\...\saves 下面）
    cfg = load()
    for key in ("save", "obs"):
        p = cfg.get(key)
        if not p:
            continue
        try:
            p = os.path.abspath(str(p))
        except Exception:
            continue
        while len(p) > 3:
            if os.path.basename(p).lower() == ".minecraft":
                add(p)
                break
            p = os.path.dirname(p)
    # ③ 各盘符下一层的 .minecraft（游戏装在 D:\xxx\.minecraft 这种情况）
    if os.name == "nt":
        for drive in "CDEFGHIJ":
            add("%s:\\.minecraft" % drive)
            for p in glob.glob("%s:\\*\\.minecraft" % drive):
                add(p)
    return found


def _add(out, paths):
    for p in paths:
        if not p:
            continue
        p = os.path.normpath(p)
        if p not in out:
            out.append(p)


def _runnable_here(path):
    """这台系统该跑哪种 java：Windows 只认 .exe；Linux/WSL 不碰 .exe
    （WSL 能"执行"Windows 的 java.exe，但它认不了 WSL 里的 /home/... 路径，所以不能选它）"""
    low = path.lower()
    if os.name == "nt":
        return low.endswith(".exe")
    return not low.endswith((".exe", ".bat", ".cmd", ".msi"))


def _windows_candidates():
    """Windows 上的候选：启动器自带的 JVM、PCL/HMCL 记录的 Java、注册表、常见安装目录"""
    out = []
    home = os.path.expanduser("~")
    appdata = os.environ.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
    local = os.environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")

    # ① 启动器自带的 JVM（官方启动器 / PCL 用官方运行库时都在这儿）
    for mc in _minecraft_dirs():
        _add(out, glob.glob(os.path.join(mc, "runtime", "*", "bin", "java.exe")))
        _add(out, glob.glob(os.path.join(mc, "runtime", "*", "*", "bin", "java.exe")))
        # 老版官方启动器在 launcher_profiles.json 里记过 javaDir
        for prof in glob.glob(os.path.join(mc, "launcher_profiles.json")):
            try:
                data = json.load(open(prof, encoding="utf-8-sig"))
            except Exception:
                continue
            for info in (data.get("profiles") or {}).values():
                jd = info.get("javaDir")
                if jd:
                    _add(out, [os.path.join(jd, "java.exe"), os.path.join(jd, "bin", "java.exe")])

    # ② PCL：配置里直接记着 Java 列表
    for cfg_path in glob.glob(os.path.join(appdata, "PCL", "config.json")) + \
                    glob.glob(os.path.join(appdata, "PCL*", "config.json")):
        try:
            data = json.load(open(cfg_path, encoding="utf-8-sig"))
        except Exception:
            continue
        for item in data.get("JavaList") or []:
            folder = item.get("Folder") or item.get("Path") or ""
            if folder:
                _add(out, [os.path.join(folder, "java.exe"),
                           os.path.join(folder, "bin", "java.exe")])

    # ③ HMCL / BakaXL 之类
    for cfg_path in glob.glob(os.path.join(appdata, "HMCL*", "hmcl.json")) + \
                    glob.glob(os.path.join(home, ".hmcl.json")):
        try:
            data = json.load(open(cfg_path, encoding="utf-8-sig"))
        except Exception:
            continue
        jd = data.get("javaDir") or data.get("javaPath") or ""
        if jd:
            jd = jd[:-len("java.exe")] if jd.lower().endswith("java.exe") else jd
            _add(out, [os.path.join(jd, "java.exe"), os.path.join(jd, "bin", "java.exe")])

    # ④ 注册表（JavaSoft）里装的 JRE/JDK
    try:
        import winreg
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for sub in (r"SOFTWARE\JavaSoft\Java Runtime Environment",
                        r"SOFTWARE\JavaSoft\JDK", r"SOFTWARE\JavaSoft\JRE",
                        r"SOFTWARE\WOW6432Node\JavaSoft\Java Runtime Environment"):
                try:
                    with winreg.OpenKey(root, sub) as key:
                        count = winreg.QueryInfoKey(key)[0]
                        for i in range(count):
                            name = winreg.EnumKey(key, i)
                            with winreg.OpenKey(key, name) as ver:
                                jh = winreg.QueryValueEx(ver, "JavaHome")[0]
                            _add(out, [os.path.join(jh, "bin", "java.exe")])
                except OSError:
                    continue
    except Exception:
        pass

    # ⑤ 常见安装目录（各个盘符都扫一遍）
    patterns = [
        r"Program Files\Java\*\bin\java.exe",
        r"Program Files\Eclipse Adoptium\*\bin\java.exe",
        r"Program Files\Zulu\*\bin\java.exe",
        r"Program Files\Microsoft\jdk*\bin\java.exe",
        r"Program Files\BellSoft\*\bin\java.exe",
        r"Program Files\Amazon Corretto\*\bin\java.exe",
        r"Program Files (x86)\Java\*\bin\java.exe",
        r"Program Files\*\*\bin\java.exe",
        r"Java\*\bin\java.exe",
        r"jdk*\bin\java.exe",
        r"jre*\bin\java.exe",
        r"*\jdk*\bin\java.exe",
    ]
    for drive in "CDEFGHIJ":
        root = "%s:\\" % drive
        if not os.path.isdir(root):
            continue
        for pat in patterns:
            _add(out, glob.glob(os.path.join(root, pat)))
    _add(out, glob.glob(os.path.join(local, "Programs", "*", "*", "bin", "java.exe")))
    _add(out, glob.glob(os.path.join(local, "Programs", "*", "*", "*", "bin", "java.exe")))
    _add(out, glob.glob(os.path.join(home, ".jdks", "*", "bin", "java.exe")))
    _add(out, glob.glob(os.path.join(home, "scoop", "apps", "*", "current", "bin", "java.exe")))
    return out


def _unix_candidates():
    """Linux / WSL：包自带的、系统的、sdkman/gradle 下过的都算"""
    out = []
    _add(out, glob.glob("/usr/lib/jvm/*/bin/java"))
    _add(out, glob.glob("/usr/lib/jvm/*/jre/bin/java"))
    _add(out, glob.glob("/usr/java/*/bin/java"))
    _add(out, glob.glob("/opt/*/bin/java"))
    _add(out, ["/usr/bin/java", "/usr/local/bin/java", "/snap/bin/java",
               os.path.expanduser("~/.local/bin/java")])
    _add(out, glob.glob(os.path.expanduser("~/.sdkman/candidates/java/*/bin/java")))
    _add(out, glob.glob(os.path.expanduser("~/.gradle/jdks/*/*/bin/java")))
    _add(out, glob.glob(os.path.expanduser("~/.jdks/*/bin/java")))
    # 别的目录里解压过的同类工具包（带着 runtime/jre 的那种）
    _add(out, glob.glob(os.path.expanduser("~/*/runtime/jre*/bin/java")))
    _add(out, glob.glob(os.path.expanduser("~/.cache/mc-seed-toolkit*/runtime/jre*/bin/java")))
    return out


def _java_candidates():
    """所有"可能是 java"的路径（还没验证能不能跑）"""
    out = []

    # 0) 包自带的免安装 JRE：Windows 用 runtime/jre-win，Linux/WSL 用 runtime/jre
    for root in (ROOT, HERE):
        if not root:
            continue
        for pat in ("runtime/jre-win/bin/java.exe", "runtime/jre-win/bin/java",
                    "runtime/jre/bin/java.exe", "runtime/jre/bin/java",
                    "runtime/*/bin/java.exe", "runtime/*/bin/java",
                    "*/runtime/jre-win/bin/java.exe", "*/runtime/jre/bin/java"):
            _add(out, glob.glob(os.path.join(root, pat)))

    # 1) 环境变量 / 配置里手填的
    _add(out, [os.environ.get("TOOLKIT_JAVA"), load().get("java")])

    # 2) PATH 里的
    for name in (("java.exe", "javaw.exe") if os.name == "nt" else ("java",)):
        _add(out, [shutil.which(name)])

    # 3) 系统和各种启动器里的
    _add(out, _windows_candidates() if os.name == "nt" else _unix_candidates())
    return [p for p in out if _runnable_here(p)]


def _java_works(path):
    """真跑一下 java -version，确认这个 Java 是可用的（残缺的 JRE 会在这里被刷掉）"""
    import subprocess
    try:
        r = subprocess.run([path, "-version"], capture_output=True, timeout=20)
        text = (r.stdout or b"") + (r.stderr or b"")
        return r.returncode == 0 and b"version" in text.lower()
    except Exception:
        return False


def find_java():
    """找一个"真的能跑"的 Java 返回；实在没有就返回 None。

    优先级：包自带的（U 盘版）> 版本够新（>=17）> 版本号高的。
    每一个候选都会真跑一次 `java -version` 验证，所以不会再出现"找到了但跑不起来"。
    """
    if _JAVA_CACHE:
        return _JAVA_CACHE[0]

    best = None                    # (优先级, 版本是否够, -版本号)
    best_path = None
    for cand in _java_candidates():
        major = check_java(cand)
        if not major:
            continue
        try:
            bundled = os.path.abspath(cand).startswith(os.path.abspath(ROOT))
        except Exception:
            bundled = False
        score = (0 if bundled else 1, 0 if major >= JAVA_MIN_MAJOR else 1, -major)
        if best is None or score < best:
            best, best_path = score, cand
    if best is None:
        return None

    _JAVA_CACHE.append(best_path)
    try:
        # 还没配置过（配置文件不存在）就先别写 —— 出厂状态的包跑一跑也保持干净，
        # 等你真的设了种子/版本/存档（或者进过设置菜单）再记这个 java 路径
        if os.path.exists(CONFIG_PATH):
            cfg = load()
            if cfg.get("java") != best_path:
                cfg["java"] = best_path
                save(cfg)
    except Exception:
        pass                       # 配置文件只读也不影响用
    return best_path


def java_hint():
    """找不到 Java 时给用户的说明（Windows / Linux 分别说）"""
    if os.name == "nt":
        return (
            "没找到能用的 Java。三个办法，任选一个：\n"
            "  1) 用【完整版】的 START.bat 启动 —— 包里自带 Windows 版 Java（runtime\\jre-win），会自动用上；\n"
            "  2) 已经在玩 Minecraft 的话，Java 一定在机器上：主菜单 3【设置】里把 Java 路径填成\n"
            "     ...\\bin\\java.exe（官方启动器/PCL 自带的在 %APPDATA%\\.minecraft\\runtime\\ 里面）；\n"
            "  3) 装一个 Java 21： https://adoptium.net/ （装完重开这个窗口）"
        )
    return (
        "没找到能用的 Java。两个办法：\n"
        "  1) 用 bash run.sh 启动（它会自动用包里自带的 runtime/jre）；\n"
        "  2) 或者 sudo apt install -y openjdk-21-jre-headless"
    )


# ------------------------------------------------------------------ 路径自适应
OBS_NAMES = ("seedhelper-observations.txt", "seedhelper_observations.txt")


def find_observations(save=None):
    """自动找模组写的观测文件。

    模组把它写在  .minecraft/versions/<版本>/seedhelper-observations.txt，
    而下载的存档在  .minecraft/versions/<版本>/saves/<存档名>，
    所以从存档目录往上找几层、再扫一遍所有版本的目录，基本都能自动命中。
    找不到返回 None。
    """
    starts = []
    if save:
        starts.append(os.path.abspath(save))
    for mc in _minecraft_dirs():
        starts.append(os.path.abspath(mc))
    for start in starts:
        # ① 自己这层 + 往上每一层
        p = start
        for _ in range(8):
            for name in OBS_NAMES:
                cand = os.path.join(p, name)
                if os.path.isfile(cand):
                    return cand
            parent = os.path.dirname(p)
            if parent == p:
                break
            p = parent
        # ② .minecraft/versions/*/seedhelper-observations.txt（换过版本也找得到）
        p = start
        for _ in range(8):
            for name in OBS_NAMES:
                hits = sorted(glob.glob(os.path.join(p, "versions", "*", name)))
                if hits:
                    return hits[-1]
            parent = os.path.dirname(p)
            if parent == p:
                break
            p = parent
    return None


def adapt_path(path):
    r"""把路径适配到当前系统：
       Windows 盘符 <-> WSL /mnt，\\wsl.localhost\... -> /，去引号，展开 ~ 和环境变量。
       这样同一个 .mc-tool.json 在 Windows 和 WSL 里都能用。"""
    import re as _re
    if not path:
        return path
    p = str(path).strip().strip('"').strip("'")
    p = os.path.expanduser(os.path.expandvars(p))

    win = _re.match(r"^([A-Za-z]):[\\/](.*)$", p)
    if os.name != "nt":
        if win:                                   # D:\x -> /mnt/d/x
            return "/mnt/%s/%s" % (win.group(1).lower(), win.group(2).replace("\\", "/"))
        unc = _re.match(r"^\\\\wsl(?:\.localhost)?\\[^\\]+\\(.*)$", p)
        if unc:                                   # \\wsl.localhost\Ubuntu\home\x -> /home/x
            return "/" + unc.group(1).replace("\\", "/")
    else:
        m = _re.match(r"^/mnt/([a-zA-Z])(?:/(.*))?$", p)
        if m:                                     # /mnt/d/x -> D:\x
            rest = (m.group(2) or "").replace("/", "\\")
            return ("%s:\\%s" % (m.group(1).upper(), rest)) if rest else ("%s:\\" % m.group(1).upper())
    return p


def load():
    cfg = dict(DEFAULTS)
    for path in (LEGACY_PATH, CONFIG_PATH):
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as fh:
                    cfg.update(json.load(fh))
            except Exception:
                pass
    for key in ("save", "obs"):
        if cfg.get(key):
            cfg[key] = adapt_path(cfg[key])
    return cfg


def save(cfg):
    data = {k: cfg.get(k, v) for k, v in DEFAULTS.items()}
    with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    return CONFIG_PATH


def set_seed(seed):
    cfg = load()
    cfg["seed"] = int(seed)
    save(cfg)
    return cfg


def get_seed(required=True):
    """取种子；取不到就返回 None（required=True 时提示怎么补）"""
    cfg = load()
    seed = cfg.get("seed")
    if seed is None and required:
        print("还没有种子。先跑 tool.py 选 1（计算种子），或在设置里手动填一个。")
    return seed


def mask(seed, show=False):
    """默认打码显示，防止截图/复述的时候漏出去"""
    if seed is None:
        return "（没有）"
    s = str(seed)
    if show or len(s) < 8:
        return s
    return f"{s[:5]}{'*' * (len(s) - 7)}{s[-2:]}"


def gateway_cache(seed):
    """缓存文件名用种子哈希，不在文件名里暴露种子"""
    import hashlib
    tag = hashlib.sha256(str(int(seed)).encode()).hexdigest()[:12]
    os.makedirs(RECORDS, exist_ok=True)
    return os.path.join(RECORDS, f".cache-gateways-{tag}.txt")


if __name__ == "__main__":
    import sys

    cfg = load()
    if len(sys.argv) > 1 and sys.argv[1] == "set" and len(sys.argv) > 2:
        set_seed(sys.argv[2])
        print("种子已写入", CONFIG_PATH)
    elif len(sys.argv) > 1 and sys.argv[1] == "show":
        print("配置文件:", CONFIG_PATH)
        print(json.dumps(load(), ensure_ascii=False, indent=2))
    else:
        print("配置文件:", CONFIG_PATH)
        print("种子:", mask(cfg.get("seed"), cfg.get("show_seed")))
        print("版本:", cfg.get("mc"))
        print("存档:", cfg.get("save"))
        print("java:", find_java())
