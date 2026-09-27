import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 统计下载的存档里每个区块有多少矿石，排出最密集的区块。
 *
 * 和 BlockFind 的区别：BlockFind 把一个方块的所有坐标列出来（找末地船那种用），
 * 这里是"按区块计数再排名"（找矿用）—— 所以只存计数和深度，不存每个坐标。
 *
 * 用法:
 *   java OreScan <存档目录> <方块id...> [--top N] [--min N] [--y 最小 最大] [--csv]
 *
 * 例:
 *   java OreScan saves/world minecraft:diamond_ore minecraft:deepslate_diamond_ore
 *   java OreScan saves/world/DIM-1 minecraft:ancient_debris --y 8 120
 */
public class OreScan {

    public static void main(String[] args) throws Exception {
        if (args.length < 2) {
            System.out.println("用法: java OreScan <存档目录> <方块id...> "
                    + "[--top N] [--min N] [--y 最小 最大] [--csv]");
            return;
        }
        Path root = Path.of(args[0]);
        List<String> targets = new ArrayList<>();
        int top = 20;
        int minCount = 1;
        int yMin = Integer.MIN_VALUE;
        int yMax = Integer.MAX_VALUE;
        boolean csv = false;
        for (int i = 1; i < args.length; i++) {
            String a = args[i];
            switch (a) {
                case "--top" -> top = Integer.parseInt(args[++i]);
                case "--min" -> minCount = Integer.parseInt(args[++i]);
                case "--y" -> {
                    yMin = Integer.parseInt(args[++i]);
                    yMax = Integer.parseInt(args[++i]);
                }
                case "--csv" -> csv = true;
                default -> targets.add(a);
            }
        }
        if (targets.isEmpty()) {
            System.out.println("没给方块 id");
            return;
        }

        Path regionDir = Files.isDirectory(root.resolve("region")) ? root.resolve("region") : root;
        List<Path> files = new ArrayList<>();
        try (var stream = Files.list(regionDir)) {
            stream.filter(p -> p.getFileName().toString().matches("r\\.-?\\d+\\.-?\\d+\\.mca"))
                    .sorted().forEach(files::add);
        }

        // 每个区块：int[目标数] 计数 + long[目标数] y 之和
        Map<Long, int[]> counts = new HashMap<>();
        Map<Long, long[]> ySums = new HashMap<>();
        long chunksSeen = 0;

        for (Path file : files) {
            byte[] region = Files.readAllBytes(file);
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
                // 便宜筛选：这个区块里一个目标都没有就跳过（省掉解析 NBT 的开销）
                boolean any = false;
                for (String t : targets) {
                    if (contains(chunk, t)) {
                        any = true;
                        break;
                    }
                }
                if (!any) continue;
                chunksSeen++;
                int chunkX = regionX * 32 + (slot % 32);
                int chunkZ = regionZ * 32 + (slot / 32);
                long key = (((long) chunkX) << 32) ^ (chunkZ & 0xFFFFFFFFL);
                decodeChunk(chunk, chunkX, chunkZ, targets, counts, ySums, yMin, yMax);
            }
        }

        List<long[]> rows = new ArrayList<>();          // [key, 总数]
        long grand = 0;
        for (Map.Entry<Long, int[]> e : counts.entrySet()) {
            int sum = 0;
            for (int c : e.getValue()) sum += c;
            if (sum < minCount) continue;
            grand += sum;
            rows.add(new long[]{e.getKey(), sum});
        }
        rows.sort(Comparator.comparingLong((long[] r) -> -r[1]).thenComparingLong(r -> r[0]));

        if (csv) {
            StringBuilder head = new StringBuilder("chunkX,chunkZ,blockX,blockZ,总数量");
            for (String t : targets) head.append(",").append(t.replace("minecraft:", ""));
            System.out.println(head);
            for (long[] r : rows) {
                int cx = (int) (r[0] >> 32);
                int cz = (int) r[0];
                StringBuilder sb = new StringBuilder();
                sb.append(cx).append(",").append(cz).append(",")
                  .append(cx * 16).append(",").append(cz * 16).append(",").append(r[1]);
                int[] c = counts.get(r[0]);
                for (int i = 0; i < targets.size(); i++) sb.append(",").append(c[i]);
                System.out.println(sb);
            }
            return;
        }

        System.out.printf("扫描 %s：%d 个区域文件，%d 个区块里有目标矿石%n",
                regionDir, files.size(), chunksSeen);
        if (rows.isEmpty()) {
            System.out.println("一个都没找到 —— 确认方块 id 写对了吗（1.18+ 深层矿石是 "
                    + "deepslate_ 开头），以及那个范围内下载过区块没有。");
            return;
        }
        long total = 0;
        for (long[] r : rows) total += r[1];
        System.out.printf("有矿石的区块 %d 个，合计 %d 个，平均每区块 %.2f 个%n",
                rows.size(), total, (double) total / rows.size());
        System.out.println();
        System.out.printf("最密集的 %d 个区块：%n", Math.min(top, rows.size()));
        System.out.printf("  %-4s %-14s %-22s %6s  %s%n",
                "排名", "区块", "方块范围(x,z)", "数量", "细分 / 平均 y");
        int rank = 0;
        for (long[] r : rows) {
            if (rank++ >= top) break;
            int cx = (int) (r[0] >> 32);
            int cz = (int) r[0];
            int[] c = counts.get(r[0]);
            long[] ys = ySums.get(r[0]);
            StringBuilder detail = new StringBuilder();
            for (int i = 0; i < targets.size(); i++) {
                if (c[i] == 0) continue;
                if (detail.length() > 0) detail.append("  ");
                detail.append(shortName(targets.get(i))).append("=").append(c[i]);
                if (ys != null && c[i] > 0) {
                    detail.append("(y≈").append(ys[i] / c[i]).append(")");
                }
            }
            System.out.printf("  %-4d (%6d,%6d)  x %5d..%-5d z %5d..%-5d %6d  %s%n",
                    rank, cx, cz, cx * 16, cx * 16 + 15, cz * 16, cz * 16 + 15,
                    r[1], detail);
        }
        System.out.println();
        System.out.println("提示：区块坐标 (cx,cz) 传送到中心就是 "
                + "x=cx*16+8、z=cz*16+8；按 F3 看「区块」那一行也对得上。");
    }

    static String shortName(String id) {
        String n = id.startsWith("minecraft:") ? id.substring("minecraft:".length()) : id;
        return n.replace("_ore", "");
    }

    static void decodeChunk(byte[] chunk, int chunkX, int chunkZ, List<String> targets,
                            Map<Long, int[]> counts, Map<Long, long[]> ySums,
                            int yMin, int yMax) {
        try {
            int[] cursor = {0};
            Object rootObj = PortalScan.Nbt.read(chunk, cursor);
            if (!(rootObj instanceof Map<?, ?> root)) return;
            if (!(root.get("sections") instanceof List<?> sections)) return;
            long key = (((long) chunkX) << 32) ^ (chunkZ & 0xFFFFFFFFL);
            int[] c = counts.computeIfAbsent(key, k -> new int[targets.size()]);
            long[] ys = ySums.computeIfAbsent(key, k -> new long[targets.size()]);
            for (Object sectionObj : sections) {
                if (!(sectionObj instanceof Map<?, ?> section)) continue;
                int sectionY = ((Number) section.get("Y")).intValue();
                if (sectionY * 16 + 15 < yMin || sectionY * 16 > yMax) continue;
                if (!(section.get("block_states") instanceof Map<?, ?> blockStates)) continue;
                if (!(blockStates.get("palette") instanceof List<?> palette)) continue;
                long[] data = (long[]) blockStates.get("data");
                int bits = Math.max(4, 32 - Integer.numberOfLeadingZeros(Math.max(1, palette.size() - 1)));
                if (((1 << bits) - 1) < palette.size() - 1) bits++;
                int perLong = 64 / bits;
                long mask = (1L << bits) - 1;
                // 先把调色板翻成"第几个目标是它"（同一段里同一个方块只会命中一次）
                int[] lookup = new int[palette.size()];
                java.util.Arrays.fill(lookup, -1);
                for (int i = 0; i < palette.size(); i++) {
                    if (!(palette.get(i) instanceof Map<?, ?> entry)) continue;
                    if (!(entry.get("Name") instanceof String name)) continue;
                    for (int t = 0; t < targets.size(); t++) {
                        if (name.equals(targets.get(t))) {
                            lookup[i] = t;
                        }
                    }
                }
                for (int y = 0; y < 16; y++) {
                    int wy = sectionY * 16 + y;
                    if (wy < yMin || wy > yMax) continue;
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
                            int t = lookup[paletteIndex];
                            if (t < 0) continue;
                            c[t]++;
                            ys[t] += wy;
                        }
                    }
                }
            }
        } catch (Throwable ignored) {
            // 单个区块坏了不影响整体
        }
    }

    static boolean contains(byte[] haystack, String needle) {
        byte[] n = needle.getBytes(java.nio.charset.StandardCharsets.US_ASCII);
        outer:
        for (int i = 0; i <= haystack.length - n.length; i++) {
            for (int j = 0; j < n.length; j++) {
                if (haystack[i + j] != n[j]) continue outer;
            }
            return true;
        }
        return false;
    }

    static byte[] decompress(byte[] region, int from, int size, int compression) throws IOException {
        byte[] raw = new byte[size];
        System.arraycopy(region, from, raw, 0, size);
        java.io.InputStream in;
        if (compression == 1) {
            in = new java.util.zip.GZIPInputStream(new java.io.ByteArrayInputStream(raw));
        } else if (compression == 2) {
            in = new java.util.zip.InflaterInputStream(new java.io.ByteArrayInputStream(raw));
        } else if (compression == 3) {
            in = new java.io.ByteArrayInputStream(raw);      // 没压缩
        } else {
            throw new IOException("未知压缩方式 " + compression);
        }
        java.io.ByteArrayOutputStream out = new java.io.ByteArrayOutputStream();
        byte[] buf = new byte[1 << 16];
        int n;
        while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
        in.close();
        return out.toByteArray();
    }
}
