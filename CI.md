# StarRoute Traders 継続検証

## 対象と標準運用

導入基準はGitHub main `8b6e741ded16301bae2bced4463013b8f55c6c14`、v0.20.0。
Python要件は3.10以上、現行ゲームのunittestは496件。CI自身の検査も追加して自動発見する。
直前までのローカル探索/UI改修をこのCI導入へ混在させない。ゲームロジック、DB、パッケージ、本番配備は変更しない。

1. PRごとに `.github/workflows/starroute-ci.yml` のGitHub-hosted Ubuntu/Python 3.10・3.14とWindows/Python 3.14を実行する。
2. 固定チェック **`StarRoute / Required`** が成功するまでmainへマージしない。ブランチ保護にこの名称を登録する。欠落・キャンセル・失敗は成功にならない。
3. main更新とmain指定の手動実行では、10.0.0.54上のStarRoute専用登録runnerから3OSを並列検証する。固定チェック **`StarRoute / Native required`** は3OSすべてが成功した場合のみPASS。
4. リリース候補の昇格は同じmain SHAの両チェック成功を前提とする。所有者matsuotakeshiが同一リポジトリ内で作成したmain向けPRも3OSで検証し、Native requiredをmainの必須チェックにする。外部PRはhostedのみ検証し、そのままマージせず、レビュー済み変更を所有者の同一リポジトリ内PRへ取り込んで3OS検証する。
5. 手動実行もmain限定。任意ブランチの手動実行は許可しない。本番自動デプロイは実装しない。

## 設備と認証

| 役割 | 実行先 | 接続アカウント |
|---|---|---|
| Actions調整役 | Ubuntu 10.0.0.54 | 既存ciアカウント・StarRoute専用runner登録と作業ディレクトリ |
| 必須ネイティブ検査 | FreeBSD 10.0.0.50 | takeshi |
| 必須ネイティブ検査 | Rocky Linux 10.0.0.51 | ci-test |
| 必須ネイティブ検査 | Ubuntu 10.0.0.53 | ci-test |
| 将来互換性調査 | Solaris 10.0.0.52 | ci-test・必須ゲートに含めない |

既存の専用SSH鍵とknown_hostsを再利用し、BatchMode/IdentitiesOnly/StrictHostKeyCheckingを有効にする。
鍵をリポジトリ、Artifact、ログに含めない。GitHubジョブの権限はcontents:read、checkout後の認証情報保持は無効。
Linerのrunner登録・サービス・鍵を置き換えない。runner登録と作業領域は分離するが、OSのCIアカウントは既存設備を共用する。
相互に敵対するプロジェクトを隔離するためのVM/ユーザー境界ではない。将来その分離が必要なら専用ユーザーと限定SSH権限へ移行する。

## 公開リポジトリとself-hostedの境界

導入時のリポジトリ公開範囲はpublic。外部PRはGitHub-hostedだけで検証する。
YAMLのmain判定に加え、StarRoute専用runnerにはroot所有の起動前フックを配置する。
`ci/runner_admission.py` をcheckout外に設置し、repository/ref/event/SHAとWebhookイベント本文を照合する。
所有者の同一リポジトリ内PRは、作者・head/baseリポジトリ・対象main・PR番号とmerge refを照合して許可する。外部PR、他の作者、任意ブランチ、別リポジトリをcheckout前に拒否する。
フックはリポジトリからジョブ中に上書きしない。ポリシー更新は別途管理者作業とする。

公式根拠: [GitHub runner pre-job hooks](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/run-scripts)、[self-hosted runner security](https://docs.github.com/en/actions/reference/security/secure-use)。

## 実行内容

`python ci/run_tests.py --output /path/to/results` が、既存の `python -m unittest discover -s tests -v` と同じ自動発見方式で全件を実行する。
最低限Python 3.10、stdlib SQLite/SSL、Git、OpenSSHのssh-keygen署名機能、OpenSSLを事前確認する。pipの実行時依存追加は不要。
テスト件数・成功/失敗/エラー・スキップ理由・Python/SQLite/OpenSSL情報をtests.jsonへ保存し、失敗時に非0で終了する。
CLI交易デモ `scripts/demo.py` も実行する。時刻/乱数/通信障害は既存テストのManualClock・固定入力・障害注入を維持する。

既存496件には交易、相場、航行、投資、海賊、災害、保険、破産、クール、成績、SQLite移行・復旧・バックアップ、設定署名、TLSマスターと複数BBSの同期・切断・再送・権限、日英端末UIが含まれる。
StarRoute専用WebUIは現行mainに存在しないため、新規Web試験を捏造しない。既存HTTP/TLS API検査を継続する。

ネイティブでは追加で実Liner Notesを複製ビルドし、`scripts/bbs_ui_telnet_demo.py` によるTelnet/PTY/Doorの売買・航行・投資・寄付・日英・NAWS・BBS復帰・TLSクライアントを実行する。
Linerのテスト用ソースは `ci/native_ci.py:LINER_SHA` の不変SHAに固定する。BBSのmake checkをStarRouteのテストとして流用しない。
Linerをビルドするmake runtimeは独立したDoor受け入れ用fixtureに限る。3OSに必要なCコンパイラ、SQLite/OpenSSL開発ヘッダは既存CI設備を使用し、自動OS更新は行わない。

FreeBSD Ports/pkg定義と既存の保守ツール検査は維持するが、このワークフローは新しいpkg/RPM/DEBや署名リポジトリを公開しない。

## 排他・取消・データ保護

各VMの `~/ci/starroute/run-OS-ランダム値` に、git archiveで固定した同一コミットを転送する。
SHA-256を検証し、上位パス・絶対パス・シンボリックリンク等を拒否する。圧縮100MiB・展開300MiBを上限にする。
DB・鍵・ポート0で割り当てるループバックサーバー・ログはrunごとに独立する。

既存の `~/ci/.liner-notes-native.lock` を共用し、Liner/StarRoute間のネイティブ実行を排他化する。
ユーザー承認を受け、Liner側にも最大20分の競合待機を追加する。従来の即時拒否API、ロック名、make/check、認証は維持する。
StarRouteとLinerとも、待機中・実行中にEOF/heartbeat/キャンセルを監視する。中止時は自分の子プロセスグループだけを終了させる。
run完了後は結果を回収して、そのrunのSHAとパス・実行中ロックを確認してStarRoute一時領域だけを削除する。削除が安全に完了できなければCIを失敗にして対象を報告する。

## 成果物・調査・失敗対応

Actions Artifactは30日保持。hostedはtests.json、nativeはOS別ログ・Door結果・results.jsonを保存する。
source SHA、ソースアーカイブSHA-256、Liner fixture SHA、開始/終了時刻・所要時間・終了結果を確認できる。
ログは認証情報・実行時DB・非公開宇宙パッケージをArtifactへ含めない。
必須3OSの一つが失敗しても残りの結果回収を継続し、全体は失敗とする。

SolarisはPythonと依存関係の読み取り調査だけを先行する。WindowsのPOSIX権限・lock試験は理由付きskipとし、同じ試験をネイティブ3OSで実行する。
失敗を回避するために既存テストを削除・skipへ変更しない。実行URL・実測件数は導入完了報告で提示する。
