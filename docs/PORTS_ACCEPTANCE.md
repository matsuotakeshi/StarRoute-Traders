検証ログとpkgは [distribution/v0.20.0](../distribution/v0.20.0/) にあります。本書のverification/等はその成果物を基準とします。以下は初回検証完了時点の記録です。GitHubへの公開作業はPUBLICATION.mdを参照してください。本番移行の具体的なコマンドは [PKG_MIGRATION_V020.md](PKG_MIGRATION_V020.md) にあります。

# StarRoute Traders v0.20.0 — 指示書No.9 完了報告

検証日：2026年11月2日。プライベートPorts、用途別pkg、署名付きローカルrepo、安全な更新・復旧、長時間航行・世界イベントを実装し、独立したFreeBSD環境で検証しました。本番への適用、公開サービスの起動、GitHubへのPushは行っていません。

## 成果物

- `ports/`：3つのPortと設定例。具体的なコマンドは [運用手順](../ports/README.md)。
- `repo/All/`：v0.20.0の3種類のpkg。
- `repo/`：署名付きpkgリポジトリ。実際にfile://で取得・インストールを検証。
- `test-repository.pub`：検証用公開鍵。本番鍵ではありません。秘密鍵は含みません。
- `distfiles/starroute-traders-0.20.0.tar.gz`：固定版ソース、テスト、ビルドスクリプト。
- `rollback-test-packages/`：実際のv0.19.0ソースから作った復旧試験用pkg。既存の本番がpkg管理だったという意味ではありません。
- `verification/`：テスト、poudriere、pkg操作、Telnet画面、保護確認のログ。
- `acceptance-checklist.json`：受け入れ項目と根拠。
- `SHA256SUMS`：成果物のハッシュ一覧。

開発元はv0.19.0のコミット `c9e5c76d0fd9b57e869350bc22b088ed95aac514`。保護した元リポジトリとは別の作業コピーで実装しました。変更一覧は `verification/source-changes.json`。

## パッケージ構成

| Port | 内容 |
|---|---|
| games/starroute-traders-client | Door、端末UI、BBS側接続・運用機能。16ファイル。エンジン、宇宙DB、生成器、秘密鍵、マスター管理ツールなし |
| games/starroute-traders | 共通ゲームエンジン、独立生成器、管理CLI、保守CLI。対応版clientに依存 |
| games/starroute-traders-master | 共通基盤に依存し、rc.dとmaster設定例を追加 |

LocalDoorがマスター側の操作実装を共有するため、共通基盤にはそのPythonモジュールも含めます。薄いclientには含めません。インストールファイルの重複はありません。

`USES=python:3.10+,run`でPythonを選択し、起動スクリプトのパスはPortsの`PYTHON_CMD`から生成します。FreeBSDで別パッケージになるSQLiteは、対応する`py-sqlite3`を依存に登録しました。Webフレームワーク等の追加はありません。

プログラムは`/usr/local/libexec/starroute-traders/`、起動コマンドは`/usr/local/bin/`、設定例は`/usr/local/etc/starroute-traders/`。DB・鍵・ログはpkg管理外です。`@sample`を使い、編集した設定を維持します。

## 自動テストと実動作

| 対象 | 結果 | 根拠 |
|---|---|---|
| Windows / Python 3.14.7 | 485成功、失敗0、394.345秒 | verification/windows-tests-final.log |
| FreeBSD 15.1 / Python 3.12.15 | 485成功、失敗0、429.647秒 | verification/freebsd-tests-acceptance.log |
| 既存回帰 | 468件を維持 | 上記2ログ、既存テストファイルの変更なし |
| 新規 | 17件成功 | 上記ログのtest_ports_time |
| poudriere / FreeBSD 15.1-RELEASE-p6 amd64 | 3 Port成功、失敗0 | verification/bulk-020-sqlite.log、build/ |
| pkg実動作 / Python 3.12.13 | install、upgrade、info、delete、再install成功 | verification/pkg-*.log |
| インストール内容 | 実行コード69ファイルが検証済みソースと一致 | verification/package-audit.json |
| Telnet更新前・更新後 | standaloneとTLS Inter-BBSの双方で成功 | verification/telnet-019-final.log、telnet-020.log |
| rc.d | 非root起動、status、restart、stop、異常終了後の明示再起動成功 | verification/service-*.log |

poudriereは `poudriere-git-5ba8498`（ソースコミット `5ba849858d4040d824fb1419bc2dd260ca0a5928`）。ビルド環境のPythonパッケージは3.12.13_2、SQLiteモジュールはpy312-sqlite3-3.12.13_10です。全回帰テストを実施したVM側のPython 3.12.15と区別しています。

Telnetでは、pkgの`/usr/local/bin/starroute-door`を実際に起動しました。売買、航行と到着、投資、寄付、日英、WHO、ランキング、殿堂、BBSへの復帰、再入場、Ctrl-]、ANSI/モノクロ、80×24・100×30・70×24・50×24を確認。画面ログは `verification/screens/` にあります。Liner notes本体は専用の一般ユーザーで実行しました。

## 更新・復旧・削除

実際の旧版pkgで売買・投資・2クールの進行・殿堂保存を行ったDBを用意し、v0.20.0へ`pkg upgrade`しました。資金、貨物、宇宙定義、惑星開発、航路、クール、順位、殿堂、編集済み設定、鍵を更新前のハッシュと照合して一致を確認しました。

最終確認では市場在庫・価格を含むDB全39テーブルのSQLダンプと、設定・鍵・ログ等11ファイルも比較しました。旧版復旧・新版更新・削除・再インストールの全段階で一致しました（`verification/all-state-result.json`）。

次の異常・復旧を検証しました。

1. pkgの更新確認待ちでSIGKILLし、旧pkgとゲーム状態が保持されることを確認。その後の更新に成功。
2. DB移行コピーの検証後・公開前に例外を注入。原本とバックアップは保持され、失敗記録を保存。
3. バックアップから別DBへ復元し、整合性を検査。
4. 旧0.19.0のpkgへ戻し、復元DBコピーでDoor経由の交易に成功。
5. pkg削除後もDB・殿堂・編集済み設定・鍵が保持され、再インストールに成功。
6. マスター起動中のpkg再インストールでPID・ログが変わらず、無断停止しないことを確認。

pkgのファイル展開途中の停電、ディスク故障、任意の破損状態からの完全自動復旧までは検証していません。更新前にゲーム更新処理を明示停止し、旧pkgとDB・設定・鍵を保存する運用です。

新しい `starroute-maintain` は `check`、`backup`、`migrate-copy`、`tick` を提供します。移行は新しいコピーだけを作り、稼働DBを自動切り替えしません。`integrity_check`と外部キー検査を実施します。

DBスキーマは既存の11を維持しました。旧版への復旧判定はDBスキーマに加えてルールバージョンを確認します。新しい`world-time-1`の宇宙を旧0.19.0へそのまま渡すことはできません。復旧時に確定済み取引を失わないよう、DBを巻き戻す操作とプログラムだけを戻す操作を区別してください。

## 航行と世界イベント

既存DBの有効カタログは変更していません。次の設定は新しい宇宙を作る際の `game.json.sample` / `examples/long-duration-template.json` で選びます。既存の宇宙を勝手に生成し直したり切り替えたりしません。

- 通常船は暫定720秒/距離単位、時間計算に使う距離の下限は暫定10。近距離は最低2時間、距離30で6時間、60で12時間、120で24時間。
- 工作船の低速特性、既存のワープ性能・Cr費用の独立性を維持。
- 世界イベントは7,200秒ごとに全宇宙で1回抽選。不発も記録。発生時は種類と対象惑星を一つ選択。
- 暫定確率1%、3種類の重みは暫定1:1:1。正式なゲームバランスではなく、共有ルールから変更可能。
- 個別航行イベント、生産、相場の周期は独立。
- 抽選結果・災害効果・ニュースを同じトランザクションで保存し、再起動・再処理で重複させない。
- ログアウト中の経過時間は、次の操作時に保存済み時刻から分割して回収。常時反映したい運用では管理者が`tick`を定期実行可能。pkgはcronを自動登録しない。
- 7日間の未処理枠、数時間航行、ログアウト・新しいGatewayでの再接続、不発・発生・保存失敗・再実行を差し替え時計で検証。

新しい固定パラメータは共有ゲームルールと設定ハッシュに含みます。動的な抽選記録・現在価格・在庫を設定ハッシュに混ぜません。旧カタログのルール識別・ハッシュ互換性を維持します。

## 配布とセキュリティ

ソースのGitHubリポジトリ、宇宙データ配布元、pkg配布元は別です。存在しないGitHubリリースURLは設定していません。ローカルdistfileを事前配置し、SHA-256で確認してビルドします。ソースtarを2回生成し、同じハッシュになることを確認しました。

同梱repoは検証用の署名付きfile://リポジトリです。正しい公開鍵で取得・インストールでき、異なる公開鍵では空のpkg台帳へ登録できないことを検証しました。既存の信頼済みキャッシュが残る場合があるため、pkg updateの終了コードだけを署名成功の判定には使っていません。

同梱repoにはStarRouteの3パッケージだけを含めます。Python・SQLite等は対応するFreeBSDの依存パッケージが必要です。本番の配信先・認証・署名鍵・HTTPSサービスは今回設定していません。検証用公開鍵を本番の信頼鍵として自動登録しないでください。

## 既存環境の保護と残る運用作業

独立領域：`/home/takeshi/starroute-ports-verification-20261102`。ホストのpkg一覧は不変、確認対象521ファイルは差分0、開始時の`/etc/rc.conf`も一致。検証jailは停止し、devfsをアンマウントしました。元のGitリポジトリにも変更はありません。

ユーザーが手動で導入済みの本番0.19.0環境、Liner notes本番、稼働サービス、Door設定、認証情報は変更していません。本番ホストの移行自体は未検証です。

本番導入では、管理者承認後に配布repoと信頼鍵を準備し、バックアップを取り、初回は`pkg install`、以後は`pkg upgrade`を使用します。既存Doorラッパーの起動先変更は手動で実施します。具体例とロールバック手順は [ports/README.md](../ports/README.md) を参照してください。

Liner notes本体のPorts化は今回の範囲外です。ゲーム側のBBS起動インターフェースと既存UIは維持しています。
