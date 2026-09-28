#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MC 多功能工具（一体的）：
  1) 计算种子 —— 用 Simple World Downloader 下的存档 + 模组观测，把世界种子算出来
  2) 计算结构 —— 用种子算各种结构的坐标（海底神殿/末地城/要塞/史莱姆农场…）

两个模式共用一份配置（种子 / 版本 / 存档路径），存在 .tool-config.json 里，
所以算完种子之后，结构计算器会自动用上它。
"""
import importlib
import datetime
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))          # app/ 目录
ROOT = os.path.dirname(HERE)                               # 工具包根目录
sys.path.insert(0, HERE)
import config as cfgmod
import agreement
import i18n
import onboard
import diag
import export
import mcvers
import ui
import updater
DEFAULT_OBS = ""
VERSIONS = mcvers.MILESTONES

# 界面文字都过一遍 i18n；查不到译文就原样显示中文
_ = i18n.t


def load_config():
    return cfgmod.load()


def save_config(cfg):
    cfgmod.save(cfg)


def banner(cfg):
    java = cfgmod.find_java()
    if java:
        major = cfgmod.check_java(java)
        java_text = f"Java {major}  ({java})" if major else java
    else:
        java_text = ui.warn(_("没找到能用的 Java —— 选 1 之前先在【设置】里填，或用 run.sh 启动"))
    seed = cfgmod.mask(cfg.get("seed"), cfg.get("show_seed"))
    ch = updater.channel()
    ver_text = updater.local_version()
    if ch != "stable" and not updater.is_prerelease(ver_text):
        ver_text += " " + ch            # 版本号自己带 -beta 时就不用再标一次
    print()
    print(ui.banner(_("MC 种子工具包"), _("从下载的存档破出世界种子，再用种子算结构坐标"),
                    version=ver_text))
    print(ui.kv([
        (_("种子"), ui.s(seed, "val")),
        (_("版本"), ui.s(cfg["mc"] or _("（还没选）"), "val")),
        (_("存档"), ui.s(ui.fit(cfg["save"] or _("（还没设）"), 46), "val")),
        ("Java", java_text),
    ], key_width=6, gap=1))


def ask(prompt, default=None, allow_empty=False):
    raw = input(ui.prompt_char() + prompt).strip()
    if not raw:
        if default is not None:
            return default
        if allow_empty:
            return ""
        return None
    return raw


def pad_name(text, width=16):
    """版本号那一列对齐用（中文/英文混排也不会歪）"""
    return ui.pad(ui.s(text, "val"), width)


# 我们准备好模组的版本（兜底用：万一本地的 mods/ 里没有版本文件夹，
# 也要能把列表显示出来，不能让用户看到一个空菜单）
BUILTIN_VERSIONS = [
    "1.16.5", "1.17.1", "1.18.2", "1.19.4",
    "1.20.1", "1.20.2", "1.20.4", "1.20.5", "1.20.6",
    "1.21", "1.21.1", "1.21.2", "1.21.3", "1.21.4", "1.21.5",
    "1.21.6", "1.21.7", "1.21.8", "1.21.9", "1.21.10", "1.21.11",
]


def supported_versions():
    """我们真的准备好模组的游戏版本 —— 就是 mods/ 下那些版本文件夹。
    选这些版本的人，模组现成就能拿；选别的版本就只能自己编模组了。"""
    import re as _re
    mods = os.path.join(ROOT, "mods")
    out = []
    try:
        for name in os.listdir(mods):
            if _re.match(r"^\d+\.\d+", name) and os.path.isdir(os.path.join(mods, name)):
                out.append(name)
    except OSError:
        pass
    if not out:
        # 本地没有版本文件夹（更新时没写进去？）就退回内置列表，
        # 至少让用户看到"支持哪些版本"，而不是一个空的菜单
        return list(BUILTIN_VERSIONS), False

    def key(v):
        parts = _re.findall(r"\d+", v)[:3]
        return tuple(int(x) for x in parts) + (0,) * (3 - len(parts))
    return sorted(out, key=key), True


def version_list_text(vs, local=True, columns=4):
    """把支持的版本摆成一个带编号的列表（编号就是"输这个数字就选它"）"""
    if not vs:
        return []
    lines = []
    row = []
    for i, v in enumerate(vs, 1):
        cell = ui.s(f"{i:2d}", "key") + " " + pad_name(v, 10)
        row.append(cell)
        if i % columns == 0:
            lines.append("  " + "".join(row))
            row = []
    if row:
        lines.append("  " + "".join(row))
    return lines


def print_version_list(vs, local=True, columns=4):
    """把"我们准备好模组的版本"打出来，顺便说明编号怎么用"""
    lines = version_list_text(vs, local, columns)
    if not lines:
        return
    print("  " + ui.info(_("这 {n} 个版本包里都带现成模组，输编号选：", n=len(vs))))
    if not local:
        print("  " + ui.warn(_("（本地 mods/ 里没找到版本文件夹 —— 这份列表是内置的；"
                              "模组可能没下全，去 记录/日志.txt 看看）")))
    for line in lines:
        print(line)


def ask_version(cfg, default="1.21.10"):
    """让用户选游戏版本：支持的直接输编号，别的版本手输版本号也行"""
    vs, local = supported_versions()
    print()
    print("  " + ui.section("选游戏版本（影响结构生成和群系判定）"))
    print_version_list(vs, local)
    if vs:
        print()
    print("  " + ui.info("其它版本也能用 —— 直接输版本号（比如 1.19.2），"))
    print("  " + ui.info("但模组得自己编：python3 tools/build-mods.py --only-seedhelper <版本>"))
    print()
    raw = ask(f"版本编号或版本号 [当前 {cfg.get('mc') or default}]: ",
              default=cfg.get("mc") or default)
    if raw and raw.isdigit() and vs and 1 <= int(raw) <= len(vs):
        return vs[int(raw) - 1]
    return raw or default


def print_version_summary(ver):
    """把 mcvers 的一行版本说明染个色：✓ 绿的，✗ 红的，≈ 黄的"""
    parts = mcvers.summary_line(ver).split()
    if not parts:
        return ver
    out = [ui.s(ui.pad(parts[0], 16), "val")]
    for bit in parts[1:]:
        if "✗" in bit:
            out.append(ui.s(bit, "err"))
        elif "≈" in bit:
            out.append(ui.s(bit, "warn"))
        else:
            out.append(ui.s(bit, "ok"))
    return "  ".join(out)


def do_seed(cfg):
    print()
    print(ui.section("计算种子 · 需要 Simple World Downloader 下出来的存档"))
    print("  " + ui.info("存档目录里要有 region/；末地中央岛一定要下到（那是 16 bit 的关键信号）"))
    print()
    save = ask(f"存档目录 [默认 {cfg['save'] or '无'}]: ", default=cfg["save"])
    if not save:
        print(ui.warn("没给存档目录，取消。"))
        return
    save = cfgmod.adapt_path(save)
    if not os.path.isdir(save):
        print(ui.err(f"目录不存在: {save}"))
        return

    # 模组观测文件（史莱姆区块 + 哈希种子）：配置里没有就自动去存档附近翻一遍
    auto_obs = cfg.get("obs") or cfgmod.find_observations(save) or DEFAULT_OBS
    obs = ask(f"模组观测文件（没有就直接回车跳过）[默认 {auto_obs or '跳过'}]: ",
              default=auto_obs, allow_empty=True)
    obs = cfgmod.adapt_path(obs) if obs else ""
    if obs and not os.path.exists(obs):
        print(ui.warn(f"找不到 {obs}"))
        print("  " + ui.info("这次只算到低 48 位（算结构够用，但不是完整 64 位种子）"))
    elif not obs:
        print("  " + ui.info("跳过观测文件 → 这次只算低 48 位"))
    use_hash = ask("用模组的哈希种子吗（用它才能出完整 64 位种子）? [Y/n]: ", default="y").lower() != "n"

    cmd = [sys.executable, os.path.join(HERE, "calc_seed.py"), save]
    if obs:
        cmd += ["--obs", obs]
    if not use_hash:
        cmd.append("--no-hash")
    print()
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    rc = subprocess.run(cmd, env=env).returncode
    cfg["save"] = save
    cfg["obs"] = obs
    # calc_seed.py 会把算出来的种子直接写进配置文件；
    # 这里重新读一遍，主菜单/结构计算器立刻就能用，不用退出重开。
    try:
        fresh = load_config()
        if fresh.get("seed") is not None:
            cfg["seed"] = fresh["seed"]
        if fresh.get("mc") and not cfg.get("mc"):
            cfg["mc"] = fresh["mc"]
        if fresh.get("java"):
            cfg["java"] = fresh["java"]
    except Exception:
        pass
    save_config(cfg)
    if rc != 0:
        print("\n" + ui.warn(f"计算过程出错了（退出码 {rc}）—— 上面最后几行就是原因。"))
    elif cfg.get("seed") is None:
        print("\n" + ui.warn("这次没解出完整种子（上面有原因）。只要低 48 位也够算结构。"))
    else:
        print("\n" + ui.ok("种子已保存：" + ui.s(cfgmod.mask(cfg["seed"], cfg.get("show_seed")), "val")
                          + "  —— 现在直接选 2 就能算结构了"))
    print("  " + ui.info("结果也写进了 记录/算种子记录.txt"))


def do_structure(cfg):
    # 首次进来：先要种子，再要版本
    if not cfg.get("seed"):
        print()
        print(ui.section("计算结构"))
        print("  " + ui.warn("这一步需要先有种子。"))
        print("  " + ui.info("还没算过种子 —— 建议先回主菜单选 1（算种子），算完会自动存下来。"))
        raw = ask("  或者手动输入种子: ", allow_empty=True)
        if not raw:
            print("  " + ui.info("那就先去算种子吧。"))
            return
        try:
            cfg["seed"] = int(raw)
            save_config(cfg)
        except ValueError:
            print("  " + ui.err("这不是个整数种子。"))
            return
    if not cfg.get("mc"):
        cfg["mc"] = ask_version(cfg)
        save_config(cfg)
        print()
        print("  " + print_version_summary(cfg["mc"]))
        f = mcvers.features(cfg["mc"])
        if f.get("note"):
            print("  " + ui.warn(f["note"]))

    print()
    print(ui.section("结构计算"))
    print("  " + ui.kv([("种子", ui.s(cfgmod.mask(cfg["seed"], cfg.get("show_seed")), "val")),
                        ("版本", ui.s(cfg["mc"], "val")),
                        ("记录", ui.s("记录/坐标记录.txt", "dim"))], key_width=4, gap=1))
    print()
    # 把种子 / 版本交给全局状态，结构模块都从这里读
    import state
    state.setup(seed=int(cfg["seed"]), show_seed=cfg.get("show_seed"), ver=cfg.get("mc"))
    os.environ["MCVER"] = str(cfg["mc"])
    calc = importlib.import_module("calc")
    while calc.menu():
        print()
    print(ui.info(f"记录文件：{os.path.join(ROOT, '记录', '坐标记录.txt')}"))


def do_settings(cfg):
    print()
    print(ui.section(_("设置（直接回车 = 这一项不改）")))
    # 语言放第一项：改完后面的话立刻就跟着换
    langs = i18n.available()
    listing = "   ".join(f"{i}) {name}" for i, (_, name) in enumerate(langs, 1))
    raw_lang = ask(f"  语言 / Language   {listing}   [{i18n.lang_name(i18n.current())}]: ",
                   allow_empty=True)
    raw_lang = (raw_lang or "").strip()
    picked = None
    if raw_lang.isdigit() and 1 <= int(raw_lang) <= len(langs):
        picked = langs[int(raw_lang) - 1][0]
    elif raw_lang.lower() in [c for c, _ in langs]:
        picked = raw_lang.lower()
    if picked and picked != i18n.current():
        i18n.set_lang(picked)
        cfg["lang"] = picked
        save_config(cfg)
        print("  " + ui.ok(_("语言已切换：{name}", name=i18n.lang_name(picked))))
    print()
    raw = ask(f"{_('种子')} [{cfg['seed'] or _('空')}]: ", allow_empty=True)
    if raw:
        try:
            cfg["seed"] = int(raw)
        except ValueError:
            print("  " + ui.warn(_("种子必须是整数，忽略")))
    # 支持哪些版本直接摆出来 —— 不然"输编号选"这四个字等于没说
    vs, local = supported_versions()
    print()
    if vs:
        print("  " + ui.s(_("支持的游戏版本（模组现成）"), "accent")
              + ui.s("    " + _("现在选的是 {v}", v=cfg['mc'] or _("空")), "hint"))
        print_version_list(vs, local)
    else:
        print("  " + ui.warn(_("本地 mods/ 里没找到版本文件夹 —— 手输版本号也行")))
    print()
    raw = ask(f"{_('版本（回车不改 / 输编号选上面的 / 也能直接输版本号）')}"
              f"[{cfg['mc'] or _('空')}]: ", allow_empty=True)
    if raw:
        if raw.isdigit() and vs and 1 <= int(raw) <= len(vs):
            cfg["mc"] = vs[int(raw) - 1]
            print("  " + ui.ok(_("选的是 {v}（模组在 mods/{v}/ 里现成的）", v=cfg['mc'])))
        else:
            cfg["mc"] = raw
            if vs and raw not in vs:
                print("  " + ui.warn(_("{v} 我们没准备模组 —— 要用得自己编", v=raw))
                      + f"（tools/build-mods.py --only-seedhelper {raw}）")
            else:
                print("  " + ui.ok(_("版本记成 {v}", v=cfg['mc'])))
    raw = ask(f"{_('存档目录')} [{cfg['save'] or _('空')}]: ", allow_empty=True)
    if raw:
        cfg["save"] = raw
    raw = ask(f"{_('模组观测文件')} [{cfg['obs'] or _('空')}]: ", allow_empty=True)
    if raw:
        cfg["obs"] = raw
    cur_java = cfg.get("java") or cfgmod.find_java() or _("没找到")
    raw = ask(f"{_('Java 路径（跑破解/查结构要用）')}[{cur_java}]: ", allow_empty=True)
    if raw:
        cfg["java"] = cfgmod.adapt_path(raw)
        major = cfgmod.check_java(cfg["java"])
        if major:
            print("  " + ui.ok(_("这个 Java 能跑（Java {major}）", major=major)))
        else:
            print("  " + ui.err(_("这个 java 跑不起来（路径不对 / 版本太老 / 不是本系统的版本）")))
            print("    " + cfgmod.java_hint().replace("\n", "\n    "))
            cfg["java"] = None
    raw = ask(_("界面里显示完整种子？现在={now}", now=_(("是" if cfg.get("show_seed") else "否")))
              + " [y/N]: ", allow_empty=True)
    if raw:
        cfg["show_seed"] = raw.lower().startswith("y")
    cur = updater.channel()
    raw = ask(f"{_('更新通道')} 1) {_('稳定版')}  2) {_('测试版')} "
              f"[{_('当前')}={_(updater.CHANNEL_NAMES.get(cur, cur))}]: ", allow_empty=True)
    if raw:
        if raw.strip() in ("2", "beta", "测试版", "测试"):
            cfg["channel"] = "beta"
            print("  " + ui.warn(_("已切成测试版 —— 新功能会先给你，但也可能遇到半成品，"
                                   "出问题用主菜单 5 反馈")))
        else:
            cfg["channel"] = "stable"
            print("  " + ui.ok(_("已切回稳定版")))
    save_config(cfg)
    print(ui.ok(_("已保存到 {path}", path=cfgmod.CONFIG_PATH)))
    print("  " + ui.info(_("界面上要显示完整种子的话，下一项答 y")))


def startup_update(man=None, msg=""):
    """启动时的检查：有新版就把面板摆出来问一句，同意才下载替换。

    · 脚本/管道里（不是真终端）→ 保持老样子静默自动更新，问了也没人答
    · MC_NO_UPDATE_ASK=1       → 同样静默自动更新
    · MC_NO_UPDATE=1           → 连检查都不做
    """
    if os.environ.get("MC_NO_UPDATE") == "1":
        return
    if updater.auto_update_enabled():
        updater.maybe_update()
        return
    if not man and not msg:                 # 没在开屏动画里查过，这里补查一次
        man, msg = updater.check()
    if not man:                        # 没新版 / 连不上：安静
        if msg and "已经是最新" not in msg:
            diag.log("更新检查", 结果=msg)
        return
    update_panel(man)
    print()
    answer = (ask("现在更新吗？[Y/n]（n = 这次先不更新，下次启动还会问）: ",
                  default="y") or "y").strip().lower()
    if answer in ("n", "no", "不"):
        print("  " + ui.info("那这次先不更新。想手动更新：主菜单选 4"))
        diag.log("用户选择暂不更新", 新版本=man.get("version"))
        return
    changed, m = updater.update(verbose=True)
    print("  " + (ui.ok(m) if changed else ui.info(m or "没有更新")))
    diag.log("启动时更新", 结果=m, 成功=changed)
    if changed:
        if (sys.stdin.isatty()
                and (ask("更新完成。现在就用新版重启吗？[Y/n]: ", default="y") or "y").lower() != "n"
                and updater.restart_into_new_version()):
            return
        print("  " + ui.info("关掉再开一次就是新版了；完整 diff 在 记录/更新日志/"))


def update_panel(man):
    """把"有新版本"这件事摆成一个面板：版本、更新说明、这次改哪些文件"""
    local = updater.local_version()
    ch = updater.channel()
    lines = [ui.s(_("当前版本"), "dim") + " " + ui.s(local, "val")
             + "    " + ui.s(_("新版本"), "dim") + " " + ui.s(man.get("version"), "key")
             + "   " + ui.s(_("（{ch}通道）",
                              ch=_(updater.CHANNEL_NAMES.get(ch, ch))), "dim"), ""]
    if man.get("notes"):
        lines.append(ui.s(_("更新说明"), "accent"))
        # 发布说明可能是双语写在一起的（"中文 / English"）：按当前语言只显示对应那半
        for row in (i18n.pick_notes(man) or "").splitlines() or [""]:
            lines.append("  " + ui.fit(row, 56))
        lines.append("")
    plan_now = updater.plan(man)
    desc = updater.describe(plan_now, limit=5)
    lines.append(ui.s(_("这次会改这些"), "accent"))
    for row in desc:
        lines.append("  " + ui.fit(row, 56))
    lines.append("")
    lines.append(ui.s(_("更新时每个文件都会列出改了多少行，完整 diff 存到"), "hint"))
    lines.append(ui.s(_("记录/更新日志/。你的种子、坐标记录、自带 Java 都不会被动。"), "hint"))
    if man.get("url_backup"):
        lines.append(ui.s(_("下载走主站（GitHub），连不上自动换备用站。"), "hint"))
    print()
    print(ui.box(lines, title=_("发现新版本")))


def do_update():
    """联网看一眼下载站有没有新版本"""
    local = updater.local_version()
    ch = updater.channel()
    print()
    print(ui.section("检查更新"))
    print("  " + ui.kv([("本地版本", ui.s(local, "val")),
                        ("更新通道", ui.s(updater.CHANNEL_NAMES.get(ch, ch), "val")
                         + ui.s(f"（{ch}）", "dim"))], gap=1))
    man, msg = updater.check()
    print("  " + (ui.ok(msg) if man else ui.info(msg)))
    if not man:
        return
    print("  " + ui.kv([("主站", ui.s(man.get("url") or man.get("zip") or "-", "val")),
                        ("备用", ui.s(man.get("url_backup") or "（没有）", "dim"))], gap=1))
    if man.get("url_backup"):
        print("  " + ui.s("  主站（GitHub）连不上会自动走备用站，两边内容一样、都带签名", "hint"))
    if man.get("notes"):
        print("  " + ui.kv([("更新说明", man["notes"])], gap=1))
    # 下载之前就把差异摆出来 —— 让人知道到底改了什么再决定
    print()
    print("  " + ui.section("这次会改这些"))
    for line in updater.describe(updater.plan(man)):
        print("  " + (ui.s(line, "dim") if line.startswith("  ") else line))
    print()
    if ask("  现在更新吗 [Y/n]: ", default="y").lower() == "n":
        return
    changed, m = updater.update(verbose=True)
    print("  " + (ui.ok(m) if changed else ui.info(m or "没有更新")))
    if changed:
        print("  " + ui.info("完整代码 diff 存在 记录/更新日志/ 里，想看细节随时翻"))


def do_export():
    """导出 / 复制上一次（或最近几次）的查询结果"""
    print()
    print(ui.section("导出 / 复制结果"))
    rows = export.load(0)
    if not rows:
        print("  " + ui.info("还没有查询记录 —— 先用主菜单 2 查点什么再来"))
        return
    recent = rows[-8:]
    print("  " + ui.info(f"一共 {len(rows)} 条查询记录，最近的是："))
    for r in reversed(recent):
        print("    " + ui.s(r.get("time", ""), "dim") + "  " + r.get("label", ""))
    print()
    n_raw = ask("导出最近几条？（默认 1）: ", default="1", allow_empty=True)
    try:
        n = max(1, int(n_raw or 1))
    except ValueError:
        n = 1
    picks = export.load(n)
    pts = sum(len(export.parse_gotos(r.get("text", ""))) for r in picks)
    print("  " + ui.info(f"这 {len(picks)} 条里有 {pts} 个 goto 坐标"))
    print()
    print(ui.menu("导出成什么", [
        ("1", "复制到剪贴板", "直接粘到聊天框/文档里"),
        ("2", "文本 .txt", "原样存一份"),
        ("3", "数据 .json", "坐标抠出来，给别的脚本用"),
        ("4", "mcfunction", "丢进 datapack 就能 /function 传送"),
        ("5", "地图 .svg", "把这次的点画成图，浏览器打开"),
        ("0", "返回", ""),
    ]))
    print()
    fmt_choice = ask("选一个: ", allow_empty=True)
    fmt = {"1": "clip", "2": "txt", "3": "json", "4": "mcfunction", "5": "map"}.get(fmt_choice or "")
    if not fmt:
        print("  " + ui.info("取消。"))
        return
    ok, msg, _ = export.do_export(picks, fmt)
    print("  " + (ui.ok(msg) if ok else ui.warn(msg)))
    if ok and fmt == "mcfunction":
        print("  " + ui.info("用法：把它放进 <存档>/datapacks/mcseed/data/mcseed/functions/，"))
        print("  " + ui.info("      游戏里 /reload 然后 /function mcseed:mcseed"))


def do_rollback():
    """回滚到更新前的版本（备份是每次更新自动留的）"""
    print()
    print(ui.section("回滚"))
    items = updater.backups()
    if not items:
        print("  " + ui.info("还没有可回滚的备份（更新过一次之后才会留备份）"))
        return
    print("  " + ui.info("每次更新都会把旧文件留在 记录/.update-backup/，所以能倒回去"))
    print()
    rows = []
    for i, (ver, mtime, count) in enumerate(items[:6], 1):
        when = datetime.datetime.fromtimestamp(mtime).strftime("%m-%d %H:%M")
        rows.append((str(i), f"回滚到 {ver}", f"{when} · {count} 个文件"))
    print(ui.menu("选一个版本", rows + [("0", "返回", "")]))
    print()
    pick = ask("选一个: ", allow_empty=True)
    if not pick or not pick.isdigit() or not (1 <= int(pick) <= len(rows)):
        print("  " + ui.info("取消。"))
        return
    ver = items[int(pick) - 1][0]
    if ask(f"确认回滚到 {ver}？回滚后要重启才会生效 [y/N]: ", default="n").lower() != "y":
        print("  " + ui.info("取消。"))
        return
    ok, msg = updater.rollback(ver)
    diag.log("回滚", 目标=ver, 结果=msg, 成功=ok)
    print("  " + (ui.ok(msg) if ok else ui.warn(msg)))
    if ok:
        print("  " + ui.info("关掉再开一次就是那个版本了"))


def do_feedback():
    """反馈问题：写清现象 -> 自动带上日志 -> 提交到反馈站"""
    print()
    print(ui.section("反馈问题"))
    print("  " + ui.info(f"反馈站：{diag.FEEDBACK_URL}"))
    print("  " + ui.info("日志里的种子和路径会自动打码，不会泄露你的存档"))
    print()
    title = ask("一句话说下问题（比如：算种子卡在 93%）：", allow_empty=True)
    if not title:
        print(ui.warn("没写问题描述，取消。"))
        return
    print("  " + ui.info("想详细描述就接着写，写完单独一行打个 . 结束（不想写直接回车）"))
    lines = []
    while True:
        line = ask("详细描述：" if not lines else "          ", allow_empty=True)
        if line is None or not line.strip() or line.strip() == ".":
            break
        lines.append(line)
    body = "\n".join(lines)
    contact = ask("留个联系方式？QQ/群昵称都行（可留空）：", allow_empty=True)
    safe = os.environ.get("MC_FEEDBACK_NO_UPLOAD") == "1"
    if not safe and ask("把日志一起发给作者吗？ [Y/n]: ", default="y").lower() != "n":
        print()
        print("  " + ui.info("正在提交…"))
        ok, msg = diag.submit(title, body, contact)
        print("  " + (ui.ok(msg) if ok else ui.warn(msg)))
        if ok:
            diag.log("提交反馈成功", 标题=title)
            print("  " + ui.info("作者看到会回复你，也可以直接去反馈站看进度"))
            return
        print("  " + ui.info("没关系，下面帮你打包一份，手动发过去也一样"))
    path = diag.bundle()
    diag.log("打包反馈", 文件=path, 标题=title)
    print()
    print(ui.ok(f"打包好了：{path}"))
    print("  " + ui.info(f"把这个文件发到反馈站 {diag.FEEDBACK_URL}，或者直接发给作者"))


def main():
    ui.init_console()          # 输出别攒着：管道里也要一行一行实时出来
    cfg = load_config()
    # 语言：配置里存的优先；第一次用还没存过就按系统区域猜一个
    i18n.set_lang(cfg.get("lang") or i18n.guess_from_system())
    first = cfg.get("seed") is None
    diag.install_excepthook()
    diag.log("启动", 版本=updater.local_version(),
             有种子=(_("有") if cfg.get("seed") else _("无")),
             版本号=cfg.get("mc") or "未选")
    # 开屏动画的进度条不是白转的：启动要等的事（联网查更新）就在这里面干完，
    # 所以条子会真的走到底，走完主菜单立刻就出来。
    need_check = (os.environ.get("MC_NO_UPDATE") != "1"
                  and not updater.auto_update_enabled())
    results = ui.intro(version=updater.local_version(), status=_("正在准备…"),
                       steps=[(_("联网检查更新"), updater.check)] if need_check else None)
    if need_check:
        man, msg = (results[0] if results and results[0] else (None, ""))
        startup_update(man, msg)
    else:
        updater.maybe_update()      # 脚本里 / 明确要求静默的那条路

    # 第一次用（或者协议改版了）：先让人看一遍
    if agreement.needs_accept(cfg):
        if not agreement.show(ask):
            print()
            print(ui.warn(_("那就不往下走了。想再看一遍就重新运行一次。")))
            diag.log("没同意用户协议，退出")
            return
        agreement.mark_agreed(cfg)
        save_config(cfg)
        diag.log("同意用户协议", 版本=agreement.AGREEMENT_VERSION)
        print("  " + ui.ok(_("记下了，以后不再问。")))

    # 第一次用（或者引导改版了）：把版本/存档/Java/更新通道一次问清楚。
    # 包里默认不带配置文件 —— 该配什么、存在哪儿，全由用户自己来。
    if onboard.needed(cfg):
        try:
            vs, _local = supported_versions()
        except Exception:
            vs = []
        onboard.run(ask, cfg, versions=vs, save=save_config)
        diag.log("走完首次引导", 版本=cfg.get("mc") or "未选",
                 通道=cfg.get("channel"), 有Java=("有" if cfg.get("java") else "无"))
        print("  " + ui.ok(_("引导完成，以后启动直接就进主菜单")))
    elif onboard.backfill(cfg, save_config):
        diag.log("老配置：补记引导标记")      # 用过一阵子的老用户，不弹问题
    try:
        while True:
            banner(cfg)
            if first:
                print()
                print("  " + ui.warn(_("第一次用建议先选 1【计算种子】—— 算出来的种子会存下来，"))
                      + "\n  " + ui.warn(_("之后结构计算器直接就能用。")))
            print()
            print(ui.menu(_("主菜单"), [
                ("1", _("计算种子"), _("从下载的存档反推世界种子")),
                ("2", _("计算结构 / 坐标"), _("用种子查海底神殿、末地城…")),
                ("3", _("设置"), _("种子 / 版本 / 路径 / Java")),
                ("4", _("检查更新"), _("联网看有没有新版本")),
                ("5", _("反馈问题"), _("带上日志一键发给作者")),
                ("6", _("用户协议 / 隐私政策"), _("什么时候都不上传什么")),
                ("7", _("导出 / 复制结果"), _("剪贴板 / txt / json / mcfunction")),
                ("8", _("回滚到旧版本"), _("更新出问题了就倒回去")),
                ("0", _("退出"), ""),
            ], footer=_("直接回车 = 退出")))
            print()
            choice = ask(_("选一个: "), allow_empty=True)
            diag.log("菜单选择", 选择=choice)
            if choice in ("0", "", "q", "exit"):
                print("\n" + ui.ok(_("再见~")))
                diag.log("退出")
                return
            if choice == "1":
                do_seed(cfg)
            elif choice == "2":
                do_structure(cfg)
            elif choice == "3":
                do_settings(cfg)
            elif choice == "4":
                do_update()
            elif choice == "5":
                do_feedback()
            elif choice == "6":
                print()
                print(ui.section("用户协议与隐私政策"))
                print(agreement.full_text())
                print()
                print(ui.info(f"当前同意的是 v{agreement.AGREEMENT_VERSION}；"
                              f"文件在 docs/用户协议与隐私政策.md"))
            elif choice == "7":
                do_export()
            elif choice == "8":
                do_rollback()
            else:
                print(ui.err("没这个选项"))
            first = cfg.get("seed") is None
            print()
    except (EOFError, KeyboardInterrupt):
        print("\n再见~")


if __name__ == "__main__":
    main()
