#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给发布清单签名（发布机专用）。

私钥默认放在 ~/.mc-keys/mc-seed-toolkit.key，**绝不能放进网站目录**。

  python3 tools/sign-release.py --genkey          # 生成一对新密钥
  python3 tools/sign-release.py --sign 清单.json    # 给清单加上 sig 字段
  python3 tools/sign-release.py --verify 清单.json  # 验一下（用内置公钥）
  python3 tools/sign-release.py --show-key        # 显示私钥对应的公钥
"""
import argparse
import json
import os
import pathlib
import stat
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(os.path.dirname(HERE), "app")
sys.path.insert(0, APP)

import ed25519                                        # noqa: E402
import release                                        # noqa: E402

DEFAULT_KEY = os.path.expanduser("~/.mc-keys/mc-seed-toolkit.key")


def load_key(path):
    with open(path, encoding="utf-8") as fh:
        text = fh.read().strip()
    if text.startswith("{"):                          # 兼容带元信息的格式
        text = json.loads(text)["private_key"]
    seed = bytes.fromhex(text)
    if len(seed) != 32:
        raise SystemExit(f"私钥长度不对（{len(seed)} 字节，应该是 32）")
    return seed


def genkey(path):
    if os.path.exists(path):
        raise SystemExit(f"{path} 已经存在了。要换钥匙就先把旧的挪走（别直接覆盖，"
                         f"旧公钥还在客户端里）。")
    seed, pub = ed25519.generate_keypair()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(seed.hex() + "\n")
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)   # 0600，只有自己能读
    except OSError:
        pass
    print(f"私钥写到 {path}（权限 0600，别拷进网站目录、别提交到 git）")
    print(f"公钥（十六进制）：\n  {pub.hex()}")

    # 顺手把公钥填进 app/release.py 的 PUBKEYS 区
    rel_path = pathlib.Path(APP, "release.py")
    text = rel_path.read_text(encoding="utf-8")
    line = f'    "{pub.hex()}",'
    if line.strip() not in text:
        text = text.replace("    # PUBKEYS-BEGIN\n", f"    # PUBKEYS-BEGIN\n{line}\n")
        rel_path.write_text(text, encoding="utf-8")
        print(f"已经把公钥写进 {rel_path}")
    print("\n⚠ 私钥丢了 = 以后再也签不出能被客户端接受的包（只能发新版本内置新公钥）")


def sign(path, key_path):
    seed = load_key(key_path)
    man = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    signed = release.sign_manifest(man, seed)
    pathlib.Path(path).write_text(json.dumps(signed, ensure_ascii=False, indent=2) + "\n",
                                  encoding="utf-8")
    ok, why = release.verify_manifest(signed, [ed25519.public_key_from_seed(seed).hex()])
    print(f"已签名 {path} -> {why}")
    if not ok:
        raise SystemExit("签完自己都验不过，别发布")
    return signed


def verify(path):
    man = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    ok, why = release.verify_manifest(man)
    print(f"{path}：{'✅ ' if ok else '❌ '}{why}")
    print("内置的可信公钥：")
    print(release.trusted_keys_text())
    return 0 if ok else 1


def main():
    p = argparse.ArgumentParser(description="发布清单签名工具")
    p.add_argument("--genkey", action="store_true")
    p.add_argument("--sign", metavar="清单.json")
    p.add_argument("--verify", metavar="清单.json")
    p.add_argument("--show-key", action="store_true")
    p.add_argument("--key", default=os.environ.get("MC_SIGN_KEY", DEFAULT_KEY))
    a = p.parse_args()
    if a.genkey:
        genkey(a.key)
    elif a.sign:
        sign(a.sign, a.key)
    elif a.verify:
        sys.exit(verify(a.verify))
    elif a.show_key:
        print(ed25519.public_key_from_seed(load_key(a.key)).hex())
    else:
        p.print_help()


if __name__ == "__main__":
    main()
