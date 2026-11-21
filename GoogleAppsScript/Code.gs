/**
 * NEWS and Current Affairs PDF upload bridge.
 *
 * Deploy as a Web App that executes as the script owner and accepts requests
 * from anyone. Every POST is protected by a long random shared secret.
 *
 * Required Script Properties:
 *   UPLOAD_SECRET    - long random secret shared with GitHub Actions
 *   DRIVE_FOLDER_ID  - existing desktop PDF folder ID
 *
 * Enable the Advanced Google service "Drive API" (v3) in this Apps Script
 * project before deploying.
 */

const DESKTOP_FOLDER_ID_PROPERTY = 'DRIVE_FOLDER_ID';
const SECRET_PROPERTY = 'UPLOAD_SECRET';
const MOBILE_FOLDER_NAME = 'Mobile';

function doGet() {
  return ContentService
    .createTextOutput(JSON.stringify({
      ok: true,
      service: 'NEWS CA PDF upload bridge',
      method: 'POST'
    }))
    .setMimeType(ContentService.MimeType.JSON);
}

function doPost(e) {
  try {
    if (!e || !e.postData || !e.postData.contents) {
      return jsonResponse(400, { ok: false, error: 'Missing request body' });
    }

    const payload = JSON.parse(e.postData.contents);
    const expectedSecret = PropertiesService
      .getScriptProperties()
      .getProperty(SECRET_PROPERTY);

    if (!expectedSecret || !payload.secret ||
        !constantTimeEquals(String(payload.secret), String(expectedSecret))) {
      return jsonResponse(401, { ok: false, error: 'Unauthorized' });
    }

    const allowedNames = ['Daily_Articles.pdf', 'Daily_Articles_Mobile.pdf'];
    const fileName = String(payload.fileName || '');
    if (allowedNames.indexOf(fileName) === -1) {
      return jsonResponse(400, { ok: false, error: 'File name not allowed' });
    }

    if (typeof payload.base64 !== 'string' || !payload.base64.length) {
      return jsonResponse(400, { ok: false, error: 'Missing PDF data' });
    }

    // Reject obviously oversized requests before decoding.
    if (payload.base64.length > 20 * 1024 * 1024) {
      return jsonResponse(413, { ok: false, error: 'PDF payload is too large' });
    }

    const properties = PropertiesService.getScriptProperties();
    const desktopFolderId = properties.getProperty(DESKTOP_FOLDER_ID_PROPERTY);
    if (!desktopFolderId) {
      throw new Error('Script property DRIVE_FOLDER_ID is not configured');
    }

    const desktopFolder = DriveApp.getFolderById(desktopFolderId);
    const destinationFolder = fileName === 'Daily_Articles_Mobile.pdf'
      ? getOrCreateSubfolder(desktopFolder, MOBILE_FOLDER_NAME)
      : desktopFolder;

    const bytes = Utilities.base64Decode(payload.base64);
    const blob = Utilities.newBlob(bytes, 'application/pdf', fileName);

    // Update the existing file in place to preserve its Drive file ID.
    const existing = findFileInFolder(destinationFolder.getId(), fileName);
    let saved;
    if (existing) {
      saved = Drive.Files.update(
        { name: fileName, mimeType: 'application/pdf' },
        existing.id,
        blob,
        { supportsAllDrives: true }
      );
    } else {
      saved = Drive.Files.create(
        {
          name: fileName,
          mimeType: 'application/pdf',
          parents: [destinationFolder.getId()]
        },
        blob,
        { supportsAllDrives: true, fields: 'id,name,mimeType,size,webViewLink' }
      );
    }

    return jsonResponse(200, {
      ok: true,
      fileName: fileName,
      fileId: saved.id,
      folderId: destinationFolder.getId(),
      size: bytes.length,
      action: existing ? 'updated' : 'created'
    });
  } catch (err) {
    console.error(err && err.stack ? err.stack : err);
    return jsonResponse(500, {
      ok: false,
      error: String(err && err.message ? err.message : err)
    });
  }
}

function getOrCreateSubfolder(parentFolder, folderName) {
  const folders = parentFolder.getFoldersByName(folderName);
  return folders.hasNext() ? folders.next() : parentFolder.createFolder(folderName);
}

function findFileInFolder(folderId, fileName) {
  const escapedName = fileName.replace(/\\'/g, "\\\\'");
  const response = Drive.Files.list({
    q: "'" + folderId + "' in parents and name = '" + escapedName + "' and trashed = false",
    pageSize: 10,
    fields: 'files(id,name)',
    supportsAllDrives: true,
    includeItemsFromAllDrives: true
  });
  return response.files && response.files.length ? response.files[0] : null;
}

function constantTimeEquals(a, b) {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) {
    diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return diff === 0;
}

function jsonResponse(statusCode, data) {
  // ContentService does not expose a custom HTTP status setter for web apps.
  // The JSON body includes ok/error; the GitHub client validates that body.
  data.status = statusCode;
  return ContentService
    .createTextOutput(JSON.stringify(data))
    .setMimeType(ContentService.MimeType.JSON);
}
