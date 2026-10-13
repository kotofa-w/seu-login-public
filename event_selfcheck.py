"""Offline checks: event mode terminates and uses the existing login gate."""
from unittest.mock import patch
import seu_login as app


def main():
    config = {"auto_login": False, "auto_network": False, "isp": "unicom"}
    for result in (app.OK, app.ERR_AUTH, app.ERR_CONFIG):
        with patch.object(app, 'automatic_login_check', return_value=result) as check, patch.object(app.time, 'sleep') as sleep:
            assert app.network_connect_login(config) == result
            assert check.call_count == 1
            assert check.call_args.args[0]['auto_login'] is True
            assert check.call_args.args[0]['auto_network'] is True
            assert check.call_args.args[0]['retry_count'] == 1
            sleep.assert_not_called()
    with patch.object(app, 'automatic_login_check', side_effect=[app.ERR_NETWORK, app.ERR_OTHER, app.OK]) as check, patch.object(app.time, 'sleep') as sleep:
        assert app.network_connect_login(config) == app.OK
        assert check.call_count == 3 and sleep.call_count == 2
    with patch.object(app, 'automatic_login_check', return_value=app.ERR_OTHER) as check, patch.object(app.time, 'sleep'):
        assert app.network_connect_login(config) == app.ERR_OTHER
        assert check.call_count == 3
    assert config['auto_login'] is False and config['auto_network'] is False
    assert app._build_parser().parse_args(['--on-network-connect']).on_network_connect
    print('PASS: bounded event retries, online/rejection/config exit, periodic option independent')


if __name__ == '__main__':
    main()
