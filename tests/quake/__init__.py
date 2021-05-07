import argparse
import logging
import os
import pathlib
import platform
import shutil
import stat
import subprocess
import sys
import unittest
import urllib.request
import zipfile


def load_tests(loader, standard_tests, pattern):
    this_dir = pathlib.Path(__file__).parent.resolve()
    os.chdir(this_dir)

    try:
        os.chdir("openarena-0.8.8")
    except FileNotFoundError:
        raise unittest.SkipTest("Run `python -m tests.quake setup` first.") from None

    package_tests = loader.discover(start_dir=this_dir, pattern=pattern)
    standard_tests.addTests(package_tests)
    return standard_tests


def run_quake(args=None):
    if args is None:
        args = "+set fs_game defrag +map defrag_gallery +quit"

    if sys.platform == "msys":
        quake = "winpty -Xallow-non-tty -Xplain ./oa_ded.exe"
    elif sys.platform == "linux" and platform.machine() in ("i386", "x86_64"):
        quake = f"./oa_ded.{platform.machine()}"
    else:
        raise unittest.SkipTest("unsupported platform")

    return subprocess.run(
        f"{quake} {args}",
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def download(url, path, force=False):
    path = pathlib.Path(path)

    if path.is_file() and not force:
        logging.info(f"{path} already exists, skipping download from {url}")
        return False

    logging.info(f"downloading {url} to {path}...")

    with urllib.request.urlopen(url) as src, open(path, "wb") as dst:
        shutil.copyfileobj(src, dst)

    logging.info("done")
    return True


def unzip(zip_path, dst_path=None):
    if dst_path is not None:
        logging.info(f"unzipping {zip_path} to {dst_path}...")
    else:
        logging.info(f"unzipping {zip_path}")
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(dst_path)
    logging.info("done")


def setup(args):
    logging.basicConfig(level=logging.INFO)

    os.chdir(pathlib.Path(__file__).parent.resolve())

    download(
        "http://download.tuxfamily.org/openarena/rel/088/openarena-0.8.8.zip",
        "openarena-0.8.8.zip",
    )
    unzip("openarena-0.8.8.zip")

    download(
        "https://q3defrag.org/files/defrag/defrag_1.91.27.zip", "defrag_1.91.27.zip"
    )
    unzip("defrag_1.91.27.zip", "openarena-0.8.8")

    os.chdir("openarena-0.8.8")
    mode = (
        stat.S_IRUSR
        | stat.S_IWUSR
        | stat.S_IXUSR
        | stat.S_IRGRP
        | stat.S_IXGRP
        | stat.S_IROTH
        | stat.S_IXOTH
    )
    os.chmod("oa_ded.i386", mode)
    os.chmod("oa_ded.x86_64", mode)

    os.chdir("defrag")
    unzip("zz-defrag_vm_191.pk3")
    os.remove("zz-defrag_vm_191.pk3")

    os.chdir("vm")
    shutil.copyfile("qagame.qvm", "original_qagame.qvm")
    shutil.copyfile("cgame.qvm", "original_cgame.qvm")
    shutil.copyfile("ui.qvm", "original_ui.qvm")

    logging.info("setup complete")


def main():
    parser = argparse.ArgumentParser(prog="python -m tests.quake")
    subparsers = parser.add_subparsers(dest="command")

    parser_setup = subparsers.add_parser(
        "setup", help="prepare the testing environment"
    )
    parser_setup.set_defaults(func=setup)

    args = parser.parse_args()
    if args.command is not None:
        args.func(args)
    else:
        parser.print_help()
