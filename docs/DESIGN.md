# StarRoute Traders Phase 1 設計

実装版: 0.1.0 / 設計改訂1: 2026-11-01。今回の追補反映は文書のみ。
企画室決定事項の要件・フェーズ・受け入れ基準は[ROADMAP.md](ROADMAP.md)を参照。

## 1. 資料照合と優先順位

優先順位は企画室の確定追補、既存開発指示書、StarRoute固有の暫定設計、参考資料の順。
以下のPhase 2説明は実装当時の状態。将来設計は追補に従い更新する。
作業フォルダの既存ファイルは添付WPRO1995009.pdfのみ。既存実装・AGENTS.mdなし。
保存済み資料もStarRouteで検索したが、関連する既存設計は特定できなかった。
参考資料: 粕川正充「ギャラクティック・フリートレーダーズ製作記」
第36回プログラミング・シンポジウム報告集、1995年1月、pp.75–82。
スキャンの本文を抽出し、ゲーム進行のp.77を画像でも確認した。末尾のセッション画像は
文字認識が不鮮明なため、内部仕様の根拠にしない。参考資料や図版は配布物へ複製しない。

| 論点 | 資料との照合 | StarRouteの判断 |
|---|---|---|
| ソリテア型＋共有経済 | p.77の交易・在庫競争と整合 | 共有市場、共有航路。PvPは中心にしない |
| 複数の遊び方 | pp.80–81の目的外行動と整合 | 最終到達でプレイを終了させない |
| 燃料と通貨 | p.77では通貨と等価、通常航路は無料 | 追補で通常航行0 Cr確定。Phase 2は燃料なし、Phase 3で有料ワープを分離 |
| 永続化 | pp.78–79はテキストファイル＋ロック | 今回の指示を優先しSQLiteとトランザクションを使用 |
| 金額の桁あふれ | pp.79–80で運用上の問題 | 整数クレジット（表示Cr）、DB上限を超える操作は全体を拒否 |
| 寄付・ジャックポット | 今回の指示が具体的な根拠 | 最終寄付者等の配分を原作の確定仕様と扱わない |
| クール・殿堂 | 今回の指示が具体的な根拠 | 終了手順を設計し、実装はPhase 4 |
| 接続方式・UI | 原作の画面・言語は継承対象でない | Python CLI、将来WebとDoorは別Adapter |

原作の再現性より、今回指定された面白さと分離構造を優先する。重大な矛盾はない。
不足している価格式・認証・クール期間等は未確定のまま、以下の暫定判断で前進する。

## 2. 境界とディレクトリ

```
starroute/
  engine.py           純粋なルール・状態遷移。SQL、端末、HTML、実時計なし
  model.py            状態、構造化エラー、数値上限
  catalog.py          JSON定義の検証・読み込み
  application.py      共通操作、Clock、Repository契約、トランザクション調整
  clock.py            SystemClockとManualClock
  repository.py       SQLite実装、スキーマ、カタログのDB固定
  adapters/cli.py     入出力、メニュー、パーサ、表示のみ
  data/demo.json      最小世界の試遊用定義
  __main__.py         組み立てと起動
scripts/demo.py        UIなし交易シナリオ
 docs/ tests/          設計、運用、自動検証
```

CLI -> Application -> Engine。Application -> Repository -> SQLite。
将来のWeb -> 同じApplication。CLIの文字列をWebから生成・解析しない。
Engineはメモリ上のWorldを変更し、構造化dictを返す。現行の文章表示はCLIが行う。商品等の名称は日本語データを返す旧DTOであり、
今後はIDから外部言語定義を解決して日英正式対応する。Engineに表示文章を追加しない。
Applicationは1操作につき1トランザクションで読込・時間更新・ルール適用・保存。
SQLiteではBEGIN IMMEDIATEで世界更新を直列化し、検査と更新の競合を防ぐ。
エラー・例外時は全ロールバック。CLIの構文不正はDB操作前に処理する。

最小世界は全プレイヤー・市場・航路をWorldにロードする単純な実装。
小規模単一サーバ向けで、大規模運用の性能を保証しない。Phase 3以降は同じ
Repository境界で操作対象行のみのロード/保存へ移行できる。巨大な分散構成は不要。
各CLIプロセスは別の接続で同じローカルDBを共有する。SQLite WALとbusy_timeoutを使用。
DBロック失敗は再試行可能なエラーとしてCLIに通知する。ネットワークFSは運用対象外。

## 3. 共通Application Interface

すべてPythonの意味のあるメソッド。戻り値はJSON化可能なdict/list/int/str/null。

| 操作 | 入力 | 戻り値の中心 |
|---|---|---|
| create_player | player_id, handle | 作成済みプレイヤー状態 |
| get_player | player_id | cash, cargo, capacity, location, travel, remaining_seconds |
| get_market | player_id, planet_id=None | planet_id, entries[goods_id, price, stock, volume] |
| buy_goods | player_id, goods_id, quantity | side, unit_price, total, quantity |
| sell_goods | 同上 | 同上 |
| get_routes | player_id | destination_id, distance, seconds, fee, is_open |
| depart | player_id, destination_id | arrival_at, destination_id, fee |
| update | 引数なし | game_time |

get_marketはPhase 2では現在地のみ。遠隔情報販売は将来のGuild機能。
エラーはGameError.code（INSUFFICIENT_FUNDS等）。端末向け文章を返さない。
quantityはboolを除く正の整数。IDはASCII英数と._-、1〜64文字。
handleは表示名であり識別/認証に使わない。制御文字を拒否し端末エスケープ注入を防ぐ。

将来追加する操作（今回は未実装）:
contribute_route(player_id, route_id, amount)、get_guild_info(player_id)、
get_rankings(season_id, category)、get_hall_of_fame(season_id=None)。
クール終了APIはプレイヤーAPIと分離した管理サービスに置く。

Web導入時は認証済みPrincipalからplayer_idを決める。リクエスト本文で任意IDを
指定させない。CSRF、レート制限、変更要求のrequest_idによる重複排除を追加する。
現CLIの--playerは信頼されたローカル試遊用の選択機能であり、認証機能ではない。
インターネットへこのCLIを直接公開する段階ではない。

## 4. データモデル

### Phase 2実装済み

| テーブル | 主キー/内容 | ライフサイクル |
|---|---|---|
| metadata | schema_version、完全なカタログJSON | DB単位 |
| seasons | id、status、開始時刻、最終game_time | 第1クールを手動管理 |
| players | id、handle | 恒久的な内部ID |
| ships | id、name、capacity、max_distance、speed | カタログ定義 |
| planets | id、name | カタログ定義 |
| goods | id、基準価格、volume、production、volatility | カタログ定義 |
| player_state | (season_id, player_id)、cash、ship_id、planet_id、destination_id、arrival_at | クール内 |
| cargo | (season_id, player_id, goods_id)、quantity | クール内 |
| markets | (season_id, planet_id, goods_id)、price、stock | クール内・全員共有 |
| routes | (season_id, id)、from/to、distance、seconds、fee、is_open | クール内・双方向 |

FK/非負CHECK/一意制約をDBでも設定。1プレイヤー1船。船の仕様はships、所有は
player_stateで表現する。船個体の改造・耐久度を入れる際はowned_shipsへ分離する。
金額・数量はSQLiteの符号付き64bitに収まる安全域（10^15以下）で検証。
合計金額のオーバーフローやマイナス残高を許さない。金額浮動小数点は使わない。

カタログは新規DB作成時に全体を保存し、通常再起動はDB内の定義を再利用する。
既存DBに異なる--configを渡すと拒否する。編集後は別のDBで試遊する。
これにより稼働中の定義だけが差し替わって既存積荷が消える事態を防ぐ。
将来のデータ更新には明示的な移行を用意する。未知のschema_versionでは起動拒否。

### 将来の拡張設計（空テーブルや仮の成功APIは作らない）

- route_contributions: season_id, route_id, player_id, amount, timestamp, request_id。
- events: season_id, event_id, type, target, start/end, payload, deterministic_rng_key。
- trade_ledger: 売上、原価配賦、航行費、損失、救済を別種で記録。利益ランキング前に導入。
- insurance_policies/claims: 契約、保険料、事故ID、支払内容。事故ID一意で二重補償防止。
- guild_state/discoveries: クール内ランク、初到達・探索履歴。
- ranking_definitions: 部門ID、評価器ID、降順/昇順、同点判定方式。
- rankings/season_results: クール終了時の全参加者結果を確定保存。
- hall_of_fame: season_id, category_id, place, player_id, handle_snapshot, score。
  UNIQUE(season_id, category_id, place)、上位3名、FKのCASCADE削除は禁止。
- bbs_accounts: (bbs_id, local_user_id)の一意な組と内部player_idを対応付ける。
  別BBSの同一人物/表示名/ローカルIDを統合しない。単体CLIの既存IDを移行で保持する。
- プレイヤー別言語設定、外部表示辞書、要求の冪等記録、惑星4産業/非公開開発方針、
  投資の実支払額と効果量、船種とグレードの分離を追加予定（ROADMAP参照）。

## 5. 時間処理の暫定仕様

元の意図: 非同期参加でき、切断しても航行や経済が続く共有宇宙。
提案: Clock.now() -> 秒、Engine.update(world, now)で遅延更新。
CLIの各操作と明示updateで呼ぶ。Phase 2では期限到来した航行のみ確定する。
長所: 常駐daemon不要、テストが速い、切断・再起動・複数CLIに対応。
短所: 接続がない間の通知は即時に発生しない。大量の周期イベントには別tick runnerが必要。
世界時刻はDBのlast_timeより後退しない。ユーザーの操作回数で世界時間は進めない。
出発時にarrival_atを保存する。航行中は売買/再出発不可。到着は一度だけ確定。
CLI waitは実時間待機中にget_playerを再呼出するAdapter機能で、ゲーム時刻を改変しない。
将来市場周期を入れる際はlast_tickからの未処理区間を順に処理し、seed＋クールID＋tick＋
対象IDの乱数系列を固定する。呼び出し回数で乱数を消費する設計にしない。
ManualClockは試験・demo専用。通常CLIから時間スキップは提供しない。

## 6. 市場・リスク・航路開拓（Phase 3設計）

Phase 2は価格固定、在庫のみ売買で共有更新。商品価格・生産・変動特性は定義できるが
production/volatilityはまだ動作しない。固定価格の最適往復が存在する試作であることを明示する。

Phase 3で導入予定の価格モデル:
惑星の商品別均衡価格＋需給偏差＋期限付き大変動＋tick単位のノイズ。
売却で偏差を負方向、購入で正方向へ動かす。偏差は経過tickに応じて均衡へ回復。
ノイズ幅・回復率・上下限・大変動率/期間は定義化。大口取引は数量区間ごとの限界価格を
積算し、同地点での即時売買や分割注文による無リスク増殖を検証する。
生産は在庫上限まで補充する。市場の無限買い取りによる貨幣供給も台帳で監視する。

旧案は残必要額まで寄付を受理する方式。追補の工作船ボーナス導入に合わせ、
支払額と効果量、開通閾値、余剰寄付の扱いを企画確認してから実装する。
DB更新はBEGIN IMMEDIATE内で行う。
開通判定、残高減算、寄付履歴、全員への航路開放、報酬を同一トランザクションで確定。
報酬原資（運営発行/積立）、最終/最大/参加者配分、端数/同額判定は設定とし、実装前に
ルールを明示する。現在は勝手に率を固定しない。報酬重複をUNIQUEな開通記録で防ぐ。
BBSごとの独立アカウントは正式仕様として認める。重複送信・報酬増殖の防止を
BBS認証/要求IDと併せて設計し、実在人物のアカウント統合で解決しない。

イベントはtype→handlerの登録方式。RNG注入と再現可能なevent_idを持つ。
難破では積荷/船/資金に損失を適用し、その後で保険・最低救済を適用する。
難破救済は最低限の船と必要資金を確保し、救済で資産を増殖できないようにする。
任意破産は別機能。初回標準船の1グレード下・初回より少ない資金で再出発し、
清算/位置/進捗等は実装前の企画確認が必須。難破の補償内容と混同しない。
原作の確率・補償率と称した数値は採用しない。

## 7. クール制・目標（Phase 4設計）

現時点ではクール1をDBに保持するだけ。自動終了/リセット/ランキングは未実装。
期間・終了条件は未指定。管理者の明示操作で終了する方式を初期候補とする。
将来: active -> closing -> closed。終了とスナップショットを原子的に確定し、
各部門上位3名を殿堂に保存してから次クールの状態を生成する。
同時操作をブロックし、終了操作の再試行で殿堂が重複しないことを保証する。
プレイヤー内部ID、全戦績、表彰、殿堂、終了時表示名は永続。
新クールでは資産、船、積荷、相場、航路開拓、惑星産業開発、ギルド/探索進捗を初期化する。
旧状態を物理削除する必要はなく、読み取り専用アーカイブも選択できる。
利益、資産、探索、開拓は別評価器。開拓寄付は現金を消費し、探索は移動時間を使うので
トレードオフを設ける。ただし最適戦略の分散は実測・調整が必要で、設計だけでは保証しない。

## 8. DoorとWeb（Phase 5設計）

Door Adapterで認証済みBBS IDと会員ID/表示名/セッションを受け取り、bbs_accountsで解決。
日英完成・Inter-BBS接続はPhase 5の必須機能。中央ゲームサーバは有力案であり通信方式は未定。
共通世界とクールを全BBSで共有し、個人の船/現金/貨物/進捗/成績はBBS別に保つ。
引数や環境変数にIDを置くだけの方式は最終認証にしない。署名付き短命チケットまたは
限定権限のローカルIPCを候補とする。Liner notes内部DBへ直接書き込まない。
ゲームDBパスと認証情報の受渡しを分離する。結果投稿はOutbox/Publisherインターフェースを
後から追加する。現時点で外部投稿APIが存在するとは仮定しない。
WebはDTOをJSONへ変換するだけのAdapterとし、価格/積載/航行条件を再実装しない。

## 9. 暫定定義と判断

| 項目 | 試遊値/挙動 | 利点 / 制約 |
|---|---|---|
| 技術 | Python 3.10+ / SQLite / 外部依存なし | FreeBSDで導入しやすい / 実機未検証 |
| 世界 | 3惑星・3商品・1船・3双方向航路 | 最小ループ確認用 / 最終規模ではない |
| 初期状態 | 5,000 CR、容量20 | JSONで変更 / バランス未調整 |
| 燃料・費用 | 現行は燃料なし、demo航路費0 | 追補で通常航行・係留は全条件で0 Cr確定。有料ワープをPhase 3へ分離 |
| 航行 | 2〜4秒、距離/船速/航続距離で検査 | すぐ試せる / 本番時間ではない |
| 市場 | 固定価格、有限共有在庫、売却で補充 | Phase 2の取引確認 / 時間生産・変動はPhase 3 |
| 売買単価 | 同じ市場では買値=売値 | 同地点の無限利益なし / スプレッドは未導入 |
| クール | 第1クールのみ・自動終了なし | 勝手な期間を固定しない / 長期運用はPhase 4待ち |

## 10. テスト方針と完了条件

外部依存のないunittest。Engineを直接呼ぶ試験、ManualClock＋一時SQLiteの統合試験、
複数接続/並行注文、CLI subprocessで交易を検証する。実時間sleepを基本試験で使わない。
検査対象: 売買成功、資金/積載/在庫/保有不足、不正数量、負値/桁、移動経路/距離、
航行中の操作、到着境界、共有在庫、失敗時原子性、再接続、設定固定、未知スキーマ。
Phase 2完了条件は買う→移動→売るで現金が増え、DB再読込後も維持されること。

Phase 3開始時に相場反映/回復/seed再現、寄付累積/競合開通/報酬一回性、
各イベント・難破・保険の損失と再起を実テストに追加。
Phase 4開始時に終了競合、リセット範囲、上位3名/同点規則、殿堂永続性/重複禁止を追加。
未実装機能に対する空のテストや常時skipを、検証済み件数として数えない。

## 11. 企画室追補の適用

船3系統/グレード、無料通常航行/係留、有料ワープ、惑星4産業、非公開上限、
船販売条件、工作船効果/鉱物発見、仮装巡洋艦の討伐、任意破産、日英/Inter-BBSを
[ROADMAP.md](ROADMAP.md)へ登録した。受け入れ基準13項目の検証先と
未決事項の企画確認時期を割り当てた。今回はゲームコードとDBを変更していない。
