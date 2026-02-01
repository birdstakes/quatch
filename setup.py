import os
import subprocess
import sys
from glob import glob
from setuptools import setup, Extension
from setuptools.command.build_ext import build_ext as _build_ext

# This abuses build_ext to build executables instead of extension modules because it
# already does most of what we need and a bunch of things (bdist_* commands, for
# instance) seem to assume binary extensions are the only way you can end up with a
# platform-specific binary distribution.

WINDOWS = sys.platform == "win32"

lburg = Extension(
    "quatch.bin.lburg",
    glob("lcc/lburg/*.c"),
)

cpp = Extension(
    "quatch.bin.q3cpp",
    glob("lcc/cpp/*.c"),
)

lcc = Extension(
    "quatch.bin.q3lcc",
    glob("lcc/etc/*.c"),
)

rcc = Extension(
    "quatch.bin.q3rcc",
    glob("lcc/src/*.c") + glob("lcc/src/*.md"),
    include_dirs=["lcc/src"],
)


class build_ext(_build_ext):
    def run(self):
        from distutils.ccompiler import new_compiler, CCompiler
        from distutils.sysconfig import customize_compiler

        compiler = new_compiler(
            compiler=self.compiler,
            verbose=self.verbose,
            dry_run=self.dry_run,
            force=self.force,
        )
        customize_compiler(compiler)

        macros = [("WIN32", None)] if WINDOWS else []

        for ext in self.extensions:
            sources = []
            for source in ext.sources:
                _, suffix = os.path.splitext(source)
                if suffix == ".md":
                    sources.append(self.lburg(source))
                else:
                    sources.append(source)

            objects = compiler.compile(
                sources,
                macros=macros + ext.define_macros,
                include_dirs=ext.include_dirs,
                output_dir=self.build_temp,
            )

            # using compiler.link_executable duplicates the file extension on windows
            compiler.link(
                CCompiler.EXECUTABLE, objects, self.get_ext_fullpath(ext.name)
            )

    def lburg(self, source):
        name, _ = os.path.splitext(source)
        output = os.path.join(self.build_temp, name + ".c")
        os.makedirs(os.path.dirname(output), exist_ok=True)
        subprocess.run(
            [
                self.get_ext_fullpath(lburg.name),
                source,
                output,
            ]
        )
        return output

    def get_ext_filename(self, ext_name):
        suffix = ".exe" if WINDOWS else ""
        return os.path.join(*ext_name.split(".")) + suffix


cmdclass = {"build_ext": build_ext}

try:
    from wheel.bdist_wheel import bdist_wheel as _bdist_wheel

    class bdist_wheel(_bdist_wheel):
        def get_tag(self):
            if "WINDOWS_HACK" in os.environ:
                # if everything is compiled with mingw32 the wheel should work
                # with any windows version of python
                return "py3", "none", "win32.win_amd64"
            else:
                return super().get_tag()

    cmdclass["bdist_wheel"] = bdist_wheel
except ImportError:
    pass

setup(
    cmdclass=cmdclass,
    ext_modules=[
        lburg,
        cpp,
        lcc,
        rcc,
    ],
)
