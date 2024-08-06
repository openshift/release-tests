import click
import logging
import sys
import oar.core.util as util
from oar import version
from oar.controller.detector import start_release_detector
from oar.core.const import CONTEXT_SETTINGS

logger = logging.getLogger(__name__)


def print_version(ctx, param, value):
    if not value or ctx.resilient_parsing:
        return
    click.echo("oarctl v{}".format(version()))
    click.echo("python v{}".format(sys.version))
    ctx.exit()


@click.group(context_settings=CONTEXT_SETTINGS)
@click.option(
    "-V",
    "--version",
    is_flag=True,
    callback=print_version,
    expose_value=False,
    is_eager=True,
)
@click.option("-v", "--debug", help="enable debug logging", is_flag=True, default=False)
def cli(debug):
    util.init_logging(logging.DEBUG if debug else logging.INFO)


cli.add_command(start_release_detector)

if __name__ == '__main__':
    cli()
