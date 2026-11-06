# Database backups

A GitHub Actions workflow (`.github/workflows/backup.yml`) copies the
Supabase database every night at 03:17 UTC. Each copy is a `pg_dump` in
custom format, checked to be readable, encrypted with
[age](https://age-encryption.org) to your public key, and uploaded to a
Cloudflare R2 bucket. The private key that can read it stays with you.

It matters because the free Supabase plan has no point-in-time recovery, and
the database holds the billing ledger and every Pro grant.

Until it is configured, the workflow runs, notes that it is not set up, and
does nothing.

## Set it up (about 15 minutes)

1. **Make a key pair** on your own computer (install `age` from
   [its releases page](https://github.com/FiloSottile/age/releases), or
   `winget install FiloSottile.age` on Windows):

    ```bash
    age-keygen -o sdebris-backup.key
    ```

    It prints a line beginning `Public key: age1...`. Keep
    `sdebris-backup.key` in your password manager and somewhere offline. Without
    it the backups cannot be read, and nobody can recover it for you.

2. **Create the bucket.** Cloudflare dashboard → *R2* → *Create bucket*, e.g.
   `sdebris-backups`. Under the bucket's *Settings → Object lifecycle rules*,
   add a rule deleting objects under `daily/` after 30 days.

3. **Create an R2 API token** (*R2 → Manage API tokens → Create*) with
   *Object Read & Write* on that bucket only. Note the access key id, secret
   and the S3 endpoint (`https://<account-id>.r2.cloudflarestorage.com`).

4. **Find the database URL.** Supabase → *Connect* → *Session pooler*
   (port **5432**). Use it exactly as shown, starting `postgresql://`, with
   your database password filled in.

5. **Add them to GitHub** → *Settings → Secrets and variables → Actions*:

    | Kind | Name | Value |
    |------|------|-------|
    | Secret | `SDEBRIS_BACKUP_DATABASE_URL` | the session pooler URL |
    | Secret | `BACKUP_R2_ACCESS_KEY_ID` | R2 access key id |
    | Secret | `BACKUP_R2_SECRET_ACCESS_KEY` | R2 secret |
    | Variable | `BACKUP_AGE_RECIPIENT` | the `age1...` public key |
    | Variable | `BACKUP_R2_ENDPOINT` | the R2 S3 endpoint |
    | Variable | `BACKUP_R2_BUCKET` | the bucket name |

6. **Run it once by hand:** *Actions → Database backup → Run workflow*. The
   log ends with `uploaded daily/sdebris-<time>.pgc.age`.

## Restore

Practise this once before you need it, against a scratch database.

```bash
# 1. Download a backup from the R2 bucket (dashboard, or the AWS CLI)
# 2. Decrypt it with your private key
age --decrypt -i sdebris-backup.key -o restore.pgc sdebris-20261107T031700Z.pgc.age

# 3. Restore into an empty database (a new Supabase project, or local Postgres)
pg_restore --no-owner --no-privileges --dbname "postgresql://...target..." restore.pgc
```

After restoring into a new Supabase project, run the migrations
(`python -m alembic upgrade head`) so the row-level security and grant
settings are reapplied, then point `SDEBRIS_DATABASE_URL` on Render at it.
