import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicLong;
import java.util.stream.IntStream;

/** 量一下：每多一个史莱姆区块约束，候选数实际降到多少 */
public class InfoTest {
    public static void main(String[] args) {
        java.util.Random jr = new java.util.Random(20260924L);
        long seed = jr.nextLong() & ((1L << 48) - 1);
        int value = SeedCracker.spikeValue(seed);

        // 找 16 个散布在较大范围内的史莱姆区块
        List<int[]> slimes = new ArrayList<>();
        for (int i = 0; slimes.size() < 16; i++) {
            int x = 37 + i * 91;
            int z = -23 - i * 57;
            if (SeedCracker.isSlimeChunk(seed, x, z)) {
                slimes.add(new int[]{x, z});
            }
        }
        System.out.println("真实低48位种子 = " + seed + ", v = " + value);
        System.out.println("用作约束的史莱姆区块: " + slimes.size() + " 个");

        AtomicLong[] failAt = new AtomicLong[17];
        for (int i = 0; i < failAt.length; i++) {
            failAt[i] = new AtomicLong();
        }

        long t0 = System.currentTimeMillis();
        IntStream.range(0, 1 << 16).parallel().forEach(high -> {
            long base = ((long) high << 32) | ((long) value << 16);
            long[] local = new long[17];
            for (int low = 0; low < (1 << 16); low++) {
                long state2 = base | low;
                long s = SeedCracker.rewind(SeedCracker.rewind(state2)) ^ SeedCracker.MULT;
                int k = 0;
                while (k < slimes.size()) {
                    int[] c = slimes.get(k);
                    if (!SeedCracker.isSlimeChunk(s, c[0], c[1])) {
                        break;
                    }
                    k++;
                }
                local[k]++;
            }
            for (int i = 0; i < local.length; i++) {
                if (local[i] != 0) {
                    failAt[i].addAndGet(local[i]);
                }
            }
        });
        System.out.printf("枚举 2^32 个候选耗时 %d ms%n", System.currentTimeMillis() - t0);

        long surviving = failAt[16].get();
        for (int k = 16; k >= 1; k--) {
            surviving += failAt[k].get();
            if (k <= 16) {
                System.out.printf("  用 %2d 个史莱姆区块后剩 %d 个候选  (等价 %5.1f bit)%n",
                        k, surviving, 48 - Math.log(surviving) / Math.log(2));
            }
            if (k == 1) {
                break;
            }
        }
    }
}
