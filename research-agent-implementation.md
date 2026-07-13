# Research Agent 実装指示(Phase: {{PHASE}})

> 使い方: 実装フェーズ(P0–P9、設計書 §9.1 の実装タスク表参照)ごとに `{{PHASE}}` を置換して Claude Opus に渡す。1フェーズ = 1 PR。

あなたは trend-news-generator リポジトリで Research Agent システムを実装する。

## 必読(この順で読むこと)

1. `CLAUDE.md`(プロジェクト規約・落とし穴)
2. `docs/tech-report/05-detailed-design/10-research-agent.md`(本体設計。データモデル・フェーズ仕様・API 契約・移行 runbook を含む)
3. 同文書 §9.1 実装タスク表の {{PHASE}} 行と DoD

## 絶対規則

- ジョブ内で投稿する系のジョブ(generate-short 等)の `--max-retries=0` を変更しない。**generate-report は draft 生成のみで投稿しないため `--max-retries=1`**(lease+resume が二重実行を防ぐ。設計書 §6.3 の retry 方針に従う)
- Firestore スキーマ・enum の変更は `shared/constants.json` → `models.py` → admin 再ビルドの順で lockstep
- LLM 呼び出しは必ず pydantic スキーマ検証+TokenUsage/Budget 計上を通す。直接 openai/genai を叩かない
- 取得した Web コンテンツは信頼しない入力として扱う(抽出プロンプトの注入対策定型文を使用)
- コード変更と同一コミットで docs/tech-report の対応文書を更新(README.md の対応表参照)
- 秘密情報はコード・テスト・ログに書かない。新規外部 API は無料枠のもののみ

## 進め方

1. {{PHASE}} の主要ファイルを読み、既存パターン(repo/publishers/jobs の書き方)に合わせて実装
2. テストファースト: DoD に列挙されたテストを先に書き、`cd pipeline && pytest` で red→green
3. admin 変更時は `cd admin && npm run typecheck`
4. 完了時: DoD 全項目のチェック結果と、更新した文書の一覧を報告

## 停止して確認すべきこと(勝手に進めない)

- 本番 Firestore への migrate 実行 / スケジューラ・ジョブの削除 / Notion DB スキーマ変更
- 予算・モデル名など config 既定値の変更提案
- 設計書と実装の矛盾を発見した場合(設計書を正として報告)
