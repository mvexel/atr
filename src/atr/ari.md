
## ari (Livemap's relay and Library)

`ari` is on this machine. Use it to reach teammates' agents and the team Library; `ari <command> --help`
has every option. Approving, declining and trusting relay messages are the owner's, on the ari site:
never do them yourself; tell the owner when something waits.

1. Ask a teammate's agent: `ari relay people` (handles), then `ari relay send <handle> "<question>" --json`,
   with `--asset <id>` per file it needs. Write a question, not a task: their agent reads and answers but
   changes nothing. Then hand the conversation to atr so the answer comes back to you as news:
   `atr relay <id> --on T3` (the id `send --json` printed). Answer a message with `ari relay reply <id> "..."`.
2. Inbox and outbox: `ari relay inbox --held` (what waits for the owner's approval), `ari relay sent`
   (what you sent, and whether it was delivered), `ari relay conversation <id>` (both ways). Reading
   changes nothing. Never put credentials in a relay message.
3. Library assets come in five kinds: video, image, html (pages), markdown (docs) and file (anything else).
4. Create and share: `ari asset publish <file> --title "..."` (the team sees it; `--private` keeps it the
   owner's; `--tag showroom` puts it in the showroom); `ari asset write --file <path|-> --title "..."` for
   a Markdown doc or page; `ari asset share <id>` / `unshare <id>`; `ari asset tag <id> <tag>`.
   Attach what you publish for the owner: `atr attach T3 <its link>`.
5. Search: `ari asset list --search "<words>"` (add `--kind`, `--by "<name>"`, `--tag`), then
   `ari asset read <id>` for a doc or page, `ari asset download <id>` for anything else.
