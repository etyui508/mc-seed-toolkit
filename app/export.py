#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把查询结果导出：复制到剪贴板 / 存成 txt json / 生成 mcfunction。

结果从哪来：engine.run_and_log 每跑完一条查询，会往 记录/结果.jsonl 追加一行
（时间、说明、完整输出）。这里读它，所以"导出上一次结果"不用重跑查询。

命令行：
  python3 app/export.py --last 1 --format txt          # 导出最近 1 条
  python3 app/export.py --last 3 --format mcfunction   # 生成可执行的传送脚本
  python3 app/export.py --last 1 --format clip         # 直接复制到剪贴板
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RESULTS = os.path.join(ROOT, "记录", "结果.jsonl")
EXPORT_DIR = os.path.join(ROOT, "记录", "导出")

sys.path.insert(0, HERE)
import i18n                                            # noqa: E402

# 导出时给用户看的提示都过一遍语言表（查不到就原样显示中文）
_ = i18n.t


def load(n=1):
    """读最近 n 条结果（新的在前）"""
    rows = []
    try:
        with open(RESULTS, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        return []
    return rows[-n:] if n > 0 else rows


def parse_gotos(text):
    """从结果文本里把 goto 坐标抠出来（附带那一行的说明）"""
    out = []
    dim = "主世界"
    for line in str(text).splitlines():
        # 结果里维度是单独一行的标题（[主世界] / [下界] / [末地]），后面各行都属它
        head = re.match(r"^\s*\[([^\]]+)\]", line)
        if head:
            tag = head.group(1)
            for name in ("下界", "末地", "主世界"):
                if name in tag:
                    dim = name
                    break
        m = re.search(r"goto\s+(-?\d+)\s+(-?\d+)", line)
        if not m:
            # 有些结果没有 goto，只有坐标：史莱姆是"方块中心 (x,z)"，
            # 引擎原始输出是"方块 (x,z)"
            m = re.search(r"方块(?:中心)?\s*\((-?\d+),(-?\d+)\)", line)
        if not m:
            continue
        x, z = int(m.group(1)), int(m.group(2))
        note = re.sub(r"^\s*\d+[\.、]\s*", "", line).strip()
        out.append({"x": x, "z": z, "dim": dim, "note": note})
    return out


def as_text(rows):
    parts = []
    for r in rows:
        parts.append(f"===== {r.get('time','')}  {r.get('label','')} =====\n{r.get('text','')}")
    return "\n".join(parts).rstrip() + "\n"


def as_json(rows):
    return json.dumps([{"time": r.get("time"), "label": r.get("label"),
                        "points": parse_gotos(r.get("text", "")),
                        "text": r.get("text", "")} for r in rows],
                      ensure_ascii=False, indent=2) + "\n"


def as_mcfunction(rows, name="mcseed"):
    """生成 .mcfunction：丢进存档的 datapacks 里，/function 就能直接飞过去。

    用 tp 而不是 /execute in ... run tp —— 保持简单，跨维度自己切一下。
    每条前面加个 tellraw，到了会看到这是什么地方。
    """
    lines = [_("# MC 种子工具包导出 {when}",
               when=f"{datetime.datetime.now():%Y-%m-%d %H:%M}"),
             _("# 用法：放到 <存档>/datapacks/mcseed/data/<命名空间>/functions/mcseed.mcfunction"),
             _("#       然后在游戏里 /reload 之后执行 /function <命名空间>:mcseed"), ""]
    total = 0
    for r in rows:
        pts = parse_gotos(r.get("text", ""))
        if not pts:
            continue
        lines.append(f"# {r.get('label','')}  （{r.get('time','')}）")
        for pt in pts:
            total += 1
            note = pt["note"].replace('"', "'")[:70]
            lines.append(f'tellraw @s {{"text":"[{pt["dim"]}] {note}","color":"aqua"}}')
            lines.append(f"tp @s {pt['x']} ~ {pt['z']}")
        lines.append("")
    if not total:
        return None
    return "\n".join(lines) + "\n"


def copy_to_clipboard(text):
    """复制到剪贴板。Windows 用 clip，WSL 用 clip.exe，Linux 试 xclip/wl-copy。"""
    candidates = []
    if os.name == "nt":
        candidates = [["clip"]]
    else:
        if os.path.exists("/mnt/c/Windows/System32/clip.exe"):     # WSL
            candidates.append(["/mnt/c/Windows/System32/clip.exe"])
        for cmd in (["xclip", "-selection", "clipboard"], ["xsel", "-ib"],
                    ["wl-copy"], ["pbcopy"]):
            candidates.append(cmd)
    for cmd in candidates:
        try:
            p = subprocess.run(cmd, input=text.encode("utf-8"),
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
            if p.returncode == 0:
                return True, " ".join(os.path.basename(c) for c in cmd[:1])
        except (OSError, subprocess.SubprocessError):
            continue
    return False, _("没找到能用的剪贴板命令")


def save(content, suffix):
    os.makedirs(EXPORT_DIR, exist_ok=True)
    path = os.path.join(EXPORT_DIR, f"{datetime.datetime.now():%Y%m%d-%H%M%S}{suffix}")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return path


def as_map(rows):
    """画成 SVG 地图（按维度分栏，各自用自己的比例尺）"""
    import map as mapmod                          # 延迟导入，免得和 map.py 绕圈
    points = mapmod.collect(rows)
    return mapmod.build(points) if points else None


FORMATS = {
    "txt": (as_text, ".txt"),
    "json": (as_json, ".json"),
    "mcfunction": (as_mcfunction, ".mcfunction"),
    "map": (as_map, ".svg"),
}


def do_export(rows, fmt):
    """返回 (成功?, 说明, 路径或内容)"""
    if not rows:
        return False, _("还没有查询记录（先跑一条查询）"), None
    if fmt == "clip":
        text = as_text(rows)
        ok, how = copy_to_clipboard(text)
        return ok, (_("已复制到剪贴板（{how}）", how=how) if ok else how), text
    fn, suffix = FORMATS[fmt]
    content = fn(rows)
    if not content:
        return False, _("这些结果里没有可导出的坐标"), None
    path = save(content, suffix)
    return True, _("已导出 {path}", path=os.path.relpath(path, ROOT)), path


def main():
    p = argparse.ArgumentParser(description=_("导出 / 复制查询结果"))
    p.add_argument("--last", type=int, default=1, help=_("导出最近几条（默认 1）"))
    p.add_argument("--format", default="txt",
                   choices=["txt", "json", "mcfunction", "map", "clip"])
    p.add_argument("--list", action="store_true", help=_("看看有哪些结果"))
    a = p.parse_args()
    if a.list:
        rows = load(0)
        print(_("共 {n} 条查询记录：", n=len(rows)))
        for r in rows[-20:]:
            print(f"  {r.get('time','')}  {r.get('label','')}")
        return 0
    rows = load(a.last)
    ok, msg, _extra = do_export(rows, a.format)
    print(("✅ " if ok else "❌ ") + msg)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
