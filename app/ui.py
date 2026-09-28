#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
终端界面小工具：颜色 + 边框 + 对齐。

只依赖标准库。两个关键点：
  1. 中文按两个格子算（用 unicodedata 的东亚宽度），不然框线会歪
  2. 环境不对的时候自动降级：
       · 管道/重定向里（不是终端）-> 不出颜色
       · 控制台编码撑不住框线（老 GBK cmd）-> 自动换成 ASCII 的 +-| 框
       · Windows 老控制台 -> 先试打开 VT 转义支持，打不开就不上色

想强制：MC_UI_COLOR=1 强开颜色，MC_UI_ASCII=1 强制 ASCII 框。
"""
import os
import re
import shutil
import sys
import unicodedata

import i18n

# 界面自己画的那几句（大标题、进度条文字、默认值提示）也走语言表
_ = i18n.t


# ---------------------------------------------------------------- 环境探测
def _enable_ansi_windows():
    """Windows 的 cmd 默认不认 ANSI 转义，先给它打开"""
    if os.name != "nt":
        return True
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)          # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        if mode.value & 0x0004:                      # ENABLE_VIRTUAL_TERMINAL_PROCESSING
            return True
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:
        return False


def _encoding():
    return (getattr(sys.stdout, "encoding", "") or "").lower()


def _can_encode(text):
    enc = _encoding() or "ascii"
    try:
        text.encode(enc)
        return True
    except Exception:
        return False


def _isatty(stream=None):
    try:
        return bool((stream or sys.stdout).isatty())
    except Exception:
        return False


def term_width(default=64, minimum=46, maximum=68):
    """界面该画多宽：跟着终端走。

    以前宽度是写死的 62/64，终端一拉窄（或者 Windows 上把窗口调小），
    框线就会折行糊成一团。这里留两列边距，并夹在 [46, 68] 之间
    ——太窄装不下说明、太宽看着散。
    """
    try:
        cols = shutil.get_terminal_size((default, 24)).columns
    except Exception:
        cols = default
    if cols < 20:
        # 拿不到真实窗口大小（有些终端/PTY 会返回 0），别因此缩成最窄
        cols = default
    return max(minimum, min(maximum, cols - 2))


def _keys_available():
    """这台机器上能不能直接读键（Windows 的 msvcrt / POSIX 的 termios）"""
    try:
        import importlib.util
        if os.name == "nt":
            need = "msvcrt"
        else:
            need = "termios"
        if importlib.util.find_spec(need) is None:
            return False
        if os.name != "nt" and importlib.util.find_spec("tty") is None:
            return False
        return True
    except Exception:
        return False


_forced_tty = os.environ.get("MC_UI_FORCE_TTY") in ("1", "yes", "true")
TTY = _isatty() or _forced_tty
VT = _enable_ansi_windows()
# ANSI：能画颜色和移动光标。真终端默认开；被管道接走时默认关（脚本里干净）
ANSI = VT and (TTY or os.environ.get("MC_UI_ANSI") in ("1", "yes", "true"))

_color_env = os.environ.get("MC_UI_COLOR")
if _color_env in ("0", "no", "false", "off", "none"):
    COLOR = False
elif _color_env:
    COLOR = ANSI
elif os.environ.get("NO_COLOR"):
    COLOR = False
else:
    COLOR = ANSI

# 能不能用方向键那种交互菜单（要真终端 + 读得到键 + 能移动光标）
INTERACTIVE = TTY and ANSI and _keys_available()

# 开屏动画：交互环境下默认放，MC_NO_ANIM=1 关掉
ANIM = INTERACTIVE and os.environ.get("MC_NO_ANIM") not in ("1", "yes", "true")

if os.environ.get("MC_UI_ASCII") in ("1", "yes", "true"):
    UNICODE = False
else:
    UNICODE = _can_encode("╭╮╰╯─│┌┐└┘█░")
# 方框线能画出来、但符号（✓ ★ ❯ 这些）画不出来的时候，符号单独退回 ASCII
SYMBOLS = UNICODE and _can_encode("✓✗⚠★❯·")


# ---------------------------------------------------------------- 颜色
_CODES = {
    "reset": "\x1b[0m",
    "bold": "\x1b[1m",
    "dim": "\x1b[2m",
    "red": "\x1b[31m",
    "green": "\x1b[32m",
    "yellow": "\x1b[33m",
    "blue": "\x1b[34m",
    "magenta": "\x1b[35m",
    "cyan": "\x1b[36m",
    "white": "\x1b[97m",
    "bwhite": "\x1b[97m",
    "gray": "\x1b[90m",
    "bred": "\x1b[91m",
    "bgreen": "\x1b[92m",
    "byellow": "\x1b[93m",
    "bcyan": "\x1b[96m",
    "rev": "\x1b[7m",
}

CLR = "\x1b[2K"                # 清掉整行（交互菜单重画用）
CLEAR_LINE = "\r" + CLR        # 回到行首 + 清掉（进度条原地刷新用）


_CONSOLE_CACHE = []


def console():
    """真正的终端输出（动画专用）。按三个地方依次找：

    1) sys.__stdout__ —— 正常双击 START.bat 跑起来时就是控制台；
    2) Windows 的 CONOUT$ —— 输出被启动器/PCL 接走时 stdout 成了管道，但控制台
       本身还在，直接打开这个设备就能写上去；
    3) Linux/macOS 的 /dev/tty —— 同上，POSIX 下走控制终端。

    为什么要绕这一圈：跑慢活儿时工具会用 contextlib.redirect_stdout 把输出
    重定向到内存（好把结果同时写进日志），动画要是跟着进去，就会"跑的时候
    什么都没显示、跑完一口气全糊出来"。
    """
    if _CONSOLE_CACHE:
        return _CONSOLE_CACHE[0]
    out = None
    try:
        candidate = getattr(sys, "__stdout__", None)
        if candidate is not None:
            candidate.write("")
            if _isatty(candidate):
                out = candidate
    except Exception:
        pass
    if out is None and os.name == "nt":
        try:
            handle = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)
            out = handle
        except Exception:
            out = None
    if out is None and os.name != "nt":
        try:
            handle = open("/dev/tty", "w", encoding="utf-8", errors="replace", buffering=1)
            out = handle
        except Exception:
            out = None
    _CONSOLE_CACHE.append(out)
    return out


def init_console():
    """让输出一行一行实时出来。

    输出被接到管道/启动器里时，Python 默认会攒够一大块才写出去，
    于是用户看到的是"卡半天，然后一口气全出来"。这里打开行缓冲。
    """
    global _CONSOLE_KIND
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(line_buffering=True, write_through=True)
        except Exception:
            pass
    # 顺手记一下"动画到底能画到哪儿"，排查用（也进反馈包）
    try:
        probe = getattr(sys, "__stdout__", None)
        if probe is not None and _isatty(probe):
            _CONSOLE_KIND = "stdout"
        elif console():
            _CONSOLE_KIND = "CONOUT$" if os.name == "nt" else "/dev/tty"
        else:
            _CONSOLE_KIND = _("无（输出被接走了，画不了动画）")
    except Exception:
        _CONSOLE_KIND = "?"


_CONSOLE_KIND = None


def console_report():
    """一行说明动画的情况，出问题时让人贴出来就能定位"""
    kind = _CONSOLE_KIND or _("（还没探测）")
    return (_("TTY={tty} ANSI={ansi} 动画画到={kind}", tty=TTY, ansi=ANSI, kind=kind) + " "
            f"stdout.isatty={_isatty(sys.stdout)} "
            f"__stdout__.isatty={_isatty(getattr(sys, '__stdout__', None))}")

# 统一配色，想换风格只动这里
STYLES = {
    "title": ("bold", "bcyan"),
    "accent": ("bcyan",),
    "key": ("bold", "byellow"),
    "val": ("white",),
    "dim": ("gray",),
    "ok": ("bgreen",),
    "warn": ("byellow",),
    "err": ("bred",),
    "bar": ("bcyan",),
    "star": ("byellow",),
    "box": ("cyan",),
    "hint": ("gray",),
    "sel": ("rev", "bold"),      # 选中项：反白
    "sel_key": ("rev", "bold", "byellow"),
}


def s(text, *styles):
    """给文字上色（没开颜色就原样返回）"""
    if not COLOR or not styles:
        return str(text)
    codes = []
    for st in styles:
        if st in STYLES:
            codes += [_CODES[c] for c in STYLES[st] if c in _CODES]
        elif st in _CODES:
            codes.append(_CODES[st])
    if not codes:
        return str(text)
    return "".join(codes) + str(text) + _CODES["reset"]


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def strip(text):
    return _ANSI_RE.sub("", str(text))


# ---------------------------------------------------------------- 宽度 / 对齐
def w(text):
    """显示宽度：中文/全角 = 2，其余 = 1（先把颜色码去掉）"""
    text = strip(text)
    total = 0
    for ch in text:
        if unicodedata.combining(ch):
            continue
        total += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return total


def cut(text, width):
    """按显示宽度截断（超了加省略号）"""
    plain = strip(text)
    if w(plain) <= width:
        return text
    out, used = "", 0
    for ch in plain:
        step = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if used + step > width - 1:
            break
        out += ch
        used += step
    return out + "…"


def pad(text, width, align="left"):
    """按显示宽度补空格"""
    space = max(0, width - w(text))
    if align == "right":
        return " " * space + text
    if align == "center":
        left = space // 2
        return " " * left + text + " " * (space - left)
    return text + " " * space


_ANSI_TOKEN = re.compile(r"(\x1b\[[0-9;]*m)")


def fit(text, width):
    """按显示宽度截断，但**保留颜色码**（框里放不下时用）"""
    if w(text) <= width:
        return text
    colored = bool(_ANSI_TOKEN.search(str(text)))
    out, used = "", 0
    for token in _ANSI_TOKEN.split(str(text)):
        if _ANSI_TOKEN.fullmatch(token):
            out += token
            continue
        for ch in token:
            step = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
            if used + step > width - 1:
                return out + "…" + (_CODES["reset"] if colored else "")
            out += ch
            used += step
    return out


# ---------------------------------------------------------------- 框线
CH = {
    True: dict(tl="╭", tr="╮", bl="╰", br="╯", h="─", v="│", boxh="┌", boxb="└"),
    False: dict(tl="+", tr="+", bl="+", br="+", h="-", v="|", boxh="+", boxb="+"),
}


def _chars():
    return CH[bool(UNICODE)]


def box(lines, title=None, width=None):
    """画一个圆角框把 lines 装起来（lines 里可以带颜色）"""
    width = width or term_width()
    ch = _chars()
    inner = max([w(x) for x in lines] + ([w(title) + 2] if title else [0])) + 2
    if width:
        inner = max(inner, width - 2)
    top = ch["h"] * inner
    if title:
        t = f" {title} "
        top = t + ch["h"] * max(0, inner - w(t))
    out = [s(ch["tl"] + top + ch["tr"], "box")]
    for line in lines:
        out.append(s(ch["v"], "box") + " " + pad(fit(line, inner - 1), inner - 1) + s(ch["v"], "box"))
    out.append(s(ch["bl"] + ch["h"] * inner + ch["br"], "box"))
    return "\n".join(out)


def rule(width=None, style="dim"):
    width = width or term_width()
    return s(_chars()["h"] * width, style)


# ---------------------------------------------------------------- 常用块
def banner(title, subtitle="", version="", width=None):
    """顶部大标题（左边标题、右边版本号）"""
    width = width or term_width()
    ch = _chars()
    right = f"V{version}" if version else ""
    inner = width - 2                                  # 左右各留一个空格
    shown_title = fit(title, inner - w(right))
    out = [s(ch["tl"] + ch["h"] * width + ch["tr"], "box"),
           s(ch["v"], "box") + " " + s(shown_title, "title")
           + " " * max(0, inner - w(shown_title) - w(right)) + s(right, "dim") + " " + s(ch["v"], "box")]
    if subtitle:
        shown_sub = fit(subtitle, inner)
        out.append(s(ch["v"], "box") + " " + s(shown_sub, "hint")
                   + " " * max(0, inner - w(shown_sub)) + " " + s(ch["v"], "box"))
    out.append(s(ch["bl"] + ch["h"] * width + ch["br"], "box"))
    return "\n".join(out)


def section(text, width=None):
    """小标题，比如  ── 计算种子 ──────────"""
    width = width or term_width()
    label = f" {text} "
    ch = _chars()
    left = ch["h"] * 2
    rest = ch["h"] * max(0, width - w(left) - w(label))
    return s(left, "dim") + s(label, "accent") + s(rest, "dim")


def kv(pairs, key_width=None, gap=2):
    """键值对齐列表：[(键, 值), ...]"""
    kw = key_width or max([w(k) for k, _ in pairs] + [0])
    return "\n".join(s(pad(k, kw), "dim") + " " * gap + str(v) for k, v in pairs)


def menu(title, items, width=None, footer=None):
    """菜单：items = [(键, 标题, 说明), ...]"""
    width = width or term_width()
    ch = _chars()
    key_w = max([w(k) for k, _, _ in items] + [1])
    label_w = max([w(lbl) for _, lbl, _ in items] + [1])
    avail = width - 3                       # 行内实际能放多宽
    body = [section(title, avail), ""]
    for key, label, hint in items:
        head = f"[{key}]" + " " * (key_w - w(key) + 2)
        label_text = label
        if w(head) + w(label_text) > avail - 4:
            label_text = cut(label_text, max(4, avail - w(head) - 4))
        row = s(f"[{key}]", "bold", "byellow") + " " * (key_w - w(key) + 2)
        row += s(pad(label_text, max(label_w, w(label_text))), "bold")
        if hint:
            room = avail - w(head) - w(pad(label_text, label_w)) - 2
            if room >= 6:
                row += "  " + s(fit(hint, room), "hint")
        body.append(row)
    if footer:
        body += ["", s(fit(footer, avail), "hint")]
    edge = "─" if UNICODE else "-"
    corner = ch
    out = [s(corner["boxh"] + edge * (width - 2) + (corner["boxh"] if not UNICODE else "┐"), "box")]
    for line in body:
        out.append(s(ch["v"], "box") + " " + pad(line, width - 3) + s(ch["v"], "box"))
    out.append(s(corner["boxb"] + edge * (width - 2) + (corner["boxb"] if not UNICODE else "┘"), "box"))
    return "\n".join(out)


def ok(text):
    return s("✓ " if SYMBOLS else "[OK] ", "ok") + str(text)


def warn(text):
    return s("⚠ " if SYMBOLS else "[!] ", "warn") + str(text)


def err(text):
    return s("✗ " if SYMBOLS else "[x] ", "err") + str(text)


def info(text):
    return s("· " if SYMBOLS else "- ", "dim") + str(text)


def star():
    return s("★" if SYMBOLS else "*", "star")


def prompt_char():
    """输入提示符（终端编码撑不住 ❯ 的时候退回 > ）"""
    return s("❯ " if SYMBOLS else "> ", "accent")


def bar(frac, width=28):
    """进度条"""
    frac = max(0.0, min(1.0, float(frac)))
    n = int(round(frac * width))
    full, empty = ("█", "░") if UNICODE else ("#", ".")
    return s(full * n, "bar") + s(empty * (width - n), "dim")


def ask(prompt, default=None, allow_empty=False):
    """带样式的输入；直接回车用默认值"""
    tail = s(f" [{_('默认')} {default}]", "dim") if default is not None else ""
    while True:
        try:
            raw = input(prompt_char() + prompt + tail + " ").strip()
        except EOFError:
            return None
        if not raw:
            if default is not None:
                return default
            if allow_empty:
                return ""
            continue
        return raw


# ---------------------------------------------------------------- 按键
_SPECIAL_KEYS = {
    b"A": "up", b"B": "down", b"C": "right", b"D": "left",
    b"H": "up", b"P": "down", b"K": "left", b"M": "right",
}


def _read_key():
    """读一个键：'up'/'down'/'left'/'right'/'enter'/'esc'/'backspace'/'quit' 或普通字符"""
    if os.name == "nt":
        import msvcrt
        ch = msvcrt.getch()
        if ch in (b"\x00", b"\xe0"):
            return _SPECIAL_KEYS.get(msvcrt.getch())
        if ch in (b"\r", b"\n"):
            return "enter"
        if ch == b"\x1b":
            return "esc"
        if ch == b"\x08":
            return "backspace"
        if ch == b"\x03":
            return "quit"
        return ch.decode("utf-8", "ignore")

    import select
    fd = sys.stdin.fileno()
    raw_mode = False
    if TTY:
        import termios
        import tty
        old = termios.tcgetattr(fd)
        tty.setraw(fd)
        raw_mode = True
    try:
        ch = os.read(fd, 1)
        if ch == b"\x1b":                       # 可能是方向键，也可能是单独按了 Esc
            if not select.select([fd], [], [], 0.05)[0]:
                return "esc"
            nxt = os.read(fd, 1)
            if nxt in (b"[", b"O"):
                if not select.select([fd], [], [], 0.05)[0]:
                    return "esc"
                return _SPECIAL_KEYS.get(os.read(fd, 1))
            return "esc"
        if ch in (b"\r", b"\n"):
            return "enter"
        if ch in (b"\x7f", b"\x08"):
            return "backspace"
        if ch == b"\x03":
            return "quit"
        return ch.decode("utf-8", "ignore")
    finally:
        if raw_mode:
            import termios
            termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _key_waiting():
    """有没有按键正等着（开屏动画靠它实现"按任意键跳过"）"""
    if not INTERACTIVE:
        return False
    try:
        if os.name == "nt":
            import msvcrt
            return bool(msvcrt.kbhit())
        import select
        return bool(select.select([sys.stdin], [], [], 0)[0])
    except Exception:
        return False


# ---------------------------------------------------------------- 开屏动画
def intro(version="", subtitle="", width=None, enabled=None, status=None, steps=None):
    """开屏动画：框线长出来 -> 标题打字机 -> 一道光扫过 -> 收起。

    一共一秒多，按任意键跳过；不是真终端就什么都不放（管道里不会污染输出）。

    steps 给一组 [(说明, 函数)] 的话，那条进度线就**一边干真活一边走到底**
    （比如"检查更新"这种启动就该等的事），走完把每个函数的返回值按顺序返回。
    """
    width = width or term_width()
    if enabled is None:
        enabled = ANIM
    if not enabled:
        return [fn() for _label, fn in (steps or [])]     # 不放动画也得把活干了
    import time

    ch = _chars()
    title = _("MC 种子工具包")
    right = f"V{version}" if version else ""
    subtitle = subtitle or _("种子计算 · 结构计算 · 坐标查询")
    inner = width - 2
    drawn = []                                     # 已经画出来的行，收尾时要擦掉

    def emit(line):
        sys.stdout.write("\r" + CLR + line + "\n")
        sys.stdout.flush()
        drawn.append(line)

    def over(line):
        """覆盖当前这一行（不换行），用来做生长 / 打字机 / 扫描"""
        sys.stdout.write("\r" + CLR + line)
        sys.stdout.flush()

    def row_title(shown):
        gap = max(0, inner - w(strip(shown)) - w(right))
        return (s(ch["v"], "box") + " " + shown + " " * gap + s(right, "dim") + " " + s(ch["v"], "box"))

    def row_subtitle(shown):
        gap = max(0, inner - w(strip(shown)))
        return s(ch["v"], "box") + " " + shown + " " * gap + " " + s(ch["v"], "box")

    def up(n):
        if n > 0:
            sys.stdout.write(f"\x1b[{n}A")
            sys.stdout.flush()

    def down(n):
        if n > 0:
            sys.stdout.write(f"\x1b[{n}B")
            sys.stdout.flush()

    def framed_progress(seconds, text):
        """没有 steps 时的兜底：走一条**会走到底**的进度条（不是来回弹的那种）"""
        steps_n = max(8, int(seconds * 24))
        for i in range(steps_n + 1):
            frac = i / steps_n
            line = ("  " + bar(frac, 22) + f" {int(frac * 100):3d}%  " + s(text, "hint"))
            over(line)
            if _key_waiting():
                break
            time.sleep(seconds / steps_n)
        over("  " + bar(1.0, 22) + " 100%  " + s(_("准备就绪"), "ok"))
        sys.stdout.write("\n")
        sys.stdout.flush()

    def run_steps(items):
        """一边画进度一边把活干了 —— 启动要等的事都塞这儿"""
        results = []
        total = len(items)
        for i, (label, fn) in enumerate(items, 1):
            frac = (i - 1) / total
            over("  " + bar(frac, 22) + f" {int(frac * 100):3d}%  " + s(label, "hint"))
            sys.stdout.flush()
            try:
                results.append(fn())
            except Exception:
                results.append(None)          # 某一步出错不该拦着启动
            # 画到这一步的完成度（剩下的留给下一步的"开始"）
            frac = i / total
            over("  " + bar(frac, 22) + f" {int(frac * 100):3d}%  "
                 + s(_("{label} 完成", label=label), "hint"))
        over("  " + bar(1.0, 22) + " 100%  " + s(_("准备就绪"), "ok"))
        sys.stdout.write("\n")
        sys.stdout.flush()
        return results

    def finish():
        """把动画占掉的那几行擦干净，让正式界面从顶上来"""
        rows = len(drawn) + 1                       # +1：当前正在写的那一行
        up(rows)
        for _i in range(rows):
            sys.stdout.write(CLR + "\n")
        up(rows)
        sys.stdout.flush()

    try:
        # ① 顶边框从左往右长出来
        for n in range(0, width + 1, 8):
            over(s(ch["tl"] + ch["h"] * n, "box"))
            if _key_waiting():
                raise KeyboardInterrupt
            time.sleep(0.005)
        over(s(ch["tl"] + ch["h"] * width + ch["tr"], "box"))
        emit(s(ch["tl"] + ch["h"] * width + ch["tr"], "box"))

        # ② 标题打字机
        for k in range(0, w(title) + 1):
            over(row_title(s(title[:k], "title")))
            if _key_waiting():
                raise KeyboardInterrupt
            time.sleep(0.018)
        over(row_title(s(title, "title")))
        emit(row_title(s(title, "title")))

        # ③ 副标题打字机
        for k in range(0, w(subtitle) + 1):
            over(row_subtitle(s(subtitle[:k], "hint")))
            if _key_waiting():
                raise KeyboardInterrupt
            time.sleep(0.006)
        over(row_subtitle(s(subtitle, "hint")))
        emit(row_subtitle(s(subtitle, "hint")))

        # ④ 底边框
        for n in range(0, width + 1, 8):
            over(s(ch["bl"] + ch["h"] * n, "box"))
            if _key_waiting():
                raise KeyboardInterrupt
            time.sleep(0.005)
        over(s(ch["bl"] + ch["h"] * width + ch["br"], "box"))
        emit(s(ch["bl"] + ch["h"] * width + ch["br"], "box"))

        # ⑤ 一道光从标题上扫过去
        back = len(drawn) - 1                       # 回到标题那一行（它上面只有顶边框）
        up(back)
        for offset in range(-3, len(title) + 3):
            chars = "".join(s(c, "bold", "bwhite") if abs(i - offset) <= 1 else s(c, "title")
                            for i, c in enumerate(title))
            over(row_title(chars))
            if _key_waiting():
                break
            time.sleep(0.012)
        over(row_title(s(title, "title")))
        down(back)

        # ⑥ 状态行：有活就一边干一边走到底，没活就走一条纯进度条
        results = (run_steps(steps) if steps
                   else (framed_progress(0.4, status or _("正在准备")), [])[1])

        # ⑦ 收尾：把整块动画擦干净，等下画正式界面
        finish()
        return results
    except KeyboardInterrupt:
        finish()
        return [fn() for _label, fn in (steps or [])]     # 跳过了也得把活干了


# ---------------------------------------------------------------- 转圈
_ACTIVE_SPINNER = []        # 正在画的那个（嵌套时只换文案，不叠着画）


class _Spinner:
    """跑慢活儿的时候转个圈 + 显示已用时间。

    三条规矩：
      · 往**真正的终端**写（ui.console()），这样 run_and_log 那种"重定向到
        缓冲区"不会把动画一起吞掉，跑完再一口气吐出来；
      · 真终端里只占一行：\\r 回到行首 + 空格补齐（不依赖 \\x1b[K 清行，
        老 cmd 只认 \\r 也能原地刷新）；
      · 输出被接走（不是终端）时，改成每几秒打一行，别一声不吭。
    """

    HEARTBEAT = 5.0        # 不是终端时：多久打一行

    def __init__(self, text="", delay=0.35):
        self.text = text or _("正在算")
        self._nested = False
        self.delay = delay          # 一眨眼就完事的活儿别闪一下动画
        self._out = console()
        self._term = bool(self._out) and _isatty(self._out)
        self._width = 0             # 上一次画了多宽，用来把残留擦干净
        self._stop = None
        self._thread = None

    def __enter__(self):
        # 已经有一个动画在画了（比如外层"正在算"里又套了个具体的扫描）：
        # 只把文案更新成更具体的那句，别两个线程抢同一行
        if _ACTIVE_SPINNER:
            _ACTIVE_SPINNER[0].text = self.text
            self._nested = True
            return self
        if not self._out:
            return self
        import threading
        _ACTIVE_SPINNER.append(self)
        self._stop = threading.Event()
        stop = self._stop

        def loop():
            import time
            t0 = time.time()
            i = 0
            frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏" if SYMBOLS else "-\\|/"
            next_beat = self.delay if not self._term else self.delay
            while not stop.wait(0.12 if self._term else 0.25):
                elapsed = time.time() - t0
                if elapsed < self.delay:
                    continue
                if self._term:
                    line = ("  " + s(self.text, "hint") + "  "
                            + s(frames[i % len(frames)], "accent")
                            + s("  " + _("已用 {t}s", t=f"{elapsed:.1f}"), "dim"))
                    pad = max(0, self._width - w(line))
                    try:
                        self._out.write("\r" + line + " " * pad)
                        self._out.flush()
                    except Exception:
                        return
                    self._width = max(self._width, w(line))
                    i += 1
                elif elapsed >= next_beat:
                    next_beat = elapsed + self.HEARTBEAT
                    try:
                        self._out.write("  " + self.text + "  "
                                        + _("已用 {t}s", t=f"{elapsed:.1f}") + "\n")
                        self._out.flush()
                    except Exception:
                        return

        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        if self._nested:
            return False
        if _ACTIVE_SPINNER and _ACTIVE_SPINNER[0] is self:
            _ACTIVE_SPINNER.pop()
        if self._stop:
            self._stop.set()
            if self._thread:
                self._thread.join(timeout=2)
        if self._term and self._width and self._out:
            try:                       # 把这一行擦干净，后面的正式输出从行首开始
                self._out.write("\r" + " " * self._width + "\r")
                self._out.flush()
            except Exception:
                pass
        return False


def spinner(text=""):
    """用法： with ui.spinner("扫描 2000 格内的结构"): 跑慢命令"""
    return _Spinner(text)
