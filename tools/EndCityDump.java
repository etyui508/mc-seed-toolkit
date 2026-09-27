// 末地城"逐段 dump" —— 直接跑游戏本体的 EndCityPieces，把每一段都打出来。
// 这是对拍基准：tools/endcity.c（自己复刻的那份，不用游戏）要和它逐段一致。
//
// 用法: java -cp <游戏classpath>:out EndCityDump <世界种子> <区块x> <区块z> ...
//   输出: CITY <cx> <cz> pieces=<段数> rot=<城朝向>
//         PIECE <序号> <名字> rot=<朝向> depth=<批次> tpl=<x>,<y>,<z> box=<x0>,<y0>,<z0>..<x1>,<y1>,<z1>
//   y 用"基点 0"（和 endcity.c 的 dump 对齐）——游戏内部只有相对高度有意义。
//
// 编译（和 ShipFinder 一样，对着 Fabric 的 intermediary jar）见 tools/run-endcity-verify.sh
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
import net.minecraft.class_3492;
import net.minecraft.class_3499;
import net.minecraft.class_5820;
import sun.misc.Unsafe;

public class EndCityDump {
    static final Map<String, class_3499> TPL = new HashMap<>();
    static Field F_SIZE, F_NAME, F_TPL_POS, F_PLACEMENT;
    static Field F_MINX, F_MINY, F_MINZ, F_MAXX, F_MAXY, F_MAXZ;

    /** 假模板管理器：只要尺寸（和 ShipFinder 同一个套路） */
    static class Mgr extends class_3485 {
        @SuppressWarnings("unchecked")
        Mgr() {
            super((net.minecraft.class_3300) null, (net.minecraft.class_32.class_5143) null,
                  (com.mojang.datafixers.DataFixer) null,
                  (net.minecraft.class_7871<net.minecraft.class_2248>) null);
        }

        @Override
        public class_3499 method_15091(class_2960 id) {
            String path = id.method_12832();
            String name = path.substring(path.lastIndexOf('/') + 1);
            class_3499 t = TPL.get(name);
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

    public static void main(String[] args) throws Exception {
        if (args.length < 4) {
            System.out.println("用法: EndCityDump <世界种子> <尺寸文件> <区块x> <区块z> [区块x 区块z ...]");
            return;
        }
        long seed = Long.parseLong(args[0]);

        net.minecraft.class_155.method_36208();
        net.minecraft.class_2966.method_12851();

        F_SIZE = class_3499.class.getDeclaredField("field_15587");
        F_NAME = class_3470.class.getDeclaredField("field_31664");
        F_TPL_POS = class_3470.class.getDeclaredField("field_15432");
        F_PLACEMENT = class_3470.class.getDeclaredField("field_15434");
        F_MINX = class_3341.class.getDeclaredField("field_14380");
        F_MINY = class_3341.class.getDeclaredField("field_14379");
        F_MINZ = class_3341.class.getDeclaredField("field_14378");
        F_MAXX = class_3341.class.getDeclaredField("field_14377");
        F_MAXY = class_3341.class.getDeclaredField("field_14376");
        F_MAXZ = class_3341.class.getDeclaredField("field_14381");
        for (Field f : new Field[]{F_SIZE, F_NAME, F_TPL_POS, F_PLACEMENT,
                                   F_MINX, F_MINY, F_MINZ, F_MAXX, F_MAXY, F_MAXZ}) {
            f.setAccessible(true);
        }

        for (String line : java.nio.file.Files.readAllLines(java.nio.file.Paths.get(args[1]))) {
            line = line.trim();
            if (line.isEmpty() || line.startsWith("#")) continue;
            String[] a = line.split("\\s+");
            class_3499 tpl = new class_3499();
            F_SIZE.set(tpl, new class_2382(Integer.parseInt(a[1]), Integer.parseInt(a[2]),
                                           Integer.parseInt(a[3])));
            TPL.put(a[0], tpl);
        }
        Mgr mgr = (Mgr) unsafe().allocateInstance(Mgr.class);

        List<int[]> cities = new ArrayList<>();
        for (int i = 2; i + 1 < args.length; i += 2) {
            cities.add(new int[]{Integer.parseInt(args[i]), Integer.parseInt(args[i + 1])});
        }

        for (int[] city : cities) {
            int cx = city[0], cz = city[1];
            class_2919 rng = new class_2919(new class_5820(0L));
            rng.method_12663(seed, cx, cz);
            class_2470 rot = class_2470.method_16548(rng);
            class_2338 pos = new class_2338(cx * 16 + 7, 0, cz * 16 + 7);
            List<class_3443> pieces = new ArrayList<>();
            class_3342.method_14679(mgr, pos, rot, pieces, rng);

            System.out.printf("CITY %d %d pieces=%d rot=%d%n", cx, cz, pieces.size(), rot.ordinal());
            int idx = 0;
            for (class_3443 p : pieces) {
                String name = "?";
                if (p instanceof class_3470 tp) {
                    name = (String) F_NAME.get(tp);
                }
                class_3341 b = p.method_14935();
                int x0 = F_MINX.getInt(b), y0 = F_MINY.getInt(b), z0 = F_MINZ.getInt(b);
                int x1 = F_MAXX.getInt(b), y1 = F_MAXY.getInt(b), z1 = F_MAXZ.getInt(b);
                String tpl = "?";
                int rotP = -1;
                String mirrorP = "?";
                if (p instanceof class_3470 tp) {
                    class_2338 t = (class_2338) F_TPL_POS.get(tp);
                    class_3492 pl = (class_3492) F_PLACEMENT.get(tp);
                    rotP = pl.method_15113().ordinal();
                    mirrorP = String.valueOf(pl.method_15114());
                    tpl = t.method_10263() + "," + t.method_10264() + "," + t.method_10260();
                }
                System.out.printf("PIECE %d %s rot=%d depth=%d mirror=%s tpl=%s box=%d,%d,%d..%d,%d,%d%n",
                        idx++, name, rotP, p.method_14923(), mirrorP, tpl, x0, y0, z0, x1, y1, z1);
            }
        }
    }
}
