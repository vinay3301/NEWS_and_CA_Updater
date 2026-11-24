/**
 * NEWS & CA Updater — webhook email notification helpers.
 * Scheduling is handled exclusively by Termux.
 * Keep this file in the notification Apps Script project alongside doPost(e).
 * Set project timezone to Asia/Kolkata.
 *
 * Script Properties used by this notification handler:
 *   ALERT_EMAIL          Recipient for workflow notifications
 *   LAST_NOTIFIED_RUN_ID Webhook deduplication cursor
 */

const CONFIG = Object.freeze({
  TIMEZONE: 'Asia/Kolkata'
});

const PROP = Object.freeze({
  ALERT_EMAIL: 'ALERT_EMAIL',
  LAST_NOTIFIED_RUN: 'LAST_NOTIFIED_RUN_ID'
});

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
