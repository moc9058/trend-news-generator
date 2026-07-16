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
  - `research/` **Research Agent(report フォーマット)= LangGraph の決定的グラフ + 役割別 LLM の6フェーズ**。`graph/`(2026-07-15 に自前 harness.py を置換・削除。`builder.py` トポロジー / `state.py` チャネル+reducer+RESET+タスク型 / `context.py` 非直列化の生き物 / `checkpointer.py` 自前 FirestoreCheckpointSaver / `runner.py` lease 済み run の実行制御 / `nodes/` — **M2 で gather/extract/verify/write の実装本体を吸収し、各フェーズは dispatch→並列 worker(`max_concurrency`=4)→バリアの3段**。ループバック verify→gather / review→write は不変。旧 R0–R9/R7L は `schemas.py` の `LEGACY_PHASE_MAP` で読み替え)/ `phases/`(残るのは plan.py と review.py のみ)/ `sources/`(kokkai・academic・gov_docs・books・ieee・news・web_grounded・deep_research)/ `fetch/`(SSRF/robots/サイズガード・trafilatura/pypdf 抽出・GCS スナップショット・citecheck)/ `schemas.py` `state.py` `budget.py` `rubric.py` `llm.py`(pydantic 検証+予算計上+監査の唯一の LLM 経路)`prompts.py` `select.py`。モデルは planner/critic=gpt-5.6-sol、verifier/writer/localizer=gpt-5.6-terra、軽量系=gpt-5.6-luna。設計=`docs/tech-report/05-detailed-design/10-research-agent.md`
  - `publishers/` **公開順は notion → x → threads 固定**(長文ティーザーが Notion 公開URLを必要とするため)。externalId / Threads containerId で冪等
  - `chat/` **リサーチチャット(管理画面の個人用)= LangGraph StateGraph、1メッセージ=1実行**。`graph.py`(壁打ち chat / 調査 research の2モード。research は plan→search→select→read→(gap ループ≤1、deep のみ)→synthesize)/ `api.py`(SSE)/ `stream_llm.py` / `prompts.py`(英語)。research のコネクタ・Fetcher・rubric・Budget・`llm.structured` を再利用するが**状態の正は Firestore `chatThreads`**(チェックポインタ不使用)。設計=`docs/tech-report/05-detailed-design/11-research-chat.md`
  - `repo/` Firestore アクセス層。コレクション: `items` `posts` `runs` `categories` `sources` `channelConfigs` `promptTemplates` `researchRuns`(+サブコレクション evidence/claims/events)`chatThreads`(+サブコレクション messages)`chatUsage` `settings/{app,channelHealth,notion}`。`research.py` は本リポジトリ唯一のトランザクション lease(`claim_next`)
  - `config.py` pydantic-settings。モデル名・シークレットは全てここ経由
  - `utils/observability.py` — **LangSmith(SaaS)トレーシング**。`langsmith-api-key` シークレットの有無が唯一のスイッチ(存在すれば `10-deploy-pipeline.sh` が `LANGSMITH_TRACING=true` ごと注入、`11-deploy-admin.sh` が admin にも注入。消して再デプロイ = 両方まとめてキルスイッチ)。`openai_client._client()` を `wrap_openai` で包むだけで、**予算計上は従来どおり自前**(`PRICES`/`cost_usd`)。トレース失敗は全て swallow — run を落とさない。プロンプト・生成文のフル送信は承認済み(runbook)。**`init_tracing()` を各エントリポイントの先頭で呼ぶこと**(下記の落とし穴)
- `admin/src/` — Firestore は firebase-admin で直接読み書き(`lib/data.ts` 読み取り、`lib/actions.ts` server actions)。公開・リトライ・ジョブ実行だけ ID トークン付きで pipeline-api を呼ぶ(`lib/pipelineClient.ts`)。**例外は `lib/langsmith.ts`**(LangSmith REST を直読 = トレース表示用。副作用の無い読み取りなので pipeline-api を挟まない)。認証は IAP(`lib/iap.ts` が `x-goog-authenticated-user-email` を読む)。UI 言語 ko/ja/en(next-intl、デフォルト ko)
- `shared/constants.json` — Python/TS 共通の enum の唯一のソース。admin は prebuild でコピーするので、変更後は再ビルドが必要
- `infra/env.sh` — 全スクリプトが source する共通設定(SA 3つ: pipeline-sa / admin-sa / scheduler-sa)

## 運用上の決定事項(確定済み・再確認不要)

- 区分(旧 cadence)は **成果物フォーマット = short / article / report**(daily→short / weekly→article / monthly→report にリネーム済み)
- 承認フロー: 短文(short)は自動投稿、記事(article)/レポート(report)は下書き → 管理画面で承認。レポートは調査計画の承認ゲート(`planApproval`)も任意で有効化可
- チャネル言語: X=日本語 / Threads=韓国語 / Notion=英語(`channelConfigs` で category×format×channel 単位に変更可)。レポートは canonical=ja → ja/ko/en を並行生成
- レポート予算: 標準 ~$10/本 をハード上限(`budget.usdCap`)。Deep Research 補助は1本1回まで・予算残<$3 で自動スキップ
- チャット: **チャット発の短文は `shortRequireApproval` に関係なく常に下書き**(handoff は投稿しない — 公開は既存の承認フローのみ)。予算は quick $0.7 / deep $3 をハード上限、月次実績は `chatUsage/{YYYY-MM}` に集計されダッシュボードのコストカードに載る
- スケジュール(JST): 06:00 collect / 08:00 short / 月曜07:00 article / 毎月1日07:00 report(pipeline-api 直呼び・自動テーマ選定)/ 月曜03:00 Threads トークン更新

## 落とし穴

- **LangGraph 移行後の research の不変条件**(壊すと静かに壊れる): ①**分岐に LLM を関与させない** — 経路は純関数 `state.gap_decision`/`critic_decision` が決め、ノードは `Command(goto=)` で運ぶだけ ②**`loops++` は coverage ノード、`revisions++` は review ノードだけ** ③**予算ガードは `phase_start` より前**(スキップされたフェーズはイベントを出さず admin 上 pending のまま)④**フェーズ通過ごとに `phase_start`/`phase_end` は厳密に1組** — dispatch が start・バリアが end を出し、**worker はフェーズイベントを出さない**(admin のフロー図が数える。revise 辺 = write_canonical の phase_start 数−1)⑤ `plan_gate`/`budget_stop`/dispatch/worker は `runner.NODE_PHASE` に載せない(run doc への投影はバリアのみ)⑥ **worker は LastValue チャネル(`run`/`selected`/`draft` 等)に書かない** — 同一 superstep の複数書き込みは InvalidUpdateError。worker が書けるのは reducer 付きチャネル(`hit_index`/`hit_rqs`/`localized`/`budget`/`claims_buf`/`evidence_ids`)だけ ⑦ dispatch は accumulator(`claims_buf`/`evidence_ids`)を **RESET** してから Send する(忘れるとループ2周目で claims が全部重複)
- **M2 の並列 fan-out で共有される可変物には全てロックがある**(`budget.py` の Lock+`try_note_fetch` / `fetcher.py` のホスト別 Lock(1 rps/host 維持)/ grounded コネクタの genai Lock)。外すと `test_parallel_safety.py` が落ちる(GIL 切替を `setswitchinterval(1e-6)` で強制して競合を顕在化させている — 既定間隔ではロック無しでも通ってしまうのを確認済み)。Send の task payload は worker の**全入力**(state はマージされない)かつチェックポイントされる — 大きな物(ReportDraft 等)は入れず、skeleton 文字列のように削って渡す
- **チェックポイントは blob 一括保存なので `DeltaChannel` を使ってはいけない**(`builder.py` の assert が検知)。`state.py` の reducer は普通の二項関数にすること(`BinaryOperatorAggregate` にコンパイルされる)。**serde の allowlist(`checkpointer._allowed_types`)から漏れた pydantic 型は例外ではなく `dict` として黙って復元される** — resume したグラフが `ReportDraft` の代わりに dict を掴む。`test_checkpointer_firestore.py` が漏れを検知する
- **`langgraph` / `langgraph-checkpoint` / `langsmith` だけ上限 pin**(`<2` / `<5` / `<1`)。内部 ABI に乗っているため。バンプ時は `docs/tech-report/05-detailed-design/10-research-agent.md` §8.2「移行で受け入れたリスク」の step-0 プローブ(import + トイグラフ挙動確認)を再実行すること
- **ジョブ内で投稿する系のジョブ(`generate-short`)は `--max-retries=0`**(クラッシュ時の二重投稿防止)。collect/seed(および後続の `generate-report` は lease/resume で二重実行を防ぐため)は retries=1。この方針を崩さないこと
- **区分リネーム移行**: cadence→format のデータ移行は `pipeline/scripts/migrate_cadence_to_format.py`(既定 dry-run、`--apply`/`--rollback`/`--notion`)。`Post` に旧値受理シム(`models.py` の `model_validator`)があるのでデプロイ→移行の順序事故は非致命。手順は `docs/runbook.md` の移行 runbook 参照
- `items` のドキュメントID = 正規化URLのハッシュ(トランザクションで完全重複排除)。タイトル近似重複は7日窓で除外
- `10-deploy-pipeline.sh` は `--set-env-vars` で env を**毎デプロイ全置換**する — `gcloud run jobs update` で手動追加した env 上書きは `./deploy.sh` で消える。モデル名等の恒久設定は config.py(シークレットは Secret Manager)だけに置くこと。残り得る旧モデル固定(`promptTemplates.modelOverride`)は deploy.sh 末尾のチェックが警告する
- pipeline-api はアプリレベル認証なし(意図的)。`--no-allow-unauthenticated` + Cloud Run IAM(admin-sa の run.invoker)で保護
- 本プロジェクトは組織なし GCP のため、IAP はカスタム OAuth クライアントを `gcloud iap settings set` で適用済み。IAP が使えない場合の NextAuth 代替は docs/runbook.md 参照
- Gemini/OpenAI キーは Secret Manager 管理。AI Studio で発行したキーは別の無課金プロジェクトに紐づきグラウンディングに使えない — gcloud でプロジェクト内発行すること
- GCS 署名URL は pipeline-sa の self token-creator で発行(秘密鍵なし)。この IAM を外すと画像添付が壊れる
- テストの HTTP モックは respx。X の OAuth 1.0a は自前実装(`publishers/x.py`)なので署名ロジック変更時は `test_oauth1.py` を必ず通す
- **research のプロンプトは英語固定**(`research/prompts.py`。`test_prompts.py` が CJK 混入を禁止)。日本語が入るのは Firestore の `promptTemplates`(文体)と `customInstructions` の層だけ — 出力言語の指定は英語プロンプト内で行う(canonical=ja)。**共有フラグメント(`_TRUST_HIERARCHY`)は f-string で定数の定義時に補間すること** — 呼び出し時に連結すると `PROMPT_VERSION` のハッシュから漏れ、本文が変わったのに版が変わらない嘘の manifest になる
- **deep_research は `build_registry(budget)` に Budget を渡したときだけ登録される**(1本 ~$2)。予算 $0.7〜$3 のリサーチチャットは Budget を渡さないので DR を持たない — この防御を外さないこと。`STRATEGY_MATRIX` にも**入れない**(入れるとチャットの `VALID_CONNECTORS` 経由で波及する)。注入は `plan.py::_inject_deep_research` が RQ[0] 末尾に1回だけ行う決定的処理。registry と `RunContext` には**同一 Budget インスタンス**を渡すこと(別だと `drCallsUsed` が別勘定になり one-shot ゲートが効かない)。課金はトークン+**web 検索 $0.01/回**の2階建て(tool 側が大半 — トークンだけだと数倍の過少計上)
- **信頼源の優先はプロンプトではなくコードが強制する**(`rubric.py` の citation gate / `plan.py` の `STRATEGY_MATRIX` / `gather.py` の tertiary 除外 / `verify.py` の coverage)。プロンプトは助言にすぎず、矛盾したら必ずコードが勝つ — プロンプト強化時はコード側の不変条件と矛盾させないこと(`test_trusted_source_invariants.py` が成果物レベルで固定)
- **LangSmith SDK は `Settings` ではなく `os.environ` を直読する** — `.env` は pydantic-settings が `Settings` に読むだけで `os.environ` に入らないため、ローカルで `.env` にだけ書くと「クライアントは wrap 済みなのにトレースが1件も出ない」無言の食い違いになる(本番は実 env なので発生せず、気付けない)。`observability._export_env()` が解決済み値を `os.environ` へ書き戻して吸収している(SDK の env は lru_cache されるのでクリアも必要)。なお SDK はレガシーな `LANGCHAIN_*` を `LANGSMITH_*` より優先する
- **その `_export_env()` は「グラフが始まる前」に走らないと意味が無い** — langchain_core はランナブル開始時に `os.environ` を読んでトレーサーを付けるか決めるので、遅いエクスポートはトレースを**劣化させるのではなく消滅させる**(`wrap_openai` のスパンだけが親無しの `ChatOpenAI` として届き、`runner._config()` の run_name/tags/metadata を持たない = runId で相関できず管理画面のトレースカードにも出ない)。`ls_client()` 任せだと初回到達が最初の LLM 呼び出しの内側になるため、`observability.init_tracing()` を `jobs/generate_report.py::main` と `app/main.py` の import 時に置いている。**新しいエントリポイントを足すときは同じことをすること**(`test_observability.py::test_init_tracing_enables_the_tracer_before_any_llm_call` が固定)
- **管理画面のトレース表示は LangSmith を読み戻している**(`admin/src/lib/langsmith.ts` = Firestore 以外を読む唯一の data 層。`langsmith` npm は入れず素の fetch。失敗は全て `null` に潰してカードごと消す)。**Firestore の `events` にプロンプト本文・生レスポンス・LLM ごとのレイテンシ・入れ子は無い** — 増やす前に「LangSmith にあるものを二重に持つ必要が本当にあるか」を先に問うこと
- **テストから `LANGSMITH_*` を消すには `delenv` では不十分** — `Settings` は env だけでなく `pipeline/.env` も読むため、手元でトレーシングを有効にしていると suite が実キーで LangSmith に送信してしまう(respx の厳格性も壊れる)。`tests/conftest.py` の autouse fixture は env を**空/false に setenv**して dotenv 層ごと打ち消している(env > .env の優先順位を利用)

## ドキュメント

- `docs/setup-credentials.md` — X/Threads/Notion/OpenAI/Gemini の認証情報発行手順
- `docs/runbook.md` — 障害対応(投稿失敗・トークン失効・収集0件・quota 超過)とコスト監視
- `docs/tech-report/` — 技術詳細文書(要件定義・構成図・データモデル・パラメーター・詳細設計)。人間向けの一次資料
- **コード・設定・インフラを変更したら `docs/tech-report/README.md` の対応表で該当文書を特定し、必ず同時に更新すること**(要件変更→01、リソース変更→02/04、スキーマ変更→03、実装変更→05 配下)
