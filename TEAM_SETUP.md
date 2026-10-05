# Team & Repo Setup Notes

Internal reference for the 5-person team sharing this laptop. Not a public-facing doc — trim before wider release.

## Org & repo
- Org: `genai-project-org` (placeholder name, real brand name TBD — see `project.config.json` once added)
- Repo: `genai-project-org/genai-project` — **public** (deliberate choice, to get free GitHub branch protection on `main`; keep this in mind before ever committing `.env` files, API keys, or credentials)
- Branch protection on `main`: no force-push, no branch deletion, 1 required PR approval. Repo admins (Bose-Siddharth) are currently exempt from the PR requirement and can push directly.

## People & SSH identities (shared laptop)
| Person | GitHub username | SSH host alias |
|---|---|---|
| Siddharth (owner) | Bose-Siddharth | `github-genai` |
| Rahul | nomadicrahul | `github-rahul` |
| Vishal | KumarVishalDas | `github-vishal` |
| Ashwani | Kashwanimishra | `github-ashwani` |
| Ranjeet | Kmr-Ranjeet | `github-ranjeet` |

A 5th collaborator (Siddharth's friend) will join later — not yet invited.

Each person's key is already on this laptop (`~/.ssh/id_<name>`) and registered to their own GitHub account. Clone/remote URLs use the alias, e.g. `git@github-rahul:genai-project-org/genai-project.git`.

## Commit identity workflow
This is **one shared local clone**, not separate clones per person. Before every commit/push:
1. Set local identity to whoever is committing: `git config user.name "<github-username>"` and `git config user.email "<their-invite-email>"`
2. Push using their SSH alias
3. Switch back to the resting default afterward: `git config user.name "Bose-Siddharth"` / `git config user.email "siddharth.bose@iemlabs.com"`

If you're a fresh Claude Code session picking this repo up: always ask whose name a push should go under, don't assume.

## Structure
- `apps/api` — FastAPI backend (from IEMA_AI_API_V3, history preserved)
- `apps/web` — React web app (from supercreater-ai-frontend/frontend, history preserved)
- `apps/mobile` — Expo mobile app (from supercreater-ai-frontend/mobile, history preserved)

## Proposed refactor (post-migration cleanup)

Priority order, low-risk items first:

1. **Consolidate `.gitignore`** — currently 3 scattered/messy ones inherited from the old repos (the web one has literal duplicate entries). Replace with one root `.gitignore` covering Python + Node + mobile.
2. **Kill duplicate lockfiles** — `apps/web` has both `yarn.lock` and `package-lock.json`. Keep yarn (matches mobile), delete the other.
3. **Remove Emergent.sh leftovers** — `.emergent/`, `test_result.md` (an agent-protocol file, not real docs), stale `test_reports/` iteration logs. Dead weight from the old third-party dev platform this was scaffolded on.
4. **`project.config.json` at root** — single source of truth for the brand name (currently "GenAI Project" placeholder), so a future rename is a one-file change instead of a codebase-wide find/replace.
5. **Root workspace setup** — a root `package.json` with Yarn workspaces for `apps/web` + `apps/mobile` (`apps/api` is Python, stays independent). Groundwork for shared scripts/tooling later.
6. **Pin Python version for `apps/api`** — currently unpinned, relies on whatever the old Elastic Beanstalk platform happened to run. Needs a `Dockerfile` or `.python-version` before containerizing.
7. **Fix or remove the dead `buildspec.yml`** — references a `Backend/` folder that doesn't exist anywhere in this repo. Leftover from the pre-merge state.
8. **Root README rewrite** — still has placeholder text, needs to describe the actual monorepo layout.

Items 1–3 and 4 are near-zero-risk and can be done anytime without discussion. Items 5, 6, 7 each need one small decision first (workspace tool choice, target Python version, whether to fix vs. delete buildspec).

## Longer-term items (from the original AWS/monorepo assessment)
- Move `apps/api` off Elastic Beanstalk to ECS Fargate (or keep EB — undecided)
- Database: MongoDB Atlas vs. DocumentDB (undecided)
- SEO: `apps/web` currently has zero SEO infra (no meta tags, sitemap, robots.txt, no SSR) — needs a real decision on investment level (full Next.js rewrite of public pages / prerendering layer / minimum-viable fix)
- Full AWS build/deploy scripting (currently no working CI/CD for any of the three apps)
- Final business name decision — still open, several fully-available candidates were vetted (see prior naming discussion)
