"""Real SQL checks use independently supplied literal precision/time oracles."""
from decimal import Decimal
import json
from wealth_ledger.persistence.context import execute
from wealth_ledger.persistence.precision import source_time
from test_postgres_config import PostgresCase,FIXTURES


class PrecisionTests(PostgresCase):
    def test_decimal_admission_matches_independent_literals_in_actual_SQL(self):
        values=json.loads((FIXTURES/'oracles.json').read_text())
        # The fixture's closed format is deliberately inspected rather than inferred.
        rows=values['decimal_cases']
        with self.operator.engine.begin() as conn:
            for row in rows:
                with self.subTest(case=row['id']):
                    actual=execute(conn,'SELECT wl_pg.decimal_token_v1(:token)',token=row['token']).scalar_one()
                    self.assertEqual(actual,row['accepted'])

    def test_NULL_pair_and_finite_value_checks(self):
        with self.operator.engine.begin() as conn:
            for token,number,expected in [(None,None,True),(None,Decimal('0'),False),('0',None,False),
                    ('1.00',Decimal('1'),True),('1',Decimal('2'),False),('0',Decimal('NaN'),False),('0',Decimal('Infinity'),False)]:
                self.assertIs(execute(conn,'SELECT wl_pg.decimal_pair_v1(:token,:number)',token=token,number=number).scalar_one(),expected)

    def test_satoshi_precision_does_not_narrow_to_bigint(self):
        with self.operator.engine.begin() as conn:
            for token,expected in [('0.00000001',True),('-0.00000001',True),('0.000000001',False),('100000000000',True)]:
                self.assertIs(execute(conn,'SELECT wl_pg.quantity_pair_v1(:token,:number,true)',token=token,number=Decimal(token)).scalar_one(),expected)
            self.assertEqual(execute(conn,"SELECT '100000000000'::numeric*100000000").scalar_one(),Decimal('10000000000000000000'))

    def test_date_only_and_native_UTC_overflow_preserve_source_token(self):
        from wealth_ledger.domain.canonical_v1 import DateOnlyV1,InstantV1
        for time in [DateOnlyV1('2026-03-08',None),InstantV1('0001-01-01T00:00:00+23:59',None,0),InstantV1('9999-12-31T23:59:59-23:59',None,0)]:
            row=source_time(time);self.assertIsNone(row['time_utc']);self.assertEqual(row['time_token'],time.token)
