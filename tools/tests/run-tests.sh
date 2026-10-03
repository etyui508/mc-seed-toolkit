#!/usr/bin/env bash
# 跑测试。发布前会自动跑 --quick 那档。
#
#   bash tools/tests/run-tests.sh          单元 + 防篡改 + 集成（一分钟上下）
#   bash tools/tests/run-tests.sh --quick  单元 + 防篡改（发布门禁用）
#   bash tools/tests/run-tests.sh --full   再加上慢的（末地城等，几分钟）
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$(dirname "$HERE")")"
PY="${PYTHON:-python3}"
MODE="${1:-normal}"
FAILED=0

echo "工具包：$ROOT"
echo
"$PY" "$HERE/test_units.py" || FAILED=1

echo
# out/ 里的二进制是不是这份源码编出来的（改了源码忘了重编 = 发出去的是旧代码）
"$PY" "$ROOT/tools/check-build-sync.py" || FAILED=1

echo
# 防篡改那 22 项（约 45 秒）：签名/哈希/域名白名单这些防线，最该防的就是回归。
# 以前它只有 README 让人手动跑，等于没进任何门禁 —— 现在跟单元测试一起跑。
"$PY" "$HERE/test_reject.py" || FAILED=1

if [ "$MODE" != "--quick" ]; then
    echo
    if [ "$MODE" = "--full" ]; then
        "$PY" "$HERE/test_integration.py" --full || FAILED=1
    else
        "$PY" "$HERE/test_integration.py" || FAILED=1
    fi
    echo
    # 英文界面里不许漏中文（0 行才过）。改了文案就容易漏，所以放在常规档里盯着。
    "$PY" "$HERE/test_en_leak.py" || FAILED=1
fi

echo
if [ "$FAILED" -eq 0 ]; then
    echo "✅ 全部测试通过"
else
    echo "❌ 有测试没过 —— 先别发布"
fi
exit $FAILED
