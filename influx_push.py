import sys
from datetime import datetime

from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

# You can generate a Token from the "Tokens Tab" in the UI
token = "FphusggCUIJi2NLeq41NP6fStpkzc0AA23DfVHoV9yoU9jhcqhOAK64QaJa4Z5axZfbY_CuXLRFYw5qJddZAEg=="
org = "w17"
bucket = "kospel"

client = InfluxDBClient(url="http://srv08.mikr.us:20344", token=token)

write_api = client.write_api(write_options=SYNCHRONOUS)



def format_lst(lst):
    fields = [
    'TEMP_IN',
    'TEMP_OUT',
    'FACTOR_SETTING',
    'TEMP_ROOM',
    'TEMP_EXT',
    'HU_INCLUDED_POWER',
    'PRESSURE',
    'FLOW',
    'FLAG_CH_PUMP_OFF_ON',
    'FLAG_IN_NA',
    'FLAG_IN_RP',
    'FLAG_IN_FUN']
    values = []
    for i, f in enumerate(fields, 1):
        value = lst[i]
        if ',' in value:
            value = value.replace(',', '.')
        values.append(f'{f}={value}')
    joined_values = ','.join(values)
    ts = int(datetime.strptime(lst[0], '%Y-%m-%d %H:%M:%S').strftime('%s')) * 1000000000
    return f'kospel {joined_values} {ts}'


with open(sys.argv[1]) as fh:
    sequence = []
    for ln in fh.readlines():
        lst = ln.strip().split(';')
        sequence.append(format_lst(lst))
    #for i in sequence: print(i)
    write_api.write(bucket, org, sequence)

