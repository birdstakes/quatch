# Quatch

Quatch is a Python library for patching Quake 3 virtual machine programs.

## Installation

Users:

```bash
git clone https://github.com/birdstakes/quatch.git
pip install ./quatch
```

Developers:

```bash
git clone https://github.com/birdstakes/quatch.git
cd quatch
pip install -e .
pip install pre-commit
pre-commit install
```

## Usage

Quatch uses the lcc compiler to compile C code. It can be found in the Quake 3 SDK or
built from the Quake 3 source code. You can either set the `LCC` environment variable
to the path of the lcc executable, or you can make sure it is in your `PATH` or the
current working directory.

```python
import quatch

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

## License

GPLv2+
