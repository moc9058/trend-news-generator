# コードの読み方入門+用語集

> 対象コード時点: コミット f703290 + 未コミット変更 / 最終更新: 2026-07-12
## 1. この文書の使い方
この文書は、詳細設計書([01-pipeline-foundation.md](01-pipeline-foundation.md)〜[09-tests.md](09-tests.md))とコードを読む**前に一度通読する**ための教材です。プログラミング経験がほぼゼロでも読めるように、このリポジトリに実際に登場する概念だけを、実物のコード断片で説明します。細部の暗記は不要で、「そういう仕組みがある」と一度知ることが目的です。使い方は 2 段階 — (1) まず頭から通読する。(2) 以後、詳細設計書やコードで分からない言葉が出たら巻末の用語集(§10)を引き、必要なら本文の該当節へ戻る。コード断片はすべて本リポジトリからの転記で、出典を明記しています。全体像は [../03-data-model.md](../03-data-model.md) と [../04-parameters.md](../04-parameters.md) も参照してください。
## 2. コードを読む前の地図
### 2.1 リポジトリ構成
```
trend-news-generator/
├── pipeline/app/        # Python。収集・生成・投稿の本体(Cloud Run で動く)
│   ├── jobs/            #   6 つのジョブの入口(collect, generate_daily, seed ...)
│   ├── collectors/      #   収集(rss / gemini_grounded / ieee_xplore / enrich)
│   ├── generators/      #   文章生成(daily / longform / OpenAI 呼び出し)
│   ├── publishers/      #   投稿(notion / x / threads と全体指揮の base)
│   ├── repo/            #   Firestore の読み書き係
│   ├── main.py          #   pipeline-api(管理画面から呼ばれる HTTP 窓口)
│   ├── models.py        #   データの形の定義
│   └── config.py        #   設定(環境変数・シークレット)
├── pipeline/tests/      # pytest のテスト
├── admin/src/           # TypeScript / Next.js。管理画面(admin)
├── infra/               # gcloud のデプロイスクリプト(番号順に実行)
└── shared/constants.json  # Python と TypeScript で共有する選択肢一覧
```
### 2.2 「エントリポイント」という考え方
コードは上から全部読むものではありません。**実行が始まる場所(エントリポイント)を見つけ、そこから呼び出される先を必要な分だけ辿る**のがコツです。本リポジトリの入口は 3 種類あります。1 つ目は**ジョブ**です。Cloud Run が `python -m app.jobs.collect` のようにモジュールを起動すると、ファイル末尾のこの決まり文句が `main()` を呼びます。
```python
if __name__ == "__main__":
    main()
```
(出典: `pipeline/app/jobs/collect.py` 末尾。全ジョブ共通の形)

2 つ目は **pipeline-api(常駐サービス)**で、コンテナの起動コマンドが Web サーバを立ち上げます。
```dockerfile
# Cloud Run service entrypoint. Jobs override with:
#   --command python --args -m,app.jobs.<name>
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
```
(出典: `pipeline/Dockerfile`。同じイメージを、起動コマンドだけ変えてサービスとジョブの両方に使う)

3 つ目は**管理画面**です。Next.js では URL がそのまま入口で、`/sources` を開くと `admin/src/app/[locale]/sources/page.tsx` が実行されます。§9 でジョブの入口から実際に辿ってみます。
## 3. Python 編(pipeline)
### 3.1 デコレータ — 関数に機能を「かぶせる」@ 記法
関数定義の直前に `@名前` と書くと、中身を変えずに機能を後付けできます(包装紙のイメージ)。本リポジトリの代表例は 3 つです。まず `@lru_cache` は「初回の結果を記憶して使い回す」。設定を毎回作り直さないための、いわゆるシングルトンです。
```python
@lru_cache
def get_settings() -> Settings:
    return Settings()
```
(出典: `pipeline/app/config.py` の `get_settings()`。`repo/client.py` の `db()` や `utils/gcs.py` も同じ形)

次に `@api_retry` は「失敗したら自動でやり直す」を後付けします(§3.11)。X / Threads / Notion の API 呼び出し全部に付いています。
```python
@api_retry
def post_tweet(
```
(出典: `pipeline/app/publishers/x.py` の `post_tweet()` 冒頭)

最後に `@app.post(...)` は「この URL に POST が来たらこの関数を実行する」という紐付けです(§3.12)。
```python
@app.post("/api/posts/{post_id}/publish")
def publish(post_id: str, req: PublishRequest) -> dict:
```
(出典: `pipeline/app/main.py` の `publish()` 冒頭)
### 3.2 pydantic の BaseModel と model_dump — 型検証付きのデータ入れ物
`BaseModel` を継承したクラスは「名前と型が決まった入れ物」になり、違う型の値を入れるとその場でエラーになります。壊れたデータが奥まで流れ込みません。`pipeline/app/models.py` に全データの形が定義され、[../03-data-model.md](../03-data-model.md) と 1 対 1 に対応します。
```python
class ImageRef(BaseModel):
    gcsPath: str
    mime: str
```
(出典: `pipeline/app/models.py` の `ImageRef`)

`model_dump()` はモデルをただの辞書(§3.7)に変換します。Firestore は辞書しか受け取らないので、保存の直前に必ず登場します。
```python
def start(job_type: str) -> str:
    run = Run(jobType=job_type, startedAt=datetime.now(timezone.utc))
    _, ref = db().collection(COLLECTION).add(run.model_dump(exclude={"id"}))
    return ref.id
```
(出典: `pipeline/app/repo/runs.py` の `start()`。`exclude={"id"}` は「id だけ除いて辞書化」)
### 3.3 pydantic-settings — 環境変数が自動で設定になる
環境変数とは OS がプログラムに渡す「名前=値」のメモです。`BaseSettings` を継承すると、フィールドと同名の環境変数(`openai_api_key` ← `OPENAI_API_KEY`)が自動で読み込まれます。
```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    project_id: str = "trend-news-generator"
    region: str = "asia-northeast1"
    timezone: str = "Asia/Tokyo"
    gcs_bucket: str = "trend-news-generator-media"
```
(出典: `pipeline/app/config.py` の `Settings` 冒頭)

優先順位は「**環境変数 > `.env` ファイル > コード内の既定値**」。本番では Cloud Run が環境変数とシークレットを注入し、ローカルでは `.env` を使います。モデル名や API キーは**すべてこのクラス経由**です。ただし本番ジョブ側に `GEMINI_MODEL` 等の上書きが入っている場合があるので、モデル名変更時は config.py と gcloud 設定の両方を確認します(CLAUDE.md の落とし穴)。
### 3.4 `class X(str, Enum)` — 文字列としても使える列挙値
Enum(列挙型)は「決まった選択肢しか取れない値」です。`str` も同時に継承すると、選択肢でありながら普通の文字列として Firestore にそのまま保存できます。
```python
class Cadence(str, Enum):
    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"
```
(出典: `pipeline/app/models.py`。カデンス=投稿頻度の区分。`PostStatus` や `Channel` も同じ作り。`Cadence.daily.value` が文字列 `"daily"` で、タイプミス由来の不正な値を型の段階で防ぐ。選択肢の一覧は `shared/constants.json` にもあり TypeScript 側と共有 — §4.6)
### 3.5 Protocol — 継承なしで「同じ形なら OK」
収集元は RSS・Gemini 検索・IEEE Xplore と方式がバラバラですが、呼ぶ側は「`collect(source)` を呼べば収集アイテムのリストが返る」ことだけ知っていれば十分です。`Protocol` はその「形」だけを宣言します。各コレクタは継承せず、同名・同型のメソッドを持つだけで合格です(構造的型付け)。
```python
class Collector(Protocol):
    def collect(self, source: Source) -> list[RawItem]: ...
```
(出典: `pipeline/app/collectors/base.py`。collect ジョブは種類→実物の辞書 `collectors = {SourceType.rss: RssCollector(), ...}` から選ぶだけ — `jobs/collect.py`)
### 3.6 try/except — 3層の障害隔離
`try:` の中でエラー(例外)が起きると `except:` に飛んで後始末ができます。方針は「**1 つの失敗で全体を殺さない**」で、隔離の壁が 3 層あります。

- ソース単位(collect): 1 つの RSS が死んでいても他ソースの収集は続ける
- カテゴリ単位(generate 系): 1 カテゴリの生成失敗を他カテゴリに波及させない
- チャネル単位(publish): X が失敗しても Notion / Threads へは投稿する

```python
            try:
                raw_items = collector.collect(source)
            except Exception as exc:
                msg = f"source {source.id or source.url or source.query}: {exc}"
                log.warning("collector failed", extra={"fields": {"error": msg}})
                run.errors.append(msg)
                continue
```
(出典: `pipeline/app/jobs/collect.py` の `main()`。`continue` = このソースは諦めて次へ)

使い分けの原則も重要です。og:image 取得のような**ベストエフォート(あれば嬉しい程度)の関数は例外を握りつぶして空値を返します**(`collectors/enrich.py` の `fetch_page()` は失敗時に `return "", ""`)。一方、**本業の関数(収集・投稿そのもの)は例外をそのまま上に投げ、上記の隔離層に任せます**。どの層で受け止めるかが設計です([02-collect.md](02-collect.md) / [03-generate.md](03-generate.md) / [04-publish.md](04-publish.md) の各エラー処理節)。
### 3.7 辞書のテクニック — 展開と後勝ち・get のフォールバック・**kwargs
辞書(dict)は「キー: 値」の入れ物です。`{**a, **b}` は a と b を混ぜた新しい辞書を作り、**同じキーは後に書いた方が勝ちます**。「既定値を先に、個別指定を後に」並べると上書き付きの初期化になります。
```python
    for src in SOURCES:
        data = {"enabled": True, "etag": "", "lastModified": "",
                "url": src.get("url", ""), "query": src.get("query", ""), **src}
        source_id = data.pop("id")
        created += _create_if_absent("sources", source_id, data)
```
(出典: `pipeline/app/jobs/seed.py` の `main()`。既定値の後ろの `**src` が勝つ)

`dict.get("キー", 既定値)` は「キーが無ければ既定値」。`or` と組み合わせるとフォールバックの連鎖になります(`collectors/rss.py` の `entry.get("published_parsed") or entry.get("updated_parsed")`)。関数定義側の `**kwargs`(名前は `**extra` 等でもよい)は「任意の名前付き引数を辞書でまとめて受け取る」記法です。
```python
def set_status(post_id: str, status: PostStatus, **extra) -> None:
    updates: dict = {"status": status.value, **extra}
    db().collection(COLLECTION).document(post_id).update(updates)
```
(出典: `pipeline/app/repo/posts.py`。呼ぶ側は `posts.set_status(post_id, final, publishedAt=...)` と追加項目を自由に渡せる)
### 3.8 f-string と str.format — 文字列の穴埋め
`f"...{変数}..."`(f-string)はその場で変数を埋め込みます。
```python
            ext = mime.split("/")[-1]
            path = f"items/{doc_id}/og.{ext}"
```
(出典: `pipeline/app/jobs/collect.py` の `_persist()`。GCS の保存先パスを組み立てている)

一方、プロンプトのように「穴あきの文面を先に用意して後から埋める」場合は `str.format()` です。テンプレートには `{items}` のようなプレースホルダ(穴)が開いています。
```python
DAILY_USER = """Today is {date}. Category: {category}.

Source items (title / summary / url):
{items}
```
(出典: `pipeline/app/generators/prompts.py` の `DAILY_USER` 冒頭)
```python
    user_prompt = template.userPromptTemplate.format(
        items=prompts.format_items_for_prompt(recent),
        category=category.name,
        date=today,
```
(出典: `pipeline/app/generators/daily.py` の `generate_for_category()`。注意点が 1 つ — プロンプト内に本物の `{ }` を書きたいとき(JSON の例を見せるとき)は `{{ }}` と二重に書いてエスケープする。`prompts.py` に多数ある `{{` は誤記ではない)
### 3.9 ハッシュ・正規化・正規表現 — 重複排除の道具箱
ハッシュは、どんなデータからも固定長の「指紋」を作る計算です(SHA-256 が代表)。同じ入力からは必ず同じ指紋ができ、逆算はできません。URL の指紋を Firestore のドキュメント ID にして二重保存を防ぎます(§6.5)。長すぎるので先頭 32 文字に切り詰めます。
```python
def item_doc_id(canonical_url: str) -> str:
    return hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()[:32]
```
(出典: `pipeline/app/normalize.py`)

指紋を取る前には**正規化**(表記ゆれを揃える作業)が要ります。タイトルの近似重複判定では `unicodedata.normalize("NFKD", ...)` で全角やアクセントの飾りを分解し、**正規表現**(文字パターンの記法。`_WORD_RE = re.compile(r"[a-z0-9가-힣぀-ヿ一-鿿]+")` = 英数字・ハングル・かな・漢字の連なり)で単語だけ拾い、並べ替えて語順の違いも吸収します。
```python
def normalize_title(title: str) -> str:
    """Lowercased, accent-stripped, sorted word bag — order-insensitive."""
    title = unicodedata.normalize("NFKD", title).lower()
    words = sorted(set(_WORD_RE.findall(title)))
    return " ".join(words)
```
(出典: `pipeline/app/normalize.py`。URL 正規化 `canonicalize_url()`(utm_ 等の追跡パラメータ除去)も同ファイル。実例は `tests/test_normalize.py` が良い教材)
### 3.10 タイムゾーン付き datetime — UTC で保存し JST で考える
時刻には「どこの時刻か」(タイムゾーン)を必ず付けます。保存・計算は世界標準時 UTC に統一し、人間向けの予定だけ日本時間 JST で考えるのが本システムの流儀です。
```python
def title_hash_seen_since(category_id: str, title_hash: str, days: int = 7) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
```
(出典: `pipeline/app/repo/items.py`。「7 日前」の計算も UTC。ジョブの起動時刻はスケジューラ側で JST 指定 — §5.7。「Firestore を直接覗くと時刻が日本時間より 9 時間前に見える」と覚えておくと混乱しない)
### 3.11 tenacity — 指数バックオフと「リトライしてよい失敗」
外部 API は時々失敗します。tenacity はリトライ(自動再試行)のライブラリで、方針を 1 箇所に集約しています。要点は**失敗の区別**です。429(呼びすぎ)と 5xx(相手側の一時障害)は待てば直るので再試行し、それ以外の 4xx(こちらの指定が悪い)は何度やっても同じなので即座に諦めます。
```python
def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return code == 429 or code >= 500
    return isinstance(exc, (httpx.TransportError, httpx.TimeoutException))
```
```python
api_retry = retry(
    retry=retry_if_exception(_is_retryable),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    reraise=True,
)
```
(出典: いずれも `pipeline/app/utils/retry.py`。`wait_exponential` が指数バックオフ = 待ち時間を 2 秒→4 秒→8 秒と倍々に延ばす(上限 30 秒・計 3 回)。混んでいる相手をさらに叩かない礼儀。`reraise=True` = 3 回失敗したら元の例外を上へ投げる)
### 3.12 FastAPI — HTTP の受付係(pipeline-api)
FastAPI は「URL+HTTP メソッド」と Python 関数を結びつける枠組みです。`app/main.py` が pipeline-api の全エンドポイント(API の入口)で、管理画面からの「承認して投稿」「失敗チャネルの再試行」「ジョブ即時実行」だけを受け付けます。エラーは `HTTPException` で返します(404 = 見つからない、409 = 今の状態では実行できない)。
```python
    post = posts.get(post_id)
    if post is None:
        raise HTTPException(404, "post not found")
    if post.status in (PostStatus.published, PostStatus.publishing):
        raise HTTPException(409, f"post is {post.status.value}")
```
(出典: `pipeline/app/main.py` の `publish()`)

時間のかかるジョブ実行は `BackgroundTasks` に登録して **202 Accepted(受け付けた。完了はまだ)を即返します**。完了したかは runs(§3.13)を別途見て確認します。
```python
@app.post("/api/jobs/{name}/run", status_code=202)
def run_job(name: str, background: BackgroundTasks) -> dict:
    module = JOB_MODULES.get(name)
    if module is None:
        raise HTTPException(400, f"unknown job {name}")
    background.add_task(_run_job, module)
    return {"accepted": True, "job": name}
```
(出典: `pipeline/app/main.py` の `run_job()`)

もう 1 つ重要な癖があります。投稿エンドポイントは一部チャネルが失敗しても HTTP としては 200 を返し、**本当の結果は応答本文の status に入っています**。「HTTP 200 = 全部成功」ではありません。
```python
    result = publish_post(post_id)
    return {
        "status": result.status.value,
        "channels": {k: v.status.value for k, v in result.channels.items()},
    }
```
(出典: `pipeline/app/main.py` の `publish()` 末尾。詳細は [05-pipeline-api.md](05-pipeline-api.md))
### 3.13 Run のライフサイクル — 全ジョブ共通の骨格
すべてのジョブは同じ骨格です。開始時に runs コレクションへ記録を作り、処理中のエラーは `run.errors` に積み上げ、最後に結果を書き戻します。管理画面のダッシュボードはこの記録を表示しているだけです。
```python
def main() -> None:
    run_id = runs.start("collect")
    run = Run(jobType="collect")
```
(出典: `pipeline/app/jobs/collect.py` の `main()` 冒頭。末尾は `run.ok = not run.errors` と `runs.finish(run_id, run)` で締める。「エラーが 1 件でもあれば ok=False、ただし処理は最後まで走り切る」— §3.6 の隔離方針とセット)
### 3.14 注意 — 本リポジトリの pipeline は同期コード
Python には `async`/`await` という並行処理の書き方がありますが、**本 pipeline は使っていません**(`pipeline/app/` に `async def` は 1 つも無い)。処理は上から順に 1 つずつ実行され、FastAPI のエンドポイントも普通の `def` です。ネット上の FastAPI 解説は async 前提が多いので注意してください。
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```
(出典: `pipeline/pyproject.toml`。この `asyncio_mode` と dev 依存の pytest-asyncio は将来 async を導入した場合への備えで、現行コードでは実質使われない)
## 4. TypeScript・Next.js 編(admin)
### 4.1 Server Components — ページはサーバで実行され、DB を直接読める
Next.js(App Router)のページは既定で**サーバ側で実行**されます。ページを描く関数の中からそのまま Firestore を読め、ブラウザには出来上がった HTML だけが届きます。
```tsx
export default async function SourcesPage() {
  const [t, tc, sources, categories] = await Promise.all([
    getTranslations('sources'),
    getTranslations('common'),
    getSources(),
    getCategories(),
  ]);
```
(出典: `admin/src/app/[locale]/sources/page.tsx`。`getSources()` の中身は `lib/data.ts` の `await db().collection('sources').get()` — 読み取り関数は全部 data.ts に集約。詳細は [07-admin-ui.md](07-admin-ui.md))
### 4.2 Client Components — `'use client'` はわずか 3 ファイル
ボタンの連打防止や文字数カウントのような「ブラウザ上での反応」が必要な部品だけ、先頭に `'use client'` と書いてブラウザ側で動かします。admin では `ActionButton.tsx`・`DraftEditor.tsx`・`LocaleSwitcher.tsx` の 3 ファイルだけです。境界の考え方は「表示するだけならサーバ、操作に反応するならクライアント」。
```tsx
'use client';

import { useState, useTransition } from 'react';
```
(出典: `admin/src/components/ActionButton.tsx` 冒頭。`useState` = 画面上の一時的な状態、`useTransition` = 処理中フラグ)
### 4.3 Server Actions — フォームからサーバ関数を直接呼ぶ
ファイル先頭に `'use server'` と宣言した関数は、ブラウザのフォームから**直接**呼び出せます(API を自作しなくてよい)。書き込み系はすべて `lib/actions.ts` にあります。
```typescript
export async function toggleSource(id: string, enabled: boolean): Promise<void> {
  await db().collection('sources').doc(id).update({ enabled });
  revalidatePath('/', 'layout');
}
```
(出典: `admin/src/lib/actions.ts`。ページ側は `<form action={saveSource}>` のように関数を渡すだけ)

関数をその場に埋め込む「インライン action」もあり、その場合は関数の中に `'use server'` を書きます。
```tsx
<form
  action={async (formData: FormData) => {
    'use server';
    await saveChannelConfig(
      id, cat.slug, cadence, channel,
      formData.get('enabled') === 'on',
```
(出典: `admin/src/app/[locale]/channels/page.tsx`。チャネル設定の保存フォーム)
### 4.4 `action.bind(null, ...)` と `formData.get('x') === 'on'`
フォームに ID などの固定値を渡すには `bind` を使います。`bind(null, 引数...)` は「引数を先に焼き込んだ新しい関数」を作る JavaScript 標準の機能です(`null` は今回使わないお約束の引数)。
```tsx
<form action={toggleSource.bind(null, s.id, !s.enabled)} className="inline">
  <button className="text-xs text-sky-700 underline">
    {s.enabled ? tc('disabled') : tc('enabled')}
```
(出典: `admin/src/app/[locale]/sources/page.tsx`。行ごとに「この ID の有効/無効を反転する関数」を仕込む)

チェックボックスは頻出の落とし穴です。HTML のチェックボックスはチェック時に文字列 `'on'` を送り、未チェック時は**何も送りません**。そのため真偽値への変換は `enabled: formData.get('enabled') === 'on',` と書きます(`admin/src/lib/actions.ts` の `saveCategory()` ほか各所)。
### 4.5 revalidatePath と force-dynamic — 常に最新を見せる
Next.js はページを賢くキャッシュ(使い回し)しますが、管理画面で「保存したのに古い表示のまま」は事故のもとです。対策は 2 つ。書き込み直後の `revalidatePath('/', 'layout')` でキャッシュを破棄する(§4.3 の各 action 末尾に必ずある)ことと、レイアウトで最初からキャッシュを無効化することです。
```tsx
export const dynamic = 'force-dynamic';
```
(出典: `admin/src/app/[locale]/layout.tsx`。全ページを「毎回サーバで作り直す」設定にしている)
### 4.6 npm の prebuild と Docker ビルドコンテキスト
npm には「`build` の直前に `prebuild` が自動で走る」という命名規則があります。
```json
  "scripts": {
    "dev": "next dev",
    "prebuild": "node scripts/sync-constants.mjs",
    "build": "next build",
    "start": "next start",
    "typecheck": "tsc --noEmit"
  },
```
(出典: `admin/package.json`)

なぜコピーが要るのか。Docker のビルドに渡されるのは指定フォルダ(ビルドコンテキスト。admin のビルドでは `admin/` フォルダ)の中身**だけ**で、1 つ上の `../shared` は見えません。そこで prebuild が `shared/constants.json` を `src/lib/` にコピーし、そのコピー(コミット済み)をビルドに使います。
```javascript
if (existsSync(source)) {
  copyFileSync(source, target);
  console.log('synced shared/constants.json');
} else {
  console.log('shared/constants.json not found; using committed copy');
}
```
(出典: `admin/scripts/sync-constants.mjs`。Cloud Build 上では else 側に落ちる。よって **constants.json を変えたら admin の再ビルドが必要**)
### 4.7 `tsc --noEmit` — 型検査のみ(admin にテストは無い)
TypeScript の型の矛盾はコンパイラ `tsc` が検査します。`--noEmit` は「変換結果は出さず、検査だけせよ」の指定です(上の package.json の `typecheck` がそれ)。admin には自動テストが無いため `npm run typecheck` が唯一の機械的検証ですが、型検査は「型の辻褄」しか見ないので、ロジックの誤りは通り抜けます。
## 5. GCP 編
### 5.1 ADC — 鍵ファイル無しの自動認証
Application Default Credentials(ADC)は「今この場所で使える認証情報を自動で探す」仕組みです。Cloud Run 上では実行中のサービスアカウント(§5.2)の身元が、ローカルでは `gcloud auth application-default login` した人間の身元が自動で使われ、コードに鍵ファイルのパスを書く必要がありません。
```typescript
    initializeApp({
      credential: applicationDefault(),
      projectId: process.env.PROJECT_ID ?? 'trend-news-generator',
    });
```
(出典: `admin/src/lib/firestore.ts`。Python 側も同様で、`repo/client.py` の `firestore.Client(...)` は鍵を渡さなければ自動で ADC を使う)
### 5.2 サービスアカウント(SA)と IAM ロール
サービスアカウントは「プログラム用の Google アカウント」です。本システムは 3 つを役割分担させています(pipeline-sa = パイプライン本体、admin-sa = 管理画面、scheduler-sa = 定時起動係)。
```bash
export PIPELINE_SA="pipeline-sa@${PROJECT_ID}.iam.gserviceaccount.com"
export ADMIN_SA="admin-sa@${PROJECT_ID}.iam.gserviceaccount.com"
export SCHEDULER_SA="scheduler-sa@${PROJECT_ID}.iam.gserviceaccount.com"
```
(出典: `infra/env.sh`)

IAM は「誰(メンバー)に何をする権利(ロール)を与えるか」の台帳です。たとえば「admin-sa は pipeline-api を呼んでよい」は、`infra/10-deploy-pipeline.sh` の 1 コマンド `gcloud run services add-iam-policy-binding pipeline-api --member="serviceAccount:${ADMIN_SA}" --role=roles/run.invoker` で表現されます(付与の全体像は [08-infra.md](08-infra.md))。
### 5.3 ID トークンと audience、そして IAP
ID トークンは「私は admin-sa です。宛先は pipeline-api です」と Google が署名した短命の身分証です。宛先(audience)が刻印されているので、盗まれても他のサービスには使えません。管理画面は pipeline-api を呼ぶたびにこれを添えます。
```typescript
  const client = await auth.getIdTokenClient(base);
  const token = await client.idTokenProvider.fetchIdToken(base);
  return fetch(`${base}${path}`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
```
(出典: `admin/src/lib/pipelineClient.ts` の `call()`。`base` = pipeline-api の URL がそのまま audience になる)

一方、**人間**の認証は IAP(Identity-Aware Proxy)が担います。管理画面の前に立つ門番で、Google ログインを通過した人だけを通し、その人のメールアドレスをヘッダでアプリに教えます。
```typescript
export async function iapUserEmail(): Promise<string> {
  const h = await headers();
  const raw = h.get('x-goog-authenticated-user-email') ?? '';
  return raw.includes(':') ? raw.split(':').pop()! : raw;
}
```
(出典: `admin/src/lib/iap.ts`。投稿の承認者記録(approvedBy)に使われる)
### 5.4 Cloud Run の「サービス」と「ジョブ」
Cloud Run には 2 つの動かし方があります。**サービス**は常駐して HTTP を待つもの(pipeline-api と admin)、**ジョブ**は起動→処理→終了の単発実行(collect など 6 つ)です。
```bash
gcloud run deploy pipeline-api \
  --image="$IMAGE" --region="$REGION" \
  --service-account="$PIPELINE_SA" \
  --no-allow-unauthenticated \
```
(出典: `infra/10-deploy-pipeline.sh`。`--no-allow-unauthenticated` = IAM で許可された者以外は HTTP で到達すらできない。pipeline-api にアプリ内の認証コードが無いのはこのため)
```bash
  # --max-retries=0 on publishing jobs prevents double posts on crash
  retries=0
  [[ "$job" == "collect" || "$job" == "seed" ]] && retries=1
  gcloud run jobs deploy "job-${job}" \
```
(出典: 同ファイル。`--max-retries` = 異常終了時に Cloud Run が自動でやり直す回数。**投稿系ジョブの 0 は確定方針** — 投稿直後にクラッシュして自動再実行されると二重投稿しかねないため。再実行しても安全な collect / seed(§6.5)だけ 1 回許している)
### 5.5 Secret Manager — 秘密の金庫とバージョン
API キーやトークンはコードに書かず Secret Manager(金庫)に入れます。中身は版(バージョン)で管理され、デプロイ時に `シークレット名:latest`(最新版)を環境変数として注入します。
```bash
SECRET_ENV="OPENAI_API_KEY=openai-api-key:latest"
SECRET_ENV+=",GEMINI_API_KEY=gemini-api-key:latest"
```
(出典: `infra/10-deploy-pipeline.sh`)

**`:latest` は「コンテナ起動時」に解決される**点が重要です。動いているプロセスには新しい版は届きません。ジョブは毎回新しく起動するので次回実行から新版が効きますが、常駐の pipeline-api は再デプロイまで古い値のままです。Threads のトークン更新ジョブは新版を追加して古い版を無効化します(ローテーション)。
```python
    new_version = client.add_secret_version(
        request={"parent": parent, "payload": {"data": new_token.encode()}}
    )
    for version in client.list_secret_versions(request={"parent": parent}):
        if version.name != new_version.name and version.state.name == "ENABLED":
            client.disable_secret_version(request={"name": version.name})
```
(出典: `pipeline/app/jobs/refresh_threads_token.py` の `_rotate_secret()`。詳細は [06-ops-jobs.md](06-ops-jobs.md))
### 5.6 GCS 署名URL — 非公開ファイルを期限付きで見せる
収集した画像は非公開の GCS バケットに置き、Threads に渡すときだけ「30 分間だけ有効」な署名URLを発行します。通常この署名には秘密鍵ファイルが必要ですが Cloud Run には鍵が無いため、「pipeline-sa が自分自身の名で署名してもらう」鍵レス方式(signBlob 相当)を使います。
```python
    return bucket.blob(path).generate_signed_url(
        version="v4",
        expiration=datetime.timedelta(minutes=minutes),
        credentials=signing_creds,
    )
```
(出典: `pipeline/app/utils/gcs.py` の `signed_url()`。`signing_creds` は同関数内で `impersonated_credentials.Credentials(..., target_principal=sa_email, ...)` として作る。前提として bootstrap で pipeline-sa に**自分自身への** `roles/iam.serviceAccountTokenCreator` を付与済み — `infra/00-bootstrap.sh`。**この IAM を外すと画像添付だけが静かに壊れる**)
### 5.7 Cloud Build / Artifact Registry / cron 式
デプロイの流れは「Cloud Build がクラウド上で Docker イメージを焼き(`gcloud builds submit ../pipeline --tag "$IMAGE"`)、Artifact Registry(イメージ置き場。`asia-northeast1-docker.pkg.dev/...`)に保存し、Cloud Run がそれを取って動かす」です。定時起動は Cloud Scheduler が cron 式で管理します。cron 式は左から「**分 時 日 月 曜日**」の 5 項目で、`*` は「毎」の意味です。
```bash
create_sched sched-collect            "0 6 * * *"  job-collect
create_sched sched-generate-daily     "0 8 * * *"  job-generate-daily
create_sched sched-generate-weekly    "0 7 * * 1"  job-generate-weekly
create_sched sched-generate-monthly   "0 7 1 * *"  job-generate-monthly
create_sched sched-threads-refresh    "0 3 * * 1"  job-refresh-threads-token
```
(出典: `infra/20-schedulers.sh`。`0 6 * * *` = 毎日 6:00、`0 7 * * 1` = 毎週月曜 7:00、`0 7 1 * *` = 毎月 1 日 7:00。すべて `--time-zone="Asia/Tokyo"` なので JST)
## 6. Firestore 編
### 6.1 コレクション/ドキュメント/docID と 2 つの作り方
Firestore は「コレクション(フォルダ)の中にドキュメント(1 件のデータ。中身は辞書)が並ぶ」データベースで、各ドキュメントには一意な名前(docID)が付きます。本システムのコレクションは `items` `posts` `runs` `categories` `sources` `channelConfigs` `promptTemplates` `settings` の 8 つです([../03-data-model.md](../03-data-model.md))。

docID の付け方は 2 通り。実行記録のように毎回新しいものは `add()` で自動採番(§3.2 の `runs.start()`)。「この ID で 1 個だけ存在してほしい」設定類は名前を自分で決めて `document(id).set()` します。seed ジョブは「無ければ作る、あれば触らない」を素朴に実装しています。
```python
def _create_if_absent(collection: str, doc_id: str, data: dict) -> bool:
    ref = db().collection(collection).document(doc_id)
    if ref.get().exists:
        return False
    ref.set(data)
    return True
```
(出典: `pipeline/app/jobs/seed.py`。だから seed は何度実行しても安全 = 冪等)
### 6.2 `create()`(既存なら失敗)vs `set(merge=True)`(部分上書き)
`set()` より厳密な道具が 2 つあります。`create()` は「**同じ docID が既にあれば失敗する**」書き込みで、失敗こそが情報です。収集アイテムの docID は URL のハッシュ(§3.9)なので、`create()` の失敗 = 「この記事は収集済み」。重複排除の門番です。
```python
    try:
        ref.create(item.model_dump(exclude={"id"}))
        return True
    except Exception as exc:  # AlreadyExists
        if type(exc).__name__ == "AlreadyExists":
            return False
        raise
```
(出典: `pipeline/app/repo/items.py` の `create_if_absent()`)

`set(..., merge=True)` は逆に「渡した項目だけ上書きし、他は残す」穏やかな書き込みです。
```python
def update_channel_health(fields: dict) -> None:
    db().collection("settings").document("channelHealth").set(fields, merge=True)
```
(出典: `pipeline/app/repo/configs.py`)
### 6.3 ドット記法の部分更新と ArrayUnion
入れ子の一部だけを更新するにはキーをドットで繋ぎます。`channels.x.text` は「channels の中の x の中の text」。投稿全体を読み直して書き戻すより安全で速い方法で、管理画面の下書き保存(`admin/src/lib/actions.ts` の `saveDraft()`)はこの形で本文だけを更新し、Python 側も `repo/posts.py` の `update_channel()` が `{f"channels.{channel}": state.model_dump()}` を update します。

配列への追記は `ArrayUnion`(重複なしで追加)を使い、同じ ID を二度記録する心配をなくします。
```python
    for item_id in item_ids:
        ref = db().collection(COLLECTION).document(item_id)
        batch.update(ref, {"usedInPostIds": firestore.ArrayUnion([post_id])})
    batch.commit()
```
(出典: `pipeline/app/repo/items.py` の `mark_used()`。`batch` = 複数の更新をまとめて 1 回で送る)
### 6.4 複合インデックス — 無いとクエリが失敗する
Firestore は「複数条件を組み合わせた検索」に、事前定義した索引(複合インデックス)を要求します。タイトル近似重複の判定は 3 条件のクエリです。
```python
        .where(filter=firestore.FieldFilter("categoryId", "==", category_id))
        .where(filter=firestore.FieldFilter("titleNormHash", "==", title_hash))
        .where(filter=firestore.FieldFilter("collectedAt", ">=", cutoff))
```
(出典: `pipeline/app/repo/items.py` の `title_hash_seen_since()`。対応する索引は `infra/firestore.indexes.json` に定義され bootstrap で作成。索引が無いとこのクエリは**遅くなるのではなく実行時エラーで失敗する**。新しい組み合わせのクエリを足したら索引も足す、がセットの作業)
### 6.5 冪等性と冪等キー — 二重実行しても安全にする
**冪等(べきとう)= 同じ操作を何度実行しても結果が 1 回分と同じ**であること。クラッシュややり直しが避けられない自動システムでは最重要の性質で、本システムは「一意な印(冪等キー)を先に決め、印を見たらスキップする」形で実現しています。

- 収集: docID = URL ハッシュ。再収集しても `create()` が失敗するだけ(§6.2)
- 投稿: チャネルに `externalId`(投稿先が発行した ID)が付いていたら投稿済みとしてスキップ
- Threads: 2 段階投稿(§7.4)の途中経過 `containerId` を先に保存し、再開時は続きから

```python
        if state.status in (ChannelStatus.published, ChannelStatus.skipped) or state.externalId:
            continue
```
(出典: `pipeline/app/publishers/base.py` の `publish_post()`)
```python
        state.containerId = threads.create_container(text, image_url)
        posts.update_channel(post_id, "threads", state)  # crash recovery point
    threads.wait_until_ready(state.containerId)
    state.externalId = threads.publish_container(state.containerId)
```
(出典: 同ファイル `_publish_threads()`。コンテナ ID を Firestore に書いてから公開へ進む。この動きの検証テストが `tests/test_publish_orchestration.py`)
## 7. Web・API 編
### 7.1 HTTP ステータスコード — そして「200 でも本文が真実」
HTTP の応答には 3 桁の結果コードが付きます。本リポジトリに登場するのは次の顔ぶれです。「4xx はこちらの問題(直すまで何度やっても同じ)、5xx は相手の問題(待てば直るかも)」という大分類を押さえると、リトライ設計(§3.11)が読めるようになります。

| コード | 意味 | 登場箇所 |
|---|---|---|
| 200 | 成功。ただし投稿 API は本文の status が真実(§3.12) | 各所 |
| 202 | 受け付けた(完了は別途確認) | ジョブ即時実行(§3.12) |
| 304 | 変わっていない(本文なし) | RSS の条件付き GET(§7.2) |
| 404 / 409 | 無い / 今の状態ではできない | pipeline-api(§3.12) |
| 429 | 呼びすぎ。待って再試行してよい | リトライ判定(§3.11) |
| 5xx | 相手側の障害。再試行してよい | リトライ判定(§3.11) |
### 7.2 HTTP 条件付き GET — ETag / If-Modified-Since / 304
RSS を毎回丸ごとダウンロードするのは無駄です。前回の応答に付いてきた版数タグ(ETag)や更新時刻を次のリクエストに添えると、変化が無ければサーバは本文なしの 304 だけを返します。
```python
        headers = {}
        if source.etag:
            headers["If-None-Match"] = source.etag
        if source.lastModified:
            headers["If-Modified-Since"] = source.lastModified

        resp = self._client.get(source.url, headers=headers)
        if resp.status_code == 304:
            log.info("rss not modified", extra={"fields": {"source": source.url}})
            return []
```
(出典: `pipeline/app/collectors/rss.py` の `collect()`。ETag 等は sources ドキュメントに保存して次回へ持ち越す)
### 7.3 OAuth 1.0a(毎回署名)と OAuth2/OIDC(トークン)の違い
外部サービスへの認可には大きく 2 世代あります。**OAuth 1.0a**(X が今も要求)はリクエスト 1 件ごとに秘密鍵で署名を計算して添える方式で、本リポジトリは自前実装しています。
```python
    digest = hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha1).digest()
    oauth_params["oauth_signature"] = base64.b64encode(digest).decode()
```
(出典: `pipeline/app/publishers/x.py` の `oauth1_header()`。**署名ロジックを触ったら `tests/test_oauth1.py` を必ず通すこと**)

**OAuth2**(Threads / Notion)は事前発行のトークン(合言葉)を毎回そのまま添える方式です。`publishers/threads.py` は全リクエストに `params: dict = {"access_token": settings.threads_access_token, "text": text}` のようにトークンを付けるだけ。署名計算は不要な代わりにトークンに寿命があり、更新ジョブが要ります(§5.5)。

OIDC は OAuth2 の上に「身元証明」を載せた規格で、§5.3 の ID トークンがそれです。まとめると「X = 毎回署名、Threads / Notion = トークン持参、サービス間 = ID トークン」。
### 7.4 Threads の 2 段階投稿(コンテナ作成→公開)とポーリング
Threads の API は 1 回では投稿できません。まず「コンテナ」という下書き実体を作り、準備完了(FINISHED)になるのを**ポーリング**(定期的な問い合わせ)で待ってから公開 API を呼びます。
```python
            status = payload.get("status")
            if status == "FINISHED":
                return
            if status == "ERROR":
                raise PermanentPublishError(
                    f"threads container error: {payload.get('error_message')}"
                )
            time.sleep(POLL_INTERVAL_S)
```
(出典: `pipeline/app/publishers/threads.py` の `wait_until_ready()`。2 秒間隔で最大 15 回。ERROR は再試行無意味なので専用例外で即諦める。2 段階の間のクラッシュに備えてコンテナ ID を先に保存するのが §6.5 の冪等設計。詳細は [04-publish.md](04-publish.md))
### 7.5 og:image — ページの「代表画像」
多くの記事ページは HTML の頭に「SNS でシェアされたとき表示する代表画像」を宣言しています。それが `og:image` メタタグです。収集の仕上げ(enrich)でこれを拾い、GCS に保存して投稿の添付画像に使います。
```python
        soup = BeautifulSoup(resp.text, "html.parser")
        og = soup.find("meta", property="og:image")
        image_url = (og.get("content") or "").strip() if og else ""
```
(出典: `pipeline/app/collectors/enrich.py` の `fetch_page()`。BeautifulSoup = HTML を解析して要素を探すライブラリ)
### 7.6 グラウンディング — 検索に基づく生成
LLM に自由作文させると事実でないことを書きます。グラウンディングは「まず Google 検索を実行し、その結果に**基づいて**答えさせる」機能で、収集ソースの 1 種(gemini_grounded)として使っています。地に足(ground)を着けさせる、という意味です。
```python
        response = self._client.models.generate_content(
            model=get_settings().gemini_model,
            contents=_PROMPT.format(query=source.query),
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
                temperature=0.2,
            ),
        )
```
(出典: `pipeline/app/collectors/gemini_grounded.py` の `collect()`。`tools=[GoogleSearch()]` が指定の本体。根拠 URL は groundingCitations として収集アイテムに残る)
### 7.7 X の加重文字数 — 全角 2・URL 一律 23
X の 280 字制限は単純な文字数ではありません。日本語などの全角文字は 1 字を 2 と数え、URL は長さに関係なく一律 23 と数えます(投稿時に短縮 URL へ置き換わるため。`_TCO_WEIGHT = 23`)。つまり日本語投稿の実質上限は約 140 字です。
```python
def _char_weight(ch: str) -> int:
    if unicodedata.east_asian_width(ch) in ("F", "W", "A"):
        return 2
    return 1
```
(出典: `pipeline/app/publishers/renderer.py`。`east_asian_width` が全角/半角の判定。長すぎた場合の分割投稿 `split_for_x_thread()` も同ファイル。管理画面のカウンタは同規則の TS 移植 `admin/src/lib/textLimits.ts` で、最終検証は投稿時に pipeline 側が行う)
## 8. テスト編
### 8.1 pytest と assert — 「こうなるはず」を機械に確認させる
pytest は `test_` で始まる関数を全部実行し、`assert 条件` が偽なら失敗として報告します。テストは「仕様の実行できる見本」なので、**挙動を知りたいときはテストから読むのが近道**です。
```python
def test_strips_tracking_params():
    assert (
        canonicalize_url("https://example.com/a?utm_source=x&utm_medium=y&id=1")
        == "https://example.com/a?id=1"
    )
```
(出典: `pipeline/tests/test_normalize.py`。「URL 正規化は utm_ を落とすが id は残す」という仕様がひと目で分かる)
### 8.2 fixture と monkeypatch — 本物を偽物にすり替えて試す
テスト中に本物の Firestore や X に触るわけにはいきません。**monkeypatch** は「テストの間だけ指定した関数を偽物に差し替える」道具、**fixture** は「複数のテストで使い回す準備一式」です。偽物(モック)は呼ばれた記録を残すので、呼び出しの順序まで検証できます。
```python
@pytest.fixture
def store(monkeypatch):
    """In-memory stand-ins for Firestore and the channel adapters."""
    state = {"post": None, "statuses": [], "channel_updates": [], "calls": []}

    monkeypatch.setattr(base.posts, "get", lambda _id: state["post"])
```
(出典: `pipeline/tests/test_publish_orchestration.py`。`lambda` = その場で作る小さな関数)
```python
    result = base.publish_post("p1")
    assert store["calls"] == ["notion", "x", "th-create", "th-publish"]
```
(出典: 同ファイル。「公開順は notion → x → threads」という確定仕様がテストで固定されている)
### 8.3 テストベクタ — 既知の入力と正解の組
暗号や署名のように「1 ビット違うだけで全く使えない」処理は、公式文書が公開する**既知の入力と正解の組(テストベクタ)**で照合します。X の OAuth 1.0a 署名は X 公式ドキュメントの例と突き合わせています。
```python
        nonce="kYjzVBB8Y0ZFabxSWbWovY3uYSQ2pTgmZeNu2VS4cg",
        timestamp="1318622958",
    )
    assert _signature(header) == "hCtSmYh+iHYCEqBWrE7C7hYmtUk="
```
(出典: `pipeline/tests/test_oauth1.py` の `test_known_signature_vector()`。普段は毎回ランダムな nonce と現在時刻を固定値にして、結果を再現可能にしている)
### 8.4 respx — 用意されているが現行テストでは未使用
respx は HTTP 通信(httpx)を偽装するモックライブラリです。`pipeline/pyproject.toml` の dev 依存に `"respx>=0.21",` として入っていますが、**現行のテストコードでは使われていません**(現状は §8.2 の monkeypatch 方式で足りている)。将来「HTTP リクエストの中身そのもの」を検証するテストを書くときの備えです。テスト全体は [09-tests.md](09-tests.md) 参照。
## 9. 読み方の実演 — 収集ジョブを最初から辿る
ここまでの知識で収集ジョブを実際に読んでみます。[02-collect.md](02-collect.md) を隣に開き、次の手順でファイルを行き来してください(エディタで関数名を Ctrl+クリックすると定義に飛べます)。

1. **起動を確認する。** `infra/10-deploy-pipeline.sh` で job-collect は `--command=python --args=-m,app.jobs.collect`(§5.4)。つまり入口は `pipeline/app/jobs/collect.py` 末尾の `if __name__ == "__main__": main()`(§2.2)。
2. **`main()` の骨格を掴む。** 冒頭の `run_id = runs.start("collect")` が実行記録の作成(§3.13)。飛び先は `repo/runs.py` — Firestore の runs に `add()` している(§6.1)。
3. **道具の準備を読む。** `collectors = {...}` が種類→コレクタの対応表(§3.5)、続く `httpx.Client(...)` は使い回す HTTP クライアント。
4. **二重ループを読む。** `for category in configs.enabled_categories():` と `for source in configs.enabled_sources(category.slug):`。飛び先は `repo/configs.py` の「enabled == True」クエリ。**管理画面でソースを無効にすれば次回から収集されない**という運用がここに繋がる。
5. **収集 1 回分を読む。** `collector.collect(source)` の実体は type 次第。rss なら `collectors/rss.py` — 条件付き GET(§7.2)して `parse_feed()` で RawItem のリストへ。gemini_grounded なら `gemini_grounded.py`(§7.6)。この呼び出しは try/except で囲まれ、失敗は `run.errors` に積んで `continue`(§3.6)。
6. **保存 `_persist()` を読む。** 同じ collect.py 内。`canonicalize_url` → `item_doc_id` → `title_norm_hash`(`normalize.py`、§3.9)。`items.title_hash_seen_since(...)` で 7 日窓の近似重複を除外(§6.4 の複合インデックスが必要)。画像が無ければ `enrich.fetch_page()` で og:image を拾い(§7.5)、`gcs.upload_bytes()` で GCS へ。最後に `items.create_if_absent(item)` — `create()` の成否で新規/重複を数える(§6.2)。
7. **締めを読む。** ループを抜けたら `run.ok = not run.errors` として `runs.finish(run_id, run)`(§3.13)。
8. **結果を確かめる。** 管理画面のダッシュボード(= runs コレクションの表示)で collected / deduped / errors を確認。§3.12 の「202 で受け付け、完了は runs で確認」の実践がこれ。

この「入口 → 骨格 → ループ → 1 件分の処理 → 締め」という読み順は、generate 系([03-generate.md](03-generate.md))や publish([04-publish.md](04-publish.md))でもそのまま通用します。
## 10. 用語集

| 用語 | よみ | 一言定義 | 詳しく学ぶ場所 |
|---|---|---|---|
| エントリポイント | えんとりぽいんと | プログラムの実行が始まる場所 | §2.2 |
| ジョブ | じょぶ | 起動→処理→終了する単発プログラム(Cloud Run Jobs) | §5.4、[06-ops-jobs.md](06-ops-jobs.md) |
| チャネル | ちゃねる | 投稿先(x / threads / notion) | [../03-data-model.md](../03-data-model.md) |
| 投稿(post) | とうこう | 生成された 1 本のコンテンツと各チャネルの状態の記録 | [../03-data-model.md](../03-data-model.md) |
| 収集アイテム(item) | しゅうしゅうあいてむ | 収集した記事 1 件(items の 1 ドキュメント) | [02-collect.md](02-collect.md) |
| カデンス(cadence) | かでんす | 投稿頻度の区分(daily / weekly / monthly) | §3.4 |
| 管理画面(admin) | かんりがめん | Next.js 製の運用 UI | §4、[07-admin-ui.md](07-admin-ui.md) |
| デコレータ | でこれーた | 関数に機能を後付けする @ 記法 | §3.1 |
| シングルトン | しんぐるとん | 全体で 1 個だけ作って使い回すオブジェクト(@lru_cache) | §3.1 |
| pydantic / BaseModel | ぱいだんてぃっく | 型検証付きデータ入れ物。model_dump() で辞書化 | §3.2 |
| pydantic-settings / 環境変数 | ぱいだんてぃっくせってぃんぐす | OS が渡す「名前=値」(環境変数)を設定クラスへ自動対応させる仕組み | §3.3 |
| Enum(列挙型) | いーなむ | 決まった選択肢しか取れない型 | §3.4 |
| Protocol | ぷろとこる | 継承なしの「同じ形なら OK」(構造的型付け) | §3.5 |
| 例外 / ベストエフォート | れいがい | エラーを上位へ伝える仕組み(try/except で受ける)/ 失敗しても空値で続行する方針 | §3.6 |
| 辞書(dict)/ **kwargs | じしょ | 「キー: 値」の入れ物(`{**a, **b}` は後勝ち)/ 名前付き引数を辞書で受ける記法 | §3.7 |
| f-string / プレースホルダ | えふすとりんぐ | 文字列穴埋め / `{items}` のような後から埋める穴 | §3.8 |
| ハッシュ(SHA-256) | はっしゅ | データから作る固定長の指紋 | §3.9 |
| 正規化 / 正規URL / 正規表現 | せいきか | 表記ゆれを揃える処理 / 追跡パラメータ等を除いた URL の基準形 / 文字パターンの記法 | §3.9 |
| UTC / JST | ゆーてぃーしー | 世界標準時 / 日本時間。保存は UTC、予定は JST | §3.10 |
| tenacity / 指数バックオフ | てなしてぃ | リトライ制御ライブラリ / 待ち時間を倍々に延ばす再試行 | §3.11 |
| FastAPI / エンドポイント | ふぁすとえーぴーあい | URL と関数を結びつける枠組み / API の入口 | §3.12、[05-pipeline-api.md](05-pipeline-api.md) |
| 202 Accepted | にーまるにー | 「受け付けた。完了は別途確認」の HTTP 応答 | §3.12 |
| Run | らん | ジョブ 1 回分の実行記録(runs コレクション) | §3.13 |
| 同期/非同期 | どうき/ひどうき | 順に 1 つずつ実行 / 並行実行。本 pipeline は同期 | §3.14 |
| Server / Client Component | さーばー/くらいあんとこんぽーねんと | サーバ側で実行され DB を直接読める部品 / ブラウザで動く部品(`'use client'`) | §4.1、§4.2 |
| Server Action | さーばーあくしょん | フォームから直接呼べるサーバ関数(`'use server'`) | §4.3 |
| revalidatePath / force-dynamic | りばりでーとぱす | キャッシュ破棄 / ページを毎回作り直す設定 | §4.5 |
| prebuild / ビルドコンテキスト | ぷりびるど | `npm run build` 直前に自動実行されるスクリプト / Docker ビルドに渡されるフォルダの範囲 | §4.6 |
| tsc --noEmit | てぃーえすしー | TypeScript の型検査のみ実行(admin にテストは無い) | §4.7 |
| ADC | えーでぃーしー | 鍵ファイル無しの GCP 自動認証 | §5.1 |
| サービスアカウント(SA)/ IAM | さーびすあかうんと | プログラム用の Google アカウント / 「誰に何を許可するか」の台帳 | §5.2、[08-infra.md](08-infra.md) |
| ID トークン / audience | あいでぃーとーくん | 宛先刻印付きの身元証明 / その宛先 | §5.3 |
| IAP | あいえーぴー | アプリの前に立つ Google ログインの門番 | §5.3 |
| Cloud Run / --max-retries | くらうどらん | コンテナ実行基盤(常駐サービスと単発ジョブ)/ 異常終了時の自動再実行回数(投稿系は 0 固定) | §5.4 |
| Secret Manager | しーくれっとまねーじゃー | 秘密情報の金庫。`:latest` は起動時に解決 | §5.5 |
| ローテーション | ろーてーしょん | 鍵・トークンの定期交換 | §5.5、[06-ops-jobs.md](06-ops-jobs.md) |
| 署名URL | しょめいゆーあーるえる | 非公開ファイルを期限付きで見せる URL(鍵レス signBlob) | §5.6 |
| Cloud Build / Artifact Registry | くらうどびるど | イメージをクラウドで焼く / 焼いたイメージの置き場 | §5.7 |
| cron 式 | くろんしき | 「分 時 日 月 曜日」で表す実行スケジュール | §5.7 |
| コレクション / docID | これくしょん | Firestore のフォルダ / ドキュメントの一意な名前 | §6.1 |
| ArrayUnion | あれいゆにおん | 配列へ重複なしで追記する更新 | §6.3 |
| 複合インデックス | ふくごういんでっくす | 複数条件クエリに必須の索引(無いと失敗) | §6.4 |
| 冪等 / 冪等キー | べきとう | 何度実行しても結果が 1 回分と同じ / それを保証する一意な印(URL ハッシュ・externalId・containerId) | §6.5 |
| ETag / 条件付き GET | いーたぐ | 版数タグを添えて「変化なしなら 304」で済ます取得 | §7.2 |
| OAuth 1.0a / OAuth2 / OIDC | おーおーす | リクエスト毎に署名する旧方式(X)/ トークン持参の現行方式 / その上の身元証明規格 | §7.3、§5.3 |
| コンテナ(Threads) | こんてな | Threads 投稿の下書き実体(作成→公開の 2 段階) | §7.4 |
| ポーリング | ぽーりんぐ | 完了するまで定期的に問い合わせて待つこと | §7.4 |
| スロットル | すろっとる | 呼び出し頻度をわざと抑えること(Notion は約 3 件/秒) | [04-publish.md](04-publish.md) |
| og:image | おーじーいめーじ | ページの代表画像を示すメタタグ | §7.5 |
| グラウンディング | ぐらうんでぃんぐ | 検索結果に基づいて LLM に生成させる仕組み | §7.6 |
| 加重文字数 | かじゅうもじすう | X の字数勘定(全角 2・URL 一律 23) | §7.7 |
| ティーザー | てぃーざー | 長文記事へ誘導する短い予告文(週次/月次の X / Threads 投稿) | [03-generate.md](03-generate.md) |
| pytest / assert | ぱいてすと | テスト実行ツール / 「こうなるはず」の表明 | §8.1 |
| fixture / monkeypatch / モック | ふぃくすちゃ | テストの共通準備 / 本物を一時的に差し替える道具 / 本物の代役をする偽オブジェクト | §8.2 |
| テストベクタ | てすとべくた | 既知の入力と正解の組による照合 | §8.3 |
| respx | れすぷえっくす | httpx 用 HTTP モック(dev 依存にあるが現行未使用) | §8.4 |
