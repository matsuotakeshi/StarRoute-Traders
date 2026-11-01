> v0.6.0では世界ID追加に伴いDBスキーマ5へ移行します。[CFG_FOUNDATION.md](CFG_FOUNDATION.md)を参照。以下はv0.5.0の設定整理の説明です。

# v0.5.0 設定ファイル

## ファイルと役割

- `starroute/config/runtime.json`: デフォルト言語と各設定ファイルの場所。
- `starroute/config/game.json`: 新しい宇宙のゲームパラメータ。初期資金、船の容量・航続距離・速度、船種・グレード、商品・市場・航路、登録済みの船価・保険・航行時間・燃料費を含みます。
- `starroute/config/inter-bbs.json`: Inter-BBS専用。現在は `format_version: 1`, `enabled: false`, `bbs_id: null`。
- `starroute/presentation/locales/ja.json`, `en.json`: 表示文言、エラー、名称の翻訳。
- `starroute/presentation/schema.json`: 翻訳の検証用定義。通常編集する必要はありません。

`runtime.json` の `default_language` を `ja` または `en` に変更します。優先順位は **起動時の --lang > プレイヤーが language コマンドで保存した言語 > default_language** です。起動時の上書きは保存しません。設定変更は次の起動から反映します。

独自設定を使用する例:

```sh
python3.12 -m starroute --settings /path/to/runtime.json --db data/universe.db --player captain
```

runtime.json の game_file、inter_bbs_file、language_files のパスは、その runtime.json が置かれたディレクトリ基準です。絶対パスも使用できます。外部へコピーする場合は参照先も合わせて変更してください。従来の引数なし設定での起動、--lang、--config も使用できます。

## 互換性

DBスキーマは4のままです。既存DBに保存されたゲーム設定が引き続き有効で、game.json の変更は新しく作る宇宙にだけ適用します。既存宇宙に --config で異なるゲーム設定を指定すると、従来通り拒否します。データの初期化・自動上書きは行いません。

旧 starroute/data/demo.json は互換用のサンプルとして残しています。新しい標準参照先は config/game.json です。初期値は従来と同一です。

通常航行・係留無料という確定ルールや、データ破損を防ぐ整数上限は任意変更する調整パラメータではありません。未確定のワープ計算式や船価を新しく決めてはいません。examples/phase3b-trial.json は引き続き試遊専用の暫定値です。

## 言語ファイル

両言語ファイルを起動時に検証します。既存のメッセージキー、波括弧内の変数名、数値の書式指定は維持してください。商品等の表示名は names で変更できます。独自ゲーム設定ですでに変更した名称は尊重します。欠落キー、重複キー、不正な書式はDBを開く前に拒否します。対応言語は今回 ja/en の2言語です。

## Inter-BBS

通信プロトコル・接続先・認証方式は未確定であり、今回通信処理は実装しません。enabled=true は未実装エラーになります。bbs_id に識別子を設定しても、CLIのローカルプレイヤーIDや既存BBSアカウントは書き換えません。接続先や認証情報の項目は仕様確定後に追加します。

## 検証

設定ファイル読込み、相対パス、言語の優先順位、翻訳変更、不正設定の拒否、既存宇宙のパラメータ維持、旧 --config の不一致拒否を自動テストに追加しています。FreeBSD実測結果は同梱の検証レポートを参照してください。
