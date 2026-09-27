这里是"对拍验证"脚本：用游戏本体里的类来验证算法实现是否完全一致。
注意：这些脚本是作者本机写的，里面的 classpath 路径写死在 verify/classpath.sh 里，
换机器要自己改。日常使用不需要它们，留着只是给你看"这些结论是怎么验证出来的"。

对拍内容（详见 ../docs/原理.md）：
  SpikeVerify.java      65536 个末地柱子布局 vs 游戏代码
  StructureVerify.java  5700 组结构摆放 vs 游戏自己的 RandomSpreadStructurePlacement
  HashVerify.java       20000 个种子的 sha256 vs BiomeAccess.hashSeed
  InfoTest.java         实测每个史莱姆区块能降多少候选
  （合成存档的扫描器自测在 ../tools/RegionScanSelfTest.java）
