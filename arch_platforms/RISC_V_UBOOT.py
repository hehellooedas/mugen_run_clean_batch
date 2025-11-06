import sys
from pathlib import Path,PurePosixPath
from psycopg2.pool import ThreadedConnectionPool
import subprocess
import shutil,time,os
import gzip,bz2,lzma,zstandard,tarfile
import paramiko
from faker import Faker

faker = Faker()

def get_client(ip, password, port=22):
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy)
    try:
        client.connect(hostname=ip, port=port, username="root", password=password, timeout=100)
    except (
            paramiko.ssh_exception.NoValidConnectionsError,
            paramiko.ssh_exception.AuthenticationException,
            paramiko.ssh_exception.SSHException,
            TypeError,
            AttributeError,
    ) as e:
        print(f"无法连接到远程机器:{ip}.\n原因： {e}")
    return client


class RISC_V_UBOOT:
    def __init__(self):
        self.arch = 'RISC-V'        # 当前测试类负责的指令集架构
        self.platform = 'UBOOT'     # 当前测试类负责的系统启动引导平台
        self.suite = ''             # 当前测试类待测试的mugen测试套名称
        self.case = ''              # 当前测试类待测试的mugen测试名称


    @staticmethod
    def make_openEuler_image(**kwargs):
        default_workdir: Path = kwargs.get('default_workdir')
        mugen_dir: Path = kwargs.get('mugen_dir')
        UBOOT_BIN_FILE: Path = kwargs.get('UBOOT_BIN_FILE')
        DRIVE_NAME: Path = Path(kwargs.get('DRIVE_FILE'))
        DRIVE_TYPE: Path = kwargs.get('DRIVE_TYPE')
        compress_format: str = kwargs.get('compress_format')

        UBOOT_BIN_FILE = UBOOT_BIN_FILE.expanduser().resolve(strict=True)
        Path(default_workdir / PurePosixPath(UBOOT_BIN_FILE).name).symlink_to(UBOOT_BIN_FILE)


        if compress_format == 'gzip':
            with gzip.open(default_workdir / DRIVE_NAME,'rb') as fin,open(default_workdir / Path(DRIVE_NAME).with_suffix(''),'wb') as fout:
                shutil.copyfileobj(fin, fout,length=1024*1024*32)
        elif compress_format == 'bzip2':
            with bz2.open(default_workdir / DRIVE_NAME,'rb') as fin,open(default_workdir / Path(DRIVE_NAME).with_suffix(''),'wb') as fout:
                shutil.copyfileobj(fin, fout,length=1024*1024*32)
        elif compress_format == 'xz':
            with lzma.open(default_workdir / DRIVE_NAME,'rb') as fin,open(default_workdir / Path(DRIVE_NAME).with_suffix(''),'wb') as fout:
                shutil.copyfileobj(fin, fout,length=1024*1024*32)
        elif compress_format == 'zstd':
            with zstandard.open(default_workdir / DRIVE_NAME,'rb') as fin,open(default_workdir / Path(DRIVE_NAME).with_suffix(''),'wb') as fout:
                shutil.copyfileobj(fin, fout,length=1024*1024*32)
        else:
            print("未检测到压缩格式，按照无压缩处理...")


        # 启动镜像
        try:
            QEMU = subprocess.Popen(
                args = f"""
                    qemu-system-riscv64 \
                        -nographic -machine virt \
                        -smp 8 -m 4G \
                        -bios {UBOOT_BIN_FILE} \
                        -drive if=none,file={default_workdir / DRIVE_NAME.with_suffix('')},format={DRIVE_TYPE},id=hd0 \
                        -object rng-random,filename=/dev/urandom,id=rng0 \
                        -device virtio-gpu \
                        -device virtio-rng-pci,rng=rng0 \
                        -device virtio-blk-pci,drive=hd0 \
                        -device virtio-net-pci,netdev=usernet,mac={faker.mac_address()} \
                        -netdev user,id=usernet,hostfwd=tcp:127.0.0.1:20000-:22
                """,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=True, start_new_session=True
            )
        except subprocess.CalledProcessError as e:
            print(f"QEMU启动uboot镜像失败.报错信息:{e}")
            sys.exit(1)

        # QEMU启动RISC-V镜像需要较长一段时间
        time.sleep(60)

        subprocess.run(
            args = "nc -vz 127.0.0.1 20000",
            shell=True,
            stdout=subprocess.PIPE,
        )

        time.sleep(120)
        client: paramiko.SSHClient = get_client('127.0.0.1', 'openEuler12#$', 20000)
        time.sleep(5)
        # copy mugen到镜像内(sftp只能传输文件而不能是目录)
        scp = subprocess.run(
            args = f"export SSHPASS='openEuler12#$' && ssh-keygen -R '[localhost]:20000' && "
                   f"sshpass -e scp -r -P 20000 -o StrictHostKeyChecking=accept-new {mugen_dir} root@localhost:/root/",
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if scp.returncode != 0:
            print(f"传输mugen进虚拟机失败.报错信息:{scp.stderr.decode()}")

        # 安装必备的rpm包
        stdin,stdout,stderr = client.exec_command(
            'dnf install -y git htop python3 && '
            'cd mugen/ && chmod +x dep_install.sh mugen.sh && bash dep_install.sh'
        )
        if stdout.channel.recv_exit_status() != 0:
            print(f"虚拟机中执行mugen初始化环境失败！报错信息:{stderr.read().decode('utf-8')}")


        #QEMU.kill()