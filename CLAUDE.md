# Working on this repository

A single-purpose bot: log in to a Discuz! forum with a username and password, submit the `dsu_paulsign` daily check-in with a random mood, exit. `sign.py` is the entire implementation; the two workflows in `.github/workflows/` schedule it and keep the repository from going dormant.

## Hard rules

Never commit the target forum's name, domain, or any other identifier, in code, comments, documentation, workflow files, or commit messages. The forum is supplied at runtime through the `DZ_BASE_URL` secret and must stay there. Use neutral placeholders such as `http://forum.example.com/` in examples. This is a deliberate constraint, not an oversight, and it also keeps the project reusable for any `dsu_paulsign` forum.

Never commit credentials, cookies, or session tokens, and never add logging that prints `DZ_PASS` or `DZ_BASE_URL`. Actions masks registered secrets, but it cannot mask a value that has been transformed, so do not embed secrets in URLs or encode them before printing.

Keep authentication password-based. An earlier design reused a captured session cookie; that was dropped because such cookies expire in about 30 days and turn the project into a monthly maintenance chore. Do not reintroduce a cookie path.

Markdown convention: one paragraph is one line. Do not hard wrap prose at a column limit. Tables and code blocks are formatted normally.

`AGENTS.md` is a symlink to this file. Edit `CLAUDE.md`; never replace the symlink with a copy.

## Things that will bite you

A missing `Referer` is not a soft failure. Some installations sit behind a scraper filter that answers a refererless request with HTTP 200 and a zero-length body. It looks exactly like a layout change, and it cost real debugging time to pin down. The session sets a default `Referer` for every request; do not remove it, and if a page ever comes back empty, suspect this before suspecting the parser.

Failed logins are rate limited. Discuz! counts wrong-password attempts, replies `登录失败，您还可以尝试 N 次`, and after five it locks the account for a cooldown and starts demanding a captcha, which this script cannot solve. Do not loop over login attempts, and do not test bad credentials casually: each test burns one of five. The retry loop in `main()` is safe because it only retries transport errors and unrecognised responses, and `fail()` exits immediately on a rejected login rather than retrying it.

`formhash` cannot be cached. Discuz! derives it from the account plus a truncated timestamp, so it changes and is session-bound. Always scrape it from a page fetched inside the same `requests.Session` immediately before the post that consumes it. There are two independent ones: the login page's `formhash` and the check-in page's `formhash`. The login page additionally carries a `loginhash` that goes in the query string, not the body.

Encoding is not UTF-8. Forums of this vintage commonly serve GBK and do not always declare it in the `Content-Type` header, so `decode()` checks the header, then the `<meta>` tag, then falls back through a candidate list. Do not replace it with `response.text`, which will silently mojibake the Chinese marker strings and break every success check.

Success and failure are detected by matching Chinese marker strings emitted by Discuz! and the plugin, collected in constants at the top of `sign.py`. They belong to the software rather than to any specific forum, so they are portable, but they are the most fragile part of the code. If a marker ever needs changing, verify against a real response body rather than guessing.

Empty is not absent. Actions passes an unset secret through as an empty string, so read optional variables as `os.getenv(name) or default` rather than `os.getenv(name, default)`. `DZ_QUESTION` in particular must end up as `"0"` and not `""` when the account has no security question.

The check-in is idempotent by design. `check_in()` fetches the page for its `formhash` anyway, so the already-checked-in marker short-circuits the submission for free. Preserve that: it is what makes a delayed, duplicated, or manually retried run safe, and a repeat submission returns an already-checked-in response rather than an error.

## The randomised slot

`.github/scripts/wait-for-slot.sh` makes the check-in land at a different time each night inside the window set by `WINDOW_START_UTC` and `WINDOW_END_UTC`. It exists because a check-in that fires on the same minute forever is the most obvious sign of a script.

It sleeps until an absolute target instant, not for a random duration. Do not simplify it into `sleep $RANDOM`: the Actions scheduler is late by anywhere from zero to thirty-odd minutes, so a random duration stacked on an unknown delay drifts out of the window, while a fixed target absorbs the delay. Cron fires ten minutes ahead of the window for the same reason, so keep the cron time and the window variables consistent if either changes.

The script is deliberately kept out of the workflow YAML so it can be tested. `NOW_OVERRIDE` injects a fake current time and `DRY_SLEEP=1` prints the plan without sleeping, so the whole decision table can be exercised in seconds:

```bash
WINDOW_START_UTC=16:15 WINDOW_END_UTC=17:00 DRY_SLEEP=1 \
  NOW_OVERRIDE=$(date -u -d "$(date -u +%F) 16:30:00" +%s) \
  .github/scripts/wait-for-slot.sh
```

Three edge cases are covered and worth preserving: a late start draws from the remaining window rather than collapsing to an edge, a start after the window has closed proceeds immediately because a late check-in still counts while a skipped one does not, and a manual run more than an hour early proceeds immediately rather than holding a runner idle. Scheduled runs wait; manual dispatches do not, unless the `jitter` input is ticked.

## Verifying a change

`DZ_DRY_RUN=1 python sign.py` logs in and reports status without submitting, which exercises everything except the final post and is the right check to run repeatedly. A full run can only be meaningfully verified once per day, since the second run of any day will correctly report an already-completed check-in. A run that reports already-checked-in still proves that connectivity, login, decoding, and page parsing all work.

Exit codes are part of the contract: 0 for both checked-in and already-checked-in, 1 for any failure. Keep them intact so schedulers can rely on them.

## The keepalive workflow

It exists solely because GitHub disables scheduled workflows in a public repository after 60 days of inactivity, which would stop the daily check-in with no visible failure. It commits a timestamp weekly to `keepalive`, an orphan branch whose only file is that timestamp and whose commit messages are the timestamp itself. Keep the churn on that branch and out of `main`, and do not merge it into `main`.
