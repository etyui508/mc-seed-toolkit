#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 app/lang/_part-*.json 合并进 app/lang/en.json。

并行翻译时每个人写自己的片段文件（免得抢同一个 en.json），最后用这个脚本合并：

    python3 tools/merge-i18n-parts.py            # 检查 + 合并
    python3 tools/merge-i18n-parts.py --dry-run  # 只看会改什么
    python3 tools/merge-i18n-parts.py --clean    # 合并完把片段文件删掉

会检查三件事：
  · 片段之间 / 与 en.json 有没有**同名不同译文**的冲突（有就报错退出，不改文件）；
  · 每条 key 能不能在源码里找到（找不到的是错别字或已经改过的文案，会列出来）；
  · 占位符是不是对得上（中文里 {x}，英文里也得有 {x}）。
"""
import argparse
import ast
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
APP = os.path.join(ROOT, "app")
LANG = os.path.join(APP, "lang")
TARGET = os.path.join(LANG, "en.json")

PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def source_strings():
    """源码里出现过的所有中文字符串（含 docstring，宽松一点，只用来做存在性检查）"""
    found = set()
    for root, _dirs, files in os.walk(APP):
        for name in files:
            if not name.endswith(".py"):
                continue
            try:
                tree = ast.parse(open(os.path.join(root, name), encoding="utf-8").read())
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    found.add(node.value)
    return found


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--clean", action="store_true")
    ap.add_argument("--json", dest="as_json", action="store_true")
    args = ap.parse_args()

    parts = sorted(f for f in os.listdir(LANG)
                   if f.startswith("_part-") and f.endswith(".json"))
    if not parts:
        print("没有 _part-*.json，什么都没做")
        return 0

    target = load(TARGET) if os.path.isfile(TARGET) else {}
    merged = dict(target)
    conflicts, added, same = [], 0, 0
    for name in parts:
        data = load(os.path.join(LANG, name))
        for k, v in data.items():
            if not isinstance(v, str) or not v:
                continue
            if k in merged:
                if merged[k] == v:
                    same += 1
                else:
                    conflicts.append((name, k, merged[k], v))
                continue
            merged[k] = v
            added += 1

    # 占位符对不上会觉得"翻译对了但显示成中文"（i18n 会退回原文），所以先查出来
    ph_bad = []
    for k, v in merged.items():
        if sorted(PLACEHOLDER.findall(k)) != sorted(PLACEHOLDER.findall(v)):
            ph_bad.append((k, v))

    src = source_strings()

    def in_source(key):
        if key in src:
            return True
        # 带前缀的 key（log:启动 / ui:xxx 这种）只查前缀后面的原文
        if ":" in key and key.split(":", 1)[1] in src:
            return True
        # 日志字段值这类会被拼进别的字符串里，宽松点：子串出现过就算
        if ":" in key:
            tail = key.split(":", 1)[1]
            if tail and any(tail in s for s in src):
                return True
        # 源码里带占位符的 f-string 拆成了 _("...{x}...", x=...)，按骨架再找一次
        skeleton = PLACEHOLDER.sub("{}", key)
        return any(PLACEHOLDER.sub("{}", s) == skeleton for s in src)

    orphans = [k for k in merged if not in_source(k)]

    if conflicts:
        print(f"!! {len(conflicts)} 条同名不同译文，先自己对齐再合并：")
        for name, k, old, new in conflicts:
            print(f"   [{name}] {k!r}\n      已有: {old!r}\n      新的: {new!r}")
    if ph_bad:
        print(f"!! {len(ph_bad)} 条占位符对不上（会退回中文）：")
        for k, v in ph_bad[:20]:
            print(f"   {k!r} -> {v!r}")
    if orphans:
        print(f"?? {len(orphans)} 条译文在源码里找不到原文（多半是改过文案）：")
        for k in orphans[:20]:
            print(f"   {k!r}")

    report = {"parts": parts, "added": added, "already": same,
              "conflicts": len(conflicts), "placeholder_mismatch": len(ph_bad),
              "orphans": len(orphans), "keys_after": len(merged)}
    if args.as_json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        print(f"片段 {len(parts)} 个：新增 {added} 条、已存在且一致 {same} 条，"
              f"合并后共 {len(merged)} 条")

    if conflicts or ph_bad:
        return 1
    if args.dry_run:
        print("（--dry-run：没有写文件）")
        return 0

    with open(TARGET, "w", encoding="utf-8") as fh:
        json.dump(merged, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"写入 {os.path.relpath(TARGET, ROOT)}")
    if args.clean:
        for name in parts:
            os.remove(os.path.join(LANG, name))
        print(f"删掉 {len(parts)} 个片段文件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
