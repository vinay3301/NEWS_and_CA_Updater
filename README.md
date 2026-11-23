# NEWS & Current Affairs PDF Updater

An automated news and current-affairs digest generator. It collects selected news and exam-relevant current-affairs articles, builds desktop and mobile-friendly PDFs, and publishes both PDFs to Google Drive.

The production workflow runs on GitHub Actions. Google Apps Script is used for the Adda247 fetch proxy and for the Google Drive upload bridge. A separate Apps Script project sends completion emails through an immediate GitHub `workflow_run` webhook, with a 10-minute polling monitor retained as a fallback.

## Contents

- [What the system does](#what-the-system-does)
- [Architecture](#architecture)
- [Sources and collection windows](#sources-and-collection-windows)
- [Article extraction and failure handling](#article-extraction-and-failure-handling)
- [PDF outputs and Google Drive](#pdf-outputs-and-google-drive)
- [Automation schedule](#automation-schedule)
- [Manual runs](#manual-runs)
- [Email notifications](#email-notifications)
- [Repository layout](#repository-layout)
- [Configuration and secrets](#configuration-and-secrets)
- [Termux setup and GitHub dispatch helper](#termux-setup-and-github-dispatch-helper)\n- [Android download workflow](#android-download-workflow)
- [Troubleshooting](#troubleshooting)
- [Security notes](#security-notes)

## What the system does

The production script:

1. Reads recent headlines from selected news RSS feeds.
2. Collects current-affairs articles from AffairsCloud and Adda247.
3. Collects Banking and RBI current-affairs articles from Adda247.
4. Filters out unrelated exam notices, recruitment posts, quizzes, promotional material, and other configured clutter.
5. Extracts article text, headings, lists, tables, links, and available images.
6. Generates a desktop PDF and a mobile-friendly PDF.
7. Uploads both PDFs to Google Drive, replacing the existing files when they are already present.

The production entry point is `News_CA_Updater.py`. GitHub Actions runs this file; it does not run `temp.py`.

## Architecture

There are two separate Apps Script web apps involved in the production path. They have different responsibilities and should not be confused.

```text
                         GitHub Actions
                    (scheduled or manual run)
                               |
                               v
                       News_CA_Updater.py
                               |
              +----------------+----------------+
              |                                 |
              v                                 v
       News RSS / AffairsCloud          Adda247 fetch requests
       and other direct sources                  |
                                                v
                                    Apps Script Adda247 proxy
                                                |
                                                v
                                  currentaffairs.adda247.com
                                                |
                                  HTML returned to Python
                                                |
                                                v
                                  Parse, filter and assemble
                                                |
                                                v
                                   Generate two PDF files
                                                |
                                                v
                                  Apps Script Drive upload
                                                |
                         +----------------------+------------------+
                         |                                         |
                         v                                         v
                  Google Drive root                         Google Drive/Mobile
                  Daily_Articles.pdf                   Daily_Articles_Mobile.pdf
```

### 1. GitHub Actions — production runner

GitHub Actions provides the cloud machine that installs Python dependencies and runs `News_CA_Updater.py`. The production workflow is:

`.github/workflows/manual_production_update.yml`

It runs Python 3.11, installs `requirements.txt`, and starts the generator.

### 2. Apps Script — Adda247 fetch proxy

GitHub Actions does **not** fetch Adda247 pages directly. The Python code routes HTTPS GET requests for the allowed Adda247 host(s) through the separately deployed Apps Script proxy. This applies to both Adda247 listing pages and individual article pages.

The proxy uses the `ADDA247_PROXY_URL` and `ADDA247_PROXY_SECRET` GitHub Actions secrets. The shared secret is checked by the proxy. The Python wrapper retries a failed proxy request up to three times, with a short pause between attempts.

Other sources, including AffairsCloud and the RSS feeds, are not sent through this Adda247 proxy. Their requests continue through the normal direct-fetch path.

The Adda247 proxy is a separate Apps Script deployment; its source code is not the same as the Drive upload bridge in `GoogleAppsScript/Code.gs`.

### 3. Apps Script — Google Drive upload bridge

`GoogleAppsScript/Code.gs` is the Drive upload bridge. GitHub Actions sends each completed PDF to this web app using the `GOOGLE_APPS_SCRIPT_URL` and `GOOGLE_APPS_SCRIPT_SECRET` secrets.

The bridge accepts only these two file names:

- `Daily_Articles.pdf`
- `Daily_Articles_Mobile.pdf`

It checks the shared secret and updates an existing file in its destination folder. Updating the existing file preserves its Google Drive file ID. If the file does not exist yet, the bridge creates it.

The mobile PDF is stored in a child folder named `Mobile` under the configured Drive destination folder. The desktop PDF is stored directly in the configured destination folder.

The bridge uses the Advanced Google Drive service (Drive API v3) in Apps Script.

## Sources and collection windows

The current generator uses the following sources and collection windows.

| Source | Collection |
|---|---|
| The Hindu | RSS; up to 5 accepted entries |
| Times of India | RSS; up to 5 accepted entries |
| Livemint | RSS; up to 5 accepted entries |
| Economic Times | RSS; up to 5 accepted entries |
| NDTV | RSS; up to 5 accepted entries |
| AffairsCloud | Current-affairs pages for today and yesterday |
| Adda247 | Current-affairs articles from the previous 3 days |
| Adda247 | Banking and RBI current-affairs articles from the previous 90 days |

The script filters titles using its configured exclusion keywords. These include recruitment and vacancy notices, exam notices, results, admit cards, quizzes, mock tests, and similar non-current-affairs material. Adda247 category/navigation items such as monthly PDFs and capsules are also excluded from article discovery.

The source websites can change their pages, dates, feeds, or markup. Collection windows and filters are implemented in `News_CA_Updater.py`.

## Article extraction and failure handling

### Adda247

Adda247 listing pages and individual article pages both use the Apps Script proxy in GitHub Actions. The returned HTML is parsed in Python with BeautifulSoup.

For each Adda247 article, the script checks whether substantive content was extracted rather than treating a headline-only fallback as a successful full-text extraction.

If an Adda247 article is incomplete during the first pass:

1. It is queued for a recovery pass after the initial current-affairs and banking collection.
2. The script retries the article twice, waiting 5 seconds and then 15 seconds.
3. If the article is still unavailable, the entry is retained in the PDF with its headline and clickable source article link.
4. The PDF displays a notice that the article text was unavailable after retries.

This is intentional: a failed article fetch should not silently erase the article from the digest. The workflow log also reports the number of articles discovered, initially extracted, recovered, and still incomplete.

### AffairsCloud

AffairsCloud article pages are fetched directly by the Python runner. Its extractor is designed to preserve article structure such as headings, bold text, links, bullet lists, and tables while removing known promotional and static page content.

### RSS news

RSS entries are used for headline-led news items. The PDF includes the headline, available feed summary, source link, and an available image. RSS items are not treated as full-page article extraction.

A successful PDF build or upload does not, by itself, prove that every source returned every article. For content verification, inspect the GitHub Actions log—especially the Adda247 discovery, recovery, and incomplete-article messages—and spot-check the resulting PDFs.

## PDF outputs and Google Drive

Each production run generates two versions from the same collected article data.

| PDF | Purpose | Google Drive destination |
|---|---|---|
| `Daily_Articles.pdf` | Desktop / full-size layout | Configured Drive destination folder |
| `Daily_Articles_Mobile.pdf` | Mobile-friendly layout | `Mobile` subfolder |

The Python generator creates the mobile-friendly PDF at `Daily_Articles.pdf` in its output directory and creates the desktop version temporarily as `Daily_Articles_Desktop.pdf`. The upload bridge assigns the final Drive names shown above.

The upload bridge updates the existing named files in place. This avoids creating a new duplicate PDF on every run and keeps the Drive file IDs stable for clients that already reference those files.

Both uploads are required for a successful production run. If either upload fails, the workflow exits with an error rather than treating the run as fully successful.

## Automation schedule

The production workflow uses this GitHub Actions cron expression:

```cron
30 */4 * * *
```

GitHub cron is interpreted in UTC. The equivalent schedule in India Standard Time (IST) is:

| IST | UTC |
|---|---|
| 2:00 AM | 8:30 PM (previous UTC day) |
| 6:00 AM | 12:30 AM |
| 10:00 AM | 4:30 AM |
| 2:00 PM | 8:30 AM |
| 6:00 PM | 12:30 PM |
| 10:00 PM | 4:30 PM |

The workflow has a 90-minute job timeout. Its concurrency group prevents overlapping production runs; a new run does not cancel an already-running production run.

**The GitHub Actions cron is the active production scheduler.** The optional Apps Script production dispatcher in `GoogleAppsScript/Scheduler.gs` is not enabled in the current setup. Do not run `setupScheduler()` while the GitHub cron is active, because that would introduce a second scheduler and could cause duplicate runs.

## Termux setup and GitHub dispatch helper

Termux is an optional Android-side command-line environment. It was prepared with Cronie so Android can run existing local scheduled commands, and it contains a helper script that can request a production GitHub Actions run. **Autosync, not Termux, is responsible for downloading the mobile PDF to the phone.**

### Packages and cron service

The Termux packages and service setup commands used are:

```bash
pkg update && pkg upgrade -y
pkg install cronie nano
sv-enable crond
sv up crond
```

The `termux-services` package is also required for the `sv` service commands. The cron daemon is managed by Termux's runit service supervisor.

### GitHub dispatch credentials

A fine-grained GitHub personal access token was created with access limited to this repository and Actions read/write permissions. The token is stored locally in:

```text
~/.config/news-ca/github.env
```

The file contains a shell variable assignment (do not commit or share the file):

```bash
GITHUB_TOKEN='YOUR_FINE_GRAINED_TOKEN'
```

The configuration directory and token file are protected with:

```bash
mkdir -p ~/.config/news-ca
chmod 700 ~/.config/news-ca
chmod 600 ~/.config/news-ca/github.env
```

### Dispatch helper

The executable helper is located at `~/scripts/github-dispatch.sh`. It reads the token from the protected environment file and dispatches `.github/workflows/manual_production_update.yml` on branch `main`, with `confirm_drive_upload=yes`.

Its permissions are restricted with:

```bash
chmod 700 ~/scripts/github-dispatch.sh
```

The helper's successful response (HTTP 204 from GitHub) means GitHub accepted the dispatch request; it does **not** mean the workflow has finished. Workflow completion and success must be checked in GitHub Actions, and the separate notification workflow sends the completion email.

### Scheduling status and separation of responsibilities

The dispatch helper has been manually invoked successfully, but it has **not yet been added as a recurring Termux cron job**. The GitHub Actions cron described in [Automation schedule](#automation-schedule) remains the active production scheduler. Do not add a second production schedule or disable the GitHub cron without deliberately migrating and verifying the scheduling arrangement.

Existing Termux cron entries for other local tasks are separate from the GitHub production workflow. Preserve them unless they are intentionally retired. Autosync operates independently and periodically downloads the updated mobile PDF from Drive.

## Manual runs

To start a production run manually:

1. Open the repository on GitHub.
2. Select **Actions**.
3. Open **Scheduled and Manual Production News CA PDF Update**.
4. Select **Run workflow**.
5. Set `confirm_drive_upload` to **yes**.
6. Start the workflow and monitor its run page.

The input defaults to **no**. A manual run with **no** is intentionally skipped; it does not run the production scraper or upload PDFs. Choose **yes** only when you want the full production run and Drive files to be updated.

Scheduled runs are automatically authorised to run the production job and upload both PDFs.

## Email notifications

Completion notifications cover both manually started and scheduled production runs, including successful and failed runs. The current setup has two notification paths:

### 1. Immediate notification — GitHub webhook (primary)

The workflow file:

`.github/workflows/notify_workflow_completion.yml`

listens for the `completed` event of **Scheduled and Manual Production News CA PDF Update** on the `main` branch. When that production workflow finishes, GitHub starts the separate **Immediate Workflow Email Notification** workflow. It sends the completed run details to the notification Apps Script web app using an HTTP POST request.

The notification workflow does not start or rerun production generation. It only reports the result of a production run. It handles both `workflow_dispatch` (manual) and `schedule` (GitHub cron) events, and forwards the run conclusion so Apps Script can send either a SUCCESS or FAILED email.

### 2. Polling notification — Apps Script fallback

The Apps Script function `setupNotificationMonitor()` installs a time-driven trigger every 10 minutes:

- `monitorProductionRun()` checks GitHub Actions for newly completed scheduled and manual production runs.
- It emails the configured address with the workflow result and a link to the GitHub run.
- It seeds its notification cursor from existing workflow history during setup, so old runs are not all emailed as new notifications.

The 10-minute trigger is a **monitoring interval**, not a production generation interval. It does not start a PDF run. It checks for completion and serves as a fallback if an immediate webhook notification is missed.

### Duplicate-notification protection

Both notification paths use the Script Property `LAST_NOTIFIED_RUN_ID` as a shared run-ID cursor. The webhook checks the cursor before sending and updates it after the email call; the polling monitor also skips run IDs at or below the cursor. The webhook handler additionally uses a script lock to serialize webhook requests.

This prevents the normal sequential case where the webhook and polling monitor both try to notify the same already-processed run. The two paths are independent executions, however, and the polling function currently does not acquire the same script lock. A very narrow timing race if both paths begin processing the same run simultaneously is therefore still theoretically possible; this is not an absolute exactly-once delivery guarantee. The monitor can be removed after the webhook has been observed working reliably if a single notification path is preferred.

### Notification configuration

In the separate Apps Script project containing `Scheduler.gs`, configure these Script Properties:

- `ALERT_EMAIL` — destination email address.
- `GITHUB_TOKEN` — GitHub fine-grained personal access token with Actions read permission for this repository (write is needed only if using the optional Apps Script dispatcher).
- `WEBHOOK_SECRET` — shared secret used to authenticate incoming completion webhook requests.

Set the Apps Script project time zone to `Asia/Kolkata`.

Deploy the notification Apps Script as a web app that executes as the script owner and is accessible to the webhook caller. Store its deployed `/exec` URL in the GitHub Actions repository secret `NOTIFICATION_WEBHOOK_URL`. Store the same secret value as Apps Script Script Property `WEBHOOK_SECRET` and GitHub Actions repository secret `NOTIFICATION_WEBHOOK_SECRET`. Do not put either secret value in this README or source control.

The GitHub notification workflow requires these repository secrets:

- `NOTIFICATION_WEBHOOK_URL` — deployed notification Apps Script web-app URL.
- `NOTIFICATION_WEBHOOK_SECRET` — must match the Apps Script `WEBHOOK_SECRET` property.

The optional `setupScheduler()` function installs both an Apps Script dispatcher and the polling monitor. It is an alternative production scheduling arrangement, not something to enable alongside the active GitHub cron. If switching schedulers in the future, disable the GitHub cron first and deliberately migrate to the Apps Script dispatcher.

## Repository layout

```text
.
├── .github/
│   └── workflows/
│       ├── manual_production_update.yml
│       └── notify_workflow_completion.yml
├── GoogleAppsScript/
│   ├── Code.gs
│   └── Scheduler.gs
├── News_CA_Updater.py
├── temp.py
├── requirements.txt
└── README.md
```

| File | Purpose |
|---|---|
| `News_CA_Updater.py` | Main production scraper, extractor, PDF generator, and upload client |
| `requirements.txt` | Python dependencies |
| `.github/workflows/manual_production_update.yml` | Scheduled and manually approved production workflow |\n| `.github/workflows/notify_workflow_completion.yml` | Sends an immediate completion webhook for production workflow success or failure |
| `GoogleAppsScript/Code.gs` | Google Drive PDF upload bridge |
| `GoogleAppsScript/Scheduler.gs` | Optional Apps Script dispatcher and workflow email monitor |
| `temp.py` | Auxiliary/working script; not invoked by the production workflow |

The Adda247 proxy web app is deployed separately in Google Apps Script; it is not the Drive upload bridge file listed above.

## Configuration and secrets

Configure these as **GitHub Actions repository secrets**. Do not put their values in source files or this README.

| GitHub Actions secret | Used for |
|---|---|
| `ADDA247_PROXY_URL` | Deployed Apps Script Adda247 fetch-proxy web-app URL |
| `ADDA247_PROXY_SECRET` | Shared secret checked by the Adda247 proxy |
| `GOOGLE_APPS_SCRIPT_URL` | Deployed Apps Script Drive upload bridge URL |
| `GOOGLE_APPS_SCRIPT_SECRET` | Shared secret checked by the Drive upload bridge |

### Drive upload bridge Script Properties

In the Apps Script project containing `GoogleAppsScript/Code.gs`, configure:

- `UPLOAD_SECRET` — must match the GitHub Actions secret `GOOGLE_APPS_SCRIPT_SECRET`.
- `DRIVE_FOLDER_ID` — ID of the existing parent Google Drive folder where the desktop PDF is stored and the `Mobile` subfolder is created.

Enable the Advanced Google service **Drive API v3** in that Apps Script project. Deploy the script as a web app that executes as the script owner. The bridge authenticates incoming POST requests with the shared secret.

### Adda247 proxy Script Properties

In the separate Apps Script project used for Adda247 fetching, configure `PROXY_SECRET` to match the GitHub Actions secret `ADDA247_PROXY_SECRET`. Use the deployed web-app URL for `ADDA247_PROXY_URL`.

### Notification Apps Script Script Properties

In the separate Apps Script project containing `Scheduler.gs`, configure `GITHUB_TOKEN`, `ALERT_EMAIL`, and `WEBHOOK_SECRET` as described in [Email notifications](#email-notifications).

## Android download workflow

Android delivery is handled by **Autosync for Google Drive** (MetaCtrl), not by GitHub Actions, Apps Script, or Termux. The production workflow uploads `Daily_Articles_Mobile.pdf` to the Google Drive `Mobile` subfolder. Autosync downloads that file to the configured local phone folder.

Recommended folder-pair configuration:

- **Remote folder:** the Google Drive `Mobile` folder.
- **Local folder:** a dedicated folder such as `Download/News_CA`.
- **Sync direction:** download only / cloud to local.
- **File selection:** synchronize `Daily_Articles_Mobile.pdf`.
- **Overwrite:** enabled, so the local copy is replaced when Drive has a newer version.
- **Delete synchronization:** disabled, to avoid deleting unrelated local or cloud files.
- **Background operation:** allow Autosync to run in the background and configure Android battery restrictions as needed.

Autosync's interval and background timing are controlled by the app and Android. The phone does not need to run the Python generator or keep Termux active for the GitHub-hosted production workflow. Apps Script cannot directly write files into Android local storage; it uploads the PDF to Drive, and Autosync handles the phone download.

The previous FolderSync instructions are obsolete; Autosync for Google Drive is the selected synchronization app.

## Troubleshooting

### A workflow run is skipped after a manual trigger

Check the `confirm_drive_upload` input. It must be set to **yes** for a manual production run. The default is **no** by design.

### Adda247 articles appear as headline plus source link

Open the workflow log and search for `[Adda247]`. Check the proxy response, the first-pass extraction count, recovery retries, and the final incomplete-article list. If the source page remains unavailable after retries, the PDF retains the headline and source link and labels the missing article text.

### Adda247 proxy configuration error

Confirm that `ADDA247_PROXY_URL` and `ADDA247_PROXY_SECRET` exist as GitHub Actions secrets, that the URL points to the deployed proxy web app, and that its `PROXY_SECRET` Script Property matches the secret exactly.

### Google Drive upload fails

Confirm that `GOOGLE_APPS_SCRIPT_URL` and `GOOGLE_APPS_SCRIPT_SECRET` are configured, and that the Drive bridge has matching `UPLOAD_SECRET` and a valid `DRIVE_FOLDER_ID`. Also verify that the Advanced Drive API service is enabled and the web app deployment is current.

### No email arrives

Check the notification project's `ALERT_EMAIL`, `GITHUB_TOKEN`, and `WEBHOOK_SECRET` Script Properties. For immediate notifications, inspect the **Immediate Workflow Email Notification** GitHub Actions run and the Apps Script execution log; confirm that the `NOTIFICATION_WEBHOOK_URL` and `NOTIFICATION_WEBHOOK_SECRET` repository secrets are configured. The 10-minute `monitorProductionRun` trigger is only the fallback and does not email every time it polls.

### A PDF exists but an article is incomplete

A successful run means the pipeline completed, not necessarily that every source page supplied full article text. Inspect the Adda247 incomplete-article messages and the PDF's source links and extraction warning.

## Security notes

- Keep all shared secrets in GitHub Actions Secrets or Apps Script Script Properties.
- Never commit API tokens, proxy secrets, OAuth credentials, service-account JSON files, or private Drive identifiers that should remain confidential.
- The Apps Script web apps require a shared secret because their web-app endpoints are called by GitHub Actions.
- The Adda247 proxy is intended only for Adda247 fetching; the Drive upload bridge accepts only the two expected PDF file names.
- Review GitHub Actions logs before sharing them publicly, and redact any accidentally exposed credentials.

---

## Current operating model

- **Production generation:** GitHub Actions cron, every 4 hours.
- **Manual production generation:** GitHub Actions workflow dispatch with `confirm_drive_upload=yes`.
- **Adda247 fetching:** separate Apps Script proxy.
- **PDF upload:** separate Apps Script Drive bridge.
- **Completion email:** immediate GitHub `workflow_run` notification workflow → Apps Script webhook; 10-minute Apps Script polling monitor retained as fallback.
- **Termux:** Cronie is installed and the GitHub dispatch helper is configured; recurring Termux production dispatch is not enabled.\n- **Android PDF download:** Autosync for Google Drive downloads the `Mobile/Daily_Articles_Mobile.pdf` file to the configured local folder.

The GitHub cron remains the only active production scheduler in this arrangement.