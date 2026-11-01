# StarRoute Traders v0.18.0 — Phase 5

最終判定・テスト件数・実測根拠は独立した成果物 `phase5-acceptance-checklist.json` / `test-results.json` を参照してください。本番への配備・既存BBSへの組み込み・ポート公開は別の承認工程です。

## 構成と責務

従来のEngine/Application/SQLiteRepositoryを再利用しています。独立したTLSマスターは `starroute.network`、サイト・参照設定の管理は `network_admin`、薄いBBSクライアントは `starroute_bbs` です。共有世界の更新はマスターだけが確定します。GitHub取得や生成をゲームAPIへ組み込んでいません。

スタンドアロンDoorも同じ端末UIを使い、ネットワーク通信を行わずLocalDoor→Gateway→MasterService→Applicationを呼び出します。サイト識別・公開投影・操作制限の意味は両モード共通です。Inter-BBSクライアント配布物にはEngine、宇宙パッケージ、秘密の設定、生成シードを含めません。

## 起動・サイト登録

Phase 4管理CLIで別DBに宇宙を登録・有効化してから実施します。実ファイルのパスに置き換えてください。

```text
python -m starroute.network_admin --db game.db --reference-key reference.key init
python -m starroute.network_admin --db game.db --reference-key reference.key add --bbs-id liner_a --name "Liner notes" --output site-profile.json
python -m starroute.network --config master.json
```

`init`は新しい参照署名鍵を0600で作り、ネットワーク用追加テーブルを準備します。既存鍵への上書きは拒否します。`site-profile.json`は新規に作る秘密ファイルで、サイト固有の256bit以上のランダム認証情報を含みます。画面や監査ログへその値を出力しません。マスターDBには認証情報のSHA-256だけを保存します。ファイルを安全な経路で対象BBS管理者へ渡してください。

TLSは必須で、平文HTTPの待ち受けは実装していません。TLS1.2以上、ホスト名・CA検証を必須とし、クライアントはHTTPリダイレクトを追跡しません。検証では一時的な自己署名証明書を専用CAとして明示的に信頼します。本番では管理者が検証したCA/証明書・秘密鍵を用意してください。既存証明書の変更は行いません。

ランタイムはPython標準ライブラリのみです。Windowsでopensslがない場合、テスト証明書生成に限りcryptographyを使用します。FreeBSDはベースのopensslで試験証明書を生成します。Python 3.10以上の構文を維持し、対応環境での実行結果はtest-results.jsonに記録します。

## Liner notes Door

既存のDOORS設定・ネイティブPTY機構を使います。認証済みの `LINER_USER_ID` と `LINER_USER` だけからプレイヤーを解決します。利用者がユーザーIDをコマンド引数で渡す機能はありません。BBS IDは管理者所有のサイトプロファイルから確定します。BBSのOS利用者・SYSOPは信頼境界内です。同じOS権限で任意のプログラムを起動できる攻撃者まで環境変数で認証する設計ではありません。

固定ラッパー例:

```python
#!/usr/local/bin/python3.12
import sys
sys.path.insert(0, '/private/starroute/client')
from starroute_bbs.door import main
sys.argv = ['door', '--config', '/private/starroute/node.json']
raise SystemExit(main())
```

doors.conf例:

```text
1|0|3600|/private/starroute/starroute-door|/private/starroute|StarRoute Traders
```

検証用Liner notesを `--doors` で起動し、認証後に `DOOR 1` で入り、`quit`で戻ります。回線切断時はLiner notesがDoorプロセス群を終了し、確定済み取引はSQLiteに残ります。再起動で同じBBS会員IDを解決します。

元のLiner notes 0.70系のDoorには、稼働中のNAWS変更をPTYへ伝える処理がありませんでした。`integration/liner_notes/prepare_resize_copy.py`は**専用マーカー付きのコピー**へだけ3ファイルの差分を作成します。既存ソース・実行ファイルは変更しません。検証版ではTelnet NAWS→PTY TIOCSWINSZ→Python端末サイズ取得を確認します。本番へのこの差分適用は承認が必要です。

## 端末UI

UTF-8、日英、ANSI/モノクロ、80×24を基本に20〜240列・12〜120行へ対応します。ANSI幅を除外し、東アジア文字幅を考慮します。市場・航路・ニュース・順位・殿堂はページ指定が可能です。

```text
status / market [page] / buy GOODS QTY / sell GOODS QTY
routes [page] / go PLANET / warp PLANET LEVEL / flight / dock
map / names on|off / color on|off
development / invest INDUSTRY CREDITS / donate ROUTE CREDITS
shipyard / ship-buy SHIP / insure / bankrupt
news [page] / WHO / ONLINE / score / rankings [page] / hall [page]
rounds / exploration / language ja|en / quit
reconnect / result / retry / cache OPERATION
```

星図は240×120の宇宙座標から船中心のビューポートを切り出します。通常惑星は`*`、船は緑の`+`、停泊惑星は緑の`*`。星図の惑星名は両言語とも英語です。表示名ON/OFFはゲーム状態を変えません。航行中はニュース以外のゲーム操作を拒否し、星図・状態/ETA・表示設定・終了・接続維持は利用できます。言語選択はプレイヤー単位で保持します。

WHOはプレイヤー表示名とBBS表示名、人数だけを返します。オンライン状態はログイン、ログアウト、ハートビート、最終通信時刻で管理します。同一BBS/利用者の複数セッションを重複表示せず、既定300秒で失効します。WHOをキャッシュで代用しません。

## 認証と設定整合性

サイト認証情報はサイトごとに分離し、ログイン時に利用者・セッションへ結び付けた別トークンを発行します。プレイヤーAPIはそのセッションからBBS_ID/USER_IDを確定し、本文の別ユーザーID・BBS IDを受け付けません。サイトは自サイトのBBS認証結果を保証する主体であり、他BBSの権限は利用できません。

正規参照にはrules_version、config_schema_version、実効ルール＋クール方針のハッシュ、Universe ID、Round ID、protocol、client_versionを含めます。マスター管理者の参照鍵でHMAC-SHA256署名し、DBの値とエンジンに実際に適用するハッシュを再照合します。鍵はDBとは別の保護ファイルに置きます。

BBSはゲームルールを実行しない薄いクライアントです。管理者が承認した互換性記述子をサイトID込みで署名し、クライアントの利用記述子と一致を確認します。未署名の自己申告や、署名済み値と異なる自己申告は検証不能です。これはリモートOSや実行バイナリの完全性を測定する仕組みではありません。ゲーム結果を決める実効設定はマスター側で一元的に検証します。

任意の相手サイトを診断する場合は、マスターが検証して保存した結果だけを使用します。相手の検証結果が未取得・期限切れなら「検証不能」であり相手異常と断定しません。通常のマスター接続では相手BBSを指定する必要はありません。

エラー分類はLOCAL_CONFIG_MISMATCH / REMOTE_CONFIG_MISMATCH / BOTH_CONFIG_MISMATCH / REFERENCE_CONFIG_UNAVAILABLE / CONFIG_VERIFICATION_FAILEDです。管理監査には比較項目・バージョン・ハッシュを記録し、利用者UIはコードと短い日英メッセージを表示します。サイト名、言語、端末設定は比較しません。

```text
python -m starroute.network_admin --db game.db --reference-key reference.key sites
python -m starroute.network_admin --db game.db --reference-key reference.key rotate --bbs-id liner_a --output replacement-profile.json
python -m starroute.network_admin --db game.db --reference-key reference.key disable --bbs-id liner_a
python -m starroute.network_admin --db game.db --reference-key reference.key approve --bbs-id liner_a --output approval.json
python -m starroute.network_admin --db game.db --reference-key reference.key audit
```

rotate/disable/approveは既存セッションを無効化します。approveの出力は署名済み設定部分だけです。管理者が既存プロファイルの認証情報を保持して、そのattestation/configuration部分を置き換えてください。実際のゲームルール不一致を自動修正する機能はありません。

## トランザクションと未応答操作

ゲームDBのBEGIN IMMEDIATEと既存operation_historyを使用します。Request IDは認証済みプレイヤー（登録時はBBS/USERの組）とクールに結び付き、同一内容は保存済み結果、異なる内容はREQUEST_CONFLICTです。価格・在庫・資金・積載量・開発上限・ジャックポットはEngineだけで決定します。

同時サイト失効やクール変更も、ゲーム更新のロック内で再確認します。SQLiteのロック待ちは既存の10秒で、競合時はRETRY_SAME_REQUESTを返します。クライアントは別IDで自動再実行しません。追加のゲームDBスキーマ番号は11のまま、ネットワーク拡張バージョン1としてp5_sites / p5_sessions / p5_audit / p5_referencesを追加します。Phase 4の確定記録と移行方式を維持します。

送信予定の更新要求は送信直前に利用者別の小さなジャーナルへ保存し、成功で除去します。応答喪失時は未確定扱いで新規更新を止めます。再接続後に結果照会し、確定済みなら二重実行せず解消します。未受付ならユーザーの明示的なretryで同じIDを再送します。通信断中の新規操作を蓄積するオフラインキューではありません。

## 公開範囲・キャッシュ

現在地、訪問済み惑星とその隣接航路・接続惑星を発見済みとする暫定公開方針です。プレイヤー別の保存済み探索からマスターが決定し、クライアントに非公開の星図全体を送って隠させることはありません。最大開発Lv、未公開資源、生成シード、イベント確率、他プレイヤーの貨物・所持金は送信しません。

公開キャッシュはBBS/USERとUniverse/Roundに分離し、取得時刻・古い可能性を明示します。ステータス・個人成績・WHOをキャッシュしません。ニュースは公開イベントだけを保存し、個人の資金・貨物に関わるニュースを除外します。認証情報・セッショントークンは監査やキャッシュへ記録しません。BBSアカウントIDと未応答操作の最小ジャーナルは、接続復旧用の管理状態でありゲーム世界の複製ではありません。

## 途中参加・正式離脱

```text
python -m starroute_bbs.node --config node.json join --new-config remote-node.json
python -m starroute_bbs.node --config node.json recover
python -m starroute_bbs.node --config node.json leave --new-config fresh-local-node.json
```

joinは先にTLS認証・整合性を確認し、元ローカルDBをバックアップします。元DBへの更新を停止してから、ノード設定を原子的に共有世界へ切り替えます。元ローカルの資産・成績を送信しません。BBS会員ファイルは操作しません。途中失敗はジャーナルから旧モードへ復旧でき、切り替え確定後に無条件で戻すことはありません。

leaveは管理者の明示操作です。先に外部GeneratorとPhase 4管理CLIで**別の新宇宙・プレイヤー0人のローカルDB**を準備します。マスターが当該サイトの更新を停止し、未応答操作をサイトの履歴から照会してから設定を切り替えます。離脱サイトの確定済み市場変更、寄付、台帳、殿堂は巻き戻しません。離脱応答を失った場合も同じ操作を再開可能です。元ノード設定とジャーナルを非公開領域に保存します。

一時通信断、BBS再起動、マスター停止はjoin/leaveを呼び出しません。資産をリセットせず、更新停止・結果照会・再認証で復旧します。

## クール更新

Phase 4 CLIで安全に切り替えた後、管理者が新しい正規参照を発行します。

```text
python -m starroute.network_admin --db game.db --reference-key reference.key publish
```

参照発行までAPIはfail-closedです。ルールとプロトコルが同じでUniverse/Roundだけが変わった場合、再接続で署名された新しい宇宙参照へ結び直し、旧キャッシュを破棄します。これはゲームルールの自動修正ではありません。ルールが変わった場合は管理者の明示的承認・プロファイル更新が必要です。旧クールの遅延更新は拒否し、未応答操作は旧アーカイブの自分の確定記録から照会できます。

## 運用・保護

既定はループバック、TLS、最大本文16KiB、接続タイムアウト10秒、同時32接続、送信元IPあたり毎分120要求です。設定ファイルで調整できます。NATを共有するBBSではIP単位の制限を考慮してください。TLSハンドシェイクも制限付きワーカで実施します。一般APIにサイト管理・宇宙有効化・鍵更新を公開しません。

参照鍵、TLS秘密鍵、サイトプロファイル、DB・バックアップは非公開領域に置きます。POSIXでサイトプロファイルが他者に読める場合、クライアントは起動を拒否します。Windowsでは利用者限定ACLを設定してください。鍵の配布・更新・失効、証明書期限、DBバックアップ、API負荷と監査ログの保存期間は運用管理者の責務です。

Phase 4のバックアップ/restore-copyを利用し、ゲームDBと参照鍵・TLS設定・サイトプロファイルを世代対応させて保護します。クライアントはclient-audit.jsonlへ通信結果の時刻・分類だけを記録します。プロファイルやキーの内容はログへ出しません。本番復元は最新確定操作との整合性を確認してから実施します。

## 検証と本番前作業

`python -m unittest discover -s tests -v`で回帰と追加テストを実行します。`scripts/phase5_telnet_demo.py`は独立Liner notes・新規会員・一時TLS証明書を使い、実際のTelnet/PTYで検証します。既存のサービス、会員、設定、DBへは接続しません。航行は実時計で到着まで確認します。

本番開始前には、配備先・待ち受け範囲・証明書・BBS別認証情報・信頼済み設定・バックアップ・監視・適用するLiner notes差分を管理者が確認し、明示的な配備承認を得てください。本番GitHubの未提供リポジトリ/Deploy Keyによる実接続はPhase 4から引き続き未検証で、今回のBBS通信検証とは別です。有料ギルド通信・未確定の幻の星勝利条件は実装していません。
