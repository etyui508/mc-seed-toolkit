import it.unimi.dsi.fastutil.ints.IntArrayList;
import java.util.stream.IntStream;

/**
 * 用游戏自己的类来对拍我们复刻的算法：
 *  - 末地柱子排列：net.minecraft.class_156.method_43251(IntStream.range(0,10), new class_5820(v))
 *  - 史莱姆区块：net.minecraft.class_2919.method_12662(x, z, seed, 987234911L).nextInt(10)
 */
public class SpikeVerify {
    public static void main(String[] args) throws Exception {
        int bad = 0;
        for (int v = 0; v < 65536; v++) {
            IntArrayList game = (IntArrayList) net.minecraft.class_156.method_43251(
                    IntStream.range(0, 10), new net.minecraft.class_5820(v));
            int[] mine = SeedCracker.spikeHeights(v);
            for (int i = 0; i < 10; i++) {
                if (game.getInt(i) != mine[i]) {
                    if (bad++ < 5) {
                        System.out.printf("排出不一致 v=%d i=%d 游戏=%d 我们=%d%n",
                                v, i, game.getInt(i), mine[i]);
                    }
                    break;
                }
            }
        }
        System.out.println(bad == 0
                ? "OK: 65536 个 v 的柱子高度排列与游戏代码逐项一致"
                : "FAIL: " + bad + " 个 v 不一致");

        int slimeBad = 0;
        java.util.Random rnd = new java.util.Random(1);
        for (int i = 0; i < 20000; i++) {
            long seed = rnd.nextLong() & ((1L << 48) - 1);
            int x = rnd.nextInt(2_000_000) - 1_000_000;
            int z = rnd.nextInt(2_000_000) - 1_000_000;
            int game = net.minecraft.class_2919.method_12662(x, z, seed, 987234911L).method_43048(10);
            boolean mine = SeedCracker.isSlimeChunk(seed, x, z);
            if ((game == 0) != mine) {
                if (slimeBad++ < 5) {
                    System.out.printf("史莱姆判定不一致 seed=%d x=%d z=%d 游戏=%d 我们=%b%n", seed, x, z, game, mine);
                }
            }
        }
        System.out.println(slimeBad == 0
                ? "OK: 20000 组史莱姆区块判定与游戏代码一致"
                : "FAIL: " + slimeBad + " 组不一致");
    }
}
