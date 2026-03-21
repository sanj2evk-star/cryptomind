# CryptoMind — Project Instructions

## Version Update Workflow

After applying any version update prompt from the user:

1. **Review** the changes for correctness and completeness
2. **Provide a summary** of what was done, what could be improved, and suggestions
3. **Ask the user** if there are any more updates to add, any minor tweaks or adjustments before deploying
4. **Ask the user for permission** before deploying (build Mac app + push to Render)
5. **Update `UPDATE_LOG.md`** at the project root with the version entry including: date, commit hash, what changed, what's right, what could be improved, and deployment status

Always maintain `UPDATE_LOG.md` as a running record of all updates.

## Deployment Rules

- Every update must be deployed to **both** Mac desktop app and Render (web/iPad)
- Always **ask permission** before building and pushing
- Build steps: `cd frontend && npm run build`, `cd desktop && npm run build:mac`, git commit + push to `main` for Render auto-deploy
