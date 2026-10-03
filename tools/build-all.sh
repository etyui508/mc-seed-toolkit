#!/usr/bin/env bash
# 编译 Java 工具（必须）；cubiomes 是可选但推荐（结构/群系检查要用）
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"     # tools/
ROOT="$(dirname "$HERE")"                               # 工具包根目录
cd "$HERE"

echo "== 编译 Java 工具 =="
mkdir -p "$ROOT/out"
# --release 17：这样 Java 17/18 也能跑（1.21 的玩家基本都是 21，但兼容一点没坏处）
javac --release 17 -encoding UTF-8 -d "$ROOT/out" SeedCracker.java RegionScan.java PortalScan.java \
    BlockFind.java PillarScan.java SlimeFind.java FindStructures.java ShipScan.java OreScan.java
echo "OK -> $ROOT/out/"

# 记下这份源码的指纹：发布前 tools/check-build-sync.py 会拿它比对，
# 免得"改了源码、忘了重编"的旧二进制被发出去
python3 "$HERE/check-build-sync.py" --record

if [[ "${1:-}" == "--with-cubiomes" ]]; then
    echo "== 编译 cubiomes 找结构工具（需要 gcc + git）=="
    CUBIOMES_DIR="${CUBIOMES_DIR:-/tmp/cubiomes}"
    if [[ ! -d "$CUBIOMES_DIR" ]]; then
        git clone --depth 1 https://github.com/Cubitect/cubiomes.git "$CUBIOMES_DIR"
    fi
    CUBIOMES_DIR="$CUBIOMES_DIR" bash "$HERE/build-cubiomes.sh"
fi

echo
echo "都好了。跑 python3 app/tool.py 开始用。"
