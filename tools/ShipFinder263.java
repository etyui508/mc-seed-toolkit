// 末地船预测器 —— 26.3 版（官方名字，直接对着 26.3 客户端编译）
//
// 26.x 开始 Mojang 发的是**未混淆**的 jar，所以这个版本不用 Fabric intermediary，
// 直接写 net.minecraft.* 的官方类名就能编译、运行。
// 逻辑跟 tools/ShipFinder.java（1.21.10 版）完全一样：
//   1) WorldgenRandom.setLargeFeatureSeed(种子, 城市区块x, 城市区块z)
//   2) Rotation.getRandom(rand) 抽朝向
//   3) EndCityPieces.startHouseTower(...) 跑完整座城（船在桥里按 1/(10-深度) 掷）
//   4) 把 "ship" 那段的包围盒 / 龙头 / 鞘翅 / 宝箱位置打出来
//
// 编译：javac -cp <26.3 客户端 jar>:<依赖库> -d out/26.3 tools/ShipFinder263.java
//   （注意这个文件里的类故意不写 public，编出来还是 ShipFinder.class，跟 1.21.10 版并存于不同目录）
import java.lang.reflect.Field;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Vec3i;
import net.minecraft.resources.Identifier;
import net.minecraft.world.level.block.Rotation;
import net.minecraft.world.level.levelgen.LegacyRandomSource;
import net.minecraft.world.level.levelgen.WorldgenRandom;
import net.minecraft.world.level.levelgen.structure.BoundingBox;
import net.minecraft.world.level.levelgen.structure.StructurePiece;
import net.minecraft.world.level.levelgen.structure.TemplateStructurePiece;
import net.minecraft.world.level.levelgen.structure.structures.EndCityPieces;
import net.minecraft.world.level.levelgen.structure.templatesystem.StructurePlaceSettings;
import net.minecraft.world.level.levelgen.structure.templatesystem.StructureTemplate;
import net.minecraft.world.level.levelgen.structure.templatesystem.StructureTemplateManager;
import sun.misc.Unsafe;

class ShipFinder {
    static final Map<String, StructureTemplate> TPL = new HashMap<>();
    static Field F_SIZE, F_NAME, F_TPOS, F_PLACE;

    static class Mgr extends StructureTemplateManager {
        @SuppressWarnings("unchecked")
        Mgr() {
            super((net.minecraft.server.packs.resources.ResourceManager) null,
                  (net.minecraft.world.level.storage.LevelStorageSource.LevelStorageAccess) null,
                  (com.mojang.datafixers.DataFixer) null,
                  (net.minecraft.core.HolderGetter<net.minecraft.world.level.block.Block>) null);
        }

        @Override
        public StructureTemplate getOrCreate(Identifier id) {
            String path = id.getPath();
            String name = path.substring(path.lastIndexOf('/') + 1);
            StructureTemplate t = TPL.get(name);
            if (t == null) {
                System.err.println("!! 没有模板 " + path);
                t = TPL.values().iterator().next();
            }
            return t;
        }
    }

    static Unsafe unsafe() throws Exception {
        Field f = Unsafe.class.getDeclaredField("theUnsafe");
        f.setAccessible(true);
        return (Unsafe) f.get(null);
    }

    /** 模板里的本地坐标 -> 世界坐标（mirror=NONE、pivot=0，跟游戏 StructureTemplate.transform 一致） */
    static int[] localToWorld(Rotation rot, int[] tpl, int lx, int ly, int lz) {
        int x, z;
        switch (rot) {
            case CLOCKWISE_90: x = -lz; z = lx; break;
            case CLOCKWISE_180: x = -lx; z = -lz; break;
            case COUNTERCLOCKWISE_90: x = lz; z = -lx; break;
            default: x = lx; z = lz; break;
        }
        return new int[]{tpl[0] + x, tpl[1] + ly, tpl[2] + z};
    }

    public static void main(String[] args) throws Exception {
        if (args.length < 3) {
            System.out.println("用法: ShipFinder <世界种子> <尺寸文件> <区块x,区块z> ...  或 @文件");
            return;
        }
        long seed = Long.parseLong(args[0]);
        net.minecraft.SharedConstants.tryDetectVersion();
        net.minecraft.server.Bootstrap.bootStrap();

        F_SIZE = StructureTemplate.class.getDeclaredField("size");
        F_SIZE.setAccessible(true);
        F_NAME = TemplateStructurePiece.class.getDeclaredField("templateName");
        F_TPOS = TemplateStructurePiece.class.getDeclaredField("templatePosition");
        F_PLACE = TemplateStructurePiece.class.getDeclaredField("placeSettings");
        for (Field f : new Field[]{F_NAME, F_TPOS, F_PLACE}) f.setAccessible(true);

        for (String line : java.nio.file.Files.readAllLines(java.nio.file.Paths.get(args[1]))) {
            line = line.trim();
            if (line.isEmpty() || line.startsWith("#")) continue;
            String[] a = line.split("\\s+");
            StructureTemplate tpl = new StructureTemplate();
            F_SIZE.set(tpl, new Vec3i(Integer.parseInt(a[1]), Integer.parseInt(a[2]), Integer.parseInt(a[3])));
            TPL.put(a[0], tpl);
        }
        Mgr mgr = (Mgr) unsafe().allocateInstance(Mgr.class);

        List<int[]> cities = new ArrayList<>();
        for (int i = 2; i < args.length; i++) {
            if (args[i].startsWith("@")) {
                for (String line : java.nio.file.Files.readAllLines(
                        java.nio.file.Paths.get(args[i].substring(1)))) {
                    line = line.trim();
                    if (line.isEmpty() || line.startsWith("#")) continue;
                    String[] a = line.replace(",", " ").split("\\s+");
                    if (a.length >= 2) cities.add(new int[]{Integer.parseInt(a[0]), Integer.parseInt(a[1])});
                }
            } else {
                String[] a = args[i].replace(",", " ").split("\\s+");
                if (a.length >= 2) cities.add(new int[]{Integer.parseInt(a[0]), Integer.parseInt(a[1])});
            }
        }

        for (int[] city : cities) {
            int cx = city[0], cz = city[1];
            WorldgenRandom rng = new WorldgenRandom(new LegacyRandomSource(0L));
            rng.setLargeFeatureSeed(seed, cx, cz);
            Rotation rot = Rotation.getRandom(rng);
            BlockPos pos = new BlockPos(cx * 16 + 7, 64, cz * 16 + 7);
            List<StructurePiece> pieces = new ArrayList<>();
            EndCityPieces.startHouseTower(mgr, pos, rot, pieces, rng);

            String ship = null;
            int sx1 = 0, sy1 = 0, sz1 = 0, sx2 = 0, sy2 = 0, sz2 = 0;
            int[] tpl = null;
            Rotation shipRot = null;
            for (StructurePiece p : pieces) {
                if (!(p instanceof TemplateStructurePiece)) continue;
                TemplateStructurePiece tp = (TemplateStructurePiece) p;
                if (!"ship".equals(F_NAME.get(tp))) continue;
                BoundingBox b = p.getBoundingBox();
                sx1 = b.minX(); sy1 = b.minY(); sz1 = b.minZ();
                sx2 = b.maxX(); sy2 = b.maxY(); sz2 = b.maxZ();
                BlockPos tpos = (BlockPos) F_TPOS.get(tp);
                tpl = new int[]{tpos.getX(), tpos.getY(), tpos.getZ()};
                shipRot = ((StructurePlaceSettings) F_PLACE.get(tp)).getRotation();
                ship = (String) F_NAME.get(tp);
            }
            if (ship == null) {
                System.out.printf("CITY %d %d NONE %d%n", cx, cz, pieces.size());
            } else {
                int gx = (sx1 + sx2) / 2, gz = (sz1 + sz2) / 2;
                int[] head = localToWorld(shipRot, tpl, 6, 8, 0);
                int[] ely = localToWorld(shipRot, tpl, 6, 5, 7);
                int[] c1 = localToWorld(shipRot, tpl, 5, 5, 7);
                int[] c2 = localToWorld(shipRot, tpl, 7, 5, 7);
                c1[1] -= 1;
                c2[1] -= 1;
                System.out.printf(
                    "CITY %d %d SHIP rot=%s box=%d,%d,%d..%d,%d,%d goto=%d,%d,%d head=%d,%d,%d elytra=%d,%d,%d chest=%d,%d,%d chest=%d,%d,%d pieces=%d%n",
                    cx, cz, shipRot, sx1, sy1, sz1, sx2, sy2, sz2, gx, sy1, gz,
                    head[0], head[1], head[2], ely[0], ely[1], ely[2],
                    c1[0], c1[1], c1[2], c2[0], c2[1], c2[2], pieces.size());
            }
        }
    }
}
