/* Model and animation command reference shown in the left pane. */
(() => {
  'use strict';
  document.getElementById('command-reference-content').innerHTML = `<div class="command-list" tabindex="0" role="region" aria-label="テキストコマンド一覧">
<h3>モデル定義</h3>
<p>通常1行に1命令。行末の <code>\\</code> で次の行へ接続。<code>#</code> 以降はコメント。<code>[…]</code> は省略可能な引数です。名前は英字・下線で始め、英数字・下線を使います。角度は度数です。</p>
<p><code>x y z</code> は位置、<code>dx dy dz</code> は軸方向（省略時は +Z）、<code>ux uy uz</code> は断面のX方向です。</p>
<dl><div class="command-entry"><dt><code>box</code></dt><dd><code>名前 x y z 幅 奥行 高さ</code></dd></div>
<div class="command-entry"><dt><code>sphere</code></dt><dd><code>名前 x y z 半径</code></dd></div>
<div class="command-entry"><dt><code>cylinder</code></dt><dd><code>名前 x y z 半径 高さ [dx dy dz]</code></dd></div>
<div class="command-entry"><dt><code>cone</code></dt><dd><code>名前 x y z 底面半径 上面半径 高さ [dx dy dz]</code>（上面半径 <code>0</code> で円錐）</dd></div>
<div class="command-entry"><dt><code>torus</code></dt><dd><code>名前 x y z 主半径 管半径 [dx dy dz]</code></dd></div>
<div class="command-entry"><dt><code>pyramid</code></dt><dd><code>名前 x y z 底面の辺長 高さ [dx dy dz]</code></dd></div>
<div class="command-entry"><dt><code>cylindrical_box</code></dt><dd><code>名前 x y z 高さ 内半径 外半径 開始角 終了角 [dx dy dz]</code></dd></div>
<div class="command-entry"><dt><code>partial_sphere</code></dt><dd><code>名前 x y z 半径 開始角 終了角 [dx dy dz]</code></dd></div>
<div class="command-entry"><dt><code>partial_cone</code></dt><dd><code>名前 x y z 底面半径 上面半径 高さ 開始角 終了角 [dx dy dz]</code></dd></div>
<div class="command-entry"><dt><code>partial_cylinder</code></dt><dd><code>名前 x y z 半径 高さ 開始角 終了角 [dx dy dz]</code></dd></div>
<div class="command-entry"><dt><code>partial_torus</code></dt><dd><code>名前 x y z 主半径 管半径 開始角 終了角 [dx dy dz]</code></dd></div>
<div class="command-entry"><dt><code>ellipsoid</code></dt><dd><code>名前 x y z X半径 Y半径 Z半径</code></dd></div>
<div class="command-entry"><dt><code>sphere_no_pole</code></dt><dd><code>名前 x y z 半径</code></dd></div>
<div class="command-entry"><dt><code>plane</code></dt><dd><code>名前 x y z X長さ Y長さ</code>（面）</dd></div>
<div class="command-entry"><dt><code>planar_circle</code></dt><dd><code>名前 x y z 半径</code>（面）</dd></div>
<div class="command-entry"><dt><code>profile</code> / <code>polygon</code> / <code>spline</code> / <code>end</code></dt><dd><code>profile 断面名</code> 内に <code>polygon u1 v1 ...</code>、または <code>spline through u1 v1 ... closed</code> を1行記述して <code>end</code> で閉じる。polygon の同じ点は最初だけ残す。スプラインは通過点4〜64組。同じ点を隣接して2回書くと角になる</dd></div>
<div class="command-entry"><dt><code>extrude</code></dt><dd><code>名前 断面名 x y z 開始距離 終了距離 [dx dy dz [ux uy uz]] [draft 角度]</code>。正の角度は内向き、負は外向き。省略時は直線押し出し</dd></div>
<div class="command-entry"><dt><code>revolve</code></dt><dd><code>名前 断面名 x y z 開始角 終了角 [dx dy dz [ux uy uz]]</code>（度数）</dd></div>
<div class="command-entry"><dt><code>union</code> / <code>subtract</code> / <code>intersect</code></dt><dd><code>出力名 左の形状名またはグループ名 右の形状名またはグループ名</code></dd></div>
<div class="command-entry"><dt><code>chamfer</code></dt><dd><code>形状名 幅</code>（その形状の全エッジを面取り）</dd></div>
<div class="command-entry"><dt><code>fillet</code></dt><dd><code>形状名 半径</code>（その形状の全エッジを丸め）</dd></div>
<div class="command-entry"><dt><code>offset</code></dt><dd><code>形状名 距離</code>（正は外側、負は内側）</dd></div>
<div class="command-entry"><dt><code>shell</code></dt><dd><code>形状名 厚み [開口面の番号 ...]</code>（正は外側、負は内側。面指定なしは閉じた中空体）</dd></div>
<div class="command-entry"><dt><code>faces</code></dt><dd><code>形状名</code>（現在の面番号と各面の座標範囲をログへ表示）</dd></div>
<div class="command-entry"><dt><code>material</code></dt><dd><code>形状名またはグループ名 baseColorのR G B metallic roughness</code>（グループ指定は個別指定のない形状へ適用）</dd></div>
<div class="command-entry"><dt><code>part</code> / <code>end</code></dt><dd>ルート階層で <code>part 部品名</code> から <code>end</code> までを再利用可能な定義にする</dd></div>
<div class="command-entry"><dt><code>use</code></dt><dd><code>use 部品名 [配置名]</code> で部品を新しく生成する</dd></div>
<div class="command-entry"><dt><code>group</code> / <code>end</code></dt><dd><code>group 名前</code> から <code>end</code> までをローカル座標のグループにする。入れ子可</dd></div>
<div class="command-entry"><dt><code>include</code></dt><dd>group 内で <code>include 既存group名</code> と書き、定義済みgroupを子として移す</dd></div>
<div class="command-entry"><dt><code>property key value</code></dt><dd>group の GLB カスタムプロパティ（extras）を設定。value は JSON 形式（文字列は二重引用符）、同じキーは上書き</dd></div>
<div class="command-entry"><dt><code>invisible</code></dt><dd>group 内に引数なしで指定し、子グループを含めて非表示にする。ソリッド計算は実行する</dd></div>
<div class="command-entry"><dt><code>scale</code></dt><dd>グループ内で <code>scale sx sy sz</code>（各軸の正の倍率）</dd></div>
<div class="command-entry"><dt><code>euler</code></dt><dd>グループ内で <code>euler rx ry rz</code>（度数）</dd></div>
<div class="command-entry"><dt><code>quaternion</code></dt><dd>グループ内で <code>quaternion x y z w</code>（有限・非ゼロ、自動正規化）。同じgroupのeulerと排他。<code>quaternion dquaternion(x, y, z, 度数)</code>で軸と角度も指定可能</dd></div>
<div class="command-entry"><dt><code>position</code></dt><dd>グループ内で <code>position x y z</code>（親座標での移動）</dd></div>
<div class="command-entry"><dt><code>let</code></dt><dd><code>let 名前 = 式</code>（数値変数。<code>\${式}</code> を数値引数や形状名に埋め込める）。<code>pi</code>、<code>e</code>、<code>sin</code> / <code>cos</code> / <code>tan</code>（ラジアン）、<code>asin</code> / <code>acos</code> / <code>atan</code> / <code>atan2</code>、<code>exp</code>、<code>log</code>、<code>sqrt</code>、<code>abs</code>、<code>radians</code> / <code>degrees</code> が使える</dd></div>
<div class="command-entry"><dt><code>fn</code></dt><dd><code>fn 名前(引数, ...) = 式</code>（数値を返す計算関数）。例: <code>fn area(r) = pi * r * r</code> → <code>\${area(5)}</code>。定義時の変数・関数を保持。定義以降で使用可。再帰不可</dd></div>
<div class="command-entry"><dt><code>for</code> / <code>end</code></dt><dd><code>for i in range(回数)</code> または <code>range(開始, 終了[, 刻み])</code>。<code>end</code> で閉じる。終了値を含まない</dd></div>
<div class="command-entry"><dt><code>if</code> / <code>end</code></dt><dd><code>if 式</code>。式が0以外なら <code>end</code> までを展開する。<code>let</code> と同じ数値式を使用</dd></div>
<div class="command-entry"><dt><code>tessellation</code></dt><dd><code>形状名 曲面精度 角度条件</code>（形状ごとの指定。曲面精度は 0.001〜2、角度は 1〜90。<code>default</code> でUI設定を使用）</dd></div></dl>
<p>例：穴のある箱</p>
<pre>box body 0 0 0 20 20 8
cylinder hole 10 10 -1 3 10
subtract result body hole</pre>
<p>Boolean は左右の入力を消費し、出力名に結果を作ります。材質の RGB・metallic・roughness は 0〜1。グループの変換は scale → 回転（euler / quaternion）→ position の順です。</p>

<h3>アニメーション定義</h3>
<p>右側の「アニメーション」タブに記述します。テキスト命令・Python の両モードで共通です。時刻は秒、回転は度、座標は対象グループのローカル座標です。<code>#</code> 以降はコメントです。</p>
<dl>
<div class="command-entry"><dt><code>animation loop 秒数</code> / <code>end</code></dt><dd>全体を囲むブロック。モデル全体で1つ、周期は <code>0 &lt; 秒数 &lt;= 1000</code>。内部に <code>track</code> を記述します。</dd></div>
<div class="command-entry"><dt><code>track グループ名</code> / <code>end</code></dt><dd>出力に残るグループを対象にします。形状はグループで包んでください。同名グループは <code>assembly/rotor</code>、ルートからの指定は <code>/assembly/rotor</code> のようにパスで区別します。非表示・空・Booleanで消費されたグループや対象の重複指定はエラーです。</dd></div>
<div class="command-entry"><dt><code>key 秒数 position|euler|scale X Y Z</code></dt><dd>1行に1チャンネルのキーを記述します。チャンネルごとに時刻を厳密に増やし、0秒と終端のキーが必要です。移動はモデルの座標単位、Euler回転は度、拡縮は正の倍率。省略時は移動・回転が <code>0 0 0</code>、拡縮が <code>1 1 1</code> です。各成分を線形補間し、回転の <code>360</code> は1回転、<code>720</code> は2回転になります。</dd></div>
<div class="command-entry"><dt><code>cycle position|euler|scale 秒数</code></dt><dd><code>track</code> 内でチャンネルごとの周期を指定します。そのチャンネルは0秒と周期の終端までのキーだけを書き、全体の秒数は各周期の整数倍にします。未指定のチャンネルは全体の終端までキーが必要です。両端の値・姿勢が異なっていても指定できます。移動・拡縮は周期の境界で開始値へジャンプします。回転差分は周期ごとに累積します。同じチャンネルへの重複指定やキーのない指定はエラーです。</dd></div>
<div class="command-entry"><dt><code>for 変数 in range(...)</code> / <code>end</code></dt><dd><code>track</code> 内でキーを繰り返し生成します。<code>range(回数)</code>、<code>range(開始, 終了[, 刻み])</code> に対応し、終了値を含みません。内部には <code>key</code> と入れ子の <code>for</code> のみ記述できます。ループ変数は時刻・値の式で使えます。展開後もチャンネルごとの時刻を増やし、境界のキーを重複させないでください。長時間の同じ動きの反復には <code>cycle</code> を使います。</dd></div>
<div class="command-entry"><dt>数式・<code>let</code>・<code>fn</code> の参照</dt><dd>周期・キー時刻・各値・<code>range</code> の引数には数式が使えます。テキストモデルのトップレベルの <code>let</code>・<code>fn</code> と数学関数・定数を参照できます。例：<code>key 4 euler 0 0 \${360 * 2}</code>。空白を含む式は <code>(式)</code> または <code>\${式}</code> で囲みます。モデル内のローカル定義やPythonの変数・関数は参照できません。</dd></div>
</dl>
<p>例：グループ <code>rotor</code> を2秒で1回転させ、全体で4秒のループにする</p>
<pre>animation loop 4
  track rotor
    cycle euler 2
    for i in range(3)
      key i euler 0 0 \${i * 180}
    end
  end
end</pre>
<p>モデルをプレビューした後、「設定を適用」で反映し、「再生」で確認できます。静的なグループ変換にアニメーションTRSを合成し、グループのローカル原点を中心に動かします。ループ両端の値・姿勢が異なるキーも指定でき、境界でのジャンプを許容します。上限は256トラック・4096キー・120,000生成サンプルです。設定はJSONへ保存され、動きはGLB・USDZへ書き出せます。</p>
</div>`;
})();
