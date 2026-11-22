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
  if (!props.getProperty(PROP.LAST_NOTIFIED_RUN)) {
    const existing = getWorkflowRuns_('workflow_dispatch', 100);
    const latestId = existing.reduce(function(maxId, run) {
      return Math.max(maxId, Number(run.id) || 0);
    }, 0);
    props.setProperty(PROP.LAST_NOTIFIED_RUN, String(latestId));
    Logger.log('Notification baseline set to existing workflow run ID %s.', latestId);
  }

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

  Logger.log('Installed dispatcher and monitor. Completion emails will cover both manually started and Apps Script-started workflow_dispatch runs.');
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

    const previousRuns = getWorkflowRuns_('workflow_dispatch', 100);
    const active = previousRuns.find(function(run) {
      return run.status === 'queued' || run.status === 'in_progress';
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
    const runs = getWorkflowRuns_('workflow_dispatch', 100);
    const lastNotified = Number(props.getProperty(PROP.LAST_NOTIFIED_RUN) || 0);

    // API returns newest first; process in ascending ID order so an older
    // still-running job cannot be skipped when a newer job finishes first.
    runs.sort(function(a, b) { return Number(a.id) - Number(b.id); });

    for (let i = 0; i < runs.length; i++) {
      const run = runs[i];
      if (Number(run.id) <= lastNotified) continue;
      if (run.head_branch !== CONFIG.BRANCH) continue;
      if (run.status !== 'completed') break;

      const successful = run.conclusion === 'success';
      notify_(
        successful ? 'NEWS CA workflow completed successfully' : 'NEWS CA workflow failed',
        'Trigger: ' + run.event +
        '\nWorkflow: ' + run.name +
        '\nConclusion: ' + run.conclusion +
        '\nStarted: ' + run.created_at +
        '\nRun: ' + run.html_url +
        (successful
          ? '\nThe workflow completed successfully, including its PDF upload steps.'
          : '\nOpen the run link to inspect the failed step.')
      );
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
    '/runs?event=' + encodeURIComponent(event) + '&per_page=' + limit;
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
