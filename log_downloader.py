"""Download per-node INFO logs over SFTP with a small Windows GUI."""
import configparser
import ctypes
import json
import os
from pathlib import Path
import queue
import re
import stat
import threading
import sys
import base64
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox

# Frozen executables store persistent configuration beside the EXE, outside its temporary bundle.
ROOT = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
REMOTE = '/home/aoting/user_config/glogs'
STAMP = re.compile(r'_info_(\d{8}-\d{6})(?:\.|$)', re.I)
ANY_STAMP = re.compile(r'_(\d{8}-\d{6})(?:\.|$)', re.I)
LEVEL_SUFFIX = re.compile(r'\.(INFO|WARNING|ERROR)$', re.I)


def crypt_password(data, decrypt=False):
    """Call Windows DPAPI and release its allocated output buffer."""
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    result = Blob()
    function = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        ctypes.windll.kernel32.LocalFree(ctypes.cast(result.data, ctypes.c_void_p))


def protect_password(password):
    """Encrypt a password with the current Windows user using DPAPI."""
    if not password:
        return ''
    # Encrypt UTF-8 bytes under the current Windows account.
    return base64.b64encode(crypt_password(password.encode('utf-8'))).decode('ascii')


def unprotect_password(value):
    """Decrypt a DPAPI password; return empty for old or invalid entries."""
    if not value:
        return ''
    try:
        # Decode stored ciphertext and decrypt it using Windows DPAPI.
        return crypt_password(base64.b64decode(value), decrypt=True).decode('utf-8')
    except (ValueError, OSError):
        return ''


def select_log(names, node, target):
    """Return an INFO filename, or last log started before target time."""
    if target is None:
        return next(iter(sorted(name for name in names if name.upper().endswith('.INFO'))), None)
    candidates = []
    for name in names:
        match = STAMP.search(name)
        if match:
            try:
                started = datetime.strptime(match[1], '%Y%m%d-%H%M%S')
            except ValueError:
                continue
            if started <= target:
                candidates.append((started, name))
    return max(candidates)[1] if candidates else None


def select_logs(names, node, target):
    """Return current severity links or one historical file per severity."""
    if target is None:
        # Download current INFO, WARNING and ERROR streams without requiring node-name equality.
        return sorted(name for name in names if LEVEL_SUFFIX.search(name))
    selected = []
    for level in ('INFO', 'WARNING', 'ERROR'):
        candidates = []
        for name in names:
            marker = re.search(r'_(INFO|WARN|WARNING|ERROR)_', name, re.I)
            if not marker:
                continue
            name_level = marker.group(1).upper()
            if name_level == 'WARN':
                name_level = 'WARNING'
            if name_level != level:
                continue
            match = ANY_STAMP.search(name)
            if not match:
                continue
            try:
                started = datetime.strptime(match[1], '%Y%m%d-%H%M%S')
            except ValueError:
                continue
            if started <= target:
                candidates.append((started, name))
        if candidates:
            selected.append(max(candidates)[1])
    return selected


def load_sessions():
    """Read connection fields only; Xftp encrypted passwords are not imported."""
    sessions = {}
    base = Path.home() / 'Documents' / 'NetSarang Computer'
    for file in base.glob('*/Xftp/Sessions/**/*.xfp'):
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        for encoding in ('utf-16', 'utf-8-sig', 'mbcs'):
            try:
                parser.read_string(file.read_text(encoding=encoding))
                connection = parser['Connection']
                if connection.get('Protocol') != '1':
                    break
                sessions['Xftp / ' + file.stem] = {
                    'host': connection['Host'], 'port': connection.get('Port', '22'),
                    'user': connection.get('UserName', 'aoting'), 'password_protected': ''}
                break
            except (UnicodeError, LookupError, configparser.Error, KeyError):
                continue
    if (ROOT / 'machines.json').exists():
        # Saved passwords are DPAPI ciphertext, never plaintext.
        sessions.update(json.loads((ROOT / 'machines.json').read_text('utf-8')))
    return sessions


def desktop_path():
    """Resolve the Windows desktop, including redirected desktop folders."""
    buffer = ctypes.create_unicode_buffer(260)
    if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buffer) != 0:
        raise RuntimeError('无法定位桌面目录')
    return Path(buffer.value)


class App:
    def __init__(self, window):
        """Build controls and keep worker messages off the UI thread."""
        self.window = window
        self.sessions = load_sessions()  # Import Xftp and locally saved connection fields.
        self.events = queue.Queue()
        self.output = None
        window.title('远程节点日志提取')
        window.geometry('680x520')
        self.fields = {}
        frame = ttk.Frame(window, padding=18)
        frame.pack(fill='both', expand=True)
        frame.columnconfigure(1, weight=1)
        for row, (key, title, default) in enumerate([
            ('machine', '机器', ''), ('host', '地址', ''), ('port', '端口', '22'),
            ('user', '用户名', 'aoting'), ('password', '密码', ''),
            ('time', '日志时间', ''), ('remote', '日志目录', REMOTE)]):
            ttk.Label(frame, text=title).grid(row=row, column=0, sticky='w', pady=5)
            variable = tk.StringVar(value=default)
            self.fields[key] = variable
            if key == 'time':
                widget = ttk.Frame(frame)
                self.time_mode = tk.StringVar(value='latest')
                modes = ttk.Frame(widget)
                modes.pack(anchor='w')
                ttk.Radiobutton(modes, text='最新日志', variable=self.time_mode,
                                value='latest', command=self.update_time_mode).pack(side='left')
                ttk.Radiobutton(modes, text='指定时间', variable=self.time_mode,
                                value='specified', command=self.update_time_mode).pack(side='left')
                selectors = ttk.Frame(widget)
                selectors.pack(anchor='w', pady=4)
                now = datetime.now()
                self.time_parts = []
                self.time_controls = []
                for initial, minimum, maximum, label in [
                    (now.year, 1970, 9999, '年'), (now.month, 1, 12, '月'),
                    (now.day, 1, 31, '日'), (now.hour, 0, 23, '时'),
                    (now.minute, 0, 59, '分'), (now.second, 0, 59, '秒')]:
                    part = tk.StringVar(value=str(initial))
                    control = ttk.Spinbox(selectors, from_=minimum, to=maximum,
                                          textvariable=part, width=5 if label == '年' else 3,
                                          wrap=True, state='disabled')
                    control.pack(side='left')
                    ttk.Label(selectors, text=label).pack(side='left', padx=(0, 3))
                    self.time_parts.append(part)
                    self.time_controls.append(control)
            elif key == 'machine':
                self.combo = ttk.Combobox(frame, textvariable=variable, values=list(self.sessions))
                self.combo.bind('<<ComboboxSelected>>', self.choose)
                widget = self.combo
            else:
                widget = ttk.Entry(frame, textvariable=variable, show='*' if key == 'password' else '')
            widget.grid(row=row, column=1, sticky='ew', pady=5)
        self.remember_password = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text='保存密码（本机加密）', variable=self.remember_password).grid(
            row=7, column=1, sticky='w')
        buttons = ttk.Frame(frame)
        buttons.grid(row=8, column=0, columnspan=2, sticky='w', pady=12)
        ttk.Button(buttons, text='保存机器', command=self.save).pack(side='left', padx=4)
        self.download = ttk.Button(buttons, text='下载日志', command=self.start)
        self.download.pack(side='left', padx=4)
        ttk.Button(buttons, text='打开结果文件夹', command=self.open_output).pack(side='left', padx=4)
        self.status = tk.Text(frame, height=10, state='disabled', wrap='word')
        self.status.grid(row=9, column=0, columnspan=2, sticky='nsew')
        frame.rowconfigure(9, weight=1)
        window.after(100, self.poll)  # Drain worker messages safely on Tk's main thread.

    def update_time_mode(self):
        """Enable date and time selectors only for historical extraction."""
        state = 'normal' if self.time_mode.get() == 'specified' else 'disabled'
        for control in self.time_controls:
            control.configure(state=state)

    def choose(self, _event):
        """Populate connection inputs from the selected machine."""
        self.remember_password.set(bool(self.sessions[self.fields['machine'].get()].get('password_protected')))
        for key, value in self.sessions[self.fields['machine'].get()].items():
            if key == 'password_protected':
                self.fields['password'].set(unprotect_password(value))  # Restore this Windows user's encrypted password.
            elif key in self.fields:
                self.fields[key].set(value)
        if 'password_protected' not in self.sessions[self.fields['machine'].get()]:
            self.fields['password'].set('')

    def save(self):
        """Persist machine fields and optionally an encrypted password."""
        name = self.fields['machine'].get().strip()
        if not name or not self.fields['host'].get().strip():
            messagebox.showerror('无法保存', '请填写机器名称和地址')
            return
        file = ROOT / 'machines.json'
        saved = json.loads(file.read_text('utf-8')) if file.exists() else {}
        saved[name] = {key: self.fields[key].get().strip() for key in ('host', 'port', 'user')}
        try:
            # Encrypt the entered password for this Windows account before saving.
            saved[name]['password_protected'] = protect_password(self.fields['password'].get()) if self.remember_password.get() else ''
        except OSError:
            messagebox.showerror('无法保存', '密码加密失败，配置未保存')
            return
        file.write_text(json.dumps(saved, ensure_ascii=False, indent=2), 'utf-8')
        self.sessions[name] = saved[name]
        self.combo['values'] = list(self.sessions)
        messagebox.showinfo('已保存', '机器配置已保存')

    def start(self):
        """Validate inputs before starting one background SFTP download."""
        values = {key: value.get() for key, value in self.fields.items()}
        try:
            # Construct datetime from the selectors; datetime also rejects impossible dates.
            target = datetime(*(int(part.get()) for part in self.time_parts)) if self.time_mode.get() == 'specified' else None
            values['time'] = target.strftime('%Y-%m-%d %H:%M:%S') if target else ''
            port = int(values['port'])
            if not 1 <= port <= 65535 or not values['host'].strip() or not values['user'].strip():
                raise ValueError()
        except ValueError:
            messagebox.showerror('输入有误', '请检查地址、用户名、端口和日期时间（例如月份天数）')
            return
        self.download['state'] = 'disabled'
        threading.Thread(target=self.run, args=(values, port, target), daemon=True).start()

    def run(self, values, port, target):
        """Download each node independently and record missing or failed logs."""
        client = None
        report = []
        try:
            import paramiko
            client = paramiko.SSHClient()
            client.load_system_host_keys()  # Load previously trusted OpenSSH host keys.
            known = ROOT / 'known_hosts'
            if known.exists():
                client.load_host_keys(str(known))  # Reject changed keys for machines used before.
            class ConfirmHost(paramiko.MissingHostKeyPolicy):
                def missing_host_key(policy, ssh, hostname, key):
                    """Ask the UI to approve and persist a first-seen host key."""
                    answer = threading.Event()
                    result = []
                    self.events.put(('trust', (hostname, key, answer, result)))
                    answer.wait()
                    if not result[0]:
                        raise RuntimeError('已取消连接')
                    ssh.get_host_keys().add(hostname, key.get_name(), key)
                    ssh.save_host_keys(str(known))
            client.set_missing_host_key_policy(ConfirmHost())
            self.events.put(('log', '正在连接…'))
            client.connect(values['host'].strip(), port=port, username=values['user'].strip(),
                           password=values['password'], timeout=15, banner_timeout=15,
                           auth_timeout=15, look_for_keys=False, allow_agent=False)
            sftp = client.open_sftp()  # Open the remote file transfer channel.
            sftp.get_channel().settimeout(60)
            remote = values['remote'].rstrip('/')
            nodes = [item.filename for item in sftp.listdir_attr(remote) if stat.S_ISDIR(item.st_mode)]
            label = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', values['machine'] or values['host'])[:60]
            output = desktop_path() / ('日志_' + label + '_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
            output.mkdir()
            self.events.put(('output', output))
            for node in sorted(nodes):
                try:
                    directory = remote + '/' + node
                    names = sftp.listdir(directory)
                    filenames = select_logs(names, node, target)  # Match INFO suffixes or historical timestamps.
                    if not filenames:
                        raise RuntimeError('未找到 INFO/WARNING/ERROR 日志' if target is None else '没有对应时间的日志')
                    for filename in filenames:
                        try:
                            # Preserve the original name; report collisions instead of overwriting another node.
                            if re.search(r'[<>:"/\\|?*\x00-\x1f]', filename) or filename.endswith((' ', '.')):
                                raise RuntimeError('原文件名不适用于 Windows，无法原名保存')
                            destination = output / filename
                            partial = output / (filename + '.part')
                            if destination.exists() or partial.exists():
                                raise RuntimeError('结果目录已存在同名文件，已跳过以防覆盖')
                            sftp.get(directory + '/' + filename, str(partial))  # Follow INFO links and download file contents.
                            partial.replace(destination)  # Publish only completed downloads under the original name.
                            report.append(node + ': 已下载 ' + filename)
                        except Exception as error:
                            report.append(node + ': ' + filename + ': ' + str(error))
                        self.events.put(('log', report[-1]))
                except Exception as error:
                    report.append(node + ': ' + str(error))
                    self.events.put(('log', report[-1]))
            (output / '提取结果.txt').write_text('输入时间: ' + (values['time'] or '最新') + '\n' + '\n'.join(report), 'utf-8')
            self.events.put(('log', '提取结束：' + str(output)))
        except Exception as error:
            self.events.put(('log', '提取失败：' + str(error)))
        finally:
            if client:
                client.close()  # Release the connection even when a node download fails.
            self.events.put(('done', None))

    def poll(self):
        """Display queued progress and first-connection confirmation dialogs."""
        while not self.events.empty():
            kind, value = self.events.get()
            if kind == 'done':
                self.download['state'] = 'normal'
            elif kind == 'output':
                self.output = value
            elif kind == 'trust':
                host, key, event, result = value
                result.append(messagebox.askyesno('首次连接', '信任机器 ' + host + ' 的主机密钥？\n指纹: ' + key.get_fingerprint().hex()))
                event.set()
            else:
                self.status['state'] = 'normal'
                self.status.insert('end', value + '\n')
                self.status.see('end')
                self.status['state'] = 'disabled'
        self.window.after(100, self.poll)  # Continue processing asynchronous download progress.

    def open_output(self):
        """Open the latest extraction directory in Windows Explorer."""
        if self.output:
            os.startfile(self.output)


if __name__ == '__main__':
    window = tk.Tk()
    App(window)  # Initialize the machine selector and download controls.
    window.mainloop()
