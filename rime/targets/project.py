import codecs
import getpass
import hashlib
import os
import re
import socket
import sys

from six.moves import http_cookiejar
from six.moves import urllib

from rime import codes
from rime import consts
from rime import target
from rime.targets.problem import Problem
from rime.util import files

if sys.version_info[0] == 2:
    import commands as builtin_commands  # NOQA
else:
    import subprocess as builtin_commands


# opener with cookiejar
cookiejar = http_cookiejar.CookieJar()
opener = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(cookiejar))

BGCOLOR_GOOD = 'BGCOLOR(#ccffcc):'
BGCOLOR_NOTBAD = 'BGCOLOR(#ffffcc):'
BGCOLOR_BAD = 'BGCOLOR(#ffcccc):'
BGCOLOR_NA = 'BGCOLOR(#cccccc):'

CELL_GOOD = BGCOLOR_GOOD + '&#x25cb;'
CELL_BAD = BGCOLOR_BAD + '&#xd7;'
CELL_NA = BGCOLOR_NA + '-'

HTMLIFY_BGCOLOR_GOOD = ' class="success">'
HTMLIFY_BGCOLOR_NOTBAD = ' class="warning">'
HTMLIFY_BGCOLOR_BAD = ' class="danger">'
HTMLIFY_BGCOLOR_NA = ' class="info">'

HTMLIFY_CELL_GOOD = HTMLIFY_BGCOLOR_GOOD + '&#x25cb;'
HTMLIFY_CELL_BAD = HTMLIFY_BGCOLOR_BAD + '&#xd7;'
HTMLIFY_CELL_NA = HTMLIFY_BGCOLOR_NA + '-'


def SafeUnicode(s):
    if sys.version_info.major == 2 and not isinstance(s, unicode):  # NOQA
        s = s.decode('utf-8')
    return s


def GetFileSize(dir, filename):
    filepath = os.path.join(dir, filename)
    if os.path.exists(filepath):
        return '%dB' % os.path.getsize(filepath)
    else:
        return '-'


def GetFileHash(dir, filename):
    filepath = os.path.join(dir, filename)
    if os.path.exists(filepath):
        f = open(filepath)
        r = f.read()
        f.close()
        return hashlib.md5(SafeUnicode(r).encode('utf-8')).hexdigest()
    else:
        return ''


def GetFileComment(dir, filename):
    filepath = os.path.join(dir, filename)
    if os.path.exists(filepath):
        f = open(filepath)
        r = f.read()
        f.close()
        return SafeUnicode(r).replace('\n', '&br;').replace('|', '&#x7c;')
    else:
        return ''


def GetHtmlifyFileComment(dir, filename):
    filepath = os.path.join(dir, filename)
    if os.path.exists(filepath):
        f = open(filepath)
        r = f.read().strip()
        f.close()
        return SafeUnicode(r).replace('\n', '<br>')
    else:
        return ''


class WikifyConfig(object):
    def __init__(self, config):
        self.url = config['url']
        self.page = config['page']
        self.encoding = config.get('encoding', 'utf-8')
        self.realm = config.get('realm')
        self.username = config.get('username')
        self.password = config.get('password')


class JudgeSystem(object):
    def __init__(self, config):
        if config is not None:
            self.name = config['name']
        else:
            self.name = None

        if self.name == 'AOJ':
            pass
        elif self.name == 'AtCoder':
            self.upload_script = config['upload_script']
            self.url = config['url']
            self.username = config['username']
            self.password = config['password']
            self.lang_ids = config['lang_ids']
            self.logined = False
        elif self.name == 'HackerRank':
            pass
        elif self.name is not None:
            raise target.ConfigurationError(
                'Unknown judge system: {}'.format(self.name))


class Project(target.TargetBase):
    """Project target."""

    CONFIG_FILENAME = 'project.json'

    def __init__(self, name, base_dir, parent):
        assert parent is None
        super(Project, self).__init__(name, base_dir, parent)
        self.project = self

    def PreLoad(self, ui, config):
        if 'library_dir' in config:
            self.library_dir = os.path.join(
                self.base_dir, config['library_dir'])
        else:
            self.library_dir = None

        if 'wikify_config' in config:
            self.wikify_config = WikifyConfig(config['wikify_config'])
        else:
            self.wikify_config = None

        self.judge_system = JudgeSystem(config.get('judge_system'))

    def PostLoad(self, ui):
        self._ChainLoad(ui)

    def _ChainLoad(self, ui):
        # Chain-load problems.
        self.problems = []
        for name in files.ListDir(self.base_dir):
            path = os.path.join(self.base_dir, name)
            if Problem.CanLoadFrom(path):
                problem = Problem(name, path, self)
                try:
                    problem.Load(ui)
                    self.problems.append(problem)
                except target.ConfigurationError:
                    ui.errors.Exception(problem)
        self.problems.sort(key=lambda a: (a.id, a.name))

    def FindByBaseDir(self, base_dir):
        if self.base_dir == base_dir:
            return self
        for problem in self.problems:
            obj = problem.FindByBaseDir(base_dir)
            if obj:
                return obj
        return None

    def build(self, ui):
        """Build all problems."""
        results = []
        for problem in self.problems:
            results.append(problem.build(ui))
        return all(results)

    def test(self, ui):
        """Run tests in the project."""
        results = []
        for problem in self.problems:
            results += problem.test(ui)
        return results

    def Pack(self, ui):
        results = []
        for problem in self.problems:
            results.append(problem.Pack(ui))
        return all(results)

    def Upload(self, ui):
        if self.judge_system.name == 'AtCoder':
            script = os.path.join(self.judge_system.upload_script)
            if not os.path.exists(os.path.join(self.base_dir, script)):
                ui.errors.Error(self, script + ' is not found.')
                return False

        results = []
        for problem in self.problems:
            results.append(problem.Upload(ui))
        return all(results)

    def _Request(self, path, data=None):
        if type(data) == dict:
            data = urllib.parse.urlencode(data).encode('utf-8')
        req = urllib.request.Request(self.judge_system.url + path, data)
        return opener.open(req)

    def _Login(self):
        if not self.judge_system.logined:
            self._Request('login',
                          {'name': self.judge_system.username,
                           'password': self.judge_system.password})
            self.judge_system.logined = True

    def Submit(self, ui):
        results = []
        for problem in self.problems:
            results.append(problem.Submit(ui))
        return all(results)

    def Add(self, args, ui):
        if len(args) != 2:
            return None
        ttype = args[0].lower()
        name = args[1]
        if ttype == 'problem':
            content = '''\
{
    time_limit=1.0
}
'''
            newdir = os.path.join(self.base_dir, name)
            if os.path.exists(newdir):
                ui.errors.Error(self, "{0} already exists.".format(newdir))
                return None
            os.makedirs(newdir)
            target.EditFile(os.path.join(newdir, 'PROBLEM'), content)
            ui.console.PrintAction('ADD', None, '%s/PROBLEM' % newdir)
        else:
            ui.errors.Error(self,
                            "Target type {0} cannot be put here.".format(
                                ttype))
            return None

    def Wikify(self, ui):
        if self.wikify_config is None:
            ui.errors.Error(self, 'wikify_config is not defined.')
            return None
        wiki = self._GenerateWiki(ui)
        self._UploadWiki(wiki, ui)
        return None

    def _GenerateWiki(self, ui):
        if not ui.options['skip_clean']:
            self.clean(ui)

        # Get system information.
        rev = builtin_commands.getoutput('svnversion')
        username = getpass.getuser()
        hostname = socket.gethostname()
        # Generate content.
        wiki = (u'このセクションは Rime により自動生成されています '
                u'(rev.%(rev)s, uploaded by %(username)s @ %(hostname)s)\n' %
                {'rev': rev, 'username': username, 'hostname': hostname})
        wiki += u'|||CENTER:|CENTER:|CENTER:|CENTER:|CENTER:|c\n'
        wiki += u'|~問題|~担当|~解答|~入力|~出力|~入検|~出検|\n'
        results = []
        for problem in self.problems:
            results.append(self._GenerateWikiOne(problem, ui))
        wiki += ''.join(results)
        return wiki

    def _GenerateWikiOne(self, problem, ui):
        # Get status.
        title = SafeUnicode(problem.wikify_config.title)
        page = SafeUnicode(problem.wikify_config.page)
        assignees = problem.wikify_config.assignees
        if isinstance(assignees, list):
            assignees = ','.join(assignees)
        assignees = SafeUnicode(assignees)
        # Fetch test results.
        results = problem.test(ui)
        # Get various information about the problem.
        num_solutions = len(results)
        num_tests = len(problem.testset.ListTestCases())
        correct_solution_results = [result for result in results
                                    if result.solution.IsCorrect()]
        num_corrects = len(correct_solution_results)
        num_incorrects = num_solutions - num_corrects
        num_agreed = len([result for result in correct_solution_results
                          if result.expected])
        need_custom_judge = problem.wikify_config.need_custom_judge
        # Solutions:
        if num_corrects >= 2:
            cell_solutions = BGCOLOR_GOOD
        elif num_corrects >= 1:
            cell_solutions = BGCOLOR_NOTBAD
        else:
            cell_solutions = BGCOLOR_BAD
        cell_solutions += '%d+%d' % (num_corrects, num_incorrects)
        # Input:
        if num_tests >= 20:
            cell_input = BGCOLOR_GOOD + str(num_tests)
        else:
            cell_input = BGCOLOR_BAD + str(num_tests)
        # Output:
        if num_corrects >= 2 and num_agreed == num_corrects:
            cell_output = BGCOLOR_GOOD
        elif num_agreed >= 2:
            cell_output = BGCOLOR_NOTBAD
        else:
            cell_output = BGCOLOR_BAD
        cell_output += '%d/%d' % (num_agreed, num_corrects)
        # Validator:
        if problem.testset.validators:
            cell_validator = CELL_GOOD
        else:
            cell_validator = CELL_BAD
        # Judge:
        if need_custom_judge:
            custom_judges = [
                judge for judge in problem.testset.judges
                if judge.__class__ != codes.InternalDiffCode]
            if custom_judges:
                cell_judge = CELL_GOOD
            else:
                cell_judge = CELL_BAD
        else:
            cell_judge = CELL_NA
        # Done.
        return (u'|[[{}>{}]]|{}|{}|{}|{}|{}|{}|\n'.format(
            title, page, assignees, cell_solutions, cell_input,
            cell_output, cell_validator, cell_judge))

    def _UploadWiki(self, wiki, ui):
        url = self.wikify_config.url
        page = SafeUnicode(self.wikify_config.page)
        encoding = self.wikify_config.encoding
        auth_realm = SafeUnicode(self.wikify_config.realm)
        auth_username = self.wikify_config.username
        auth_password = self.wikify_config.password
        auth_hostname = urllib.parse.urlparse(url).hostname

        native_page = page.encode(encoding)
        native_wiki = wiki.encode(encoding)

        if self.wikify_config.realm:
            auth_handler = urllib.request.HTTPBasicAuthHandler()
            auth_handler.add_password(
                auth_realm, auth_hostname, auth_username, auth_password)
            opener = urllib.request.build_opener(auth_handler)
            urllib.request.install_opener(opener)

        ui.console.PrintAction('UPLOAD', None, url)

        edit_params = {
            'cmd': 'edit',
            'page': native_page,
        }
        edit_page_content = urllib.request.urlopen(
            '%s?%s' % (url, urllib.parse.urlencode(edit_params))).read()

        digest = re.search(
            r'value="([0-9a-f]{32})"',
            edit_page_content.decode(encoding)).group(1)

        update_params = {
            'cmd': 'edit',
            'page': native_page,
            'digest': digest,
            'msg': native_wiki,
            'write': u'ページの更新'.encode(encoding),
            'encode_hint': u'ぷ'.encode(encoding),
        }
        urllib.request.urlopen(
            url, urllib.parse.urlencode(update_params).encode(encoding))

    def WikifyFull(self, ui):
        if self.wikify_config is None:
            ui.errors.Error(self, 'wikify_config is not defined.')
            return None
        wikiFull = self._GenerateWikiFull(ui)
        self._UploadWiki(wikiFull, ui)

    def _GenerateWikiFull(self, ui):
        if not ui.options['skip_clean']:
            self.clean(ui)

        # Get system information.
        rev = SafeUnicode(builtin_commands.getoutput(
            'git show -s --oneline').replace('\n', ' ').replace('\r', ' '))
        username = getpass.getuser()
        hostname = socket.gethostname()

        # Generate content.
        wiki = u'** Summary\n'
        wiki += u'|||CENTER:|CENTER:|CENTER:|CENTER:|CENTER:|c\n'
        wiki += u'|~問題|~担当|~解答|~入力|~出力|~入検|~出検|\n'

        wikiFull = u'** Detail\n'

        results = []
        for problem in self.problems:
            results.append(self._GenerateWikiFullOne(problem, ui))
        wikiResults, wikiFullResults = zip(*results)
        wiki += ''.join(wikiResults)
        wikiFull += ''.join(wikiFullResults)

        cc = os.getenv('CC', 'gcc')
        cxx = os.getenv('CXX', 'g++')
        java_home = os.getenv('JAVA_HOME')
        if java_home is not None:
            java = os.path.join(java_home, 'bin/java')
            javac = os.path.join(java_home, 'bin/javac')
        else:
            java = 'java'
            javac = 'javac'
        environments = '** Environments\n'
        environments += (
            ':gcc:|' + builtin_commands.getoutput(
                '{0} --version'.format(cc)) + '\n')
        environments += (
            ':g++:|' + builtin_commands.getoutput(
                '{0} --version'.format(cxx)) + '\n')
        environments += (
            ':javac:|' + builtin_commands.getoutput(
                '{0} -version'.format(javac)) + '\n')
        environments += (
            ':java:|' + builtin_commands.getoutput(
                '{0} -version'.format(java)) + '\n')

        errors = '** Error Messages\n'
        if ui.errors.HasError():
            errors += ':COLOR(red):ERROR:|\n'
            for e in ui.errors.errors:
                errors += '--' + e + '\n'
        if ui.errors.HasWarning():
            errors += ':COLOR(yellow):WARNING:|\n'
            for e in ui.errors.warnings:
                errors += '--' + e + '\n'
        errors = SafeUnicode(errors)

        return (u'#contents\n' +
                (u'このセクションは Rime により自動生成されています '
                 u'(rev.%(rev)s, uploaded by %(username)s @ %(hostname)s)\n' %
                 {'rev': rev, 'username': username, 'hostname': hostname})
                + wiki + environments + errors + wikiFull)

    def _GenerateWikiFullOne(self, problem, ui):
        result = problem.Build(ui)
        if not result:
            return False

        # Get status.
        title = SafeUnicode(problem.wikify_config.title)
        page = SafeUnicode(problem.wikify_config.page)
        assignees = problem.wikify_config.assignees
        if isinstance(assignees, list):
            assignees = ','.join(assignees)
        assignees = SafeUnicode(assignees)

        # Get various information about the problem.
        wikiFull = '***' + title + '\n'
        solutions = sorted(problem.solutions, key=lambda x: x.name)
        solutionnames = [solution.name for solution in solutions]
        captions = [name.replace('-', ' ').replace('_', ' ')
                    for name in solutionnames]
        wikiFull += '|CENTER:~' + '|CENTER:~'.join(
            ['testcase', 'in', 'diff', 'md5'] + captions +
            ['Comments']) + '|h\n'
        formats = ['RIGHT:' for solution in solutions]
        wikiFull += '|' + '|'.join(
            ['LEFT:', 'RIGHT:', 'RIGHT:', 'LEFT:'] + formats +
            ['LEFT:']) + '|c\n'

        dics = {}
        for testcase in problem.testset.ListTestCases():
            testname = os.path.splitext(os.path.basename(testcase.infile))[0]
            dics[testname] = {}
        results = []
        for solution in solutions:
            name = solution.name
            test_result = problem.testset.test_solution(solution, ui)[0]
            results.append(test_result)
            for testcase, result in test_result.results.items():
                testname = os.path.splitext(
                    os.path.basename(testcase.infile))[0]
                dics.setdefault(testname, {})[name] = (
                    result.verdict, result.time)
        testnames = sorted(dics.keys())
        lists = []
        for testname in testnames:
            cols = []
            for name in solutionnames:
                cols.append(dics[testname].get(name, ('NA', None)))
            lists.append((testname, cols))
        rows = []
        dir = problem.testset.out_dir
        for casename, cols in lists:
            rows.append(
                '|' +
                '|'.join(
                    [
                        casename.replace('_', ' ').replace('-', ' '),
                        GetFileSize(dir, casename + consts.IN_EXT),
                        GetFileSize(dir, casename + consts.DIFF_EXT),
                        GetFileHash(dir, casename + consts.IN_EXT)
                    ] +
                    [self._GetMessage(*t) for t in cols] +
                    [GetFileComment(dir, casename + '.comment')]
                ) +
                '|\n')
        wikiFull += ''.join(rows)

        # Get various information about the problem.
        num_solutions = len(results)
        num_tests = len(problem.testset.ListTestCases())
        correct_solution_results = [result for result in results
                                    if result.solution.IsCorrect()]
        num_corrects = len(correct_solution_results)
        num_incorrects = num_solutions - num_corrects
        num_agreed = len([result for result in correct_solution_results
                          if result.expected])
        need_custom_judge = problem.wikify_config.need_custom_judge

        # Solutions:
        if num_corrects >= 2:
            cell_solutions = BGCOLOR_GOOD
        elif num_corrects >= 1:
            cell_solutions = BGCOLOR_NOTBAD
        else:
            cell_solutions = BGCOLOR_BAD
        cell_solutions += '%d+%d' % (num_corrects, num_incorrects)

        # Input:
        if num_tests >= 20:
            cell_input = BGCOLOR_GOOD + str(num_tests)
        else:
            cell_input = BGCOLOR_BAD + str(num_tests)

        # Output:
        if num_corrects >= 2 and num_agreed == num_corrects:
            cell_output = BGCOLOR_GOOD
        elif num_agreed >= 2:
            cell_output = BGCOLOR_NOTBAD
        else:
            cell_output = BGCOLOR_BAD
        cell_output += '%d/%d' % (num_agreed, num_corrects)

        # Validator:
        if problem.testset.validators:
            cell_validator = CELL_GOOD
        else:
            cell_validator = CELL_BAD

        # Judge:
        if need_custom_judge:
            custom_judges = [
                judge for judge in problem.testset.judges
                if judge.__class__ != codes.InternalDiffCode]
            if custom_judges:
                cell_judge = CELL_GOOD
            else:
                cell_judge = CELL_BAD
        else:
            cell_judge = CELL_NA

        # Done.
        wiki = (u'|[[{}>{}]]|{}|{}|{}|{}|{}|{}|\n'.format(
            title, page, assignees, cell_solutions, cell_input,
            cell_output, cell_validator, cell_judge))

        return wiki, wikiFull

    def _GetMessage(self, verdict, time):
        if verdict == 'NA':
            return BGCOLOR_NA + str(verdict)
        elif time is None:
            return BGCOLOR_BAD + str(verdict)
        else:
            return BGCOLOR_GOOD + '%.2fs' % (time)

    def HtmlifyFull(self, ui):
        htmlFull = self._GenerateHtmlFull(ui)
        codecs.open("summary.html", 'w', 'utf8').write(htmlFull)

    def _GenerateHtmlFull(self, ui):
        if not ui.options['skip_clean']:
            self.clean(ui)

        # Get system information.
        rev = SafeUnicode(builtin_commands.getoutput(
            'git show -s --oneline').replace('\n', ' ').replace('\r', ' '))
        username = getpass.getuser()
        hostname = socket.gethostname()

        header = u'<!DOCTYPE html>\n<html lang="ja"><head>'
        header += (
            u'<meta charset="utf-8"/>'
            '<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com'
            '/bootstrap/3.2.0/css/bootstrap.min.css"></head>\n<body>')
        info = u'このセクションは Rime により自動生成されています '
        info += (u'(rev.%(rev)s, uploaded by %(username)s @ %(hostname)s)\n'
                 % {'rev': rev, 'username': username, 'hostname': hostname})
        footer = u'</body></html>'

        # Generate content.
        html = u'<h2>Summary</h2>\n<table class="table">\n'
        html += (u'<thead><tr><th>問題</th><th>担当</th><th>解答</th><th>入力</th>'
                 u'<th>出力</th><th>入検</th><th>出検</th></tr></thead>\n')

        htmlFull = u'<h2>Detail</h2>\n'

        results = []
        for problem in self.problems:
            results.append(self._GenerateHtmlFullOne(problem, ui))
        htmlResults, htmlFullResults = zip(*results)
        html += '<tbody>' + ''.join(htmlResults) + '</tbody></table>\n'
        htmlFull += ''.join(htmlFullResults)

        cc = os.getenv('CC', 'gcc')
        cxx = os.getenv('CXX', 'g++')
        java_home = os.getenv('JAVA_HOME')
        if java_home is not None:
            java = os.path.join(java_home, 'bin/java')
            javac = os.path.join(java_home, 'bin/javac')
        else:
            java = 'java'
            javac = 'javac'
        environments = '<h2>Environments</h2>\n<dl class="dl-horizontal">\n'
        environments += (
            '<dt>gcc:</dt><dd>' +
            builtin_commands.getoutput('{0} --version'.format(cc)) +
            '</dd>\n')
        environments += (
            '<dt>g++:</dt><dd>' +
            builtin_commands.getoutput('{0} --version'.format(cxx)) +
            '</dd>\n')
        environments += (
            '<dt>javac:</dt><dd>' +
            builtin_commands.getoutput('{0} -version'.format(javac)) +
            '</dd>\n')
        environments += (
            '<dt>java:</dt><dd>' +
            builtin_commands.getoutput('{0} -version'.format(java)) +
            '</dd>\n')
        environments += '</dl>\n'

        errors = ''
        if ui.errors.HasError() or ui.errors.HasWarning():
            errors = '<h2>Error Messages</h2>\n<dl class="dl-horizontal">\n'
            if ui.errors.HasError():
                errors += '<dt class="danger">ERROR:</dt><dd><ul>\n'
                for e in ui.errors.errors:
                    errors += '<li>' + e + '</li>\n'
                errors += '</ul></dd>\n'
            if ui.errors.HasWarning():
                errors += '<dt class="warning">WARNING:</dt><dd><ul>\n'
                for e in ui.errors.warnings:
                    errors += '<li>' + e + '</li>\n'
                errors += '</ul></dd>\n'
            errors += '</dl>\n'

        return header + info + html + environments + errors + htmlFull + footer

    def _GenerateHtmlFullOne(self, problem, ui):
        result = problem.build(ui)
        if not result:
            return False

        # Get status.
        title = SafeUnicode(problem.wikify_config.title)
        assignees = problem.wikify_config.assignees
        if isinstance(assignees, list):
            assignees = ','.join(assignees)
        assignees = SafeUnicode(assignees)

        # Get various information about the problem.
        htmlFull = '<h3>' + title + '</h3>\n'
        solutions = sorted(problem.solutions, key=lambda x: x.name)
        solutionnames = [solution.name for solution in solutions]

        captions = [
            name.replace('-', ' ').replace('_', ' ') for name in solutionnames]
        htmlFull += ('<table class="table">\n<thead><tr><th>' +
                     '</th><th>'.join(
                         ['testcase', 'in', 'diff', 'md5'] + captions +
                         ['Comments']) + '</th></tr></thead>\n<tbody>\n')

        dics = {}
        for testcase in problem.testset.ListTestCases():
            testname = os.path.splitext(os.path.basename(testcase.infile))[0]
            dics[testname] = {}
        results = []
        for solution in solutions:
            name = solution.name
            test_result = problem.testset.test_solution(solution, ui)[0]
            results.append(test_result)
            for testcase, result in test_result.results.items():
                testname = os.path.splitext(
                    os.path.basename(testcase.infile))[0]
                dics.setdefault(testname, {})[name] = (
                    result.verdict, result.time)
        testnames = sorted(dics.keys())
        lists = []
        for testname in testnames:
            cols = []
            for name in solutionnames:
                cols.append(dics[testname].get(name, ('NA', None)))
            lists.append((testname, cols))
        rows = []
        dir = problem.testset.out_dir
        for casename, cols in lists:
            rows.append(
                '<tr><td' +
                '</td><td'.join(
                    [
                        '>' + casename.replace('_', ' ').replace('-', ' '),
                        '>' + GetFileSize(dir, casename + consts.IN_EXT),
                        '>' + GetFileSize(dir, casename + consts.DIFF_EXT),
                        '>' + GetFileHash(dir, casename + consts.IN_EXT)
                    ] +
                    [self._GetHtmlifyMessage(*t) for t in cols] +
                    ['>' + GetHtmlifyFileComment(dir, casename + '.comment')]
                ) +
                '</td></tr>\n')
        htmlFull += ''.join(rows)
        htmlFull += '</tbody></table>'

        # Get various information about the problem.
        num_solutions = len(results)
        num_tests = len(problem.testset.ListTestCases())
        correct_solution_results = [result for result in results
                                    if result.solution.IsCorrect()]
        num_corrects = len(correct_solution_results)
        num_incorrects = num_solutions - num_corrects
        num_agreed = len([result for result in correct_solution_results
                          if result.expected])
        need_custom_judge = problem.wikify_config.need_custom_judge

        # Solutions:
        if num_corrects >= 2:
            cell_solutions = HTMLIFY_BGCOLOR_GOOD
        elif num_corrects >= 1:
            cell_solutions = HTMLIFY_BGCOLOR_NOTBAD
        else:
            cell_solutions = HTMLIFY_BGCOLOR_BAD
        cell_solutions += '%d+%d' % (num_corrects, num_incorrects)

        # Input:
        if num_tests >= 20:
            cell_input = HTMLIFY_BGCOLOR_GOOD + str(num_tests)
        else:
            cell_input = HTMLIFY_BGCOLOR_BAD + str(num_tests)

        # Output:
        if num_corrects >= 2 and num_agreed == num_corrects:
            cell_output = HTMLIFY_BGCOLOR_GOOD
        elif num_agreed >= 2:
            cell_output = HTMLIFY_BGCOLOR_NOTBAD
        else:
            cell_output = HTMLIFY_BGCOLOR_BAD
        cell_output += '%d/%d' % (num_agreed, num_corrects)

        # Validator:
        if problem.testset.validators:
            cell_validator = HTMLIFY_CELL_GOOD
        else:
            cell_validator = HTMLIFY_CELL_BAD

        # Judge:
        if need_custom_judge:
            custom_judges = [
                judge for judge in problem.testset.judges
                if judge.__class__ != codes.InternalDiffCode]
            if custom_judges:
                cell_judge = HTMLIFY_CELL_GOOD
            else:
                cell_judge = HTMLIFY_CELL_BAD
        else:
            cell_judge = HTMLIFY_CELL_NA

        # Done.
        html = ('<tr><td>{}</td><td>{}</td><td{}</td><td{}</td>'
                '<td{}</td><td{}</td><td{}<td></tr>\n'.format(
                    title, assignees, cell_solutions, cell_input,
                    cell_output, cell_validator, cell_judge))

        return html, htmlFull

    def _GetHtmlifyMessage(self, verdict, time):
        if verdict == 'NA':
            return HTMLIFY_BGCOLOR_NA + str(verdict)
        elif time is None:
            return HTMLIFY_BGCOLOR_BAD + str(verdict)
        else:
            return HTMLIFY_BGCOLOR_GOOD + '%.2fs' % (time)

    def clean(self, ui):
        """Clean the project."""
        results = [problem.clean(ui) for problem in self.problems]
        return all(results)
