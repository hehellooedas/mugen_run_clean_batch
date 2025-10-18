#! /usr/bin/env python3
# encoding: utf-8

"""
    在mrcb脚本运行前运行该脚本初始化环境和安装必要rpm包/Python第三方库
    以确保mrcb运行正常,简化用户操作
"""
import shutil
import subprocess
import sys,os
import platform
import time
from pathlib import Path



def close_selinux():
    shutil.copy2(src=Path('resources/selinux.conf'),dst=Path('/etc/selinux/config'))
    os.chmod(Path('/etc/selinux/config'),mode=0o644)
    subprocess.run(
        "setenforce 0",
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def flash_time():
    try:
        subprocess.run(
            "dnf install -y chrony",
            shell=True,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        with open(Path('/etc/chrony.conf'),'w') as f:
            f.write(
                """
                    pool pool.ntp.org iburst
                    server time.cloudflare.com iburst
                    server time.google.com iburst
                    makestep 1.0 3
                    rtcsync
                    logdir /var/log/chrony
                """
            )
        chrony = subprocess.run(
            "systemctl enable --now chronyd && chronyc sources -v",
            shell=True,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        print(f"mrcb准备:chrony信息{chrony.stdout.decode()}")
    except subprocess.CalledProcessError as e:
        print(f"mrcb准备:刷新时间失败.报错信息:{e.stderr.decode()}")
        sys.exit(1)


def check_arch():
    if platform.machine() != 'x86_64':
        print(f"mrcb准备:当前机器不为x86_64,不符合mrcb项目的运行要求,请更换机器架构到x86_64.")
        sys.exit(1)

    if '9950x' in platform.processor():
        print("当前9950x机器非常适合用于运行mrcb项目!")
    if os.cpu_count() <= 4:
        print("当前机器的CPU核心数有点少~~~")


def install_needed_rpms():
    try:
        subprocess.run(
            "dnf install -y gcc python3-devel python3-pip python3-Cython python3-psycopg2 python3-paramiko systemd-devel libffi-devel pkgconf libxml2 libxslt libxslt-devel libxml2-devel tmux postgresql",
            shell=True,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as e:
        print(f"mrcb准备:安装必备的rpm包失败.报错信息:{e.stderr}")
        sys.exit(1)



def install_needed_python_packages():
    try:
        subprocess.run(
            "pip install --upgrade pip setuptools && pip install --trusted-host pypi.org --trusted-host pypi.python.org --trusted-host=files.pythonhosted.org -r requirements.txt",
            shell=True,check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as e:
        print(f"mrcb准备:安装必备的Python第三方库失败.报错信息:{e.stderr}")
        sys.exit(1)


def init_postgresql():
    # 安装rpm包
    try:
        subprocess.run(
            "dnf install -y postgresql postgresql-server",
            shell=True,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as e:
        print(f"mrcb准备:安装postgresql数据库失败.报错信息:{e.stderr}")
        sys.exit(1)
    # 初始化pgsql
    if not Path("/var/lib/pgsql/data/").exists():   # 只有在pgsql未初始化时才需要初始化,不必重复初始化
        try:
            subprocess.run(
                "postgresql-setup --initdb",
                shell=True,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except subprocess.CalledProcessError as e:
            print(f"mrcb准备:初始化postgresql数据库失败.报错信息:{e.stderr}")
            sys.exit(1)
    time.sleep(3)

    shutil.copy2(src=Path('resources/postgresql.conf'), dst=Path('/var/lib/pgsql/data/postgresql.conf'))
    shutil.copy2(src=Path('resources/pg_hba.conf'), dst=Path('/var/lib/pgsql/data/pg_hba.conf'))
    shutil.chown(Path('/var/lib/pgsql/data/postgresql.conf'),user='postgres',group='postgres')
    shutil.chown(Path('/var/lib/pgsql/data/pg_hba.conf'), user='postgres', group='postgres')
    os.chmod(Path('/var/lib/pgsql/data/postgresql.conf'), 0o600)
    os.chmod(Path('/var/lib/pgsql/data/pg_hba.conf'), 0o600)


    # 导入pystemd包
    try:
        from pystemd.systemd1 import Unit
    except ImportError:
        print(f"mrcb准备:Python无法操作systemd.")
        sys.exit(1)

    def service_load_and_start(service:Unit):
        try:
            service.Unit.Start(b'replace')
        except:
            time.sleep(3)
            service.load(force=True)
            service.Unit.Start(b'replace')
        if service.Unit.ActiveState == b'active':
            time.sleep(3)
            service.Unit.Start(b'replace')
            if service.Unit.ActiveState != b'active':
                print(f"mrcb准备:启动postgresql服务失败.")
                sys.exit(1)

    time.sleep(3)
    # 操作并初始化pgsql表和库
    postgresql = Unit('postgresql.service',_autoload=True)
    service_load_and_start(postgresql)

    time.sleep(3)
    try:
        from psycopg2.pool import SimpleConnectionPool
    except ImportError:
        print(f"mrcb准备:引入psycopg2库失败.")
        sys.exit(1)

    cmd = r'''cd &&
    psql -tAc "SELECT 1 FROM pg_database WHERE datname = 'mugen_run_clean_batch'" | grep -q 1 ||
    psql -v ON_ERROR_STOP=1 -d postgres -c "CREATE DATABASE mugen_run_clean_batch ENCODING 'UTF8' TEMPLATE template0; -D /var/lib/pgsql"
    '''

    subprocess.run(['runuser', '-u', 'postgres', '--', 'bash', '-lc', cmd], check=True)


if __name__ == "__main__":
    print("开始做mrcb运行前准备工作:")
    close_selinux()         # 关闭selinux
    check_arch()            # 检查当前机器架构是否满足mrcb运行
    flash_time()            # 设置时间
    install_needed_rpms()   # 安装更必备的rpm包
    install_needed_python_packages()    # 安装必备的Python第三方库
    init_postgresql()       # 初始化postgresql数据库
    print("mrcb准备工作完成!")