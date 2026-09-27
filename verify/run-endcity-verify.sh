#!/usr/bin/env bash
# 对拍末地城生成器：
#   左边 = tools/endcity.c（我们自己复刻的，不用游戏、不用存档）
#   右边 = 游戏本体（tools/EndCityDump.java，直接调 EndCityPieces）
#
# 用法: bash verify/run-endcity-verify.sh [种子个数] [每个种子测几个城]
#
# 需要本机装过 Minecraft（拿它的类来对拍）。classpath 默认取 verify/classpath.sh，
# 也可以自己给：GAME_CP="..." bash verify/run-endcity-verify.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT="$(dirname "$HERE")"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

NSEED="${1:-4}"
NCITY="${2:-150}"
SIZES="$PROJECT/tools/endcity-sizes.txt"

GAME_CP="${GAME_CP:-$(bash "$HERE/classpath.sh")}"
if [[ -z "$GAME_CP" ]]; then
    echo "没拿到游戏 classpath —— 先确认本机装了 Minecraft（Fabric），或自己给 GAME_CP" >&2
    exit 1
fi

echo "== 编译游戏本体的对拍工具 =="
javac -proc:none -encoding UTF-8 -cp "$GAME_CP" -d "$WORK" "$PROJECT/tools/EndCityDump.java" 2>&1 \
    | grep -v "proprietary API" | grep -v "^import" | grep -v "^\s*\^" | grep -v "^Note:" || true

echo "== 生成测试用的城（$NSEED 个种子 × $NCITY 个城） =="
python3 - "$NSEED" "$NCITY" > "$WORK/seeds.txt" <<'PY'
import random, sys
nseed, ncity = int(sys.argv[1]), int(sys.argv[2])
rnd = random.Random(20260926)
seeds = [rnd.getrandbits(63) - (1 << 62) for _ in range(nseed)]
for s in seeds:
    cities = [(rnd.randint(-400, 400), rnd.randint(-400, 400)) for _ in range(ncity)]
    print(s, " ".join(f"{x} {z}" for x, z in cities))
PY

total=0
bad=0
while read -r seed cities; do
    # shellcheck disable=SC2086
    "$PROJECT/out/findstruct" shipdump "$seed" $cities > "$WORK/ours.txt"
    # shellcheck disable=SC2086
    java -cp "$WORK:$GAME_CP" EndCityDump "$seed" "$SIZES" $cities 2>/dev/null \
        | sed 's/ mirror=[A-Z_]*//' > "$WORK/game.txt"
    n=$(grep -c '^CITY' "$WORK/game.txt" || true)
    if diff -q "$WORK/game.txt" "$WORK/ours.txt" > /dev/null; then
        total=$((total + n))
        echo "  种子 $seed：$n 个城，逐段完全一致 ✅"
    else
        bad=$((bad + n))
        total=$((total + n))
        echo "  种子 $seed：有差异 ❌（差异前 20 行）"
        diff "$WORK/game.txt" "$WORK/ours.txt" | head -20
    fi
done < "$WORK/seeds.txt"

echo
if [[ "$bad" -eq 0 ]]; then
    echo "全部一致：$total 个城的每一段（名字/朝向/批次/模板原点/包围盒）都和游戏本体相同 ✅"
else
    echo "有 $bad / $total 个城对不上 ❌"
    exit 1
fi

# ---------------------------------------------------------------- 第二轮：对"船"的输出
# 第一轮已经逐段对过，这一轮直接比用户看到的那几行（龙头/鞘翅/宝箱/朝向）
echo
echo "== 对拍船的坐标（tools/ShipFinder.java vs findstruct ship） =="
shipbad=0
shiptotal=0
while read -r seed cities; do
    # shellcheck disable=SC2086
    "$PROJECT/out/findstruct" ship "$seed" $cities > "$WORK/ours_ship.txt"
    printf '%s\n' $cities | paste - - > "$WORK/cities.txt"
    java -cp "$PROJECT/out:$GAME_CP" ShipFinder "$seed" "$SIZES" "@$WORK/cities.txt" 2>/dev/null \
        | sed -e 's/rot=NONE/rot=0/' -e 's/rot=CLOCKWISE_90/rot=1/' \
              -e 's/rot=CLOCKWISE_180/rot=2/' -e 's/rot=COUNTERCLOCKWISE_90/rot=3/' \
        > "$WORK/game_ship.txt"
    n=$(grep -c '^CITY' "$WORK/game_ship.txt" || true)
    shiptotal=$((shiptotal + n))
    if diff -q "$WORK/game_ship.txt" "$WORK/ours_ship.txt" > /dev/null; then
        echo "  种子 $seed：$n 个城，船的坐标完全一致 ✅"
    else
        shipbad=$((shipbad + 1))
        echo "  种子 $seed：有差异 ❌"
        diff "$WORK/game_ship.txt" "$WORK/ours_ship.txt" | head -20
    fi
done < "$WORK/seeds.txt"

if [[ "$shipbad" -eq 0 ]]; then
    echo "船也对上了：$shiptotal 个城（有船/没船、龙头/鞘翅/宝箱坐标全部一致）✅"
else
    echo "有 $shipbad 个种子的船对不上 ❌"
    exit 1
fi
