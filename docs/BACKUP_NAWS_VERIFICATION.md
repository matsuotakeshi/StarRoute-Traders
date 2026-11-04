# 定期バックアップ・端末サイズの検証記録

実施日：2026-11-03（日本時間）。本番srvではなく、ユーザー指定の検証VM 10.0.0.50で実施した。

## 成果物

- `scripts/scheduled_backup.py`：定期保存、明示的な世代削除、検証、別ディレクトリへの復元確認。
- `examples/scheduled-backup.example.json`：既存standalone配置向け設定サンプル。
- [定期バックアップ運用手順](SCHEDULED_BACKUP.md)：配置・cron・復元確認・障害対応。
- `scripts/liner_naws_probe.py`：隔離Liner notesでNAWS→PTY→StarRouteの寸法を直接測定する再現用試験。
- `verification/backup-naws-20261103/`：ログ、JSON結果、画面出力。

ゲームルール、DBスキーマ、pkg版、既存宇宙・航行速度は変更していない。以前作成した署名repo・配布ZIPも変更していない。ツールは次版pkgへの組み込み前の独立運用ツールとして提供する。

## バックアップ試験

| 環境 | 結果 |
|---|---|
| Windows / Python 3.14.7 | 10件成功、POSIX権限・symlink試験1件を対象外としてskip |
| FreeBSD 15.1 / Python 3.12.15 | 11件すべて成功 |

確認内容：WAL使用中の確定データ保存、未コミット変更の除外、二重実行拒否、成功後だけの世代削除、失敗時の既存世代保持、破損・パストラバーサル拒否、既存復元先の拒否、設定変更検出、0700/0600とsymlink拒否。

Windows初回試験ではsandbox一時領域のSQLite作成制約があったため、明示的なworkspace内TMPを使用した。その後、読み取り専用fdへのfsyncと、WALスナップショット検査時の副ファイル発生を修正。最終試験は成功している。

FreeBSDでは実際のStarRoute宇宙を別領域へ生成し、`-I`・最小環境変数でCLIを実行した。3回保存→2世代保持、verify、restore-copy、既存復元先への再実行拒否を確認。元DBと復元DBのSQLダンプは一致、元DBは不変。復元DBのゲーム保守検査はschema 11、rules_version phase3-complete-1、integrity ok。

全ゲーム485件の再実行はしていない。今回は新規バックアップ試験と既存の実Telnet統合シナリオを実行した。本番cronの登録や翌日の自動実行確認は未実施。

## 端末サイズの直接測定

隔離コピー元：`/home/takeshi/starroute-phase5-verification-20261102/final3/liner-isolated`

この検証用Liner notesには既に`door_resize`と`TIOCSWINSZ`の差分が存在した。新たに本番ソースへパッチを適用したわけではない。

新規試験領域：`/home/takeshi/starroute-backup-naws-verification-20261103`

実行バイナリSHA-256：`51ffa5e6ed1134b562691974d77d071ce8029600cbb578f5757b3106d7c52fa3`

| Telnet NAWS | 実PTYサイズ | StarRoute認識値 | 結果 |
|---|---|---|---|
| 80×24 | 80×24 | 80×24 | 成功 |
| 100×30 | 100×30 | 100×30 | 成功 |
| 70×24 | 70×24 | 70×24 | 成功 |
| 50×24 | 50×24 | 50×24 | 成功 |
| 80×24へ戻す | 80×24 | 80×24 | 成功 |

同じDoor接続中に変更し、固定したCOLUMNS=80/LINES=24環境変数よりも実PTYを優先することを確認。試験Door終了後、BBSへ復帰しPING応答も成功した。

既存の実ゲームTelnetシナリオでも、日英、売買・航行・到着・投資・寄付、WHO、再入場、Ctrl-]、ANSI/モノクロ、TLS Inter-BBSを確認。4サイズの画面出力が列数・行数内に収まることをassertし、`screens/naws-*.txt`へ記録した。

コピー元301ファイルのSHA-256は試験前後で一致。試験サーバはループバックの一時ポートだけを使い、終了時に停止。既存サービス・本番アカウント・本番DB・本番Door設定は操作していない。

## 本番への引き継ぎ

今回の結果は上記検証用バイナリについてのもの。本番srvのLiner notesへ同じNAWS→PTY差分が入っているとは断定しない。本番確認はユーザー指定により対象外。必要になったら、稼働バイナリの対応状況と実Telnet画面サイズ変更を別途確認する。

本番へのバックアップツール配置・cron追加も未実施。最初は削除なしで保存し、復元確認後に`--prune`を有効にする。Liner notes全体のデータバックアップや別媒体保管は、このStarRoute用ツールとは別の運用項目。
