/**
 * 找史莱姆区块：用 SeedCracker 里那个跟游戏逐项对拍过的判定公式。
 * 用法: java SlimeFind <种子> <中心方块x> <中心方块z> [搜索半径(方块)] [要几个]
 * 输出按距离排序。
 */
public class SlimeFind {
    public static void main(String[] args) {
        long seed = Long.parseLong(args[0]);
        int centerX = Integer.parseInt(args[1]);
        int centerZ = Integer.parseInt(args[2]);
        int radius = args.length > 3 ? Integer.parseInt(args[3]) : 512;
        int want = args.length > 4 ? Integer.parseInt(args[4]) : 12;

        int centerChunkX = Math.floorDiv(centerX, 16);
        int centerChunkZ = Math.floorDiv(centerZ, 16);
        int chunkRadius = radius / 16;
        int found = 0;
        java.util.List<int[]> hits = new java.util.ArrayList<>();
        for (int dx = -chunkRadius; dx <= chunkRadius; dx++) {
            for (int dz = -chunkRadius; dz <= chunkRadius; dz++) {
                int cx = centerChunkX + dx;
                int cz = centerChunkZ + dz;
                if (SeedCracker.isSlimeChunk(seed, cx, cz)) {
                    hits.add(new int[]{cx, cz, (int) Math.hypot(dx, dz)});
                }
            }
        }
        hits.sort(java.util.Comparator.comparingInt(h -> h[2]));
        System.out.printf("史莱姆区块（种子 %d，中心方块 %d,%d，半径 %d 格）：%d 个%n",
                seed, centerX, centerZ, radius, hits.size());
        for (int[] h : hits) {
            if (found++ >= want) {
                System.out.printf("  …还有 %d 个%n", hits.size() - want);
                break;
            }
            System.out.printf("  区块 (%d,%d)  方块中心 (%d,%d)  距你 %d 区块%n",
                    h[0], h[1], h[0] * 16 + 8, h[1] * 16 + 8, h[2]);
        }
        if (hits.isEmpty()) {
            System.out.println("半径内没有史莱姆区块，试试加大半径");
        }
    }
}
