#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""界面文字的多语言。

怎么用：

    import i18n
    print(i18n.t("正在计算种子…"))
    print(i18n.t("已更新到 {ver}", ver="1.16.0"))

设计上刻意"以中文原文为 key"：
  · 没翻译到的地方原样显示中文，不会崩、不会显示成空白；
  · 加新语言只要往 app/lang/ 里丢一个 json，不用改代码；
  · 代码里读起来还是中文，改文案的时候一眼就能对上。

语言文件放在 app/lang/<代码>.json，内容就是 {"中文原文": "译文"}。
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
LANG_DIR = os.path.join(HERE, "lang")

# 语言代码 -> 用它自己的语言写的名字（选语言那一步显示这个）
LANGS = {
    "zh": "中文",
    "en": "English",
}

# 藏起来的语言：不进「选语言」那屏，也不在设置里列出来，
# 只有主菜单那个彩蛋（[9] 千万别点 → Yes ③）能切过去。
# 表是 tools/make-mt-lang.py 生成的（拿英文译文过一遍"老式机翻"再翻回来），
# 两份跟着界面语言走：界面中文 → 机翻吐中文，界面英文 → 机翻吐英文。
# 翻不全的地方照常回落，不会变空。
HIDDEN_LANGS = {
    "mt": "机翻",
    "mt-en": "Machine English",
}
DEFAULT = "zh"

_lang = DEFAULT
_table = {}


def available():
    """有哪些语言：[(代码, 名字), ...]（只列能选的，彩蛋语言不算）"""
    return [(code, name) for code, name in LANGS.items()]


def lang_name(code):
    code = (code or "").lower()
    return LANGS.get(code) or HIDDEN_LANGS.get(code) or code or DEFAULT


def current():
    return _lang


def _load(code):
    path = os.path.join(LANG_DIR, f"{code}.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return {k: v for k, v in data.items() if isinstance(v, str) and v}
    except Exception:
        return {}


def set_lang(code):
    """切语言。未知代码当作默认（中文）。"""
    global _lang, _table
    code = str(code or "").strip().lower()
    if code not in LANGS and code not in HIDDEN_LANGS:
        code = DEFAULT
    _lang = code
    _table = {} if code == DEFAULT else _load(code)
    # 子进程（Java 工具、cubiomes、calc_seed.py 这些）拿不到内存里的语言，
    # 只能靠环境变量传 —— 它们起来的时候会读 MC_LANG。
    try:
        os.environ["MC_LANG"] = code
    except Exception:
        pass
    return _lang


def guess_from_system():
    """从系统区域猜一个默认语言：认识中文就中文，否则英文。

    只在"配置里还没存过语言"的时候用（首次启动的默认选项）。
    环境变量 MC_LANG 排在最前面：run.sh 用它告诉工具"这次按哪种语言来"，
    子进程（Java 工具、calc_seed.py）也靠它知道自己该说什么话。
    """
    env_lang = (os.environ.get("MC_LANG") or "").strip().lower()
    if env_lang.startswith(("mt-en", "en")):        # mt-en 要排在 mt 前面
        return "en"
    if env_lang.startswith(("mt", "zh")):
        return "zh"
    for key in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        value = os.environ.get(key)
        if value:
            v = value.lower()
            if "zh" in v or "chinese" in v:
                return "zh"
            if v and not v.startswith(("c.", "posix")):
                return "en"
    if os.name == "nt":                     # Windows：问一下系统界面语言
        try:
            import ctypes
            code = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            return "zh" if (code & 0x3FF) == 0x04 else "en"
        except Exception:
            pass
    return DEFAULT


def t(text, **kw):
    """翻译一句；查不到就原样返回。

    kw 用来填 {占位符}。译文里的占位符跟中文对不上时不会炸，退回中文。
    """
    s = text
    if _lang != DEFAULT and _table:
        s = _table.get(text, text)
    if kw:
        try:
            s = s.format(**kw)
        except Exception:
            try:
                s = str(text).format(**kw)
            except Exception:
                s = text
    return s


def split_notes(text):
    """把"中文 / English"这种双语发布说明拆成 (中文, 英文)。

    拆不开就返回 (原文, "")。

    规矩：左边有中文、右边一个中文都没有、而且右边像一句英文（带 the/and/to 这类
    虚词）才算真的双语。这样「剪贴板 / txt / json」不会被拆错，
    「（中文 / 英文）」这种藏在中文里的斜杠也骗不过去。
    想百分百确定的话，用显式分隔符 `=== EN ===` 那几种，不走猜的。
    """
    text = str(text or "").strip()
    if not text:
        return "", ""
    # 显式分隔符：怎么切都不会错，优先用
    for sep in ("\n=== EN ===\n", "\n== EN ==\n", "\n\n---\n\n", "|||"):
        if sep in text:
            head, _, tail = text.partition(sep)
            if head.strip() and tail.strip():
                return head.strip(), tail.strip()
    best = None
    for sep in (" / ", "｜"):
        start = 0
        while True:
            i = text.find(sep, start)
            if i < 0:
                break
            head, tail = text[:i], text[i + len(sep):]
            if (head.strip() and tail.strip() and _has_cjk(head)
                    and not _has_cjk(tail) and _looks_english(tail)):
                if best is None or len(tail) > len(best[1]):
                    best = (head.strip(), tail.strip())
            start = i + len(sep)
    return best if best else (text, "")


def _has_cjk(text):
    return any("\u4e00" <= ch <= "\u9fff" for ch in str(text))


# 判断"这半像不像一句英文"用的虚词（中文说明里几乎不会出现这些）
_EN_WORDS = (" the ", " a ", " an ", " to ", " and ", " of ", " for ", " with ",
             " on ", " in ", " is ", " are ", " by ", " from ", " that ")


def _looks_english(text):
    low = " " + str(text).lower().replace("\n", " ") + " "
    return any(word in low for word in _EN_WORDS)


def pick_notes(man):
    """从更新清单里按当前语言挑出发布说明。

    优先用单独的 notes_en 字段；没有就把 notes 里的"中文 / English"拆开取对应那半；
    英文那半缺失（老版本说明）时，英文界面下退回显示中文，总比空着强。
    """
    zh, en = split_notes(man.get("notes"))
    if current() == "en":
        return str(man.get("notes_en") or "").strip() or en or zh
    return zh or str(man.get("notes") or "")
