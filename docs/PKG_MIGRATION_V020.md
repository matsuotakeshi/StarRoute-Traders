# v0.19.0手動配置からv0.20.0のpkg管理へ

この文書は実行手順です。本番での実施記録ではありません。今回の対象はStarRoute Traders本体とDoorです。Liner notes本体のPorts/pkg化は別工程です。

会話で確認済みの構成を使用します。現在も同じパス・スタンドアロン構成かを最初に確認してください。

| 対象 | パス |
|---|---|
| Door | `/usr/local/libexec/liner-notes/starroute-door` |
| Door登録 | `/usr/local/etc/liner-notes/doors.conf` |
| 既存設定 | `/usr/local/etc/starroute-traders/door.json` |
| DB | `/var/db/starroute-traders/world/game.db` |
| 参照鍵 | `/var/db/starroute-traders/world/reference.key` |
| サイト設定 | `/var/db/starroute-traders/world/site-profile.json` |
| 旧プログラム | `/usr/local/share/starroute-traders/0.19.0` |
| BBS実行ユーザー | `liner_notes` |

既存Door番号1、作業ディレクトリ、DB、鍵、設定、宇宙、クールは維持します。今回はmasterパッケージをインストールせず、サービスも追加しません。新規宇宙生成・init・クール切替・鍵再発行・DB移行は不要です。DBスキーマは11のままです。

## 1. ファイルを転送する

Privateリポジトリの `distribution/starroute-traders-0.20.0-freebsd.zip` を、既存のファイル転送手段で本番の `/root/starroute-traders-0.20.0-freebsd.zip` に置きます。GitHubの通常のログインパスワードをgitのHTTPS認証へ入力しないでください。ブラウザーからのPrivateファイル取得、既存SSH接続、既存の転送設定を利用できます。

このZIPのSHA-256は次の値です。信頼できるこの文書の値と、転送後の値を比較します。

```text
592aefcc0482386c5473815e266b5f655ad0352a2e6124907457973f07f730b5
```

FreeBSDのrootで、以下は同じ`sh`セッション内で順番に実行します。エラーが出たらその段階で止めます。

```sh
/bin/sh
set -eu
umask 077
ZIP=/root/starroute-traders-0.20.0-freebsd.zip
EXPECTED=592aefcc0482386c5473815e266b5f655ad0352a2e6124907457973f07f730b5
test "$(sha256 -q "$ZIP")" = "$EXPECTED"
STAGE=$(mktemp -d /root/starroute-v0200-pkg.XXXXXX)
tar -xf "$ZIP" -C "$STAGE"
printf '展開先: %s\n' "$STAGE"
freebsd-version -u
uname -m
```

配布pkgはFreeBSD 15.1 amd64で構築しました。異なる環境ではABI検査を無効化せず、その環境用にPortsから構築します。同梱の署名鍵は検証用公開鍵です。初回は検証済みローカルpkgを使用し、検証用repoを本番の恒久的な信頼先へ登録しません。

## 2. 現在の構成を確認する

```sh
DOOR=/usr/local/libexec/liner-notes/starroute-door
DB=/var/db/starroute-traders/world/game.db
test -x "$DOOR"
test -f "$DB"
test -d /usr/local/share/starroute-traders/0.19.0
id liner_notes
grep -n 'starroute-door' /usr/local/etc/liner-notes/doors.conf
/usr/local/bin/python3.12 -I - <<'PY'
import json
from pathlib import Path
c = json.loads(Path('/usr/local/etc/starroute-traders/door.json').read_text())
expected = {
    'mode': 'standalone',
    'database': '/var/db/starroute-traders/world/game.db',
    'reference_key': '/var/db/starroute-traders/world/reference.key',
    'profile': '/var/db/starroute-traders/world/site-profile.json',
}
assert all(c.get(k) == v for k, v in expected.items()), '構成が手順と異なります'
for k in ('database', 'reference_key', 'profile'):
    assert Path(c[k]).is_file(), k
print('既存スタンドアロン構成を確認しました。認証情報は表示していません。')
PY
```

## 3. ゲームへの新規入場を止め、バックアップする

ゲーム利用者に終了してもらいます。Liner notes本体は継続稼働でき、Doorだけ新規起動不可にします。既存セッションは実行権限を外しても終了しないため、全員退出するまで待ちます。定期tick等を別途設定した場合も停止します。未確定要求がある場合は結果を確認してから進めます。

```sh
MIG=$(mktemp -d /root/starroute-pkg-migration.XXXXXX)
cp -p "$DOOR" "$MIG/starroute-door.before"
cp -p /usr/local/etc/liner-notes/doors.conf "$MIG/doors.conf.before"
pkg query '%n-%v' > "$MIG/packages.before.txt"
printf '復旧用ディレクトリを控えてください: %s\n' "$MIG"
chmod 0644 "$DOOR"
while pgrep -u liner_notes -f 'starroute-door|starroute_bbs|starroute-master'; do
    echo 'ゲームの既存セッションの終了を待っています。'
    sleep 5
done
```

上の検索がPIDを返す間は次へ進みません。別アカウントのCLI・保守処理等の書き込みがないことも確認します。`pkill python`等で他のサービスを巻き込まないでください。以下では権限700の復旧用ディレクトリへDB・認証情報を含む非公開バックアップを保存します。Gitや配布物には含めません。

```sh
export MIG
tar -cpf "$MIG/state-and-config.tar" -C / \
    var/db/starroute-traders usr/local/etc/starroute-traders
/usr/local/bin/python3.12 -I - <<'PY'
import os, sqlite3
from pathlib import Path
source = Path('/var/db/starroute-traders/world/game.db')
target = Path(os.environ['MIG']) / 'game.before.db'
fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
os.close(fd)
db = sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)
backup = sqlite3.connect(target)
try:
    db.backup(backup)
    assert backup.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert not backup.execute('PRAGMA foreign_key_check').fetchall()
finally:
    backup.close()
    db.close()
print('DBバックアップ・整合性確認完了')
PY
```

## 4. 初回pkgインストール

初回移行は`pkg upgrade`ではなく`pkg install`です。FreeBSD公式リポジトリは無効化しません。依存のPython・SQLiteは既存の公式配布元から取得します。`-n`で提案される変更を確認し、無関係なパッケージ削除・置換があれば実行せず調査してください。

```sh
pkg install -n \
    "$STAGE/repo/All/starroute-traders-client-0.20.0.pkg" \
    "$STAGE/repo/All/starroute-traders-0.20.0.pkg"

pkg install \
    "$STAGE/repo/All/starroute-traders-client-0.20.0.pkg" \
    "$STAGE/repo/All/starroute-traders-0.20.0.pkg"

pkg info -g 'starroute-traders*'
pkg check -s -g 'starroute-traders*'
/usr/local/bin/starroute-door --help
/usr/local/bin/starroute-maintain --db "$DB" check
```

pkgは既存の`door.json`を変更しません。`standalone.json.sample`や`game.json.sample`を既存設定へ上書きしないでください。新しい長時間航行・世界イベント設定は新規宇宙用で、今回の移行だけでは既存宇宙のルールを変更しません。

## 5. Doorラッパーの起動先だけ切り替える

以下はpkgが選んだPythonのパスを起動ファイルから取得し、既存設定をそのまま使用するラッパーを作ります。BBSから渡されるユーザー識別環境変数もそのまま渡します。

```sh
SRT_PY=$(sed -n '1s/^#!//p' /usr/local/bin/starroute-door | awk '{print $1}')
test -x "$SRT_PY"
NEXT=$(mktemp /usr/local/libexec/liner-notes/starroute-door.pkg.XXXXXX)
{
    printf '#!%s -I\n' "$SRT_PY"
    cat <<'PY'
import os
os.execv('/usr/local/bin/starroute-door', [
    'starroute-door', '--config', '/usr/local/etc/starroute-traders/door.json'
])
PY
} > "$NEXT"
chown root:wheel "$NEXT"
chmod 0755 "$NEXT"
mv -f "$NEXT" "$DOOR"
cmp -s "$MIG/doors.conf.before" /usr/local/etc/liner-notes/doors.conf
```

この`mv`でDoorの新規起動が再開します。管理者が試遊できる保守時間に実施します。既存`doors.conf`のパスが変わらないため、Liner notesの再起動は通常不要です。Liner notesをrootで再起動しないでください（Door起動を拒否する既存仕様）。

## 6. Telnetで確認する

1. 通常のBBSログインからDoor 1を起動。
2. 星図・所持金・貨物・現在地が以前の状態であることを確認。
3. 市場、日英切替、80×24とNAWS、WHO、順位・殿堂を確認。
4. QでBBSへ戻り、再入場して同じ状態を確認。
5. 必要な少額交易は合意したアカウントで実施し、既存ゲームへ影響する操作であることを意識する。

```sh
/usr/local/bin/starroute-maintain --db "$DB" check
cmp -s "$MIG/doors.conf.before" /usr/local/etc/liner-notes/doors.conf
pkg create -o "$MIG" starroute-traders-client starroute-traders
```

今回の隔離試験はWindows/FreeBSD各485件、実pkg更新・復旧、Telnet試遊まで成功しています。本番で同じ結果になることを事前に実測したものではありません。試験用スクリプトを本番DBへ向けて実行しないでください。

## 7. 初回移行から元の手動配置へ戻す

旧コードと旧ラッパーを保存しているため、DBを巻き戻さず起動先を戻せます。ゲーム新規入場を止め、既存ゲーム利用者が退出してから実施します。`MIG`を失った場合は、控えた実際の復旧ディレクトリを指定し直します。

```sh
chmod 0644 "$DOOR"
# ゲーム利用者・CLI・保守処理の終了を確認してから続行
/usr/local/bin/starroute-maintain --db "$DB" check \
    --supported-max-schema 11 --supported-rules-version phase3-complete-1
BACK=$(mktemp /usr/local/libexec/liner-notes/starroute-door.rollback.XXXXXX)
cp -p "$MIG/starroute-door.before" "$BACK"
mv -f "$BACK" "$DOOR"
```

旧ラッパーを戻した後、Telnetから確認します。新しい`world-time-1`宇宙へ切り替えた場合は上の互換性検査が失敗するため、この方法では戻しません。DBバックアップの復元は、バックアップ後に確定した取引を失う可能性があるので、自動では実施しません。

pkgを撤去する場合は、旧ラッパーがpkgの起動ファイルを参照していないことを確認してから以下を実行します。`pkg autoremove`は今回実施しません。

```sh
pkg delete starroute-traders starroute-traders-client
```

## 8. 次回以降の署名付きrepo運用

初回のローカルpkg導入でpkg管理は開始できます。継続更新用repoは、本番用の署名鍵を管理するビルド環境で作成します。同梱の検証用公開鍵を恒久設定へ流用しません。

以下は**本番BBSではなくビルド・署名用FreeBSD環境**での例です。新しい鍵は管理者の承認のもと一度だけ作り、後のリリースでは保管済み鍵を使います。既存鍵を上書きしません。

```sh
/bin/sh
set -eu
umask 077
KEYDIR=/root/starroute-signing
PUBDIR=/root/starroute-publish-v0.20.0
test ! -e "$KEYDIR"
test ! -e "$PUBDIR"
mkdir -m 700 "$KEYDIR" "$PUBDIR"
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 \
    -out "$KEYDIR/repository.key"
openssl pkey -in "$KEYDIR/repository.key" -pubout \
    -out "$PUBDIR/repository.pub"
mkdir "$PUBDIR/repo" "$PUBDIR/repo/All"
# SRCは検証済み成果物の展開先へ置換
SRC=/path/to/starroute-traders-ports-release
cp "$SRC/repo/All/"starroute-traders*.pkg "$PUBDIR/repo/All/"
pkg repo "$PUBDIR/repo" "rsa:$KEYDIR/repository.key"
sha256 -q "$PUBDIR/repository.pub"
```

`repo/`と`repository.pub`だけを信頼できる既存経路で本番へ転送し、公開鍵ハッシュを署名環境の値と照合します。秘密鍵は転送しません。本番では `/var/db/starroute-pkg-repo/v0.20.0/` にrepoの中身（All、meta.conf、data.pkg等）を配置し、公開鍵を `/usr/local/etc/pkg/keys/starroute.pub` に置きます。両ディレクトリの準備・転送は既存データと混ぜず行います。

```sh
# 本番上：repoと公開鍵を配置・照合した後
install -d -m 0755 /usr/local/etc/pkg/repos
test ! -e /usr/local/etc/pkg/repos/StarRoute.conf
cat > /usr/local/etc/pkg/repos/StarRoute.conf <<'CONF'
StarRoute: {
  url: "file:///var/db/starroute-pkg-repo/v0.20.0",
  enabled: yes,
  signature_type: "pubkey",
  pubkey: "/usr/local/etc/pkg/keys/starroute.pub"
}
CONF
chmod 0644 /usr/local/etc/pkg/repos/StarRoute.conf
pkg update -r StarRoute
pkg rquery -r StarRoute '%n %v'
pkg install -n starroute-traders
```

次の版では新repoを別ディレクトリへ転送・検証し、明示的にURLを更新してから、Door入場停止・バックアップの後に以下を実行します。公式repoを有効なままにして依存を解決します。`-r StarRoute`だけに限定すると、そのrepoにない新しい依存を取得できない場合があります。

```sh
pkg upgrade -n -g 'starroute-traders*'
pkg upgrade -g 'starroute-traders*'
/usr/local/bin/starroute-maintain --db /var/db/starroute-traders/world/game.db check
```

repoにはStarRouteの3パッケージだけを置きます。公式Python等を独自repoで置き換えません。サンプル設定・宇宙を自動適用しません。

参考：[pkg-install(8)](https://man.freebsd.org/cgi/man.cgi?query=pkg-install&sektion=8)、[pkg-repository(5)](https://man.freebsd.org/cgi/man.cgi?query=pkg-repository&sektion=5)。
