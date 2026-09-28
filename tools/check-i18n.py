#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""界面多语言的体检脚本。

数三样东西，缺哪个都会在英文界面里露馅：

  1. 没包 _() 的中文字面量   —— 英文用户还会看到中文（提示、报错、菜单）；
  2. 包了 _() 但译文表里没有 —— 同样显示中文（i18n 查不到就原样返回）；
  3. 译文表里有、源码里找不到的 key —— 改文案后留下的僵尸条目。

用法：
    python3 tools/check-i18n.py            # 概览（每个文件一行）
    python3 tools/check-i18n.py -v         # 连同具体字符串一起列出来
    python3 tools/check-i18n.py --json     # 给别的脚本吃

退出码：0 = 干净；1 = 有"包了但没译文"；2 = 还有没包的中文（-v 能看到是哪句）。

只数不改。路径名 / 文件名 / JSON 键 / 正则这些**故意**保持中文的常量会算进
"未包"那一类，所以这里只做提醒，不自动改代码。
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
LANG_DIR = os.path.join(APP, "lang")

CJK = re.compile(r"[\u4e00-\u9fff]")

# 故意保持中文的：目录名 / 文件名 / 程序自己解析的标记
INTENTIONAL = (
    "记录", "日志.txt", "坐标记录.txt", "结果.jsonl", "算种子记录.txt",
    "要装的东西.txt", "使用说明.md", "用户协议与隐私政策.md",
    ".update-backup", "反馈包",
)


def _is_wrapped_call(node):
    f = node.func
    if isinstance(f, ast.Name):
        return f.id in ("_", "t")
    if isinstance(f, ast.Attribute):
        return f.attr in ("t", "translate")
    return False


def _docstrings(tree):
    """模块 / 函数 / 类的 docstring（注释和说明不算界面文字，跳过）"""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef,
                             ast.AsyncFunctionDef, ast.ClassDef)):
            text = ast.get_docstring(node, clean=False)
            if text:
                out.add(text)
    return out


def scan_file(path):
    """返回 (包了 _() 的字符串集合, 没包的中文集合)"""
    try:
        tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
    except SyntaxError:
        return set(), set()
    skip = _docstrings(tree)
    wrapped, all_cjk = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _is_wrapped_call(node) and node.args:
            a = node.args[0]
            if isinstance(a, ast.Constant) and isinstance(a.value, str):
                wrapped.add(a.value)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if CJK.search(node.value) and node.value not in skip:
                all_cjk.add(node.value)
    return wrapped, all_cjk - wrapped


def load_table():
    table = {}
    if not os.path.isdir(LANG_DIR):
        return table
    for name in sorted(os.listdir(LANG_DIR)):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(LANG_DIR, name), encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            continue
        for k, v in data.items():
            if isinstance(v, str) and v:
                table.setdefault(k, name)
    return table


def looks_intentional(s):
    return any(tok in s for tok in INTENTIONAL)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--json", dest="as_json", action="store_true")
    args = ap.parse_args()

    table = load_table()
    rows = []
    all_wrapped, all_unwrapped = set(), set()
    for root, _dirs, files in os.walk(APP):
        for name in sorted(files):
            if not name.endswith(".py"):
                continue
            path = os.path.join(root, name)
            wrapped, unwrapped = scan_file(path)
            rel = os.path.relpath(path, ROOT)
            missing = sorted(s for s in wrapped if s not in table)
            soft = sorted(s for s in unwrapped if not looks_intentional(s))
            hard = sorted(s for s in unwrapped if looks_intentional(s))
            all_wrapped |= wrapped
            all_unwrapped |= unwrapped
            rows.append({"file": rel, "wrapped": len(wrapped), "missing": missing,
                         "unwrapped": soft, "intentional": hard})

    stale = sorted(k for k in table
                   if CJK.search(k) and k not in all_wrapped and k not in all_unwrapped)
    result = {"rows": rows, "table_keys": len(table), "stale": stale}

    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"译文表：{len(table)} 条")
        print(f"{'file':<30}{'wrapped':>8}{'missing':>8}{'raw':>6}{'raw(path)':>10}")
        print("-" * 64)
        for r in rows:
            if r["wrapped"] or r["missing"] or r["unwrapped"] or r["intentional"]:
                print(f"{r['file']:<30}{r['wrapped']:>8}{len(r['missing']):>8}"
                      f"{len(r['unwrapped']):>6}{len(r['intentional']):>10}")
        print("-" * 64)
        tot_missing = sum(len(r["missing"]) for r in rows)
        tot_un = sum(len(r["unwrapped"]) for r in rows)
        print(f"缺译文 {tot_missing} 条 · 没包的中文 {tot_un} 条（含故意的路径/常量）"
              f" · 僵尸条目 {len(stale)} 条")
        if args.verbose:
            for r in rows:
                if r["missing"]:
                    print(f"\n[missing] {r['file']}")
                    for s in r["missing"]:
                        print("   " + s.replace("\n", "\\n"))
                if r["unwrapped"]:
                    print(f"\n[raw] {r['file']}")
                    for s in r["unwrapped"]:
                        print("   " + s.replace("\n", "\\n"))
            if stale:
                print("\n[stale]")
                for s in stale:
                    print("   " + s.replace("\n", "\\n"))
        else:
            print("（加 -v 看具体是哪些句子）")

    if any(r["missing"] for r in rows):
        return 1
    if sum(len(r["unwrapped"]) for r in rows):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
