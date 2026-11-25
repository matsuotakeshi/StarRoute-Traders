# StarRoute Traders CI（軽量版、2026-11-17）

通常はFreeBSD 10.0.0.50 / Python 3.12だけで既存unittest全件、CLI、隔離Telnet UI・探索試遊を実行する。
ゲームロジックのテストは削除・縮小していない。長時間の実航行試遊もFreeBSDでは維持する。

| workflow | 起動 | 内容 | 必須 |
|---|---|---|---|
| FreeBSD Regression (`starroute-ci.yml`) | PR / 手動 | 全回帰＋CLI＋実Telnet | `StarRoute / FreeBSD required` |
| Linux Compatibility | 手動、Linux変更・Linuxリリース前 | Rocky上の選択テスト＋短いTelnet/PTY Door試験 | 該当変更のレビューで確認 |
| Debian Compatibility | Debian固有変更時に手動 | Debian子機上の同じ限定試験 | 通常必須ではない |
| Extended Tests | 手動 | hosted OS 1つ・Python 1つを選択して全回帰 | 通常必須ではない |

Python対応は3.10以上。通常は3.12、追加バージョンは必要時だけ選ぶ。WindowsもExtended Testsで選択する。
Solarisは未対応・対象外。通常のhosted全回帰マトリクスは廃止した。

## Linux範囲

`ci/run_tests.py --suite compatibility` の明示リストを使う。import・CLI起動、SQLiteのパス/ロールバック/再読込、
保守バックアップ、アクセス権、シグナル・プロセス終了、共有ロック・切断、端末サイズ/ANSI、thin client importを確認する。
`ci/door_smoke.py` は既存Liner fixtureを隔離ビルドし、実Telnet登録、Door起動、NAWS 80→70桁、終了、
再入場、Ctrl-]、BBSへの復帰を短時間で確認する。ゲームの交易・航行全シナリオはLinuxで繰り返さない。
Linuxの配布形式・インストール/サービス管理は未整備であり、これらを合格扱いにしない。
変更パスだけではLinux依存性を確実に判別できないため、自動パスフィルターは設けず手動を採用した。
Linux関連変更ではマージ前に該当Linux証跡を確認する（GitHub全PR必須にはしない）。

## 操作と省資源

Actionsでworkflowを選び、mainを指定してRun workflowを実行する。
Linux/Debian/Extendedは必要な対象だけ選ぶ。通常はmainの手動workflowを使用する。
マージ前のLinux関連変更は、信頼済みの対象コミットを専用作業領域に配置し、
同じnative supervisorと共有VMロックを利用して確認する。試験起動だけのコミットは作らない。

同一コミットの成功済み結果は再利用する。既存のrun URL、SHA、JSONを先に確認する。
main pushでは全回帰を再実行しない。mainの直接pushで未検証変更を入れず、PRの必須チェックを通す。
リリース等で最終main SHAの証跡が必要な場合はworkflow_dispatchを使用する。
PRの仮マージSHAとmain SHAは異なるため、PR成功をmain実行済みとは報告しない。
新コミットでは同じworkflow/branchの古い実行・待機をcancel-in-progressでキャンセルする。
自動再試行や自動修正ループはない。原因不明の失敗が続く場合はログと調査結果を報告して停止する。

## 安全・結果

10.0.0.54の既存StarRoute runner (`starroute-native`) を利用。Debian子機は `ci-test@10.0.0.59` に `/home/ci/.ssh/id_ed25519_debian_ci` で接続し、親機の `ci` ユーザーの `known_hosts` に登録したホスト鍵を照合する。
Liner用runner、本番、root管理admission hookは変更しない。
各VMの `~/ci/.liner-notes-native.lock` で別プロジェクトとも排他。待機中もheartbeatで中止を検知する。
一時パス・DB・ポートはStarRoute専用。終了時はSHAマーカーが一致する自分のrunだけを削除する。
外部/未信頼PRは自宅runnerでは実行しない。required gateはskipも失敗にする。
レビュー済み変更を所有者の同一repoブランチへ移して検証する。`pull_request_target` は使わない。

結果はActionsのSummaryと30日保持artifact。`results.json` にSHA・OS・Python・件数・所要時間・状態、
`tests.json` に失敗テスト名・traceback・exit_code。コマンド失敗時の終了コードはOS別logにも残る。
SSH失敗・結果未生成も成功扱いにしない。branch protectionは新チェック1件をGitHub Actions appに紐づけて必須にする。

## 直前の成功証跡

v0.21.0 `96f2b37e0bd1a92c337692ed3dc205d38d7908d8`:
https://github.com/matsuotakeshi/StarRoute-Traders/actions/runs/42590614375
旧構成の3OS各599件、Windows589件＋POSIX専用10skipが成功。これを再試験せず保持する。
