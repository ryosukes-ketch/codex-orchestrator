
## Purpose
Template for recording actual staging execution in a repeatable, reviewable format.

## Run metadata
- Execution ID: staging-2026-03-30-01
- Date (JST/UTC): 2026-03-30 JST
- Environment name: ローカル検証環境
- Candidate version/tag: D:\codex 現在版（pytest 824 passed 時点）
- Commit SHA: なし（Git未使用）
- Operator(s): 石津凌佑
- Reviewer(s): 未定
- Related plan:
  - `docs/staging_validation_plan.md`
  - `docs/live_validation_checklist.md`

## Execution context
- Runtime config profile: ローカル既定設定
- Auth mode/profile: 未確認
- Provider mode/profile: 未確認
- Persistence mode/profile: 未確認
- Special flags/overrides used: なし
- Known limitations at start:
  - Git 管理なし
  - live provider 未検証
  - real auth 未検証
  - real persistence 未検証

## Step-by-step log
| Step # | Area | Procedure executed | Expected result | Actual result | Status (Pass/Fail/Blocked) | Evidence link |
|---|---|---|---|---|---|---|
| 1 | Startup | アプリ起動確認を行う | 起動エラーなく開始できる | 未実施 | Blocked |  | 
| 2 | Auth |  |  |  |  |  |
| 3 | Provider |  |  |  |  |  |
| 4 | Persistence |  |  |  |  |  |
| 5 | Manual workflow |  |  |  |  |  |
| 6 | Rollback rehearsal |  |  |  |  |  |

## Result summary
- Overall status: Pass / Conditional Pass / Fail
- Blocking findings:
- Non-blocking findings:
- Deviations from plan:

## Requirement and AC impact summary
| Finding ID | Requirement ID | Acceptance criterion | Impact summary | Go/No-Go impact |
|---|---|---|---|---|
|  |  |  |  |  |

## Signoff tracking
- Auth owner:
- Provider owner:
- Persistence owner:
- Rollback owner:
- Release decision owner:

## Final staging recommendation
- Recommendation: Go / No-Go / Re-test
- Decision timestamp:
- Decision rationale:
- Follow-up actions:


- 2026-03-31 Auth確認: /orchestrator/resume/approval に Bearer dev-approver-token で認証成功。waiting_approval -> completed を確認。project_id=539bd928-4b5b-4c96-b6b4-5ac7cf132b73

- 2026-03-31 tests/test_api.py: 53 passed。Auth付き approval resume と API 全体テスト成功。

- 2026-03-31 ruff check .: All checks passed。git status は D:\codex が Git リポジトリではないため未実施。

- 2026-03-31 reject -> resume/revision -> replanning/start を手動確認。project_id=db745c1b-de43-4dcd-a8d5-c891eba9a41a は最終的に completed。

- 2026-03-31 全テスト実行: 826 passed, 1 skipped in 13.50s。approval / reject / revision / replanning の手動確認後も全体テスト成功。

- 2026-03-31 artifact重複修正: replanning/start 後に同一artifact idをupsertするよう修正。test_resume_revision_then_start_replanning に artifact_count=4 と重複なし確認を追加。pytest -q は 826 passed, 1 skipped、ruff check . は All checks passed。

- 2026-03-31 approval checkpoint更新修正: approval/reject時に checkpoint-approval-{project_id} を判断結果で更新するよう修正。関連テスト追加後、tests/test_api.py は 53 passed、pytest -q は 826 passed, 1 skipped、ruff check . は All checks passed。

- 2026-03-31 intake改行正規化修正: PowerShell由来の backtick newline (
 / 
) を intake で正規化する helper を追加。test_intake_brief_normalizes_powershell_backtick_newlines を追加。tests/test_api.py は 54 passed、pytest -q は 827 passed, 1 skipped、ruff check . は All checks passed。

- 2026-03-31 dry_run_orchestration改行正規化回帰テスト追加: test_run_dry_run_orchestration_normalizes_powershell_backtick_newlines を追加。pytest -q と ruff check . まで通過。

- 2026-03-31 dry_run_orchestration改行正規化回帰テスト確認: targeted dry_run test / full pytest / ruff を再実行して通過確認。

- 2026-03-31 dry_run_orchestration改行正規化回帰テスト修正: CurrentBriefArtifact 経由のため current_brief.brief.* を参照するよう訂正。targeted dry_run test / full pytest / ruff を通過確認。

- 2026-03-31 dry_run_orchestration改行正規化回帰テスト修正: CurrentBriefArtifact の内部構造依存をやめ、model_dump_json() に対する文字列検証へ変更。pytest -q / ruff check . を再通過確認。

- 2026-03-31 バックアップ整理: *.bak_* を削除。削除後に pytest -q / ruff check . を再実行し、グリーン維持を確認。

- 2026-04-01 approval request uniqueness固定: partial idempotent API test に approval_requested / approvals の action_type 重複なし assert を追加。pytest -q tests/test_api.py / pytest -q / ruff check . を通過確認。

- 2026-04-01 service層 approval uniqueness 固定: tests/test_orchestrator.py の partial idempotent test に approval_requested / approvals の action_type 重複なし assert を追加。tests/test_orchestrator.py / pytest -q / ruff check . を通過確認。

- 2026-04-01 lint修正: tests/test_orchestrator.py の approval uniqueness assert を改行して E501 を解消。pytest -q / ruff check . の再通過を確認。

- 2026-04-01 line ending hygiene: .gitattributes を追加して LF/CRLF を固定。git add --renormalize . 実施後、pytest -q / ruff check . を通過確認。

- 2026-04-01 18:08:50 full live flow確認: .\scripts\live-smoke.ps1 / .\scripts\release-readiness.ps1 -SkipVerify を実行。
  approval project_id=539bd928-4b5b-4c96-b6b4-5ac7cf132b73
  reject/revision/replanning project_id=db745c1b-de43-4dcd-a8d5-c891eba9a41a
  Authorization=Bearer dev-approver-token
  結果: successful full live flow smoke

- 2026-04-01 18:14:16 full live flow再検証: 旧ID 539bd928-4b5b-4c96-b6b4-5ac7cf132b73 / db745c1b-de43-4dcd-a8d5-c891eba9a41a は audit 404 のため現行サーバー状態では再利用不可。
  approval old project_id=539bd928-4b5b-4c96-b6b4-5ac7cf132b73
  reject/revision/replanning old project_id=db745c1b-de43-4dcd-a8d5-c891eba9a41a
  approval seed project_id=c216da0c-3081-4984-b7f4-b6944acaff3b status=completed
  recovery seed project_id=b0fd49e8-c0b2-4d8e-98ec-5a957e11cdd3 status=revision_requested
  Authorization=Bearer dev-approver-token
  結果: failed full live flow smoke with fresh seed projects: Flow failed for resume-approval: 409 {"detail":"Project is not in waiting_approval state (current: completed)."}

- 2026-04-01 18:23:08 full live flow最終検証: deterministic seed で再実行。
  approval seed project_id=5e9e5c95-269e-4d39-b922-08e6ced25206 status=waiting_approval trend_provider=gemini-flash-lite-latest
  recovery seed project_id=47d277f5-8cf7-4789-bf83-5c5052a8f1de status=revision_requested trend_provider=mock simulate_review_failure=true
  Authorization=Bearer dev-approver-token
  結果: failed full live flow smoke with deterministic approval/recovery seeds: Flow failed for approval-reject: 409 {"detail":"Cannot reject non-pending action(s): external_api_send"}

- 2026-04-01 18:27:45 reject→revision→replanning live chain確認: fresh waiting_approval seed で実行。
  project_id=75b8ff3a-1b84-4e5a-bd02-27edde7b3308
  trend_provider=gemini-flash-lite-latest for reject seed
  flow=approval/reject -> resume/revision -> replanning/start
  Authorization=Bearer dev-approver-token
  final_status=completed
