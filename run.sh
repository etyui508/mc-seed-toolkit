#!/usr/bin/env bash
# U 盘版启动器（WSL / Linux 满血版）
#   · 自动挑一个"真的能跑"的 Java（优先包里自带的，其次系统的）
#   · 在 Windows 的 Git Bash / MSYS 里会直接告诉你该去哪跑
#   · U 盘不能执行程序时，自动复制到本机缓存里跑（配置和种子仍留在原处）
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"

# 解压时多套了一层（里面还有个同名文件夹）也能自动找到真正的工具目录
RELOCATED=""
if [ ! -f "$HERE/app/tool.py" ]; then
    inner="$(find "$HERE" -maxdepth 3 -name tool.py -print -quit 2>/dev/null || true)"
    if [ -n "$inner" ]; then
        HERE="$(dirname "$(dirname "$inner")")"
        RELOCATED="1"
    fi
fi

# ---------- 界面语言：跟工具里的语言设置对齐 ----------
# 优先环境变量 MC_LANG（app/i18n.py 也是用它把语言传给子进程），
# 其次读 .mc-tool.json 里的 "lang"；都认不出来就是中文。
UI_LANG="zh"
case "${MC_LANG:-}" in
    en*|EN*) UI_LANG="en" ;;
    zh*|ZH*) UI_LANG="zh" ;;
    *)
        if [ -f "$HERE/.mc-tool.json" ] \
           && grep -q '"lang"[[:space:]]*:[[:space:]]*"en"' "$HERE/.mc-tool.json" 2>/dev/null; then
            UI_LANG="en"
        fi
        ;;
esac

# 同一句话两种说法，按上面的 UI_LANG 挑一个
say() {
    if [ "$UI_LANG" = "en" ]; then printf '%s\n' "$2"; else printf '%s\n' "$1"; fi
}

if [ -n "$RELOCATED" ]; then
    say "（自动定位到工具目录：$HERE）" "(toolkit located at: $HERE)"
fi

# ---------- 0) Windows 原生（Git Bash / MSYS）也能跑了：用 Windows 版 Python + .exe 工具 ----------
case "$(uname -s 2>/dev/null || echo unknown)" in
    MINGW*|MSYS*|CYGWIN*|Windows*)
        say "（检测到 Windows 的 Git Bash / MSYS —— 走 Windows 原生模式，用 findstruct.exe + 你的 Java）" \
            "(Git Bash / MSYS on Windows detected - running natively with findstruct.exe + your Java)"
        PY=""
        for c in "py -3" python.exe python py; do
            if command -v ${c%% *} >/dev/null 2>&1; then PY="$c"; break; fi
        done
        if [ -z "$PY" ]; then
            say "没找到 Python 3。装一个：https://www.python.org/downloads/ （安装时勾选 Add python.exe to PATH）" \
                "Python 3 not found. Install it: https://www.python.org/downloads/ (tick \"Add python.exe to PATH\")"
            exit 1
        fi
        export PYTHONUTF8=1 PYTHONIOENCODING=utf-8
        cd "$HERE" || exit 1
        exec $PY app/tool.py
        ;;
esac

# ---------- 1) Python ----------
PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
    say "缺少 Python 3。装一下：sudo apt update && sudo apt install -y python3" \
        "Python 3 is missing. Install it: sudo apt update && sudo apt install -y python3"
    exit 1
fi

# ---------- 2) 挑一个真能跑的 Java ----------
find_java() {
    local cand
    for cand in "$HERE/runtime/jre/bin/java" "$(command -v java 2>/dev/null || true)"; do
        [ -n "$cand" ] || continue
        [ -x "$cand" ] || continue
        if "$cand" -version >/dev/null 2>&1; then
            printf '%s' "$cand"
            return 0
        fi
    done
    return 1
}

if JAVA="$(find_java)"; then
    export TOOLKIT_JAVA="$JAVA"
    say "（使用 Java：$JAVA）" "(using Java: $JAVA)"
else
    say "警告：没有找到能用的 Java —— 包里自带的那份在 $HERE/runtime/jre/bin/java" \
        "Warning: no working Java found - the bundled one should be at $HERE/runtime/jre/bin/java"
    say "      如果它跑不起来，可以 sudo apt install -y openjdk-21-jre-headless" \
        "      if that one does not run, try: sudo apt install -y openjdk-21-jre-headless"
fi

# ---------- 3) U 盘不让执行程序时，复制到本机缓存跑 ----------
RUN_DIR="$HERE"
if [ -x "$HERE/out/findstruct" ]; then
    set +e
    "$HERE/out/findstruct" >/dev/null 2>&1
    rc=$?
    set -e
    if [ "$rc" -eq 126 ] || [ "$rc" -eq 127 ]; then
        RUN_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/mc-seed-toolkit-full"
        mkdir -p "$RUN_DIR"
        cp -rf "$HERE"/. "$RUN_DIR"/ 2>/dev/null || true
        mkdir -p "$RUN_DIR/记录"
        for f in "$HERE"/.mc-tool.json "$HERE"/记录/.cache-gateways-*.txt; do
            [ -e "$f" ] || continue
            if [ "$(dirname "$f")" = "$HERE/记录" ]; then
                ln -sfn "$f" "$RUN_DIR/记录/$(basename "$f")"
            else
                ln -sfn "$f" "$RUN_DIR/$(basename "$f")"
            fi
        done
        say "（这个盘不能直接执行程序，已复制到 $RUN_DIR 运行；配置和种子仍留在原处）" \
            "(this drive can not run programs directly, so it was copied to $RUN_DIR; config and seeds stay where they are)"
    fi
fi

cd "$RUN_DIR"
exec "$PY" app/tool.py
