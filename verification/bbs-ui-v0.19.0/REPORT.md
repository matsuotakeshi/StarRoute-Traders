# BBS UI改修完了 — v0.19.0

独立作業コピーで改修し、受け入れ19項目を確認しました。本番適用・GitHub Pushは実施していません。

- Windows: 468件成功（既存430＋追加38）、失敗0。
- FreeBSD: 468件成功（既存430＋追加38）、失敗0。
- 実Liner notes/Telnet: 日本語/英語、数字売買、実時間の航行・到着・売却、投資・寄付、WHO、ランキング・殿堂、名前切替、80/100/70/50列NAWS、BBS復帰・再入場・Ctrl-]を確認。
- スタンドアロンとTLSマスター経由の購入を実証。SQLite integrity_check/foreign_key_check正常。
- 既存ローカル168ファイル、FreeBSD保護対象3119ファイルのSHA-256は前後一致。
- DBスキーマ変更なし。Liner notes Cソースの追加変更なし。既存Phase 5の隔離NAWS対応runtimeを再利用。

実装・操作・最小サーバ追加・制約・本番適用とロールバックは BBS_UI_COMPLETE.md を参照してください。新UIはv0.19.0マスターと組み合わせます。

FreeBSD検証先: /home/takeshi/starroute-phase5-verification-20261102/ui-release

薄いBBSクライアントZIPにはEngine、DB、秘密宇宙、認証情報を含めていません。スタンドアロンには全体ソースを使います。署名鍵・認証情報は既存の保護された設定から参照してください。

確認価格が変化した売買はサーバで拒否し、再見積り後に再確認します。航行費用やゲームルールの数値は変更していません。極端に小さな端末では省略とページ数が増えます。ANSI非対応時は連続出力になります。

証拠: test-results.json、bbs-ui-acceptance-checklist.json、Windows/FreeBSD全テストログ、freebsd/screensの実端末出力、implementation.diff、変更ファイル一覧。画面PNGは保存済み端末出力の可視化です。
