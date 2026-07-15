# CLAUDE.md

技術・経済・国際政治のトレンドを毎日収集し、X・Threads・Notion に自動投稿する GCP ネイティブなシステム。
プロジェクト `trend-news-generator` / リージョン `asia-northeast1` / タイムゾーン `Asia/Tokyo`。

## コマンド

```bash
# pipeline (Python 3.12) — ローカルは uv で仮想環境に隔離(素の pip/python は使わない)
cd pipeline
uv venv && uv pip install -e ".[dev]"   # .venv を作成(deploy.sh の pick_python が自動検出)
uv run pytest                           # pytest + pytest-asyncio(asyncio_mode=auto) + respx
uv run python -m app.jobs.collect       # 単発実行(ADC + .env が必要。cp .env.example .env)

# admin (Next.js 15 / React 19 / TypeScript)
cd admin
npm install
npm run dev
npm run typecheck                   # tsc --noEmit(テストスクリプトは無い)
npm run build                       # prebuild で shared/constants.json を src/lib/ に同期

# デプロイ(gcloud スクリプト。Terraform は不使用)
./deploy.sh                         # 全アップデートはこれ1本で完結(下記チェーンの一括ラッパー。--help 参照)
infra/00-bootstrap.sh → 01-secrets.sh(対話式・既定スキップ) → 10-deploy-pipeline.sh → (job-seed 実行) → 11-deploy-admin.sh → 20-schedulers.sh
```

**デプロイ方針: あらゆる更新のデプロイは `./deploy.sh` で完結させる。** 通常のコード/設定/スキーマ更新は素の `./deploy.sh`(高速化には `--skip-bootstrap` 可)。一回性のデータ移行が要る更新は手順書ではなく deploy.sh のフラグとして実装する(例: cadence→format の `--migrate`)。新しい更新でデプロイ手順が増える場合は必ず deploy.sh に組み込むこと。末尾に warn-only の model config check があり、モデル env 上書き残存と `promptTemplates.modelOverride` の旧モデル固定を検出する。

## アーキテクチャ

- `pipeline/app/` — 単一 Docker イメージで FastAPI サービス(`main.py` = pipeline-api)と 7 つの Cloud Run Jobs(`jobs/*.py`、`python -m app.jobs.<name>` で起動。うち `generate_report` = Research Agent、キュー消費+lease)を兼ねる
  - `collectors/` gemini_grounded(グラウンディング検索)・rss(arXiv Atom も rss ソースとして処理)・ieee_xplore・enrich(og:image 取得)
  - `generators/` short(gpt-5.6-luna、旧 daily)・longform(article の2段階: luna で選定 → gpt-5.6-terra で長文)
  - `research/` **Research Agent(report フォーマット)= 決定的 Harness + 役割別 LLM の6フェーズ**。`harness.py`(フェーズ遷移・lease・resume・予算・cancel)/ `phases/`(plan→gather→extract→verify→write→review。ループバック verify→gather / review→write。旧 R0–R9/R7L は `schemas.py` の `LEGACY_PHASE_MAP` で読み替え)/ `sources/`(kokkai・academic・gov_docs・books・ieee・news・web_grounded・deep_research)/ `fetch/`(SSRF/robots/サイズガード・trafilatura/pypdf 抽出・GCS スナップショット・citecheck)/ `schemas.py` `state.py` `budget.py` `rubric.py` `llm.py`(pydantic 検証+予算計上+監査の唯一の LLM 経路)`prompts.py` `select.py`。モデルは planner/critic=gpt-5.6-sol、verifier/writer/localizer=gpt-5.6-terra、軽量系=gpt-5.6-luna。設計=`docs/tech-report/05-detailed-design/10-research-agent.md`
  - `publishers/` **公開順は notion → x → threads 固定**(長文ティーザーが Notion 公開URLを必要とするため)。externalId / Threads containerId で冪等
  - `repo/` Firestore アクセス層。コレクション: `items` `posts` `runs` `categories` `sources` `channelConfigs` `promptTemplates` `researchRuns`(+サブコレクション evidence/claims/events)`settings/{app,channelHealth,notion}`。`research.py` は本リポジトリ唯一のトランザクション lease(`claim_next`)
  - `config.py` pydantic-settings。モデル名・シークレットは全てここ経由
  - `utils/observability.py` — **LangSmith(SaaS)トレーシング**。`langsmith-api-key` シークレットの有無が唯一のスイッチ(存在すれば `10-deploy-pipeline.sh` が `LANGSMITH_TRACING=true` ごと注入。消して再デプロイ = キルスイッチ)。`openai_client._client()` を `wrap_openai` で包むだけで、**予算計上は従来どおり自前**(`PRICES`/`cost_usd`)。トレース失敗は全て swallow — run を落とさない。プロンプト・生成文のフル送信は承認済み(runbook)
- `admin/src/` — Firestore は firebase-admin で直接読み書き(`lib/data.ts` 読み取り、`lib/actions.ts` server actions)。公開・リトライ・ジョブ実行だけ ID トークン付きで pipeline-api を呼ぶ(`lib/pipelineClient.ts`)。認証は IAP(`lib/iap.ts` が `x-goog-authenticated-user-email` を読む)。UI 言語 ko/ja/en(next-intl、デフォルト ko)
- `shared/constants.json` — Python/TS 共通の enum の唯一のソース。admin は prebuild でコピーするので、変更後は再ビルドが必要
- `infra/env.sh` — 全スクリプトが source する共通設定(SA 3つ: pipeline-sa / admin-sa / scheduler-sa)

## 運用上の決定事項(確定済み・再確認不要)

- 区分(旧 cadence)は **成果物フォーマット = short / article / report**(daily→short / weekly→article / monthly→report にリネーム済み)
- 承認フロー: 短文(short)は自動投稿、記事(article)/レポート(report)は下書き → 管理画面で承認。レポートは調査計画の承認ゲート(`planApproval`)も任意で有効化可
- チャネル言語: X=日本語 / Threads=韓国語 / Notion=英語(`channelConfigs` で category×format×channel 単位に変更可)。レポートは canonical=ja → ja/ko/en を並行生成
- レポート予算: 標準 ~$10/本 をハード上限(`budget.usdCap`)。Deep Research 補助は1本1回まで・予算残<$3 で自動スキップ
- スケジュール(JST): 06:00 collect / 08:00 short / 月曜07:00 article / 毎月1日07:00 report(pipeline-api 直呼び・自動テーマ選定)/ 月曜03:00 Threads トークン更新

## 落とし穴

- **ジョブ内で投稿する系のジョブ(`generate-short`)は `--max-retries=0`**(クラッシュ時の二重投稿防止)。collect/seed(および後続の `generate-report` は lease/resume で二重実行を防ぐため)は retries=1。この方針を崩さないこと
- **区分リネーム移行**: cadence→format のデータ移行は `pipeline/scripts/migrate_cadence_to_format.py`(既定 dry-run、`--apply`/`--rollback`/`--notion`)。`Post` に旧値受理シム(`models.py` の `model_validator`)があるのでデプロイ→移行の順序事故は非致命。手順は `docs/runbook.md` の移行 runbook 参照
- `items` のドキュメントID = 正規化URLのハッシュ(トランザクションで完全重複排除)。タイトル近似重複は7日窓で除外
- `10-deploy-pipeline.sh` は `--set-env-vars` で env を**毎デプロイ全置換**する — `gcloud run jobs update` で手動追加した env 上書きは `./deploy.sh` で消える。モデル名等の恒久設定は config.py(シークレットは Secret Manager)だけに置くこと。残り得る旧モデル固定(`promptTemplates.modelOverride`)は deploy.sh 末尾のチェックが警告する
- pipeline-api はアプリレベル認証なし(意図的)。`--no-allow-unauthenticated` + Cloud Run IAM(admin-sa の run.invoker)で保護
- 本プロジェクトは組織なし GCP のため、IAP はカスタム OAuth クライアントを `gcloud iap settings set` で適用済み。IAP が使えない場合の NextAuth 代替は docs/runbook.md 参照
- Gemini/OpenAI キーは Secret Manager 管理。AI Studio で発行したキーは別の無課金プロジェクトに紐づきグラウンディングに使えない — gcloud でプロジェクト内発行すること
- GCS 署名URL は pipeline-sa の self token-creator で発行(秘密鍵なし)。この IAM を外すと画像添付が壊れる
- テストの HTTP モックは respx。X の OAuth 1.0a は自前実装(`publishers/x.py`)なので署名ロジック変更時は `test_oauth1.py` を必ず通す
- **LangSmith SDK は `Settings` ではなく `os.environ` を直読する** — `.env` は pydantic-settings が `Settings` に読むだけで `os.environ` に入らないため、ローカルで `.env` にだけ書くと「クライアントは wrap 済みなのにトレースが1件も出ない」無言の食い違いになる(本番は実 env なので発生せず、気付けない)。`observability._export_env()` が解決済み値を `os.environ` へ書き戻して吸収している(SDK の env は lru_cache されるのでクリアも必要)。なお SDK はレガシーな `LANGCHAIN_*` を `LANGSMITH_*` より優先する
- **テストから `LANGSMITH_*` を消すには `delenv` では不十分** — `Settings` は env だけでなく `pipeline/.env` も読むため、手元でトレーシングを有効にしていると suite が実キーで LangSmith に送信してしまう(respx の厳格性も壊れる)。`tests/conftest.py` の autouse fixture は env を**空/false に setenv**して dotenv 層ごと打ち消している(env > .env の優先順位を利用)

## ドキュメント

- `docs/setup-credentials.md` — X/Threads/Notion/OpenAI/Gemini の認証情報発行手順
- `docs/runbook.md` — 障害対応(投稿失敗・トークン失効・収集0件・quota 超過)とコスト監視
- `docs/tech-report/` — 技術詳細文書(要件定義・構成図・データモデル・パラメーター・詳細設計)。人間向けの一次資料
- **コード・設定・インフラを変更したら `docs/tech-report/README.md` の対応表で該当文書を特定し、必ず同時に更新すること**(要件変更→01、リソース変更→02/04、スキーマ変更→03、実装変更→05 配下)
