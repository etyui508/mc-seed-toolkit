#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""诊断日志：出问题的时候，让用户把这一份文件发过来就能排查。

写在哪：  记录/日志.txt（超过 512KB 自动轮转成 日志.1.txt）
记什么：  启动环境、菜单选择、每条查询的参数和结果条数、更新过程、报错和堆栈
不记什么：种子、存档路径里的用户名 —— 写进去之前都会先脱敏
          （你也不想为了报个 bug 就把种子交出去）

想让用户一键打包：diag.bundle() 会生成 记录/反馈包-<时间>.zip
"""
import datetime
import os
import platform
import sys
import traceback
import zipfile

import i18n

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RECORDS = os.path.join(ROOT, "记录")
LOG_FILE = os.path.join(RECORDS, "日志.txt")
OLD_LOG = os.path.join(RECORDS, "日志.1.txt")
MAX_BYTES = 512 * 1024

_installed = False


def _t_log(text):
    """日志里的事件名 / 字段名也翻译，但用独立的键（log:xxx），
    免得跟界面上同名的文案串味（比如界面的「新版本」是 Available，
    日志里当字段用就得是 new_version）。查不到就保持中文。"""
    if i18n.current() == i18n.DEFAULT:
        return text
    got = i18n.t("log:" + text)
    return text if got.startswith("log:") else got


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------- 脱敏
def sanitize(text):
    """把不该出现在日志里的东西抹掉：种子、家目录、工具包路径"""
    if not text:
        return ""
    text = str(text)
    import state
    if state.SEED is not None:
        text = text.replace(str(state.SEED), "<种子>")
    # 存档 / 观测文件的路径也打码（里面有服务器地址和你的目录结构）
    try:
        import config as cfgmod
        cfg = cfgmod.load()
        for key, tag in (("save", "<存档路径>"), ("obs", "<观测文件>")):
            value = cfg.get(key)
            if value and len(str(value)) > 3:
                text = text.replace(str(value), tag)
    except Exception:
        pass
    home = os.path.expanduser("~")
    # 先替工具包目录，再替家目录（顺序反了的话 ROOT 会被家目录那步切碎）
    for holder in (ROOT, home):
        if holder and len(str(holder)) > 3:
            text = text.replace(str(holder), "<路径>")
            text = text.replace(str(holder).replace("\\", "/"), "<路径>")
    # Windows 下的用户名（C:\Users\xxx）
    for marker in ("\\Users\\", "/Users/", "/home/"):
        idx = 0
        while True:
            idx = text.find(marker, idx)
            if idx < 0:
                break
            end = idx + len(marker)
            while end < len(text) and text[end] not in "\\/\"' \n\t":
                end += 1
            text = text[:idx + len(marker)] + "<用户>" + text[end:]
            idx += len(marker)
    return text


# ---------------------------------------------------------------- 写日志
def _rotate():
    try:
        if os.path.getsize(LOG_FILE) > MAX_BYTES:
            if os.path.exists(OLD_LOG):
                os.remove(OLD_LOG)
            os.replace(LOG_FILE, OLD_LOG)      # replace 比 rename 稳（Windows 上也能覆盖）
    except OSError:
        pass


def log(event, level="INFO", **fields):
    """记一行。fields 会写成 键=值，方便 grep"""
    try:
        os.makedirs(RECORDS, exist_ok=True)
        _rotate()
        detail = "  ".join(f"{_t_log(k)}={sanitize(v)}"
                          for k, v in fields.items() if v not in (None, ""))
        line = f"{_now()}  {level:<5} {_t_log(event)}"
        if detail:
            line += "  " + detail
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(line.rstrip() + "\n")
    except Exception:
        pass                      # 日志绝不能把主程序搞崩


def warn(event, **fields):
    log(event, level="WARN", **fields)


def error(event, exc=None, **fields):
    if exc is not None:
        fields["异常"] = f"{type(exc).__name__}: {exc}"
    log(event, level="ERROR", **fields)
    if exc is not None:
        for line in traceback.format_exc().splitlines():
            if line.strip():
                log("  " + line.strip(), level="ERROR")


def environment():
    """把排查问题需要的环境信息收集起来（不含任何隐私）"""
    import config as cfgmod
    info = {
        _t_log("工具版本"): _version(),
        _t_log("时间"): _now(),
        _t_log("系统"): f"{platform.system()} {platform.release()} ({platform.machine()})",
        "Python": sys.version.split()[0],
        _t_log("执行文件"): sys.executable,
        _t_log("界面"): _t_log("彩色") if _ui_color() else _t_log("纯文本"),
    }
    try:
        java = cfgmod.find_java()
        info["Java"] = f"{cfgmod.check_java(java)}  {java}" if java else _t_log("没找到")
    except Exception as e:
        info["Java"] = _t_log("检测失败") + f"（{e}）"
    try:
        import engine
        info[_t_log("结构引擎")] = (engine.FINDSTRUCT if os.path.exists(engine.FINDSTRUCT)
                                    else _t_log("缺失"))
    except Exception:
        pass
    try:
        import state
        info[_t_log("当前版本")] = state.USER_VER or _t_log("（没选）")
    except Exception:
        pass
    return info


def _version():
    try:
        import updater
        return updater.local_version()
    except Exception:
        return "?"


def _ui_color():
    try:
        import ui
        return ui.COLOR
    except Exception:
        return False


def text(limit=0):
    """读日志内容（limit>0 时只取最后 limit 行）"""
    try:
        with open(LOG_FILE, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return "（还没有日志）"
    if limit and len(lines) > limit:
        lines = [f"（前面还有 {len(lines) - limit} 行，见完整文件）"] + lines[-limit:]
    return "\n".join(lines)


def tail_file(path, limit=200):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return None
    if len(lines) > limit:
        return "\n".join([f"（只取最后 {limit} 行）"] + lines[-limit:])
    return "\n".join(lines)


# ---------------------------------------------------------------- 崩溃兜底
def install_excepthook(notify=True):
    """程序崩了也别让用户一脸懵：写日志 + 告诉他们怎么反馈"""
    global _installed
    if _installed:
        return
    _installed = True
    old = sys.excepthook

    def hook(kind, value, tb):
        error("程序崩了", exc=value,
              **{"类型": kind.__name__})
        detail = "".join(traceback.format_exception(kind, value, tb))
        for line in traceback.format_exception(kind, value, tb):
            for sub in line.rstrip().splitlines():
                log("  " + sub.strip(), level="ERROR")
        if notify:
            print()
            print("=" * 60)
            print("  " + i18n.t("出错了。这段信息已经写进 记录/日志.txt"))
            print("=" * 60)
            # 崩了还让人自己去菜单里翻日志，太麻烦 —— 直接问一句要不要发出去
            try:
                import ui
                if (ui.INTERACTIVE
                        and input("  " + i18n.t("直接把这段报错发给作者吗？")
                                  + "[Y/n] ").strip().lower() != "n"):
                    ok, msg = submit(i18n.t("崩溃：{kind}", kind=type(value).__name__),
                                     str(value)[:2000],
                                     "", extra=detail)
                    print("  " + ("✓ " + msg if ok else "· " + msg))
                else:
                    print("  " + i18n.t("那稍后可以用主菜单 5【反馈问题】发出去"))
            except Exception:
                print("  " + i18n.t("（想反馈就发 记录/日志.txt）"))
        return old(kind, value, tb)

    sys.excepthook = hook


# ---------------------------------------------------------------- 打包反馈
FEEDBACK_URL = "https://mcseek.bony-doorframe-shortly.top"


def submit(title, body, contact="", extra=""):
    """把问题 + 日志提交到反馈站。返回 (成功?, 说明)"""
    import json
    import urllib.error
    import urllib.request

    payload = {
        "title": title or "（没写标题）",
        "body": body or "",
        "contact": contact or "",
        "version": _version(),
        "env": sanitize("\n".join(f"{k}: {v}" for k, v in environment().items())),
        "log": sanitize(text()) + (("\n\n--- 附加信息 ---\n" + sanitize(extra)) if extra else ""),
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(FEEDBACK_URL + "/api/report", data=data, headers={
        "Content-Type": "application/json",
        "User-Agent": f"mc-seed-toolkit/{_version()}",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        if result.get("ok"):
            return True, result.get("message") or "已提交"
        return False, result.get("message") or "反馈站没接受这条提交"
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = json.loads(e.read().decode("utf-8")).get("message", "")
        except Exception:
            pass
        return False, detail or f"反馈站返回 {e.code}"
    except Exception as e:
        return False, f"连不上反馈站（{e}）"


def bundle(include_records=True):
    """把日志 + 环境信息 + 最近的记录打包成一个 zip，返回路径"""
    os.makedirs(RECORDS, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = os.path.join(RECORDS, f"反馈包-{stamp}.zip")
    env = "\n".join(f"{k}: {v}" for k, v in environment().items())
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("环境.txt", sanitize(env) + "\n")
        z.writestr("日志.txt", sanitize(text()))
        if include_records:
            for name in ("坐标记录.txt", "算种子记录.txt"):
                body = tail_file(os.path.join(RECORDS, name))
                if body:
                    z.writestr(name, sanitize(body) + "\n")
    return path


if __name__ == "__main__":
    # 单独跑这个脚本时也要按配置里的语言来，不然英文用户看到的还是中文
    try:
        import config as cfgmod
        i18n.set_lang(cfgmod.load().get("lang") or i18n.guess_from_system())
    except Exception:
        pass
    print(i18n.t("环境信息："))
    for k, v in environment().items():
        print(f"  {k}: {v}")
    print("\n" + i18n.t("日志文件：{path}", path=LOG_FILE))
    print(text(limit=20))
