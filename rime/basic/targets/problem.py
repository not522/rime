import itertools
import json
import os.path

from rime.basic import commands
from rime.basic import consts
from rime.basic.targets import project
from rime.core import targets
from rime.core import taskgraph
from rime.util import files


class WikifyConfig(object):
    def __init__(self, config, name):
        self.title = config.get('title', name)
        self.page = config.get('page', '')
        self.assignees = config.get('assignees', '')
        self.need_custom_judge = config.get('need_custom_judge', False)


class Problem(targets.TargetBase):
    """Problem target."""

    CONFIG_FILENAME = 'problem.json'

    def __init__(self, name, base_dir, parent):
        assert isinstance(parent, project.Project)
        super(Problem, self).__init__(name, base_dir, parent)
        self.project = parent
        self.problem = self
        self.out_dir = os.path.join(self.problem.base_dir, consts.RIME_OUT_DIR)

    def PreLoad(self, ui):
        if ui.options['rel_out_dir'] != "-":
            self.out_dir = os.path.join(
                self.project.base_dir, ui.options['rel_out_dir'], self.name,
                consts.RIME_OUT_DIR)
        if ui.options['abs_out_dir'] != "-":
            self.out_dir = os.path.join(
                ui.options['abs_out_dir'], self.name, consts.RIME_OUT_DIR)

        with open(self.config_file) as f:
            config = json.load(f)

        self.id = config.get('id', '')
        self.timeout = config['time_limit']
        self.reference_solution = config.get('reference_solution')

        if 'wikify_config' in config:
            self.wikify_config = WikifyConfig(config, self.name)
        else:
            self.wikify_config = None

        self.atcoder_task_id = config.get('atcoder_task_id')

    def PostLoad(self, ui):
        self._ChainLoad(ui)
        self._ParseSettings(ui)

    def _ChainLoad(self, ui):
        # Chain-load solutions.
        self.solutions = []
        for name in sorted(files.ListDir(self.base_dir)):
            path = os.path.join(self.base_dir, name)
            if targets.registry.Solution.CanLoadFrom(path):
                solution = targets.registry.Solution(name, path, self)
                try:
                    solution.Load(ui)
                    self.solutions.append(solution)
                except targets.ConfigurationError:
                    ui.errors.Exception(solution)
        # Chain-load testsets.
        self.testsets = []
        for name in sorted(files.ListDir(self.base_dir)):
            path = os.path.join(self.base_dir, name)
            if targets.registry.Testset.CanLoadFrom(path):
                testset = targets.registry.Testset(name, path, self)
                try:
                    testset.Load(ui)
                    self.testsets.append(testset)
                except targets.ConfigurationError:
                    ui.errors.Exception(testset)

    def _ParseSettings(self, ui):
        # Currently we only support one testset per problem.
        self.testset = None
        if len(self.testsets) >= 2:
            ui.errors.Error(self, 'Multiple testsets found')
        elif len(self.testsets) == 0:
            self.testset = targets.registry.Testset.CreateEmpty(self, ui)
        elif len(self.testsets) == 1:
            self.testset = self.testsets[0]

        if self.timeout is None:
            ui.errors.Error(self, 'Time limit is not specified')

        # Select a reference solution.
        if self.reference_solution is None:
            # If not explicitly specified, select one which is
            # not marked as incorrect.
            for solution in self.solutions:
                if solution.IsCorrect():
                    self.reference_solution = solution
                    break

        else:
            # If explicitly specified, just use it.
            reference_solution_name = self.reference_solution
            self.reference_solution = None
            for solution in self.solutions:
                if solution.name == reference_solution_name:
                    self.reference_solution = solution
                    break
            if self.reference_solution is None:
                ui.errors.Error(
                    self,
                    ('Reference solution "%s" does not exist' %
                     reference_solution_name))

    def FindByBaseDir(self, base_dir):
        if self.base_dir == base_dir:
            return self
        for solution in self.solutions:
            obj = solution.FindByBaseDir(base_dir)
            if obj:
                return obj
        for testset in self.testsets:
            obj = testset.FindByBaseDir(base_dir)
            if obj:
                return obj
        return None

    @taskgraph.task_method
    def Build(self, ui):
        """Build all solutions and the testset."""
        results = yield taskgraph.TaskBranch(
            [solution.Build(ui) for solution in self.solutions] +
            [self.testset.Build(ui)])
        yield all(results)

    @taskgraph.task_method
    def Test(self, ui):
        """Run tests in the problem."""
        results = yield taskgraph.TaskBranch(
            [testset.Test(ui) for testset in self.testsets])
        yield list(itertools.chain(*results))

    @taskgraph.task_method
    def TestSolution(self, solution, ui):
        """Run tests in the problem."""
        results = yield taskgraph.TaskBranch(
            [testset.TestSolution(solution, ui) for testset in self.testsets])
        yield list(itertools.chain(*results))

    @taskgraph.task_method
    def Pack(self, ui):
        results = yield taskgraph.TaskBranch(
            [testset.Pack(ui) for testset in self.testsets])
        yield all(results)

    @taskgraph.task_method
    def Upload(self, ui):
        if not (yield self.Pack(ui)):
            yield False
        if len(commands.uploader_registry.classes) > 0:
            results = yield taskgraph.TaskBranch(
                [uploader().Upload(ui, self, not ui.options['upload'])
                 for uploader in commands.uploader_registry.classes.values()])
            yield all(results)
        else:
            ui.errors.Error(self, "Upload nothing.")
            yield False

    @taskgraph.task_method
    def Submit(self, ui):
        if self.atcoder_task_id is None:
            ui.console.PrintAction(
                'SUBMIT', self,
                'This problem is considered to a spare. Not submitted.')
            yield True

        results = yield taskgraph.TaskBranch(
            [solution.Submit(ui) for solution in self.solutions])
        yield all(results)

    @taskgraph.task_method
    def Add(self, args, ui):
        if len(args) != 2:
            yield None
        ttype = args[0].lower()
        name = args[1]
        if ttype == 'solution':
            content = '''\
## Solution
#c_solution(src='main.c') # -lm -O2 as default
#cxx_solution(src='main.cc', flags=[]) # -std=c++11 -O2 as default
#kotlin_solution(src='main.kt') # kotlin
#java_solution(src='Main.java', encoding='UTF-8', mainclass='Main')
#java_solution(src='Main.java', encoding='UTF-8', mainclass='Main',
#              challenge_cases=[])
#java_solution(src='Main.java', encoding='UTF-8', mainclass='Main',
#              challenge_cases=['10_corner*.in'])
#rust_solution(src='main.rs') # Rust (rustc)
#script_solution(src='main.sh') # shebang line is required
#script_solution(src='main.pl') # shebang line is required
#script_solution(src='main.py') # shebang line is required
#script_solution(src='main.rb') # shebang line is required
#js_solution(src='main.js') # javascript (nodejs)
#hs_solution(src='main.hs') # haskell (stack + ghc)
#cs_solution(src='main.cs') # C# (mono)

## Score
#expected_score(100)
'''
            newdir = os.path.join(self.base_dir, name)
            if(os.path.exists(newdir)):
                ui.errors.Error(self, "{0} already exists.".format(newdir))
                yield None
            os.makedirs(newdir)
            targets.EditFile(os.path.join(newdir, 'SOLUTION'), content)
            ui.console.PrintAction('ADD', None, '%s/SOLUTION' % newdir)
        elif ttype == 'testset':
            content = '''\
## Input generators.
#c_generator(src='generator.c')
#cxx_generator(src='generator.cc', dependency=['testlib.h'])
#java_generator(src='Generator.java', encoding='UTF-8', mainclass='Generator')
#rust_generator(src='generator.rs')
#script_generator(src='generator.pl')

## Input validators.
#c_validator(src='validator.c')
#cxx_validator(src='validator.cc', dependency=['testlib.h'])
#java_validator(src='Validator.java', encoding='UTF-8',
#               mainclass='tmp/validator/Validator')
#rust_validator(src='validator.rs')
#script_validator(src='validator.pl')

## Output judges.
#c_judge(src='judge.c')
#cxx_judge(src='judge.cc', dependency=['testlib.h'],
#          variant=testlib_judge_runner)
#java_judge(src='Judge.java', encoding='UTF-8', mainclass='Judge')
#rust_judge(src='judge.rs')
#script_judge(src='judge.py')

## Reactives.
#c_reactive(src='reactive.c')
#cxx_reactive(src='reactive.cc', dependency=['testlib.h', 'reactive.hpp'],
#             variant=kupc_reactive_runner)
#java_reactive(src='Reactive.java', encoding='UTF-8', mainclass='Judge')
#rust_reactive(src='reactive.rs')
#script_reactive(src='reactive.py')

## Extra Testsets.
# icpc type
#icpc_merger(input_terminator='0 0\\n')
# icpc wf ~2011
#icpc_merger(input_terminator='0 0\\n',
#            output_replace=casenum_replace('Case 1', 'Case {{0}}'))
#gcj_merger(output_replace=casenum_replace('Case 1', 'Case {{0}}'))
id='{0}'
#merged_testset(name=id + '_Merged', input_pattern='*.in')
#subtask_testset(name='All', score=100, input_patterns=['*'])
# precisely scored by judge program like Jiyukenkyu (KUPC 2013)
#scoring_judge()
'''
            newdir = os.path.join(self.base_dir, name)
            if(os.path.exists(newdir)):
                ui.errors.Error(self, "{0} already exists.".format(newdir))
                yield None
            os.makedirs(newdir)
            targets.EditFile(os.path.join(newdir, 'TESTSET'),
                             content.format(self.id))
            ui.console.PrintAction('ADD', self, '%s/TESTSET' % newdir)
        else:
            ui.errors.Error(self,
                            "Target type {0} cannot be put here.".format(
                                ttype))
            yield None

    @taskgraph.task_method
    def Clean(self, ui):
        """Clean the problem."""
        ui.console.PrintAction('CLEAN', self)
        success = True
        if success:
            try:
                files.RemoveTree(self.out_dir)
            except Exception:
                ui.errors.Exception(self)
                success = False
        yield success


class ProblemComponentMixin(object):
    """Mix-in for components of a problem (solution, testset)."""

    def __init__(self):
        self.src_dir = self.base_dir
        assert self.src_dir.startswith(self.base_dir)
        rel_dir = self.src_dir[len(self.problem.base_dir) + 1:]
        self.out_dir = os.path.join(self.problem.out_dir, rel_dir)
        self.stamp_file = os.path.join(self.out_dir, consts.STAMP_FILE)

    def GetLastModified(self):
        """Get timestamp of this target."""
        stamp = files.GetLastModifiedUnder(self.src_dir)
        if self.project.library_dir is not None:
            stamp = max(stamp, files.GetLastModifiedUnder(
                self.project.library_dir))
        return stamp

    def SetCacheStamp(self, ui):
        """Update the stamp file."""
        try:
            files.CreateEmptyFile(self.stamp_file)
            return True
        except Exception:
            ui.errors.Exception(self)
            return False

    def GetCacheStamp(self):
        """Get timestamp of the stamp file.

        Returns datetime.datetime.min if not available.
        """
        return files.GetModified(self.stamp_file)

    def IsBuildCached(self):
        """Check if cached build is not staled."""
        src_mtime = self.GetLastModified()
        stamp_mtime = self.GetCacheStamp()
        return (src_mtime < stamp_mtime)


targets.registry.Add(Problem)
