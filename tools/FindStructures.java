import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

/**
 * 已知种子 -> 列出周围的结构候选位置。
 * 用法: java FindStructures <种子> <中心区块x> <中心区块z> [半径区块数]
 *
 * 注意：算出来的是"摆放算法给出的起始区块"，结构是否真的生成还要过群系检查
 *      （比如海底神殿必须落在深海），所以是候选位置，去之前别抱 100% 期望。
 *      废弃矿井/埋藏的宝藏这种"每区块 0.4%/1%"的结构不列。
 */
public class FindStructures {
    public static void main(String[] args) {
        if (args.length < 3) {
            System.out.println("用法: java FindStructures <种子> <中心区块x> <中心区块z> [半径区块数]");
            return;
        }
        long seed = Long.parseLong(args[0]);
        int centerX = Integer.parseInt(args[1]);
        int centerZ = Integer.parseInt(args[2]);
        int radius = args.length > 3 ? Integer.parseInt(args[3]) : 200;

        System.out.printf("种子 %d (0x%016X)，搜索中心区块 (%d,%d)，半径 %d 区块（%d 方块）%n",
                seed, seed, centerX, centerZ, radius, radius * 16);
        for (SeedCracker.Placement p : SeedCracker.PLACEMENTS) {
            if (p.spacing <= 4) {
                continue;   // 矿井/藏宝图/下界化石这类不是"按区域摆一个"的，密度太高没意义
            }
            List<int[]> hits = new ArrayList<>();
            int rx0 = Math.floorDiv(centerX - radius, p.spacing);
            int rx1 = Math.floorDiv(centerX + radius, p.spacing);
            int rz0 = Math.floorDiv(centerZ - radius, p.spacing);
            int rz1 = Math.floorDiv(centerZ + radius, p.spacing);
            for (int rx = rx0; rx <= rx1; rx++) {
                for (int rz = rz0; rz <= rz1; rz++) {
                    int[] start = SeedCracker.startChunk(seed, rx, rz, p);
                    int dx = start[0] - centerX;
                    int dz = start[1] - centerZ;
                    if (Math.max(Math.abs(dx), Math.abs(dz)) <= radius) {
                        hits.add(new int[]{start[0], start[1], Math.max(Math.abs(dx), Math.abs(dz))});
                    }
                }
            }
            if (hits.isEmpty()) {
                continue;
            }
            hits.sort(Comparator.comparingInt(a -> a[2]));
            System.out.printf("%n[%s] %s（spacing %d/sep %d）：%d 个候选%n",
                    dimension(p.name), p.name, p.spacing, p.separation, hits.size());
            int shown = 0;
            for (int[] hit : hits) {
                if (shown++ >= 12) {
                    System.out.printf("  …还有 %d 个%n", hits.size() - 12);
                    break;
                }
                System.out.printf("  区块 (%d,%d)  方块 (%d,%d)  距中心 %d 区块  %s%n",
                        hit[0], hit[1], hit[0] * 16 + 8, hit[1] * 16 + 8, hit[2], direction(hit[0] - centerX, hit[1] - centerZ));
            }
        }
    }

    static String direction(int dx, int dz) {
        String ns = dz < 0 ? "北" : (dz > 0 ? "南" : "");
        String ew = dx < 0 ? "西" : (dx > 0 ? "东" : "");
        return ns + ew;
    }

    static String dimension(String set) {
        return switch (set) {
            case "nether_complexes", "nether_fossils" -> "下界";
            case "end_cities" -> "末地";
            default -> "主世界";
        };
    }
}
