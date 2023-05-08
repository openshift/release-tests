import click
import logging
import oar.core.util as util
from oar.cli.cmd_create_test_report import create_test_report
from oar.core.config_store import ConfigStore, ConfigStoreException

logger = logging.getLogger(__name__)


@click.group()
@click.pass_context
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
