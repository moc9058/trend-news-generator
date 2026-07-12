# CLAUDE.md

技術・経済・国際政治のトレンドを毎日収集し、X・Threads・Notion に自動投稿する GCP ネイティブなシステム。
プロジェクト `trend-news-generator` / リージョン `asia-northeast1` / タイムゾーン `Asia/Tokyo`。

## コマンド

```bash
# pipeline (Python 3.12)
cd pipeline
pip install -e ".[dev]"
pytest                              # pytest + pytest-asyncio(asyncio_mode=auto) + respx
python -m app.jobs.collect          # 単発実行(ADC + .env が必要。cp .env.example .env)

# admin (Next.js 15 / React 19 / TypeScript)
cd admin
npm install
npm run dev
npm run typecheck                   # tsc --noEmit(テストスクリプトは無い)
npm run build                       # prebuild で shared/constants.json を src/lib/ に同期

# デプロイ(gcloud スクリプト。Terraform は不使用)
infra/00-bootstrap.sh → 01-secrets.sh → 10-deploy-pipeline.sh → (job-seed 実行) → 11-deploy-admin.sh → 20-schedulers.sh
```

## アーキテクチャ

- `pipeline/app/` — 単一 Docker イメージで FastAPI サービス(`main.py` = pipeline-api)と 6 つの Cloud Run Jobs(`jobs/*.py`、`python -m app.jobs.<name>` で起動)を兼ねる
  - `collectors/` gemini_grounded(グラウンディング検索)・rss(arXiv Atom も rss ソースとして処理)・ieee_xplore・enrich(og:image 取得)
  - `generators/` daily(gpt-5.4-mini)・longform(2段階: mini で選定 → gpt-5.5 で長文)
  - `publishers/` **公開順は notion → x → threads 固定**(長文ティーザーが Notion 公開URLを必要とするため)。externalId / Threads containerId で冪等
  - `repo/` Firestore アクセス層。コレクション: `items` `posts` `runs` `categories` `sources` `channelConfigs` `promptTemplates` `settings/{app,channelHealth,notion}`
  - `config.py` pydantic-settings。モデル名・シークレットは全てここ経由
- `admin/src/` — Firestore は firebase-admin で直接読み書き(`lib/data.ts` 読み取り、`lib/actions.ts` server actions)。公開・リトライ・ジョブ実行だけ ID トークン付きで pipeline-api を呼ぶ(`lib/pipelineClient.ts`)。認証は IAP(`lib/iap.ts` が `x-goog-authenticated-user-email` を読む)。UI 言語 ko/ja/en(next-intl、デフォルト ko)
- `shared/constants.json` — Python/TS 共通の enum の唯一のソース。admin は prebuild でコピーするので、変更後は再ビルドが必要
- `infra/env.sh` — 全スクリプトが source する共通設定(SA 3つ: pipeline-sa / admin-sa / scheduler-sa)

## 運用上の決定事項(確定済み・再確認不要)

- 承認フロー: 日次は自動投稿、週次/月次は下書き → 管理画面で承認
- チャネル言語: X=日本語 / Threads=韓国語 / Notion=英語(`channelConfigs` で category×cadence×channel 単位に変更可)
- スケジュール(JST): 06:00 collect / 08:00 daily / 月曜07:00 weekly / 毎月1日07:00 monthly / 月曜03:00 Threads トークン更新

## 落とし穴

- **投稿系ジョブは `--max-retries=0`**(クラッシュ時の二重投稿防止)。collect/seed のみ retries=1。この方針を崩さないこと
- `items` のドキュメントID = 正規化URLのハッシュ(トランザクションで完全重複排除)。タイトル近似重複は7日窓で除外
- 本番ジョブには `GEMINI_MODEL` 等の env 上書きが入っている場合がある — config.py のデフォルトと乖離し得るので、モデル名変更時は両方確認
- pipeline-api はアプリレベル認証なし(意図的)。`--no-allow-unauthenticated` + Cloud Run IAM(admin-sa の run.invoker)で保護
- 本プロジェクトは組織なし GCP のため、IAP はカスタム OAuth クライアントを `gcloud iap settings set` で適用済み。IAP が使えない場合の NextAuth 代替は docs/runbook.md 参照
- Gemini/OpenAI キーは Secret Manager 管理。AI Studio で発行したキーは別の無課金プロジェクトに紐づきグラウンディングに使えない — gcloud でプロジェクト内発行すること
- GCS 署名URL は pipeline-sa の self token-creator で発行(秘密鍵なし)。この IAM を外すと画像添付が壊れる
- テストの HTTP モックは respx。X の OAuth 1.0a は自前実装(`publishers/x.py`)なので署名ロジック変更時は `test_oauth1.py` を必ず通す

## ドキュメント

- `docs/setup-credentials.md` — X/Threads/Notion/OpenAI/Gemini の認証情報発行手順
- `docs/runbook.md` — 障害対応(投稿失敗・トークン失効・収集0件・quota 超過)とコスト監視
- `docs/tech-report/` — 技術詳細文書(要件定義・構成図・データモデル・パラメーター・詳細設計)。人間向けの一次資料
- **コード・設定・インフラを変更したら `docs/tech-report/README.md` の対応表で該当文書を特定し、必ず同時に更新すること**(要件変更→01、リソース変更→02/04、スキーマ変更→03、実装変更→05 配下)
