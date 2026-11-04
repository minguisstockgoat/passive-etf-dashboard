import datetime as dt
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from daily_changes import compare, sessions
from collect_daily import valid

def snap(qty=(100,100,100),weight=(40,30,30),price=(4,3,3)):
    return {'asof':'2026-11-03','holdings':[{'code':str(i+1).zfill(6),'name':f'Stock {i}', 'shares':q,'weight':w,'amount':q*p} for i,(q,w,p) in enumerate(zip(qty,weight,price))]}

class Comparisons(unittest.TestCase):
    def test_price_only_does_not_create_rebalancing(self):
        a=snap();b=snap(weight=(50,25,25),price=(6,3,3))
        r=compare(a,b)['summary']
        self.assertEqual(r['in']+r['out']+r['up']+r['down'],0)
    def test_cu_rescale_does_not_create_rebalancing(self):
        self.assertEqual(compare(snap(),snap(qty=(200,200,200)))['summary']['to'],0)
    def test_split_is_separate_from_trading(self):
        r=compare(snap(),snap(qty=(200,100,100),price=(2,3,3)))['summary']
        self.assertEqual(r['ca'],1);self.assertEqual(r['to'],0)
    def test_actual_reallocation_is_detected(self):
        r=compare(snap(),snap(qty=(110,90,100),weight=(44,27,30)))['summary']
        self.assertGreater(r['to'],0);self.assertGreater(r['up'],0);self.assertGreater(r['down'],0)
    def test_code_change_not_entry_exit(self):
        a=snap();b=snap();b['holdings'][0]['code']='999999'
        r=compare(a,b)['summary']
        self.assertEqual(r['recode'],1);self.assertEqual(r['in']+r['out'],0)
    def test_holiday_gap_not_calendar_gap(self):
        with patch('daily_changes.KH.load',return_value={dt.date(2026,11,4)}):
            self.assertEqual(sessions('2026-11-03','2026-11-05'),1)
    def test_stale_source_cannot_replace_newer_snapshot(self):
        current=snap();previous=snap();previous['asof']='2026-11-04'
        self.assertEqual(valid(current,previous,dt.date(2026,11,4)),'source_date_regressed')
    def test_future_or_incomplete_source_rejected(self):
        d=snap();d['asof']='2026-11-05'
        self.assertEqual(valid(d,{},dt.date(2026,11,4)),'future_source_date')
        d=snap(weight=(10,10,10))
        self.assertEqual(valid(d,{},dt.date(2026,11,4)),'incomplete_weights')

if __name__=='__main__':unittest.main()
