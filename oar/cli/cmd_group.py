import click
import logging
import sys
from oar.cli.cmd_image_consistency_check import image_consistency_check
from oar.cli.cmd_image_signed_check import image_signed_check
from oar.cli.cmd_stage_testing import stage_testing
import oar.core.util as util
from oar import version
from oar.cli.cmd_create_test_report import create_test_report
from oar.cli.cmd_take_ownership import take_ownership
from oar.cli.cmd_update_bug_list import update_bug_list
from oar.cli.cmd_check_greenwave_cvp_tests import check_greenwave_cvp_tests
from oar.cli.cmd_push_to_cdn import push_to_cdn_staging
from oar.cli.cmd_drop_bugs import drop_bugs
from oar.cli.cmd_change_advisory_status import change_advisory_status
from oar.cli.cmd_check_cve_tracker_bug import check_cve_tracker_bug
from oar.core.configstore import ConfigStore, ConfigStoreException
from oar.core.const import CONTEXT_SETTINGS

logger = logging.getLogger(__name__)


def print_version(ctx, param, value):
    if not value or ctx.resilient_parsing:
        return
    click.echo("oar v{}".format(version()))
    click.echo("python v{}".format(sys.version))
    ctx.exit()


@click.group(context_settings=CONTEXT_SETTINGS)
@click.pass_context
@click.option(
    "-V",
    "--version",
    is_flag=True,
    callback=print_version,
    expose_value=False,
    is_eager=True,
)
@click.option("-r", "--release", help="z-stream releaes version")
@click.option("-v", "--debug", help="enable debug logging", is_flag=True, default=False)
def cli(ctx, release, debug):
    util.init_logging(logging.DEBUG if debug else logging.INFO)
    is_help = False
    for k in CONTEXT_SETTINGS["help_option_names"]:
        if k in sys.argv:
            is_help = True
            break
    if not is_help:
        if not release:
            raise click.MissingParameter(
                "-r/--release is required", param_type='option')

        cs = ConfigStore(release)
        ctx.ensure_object(dict)
        ctx.obj["cs"] = cs


cli.add_command(create_test_report)
cli.add_command(take_ownership)
cli.add_command(update_bug_list)
cli.add_command(image_consistency_check)
cli.add_command(check_greenwave_cvp_tests)
cli.add_command(check_cve_tracker_bug)
cli.add_command(push_to_cdn_staging)
cli.add_command(stage_testing)
cli.add_command(image_signed_check)
cli.add_command(drop_bugs)
cli.add_command(change_advisory_status)
