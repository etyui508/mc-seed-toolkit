#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""结构模块的公共骨架：每个结构导出一个 STRUCT，模块自己决定怎么算。"""


class Context:
    """把菜单那边的交互动作打包传进来（结构模块不用管界面细节）"""

    def __init__(self, ask, ask_center, ask_dist):
        self.ask = ask                 # ask(提示) -> 字符串
        self.ask_center = ask_center   # ask_center((默认x, 默认z)) -> (x, z)
        self.ask_dist = ask_dist       # ask_dist() -> (最近, 最远)，0 表示不限

    def number(self, prompt, default):
        """问一个数字，回车或答错就用默认值"""
        raw = (self.ask(prompt) or "").strip()
        if not raw:
            return default
        try:
            return int(raw)
        except ValueError:
            print(f"  （{raw} 不是数字，按默认 {default} 算）")
            return default


class Structure:
    """一个结构 = 一条菜单项 + 一套算法"""

    def __init__(self, no, name, hint="", key=None, nether=False, radius=3000, top=8,
                 runner=None, cli=None):
        self.no = no
        self.name = name
        self.hint = hint
        self.key = key or name          # 引擎里的键（findstruct 用的）
        self.nether = nether            # 下界结构：坐标要 ÷8
        self.radius = radius
        self.top = top
        self.runner = runner            # 交互模式的实现
        self.cli = cli                  # 命令行模式的实现

    def run(self, ctx):
        """菜单里选中它时走这里"""
        if self.runner is None:
            from . import probe
            return probe.run_interactive(self, ctx)
        return self.runner(self, ctx)

    def __repr__(self):
        return f"<Structure {self.no} {self.name}>"
