"""Tellor Disputables - CLI dashboard & alerts for potential
bad values reported to Tellor oracles."""
from hexbytes import HexBytes
from telliot_feeds import feeds
from web3.datastructures import AttributeDict

ETHEREUM_CHAIN_ID = 1  # Testnet
POLYGON_CHAIN_ID = 80001  # Testnet
CONFIDENCE_THRESHOLD = 0.50

WAIT_PERIOD = 7  # seconds between checks for new events

ALWAYS_ALERT_QUERY_TYPES = ("AutopayAddresses", "TellorOracleAddress")

DATAFEED_LOOKUP = {
    "000000000000000000000000000000000000000000000000000000000000000a": feeds.ampl_usd_vwap_feed,
    "35e083af947a4cf3bc053440c3b4f753433c76acab6c8b1911ee808104b72e85": feeds.bct_usd_feed.bct_usd_median_feed,
    "0000000000000000000000000000000000000000000000000000000000000002": feeds.btc_usd_feed.btc_usd_median_feed,
    "d913406746edf7891a09ffb9b26a12553bbf4d25ecf8e530ec359969fe6a7a9c": feeds.dai_usd_feed.dai_usd_median_feed,
    "000000000000000000000000000000000000000000000000000000000000003b": feeds.eth_jpy_feed.eth_jpy_median_feed,
    "0000000000000000000000000000000000000000000000000000000000000001": feeds.eth_usd_feed.eth_usd_median_feed,
    "7239909c0aa5d3e89efb2dce06c80811e93ab18413110b8c0435ee32c52cc4fb": feeds.idle_usd_feed.idle_usd_median_feed,
    "40aa71e5205fdc7bdb7d65f7ae41daca3820c5d3a8f62357a99eda3aa27244a3": feeds.matic_usd_feed.matic_usd_median_feed,
    "b9d5e25dabd5f0a48f45f5b6b524bac100df05eaf5311f3e5339ac7c3dd0a37e": feeds.mkr_usd_feed.mkr_usd_median_feed,
    "ee4fcdeed773931af0bcd16cfcea5b366682ffbd4994cf78b4f0a6a40b570340": feeds.olympus.ohm_eth_median_feed,
    "0000000000000000000000000000000000000000000000000000000000000032": feeds.trb_usd_feed.trb_usd_median_feed,
    "0000000000000000000000000000000000000000000000000000000000000029": feeds.uspce_feed,
    "2e0aa9e19f5c3e1d3e086b34fe90072b43889382f563e484e8e1e3588b19ef14": feeds.eur_usd_feed.eur_usd_median_feed,
    "8ee44cd434ed5b0e007eee581fbe0855336f3f84484e8d9989a620a4a49aa0f7": feeds.usdc_usd_feed.usdc_usd_median_feed,
    "a9b17c33422e2e576fb664d1d11d38c377b614d62f92653d006eca7bb2af1656": feeds.vesq.vsq_usd_median_feed,
    "6e5122118ce52cc9b97c359c1f174a3c21c71d810f7addce3484cc28e0be0f29": feeds.ric_usd_feed.ric_usd_median_feed,
    "3f640bf607feb4455c3eb10629385d823341cd18fef6f9f87b8bcfbeafc44eeb": feeds.sushi_usd_feed.sushi_usd_median_feed
    # "": feeds.diva_protocol_feed.assemble_diva_datafeed
}


# OHM/ETH SpotPrice
EXAMPLE_NEW_REPORT_EVENT = AttributeDict(
    {
        "address": "0x41b66dd93b03e89D29114a7613A6f9f0d4F40178",
        "blockHash": HexBytes("0x61967b410ac2ef5352e1bc0c06ab63fb84ba9161276a4645aca389fd01409ef7"),
        "blockNumber": 25541322,
        "data": "0xee4fcdeed773931af0bcd16cfcea5b366682ffbd4994cf78b4f0a6a40b570"
        "3400000000000000000000000000000000000000000000000000000000062321"
        "eec0000000000000000000000000000000000000000000000000000000000000"
        "0c000000000000000000000000000000000000000000000000000000000000000"
        "3a000000000000000000000000000000000000000000000000000000000000010"
        "0000000000000000000000000d5f1cc896542c111c7aa7d7fae2c3d654f34b927"
        "00000000000000000000000000000000000000000000000000000000000000200"
        "0000000000000000000000000000000000000000000000000248c37b20efbff000"
        "000000000000000000000000000000000000000000000000000000000016000000"
        "0000000000000000000000000000000000000000000000000000000004000000000"
        "00000000000000000000000000000000000000000000000000000080000000000000"
        "000000000000000000000000000000000000000000000000000953706f7450726963"
        "65000000000000000000000000000000000000000000000000000000000000000000"
        "000000000000000000000000000000000000000000c00000000000000000000000"
        "0000000000000000000000000000000000000000400000000000000000000000000"
        "00000000000000000000000000000000000008000000000000000000000000000000"
        "000000000000000000000000000000000036f686d0000000000000000000000000"
        "0000000000000000000000000000000000000000000000000000000000000000000"
        "000000000000000000000000000003657468000000000000000000000000000000"
        "0000000000000000000000000000",
        "logIndex": 101,
        "removed": False,
        "topics": [HexBytes("0x48e9e2c732ba278de6ac88a3a57a5c5ba13d3d8370e709b3b98333a57876ca95")],
        "transactionHash": HexBytes("0x0b91b05c53c527918615be6914ec087275d80a454a468977409da1634f25cbf4"),
        "transactionIndex": 1,
    }
)

# OHM/ETH SpotPrice
EXAMPLE_NEW_REPORT_EVENT_TX_RECEIPT = (
    AttributeDict(
        {
            "args": AttributeDict(
                {
                    "_queryId": b"\xeeO\xcd\xee\xd7s\x93\x1a\xf0\xbc\xd1l\xfc"
                    b"\xea[6f\x82\xff\xbdI\x94\xcfx\xb4\xf0\xa6\xa4\x0bW\x03@",
                    "_time": 1647451884,
                    "_value": b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00$\x8c7\xb2\x0e\xfb\xff",
                    "_nonce": 58,
                    "_queryData": b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                    b"\x00\x00\x00\x00@\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                    b"\x00\x00\x00\x00\x00\x00\x00\x80\x00\x00\x00\x00\x00\x00"
                    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\tSpotPrice"
                    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xc0\x00"
                    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                    b"\x00\x00@\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                    b"\x00\x00\x00\x00\x00\x80\x00\x00\x00\x00\x00\x00\x00\x00"
                    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x03ohm\x00\x00\x00\x00"
                    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x03eth\x00\x00"
                    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
                    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00",
                    "_reporter": "0xd5f1Cc896542C111c7Aa7D7fae2C3D654f34b927",
                }
            ),
            "event": "NewReport",
            "logIndex": 101,
            "transactionIndex": 1,
            "transactionHash": HexBytes("0x0b91b05c53c527918615be6914ec087275d80a454a468977409da1634f25cbf4"),
            "address": "0x41b66dd93b03e89D29114a7613A6f9f0d4F40178",
            "blockHash": HexBytes("0x61967b410ac2ef5352e1bc0c06ab63fb84ba9161276a4645aca389fd01409ef7"),
            "blockNumber": 25541322,
        }
    ),
)


LEGACY_ASSETS = {
    1: "ETH",
    2: "BTC",
    10: "AMPL",
    50: "TRB",
    59: "ETH",
}


LEGACY_CURRENCIES = {
    1: "USD",
    2: "USD",
    10: "USD",
    50: "USD",
    59: "JPY",
}
