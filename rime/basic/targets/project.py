import itertools
import os
import sys

from rime.core import targets
from rime.core import taskgraph
from rime.util import files
from rime.util import module_loader


class Project(targets.TargetBase):
    """Project target.

    Project is the only target defined in rime.core. Here, only special methods
    which need to be cared in the core library are defined, e.g. use_plugin().
    """

    CONFIG_FILENAME = 'PROJECT'

    def __init__(self, name, base_dir, parent):
        assert parent is None
        super(Project, self).__init__(name, base_dir, parent)
        self.project = self

    def PreLoad(self, ui):
        # Do not use super() here because targets.Project will be overridden.
        targets.TargetBase.PreLoad(self, ui)

        def use_plugin(name):
            module_name = 'rime.plugins.%s' % name
            if module_name not in sys.modules:
                if not module_loader.LoadModule(module_name):
                    raise targets.ConfigurationError(
                        'Failed to load a plugin: %s' % name)
                raise targets.ReloadConfiguration(
                    'use_plugin(%s)' % repr(name))
        self.exports['use_plugin'] = use_plugin

        self.library_dir = None
        self.project_defined = False

        def _project(library_dir=None):
            if self.project_defined:
                raise RuntimeError('project() is already defined.')
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
    def Pack(self, ui):
        results = yield taskgraph.TaskBranch(
            [problem.Pack(ui) for problem in self.problems])
        yield all(results)

    @taskgraph.task_method
    def Upload(self, ui):
        results = yield taskgraph.TaskBranch(
            [problem.Upload(ui) for problem in self.problems])
        yield all(results)

    @taskgraph.task_method
    def Submit(self, ui):
        results = yield taskgraph.TaskBranch(
            [problem.Submit(ui) for problem in self.problems])
        yield all(results)

    @taskgraph.task_method
    def Add(self, args, ui):
        if len(args) != 2:
            yield None
        ttype = args[0].lower()
        name = args[1]
        if ttype == 'problem':
            content = '''\
pid='X'

problem(
  time_limit=1.0,
  id=pid,
  title=pid + ": Your Problem Name",
  #wiki_name="Your pukiwiki page name", # for wikify plugin
  #assignees=['Assignees', 'for', 'this', 'problem'], # for wikify plugin
  #need_custom_judge=True, # for wikify plugin
  #reference_solution='???',
  )

atcoder_config(
  task_id=None # None means a spare
)
'''
            newdir = os.path.join(self.base_dir, name)
            if(os.path.exists(newdir)):
                ui.errors.Error(self, "{0} already exists.".format(newdir))
                yield None
            os.makedirs(newdir)
            targets.EditFile(os.path.join(newdir, 'PROBLEM'), content)
            ui.console.PrintAction('ADD', None, '%s/PROBLEM' % newdir)
        else:
            ui.errors.Error(self,
                            "Target type {0} cannot be put here.".format(
                                ttype))
            yield None

    @taskgraph.task_method
    def Clean(self, ui):
        """Clean the project."""
        results = yield taskgraph.TaskBranch(
            [problem.Clean(ui) for problem in self.problems])
        yield all(results)


targets.registry.Add(Project)
