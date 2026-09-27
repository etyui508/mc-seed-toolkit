#ifndef ENDCITY_H
#define ENDCITY_H

#include <stdint.h>

/* 末地城的一个结构段 */
typedef struct {
    const char *name;
    int type;
    int rot;            /* 0=正 1=顺时针90 2=180 3=逆时针90（游戏的 BlockRotation 序） */
    int depth;          /* 同一批生成的段共用一个 depth（游戏的行为，碰撞判定要用） */
    int mirror;         /* 1 = LEFT_RIGHT（overwrite=false 的段：二层楼板那几段） */
    int px, py, pz;     /* 模板原点（y 是相对"基点 0"的） */
    int x0, y0, z0, x1, y1, z1;   /* 包围盒（含端点） */
} EcPiece;

enum {
    EC_BASE_FLOOR, EC_BASE_ROOF, EC_BRIDGE_END, EC_BRIDGE_GENTLE, EC_BRIDGE_PIECE,
    EC_BRIDGE_STEEP, EC_FAT_BASE, EC_FAT_MIDDLE, EC_FAT_TOP, EC_SECOND_FLOOR_1,
    EC_SECOND_FLOOR_2, EC_SECOND_ROOF, EC_SHIP, EC_THIRD_FLOOR_1, EC_THIRD_FLOOR_2,
    EC_THIRD_ROOF, EC_TOWER_BASE, EC_TOWER_PIECE, EC_TOWER_TOP, EC_TYPE_COUNT
};

#define EC_MAX_PIECES 512

/* 生成一座末地城的全部结构段，返回段数。
   基点 y 用 0（和游戏内部一样），要世界坐标的 y 再加基点高度（findstruct endbase）。
   注意：每个区块坐标对应的"城"，这里只管生成，不管群系/地形检查。 */
int ecCityPieces(EcPiece *out, int maxp, uint64_t seed, int chunkX, int chunkZ);

/* 模板本地坐标 -> 世界偏移（mirror=NONE）——龙头/鞘翅/宝箱那些标记用它换算 */
void ecTransformLocal(int rot, int lx, int ly, int lz, int *ox, int *oy, int *oz);

#endif
