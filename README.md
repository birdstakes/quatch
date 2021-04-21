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

```python
import quatch

symbols = {
    'G_InitGame': 0x2b7,
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
