# Quatch

Quatch is a Python library for patching Quake 3 virtual machine programs.

## Installation

```bash
python -m pip install git+https://github.com/birdstakes/quatch.git
```

## Usage

Quatch's main goal is to make it easy to add new C code to an existing qvm:

```python
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
```
