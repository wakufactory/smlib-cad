# 機械部品サンプル（10種）

各部品は `smlib-model` 形式の編集用 JSON、読みやすいテキスト命令 `.txt`、生成済み `.glb` の3ファイルです。`00_all_machine_parts.json` / `.glb` は10個を2行×5列に並べた一覧モデルです。寸法は任意の mm 相当です。実機用の公差や強度は設定していません。

| 番号 | 部品 | 回転体とブーリアンの見どころ |
| --- | --- | --- |
| 01 | フランジ付き軸受ハウジング | 段付き座面、4つの取付穴 |
| 02 | Vベルトプーリー | V溝断面、軸のキー溝 |
| 03 | 軸継手の片側 | 段付きハブ、キー溝、横向き止めねじ穴 |
| 04 | バルブハンドル | リムとハブの回転体、十字スポークとの和、軸穴 |
| 05 | パイプ継手ナット | 中空の段付き断面、4面の工具掛け |
| 06 | ノズルアダプター | 径の変わる流路、横向き貫通ポート |
| 07 | ブレーキローター | 段付きディスク、8つの肉抜き穴 |
| 08 | ペデスタル脚 | 筒状の座と2つの取付耳、ボルト穴 |
| 09 | パドル羽根車 | 回転ハブ、8枚の羽根との和、軸穴 |
| 10 | 偏心カム | 回転ハブと偏心ローブ、軸穴と位置決め穴 |

JSONをアプリの「JSON を読み込む」で開くとソースを編集できます。GLBは次のようにリポジトリのルートから再生成できます。

```sh
make glb MODEL=examples/machine_parts/01_bearing_housing.json
```

全10種のGLBを更新する場合:

```sh
for model in examples/machine_parts/0[1-9]_*.json examples/machine_parts/10_*.json; do make glb MODEL="$model"; done
```

個別モデルを編集した後、一覧モデルとそのGLBを更新する場合:

```sh
python3.12 examples/machine_parts/build_gallery.py
make glb MODEL=examples/machine_parts/00_all_machine_parts.json
```

`.txt` は JSON の `source` フィールドと同じ内容の閲覧用コピーです。ソースを変更したら JSON を正として GLB を再生成してください。
