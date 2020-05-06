import os
import os.path
import re
import time

from rime.basic import codes as basic_codes
from rime.basic import consts
from rime.basic.targets import project
from rime.basic.targets import problem
from rime.basic.targets import solution
from rime.basic.targets import testset
from rime.basic.util import test_summary
from rime.core import commands
from rime.core import taskgraph
from rime.util import class_registry
from rime.util import files


# Register the root command and global options.
class Default(commands.CommandBase):
    def __init__(self, parent):
        assert parent is None
        super(Default, self).__init__(
            None, None, '', consts.GLOBAL_HELP, parent)
        self.AddOptionEntry(commands.OptionEntry(
            'h', 'help', 'help', bool, False, None,
            'Show this help.'))
        self.AddOptionEntry(commands.OptionEntry(
            'j', 'jobs', 'parallelism', int, 0, 'n',
            'Run multiple jobs in parallel.'))
        self.AddOptionEntry(commands.OptionEntry(
            'd', 'debug', 'debug', bool, False, None,
            'Turn on debugging.'))
        self.AddOptionEntry(commands.OptionEntry(
            'C', 'cache_tests', 'cache_tests', bool, False, None,
            'Cache test results.'))
        self.AddOptionEntry(commands.OptionEntry(
            'p', 'precise', 'precise', bool, False, None,
            'Do not run timing tasks concurrently.'))
        self.AddOptionEntry(commands.OptionEntry(
            'k', 'keep_going', 'keep_going', bool, False, None,
            'Do not skip tests on failures.'))
        self.AddOptionEntry(commands.OptionEntry(
            'q', 'quiet', 'quiet', bool, False, None,
            'Skip unimportant message.'))
        self.AddOptionEntry(commands.OptionEntry(
            'r', 'rel_out_dir', 'rel_out_dir', str, "-", "rel_path",
            'Specify the relative path of the directory'
            'where rime-out\'s are put.'))
        self.AddOptionEntry(commands.OptionEntry(
            'a', 'abs_out_dir', 'abs_out_dir', str, "-", "abs_path",
            'Specify the absolute path of the directory'
            'where rime-out\'s are put.'))


def IsBasicTarget(obj):
    return isinstance(obj, (project.Project,
                            problem.Problem,
                            solution.Solution,
                            testset.Testset))


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

    if not IsBasicTarget(obj):
        ui.errors.Error(
            None, '%s is not supported for the specified target.' %
            method_name)
        return None

    return getattr(obj, method_name)(ui)


class Build(commands.CommandBase):
    def __init__(self, parent):
        super(Build, self).__init__(
            'build',
            '[<target>]',
            'Build a target and its dependencies.',
            consts.BUILD_HELP,
            parent)

    def Run(self, project, args, ui):
        return RunCommon('Build', project, args, ui)


class Test(commands.CommandBase):
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


packer_registry = class_registry.ClassRegistry(PackerBase)
submitter_registry = class_registry.ClassRegistry(SubmitterBase)
uploader_registry = class_registry.ClassRegistry(UploaderBase)


class Pack(commands.CommandBase):
    def __init__(self, parent):
        super(Pack, self).__init__(
            'pack',
            '[<target>]',
            'Pack testsets to export to online judges.',
            '',
            parent)

    def Run(self, project, args, ui):
        return RunCommon('Pack', project, args, ui)


class Upload(commands.CommandBase):
    def __init__(self, parent):
        super(Upload, self).__init__(
            'upload',
            '[<target>]',
            'Upload testsets to export to online judges.',
            '',
            parent)

        self.AddOptionEntry(commands.OptionEntry(
            'u', 'upload', 'upload', bool, False, None,
            'Without this option, just dry-run.'))

    def Run(self, project, args, ui):
        return RunCommon('Upload', project, args, ui)


class Submit(commands.CommandBase):
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


class Add(commands.CommandBase):
    def __init__(self, parent):
        super(Add, self).__init__(
            'add',
            '[<parent target> <child type> <child dir>]',
            'Add a new target directory.',
            '',
            parent)

    def Run(self, project, args, ui):
        return Run('Add', project, args, ui)


class Wikify(commands.CommandBase):
    def __init__(self, parent):
        super(Wikify, self).__init__(
            'wikify',
            '',
            'Upload test results to Pukiwiki.',
            '',
            parent)
        self.AddOptionEntry(commands.OptionEntry(
            's', 'skip_clean', 'skip_clean', bool, False, None,
            'Skip cleaning generated files up.'
        ))

    def Run(self, obj, args, ui):
        if args:
            ui.console.PrintError('Extra argument passed to wikify command!')
            return None

        if isinstance(obj, project.Project):
            return obj.Wikify(ui)

        ui.console.PrintError(
            'Wikify is not supported for the specified target.')
        return None


class WikifyFull(commands.CommandBase):
    def __init__(self, parent):
        super(WikifyFull, self).__init__(
            'wikify_full',
            '',
            'Upload all test results to Pukiwiki.',
            '',
            parent)
        self.AddOptionEntry(commands.OptionEntry(
            's', 'skip_clean', 'skip_clean', bool, False, None,
            'Skip cleaning generated files up.'
        ))

    def Run(self, obj, args, ui):
        if args:
            ui.console.PrintError(
                'Extra argument passed to wikify_full command!')
            return None

        if isinstance(obj, project.Project):
            return obj.WikifyFull(ui)

        ui.console.PrintError(
            'Wikify_full is not supported for the specified target.')
        return None


class HtmlifyFull(commands.CommandBase):
    def __init__(self, parent):
        super(HtmlifyFull, self).__init__(
            'htmlify_full',
            '',
            'Local version of htmlify_full.',
            '',
            parent)
        self.AddOptionEntry(commands.OptionEntry(
            's', 'skip_clean', 'skip_clean', bool, False, None,
            'Skip cleaning generated files up.'
        ))

    def Run(self, obj, args, ui):
        if args:
            ui.console.PrintError(
                'Extra argument passed to htmlify_full command!')
            return None

        if isinstance(obj, project.Project):
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
                not isinstance(checker, basic_codes.InternalDiffCode)):
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
        if not isinstance(checker, basic_codes.InternalDiffCode):
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
                not isinstance(checker, basic_codes.InternalDiffCode)):
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


class AtCoderUploader(UploaderBase):
    @taskgraph.task_method
    def Upload(self, ui, problem, dryrun):
        if problem.project.atcoder_config is None:
            ui.errors.Error(
                problem, 'atcoder_config is not defined in PROJECT.')
            yield False

        if not problem.atcoder_config_defined:
            ui.errors.Error(
                problem, 'atcoder_config() is not defined in PROBLEM.')
            yield False

        if problem.atcoder_task_id is None:
            ui.console.PrintAction(
                'UPLOAD', problem,
                'This problem is considered to a spare. Not uploaded.')
            yield True

        script = os.path.join(problem.project.atcoder_config.upload_script)
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
        if solution.project.atcoder_config is None:
            ui.errors.Error(
                solution, 'atcoder_config is not defined in PROJECT.')
            yield False

        solution.project._Login()

        task_id = str(solution.problem.atcoder_task_id)
        lang_id = solution.project.atcoder_config.lang_ids[
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


class Clean(commands.CommandBase):
    def __init__(self, parent):
        super(Clean, self).__init__(
            'clean',
            '[<target>]',
            'Clean intermediate files.',
            consts.CLEAN_HELP,
            parent)

    def Run(self, project, args, ui):
        return RunCommon('Clean', project, args, ui)


commands.registry.Add(Default)
commands.registry.Add(Build)
commands.registry.Add(Test)
commands.registry.Add(Pack)
commands.registry.Add(Upload)
commands.registry.Add(Submit)
commands.registry.Add(Add)
commands.registry.Add(Wikify)
commands.registry.Add(WikifyFull)
commands.registry.Add(HtmlifyFull)
packer_registry.Add(AOJPacker)
packer_registry.Add(AtCoderPacker)
uploader_registry.Add(AtCoderUploader)
submitter_registry.Add(AtCoderSubmitter)
commands.registry.Add(Clean)
