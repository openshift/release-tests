# Async Approval Release Implementation

## Overview

This document describes the new async implementation for the `approve_release` function in `oar/core/operators.py`. The solution enables asynchronous execution of metadata URL checking while providing immediate feedback to users.

## Key Changes Made

### 1. Modified `approve_release()` Method

**Location**: `oar/core/operators.py` - `ApprovalOperator.approve_release()`

**Changes**:
- Returns `"SCHEDULED"` instead of blocking when metadata URL is not immediately accessible
- Launches background process using `subprocess.Popen` with `start_new_session=True` for true process independence
- Maintains existing file-based locking mechanism to prevent duplicate processes

**Return Values**:
- `True`: Metadata URL accessible immediately, advisories moved to REL_PREP
- `"SCHEDULED"`: Background process started for periodic checking (process continues independently after parent exit)
- `False`: Scheduler already running (lock file exists)

### 2. Added Background Worker Function

**Location**: `oar/core/operators.py` - `ApprovalOperator._background_metadata_checker()`

**Functionality**:
- Runs in separate process
- Periodically checks metadata URL accessibility (every 30 minutes)
- Handles 2-day timeout
- Sends completion notifications based on environment variables
- Properly manages scheduler lock files

### 3. Enhanced Completion Notification System

**Location**: `oar/core/notification.py` - `NotificationManager.share_release_approval_completion()`

**Features**:
- **Always sends to default channel**: Summary notification sent to QE release channel regardless of context
- **Thread-specific full logs**: When Slack context available (`OAR_SLACK_CHANNEL`, `OAR_SLACK_THREAD`), sends complete log messages to original thread
- **Message splitting**: Handles large log outputs using `util.split_large_message()`
- **Comprehensive logging**: Includes all background process logs plus summary
- **Error handling**: Proper notification for success, timeout, and error scenarios

### 4. Updated CLI Command

**Location**: `oar/cli/cmd_change_advisory_status.py`

**Changes**:
- Updated to handle new return type (string "SCHEDULED")
- Maintains task status as INPROGRESS when background process starts
- Provides informative logging

### 5. Enhanced Slack Integration

**Location**: `tools/slack_message_receiver.py`

**Changes**:
- Sets environment variables `OAR_SLACK_CHANNEL` and `OAR_SLACK_THREAD` for subprocesses
- Enables thread-specific completion notifications

## How It Works

### Slack Execution Flow:
1. User sends command via Slack: `oar change-advisory-status`
2. Slack receiver sets environment variables with channel/thread context
3. Command executes in subprocess with inherited environment
4. If metadata URL not accessible immediately:
   - Background process starts
   - Returns "SCHEDULED" to CLI
   - CLI logs "Background metadata checker process started"
5. Background process periodically checks metadata URL
6. When accessible:
   - Moves advisories to REL_PREP
   - **Sends summary notification to default QE release channel**
   - **Sends full log messages to original Slack thread**
7. On timeout/error:
   - **Sends summary notification to default QE release channel**
   - **Sends full error details to original Slack thread**

### Non-Slack Execution Flow:
1. User runs command directly: `oar change-advisory-status`
2. No Slack environment variables set
3. If metadata URL not accessible immediately:
   - Background process starts
   - Returns "SCHEDULED" to CLI
4. Background process completes:
   - **Sends summary notification to default QE release channel**
   - No thread-specific messaging (no Slack context available)

## Environment Variables

- `OAR_SLACK_CHANNEL`: Set by Slack receiver with channel ID
- `OAR_SLACK_THREAD`: Set by Slack receiver with thread timestamp

## Benefits

1. **Dual Notification**: Summary notifications always sent to QE release channel + full logs to original thread
2. **Improved User Experience**: Immediate feedback in Slack threads with complete execution details
3. **Non-Blocking**: CLI commands return quickly instead of blocking for up to 2 days
4. **Backward Compatibility**: Existing functionality preserved for non-Slack usage
5. **Thread Awareness**: Completion messages with full logs go to the original request thread
6. **Error Handling**: Proper notification for timeouts and errors to both channels

## Usage

The solution works automatically - no changes required for users. The same CLI commands now provide async behavior when executed through Slack.
