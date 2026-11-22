# NEWS & Current Affairs PDF Updater

An automated news and current-affairs digest generator. It collects selected news and exam-relevant current-affairs articles, builds desktop and mobile-friendly PDFs, and publishes both PDFs to Google Drive.

The production workflow runs on GitHub Actions. Google Apps Script is used for the Adda247 fetch proxy and for the Google Drive upload bridge. A separate Apps Script project monitors workflow completion and emails the result.

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

`GoogleAppsScript/Scheduler.gs` belongs to a separate Apps Script project. In the current setup, only its notification-monitor function is installed:

- `setupNotificationMonitor()` installs a time-driven trigger every 10 minutes.
- `monitorProductionRun()` checks GitHub Actions for newly completed scheduled and manual workflow runs.
- It emails the configured address with the workflow result and a link to the GitHub run.
- It seeds its notification cursor from existing workflow history during setup, so old runs are not all emailed as new notifications.

The 10-minute trigger is a **monitoring interval**, not a production generation interval. It does not start a PDF run. It checks for completion and sends an email when a new run is completed.

Required Script Properties for this separate monitor project:

- `GITHUB_TOKEN` — a GitHub fine-grained personal access token with Actions read and write permission for this repository (write is needed only if using the optional dispatcher).
- `ALERT_EMAIL` — the address that should receive workflow notifications.

Set the Apps Script project time zone to `Asia/Kolkata`.

The optional `setupScheduler()` function installs both an Apps Script dispatcher and the monitor. It is an alternative scheduling arrangement, not something to enable alongside the active GitHub cron. If switching schedulers in the future, disable the GitHub cron first and deliberately migrate to the Apps Script dispatcher.

## Repository layout

```text
.
├── .github/
│   └── workflows/
│       ├── manual_production_update.yml
│       ├── test_adda_proxy.yml
│       └── test_adda_python_proxy.yml
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
| `.github/workflows/manual_production_update.yml` | Scheduled and manually approved production workflow |
| `.github/workflows/test_adda_proxy.yml` | Adda247 proxy diagnostic workflow |
| `.github/workflows/test_adda_python_proxy.yml` | Python-to-proxy integration diagnostic workflow |
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

### Notification monitor Script Properties

In the separate Apps Script project containing `Scheduler.gs`, configure `GITHUB_TOKEN` and `ALERT_EMAIL` as described in [Email notifications](#email-notifications).

## Android download workflow

Android delivery is a separate client-side step; it is not performed by GitHub Actions itself.

FolderSync can download the mobile PDF from the Google Drive `Mobile` folder to a dedicated phone folder such as `Download/Daily Articles`. Configure the folder pair as a one-way **To local folder** sync, filter it to `Daily_Articles_Mobile.pdf`, keep overwrite enabled, and keep sync deletions disabled so unrelated phone files are not removed.

The configured FolderSync schedule can periodically check Drive for an updated PDF. FolderSync must be allowed to run in the background by Android. The phone does not need to run the Python generator or keep Termux active for the GitHub-hosted production workflow.

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

Check the notification project's `ALERT_EMAIL` and `GITHUB_TOKEN` Script Properties, its Apps Script execution log, and whether the `monitorProductionRun` time-driven trigger exists. Remember that this monitor checks every 10 minutes; it does not email every time it polls.

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
- **Completion email:** Apps Script notification monitor, polling every 10 minutes.
- **Android PDF download:** FolderSync from Drive's `Mobile` folder.

The GitHub cron remains the only active production scheduler in this arrangement.