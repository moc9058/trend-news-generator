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

## クラウド構成図 + フロー

GCP プロジェクト `trend-news-generator`(asia-northeast1)。矢印の番号 ①〜④ が処理フロー。

```mermaid
flowchart LR
  subgraph EXT_IN["外部ソース"]
    SRC["Gemini grounding<br/>RSS / arXiv / IEEE Xplore"]
  end

  subgraph GCP["GCP: trend-news-generator"]
    SCHED["Cloud Scheduler ×5<br/>(JST, scheduler-sa)"]

    subgraph RUN["Cloud Run Jobs(pipeline-sa, 同一イメージ)"]
      JC["job-collect"]
      JD["job-generate-daily"]
      JW["job-generate-weekly<br/>job-generate-monthly"]
      JT["job-refresh-threads-token"]
    end

    API["Cloud Run service<br/>pipeline-api(非公開)"]
    ADMIN["Cloud Run service<br/>admin-ui + IAP(admin-sa)"]

    FS[("Firestore<br/>items / posts / runs / 設定")]
    GCS[("GCS<br/>*-media(画像)")]
    SM[["Secret Manager<br/>APIキー ×7"]]
    AR["Artifact Registry<br/>(Cloud Build でイメージ格納)"]
  end

  subgraph EXT_OUT["投稿先 / LLM"]
    LLM["OpenAI<br/>gpt-5.4-mini / gpt-5.5"]
    SNS["Notion → X → Threads<br/>(この順で投稿)"]
  end

  OP(["運用者(承認)"])

  SCHED -- "①〜④ 起動" --> RUN
  SRC -- "① 収集" --> JC
  JC -- "① items(URLハッシュ重複排除)" --> FS
  JC -- "① og:image" --> GCS
  JD & JW <-- "② 生成" --> LLM
  JD -- "② 短文 → 自動投稿" --> SNS
  JW -- "② 長文下書き(draft)" --> FS
  OP -- "IAP 認証" --> ADMIN
  ADMIN <-- "Firestore 直接読み書き" --> FS
  ADMIN -- "③ 承認・公開(ID token)" --> API
  API -- "③ 投稿" --> SNS
  JT -- "④ トークン更新(毎週)" --> SM
  SM -.-> RUN
  AR -.-> RUN
```

### フロー概要(JST)

| # | 時刻 | 処理 |
|---|---|---|
| ① | 毎日 06:00 | `job-collect` — 外部ソース収集 → Firestore `items` + GCS 画像 |
| ② | 毎日 08:00 | `job-generate-daily` — 短文生成 → X(日)/Threads(韓)/Notion(英)へ自動投稿 |
| ② | 月曜 07:00 / 毎月1日 07:00 | weekly / monthly — 2段階生成(gpt-5.4-mini 選定 → gpt-5.5 長文)→ 下書き |
| ③ | 随時 | admin-ui で下書き承認 → pipeline-api 経由で Notion → X → Threads に投稿 |
| ④ | 月曜 03:00 | `job-refresh-threads-token` — Threads long-lived token を Secret Manager に更新 |

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
