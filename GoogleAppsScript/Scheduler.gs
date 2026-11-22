/**
 * NEWS & CA Updater — independent Google Apps Script scheduler.
 * Separate Apps Script project; do not paste into the existing upload bridge.
 * Set project timezone to Asia/Kolkata.
 *
 * Script Properties:
 *   GITHUB_TOKEN  Fine-grained PAT: Actions Read and write on this repo
 *   ALERT_EMAIL   Address for scheduler/workflow alerts
 *
 * Run testGitHubConnection() first. Do NOT run setupScheduler() until the
 * GitHub Actions cron is disabled, or both schedulers may launch duplicate PDFs.
 */

const CONFIG = Object.freeze({
  OWNER: 'vinay3301',
  REPO: 'NEWS_and_CA_Updater',
  WORKFLOW: 'manual_production_update.yml',
  BRANCH: 'main',
  TIMEZONE: 'Asia/Kolkata',
  HOURS: [2, 6, 10, 14, 18, 22],
  POLL_MINUTES: 10,
  SLOT_GRACE_MINUTES: 55,
  DISPATCH_GRACE_MINUTES: 20
});

const PROP = Object.freeze({
  TOKEN: 'GITHUB_TOKEN',
  ALERT_EMAIL: 'ALERT_EMAIL',
  PENDING_AT: 'PENDING_DISPATCH_AT',
  PENDING_BASELINE_ID: 'PENDING_BASELINE_RUN_ID',
  PENDING_SLOT: 'PENDING_DISPATCH_SLOT',
  LAST_NOTIFIED_RUN: 'LAST_NOTIFIED_RUN_ID',
  LAST_SLOT: 'LAST_DISPATCH_SLOT'
});

/** Read-only test. Does not start a workflow or upload PDFs. */
function testGitHubConnection() {
  const response = githubRequest_('get', '/actions/workflows/' + CONFIG.WORKFLOW);
  if (response.getResponseCode() !== 200) {
    throw new Error('GitHub connection test failed: HTTP ' +
      response.getResponseCode() + ' — ' + response.getContentText());
  }
  const workflow = JSON.parse(response.getContentText());
  Logger.log('Connection OK. Workflow: %s; state: %s; path: %s',
    workflow.name, workflow.state, workflow.path);
  return { ok: true, name: workflow.name, state: workflow.state };
}

/**
 * Install the dispatcher and monitor.
 * Seeds the notification cursor to the latest existing run, preventing old
 * workflow history from generating a flood of emails on first setup.
 */
function setupScheduler() {
  const props = PropertiesService.getScriptProperties();
  seedNotificationCursor_(props);
  const handlers = ['scheduledProductionDispatch', 'monitorProductionRun'];
  ScriptApp.getProjectTriggers().forEach(function(trigger) {
    if (handlers.indexOf(trigger.getHandlerFunction()) !== -1) {
      ScriptApp.deleteTrigger(trigger);
    }
  });

  ScriptApp.newTrigger('scheduledProductionDispatch')
    .timeBased().everyMinutes(CONFIG.POLL_MINUTES).create();
  ScriptApp.newTrigger('monitorProductionRun')
    .timeBased().everyMinutes(CONFIG.POLL_MINUTES).create();

  Logger.log('Installed dispatcher and monitor. Completion emails cover manual and scheduled workflow runs.');
}

/**
 * Safe transition step: installs only the email monitor.
 * It does not dispatch production workflows or alter the GitHub cron.
 */
function setupNotificationMonitor() {
  const props = PropertiesService.getScriptProperties();
  seedNotificationCursor_(props);

  ScriptApp.getProjectTriggers().forEach(function(trigger) {
    if (trigger.getHandlerFunction() === 'monitorProductionRun') {
      ScriptApp.deleteTrigger(trigger);
    }
  });
  ScriptApp.newTrigger('monitorProductionRun')
    .timeBased().everyMinutes(CONFIG.POLL_MINUTES).create();

  Logger.log('Installed notification-only monitor. It will email results for manual and scheduled runs; no production workflow was started.');
}

/** Seed at the latest existing run so setup does not email old run history. */
function seedNotificationCursor_(props) {
  if (!props.getProperty(PROP.LAST_NOTIFIED_RUN)) {
    const existing = getWorkflowRuns_(null, 100);
    const latestId = existing.reduce(function(maxId, run) {
      return Math.max(maxId, Number(run.id) || 0);
    }, 0);
    props.setProperty(PROP.LAST_NOTIFIED_RUN, String(latestId));
    Logger.log('Notification baseline set to existing workflow run ID %s.', latestId);
  }
}

/** Runs every 10 minutes and dispatches at most once per configured IST slot. */
function scheduledProductionDispatch() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(10000)) {
    Logger.log('Another scheduler execution holds the lock; skipping.');
    return;
  }

  try {
    const props = PropertiesService.getScriptProperties();
    if (props.getProperty(PROP.PENDING_AT)) {
      Logger.log('A previous Apps Script dispatch is still pending; waiting for monitor.');
      return;
    }

    const now = new Date();
    const hour = Number(Utilities.formatDate(now, CONFIG.TIMEZONE, 'H'));
    const minute = Number(Utilities.formatDate(now, CONFIG.TIMEZONE, 'm'));
    if (CONFIG.HOURS.indexOf(hour) === -1 || minute > CONFIG.SLOT_GRACE_MINUTES) return;

    const slot = Utilities.formatDate(now, CONFIG.TIMEZONE, 'yyyy-MM-dd-HH');
    if (props.getProperty(PROP.LAST_SLOT) === slot) {
      Logger.log('Slot %s was already dispatched; skipping.', slot);
      return;
    }

    const previousRuns = getWorkflowRuns_(null, 100);
    const active = previousRuns.find(function(run) {
      return (run.event === 'workflow_dispatch' || run.event === 'schedule') &&
        (run.status === 'queued' || run.status === 'in_progress');
    });
    if (active) {
      notify_('NEWS CA scheduler skipped a slot',
        'An earlier workflow_dispatch run is still ' + active.status +
        '. No second run was started.\n' + active.html_url);
      props.setProperty(PROP.LAST_SLOT, slot);
      return;
    }

    const baselineId = previousRuns.reduce(function(maxId, run) {
      return Math.max(maxId, Number(run.id) || 0);
    }, 0);
    const dispatchAt = Date.now();

    props.setProperty(PROP.PENDING_AT, String(dispatchAt));
    props.setProperty(PROP.PENDING_BASELINE_ID, String(baselineId));
    props.setProperty(PROP.PENDING_SLOT, slot);
    props.setProperty(PROP.LAST_SLOT, slot);

    const response = githubRequest_('post',
      '/actions/workflows/' + CONFIG.WORKFLOW + '/dispatches', {
        ref: CONFIG.BRANCH,
        inputs: { confirm_drive_upload: 'yes' }
      });

    if (response.getResponseCode() !== 204) {
      clearPending_(props);
      props.deleteProperty(PROP.LAST_SLOT);
      throw new Error('Workflow dispatch failed: HTTP ' +
        response.getResponseCode() + ' — ' + response.getContentText());
    }
    Logger.log('GitHub accepted workflow dispatch for IST slot %s.', slot);
  } catch (error) {
    notify_('NEWS CA scheduler could not confirm workflow dispatch',
      String(error && error.stack ? error.stack : error));
    throw error;
  } finally {
    lock.releaseLock();
  }
}

/**
 * Emails the result of EVERY new workflow_dispatch run, regardless of whether
 * it was started from GitHub's UI or by this Apps Script scheduler.
 */
function monitorProductionRun() {
  const props = PropertiesService.getScriptProperties();

  try {
    const runs = getWorkflowRuns_(null, 100);
    const lastNotified = Number(props.getProperty(PROP.LAST_NOTIFIED_RUN) || 0);

    // API returns newest first; process in ascending ID order so an older
    // still-running job cannot be skipped when a newer job finishes first.
    runs.sort(function(a, b) { return Number(a.id) - Number(b.id); });

    for (let i = 0; i < runs.length; i++) {
      const run = runs[i];
      if (Number(run.id) <= lastNotified) continue;
      if (run.head_branch !== CONFIG.BRANCH) continue;
      if (run.event !== 'workflow_dispatch' && run.event !== 'schedule') continue;
      if (run.status !== 'completed') break;

      const successful = run.conclusion === 'success';
      sendWorkflowStatusEmail_(run, successful);
      props.setProperty(PROP.LAST_NOTIFIED_RUN, String(run.id));
    }

    checkPendingDispatch_(props, runs);
  } catch (error) {
    Logger.log('Run monitor error: ' + error);
    notify_('NEWS CA scheduler monitor encountered an error',
      String(error && error.stack ? error.stack : error));
    throw error;
  }
}

/** Alert if an Apps Script dispatch never appears as a GitHub run. */
function checkPendingDispatch_(props, runs) {
  const pendingAt = Number(props.getProperty(PROP.PENDING_AT) || 0);
  if (!pendingAt) return;

  const baselineId = Number(props.getProperty(PROP.PENDING_BASELINE_ID) || 0);
  const matchingRun = runs.find(function(run) {
    return Number(run.id) > baselineId &&
      new Date(run.created_at).getTime() >= pendingAt - 2 * 60 * 1000 &&
      run.head_branch === CONFIG.BRANCH;
  });

  if (matchingRun) {
    if (matchingRun.status === 'completed') clearPending_(props);
    return;
  }

  if (Date.now() - pendingAt > CONFIG.DISPATCH_GRACE_MINUTES * 60 * 1000) {
    notify_('NEWS CA workflow dispatch not visible in GitHub',
      'Apps Script sent the dispatch request, but no new matching workflow run ' +
      'appeared within ' + CONFIG.DISPATCH_GRACE_MINUTES +
      ' minutes. Check GitHub Actions. The slot will not be automatically retried.');
    clearPending_(props);
  }
}

function clearPending_(props) {
  props.deleteProperty(PROP.PENDING_AT);
  props.deleteProperty(PROP.PENDING_BASELINE_ID);
  props.deleteProperty(PROP.PENDING_SLOT);
}

function getWorkflowRuns_(event, limit) {
  const path = '/actions/workflows/' + CONFIG.WORKFLOW +
    '/runs?' + (event ? 'event=' + encodeURIComponent(event) + '&' : '') +
    'per_page=' + limit;
  const response = githubRequest_('get', path);
  if (response.getResponseCode() !== 200) {
    throw new Error('Could not read workflow runs: HTTP ' +
      response.getResponseCode() + ' — ' + response.getContentText());
  }
  return JSON.parse(response.getContentText()).workflow_runs || [];
}

function githubRequest_(method, path, payload) {
  const token = PropertiesService.getScriptProperties().getProperty(PROP.TOKEN);
  if (!token) throw new Error('Missing Script Property GITHUB_TOKEN.');
  const options = {
    method: method,
    headers: {
      Authorization: 'Bearer ' + token,
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28'
    },
    muteHttpExceptions: true
  };
  if (payload) {
    options.contentType = 'application/json';
    options.payload = JSON.stringify(payload);
  }
  return UrlFetchApp.fetch(
    'https://api.github.com/repos/' + CONFIG.OWNER + '/' + CONFIG.REPO + path,
    options
  );
}


/**
 * Send a readable HTML status report for a completed production workflow.
 * A successful run means both required PDF upload steps completed. On failure,
 * the email deliberately does not guess which upload step succeeded.
 */
function sendWorkflowStatusEmail_(run, successful) {
  const email = PropertiesService.getScriptProperties().getProperty(PROP.ALERT_EMAIL);
  if (!email) {
    Logger.log('ALERT_EMAIL is not configured. Workflow run %s was %s.',
      run.id, run.conclusion);
    return;
  }

  const startedAt = run.run_started_at || run.created_at;
  const finishedAt = run.updated_at || '';
  const startedText = formatIst_(startedAt);
  const finishedText = formatIst_(finishedAt);
  const durationText = formatRunDuration_(startedAt, finishedAt);
  const statusText = successful ? 'SUCCESS' : String(run.conclusion || 'FAILED').toUpperCase();
  const statusColor = successful ? '#137333' : '#b3261e';
  const statusBg = successful ? '#e6f4ea' : '#fce8e6';
  const workflowName = run.name || 'Production News & CA PDF Update';
  const triggerText = run.event === 'schedule' ? 'Scheduled' : 'Manual';
  const uploadText = successful
    ? 'Both desktop and mobile PDFs uploaded successfully to Google Drive.'
    : 'Upload completion is not confirmed. Open the workflow run to see which steps completed.';
  const subject = successful
    ? 'NEWS & CURRENT AFFAIRS | Workflow SUCCESS'
    : 'NEWS & CURRENT AFFAIRS | Workflow FAILED';

  const plainBody = [
    'NEWS & CURRENT AFFAIRS — WORKFLOW REPORT',
    'STATUS: ' + statusText,
    '',
    'Workflow: ' + workflowName,
    'Trigger: ' + triggerText,
    'Conclusion: ' + statusText,
    'Started (IST): ' + startedText,
    'Completed (IST): ' + finishedText,
    'Duration: ' + durationText,
    'PDF upload status: ' + uploadText,
    '',
    'GitHub Actions run: ' + (run.html_url || '')
  ].join('\n');

  const safeRunUrl = escapeHtml_(run.html_url || '');
  const htmlBody = `
    <div style="margin:0;padding:24px 12px;background:#f3f5f7;font-family:Arial,Helvetica,sans-serif;color:#202124;">
      <div style="max-width:680px;margin:0 auto;background:#ffffff;border:1px solid #e0e3e7;border-radius:12px;overflow:hidden;">
        <div style="padding:24px 28px;background:#172b4d;color:#ffffff;">
          <div style="font-size:12px;font-weight:700;letter-spacing:1.4px;color:#d5e2f5;">AUTOMATION NOTIFICATION</div>
          <div style="font-size:23px;line-height:1.3;font-weight:700;margin-top:8px;">NEWS &amp; CURRENT AFFAIRS</div>
          <div style="font-size:15px;color:#e4ebf5;margin-top:5px;">Production workflow report</div>
        </div>
        <div style="padding:26px 28px;">
          <div style="display:inline-block;padding:9px 16px;border-radius:7px;background:${statusBg};color:${statusColor};font-size:16px;font-weight:700;letter-spacing:.5px;">
            ${escapeHtml_(statusText)}
          </div>
          <p style="font-size:15px;line-height:1.6;margin:18px 0 22px;color:#3c4043;">
            ${successful
              ? 'The production workflow completed successfully. The required PDF generation and Google Drive upload steps finished.'
              : 'The production workflow did not complete successfully. Open the GitHub Actions report below to identify the failed step.'}
          </p>

          <div style="font-size:17px;font-weight:700;color:#172b4d;padding-bottom:10px;border-bottom:2px solid #e8edf3;margin-bottom:12px;">WORKFLOW DETAILS</div>
          <table role="presentation" style="width:100%;border-collapse:collapse;font-size:14px;line-height:1.5;">
            <tr><td style="padding:9px 8px 9px 0;color:#5f6368;width:38%;border-bottom:1px solid #edf0f2;">Workflow</td><td style="padding:9px 0;font-weight:700;color:#202124;border-bottom:1px solid #edf0f2;">${escapeHtml_(workflowName)}</td></tr>
            <tr><td style="padding:9px 8px 9px 0;color:#5f6368;border-bottom:1px solid #edf0f2;">Trigger</td><td style="padding:9px 0;font-weight:700;color:#202124;border-bottom:1px solid #edf0f2;">${escapeHtml_(triggerText)}</td></tr>
            <tr><td style="padding:9px 8px 9px 0;color:#5f6368;border-bottom:1px solid #edf0f2;">Conclusion</td><td style="padding:9px 0;font-weight:700;color:${statusColor};border-bottom:1px solid #edf0f2;">${escapeHtml_(statusText)}</td></tr>
            <tr><td style="padding:9px 8px 9px 0;color:#5f6368;border-bottom:1px solid #edf0f2;">Started (IST)</td><td style="padding:9px 0;font-weight:600;color:#202124;border-bottom:1px solid #edf0f2;">${escapeHtml_(startedText)}</td></tr>
            <tr><td style="padding:9px 8px 9px 0;color:#5f6368;border-bottom:1px solid #edf0f2;">Completed (IST)</td><td style="padding:9px 0;font-weight:600;color:#202124;border-bottom:1px solid #edf0f2;">${escapeHtml_(finishedText)}</td></tr>
            <tr><td style="padding:9px 8px 9px 0;color:#5f6368;">Total duration</td><td style="padding:9px 0;font-weight:700;color:#202124;">${escapeHtml_(durationText)}</td></tr>
          </table>

          <div style="margin-top:24px;padding:16px 18px;border:1px solid ${successful ? '#cce8d3' : '#f2c7c5'};border-left:5px solid ${statusColor};border-radius:8px;background:${successful ? '#f6fbf7' : '#fff8f7'};">
            <div style="font-size:15px;font-weight:700;color:#202124;margin-bottom:7px;">PDF UPLOAD STATUS</div>
            <div style="font-size:14px;line-height:1.6;color:#3c4043;">${escapeHtml_(uploadText)}</div>
          </div>

          <div style="margin-top:26px;text-align:center;">
            <a href="${safeRunUrl}" style="display:inline-block;padding:13px 22px;background:#1967d2;color:#ffffff;text-decoration:none;border-radius:7px;font-size:15px;font-weight:700;">
              OPEN GITHUB ACTIONS RUN
            </a>
          </div>
          <div style="margin-top:22px;padding-top:14px;border-top:1px solid #edf0f2;font-size:12px;line-height:1.5;color:#80868b;">
            Automated notification from NEWS &amp; CURRENT AFFAIRS Updater.
          </div>
        </div>
      </div>
    </div>`;

  MailApp.sendEmail({
    to: email,
    subject: subject,
    body: plainBody,
    htmlBody: htmlBody
  });
}

function formatIst_(dateValue) {
  if (!dateValue) return 'Not available';
  const date = new Date(dateValue);
  if (isNaN(date.getTime())) return 'Not available';
  return Utilities.formatDate(date, CONFIG.TIMEZONE, 'dd MMM yyyy, hh:mm:ss a');
}

function formatRunDuration_(startValue, endValue) {
  if (!startValue || !endValue) return 'Not available';
  const seconds = Math.max(0, Math.round((new Date(endValue).getTime() -
    new Date(startValue).getTime()) / 1000));
  if (!isFinite(seconds)) return 'Not available';
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainingSeconds = seconds % 60;
  return (hours ? hours + 'h ' : '') +
    (minutes ? minutes + 'm ' : '') + remainingSeconds + 's';
}

function escapeHtml_(value) {
  return String(value == null ? '' : value).replace(/[&<>"']/g, function(char) {
    return {
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;'
    }[char];
  });
}

function notify_(subject, body) {
  const email = PropertiesService.getScriptProperties().getProperty(PROP.ALERT_EMAIL);
  if (!email) {
    Logger.log('ALERT_EMAIL is not configured. Alert: %s\n%s', subject, body);
    return;
  }
  MailApp.sendEmail({ to: email, subject: subject, body: body });
}

/** Remove only this scheduler's triggers; does not alter GitHub workflow. */
function removeSchedulerTriggers() {
  const handlers = ['scheduledProductionDispatch', 'monitorProductionRun'];
  ScriptApp.getProjectTriggers().forEach(function(trigger) {
    if (handlers.indexOf(trigger.getHandlerFunction()) !== -1) {
      ScriptApp.deleteTrigger(trigger);
    }
  });
  Logger.log('Scheduler triggers removed.');
}
