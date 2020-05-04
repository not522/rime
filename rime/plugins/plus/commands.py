import os
import os.path
from subprocess import call

from rime.basic import commands as basic_commands
from rime.basic import consts
import rime.basic.targets.problem   # NOQA
import rime.basic.targets.project   # NOQA
import rime.basic.targets.solution  # NOQA
import rime.basic.targets.testset   # NOQA
from rime.core import commands
from rime.core import targets
from rime.core import taskgraph
from rime.util import class_registry
from rime.util import files


class PackerBase(object):
    @taskgraph.task_method
    def Pack(self, ui, testset):
        raise NotImplementedError()


class UploaderBase(object):
    @taskgraph.task_method
    def Upload(self, ui, problem, dryrun):
        raise NotImplementedError()


packer_registry = class_registry.ClassRegistry(PackerBase)
uploader_registry = class_registry.ClassRegistry(UploaderBase)


class Testset(targets.registry.Testset):

    @taskgraph.task_method
    def Pack(self, ui):
        if not (yield self.Build(ui)):
            yield False
        if len(packer_registry.classes) > 0:
            results = yield taskgraph.TaskBranch(
                [packer().Pack(ui, self) for packer
                 in packer_registry.classes.values()])
            yield all(results)
        else:
            ui.errors.Error(self, "Pack nothing: you must add some plugin.")
            yield False

    @taskgraph.task_method
    def Upload(self, ui):
        ui.errors.Error(self, "A testset is not a target.")
        yield False

    @taskgraph.task_method
    def Submit(self, ui):
        ui.errors.Error(self, "A testset is not a target.")
        yield False


targets.registry.Override('Testset', Testset)


class Pack(commands.CommandBase):
    def __init__(self, parent):
        super(Pack, self).__init__(
            'pack',
            '[<target>]',
            'Pack testsets to export to online judges.',
            '',
            parent)

    def Run(self, project, args, ui):
        return basic_commands.RunCommon('Pack', project, args, ui)


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
        return basic_commands.RunCommon('Upload', project, args, ui)


class Submit(commands.CommandBase):
    def __init__(self, parent):
        super(Submit, self).__init__(
            'submit',
            '[<target>]',
            'Submit solutions to online judges.',
            '',
            parent)

    def Run(self, project, args, ui):
        return basic_commands.RunCommon('Submit', project, args, ui)


commands.registry.Add(Pack)
commands.registry.Add(Upload)
commands.registry.Add(Submit)


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


commands.registry.Add(Add)
