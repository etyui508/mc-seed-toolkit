import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.zip.DeflaterOutputStream;

/**
 * 合成一个区域文件（里面塞一圈海晶石当海底神殿），验证扫描 + 聚类能定位到中心。
 * 真实存档的读取能力由 tools/RegionScan.java 在真实存档上人工验证过。
 */
public class RegionScanSelfTest {
    public static void main(String[] args) throws Exception {
        int regionX = 3;
        int regionZ = -2;
        int centerChunkX = 110;
        int centerChunkZ = -50;

        Path dir = Files.createTempDirectory("regionscan-test");
        Path regionDir = dir.resolve("region");
        Files.createDirectories(regionDir);
        Path file = regionDir.resolve("r." + regionX + "." + regionZ + ".mca");

        byte[] region = new byte[4096 * 40];
        int nextSector = 2;
        int written = 0;
        for (int dx = -2; dx <= 2; dx++) {
            for (int dz = -2; dz <= 2; dz++) {
                int cx = centerChunkX + dx;
                int cz = centerChunkZ + dz;
                int slot = Math.floorMod(cx, 32) + Math.floorMod(cz, 32) * 32;
                byte[] chunk = fakeChunk(cx, cz, "minecraft:prismarine");
                byte[] packed = packRecord(chunk);
                int offset = nextSector;
                int sectors = (packed.length + 4095) / 4096;
                System.arraycopy(packed, 0, region, offset * 4096, packed.length);
                region[slot * 4] = (byte) (offset >> 16);
                region[slot * 4 + 1] = (byte) (offset >> 8);
                region[slot * 4 + 2] = (byte) offset;
                region[slot * 4 + 3] = (byte) sectors;
                nextSector += sectors;
                written++;
            }
        }
        Files.write(file, region);
        System.out.printf("合成区域文件：%d 个区块，中心区块 (%d,%d)%n", written, centerChunkX, centerChunkZ);

        Map<String, Set<Long>> flagged = new LinkedHashMap<>();
        long[] stat = RegionScan.scanRegion(file, flagged);
        System.out.printf("扫描解出 %d 个区块，命中标记的集合数 %d%n", stat[0], flagged.size());

        Set<Long> hits = flagged.get("ocean_monuments|minecraft:prismarine");
        if (hits == null || hits.isEmpty()) {
            System.out.println("FAIL: 没检测到海晶石");
            return;
        }
        List<RegionScan.Cluster> clusters = RegionScan.cluster(hits);
        if (clusters.size() != 1) {
            System.out.println("FAIL: 聚类数量不对 " + clusters.size());
            return;
        }
        RegionScan.Cluster cluster = clusters.get(0);
        boolean ok = Math.abs(cluster.centerX() - centerChunkX) <= 1
                && Math.abs(cluster.centerZ() - centerChunkZ) <= 1
                && cluster.chunks() == written;
        System.out.printf("检测到海底神殿：中心 (%d,%d) 半径 %d，区块数 %d -> %s%n",
                cluster.centerX(), cluster.centerZ(), cluster.radius(), cluster.chunks(),
                ok ? "OK ✅" : "FAIL ❌");
    }

    /** 造一个形状像样的区块 NBT（扫描器只看里面的方块 id 字符串） */
    static byte[] fakeChunk(int cx, int cz, String block) {
        StringBuilder sb = new StringBuilder();
        sb.append("xPos").append((char) cx).append(cx);
        sb.append("zPos").append(cz);
        sb.append("sections");
        sb.append(block);
        return sb.toString().getBytes(StandardCharsets.UTF_8);
    }

    /** [4 字节长度][1 字节压缩类型=2][zlib 数据] */
    static byte[] packRecord(byte[] chunk) throws Exception {
        ByteArrayOutputStream compressed = new ByteArrayOutputStream();
        try (DeflaterOutputStream deflater = new DeflaterOutputStream(compressed)) {
            deflater.write(chunk);
        }
        byte[] payload = compressed.toByteArray();
        int length = payload.length + 1;
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        out.write((length >>> 24) & 0xFF);
        out.write((length >>> 16) & 0xFF);
        out.write((length >>> 8) & 0xFF);
        out.write(length & 0xFF);
        out.write(2);
        out.write(payload);
        return out.toByteArray();
    }
}
