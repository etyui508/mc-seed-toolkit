// 末地船预测器 —— 直接调用游戏本体的末地城生成器（class_3342 = EndCityPieces）
//
// 为什么能 100% 准：这里不是"我总结的规律"，而是把游戏自己的生成代码跑一遍。
//   1) 用 WorldgenRandom.setLargeFeatureSeed(世界种子, 城市所在区块x, 区块z) 建随机数
//   2) Rotation.getRandom(rand) 先抽一个朝向（消耗 1 次 nextInt(4)）
//   3) EndCityPieces.startHouseTower(...) 跑完整个城市布局（船在桥里按 1/(10-depth) 概率掷）
//   4) 把生成出来的 "ship" 那一段的包围盒打出来 —— 那就是船在世界的坐标
//
// 模板尺寸从游戏本体的 data/minecraft/structure/end_city/*.nbt 读（只用到 size），
// 用 /tools/dump-endcity-sizes.py 导出的 sizes 文本喂进来。
//
// 编译/运行见 tools/run-shipfinder.sh
import java.lang.reflect.Field;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import net.minecraft.class_2338;
import net.minecraft.class_2382;
import net.minecraft.class_2470;
import net.minecraft.class_2919;
import net.minecraft.class_2960;
import net.minecraft.class_3341;
import net.minecraft.class_3342;
import net.minecraft.class_3443;
import net.minecraft.class_3470;
import net.minecraft.class_3485;
import net.minecraft.class_3499;
import net.minecraft.class_5820;
import sun.misc.Unsafe;

public class ShipFinder {
    static final Map<String, class_3499> TPL = new HashMap<>();
    static Field F_SIZE, F_NAME, F_MINX, F_MINY, F_MINZ, F_MAXX, F_MAXY, F_MAXZ;
    static Field F_TPL_POS, F_PLACEMENT;

    /** 模板里的本地坐标 -> 世界坐标（mirror=NONE、pivot=0，跟游戏 StructureTemplate.transform 一致） */
    static int[] localToWorld(class_2470 rot, int[] tpl, int lx, int ly, int lz) {
        int x, z;
        switch (rot) {
            case field_11463: x = -lz; z = lx; break;          // clockwise_90
            case field_11464: x = -lx; z = -lz; break;         // 180
            case field_11465: x = lz; z = -lx; break;          // counterclockwise_90
            default:          x = lx; z = lz; break;           // none
        }
        return new int[]{tpl[0] + x, tpl[1] + ly, tpl[2] + z};
    }

    /** 假的模板管理器：游戏问我要模板，我就给一个"只有尺寸"的空模板 */
    static class Mgr extends class_3485 {
        // 这个构造永远不会被调用（下面用 Unsafe.allocateInstance 直接分配对象），
        // 写出来只是为了让 javac 通过 —— 真正的构造要资源管理器，我们不需要。
        @SuppressWarnings("unchecked")
        Mgr() {
            super((net.minecraft.class_3300) null, (net.minecraft.class_32.class_5143) null,
                  (com.mojang.datafixers.DataFixer) null, (net.minecraft.class_7871<net.minecraft.class_2248>) null);
        }

        @Override
        public class_3499 method_15091(class_2960 id) {
            String path = id.method_12832();
            String name = path.substring(path.lastIndexOf('/') + 1);
            class_3499 t = TPL.get(name);
            if (t == null) {
                System.out.println("!! 没有模板 " + path);
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

    public static void main(String[] args) throws Exception {
        if (args.length < 3) {
            System.out.println("用法: ShipFinder <世界种子> <尺寸文件> <区块x,区块z> [区块x,区块z ...]");
            return;
        }
        long seed = Long.parseLong(args[0]);

        // 先让游戏自己把注册表初始化好（跟游戏启动时做的一样），
        // 不然后面碰到方块/物品注册表会直接 "Not bootstrapped"
        net.minecraft.class_155.method_36208();   // SharedConstants.tryDetectVersion()：读包里的 version.json
        net.minecraft.class_2966.method_12851();

        F_SIZE = class_3499.class.getDeclaredField("field_15587"); F_SIZE.setAccessible(true);
        F_NAME = class_3470.class.getDeclaredField("field_31664"); F_NAME.setAccessible(true);
        F_TPL_POS = class_3470.class.getDeclaredField("field_15432"); F_TPL_POS.setAccessible(true);
        F_PLACEMENT = class_3470.class.getDeclaredField("field_15434"); F_PLACEMENT.setAccessible(true);
        F_MINX = class_3341.class.getDeclaredField("field_14380");
        F_MINY = class_3341.class.getDeclaredField("field_14379");
        F_MINZ = class_3341.class.getDeclaredField("field_14378");
        F_MAXX = class_3341.class.getDeclaredField("field_14377");
        F_MAXY = class_3341.class.getDeclaredField("field_14376");
        F_MAXZ = class_3341.class.getDeclaredField("field_14381");
        for (Field f : new Field[]{F_MINX, F_MINY, F_MINZ, F_MAXX, F_MAXY, F_MAXZ}) {
            f.setAccessible(true);
        }

        // 读模板尺寸：每行 "名字 sx sy sz"
        for (String line : java.nio.file.Files.readAllLines(java.nio.file.Paths.get(args[1]))) {
            line = line.trim();
            if (line.isEmpty() || line.startsWith("#")) continue;
            String[] a = line.split("\\s+");
            class_3499 tpl = new class_3499();
            F_SIZE.set(tpl, new class_2382(Integer.parseInt(a[1]), Integer.parseInt(a[2]), Integer.parseInt(a[3])));
            TPL.put(a[0], tpl);
        }

        Mgr mgr = (Mgr) unsafe().allocateInstance(Mgr.class);   // 跳过构造（那个构造要资源管理器）

        // 城市列表：命令行直接给 "区块x,区块z"，或者用 @文件名（每行 "x z" 或 "x,z"）
        java.util.List<int[]> cities = new ArrayList<>();
        for (int i = 2; i < args.length; i++) {
            if (args[i].startsWith("@")) {
                for (String line : java.nio.file.Files.readAllLines(
                        java.nio.file.Paths.get(args[i].substring(1)))) {
                    line = line.trim();
                    if (line.isEmpty() || line.startsWith("#")) continue;
                    String[] a = line.replace(",", " ").split("\\s+");
                    if (a.length >= 2) {
                        cities.add(new int[]{Integer.parseInt(a[0]), Integer.parseInt(a[1])});
                    }
                }
            } else {
                String[] a = args[i].replace(",", " ").split("\\s+");
                if (a.length >= 2) {
                    cities.add(new int[]{Integer.parseInt(a[0]), Integer.parseInt(a[1])});
                }
            }
        }

        for (int[] city : cities) {
            int cx = city[0];
            int czz = city[1];
            // ① 游戏怎么建这个随机数：GenerationContext -> WorldgenRandom + setLargeFeatureSeed(seed, chunkX, chunkZ)
            class_2919 rng = new class_2919(new class_5820(0L));
            rng.method_12663(seed, cx, czz);
            // ② 朝向也是从这个随机数里抽的（1 次 nextInt(4)）
            class_2470 rot = class_2470.method_16548(rng);
            // ③ 起点：区块中心偏一点（x/z 才是关键；y 只是把整座城平移，不影响船的水平位置）
            class_2338 pos = new class_2338(cx * 16 + 7, 64, czz * 16 + 7);

            List<class_3443> pieces = new ArrayList<>();
            class_3342.method_14679(mgr, pos, rot, pieces, rng);

            String ship = null;
            int sx1 = 0, sz1 = 0, sx2 = 0, sz2 = 0, sy1 = 0, sy2 = 0;
            int[] tpl = null;
            class_2470 shipRot = null;
            for (class_3443 p : pieces) {
                if (!(p instanceof class_3470)) continue;
                String name = (String) F_NAME.get(p);
                if (!"ship".equals(name)) continue;
                class_3341 b = p.method_14935();
                sx1 = F_MINX.getInt(b); sy1 = F_MINY.getInt(b); sz1 = F_MINZ.getInt(b);
                sx2 = F_MAXX.getInt(b); sy2 = F_MAXY.getInt(b); sz2 = F_MAXZ.getInt(b);
                class_2338 tp = (class_2338) F_TPL_POS.get(p);
                tpl = new int[]{tp.method_10263(), tp.method_10264(), tp.method_10260()};
                shipRot = ((net.minecraft.class_3492) F_PLACEMENT.get(p)).method_15113();
                ship = name;
            }
            if (ship == null) {
                System.out.printf("CITY %d %d NONE %d%n", cx, czz, pieces.size());
            } else {
                int cxx = (sx1 + sx2) / 2, cz2 = (sz1 + sz2) / 2;
                // 船模板里的标记：龙头 (6,8,0)、鞘翅 (6,5,7)、两个宝箱 (5,5,7)/(7,5,7)
                int[] head = localToWorld(shipRot, tpl, 6, 8, 0);
                int[] elytra = localToWorld(shipRot, tpl, 6, 5, 7);
                int[] ch1 = localToWorld(shipRot, tpl, 5, 5, 7);
                int[] ch2 = localToWorld(shipRot, tpl, 7, 5, 7);
                ch1[1] -= 1;   // 游戏把"Chest"标记的箱子放在标记下面一格
                ch2[1] -= 1;
                System.out.printf(
                    "CITY %d %d SHIP rot=%s box=%d,%d,%d..%d,%d,%d goto=%d,%d,%d head=%d,%d,%d elytra=%d,%d,%d chest=%d,%d,%d chest=%d,%d,%d pieces=%d%n",
                    cx, czz, shipRot, sx1, sy1, sz1, sx2, sy2, sz2, cxx, sy1, cz2,
                    head[0], head[1], head[2], elytra[0], elytra[1], elytra[2],
                    ch1[0], ch1[1], ch1[2], ch2[0], ch2[1], ch2[2], pieces.size());
            }
        }
    }
}
