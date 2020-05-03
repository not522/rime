import fnmatch
import json
import os.path

from rime.basic import consts
import rime.basic.targets.problem  # NOQA
import rime.basic.targets.project  # NOQA
import rime.basic.targets.solution  # NOQA
import rime.basic.targets.testset  # NOQA
from rime.basic import test
from rime.core import codes
from rime.core import targets
from rime.core import taskgraph
from rime.util import files


class Testset(targets.registry.Testset):
    def __init__(self, *args, **kwargs):
        super(Testset, self).__init__(*args, **kwargs)

    # dependency
    def PreLoad(self, ui):
        super(Testset, self).PreLoad(ui)
        self.reactives = []
        self.exports.update(
            codes.CreateDictionary('%s_generator', self.generators,
                                   src_dir=self.src_dir,
                                   out_dir=self.out_dir,
                                   wrapper=self._WrapDependency))
        self.exports.update(
            codes.CreateDictionary('%s_validator', self.validators,
                                   src_dir=self.src_dir,
                                   out_dir=self.out_dir,
                                   wrapper=self._WrapDependency))
        self.exports.update(
            codes.CreateDictionary('%s_judge', self.judges,
                                   src_dir=self.src_dir,
                                   out_dir=self.out_dir,
                                   wrapper=self._WrapDependency))
        self.exports.update(
            codes.CreateDictionary('%s_reactive', self.reactives,
                                   src_dir=self.src_dir,
                                   out_dir=self.out_dir,
                                   wrapper=self._WrapDependency))

    def _WrapDependency(self, code_class):
        def Wrapped(src_name, src_dir, out_dir, dependency=[], variant=None,
                    *args, **kwargs):
            code = code_class(src_name, src_dir, out_dir, *args, **kwargs)
            code.dependency = dependency
            code.variant = variant
            return code
        return Wrapped

    # unexpectedly accepted error message
    @taskgraph.task_method
    def _TestSolutionWithChallengeCases(self, solution, ui):
        """Test a wrong solution which has specified challenge cases."""
        all_testcases = self.ListTestCases()
        challenge_infiles = solution.challenge_cases
        testcases = []
        for infile in challenge_infiles:
            matched_testcases = [
                testcase for testcase in all_testcases
                if fnmatch.fnmatch(os.path.basename(testcase.infile), infile)]

            if not matched_testcases:
                ui.errors.Error(solution,
                                'Challenge case not found: %s' % infile)
                result = test.TestsetResult(self, solution, [])
                result.Finalize(False,
                                'Challenge case not found: %s' % infile)
                yield result

            testcases.extend(
                [t for t in matched_testcases if t.infile not in testcases])
        # Try challenge cases.
        result = test.TestsetResult(self, solution, testcases)
        yield taskgraph.TaskBranch([
            self._TestSolutionWithChallengeCasesOne(
                solution, testcase, result, ui)
            for testcase in testcases],
            unsafe_interrupt=True)
        if not result.IsFinalized():
            result.Finalize(False,
                            'Unexpectedly accepted all challenge cases')
            ui.errors.Error(solution, result.detail)
        yield result

    # input pattern & expected verdict
    @taskgraph.task_method
    def _TestSolutionWithChallengeCasesOne(self, solution, testcase, result,
                                           ui):
        """Test a wrong solution which has specified challenge cases."""
        case_result = yield self._TestOneCase(solution, testcase, ui)
        result.results[testcase] = case_result
        if (solution.expected_verdicts is None and
                case_result.verdict == test.TestCaseResult.AC):
            ui.console.PrintAction('TEST', solution,
                                   '%s: Unexpectedly accepted'
                                   % os.path.basename(testcase.infile),
                                   progress=True)
            yield False
        elif (solution.expected_verdicts is not None and
              case_result.verdict not in solution.expected_verdicts):
            result.Finalize(False,
                            '%s: Unexpected Verdict (%s)' %
                            (os.path.basename(testcase.infile),
                             case_result.verdict),
                            notable_testcase=testcase)
            ui.errors.Error(solution, result.detail)
            if ui.options['keep_going']:
                yield False
            else:
                raise taskgraph.Bailout([False])
        elif case_result.verdict not in (test.TestCaseResult.WA,
                                         test.TestCaseResult.TLE,
                                         test.TestCaseResult.RE):
            result.Finalize(False,
                            '%s: Judge Error' % os.path.basename(
                                testcase.infile),
                            notable_testcase=testcase)
            ui.errors.Error(solution, result.detail)
            if ui.options['keep_going']:
                yield False
            else:
                raise taskgraph.Bailout([False])
        ui.console.PrintAction('TEST', solution,
                               '%s: PASSED' % os.path.basename(
                                   testcase.infile),
                               progress=True)
        result.Finalize(True,
                        '%s: %s' % (os.path.basename(testcase.infile),
                                    case_result.verdict),
                        notable_testcase=testcase)
        yield True

    # input pattern
    @taskgraph.task_method
    def _TestSolutionWithAllCases(self, solution, ui):
        """Test a solution without challenge cases.

        The solution can be marked as wrong but without challenge cases.
        """
        testcases = self.ListTestCases()
        result = test.TestsetResult(self, solution, testcases)
        # Try all cases.
        yield taskgraph.TaskBranch([
            self._TestSolutionWithAllCasesOne(solution, testcase, result, ui)
            for testcase in testcases],
            unsafe_interrupt=True)
        if not result.IsFinalized():
            if solution.IsCorrect():
                result.Finalize(True, result.GetTimeStats(ui))
            else:
                result.Finalize(False, 'Unexpectedly accepted all test cases')
                ui.errors.Error(solution, result.detail)
        yield result

    # improve keep going & expected verdict
    @taskgraph.task_method
    def _TestSolutionWithAllCasesOne(self, solution, testcase, result, ui):
        """Test a solution without challenge cases.

        The solution can be marked as wrong but without challenge cases.
        """
        case_result = yield self._TestOneCase(solution, testcase, ui)
        result.results[testcase] = case_result
        if case_result.verdict not in (test.TestCaseResult.AC,
                                       test.TestCaseResult.WA,
                                       test.TestCaseResult.TLE,
                                       test.TestCaseResult.RE):
            result.Finalize(False,
                            '%s: Judge Error' %
                            os.path.basename(testcase.infile),
                            notable_testcase=testcase)
            ui.errors.Error(solution, result.detail)
            if ui.options['keep_going']:
                yield False
            else:
                raise taskgraph.Bailout([False])
        elif case_result.verdict != test.TestCaseResult.AC:
            expected = not solution.IsCorrect()
            r = test.TestsetResult(
                result.testset, result.solution, result.testcases)
            r.Finalize(expected,
                       '%s: %s' % (os.path.basename(testcase.infile),
                                   case_result.verdict),
                       notable_testcase=testcase)
            result.Finalize(expected,
                            '%s: %s' % (os.path.basename(testcase.infile),
                                        case_result.verdict),
                            notable_testcase=testcase)
            if solution.IsCorrect():
                if case_result.verdict == test.TestCaseResult.WA:
                    judgefile = os.path.join(
                        solution.out_dir,
                        os.path.splitext(
                            os.path.basename(testcase.infile))[0] +
                        consts.JUDGE_EXT)
                    ui.errors.Error(solution,
                                    '%s\n  judge log: %s' %
                                    (r.detail, judgefile))
                else:
                    ui.errors.Error(solution, r.detail)
            elif (solution.expected_verdicts is not None and
                  case_result.verdict not in solution.expected_verdicts):
                r = test.TestsetResult(
                    result.testset, result.solution, result.testcases)
                r.Finalize(False,
                           '%s: Unexpected Verdict (%s)' %
                           (os.path.basename(testcase.infile),
                            case_result.verdict),
                           notable_testcase=testcase)
                ui.errors.Error(solution, r.detail)
                if case_result.verdict == test.TestCaseResult.WA:
                    judgefile = os.path.join(
                        solution.out_dir,
                        os.path.splitext(
                            os.path.basename(testcase.infile))[0] +
                        consts.JUDGE_EXT)
                    ui.errors.Error(solution,
                                    '%s\n  judge log: %s' %
                                    (r.detail, judgefile))
                else:
                    ui.errors.Error(solution, r.detail)
            if ui.options['keep_going']:
                yield False
            else:
                raise taskgraph.Bailout([False])
        ui.console.PrintAction('TEST', solution,
                               '%s: PASSED' % os.path.basename(
                                   testcase.infile),
                               progress=True)
        yield True

    # cache test results
    @taskgraph.task_method
    def _TestOneCase(self, solution, testcase, ui):
        """Test a solution with one case.

        Cache results if option is set.
        Returns TestCaseResult.
        """
        cache_file_name = os.path.join(
            solution.out_dir,
            os.path.splitext(
                os.path.basename(testcase.infile))[0] + consts.CACHE_EXT)
        solution_file_name = os.path.join(
            solution.src_dir, solution.code.src_name)

        cache_flag = (
            ui.options['cache_tests'] and
            files.GetModified(solution_file_name) <
            files.GetModified(cache_file_name) and
            files.GetModified(testcase.infile) <
            files.GetModified(cache_file_name))

        if cache_flag:
            case_result_cache = files.ReadFile(cache_file_name)
            if case_result_cache is not None:
                j = json.loads(case_result_cache)
                if j['time'] is not None:
                    j['time'] = float(j['time'])
                if j['verdict'] is not None:
                    j['verdict'] = j['verdict'].encode('ascii')

                case_result = test.TestCaseResult(
                    solution, testcase, None, None, True)
                case_result.time = j['time']
                case_result.verdict = [
                    verdict for verdict in
                    test.TestCaseResult.__dict__.values()
                    if isinstance(verdict, test.TestVerdict) and
                    verdict.msg == j['verdict']][0]

            yield case_result

        case_result = yield self._TestOneCaseNoCache(solution, testcase, ui)

        # always cache in json
        files.WriteFile(json.dumps({
            'verdict': case_result.verdict.msg,
            'time': case_result.time
        }), cache_file_name)

        yield case_result

    consts.INVALID_EXT = '.invalid'

    def ListInvalidTestCases(self):
        """Enumerate invalid test cases."""
        testcases = []
        for infile in files.ListDir(self.out_dir, False):
            infile = os.path.join(self.out_dir, infile)
            if not infile.endswith(consts.INVALID_EXT):
                continue
            if not os.path.isfile(infile):
                continue
            testcases.append(test.TestCase(self, infile))
        self._SortTestCases(testcases)
        return testcases

    @taskgraph.task_method
    def _RunValidators(self, ui):
        """Run input validators."""
        if not self.validators:
            # Ignore when this testset actually does not exist.
            if self.base_dir:
                ui.errors.Warning(self, 'Validator unavailable')
            yield True
        testcases = self.ListTestCases()
        results = yield taskgraph.TaskBranch([
            self._RunValidatorOne(validator, testcase, ui)
            for validator in self.validators
            for testcase in testcases])
        if not all(results):
            yield False
        invalidcases = self.ListInvalidTestCases()
        results = yield taskgraph.TaskBranch([
            self._RunValidatorForInvalidCasesOne(validator, invalidcase, ui)
            for validator in self.validators
            for invalidcase in invalidcases])
        if not all(results):
            yield False
        ui.console.PrintAction('VALIDATE', self, 'OK')
        yield True

    @taskgraph.task_method
    def _RunValidatorForInvalidCasesOne(self, validator, testcase, ui):
        """Run an input validator against a single input file."""
        validationfile = (
            os.path.splitext(testcase.infile)[0] + consts.VALIDATION_EXT)
        res = yield validator.Run(
            args=(), cwd=self.out_dir,
            input=testcase.infile,
            output=validationfile,
            timeout=None, precise=False,
            redirect_error=True)
        if res.status == codes.RunResult.OK:
            ui.errors.Error(self,
                            '%s: Unexpectedly Validator Accepted: %s' %
                            (os.path.basename(testcase.infile), res.status))
            raise taskgraph.Bailout([False])
        ui.console.PrintAction(
            'VALIDATE', self,
            '%s: Expectedly Failed' % os.path.basename(testcase.infile),
            progress=True)
        yield True


targets.registry.Override('Testset', Testset)
