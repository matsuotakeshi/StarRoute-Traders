# Private Portsのビルドと運用

本番ホストではなく専用FreeBSDビルド環境で実施します。最新の合否・使用したバージョン・ログは別添の受け入れ記録を参照してください。

## poudriere

専用ビルドVMにpoudriereを用意し、専用設定でBASEFS、DISTFILES_CACHE、Portsツリーを分離します。UFSではNO_ZFS=yesを指定できます。今回の検証ではpoudriere自体も専用ディレクトリにインストールしました。

```sh
# SRC、DISTFILES、PRIVATE_PORTS、CONFは専用領域の実際のパスへ置換
python3 scripts/build_ports_distfile.py --source "$SRC" --output "$DISTFILES" --ports "$SRC/ports"
cp -Rp "$SRC/ports/games/starroute-traders" "$PRIVATE_PORTS/games/"
cp -Rp "$SRC/ports/games/starroute-traders-client" "$PRIVATE_PORTS/games/"
cp -Rp "$SRC/ports/games/starroute-traders-master" "$PRIVATE_PORTS/games/"
poudriere -e "$CONF" jail -c -j srt151 -v 15.1-RELEASE -a amd64
poudriere -e "$CONF" ports -c -p srt -m null -M "$PRIVATE_PORTS"
poudriere -e "$CONF" bulk -j srt151 -p srt games/starroute-traders games/starroute-traders-client games/starroute-traders-master
```

ソースアーカイブはバージョン固定・SHA-256照合です。ローカルdistfileを事前配置するため、存在しないGitHubリリースへのアクセスは行いません。GitHubソース、宇宙データ配布元、pkgリポジトリはそれぞれ独立です。

## pkgリポジトリ

検証は専用jail内のfile://リポジトリで行います。本番では3種類のStarRouteパッケージだけを専用ディレクトリに置き、Python等は公式リポジトリから取得する構成を基本とします。検証用の依存パッケージ一式を、無条件に本番の公式パッケージへ優先させないでください。

署名用秘密鍵は配布サーバ・BBSクライアントへ渡しません。管理者が信頼した公開鍵をリポジトリとは別経路で配布し、次のように設定します。パスは例です。

```text
StarRoute: {
  url: "file:///srv/pkg/starroute",
  enabled: yes,
  signature_type: "pubkey",
  pubkey: "/usr/local/etc/pkg/keys/starroute.pub"
}
```

署名の例（管理者が準備した鍵を使用）:

```sh
pkg repo /srv/pkg/starroute rsa:/private/signing/starroute.key
```

本番用キーは検証用キーとは分離します。鍵更新時には旧鍵・新鍵の承認と配布の順序を管理し、検証失敗時に無署名へ自動フォールバックしません。HTTPS配布へ拡張してもリポジトリ署名を維持します。インターネット公開や本番repo設定は今回自動実施しません。

## インストールと更新

```sh
pkg update -r StarRoute
pkg install -r StarRoute starroute-traders         # スタンドアロン
pkg install -r StarRoute starroute-traders-master  # マスター
pkg install -r StarRoute starroute-traders-client  # 参加BBSのみ
pkg info -g 'starroute-traders*'
```

設定は/usr/local/etc/starroute-traders/*.sampleにあります。既存のdoor.jsonをそのまま参照できます。初期DB・鍵・宇宙の登録は既存の管理手順で明示実行し、初回pkg installだけで生成・有効化しません。新しい長時間航行ルールを使う宇宙はgame.json.sampleをテンプレートとして外部生成し、既存の登録・有効化手順を経由します。

更新はDoor新規入場とゲーム更新を管理者が止め、未応答要求を照会してから実施します。

次の通常更新例は0.20.0以降の保守コマンドが既にある環境向けです。0.19.0から初めて移行する場合は、保守コマンドがまだないため、先に既存PythonのSQLite backup APIでバックアップします。以下のパスは実環境へ合わせ、保存先の親ディレクトリを管理者だけが読める状態で事前作成してください。

```sh
/usr/local/bin/python3.12 -I - <<'PY'
import os, sqlite3
source = '/var/db/starroute-traders/world/game.db'
destination = '/private/backup/game-before-first-pkg.db'
fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
os.close(fd)
c = sqlite3.connect('file:' + source + '?mode=ro', uri=True)
out = sqlite3.connect(destination)
try:
    c.backup(out)
    assert out.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert not out.execute('PRAGMA foreign_key_check').fetchall()
finally:
    out.close()
    c.close()
print('Backup verified')
PY
```

手動配置版から初回移行する場合は `pkg upgrade` ではなく `pkg install` を使います。既存の0.19.0配置ディレクトリとDoorラッパーを残し、pkg版の起動先へ切り替えるのは承認後に管理者が実施してください。今回作成した0.19.0のpkgは更新試験用の再パッケージであり、以前から本番がpkg管理だったという意味ではありません。

```sh
starroute-maintain --db /var/db/starroute-traders/world/game.db check
starroute-maintain --db /var/db/starroute-traders/world/game.db backup --output /private/backup/game-before-upgrade.db
pkg create -o /private/backup/pkg starroute-traders-client starroute-traders starroute-traders-master
pkg upgrade -g -r StarRoute 'starroute-traders*'
starroute-maintain --db /var/db/starroute-traders/world/game.db check
```

DB更新が必要な版では、原本を変更せず移行先コピーを作ります。

```sh
starroute-maintain --db /var/db/starroute-traders/world/game.db migrate-copy --backup /private/backup/pre-migration.db --output /private/staging/migrated.db
```

移行結果・監査記録・整合性を確認し、更新停止中に管理者が参照先を明示切替します。今回のDBスキーマは11のままです。設定・鍵・未確定要求ジャーナルも別途バックアップします。

## 復旧と削除

旧版0.19.0への復旧可否は、スキーマとルールの両方で確認します。

```sh
starroute-maintain --db /private/backup/game-before-upgrade.db check --supported-max-schema 11 --supported-rules-version phase3-complete-1
pkg add -f /private/backup/pkg/starroute-traders-client-0.19.0.pkg /private/backup/pkg/starroute-traders-0.19.0.pkg /private/backup/pkg/starroute-traders-master-0.19.0.pkg
```

新しいworld-time-1ルールのDBは旧版へそのまま渡せません。旧DBへ戻す必要がある場合、バックアップ後に確定した取引との整合性を確認してから復旧します。通常のプログラム更新だけならDBを巻き戻しません。

```sh
pkg delete starroute-traders-master starroute-traders starroute-traders-client
```

運用データ・鍵・ログ・編集済み設定は削除対象に含めません。運用データの完全削除は別の明示操作です。

## Liner notesのDoor起動先

本番への適用承認後、既存ラッパーをバックアップして、既存の `door.json` を指定する起動先だけを変更します。次はPython 3.12を選択した検証環境の例です。BBS本体は従来どおり一般ユーザーで起動します。Liner notesはrootからのDoor起動を拒否します。

```python
#!/usr/local/bin/python3.12 -I
import os
os.execv('/usr/local/bin/starroute-door', [
    'starroute-door', '--config', '/usr/local/etc/starroute-traders/door.json'
])
```

既存の `/usr/local/etc/liner-notes/doors.conf`、作業ディレクトリ、ユーザー識別環境変数は維持します。戻す場合は保存した旧ラッパーへ戻します。旧版非対応の新しい宇宙へ切り替えた後は、単純なラッパー復旧では戻せません。

マスター運用では、専用ユーザーと非公開データ領域を管理者が準備し、`master.json` のDB・鍵・TLS証明書を設定します。その後に限り、以下を実施します。

```sh
sysrc starroute_master_enable=YES
sysrc starroute_master_user=starroute
service starroute_master start
service starroute_master status
# 更新前は管理者が明示停止し、更新後に明示再開
service starroute_master stop
```

pkg自身はサービスを起動・停止しません。参加BBSのみの場合、マスター用ユーザー・DB・秘密情報は配置しません。

## 参考資料

- [FreeBSD Porter's Handbook: Testing with poudriere](https://docs.freebsd.org/en/books/porters-handbook/testing/)
- [USES Python](https://docs.freebsd.org/en/books/porters-handbook/uses/#uses-python)
- [設定ファイルと@sample](https://docs.freebsd.org/en/books/porters-handbook/plist/#plist-config)
- [pkg-repo(8)](https://man.freebsd.org/cgi/man.cgi?query=pkg-repo&sektion=8)
