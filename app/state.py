#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全局状态：当前种子 / 版本 / 界面开关。

engine 和 structures 里的模块都从这里读，省得互相 import 绕成一圈。
"""

SEED = None            # 当前世界种子
SHOW_SEED = False      # 界面上要不要显示完整种子
USER_VER = None        # 用户填的游戏版本，比如 "1.21.10"
CUBI_VER = "1.21"      # 给 cubiomes 引擎用的版本（它只认到 1.21）
VER_FEAT = {}          # mcvers.features(USER_VER) 的结果
_NUMBERS = False


def setup(seed=None, show_seed=None, ver=None):
    """启动时一次性把状态设好"""
    global SEED, SHOW_SEED, USER_VER, CUBI_VER, VER_FEAT
    if seed is not None:
        SEED = seed
    if show_seed is not None:
        SHOW_SEED = bool(show_seed)
    if ver:
        USER_VER = str(ver)
    import mcvers
    if USER_VER:
        CUBI_VER = mcvers.cubiomes_version(USER_VER)
        VER_FEAT = mcvers.features(USER_VER)
    return SEED


def masked():
    """界面上显示的种子（默认打码）"""
    import config as cfgmod
    return cfgmod.mask(SEED, SHOW_SEED)
