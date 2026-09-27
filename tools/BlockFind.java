import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.zip.GZIPInputStream;
import java.util.zip.InflaterInputStream;

/**
 * 在下载的存档里精确找方块（解析区块 NBT + 解开方块调色板到每个坐标）。
 *
 * 用法: java BlockFind <存档目录> <方块id> [方块id...]
 *   例: java BlockFind saves/xxx minecraft:dragon_head            # 末地船（有龙首 = 有船 = 有鞘翅）
 *       java BlockFind saves/xxx minecraft:end_portal_frame minecraft:end_portal
 *       java BlockFind saves/xxx minecraft:spawner                # 刷怪笼
 */
public class BlockFind {
    public static void main(String[] args) throws Exception {
        if (args.length < 2) {
            System.out.println("用法: java BlockFind <存档目录> <方块id> [方块id...]");
            return;
        }
        Path root = Path.of(args[0]);
        Path regionDir = Files.isDirectory(root.resolve("region")) ? root.resolve("region") : root;
        List<String> targets = new ArrayList<>();
        for (int i = 1; i < args.length; i++) {
            targets.add(args[i]);
        }

        Map<String, List<long[]>> found = new HashMap<>();
        for (String t : targets) {
            found.put(t, new ArrayList<>());
        }

        List<Path> files = new ArrayList<>();
        try (var stream = Files.list(regionDir)) {
            stream.filter(p -> p.getFileName().toString().matches("r\\.-?\\d+\\.-?\\d+\\.mca"))
                    .sorted().forEach(files::add);
        }
        System.out.printf("扫描 %s：%d 个区域文件%n", regionDir, files.size());

        byte[] needle0 = targets.get(0).getBytes(java.nio.charset.StandardCharsets.US_ASCII);
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
                if (!contains(chunk, new String(needle0, java.nio.charset.StandardCharsets.US_ASCII))) {
                    // 便宜筛选：这个区块里连第一个目标都没有就跳过
                    boolean any = false;
                    for (String t : targets) {
                        if (contains(chunk, t)) {
                            any = true;
                            break;
                        }
                    }
                    if (!any) continue;
                }
                int chunkX = regionX * 32 + (slot % 32);
                int chunkZ = regionZ * 32 + (slot / 32);
                decodeChunk(chunk, chunkX, chunkZ, found);
            }
        }

        for (String t : targets) {
            List<long[]> list = found.get(t);
            if (list.isEmpty()) {
                System.out.printf("%n%s：没找到%n", t);
                continue;
            }
            long sx = 0, sy = 0, sz = 0;
            for (long[] p : list) {
                sx += p[0];
                sy += p[1];
                sz += p[2];
            }
            System.out.printf("%n%s：找到 %d 个，中心大约 (%d, %d, %d)%n",
                    t, list.size(), sx / list.size(), sy / list.size(), sz / list.size());
            int shown = 0;
            for (long[] p : list) {
                if (shown++ >= 12) {
                    System.out.printf("  …还有 %d 个%n", list.size() - 12);
                    break;
                }
                System.out.printf("  %d %d %d%n", p[0], p[1], p[2]);
            }
        }
    }

    static void decodeChunk(byte[] chunk, int chunkX, int chunkZ, Map<String, List<long[]>> found) {
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
                            List<long[]> list = found.get(name);
                            if (list != null) {
                                list.add(new long[]{chunkX * 16 + x, sectionY * 16 + y, chunkZ * 16 + z});
                            }
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
