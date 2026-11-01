> v0.8.0: rules_version=phase3d-1、設定射影3、DB7。非公開上限・資源特性を含むdevelopmentを共有ルールへ追加。[PHASE3D.md](PHASE3D.md)参照。

> v0.7.0: rules_version=phase3c-1、設定射影スキーマ2、DBスキーマ6へ更新。economyを共有ルールへ追加。[PHASE3C.md](PHASE3C.md)参照。以下はv0.6.0の履歴。

# CFG-01〜05 設定管理基盤 v0.6.0

## 実装

- CFG-01: Catalog.effective_rules() / rules.effective_rules(catalog) に共有ルールの明示的な射影を集約。Engineが利用するCatalogをApplication経由で使用。Settings.site_settings()はデフォルト言語・言語ファイル・Inter-BBS設定を独立取得。
- CFG-02: Application.configuration_info()でworld_id、rules_version、config_schema_version、canonicalization、algorithm、sha256を取得。ローカルCLIのconfig-infoも同じAPIを使用。
- CFG-03: DBスキーマ5のworld_identityにUUIDを1件永続化。account_identity(bbs_id, local_user_id)はworld_idと旧player_idを含む識別情報を返す。世界は引き続き1DB単位であり、異なるBBSの同一人物を統合しない。
- CFG-04: Application.reference_candidate()で正規参照の候補情報を作成可能。世界・版・ハッシュと検証情報（status/authority/key_id/signature_algorithm/signature/distribution）を持つ。常にunverified、方式等はnull。候補生成は真正性の検証・接続許可ではなく、登録・署名・配布は未実装。
- CFG-05: 順序不変、ルール変更、サイト設定分離、版、移行、失敗時ロールバック、バックアップ復元、既存再送結果、CLI読取り等の自動テストを追加。

## 正規化方式 srt-integer-json-v1

共有設定の射影、rules_version、config_schema_version、canonicalizationを包んだJSONをSHA-256へ渡す。UTF-8、BOMなし、キー辞書順、空白なし、非ASCII文字はそのまま。整数・真偽・null・文字列・配列・文字列キー辞書のみ。整数5000と5000.0は同値として受理せず、後者を拒否する。浮動小数点、NaN、Infinity、重複JSONキーは拒否。文字列のUnicode正規化は行わず、IDは既存のASCII識別子制約を維持。

商品・船・惑星・航路・グレードはID順、市場初期値は惑星ID/商品ID順、航行計画は船ID/航路ID順、ワープ選択肢はlevel順。これらは意味に順序依存がない集合。将来追加する順序依存配列は勝手にソートしない。

既定の船プロフィールは旧形式でも展開する。navigationの未指定/nullは同じ空計画になる。表示名・翻訳・サイト設定・provisional等の説明用状態は除外。ゲーム値とIDは保持する。通常航行で無視される旧fee、明示航行計画で置き換わる旧speed/secondsは除外。確定した無料航行・無料係留と整数上限は明示的なfixed_rulesとして含む。

商品生産量・変動特性、保険料・船価等の既存の将来機能用設定も共有ルールの予約パラメータとして含めるが、機能を実装済みとはしない。可変の現金・市場在庫・開発進捗はハッシュ対象ではなく、初期値とルールが対象。

未知の設定項目は既存ゲームの読込み互換を保つが、ハッシュ取得時にはCONFIG_VERIFICATION_FAILEDとする。新機能の設定は分類と正規化を追加してから検証可能にする。将来の投資・イベント等の値を仮に追加してはいない。

## バージョンと互換性

rules_version=phase3b-1は実装済みルールの識別子。config_schema_version=1は共有ルール射影の形式であり、入力カタログformat_version=1/2、DBスキーマ5、アプリ0.6.0とは別。ルールや正規化の意味を変えた際は対応する版も変更する。

Catalog.canonical()と既存見積りハッシュは変更していない。既存DBではDB内catalogを引き続き使用し、ファイル差し替えで有効ルールやハッシュは変わらない。ハッシュとworld_idは別項目。同じルールの別世界は同じハッシュ・別世界IDとなる。

旧DBはスキーマ1〜4から自動移行する。更新前のDBを .vN-backup-UUID.db に保存し、world_identity追加とスキーマ更新を同一トランザクションで実行。旧player_id・アカウント対応・資産・市場・航路・航行期限・要求履歴を変更しない。失敗時はロールバックしバックアップを保持する。スキーマ5のID欠落/不正を自動で再発行しない。

スキーマ5のDBバックアップ/復元は同じ世界IDを保持する。旧版へ戻すときは旧版対応の移行前バックアップを使用する。旧版へ新スキーマDBを直接渡さない。

## 確認事項・Phase 5との境界

正規マスター管理主体・配布・署名/認証方式、通信プロトコルは未定。自己申告ハッシュを正規設定と認める処理は存在しない。通信と接続可否の判定はPhase 5のまま。ゲームの具体値・イベント等の未決事項も継続する。

既存DBのコピーを独立した新世界へ分岐させる管理操作は未実装。同じバックアップを復元すれば同じ世界として扱う。旧スキーマのコピーをそれぞれ初回移行すると別世界IDが発行されるため、将来同一共有世界へ参加させるコピーは、権威ある移行済みDBから作る管理手順をPhase 5で確定する。IDをルールハッシュから推測したり、黙って統合したりしない。

有効設定全体は内部管理専用。CLI config-infoはID・版・ハッシュだけを表示する。将来の非公開開発上限も共有ルールへ登録するが、公開応答へその値を返さない。候補情報に署名値等を保存・公開する運用はまだない。

## CLI

```sh
python3.12 -m starroute --db data/universe.db --player captain --command config-info
```

config-infoは登録前でも利用可能。ゲーム時間を進めず、取引や共有更新を行わない。JSONのキーは機械判読用で日英共通。
