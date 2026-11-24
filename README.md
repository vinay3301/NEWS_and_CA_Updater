# NEWS & Current Affairs PDF Updater

An automated news and current-affairs digest generator. It collects selected news and exam-relevant current-affairs articles, builds desktop and mobile-friendly PDFs, and publishes both PDFs to Google Drive.

The production workflow runs on GitHub Actions and is dispatched automatically by a Termux cron job every 3 hours, or manually from GitHub Actions. Google Apps Script is used for the Adda247 fetch proxy, the Google Drive upload bridge, and a separate notification webhook that sends completion emails. The production workflow posts its own completion notification directly to that webhook; there is no polling monitor or GitHub `workflow_run` notification workflow.

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
- [Termux setup and GitHub dispatch helper](#termux-setup-and-github-dispatch-helper)
- [Android download workflow](#android-download-workflow)
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
                    (Termux-dispatched or manual run)
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

The production workflow is **not scheduled by GitHub Actions cron**. The GitHub schedule trigger was removed. Termux is the only automatic production scheduler.

A cron entry on the Android device dispatches the production workflow every 3 hours:

```cron
0 */3 * * * /data/data/com.termux/files/home/scripts/github-dispatch.sh >> /data/data/com.termux/files/home/logs/github-dispatch-cron.log 2>&1
```

This runs at minute 0 every third hour in the device's local time (India Standard Time when the phone is configured for IST). The helper requests .github/workflows/manual_production_update.yml on branch main with confirm_drive_upload=yes.

The workflow has a 90-minute job timeout. Its concurrency group prevents overlapping production runs; a new run does not cancel an already-running production run.

Keep the GitHub Actions workflow available for manual dispatch. Do not re-add a GitHub cron schedule while the Termux cron is active, or duplicate production runs may occur.

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

The recurring Termux cron job is active and is the **only automatic production scheduler**. It dispatches the GitHub Actions workflow every 3 hours. GitHub Actions itself has no cron schedule for this workflow.

The dispatch helper's successful response (HTTP 204 from GitHub) means GitHub accepted the dispatch request; it does **not** mean the workflow has finished. Check the GitHub Actions run and the completion email for the final result.

Existing Termux cron entries for other local tasks are separate and must be preserved. In particular, do not replace or remove unrelated SMS automation cron entries when maintaining this scheduler. Android must allow Termux and its cron service to run; after an Android restart, open Termux as required by the device setup. Autosync operates independently and periodically downloads the mobile PDF from Drive.

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

Completion emails are sent directly by the **production workflow** for both successful and failed runs, including runs dispatched by Termux and runs started manually in GitHub Actions.

### Direct completion webhook

At the end of .github/workflows/manual_production_update.yml, the step **Send completion email notification** runs with if: always(). It posts the production run ID, run URL, event, timing, and final conclusion to the notification Apps Script web app.

The notification step uses continue-on-error: true. Therefore, a webhook or email-notification failure is reported in that step's log but does not change the production job's success/failure result or undo a completed PDF upload.

The conclusion is reported as success only when both the production job and the scraper/upload step succeeded. Otherwise, the notification reports failure.

### Notification Apps Script

The notification receiver is a separate Apps Script project with a single live Code.gs file. Its deployed doPost(e) handler:

- Authenticates the request using the Script Property WEBHOOK_SECRET.
- Validates the workflow-run information and its conclusion.
- Uses a script lock and LAST_NOTIFIED_RUN_ID to reject duplicate or already-processed run IDs.
- Sends the completion email to ALERT_EMAIL.

The live notification project has no time-driven scheduler or polling trigger. It does not dispatch production runs and does not poll GitHub Actions. The old monitorProductionRun() polling monitor and Apps Script production dispatcher have been removed from the live project.

### Notification configuration

In the separate notification Apps Script project, configure these Script Properties:

- ALERT_EMAIL — destination email address.
- WEBHOOK_SECRET — shared secret used to authenticate incoming completion webhook requests.
- LAST_NOTIFIED_RUN_ID — notification cursor maintained by the webhook handler; it is updated automatically when a run is successfully processed. Do not reset it during routine operation.

Set the Apps Script project time zone to Asia/Kolkata.

Deploy the notification Apps Script as a web app that executes as the script owner and is accessible to the webhook caller. When changing the deployed code, update the existing web-app deployment to a new version and preserve its existing /exec URL.

Configure these GitHub Actions repository secrets:

- NOTIFICATION_WEBHOOK_URL — deployed notification Apps Script web-app URL.
- NOTIFICATION_WEBHOOK_SECRET — must match the Apps Script WEBHOOK_SECRET property.

Do not put secret values in this README or source control. No GitHub token or Apps Script polling trigger is required for the notification-only project.

## Repository layout

```text
.
├── .github/
│   └── workflows/
│       └── manual_production_update.yml
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
| `.github/workflows/manual_production_update.yml` | Production workflow, manual dispatch, and direct completion webhook notification |
| `GoogleAppsScript/Code.gs` | Google Drive PDF upload bridge |
| `GoogleAppsScript/Scheduler.gs` | Notification email helper/source reference; it is not a live scheduler or polling monitor |
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

In the separate live notification Apps Script project (single Code.gs file), configure ALERT_EMAIL and WEBHOOK_SECRET as described in [Email notifications](#email-notifications). LAST_NOTIFIED_RUN_ID is maintained by the webhook handler. The repository's GoogleAppsScript/Scheduler.gs is a helper/source-reference file, not the live deployed notification project.

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

Inspect the **Send completion email notification** step in the production workflow run and the notification Apps Script execution log. Confirm that ALERT_EMAIL and WEBHOOK_SECRET are set in the notification project, and that the GitHub Actions secrets NOTIFICATION_WEBHOOK_URL and NOTIFICATION_WEBHOOK_SECRET are configured and match. The notification step uses continue-on-error: true, so a notification failure does not fail an otherwise successful production run.

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

- **Automatic production scheduling:** Termux cron dispatches the GitHub Actions production workflow every 3 hours.
- **Manual production generation:** GitHub Actions workflow dispatch with confirm_drive_upload=yes.
- **GitHub Actions cron:** Removed; do not add a second schedule while Termux is active.
- **Adda247 fetching:** separate Apps Script proxy.
- **PDF upload:** separate Apps Script Drive bridge.
- **Completion email:** production workflow's final notification step → direct Apps Script webhook; no GitHub workflow_run notification workflow and no Apps Script polling monitor.
- **Notification Apps Script:** webhook receiver only; no scheduler triggers.
- **Android PDF download:** Autosync for Google Drive downloads the Mobile/Daily_Articles_Mobile.pdf file to the configured local folder.

The GitHub Actions production workflow remains manually dispatchable, while Termux supplies its recurring dispatches.