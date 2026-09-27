#!/usr/bin/env bash
# 编译 cubiomes 版的找结构工具（需要 gcc；cubiomes 源码在 /tmp/cubiomes）
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="${CUBIOMES_DIR:-/tmp/cubiomes}"
OUT="$HERE/../out/findstruct"

if [[ ! -d "$SRC" ]]; then
    echo "没找到 cubiomes 源码（$SRC），先:" >&2
    echo "  git clone --depth 1 https://github.com/Cubitect/cubiomes.git $SRC" >&2
    exit 1
fi

mkdir -p "$(dirname "$OUT")"
gcc -O2 -fwrapv -Wall -I"$SRC" -o "$OUT" "$HERE/findstruct.c" \
    "$HERE/endcity.c" \
    "$SRC/biomes.c" "$SRC/biomenoise.c" "$SRC/layers.c" "$SRC/generator.c" \
    "$SRC/finders.c" "$SRC/noise.c" "$SRC/quadbase.c" "$SRC/util.c" -lm -lpthread
echo "编译好了 -> $OUT"
