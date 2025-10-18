#! /usr/bin/env python3
# encoding: utf-8

"""
    在mrcb脚本运行前运行该脚本初始化环境和安装必要rpm包/Python第三方库
    以确保mrcb运行正常,简化用户操作
"""
import shutil
import subprocess
import sys
import platform
import time
from pathlib import Path




def flash_time():
    try:
        subprocess.run(
            "dnf install -y ntp && ntpdate cn.pool.ntp.org",
            shell=True,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as e:
        print(f"mrcb准备:刷新时间失败.报错信息:{e.stderr}")
        sys.exit(1)


def check_arch():
    if platform.machine() != 'x86_64':
        print(f"mrcb准备:当前机器不为x86_64,不符合mrcb项目的运行要求,请更换机器架构到x86_64.")
        sys.exit(1)


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

    shutil.move(src=Path('resources/postgresql.conf'), dst=Path('/var/lib/pgsql/data/postgresql.conf'))
    shutil.move(src=Path('resources/pg_hba.conf'), dst=Path('/var/lib/pgsql/data/pg_hba.conf'))

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
            if service.Unit.ActiveState == b'active':
                print(f"mrcb准备:启动postgresql服务失败.")

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
    pgsql_pool = SimpleConnectionPool(
        minconn=1,maxconn=4,
        host='localhost',
        port='5432',
        user='postgres',
        password='postgres',
    )
    with pgsql_pool.getconn() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT datname FROM pg_database WHERE datistemplate = false;")
            result = cursor.fetchall()
            print(result)


if __name__ == "__main__":
    check_arch()
    flash_time()
    install_needed_rpms()
    install_needed_python_packages()
    init_postgresql()
