#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ed25519 签名 / 验签（纯 Python，不用装任何第三方库）。

用途：给自动更新的清单签名。私钥只在发布机上，公钥内置在客户端里
—— 就算域名、服务器、Cloudflare 账号全被拿下，攻击者也伪造不出签名。

实现参考 RFC 8032 附录里的参考代码，跑 `python3 app/ed25519.py` 会跑一遍
官方的测试向量自检。
"""
import hashlib

P = 2 ** 255 - 19
L = 2 ** 252 + 27742317777372353535851937790883648493


def _sha512(data):
    return hashlib.sha512(data).digest()


def _inv(x):
    return pow(x, P - 2, P)


_d = -121665 * _inv(121666) % P
_I = pow(2, (P - 1) // 4, P)


def _x_recover(y):
    xx = (y * y - 1) * _inv(_d * y * y + 1)
    x = pow(xx, (P + 3) // 8, P)
    if (x * x - xx) % P != 0:
        x = (x * _I) % P
    if x % 2 != 0:
        x = P - x
    return x


_BY = 4 * _inv(5) % P
_BX = _x_recover(_BY)
_B = (_BX % P, _BY % P, 1, (_BX * _BY) % P)


def _add(a, b):
    x1, y1, z1, t1 = a
    x2, y2, z2, t2 = b
    A = (y1 - x1) * (y2 - x2) % P
    Bv = (y1 + x1) * (y2 + x2) % P
    C = 2 * t1 * t2 * _d % P
    D = 2 * z1 * z2 % P
    E = Bv - A
    F = D - C
    G = D + C
    H = Bv + A
    return (E * F % P, G * H % P, F * G % P, E * H % P)


def _double(a):
    x1, y1, z1, _t1 = a
    A = x1 * x1 % P
    Bv = y1 * y1 % P
    C = 2 * z1 * z1 % P
    H = (A + Bv) % P
    E = (H - (x1 + y1) * (x1 + y1)) % P
    G = (A - Bv) % P
    F = (C + G) % P
    return (E * F % P, G * H % P, F * G % P, E * H % P)


def _scalar_mult(point, e):
    if e == 0:
        return (0, 1, 1, 0)
    q = _scalar_mult(point, e // 2)
    q = _double(q)
    if e & 1:
        q = _add(q, point)
    return q


def _encode_point(point):
    x, y, z, _t = point
    zi = _inv(z)
    x = x * zi % P
    y = y * zi % P
    bits = [(y >> i) & 1 for i in range(255)] + [x & 1]
    return bytes(sum(bits[i * 8 + j] << j for j in range(8)) for i in range(32))


def _decode_point(data):
    if len(data) != 32:
        raise ValueError("点长度不对")
    y = int.from_bytes(data, "little") & ((1 << 255) - 1)
    x = _x_recover(y)
    if (x & 1) != (data[31] >> 7):
        x = P - x
    point = (x, y, 1, x * y % P)
    # 拒绝不在主群里的点（小的子群攻击）
    if not _is_on_curve(point):
        raise ValueError("点不在曲线上")
    return point


def _is_on_curve(point):
    x, y, z, t = point
    zi = _inv(z)
    x = x * zi % P
    y = y * zi % P
    return (-x * x + y * y - 1 - _d * x * x * y * y) % P == 0


# ---------------------------------------------------------------- 对外接口
def public_key_from_seed(seed):
    """32 字节私钥种子 -> 32 字节公钥"""
    if len(seed) != 32:
        raise ValueError("私钥必须是 32 字节")
    h = _sha512(seed)
    # 标准 clamp：清掉最低 3 位和最高 2 位，再置上第 254 位
    a = int.from_bytes(h[:32], "little")
    a &= 2 ** 254 - 8
    a |= 2 ** 254
    return _encode_point(_scalar_mult(_B, a))


def sign(message, seed):
    """签名：返回 64 字节"""
    if len(seed) != 32:
        raise ValueError("私钥必须是 32 字节")
    pub = public_key_from_seed(seed)
    h = _sha512(seed)
    a = int.from_bytes(h[:32], "little")
    a &= 2 ** 254 - 8
    a |= 2 ** 254
    r = int.from_bytes(_sha512(h[32:] + message), "little") % L
    R = _encode_point(_scalar_mult(_B, r))
    k = int.from_bytes(_sha512(R + pub + message), "little") % L
    S = (r + k * a) % L
    return R + S.to_bytes(32, "little")


def verify(signature, message, public_key):
    """验签：签名对得上返回 True"""
    try:
        if len(signature) != 64 or len(public_key) != 32:
            return False
        R = _decode_point(signature[:32])
        S = int.from_bytes(signature[32:], "little")
        if S >= L:
            return False
        A = _decode_point(public_key)
        k = int.from_bytes(_sha512(signature[:32] + public_key + message), "little") % L
        left = _scalar_mult(_B, S)
        right = _add(R, _scalar_mult(A, k))
        return _encode_point(left) == _encode_point(right)
    except Exception:
        return False


def generate_keypair():
    """随机生成一对新密钥：(私钥种子, 公钥)"""
    import os
    seed = os.urandom(32)
    return seed, public_key_from_seed(seed)


# ---------------------------------------------------------------- 自检
def _selftest():
    vectors = [
        ("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
         "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
         "",
         "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
         "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
        ("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
         "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
         "72",
         "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da"
         "085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
    ]
    ok = 0
    for sk_hex, pk_hex, msg_hex, sig_hex in vectors:
        seed = bytes.fromhex(sk_hex)
        pk = public_key_from_seed(seed)
        msg = bytes.fromhex(msg_hex)
        sig = sign(msg, seed)
        good = (pk.hex() == pk_hex and sig.hex() == sig_hex
                and verify(sig, msg, bytes.fromhex(pk_hex)))
        print(f"  RFC 8032 向量：{'✅' if good else '❌'}")
        ok += bool(good)
    # 篡改必须被拒
    seed, pk = generate_keypair()
    msg = b"mc-seed-toolkit release 1"
    sig = sign(msg, seed)
    tampered = bytearray(sig)
    tampered[5] ^= 1
    checks = {
        "正常验签通过": verify(sig, msg, pk),
        "改一个字节就不过": not verify(bytes(tampered), msg, pk),
        "改消息就不过": not verify(sig, msg + b"x", pk),
        "换个公钥就不过": not verify(sig, msg, public_key_from_seed(b"\x00" * 32)),
        "乱给的签名不过": not verify(b"\x00" * 64, msg, pk),
    }
    for name, good in checks.items():
        print(f"  {name}：{'✅' if good else '❌'}")
        ok += bool(good)
    print(f"\n自检：{ok}/{len(vectors) + len(checks)} 项通过")
    return ok == len(vectors) + len(checks)


if __name__ == "__main__":
    import sys
    print("Ed25519 自检：")
    sys.exit(0 if _selftest() else 1)
