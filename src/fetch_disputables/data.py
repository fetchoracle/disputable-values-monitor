"""Get and parse NewReport events from Fetch oracles."""
from decimal import *
import asyncio
import math
from dataclasses import dataclass
from enum import Enum
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple
from typing import Union
import time
import os

import eth_abi
from chained_accounts import ChainedAccount
from clamfig.base import Registry
from hexbytes import HexBytes
from telliot_core.apps.telliot_config import TelliotConfig
from telliot_core.contract.contract import Contract
from telliot_core.directory import contract_directory
from telliot_core.model.base import Base
from telliot_feeds.datafeed import DataFeed
from telliot_feeds.datasource import DataSource
from telliot_feeds.feeds import CATALOG_FEEDS
from telliot_feeds.feeds import DATAFEED_BUILDER_MAPPING
from telliot_feeds.queries.abi_query import AbiQuery
from telliot_feeds.queries.json_query import JsonQuery
from telliot_feeds.queries.query import OracleQuery
from telliot_feeds.queries.query_catalog import query_catalog
from web3 import Web3
from web3._utils.events import get_event_data
from web3.exceptions import ExtraDataLengthError
from web3.middleware import geth_poa_middleware
from web3.types import LogReceipt

from fetch_disputables import ALWAYS_ALERT_QUERY_TYPES
from fetch_disputables import NEW_REPORT_ABI, NEW_DISPUTE_ABI
from fetch_disputables.utils import are_all_attributes_none
from fetch_disputables.utils import disputable_str
from fetch_disputables.utils import get_logger
from fetch_disputables.utils import get_tx_explorer_url
from fetch_disputables.utils import NewReport
from fetch_disputables.utils import NewDispute
from fetch_disputables.handle_connect_endpoint import (
    connected_endpoints,
    handle_connect_endpoint,
    get_endpoint
)

from fetch_disputables.utils import Topics

from dotenv import load_dotenv
load_dotenv()

logger = get_logger(__name__)


class Metrics(Enum):
    Percentage = "percentage"
    Equality = "equality"
    Range = "range"

start_block: Dict[int, int] = {}
disputes_start_block: Dict[int, int] = {}
inital_block_offset = int(os.getenv("INITIAL_BLOCK_OFFSET", 0))
chain_reorg = int(os.getenv("CHAIN_REORG", 0))


@dataclass
class Threshold(Base):
    """
    A Threshold for sending a dispute.

    amount (Optional[int]) -- amount of tolerated difference between
    submitted on-chain values and trusted values from telliot.

    metric (Metrics) -- type of threshold

    If self.metric == "percentage", amount is a percent with a minimum of 0
    If self.metric == "equality", amount is None
    If self.metric == "range", amount is the maximum distance an on-chain value can have from
    the trusted value from telliot
    """

    metric: Metrics
    amount: Union[int, float, None]

    def __post_init__(self) -> None:

        if self.metric == Metrics.Equality:
            logger.warning("Equality threshold selected, ignoring amount")
            self.amount = None

        if self.metric != Metrics.Equality:
            if self.amount is None:
                raise ValueError(f"{self.metric} threshold selected, amount cannot be None")

            if self.amount < 0:
                raise ValueError(f"{self.metric} threshold selected, amount cannot be negative")


Reportable = Union[str, bytes, float, int, tuple[Any], None]


@dataclass
class MonitoredFeed(Base):
    feed: DataFeed[Any]
    threshold: Threshold
    trusted_val: Optional[Reportable] = None
    percent_diff: Optional[float] = None
    datafeed_query_tag: Optional[str] = None

    async def is_disputable(
        self,
        cfg: TelliotConfig,
        reported_val: Reportable,
    ) -> Optional[bool]:
        """Check if the reported value is disputable."""
        if reported_val is None:
            logger.error("Need reported value to check disputability")
            return None

        if get_query_type(self.feed.query) == "EVMCall":

            if not isinstance(reported_val, tuple):
                return True

            block_timestamp = reported_val[1]
            reported_val = HexBytes(reported_val[0])
            cfg.main.chain_id = self.feed.query.chainId

            block_number = get_block_number_at_timestamp(cfg, block_timestamp)

            trusted_val, _ = await general_fetch_new_datapoint(self.feed, block_number)
            if not isinstance(trusted_val, tuple):
                logger.warning(f"Bad value response for EVMCall: {trusted_val}")
                return None

            if trusted_val[0] is None:
                logger.warning(f"Unable to fetch trusted value for EVMCall: {trusted_val}")
                return None
            trusted_val = HexBytes(trusted_val[0])
        elif get_query_type(self.feed.query) == "FetchRNG":

            retries = 3
            while retries > 0:
                try:
                    trusted_val, _ = await general_fetch_new_datapoint(self.feed)
                    if trusted_val is None:
                        logger.warning(f"FetchRNG could not build trusted value: {trusted_val}")
                        retries -= 1
                        time.sleep(20)
                    else:
                        retries = 0
                except Exception as e:
                    logger.warning(f"FetchRNG could not build trusted value: {trusted_val} {e}")
                    retries -= 1
                    time.sleep(20)

            if trusted_val is None:
                logger.warning(f"Unable to fetch trusted value for FetchRNG: {trusted_val}")
                return None
        elif get_query_type(self.feed.query) == "FetchRNGCustom":

            if not isinstance(reported_val, tuple):
                return True

            timestamp = reported_val[1]

            if not self.feed.source.is_valid_timestamp(timestamp):
                logger.warning(f"FetchRNGCustom invalid timestamp {timestamp}")
                return True

            self.feed.source.timestamp = timestamp;

            retries = 3
            while retries > 0:
                try:
                    trusted_val, _ = await general_fetch_new_datapoint(self.feed)
                    if trusted_val is None:
                        logger.warning(f"FetchRNGCustom could not build trusted value: {trusted_val}")
                        retries -= 1
                        time.sleep(20)
                    else:
                        retries = 0
                except Exception as e:
                    logger.warning(f"FetchRNGCustom could not build trusted value: {trusted_val} {e}")
                    retries -= 1
                    time.sleep(20)

            if trusted_val is None:
                logger.warning(f"Unable to fetch trusted value for FetchRNGCustom: {trusted_val}")
                return None
        else:
            trusted_val, _ = await general_fetch_new_datapoint(self.feed)

            if trusted_val is None:
                logger.warning(f"trusted val was {trusted_val}")
                return None

        if isinstance(reported_val, (str, bytes, float, int, tuple)) and isinstance(
            trusted_val, (str, bytes, float, int, tuple)
        ):

            if self.threshold.metric == Metrics.Percentage:

                if not trusted_val:
                    logger.warning(
                        f"Telliot val for {self.feed.query} found to be 0. Reported value was {reported_val!r}"
                        "Please double check telliot value before disputing."
                    )
                    return None

                if isinstance(trusted_val, (str, bytes, tuple)) or isinstance(reported_val, (str, bytes, tuple)):
                    logger.error("Cannot evaluate percent difference on text/addresses/bytes")
                    return None
                if self.threshold.amount is None:
                    logger.error("Please set a threshold amount to measure percent difference")
                    return None
                percent_diff: float = (reported_val - trusted_val) / trusted_val
                self.trusted_val = trusted_val
                self.percent_diff = float(abs(percent_diff))
                query_id = self.feed.query.query_id.hex()
                logger.info(f"""
                    Query ID: {query_id}
                    Trusted Value: {trusted_val}
                    Reported Value: {reported_val}
                    Percentage change: {float(abs(percent_diff)) * 100}%
                    Threshold: {self.threshold.amount * 100}%
                    Is percentage change greater than threshold: {float(abs(percent_diff)) >= self.threshold.amount}
                """)
                self.trusted_val = trusted_val
                self.percent_diff = float(abs(percent_diff))
                return float(abs(percent_diff)) >= self.threshold.amount

            elif self.threshold.metric == Metrics.Range:

                if isinstance(trusted_val, (str, bytes, tuple)) or isinstance(reported_val, (str, bytes, tuple)):
                    logger.error("Cannot evaluate range on text/addresses/bytes")

                if self.threshold.amount is None:
                    logger.error("Please set a threshold amount to measure range")
                    return None
                range_: float = abs(reported_val - trusted_val)
                return range_ >= self.threshold.amount

            elif self.threshold.metric == Metrics.Equality:
                logger.debug(f"""
                    Using equality metric with datafeed:
                    DataFeed: {self.feed}
                    Query ID: {self.feed.query.query_id.hex()}
                    Trusted Value: {trusted_val}
                    Reported Value: {reported_val}
                    Trusted Value == Reported Value: {trusted_val == reported_val}
                    Disputable: {trusted_val != reported_val}         
                """)

                # if we have two bytes strings (not raw bytes)
                if (
                    (isinstance(reported_val, str))
                    and (isinstance(trusted_val, str))
                    and reported_val.startswith("0x")
                    and trusted_val.startswith("0x")
                ):
                    return trusted_val.lower() != reported_val.lower()
                return bool(trusted_val != reported_val)

            else:
                logger.error("Attemping comparison with unknown threshold metric")
                return None
        else:
            logger.error(
                f"Unable to compare telliot val {trusted_val!r} of type {type(trusted_val)}"
                f"with reported val {reported_val!r} of type {type(reported_val)} on chain_id {cfg.main.chain_id}"
            )
            return None


async def general_fetch_new_datapoint(feed: DataFeed, *args: Any) -> Optional[Any]:
    """Fetch a new datapoint from a datafeed."""
    return await feed.source.fetch_new_datapoint(*args)


def get_contract_info(chain_id: int, name: str) -> Tuple[Optional[str], Optional[str]]:
    """Get the contract address and ABI for the given chain ID."""

    contracts = contract_directory.find(chain_id=chain_id, name=name)

    if len(contracts) > 0:
        contract_info = contracts[0]
        addr = contract_info.address[chain_id]
        abi = contract_info.get_abi(chain_id=chain_id)
        return addr, abi

    else:
        logger.debug(f"Could not find contract info for contract {name} chain_id {chain_id}")
        return None, None


def get_contract(cfg: TelliotConfig, account: ChainedAccount, name: str) -> Optional[Contract]:
    """Build Contract object from abi and address"""

    chain_id = cfg.main.chain_id
    addr, abi = get_contract_info(chain_id, name)

    if (addr is None) or (abi is None):
        logger.error(f"Could not find contract {name} on chain_id {chain_id}")
        return None
    
    endpoint = get_endpoint(cfg, chain_id)
    if not endpoint:
        logger.error(f"Unable to find a suitable endpoint for chain_id {chain_id}")
        return None

    c = Contract(addr, abi, endpoint, account)

    try:
        connected_to_node = endpoint.connect()
    except (ValueError, ConnectionError) as e:
        logger.error(f"Could not connect to endpoint {endpoint} for chain_id {chain_id}: " + str(e))
        return None

    if not connected_to_node:
        logger.error(f"Could not connect to endpoint {endpoint} for chain_id {chain_id}")
        return None

    status = c.connect()

    if not status.ok:
        logger.error(f"Could not connect to contract {name} on chain_id {chain_id}: " + status.error)
        return None

    return c


def get_query_type(q: OracleQuery) -> str:
    """Get query type from class name"""
    return type(q).__name__


def mk_filter(
    from_block: int, to_block: Union[str, int], addr: str, topics: list[str]
) -> dict[str, Union[int, str, list[str]]]:
    """Create a dict with the given parameters."""
    return {
        "fromBlock": from_block,
        "toBlock": to_block,
        "address": addr,
        "topics": topics,
    }


async def log_loop(web3: Web3, chain_id: int, addr: str, topics: list[str]) -> list[tuple[int, Any]]:
    """Generate a list of recent events from a contract."""
    try:
        block_number = web3.eth.get_block_number()
    except Exception as e:
        if "server rejected" in str(e):
            logger.info(f"Attempted to connect to deprecated infura network. Please check configs! {e}")
        else:
            logger.warning(f"unable to retrieve latest block number from chain_id {chain_id}: {e}")
        return []
    from_block = start_block.get(chain_id, block_number - inital_block_offset)
    from_block -= chain_reorg  # go back CHAIN_REORG more blocks to account for reorgs

    if topics[0] == Topics.NEW_DISPUTE:
        from_block = disputes_start_block.get(chain_id, block_number - inital_block_offset)
        from_block -= chain_reorg
    from_block = max(from_block, 0)
    event_filter = mk_filter(from_block, block_number, addr, topics)

    try:
        events = web3.eth.get_logs(event_filter)  # type: ignore
    except Exception as e:
        msg = str(e)
        if "unknown block" in msg:
            logger.error(f"waiting for new blocks on chain_id {chain_id}")
        elif "request failed or timed out" in msg:
            logger.error(f"request for eth event logs failed on chain_id {chain_id}")
        elif "Too Many Requests" in msg:
            logger.info(f"Too many requests to node on chain_id {chain_id}")
        else:
            logger.error(f"unknown RPC error gathering eth event logs on chain_id {chain_id}\n {msg}")
        return []

    unique_events_list = []
    for event in events:
        if (chain_id, event) not in unique_events_list:
            unique_events_list.append((chain_id, event))
    start_block[chain_id] = block_number
    if topics[0] == Topics.NEW_DISPUTE:
        disputes_start_block[chain_id] = block_number
    return unique_events_list


async def chain_events(
    cfg: TelliotConfig, chain_addy: dict[int, str], topics: list[list[str]]
) -> List[List[tuple[int, Any]]]:
    """"""
    events_loop = []
    for topic in topics:
        for chain_id, address in chain_addy.items():
            try:
                endpoint = get_endpoint(cfg, chain_id)
                if not endpoint: continue
                if endpoint.url.endswith("{INFURA_API_KEY}"):
                    continue
                endpoint.connect()
                w3 = endpoint.web3
            except (IndexError, ValueError) as e:
                logger.error(f"Unable to connect to endpoint on chain_id {chain_id}: {e}")
                continue
            events_loop.append(log_loop(w3, chain_id, address, topic))
    events: List[List[tuple[int, Any]]] = await asyncio.gather(*events_loop)

    return events

async def get_events(cfg: TelliotConfig, contract_name: str, topics: list[str]) -> List[List[tuple[int, Any]]]:
    """Get all events from all live Fetch networks"""

    endpoints = []
    for endpoint in cfg.endpoints.endpoints:
        if endpoint.url.endswith("{INFURA_API_KEY}"): continue

        chain_id = endpoint.chain_id

        handle_connect_endpoint(endpoint, chain_id)

        connected_endpoint = connected_endpoints[chain_id]
        if connected_endpoint is None: continue

        endpoints.append(endpoint)

    log_loops = []
    for endpoint in endpoints:
        w3 = endpoint.web3

        chain_id = endpoint.chain_id

        if not w3: continue

        addr, _ = get_contract_info(chain_id, contract_name)

        if not addr: continue

        log_loops.append(log_loop(w3, chain_id, addr, topics))

    events_lists: List[List[tuple[int, Any]]] = await asyncio.gather(*log_loops)

    return events_lists


def get_query_from_data(query_data: bytes) -> Optional[Union[AbiQuery, JsonQuery]]:
    for q_type in (JsonQuery, AbiQuery):
        try:
            return q_type.get_query_from_data(query_data)
        except ValueError:
            pass
    return None


def get_source_from_data(query_data: bytes) -> Optional[DataSource]:
    """Recreate data source using query type thats decoded from query data field"""
    try:
        query_type, encoded_param_values = eth_abi.decode_abi(["string", "bytes"], query_data)
    except OverflowError:
        logger.error("OverflowError while decoding query data.")
        return None
    try:
        cls = Registry.registry[query_type]
    except KeyError:
        logger.error(f"Unsupported query type: {query_type}")
        return None
    params_abi = cls.abi
    param_names = [p["name"] for p in params_abi]
    param_types = [p["type"] for p in params_abi]
    param_values = eth_abi.decode_abi(param_types, encoded_param_values)

    source = DATAFEED_BUILDER_MAPPING[query_type].source
    for key, value in zip(param_names, param_values):
        setattr(source, key, value)
    return source

async def parse_new_dispute_event(
    cfg: TelliotConfig,
    log: LogReceipt
) -> Optional[NewDispute]:
    chain_id = cfg.main.chain_id
    endpoint = get_endpoint(cfg, chain_id)

    new_dispute = NewDispute()

    if not endpoint:
        logger.error(f"Unable to find a suitable endpoint for chain_id {chain_id}")
        return None
    
    try:
        endpoint.connect()
        w3 = endpoint.web3
    except ValueError as e:
        logger.error(f"Unable to connect to endpoint on chain_id {chain_id}: {e}")
        return None
    
    codec = w3.codec
    event_data = get_event_data(codec, NEW_DISPUTE_ABI, log)

    new_dispute.tx_hash = event_data.transactionHash.hex()
    new_dispute.chain_id = chain_id
    new_dispute.dispute_id = event_data.args._disputeId
    new_dispute.reporter = event_data.args._reporter
    new_dispute.query_id = "0x" + event_data.args._queryId.hex()
    new_dispute.initiator = event_data.args._initiator
    new_dispute.timestamp = event_data.args._timestamp
    new_dispute.startDate = event_data.args._startDate
    new_dispute.voteRound = event_data.args._voteRound
    new_dispute.fee = event_data.args._fee
    new_dispute.voteRoundLength = event_data.args._voteRoundLength
    new_dispute.link = get_tx_explorer_url(tx_hash=new_dispute.tx_hash, cfg=cfg)
    new_dispute.blockNumber = event_data.blockNumber

    return new_dispute

async def parse_new_report_event(
    cfg: TelliotConfig,
    log: LogReceipt,
    confidence_threshold: float,
    monitored_feeds: List[MonitoredFeed],
    managed_feeds,
    displayed_events: set[str],
    see_all_values: bool = False,
    skip_processed_reports: bool = False
) -> Optional[NewReport]:
    """Parse a NewReport event."""

    chain_id = cfg.main.chain_id

    new_report = NewReport()

    endpoint = get_endpoint(cfg, chain_id)

    if not endpoint:
        logger.error(f"Unable to find a suitable endpoint for chain_id {chain_id}")
        return None
    else:

        try:
            endpoint.connect()
            w3 = endpoint.web3
        except ValueError as e:
            logger.error(f"Unable to connect to endpoint on chain_id {chain_id}: {e}")
            return None

        codec = w3.codec
        event_data = get_event_data(codec, NEW_REPORT_ABI, log)

    q = get_query_from_data(event_data.args._queryData)

    if q is None:
        logger.error(f"Unable to form query from queryData of query type {new_report.query_type}")
        return None

    new_report.tx_hash = event_data.transactionHash.hex()
    if skip_processed_reports and new_report.tx_hash in displayed_events: return None
    new_report.chain_id = chain_id
    new_report.query_id = "0x" + event_data.args._queryId.hex()
    new_report.query_type = get_query_type(q)
    new_report.link = get_tx_explorer_url(tx_hash=new_report.tx_hash, cfg=cfg)
    new_report.submission_timestamp = event_data.args._time  # in unix time
    new_report.asset = getattr(q, "asset", "N/A")
    new_report.currency = getattr(q, "currency", "N/A")
    new_report.reporter = event_data.args._reporter
    new_report.contract_address = event_data.address
    new_report.blockNumber = event_data.blockNumber

    try:
        new_report.value = q.value_type.decode(event_data.args._value)
    except eth_abi.exceptions.DecodingError:
        new_report.value = event_data.args._value

    # if query of event matches a query type of the monitored feeds, fill the query parameters

    monitored_feed = None
    query_tag = None

    for mf in monitored_feeds:
        try:
            feed_qid = HexBytes(mf.feed.query.query_id).hex()
        except Exception as e:
            logger.error(f"Error while assembling query id for {mf.feed.query.descriptor}: {e}")
            feed_qid = None

        try:
            feed_qtag = mf.datafeed_query_tag
        except Exception as e:
            logger.error(f"Error while assembling query tag for {mf}: {e}")
            feed_qtag = None

        if feed_qid is None:
            if get_query_type(mf.feed.query) == new_report.query_type:
                # for generic queries the query params are None
                if are_all_attributes_none(mf.feed.query):
                    source = get_source_from_data(event_data.args._queryData)
                    if source is None:
                        logger.error(f"Unable to form source from queryData of query type {new_report.query_type}")
                        return None
                    mf.feed = DataFeed(query=q, source=source)
                    monitored_feed = mf

        if feed_qid == new_report.query_id:
            if new_report.query_type == "SpotPrice":
                catalog_entry = query_catalog.find(query_id=new_report.query_id)
                query_tag = catalog_entry[0].tag if feed_qtag is None else feed_qtag
                mf.feed = CATALOG_FEEDS.get(query_tag)

            else:

                source = get_source_from_data(event_data.args._queryData)

                if source is None:
                    logger.error(f"Unable to form source from queryData of query type {new_report.query_type}")
                    return None

                mf.feed = DataFeed(query=q, source=source)

            monitored_feed = mf

    if new_report.query_type in ALWAYS_ALERT_QUERY_TYPES:
        new_report.status_str = "❗❗❗❗ VERY IMPORTANT DATA SUBMISSION ❗❗❗❗"
        return new_report

    if monitored_feed is not None:
        monitored_query_id = monitored_feed.feed.query.query_id.hex()
    else:
        monitored_query_id = None

    if (new_report.query_id[2:] != monitored_query_id) or (not monitored_feed):

        # build a monitored feed for all feeds not auto-disputing for
        threshold = Threshold(metric=Metrics.Percentage, amount=confidence_threshold)
        catalog = query_catalog.find(query_id=new_report.query_id)
        if catalog:
            query_tag = catalog[0].tag
            feed = CATALOG_FEEDS.get(query_tag)
            if feed is None:
                logger.error(f"Unable to find feed for tag {query_tag}")
                return None
        else:
            # have to check if feed's source supports generic queries and isn't a manual source
            # where a manual input is required
            auto_types = [
                "GasPriceOracle",
                "AmpleforthCustomSpotPrice",
                "AmpleforthUSPCE",
                "MimicryCollectionStat",
                "MimicryNFTMarketIndex",
                "MimicryMacroMarketMashup",
            ]

            if (os.getenv("DISPUTE_RNG_QUERIES", 'False').lower() in ('true', '1', 't')):
                auto_types.append("FetchRNG")

            if new_report.query_type == 'FetchRNG':
                threshold = Threshold(metric=Metrics.Equality, amount=None)

            if new_report.query_type not in auto_types:
                logger.debug(f"Query type {new_report.query_type} doesn't have an auto source to compare value")
                return None
            feed = DataFeed(query=q, source=get_source_from_data(event_data.args._queryData))

        monitored_feed = MonitoredFeed(feed, threshold)

    logger.debug(f"Monitored feed: {managed_feeds.is_managed_feed(new_report.query_id)} - queryId {new_report.query_id} - report_hash={new_report.tx_hash}")
    if managed_feeds.is_managed_feed(new_report.query_id):
        logger.info(f"Found a managed feed report - {new_report.query_id}, report_hash={new_report.tx_hash}")
        new_report.is_managed_feed = True
        new_report.status_str = disputable_str(False, new_report.query_id)
        new_report.disputable = False
        removable = await managed_feeds.is_report_removable(
            monitored_feed, new_report.query_id, cfg, new_report.value
        )
        logger.info(f"Removable: {removable}")
        new_report.removable = removable
        if new_report.removable:
            new_report.status_str = "removable"

        new_report.monitored_feed = {
            "datafeed_querytag": managed_feeds.managed_feeds[new_report.query_id]['datafeed_query_tag'],
            "datafeed_source": monitored_feed.feed.source,
            "trusted_value": monitored_feed.trusted_val,
            "percentage_change": monitored_feed.percent_diff,
            "threshold_amount": monitored_feed.threshold.amount,
            "threshold_metric": monitored_feed.threshold.metric
        }
        
        return new_report

    disputable = await monitored_feed.is_disputable(cfg, new_report.value)
    if disputable is None:

        if see_all_values:

            new_report.status_str = disputable_str(disputable, new_report.query_id)
            new_report.disputable = disputable

            return new_report
        else:
            logger.info(f"unable to check disputability, report hash: {new_report.tx_hash}")
            return None
    else:
        new_report.status_str = disputable_str(disputable, new_report.query_id)
        new_report.disputable = disputable

        new_report.monitored_feed = {
            "datafeed_querytag": query_tag,
            "datafeed_source": monitored_feed.feed.source,
            "trusted_value": monitored_feed.trusted_val,
            "percentage_change": monitored_feed.percent_diff,
            "threshold_amount": monitored_feed.threshold.amount,
            "threshold_metric": monitored_feed.threshold.metric
        }
        return new_report


def get_block_number_at_timestamp(cfg: TelliotConfig, timestamp: int) -> Optional[int]:

    try:
        endpoint = cfg.get_endpoint()
        endpoint.connect()
    except ValueError as e:
        logger.error(f"Unable to connect to endpoint on chain_id {cfg.main.chain_id}: {e}")
        return None

    w3 = endpoint.web3

    current_block = w3.eth.block_number
    start_block = 0
    end_block = current_block

    while start_block <= end_block:
        midpoint = math.floor((start_block + end_block) / 2)
        # for poa chains get_block method throws an error if poa middleware is not injected
        try:
            block = w3.eth.get_block(midpoint)
        except ExtraDataLengthError:
            w3.middleware_onion.inject(geth_poa_middleware, layer=0)
            block = w3.eth.get_block(midpoint)

        if block.timestamp == timestamp:
            return midpoint
        elif block.timestamp < timestamp:
            start_block = midpoint + 1
        else:
            end_block = midpoint - 1

    # If we haven't found an exact match, interpolate between adjacent blocks
    block_a = w3.eth.get_block(end_block)
    block_b = w3.eth.get_block(start_block)

    block_delta = block_b.number - block_a.number
    timestamp_delta = block_b.timestamp - block_a.timestamp
    target_delta = timestamp - block_a.timestamp

    estimated_block_delta = target_delta * block_delta / timestamp_delta
    estimated_block_number = block_a.number + estimated_block_delta

    return int(estimated_block_number)

def get_w3(cfg: TelliotConfig, chain_id: int) -> Optional[Web3]:
    endpoint = get_endpoint(cfg, chain_id)
    if not endpoint:
        logger.error(f"Unable to find a suitable endpoint for chain_id {chain_id}")
        return None
    return endpoint.web3

async def get_fetch_balance(cfg: TelliotConfig, address: str) -> Optional[Decimal]:
    w3 = get_w3(cfg, int(os.getenv("NETWORK_ID", "943")))

    fetch_token = get_contract(cfg, name="fetch-token", account=None)
    fetch_balance, status = await fetch_token.read("balanceOf", Web3.toChecksumAddress(address))

    if not status.ok:
        logger.error(f"Unable to retrieve {address} account balance")
        return None

    fetch_balance = Decimal(w3.fromWei(fetch_balance, 'ether'))
    
    return fetch_balance

async def get_pls_balance(cfg: TelliotConfig, address: str) -> Optional[Decimal]:
    w3 = get_w3(cfg, int(os.getenv("NETWORK_ID", "943")))
    balance_wei = w3.eth.getBalance(address)
    balance = Decimal(w3.fromWei(balance_wei, 'ether'))
    return balance