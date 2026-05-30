import paramiko, io, tarfile

NAS_IP = '192.168.31.233'
NAS_USER = 'pcwork'
NAS_PASS = 'Shanghai2025/'
THUMBS = r'C:\Users\jason\Projects\relic-album\thumbs'
REMOTE = '/home/pcwork/nature-album/thumbs'

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(NAS_IP, username=NAS_USER, password=NAS_PASS)

buf = io.BytesIO()
with tarfile.open(fileobj=buf, mode='w:gz') as tar:
    tar.add(THUMBS, arcname='thumbs')
data = buf.getvalue()
print(f'Packed {len(data)//1024} KB')

chan = ssh.get_transport().open_session()
chan.exec_command(f'cd {REMOTE}/.. && tar -xzf -')
chan.sendall(data)
chan.shutdown_write()
chan.recv_exit_status()
print('Extracted on NAS')
ssh.close()
print('Thumbs synced')
