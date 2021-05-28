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

r"""A Quake 3 VM patching library.

Quatch is a library for reading, modifying, and writing Quake 3 .qvm files.
Its main goal is to make it easy to add new C code to an existing qvm:

    import quatch

    # A symbol for G_InitGame, CG_Init or UI_Init must be provided so quatch can
    # install a hook to initialize any added data.
    # These addresses are for DeFRaG 1.91.27.
    symbols = {
        'G_InitGame': 0x2b7,
        'Com_Printf': 0x446,
    }

    qvm = quatch.Qvm('qagame.qvm', symbols=symbols)

    qvm.add_c_code(r'''
    void G_InitGame(int levelTime, int randomSeed, int restart);
    void Com_Printf(const char *fmt, ...);

    void G_InitGame_hook(int levelTime, int randomSeed, int restart) {
        G_InitGame(levelTime, randomSeed, restart);
        Com_Printf("^1Hooked\n");
    }
    ''')

    qvm.replace_calls('G_InitGame', 'G_InitGame_hook')
    qvm.write('patched_qagame.qvm')

If more control is needed, code and data can be added and changed manually. See the Qvm
and Instruction classes for more information.
"""

from ._instruction import assemble, disassemble, Instruction, Opcode
from ._qvm import CompilerError, InitSymbolError, Qvm

__all__ = [
    "assemble",
    "disassemble",
    "CompilerError",
    "InitSymbolError",
    "Instruction",
    "Opcode",
    "Qvm",
]
