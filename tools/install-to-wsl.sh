#!/usr/bin/env bash
# 把 U 盘上这套东西装进 WSL 家目录（推荐！比直接在 U 盘跑更稳、更快）
set -euo pipefail

HERE="$(dirname "$(cd "$(dirname "$0")" && pwd)")"      # 工具包根目录（本脚本在 tools/ 下）
DEST="${1:-$HOME/mc-seed-toolkit-full}"

echo "从 $HERE 复制到 $DEST ..."
mkdir -p "$DEST"
cp -rf "$HERE"/. "$DEST"/
chmod +x "$DEST"/run.sh "$DEST"/out/findstruct 2>/dev/null || true

echo
echo "装好了，检查环境："
python3 -c "print('  python3:', __import__('sys').version.split()[0])"
"$DEST"/runtime/jre/bin/java -version 2>&1 | head -1 | sed 's/^/  java: /'
echo "  群系检查（cubiomes 版）: $( [[ -x "$DEST/out/findstruct" ]] && echo 可用 || echo 缺失 )"
echo
echo "以后这样启动："
echo "  cd $DEST && bash run.sh"
echo "（或者 python3 app/tool.py）"
