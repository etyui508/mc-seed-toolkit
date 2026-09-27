#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真跑引擎的集成测试。

会在临时目录里复制一份工具包再跑 —— 不碰你自己的 记录/ 和 .mc-tool.json。
需要 out/findstruct（包里随带）；找不到就整体跳过。

跑法：python3 tools/tests/test_integration.py [--full]
      --full 会加上慢的（大范围并行扫描、末地城），发布门禁默认不跑。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
# 随便挑的一个测试种子（跟作者自己的存档没关系 —— 这里故意不用真种子）
SEED = -2026092700000000001
VER = "1.21.10"
FULL = "--full" in sys.argv

OK, BAD, SKIP = [], [], []


def check(name, cond, extra="", skip=False):
    if skip:
        SKIP.append(name)
        print(f"  ⏭  {name}   {extra}")
        return
    (OK if cond else BAD).append(name)
    print(("  ✅ " if cond else "  ❌ ") + name + (f"   {extra}" if extra else ""))


def sandbox():
    """复制一份能跑的工具包到临时目录（不带 runtime/，几 MB）"""
    tmp = tempfile.mkdtemp(prefix="mc-it-")
    for name in ("app", "tools", "out", "docs", "mods", "mod-src", "verify"):
        src = os.path.join(ROOT, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(tmp, name),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in ("README.md", "使用说明.md", "run.sh", "START.bat"):
        p = os.path.join(ROOT, name)
        if os.path.isfile(p):
            shutil.copy2(p, os.path.join(tmp, name))
    with open(os.path.join(tmp, ".mc-tool.json"), "w", encoding="utf-8") as fh:
        json.dump({"seed": SEED, "mc": VER, "show_seed": False, "agreed": "1:test",
                   "channel": "stable"}, fh)
    return tmp


def run(box, args, stdin=None, timeout=300, env_extra=None):
    env = dict(os.environ, MC_NO_UPDATE="1", MCVER=VER,
               PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    if env_extra:
        env.update(env_extra)
    t0 = time.time()
    try:
        p = subprocess.run([sys.executable] + args, cwd=box, input=stdin,
                           capture_output=True, text=True, timeout=timeout, env=env)
        return p.stdout + p.stderr, p.returncode, time.time() - t0
    except subprocess.TimeoutExpired:
        return f"（超时 {timeout}s）", -1, time.time() - t0


def cli(box, name, args, want, timeout=300):
    out, rc, dt = run(box, ["app/calc.py"] + args, timeout=timeout)
    bad = "Traceback" in out or (want and want not in out) or (rc not in (0, -1))
    check(name, not bad, f"{dt:.1f}s" if not bad else out.strip().splitlines()[-1][:70])


def main():
    findstruct = os.path.join(ROOT, "out", "findstruct")
    if not os.path.exists(findstruct) and not os.path.exists(findstruct + ".exe"):
        print("没有 out/findstruct —— 跳过全部集成测试（精简版？）")
        return 0

    box = sandbox()
    print("=" * 60)
    print(f"  集成测试（沙箱：{box}）")
    print("=" * 60)
    try:
        print("\n① 命令行：每个子命令都真跑一遍")
        cli(box, "struct 海底神殿", ["struct", "--name", "海底神殿", "--center", "0", "0",
                                     "--radius", "2000", "--top", "1"], "海底神殿")
        cli(box, "struct 村庄", ["struct", "--name", "村庄", "--center", "0", "0",
                                 "--radius", "900", "--top", "1"], "村庄")
        cli(box, "struct 下界要塞（÷8 换算）", ["struct", "--name", "下界要塞", "--center", "0", "0",
                                              "--radius", "800", "--top", "1",
                                              "--from", "overworld"], "下界")
        cli(box, "stronghold", ["stronghold", "--center", "0", "0", "--top", "1"], "要塞")
        cli(box, "biome", ["biome", "--at", "100", "200"], "->")
        cli(box, "find-biome", ["find-biome", "--name", "plains", "--center", "0", "0",
                                "--radius", "800"], "最近的 plains")
        cli(box, "slime", ["slime", "--center", "0", "0", "--radius", "300", "--top", "1"],
            "史莱姆区块")
        cli(box, "overview", ["overview", "--center", "0", "0", "--radius", "800",
                              "--top", "2"], "附近结构总览")
        cli(box, "ships", ["ships", "--center", "0", "0", "--radius", "2500", "--top", "1"],
            "末地船")

        print("\n② 并行扫描（radius ≥ 16000 格才走这条路 —— 曾经因为缺正则静默失效）")
        out, rc, dt = run(box, ["app/calc.py", "struct", "--name", "海底神殿", "--center", "0", "0",
                                "--radius", "20000", "--top", "2"], timeout=420)
        check("大范围 struct 能出结果", "海底神殿" in out and "Traceback" not in out, f"{dt:.1f}s")
        out2, _rc, _dt = run(box, ["-c",
                                   "import sys;sys.path.insert(0,'app');import state,engine;"
                                   f"state.setup(seed={SEED},ver='{VER}');"
                                   "print('NONE' if engine._run_find_parallel(0,0,1250,5,0,0,True) is None"
                                   " else 'OK')"], timeout=420)
        check("并行扫描合并本身可用", "OK" in out2, "" if "OK" in out2 else out2.strip()[-60:])

        print("\n③ 交互菜单（喂按键，模拟真人操作）")
        # 结构菜单在 calc.py；主菜单那几个（协议/设置…）在 tool.py
        menus = [("app/calc.py", "结构菜单 1 海底神殿", "1\n\n\n800\n1\n0\n", "海底神殿"),
                 ("app/calc.py", "结构菜单 5 要塞", "5\n\n\n0\n", "要塞"),
                 ("app/calc.py", "结构菜单 24 末地船（扫存档）路径不对要友好报错",
                  "24\n/tmp/没有这个目录\n0\n", "不存在"),
                 ("app/calc.py", "结构菜单 27 查群系", "27\n100 200\n\n0\n", "->"),
                 ("app/calc.py", "结构菜单 29 史莱姆", "29\n\n300\n1\n0\n", "史莱姆区块"),
                 ("app/tool.py", "主菜单 6 用户协议", "6\n0\n", "隐私政策")]
        for entry, name, keys, want in menus:
            out, rc, dt = run(box, [entry], stdin=keys, timeout=300)
            check(name, want in out and "Traceback" not in out, f"{dt:.1f}s")

        # 第一次用：沙箱里造一份"没有配置文件"的包，看引导会不会自己跑起来
        print("\n③b 首次启动引导（包里不带配置文件）")
        fresh = sandbox()
        try:
            os.remove(os.path.join(fresh, ".mc-tool.json"))
            env_extra = {"MC_ONBOARD": "1"}          # 管道里不是真终端，这里强制走一遍
            # 第一个回车 = 语言选默认（中文）；后面一路回车；最后退到主菜单选 0
            keys = "\n" + "y\n\n\n\n\n\n0\n"
            out, rc, dt = run(fresh, ["app/tool.py"], stdin=keys, timeout=300, env_extra=env_extra)
            check("引导真的跑起来了", "欢迎用 MC 种子工具包" in out and "配好了" in out, f"{dt:.1f}s")
            check("语言是第一件事问的", "请选择语言" in out and "Choose your language" in out)
            cfg_path = os.path.join(fresh, ".mc-tool.json")
            check("配置是引导的时候现写的", os.path.isfile(cfg_path))
            made = json.load(open(cfg_path, encoding="utf-8"))
            check("语言记下来了", made.get("lang") in ("zh", "en"), str(made.get("lang")))
            check("引导完记了 onboarded 标记", str(made.get("onboarded", "")).startswith("1:"),
                  str(made.get("onboarded")))
            check("版本也配好了", bool(made.get("mc")), str(made.get("mc")))
            check("种子还是空的（出厂状态不塞种子）", made.get("seed") is None)
            # 第二次启动就不该再问一遍了
            out2, _rc2, _dt2 = run(fresh, ["app/tool.py"], stdin="0\n", timeout=300,
                                   env_extra=env_extra)
            check("第二次启动不再走引导", "欢迎用 MC 种子工具包" not in out2)
        finally:
            shutil.rmtree(fresh, ignore_errors=True)

        if FULL:
            print("\n④ 慢的（--full 才跑）")
            cli(box, "末地城（挑没被搜过的）", ["endcity", "--top", "1"], "末地城", timeout=600)

        print("\n⑤ 别的入口")
        for name, args, want in (("mcvers 表", ["app/mcvers.py"], "柱子✓"),
                                 ("config 查看", ["app/config.py"], "配置文件"),
                                 ("diag 环境", ["app/diag.py"], "Python"),
                                 ("ed25519 自检", ["app/ed25519.py"], "7/7"),
                                 ("calc.py --help", ["app/calc.py", "--help"], "struct")):
            out, rc, dt = run(box, args)
            check(name, want in out and "Traceback" not in out)

        print("\n⑥ 沙箱没被污染")
        check("记录里只有测试产生的东西",
              all(not f.startswith("..") for f in os.listdir(os.path.join(box, "记录")))
              if os.path.isdir(os.path.join(box, "记录")) else True)
        check("种子配置还是测试那个",
              json.load(open(os.path.join(box, ".mc-tool.json"), encoding="utf-8"))["seed"] == SEED)
    finally:
        shutil.rmtree(box, ignore_errors=True)

    print(f"\n=== 通过 {len(OK)} 项，失败 {len(BAD)} 项"
          + (f"，跳过 {len(SKIP)} 项" if SKIP else "") + " ===")
    for b in BAD:
        print("  失败:", b)
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
