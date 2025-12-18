import logging
import sys

import click

import oar.core.util as util
from oar import version
from oar.cli.cmd_change_advisory_status import change_advisory_status
from oar.cli.cmd_check_cve_tracker_bug import check_cve_tracker_bug
from oar.cli.cmd_create_test_report import create_test_report
from oar.cli.cmd_image_consistency_check import image_consistency_check
from oar.cli.cmd_image_signed_check import image_signed_check
from oar.cli.cmd_push_to_cdn import push_to_cdn_staging
from oar.cli.cmd_stage_testing import stage_testing
from oar.cli.cmd_take_ownership import take_ownership
from oar.core.configstore import ConfigStore
from oar.core.const import CONTEXT_SETTINGS, TASK_STATUS_PASS, TASK_STATUS_FAIL, TASK_STATUS_INPROGRESS, WORKFLOW_TASK_NAMES
from oar.core.log_capture import capture_logs, merge_output
from oar.core.statebox import StateBox
from oar.core.exceptions import StateBoxException

logger = logging.getLogger(__name__)


def print_version(ctx, param, value):
    if not value or ctx.resilient_parsing:
        return
    click.echo("oar v{}".format(version()))
    click.echo("python v{}".format(sys.version))
    ctx.exit()


def cli_result_callback(result, release, debug):
    """
    Result callback for CLI group - automatically updates StateBox after command execution.

    This callback is invoked after every subcommand completes, allowing us to:
    1. Capture all logs from the command execution
    2. Update StateBox with task results
    3. Handle errors transparently

    The callback runs transparently - users see normal output, StateBox updates happen
    in the background.

    Args:
        result: Return value from subcommand (unused)
        release: Release version from CLI group option
        debug: Debug flag from CLI group option

    Design:
        - Logs are captured via ctx.obj['_log_buffer'] (set by CLI group or provided by MCP server)
        - Task name is derived from Click command name (e.g., "create-test-report")
        - ConfigStore retrieved from ctx.obj['cs'] (cached in MCP server, fresh in CLI)
        - StateBox initialized with ConfigStore dependency injection: StateBox(configstore=cs)
        - Release version extracted from configstore.release (not passed directly)
        - StateBox update happens after command completes
        - Failures are logged but don't block the command
    """
    # Get current context to access ctx.obj
    try:
        ctx = click.get_current_context()
    except RuntimeError:
        # No context available
        return

    # Skip StateBox update if:
    # - No release in context (help mode)
    # - No ConfigStore available (not initialized)
    # - MCP server explicitly disabled updates (ctx.obj.get('skip_statebox_update'))
    if not ctx.obj or 'cs' not in ctx.obj:
        return

    if ctx.obj.get('skip_statebox_update', False):
        return

    # Release is already passed as parameter from CLI group
    if not release:
        return

    # Get command name from invoked subcommand
    command_name = ctx.invoked_subcommand
    if not command_name:
        return

    # Skip StateBox update if command is not a workflow task
    # Only tasks in WORKFLOW_TASK_NAMES should be tracked in StateBox
    if command_name not in WORKFLOW_TASK_NAMES:
        return

    # Get captured logs from buffer (set by __main__.py or MCP server)
    log_buffer = ctx.obj.get('_log_buffer')
    if log_buffer:
        captured_logs = log_buffer.getvalue()
    else:
        captured_logs = ctx.obj.get('captured_logs', '')

    # Get explicit output if provided by command
    explicit_output = ctx.obj.get('statebox_output')

    # Determine final output for StateBox
    if explicit_output:
        output = explicit_output.strip() if explicit_output else None
    elif captured_logs:
        output = captured_logs.strip() if captured_logs else None
    else:
        output = None

    # Determine task status by parsing command output
    # For async tasks (push-to-cdn, image-consistency-check, stage-testing),
    # the last line determines the status:
    # - Contains [Pass] → Pass
    # - Contains [Fail] → Fail
    # - Contains [In Progress] → In Progress
    # - Contains error logs (: ERROR:) → Fail
    # - Otherwise (no status marker) → In Progress (async job triggered)
    explicit_status = ctx.obj.get('statebox_status')
    if explicit_status:
        status = explicit_status
    elif output:
        last_line = output.strip().split('\n')[-1] if output.strip() else ''
        if f'[{TASK_STATUS_FAIL}]' in last_line:
            status = TASK_STATUS_FAIL
        elif f'[{TASK_STATUS_PASS}]' in last_line:
            status = TASK_STATUS_PASS
        elif f'[{TASK_STATUS_INPROGRESS}]' in last_line:
            status = TASK_STATUS_INPROGRESS
        elif ': ERROR:' in output:
            # Check for error logs in output (handles exceptions before update_task_status)
            status = TASK_STATUS_FAIL
        else:
            # No status marker in last line → async job triggered but not completed
            status = TASK_STATUS_INPROGRESS
    else:
        # No output captured - default to Pass for backward compatibility
        status = TASK_STATUS_PASS

    try:
        # Get ConfigStore from context (cached in MCP server)
        cs = ctx.obj.get('cs')

        # Pass cached ConfigStore to StateBox (release extracted from ConfigStore)
        statebox = StateBox(configstore=cs)

        # Update task with captured output
        statebox.update_task(
            task_name=command_name,
            status=status,
            result=output,
            auto_save=True
        )
        logger.info(f"StateBox updated successfully for task '{command_name}'")

    except StateBoxException as e:
        # Log error but don't fail the command
        logger.warning(f"Failed to update StateBox for task '{command_name}': {e}")
    except Exception as e:
        logger.warning(f"Unexpected error updating StateBox: {e}")


@click.group(context_settings=CONTEXT_SETTINGS, result_callback=cli_result_callback)
@click.pass_context
@click.option(
    "-V",
    "--version",
    is_flag=True,
    callback=print_version,
    expose_value=False,
    is_eager=True,
)
@click.option("-r", "--release", help="z-stream release version")
@click.option("-v", "--debug", help="enable debug logging", is_flag=True, default=False)
def cli(ctx, release, debug):
    util.init_logging(logging.DEBUG if debug else logging.INFO)

    # Setup log capture AFTER init_logging so console handler is already configured
    # This allows logs to be both displayed AND captured for StateBox
    ctx.ensure_object(dict)
    if '_log_buffer' not in ctx.obj:
        # Only setup log capture if not already provided (e.g., by MCP server)
        # Use Click's with_resource() to properly manage context manager lifecycle
        log_capture_cm = capture_logs(thread_safe=False)
        log_buffer = ctx.with_resource(log_capture_cm)
        ctx.obj['_log_buffer'] = log_buffer

    is_help = False
    for k in CONTEXT_SETTINGS["help_option_names"]:
        if k in sys.argv:
            is_help = True
            break
    if not is_help:
        if not release:
            raise click.MissingParameter(
                "-r/--release is required", param_type='option')

        # Validate environment variables before proceeding
        validation_result = ConfigStore.validate_environment()
        if not validation_result['valid']:
            logger.error("Missing required environment variables for OAR CLI:")
            for error in validation_result['errors']:
                logger.error(f"  - {error}")
            logger.error("")
            logger.error("Fix: Add these variables to ~/.bash_profile and run: source ~/.bash_profile")
            sys.exit(1)

        # Log warnings for optional variables
        if validation_result['missing_optional']:
            for var in validation_result['missing_optional']:
                logger.warning(f"Optional environment variable not set: {var}")

        # Check if ConfigStore was already provided (e.g., from MCP server cache)
        ctx.ensure_object(dict)
        if "cs" not in ctx.obj:
            # Create new ConfigStore only if not provided
            cs = ConfigStore(release)
            ctx.obj["cs"] = cs
        else:
            # Use cached ConfigStore from MCP server
            logger.debug(f"Using cached ConfigStore for release {release}")

        # Initialize log capture buffer for result_callback
        # This will be populated by wrapper or MCP server
        ctx.obj.setdefault('captured_logs', '')
        ctx.obj.setdefault('skip_statebox_update', False)

# TODO remove eliminated commands
cli.add_command(create_test_report)
cli.add_command(take_ownership)
cli.add_command(image_consistency_check)
cli.add_command(check_cve_tracker_bug)
cli.add_command(push_to_cdn_staging)
cli.add_command(stage_testing)
cli.add_command(image_signed_check)
cli.add_command(change_advisory_status)

