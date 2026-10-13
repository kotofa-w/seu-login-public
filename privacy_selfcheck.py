"""Offline checks for credential-safe login results and logs."""
import ast
import base64
import io
import json
import logging
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import quote

import requests
import seu_login as app


def main():
    for path in Path(__file__).parent.glob('*.py'):
        ast.parse(path.read_text(encoding='utf-8'))
    username, password = 'synthetic-user', 'Synthetic+/&=Password'
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    app.logger.handlers = [handler]
    app.logger.setLevel(logging.DEBUG)
    client = app.SEULogin(username, password, 'unicom')
    client.wlan_user_ip = '192.0.2.10'
    leak = f'user_account={username}&user_password={quote(password, safe="")}'
    config = {'username': username, 'password': password, 'isp': 'unicom'}
    for status, attempts in ((app.OK, 0), (app.ERR_NETWORK, 1), (app.ERR_OTHER, 0)):
        with patch.object(app, 'create_client', return_value=client), patch.object(client, 'query_status', return_value=(status, 'simulated')), patch.object(app, 'run_login', return_value=app.OK) as login:
            app.automatic_login_check(config)
            assert login.call_count == attempts
    with patch.object(app, 'create_client') as create:
        app.automatic_login_check({**config, 'auto_login': False})
        create.assert_not_called()
    for result, expected in ((1, app.OK), (0, app.ERR_NETWORK), ('unknown', app.ERR_OTHER)):
        response = SimpleNamespace(text='dr1003(' + json.dumps({'result': result}) + ')')
        with patch.object(client.session, 'get', return_value=response) as get:
            assert client.query_status()[0] == expected
            assert get.call_args.args[0] == 'https://w.seu.edu.cn/drcom/chkstatus'
    campus = app.SEULogin(username, password, 'campus')
    campus_requests = []
    def campus_get(url, **kwargs):
        campus_requests.append((url, kwargs))
        if kwargs.get('params', {}).get('a') == 'login':
            return SimpleNamespace(status_code=200, text='dr1003({"result":"1"})')
        if url == app.CONNECTIVITY_CHECK_URL:
            return SimpleNamespace(status_code=200, url='https://w.seu.edu.cn/a79.htm?wlanuserip=192.0.2.20&wlanacip=192.0.2.1&wlanacname=ExampleAC', text='')
        return SimpleNamespace(status_code=200, url=url, text="ss5='192.0.2.20';")
    with patch.object(campus.session, 'get', side_effect=campus_get):
        assert campus.login()[0] == app.OK
    login_url, login_kwargs = campus_requests[-1]
    assert login_url == 'https://w.seu.edu.cn:802/eportal/'
    assert login_kwargs['params']['wlan_ac_ip'] == '192.0.2.1'
    assert login_kwargs['params']['wlan_ac_name'] == 'ExampleAC'
    assert login_kwargs['params']['user_account'] == ',1,' + username
    assert login_kwargs['params']['jsVersion'] == '3.3.3'
    fallback_requests = []
    def fallback_get(url, **kwargs):
        fallback_requests.append((url, kwargs))
        if kwargs.get('params', {}).get('a') == 'login':
            return SimpleNamespace(status_code=200, text='dr1003({"result":"1"})')
        return SimpleNamespace(status_code=200, url=app.PORTAL_PAGE_URL, text="<!--Dr.COMWebLoginID_0.htm-->\nss5='192.0.2.20';")
    with patch.object(campus.session, 'get', side_effect=fallback_get):
        assert campus.login()[0] == app.OK
    assert fallback_requests[-1][1]['params']['wlan_ac_ip'] == '10.80.175.1'
    assert fallback_requests[-1][1]['params']['wlan_ac_name'] == ''
    with patch.object(campus.session, 'get', return_value=SimpleNamespace(status_code=200, url=app.PORTAL_PAGE_URL, text="ss5='192.0.2.20';")) as get:
        assert campus.login()[0] == app.ERR_NETWORK
        assert not any(call.kwargs.get('params', {}).get('a') == 'login' for call in get.call_args_list)
    with patch.object(campus.session, 'get', return_value=SimpleNamespace(status_code=204, url=app.CONNECTIVITY_CHECK_URL, text='')) as get:
        assert campus.login()[0] == app.OK
        assert get.call_count == 1
    missing_ip = SimpleNamespace(status_code=200, url=app.PORTAL_PAGE_URL + '?wlanacip=192.0.2.1', text='')
    with patch.object(campus.session, 'get', return_value=missing_ip) as get, patch.object(app, '_get_local_ip', return_value='192.0.2.99'):
        assert campus.login()[0] == app.ERR_NETWORK
        assert not any(call.kwargs.get('params', {}).get('a') == 'login' for call in get.call_args_list)
    redirect_url = app.PORTAL_PAGE_URL + '?wlanuserip=192.0.2.20&wlanacip=192.0.2.1&wlanacname=ExampleAC'
    for response in (
        SimpleNamespace(status_code=200, url='http://192.0.2.1/', text='<script>location.href="' + redirect_url.replace('&', '&amp;') + '"</script>'),
        SimpleNamespace(status_code=200, url=app.PORTAL_PAGE_URL, text="<!--Dr.COMWebLoginID_0.htm-->\nss5='192.0.2.20';", history=[SimpleNamespace(url=redirect_url)]),
    ):
        with patch.object(campus.session, 'get', return_value=response):
            assert campus._get_portal_params()
            assert campus.wlan_ac_ip == '192.0.2.1' and campus.wlan_ac_name == 'ExampleAC'
    with patch.object(campus.session, 'get', side_effect=[requests.Timeout(), SimpleNamespace(status_code=200, url=redirect_url, text='')]):
        assert campus._get_portal_params()
    with patch.object(campus.session, 'get', side_effect=requests.ConnectionError('simulated')) as get:
        assert campus.login()[0] == app.ERR_NETWORK
        assert get.call_count == 2
    assert campus.session.trust_env is False
    with patch.object(client, '_get_portal_params', return_value=True), patch.object(client.session, 'get', return_value=SimpleNamespace(status_code=200, text='dr1003({"result":"1"})')) as get:
        assert client.login()[0] == app.OK
        assert get.call_args.args[0] == app.PORTAL_BASE
    for ssid, expected in ((b'SEU-WLAN', 'campus'), (b'SEU-ISP', 'unicom')):
        netsh = SimpleNamespace(returncode=0, stdout=b' BSSID : ignored\r\n SSID : ' + ssid + b'\r\n')
        with patch.object(app.subprocess, 'run', return_value=netsh):
            selected = app.create_client(config)
        assert selected.isp == expected
        assert selected.username == username and selected.password == password
        expected_account = ',1,' + username if expected == 'campus' else ',0,' + username + app.ISP_SUFFIX[expected]
        assert selected._build_login_params()['user_account'] == expected_account
    for stdout in (b'', b'SSID : OtherWiFi\r\n', b'SSID : SEU-WLAN\r\nSSID : SEU-ISP\r\n'):
        with patch.object(app.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout=stdout)):
            with patch.object(app.SEULogin, 'login') as login:
                assert app.run_login(config) == app.ERR_NETWORK
                login.assert_not_called()
    for response in (SimpleNamespace(returncode=5, stdout=b''), app.subprocess.TimeoutExpired('netsh', 10)):
        kwargs = {'side_effect': response} if isinstance(response, Exception) else {'return_value': response}
        with patch.object(app.subprocess, 'run', **kwargs):
            assert app.run_login(config) == app.ERR_NETWORK
    with patch.object(app.subprocess, 'run') as netsh:
        assert app.create_client({**config, 'auto_network': False}).isp == 'unicom'
        netsh.assert_not_called()
    with patch.object(app.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout=b'SSID : SEU-ISP\r\n')):
        assert app.run_login({**config, 'isp': 'campus'}) == app.ERR_NETWORK
    for second, expected_calls in ((b'SEU-ISP', 2), (b'OtherWiFi', 1)):
        observed = []
        def fail_login(self):
            observed.append(self.isp)
            return app.ERR_NETWORK, 'simulated failure'
        readings = [SimpleNamespace(returncode=0, stdout=b'SSID : SEU-WLAN\r\n'), SimpleNamespace(returncode=0, stdout=b'SSID : ' + second + b'\r\n')]
        with patch.object(app.subprocess, 'run', side_effect=readings), patch.object(app.SEULogin, 'login', fail_login), patch.object(app.time, 'sleep'):
            assert app.run_login({**config, 'retry_count': 2, 'silent': True}) == app.ERR_NETWORK
        assert len(observed) == expected_calls
        assert observed == (['campus', 'unicom'] if expected_calls == 2 else ['campus'])
        assert config['isp'] == 'unicom'
    with patch.object(app.subprocess, 'run') as netsh, patch.object(app.SEULogin, 'query_status', return_value=(app.OK, 'Online')), patch.object(app.SEULogin, 'logout', return_value=(app.OK, 'Logout OK')):
        assert app.run_status(config) == app.OK
        assert app.run_logout(config) == app.OK
        netsh.assert_not_called()
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / 'config.ini'
        app.save_config({**config, 'auto_network': False, 'auto_login': False}, path)
        assert app.load_config(path)['auto_network'] is False
        assert app.load_config(path)['auto_login'] is False
        path.write_text('[auth]\nusername = test\npassword = test\nisp = unicom\n', encoding='utf-8')
        assert app.load_config(path)['auto_network'] is True
    with patch.object(client, '_get_portal_params', return_value=True):
        with patch.object(client.session, 'get', side_effect=requests.ConnectionError(leak)):
            code, message = client.login()
            assert code == app.ERR_NETWORK
            assert 'ConnectionError' in message
            output.write(message)
        for result in ('1', 1, '0'):
            for raw in (leak, base64.b64encode(leak.encode()).decode()):
                response = SimpleNamespace(status_code=200, text='dr1003(' + json.dumps({'result': result, 'msg': raw}) + ')')
                with patch.object(client.session, 'get', return_value=response):
                    code, message = client.login()
                    assert code == (app.OK if result in ('1', 1) else app.ERR_AUTH)
                    output.write(message)
        with patch.object(app, '_get_local_ip', return_value=''):
            client.wlan_user_ip = ''
            with patch.object(client.session, 'get') as get:
                assert client.login()[0] == app.ERR_NETWORK
                get.assert_not_called()
    with patch.object(app.socket, 'socket') as sock:
        sock.return_value.connect.side_effect = OSError('unavailable')
        assert app._get_local_ip() == ''
        sock.return_value.close.assert_called_once()
    text = output.getvalue()
    for secret in (username, password, quote(password, safe=''), '192.0.2.10', base64.b64encode(leak.encode()).decode()):
        assert secret not in text, 'Sensitive value reached diagnostic output'
    print('PASS: SSID routing/failure/manual/config, syntax, login, exception privacy, IP failure')


if __name__ == '__main__':
    main()
