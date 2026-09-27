import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.zip.GZIPInputStream;
import java.util.zip.InflaterInputStream;

/**
 * 扫存档找末地船（不用种子，靠"龙头"定位）。
 *
 * 为什么靠龙头就够了：
 *   末地船只有一种模板（end_city/ship.nbt），里面几个关键位置是固定的：
 *     龙头 (6,8,0)、鞘翅展示框 (6,5,7)、两个宝箱标记 (5,5,7)/(7,5,7)
 *   （原版 Structures/StructurePiece.handleMetadata 把 "Chest" 标记的箱子放在标记下面一格）
 *   而 `minecraft:dragon_wall_head` 这个方块**只有末地船会天然生成**，
 *   所以：在存档里扫到龙头 -> 按模板反推整条船的坐标 -> 鞘翅和宝箱就都出来了。
 *
 * 座落朝向有 4 种可能，用"预测出来的宝箱位置上是不是真的有箱子方块"来判定，
 * 所以结果自带校验（跟着种子算的那套 tools/ShipFinder.java 是同一套模板偏移）。
 *
 * 用法: java ShipScan <存档目录>
 *   （存档目录就是下载器写出来的那个文件夹，里面要有 region/）
 */
public class ShipScan {
    static final String HEAD = "minecraft:dragon_wall_head";
    static final String CHEST = "minecraft:chest";

    static final int[] HEAD_LOCAL = {6, 8, 0};
    static final int[] ELYTRA_LOCAL = {6, 5, 7};
    static final int[] CHEST1_LOCAL = {5, 5, 7};
    static final int[] CHEST2_LOCAL = {7, 5, 7};
    static final String[] ROT_CN = {"正", "顺时针90", "180", "逆时针90"};

    /** 模板里的本地坐标 -> 世界坐标的偏移量（mirror=NONE，和游戏的 transform 一致） */
    static int[] rot(int r, int lx, int ly, int lz) {
        switch (r) {
            case 1:  return new int[]{-lz, ly, lx};     // clockwise_90
            case 2:  return new int[]{-lx, ly, -lz};    // 180
            case 3:  return new int[]{lz, ly, -lx};     // counterclockwise_90
            default: return new int[]{lx, ly, lz};      // none
        }
    }

    public static void main(String[] args) throws Exception {
        if (args.length == 0) {
            System.out.println("用法: java ShipScan <存档目录>");
            System.out.println("  在下载的存档里扫末地船（靠龙头定位），直接给出龙头/鞘翅/宝箱坐标");
            return;
        }
        Path root = Path.of(args[0]);
        if (!Files.isDirectory(root)) {
            System.out.println("找不到目录: " + root);
            return;
        }
        Path regionDir = Files.isDirectory(root.resolve("region")) ? root.resolve("region") : root;
        if (!Files.isDirectory(regionDir)) {
            System.out.println("这个目录里没有 region/ : " + regionDir);
            System.out.println("（要填下载器写出来的存档目录，不是 .minecraft 目录）");
            return;
        }

        List<Path> files = new ArrayList<>();
        try (var stream = Files.list(regionDir)) {
            stream.filter(p -> p.getFileName().toString().matches("r\\.-?\\d+\\.-?\\d+\\.mca"))
                    .sorted().forEach(files::add);
        }
        System.out.printf("扫描 %s：%d 个区域文件%n", regionDir, files.size());
        if (files.isEmpty()) {
            System.out.println("没有区域文件 —— 存档是空的，或者下载器没写进 region/");
            return;
        }

        // 一趟扫完：龙头 + 箱子都要（箱子只用来给龙头判方向）
        Set<Long> heads = java.util.concurrent.ConcurrentHashMap.newKeySet();
        Set<Long> chests = java.util.concurrent.ConcurrentHashMap.newKeySet();
        long[] verdict = scan(files, heads, chests);
        System.out.printf("解开 %d 个区块、%.1f MB，用时 %.1f 秒%n",
                verdict[0], verdict[1] / 1048576.0, verdict[2] / 1e9);
        System.out.printf("龙头 %d 个，箱子 %d 个%n", heads.size(), chests.size());
        if (heads.isEmpty()) {
            System.out.println("没扫到龙头 —— 要么末地城那几片区域没下载到，要么船所在的区块被下载器跳过了。");
            System.out.println("（龙头 minecraft:dragon_wall_head 只有末地船会天然生成，是船的标志物）");
            return;
        }

        List<long[]> ships = new ArrayList<>();
        for (long key : heads) {
            ships.add(new long[]{unkey(key, 0), unkey(key, 1), unkey(key, 2)});
        }
        ships.sort((a, b) -> {
            long da = a[0] * a[0] + a[2] * a[2];
            long db = b[0] * b[0] + b[2] * b[2];
            return Long.compare(da, db);
        });

        System.out.printf("%n[末地] 末地船 %d 条（存档里扫出来的，不用种子）%n", ships.size());
        int n = 0;
        for (long[] h : ships) {
            n++;
            int hx = (int) h[0], hy = (int) h[1], hz = (int) h[2];
            int bestRot = -1, bestScore = -1;
            int[] bestElytra = null, bestC1 = null, bestC2 = null;
            for (int r = 0; r < 4; r++) {
                int[] headOff = rot(r, HEAD_LOCAL[0], HEAD_LOCAL[1], HEAD_LOCAL[2]);
                // 龙头世界坐标 = 模板原点 + 偏移 -> 反推模板原点
                int tx = hx - headOff[0], ty = hy - headOff[1], tz = hz - headOff[2];
                int[] e = add(tx, ty, tz, rot(r, ELYTRA_LOCAL[0], ELYTRA_LOCAL[1], ELYTRA_LOCAL[2]));
                int[] c1 = add(tx, ty, tz, rot(r, CHEST1_LOCAL[0], CHEST1_LOCAL[1], CHEST1_LOCAL[2]));
                int[] c2 = add(tx, ty, tz, rot(r, CHEST2_LOCAL[0], CHEST2_LOCAL[1], CHEST2_LOCAL[2]));
                c1[1] -= 1;        // 游戏把 "Chest" 标记的箱子放在标记下面一格
                c2[1] -= 1;
                int score = (chests.contains(key(c1)) ? 1 : 0) + (chests.contains(key(c2)) ? 1 : 0);
                if (score > bestScore) {
                    bestScore = score;
                    bestRot = r;
                    bestElytra = e;
                    bestC1 = c1;
                    bestC2 = c2;
                }
            }
            long dist = Math.round(Math.sqrt((double) hx * hx + (double) hz * hz));
            System.out.printf("%n  %d. 龙头 goto %d %d   (y=%d)   离末地中心 %d 格   朝向 %s%n",
                    n, hx, hz, hy, dist, ROT_CN[bestRot]);
            System.out.printf("     鞘翅展示框 (%d,%d,%d)%n", bestElytra[0], bestElytra[1], bestElytra[2]);
            System.out.printf("     两个宝箱   (%d,%d,%d) (%d,%d,%d)%n",
                    bestC1[0], bestC1[1], bestC1[2], bestC2[0], bestC2[1], bestC2[2]);
            if (bestScore == 2) {
                System.out.println("     校验：预测的两个宝箱位置上存档里真的有箱子 ✅");
            } else if (bestScore == 1) {
                System.out.println("     校验：两个宝箱只对上一个（另一个可能没下载到）⚠");
            } else {
                System.out.println("     校验：预测的宝箱位置上没扫到箱子（这片区块大概没下载全）⚠");
            }
        }
        System.out.println("\n提示：龙头就是船头的标志物，飞过去看到那个龙头就是这条船；");
        System.out.println("      鞘翅挂在展示框里，宝箱在船身里。y 是算出来的精确值（不定形地形不影响它）。");
    }

    static int[] add(int tx, int ty, int tz, int[] off) {
        return new int[]{tx + off[0], ty + off[1], tz + off[2]};
    }

    static long key(int[] p) {
        return key(p[0], p[1], p[2]);
    }

    /** 坐标 -> 一个 long（每个轴 21 位，够 ±100 万格） */
    static long key(int x, int y, int z) {
        return ((long) (x & 0x1FFFFF) << 42) | ((long) (y & 0x1FFFFF) << 21) | (z & 0x1FFFFF);
    }

    static int unkey(long k, int axis) {
        int shift = 42 - axis * 21;
        int v = (int) ((k >>> shift) & 0x1FFFFF);
        return (v & 0x100000) != 0 ? v - 0x200000 : v;   // 21 位补码还原成负数
    }

    /** 扫一遍区域文件，收龙头和箱子，返回 {区块数, 字节数, 纳秒} */
    static long[] scan(List<Path> files, Set<Long> heads, Set<Long> chests) {
        java.util.concurrent.atomic.LongAdder chunks = new java.util.concurrent.atomic.LongAdder();
        java.util.concurrent.atomic.LongAdder bytes = new java.util.concurrent.atomic.LongAdder();
        long t0 = System.nanoTime();
        Set<String> targets = new LinkedHashSet<>(List.of(HEAD, CHEST));
        files.parallelStream().forEach(file -> {
            byte[] region;
            try {
                region = Files.readAllBytes(file);
            } catch (IOException e) {
                return;
            }
            String name = file.getFileName().toString();
            String[] parts = name.substring(2, name.length() - 4).split("\\.");
            int regionX = Integer.parseInt(parts[0]);
            int regionZ = Integer.parseInt(parts[1]);
            for (int slot = 0; slot < 1024; slot++) {
                int header = slot * 4;
                int offset = ((region[header] & 0xFF) << 16) | ((region[header + 1] & 0xFF) << 8)
                        | (region[header + 2] & 0xFF);
                if (offset == 0) continue;
                int pos = offset * 4096;
                if (pos + 5 > region.length) continue;
                int length = ((region[pos] & 0xFF) << 24) | ((region[pos + 1] & 0xFF) << 16)
                        | ((region[pos + 2] & 0xFF) << 8) | (region[pos + 3] & 0xFF);
                int compression = region[pos + 4] & 0xFF;
                int size = length - 1;
                if (size <= 0 || pos + 5 + size > region.length) continue;
                byte[] chunk;
                try {
                    chunk = decompress(region, pos + 5, size, compression);
                } catch (Exception e) {
                    continue;
                }
                // 便宜筛选：解压出来连目标方块名都没有就跳过
                boolean any = false;
                for (String t : targets) {
                    if (contains(chunk, t)) { any = true; break; }
                }
                if (!any) continue;
                int chunkX = regionX * 32 + (slot % 32);
                int chunkZ = regionZ * 32 + (slot / 32);
                decodeChunk(chunk, chunkX, chunkZ, heads, chests);
                chunks.increment();
                bytes.add(chunk.length);
            }
        });
        return new long[]{chunks.sum(), bytes.sum(), System.nanoTime() - t0};
    }

    static void decodeChunk(byte[] chunk, int chunkX, int chunkZ, Set<Long> heads, Set<Long> chests) {
        try {
            int[] cursor = {0};
            Object rootObj = PortalScan.Nbt.read(chunk, cursor);
            if (!(rootObj instanceof Map<?, ?> root)) return;
            if (!(root.get("sections") instanceof List<?> sections)) return;
            boolean hasHead = contains(chunk, HEAD);
            boolean hasChest = contains(chunk, CHEST);
            for (Object sectionObj : sections) {
                if (!(sectionObj instanceof Map<?, ?> section)) continue;
                int sectionY = ((Number) section.get("Y")).intValue();
                if (!(section.get("block_states") instanceof Map<?, ?> blockStates)) continue;
                if (!(blockStates.get("palette") instanceof List<?> palette)) continue;
                long[] data = (long[]) blockStates.get("data");
                int bits = Math.max(4, 32 - Integer.numberOfLeadingZeros(Math.max(1, palette.size() - 1)));
                if (((1 << bits) - 1) < palette.size() - 1) bits++;
                int perLong = 64 / bits;
                long mask = (1L << bits) - 1;
                // 这个 section 的调色板里有没有我们要的方块，没有就整段跳过
                boolean wantHead = false, wantChest = false;
                for (Object entryObj : palette) {
                    if (!(entryObj instanceof Map<?, ?> entry)) continue;
                    Object nm = entry.get("Name");
                    if (HEAD.equals(nm)) wantHead = true;
                    if (CHEST.equals(nm)) wantChest = true;
                }
                if ((!wantHead || !hasHead) && (!wantChest || !hasChest)) continue;
                for (int y = 0; y < 16; y++) {
                    for (int z = 0; z < 16; z++) {
                        for (int x = 0; x < 16; x++) {
                            int index = (y << 8) | (z << 4) | x;
                            int paletteIndex = 0;
                            if (data != null && data.length > 0) {
                                int longIndex = index / perLong;
                                if (longIndex >= data.length) continue;
                                paletteIndex = (int) ((data[longIndex] >>> ((index % perLong) * bits)) & mask);
                            }
                            if (paletteIndex >= palette.size()) continue;
                            if (!(palette.get(paletteIndex) instanceof Map<?, ?> entry)) continue;
                            Object nm = entry.get("Name");
                            int wx = chunkX * 16 + x;
                            int wy = sectionY * 16 + y;
                            int wz = chunkZ * 16 + z;
                            if (wantHead && HEAD.equals(nm)) heads.add(key(wx, wy, wz));
                            else if (wantChest && CHEST.equals(nm)) chests.add(key(wx, wy, wz));
                        }
                    }
                }
            }
        } catch (Throwable ignored) {
            // 坏区块跳过
        }
    }

    static byte[] decompress(byte[] data, int from, int size, int compression) throws IOException {
        byte[] raw = new byte[size];
        System.arraycopy(data, from, raw, 0, size);
        InputStream in = switch (compression) {
            case 1 -> new GZIPInputStream(new java.io.ByteArrayInputStream(raw));
            case 2 -> new InflaterInputStream(new java.io.ByteArrayInputStream(raw));
            case 3 -> new java.io.ByteArrayInputStream(raw);
            default -> throw new IOException("未知压缩类型 " + compression);
        };
        ByteArrayOutputStream out = new ByteArrayOutputStream(Math.max(size * 4, 8192));
        in.transferTo(out);
        in.close();
        return out.toByteArray();
    }

    static boolean contains(byte[] data, String needle) {
        byte[] target = needle.getBytes(StandardCharsets.US_ASCII);
        outer:
        for (int i = 0; i + target.length <= data.length; i++) {
            for (int j = 0; j < target.length; j++) {
                if (data[i + j] != target[j]) continue outer;
            }
            return true;
        }
        return false;
    }
}
