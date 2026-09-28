#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发布清单的签名与验签。

为什么需要它：更新的下载地址是一个域名（mcdownload.xxx.top）。
域名被劫持、服务器被拿下、Cloudflare 账号被盗 —— 这些情况下 HTTPS 都救不了你，
攻击者可以把包换成自己的，还能算出"正确的" sha256。

所以真正的防线是**离线签名**：
  · 发布机上有私钥（不放在网站目录里）
  · 客户端里内置公钥
  · 每次更新先验签：签名对不上就拒绝更新

这样即使域名彻底被黑，也推不出一个客户端会接受的包。

签名的对象是"清单里除 sig 之外的所有字段"的规范 JSON（键排序、无多余空格），
所以内容和格式有一点点变化都验不过 —— 这正是我们想要的。
"""
import json

try:
    from . import ed25519
except ImportError:                     # 直接跑脚本 / tools 里导入时
    import ed25519

# 可信公钥（可写多个，方便以后换钥匙时平滑过渡）
PUBLIC_KEYS = [
    # PUBKEYS-BEGIN
    "2ce74cd8be9e44dab33712bcd095f8f3e2c9efce9283ca939977889c8cbd46a0",
    # PUBKEYS-END
]

# 这两个字段是"签名本身"的元信息，不参与签名计算
SIG_FIELDS = ("sig", "sig_alg")


def canonical(man):
    """清单的规范字节：去掉签名相关的字段，键排序，紧凑分隔符
    —— 签名和验签都对着它算，两边必须完全一致"""
    body = {k: v for k, v in man.items() if k not in SIG_FIELDS}
    text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return text.encode("utf-8")


def sign_manifest(man, seed):
    """给清单加上 sig 字段（seed 是 32 字节私钥）"""
    signed = dict(man)
    signed["sig"] = ed25519.sign(canonical(man), seed).hex()
    signed["sig_alg"] = "ed25519"
    return signed


def verify_manifest(man, keys=None):
    """验签。返回 (是否信任, 说明)"""
    keys = keys if keys is not None else PUBLIC_KEYS
    if not isinstance(man, dict):
        return False, _("清单不是个 JSON 对象")
    sig_hex = man.get("sig")
    if not sig_hex:
        return False, _("清单上没有签名（sig）")
    if str(man.get("sig_alg", "ed25519")) != "ed25519":
        return False, _("不认识的签名算法：{alg}", alg=man.get("sig_alg"))
    if not keys:
        return False, _("客户端里没有内置任何公钥（这份包不完整）")
    try:
        sig = bytes.fromhex(str(sig_hex))
    except ValueError:
        return False, _("签名不是合法的十六进制")
    msg = canonical(man)
    for pub_hex in keys:
        try:
            pub = bytes.fromhex(pub_hex)
        except ValueError:
            continue
        if ed25519.verify(sig, msg, pub):
            return True, _("签名有效")
    return False, _("签名对不上（清单被改过，或者不是我们签的）")


def trusted_keys_text():
    """把内置公钥列出来（排查时看）"""
    return "\n".join("  " + k for k in PUBLIC_KEYS) or "  （没有）"
import i18n                 # 验签失败的说明是给用户看的，走语言表

_ = i18n.t
