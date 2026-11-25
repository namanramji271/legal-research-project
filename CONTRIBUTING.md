# Contributing

This project is maintained by two people. Use pull requests so each change gets
a second review and `main` stays stable.

## Workflow

1. Never commit directly to `main`.
2. Pull the latest changes before starting work: `git pull`.
3. Create one branch per task, using `feat/`, `fix/`, or `chore/` (for example,
   `feat/case-reranker`).
4. Keep commits small and focused on one task.
5. Open a pull request and have the other contributor review it before merging.
6. Never commit `.env` files, generated data, or index files. This includes
   judgment corpora, SQLite databases, ChromaDB directories, and user databases.
7. Edit `AGENTS.md` only when needed, in a small, separate pull request.

## Ownership

- **Venkatesh:** retrieval, evaluation, and the paper.
- **Naman:** frontend and deployment.

Coordinate changes that cross these areas in the pull request description and
request review from the owner of the affected area.
