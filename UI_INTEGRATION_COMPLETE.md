# 星図・航行・交易情報・航路開拓 UI統合改善

2026-11-09。直前の探索実装 `starroute-traders-exploration-20261109` を基準とした独立作業コピー。
正式な版番号変更、GitHubへのPush、本番更新、新しいFreeBSD/Linux配布パッケージの作成は行わない。

## 実装と操作

### 星図

- 上端X・左端Yに宇宙の絶対座標を表示。5マス間隔の目盛りと船の現在位置 `POS X=… Y=…` を別領域に配置する。
- 240×120の既存座標系、緑の船・停泊惑星、英語惑星名、名称切り替え、NAWSによる可変サイズを維持する。
- メインの `V` → `1` → X → Y で閲覧位置を移動。`2` は船への追従に戻す。直接 `chart 239 119` も使用可能。
- これは閲覧のみ。船の位置、所持金、探索到達結果を変更しない。装置がなくても利用でき、取得済みの公開星図だけを描画する。
- 装置所有者は `V` → `3` で閲覧位置を航行先候補へ渡せる。既存のモード選択・見積もり・確認を経由する。航行中は候補からの新規出発を拒否する。
- 座標入力の0は座標0。`:cancel` または `back` で戻る。`M`・`?`・`Q` も利用可能。自由命名の大文字小文字は変更しない。

### 航行

- 通常/ワープ/座標航行の確認に、出発地点、目的地点、方式、距離、所要時間、到着予定時刻、燃料費、所持Crを表示する。全て既存エンジンの計算結果を使用する。
- 長い確認内容は `>` で最後まで閲覧し、`Y` で出港してメイン星図へ戻る。`N` は取消してメインへ、`0` は前の選択へ戻る。
- 航行中は現在座標、出発地点、目的地、方式、保存済み到着予定時刻（UTC）、残り時間を表示。再接続後も同じ保存状態を使用する。
- 出港時に噂を得た場合は、取得済み手帳に記録されたことを通知する。
- 空間からの帰還候補は既存の既知通常惑星一覧を利用。画面には航行計算に使うマンハッタン距離を表示する。近接探索ヒントに使う既存のチェビシェフ距離・判定は変更しない。
- 通常航行0 Cr、座標航行速度係数、ワープ費用、航行中のゲーム操作制限、ログアウト時の航行保存を維持する。

### 交易と履歴

- 購入・売却の両画面に単価、販売在庫、買取可能数量、保有数量、貨物空き容量、売買可能数量を分けて表示する。約定後に市場情報と残高を再取得する。
- メインの `B` または `history` で本人の当クール取引台帳を新しい順に閲覧できる。日時、惑星、商品、売買種別、数量、最初/最後の単価、総額を表示する。
- 数量別価格の取引を単一の固定単価に見せない。既存の台帳を変更せず、既存のFIFO集計と同じ確定済み売買を表示する。
- `N/P` は画面内のページ、`O` はさらに古い20取引。履歴APIは認証済み本人・対象クールに限定し、他人のID指定や無制限件数を拒否する。公開キャッシュ対象に追加しない。
- 取引ごとのFIFO利益は既存台帳の公開値にないため新規計算しない。既存 `score` のクール合計利益を利用する。

### 航路開拓・情報

- 寄付一覧・対象詳細・確認・結果に、起終点、距離、実際の寄付累積Cr、開拓効果、必要効果、開通までの残り支払Cr、開通状態を表示する。
- 残り支払Crは現在の船の工作船ボーナスと既存の端数繰越を反映する。通常船と工作船で残り支払額が異なる場合がある。
- 実際の支払いと開拓効果を混同しない。更新は既存の共有DBトランザクション・Request ID処理を使用する。別BBSも同じ開通状態を取得する。
- 開通後の航行候補と見積もりは既存の航路参照を使用し、航行中の保存済み行程は変更しない。直接探査や新しい自動多段経路機能は追加しない。
- 情報手帳は既存の取得順逆順・重複保持・真偽非公開を維持。取得日時をUTC表示し、噂本文を狭い端末でも折り返す。保険加入メッセージと日英言語切替を維持する。

## 設定と互換性

- 新しい `examples/exploration-operations.json` は、探索対応宇宙に世界全体で7200秒ごとの災害抽選を設定する。暫定確率は100 bps（1%/抽選）、災害種別の重みは均等。市場の通常相場更新周期とは別項目。
- 従来の `examples/exploration-trial.json` は変更しない。短時間試遊設定と運用候補を明確に区別する。新テンプレートは共有ルールと正規化ハッシュに含まれる。
- 新規クールの標準期間を暫定365日（31,536,000秒）に揃える。開始済み・準備済みクールの保存済み期間や終了日時は書き換えない。
- テンプレートは新しい宇宙の生成時だけ指定する。現在稼働中の宇宙に自動適用しない。既存の保存済みゲームルール・設定ハッシュを変更しない。
- SQLiteスキーマ11を維持し、移行処理・初期化は追加しない。既存台帳、資産、価格、船性能、探索機能を維持する。
- API差分は公開可能な距離・到着時刻・寄付進捗の追加と、本人限定 `trade_history` 読み取り操作。新UIは対応するマスターと組み合わせる。古いマスターとの新機能互換は保証しない。
- Portsのファイル一覧には新規Pythonモジュールを追記したが、パッケージ作成・インストール・本番配布は実施しない。

## 検証と証跡

実行結果と合否は `verification/ui-integration-20261109/acceptance.json`、変更一覧は `changed-files.json` に記録する。
Windowsの全体ログ・最終UI再検証・探索/交易CLIログ、FreeBSDの全体ログ・最終UI再検証・実Telnet出力を同じ証跡ディレクトリに保存する。

| 環境 | 全体テスト | 最終変更の再検証 | 重複を除く確認済みテスト |
|---|---|---|---|
| Windows / Python 3.14.7 | 578件、577成功・POSIX専用1件対象外 | 関連57件成功 | 579件、578成功・1件対象外 |
| FreeBSD 15.1-RELEASE / Python 3.12.15 | 578件すべて成功 | 関連57件成功、最終表示16件成功 | 579件すべて成功 |

元の560件に19件を追加した。全体テスト開始後に共通キー確認を1件追加したため、最終件数は全体実行と追加確認の集合で算出している。失敗・エラーは両環境とも最終0件。
Windowsの対象外1件はPOSIXの権限・シンボリックリンク検査であり、FreeBSDでは成功している。

探索CLIは生成・検証・登録・有効化、装置/ギルド、座標航行、ログアウト・到着後再接続、日英混在の個人名、幻の星での売買、通常惑星への帰還を確認した。
交易CLIは2区間で5,000 Cr→5,492 Cr、全貨物売却済みを確認した。両環境で一致する。
実TelnetはスタンドアロンとTLS Inter-BBSのDoor起動・売買・WHO・BBS復帰を確認し、スタンドアロンでは航行・投資・寄付・再接続・ANSI/モノクロ・Ctrl-]・NAWS 80/100/70/50桁も確認した。
複数BBSの共有在庫、同一Request ID、本人履歴、共有航路開通はTLSクライアントの自動統合テストで確認した。DBのintegrity_check/foreign_key_checkも成功した。

実端末の記録（ANSI原文も同じディレクトリに保存）:

- [日本語メイン画面](verification/ui-integration-20261109/freebsd/screens/main-ja.txt)
- [宇宙端の座標ジャンプ](verification/ui-integration-20261109/freebsd/screens/chart-edge.txt)
- [船へ追従を戻した星図](verification/ui-integration-20261109/freebsd/screens/chart-follow.txt)
- [購入時の在庫・買取枠・保有数](verification/ui-integration-20261109/freebsd/screens/buy-quantity.txt)
- [売却時の数量](verification/ui-integration-20261109/freebsd/screens/sell-quantity.txt)
- [本人の取引履歴](verification/ui-integration-20261109/freebsd/screens/trade-history.txt)
- [航路の寄付進捗](verification/ui-integration-20261109/freebsd/screens/donation-progress.txt)
- [出港確認](verification/ui-integration-20261109/freebsd/screens/warp-confirm.txt)
- [航行中の星図・ETA](verification/ui-integration-20261109/freebsd/screens/flight.txt)
- [50桁の縦配置](verification/ui-integration-20261109/freebsd/screens/naws-50.txt)

初期検証のログも保持した。解消済みの内容は、旧単体テストの呼び出し時のimportパス、軸の予約領域に合わせた旧描画テストの期待位置修正、新規テストの航路ID取得方法、デモの出港成功メッセージ判定である。実画面で見つけた航行中の初心者案内も修正し、最終Telnet試遊を再実行した。最終判定には `windows-tests.txt` / `windows-final-ui3.txt` / `freebsd/tests.log` / `freebsd/final-ui.log` / `freebsd/final-view.log` / `freebsd/telnet-final.log` を使用する。

保護対象のローカル基準226ファイルと、元のFreeBSD Liner notes検証環境301ファイルはSHA-256照合で不変を確認した。今回のFreeBSD検証先は `/home/takeshi/starroute-ui-integration-verification-20261109`。

再現コマンド（新しい隔離用ディレクトリを指定）:

```sh
python3.12 -m unittest discover -s tests -v
python3.12 scripts/exploration_demo.py --directory /path/to/NEW-exploration-demo
python3.12 scripts/trade_cycle_demo.py --directory /path/to/NEW-trade-demo
python3.12 scripts/ui_integration_telnet_demo.py --directory /path/to/NEW-telnet-demo --liner /path/to/isolated-liner-copy --template examples/market-buyback-trial.json
```

Telnetデモは複製したLiner notesをループバックに限定して起動する。検証専用の資金・短縮時間を用いる。
本番Liner notes、サービス、設定、ゲームDB、認証情報の変更は行わない。

## 残る仕様確認と次期引き継ぎ

1. 災害発生率1%と種別比率、クール365日、航路外速度係数は調整可能な暫定値。正式バランスの確定とは区別する。
2. 個々の取引のFIFO利益表示は、台帳に原価配賦結果を公開する設計が必要になった段階で検討する。今回は合計成績を維持する。
3. 履歴の別クール切替、検索、日付範囲指定は今回追加しない。既存の過去クール成績は従来機能で参照する。
4. UI追加コマンドに対応するサーバーとクライアントの配布・本番導入は別作業。新pkg、WebUI、新船種、商品正式確定、直接航路探査は対象外。
