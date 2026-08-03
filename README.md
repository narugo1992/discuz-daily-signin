# discuz-daily-signin

A tiny GitHub Actions bot that performs the daily check-in on a Discuz! forum running the widely deployed `dsu_paulsign` plugin. It logs in with a username and password, picks a random mood, submits the check-in, and stops. One scheduled run per day, no server to maintain.

## How it works

The whole protocol is two form posts, which is why this needs no browser automation and no dependencies beyond `requests`.

1. `GET member.php?mod=logging&action=login` to obtain a `formhash` and a `loginhash`, plus the session cookies.
2. `POST member.php?mod=logging&action=login&loginsubmit=yes&loginhash=...` with the credentials. A `欢迎您回来` in the response means the session is authenticated.
3. `GET plugin.php?id=dsu_paulsign:sign` to obtain a fresh `formhash`. If the page already says `您今天已经签到过了`, the run stops here.
4. `POST plugin.php?id=dsu_paulsign:sign&operation=qiandao&infloat=1&inajax=1` with `formhash`, `qdmode=1` and a random `qdxq` mood code.

Three details are worth knowing before modifying this. The `formhash` is derived from the account and a truncated timestamp, so it cannot be cached or hard-coded and must be scraped from a page fetched in the same session. Many Discuz! installations of this vintage serve GBK rather than UTF-8, so responses are decoded against the charset the site actually declares instead of trusting the default. And every request carries a `Referer`, because some installations sit behind a scraper filter that answers a refererless request with HTTP 200 and an empty body, which is easy to misread as a broken parser.

Failed logins are rate limited by Discuz! itself: after five wrong passwords the account is locked for a cooldown and a captcha appears, which this script cannot solve. Get the credentials right the first time, and use the dry-run toggle rather than repeatedly guessing.

Because the check-in page has to be fetched anyway for its `formhash`, using it to detect an already-completed day costs nothing. That makes the script idempotent: running it repeatedly on the same day is harmless, so a delayed or duplicated schedule never causes trouble.

## Setup

Fork or clone this repository, then add the following repository secrets under Settings, Secrets and variables, Actions.

| Secret | Required | Purpose |
| --- | --- | --- |
| `DZ_BASE_URL` | yes | Forum base URL with a trailing slash, for example `http://forum.example.com/` |
| `DZ_USER` | yes | Username |
| `DZ_PASS` | yes | Password |
| `DZ_QUESTION` | no | Security question id, if the account has one configured |
| `DZ_ANSWER` | no | Security question answer |

The target forum is intentionally not committed anywhere in this repository; it lives only in `DZ_BASE_URL`. That keeps the repository useful for any `dsu_paulsign` forum and avoids advertising a specific one.

Once the secrets are in place, open the Actions tab, select the `daily check-in` workflow, and use Run workflow to verify the setup. The dispatch form accepts an optional mood code and a dry-run toggle that logs in and reports status without submitting anything.

## Moods

`dsu_paulsign` accepts nine mood codes. One is picked at random on every run unless `DZ_MOOD` overrides it.

| Code | Meaning | Code | Meaning | Code | Meaning |
| --- | --- | --- | --- | --- | --- |
| `kx` | happy | `nu` | angry | `yl` | lazy |
| `ng` | sad | `ch` | sweating | `shuai` | unlucky |
| `ym` | gloomy | `fd` | striving | | |
| `wl` | bored | | | | |

## Schedule

The check-in does not happen at a fixed minute. Cron fires at `5 16 * * *`, that is 16:05 UTC, and the job then waits until a randomly chosen instant inside a window defined by `WINDOW_START_UTC` and `WINDOW_END_UTC` in the workflow, 16:15 to 17:00 UTC by default. In UTC+8 that means the check-in lands somewhere between 00:15 and 01:00 each night, at a different time every day. Hitting the same minute forever is the most obvious tell that a check-in is scripted, and a random slot costs nothing to arrange.

The target is computed as an absolute instant rather than a random sleep duration, which is what makes it robust. The Actions scheduler starts jobs anywhere from on time to half an hour late, so a random duration piled on top of an unknown delay would regularly overshoot the window; sleeping until a fixed target absorbs the delay instead. Cron deliberately fires ten minutes before the window opens so that the whole window remains reachable even when the scheduler is behind. If a late start eats into the window, the target is drawn from whatever remains of it; if the window has closed entirely, the check-in runs immediately, because a late check-in still counts for the day while a skipped one does not.

Adjust the cron expression and the two window variables together if the forum uses a different timezone. Actions cron is always UTC and never accounts for daylight saving. A window that wraps past midnight, such as 23:30 to 00:30, is handled.

Manual dispatches run immediately rather than waiting, which is what you want when testing. Tick the `jitter` input to exercise the waiting path on a real run.

One further scheduling caveat applies to any repository like this: GitHub disables scheduled workflows in a public repository after 60 days without repository activity, which would silently stop the daily run.

The `keepalive` workflow handles that second problem. It commits a timestamp once a week to a dedicated orphan branch named `keepalive`, whose only content is that timestamp file. Keeping the churn off `main` leaves the project history readable while still resetting the inactivity counter.

## Running locally

```bash
pip install -r requirements.txt
export DZ_BASE_URL='http://forum.example.com/'
export DZ_USER='your-username'
export DZ_PASS='your-password'
python sign.py            # check in
DZ_DRY_RUN=1 python sign.py   # log in only, submit nothing
DZ_MOOD=kx python sign.py     # pin the mood
```

The script exits 0 on a successful check-in and on an already-checked-in day, and exits 1 on any failure, so it slots into any scheduler that reads exit codes.

## Security notes

Many forums of this era are HTTP only, in which case the password crosses the network in clear text. That is a property of the forum rather than of this script, but it is worth weighing. Use a password unique to that forum so a compromise cannot spread, and keep it in Actions secrets rather than in the repository.

Workflow logs are public in a public repository. The script never prints the credentials or the base URL, and Actions masks registered secret values, but keep that in mind when adding debug output: a secret that has been transformed, for instance base64 encoded or embedded in a URL, is no longer masked.

Automated check-ins may be against a given forum's rules. A single well-formed request a day is indistinguishable from a manual click server side, but the account risk, whatever it amounts to, is the operator's to accept.

## License

MIT
