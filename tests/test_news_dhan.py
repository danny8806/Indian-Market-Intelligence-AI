"""Adapter-level regression checks for imported private Sniper Dhan read-only logic."""
import unittest
from datetime import datetime
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import requests
from desk.dhan_data import DhanDataClient
from desk.dhan_instruments import resolve_dhan_symbols

IST=ZoneInfo("Asia/Kolkata")
HEADER=("SEM_EXM_EXCH_ID,SEM_SEGMENT,SEM_SMST_SECURITY_ID,SEM_INSTRUMENT_NAME,"
        "SEM_TRADING_SYMBOL,SEM_SERIES\n")


class InstrumentMappingTests(unittest.TestCase):
    def test_nse_eq_only(self):
        raw=(HEADER+"NSE,E,5900,EQUITY,AXISBANK,EQ\n"
             +"BSE,E,9999,EQUITY,AXISBANK,EQ\n"
             +"NSE,E,8888,EQUITY,AXISBANK,BE\n").encode()
        snap=resolve_dhan_symbols(raw,{"AXISBANK"},datetime(2026,11,4,9,tzinfo=IST))
        self.assertEqual(snap.security_ids,{"AXISBANK":"5900"})

    def test_ambiguous_or_missing_id(self):
        raw=(HEADER+"NSE,E,5900,EQUITY,AXISBANK,EQ\n"
             +"NSE,E,9999,EQUITY,AXISBANK,EQ\n").encode()
        for symbol in ("AXISBANK","HDFCBANK"):
            with self.subTest(symbol=symbol),self.assertRaises(ValueError):
                resolve_dhan_symbols(raw,{symbol},datetime(2026,11,4,9,tzinfo=IST))


class DhanQuoteTests(unittest.TestCase):
    def setUp(self):
        self.session=Mock()
        self.client=DhanDataClient("client","1234","JBSWY3DPEHPK3PXP",session=self.session)
        self.client.token="token"
        self.client._quote_last_call=-10**12

    def test_integer_security_id_ltp(self):
        response=Mock()
        response.json.return_value={"data":{"NSE_EQ":{"1333":{"last_price":692.5}}}}
        self.session.request.return_value=response
        self.assertEqual(self.client.get_ltp({"HDFCBANK":"1333"}),{"HDFCBANK":692.5})
        self.assertEqual(self.session.request.call_args.kwargs["json"],{"NSE_EQ":[1333]})

    def test_integer_security_id_ohlc(self):
        response=Mock()
        response.json.return_value={"data":{"NSE_EQ":{"1333":{
            "last_price":693.0,
            "ohlc":{"open":692.1,"high":694.0,"low":691.0,"close":693.0}}}}}
        self.session.request.return_value=response
        self.assertEqual(self.client.get_ohlc({"HDFCBANK":"1333"})["HDFCBANK"]["open"],692.1)
        self.assertEqual(self.session.request.call_args.kwargs["json"],{"NSE_EQ":[1333]})

    def test_redacted_error(self):
        response=Mock(status_code=400)
        response.raise_for_status.side_effect=requests.HTTPError("bad request")
        response.json.return_value={"remarks":"Invalid request token"}
        self.session.request.return_value=response
        with self.assertRaises(requests.HTTPError) as caught:
            self.client._request("POST","https://api.dhan.co/v2/charts/intraday",json_body={})
        self.assertIn("[redacted]",str(caught.exception))
        self.assertNotIn("token",str(caught.exception))


if __name__=="__main__":
    unittest.main()
