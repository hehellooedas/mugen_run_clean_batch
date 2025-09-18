#! /usr/bin/env python3
# encoding: utf-8
import subprocess

from rich.console import Console
from rich.table import Table
from rich.traceback import install
from rich.logging import RichHandler
from setproctitle import setproctitle

import queue
import logging
import argparse
import tomllib
import time
import json
import faker
import zipfile,lzma,tarfile
import shutil,psutil
import os,sys,signal
import requests

from collections import namedtuple
from pathlib import Path
from io import BytesIO
from openpyxl import load_workbook
import zstandard as zstd
from paramiko import SSHClient
from concurrent.futures import ThreadPoolExecutor



setproctitle('mrcb')

install(show_locals=True)
console = Console(color_system='256',file=sys.stdout)

logging.basicConfig(
    level=logging.INFO,
    format='%(message)s',
    handlers=[RichHandler()]
)


cpu_count = os.cpu_count()

# mugen测试用例描述
mugen_test = namedtuple(
    typename='mugen_test',
    field_names=[
        'TestSuite',    # 所属测试套
        'TestCase'      # 测试用例名
    ]
)


# mrcb存放资源的临时目录
mrcb_tmp_dir = Path('/root/mrcb_tmp')
firmware_dir = mrcb_tmp_dir / 'firmware'
mugen_dir = mrcb_tmp_dir / 'mugen'

# mrcb运行时目录
mrcb_runtime_dir = Path('/root/mrcb_runtime')

# mrcb存放结果的目录
mrcb_result_dir = Path('/root/mrcb_result')


support_platform = ('UEFI','uboot','penglai')
support_arch = ('x86_64','riscv64')

faker = faker.Faker()

headers = {
    'Accept': 'image/avif,image/webp,image/png,image/svg+xml,image/*;q=0.8,*/*;q=0.5',
    'Accept-Encoding': 'gzip, deflate, br, zstd',
    'User-Agent': faker.user_agent(),
    'Referer': 'https://gitee.com/April_Zhao/mugen_run_clean_batch',
}


SuiteCaseQueue = queue.Queue()



def parse_config() -> dict:
    """
    1. 命令行交互
    2. 读取和解析Toml配置文件
    :return: config字典
    """
    parser = argparse.ArgumentParser(
        description="mrcb - Batch run mugen tests in a clean environment\n"
                    "把mugen运行在干净的系统环境"
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
    if len(config.keys()) != 1:
        console.print('配置文件中请不要出现多于一对[]')
        sys.exit(1)
    # 判断platform是否合法
    global platform,arch
    platform,arch = config['platform'],config['arch']
    if platform not in support_platform:
        console.print(f'您输入的openEuler qemu镜像启动平台{platform}值不合法,合法值必须为{support_platform}其中之一')
        console.print('如有新平台需要接入请给mrcb项目提交issue')
        sys.exit(1)
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
    if arch is None or arch not in support_arch:
        console.print(f'您输入的arch字段有误,请确认值为下列之一:{support_arch}')
        sys.exit(1)
    result = {}

    if platform == "UEFI":
        drive_url:str = config.get('drive','')
        if drive_url == '' or check_url(drive_url) is False:
            console.print(f'您输入的drive_url字段url无法访问,请检查')
            sys.exit(1)
        result['drive_url'] = drive_url
        
        VIRT_CODE = config.get('VIRT_CODE','')
        if VIRT_CODE == '' or check_url(VIRT_CODE) is False:
            console.print(f"您输入的VIRT_CODE字段url无法访问,请检查")
            sys.exit(1)
        result['VIRT_CODE'] = VIRT_CODE

        VIRT_VARS = config.get('VIRT_VARS','')
        if VIRT_VARS == '' or check_url(VIRT_VARS) is False:
            console.print(f"您输入的VIRT_VARS字段url无法访问,请检查")
            sys.exit(1)
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

    # 获取所有需要测试的mugen测试用例名
    for i in range(from_to[0],from_to[1]+1):
        SuiteCaseQueue.put(
        mugen_test(
            TestSuite = ws.cell(row=i,column=1).value,
            TestCase = ws.cell(row=i,column=2).value,
        ))





def init_environment_before_run(config):
    """
    初始化正式运行前所需的本地环境
    :return:
    """
    if mrcb_tmp_dir.exists():
        shutil.rmtree(mrcb_tmp_dir)
    mrcb_tmp_dir.mkdir(parents=True)

    if mrcb_runtime_dir.exists():
        shutil.rmtree(mrcb_runtime_dir)
    mrcb_runtime_dir.mkdir(parents=True)

    if mrcb_result_dir.exists():
        shutil.rmtree(mrcb_result_dir)
    shutil.rmtree(mrcb_result_dir)


    # 下载所有所需文件到tmp目录
    try:    # 获取mugen
        subprocess.run(
            args="git clone https://gitee.com/openeuler/mugen.git --depth=1",
            cwd=mrcb_tmp_dir,
            check=True,shell=True,
        )
    except subprocess.CalledProcessError as e:
        console.print(f"git clone失败,{e}")
        sys.exit(1)


    # 下载openEuler的qemu镜像
    url = config.get('drive_url')
    image_format = url.split('.')[-1]
    response = requests.get(
        url = url,
        headers = headers,
    )
    response.raise_for_status()
    if image_format == 'zst':
        decompressed_data = zstd.decompress(response.content)
        with open(mrcb_tmp_dir / f"openEuler.{config['drive_type']}", 'wb') as file:
            file.write(decompressed_data)
    elif image_format == 'xz':
        pass
    elif image_format == 'bz2':
        pass
    elif image_format == 'zip':
        pass
    elif image_format == 'gz':
        pass

    if platform == 'UEFI':
        ...






if __name__ == "__main__":
    start_time = time.time()
    config = parse_config()
    check_config(config)
    init_environment_before_run(config)
    print(config)

    # 正式开始测试
    with ThreadPoolExecutor(max_workers=cpu_count) as executor:
        pass