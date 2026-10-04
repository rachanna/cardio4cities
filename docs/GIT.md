# Git Setup and Workflow

Do sections 1–5 once, before task D1-1 in `docs/design/BUILD_PLAN.md`.

## 1. One-time machine setup

```bash
git config --global user.name "Rachanna Jakkali"
git config --global user.email "<your GitHub email>"
git config --global init.defaultBranch main
gh auth login          # GitHub CLI; choose SSH, or use an existing SSH key
```

## 2. Create the repository

Private while building; shared or made public at submission (§9).

```bash
gh repo create cardio4cities --private --clone
cd cardio4cities
```

## 3. `.gitignore` first

Create it before adding anything else, so secrets and large downloads can never be committed.

```gitignore
# secrets
.env
.env.*
!.env.example
# python
.venv/
__pycache__/
*.pyc
.mypy_cache/
.ruff_cache/
.pytest_cache/
# web
web/node_modules/
web/.next/
web/out/
# large reference downloads
reference/geonames/*.txt
reference/geonames/*.zip
# local
.DS_Store
*.log
```

## 4. Add the design pack and make the first commit

```bash
unzip ~/Downloads/cardio4cities-design-pack.zip -d /tmp/pack
cp -r /tmp/pack/cardio4cities/. .
git add .gitignore CLAUDE.md docs/
git commit -m "docs: design pack (requirements, HLD, LLD, build plan, decisions)"
git push -u origin main
```

## 5. Secret scanning on every commit

One leaked API key on a shared repository can cost money within minutes.

```bash
pip install pre-commit      # or: uv tool install pre-commit
```

`.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.21.2            # use the latest release tag
    hooks:
      - id: gitleaks
```

```bash
pre-commit install
git add .pre-commit-config.yaml
git commit -m "chore: secret scanning on commit"
```

Claude Code adds ruff and the import-lint check to this file in task D1-1.

CI runs the same scanner (same version) over the whole history on every push, so a
commit made without the hook is still caught (BD-36).

## 6. Branches and commits

| Rule | Example |
|---|---|
| One branch per build task, named after it | `git switch -c day1/D1-1-scaffold` |
| Commit messages start with the task ID | `D1-3: migrations for claims and verdicts` |
| Merge into `main` only when `poe lint` and `poe test` pass | then delete the branch |
| Spike results go into `docs/DECISIONS.md` in the same merge as the spike script | `D1-5: S-1 Graphiti triplets spike, BD-01` |
| Design changes go into `docs/DECISIONS.md` in the same commit as the code | never a separate "update docs later" commit |

## 7. Protect `main`

GitHub → Settings → Branches → add a rule for `main`:

- Require the CI status check to pass before merging (the workflow is created in D1-1)
- Block force pushes
- Block deletion

## 8. Connect Render (task D1-4)

- Install Render's GitHub app for this repository only.
- Create the services from `render.yaml`.
- **Auto-deploy off** (R-91): deploy by hand from the Render dashboard, so nothing redeploys during a rehearsal or the demo.

## 9. Submission

```bash
git tag -a v1.0-submission -m "Case study submission"
git push origin v1.0-submission
```

Then either make the repository public, or add the panel's GitHub accounts as read-only collaborators (Settings → Collaborators). The tag shows exactly what was submitted, even if work continues afterwards.

**Before sharing, check:**

```bash
gitleaks detect                 # scans the whole history, not just new commits
git log --all -- .env           # must print nothing
```

If either finds something: rotate the exposed key with its provider first, then remove it from history before sharing.
