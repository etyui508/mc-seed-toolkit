#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把按 intermediary 名字写的模组源码，译成 Forge 能跑的 SRG 名字版本。

为什么要这一步：Forge 1.20.1 运行时的命名是「官方类名 + SRG 成员名」——
类叫 net.minecraft.client.Minecraft，字段方法却是 f_90981_ / m_91087_ 这种。
而我们的源码写的是 Fabric 的 intermediary 名字（class_310 / field_1687）。

翻译链（两边都用"混淆名"当共同键）：

    intermediary  ──Fabric tiny──▶  混淆名  ──Mojang 官方表──▶  官方类名
                                        └──Forge joined.tsrg──▶  SRG 成员名

顺带也能把 26.x 那种"官方名"版本试试：官方表出来的类名一样，只是成员不换 SRG。

用法:
    python3 tools/port-to-forge.py <源.java> <输出.java> [--version 1.20.1]
                                   [--tiny 路径] [--mojang 路径] [--tsrg 路径]
    python3 tools/port-to-forge.py --report 1.20.1     # 只看名字能不能全译出来

映射文件会缓存在 .build-cache/mappings/ 下，缺了自动去官方源下。
"""
import argparse
import io
import os
import re
import sys
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, ".build-cache")
FABRIC_MAVEN = "https://maven.fabricmc.net"
FORGE_MAVEN = "https://maven.minecraftforge.net"
MOJANG_MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"


def log(*a):
    print(*a, flush=True)


def download(url, dest, desc=None):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return dest
    log(f"    下载 {desc or os.path.basename(dest)} …")
    req = urllib.request.Request(url, headers={"User-Agent": "mc-seed-toolkit-port"})
    with urllib.request.urlopen(req, timeout=300) as r, open(dest, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    return dest


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "mc-seed-toolkit-port"})
    import json
    return json.loads(urllib.request.urlopen(req, timeout=120).read().decode())


# ------------------------------------------------------------------ 三张表
def load_tiny(path):
    """Fabric intermediary：混淆名 <-> class_xxx / method_xxx / field_xxx"""
    if zipfile.is_zipfile(path):                 # 传进来的是 intermediary-x-v2.jar
        with zipfile.ZipFile(path) as z:
            name = [n for n in z.namelist() if n.endswith(".tiny")][0]
            data = z.read(name).decode("utf-8", "replace")
    else:                                        # 已经是解出来的 mappings.tiny
        data = open(path, encoding="utf-8").read()
    inter_cls = {}                      # class_xxx -> 混淆名
    obf_cls = {}                        # 混淆名 -> class_xxx
    # 注意：同一个类里字段和方法会重名，方法之间还会重载（同一个 u 对应好几个描述符）。
    # 所以键必须带「类型 + 描述符」，只带类名+成员名的话会互相覆盖 —— 之前就是这么
    # 漏掉 method_10263 的（被同名的另一个重载盖掉了）。
    members = {}                        # (混淆类, 混淆成员, 描述符, 'm'/'f') -> intermediary 名
    cur = None
    for line in data.splitlines()[1:]:
        parts = line.lstrip("\t").split("\t")
        if not parts or not parts[0]:
            continue
        if parts[0] == "c" and len(parts) > 2:
            cur = parts[1]
            obf_cls[cur] = parts[2].rsplit("/", 1)[-1]
            inter_cls[parts[2].rsplit("/", 1)[-1]] = cur
        elif parts[0] in ("m", "f") and len(parts) > 3 and cur:
            members[(cur, parts[2], parts[1], parts[0])] = parts[3]
    return inter_cls, obf_cls, members


def load_mojang(path):
    """Mojang 官方表：混淆名 -> 官方全名（把 . 换成 / 好用一点）"""
    out = {}
    for line in open(path, encoding="utf-8"):
        if line.startswith("#") or line.startswith(" "):
            continue
        if "->" not in line:
            continue
        left, right = line.split("->")
        if ":" not in right:
            continue
        out[right.split(":")[0].strip()] = left.strip()
    return out


def load_tsrg(path):
    """Forge joined.tsrg：混淆名 -> SRG。返回 {(混淆类, 混淆成员): SRG 名}"""
    out = {}
    cur = None
    for line in open(path, encoding="utf-8"):
        if line.startswith("tsrg"):
            continue
        if not line.startswith("\t"):
            p = line.rstrip("\n").split(" ")
            cur = p[0] if p and p[0] else cur
            continue
        p = line.lstrip("\t").rstrip("\n").split(" ")
        if not p or p[0] in ("static", "<init>", "<clinit>") or not p[0]:
            continue
        if len(p) >= 3 and p[1].startswith("("):     # 方法：混淆名 描述符 SRG 编号
            out[(cur, p[0], p[1], "m")] = p[2]
        elif len(p) >= 2:                            # 字段：混淆名 SRG 编号（没有描述符）
            out[(cur, p[0], "f")] = p[1]
    return out


def prepare(ver):
    """把三张表准备好（缺的就下）"""
    tiny_local = os.path.join(CACHE, "intermediary", ver, "mappings", "mappings.tiny")
    if not os.path.exists(tiny_local):
        jar = os.path.join(CACHE, "intermediary", f"intermediary-{ver}-v2.jar")
        download(f"{FABRIC_MAVEN}/net/fabricmc/intermediary/{ver}/intermediary-{ver}-v2.jar",
                 jar, f"intermediary {ver}")
        with zipfile.ZipFile(jar) as z:
            name = [n for n in z.namelist() if n.endswith(".tiny")][0]
            os.makedirs(os.path.dirname(tiny_local), exist_ok=True)
            open(tiny_local, "wb").write(z.read(name))

    mojang_local = os.path.join(CACHE, "mappings", f"client-{ver}.txt")
    if not os.path.exists(mojang_local):
        man = fetch_json(MOJANG_MANIFEST)
        entry = next((v for v in man["versions"] if v["id"] == ver), None)
        if not entry:
            raise SystemExit(f"Mojang 清单里没有 {ver}")
        info = fetch_json(entry["url"])
        url = info["downloads"].get("client_mappings", {}).get("url")
        if not url:
            raise SystemExit(f"{ver} 没有官方映射表")
        download(url, mojang_local, f"Mojang 官方表 {ver}")

    tsrg_local = os.path.join(CACHE, "mappings", f"joined-{ver}.tsrg")
    if not os.path.exists(tsrg_local):
        # mcp_config 的版本号是 <版本>-<时间戳>，那个时间戳既不是 releaseTime 也不是 time
        # （是客户端 jar 的构建时间），所以去 maven 的 maven-metadata.xml 里问，别猜。
        meta = urllib.request.urlopen(
            urllib.request.Request(f"{FORGE_MAVEN}/de/oceanlabs/mcp/mcp_config/maven-metadata.xml",
                                   headers={"User-Agent": "mc-seed-toolkit-port"}),
            timeout=120).read().decode("utf-8", "replace")
        stamps = sorted(set(re.findall(
            rf"<version>{re.escape(ver)}-(\d{{8}}\.\d{{6}})</version>", meta)))
        if not stamps:
            raise SystemExit(f"maven 上没有 {ver} 的 mcp_config（拿不到 Forge 映射）")
        stamp = stamps[-1]              # 同一版本重发过就用最新的那份
        zip_path = os.path.join(CACHE, "mappings", f"mcp_config-{ver}-{stamp}.zip")
        download(f"{FORGE_MAVEN}/de/oceanlabs/mcp/mcp_config/{ver}-{stamp}/"
                 f"mcp_config-{ver}-{stamp}.zip", zip_path, f"Forge 映射 {ver}")
        with zipfile.ZipFile(zip_path) as z:
            os.makedirs(os.path.dirname(tsrg_local), exist_ok=True)
            open(tsrg_local, "wb").write(z.read("config/joined.tsrg"))
    return tiny_local, mojang_local, tsrg_local


def build_maps(ver):
    tiny, mojang_path, tsrg_path = prepare(ver)
    inter_cls, _obf_cls, members = load_tiny(tiny)
    mojang = load_mojang(mojang_path)
    tsrg = load_tsrg(tsrg_path)
    return inter_cls, members, mojang, tsrg


def translate(text, inter_cls, members, mojang, tsrg, todo=None):
    """把源码里的 intermediary 名字换成 Forge 那套（类用官方名，成员用 SRG）"""
    stats = {"class": 0, "member": 0}
    unknown_cls, unknown_mem, ambiguous = set(), set(), {}

    def cls_sub(m):
        tok = m.group("tok")
        obf = inter_cls.get(tok)
        official = mojang.get(obf) if obf else None
        if not official:
            unknown_cls.add(tok)
            return m.group(0)
        stats["class"] += 1
        if m.group("head"):                       # net.minecraft.class_xxx
            return official
        return official.rsplit(".", 1)[-1]        # 裸类名

    def mem_sub(m):
        tok = m.group(0)
        kind = "m" if tok.startswith("method_") else "f"
        srgs = set()
        for k, v in members.items():
            if v != tok or k[3] != kind:
                continue
            s = tsrg.get((k[0], k[1], k[2], "m")) if kind == "m" else tsrg.get((k[0], k[1], "f"))
            if s:
                srgs.add(s)
        if not srgs:
            unknown_mem.add(tok)
            return tok
        if len(srgs) > 1:
            ambiguous[tok] = sorted(srgs)
            return tok
        stats["member"] += 1
        return srgs.pop()

    text = re.sub(r"(?P<head>net\.minecraft\.)?\b(?P<tok>class_\d+)\b", cls_sub, text)
    text = re.sub(r"\b(?:method|field)_\d+\b", mem_sub, text)
    if todo is not None:
        todo.update(unknown_cls=unknown_cls, unknown_mem=unknown_mem, ambiguous=ambiguous)
    return text, stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", nargs="?")
    ap.add_argument("dst", nargs="?")
    ap.add_argument("--version", default="1.20.1")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()

    log(f"准备 {a.version} 的映射表…")
    inter_cls, members, mojang, tsrg = build_maps(a.version)
    log(f"  class_ 名字 {len(inter_cls)} 个，成员 {len(members)} 个，"
        f"官方类 {len(mojang)} 个，SRG 成员 {len(tsrg)} 个")

    src = a.src or os.path.join(ROOT, "mod-src", "src", "com", "etyui", "seedhelper",
                                "SeedHelperClient.java")
    text = io.open(src, encoding="utf-8").read()
    todo = {}
    out, stats = translate(text, inter_cls, members, mojang, tsrg, todo)
    log(f"  译了 {stats['class']} 处类名、{stats['member']} 处成员名")
    for name, what in (("unknown_cls", "查不到官方名的类"), ("unknown_mem", "查不到 SRG 的成员")):
        if todo.get(name):
            log(f"  ⚠ {what}：{sorted(todo[name])}")
    if todo.get("ambiguous"):
        log(f"  ⚠ 有歧义的成员名（同一个 intermediary 名落在多个类上）：")
        for k, v in sorted(todo["ambiguous"].items()):
            log(f"      {k} -> {v}")
    if a.dst:
        os.makedirs(os.path.dirname(os.path.abspath(a.dst)), exist_ok=True)
        io.open(a.dst, "w", encoding="utf-8").write(out)
        log(f"  ✅ 写出 {a.dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
