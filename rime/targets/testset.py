import fnmatch
import json
import os.path
import re

from rime import codes
from rime import commands
from rime import consts
from rime import target
from rime import test
from rime.targets.problem_component_mixin import ProblemComponentMixin
from rime.targets import problem
from rime.util import files


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


consts.IN_ORIGINAL_EXT = '.in_orig'


class TestMerger(object):
    def __init__(self, output_replace=None):
        self.output_replace = output_replace

    def Run(self, testcases, merged_testcase, ui):
        infiles = [os.path.splitext(t.infile)[0] + consts.IN_ORIGINAL_EXT
                   for t in testcases]
        difffiles = [os.path.splitext(infile)[0] + consts.DIFF_EXT
                     for infile in infiles]
        ui.console.PrintAction(
            'MERGE', merged_testcase.testset,
            'Generating %s' % os.path.basename(merged_testcase.infile),
            progress=True)
        self._ConcatenateIn(infiles, merged_testcase.infile)
        ui.console.PrintAction(
            'MERGE', merged_testcase.testset,
            'Generating %s' % os.path.basename(merged_testcase.difffile),
            progress=True)
        self._ConcatenateDiff(difffiles, merged_testcase.difffile)

    def _ConcatenateIn(self, srcs, dst):
        raise NotImplementedError()

    def _ConcatenateDiff(self, srcs, dst):
        # avoid overwriting
        if any([os.path.exists(src) and src != dst for src in srcs]):
            with open(dst, 'w') as f:
                for i, src in enumerate(srcs):
                    if self.output_replace:
                        f.write(self.output_replace(
                            i + 1, files.ReadFile(src)))
                    else:
                        f.write(files.ReadFile(src))


class ICPCMerger(TestMerger):
    PREFIX = 'icpc'

    def __init__(self, input_terminator, output_replace=None):
        super(ICPCMerger, self).__init__(output_replace)
        self.input_terminator = input_terminator
        if self.input_terminator and not self.input_terminator.endswith('\n'):
            raise RuntimeError(
                'icpc_merger(): input_terminator is not ending with \\n.')

    def _ConcatenateIn(self, srcs, dst):
        with open(dst, 'w') as f:
            for i, src in enumerate(srcs):
                f.write(files.ReadFile(src))
            f.write(self.input_terminator)


class GCJMerger(TestMerger):
    PREFIX = 'gcj'

    def __init__(self, output_replace=None):
        super(GCJMerger, self).__init__(output_replace)

    def _ConcatenateIn(self, srcs, dst):
        with open(dst, 'w') as f:
            f.write(str(len(srcs)) + '\n')
            for i, src in enumerate(srcs):
                f.write(files.ReadFile(src))


class MergedTestCase(test.TestCase):
    def __init__(self, testset, name, input_pattern):
        super(MergedTestCase, self).__init__(
            testset,
            os.path.join(testset.out_dir,
                         '{0}{1}'.format(name, consts.IN_EXT)))
        self.input_pattern = input_pattern

    @property
    def timeout(self):
        return None


class SubtaskTestCase(test.TestCase):
    def __init__(self, testset, name, score, input_patterns):
        super(SubtaskTestCase, self).__init__(
            testset,
            name, name)
        self.name = name
        self.score = score
        self.input_patterns = input_patterns

    @property
    def timeout(self):
        return None


class CasenumReplaceConfig(object):
    def __init__(self, case_pattern, case_replace):
        self.case_pattern = case_pattern
        self.case_replace = case_replace

    def __call__(self, i, src):
        return src.replace(self.case_pattern, self.case_replace.format(i))


class Testset(target.TargetBase, ProblemComponentMixin):
    """Testset target."""

    CONFIG_FILENAME = 'testset.json'

    def __init__(self, name, base_dir, parent):
        assert isinstance(parent, problem.Problem)
        super(Testset, self).__init__(name, base_dir, parent)
        self.project = parent.project
        self.problem = parent
        ProblemComponentMixin.__init__(self)

        # TODO(mizuno): activate them.
        # self.exports['rime_judge_runner'] = RimeJudgeRunner()
        # self.exports['testlib_judge_runner'] = TestlibJudgeRunner()

        # self.exports['kupc_reactive_runner'] = KUPCReactiveRunner()

        # self.exports['icpc_merger'] = ICPCMerger()
        # self.exports['gcj_merger'] = GCJMerger()

        self.aoj_pack_dir = os.path.join(self.problem.out_dir, 'aoj')
        self.atcoder_pack_dir = os.path.join(self.problem.out_dir, 'atcoder')
        self.pack_dir = os.path.join(self.problem.out_dir, 'hacker_rank')

    @classmethod
    def CreateEmpty(cls, parent, ui):
        # Workaround for no testset case.
        # TODO(nya): support multiple testsets.
        testset = cls('tests', '', parent)
        testset.config_file = '/dev/null'
        testset.Load(ui)
        return testset

    def PreLoad(self, ui, config):
        self.generators = []
        self.validators = []
        self.judges = []
        self.reactives = []

        for generator in config['generator']:
            self.generators.append(codes.get_code(
                src_dir=self.src_dir, out_dir=self.out_dir, **generator))

        for generator in config['validator']:
            self.validators.append(codes.get_code(
                src_dir=self.src_dir, out_dir=self.out_dir, **generator))

        for generator in config.get('judge', []):
            self.judges.append(codes.get_code(
                src_dir=self.src_dir, out_dir=self.out_dir, **generator))

        for generator in config.get('reactive', []):
            self.reactives.append(codes.get_code(
                src_dir=self.src_dir, out_dir=self.out_dir, **generator))

        if 'test_merger' in config:
            if config['test_merger']['kind'] == 'icpc':
                self.test_merger = ICPCMerger(**config['test_merger'])
            elif config['test_merger']['kind'] == 'gcj':
                self.test_merger = GCJMerger(**config['test_merger'])
            else:
                assert False, 'Unkown test merger'
        else:
            self.test_merger = None

        if 'casenum_replace' in config:
            self.casenum_replace = CasenumReplaceConfig(
                **config['casenum_replace'])
        else:
            self.casenum_replace = None

        self.merged_testcases = []
        if 'merged_testset' in config:
            for merged_testset in config['merged_testset']:
                self.merged_testcases.append(
                    MergedTestCase(self, **config['merged_testset']))

        self.subtask = []
        if 'subtask' in config:
            for subtask in config['subtask']:
                self.subtask.append(SubtaskTestCase(self, **config['subtask']))

        self.scoring_judge = config.get('scoring_judge', False)

        if not self.judges:
            self.judges.append(codes.InternalDiffCode())

    def GetLastModified(self):
        """Get timestamp of this target.

        Testsets depend on reference solution.
        """
        stamp = ProblemComponentMixin.GetLastModified(self)
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

        merged_infiles = set([t.infile for t in self.GetMergedTestCases()])
        return [t for t in testcases if t.infile not in merged_infiles]

    def GetMergedTestCases(self):
        return self.merged_testcases

    def _SortTestCases(self, testcases):
        """Sorts test cases in a little bit smarter way."""
        def tokenize(s):
            def replace_digits(match):
                return '%08s' % match.group(0)
            return re.sub(r'\d+', replace_digits, s.infile)
        testcases.sort(key=tokenize)

    def build(self, ui):
        """Build testset."""
        if self.IsBuildCached():
            if not self.ListTestCases():
                ui.errors.Warning(self, 'No test case found')
            return True
        if not self._init_output_dir(ui):
            return False
        if not self._compile_generators(ui):
            return False
        if not self._compile_validators(ui):
            return False
        if not self._compile_judges(ui):
            return False
        if not self._run_generators(ui):
            return False
        if not self._run_validators(ui):
            return False
        if not self.ListTestCases():
            ui.errors.Warning(self, 'No test case found')
        else:
            if not self._compile_reference_solution(ui):
                return False
            if not self._run_reference_solution(ui):
                return False
        if not self._post_build_hook(ui):
            return False
        if not self.SetCacheStamp(ui):
            return False
        return True

    def _init_output_dir(self, ui):
        """Initialize output directory."""
        try:
            files.RemoveTree(self.out_dir)
            files.CopyTree(self.src_dir, self.out_dir)
        except Exception:
            ui.errors.Exception(self)
            return False
        return True

    def _compile_generators(self, ui):
        """Compile all input generators."""
        results = []
        for generator in self.generators:
            results.append(self._compile_generator_one(generator, ui))
        return all(results)

    def _compile_generator_one(self, generator, ui):
        """Compile a single input generator."""
        if not generator.QUIET_COMPILE:
            ui.console.PrintAction('COMPILE', self, generator.src_name)
        res = generator.Compile()
        if res.status != codes.RunResult.OK:
            ui.errors.Error(
                self, '%s: Compile Error (%s)' %
                (generator.src_name, res.status))
            ui.console.PrintLog(generator.ReadCompileLog())
            return False
        return True

    def _run_generators(self, ui):
        """Run all input generators."""
        results = []
        for generator in self.generators:
            results.append(self._run_generator_one(generator, ui))
        if not all(results):
            return False

        if self.test_merger:
            for testcase in self.ListTestCases():
                src = testcase.infile
                dst = os.path.splitext(src)[0] + consts.IN_ORIGINAL_EXT
                files.CopyFile(src, dst)
                self.test_merger.Run([testcase], testcase, ui)

        return True

    def _run_generator_one(self, generator, ui):
        """Run a single input generator."""
        ui.console.PrintAction('GENERATE', self, generator.src_name)
        res = generator.Run(
            args=(), cwd=self.out_dir,
            input=os.devnull, output=os.devnull, timeout=None, precise=False)
        if res.status != codes.RunResult.OK:
            ui.errors.Error(self,
                            '%s: %s' % (generator.src_name, res.status))
            return False
        return True

    def _compile_validators(self, ui):
        """Compile input validators."""
        results = []
        for validator in self.validators:
            results.append(self._compile_validator_one(validator, ui))
        return all(results)

    def _compile_validator_one(self, validator, ui):
        """Compile a single input validator."""
        if not validator.QUIET_COMPILE:
            ui.console.PrintAction('COMPILE', self, validator.src_name)
        res = validator.Compile()
        if res.status != codes.RunResult.OK:
            ui.errors.Error(
                self, '%s: Compile Error (%s)' %
                (validator.src_name, res.status))
            ui.console.PrintLog(validator.ReadCompileLog())
            return False
        return True

    def _run_validators(self, ui):
        """Run input validators."""
        if not self.validators:
            # Ignore when this testset actually does not exist.
            if self.base_dir:
                ui.errors.Warning(self, 'Validator unavailable')
            return True

        testcases = self.ListTestCases()
        invalidcases = self.ListInvalidTestCases()
        results = []
        for validator in self.validators:
            for testcase in testcases:
                results.append(self._run_validator_one(
                    validator, testcase, ui))
            for invalidcase in invalidcases:
                results.append(self._run_validator_for_invalid_cases_one(
                    validator, invalidcase, ui))

        if not all(results):
            return False
        ui.console.PrintAction('VALIDATE', self, 'OK')
        return True

    def _run_validator_one(self, validator, testcase, ui):
        """Run an input validator against a single input file."""
        validationfile = (
            os.path.splitext(testcase.infile)[0] + consts.VALIDATION_EXT)
        res = validator.Run(
            args=(), cwd=self.out_dir,
            input=testcase.infile,
            output=validationfile,
            timeout=None, precise=False,
            redirect_error=True)
        if res.status == codes.RunResult.NG:
            ui.errors.Error(
                self, '%s: Validation Failed' %
                os.path.basename(testcase.infile))
            log = files.ReadFile(validationfile)
            ui.console.PrintLog(log)
            return False
        elif res.status != codes.RunResult.OK:
            ui.errors.Error(self,
                            '%s: Validator Failed: %s' %
                            (os.path.basename(testcase.infile), res.status))
            return False
        ui.console.PrintAction('VALIDATE', self,
                               '%s: PASSED' % os.path.basename(
                                   testcase.infile),
                               progress=True)
        return True

    def _compile_judges(self, ui):
        """Compile all judges."""
        results = []
        for judge in self.judges:
            results.append(self._compile_judge_one(judge, ui))
        if not all(results):
            return False

        results = []
        for reactive in self.reactives:
            results.append(self._compile_reactive_one(reactive, ui))
        return all(results)

    def _compile_judge_one(self, judge, ui):
        """Compile a single judge."""
        if not judge.QUIET_COMPILE:
            ui.console.PrintAction('COMPILE', self, judge.src_name)
        res = judge.Compile()
        if res.status != codes.RunResult.OK:
            ui.errors.Error(
                self, '%s: Compile Error (%s)' % (judge.src_name, res.status))
            ui.console.PrintLog(judge.ReadCompileLog())
            return False
        return True

    def _compile_reference_solution(self, ui):
        """Compile the reference solution."""
        reference_solution = self.problem.reference_solution
        if reference_solution is None:
            ui.errors.Error(self, 'Reference solution unavailable')
            return False
        return reference_solution.build(ui)

    def _compile_reactive_one(self, reactive, ui):
        """Compile a single reative."""
        if not reactive.QUIET_COMPILE:
            ui.console.PrintAction('COMPILE', self, reactive.src_name)
        res = reactive.Compile()
        if res.status != codes.RunResult.OK:
            ui.errors.Error(self, '%s: Compile Error (%s)'
                            % (reactive.src_name, res.status))
            ui.console.PrintLog(reactive.ReadCompileLog())
            return False
        return True

    def _run_reference_solution(self, ui):
        """Run the reference solution to generate reference outputs."""
        reference_solution = self.problem.reference_solution
        if reference_solution is None:
            ui.errors.Error(self, 'Reference solution unavailable')
            return False
        testcases = self.ListTestCases()
        results = []
        for testcase in testcases:
            results.append(self._run_reference_solution_one(
                reference_solution, testcase, ui))
        if not all(results):
            return False
        ui.console.PrintAction('REFRUN', reference_solution)
        return True

    def _run_reference_solution_one(self, reference_solution, testcase, ui):
        """Run the reference solution against a single input file."""
        if os.path.isfile(testcase.difffile):
            return True
        # reactive
        if self.reactives:
            if len(self.reactives) > 1:
                ui.errors.Error(self, "Multiple reactive checkers registered.")
                return None
            reactive = self.reactives[0]
            if not reactive.variant:
                reactive.variant = KUPCReactiveRunner()
            res = reactive.variant.Run(
                reactive=reactive,
                args=reference_solution.code.run_args,
                cwd=reference_solution.out_dir,
                input=testcase.infile,
                output=testcase.difffile,
                timeout=None, precise=False)
        else:
            res = reference_solution.Run(
                args=(), cwd=reference_solution.out_dir,
                input=testcase.infile,
                output=testcase.difffile,
                timeout=None, precise=False)
        if res.status != codes.RunResult.OK:
            ui.errors.Error(reference_solution, res.status)
            return False
        ui.console.PrintAction('REFRUN', reference_solution,
                               '%s: DONE' % os.path.basename(testcase.infile),
                               progress=True)
        return True

    def _post_build_hook(self, ui):
        results = []
        for testcase in self.GetMergedTestCases():
            results.append(self._generate_merged_test(testcase, ui))
        if not all(results):
            return False

        results = []
        for testcase in self.GetMergedTestCases():
            results.append(self._validate_merged_test(testcase, ui))
        if not all(results):
            return False

        return True

    def _generate_merged_test(self, merged_testcase, ui):
        if not self.test_merger:
            ui.errors.Error(self, "No merger registered!")
            return False

        testcases = [t for t in self.ListTestCases()
                     if fnmatch.fnmatch(os.path.basename(t.infile),
                                        merged_testcase.input_pattern)]
        self.test_merger.Run(testcases, merged_testcase, ui)
        return True

    def _validate_merged_test(self, merged_testcase, ui):
        if not self.validators:
            if self.base_dir:
                ui.errors.Warning(self, 'Validator unavailable')
            return True
        testcases = self.GetMergedTestCases()
        results = []
        for validator in self.validators:
            for testcase in testcases:
                results.append(self._run_validator_one(
                    validator, testcase, ui))

        if not all(results):
            return False
        ui.console.PrintAction('VALIDATE', self, 'OK Merged Cases')
        return True

    def test(self, ui):
        """Run tests in the testset."""
        results = []
        for solution in self.problem.solutions:
            results.append(self.test_solution(solution, ui))
        return results

    def test_solution(self, solution, ui):
        """Test a single solution."""
        if not self.build(ui):
            result = test.TestsetResult(self, solution, [])
            result.Finalize(False, 'Failed to build tests')
            return result
        if not solution.build(ui):
            result = test.TestsetResult(self, solution, [])
            result.Finalize(False, 'Compile Error')
            return result
        ui.console.PrintAction('TEST', solution, progress=True)
        if not solution.IsCorrect() and solution.challenge_cases:
            result = self._test_solution_with_challenge_cases(solution, ui)
        else:
            result = self._test_solution_with_all_cases(solution, ui)
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
        return result

    def _test_solution_with_challenge_cases(self, solution, ui):
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
                return result

            testcases.extend(
                [t for t in matched_testcases if t.infile not in testcases])
        # Try challenge cases.
        result = test.TestsetResult(self, solution, testcases)
        for testcase in testcases:
            case_result = self._test_solution_with_challenge_cases_one(
                solution, testcase, result, ui)
            if not case_result and not ui.options['keep_going']:
                break
        if not result.IsFinalized():
            result.Finalize(False,
                            'Unexpectedly accepted all challenge cases')
            ui.errors.Error(solution, result.detail)
        return result

    def _test_solution_with_challenge_cases_one(
            self, solution, testcase, result, ui):
        """Test a wrong solution which has specified challenge cases."""
        case_result = self._test_one_case(solution, testcase, ui)
        result.results[testcase] = case_result
        if not solution.verdicts.is_expected(case_result.verdict):
            result.Finalize(False,
                            '%s: Unexpected Verdict (%s)' %
                            (os.path.basename(testcase.infile),
                             case_result.verdict),
                            notable_testcase=testcase)
            ui.errors.Error(solution, result.detail)
            return False
        elif case_result.verdict not in ('WA', 'TLE', 'RE'):
            result.Finalize(False,
                            '%s: Judge Error' % os.path.basename(
                                testcase.infile),
                            notable_testcase=testcase)
            ui.errors.Error(solution, result.detail)
            return False
        ui.console.PrintAction('TEST', solution,
                               '%s: PASSED' % os.path.basename(
                                   testcase.infile),
                               progress=True)
        result.Finalize(True,
                        '%s: %s' % (os.path.basename(testcase.infile),
                                    case_result.verdict),
                        notable_testcase=testcase)
        return True

    def _test_solution_with_all_cases(self, solution, ui):
        """Test a solution without challenge cases.

        The solution can be marked as wrong but without challenge cases.
        """
        testcases = self.ListTestCases()
        result = test.TestsetResult(self, solution, testcases)
        # Try all cases.
        for testcase in testcases:
            case_result = self._test_solution_with_all_cases_one(
                solution, testcase, result, ui)
            if not case_result and not ui.options['keep_going']:
                break
        if not result.IsFinalized():
            if solution.IsCorrect():
                result.Finalize(True, result.GetTimeStats(ui))
            else:
                result.Finalize(False, 'Unexpectedly accepted all test cases')
                ui.errors.Error(solution, result.detail)

        original_result = result
        if (original_result.expected and
                solution.IsCorrect() and
                self.merged_testcases):
            merged_result = self._test_solution_with_merged_tests(solution, ui)
            original_result.results.update(merged_result.results)
            if not merged_result.expected:
                original_result.Finalize(
                    False, detail=merged_result.detail,
                    notable_testcase=merged_result.notable_testcase,
                    allow_override=True)
            else:
                if merged_result.IsTimingValid(ui):
                    detail = ('%s, %s' %
                              (original_result.detail,
                               ', '.join(['%s %.2fs' %
                                          (os.path.basename(t.infile),
                                           merged_result.results[t].time)
                                          for t in merged_result.testcases])))
                else:
                    detail = ('%s, %s' %
                              (original_result.detail,
                               ', '.join(['%s *.**s' %
                                          os.path.basename(t.infile)
                                          for t in merged_result.testcases])))
                original_result.Finalize(
                    True, detail=detail, allow_override=True)

        if self.subtask:
            max_score = 0
            min_score = 0

            for subtask in self.subtask:
                subtask_results = [
                    r for (t, r) in original_result.results.items()
                    if any([fnmatch.fnmatch(os.path.basename(t.infile),
                                            input_pattern)
                            for input_pattern in subtask.input_patterns])]
                accepted = all([result.verdict == 'AC'
                                for result in subtask_results
                                if result.verdict != 'NA'])
                unknown = any([result.verdict == 'NA'
                               for result in subtask_results])
                if accepted:
                    if not unknown:
                        min_score += subtask.score
                    max_score += subtask.score

            if min_score == max_score:
                detail = ('%s, score %s' % (original_result.detail, min_score))
            else:
                detail = ('%s, score %s <= x <= %s' %
                          (original_result.detail, min_score, max_score))
                ui.errors.Warning(
                    self,
                    "If you want more precise score, set keep_going option.")

            if solution.expected_score is not None:
                expected_result = (min_score <= solution.expected_score and
                                   solution.expected_score <= max_score)
                if expected_result:
                    original_result.Finalize(
                        True, detail=detail, allow_override=True)
                else:
                    original_result.Finalize(
                        False,
                        notable_testcase=test.TestCase(
                            self, 'unexpected_score.in'),
                        detail=detail, allow_override=True)
                    if min_score == max_score:
                        ui.errors.Error(self,
                                        'expected score %s does not equal to '
                                        '%s' %
                                        (solution.expected_score, min_score))
                    else:
                        ui.errors.Error(
                            self,
                            'expected score x = %s does not satisfy'
                            '%s <= x <= %s' %
                            (solution.expected_score, min_score, max_score))
            elif original_result.expected:
                original_result.Finalize(
                    True, detail=detail, allow_override=True)
            else:
                original_result.Finalize(
                    False,
                    notable_testcase=original_result.notable_testcase,
                    detail=detail, allow_override=True)

        elif original_result.IsAccepted() and self.scoring_judge:
            score = 0
            p = re.compile("IMOJUDGE<<<(\\d+)>>>")
            for (testcase, result) in original_result.results.items():
                judge_detail = files.ReadFile(
                    os.path.join(
                        solution.out_dir,
                        os.path.splitext(
                            os.path.basename(testcase.infile))[0] +
                        consts.JUDGE_EXT))
                if judge_detail:
                    judge_detail = judge_detail.strip()
                    if judge_detail.isdigit():
                        score += int(judge_detail)
                    elif p.search(judge_detail):
                        score += int(p.search(judge_detail).group(1))
                    else:
                        ui.errors.Error(
                            self,
                            'the judge result does not indicate a score:'
                            '"%s"' % (judge_detail))
                        original_result.Finalize(
                            False,
                            notable_testcase=test.TestCase(
                                self, 'judge_error.in'),
                            detail=original_result.detail, allow_override=True)
                        return original_result
                else:
                    ui.errors.Error(self, 'the judge is silent.')
                    original_result.Finalize(
                        False,
                        notable_testcase=test.TestCase(self, 'judge_error.in'),
                        detail=original_result.detail, allow_override=True)
                    return original_result
            score /= float(len(original_result.results))
            detail = ('%s, score %s' %
                      (original_result.detail, score))
            expected_result = score == solution.expected_score
            if expected_result or not solution.expected_score:
                original_result.Finalize(
                    True, detail=detail, allow_override=True)
            else:
                original_result.Finalize(
                    False,
                    notable_testcase=test.TestCase(
                        self, 'unexpected_score.in'),
                    detail=detail, allow_override=True)
                ui.errors.Error(self,
                                'expected score %d does not equal to %s' %
                                (solution.expected_score, score))
            original_result.Finalize(True, detail=detail, allow_override=True)
        return original_result

    def _test_solution_with_all_cases_one(
            self, solution, testcase, result, ui):
        """Test a solution without challenge cases.

        The solution can be marked as wrong but without challenge cases.
        """
        case_result = self._test_one_case(solution, testcase, ui)
        result.results[testcase] = case_result
        if case_result.verdict not in ('AC', 'WA', 'TLE', 'RE'):
            result.Finalize(False,
                            '%s: Judge Error' %
                            os.path.basename(testcase.infile),
                            notable_testcase=testcase)
            ui.errors.Error(solution, result.detail)
            return False
        elif case_result.verdict != 'AC':
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
                if case_result.verdict == 'WA':
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
            elif not solution.verdicts.is_expected(case_result.verdict):
                r = test.TestsetResult(
                    result.testset, result.solution, result.testcases)
                r.Finalize(False,
                           '%s: Unexpected Verdict (%s)' %
                           (os.path.basename(testcase.infile),
                            case_result.verdict),
                           notable_testcase=testcase)
                ui.errors.Error(solution, r.detail)
                if case_result.verdict == 'WA':
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
            return False
        ui.console.PrintAction('TEST', solution,
                               '%s: PASSED' % os.path.basename(
                                   testcase.infile),
                               progress=True)
        return True

    def _test_solution_with_merged_tests(self, solution, ui):
        testcases = self.GetMergedTestCases()
        result = test.TestsetResult(self, solution, testcases)
        # Try all cases.
        for testcase in testcases:
            result = self._test_solution_with_all_cases_one(
                solution, testcase, result, ui)
            if not result and not ui.options['keep_going']:
                break
        if not result.IsFinalized():
            result.Finalize(True, 'okay')
        return result

    def _test_one_case(self, solution, testcase, ui):
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
                    if verdict == j['verdict']][0]

            return case_result

        case_result = self._test_one_case_no_cache(solution, testcase, ui)

        # always cache in json
        files.WriteFile(json.dumps({
            'verdict': case_result.verdict,
            'time': case_result.time
        }), cache_file_name)

        return case_result

    def _test_one_case_no_cache(self, solution, testcase, ui):
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
                return
            reactive = self.reactives[0]
            if not reactive.variant:
                reactive.variant = KUPCReactiveRunner()
            res = reactive.variant.Run(
                reactive=reactive,
                args=solution.code.run_args, cwd=solution.out_dir,
                input=testcase.infile,
                output=outfile,
                timeout=testcase.timeout, precise=precise)
        else:
            res = solution.Run(
                args=(), cwd=solution.out_dir,
                input=testcase.infile,
                output=outfile,
                timeout=testcase.timeout, precise=precise)
        if res.status == codes.RunResult.TLE:
            return test.TestCaseResult(
                solution, 'TLE', time=None, cached=False)
        if res.status != codes.RunResult.OK:
            return test.TestCaseResult(
                solution, 'RE', time=None, cached=False)

        time = res.time
        for judge in self.judges:
            if not judge.variant:
                judge.variant = RimeJudgeRunner()
            res = judge.variant.Run(
                judge=judge,
                infile=testcase.infile,
                difffile=testcase.difffile,
                outfile=outfile,
                cwd=self.out_dir,
                judgefile=judgefile)
            if res.status == codes.RunResult.NG:
                return test.TestCaseResult(
                    solution, 'WA', time=None, cached=False)
            elif res.status != codes.RunResult.OK:
                return test.TestCaseResult(
                    solution, 'Validator %s' % res.status,
                    time=None, cached=False)
        return test.TestCaseResult(solution, 'AC',
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

    def _run_validator_for_invalid_cases_one(self, validator, testcase, ui):
        """Run an input validator against a single input file."""
        validationfile = (
            os.path.splitext(testcase.infile)[0] + consts.VALIDATION_EXT)
        res = validator.Run(
            args=(), cwd=self.out_dir,
            input=testcase.infile,
            output=validationfile,
            timeout=None, precise=False,
            redirect_error=True)
        if res.status == codes.RunResult.OK:
            ui.errors.Error(self,
                            '%s: Unexpectedly Validator Accepted: %s' %
                            (os.path.basename(testcase.infile), res.status))
            return False
        ui.console.PrintAction(
            'VALIDATE', self,
            '%s: Expectedly Failed' % os.path.basename(testcase.infile),
            progress=True)
        return True

    def Pack(self, ui):
        if not self.build(ui):
            return False
        if self.project.judge_system.name == 'AOJ':
            return commands.AOJPacker().Pack(ui, self)
        elif self.project.judge_system.name == 'AtCoder':
            return commands.AtCoderPacker().Pack(ui, self)
        elif self.project.judge_system.name == 'HackerRank':
            return commands.HackerRankPacker().Pack(ui, self)
        else:
            ui.errors.Error(self, "Pack nothing.")
            return False

    def clean(self, ui):
        """Clean the testset."""
        ui.console.PrintAction('CLEAN', self)
        try:
            files.RemoveTree(self.out_dir)
        except Exception:
            ui.errors.Exception(self)
            return False
        return True
