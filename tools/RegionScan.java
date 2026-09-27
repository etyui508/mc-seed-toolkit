import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.zip.GZIPInputStream;
import java.util.zip.InflaterInputStream;

/**
 * 离线扫存档找结构：流式读 .mca（区域文件），在解压后的区块数据里找“只有该结构才会有的方块”，
 * 把聚类中心转成 struct:<结构集>:<区块x>,<区块z>,<半径> 交给破解器用。
 *
 * 用法: java RegionScan <存档目录或 region 目录> [--all]
 *   --all  连低置信度（可能被玩家建筑误伤）的也输出
 *
 * 只读、流式，内存占用与存档大小无关（一次只解压一个区块）。
 */
public class RegionScan {
    /** 证据方块 -> 结构集；minChunks 是聚类至少要有多少个区块才算数 */
    record Marker(String set, String block, int minChunks, boolean highConfidence) {
    }

    static final List<Marker> MARKERS = List.of(
            // 海底神殿：海晶石只在这里自然生成
            new Marker("ocean_monuments", "minecraft:prismarine", 3, true),
            new Marker("ocean_monuments", "minecraft:prismarine_bricks", 2, true),
            new Marker("ocean_monuments", "minecraft:dark_prismarine", 3, true),
            new Marker("ocean_monuments", "minecraft:sea_lantern", 2, true),
            new Marker("ocean_monuments", "minecraft:wet_sponge", 1, true),
            // 远古城市
            new Marker("ancient_cities", "minecraft:sculk_catalyst", 2, true),
            new Marker("ancient_cities", "minecraft:reinforced_deepslate", 1, true),
            // 试炼密室
            new Marker("trial_chambers", "minecraft:trial_spawner", 1, true),
            new Marker("trial_chambers", "minecraft:vault", 1, true),
            // 末地城
            new Marker("end_cities", "minecraft:purpur_block", 3, true),
            new Marker("end_cities", "minecraft:purpur_pillar", 2, true),
            // 下界要塞 / 堡垒
            new Marker("nether_complexes", "minecraft:nether_bricks", 4, true),
            new Marker("nether_complexes", "minecraft:gilded_blackstone", 2, true),
            new Marker("nether_complexes", "minecraft:polished_blackstone_bricks", 4, true),
            // 古迹废墟
            // 古迹废墟：用泥砖（原版结构模板里只有它用泥砖；可疑沙砾在实测里有别的来源，会误报）
            new Marker("trail_ruins", "minecraft:mud_bricks", 3, true),
            // 废弃传送门：哭泣的黑曜石只有它天然生成；主世界的下界岩也基本只有它
            new Marker("ruined_portals", "minecraft:crying_obsidian", 1, true),
            new Marker("ruined_portals", "minecraft:netherrack", 4, false),
            // 沙漠神殿（要同时出现陶土，否则会被沙漠变体的废弃传送门误判）
            new Marker("desert_pyramids", "minecraft:orange_terracotta", 2, false),
            new Marker("desert_pyramids", "minecraft:chiseled_sandstone", 2, false),
            // 村庄（钟也算玩家会放的东西，低置信度）
            new Marker("villages", "minecraft:bell", 1, false),
            // 废弃矿井
            new Marker("mineshafts", "minecraft:rail", 40, false),
            new Marker("mineshafts", "minecraft:cobweb", 20, false)
    );

    public static void main(String[] args) throws Exception {
        if (args.length == 0) {
            System.out.println("用法: java RegionScan <存档目录或 region 目录> [--all]");
            return;
        }
        Path root = Path.of(args[0]);
        boolean includeLow = args.length > 1 && args[1].equals("--all");
        Path regionDir = Files.isDirectory(root.resolve("region")) ? root.resolve("region") : root;
        if (!Files.isDirectory(regionDir)) {
            System.out.println("找不到 region 目录: " + regionDir);
            return;
        }
        List<Path> files = new ArrayList<>();
        try (var stream = Files.list(regionDir)) {
            stream.filter(p -> p.getFileName().toString().matches("r\\.-?\\d+\\.-?\\d+\\.mca"))
                    .sorted()
                    .forEach(files::add);
        }
        System.out.printf("扫描 %s：%d 个区域文件%n", regionDir, files.size());

        // 区域文件之间互不相干，多线程并行解压
        Map<String, Set<Long>> flagged = new java.util.concurrent.ConcurrentHashMap<>();
        java.util.concurrent.atomic.LongAdder chunkCounter = new java.util.concurrent.atomic.LongAdder();
        java.util.concurrent.atomic.LongAdder byteCounter = new java.util.concurrent.atomic.LongAdder();
        long firstNs = System.nanoTime();
        files.parallelStream().forEach(file -> {
            try {
                long[] stat = scanRegion(file, flagged);
                chunkCounter.add(stat[0]);
                byteCounter.add(stat[1]);
            } catch (IOException ignored) {
                // 坏文件跳过
            }
        });
        long chunks = chunkCounter.sum();
        long bytes = byteCounter.sum();
        double seconds = (System.nanoTime() - firstNs) / 1e9;
        System.out.printf("解压 %d 个区块、%.1f MB，用时 %.1f 秒（%d 线程）%n",
                chunks, bytes / 1048576.0, seconds, Runtime.getRuntime().availableProcessors());
        if (chunks > 0) {
            long minArea = 0;
            long maxArea = 0;
            for (Path file : files) {
                String name = file.getFileName().toString();
                maxArea += 1024;
            }
            System.out.printf("已加载区块占这些区域文件的 %.0f%%（剩下的是没跑到的空区块）%n",
                    chunks * 100.0 / maxArea);
        }
        if (chunks == 0) {
            System.out.println("没解出任何区块 —— 下载器可能没写进 region 目录，或者存档是空的");
            return;
        }

        List<String> hints = new ArrayList<>();
        System.out.println();
        for (Marker marker : MARKERS) {
            Set<Long> cells = flagged.get(marker.set + "|" + marker.block);
            if (cells == null || cells.isEmpty()) {
                continue;
            }
            List<Cluster> clusters = cluster(cells);
            for (Cluster c : clusters) {
                if (c.chunks < marker.minChunks) {
                    continue;
                }
                boolean high = marker.highConfidence;
                System.out.printf("[%s] %-18s %-38s 区块 %d 个，中心 (%d,%d) 半径 %d%n",
                        high ? "高" : "低", marker.set, marker.block, c.chunks, c.centerX, c.centerZ, c.radius);
                if (high || includeLow) {
                    hints.add("struct:" + marker.set + ":" + c.centerX + "," + c.centerZ + "," + c.radius);
                }
            }
        }

        if (hints.isEmpty()) {
            System.out.println("\n没找到高置信度结构。可以在下载范围更大一点之后重扫，或者加 --all 看低置信度的。");
            return;
        }
        // 同一个结构集可能被多个方块命中，去重
        Path out = Path.of(System.getProperty("user.dir"), "struct-hints.txt");
        List<String> unique = new ArrayList<>(new LinkedHashSet<>(hints));
        if (Files.exists(out)) {   // 和之前几次下载扫出来的结果合起来，避免覆盖
            for (String line : Files.readAllLines(out)) {
                String trimmed = line.trim();
                if (!trimmed.isEmpty() && !unique.contains(trimmed)) {
                    unique.add(trimmed);
                }
            }
        }
        java.util.Collections.sort(unique);
        Files.write(out, unique);
        System.out.println("\n写好了 " + unique.size() + " 条结构提示 -> " + out);
        System.out.println("把这文件里的行贴进 seedhelper-observations.txt，或者直接喂给:");
        System.out.println("  java SeedCracker crack <v> \"$(paste -sd';' struct-hints.txt | sed 's/struct://g')\"");
    }

    /** 返回 [解出的区块数, 解压后的总字节数] */
    static long[] scanRegion(Path file, Map<String, Set<Long>> flagged) throws IOException {
        String name = file.getFileName().toString();
        String[] parts = name.substring(2, name.length() - 4).split("\\.");
        int regionX = Integer.parseInt(parts[0]);
        int regionZ = Integer.parseInt(parts[1]);

        byte[] data = Files.readAllBytes(file);
        long chunkCount = 0;
        long totalBytes = 0;
        for (int slot = 0; slot < 1024; slot++) {
            int headerOffset = slot * 4;
            int offset = ((data[headerOffset] & 0xFF) << 16) | ((data[headerOffset + 1] & 0xFF) << 8)
                    | (data[headerOffset + 2] & 0xFF);
            int sectors = data[headerOffset + 3] & 0xFF;
            if (offset == 0 || sectors == 0) {
                continue;
            }
            int pos = offset * 4096;
            if (pos + 5 > data.length) {
                continue;
            }
            // 区块记录：4 字节大端长度（含压缩类型字节）+ 1 字节压缩类型 + 数据
            int length = ((data[pos] & 0xFF) << 24) | ((data[pos + 1] & 0xFF) << 16)
                    | ((data[pos + 2] & 0xFF) << 8) | (data[pos + 3] & 0xFF);
            int compression = data[pos + 4] & 0xFF;
            int size = length - 1;
            if (size <= 0 || pos + 5 + size > data.length) {
                continue;
            }
            byte[] chunk;
            try {
                chunk = decompress(data, pos + 5, size, compression);
            } catch (Exception e) {
                continue;
            }
            chunkCount++;
            totalBytes += chunk.length;
            int chunkX = regionX * 32 + (slot % 32);
            int chunkZ = regionZ * 32 + (slot / 32);
            for (Marker marker : MARKERS) {
                if (contains(chunk, marker.block)) {
                    flagged.computeIfAbsent(marker.set + "|" + marker.block,
                                    k -> java.util.concurrent.ConcurrentHashMap.newKeySet())
                            .add(key(chunkX, chunkZ));
                }
            }
        }
        return new long[]{chunkCount, totalBytes};
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

    /** 在字节里找 ASCII 子串（区块数据里的方块 id 就是这么存的） */
    static boolean contains(byte[] data, String needle) {
        byte[] target = needle.getBytes(java.nio.charset.StandardCharsets.US_ASCII);
        outer:
        for (int i = 0; i + target.length <= data.length; i++) {
            for (int j = 0; j < target.length; j++) {
                if (data[i + j] != target[j]) {
                    continue outer;
                }
            }
            return true;
        }
        return false;
    }

    static long key(int x, int z) {
        return (((long) x) << 32) ^ (z & 0xFFFFFFFFL);
    }

    static int keyX(long key) {
        return (int) (key >> 32);
    }

    static int keyZ(long key) {
        return (int) key;
    }

    record Cluster(int centerX, int centerZ, int radius, int chunks) {
    }

    /** 简单的网格聚类：相距 <= 6 个区块的算同一处结构 */
    static List<Cluster> cluster(Set<Long> cells) {
        List<long[]> points = new ArrayList<>();
        for (long key : cells) {
            points.add(new long[]{keyX(key), keyZ(key)});
        }
        boolean[] used = new boolean[points.size()];
        List<Cluster> result = new ArrayList<>();
        for (int i = 0; i < points.size(); i++) {
            if (used[i]) {
                continue;
            }
            List<Integer> group = new ArrayList<>();
            group.add(i);
            used[i] = true;
            boolean changed = true;
            while (changed) {
                changed = false;
                for (int j = 0; j < points.size(); j++) {
                    if (used[j]) {
                        continue;
                    }
                    for (int k : group) {
                        if (Math.abs(points.get(j)[0] - points.get(k)[0]) <= 6
                                && Math.abs(points.get(j)[1] - points.get(k)[1]) <= 6) {
                            group.add(j);
                            used[j] = true;
                            changed = true;
                            break;
                        }
                    }
                }
            }
            int minX = Integer.MAX_VALUE;
            int maxX = Integer.MIN_VALUE;
            int minZ = Integer.MAX_VALUE;
            int maxZ = Integer.MIN_VALUE;
            for (int index : group) {
                minX = Math.min(minX, (int) points.get(index)[0]);
                maxX = Math.max(maxX, (int) points.get(index)[0]);
                minZ = Math.min(minZ, (int) points.get(index)[1]);
                maxZ = Math.max(maxZ, (int) points.get(index)[1]);
            }
            int centerX = (minX + maxX) / 2;
            int centerZ = (minZ + maxZ) / 2;
            int radius = Math.max(2, Math.max(maxX - minX, maxZ - minZ) / 2 + 1);
            result.add(new Cluster(centerX, centerZ, Math.min(radius, 6), group.size()));
        }
        return result;
    }
}
