# Serving thousands of readers for nothing

This platform is open source and runs entirely on free tiers. That is a design
constraint, not an accident, and two things follow from it that are worth
writing down, because both were discovered by measurement rather than guessed
at, and both are easy to undo by accident.

The short version: **reads are cached so they never reach the API, and sign-in
avoids email wherever possible.** Everything below is why.

## What the limits actually were

Measured against the deployed stack, before any of this:

| | Figure |
|---|---|
| Requests the API answered per second | 12.5 |
| Requests one page load sent | 23 |
| Page loads per minute, site-wide | ~30 |
| Sign-ups possible per hour | 2–4 |

Thirty page loads a minute is not thousands of users. Neither is four
sign-ups an hour. They have separate causes and separate fixes.

## Reads: cached, not recomputed

Nothing an anonymous visitor sees is specific to them. The catalogue, the
conjunction list and the trajectories are platform-owned rows, rewritten every
six hours by the scheduled screening. Computing them per visitor was pure
waste — and expensive waste, because a trajectory runs SGP4 across a time grid
and the API has a tenth of a CPU.

Three changes, in increasing order of effect:

1. **Batching.** `GET /trajectories?norad_ids=…` returns every track in one
   request. The console asked for one per object, which on a twenty-object
   catalogue was twenty round trips before the first paint finished.
2. **An in-process cache** (`sdebris/api/public_cache.py`) holds the finished
   JSON for five minutes. A repeat request is a dictionary lookup, not a
   propagation.
3. **An edge cache** (`web/app/api/public/[...path]/route.ts`). Public reads go
   to the site's own origin, where a route handler holds the answer and
   forwards at most one request per interval upstream. This is the one that
   matters: a response served from the edge never touches the API at all, so
   it stays fast while the instance is asleep and costs no instance hours.

Anonymous page loads now send **one** uncached request to the API, down from
twenty-three.

### The rule for adding a route to the cache

The allow-list in the route handler is a security boundary, not an
optimisation. That route runs with no bearer token and its answers go into a
cache every visitor shares, so a path that reaches it by mistake is both an
authorisation bypass and a way to serve one account's rows to the next person.

> **Only add a path that takes no principal.** If the handler's signature
> mentions `PrincipalDep` or `OptionalPrincipalDep`, it does not belong here.

`/monitoring` is the trap. It looks public, it is readable without signing in,
and it returns the platform's watch list to anonymous callers — but a
signed-in caller additionally sees their own objects. It is deliberately
absent, and `web/tests/public-proxy.test.ts` fails if it is added.

### The shared secret

The API meters anonymous traffic by client address. Behind a cache every
visitor arrives from the same few addresses, so without an exemption the
second person to open the site would be throttled as though they were the
first one again.

Set the same value in both places:

- Render: `SDEBRIS_PROXY_TOKEN`
- Vercel: `SDEBRIS_PROXY_TOKEN` (**not** `NEXT_PUBLIC_`, or it ships to the
  browser and anyone can spend the exemption)

Leave both unset and nothing breaks; the proxy simply gets no exemption, which
is the safe default and fine at low traffic.

## Sign-in: avoid email where possible

Supabase's built-in email sender allows roughly **two messages an hour for the
whole project**. That is a platform limit, not a per-address one, so a visitor
who is refused gains nothing by trying another address. At that rate the site
cannot accept public sign-ups in any meaningful sense.

Switching from magic links to six-digit codes fixed several real problems —
no redirect to misconfigure, no same-browser constraint, no credential in a
URL — but it did not touch this one. A code and a link are the same email.

So the platform offers three routes, in this order:

1. **GitHub** — first, because the people most likely to want an account on an
   open-source orbital tool are already reading the repository.
2. **Google** — for everyone else.
3. **A six-digit code by email** — for people who want neither.

OAuth is unmetered, costs nothing, needs no domain, and never puts a
credential in an inbox. Email remains as a genuine fallback, not a token one.

### Enabling the providers

Both are configured in **Supabase → Authentication → Providers**, and each
needs an OAuth application created with the provider:

| Provider | Where | Callback URL |
|---|---|---|
| GitHub | Settings → Developer settings → OAuth Apps | `https://PROJECT.supabase.co/auth/v1/callback` |
| Google | Google Cloud Console → Credentials → OAuth client ID | `https://PROJECT.supabase.co/auth/v1/callback` |

Paste the client ID and secret into Supabase. Until a provider is enabled its
button returns "Unsupported provider", which the sign-in page rewrites into
something a visitor can act on.

### Making email work properly

The built-in sender is for development. For real use, configure custom SMTP in
**Supabase → Project Settings → Authentication → SMTP Settings**.

**Brevo** is the recommendation for this project specifically: 300 emails a day
free and permanent, and — unlike most providers — it will verify an individual
sender address, so it works without owning a domain. Resend's free tier is
larger on paper, but its test domain only delivers to your own address, so real
sending needs a domain you have bought.

Two settings, not one. After saving SMTP, raise **Authentication → Rate Limits
→ "Rate limit for sending emails"**, which has its own conservative default;
otherwise one ceiling has been swapped for another.

The email template must contain `{{ .Token }}`. A template with only
`{{ .ConfirmationURL }}` sends a link, and the code field on the sign-in page
will never be satisfied.

## Keeping the instance awake

`.github/workflows/keepwarm.yml` pings `/ready` every ten minutes so Render does
not stop the instance after fifteen minutes of quiet, and so Supabase does not
pause the project after seven days without a query.

It runs for eighteen hours a day rather than twenty-four, and the arithmetic is
the reason. The free allowance is 750 instance-hours a month **shared across
every free service on the account**. Continuous uptime costs 744 of them in a
31-day month — six hours of headroom for everything, which one overlapping
deploy can exhaust. Running out suspends the service for the rest of the month.

Set the repository variable `SDEBRIS_API_URL` (Settings → Secrets and variables
→ Actions → **Variables**, not Secrets — it is a public URL) or the workflow
reports that there is nothing to do and exits.

Two caveats worth knowing:

- GitHub's scheduler is best-effort and can run twenty minutes late. The job
  pings three times across each interval so a late start still leaves no gap.
  A dedicated uptime monitor is more reliable; UptimeRobot's free tier polls
  every five minutes and takes two minutes to set up.
- Runner minutes are unmetered on **public** repositories. On a private one
  this schedule would exhaust the 2,000-minute monthly allowance in about a
  week.

## What breaks next

In the order it will happen, roughly:

1. **Vercel's Hobby plan is non-commercial.** Fine for open source, but it
   conflicts with the paid tier in the billing model. Revenue means Vercel Pro.
2. **Supabase free allows 500 MB of database.** Screening results accumulate;
   old conjunction events are the first thing to prune.
3. **Render's 750 hours**, as above, if a second free service appears.
4. **The in-process cache is per-instance.** It is correct at one instance and
   still correct at several, just less effective. The rate limiter is the part
   that genuinely assumes a single process, and would need Redis before the
   API is scaled horizontally.

Free-tier figures change often. Verify them against the providers before
relying on any number here.
