# 01. 要件定義 — 実装済み機能の一覧と受け入れ条件(as-built)

> 対象コード時点: コミット c694140 + 未コミット変更 / 最終更新: 2026-07-15(リサーチチャット FR-5 追加)

## 1. この文書の位置づけ

- 本書は「これから作るもの」ではなく「**現に実装されているもの**」の要件定義(as-built = 竣工図)である。各要件の受け入れ条件は理想値ではなく、コード・テスト・完成済みの兄弟文書で確認済みの**現在の実際の挙動**をそのまま書く。
- 個々の数値(文字数上限・時刻・件数など)の正(基準)は [04-parameters.md](04-parameters.md) であり、本書への転記は要件の理解に必要な最小限にとどめる。データ構造の正は [03-data-model.md](03-data-model.md)。
- 要件を変更するときは、第 5 章の FR⇔実装対応表から該当コードと詳細文書を特定し、コード・テスト・文書を同時に更新する(文書とコードの一致を検証する手順は [05-detailed-design/09-tests.md](05-detailed-design/09-tests.md) 第 2 部)。

### 用語(本書全体で使う言葉)

| 用語 | 意味 |
|---|---|
| ジョブ | Cloud Run Jobs(起動 → 処理 → 終了する GCP の使い切り実行環境)で動く処理単位。本システムには 6 つある |
| チャネル | 投稿の公開先サービス。`x` / `threads` / `notion` の 3 つ |
| 投稿(post) | 生成された記事 1 本分のデータ。3 チャネル分の本文と公開状態を 1 ドキュメントに内包する |
| 収集アイテム(item) | 収集した記事 1 件分のデータ |
| カデンス(cadence) | 投稿頻度の区分。`daily`(日次)/ `weekly`(週次)/ `monthly`(月次) |
| 下書き(`draft`) | 人の承認を待っている状態の投稿 |
| 管理画面(admin) | オーナーが使う Web 画面(Next.js 製、IAP 保護) |
| LLM | 大規模言語モデル。文章を読み書きできる生成 AI。本システムは OpenAI(生成)と Gemini(検索収集)を使う |
| 受け入れ条件 | 「要件が満たされている」と判定する具体条件。本書では現在の実挙動そのもの |

## 2. システムの目的と利用者

**目的(3 行)**:

1. 技術・経済・国際政治のトレンドを毎日自動収集し、LLM で投稿文を生成して X・Threads・Notion の 3 チャネルへ投稿する。
2. 日次の短文は全自動で投稿し、週次・月次の長文は下書き(`draft`)を人が管理画面で承認してから公開する。
3. 運用(設定変更・承認・失敗リトライ・手動実行)は管理画面 1 つで完結させ、インフラは GCP 単一プロジェクト(`trend-news-generator` / `asia-northeast1`)に閉じる。

**利用者**:

| 利用者 | 人数 | 関わり方 |
|---|---|---|
| オーナー(moc9058@gmail.com) | 1 名 | 管理画面の全機能(承認・設定・リトライ・手動実行)。IAP の通過許可(`infra/env.sh` の `ADMIN_EMAIL`)はこの 1 アカウントのみで、承認者・運用者・開発者を兼ねる |
| SNS・Notion の読者 | 不特定 | 公開された投稿を読むだけ。本システムのアカウント・画面は持たない |

本システムは**オーナー 1 名による個人運用**を前提に設計されており、複数ユーザー・権限分離は明示的な非要件である(第 7 章)。

## 3. 機能要件(FR)

README のフロー①〜④(収集 → 生成 → 投稿・承認 → 運用)に対応する 4 グループ・計 18 要件。各要件は「要件文(1 行)+受け入れ条件(現在の挙動)+詳細文書」の形式で記す。

### FR-1 収集 — フロー①(毎日 06:00 JST、job-collect)

外部ソースから記事を集め、Firestore(GCP のドキュメント型データベース)の `items` コレクションと GCS(ファイル置き場)に保存する。

#### FR-1.1 RSS/Atom 収集(arXiv 含む)

**要件**: Firestore の `sources` に登録した RSS/Atom フィード(サイト更新情報の定型 XML)から記事を取り込めること。

受け入れ条件(現在の挙動):

- 有効なカテゴリ × 有効なソースを巡回し、1 フィードあたり最大 30 エントリ、要約は 2,000 字までを `items` に保存する。
- 前回取得時の ETag / Last-Modified を使う条件付き GET により、未更新のフィード(HTTP 304)はダウンロードも解析もしない。
- arXiv の Atom フィードは専用実装を持たず、`rss` タイプのソースとして同じ経路で処理される(`pipeline/tests/test_academic_sources.py` が固定)。
- ソースの追加・停止は管理画面から行え、コード変更を要しない。

詳細: [05-detailed-design/02-collect.md](05-detailed-design/02-collect.md)

#### FR-1.2 Gemini グラウンディング検索

**要件**: 検索クエリ(`sources.query`)を与えるだけで、Google 検索を根拠にした直近ニュースを収集できること。

受け入れ条件(現在の挙動):

- Gemini(既定モデル `gemini-3.5-flash`。本番ジョブは環境変数で上書きされ得る)の `google_search` ツールで、直近 24〜48 時間の主要ニュース 5〜8 件を JSON で受け取る。プロンプトで URL の捏造を禁止している。
- 応答が壊れていても例外にせず「そのソースは 0 件」に落とす(収集ジョブ全体は止まらない)。
- 根拠として参照された URL(最大 20 件)を item の `groundingCitations` に保存する。

詳細: [05-detailed-design/02-collect.md](05-detailed-design/02-collect.md)

#### FR-1.3 IEEE Xplore 収集(任意キー)

**要件**: IEEE Xplore(論文検索 API)から学術記事のメタデータを収集できること。ただし API キーは任意とする。

受け入れ条件(現在の挙動):

- 検索クエリに対し出版日の降順で最大 10 件を取得する。
- API キー(`IEEE_API_KEY`)が未設定の場合は警告ログを出して空リストを返すだけで、エラーにしない(他ソースの収集を巻き込まない)。
- seed(FR-4.2)ではこのソースは `enabled: false` で投入され、キーを用意した人だけが管理画面で有効化する運用。

詳細: [05-detailed-design/02-collect.md](05-detailed-design/02-collect.md)

#### FR-1.4 二重の重複排除

**要件**: 同じ記事・同じ話題を二度保存しないこと。

受け入れ条件(現在の挙動):

- **URL 単位(完全)**: URL を正規化(追跡パラメータ `utm_*` 等・`www.`・末尾スラッシュの除去など)し、その SHA-256 ハッシュ先頭 32 文字を `items` のドキュメント ID とする。Firestore の排他作成(`create`)を使うため、同じ URL の再収集・ジョブ再実行でも絶対に 2 件にならない。
- **タイトル単位(近似)**: 正規化タイトル(語順・大小文字・記号に鈍感な「単語袋」)のハッシュが、同カテゴリ・過去 7 日以内に存在すれば保存前に破棄する。「URL は違うが実質同じ話」を弾くための窓。
- 重複は統計 `deduped` として記録されるだけで、エラー扱いにならない。

詳細: [05-detailed-design/02-collect.md](05-detailed-design/02-collect.md)、[03-data-model.md](03-data-model.md)

#### FR-1.5 og:image 取得と GCS 保存

**要件**: 記事の代表画像(og:image)と本文テキストを補完し、画像は GCS に保存できること。

受け入れ条件(現在の挙動):

- 画像 URL か本文が欠けている item は記事ページを取得し、og:image の URL と本文テキスト(最大 10,000 字)を補完する。
- 画像は jpeg / png / webp / gif かつ 8 MiB 以下のみを受け入れ、GCS の `items/{docID}/og.{拡張子}` に保存する。
- 補完・画像取得の失敗はエラー扱いにせず、画像・本文なしのまま item を保存して続行する。保存された画像は日次投稿の X / Threads 添付候補になる(FR-2.1)。

詳細: [05-detailed-design/02-collect.md](05-detailed-design/02-collect.md)

### FR-2 生成 — フロー②(日次 08:00 / 週次 月曜 07:00 / 月次 毎月 1 日 07:00 JST)

収集アイテムを材料に、OpenAI の LLM で投稿を生成する。

#### FR-2.1 日次短文の生成

**要件**: カテゴリごとに、3 チャネル分の短文を 1 回の LLM 呼び出しでまとめて生成できること。

受け入れ条件(現在の挙動):

- 直近 36 時間・最大 15 件の item を材料に、`gpt-5.6-luna`(既定)への 1 回の JSON モード呼び出しで X 用・Threads 用・Notion 用のテキストを同時に得る(チャネル別に呼ばないため呼び出し回数は 1/3。文字数超過時のみ縮小リトライで +1 回)。
- 各チャネルの出力言語は `channelConfigs` から注入され、seed 投入時の既定は x=`ja`(日本語)/ threads=`ko`(韓国語)/ notion=`en`(英語)。プロンプト本文は内容だけを指示し、言語は設定から来る分離設計。
- 「3 チャネルすべて無効」「直近 36 時間の item が 0 件」「プロンプトテンプレートが無い/無効」のカテゴリはスキップされる(エラーではない)。
- `settings/app` の `attachImages`(既定 true)が有効なら、画像を持つ最初の item の画像を X / Threads の添付候補として記録する。

詳細: [05-detailed-design/03-generate.md](05-detailed-design/03-generate.md)

#### FR-2.2 週次・月次の 2 段階長文生成

**要件**: 長文記事を「安いモデルで素材選定 → 高性能モデルで執筆」の 2 段階で生成し、必ず下書きとして保存すること。

受け入れ条件(現在の挙動):

- 第 1 段(選定): 週次は 7 日・月次は 30 日の候補 item(最大 120 件、タイトル+要約のみ)を `gpt-5.6-luna` に渡し、テーマ・章立て・使用 item の ID を選ばせる。候補が 3 件未満のカテゴリはスキップ。
- 第 2 段(執筆): 選定された item(最大 25 件、各本文最大 4,000 字)を `gpt-5.6-terra`(既定)に渡し、本文(Markdown)・要約・X / Threads 用ティーザー(本文へ誘導する短い紹介文)を受け取る。
- 月次は第 1 段の材料に当月の週次記事の要約(直近 8 投稿・31 日以内)を加える「階層的蓄積」を行う。
- 生成結果は**常に** `draft` で保存され、このジョブから投稿する経路はコード上存在しない(自動投稿される余地が構造的にない)。

詳細: [05-detailed-design/03-generate.md](05-detailed-design/03-generate.md)

#### FR-2.3 プロンプト・モデルの管理画面差し替え

**要件**: 生成プロンプトと使用モデルを、再デプロイなしで管理画面から変更できること。

受け入れ条件(現在の挙動):

- 実行時に読まれるプロンプトは常に Firestore の `promptTemplates`(コード内の `DEFAULTS` は seed 用の雛形にすぎない)。管理画面で編集すると次のジョブ実行から反映される。
- テンプレートの `modelOverride` を設定すると、日次生成と長文の**第 2 段(執筆)**のモデルが差し替わる。長文の第 1 段(選定)は常に既定の `openai_model_daily` で固定。
- テンプレートを `enabled: false` にすると、そのカテゴリ×カデンスの生成はスキップされる。
- テンプレートの `customInstructions`(自由記述の常設リクエスト。管理画面の `/focus` ページで編集、ko/ja/en いずれで書いてもよい)は、生成プロンプト末尾に OWNER INSTRUCTIONS ブロックとして付加される(short / article の2段階 / report の write)。チャネル別の出力言語は変えない。
- `settings/app` の `globalChannels`(既定 X=off / Threads=off / Notion=on)はチャネル全体のキルスイッチで、生成時にカテゴリ別 `channelConfigs.enabled` と AND される。

詳細: [05-detailed-design/03-generate.md](05-detailed-design/03-generate.md)、[03-data-model.md](03-data-model.md)

### FR-3 投稿・承認 — フロー③

生成済みの投稿を外部チャネルへ公開する。入口は「日次ジョブからの自動公開」と「管理画面からの承認公開(pipeline-api 経由)」の 2 つで、どちらも同じ公開処理 `publish_post()` に合流する。

#### FR-3.1 公開順は notion → x → threads 固定

**要件**: 3 チャネルへ `notion` → `x` → `threads` の固定順で公開すること。

受け入れ条件(現在の挙動):

- 順序は `pipeline/app/publishers/base.py` にリテラルで書かれ、テスト(`pipeline/tests/test_publish_orchestration.py`)で固定されている。週次・月次の X / Threads ティーザー末尾に Notion の公開 URL を付けるため、URL の供給元である Notion を必ず先に公開する必要がある。
- あるチャネルの失敗は他チャネルの続行を妨げない(チャネル単位の失敗隔離)。全チャネル終了後、成功と失敗の混在は `partially_published`、全滅は `failed`、失敗ゼロは `published` として投稿全体の状態が決まる。

詳細: [05-detailed-design/04-publish.md](05-detailed-design/04-publish.md)

#### FR-3.2 承認フロー(日次=自動、週次・月次=承認制)

**要件**: 日次は既定で自動投稿し、週次・月次は必ず人の承認を経て投稿すること。

受け入れ条件(現在の挙動):

- 日次: `settings/app` の `dailyRequireApproval`(既定 `false`)が偽なら投稿は `approved` 状態で作成され、生成ジョブ内でそのまま公開まで進む。真に切り替えると日次も `draft` で止まる(管理画面から変更可能な安全弁)。
- 週次・月次: 常に `draft` で作成され、管理画面の「承認して投稿」→ pipeline-api の `POST /api/posts/{id}/publish` で同期公開される。承認者のメールアドレス(IAP 認証由来)が投稿の `approvedBy` に記録される。
- 公開時にチェックを外したチャネルは `skipped`(対象外)に確定し、API 経由で復活させる手段はない。すでに `published` / `publishing` の投稿への再公開要求は HTTP 409 で拒否される(二重公開の入口ブロック)。

詳細: [05-detailed-design/05-pipeline-api.md](05-detailed-design/05-pipeline-api.md)、[05-detailed-design/04-publish.md](05-detailed-design/04-publish.md)

#### FR-3.3 チャネル別リトライ(`failed` のみ)

**要件**: 失敗したチャネルだけを、成功済みチャネルに触れずに再実行できること。

受け入れ条件(現在の挙動):

- 管理画面の投稿履歴で `failed` チャネルの横に出るリトライボタン → pipeline-api の `POST /api/posts/{id}/retry-channel`。状態が `failed` 以外のチャネル(`pending` / `published` / `skipped`)への要求は 409 で拒否される。
- 対象チャネルを `pending` に戻しエラーをクリアしたうえで、`only_channel` 指定の公開処理を実行する。他チャネルには一切触れない(テストで固定)。

詳細: [05-detailed-design/05-pipeline-api.md](05-detailed-design/05-pipeline-api.md)

#### FR-3.4 冪等性 — 再実行しても二重投稿しない

**要件**: 公開処理を途中クラッシュ後に再実行しても、外部サービスへの投稿が 1 回分にとどまること(冪等性)。

受け入れ条件(現在の挙動):

- 公開先が発行した ID(`externalId`)が記録済みのチャネルは、再実行時に必ずスキップされる。
- Threads は「container(投稿の器)作成 → 公開」の 2 段階 API のため、container 作成の**直後**に `containerId` を Firestore へ永続化する。公開前にクラッシュしても、リトライ時は同じ container の公開から再開し、2 個目を作らない(テスト `test_resumes_persisted_threads_container` が固定)。
- 投稿系ジョブは `--max-retries=0` でデプロイされ、インフラによる自動再実行は起きない(NFR-1)。

詳細: [05-detailed-design/04-publish.md](05-detailed-design/04-publish.md)

#### FR-3.5 チャネル別の文字数制御

**要件**: X・Threads それぞれの文字数制限に必ず収まる形で投稿すること。

受け入れ条件(現在の挙動):

- X は「加重 280」(全角級の文字=2、半角=1、URL は長さによらず一律 23 と数える X 公式仕様)で判定する。
- 生成時に超過を検知したら「短く書き直せ」の縮小リトライを 1 回だけ行う。それでも X が超過する場合は文単位で分割し、連番 `(i/n)` 付きの連投スレッドとして投稿する(切り捨てない)。Threads は 500 字で、なお超過する場合は 499 字+「…」に強制トリムする(文字数を理由に日次ジョブが落ちることはない)。
- 長文ティーザーへの URL 追記時は、上限に収まるまで本文側を削って合成する(`append_url`)。境界値(280/281、500/501 等)はテストで固定。管理画面の残文字数表示は同ルールの TypeScript ミラーで、判定の正は常に pipeline 側。

詳細: [05-detailed-design/04-publish.md](05-detailed-design/04-publish.md)、[05-detailed-design/03-generate.md](05-detailed-design/03-generate.md)

#### FR-3.6 公開済み投稿の削除

**要件**: 公開済みの投稿を、リモート成果物(ツイート・Threads メディア・Notion ページ)ごと管理画面から削除できること。

受け入れ条件(現在の挙動):

- pipeline-api の `POST /api/posts/{id}/delete`(`{channels, deletePost}`)が実体。`channels` 省略時は成果物を持つ全チャネル。X はツイート削除(404 は成功扱い)、Threads はメディア削除、Notion はページのアーカイブ(report の言語別ページ含む)。
- 成功したチャネルは `deleted` + `enabled=false` になり再公開されない。`deletePost=true` かつ `published` チャネルが残らず全チャネルエラーなしなら Firestore の post ドキュメントも削除する。
- 管理画面からは投稿履歴の複数選択削除(投稿ごと)と、投稿詳細のチャネル別削除ができる。
- 既知の制限: X のスレッド投稿は先頭ツイート ID しか保存されないため、返信ツイートは残る。

詳細: [05-detailed-design/04-publish.md](05-detailed-design/04-publish.md)、[05-detailed-design/05-pipeline-api.md](05-detailed-design/05-pipeline-api.md)

### FR-4 運用 — フロー④と管理画面

#### FR-4.1 Threads トークンの週次自動更新

**要件**: 約 60 日で失効する Threads のアクセストークンを、人手なしで更新し続けること。

受け入れ条件(現在の挙動):

- 毎週月曜 03:00 JST に更新 API を呼び、新トークンを Secret Manager(GCP の秘密情報保管サービス)へ新バージョンとして追加し、旧バージョンを無効化(削除ではなくロールバック可能な disable)する。
- 新しい有効期限を `settings/channelHealth` に記録し、管理画面ダッシュボードが「残り日数」を表示する(14 日未満または更新エラーで赤色警告)。
- 更新失敗時は自動再実行されない(`--max-retries=0`)が、週次更新 × 60 日寿命の余裕により数回の失敗は許容される。新トークンが効くのは次のコンテナ起動から。

詳細: [05-detailed-design/06-ops-jobs.md](05-detailed-design/06-ops-jobs.md)

#### FR-4.2 seed — 初期データ投入(既存を上書きしない)

**要件**: 空の Firestore にシステム稼働に必要な初期データを 1 コマンドで投入でき、再実行しても既存データを壊さないこと。

受け入れ条件(現在の挙動):

- カテゴリ 3・ソース 10(うち arXiv と IEEE の 2 件は `enabled: false` で投入)・プロンプトテンプレート 9・チャネル設定 27・settings 3 の計 52 ドキュメントを投入する。
- チャネル既定言語(x=`ja` / threads=`ko` / notion=`en`)と運用フラグの既定値(`dailyRequireApproval: false` など)はここで決まる。
- **既存ドキュメントには一切触れない**(存在確認してから作成する create-only)。したがって管理画面での編集後に seed を再実行しても編集内容は無傷。裏返しに、コード側の初期値変更は既存環境へ反映されない。
- `settings/notion` の `databaseId` は空で投入されるため、管理画面での入力が別途必要(空のままだと Notion 公開は失敗する)。

詳細: [05-detailed-design/06-ops-jobs.md](05-detailed-design/06-ops-jobs.md)

#### FR-4.3 管理画面での設定 CRUD

**要件**: カテゴリ・ソース・プロンプト・チャネル設定・アプリ設定を管理画面から作成・閲覧・更新(ソースは削除も)できること。

受け入れ条件(現在の挙動):

- 全 14 画面(ダッシュボード/下書き一覧・編集/投稿履歴・投稿詳細/フォーカス/カテゴリ/ソース/プロンプト一覧・編集/チャネル/設定/research 一覧・詳細)。サイドバーのナビは Main(ダッシュボード・投稿履歴・下書き・フォーカス)+ System(設定)に絞られ、カテゴリ〜research は設定ページのリンクグリッドから開く。
- DB 内で完結する操作(設定保存・フォーカス保存・自動化グリッド・下書きテキスト保存/削除)は Firestore へ直接書き、外部への副作用がある操作(承認公開・リトライ・削除・ジョブ実行・レポート run 作成)だけが pipeline-api を経由する。
- 設定ページでは `globalChannels`(チャネル全体の on/off)を切り替えられる。フォーカスページでは カテゴリ×フォーマット単位の `focusKeywords` と `customInstructions` を編集できる。
- 下書き編集ではタイトル・要約・本文・X / Threads 用テキストを編集でき、X は加重文字数のライブ表示(280 超で赤字)が付く。保存はステータスを変えない。
- ソースの削除は確認ダイアログなしで即実行される(現挙動として明記)。

詳細: [05-detailed-design/07-admin-ui.md](05-detailed-design/07-admin-ui.md)

#### FR-4.4 手動ジョブ実行

**要件**: スケジュールを待たずに、管理画面から任意のジョブを実行できること。

受け入れ条件(現在の挙動):

- 7 ジョブ(`collect` / `generate_short` / `generate_article` / `generate_report` / `cleanup_drafts` / `refresh_threads_token` / `seed`)を pipeline-api の `POST /api/jobs/{name}/run` で起動できる(`main.py` の `JOB_MODULES`)。
- 応答は 202(受付)を即返し、ジョブ本体は pipeline-api のプロセス内でバックグラウンド実行される(Cloud Run Jobs とは別経路)。**成否は HTTP では分からず**、`runs` コレクション(ダッシュボードに表示)と Cloud Logging で確認する。

詳細: [05-detailed-design/05-pipeline-api.md](05-detailed-design/05-pipeline-api.md)

#### FR-4.5 ダッシュボード

**要件**: システムの健康状態(コスト・トークン期限・実行履歴・承認待ち)を 1 画面で確認できること。

受け入れ条件(現在の挙動):

- LLM コスト概算の当月分と累計(いずれも `runs.costUsd` + `researchRuns.budget.usdSpent` の合計。当月は UTC 月初起点)、Threads トークンの残り日数(14 日未満で赤字)、承認待ち下書き数のカードを表示する。
- Threads トークン更新の失敗時は画面最上部に赤帯が出る(`threadsRefreshError` が空でないとき)。
- 自動化グリッド(カテゴリ×フォーマットの生成 on/off とチャネル別トグル、フォーマット別スケジュールラベル付き)と手動実行ボタン(short / article / report。report は `POST /api/research/runs` で自動テーマの調査 run を作成)を持つ。
- 承認待ち下書き(先頭 5 件)・直近の投稿(8 件、チャネル別状態バッジ付き)を一覧する。ジョブ実行履歴は設定ページへ移設。

詳細: [05-detailed-design/07-admin-ui.md](05-detailed-design/07-admin-ui.md)

### FR-5 リサーチチャット — 管理画面の個人用チャット

#### FR-5.1 壁打ちモード(chat)

**要件**: 自分のアイデアを深掘りするための対話ができること。汎用チャットより鋭い相手であること。

受け入れ条件(現在の挙動):

- ダッシュボード最上部の常設パネル、または専用ページ `/[locale]/chat` から送信できる。応答はトークン単位でストリーミング表示される。
- 応答は**ユーザーが書いた言語**で返る(チャネル言語設定とは無関係の個人ツール)。
- ツール(検索・fetch)は使わない。前提の指摘・反論・構造化を行い、過度に同調しない(`SPARRING_SYSTEM`)。

#### FR-5.2 調査モード(research)

**要件**: 信頼できる一次資料を自律的に探し、**本文を読んだ上で**引用付きの回答を返すこと。

受け入れ条件(現在の挙動):

- 深さは quick(1〜3分・上限 $0.7)/ deep(〜10分・上限 $3)の2段階。上限は構造的に超えられない。
- 既存コネクタ(国会会議録・政府資料・学術・IEEE・書籍・良質報道・グラウンディング検索)に加え、収集済み `items` を引く `internal_items` を使う。本文取得は Research Agent の `Fetcher`(SSRF ガード・robots・レート制限)をそのまま経由する。
- 回答は番号付き引用 [n] と出典リスト(URL・tier・信頼度スコア)を伴う。
- 検索・取得の進捗(計画中/検索中/読解中…)が画面に出る。
- 予算切れ・時間切れ・キャンセル時は**エラーにせず**、そこまでの材料で「打ち切った」と明示した回答を返す。出典0件の場合はその旨と、無出典である旨を明記して答える。
- 取得した本文は untrusted data として扱い、その中の指示には従わない。

#### FR-5.3 作成フローへの引き継ぎ(handoff)

**要件**: 会話の結論を短文・記事・レポートの作成に流せること。

受け入れ条件(現在の挙動):

- 完了した assistant メッセージから format(短文/記事/レポート)を選んで作成に回せる。
- **チャット発の短文は `shortRequireApproval` の設定に関係なく常に下書き**。このエンドポイントは投稿を一切行わず、公開は既存の承認 → publish フローに限定される(NFR-1 の方針に抵触しない)。
- レポートは `trigger="chat"` の調査 run を `queued` で作成し、会話の要約と出典を `seedContext` として渡す。調査計画フェーズはそれを「検証すべき先行作業」として受け取る(結論としてではない)。
- 作成物への参照が元メッセージに残り、画面からたどれる。

詳細: [05-detailed-design/11-research-chat.md](05-detailed-design/11-research-chat.md)

## 4. 非機能要件(NFR)

#### NFR-1 二重投稿防止(3 層)

同じ内容が外部 SNS に 2 回投稿される事故を、独立した 3 層で防ぐ。これは本システムでもっとも優先される品質特性である。

| 層 | 仕組み | 実装 |
|---|---|---|
| 1 | 投稿系ジョブ(生成 3 種+トークン更新)は `--max-retries=0`。クラッシュしてもインフラが自動再実行しない | `infra/10-deploy-pipeline.sh`(collect / seed のみ 1) |
| 2 | チャネルごとの `externalId`(公開先が発行した ID)。非空なら再実行時に必ずスキップ | `pipeline/app/publishers/base.py` |
| 3 | Threads 専用の `containerId` 早期永続化。2 段階 API の中間 ID を作成直後に保存し、途中クラッシュ後も同じ container から再開 | 同上 |

受け入れ条件: `pipeline/tests/test_publish_orchestration.py` の externalId スキップ・container 再開テストが通ること。`--max-retries=0` の方針は確定事項であり崩さない。詳細: [05-detailed-design/04-publish.md](05-detailed-design/04-publish.md)

#### NFR-2 コスト制御

- **X**: 投稿は従量課金(1 投稿 $0.015、URL 付き投稿は $0.20)のため、日次の X 投稿は既定で URL を付けない(`xAllowUrlOnDaily: false`。生成文に紛れた URL も除去する)。支払いはプリペイドクレジット方式で、残高切れは投稿失敗として現れる。
- **LLM**: 長文生成は「安い `gpt-5.6-luna` で選定 → 高い `gpt-5.6-terra` は絞り込んだ入力で執筆のみ」の 2 段階で入力トークンを桁で節約する(FR-2.2)。日次は 1 回の呼び出しで 3 チャネル分を得る(FR-2.1)。
- **チャット**: 1メッセージあたり quick $0.7 / deep $3 をハード上限とする(`chat_budget_*_usd`)。上限に達したら例外ではなく打ち切り回答になる。壁打ちはツールを使わないため実費のみ。
- **可視化**: 実測トークン数からのコスト概算を投稿(`tokenUsage`)と実行記録(`runs.costUsd`)、チャットは `chatUsage/{YYYY-MM}` に保存し、ダッシュボードで当月合計を表示する。単価表はコード内固定の**目安**であり、実請求は OpenAI ダッシュボードで確認する運用([../runbook.md](../runbook.md))。
- **Gemini**: グラウンディング検索は無料枠(月 5,000 リクエスト)内での利用が前提。超過は「収集 0 件」として現れ、対応は runbook に定める。

詳細: [05-detailed-design/03-generate.md](05-detailed-design/03-generate.md)、[04-parameters.md](04-parameters.md)

#### NFR-3 認証・秘密情報の保護

- **人間 → 管理画面**: IAP(Identity-Aware Proxy。Google アカウントでのログインを強制する門番)。通過できるのは許可メール 1 件のみで、アプリ側にログイン画面は存在しない。
- **管理画面 → pipeline-api**: Google 発行の ID トークン+Cloud Run IAM。pipeline-api は `--no-allow-unauthenticated` でデプロイされ、`admin-sa` 以外の名義は入口(アプリのコードが動く前)で拒否される。**アプリ内の認証コードは意図的に持たない**(コードの docstring に明記された設計判断)。
- **秘密情報**: API キー・トークン 7 件はすべて Secret Manager 管理で、コンテナ起動時に環境変数として注入される。コードにも `.env.example` にも実値は置かない。

受け入れ条件: 上記のインフラ設定(`infra/10-deploy-pipeline.sh` / `11-deploy-admin.sh` / `01-secrets.sh`)が適用されていること。詳細: [05-detailed-design/05-pipeline-api.md](05-detailed-design/05-pipeline-api.md)、[04-parameters.md](04-parameters.md) §6

#### NFR-4 障害の局所化とリトライ方針

- **失敗の隔離単位**: 収集はソース単位と item 単位、生成はカテゴリ単位、公開はチャネル単位。1 つの失敗は記録して次へ進み、他を道連れにしない。
- **API 呼び出しの自動再試行**: 外部 API 呼び出しは tenacity(Python の再試行ライブラリ)による共通ポリシーで最大 3 回試行(指数バックオフ 2〜30 秒)。対象は 429(レート制限)・5xx・通信断のみで、その他の 4xx は即時失敗(`PermanentPublishError`)。1 回のジョブ実行内の再試行であり、二重投稿にならない粒度に限定している。
- **ジョブ自体の再実行**: 投稿を伴うジョブは自動再実行なし(NFR-1)。冪等な collect / seed のみ `--max-retries=1`。

詳細: [05-detailed-design/02-collect.md](05-detailed-design/02-collect.md) §7、[05-detailed-design/04-publish.md](05-detailed-design/04-publish.md) §7、[04-parameters.md](04-parameters.md) §4・§8.5

#### NFR-5 可観測性 — ただし監視は手動

- 全ジョブ実行が `runs` コレクションに記録される(開始・終了時刻、統計、エラー一覧、コスト概算)。クラッシュは `finishedAt` の無い runs ドキュメントとして痕跡が残る。ログは構造化ログとして Cloud Logging に出る。
- 確認手段は管理画面ダッシュボード(FR-4.5)と Cloud Logging。**CI(push 時の自動テスト)と自動監視アラート(メール・チャット等への異常通知)は存在せず、テスト実行(pytest、2026-07-12 時点 50 件)も異常の検知もすべて人が手動で行う**のが現状の as-built である。ダッシュボードの赤帯・赤字警告も「画面を開いたときに見える」受動的な表示にとどまる。

詳細: [05-detailed-design/09-tests.md](05-detailed-design/09-tests.md)、[../runbook.md](../runbook.md)

#### NFR-6 多言語

- **投稿の言語**: `channelConfigs` でカテゴリ×カデンス×チャネル単位に設定でき(`ja` / `ko` / `en`)、既定は x=`ja` / threads=`ko` / notion=`en`(FR-4.2)。設定が無い組み合わせは「無効・`en`」にフォールバックする=投稿されない。
- **管理画面の UI 言語**: ko / ja / en の 3 言語(既定 ko)。URL の言語プレフィックスのみで決まり、ブラウザ言語の自動判定は無効化されている。UI 言語と投稿言語は独立した仕組みである。

詳細: [03-data-model.md](03-data-model.md)、[05-detailed-design/07-admin-ui.md](05-detailed-design/07-admin-ui.md) §8

## 5. FR⇔実装対応表

要件を変更するときは、この表で主担当コードと詳細文書を特定してから着手する(文書更新の起点)。テストの対応は [05-detailed-design/09-tests.md](05-detailed-design/09-tests.md) §5 を併読。

| FR | 主担当コード(ファイル) | 詳細文書 |
|---|---|---|
| FR-1.1 | `pipeline/app/collectors/rss.py`(ループは `pipeline/app/jobs/collect.py`) | [05-detailed-design/02-collect.md](05-detailed-design/02-collect.md) |
| FR-1.2 | `pipeline/app/collectors/gemini_grounded.py` | 同上 |
| FR-1.3 | `pipeline/app/collectors/ieee_xplore.py` | 同上 |
| FR-1.4 | `pipeline/app/normalize.py`、`pipeline/app/repo/items.py`、`pipeline/app/jobs/collect.py` | 同上、[03-data-model.md](03-data-model.md) §4 |
| FR-1.5 | `pipeline/app/collectors/enrich.py`、`pipeline/app/utils/gcs.py` | [05-detailed-design/02-collect.md](05-detailed-design/02-collect.md) |
| FR-2.1 | `pipeline/app/generators/short.py`(入口 `pipeline/app/jobs/generate_short.py`) | [05-detailed-design/03-generate.md](05-detailed-design/03-generate.md) |
| FR-2.2 | `pipeline/app/generators/longform.py`(入口 `pipeline/app/jobs/longform_runner.py`) | 同上 |
| FR-2.3 | `pipeline/app/repo/configs.py`、`pipeline/app/generators/prompts.py`、`admin/src/app/[locale]/prompts/[id]/page.tsx` | 同上、[05-detailed-design/07-admin-ui.md](05-detailed-design/07-admin-ui.md) |
| FR-3.1 | `pipeline/app/publishers/base.py` | [05-detailed-design/04-publish.md](05-detailed-design/04-publish.md) |
| FR-3.2 | `pipeline/app/generators/short.py`(初期状態の分岐)、`pipeline/app/main.py`(承認 API)、`admin/src/components/DraftEditor.tsx` | [05-detailed-design/05-pipeline-api.md](05-detailed-design/05-pipeline-api.md) |
| FR-3.3 | `pipeline/app/main.py`(`retry_channel`)、`admin/src/app/[locale]/posts/page.tsx` | 同上 |
| FR-3.4 | `pipeline/app/publishers/base.py`、`infra/10-deploy-pipeline.sh`(max-retries) | [05-detailed-design/04-publish.md](05-detailed-design/04-publish.md) |
| FR-3.5 | `pipeline/app/publishers/renderer.py`(表示用ミラー `admin/src/lib/textLimits.ts`) | 同上 |
| FR-3.6 | `pipeline/app/publishers/base.py`(`delete_post_channels`)、`pipeline/app/main.py`(`delete_post`)、`admin/src/app/[locale]/posts/` | [05-detailed-design/04-publish.md](05-detailed-design/04-publish.md)、[05-detailed-design/05-pipeline-api.md](05-detailed-design/05-pipeline-api.md) |
| FR-4.1 | `pipeline/app/jobs/refresh_threads_token.py`、`pipeline/app/publishers/threads.py` | [05-detailed-design/06-ops-jobs.md](05-detailed-design/06-ops-jobs.md) |
| FR-4.2 | `pipeline/app/jobs/seed.py` | 同上 |
| FR-4.3 | `admin/src/lib/actions.ts`、`admin/src/lib/data.ts` | [05-detailed-design/07-admin-ui.md](05-detailed-design/07-admin-ui.md) |
| FR-4.4 | `pipeline/app/main.py`(`JOB_MODULES`)、`admin/src/app/[locale]/settings/page.tsx` | [05-detailed-design/05-pipeline-api.md](05-detailed-design/05-pipeline-api.md) |
| FR-4.5 | `admin/src/app/[locale]/page.tsx`、`admin/src/lib/data.ts` | [05-detailed-design/07-admin-ui.md](05-detailed-design/07-admin-ui.md) |
| FR-5.1 | `pipeline/app/chat/graph.py`(`chat_respond`)、`pipeline/app/chat/prompts.py`、`admin/src/components/chat/ChatView.tsx` | [05-detailed-design/11-research-chat.md](05-detailed-design/11-research-chat.md) |
| FR-5.2 | `pipeline/app/chat/graph.py`、`pipeline/app/chat/api.py`(SSE)、`admin/src/app/api/chat/stream/route.ts` | 同上 |
| FR-5.3 | `pipeline/app/chat/api.py`(`handoff`)、`pipeline/app/generators/{short,longform}.py`(seed)、`pipeline/app/research/prompts.py`(`build_seed_block`) | 同上 |

NFR の実装位置は第 4 章の各節に記した(NFR-1 = `publishers/base.py` + infra、NFR-4 = `pipeline/app/utils/retry.py` ほか)。

## 6. 制約と前提

本システムの要件・設計判断の背景にある外部制約。ここが変わると第 3〜4 章の要件も見直しになる。

| # | 制約・前提 | 内容と要件への影響 |
|---|---|---|
| 1 | 組織なし GCP | IAP は本来 Google Workspace 組織向けの機能のため、カスタム OAuth クライアントを `gcloud iap settings set` で適用して使っている(適用済み)。IAP が使えなくなった場合の代替案(NextAuth)は [../runbook.md](../runbook.md) に記載 |
| 2 | X の投稿は従量課金 | 1 投稿 $0.015、URL 付き投稿は $0.20(約 13 倍)。プリペイドクレジット方式で残高照会 API は無く、残高切れは投稿失敗として現れる。→ 日次 X は既定 URL なし(NFR-2)、既定運用のコスト目安は月 $5 前後([../setup-credentials.md](../setup-credentials.md)) |
| 3 | Threads トークンは約 60 日で失効 | 放置すると Threads への投稿だけが全滅する。→ 週次自動更新(FR-4.1)で約 8 倍の余裕を確保。完全失効時の再発行手順は [../runbook.md](../runbook.md) |
| 4 | Gemini グラウンディングのキー制約と無料枠 | API キーは GCP プロジェクト内で発行したものが必須(AI Studio 発行キーは別の無課金プロジェクトに紐づきグラウンディングに使えない)。無料枠は月 5,000 リクエストで、超過時は収集 0 件として現れる |
| 5 | IEEE Xplore キーは任意 | 無料枠は 1 日約 200 コール。キー未設定でもシステム全体は動く(該当ソースが 0 件になるだけ。FR-1.3) |
| 6 | GCS 署名 URL の IAM 前提 | Threads の画像添付は署名 URL(期限付き公開 URL)方式で、pipeline-sa 自身への `serviceAccountTokenCreator` 付与が前提。外すと画像添付だけが静かに失敗する(投稿自体は続行) |
| 7 | スケジュールは Cloud Scheduler が正 | 実行時刻(JST)は `infra/20-schedulers.sh` の cron 式で決まる。Firestore の `timezone` 設定は表示用で、実行時刻を変えない |
| 8 | 本番環境変数のドリフト | 本番ジョブには `GEMINI_MODEL` 等の手動 env 上書きが入っている場合があり、`pipeline/app/config.py` のデフォルトと乖離し得る。モデル名を扱う要件変更時は両方を確認する([04-parameters.md](04-parameters.md) §4.4) |

## 7. 明示的な非要件(実装していないこと)

以下は「未完成」ではなく、**現時点で意図的に実装していない**事項である。完成済み文書・コードで確認できる現状の事実を根拠として併記する。

| # | 非要件 | 現状の事実(根拠) |
|---|---|---|
| 1 | 複数ユーザー・権限分離 | IAP を通過できるのは 1 メールアドレスのみで、通過者は全員フル権限(画面・操作の権限分岐なし)。承認者の記録(`approvedBy`)は監査用であり認可には使わない([05-detailed-design/07-admin-ui.md](05-detailed-design/07-admin-ui.md) §7.3) |
| 2 | 複数 SNS アカウント・複数テナント運用 | 各チャネルの認証情報は Secret Manager に 1 組のみ([04-parameters.md](04-parameters.md) §3) |
| 3 | リアルタイム収集・即時投稿 | 収集は 1 日 1 回、生成・投稿は定時のバッチ。Webhook・ストリーミングの実装はない([04-parameters.md](04-parameters.md) §5) |
| 4 | 投稿の自動リトライによる再実行 | 投稿系ジョブは `--max-retries=0` で、失敗チャネルの再実行は管理画面からの手動操作のみ(NFR-1、FR-3.3)。「自動で何度でも投げ直す」機能は二重投稿リスクのため持たない |
| 5 | CI/CD | push 時の自動テスト・自動デプロイは無い。テストは手動 pytest、デプロイは gcloud スクリプトの手動実行([05-detailed-design/09-tests.md](05-detailed-design/09-tests.md))。admin にはテストスクリプト自体が無い(`typecheck` のみ) |
| 6 | 自動監視アラート | 異常のプッシュ通知(メール・チャット等)は無い。検知は管理画面の表示と Cloud Logging の手動確認(NFR-5) |
| 7 | 生成品質の自動検証 | 生成系(LLM 呼び出し部)の自動テストは無く、「変な文章を作らないか」は承認フロー(週次・月次)と事後確認(日次)という人の目で担保する([05-detailed-design/09-tests.md](05-detailed-design/09-tests.md) §6) |
| 8 | 投稿の予約・時刻指定 | 承認するとその場で同期公開される。公開時刻の指定・予約キューは無い([05-detailed-design/05-pipeline-api.md](05-detailed-design/05-pipeline-api.md)) |
| 9 | A/B テスト・効果測定 | 投稿のエンゲージメント(閲覧・反応)を収集・分析する機能は無い。ダッシュボードが扱うのはコスト・実行履歴・投稿状態のみ(FR-4.5) |
| 10 | データの保持期間管理 | `items` / `posts` / `runs` の**期間ベースの**自動削除・アーカイブは無い(下書きの 30 日クリーンアップと、管理画面からの手動の投稿削除 FR-3.6 は別)。 |
| 11 | `skipped` チャネルの復活 | 公開時にチェックを外したチャネルは確定的に `skipped` となり、API から再有効化する手段は無い(FR-3.2) |

これらを将来実装する場合は、本書の該当章(多くは NFR-1 / NFR-5)と第 5 章の対応表を必ず更新すること。
