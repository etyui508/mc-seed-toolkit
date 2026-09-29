#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""首次启动的用户协议 / 隐私政策。

什么时候弹：配置里没记过"同意过哪一版"，或者记的版本比现在旧。
同意之后记在 .mc-tool.json 的 agreed 字段里（带版本和时间），以后就不再烦你。

改协议的正文时，把它上面的 AGREEMENT_VERSION 一起 +1，这样所有人下次启动都会重新看一遍。
"""
import datetime
import os

import i18n

# 界面文字都过一遍 i18n；查不到译文就原样显示中文
_ = i18n.t

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOC = os.path.join(ROOT, "docs", "用户协议与隐私政策.md")
DOC_EN = os.path.join(ROOT, "docs", "用户协议与隐私政策.en.md")

AGREEMENT_VERSION = "1"

# 正文太长，终端里只显示这几条要点；全文在 docs/用户协议与隐私政策.md
# 注意：这里存的是中文原文，翻译在显示的时候现查（import 时 i18n 还不知道用户选了哪种语言）
POINTS = [
    ("纯客户端", "不连服务器、不用 OP，算力都在你自己电脑上"),
    ("服规自己看", "很多服把「下载地图 / 破种子」写进规则了"),
    ("默认不上传", "种子、坐标、存档只存在你自己的电脑里"),
    ("只连两个地方", "启动查更新（只带版本号）+ 你亲手点反馈时"),
    ("日志先打码", "种子 / 路径 / 用户名会换成 <种子> 这种"),
    ("学生作品", "免费给你用，不担保结果"),
]


def needs_accept(cfg):
    """这次启动要不要让用户看协议"""
    agreed = str(cfg.get("agreed") or "")
    if not agreed:
        return True
    return not agreed.startswith(AGREEMENT_VERSION + ":")


def mark_agreed(cfg):
    cfg["agreed"] = f"{AGREEMENT_VERSION}:{datetime.datetime.now():%Y-%m-%d %H:%M}"
    return cfg


def full_text():
    """协议全文（按当前语言读文档；文档没了就退化成要点）"""
    path = DOC_EN if (i18n.current() == "en" and os.path.isfile(DOC_EN)) else DOC
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return _("（找不到 docs/用户协议与隐私政策.md，以下是要点）") + "\n\n" + \
               "\n".join(f"· {_(t)}：{_(d)}" for t, d in POINTS)


def doc_name():
    """当前语言该看哪份协议文档的文件名（中英各一份，别让英文用户去翻中文名）"""
    if i18n.current() == "en" and os.path.isfile(DOC_EN):
        return os.path.basename(DOC_EN)
    return os.path.basename(DOC)


def show(ask, width=None):
    """把协议摆出来，问用户同不同意。ask 是工具里那个输入函数"""
    import ui
    print()
    print(ui.box(
        [ui.s(_("第一次运行，先花十秒看一遍这几条："), "bold")] +
        [""] + [f"{ui.s('·', 'dim')} {ui.s(_(t), 'key')} —— {_(d)}" for t, d in POINTS] + [""] +
        [ui.s(_("  版本 v{ver} · 全文在 docs/{doc}", ver=AGREEMENT_VERSION, doc=doc_name()), "hint")],
        title=_("用户协议 & 隐私政策"), width=width))
    print()
    print("  " + ui.info(_("看全文：主菜单里随时可以再翻（或者直接打开上面那个 md 文件）")))
    print()
    answer = (ask(_("同意吗？同意才能往下用 [Y/n]: "), default="y") or "y").strip().lower()
    return answer not in ("n", "no", "不", "不同意")
