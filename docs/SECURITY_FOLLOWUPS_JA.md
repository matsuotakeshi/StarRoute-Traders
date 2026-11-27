# セキュリティ監査後の移行手順

## Inter-BBS

通常のDoorは既存のサイトプロファイルでログインできます。離脱とサイト単位の結果照会には別の運用者用資格を発行します。

```sh
umask 077
starroute-sites --db /path/to/game.db --reference-key /path/to/reference.key \
  operator --bbs-id SITE --output /admin-only/operator-new.json
```

資格ファイルは認証済みの経路でサイト管理者に届け、管理者専用のディレクトリに置きます。Nodeの設定には `operator_credential_file` としてこのパスだけを記載します。Doorの実行UIDにはファイルと親ディレクトリの閲覧・通過権限を付与しません。再発行すると前の運用者用資格は失効します。サイトの無効化はゲーム用と運用者用の両方に適用されます。

新しいクールは終了時に公開用の発見者索引を作ります。更新前に作成したアーカイブがある場合は、バックアップを取った上で管理者が `starroute-admin --db /path/to/game.db index-arrivals` を実行します。再実行できます。現行DBと非公開アーカイブは保持します。APIは最大100件ずつ返し、次のページは前のページの末尾の `round_id` と `rank` を `after_round` と `after_rank` に渡します。

Door起動時に旧世代の公開キャッシュを削除します。旧世代のバックアップを保管する場合は管理者専用領域で扱ってください。本人に表示する情報はオンライン中に受信端末へ送ります。

## FreeBSDのリリース工程

1. クリーンなPortsビルド環境で、client、本体、masterの順にビルドします。依存先のpkgをビルド環境に登録してから後続を作ります。
2. `python3 scripts/verify_pkg_dependencies.py /absolute/path/to/All` で、生成した3つのpkgの依存名・origin・版を確認します。クリーンなjailでは署名済みリポジトリからmasterを選び、本体とclientが解決されることも確認します。
3. 本番更新は既存の署名付きpkgリポジトリを第一選択とします。導入ZIPを別途出荷する場合は、発行環境で detached signature を作成し、信頼済みの公開鍵をZIPと独立した管理経路で配布します。

```sh
# 発行側
openssl dgst -sha256 -sign /signing-only/publisher.key -out kit.zip.sig kit.zip
# 導入側。展開やpkg実行の前に検証する
sh /trusted/verify_release_kit.sh /staging/kit.zip /staging/kit.zip.sig /trusted/publisher.pem
```

署名の検証が失敗した場合は導入を停止します。新宇宙の作成スクリプトは `--seed-stdin` に対応する同梱のジェネレーターと組み合わせて使います。旧ジェネレーターの `--seed` は公開のテスト値に使用できます。Python wheelの配布記録には使用したPythonとビルド環境で解決したsetuptoolsの版を保存します。

## Native CI

LANのランナーは、通常のPR起動条件に加えて、先端を設定したイベントの送信者と起動主体がリポジトリ所有者であることを確認します。外部ランナーに導入済みのroot所有の事前フックは、対象の変更を承認した後に管理者が更新し、GitHub側のブランチへの書き込み権限も確認してください。
