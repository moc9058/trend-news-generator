# 認証情報セットアップ手順

`infra/01-secrets.sh` を実行する前に、以下の値を揃えてください。

## 1. X (Twitter) — OAuth 1.0a + プリペイドクレジット

1. https://console.x.com でサインイン → プロジェクト & アプリを作成
2. **課金**: Billing でプリペイドクレジットを購入（従量課金: 投稿 $0.015/件、URL入り投稿 $0.20/件。本システムの既定運用は月 $5 前後）
3. アプリの **User authentication settings** を設定（Read and write権限）
4. **Keys and tokens** タブで取得:
   - API Key / API Key Secret（= consumer_key / consumer_secret）
   - Access Token / Access Token Secret（自分のアカウントで発行、Read and write）
5. `01-secrets.sh` には1行JSONで入力:
   ```json
   {"consumer_key":"...","consumer_secret":"...","access_token":"...","access_token_secret":"..."}
   ```

> 注意: X はクレジット残高照会APIを提供していません。残高切れは投稿失敗としてダッシュボード（posts の failed ステータス）に現れます。

## 2. Threads — long-lived token（60日、週次ジョブが自動更新）

1. https://developers.facebook.com → アプリ作成 → ユースケースに **Threads API** を選択
2. 権限: `threads_basic`, `threads_content_publish`
3. アプリに自分の Threads アカウントをテスター追加 → Threads 側で承認
4. Graph API Explorer 等で OAuth フローを1回実施し short-lived token を取得
5. long-lived token に交換:
   ```
   curl "https://graph.threads.net/access_token?grant_type=th_exchange_token&client_secret=<APP_SECRET>&access_token=<SHORT_TOKEN>"
   ```
6. Threads user ID を取得:
   ```
   curl "https://graph.threads.net/v1.0/me?fields=id&access_token=<LONG_TOKEN>"
   ```
7. `threads-access-token`（long-lived token）と `threads-user-id` を登録

以後は `job-refresh-threads-token`（毎週月曜 03:00 JST）が自動でトークンを更新し、新バージョンを Secret Manager に追加します。

## 3. Notion — internal integration

1. https://www.notion.so/my-integrations → **New integration**（対象ワークスペース選択、Read/Insert/Update content）
2. 「**Trend News**」データベースを作成。必須プロパティ:
   - `Name`（タイトル）/ `Category`（セレクト）/ `Format`（セレクト。short/article/report）/ `Date`(日付)
   - レポート機能を使う場合は `Language`（セレクト。ja/ko/en）も追加（言語別3ページに付与）。選択肢は初回書込みで自動作成される
   - ※旧環境から移行する場合は `Cadence`→`Format` のリネーム（`pipeline/scripts/migrate_cadence_to_format.py --notion` または手動 UI）。手順は runbook の「区分リネーム移行」参照
3. DB ページ右上 **…** → **Connections** → 作成した integration を接続
4. **Share → Publish** で DB を Web 公開（X/Threads に貼る公開URLのため）
   - ※子ページが公開URLを持つかは最初の週次投稿で要確認。継承されない場合は投稿にURLを含めない運用に切替可（`channels` 設定は不要、リンクは自動で付かなくなるだけ）
5. DB の URL から database ID（32桁hex）を控える → 管理画面 **Settings → Notion database ID** に入力
6. integration token（`ntn_` または `secret_` で始まる）を `notion-api-key` に登録

## 4. OpenAI / Gemini

- OpenAI: https://platform.openai.com → API key 発行。使用モデル: gpt-5.4-mini（短文・調査の軽量系）/ gpt-5.5（記事・レポートの推論系）。**Deep Research 補助**（レポートのみ・任意）を使う場合は `o4-mini-deep-research`（Responses API, background）へのアクセスが必要。`DEEP_RESEARCH_PROVIDER=openai`（既定）で有効、`off` で無効。1本1回・予算残<$3 で自動スキップ
- Gemini: https://aistudio.google.com → **Get API key**（Vertex 不要）。Grounding with Google Search は Gemini 3 系で月5,000プロンプト無料。短文収集に加えレポートの `web_grounded`/`gov_docs`/`news` コネクタでも使用

## 5. 学術・議事録・書籍コネクタ（レポート機能・すべて任意/無料）

レポート(report)の調査コネクタは基本キー不要:

- **国会会議録**（`kokkai`）・**e-Gov 法令 / go.jp**（`gov_docs`）・**OpenAlex / Crossref / arXiv**（`academic` のフォールバック）・**Google Books / NDL**（`books`）はキー不要
- **Semantic Scholar**（`academic` の第1候補）は**任意**でレート上限を上げる API キーを取得可: https://www.semanticscholar.org/product/api → `semantic-scholar-api-key` に登録（`01-secrets.sh`、空でも OpenAlex/Crossref にフォールバックして動作）

## 6. IEEE Xplore（任意）

1. https://developer.ieee.org → アカウント登録 → **Metadata Search API** の API key を申請（無料、~200コール/日）
2. `01-secrets.sh` で `ieee-api-key` に登録（スキップ可）
3. 管理画面 **Sources** で `scitech-ieee` ソースを有効化、またはクエリを追加

> arXiv は API キー不要です。arXiv API は Atom を返すため `rss` タイプのソースとしてそのまま登録できます（seed 済みの `scitech-arxiv-csai` を有効化するか、`https://export.arxiv.org/api/query?search_query=cat:cs.AI&sortBy=submittedDate&sortOrder=descending&max_results=10` の形式で追加）。

## 7. GCP

課金が有効なプロジェクト `trend-news-generator` を用意し、オーナー権限の gcloud CLI で:

```bash
cd infra
./00-bootstrap.sh   # API有効化, Firestore, GCS, Artifact Registry, SA, IAM
./01-secrets.sh     # 上で揃えた値を対話式で登録
./10-deploy-pipeline.sh
gcloud run jobs execute job-seed --region asia-northeast1 --wait
./11-deploy-admin.sh
./20-schedulers.sh
```
