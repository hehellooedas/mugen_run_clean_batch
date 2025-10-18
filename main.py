#! /usr/bin/env python3
# encoding: utf-8

import subprocess

from psutil import users
from rich.console import Console
from rich.table import Table
from rich.traceback import install
from rich.logging import RichHandler
from setproctitle import setproctitle
from datetime import datetime

import logging
import argparse
import tomllib
import time
import json,pickle
import faker
import zipfile,lzma,tarfile
import shutil,psutil
import os,sys,signal
import requests
import humanfriendly
from collections import namedtuple
from pathlib import Path
from io import BytesIO
from openpyxl import load_workbook
import zstandard as zstd
from paramiko import SSHClient
from psycopg2.pool import ThreadedConnectionPool
from concurrent.futures import ThreadPoolExecutor
from queue import Queue,Empty



setproctitle('mrcb')    # 设置mrcb的进程名称

#install(show_locals=True)
console = Console(color_system='256',file=sys.stdout)

logging.basicConfig(
    level=logging.INFO,
    format='%(message)s',
    handlers=[RichHandler()]
)


cpu_count = os.cpu_count()
pgsql_pool = ThreadedConnectionPool(
    minconn=1,maxconn=cpu_count,
    host='localhost',
    port=5432,
    user='postgres',
    password='postgres',
)


# mugen测试用例描述
mugen_test = namedtuple(
    typename='mugen_test',
    field_names=[
        'TestSuite',    # 所属测试套
        'TestCase'      # 测试用例名
    ]
)
mugen_tests:Queue = Queue(maxsize=cpu_count * 2)      # 存放所有测试用例描述的列表
target_mugen_tail_object:object = object()             # 队列尾标志
# 把所有待测试项目全部放进队列里
def put_mugen_test_to_queue(mugen_test_list:list):
    for mugen_test in mugen_test_list:
        mugen_tests.put(mugen_test,block=True)
    mugen_tests.put(target_mugen_tail_object,block=True)




# mrcb存放资源的临时目录
mrcb_dir = Path('.')
mrcb_work_dir = mrcb_dir / f"workdir_{datetime.now().strftime('%Y%m%d_%H%M%S')}" # 本次运行mrcb创建的工作目录
mrcb_firmware_dir = mrcb_work_dir / 'firmware'   # 存放固件
mrcb_mugen_dir = mrcb_work_dir / 'mugen'         # 存放mugen项目
mrcb_runtime_dir = mrcb_work_dir / 'runtime'


# 当前项目支持的架构和启动平台
support_platforms = ('UEFI','UBOOT','PENGLAI')  # 支持的启动引导方式(固件)
support_archs = ('X86','ARM','RISC-V')          # 支持的指令集架构


# 预制的https请求头
faker = faker.Faker()
headers = {
    'Accept': 'image/avif,image/webp,image/png,image/svg+xml,image/*;q=0.8,*/*;q=0.5',
    'Accept-Encoding': 'gzip, deflate, br, zstd',
    'User-Agent': faker.user_agent(),
    'Referer': 'https://gitee.com/April_Zhao/mugen_run_clean_batch',
}





def parse_config() -> dict:
    """
    1. 命令行交互
    2. 读取和解析Toml配置文件
    :return: config字典,所有输入的参数转换为Python对象
    """
    parser = argparse.ArgumentParser(
        description="mrcb - Batch run mugen tests in a clean environment\n"
                    "把mugen批量地运行在干净的系统环境"
    )
    parser.add_argument(
        "--config", "-c",
        type=str,
        default="mrcb_config.toml",
        help="指定mrcb所需的Toml格式配置文件"
    )

    mrcb_config_file = parser.parse_args().config
    try:
        config = tomllib.loads(open(mrcb_config_file).read())
    except FileNotFoundError:
        console.print(f"您指定的文件{mrcb_config_file}不存在,请检查文件或目录名是否正确")
        sys.exit(1)

    # 判断platform是否合法
    global platform,arch
    platform,arch = config['platform'],config['arch']
    if platform not in support_platforms:
        console.print(f'您输入的openEuler qemu镜像启动平台{platform}值不合法,合法值必须为{support_platforms}其中之一')
        console.print('如有新平台需要接入请给mrcb项目提交issue')
        sys.exit(1)
    print(config)
    return config



def check_url(url: str) -> bool:
    try:
        response = requests.head(url=url,headers=headers,timeout=5)
        if response.status_code != requests.codes.ok:
            return False
    except (requests.exceptions.ConnectionError, requests.exceptions.HTTPError) as e:
        return False
    return True



def check_config(config:dict):
    """
    检查用户输入的Toml内的值是否合法
    根据配置文件的值制作参数列表
    :param platform:
    :param config:
    :return:
    """
    arch = config.get('arch',None)
    if arch is None or arch not in support_archs:
        console.print(f'您输入的arch字段有误,请确认值为下列之一:{support_archs}')
        sys.exit(1)
    result = {}

    if platform == "UEFI":
        drive_url:str = config.get('drive','')
        if drive_url == '' or check_url(drive_url) is False:
            console.print(f'您输入的drive_url字段url无法访问,请检查')
            #sys.exit(1)
        result['drive_url'] = drive_url
        
        VIRT_CODE = config.get('VIRT_CODE','')
        if VIRT_CODE == '' or check_url(VIRT_CODE) is False:
            console.print(f"您输入的VIRT_CODE字段url无法访问,请检查")
            #sys.exit(1)
        result['VIRT_CODE'] = VIRT_CODE

        VIRT_VARS = config.get('VIRT_VARS','')
        if VIRT_VARS == '' or check_url(VIRT_VARS) is False:
            console.print(f"您输入的VIRT_VARS字段url无法访问,请检查")
            #sys.exit(1)
        result['VIRT_VARS'] = VIRT_VARS
    elif platform == "uboot":
        pass
    elif platform == "penglai":
        pass
    input_excel = config.get('input_excel','')
    if input_excel == '':
        console.print(f"input_excel字段不可以为空")
        sys.exit(1)
    wb = load_workbook(input_excel)
    ws = wb.active
    from_to = config.get('from_to',[])
    if from_to == []:  # 由mrcb自动判断
        pass

    all_mugen_tests = []
    # 获取所有需要测试的mugen测试用例名
    for i in range(from_to[0],from_to[1]+1):
        each_mugen_test = mugen_test(
            TestSuite = ws.cell(row=i,column=1).value,
            TestCase = ws.cell(row=i,column=2).value,
        )
        all_mugen_tests.append(each_mugen_test)

    # 校验测试用例的合法性
    for TestSuite,TestCase in all_mugen_tests:
        if TestSuite + '.json' in mugen_suite_jsons:
            pass
        else:
            print(f"{TestSuite}不在mugen测试范围里,无法找到{TestSuite}.json文件.")
            #sys.exit(1)
        with open(mrcb_mugen_dir / 'suite2cases' / f'{TestSuite}.json','r',encoding='utf-8') as f:
            TestSuite_json = json.load(f)
            print(TestSuite_json)
            if TestCase not in (v for each in TestSuite_json['cases'] for k,v in each):
                print(f"{TestSuite}中不含有{TestCase},请仔细检查excel文件!")

    # 检测完成后建立数据表,将运行信息登记
    with pgsql_pool.getconn() as conn:
        with conn.cursor() as cursor:
            cursor.execute('select * from mugen_run_clean_batch;')
        


def get_analysis_mugen():
    """
    初始化正式运行前所需的本地环境
    :return:
    """

    if mrcb_work_dir.exists():
        shutil.rmtree(mrcb_work_dir)
    mrcb_work_dir.mkdir();mrcb_firmware_dir.mkdir()
    # 下载所有所需文件到tmp目录
    try:    # 获取mugen
        subprocess.run(
            args="git clone https://gitee.com/openeuler/mugen.git --depth=1",
            cwd=mrcb_work_dir,
            check=True,shell=True,
        )
    except subprocess.CalledProcessError as e:
        console.print(f"git clone失败,{e}")
        sys.exit(1)
    # 获取所有有可能用到的json文件的文件名
    global mugen_suite_jsons, mugen_cli_test_jsons, mugen_doc_test_jsons, mugen_fs_test_jsons, mugen_network_test_jsons, mugen_service_jsons, mugen_smoke_test_jsons, mugen_system_integration_jsons
    mugen_suite_jsons = list(os.walk(mrcb_mugen_dir / 'suite2cases'))[0][2]
    mugen_cli_test_jsons = list(os.walk(mrcb_mugen_dir / 'suite2cases/mugen_baseline_json' / 'cli-test'))[0][2]
    mugen_doc_test_jsons = list(os.walk(mrcb_mugen_dir / 'suite2cases/mugen_baseline_json' / 'doc-test'))[0][2]
    mugen_fs_test_jsons = list(os.walk(mrcb_mugen_dir / 'suite2cases/mugen_baseline_json' / 'fs-test'))[0][2]
    mugen_network_test_jsons = list(os.walk(mrcb_mugen_dir / 'suite2cases/mugen_baseline_json' / 'network_test'))[0][2]
    mugen_service_jsons = list(os.walk(mrcb_mugen_dir / 'suite2cases/mugen_baseline_json' / 'service'))[0][2]
    mugen_smoke_test_jsons = list(os.walk(mrcb_mugen_dir / 'suite2cases/mugen_baseline_json' / 'smoke-test'))[0][2]
    mugen_system_integration_jsons = list(os.walk(mrcb_mugen_dir / 'suite2cases/mugen_baseline_json' / 'system-integration'))[0][2]




def input_from_excel():
    input_excel_file = config.get('input_excel')
    wb = load_workbook(input_excel_file,read_only=True)
    ws = wb.active

    from_to = config.get('from_to')
    all_mugen_tests = []
    for i in range(from_to[0],from_to[1]+1):
        all_mugen_tests.append(mugen_test(TestSuite=ws[f'a{i}'].value,TestCase=ws[f'b{i}'].value))


if __name__ == "__main__":
    start_time = time.time()

    # 先初始化mugen
    get_analysis_mugen()
    config:dict = parse_config()
    input_from_excel()
    check_config(config)

    # 正式开始测试
    # with ThreadPoolExecutor(max_workers=cpu_count) as executor:
    #     executor.submit(put_mugen_test_to_queue)


    end_time = time.time()
    console.print(f"mrcb运行结束,本次运行总耗时{humanfriendly.format_timespan(end_time - start_time)}")