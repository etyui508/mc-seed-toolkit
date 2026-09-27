#!/usr/bin/env bash
# 手工编译这个 Fabric 模组：
#   - 代码直接写的是 intermediary 名字（编译期就对着游戏本体校验，不需要 Loom/重映射）
#   - 依赖 fabric-loader 的入口点和 fabric-api 的 ClientTickEvents
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MC_DIR="/mnt/d/666/新建文件夹/.minecraft"
VERSION="$MC_DIR/versions/1.21.10-Fabric 0.19.3"
LIBS="$MC_DIR/libraries"
INTERMEDIARY="$VERSION/.fabric/remappedJars/minecraft-1.21.10-0.19.3/client-intermediary.jar"
OUT="$HERE/build"
JAR="$HERE/seedhelper-1.1.0.jar"

rm -rf "$OUT"
mkdir -p "$OUT/classes"

# fabric-api 里嵌套的子模块要解出来才能编译
NESTED="$HERE/build/nested"
mkdir -p "$NESTED"
unzip -o -q "$VERSION/mods/fabric-api-0.138.4+1.21.10.jar" 'META-INF/jars/fabric-lifecycle-events-v1-*.jar' \
    'META-INF/jars/fabric-api-base-*.jar' -d "$NESTED"

# 和游戏一致的库列表（顺序也对）
CP="$INTERMEDIARY:$("$HERE/../verify/classpath.sh" 2>/dev/null || true)"
CP="$CP:$(find "$NESTED" -name '*.jar' | tr '\n' ':')"
CP="$CP:$(find "$LIBS/net/fabricmc/fabric-loader" -name '*.jar' | head -1)"

echo "[1/3] 编译"
javac -encoding UTF-8 -proc:none -nowarn -cp "$CP" -d "$OUT/classes" $(find "$HERE/src" -name '*.java')

echo "[2/3] 打包"
cp "$HERE/fabric.mod.json" "$OUT/classes/"
( cd "$OUT/classes" && jar cf "$JAR" . )

echo "[3/3] 校验"
unzip -l "$JAR" | tail -5
echo "OK -> $JAR"
