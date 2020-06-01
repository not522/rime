from rime.commands import AtCoderSubmitter
from rime import codes
from rime import target
from rime import test
from rime.targets.problem_component_mixin import ProblemComponentMixin
from rime.targets import problem
from rime.util import files


class Solution(target.TargetBase, ProblemComponentMixin):
    """Solution target."""

    CONFIG_FILENAME = 'solution.json'

    def __init__(self, name, base_dir, parent):
        assert isinstance(parent, problem.Problem)
        super(Solution, self).__init__(name, base_dir, parent)
        self.project = parent.project
        self.problem = parent
        ProblemComponentMixin.__init__(self)

    def PreLoad(self, ui, config):
        self.code = codes.get_code(
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

    def build(self, ui):
        """Build this solution."""
        if self.IsBuildCached():
            ui.console.PrintAction(
                'COMPILE', self, 'up-to-date', progress=True)
            return True
        files.MakeDir(self.out_dir)
        if not self.code.QUIET_COMPILE:
            ui.console.PrintAction('COMPILE', self)
        res = self.code.Compile()
        log = self.code.ReadCompileLog()
        if res.status != codes.RunResult.OK:
            ui.errors.Error(self, 'Compile Error (%s)' % res.status)
            ui.console.PrintLog(log)
            return False
        if log:
            ui.console.Print('Compiler warnings found:')
            ui.console.PrintLog(log)
        if not self.SetCacheStamp(ui):
            return False
        return True

    def Run(self, args, cwd, input, output, timeout, precise):
        """Run this solution."""
        return self.code.Run(
            args=args, cwd=cwd, input=input, output=output,
            timeout=timeout, precise=precise)

    def test(self, ui):
        """Run tests for the solution."""
        results = []
        for testset in self.problem.testsets:
            results.append(testset.test_solution(self, ui))
        return results

    def Submit(self, ui):
        if not self.build(ui):
            return False
        if self.project.judge_system.name == 'AtCoder':
            return AtCoderSubmitter().Submit(ui, self)
        else:
            ui.errors.Error(self, "Submit nothing.")
            return False

    def clean(self, ui):
        """Clean the solution."""
        ui.console.PrintAction('CLEAN', self)
        e = self.code.clean()
        if e:
            ui.errors.Exception(self, e)
            return False
        return True
