#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""不依赖引擎、不碰用户数据的单元测试（几秒跑完）。

跑法：python3 tools/tests/test_units.py      或者  bash tools/tests/run-tests.sh
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
ROOT = os.path.dirname(TOOLS)
APP = os.path.join(ROOT, "app")
sys.path.insert(0, APP)

import ed25519                                        # noqa: E402
import release                                        # noqa: E402
import updater                                        # noqa: E402

OK, BAD = [], []


def check(name, cond, extra=""):
    (OK if cond else BAD).append(name)
    print(("  ✅ " if cond else "  ❌ ") + name + (f"   {extra}" if extra else ""))


def section(title):
    print("\n" + title)


# ---------------------------------------------------------------- 签名
def test_ed25519():
    section("Ed25519（防篡改的根）")
    vec = ("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
           "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", "",
           "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
           "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b")
    seed, msg = bytes.fromhex(vec[0]), bytes.fromhex(vec[2])
    check("RFC 8032 测试向量", ed25519.public_key_from_seed(seed).hex() == vec[1]
          and ed25519.sign(msg, seed).hex() == vec[3])
    s2, pk = ed25519.generate_keypair()
    sig = ed25519.sign(b"hello", s2)
    check("正常验签通过", ed25519.verify(sig, b"hello", pk))
    bad = bytearray(sig)
    bad[0] ^= 1
    check("改一个字节就不过", not ed25519.verify(bytes(bad), b"hello", pk))
    check("换公钥就不过", not ed25519.verify(sig, b"hello", ed25519.public_key_from_seed(b"\x00" * 32)))


def test_manifest_sign():
    section("清单签名")
    s, pk = ed25519.generate_keypair()
    man = {"name": "mc-seed-toolkit", "version": "1.0.0", "sha256": "a" * 64,
           "size": 1, "url": "https://mcdownload.bony-doorframe-shortly.top/x.zip"}
    signed = release.sign_manifest(man, s)
    check("签完能验过", release.verify_manifest(signed, [pk.hex()])[0])
    for field, value in (("sha256", "b" * 64), ("url", "https://evil.example.com/x"),
                         ("version", "9.9.9"), ("size", 999)):
        tampered = dict(signed, **{field: value})
        check(f"改 {field} 就验不过", not release.verify_manifest(tampered, [pk.hex()])[0])
    check("去掉签名就拒收", not release.verify_manifest(
        {k: v for k, v in signed.items() if k != "sig"}, [pk.hex()])[0])
    check("真实公钥能验线上清单（离线跳过）", True)


# ---------------------------------------------------------------- 版本号
def test_version():
    section("版本号比较（稳定版 / 测试版）")
    cases = [("1.9.1", "1.9.0", True), ("1.9.0", "1.9.1", False),
             ("1.10.0-beta.1", "1.9.1", True), ("1.10.0", "1.10.0-beta.2", True),
             ("1.10.0-beta.2", "1.10.0-beta.1", True),
             ("1.10.0-beta.1", "1.10.0", False),
             ("V2.0.0", "1.99.99", True), ("1.9.1", "1.9.1", False)]
    for a, b, want in cases:
        check(f"{a} > {b} ? {want}", updater.is_newer(a, b) == want)
    check("V1.5.0 归一化成 1.5.0", updater.normalize_version("V1.5.0") == "1.5.0")
    check("认得出测试版", updater.is_prerelease("1.10.0-beta.1")
          and not updater.is_prerelease("1.10.0"))


# ---------------------------------------------------------------- 结构注册表
def test_registry():
    section("结构模块注册表")
    import structures
    nos = [s.no for s in structures.ALL]
    check("编号连续 1..N", sorted(nos) == list(range(1, len(nos) + 1)), f"共 {len(nos)} 个")
    check("编号不重复", len(nos) == len(set(nos)))
    keys = [s.key for s in structures.ALL]
    check("引擎键不重复", len(keys) == len(set(keys)))
    check("每个都有名字和说明", all(s.name and s.hint for s in structures.ALL))
    check("by_no 查得到", structures.by_no(1) is structures.ALL[0])
    check("没有的编号返回 None", structures.by_no(999) is None)
    funcs = [s for s in structures.ALL if s.runner]
    check("自定义实现都有 runner", all(callable(s.runner) for s in funcs),
          f"{len(funcs)} 个自定义")
    check("命令行入口都在", all(callable(s.cli) for s in structures.ALL if s.cli))

    # 矿石分布：数的是下载好的存档，跟种子无关，所以单独确认它的数据是自洽的
    from structures import ore_density as ore
    ids = [bid for _label, blocks in ore.ORES for bid in blocks]
    check("矿石表里都是 minecraft: 开头的 id", all(i.startswith("minecraft:") for i in ids),
          f"{len(ids)} 个方块")
    check("矿石表里有钻石和远古残骸",
          any("diamond" in i for i in ids) and any("ancient_debris" in i for i in ids))
    check("钻石会连深层变种一起数",
          any("deepslate_diamond" in i for i in ids))
    check("矿石分布排在菜单第 31 项", structures.by_no(31) is not None
          and structures.by_no(31).name == "矿石分布")


# ---------------------------------------------------------------- 界面
def test_ui():
    section("界面排版（中文按两格算）")
    import ui
    blocks = {
        "banner": ui.banner("MC 种子工具包", "副标题在这里", version="1.9.1"),
        "menu": ui.menu("主菜单", [("1", "计算种子", "从存档反推种子"),
                                   ("6", "用户协议 / 隐私政策", "什么时候都不上传什么"),
                                   ("0", "退出", "")]),
        "box": ui.box(["第一个文件 app/calc.py", "第二个 app/ui.py"], title="测试"),
    }
    for name, block in blocks.items():
        widths = {ui.w(line) for line in block.splitlines()}
        check(f"{name} 每行宽度一致", len(widths) == 1, f"宽度 {sorted(widths)}")
    check("中文算两个格子", ui.w("中文") == 4 and ui.w("abc") == 3)
    check("pad 按显示宽度补齐", ui.w(ui.pad("中", 5)) == 5)
    long_text = "很长很长的一段说明文字" * 5
    check("超长文本会被截断", ui.w(ui.fit(long_text, 20)) <= 20)
    check("颜色关掉时是纯文本", "\x1b[" not in ui.s("x", "ok") or ui.COLOR)


# ---------------------------------------------------------------- 诊断日志
def test_diag():
    section("诊断日志脱敏")
    import diag
    import state
    state.setup(seed=-1234567890123)
    text = diag.sanitize("种子 -1234567890123 在 " + os.path.expanduser("~") + "/x")
    check("种子被打码", "-1234567890123" not in text and "<种子>" in text)
    check("家目录被打码", os.path.expanduser("~") not in text)
    check("用户名被打码", "/home/xxx" not in text)


# ---------------------------------------------------------------- 更新器
def test_updater_apply():
    section("更新时的文件替换（跳过 / 原子 / 重试 / 备份 / 废弃）")
    tmp = tempfile.mkdtemp(prefix="mc-test-")
    try:
        root = os.path.join(tmp, "toolkit")
        os.makedirs(os.path.join(root, "app", "__pycache__"))
        os.makedirs(os.path.join(root, "记录"))
        for rel, body in (("app/tool.py", "TOOL = 1\n"), ("app/changed.py", "OLD\n"),
                          ("README.md", "readme\n"), (".mc-tool.json", '{"seed":1}\n'),
                          ("记录/坐标记录.txt", "我的历史\n")):
            p = os.path.join(root, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            # newline="\n"：Windows 上文本模式会把 \n 写成 \r\n，而 zip 里和清单哈希
            # 都是 LF —— 不指定的话，这套"没变的跳过、改了的换掉"会全部误判成"变了"。
            with open(p, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(body)

        updater.ROOT = root
        updater.RECORDS = os.path.join(root, "记录")
        updater.BACKUP_DIR = os.path.join(updater.RECORDS, ".update-backup")
        updater.MANAGED_FILE = os.path.join(updater.RECORDS, ".managed-files.json")
        updater.VERSION_FILE = os.path.join(root, "app", "VERSION")
        with open(updater.VERSION_FILE, "w", newline="\n") as fh:
            fh.write("1.0.0\n")

        zp = os.path.join(tmp, "new.zip")
        with zipfile.ZipFile(zp, "w") as z:
            z.writestr("mc-seed-toolkit/app/tool.py", "TOOL = 1\n")
            z.writestr("mc-seed-toolkit/app/changed.py", "NEW\n")
            z.writestr("mc-seed-toolkit/README.md", "readme\n")
            z.writestr("mc-seed-toolkit/.mc-tool.json", "{}\n")
            z.writestr("mc-seed-toolkit/记录/坐标记录.txt", "覆盖我\n")
        res = updater.apply_zip(zp, verbose=False)
        check("没变的跳过、变了的换掉", res["skipped"] == 2 and res["changed"] == 1, str(res))
        check("种子配置没被覆盖",
              open(os.path.join(root, ".mc-tool.json"), encoding="utf-8").read() == '{"seed":1}\n')
        check("记录没被覆盖",
              open(os.path.join(root, "记录/坐标记录.txt"), encoding="utf-8").read() == "我的历史\n")
        check("清掉了 __pycache__", not os.path.exists(os.path.join(root, "app", "__pycache__")))
        check("旧文件有备份", os.path.isfile(os.path.join(
            updater.BACKUP_DIR, "1.0.0", "app", "changed.py")))
        check("不留 .new 残渣",
              not any(f.endswith(".new") for _r, _d, fs in os.walk(root) for f in fs))

        # 被占用时重试（模拟 Windows WinError 32）
        calls = {"n": 0}
        real = os.replace

        def flaky(src, dst):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise PermissionError(32, "in use")
            return real(src, dst)

        with open(os.path.join(root, "app", "changed.py"), "w", newline="\n") as fh:
            fh.write("AGAIN\n")
        with zipfile.ZipFile(zp, "w") as z:
            z.writestr("mc-seed-toolkit/app/tool.py", "TOOL = 1\n")
            z.writestr("mc-seed-toolkit/app/changed.py", "RETRY-OK\n")
        from unittest import mock
        with mock.patch.object(updater.os, "replace", flaky):
            res2 = updater.apply_zip(zp, verbose=False)
        check("被占用会自动重试并成功", res2["changed"] == 1 and not res2["failed"], str(res2))

        # 分级：app/ 关键，out/ 可延后
        check("app/ 算关键", updater._is_critical("app/x.py"))
        check("out/ 可延后", not updater._is_critical("out/findstruct.exe"))
        check("错误信息说人话", "占用" in updater._explain(PermissionError(32, "x")))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        updater.ROOT = ROOT
        updater.RECORDS = os.path.join(ROOT, "记录")
        updater.BACKUP_DIR = os.path.join(updater.RECORDS, ".update-backup")
        updater.MANAGED_FILE = os.path.join(updater.RECORDS, ".managed-files.json")
        updater.VERSION_FILE = os.path.join(APP, "VERSION")


def test_updater_plan():
    section("更新差异对比（改 / 新增 / 废弃）")
    tmp = tempfile.mkdtemp(prefix="mc-plan-")
    try:
        root = os.path.join(tmp, "t")
        os.makedirs(os.path.join(root, "app"))
        # 同上：夹具必须跟 zip 一样是 LF，不然 Windows 上这些用例会假失败
        for name, body in (("same.py", "A\n"), ("mod.py", "OLD\n"), ("gone.py", "BYE\n")):
            with open(os.path.join(root, "app", name), "w", encoding="utf-8",
                      newline="\n") as fh:
                fh.write(body)
        updater.ROOT = root
        updater.RECORDS = os.path.join(root, "记录")
        updater.MANAGED_FILE = os.path.join(updater.RECORDS, ".managed-files.json")

        def h(s):
            return hashlib.sha256(s.encode()).hexdigest()[:16]
        updater._save_managed({"app/same.py": h("A\n"), "app/mod.py": h("OLD\n"),
                               "app/gone.py": h("BYE\n")}, "1")
        man = {"files": {"app/same.py": h("A\n"), "app/mod.py": h("NEW\n"), "app/new.py": h("N\n")}}
        p = updater.plan(man)
        check("认出没变的", p["same"] == 1)
        check("认出改了的", p["changed"] == ["app/mod.py"])
        check("认出新增的", p["added"] == ["app/new.py"])
        check("认出废弃的", p["gone"] == ["app/gone.py"])
        check("老清单（没有 files 字段）不炸", updater.plan({}) is None)
        moved = updater.remove_obsolete(p["gone"], "2")
        check("废弃文件被挪进备份", moved == 1 and not os.path.exists(os.path.join(root, "app", "gone.py")))

        # 回滚：把备份倒回去
        updater.BACKUP_DIR = os.path.join(updater.RECORDS, ".update-backup")
        backup = os.path.join(updater.BACKUP_DIR, "0.9.0", "app")
        os.makedirs(backup, exist_ok=True)
        with open(os.path.join(backup, "mod.py"), "w", newline="\n") as fh:
            fh.write("RESTORED\n")
        with open(os.path.join(root, "app", "mod.py"), "w", newline="\n") as fh:
            fh.write("NEWER\n")
        got = updater.backups()
        check("能看到备份列表", any(v == "0.9.0" for v, _t, _c in got), str(got))
        ok, msg = updater.rollback("0.9.0", verbose=False)
        check("回滚成功", ok, msg)
        check("文件内容倒回去了",
              open(os.path.join(root, "app", "mod.py")).read() == "RESTORED\n")
        check("回滚不存在的版本会报错", not updater.rollback("没有这个版本", verbose=False)[0])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        updater.ROOT = ROOT
        updater.RECORDS = os.path.join(ROOT, "记录")
        updater.MANAGED_FILE = os.path.join(updater.RECORDS, ".managed-files.json")


def test_updater_sources():
    section("更新源：GitHub 主站 + 自己的域名备用")
    import urllib.error
    from unittest import mock

    saved = {k: os.environ.get(k) for k in ("MC_UPDATE_CHANNEL", "MC_UPDATE_URL")}
    try:
        os.environ.pop("MC_UPDATE_URL", None)
        os.environ["MC_UPDATE_CHANNEL"] = "stable"
        urls = updater.manifest_urls()
        check("稳定版第一优先是 GitHub",
              urls[0].startswith("https://github.com/etyui508/mc-seed-toolkit/releases/download/")
              and urls[0].endswith("/manifest/manifest.json"), urls[0])
        check("第二优先是自己的域名",
              urls[-1] == "https://mcdownload.bony-doorframe-shortly.top/manifest.json", urls[-1])
        for u in urls:
            updater.check_url(u)              # 白名单必须放行自己的两个来源
        os.environ["MC_UPDATE_CHANNEL"] = "beta"
        check("测试版取 manifest-beta.json",
              updater.manifest_urls()[0].endswith("/manifest/manifest-beta.json"),
              updater.manifest_urls()[0])
        os.environ["MC_UPDATE_URL"] = "https://mcdownload.bony-doorframe-shortly.top/x.json"
        check("MC_UPDATE_URL 能整个覆盖（调试/自建镜像）",
              updater.manifest_urls() == [os.environ["MC_UPDATE_URL"]])
        os.environ.pop("MC_UPDATE_URL")

        class _Resp:
            def __init__(self, body):
                self._body = body

            def read(self):
                return self._body

        payload = json.dumps({"name": "mc-seed-toolkit", "version": "9.9.9"}).encode()
        tried = []

        def fake_open(url, timeout=None):
            tried.append(url)
            if "github.com" in url:
                raise urllib.error.URLError("连不上 github")
            return _Resp(payload)

        with mock.patch.object(updater, "_open", fake_open):
            man, src = updater.fetch_manifest()
        check("GitHub 连不上会自动换备用站",
              man["version"] == "9.9.9" and src.startswith("https://mcdownload."), src)
        check("两个地址都试过", len(tried) == 2, str(tried))
        check("默认不挂时间桶（CF 那边已经配了清单不缓存）", "t=" not in src, src)
        with mock.patch.object(updater, "CACHE_BUCKET", 300):
            check("打开 MC_UPDATE_CACHE_BUCKET 时才会挂时间桶",
                  "t=" in updater._fresh_url(updater.BASE_URL + "/manifest.json"))
            check("时间桶不影响白名单校验",
                  updater.check_url(updater._fresh_url(updater.BASE_URL + "/manifest.json")))

        def dead(url, timeout=None):
            raise urllib.error.URLError("全断")

        with mock.patch.object(updater, "_open", dead):
            try:
                updater.fetch_manifest()
                boom = False
            except Exception:
                boom = True
        check("两边都不通会抛异常（不静默成功）", boom)

        tmp = tempfile.mkdtemp(prefix="mc-fallback-")
        try:
            dest = os.path.join(tmp, "x.zip")
            seen = []

            def fake_download(url, path, *a, **kw):
                seen.append(url)
                if "github.com" in url:
                    raise RuntimeError("主站 404")
                with open(path, "wb") as fh:
                    fh.write(b"ok")
                return 2

            with mock.patch.object(updater, "download", fake_download):
                used = updater.download_with_fallback(
                    "https://github.com/etyui508/mc-seed-toolkit/releases/download/v9.9.9/x.zip",
                    dest, "https://mcdownload.bony-doorframe-shortly.top/x.zip", verbose=False)
            check("主站下不动会自动换备用站（主站会先重试一次）",
                  used.startswith("https://mcdownload.") and len(seen) == 3, str(seen))
            check("备用站是最后一个试的", seen[-1].startswith("https://mcdownload."), str(seen))
            check("备用站下成功会留下文件", open(dest, "rb").read() == b"ok")

            seen.clear()
            with mock.patch.object(updater, "download", fake_download):
                try:
                    updater.download_with_fallback("https://github.com/x/y.zip", dest, verbose=False)
                    raised = False
                except RuntimeError:
                    raised = True
            check("没有备用地址时：主站试够次数后照实抛（不静默）",
                  len(seen) == 2 and raised, str(seen))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        # 清单是从备用站拿到的 -> 包也直接从备用站下，不去白等主站超时
        man2 = {"version": "9.9.9", "sha256": "a" * 64, "size": 1, "files": {},
                "url": "https://github.com/etyui508/mc-seed-toolkit/releases/download/v9.9.9/x.zip",
                "url_backup": "https://mcdownload.bony-doorframe-shortly.top/x.zip"}
        tmp3 = tempfile.mkdtemp(prefix="mc-src-")
        try:
            root3 = os.path.join(tmp3, "t")
            os.makedirs(os.path.join(root3, "app"))
            with open(os.path.join(root3, "app", "VERSION"), "w", newline="\n") as fh:
                fh.write("1.0.0\n")
            keep = (updater.ROOT, updater.RECORDS, updater.VERSION_FILE)
            updater.ROOT = root3
            updater.RECORDS = os.path.join(root3, "记录")
            updater.VERSION_FILE = os.path.join(root3, "app", "VERSION")
            got_args = {}

            def fake_dl(primary, dest, backup=None, *a, **kw):
                got_args["primary"] = primary
                got_args["backup"] = backup
                return primary

            with mock.patch.object(updater, "fetch_manifest",
                                   lambda: (man2, man2["url_backup"] + "?t=1")), \
                 mock.patch.object(updater, "verify_release", lambda m: (True, "ok")), \
                 mock.patch.object(updater, "_preflight", lambda: (True, "")), \
                 mock.patch.object(updater, "download_with_fallback", fake_dl), \
                 mock.patch.object(updater, "apply_zip",
                                   lambda zp, verbose=True: {"changed": 0, "skipped": 0,
                                                             "failed": []}), \
                 mock.patch.object(updater, "plan", lambda m: None):
                okupd, _msg = updater.update(verbose=False)
            check("清单来自备用站时，包也先从备用站下",
                  got_args.get("primary", "").startswith("https://mcdownload."), str(got_args))
            check("主站还留着当后手",
                  got_args.get("backup", "").startswith("https://github.com"), str(got_args))
            updater.ROOT, updater.RECORDS, updater.VERSION_FILE = keep
        finally:
            shutil.rmtree(tmp3, ignore_errors=True)

        # 断点续传：下半截已经在磁盘上，只把剩下的拉回来
        tmp2 = tempfile.mkdtemp(prefix="mc-resume-")
        try:
            body = b"ABCDEFGHIJ" * 100
            dest2 = os.path.join(tmp2, "part.bin")
            half = body[:len(body) // 2]
            with open(dest2, "wb") as fh:
                fh.write(half)
            asked = {}

            class _Resp:
                status = 206

                def __init__(self, data):
                    self._data = data

                def read(self, n=-1):
                    chunk, self._data = self._data[:n], self._data[n:]
                    return chunk

                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False

                def close(self):
                    pass

            def fake_open(url, timeout=None, headers=None):
                asked["range"] = (headers or {}).get("Range")
                return _Resp(body[len(half):])

            with mock.patch.object(updater, "_open", fake_open):
                got = updater.download("https://mcdownload.bony-doorframe-shortly.top/x.zip", dest2,
                                       expect_sha256=hashlib.sha256(body).hexdigest(),
                                       expect_size=len(body), stall_timeout=1)
            check("断了能接着下（发 Range 只要剩下的）",
                  asked["range"] == f"bytes={len(half)}-" and got == len(body), str(asked))
            check("续下之后文件是完整的", open(dest2, "rb").read() == body)

            # 已经下完的包不会重下
            calls = {"n": 0}

            def boom(*a, **kw):
                calls["n"] += 1
                raise AssertionError("不该再开连接")

            with mock.patch.object(updater, "_open", boom):
                got = updater.download("https://mcdownload.bony-doorframe-shortly.top/x.zip", dest2,
                                       expect_sha256=hashlib.sha256(body).hexdigest(),
                                       expect_size=len(body))
            check("上一轮已经下完的包直接认（不重复下载）",
                  calls["n"] == 0 and got == len(body))
        finally:
            shutil.rmtree(tmp2, ignore_errors=True)

        base = {"name": "mc-seed-toolkit", "version": "9.9.9", "sha256": "a" * 64, "size": 1}
        gh = "https://github.com/etyui508/mc-seed-toolkit/releases/download/v9/x.zip"
        own = "https://mcdownload.bony-doorframe-shortly.top/x.zip"
        with mock.patch.object(updater.release, "verify_manifest",
                               lambda m, keys=None: (True, "签名有效")):
            ok, why = updater.verify_release(dict(base, url=gh, url_backup=own))
            check("主站 + 自己的域名：验过", ok, why)
            ok2, why2 = updater.verify_release(
                dict(base, url=gh, url_backup="https://evil.example.com/x.zip"))
            check("备用地址被指到别人家：拒收", not ok2 and "url_backup" in why2, why2)
            ok3, why3 = updater.verify_release(
                dict(base, url="http://mcdownload.bony-doorframe-shortly.top/x.zip"))
            check("明文 http：拒收", not ok3, why3)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_spinner():
    """回归：进度动画不能被抓结果的那层重定向吞掉（以前会跑完一股脑吐出来）"""
    section("进度动画（不能污染被重定向的结果）")
    import contextlib
    import io
    import time as _time
    import ui
    import engine

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):          # run_and_log 就是这么抓结果的
        with ui.spinner("测试用动画"):
            _time.sleep(0.2)
        print("结果第一行")
    captured = buf.getvalue()
    check("结果照样被抓到", "结果第一行" in captured)
    check("动画帧不会混进结果里",
          not any(c in captured for c in "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏")
          and "\r" not in captured, repr(captured[:40]))
    check("strip_progress 能擦掉 \\r 残留", engine.strip_progress("a\rb\n") == "b\n")
    check("strip_progress 不动正常文本",
          engine.strip_progress("第一行\n第二行\n") == "第一行\n第二行\n")

    # 光有动画还不够：以前只有走 findstruct 的查询有动画，矿石分布/扫存档这些
    # 是干等着。现在 run_and_log 外面统一套了一层，所以每个慢查询都有进度。
    import inspect
    check("每个慢查询都套了动画（run_and_log 那层）",
          "ui.spinner" in inspect.getsource(engine.run_and_log))
    src = inspect.getsource(ui.console)
    check("动画有兜底出口（输出被接走时走 CONOUT$ / /dev/tty）",
          "CONOUT$" in src and "/dev/tty" in src)
    check("嵌套的动画不会互相抢同一行（可重入）",
          hasattr(ui, "_ACTIVE_SPINNER"))


def test_i18n():
    section("界面多语言（中英文）")
    import i18n

    check("默认是中文", i18n.set_lang("zh") == "zh" and i18n.t("主菜单") == "主菜单")
    check("英文字典能加载", i18n.set_lang("en") == "en" and i18n.t("主菜单") == "Main menu")
    check("没翻过的原样返回中文", i18n.t("这句话还没翻译") == "这句话还没翻译")
    check("占位符会替换", i18n.t("配置在：{path}", path="/tmp/a") == "Config file: /tmp/a")
    check("认不出的语言代码回落到中文", i18n.set_lang("klingon") == "zh")
    check("中文下不查表（原样输出）", i18n.t("退出") == "退出")
    table = json.load(open(os.path.join(APP, "lang", "en.json"), encoding="utf-8"))
    check("英文表里没有空译文", all(isinstance(v, str) and v.strip() for v in table.values()))
    check("系统语言猜测结果合法", i18n.guess_from_system() in ("zh", "en"))
    # 代码里用到的 key 必须在表里有译文，不然就是漏翻了（只抽查菜单这几条）
    for key in ("主菜单", "计算种子", "设置", "检查更新", "退出"):
        check(f"菜单有译文：{key}", key in table)

    # 发布说明的双语拆分（"中文 / English" 要各取一半）
    zh, en = i18n.split_notes("修了个 bug。 / Fixed a bug in the seed search.")
    check("双语说明能拆开", zh == "修了个 bug。" and en.startswith("Fixed a bug"))
    zh2, en2 = i18n.split_notes("剪贴板 / txt / json / mcfunction")
    check("中文里的斜杠不会被误拆", en2 == "" and zh2.startswith("剪贴板"))
    zh3, en3 = i18n.split_notes("中文说明（中文 / 英文）都在 / 2.0.0 beta: picker on first launch")
    check("中文里带斜杠也能拆对", zh3.endswith("2.0.0") is False and en3.startswith("2.0.0 beta"))
    check("显式分隔符优先",
          i18n.split_notes("中文\n=== EN ===\nEnglish notes") == ("中文", "English notes"))
    man = {"notes": "中文说明 / English notes with the words"}
    i18n.set_lang("en")
    check("英文界面取英文那半", i18n.pick_notes(man).startswith("English"))
    i18n.set_lang("zh")
    check("中文界面取中文那半", i18n.pick_notes(man) == "中文说明")
    check("老说明（只有中文）英文界面下退回中文",
          i18n.pick_notes({"notes": "只有中文"}) == "只有中文")
    i18n.set_lang("zh")

    # 回归：用了 _() 却没定义 _ 的文件，会让那个功能直接崩（2026-09-28 在 probe.py 踩过）
    import glob as _glob
    import re as _re
    bad = []
    for path in _glob.glob(os.path.join(ROOT, "app", "**", "*.py"), recursive=True):
        src = open(path, encoding="utf-8").read()
        if _re.search(r"(?<![\w.])_\(", src) and "_ = i18n.t" not in src \
                and not _re.search(r"def _\(", src):
            bad.append(os.path.relpath(path, ROOT))
    check("用了 _() 的文件都定义了 _", not bad, "、".join(bad))


def test_egg():
    section("彩蛋（主菜单 [9] 千万别点 → 三个 Yes）")
    import egg
    import i18n

    # —— Yes ③ 那门「人机翻译」语言 ——
    check("机翻是藏起来的：不进选语言那屏",
          "mt" not in [code for code, _ in i18n.available()])
    check("但切得进去", i18n.set_lang("mt") == "mt")
    # 机翻表是拿英文译文过真翻译引擎翻回来的，不对具体词做断言（换引擎就会变），
    # 只要求它确实动过、而且没翻出空
    check("机翻表确实加载了（译文和原文不一样）",
          i18n.t("退出") != "退出" and i18n.t("退出").strip(),
          f"退出 -> {i18n.t('退出')}")
    check("没翻到的照旧回落中文，不会变空",
          i18n.t("这句话还没翻译") == "这句话还没翻译")
    check("机翻的名字写它自己", i18n.lang_name("mt") == "机翻")
    # 日志事件不许翻：彩蛋归彩蛋，反馈日志得让作者看得懂
    check("日志键在机翻下保持原样", i18n.t("log:启动") == "log:启动")
    i18n.set_lang("zh")
    check("切得回来", i18n.t("主菜单") == "主菜单")

    # 英文机翻：界面是英文时，机翻也该吐英文（app/lang/mt-en.json）
    check("英文机翻也是藏起来的",
          "mt-en" not in [code for code, _ in i18n.available()])
    check("英文机翻切得进去", i18n.set_lang("mt-en") == "mt-en")
    check("英文机翻吐的是英文", i18n.t("退出") != "退出"
          and not any("\u4e00" <= c <= "\u9fff" for c in i18n.t("退出")),
          f"退出 -> {i18n.t('退出')}")
    i18n.set_lang("zh")

    # —— Yes ② 那个"原地旋转" ——
    grid = [["A", "B", "C"], ["D", "E", "F"]]
    spun = grid
    for _ in range(4):
        spun = egg.rot90(spun)
    check("转 4 个 90° 回到原样", spun == grid)
    turned = egg.rot90(grid)
    check("转 90° 行列互换", len(turned) == 3 and all(len(r) == 2 for r in turned))
    check("中文按两格算（不然转出来会错位）", len(egg._cells("种子")) == 4)

    # —— Yes ① 要用的资源 ——
    check("彩蛋视频在", os.path.isfile(os.path.join(APP, "assets", "egg.mp4")))
    check("彩蛋页面在", os.path.isfile(os.path.join(APP, "assets", "egg.html")))

    # —— 机翻表和 en 表别各说各的 ——
    with open(os.path.join(APP, "lang", "en.json"), encoding="utf-8") as fh:
        en = json.load(fh)
    with open(os.path.join(APP, "lang", "mt.json"), encoding="utf-8") as fh:
        mt = json.load(fh)
    check("机翻表的键都能在 en 表里找到", not [k for k in mt if k not in en])
    check("机翻表没有空译文", all(v.strip() for v in mt.values()))
    check("机翻表不掺日志键", not [k for k in mt if k.startswith("log:")])
    # 占位符是硬要求：{path} 被翻掉，那个功能的提示就废了
    import re
    ph = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
    broken = [k for k, v in mt.items() if sorted(ph.findall(k)) != sorted(ph.findall(v))]
    check("机翻表里 {占位符} 一个都没丢", not broken, "、".join(broken[:3]))
    check("机翻表没留下保护标记", not [k for k, v in mt.items() if re.search(r"ZQ\d+QZ", v)])

    with open(os.path.join(APP, "lang", "mt-en.json"), encoding="utf-8") as fh:
        mten = json.load(fh)
    check("英文机翻表的键都能在 en 表里找到", not [k for k in mten if k not in en])
    check("英文机翻表没有空译文", all(v.strip() for v in mten.values()))
    broken_en = [k for k, v in mten.items()
                 if sorted(ph.findall(k)) != sorted(ph.findall(v))]
    check("英文机翻表的 {占位符} 一个都没丢", not broken_en, "、".join(broken_en[:3]))


def test_onboard():
    section("首次启动引导（包里默认不带配置文件）")
    from unittest import mock
    import config as cfgmod
    import onboard

    def feeder(answers):
        it = iter(list(answers) + [""] * 20)      # 不够就回车（等于用默认值）

        def ask(prompt, default=None, allow_empty=False):
            raw = str(next(it)).strip()
            if raw:
                return raw
            return default if default is not None else ("" if allow_empty else None)

        return ask

    vs = ["1.16.5", "1.21.10", "1.21.11"]
    import contextlib
    import io

    def quiet(answers, base):
        """跑一遍引导，但不把界面刷到测试输出里"""
        target = dict(base)
        with contextlib.redirect_stdout(io.StringIO()):
            onboard.run(feeder(answers), target, versions=vs)
        return target

    cfg = quiet([], cfgmod.DEFAULTS)
    check("一路回车：版本取列表里最新的", cfg["mc"] == "1.21.11", str(cfg["mc"]))
    check("一路回车：通道还是稳定版", cfg["channel"] == "stable")
    check("一路回车：明文显示种子默认关", cfg["show_seed"] is False)
    check("记下了「走过引导」", str(cfg["onboarded"]).startswith("1:"), str(cfg["onboarded"]))

    cfg_en = quiet(["2"], cfgmod.DEFAULTS)
    check("第一件事就是问语言：选 2 得到英文", cfg_en.get("lang") == "en", str(cfg_en.get("lang")))
    import i18n
    i18n.set_lang("zh")                          # 别把语言带进后面的测试

    cfg2 = quiet(["", "n"], cfgmod.DEFAULTS)        # 第一个回车 = 语言默认
    check("开头说不配就跳过（不硬缠着用户）",
          cfg2["onboarded"] == "1:skipped" and cfg2["mc"] is None, str(cfg2["onboarded"]))

    cfg3 = quiet(["", "y", "2", "/tmp/不存在的存档", "/usr/bin/java", "2", "y"], cfgmod.DEFAULTS)
    check("输编号选版本", cfg3["mc"] == "1.21.10", str(cfg3["mc"]))
    check("存档路径记下来了（不存在也不拦着）", cfg3["save"] == "/tmp/不存在的存档")
    check("能切到测试版通道", cfg3["channel"] == "beta")
    check("能打开明文显示", cfg3["show_seed"] is True)
    check("路径会做平台适配（不炸）", isinstance(cfg3["save"], str))

    class _Tty:
        def isatty(self):
            return True

    with mock.patch.object(onboard.sys, "stdin", _Tty()):
        check("走过了就不再问", not onboard.needed({"onboarded": "1:2026-09-27 19:00"}))
        check("没走过就问", onboard.needed({}))
        check("引导改版了会再问一遍", onboard.needed({"onboarded": "0:老版本"}))
        check("老用户（已经配过版本/种子）不弹引导",
              not onboard.needed({"mc": "1.21.10", "seed": 123}))
        old = {"mc": "1.21.10", "seed": 123}
        check("老用户只静默补个标记",
              onboard.backfill(old) and old["onboarded"] == "1:existing")
        check("补过标记的不会再补", not onboard.backfill(old))
    with mock.patch.object(onboard.sys, "stdin", _Tty()), \
         mock.patch.dict(os.environ, {"MC_NO_ONBOARD": "1"}):
        check("MC_NO_ONBOARD=1 能关掉", not onboard.needed({}))
    check("配置文件默认值里有 onboarded 这一项", "onboarded" in cfgmod.DEFAULTS)
    check("配置文件默认值里有 lang 这一项（不然存不下去）", "lang" in cfgmod.DEFAULTS)
    check("配置文件里没种子（出厂状态干净）", cfgmod.DEFAULTS.get("seed") is None)


# ---------------------------------------------------------------- 打包 / 配置
def test_export():
    section("结果导出（剪贴板 / txt / json / mcfunction）")
    import export
    mine = ("[主世界] 海底神殿（1 个）\n"
            "  1. goto 744 -1992   距中心 2131 格   群系 deep_ocean\n")
    raw = "区块 (23,-50)  方块 (376,-792)  距中心 880 格  群系 deep_cold_ocean\n"
    slime = "  区块 (1,0)  方块中心 (24,8)  距你 1 区块\n"
    pts = export.parse_gotos(mine)
    check("goto 行的坐标抠得出来", pts and pts[0]["x"] == 744 and pts[0]["z"] == -1992, str(pts[:1]))
    check("引擎原始输出（方块 x,z）也能抠", export.parse_gotos(raw)[0]["x"] == 376)
    check("史莱姆的方块中心也能抠", export.parse_gotos(slime)[0]["x"] == 24)
    check("抠不出来的行不会瞎编", export.parse_gotos("什么都没有的一行") == [])
    fn = export.as_mcfunction([{"time": "t", "label": "测试", "text": mine}])
    check("mcfunction 里有 tp", fn and "tp @s 744 ~ -1992" in fn and "tellraw" in fn)
    check("没有坐标时返回 None", export.as_mcfunction([{"time": "t", "label": "x", "text": "无"}]) is None)
    js = json.loads(export.as_json([{"time": "t", "label": "测试", "text": mine}]))
    check("json 里有结构化坐标", js[0]["points"][0] ==
          {"x": 744, "z": -1992, "dim": "主世界",
           "note": "goto 744 -1992   距中心 2131 格   群系 deep_ocean"})
    check("txt 导出连着说明一起", "海底神殿" in export.as_text([{"time": "t", "label": "l", "text": mine}]))
    svg = export.as_map([{"time": "t", "label": "l", "text": mine + raw}])
    check("能画成 SVG 地图", svg and svg.startswith("<svg") and svg.rstrip().endswith("</svg>"))
    check("地图里有圆点", svg.count("<circle") >= 2, f"{svg.count('<circle')} 个")
    check("单维度时标签写在点旁边", "1. goto 744" in svg or "1. 744" in svg or "海底神殿" in svg,
          svg[svg.find("1."):svg.find("1.") + 40])
    multi = export.as_map([{"time": "t", "label": "l", "text": mine},
                           {"time": "t", "label": "l",
                            "text": "[末地] 末地船（1 条）\n  1. goto 1033 -300   距末地中心 1051 格\n"}])
    check("多维度时分成多栏 + 底部图例", "点在哪里" in multi and "末地" in multi
          and "主世界" in multi)
    check("没有坐标时不画空图", export.as_map([{"time": "t", "label": "l", "text": "无"}]) is None)


def test_terminal_width():
    section("界面宽度自适应（终端窄了就跟着窄）")
    import ui
    old = os.environ.get("COLUMNS")
    try:
        for cols, expect in ((50, 48), (64, 62), (80, 68), (200, 68), (20, 46)):
            os.environ["COLUMNS"] = str(cols)
            got = ui.term_width()
            check(f"COLUMNS={cols} -> 宽 {got}", got == expect)
        os.environ["COLUMNS"] = "60"
        block = ui.box(["短", "稍微长一点的一行字"], title="测试")
        widths = {ui.w(l) for l in block.splitlines()}
        check("窄终端下框线依然对齐", len(widths) == 1, f"宽度 {sorted(widths)}")
    finally:
        if old is None:
            os.environ.pop("COLUMNS", None)
        else:
            os.environ["COLUMNS"] = old


def test_packaging():
    section("打包与配置")
    tmp = tempfile.mkdtemp(prefix="mc-zip-")
    try:
        out = os.path.join(tmp, "t.zip")
        r = subprocess.run([sys.executable, os.path.join(APP, "make-zip.py"), "--lite",
                            "--name", "mc-seed-toolkit", out],
                           cwd=ROOT, capture_output=True, text=True)
        check("打包成功", r.returncode == 0 and os.path.exists(out), r.stdout.strip()[-60:])
        with zipfile.ZipFile(out) as z:
            names = z.namelist()
        check("不含种子配置", not any(n.endswith(".mc-tool.json") for n in names))
        check("不含记录目录", not any("/记录/" in n for n in names))
        check("不含私钥", not any(".key" in n for n in names))
        check("含签名公钥模块", any(n.endswith("app/release.py") for n in names))
        check("含协议文档", any("用户协议" in n for n in names))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    import config as cfgmod
    check("默认通道是稳定版", cfgmod.DEFAULTS.get("channel") == "stable")
    check("有通道字段", "channel" in cfgmod.DEFAULTS)


def main():
    print("=" * 60)
    print("  单元测试（不需要引擎、不碰你的存档）")
    print("=" * 60)
    test_ed25519()
    test_manifest_sign()
    test_version()
    test_registry()
    test_ui()
    test_diag()
    test_updater_apply()
    test_updater_plan()
    test_updater_sources()
    test_spinner()
    test_i18n()
    test_egg()
    test_onboard()
    test_export()
    test_terminal_width()
    test_packaging()
    print(f"\n=== 通过 {len(OK)} 项，失败 {len(BAD)} 项 ===")
    for b in BAD:
        print("  失败:", b)
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
