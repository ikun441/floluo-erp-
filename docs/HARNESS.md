# Harness integration

2026-10-20: re-read the repaired dsh-delegator skill. Default host-side Bailian broker keeps provider credentials outside the DSH child, binds an ephemeral loopback port and restricts sandbox outbound access to that port. Existing skill validation records report a successful live model and reviewed fixture edit. This is not yet proof of a successful ERP task.

ERP delegation: exact docs/GLOSSARY.md path only, three non-sensitive design documents as context, no runtime template or broad gateway_network override. Codex reviews the complete patch and runs trusted checks before digest-gated application. Provider keys are never included in project files or prompts. The temporary broker is accessible to other local processes during its lifetime; it is not a multi-user service.
