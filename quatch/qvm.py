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

"""This module contains the main Qvm class."""

from __future__ import annotations

import collections
import contextlib
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Mapping
from typing import Optional, Union
from . import q3asm
from .instruction import assemble, disassemble, Instruction as Ins, Opcode as Op
from .memory import Memory, RegionTag
from .util import pad


STACK_SIZE = 0x10000


class InitSymbolError(Exception):
    pass


class CompilerError(Exception):
    pass


class Qvm:
    """A patchable Quake 3 VM program.

    Attributes:
        vm_magic: The "magic number" of the qvm file format version.
        memory: The contents of the program's memory.
        instructions: Dissasembly of the code section.
        symbols: A dictionary mapping names to addresses.
    """

    def __init__(self, path: str, symbols: Optional[Mapping[str, int]] = None) -> None:
        """Initialize Qvm from a .qvm file.

        Args:
            path: Path of the .qvm file to read.
            symbols: A mapping from names to addresses.
        """
        with open(path, "rb") as f:
            format = "<IIIIIIII"
            raw_header = f.read(struct.calcsize(format))
            (
                self.vm_magic,
                instruction_count,
                code_offset,
                code_length,
                data_offset,
                self._data_length,
                self._lit_length,
                bss_length,
            ) = struct.unpack(format, raw_header)

            f.seek(code_offset)
            self.instructions = disassemble(f.read(code_length))

            # strip off trailing instructions that are actually just padding
            self.instructions = self.instructions[:instruction_count]

            self.memory = Memory()

            # STACK_SIZE bytes are reserved at the end of bss for use as the program
            # stack. We are going to use it for our own data and reserve STACK_SIZE
            # more bytes at the end when we're done.
            bss_length -= STACK_SIZE

            f.seek(data_offset)
            self.add_data(f.read(self._data_length))
            self.add_lit(f.read(self._lit_length))
            self.add_bss(bss_length)

        self.symbols = dict(symbols or {})

        self._calls = collections.defaultdict(list)
        for i in range(len(self.instructions) - 1):
            first, second = self.instructions[i : i + 2]
            if first.opcode == Op.CONST and second.opcode == Op.CALL:
                self._calls[first.operand].append(i)

        self._lcc = self._find_lcc()

    def write(self, path: str) -> None:
        """Write a .qvm file.

        Requires a symbol to be defined for one of the G_InitGame, CG_Init, or UI_Init
        functions if any new data has been added so that it can be initialized by
        hooking the function.

        Args:
            path: Path of the .qvm file to write.

        Raises:
            InitSymbolError: No valid G_InitGame, CG_Init, or UI_Init symbol was found.
        """
        self._add_data_init_code()

        with open(path, "wb") as f:
            format = "<IIIIIIII"
            header_size = struct.calcsize(format)
            f.seek(header_size)

            code_offset = f.tell()
            code = pad(assemble(self.instructions), 4)
            f.write(code)

            data_offset = f.tell()
            f.write(self.memory[: self._data_length + self._lit_length])

            header = struct.pack(
                format,
                self.vm_magic,
                len(self.instructions),
                code_offset,
                len(code),
                data_offset,
                self._data_length,
                self._lit_length,
                len(self.memory) - self._data_length - self._lit_length + STACK_SIZE,
            )
            f.seek(0)
            f.write(header)

    def add_data(self, data: bytes, alignment: int = 4) -> int:
        """Add data to the DATA section.

        The DATA section is meant hold to 4-byte words, so alignment and the size of
        data must both be multiples of 4.

        Args:
            data: The data to add.
            alignment: The added data's address will be a multiple of this.

        Returns:
            The address of the added data.
        """
        return self.memory.add_region(RegionTag.DATA, data=data, alignment=alignment)

    def add_lit(self, data: bytes, alignment: int = 1) -> int:
        """Add data to the LIT section.

        Args:
            data: The data to add.
            alignment: The added data's address will be a multiple of this.

        Returns:
            The address of the added data.
        """
        return self.memory.add_region(RegionTag.LIT, data=data, alignment=alignment)

    def add_bss(self, size: int, alignment: int = 1) -> int:
        """Add data to the BSS section.

        Args:
            size: The number of BSS bytes to add.
            alignment: The added data's address will be a multiple of this.

        Returns:
            The address of the added data.
        """
        return self.memory.add_region(RegionTag.BSS, size=size, alignment=alignment)

    def add_code(self, instructions: Iterable[Ins]) -> int:
        """Add code to the Qvm.

        Args:
            instructions: The instructions to add.

        Returns:
            The address of the added code.
        """
        address = len(self.instructions)
        self.instructions.extend(instructions)
        return address

    def _find_lcc(self):
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

    def add_c_code(
        self, code: str, include_dirs: Optional[Iterable[str]] = None
    ) -> None:
        """Compile C code and add it to the Qvm.

        Symbols defined in the code will be added to `symbols`.

        Args:
            code: The C code to compile.
            include_dirs: A list of include paths.

        Raises:
            CompilerError: There was an error during compilation.
            FileNotFoundError: The lcc compiler could not be found.
        """
        if self._lcc is None:
            raise FileNotFoundError(
                "Unable to locate lcc. Set the LCC environment variable or make sure "
                "it is in your PATH."
            )

        c_file = tempfile.NamedTemporaryFile(suffix=".c", delete=False)
        asm_file = tempfile.NamedTemporaryFile(suffix=".asm", delete=False)

        try:
            c_file.write(code.encode())

            # these must be closed on windows or lcc won't be able to open them
            c_file.close()
            asm_file.close()

            command = [
                self._lcc,
                "-DQ3_VM",
                "-S",
                "-Wf-target=bytecode",
                "-Wf-g",
            ]
            if include_dirs is not None:
                command += [f"-I{include_dir}" for include_dir in include_dirs]
            command += ["-o", asm_file.name, c_file.name]

            # make sure lcc can find the other executables it needs
            env = os.environ.copy()
            env["PATH"] = (
                os.path.realpath(os.path.dirname(self._lcc))
                + os.pathsep
                + env.get("PATH", "")
            )

            subprocess.check_output(command, env=env, stderr=subprocess.STDOUT)

            self.memory.align(4)

            assembler = q3asm.Assembler()
            instructions, segments, symbols = assembler.assemble(
                [asm_file.name],
                code_base=len(self.instructions),
                data_base=len(self.memory),
                symbols=self.symbols,
            )

            self.instructions.extend(instructions)

            self.add_data(segments["data"].image)
            self.add_lit(segments["lit"].image)
            self.add_bss(len(segments["bss"].image))

            self.symbols.update(symbols)

        except subprocess.CalledProcessError as e:
            raise CompilerError(e.output.decode()) from None

        finally:
            c_file.close()
            asm_file.close()
            with contextlib.suppress(FileNotFoundError):
                os.remove(c_file.name)
                os.remove(asm_file.name)

    def _add_data_init_code(self) -> None:
        for init_name in ("G_InitGame", "CG_Init", "UI_Init"):
            original_init = self.symbols.get(init_name)
            if original_init is not None:
                break

        if original_init is None:
            raise InitSymbolError(
                "Cannot find a symbol for G_InitGame, CG_Init, or UI_Init"
            )

        if len(self._calls[original_init]) == 0:
            raise InitSymbolError(f"{init_name} is never called")

        # check original_init's first callsite in case it has already been hooked
        original_init_call = self._calls[original_init][0]
        current_init = self.instructions[original_init_call].operand

        init_wrapper = self.add_code([Ins(Op.ENTER, 0x100)])

        # initialize new data
        for region in self.memory.regions_with_tag(RegionTag.DATA):
            begin, end = region.begin, region.end

            # skip .qvm's data section
            if (begin, end) == (0, self._data_length):
                continue

            for address in range(begin, end, 4):
                value = struct.unpack("<I", self.memory[address : address + 4])[0]
                if value != 0:
                    self.add_code(
                        [
                            Ins(Op.CONST, address),
                            Ins(Op.CONST, value),
                            Ins(Op.STORE4),
                        ]
                    )

        # initialize new lit
        for region in self.memory.regions_with_tag(RegionTag.LIT):
            begin, end = region.begin, region.end

            # skip .qvm's lit section
            if (begin, end) == (
                self._data_length,
                self._data_length + self._lit_length,
            ):
                continue

            for address in range(begin, end):
                value = self.memory[address]
                if value != 0:
                    self.add_code(
                        [
                            Ins(Op.CONST, address),
                            Ins(Op.CONST, value),
                            Ins(Op.STORE1),
                        ]
                    )

        self.add_code(
            [
                # call original init function
                Ins(Op.LOCAL, 0x108),
                Ins(Op.LOAD4),
                Ins(Op.ARG, 0x8),
                Ins(Op.LOCAL, 0x10C),
                Ins(Op.LOAD4),
                Ins(Op.ARG, 0xC),
                Ins(Op.LOCAL, 0x110),
                Ins(Op.LOAD4),
                Ins(Op.ARG, 0x10),
                Ins(Op.CONST, current_init),
                Ins(Op.CALL),
                Ins(Op.LEAVE, 0x100),
                # dummy end proc so quake3e doesn't complain
                Ins(Op.PUSH),
                Ins(Op.LEAVE, 0x100),
            ]
        )

        # only hook the first call site in case there are multiple (this should be the
        # one called from vmMain when the qvm is first loaded)
        self.instructions[original_init_call].operand = init_wrapper

    def replace_calls(self, old: Union[str, int], new: Union[str, int]) -> int:
        """Replace calls to ``old`` with calls to ``new``.

        Args:
            old: The name or address of the old function.
            new: The name or address of the new function.

        Returns:
            The number of calls replaced.
        """
        if isinstance(old, str):
            old = self.symbols[old]

        if isinstance(new, str):
            new = self.symbols[new]

        for call in self._calls[old]:
            self.instructions[call].operand = new

        return len(self._calls[old])
