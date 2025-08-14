# GDVC Mini

[![PyPI version](https://badge.fury.io/py/gdvc-mini.svg)](https://badge.fury.io/py/gdvc-mini)

Simple version control using Google Drive folders. 
I wanted something in between rclone and dvc

## Install
```
pip install -e .
```

Push to drive setup:
```
gcloud auth application-default login --scopes=https://www.googleapis.com/auth/cloud-platform,https://www.googleapis.com/auth/drive
```
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

Upload version: to a private repo
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
      "local_path": "."
    }
  },
  "current_version": "v1.0",
  "tracked_directories": ["models", "data"]
}
```