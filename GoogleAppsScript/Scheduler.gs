/**
 * NEWS & CA Updater — independent Google Apps Script scheduler.
 *
 * This is a SEPARATE Apps Script project. Do not paste into the existing
 * PDF upload bridge project. Set project timezone to Asia/Kolkata.
 *
 * Script Properties required:
 *   GITHUB_TOKEN  Fine-grained PAT with Actions: Read and write on this repo
 *   ALERT_EMAIL   Email address for run result alerts
 *
 * First run testGitHubConnection() (read-only), then setupScheduler().
 * Do not enable this scheduler until the GitHub cron is disabled, otherwise
 * the old cron and this scheduler can launch duplicate production runs.
 */

const CONFIG = Object.freeze({
  OWNER: 'vinay3301',
  REPO: 'NEWS_and_CA_Updater',
  WORKFLOW: 'manual_production_update.yml',
  BRANCH: 'main',
  TIMEZONE: 'Asia/Kolkata',
  HOURS: [2, 6, 10, 14, 18, 22],
  MONITOR_MINUTES: 10,
  DISPATCH_GRACE_MINUTES: 20
});

const PROP = Object.freeze({
  TOKEN: 'GITHUB_TOKEN',
  ALERT_EMAIL: 'ALERT_EMAIL',
  PENDING_AT: 'PENDING_DISPATCH_AT',
  LAST_NOTIFIED_RUN: 'LAST_NOTIFIED_RUN_ID',
  LAST_SLOT: 'LAST_DISPATCH_SLOT'
});

/** Read-only connection test. Does not start a workflow or upload PDFs. */
function testGitHubConnection() {
  const response = githubRequest_(
    'get',
    '/actions/workflows/' + CONFIG.WORKFLOW
  );
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
 * Install six daily time-driven triggers and a 10-minute run monitor.
 * Run once only after the GitHub cron has been disabled.
 */
function setupScheduler() {
  const handlers = ['scheduledProductionDispatch', 'monitorProductionRun'];
  ScriptApp.getProjectTriggers().forEach(function(trigger) {
    if (handlers.indexOf(trigger.getHandlerFunction()) !== -1) {
      ScriptApp.deleteTrigger(trigger);
    }
  });

  CONFIG.HOURS.forEach(function(hour) {
    ScriptApp.newTrigger('scheduledProductionDispatch')
      .timeBased()
      .atHour(hour)
      .nearMinute(0)
      .everyDays(1)
      .inTimezone(CONFIG.TIMEZONE)
      .create();
  });

  ScriptApp.newTrigger('monitorProductionRun')
    .timeBased()
    .everyMinutes(CONFIG.MONITOR_MINUTES)
    .create();

  Logger.log('Installed 6 daily dispatch triggers (IST) and 10-minute monitor.');
}

/** Called by each daily time trigger. */
function scheduledProductionDispatch() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(10000)) {
    Logger.log('Another scheduler execution holds the lock; skipping.');
    return;
  }

  try {
    const now = new Date();
    const hour = Number(Utilities.formatDate(now, CONFIG.TIMEZONE, 'H'));
    if (CONFIG.HOURS.indexOf(hour) === -1) {
      Logger.log('Trigger fired outside configured hour; skipping: ' + now);
      return;
    }

    const slot = Utilities.formatDate(now, CONFIG.TIMEZONE, 'yyyy-MM-dd-HH');
    const props = PropertiesService.getScriptProperties();
    if (props.getProperty(PROP.LAST_SLOT) === slot) {
      Logger.log('Duplicate trigger for slot %s; skipping.', slot);
      return;
    }

    // Avoid overlapping production jobs. Do not dispatch if an earlier run
    // is queued or in progress.
    const active = getWorkflowRuns_('workflow_dispatch', 10).find(function(run) {
      return run.status === 'queued' || run.status === 'in_progress';
    });
    if (active) {
      notify_('NEWS CA scheduler skipped a slot',
        'An earlier manual production workflow is still ' + active.status +
        '. No second run was started.\n' + active.html_url);
      return;
    }

    const body = {
      ref: CONFIG.BRANCH,
      inputs: { confirm_drive_upload: 'yes' }
    };
    const response = githubRequest_(
      'post',
      '/actions/workflows/' + CONFIG.WORKFLOW + '/dispatches',
      body
    );

    if (response.getResponseCode() !== 204) {
      throw new Error('Workflow dispatch failed: HTTP ' +
        response.getResponseCode() + ' — ' + response.getContentText());
    }

    props.setProperty(PROP.LAST_SLOT, slot);
    props.setProperty(PROP.PENDING_AT, String(Date.now()));
    Logger.log('GitHub accepted production workflow dispatch for slot %s.', slot);
  } catch (error) {
    notify_('NEWS CA scheduler could not start production workflow',
      String(error && error.stack ? error.stack : error));
    throw error;
  } finally {
    lock.releaseLock();
  }
}

/** Poll GitHub for the dispatched run and email its final result. */
function monitorProductionRun() {
  const props = PropertiesService.getScriptProperties();
  const pendingAt = Number(props.getProperty(PROP.PENDING_AT) || 0);
  if (!pendingAt) return;

  const runs = getWorkflowRuns_('workflow_dispatch', 10);
  const run = runs.find(function(item) {
    return new Date(item.created_at).getTime() >= pendingAt - 3 * 60 * 1000;
  });

  if (!run) {
    if (Date.now() - pendingAt > CONFIG.DISPATCH_GRACE_MINUTES * 60 * 1000) {
      notify_('NEWS CA workflow dispatch not visible in GitHub',
        'Apps Script sent the workflow_dispatch request, but no matching run ' +
        'appeared within ' + CONFIG.DISPATCH_GRACE_MINUTES + ' minutes. Check GitHub Actions.');
      props.deleteProperty(PROP.PENDING_AT);
    }
    return;
  }

  if (run.status !== 'completed') return;

  if (props.getProperty(PROP.LAST_NOTIFIED_RUN) === String(run.id)) {
    props.deleteProperty(PROP.PENDING_AT);
    return;
  }

  const successful = run.conclusion === 'success';
  notify_(
    successful ? 'NEWS CA PDFs uploaded successfully' : 'NEWS CA production workflow failed',
    'Workflow: ' + run.name + '\nConclusion: ' + run.conclusion +
    '\nStarted: ' + run.created_at + '\nRun: ' + run.html_url +
    (successful
      ? '\nThe workflow completed successfully, including its PDF upload step.'
      : '\nOpen the run link to inspect the failed step.')
  );

  props.setProperty(PROP.LAST_NOTIFIED_RUN, String(run.id));
  props.deleteProperty(PROP.PENDING_AT);
}

function getWorkflowRuns_(event, limit) {
  const path = '/actions/workflows/' + CONFIG.WORKFLOW +
    '/runs?event=' + encodeURIComponent(event) + '&per_page=' + limit;
  const response = githubRequest_('get', path);
  if (response.getResponseCode() !== 200) {
    throw new Error('Could not read workflow runs: HTTP ' +
      response.getResponseCode() + ' — ' + response.getContentText());
  }
  return (JSON.parse(response.getContentText()).workflow_runs || []);
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

function notify_(subject, body) {
  const email = PropertiesService.getScriptProperties().getProperty(PROP.ALERT_EMAIL);
  if (!email) {
    Logger.log('ALERT_EMAIL is not configured. Alert: %s\n%s', subject, body);
    return;
  }
  MailApp.sendEmail({ to: email, subject: subject, body: body });
}

/** Remove only this scheduler's triggers; does not change GitHub workflow. */
function removeSchedulerTriggers() {
  const handlers = ['scheduledProductionDispatch', 'monitorProductionRun'];
  ScriptApp.getProjectTriggers().forEach(function(trigger) {
    if (handlers.indexOf(trigger.getHandlerFunction()) !== -1) {
      ScriptApp.deleteTrigger(trigger);
    }
  });
  Logger.log('Scheduler triggers removed.');
}
