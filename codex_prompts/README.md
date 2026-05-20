# Codex Prompts History

This directory keeps the original Codex prompts that were used to implement
`server-backup` PR by PR.

These files are preserved for:

- maintenance history
- implementation traceability
- future audits of design and delivery decisions

They are **not** required for a normal installation or for day-to-day
operations. A new user should install the code and follow the runbooks under
`../docs/`, not replay the prompts.

Historical PRD source documents are now stored under `../prd/`.

Implementation order that was used historically:

```text
01_PR01_PR02_PR27_INITIAL_SETUP.md
02_PR03_CONFIG_LOADER_VALIDATORS.md
03_PR04_GLOBAL_SETUP_WIZARD.md
04_PR05_SFTP_TARGET_WIZARD.md
05_PR06_PROFILE_WIZARD.md
06_PR07_RESTIC_REPOSITORIES.md
07_PR08_BACKUP_MULTI_TARGET.md
07B_PR08_HOTFIX_INTERRUPT_HANDLING.md
08_PR09_RETENTION_PRUNE.md
09_PR10_RESTORE_TEST.md
10_PR11_EMAIL_REPORTS.md
11_PR12_COVERAGE_AUDIT.md
12_PR13_DB_WIZARD_DUMPS.md
13_PR14_DOCKER_PROFILE_COVERAGE.md
14_PR15_DEPLOYMENT_RUNBOOK.md
14_PR16_PRODUCTION_HARDENING_SCHEDULING.md
15_PR17_FINAL_VALIDATION_RELEASE.md
16_PR18_REPOSITORY_CLEANUP_V1.md
```
