# tech-report — コード詳細説明書(索引)

> 対象コード時点: コミット f703290 + 未コミット変更 / 最終更新: 2026-07-12

## 1. この文書群について

trend-news-generator の**仕組みをコード単位で説明する**技術文書一式です。

- **読者**: 本システムのオーナー本人(ソフトウェア開発の専門教育を受けていない前提)
- **到達目標**: AI ツールの助けなしで、一人で各機能のコードを読んで理解できること
- **粒度**: 全関数の役割・入出力・呼び出し関係を日本語で説明し、特に難しい箇所(OAuth 署名・冪等性・トランザクション等)のみコードを抜粋して行単位で解説
- **鮮度の見方**: 各文書の冒頭に「対象コード時点(コミットハッシュ)」があります。`git log -1 --format=%h` と比べて古ければ、その文書は更新が必要かもしれません

### 責務分担(この文書群に「書いていないこと」)

| 知りたいこと | 見る場所 |
|---|---|
| 障害の直し方(投稿失敗・トークン失効・収集0件・quota) | [`../runbook.md`](../runbook.md) |
| X/Threads/Notion/OpenAI/Gemini の認証情報の発行手順 | [`../setup-credentials.md`](../setup-credentials.md) |
| 5分で分かる全体概要とセットアップ手順 | ルートの [`README.md`](../../README.md) |
| AI エージェント向けの要点・落とし穴 | ルートの [`CLAUDE.md`](../../CLAUDE.md) |
| **仕組みの詳細(なぜ・どうやって動くか)** | **この tech-report** |

## 2. 文書一覧と読む順序

### 文書一覧

| 文書 | 内容 | こういう時に読む |
|---|---|---|
| [01-requirements.md](01-requirements.md) | 要件定義書(機能要件 FR / 非機能要件 NFR、FR⇔実装対応表) | 「何ができるシステムか」を確認したい |
| [02-architecture.md](02-architecture.md) | 構成図(GCP リソース図、フロー別シーケンス図4枚、認証の2段構え) | クラウド上で何がどう動くかを知りたい |
| [03-data-model.md](03-data-model.md) | Firestore 全10コレクションのスキーマ・ID 規約・状態遷移 | データの形と流れを知りたい(全文書の参照先) |
| [04-parameters.md](04-parameters.md) | パラメーターシート(config 全項目・Secret・Cloud Run・cron・IAM・ハードコード定数) | 設定値の一覧と変更方法を知りたい |
| [05-detailed-design/00-code-reading-primer.md](05-detailed-design/00-code-reading-primer.md) | コードの読み方入門+用語集(Python/TS/GCP の前提知識) | **コードを読む前に一度通読** |
| [05-detailed-design/01-pipeline-foundation.md](05-detailed-design/01-pipeline-foundation.md) | 共通基盤(config / models / normalize / repo / utils) | どの機能を読むにも必要な部品の理解 |
| [05-detailed-design/02-collect.md](05-detailed-design/02-collect.md) | ①収集(RSS / Gemini grounding / IEEE / 画像取得 / 重複排除) | 毎朝6時のジョブの中身 |
| [05-detailed-design/03-generate.md](05-detailed-design/03-generate.md) | ②生成(日次短文 / 週次・月次の2段階長文) | LLM で文章を作る仕組み |
| [05-detailed-design/04-publish.md](05-detailed-design/04-publish.md) | ③投稿(notion→x→threads 固定順、OAuth 署名、冪等性) | 実際に SNS へ投稿する仕組み |
| [05-detailed-design/05-pipeline-api.md](05-detailed-design/05-pipeline-api.md) | ③承認 API(FastAPI、認証の考え方、手動ジョブ実行) | 管理画面のボタンの先で起きること |
| [05-detailed-design/06-ops-jobs.md](05-detailed-design/06-ops-jobs.md) | ④運用ジョブ(Threads トークン週次更新、seed 初期投入) | トークン更新と初期データの仕組み |
| [05-detailed-design/07-admin-ui.md](05-detailed-design/07-admin-ui.md) | 管理画面(10画面、Server Actions、IAP 認証、i18n) | 管理画面のコードを読みたい |
| [05-detailed-design/08-infra.md](05-detailed-design/08-infra.md) | インフラ(gcloud スクリプト6本の逐段解説、Dockerfile) | デプロイ・GCP リソース作成の中身 |
| [05-detailed-design/09-tests.md](05-detailed-design/09-tests.md) | テスト(8ファイルの解説)+**文書検証の恒久手順** | テストの動かし方/文書更新後の確認 |

### 読む順序

- **初めて通読するとき**: [01-requirements](01-requirements.md) → [02-architecture](02-architecture.md) → [03-data-model](03-data-model.md) → [primer](05-detailed-design/00-code-reading-primer.md) → 興味のある機能の詳細設計書
- **コードを読み解くとき**: [primer](05-detailed-design/00-code-reading-primer.md) → [01-pipeline-foundation](05-detailed-design/01-pipeline-foundation.md) → 対象機能の文書を横に置いてコードを開く(各文書の「関数リファレンス」が読み進める順の地図になります)
- **設定を変えたいとき**: [04-parameters](04-parameters.md) の「変更するときは」→ 該当する詳細設計書の「変更するときは」

## 3. 用語統一表

この文書群では表記を以下に統一しています。

| 用語 | 意味 | 使わない表記 |
|---|---|---|
| ジョブ | Cloud Run Jobs の実行単位(job-collect 等7種) | バッチ、タスク |
| チャネル | 投稿先 `x` / `threads` / `notion` | チャンネル |
| 投稿(post) | Firestore `posts` の1ドキュメント(SNS 投稿のもとになる単位) | 記事(items と紛らわしいため) |
| 収集アイテム(item) | Firestore `items` の1ドキュメント(収集した外部記事) | ニュース、記事 |
| 下書き | `status: draft` の投稿 | ドラフト |
| カデンス(cadence) | 配信周期 `daily` / `weekly` / `monthly` | 頻度 |
| 管理画面(admin) | Next.js 製の admin-ui | ダッシュボード(トップページの1画面のみを指す) |

enum 値・ステータス値は常にコードスパンで原語表記します(例: `draft`、`partially_published`)。

## 4. コード ⇔ 文書 対応表(更新時はここで引く)

| 変更したコード | 更新する文書 |
|---|---|
| `pipeline/app/config.py` | [04-parameters](04-parameters.md) §2、[05/01-foundation](05-detailed-design/01-pipeline-foundation.md) |
| `pipeline/app/models.py`、`shared/constants.json` | [03-data-model](03-data-model.md)、[05/01-foundation](05-detailed-design/01-pipeline-foundation.md) |
| `pipeline/app/normalize.py`、`repo/**`、`utils/**` | [05/01-foundation](05-detailed-design/01-pipeline-foundation.md)(スキーマに影響すれば [03-data-model](03-data-model.md) も) |
| `pipeline/app/jobs/collect.py`、`collectors/**` | [05/02-collect](05-detailed-design/02-collect.md) |
| `pipeline/app/jobs/generate_*.py`、`longform_runner.py`、`generators/**` | [05/03-generate](05-detailed-design/03-generate.md) |
| `pipeline/app/publishers/**` | [05/04-publish](05-detailed-design/04-publish.md) |
| `pipeline/app/main.py` | [05/05-pipeline-api](05-detailed-design/05-pipeline-api.md)(公開ロジックなら [05/04-publish](05-detailed-design/04-publish.md)) |
| `pipeline/app/jobs/refresh_threads_token.py`、`seed.py` | [05/06-ops-jobs](05-detailed-design/06-ops-jobs.md) |
| `admin/**` | [05/07-admin-ui](05-detailed-design/07-admin-ui.md) |
| `infra/**`、`pipeline/Dockerfile`、`admin/Dockerfile` | [05/08-infra](05-detailed-design/08-infra.md)、[04-parameters](04-parameters.md)(値が変わる場合)、[02-architecture](02-architecture.md)(リソース構成が変わる場合) |
| `pipeline/tests/**`、`pipeline/pyproject.toml` | [05/09-tests](05-detailed-design/09-tests.md) |
| 機能の追加・削除(要件が変わる) | [01-requirements](01-requirements.md) の FR/NFR と対応表 |
| Firestore のコレクション・フィールド・インデックス | [03-data-model](03-data-model.md) |
| スケジュール(cron)・Secret・IAM・Cloud Run 設定 | [04-parameters](04-parameters.md)、[02-architecture](02-architecture.md) |

## 5. 更新ルール

1. コードを変更したら、**同じコミットで**上の対応表から該当文書を特定して更新する(ルートの `CLAUDE.md` にも同じ義務を記載)
2. 更新した文書は冒頭の `> 対象コード時点: ... / 最終更新: ...` を書き換える
3. 更新後は [05/09-tests 第2部「文書検証の恒久手順」](05-detailed-design/09-tests.md) のチェック(ファイルパス実在・関数名実在・パラメーター突合・pytest・リンク確認)を実行する
4. 文書間で同じ事実を二重に書かない: データ構造の正は [03-data-model](03-data-model.md)、設定値の正は [04-parameters](04-parameters.md)、処理の流れの正は各詳細設計書。他の文書からはリンクで参照する
