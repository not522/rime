import itertools

from rime.basic import test
from rime.basic.commands import submitter_registry
from rime.basic.targets import problem
from rime.core import codes
from rime.core import targets
from rime.core import taskgraph
from rime.util import files


class Solution(targets.TargetBase, problem.ProblemComponentMixin):
    """Solution target."""

    CONFIG_FILENAME = 'solution.json'

    def __init__(self, name, base_dir, parent):
        assert isinstance(parent, problem.Problem)
        super(Solution, self).__init__(name, base_dir, parent)
        self.project = parent.project
        self.problem = parent
        problem.ProblemComponentMixin.__init__(self)

    def PreLoad(self, ui, config):
        self.code = codes.AutoCode(
            src_dir=self.src_dir, out_dir=self.out_dir, **config)
        self.challenge_cases = config.get('challenge_cases')

        expected_verdicts = config.get('expected_verdicts', [])
        self.expected_verdicts = []
        if 'AC' in expected_verdicts:
            self.expected_verdicts.append(test.TestCaseResult.AC)
        if 'WA' in expected_verdicts:
            self.expected_verdicts.append(test.TestCaseResult.WA)
        if 'TLE' in expected_verdicts:
            self.expected_verdicts.append(test.TestCaseResult.TLE)
        if 'RE' in expected_verdicts:
            self.expected_verdicts.append(test.TestCaseResult.RE)
        if self.expected_verdicts == []:
            self.expected_verdicts = None

        self.expected_score = config.get('expected_score')

    def PostLoad(self, ui):
        pass

    def IsCorrect(self):
        """Returns whether this is correct solution."""
        return self.challenge_cases is None

    @taskgraph.task_method
    def Build(self, ui):
        """Build this solution."""
        if self.IsBuildCached():
            ui.console.PrintAction(
                'COMPILE', self, 'up-to-date', progress=True)
            yield True
        files.MakeDir(self.out_dir)
        if not self.code.QUIET_COMPILE:
            ui.console.PrintAction('COMPILE', self)
        res = yield self.code.Compile()
        log = self.code.ReadCompileLog()
        if res.status != codes.RunResult.OK:
            ui.errors.Error(self, 'Compile Error (%s)' % res.status)
            ui.console.PrintLog(log)
            yield False
        if log:
            ui.console.Print('Compiler warnings found:')
            ui.console.PrintLog(log)
        if not self.SetCacheStamp(ui):
            yield False
        yield True

    @taskgraph.task_method
    def Run(self, args, cwd, input, output, timeout, precise):
        """Run this solution."""
        yield (yield self.code.Run(
            args=args, cwd=cwd, input=input, output=output,
            timeout=timeout, precise=precise))

    @taskgraph.task_method
    def Test(self, ui):
        """Run tests for the solution."""
        results = yield taskgraph.TaskBranch(
            [testset.TestSolution(self, ui) for testset in
             self.problem.testsets])
        yield list(itertools.chain(*results))

    @taskgraph.task_method
    def Submit(self, ui):
        if not (yield self.Build(ui)):
            yield False
        if len(submitter_registry.classes) > 0:
            results = yield taskgraph.TaskBranch(
                [submitter().Submit(ui, self) for submitter
                 in submitter_registry.classes.values()])
            yield all(results)
        else:
            ui.errors.Error(self, "Submit nothing.")
            yield False

    @taskgraph.task_method
    def Clean(self, ui):
        """Clean the solution."""
        ui.console.PrintAction('CLEAN', self)
        e = yield self.code.Clean()
        if e:
            ui.errors.Exception(self, e)
            yield False
        yield True


targets.registry.Add(Solution)
