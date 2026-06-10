# Daily Digest Email — Setup

This repo contains a GitHub Actions workflow (`.github/workflows/daily-digest.yml`)
that runs every morning at 7am and emails a "Daily Digest" to dstozki@gmail.com:
a stack-ranked summary of the previous 24 hours of email, with action items and
dates for each item.

The workflow runs independently of any Claude Code session — once the secrets
below are configured, it will fire automatically every day.

## One-time setup (required)

You need to add four repository secrets (Settings -> Secrets and variables ->
Actions -> New repository secret):

1. **ANTHROPIC_API_KEY** - an Anthropic API key (used to summarize and
   stack-rank your emails).

2. **GMAIL_CLIENT_ID**, **GMAIL_CLIENT_SECRET**, **GMAIL_REFRESH_TOKEN** -
   credentials that let the workflow read your inbox and send the digest.
   To generate these:
   - In Google Cloud Console, create an OAuth 2.0 Client ID of type
     "Desktop app" and download it as `scripts/client_secret.json`
     (do not commit this file).
   - Run locally:
     ```
     pip install -r scripts/requirements.txt
     python scripts/get_gmail_refresh_token.py
     ```
   - Sign in as dstozki@gmail.com when the browser opens and grant access.
   - Copy the three printed values into the repo secrets above.

## Schedule

The workflow runs at `0 13 * * *` (13:00 UTC = 7:00 AM Mountain Daylight
Time). GitHub Actions cron does not adjust for daylight saving, so during
Mountain Standard Time this will run at 6am instead of 7am. Edit the cron
expression in `.github/workflows/daily-digest.yml` if you want a different
time or to account for DST.

## Testing

After secrets are configured, go to Actions -> "Daily Digest Email" -> "Run
workflow" to trigger it manually and verify the email arrives.
