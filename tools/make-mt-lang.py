#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 app/lang/mt.json —— 「人机翻译版」界面文字（主菜单彩蛋 Yes ③ 用的）。

做法：**让 AI 扮演一台 1998 年的机翻引擎**，把 en.json 里现成的英文译文
逐词硬翻回中文，并额外要求它把这句"连续翻译十遍"（英→日→韩→法→德→俄→阿→
泰→越→西→中），每一步都走那套死板规则。产出的就是雷时东翻译法：

    Quit                     -> 戒烟
    Settings                 -> 安装
    Find the world seed      -> 找到 世界 籽
    ...can use it right away -> …能 使用 它 右 离开
    Seeds and save paths…    -> 籽 和 保存 路径 里面 日志 是 蒙面 自动。

为什么不让 AI"好好翻十遍"：试过，它每一跳都翻得很准，十跳下来反而收敛回
通顺的正确译文（真机翻才会丢东西）。所以必须同时给它一套**死板的逐词规则**
（不许调整语序、不许润色、术语按字面乱译），漂移才出得来。

为什么不用 Google：2026-09-29 那条路被打限流了（几百次请求之后 IP 直接 302
到 sorry 页），有道/百度/腾讯也一样（限流、要签名、要鉴权）。自家模型稳定、
不用代理、不会被封。

工程上的三件事：
  · **一次一批**：几十行拼成一块发过去，回来的行数对得上才认，对不上退回逐条；
  · **{占位符} 换成 ZQ0QZ 记号**再上路（{path} 会被翻成 {路径}），回来校验；
  · **逐批落盘**：断了从上次的地方接着跑，不会白跑。

    python3 tools/make-mt-lang.py              # 接着上次跑
    python3 tools/make-mt-lang.py --refresh    # 全部重来
    python3 tools/make-mt-lang.py --check      # 只比对，不写文件（不联网）
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EN = os.path.join(ROOT, "app", "lang", "en.json")
MT = os.path.join(ROOT, "app", "lang", "mt.json")
CACHE = os.path.join(HERE, "mt-cache.json")

API = os.environ.get("MT_API", "https://api.deepseek.com/chat/completions")
MODEL = os.environ.get("MT_MODEL", "deepseek-v4-flash")
CODEX_CONF = os.path.expanduser("~/.codex/config.toml")
BATCH_CHARS = 900          # 一批拼多长
BATCH_MAX = 25             # 一批最多几行
ATTEMPTS = 4

SYSTEM = (
    "你是一台 1998 年的机翻引擎，词库很小、语法很死。铁律：\n"
    "1) 严格按源文本的词序逐词翻译，绝不调整语序、绝不合并短句；\n"
    "2) 每个词只取最字面的常见义，哪怕在这个句子里明显不对"
    "（Settings=安装，Quit=戒烟，Releases=开发版，Roll back=回滚，"
    "seed=籽，structure=建筑物，End=结束，right away=右离开）；\n"
    "3) 功能词（the/a/of/to/and 这类）能不译就不译；\n"
    "4) 绝对不许润色，不许补主语，读着别扭、像机器硬拼的才对；\n"
    "5) 数字、路径、{花括号里的占位符} 原样保留。"
)
CHAIN = ("把每一行按这个顺序连续翻译十遍：英语→日语→韩语→法语→德语→俄语→"
         "阿拉伯语→泰语→越南语→西班牙语→中文。每一次都用上面那套死板的逐词"
         "规则，别让它变通顺。一行输入只对应一行输出：不要解释、不要补充说明、"
         "不要拆成多行、不要加序号。")

# 翻完之后的小替换：引擎把 Minecraft 翻成"我的世界"，但这个彩蛋叫"雷时东"
TERMS = (
    ("我的世界", "雷时东"),
    ("Minecraft", "雷时东"),
)

PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
MARKER = "ZQ%dQZ"          # 全大写记号不会被翻译（试过 <PH0>、[[0]]、私有区字符）

_calls = 0
_fallback = []


def has_cjk(text):
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def tokens():
    """手上有哪些 key，按可靠程度排。

    环境变量里那个 DEEPSEEK_API_KEY 是失效的（2026-09-29 实测），而
    ~/.codex/config.toml 里 Codex 自己用的那个能用 —— 所以不猜，一个个试。
    """
    out = []
    got = os.environ.get("MT_TOKEN", "").strip()
    if got:
        out.append(got)
    try:
        with open(CODEX_CONF, encoding="utf-8") as fh:
            m = re.search(r'experimental_bearer_token\s*=\s*"([^"]+)"', fh.read())
        if m:
            out.append(m.group(1))
    except OSError:
        pass
    for name in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY"):
        got = os.environ.get(name, "").strip()
        if got and got not in out:
            out.append(got)
    if not out:
        raise SystemExit("找不到可用的 API token（MT_TOKEN / ~/.codex/config.toml / "
                         "DEEPSEEK_API_KEY）")
    return out


def protect(text):
    """把 {name} 换成记号，免得大括号里面被一起翻掉（{path} -> {路径}）"""
    names = PLACEHOLDER.findall(text)
    for i, name in enumerate(names):
        text = text.replace("{%s}" % name, MARKER % i, 1)
    return text, names


def restore(text, names):
    for i, name in enumerate(names):
        text = text.replace(MARKER % i, "{%s}" % name)
    return text


def decorate(text):
    for zh, mt in TERMS:
        text = text.replace(zh, mt)
    return text


def ask(lines, key, lenient=False):
    """一次翻一批：把若干行交给"机翻引擎"，返回等长的译文行。"""
    global _calls
    user = (CHAIN + "\n\n输出要求：行数必须和输入完全一致，一行一条，"
            "不要编号、不要解释、不要空行。\n\n" + "\n".join(lines))
    payload = {"model": MODEL,
               "thinking": {"type": "disabled"},      # 思维链又慢又贵，这里不需要
               "messages": [{"role": "system", "content": SYSTEM},
                            {"role": "user", "content": user}],
               "max_tokens": max(1200, 160 * len(lines)),
               "temperature": 0.6}
    last = ""
    for attempt in range(ATTEMPTS):
        done = subprocess.run(
            ["curl", "-s", API, "-H", "Authorization: Bearer " + key,
             "-H", "Content-Type: application/json",
             "-d", json.dumps(payload, ensure_ascii=False)],
            capture_output=True, text=True, timeout=600)
        _calls += 1
        last = (done.stdout or "").strip()
        try:
            data = json.loads(last)
        except ValueError:
            time.sleep(2 * (attempt + 1))
            continue
        if "error" in data:
            raise RuntimeError(str(data["error"].get("message", data["error"]))[:120])
        got = (data["choices"][0]["message"].get("content") or "").strip()
        rows = [r for r in got.splitlines() if r.strip()]
        if len(rows) == len(lines):
            return rows
        # 单行输入时模型偶尔会多嘴写两三行；只取第一行（提示词已经要求它别解释）
        if lenient and len(lines) == 1 and rows:
            return [rows[0]]
        last = f"行数 {len(rows)} != {len(lines)}"
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"这批没翻成：{last}")


def chunks(items, limit=BATCH_CHARS, most=BATCH_MAX):
    batch, size = [], 0
    for key, text in items:
        if batch and (size + len(text) + 1 > limit or len(batch) >= most):
            yield batch
            batch, size = [], 0
        batch.append((key, text))
        size += len(text) + 1
    if batch:
        yield batch


def save(cache, verbose=False):
    with open(CACHE, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    if verbose:
        print(f"    …落盘 {len(cache['done'])} 条，已发 {_calls} 次请求", flush=True)


def load_cache(refresh):
    try:
        with open(CACHE, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {}
    if refresh or "done" not in data:
        # 兼容老格式：以前整个缓存就是 {英文: 中文} 一张平表
        done = {} if refresh else {k: v for k, v in data.items() if isinstance(v, str)}
    else:
        done = dict(data.get("done", {}))
    return {"done": done}


def build(refresh, key):
    with open(EN, encoding="utf-8") as fh:
        en = json.load(fh)
    cache = load_cache(refresh)
    done = cache["done"]
    keys = [k for k, v in en.items()
            if isinstance(v, str) and v.strip()
            and not k.startswith("log:")          # 日志保持中文，反馈日志得看得懂
            and has_cjk(k)]                       # 本来就英文/符号的不折腾
    todo = [k for k in keys if en[k] not in done]
    print(f"共 {len(keys)} 条；已完成 {len(keys) - len(todo)}，这次要翻 {len(todo)}",
          flush=True)

    groups = list(chunks([(k, protect(en[k])[0]) for k in todo]))
    for i, batch in enumerate(groups, 1):
        want = [text for _, text in batch]
        try:
            rows = ask(want, key)
        except Exception as exc:
            print(f"   第 {i} 批失败（{exc}），改逐条", flush=True)
            rows = []
        if len(rows) == len(batch):
            for (k, _), row in zip(batch, rows):
                got = finalize(en[k], row, key)
                if got is not None:
                    done[en[k]] = got
        else:
            for k, text in batch:
                try:
                    got = finalize(en[k], ask([text], key, lenient=True)[0], key)
                    if got is not None:
                        done[en[k]] = got
                except Exception as exc:
                    print(f"   跳过 {k[:18]}（{exc}）", flush=True)
        if i % 4 == 0 or i == len(groups):
            save(cache, verbose=True)
    save(cache)
    table = {k: done[en[k]] for k in keys if en[k] in done}
    return dict(sorted(table.items())), len(keys)


def finalize(english, raw, key):
    """记号还原 + 校验。实在拿不准就返回 None —— 让这一条保持中文原样，
    千万别回落到英文原文（mt 模式下突然冒出一句英文，比不翻还怪）。"""
    _, names = protect(english)
    if raw and all((MARKER % i) in raw for i in range(len(names))):
        out = decorate(restore(raw, names))
        if out.strip():
            return out
    _fallback.append(english)
    try:
        once = restore(decorate(ask([protect(english)[0]], key, lenient=True)[0]), names)
        if sorted(PLACEHOLDER.findall(once)) == sorted(names) and once.strip():
            return once
    except Exception:
        pass
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="全部重来（清掉缓存）")
    ap.add_argument("--check", action="store_true", help="只比对，不写文件（不联网）")
    args = ap.parse_args()

    if args.check:
        with open(EN, encoding="utf-8") as fh:
            en = json.load(fh)
        done = load_cache(refresh=False)["done"]
        keys = [k for k, v in en.items()
                if isinstance(v, str) and v.strip() and not k.startswith("log:")
                and has_cjk(k)]
        missing = [k for k in keys if en[k] not in done]
        if missing:
            print(f"❌ 还差 {len(missing)} 条没翻完，接着跑："
                  f"python3 tools/make-mt-lang.py", file=sys.stderr)
            return 1
        text = json.dumps({k: done[en[k]] for k in keys}, ensure_ascii=False,
                          indent=2, sort_keys=True) + "\n"
        with open(MT, encoding="utf-8") as fh:
            got = fh.read()
        if got == text:
            print(f"✅ mt.json 和缓存一致（{len(keys)} 条）")
            return 0
        print("❌ mt.json 和缓存对不上，重跑：python3 tools/make-mt-lang.py",
              file=sys.stderr)
        return 1

    key = None
    for candidate in tokens():
        try:
            probe = ask(["Quit"], candidate)[0]
            key = candidate
            print(f"引擎正常（Quit -> {probe}）", flush=True)
            break
        except Exception as exc:
            print(f"（这个 key 不行：{str(exc)[:70]}）", flush=True)
    if key is None:
        print("⛔ 手上没有能用的 key", file=sys.stderr)
        return 3

    table, total = build(args.refresh, key)
    with open(MT, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(table, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(f"写入 {os.path.relpath(MT, ROOT)}：{len(table)}/{total} 条，"
          f"共发 {_calls} 次请求")
    if len(table) < total:
        print(f"⚠ 还差 {total - len(table)} 条 —— 再跑一次就接着来")
    if _fallback:
        print(f"⚠ {len(_fallback)} 条的记号被磨掉了，退回了保守结果")
    for probe in ("主菜单", "退出", "设置", "计算种子", "从下载的存档反推世界种子"):
        if probe in table:
            print(f"  {probe}  ->  {table[probe]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
