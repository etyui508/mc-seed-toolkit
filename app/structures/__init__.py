#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""结构注册表：所有结构模块在这里排好队，菜单和命令行都从这儿取。"""

from . import stronghold
from . import ocean_monument
from . import ancient_city
from . import trial_chamber
from . import woodland_mansion
from . import village
from . import pillager_outpost
from . import igloo
from . import swamp_hut
from . import desert_pyramid
from . import jungle_temple
from . import trail_ruins
from . import desert_well
from . import mineshaft
from . import shipwreck
from . import buried_treasure
from . import geode
from . import ruined_portal
from . import ruined_portal_nether
from . import nether_fortress
from . import end_city
from . import end_island
from . import end_ship
from . import end_ship_scan
from . import end_city_clean
from . import overview
from . import biome_at
from . import biome_find
from . import slime
from . import scan_block
from . import ore_density


# 全部结构，按菜单编号排序（编号唯一，1~31）
ALL = sorted([m.STRUCT for m in (
    stronghold,
    ocean_monument,
    ancient_city,
    trial_chamber,
    woodland_mansion,
    village,
    pillager_outpost,
    igloo,
    swamp_hut,
    desert_pyramid,
    jungle_temple,
    trail_ruins,
    desert_well,
    mineshaft,
    shipwreck,
    buried_treasure,
    geode,
    ruined_portal,
    ruined_portal_nether,
    nether_fortress,
    end_city,
    end_island,
    end_ship,
    end_ship_scan,
    end_city_clean,
    overview,
    biome_at,
    biome_find,
    slime,
    scan_block,
    ore_density,
)], key=lambda s: s.no)

BY_NO = {s.no: s for s in ALL}


def by_no(no):
    """按菜单编号取结构"""
    return BY_NO.get(int(no))


def by_name(query):
    """按名字（或引擎键）找结构，命令行 --name 用"""
    if not query:
        return None
    for s in ALL:
        if query == s.name or query == s.key:
            return s
    for s in ALL:
        if query in s.name or query in s.key:
            return s
    return None


def grouped():
    """(原版结构, 特殊功能) —— 菜单左边两栏用"""
    return [s for s in ALL if s.no <= 22], [s for s in ALL if s.no > 22]
