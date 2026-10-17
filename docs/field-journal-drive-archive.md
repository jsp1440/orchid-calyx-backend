# Field Journal media archive in Google Drive

The Field Journal keeps every uploaded original photo and video byte-for-byte.
The backend first writes the original to local storage (`FIELD_MEDIA_STORAGE_DIR`).
On Render without a paid disk, that storage is lost on every redeploy. So the
backend also copies each original into the owner's own Google Drive. An upload
reports `durability: "durable"` only after Drive confirms that its copy matches
the original exactly.

No paid service is involved. The archive uses the owner's existing Google Drive
storage.

## How it behaves

| Situation | Upload response |
|-----------|-----------------|
| Archive configured; Drive's `md5Checksum` and `size` match the original | `201`, `durability: "durable"`, `archive: {"provider": "google_drive", "state": "verified", "drive_file_id": "…"}` |
| Archive configured; Drive fails, times out, or reports a different checksum | `201`, `archive.state: "pending"` with an `error_code`. `durability` is as before: `durable` only if `FIELD_MEDIA_STORAGE_DURABLE=true`, otherwise `not_guaranteed`. |
| Archive not configured | `201`, `archive.state: "not_configured"`. `durability` is as above. |

- A Drive problem never fails an upload. The original is still kept locally.
- When the Field Journal re-uploads the same bytes (its normal idempotent
  retry), the server tries the pending archive again. Once a copy is
  verified, a re-upload does not upload anything new to Drive.
- `POST /api/field-observations/archive/retry?limit=10` retries pending
  archives for originals whose bytes are still held locally. Each request
  handles at most 10 items and stops after 120 seconds. `pending_after` says
  how many still need archiving; call it again until that is `0`. It needs the
  owner session, or the API key without `X-Auth-Subject`.
- A verified archive state is never downgraded. A slow attempt that times out
  after another attempt succeeded cannot mark the copy pending again.
- `GET /api/field-observations/archive/status` returns counts by state and
  error code. It contains no ids, names, observers or locality. Add
  `?probe=true` to make one read-only Drive call that proves the credentials
  work.
- Readback (`GET …/media/{sha256}/original`): if the local file has gone, the
  server downloads the verified Drive copy. It checks the MD5, size and SHA-256
  before serving the copy (`X-Field-Media-Source: google_drive_archive`), then
  caches it locally again. A copy that fails verification is refused with
  `502`. A Drive outage returns `503`. An original that was never archived
  still returns `410`.

### What lands in Drive

- **One folder:** "Orchid Continuum — Field Journal Media Archive", or the name
  set in `FIELD_MEDIA_DRIVE_FOLDER_NAME`. It is created in My Drive on the first
  upload. The backend finds it again by a hidden app marker
  (`appProperties.oc_archive`), not by its name. Renaming or moving the folder
  is therefore safe, but **do not delete it**.
- **One subfolder per observation**, named with the opaque observation id
  (`fo-…`).
- **Files:** each file is named `{first 16 hex characters of its SHA-256}{ext}`,
  for example `3f9a…c2e1.jpg`. The extension comes from a fixed list of
  photo/video types, otherwise `.bin`. The user's original filename might name
  a place, so it is kept **only** in the backend's private provenance record.
  It never appears in a Drive name, description or property. The hidden
  properties are `oc_observation_id`, `oc_sha256` and `oc_client_media_id`
  only; an id that looks like a coordinate is left out.
- **No coordinates, locality, notes or observer identity** are written to any
  Drive name or property.
- **No sharing:** the backend never creates sharing permissions, so files stay
  private to the owner. Camera originals are unmodified, so their EXIF data
  may include device GPS. Do not share the archive folder.

### Coexistence with the Google Forms

The archive uses the `https://www.googleapis.com/auth/drive.file` scope. With
that scope Google lets the app see **only files the app created itself**. The
app cannot list, read, move, change or delete the existing Google Forms, their
response spreadsheets, or their file-upload response folders. Google enforces
this limit, not just this code, so the forms keep working exactly as they do
today. The code also scopes every lookup by its own app marker. The tests
(`tests/test_field_observation_drive_archive.py`) check that it never refers to
an item it did not create.

## Owner setup (one time, about 15 minutes)

You need the Google account that owns the Drive (the owner's personal Gmail account; its address is deliberately not recorded in this public repository).
**Do not use a service account.** Google service accounts have no storage
quota in a personal My Drive, so uploads would fail. The backend rejects
service-account JSON with an error that says so.

### 1. Create a Google Cloud project

1. Open <https://console.cloud.google.com/> signed in as the Drive owner's Gmail account.
2. Create a project, for example "Orchid Continuum Field Archive". No billing
   account is needed.

### 2. Enable the Google Drive API

APIs & Services → Library → "Google Drive API" → **Enable**.

### 3. Configure the OAuth consent screen

APIs & Services → OAuth consent screen (in newer consoles: Google Auth
Platform → Branding / Audience / Data access):

1. **User type:** External.
2. **App name:** for example "Orchid Continuum Field Archive". Set the support
   and developer email to that same address.
3. **Scopes (Data access):** add only
   `https://www.googleapis.com/auth/drive.file`. Add no other Drive scope.
4. **Test users:** add the Drive owner's Gmail address.

**Testing vs. production status.** While the app's publishing status is
**Testing**, Google expires its refresh tokens after **7 days**. The archive
would then stop working (`error_code: drive_credentials_invalid`) until a new
token is issued. To avoid this, go to Audience → **Publish app** to move it to
**In production** *before* creating the refresh token in step 5.

`drive.file` is a *non-sensitive* scope. An app that requests only
non-sensitive scopes does not need Google's verification review to be
published. You may see an "unverified app" notice once when you authorise it
yourself. That is expected for a personal app: choose *Advanced → Go to …* and
continue. No one else ever signs in to this app.

### 4. Create an OAuth client

APIs & Services → Credentials → **Create credentials → OAuth client ID** →
Application type **Desktop app**. Download the client JSON (for example
`client_secret.json`) and keep it private.

### 5. Obtain a refresh token (on your own computer)

Install the helper library locally. It is not a backend dependency.

```bash
python3 -m venv oc-drive && . oc-drive/bin/activate
pip install google-auth-oauthlib
```

Save this as `get_drive_token.py` in the folder that holds `client_secret.json`:

```python
"""Prints FIELD_MEDIA_DRIVE_CREDENTIALS_JSON for the Field Journal archive."""
import json

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/drive.file"]

flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", SCOPES)
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
print(json.dumps({
    "type": "authorized_user",
    "client_id": creds.client_id,
    "client_secret": creds.client_secret,
    "refresh_token": creds.refresh_token,
}))
```

The backend uses only `client_id`, `client_secret` and `refresh_token` (plus
`token_uri` if present). It ignores any `token`, `expiry` or `scopes` in the
JSON and always requests the `drive.file` scope.

Run `python get_drive_token.py`. A browser opens. Sign in as
the Drive owner's account and allow access to "files created by this app". The
script prints one line of JSON. That line is a credential: do not commit it,
paste it into an issue or chat, or email it.

### 6. Set it on the Render backend

Render dashboard → the Calyx backend service → Environment:

| Variable | Value |
|----------|-------|
| `FIELD_MEDIA_DRIVE_CREDENTIALS_JSON` | the JSON line from step 5 (mark it secret) |
| `FIELD_MEDIA_DRIVE_FOLDER_NAME` | optional; the folder name used when the archive folder is first created |
| `FIELD_MEDIA_DRIVE_TIMEOUT_SECONDS` | optional; per-upload Drive time limit, default `60`, range 1–600 |

Save. Render then redeploys the service.

### 7. Verify

With the owner session (or the backend API key, without `X-Auth-Subject`):

```
GET /api/field-observations/archive/status?probe=true
```

Expect `"configured": true` and `"probe": {"ok": true, …}`.
`archive_folder_present` becomes `true` after the first upload. Then upload a
test photo from the Field Journal. Its response should show
`"durability": "durable"` and `"archive": {"state": "verified", …}`. The file
should appear in the archive folder in Drive. If any media were uploaded before
the archive was configured, run `POST /api/field-observations/archive/retry`
until `remaining` is `0`. Only media whose bytes are still on the server can be
archived. `unarchived_without_local_bytes` counts the rest, which must be
re-uploaded from the device.

## Troubleshooting

| `error_code` | Meaning | Action |
|--------------|---------|--------|
| `drive_not_configured` | `FIELD_MEDIA_DRIVE_CREDENTIALS_JSON` is unset | Complete the setup above |
| `drive_credentials_invalid` | JSON invalid, a service account, missing fields, or the refresh token was revoked or expired (Testing-status apps expire after 7 days) | Publish the app to production, repeat step 5, update the variable |
| `drive_timeout` | Drive did not finish within the time limit | Usually transient; the next re-upload or `archive/retry` reuses any copy that did arrive |
| `drive_verification_failed` | Drive's checksum or size differed from the original | Retry; the original is never reported durable on a mismatch |
| `drive_unavailable` | Other Drive/API error | Retry later; check the Drive API is enabled |
| `local_bytes_missing` | The server copy was lost before it was archived | Re-upload from the Field Journal device |

To revoke access at any time: <https://myaccount.google.com/permissions> →
remove the app. Uploads then report `pending` and keep the local copy.
