# テストと文書検証 詳細設計

> 対象コード時点: コミット 6cdcccd + 未コミット変更 / 最終更新: 2026-07-15(M0-a: conftest.py・test_observability.py 追記 / Research Chat: `pipeline/tests/chat/` 9ファイル・84件を追加)

この文書は2部構成です。第1部は pipeline の自動テスト(コードが正しく動くことを機械的に確かめる仕組み)の読み方と動かし方、第2部は本 tech-report 文書群を更新したときに「文書とコードが一致しているか」を確かめる恒久手順です。
パイプライン共通の前提知識は [01-pipeline-foundation.md](01-pipeline-foundation.md) を、コードの読み進め方は [00-code-reading-primer.md](00-code-reading-primer.md) を先に参照してください。

## 第1部: テストの構成

### 1. この文書で分かること

- pipeline のテスト(`pipeline/tests/` 直下11ファイル + `tests/research/` 11ファイル + `tests/chat/` 9ファイル、計256件・2026-07-15時点)をどう実行し、結果をどう読むか
- 各テストファイルが「何を固定しているか」と、どの機能文書に対応するか
- テストが無い領域はどこで、実運用では何がそれを補っているか

### 2. テストの実行方法

テストは `pipeline/` 配下にだけ存在します(admin にはありません。6章参照)。ネットワーク接続・GCP の認証情報・各サービスの API キーは一切不要です — 外部と通信する部分はすべて偽物に差し替えられるか、そもそも通信しない純粋な関数だけを対象にしているためです。

```bash
cd pipeline
```
リポジトリ内の `pipeline` ディレクトリへ移動します。以降のコマンドはここで実行します。

```bash
uv venv && uv pip install -e ".[dev]"
```
初回のみ。`uv venv` で `.venv` を作り(ローカルは素の pip/python ではなく uv で仮想環境に隔離する)、pipeline 本体とテスト用の追加ライブラリ(`pyproject.toml` の `[project.optional-dependencies]` にある dev グループ: pytest / pytest-asyncio / respx)をインストールします。`-e` は「編集可能モード」で、コードを直したら再インストールなしで反映されます。

```bash
uv run pytest
```
全テストを実行します。設定(`pyproject.toml` の `[tool.pytest.ini_options]`)により `tests/` ディレクトリが自動で対象になります。

```bash
uv run pytest tests/test_oauth1.py
```
1ファイルだけ実行する例。署名ロジックを触ったときは最低限これを回します(4章参照)。

```bash
uv run pytest -v -k "notion"
```
`-v` はテスト名を1行ずつ表示、`-k` は名前に指定文字列を含むテストだけを選んで実行します。

**出力の読み方**: 成功したテストは `.`(ドット)1個で表示され、最後に要約が出ます。2026-07-15 時点のコードでは全件成功し、次のようになります(所要 6〜7 秒)。

```text
256 passed, 2 warnings in 7.55s
```

- `256 passed` — 256件すべて成功。これが正常です(件数は今後増減し得ます。5章末尾の表が最新の内訳)
- `F` と `FAILED tests/test_xxx.py::test_yyy` — そのテストの期待値と実際の値が食い違った。直前に「期待値 / 実際の値」の比較が表示されます
- `E` / `ERROR` / `Interrupted: N error during collection` — テスト実行以前の問題(import の失敗など)。コード自体が壊れている合図で、失敗より深刻です
- `warning` は利用ライブラリ内部の非推奨警告などで、`passed` であれば気にする必要はありません

なお本リポジトリには CI(コードを push するたびに自動でテストを回す仕組み)がありません。実行は常に手動です。コード変更後・デプロイ前に必ず回してください。

### 3. テスト基盤の解説

**pytest** — Python の標準的なテスト実行ツール。`tests/` 内の `test_` で始まる関数を全部見つけて実行し、`assert 式`(「これは真のはず」という宣言)が偽になったら失敗として報告します。

**pytest-asyncio と `asyncio_mode = "auto"`** — 非同期関数(`async def` で書かれた、待ち時間中に他の処理を進められる関数)のテストをそのまま書けるようにする追加設定です(`pipeline/pyproject.toml` で有効化)。ただし現在の 9 ファイルはすべて同期関数のテストで、この設定の出番はまだありません。将来 async のコードにテストを足しても追加設定なしで動く、という備えです。

**respx** — HTTP クライアント httpx の通信を横取りし、実際のサーバーに届く前に偽の応答を返すライブラリです。これがあるため、X や Notion に本当に投稿することなく HTTP 呼び出しコードを検証できます。**ただし現在のテストコードに respx の import はまだ登場しません**。dev 依存として導入済みで、プロジェクト方針(CLAUDE.md)として「HTTP をモックするなら respx」と決まっているものの、現行のテストは HTTP に到達する一歩手前の層(パース関数・署名関数・整形関数)と、HTTP 呼び出し部を丸ごと差し替えたオーケストレーション層を対象にしているためです。新たに HTTP 層そのもののテストを書くときに使います(12章に例)。

**monkeypatch(モンキーパッチ)** — pytest 標準の部品で、テストの間だけオブジェクトの属性を別物に差し替え、テスト終了時に自動で元へ戻します。本スイートの外部依存の切り離しはすべてこれで行われています。実例:

- `pipeline/tests/test_publish_orchestration.py` の `store` fixture — Firestore アクセス層(`base.posts` の `get` / `set_status` / `update_channel`)と3チャネルのアダプタ(`base.notion.publish` / `base.x.publish` / `base.threads` の3関数)を、呼び出し履歴をメモリ上のリストに記録するだけの偽物に差し替え
- `pipeline/tests/test_academic_sources.py` の `test_ieee_collector_skips_without_key()` — 設定オブジェクトの `ieee_api_key` を空文字に差し替えて「キー未設定」の状況を再現
- `pipeline/tests/test_api.py` の `test_run_job_accepted()` — `monkeypatch.setattr` で `_trigger_job`(Cloud Run Job を起動する関数)を、呼ばれた API 名を記録するだけの偽物に差し替え(実ジョブは起動しない)

この差し替えが成立するのは、対象コード(例: `pipeline/app/publishers/base.py` の `publish_post()`)が依存先をモジュール属性経由で参照しているからです。一種の依存注入(依存部品を外から入れ替えられる作り)として機能しています。

**`tests/conftest.py`(全テスト共通の自動 fixture)** — `conftest.py` は pytest が自動で読み込む特別なファイルで、置いたディレクトリ配下の全テストに fixture を配れます。ここには `_no_langsmith_env` が1つだけあり、`autouse=True`(テスト側が何も書かなくても必ず適用)で `LANGSMITH_*` 系の環境変数を空/false に**上書き**します。**なぜ「削除」ではなく「空で上書き」か**: `pipeline/app/config.py` の `Settings` は環境変数だけでなく `pipeline/.env` ファイルも読むため、変数を消しても手元の `.env` に書いたキーが復活してしまいます。pydantic-settings も LangSmith SDK も「環境変数 > `.env`」の優先順位なので、空で上書きすれば両方の層を確実に打ち消せます。これが無いと、トレーシングを有効にしている開発者の手元でだけ、テストが実キーで LangSmith に本物の通信を行い(respx の厳格な検証も壊れる)、テストのプロンプトが SaaS に漏れます。

**fixture(フィクスチャ)** — pytest 用語で「テストの前準備を関数化したもの」。`@pytest.fixture` を付けた関数をテストが引数として受け取ると、準備済みの部品が渡されます。また `tests/fixtures/` ディレクトリには入力データのサンプルが置かれています:

- `pipeline/tests/fixtures/sample_feed.xml` — RSS 2.0 形式のフィード。記事3件(うち1件はタイトル空=捨てられるべきデータ、1件は `media:content` の画像付き、URL に `utm_source` 付き)
- `pipeline/tests/fixtures/arxiv_atom.xml` — arXiv が返す Atom 形式のフィード。論文2件

**FastAPI TestClient** — `pipeline/tests/test_api.py` で使用。サーバーを起動せずに、HTTP リクエストをアプリケーションへ直接流し込んで応答を検査できる仕組みです。

### 4. テストファイル別リファレンス

#### test_normalize.py(8件)— URL・タイトル正規化

対象: `pipeline/app/normalize.py` の `canonicalize_url()` / `item_doc_id()` / `normalize_title()` / `title_norm_hash()`。

| テスト関数 | 固定している振る舞い |
|---|---|
| `test_strips_tracking_params()` | `utm_*` 系の追跡パラメーターは除去し、それ以外(`id=1`)は残す |
| `test_strips_www_fragment_and_trailing_slash()` | `www.`・ホスト名の大文字・`#fragment`・末尾スラッシュを除去 |
| `test_sorts_query_params()` | クエリパラメーターの順序が違っても同じ URL に揃う |
| `test_root_path_preserved()` | ルート `/` だけは削らない |
| `test_doc_id_stable_and_short()` | 同じ URL からは常に同じ 32 文字の ID が得られる |
| `test_title_normalization_order_and_case_insensitive()` | 語順・大文字小文字が違っても同じタイトルとみなす |
| `test_title_hash_differs_for_different_stories()` | 別のニュースはちゃんと別ハッシュになる(潰しすぎない) |
| `test_cjk_titles()` | 日本語タイトルでも記号(「!」)の有無を無視できる |

特筆: `items` のドキュメント ID = 正規化 URL のハッシュという重複排除設計([02-collect.md](02-collect.md)・[../03-data-model.md](../03-data-model.md))の土台。ここが崩れると同じ記事が二重に貯まります。

#### test_rss.py(2件)— RSS パース

対象: `pipeline/app/collectors/rss.py` の `parse_feed()`。入力は `sample_feed.xml`。

| テスト関数 | 固定している振る舞い |
|---|---|
| `test_parse_feed_extracts_items()` | 3件中2件を抽出(タイトル空は捨てる)。タイトル・URL・日付・要約・`media:content` からの画像 URL が取れる |
| `test_parse_feed_without_image()` | 画像の無い記事は `imageUrl` が空文字 |

特筆: パース段階の URL は `utm_source` 付きのまま。追跡パラメーター除去(正規化)は保存時に行う、という役割分担がここから読み取れます。

#### test_academic_sources.py(3件)— arXiv / IEEE Xplore

対象: `parse_feed()`(arXiv Atom)と `pipeline/app/collectors/ieee_xplore.py` の `parse_articles()` / `IeeeXploreCollector`。

| テスト関数 | 固定している振る舞い |
|---|---|
| `test_arxiv_atom_parses_through_feed_collector()` | arXiv の Atom 形式が専用コレクター無しで rss コレクターのまま読める(設計判断の証明) |
| `test_ieee_parse_articles()` | IEEE API の応答形式を解釈。URL の無い論文は捨てる。`"1 June 2026"` 形式の日付を解釈 |
| `test_ieee_collector_skips_without_key()` | API キー未設定なら `collect()` は空リストを返す(例外で収集ジョブ全体を止めない) |

#### test_oauth1.py(3件)— X の OAuth 1.0a 署名 【最重要級】

対象: `pipeline/app/publishers/x.py` の `oauth1_header()`。X への投稿に必須の電子署名(リクエストが本人のものである証明)を自前実装しているため、その正しさをここで担保します。

| テスト関数 | 固定している振る舞い |
|---|---|
| `test_known_signature_vector()` | **X(Twitter)公式ドキュメント「Creating a signature」の既知テストベクタとの照合**。公式が例示する資格情報・nonce・timestamp を入れたとき、署名が公式記載の期待値 `hCtSmYh+iHYCEqBWrE7C7hYmtUk=` に一致すること |
| `test_header_shape()` | ヘッダーが `OAuth ` で始まり、`oauth_consumer_key` など必須6項目を含む |
| `test_json_body_not_signed_but_query_is()` | JSON ボディは署名対象外(同条件なら同署名)、クエリパラメーターは署名対象(署名が変わる) |

特筆: テストベクタとは「入力と正解の組」を公式が公開したものです。署名は1文字ずれても X 側で認証エラーになるため、`oauth1_header()` を変更したら必ずこのファイルを通すこと(CLAUDE.md の運用規則と同一)。**期待値側を書き換えてテストを通すのは厳禁**です — 期待値の出所は X 公式であり、こちらの都合では変わりません。

#### test_renderer.py(10件)— 文字数制限と本文整形

対象: `pipeline/app/publishers/renderer.py` の `x_weighted_length()` / `fits_x()` / `fits_threads()` / `split_for_x_thread()` / `strip_urls()` / `append_url()`。

| テスト関数 | 固定している振る舞い |
|---|---|
| `test_ascii_weight_is_one()` | 英数字は1文字=重み1 |
| `test_cjk_weight_is_two()` | 日本語・韓国語は1文字=重み2(X の数え方) |
| `test_url_counts_as_23()` | URL は長さによらず一律 23 と数える(X の短縮仕様) |
| `test_fits_x_boundary()` | 上限 280 ちょうどは可・281 は不可(日本語なら 140/141) |
| `test_fits_threads()` | Threads は 500 ちょうど可・501 不可 |
| `test_split_short_text_is_single_part()` | 短文は分割しない |
| `test_split_long_text_numbered_and_within_limit()` | 長文分割の各パートが上限内で、末尾に `(i/n)` の連番が付く |
| `test_split_cjk_long_text()` | 日本語の長文でも各パートが上限内 |
| `test_strip_urls()` | 本文から URL を除去できる |
| `test_append_url_trims_to_fit()` | ほぼ満杯の本文に URL を足しても、本文を削って上限内に収める |

#### test_notion_blocks.py(6件)— Markdown → Notion ブロック変換

対象: `pipeline/app/publishers/notion.py` の `markdown_to_blocks()`。Notion API は Markdown を直接受け付けないため、独自の「ブロック」形式へ変換する必要があります。

| テスト関数 | 固定している振る舞い |
|---|---|
| `test_headings_and_paragraphs()` | `#`/`##`/`###` と段落が heading_1/2/3・paragraph ブロックになる |
| `test_lists_quotes_dividers()` | 箇条書き・番号付きリスト・引用・区切り線の変換 |
| `test_code_fence()` | コードブロックが言語名(python 等)付きで変換される |
| `test_inline_bold_and_link()` | 文中の **太字** とリンクが Notion の装飾情報として保持される |
| `test_long_text_split_at_2000()` | 4500 文字が 2000+2000+500 に分割される(Notion API の1要素 2000 字制限対応) |
| `test_empty_lines_skipped()` | 空行だけの入力は空リスト |

#### test_publish_orchestration.py(8件)— 公開の順序・冪等性・クラッシュ復旧 【最重要級】

対象: `pipeline/app/publishers/base.py` の `publish_post()`。3章で述べた `store` fixture が Firestore と3チャネルすべてを偽物にし、「どの偽物が・どの順で呼ばれたか」を検証します。冪等性(何度実行しても結果が同じで、二重投稿にならない性質)の仕様書に相当します。

| テスト関数 | 固定している振る舞い |
|---|---|
| `test_publishes_all_channels_notion_first()` | 公開順が notion → x → threads(作成→公開)で固定。長文ティーザーが Notion の公開 URL を必要とするため |
| `test_skips_channels_with_external_id()` | `externalId`(投稿済みの証拠)があるチャネルには再投稿しない |
| `test_resumes_persisted_threads_container()` | Threads の `containerId` が保存済みなら、作成をスキップして公開だけ再開(クラッシュ後の途中再開) |
| `test_partial_failure_status()` | X だけ失敗 → 投稿全体は `partially_published`、当該チャネルは `failed` + エラー文言保存 |
| `test_all_failed_status()` | 全チャネル失敗 → `failed` |
| `test_only_channel_retry()` | `only_channel="x"` 指定時は他チャネルに触れない(管理画面のチャネル別リトライ) |
| `test_daily_x_gets_no_url()` | 日次投稿の X 本文には Notion URL を付けない |
| `test_weekly_x_teaser_gets_notion_url()` | 週次ティーザーの X 本文には Notion URL が追記される |

特筆: 投稿系ジョブが `--max-retries=0`(CLAUDE.md 参照)でも安全に手動リトライできる根拠が、このファイルの externalId / containerId の扱いです。ここを緩めると実サービスで二重投稿が起きます。

#### test_api.py(10件)— pipeline-api のエンドポイント

対象: `pipeline/app/main.py`。TestClient 経由で HTTP の入口だけを検証し、中身(`publish_post()` や Cloud Run Job の起動 `_trigger_job()`)は monkeypatch で偽物にしています。

| テスト関数 | 固定している振る舞い |
|---|---|
| `test_healthz()` | `/healthz` が `{"ok": true}` を返す(死活監視用) |
| `test_publish_404()` | 存在しない投稿の公開要求 → 404 |
| `test_publish_conflict_when_already_published()` | 公開済み・公開中の投稿 → 409(二重公開の入口ブロック) |
| `test_publish_flow()` | 正常系: 200 が返り、承認者(`approvedBy`)が記録される |
| `test_retry_channel_requires_failed_state()` | `failed` 状態以外のチャネルはリトライ不可 → 409 |
| `test_retry_unknown_channel()` | 未知のチャネル名 → 400 |
| `test_run_unknown_job()` | 未知のジョブ名 → 400 |
| `test_run_job_accepted()` | 既知のジョブ → 202、応答の `job` が Cloud Run Job 名、`_trigger_job()` に API 名が渡る |
| `test_run_job_trigger_failure_is_502()` | ジョブ起動が例外を投げたら → 502(detail にジョブ名) |
| `test_cloud_run_job_name_mapping()` | 名前変換 `generate_daily`→`job-generate-daily` |

特筆: 404/409/400/502/202 の使い分けは管理画面([07-admin-ui.md](07-admin-ui.md))のエラー表示と対応しています。

#### test_delete_post.py(7件)— 投稿削除(リモート成果物+doc)

対象: `pipeline/app/publishers/base.py` の `delete_post_channels()` と `pipeline/app/main.py` の `POST /api/posts/{id}/delete`。3 チャネルの削除 API(`x.delete` / `threads.delete` / `notion.archive_page`)は monkeypatch で偽物にしています。

| テスト関数 | 固定している振る舞い |
|---|---|
| `test_deletes_all_channels_and_doc()` | 全チャネルのリモート削除 + `deletePost=true` で doc も削除される |
| `test_deletes_channel_subset_keeps_doc()` | チャネル部分指定なら doc は残り、他チャネルは `published` のまま |
| `test_report_notion_delete_archives_localized_pages()` | report は `localizations` の言語別 Notion ページもアーカイブされる |
| `test_remote_error_is_reported_and_blocks_doc_delete()` | リモート削除失敗は `"error: ..."` として報告され、doc 削除がブロックされる |
| `test_pending_channel_without_artifact_is_disabled()` | 成果物の無い `pending` チャネルは API を呼ばず `skipped` + `enabled=false` になる |
| `test_delete_endpoint_404()` | 存在しない投稿 → 404 |
| `test_delete_endpoint_ok()` | エンドポイント正常系(`channels` / `docDeleted` を含む 200 応答) |

#### pipeline/tests/chat/(9ファイル・84件)— Research Chat

対象: `pipeline/app/chat/`(`graph.py` `api.py` `schemas.py` `prompts.py`)と `pipeline/app/repo/chat.py`。設計は [11-research-chat.md](11-research-chat.md)。他の pipeline テストと同じく monkeypatch/偽物差し替えで完結し、外部通信は行いません。`tests/chat/conftest.py` に本サブディレクトリ専用の fixture(Firestore 偽物など)がまとまっています。

| テストファイル | 件数 | 固定している振る舞い |
|---|---|---|
| `test_graph_chat_mode.py` | 4 | 壁打ち(chat)モード: トークンのストリーミング出力、履歴の組み立て、ツールを一切実行しないこと |
| `test_graph_research_quick.py` | 10 | 調査モード・クイック(quick)の plan→search→select→read→synthesize 一連。重複排除、ソースの優先順位(tier)並び替え、引用番号の採番、予算・締切超過時の早期打ち切り、コネクタ失敗が全体を止めないこと |
| `test_graph_research_deep.py` | 6 | 調査モード・ディープ(deep): LLM によるソース選定、ギャップ判定ループとその上限(`MAX_LOOPS=1`)、キャンセル |
| `test_chat_api_sse.py` | 17 | `pipeline/app/chat/api.py` の SSE エンドポイント: イベント順序・フレーミング、永続化、キャンセル、ワーカースレッド異常終了時の終了保証(`_SENTINEL`) |
| `test_chat_handoff.py` | 11 | 引き継ぎ(handoff): report → `seedContext` 付きの `queued` ResearchRun、short/article → 常に draft、404/409/400 の使い分け |
| `test_seed_block.py` | 13 | `build_seed_block()` の出力、調査計画プロンプトへの注入、生成系(short/article)へのシード材料受け渡し、下書き強制の担保 |
| `test_chat_repo.py` | 14 | `pipeline/app/repo/chat.py`: スレッド/メッセージの CRUD、トランザクションによる連番(`seq`)採番、履歴トリム、使用量(usage)の加算(**本スイート唯一の最小 Firestore 偽物を内蔵**) |
| `test_llm_seams.py` | 6 | `llm.structured` / `openai_client` の既定動作が、追加された `event_sink` / `stream_text` の縫い目(seam)によって**変わっていない**ことを固定するピン留めテスト |
| `test_stream_llm.py` | 3 | `stream_chat` の予算計上・監査の規律(`research/llm.py` の唯一の LLM 経路という原則を壊していないこと) |

特筆: `test_chat_repo.py` の Firestore 偽物は本スイートで唯一のもの(他ファイルは attribute monkeypatch で足りている)。`test_llm_seams.py` は Research Agent(doc 10)側の `llm.py` にチャット用の縫い目を追加した際の**非破壊性の証明**であり、doc 10 のテスト(`tests/research/*`)とは独立に両方通す必要があります。

#### test_prompts.py(9件)— プロンプト自体のガード

対象: `pipeline/app/research/prompts.py` の定数そのもの(LLM は呼びません)。「壊れても静かに壊れる」性質を機械的に守るためのファイルです。

| テスト関数 | 固定している振る舞い |
|---|---|
| `test_prompt_constants_are_discovered()` | ガードのガード。定数の集合が空なら以下の検査はすべて無意味に成功してしまうため、18個以上あることを先に確かめる |
| `test_all_prompts_are_english_no_cjk()` | 全プロンプト定数に CJK(ひらがな/カタカナ/漢字/ハングル)が無い = 英語ポリシー([10-research-agent.md](10-research-agent.md) §6.5) |
| `test_extract_prompt_keeps_injection_hardening()` | 間接プロンプトインジェクション対策の文言と `<<<DOCUMENT` フェンスが逐語で残る(§6.6) |
| `test_plan_prompt_keeps_connector_and_theme_enums()` | プロンプトのコネクタ名7種・themeClass 6種が `STRATEGY_MATRIX` と一致。ズレると全 RQ が既定クラスへ黙って落ちる |
| `test_trust_hierarchy_present_in_hardened_prompts()` | 信頼源ヒエラルキーが PLAN/TRIAGE に、tier 重み付けが VERIFY に存在し、`{_TRUST_HIERARCHY}` が未補間で残っていない |
| `test_output_language_directives_survive()` | 信頼源強化で canonical=ja の出力言語指定を壊していない |
| `test_every_system_prompt_demands_strict_json()` | 全 `*_SYSTEM` が "Return strictly the requested JSON" を含む(JSON モードの前提) |
| `test_system_prompts_have_no_unresolved_placeholders()` | `*_SYSTEM` は無加工で送られるため `{placeholder}` が残っていない(`LOCALIZE_SYSTEM` のみ例外) |
| `test_prompt_version_reflects_prompt_changes()` | プロンプトを変えれば `PROMPT_VERSION` が変わる(定義時補間の担保。§6.5 の罠) |

#### test_trusted_source_invariants.py(5件)— 信頼できる情報源の不変条件 【最重要級】

対象: **パイプライン全体**(`ResearchHarness` を偽 LLM/コネクタで通貫実行)。「政府・議会記録・査読論文・一次資料を優先する」という本システムの核心が、プロンプトではなく**決定的コード**で守られていることを成果物レベルで証明します([10-research-agent.md](10-research-agent.md) §4.2)。

| テスト関数 | 固定している振る舞い |
|---|---|
| `test_plan_fixes_invalid_strategies_to_matrix()` | planner が存在しないコネクタ名を返しても `STRATEGY_MATRIX` が検証・修正する(全滅時は `matrix[:4]` = 官公・学術系) |
| `test_strategy_matrix_never_leads_with_the_open_web()` | どのテーマ分類も `web_grounded` から始まらない。**例外として `society_culture` だけは web_grounded が academic より上位**(意図的な設計)であることも明示的に固定 |
| `test_triage_drops_tertiary_and_caps_selection()` | tertiary は選定・証拠のどちらにも入らない。`MAX_SELECTED=20` の打ち切り |
| `test_coverage_requires_tiered_evidence_loops_on_tertiary_only()` | RQ の解決には証拠2件以上かつ primary/secondary 1件以上。足りなければ resolved=false のまま gather へループバック |
| `test_weak_claims_render_demoted()` | **LLM が `corroborated` と主張しても**、引用ゲートを通らない弱い根拠なら renderAs が断定にならない(`opinion_report` へ降格)= モデルはゲートを言葉で突破できない |

特筆: この5件は**LangGraph 移行(M1/M2)を跨いで assertion を変えずに持ち越す**設計です(実行の縫い目だけを `runner.run_research` に差し替える)。信頼モデルの弱体化はレビューではなく**テストの失敗**として現れます。作成時に4種の変異(tertiary 除外の削除・引用ゲートの無効化・strategy 検証の削除・証拠件数の下限引き下げ)を注入し、それぞれ対応するテストだけが落ちることを確認済みです。

### 5. テスト ⇔ 機能文書の対応表

| テストファイル | 件数 | 主な対象コード | 対応する機能文書 |
|---|---|---|---|
| `tests/test_normalize.py` | 8 | `pipeline/app/normalize.py` | [02-collect.md](02-collect.md)、[../03-data-model.md](../03-data-model.md) |
| `tests/test_rss.py` | 2 | `pipeline/app/collectors/rss.py` | [02-collect.md](02-collect.md) |
| `tests/test_academic_sources.py` | 3 | `pipeline/app/collectors/rss.py`・`pipeline/app/collectors/ieee_xplore.py` | [02-collect.md](02-collect.md) |
| `tests/test_oauth1.py` | 3 | `pipeline/app/publishers/x.py` | [04-publish.md](04-publish.md) |
| `tests/test_renderer.py` | 10 | `pipeline/app/publishers/renderer.py` | [04-publish.md](04-publish.md) |
| `tests/test_notion_blocks.py` | 6 | `pipeline/app/publishers/notion.py` | [04-publish.md](04-publish.md) |
| `tests/test_publish_orchestration.py` | 8 | `pipeline/app/publishers/base.py` | [04-publish.md](04-publish.md)、[03-generate.md](03-generate.md)(Post の契約) |
| `tests/test_api.py` | 10 | `pipeline/app/main.py` | [05-pipeline-api.md](05-pipeline-api.md)、[06-ops-jobs.md](06-ops-jobs.md)(ジョブ手動実行) |
| `tests/test_keywords_cleanup.py` | 8 | `generators/prompts.py`・`collectors/gemini_grounded.py`・`jobs/cleanup_drafts.py` | [02-collect.md](02-collect.md)(キーワード収集)、[03-generate.md](03-generate.md)(キーワード生成)、[06-ops-jobs.md](06-ops-jobs.md)(下書き削除) |
| `tests/chat/`(9ファイル) | 84 | `pipeline/app/chat/`・`pipeline/app/repo/chat.py` | [11-research-chat.md](11-research-chat.md) |

### 6. テストが無い領域(正直な一覧)と実運用での補い

自動テストは「決定的で外部に依存しない部分」に集中投資されています。以下は意図的にテストが無い領域です。

| 領域 | テストが無い理由 | 実運用で補っているもの |
|---|---|---|
| 生成系すべて(`pipeline/app/generators/` の daily・longform・openai_client・prompts) | LLM の出力は毎回変わり、正解を assert できない | 週次・月次は下書き → 管理画面で人間が承認([03-generate.md](03-generate.md))。日次も管理画面で事後確認可能。トークン使用量は `posts` に記録 |
| ジョブ本体(`pipeline/app/jobs/` の collect・generate_daily・generate_weekly・generate_monthly・longform_runner・refresh_threads_token・seed) | Firestore・外部 API を束ねる結合部分で、単体テストの費用対効果が低い | 全実行が `runs` コレクションに記録され管理画面から確認できる([01-pipeline-foundation.md](01-pipeline-foundation.md))。失敗時の対応は `docs/runbook.md` |
| 収集の HTTP 経路(`RssCollector` のフィード取得部、`IeeeXploreCollector` の API 呼び出し部、`pipeline/app/collectors/gemini_grounded.py` と `pipeline/app/collectors/enrich.py` の全体) | パース(検証済み)と分離されており、残りは通信そのもの | `items` の ID 冪等性により重複せず、収集0件は runbook の点検対象 |
| 公開の HTTP 実装(`pipeline/app/publishers/x.py` の `upload_media()` / `post_tweet()`、`pipeline/app/publishers/threads.py` 全体、notion.py のページ作成部) | 署名・整形・オーケストレーションという「壊れやすい頭脳部分」は検証済み。残りは API 呼び出しの写経部分 | `--max-retries=0` + externalId 冪等 + 管理画面のチャネル別リトライ |
| Firestore アクセス層(`pipeline/app/repo/` 全体)と `pipeline/app/utils/`(GCS 署名 URL・ログ・リトライ) | 実データベース無しでは意味のある検証にならない | スキーマとトランザクション設計は [../03-data-model.md](../03-data-model.md) に明文化 |
| admin 全体 | **テストスクリプト自体が存在しない**。`admin/package.json` の scripts は dev / prebuild / build / start / typecheck のみ | `npm run typecheck`(`tsc --noEmit` = 型の矛盾だけを機械検証)と `npm run build` の成否。操作系は pipeline-api 側の検証(test_api.py)が下支え |
| infra のシェルスクリプト(`infra/` 全体) | シェルスクリプトの自動テストは未整備 | 冪等に再実行できる作りと、[08-infra.md](08-infra.md) の手順書化 |

「生成が変な文章を作らないか」はテストでは守られていない、と理解しておくのが正確です。守っているのは承認フローと管理画面です。

## 第2部: 文書検証の恒久手順

tech-report(この文書群)を更新したら、以下の手順 1〜6 を上から順に実行してください。所要は全部で 10 分程度です。CLAUDE.md の規定(コード変更時は対応文書を必ず同時更新)の「検算」に当たります。CI が無いため、これも手動です。**すべてリポジトリのルートディレクトリで実行**します。

### 7. 手順1: 文書中のファイルパス実在チェック

文書内でバッククォート付きで書かれた `pipeline/...` `admin/...` `infra/...` `shared/...` `docs/...` 形式のパスを全部集め、実在を確認します。

```bash
grep -rhoE '`(pipeline|admin|infra|shared|docs)/[^` ]+`' docs/tech-report --include='*.md' \
  | tr -d '`' \
  | grep -vE '[*<>{]|\.\.\.' \
  | sort -u \
  | while read -r p; do [ -e "$p" ] || echo "存在しないパス: $p"; done
```

1行目: 全文書からパス形式のコードスパン(バッククォート囲み)を抽出。2行目: バッククォートを除去。3行目: ワイルドカードやプレースホルダーを含む表記(アスタリスク・山括弧・三点リーダー)を除外。4行目: 重複を除いて整列。5行目: 1件ずつ `test -e`(存在確認)し、無いものだけ表示。

**何も表示されなければ合格**です。表示されたら、コード側でファイルが改名・削除されたのに文書が古いままです。なおこのチェックが機能する前提として、文書中のパスは必ずバッククォートで囲む規約を維持してください。

### 8. 手順2: 関数名実在チェック

文書内で `名前()` の形式(バッククォート囲み・丸括弧付き)で言及された関数がコードに実在するかを確認します。

```bash
grep -rhoE '`[a-z_][A-Za-z0-9_.]*\(\)`' docs/tech-report --include='*.md' \
  | tr -d '`()' | sort -u \
  | while read -r f; do
      base=${f##*.}
      grep -rq "def ${base}(" pipeline/app pipeline/tests \
        || grep -rq "${base}" admin/src \
        || echo "定義が見つからない: $f"
    done
```

前半: 文書から `関数名()` 形式のコードスパンを抽出し、記号を外して一覧化。後半: `obj.method()` 形式は最後の名前だけ取り出し(`${f##*.}`)、まず Python 側を `def 名前(` で検索(`async def` も部分一致で拾えます)、見つからなければ admin 側(TypeScript)を名前の出現で検索します。

注意: admin 側は関数の書き方が多様(アロー関数等)なため名前の出現だけを見る緩い判定です。「見つからない」と出たものが本当に消えたのか、書き方の問題なのかは目視で確定してください。

### 9. 手順3: パラメーター突合

[../04-parameters.md](../04-parameters.md) の表を、値の実際の出所と**1行ずつ**照合します。出所は次の4つです。

```bash
sed -n '1,80p' pipeline/app/config.py
```
アプリの既定値(Settings クラス)。モデル名(`openai_model_daily` 等)・しきい値はここが基準。

```bash
grep -nE '^[A-Z_]+=' infra/env.sh
```
デプロイスクリプト共通の変数(プロジェクト ID・リージョン・サービスアカウント名など)。

```bash
grep -n -- '--set-env-vars\|--set-secrets' infra/10-deploy-pipeline.sh
grep -n -- '--schedule' infra/20-schedulers.sh
```
デプロイ時に注入される環境変数・シークレットと、スケジュール(cron 式)。

さらに CLAUDE.md の落とし穴どおり、**本番ジョブには `GEMINI_MODEL` 等の env 上書きが入っている場合があります**。config.py と文書が一致していても本番と違うことがあるため、モデル名などの重要値は本番側も確認します(要 gcloud 認証):

```bash
gcloud run jobs describe job-collect --region=asia-northeast1 --format=yaml | grep -A20 'env:'
```

### 10. 手順4: enum 突合

enum(選択肢の固定リスト。投稿ステータス等)の唯一のソースは `shared/constants.json` です。まず現物を表示します。

```bash
python3 -c "
import json
d = json.load(open('shared/constants.json'))
for k, v in d.items(): print(f'{k}: {v}')"
```

キー(formats / channels / postStatuses / channelStatuses / sourceTypes / languages / jobTypes / researchRunStatuses)が表示されます。これを次の3か所と照合します。

1. [../03-data-model.md](../03-data-model.md) の enum 表 — 文書側
2. `pipeline/app/models.py` の enum クラス(`Format` / `Channel` / `PostStatus` / `ChannelStatus` / `SourceType`)、`pipeline/app/research/schemas.py` の `ResearchRunStatus`(researchRunStatuses に対応)、`pipeline/app/main.py` の `JOB_MODULES`(jobTypes に対応)— Python 側は JSON を読み込まず**手で複製されている**ため、値を変えたら両方直す必要があります
3. admin 側 — `admin/scripts/sync-constants.mjs` が prebuild で JSON をコピーする仕組みのため、値の変更後は **admin の再ビルドが必要**です

### 11. 手順5: pytest 実行 / 手順6: Mermaid とリンクの確認

**手順5**: 第1部の方法で全テストを回します。

```bash
cd pipeline && pytest
```

基準は `256 passed`(2026-07-15 時点。内訳: `pipeline/tests/` 直下11ファイル75件 + `tests/research/*` 11ファイル97件(Research Agent — スキーマ round-trip / lease / budget / rubric / コネクタ(respx)/ fetcher ガード / golden plan→review 通貫 / API / 失敗パターン §7.3 / LangSmith 配線 / **プロンプト言語・注入防御ガード(`test_prompts.py`)** / **信頼源の不変条件(`test_trusted_source_invariants.py`)**)+ `tests/chat/*` 9ファイル84件(Research Chat — 4章末尾参照))。失敗や collection error が出た状態で文書だけ直しても意味がないので、先にコードを直します。**件数が前回より減っていたら**、誰かがテストを消した合図なので経緯を確認してください。

**手順6a — Mermaid 図の構文確認**: 文書中の図(` ```mermaid ` ブロック)は構文エラーがあると描画されません。まず一覧を出します。

```bash
grep -rn '```mermaid' docs/tech-report --include='*.md'
```

各図は GitHub 上のプレビューで開くか、ブロックの中身を https://mermaid.live に貼り付けて描画されることを確認します(エラーならその場で赤く表示されます)。Node.js があればコマンドラインでも検証できます(図を画像として出力できれば構文は正しい):

```bash
npx -y @mermaid-js/mermaid-cli -i docs/tech-report/05-detailed-design/02-collect.md -o /tmp/mmd-check.md
```

**手順6b — 相対リンク切れ確認**: Markdown の文書間リンク(角括弧の表示名+丸括弧の相対パス、という記法)の飛び先が実在するか確認します。

```bash
find docs/tech-report -name '*.md' | while read -r f; do
  d=$(dirname "$f")
  grep -oE '\]\([^)]+\)' "$f" \
    | sed -E 's/^\]\((.*)\)$/\1/' | sed 's/#.*//' \
    | grep -vE '^(https?:|mailto:|$)' \
    | while read -r l; do [ -e "$d/$l" ] || echo "$f → リンク切れ: $l"; done
done
```

各文書について、リンク記法から括弧内のパスを取り出し(`#見出し` 部分と外部 URL は除外)、その文書のあるディレクトリ基準で実在確認します。何も表示されなければ合格です。

### 12. 変更するときは(テスト追加の指針)

コードを変更する際、どのテストを更新・追加すべきかの早見表です。

| こういう変更をしたら | 更新・追加するテスト |
|---|---|
| URL 正規化・タイトル重複判定のルール変更 | `tests/test_normalize.py` に新旧のケースを追加 |
| フィード・API 応答から取り出すフィールドの変更 | `tests/fixtures/` のサンプルにその要素を足し、`tests/test_rss.py` / `tests/test_academic_sources.py` を更新 |
| 新しいソース種別(コレクター)の追加 | パース部分を純粋関数に切り出し、fixture + パーステストを新設 |
| **OAuth 署名ロジック(`oauth1_header()`)に少しでも触れた** | `tests/test_oauth1.py` を必ず実行。既知ベクタの期待値は変更禁止 |
| 文字数制限・分割・URL 追記のルール変更 | `tests/test_renderer.py`(境界値: 上限ちょうど/超過の両方を書く) |
| Markdown → Notion 変換で対応記法を追加 | `tests/test_notion_blocks.py` |
| 公開順・冪等性・ステータス遷移・チャネル追加 | `tests/test_publish_orchestration.py`(`store` fixture に偽アダプタを追加して呼び出し順を assert) |
| pipeline-api のエンドポイント追加・応答コード変更 | `tests/test_api.py` |
| HTTP を直接呼ぶコードそのものをテストしたい | respx を使う(プロジェクト方針)。例: |

```python
import respx

@respx.mock
def test_example():
    route = respx.post("https://api.x.com/2/tweets").respond(json={"data": {"id": "1"}})
    # ここで実際の投稿関数を呼ぶと、上の偽応答が返り、route.called で呼ばれたか確認できる
```

生成系(LLM 呼び出し)は前述のとおり出力を assert できませんが、**プロンプトの組み立てや応答の後処理など決定的な部分を関数に切り出せばテスト可能**になります。ロジックを足すときはまず「純粋関数に切り出せないか」を考えるのが本プロジェクトの流儀です。

最後に、テストを追加・削除したら**この文書自体の 4章・5章・6章の表と件数を更新**してください(それが第2部の手順で検出される側に回らないために)。
