# 構成と他機種への移植

[README](README.md) / [導入手順](SETUP.md)

移植対象はLinuxの小型PC・SBCです。Pythonの管理処理はCPUアーキテクチャに強く依存しませんが、OSのパッケージ、カーネル、ネットワーク、起動・保存方式は移植先に合わせる必要があります。

## 処理の流れ

```text
USB挿入 → udev → usbip-auto@.service → usbip-auto-share
                                      ↓
                              usbip-host / usbipd ← USB/IPクライアント

ブラウザー → lighttpd → 状態表示CGI
                     → 認証済み設定CGI → UNIXソケット → root側の設定処理

本体キーボード → tty1コンソール → ネットワーク・OS保護・パスワード操作
```

| 部分 | 主なファイル | 役割 |
| --- | --- | --- |
| 自動共有 | `usbip-auto-share`、`90-usbip-auto.rules`、`usbip-auto@.service` | USBクラス・マウント状態を調べて共有。最大6回再試行 |
| 履歴 | `usbip-history.py` | sysfsの状態変化をRAMに記録 |
| Web表示 | `usbip-status.py`、`system-status.py` | 共有一覧・履歴・システム状態 |
| Web設定 | `network-settings.py`、`network-request.py` | 入力受付と特権処理への要求 |
| 特権処理 | `network-trial.py`、`wyse-network.socket`、`wyse-network@.service` | NetworkManagerの試用・確定・復旧、共有操作 |
| 認証 | `web-password.py`、`install-web-auth.sh` | ハッシュ保存、変更・再発行、永続領域への配置 |
| OS更新 | `os-update.py`、`wyse-os-update*.service` | APT更新と保守起動・OS保護復帰 |
| 本体メニュー | `console.py`、`wyse-console.service` | tty1上のcursesメニュー |
| 永続設定 | `install-settings-volume.sh`、`overlay-remount.sh` | 設定用ext4とbind mount、OS保護設定 |

Web処理にroot権限を与えず、UNIXソケット経由で限定した要求をroot側へ渡します。移植時にもこの分離を維持します。USB停止・復旧は共有処理とロックを共用し、使用中の機器を強制的に奪いません。

## RAMと永続領域

| 保存先 | 内容 | 再起動後 |
| --- | --- | --- |
| `/run/wyse-usb-history/` | USB接続履歴 | 消える |
| `/run/wyse-usb-paused/` | 共有の一時停止 | 消える |
| `/run/wyse-apt-check.json` | 更新候補の確認結果 | 消える |
| `/var/lib/wyse-settings/` | ネットワーク、認証、モード、ホスト名、保護設定、更新状態 | 残る |
| OSルートのOverlayFS上層 | OS保護中の一時書き込み | 消える |

永続領域は `LABEL=WYSECFG` の別ext4パーティションです。NetworkManagerのプロファイルとWeb認証ディレクトリをそこからbind mountします。`/dev/mmcblk0pN` の番号固定は避けます。共有ストレージを設定領域として使わないでください。

## 移植時に確認・変更する箇所

### 1. USB/IPとOS依存パッケージ

移植先カーネルで `usbip-host` を利用できること、対応する `usbip` / `usbipd` が導入できることを確認します。パッケージ名はディストリビューションに合わせます。Web管理はPython 3、python3-dbus、systemd、NetworkManager、lighttpdに依存します。

`debian.sources` はDebian 13用です。Raspberry Pi OSや別のDebian版のAPT設定を、このファイルで上書きしないでください。Wi-Fiファームウェアも対象チップ用を選びます。Wyse向けの `firmware-libertas` を共通要件にはしません。

### 2. インターフェース名とプロファイルUUID

現行コードは次の値を参照します。UUIDはプロファイルを識別する値で、認証情報ではありません。

| 対象 | 現行値 | 変更箇所 |
| --- | --- | --- |
| 有線IF | `enp1s0` | `network-trial.py`、`system-status.py`、NetworkManager、Avahi |
| 無線IF | `mlan0` | 同上 |
| 有線UUID | `9f2e56cf-5d10-4d5b-a03e-efed733fd464` | `network-trial.py`、作成するプロファイル |
| 無線UUID | `12130d96-e908-42ce-9561-1ae5bd132282` | `network-trial.py`、`console.py`、`system-status.py`、作成するプロファイル |

`ip -br link` と `nmcli connection show` で実際の値を確認します。`network-trial.py` は先頭の定数だけでなく状態取得処理にもIF名があるため、ファイル内全体を確認します。テストのモックも変更に合わせます。

無線なしの機種や有線のみの構成へ移植する場合は、AP作成手順に加え、コンソールのモード切替・状態表示・リセット処理が無線を前提にしないよう調整します。

### 3. Wi-Fi親機

無線チップ名だけで判断せず、使用するカーネル・ドライバー・ファームウェアでAPモードを利用できるか確認します。NetworkManagerの `ipv4.method shared` がアドレス配布を担う構成です。別のDHCPサーバーを同じネットワークに重ねて動かさないよう設計します。

現行実装はWi-Fi親機向けです。子機接続や親機・子機の同時運用には、プロファイル・Web画面・ロールバック範囲の追加設計が必要です。

### 4. 起動とOS保護

Wyseの導入手順はGRUBとinitramfs-tools、overlayroot、ext4ルートを前提とします。Raspberry Pi等では、ブート方式・カーネル更新方法・ルート保護機構を確認し、GRUB関連コマンドをそのまま実行しないでください。

特に以下は一体で見直します。

- `install-settings-volume.sh` のext4検査、設定ディスク、`overlayroot_cfgdisk`
- `console.py` の保護ON/OFF設定
- `overlay-remount.sh` と関連サービスの起動順
- `os-update.py` の `/media/root-ro`、保守起動、更新後の保護復帰
- 設定領域を待つsystemd依存関係、タイムアウト

移植先の保護機構と更新方式が整合するまでは、OS保護・WebからのOS更新を有効にしません。OS保護を省く場合も、現行の設定処理が永続領域を要求するため、関連コードの調整が必要です。

### 5. コンソール・Web・名前解決

`wyse-console.service` は `/dev/tty1` とLinuxコンソールを使い、gettyと排他にします。シリアルコンソール中心のSBCでは端末・TERM・ログインサービスとの関係を変更します。

lighttpdは `/var/www/html`、HTTPS証明書は `/etc/lighttpd/` を使用します。ホスト名・証明書のSAN・Avahiの公開インターフェースを合わせます。Avahi標準設定はコピーせず、SETUP.mdの指定項目を移植先の設定へ反映します。

## 移植後の確認項目

単体テストはLinux環境でリポジトリ直下から実行します。実機USB操作の代わりにモックを使います。

```sh
python3 -m unittest discover -s tests -v
```

単体テストだけではカーネル・USB機器・無線ドライバーの互換性は確認できません。実機では以下を確認します。

1. HID除外、USBの挿抜、共有・接続・切断、共有停止・再開。
2. ネットワーク変更の確定とタイムアウト復旧、有線とWi-Fiの両方の復帰。
3. 最後に確定したモード・ホスト名・認証の再起動後の保持。
4. 設定領域のマウントと、モニターなしでのサービス起動。
5. OS保護の切替と、OS更新後のカーネル・ネットワーク・USB/IPの起動。

この資料は移植の設計参考です。特定のRaspberry Piモデルやディストリビューションへの対応を保証するものではありません。
