# StarRoute Traders v0.17.0 — Phase 4

## 実装範囲

Phase 3 のゲームエンジンを継続使用し、独立した宇宙取得、検証・登録台帳、クール管理、成績・ランキング・殿堂、探索履歴、バックアップ・復旧用コピーを追加しました。実行結果の確定情報は成果物の `phase4-acceptance-checklist.json` と検証ログを参照してください。Phase 3 の acceptance-checklist.json は別の成果物として保存されています。

本番 GitHub 接続、Inter-BBS API、Door 起動、BBS 認証、外部サービス公開は行いません。Private Repository の実 URL / Deploy Key が未提供のため、本番接続は未検証です。ローカル Git と使い捨て Ed25519 署名鍵で同じコミット固定・blob取得・署名検証処理を検証します。

## 責務

- `srt_universe_generator`: 既存の独立した宇宙生成ツール。
- `distribution.py`: Git 取得と署名付きマニフェスト検証。checkout、submodule、取得コード実行を行いません。
- `universe_package.py`: エンジンに依存しない形式・48惑星・名称・産業Lv・生成定義検証。
- `operations.py`: 管理者専用の検証、登録、有効化、締め処理、バックアップ。
- `statistics.py`: サーバに保存された確定操作から算出する成績。
- `records.py`: 秘密情報を含まない読み取り専用の成績・探索インターフェース。
- `admin.py`: 管理CLI。ゲーム操作CLIは従来の `python -m starroute` を維持。

旧DBは互換モードのまま使用できます。新しいクール運用は `admin init` で作る別のDBを使用します。旧DBを無断で管理対象へ変換しません。管理対象DBでは登録・有効化前のゲーム操作を拒否します。

## 依存関係

Python 3.10以上の構文と標準ライブラリを使用。検証対象は Windows Python 3.14.7 / FreeBSD Python 3.12.15。Git 2.30以上、SSH署名を扱える OpenSSH 8.2以上を運用の最低基準とします。最低バージョンそのものの実機試験は行っていません。

Windows: Python、Git for Windows、Windows OpenSSH Clientをインストールし `python`, `git`, `ssh`, `ssh-keygen` をPATHへ置きます。
FreeBSD: 管理者が必要に応じ `pkg install python312 git` を実行します。ベースの OpenSSH を利用できます。ゲーム利用者にroot権限は不要です。

`python -m unittest discover -s tests -v` で全テストを実行します。Windowsの制限された実行環境では Git for Windows の補助プロセス起動が制限される場合があります。通常の利用者環境で検証してください。

## 管理CLI

以下のDB、Universe ID、Round IDは説明用です。実行対象の値に置き換えてください。CLIの時刻はUTCエポック秒です。

```text
python -m starroute.admin --db isolated.db init
python -m starroute.admin --db isolated.db stage --package universe.json
python -m starroute.admin --db isolated.db validate --universe UUID
python -m starroute.admin --db isolated.db register --universe UUID
python -m starroute.admin --db isolated.db prepare --universe UUID --round 1 --start UTC_SECONDS --policy round-policy.json
python -m starroute.admin --db isolated.db activate --universe UUID --round 1
python -m starroute.admin --db isolated.db list
python -m starroute.admin --db isolated.db universe --universe UUID
python -m starroute.admin --db isolated.db rounds
python -m starroute.admin --db isolated.db rankings --round 1
python -m starroute.admin --db isolated.db scores --round 1
python -m starroute.admin --db isolated.db finish --universe UUID --round 1
python -m starroute.admin --db isolated.db hall
python -m starroute.admin --db isolated.db history
python -m starroute.admin --db isolated.db check
python -m starroute.admin --db isolated.db archive-check --round 1
```

`--lang ja` / `--lang en` を管理CLIのサブコマンド前に指定できます。機械可読JSONの項目名は共通です。

ゲームCLIには `rankings [ROUND [trade|planet|route|exploration]]`, `score [ROUND]`, `hall`, `rounds`, `exploration [ROUND]` を追加しました。日英の表示ラベルは別言語ファイルです。クール終了後・航行中も読み取り可能です。表示は確定済みDBのスナップショットであり、時刻更新や秘密情報の取得は行いません。

次宇宙Bを事前登録しても宇宙Aは変わりません。Bをprepareした後、Aを締めてからBをactivateできます。稼働中Aから一括切り替えする場合は、activateに `--previous-round A_ROUND --previous-universe A_UUID` を明示します。一括処理全体が同じトランザクションです。

## GitHub取得と署名

取得先は `git@github.com:OWNER/REPOSITORY.git` 形式のみ。本番URLはコードに固定しません。40桁または64桁のコミットIDを必須とし、ブランチ名は拒否します。

配布リポジトリには次の3ファイルを置きます。

```text
universe.json
universe.json.manifest.json
universe.json.manifest.json.sig
```

マニフェスト形式:

```json
{"format":"srt-signed-manifest-v1","package_sha256":"SHA256_OF_EXACT_PACKAGE_BYTES","universe_id":"UUID"}
```

発行者の管理端末で署名します。

```text
ssh-keygen -Y sign -f ISSUER_PRIVATE_KEY -n starroute-universe universe.json.manifest.json
```

マスター側の信頼ファイルには `issuer-name ssh-ed25519 PUBLIC_KEY_BASE64` を配置します。公開鍵は配布リポジトリから自動取得せず、管理者が別経路で指紋を確認して登録します。鍵更新も明示的な管理作業です。署名秘密鍵はマスターに不要です。

```text
python -m starroute.admin --db isolated.db fetch --repository git@github.com:OWNER/REPOSITORY.git --commit FULL_COMMIT_ID --package-path universe.json --allowed-signers TRUST_FILE --identity issuer-name --key READ_ONLY_DEPLOY_KEY --known-hosts TRUSTED_HOSTS
```

GitHub上のDeploy Keyは必ず書き込み許可を外して登録してください。読み取り専用というサーバ側の権限設定を、Gitクライアントが単独で証明することはできません。本実装はfetchのみを実行し、push機能を持ちません。SSHはBatchMode、IdentitiesOnly、厳格なホスト鍵検証を必須にし、パスワードへのフォールバックを禁止します。Gitのグローバル設定によるURL書き換え等を無効化します。

パッケージおよび関連blobの上限は既定各32MiB、外部コマンドの時間上限は既定120秒です。`config/distribution.json`で取得側制限を変更できます（登録のハード上限は32MiB）。これらは運用制約でありゲームルールではありません。パス逸脱、シンボリックリンク、実行可能ファイルモードを拒否します。署名はマニフェストの生バイト列に対して検証し、パッケージ生バイトのSHA-256も確認します。登録後は正規化したパッケージハッシュを再検証します。

`--local-test` は明示的なローカルGit試験用です。台帳にはGitHubと異なる `LocalGitTest` を記録します。通常のローカル生成ファイルは `trusted_local` と記録し、暗号学的な署名検証済みと偽りません。管理者が信頼するローカル生成物を取り込む経路です。

## DBスキーマ11・整合性

スキーマ10から既存テーブルを破壊せず、p4_universes / p4_rounds / p4_audit / p4_visits / p4_discoveries / p4_statistics / p4_rankings / p4_hall / p4_archivesを追加します。旧スキーマの移行前バックアップを維持します。移行はトランザクションで確定します。

宇宙状態はSTAGED→VALIDATED→REGISTERED→ACTIVE→ARCHIVED、クールはPREPARED→ACTIVE→CLOSING→CLOSED→ARCHIVEDです。CLOSINGと成績保存は同じトランザクションなので、失敗・強制終了時はACTIVEへ戻ります。監査履歴には途中の正常遷移も記録します。同一UUID・同内容は再利用し、異なる内容は拒否します。1宇宙を複数クールに流用しません。

締め処理は書き込みロックを取得し、締め時刻までの航行・イベントを確定した後に集計します。未完了航行は旧宇宙のアーカイブに残し、新クールへ継続しません。旧宇宙の表とカタログ・識別情報は圧縮JSON＋SHA-256で保存します。殿堂・確定順位・確定成績・アーカイブにはUPDATE/DELETE拒否トリガーがあります。表示名も確定時の値を保存します。

切り替えは単一SQLiteのBEGIN IMMEDIATEと遅延外部キー検証を使用。旧宇宙の締め・保存、新初期世界への置換、プレイヤーの再初期化、状態変更を一括確定します。プレイヤーのBBS識別・利用者ID・表示名・言語設定は残ります。市場、開発、貨物、航行、保険、寄付、イベントなどは新しい生成データから初期化します。古いエンジン接続はWORLD_CHANGEDで拒否し、接続を開き直します。

## 成績・暫定ルール

`starroute/config/phase4.json` が既定値です。prepare時の `--policy` で変更し、そのクール内に固定保存します。

- 既定期間30日（2592000秒）は暫定。期間は任意の正整数に変更できます。
- 交易はFIFOによる実現損益。売却代金から売却した在庫の取得原価を差し引きます。未売却在庫は含み益を算入しません。端数はロット残額へ繰り越します。
- 取得原価のないイベント貨物等は暫定的に0原価として扱い、unpriced_unitsへ別記します。正式な評価方式は未確定です。
- 航行費、投資、寄付、保険料・保険金、ジャックポット、再出発資金、船購入、海賊・修理損失は交易利益と分離します。
- 惑星・航路部門は実際の効果量を既定とし、paid_credits方式も選択可能。支払額、効果量、工作船ボーナスを別々に保存します。対象惑星・産業・航路の詳細は既存台帳と旧宇宙アーカイブに残ります。
- 探索は訪問済み惑星数の暫定評価。幻の星発見・勝利条件を実装したとは扱いません。殿堂にも `provisional_unique_visits_not_victory` を記録します。
- 同点はプレイヤーID昇順の一意な表示順位。部門ごとに上位3件、3人未満なら存在する人数のみ保存します。
- クール終端以降は新しいゲーム操作を拒否します。時刻表示の数値はUTC秒で、クライアント側で地域時刻へ変換できます。

Phase 3のルールハッシュは互換性のため維持し、Phase 4のクール設定は独立ハッシュを計算します。クールのconfiguration_hashはエンジン側ハッシュとクール方針ハッシュを束ねたSHA-256です。市場・在庫・開発進捗など動的状態は含みません。

## バックアップ・復旧

登録・締め・有効化前に `<db>.backups/` へSQLite Backup APIで整合したコピーを作成し、integrity_check / foreign_key_checkを実行します。POSIXではディレクトリ0700・ファイル0600を基本とします。Windowsでは親ディレクトリの利用者限定ACLも管理者が設定してください。DB、バックアップ、宇宙パッケージは非公開領域に置き、BBSへ配布しません。

途中例外やプロセス停止後はDBを開き直し `check` と `history` で確定状態を確認します。REGISTERED/PREPAREDなら同じIDで再試行し、ACTIVEならゲームを再初期化しません。確定済み締め処理の再実行も殿堂を増やしません。

バックアップからの調査復旧は新しい場所に限定します。

```text
python -m starroute.admin --db recovered-isolated.db restore-copy --backup BACKUP_FILE
python -m starroute.admin --db recovered-isolated.db check
```

既存ファイルへの上書きは拒否します。新クールで操作が確定した後の旧バックアップ復元を自動実行しません。本番復旧は現在DBと監査・操作履歴を比較し、ユーザーの承認を受ける別の運用作業です。

## 検証シナリオ

`python scripts/phase4_demo.py --directory NEW_PRIVATE_DIRECTORY --lang ja`（enも可）でA〜Eを実行します。実際の管理CLI・ゲームCLIの引数解析と処理を使用し、待ち時間を避けるためテスト用時計だけを差し替えます。宇宙生成、署名付きローカルGit取得、4人の売買、航行、投資、航路寄付、締めの二重実行、12件の殿堂、新宇宙、登録・切り替え障害の復旧を検証します。生成した試験用秘密鍵は使用後削除し、成果物には含めません。

## Phase 5への引き継ぎ

認証済みサイトからのBBS_IDとUSER_IDを既存Application境界に結び付け、Universe ID / Round ID / エンジンとクールの設定ハッシュを要求ごとに照合してください。操作の結果や得点はマスターで計算します。管理CLI・台帳の秘密データをAPIへ丸ごと公開しないでください。

本番API、サイト登録・失効、接続相手認証、正規設定の真正性・双方の不一致分類、途中参加・離脱、公開データのプレイヤー別フィルター、通信断キャッシュ、再送時の結果照会、オンライン一覧、Liner notes Door連携はPhase 5です。現在のCLIは信頼済みローカル管理者・利用者向けであり、ネットワーク認証機能ではありません。
