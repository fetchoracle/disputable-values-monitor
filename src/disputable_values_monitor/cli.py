"""CLI dashboard to display recent values reported to Tellor oracles."""
import logging
import warnings
from time import sleep

from decimal import *
import os

from web3 import Web3

import click
import pandas as pd
from chained_accounts import ChainedAccount
from hexbytes import HexBytes
from telliot_core.apps.telliot_config import TelliotConfig
from telliot_core.cli.utils import async_run

from disputable_values_monitor import WAIT_PERIOD
from disputable_values_monitor.config import AutoDisputerConfig
from disputable_values_monitor.data import chain_events
from disputable_values_monitor.data import get_events
from disputable_values_monitor.data import parse_new_report_event
from disputable_values_monitor.discord import alert
from disputable_values_monitor.discord import dispute_alert
from disputable_values_monitor.discord import generic_alert
from disputable_values_monitor.discord import get_alert_bot_1
from disputable_values_monitor.disputer import dispute
from disputable_values_monitor.utils import clear_console
from disputable_values_monitor.utils import format_values
from disputable_values_monitor.utils import get_logger
from disputable_values_monitor.utils import get_tx_explorer_url
from disputable_values_monitor.utils import select_account
from disputable_values_monitor.utils import Topics

from disputable_values_monitor.data import get_fetch_balance, get_pls_balance
from disputable_values_monitor.utils import get_env_reporters_balance_threshold, get_reporters
from disputable_values_monitor.utils import create_async_task
from disputable_values_monitor.utils import fetch_dashboard
from disputable_values_monitor.discord import token_balance_alert

reporters: list[str] = get_reporters()

def get_reporters_balance_threshold(reporters: list[str], env_variable_name: str):
    reporters_threshold: list[int] = get_env_reporters_balance_threshold(env_variable_name=env_variable_name)
    return {reporter: Decimal(reporter_threshold) for reporter, reporter_threshold in zip(reporters, reporters_threshold)}

ReportersBalance = dict[str, tuple[Decimal, bool]]
ReportersBalanceThreshold = dict[str, Decimal]

reporters_pls_balance: ReportersBalance = dict()
reporters_pls_balance_threshold: ReportersBalanceThreshold = get_reporters_balance_threshold(
    reporters=reporters,
    env_variable_name="REPORTERS_PLS_BALANCE_THRESHOLD"
)

reporters_fetch_balance: ReportersBalance = dict()
reporters_fetch_balance_threshold: ReportersBalanceThreshold = get_reporters_balance_threshold(
    reporters=reporters,
    env_variable_name="REPORTERS_FETCH_BALANCE_THRESHOLD"
)

disputer_balances: dict[str, tuple[Decimal, bool]] = dict()

warnings.simplefilter("ignore", UserWarning)
price_aggregator_logger = logging.getLogger("telliot_feeds.sources.price_aggregator")
price_aggregator_logger.handlers = [
    h for h in price_aggregator_logger.handlers if not isinstance(h, logging.StreamHandler)
]

logger = get_logger(__name__)


def print_title_info() -> None:
    """Prints the title info."""
    click.echo("Disputable Values Monitor 📒🔎📲")


@click.command()
@click.option(
    "-av", "--all-values", is_flag=True, default=False, show_default=True, help="if set, get alerts for all values"
)
@click.option("-a", "--account-name", help="the name of a ChainedAccount to dispute with", type=str)
@click.option("-w", "--wait", help="how long to wait between checks", type=int, default=WAIT_PERIOD)
@click.option("-d", "--is-disputing", help="enable auto-disputing on chain", is_flag=True)
@click.option(
    "-c",
    "--confidence-threshold",
    help="set general confidence percentage threshold for monitoring only",
    type=float,
    default=0.1,
)
@click.option(
    "--initial_block_offset",
    help="the number of blocks to look back when first starting the DVM",
    type=int,
    default=0,
)
@async_run
async def main(
    all_values: bool,
    wait: int,
    account_name: str,
    is_disputing: bool,
    confidence_threshold: float,
    initial_block_offset: int,
) -> None:
    """CLI dashboard to display recent values reported to Tellor oracles."""
    # Raises exception if no webhook url is found
    _ = get_alert_bot_1()
    await start(
        all_values=all_values,
        wait=wait,
        account_name=account_name,
        is_disputing=is_disputing,
        confidence_threshold=confidence_threshold,
        initial_block_offset=initial_block_offset,
    )


async def start(
    all_values: bool,
    wait: int,
    account_name: str,
    is_disputing: bool,
    confidence_threshold: float,
    initial_block_offset: int,
) -> None:
    """Start the CLI dashboard."""
    cfg = TelliotConfig()
    cfg.main.chain_id = int(os.getenv("NETWORK_ID", "943")) #chain_id to select account to dispute
    disp_cfg = AutoDisputerConfig(is_disputing=is_disputing, confidence_flag=confidence_threshold)
    print_title_info()

    if not disp_cfg.monitored_feeds:
        logger.error("No feeds set for monitoring, please add feeds to ./disputer-config.yaml")
        return

    account: ChainedAccount = select_account(cfg, account_name)

    if account and is_disputing:
        click.echo("...you're now auto-disputing!")
    else:
        click.echo("...you're NOT auto-disputing. Use -d if you want to enable auto dispute")

    display_rows = []
    displayed_events = set()

    # Build query if filter is set
    while True:

        # Fetch NewReport events
        event_lists = await get_events(
            cfg=cfg,
            contract_name="tellor360-oracle",
            topics=[Topics.NEW_REPORT],
            inital_block_offset=initial_block_offset,
        )
        tellor_flex_report_events = await get_events(
            cfg=cfg,
            contract_name="tellorflex-oracle",
            topics=[Topics.NEW_REPORT],
            inital_block_offset=initial_block_offset,
        )
        tellor360_events = await chain_events(
            cfg=cfg,
            # addresses are for token contract
            chain_addy={
                #1: "0x88dF592F8eb5D7Bd38bFeF7dEb0fBc02cf3778a0",
                #11155111: "0x80fc34a2f9FfE86F41580F47368289C402DEc660",
            },
            topics=[[Topics.NEW_ORACLE_ADDRESS], [Topics.NEW_PROPOSED_ORACLE_ADDRESS]],
            inital_block_offset=initial_block_offset,
        )
        event_lists += tellor360_events + tellor_flex_report_events

        reporters_pls_balance_task = create_async_task(
            update_reporters_pls_balance,
            cfg,
            reporters,
            reporters_pls_balance
        )
        reporters_pls_balance_task.add_done_callback(
            lambda future_obj: alert_reporters_balance_threshold(
                reporters_balance=reporters_pls_balance,
                reporters_balance_threshold=reporters_pls_balance_threshold,
                asset="PLS"
            )
        )

        reporters_fetch_balance_task = create_async_task(
            update_reporters_fetch_balance,
            cfg,
            reporters,
            reporters_fetch_balance
        )
        reporters_fetch_balance_task.add_done_callback(
            lambda future_obj: alert_reporters_balance_threshold(
                reporters_balance=reporters_fetch_balance,
                reporters_balance_threshold=reporters_fetch_balance_threshold,
                asset="FETCH"
            )
        )

        disputer_balances_task = create_async_task(
            update_disputer_balances,
            telliot_config=cfg,
            disputer_account=account,
            disputer_balances=disputer_balances
        )
        disputer_balances_task.add_done_callback(
            lambda future_obj: alert_on_disputer_balances_threshold(
                disputer_account=account,
                disputer_balances=disputer_balances
            )
        )        
        for event_list in event_lists:
            # event_list = [(80001, EXAMPLE_NEW_REPORT_EVENT)]
            if not event_list:
                continue
            for chain_id, event in event_list:

                cfg.main.chain_id = chain_id
                if (
                    HexBytes(Topics.NEW_ORACLE_ADDRESS) in event.topics
                    or HexBytes(Topics.NEW_PROPOSED_ORACLE_ADDRESS) in event.topics
                ):
                    link = get_tx_explorer_url(cfg=cfg, tx_hash=event.transactionHash.hex())
                    msg = f"\n❗NEW ORACLE ADDRESS ALERT❗\n{link}"
                    generic_alert(msg=msg)
                    continue

                try:
                    new_report = await parse_new_report_event(
                        cfg=cfg,
                        monitored_feeds=disp_cfg.monitored_feeds,
                        log=event,
                        confidence_threshold=confidence_threshold,
                    )
                except Exception as e:
                    logger.error(f"unable to parse new report event on chain_id {chain_id}: {e}")
                    continue

                # Skip duplicate & missing events
                if new_report is None or new_report.tx_hash in displayed_events:
                    continue
                displayed_events.add(new_report.tx_hash)

                # Refesh
                clear_console()
                print_title_info()

                if is_disputing:
                    click.echo("...Now with auto-disputing!")

                alert(all_values, new_report)

                if is_disputing and new_report.disputable:
                    success_msg = await dispute(cfg, disp_cfg, account, new_report)
                    if success_msg:
                        msg = (
                               f"**Value disputed!**\n" 
                               f"Check Fetch Dashboard to vote on it: {fetch_dashboard['vote']}\n"
                               f"{success_msg}\n"
                               f"{new_report.asset}/{new_report.currency}: {new_report.value}"
                           )
                        dispute_alert(msg)

                display_rows.append(
                    (
                        new_report.tx_hash,
                        new_report.submission_timestamp,
                        new_report.link,
                        new_report.query_type,
                        new_report.value,
                        new_report.status_str,
                        new_report.asset,
                        new_report.currency,
                        new_report.chain_id,
                    )
                )

                # Prune display
                if len(display_rows) > 10:
                    # sort by timestamp
                    display_rows = sorted(display_rows, key=lambda x: x[1])
                    displayed_events.remove(display_rows[0][0])
                    del display_rows[0]

                # Display table
                _, times, links, query_type, values, disputable_strs, assets, currencies, chain = zip(*display_rows)

                dataframe_state = dict(
                    When=times,
                    Transaction=links,
                    QueryType=query_type,
                    Asset=assets,
                    Currency=currencies,
                    # split length of characters in the Values' column that overflow when displayed in cli
                    Value=values,
                    Disputable=disputable_strs,
                    ChainId=chain,
                )
                df = pd.DataFrame.from_dict(dataframe_state)
                df = df.sort_values("When")
                df["Value"] = df["Value"].apply(format_values)
                print(df.to_markdown(index=False), end="\r")
                df.to_csv("table.csv", mode="a", header=False)
                # reset config to clear object attributes that were set during loop
                disp_cfg = AutoDisputerConfig(is_disputing=is_disputing, confidence_flag=confidence_threshold)

        sleep(wait)

excluded_addresses = {"0x0000000000000000000000000000000000000000"}
warning_sent = False
async def update_reporters_pls_balance(
    telliot_config: TelliotConfig,
    reporters: list[str],
    reporters_pls_balance: dict[str, tuple[Decimal, bool]],
):
    global warning_sent
    for reporter in reporters:
        if reporter in excluded_addresses:
            if not warning_sent:
                print("Reporters' addresses to monitor token balance not set. Check .env to edit/add them.")
                warning_sent = True
            continue
        balance = await get_pls_balance(telliot_config, reporter)
        old_balance, alert_sent = reporters_pls_balance.get(reporter, (0, False))
        reporters_pls_balance[reporter] = (balance, balance <= reporters_pls_balance_threshold[reporter] and alert_sent)

async def update_reporters_fetch_balance(
    cfg: TelliotConfig,
    reporters: list[str],
    reporters_fetch_balance: dict[str, tuple[Decimal, bool]],
):
    global warning_sent
    for reporter in reporters:
        if reporter in excluded_addresses:
            if not warning_sent:
                warning_sent = True
            continue
        old_fetch_balance, alert_sent = reporters_fetch_balance.get(reporter, (0, False))
        reporter_fetch_balance = await get_fetch_balance(cfg, reporter)
        reporters_fetch_balance[reporter] = (reporter_fetch_balance, reporter_fetch_balance <= reporters_fetch_balance_threshold[reporter] and alert_sent)

def alert_reporters_balance_threshold(
    reporters_balance: ReportersBalance,
    reporters_balance_threshold: ReportersBalanceThreshold,
    asset: str
):
    for reporter, (balance, alert_sent) in reporters_balance.items():
        if balance >= reporters_balance_threshold[reporter]: continue
        if alert_sent: continue

        subject = f"DVM ALERT - Reporter {asset} balance threshold met"
        msg = (
            f"**Reporter's {asset} balance lower than threshold**\n"
            f"Reporter's address: {reporter}\n"
            f"Current {asset} threshold: {reporters_balance_threshold[reporter]:,.2f}\n"
            f"Current {asset} balance: {balance:,.2f}\n"
            f"In network ID: {os.getenv('NETWORK_ID', '943')}"
        )
        token_balance_alert(msg)
        reporters_balance[reporter] = (balance, True)
        
async def update_disputer_balances(
    telliot_config: TelliotConfig,
    disputer_account: ChainedAccount,
    disputer_balances: dict[str, tuple[Decimal, bool]]
):
    if disputer_account is None:
        return
    try:
        disputer_address = Web3.toChecksumAddress(disputer_account.address)
        old_balance_pls, alert_sent_pls = disputer_balances.get('PLS', (0, False))
        disputer_pls_balance = await get_pls_balance(telliot_config, disputer_address)

        disputer_pls_balance_threshold = os.getenv("DISPUTER_PLS_BALANCE_THRESHOLD")
        disputer_fetch_balance_threshold = os.getenv("DISPUTER_FETCH_BALANCE_THRESHOLD")

        disputer_balance_thresholds = {
            'PLS': Decimal(disputer_pls_balance_threshold) if disputer_pls_balance_threshold is not None else None,
            'FETCH': Decimal(disputer_fetch_balance_threshold) if disputer_fetch_balance_threshold is not None else None
        }

        if disputer_balance_thresholds['PLS'] is None:
            logger.warning("DISPUTER_PLS_BALANCE_THRESHOLD environment variable not set, using old balance to check if alert should be sent")
            set_alert_sent_pls = disputer_pls_balance == old_balance_pls and alert_sent_pls
        else:
            set_alert_sent_pls = disputer_pls_balance <= disputer_balance_thresholds['PLS'] and alert_sent_pls

        
        disputer_balances['PLS'] = (disputer_pls_balance, set_alert_sent_pls)

        old_balance_fetch, alert_sent_fetch = disputer_balances.get('FETCH', (0, False))
        disputer_fetch_balance = await get_fetch_balance(telliot_config, disputer_address)

        if disputer_balance_thresholds['FETCH'] is None:
            logger.warning("DISPUTER_FETCH_BALANCE_THRESHOLD environment variable not set, using old balance to check if alert should be sent")
            set_alert_sent_fetch = disputer_fetch_balance == old_balance_fetch and alert_sent_fetch
        else:
            set_alert_sent_fetch = disputer_fetch_balance <= disputer_balance_thresholds['FETCH'] and alert_sent_fetch
        
        disputer_balances['FETCH'] = (disputer_fetch_balance, set_alert_sent_fetch)
    except Exception as e:
        logger.error("Error updating disputer balances")
        logger.error(e)

def alert_on_disputer_balances_threshold(
    disputer_account: ChainedAccount,
    disputer_balances: dict[str, tuple[Decimal, bool]]
):
    if disputer_account is None:
        return
    disputer_pls_balance_threshold = os.getenv("DISPUTER_PLS_BALANCE_THRESHOLD")
    disputer_fetch_balance_threshold = os.getenv("DISPUTER_FETCH_BALANCE_THRESHOLD")

    disputer_balance_thresholds = {
        'PLS': Decimal(disputer_pls_balance_threshold) if disputer_pls_balance_threshold is not None else None,
        'FETCH': Decimal(disputer_fetch_balance_threshold) if disputer_fetch_balance_threshold is not None else None
    }

    if disputer_balance_thresholds['PLS'] is None:
        logger.warning("DISPUTER_PLS_BALANCE_THRESHOLD environment variable not set")
    
    if disputer_balance_thresholds['FETCH'] is None:
        logger.warning("DISPUTER_FETCH_BALANCE_THRESHOLD environment variable not set")

    for asset, (balance, alert_sent) in disputer_balances.items():
        if disputer_balance_thresholds[asset] is None: continue
        if balance >= disputer_balance_thresholds[asset]: continue
        if alert_sent: continue

        subject = f"DVM ALERT ({os.getenv('ENV_NAME', 'default')}) - Disputer {asset} balance threshold met"
        msg = (
            f"**Disputer's {asset} balance lower than threshold**\n"
            f"Disputer's address: {disputer_account.address}\n"
            f"Current {asset} threshold: {disputer_balance_thresholds[asset]:,.2f}\n"
            f"Current {asset} balance: {balance:,.2f}\n"
            f"In network ID: {os.getenv('NETWORK_ID', '943')}"
        )
        token_balance_alert(msg)
        disputer_balances[asset] = (balance, True)

if __name__ == "__main__":
    main()
