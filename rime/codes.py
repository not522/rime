import optparse
import os
import os.path
import signal
import subprocess

from rime import consts
from rime import task
from rime.util import files


class RunResult(object):
    """Result of a single run.

    Note that this is not judgement result but just execution status.
    """

    OK = 'OK'
    NG = 'Exited Abnormally'
    RE = 'Runtime Error'
    TLE = 'Time Limit Exceeded'

    def __init__(self, status, time):
        self.status = status
        self.time = time


class Code(object):
    """Interface of program codes.

    Supports operations such as compile, run, clean.
    """

    # Set to True if the deriving class does not require compilation
    # (e.g. script language).
    QUIET_COMPILE = False

    # Prefix of exported directive.
    # (e.g. prefix "foo" generates foo_solution, foo_generator, etc.)
    PREFIX = None

    # Extensions of this type of source codes. Used to autodetect code types.
    EXTENSIONS = None

    def __init__(self, src_name, src_dir, out_dir):
        self.src_name = src_name
        self.src_dir = src_dir
        self.out_dir = out_dir

    def Compile(self):
        raise NotImplementedError()

    def Run(self, args, cwd, input, output, timeout, precise,
            redirect_error=False):
        raise NotImplementedError()

    def Clean(self):
        raise NotImplementedError()


class UnknownCodeExtensionException(Exception):
    pass


def get_code(src, src_dir, out_dir, *args, **kwargs):
    src_ext = os.path.splitext(src)[1][1:]
    if src_ext == 'c':
        return CCode(src, src_dir, out_dir, *args, **kwargs)
    if src_ext in ('cc', 'cxx', 'cpp'):
        return CXXCode(src, src_dir, out_dir, *args, **kwargs)
    if src_ext == 'kt':
        return KotlinCode(src, src_dir, out_dir, *args, **kwargs)
    if src_ext == 'java':
        return JavaCode(src, src_dir, out_dir, *args, **kwargs)
    if src_ext == 'rs':
        return RustCode(src, src_dir, out_dir, *args, **kwargs)
    if src_ext == 'js':
        return JavaScriptCode(src, src_dir, out_dir, *args, **kwargs)
    if src_ext == 'hs':
        return HaskellCode(src, src_dir, out_dir, *args, **kwargs)
    if src_ext == 'cs':
        return CsCode(src, src_dir, out_dir, *args, **kwargs)
    return ScriptCode(src, src_dir, out_dir, *args, **kwargs)


class CodeBase(Code):
    """Base class of program codes with various common methods."""

    def __init__(self, src_name, src_dir, out_dir, compile_args, run_args):
        super(CodeBase, self).__init__(src_name, src_dir, out_dir)
        self.log_name = os.path.splitext(src_name)[0] + consts.LOG_EXT
        self.compile_args = tuple(compile_args)
        self.run_args = tuple(run_args)
        self.dependency = []
        self.variant = None

    def Compile(self):
        """Compile the code and return RunResult."""
        try:
            if not self.compile_args:
                result = RunResult(RunResult.OK, None)
            else:
                result = self._ExecForCompile(args=self.compile_args)
        except Exception as e:
            result = RunResult('On compiling: %s' % e, None)
        return result

    def Run(self, args, cwd, input, output, timeout, precise,
            redirect_error=False):
        """Run the code and return RunResult."""
        try:
            result = self._ExecForRun(
                args=tuple(list(self.run_args) + list(args)), cwd=cwd,
                input=input, output=output, timeout=timeout, precise=precise,
                redirect_error=redirect_error)
        except Exception as e:
            result = RunResult('On execution: %s' % e, None)
        return result

    def clean(self):
        """Cleans the output directory.

        Returns an exception object on error.
        """
        try:
            files.RemoveTree(self.out_dir)
        except Exception as e:
            return e
        else:
            return None

    def ReadCompileLog(self):
        return files.ReadFile(os.path.join(self.out_dir, self.log_name))

    def _ExecForCompile(self, args):
        for f in files.ListDir(self.src_dir):
            srcpath = os.path.join(self.src_dir, f)
            dstpath = os.path.join(self.out_dir, f)
            if os.path.isdir(srcpath):
                files.CopyTree(srcpath, dstpath)
            else:
                files.CopyFile(srcpath, dstpath)

        if len(self.dependency) > 0:
            global libdir
            if libdir is None:
                raise IOError('library_dir is not defined.')
            else:
                for f in self.dependency:
                    if not os.path.exists(os.path.join(libdir, f)):
                        raise IOError('%s is not found in %s.' % (f, libdir))
                    files.CopyFile(
                        os.path.join(libdir, f),
                        self.out_dir)

        with open(os.path.join(self.out_dir, self.log_name), 'w') as outfile:
            return self._ExecInternal(
                args=args, cwd=self.out_dir, stdin=files.OpenNull(),
                stdout=outfile, stderr=subprocess.STDOUT)

    def _ExecForRun(self, args, cwd, input, output, timeout, precise,
                    redirect_error=False):
        with open(input, 'r') as infile:
            with open(output, 'w') as outfile:
                if redirect_error:
                    errfile = subprocess.STDOUT
                else:
                    errfile = files.OpenNull()
                return self._ExecInternal(
                    args=args, cwd=cwd,
                    stdin=infile, stdout=outfile, stderr=errfile,
                    timeout=timeout, precise=precise)

    def _ExecInternal(self, args, cwd, stdin, stdout, stderr,
                      timeout=None, precise=False):
        proc, time = task.run_subprocess(
            args, cwd=cwd, stdin=stdin, stdout=stdout, stderr=stderr,
            timeout=timeout)
        code = proc.returncode
        # TODO(mizuno): Retry if TLE.
        if code == 0:
            status = RunResult.OK
        elif code == -(signal.SIGXCPU):
            status = RunResult.TLE
        elif code < 0:
            status = RunResult.RE
        else:
            status = RunResult.NG
        return RunResult(status, time)

    def _ResetIO(self, *args):
        for f in args:
            if f is None:
                continue
            try:
                f.seek(0)
                f.truncate()
            except IOError:
                pass


class CCode(CodeBase):
    PREFIX = 'c'
    EXTENSIONS = ['c']

    def __init__(self, src_name, src_dir, out_dir, flags=['-O2', '-lm'],
                 **kwargs):
        exe_name = os.path.splitext(src_name)[0] + consts.EXE_EXT
        cc = os.getenv('CC', 'gcc')
        super(CCode, self).__init__(
            src_name=src_name, src_dir=src_dir, out_dir=out_dir,
            compile_args=([cc,
                           '-o', os.path.join(out_dir, exe_name),
                           src_name] + list(flags)),
            run_args=[os.path.join(out_dir, exe_name)])


class CXXCode(CodeBase):
    PREFIX = 'cxx'
    EXTENSIONS = ['cc', 'cxx']

    def __init__(self, src_name, src_dir, out_dir,
                 flags=['-std=c++11', '-O2'], **kwargs):
        exe_name = os.path.splitext(src_name)[0] + consts.EXE_EXT
        cxx = os.getenv('CXX', 'g++')
        super(CXXCode, self).__init__(
            src_name=src_name, src_dir=src_dir, out_dir=out_dir,
            compile_args=([cxx,
                           '-o', os.path.join(out_dir, exe_name),
                           src_name] + list(flags)),
            run_args=[os.path.join(out_dir, exe_name)])


class KotlinCode(CodeBase):
    PREFIX = 'kotlin'
    EXTENSIONS = ['kt']

    def __init__(self, src_name, src_dir, out_dir,
                 compile_flags=[], run_flags=[], **kwargs):
        kotlinc = 'kotlinc'
        kotlin = 'kotlin'
        mainclass = os.path.splitext(src_name)[0].capitalize() + 'Kt'
        super(KotlinCode, self).__init__(
            src_name=src_name, src_dir=src_dir, out_dir=out_dir,
            compile_args=([kotlinc, '-d', files.ConvPath(out_dir)] +
                          compile_flags + [src_name]),
            run_args=([kotlin, '-Dline.separator=\n',
                       '-cp', files.ConvPath(out_dir)] +
                      run_flags + [mainclass]))


class JavaCode(CodeBase):
    PREFIX = 'java'
    EXTENSIONS = ['java']

    def __init__(self, src_name, src_dir, out_dir,
                 compile_flags=[], run_flags=[],
                 encoding='UTF-8', mainclass='Main', **kwargs):
        java_home = os.getenv('JAVA_HOME')
        if java_home is not None:
            java = os.path.join(java_home, 'bin/java')
            javac = os.path.join(java_home, 'bin/javac')
        else:
            java = 'java'
            javac = 'javac'
        super(JavaCode, self).__init__(
            src_name=src_name, src_dir=src_dir, out_dir=out_dir,
            compile_args=([javac, '-encoding', encoding,
                           '-d', files.ConvPath(out_dir)] +
                          compile_flags + [src_name]),
            run_args=([java, '-Dline.separator=\n',
                       '-cp', files.ConvPath(out_dir)] +
                      run_flags + [mainclass]))


class RustCode(CodeBase):
    PREFIX = 'rust'
    EXTENSIONS = ['rs']

    def __init__(self, src_name, src_dir, out_dir,
                 flags=['-C', 'opt-level=2'], **kwargs):
        exe_name = os.path.splitext(src_name)[0] + consts.EXE_EXT
        rustc = 'rustc'
        super(RustCode, self).__init__(
            src_name=src_name, src_dir=src_dir, out_dir=out_dir,
            compile_args=([rustc,
                           '-o', os.path.join(out_dir, exe_name),
                           src_name] + list(flags)),
            run_args=[os.path.join(out_dir, exe_name)])


class ScriptCode(CodeBase):
    QUIET_COMPILE = True
    PREFIX = 'script'
    EXTENSIONS = ['sh', 'pl', 'py', 'rb']

    def __init__(self, src_name, src_dir, out_dir, run_flags=[], **kwargs):
        super(ScriptCode, self).__init__(
            src_name=src_name, src_dir=src_dir, out_dir=out_dir,
            compile_args=[],
            run_args=['false', os.path.join(src_dir, src_name)] + run_flags)
        # Replace the executable with the shebang line
        run_args = list(self.run_args)
        try:
            run_args[0] = self._ReadAndParseShebangLine()
            if run_args[0] is not None:
                run_args = run_args[0].split(' ') + run_args[1:]
        except IOError:
            pass
        self.run_args = tuple(run_args)

    def Compile(self, *args, **kwargs):
        """Fail if the script is missing a shebang line."""
        try:
            interpreter = self.run_args[0]
        except IOError:
            return RunResult('File not found', None)
        if not interpreter:
            return RunResult('Script missing a shebang line', None)
        if not os.path.exists(interpreter):
            return RunResult('Interpreter not found: %s' %
                             interpreter, None)

        # when using env, try to output more detailed error message
        if interpreter == '/bin/env' or interpreter == '/usr/bin/env':
            try:
                # if the command does not exist,
                # "which" return 1 as the status code
                interpreter = subprocess.check_output(
                    ['which', self.run_args[1]]).strip()
            except subprocess.CalledProcessError:
                return RunResult(
                    'Interpreter not installed: %s' % self.run_args[1], None)
            if not os.path.exists(interpreter):
                return RunResult('Interpreter not found: %s' %
                                 interpreter, None)

        return CodeBase.Compile(self, *args, **kwargs)

    def _ReadAndParseShebangLine(self):
        with open(os.path.join(self.src_dir, self.src_name)) as f:
            shebang_line = f.readline()
        if not shebang_line.startswith('#!'):
            return None
        return shebang_line[2:].strip()


class JavaScriptCode(CodeBase):
    QUIET_COMPILE = True
    PREFIX = 'js'
    EXTENSIONS = ['js']

    def __init__(self, src_name, src_dir, out_dir, run_flags=[], **kwargs):
        super(JavaScriptCode, self).__init__(
            src_name=src_name, src_dir=src_dir, out_dir=out_dir,
            compile_args=[],
            run_args=['node', '--',
                      os.path.join(src_dir, src_name)] + run_flags)

    def Compile(self, *args, **kwargs):
        """Fail if the script is missing a shebang line."""
        try:
            open(os.path.join(self.src_dir, self.src_name))
        except IOError:
            return RunResult('File not found', None)
        return super(JavaScriptCode, self).Compile(*args, **kwargs)


class HaskellCode(CodeBase):
    PREFIX = 'hs'
    EXTENSIONS = ['hs']

    def __init__(self, src_name, src_dir, out_dir, flags=[], **kwargs):
        exe_name = os.path.splitext(src_name)[0] + consts.EXE_EXT
        exe_path = os.path.join(out_dir, exe_name)
        super(HaskellCode, self).__init__(
            src_name=src_name, src_dir=src_dir, out_dir=out_dir,
            compile_args=(['stack', 'ghc', '--', '-O',
                           '-o', exe_path, '-outputdir', out_dir, src_name] +
                          list(flags)),
            run_args=[exe_path])


class CsCode(CodeBase):
    PREFIX = 'cs'
    EXTENSIONS = ['cs']

    def __init__(self, src_name, src_dir, out_dir, flags=[], **kwargs):
        exe_name = os.path.splitext(src_name)[0] + consts.EXE_EXT
        exe_path = os.path.join(out_dir, exe_name)
        super(CsCode, self).__init__(
            src_name=src_name,
            src_dir=src_dir,
            out_dir=out_dir,
            compile_args=(['mcs',
                           src_name,
                           '-out:' + exe_path] + list(flags)),
            run_args=['mono', exe_path])


class InternalDiffCode(CodeBase):
    QUIET_COMPILE = True

    def __init__(self):
        super(InternalDiffCode, self).__init__(
            src_name='diff',
            src_dir='',
            out_dir='',
            compile_args=[],
            run_args=[])

    def Run(self, args, cwd, input, output, timeout, precise,
            redirect_error=False):
        parser = optparse.OptionParser()
        parser.add_option('-i', '--infile', dest='infile')
        parser.add_option('-d', '--difffile', dest='difffile')
        parser.add_option('-o', '--outfile', dest='outfile')
        options, _ = parser.parse_args([''] + list(args))
        run_args = ('diff', '-u', options.difffile, options.outfile)
        with open(input, 'r') as infile:
            with open(output, 'w') as outfile:
                if redirect_error:
                    errfile = subprocess.STDOUT
                else:
                    errfile = files.OpenNull()
                try:
                    proc, time = task.run_subprocess(
                        run_args, cwd=cwd, stdin=infile, stdout=outfile,
                        stderr=errfile, timeout=timeout)
                except OSError:
                    return RunResult(RunResult.RE, None)
                ret = proc.returncode
                if ret == 0:
                    return RunResult(RunResult.OK, time)
                if ret > 0:
                    return RunResult(RunResult.NG, None)
                return RunResult(RunResult.RE, None)

    def Clean(self):
        return True
