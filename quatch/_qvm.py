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
from typing import Any, List, NamedTuple, Optional, Union
from ._compile import compile_c_file, CompilerError
from ._instruction import assemble, disassemble, Instruction as Ins, Opcode as Op
from ._memory import Memory, RegionTag
from ._q3asm import Assembler, AssemblerError, Segment
from ._util import crc32, forge_crc32, pad


STACK_SIZE = 0x10000
HEADER_FORMAT = "<IIIIIIII"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)


class CompilationResult(NamedTuple):
    output: str
    segments: dict[str, Segment]


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

    def __init__(
        self,
        path: str,
        code_symbols: Mapping[str, int] = None,
        data_symbols: Mapping[str, int] = None,
    ) -> None:
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
                self._original_data_length,
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
            self.add_data(f.read(self._original_data_length))
            self.add_lit(f.read(self._original_lit_length))
            self.add_bss(bss_length)

            f.seek(0)
            self._original_crc = crc32(f.read())

        self.symbols = {}
        if code_symbols:
            for name, value in code_symbols.items():
                self.symbols[name] = {"value": value, "type": "code"}
        if data_symbols:
            for name, value in data_symbols.items():
                if name in self.symbols:
                    raise ValueError(f"Symbol {name} already defined")
                self.symbols[name] = {"value": value, "type": "data"}

        self._calls = collections.defaultdict(list)
        for i in range(len(self.instructions) - 1):
            first, second = self.instructions[i : i + 2]
            if first.opcode == Op.CONST and second.opcode == Op.CALL:
                self._calls[first.operand].append(i)

        self.local_symbols = {}

    def write(
        self, path: str, map_path: Optional[str] = None, forge_crc: bool = False
    ) -> None:
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
                self.memory[: self._original_data_length + self._original_lit_length]
            )

            bss_length = (
                len(self.memory)
                - self._original_data_length
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
                    self._original_data_length,
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

        if not map_path:
            return
        with open(map_path, "w") as f:
            for name, sym in self.symbols.items():
                if name.startswith("$"):
                    continue
                value = sym["value"] & 0xFFFFFFFF
                f.write(f"{0 if sym['type'] == 'code' else 1} {value:8x} {name}\n")

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
        **kwargs: Optional[Any],
    ) -> CompilationResult:
        """Compile a string of C code and add it to the Qvm.

        See add_c_files for other arguments.
        """
        c_file = tempfile.NamedTemporaryFile(suffix=".c", delete=False)
        try:
            c_file.write(code.encode())

            # this must be closed on windows or lcc won't be able to open it
            c_file.close()

            return self.add_c_file(c_file.name, **kwargs)
        finally:
            c_file.close()
            with contextlib.suppress(FileNotFoundError):
                os.remove(c_file.name)

    def add_c_file(
        self,
        path: str,
        **kwargs: Optional[Any],
    ) -> CompilationResult:
        """Compile a C file and add the code to the Qvm.

        See add_c_files for other arguments.
        """
        return self.add_c_files([path], **kwargs)

    def my_add_c_files(
        self,
        paths: Iterable[str],
        include_dirs: Optional[Iterable[str]] = None,
        additional_cflags: Optional[List[str]] = None,
        suppress_missing_symbols: Optional[bool] = False,
        dump_stack: Optional[bool] = False,
    ) -> CompilationResult:
        """Compile C files and add the code to the Qvm.

        Additional search paths for include files can be specified in include_dirs.

        Compilation errors will cause a CompilerError exception to be raised with the
        error message.

        Returns a CompilationResult with the compiler's standard output/error and
        segments containing the compiled code and data.
        """
        asm_files = []
        output = []

        try:
            for (path, *rest) in paths:
                asm_file = tempfile.NamedTemporaryFile(suffix=".asm", delete=False)
                asm_files.append((asm_file, *rest))

                # this must be closed on windows or lcc won't be able to open it
                asm_file.close()
                if dump_stack:
                    if additional_cflags:
                        additional_cflags += ["-Wf-dump-stack"]
                    else:
                        additional_cflags = ["-Wf-dump-stack"]
                output.append(
                    compile_c_file(
                        path,
                        asm_file.name,
                        include_dirs=include_dirs,
                        additional_args=additional_cflags,
                    )
                )

            self.memory.align(4)

            assembler = Assembler(suppress_missing_symbols)
            file_segments, symbols = assembler.my_assemble(
                [(asm_file.name, *rest) for (asm_file, *rest) in asm_files],
                symbols=self.symbols,
            )
            self.local_symbols.update(assembler.local_symbols)

            for segments in file_segments:
                code_base = segments["code"].segment_base
                code_data = segments["code"].image
                self.instructions[code_base : code_base + len(code_data)] = code_data

                for region in ("data", "lit", "bss"):
                    segment = segments[region]
                    segment_base, segment_data = segment.segment_base, segment.image
                    self.memory[
                        segment_base : segment_base + len(segment_data)
                    ] = segment_data

            self.symbols.update(symbols)
            return [CompilationResult(i, x) for i, x in zip(output, file_segments)]

        except AssemblerError as e:
            raise CompilerError(str(e)) from None

        finally:
            for (asm_file, *rest) in asm_files:
                asm_file.close()
                with contextlib.suppress(FileNotFoundError):
                    os.remove(asm_file.name)

    def add_c_files(
        self,
        paths: Iterable[str],
        include_dirs: Optional[Iterable[str]] = None,
        code_base: Optional[int] = None,
        data_base: Optional[int] = None,
        bss_base: Optional[int] = None,
        lit_base: Optional[int] = None,
        pad_segments: Optional[bool] = True,
    ) -> CompilationResult:
        """Compile C files and add the code to the Qvm.

        Additional search paths for include files can be specified in include_dirs.

        Compilation errors will cause a CompilerError exception to be raised with the
        error message.

        Returns a CompilationResult with the compiler's standard output/error and
        segments containing the compiled code and data.
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
                code_base=code_base
                if code_base is not None
                else len(self.instructions),
                data_base=data_base if data_base is not None else len(self.memory),
                lit_base=lit_base,
                bss_base=bss_base,
                pad_segments=pad_segments,
                symbols=self.symbols,
            )

            if code_base is not None:
                self.instructions[
                    code_base : code_base + len(instructions)
                ] = instructions
            else:
                self.instructions.extend(instructions)

            data = segments["data"].image
            if data_base is not None:
                self.memory[data_base : data_base + len(data)] = data
            else:
                self.add_data(data)

            lit = segments["lit"].image
            if lit_base is not None:
                self.memory[lit_base : lit_base + len(lit)] = lit
            else:
                self.add_lit(lit)

            bss = segments["bss"].image
            if bss_base is not None:
                self.memory[bss_base : bss_base + len(bss)] = bss
            else:
                self.add_bss(len(bss))

            self.symbols.update(symbols)
            return CompilationResult(output, instructions, segments)

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
                original_init = original_init["value"]
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
            if (begin, end) == (0, self._original_data_length):
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
                self._original_data_length,
                self._original_data_length + self._original_lit_length,
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
            old = self.symbols[old]["value"]

        if isinstance(new, str):
            new = self.symbols[new]["value"]

        for call in self._calls[old]:
            self.instructions[call].operand = new

        return len(self._calls[old])
