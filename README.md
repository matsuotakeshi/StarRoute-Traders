> v0.19.0: BBS UI全面改修。常設星図・数字メニュー・対話型売買/航行/投資・日英・NAWS対応。[操作と配備手順](BBS_UI_COMPLETE.md)。本番適用は別途承認が必要です。

> v0.18.0: Phase 5。TLSマスターAPI、BBSサイト認証、日英Door、共有世界、設定診断、通信復旧、参加・離脱を追加。[Phase 5運用手順](PHASE5_COMPLETE.md)と[API仕様](docs/PHASE5_API.md)を参照してください。実測結果は独立したPhase 5受け入れチェックリストに記録します。Inter-BBS参加BBSには薄いクライアント配布物のみを使用してください。以下は履歴。

> v0.17.0: Phase 4の宇宙登録・クール・成績・殿堂・復旧。[Phase 4運用手順](PHASE4_COMPLETE.md)。

> v0.16.0: Phase 3統合実装。船販売・航路開拓・特殊イベント・災害・ニュース・保険/破産・星図・ローカル宇宙取り込み。[実装範囲と暫定仕様](docs/PHASE3_COMPLETE.md)。

# StarRoute Traders 0.15.0

v0.15.0で[外部生成器・独立した産業Lv・宇宙パッケージ](docs/DIRECTIVE_NO7.md)を追加。取り込み前の検証は独立ツールです。登録/有効化とBBS通信は未実装のままです。

v0.14.0で[集中型マスター方式のPhase 3基盤](docs/DIRECTIVE_NO6.md)を追加。公開情報の切り出し・対象ID確認・操作窓口・確定結果照会を整備しました。通信/認証はPhase 5です。本ソースと生成JSONはマスター管理者用で、BBS配布物ではありません。

v0.13.0で[48惑星・宇宙ジェネレーター](docs/UNIVERSE_GENERATOR.md)を追加。正式名称を採用し、配置/産出/航路は管理者が試遊設定から生成・保存できます。既存世界は自動変更しません。

v0.12.0で[産業開発による生産能力・市場容量への効果](docs/INDUSTRY_EFFECTS.md)を追加。新規試遊世界で有効化でき、旧世界の経済条件は維持します。

v0.11.0で[急騰/急落イベント](docs/MARKET_EVENTS.md)の再現・保存・価格統合を追加しました。

v0.10.0で[産出地からの距離による地域相場](docs/REGIONAL_PRICES.md)を追加しました。

v0.9.1で[燃料候補商品の試遊・航行費との独立性確認](docs/DIRECTIVE_NO4.md)を追加しました。

v0.9.0で[惑星別産出定義・生産能力・供給処理](docs/PRODUCTION.md)を追加しました。

追加指示書No.3の[惑星別生産・地域相場の開発計画](docs/DIRECTIVE_NO3.md)を登録しました（計画更新のみ）。

v0.8.0で[Phase 3Dの4産業投資・非公開上限・資源特性](docs/PHASE3D.md)を追加。新規試遊世界で使用できます。

v0.7.0で[Phase 3Cの台帳・数量別価格・市場需給](docs/PHASE3C.md)を追加。新規試遊DBで有効化できます。旧DBの価格方式は変わりません。

v0.6.0で[設定管理基盤CFG-01〜05](docs/CFG_FOUNDATION.md)を実装しました。config-infoで世界ID・設定版・SHA-256を表示できます。

追加指示書No.2の[実装照合・開発タスク](docs/DIRECTIVE_NO2.md)を登録しました（計画更新のみ）。

CLIで「惑星間を移動し、商品を売買して利益を得る」Phase 2の最小版です。
GFTの画面・名称・内部仕様の複製ではなく、共有宇宙交易の構造を発展させる土台です。
設計は [docs/DESIGN.md](docs/DESIGN.md)、実装状況は [docs/STATUS.md](docs/STATUS.md)。
2026-11-01の企画室追補を反映した[開発計画](docs/ROADMAP.md)を同梱しています。
Phase 3Bの通常航行・ワープ・燃料費・無料係留を追加しました。[仕様・確認事項](docs/PHASE3B.md)を参照してください。
既存の基盤整備は[FOUNDATION.md](docs/FOUNDATION.md)に記載しています。

## v0.5.0 設定の分離

ゲーム設定・Inter-BBS設定・日本語/英語ファイルを分離しました。デフォルト言語を変更できます。
[設定方法と互換性](docs/CONFIGURATION.md)を参照してください。既存DBのゲーム設定は自動変更しません。

## v0.4.0の追加機能

通常航行の追加料金・係留費は0 Cr。quote / warp / dock / voyageを追加。
正式な時間・燃料費式は未決定。既存DBのワープは設定未登録のため未有効。
試遊用の暫定設定を、別の新しいDBで試す例:

```sh
python3 -m starroute --db warp-trial.db --config examples/phase3b-trial.json --player captain
```

```text
register 船長
quote forge normal
quote forge warp fast
warp forge fast
wait
dock
voyage
```

試遊値は正式仕様ではありません。元DBにこの設定を適用しないでください。

## v0.3.0からの船モデル

- `ship` で船種・グレード・将来用性能モデルを日英で確認。
- 既存船の正式グレードや価格は未割当。従来の交易・航行性能を保持。
- 旧DBはバックアップ後にschema 4へ移行。旧版と元DBを保持して利用してください。
- 船購入・保険課金は後続段階です。ワープ航行はv0.4.0で追加しています。

## v0.2.0からの基盤機能

- `language ja` / `language en` でプレイヤー別言語を保存。`--lang en` は当該起動のみ上書き。
- `request buy-001 buy grain 10` は同一プレイヤー・同一クールで一度だけ実行。応答を失った際も同じID・同じ内容で再送可能。
- 旧DBは自動バックアップ後、トランザクション内でschema 4へ移行。旧版では移行後のDBを開けないため、戻す際は旧版とバックアップを組にして使用。
- BBS別識別は信頼されたAdapter向けAPIのみ。ネットワーク認証やDoor接続は未実装。

## 必要な環境

Python 3.10以降（sqlite3標準モジュールを含む）。ゲーム実行・テストの外部依存はありません。
v0.1.0はFreeBSD 15.1でも検証済み。v0.4.0の検証結果は同梱の検証報告を参照してください。
このフォルダで実行します。pip installは不要です。

```sh
python3 -m starroute --db ./universe.db --player takeshi
```

Windowsでpython3がない場合は、その環境のPython起動コマンド（例: py -3）へ読み替えてください。
初回だけ以下を入力します。

```text
register たけし
status
market
buy grain 10
routes
go forge
wait
market
sell grain 10
status
quit
```

星穀10個をオーロラで600 Crで買い、フォージで1,200 Crで売ると、
5,000 Crから5,600 Crへ増えます。航行は実時間で2秒です。
`quit`や切断後も確定済みの操作と航行はDBに残ります。
再開は同じ起動コマンド。再登録は不要です。

別のプレイヤーも、同じDBパスに別IDで接続すると共有世界に参加できます。
ハンドル名は重複できますが、内部IDは固有です。

```sh
python3 -m starroute --db ./universe.db --player second
```

単一コマンドも実行できます。正常終了コード0、入力/ゲームエラー1です。

```sh
python3 -m starroute --db ./universe.db --player takeshi --command status
```

## 自動デモとテスト

デモは一時DBとテスト時計を使います。遊んでいるDBには触れません。

```sh
python3 scripts/demo.py
python3 -m unittest discover -s tests -v
```

## 定義の変更

`starroute/data/demo.json`が試遊用の設定です。
コピーして初期資金、容量、商品、惑星、航路などを変更し、新しいDBで試せます。

```sh
python3 -m starroute --db ./custom.db --config ./custom.json --player takeshi
```

初回作成時に完全な設定をDBへ保存します。
既存DBは保存した定義を使い続け、異なる`--config`を渡すと拒否します。
商品は全惑星のmarket定義と組で追加してください。
航路は双方向です。同じ2惑星間の重複航路は登録できません。
production/volatility_bpsは将来用の定義で、この版では生産や価格変動は起きません。
船購入・交換・保険料の徴収はまだ実装していません。ワープ燃料費はv0.4.0で明示的設定表に従って支払います。

## 運用上の境界

これは信頼されたローカル利用向け試作です。`--player`は認証ではありません。
Liner notesへDoorとして公開する前に認証Adapterを追加する必要があります。
複数セッションは同一サーバ上のローカルSQLiteを共有してください。
DB書き込み権限のある利用者はDBへ直接アクセスできるため、OS権限で管理してください。
UTF-8の対話端末を想定し、Telnetプロトコル処理や旧文字コード変換は含みません。

バックアップは全セッションを終了して取得するか、稼働中はSQLite backupを使用します。
Python標準ライブラリで稼働中の整合したバックアップを取得する例:

```sh
python3 - <<'PY'
import sqlite3
source = sqlite3.connect('universe.db')
target = sqlite3.connect('universe-backup.db')
try:
    source.backup(target)
finally:
    target.close()
    source.close()
PY
```

試遊を最初からやり直す際は、別の新しいDBファイル名で起動してください。

## アーキテクチャ

CLIはApplicationの共通操作を呼び、Engineがルールを判定し、Repositoryが保存します。
Engineには表示・SQL・実時計を含めません。
将来WebはApplicationを直接呼び、CLIコマンドを経由しません。
現時点ではWeb/HTTPサーバ、Door連携、外部投稿機能は含みません。

## 今後の段階

- Phase 3: 相場変動・生産、航路寄付・開通・ジャックポット、事故・保険。
- Phase 4: ギルド、探索、ランキング、クール終了、殿堂。
- Phase 5: 認証付きDoor、Web Adapter。

試遊データは最終バランスではありません。価格固定のため有利な往復路があり、
長期投機や事故からの再起はまだ遊べません。次段階で市場変動とリスクを追加します。
