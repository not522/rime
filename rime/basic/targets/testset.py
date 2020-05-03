import fnmatch
import itertools
import json
import os.path
import re

from rime.basic import codes as basic_codes
from rime.basic import consts
from rime.basic.targets import problem
from rime.basic import test
from rime.core import codes as core_codes
from rime.core import targets
from rime.core import taskgraph
from rime.util import files
from rime.util import class_registry


class JudgeRunner(object):
    def Run(self, infile, difffile, outfile, cwd, judgefile):
        raise NotImplementedError()


class RimeJudgeRunner(JudgeRunner):
    PREFIX = 'rime'

    def Run(self, judge, infile, difffile, outfile, cwd, judgefile):
        return judge.Run(
            args=('--infile', infile,
                  '--difffile', difffile,
                  '--outfile', outfile),
            cwd=cwd,
            input=os.devnull,
            output=judgefile,
            timeout=None, precise=False,
            redirect_error=True)  # !redirect_error


class TestlibJudgeRunner(JudgeRunner):
    PREFIX = 'testlib'

    def Run(self, judge, infile, difffile, outfile, cwd, judgefile):
        return judge.Run(
            args=(infile, outfile, difffile),
            cwd=cwd,
            input=os.devnull,
            output=judgefile,
            timeout=None, precise=False,
            redirect_error=True)  # !redirect_error


judge_runner_registry = class_registry.ClassRegistry(JudgeRunner)
judge_runner_registry.Add(RimeJudgeRunner)
judge_runner_registry.Add(TestlibJudgeRunner)


class ReactiveRunner(object):
    def Run(self, reactive, solution, args, cwd, input, output, timeout,
            precise):
        raise NotImplementedError()


class KUPCReactiveRunner(ReactiveRunner):
    PREFIX = 'kupc'

    def Run(self, reactive, args, cwd, input, output, timeout, precise):
        return reactive.Run(
            args=("'%s'" % ' '.join(args),),
            cwd=cwd,
            input=input,
            output=output,
            timeout=timeout,
            precise=precise,
            redirect_error=True)  # !redirect_error


reactive_runner_registry = class_registry.ClassRegistry(ReactiveRunner)
reactive_runner_registry.Add(KUPCReactiveRunner)


class Testset(targets.TargetBase, problem.ProblemComponentMixin):
    """Testset target."""

    CONFIG_FILENAME = 'TESTSET'

    def __init__(self, name, base_dir, parent):
        assert isinstance(parent, problem.Problem)
        super(Testset, self).__init__(name, base_dir, parent)
        self.project = parent.project
        self.problem = parent
        problem.ProblemComponentMixin.__init__(self)

        for judge_runner in judge_runner_registry.classes.values():
            self.exports['{0}_judge_runner'.format(
                judge_runner.PREFIX)] = judge_runner()

        for reactive_runner in reactive_runner_registry.classes.values():
            self.exports['{0}_reactive_runner'.format(
                reactive_runner.PREFIX)] = reactive_runner()


    @classmethod
    def CreateEmpty(cls, parent, ui):
        # Workaround for no testset case.
        # TODO(nya): support multiple testsets.
        testset = cls('tests', '', parent)
        testset.config_file = '/dev/null'
        testset.Load(ui)
        return testset

    def PreLoad(self, ui):
        super(Testset, self).PreLoad(ui)
        self.generators = []
        self.validators = []
        self.judges = []
        self.reactives = []
        self.exports.update(
            core_codes.CreateDictionary('%s_generator', self.generators,
                                        src_dir=self.src_dir,
                                        out_dir=self.out_dir,
                                        wrapper=self._WrapDependency))
        self.exports.update(
            core_codes.CreateDictionary('%s_validator', self.validators,
                                        src_dir=self.src_dir,
                                        out_dir=self.out_dir,
                                        wrapper=self._WrapDependency))
        self.exports.update(
            core_codes.CreateDictionary('%s_judge', self.judges,
                                        src_dir=self.src_dir,
                                        out_dir=self.out_dir,
                                        wrapper=self._WrapDependency))
        self.exports.update(
            core_codes.CreateDictionary('%s_reactive', self.reactives,
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

    def PostLoad(self, ui):
        if not self.judges:
            self.judges.append(basic_codes.InternalDiffCode())

    def GetLastModified(self):
        """Get timestamp of this target.

        Testsets depend on reference solution.
        """
        stamp = problem.ProblemComponentMixin.GetLastModified(self)
        if self.problem.reference_solution:
            stamp = max(
                stamp, self.problem.reference_solution.GetLastModified())
        return stamp

    def ListTestCases(self):
        """Enumerate test cases."""
        testcases = []
        for infile in files.ListDir(self.out_dir, False):
            infile = os.path.join(self.out_dir, infile)
            if not infile.endswith(consts.IN_EXT):
                continue
            if not os.path.isfile(infile):
                continue
            testcases.append(test.TestCase(self, infile))
        self._SortTestCases(testcases)
        return testcases

    def _SortTestCases(self, testcases):
        """Sorts test cases in a little bit smarter way."""
        def tokenize(s):
            def replace_digits(match):
                return '%08s' % match.group(0)
            return re.sub(r'\d+', replace_digits, s.infile)
        testcases.sort(key=tokenize)

    @taskgraph.task_method
    def Build(self, ui):
        """Build testset."""
        if self.IsBuildCached():
            if not self.ListTestCases():
                ui.errors.Warning(self, 'No test case found')
            yield True
        if not (yield self._InitOutputDir(ui)):
            yield False
        if not all((yield taskgraph.TaskBranch([
                self._CompileGenerators(ui),
                self._CompileValidators(ui),
                self._CompileJudges(ui)]))):
            yield False
        if not (yield self._RunGenerators(ui)):
            yield False
        if not (yield self._RunValidators(ui)):
            yield False
        if not self.ListTestCases():
            ui.errors.Warning(self, 'No test case found')
        else:
            if not (yield self._CompileReferenceSolution(ui)):
                yield False
            if not (yield self._RunReferenceSolution(ui)):
                yield False
        if not (yield self._PostBuildHook(ui)):
            yield False
        if not self.SetCacheStamp(ui):
            yield False
        yield True

    @taskgraph.task_method
    def _InitOutputDir(self, ui):
        """Initialize output directory."""
        try:
            files.RemoveTree(self.out_dir)
            files.CopyTree(self.src_dir, self.out_dir)
        except Exception:
            ui.errors.Exception(self)
            yield False
        yield True

    @taskgraph.task_method
    def _CompileGenerators(self, ui):
        """Compile all input generators."""
        results = yield taskgraph.TaskBranch([
            self._CompileGeneratorOne(generator, ui)
            for generator in self.generators])
        yield all(results)

    @taskgraph.task_method
    def _CompileGeneratorOne(self, generator, ui):
        """Compile a single input generator."""
        if not generator.QUIET_COMPILE:
            ui.console.PrintAction('COMPILE', self, generator.src_name)
        res = yield generator.Compile()
        if res.status != core_codes.RunResult.OK:
            ui.errors.Error(
                self, '%s: Compile Error (%s)' %
                (generator.src_name, res.status))
            ui.console.PrintLog(generator.ReadCompileLog())
            raise taskgraph.Bailout([False])
        yield True

    @taskgraph.task_method
    def _RunGenerators(self, ui):
        """Run all input generators."""
        results = yield taskgraph.TaskBranch([
            self._RunGeneratorOne(generator, ui)
            for generator in self.generators])
        yield all(results)

    @taskgraph.task_method
    def _RunGeneratorOne(self, generator, ui):
        """Run a single input generator."""
        ui.console.PrintAction('GENERATE', self, generator.src_name)
        res = yield generator.Run(
            args=(), cwd=self.out_dir,
            input=os.devnull, output=os.devnull, timeout=None, precise=False)
        if res.status != core_codes.RunResult.OK:
            ui.errors.Error(self,
                            '%s: %s' % (generator.src_name, res.status))
            raise taskgraph.Bailout([False])
        yield True

    @taskgraph.task_method
    def _CompileValidators(self, ui):
        """Compile input validators."""
        results = yield taskgraph.TaskBranch([
            self._CompileValidatorOne(validator, ui)
            for validator in self.validators])
        yield all(results)

    @taskgraph.task_method
    def _CompileValidatorOne(self, validator, ui):
        """Compile a single input validator."""
        if not validator.QUIET_COMPILE:
            ui.console.PrintAction('COMPILE', self, validator.src_name)
        res = yield validator.Compile()
        if res.status != core_codes.RunResult.OK:
            ui.errors.Error(
                self, '%s: Compile Error (%s)' %
                (validator.src_name, res.status))
            ui.console.PrintLog(validator.ReadCompileLog())
            raise taskgraph.Bailout([False])
        yield True

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
        ui.console.PrintAction('VALIDATE', self, 'OK')
        yield True

    @taskgraph.task_method
    def _RunValidatorOne(self, validator, testcase, ui):
        """Run an input validator against a single input file."""
        validationfile = (
            os.path.splitext(testcase.infile)[0] + consts.VALIDATION_EXT)
        res = yield validator.Run(
            args=(), cwd=self.out_dir,
            input=testcase.infile,
            output=validationfile,
            timeout=None, precise=False,
            redirect_error=True)
        if res.status == core_codes.RunResult.NG:
            ui.errors.Error(
                self, '%s: Validation Failed' %
                os.path.basename(testcase.infile))
            log = files.ReadFile(validationfile)
            ui.console.PrintLog(log)
            raise taskgraph.Bailout([False])
        elif res.status != core_codes.RunResult.OK:
            ui.errors.Error(self,
                            '%s: Validator Failed: %s' %
                            (os.path.basename(testcase.infile), res.status))
            raise taskgraph.Bailout([False])
        ui.console.PrintAction('VALIDATE', self,
                               '%s: PASSED' % os.path.basename(
                                   testcase.infile),
                               progress=True)
        yield True

    @taskgraph.task_method
    def _CompileJudges(self, ui):
        """Compile all judges."""
        results = yield taskgraph.TaskBranch([
            self._CompileJudgeOne(judge, ui)
            for judge in self.judges])
        yield all(results)

        results = yield taskgraph.TaskBranch([
            self._CompileReactiveOne(reactive, ui)
            for reactive in self.reactives])
        yield all(results)

    @taskgraph.task_method
    def _CompileJudgeOne(self, judge, ui):
        """Compile a single judge."""
        if not judge.QUIET_COMPILE:
            ui.console.PrintAction('COMPILE', self, judge.src_name)
        res = yield judge.Compile()
        if res.status != core_codes.RunResult.OK:
            ui.errors.Error(
                self, '%s: Compile Error (%s)' % (judge.src_name, res.status))
            ui.console.PrintLog(judge.ReadCompileLog())
            yield False
        yield True

    @taskgraph.task_method
    def _CompileReferenceSolution(self, ui):
        """Compile the reference solution."""
        reference_solution = self.problem.reference_solution
        if reference_solution is None:
            ui.errors.Error(self, 'Reference solution unavailable')
            yield False
        yield (yield reference_solution.Build(ui))

    @taskgraph.task_method
    def _CompileReactiveOne(self, reactive, ui):
        """Compile a single reative."""
        if not reactive.QUIET_COMPILE:
            ui.console.PrintAction('COMPILE', self, reactive.src_name)
        res = yield reactive.Compile()
        if res.status != core_codes.RunResult.OK:
            ui.errors.Error(self, '%s: Compile Error (%s)'
                            % (reactive.src_name, res.status))
            ui.console.PrintLog(reactive.ReadCompileLog())
            yield False
        yield True

    @taskgraph.task_method
    def _RunReferenceSolution(self, ui):
        """Run the reference solution to generate reference outputs."""
        reference_solution = self.problem.reference_solution
        if reference_solution is None:
            ui.errors.Error(self, 'Reference solution unavailable')
            yield False
        testcases = self.ListTestCases()
        results = yield taskgraph.TaskBranch([
            self._RunReferenceSolutionOne(reference_solution, testcase, ui)
            for testcase in testcases])
        if not all(results):
            yield False
        ui.console.PrintAction('REFRUN', reference_solution)
        yield True

    @taskgraph.task_method
    def _RunReferenceSolutionOne(self, reference_solution, testcase, ui):
        """Run the reference solution against a single input file."""
        if os.path.isfile(testcase.difffile):
            yield True
        # reactive
        if self.reactives:
            if len(self.reactives) > 1:
                ui.errors.Error(self, "Multiple reactive checkers registered.")
                yield None
            reactive = self.reactives[0]
            if not reactive.variant:
                reactive.variant = KUPCReactiveRunner()
            res = yield reactive.variant.Run(
                reactive=reactive,
                args=reference_solution.code.run_args,
                cwd=reference_solution.out_dir,
                input=testcase.infile,
                output=testcase.difffile,
                timeout=None, precise=False)
        else:
            res = yield reference_solution.Run(
                args=(), cwd=reference_solution.out_dir,
                input=testcase.infile,
                output=testcase.difffile,
                timeout=None, precise=False)
        if res.status != core_codes.RunResult.OK:
            ui.errors.Error(reference_solution, res.status)
            raise taskgraph.Bailout([False])
        ui.console.PrintAction('REFRUN', reference_solution,
                               '%s: DONE' % os.path.basename(testcase.infile),
                               progress=True)
        yield True

    @taskgraph.task_method
    def _PostBuildHook(self, ui):
        yield True

    @taskgraph.task_method
    def Test(self, ui):
        """Run tests in the testset."""
        results = yield taskgraph.TaskBranch(
            [self.TestSolution(solution, ui) for solution in
             self.problem.solutions])
        yield list(itertools.chain(*results))

    @taskgraph.task_method
    def TestSolution(self, solution, ui):
        """Test a single solution."""
        if not (yield self.Build(ui)):
            result = test.TestsetResult(self, solution, [])
            result.Finalize(False, 'Failed to build tests')
            yield [result]
        if not (yield solution.Build(ui)):
            result = test.TestsetResult(self, solution, [])
            result.Finalize(False, 'Compile Error')
            yield [result]
        ui.console.PrintAction('TEST', solution, progress=True)
        if not solution.IsCorrect() and solution.challenge_cases:
            result = yield self._TestSolutionWithChallengeCases(solution, ui)
        else:
            result = yield self._TestSolutionWithAllCases(solution, ui)
        status_row = [result.detail]
        if result.IsCached():
            status_row += [' ', '(cached)']
        ui.console.PrintAction('TEST', solution, *status_row)
        if solution.IsCorrect() and not result.expected:
            assert result.notable_testcase
            judgefile = (os.path.splitext(result.notable_testcase.infile)[0] +
                         consts.JUDGE_EXT)
            log = files.ReadFile(judgefile)
            ui.console.PrintLog(log)
        yield [result]

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
            for testcase in testcases])
        if not result.IsFinalized():
            result.Finalize(False,
                            'Unexpectedly accepted all challenge cases')
            ui.errors.Error(solution, result.detail)
        yield result

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
            for testcase in testcases])
        if not result.IsFinalized():
            if solution.IsCorrect():
                result.Finalize(True, result.GetTimeStats(ui))
            else:
                result.Finalize(False, 'Unexpectedly accepted all test cases')
                ui.errors.Error(solution, result.detail)
        yield result

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

    @taskgraph.task_method
    def _TestOneCaseNoCache(self, solution, testcase, ui):
        """Test a solution with one case.

        Never cache results.
        Returns TestCaseResult.
        """
        outfile, judgefile = [
            os.path.join(
                solution.out_dir,
                os.path.splitext(os.path.basename(testcase.infile))[0] + ext)
            for ext in (consts.OUT_EXT, consts.JUDGE_EXT)]
        precise = (ui.options['precise'] or ui.options['parallelism'] <= 1)
        # reactive
        if self.reactives:
            if len(self.reactives) > 1:
                ui.errors.Error(self, "Multiple reactive checkers registered.")
                yield None
            reactive = self.reactives[0]
            if not reactive.variant:
                reactive.variant = KUPCReactiveRunner()
            res = yield reactive.variant.Run(
                reactive=reactive,
                args=solution.code.run_args, cwd=solution.out_dir,
                input=testcase.infile,
                output=outfile,
                timeout=testcase.timeout, precise=precise)
        else:
            res = yield solution.Run(
                args=(), cwd=solution.out_dir,
                input=testcase.infile,
                output=outfile,
                timeout=testcase.timeout, precise=precise)
        if res.status == core_codes.RunResult.TLE:
            yield test.TestCaseResult(
                solution, test.TestCaseResult.TLE, time=None, cached=False)
        if res.status != core_codes.RunResult.OK:
            yield test.TestCaseResult(
                solution, test.TestCaseResult.RE, time=None, cached=False)

        time = res.time
        for judge in self.judges:
            if not judge.variant:
                judge.variant = RimeJudgeRunner()
            res = yield judge.variant.Run(
                judge=judge,
                infile=testcase.infile,
                difffile=testcase.difffile,
                outfile=outfile,
                cwd=self.out_dir,
                judgefile=judgefile)
            if res.status == core_codes.RunResult.NG:
                yield test.TestCaseResult(
                    solution, test.TestCaseResult.WA, time=None, cached=False)
            elif res.status != core_codes.RunResult.OK:
                yield test.TestCaseResult(
                    solution, test.TestVerdict('Validator %s' % res.status),
                    time=None, cached=False)
        yield test.TestCaseResult(solution, test.TestCaseResult.AC,
                                  time=time, cached=False)

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
        if res.status == core_codes.RunResult.OK:
            ui.errors.Error(self,
                            '%s: Unexpectedly Validator Accepted: %s' %
                            (os.path.basename(testcase.infile), res.status))
            raise taskgraph.Bailout([False])
        ui.console.PrintAction(
            'VALIDATE', self,
            '%s: Expectedly Failed' % os.path.basename(testcase.infile),
            progress=True)
        yield True

    @taskgraph.task_method
    def Clean(self, ui):
        """Clean the testset."""
        ui.console.PrintAction('CLEAN', self)
        try:
            files.RemoveTree(self.out_dir)
        except Exception:
            ui.errors.Exception(self)
        yield True


targets.registry.Add(Testset)
