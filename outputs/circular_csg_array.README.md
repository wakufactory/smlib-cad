# 円形 CSG 配置

ソースは `examples/circular_csg_array.txt`、画面に読み込めるモデルは `examples/circular_csg_array.json` です。`part clamp` に台座と円柱ボスの結合、貫通穴の切り抜き、外側へ開くスリットの切り抜きを一度だけ定義し、`use` で6個の CSG 形状を生成します。中央のカラーも二つの円柱の差分です。合計 7 形状を個別の材質で GLB に出力します。

子グループの `position 30 0 0` が各クランプを原点から半径 30 の位置へ移し、親グループの `euler 0 0 0/60/120/180/240/300` が原点を中心に回します。この順序で、スリットも各クランプの外側へ向きます。

ルートディレクトリから再生成できます。

```sh
make glb MODEL=examples/circular_csg_array.json GLB=outputs/circular_csg_array.glb
```

ソース座標は Z-up、GLB は Y-up です。保存済み設定は弦高許容値 `0.12`、角度条件 `18°`、全体加工なしです。
