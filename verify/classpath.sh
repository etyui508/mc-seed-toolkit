#!/usr/bin/env bash
# 输出和游戏本体一致（且顺序正确）的 classpath
set -euo pipefail
MC_DIR="/mnt/d/666/新建文件夹/.minecraft"
VERSION="$MC_DIR/versions/1.21.10-Fabric 0.19.3"
python3 - "$VERSION" <<'PY'
import json, os, sys
version = sys.argv[1]
lib_root = os.path.normpath(os.path.join(version, "..", "..", "libraries"))
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
print(":".join([intermediary] + libs))
PY
