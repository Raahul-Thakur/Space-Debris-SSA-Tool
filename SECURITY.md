# Security policy

## Supported version

Security fixes are applied to the latest commit on `main`.

## Reporting a vulnerability

Do not disclose authentication bypasses, leaked credentials, injection issues, or other
exploitable findings in a public issue. Use GitHub's private vulnerability reporting for
this repository. If that feature is unavailable, contact the repository owner privately
through their GitHub profile.

Include reproduction steps, affected endpoints or versions, and the potential impact.
Do not access data that does not belong to you and do not run denial-of-service tests.

## Session tokens

Signing in issues two credentials, and they are not equally dangerous. The
access token proves who you are and expires within the hour. The **refresh
token mints new access tokens and does not expire on its own**, so it is the
one that matters: anyone holding it can act as that account until the session
is revoked.

### How the platform handles them

**Sign-in uses the PKCE flow.** Under the older implicit flow a magic link
returns both tokens in the URL fragment, which puts a working credential in
the address bar, in browser history, and in any screenshot or copied link.
PKCE returns a single-use `code` instead, exchanged for a session using a
verifier held only in the browser that requested it. An intercepted code is
useless without that verifier.

The cost is that the link must be opened in the browser that asked for it.
Requesting sign-in on a laptop and opening the email on a phone will not
work.

**The callback URL is scrubbed** as soon as the session is established, so
even a spent code does not linger where it can be copied, and a project not
yet moved to PKCE still does not leave tokens in the bar.

**Sessions can be ended by the person who owns them.** The console carries a
sign-out control scoped to the current device, and `signOutEverywhere()`
revokes every session for the account — which is the remedy when a
credential is believed to have leaked.

**Nothing logs a token.** The access token is held in a module variable for
the lifetime of the page and attached as a bearer header; it is never written
to the console, to an error message, or to the activity feed.

### Settings that belong in the Supabase dashboard

These are project configuration, not code, so they survive no deployment and
have to be set once by hand:

| Setting | Value | Why |
| --- | --- | --- |
| Authentication → Sessions → **Refresh token rotation** | enabled | A refresh token is single-use; the next one replaces it |
| Authentication → Sessions → **Reuse interval** | 10 seconds | A rotated token presented twice signals theft and kills the family |
| Authentication → Sessions → **Time-box user sessions** | 7 days | A forgotten session cannot live forever |
| Authentication → Sessions → **Inactivity timeout** | 24 hours | Abandoned tabs stop being credentials |
| Authentication → **Access token expiry** | 3600 seconds | Shorter means a leaked access token is worth less |
| Authentication → URL Configuration → **Site URL** | the production domain | A mismatch silently redirects sign-in to this value |
| Authentication → URL Configuration → **Redirect URLs** | production domain with `/**` | Without the wildcard the callback path will not match |

### If a token is exposed

Treat any URL containing `access_token=`, `refresh_token=` or `code=` as a
credential, wherever it appears — chat, a ticket, a screenshot, a bug report.

1. Revoke the session. Either `signOutEverywhere()` from the signed-in
   browser, or delete the row directly:

   ```sql
   delete from auth.sessions where id = '<session-id>';
   ```

2. Confirm nothing remains:

   ```sql
   select count(*) from auth.refresh_tokens where not revoked;
   ```

3. If the exposure was public rather than private, rotate the database
   password too: the same transcript or screenshot may hold more than one
   secret.

Revoking costs the user a single re-authentication. It is never the wrong
call when there is doubt.

## Scope and limitations

This is an educational portfolio project, not an operational SSA service. Scientific
model limitations should use the public methodology-feedback issue form unless they also
create a security or privacy risk.
