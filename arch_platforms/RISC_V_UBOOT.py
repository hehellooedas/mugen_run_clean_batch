import sys,re
from pathlib import Path,PurePosixPath
from psycopg2.pool import ThreadedConnectionPool
from queue import Queue
import subprocess
import shutil,time,json
import gzip,bz2,lzma,zstandard
import paramiko
from faker import Faker
from psycopg2 import sql
from psycopg2.extras import register_json
from datetime import datetime

from threading import Lock


faker = Faker()

def get_client(ip, password, port=22):
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy)
    try:
        client.connect(hostname=ip, port=port, username="root", password=password, timeout=60)
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
    def __init__(self,**kwargs):
        self.arch = 'RISC-V'        # 当前测试类负责的指令集架构
        self.platform = 'UBOOT'     # 当前测试类负责的系统启动引导平台
        self.suite = kwargs.get('testsuite')             # 当前测试类待测试的mugen测试套名称
        self.case = kwargs.get('testcase')              # 当前测试类待测试的mugen测试名称
        self.vcpu = 2
        self.database_table_name = kwargs.get('database_table_name')
        self.workdir_runtime = kwargs.get('workdir_runtime')
        self.id_queue:Queue = kwargs.get('id_queue')
        self.multi_machine_lock = kwargs.get('multi_machine_lock')
        self.pool:ThreadedConnectionPool = kwargs.get('pgsql_pool')


        self.UBOOT_BIN_NAME: Path = kwargs.get('UBOOT_BIN_NAME')
        self.DRIVE_NAME: Path = Path(kwargs.get('DRIVE_FILE'))
        self.DRIVE_TYPE: Path = kwargs.get('DRIVE_TYPE')

        self.new_machine_lock:Lock = kwargs.get('new_machine_lock')


    def pre_test(self):
        self.machine_id = self.id_queue.get()
        self.workdir = self.workdir_runtime / str(self.machine_id)
        if (self.workdir).exists():
            shutil.rmtree(self.workdir)
        shutil.copytree(self.workdir_runtime / 'default',self.workdir)
        self.ssh_port = self.machine_id + 20000
        self.QEMU_script = f"""
                    qemu-system-riscv64 \
                        -nographic -machine virt \
                        -smp {self.vcpu} -m 4G \
                        -bios {self.workdir / self.UBOOT_BIN_NAME} \
                        -drive if=none,file={self.workdir / self.DRIVE_NAME.with_suffix('')},format={self.DRIVE_TYPE},id=hd0 \
                        -object rng-random,filename=/dev/urandom,id=rng0 \
                        -device virtio-rng-pci,rng=rng0 \
                        -device virtio-blk-pci,drive=hd0 \
                        -netdev tap,id=net0,ifname=tap{self.ssh_port},script=no,downscript=no -device virtio-net-pci,netdev=net0,mac={faker.mac_address()} \
                        -device virtio-net-pci,netdev=usernet,mac={faker.mac_address()} \
                        -netdev user,id=usernet,hostfwd=tcp:127.0.0.1:{self.ssh_port}-:22 \
                        -device qemu-xhci -usb -device usb-kbd
                """

        # 从数据库中取出json描述信息
        conn = self.pool.getconn()
        register_json(conn,loads=json.loads)
        with conn.cursor() as cursor:
            query = sql.SQL("select desc_json from {} where testsuite=%s and testcase=%s").format(sql.Identifier('public',self.database_table_name))
            cursor.execute(query,(self.suite,self.case))
            desc_json = cursor.fetchone()[0]
        self.pool.putconn(conn)



        # 机器类型(kvm/physical)
        self.machine_type = desc_json.get('machine_type','kvm')

        # 额外添加的网卡数量
        self.add_network_interface = desc_json.get('add_network_interface',0)
        if self.add_network_interface != 0 or self.add_network_interface != 1:
            for i in range(self.add_network_interface):
                self.QEMU_script += f" -netdev tap,id=net0,ifname=tap{2+i},script=no,downscript=no -device virtio-net-pci,netdev=net0,mac={faker.mac_address()} "

        # 额外添加的磁盘数量
        self.add_disk = desc_json.get('add_disk',[])
        if self.add_disk != []:
            (self.workdir / 'disks').mkdir(parents=True)    # 创建磁盘所在目录
            for i in range(1,len(self.add_disk)+1):
                subprocess.run(     # 分别创建每一个磁盘
                    args = f"qemu-img create -f qcow2 disk{i}.qcow2 {self.add_disk[i-1]}G",
                    shell=True,cwd=self.workdir / 'disks',
                )
                self.QEMU_script += f" -drive file=disks/disk{i}.qcow2,format=qcow2,id=hd{i},if=none -device virtio-blk-pci,drive=hd{i} "



    def run_test(self):
        # print(self.QEMU_script,self.machine_id,self.ssh_port)
        self.new_machine_lock.acquire()
        try:
            self.QEMU = subprocess.Popen(
                args = self.QEMU_script,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,start_new_session=True,
            )
        except subprocess.CalledProcessError as e:
            print(f"QEMU启动失败.报错信息:{e}")
        time.sleep(60)
        subprocess.run(
            args = f"nc -vz 127.0.0.1 {self.ssh_port}",
            shell=True,
            stdout=subprocess.PIPE,
        )
        time.sleep(120)
        client = get_client('127.0.0.1', 'openEuler12#$', self.ssh_port)
        self.new_machine_lock.release()

        # 记录运行mugen时的时间
        start_time = datetime.now()
        # 开始测mugen
        stdin,stdout,stderr = client.exec_command(
            f"cd /root/mugen && bash mugen.sh -f {self.suite} -r {self.case} -x"
        )
        return_code = stdout.channel.recv_exit_status() # 阻塞

        # 记录mugen运行结束时的时间
        end_time = datetime.now()

        mugen_output = stderr.read().decode('utf-8')
        matches = re.search(r'(\d+)\s+successes\s+(\d+)\s+failures\s+and\s+(\d+)\s+skips', mugen_output)
        if matches:
            check_result = tuple(map(int, matches.groups()))
            print(check_result)
        else:
            check_result = ('NULL','NULL','NULL')

        with client.open_sftp() as sftp:
            log_file_path = f"/root/mugen/logs/{self.suite}/{self.case}/"
            log_file_name = sftp.listdir(log_file_path)[0]
            print(log_file_name)
            if not log_file_name:
                print(f"目录{log_file_path}下没有找到.log文件!!!")
                sys.exit(1)
            print(log_file_path + log_file_name)
            with sftp.open(log_file_path + log_file_name,'r') as log:
                content = log.read().decode('utf-8')
                output_log = content


        self.QEMU.kill()

        failure_reason = '/'

        # 把获取到的信息更新到数据库
        conn = self.pool.getconn()
        with conn.cursor() as cursor:
            updatedb = sql.SQL("""
                               UPDATE {schema_table}
                               SET
                                state = TRUE,
                                start_time = %s,
                                end_time = %s,
                                check_result = %s,
                                output_log = %s,
                                failure_reason = %s
                                WHERE
                                testsuite = %s
                                AND testcase = %s
                               """).format(
                schema_table=sql.Identifier('public', self.database_table_name)
            )
            cursor.execute(updatedb,(
                start_time,
                end_time,
                check_result,
                output_log,
                failure_reason,
                self.suite,
                self.case
            ))
            conn.commit()

        self.pool.putconn(conn)


    def post_test(self):
        # 把任务ID放回资源池,必须先删除工作目录再放回queue
        shutil.rmtree(self.workdir)
        self.id_queue.put(self.machine_id)


    def run_lifecycle(self):
        self.pre_test()
        self.run_test()
        self.post_test()


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
            # 解压缩后删除压缩前的文件以减小磁盘占用
            (default_workdir / DRIVE_NAME).unlink()
        elif compress_format == 'bzip2':
            with bz2.open(default_workdir / DRIVE_NAME,'rb') as fin,open(default_workdir / Path(DRIVE_NAME).with_suffix(''),'wb') as fout:
                shutil.copyfileobj(fin, fout,length=1024*1024*32)
            (default_workdir / DRIVE_NAME).unlink()
        elif compress_format == 'xz':
            with lzma.open(default_workdir / DRIVE_NAME,'rb') as fin,open(default_workdir / Path(DRIVE_NAME).with_suffix(''),'wb') as fout:
                shutil.copyfileobj(fin, fout,length=1024*1024*32)
            (default_workdir / DRIVE_NAME).unlink()
        elif compress_format == 'zstd':
            with zstandard.open(default_workdir / DRIVE_NAME,'rb') as fin,open(default_workdir / Path(DRIVE_NAME).with_suffix(''),'wb') as fout:
                shutil.copyfileobj(fin, fout,length=1024*1024*32)
            (default_workdir / DRIVE_NAME).unlink()
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
                        -device virtio-rng-pci,rng=rng0 \
                        -device virtio-blk-pci,drive=hd0 \
                        -netdev tap,id=net0,ifname=tap0,script=no,downscript=no -device virtio-net-pci,netdev=net0,mac={faker.mac_address()} \
                        -device virtio-net-pci,netdev=usernet,mac={faker.mac_address()} \
                        -netdev user,id=usernet,hostfwd=tcp:127.0.0.1:20000-:22 \
                        -device qemu-xhci -usb -device usb-kbd 
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

        time.sleep(60)
        client: paramiko.SSHClient = get_client('127.0.0.1', 'openEuler12#$', 20000)
        time.sleep(5)
        # copy mugen到镜像内(sftp只能传输文件而不能是目录)
        Path('/root/.ssh/known_hosts',exists_ok=True)
        scp = subprocess.run(
            args = f"export SSHPASS='openEuler12#$' && ssh-keygen -R '[localhost]:20000' && "
                   f"sshpass -e scp -r -P 20000 -o StrictHostKeyChecking=accept-new {mugen_dir} root@localhost:/root/",
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if scp.returncode != 0:
            print(f"传输mugen进虚拟机失败.报错信息:{scp.stderr.decode()}")
            sys.exit(1)

        # 安装必备的rpm包
        stdin,stdout,stderr = client.exec_command(
            'set -e;'
            'dnf install -y git htop python3 && rpm --rebuilddb && dnf update -y && '
            'cd mugen/ && chmod +x dep_install.sh mugen.sh && bash dep_install.sh'
        )
        if stdout.channel.recv_exit_status() != 0:
            print(f"虚拟机中执行mugen初始化环境失败！报错信息:{stderr.read().decode('utf-8')}")

        stdin,stdout,stderr = client.exec_command(
            "systemctl disable --now firewalld && systemctl enable --now sshd"
        )
        if stdout.channel.recv_exit_status() != 0:
            print(f"关闭firewalld防火墙失败或者自启动sshd失败.报错信息:{stderr.read().decode('utf-8')}")

        stdin,stdout,stderr = client.exec_command(
            f"""
                nmcli con add type ethernet con-name net-static ifname enp0s3 ip4 10.0.0.2/24 gw4 10.0.0.254 && 
                nmcli con up net-static && nmcli device status && 
                cd mugen/ && bash mugen.sh -c --ip 10.0.0.2 --password openEuler12#$
            """
        )
        if stdout.channel.recv_exit_status() != 0:
            print(f"tap网络设置错误,或mugen创建conf/env.json失败!报错信息:{stderr.read().decode('utf-8')}")

        with client.open_sftp() as sftp:
            with sftp.open('/root/mugen/conf/env.json','r') as env:
                print(f"env content:{env.read().decode('utf-8')}")


        stdin,stdout,stderr = client.exec_command(
            "systemctl enable --now sshd && poweroff"
        )
        time.sleep(120)
