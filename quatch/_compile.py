# Copyright 2021 Josh Steffen
#
# This file is part of Quatch.
#
# Quatch is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# Quatch is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Quatch; If not, see <https://www.gnu.org/licenses/>.

"""C code compilation with Quake 3's lcc compiler."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import Iterable, Optional


class CompilerError(Exception):
    pass


def compile_c_file(
    input_path: str, output_path: str, include_dirs: Optional[Iterable[str]] = None
) -> str:
    """Compile C code into lcc bytecode.

    Requires Quake 3's lcc compiler to be installed. The LCC environment variable can be
    set to the path of the lcc executable if it is not detected.

    Additional search paths for include files can be specified in include_dirs.

    Compilation errors will cause a CompilerError exception to be raised with the
    error message.

    Returns the compiler's standard output/error.
    """
    if _lcc is None:
        raise FileNotFoundError(
            "Unable to locate lcc. Set the LCC environment variable or make sure "
            "it is in your PATH."
        )

    command = [
        _lcc,
        "-DQ3_VM",
        "-S",
        "-Wf-target=bytecode",
        "-Wf-g",
    ]
    if include_dirs is not None:
        command += [f"-I{include_dir}" for include_dir in include_dirs]
    command += ["-o", output_path, input_path]

    # make sure lcc can find the other executables it needs
    env = os.environ.copy()
    env["PATH"] = (
        os.path.realpath(os.path.dirname(_lcc)) + os.pathsep + env.get("PATH", "")
    )

    try:
        output = subprocess.check_output(command, env=env, stderr=subprocess.STDOUT)
        return output.decode()

    except subprocess.CalledProcessError as e:
        raise CompilerError(e.output.decode()) from None


def _find_lcc():
    path = os.getcwd() + os.pathsep + os.environ.get("PATH", "")
    lcc = (
        os.environ.get("LCC")
        or shutil.which("lcc", path=path)
        or shutil.which("q3lcc", path=path)
    )

    if lcc is None and sys.platform in ("win32", "msys"):
        for bin_dir in ("bin_nt", "bin"):
            lcc = lcc or shutil.which(
                os.path.join("C:" + os.sep, "quake3", bin_dir, "lcc.exe")
            )

    return lcc


_lcc = _find_lcc()
