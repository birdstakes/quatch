# Copyright 2021 Josh Steffen
#
# This file is part of Quatch.
#
# Quatch is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# Quatch is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Quatch; If not, see <https://www.gnu.org/licenses/>.

import collections
import contextlib
import os
import shutil
import struct
import subprocess
import tempfile
from . import q3asm
from .instructions import assemble, disassemble, Instruction as Ins, Opcode as Op
from .util import pad


class InitSymbolError(Exception):
    pass


class CompilerError(Exception):
    pass


class Qvm:
    def __init__(self, path, symbols=None):
        with open(path, "rb") as f:
            format = "<IIIIIIII"
            raw_header = f.read(struct.calcsize(format))
            (
                self.vm_magic,
                instruction_count,
                code_offset,
                code_length,
                data_offset,
                self.data_length,
                self.lit_length,
                self.bss_length,
            ) = struct.unpack(format, raw_header)

            self.bss_end = self.data_length + self.lit_length + self.bss_length

            f.seek(code_offset)
            self.instructions = disassemble(f.read(code_length))

            # strip off trailing instructions that are actually just padding
            self.instructions = self.instructions[:instruction_count]

            f.seek(data_offset)
            self.data = f.read(self.data_length + self.lit_length)

        self.symbols = symbols or {}
        self.new_data = bytearray()

        # TODO: what should happen if some of the original instructions are
        # changed, invalidating this?
        self.calls = collections.defaultdict(list)
        for i in range(len(self.instructions) - 1):
            first, second = self.instructions[i : i + 2]
            if first.opcode == Op.CONST and second.opcode == Op.CALL:
                self.calls[first.operand].append(i)

    def write(self, path):
        self._add_data_init_code()

        with open(path, "wb") as f:
            format = "<IIIIIIII"
            header_size = struct.calcsize(format)
            f.seek(header_size)

            code_offset = f.tell()
            code = pad(assemble(self.instructions), 4)
            f.write(code)

            data_offset = f.tell()
            f.write(self.data)

            f.seek(0)
            f.write(
                struct.pack(
                    format,
                    self.vm_magic,
                    len(self.instructions),
                    code_offset,
                    len(code),
                    data_offset,
                    self.data_length,
                    self.lit_length,
                    self.bss_length + len(self.new_data),
                )
            )

    def add_data(self, data, align=4):
        self.new_data = pad(self.new_data, align)
        address = self.bss_end + len(self.new_data)
        self.new_data.extend(data)
        return address

    def add_string(self, string):
        return self.add_data(string.encode() + b"\0", align=1)

    def add_code(self, instructions):
        address = len(self.instructions)
        self.instructions.extend(instructions)
        return address

    def add_c_code(self, c_code, include_dirs=[]):
        path = os.getcwd() + os.pathsep + os.environ.get("PATH", "")
        lcc = (
            os.environ.get("LCC")
            or shutil.which("lcc", path=path)
            or shutil.which("q3lcc", path=path)
        )
        if lcc is None:
            raise FileNotFoundError(
                "Unable to locate lcc. Set the LCC environment variable or make sure "
                "it is in your PATH."
            )

        c_file = tempfile.NamedTemporaryFile(suffix=".c", delete=False)
        asm_file = tempfile.NamedTemporaryFile(suffix=".asm", delete=False)

        try:
            c_file.write(c_code.encode())

            # these must be closed on windows or lcc won't be able to open them
            c_file.close()
            asm_file.close()

            command = [
                lcc,
                "-DQ3_VM",
                "-S",
                "-Wf-target=bytecode",
                "-Wf-g",
            ]
            command += [f"-I{include_dir}" for include_dir in include_dirs]
            command += ["-o", asm_file.name, c_file.name]

            # make sure lcc can find the other executables it needs
            env = os.environ.copy()
            env["PATH"] = (
                os.path.realpath(os.path.dirname(lcc))
                + os.pathsep
                + env.get("PATH", "")
            )

            subprocess.check_output(command, env=env, stderr=subprocess.STDOUT)

            self.new_data = pad(self.new_data, 4)

            assembler = q3asm.Assembler()
            instructions, segments, symbols = assembler.assemble(
                [asm_file.name],
                code_base=len(self.instructions),
                data_base=self.bss_end + len(self.new_data),
                symbols=self.symbols,
            )

            self.instructions.extend(instructions)

            self.add_data(segments["data"].image)
            self.add_data(segments["lit"].image)
            self.add_data(segments["bss"].image)

            self.symbols.update(symbols)

        except subprocess.CalledProcessError as e:
            raise CompilerError(e.output.decode()) from None

        finally:
            c_file.close()
            asm_file.close()
            with contextlib.suppress(FileNotFoundError):
                os.remove(c_file.name)
                os.remove(asm_file.name)

    def _add_data_init_code(self):
        if len(self.new_data) == 0:
            return

        for init_name in ("G_InitGame", "CG_Init", "UI_Init"):
            original_init = self.symbols.get(init_name)
            if original_init is not None:
                break

        if original_init is None:
            raise InitSymbolError(
                "Cannot find a symbol for G_InitGame, CG_Init, or UI_Init"
            )

        if len(self.calls[original_init]) == 0:
            raise InitSymbolError(f"{init_name} is never called")

        # check original_init's first callsite in case it has already been hooked
        original_init_call = self.calls[original_init][0]
        current_init = self.instructions[original_init_call].operand

        init_wrapper = self.add_code([Ins(Op.ENTER, 0x100)])

        self.new_data = pad(self.new_data, 4)
        for i in range(0, len(self.new_data), 4):
            value = struct.unpack("<I", self.new_data[i : i + 4])[0]
            if value != 0:
                self.add_code(
                    [
                        Ins(Op.CONST, self.bss_end + i),
                        Ins(Op.CONST, value),
                        Ins(Op.STORE4),
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

        self.instructions[original_init_call].operand = init_wrapper

    def replace_calls(self, old, new):
        if not isinstance(old, int):
            old = self.symbols[old]

        if not isinstance(new, int):
            new = self.symbols[new]

        for call in self.calls[old]:
            self.instructions[call].operand = new

        return len(self.calls[old])
