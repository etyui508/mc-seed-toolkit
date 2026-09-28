#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""主菜单 [9] 千万别点 —— 一个纯彩蛋。

点进去没有「不」，只有三个 Yes：
  ① 开浏览器放一段视频
  ② 整个窗口原地转三圈（真的在字符网格上转，不是假装转）
  ③ 把界面语言换成「人机翻译版」

几条自我约束：
  · 输出被接走（管道 / 重定向）或者终端不支持 ANSI 时，动画降级成一行提示，
    绝不往屏幕上糊一屏乱码；
  · 只动配置里的 lang 这一项，随时能在【设置】里切回来，不碰种子/存档/记录；
  · 输入被关掉（EOF，比如管道里跑）时放人走 —— 那不算作弊，不放人走会死循环。
"""
import os
import pathlib
import subprocess
import sys
import time
import unicodedata

import diag
import i18n
import ui

import config as cfgmod

_ = i18n.t

HERE = os.path.dirname(os.path.abspath(__file__))
EGG_HTML = os.path.join(HERE, "assets", "egg.html")

# 窗口转一圈分 4 步（90° 一格），转 3 圈。步子太快看不清，太慢显得卡。
TURNS = 3
FRAME_SECONDS = 0.11


# ---------------------------------------------------------------- 入口
def run(cfg):
    """从主菜单进来。三个 Yes 挑一个，没有第四个选项。"""
    print()
    print(ui.section(_("千万别点")))
    print("  " + ui.warn(_("这个按钮上写着别点，那不是装饰。")))
    print("  " + ui.info(_("你真的确定要为自己的选择负责吗？")))
    print()
    print(ui.menu(_("请挑一个"), [
        ("1", "Yes ①", ""),
        ("2", "Yes ②", ""),
        ("3", "Yes ③", ""),
    ], footer=_("这里没有「不」，只有三个 Yes。")))
    print()
    while True:
        raw = ui.ask(_("选一个: "), allow_empty=True)
        if raw is None:                     # 输入被关掉（Ctrl+D / 管道），不困着人
            print()
            return
        raw = raw.strip()
        if raw in ("1", "2", "3"):
            break
        print("  " + ui.warn(_("没有别的选项。三个 Yes 挑一个。")))
    print()
    diag.log("彩蛋", 选了="Yes" + raw)
    if raw == "1":
        _video()
    elif raw == "2":
        _spin()
    else:
        _mt(cfg)


# ---------------------------------------------------------------- Yes ①
def _video():
    """开浏览器放 app/assets/egg.html（里面引的是旁边那段 egg.mp4）。"""
    if not os.path.isfile(EGG_HTML):
        print("  " + ui.err(_("彩蛋视频不见了（app/assets/egg.html）")))
        return
    if _open_browser(pathlib.Path(EGG_HTML).as_uri()):
        print("  " + ui.ok(_("窗口开出来了 —— 都说了别点。")))
    else:
        print("  " + ui.warn(_("没找到能用的浏览器，自己打开这个文件也一样：")))
        print("    " + EGG_HTML)


def _is_wsl():
    try:
        with open("/proc/version", encoding="utf-8", errors="ignore") as fh:
            return "microsoft" in fh.read().lower()
    except OSError:
        return False


def _windows_path(path):
    r"""把 /home/... 翻成 WSL 里的 Windows 路径：\\wsl$\发行版\home\..."""
    distro = os.environ.get("WSL_DISTRO_NAME") or "Ubuntu"
    return "\\\\wsl$\\" + distro + os.path.abspath(path).replace("/", "\\")


def _open_browser(url):
    """开默认浏览器。

    Windows / macOS 直接交给 webbrowser。Linux（含 WSL）不能信它：
    xdg-open 说"没有能打开这个的程序"时它照样返回 True（只要进程起得来），
    于是就成了"提示打开了、其实什么都没开"。所以这里一个个试，**看退出码**。
    """
    if os.name == "nt" or sys.platform == "darwin":
        try:
            import webbrowser
            return bool(webbrowser.open(url, new=2))
        except Exception:
            return False
    # (命令, 是不是"起得来就算成功")
    tries = []
    if _is_wsl():
        win = _windows_path(EGG_HTML)
        tries += [(["wslview", url], False),
                  # Start-Process 是这里唯一会老实返回退出码的：0 = 交出去了
                  (["powershell.exe", "-NoProfile", "-Command",
                    "Start-Process '%s'" % win], False),
                  # explorer.exe 打开了也照样返回 1（WSL 上人人都踩过），
                  # 所以它只要起得来就算成功，放在后面当兜底
                  (["explorer.exe", win], True)]
    tries.append((["xdg-open", url], False))
    for cmd, any_exit in tries:
        try:
            done = subprocess.run(cmd, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, timeout=20)
        except Exception:
            continue
        if done.returncode == 0 or any_exit:
            return True
    return False


# ---------------------------------------------------------------- Yes ②
def _window_lines():
    """要转的那个「窗口」。纯文本无颜色 —— 颜色码会被旋转搅碎。"""
    ch = ui._chars()
    inner = 15
    rows = [_("千万别点"), _("都说了别点")]
    out = [ch["tl"] + ch["h"] * inner + ch["tr"]]
    for row in rows:
        out.append(ch["v"] + " " + ui.pad(ui.cut(row, inner - 1), inner - 1) + ch["v"])
    out.append(ch["bl"] + ch["h"] * inner + ch["br"])
    return out


def _cells(line):
    """把一行拆成「显示格子」：中文占两格，两个格子都放它自己。

    这样旋转出来的图不会因为宽字符错位。转过去之后那个字会在相邻两行各出现
    一次，看着像描粗了 —— 反正转起来本来也读不出来。
    """
    out = []
    for ch in line:
        out.append(ch)
        if unicodedata.east_asian_width(ch) in ("W", "F"):
            out.append(ch)
    return out


def rot90(grid):
    """顺时针转 90°（网格里一格 = 屏幕上一格）"""
    height = len(grid)
    width = max(len(row) for row in grid)
    padded = [row + [" "] * (width - len(row)) for row in grid]
    return [[padded[height - 1 - i][j] for i in range(height)] for j in range(width)]


def render_grid(grid):
    return ["".join(row).rstrip() for row in grid]


def flip180(lines):
    """转 180°。

    为什么不用旋转网格：中文占两格，转 90° 时那两格会落到相邻两行（正好是
    一个字转过来该有的样子），转 180° 时却会落在同一行相邻两格上 —— 屏幕上
    就变成「点点别别」。所以这一帧走"整行倒序 + 行内倒序"，字形不乱。
    """
    return [line[::-1] for line in reversed(lines)]


def _paint(lines, height, first=False):
    buf = []
    if not first:
        buf.append("\x1b[%dA" % height)         # 回到上一帧的第一行
    for i in range(height):
        buf.append("\x1b[2K")                   # 清这一行
        buf.append(lines[i] if i < len(lines) else "")
        buf.append("\n")
    sys.stdout.write("".join(buf))
    sys.stdout.flush()


def _spin():
    if not ui.ANIM:
        print("  " + ui.info(_("（这个终端画不了动画，就先不转了）")))
        return
    base = _window_lines()
    grid = [_cells(line) for line in base]
    height = max(len(grid), max(len(row) for row in grid))
    quarter = [base,                                    # 0°
               render_grid(rot90(grid)),                # 90°
               flip180(base),                           # 180°
               render_grid(rot90(rot90(rot90(grid))))]  # 270°
    frames = quarter * TURNS + [base]                   # 转满三圈，停在正面

    sys.stdout.write("\x1b[2J\x1b[H")       # 清屏从头画：块子比屏幕高就滚花了
    for i, frame in enumerate(frames):
        _paint(frame, height, first=(i == 0))
        time.sleep(FRAME_SECONDS)
    _paint(frame, height)                   # 最后一帧多停一下
    time.sleep(0.35)
    sys.stdout.write("\x1b[2J\x1b[H")       # 收干净，主循环接着把菜单画回来
    sys.stdout.flush()
    print("  " + ui.ok(_("转完了。你的窗口没事。")))


# ---------------------------------------------------------------- Yes ③
def _mt(cfg):
    """切成「人机翻译版」，顺手把语言记进配置（下次启动还是它）。"""
    i18n.set_lang("mt")
    cfg["lang"] = "mt"
    try:
        cfgmod.save(cfg)
    except Exception:
        pass
    print("  " + ui.ok(_("语言已切换：{name}", name=i18n.lang_name("mt"))))
    print("  " + ui.info(_("雷时东雷时东粉末雷时东滚木")))
    print("  " + ui.info(_("想切回来：主菜单 3【设置】最上面那一项。")))
