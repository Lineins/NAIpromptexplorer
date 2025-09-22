# NAI Prompt Explorer

NAI Prompt Explorer は、PNG ファイルに埋め込まれたプロンプト情報を検索しながら画像を閲覧するためのデスクトップアプリケーションです。Windows 11 (64bit) を想定していますが、Python と Tkinter が利用可能であれば他の OS でも動作します。

## 主な機能

- プロンプトの検索
  - カンマを含む文字列をそのまま検索できる完全一致モード
  - 入力した複数タグを順不同で含む画像を探す AND モード
- 検索結果をサムネイル一覧で表示（列数・サムネイルサイズを可変）
  - Ctrl + マウスホイールでもサムネイルサイズを調整
- サムネイルをクリックするとプロンプト全文を表示
  - 表示欄はスクロール可能で、表示領域は分割バーで調整可能
  - プロンプトを同名のテキストファイルとして保存可能
- 対象フォルダのプリセット管理と、デフォルトフォルダの保存

## 必要条件

- Python 3.10 以上
- [Pillow](https://python-pillow.org/) ライブラリ

## セットアップ

```bash
python -m venv .venv
source .venv/bin/activate  # Windows の場合は .venv\Scripts\activate
pip install -r requirements.txt
```

## 使い方

```bash
python -m naipromptexplorer.app
```

初回起動時は `C:\Users\kuron\Downloads\NAIv4.5画風` フォルダを読み込みます。設定から別フォルダを指定すると、そのパスをデフォルトとして保存できます。プリセットを追加しておけば、ドロップダウンから素早く切り替えられます。

検索欄にタグを入力し「検索」を押すか Enter を押すと絞り込みが実行されます。リセットボタンで検索条件をクリアできます。

## 設定ファイル

`%USERPROFILE%\.naipromptexplorer\settings.json`（Windows）の JSON ファイルにデフォルトフォルダとプリセットを保存します。アプリケーション終了後も設定が保持されます。

## 注意事項

- インデックス作成時に PNG ファイルのメタデータを読み込みます。ファイル数が多い場合は処理完了まで時間がかかることがあります。
- プロンプト情報が埋め込まれていないファイルは空欄として表示されます。
