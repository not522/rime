import os
import os.path

from rime.basic import consts
from rime.basic.targets import project
from rime.basic.targets import problem
from rime.basic.targets import solution
from rime.basic.targets import testset
from rime.basic.util import test_summary
from rime.core import commands
from rime.core import taskgraph
from rime.util import class_registry


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
commands.registry.Add(Clean)
