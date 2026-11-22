import os
import sys
import re
import time
import html
import json
import random
import shutil
import tempfile
import unicodedata
import subprocess
import requests
import feedparser
import urllib.request
from io import BytesIO
from bs4 import BeautifulSoup, NavigableString, Tag
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from oauth2client.service_account import ServiceAccountCredentials
from google.oauth2.credentials import Credentials as GoogleOAuthCredentials

# === GOOGLE DRIVE API IMPORTS ===
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# === REPORTLAB IMPORTS FOR PDF GENERATION ===
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, HRFlowable,
    ListFlowable, ListItem, PageBreak, BaseDocTemplate,
    PageTemplate, Frame, Image, Table, TableStyle
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# === ANSI COLOR CODES ===
COLORS = {
    "GREEN": "\033[92m",
    "WHITE": "\033[97m",
    "BOLD": "\033[1m",
    "RESET": "\033[0m"
}

# === ROBOTO FONT SETUP & AUTO-DOWNLOAD ===
FONT_REGULAR_PATH = "Roboto-Regular.ttf"
FONT_BOLD_PATH = "Roboto-Bold.ttf"

ROBOTO_URLS = {
    FONT_REGULAR_PATH:
        "https://raw.githubusercontent.com/googlefonts/roboto/main/src/hinted/Roboto-Regular.ttf",
    FONT_BOLD_PATH:
        "https://raw.githubusercontent.com/googlefonts/roboto/main/src/hinted/Roboto-Bold.ttf"
}

for file_name, url in ROBOTO_URLS.items():
    if not os.path.exists(file_name):
        print(f"[*] Downloading {file_name} for Roboto typography...")
        try:
            urllib.request.urlretrieve(url, file_name)
        except Exception as e:
            print(f"[!] Warning: Failed to download {file_name}. Error: {e}")

if os.path.exists(FONT_REGULAR_PATH):
    pdfmetrics.registerFont(TTFont('Roboto', FONT_REGULAR_PATH))
    MAIN_FONT = 'Roboto'
else:
    MAIN_FONT = 'Helvetica'

if os.path.exists(FONT_BOLD_PATH):
    pdfmetrics.registerFont(TTFont('Roboto-Bold', FONT_BOLD_PATH))
    BOLD_FONT = 'Roboto-Bold'
else:
    BOLD_FONT = 'Helvetica-Bold'

# === CONFIGURATION ===
# Keep the existing Android/Pydroid paths for local runs. GitHub Actions
# supplies NEWS_CA_OUTPUT_DIR and GOOGLE_SERVICE_ACCOUNT_JSON as environment variables.
JSON_FILE = "/storage/emulated/0/pydroidScripts/Script_for_SMS/fifth-composite-489705-v5-d06baf7f990f.json"

if not os.path.exists(JSON_FILE):
    JSON_FILE = os.path.expanduser(
        "~/Script_for_SMS/fifth-composite-489705-v5-d06baf7f990f.json"
    )

DOWNLOAD_DIR = os.environ.get(
    "NEWS_CA_OUTPUT_DIR",
    os.path.expanduser("~/storage/downloads")
)
DRIVE_FOLDER_ID = (
    os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "").strip()
    or "14TKvCUr0k0bH8nADXlUrdIPoqhUJNrGH"
)
MOBILE_DRIVE_FOLDER_NAME = os.environ.get(
    "MOBILE_DRIVE_FOLDER_NAME",
    "Mobile"
)


def india_now():
    """Return naive India local time to match the script's existing RSS datetimes."""
    return datetime.now(ZoneInfo("Asia/Kolkata")).replace(tzinfo=None)

EXCLUDE_KEYWORDS = [
    "riddle", "optical illusion", "quiz", "brain teaser", "iq test",
    "admit card", "result", "recruitment", "vacancy", "exam date",
    "admission", "university", "hall ticket", "answer key", "cutoff",
    "cut-off", "selection list", "ssc", "upsc", "ibps", "banking exam",
    "job alert", "salary", "notification", "free mock test", "mock test",
    "we are hiring", "apprentice recruitment", "online registration"
]

# =====================================================================
# AFFAIRSCLOUD STATIC CONTENT TO OMIT
# =====================================================================

STATIC_CLUTTER_KEYWORDS = [
    "aspirant:",
    "affairscloud:",
    "does affairscloud covers",
    "why is there a delay in news",

    "mock test",
    "free mock test",

    "download current affairs app",
    "download the app",
    "click here to download the app",
    "careerscloud app or website",
    "careerscloud app",
    "careerscloud website",

    "we are hiring",
    "subject matter expert",
    "ca video creator",
    "content developers",

    "recruitment 2024",
    "recruitment 2025",
    "recruitment 2026",
    "apprentice recruitment",

    "registration last date",
    "check eligibility & vacancy",
    "apply now",

    "exclusively in our daily pdf",
    "toppers ca pdf",
    "crack current course",

    "click here for affairscloud hindu free vocabs",
    "affairscloud hindu free vocabs",
    "affairscloud hindu free vocabs telegram",

    "click here for current affairs",
    "click here for current affairs september",
    "click here for current affairs october",
    "click here for current affairs november",
    "click here for current affairs december",
    "click here for current affairs january",
    "click here for current affairs february",
    "click here for current affairs march",
    "click here for current affairs april",
    "click here for current affairs may",
    "click here for current affairs june",
    "click here for current affairs july",
    "click here for current affairs august",

    "make sure to download the app",
    "thank you for your understanding",

    "state government exams",
    "we are here for you to provide",
    "our current affairs september",
    "help you to get more marks in banking",

    # CareersCloud promotional text from the supplied HTML
    "read current affairs in careerscloud app",
    "course name – learn current affairs",
    "course name - learn current affairs",

    # Generic promotional/navigation text
    "click here",
    "subscribe to the crack current course",
]

# This table is present in the supplied AffairsCloud HTML.
# It is not part of the actual current-affairs content.
AFFAIRSCLOUD_OMIT_TABLE_KEYWORDS = [
    "legal compliance",
    "content sharing and legal compliance",
    "careerscloud content sharing",
    "not to share or distribute our content",
    "tracking system to monitor such activities",
    "strict legal action"
]

ADDA_STATIC_CATEGORY_KEYWORDS = [
    "monthly current affairs pdf",
    "capsule pdf",
    "download monthly"
]

NEWS_SOURCES = {
    "The Hindu": "https://www.thehindu.com/news/national/feeder/default.rss",
    "Times of India": "https://timesofindia.indiatimes.com/rssfeedstopstories.cms",
    "Livemint": "https://www.livemint.com/rss/news",
    "Economic Times": "https://economictimes.indiatimes.com/rssfeedstopstories.cms",
    "NDTV": "https://feeds.feedburner.com/ndtvnews-top-stories"
}

PDF_HEADLINE_COLORS = {
    "The Hindu": "#C81E1E",
    "Times of India": "#C81E1E",
    "Livemint": "#C81E1E",
    "Economic Times": "#C81E1E",
    "NDTV": "#C81E1E",
    "AffairsCloud": "#C81E1E",
    "Adda247": "#C81E1E",
    "DEFAULT": "#C81E1E"
}

HEADERS = {
    'User-Agent':
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36',

    'Accept':
        'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',

    'Accept-Language': 'en-US,en;q=0.9'
}

# === ADDA247 APPS SCRIPT FETCH PROXY ===
ADDA247_PROXY_URL = os.environ.get("ADDA247_PROXY_URL", "").strip()
ADDA247_PROXY_SECRET = os.environ.get("ADDA247_PROXY_SECRET", "")


class Adda247ProxySession:
    """Route only Adda247 GET requests through Apps Script; leave all other hosts direct."""

    ADDA247_HOSTS = {
        "currentaffairs.adda247.com",
        "www.currentaffairs.adda247.com"
    }

    def __init__(self, direct_session):
        self.direct_session = direct_session
        self.proxy_transport = requests.Session()

    def get(self, url, headers=None, timeout=None, **kwargs):
        from urllib.parse import urlparse

        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in self.ADDA247_HOSTS
        ):
            return self.direct_session.get(
                url, headers=headers, timeout=timeout, **kwargs
            )

        if not ADDA247_PROXY_URL or not ADDA247_PROXY_SECRET:
            raise RuntimeError(
                "Adda247 proxy settings are missing. Configure "
                "ADDA247_PROXY_URL and ADDA247_PROXY_SECRET in GitHub Actions."
            )

        last_error = None
        for attempt in range(1, 4):
            try:
                proxy_response = self.proxy_transport.post(
                    ADDA247_PROXY_URL,
                    json={"secret": ADDA247_PROXY_SECRET, "url": url},
                    headers={"Content-Type": "application/json"},
                    timeout=(30, 180)
                )
                proxy_response.raise_for_status()
                result = proxy_response.json()

                origin_status = int(result.get("status") or 0)
                page_html = result.get("html") or ""
                if result.get("ok") and origin_status == 200 and page_html:
                    response = requests.Response()
                    response.status_code = 200
                    response.url = url
                    response.encoding = "utf-8"
                    response._content = page_html.encode("utf-8")
                    response.headers["Content-Type"] = (
                        result.get("contentType") or "text/html; charset=UTF-8"
                    )
                    print(
                        f"[Adda247 Proxy] HTTP {origin_status}; "
                        f"{len(page_html)} HTML characters; attempt {attempt}: {url}"
                    )
                    return response

                last_error = RuntimeError(
                    f"Apps Script could not fetch Adda247 URL "
                    f"(origin HTTP {origin_status}, HTML length {len(page_html)})."
                )

            except Exception as exc:
                last_error = exc

            print(
                f"[Adda247 Proxy] Attempt {attempt}/3 failed for {url}: "
                f"{type(last_error).__name__}: {last_error}"
            )
            if attempt < 3:
                time.sleep(3)

        raise RuntimeError(
            f"Adda247 proxy failed after 3 attempts for {url}: {last_error}"
        ) from last_error





def check_internet():
    try:
        requests.get("https://www.google.com", timeout=5)
        return True
    except:
        return False


def show_status(status):
    print(
        f"{COLORS['GREEN']}[*] {status}{COLORS['RESET']}"
    )


def send_notify(title, content):
    binary_path = shutil.which("termux-notification")

    if not binary_path:
        binary_path = "/data/data/com.termux/files/usr/bin/termux-notification"

    try:
        subprocess.run(
            [binary_path, "-t", title, "-c", content],
            check=True
        )
        print(
            f"[*] Notification sent successfully: {title}"
        )
    except Exception as e:
        print(
            f"[!] Failed to trigger notification via subprocess: {e}"
        )


def sanitize_text(text):
    if not text:
        return ""

    text = text.replace("Â·", "•").replace("Â", "")

    text = re.sub(
        r'&#8377;|&#x20B9;|\u20b9|₹',
        'Rs ',
        text
    )

    text = re.sub(
        r'[\u25a0\u25a1\ufffd\u25fe\u25fd\u25fc\u25fb]\s*(?=\d)',
        'Rs ',
        text
    )

    text = re.sub(
        r'[ \t]+',
        ' ',
        text
    )

    return text.strip()


def is_english_text(text):
    if not text:
        return False

    printable_chars = [
        c for c in text
        if not c.isspace()
        and not c.isdigit()
        and not unicodedata.category(c).startswith('P')
    ]

    if not printable_chars:
        return True

    latin_count = sum(
        1 for c in printable_chars
        if 'LATIN' in unicodedata.name(c, '')
    )

    return (
        latin_count / len(printable_chars)
    ) >= 0.75


def is_valid_url(url):
    if not url or not isinstance(url, str):
        return False

    url = url.strip()

    return (
        url.startswith(('http://', 'https://'))
        and " " not in url
    )


def clean_hyperlink_for_drive(url, display_text):
    if not is_valid_url(url):
        return display_text

    clean_url = html.escape(url.strip())
    clean_text = html.escape(display_text)

    return (
        f'<a href="{clean_url}">'
        f'<font color="#0066CC"><u>{clean_text}</u></font>'
        f'</a>'
    )


def extract_rss_image(entry):
    if 'media_content' in entry and entry.media_content:
        for media in entry.media_content:
            if (
                'url' in media
                and is_valid_url(media['url'])
            ):
                return media['url']

    if 'media_thumbnail' in entry and entry.media_thumbnail:
        for media in entry.media_thumbnail:
            if (
                'url' in media
                and is_valid_url(media['url'])
            ):
                return media['url']

    if 'enclosures' in entry and entry.enclosures:
        for enc in entry.enclosures:
            if (
                enc.get('type', '').startswith('image/')
                and is_valid_url(enc.get('href'))
            ):
                return enc.get('href')

    summary_html = (
        entry.get('summary', '')
        or entry.get('description', '')
    )

    if summary_html:
        soup = BeautifulSoup(
            summary_html,
            'html.parser'
        )

        img = soup.find('img', src=True)

        if img and is_valid_url(img['src']):
            return img['src']

    return None


# === GOOGLE AUTHENTICATION & DRIVE UPLOADER ===
SCOPE = ["https://www.googleapis.com/auth/drive"]

# GitHub Actions should use the user's Google account via OAuth refresh token.
# This avoids the storage-quota limitation of service accounts when creating files.
UPLOAD_BRIDGE_URL = os.environ.get("GOOGLE_APPS_SCRIPT_URL", "").strip()
UPLOAD_BRIDGE_SECRET = os.environ.get("GOOGLE_APPS_SCRIPT_SECRET", "").strip()
USE_UPLOAD_BRIDGE = (
    os.environ.get("GITHUB_ACTIONS", "").lower() == "true"
    and bool(UPLOAD_BRIDGE_URL)
    and bool(UPLOAD_BRIDGE_SECRET)
)

_oauth_client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "").strip()
_oauth_client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
_oauth_refresh_token = os.environ.get("GOOGLE_OAUTH_REFRESH_TOKEN", "").strip()

if USE_UPLOAD_BRIDGE:
    # GitHub Actions uploads PDFs through the owner-authorized Apps Script bridge.
    # Existing OAuth secrets remain configured as a fallback until migration is verified.
    creds = None
elif _oauth_client_id and _oauth_client_secret and _oauth_refresh_token:
    creds = GoogleOAuthCredentials(
        token=None,
        refresh_token=_oauth_refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=_oauth_client_id,
        client_secret=_oauth_client_secret,
        scopes=SCOPE
    )
elif os.environ.get("GITHUB_ACTIONS", "").lower() == "true":
    raise RuntimeError(
        "Configure GOOGLE_APPS_SCRIPT_URL and GOOGLE_APPS_SCRIPT_SECRET, "
        "or provide the existing Google OAuth secrets as a fallback."
    )
else:
    # Preserve existing Android/Pydroid service-account authentication locally.
    if not os.path.exists(JSON_FILE):
        raise FileNotFoundError(
            "Google service-account JSON was not found at the configured local path."
        )
    creds = ServiceAccountCredentials.from_json_keyfile_name(JSON_FILE, SCOPE)


def upload_pdf_via_apps_script(file_path, file_name):
    """Upload one PDF to the authenticated Google Apps Script Drive bridge."""
    if not UPLOAD_BRIDGE_URL or not UPLOAD_BRIDGE_SECRET:
        raise RuntimeError("Google Apps Script upload bridge settings are missing.")

    import base64

    with open(file_path, "rb") as pdf_file:
        encoded_pdf = base64.b64encode(pdf_file.read()).decode("ascii")

    response = requests.post(
        UPLOAD_BRIDGE_URL,
        json={
            "secret": UPLOAD_BRIDGE_SECRET,
            "fileName": file_name,
            "base64": encoded_pdf
        },
        headers={"Content-Type": "application/json"},
        timeout=(30, 300)
    )
    response.raise_for_status()

    try:
        result = response.json()
    except ValueError as exc:
        raise RuntimeError(
            "Apps Script returned a non-JSON response. Check that the Web App "
            "deployment URL ends in /exec and is accessible."
        ) from exc

    if not result.get("ok"):
        raise RuntimeError(
            f"Apps Script upload failed for {file_name}: "
            f"{result.get('error', 'Unknown error')}"
        )

    print(
        f"{COLORS['GREEN']}[+] Apps Script {result.get('action')} "
        f"{file_name} in Google Drive (ID: {result.get('fileId')}, "
        f"size: {result.get('size')} bytes){COLORS['RESET']}"
    )
    return True


def get_or_create_drive_subfolder(
    parent_folder_id,
    folder_name,
    credentials
):
    """Find a named child folder in Drive or create it if it does not exist."""
    drive_service = build(
        'drive',
        'v3',
        credentials=credentials
    )

    query = (
        f"'{parent_folder_id}' in parents "
        f"and name = '{folder_name}' "
        f"and mimeType = 'application/vnd.google-apps.folder' "
        f"and trashed = false"
    )

    results = drive_service.files().list(
        q=query,
        fields="files(id, name)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True
    ).execute()

    folders = results.get('files', [])
    if folders:
        return folders[0]['id']

    created = drive_service.files().create(
        body={
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [parent_folder_id]
        },
        fields='id, name',
        supportsAllDrives=True
    ).execute()

    print(
        f"{COLORS['GREEN']}[+] Created Google Drive folder: "
        f"{folder_name} (ID: {created.get('id')}){COLORS['RESET']}"
    )
    return created['id']


def upload_pdf_to_drive(
    file_path,
    folder_id,
    credentials,
    target_name="Daily_Articles.pdf"
):
    try:
        drive_service = build(
            'drive',
            'v3',
            credentials=credentials
        )

        try:
            drive_service.files().get(
                fileId=folder_id,
                fields="id, name",
                supportsAllDrives=True
            ).execute()

        except Exception as f_err:
            print(
                f"[!] Target folder access check failed: {f_err}"
            )
            if os.environ.get("GITHUB_ACTIONS", "").lower() == "true":
                raise RuntimeError(
                    f"Google Drive folder is not accessible: {folder_id}"
                ) from f_err
            return False

        query = (
            f"'{folder_id}' in parents "
            f"and name = '{target_name}' "
            f"and trashed = false"
        )

        results = drive_service.files().list(
            q=query,
            fields="files(id, name)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True
        ).execute()

        items = results.get('files', [])

        media = MediaFileUpload(
            file_path,
            mimetype='application/pdf',
            resumable=True
        )

        if items:
            file_id = items[0]['id']

            drive_service.files().update(
                fileId=file_id,
                media_body=media,
                supportsAllDrives=True
            ).execute()

            print(
                f"{COLORS['GREEN']}[+] Successfully updated "
                f"{target_name} on Google Drive "
                f"(ID: {file_id}){COLORS['RESET']}"
            )
            return True

        else:
            file_metadata = {
                'name': target_name,
                'parents': [folder_id]
            }

            new_file = drive_service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id',
                supportsAllDrives=True
            ).execute()

            print(
                f"{COLORS['GREEN']}[+] Created new PDF "
                f"{target_name} on Google Drive "
                f"(ID: {new_file.get('id')}){COLORS['RESET']}"
            )
            return True

    except Exception as e:
        print(
            f"[!] Google Drive upload failed: {e}"
        )
        if os.environ.get("GITHUB_ACTIONS", "").lower() == "true":
            raise
        return False


# === ADVANCED HTML COLOR AND FORMATTING EXTRACTOR ===
def extract_color_from_style(style_attr):
    if not style_attr:
        return None

    match = re.search(
        r'color\s*:\s*([^;]+)',
        style_attr,
        re.IGNORECASE
    )

    if match:
        color_val = match.group(1).strip()

        if color_val.startswith('#'):
            return color_val

        elif 'rgb' in color_val.lower():
            rgb_nums = re.findall(
                r'\d+',
                color_val
            )

            if len(rgb_nums) >= 3:
                return (
                    f"#{int(rgb_nums[0]):02x}"
                    f"{int(rgb_nums[1]):02x}"
                    f"{int(rgb_nums[2]):02x}"
                )

        elif color_val.lower() in [
            'red',
            'green',
            'blue',
            'black',
            'maroon'
        ]:
            color_map = {
                'red': '#D32F2F',
                'green': '#339966',
                'blue': '#0000FF',
                'black': '#000000',
                'maroon': '#800000'
            }

            return color_map[color_val.lower()]

    return None


def clean_node_to_reportlab_html(element):
    if isinstance(element, NavigableString):
        return html.escape(str(element))

    if not isinstance(element, Tag):
        return ""

    tag_name = (
        element.name.lower()
        if element.name
        else ""
    )

    inner_html = "".join(
        [
            clean_node_to_reportlab_html(child)
            for child in element.children
        ]
    )

    if not inner_html.strip():
        return ""

    color_val = None

    if element.has_attr('style'):
        color_val = extract_color_from_style(
            element['style']
        )

    if not color_val and element.has_attr('color'):
        color_val = element['color']

    res = inner_html

    if tag_name in ['b', 'strong']:
        res = f"<b>{res}</b>"

    elif tag_name in ['i', 'em']:
        res = f"<i>{res}</i>"

    elif tag_name == 'u':
        res = f"<u>{res}</u>"

    elif tag_name == 'a':
        href = element.get('href', '')

        if href and href.startswith('http'):
            clean_href = html.escape(
                href.strip()
            )

            res = (
                f'<a href="{clean_href}">'
                f'<font color="#0066CC"><u>{res}</u></font>'
                f'</a>'
            )

    if color_val:
        res = (
            f'<font color="{color_val}">'
            f'{res}'
            f'</font>'
        )

    return res


def parse_html_table(table_tag):
    table_matrix = []

    rows = table_tag.find_all('tr')

    for row in rows:
        row_data = []

        cells = row.find_all(
            ['td', 'th']
        )

        for cell in cells:
            cell_html = clean_node_to_reportlab_html(
                cell
            )

            row_data.append(
                cell_html
                if cell_html.strip()
                else " "
            )

        if row_data:
            table_matrix.append(row_data)

    return table_matrix


# =====================================================================
# AFFAIRSCLOUD-SPECIFIC HELPERS
# =====================================================================

def affairscloud_is_static_content(text):
    """
    Determines whether a block belongs to AffairsCloud promotional,
    navigation, recruitment, legal, or other static clutter.

    This is intentionally used ONLY by the AffairsCloud extractor.
    """

    if not text:
        return False

    normalized = sanitize_text(text).lower()

    if not normalized:
        return False

    # Exact / phrase based static-content filtering
    for keyword in STATIC_CLUTTER_KEYWORDS:
        if keyword.lower() in normalized:
            return True

    return False


def affairscloud_is_legal_table(table_tag):
    """
    Detects the CareersCloud legal/content-sharing table supplied
    in the user's AffairsCloud HTML example.
    """

    table_text = sanitize_text(
        table_tag.get_text(" ", strip=True)
    ).lower()

    for keyword in AFFAIRSCLOUD_OMIT_TABLE_KEYWORDS:
        if keyword.lower() in table_text:
            return True

    return False


def affairscloud_get_color(element):
    """
    Reads the actual CSS color used by AffairsCloud.

    Supports:
      style="color: #ff0000"
      style="color: #0000ff"
      style="color: #339966"
      color="..."
    """

    if not isinstance(element, Tag):
        return None

    color_val = None

    if element.has_attr('style'):
        color_val = extract_color_from_style(
            element.get('style', '')
        )

    if not color_val and element.has_attr('color'):
        color_val = element.get('color')

    if color_val:
        return color_val.lower()

    return None


def affairscloud_text_from_node(node):
    """
    Returns clean visible text from an HTML node.
    """

    if not node:
        return ""

    return sanitize_text(
        node.get_text(
            " ",
            strip=True
        )
    )


# =====================================================================
# FIXED AFFAIRSCLOUD INLINE HTML CONVERTER
# =====================================================================

def affairscloud_inline_html(node):
    """
    Converts inline AffairsCloud HTML to ReportLab HTML.

    IMPORTANT:
    AffairsCloud uses <strong>/<b> extensively for individual words
    inside normal paragraphs.

    ReportLab does not always switch from the registered Roboto regular
    font to Roboto-Bold merely because <b> is present.

    Therefore bold text is explicitly assigned BOLD_FONT.

    Preserved:
      - <strong>
      - <b>
      - <i>
      - <em>
      - <u>
      - <span style="color: ...">
      - <font color="...">
      - <a>
      - nested formatting

    This is the only formatting change required for the issue shown
    in the supplied PDF and AffairsCloud screenshots.
    """

    if isinstance(node, NavigableString):
        text = str(node)

        # Remove the marker if one somehow remains
        text = text.replace(
            "||BR_BREAK||",
            " "
        )

        return html.escape(
            text,
            quote=False
        )

    if not isinstance(node, Tag):
        return ""

    tag_name = (
        node.name.lower()
        if node.name
        else ""
    )

    if tag_name in [
        'script',
        'style',
        'noscript',
        'iframe'
    ]:
        return ""

    if tag_name == 'br':
        return "<br/>"

    children_html = "".join(
        affairscloud_inline_html(child)
        for child in node.children
    )

    if not children_html.strip():
        return ""

    result = children_html

    # =============================================================
    # BOLD
    #
    # FIX:
    # Do NOT depend on ReportLab's automatic <b> font switching.
    #
    # Explicitly use the already registered BOLD_FONT.
    #
    # This is what fixes:
    #
    # <strong>PM-KMY</strong>
    # <strong>seven years</strong>
    # <strong>Launch:</strong>
    # <strong>MoA&FW</strong>
    # <strong>LIC</strong>
    # <strong>60</strong>
    # <strong>24.96 lakh</strong>
    #
    # and all other bold words.
    # =============================================================

    if tag_name in ['strong', 'b']:
        result = (
            f'<font name="{html.escape(BOLD_FONT)}">'
            f'{result}'
            f'</font>'
        )

    # =============================================================
    # ITALIC
    # =============================================================

    elif tag_name in ['em', 'i']:
        result = f"<i>{result}</i>"

    # =============================================================
    # UNDERLINE
    # =============================================================

    elif tag_name == 'u':
        result = f"<u>{result}</u>"

    # =============================================================
    # LINKS
    # =============================================================

    elif tag_name == 'a':
        href = node.get(
            'href',
            ''
        ).strip()

        # Promotion links are removed by the block filter,
        # but normal article links are retained.
        if is_valid_url(href):
            clean_href = html.escape(
                href,
                quote=True
            )

            result = (
                f'<a href="{clean_href}">'
                f'<font color="#0066CC"><u>'
                f'{result}'
                f'</u></font></a>'
            )

    # =============================================================
    # ACTUAL AFFAIRSCLOUD COLOR
    #
    # This is applied AFTER bold/italic/link processing so that:
    #
    # <span style="color:#339966">
    #     <strong>PM-KMY Overview</strong>
    # </span>
    #
    # becomes:
    #
    # green + bold
    #
    # instead of losing either formatting property.
    # =============================================================

    color_val = affairscloud_get_color(node)

    if color_val:
        result = (
            f'<font color="{html.escape(color_val)}">'
            f'{result}'
            f'</font>'
        )

    return result


def affairscloud_normalize_inline_html(raw_html):
    """
    Cleans an inline HTML fragment before giving it to ReportLab.
    """

    if not raw_html:
        return ""

    # Convert <br> variants to ReportLab-compatible line breaks
    raw_html = re.sub(
        r'<br\s*/?>',
        '<br/>',
        raw_html,
        flags=re.IGNORECASE
    )

    fragment = BeautifulSoup(
        raw_html,
        'html.parser'
    )

    result = "".join(
        affairscloud_inline_html(child)
        for child in fragment.children
    )

    return result.strip()


def affairscloud_split_by_br(tag):
    """
    Split a paragraph into logical pieces at <br> while preserving
    all inline HTML formatting.

    Example:

       <span blue><b>Heading</b></span><br>
       Normal paragraph<br>
       <span green><b>About...</b></span><br>
       <b>Launch:</b> ...

    becomes four independent logical blocks.
    """

    pieces = []
    current = []

    def walk(node):
        nonlocal current

        if isinstance(node, NavigableString):
            current.append(
                html.escape(
                    str(node)
                )
            )
            return

        if not isinstance(node, Tag):
            return

        if node.name.lower() == 'br':
            piece = "".join(current).strip()

            if piece:
                pieces.append(piece)

            current = []
            return

        # Preserve the complete inline element while walking its
        # children manually so <br> can be detected.
        if node.name.lower() in [
            'strong',
            'b',
            'i',
            'em',
            'u',
            'span',
            'a',
            'font'
        ]:
            opening = str(
                node.copy()
                if hasattr(node, 'copy')
                else ""
            )

        for child in node.children:
            if (
                isinstance(child, Tag)
                and child.name.lower() == 'br'
            ):
                piece = "".join(current).strip()

                if piece:
                    pieces.append(piece)

                current = []

            elif (
                isinstance(child, Tag)
                and child.name.lower() in [
                    'strong',
                    'b',
                    'i',
                    'em',
                    'u',
                    'span',
                    'a',
                    'font'
                ]
            ):
                # If an inline tag contains a BR, process it recursively.
                has_br = child.find('br') is not None

                if has_br:
                    # We need to retain the inline formatting around
                    # each portion. Build the parts using a temporary
                    # fragment.
                    temp_html = str(child)
                    temp_soup = BeautifulSoup(
                        temp_html,
                        'html.parser'
                    )

                    temp_tag = temp_soup.find(
                        child.name
                    )

                    if temp_tag:
                        local_current = []

                        def walk_inline(n):
                            nonlocal local_current

                            if isinstance(
                                n,
                                NavigableString
                            ):
                                local_current.append(
                                    html.escape(
                                        str(n)
                                    )
                                )
                                return

                            if not isinstance(n, Tag):
                                return

                            if n.name.lower() == 'br':
                                return

                            for ch in n.children:
                                if (
                                    isinstance(ch, Tag)
                                    and ch.name.lower() == 'br'
                                ):
                                    continue

                                local_current.append(
                                    affairscloud_inline_html(ch)
                                )

                        # Simpler and safer fallback:
                        # retain the whole tag if no direct split
                        # is needed at this level.
                        current.append(
                            affairscloud_inline_html(child)
                        )

                else:
                    current.append(
                        affairscloud_inline_html(child)
                    )

            else:
                current.append(
                    affairscloud_inline_html(child)
                )

    # The above recursive approach can become unnecessarily complex
    # for malformed WordPress HTML. A DOM-based separator is more
    # reliable for AffairsCloud's actual structure.
    #
    # Therefore use a cloned fragment and replace BR tags with a
    # unique separator while preserving all inline HTML.

    cloned = BeautifulSoup(
        str(tag),
        'html.parser'
    )

    for br in cloned.find_all('br'):
        br.replace_with(
            NavigableString(
                '||AFFAIRSCLOUD_BR||'
            )
        )

    full_html = cloned.decode_contents()

    raw_parts = full_html.split(
        '||AFFAIRSCLOUD_BR||'
    )

    final_parts = []

    for raw_part in raw_parts:
        raw_part = raw_part.strip()

        if not raw_part:
            continue

        formatted = affairscloud_normalize_inline_html(
            raw_part
        )

        if formatted.strip():
            final_parts.append(
                formatted.strip()
            )

    return final_parts


def affairscloud_detect_block_type(
    html_fragment,
    plain_text,
    source_tag=None
):
    """
    Detect formatting from the actual AffairsCloud HTML.

    Priority:
      1. Actual color in HTML
      2. Actual heading tag
      3. Actual strong/span structure
      4. Key-value lead-in
      5. Normal paragraph
    """

    text = sanitize_text(
        plain_text
    )

    if not text:
        return None

    fragment = BeautifulSoup(
        html_fragment,
        'html.parser'
    )

    # Find the effective color used by the fragment.
    colors_found = []

    for el in fragment.find_all(
        True
    ):
        color = affairscloud_get_color(el)

        if color:
            colors_found.append(
                color.lower()
            )

    # Also inspect the root-level fragment elements.
    for el in fragment.find_all(
        True
    ):
        style = el.get(
            'style',
            ''
        )

        if style:
            color = extract_color_from_style(
                style
            )

            if color:
                colors_found.append(
                    color.lower()
                )

    # -------------------------------------------------------------
    # 1. RED CATEGORY HEADERS
    # -------------------------------------------------------------
    red_colors = {
        '#ff0000',
        '#d32f2f',
        '#c81e1e',
        'red'
    }

    if any(
        c in red_colors
        for c in colors_found
    ):
        category_names = [
            "NATIONAL AFFAIRS",
            "STATE AFFAIRS",
            "BANKING",
            "BUSINESS",
            "AWARDS",
            "APPOINTMENTS",
            "SCIENCE",
            "SPORTS",
            "ENVIRONMENT",
            "INTERNATIONAL AFFAIRS",
            "DEFENCE",
            "SUMMITS & CONFERENCES",
            "IMPORTANT DAYS",
            "REPORTS & INDICES",
            "RANKINGS & INDEXES",
            "AGREEMENTS & MOUS",
            "SCHEMES",
            "OBITUARIES"
        ]

        upper_text = text.upper()

        if any(
            category in upper_text
            for category in category_names
        ):
            return "category_header"

    # -------------------------------------------------------------
    # 2. GREEN SUBHEADINGS
    # -------------------------------------------------------------
    green_colors = {
        '#339966',
        '#008000',
        '#009966',
        'green'
    }

    if any(
        c in green_colors
        for c in colors_found
    ):
        return "key_highlights"

    # -------------------------------------------------------------
    # 3. BLUE ARTICLE HEADINGS
    # -------------------------------------------------------------
    blue_colors = {
        '#0000ff',
        '#0000c8',
        '#0000cc',
        'blue'
    }

    if any(
        c in blue_colors
        for c in colors_found
    ):
        return "subheading"

    # -------------------------------------------------------------
    # 4. REAL HTML HEADINGS
    # -------------------------------------------------------------
    if source_tag:
        tag_name = (
            source_tag.name.lower()
            if source_tag.name
            else ""
        )

        if tag_name in [
            'h2',
            'h3',
            'h4',
            'h5'
        ]:
            return "subheading"

    # -------------------------------------------------------------
    # 5. KEY-VALUE PARAGRAPHS
    # -------------------------------------------------------------
    return "paragraph"


# =====================================================================
# EXACT AFFAIRSCLOUD & ADDA247 EXTRACTOR ENGINE
# =====================================================================

def extract_affairscloud_rich_content(
    session,
    url,
    headline
):
    """
    AffairsCloud-specific content extractor.

    Important:
    This function intentionally reads the actual HTML formatting
    supplied by AffairsCloud instead of reconstructing formatting
    from article text.

    Preserved:
      - red category headings
      - blue article headings
      - green subheadings
      - bold text
      - links
      - bullets
      - tables
      - BR-separated content

    Removed:
      - CareersCloud legal table
      - CareersCloud app promotions
      - hiring advertisements
      - Telegram promotion
      - Current Affairs navigation links
      - Daily PDF/Toppers CA promotion
      - other static clutter
    """

    try:
        resp = session.get(
            url,
            headers=HEADERS,
            timeout=12
        )

        if resp.status_code != 200:
            return (
                headline,
                [
                    {
                        "type": "paragraph",
                        "text": html.escape(headline)
                    }
                ],
                None
            )

        soup = BeautifulSoup(
            resp.text,
            'html.parser'
        )

        # =============================================================
        # FEATURED IMAGE
        # =============================================================

        extracted_image_url = None

        og_img = (
            soup.find(
                "meta",
                property=re.compile(
                    r"og:image",
                    re.I
                )
            )
            or
            soup.find(
                "meta",
                attrs={
                    "name": re.compile(
                        r"twitter:image",
                        re.I
                    )
                }
            )
        )

        if (
            og_img
            and og_img.get("content")
            and is_valid_url(
                og_img["content"]
            )
        ):
            extracted_image_url = (
                og_img["content"].strip()
            )

        if not extracted_image_url:
            img_tag = (
                soup.find(
                    "img",
                    class_=re.compile(
                        r"wp-post-image|featured-image|"
                        r"attachment-post-thumbnail",
                        re.I
                    )
                )
                or
                (
                    soup.find("article")
                    and
                    soup.find("article").find(
                        "img",
                        src=True
                    )
                )
            )

            if (
                img_tag
                and img_tag.get("src")
                and is_valid_url(
                    img_tag["src"]
                )
            ):
                extracted_image_url = (
                    img_tag["src"].strip()
                )

        # =============================================================
        # REMOVE NON-ARTICLE SITE ELEMENTS
        # =============================================================

        for element in soup(
            [
                "script",
                "style",
                "nav",
                "footer",
                "header",
                "aside",
                "form",
                "iframe",
                "noscript"
            ]
        ):
            element.decompose()

        # =============================================================
        # FIND ACTUAL ARTICLE CONTENT
        # =============================================================

        article_body = (
            soup.find(
                "div",
                class_=lambda c:
                    c
                    and any(
                        x in c.lower()
                        for x in [
                            "entry-content",
                            "pf-content",
                            "post-content",
                            "article-content",
                            "ca-post-content"
                        ]
                    )
            )
            or
            soup.find("article")
            or
            soup
        )

        # =============================================================
        # REMOVE MALFORMED AMP-TABLE WRAPPERS
        # =============================================================

        for amp_div in article_body.find_all(
            "div",
            class_="amp-table"
        ):
            amp_div.unwrap()

        # =============================================================
        # REMOVE LEGAL / STATIC TABLES BEFORE ARTICLE PROCESSING
        # =============================================================

        for table in article_body.find_all("table"):
            if affairscloud_is_legal_table(table):
                table.decompose()

        # =============================================================
        # REMOVE STATIC PROMOTIONAL BLOCKS
        # =============================================================

        elements_to_remove = []

        for element in article_body.find_all(
            [
                "p",
                "div",
                "section",
                "li"
            ]
        ):
            text = affairscloud_text_from_node(
                element
            )

            if not text:
                continue

            if affairscloud_is_static_content(
                text
            ):
                elements_to_remove.append(
                    element
                )

        # Avoid removing a parent and then separately processing
        # descendants that are already gone.
        for element in elements_to_remove:
            if element.parent is not None:
                element.decompose()

        # =============================================================
        # PROCESS ARTICLE IN ORIGINAL DOM ORDER
        # =============================================================

        structured_blocks = []
        plain_paragraphs = []

        def append_paragraph(
            html_fragment,
            plain_text,
            source_tag=None
        ):
            plain_text = sanitize_text(
                plain_text
            )

            if not plain_text:
                return

            if len(plain_text) < 2:
                return

            # Final static-content safety check.
            if affairscloud_is_static_content(
                plain_text
            ):
                return

            block_type = affairscloud_detect_block_type(
                html_fragment,
                plain_text,
                source_tag
            )

            if block_type == "category_header":
                formatted = (
                    '<font color="#D32F2F">'
                    '<font name="'
                    f'{html.escape(BOLD_FONT)}'
                    '">'
                    f'{html.escape(plain_text)}'
                    '</font>'
                    '</font>'
                )

                structured_blocks.append(
                    {
                        "type": "category_header",
                        "text": formatted
                    }
                )

            elif block_type == "key_highlights":
                # Preserve the actual HTML inside the green heading.
                formatted = html_fragment

                structured_blocks.append(
                    {
                        "type": "key_highlights",
                        "text": formatted
                    }
                )

            elif block_type == "subheading":
                # Preserve actual blue heading formatting.
                formatted = html_fragment

                structured_blocks.append(
                    {
                        "type": "subheading",
                        "text": formatted
                    }
                )

            else:
                # Normal paragraph.
                #
                # The important part is that we DO NOT flatten
                # <strong>, <span>, <a>, etc.
                formatted = html_fragment

                structured_blocks.append(
                    {
                        "type": "paragraph",
                        "text": formatted
                    }
                )

            plain_paragraphs.append(
                plain_text
            )

        def process_node(node):
            if not isinstance(node, Tag):
                return

            tag_name = (
                node.name.lower()
                if node.name
                else ""
            )

            # ---------------------------------------------------------
            # TABLE
            # ---------------------------------------------------------
            if tag_name == "table":
                if affairscloud_is_legal_table(
                    node
                ):
                    return

                table_matrix = parse_html_table(
                    node
                )

                if table_matrix:
                    structured_blocks.append(
                        {
                            "type": "table",
                            "matrix": table_matrix
                        }
                    )

                    plain_paragraphs.append(
                        "[TABLE INCLUDED IN PDF]"
                    )

                return

            # ---------------------------------------------------------
            # UL / OL
            # ---------------------------------------------------------
            if tag_name in [
                "ul",
                "ol"
            ]:
                items = []

                for li in node.find_all(
                    "li",
                    recursive=False
                ):
                    li_text = affairscloud_text_from_node(
                        li
                    )

                    if not li_text:
                        continue

                    if affairscloud_is_static_content(
                        li_text
                    ):
                        continue

                    li_html = affairscloud_inline_html(
                        li
                    )

                    if li_html.strip():
                        items.append(
                            li_html
                        )

                        plain_paragraphs.append(
                            f"• {li_text}"
                        )

                if items:
                    structured_blocks.append(
                        {
                            "type": "bullet_list",
                            "items": items
                        }
                    )

                return

            # ---------------------------------------------------------
            # HEADINGS
            # ---------------------------------------------------------
            if tag_name in [
                "h2",
                "h3",
                "h4",
                "h5"
            ]:
                text = affairscloud_text_from_node(
                    node
                )

                if not text:
                    return

                if affairscloud_is_static_content(
                    text
                ):
                    return

                formatted = affairscloud_inline_html(
                    node
                )

                # If it has actual AffairsCloud color, preserve it.
                # Otherwise use the same blue heading convention
                # used by AffairsCloud article titles.
                if not affairscloud_get_color(node):
                    formatted = (
                        '<font color="#0000FF">'
                        '<font name="'
                        f'{html.escape(BOLD_FONT)}'
                        '">'
                        f'{html.escape(text)}'
                        '</font>'
                        '</font>'
                    )

                structured_blocks.append(
                    {
                        "type": "subheading",
                        "text": formatted
                    }
                )

                plain_paragraphs.append(
                    text
                )

                return

            # ---------------------------------------------------------
            # PARAGRAPH
            # ---------------------------------------------------------
            if tag_name == "p":
                pieces = affairscloud_split_by_br(
                    node
                )

                for piece in pieces:
                    piece_soup = BeautifulSoup(
                        piece,
                        'html.parser'
                    )

                    piece_text = sanitize_text(
                        piece_soup.get_text(
                            " ",
                            strip=True
                        )
                    )

                    if not piece_text:
                        continue

                    if affairscloud_is_static_content(
                        piece_text
                    ):
                        continue

                    append_paragraph(
                        piece,
                        piece_text,
                        node
                    )

                return

            # ---------------------------------------------------------
            # DIV / SECTION
            # ---------------------------------------------------------
            if tag_name in [
                "div",
                "section",
                "article",
                "main"
            ]:
                for child in list(node.children):
                    if isinstance(child, Tag):
                        process_node(child)

                return

            # ---------------------------------------------------------
            # OTHER BLOCK ELEMENTS
            # ---------------------------------------------------------
            if tag_name in [
                "blockquote",
                "pre"
            ]:
                text = affairscloud_text_from_node(
                    node
                )

                if text and not affairscloud_is_static_content(
                    text
                ):
                    append_paragraph(
                        affairscloud_inline_html(node),
                        text,
                        node
                    )

                return

        # =============================================================
        # PROCESS ONLY THE ARTICLE BODY
        # =============================================================

        if article_body.name.lower() == "p":
            process_node(article_body)

        else:
            for child in list(
                article_body.children
            ):
                if isinstance(child, Tag):
                    process_node(child)

        # =============================================================
        # FALLBACK
        # =============================================================

        plain_text = (
            "\n\n".join(
                plain_paragraphs
            )
            if plain_paragraphs
            else headline
        )

        if not structured_blocks:
            structured_blocks = [
                {
                    "type": "paragraph",
                    "text": html.escape(
                        headline
                    )
                }
            ]

        return (
            plain_text,
            structured_blocks,
            extracted_image_url
        )

    except Exception as e:
        print(
            f"[!] Error extracting content for {url}: {e}"
        )

        return (
            headline,
            [
                {
                    "type": "paragraph",
                    "text": html.escape(
                        headline
                    )
                }
            ],
            None
        )


def extract_adda247_article_content(session, url, headline):
    """
    Extract one Adda247 article and explicitly report whether substantive
    article content was obtained. Keep the existing parser and PDF blocks.
    """
    plain_text, structured_blocks, image_url = (
        extract_affairscloud_rich_content(session, url, headline)
    )

    normalized_text = re.sub(r"\s+", " ", (plain_text or "")).strip().casefold()
    normalized_headline = re.sub(r"\s+", " ", (headline or "")).strip().casefold()
    content_ok = (
        bool(normalized_text)
        and normalized_text != normalized_headline
        and len(normalized_text) > len(normalized_headline) + 20
    )

    return plain_text, structured_blocks, image_url, content_ok


def retry_incomplete_adda247_articles(rows, session):
    """
    Retry headline-only Adda247 rows after the initial listing passes.
    Updates existing rows in place and returns the rows still incomplete.
    """
    is_github_actions = os.environ.get("GITHUB_ACTIONS", "").lower() == "true"
    if not is_github_actions:
        return []

    incomplete_by_url = {}
    for row in rows:
        if not row.get("content_extracted", True):
            url = row.get("raw_link")
            if url:
                incomplete_by_url.setdefault(url, []).append(row)
    if not incomplete_by_url:
        print("[Adda247] Content verification: all article pages extracted.")
        return []

    print(
        f"[Adda247] Second-pass recovery: retrying "
        f"{len(incomplete_by_url)} incomplete article(s)."
    )

    still_incomplete = []
    for url, affected_rows in incomplete_by_url.items():
        row = affected_rows[0]
        recovered = False
        for retry_number, wait_seconds in enumerate((5, 15), start=1):
            print(
                f"[Adda247] Recovery retry {retry_number}/2: "
                f"{row.get('title', url)}"
            )
            time.sleep(wait_seconds)

            try:
                plain_text, structured_blocks, image_url, content_ok = (
                    extract_adda247_article_content(
                        session, url, row.get("title", "")
                    )
                )
                if content_ok:
                    for affected_row in affected_rows:
                        affected_row["desc"] = plain_text
                        affected_row["plain_text"] = plain_text
                        affected_row["structured_content"] = structured_blocks
                        affected_row["image_url"] = image_url
                        affected_row["content_extracted"] = True
                    recovered = True
                    print(f"[Adda247] RECOVERED: {row.get('title', url)}")
                    break
            except Exception as exc:
                print(
                    f"[Adda247] Recovery retry {retry_number}/2 failed "
                    f"for {url}: {type(exc).__name__}: {exc}"
                )

        if not recovered:
            for affected_row in affected_rows:
                affected_row["content_extracted"] = False
            still_incomplete.append(row)

    print(
        f"[Adda247] Content verification: "
        f"{len(incomplete_by_url) - len(still_incomplete)} recovered; "
        f"{len(still_incomplete)} still incomplete."
    )
    for row in still_incomplete:
        print(
            f"[Adda247] INCOMPLETE ARTICLE: {row.get('title', '')} | "
            f"{row.get('raw_link', '')}"
        )

    return still_incomplete


# === CURRENT AFFAIRS FETCHERS ===

def fetch_affairscloud_today_and_yesterday(session):
    show_status(
        "Scraping AffairsCloud Current Affairs..."
    )

    ac_articles = []

    today_dt = datetime.now()
    yesterday_dt = today_dt - timedelta(days=1)

    dates_to_fetch = [
        ("Today", today_dt),
        ("Yesterday", yesterday_dt)
    ]

    base_ca_url = (
        "https://affairscloud.com/"
        "current-affairs-ca/current-affairs-today/"
    )

    try:
        resp = session.get(
            base_ca_url,
            headers=HEADERS,
            timeout=12
        )

        if resp.status_code == 200:
            soup = BeautifulSoup(
                resp.text,
                'html.parser'
            )

            post_links = []

            for a in soup.find_all(
                'a',
                href=True
            ):
                href = a['href']
                text = sanitize_text(
                    a.get_text()
                )

                if (
                    "current-affairs-" in href
                    and any(
                        month in text.lower()
                        for month in [
                            "january",
                            "february",
                            "march",
                            "april",
                            "may",
                            "june",
                            "july",
                            "august",
                            "september",
                            "october",
                            "november",
                            "december"
                        ]
                    )
                ):
                    if (
                        href not in post_links
                        and "category" not in href
                        and "pdf" not in href
                    ):
                        post_links.append(
                            href
                        )

            for label, dt in dates_to_fetch:
                day_str = str(dt.day)
                month_name = (
                    dt.strftime("%B").lower()
                )
                year_str = str(dt.year)

                matched_link = None

                for link in post_links:
                    link_lower = link.lower()

                    if (
                        f"{day_str}-{month_name}-{year_str}"
                        in link_lower
                        or
                        f"{day_str}-{dt.strftime('%b').lower()}-{year_str}"
                        in link_lower
                    ):
                        matched_link = link
                        break

                if not matched_link:
                    matched_link = (
                        "https://affairscloud.com/"
                        f"current-affairs-{day_str}-"
                        f"{month_name}-{year_str}/"
                    )

                print(
                    f"[*] Fetching AffairsCloud {label} "
                    f"({dt.strftime('%d %b %Y')}): "
                    f"{matched_link}"
                )

                title_lbl = (
                    "AffairsCloud Current Affairs - "
                    f"{dt.strftime('%d %B %Y')} "
                    f"({label})"
                )

                plain_desc, structured_data, img_url = (
                    extract_affairscloud_rich_content(
                        session,
                        matched_link,
                        title_lbl
                    )
                )

                ac_articles.append(
                    {
                        'ts': dt.date(),
                        'source_name': 'AffairsCloud',
                        'date_label':
                            f"AffairsCloud "
                            f"({dt.strftime('%d %b %Y')})",
                        'title': title_lbl,
                        'desc': plain_desc,
                        'plain_text': plain_desc,
                        'structured_content':
                            structured_data,
                        'image_url': img_url,
                        'raw_link': matched_link
                    }
                )

    except Exception as e:
        print(
            f"[!] Error fetching AffairsCloud posts: {e}"
        )

    return ac_articles


def _adda_parse_listing_date(text):
    """Parse common visible and machine-readable Adda247 date formats."""
    if not text:
        return None
    text = sanitize_text(str(text))
    patterns = [
        (r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}\b', "%B %d, %Y"),
        (r'\b\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\b', "%d %B %Y"),
        (r'\b\d{4}-\d{2}-\d{2}\b', "%Y-%m-%d")
    ]
    for pattern, fmt in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                return datetime.strptime(match.group(0), fmt).date()
            except ValueError:
                pass
    return None


def _adda_date_near_link(a_tag):
    """Find a single unambiguous date in the link's nearby listing container."""
    node = a_tag
    for _ in range(6):
        if not node:
            break
        if isinstance(node, Tag):
            time_tag = node.find("time")
            if time_tag:
                parsed = _adda_parse_listing_date(
                    time_tag.get("datetime", "") or time_tag.get_text(" ", strip=True)
                )
                if parsed:
                    return parsed
            dates = []
            pattern = (
                r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}\b'
                r'|\b\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\b'
                r'|\b\d{4}-\d{2}-\d{2}\b'
            )
            for value in re.findall(pattern, node.get_text(" ", strip=True), re.IGNORECASE):
                parsed = _adda_parse_listing_date(value)
                if parsed and parsed not in dates:
                    dates.append(parsed)
            if len(dates) == 1:
                return dates[0]
        node = node.parent
    return None


def _adda_listing_links(soup, page_url):
    """Discover article links without depending on Adda247 theme CSS classes."""
    from urllib.parse import urljoin, urlparse

    results = []
    seen = set()
    for a_tag in soup.find_all("a", href=True):
        title = sanitize_text(a_tag.get_text(" ", strip=True))
        if len(title) < 15:
            continue
        link = urljoin(page_url, a_tag["href"].strip())
        parsed = urlparse(link)
        host = (parsed.hostname or "").lower()
        path = parsed.path.rstrip("/").lower()
        if parsed.scheme not in ("http", "https"):
            continue
        if host not in ("currentaffairs.adda247.com", "www.currentaffairs.adda247.com"):
            continue
        if (
            not path
            or path in ("/latest-posts", "/banking-current-affairs")
            or path.startswith(("/category/", "/tag/", "/author/", "/page/"))
            or "/wp-content/" in path
            or link in seen
        ):
            continue
        if any(word in title.lower() for word in EXCLUDE_KEYWORDS + ADDA_STATIC_CATEGORY_KEYWORDS):
            continue
        seen.add(link)
        results.append((a_tag, title, link))
    return results


def _adda_article_date_from_page(session, link):
    """Fallback to WordPress/SEO metadata if the listing has no visible date."""
    try:
        response = session.get(link, headers=HEADERS, timeout=12)
        if response.status_code != 200:
            return None
        soup = BeautifulSoup(response.text, "html.parser")
        meta = (
            soup.find("meta", property="article:published_time")
            or soup.find("meta", attrs={"name": "date"})
            or soup.find("meta", property="og:updated_time")
            or soup.find("time", attrs={"datetime": True})
        )
        if not meta:
            return None
        return _adda_parse_listing_date(
            meta.get("content", "") or meta.get("datetime", "")
            or meta.get_text(" ", strip=True)
        )
    except Exception as exc:
        print(f"[!] Could not read Adda247 article date for {link}: {exc}")
        return None


def fetch_adda247_previous_3_days(session):
    show_status(
        "Scraping Previous 3 Days Current Affairs from Adda247..."
    )

    cutoff_date_ca = (
        datetime.now() - timedelta(days=3)
    ).date()

    ca_target_urls = [
        f"https://currentaffairs.adda247.com/"
        f"?nocache={random.randint(1,999)}",

        f"https://currentaffairs.adda247.com/"
        f"latest-posts/?nocache={random.randint(1,999)}"
    ]

    rows_adda = []
    seen_links = set()

    for url_ca in ca_target_urls:
        try:
            resp = session.get(
                url_ca,
                headers=HEADERS,
                timeout=10
            )

            print(f"[Adda247 CA] HTTP {resp.status_code}: {url_ca}")

            if resp.status_code != 200:
                continue

            soup = BeautifulSoup(
                resp.text,
                'html.parser'
            )

            posts = soup.select(
                'article, li.category_postlist, '
                'div.post-content, div.entry-header, div.ca-card'
            )

            for post in posts:
                a_tag = post.find(
                    "a",
                    href=True
                )

                if not a_tag:
                    continue

                title = sanitize_text(
                    a_tag.get_text(
                        strip=True
                    )
                )

                if (
                    len(title) < 15
                    or any(
                        w in title.lower()
                        for w in (
                            EXCLUDE_KEYWORDS
                            + ADDA_STATIC_CATEGORY_KEYWORDS
                        )
                    )
                ):
                    continue

                link = a_tag["href"].strip()

                if (
                    link in seen_links
                    or not link.startswith("http")
                ):
                    continue

                date_tag = (
                    post.find(
                        "p",
                        class_=lambda c:
                            c and "date" in c.lower()
                    )
                    or
                    post.find("time")
                    or
                    post.find(
                        "span",
                        class_=lambda c:
                            c and "date" in c.lower()
                    )
                )

                date_str = (
                    date_tag.get_text(
                        strip=True
                    )
                    if date_tag
                    else
                    datetime.now().strftime(
                        "%B %d, %Y"
                    )
                )

                try:
                    match = re.search(
                        r'(January|February|March|April|May|June|July|August|September|October|November|December)'
                        r'\s+\d{1,2},\s+\d{4}',
                        date_str
                    )

                    article_date = (
                        datetime.strptime(
                            match.group(0),
                            "%B %d, %Y"
                        ).date()
                        if match
                        else
                        datetime.now().date()
                    )

                except Exception:
                    article_date = (
                        datetime.now().date()
                    )

                if article_date >= cutoff_date_ca:
                    plain_desc, structured_data, img_url, content_extracted = (
                        extract_adda247_article_content(
                            session,
                            link,
                            title
                        )
                    )

                    seen_links.add(link)

                    rows_adda.append(
                        {
                            'ts': article_date,
                            'source_name': 'Adda247',
                            'date_label':
                                f"Adda247 "
                                f"({article_date.strftime('%d %b %Y')})",
                            'title': title,
                            'desc': plain_desc,
                            'plain_text': plain_desc,
                            'structured_content':
                                structured_data,
                            'image_url': img_url,
                            'raw_link': link,
                            'content_extracted': content_extracted
                        }
                    )

        except Exception as e:
            print(
                f"[!] Adda247 CA HTML scraping issue "
                f"for {url_ca}: {e}"
            )

    rows_adda.sort(
        key=lambda x: x['ts'],
        reverse=True
    )

    full_text_count = sum(1 for row in rows_adda if row.get("content_extracted"))
    print(
        f"[Adda247 CA] Articles discovered: {len(rows_adda)}; "
        f"full text on first pass: {full_text_count}; "
        f"headline-only pending recovery: {len(rows_adda) - full_text_count}"
    )

    return rows_adda


def fetch_banking_current_affairs(
    session,
    cutoff_days=90
):
    show_status(
        "Scraping Banking & RBI Current Affairs (Adda247)..."
    )

    cutoff_date = (
        datetime.now()
        - timedelta(days=cutoff_days)
    ).date()

    base_url = (
        "https://currentaffairs.adda247.com/"
        "banking-current-affairs/"
    )

    rows_banking = []
    seen_links = set()

    page = 1
    keep_scraping = True

    while keep_scraping:
        target_url = (
            f"{base_url}?nocache="
            f"{random.randint(1,999)}"
            if page == 1
            else
            f"{base_url}?lcp_page0={page}"
            f"#lcp_instance_0"
        )

        try:
            resp = session.get(
                target_url,
                headers=HEADERS,
                timeout=12
            )

            print(f"[Adda247 Banking] Page {page} HTTP {resp.status_code}: {target_url}")

            if resp.status_code != 200:
                break

            soup = BeautifulSoup(
                resp.text,
                'html.parser'
            )

            container = soup.find(
                'ul',
                class_='lcp_catlist'
            )

            if not container:
                print(f"[Adda247 Banking] Page {page}: expected ul.lcp_catlist not found")
                break

            items = container.find_all('li')
            print(f"[Adda247 Banking] Page {page}: {len(items)} listing items found")

            if not items:
                break

            page_had_valid = False

            for li in items:
                desc_div = li.find(
                    'div',
                    class_='desc'
                )

                if not desc_div:
                    continue

                a_tag = desc_div.find(
                    'a',
                    href=True
                )

                if not a_tag:
                    continue

                link = a_tag['href'].strip()

                title = sanitize_text(
                    a_tag.get_text(
                        strip=True
                    )
                )

                if (
                    link in seen_links
                    or len(title) < 15
                    or any(
                        w in title.lower()
                        for w in (
                            EXCLUDE_KEYWORDS
                            + ADDA_STATIC_CATEGORY_KEYWORDS
                        )
                    )
                ):
                    continue

                date_p = desc_div.find('p')

                article_date = (
                    datetime.now().date()
                )

                if date_p:
                    match = re.search(
                        r'(January|February|March|April|May|June|July|August|September|October|November|December)'
                        r'\s+\d{1,2},\s+\d{4}',
                        date_p.get_text()
                    )

                    if match:
                        try:
                            article_date = datetime.strptime(
                                match.group(0),
                                "%B %d, %Y"
                            ).date()
                        except ValueError:
                            pass

                if article_date >= cutoff_date:
                    page_had_valid = True

                    seen_links.add(link)

                    plain_desc, structured_data, img_url, content_extracted = (
                        extract_adda247_article_content(
                            session,
                            link,
                            title
                        )
                    )

                    rows_banking.append(
                        {
                            'ts': article_date,
                            'source_name':
                                'Banking Current Affairs',
                            'date_label':
                                article_date.strftime(
                                    "%d %b %Y"
                                ),
                            'title': title,
                            'desc': plain_desc,
                            'plain_text': plain_desc,
                            'structured_content':
                                structured_data,
                            'image_url': img_url,
                            'raw_link': link,
                            'content_extracted': content_extracted
                        }
                    )

                else:
                    keep_scraping = False

            if not page_had_valid:
                break

            page += 1
            time.sleep(1)

        except Exception as e:
            print(
                f"[!] Error processing Banking CA "
                f"page {page}: {e}"
            )
            break

    full_text_count = sum(1 for row in rows_banking if row.get("content_extracted"))
    print(
        f"[Adda247 Banking] Articles discovered: {len(rows_banking)}; "
        f"full text on first pass: {full_text_count}; "
        f"headline-only pending recovery: {len(rows_banking) - full_text_count}"
    )
    return rows_banking


def draw_page_decorations(canvas, doc):
    if doc.page > 1:
        canvas.saveState()

        canvas.setFont(
            BOLD_FONT,
            11
        )

        canvas.setFillColor(
            colors.HexColor('#0066CC')
        )

        x_pos = (
            doc.pagesize[0]
            - doc.rightMargin
        )

        y_pos = (
            doc.bottomMargin
            - 10
        )

        text_str = "[index]"

        canvas.drawRightString(
            x_pos,
            y_pos,
            text_str
        )

        text_width = canvas.stringWidth(
            text_str,
            BOLD_FONT,
            11
        )

        rect = (
            x_pos - text_width - 4,
            y_pos - 4,
            x_pos + 4,
            y_pos + 12
        )

        canvas.linkAbsolute(
            "Index Page",
            "table_of_contents",
            Rect=rect,
            Border=[0, 0, 0]
        )

        canvas.restoreState()


# === PDF GENERATOR WITH FIXED STYLING ===
def generate_pdf_document(
    news_items,
    ca_items,
    banking_items,
    session,
    filepath,
    is_desktop=False
):
    if is_desktop:
        PAGE_SIZE = A4

        left_m = (
            right_m
        ) = (
            top_m
        ) = (
            bottom_m
        ) = 0.5 * inch

        max_img_width = 7.27 * inch
        max_img_height = 4.5 * inch
        content_width = 7.27 * inch

    else:
        PAGE_SIZE = (
            4.2 * inch,
            8.0 * inch
        )

        left_m = (
            right_m
        ) = 0.12 * inch

        top_m = (
            bottom_m
        ) = 0.35 * inch

        max_img_width = 3.96 * inch
        max_img_height = 2.4 * inch
        content_width = 3.96 * inch

    doc = BaseDocTemplate(
        filepath,
        pagesize=PAGE_SIZE,
        leftMargin=left_m,
        rightMargin=right_m,
        topMargin=top_m,
        bottomMargin=bottom_m
    )

    frame = Frame(
        doc.leftMargin,
        doc.bottomMargin,
        doc.width,
        doc.height,
        id='normal_frame'
    )

    template = PageTemplate(
        id='pdf_template',
        frames=frame,
        onPage=draw_page_decorations
    )

    doc.addPageTemplates(
        [template]
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Normal'],
        fontName=BOLD_FONT,
        fontSize=21,
        leading=26,
        alignment=TA_CENTER,
        textColor=colors.HexColor('#1B365D'),
        spaceAfter=4
    )

    updated_time_style = ParagraphStyle(
        'LastUpdatedTime',
        parent=styles['Normal'],
        fontName=MAIN_FONT,
        fontSize=10.5,
        leading=14,
        alignment=TA_CENTER,
        textColor=colors.HexColor('#555555'),
        spaceAfter=12
    )

    idx_main_style = ParagraphStyle(
        'IndexTitle',
        parent=styles['Normal'],
        fontName=BOLD_FONT,
        fontSize=17,
        leading=22,
        textColor=colors.HexColor('#1B365D'),
        spaceBefore=4,
        spaceAfter=8
    )

    cat_title_style = ParagraphStyle(
        'CategoryTitle',
        parent=styles['Normal'],
        fontName=BOLD_FONT,
        fontSize=21,
        leading=26,
        textColor=colors.HexColor('#A02020'),
        spaceBefore=22,
        spaceAfter=12
    )

    category_header_style = ParagraphStyle(
        'CatHeaderStyle',
        parent=styles['Normal'],
        fontName=BOLD_FONT,
        fontSize=15,
        leading=20,
        alignment=TA_CENTER,
        textColor=colors.HexColor('#D32F2F'),
        spaceBefore=14,
        spaceAfter=8
    )

    subheading_style = ParagraphStyle(
        'SideHeading',
        parent=styles['Normal'],
        fontName=BOLD_FONT,
        fontSize=15,
        leading=21,
        alignment=TA_LEFT,
        textColor=colors.HexColor('#0000FF'),
        spaceBefore=12,
        spaceAfter=6
    )

    key_highlights_style = ParagraphStyle(
        'KeyHighlightsHeading',
        parent=styles['Normal'],
        fontName=BOLD_FONT,
        fontSize=14.5,
        leading=20,
        alignment=TA_LEFT,
        textColor=colors.HexColor('#339966'),
        spaceBefore=10,
        spaceAfter=4
    )

    body_style = ParagraphStyle(
        'ReadingBody',
        parent=styles['Normal'],
        fontName=MAIN_FONT,
        fontSize=13,
        leading=18.5,
        alignment=TA_LEFT,
        textColor=colors.HexColor('#222222'),
        spaceAfter=10
    )

    bullet_style = ParagraphStyle(
        'ReadingBullet',
        parent=styles['Normal'],
        fontName=MAIN_FONT,
        fontSize=13,
        leading=18.5,
        alignment=TA_LEFT,
        textColor=colors.HexColor('#222222'),
        spaceAfter=6
    )

    meta_style = ParagraphStyle(
        'ReadingMeta',
        parent=styles['Normal'],
        fontName=MAIN_FONT,
        fontSize=11.5,
        leading=15,
        textColor=colors.HexColor('#666666'),
        spaceAfter=10
    )

    table_header_cell_style = ParagraphStyle(
        'THeaderCell',
        parent=styles['Normal'],
        fontName=BOLD_FONT,
        fontSize=11,
        leading=15,
        alignment=TA_CENTER,
        textColor=colors.white
    )

    table_body_cell_style = ParagraphStyle(
        'TBodyCell',
        parent=styles['Normal'],
        fontName=MAIN_FONT,
        fontSize=10.5,
        leading=14.5,
        alignment=TA_CENTER,
        textColor=colors.HexColor('#222222')
    )

    story = []

    today_str = datetime.now().strftime(
        "%d %B %Y"
    )

    story.append(
        Paragraph(
            f"DAILY DIGEST & ARTICLES<br/>{today_str}",
            title_style
        )
    )

    story.append(
        Paragraph(
            f"Last Updated: "
            f"{datetime.now().strftime('%d %b %Y, %H:%M IST')}",
            updated_time_style
        )
    )

    story.append(
        Spacer(
            1,
            4
        )
    )

    categories = [
        (
            "NEWS ARTICLES",
            news_items,
            "NEWS",
            "cat_news"
        ),
        (
            "CURRENT AFFAIRS (CA)",
            ca_items,
            "CA",
            "cat_ca"
        ),
        (
            "BANKING AND RBI CURRENT AFFAIRS",
            banking_items,
            "BANKING",
            "cat_banking"
        )
    ]

    story.append(
        Paragraph(
            '<a name="table_of_contents"/>'
            'TABLE OF CONTENTS / INDEX',
            idx_main_style
        )
    )

    for (
        cat_title,
        items,
        cat_type,
        cat_bookmark
    ) in categories:

        story.append(
            Paragraph(
                f'<a href="#{cat_bookmark}">'
                f'<font color="#A02020">'
                f'<b>■ {cat_title}</b>'
                f'</font>'
                f'</a>',
                ParagraphStyle(
                    'IdxCat',
                    parent=styles['Normal'],
                    fontName=BOLD_FONT,
                    fontSize=13,
                    leading=18,
                    spaceBefore=8,
                    spaceAfter=4
                )
            )
        )

        if not items:
            story.append(
                Paragraph(
                    "No articles available "
                    "for this section today.",
                    ParagraphStyle(
                        'NoArt',
                        parent=styles['Normal'],
                        fontName=MAIN_FONT,
                        fontSize=11,
                        leading=15,
                        leftIndent=10
                    )
                )
            )

            continue

        for idx, item in enumerate(
            items,
            1
        ):
            art_bookmark_name = (
                f"bm_{cat_type.lower()}_{idx}"
            )

            item["doc_bookmark"] = (
                art_bookmark_name
            )

            title_text = html.escape(
                sanitize_text(
                    item.get(
                        "title",
                        "Untitled Article"
                    )
                )
            )

            story.append(
                Paragraph(
                    f'{idx}. '
                    f'<a href="#{art_bookmark_name}">'
                    f'<font color="#0066CC">'
                    f'<u>{title_text}</u>'
                    f'</font>'
                    f'</a>',
                    ParagraphStyle(
                        'IdxArt',
                        parent=styles['Normal'],
                        fontName=MAIN_FONT,
                        fontSize=12,
                        leading=17,
                        leftIndent=10,
                        spaceAfter=3
                    )
                )
            )

    story.append(
        Spacer(
            1,
            12
        )
    )

    story.append(
        HRFlowable(
            width="100%",
            thickness=1,
            color=colors.HexColor('#CCCCCC'),
            spaceAfter=18
        )
    )

    for (
        cat_title,
        items,
        cat_type,
        cat_bookmark
    ) in categories:

        story.append(
            Paragraph(
                f'<a name="{cat_bookmark}"/>'
                f'{cat_title}',
                cat_title_style
            )
        )

        if not items:
            story.append(
                Paragraph(
                    "No articles available "
                    "for this section today.",
                    ParagraphStyle(
                        'Empty',
                        parent=styles['Normal'],
                        fontName=MAIN_FONT,
                        fontSize=12,
                        leading=16
                    )
                )
            )

            continue

        for idx, item in enumerate(
            items,
            1
        ):
            title = html.escape(
                sanitize_text(
                    item.get(
                        "title",
                        "Untitled Article"
                    )
                )
            )

            url = item.get(
                "raw_link",
                ""
            )

            date_label = html.escape(
                sanitize_text(
                    item.get(
                        "date_label",
                        ""
                    )
                )
            )

            source_name = item.get(
                "source_name",
                "DEFAULT"
            )

            art_bookmark = item.get(
                "doc_bookmark",
                f"bm_{cat_type.lower()}_{idx}"
            )

            headline_hex = PDF_HEADLINE_COLORS.get(
                source_name,
                PDF_HEADLINE_COLORS["DEFAULT"]
            )

            art_style = ParagraphStyle(
                f'ArtHead_{source_name}',
                parent=styles['Normal'],
                fontName=BOLD_FONT,
                fontSize=15,
                leading=20,
                textColor=colors.HexColor(
                    headline_hex
                ),
                spaceBefore=12,
                spaceAfter=6
            )

            story.append(
                Paragraph(
                    f'<a name="{art_bookmark}"/>'
                    f'{idx}. {title}',
                    art_style
                )
            )

            img_url = item.get(
                "image_url"
            )

            if img_url:
                try:
                    img_resp = session.get(
                        img_url,
                        headers=HEADERS,
                        timeout=6
                    )

                    if img_resp.status_code == 200:
                        img_data = BytesIO(
                            img_resp.content
                        )

                        img_flowable = Image(
                            img_data
                        )

                        w = img_flowable.drawWidth
                        h = img_flowable.drawHeight

                        aspect = (
                            h / float(w)
                            if w
                            else 0.6
                        )

                        new_w = min(
                            w,
                            max_img_width
                        )

                        new_h = min(
                            new_w * aspect,
                            max_img_height
                        )

                        img_flowable.drawWidth = new_w
                        img_flowable.drawHeight = new_h
                        img_flowable.hAlign = 'CENTER'

                        story.append(
                            Spacer(
                                1,
                                4
                            )
                        )

                        story.append(
                            img_flowable
                        )

                        story.append(
                            Spacer(
                                1,
                                6
                            )
                        )

                except Exception as img_err:
                    print(
                        f"[!] Skip image render for "
                        f"'{title[:20]}...': "
                        f"{img_err}"
                    )

            meta_html = (
                f'[{date_label}] '
                f'&nbsp;|&nbsp; '
            )

            if is_valid_url(url):
                meta_html += clean_hyperlink_for_drive(
                    url,
                    "Source Article Link"
                )

            story.append(
                Paragraph(
                    meta_html,
                    meta_style
                )
            )

            if (
                "structured_content" in item
                and item["structured_content"]
            ):

                for block in item[
                    "structured_content"
                ]:

                    b_type = block.get(
                        "type"
                    )

                    b_text = block.get(
                        "text",
                        ""
                    )

                    if b_type == "category_header":
                        story.append(
                            Paragraph(
                                b_text,
                                category_header_style
                            )
                        )

                    elif b_type == "subheading":
                        story.append(
                            Paragraph(
                                b_text,
                                subheading_style
                            )
                        )

                    elif b_type == "key_highlights":
                        story.append(
                            Paragraph(
                                b_text,
                                key_highlights_style
                            )
                        )

                    elif b_type == "paragraph":
                        story.append(
                            Paragraph(
                                b_text,
                                body_style
                            )
                        )

                    elif b_type == "bullet_list":
                        bullet_items = []

                        for bullet in block.get(
                            "items",
                            []
                        ):
                            bullet_items.append(
                                ListItem(
                                    Paragraph(
                                        bullet,
                                        bullet_style
                                    ),
                                    leftIndent=12,
                                    bulletColor=
                                        colors.HexColor(
                                            '#1B365D'
                                        )
                                )
                            )

                        story.append(
                            ListFlowable(
                                bullet_items,
                                bulletType='bullet',
                                start='square',
                                leftIndent=10
                            )
                        )

                        story.append(
                            Spacer(
                                1,
                                4
                            )
                        )

                    elif b_type == "table":
                        matrix = block.get(
                            "matrix",
                            []
                        )

                        if matrix:
                            table_data = []

                            for row_idx, row in enumerate(
                                matrix
                            ):
                                formatted_row = []

                                for cell_text in row:
                                    style_to_use = (
                                        table_header_cell_style
                                        if row_idx == 0
                                        else
                                        table_body_cell_style
                                    )

                                    formatted_row.append(
                                        Paragraph(
                                            cell_text,
                                            style_to_use
                                        )
                                    )

                                table_data.append(
                                    formatted_row
                                )

                            num_cols = (
                                max(
                                    len(r)
                                    for r in matrix
                                )
                                if matrix
                                else 1
                            )

                            col_w = (
                                content_width
                                / float(num_cols)
                            )

                            t_flowable = Table(
                                table_data,
                                colWidths=[
                                    col_w
                                ] * num_cols
                            )

                            t_flowable.setStyle(
                                TableStyle(
                                    [
                                        (
                                            'BACKGROUND',
                                            (0, 0),
                                            (-1, 0),
                                            colors.HexColor(
                                                '#E65100'
                                            )
                                        ),
                                        (
                                            'TEXTCOLOR',
                                            (0, 0),
                                            (-1, 0),
                                            colors.white
                                        ),
                                        (
                                            'ALIGN',
                                            (0, 0),
                                            (-1, -1),
                                            'CENTER'
                                        ),
                                        (
                                            'VALIGN',
                                            (0, 0),
                                            (-1, -1),
                                            'MIDDLE'
                                        ),
                                        (
                                            'GRID',
                                            (0, 0),
                                            (-1, -1),
                                            0.5,
                                            colors.HexColor(
                                                '#CCCCCC'
                                            )
                                        ),
                                        (
                                            'TOPPADDING',
                                            (0, 0),
                                            (-1, -1),
                                            5
                                        ),
                                        (
                                            'BOTTOMPADDING',
                                            (0, 0),
                                            (-1, -1),
                                            5
                                        ),
                                        (
                                            'LEFTPADDING',
                                            (0, 0),
                                            (-1, -1),
                                            4
                                        ),
                                        (
                                            'RIGHTPADDING',
                                            (0, 0),
                                            (-1, -1),
                                            4
                                        )
                                    ]
                                )
                            )

                            story.append(
                                Spacer(
                                    1,
                                    6
                                )
                            )

                            story.append(
                                t_flowable
                            )

                            story.append(
                                Spacer(
                                    1,
                                    8
                                )
                            )

            else:
                desc = sanitize_text(
                    item.get(
                        "desc",
                        ""
                    )
                )

                if (
                    desc
                    and desc != item.get(
                        "title"
                    )
                ):
                    for paragraph_text in desc.split(
                        "\n\n"
                    ):
                        p_clean = html.escape(
                            sanitize_text(
                                paragraph_text
                            )
                        )

                        if p_clean:
                            story.append(
                                Paragraph(
                                    p_clean,
                                    body_style
                                )
                            )

            story.append(
                Spacer(
                    1,
                    4
                )
            )

            story.append(
                HRFlowable(
                    width="100%",
                    thickness=0.6,
                    color=colors.HexColor(
                        '#E0E0E0'
                    ),
                    spaceAfter=14
                )
            )

    doc.build(
        story
    )

    print(
        f"{COLORS['GREEN']}[+] Successfully generated "
        f"PDF Document: {filepath}"
        f"{COLORS['RESET']}"
    )


# === MAIN PIPELINE RUNNER ===
def run_updates():
    if not check_internet():
        message = (
            f"[{india_now()}] Device offline, "
            f"skipping PDF generation and Google Drive sync."
        )
        print(message)
        if os.environ.get("GITHUB_ACTIONS", "").lower() == "true":
            raise RuntimeError(message)
        return

    session = requests.Session()
    session.headers.update(HEADERS)

    # In GitHub Actions, route Adda247 listing and article requests through
    # the dedicated Apps Script fetch proxy. AffairsCloud, RSS, images and
    # all other requests continue using the original direct session.
    if os.environ.get("GITHUB_ACTIONS", "").lower() == "true":
        if not ADDA247_PROXY_URL or not ADDA247_PROXY_SECRET:
            raise RuntimeError(
                "Configure ADDA247_PROXY_URL and ADDA247_PROXY_SECRET "
                "in GitHub Actions to fetch Adda247."
            )
        adda_session = Adda247ProxySession(session)
    else:
        # Preserve the existing direct-fetch behavior on Android/Pydroid.
        adda_session = session

    notif_lines = []

    # 1. RSS NEWS ARTICLES
    show_status(
        "0% - Fast Scraping RSS News Articles..."
    )

    all_news = []

    for source, url in NEWS_SOURCES.items():
        try:
            feed = feedparser.parse(
                url
            )

            source_count = 0

            for entry in feed.entries:
                if source_count >= 5:
                    break

                link = entry.get(
                    'link',
                    ''
                ).strip()

                title = sanitize_text(
                    entry.get(
                        'title',
                        ''
                    )
                )

                if (
                    not title
                    or not is_english_text(title)
                    or any(
                        w in title.lower()
                        for w in EXCLUDE_KEYWORDS
                    )
                ):
                    continue

                raw_summary = (
                    entry.get(
                        'summary',
                        ''
                    )
                    or
                    entry.get(
                        'description',
                        ''
                    )
                )

                desc = (
                    sanitize_text(
                        BeautifulSoup(
                            raw_summary,
                            'html.parser'
                        ).get_text()
                    )
                    if raw_summary
                    else title
                )

                img_url = extract_rss_image(
                    entry
                )

                dt = (
                    datetime(
                        *entry.published_parsed[:6]
                    )
                    if entry.get(
                        'published_parsed'
                    )
                    else
                    india_now()
                )

                all_news.append(
                    {
                        'ts': dt,
                        'source_name': source,
                        'date_label':
                            f"{source} "
                            f"({dt.strftime('%d %b %Y')})",
                        'title': title,
                        'desc': desc,
                        'image_url': img_url,
                        'raw_link': link
                    }
                )

                source_count += 1

        except Exception as e:
            print(
                f"[!] Failed parsing RSS for "
                f"{source}: {e}"
            )
            continue

    all_news.sort(
        key=lambda x: x['ts'],
        reverse=True
    )

    if all_news:
        notif_lines.append(
            "📰 NEWS"
        )

        for item in all_news[:2]:
            notif_lines.append(
                f"• {item['title']}"
            )

    # 2. CURRENT AFFAIRS
    show_status(
        "33% - Fetching Current Affairs "
        "(AffairsCloud and Adda247 with Tables)..."
    )

    ac_items = (
        fetch_affairscloud_today_and_yesterday(
            session
        )
    )

    adda_items = (
        fetch_adda247_previous_3_days(
            adda_session
        )
    )

    rows_ca = []

    for ac_item in ac_items:
        rows_ca.append(
            ac_item
        )

    for adda_item in adda_items:
        if not any(
            item['raw_link']
            == adda_item['raw_link']
            for item in rows_ca
        ):
            rows_ca.append(
                adda_item
            )

    if rows_ca:
        notif_lines.append(
            "\n⚡ CURRENT AFFAIRS"
        )

        for item in rows_ca[:2]:
            notif_lines.append(
                f"• {item['title']}"
            )

    # 3. BANKING AND RBI CURRENT AFFAIRS
    show_status(
        "66% - Scraping Banking & RBI "
        "Current Affairs (Adda247)..."
    )

    rows_banking = (
        fetch_banking_current_affairs(
            adda_session,
            cutoff_days=90
        )
    )

    rows_banking.sort(
        key=lambda x: x['ts'],
        reverse=True
    )

    # Retry incomplete Adda247 article pages once the first pass across both
    # current-affairs sections is complete. Never replace Drive PDFs with
    # headline-only Adda247 entries from GitHub Actions.
    if os.environ.get("GITHUB_ACTIONS", "").lower() == "true":
        adda_rows_for_validation = []
        seen_adda_urls = set()
        for row in rows_ca + rows_banking:
            if (
                row.get("source_name") in ("Adda247", "Banking Current Affairs")
                and row.get("raw_link")
                and row["raw_link"] not in seen_adda_urls
            ):
                seen_adda_urls.add(row["raw_link"])
                adda_rows_for_validation.append(row)

        incomplete_adda_rows = retry_incomplete_adda247_articles(
            adda_rows_for_validation,
            adda_session
        )
        if incomplete_adda_rows:
            raise RuntimeError(
                f"Aborting before PDF generation and Google Drive upload: "
                f"{len(incomplete_adda_rows)} Adda247 article(s) still have "
                f"headline-only content after recovery retries. Existing "
                f"Google Drive PDFs were not changed. See INCOMPLETE ARTICLE "
                f"entries above."
            )

    if rows_banking:
        notif_lines.append(
            "\n🏦 BANKING & RBI CA"
        )

        for item in rows_banking[:2]:
            notif_lines.append(
                f"• {item['title']}"
            )

    # 4. GENERATE PDFS
    show_status(
        "85% - Generating PDF Documents..."
    )

    if not os.path.exists(
        DOWNLOAD_DIR
    ):
        os.makedirs(
            DOWNLOAD_DIR,
            exist_ok=True
        )

    local_pdf_path = os.path.join(
        DOWNLOAD_DIR,
        "Daily_Articles.pdf"
    )

    generate_pdf_document(
        all_news,
        rows_ca,
        rows_banking,
        session,
        local_pdf_path,
        is_desktop=False
    )

    # Keep both PDFs in the workflow output directory on GitHub Actions
    # so they can also be downloaded as a workflow artifact.
    temp_dir = (
        DOWNLOAD_DIR
        if os.environ.get("GITHUB_ACTIONS", "").lower() == "true"
        else tempfile.gettempdir()
    )

    drive_pdf_temp_path = os.path.join(
        temp_dir,
        "Daily_Articles_Desktop.pdf"
    )

    generate_pdf_document(
        all_news,
        rows_ca,
        rows_banking,
        session,
        drive_pdf_temp_path,
        is_desktop=True
    )

    # 5. UPLOAD DESKTOP PDF TO GOOGLE DRIVE & CLEANUP
    show_status(
        "95% - Uploading Desktop PDF to Google Drive..."
    )

    if USE_UPLOAD_BRIDGE:
        desktop_uploaded = upload_pdf_via_apps_script(
            drive_pdf_temp_path,
            "Daily_Articles.pdf"
        )
        mobile_uploaded = upload_pdf_via_apps_script(
            local_pdf_path,
            "Daily_Articles_Mobile.pdf"
        )
        if not desktop_uploaded or not mobile_uploaded:
            raise RuntimeError("One or more Google Drive uploads failed.")
    else:
        # Existing direct Drive upload remains available for local Android runs
        # and as a GitHub OAuth fallback until the bridge is fully verified.
        desktop_uploaded = upload_pdf_to_drive(
            drive_pdf_temp_path,
            DRIVE_FOLDER_ID,
            creds,
            target_name="Daily_Articles.pdf"
        )

        if os.environ.get("GITHUB_ACTIONS", "").lower() == "true":
            if not desktop_uploaded:
                raise RuntimeError("Desktop PDF upload to Google Drive failed.")

            mobile_folder_id = get_or_create_drive_subfolder(
                DRIVE_FOLDER_ID,
                MOBILE_DRIVE_FOLDER_NAME,
                creds
            )

            mobile_uploaded = upload_pdf_to_drive(
                local_pdf_path,
                mobile_folder_id,
                creds,
                target_name="Daily_Articles_Mobile.pdf"
            )

            if not mobile_uploaded:
                raise RuntimeError("Mobile PDF upload to Google Drive failed.")

    if (
        os.path.exists(drive_pdf_temp_path)
        and os.environ.get("GITHUB_ACTIONS", "").lower() != "true"
    ):
        os.remove(
            drive_pdf_temp_path
        )

    show_status(
        "100% - Processing Complete!"
    )

    # 6. TRIGGER TERMUX NOTIFICATION (local Android runs only)
    if (
        notif_lines
        and os.environ.get("GITHUB_ACTIONS", "").lower() != "true"
    ):
        summary_metrics = [
            f"📊 Articles -> News: "
            f"{len(all_news)} | "
            f"CA: {len(rows_ca)} | "
            f"Banking: {len(rows_banking)}",

            "\n✨ RECENT HEADLINES:"
        ]

        summary_metrics.extend(
            notif_lines
        )

        send_notify(
            "News Engine: PDF Generated & Uploaded to Drive",
            "\n".join(
                summary_metrics
            )
        )


if __name__ == "__main__":
    run_updates()
