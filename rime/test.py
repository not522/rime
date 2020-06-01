import os.path

from rime import consts


class UnknownVerdictException(Exception):
    def __init__(self, verdict):
        self.verdict = verdict


class Verdicts(object):
    def __init__(self, verdicts):
        self.verdicts = []
        self.options = ['AC']
        if verdicts is None:
            return
        if not isinstance(verdicts, list):
            verdicts = [verdicts]
        for verdict in verdicts:
            if ':' in verdict:
                if verdict.count(':') != 1:
                    raise UnknownVerdictException(verdict)
                verdict, option = verdict.split(':')
                if not self._valid_verdict(verdict) or option != 'option':
                    raise UnknownVerdictException(verdict + ':' + option)
                self.options.append(verdict)
            else:
                if not self._valid_verdict(verdict):
                    raise UnknownVerdictException(verdict)
                self.verdicts.append(verdict)

    def _valid_verdict(self, verdict):
        return verdict in ('AC', 'WA', 'TLE', 'RE')

    def is_expected(self, verdict):
        return (verdict in self.verdicts) or (verdict in self.options)


class TestCase(object):

    def __init__(self, testset, infile, difffile=None):
        self.testset = testset
        self.infile = infile
        if difffile is None:
            self.difffile = os.path.splitext(infile)[0] + consts.DIFF_EXT
        else:
            self.difffile = difffile

    @property
    def timeout(self):
        return self.testset.problem.timeout


class TestCaseResult(object):
    """Testcase result."""

    def __init__(self, solution, verdict, time, cached):
        self.solution = solution
        self.verdict = verdict
        self.time = time
        self.cached = cached


class TestsetResult(object):
    """Testset result.

    This includes sub-results for each testcase.
    """

    def __init__(self, testset, solution, testcases):
        """Construct with empty results."""
        self.testset = testset
        self.problem = testset.problem
        self.solution = solution
        self.testcases = testcases
        self.results = dict(
            [(testcase,
              TestCaseResult(solution, 'NA', time=None, cached=False))
             for testcase in testcases])
        assert len(self.results) == len(testcases)
        self.finalized = False

    def IsFinalized(self):
        return self.finalized

    def Finalize(self, expected, detail, notable_testcase=None,
                 allow_override=False):
        if self.finalized and not allow_override:
            return
        self.expected = expected
        self.detail = detail
        self.notable_testcase = notable_testcase
        self.finalized = True

    def IsCached(self):
        return any((c.cached for c in self.results.values()))

    def IsAccepted(self):
        return all((c.verdict == 'AC' for c in self.results.values()))

    def IsTimingValid(self, ui):
        """Checks if timing stats are valid."""
        return (self.results and
                all((c.verdict == 'AC' for c in self.results.values())))

    def GetTimeStats(self, ui):
        """Get time statistics."""
        # TODO(nya): Concat support
        if not self.IsTimingValid(ui):
            return 'max *.**s, acc *.**s'
        return 'max %.2fs, acc %.2fs' % (
            self.GetMaxTime(), self.GetTotalTime())

    def GetMaxTime(self):
        """Get maximum time.

        All case should be accepted.
        """
        return max([c.time for _, c in self.results.items()])

    def GetTotalTime(self):
        """Get total time.

        All case should be accepted.
        """
        return sum([c.time for _, c in self.results.items()])
