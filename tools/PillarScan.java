import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.zip.GZIPInputStream;
import java.util.zip.InflaterInputStream;

/**
 * 只靠下载的存档解末地柱子 -> 反查出那 16 位 v。
 * （柱子顶面 = 76 + 3h，h 是 0..9 的某个排列；排列只由 Random(seed).nextLong()&0xFFFF 决定）
 *
 * 用法: java PillarScan <存档目录>
 */
public class PillarScan {
    static final int[] PX = {42, 33, 12, -13, -34, -42, -34, -13, 12, 33};
    static final int[] PZ = {0, 24, 39, 39, 24, -1, -25, -40, -40, -25};
    static final long MULT = 0x5DEECE66DL;
    static final long ADD = 0xBL;
    static final long MASK = (1L << 48) - 1;

    public static void main(String[] args) throws Exception {
        if (args.length == 0) {
            System.out.println("用法: java PillarScan <存档目录>");
            return;
        }
        Path root = Path.of(args[0]);
        Path regionDir = Files.isDirectory(root.resolve("region")) ? root.resolve("region") : root;
        List<Path> files = new ArrayList<>();
        try (var stream = Files.list(regionDir)) {
            stream.filter(p -> p.getFileName().toString().matches("r\\.-?\\d+\\.-?\\d+\\.mca"))
                    .sorted().forEach(files::add);
        }
        int[] tops = new int[PX.length];
        java.util.Arrays.fill(tops, Integer.MIN_VALUE);

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
                if (!contains(chunk, "minecraft:obsidian") && !contains(chunk, "minecraft:bedrock")) {
                    continue;
                }
                int chunkX = regionX * 32 + (slot % 32);
                int chunkZ = regionZ * 32 + (slot / 32);
                scanChunk(chunk, chunkX, chunkZ, tops);
            }
        }

        int found = 0;
        int[] heights = new int[PX.length];
        for (int i = 0; i < PX.length; i++) {
            if (tops[i] == Integer.MIN_VALUE) continue;
            found++;
            int d = tops[i] - 76;
            heights[i] = (d >= 0 && d % 3 == 0) ? d / 3 : -1;
        }
        System.out.printf("末地柱子里解出 %d/10 根%n", found);
        if (found < 10) {
            System.out.println("柱子没下全（下载范围要覆盖 x/z ±60 以内、y 60~110 的那一圈）");
            for (int i = 0; i < PX.length; i++) {
                System.out.printf("  柱%d (%d,%d): %s%n", i, PX[i], PZ[i],
                        tops[i] == Integer.MIN_VALUE ? "没下到" : "顶面 y=" + tops[i]);
            }
            return;
        }
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < PX.length; i++) {
            sb.append(tops[i]).append(i < PX.length - 1 ? "," : "");
            if (heights[i] < 0 || heights[i] > 9) {
                System.out.println("柱子高度不符合原版规律（76+3h），服务器可能改过世界生成");
                return;
            }
        }
        int value = matchValue(heights);
        System.out.println("end_pillars tops=" + sb + " v=" + value);
        if (value < 0) {
            System.out.println("(这 10 个高度组合在 65536 种布局里找不到，说明不是原版末地)");
        } else {
            System.out.println("=> 这 16 bit: v=" + value);
        }
    }

    static void scanChunk(byte[] chunk, int chunkX, int chunkZ, int[] tops) {
        try {
            int[] cursor = {0};
            Object rootObj = PortalScan.Nbt.read(chunk, cursor);
            if (!(rootObj instanceof Map<?, ?> root)) return;
            if (!(root.get("sections") instanceof List<?> sections)) return;
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
                            if (!(entry.get("Name") instanceof String name)) continue;
                            if (!name.equals("minecraft:obsidian") && !name.equals("minecraft:bedrock")) continue;
                            int wx = chunkX * 16 + x;
                            int wy = sectionY * 16 + y;
                            int wz = chunkZ * 16 + z;
                            for (int i = 0; i < PX.length; i++) {
                                if (PX[i] == wx && PZ[i] == wz && wy > tops[i]) {
                                    tops[i] = wy;
                                }
                            }
                        }
                    }
                }
            }
        } catch (Throwable ignored) {
            // 坏区块跳过
        }
    }

    static int matchValue(int[] heights) {
        int[] a = new int[10];
        for (int v = 0; v < 65536; v++) {
            for (int i = 0; i < 10; i++) a[i] = i;
            long state = (v ^ MULT) & MASK;
            for (int i = 10; i > 1; i--) {
                state = (state * MULT + ADD) & MASK;
                int r = (int) (state >>> 17);
                int m = i - 1;
                int bound;
                if ((i & m) == 0) {
                    bound = (int) (((long) i * r) >> 31);
                } else {
                    int u = r;
                    int res = u % i;
                    while (u - res + m < 0) {
                        state = (state * MULT + ADD) & MASK;
                        u = (int) (state >>> 17);
                        res = u % i;
                    }
                    bound = res;
                }
                int tmp = a[bound];
                a[bound] = a[i - 1];
                a[i - 1] = tmp;
            }
            boolean ok = true;
            for (int i = 0; i < 10 && ok; i++) ok = a[i] == heights[i];
            if (ok) return v;
        }
        return -1;
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
        byte[] target = needle.getBytes(java.nio.charset.StandardCharsets.US_ASCII);
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
