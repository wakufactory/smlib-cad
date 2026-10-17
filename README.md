# SMLib Modeler

テキスト命令または Python コードで BRep を作り、ブラウザでプレビューして GLB に保存するローカルツールです。形状生成とテッセレーションには、同梱の `usd-brep` ソースから作る **USD 非依存** の `_smlib_core` Python 拡張を使います。USD ファイルや `pxr` API は使いません。

## ビルドと起動（Apple Silicon）

このフォルダーで実行します。Python 3.12 と pybind11 2.11.1 が必要です。先の公式ビルド試行で Packman Python 3.12 は `.packman-cache/python/` に取得済みです。`Makefile` はそれを自動検出します。別の Python 3.12 を使う場合は `make PYTHON=/path/to/python3.12` を指定してください。

```bash
uv pip install --target .deps/pybind11 pybind11==2.11.1
make start
```

`make start` は必要なネイティブ拡張をビルドしてからサーバーを起動します。`http://127.0.0.1:8765` を開きます。別のポートは `make start PORT=8766`、別の Python 3.12 は `make start PYTHON=/path/to/python3.12` で指定できます。停止は起動した端末で Ctrl+C を押します。`Makefile` はこのツールに必要な `SMLib`、`SM_API`、`_smlib_core` を arm64 用の単一 Python 拡張に直接リンクします。公式の macOS 用 premake パッケージや OpenUSD は不要です。

ネイティブバインディングの確認:

```bash
PYTHONPATH="$PWD/.build/smlib-core" \
  "$PWD/.packman-cache/python/3.12.14-macos-aarch64/bin/python3.12" \
  -m unittest discover -s usd-brep/source/SmPyCore/tests -v
```

`_smlib_core` は下記のプリミティブに加え、Boolean、全エッジ加工、`face_info`、`offset_brep`、`shell_brep`、`transform_brep`、`tessellate` を公開します。楕円球は球を中心から X/Y/Z 方向へ拡大縮小した BRep です。USD は使いません。引数・戻り値・所有権の契約は [ツール境界 API 仕様](usd-brep/docs/smlib-core-tool-api.md) を参照してください。

## 入力

「テキスト命令」は 1 行に 1 命令を書きます。`#` 以降はコメントです。単位は任意ですが、モデル内では統一してください。

「JSON を保存」を押すと、現在のテキスト命令またはPythonコードと、曲面精度・角度条件・全体加工・幅/半径を `model.json` に保存します。「JSON を読み込む」でそのファイルを選ぶと、入力モード・コード・各設定が復元され、自動でプレビューが更新されます。JSON が壊れている場合や未対応の形式の場合は、編集中の内容を変更せずにエラーを表示します。

ファイル形式は UTF-8 のJSONです。`format: "smlib-model"`、`version: 1`、`mode`（`"text"` または `"python"`）、`source`、`parameters` を持ちます。PythonモードのJSONを読み込んでプレビューする場合や `make glb` で変換する場合、保存されたPythonコードが実行されます。

保存したJSONをGLBへ変換するには `make glb` を実行します。必要なら `_smlib_core` もビルドします。既定の入力は `model.json` で、同じ場所に `model.glb` を作ります。別の入力や出力先には `MODEL` と `GLB` を指定できます。モデル定義と全体パラメータは画面の「GLB を保存」と同じ処理に渡されます。

```bash
make glb
make glb MODEL=design.json
make glb MODEL=design.json GLB=outputs/design.glb
```

```json
{
  "format": "smlib-model",
  "version": 1,
  "mode": "text",
  "source": "box body 0 0 0 10 10 10\n",
  "parameters": {"chord": 0.08, "angle": 20, "finish": "none", "finishSize": 1}
}
```

```text
box body -10 -10 0 20 20 8
sphere hole 0 0 8 7
subtract result body hole
material result 0.85 0.24 0.12 0.65 0.3
```

| 命令 | 引数 |
| --- | --- |
| `box` | `名前 x y z 幅 奥行 高さ` |
| `sphere` | `名前 x y z 半径` |
| `cylinder` | `名前 x y z 半径 高さ [dx dy dz]` |
| `cone` | `名前 x y z 底面半径 上面半径 高さ [dx dy dz]`（上面半径 `0` で円錐） |
| `torus` | `名前 x y z 主半径 管半径 [dx dy dz]` |
| `pyramid` | `名前 x y z 底面の辺長 高さ [dx dy dz]` |
| `cylindrical_box` | `名前 x y z 高さ 内半径 外半径 開始角 終了角 [dx dy dz]` |
| `partial_sphere` | `名前 x y z 半径 開始角 終了角 [dx dy dz]` |
| `partial_cone` | `名前 x y z 底面半径 上面半径 高さ 開始角 終了角 [dx dy dz]` |
| `partial_cylinder` | `名前 x y z 半径 高さ 開始角 終了角 [dx dy dz]` |
| `partial_torus` | `名前 x y z 主半径 管半径 開始角 終了角 [dx dy dz]` |
| `ellipsoid` | `名前 x y z X半径 Y半径 Z半径` |
| `sphere_no_pole` | `名前 x y z 半径` |
| `plane` | `名前 x y z X長さ Y長さ`（面） |
| `planar_circle` | `名前 x y z 半径`（面） |
| `profile` / `polygon` / `end` | `profile 断面名` 内に `polygon u1 v1 u2 v2 ...` を1行記述して `end` で閉じる |
| `extrude` | `名前 断面名 x y z 開始距離 終了距離 [dx dy dz [ux uy uz]]` |
| `revolve` | `名前 断面名 x y z 開始角 終了角 [dx dy dz [ux uy uz]]`（度数） |
| `union` / `subtract` / `intersect` | `出力名 左の形状名またはグループ名 右の形状名またはグループ名` |
| `chamfer` | `形状名 幅`（その形状の全エッジを面取り） |
| `fillet` | `形状名 半径`（その形状の全エッジを丸め） |
| `offset` | `形状名 距離`（正は外側、負は内側） |
| `shell` | `形状名 厚み [開口面の番号 ...]`（正は外側、負は内側。面指定なしは閉じた中空体） |
| `faces` | `形状名`（現在の面番号と各面の座標範囲をログへ表示） |
| `material` | `形状名 baseColorのR G B metallic roughness` |
| `part` / `end` | ルート階層で `part 部品名` から `end` までを再利用可能な定義にする |
| `use` | `use 部品名 [配置名]` で部品を新しく生成する |
| `group` / `end` | `group 名前` から `end` までをローカル座標のグループにする。入れ子可 |
| `scale` | グループ内で `scale sx sy sz`（各軸の正の倍率） |
| `euler` | グループ内で `euler rx ry rz`（度数） |
| `position` | グループ内で `position x y z`（親座標での移動） |

### 押し出しと回転体

`profile` は穴なしの閉じた多角形断面です。3〜1024頂点の `(u, v)` を並べ、最後から最初への辺は自動で閉じます。最初の点を末尾にもう一度書くこともできます。時計回り・反時計回りのどちらも受け付け、自己交差、自己接触、辺の重なり、長さゼロの辺、面積ゼロを拒否します。円弧・スプライン・穴付き断面は未対応です。

```text
profile section
  polygon 0 0  18 0  18 5  6 5  6 16  0 16
end
extrude bracket section 0 0 0 -3 3

profile wall
  polygon 5 0  9 0  9 12  5 12
end
revolve sleeve wall 30 0 0 0 360
revolve sector wall 60 0 0 30 270
```

`extrude` は断面をローカルXY面に置き、ローカルZ座標の `開始距離 < 終了距離` の間に押し出して両端を閉じます。負の距離も使え、`-3 3` は断面を中心に両側3ずつ押し出します。原点 `(x, y, z)` は距離0の断面原点です。

`revolve` は断面の `(u, v)` を `(半径, 高さ)` として使い、原点を通る軸の周りに右ねじ方向へ回転します。半径は0以上で、軸への接触を許可します。`0 < 終了角 - 開始角 <= 360`、部分回転は開始・終了の端面を閉じ、360度は全回転になります。`wall` は穴のない長方形断面ですが、軸から離れているため全回転すると中空の筒になります。

軸 `dx dy dz` の既定は +Z、長さは形状に影響しません。横方向 `ux uy uz` は押し出しのローカル+X／回転角0度の半径方向を指定し、軸に垂直な面へ投影して正規化します。ゼロベクトルや軸に平行な横方向はエラーです。横方向を省略した場合は、既存プリミティブと同じ +Z から軸への最短回転を使います。横方向だけ指定したい場合は軸も明記します。

断面は生成後も再利用できます。グループ内の断面はそのグループと子グループで参照でき、`part` 内でも定義・利用できます。`use` は呼び出し位置で見える断面を継承し、各部品内の定義はその部品だけで有効です。断面は使用する命令より前に定義してください。グループの変換は生成したBRepに適用します。生成結果には既存の Boolean、材質、面取り・丸めを適用できます。

Python API でも同じ形状を生成できます。入力点列と `Profile` は生成で変更されません。

```python
section = sm.create_profile([(0, 0), (18, 0), (18, 5), (6, 5), (6, 16), (0, 16)])
result = sm.create_extrude(section, (0, 0, 0), -3, 3)
# 半径・高さ断面を +X 軸の周りに回す。角度0の半径方向は +Y。
wall = sm.create_profile([(5, 0), (9, 0), (9, 12), (5, 12)])
result = sm.create_revolve(wall, (0, 0, 0), 30, 270, axis=(1, 0, 0), xdir=(0, 1, 0))
```

画面の「押し出し・回転体」→「読込」で、凹断面の押し出しと全回転・部分回転の3形状を読み込めます。ソースは `examples/extrude_revolve.txt`、JSONモデルは `examples/extrude_revolve.json`、生成済みGLBは `outputs/extrude_revolve.glb` です。再生成は `make glb MODEL=examples/extrude_revolve.json GLB=outputs/extrude_revolve.glb` で行います。

### オフセットとシェル

`offset 名前 距離` は形状全体の面を法線方向にずらします。正の距離は外側、負の距離は内側で、平行移動とは異なります。`shell 名前 厚み [面番号 ...]` は元の境界とオフセットした境界の間に壁を作り、指定した面を開口にします。いずれもテキスト命令では同じ名前の形状を新しい結果に置き換え、材質を保持します。距離・厚みは有限な非ゼロ値を指定します。

```text
box body 0 0 0 10 10 10
offset body 1

box cup 20 0 0 10 10 10
faces cup
shell cup -1 1
```

この未加工の `box` では面0が−Z面、面1が＋Z面なので、`shell cup -1 1` で外寸を保った上面開口の箱になります。面指定を省略すると閉じた中空体、`shell cup -1 0 1` なら上下に開口した角筒になります。面番号は0始まりです。Boolean・面取り・オフセットなどの加工後は変化し得るので、実行対象の形状に `faces 名前` を使って確認してください。範囲はその命令時点の座標であり、外側の `group` の未適用変換は含みません。番号のクリック選択は未対応です。

Python API は新しい `Brep` を返し、元の形状を保持します。`_smlib_core.shell_brep` の開口面指定は **面番号の整数列** で、`_omni_solid` の `Face` ハンドル列とは異なります。

```python
body = sm.create_box((0, 0, 0), 10, 10, 10)
print(sm.face_info(body))
expanded = sm.offset_brep(body, 1)
result = sm.shell_brep(body, -1, faces_to_shell=[1])
```

Python の詳細設定は `extended_offset=True`（凸部の隣接面を延長して交差）、`self_intersection=True`（自己交差の処理）です。シェルには `create_solid=True`（面入力の開いた端同士をつなぐ）もあります。テキスト命令ではこれらの既定値を使います。厚みが局所的な形状寸法や曲率に対して大きすぎる場合など、カーネルが処理できない形状は操作名・ステータスを含むエラーになります。

画面の「オフセット・シェル」→「読込」で、外側オフセット・上面開口の箱・上下開口の角筒を試せます。ソースは `examples/offset_shell.txt`、JSONモデルは `examples/offset_shell.json`、GLBは `outputs/offset_shell.glb` です。再生成は `make glb MODEL=examples/offset_shell.json GLB=outputs/offset_shell.glb` で行います。

### グループ変換

`group 名前` から `end` までの形状と Boolean 結果をまとめて変換できます。グループの原点はローカル座標 `(0, 0, 0)` です。`scale`、`euler`、`position` はグループの設定値であり、記述位置にかかわらずそのグループ内の完成形状すべてに適用します。同じ項目を複数回書いた場合は最後の値を使います。省略値はそれぞれ `1 1 1`、`0 0 0`、`0 0 0` です。

```text
group assembly
  position 20 0 0
  euler 0 0 30
  box body 0 0 0 10 10 10
  sphere hole 5 5 5 2
  subtract part body hole
  group detail
    position 0 0 8
    box cap 0 0 0 3 3 2
  end
end
```

変換はローカル原点を基準に拡大縮小し、X → Y → Z の順に回転してから、親座標で移動します（行列では `T × Rz × Ry × Rx × S`）。子グループの変換を先に、その後に親グループの変換を適用します。Boolean の入力は同じグループ内の形状か、閉じた子グループから親へ渡された形状です。グループを閉じると、残った形状名と材質が親へ渡されます。親と同名の形状があればエラーになります。グループ名は説明用で、形状名のように Boolean の入力には指定できません。プレビューと GLB は変換後の BRep をテッセレーションします。

### 部品の再利用

`part 部品名` はルート階層で定義し、`use 部品名 [配置名]` で配置します。定義はソース内の `use` より後に書いても参照できます。部品内では通常の形状・Boolean・材質・グループ命令を使えます。`use` ごとに部品の CSG を評価し直し、独立した BRep を生成します。

```text
part clamp
  box body -6 -5 0 12 10 5
  cylinder bore 0 0 -1 2 7
  subtract result body bore
end

group station
  position 30 0 0
  use clamp front
  material front__result 0.8 0.2 0.1 0.5 0.4
end
```

完成した形状名には `配置名__形状名` を使います。上の例は `front__result` です。配置名を省略すると `部品名_1`、`部品名_2` のような名前を自動で割り当てます。部品内の材質も形状名とともに引き継がれ、配置後に `material` で変更できます。名前の衝突と再帰的な部品参照はエラーです。展開は最大 512 回、入れ子参照は最大 32 段です。GLB は各配置の完成形状を個別メッシュとして出力します。

`cylinder`、`cone`、`torus`、`pyramid`、`cylindrical_box`、`partial_sphere`、`partial_cone`、`partial_cylinder`、`partial_torus` には、末尾に軸方向 `dx dy dz` を追加できます。長さは任意ですが、ゼロベクトルは指定できません。省略時は +Z 方向です。たとえば `cylinder post 0 0 0 2 10 1 0 0` は原点を底面中心として +X 方向に伸びる円柱です。Python コードでも `sm.create_cylinder((0, 0, 0), 2, 10, axis=(1, 0, 0))` のように指定できます。軸は BRep を回転するため、プレビュー・Boolean・GLB のすべてに反映されます。

角度は形状のローカル XY 平面の X 軸からローカル Z 軸回りに測った度数で、終了角は開始角より大きく、差は最大 360° です。`partial_sphere` は軸回りの扇形で、半球ではありません。軸を傾けるときのローカル X/Y は、+Z から指定軸への最短回転で決まります。`plane` と `planar_circle` は厚みのない面です。プレビューと GLB 出力には使えますが、立体 Boolean の入力には向きません。

### グループを入力にする Boolean 演算

`end` で閉じたグループ名は、`union`・`subtract`・`intersect` の左右どちらにも指定できます。グループの変換後の座標で演算します。

```text
group moved
  position 10 0 0
  box body 0 0 0 10 10 10
end

cylinder hole 15 5 -1 2 12
subtract result moved hole
```

複数形状を含むグループは、参照時に中の形状をすべて結合して1つの BRep にしてから演算します。離れた形状も含められます。子グループや `use` で生成した形状も対象です。演算前の表示では個々の形状と材質を保持しますが、演算後は入力を消費して出力名の1形状になり、材質は `material result ...` で指定し直します。入力に指定したグループ名は消費されます。出力名にそのグループ名を指定した場合は、以後は形状名として扱います。

閉じた子グループ名も親スコープに公開されます。形状名とグループ名の衝突はエラーです。同じ形状を共有する左右の入力（親グループとその子、グループとそのメンバーなど）や、空のグループは指定できません。`part` 内のグループ名はその部品の評価内で使えます。`use` が外側に公開する名前は従来どおり完成形状の `配置名__形状名` です。

### 全エッジの面取り・丸め

画面の「全体加工」で「面取り」または「丸め」を選び、「幅/半径」に正の値を入力すると、ソースで作った各形状の全エッジへ適用します。面取りの値は面取り面を横切る幅、丸めの値は円弧半径です。「プレビュー」と「GLB を保存」の両方で再計算します。特定の形状だけ加工する場合は、テキスト命令を形状生成後に書きます。

```text
box body 0 0 0 10 10 10
chamfer body 1
```

Python コードでは `result = sm.chamfer_fillet(result, radius=1)` または `result = sm.circular_fillet(result, radius=1)` と書けます。どちらも BRep をその場で変更して同じ BRep を返します。加工寸法が大きすぎる場合や、球・平面など一括加工できない形状が混じる場合は、その形状名を表示して処理を中止します。「全プリミティブ」のサンプルには一括加工できない形状が含まれます。特定の形状だけ加工するには個別命令を使ってください。ソース内の加工と画面の「全体加工」を両方指定した場合は、ソース内の加工を先に適用します。

### 球の陰影と曲面精度

画面の「曲面精度」はテッセレーションの弦高許容値（0.001～2、モデルの単位）、「角度条件」は曲線・曲面の角度許容値（1～90°）です。どちらも小さい値ほど通常は細かくなります。角度条件の初期値は従来と同じ 20° で、プレビューと GLB 保存の両方に適用します。片方の条件を緩めてももう片方が分割数を決める場合があるため、三角形数は連続的には変わりません。通常の `sphere` は極に特異点と継ぎ目があり、SMLib の分割結果によっては局所的に大きな三角形ができます。半径 4 の単独球で弦高 `0.02` を指定した測定では、三角形重心の球面からの最大距離は通常球で約 `0.188`、`sphere_no_pole` で約 `0.011` でした。球面上の位置は正しくても、三角形の内部は平面なので溝状に見える場合があります。

球を単独で滑らかに見せたい場合は `sphere_no_pole` を使えます。プレビューと GLB は曲面に沿った頂点法線を使い、箱などの稜線は鋭いままにしています。プレビューの照明は概略表示なので、明暗の境界も形状の溝とは区別してください。

Boolean 命令は右側の入力形状を消費します。複雑なモデルには「Python コード」を選び、`_smlib_core` を `sm` として利用してください。完成形を `result` に代入します。

```python
body = sm.create_box((-10, -10, 0), 20, 20, 8)
hole = sm.create_sphere((0, 0, 8), 7)
result = sm.boolean_difference(body, hole)
materials = {"result": {"baseColor": [0.85, 0.24, 0.12], "metallic": 0.65, "roughness": 0.3}}
```

追加プリミティブの Python 名は各テキスト命令に `create_` を付けたものです。例えば `sm.create_ellipsoid((0, 0, 0), 8, 5, 3)`、`sm.create_cone((0, 0, 0), 4, 0, 7)`、`sm.create_partial_torus((0, 0, 0), 6, 1, 0, 180)` と書けます。

材質は完成したソリッド名ごとに指定します。`baseColor` は線形 RGB の3値、`metallic` と `roughness` はそれぞれ1値で、いずれも `0` から `1` の範囲です。省略したソリッドには既定の水色の材質を使います。Boolean 演算で作った形状には、演算後の名前を指定してください。GLB には glTF の PBR 材質として保存されます。ブラウザのプレビューは three.js の `MeshStandardMaterial` で同じ値を使い、環境マップなしの平行光と環境光で照らします。

「プレビュー」で再計算します。プレビュー右上の表示切替で `Shading`（PBR 材質と照明）と `Wireframe`（テッセレーション後の三角形の辺）を切り替えられます。`Shading` の光は画面左上側からの平行光で、視点を回しても画面上の方向は固定です。切替時の再計算は不要です。描画には CDN から読み込む three.js 0.186.1 を使うため、ブラウザから `cdn.jsdelivr.net` へ接続できる必要があります。GLB は保存時にも同じソースから再計算するため、プレビュー後に編集した場合は最新の内容が保存されます。GLB は glTF 標準の Y-up 座標へ変換します。Python コードは任意のローカルコードとして実行されます。信頼できるコードだけを入力し、本ツールは `127.0.0.1` のみに公開してください。

### 全プリミティブと材質のサンプル

画面上部で「全プリミティブ」を選び「読込」を押すと、`examples/all_primitives_materials.txt` がテキスト命令として読み込まれます。15種類を5列×3行に並べ、各形状に固有の `baseColor`、`metallic`、`roughness` を割り当てています。平面と平面円も含みます。生成済み GLB は `outputs/primitive_gallery/all_primitives_materials.glb`、材質・三角形数の対応は同じフォルダーの `manifest.json` にあります。

4気筒エンジンブロック風の CSG サンプルは `examples/inline_four_engine_block.json` にあります。テキスト命令でシリンダー穴、クランク軸トンネル、ボルト穴、側面ポートなどを構成し、生成済みの `outputs/inline_four_engine_block.glb` と再生成手順を `outputs/inline_four_engine_block.README.md` に置いています。

`part` と `group` を使う円形配置のサンプルは `examples/circular_csg_array.txt` と、画面へ読み込める `examples/circular_csg_array.json` にあります。1 個のクランプ定義を6回 `use` し、子グループの `position 30 0 0` と親グループの 60° 刻みの `euler` で円周上に並べます。各クランプは結合・穴あけ・スリット切り抜きの CSG です。中央のカラーも CSG です。画面の「円形 CSG 配置」→「読込」でも開けます。生成済みの `outputs/circular_csg_array.glb` と構成の説明は `outputs/circular_csg_array.README.md` にあります。GLB の再生成には `make glb MODEL=examples/circular_csg_array.json GLB=outputs/circular_csg_array.glb` を使います。

サンプルの GLB を再生成するには、ワークスペースのルートで実行します。

```bash
PYTHONPATH="$PWD/.build/smlib-core:$PWD" \
  "$PWD/.packman-cache/python/3.12.14-macos-aarch64/bin/python3.12" \
  examples/export_primitive_gallery.py
```

## 検証

プレビューと GLB の三角形化は共通です。穴なしの凸・凹多角形を面の2D投影上で耳切り法により分割し、その後、隣接する2三角形の最小角が改善する場合だけ内部の対角線を交換します。角度は元の3D座標で評価し、同品質の対角線は交換しません。境界・頂点数・三角形数・コーナー法線を保持します。頂点追加や最適品質の保証は行わないため、形状によっては細長い三角形が残ります。入力は自己交差のない単一輪郭を前提とし、分割できない面はエラーにします。穴の輪郭を持つ面の分割は未対応です。

```bash
PYTHONPATH="$PWD/.build/smlib-core:$PWD" \
  "$PWD/.packman-cache/python/3.12.14-macos-aarch64/bin/python3.12" \
  -m unittest discover -s tests -v
PYTHONPYCACHEPREFIX=/tmp/cad-pycache \
  "$PWD/.packman-cache/python/3.12.14-macos-aarch64/bin/python3.12" \
  -m py_compile modeler.py server.py json_to_glb.py
node --check app.js
node tests/test_model_file_ui.js
```

このテストはJSONモデルの往復と不正値の拒否、テキスト命令・三角形化・GLB 構造、追加プリミティブのネイティブ生成と楕円球の寸法・Boolean を確認します。ネイティブバインディング単体のテストは上記の Python 3.12 コマンドで実行します。
