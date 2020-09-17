# -*- coding: utf-8 -*-

import requests
from requests.cookies import cookiejar_from_dict
import json
from datetime import datetime
from os import SEEK_END
import argparse
import logging
import sys
import urllib3


log = logging.getLogger(__name__)

class KospelSnapshot:
    sessid_filename = '/tmp/.sessid'
    delimiter  = ';'
    temperature_params = ['TEMP_IN', 'TEMP_OUT', 'FACTOR_SETTING', 'TEMP_ROOM', 'TEMP_EXT']
    labels = (
        ('TEMP_IN', 'Temperatura wlotowa'),
        ('TEMP_OUT', 'Temperatura wylotowa'),
        ('FACTOR_SETTING', 'Nastawa czynnika'),
        ('TEMP_ROOM', 'Temperatura pokojowa'),
        ('TEMP_EXT', 'Temperatura zewnętrzna'),
        ('HU_INCLUDED_POWER', 'Moc załączona '),
        ('PRESSURE', 'Ciśnienie'),
        ('FLOW', 'Przepływ'),
        ('FLAG_CH_PUMP_OFF_ON', 'Pompa obiegowa'),
        ('FLAG_IN_NA', 'Wejście NA'),
        ('FLAG_IN_RP', 'Wejście RP'),
        ('FLAG_IN_FUN', 'Wejście FUN'),
    )

    def __init__(self, username, password, filename=None):
        self.username = username
        self.password = password
        self.filename = filename
        self.session = requests.Session()
        sessid = self._get_sessid()
        if sessid:
            self.session.cookies = cookiejar_from_dict({'KOSPELSESSID': sessid})
        self.session.headers.update({
            'X-Requested-With': 'XMLHttpRequest',
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/84.0.4147.125 Safari/537.36',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Dest': 'empty',
            'Connection': 'keep-alive',
            'Accept-Language': 'en-GB,en-US;q=0.9,en;q=0.8',
        })

    def run(self):
        payload = self._get_data()
        if not self.filename:
            log.info(payload)
            return

        if int(payload.get('status', 0)) != 0:
            log.warning(payload)
            log.info('Cannot connect to the API. Re-logging')
            self._login()
            payload = self._get_data()

        if not payload.get('regs'):
            log.warning(payload)
            return
        new_values = self._format_payload(payload)
        prev_values = self._get_prev_values()
        if any(new_values) and new_values != prev_values:
            log.debug('Storing %s', new_values)
            self._store_values(new_values)
        else:
            log.info('Skipping %s', new_values)

    def _get_sessid(self):
        try:
            with open(self.sessid_filename, 'r') as fh:
                log.debug('Getting sessid from file')
                return fh.read().strip()
        except IOError:
            log.debug('Sessid file not found')
            return None

    def _set_sessid(self):
        sessid = self.session.cookies.get('KOSPELSESSID')
        if sessid:
            with open(self.sessid_filename, 'w') as fh:
                log.debug('Storing sessid %s in file', sessid)
                fh.write(sessid)

    def _get_prev_values(self):
        try:
            with open(self.filename, 'rb') as fh:
                try:
                    fh.seek(-128, SEEK_END)
                except OSError:
                    fh.seek(0)
                values = []
                last_line = fh.readlines()[-1].decode("utf-8").strip().replace(',', '.')
                for value in last_line.split(self.delimiter)[1:]:
                    try:
                        values.append(int(value))
                    except ValueError:
                        values.append(float(value))
                return values
        except (IOError, ValueError):
            return []

    def _format_payload(self, payload):
        values = []
        for key, label in self.labels:
            value = payload['regs'][key]
            if key in self.temperature_params:
                values.append(self._format_float(value))
            else:
                values.append(int(value))
        return values

    def _format_float(self, value):
        value = str(value)
        return float('{}.{}'.format(value[0:-1], value[-1]))

    def _store_values(self, values):
        with open(self.filename, 'a') as fh:
            now = datetime.strftime(datetime.now(), '%Y-%m-%d %H:%M:%S')
            values.insert(0, now)
            fh.write(self.delimiter.join([str(i) for i in values]).replace('.', ',') + '\n')

    def _login(self):
        self._dologin()
        self._seldev()
        self._api1()
        self._read()
        self._select_module()
        self._session_device()

    def _get_data(self):
        headers = {
            'Accept': 'application/vnd.kospel.cmi-v1+json',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'Origin': 'https://ha.kospel.pl',
            'Referer': 'https://ha.kospel.pl/ekd'
        }
        data = '["{}"]'.format('","'.join([i[0] for i in self.labels]))
        resp = self.session.post('https://ha.kospel.pl/api/ekd/read/101', headers=headers, data=data)
        return resp.json()

    def _dologin(self):
        headers = {
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'Content-Type': 'application/json; charset=UTF-8',
            'Origin': 'https://ha.kospel.pl',
            'Referer': 'https://ha.kospel.pl/',
        }
        data = json.dumps({"username":self.username, "password": self.password})
        resp = self.session.post('https://ha.kospel.pl/api/dologin', headers=headers, data=data)
        log.debug(resp.text.strip())
        if resp.ok:
            self._set_sessid()

    def _seldev(self):
        headers = {
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'Content-Type': 'application/json; charset=UTF-8',
            'Origin': 'https://ha.kospel.pl',
            'Referer': 'https://ha.kospel.pl/mdevs',
        }
        data = '{"dev":"/connectedDevices","devSN":"mi01_00001403"}'
        resp = self.session.post('https://ha.kospel.pl/api/seldev', headers=headers, data=data)
        log.debug(resp.text.strip())

    def _api1(self):
        headers = {
            'Accept': 'application/vnd.kospel.cmi-v1+json',
            'Referer': 'https://ha.kospel.pl/connectedDevices',
        }
        resp = self.session.get('https://ha.kospel.pl/api', headers=headers)
        log.debug(resp.text.strip())

    def _read(self):
        headers = {
            'Accept': 'application/vnd.kospel.cmi-v1+json',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'Origin': 'https://ha.kospel.pl',
            'Referer': 'https://ha.kospel.pl/connectedDevices',
        }
        data = '["CMI__NAME"]'
        resp = self.session.post('https://ha.kospel.pl/api/cmi/read/254', headers=headers, data=data)
        log.debug(resp.text.strip())

    def _select_module(self):
        headers = {
            'Accept': '*/*',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'Origin': 'https://ha.kospel.pl',
            'Referer': 'https://ha.kospel.pl/connectedDevices',
        }
        data = {
            'id': '101',
            'devType': '19'
        }

        resp = self.session.post('https://ha.kospel.pl/api/selectModule', headers=headers, data=data)
        log.debug(resp.text.strip())

    def _session_device(self):
        headers = {
            'Accept': 'application/vnd.kospel.cmi-v1+json',
            'Referer': 'https://ha.kospel.pl/ekd',
        }
        resp = self.session.get('https://ha.kospel.pl/api/sessionDevice', headers=headers)
        log.debug(resp.text.strip())



if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-u', '--username', required=True)
    parser.add_argument('-p', '--password', required=True)
    parser.add_argument('-o', '--outfile', required=False)
    parser.add_argument('-v', '--verbose', action='count', default=0)
    args = parser.parse_args()

    logging.basicConfig(
        stream=sys.stdout,
        level={0: logging.WARNING, 1: logging.INFO, 2: logging.DEBUG}.get(args.verbose, logging.DEBUG),
        format='%(asctime)s %(levelname)s: %(message)s')
    logging.getLogger('urllib3').setLevel(logging.CRITICAL)

    service = KospelSnapshot(username=args.username, password=args.password, filename=args.outfile)
    service.run()

