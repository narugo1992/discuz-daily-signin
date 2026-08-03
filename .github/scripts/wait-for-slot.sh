#!/usr/bin/env bash
# Sleep until a randomly chosen instant inside a daily window, so that the
# check-in lands at a different, unremarkable time every day instead of on the
# same minute forever.
#
# The target is an absolute instant rather than a random duration. That matters
# because the Actions scheduler starts jobs anywhere from on time to half an
# hour late; sleeping a random duration on top of an unknown delay would drift
# out of the window, whereas sleeping until a fixed target absorbs the delay.
#
# Environment:
#   WINDOW_START_UTC  Window opens, HH:MM in UTC (required)
#   WINDOW_END_UTC    Window closes, HH:MM in UTC (required)
#   NOW_OVERRIDE      Unix timestamp to treat as the current time (tests only)
#   DRY_SLEEP         When "1", report the plan without actually sleeping (tests)

set -euo pipefail

: "${WINDOW_START_UTC:?WINDOW_START_UTC is required}"
: "${WINDOW_END_UTC:?WINDOW_END_UTC is required}"

now="${NOW_OVERRIDE:-$(date -u +%s)}"
today="$(date -u -d "@$now" +%F)"
start="$(date -u -d "$today $WINDOW_START_UTC:00" +%s)"
end="$(date -u -d "$today $WINDOW_END_UTC:00" +%s)"

# A window given as, say, 23:30 to 00:30 wraps past midnight; carry the end into
# the next day so the arithmetic below stays monotonic.
if [ "$end" -le "$start" ]; then
  end="$(( end + 86400 ))"
fi

stamp() { date -u -d "@$1" '+%H:%M:%S'; }

if [ "$now" -ge "$end" ]; then
  # The scheduler was late enough to miss the window outright. A late check-in
  # still counts for the day, so proceed rather than skip.
  echo "Window closed at $(stamp "$end") UTC; running immediately."
  exit 0
fi

if [ "$now" -lt "$(( start - 3600 ))" ]; then
  # A manual run hours ahead of the window should not hold a runner idle for
  # hours. Only the scheduled lead time is worth waiting out.
  echo "Started more than an hour before the window; running immediately."
  exit 0
fi

# Draw from whatever remains of the window, so a late start still produces a
# random time inside it rather than collapsing to the window edge.
floor="$(( now > start ? now : start ))"
offset="$(shuf -i "0-$(( end - floor ))" -n 1)"
target="$(( floor + offset ))"
wait_for="$(( target - now ))"

echo "Now:    $(stamp "$now") UTC"
echo "Target: $(stamp "$target") UTC (waiting ${wait_for}s)"

if [ "${DRY_SLEEP:-}" = "1" ]; then
  echo "DRY_SLEEP set; not sleeping."
  exit 0
fi

sleep "$wait_for"
