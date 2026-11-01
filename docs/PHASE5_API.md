# Phase 5 API / protocol 1

すべてTLS1.2以上のHTTPS POST、Content-Type: application/json、Authorization: Bearerです。既定で本文16KiB、JSONの重複キー・余分なフィールドは拒否します。応答は `{ "ok": true, "result": ... }` または `{ "ok": false, "error": "CODE" }`。資格情報をURLに含めません。リダイレクト・暗黙の環境プロキシは利用せず、設定したマスターへ直接接続します。

## サイト資格情報の窓口

| Path | Body | 結果 |
|---|---|---|
| /v1/reference | {} | 検証済み正規設定 |
| /v1/connect | attestation, configuration, 任意peer | admitted, diagnostic |
| /v1/rebind | attestation, configuration | 同一ルールの新クール向け署名済み設定 |
| /v1/session | user_id, display_name, session_id, universe_id, round_id | session_token, reference |
| /v1/leave | universe_id, round_id, confirm_bbs_id | state=LEFT |
| /v1/site-result | user_id, universe_id, round_id, operation, request_id | 自サイトの確定結果。正式離脱後も読み取りだけ可能 |

サイトIDは資格情報から確定します。user_idはBBSの認証済み会員IDであり、他サイトへ越境する操作はありません。署名済み記述子は管理者が発行し、鍵はBBSへ渡しません。peerを指定した診断ではマスターの検証済み履歴を使用し、未確認・期限切れを異常と断定しません。

## プレイヤーセッションの窓口

| Path | Body | 結果 |
|---|---|---|
| /v1/call | universe_id, round_id, operation, arguments, request_id | 公開投影された操作結果 |
| /v1/result | universe_id, round_id, operation, request_id | status=committed / unknown |
| /v1/who | {} | players（player,bbsのみ）, count |
| /v1/heartbeat | {} | online=true |
| /v1/logout | {} | logged_out=true |

request_idは更新操作に必須、読み取りではnullです。round_idは正の整数で、boolは不可。同じクール・利用者・Request ID・内容は同じ保存済み結果を返し、違う内容はREQUEST_CONFLICTです。unknownは確定成功が見つからないという意味であり、別IDで再実行してはいけません。旧クールのunknownはclosed_round=trueとし、新クールへ再送しません。

## 操作

| operation | arguments |
|---|---|
| register | handle（通常はsession時に自動登録） |
| buy / sell / quote_trade | goods_id, quantity（quote_tradeはsideも必要） |
| invest | industry, paid_credits |
| navigate / quote_navigation | destination_id, mode, level |
| donate | route_id, paid_credits |
| buy_ship | ship_id |
| dock / insure / bankrupt | {} |
| status / market / production / development / routes / shipyard / flight / news | {} |
| map / score / rankings / hall / rounds / exploration | {} |

modeはnormal/warp、通常航行のlevelはnull、warpのlevelはゲーム設定内の識別子です。価格・最終資金・開発効果・イベント結果をクライアントが指定する窓口はありません。ゲームエンジンの入力型と制約を引き続き検証します。航行中はnews/status/flight/mapの参照と接続管理・表示設定だけが利用可能です。

## エラーと運用

AUTH_FAILED / SESSION_EXPIREDは資格情報またはセッションを再確認します。WORLD_TARGET_MISMATCHは現行クールへ再接続します。設定異常では自動修正せず管理者が診断を確認します。RETRY_SAME_REQUEST / 応答喪失 / SERVER_ERRORは結果照会後に同一要求だけを再送します。RATE_LIMITED / REQUEST_TOO_LARGEは設定した入力・頻度制約による拒否です。

管理APIは公開しません。サイト発行・更新・失効、正規参照の発行、宇宙とクールの操作はOS上の管理CLIを使用します。マスターDB、参照鍵、TLS秘密鍵へのOS権限が最上位の信頼境界です。侵害されたBBSの自サイト内ユーザーなりすましはBBS認証の責務ですが、他サイトのセッション・資金やゲーム計算結果を指定する権限はありません。

実装箇所: starroute/network.py, network_security.py, master.py。クライアント: starroute_bbs/client.py。運用はPHASE5_COMPLETE.mdを参照。
