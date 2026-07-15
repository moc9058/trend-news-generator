# 運用 Runbook

## 日常運用

| 時刻 (JST) | ジョブ | 動作 |
|---|---|---|
| 毎日 06:00 | job-collect | Gemini grounding + RSS/arXiv/IEEE → items 蓄積 |
| 毎日 08:00 | job-generate-daily | 短文生成 → X/Threads/Notion へ自動投稿 |
| 月曜 07:00 | job-generate-weekly | 週次分析記事の**下書き**生成 → 管理画面で承認 |
| 毎月1日 07:00 | job-generate-monthly | 月次レポートの**下書き**生成 → 管理画面で承認 |
| 月曜 03:00 | job-refresh-threads-token | Threads トークン更新 |

週次・月次の下書きは 管理画面 → Drafts → 編集/プレビュー → **承認して投稿**。

## 障害対応

### チャネル投稿失敗（posts に failed バッジ）
1. Posts ページでエラーメッセージ確認
2. 一時障害（429/5xx はパイプラインが3回リトライ済み）→ **リトライ**ボタン
3. X の 402/課金系エラー → console.x.com でクレジット残高を補充してからリトライ
4. 二重投稿の心配は不要: externalId 記録済みチャネルはスキップされ、Threads は containerId から再開

### 誤投稿の削除・チャネルの一括停止
- **公開済み投稿の削除**: Posts ページのチェックボックスで複数選択して削除(投稿ごと削除)、または投稿詳細ページでチャネル単位に削除。実体は pipeline-api の `POST /api/posts/{id}/delete` — X ツイート/Threads メディアは削除、Notion ページはアーカイブ(report の言語別ページ含む)。**X のスレッド投稿は先頭ツイートしか消えない**(返信ツイートは X 上で手動削除)
- **チャネルを全カテゴリで止める**: Settings のグローバルチャネルスイッチ(`settings/app.globalChannels`、既定 X=off / Threads=off / Notion=on)。カテゴリ別 channelConfigs と AND で効き、次の生成から反映(既公開の投稿には影響しない)

### Threads トークン
- ダッシュボードに赤バナー（refresh 失敗）または期限14日未満 → 手動リフレッシュ: Settings → `refresh_threads_token` **今すぐ実行**
- 完全失効した場合: docs/setup-credentials.md §2 の手順で再OAuth → `gcloud secrets versions add threads-access-token --data-file=-`

### 収集が0件
- Runs の collect エラー確認。RSS 障害はソース単位でスキップされるので他ソースには影響なし
- Sources ページでソースを個別に無効化/修正 → **collect を今すぐ実行**

### Gemini grounding 無料枠（月5,000）超過
- 使用量は https://aistudio.google.com で確認。超過時は gemini_grounded ソースを一部無効化するか課金を許容（本システムの使用量は枠の3〜4%）

### Cloud Run 直結 IAP が使えない場合（組織ポリシー等）
代替: admin-ui を `--allow-unauthenticated` にせず、NextAuth (Google provider) + `moc9058@gmail.com` allowlist を実装して認証を持ち込む。middleware.ts に認証ガードを追加し、`iap.ts` の代わりにセッションから承認者メールを取る。

### Research Agent（レポート）の失敗対応
実体は `researchRuns/{id}`（status / phase / budget と、サブコレクション evidence/claims/events）。admin の **Research → 実行詳細**でタイムライン・証拠・claims・コストを確認できる。

- **`budget_exhausted` で停止**: 予算上限に達し次フェーズに入れず graceful 停止。部分成果（計画・証拠一覧）は閲覧可能。続きは**新しい run**（予算を上げて）で。同一 run の継続は行わない設計（doc 10 §7.2）
- **`failed`**: `events` の `ok:false` 行と `error` を確認。多くはコネクタ断か LLM スキーマ不正。**resume**: run は lease 方式なので、`gcloud run jobs execute job-generate-report --region asia-northeast1` で再実行すると `claim_next` が最後の完了フェーズから再開する（全フェーズ冪等）
- **`running` のまま固まる**: heartbeat が30分超で stale とみなされ、次の job 実行が自動で奪取・再開する。手動なら上記の execute を叩く
- **コネクタが 429 嵐 / 連続失敗**: 5連続失敗で当該コネクタは run 内で自動無効化（サーキットブレーカ）され、カバレッジに未充足として残る。恒常的なら該当コネクタのキー/クォータを確認
- **cancel**: admin の「実行をキャンセル」→ `cancelRequested=true`。Harness が次のフェーズ境界で `cancelled` にして停止

### リサーチチャットの失敗対応
実体は `chatThreads/{id}` と サブコレクション `messages/{id}`（status / sources / usage）。設計は doc 11。**チャットは投稿を一切行わない**（handoff も下書き止まり）ので、障害の影響は「答えが出ない」までで、公開事故には繋がらない。

- **回答が途中で止まる / 進捗が出ない**: まず `messages/{id}.status` を見る。`error` なら `error` フィールドに原因が入っている。`streaming` のまま固まっているのは異常（ワーカーが番兵を積む前に死んだ場合のみ起きうる。doc 11 §6.1）— Cloud Logging で `chat run failed` を検索
- **ブラウザだけ切れた場合**: run はサーバ側で完走して Firestore に書き切るので、**リロードすれば完全な回答が出る**。再送は不要
- **Stop が効かない**: `cancelRequested=true` はノード境界と約5秒間隔のポーリングで拾う。deep 調査は fetch 中だと最大数秒遅れる。最終ステータスは必ず読み直して確定するので、`complete` で終わったなら実際にキャンセルより先に完了している
- **`budget_exhausted` 相当（quick $0.7 / deep $3 上限）**: 例外にはならず、そこまでの材料で「打ち切った」と明示した回答が返る。恒常的に足りないなら `config.py` の `chat_budget_*_usd` を上げて再デプロイ（env 上書きは毎デプロイ消えるので不可）
- **出典が0件**: コネクタ断か、質問がコネクタの守備範囲外。回答は「見つけられなかった」+ 無出典と明記した形で返る。`gemini-api-key` を確認（`web_grounded` は Gemini キーが無いと**コネクタ構築自体が失敗**し、そのメッセージは `error` になる）
- **コスト**: `chatUsage/{YYYY-MM}` に月次集計。ダッシュボードのコストカードに含まれる

### LangSmith（トレーシング）
LLM 呼び出しの可視化のみを担う**任意の観測基盤**。UI は https://smith.langchain.com のプロジェクト `trend-news-generator`（1 LLM 呼び出し = 1トレース。モデル名・トークン数・レイテンシ・プロンプト/生成文の全文が見える）。

- **障害の影響範囲はトレースの欠落だけ**。SDK はバックグラウンド送信で自身の例外を飲み込み、`utils/observability.py` も全例外を swallow + warn ログにするため、LangSmith が落ちても停止しても run は正常に完走する。「トレースが出ない」以外の症状が出たらそれは別の原因
- **有効・無効の切り替え**: `langsmith-api-key` シークレットの有無が唯一のスイッチ。**止めたいとき** = `gcloud secrets delete langsmith-api-key`（または最新バージョンを disable）→ `./deploy.sh --skip-seed`。env は毎デプロイ全置換なので確実に消える。**戻すとき** = `./infra/01-secrets.sh` でキーを投入 → 再デプロイ
- **キーが無効・期限切れ**: warn ログ（`langsmith flush failed` / `langsmith client init failed`）が出るだけで run は完走する。急がず次のデプロイで差し替えてよい
- **プライバシー**: プロンプト・生成文・収集記事の抜粋が**全文そのまま米国の SaaS へ送られる**（ユーザー承認済みの既定。エンドポイントは未設定 = US）。送信したくないデータを扱う場合は上記のキルスイッチで無効化すること
- 無料枠は月 5,000 トレース / 保持14日。本システムの想定は短文 ~90 + 記事 ~4 + レポート 1 run/月 で枠の 5% 未満

## コスト監視

- ダッシュボードに当月 LLM コスト（runs.costUsd 集計）
- X 投稿コストの目安: 短文 3件/日 × $0.015 + 記事 URL入り ≈ 月 $5 未満
- **レポート費用**: 1本あたりハード上限 $10（`researchRuns.budget.usdCap`。超過は構造的に不可）。Deep Research を有効化した場合は +~$2/回（1本1回まで）
- **チャット費用**: 1メッセージあたりハード上限 quick $0.7 / deep $3（`config.py` の `chat_budget_*_usd`）。壁打ちは実費のみ。使った分は `chatUsage/{YYYY-MM}` に積まれ、ダッシュボードの当月コストに合算される。**上限は1メッセージ単位なので、月次の総額は使った回数次第** — 想定外に伸びたらここを見る
- GCP 側は Billing コンソールで budget alert（$30）を設定推奨

## 区分リネーム移行（cadence → format, P0）

daily/weekly/monthly を short/article/report に一括変換する一度きりの移行。スクリプトは `pipeline/scripts/migrate_cadence_to_format.py`（既定 dry-run、`--apply`/`--rollback`/`--notion`）。

**推奨: `./deploy.sh --migrate`** が下記1〜10をこの安全な順序（バックアップ→インデックス→**pause**→デプロイ→dry-run→apply→admin→schedulers→resume→孤児削除）で一括実行する。破壊的手順（apply・孤児削除）は確認プロンプトが出る（`--yes` で無人実行）。Python はデフォルトで `pipeline/.venv/bin/python`（`PYTHON=...` で上書き可）を使い、ADC 認証と `pip install -e '.[dev]'` 済みが前提。手動で行う場合の詳細順序は以下:

> **pause は必須**: 旧 Cloud Run ジョブは旧イメージ digest のまま動き続けるため、pause を省略すると「旧コード×移行済みデータ」で `cleanup_drafts` が ValidationError で落ち、旧 `generate-daily` が Notion 400（"Cadence" プロパティ消失）を起こす。

1. **バックアップ**: `gcloud firestore export gs://trend-news-generator-media/backups/pre-format-YYYYMMDD`
2. **複合インデックスを先に作成**（ビルドが非同期のため先行）: `posts(format, createdAt DESC)` + `researchRuns(status, createdAt ASC)`（`infra/firestore.indexes.json` / `00-bootstrap.sh` に反映済み）
3. **スケジューラ pause**: `sched-collect / sched-generate-daily / -weekly / -monthly / sched-cleanup-drafts`（`sched-threads-refresh` は cadence 非依存で継続可）
4. **新コードデプロイ**（`10-deploy-pipeline.sh`）: pipeline-api 更新 + `job-generate-short/article` 新規作成（旧 `job-generate-{daily,weekly,monthly}` は残置＝ロールバック用）
5. `migrate_cadence_to_format.py`（引数なし=dry-run）→ 差分レビュー → `--apply`
6. **Notion DB**: `--notion` で `PATCH /v1/databases/{id}` により "Cadence"→"Format" リネーム + `Language` セレクト追加（手動 UI でも可）。セレクト選択肢は初回書込みで自動作成。旧ページは旧値のまま容認
7. **admin 再ビルド・デプロイ**: `admin/src/lib/shared-constants.json` の再生成をコード変更と同一コミットに含める（admin の Docker ビルドは `shared/` を参照できず committed copy にフォールバックするため、忘れると旧 enum が本番に出る）
8. `20-schedulers.sh` 再実行（`sched-generate-short/article` 作成）→ **名前が変わらない paused スケジューラを明示 resume**: `sched-collect / sched-cleanup-drafts`
9. **孤児削除**: `gcloud run jobs delete job-generate-{daily,weekly,monthly}` / `gcloud scheduler jobs delete sched-generate-{daily,weekly,monthly}`
10. スモーク（短文自動生成1件・admin グリッド表示・`promptTemplates`/`channelConfigs` 件数 9/27 一致）後、旧 `posts(cadence, createdAt)` 複合インデックスを削除

ロールバック: `migrate_cadence_to_format.py --rollback --apply`（逆写像）。`Post` の旧値受理シムにより移行/デプロイの順序事故は非致命。`gcloud firestore import` は export 後に作成された新 ID 文書を消さないため最終手段。

## ローカルでの単発実行

```bash
cd pipeline
cp .env.example .env   # 値を記入
gcloud auth application-default login
python -m app.jobs.collect
python -m app.jobs.generate_short
```

## 安全弁

- **Settings → shortRequireApproval**: 短文も承認必須にする（品質問題発生時）
- **Settings → attachImages**: 収集画像の添付を全停止（著作権リスク対応）
- チャネル単位の停止: Channels ページのチェックボックス
