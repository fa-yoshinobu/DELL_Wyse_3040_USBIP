# Third-party notices

## Digital Agency design tokens

Web画面の配色・間隔等は、デジタル庁の `@digital-go-jp/design-tokens` 2.1.0 を参考にしています。参考・利用部分の通知を保持するため、元のMITライセンスを以下に掲載します。独自に調整したCSSであり、デジタル庁による認定・推奨を示すものではありません。

- Source: https://github.com/digital-go-jp/design-tokens
- License: https://github.com/digital-go-jp/design-tokens/blob/main/LICENSE

MIT License

Copyright (c) 2023 デジタル庁

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Separately installed software

Debian、Linux、USB/IP、Avahi、NetworkManager、lighttpd、Python、overlayroot等は、この管理ソフトのMITライセンスへの変更対象ではありません。パッケージマネージャーで別途導入し、それぞれのライセンスに従います。OSイメージや依存ソフトを同梱して配布する場合は、各構成要素の配布条件を別途確認してください。

Avahiの標準 `avahi-daemon.conf` は同梱していません。Debianパッケージが配置した設定ファイルに、SETUP.mdで指定した設定だけを反映します。
