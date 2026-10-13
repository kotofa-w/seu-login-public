"""Check that both guardian controls share the persisted auto_login setting."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import tkinter as tk
import seu_login as app
import seu_login_gui as gui


class Widget:
    def __init__(self, *args, **kwargs):
        pass
    def pack(self, *args, **kwargs):
        pass
    def grid(self, *args, **kwargs):
        pass
    def columnconfigure(self, *args, **kwargs):
        pass
    def configure(self, *args, **kwargs):
        pass


def main():
    interpreter = tk.Tcl()
    view = gui.SEULoginApp.__new__(gui.SEULoginApp)
    view.tab_settings = Widget()
    view.var_auto_login = tk.BooleanVar(interpreter, value=False)
    with patch.object(gui.ttk, 'Frame', Widget), patch.object(gui.ttk, 'LabelFrame', Widget), patch.object(gui.ttk, 'Label', Widget), patch.object(gui.ttk, 'Checkbutton', Widget), patch.object(gui.ttk, 'Button', Widget), patch.object(gui.ttk, 'Spinbox', Widget), patch.object(gui.tk, 'BooleanVar', side_effect=lambda **kwargs: tk.Variable(interpreter, value=kwargs.get('value'))), patch.object(gui.tk, 'IntVar', side_effect=lambda **kwargs: tk.Variable(interpreter, value=kwargs.get('value'))):
        view._build_settings_tab()
    assert view.var_daemon is view.var_auto_login
    view.var_event_trigger = tk.BooleanVar(interpreter, value=False)
    view.var_username = tk.StringVar(interpreter, value='synthetic')
    view.var_password = tk.StringVar(interpreter, value='synthetic')
    view.var_auto_network = tk.BooleanVar(interpreter, value=True)
    view._get_isp_key = lambda: 'unicom'
    view.config = {}
    folder = Path(__file__).parent / '_test_config'
    assert folder.is_dir(), 'Create _test_config with PowerShell before this test'
    path = folder / 'guardian.ini'
    try:
        for enabled in (True, False):
            view.var_daemon.set(enabled)
            settings = view._collect_settings()
            assert settings['auto_login'] is enabled
            app.save_config(settings, path)
            view.config = app.load_config(path)
            view.var_auto_login.set(not enabled)
            view.var_isp = tk.StringVar(interpreter)
            view._apply_config()
            assert view.var_daemon.get() is enabled
        view.var_event_trigger.set(True)
        view._select_event_mode()
        assert view.var_daemon.get() is False
        app.save_config(view._collect_settings(), path)
        view.config = app.load_config(path)
        view.var_event_trigger.set(False)
        view._apply_config()
        assert view.var_event_trigger.get() is True and view.var_daemon.get() is False
        view.var_daemon.set(True)
        view._select_guardian_mode()
        assert view.var_event_trigger.get() is False
        view._set_status = lambda message: None
        with patch.object(gui.seu_login, 'save_config'), patch.object(view, '_sync_event_trigger') as sync, patch.object(gui.messagebox, 'showinfo'):
            view._save_settings()
            sync.assert_called_once_with(False)
        view.var_event_trigger.set(True)
        view._select_event_mode()
        with patch.object(gui.seu_login, 'save_config'), patch.object(view, '_sync_event_trigger', side_effect=RuntimeError('simulated')), patch.object(gui.messagebox, 'showerror') as error:
            view._save_settings()
            assert view.var_event_trigger.get() is False
            assert view.var_daemon.get() is True
            error.assert_called_once()
        with patch.object(gui.subprocess, 'run', return_value=type('Result', (), {'returncode': 0})()) as run:
            view._sync_event_trigger(True)
            assert '-Remove' not in run.call_args.args[0]
            view._sync_event_trigger(False)
            assert '-Remove' in run.call_args.args[0]
        view.config['event_trigger'] = True
        view.var_event_trigger.set(False)
        view.var_auto_login.set(True)
        view._closing = False
        view._logging_in = False
        view.root = SimpleNamespace(after=lambda *args: 'timer')
        view.btn_login = Widget()
        with patch.object(gui.threading, 'Thread') as thread:
            view._auto_login_tick()
            thread.assert_not_called()
    finally:
        path.unlink(missing_ok=True)
    print('PASS: saved guardian/event selection, mutual exclusion, task sync and failed-save rollback')


if __name__ == '__main__':
    main()
