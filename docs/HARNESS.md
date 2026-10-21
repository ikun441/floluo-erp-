# Harness integration

2026-10-20: re-read the repaired dsh-delegator skill. Default host-side Bailian broker keeps provider credentials outside the DSH child, binds an ephemeral loopback port and restricts sandbox outbound access to that port. Existing skill validation records report a successful live model and reviewed fixture edit. This is not yet proof of a successful ERP task.

ERP delegation: exact docs/GLOSSARY.md path only, three non-sensitive design documents as context, no runtime template or broad gateway_network override. Codex reviews the complete patch and runs trusted checks before digest-gated application. Provider keys are never included in project files or prompts. The temporary broker is accessible to other local processes during its lifetime; it is not a multi-user service.

ERP first real task result: dry-run passed; five upstream HTTP 200 responses; no final event before the 180-second deadline. Result takeover_required / timeout, no target file created and nothing merged. Codex takes over the glossary task. This proves route connectivity, not successful ERP delegation.

Catalog fixture task: first candidate had no changes and was rejected. One corrected attempt produced exactly the authorized JSON file with eight cases. The patch reviewer rejected its missing final newline, as designed. Codex reviewed all data, checked all eight outcomes against the actual ProductInput schema and boundary lengths, then took over canonical JSON serialization with a newline. No automatic patch was applied and no review rule was relaxed. A private review receipt retains the original artifact SHA256.

Procurement boundary fixtures: used an independent clean source worktree so core implementation could continue without changing the delegated source revision. First attempt lacked an exported parent directory and created no target. Its trusted check also exposed that runtime/bin/node requires a desktop-only environment variable. The second and final attempt exported one safe JSON context to provision the directory and selected the actual Electron executable in Node mode. It produced exactly the intended 12 cases, but the reviewer rejected the missing final newline before running checks. No automatic patch was applied. Codex inspected the entire JSON, validated all 12 expected outcomes against the real LineInput schema, and took over canonical serialization. The original and normalized hashes are retained in a private review receipt. The JSON does not contain business records or credentials. No sandbox rules were relaxed.

v1.0.3 message UI: an isolated exact-file task timed out at300 seconds; report remained takeover_required, not a successful candidate. A complete MessagingView.tsx was present in the retained worktree. Codex read the entire untrusted file, took over integration, corrected hidden-field guards and password/one-time-secret handling, then ran project TypeScript, formatting, build and real-browser checks. No report status was altered and no digest-gated auto-apply was used; a private SHA256 receipt records the original partial artifact. The timeout is not counted as successful Harness execution. Further retries for this task were stopped.

v1.0.4 OperationsView: an exact-file isolated task timed out at240 seconds and no candidate existed. Codex took over implementation, with no automatic retry or relaxed sandbox. The task was not counted as successful delegation. Core migration, preview/confirmation authorization and transactions remained with Codex.


离线规则样例任务：2026-10-21，精确授权tests/fixtures/local_intent_cases.json，180秒超时，两个上游200响应，无候选文件。未应用任何DSH产物，也未放宽沙箱或重试；Codex接管有边界的样例与可信回归测试。此任务不计为成功委派。


v1.0.5回执样例任务未得到可审查报告或候选文件，未采用任何产物，不计为成功委派；没有放宽隔离。最终回执、连接、并发和权限测试由Codex实现并真实运行。


v1.0.6销售金额样例：精确授权tests/fixtures/sales_amount_cases.json，隔离dry-run通过。headless返回needs_codex_review，但review实际changed为空，指定JSON检查退出69，tests_passed=false；未应用候选、未调整报告或隔离。Codex接管八例样本与真实金额校验，不计为成功委派。
