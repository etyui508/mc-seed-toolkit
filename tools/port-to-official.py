#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把按 intermediary 名字写的模组源码，转成官方名字版本（给 26.x 用）。

原理：
  · Fabric 的 intermediary 映射： 混淆名 -> class_xxx
  · Mojang 的官方映射（client.txt）：混淆名 -> 可读的官方名
  两边用"混淆名"当共同键接起来，就得到 class_xxx -> MinecraftClient 这种对照。
  26.x 起官方 jar 不再混淆（Fabric 用的是恒等映射），所以源码里必须写官方名字。

用法: python3 tools/port-to-official.py <源文件.java> <输出.java>
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, ".build-cache")
VER = os.environ.get("MC_PORT_FROM", "1.21.10")     # 拿哪个版本的映照表（intermediary 跨版本通用）

# 两个映射文件对不上键的少数几个（命名空间细节），查过 26.x 的官方名后手工补上
MANUAL = {
    "field_1724": "player",          # Minecraft.player（本地玩家）
    "field_10540": "OBSIDIAN",       # Blocks.OBSIDIAN
    "method_26204": "getBlock",      # BlockState.getBlock
    "method_12006": "getSections",   # LevelChunk.getSections
    "method_12254": "getBlockState", # LevelChunkSection.getBlockState
    "method_21730": "getChunk",      # ChunkSource.getChunk
    "method_29177": "location",      # ResourceKey.location
}


def load_tiny(ver):
    """intermediary 映射：返回 (混淆类->class_xxx, 混淆成员->method_xxx/field_xxx)"""
    base = os.path.join(CACHE, "intermediary", ver)
    path = None
    for root, _d, files in os.walk(base):
        for f in files:
            if f.endswith(".tiny"):
                path = os.path.join(root, f)
                break
        if path:
            break
    if not path:
        raise SystemExit(f"找不到 {ver} 的 intermediary 映射")
    classes, members = {}, {}
    cur = None
    for line in open(path, encoding="utf-8"):
        parts = line.rstrip("\n").lstrip("\t").split("\t")
        if not parts or not parts[0]:
            continue
        if parts[0] == "c" and len(parts) > 2:
            cur = parts[1]                      # 混淆名
            classes[cur] = parts[2].rsplit("/", 1)[-1]   # class_xxx
        elif parts[0] in ("m", "f") and len(parts) > 3 and cur:
            members[(cur, parts[2])] = parts[3]  # (混淆类, 混淆成员) -> method_xxx
    return classes, members


def load_official(path):
    """Mojang 官方映射 client.txt。格式是 **官方名 -> 混淆名**：

      com.mojang.blaze3d.Blaze3D -> fqq:
          9:10:void youJustLostTheGame() -> a
          13:13:double getTime() -> b

    返回 (混淆类 -> 官方类名, (混淆类, 混淆成员) -> 官方成员名)
    """
    classes, members = {}, {}
    obf_class = None
    for raw in open(path, encoding="utf-8"):
        line = raw.rstrip("\n")
        if line.startswith("#") or not line.strip():
            continue
        if not line.startswith(" "):             # 类那一行
            left, _, right = line.partition(" -> ")
            obf_class = right.strip().rstrip(":")
            classes[obf_class] = left.strip().split("$")[0]   # 完整官方路径
            continue
        left, _, right = line.strip().partition(" -> ")
        if not obf_class or not right:
            continue
        obf_member = right.strip()
        m = re.search(r"([\w$]+)\s*\(", left)     # "9:10:void foo(...)" -> foo
        official = m.group(1) if m else (left.split()[-1] if left.split() else "")
        if official:
            members[(obf_class, obf_member)] = official
    return classes, members


def main():
    src_path, out_path = sys.argv[1], sys.argv[2]
    tiny_classes, tiny_members = load_tiny(VER)
    off_classes, off_members = load_official(
        os.path.join(CACHE, "mappings", f"client-{VER}.txt"))

    obf2inter = tiny_classes                        # 混淆 -> class_xxx
    obf2off = off_classes                           # 混淆 -> 官方名
    inter2off = {}
    for obf, inter in obf2inter.items():
        if obf in obf2off:
            inter2off[inter] = obf2off[obf]
    # 成员： (混淆类, 混淆成员) -> intermediary ；同样接到官方名。
    # 注意同一个 intermediary 成员名在不同类下可能不同，所以额外记一份"全局候选"，
    # 源码里是裸名字（不知道 owner）时，只要全局唯一就用它。
    member_map, candidates = {}, {}
    for (obf, member), inter in tiny_members.items():
        off = off_members.get((obf, member))
        if off:
            member_map.setdefault(inter, off)
            candidates.setdefault(inter, set()).add(off)
    unique = {k: next(iter(v)) for k, v in candidates.items() if len(v) == 1}
    print(f"类名对照 {len(inter2off)} 条，成员对照 {len(member_map)} 条")
    print(f"  其中全局唯一、可以无脑替换的成员名：{len(unique)} 条")

    text = open(src_path, encoding="utf-8").read()

    # 类名：net.minecraft.class_310 -> net.minecraft.MinecraftClient
    def cls_sub(m):
        full = inter2off.get(m.group(2))
        return full if full else m.group(1) + m.group(2)   # 包名也一起换掉
    text, n_cls = re.subn(r"\b([a-z][\w.]*\.)(class_\d+)", cls_sub, text)
    # 还有一种写法是裸类名（文件上面已经 import 过了）：class_638 world = ...
    def bare_sub(m):
        full = inter2off.get(m.group(0))
        return full.rsplit(".", 1)[-1] if full else m.group(0)
    text, n_bare = re.subn(r"\bclass_\d+\b", bare_sub, text)
    # 成员名（method_xxx / field_xxx）直接换成官方名
    def mem_sub(m):
        name = m.group(0)
        return MANUAL.get(name) or member_map.get(name) or unique.get(name) or name
    text, n_mem = re.subn(r"\b(?:method|field)_\d+\b", mem_sub, text)
    print(f"替换：带包名 {n_cls} 处，裸类名 {n_bare} 处，成员 {n_mem} 处")

    left = len(re.findall(r"\bclass_\d+\b", text)) + len(re.findall(r"\b(?:method|field)_\d+\b", text))
    print(f"还剩没换上的：{left} 处")
    if left:
        for m in re.findall(r"\b(?:class|method|field)_\d+\b", text)[:8]:
            print("   ", m)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    open(out_path, "w", encoding="utf-8").write(text)
    print("写出", out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
