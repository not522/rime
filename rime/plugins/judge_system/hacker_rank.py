import os
import os.path
import shutil

from rime.basic import consts
from rime.basic import commands as basic_commands
import rime.basic.targets.testset   # NOQA
from rime.core import targets
from rime.core import taskgraph
from rime.util import files


class Testset(targets.registry.Testset):
    def __init__(self, *args, **kwargs):
        super(Testset, self).__init__(*args, **kwargs)
        self.pack_dir = os.path.join(self.problem.out_dir,
                                     'hacker_rank')


class HackerRankPacker(basic_commands.PackerBase):
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


targets.registry.Override('Testset', Testset)

basic_commands.packer_registry.Add(HackerRankPacker)
