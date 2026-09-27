/** 用游戏自己的 RandomSpreadStructurePlacement (class_6872) 对拍我们的结构摆放实现 */
public class StructureVerify {
    public static void main(String[] args) {
        // 枚举的静态初始化会碰注册表，先跑一遍 Bootstrap（失败也无所谓，能让注册表可用即可）
        try {
            net.minecraft.class_155.method_36208();   // SharedConstants.createGameVersion()
            net.minecraft.class_2966.method_12851();  // Bootstrap.initialize()
        } catch (Throwable ignored) {
            // 忽略
        }
        java.util.Random rnd = new java.util.Random(7);
        int bad = 0;
        int total = 0;
        int hits = 0;
        for (SeedCracker.Placement p : SeedCracker.PLACEMENTS) {
            if (p.spacing - p.separation <= 0) {
                continue;
            }
            net.minecraft.class_6873 type = p.triangular
                    ? net.minecraft.class_6873.field_36422
                    : net.minecraft.class_6873.field_36421;
            net.minecraft.class_6872 placement =
                    new net.minecraft.class_6872(p.spacing, p.separation, type, p.salt);
            for (int i = 0; i < 300; i++) {
                long seed = rnd.nextLong();
                int cx = rnd.nextInt(400000) - 200000;
                int cz = rnd.nextInt(400000) - 200000;
                net.minecraft.class_1923 start = placement.method_40169(seed, cx, cz);
                boolean gameSays = start.field_9181 == cx && start.field_9180 == cz;
                boolean mine = SeedCracker.structureStartAt(seed, cx, cz, p);
                total++;
                if (gameSays) {
                    hits++;
                }
                if (gameSays != mine) {
                    bad++;
                    if (bad <= 6) {
                        System.out.printf("不一致 %s seed=%d 区块(%d,%d) 游戏起始=(%d,%d) 我们=%b%n",
                                p.name, seed, cx, cz, start.field_9181, start.field_9180, mine);
                    }
                }
            }
        }
        System.out.println(bad == 0
                ? "OK: " + total + " 组结构摆放判定与游戏代码一致（其中 " + hits + " 组确实是起始区块）"
                : "FAIL: " + bad + " / " + total + " 组不一致");
    }
}
