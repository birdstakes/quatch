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

"""A class for loading and patching .qvm files."""

from __future__ import annotations

import collections
import contextlib
import mmap
import os
import struct
import tempfile
from collections.abc import Iterable, Mapping
from typing import Any, Optional, Union
from ._compile import compile_c_file, CompilerError
from ._instruction import assemble, disassemble, Instruction as Ins, Opcode as Op
from ._memory import Memory, RegionTag
from ._q3asm import Assembler, AssemblerError
from ._util import crc32, forge_crc32, pad


STACK_SIZE = 0x10000
HEADER_FORMAT = "<IIIIIIII"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)


class InitSymbolError(Exception):
    pass


class Qvm:
    """A patchable Quake 3 VM program.

    Compiling C code:
        The add_c_code, add_c_file, and add_c_files methods compile C code and add the
        resulting instructions, data, and defined symbols to the Qvm. By default these
        use the version of Quake 3's lcc compiler that is included with Quatch, but the
        LCC environment variable can be set to the path of a different lcc executable if
        a specific version is needed.

    Attributes:
        vm_magic: The magic number of the qvm file format version.
        memory: The contents of the program's memory.
        instructions: Dissasembly of the code section.
        symbols: A dictionary mapping symbol names to addresses.
    """

    def __init__(self, path: str, symbols: Mapping[str, int] = None) -> None:
        """Initialize a Qvm from a .qvm file.

        A mapping from names to addresses may be provided in symbols. Anything defined
        here will be available from C code added with self.add_c_code.
        """
        with open(path, "rb") as f:
            (
                self.vm_magic,
                instruction_count,
                code_offset,
                code_length,
                data_offset,
                self._orignal_data_length,
                self._original_lit_length,
                bss_length,
            ) = struct.unpack(HEADER_FORMAT, f.read(HEADER_SIZE))

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
            self.add_data(f.read(self._orignal_data_length))
            self.add_lit(f.read(self._original_lit_length))
            self.add_bss(bss_length)

            f.seek(0)
            self._original_crc = crc32(f.read())

        self.symbols = dict(symbols or {})

        self._calls = collections.defaultdict(list)
        for i in range(len(self.instructions) - 1):
            first, second = self.instructions[i : i + 2]
            if first.opcode == Op.CONST and second.opcode == Op.CALL:
                self._calls[first.operand].append(i)

    def write(self, path: str, forge_crc: bool = False) -> None:
        """Write a .qvm file.

        If forge_crc is True, the resulting file will have the same CRC-32 checksum as
        the original .qvm file.

        New data will be initialized by hooking one of the G_InitGame, CG_Init, or
        UI_Init functions. An InitSymbolError exception will be raised if a valid symbol
        for one of these functions cannot be found.
        """
        self._add_data_init_code()

        with open(path, "w+b") as f:
            f.seek(HEADER_SIZE)

            code_offset = f.tell()
            code = pad(assemble(self.instructions), 4)
            f.write(code)

            data_offset = f.tell()
            f.write(
                self.memory[: self._orignal_data_length + self._original_lit_length]
            )

            bss_length = (
                len(self.memory)
                - self._orignal_data_length
                - self._original_lit_length
                + STACK_SIZE
            )

            f.seek(0)
            f.write(
                struct.pack(
                    HEADER_FORMAT,
                    self.vm_magic,
                    len(self.instructions),
                    code_offset,
                    len(code),
                    data_offset,
                    self._orignal_data_length,
                    self._original_lit_length,
                    bss_length,
                )
            )

            if forge_crc:
                f.flush()
                with mmap.mmap(f.fileno(), 0) as mm:
                    # we'll let forge_crc32 overwrite the first 4 bytes of the data
                    # section since nobody should be using address 0
                    forge_crc32(mm, data_offset, self._original_crc)

    def add_data(self, data: bytes, alignment: int = 4) -> int:
        """Add data to the DATA section and return its address.

        The DATA section is meant hold to 4-byte words that will be byte-swapped at
        load time if needed, so alignment and the size of data must both be multiples
        of 4.
        """
        return self.memory.add_region(RegionTag.DATA, data=data, alignment=alignment)

    def add_lit(self, data: bytes, alignment: int = 1) -> int:
        """Add data to the LIT section and return its address.

        The LIT section is meant to hold data that never needs to be byte-swapped, such
        as strings.
        """
        return self.memory.add_region(RegionTag.LIT, data=data, alignment=alignment)

    def add_bss(self, size: int, alignment: int = 1) -> int:
        """Add zero-filled data to the BSS section and return its address."""
        return self.memory.add_region(RegionTag.BSS, size=size, alignment=alignment)

    def add_code(self, instructions: Iterable[Ins]) -> int:
        """Add code to the Qvm and return its address."""
        address = len(self.instructions)
        self.instructions.extend(instructions)
        return address

    def add_c_code(
        self,
        code: str,
        include_dirs: Optional[Iterable[str]] = None,
        **kwargs: Optional[Any],
    ) -> str:
        """Compile a string of C code and add it to the Qvm.

        Additional search paths for include files can be specified in include_dirs.

        Compilation errors will cause a CompilerError exception to be raised with the
        error message.

        Returns the compiler's standard output/error.
        """
        c_file = tempfile.NamedTemporaryFile(suffix=".c", delete=False)
        try:
            c_file.write(code.encode())

            # this must be closed on windows or lcc won't be able to open it
            c_file.close()

            return self.add_c_file(c_file.name, include_dirs=include_dirs, **kwargs)
        finally:
            c_file.close()
            with contextlib.suppress(FileNotFoundError):
                os.remove(c_file.name)

    def add_c_file(
        self,
        path: str,
        include_dirs: Optional[Iterable[str]] = None,
        **kwargs: Optional[Any],
    ) -> str:
        """Compile a C file and add the code to the Qvm.

        Additional search paths for include files can be specified in include_dirs.

        Compilation errors will cause a CompilerError exception to be raised with the
        error message.

        Returns the compiler's standard output/error.
        """
        return self.add_c_files([path], include_dirs=include_dirs, **kwargs)

    def add_c_files(
        self,
        paths: Iterable[str],
        include_dirs: Optional[Iterable[str]] = None,
        **kwargs: Optional[Any],
    ) -> str:
        """Compile C files and add the code to the Qvm.

        Additional search paths for include files can be specified in include_dirs.

        Compilation errors will cause a CompilerError exception to be raised with the
        error message.

        Returns the compiler's standard output/error.
        """
        asm_files = []
        output = ""

        try:
            for path in paths:
                asm_file = tempfile.NamedTemporaryFile(suffix=".asm", delete=False)
                asm_files.append(asm_file)

                # this must be closed on windows or lcc won't be able to open it
                asm_file.close()

                output += compile_c_file(path, asm_file.name, include_dirs=include_dirs)

            self.memory.align(4)

            assembler = Assembler()
            instructions, segments, symbols = assembler.assemble(
                [asm_file.name for asm_file in asm_files],
                code_base=kwargs.get("code_base", len(self.instructions)),
                data_base=kwargs.get("data_base", len(self.memory)),
                lit_base=kwargs.get("lit_base"),
                bss_base=kwargs.get("bss_base"),
                pad_segments=kwargs.get("pad_segments"),
                symbols=self.symbols,
            )

            new_segment_bases = kwargs.get("new_segment_bases")
            if new_segment_bases:
                for section in ("code", "data", "lit", "bss"):
                    segment = segments[section]
                    new_segment_bases[f"{section}_base"] = segment.segment_base + len(
                        segment.image
                    )

            code_base = kwargs.get("code_base")
            if code_base is not None:
                self.instructions[
                    code_base : code_base + len(instructions)
                ] = instructions
            else:
                self.instructions.extend(instructions)

            for segment in ("data", "lit", "bss"):
                base = kwargs.get(f"{segment}_base")
                data = segments[segment].image
                if base is not None:
                    self.mem[base : base + len(data)] = data
                else:
                    getattr(self, f"add_{segment}")(
                        len(data) if segment == "bss" else data
                    )

            self.symbols.update(symbols)
            return output

        except AssemblerError as e:
            raise CompilerError(str(e)) from None

        finally:
            for asm_file in asm_files:
                asm_file.close()
                with contextlib.suppress(FileNotFoundError):
                    os.remove(asm_file.name)

    def _add_data_init_code(self) -> None:
        if (
            len(list(self.memory.regions_with_tag(RegionTag.DATA))) == 1
            and len(list(self.memory.regions_with_tag(RegionTag.LIT))) == 1
        ):
            return

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
            if (begin, end) == (0, self._orignal_data_length):
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
                self._orignal_data_length,
                self._orignal_data_length + self._original_lit_length,
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
        """Replace calls to old with calls to new.

        The old and new functions can be provided as addresses or names. If they are
        names they will be looked up in self.symbols.

        Returns the number of calls replaced.
        """
        if isinstance(old, str):
            old = self.symbols[old]

        if isinstance(new, str):
            new = self.symbols[new]

        for call in self._calls[old]:
            self.instructions[call].operand = new

        return len(self._calls[old])
