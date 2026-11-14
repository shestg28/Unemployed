# Agent Rules

## Stack
TBD (placeholder — fill in once the problem statement is known)

## AWS
- Region: `ap-south-1`
- Credentials come from `.env` only. Never hardcode them. Never commit them.

## Folder ownership
Agents must not write outside their folder.

| Path             | Owner |
|------------------|-------|
| `/pipeline`, `/api` | A |
| `/web`           | C |
| root, config     | B |

## Rules
- Read `CONTRACT.md` before any change.
- Never change an interface defined in `CONTRACT.md`.
- No new dependencies without asking B.
- No refactoring shared files.
- Small commits. Push every 20 minutes.

## Do not
- Do not write outside your folder.
- Do not edit `CONTRACT.md` interfaces.
- Do not add dependencies without B's OK.
- Do not hardcode or commit secrets.
- Do not refactor shared files.
- Do not make big, rare commits.
