// 基于 cubiomes：按种子找"真的会生成"的结构（含群系检查）+ 要塞（末地门）
// 编译见 tools/build-cubiomes.sh
//
// 用法:
//   findstruct biome <种子> <方块x> <方块z> ...       查这些点的群系
//   findstruct find  <种子> <中心区块x> <中心区块z> [半径区块数] [每种最多显示几个]
//                    [最短距离(方块)] [最远距离(方块，0/省略=不限)]
//   findstruct endbase <种子> <区块x> <区块z> ...     末地城基点高度（算末地船 y 用）
//   findstruct ship  <种子> <区块x> <区块z> ...       末地船：只给种子就算（不用游戏、不用存档）

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

#include "generator.h"
#include "finders.h"
#include "util.h"
#include "endcity.h"

/* 版本：默认 1.21.x；用环境变量 MCVER=1.20.4 之类覆盖（tool.py 会设置） */
static int mcFromEnv(void)
{
    const char *v = getenv("MCVER");
    if (!v || !*v) return MC_1_21;
    int a = 0, b = 0, c = 0;
    sscanf(v, "%d.%d.%d", &a, &b, &c);
    if (a != 1) goto unknown;
    switch (b)
    {
        case 21:
            if (c >= 9) return MC_1_21;      /* 1.21.9+（含 1.21.10）用最新世界生成 */
            if (c >= 4) return MC_1_21;      /* 1.21.4+ 冬季更新 */
            if (c >= 2) return MC_1_21_3;    /* 1.21.2 - 1.21.3 */
            return MC_1_21_1;                /* 1.21 - 1.21.1 */
        case 20: return MC_1_20;
        case 19: return MC_1_19;
        case 18: return MC_1_18;
        case 17: return MC_1_17;
        case 16: return MC_1_16;
        case 15: return MC_1_15;
        case 14: return MC_1_14;
        case 13: return MC_1_13;
        case 12: return MC_1_12;
        case 11: return MC_1_11;
        case 10: return MC_1_10;
        case 9:  return MC_1_9;
        case 8:  return MC_1_8;
        case 7:  return MC_1_7;
        default: break;
    }
unknown:
    fprintf(stderr, "不认识的版本 '%s'，用默认 1.21\\n", v);
    return MC_1_21;
}

typedef struct {
    int type;
    const char *name;
    const char *dim;
} Ent;

typedef struct {
    int x, z, dist;
} Hit;

/* ---------------------------------------------------------------- 末地船
 *
 * 生成器在 tools/endcity.c 里（照游戏本体 EndCityPieces 的字节码逐条复刻），
 * 所以**只要有种子**就能算出每座末地城长什么样 —— 不用装 Minecraft，也不用下载存档。
 *
 * 船是"桥"生成时的分支：if (!已出过船 && nextInt(10 - 深度) == 0) 就摆一条，
 * 位置在桥末端再往 (-8..-1, -70..-61) 偏。每座城最多一条船。
 *
 * 船模板里的标记是固定的（end_city/ship.nbt）：
 *   龙头 (6,8,0)、鞘翅展示框 (6,5,7)、两个宝箱标记 (5,5,7)/(7,5,7)
 * 游戏把 "Chest" 标记的箱子放在标记**下面一格**。
 * 这四个坐标跟 tools/ShipFinder.java（跑游戏本体那份）算出来的是同一套。
 */

/* 输出里的 y 统一按"基点 y = 64"算，调用方拿到真实基点高度再加差值 */
#define SHIP_BASE_Y 64

static int cmpHit(const void *a, const void *b)
{
    int da = ((const Hit *) a)->dist;
    int db = ((const Hit *) b)->dist;
    return (da > db) - (da < db);
}

/* 村庄按群系分 5 种变体（僵尸村庄是生成时随机决定的，算不出来） */
static const char *villageVariant(const char *biome)
{
    if (strstr(biome, "desert")) return "沙漠村庄";
    if (strstr(biome, "savanna")) return "热带草原村庄";
    if (strstr(biome, "snowy") || strstr(biome, "ice_spikes")) return "雪原村庄";
    if (strstr(biome, "taiga")) return "针叶林村庄";
    return "平原村庄";
}

static const Ent ENTRIES[] = {
    {Monument,       "海底神殿",   "主世界"},
    {Ancient_City,   "远古城市",   "主世界"},
    {Trial_Chambers, "试炼密室",   "主世界"},
    {Village,        "村庄",       "主世界"},
    {Outpost,        "掠夺者前哨", "主世界"},
    {Trail_Ruins,    "古迹废墟",   "主世界"},
    {Igloo,          "雪原小屋",   "主世界"},
    {Desert_Pyramid, "沙漠神殿",   "主世界"},
    {Jungle_Temple,  "丛林神殿",   "主世界"},
    {Swamp_Hut,      "女巫小屋",   "主世界"},
    {Ruined_Portal,  "废弃传送门", "主世界"},
    {Ruined_Portal_N,"废弃传送门(下界)", "下界"},
    {Shipwreck,      "沉船",       "主世界"},
    {Mansion,        "林地府邸",   "主世界"},
    {Ocean_Ruin,     "海底遗迹",   "主世界"},
    {Fortress,       "下界要塞",   "下界"},
    {Bastion,        "堡垒遗迹",   "下界"},
    {End_City,       "末地城",     "末地"},
    {End_Gateway,    "末地折跃门", "末地"},
    {End_Island,     "末地小岛",   "末地"},
    {Treasure,       "埋藏的宝藏", "主世界"},
    {Mineshaft,      "废弃矿井",   "主世界"},
    {Desert_Well,    "沙漠水井",   "主世界"},
    {Geode,          "紫水晶洞",   "主世界"},
};

/* 扫一片区块矩形里的结构（find 和 findrect 共用；findrect 是给多进程并行拆着扫用的）。
   x0..z1 = 要扫的区块范围（闭区间）；距离和距离窗口都按"中心区块 (centerX, centerZ)"算；
   globalRadius 只用来给"每区块一个"的结构（矿井/宝藏/水井/晶洞/折跃门/末地小岛）定扫描上限
   —— 拆开并行扫的时候用它，保证结果和"一个进程扫整片"一样。 */
static void scanStructures(Generator *g, long long seed, int mc,
                           int x0, int z0, int x1, int z1,
                           int centerX, int centerZ, int globalRadius,
                           int topN, int minDist, int maxDist, int nobiome)
{
    int bx0 = x0 * 16, bx1 = x1 * 16 + 15, bz0 = z0 * 16, bz1 = z1 * 16 + 15;
    int lim = globalRadius < 2100 ? globalRadius : 2100;
    int limx0 = x0 > centerX - lim ? x0 : centerX - lim;
    int limx1 = x1 < centerX + lim ? x1 : centerX + lim;
    int limz0 = z0 > centerZ - lim ? z0 : centerZ - lim;
    int limz1 = z1 < centerZ + lim ? z1 : centerZ + lim;

    for (size_t e = 0; e < sizeof(ENTRIES) / sizeof(ENTRIES[0]); e++) {
        Ent ent = ENTRIES[e];
        int dim = DIM_OVERWORLD;
        if (strcmp(ent.dim, "下界") == 0) dim = DIM_NETHER;
        if (strcmp(ent.dim, "末地") == 0) dim = DIM_END;
        applySeed(g, dim, (uint64_t) seed);

        StructureConfig sc;
        getStructureConfig(ent.type, mc, &sc);
        if (sc.regionSize <= 0) continue;

        int step = sc.regionSize > 1 ? sc.regionSize : 1;
        int rx0, rx1, rz0, rz1;
        if (step > 1) {
            rx0 = floordiv(x0, step); rx1 = floordiv(x1, step);
            rz0 = floordiv(z0, step); rz1 = floordiv(z1, step);
        } else {
            rx0 = limx0; rx1 = limx1; rz0 = limz0; rz1 = limz1;
        }
        long cap = (long) (rx1 - rx0 + 1) * (rz1 - rz0 + 1);
        if (cap <= 0) continue;
        Hit *hits = calloc((size_t) cap, sizeof(Hit));
        if (!hits) continue;
        int found = 0;
        for (int rx = rx0; rx <= rx1; rx++) {
            for (int rz = rz0; rz <= rz1; rz++) {
                Pos p;
                if (!getStructurePos(ent.type, mc, (uint64_t) seed, rx, rz, &p)) continue;
                if (p.x < bx0 || p.x > bx1 || p.z < bz0 || p.z > bz1) continue;
                if (ent.type == End_Island) {
                    /* cubiomes 的可行性检查在末地只认末地城/折跃门，末地小岛一律返回 0，
                       所以这里自己判：主岛和虚空（群系 the_end）不算，外岛那几种才算 */
                    const char *b = biome2str(mc, getBiomeAt(g, 1, p.x, 64, p.z));
                    if (!strstr(b, "end_highlands") && !strstr(b, "end_midlands") &&
                        !strstr(b, "end_barrens") && !strstr(b, "small_end_islands")) {
                        continue;
                    }
                } else if (!isViableStructurePos(ent.type, g, p.x, p.z, 0)) {
                    continue;
                }
                double bdx = p.x - centerX * 16.0, bdz = p.z - centerZ * 16.0;
                int blockDist = (int) sqrt(bdx * bdx + bdz * bdz);
                if (blockDist < minDist) continue;
                if (maxDist > 0 && blockDist > maxDist) continue;
                hits[found].x = p.x;
                hits[found].z = p.z;
                hits[found].dist = blockDist;
                found++;
            }
        }
        if (found > 1) qsort(hits, (size_t) found, sizeof(Hit), cmpHit);
        if (found > 0) {
            printf("\n[%s] %s：%d 个过了群系检查\n", ent.dim, ent.name, found);
            int shown = found < topN ? found : topN;
            for (int i = 0; i < shown; i++) {
                if (nobiome) {
                    // 只报坐标（不算群系）：并行扫的时候行数会翻好几倍，
                    // 每行都做一次噪声采样太贵，而且调用方多数不看群系
                    printf("  区块 (%d,%d)  方块 (%d,%d)  距中心 %d 格\n",
                           hits[i].x >> 4, hits[i].z >> 4, hits[i].x + 8, hits[i].z + 8,
                           hits[i].dist);
                    continue;
                }
                const char *biome = biome2str(mc, getBiomeAt(g, 1, hits[i].x, 64, hits[i].z));
                if (ent.type == Village) {
                    printf("  区块 (%d,%d)  方块 (%d,%d)  距中心 %d 格  %s（群系 %s）\n",
                           hits[i].x >> 4, hits[i].z >> 4, hits[i].x + 8, hits[i].z + 8,
                           hits[i].dist, villageVariant(biome), biome);
                } else {
                    printf("  区块 (%d,%d)  方块 (%d,%d)  距中心 %d 格  群系 %s\n",
                           hits[i].x >> 4, hits[i].z >> 4, hits[i].x + 8, hits[i].z + 8,
                           hits[i].dist, biome);
                }
            }
            if (found > shown) printf("  …还有 %d 个\n", found - shown);
        }
        free(hits);
    }
}

/* 要塞（末地门）那一段 */
static void printStrongholds(Generator *g, long long seed, int mc,
                             int centerX, int centerZ, int minDist, int maxDist)
{
    applySeed(g, DIM_OVERWORLD, (uint64_t) seed);
    StrongholdIter sh;
    Pos p = initFirstStronghold(&sh, mc, (uint64_t) seed);
    Pos shPos[128];
    int shDist[128];
    int shCount = 0;
    for (int i = 0; i < 128; i++) {
        shPos[shCount] = p;
        double ddx = p.x - centerX * 16.0, ddz = p.z - centerZ * 16.0;
        shDist[shCount] = (int) sqrt(ddx * ddx + ddz * ddz);
        shCount++;
        if (nextStronghold(&sh, g) < 0) break;
        p = sh.pos;
    }
    for (int i = 1; i < shCount; i++) {
        Pos hp = shPos[i];
        int hd = shDist[i];
        int j = i - 1;
        while (j >= 0 && shDist[j] > hd) {
            shPos[j + 1] = shPos[j];
            shDist[j + 1] = shDist[j];
            j--;
        }
        shPos[j + 1] = hp;
        shDist[j + 1] = hd;
    }
    int lo = 0;
    while (lo < shCount && shDist[lo] < minDist) lo++;
    int hi = shCount;
    if (maxDist > 0) {
        hi = lo;
        while (hi < shCount && shDist[hi] <= maxDist) hi++;
    }
    printf("\n[主世界] 要塞（末地门在要塞里面）：");
    if (minDist > 0 || maxDist > 0) {
        printf("范围内 %d 个", hi - lo);
        if (minDist > 0 && maxDist > 0) printf("（%d ~ %d 方块）", minDist, maxDist);
        else if (minDist > 0)           printf("（≥ %d 方块）", minDist);
        else                            printf("（≤ %d 方块）", maxDist);
    }
    printf("\n");
    for (int i = lo; i < hi && i < lo + 8; i++) {
        int bx = shPos[i].x, bz = shPos[i].z;
        int hx = bx - centerX * 16, hz = bz - centerZ * 16;
        printf("  #%d 方块 (%d,%d)  距你 %.1f 格  %s%s%s%s\n",
               i - lo + 1, bx, bz,
               sqrt((double) hx * hx + (double) hz * hz),
               hz < 0 ? "北" : (hz > 0 ? "南" : ""),
               hx < 0 ? "西" : (hx > 0 ? "东" : ""),
               "",
               "");
    }
}

int main(int argc, char **argv)
{
    if (argc < 2) {
        fprintf(stderr, "用法:\n  findstruct biome <种子> <x> <z> ...\n"
                        "  findstruct find <种子> <中心区块x> <中心区块z>"
                        " [半径] [每类条数] [最短距离] [最远距离]\n"
                        "  findstruct endbase <种子> <区块x> <区块z> ...\n"
                        "  findstruct ship <种子> <区块x> <区块z> ...   （末地船，只用种子）\n");
        return 1;
    }
    int mc = mcFromEnv();

    if (strcmp(argv[1], "biome") == 0 && argc >= 5) {
        long long seed = strtoll(argv[2], NULL, 10);
        Generator g;
        setupGenerator(&g, mc, 0);
        applySeed(&g, DIM_OVERWORLD, (uint64_t) seed);
        for (int i = 3; i + 1 < argc; i += 2) {
            int x = atoi(argv[i]);
            int z = atoi(argv[i + 1]);
            int id = getBiomeAt(&g, 1, x, 64, z);
            printf("(%d,%d) -> %s\n", x, z, biome2str(mc, id));
        }
        return 0;
    }

    // biome2 <种子> <x> <z> ...   同时报两个高度：y=64（洞里）和 y=320（地表）
    //   模组的群系采样点没记 y，所以复核的时候两个都看一眼，对上一个就算对上
    if (strcmp(argv[1], "biome2") == 0 && argc >= 5) {
        long long seed = strtoll(argv[2], NULL, 10);
        Generator g;
        setupGenerator(&g, mc, 0);
        applySeed(&g, DIM_OVERWORLD, (uint64_t) seed);
        for (int i = 3; i + 1 < argc; i += 2) {
            int x = atoi(argv[i]);
            int z = atoi(argv[i + 1]);
            const char *low = biome2str(mc, getBiomeAt(&g, 1, x, 64, z));
            const char *high = biome2str(mc, getBiomeAt(&g, 1, x, 320, z));
            printf("(%d,%d) -> %s / %s\n", x, z, low, high);
        }
        return 0;
    }

    // biomedim <种子> <维度 0主世界/-1下界/1末地> <x> <z> ...
    //   查某个维度里的群系（主世界以外的点用原来的 biome 命令会算错）
    if (strcmp(argv[1], "biomedim") == 0 && argc >= 6) {
        long long seed = strtoll(argv[2], NULL, 10);
        int dim = atoi(argv[3]);
        Generator g;
        setupGenerator(&g, mc, 0);
        applySeed(&g, dim, (uint64_t) seed);
        for (int i = 4; i + 1 < argc; i += 2) {
            int x = atoi(argv[i]);
            int z = atoi(argv[i + 1]);
            printf("(%d,%d) -> %s\n", x, z, biome2str(mc, getBiomeAt(&g, 1, x, 64, z)));
        }
        return 0;
    }

    // biomefind <种子> <维度(0主世界/-1下界/1末地)> <中心x> <中心z> <半径方块> <群系名> [步长]
    if (strcmp(argv[1], "biomefind") == 0 && argc >= 8) {
        long long seed = strtoll(argv[2], NULL, 10);
        int dim = atoi(argv[3]);
        int centerX = atoi(argv[4]);
        int centerZ = atoi(argv[5]);
        int radius = atoi(argv[6]);
        const char *target = argv[7];
        int step = argc > 8 ? atoi(argv[8]) : 64;
        Generator g;
        setupGenerator(&g, mc, 0);
        applySeed(&g, dim, (uint64_t) seed);
        int best = -1, bx = 0, bz = 0;
        for (int x = centerX - radius; x <= centerX + radius; x += step) {
            for (int z = centerZ - radius; z <= centerZ + radius; z += step) {
                int id = getBiomeAt(&g, 1, x, 64, z);
                if (strcmp(biome2str(mc, id), target) != 0) continue;
                int d = (int) fmax(abs(x - centerX), abs(z - centerZ));
                if (best < 0 || d < best) { best = d; bx = x; bz = z; }
            }
        }
        if (best < 0) {
            printf("半径 %d 方块内没找到 %s（步长 %d，可能太小，试试加大半径）\n", radius, target, step);
        } else {
            printf("最近的 %s：方块 (%d,%d)，距中心 %d 格（步长 %d，实际位置在附近 ±%d 格内）\n",
                   target, bx, bz, best, step, step);
        }
        return 0;
    }

    // endbase <种子> <区块x> <区块z> ...   末地城的基点高度
    // 游戏里末地城的起点 y = 四个角的高度取最小值（角的位置跟城市朝向有关），
    // 船的坐标都是相对这个基点算的，所以要算船的 y 就得先有这个值。
    if (strcmp(argv[1], "endbase") == 0 && argc >= 5) {
        long long seed = strtoll(argv[2], NULL, 10);
        for (int i = 3; i + 1 < argc; i += 2) {
            int cx = atoi(argv[i]);
            int cz = atoi(argv[i + 1]);
            uint64_t rng = chunkGenerateRnd((uint64_t) seed, cx, cz);
            int rot = nextInt(&rng, 4);
            int bx = cx * 16 + 7, bz = cz * 16 + 7;
            int dx = 5, dz = 5;
            switch (rot) {
                case 1: dx = -5; break;
                case 2: dx = -5; dz = -5; break;
                case 3: dz = -5; break;
                default: break;
            }
            int h0 = getEndSurfaceHeight(mc, (uint64_t) seed, bx, bz);
            int h1 = getEndSurfaceHeight(mc, (uint64_t) seed, bx, bz + dz);
            int h2 = getEndSurfaceHeight(mc, (uint64_t) seed, bx + dx, bz);
            int h3 = getEndSurfaceHeight(mc, (uint64_t) seed, bx + dx, bz + dz);
            int y = h0;
            if (h1 < y) y = h1;
            if (h2 < y) y = h2;
            if (h3 < y) y = h3;
            printf("BASE %d %d %d %d\n", cx, cz, rot, y);
        }
        return 0;
    }

    // shipdump <种子> <区块x> <区块z> —— 对拍用：这座城的每一段都打出来
    //   （和 tools/EndCityDump.java 跑游戏本体出来的逐段比对）
    if (strcmp(argv[1], "shipdump") == 0 && argc >= 5) {
        long long seed = strtoll(argv[2], NULL, 10);
        static EcPiece pieces[EC_MAX_PIECES];
        for (int a = 3; a + 1 < argc; a += 2) {
            int cx = atoi(argv[a]);
            int cz = atoi(argv[a + 1]);
            int n = ecCityPieces(pieces, EC_MAX_PIECES, (uint64_t) seed, cx, cz);
            printf("CITY %d %d pieces=%d rot=%d\n", cx, cz, n, n > 0 ? pieces[0].rot : -1);
            for (int i = 0; i < n; i++) {
                printf("PIECE %d %s rot=%d depth=%d tpl=%d,%d,%d box=%d,%d,%d..%d,%d,%d\n",
                       i, pieces[i].name, pieces[i].rot, pieces[i].depth,
                       pieces[i].px, pieces[i].py, pieces[i].pz,
                       pieces[i].x0, pieces[i].y0, pieces[i].z0,
                       pieces[i].x1, pieces[i].y1, pieces[i].z1);
            }
        }
        return 0;
    }

    // ship <种子> <区块x> <区块z> ...
    //   末地船：只给种子就算（tools/endcity.c 里那份 = 游戏本体 EndCityPieces 的复刻）
    if (strcmp(argv[1], "ship") == 0 && argc >= 5) {
        long long seed = strtoll(argv[2], NULL, 10);
        static EcPiece pieces[EC_MAX_PIECES];
        for (int a = 3; a + 1 < argc; a += 2) {
            int cx = atoi(argv[a]);
            int cz = atoi(argv[a + 1]);
            int n = ecCityPieces(pieces, EC_MAX_PIECES, (uint64_t) seed, cx, cz);
            int si = -1;
            for (int i = 0; i < n; i++) {
                if (pieces[i].type == EC_SHIP) { si = i; break; }
            }
            if (si < 0) {
                printf("CITY %d %d NONE %d\n", cx, cz, n);
                continue;
            }
            EcPiece *sp = &pieces[si];
            /* y 统一换成"基点 y = 64"那套；调用方拿到真实基点高度再加差值 */
            int x0 = sp->x0, x1 = sp->x1, z0 = sp->z0, z1 = sp->z1;
            int y0 = sp->y0 + SHIP_BASE_Y, y1 = sp->y1 + SHIP_BASE_Y;
            /* 模板里的标记：龙头 (6,8,0)、鞘翅 (6,5,7)、宝箱 (5,5,7)/(7,5,7)（箱子在标记下面一格） */
            int hx, hy, hz, ex, ey, ez, c1x, c1y, c1z, c2x, c2y, c2z;
            ecTransformLocal(sp->rot, 6, 8, 0, &hx, &hy, &hz);
            ecTransformLocal(sp->rot, 6, 5, 7, &ex, &ey, &ez);
            ecTransformLocal(sp->rot, 5, 5, 7, &c1x, &c1y, &c1z);
            ecTransformLocal(sp->rot, 7, 5, 7, &c2x, &c2y, &c2z);
            printf("CITY %d %d SHIP rot=%d box=%d,%d,%d..%d,%d,%d "
                   "goto=%d,%d,%d head=%d,%d,%d elytra=%d,%d,%d "
                   "chest=%d,%d,%d chest=%d,%d,%d pieces=%d\n",
                   cx, cz, sp->rot, x0, y0, z0, x1, y1, z1,
                   (x0 + x1) / 2, y0, (z0 + z1) / 2,
                   sp->px + hx, sp->py + SHIP_BASE_Y + hy, sp->pz + hz,
                   sp->px + ex, sp->py + SHIP_BASE_Y + ey, sp->pz + ez,
                   sp->px + c1x, sp->py + SHIP_BASE_Y + c1y - 1, sp->pz + c1z,
                   sp->px + c2x, sp->py + SHIP_BASE_Y + c2y - 1, sp->pz + c2z,
                   n);
        }
        return 0;
    }

    // findrect <种子> <x0> <z0> <x1> <z1> <中心区块x> <中心区块z> <全局半径>
    //          [每种几个] [最短距离] [最远距离] [nobiome]
    //   只扫指定的区块矩形（闭区间），不算要塞 —— 给 calc.py 拆成几块、开多个进程并行扫用的。
    //   距离和距离窗口按"中心区块"算，所以拆开扫和一次扫整片的结果一样。
    if (strcmp(argv[1], "findrect") == 0 && argc >= 9) {
        long long seed = strtoll(argv[2], NULL, 10);
        int x0 = atoi(argv[3]), z0 = atoi(argv[4]);
        int x1 = atoi(argv[5]), z1 = atoi(argv[6]);
        int centerX = atoi(argv[7]), centerZ = atoi(argv[8]);
        int globalRadius = argc > 9 ? atoi(argv[9]) : 200;
        int topN = argc > 10 ? atoi(argv[10]) : 6;
        int minDist = argc > 11 ? atoi(argv[11]) : 0;
        int maxDist = argc > 12 ? atoi(argv[12]) : 0;
        int nobiome = argc > 13 ? atoi(argv[13]) : 0;
        if (x1 < x0) { int t = x0; x0 = x1; x1 = t; }
        if (z1 < z0) { int t = z0; z0 = z1; z1 = t; }
        Generator g;
        setupGenerator(&g, mc, 0);
        scanStructures(&g, seed, mc, x0, z0, x1, z1,
                       centerX, centerZ, globalRadius, topN, minDist, maxDist, nobiome);
        return 0;
    }

    if (strcmp(argv[1], "find") != 0 || argc < 5) {
        fprintf(stderr, "参数不对，看上面的用法\n");
        return 1;
    }

    long long seed = strtoll(argv[2], NULL, 10);
    int cx = atoi(argv[3]);
    int cz = atoi(argv[4]);
    int radius = argc > 5 ? atoi(argv[5]) : 200;
    int topN = argc > 6 ? atoi(argv[6]) : 6;
    int minDist = argc > 7 ? atoi(argv[7]) : 0;   // 最小距离（方块），跳过别人搜过的近处
    int maxDist = argc > 8 ? atoi(argv[8]) : 0;   // 最大距离（方块），0 = 不限（只要远处的就填它）
    int x0 = cx - radius, x1 = cx + radius, z0 = cz - radius, z1 = cz + radius;

    printf("种子 %lld，中心区块 (%d,%d)，半径 %d 区块（%d 方块）——下面是过了群系检查的（真的会生成）\n",
           seed, cx, cz, radius, radius * 16);
    if (minDist > 0 || maxDist > 0) {
        printf("距离窗口：");
        if (minDist > 0 && maxDist > 0) printf("%d ~ %d 方块\n", minDist, maxDist);
        else if (minDist > 0)           printf("≥ %d 方块（只要远的）\n", minDist);
        else                            printf("≤ %d 方块\n", maxDist);
    }

    Generator g;
    setupGenerator(&g, mc, 0);

    scanStructures(&g, seed, mc, x0, z0, x1, z1, cx, cz, radius, topN, minDist, maxDist, 0);
    printStrongholds(&g, seed, mc, cx, cz, minDist, maxDist);
    return 0;
}
