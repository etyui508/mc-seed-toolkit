/** 对拍哈希种子：游戏里是 BiomeAccess.hashSeed = sha256(seed) 取前 8 字节（小端） */
public class HashVerify {
    public static void main(String[] args) {
        java.util.Random rnd = new java.util.Random(99);
        int bad = 0;
        for (int i = 0; i < 20000; i++) {
            long seed = rnd.nextLong();
            long game = net.minecraft.class_4543.method_27984(seed);
            long mine = SeedCracker.hashedSeed(seed);
            if (game != mine) {
                if (bad++ < 5) {
                    System.out.printf("不一致 seed=%d 游戏=%d 我们=%d%n", seed, game, mine);
                }
            }
        }
        System.out.println(bad == 0
                ? "OK: 20000 个种子的哈希种子与游戏代码一致"
                : "FAIL: " + bad + " 个不一致");
    }
}
