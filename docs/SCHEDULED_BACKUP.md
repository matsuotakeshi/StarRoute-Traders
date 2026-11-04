# StarRouteの定期バックアップ

`scripts/scheduled_backup.py`はPython 3.10以上と標準SQLiteで動作する独立ツール。既存pkg・ゲームエンジン・DBスキーマの変更は不要。cronの自動登録や本番データへの自動復元は行わない。

## 保存するもの

- SQLite backup APIによる確定済みDBのスナップショット。稼働DBがWAL方式でも、保存先は単体で復元できるDELETE journal方式にする。生のDBファイルのコピーは使わない。
- 設定で明示したファイル（Door設定、参照鍵、サイト設定、Door登録、起動ラッパー）。ディレクトリ全体を無差別に収集しない。
- SHA-256、保存時刻UTC、元パス・所有者ID・モードのmanifest。設定値や秘密鍵の内容をログに出さない。

これはStarRoute用であり、Liner notes全体の会員・掲示板データのバックアップではない。署名用VMのpkg署名秘密鍵も収集対象に含めない。追加ファイルは`files`に明示する。複数DBを一つの整合した状態で保存する用途は対象外。

FreeBSDでは保存先を実行ユーザー所有・0700、保存ファイルを0600にする。暗号化はしないため、秘密鍵を含むバックアップを公開Web・GitHub・共有フォルダーへ置かない。WindowsではPOSIXモードによる保護を保証せず、運用する場合は別途NTFS ACLを設定する。

## 初回配置（本番は管理者が実施）

`scheduled_backup.py`と`scheduled-backup.example.json`を既存経路で`/root/`へ転送する。以下は同じshで実行する。既存ツールや設定があれば上書きせず停止する。

```sh
/bin/sh
set -eu
umask 077
test ! -e /usr/local/libexec/starroute-ops/scheduled_backup.py
test ! -e /usr/local/etc/starroute-traders/backup.json
install -d -m 0755 /usr/local/libexec/starroute-ops
install -m 0555 /root/scheduled_backup.py /usr/local/libexec/starroute-ops/scheduled_backup.py
install -m 0600 /root/scheduled-backup.example.json /usr/local/etc/starroute-traders/backup.json
```

設定の全パスが存在することを確認する。サンプルの保存先は`/var/backups/starroute-traders`、保持は**14成功世代**、DB取得タイムアウトは120秒。暫定運用値であり変更可能。14日という意味ではなく、手動実行分も世代に数える。保存先に十分な空き容量を用意する。

まず削除なしで実行する。既存Doorと同じPythonを使うことを基本とし、今回のFreeBSD環境ではPython 3.12を確認している。

```sh
/usr/local/bin/python3.12 -I /usr/local/libexec/starroute-ops/scheduled_backup.py run \
  --config /usr/local/etc/starroute-traders/backup.json
```

成功時に`status: ok`と`snapshot`パスが表示される。その実パスを使って検査・復元試験をする。以下のSNAPSHOTは表示結果に置き換える。

```sh
SNAPSHOT=/var/backups/starroute-traders/snapshot-実際の保存世代
/usr/local/bin/python3.12 -I /usr/local/libexec/starroute-ops/scheduled_backup.py verify --snapshot "$SNAPSHOT"
RESTORE_PARENT=$(mktemp -d /root/starroute-restore-check.XXXXXX)
/usr/local/bin/python3.12 -I /usr/local/libexec/starroute-ops/scheduled_backup.py restore-copy \
  --snapshot "$SNAPSHOT" --destination "$RESTORE_PARENT/restored"
/usr/local/bin/starroute-maintain --db "$RESTORE_PARENT/restored/game.db" check
```

restore-copyは新規ディレクトリだけを受け付け、既存DB・ディレクトリを上書きしない。復元した`game.db`と番号付き設定ファイルの対応はmanifestで確認する。元の所有権は記録するが自動適用しない。

## 定期実行

初回バックアップと復元確認後に、rootの`crontab -e`へ次の1行を追加する。既存crontab全体を置換しない。実行頻度は例として毎日03:15、**サーバのローカル時刻**に従う。日本時間を前提にせずsrvの`date`で確認する。

```cron
15 3 * * * /usr/local/bin/python3.12 -I /usr/local/libexec/starroute-ops/scheduled_backup.py run --config /usr/local/etc/starroute-traders/backup.json --prune
```

標準出力にはJSONの結果1行が出る。cronメールを管理者が受信できるようにするか既存監視へ収集し、非ゼロ終了・成功世代が24時間以上増えない状況・空き容量を監視する。異常通知の配送先はこのツールでは新設しない。ログを無制限に追記するcron例にはしていない。

`--prune`指定時だけ、新規保存と検証の成功後に古い世代を削除する。ツールの形式・ハッシュ・DB整合性を確認できない世代や、無関係なディレクトリは削除しない。破損世代があると世代削除を停止して非ゼロ終了する。この場合、新しい正常世代が既に作成されている可能性がある。

## 異常時と復旧

- 二重実行：OSのファイルロックで拒否する。プロセス終了時にロックは解放される。`.backup.lock`を実行中に削除しない。
- 容量不足、設定ファイル欠落、SQLite検査失敗、取得タイムアウト：非ゼロ終了。完了世代を公開せず、以前の世代は削除しない。
- `.pending-*`は失敗時の未完了データ。復元元に選ばず、実行中でないことと原因を確認してから管理者が整理する。
- 各世代は`integrity_check`と`foreign_key_check`を確認する。ハッシュは破損検出であり、攻撃者によるmanifestの改変に対する署名ではない。
- 通常の売買と並行してSQLiteスナップショットを取得できるが、設定・鍵の変更、DBファイル置換、宇宙切替・移行とは同時実行しない。設定ハッシュの前後比較でも変化を検出するが、複数ファイルとDBを一つのトランザクションにする機能ではない。
- 本番復元はゲーム更新停止、最新状態の退避、restore-copy検証、対象宇宙・クール・互換ルール確認後に別途実施する。自動で現在のDBへ戻さない。復元時点より後の確定済み取引を失う可能性を確認する。

同一ディスクの定期保存だけではディスク故障に対応できない。検証済み世代を別媒体へ保管する運用は別途必要。転送先・暗号化・保管期間は管理者が決める。
