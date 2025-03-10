#! /usr/bin/env python3
# encoding: utf-8

import asyncio,aiohttp,aiofiles,asyncssh,asyncpg
import tomllib,zipfile,io,json,faker,argparse,lzma
import time,datetime,shutil
import os,sys,signal
from pathlib import Path
import zstandard as zstd
from concurrent.futures import ProcessPoolExecutor


fake = faker.Faker()
cpu_count = os.cpu_count()
mrcb_tmp_dir = Path('mrcb_tmp')

platform = ''   # 测试平台(UEFI,uboot,penglai)
arch = ''       # 测试架构
headers = {
    'Accept': 'image/avif,image/webp,image/png,image/svg+xml,image/*;q=0.8,*/*;q=0.5',
    'Accept-Encoding': 'gzip, deflate, br, zstd',
    'User-Agent': fake.user_agent(),
    'Referer': 'https://gitee.com/April_Zhao/mugen_run_clean_batch',
}
config = {}

def parse_config() -> dict:
    global platform,arch
    parser = argparse.ArgumentParser(description="get the config file name for mrcb.")
    parser.add_argument("--config", "-c", type=str, default="mrcb_config.toml")
    mrcb_config_file = parser.parse_args().config
    try:
        config = tomllib.loads(open(mrcb_config_file).read())
    except FileNotFoundError:
        print(f"您指定的文件{mrcb_config_file}不存在,请检查文件或目录名是否正确")
        sys.exit(1)
    if len(config.keys()) != 1:
        print('配置文件中请不要出现多于一对[]')
        sys.exit(1)
    platform = next(iter(config.keys()))
    config = config[platform]
    arch = config['arch']
    if platform in ('uefi','UEFI'):
        print('测试平台为UEFI')
        platform = 'UEFI'
    elif platform in ('uboot','UBOOT'):
        print('测试平台为uboot')
        platform = 'uboot'
    elif platform in ('penglai','PENGLAI'):
        print('测试平台为penglai')
        platform = 'penglai'
    config['input_excel'] = Path(config['input_excel'])
    return config



async def excel2pg(config: dict):
    pass



async def init_environment():
    """
    初始化运行qemu的环境
    """
    install_rpms = await asyncio.create_subprocess_shell(
        "dnf install -y --nobest --skip-broken qemu qemu-img bridge-utils git make",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout,stderr = await install_rpms.communicate()
    if install_rpms.returncode != 0:
        print(f"初始化mrcb环境.安装必要的rpm包失败,报错信息:{stderr.decode('utf-8')}")
        sys.exit(1)



async def init_mugen(config:dict):
    """
    运行前需要对当前版本的mugen进行分析,并保存分析的结果
    mugen更新后描述测试用例的json文件可能改变,因此需要每天更新
    :return:
    """
    if (datetime.datetime.fromtimestamp(Path(mrcb_tmp_dir / 'mugen').stat().st_ctime)).day >= 1:
        shutil.rmtree(mrcb_tmp_dir / 'mugen')
    if not Path(mrcb_tmp_dir / 'mugen').exists():
        gitClone = await asyncio.subprocess.create_subprocess_shell(
            f"cd {mrcb_tmp_dir} && git clone https://gitee.com/openeuler/mugen.git --depth=1",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout,stderr = await gitClone.communicate()
        if gitClone.returncode != 0:
            print(f"mrcb初始化.git clone mugen失败,报错信息:{stderr.decode('utf-8')}")
            sys.exit(1)

    async with aiofiles.open(mrcb_tmp_dir / 'mugen/suite2cases/FS_Device.json','r') as file:
        content = await file.read()
        case = json.loads(content)
        print(case.get('machine num'))
        print(case.get('add disk')[0])



async def download_openEuler_file(session:aiohttp.ClientSession):
    async with session.get(
            config['drive_url'],
            headers=headers
    ) as response:
        response.raise_for_status()
        content = await response.read()
        compress_format = config['drive_url'].split('.')[-1]
        print(compress_format)
        if compress_format == 'xz':
            async with lzma.open(content, 'rb') as xz_file, aiofiles.open(
                    mrcb_tmp_dir / f"openEuler.{config['drive_type']}", 'wb') as file:
                await file.write(xz_file.read())
        elif compress_format == 'zip':
            async with zipfile.ZipFile(io.BytesIO(content)) as zip_file, aiofiles.open(
                    mrcb_tmp_dir / f"openEuler.{config['drive_type']}", 'wb') as file:
                await file.write(zip_file.read())
        elif compress_format == 'zst':
            with zstd.open(io.BytesIO(content)) as z_file, aiofiles.open(
                    mrcb_tmp_dir / f"openEuler.{config['drive_type']}", 'wb') as file:
                await file.write(z_file.read())


async def download_UEFI_firmware(session:aiohttp.ClientSession,type:str):
    print(config[type])
    async with session.get(config[type],headers=headers) as response:
        response.raise_for_status()
        content = await response.read()
        async with aiofiles.open(mrcb_tmp_dir / f'RISCV_{type}.fd', 'wb') as file:
            await file.write(content)



async def init_openEuler(config:dict):
    # 下载镜像
    async with aiohttp.client.ClientSession() as session:
        if platform == 'UEFI':
            try:
                await asyncio.gather(
                    download_openEuler_file(session),
                    download_UEFI_firmware(session,'VIRT_CODE'),
                    download_UEFI_firmware(session, 'VIRT_VARS')
                )
            except aiohttp.ClientError:
                print(f"网络问题,下载中断,请重试并检查输入的url")
            except lzma.LZMAError:
                print(f"{config['drive_url']}文件解压缩出错,请重试")
            except zipfile.BadZipFile:
                print(f"{config['drive_url']}文件解压缩出错,请重试")
            except Exception as e:
                print(f'发生了mrcb预料之外的错误.报错信息:{e}')

        elif platform == 'uboot':
            pass

        elif platform == 'penglai':
            pass



if __name__ == "__main__":
    config = parse_config()
    #excel2pg(config['input_excel'])

    if not mrcb_tmp_dir.exists():
        mrcb_tmp_dir.mkdir()
    #asyncio.create_task(init_mugen(config))
    #asyncio.create_task(init_openEuler(config))
    #asyncio.create_task(excel2pg(config))
    asyncio.run(init_openEuler(config))
    machine_id_queue = asyncio.Queue(maxsize=cpu_count)