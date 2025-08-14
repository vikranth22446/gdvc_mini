# GDVC Mini

[![PyPI version](https://badge.fury.io/py/gdvc-mini.svg)](https://badge.fury.io/py/gdvc-mini)

Simple version control using Google Drive folders. Simplifes the process of quick iteration and dev sharing within drive.

A simplified midway between [dvc](https://dvc.org/)/[rclone](https://rclone.org/drive/).

#### Alternatives:
Rclone/DVC:
1. Rclone/dvc require permissions for downloading and initial setup. This makes others testing a repo harder
2. DVC also uses a custom file format and doesn't allow for quick downloading for testing

Git LFS:
1. Limited file storage and no support for custom backends

Note: This is not intended for full model checkpoints, as each version currently duplicates the entire folder.

## Install
```
pip install gdvc
```

dev Version:
```
pip install -e .
```

push to drive setup:
```
gcloud auth application-default login --scopes=https://www.googleapis.com/auth/cloud-platform,https://www.googleapis.com/auth/drive
```
init your drive folder:
```
gdvc init https://drive.google.com/drive/folders/YOUR_FOLDER_ID
```

## Usage

Track directories:
```
gdvc track add models
gdvc track add data
gdvc track list
```

Upload a version (to your configured private Google Drive folder):
```
gdvc upload v1
```

Download version:
```
gdvc download v1
gdvc download latest
```

Change to different Drive folder:
```
gdvc change_folder_root https://drive.google.com/drive/folders/NEW_FOLDER_ID
```

## Commands

- `init <folder_url>` - Initialize project
- `track add/remove/list` - Manage tracked directories  
- `upload <version>` - Upload tracked directories as version
- `download <version>` - Download version to current directory
- `change_folder_root <url>` - Switch to new Drive folder, keep current version only
- `publish <version>` - Make version public
- `update` - Download latest version

## File Structure

Uploads create: `version_name/directory_name/files`
Downloads merge into current directory preserving structure.

## Configuration

Project settings are stored in `.gdvc_config.json` which can be safely committed to git.
Contains Drive folder URLs, version history, and tracked directories.

**Sample config structure:**
```json
{
  "drive_folder_url": "https://drive.google.com/drive/folders/<sample_folder>",
  "versions": {
    "v1.0": {
      "url": "https://drive.google.com/drive/folders/<sample_folder>",
      "local_path": ".",
      "is_public": false
    },
   },
  "public_version": "v0",
  "current_version": "v1.0",
  "tracked_directories": ["models", "data"]
}
```