# モデル編集チャット用仕様書

モデル編集チャットへ渡す、テキスト命令とPythonコードの仕様です。
このファイルを直接読み込むため、READMEの見出しや構成には依存しません。
言語・APIの変更時には、このファイルも実装に合わせて更新してください。

- 座標系はZ-upです。実寸を想定する場合、座標と寸法は1 = 1 mで記述します。10 mmは0.01です。
- 現在のソースとモデル設定を基準に編集し、無関係な形状・材質・グループ変換を保持します。
- テキスト命令とPythonの入力モードを維持します。
- Pythonでは `_smlib_core` が `sm` として渡されます。追加で渡される型スタブをAPIの引数・戻り値の参照にしてください。
- UIのモデル設定は参照情報です。返す変更対象はソース全文です。

## テキスト命令

「テキスト命令」は1行に1命令を書きます。`#`以降はコメントです。実寸モデルは1 = 1 mで統一します。既存モデルを編集する際は既存の単位・寸法を確認し、依頼されていない全体の拡大縮小は行いません。

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
| `profile` / `polygon` / `spline` / `end` | `profile 断面名` 内に `polygon u1 v1 ...` または `spline through u1 v1 ... closed` を1行記述して `end` で閉じる |
| `extrude` | `名前 断面名 x y z 開始距離 終了距離 [dx dy dz [ux uy uz]] [draft 角度]` |
| `revolve` | `名前 断面名 x y z 開始角 終了角 [dx dy dz [ux uy uz]]`（度数） |
| `union` / `subtract` / `intersect` | `出力名 左の形状名またはグループ名 右の形状名またはグループ名` |
| `chamfer` | `形状名 幅`（その形状の全エッジを面取り） |
| `fillet` | `形状名 半径`（その形状の全エッジを丸め） |
| `offset` | `形状名 距離`（正は外側、負は内側） |
| `shell` | `形状名 厚み [開口面の番号 ...]`（正は外側、負は内側。面指定なしは閉じた中空体） |
| `faces` | `形状名`（現在の面番号と各面の座標範囲をログへ表示） |
| `material` | `形状名またはグループ名 baseColorのR G B metallic roughness`。グループ指定は個別指定のない形状に適用 |
| `part` / `end` | ルート階層で `part 部品名` から `end` までを再利用可能な定義にする |
| `fn` | `fn 名前(引数, ...) = 式` で数値を返す計算関数を定義 |
| `use` | `use 部品名 [配置名]` で部品を新しく生成する |
| `group` / `end` | `group 名前` から `end` までをローカル座標のグループにする。入れ子可 |
| `invisible` | group 内に引数なしで指定し、子グループを含めて非表示にする。ソリッド計算は実行する |
| `scale` | グループ内で `scale sx sy sz`（各軸の正の倍率） |
| `euler` | グループ内で `euler rx ry rz`（度数） |
| `position` | グループ内で `position x y z`（親座標での移動） |
| `tessellation` | `形状名 曲面精度 角度条件`（形状別。各値に `default` を指定すると UI 設定を使用） |

Web UI の左ペインにある「テキストコマンド一覧」でも書式を参照できます。一覧だけをスクロールでき、右側のモデル定義を見ながら編集できます。初期状態では閉じています。見出しを押すと開閉できます。

## プリミティブの軸と角度

`cylinder`、`cone`、`torus`、`pyramid`、`cylindrical_box`、`partial_sphere`、`partial_cone`、`partial_cylinder`、`partial_torus` には、末尾に軸方向 `dx dy dz` を追加できます。長さは任意ですが、ゼロベクトルは指定できません。省略時は +Z 方向です。たとえば `cylinder post 0 0 0 2 10 1 0 0` は原点を底面中心として +X 方向に伸びる円柱です。Python コードでも `sm.create_cylinder((0, 0, 0), 2, 10, axis=(1, 0, 0))` のように指定できます。軸は BRep を回転するため、プレビュー・Boolean・GLB のすべてに反映されます。

角度は形状のローカル XY 平面の X 軸からローカル Z 軸回りに測った度数で、終了角は開始角より大きく、差は最大 360° です。`partial_sphere` は軸回りの扇形で、半球ではありません。軸を傾けるときのローカル X/Y は、+Z から指定軸への最短回転で決まります。`plane` と `planar_circle` は厚みのない面です。プレビューと GLB 出力には使えますが、立体 Boolean の入力には向きません。

`ellipsoid` は球を中心から X/Y/Z 方向へ拡大縮小した BRep です。

## 変数・式・繰り返し

テキスト命令では `let 名前 = 式` で数値変数を定義し、数値引数や形状名に `${式}` を埋め込めます。式で使えるのは有限な数値、定義済み変数、定数 `pi`・`e`、`+`、`-`、`*`、`/`、括弧、および下記の数学関数です。式内には空白を入れられます。`let` は定義した行以降で有効です。同じスコープで同名を再定義するとエラーになります。

| 関数 | 引数と単位 |
| --- | --- |
| `sin(x)`、`cos(x)`、`tan(x)` | `x` はラジアン |
| `asin(x)`、`acos(x)`、`atan(x)`、`atan2(y, x)` | 結果はラジアン |
| `exp(x)`、`log(x)`、`sqrt(x)`、`abs(x)` | 通常の指数・自然対数・平方根・絶対値 |
| `radians(x)`、`degrees(x)` | 度からラジアン、ラジアンから度への変換 |

CAD 命令の `euler` などの角度は度数なので、三角関数へ渡す際は `sin(radians(30))` のように変換します。例えば `let x = 18 * cos(radians(i * 360 / count))` と書けます。数学関数は許可リストからのみ呼び出せ、未対応の関数、属性参照、キーワード引数、定義域外や無限大になる計算はエラーです。Python の `eval` は使いません。

```text
let count = 6
let radius = 30
part peg
  cylinder body 0 0 0 2 5
end
for i in range(count)
  group station_${i}
    euler 0 0 ${i * 360 / count}
    group offset_${i}
      position ${radius} 0 0
      use peg peg_${i}
    end
  end
end
```

`fn 名前(引数, ...) = 式` で、数値を1つ返す計算関数を定義できます。`end` は不要で、引数なしの `fn count() = 6` も使えます。引数は識別子のみで、呼び出しは位置引数を使います。関数は定義した行以降で、`let` の右辺、`${...}`、`if`、`range(...)` の式から呼び出せます。複数引数の関数を `range` 内に入れることもできます。

```text
let radius = 30
fn angle(i, count) = i * 360 / count
fn circle_x(deg) = radius * cos(radians(deg))
fn circle_y(deg) = radius * sin(radians(deg))
for i in range(6)
  let deg = angle(i, 6)
  sphere ball_${i} ${circle_x(deg)} ${circle_y(deg)} 0 2
end
```

関数は定義時点の変数と定義済み関数を保持し、引数は関数本文内だけで有効です。呼び出し側の同名変数・関数によって参照先は変わりません。`group`・`for`・`if`・`part` 内でも定義でき、その外には漏れません。`part` は `use` 時点で見える関数を利用できます。同じスコープ内での同名定義、組み込み数学関数・定数名の関数定義、前方参照・再帰呼び出し、既定値・キーワード引数は使えません。関数本文は既存の数値式と同じ構文に制限され、未使用の定義も構文・名前・引数数を検査します。定義域やゼロ除算は呼び出し時に検査し、エラーには呼び出し行と関数定義行が付いています。式と関数呼び出しを合わせた深さは最大32段、1つの式の評価は最大10,000ノードです。

`for 名前 in range(回数)` は `0` から `回数 - 1` まで繰り返します。`range(開始, 終了)` と `range(開始, 終了, 刻み)` も使え、終了値は含みません。引数は整数、刻みは 0 以外です。ループは入れ子にでき、`end` で閉じます。ループ変数とループ内の `let` はその反復内だけで有効です。グループ内の `let` はそのグループ内だけで有効です。`part` 本文は `use` ごとに評価され、その時点で見える変数を参照できます。部品内の変数は外に出ません。部品定義は従来どおりルート階層だけに置きます。

`if 式` は式の値が0以外なら `end` までを1回展開し、0なら飛ばします。式は `let` の右辺と同じ数値式で、`${}` は付けません。負の値も0以外なので真です。`for` や `group`、`part` の本文に入れ子にできます。`if` 内の `let` は外へ出ませんが、作成した形状は通常の命令と同じスコープに残ります。

```text
let add_boss = 1
box body 0 0 0 10 10 4
if add_boss
  cylinder boss 5 5 4 2 3
  union body body boss
end
```

1つのループは最大512回、`for` と `if` の入れ子は最大32段、展開後は空行を含め最大20,000行です。未定義変数、ゼロ除算、有限でない結果、許可していない式は行番号付きのエラーになります。変数・計算関数・ループ・条件分岐はテキスト命令専用で、Python モードには影響しません。

## 押し出しと回転体

`profile` は穴なしの閉じた断面です。`polygon` は重複を除いた3〜1024頂点の `(u, v)` を直線で結び、最後から最初への辺は自動で閉じます。同じ点を複数回書いた場合は、最初の1回だけを残して以降を無視します。`spline through` は4〜64組の通過点を指定し、`closed` を末尾に付けます。各点を通る3次スプラインが最後から最初へつながります。同じ通過点を隣接して2回書くと、その位置で接線が折れます（例: `... 4 0  4 0 ...`）。3回以上の連続や、異なる点が4個未満の輪郭は拒否します。末尾に始点を再記載した場合は閉じ指定として取り除きます。どちらも時計回り・反時計回りを受け付け、自己交差、自己接触、重なり、ゼロ面積を拒否します。スプラインの検査は各区間16分割のサンプルに基づきます。穴付き断面は未対応です。

```text
profile section
  polygon 0 0  18 0  18 0  18 5  6 5  6 16  0 16
end
extrude bracket section 0 0 0 -3 3
extrude tapered section 30 0 0 0 5 draft 5

profile wall
  polygon 5 0  9 0  9 12  5 12
end
revolve sleeve wall 30 0 0 0 360
revolve sector wall 60 0 0 30 270

profile curved_wall
  spline through 2 0  4 0  4 0  5 1  5 3  4 4  2 4  1 3  1 1 closed
end
extrude curved_plate curved_wall 90 0 0 0 2
revolve curved_ring curved_wall 110 0 0 0 360
```

`extrude` は断面をローカルXY面に置き、ローカルZ座標の `開始距離 < 終了距離` の間に押し出して両端を閉じます。負の距離も使え、`-3 3` は断面を中心に両側3ずつ押し出します。原点 `(x, y, z)` は距離0の断面原点です。

末尾に `draft 角度` を付けると抜き勾配を付けます。角度は度数で `-90 < 角度 < 90`、正で内向き（終端側が小さく）、負で外向き（終端側が大きく）です。省略または `draft 0` は従来の直線押し出しです。`draft` は軸・横方向の指定より後に書きます。指定高さより手前で断面がつぶれる場合や、終端面ができない場合はエラーです。

`revolve` は断面の `(u, v)` を `(半径, 高さ)` として使い、原点を通る軸の周りに右ねじ方向へ回転します。半径は0以上で、軸への接触を許可します。`0 < 終了角 - 開始角 <= 360`、部分回転は開始・終了の端面を閉じ、360度は全回転になります。`wall` は穴のない長方形断面ですが、軸から離れているため全回転すると中空の筒になります。

軸 `dx dy dz` の既定は +Z、長さは形状に影響しません。横方向 `ux uy uz` は押し出しのローカル+X／回転角0度の半径方向を指定し、軸に垂直な面へ投影して正規化します。ゼロベクトルや軸に平行な横方向はエラーです。横方向を省略した場合は、既存プリミティブと同じ +Z から軸への最短回転を使います。横方向だけ指定したい場合は軸も明記します。

多角形とスプラインの断面は生成後も再利用できます。グループ内の断面はそのグループと子グループで参照でき、`part` 内でも定義・利用できます。`use` は呼び出し位置で見える断面を継承し、各部品内の定義はその部品だけで有効です。断面は使用する命令より前に定義してください。グループの変換は生成したBRepに適用します。生成結果には既存の Boolean、材質、面取り・丸めを適用できます。

Python API でも同じ形状を生成できます。入力点列と `Profile` は生成で変更されません。

```python
section = sm.create_profile([(0, 0), (18, 0), (18, 5), (6, 5), (6, 16), (0, 16)])
result = sm.create_extrude(section, (0, 0, 0), -3, 3)
result = sm.create_extrude(section, (0, 0, 0), 0, 5, draft_angle=5)
# 半径・高さ断面を +X 軸の周りに回す。角度0の半径方向は +Y。
wall = sm.create_profile([(5, 0), (9, 0), (9, 12), (5, 12)])
result = sm.create_revolve(wall, (0, 0, 0), 30, 270, axis=(1, 0, 0), xdir=(0, 1, 0))
smooth = sm.create_spline_profile([(2, 0), (4, 0), (5, 1), (5, 3),
                                   (4, 4), (2, 4), (1, 3), (1, 1)])
result = sm.create_extrude(smooth, (0, 0, 0), 0, 2)
result = sm.create_revolve(smooth, (10, 0, 0), 0, 360)
```

回転軸上に断面の点を置くことは有効です。円錐の先端など、法線が一意に決まらない特異点では、SMLibの多角形生成時に各多角形が接する方向から曲面法線を評価してコーナーごとに保持します。`_smlib_core` によるテッセレーション後の全メッシュ補正は不要です。先端1点に全周共通の法線を割り当てないため、内壁の片側だけ陰影が反転する問題を防ぎます。再現・確認用の断面は `examples/revolve_cone_tip.txt` にあります。`make test-pole-normals` はPythonを通さず、PolyBrepと6種類の描画コールバック、全回転・部分回転、Z軸・X軸の法線を検証します。

画面の「押し出し・回転体・スプライン」→「読込」で、折線断面の押し出し・回転体・抜き勾配付き押し出し4形状と、スプライン断面の押し出し・回転体2形状を読み込めます。ソースは `examples/extrude_revolve.txt`、JSONモデルは `examples/extrude_revolve.json`、生成済みGLBは `outputs/extrude_revolve.glb` です。再生成は `make glb MODEL=examples/extrude_revolve.json GLB=outputs/extrude_revolve.glb` で行います。

## オフセットとシェル

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

## グループ変換

`group 名前` から `end` までの形状と Boolean 結果をまとめて変換できます。グループの原点はローカル座標 `(0, 0, 0)` です。`scale`、`euler`、`position` はグループの設定値であり、記述位置にかかわらずそのグループ内の完成形状すべてに適用します。同じ項目を複数回書いた場合は最後の値を使います。省略値はそれぞれ `1 1 1`、`0 0 0`、`0 0 0` です。

グループ内に引数なしの `invisible` を書くと、記述位置にかかわらずグループ全体（子グループを含む）を非表示にします。BRep の作成・変換・Boolean・仕上げは通常どおり計算し、非表示の形状も演算の入力に使えます。テッセレーションは省略し、WebGL／USDZ プレビューと GLB／USDZ 書き出しには含めません。Boolean の結果は所属する親 group の表示設定に従い、非表示の入力を使っても、結果がその group の外に配置されれば表示されます。

```text
group helper
  invisible
  box tool 0 0 0 2 2 2
end
box body 0 0 0 5 5 5
subtract result body helper
```

この例では `helper` のソリッドを計算して切り抜きに使い、ルートにできた `result` を表示します。

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

## 部品の再利用

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

## グループを入力にする Boolean 演算

`end` で閉じたグループ名は、`union`・`subtract`・`intersect` の左右どちらにも指定できます。グループの変換後の座標で演算します。

```text
group moved
  position 10 0 0
  box body 0 0 0 10 10 10
end

cylinder hole 15 5 -1 2 12
subtract result moved hole
```

複数形状を含むグループは、参照時に中の形状をすべて結合して1つの BRep にしてから演算します。離れた形状も含められます。子グループや `use` で生成した形状も対象です。演算前の表示では個々の形状と材質を保持しますが、演算後は入力を消費して出力名の1形状になり、材質は `material result ...` で指定し直します。Boolean の結果は、全入力 solid に共通する最も近い、消費されずに残る親 group に所属します。共通の group がなければルートに配置します。入力側の枝の変換は結果形状に焼き込み、共通の親とそれより上の TRS は保持します。結果自身の TRS は単位変換です。無関係な兄弟 solid は残り、空になった group は export から除かれます。元の枝への追従関係はなく、ソース再評価時に再計算します。入力に指定したグループ名は消費されます。出力名にそのグループ名を指定した場合は、以後は形状名として扱います。

閉じた子グループ名も親スコープに公開されます。形状名とグループ名の衝突はエラーです。同じ形状を共有する左右の入力（親グループとその子、グループとそのメンバーなど）や、空のグループは指定できません。`part` 内のグループ名はその部品の評価内で使えます。`use` が外側に公開する名前は従来どおり完成形状の `配置名__形状名` です。

## 全エッジの面取り・丸め

画面の「全体加工」で「面取り」または「丸め」を選び、「幅/半径」に正の値を入力すると、ソースで作った各形状の全エッジへ適用します。面取りの値は面取り面を横切る幅、丸めの値は円弧半径です。「プレビュー」と「GLB を保存」の両方で再計算します。特定の形状だけ加工する場合は、テキスト命令を形状生成後に書きます。

```text
box body 0 0 0 10 10 10
chamfer body 1
```

Python コードでは `result = sm.chamfer_fillet(result, radius=1)` または `result = sm.circular_fillet(result, radius=1)` と書けます。どちらも BRep をその場で変更して同じ BRep を返します。加工寸法が大きすぎる場合や、球・平面など一括加工できない形状が混じる場合は、その形状名を表示して処理を中止します。「全プリミティブ」のサンプルには一括加工できない形状が含まれます。特定の形状だけ加工するには個別命令を使ってください。ソース内の加工と画面の「全体加工」を両方指定した場合は、ソース内の加工を先に適用します。

## テッセレーション精度と球の陰影

solid 個別のテッセレーション精度は、作成後に `tessellation 名前 曲面精度 角度条件` で指定できます。

```text
sphere fine 0 0 0 4
tessellation fine 0.01 5
sphere normal 10 0 0 4
# normal は画面の全体設定を使用
```

曲面精度は `0.001～2`（モデルの単位）、角度条件は `1～90`（度）です。各値に `default` を指定すると、その項目は全体設定を使用します（例: `tessellation fine default 5`）。命令がない solid は両方とも全体設定を使用します。同じ solid への再指定は前の指定を置き換え、`tessellation fine default default` で両方を全体設定へ戻せます。設定はグループの変換・`part` / `use`・面取り・丸め・offset・shell を通じて保持され、プレビュー・GLB・USDZ に共通で適用されます。Boolean 演算は入力の設定を引き継がないため、必要なら演算後の solid に指定してください。グループ名への一括指定や、Boolean 結果の面ごとの指定には対応しません。JSON にはテキストソースの一部として保存されます。

画面の「曲面精度」はテッセレーションの弦高許容値（0.001～2、モデルの単位）、「角度条件」は曲線・曲面の角度許容値（1～90°）です。どちらも小さい値ほど通常は細かくなります。角度条件の初期値は従来と同じ 20° で、プレビューと GLB 保存の両方に適用します。片方の条件を緩めてももう片方が分割数を決める場合があるため、三角形数は連続的には変わりません。通常の `sphere` は極に特異点と継ぎ目があり、SMLib の分割結果によっては局所的に大きな三角形ができます。半径 4 の単独球で弦高 `0.02` を指定した測定では、三角形重心の球面からの最大距離は通常球で約 `0.188`、`sphere_no_pole` で約 `0.011` でした。球面上の位置は正しくても、三角形の内部は平面なので溝状に見える場合があります。

球を単独で滑らかに見せたい場合は `sphere_no_pole` を使えます。プレビューと GLB は曲面に沿った頂点法線を使い、箱などの稜線は鋭いままにしています。プレビューの照明は概略表示なので、明暗の境界も形状の溝とは区別してください。

## 三角形化

プレビューと GLB の三角形化は共通です。穴なしの凸・凹多角形を面の2D投影上で耳切り法により分割し、その後、隣接する2三角形の最小角が改善する場合だけ内部の対角線を交換します。角度は元の3D座標で評価し、同品質の対角線は交換しません。境界・頂点数・三角形数・コーナー法線を保持します。頂点追加や最適品質の保証は行わないため、形状によっては細長い三角形が残ります。入力は自己交差のない単一輪郭を前提とし、分割できない面はエラーにします。穴の輪郭を持つ面の分割は未対応です。

## Python コード

Pythonコードはモデル生成処理として実行されます。生成するコードは形状・材質の定義に限定し、ファイル操作、外部通信、プロセス実行や外部ライブラリのインポートは含めません。

Boolean 命令は右側の入力形状を消費します。複雑なモデルには「Python コード」を選び、`_smlib_core` を `sm` として利用してください。完成形を `result` に代入します。

```python
body = sm.create_box((-10, -10, 0), 20, 20, 8)
hole = sm.create_sphere((0, 0, 8), 7)
result = sm.boolean_difference(body, hole)
materials = {"result": {"baseColor": [0.85, 0.24, 0.12], "metallic": 0.65, "roughness": 0.3}}
```

複数の完成形状は `objects` 辞書で明示します。値には BRep または `Group` を指定できます。`Group` はエディタ内で自動提供される Python 側の補助クラスです。通常の Python ファイルからは `from modeler import Group` で利用できます。カーネルの `sm` API とは別に、表示・保存用の構成を定義します。

```python
objects = {
    "assembly": Group({
        "base": sm.create_box((0, 0, 0), 10, 8, 2),
        "detail": Group({
            "post": sm.create_cylinder((5, 4, 2), 1, 6),
        }, material={"baseColor": [0.8, 0.8, 0.8], "metallic": 0.8}),
    }, material={"baseColor": [0.2, 0.5, 0.8]},
       scale=(1, 1, 1), euler=(0, 0, 30), position=(10, 0, 0)),
}
materials = {"post": {"baseColor": [1, 0.3, 0.1]}}
```

`Group(objects, *, material=None, scale=(1,1,1), euler=(0,0,0), position=(0,0,0), invisible=False)` は入れ子にできます。子の変換後、親の変換を適用し、各段は scale → X/Y/Z Euler回転（度）→ position の順です。scale は各成分が正の有限数、euler・position は有限数3個です。変換は評価時に完成 BRep へ適用します。Boolean はグループ化の前に BRep 同士で実行してください。`Group` 自体は Boolean の引数にはできません。`invisible=True` を指定すると、子グループを含むソリッドの計算を行いつつ、プレビューと GLB／USDZ の描画出力から除外します。値は bool で指定します。

材質の優先順は形状への `materials` 指定 → 最も近い子グループ → 親グループです。`materials` には形状名とグループ名の両方を指定でき、同じグループの `material=` を置き換えます。辞書の記述順には依存しません。材質はプロパティ単位ではなく材質全体を置き換え、省略プロパティは既定値になります。プレビュー、GLB、USDZ に共通で反映されます。

形状名・グループ名は全体で一意な英数字・アンダースコアの識別子（先頭は英字またはアンダースコア）です。辞書のキーを名前に使い、変数名は使いません。同じ BRep を複数箇所に登録せず、配置ごとに新しい BRep を作ってください。`objects` を定義するとそれを出力として優先し、作業用変数は表示しません。`result = Group({...})` も使用でき、その最上位グループ名は `result` になります。`objects` がなく `result` が BRep の従来コードはそのまま動作し、`result` もなければ最後の BRep 変数を使います。

GLB・USDZ は group 階層と各 group のローカル TRS を再帰的に保持します。各 BRep は個別メッシュとして所属 group の下に配置し、名前と材質を保持します。Pythonサンプルは `examples/python_groups.py` と読み込み用の `examples/python_groups.json` です。`make glb MODEL=examples/python_groups.json` と `make usdz MODEL=examples/python_groups.json` で再生成できます。

追加プリミティブの Python 名は各テキスト命令に `create_` を付けたものです。例えば `sm.create_ellipsoid((0, 0, 0), 8, 5, 3)`、`sm.create_cone((0, 0, 0), 4, 0, 7)`、`sm.create_partial_torus((0, 0, 0), 6, 1, 0, 180)` と書けます。

## 材質

材質は完成したソリッド名かグループ名に指定します。`material グループ名 R G B metallic roughness` は子グループと `use` の形状を含め、個別指定のない形状に適用します。グループ内でも `end` の後でも指定できます。個別指定はグループ指定より優先し、子グループ指定は親グループ指定より優先します。`baseColor` は線形 RGB の3値、`metallic` と `roughness` はそれぞれ1値で、いずれも `0` から `1` の範囲です。省略したソリッドには既定の水色の材質を使います。Boolean 演算で作った形状には、演算後の名前を指定してください。GLB と USDZ に PBR 材質として保存されます。ブラウザのプレビューは three.js の `MeshStandardMaterial` で同じ値を使い、環境マップなしの平行光と環境光で照らします。

