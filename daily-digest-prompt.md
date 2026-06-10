# Daily Digest — Scheduled Trigger Setup

This repo includes the prompt used to generate the recurring "Daily Digest" email.

## One-time setup (manual, ~1 minute)

Claude Code on the web doesn't expose a tool that can create scheduled triggers or
send email directly — both require a one-time setup step in the web UI:

1. Go to the Claude Code web app → this repo (`dstozki-afk/area51`) → **Triggers**.
2. Create a new trigger:
   - **Schedule**: daily at 7:00 AM (your local timezone)
   - **Prompt**: paste the contents of the "Digest Prompt" section below
3. Save. Each morning at 7am, a new session will run this prompt automatically.

## Sending vs. drafting

The connected Gmail tool only supports creating drafts, not sending. Each run will
produce a Gmail draft titled "Daily Digest - <date>". If you want it actually sent
(not just drafted) every morning with no manual step, reconnect/upgrade the Gmail
connector to one that grants `gmail.send` scope — once that's available, update the
prompt below to say "send the email" instead of "create a draft".

## Digest Prompt

```
Search my Gmail for all messages from the last 24 hours (newer_than:1d, in:inbox).
Stack-rank them by importance (financial/security alerts and time-sensitive items
first, then personal/family, then career/work opportunities, then logistics/travel,
then informational, then promotional/newsletters last).

For each item give: a 1-2 sentence summary, the relevant date/time, and a clear
recommended action (or "No action needed").

Create a Gmail draft (to dstozki@gmail.com) titled "Daily Digest - <today's date>"
containing the stack-ranked summary.
```
