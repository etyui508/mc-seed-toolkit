#!/usr/bin/env bash
# 用游戏本体里的类对拍我们的复刻实现（末地柱子 / 史莱姆区块 / 结构摆放）
set -euo pipefail

MC_DIR="/mnt/d/666/新建文件夹/.minecraft"
VERSION="$MC_DIR/versions/1.21.10-Fabric 0.19.3"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT="$(dirname "$HERE")"
OUT="$HERE/out"

mkdir -p "$OUT"

# 用版本 json 里的库列表拼出和游戏一模一样（且顺序正确）的 classpath
CP="$(python3 - "$VERSION" "$OUT" <<'PY'
import json, os, sys
version, out = sys.argv[1], sys.argv[2]
lib_root = os.path.join(version, "..", "..", "libraries")
lib_root = os.path.normpath(lib_root)
json_path = [f for f in os.listdir(version) if f.endswith(".json") and "Fabric" in f][0]
data = json.load(open(os.path.join(version, json_path)))
libs = []
for lib in data["libraries"]:
    art = lib.get("downloads", {}).get("artifact")
    if not art or "natives" in lib["name"]:
        continue
    p = os.path.join(lib_root, art["path"])
    if os.path.exists(p):
        libs.append(p)
intermediary = os.path.join(version, ".fabric", "remappedJars",
                            "minecraft-1.21.10-0.19.3", "client-intermediary.jar")
print(":".join([out, intermediary] + libs))
PY
)"

javac -encoding UTF-8 -proc:none -cp "$CP" -d "$OUT" \
    "$PROJECT/tools/SeedCracker.java" "$HERE/SpikeVerify.java" "$HERE/StructureVerify.java" \
    "$HERE/HashVerify.java" "$HERE/InfoTest.java"

echo "== 末地柱子 + 史莱姆区块 =="
java -cp "$CP" SpikeVerify | tail -3
echo "== 结构摆放 =="
java -cp "$CP" StructureVerify | tail -2
echo "== 哈希种子（sha256） =="
java -cp "$CP" HashVerify | tail -1
echo "== 自测 =="
java -cp "$OUT" SeedCracker selftest | tail -2
