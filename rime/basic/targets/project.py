import itertools
import os.path

from rime.core import targets
from rime.core import taskgraph
from rime.util import files

rime_plus_version = '1.0.0'
libdir = None


def parseVersion(v):
    return [int(d) for d in v.split('.')]


class Project(targets.registry.Project):
    """Project target."""

    CONFIG_FILENAME = 'PROJECT'

    def __init__(self, name, base_dir, parent):
        assert parent is None
        super(Project, self).__init__(name, base_dir, parent)
        self.project = self

    def PreLoad(self, ui):
        super(Project, self).PreLoad(ui)
        self.library_dir = None
        self.project_defined = False

        def _project(library_dir=None,
                     required_rime_plus_version=rime_plus_version):
            if self.project_defined:
                raise RuntimeError('project() is already defined.')
            if (parseVersion(rime_plus_version) <
                    parseVersion(required_rime_plus_version)):
                raise RuntimeError('installed rime-plus is too old.')
            global libdir
            libdir = os.path.join(
                self.base_dir,
                library_dir)
            self.library_dir = libdir
            self.project_defined = True
        self.exports['project'] = _project

    def PostLoad(self, ui):
        super(Project, self).PostLoad(ui)
        self._ChainLoad(ui)

    def _ChainLoad(self, ui):
        # Chain-load problems.
        self.problems = []
        for name in files.ListDir(self.base_dir):
            path = os.path.join(self.base_dir, name)
            if targets.registry.Problem.CanLoadFrom(path):
                problem = targets.registry.Problem(name, path, self)
                try:
                    problem.Load(ui)
                    self.problems.append(problem)
                except targets.ConfigurationError:
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

    @taskgraph.task_method
    def Build(self, ui):
        """Build all problems."""
        results = yield taskgraph.TaskBranch(
            [problem.Build(ui) for problem in self.problems])
        yield all(results)

    @taskgraph.task_method
    def Test(self, ui):
        """Run tests in the project."""
        results = yield taskgraph.TaskBranch(
            [problem.Test(ui) for problem in self.problems])
        yield list(itertools.chain(*results))

    @taskgraph.task_method
    def Clean(self, ui):
        """Clean the project."""
        results = yield taskgraph.TaskBranch(
            [problem.Clean(ui) for problem in self.problems])
        yield all(results)


targets.registry.Override('Project', Project)
