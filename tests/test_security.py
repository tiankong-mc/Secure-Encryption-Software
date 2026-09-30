"""Regression tests use real crypto/Flask; only OS DPAPI and network I/O are mocked."""
import base64
import hashlib
import io
import json
import os
import re
import ssl
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import bcrypt
import pyotp
import pyzipper
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

import auth
import crypto
import mail_security
import settings
import storage
import ui_web as web
import updater


class FakeSettings:
    """Windows storage substitute, with actual AES master keys."""
    def __init__(self, root, data=None):
        self.root = str(root)
        self.data = data or {}
        self.key = os.urandom(32)
        self.dpapi = MagicMock()
        self.dpapi.protect.side_effect = lambda data: data
        self.dpapi.unprotect.side_effect = lambda data: data
    def load_settings(self):
        return self.data
    def save_settings(self, data):
        self.data = dict(data)
    def get_master_key(self):
        return self.key
    def get_secret_dir(self):
        return self.root


@pytest.fixture
def manager(tmp_path):
    return auth.AuthManager(FakeSettings(tmp_path))


@pytest.fixture
def web_env(tmp_path, monkeypatch):
    a = auth.AuthManager(FakeSettings(tmp_path))
    # Low bcrypt cost here keeps HTTP tests fast; production setters use defaults.
    a.password_hash = bcrypt.hashpw(b'correct', bcrypt.gensalt(rounds=4)).decode()
    a.settings_dict['password_hash'] = a.password_hash
    a.email_config = {'receiver_email': 'receiver@example.test'}
    a.settings_dict['email'] = a.email_config
    class Files:
        entry = {'id': 'file1', 'original_name': '<script>alert(1)</script>.txt',
                 'is_advanced': True, 'second_auth_methods': ['password', 'email'],
                 'ext': '.txt', 'type': 'text', 'tags': []}
        def get_entry_by_id(self, value):
            return self.entry if value == 'file1' else None
        def get_all_entries(self):
            return [self.entry]
        def get_file_data(self, value):
            return b'<script>secret</script>'
        def log(self, value):
            pass
    files = Files()
    monkeypatch.setattr(web, 'web_auth', a)
    monkeypatch.setattr(web, 'web_storage', files)
    monkeypatch.setattr(web, '_server', None)
    monkeypatch.setattr(web, '_login_rates', {})
    monkeypatch.setattr(web, '_op_rates', {})
    monkeypatch.setattr(web, '_email_rates', {})
    monkeypatch.setattr(web, '_email_codes', {})
    monkeypatch.setattr(web, '_email_global_last_sent', 0)
    web.flask_app.config.update(TESTING=True, SESSION_COOKIE_SECURE=True)
    web.flask_app.secret_key = os.urandom(32)
    return a, files


def token(client):
    response = client.get('/login', base_url='https://localhost')
    assert response.status_code == 200
    return re.search(rb'name="csrf_token" value="([^"]+)"', response.data)[1].decode()


def post(client, path, data=None, csrf=None, **kwargs):
    if csrf is None:
        with client.session_transaction(base_url='https://localhost') as sess:
            csrf = sess['csrf_token']
    payload = {'csrf_token': csrf, **(data or {})}
    return client.post(path, data=payload, base_url='https://localhost', **kwargs)


def login(client):
    t = token(client)
    response = post(client, '/login', {'method': 'password', 'input': 'correct'}, csrf=t)
    assert response.status_code == 302
    client.get('/', base_url='https://localhost')


@pytest.mark.parametrize('corrupt', [b'not json', b'[]', b'null'])
def test_corrupt_config_stops_without_overwriting(tmp_path, corrupt):
    obj = settings.SettingsManager.__new__(settings.SettingsManager)
    obj.CONFIG_PATH = str(tmp_path / 'config.dat')
    obj.MASTER_KEY_PATH = str(tmp_path / 'master.key')
    obj._settings_cache = None
    obj.dpapi = MagicMock()
    obj.dpapi.unprotect.return_value = corrupt
    with open(obj.CONFIG_PATH, 'wb') as f:
        f.write(b'existing')
    with pytest.raises(RuntimeError):
        obj.load_settings()
    assert open(obj.CONFIG_PATH, 'rb').read() == b'existing'
    assert obj._settings_cache is None


def test_missing_config_with_existing_key_stops(tmp_path):
    obj = settings.SettingsManager.__new__(settings.SettingsManager)
    obj.CONFIG_PATH = str(tmp_path / 'absent')
    obj.MASTER_KEY_PATH = str(tmp_path / 'key')
    obj._settings_cache = None
    (tmp_path / 'key').write_bytes(b'key')
    with pytest.raises(RuntimeError):
        obj.load_settings()


def test_atomic_config_write_does_not_follow_predictable_tmp_link(tmp_path):
    victim = tmp_path / 'victim'
    victim.write_bytes(b'keep')
    destination = tmp_path / 'config.dat'
    (tmp_path / 'config.dat.tmp').symlink_to(victim)
    settings.SettingsManager._atomic_write(str(destination), b'safe')
    assert victim.read_bytes() == b'keep'
    assert destination.read_bytes() == b'safe'


@pytest.mark.parametrize('port', [587, 465])
def test_smtp_checks_certificates(monkeypatch, port):
    smtp = MagicMock()
    smtp.__enter__.return_value = smtp
    ctor = MagicMock(return_value=smtp)
    monkeypatch.setattr(mail_security.smtplib, 'SMTP_SSL' if port == 465 else 'SMTP', ctor)
    with mail_security.secure_smtp('mail.example.test', port) as server:
        server.login('user', 'secret')
    context = (ctor.call_args.kwargs['context'] if port == 465
               else smtp.starttls.call_args.kwargs['context'])
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname


def test_smtp_tls_failure_prevents_credentials(monkeypatch):
    smtp = MagicMock()
    smtp.__enter__.return_value = smtp
    smtp.starttls.side_effect = ssl.SSLCertVerificationError('untrusted')
    monkeypatch.setattr(mail_security.smtplib, 'SMTP', MagicMock(return_value=smtp))
    with pytest.raises(ssl.SSLCertVerificationError):
        with mail_security.secure_smtp('mail.example.test', 587) as server:
            server.login('user', 'secret')
    smtp.login.assert_not_called()


def test_bcrypt_long_prefix_and_malformed_hash_fail_closed(manager):
    manager.password_hash = bcrypt.hashpw(b'a' * 72, bcrypt.gensalt(rounds=4)).decode()
    assert manager.verify_password('a' * 72)
    assert not manager.verify_password('a' * 72 + 'different')
    manager.password_hash = 'invalid'
    assert not manager.verify_password('anything')
    with pytest.raises(ValueError):
        manager.set_password('汉' * 25)


def test_totp_consumed_once_including_concurrent_requests(manager):
    manager.save_totp_secret(pyotp.random_base32())
    code = pyotp.TOTP(manager.totp_secret).now()
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(manager.verify_totp, [code] * 4))
    assert results.count(True) == 1
    restored = auth.AuthManager(manager.settings)
    assert not restored.verify_totp(code)


def test_csrf_without_origin_still_rejected(web_env):
    client = web.flask_app.test_client()
    token(client)
    assert client.post('/login', data={'method': 'password', 'input': 'correct'},
                       base_url='https://localhost').status_code == 403
    assert client.post('/send_code', base_url='https://localhost').status_code == 403


def test_cross_origin_post_rejected_even_with_token(web_env):
    client = web.flask_app.test_client()
    t = token(client)
    assert post(client, '/login', {'method': 'password', 'input': 'correct'}, csrf=t,
                headers={'Origin': 'https://attacker.example'}).status_code == 403


@pytest.mark.parametrize('host', ['evil.example', '8.8.8.8'])
def test_dns_rebinding_and_public_host_rejected(web_env, host):
    response = web.flask_app.test_client().get('/login', base_url='https://' + host)
    assert response.status_code == 403


def test_public_client_and_oversized_body_rejected(web_env):
    client = web.flask_app.test_client()
    assert client.get('/login', environ_overrides={'REMOTE_ADDR': '8.8.8.8'},
                      base_url='https://localhost').status_code == 403
    assert client.post('/login', data={'input': 'x' * 20000},
                       base_url='https://localhost').status_code == 413


def test_security_headers_and_no_cached_plaintext(web_env):
    client = web.flask_app.test_client()
    login(client)
    response = client.get('/', base_url='https://localhost')
    assert 'no-store' in response.headers['Cache-Control']
    assert response.headers['X-Frame-Options'] == 'DENY'
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert b'&lt;script&gt;' in response.data
    assert b'<script>alert' not in response.data


def test_advanced_files_require_second_auth_and_grant_expires(web_env):
    client = web.flask_app.test_client()
    login(client)
    for path in ['/view/file1', '/download/file1']:
        assert client.get(path, base_url='https://localhost').status_code == 302
    client.get('/second_auth/file1', base_url='https://localhost')
    assert post(client, '/second_auth/file1', {'method': 'password', 'input': 'correct'}).status_code == 200
    assert client.get('/download/file1', base_url='https://localhost').data == b'<script>secret</script>'
    with client.session_transaction(base_url='https://localhost') as sess:
        record = sess['second_auth']
        record['file1']['expiry'] = time.time() - 1
        sess['second_auth'] = record
    assert client.get('/download/file1', base_url='https://localhost').status_code == 302


def test_relogin_discards_old_second_auth(web_env):
    client = web.flask_app.test_client()
    login(client)
    with client.session_transaction(base_url='https://localhost') as sess:
        sess['second_auth'] = {'file1': {'client': '127.0.0.1', 'expiry': time.time() + 60}}
    login(client)
    assert client.get('/download/file1', base_url='https://localhost').status_code == 302


@pytest.mark.parametrize('reason', ['expiry', 'password_changed', 'client_changed'])
def test_session_expires_and_invalidates_on_security_changes(web_env, reason):
    a, _ = web_env
    client = web.flask_app.test_client()
    login(client)
    kwargs = {}
    if reason == 'expiry':
        with client.session_transaction(base_url='https://localhost') as sess:
            sess['auth_expiry'] = time.time() - 1
    elif reason == 'password_changed':
        a.settings_dict['password_hash'] = 'changed'
    else:
        kwargs['environ_overrides'] = {'REMOTE_ADDR': '192.168.0.2'}
    assert client.get('/', base_url='https://localhost', **kwargs).status_code == 302


def test_email_codes_isolated_by_browser_and_operation(web_env):
    first, second = web.flask_app.test_client(), web.flask_app.test_client()
    for client, sid in [(first, 'browser1'), (second, 'browser2')]:
        token(client)
        with client.session_transaction(base_url='https://localhost') as sess:
            sess['challenge_id'] = sid
    web._store_email_code(('browser1', 'login'), '123456')
    assert post(second, '/login', {'method': 'email', 'input': '123456'}).status_code == 200
    assert post(first, '/login', {'method': 'email', 'input': '123456'}).status_code == 302
    web._store_email_code(('browser1', 'login'), '654321')
    assert not web._email_code_matches(('browser1', 'second_auth:file1'), '654321')
    assert web._email_code_matches(('browser1', 'login'), '654321')
    assert not web._email_code_matches(('browser1', 'login'), '654321')


def test_second_auth_failures_cannot_be_cleared_by_relogin(web_env):
    a, _ = web_env
    client = web.flask_app.test_client()
    login(client)
    for _ in range(5):
        post(client, '/second_auth/file1', {'method': 'password', 'input': 'wrong'})
    assert a.get_op_lock_remaining() > 0
    login(client)
    assert post(client, '/second_auth/file1', {'method': 'password', 'input': 'correct'}).status_code == 429


def test_lockout_shared_across_ip_and_survives_auth_reload(web_env):
    a, _ = web_env
    for i in range(5):
        client = web.flask_app.test_client()
        t = token(client)
        post(client, '/login', {'method': 'password', 'input': 'wrong'}, csrf=t,
             environ_overrides={'REMOTE_ADDR': f'192.168.0.{i+1}'})
    assert a.get_login_lock_remaining() > 0
    assert auth.AuthManager(a.settings).get_login_lock_remaining() > 0
    client = web.flask_app.test_client()
    t = token(client)
    assert post(client, '/login', {'method': 'password', 'input': 'correct'}, csrf=t).status_code == 429


def test_email_recipient_cooldown_not_bypassed_by_new_ip(web_env):
    assert web._reserve_email_send('192.168.0.1') == 0
    assert web._reserve_email_send('192.168.0.2') > 0


def test_https_failure_never_starts_plain_http(web_env, monkeypatch):
    monkeypatch.setattr(web, '_ensure_self_signed_cert', MagicMock(side_effect=RuntimeError('broken')))
    make = MagicMock()
    monkeypatch.setattr(web, 'make_server', make)
    assert not web.start_web_server(web.web_storage, web.web_auth)
    make.assert_not_called()


def test_http_can_only_bind_loopback_and_stop_revokes_sessions(web_env, monkeypatch):
    client = web.flask_app.test_client()
    login(client)
    make = MagicMock()
    monkeypatch.setattr(web, 'make_server', make)
    monkeypatch.setattr(web.threading, 'Thread', MagicMock())
    assert web.start_web_server(web.web_storage, web.web_auth, enable_https=False)
    assert make.call_args.args[0] == '127.0.0.1'
    web.stop_web_server()
    assert client.get('/', base_url='https://localhost').status_code == 302


@pytest.mark.parametrize('name', ['../escape.vault', 'NUL.vault', 'folder/file.vault',
                                   'file.vault:stream', 'CON.vault', 'file.vault.',
                                   'file.vault ', 'x\\escape.vault'])
def test_backup_rejects_windows_and_traversal_paths(name):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as zf:
        zf.writestr('meta.json', '{}')
        zf.writestr('index.enc', b'x')
        zf.writestr(name, b'x')
    with zipfile.ZipFile(buffer) as zf, pytest.raises(ValueError):
        storage.StorageManager._validate_backup_members(zf)


def test_backup_total_and_metadata_limits(monkeypatch):
    infos = [zipfile.ZipInfo('meta.json'), zipfile.ZipInfo('index.enc')]
    infos[0].file_size = storage.MAX_BACKUP_METADATA_BYTES + 1
    infos[0].compress_size = infos[0].file_size
    zf = MagicMock()
    zf.infolist.return_value = infos
    with pytest.raises(ValueError):
        storage.StorageManager._validate_backup_members(zf)
    infos[0].file_size = infos[1].file_size = 6
    infos[1].compress_size = 6
    monkeypatch.setattr(storage, 'MAX_BACKUP_BYTES', 10)
    with pytest.raises(ValueError):
        storage.StorageManager._validate_backup_members(zf)


def test_real_portable_backup_roundtrip_and_wrong_password(tmp_path):
    source_settings = FakeSettings(tmp_path / 'source')
    source = storage.StorageManager(source_settings)
    path = tmp_path / 'plain.txt'
    path.write_bytes(b'confidential test')
    source.add_file(str(path), is_advanced=True, second_auth_methods=['password'])
    backup = tmp_path / 'backup.vaultbk'
    source.export_vault(str(backup), 'backup-password', auth_settings={'password_hash': 'test'})
    destination = storage.StorageManager(FakeSettings(tmp_path / 'dest'))
    result = destination.import_vault(str(backup), 'backup-password')
    assert result['imported_count'] == 1
    entry = destination.index[0]
    assert entry['is_advanced']
    assert destination.get_file_data(entry['id']) == path.read_bytes()
    assert result['auth_settings'] == {'password_hash': 'test'}
    before = list(destination.index)
    with pytest.raises(ValueError):
        destination.import_vault(str(backup), 'incorrect')
    assert destination.index == before


def test_backup_failure_rolls_back_partial_import(tmp_path):
    source = storage.StorageManager(FakeSettings(tmp_path / 'source'))
    path = tmp_path / 'plain.txt'
    path.write_bytes(b'data')
    source.add_file(str(path))
    # A corrupt second record fails after the first file was staged.
    source.index.append({**source.index[0], 'id': str(uuid.uuid4()),
                         'original_name': '\x00bad'})
    backup = tmp_path / 'backup.vaultbk'
    source.export_vault(str(backup), 'backup-password')
    destination = storage.StorageManager(FakeSettings(tmp_path / 'dest'))
    with pytest.raises(ValueError):
        destination.import_vault(str(backup), 'backup-password')
    assert destination.index == []
    assert list((tmp_path / 'dest').glob('*.vault*')) == []


@pytest.mark.parametrize('value', ['bad%PATH%', 'bad!path', 'bad"path', 'bad\npath', 'bad&path'])
def test_updater_rejects_batch_path_injection(tmp_path, value):
    with pytest.raises(updater.UpdateError):
        updater.write_update_bat(str(tmp_path), value, 'target.exe', 'a' * 64)
    assert not list(tmp_path.glob('*.bat'))


def test_updater_requires_hash_and_generates_unique_scripts(tmp_path):
    with pytest.raises(updater.UpdateError):
        updater.write_update_bat(str(tmp_path), 'download.exe', 'target.exe')
    paths = [updater.write_update_bat(str(tmp_path), 'download.exe', 'target.exe', 'a' * 64)
             for _ in range(2)]
    assert paths[0] != paths[1]
    assert 'certutil -hashfile' in open(paths[0]).read()


def test_signature_returns_exact_verified_digest_and_rejects_tampering(tmp_path):
    key = Ed25519PrivateKey.generate()
    pub = base64.b64encode(key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
    path = tmp_path / 'update.exe'
    data = b'genuine publisher binary'
    path.write_bytes(data)
    sig = key.sign(hashlib.sha256(data).digest())
    assert updater.verified_update_sha256(str(path), sig, pub) == hashlib.sha256(data).hexdigest()
    assert updater.verify_update_signature(str(path), sig, pub)
    path.write_bytes(b'tampered')
    assert updater.verified_update_sha256(str(path), sig, pub) is None


def test_aes_gcm_rejects_modified_ciphertext_and_handles_empty_file():
    key = os.urandom(32)
    encrypted = crypto.encrypt_data(b'secret', key)
    with pytest.raises(ValueError):
        crypto.decrypt_data(encrypted[:-1] + bytes([encrypted[-1] ^ 1]), key)
    assert crypto.decrypt_data(crypto.encrypt_data(b'', key), key) == b''


def test_non_ascii_verification_input_is_a_failure_not_a_crash(web_env, manager):
    import auth_helpers
    client = web.flask_app.test_client()
    t = token(client)
    assert post(client, '/login', {'method': 'email', 'input': '你好'}, csrf=t).status_code == 200
    assert post(client, '/login', {'csrf_token': '你好', 'input': 'wrong'}, csrf=t).status_code == 403
    web._store_email_code(('browser', 'login'), '123456')
    assert not web._email_code_matches(('browser', 'login'), '你好')
    assert auth_helpers.verify_email_code('你好', '123456', time.time())[0] == 'fail'
    manager.generate_recovery_code()
    assert not manager.verify_recovery_code('你好')


def test_desktop_second_auth_reopening_keeps_lock_and_never_deletes(manager, monkeypatch):
    from PyQt5.QtWidgets import QApplication, QDialog
    import ui_dialogs
    application = QApplication.instance() or QApplication([])
    manager.password_hash = bcrypt.hashpw(b'correct', bcrypt.gensalt(rounds=4)).decode()
    manager.settings_dict['password_hash'] = manager.password_hash
    files = MagicMock()
    monkeypatch.setattr(ui_dialogs.QMessageBox, 'warning', MagicMock())
    for _ in range(5):
        dialog = ui_dialogs.AuthDialog(None, manager, ['password'], 'file1', files)
        dialog.pw_input.setText('wrong')
        dialog.accept()
        assert dialog.result() != QDialog.Accepted
        dialog.close()
    assert manager.get_op_lock_remaining() > 0
    dialog = ui_dialogs.AuthDialog(None, manager, ['password'], 'file1', files)
    dialog.pw_input.setText('correct')
    dialog.accept()
    assert dialog.result() != QDialog.Accepted
    files.remove_entry.assert_not_called()
    files.get_file_data.assert_not_called()
    dialog.close()
    assert application is not None


def test_cancelled_first_setup_can_restart_without_lost_config_error(tmp_path):
    obj = settings.SettingsManager.__new__(settings.SettingsManager)
    obj.CONFIG_PATH = str(tmp_path / 'config.dat')
    obj.MASTER_KEY_PATH = str(tmp_path / 'master.key')
    obj._settings_cache = None
    obj.dpapi = MagicMock()
    obj.dpapi.protect.side_effect = lambda data: data
    obj.dpapi.unprotect.side_effect = lambda data: data
    key = obj.get_master_key()
    obj._settings_cache = None
    assert obj.load_settings() == {}
    assert obj.get_master_key() == key


def test_recovery_grant_expires_and_code_cannot_be_reused(manager, monkeypatch):
    monkeypatch.setattr(auth.time, 'time', lambda: 1000)
    code = manager.generate_recovery_code()
    assert manager.verify_recovery_code(code)
    assert manager.recovery_verified_until == 1900
    monkeypatch.setattr(auth.time, 'time', lambda: 1100)
    assert not manager.verify_recovery_code(code)
    assert manager.recovery_verified_until == 1900


def test_long_new_password_allowed_and_existing_short_password_still_works(manager):
    manager.set_password('a strong longer passphrase')
    assert manager.verify_password('a strong longer passphrase')
    manager.password_hash = bcrypt.hashpw(b'legacy', bcrypt.gensalt(rounds=4)).decode()
    assert manager.verify_password('legacy')
