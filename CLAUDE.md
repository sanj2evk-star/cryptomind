# CryptoMind — Project Instructions

## Version Update Workflow

After applying any version update prompt from the user:

1. **Review** the changes for correctness and completeness
2. **Provide a summary** of what was done, what could be improved, and suggestions
3. **Ask the user** if there are any more updates to add, any minor tweaks or adjustments before deploying
4. **Ask the user for permission** before deploying (push to Render)
5. **Update `UPDATE_LOG.md`** at the project root with the version entry including: date, commit hash, what changed, what's right, what could be improved, and deployment status

Always maintain `UPDATE_LOG.md` as a running record of all updates.

## Deployment Rules

- CryptoMind runs as a **web app only** (deployed on Render)
- Desktop app was removed in v7.6.3 — no Electron, no local packaging
- Always **ask permission** before pushing
- Build steps: `cd frontend && npm run build`, git commit + push to `main` for Render auto-deploy
