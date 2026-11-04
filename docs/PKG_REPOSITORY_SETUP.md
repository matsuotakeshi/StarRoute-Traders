# StarRoute署名付きpkg更新先の設定

作成日：2026-11-03（日本時間）。ユーザー承認済み構成：検証VM 10.0.0.50で署名し、本番srvへ手動転送するfile://方式。HTTPサービスは起動しない。srvと検証VMは別のホストとして扱う。

## 作成済みの成果物と検証

- ローカル受け渡し先：`C:\Users\takeshi\Documents\Codex\starroute-pkg-repository-20261103`
- VM受け渡し先：`/home/takeshi/starroute-signed-repo-20261103`
- 署名鍵（VMのrootだけが保持）：`/root/starroute-pkg-signing/repository.key`（RSA 3072 bit、親700・ファイル600）。既存のゲーム鍵は変更していない。
- VMでの公開用生成物：`/root/starroute-pkg-publish-20261103/bundle`
- pkg 2.8.4 / FreeBSD 15.1-RELEASEで、空の隔離pkg台帳への署名検証と3件のカタログ取得に成功。
- 3パッケージを実際にfetchし、元のv0.20.0配布物とのバイト一致を確認。
- 別の公開鍵では署名失敗。別の空台帳にパッケージが登録されないことを確認（終了コードだけに依存しない）。
- ホストのインストール済みpkg一覧は前後一致。ゲームDB・Door・サービスは操作していない。
- 登録スクリプトの`--verify-only`をVM上で実行して成功。`--activate`のsrv実行はユーザーの手動作業であり、まだ実測結果はない。

公開鍵のSHA-256（転送物内の値だけでなく、この値と照合する）：

```text
4a1be877f157f60e26d712f3ae00734445e3bad104be90e9136ec2d1b6978ebd
```

アーカイブ `starroute-pkg-repo-v0.20.0.tar.gz` のSHA-256：

```text
ad5d854342c37f001a6b0b1c29053a8ed21837d96ca1b1e5970be9d78c540314
```

秘密鍵・ゲームDB・認証情報はアーカイブに含まない。アーカイブのハッシュは転送時の破損検出、公開鍵でのrepo検証は署名者の検証として区別する。

## 本番srvでの登録

受け渡し先にある次の2ファイルを、既存の転送手段でsrvの`/root/`へ置く。秘密鍵を転送する必要はない。

1. `starroute-pkg-repo-v0.20.0.tar.gz`
2. `setup_signed_pkg_repo_v020.sh`

信頼済みの本書・スクリプトを使用する。スクリプトは今回のアーカイブと公開鍵のSHA-256を固定している。別のリリースを無条件に受け入れる汎用インストーラーではない。

rootで次を実行する。最初の検証ではシステムのrepo設定やインストール済みpkgを変更しない。ログは表示された`/var/tmp/starroute-repo-check.*`に残る。

```sh
/bin/sh /root/setup_signed_pkg_repo_v020.sh --verify-only \
  /root/starroute-pkg-repo-v0.20.0.tar.gz
```

成功後に登録する。この操作は更新先を登録するだけで、ゲームの更新・再インストール・DB変更・BBS再起動は行わない。

```sh
/bin/sh /root/setup_signed_pkg_repo_v020.sh --activate \
  /root/starroute-pkg-repo-v0.20.0.tar.gz
pkg rquery -r StarRoute '%n %v'
pkg info -g 'starroute-traders*'
/usr/local/bin/starroute-maintain --db /var/db/starroute-traders/world/game.db check
```

カタログには本体・client・masterの3件、現在のインストール一覧には本体・clientの2件が表示される。standaloneではmasterの追加は不要。

作成先：

| 内容 | パス |
|---|---|
| repo | `/var/db/starroute-pkg-repo/v0.20.0` |
| 公開鍵 | `/usr/local/etc/pkg/keys/starroute.pub` |
| 設定 | `/usr/local/etc/pkg/repos/StarRoute.conf` |

設定は`file:///var/db/starroute-pkg-repo/v0.20.0`、`signature_type: "pubkey"`。FreeBSD公式repoは変更しない。既存の上記パスがあれば上書きせず停止する。途中エラーでもパッケージ更新は実行していないため、ゲームは既存版で継続できる。

登録中断後は表示されたログと3つの作成先を確認する。再実行のために既存ディレクトリや鍵を削除しない。既に正常登録済みなら再登録は不要。設定だけ無効に戻す場合は、他の管理作業がないことを確認して次を実行する。ゲームやpkgを削除しない。

```sh
# StarRoute.confが今回作成した設定であることを確認した場合だけ実行
/bin/sh -c 'set -eu; test ! -e /usr/local/etc/pkg/repos/StarRoute.conf.disabled; mv /usr/local/etc/pkg/repos/StarRoute.conf /usr/local/etc/pkg/repos/StarRoute.conf.disabled'
```

## 次のバージョンを配布するとき

1. 対象FreeBSD ABIの新pkgを独立環境で構築・検証する。
2. VMの新しい版別ディレクトリへStarRouteの3pkgだけを配置する。公式のPython等を混ぜない。
3. **今回作成した同じ秘密鍵**で`pkg repo`を実行する。リリースごとに鍵を作り直さない。
4. 空の隔離pkg台帳で署名・全pkgのfetch・バイト一致を確認する。
5. 公開repoのみsrvの新しい版別ディレクトリへ転送する。既存repoを直接書き換えない。
6. srvでも隔離台帳で検証し、保存した旧設定を戻せるようにして、`StarRoute.conf`のURLを新しい版へ切り替える。公開鍵は維持する。
7. `pkg update -r StarRoute`後にカタログの対象版を確認する。Door入場停止、既存セッション終了、DB・設定バックアップを行ってから更新する。

署名コマンド（VM上、新しい版のrepoを用意した後。`NEW_REPO`はその実パス）：

```sh
: "${NEW_REPO:?新しい版専用repoの絶対パスを設定してください}"
test -d "$NEW_REPO/All"
test -f /root/starroute-pkg-signing/repository.key
pkg repo "$NEW_REPO" rsa:/root/starroute-pkg-signing/repository.key
```

本番の更新計画確認と実行（新しい版を配布してから使用する）：

```sh
pkg update -r StarRoute
pkg rquery -r StarRoute '%n %v'
pkg upgrade -n -g 'starroute-traders*'
# 対象版と依存の変更内容を確認し、入場停止・バックアップの後に実行
pkg upgrade -g 'starroute-traders*'
/usr/local/bin/starroute-maintain --db /var/db/starroute-traders/world/game.db check
```

`-r StarRoute`でインストール対象repoを限定すると公式repoの依存を取得できない場合があるため、更新実行はrepoを限定しない。対象パッケージと版をdry-runで確認する。v0.20.0導入済みの現在はアップグレードを実行する必要はない。

これは手動転送型の更新先であり、GitHubから新しい版を自動取得するものではない。署名鍵の非公開バックアップとVMの保護は管理者の運用項目。鍵を紛失した場合、同名で再生成して続行せず、新鍵の承認・公開鍵配布を別途行う。

参考：[pkg-add(8)](https://man.freebsd.org/cgi/man.cgi?query=pkg-add&sektion=8&apropos=0)、[pkg-repo(8)](https://man.freebsd.org/cgi/man.cgi?query=pkg-repo&sektion=8)、[pkg-repository(5)](https://man.freebsd.org/cgi/man.cgi?query=pkg-repository&sektion=5)。
