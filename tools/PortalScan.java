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
 * 从下载的存档里找末地传送门：解析区块 NBT + 解开方块调色板，
 * 精确列出 12 个框架的坐标、哪些已经插了眼、传送门是否已点亮。
 *
 * 用法: java PortalScan <存档目录或 region 目录>
 */
public class PortalScan {
    public static void main(String[] args) throws Exception {
        if (args.length == 0) {
            System.out.println("用法: java PortalScan <存档目录或 region 目录>");
            return;
        }
        Path root = Path.of(args[0]);
        Path regionDir = Files.isDirectory(root.resolve("region")) ? root.resolve("region") : root;
        List<Path> files = new ArrayList<>();
        try (var stream = Files.list(regionDir)) {
            stream.filter(p -> p.getFileName().toString().matches("r\\.-?\\d+\\.-?\\d+\\.mca"))
                    .sorted().forEach(files::add);
        }
        System.out.printf("扫描 %s：%d 个区域文件%n", regionDir, files.size());

        List<long[]> frames = new ArrayList<>();   // x, y, z
        List<Boolean> eyes = new ArrayList<>();
        List<long[]> portalBlocks = new ArrayList<>();
        int chunksWithFrames = 0;

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
                if (offset == 0) {
                    continue;
                }
                int pos = offset * 4096;
                if (pos + 5 > region.length) {
                    continue;
                }
                int length = ((region[pos] & 0xFF) << 24) | ((region[pos + 1] & 0xFF) << 16)
                        | ((region[pos + 2] & 0xFF) << 8) | (region[pos + 3] & 0xFF);
                int compression = region[pos + 4] & 0xFF;
                int size = length - 1;
                if (size <= 0 || pos + 5 + size > region.length) {
                    continue;
                }
                byte[] chunk;
                try {
                    chunk = decompress(region, pos + 5, size, compression);
                } catch (Exception e) {
                    continue;
                }
                if (!contains(chunk, "end_portal_frame")) {
                    continue;
                }
                int chunkX = regionX * 32 + (slot % 32);
                int chunkZ = regionZ * 32 + (slot / 32);
                if (parseChunk(chunk, chunkX, chunkZ, frames, eyes, portalBlocks)) {
                    chunksWithFrames++;
                }
            }
        }

        if (frames.isEmpty() && portalBlocks.isEmpty()) {
            System.out.println("没找到末地传送门框架。可能是下载范围没覆盖到传送门房间（周围 8 区块内飞一圈再下一次）。");
            return;
        }

        int eyeCount = 0;
        for (boolean eye : eyes) {
            if (eye) {
                eyeCount++;
            }
        }
        System.out.printf("%n找到 %d 个末地传送门框架（分布在 %d 个区块），其中已插眼 %d 个%n",
                frames.size(), chunksWithFrames, eyeCount);
        if (!portalBlocks.isEmpty()) {
            System.out.println("检测到 minecraft:end_portal 方块 → **这个传送门已经被点亮了**，直接进去就行！");
        } else {
            System.out.printf("传送门还没点亮 → 还差 %d 个末影眼%n", Math.max(12 - eyeCount, 0));
        }

        System.out.println("\n框架坐标（方块坐标 x y z，带*的是已经插了眼的）：");
        List<String> lines = new ArrayList<>();
        for (int i = 0; i < frames.size(); i++) {
            long[] f = frames.get(i);
            String line = String.format("  %s %d %d %d", eyes.get(i) ? "*" : " ", f[0], f[1], f[2]);
            System.out.println(line);
            lines.add(String.format("portal_frame:%d,%d,%d eye=%s", f[0], f[1], f[2], eyes.get(i)));
        }
        if (!portalBlocks.isEmpty()) {
            long[] p = portalBlocks.get(0);
            System.out.printf("%n传送门方块位置（门中心）：%d %d %d%n", p[0], p[1], p[2]);
        }
        Path out = Path.of("portal-info.txt");
        Files.write(out, lines);
        System.out.println("\n明细也写到 " + out.toAbsolutePath());
    }

    /** 返回这个区块里是否真的有框架 */
    static boolean parseChunk(byte[] chunk, int chunkX, int chunkZ,
                              List<long[]> frames, List<Boolean> eyes, List<long[]> portalBlocks) {
        try {
            int[] cursor = {0};
            Object rootObj = Nbt.read(chunk, cursor);
            if (!(rootObj instanceof Map<?, ?> root)) {
                return false;
            }
            Object sectionsObj = root.get("sections");
            if (!(sectionsObj instanceof List<?> sections)) {
                return false;
            }
            boolean found = false;
            for (Object sectionObj : sections) {
                if (!(sectionObj instanceof Map<?, ?> section)) {
                    continue;
                }
                int sectionY = ((Number) section.get("Y")).intValue();
                Object blockStatesObj = section.get("block_states");
                if (!(blockStatesObj instanceof Map<?, ?> blockStates)) {
                    continue;
                }
                Object paletteObj = blockStates.get("palette");
                if (!(paletteObj instanceof List<?> palette)) {
                    continue;
                }
                long[] data = (long[]) blockStates.get("data");
                int bits = Math.max(4, 32 - Integer.numberOfLeadingZeros(Math.max(1, palette.size() - 1)));
                if (((1 << bits) - 1) < palette.size() - 1) {
                    bits++;
                }
                int perLong = 64 / bits;
                long mask = (1L << bits) - 1;
                for (int y = 0; y < 16; y++) {
                    for (int z = 0; z < 16; z++) {
                        for (int x = 0; x < 16; x++) {
                            int index = (y << 8) | (z << 4) | x;
                            int paletteIndex;
                            if (data == null || data.length == 0) {
                                paletteIndex = 0;
                            } else {
                                int longIndex = index / perLong;
                                int shift = (index % perLong) * bits;
                                if (longIndex >= data.length) {
                                    continue;
                                }
                                paletteIndex = (int) ((data[longIndex] >>> shift) & mask);
                            }
                            if (paletteIndex >= palette.size()) {
                                continue;
                            }
                            Object entryObj = palette.get(paletteIndex);
                            if (!(entryObj instanceof Map<?, ?> entry)) {
                                continue;
                            }
                            Object nameObj = entry.get("Name");
                            if (!(nameObj instanceof String name)) {
                                continue;
                            }
                            int wx = chunkX * 16 + x;
                            int wy = sectionY * 16 + y;
                            int wz = chunkZ * 16 + z;
                            if (name.equals("minecraft:end_portal_frame")) {
                                boolean eye = false;
                                if (entry.get("Properties") instanceof Map<?, ?> props) {
                                    Object e = props.get("eye");
                                    eye = e != null && e.toString().equals("true");
                                }
                                frames.add(new long[]{wx, wy, wz});
                                eyes.add(eye);
                                found = true;
                            } else if (name.equals("minecraft:end_portal")) {
                                portalBlocks.add(new long[]{wx, wy, wz});
                            }
                        }
                    }
                }
            }
            return found;
        } catch (Throwable t) {
            return false;
        }
    }

    /** 极简 NBT 读取（够用就行） */
    static final class Nbt {
        static Object read(byte[] d, int[] p) {
            int type = d[p[0]++] & 0xFF;
            if (type == 0) {
                return null;
            }
            readString(d, p);   // 名字
            return readPayload(d, p, type);
        }

        static Object readPayload(byte[] d, int[] p, int type) {
            switch (type) {
                case 1: return d[p[0]++];
                case 2: { short v = (short) (((d[p[0]] & 0xFF) << 8) | (d[p[0] + 1] & 0xFF)); p[0] += 2; return v; }
                case 3: { int v = readInt(d, p); return v; }
                case 4: {
                    long v = 0;
                    for (int i = 0; i < 8; i++) v = (v << 8) | (d[p[0] + i] & 0xFF);
                    p[0] += 8;
                    return v;
                }
                case 5: { int v = readInt(d, p); return Float.intBitsToFloat(v); }
                case 6: {
                    long v = 0;
                    for (int i = 0; i < 8; i++) v = (v << 8) | (d[p[0] + i] & 0xFF);
                    p[0] += 8;
                    return Double.longBitsToDouble(v);
                }
                case 7: { int n = readInt(d, p); byte[] v = new byte[n]; System.arraycopy(d, p[0], v, 0, n); p[0] += n; return v; }
                case 8: return readString(d, p);
                case 9: {
                    int elemType = d[p[0]++] & 0xFF;
                    int n = readInt(d, p);
                    List<Object> list = new ArrayList<>(n);
                    for (int i = 0; i < n; i++) list.add(readPayload(d, p, elemType));
                    return list;
                }
                case 10: {
                    Map<String, Object> map = new java.util.HashMap<>();
                    while (true) {
                        int t = d[p[0]++] & 0xFF;
                        if (t == 0) break;
                        String key = readString(d, p);
                        map.put(key, readPayload(d, p, t));
                    }
                    return map;
                }
                case 11: {
                    int n = readInt(d, p);
                    int[] v = new int[n];
                    for (int i = 0; i < n; i++) v[i] = readInt(d, p);
                    return v;
                }
                case 12: {
                    int n = readInt(d, p);
                    long[] v = new long[n];
                    for (int i = 0; i < n; i++) {
                        long l = 0;
                        for (int j = 0; j < 8; j++) l = (l << 8) | (d[p[0] + j] & 0xFF);
                        p[0] += 8;
                        v[i] = l;
                    }
                    return v;
                }
                default:
                    throw new IllegalStateException("未知 NBT 类型 " + type);
            }
        }

        static int readInt(byte[] d, int[] p) {
            int v = ((d[p[0]] & 0xFF) << 24) | ((d[p[0] + 1] & 0xFF) << 16)
                    | ((d[p[0] + 2] & 0xFF) << 8) | (d[p[0] + 3] & 0xFF);
            p[0] += 4;
            return v;
        }

        static String readString(byte[] d, int[] p) {
            int n = ((d[p[0]] & 0xFF) << 8) | (d[p[0] + 1] & 0xFF);
            p[0] += 2;
            String s = new String(d, p[0], n, java.nio.charset.StandardCharsets.UTF_8);
            p[0] += n;
            return s;
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
                if (data[i + j] != target[j]) {
                    continue outer;
                }
            }
            return true;
        }
        return false;
    }
}
