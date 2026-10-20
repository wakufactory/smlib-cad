# SMLib Modeler

テキスト命令または Python コードで BRep を作り、ブラウザでプレビューして GLB または USDZ に保存するローカルツールです。形状生成とテッセレーションには、同梱の `usd-brep` ソースから作る **USD 非依存** の `_smlib_core` Python 拡張を使います。USDZ はテッセレーション済みメッシュから直接生成し、`pxr` API は使いません。

## ビルドと起動（Apple Silicon）

このフォルダーで実行します。Xcode Command Line Tools、Python 3.12（開発用ヘッダーを含む）、`uv` と pybind11 2.11.1 が必要です。`Makefile` は `usd-brep` 内の `SMLib`・`SM_API`・`SmPyCore` のソースを直接コンパイルして、Python 拡張 `_smlib_core` を作ります。

```bash
uv pip install --target .deps/pybind11 pybind11==2.11.1
make start
```

`Makefile` は `.packman-cache/python/` に Python 3.12 があればそれを再利用し、なければ PATH 上の `python3.12` を使います。別の Python 3.12 を使う場合は `make start PYTHON=/path/to/python3.12` を指定します。Packman・Premake・OpenUSD のインストールは、このツールのビルドには必要ありません。

`make start` は必要なネイティブ拡張とローカルHTTPS証明書を用意し、全IPv4インターフェース（`0.0.0.0`）でサーバーを起動します。`make start-https` も同じ起動方法です。このMacでは `https://localhost:8765`、同じLAN内の端末では `https://<MacのLAN内IPv4アドレス>:8765` を開きます。MacのIPv4アドレスは「システム設定 → ネットワーク」で確認できます。停止は起動した端末で Ctrl+C を押します。

ポートを変えるには `make start PORT=8766` を指定します。HTTPが必要な場合は `make start-http` を使いますが、USDZ の `<model>` プレビューには信頼済みHTTPS接続が必要です。`Makefile` は `SMLib`、`SM_API`、`_smlib_core` を arm64 用の単一 Python 拡張に直接リンクします。以下のテスト・サンプル中の `python3.12` も、ビルドに使った Python の実行ファイルに合わせてください。

このMacからのみアクセスできるようにする場合は、待ち受け先を明示します。

```bash
make start HOST=127.0.0.1
```

通常起動では、LANからアクセスした端末もPythonコードを実行できます。認証はないため、信頼できるLANだけで使い、ルーターのポート転送などでインターネットに公開しないでください。macOSのファイアウォールが接続を確認した場合は、利用するネットワークでの着信を許可する必要があります。

### HTTPS と USDZ の `<model>` プレビュー

初回起動時に `.certs/` にローカルCAとサーバー証明書を生成します。証明書には `localhost`、`127.0.0.1`、起動時に検出したMacのIPv4アドレスを含めます。別のLANアドレスを追加する場合は `make start CERT_IP=192.168.1.20` と指定してください。CAは保持し、必要なアドレスが増えた場合はサーバー証明書のみ更新します。

接続するApple端末には `.certs/local-ca.mobileconfig` をAirDropなどで渡してインストールし、SSL/TLS用に信頼してください。iPhone・iPad・Vision Proではインストール後に「設定 → 一般 → 情報 → 証明書信頼設定」でルート証明書の完全な信頼を有効にします。Macでは `.certs/local-ca.crt` をキーチェーンに追加して信頼します。`.certs/local-ca.key` と `.certs/server.key` は共有しないでください。これらはGitの対象外です。

画面右側の「プレビュー方式」で「USDZ `<model>`」を選ぶと、現在のモデルを「保存時の座標倍率」を適用したUSDZとして再計算し、同じサーバーから配信して表示します。「プレビュー」でも再計算できます。対応していないブラウザや信頼済みHTTPSでない接続ではWebGL表示を使ってください。`<model>` は対応版のSafariで動作し、表示・操作はブラウザ側に委ねられます。

ネイティブバインディングの確認（ビルドに使った Python 3.12 を指定）:

```bash
PYTHONPATH="$PWD/.build/smlib-core" \
  python3.12 \
  -m unittest discover -s usd-brep/source/SmPyCore/tests -v
```

`_smlib_core` は下記のプリミティブに加え、Boolean、全エッジ加工、`face_info`、`offset_brep`、`shell_brep`、`transform_brep`、`tessellate` を公開します。楕円球は球を中心から X/Y/Z 方向へ拡大縮小した BRep です。USD は使いません。引数・戻り値・所有権の契約は [ツール境界 API 仕様](usd-brep/docs/smlib-core-tool-api.md) を参照してください。

## チャットでモデルを編集

右ペイン下部の「モデル編集チャット」に指示すると、現在のソース・入力モード・モデルの設定を Codex 経由で GPT に送り、返ってきたソースをエディタに反映してプレビューします。テキスト命令と Python の両方に対応します。質問への回答だけの場合はソースを変更しません。

「画像を添付」で参考画像・図面・スクリーンショットを選択できます。PNG・JPEG・WebPを1回に3枚まで、各2 MiB以下で添付でき、送信前にサムネイルを確認・削除できます。画像だけを添付して送信することもできます。画像は指示と現在のソースに添えてGPTへ渡し、履歴にも表示します。画像だけでは確定できない実寸はGPTから確認するよう指示しています。

添付画像は会話の `images`（`name` と `dataUrl`）としてモデルJSONにも保存・復元します。保存する履歴内の画像データはbase64形式で合計12 MB、モデルJSON全体は16 MBまでです。復元した履歴の画像は、次の送信時に画像入力としてCodexへ渡し直します。サーバーは画像形式・サイズを検査し、Codexの一時作業フォルダーへ画像を展開して渡し、処理終了時に削除します。

GPTへの指示では、実寸を想定するモデルの座標・寸法は **1 = 1 m** とし、mm・cmで指定された寸法はmへ換算してソースに記述させます（例：10 mm → 0.01）。

サーバーのMacに Codex CLI、または CLI を同梱する ChatGPT / Codex アプリが必要です。PATH 上の `codex`、次にアプリ内のCLIを検出します。別の場所にある場合は起動時に `CAD_CODEX_BIN=/absolute/path/to/codex make start` を指定します。モデルは Codex の既定値を使い、必要なら `CAD_CODEX_MODEL=<利用可能なモデルID> make start` で指定できます。

1. `make start` で起動し、ブラウザで開きます。
2. チャット欄の「ChatGPT にログイン」を押し、表示されたリンクを**サーバーのMacのブラウザ**で開いて認証します。OAuth のコールバック先はそのMacの localhost です。LANの別端末からCADを開く場合も、初回認証はMac側で行ってください。
3. 「ChatGPT 接続済み」になったら指示を送ります。ログイン後の認証状態は自動確認し、必要なら「接続確認」で再確認できます。

ChatGPT OAuth でログインした Codex の利用枠を使います。APIキーによる呼び出しへの自動切り替えは行いません。LAN用の追加認証はなく、利用枠はサーバーでログインしたアカウントのものです。

「停止」は進行中の応答を中断します。「変更を戻す」は直前にチャットの変更を反映する前のソース・入力モードへ戻し、再プレビューします。応答待ちの間にソースを手動編集・読込した場合は自動上書きせず、変更案を保留します。「変更案を反映」を押すと現在のソースを置き換え、その直前の内容を取り消し用に保持します。生成に失敗したソースも編集欄に残り、エラーを次の送信に添付するため、「このエラーを直して」と依頼できます。

会話はタブごとに分かれます。「JSON を保存」で、会話があればモデルJSON内の任意項目 `chat`（`version: 1` と `messages`）へ保存します。各メッセージには `role`（`user` / `assistant` / `system`）、`text`、必要に応じて `error: true` を記録します。表示中の直近100件を対象とし、履歴の合計は20万文字、モデルJSON全体は16 MB以下です。ログイン情報やCodexの内部スレッドIDは含めません。

「JSON を読み込む」で会話表示も復元し、次の送信でその履歴を新しいCodex会話の文脈に添えます。現在のモデルソースを正として送るため、元のCodex内部スレッドや過去のソース全文を復元する方式ではありません。`chat` を含まない従来のJSONは会話なしとして読み込み、その前に開いていたモデルの会話をクリアします。不正な履歴はソース・会話とも変更せずに拒否します。チャット応答中は、完了または停止してからJSONを読み込んでください。

「新しい会話」、ページの再読込、サーバー再起動で現在の会話を切り替えます。保存したJSONを読み込めば履歴を復元できます。1サーバーで最大8会話を保持し、1時間使われていない会話は後続の新規会話作成時に終了します。

Codex は専用の `CODEX_HOME`（既定 `.build/codex-chat/`、`CAD_CODEX_HOME` で変更可能）と一時作業フォルダーで起動します。普段の Codex の設定・会話・メモリを読み込まず、メモリ機能・シェル・プラグインなども無効にします。既存のCLIでログイン済みでも、この専用環境では初回ログインが必要です。認証情報は専用フォルダーにCodex自身が保存するため、共有しないでください。Codexの会話は ephemeral とし、CAD側の会話履歴はJSON保存時以外はメモリ内だけに保持します。

Codex との通信はローカルの app-server の標準入出力を使用します。Codex にファイル編集を任せず、構造化された返信（説明とソース全文）を受け取り、CADがエディタへ反映します。Pythonモードのプレビューは従来どおりローカルPythonコードを実行します。

Codexの実行権限は専用の `cad-chat` プロファイルで指定し、読み取り先を一時作業フォルダーと最小限の実行環境に限定します。書き込みとツールからのネットワーク接続は許可しません。旧形式の `readOnly.access` は送信しません。

## 入力

「テキスト命令」は 1 行に 1 命令を書きます。`#` 以降はコメントです。単位は任意ですが、モデル内では統一してください。

「保存ファイル名」に名前を入力してから JSON・GLB・USDZ の保存ボタンを押します。拡張子は形式に応じて自動で付きます。入力名の末尾が `.json`、`.glb`、`.usdz` の場合は、選んだ形式の拡張子に置き換えます。「保存時の座標倍率」に正の数値を入れると、GLB・USDZ の全頂点座標を原点基準でその倍率にして保存し、USDZ `<model>` プレビューにも同じ倍率を適用します。たとえばモデルの単位を mm としている場合、`0.001` で座標値を m に換算できます。倍率 `1` は従来と同じ座標値です。法線、テッセレーション精度、WebGL プレビューには影響しません。「JSON を保存」を押すと、現在のテキスト命令またはPythonコードと、曲面精度・角度条件・全体加工・幅/半径・保存時の座標倍率を保存します。「JSON を読み込む」でそのファイルを選ぶと、入力モード・コード・各設定が復元され、自動でプレビューが更新され、保存ファイル名には読み込んだJSONの名前が入ります。JSON が壊れている場合や未対応の形式の場合は、編集中の内容を変更せずにエラーを表示します。

ファイル形式は UTF-8 のJSONです。`format: "smlib-model"`、`version: 1`、`mode`（`"text"` または `"python"`）、`source`、`parameters` を持ちます。`parameters.exportScale` を持たない従来のJSONは倍率 `1` として扱います。PythonモードのJSONを読み込んでプレビューする場合や `make glb` / `make usdz` で変換する場合、保存されたPythonコードが実行されます。

保存したJSONをGLBへ変換するには `make glb` を実行します。必要なら `_smlib_core` もビルドします。既定の入力は `model.json` で、同じ場所に `model.glb` を作ります。別の入力や出力先には `MODEL` と `GLB` を指定できます。モデル定義と全体パラメータは画面の「GLB を保存」と同じ処理に渡されます。

```bash
make glb
make glb MODEL=design.json
make glb MODEL=design.json GLB=outputs/design.glb
```

USDZ は画面の「USDZ を保存」、または保存済みJSONから `make usdz` で作成できます。既定の入力は `model.json`、出力は同じ場所の `model.usdz` です。出力先の変更には `USDZ` を指定します。

```bash
make usdz
make usdz MODEL=design.json USDZ=outputs/design.usdz
```

USDZ はプレビュー・GLB と同じテッセレーション結果を Z-up の USD Mesh として保存し、各形状の色・metallic・roughness を UsdPreviewSurface 材質に設定します。元の BRep や編集用のモデル定義は含まれません。USDZ は非圧縮で、テキスト形式の `model.usda` を格納するため、大きなモデルでは GLB よりファイルサイズが増えます。座標値には指定した保存時の倍率を掛け、USD上の単位は 1 = 1 m として記録します。

```json
{
  "format": "smlib-model",
  "version": 1,
  "mode": "text",
  "source": "box body 0 0 0 10 10 10\n",
  "parameters": {"chord": 0.08, "angle": 20, "finish": "none", "finishSize": 1, "exportScale": 1}
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
| `profile` / `polygon` / `spline` / `end` | `profile 断面名` 内に `polygon u1 v1 ...` または `spline through u1 v1 ... closed` を1行記述して `end` で閉じる |
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
| `tessellation` | `形状名 曲面精度 角度条件`（形状別。各値に `default` を指定すると UI 設定を使用） |

Web UI の左ペインにある「テキストコマンド一覧」でも書式を参照できます。一覧だけをスクロールでき、右側のモデル定義を見ながら編集できます。初期状態では閉じています。見出しを押すと開閉できます。

### 変数・式・繰り返し

テキスト命令では `let 名前 = 式` で数値変数を定義し、数値引数や形状名に `${式}` を埋め込めます。式で使えるのは有限な数値、定義済み変数、`+`、`-`、`*`、`/`、括弧です。式内には空白を入れられます。`let` は定義した行以降で有効です。同じスコープで同名を再定義するとエラーになります。

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

1つのループは最大512回、`for` と `if` の入れ子は最大32段、展開後は空行を含め最大20,000行です。未定義変数、ゼロ除算、有限でない結果、許可していない式は行番号付きのエラーになります。変数・ループ・条件分岐はテキスト命令専用で、Python モードには影響しません。

### 押し出しと回転体

`profile` は穴なしの閉じた断面です。`polygon` は重複を除いた3〜1024頂点の `(u, v)` を直線で結び、最後から最初への辺は自動で閉じます。同じ点を複数回書いた場合は、最初の1回だけを残して以降を無視します。`spline through` は4〜64組の通過点を指定し、`closed` を末尾に付けます。各点を通る3次スプラインが最後から最初へつながります。同じ通過点を隣接して2回書くと、その位置で接線が折れます（例: `... 4 0  4 0 ...`）。3回以上の連続や、異なる点が4個未満の輪郭は拒否します。末尾に始点を再記載した場合は閉じ指定として取り除きます。どちらも時計回り・反時計回りを受け付け、自己交差、自己接触、重なり、ゼロ面積を拒否します。スプラインの検査は各区間16分割のサンプルに基づきます。穴付き断面は未対応です。

```text
profile section
  polygon 0 0  18 0  18 0  18 5  6 5  6 16  0 16
end
extrude bracket section 0 0 0 -3 3

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

`revolve` は断面の `(u, v)` を `(半径, 高さ)` として使い、原点を通る軸の周りに右ねじ方向へ回転します。半径は0以上で、軸への接触を許可します。`0 < 終了角 - 開始角 <= 360`、部分回転は開始・終了の端面を閉じ、360度は全回転になります。`wall` は穴のない長方形断面ですが、軸から離れているため全回転すると中空の筒になります。

軸 `dx dy dz` の既定は +Z、長さは形状に影響しません。横方向 `ux uy uz` は押し出しのローカル+X／回転角0度の半径方向を指定し、軸に垂直な面へ投影して正規化します。ゼロベクトルや軸に平行な横方向はエラーです。横方向を省略した場合は、既存プリミティブと同じ +Z から軸への最短回転を使います。横方向だけ指定したい場合は軸も明記します。

多角形とスプラインの断面は生成後も再利用できます。グループ内の断面はそのグループと子グループで参照でき、`part` 内でも定義・利用できます。`use` は呼び出し位置で見える断面を継承し、各部品内の定義はその部品だけで有効です。断面は使用する命令より前に定義してください。グループの変換は生成したBRepに適用します。生成結果には既存の Boolean、材質、面取り・丸めを適用できます。

Python API でも同じ形状を生成できます。入力点列と `Profile` は生成で変更されません。

```python
section = sm.create_profile([(0, 0), (18, 0), (18, 5), (6, 5), (6, 16), (0, 16)])
result = sm.create_extrude(section, (0, 0, 0), -3, 3)
# 半径・高さ断面を +X 軸の周りに回す。角度0の半径方向は +Y。
wall = sm.create_profile([(5, 0), (9, 0), (9, 12), (5, 12)])
result = sm.create_revolve(wall, (0, 0, 0), 30, 270, axis=(1, 0, 0), xdir=(0, 1, 0))
smooth = sm.create_spline_profile([(2, 0), (4, 0), (5, 1), (5, 3),
                                   (4, 4), (2, 4), (1, 3), (1, 1)])
result = sm.create_extrude(smooth, (0, 0, 0), 0, 2)
result = sm.create_revolve(smooth, (10, 0, 0), 0, 360)
```

画面の「押し出し・回転体・スプライン」→「読込」で、折線断面の押し出しと回転体3形状、スプライン断面の押し出しと回転体2形状を読み込めます。ソースは `examples/extrude_revolve.txt`、JSONモデルは `examples/extrude_revolve.json`、生成済みGLBは `outputs/extrude_revolve.glb` です。再生成は `make glb MODEL=examples/extrude_revolve.json GLB=outputs/extrude_revolve.glb` で行います。

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

Web 画面のプレビュー・GLB・USDZ 生成はリクエストごとに別プロセスで実行します。形状カーネルが異常終了してもサーバは動作を続け、画面に生成エラーを表示します。計算が 120 秒を超えた場合もエラーを返します。

### 球の陰影と曲面精度

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

Boolean 命令は右側の入力形状を消費します。複雑なモデルには「Python コード」を選び、`_smlib_core` を `sm` として利用してください。完成形を `result` に代入します。

```python
body = sm.create_box((-10, -10, 0), 20, 20, 8)
hole = sm.create_sphere((0, 0, 8), 7)
result = sm.boolean_difference(body, hole)
materials = {"result": {"baseColor": [0.85, 0.24, 0.12], "metallic": 0.65, "roughness": 0.3}}
```

追加プリミティブの Python 名は各テキスト命令に `create_` を付けたものです。例えば `sm.create_ellipsoid((0, 0, 0), 8, 5, 3)`、`sm.create_cone((0, 0, 0), 4, 0, 7)`、`sm.create_partial_torus((0, 0, 0), 6, 1, 0, 180)` と書けます。

材質は完成したソリッド名ごとに指定します。`baseColor` は線形 RGB の3値、`metallic` と `roughness` はそれぞれ1値で、いずれも `0` から `1` の範囲です。省略したソリッドには既定の水色の材質を使います。Boolean 演算で作った形状には、演算後の名前を指定してください。GLB には glTF の PBR 材質として保存されます。ブラウザのプレビューは three.js の `MeshStandardMaterial` で同じ値を使い、環境マップなしの平行光と環境光で照らします。

「プレビュー」で再計算します。WebGL プレビュー左上の投影方式で「平行投影」（初期値）と「透視投影」を切り替えられます。視点の向きとホイール／ピンチによるズームは切替後も引き継がれ、モデルの再計算は不要です。投影方式はブラウザの下書きに保存されます。プレビュー右上の表示切替で `Shading`（PBR 材質と照明）、`Wireframe`（テッセレーション後の三角形の辺）、`面法線 RGB` を切り替えられます。`面法線 RGB` は各三角形の面法線を座標から計算し、X・Y・Z 成分を R・G・B に対応させ、−1～+1 を 0～1 の色に変換します。照明や材質の影響は受けません。プレビュー右側で XYZ 軸（X=赤、Y=緑、Z=青）を表示・非表示にできます。左ペイン最下部でグリッド点を表示・非表示にでき、間隔（正の数値）、平面（XY・YZ・ZX）、法線軸座標を指定できます。法線軸はそれぞれ Z・X・Y で、初期値は間隔1、XY 平面、Z=0 です。変更はモデルの再計算なしでプレビューに反映されます。モデルが大きい場合、グリッド点はモデル中央付近の最大 101×101 点に制限します。これらの表示設定はブラウザの下書きに保存され、再プレビュー後も保たれます。これらの表示は WebGL プレビュー専用で、USDZ `<model>` プレビューや GLB・USDZ の保存データには反映しません。`Shading` の光は画面左上側からの平行光で、視点を回しても画面上の方向は固定です。表示切替時の再計算は不要です。描画には CDN から読み込む three.js 0.186.1 を使うため、ブラウザから `cdn.jsdelivr.net` へ接続できる必要があります。GLB は保存時にも同じソースから再計算するため、プレビュー後に編集した場合は最新の内容が保存されます。GLB は glTF 標準の Y-up 座標へ変換します。Python コードは任意のローカルコードとして実行されます。信頼できるコードだけを入力し、LAN公開時の注意事項は上の「ビルドと起動」を確認してください。

### 全プリミティブと材質のサンプル

画面上部で「全プリミティブ」を選び「読込」を押すと、`examples/all_primitives_materials.txt` がテキスト命令として読み込まれます。15種類を5列×3行に並べ、各形状に固有の `baseColor`、`metallic`、`roughness` を割り当てています。平面と平面円も含みます。生成済み GLB は `outputs/primitive_gallery/all_primitives_materials.glb`、材質・三角形数の対応は同じフォルダーの `manifest.json` にあります。

4気筒エンジンブロック風の CSG サンプルは `examples/inline_four_engine_block.json` にあります。テキスト命令でシリンダー穴、クランク軸トンネル、ボルト穴、側面ポートなどを構成し、生成済みの `outputs/inline_four_engine_block.glb` と再生成手順を `outputs/inline_four_engine_block.README.md` に置いています。

`part`、`group`、`let`、`for` を使う円形配置のサンプルは `examples/circular_csg_array.txt` と、画面へ読み込める `examples/circular_csg_array.json` にあります。1 個のクランプ定義を `for i in range(count)` で6回 `use` し、子グループの半径方向への移動と親グループの `i * 360 / count` 度の回転で円周上に並べます。6色の材質指定はループ後に個別に書いています。各クランプは結合・穴あけ・スリット切り抜きの CSG です。中央のカラーも CSG です。画面の「円形 CSG 配置」→「読込」でも開けます。生成済みの `outputs/circular_csg_array.glb` と構成の説明は `outputs/circular_csg_array.README.md` にあります。GLB の再生成には `make glb MODEL=examples/circular_csg_array.json GLB=outputs/circular_csg_array.glb` を使います。

サンプルの GLB を再生成するには、ワークスペースのルートで実行します。

```bash
PYTHONPATH="$PWD/.build/smlib-core:$PWD" \
  python3.12 \
  examples/export_primitive_gallery.py
```

## 検証

回転軸上に断面の点を置くことは有効です。円錐の先端など、法線が一意に決まらない特異点では、SMLibの多角形生成時に各多角形が接する方向から曲面法線を評価してコーナーごとに保持します。`_smlib_core` によるテッセレーション後の全メッシュ補正は不要です。先端1点に全周共通の法線を割り当てないため、内壁の片側だけ陰影が反転する問題を防ぎます。再現・確認用の断面は `examples/revolve_cone_tip.txt` にあります。`make test-pole-normals` はPythonを通さず、PolyBrepと6種類の描画コールバック、全回転・部分回転、Z軸・X軸の法線を検証します。

プレビューと GLB の三角形化は共通です。穴なしの凸・凹多角形を面の2D投影上で耳切り法により分割し、その後、隣接する2三角形の最小角が改善する場合だけ内部の対角線を交換します。角度は元の3D座標で評価し、同品質の対角線は交換しません。境界・頂点数・三角形数・コーナー法線を保持します。頂点追加や最適品質の保証は行わないため、形状によっては細長い三角形が残ります。入力は自己交差のない単一輪郭を前提とし、分割できない面はエラーにします。穴の輪郭を持つ面の分割は未対応です。

```bash
PYTHONPATH="$PWD/.build/smlib-core:$PWD" \
  python3.12 \
  -m unittest discover -s tests -v
PYTHONPYCACHEPREFIX=/tmp/cad-pycache \
  python3.12 \
  -m py_compile modeler.py server.py codex_bridge.py json_to_glb.py json_to_usdz.py
node --check app.js
node --check chat.js
node tests/test_model_file_ui.js
node tests/test_preview_guides.js
node tests/test_chat_ui.js
```

このテストはJSONモデルの往復と不正値の拒否、テキスト命令・三角形化・GLB 構造、追加プリミティブのネイティブ生成と楕円球の寸法・Boolean を確認します。チャットのテストは代替app-serverを使い、実モデルの利用枠を消費せずに会話の分離、停止、エラー、ソース反映・取り消し・手動編集との競合を検証します。実際のモデルによる編集にはChatGPTログインが必要です。ネイティブバインディング単体のテストは上記の Python 3.12 コマンドで実行します。

編集内容は同じブラウザ・同じ接続先のローカルストレージに自動保存されます。リロード時にソース、入力モード、設定、保存ファイル名、表示設定を復元し、モデルがあればプレビューを再生成します。「クリア」の空状態も保持します。途中の入力やエラーのある定義も保存します。チャット履歴・添付画像はこの自動保存に含みません。ブラウザの保存領域を消すと失われるため、持ち出しやバックアップには「JSON を保存」を使ってください。
