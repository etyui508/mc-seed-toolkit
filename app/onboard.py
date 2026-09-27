#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""首次启动引导：配置文件由用户自己配出来，包里默认一份都不带。

为什么不做一份"出厂配置"塞进包里：
  · 配置里会有种子、存档路径、用户名之类的东西，发给别人等于把自己的底交出去；
  · 每个人的游戏版本 / 存档位置 / Java 都不一样，填错了还不如让用户自己选一次。

所以：第一次启动花半分钟走一遍这里，之后配置文件就一直在本地，
每次启动直接读它（想改主菜单 3【设置】）。

每一步都能直接回车用默认值，全程也可以随时输 q 跳过。
"""
import datetime
import os
import sys

import config as cfgmod
import i18n
import ui

ONBOARD_VERSION = "1"      # 引导流程改版了就 +1，老用户会再走一遍（依旧可以一路回车）

# 界面文字都过一遍 i18n；查不到译文就原样显示中文
_ = i18n.t


def needed(cfg):
    """这次启动要不要走引导。

    · 没配过（配置文件里没有 onboarded 标记）→ 走
    · 引导改版了 → 再走一遍
    · MC_NO_ONBOARD=1 或者不是真终端（脚本/管道里）→ 跳过，别卡住脚本
    """
    if os.environ.get("MC_NO_ONBOARD") == "1":
        return False
    if str(cfg.get("onboarded") or "").split(":")[0] == ONBOARD_VERSION:
        return False                      # 已经走过这一版引导了，不再打扰
    if is_configured(cfg):
        return False                      # 老用户（配置里早就有版本/种子了）不折腾他
    if os.environ.get("MC_ONBOARD") == "1":      # 自动化/测试里强制走一遍
        return True
    if not sys.stdin.isatty():
        return False
    return True


def is_configured(cfg):
    """这份配置像不像"已经用过一阵子了"（版本选过 / 种子有过）"""
    return bool(cfg.get("mc")) or cfg.get("seed") is not None


def backfill(cfg, save=None):
    """老版本升上来的：静默补个「引导已走过」的标记，省得突然弹一堆问题"""
    if str(cfg.get("onboarded") or "").split(":")[0] == ONBOARD_VERSION:
        return False
    cfg["onboarded"] = f"{ONBOARD_VERSION}:existing"
    if save:
        save(cfg)
    return True


def _step(n, title):
    print()
    print("  " + ui.s(f"[{n}/5] ", "dim") + ui.s(_(title), "accent"))


def _pick_language(ask, cfg):
    """第一件事：问语言。

    这时候还不知道用哪种语言，所以这一屏本身是双语的。
    """
    default = "1" if i18n.guess_from_system() == "zh" else "2"
    print()
    print(ui.box([
        ui.s("请选择语言  /  Choose your language", "accent"),
        "",
        "    " + ui.s("1", "key") + ") 中文",
        "    " + ui.s("2", "key") + ") English",
    ], title="欢迎 / Welcome"))
    raw = ask(f"  语言 / Language [{default}]: ", default=default, allow_empty=True)
    answer = str(raw or default).strip().lower()
    code = "en" if answer in ("2", "en", "english", "英文") else "zh"
    i18n.set_lang(code)
    cfg["lang"] = code
    return code


def _pick_version(ask, cfg, versions):
    """选游戏版本：支持的直接输编号，别的版本手输版本号"""
    versions = versions or []
    cur = cfg.get("mc") or (versions[-1] if versions else "1.21.10")
    if versions:
        lines = []
        for i, v in enumerate(versions, 1):
            lines.append(f"{i:>2}) {v}")
        # 一行四个，省得刷屏
        for i in range(0, len(lines), 4):
            print("    " + "   ".join(lines[i:i + 4]))
        print("    " + ui.s(_("（这 {n} 个版本包里都带现成模组；别的版本也能用，就是要自己编模组）",
                              n=len(versions)), "hint"))
    raw = ask(f"  {_('版本编号（或直接输版本号）')}[{cur}]: ", default=cur)
    raw = (raw or "").strip()
    if raw.isdigit() and versions and 1 <= int(raw) <= len(versions):
        return versions[int(raw) - 1]
    return raw or cur


def _pick_save(ask, cfg):
    """下载器把存档存哪儿了（可选，以后算种子要用）"""
    cur = cfg.get("save") or ""
    hint = _("存档目录（下载器存出来的那个文件夹，里面是 level.dat）")
    skip = _("先不填（回车跳过）")
    raw = ask(f"  {hint}[{cur or skip}]: ", allow_empty=True)
    raw = (raw or "").strip()
    if not raw:
        return cur
    path = cfgmod.adapt_path(raw)
    if not os.path.exists(path):
        print("    " + ui.warn(_("这个路径现在不存在 —— 先记下了，之后可以改（主菜单 3）")))
    else:
        has_level = os.path.isfile(os.path.join(path, "level.dat"))
        print("    " + (ui.ok(_("看着对，里面有 level.dat"))
                        if has_level else
                        ui.warn(_("路径在，但没看到 level.dat —— 可能是上一级目录？"))))
    return path


def _pick_java(ask, cfg):
    """Java：先自动找，找不到就让用户填（完整版自带的那份会被自动认出来）"""
    found = cfgmod.find_java()
    if found:
        major = cfgmod.check_java(found) or "?"
        print("    " + ui.ok(_("自动找到了 Java {major}：{path}",
                              major=major, path=ui.fit(found, 52))))
        raw = ask(f"  {_('就用它吗？')}[Y/n]: ", default="y")
        if (raw or "y").strip().lower() not in ("n", "no", "不"):
            return found
    else:
        print("    " + ui.warn(_("没自动找到 Java（算种子/查结构要用它）")))
        for line in cfgmod.java_hint().splitlines():
            print("    " + ui.s(line, "hint"))
    raw = ask(f"  {_('Java 路径（不想填就回车）')}[{cfg.get('java') or _('空')}]: ", allow_empty=True)
    raw = (raw or "").strip()
    if not raw:
        return cfg.get("java")
    path = cfgmod.adapt_path(raw)
    major = cfgmod.check_java(path)
    if major:
        print("    " + ui.ok(_("这个 Java 能跑（Java {major}）", major=major)))
        return path
    print("    " + ui.err(_("这个 java 跑不起来（路径不对 / 版本太老 / 不是本系统的版本）")))
    return cfg.get("java")


def run(ask, cfg, versions=None, save=None):
    """走一遍首次启动引导。

    ask  —— 问一句拿一个答案，签名跟 tool.ask 一样（(提示, 默认值) -> 字符串）
    save —— 存配置的函数（一般是 config.save），传了就每步存一次，中途关掉也不丢
    """
    # 第一件事永远是问语言 —— 后面所有话都按它来
    if not cfg.get("lang"):
        _pick_language(ask, cfg)
        if save:
            save(cfg)

    print()
    print(ui.box([
        ui.s(_("第一次用，先花半分钟把这几样配一下"), "accent"),
        "",
        ui.s(_("配置文件放在本地（.mc-tool.json），包里默认一份都不带 ——"), "hint"),
        ui.s(_("种子、存档路径这些只存在你自己电脑上。"), "hint"),
        "",
        ui.s(_("每一步都能直接回车用默认值，也可以随时输 q 跳过；"), "hint"),
        ui.s(_("以后想改：主菜单 3【设置】。"), "hint"),
    ], title=_("欢迎用 MC 种子工具包")))
    print()
    if (ask(f"  {_('现在配一下吗？')}[Y/n]: ", default="y") or "y").strip().lower() in ("n", "no", "不", "q"):
        print("  " + ui.info(_("那先跳过 —— 配置是空的，用到的时候工具会再问你")))
        cfg["onboarded"] = f"{ONBOARD_VERSION}:skipped"
        if save:
            save(cfg)
        return cfg

    # ① 游戏版本
    _step(1, "你玩哪个版本？（决定结构怎么生成、群系怎么判）")
    print("    " + ui.s(_("不确定就用默认（列表里最新那个）—— 以后随时能在设置里改"), "hint"))
    cfg["mc"] = _pick_version(ask, cfg, versions)
    if save:
        save(cfg)

    # ② 存档目录（可选）
    _step(2, "下载器存出来的存档在哪儿？（可选）")
    print("    " + ui.s(_("用来从存档反推种子。现在不知道也没事，回车跳过。"), "hint"))
    cfg["save"] = _pick_save(ask, cfg)
    if save:
        save(cfg)

    # ③ Java
    _step(3, "Java（算种子和查结构要用）")
    cfg["java"] = _pick_java(ask, cfg)
    if save:
        save(cfg)

    # ④ 更新通道
    _step(4, "更新通道")
    print("    " + ui.s(_("1) 稳定版　只给你测试过、确认没问题的版本（推荐）"), "hint"))
    print("    " + ui.s(_("2) 测试版　新功能先到手，但也可能碰到半成品"), "hint"))
    raw = ask(f"  {_('选哪个？')}[{_('当前')}={cfg.get('channel') or 'stable'}]: ", allow_empty=True)
    if (raw or "").strip():
        cfg["channel"] = "beta" if raw.strip() in ("2", "beta", "测试", "测试版") else "stable"
    if save:
        save(cfg)

    # ⑤ 界面里要不要明文显示种子
    _step(5, "界面里要不要明文显示种子？（默认打码）")
    print("    " + ui.s(_("打码是为了截图 / 录屏时不把种子漏出去，你自己看的时候也能再按一下显示"), "hint"))
    raw = ask(f"  {_('明文显示？')}[{'y' if cfg.get('show_seed') else 'N'}]: ", allow_empty=True)
    if (raw or "").strip():
        cfg["show_seed"] = raw.strip().lower().startswith("y")

    cfg["onboarded"] = f"{ONBOARD_VERSION}:{datetime.datetime.now():%Y-%m-%d %H:%M}"
    if save:
        save(cfg)

    print()
    print(ui.box([
        ui.s(_("配好了，就这么用："), "accent"),
        "",
        "  " + ui.s("1", "key") + " " + _("计算种子    —— 从下载的存档反推世界种子"),
        "  " + ui.s("2", "key") + " " + _("计算结构    —— 用种子查海底神殿、末地城…"),
        "  " + ui.s("3", "key") + " " + _("设置        —— 上面几项随时能改"),
        "",
        ui.s(_("第一次建议先走一遍 1，算出来的种子会存下来。"), "hint"),
        ui.s(_("配置在：{path}", path=ui.fit(cfgmod.CONFIG_PATH, 48)), "hint"),
    ], title=_("完成")))
    return cfg
