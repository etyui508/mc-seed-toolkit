#!/usr/bin/env bash
# 交叉编译 Windows 版的 findstruct.exe（WSL 里也能跑，需要 mingw-w64）
#   sudo apt install -y gcc-mingw-w64-x86-64
# cubiomes 源码默认在 /tmp/cubiomes，可以用 CUBIOMES_DIR= 改。
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="${CUBIOMES_DIR:-/tmp/cubiomes}"
OUT="$HERE/../out/findstruct.exe"
CC="${MINGW_CC:-x86_64-w64-mingw32-gcc}"

if [[ ! -d "$SRC" ]]; then
    echo "没找到 cubiomes 源码（$SRC），先:" >&2
    echo "  git clone --depth 1 https://github.com/Cubitect/cubiomes.git $SRC" >&2
    exit 1
fi
if ! command -v "$CC" >/dev/null 2>&1; then
    echo "没找到 $CC —— sudo apt install -y gcc-mingw-w64-x86-64" >&2
    exit 1
fi

mkdir -p "$(dirname "$OUT")"
"$CC" -static -O2 -fwrapv -Wall -I"$SRC" -o "$OUT" "$HERE/findstruct.c" \
    "$HERE/endcity.c" \
    "$SRC/biomes.c" "$SRC/biomenoise.c" "$SRC/layers.c" "$SRC/generator.c" \
    "$SRC/finders.c" "$SRC/noise.c" "$SRC/quadbase.c" "$SRC/util.c" -lm -lpthread
echo "编译好了 -> $OUT"
