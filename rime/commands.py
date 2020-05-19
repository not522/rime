import os
import os.path
import re
import shutil
import time

from rime import codes
from rime import consts
from rime import taskgraph
from rime import test_summary
from rime.util import files


class ParseError(Exception):
    pass


class OptionEntry(object):
    def __init__(self, shortname, longname, varname, argtype, argdef, argname,
                 description):
        assert argtype in (bool, int, str)
        assert isinstance(argdef, argtype)
        self.shortname = shortname
        self.longname = longname
        self.varname = varname
        self.argtype = argtype
        self.argdef = argdef
        self.argname = argname
        self.description = description

    def Match(self, name):
        return (name in (self.shortname, self.longname))


class Command(object):
    name = None
    description = None

    def __init__(self, parent):
        self.parent = parent

    def FindOptionEntry(self, name):
        raise NotImplementedError()

    def GetDefaultOptionDict(self):
        raise NotImplementedError()

    def PrintHelp(self, ui):
        raise NotImplementedError()

    def Run(self, project, args, ui):
        raise NotImplementedError()


class CommandBase(Command):
    def __init__(self, name, args, oneline_summary, description, parent):
        super(CommandBase, self).__init__(parent)
        self.name = name
        self.args = args
        self.oneline_summary = oneline_summary
        self.description = description
        self.options = []

    def AddOptionEntry(self, option):
        self.options.append(option)

    def FindOptionEntry(self, name):
        for option in self.options:
            if option.Match(name):
                return option
        if self.parent:
            return self.parent.FindOptionEntry(name)
        return None

    def GetDefaultOptionDict(self):
        if self.parent:
            options = self.parent.GetDefaultOptionDict()
        else:
            options = {}
        for option in self.options:
            assert option.varname not in options
            options[option.varname] = option.argdef
        return options

    def PrintHelp(self, ui):
        ui.console.Print('rime.py %s [<options>...] %s' %
                         (self.name or '<command>', self.args or
                          '[<args>...]'))
        ui.console.Print()
        self._PrintCommandDescription(ui)
        if self.name:
            ui.console.Print('Options for "%s":' % self.name)
            ui.console.Print()
            self._PrintOptionDescription(ui)
        ui.console.Print('Global options:')
        ui.console.Print()
        ui.commands[None]._PrintOptionDescription(ui)

    def _PrintCommandDescription(self, ui):
        if self.oneline_summary:
            ui.console.Print(self.oneline_summary)
            ui.console.Print()
        if self.description:
            for line in self.description.splitlines():
                ui.console.Print('    ' + line)
            ui.console.Print()

        if not self.name:
            rows = []
            values = filter(lambda a: a.name, ui.commands.values())
            for cmd in sorted(values, key=lambda a: a.name):
                rows.append((' %s    ' % cmd.name, cmd.oneline_summary))

            offset = max([len(left_col) for left_col, _ in rows])

            ui.console.Print('Commands:')
            ui.console.Print()
            for left_col, right_col in rows:
                ui.console.Print(left_col.ljust(offset) + right_col)
            ui.console.Print()

    def _PrintOptionDescription(self, ui):
        rows = []
        for option in sorted(self.options, key=lambda a: a.longname):
            longopt = '--%s' % option.longname
            if option.argname:
                longopt += ' <%s>' % option.argname
            if option.shortname:
                left_col_head = ' -%s, %s  ' % (option.shortname, longopt)
            else:
                left_col_head = '     %s  ' % longopt
            rows.append((left_col_head, option.description.splitlines()))
        if not rows:
            ui.console.Print(' No options.')
        else:
            offset = max([len(left_col) for left_col, _ in rows])
            for left_col_head, right_col_lines in rows:
                for i, right_col_line in enumerate(right_col_lines):
                    left_col_line = (i == 0 and left_col_head or '').ljust(
                        offset)
                    ui.console.Print(left_col_line + right_col_line)
        ui.console.Print()


def get_commands():
    default = Default(None)
    commands = {}
    commands[None] = default
    commands['build'] = Build(default)
    commands['test'] = Test(default)
    commands['pack'] = Pack(default)
    commands['upload'] = Upload(default)
    commands['submit'] = Submit(default)
    commands['add'] = Add(default)
    commands['wikify'] = Wikify(default)
    commands['wikify_full'] = WikifyFull(default)
    commands['htmlify_full'] = HtmlifyFull(default)
    commands['clean'] = Clean(default)
    commands['help'] = Help(default)
    return commands


def Parse(argv, commands):
    """Parses the command line arguments.

    Arguments:
      argv: A list of string passed to the command.
          Note that this should include sys.argv[0] as well.

    Returns:
      A tuple of (cmd_name, extra_args, options) where:
        cmd: Command object of the main command specified by the command line.
        extra_args: A list of extra arguments given to the command.
        options: Dictionary containing option arguments.

    Raises:
      ParseError: When failed to parse arguments.
    """
    default = commands[None]
    cmd = None
    extra_args = []
    options = default.GetDefaultOptionDict()

    assert len(argv) >= 1
    i = 1
    option_finished = False

    while i < len(argv):
        arg = argv[i]
        i += 1

        if option_finished or not arg.startswith('-'):
            if cmd is None:
                arg = arg.lower()

                if arg not in commands:
                    raise ParseError('Unknown command: %s' % arg)
                cmd = commands[arg]
                options.update(cmd.GetDefaultOptionDict())

            else:
                extra_args.append(arg)

        else:
            longopt = arg.startswith('--')
            optvalue = None

            if longopt:
                optname = arg[2:]
                if optname == '':
                    option_finished = True
                    continue
                if '=' in optname:
                    sep = optname.find('=')
                    optvalue = optname[sep + 1:]
                    optname = optname[:sep]
                optnames = [optname]

            else:
                optnames = arg[1:]

            for optname in optnames:
                optfull = '%s%s' % (longopt and '--' or '-', optname)

                option = (cmd and cmd.FindOptionEntry(optname) or
                          default.FindOptionEntry(optname))
                if option is None:
                    raise ParseError('Unknown option: %s' % optfull)

                if option.argtype is bool:
                    optvalue = True
                elif optvalue is None:
                    if i == len(argv):
                        raise ParseError(
                            'Option parameter was missing for %s' % optfull)
                    optvalue = argv[i]
                    i += 1

                try:
                    optvalue = option.argtype(optvalue)
                except Exception:
                    raise ParseError(
                        'Invalid option parameter for %s' % optfull)

                options[option.varname] = optvalue

    if cmd is None:
        cmd = commands[None]
        options['help'] = True

    return (cmd, extra_args, options)


# Register the root command and global options.
class Default(CommandBase):
    def __init__(self, parent):
        assert parent is None
        super(Default, self).__init__(
            None, None, '', consts.GLOBAL_HELP, parent)
        self.AddOptionEntry(OptionEntry(
            'h', 'help', 'help', bool, False, None,
            'Show this help.'))
        self.AddOptionEntry(OptionEntry(
            'j', 'jobs', 'parallelism', int, 0, 'n',
            'Run multiple jobs in parallel.'))
        self.AddOptionEntry(OptionEntry(
            'd', 'debug', 'debug', bool, False, None,
            'Turn on debugging.'))
        self.AddOptionEntry(OptionEntry(
            'C', 'cache_tests', 'cache_tests', bool, False, None,
            'Cache test results.'))
        self.AddOptionEntry(OptionEntry(
            'p', 'precise', 'precise', bool, False, None,
            'Do not run timing tasks concurrently.'))
        self.AddOptionEntry(OptionEntry(
            'k', 'keep_going', 'keep_going', bool, False, None,
            'Do not skip tests on failures.'))
        self.AddOptionEntry(OptionEntry(
            'q', 'quiet', 'quiet', bool, False, None,
            'Skip unimportant message.'))
        self.AddOptionEntry(OptionEntry(
            'r', 'rel_out_dir', 'rel_out_dir', str, "-", "rel_path",
            'Specify the relative path of the directory'
            'where rime-out\'s are put.'))
        self.AddOptionEntry(OptionEntry(
            'a', 'abs_out_dir', 'abs_out_dir', str, "-", "abs_path",
            'Specify the absolute path of the directory'
            'where rime-out\'s are put.'))


def RunCommon(method_name, project, args, ui):
    if args:
        base_dir = os.path.abspath(args[0])
        args = args[1:]
    else:
        base_dir = os.getcwd()

    obj = project.FindByBaseDir(base_dir)
    if not obj:
        ui.errors.Error(None,
                        'Target directory is missing or not managed by Rime.')
        return None

    if args:
        ui.errors.Error(None,
                        'Extra argument passed to %s command!' % method_name)
        return None

    return getattr(obj, method_name)(ui)


class Build(CommandBase):
    def __init__(self, parent):
        super(Build, self).__init__(
            'build',
            '[<target>]',
            'Build a target and its dependencies.',
            consts.BUILD_HELP,
            parent)

    def Run(self, project, args, ui):
        return RunCommon('Build', project, args, ui)


class Test(CommandBase):
    def __init__(self, parent):
        super(Test, self).__init__(
            'test',
            '[<target>]',
            'Run tests in a target.',
            consts.TEST_HELP,
            parent)

    def Run(self, project, args, ui):
        task = RunCommon('Test', project, args, ui)
        if not task:
            return task

        @taskgraph.task_method
        def TestWrapper():
            results = yield task
            test_summary.PrintTestSummary(results, ui)
            yield results
        return TestWrapper()


class PackerBase(object):
    @taskgraph.task_method
    def Pack(self, ui, testset):
        raise NotImplementedError()


class UploaderBase(object):
    @taskgraph.task_method
    def Upload(self, ui, problem, dryrun):
        raise NotImplementedError()


class SubmitterBase(object):
    @taskgraph.task_method
    def Submit(self, ui, solution):
        raise NotImplementedError()


class Pack(CommandBase):
    def __init__(self, parent):
        super(Pack, self).__init__(
            'pack',
            '[<target>]',
            'Pack testsets to export to online judges.',
            '',
            parent)

    def Run(self, project, args, ui):
        return RunCommon('Pack', project, args, ui)


class Upload(CommandBase):
    def __init__(self, parent):
        super(Upload, self).__init__(
            'upload',
            '[<target>]',
            'Upload testsets to export to online judges.',
            '',
            parent)

        self.AddOptionEntry(OptionEntry(
            'u', 'upload', 'upload', bool, False, None,
            'Without this option, just dry-run.'))

    def Run(self, project, args, ui):
        return RunCommon('Upload', project, args, ui)


class Submit(CommandBase):
    def __init__(self, parent):
        super(Submit, self).__init__(
            'submit',
            '[<target>]',
            'Submit solutions to online judges.',
            '',
            parent)

    def Run(self, project, args, ui):
        return RunCommon('Submit', project, args, ui)


def Run(method_name, project, args, ui):
    if args:
        base_dir = os.path.abspath(args[0])
        args = args[1:]
    else:
        base_dir = os.getcwd()

    obj = project.FindByBaseDir(base_dir)
    if not obj:
        ui.errors.Error(None,
                        'Target directory is missing or not managed by Rime.')
        return None

    return getattr(obj, method_name)(args, ui)


class Add(CommandBase):
    def __init__(self, parent):
        super(Add, self).__init__(
            'add',
            '[<parent target> <child type> <child dir>]',
            'Add a new target directory.',
            '',
            parent)

    def Run(self, project, args, ui):
        return Run('Add', project, args, ui)


class Wikify(CommandBase):
    def __init__(self, parent):
        super(Wikify, self).__init__(
            'wikify',
            '',
            'Upload test results to Pukiwiki.',
            '',
            parent)
        self.AddOptionEntry(OptionEntry(
            's', 'skip_clean', 'skip_clean', bool, False, None,
            'Skip cleaning generated files up.'
        ))

    def Run(self, obj, args, ui):
        if args:
            ui.console.PrintError('Extra argument passed to wikify command!')
            return None

        if obj.parent is None:
            return obj.Wikify(ui)

        ui.console.PrintError(
            'Wikify is not supported for the specified target.')
        return None


class WikifyFull(CommandBase):
    def __init__(self, parent):
        super(WikifyFull, self).__init__(
            'wikify_full',
            '',
            'Upload all test results to Pukiwiki.',
            '',
            parent)
        self.AddOptionEntry(OptionEntry(
            's', 'skip_clean', 'skip_clean', bool, False, None,
            'Skip cleaning generated files up.'
        ))

    def Run(self, obj, args, ui):
        if args:
            ui.console.PrintError(
                'Extra argument passed to wikify_full command!')
            return None

        if obj.parent is None:
            return obj.WikifyFull(ui)

        ui.console.PrintError(
            'Wikify_full is not supported for the specified target.')
        return None


class HtmlifyFull(CommandBase):
    def __init__(self, parent):
        super(HtmlifyFull, self).__init__(
            'htmlify_full',
            '',
            'Local version of htmlify_full.',
            '',
            parent)
        self.AddOptionEntry(OptionEntry(
            's', 'skip_clean', 'skip_clean', bool, False, None,
            'Skip cleaning generated files up.'
        ))

    def Run(self, obj, args, ui):
        if args:
            ui.console.PrintError(
                'Extra argument passed to htmlify_full command!')
            return None

        if obj.parent is None:
            return obj.HtmlifyFull(ui)

        ui.console.PrintError(
            'Htmlify_full is not supported for the specified target.')
        return None


class AOJPacker(PackerBase):
    @taskgraph.task_method
    def Pack(self, ui, testset):
        testcases = testset.ListTestCases()
        try:
            files.RemoveTree(testset.aoj_pack_dir)
            files.MakeDir(testset.aoj_pack_dir)
        except Exception:
            ui.errors.Exception(testset)
            yield False
        for (i, testcase) in enumerate(testcases):
            basename = os.path.splitext(testcase.infile)[0]
            difffile = basename + consts.DIFF_EXT
            packed_infile = 'in' + str(i + 1) + '.txt'
            packed_difffile = 'out' + str(i + 1) + '.txt'
            try:
                ui.console.PrintAction(
                    'PACK',
                    testset,
                    '%s -> %s' % (os.path.basename(testcase.infile),
                                  packed_infile),
                    progress=True)
                files.CopyFile(os.path.join(testset.out_dir, testcase.infile),
                               os.path.join(testset.aoj_pack_dir,
                                            packed_infile))
                ui.console.PrintAction(
                    'PACK',
                    testset,
                    '%s -> %s' % (os.path.basename(difffile), packed_difffile),
                    progress=True)
                files.CopyFile(os.path.join(testset.out_dir, difffile),
                               os.path.join(testset.aoj_pack_dir,
                                            packed_difffile))
            except Exception:
                ui.errors.Exception(testset)
                yield False

        # case.txt
        files.WriteFile(str(len(testcases)),
                        os.path.join(testset.aoj_pack_dir, 'case.txt'))

        # build.sh
        # TODO(mizuno): reactive
        checker = testset.judges[0]
        if (len(testset.judges) == 1 and
                not isinstance(checker, codes.InternalDiffCode)):
            ui.console.PrintAction(
                'PACK', testset, 'checker files', progress=True)
            files.CopyFile(os.path.join(testset.src_dir, checker.src_name),
                           os.path.join(testset.aoj_pack_dir, 'checker.cpp'))
            for f in checker.dependency:
                files.CopyFile(os.path.join(testset.project.library_dir, f),
                               os.path.join(testset.aoj_pack_dir, f))
            files.WriteFile(
                '#!/bin/bash\ng++ -o checker -std=c++11 checker.cpp',
                os.path.join(testset.aoj_pack_dir, 'build.sh'))
        elif len(testset.judges) > 1:
            ui.errors.Error(
                testset, "Multiple output checker is not supported!")
            yield False

        # AOJCONF
        aoj_conf = '''\
# Problem ID
PROBLEM_ID = '*'

# Judge type
#   'diff-validator' for a problem without special judge
#   'float-validator' for a problem with floating point validator
#   'special-validator' for a problem with special validator
#   'reactive' for a reactive problem
{0}

# Language of problem description
#   'ja', 'en' or 'ja-en'
DOCUMENT_TYPE = '*'

# Title of the problem
TITLE = '{1}'

# Time limit (integer, in seconds)
TIME_LIMIT = 1

# Memory limit (integer, in KB)
MEMORY_LIMIT = 32768

# Date when the problem description will be able to be seen
PUBLICATION_DATE = datetime.datetime(*, *, *, *, *)
'''
        if not isinstance(checker, codes.InternalDiffCode):
            files.WriteFile(
                aoj_conf.format(
                    'JUDGE_TYPE = \'special-validator\'',
                    testset.problem.title),
                os.path.join(testset.aoj_pack_dir, 'AOJCONF'))
        else:
            files.WriteFile(
                aoj_conf.format(
                    'JUDGE_TYPE = \'diff-validator\'', testset.problem.title),
                os.path.join(testset.aoj_pack_dir, 'AOJCONF'))

        yield True


class AtCoderPacker(PackerBase):
    @taskgraph.task_method
    def Pack(self, ui, testset):
        testcases = testset.ListTestCases()
        try:
            files.RemoveTree(testset.atcoder_pack_dir)
            files.MakeDir(testset.atcoder_pack_dir)
            files.MakeDir(os.path.join(testset.atcoder_pack_dir, 'in'))
            files.MakeDir(os.path.join(testset.atcoder_pack_dir, 'out'))
            files.MakeDir(os.path.join(testset.atcoder_pack_dir, 'etc'))
        except Exception:
            ui.errors.Exception(testset)
            yield False
        for (i, testcase) in enumerate(testcases):
            basename = os.path.splitext(testcase.infile)[0]
            difffile = basename + consts.DIFF_EXT
            packed_infile = os.path.join('in', os.path.basename(basename))
            packed_difffile = os.path.join('out', os.path.basename(basename))
            try:
                ui.console.PrintAction(
                    'PACK',
                    testset,
                    '%s -> %s' % (os.path.basename(testcase.infile),
                                  packed_infile),
                    progress=True)
                files.CopyFile(os.path.join(testset.out_dir, testcase.infile),
                               os.path.join(testset.atcoder_pack_dir,
                                            packed_infile))
                ui.console.PrintAction(
                    'PACK',
                    testset,
                    '%s -> %s' % (os.path.basename(difffile), packed_difffile),
                    progress=True)
                files.CopyFile(os.path.join(testset.out_dir, difffile),
                               os.path.join(testset.atcoder_pack_dir,
                                            packed_difffile))
            except Exception:
                ui.errors.Exception(testset)
                yield False

        # checker
        checker = testset.judges[0]
        if (len(testset.judges) == 1 and
                not isinstance(checker, codes.InternalDiffCode)):
            ui.console.PrintAction(
                'PACK', testset, 'output checker files', progress=True)
            files.CopyFile(
                os.path.join(testset.src_dir, checker.src_name),
                os.path.join(testset.atcoder_pack_dir, 'etc',
                             'output_checker.cpp'))
            for f in checker.dependency:
                files.CopyFile(os.path.join(testset.project.library_dir, f),
                               os.path.join(testset.atcoder_pack_dir, 'etc',
                                            f))
        elif len(testset.judges) > 1:
            ui.errors.Error(
                testset, "Multiple output checker is not supported!")
            yield False

        # reactive
        if len(testset.reactives) == 1:
            reactive = testset.reactives[0]
            ui.console.PrintAction(
                'PACK', testset, 'reactive checker files', progress=True)
            files.CopyFile(
                os.path.join(testset.src_dir, reactive.src_name),
                os.path.join(testset.atcoder_pack_dir, 'etc', 'reactive.cpp'))
            for f in reactive.dependency:
                files.CopyFile(os.path.join(testset.project.library_dir, f),
                               os.path.join(testset.atcoder_pack_dir, 'etc',
                                            f))
            # outは使わない
            files.RemoveTree(os.path.join(testset.atcoder_pack_dir, 'out'))
        elif len(testset.judges) > 1:
            ui.errors.Error(
                testset, "Multiple reactive checker is not supported!")
            yield False

        # score.txt
        subtasks = testset.subtask_testcases
        if len(subtasks) > 0:
            score = '\n'.join([
                s.name + '(' + str(s.score) + ')' + ': ' +
                ','.join(s.input_patterns)
                for s in subtasks])
        else:
            score = 'All(100): *'
        files.WriteFile(
            score, os.path.join(testset.atcoder_pack_dir, 'etc', 'score.txt'))

        yield True


class HackerRankPacker(PackerBase):
    @taskgraph.task_method
    def Pack(self, ui, testset):
        testcases = testset.ListTestCases()
        try:
            files.RemoveTree(testset.pack_dir)
            files.MakeDir(testset.pack_dir)
            files.MakeDir(os.path.join(testset.pack_dir, 'input'))
            files.MakeDir(os.path.join(testset.pack_dir, 'output'))
        except Exception:
            ui.errors.Exception(testset)
            yield False
        template_packed_infile = 'input{:d}.txt'
        template_packed_difffile = 'output{:d}.txt'
        for i, testcase in enumerate(testcases):
            basename = os.path.splitext(testcase.infile)[0]
            difffile = basename + consts.DIFF_EXT
            packed_infile = template_packed_infile.format(i)
            packed_difffile = template_packed_difffile.format(i)
            try:
                ui.console.PrintAction(
                    'PACK',
                    testset,
                    '%s -> input/%s' % (os.path.basename(testcase.infile),
                                        packed_infile),
                    progress=True)
                files.CopyFile(os.path.join(testset.out_dir, testcase.infile),
                               os.path.join(testset.pack_dir,
                                            'input',
                                            packed_infile))
                ui.console.PrintAction(
                    'PACK',
                    testset,
                    '%s -> output/%s' % (os.path.basename(difffile),
                                         packed_difffile),
                    progress=True)
                files.CopyFile(os.path.join(testset.out_dir, difffile),
                               os.path.join(testset.pack_dir,
                                            'output',
                                            packed_difffile))
            except Exception:
                ui.errors.Exception(testset)
                yield False

        # hacker_rank.zip
        try:
            shutil.make_archive(
                os.path.join(testset.pack_dir, 'hacker_rank'),
                'zip',
                os.path.join(testset.pack_dir))
            ui.console.PrintAction(
                'PACK', testset, 'zipped to hacker_rank.zip', progress=True)
        except Exception:
            ui.errors.Exception(testset)
            yield False

        yield True


class AtCoderUploader(UploaderBase):
    @taskgraph.task_method
    def Upload(self, ui, problem, dryrun):
        if problem.project.judge_system.name != 'AtCoder':
            ui.errors.Error(
                problem, 'judge_system is not defined in project.json.')
            yield False

        if problem.atcoder_task_id is None:
            ui.console.PrintAction(
                'UPLOAD', problem,
                'This problem is considered to a spare. Not uploaded.')
            yield True

        script = os.path.join(problem.project.judge_system.upload_script)
        if not os.path.exists(os.path.join(problem.project.base_dir, script)):
            ui.errors.Error(problem, script + ' is not found.')
            yield False

        stmp = files.ReadFile(script)
        if not stmp.startswith('#!/usr/bin/php'):
            ui.errors.Error(problem, script + ' is not an upload script.')
            yield False

        log = os.path.join(problem.out_dir, 'upload_log')

        if not dryrun:
            args = ('php', script, str(problem.atcoder_task_id),
                    problem.testset.atcoder_pack_dir)
        else:
            ui.console.PrintWarning('Dry-run mode')
            args = ('echo', 'php', script, str(problem.atcoder_task_id),
                    problem.testset.atcoder_pack_dir)

        ui.console.PrintAction(
            'UPLOAD', problem, ' '.join(args), progress=True)
        devnull = files.OpenNull()

        with open(log, 'a+') as logfile:
            task = taskgraph.ExternalProcessTask(
                args, cwd=problem.project.base_dir,
                stdin=devnull, stdout=logfile, stderr=logfile, exclusive=True)
            try:
                proc = yield task
            except Exception:
                ui.errors.Exception(problem)
                yield False
            ret = proc.returncode
            if ret != 0:
                ui.errors.Error(problem, 'upload failed: ret = %d' % ret)
                yield False
            ui.console.PrintAction(
                'UPLOAD', problem, str(problem.atcoder_task_id))
            yield True


class AtCoderSubmitter(SubmitterBase):
    @taskgraph.task_method
    def Submit(self, ui, solution):
        if solution.project.judge_system.name != 'AtCoder':
            ui.errors.Error(
                solution, 'judge_system is not defined in project.json.')
            yield False

        solution.project._Login()

        task_id = str(solution.problem.atcoder_task_id)
        lang_id = solution.project.judge_system.lang_ids[
            solution.code.PREFIX]
        source_code = files.ReadFile(
            os.path.join(solution.src_dir, solution.code.src_name))

        ui.console.PrintAction(
            'SUBMIT', solution, str({'task_id': task_id, 'lang_id': lang_id}),
            progress=True)

        html = solution.project._Request('submit?task_id=%s' % task_id).read()
        pat = re.compile(r'name="__session" value="([^"]+)"')
        m = pat.search(str(html))
        session = m.group(1)
        r = solution.project._Request('submit?task_id=%s' % task_id, {
            '__session': session,
            'task_id': task_id,
            'language_id_' + task_id: lang_id,
            'source_code': source_code})
        r.read()

        results = solution.project._Request('submissions/me').read()
        submit_id = str(results).split(
            '<td><a href="/submissions/')[1].split('"')[0]

        ui.console.PrintAction(
            'SUBMIT', solution, 'submitted: ' + str(submit_id), progress=True)

        while True:
            result, progress = str(solution.project._Request(
                'submissions/' + submit_id).read()).split(
                'data-title="')[1].split('"', 1)
            if 'Judging' not in result:
                break
            time.sleep(5.0)

        if solution.IsCorrect():
            expected = ''
        else:
            expected = '(fake solution)'
        ui.console.PrintAction(
            'SUBMIT', solution, '{0} {1}'.format(result, expected))

        yield True


class Clean(CommandBase):
    def __init__(self, parent):
        super(Clean, self).__init__(
            'clean',
            '[<target>]',
            'Clean intermediate files.',
            consts.CLEAN_HELP,
            parent)

    def Run(self, project, args, ui):
        return RunCommon('Clean', project, args, ui)


class Help(CommandBase):
    def __init__(self, parent):
        super(Help, self).__init__(
            'help',
            '<command>',
            'Show help.',
            'To see a brief description and available options of a command,'
            'try:\n'
            '\n'
            'rime.py help <command>',
            parent)

    def Run(self, project, args, ui):
        commands = get_commands()
        cmd = None
        if len(args) > 0:
            cmd = commands.get(args[0])
        if not cmd:
            cmd = self
        cmd.PrintHelp(ui)
        return None
