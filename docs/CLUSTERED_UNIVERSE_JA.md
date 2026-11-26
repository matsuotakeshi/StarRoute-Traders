# 星団と空白地帯のある宇宙を生成する

次の新宇宙の候補を、現行の240×120でオフライン生成する例です。
本番では推測されにくい独自のシードを使い、生成パッケージは運営者だけが参照できる場所に保管します。

```sh
umask 077
python3 -m srt_universe_generator \
  --template examples/release-world.json \
  --parameters examples/clustered-universe-trial.json \
  --levels examples/industry-levels-trial.json \
  --seed YOUR-PRIVATE-SEED --output private-universe.json
```

このコマンドはパッケージ作成までを行います。有効化は従来の管理操作で別途実施します。
均一配置を使うには従来どおり `examples/connected-universe-trial.json` を指定します。

| 設定 | 240×120の試遊値 | 内容 |
| --- | ---: | --- |
| `width`, `height` | 240, 120 | 横幅と縦幅 |
| `distribution.mode` | `clusters_and_void_v1` | 星団配置の方式 |
| `distribution.cluster_count` | 4 | 星団数 |
| `distribution.frontier_planets` | 8 | 星団外の惑星数。残る40個を各星団へ均等配分 |
| `distribution.cluster_radius` | 18 | 各星団の円の半径 |
| `distribution.void_width` | 30 | 中央の空白帯の幅。通常惑星の配置を禁止 |
| `distribution.min_distance` | 4 | 通常惑星同士の最小チェビシェフ距離 |
| `max_attempts` | 32 | 配置、航路、幻の星などの制約が成立するまでの試行上限 |

星団中心は横方向の各区画内でシードから決めます。通常惑星48個を重複なく置き、
既存の船の航続距離内にある航路から最小全域木を作ります。初期開通は47本です。
未開通候補には、その1本の開通で両端間の移動距離を最も短縮できる航路を含めます。
幻の星は既存のチェビシェフ距離（全通常惑星から10以上、基準惑星から40以内）で
候補を探索します。制約が成立しない場合は別の配置を試し、上限で失敗として返します。

公開可能な合成データだけの比較を再現するには次を実行します。

```sh
python3 scripts/compare_universe_distributions.py --directory comparison --seed cluster-comparison-0
```

星図の `*` は1惑星、数字は同じ表示マスに収まった惑星数です。
区画内外の移動距離は、各惑星の横座標を4等分した区画を使って集計します。
360×180はオフライン生成・比較用です。運用時の有効化とゲーム画面は240×120を前提にしています。
試遊値を調整する際は、複数シードで空白帯の幅、近隣距離、星団間航路、寄付航路の短縮幅を比較します。
