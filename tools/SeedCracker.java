import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.stream.IntStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;

/**
 * Minecraft 1.21.10 种子破解工具（无需 OP，纯客户端数据）。
 *
 * 数据来源（都在客户端能看到）：
 *   1) 末地 10 根黑曜石柱的顶面 Y 坐标  ->  16 bit 约束
 *      原版代码：EndSpikeFeature.getSpikes() = Random.create(seed).nextLong() & 0xFFFF
 *      10 根柱子的高度是 0..9 的一个排列（顶面 y = 76 + 3h），排列只由这 16 位决定。
 *   2) 若干“确定是史莱姆区块”的区块坐标  ->  每个约 3.32 bit
 *      原版代码：ChunkRandom.getSlimeRandom(x, z, seed, 987234911L).nextInt(10) == 0
 *
 * 两者合起来约束的是种子的低 48 位（原版所有 java.util.Random 体系只吃低 48 位）。
 *
 * 用法：
 *   java SeedCracker positions
 *   java SeedCracker end <种子>                    看某个种子的末地柱子长什么样
 *   java SeedCracker spikes <柱0顶Y,柱1顶Y,...柱9顶Y>
 *   java SeedCracker crack <v> "slime:144,-48;ocean_monuments:123,-456;villages:20,30,2"
 *   java SeedCracker selftest
 */
public final class SeedCracker {
    static final long MULT = 0x5DEECE66DL;
    static final long ADD = 0xBL;
    static final long MASK = (1L << 48) - 1;
    /** MULT 在 2^48 下的乘法逆元 */
    static final long INVMULT = 246154705703781L;

    static final int PILLARS = 10;
    static final int BASE_TOP_Y = 76;
    static final int TOP_STEP = 3;

    static final int[] PILLAR_X = new int[PILLARS];
    static final int[] PILLAR_Z = new int[PILLARS];

    /** 结构集摆放参数：从 class_7072 (StructureSets) 的字节码里抠出来的 */
    static final class Placement {
        final String name;
        final int spacing;
        final int separation;
        final int salt;
        final boolean triangular;
        /** 1.9~1.12 里不是 random_spread 的那几种，用专门的算法 */
        final String special;

        Placement(String name, int spacing, int separation, int salt, boolean triangular) {
            this(name, spacing, separation, salt, triangular, null);
        }

        Placement(String name, int spacing, int separation, int salt, boolean triangular, String special) {
            this.name = name;
            this.spacing = spacing;
            this.separation = separation;
            this.salt = salt;
            this.triangular = triangular;
            this.special = special;
        }
    }

    static final Placement[] PLACEMENTS = {
            new Placement("villages", 34, 8, 10387312, false),
            new Placement("desert_pyramids", 32, 8, 14357617, false),
            new Placement("igloos", 32, 8, 14357618, false),
            new Placement("jungle_temples", 32, 8, 14357619, false),
            new Placement("swamp_huts", 32, 8, 14357620, false),
            new Placement("pillager_outposts", 32, 8, 165745296, false),
            new Placement("ocean_monuments", 32, 5, 10387313, true),
            new Placement("woodland_mansions", 80, 20, 10387319, true),
            new Placement("buried_treasures", 1, 0, 0, false),
            new Placement("mineshafts", 1, 0, 0, false),
            new Placement("ruined_portals", 40, 15, 34222645, false),
            new Placement("shipwrecks", 24, 4, 165745295, false),
            new Placement("ocean_ruins", 20, 8, 14357621, false),
            new Placement("nether_complexes", 27, 4, 30084232, false),
            new Placement("nether_fossils", 2, 1, 14357921, false),
            new Placement("end_cities", 20, 11, 10387313, true),
            new Placement("ancient_cities", 24, 8, 20083232, false),
            new Placement("trail_ruins", 34, 8, 83469867, false),
            new Placement("trial_chambers", 34, 12, 94251327, false),
            // 26.3 新加的（老版本用不到，放这儿只是让 26.x 也能用它的提示）
            new Placement("abandoned_camp", 37, 8, 91231127, false),
    };

    /**
     * 1.9 ~ 1.12 的结构摆放参数（那时候还没有 structure_set 数据，全是代码里写死的）：
     *   · 村庄是 32 格网格（1.14 起才改成 34），盐一样
     *   · 沙漠神殿 / 丛林神殿 / 女巫小屋 / 雪屋 共用同一个 32 格网格和同一个盐 14357617
     *   · 海底神殿 32/5 三角形、林地府邸 80/20 三角形、末地城 20/11 三角形 —— 和现代一样
     *   · 废弃矿井、下界要塞是另外的算法（见下面的 mineshaftChance / fortressOld）
     * 摆放公式本身和现代是同一套：regionX*341873128712 + regionZ*132897987541 + seed + salt。
     */
    static final Placement[] PLACEMENTS_OLD = {
            new Placement("villages", 32, 8, 10387312, false),
            new Placement("temples", 32, 8, 14357617, false),
            new Placement("desert_pyramids", 32, 8, 14357617, false),
            new Placement("jungle_temples", 32, 8, 14357617, false),
            new Placement("swamp_huts", 32, 8, 14357617, false),
            new Placement("igloos", 32, 8, 14357617, false),
            new Placement("ocean_monuments", 32, 5, 10387313, true),
            new Placement("woodland_mansions", 80, 20, 10387319, true),
            new Placement("end_cities", 20, 11, 10387313, true),
            new Placement("mineshafts", 1, 0, 0, false, "mineshaft_chance"),
            new Placement("nether_complexes", 16, 0, 0, false, "fortress_old"),
    };

    /** null = 用现代（1.13+）那套；否则用 1.9~1.12 那套 */
    static Placement[] ACTIVE = null;

    /**
     * 少数参数在 1.18 改过，按版本覆盖。
     * 查 cubiomes 的 finders.c 得到的规则：
     *   case Village: *sconf = mc <= MC_1_17 ? s_village_117 : s_village;
     * 也就是 **1.17 及以前的村庄是 32 格网格，1.18 起才改成 34**。
     * 这个数错了会把正确种子筛掉（最后有 sha256 兜底，不会解错，但可能解不出来）。
     */
    static java.util.Map<String, Placement> OVERRIDES = java.util.Map.of();

    /** 按版本切换结构摆放参数 */
    static void setVersion(String ver) {
        if (ver == null || ver.isBlank()) {
            ACTIVE = null;
            return;
        }
        String v = ver.trim();
        boolean old = false;
        try {
            String[] p = v.split("\\.");
            int major = Integer.parseInt(p[0].replaceAll("\\D+$", ""));
            int minor = p.length > 1 ? Integer.parseInt(p[1].replaceAll("\\D.*$", "")) : 0;
            old = (major == 1 && minor >= 9 && minor <= 12);
        } catch (Exception ignore) {
            // 版本号看不懂就按现代算
        }
        ACTIVE = old ? PLACEMENTS_OLD : null;
        // 1.16~1.17：村庄网格还是 32（别的结构这几年没改，见 docs/版本支持.md）
        boolean mid = false;
        try {
            String[] p = v.split("\\.");
            int major = Integer.parseInt(p[0].replaceAll("\\D+$", ""));
            int minor = p.length > 1 ? Integer.parseInt(p[1].replaceAll("\\D.*$", "")) : 0;
            mid = (major == 1 && minor >= 16 && minor <= 17);
        } catch (Exception ignore) {
            // 看不懂就当现代
        }
        OVERRIDES = mid
                ? java.util.Map.of("villages",
                        new Placement("villages", 32, 8, 10387312, false))
                : java.util.Map.of();
        System.out.println("（结构摆放按 " + v + "：" + (old
                ? "1.9~1.12 老算法 —— 村庄 32 格网格、四种神殿共用一个盐、矿井按概率、要塞用老公式"
                : mid
                ? "1.13+ 数据驱动；1.17 及以前村庄是 32 格网格（1.18 才改 34）"
                : "1.13+ 数据驱动（random_spread）") + "）");
    }

    static {
        for (int i = 0; i < PILLARS; i++) {
            // 和原版一致的表达式：floor(42 * cos(2 * (-PI + 0.3141592653589793 * i)))
            double angle = 2.0 * (-Math.PI + 0.3141592653589793 * i);
            PILLAR_X[i] = (int) Math.floor(42.0 * Math.cos(angle));
            PILLAR_Z[i] = (int) Math.floor(42.0 * Math.sin(angle));
        }
    }

    static Placement placement(String name) {
        Placement over = OVERRIDES.get(name);          // 先看版本覆盖
        if (over != null) {
            return over;
        }
        if (ACTIVE != null) {
            for (Placement p : ACTIVE) {
                if (p.name.equals(name)) {
                    return p;
                }
            }
        }
        for (Placement p : PLACEMENTS) {
            if (p.name.equals(name)) {
                return p;
            }
        }
        for (Placement p : PLACEMENTS_OLD) {
            if (p.name.equals(name)) {
                return p;
            }
        }
        return null;
    }

    /** 与原版 CheckedRandom（= java.util.Random）完全一致的线性同余发生器 */
    static final class Lcg {
        private long state;

        Lcg(long seed) {
            state = (seed ^ MULT) & MASK;
        }

        int next(int bits) {
            state = (state * MULT + ADD) & MASK;
            return (int) (state >>> (48 - bits));
        }

        int nextInt(int bound) {
            int r = next(31);
            int m = bound - 1;
            if ((bound & m) == 0) {
                r = (int) (((long) bound * r) >> 31);
            } else {
                int u = r;
                int res = u % bound;
                while (u - res + m < 0) {
                    u = next(31);
                    res = u % bound;
                }
                r = res;
            }
            return r;
        }

        int nextInt() {
            return next(32);
        }

        long nextLong() {
            return ((long) next(32) << 32) + next(32);
        }

        void setSeed(long seed) {
            state = (seed ^ MULT) & MASK;
        }

        double nextDouble() {
            return (((long) next(26) << 27) + next(27)) * 0x1.0p-53;
        }
    }

    /**
     * 1.9 ~ 1.12 的废弃矿井：按区块概率生成（不是 random_spread）。原版 MapGenMineshaft：
     *   rand.setSeed(worldSeed);
     *   k = rand.nextLong(); l = rand.nextLong();
     *   rand.setSeed((long)chunkX * k ^ (long)chunkZ * l ^ worldSeed);
     *   rand.nextInt();                   // 老版本这里多走一步
     *   if (rand.nextDouble() >= 0.004) return false;
     *   d = max(|chunkX|, |chunkZ|);
     *   return d >= 80 || rand.nextInt(80) < d;      // 离原点太近会被再筛一次
     * （和 cubiomes 的 getMineshafts 逐区块对拍通过）
     */
    static boolean mineshaftChance(long seed, int chunkX, int chunkZ, double chance) {
        Lcg rand = new Lcg(seed);
        long k = rand.nextLong();
        long l = rand.nextLong();
        rand.setSeed((long) chunkX * k ^ (long) chunkZ * l ^ seed);
        rand.nextInt();
        if (rand.nextDouble() >= chance) {
            return false;
        }
        int d = Math.max(Math.abs(chunkX), Math.abs(chunkZ));
        return d >= 80 || rand.nextInt(80) < d;
    }

    /**
     * 1.9 ~ 1.12 的下界要塞：16 区块一格的网格 + 老公式。原版 MapGenNetherBridge：
     *   i = chunkX >> 4; j = chunkZ >> 4;
     *   rand.setSeed((long)(i ^ j << 4) ^ worldSeed);
     *   rand.nextInt();
     *   if (rand.nextInt(3) != 0) return false;
     *   return chunkX == (i<<4)+4+rand.nextInt(8) && chunkZ == (j<<4)+4+rand.nextInt(8);
     */
    static boolean fortressOld(long seed, int chunkX, int chunkZ) {
        int i = chunkX >> 4;
        int j = chunkZ >> 4;
        Lcg rand = new Lcg((long) (i ^ j << 4) ^ seed);
        rand.nextInt();
        if (rand.nextInt(3) != 0) {
            return false;
        }
        return chunkX == (i << 4) + 4 + rand.nextInt(8) && chunkZ == (j << 4) + 4 + rand.nextInt(8);
    }

    static long advance(long state) {
        return (state * MULT + ADD) & MASK;
    }

    static long rewind(long state) {
        return ((state - ADD) * INVMULT) & MASK;
    }

    /** 种子 -> 末地柱子那 16 位 */
    static int spikeValue(long seed) {
        Lcg random = new Lcg(seed);
        return (int) (random.nextLong() & 0xFFFFL);
    }

    /** 那 16 位 -> 10 根柱子的 h 值（第 i 根柱子对应 PILLAR_X/Z[i]） */
    static int[] spikeHeights(int value) {
        int[] heights = new int[PILLARS];
        for (int i = 0; i < PILLARS; i++) {
            heights[i] = i;
        }
        Lcg random = new Lcg(value);
        for (int i = PILLARS; i > 1; i--) {
            int j = random.nextInt(i);
            int tmp = heights[j];
            heights[j] = heights[i - 1];
            heights[i - 1] = tmp;
        }
        return heights;
    }

    static int topY(int h) {
        return BASE_TOP_Y + TOP_STEP * h;
    }

    /** 原版 ChunkRandom.getSlimeRandom(x, z, seed, 987234911L).nextInt(10) == 0 */
    static boolean isSlimeChunk(long seed, int chunkX, int chunkZ) {
        // 注意：原版这几项都是 int 运算（会溢出）后再转 long，必须照抄，不能直接用 long 算
        long l = seed
                + (long) (chunkX * chunkX * 4987142)
                + (long) (chunkX * 5947611)
                + (long) (chunkZ * chunkZ) * 4392871L
                + (long) (chunkZ * 389711);
        // 展开成无分配写法（这个函数在破解循环里会跑几十亿次）
        long state = ((l ^ 987234911L) ^ MULT) & MASK;
        state = (state * MULT + ADD) & MASK;
        int u = (int) (state >>> 17);
        int res;
        while (true) {
            res = u % 10;
            if (u - res + 9 >= 0) break;
            state = (state * MULT + ADD) & MASK;
            u = (int) (state >>> 17);
        }
        return res == 0;
    }

    /**
     * 原版 RandomSpreadStructurePlacement.getStartChunk(seed, chunkX, chunkZ)：
     *   regionX = floorDiv(chunkX, spacing)，同理 regionZ
     *   ChunkRandom.setRegionSeed(seed, regionX, regionZ, salt)
     *   偏移 = spreadType.getOffset(random, spacing - separation)
     * 返回起始区块是否正好是 (chunkX, chunkZ)。
     */
    static boolean structureStartAt(long seed, int chunkX, int chunkZ, Placement p) {
        int regionX = Math.floorDiv(chunkX, p.spacing);
        int regionZ = Math.floorDiv(chunkZ, p.spacing);
        int[] start = startChunk(seed, regionX, regionZ, p);
        return start[0] == chunkX && start[1] == chunkZ;
    }

    /** 直接算某个 region 的结构起始区块（原版 RandomSpreadStructurePlacement.getStartChunk 的 region 版本） */
    static int[] startChunk(long seed, int regionX, int regionZ, Placement p) {
        long l = (long) regionX * 341873128712L
                + (long) regionZ * 132897987541L
                + seed
                + (long) p.salt;
        Lcg random = new Lcg(l);
        int bound = p.spacing - p.separation;
        int offsetX;
        int offsetZ;
        if (p.triangular) {
            offsetX = (random.nextInt(bound) + random.nextInt(bound)) / 2;
            offsetZ = (random.nextInt(bound) + random.nextInt(bound)) / 2;
        } else {
            offsetX = random.nextInt(bound);
            offsetZ = random.nextInt(bound);
        }
        return new int[]{regionX * p.spacing + offsetX, regionZ * p.spacing + offsetZ};
    }

    /** 玩家看到的建筑不一定正好压在起始区块上，所以允许在 (x,z) 周围 radius 个区块内 */
    private static final ThreadLocal<long[]> RNG_STATE = ThreadLocal.withInitial(() -> new long[1]);

    /** 无分配版的 nextInt(bound)：状态放在 ThreadLocal 里（跟 java.util.Random 完全一致） */
    static int nextIntTC(int bound) {
        long[] st = RNG_STATE.get();
        st[0] = (st[0] * MULT + ADD) & MASK;
        int r = (int) (st[0] >>> 17);
        int m = bound - 1;
        if ((bound & m) == 0) {
            return (int) (((long) bound * r) >> 31);
        }
        int u = r;
        int res;
        while (true) {
            res = u % bound;
            if (u - res + m >= 0) {
                return res;
            }
            st[0] = (st[0] * MULT + ADD) & MASK;
            u = (int) (st[0] >>> 17);
        }
    }

    /** 玩家看到的建筑不一定正好压在起始区块上，所以允许在 (x,z) 周围 radius 个区块内 */
    static boolean structureNear(long seed, int chunkX, int chunkZ, int radius, Placement p) {
        int x0 = chunkX - radius;
        int x1 = chunkX + radius;
        int z0 = chunkZ - radius;
        int z1 = chunkZ + radius;
        int regionX0 = Math.floorDiv(x0, p.spacing);
        int regionX1 = Math.floorDiv(x1, p.spacing);
        int regionZ0 = Math.floorDiv(z0, p.spacing);
        int regionZ1 = Math.floorDiv(z1, p.spacing);
        int bound = p.spacing - p.separation;
        long[] st = RNG_STATE.get();
        for (int regionX = regionX0; regionX <= regionX1; regionX++) {
            for (int regionZ = regionZ0; regionZ <= regionZ1; regionZ++) {
                long l = (long) regionX * 341873128712L
                        + (long) regionZ * 132897987541L
                        + seed
                        + (long) p.salt;
                st[0] = (l ^ MULT) & MASK;
                int offX;
                int offZ;
                if (p.triangular) {
                    offX = (nextIntTC(bound) + nextIntTC(bound)) / 2;
                    offZ = (nextIntTC(bound) + nextIntTC(bound)) / 2;
                } else {
                    offX = nextIntTC(bound);
                    offZ = nextIntTC(bound);
                }
                int startX = regionX * p.spacing + offX;
                int startZ = regionZ * p.spacing + offZ;
                if (startX >= x0 && startX <= x1 && startZ >= z0 && startZ <= z1) {
                    return true;
                }
            }
        }
        return false;
    }

    /** 一条观测约束 */
    static final class Constraint {
        final Placement placement;   // null 表示史莱姆区块
        final int x;
        final int z;
        final int radius;

        Constraint(Placement placement, int x, int z, int radius) {
            this.placement = placement;
            this.x = x;
            this.z = z;
            this.radius = radius;
        }

        boolean matches(long seed) {
            if (placement == null) {
                return isSlimeChunk(seed, x, z);
            }
            if ("mineshaft_chance".equals(placement.special)) {
                for (int dx = -radius; dx <= radius; dx++) {
                    for (int dz = -radius; dz <= radius; dz++) {
                        if (mineshaftChance(seed, x + dx, z + dz, 0.004)) {
                            return true;
                        }
                    }
                }
                return false;
            }
            if ("fortress_old".equals(placement.special)) {
                for (int dx = -radius; dx <= radius; dx++) {
                    for (int dz = -radius; dz <= radius; dz++) {
                        if (fortressOld(seed, x + dx, z + dz)) {
                            return true;
                        }
                    }
                }
                return false;
            }
            return structureNear(seed, x, z, radius, placement);
        }

        /** 这条观测有多大可能会“通过”（用来决定先算哪条最省时间） */
        double passProbability() {
            if (placement == null) {
                return 0.1;   // nextInt(10) == 0
            }
            if (placement.special != null) {
                double p = 0.005 * (2 * radius + 1) * (2 * radius + 1);
                return Math.min(p, 1.0);
            }
            double p = (double) (2 * radius + 1) * (2 * radius + 1)
                    / ((double) placement.spacing * placement.spacing);
            return Math.min(p, 1.0);
        }

        /** 判定开销 / 通过率，越小越先算 */
        double cost() {
            double ops = placement == null ? 3.0 : 6.0 + 3.0 * (2 * radius + 1);
            return ops / passProbability();
        }

        /** 这条观测大概值多少 bit */
        double infoBits() {
            if (placement == null) {
                return Math.log(10.0) / Math.log(2.0);
            }
            int bound = placement.spacing - placement.separation;
            double bits = 2.0 * (Math.log(bound) / Math.log(2.0));
            if (placement.triangular) {
                bits -= 1.0;
            }
            bits -= 2.0 * (Math.log(2 * radius + 1) / Math.log(2.0));
            return Math.max(bits, 0.0);
        }

        @Override
        public String toString() {
            return (placement == null ? "slime" : placement.name)
                    + ":" + x + "," + z + (placement == null ? "" : "±" + radius);
        }
    }

    static Constraint parseConstraint(String text) {
        String[] parts = text.trim().split("[:,]");
        if (parts.length < 3) {
            throw new IllegalArgumentException("看不懂的约束: " + text + "（格式 类型:x,z[,半径]）");
        }
        String type = parts[0].trim();
        int x = Integer.parseInt(parts[1].trim());
        int z = Integer.parseInt(parts[2].trim());
        if (type.equals("slime")) {
            return new Constraint(null, x, z, 0);
        }
        Placement p = placement(type);
        if (p == null) {
            throw new IllegalArgumentException("不认识的结构集: " + type
                    + "（可用：slime、" + java.util.Arrays.stream(PLACEMENTS).map(q -> q.name).toList() + "）");
        }
        int radius = parts.length > 3 ? Integer.parseInt(parts[3].trim()) : 1;
        return new Constraint(p, x, z, radius);
    }

    // ------------------------------------------------------- 哈希种子（定高 16 位）

    /** 对应原版 BiomeAccess.hashSeed：Guava Hashing.sha256().hashLong(seed).asLong()（小端） */
    static long hashedSeed(long seed) {
        // 用复用 buffer 的写法（这个函数在定高 16 位时会被调用几十亿次）
        MessageDigest digest = SHA.get();
        byte[] buf = BUF.get();
        for (int i = 0; i < 8; i++) {
            buf[i] = (byte) (seed >>> (8 * i));
        }
        digest.reset();
        digest.update(buf, 0, 8);
        try {
            digest.digest(buf, 0, 32);
        } catch (java.security.DigestException e) {
            throw new RuntimeException(e);
        }
        long out = 0;
        for (int i = 7; i >= 0; i--) {
            out = (out << 8) | (buf[i] & 0xFFL);
        }
        return out;
    }

    private static final ThreadLocal<MessageDigest> SHA = ThreadLocal.withInitial(() -> {
        try {
            return MessageDigest.getInstance("SHA-256");
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    });
    private static final ThreadLocal<byte[]> BUF = ThreadLocal.withInitial(() -> new byte[64]);

    // ---------------------------------------------------------------- 进度上报
    /** 进度打到 stderr（带 ##PROGRESS 前缀好解析），stdout 留给正经结果。
     *  12 个线程一起喊会把管道塞满，所以每 200ms 最多报一条。 */
    private static final java.util.concurrent.atomic.AtomicLong LAST_PROGRESS =
            new java.util.concurrent.atomic.AtomicLong(0);

    static void progress(String phase, long done, long total) {
        long now = System.currentTimeMillis();
        boolean isFinal = done >= total;            // 最后一帧：不管限流、不管抢没抢到，都要报出去
        long prev = LAST_PROGRESS.get();
        if (!isFinal && now - prev < 200) {
            return;
        }
        if (!LAST_PROGRESS.compareAndSet(prev, now)) {
            if (!isFinal) {
                return;
            }
            LAST_PROGRESS.set(now);                 // 抢输了也要把 100% 报出去，不然进度条走不到底
        }
        System.err.printf("##PROGRESS %s %d %d%n", phase, done, total);
        System.err.flush();
    }

    /**
     * 客户端能看到的就是这个哈希值。它由整个 64 位种子算出，
     * 所以只要低 48 位候选不多，就可以把高 16 位 65536 种全试一遍，把完整种子定死。
     */
    static long[] resolveHighBits(long low48, long hashedSeed) {
        for (int high = 0; high < 65536; high++) {
            long seed = low48 | ((long) high << 48);
            if (hashedSeed(seed) == hashedSeed) {
                return new long[]{seed};
            }
        }
        return null;
    }

    // ---------------------------------------------------------------- CLI

    public static void main(String[] args) {
        // 版本从环境变量来（app/calc_seed.py 会带上）：结构摆放参数按版本挑
        String envVer = System.getenv("MCVER");
        if (envVer != null && !envVer.isBlank()) {
            setVersion(envVer);
        }
        if (args.length == 0) {
            usage();
            return;
        }
        switch (args[0]) {
            case "positions" -> printPositions();
            case "end" -> printEnd(Long.parseLong(args[1]));
            case "spikes" -> spikesFromObservation(args[1]);
            case "crack" -> crackFromCli(args[1], args[2]);
            case "file" -> crackFromFile(args[1]);
            case "check" -> checkSeed(args);
            case "selftest" -> selfTest();
            default -> usage();
        }
    }

    static void usage() {
        System.out.println("""
                用法:
                  java SeedCracker positions
                  java SeedCracker end <种子>
                  java SeedCracker spikes <柱0顶Y,柱1顶Y,...,柱9顶Y>
                  java SeedCracker crack <v> "<约束;约束;...>"
                  java SeedCracker file <观测文件.txt>        （模组自动生成的那个文件）
                  java SeedCracker selftest

                约束写法：
                  slime:x,z                          确认是史莱姆区块的区块坐标
                  ocean_monuments:x,z[±r]             结构主体所在区块（r 默认 1）
                  可用的结构集见 PLACEMENTS 表，例如 villages / desert_pyramids / swamp_huts /
                  igloos / jungle_temples / pillager_outposts / ocean_monuments /
                  woodland_mansions / ruined_portals / shipwrecks / ocean_ruins /
                  nether_complexes / end_cities / ancient_cities / trail_ruins / trial_chambers
                """);
    }

    static void printPositions() {
        System.out.println("10 根柱子的中心坐标（按索引 i，末地 (0,0) 为圆心，半径 42）：");
        for (int i = 0; i < PILLARS; i++) {
            System.out.printf("  柱%d: x=%d z=%d   顶面 y = 76 + 3h%n", i, PILLAR_X[i], PILLAR_Z[i]);
        }
        System.out.println("记下每根柱子的顶面 Y（F3 看 Targeted Block 的 y），按上面的索引顺序填进 spikes 命令");
    }

    static void printEnd(long seed) {
        int value = spikeValue(seed);
        int[] heights = spikeHeights(value);
        System.out.printf("种子 %d（低48位=0x%012X）: v=%d%n", seed, seed & MASK, value);
        for (int i = 0; i < PILLARS; i++) {
            System.out.printf("  柱%d: x=%d z=%d  h=%d  顶面 y=%d%n",
                    i, PILLAR_X[i], PILLAR_Z[i], heights[i], topY(heights[i]));
        }
    }

    static void spikesFromObservation(String csv) {
        String[] parts = csv.split(",");
        if (parts.length != PILLARS) {
            System.out.println("需要正好 " + PILLARS + " 个顶面 Y 值，按柱子索引顺序，用逗号分隔");
            return;
        }
        int[] observed = new int[PILLARS];
        for (int i = 0; i < PILLARS; i++) {
            int y = Integer.parseInt(parts[i].trim());
            if ((y - BASE_TOP_Y) % TOP_STEP != 0) {
                System.out.printf("第 %d 根顶面 y=%d 不是 76+3h 的形式，可能量错了（应该比 76 大、且与 76 同余 mod 3）%n", i, y);
                return;
            }
            int h = (y - BASE_TOP_Y) / TOP_STEP;
            if (h < 0 || h > 9) {
                System.out.printf("第 %d 根顶面 y=%d 超出范围（原版只能是 76..103）%n", i, y);
                return;
            }
            observed[i] = h;
        }
        List<Integer> matches = new ArrayList<>();
        for (int v = 0; v < 65536; v++) {
            int[] heights = spikeHeights(v);
            boolean ok = true;
            for (int i = 0; i < PILLARS && ok; i++) {
                ok = heights[i] == observed[i];
            }
            if (ok) {
                matches.add(v);
            }
        }
        if (matches.isEmpty()) {
            System.out.println("没有匹配的 v —— 要么量错了，要么这个服务器的末地被改过（不是原版世界生成）");
            return;
        }
        System.out.println("匹配到的 v: " + matches + "（共 " + matches.size() + " 个，取第一个喂给 crack 即可）");
    }

    static void crackFromCli(String vStr, String constraintStr) {
        int v = Integer.parseInt(vStr);
        List<Constraint> constraints = new ArrayList<>();
        for (String piece : constraintStr.split(";")) {
            if (piece.isBlank()) {
                continue;
            }
            constraints.add(parseConstraint(piece));
        }
        constraints.sort(java.util.Comparator.comparingDouble(Constraint::cost));
        System.out.println("约束：" + constraints);
        double bits = constraints.stream().mapToDouble(Constraint::infoBits).sum() + 16.0;
        System.out.printf("观测合计约 %.1f bit（含末地柱子 16 bit），预计剩 %.3g 个候选%n",
                bits, Math.pow(2, Math.max(48 - bits, 0)));
        long t0 = System.currentTimeMillis();
        List<long[]> results = crack(v, constraints, 0);
        System.out.printf("枚举 2^32 个候选耗时 %d ms%n", System.currentTimeMillis() - t0);
        if (results.isEmpty()) {
            System.out.println("没解出来：数据可能记错了（或者服务器改过生成）");
            return;
        }
        System.out.println("低 48 位候选（" + results.size() + " 个）：");
        for (long[] r : results) {
            System.out.printf("  种子低48位 = %d  (0x%012X)%n", r[0], r[0]);
        }
        System.out.println("完整 64 位种子 = 低48位 + (高16位 << 48)，高 16 位共 65536 种可能：");
        System.out.println("  只找结构（村庄/神殿/前哨/海底神殿…）用哪个高 16 位都一样；");
        System.out.println("  要预测地形/群系，再用已知群系点筛，或用单机建世界试。");
    }

    /** 枚举所有满足 16 位末地约束、且满足全部观测约束的“种子低 48 位” */
    /** 候选太多时不用全收集（几百万条会吃内存 + 拖慢）；够用就行 */
    static final int CANDIDATE_CAP = 200000;

    /** 枚举所有满足 16 位末地约束、且"最多允许 maxBad 条观测对不上"的种子低 48 位。
     *  maxBad=0 就是严格模式（原来那样）。放宽是安全的：最后有 sha256 哈希兜底，不会解错，
     *  只是多留几个候选 —— 用来对付"观测文件里混进了别的世界/手滑记错的几条"。 */
    static List<long[]> crack(int value, List<Constraint> constraints, int maxBad) {
        List<long[]> results = Collections.synchronizedList(new ArrayList<>());
        java.util.concurrent.atomic.LongAdder total = new java.util.concurrent.atomic.LongAdder();
        java.util.concurrent.atomic.AtomicLong done = new java.util.concurrent.atomic.AtomicLong();
        IntStream.range(0, 1 << 16).parallel().forEach(high -> {
            progress("enum", done.incrementAndGet(), 1 << 16);
            long base = ((long) high << 32) | ((long) value << 16);
            for (int low = 0; low < (1 << 16); low++) {
                long state2 = base | low;
                long seed = rewind(rewind(state2)) ^ MULT;
                int bad = 0;
                for (int i = 0; i < constraints.size(); i++) {
                    if (!constraints.get(i).matches(seed)) {
                        if (++bad > maxBad) {
                            break;
                        }
                    }
                }
                if (bad <= maxBad) {
                    total.increment();
                    if (results.size() < CANDIDATE_CAP) {
                        results.add(new long[]{seed});
                    }
                }
            }
        });
        if (total.sum() > CANDIDATE_CAP) {
            System.out.printf("（候选共 %d 个，只保留前 %d 个用来定高 16 位；加更多观测会更快）%n",
                    total.sum(), CANDIDATE_CAP);
        }
        return results;
    }

    // ------------------------------------------------- 读模组产出的观测文件

    /** 解析模组写的观测文件，一条龙解到底；返回结果（有哈希时是完整 64 位种子） */
    static List<Long> crackFromFile(String pathStr) {
        Path path = Path.of(pathStr);
        List<String> lines;
        try {
            lines = Files.readAllLines(path, StandardCharsets.UTF_8);
        } catch (Exception e) {
            System.out.println("读不了文件: " + path + " -> " + e);
            return List.of();
        }

        int value = -1;
        long hashed = 0L;
        boolean hasHash = false;
        List<Constraint> constraints = new ArrayList<>();
        java.util.Map<String, Integer> slimeCounts = new java.util.LinkedHashMap<>();
        int structLines = 0;
        int biomeLines = 0;

        // 先看有没有写版本号（决定用 1.13+ 还是 1.9~1.12 的结构摆放参数）
        for (String raw : lines) {
            String line = raw.trim();
            if (line.startsWith("version=")) {
                setVersion(line.substring("version=".length()).trim());
                break;
            }
        }

        for (String raw : lines) {
            String line = raw.trim();
            if (line.isEmpty() || line.startsWith("#")) {
                continue;
            }
            if (line.startsWith("hashed_seed=")) {
                hashed = Long.parseLong(line.substring("hashed_seed=".length()).trim());
                hasHash = true;
            } else if (line.startsWith("end_pillars")) {
                int idx = line.indexOf("v=");
                if (idx >= 0) {
                    value = Integer.parseInt(line.substring(idx + 2).trim().split("\\s+")[0]);
                }
            } else if (line.startsWith("struct:")) {
                String[] parts = line.split(":");
                if (parts.length < 3) {
                    continue;
                }
                Placement placement = placement(parts[1]);
                String[] xz = parts[2].split(",");
                if (placement == null || xz.length < 2) {
                    continue;
                }
                int radius = xz.length > 2 ? Integer.parseInt(xz[2].trim()) : 0;
                constraints.add(new Constraint(placement,
                        Integer.parseInt(xz[0].trim()), Integer.parseInt(xz[1].trim()), radius));
                structLines++;
            } else if (line.startsWith("slime:")) {
                String head = line.substring("slime:".length()).trim();
                String[] fields = head.split("\\s+");
                String[] xz = fields[0].split(",");
                if (xz.length < 2) {
                    continue;
                }
                int count = 1;
                for (String field : fields) {
                    if (field.startsWith("count=")) {
                        count = Integer.parseInt(field.substring("count=".length()).trim());
                    }
                }
                slimeCounts.merge(xz[0].trim() + "," + xz[1].trim(), count, Math::max);
            } else if (line.startsWith("biome:")) {
                biomeLines++;
            }
        }

        int slimeUsed = 0;
        for (java.util.Map.Entry<String, Integer> entry : slimeCounts.entrySet()) {
            if (entry.getValue() >= 2) {
                String[] xz = entry.getKey().split(",");
                constraints.add(new Constraint(null,
                        Integer.parseInt(xz[0]), Integer.parseInt(xz[1]), 0));
                slimeUsed++;
            }
        }

        constraints.sort(java.util.Comparator.comparingDouble(Constraint::cost));
        double bits = constraints.stream().mapToDouble(Constraint::infoBits).sum() + (value < 0 ? 0.0 : 16.0);
        System.out.printf("读入: v=%s, 结构 %d 条, 史莱姆区块 %d/%d 条(>=2次), 群系采样 %d 条, 哈希种子 %s%n",
                value < 0 ? "（还没有末地柱子数据）" : Integer.toString(value),
                structLines, slimeUsed, slimeCounts.size(), biomeLines,
                hasHash ? Long.toString(hashed) : "（没有）");
        System.out.printf("约束合计约 %.1f bit（其中末地柱子 %s）%n",
                bits, value < 0 ? "还没拿到，去一趟末地能白嫖 16 bit" : "16 bit");
        if (value < 0) {
            System.out.println("现在还没法枚举：先去一趟末地让模组记下柱子（或者手动跑 spikes 命令填 v）。");
            return List.of();
        }

        long t0 = System.currentTimeMillis();
        // 允许"一小部分观测对不上"：观测文件是**追加**写的，混进别的世界/手滑记错的几条很常见。
        // 放宽是安全的 —— 最后那道 sha256 哈希是完整 64 位种子的指纹，解错了根本过不了。
        // 有哈希就一步放宽到位（分多轮试会慢好几倍）；没哈希就只放宽一点点，免得候选太多。
        int allowedBad = hasHash ? Math.min(8, Math.max(1, constraints.size() / 3))
                                 : Math.min(2, Math.max(0, constraints.size() / 6));
        if (allowedBad > 0) {
            System.out.printf("（共 %d 条观测，允许最多 %d 条对不上%s）%n",
                    constraints.size(), allowedBad,
                    hasHash ? "，最后有 sha256 兜底，不会解错" : "，没有哈希兜底，结果不一定唯一");
        }
        List<long[]> candidates = crack(value, constraints, allowedBad);
        System.out.printf("枚举 2^32 个候选耗时 %d ms，剩 %d 个低 48 位候选%n",
                System.currentTimeMillis() - t0, candidates.size());
        if (candidates.isEmpty()) {
            System.out.println("没解出来：对不上的观测太多了（已经允许 " + allowedBad + " 条对不上还是不行）。");
            System.out.println("常见原因：末地柱子没下全、结构提示太少，或者服务器改过世界生成。");
            return List.of();
        }

        if (!hasHash) {
            System.out.println("没有哈希种子，只能给到低 48 位（找结构够用）：");
            if (allowedBad > 0) {
                System.out.println("（注意：这次是放宽过的，这些候选不一定唯一 —— 想要准的，"
                        + "要么补观测，要么用模组抓哈希种子）");
            }
            List<Long> lows = new ArrayList<>();
            for (long[] c : candidates) {
                System.out.printf("  0x%012X%n", c[0]);
                lows.add(c[0]);
            }
            return lows;
        }

        System.out.println("用哈希种子定高 16 位…");
        if (candidates.size() > 20000) {
            double sec = candidates.size() * 65536.0 * 62e-9 / 3.0;
            System.out.printf("  候选 %d 个，这步预计 %d 秒 —— 候选越多越慢，多下载几个海底神殿/试炼密室会快很多%n",
                    candidates.size(), (int) sec);
        }
        long t1 = System.currentTimeMillis();
        final long hashedSeedValue = hashed;
        List<Long> full = java.util.Collections.synchronizedList(new ArrayList<>());
        java.util.concurrent.atomic.AtomicLong hashDone = new java.util.concurrent.atomic.AtomicLong();
        candidates.parallelStream().forEach(c -> {
            progress("hash", hashDone.incrementAndGet(), candidates.size());
            long[] resolved = resolveHighBits(c[0], hashedSeedValue);
            if (resolved != null) {
                full.add(resolved[0]);
            }
        });
        System.out.printf("耗时 %d ms%n", System.currentTimeMillis() - t1);
        if (full.isEmpty()) {
            System.out.println("低 48 位候选里没有一个能对上哈希 —— 说明约束里有错数据（史莱姆区块容易记错）");
            return List.of();
        }
        System.out.println("完整种子（64 位）：");
        for (long seed : full) {
            System.out.printf("  %d   (0x%016X)  sha256校验通过 ✅%n", seed, seed);
            List<String> mismatched = new ArrayList<>();
            for (Constraint c : constraints) {
                if (!c.matches(seed)) {
                    mismatched.add(c.toString());
                }
            }
            if (!mismatched.isEmpty()) {
                System.out.println("      这条种子里，下面这几条观测和它不符合（基本就是脏数据，可以剪掉）：");
                System.out.println("        " + mismatched);
            }
        }
        return full;
    }

    // ------------------------------------------------- 校验一个已知的种子

    /** check <种子> [观测文件]：用哈希种子 + 所有观测数据验证这个种子对不对 */
    static void checkSeed(String[] args) {
        if (args.length < 2) {
            System.out.println("用法: java SeedCracker check <种子> [观测文件]");
            return;
        }
        long seed = Long.parseLong(args[1].trim());
        String pathStr = args.length > 2 ? args[2] : "seedhelper-observations.txt";

        System.out.printf("待验证种子 = %d  (0x%016X)%n", seed, seed);
        long mine = hashedSeed(seed);
        System.out.printf("这个种子的 sha256 哈希种子 = %d%n", mine);

        Path path = Path.of(pathStr);
        List<String> lines = List.of();
        try {
            if (Files.exists(path)) {
                // 优先用合并过的文件（带结构提示），没有就用模组原始文件
                List<String> merged = List.of();
                Path mergedPath = Path.of("observations-merged.txt");
                if (Files.exists(mergedPath) && !pathStr.endsWith("observations-merged.txt")) {
                    merged = Files.readAllLines(mergedPath, StandardCharsets.UTF_8);
                }
                lines = merged.isEmpty() ? Files.readAllLines(path, StandardCharsets.UTF_8) : merged;
            }
        } catch (Exception e) {
            System.out.println("读观测文件失败: " + e);
        }

        long recorded = 0L;
        boolean hasRecorded = false;
        List<Constraint> constraints = new java.util.ArrayList<>();
        java.util.Map<String, Integer> slimeCounts = new java.util.LinkedHashMap<>();
        for (String raw : lines) {
            String line = raw.trim();
            if (line.startsWith("hashed_seed=")) {
                recorded = Long.parseLong(line.substring("hashed_seed=".length()).trim());
                hasRecorded = true;
            } else if (line.startsWith("struct:")) {
                String[] parts = line.split(":");
                if (parts.length >= 3) {
                    Placement placement = placement(parts[1]);
                    String[] xz = parts[2].split(",");
                    if (placement != null && xz.length >= 2) {
                        int radius = xz.length > 2 ? Integer.parseInt(xz[2].trim()) : 0;
                        constraints.add(new Constraint(placement,
                                Integer.parseInt(xz[0].trim()), Integer.parseInt(xz[1].trim()), radius));
                    }
                }
            } else if (line.startsWith("slime:")) {
                String[] fields = line.substring("slime:".length()).trim().split("\\s+");
                String[] xz = fields[0].split(",");
                if (xz.length >= 2) {
                    int count = 1;
                    for (String field : fields) {
                        if (field.startsWith("count=")) {
                            count = Integer.parseInt(field.substring("count=".length()).trim());
                        }
                    }
                    slimeCounts.merge(xz[0].trim() + "," + xz[1].trim(), count, Math::max);
                }
            }
        }
        for (java.util.Map.Entry<String, Integer> entry : slimeCounts.entrySet()) {
            if (entry.getValue() >= 2) {
                String[] xz = entry.getKey().split(",");
                constraints.add(new Constraint(null,
                        Integer.parseInt(xz[0]), Integer.parseInt(xz[1]), 0));
            }
        }

        System.out.println();
        if (hasRecorded) {
            System.out.printf("客户端记录的哈希种子 = %d%n", recorded);
            System.out.println(mine == recorded
                    ? "✅ 哈希完全一致 —— 这个种子是真的（sha256 撞车不可能）"
                    : "❌ 哈希对不上 —— 这个种子不对");
        } else {
            System.out.println("（观测文件里没有 hashed_seed，跳过哈希校验）");
        }

        if (!constraints.isEmpty()) {
            int matched = 0;
            java.util.List<String> bad = new java.util.ArrayList<>();
            for (Constraint c : constraints) {
                if (c.matches(seed)) {
                    matched++;
                } else {
                    bad.add(c.toString());
                }
            }
            System.out.printf("用你的观测数据交叉验证：%d/%d 条对得上%n", matched, constraints.size());
            if (!bad.isEmpty()) {
                System.out.println("  对不上的：" + bad);
                System.out.println("  （少量对不上可能是扫描半径/误判，全对不上就是种子不对或服务器改了生成）");
            }
        }

        int value = spikeValue(seed);
        int[] heights = spikeHeights(value);
        System.out.println();
        System.out.printf("这个种子对应的末地柱子（进末地可以直接核对）：v=%d%n", value);
        for (int i = 0; i < PILLARS; i++) {
            System.out.printf("  柱%d x=%d z=%d  顶面 y=%d%n",
                    i, PILLAR_X[i], PILLAR_Z[i], topY(heights[i]));
        }
    }

    // ---------------------------------------------------------- selftest

    static void selfTest() {
        java.util.Random jr = new java.util.Random(20260924L);
        long seed = jr.nextLong();
        System.out.printf("合成测试：真实完整种子 = %d (0x%016X)%n", seed, seed);

        int value = spikeValue(seed);
        int[] heights = spikeHeights(value);
        StringBuilder file = new StringBuilder();
        file.append("# selftest 合成观测\n");
        file.append("hashed_seed=").append(hashedSeed(seed)).append('\n');
        file.append("end_pillars tops=");
        for (int i = 0; i < PILLARS; i++) {
            file.append(topY(heights[i])).append(i < PILLARS - 1 ? "," : "");
        }
        file.append(" v=").append(value).append('\n');

        // 模拟模组自动记录：结构记的是游戏里的“起始区块”，属于精确值
        Placement monument = placement("ocean_monuments");
        int found = 0;
        for (int cx = 60; cx < 4000 && found < 3; cx += 5) {
            for (int cz = -300; cz < 300 && found < 3; cz += 7) {
                if (structureStartAt(seed, cx, cz, monument)) {
                    file.append("struct:ocean_monuments:").append(cx).append(',').append(cz).append('\n');
                    found++;
                    break;
                }
            }
        }
        Placement village = placement("villages");
        found = 0;
        for (int cx = 20; cx < 4000 && found < 2; cx += 9) {
            for (int cz = 30; cz < 3000 && found < 2; cz += 13) {
                if (structureStartAt(seed, cx, cz, village)) {
                    file.append("struct:villages:").append(cx).append(',').append(cz).append('\n');
                    found++;
                    break;
                }
            }
        }
        int slimes = 0;
        for (int cx = 40; cx < 4000 && slimes < 4; cx++) {
            if (isSlimeChunk(seed, cx, -cx / 3)) {
                file.append("slime:").append(cx).append(',').append(-cx / 3).append(" count=3\n");
                slimes++;
            }
        }
        file.append("biome:0,0=minecraft:plains\n");

        System.out.println("--- 合成观测文件内容（就是模组会写的那种）---");
        System.out.print(file);
        try {
            Path tmp = Files.createTempFile("seedhelper-selftest", ".txt");
            Files.writeString(tmp, file.toString(), StandardCharsets.UTF_8);
            System.out.println("--- 破解 ---");
            List<Long> result = crackFromFile(tmp.toString());
            System.out.println(result.contains(seed) ? "命中真实完整种子 ✅" : "没有命中真实种子 ❌");
        } catch (Exception e) {
            System.out.println("自测失败: " + e);
        }
    }
}
