# Pending changes to protected files

Each `.patch` here changes a protected file and waits for the owner's named yes. None is applied by an agent.
Check one with `git apply --check docs/pending-protected/<name>.patch` and apply it with `git apply`.

## `cf-gateway-off.patch` (`.github/workflows/deploy.yml`)

Adds `CF_GATEWAY=off` to the Cloud Run `--set-env-vars` line, which switches off the OpenRouter free lane
(see `docs/privacy-gateway.md`). The patch replaces that whole line, so it stops applying if anything else on
the line changes first. The equivalent by hand:

- append `,CF_GATEWAY=off` to the end of the `--set-env-vars` value in `deploy.yml`; or
- run `gcloud run services update <service> --region <region> --update-env-vars CF_GATEWAY=off`, and also make
  the `deploy.yml` change, or the next deploy sets the env list again without it.

Once it is live, update `docs/privacy-gateway.md`: the `CF_GATEWAY` row under "Gateway lane configuration"
becomes `off` with the date, and the "In short" and "The OpenRouter lane" sections drop "still on".

## `claude-md-gateway-wording.patch` (`CLAUDE.md`)

Brings the gateway bullet in line with the privacy record: the OpenRouter free model is "probably dead
(unverified)" rather than stated as dead, and the Kernal router is named as run by a family member of CF's
developer, not by CF, with no processing agreement on file.

## `badges-readinglist.patch` (`run.py`)

See PR #226.
