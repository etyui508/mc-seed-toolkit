/* 末地城生成器 —— 照着 1.21.10 客户端的字节码逐条复刻
 * （class_3342 = EndCityPieces，以及它内部那四个生成器 class_3342$1..$4）
 *
 * 为什么要自己写一份：这样"这座末地城有没有末地船、船在哪"**只用一个世界种子**就能算，
 * 不需要装 Minecraft、不需要下载存档，也不挑版本（末地城生成器从 1.9 起就没变过）。
 * 手边另一条路 tools/ShipFinder.java 是直接跑游戏本体的类，很准但要本机装着游戏。
 *
 * 复刻要点（都是游戏里那些"看不出来但必须一模一样"的地方）：
 *   · 随机数：WorldgenRandom.setLargeFeatureSeed(种子, 区块x, 区块z)
 *   · 段的位置：新段位置 = 父段位置 + 用**父段**的朝向/镜像把偏移转过去
 *     （镜像 LEFT_RIGHT 是 overwrite=false 的段才有的：二层楼板那几段）
 *   · 包围盒：模板两个角 (0,0,0) 和 (尺寸-1) 转过去取 min/max，再平移到段位置
 *   · 递归：深度 > 8 就不生成；一批新段生成完掷一次 nextInt()，这批段的 depth 都设成它，
 *     只有和**已有段**撞包围盒、且 depth 不同，整批才作废
 *   · 船：桥的生成里 if (!出过船 && nextInt(10 - 深度) == 0) 摆一条，
 *     位置在桥末端再往 (-8..-1, -70..-61) 偏；整座城最多一条船
 *
 * 验证：tools/EndCityDump.java（跑游戏本体，把每一段的名字/朝向/原点/包围盒打出来）
 *       与本文件的 dump 逐段对拍，见 docs/原理.md。
 */

#include <string.h>
#include "endcity.h"

#define EC_MULT 0x5DEECE66DULL
#define EC_ADD  0xBULL
#define EC_MASK ((1ULL << 48) - 1)

/* 段类型表：名字 + 模板尺寸（数据包 data/minecraft/structure/end_city 里的 *.nbt，
   和包里 tools/endcity-sizes.txt 一致） */
static const struct { const char *name; int sx, sy, sz; } EC_INFO[EC_TYPE_COUNT] = {
    {"base_floor",          10,  4, 10},
    {"base_roof",           12,  2, 12},
    {"bridge_end",           5,  6,  2},
    {"bridge_gentle_stairs", 5,  7,  8},
    {"bridge_piece",         5,  6,  4},
    {"bridge_steep_stairs",  5,  7,  4},
    {"fat_tower_base",      13,  4, 13},
    {"fat_tower_middle",    13,  8, 13},
    {"fat_tower_top",       17,  6, 17},
    {"second_floor_1",      12,  8, 12},
    {"second_floor_2",      12,  8, 12},
    {"second_roof",         14,  2, 14},
    {"ship",                13, 24, 29},
    {"third_floor_1",       14,  8, 14},
    {"third_floor_2",       14,  8, 14},
    {"third_roof",          16,  2, 16},
    {"tower_base",           7,  7,  7},
    {"tower_piece",          7,  4,  7},
    {"tower_top",            9,  5,  9},
};

/* ---------------------------------------------------------------- 随机数 */

typedef struct { uint64_t s; } EcRng;

/* 原版 LegacyRandomSource.setSeed（实测等于 seed ^ MULT，不掺旧状态） */
static void rngSeed(EcRng *r, uint64_t seed)
{
    r->s = (seed ^ EC_MULT) & EC_MASK;
}

static int rngNext(EcRng *r, int bits)
{
    r->s = (r->s * EC_MULT + EC_ADD) & EC_MASK;
    return (int) (r->s >> (48 - bits));
}

static int rngNextInt(EcRng *r, int bound)
{
    int m = bound - 1;
    int u = rngNext(r, 31);
    if ((bound & m) == 0)
        return (int) (((int64_t) bound * u) >> 31);
    int res = u % bound;
    while (u - res + m < 0)
    {
        u = rngNext(r, 31);
        res = u % bound;
    }
    return res;
}

static int64_t rngNextLong(EcRng *r)
{
    /* 和 java.util.Random.nextLong() 一模一样：两次 next(32) 按**有符号 int** 拼起来。
       注意低 32 位是当有符号数加的（不是按无符号掩码）—— 两者差 2^32，会把整条随机序列带偏。
       顺序也要写死：先高后低（C 里表达式求值顺序未定义，不能写成一行）。 */
    int64_t hi = rngNext(r, 32);
    int64_t lo = rngNext(r, 32);
    return (hi << 32) + lo;
}

static int rngNextBool(EcRng *r)
{
    return rngNext(r, 1) != 0;
}

/* WorldgenRandom.setLargeFeatureSeed(种子, 区块x, 区块z) */
static void rngLargeFeature(EcRng *r, uint64_t seed, int chunkX, int chunkZ)
{
    rngSeed(r, seed);
    int64_t a = rngNextLong(r);
    int64_t b = rngNextLong(r);
    rngSeed(r, (uint64_t) ((int64_t) chunkX * a) ^ (uint64_t) ((int64_t) chunkZ * b) ^ seed);
}

/* ------------------------------------------------------- 坐标变换 / 包围盒 */

/* 游戏的 StructureTemplate.transform（pivot 恒为 0）：先镜像，再旋转 */
static void ecTransform(int rot, int mirror, int lx, int ly, int lz,
                        int *ox, int *oy, int *oz)
{
    int x = lx, z = lz;
    if (mirror)
        z = -z;                    /* LEFT_RIGHT：把 z 取反 */
    switch (rot)
    {
    case 1:  *ox = -z; *oz =  x; break;   /* clockwise_90 */
    case 2:  *ox = -x; *oz = -z; break;   /* 180 */
    case 3:  *ox =  z; *oz = -x; break;   /* counterclockwise_90 */
    default: *ox =  x; *oz =  z; break;   /* none */
    }
    *oy = ly;
}

void ecTransformLocal(int rot, int lx, int ly, int lz, int *ox, int *oy, int *oz)
{
    ecTransform(rot, 0, lx, ly, lz, ox, oy, oz);
}

/* ---------------------------------------------------------------- 生成 */

typedef struct {
    EcPiece *list;
    int n;
    int maxp;
    EcRng *rng;
    int ship;          /* 这座城已经出过船了 */
    int batchStart;    /* 当前这批（临时表）从哪个下标开始 —— 递归时当检查范围用 */
} EcEnv;

enum { EC_GEN_HOUSE_TOWER, EC_GEN_TOWER, EC_GEN_BRIDGE, EC_GEN_FAT_TOWER };

typedef struct { int x, y, z; } EcPos;

/* 新增一段：prev==NULL 时用绝对坐标（城里第一段），否则按父段的朝向/镜像偏移过去 */
static EcPiece *addPiece(EcEnv *env, EcPiece *prev, int rot, int px, int py, int pz,
                         int typ, int overwrite)
{
    if (env->n >= env->maxp || typ < 0 || typ >= EC_TYPE_COUNT)
        return prev ? prev : env->list;
    EcPiece *p = &env->list[env->n++];
    p->name = EC_INFO[typ].name;
    p->type = typ;
    p->rot = rot;
    p->depth = 0;
    /* 1.21.10 实测：所有段的 placement 镜像都是 NONE（拿 EndCityDump.java 打出来看过），
       那个 overwrite 布尔只影响方块摆放，不影响段的位置和包围盒 —— 所以这里恒为 0。 */
    p->mirror = 0;
    (void) overwrite;
    if (prev)
    {
        int dx, dy, dz;
        ecTransform(prev->rot, prev->mirror, px, py, pz, &dx, &dy, &dz);
        p->px = prev->px + dx;
        p->py = prev->py + dy;
        p->pz = prev->pz + dz;
    }
    else
    {
        p->px = px;
        p->py = py;
        p->pz = pz;
    }
    /* 包围盒：两个角转过去取 min/max，再平移到段位置 */
    int ax, ay, az, bx, by, bz;
    ecTransform(rot, p->mirror, 0, 0, 0, &ax, &ay, &az);
    ecTransform(rot, p->mirror, EC_INFO[typ].sx - 1, EC_INFO[typ].sy - 1,
                EC_INFO[typ].sz - 1, &bx, &by, &bz);
    p->x0 = p->px + (ax < bx ? ax : bx);
    p->x1 = p->px + (ax > bx ? ax : bx);
    p->y0 = p->py + (ay < by ? ay : by);
    p->y1 = p->py + (ay > by ? ay : by);
    p->z0 = p->pz + (az < bz ? az : bz);
    p->z1 = p->pz + (az > bz ? az : bz);
    return p;
}

static int overlap(const EcPiece *a, const EcPiece *b)
{
    return a->x0 <= b->x1 && b->x0 <= a->x1 &&
           a->y0 <= b->y1 && b->y0 <= a->y1 &&
           a->z0 <= b->z1 && b->z0 <= a->z1;
}

static int genRun(EcEnv *env, int gen, EcPiece *cur, int depth, const EcPos *pos);

/* 桥（游戏里 field_14387：整座城共用，出过船就不再出） */
static int genBridge(EcEnv *env, EcPiece *cur, int depth, const EcPos *pos)
{
    int rot = cur->rot;
    int floors = 1 + rngNextInt(env->rng, 4);
    EcPiece *p = addPiece(env, cur, rot, 0, 0, -4, EC_BRIDGE_PIECE, 1);
    p->depth = -1;
    int y = 0;
    for (int i = 0; i < floors; i++)
    {
        if (rngNextBool(env->rng))
        {
            p = addPiece(env, p, rot, 0, y, -4, EC_BRIDGE_PIECE, 1);
            y = 0;
            continue;
        }
        if (rngNextBool(env->rng))
            p = addPiece(env, p, rot, 0, y, -4, EC_BRIDGE_STEEP, 1);
        else
            p = addPiece(env, p, rot, 0, y, -8, EC_BRIDGE_GENTLE, 1);
        y = 4;
    }
    if (!env->ship && rngNextInt(env->rng, 10 - depth) == 0)
    {
        int sx = -8 + rngNextInt(env->rng, 8);
        int sz = -70 + rngNextInt(env->rng, 10);
        addPiece(env, p, rot, sx, y, sz, EC_SHIP, 1);
        env->ship = 1;
    }
    else
    {
        EcPos house = {-3, y + 1, -11};
        if (!genRun(env, EC_GEN_HOUSE_TOWER, p, depth + 1, &house))
            return 0;
    }
    p = addPiece(env, p, (rot + 2) & 3, 4, y, 0, EC_BRIDGE_END, 1);
    p->depth = -1;
    return 1;
}

/* 楼（游戏里 field_14390：从桥接出来的那一段，做 base_floor 那条链） */
static int genHouseTower(EcEnv *env, EcPiece *cur, int depth, const EcPos *pos)
{
    if (depth > 8)
        return 0;
    int rot = cur->rot;
    EcPiece *p = addPiece(env, cur, rot, pos->x, pos->y, pos->z, EC_BASE_FLOOR, 1);
    int k = rngNextInt(env->rng, 3);
    if (k == 0)
    {
        addPiece(env, p, rot, -1, 4, -1, EC_BASE_ROOF, 1);
    }
    else if (k == 1)
    {
        p = addPiece(env, p, rot, -1, 0, -1, EC_SECOND_FLOOR_2, 0);
        p = addPiece(env, p, rot, -1, 8, -1, EC_SECOND_ROOF, 0);
        genRun(env, EC_GEN_TOWER, p, depth + 1, NULL);
    }
    else if (k == 2)
    {
        p = addPiece(env, p, rot, -1, 0, -1, EC_SECOND_FLOOR_2, 0);
        p = addPiece(env, p, rot, -1, 4, -1, EC_THIRD_FLOOR_2, 0);
        p = addPiece(env, p, rot, -1, 8, -1, EC_THIRD_ROOF, 1);
        genRun(env, EC_GEN_TOWER, p, depth + 1, NULL);
    }
    return 1;
}

/* 塔楼 + 它的桥（游戏里 field_14386） */
static const struct { int drot, x, y, z; } EC_TOWER_BRIDGES[4] = {
    {0, 1, -1, 0}, {1, 6, -1, 1}, {3, 0, -1, 5}, {2, 5, -1, 6},
};

static int genTower(EcEnv *env, EcPiece *cur, int depth, const EcPos *pos)
{
    if (depth > 8)
        return 0;
    int rot = cur->rot;
    EcPiece *p = cur;
    int bx = 3 + rngNextInt(env->rng, 2);       /* 注意顺序：先 x 后 z（和游戏一致） */
    int bz = 3 + rngNextInt(env->rng, 2);
    p = addPiece(env, p, rot, bx, -3, bz, EC_TOWER_BASE, 1);
    p = addPiece(env, p, rot, 0, 7, 0, EC_TOWER_PIECE, 1);
    EcPiece *floor = (rngNextInt(env->rng, 3) == 0) ? p : NULL;
    int floors = 1 + rngNextInt(env->rng, 3);
    for (int i = 0; i < floors; i++)
    {
        p = addPiece(env, p, rot, 0, 4, 0, EC_TOWER_PIECE, 1);
        if (i < floors - 1 && rngNextBool(env->rng))
            floor = p;
    }
    if (floor)
    {
        for (int i = 0; i < 4; i++)
        {
            if (!rngNextBool(env->rng))
                continue;
            EcPiece *bridge = addPiece(env, floor, (rot + EC_TOWER_BRIDGES[i].drot) & 3,
                                       EC_TOWER_BRIDGES[i].x, EC_TOWER_BRIDGES[i].y,
                                       EC_TOWER_BRIDGES[i].z, EC_BRIDGE_END, 1);
            genRun(env, EC_GEN_BRIDGE, bridge, depth + 1, NULL);
        }
        addPiece(env, p, rot, -1, 4, -1, EC_TOWER_TOP, 1);
    }
    else if (depth == 7)
    {
        addPiece(env, p, rot, -1, 4, -1, EC_TOWER_TOP, 1);
    }
    else
    {
        return genRun(env, EC_GEN_FAT_TOWER, p, depth + 1, NULL);
    }
    return 1;
}

/* 胖塔（游戏里 field_14384） */
static const struct { int drot, x, y, z; } EC_FAT_BRIDGES[4] = {
    {0, 4, -1, 0}, {1, 12, -1, 4}, {3, 0, -1, 8}, {2, 8, -1, 12},
};

static int genFatTower(EcEnv *env, EcPiece *cur, int depth, const EcPos *pos)
{
    int rot = cur->rot;
    EcPiece *p = addPiece(env, cur, rot, -3, 4, -3, EC_FAT_BASE, 1);
    p = addPiece(env, p, rot, 0, 4, 0, EC_FAT_MIDDLE, 1);
    for (int i = 0; i < 2; i++)
    {
        if (rngNextInt(env->rng, 3) == 0)
            break;
        p = addPiece(env, p, rot, 0, 8, 0, EC_FAT_MIDDLE, 1);
        for (int j = 0; j < 4; j++)
        {
            if (!rngNextBool(env->rng))
                continue;
            EcPiece *bridge = addPiece(env, p, (rot + EC_FAT_BRIDGES[j].drot) & 3,
                                       EC_FAT_BRIDGES[j].x, EC_FAT_BRIDGES[j].y,
                                       EC_FAT_BRIDGES[j].z, EC_BRIDGE_END, 1);
            genRun(env, EC_GEN_BRIDGE, bridge, depth + 1, NULL);
        }
    }
    addPiece(env, p, rot, -2, 8, -2, EC_FAT_TOP, 1);
    return 1;
}

/* 对应游戏的 method_14673：跑一个生成器把新段攒进"临时表"，再做碰撞检查；
   全过了才并进上一层的表里。
     · 检查范围是 [env->batchStart, 这批的起点) —— 也就是"上一层临时表当时的全部内容"
     · 整批段的 depth 都设成这次掷出来的随机数
     · 撞上已有段、且 depth 和父段不同 -> 整批作废 */
static int genRun(EcEnv *env, int gen, EcPiece *cur, int depth, const EcPos *pos)
{
    if (depth > 8)
        return 0;
    int outerStart = env->batchStart;
    int start = env->n;
    env->batchStart = start;
    int ok;
    if (gen == EC_GEN_HOUSE_TOWER)
        ok = genHouseTower(env, cur, depth, pos);
    else if (gen == EC_GEN_TOWER)
        ok = genTower(env, cur, depth, pos);
    else if (gen == EC_GEN_BRIDGE)
        ok = genBridge(env, cur, depth, pos);
    else
        ok = genFatTower(env, cur, depth, pos);
    env->batchStart = outerStart;
    if (!ok)
    {
        env->n = start;
        return 0;
    }
    int gendepth = rngNext(env->rng, 32);
    for (int i = start; i < env->n; i++)
    {
        env->list[i].depth = gendepth;
        for (int j = outerStart; j < start; j++)
        {
            if (overlap(&env->list[i], &env->list[j]))
            {
                if (cur->depth != env->list[j].depth)
                {
                    env->n = start;
                    return 0;
                }
                break;
            }
        }
    }
    return 1;
}

int ecCityPieces(EcPiece *out, int maxp, uint64_t seed, int chunkX, int chunkZ)
{
    if (maxp <= 4)
        return 0;
    EcEnv env;
    memset(&env, 0, sizeof(env));
    env.list = out;
    env.maxp = maxp;
    EcRng rng;
    env.rng = &rng;
    rngLargeFeature(&rng, seed, chunkX, chunkZ);
    int rot = rngNextInt(&rng, 4);

    /* 城的第一个模板原点：区块中心偏 (-1,-1)（游戏里是 chunkX*16+7） */
    EcPiece *p = addPiece(&env, NULL, rot, chunkX * 16 + 7, 0, chunkZ * 16 + 7,
                          EC_BASE_FLOOR, 1);
    p = addPiece(&env, p, rot, -1, 0, -1, EC_SECOND_FLOOR_1, 0);
    p = addPiece(&env, p, rot, -1, 4, -1, EC_THIRD_FLOOR_1, 0);
    p = addPiece(&env, p, rot, -1, 8, -1, EC_THIRD_ROOF, 1);
    env.batchStart = 0;          /* 第一批要和"已有的那 4 段"比包围盒 */
    genRun(&env, EC_GEN_TOWER, p, 1, NULL);
    return env.n;
}
