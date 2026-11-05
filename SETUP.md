# 導入・運用手順

[README](README.md) / [構成・移植ガイド](PORTING.md)

対象はDell Wyse 3040、Debian 13 amd64、systemd、NetworkManager、ext4です。以下は管理者向けの手動配置手順で、一括自動インストーラーではありません。新規導入の全工程を保証するものではなく、対象機器で動作を確認してください。Raspberry Pi等は先に移植ガイドを参照してください。

ホスト名 `wyse-usbip` とWi-Fiアドレス `10.42.0.1/24` は構成例です。既存LANと重複しないアドレスを選びます。設定領域の作成は対象パーティションのデータを消去するため、インストール時に専用領域を確保してください。

## 接続と操作

HTTPは80番、HTTPSは443番です。`http://機器名またはIP/` と `https://機器名またはIP/` はシステム状態へ移動します。共有一覧・履歴・システム状態は認証不要、設定画面はHTTPSのBasic認証が必要です。

- [システム状態](http://wyse-usbip.local/system.py)
- [USB共有一覧](http://wyse-usbip.local/usbip.py)
- [Web管理](https://wyse-usbip.local/network.py)（ユーザー名 `admin`、自己署名証明書）
- Windowsの `usbip-win2` は `wyse-usbip.local` のTCP 3240へ接続します。

USBは挿すと自動共有されます。HIDを含む機器、USBハブ、Wyse側でマウント中のストレージは除外します。共有停止・再開はWeb管理画面から機器ごとに操作できます。使用中はWindowsで切断してから停止します。停止は抜き差しや再起動で解除されます。

本体メニューで最後に確定した単独／既存LANモードが次回起動時に適用されます。単独モードはWi-Fi親機とDHCP配布を有効にします。既存LANモードは親機とWyse側のDHCP配布を停止します。WebからIP・SSIDを変更した場合は新しいIPで開き直し、120秒以内に確定します。ネットワーク初期化では有線DHCP、SSID `wyse`、Wi-Fi管理IP `10.42.0.1/24` に戻ります。確定しなければ有線・Wi-Fiとも試用前へ戻ります。Wi-Fiのセキュリティ、機器名、モード、管理者認証、OS保護は初期化の対象外です。

## 1. Debianとネットワークを準備

Debian 13 amd64のnetinstを使い、SSH serverとstandard system utilitiesを選びます。デスクトップ環境は不要です。本体コンソールを使える状態で作業し、以下はrootシェルで実行します。

APTは [debian.sources](scripts/debian.sources) を `/etc/apt/sources.list.d/debian.sources` に配置します。通常・更新・セキュリティをDebian公式のHTTPSで取得し、Debianのアーカイブ鍵を指定します。既存の `/etc/apt/sources.list` が同じ取得先を定義している場合は退避し、重複登録を避けます。

```sh
apt update
apt install python3 python3-dbus network-manager wpasupplicant dnsmasq-base \
  usbip lighttpd lighttpd-mod-openssl openssl overlayroot \
  avahi-daemon libnss-myhostname firmware-libertas
ip -br link
nmcli device status
```

現行コードの対象は有線 `enp1s0`、無線 `mlan0` です。名前が異なる場合は、以下のコマンドと `network-trial.py`、Avahiの対象インターフェースを合わせます。Debianのインストーラーが有線をifupdownで管理している場合は、本体コンソールから `ifdown enp1s0` を実行し、`/etc/network/interfaces` を退避した上で有線の `allow-hotplug` と `iface` の行を外します。ループバックと `source` の行は保持します。以下は新規プロファイルを作る場合の手順です。

```sh
systemctl enable --now NetworkManager
systemctl restart NetworkManager
nmcli con add type ethernet ifname enp1s0 con-name wyse-lan \
  connection.uuid 9f2e56cf-5d10-4d5b-a03e-efed733fd464 ipv4.method auto
nmcli con add type wifi ifname mlan0 con-name wyse ssid wyse \
  connection.uuid 12130d96-e908-42ce-9561-1ae5bd132282 \
  802-11-wireless.mode ap 802-11-wireless.band bg \
  ipv4.method shared ipv4.addresses 10.42.0.1/24 ipv6.method disabled
nmcli con up wyse-lan
nmcli con up wyse
```

UUIDは管理コードと本体メニューで参照します。Wi-FiパスワードはWeb管理から設定できます。有線のDHCPアドレスは本体画面か `ip -br -4 a` で確認します。

携帯回線モデムを使わない構成では `systemctl mask --now ModemManager.service` を実行します。戻す場合はOS保護を無効にして起動し、`systemctl unmask ModemManager.service` と `systemctl enable --now ModemManager.service` を実行します。

## 2. USB/IPとWeb管理を配置

[scripts](scripts/) に移動して配置します。lighttpdドキュメントルート `/var/www/html` を前提にしています。

```sh
install -m755 usbip-auto-share /usr/local/sbin/
install -m755 usbip-history.py /usr/local/sbin/wyse-usb-history
install -m644 VERSION /var/www/html/VERSION
install -m755 usbip-status.py /var/www/html/usbip.py
install -m755 system-status.py /var/www/html/system.py
install -m755 network-settings.py /var/www/html/network.py
install -m755 network-request.py /usr/local/sbin/wyse-network-request
install -m755 web-password.py /usr/local/sbin/wyse-web-password
install -m755 network-trial.py /usr/local/sbin/wyse-network-trial
install -m755 os-update.py /usr/local/sbin/wyse-os-update
install -D -m644 wyse-update.conf /etc/systemd/system/usbipd.service.d/wyse-update.conf
install -m755 console.py /usr/local/sbin/wyse-console.py
install -m755 overlay-remount.sh /usr/local/sbin/wyse-overlay-remount
install -m644 ./*.service wyse-network.socket /etc/systemd/system/
install -m644 90-usbip-auto.rules /etc/udev/rules.d/
install -m644 90-wyse-usbip.conf /etc/lighttpd/conf-available/
for conf in 90-wyse-usbip.conf; do
  ln -sfn "../conf-available/$conf" "/etc/lighttpd/conf-enabled/$conf"
done

umask 077
test -s /root/wyse-web-password || openssl rand -hex 16 > /root/wyse-web-password
{ printf 'admin:'; openssl passwd -apr1 -stdin < /root/wyse-web-password; } > /etc/lighttpd/wyse.htpasswd
chgrp www-data /etc/lighttpd/wyse.htpasswd
chmod 640 /etc/lighttpd/wyse.htpasswd
if [ ! -s /etc/lighttpd/wyse.key ]; then
  openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes -days 825 \
    -subj /CN=wyse-usbip.local -addext subjectAltName=DNS:wyse-usbip.local,IP:10.42.0.1 \
    -keyout /etc/lighttpd/wyse.key -out /etc/lighttpd/wyse.crt
fi
systemctl daemon-reload
systemctl enable --now usbipd.service wyse-network.socket wyse-usb-history.service
systemctl enable lighttpd.service wyse-console.service wyse-os-update.service
udevadm control --reload
```

初回セットアップは、本体コンソールまたはSSHで本書のコマンド・スクリプトを実行します。初回起動時に自動で初期設定ウィザードが開く方式ではありません。SSHを利用する場合は、Debianのインストール時にSSH serverを選択し、設定したOSユーザーで接続してください。Web管理の認証とは別です。

Web管理のユーザー名は `admin` です。初期パスワードはセットアップ時にランダムに生成され、機器共通の固定値ではありません。本体コンソールまたはSSHで次のコマンドを実行して確認します。

```sh
sudo cat /root/wyse-web-password
# rootで操作中の場合は sudo を付けずに実行
```

次節の永続設定とWeb管理の有効化を完了した後、ブラウザーで管理画面にログインし、設定画面の「管理パスワード」から任意の値へ変更できます。このファイルは初回発行値の記録であり、Webで変更・本体で再発行した後の現在値を示すものではありません。パスワードが分からなくなった場合は、本体メニューの `Reset Web admin password` で再発行し、画面に表示された新しい値を使用します。詳しくは本書の「管理パスワードの変更・本体からの初期化」を参照してください。

Web管理の認証設定は次節で永続保存領域を準備してから有効にします。USBは抜き差しするか再起動して共有を確認します。本体メニューは次回起動時からtty1で表示されます。

## 3. 永続設定、名前解決、OS保護

1. `lsblk -f` で内蔵ストレージを特定し、設定用に空のext4パーティションを用意してラベルを `WYSECFG` にします。転用する場合は対象のデバイス・用途・UUIDを照合し、対象だけを `swapoff` してから `mkfs.ext4 -L WYSECFG 対象デバイス` を実行し、旧スワップ行を `/etc/fstab` から除きます。フォーマットで対象領域の内容は消去されます。
2. OS保護が無効でルートがext4の状態で `sh install-settings-volume.sh` を実行します。設定領域を `/var/lib/wyse-settings` にマウントし、NetworkManagerの設定をそこに置きます。既存の設定領域を再利用する場合は、スクリプト実行前に保存済みのプロファイルを確認します。`LABEL=WYSECFG` 行の待機時間は `x-systemd.device-timeout=30s` を使用します。既存のfstab行はスクリプトの再実行では変更されないため、必要に応じて手動で合わせます。
3. Avahiによる `.local` 公開は、Debianの `avahi-daemon` パッケージが配置する `/etc/avahi/avahi-daemon.conf` を編集します。このファイルは本プロジェクトには同梱しません。下の表の項目を該当セクション内で変更または追加し、同じ項目を重複させないでください。既存のライセンスコメントと、それ以外の設定は保持します。

   | セクション | 項目 | 値 |
   | --- | --- | --- |
   | `[server]` | `use-ipv4` | `yes` |
   | `[server]` | `use-ipv6` | `no` |
   | `[server]` | `allow-interfaces` | `enp1s0,mlan0` |
   | `[publish]` | `publish-hinfo` | `no` |
   | `[publish]` | `publish-workstation` | `no` |
   | `[publish]` | `publish-aaaa-on-ipv4` | `no` |

   インターフェース名は `ip -br link` で確認した実機の名前に合わせます。設定後、下のコマンドで名前公開と保守起動を準備します。旧スワップの復帰先を探して起動が遅れるのを防ぐため、スワップ転用時は `RESUME=none` を使います。

```sh
sh install-web-auth.sh
install -D -m644 wyse-web-auth.conf /etc/systemd/system/lighttpd.service.d/wyse-web-auth.conf
install -m644 89-wyse-network.conf /etc/lighttpd/conf-available/
ln -sfn ../conf-available/89-wyse-network.conf /etc/lighttpd/conf-enabled/89-wyse-network.conf
lighttpd -tt -f /etc/lighttpd/lighttpd.conf
install -D -m644 wyse-hostname.conf /etc/systemd/system/avahi-daemon.service.d/wyse-hostname.conf
install -m644 wyse-recovery.cfg /etc/default/grub.d/wyse-recovery.cfg
printf 'GRUB_TIMEOUT=1\n' > /etc/default/grub.d/wyse-fast-boot.cfg
printf 'RESUME=none\n' > /etc/initramfs-tools/conf.d/resume
update-initramfs -u
update-grub
grub-script-check /boot/grub/grub.cfg
systemctl daemon-reload
systemctl enable wyse-hostname.service wyse-overlay-rw.service
systemctl enable --now avahi-daemon.service
systemctl restart avahi-daemon lighttpd
```

Web管理から機器名を `wyse-usbip` に保存し、Windowsから名前解決を確認します。Wi-Fiを使う場合はWPA2パスワードもここで設定します。次に本体メニューで「Enable OS protection on next boot」を選んで再起動します。更新作業は「Disable OS protection on next boot」を選んで再起動してから行います。起動時の保守入口はGRUBのAdvanced options内のrecovery modeです。

## 4. 確認と戻し方

- `systemctl is-active usbipd lighttpd avahi-daemon wyse-console wyse-network.socket` を確認します。
- Windowsで `usbip.exe list -r wyse-usbip.local` を実行し、一覧・接続・切断と、Webでの共有停止・再開を確認します。
- `findmnt -no SOURCE,VFS-OPTIONS -T /media/root-ro` が `ro`、`findmnt -no SOURCE -T /etc/NetworkManager/system-connections` が設定領域を指すことを確認します。
- 両モードの再起動、ネットワーク設定の確定と120秒後の復旧、OS保護有効での電源断復帰を確認します。
- 更新から戻す場合はOS保護を無効にして起動し、更新前に退避した対象ファイルを戻します。プロファイルが原因でWebに入れない場合は本体メニューと有線側のIPv4を確認します。

## 日常の運用

### USB共有・復旧・接続履歴

- 自動共有は機器を固定せず、情報の準備待ちや一時失敗を最大6回再試行します。失敗理由はjournalで確認できます。
- エラー状態の機器は認証済み設定画面の「共有を復旧」で再共有できます。正常待機中・使用中の機器には実行できません。失敗して停止状態になった場合は「共有を再開」を使用します。Windows側での再接続は別途必要です。
- ハブや接続ポートを変えるとバスIDが変わる場合があります。Windows側で一覧を更新し、新しいIDへ接続してください。
- 接続履歴は `/run/wyse-usb-history/history.json`（RAM）に最大200件保存し、本体の再起動で消えます。履歴サービスだけの再起動では維持します。
- 履歴は0.5秒間隔の検出結果です。短時間の接続や監視停止中の操作は取りこぼす場合があります。「使用中を検出」は検出時刻であり接続開始時刻ではありません。接続元PCのIPは記録しません。

### システム状態とバージョン

管理ソフトの版は `scripts/VERSION`（現在1.1.0）で管理し、`/var/www/html/VERSION` へ配置します。OS・カーネルの版は実行中のOSから取得します。

システム状態は機器名、管理ソフト版、OS・カーネル、稼働時間、RAM使用量、OS保護、主要サービス、有線・Wi-FiのIPとSSIDを表示します。ページを開く／更新するたびに取得し、Wi-Fiキーや管理者パスワードは表示しません。

### 管理パスワードの変更・本体からの初期化

Web設定画面の「管理パスワード」で、現在のパスワードと新しいパスワード・確認入力を送信します。新しい値は半角英数字・記号5〜64文字（空白なし）。ユーザー名は `admin` のままで、SSHユーザーのパスワードには影響しません。変更後、次回アクセス時にブラウザーの認証欄へ新しい値を入力してください。

忘れた場合はWyse本体のコンソールで `Reset Web admin password` を選択し、確認画面でYを押します。ランダムな16文字の新パスワードをその画面に表示します。Rキーで表示を消せます。固定の共通初期パスワードには戻しません。この初期化操作はWebの要求受付には登録していません。rootでの保守時は `/usr/local/sbin/wyse-web-password reset` も利用できます（標準出力に新しい値が出るためログ採取中には実行しないでください）。

ハッシュは `/var/lib/wyse-settings/web-auth/htpasswd` に保存し、同ディレクトリを `/etc/lighttpd/wyse-auth` へbind mountします。ディレクトリはroot:www-data 750、ファイルはroot:www-data 640です。保存先がext4・書込可能・正しいbind mountであることを確認し、一時ファイルからの置換とfsyncで保存します。新規値はSHA-512 crypt形式。既存APR1ハッシュは変更前の認証に対応します。平文の新パスワードはファイルやコマンド引数へ保存しません。OS保護中でも再起動後まで保持されます。

`install-web-auth.sh` は旧 `/etc/lighttpd/wyse.htpasswd` から初回だけ移行します。再実行で既存のパスワードを上書きしません。lighttpdのdrop-inが認証保存先のマウント完了を待ちます。認証ファイルはWebドキュメントルート外です。

### OS・カーネルのWeb更新

認証済みの設定画面の「OS・カーネル更新」を使用します。

1. 「更新を確認」を押し、少し待って「更新状況を再読込」を押します。APTの一覧取得と更新シミュレーションで件数を表示します。
2. USB/IPクライアントを切断し、再起動の確認にチェックして「更新して再起動」を押します。
3. OS保護中は書き込み可能な通常OSへ保守起動し、APT更新後に元の保護設定で再起動します（計2回）。完了後に同じ管理画面で結果を確認します。

実行内容は `apt-get update --error-on=any` と `apt-get -y --with-new-pkgs --no-remove upgrade` 相当です。カーネル更新に必要な追加パッケージは許可し、パッケージ削除・Debianのメジャー版移行・管理ソフト自体の更新は行いません。設定ファイルの競合では既存設定を保持します。保守起動中はUSB/IPサービスの開始を更新処理の後まで待たせます。

更新確認結果は `/run/wyse-apt-check.json`（RAM）。更新処理の状態と結果ログ末尾は `/var/lib/wyse-settings/os-update.json` に保存し、再起動後も確認できます。更新実行時だけ保存し、ログは最大2200文字に制限します。USB接続履歴はRAMのみです。

APT失敗時は失敗として表示し、元のOS保護設定へ戻します。電源断でパッケージ処理が中断された場合は、自動で再実行しません。`dpkg --audit` で未完了状態が見つかった場合は更新を拒否するため、OS保護を無効にしてSSHで状態を調べ、必要な復旧を行ってから再試行してください。パッケージ更新自体を旧版へ自動で戻す機能ではありません。
