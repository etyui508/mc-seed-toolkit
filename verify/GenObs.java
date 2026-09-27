/** 造一批“真实观测数据”给 CLI 测试用（拿已知种子反推它会长什么样） */
public class GenObs {
    public static void main(String[] args) {
        long seed = args.length > 0 ? Long.parseLong(args[0]) : 122893128579314L;
        System.out.println("v = " + SeedCracker.spikeValue(seed));
        StringBuilder sb = new StringBuilder();
        SeedCracker.Placement p = SeedCracker.placement("ocean_monuments");
        int n = 0;
        for (int x = 60; x < 2000 && n < 3; x += 5) {
            for (int z = -300; z < 300 && n < 3; z += 7) {
                if (SeedCracker.structureStartAt(seed, x, z, p)) {
                    sb.append("ocean_monuments:").append(x).append(',').append(z).append(';');
                    n++;
                }
            }
        }
        n = 0;
        for (int x = 40; x < 3000 && n < 6; x++) {
            if (SeedCracker.isSlimeChunk(seed, x, -x / 3)) {
                sb.append("slime:").append(x).append(',').append(-x / 3).append(';');
                n++;
            }
        }
        System.out.println(sb);
    }
}
