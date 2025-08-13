import argparse
import json
import os
import re
import sys
from urllib.parse import parse_qs, urlparse

import gdown
from google.auth import default
from google.auth.exceptions import DefaultCredentialsError
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

CONFIG_FILE = ".gdvc_config.json"
KEY_VERSIONS = "versions"
KEY_CURRENT = "current_version"
KEY_PUBLIC = "public_version"
KEY_FOLDER_URL = "drive_folder_url"
KEY_TRACKED_DIRS = "tracked_directories"

SENSITIVE_PATTERNS = [
    ".env",
    ".key",
    ".pem",
    ".p12",
    ".pfx",
    ".crt",
    ".cer",
    "credentials",
    "secret",
    "token",
    "password",
    "config.json",
    ".ssh/",
    "id_rsa",
    "id_ed25519",
    ".git/config",
    "settings.ini",
]


def load_config():
    if not os.path.exists(CONFIG_FILE):
        sys.exit(f"Config file '{CONFIG_FILE}' not found.")
    try:
        with open(CONFIG_FILE, "r") as f:
            config = json.load(f)
    except json.JSONDecodeError:
        sys.exit(f"Config file '{CONFIG_FILE}' is not valid JSON.")

    for key in [KEY_VERSIONS, KEY_FOLDER_URL]:
        if key not in config:
            sys.exit(f"Missing '{key}' in config file.")

    if KEY_TRACKED_DIRS not in config:
        config[KEY_TRACKED_DIRS] = []
    if KEY_CURRENT not in config:
        config[KEY_CURRENT] = None
    if KEY_PUBLIC not in config:
        config[KEY_PUBLIC] = None

    migrated = False
    for ver, data in list(config[KEY_VERSIONS].items()):
        if isinstance(data, str):
            config[KEY_VERSIONS][ver] = {"url": data, "local_path": "."}
            migrated = True
    if migrated:
        save_config(config)
        print("Migrated config to new format with local_path support.")

    return config


def save_config(data):
    tmp_file = CONFIG_FILE + ".tmp"
    with open(tmp_file, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_file, CONFIG_FILE)


def is_sensitive_file(file_path):
    return any(pattern.lower() in file_path.lower() for pattern in SENSITIVE_PATTERNS)


def scan_for_sensitive_files(local_path, collected=None):
    if collected is None:
        collected = []

    if os.path.isfile(local_path):
        if is_sensitive_file(local_path):
            collected.append(local_path)
    elif os.path.isdir(local_path):
        for item in os.listdir(local_path):
            scan_for_sensitive_files(os.path.join(local_path, item), collected)

    return collected


def confirm_public_upload(sensitive_files, total_files):
    print(f"\nUpload Summary: {total_files} files")

    if sensitive_files:
        print(f"WARNING: Found {len(sensitive_files)} sensitive files")
        for f in sensitive_files[:5]:
            print(f"   • {f}")
        if len(sensitive_files) > 5:
            print(f"   ... and {len(sensitive_files) - 5} more")
        print("\nREFUSING to make sensitive files public. Use --private flag.")
        return False

    print("Files will be PUBLIC (anyone with link can download)")
    return input("\nContinue? (y/N): ").strip().lower() in ["y", "yes"]


def get_folder_id_from_url(url):
    parsed = urlparse(url)
    m = re.search(r"/folders/([a-zA-Z0-9_-]+)", parsed.path)
    if m:
        return m.group(1)
    qs_id = parse_qs(parsed.query).get("id", [None])[0]
    if qs_id:
        return qs_id
    sys.exit(f"Invalid Google Drive folder URL: {url}")


def init_drive_auth():
    try:
        credentials, _ = default(scopes=["https://www.googleapis.com/auth/drive"])
        service = build("drive", "v3", credentials=credentials)
        return service
    except DefaultCredentialsError as e:
        sys.exit(
            f"Authentication failed: No valid credentials found. Run 'gcloud auth application-default login' first. Error: {e}"
        )
    except Exception as e:
        sys.exit(f"Authentication failed: {e}")


def ensure_public_permission(drive_service, file_id):
    try:
        permission = {"type": "anyone", "role": "reader"}
        drive_service.permissions().create(fileId=file_id, body=permission).execute()
        return True
    except Exception as e:
        error_str = str(e).lower()
        if "403" in error_str or "forbidden" in error_str:
            print(f"Permission denied: {e}")
        elif "404" in error_str:
            print(f"File not found: {e}")
        else:
            print(f"Failed to set public permission: {e}")
        return False


def ensure_public_recursive(drive_service, folder_id):
    failed_items = []

    if not ensure_public_permission(drive_service, folder_id):
        failed_items.append(f"folder:{folder_id}")

    try:
        results = (
            drive_service.files()
            .list(q=f"'{folder_id}' in parents and trashed=false")
            .execute()
        )
        items = results.get("files", [])
        for item in items:
            if item["mimeType"] == "application/vnd.google-apps.folder":
                failed_items.extend(ensure_public_recursive(drive_service, item["id"]))
            elif not ensure_public_permission(drive_service, item["id"]):
                failed_items.append(f"file:{item['name']}")
    except Exception as e:
        error_str = str(e).lower()
        if "403" in error_str or "forbidden" in error_str:
            print(f"Access denied listing folder: {e}")
        else:
            print(f"Failed to list folder: {e}")
        failed_items.append(f"folder_listing:{folder_id}")

    return failed_items


def upload_folder_recursive(drive_service, local_path, parent_folder_id, make_public):
    folder_name = os.path.basename(local_path.rstrip(os.sep))
    folder_metadata = {
        "name": folder_name,
        "parents": [parent_folder_id],
        "mimeType": "application/vnd.google-apps.folder",
    }
    folder = drive_service.files().create(body=folder_metadata).execute()
    folder_id = folder["id"]

    if make_public:
        ensure_public_permission(drive_service, folder_id)

    for item in os.listdir(local_path):
        item_path = os.path.join(local_path, item)
        if os.path.isfile(item_path):
            try:
                file_metadata = {"name": item, "parents": [folder_id]}
                media = MediaFileUpload(item_path)
                file = (
                    drive_service.files()
                    .create(body=file_metadata, media_body=media)
                    .execute()
                )
                if make_public:
                    ensure_public_permission(drive_service, file["id"])
                print(f"Uploaded {item}")
            except Exception as e:
                print(f"Failed to upload {item}: {e}")
        elif os.path.isdir(item_path):
            upload_folder_recursive(drive_service, item_path, folder_id, make_public)

    return folder_id


def upload_tracked_version(version_name, make_public=False):
    config = load_config()
    tracked_dirs = config.get(KEY_TRACKED_DIRS, [])

    if not tracked_dirs:
        sys.exit(
            "❌ No directories are being tracked. Use 'gdvc track add <directory>' to add directories."
        )

    existing_dirs = []
    missing_dirs = []
    all_sensitive_files = []
    total_files = 0

    for dir_name in tracked_dirs:
        if os.path.exists(dir_name) and os.path.isdir(dir_name):
            existing_dirs.append(dir_name)
            sensitive_files = scan_for_sensitive_files(dir_name)
            all_sensitive_files.extend(sensitive_files)
            total_files += sum([len(files) for _, _, files in os.walk(dir_name)])
        else:
            missing_dirs.append(dir_name)

    if not existing_dirs:
        sys.exit("❌ None of the tracked directories exist locally.")

    if missing_dirs:
        print(
            f"⚠️ Warning: Missing directories (will be skipped): {', '.join(missing_dirs)}"
        )

    if make_public and not confirm_public_upload(all_sensitive_files, total_files):
        sys.exit("Upload cancelled by user.")

    drive = init_drive_auth()
    parent_folder_id = get_folder_id_from_url(config[KEY_FOLDER_URL])

    try:
        results = (
            drive.files()
            .list(
                q=f"'{parent_folder_id}' in parents and "
                f"mimeType='application/vnd.google-apps.folder' and "
                f"name='{version_name}' and trashed=false"
            )
            .execute()
        )
        existing = results.get("files", [])
    except Exception as e:
        sys.exit(f"❌ Failed to query Drive: {e}")

    if existing:
        version_folder = existing[0]
        version_id = version_folder["id"]
        print(f"Reusing existing version folder '{version_name}' (id={version_id})")
    else:
        folder_metadata = {
            "name": version_name,
            "parents": [parent_folder_id],
            "mimeType": "application/vnd.google-apps.folder",
        }
        version_folder = drive.files().create(body=folder_metadata).execute()
        version_id = version_folder["id"]
        print(f"📁 Created version folder '{version_name}'")

    if make_public:
        ensure_public_permission(drive, version_id)

    for dir_name in existing_dirs:
        print(f"📂 Uploading directory: {dir_name}")
        upload_folder_recursive(drive, dir_name, version_id, make_public)

    public_url = f"https://drive.google.com/drive/folders/{version_id}?usp=sharing"
    config[KEY_VERSIONS][version_name] = {"url": public_url, "local_path": "."}
    config[KEY_CURRENT] = version_name
    save_config(config)

    print(f"✅ Uploaded version '{version_name}'")
    print(f"📂 Included directories: {', '.join(existing_dirs)}")
    if make_public:
        print(f"🔗 Public link (unauth downloads OK): {public_url}")
    else:
        print("🔒 Uploaded privately. Unauthenticated downloads will NOT work.")


def upload_version(local_folder, version_name, make_public=False):
    if not os.path.isdir(local_folder):
        sys.exit(f"Local folder '{local_folder}' does not exist.")

    sensitive_files = scan_for_sensitive_files(local_folder)
    total_files = sum([len(files) for _, _, files in os.walk(local_folder)])

    if make_public and not confirm_public_upload(sensitive_files, total_files):
        sys.exit("Upload cancelled by user.")

    drive = init_drive_auth()
    config = load_config()
    parent_folder_id = get_folder_id_from_url(config[KEY_FOLDER_URL])

    try:
        results = (
            drive.files()
            .list(
                q=f"'{parent_folder_id}' in parents and "
                f"mimeType='application/vnd.google-apps.folder' and "
                f"name='{version_name}' and trashed=false"
            )
            .execute()
        )
        existing = results.get("files", [])
    except Exception as e:
        sys.exit(f"❌ Failed to query Drive: {e}")

    if existing:
        version_folder = existing[0]
        version_id = version_folder["id"]
        print(f"Reusing existing version folder '{version_name}' (id={version_id})")
    else:
        folder_metadata = {
            "name": version_name,
            "parents": [parent_folder_id],
            "mimeType": "application/vnd.google-apps.folder",
        }
        version_folder = drive.files().create(body=folder_metadata).execute()
        version_id = version_folder["id"]
        print(f"📁 Created version folder '{version_name}'")

    if make_public:
        ensure_public_permission(drive, version_id)

    for item in os.listdir(local_folder):
        path = os.path.join(local_folder, item)
        if os.path.isfile(path):
            try:
                file_metadata = {"name": item, "parents": [version_id]}
                media = MediaFileUpload(path)
                file = (
                    drive.files().create(body=file_metadata, media_body=media).execute()
                )
                if make_public:
                    ensure_public_permission(drive, file["id"])
                print(f"📤 Uploaded {item}")
            except Exception as e:
                print(f"⚠️ Failed to upload {item}: {e}")
        elif os.path.isdir(path):
            upload_folder_recursive(drive, path, version_id, make_public)

    public_url = f"https://drive.google.com/drive/folders/{version_id}?usp=sharing"
    config[KEY_VERSIONS][version_name] = {"url": public_url, "local_path": "."}
    config[KEY_CURRENT] = version_name
    save_config(config)

    print(f"✅ Uploaded version '{version_name}'")
    if make_public:
        print(f"🔗 Public link (unauth downloads OK): {public_url}")
    else:
        print("🔒 Uploaded privately. Unauthenticated downloads will NOT work.")


def download_version(version_name):
    config = load_config()
    if version_name not in config[KEY_VERSIONS]:
        sys.exit(f"❌ Version '{version_name}' not found in config.")

    version_info = config[KEY_VERSIONS][version_name]
    folder_id = get_folder_id_from_url(version_info["url"])
    version_path = version_info["local_path"]

    os.makedirs(version_path, exist_ok=True)
    print(f"⬇️ Downloading '{version_name}' to {version_path}")

    try:
        gdown.download_folder(
            id=folder_id, output=version_path, quiet=False, use_cookies=False
        )
        print(f"✅ Downloaded to {version_path}")
    except Exception as e:
        msg = str(e)
        if "permission" in msg.lower() or "403" in msg or "not allowed" in msg.lower():
            sys.exit("❌ Download failed: This folder is not public.")
        sys.exit(f"❌ Download failed: {e}")


def download_latest():
    config = load_config()
    latest = config.get(KEY_PUBLIC)
    if not latest:
        sys.exit("❌ No public version set in config.")
    if latest not in config.get(KEY_VERSIONS, {}):
        sys.exit(f"❌ Public version '{latest}' missing from versions map.")
    download_version(latest)


def publish_version(version_name, recursive=True):
    config = load_config()
    versions = config.get(KEY_VERSIONS, {})
    if version_name not in versions:
        sys.exit(f"❌ Version '{version_name}' not found in config.")

    folder_id = get_folder_id_from_url(versions[version_name]["url"])
    drive = init_drive_auth()

    if recursive:
        print("Publishing folder and contents (recursive)...")
        failed_items = ensure_public_recursive(drive, folder_id)
        if failed_items:
            print(f"Warning: Failed to publish {len(failed_items)} items:")
            for item in failed_items[:10]:
                print(f"  - {item}")
            if len(failed_items) > 10:
                print(f"  ... and {len(failed_items) - 10} more")
        else:
            print(f"Version '{version_name}' is now fully public.")
            config[KEY_PUBLIC] = version_name
            save_config(config)
            print(f"Set '{version_name}' as the public version.")
    else:
        print("Publishing folder only...")
        success = ensure_public_permission(drive, folder_id)
        if success:
            print(f"Version '{version_name}' folder is now public.")
            config[KEY_PUBLIC] = version_name
            save_config(config)
            print(f"Set '{version_name}' as the public version.")
        else:
            print(f"Failed to publish version '{version_name}'.")


def update_to_latest():
    config = load_config()
    latest_version = config.get(KEY_PUBLIC)
    if not latest_version:
        sys.exit("No public version set in config.")

    local_path = config[KEY_VERSIONS][latest_version]["local_path"]
    if os.path.exists(local_path) and os.listdir(local_path):
        print(f"Already up-to-date with version '{latest_version}'")
    else:
        print(f"Updating to latest version: {latest_version}")
        download_version(latest_version)


def init_config(folder_url, tracked_dirs=None):
    if os.path.exists(CONFIG_FILE):
        response = (
            input(f"Config file '{CONFIG_FILE}' already exists. Overwrite? (y/N): ")
            .strip()
            .lower()
        )
        if response not in ["y", "yes"]:
            print("Init cancelled.")
            return

    try:
        folder_id = get_folder_id_from_url(folder_url)
    except SystemExit:
        sys.exit("❌ Invalid Google Drive folder URL provided.")

    config = {
        KEY_FOLDER_URL: folder_url,
        KEY_VERSIONS: {},
        KEY_CURRENT: None,
        KEY_PUBLIC: None,
        KEY_TRACKED_DIRS: tracked_dirs or [],
    }

    try:
        save_config(config)
        print(f"✅ Initialized GDVC config with folder: {folder_url}")
        print(f"📁 Folder ID: {folder_id}")
        if tracked_dirs:
            print(f"📂 Tracking directories: {', '.join(tracked_dirs)}")
        else:
            print(
                "📂 No directories tracked yet. Use 'gdvc track add <dir>' to add directories."
            )
        print(f"📄 Config saved to: {CONFIG_FILE}")
    except Exception as e:
        sys.exit(f"❌ Failed to save config: {e}")


def track_add_directory(directory):
    config = load_config()
    tracked_dirs = config.get(KEY_TRACKED_DIRS, [])

    if directory in tracked_dirs:
        print(f"📂 Directory '{directory}' is already being tracked.")
        return

    tracked_dirs.append(directory)
    config[KEY_TRACKED_DIRS] = tracked_dirs
    save_config(config)
    print(f"✅ Added '{directory}' to tracked directories.")


def track_remove_directory(directory):
    config = load_config()
    tracked_dirs = config.get(KEY_TRACKED_DIRS, [])

    if directory not in tracked_dirs:
        print(f"❌ Directory '{directory}' is not being tracked.")
        return

    tracked_dirs.remove(directory)
    config[KEY_TRACKED_DIRS] = tracked_dirs
    save_config(config)
    print(f"✅ Removed '{directory}' from tracked directories.")


def track_list_directories():
    config = load_config()
    tracked_dirs = config.get(KEY_TRACKED_DIRS, [])

    if not tracked_dirs:
        print("📂 No directories are currently being tracked.")
        print("   Use 'gdvc track add <directory>' to start tracking directories.")
    else:
        print("📂 Tracked directories:")
        for dir_name in tracked_dirs:
            status = (
                "✓" if os.path.exists(dir_name) and os.path.isdir(dir_name) else "✗"
            )
            print(f"  {status} {dir_name}")


def change_folder_root(new_folder_url):
    if not os.path.exists(CONFIG_FILE):
        sys.exit(f"❌ Config file '{CONFIG_FILE}' not found. Run 'gdvc init' first.")

    # Validate new folder URL
    try:
        new_folder_id = get_folder_id_from_url(new_folder_url)
    except SystemExit:
        sys.exit("❌ Invalid Google Drive folder URL provided.")

    # Load current config
    old_config = load_config()
    current_version = old_config.get(KEY_CURRENT)
    public_version = old_config.get(KEY_PUBLIC)
    tracked_dirs = old_config.get(KEY_TRACKED_DIRS, [])

    if not current_version:
        sys.exit("❌ No current version found in config.")

    # Backup old config
    backup_file = CONFIG_FILE + ".backup"
    with open(backup_file, "w") as f:
        json.dump(old_config, f, indent=2)
    print(f"📄 Backed up old config to: {backup_file}")

    # Create new config with only current version
    new_config = {
        KEY_FOLDER_URL: new_folder_url,
        KEY_VERSIONS: {current_version: old_config[KEY_VERSIONS][current_version]},
        KEY_CURRENT: current_version,
        KEY_PUBLIC: public_version,
        KEY_TRACKED_DIRS: tracked_dirs,
    }

    # Save new config
    save_config(new_config)

    print(f"✅ Changed folder root to: {new_folder_url}")
    print(f"📁 New folder ID: {new_folder_id}")
    print(f"📂 Preserved version: {current_version}")
    print(
        f"📂 Preserved tracked directories: {', '.join(tracked_dirs) if tracked_dirs else 'None'}"
    )
    print(f"🗑️ Removed {len(old_config[KEY_VERSIONS]) - 1} historical versions")


def preview_upload(local_folder):
    if not os.path.isdir(local_folder):
        sys.exit(f"Local folder '{local_folder}' does not exist.")

    sensitive_files = scan_for_sensitive_files(local_folder)
    all_files = [
        os.path.join(root, file)
        for root, _, files in os.walk(local_folder)
        for file in files
    ]

    print(f"\nDry Run - Upload Preview: {len(all_files)} files")

    if sensitive_files:
        print(f"Sensitive files found ({len(sensitive_files)}):")
        for f in sensitive_files:
            print(f"  SENSITIVE: {f}")

    print("All files to upload:")
    for f in all_files:
        status = "SENSITIVE" if f in sensitive_files else "OK"
        print(f"  [{status}] {f}")


def main():
    parser = argparse.ArgumentParser(
        description="GDVC-Mini: Lightweight Google Drive version control tool",
        epilog="""Examples:
  gdvc init https://drive.google.com/drive/folders/ABC123 src data
  gdvc track add models
  gdvc upload v1.0 --public
  gdvc publish v1.0
  gdvc download latest
  gdvc update

Workflow:
  1. Upload creates new version (sets current_version)
  2. Publish makes version public (sets public_version)
  3. Download/update uses public_version""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    init_parser = subparsers.add_parser(
        "init",
        help="Initialize GDVC with Google Drive folder URL",
        epilog="Examples:\n  gdvc init https://drive.google.com/drive/folders/ABC123\n  gdvc init https://drive.google.com/drive/folders/ABC123 src data models",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    init_parser.add_argument("folder_url", help="Google Drive folder URL")
    init_parser.add_argument(
        "directories", nargs="*", help="Directories to track (optional)"
    )

    upload_parser = subparsers.add_parser(
        "upload",
        help="Upload a version to Drive",
        epilog="Examples:\n  gdvc upload v1.0                    # Upload tracked directories\n  gdvc upload v1.0 --public           # Upload and make public\n  gdvc upload v1.0 ./src --public     # Upload specific folder\n  gdvc upload v1.0 --dry-run          # Preview upload",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    upload_parser.add_argument("version_name", help="Version name")
    upload_parser.add_argument(
        "local_folder",
        nargs="?",
        help="Local folder to upload (optional if using tracked directories)",
    )
    upload_parser.add_argument(
        "--public", action="store_true", help="Make files public"
    )
    upload_parser.add_argument(
        "--dry-run", action="store_true", help="Preview upload without executing"
    )

    track_parser = subparsers.add_parser(
        "track",
        help="Manage tracked directories",
        epilog="Examples:\n  gdvc track add src\n  gdvc track add models\n  gdvc track remove data\n  gdvc track list",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    track_subparsers = track_parser.add_subparsers(
        dest="track_action", help="Track actions"
    )

    track_add = track_subparsers.add_parser("add", help="Add directory to tracking")
    track_add.add_argument("directory", help="Directory to track")

    track_remove = track_subparsers.add_parser(
        "remove", help="Remove directory from tracking"
    )
    track_remove.add_argument("directory", help="Directory to stop tracking")

    track_subparsers.add_parser("list", help="List tracked directories")

    download_parser = subparsers.add_parser(
        "download",
        help="Download a version from Drive",
        epilog="Examples:\n  gdvc download v1.0\n  gdvc download latest",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    download_parser.add_argument("version", help='Version name or "latest"')

    publish_parser = subparsers.add_parser(
        "publish",
        help="Make a version public (sets as downloadable version)",
        epilog="Examples:\n  gdvc publish v1.0                   # Publish version and contents\n  gdvc publish v1.0 --no-recursive    # Publish folder only",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    publish_parser.add_argument("version_name", help="Version name to publish")
    publish_parser.add_argument(
        "--no-recursive", action="store_true", help="Publish folder only, not contents"
    )

    subparsers.add_parser(
        "update",
        help="Update to latest public version",
        epilog="Example:\n  gdvc update",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    change_root_parser = subparsers.add_parser(
        "change_folder_root",
        help="Change Drive folder root, preserving only current version",
        epilog="Example:\n  gdvc change_folder_root https://drive.google.com/drive/folders/XYZ789",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    change_root_parser.add_argument(
        "new_folder_url", help="New Google Drive folder URL"
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "init":
        init_config(args.folder_url, args.directories)
    elif args.command == "upload":
        if args.local_folder:
            # Legacy mode: upload specific folder
            if args.dry_run:
                preview_upload(args.local_folder)
            else:
                upload_version(args.local_folder, args.version_name, args.public)
        else:
            # New mode: upload tracked directories
            if args.dry_run:
                # TODO: Add dry run for tracked directories
                print("Dry run for tracked directories not yet implemented")
            else:
                upload_tracked_version(args.version_name, args.public)
    elif args.command == "track":
        if args.track_action == "add":
            track_add_directory(args.directory)
        elif args.track_action == "remove":
            track_remove_directory(args.directory)
        elif args.track_action == "list":
            track_list_directories()
        else:
            track_parser.print_help()
    elif args.command == "download":
        if args.version.lower() == "latest":
            download_latest()
        else:
            download_version(args.version)
    elif args.command == "publish":
        publish_version(args.version_name, recursive=not args.no_recursive)
    elif args.command == "update":
        update_to_latest()
    elif args.command == "change_folder_root":
        change_folder_root(args.new_folder_url)


if __name__ == "__main__":
    main()
