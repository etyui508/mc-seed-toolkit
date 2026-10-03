#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""防篡改机制自测：各种"坏清单"到底会不会被客户端拦下来。

这是**离线**跑的（不联网、不碰线上）—— 拿一把临时生成的密钥冒充"可信公钥"，
然后造出一堆被做过手脚的清单，看客户端认不认。

跑法：python3 tools/tests/test_reject.py
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
APP = os.path.join(ROOT, "app")
sys.path.insert(0, APP)

import ed25519                                        # noqa: E402
import release                                        # noqa: E402
import updater                                        # noqa: E402

OK, BAD = [], []
REAL_URL = "https://mcdownload.bony-doorframe-shortly.top/mc-seed-toolkit-9.9.9.zip"


def check(name, cond, extra=""):
    (OK if cond else BAD).append(name)
    print(("  ✅ " if cond else "  ❌ ") + name + (f"   {extra}" if extra else ""))


def make_pkg(tmp):
    """造一个真包，返回 (路径, sha256, 大小)"""
    path = os.path.join(tmp, "mc-seed-toolkit-9.9.9.zip")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mc-seed-toolkit/app/VERSION", "9.9.9\n")
        z.writestr("mc-seed-toolkit/app/tool.py", "# 假包也得像个工具包\n")
        z.writestr("mc-seed-toolkit/app/probe.py", "X = 1\n")
    data = open(path, "rb").read()
    return path, hashlib.sha256(data).hexdigest(), len(data)


def base_manifest(sha, size):
    return {"name": "mc-seed-toolkit", "version": "9.9.9",
            "zip": "mc-seed-toolkit-9.9.9.zip",
            "url": REAL_URL, "sha256": sha, "size": size, "notes": "自测"}


def serve(man, zip_path):
    """把 updater 的网络那层换掉：拿清单就吐这份，下包就吐本地文件"""
    import io
    from unittest import mock

    class _Resp:
        def __init__(self, data):
            self._d = io.BytesIO(data)
            self.status = 200

        def read(self, n=-1):
            return self._d.read(n)

        def close(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    body = json.dumps(man).encode()
    blob = open(zip_path, "rb").read()

    def fake_open(url, timeout=None, headers=None):
        if url.endswith(".json") or "manifest" in url:
            return _Resp(body)
        return _Resp(blob)

    return mock.patch.object(updater, "_open", fake_open)


def run_case(tmp, root, name, man, zip_path, want_reject, want_text=""):
    """在沙箱工具目录里跑一次真 update()，看它认不认这份清单"""
    with serve(man, zip_path):
        changed, msg = updater.update(verbose=False)
    touched = open(os.path.join(root, "app", "probe.py"), encoding="utf-8").read() != "OLD\n"
    rejected = (not changed) and (not touched)
    why = msg.splitlines()[0] if msg else "（没说话）"
    if want_reject:
        good = rejected and (want_text in (msg or "")) and not touched
    else:
        good = bool(changed) and touched
    check(f"{name} → {'拦住' if want_reject else '放行'}", good, why[:78])
    return msg


def main():
    tmp = tempfile.mkdtemp(prefix="mc-reject-")
    saved_keys = list(release.PUBLIC_KEYS)
    keep = (updater.ROOT, updater.RECORDS, updater.BACKUP_DIR, updater.DIFF_DIR,
            updater.MANAGED_FILE, updater.VERSION_FILE)
    try:
        zip_path, sha, size = make_pkg(tmp)
        root = os.path.join(tmp, "toolkit")
        os.makedirs(os.path.join(root, "app"))
        os.makedirs(os.path.join(root, "记录"))
        open(os.path.join(root, "app", "probe.py"), "w", newline="\n").write("OLD\n")
        open(os.path.join(root, "app", "VERSION"), "w", newline="\n").write("1.0.0\n")
        open(os.path.join(root, ".mc-tool.json"), "w", newline="\n").write('{"seed": 42}\n')

        updater.ROOT = root
        updater.RECORDS = os.path.join(root, "记录")
        updater.BACKUP_DIR = os.path.join(updater.RECORDS, ".update-backup")
        updater.DIFF_DIR = os.path.join(updater.RECORDS, "更新日志")
        updater.MANAGED_FILE = os.path.join(updater.RECORDS, ".managed-files.json")
        updater.VERSION_FILE = os.path.join(root, "app", "VERSION")

        good_seed, good_pub = ed25519.generate_keypair()
        bad_seed, _bad_pub = ed25519.generate_keypair()
        release.PUBLIC_KEYS[:] = [good_pub.hex()]      # 假装这把就是客户端里内置的

        def reset():
            """每条用例都从"旧版本、干净沙箱"开始"""
            open(os.path.join(root, "app", "probe.py"), "w", newline="\n").write("OLD\n")
            open(os.path.join(root, "app", "VERSION"), "w", newline="\n").write("1.0.0\n")
            open(os.path.join(root, ".mc-tool.json"), "w", newline="\n").write('{"seed": 42}\n')

        print("=" * 60)
        print("  防篡改机制自测（离线，造各种坏清单去打真 update()）")
        print("=" * 60)
        print()
        print("① 正常情况：格式对、签名对、白名单地址 —— 该放行")
        good = release.sign_manifest(base_manifest(sha, size), good_seed)
        run_case(tmp, root, "正经清单", good, zip_path, False)
        check("放行的那次确实把文件换了（说明测试台本身是好的）",
              open(os.path.join(root, "app", "probe.py"), encoding="utf-8").read() != "OLD\n")

        print()
        print("② 伪造 / 破损的签名 —— 该拦住")
        reset()
        run_case(tmp, root, "别人的私钥签的（域名被黑的场景）",
                 release.sign_manifest(base_manifest(sha, size), bad_seed),
                 zip_path, True, "签名")
        reset()
        run_case(tmp, root, "压根没签名（sig 字段被删掉）",
                 base_manifest(sha, size), zip_path, True, "签名")
        reset()
        run_case(tmp, root, "签名是一串乱写的十六进制",
                 dict(base_manifest(sha, size), sig="de" * 64, sig_alg="ed25519"),
                 zip_path, True, "签名")
        reset()
        run_case(tmp, root, "换个签名算法名（ed25519 之外）",
                 dict(release.sign_manifest(base_manifest(sha, size), good_seed),
                      sig_alg="rsa-sha256"), zip_path, True, "签名")

        print()
        print("③ 签完名的清单又被改过 —— 该拦住（签名会对不上）")
        signed = release.sign_manifest(base_manifest(sha, size), good_seed)
        for field, value, label in (("sha256", "b" * 64, "把 sha256 改掉"),
                                    ("size", size + 1, "把包大小改掉"),
                                    ("version", "9.9.10", "把版本号改掉"),
                                    ("url", REAL_URL.replace("mcdownload", "evil"),
                                     "把下载地址换成别人家"),
                                    ("notes", "（改过的说明）", "把说明文字改掉")):
            reset()
            run_case(tmp, root, label, dict(signed, **{field: value}), zip_path, True, "签名")

        print()
        print("④ 签名没问题，但地址本身不合规 —— 该拦住（白名单 / 必须 https）")
        for label, url in (("明文 http 的地址",
                            "http://mcdownload.bony-doorframe-shortly.top/x.zip"),
                           ("别人家域名的地址", "https://evil.example.com/x.zip"),
                           ("带端口的怪地址",
                            "https://mcdownload.bony-doorframe-shortly.top:8443/x.zip")):
            reset()
            m = release.sign_manifest(base_manifest(sha, size), good_seed)
            m["url"] = url
            # 这里要测的是"地址本身"（不是签名），所以改完地址再重新签一次
            m = release.sign_manifest({k: v for k, v in m.items()
                                       if k not in ("sig", "sig_alg")}, good_seed)
            with serve(m, zip_path):
                changed, msg = updater.update(verbose=False)
            blocked = (not changed) and any(w in (msg or "")
                                            for w in ("https", "域名", "端口", "用户名"))
            check(f"{label} → 拦住", blocked, (msg or "（没说话）")[:78])

        print()
        print("⑤ 签名没问题、地址也没问题，但包对不上 —— 该拦住（sha / 大小）")
        reset()
        run_case(tmp, root, "包里内容和清单里的 sha256 不一致",
                 release.sign_manifest(
                     dict(base_manifest(sha, size), sha256="c" * 64), good_seed),
                 zip_path, True, "sha256")
        reset()
        run_case(tmp, root, "包大小和清单不一致",
                 release.sign_manifest(
                     dict(base_manifest(sha, size), size=size + 4096), good_seed),
                 zip_path, True, "大小")

        print()
        print("⑥ 清单本身名不对 / 不是 JSON 对象 —— 该拦住")
        reset()
        run_case(tmp, root, "清单里的 name 换成了别的",
                 release.sign_manifest(dict(base_manifest(sha, size), name="别的工具"), good_seed),
                 zip_path, True, "名字")
        reset()
        run_case(tmp, root, "清单里没有版本号",
                 release.sign_manifest(
                     {k: v for k, v in base_manifest(sha, size).items() if k != "version"},
                     good_seed), zip_path, True, "版本号")

        print()
        print("⑦ 确认被拦住之后，本地文件一个都没动")
        check("程序文件还是旧的",
              open(os.path.join(root, "app", "probe.py"), encoding="utf-8").read() == "OLD\n")
        check("版本号还是旧的",
              open(updater.VERSION_FILE, encoding="utf-8").read().strip() == "1.0.0")
        check("种子配置没被动",
              open(os.path.join(root, ".mc-tool.json"), encoding="utf-8").read() == '{"seed": 42}\n')

        print()
        print("⑧ 调试开关还有效吗（MC_UPDATE_ALLOW_UNSIGNED=1）")
        reset()
        updater.ALLOW_UNSIGNED = True
        run_case(tmp, root, "开了开关：没签名的也放行（只有调试能这么干）",
                 base_manifest(sha, size), zip_path, False)
        updater.ALLOW_UNSIGNED = False

        print()
        print("=" * 60)
        print(f"  {len(OK)} 项通过，{len(BAD)} 项失败")
        for b in BAD:
            print("   失败:", b)
        print("=" * 60)
        return 1 if BAD else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        (updater.ROOT, updater.RECORDS, updater.BACKUP_DIR, updater.DIFF_DIR,
         updater.MANAGED_FILE, updater.VERSION_FILE) = keep
        release.PUBLIC_KEYS[:] = saved_keys


if __name__ == "__main__":
    sys.exit(main())
