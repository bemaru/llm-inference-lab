# Repository Guidance

## Scope

- Keep this repository limited to general serving/benchmark code, reusable
  examples, and reviewed, sanitized performance records.
- Active product integrations and private operations belong in their owning
  repositories. Completed internal work records belong in a private archive.
- Never commit credentials, internal endpoints, private host/user paths, raw
  prompts/responses, or host-specific logs. Keep raw artifacts outside Git.
- Preserve evidence provenance and measurement limitations. Sanitizing a profile
  changes its hash; do not rewrite historical recipe IDs or source hashes to
  make them match a sanitized copy.
- Check third-party provenance and redistribution terms before adding artifacts.
  License and contribution-policy decisions require explicit owner approval.

## Change and publication workflow

- Before editing, check the checkout path, Git remote, branch, and worktree status.
  Preserve unrelated changes and stage only the intended files.
- For material coming from a private source, select and sanitize files manually,
  review their contents and diff, and record source provenance privately. Do not
  merge private history, mirror folders, or automatically synchronize repositories.
- Before committing or pushing, review the staged diff for sensitive content,
  raw data, provenance, and scope; `.gitignore` is not a disclosure review.
- Run the applicable [local checks](README.md#local-checks) and verify changed
  documentation links. State which checks ran and any unverified limits.
- Starting services, uploading run data, and publishing changes require user
  authorization; ordinary edits or a review request do not authorize those actions.
