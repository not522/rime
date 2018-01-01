#!/usr/bin/python
#
# Copyright (c) 2011 Rime Project.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#

import hashlib
import os.path

from rime.basic import consts
from rime.util import files


def PrintTestSummary(results, ui):
    if len(results) == 0:
        return

    PrintBuildSummary(results, ui)

    ui.console.Print()
    ui.console.Print(ui.console.BOLD, 'Test Summary:', ui.console.NORMAL)
    solution_name_width = max(
        map(lambda t: len(t.solution.name), results))
    last_problem = None
    for result in sorted(results, key=KeyTestResultForListing):
        if last_problem is not result.problem:
            problem_row = [
                ui.console.BOLD,
                ui.console.CYAN,
                result.problem.name,
                ui.console.NORMAL,
                ' ... %d solutions, %d tests' %
                (len(result.problem.solutions),
                 len(result.problem.testset.ListTestCases()))]
            ui.console.Print(*problem_row)
            last_problem = result.problem
        status_row = ['  ']
        status_row += [
            result.solution.IsCorrect() and ui.console.GREEN or
            ui.console.YELLOW,
            result.solution.name.ljust(solution_name_width),
            ui.console.NORMAL,
            ' ']
        if result.expected:
            status_row += [ui.console.GREEN, ' OK ', ui.console.NORMAL]
        else:
            status_row += [ui.console.RED, 'FAIL', ui.console.NORMAL]
        status_row += [' ', result.detail]
        if result.IsCached():
            status_row += [' ', '(cached)']
        ui.console.Print(*status_row)


def PrintBuildSummary(results, ui):
    if len(results) == 0:
        return
    ui.console.Print()
    ui.console.Print(ui.console.BOLD, 'Build Summary:', ui.console.NORMAL)
    solution_name_width = max(
        map(lambda t: len(t.solution.name), results))
    solution_prefix_width = max(
        map(lambda t: len(t.solution.code.PREFIX), results))
    solution_line_width = max(
        map(lambda t: len(_SolutionLine(t.solution)), results))
    solution_size_width = max(
        map(lambda t: len(_SolutionSize(t.solution)), results))
    last_problem = None
    for result in sorted(results, key=KeyTestResultForListing):
        if last_problem is not result.problem:
            problem_row = [
                ui.console.BOLD,
                ui.console.CYAN,
                result.problem.name,
                ui.console.NORMAL,
                ' ... in: %s, diff: %s, md5: %s' %
                (_TestsetInSize(result),
                 _TestsetDiffSize(result),
                 _TestsetHash(result)
                 )]
            ui.console.Print(*problem_row)
            last_problem = result.problem
        status_row = ['  ']
        status_row += [
            result.solution.IsCorrect() and ui.console.GREEN
            or ui.console.YELLOW,
            result.solution.name.ljust(solution_name_width),
            ' ',
            ui.console.GREEN,
            result.solution.code.PREFIX.upper().ljust(solution_prefix_width),
            ' ',
            ui.console.NORMAL,
            _SolutionLine(result.solution).rjust(solution_line_width),
            ', ',
            _SolutionSize(result.solution).rjust(solution_size_width)]
        ui.console.Print(*status_row)


def KeyTestResultForListing(a):
    """Key function of TestResult for display-ordering."""
    return (a.problem.id,
            a.problem.name,
            a.solution is not a.problem.reference_solution,
            not a.solution.IsCorrect(),
            a.solution.name)


def _TestsetHash(result):
    try:
        md5 = hashlib.md5()
        for t in result.problem.testset.ListTestCases():
            md5.update(files.ReadFile(t.infile))
        return md5.hexdigest()
    except Exception:
        return '-'


def _TestsetInSize(result):
    try:
        size = 0
        for t in result.problem.testset.ListTestCases():
            size += len(files.ReadFile(t.infile))
        return _SmartFileSize(size)
    except Exception:
        return '-'


def _TestsetDiffSize(result):
    try:
        size = 0
        for t in result.problem.testset.ListTestCases():
            out_file = os.path.join(
                result.problem.testset.out_dir,
                os.path.splitext(os.path.basename(t.infile))[0]
                + consts.DIFF_EXT)
            size += len(files.ReadFile(out_file))
        return _SmartFileSize(size)
    except Exception:
        return '-'


def _SolutionSize(solution):
    try:
        src = os.path.join(solution.src_dir, solution.code.src_name)
        return _SmartFileSize(len(files.ReadFile(src)))
    except Exception:
        return '-'


def _SolutionLine(solution):
    try:
        src = os.path.join(solution.src_dir, solution.code.src_name)
        return str(sum(1 for line in open(src))) + ' lines'
    except Exception:
        return '-'


def _SmartFileSize(size):
    if size < 1000:
        return str(size) + 'B'
    elif size < 1000000:
        return str(size // 100 * 0.1) + 'kB'
    else:
        return str(size // 100000 * 0.1) + 'MB'
