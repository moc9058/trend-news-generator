# trend-news-generator

技術・経済・国際政治などのトレンドを毎日自動収集し、X・Threads・Notion に自動投稿するシステム。

- **日次**: SNS向け短文を自動生成・自動投稿(X=日本語 / Threads=韓国語 / Notion=英語)
- **週次**: Economist・FT級の分析記事を下書き生成 → 管理画面で承認して投稿
- **月次**: 研究レポート級の深掘り記事を下書き生成 → 承認して投稿

## 構成

| ディレクトリ | 内容 |
|---|---|
| `pipeline/` | Python 3.12。収集・生成・投稿パイプライン(Cloud Run Jobs)と承認API(FastAPI, Cloud Run service) |
| `admin/` | Next.js 15 管理画面(Cloud Run + IAP)。カテゴリ・ソース・プロンプト・チャネル設定、下書き承認。UI言語 ko/ja/en |
| `infra/` | gcloud ベースのセットアップ・デプロイスクリプト |
| `shared/` | Python/TypeScript 共有定数(cadence, channel, status) |
| `docs/` | 認証情報の発行手順(`setup-credentials.md`)、運用手順(`runbook.md`) |

## アーキテクチャ概要

```
Cloud Scheduler (JST)
  06:00 ─→ job-collect            Gemini grounding + RSS/arXiv/IEEE Xplore → Firestore items (URLハッシュで重複排除)
  08:00 ─→ job-generate-daily     gpt-5.4-mini → 短文生成 → X/Threads/Notion へ自動投稿
  月曜   ─→ job-generate-weekly    2段階生成(gpt-5.4-mini 選定 → gpt-5.5 長文) → 下書き
  月初   ─→ job-generate-monthly   同上(月次スケール、週次記事も入力)
  月曜   ─→ job-refresh-threads-token  Threads long-lived token を更新

admin-ui (IAP) ──ID token──→ pipeline-api ──→ publish層(X / Threads / Notion)
      └─────── firebase-admin で Firestore 直接読み書き
```

## セットアップ

1. `docs/setup-credentials.md` に従い X / Threads / Notion / OpenAI / Gemini の認証情報を発行
2. `infra/00-bootstrap.sh` — GCP API有効化、Firestore、GCS、Artifact Registry、サービスアカウント
3. `infra/01-secrets.sh` — Secret Manager にシークレット登録(対話式)
4. `infra/10-deploy-pipeline.sh` — pipeline イメージのビルドと service + 5 jobs のデプロイ
5. seed 実行: `gcloud run jobs execute job-seed --region asia-northeast1 --wait`
6. `infra/11-deploy-admin.sh` — 管理UIを `--iap` 付きでデプロイ
7. `infra/20-schedulers.sh` — Cloud Scheduler 5本を作成

## ローカル開発

```bash
# pipeline
cd pipeline
pip install -e ".[dev]"
pytest
python -m app.jobs.collect          # ADC + .env で単発実行

# admin
cd admin
npm install
npm run dev
```
