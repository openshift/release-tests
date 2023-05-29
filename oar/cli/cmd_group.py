import click
import logging
import sys
import oar.core.util as util
from oar import version
from oar.cli.cmd_create_test_report import create_test_report
from oar.cli.cmd_take_ownership import take_ownership
from oar.cli.cmd_update_bug_list import update_bug_list
from oar.cli.cmd_check_greenwave_cvp_tests import check_greenwave_cvp_tests
from oar.cli.cmd_push_to_cdn import push_to_cdn_staging
from oar.core.config_store import ConfigStore, ConfigStoreException
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
@click.option("-r", "--release", help="z-stream releaes version", required=True)
@click.option("-v", "--debug", help="enable debug logging", is_flag=True, default=False)
def cli(ctx, release, debug):
    util.init_logging(logging.DEBUG if debug else logging.INFO)
    try:
        cs = ConfigStore(release)
    except ConfigStoreException as cse:
        logger.exception("config store initialization failed")

    ctx.ensure_object(dict)
    ctx.obj["cs"] = cs


cli.add_command(create_test_report)
cli.add_command(take_ownership)
cli.add_command(update_bug_list)
cli.add_command(check_greenwave_cvp_tests)
cli.add_command(push_to_cdn_staging)
