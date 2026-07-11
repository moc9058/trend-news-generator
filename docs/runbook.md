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

## コスト監視

- ダッシュボードに当月 LLM コスト（runs.costUsd 集計）
- X 投稿コストの目安: 日次 3件/日 × $0.015 + 週次/月次 URL入り ≈ 月 $5 未満
- GCP 側は Billing コンソールで budget alert（$30）を設定推奨

## ローカルでの単発実行

```bash
cd pipeline
cp .env.example .env   # 値を記入
gcloud auth application-default login
python -m app.jobs.collect
python -m app.jobs.generate_daily
```

## 安全弁

- **Settings → dailyRequireApproval**: 日次も承認必須にする（品質問題発生時）
- **Settings → attachImages**: 収集画像の添付を全停止（著作権リスク対応）
- チャネル単位の停止: Channels ページのチェックボックス
